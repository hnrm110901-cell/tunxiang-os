"""delivery_window_service — 供应商配送时间窗硬约束（PRD-05 / Tier 1 食安）

核心业务逻辑：
  1. CRUD（草稿态 approved_by=NULL，必须独立 approve 才参与 check）
  2. 二级审批 approve_delivery_window（不允许 self-approve：approver_id != created_by）
  3. check_delivery_window — 签收时刻合规性检查
     - 按 weekday 位匹配（bit 0 = 周一 ... bit 6 = 周日）
     - grace_minutes 容忍：earliest - grace ≤ signed_at.time() ≤ latest + grace 算合规
     - 早到 / 晚到分别返回 violation_kind + violation_minutes
     - 未配置窗口时 within_window=True（fail-open — 无配置不阻塞收货）
  4. record_violation — 写违约日志（UNIQUE(tenant, receiving_order_id) 幂等）
  5. count_violations — supplier_scoring_engine 按 period 聚合扣分基础

设计要点：
  - RLS 标准模式：每次操作前 set_config('app.tenant_id', :tid, true)
  - lock 参数沿 PR-A/B/C/D/E 行锁 pattern（mutation 路径默认 False，调用方 lock=True）
  - raw SQL text() 路径与 yield_standard_service / weight_standard_service 对齐
  - signed_at 解读：store-local 时间（与 ReceivingOrder.signed_at 写入约定一致）
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Union

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

logger = structlog.get_logger(__name__)

_DBConn = Union[AsyncConnection, AsyncSession]


def _uuid_str(val: str | uuid.UUID) -> str:
    return str(val)


async def _set_tenant(db: _DBConn, tenant_id: str) -> None:
    """设置 RLS 租户上下文（与 yield_standard_service / weight_standard_service 同 pattern）。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


def _weekday_bit(d: datetime | date) -> int:
    """Monday=bit 0, Sunday=bit 6（与 Python date.weekday() 对齐）"""
    return 1 << d.weekday()


def _time_to_minutes(t: time) -> int:
    """将 TIME 转分钟数（00:00 = 0 ... 23:59 = 1439）"""
    return t.hour * 60 + t.minute


def _datetime_to_local_minutes(dt: datetime) -> int:
    """signed_at → 当日分钟数（按 dt 本身的 time 部分解读，与 store-local 约定一致）"""
    return dt.hour * 60 + dt.minute


# ─── CRUD ─────────────────────────────────────────────────────────────────────


async def list_delivery_windows(
    db: AsyncSession,
    tenant_id: str,
    supplier_id: str,
    *,
    store_id: Optional[str] = None,
    only_active: bool = True,
) -> list[dict]:
    """列出某 supplier 的配送时间窗。

    only_active=True 时：
      - approved_by IS NOT NULL（已审批生效）
      - is_deleted = FALSE
    only_active=False 时返回包含草稿/已删的所有记录（管理后台列表用）。
    """
    await _set_tenant(db, tenant_id)

    where_clauses = [
        "tenant_id = :tenant_id",
        "supplier_id = :supplier_id",
    ]
    if store_id is not None:
        where_clauses.append("store_id = :store_id")
    if only_active:
        where_clauses.append("approved_by IS NOT NULL")
        where_clauses.append("is_deleted = FALSE")

    where_sql = " AND ".join(where_clauses)
    sql = f"""
        SELECT
            id::text                AS id,
            tenant_id::text         AS tenant_id,
            supplier_id::text       AS supplier_id,
            store_id::text          AS store_id,
            weekday_mask,
            earliest_time,
            latest_time,
            grace_minutes,
            auto_reject_on_late,
            approved_by::text       AS approved_by,
            approved_at,
            notes,
            created_by::text        AS created_by,
            created_at,
            updated_at,
            is_deleted
        FROM supplier_delivery_windows
        WHERE {where_sql}
        ORDER BY created_at DESC
    """
    params: dict = {
        "tenant_id": _uuid_str(tenant_id),
        "supplier_id": _uuid_str(supplier_id),
    }
    if store_id is not None:
        params["store_id"] = _uuid_str(store_id)

    result = await db.execute(text(sql), params)
    return [dict(r) for r in result.mappings()]


async def get_delivery_window(
    db: AsyncSession,
    tenant_id: str,
    window_id: str,
    *,
    lock: bool = False,
) -> Optional[dict]:
    """单条时间窗查询。lock=True 加 FOR UPDATE 行锁（mutation 路径）。"""
    await _set_tenant(db, tenant_id)

    lock_clause = " FOR UPDATE" if lock else ""
    result = await db.execute(
        text(
            f"""
            SELECT
                id::text                AS id,
                tenant_id::text         AS tenant_id,
                supplier_id::text       AS supplier_id,
                store_id::text          AS store_id,
                weekday_mask,
                earliest_time,
                latest_time,
                grace_minutes,
                auto_reject_on_late,
                approved_by::text       AS approved_by,
                approved_at,
                notes,
                created_by::text        AS created_by,
                created_at,
                updated_at,
                is_deleted
            FROM supplier_delivery_windows
            WHERE id        = :window_id
              AND tenant_id = :tenant_id
              AND is_deleted = FALSE
            LIMIT 1{lock_clause}
            """
        ),
        {"window_id": window_id, "tenant_id": _uuid_str(tenant_id)},
    )
    row = result.mappings().first()
    return dict(row) if row is not None else None


async def create_delivery_window(
    db: AsyncSession,
    tenant_id: str,
    *,
    supplier_id: str,
    store_id: str,
    earliest_time: time,
    latest_time: time,
    created_by: str,
    weekday_mask: int = 127,
    grace_minutes: int = 15,
    auto_reject_on_late: bool = False,
    notes: Optional[str] = None,
) -> dict:
    """新建配送时间窗（草稿态 — approved_by=NULL，必须调 approve 才生效）。"""
    if earliest_time >= latest_time:
        raise ValueError("earliest_time 必须早于 latest_time")
    if weekday_mask < 1 or weekday_mask > 127:
        raise ValueError("weekday_mask 必须在 [1, 127] 范围")
    if grace_minutes < 0 or grace_minutes > 240:
        raise ValueError("grace_minutes 必须在 [0, 240] 范围")

    await _set_tenant(db, tenant_id)

    new_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    result = await db.execute(
        text(
            """
            INSERT INTO supplier_delivery_windows (
                id, tenant_id, supplier_id, store_id,
                weekday_mask, earliest_time, latest_time,
                grace_minutes, auto_reject_on_late,
                approved_by, approved_at,
                notes, created_by, created_at, updated_at, is_deleted
            )
            VALUES (
                :id, :tenant_id, :supplier_id, :store_id,
                :weekday_mask, :earliest_time, :latest_time,
                :grace_minutes, :auto_reject_on_late,
                NULL, NULL,
                :notes, :created_by, :now, :now, FALSE
            )
            RETURNING
                id::text                AS id,
                tenant_id::text         AS tenant_id,
                supplier_id::text       AS supplier_id,
                store_id::text          AS store_id,
                weekday_mask,
                earliest_time,
                latest_time,
                grace_minutes,
                auto_reject_on_late,
                approved_by::text       AS approved_by,
                approved_at,
                notes,
                created_by::text        AS created_by,
                created_at,
                updated_at,
                is_deleted
            """
        ),
        {
            "id": new_id,
            "tenant_id": _uuid_str(tenant_id),
            "supplier_id": _uuid_str(supplier_id),
            "store_id": _uuid_str(store_id),
            "weekday_mask": weekday_mask,
            "earliest_time": earliest_time,
            "latest_time": latest_time,
            "grace_minutes": grace_minutes,
            "auto_reject_on_late": auto_reject_on_late,
            "notes": notes,
            "created_by": _uuid_str(created_by),
            "now": now,
        },
    )
    row = result.mappings().first()
    if row is None:
        raise ValueError("create_delivery_window failed — RETURNING 无结果")

    logger.info(
        "delivery_window_created",
        window_id=new_id,
        tenant_id=str(tenant_id),
        supplier_id=str(supplier_id),
        store_id=str(store_id),
        weekday_mask=weekday_mask,
    )
    return dict(row)


async def approve_delivery_window(
    db: AsyncSession,
    tenant_id: str,
    window_id: str,
    approver_id: str,
) -> dict:
    """二级审批：approver_id 必须 != created_by（防 self-approve）。

    审批前 approved_by IS NULL（草稿态）；审批后 approved_by + approved_at 写入。
    UPDATE 路径用 FOR UPDATE 行锁串行化重复审批请求（与 yield_standard 同 pattern）。
    """
    await _set_tenant(db, tenant_id)

    # 先 lock=True 查到 created_by + approved_by 状态
    existing = await get_delivery_window(db, tenant_id, window_id, lock=True)
    if existing is None:
        raise ValueError(f"window_id={window_id} 不存在或已删除")

    if existing.get("approved_by") is not None:
        raise ValueError(f"window_id={window_id} 已审批，不能重复审批")

    if str(existing["created_by"]) == str(approver_id):
        raise ValueError(
            f"approver_id={approver_id} 不能与 created_by 相同（二级审批必须独立签字）"
        )

    now = datetime.now(timezone.utc)
    result = await db.execute(
        text(
            """
            UPDATE supplier_delivery_windows
            SET approved_by = :approver_id,
                approved_at = :now,
                updated_at  = :now
            WHERE id        = :window_id
              AND tenant_id = :tenant_id
              AND approved_by IS NULL
              AND is_deleted = FALSE
            RETURNING
                id::text                AS id,
                tenant_id::text         AS tenant_id,
                supplier_id::text       AS supplier_id,
                store_id::text          AS store_id,
                weekday_mask,
                earliest_time,
                latest_time,
                grace_minutes,
                auto_reject_on_late,
                approved_by::text       AS approved_by,
                approved_at,
                notes,
                created_by::text        AS created_by,
                created_at,
                updated_at,
                is_deleted
            """
        ),
        {
            "window_id": window_id,
            "tenant_id": _uuid_str(tenant_id),
            "approver_id": _uuid_str(approver_id),
            "now": now,
        },
    )
    row = result.mappings().first()
    if row is None:
        raise ValueError(
            f"approve_delivery_window failed — window_id={window_id} 并发已审批"
        )

    logger.info(
        "delivery_window_approved",
        window_id=window_id,
        tenant_id=str(tenant_id),
        approver_id=str(approver_id),
    )
    return dict(row)


async def soft_delete_delivery_window(
    db: AsyncSession,
    tenant_id: str,
    window_id: str,
) -> bool:
    """软删时间窗。软删后 check_delivery_window 不再使用此条配置。"""
    await _set_tenant(db, tenant_id)

    now = datetime.now(timezone.utc)
    result = await db.execute(
        text(
            """
            UPDATE supplier_delivery_windows
            SET is_deleted = TRUE,
                updated_at = :now
            WHERE id        = :window_id
              AND tenant_id = :tenant_id
              AND is_deleted = FALSE
            """
        ),
        {"window_id": window_id, "tenant_id": _uuid_str(tenant_id), "now": now},
    )
    affected = result.rowcount if result.rowcount is not None else 0
    deleted = affected > 0
    if deleted:
        logger.info(
            "delivery_window_soft_deleted",
            window_id=window_id,
            tenant_id=str(tenant_id),
        )
    return deleted


# ─── 时间窗合规性检查 ─────────────────────────────────────────────────────────


def _pick_window_for_weekday(
    windows: list[dict], weekday_bit: int
) -> Optional[dict]:
    """从 active windows 中按 weekday_mask 匹配挑一条。

    挑选规则：
      - weekday_mask & weekday_bit != 0 (位匹配该工作日)
      - 多条匹配时取 created_at 最近（list 已按 created_at DESC 排序）
    """
    for w in windows:
        if (w["weekday_mask"] & weekday_bit) != 0:
            return w
    return None


async def check_delivery_window(
    db: AsyncSession,
    tenant_id: str,
    *,
    supplier_id: str,
    store_id: str,
    signed_at: datetime,
) -> dict:
    """检查 signed_at 是否落在配送时间窗内（含 grace 容忍）。

    返回 dict 结构：
      {
        "within_window": bool,
        "window_id": Optional[str],
        "weekday_matched": bool,
        "scheduled_earliest": Optional[time],
        "scheduled_latest": Optional[time],
        "grace_minutes": Optional[int],
        "violation_minutes": int,   # 0 = 合规；>0 = 超出窗口分钟数
        "violation_kind": Optional[str],  # late / early / None
      }

    Fail-open 约定：
      - 未配置任何窗口 → within_window=True, weekday_matched=False（不阻塞收货）
      - 配置存在但 weekday 不匹配 → within_window=True, weekday_matched=False
      - 仅配置 weekday 匹配且时间超界才记违约
    """
    windows = await list_delivery_windows(
        db, tenant_id, supplier_id, store_id=store_id, only_active=True
    )

    if not windows:
        return {
            "within_window": True,
            "window_id": None,
            "weekday_matched": False,
            "scheduled_earliest": None,
            "scheduled_latest": None,
            "grace_minutes": None,
            "violation_minutes": 0,
            "violation_kind": None,
        }

    weekday_bit = _weekday_bit(signed_at)
    picked = _pick_window_for_weekday(windows, weekday_bit)

    if picked is None:
        return {
            "within_window": True,
            "window_id": None,
            "weekday_matched": False,
            "scheduled_earliest": None,
            "scheduled_latest": None,
            "grace_minutes": None,
            "violation_minutes": 0,
            "violation_kind": None,
        }

    earliest = picked["earliest_time"]
    latest = picked["latest_time"]
    grace = int(picked["grace_minutes"])

    signed_min = _datetime_to_local_minutes(signed_at)
    early_min = _time_to_minutes(earliest) - grace
    late_min = _time_to_minutes(latest) + grace

    if signed_min < early_min:
        violation_minutes = early_min - signed_min
        violation_kind = "early"
        within = False
    elif signed_min > late_min:
        violation_minutes = signed_min - late_min
        violation_kind = "late"
        within = False
    else:
        violation_minutes = 0
        violation_kind = None
        within = True

    return {
        "within_window": within,
        "window_id": picked["id"],
        "weekday_matched": True,
        "scheduled_earliest": earliest,
        "scheduled_latest": latest,
        "grace_minutes": grace,
        "violation_minutes": violation_minutes,
        "violation_kind": violation_kind,
    }


async def record_violation(
    db: AsyncSession,
    tenant_id: str,
    *,
    supplier_id: str,
    store_id: str,
    receiving_order_id: str,
    window_id: Optional[str],
    scheduled_earliest: time,
    scheduled_latest: time,
    actual_signed_at: datetime,
    violation_minutes: int,
    violation_kind: str,
) -> Optional[dict]:
    """写违约日志（UNIQUE(tenant_id, receiving_order_id) 保证幂等）。

    重复调用同一 receiving_order_id 时返回 None — supplier_scoring_engine 不会双计。
    """
    if violation_kind not in ("late", "early"):
        raise ValueError(f"未知 violation_kind={violation_kind!r}")
    if violation_minutes <= 0:
        raise ValueError("violation_minutes 必须 > 0")

    await _set_tenant(db, tenant_id)

    new_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    result = await db.execute(
        text(
            """
            INSERT INTO supplier_delivery_violations (
                id, tenant_id, supplier_id, store_id,
                receiving_order_id, window_id,
                scheduled_earliest, scheduled_latest,
                actual_signed_at, violation_minutes, violation_kind, recorded_at
            )
            VALUES (
                :id, :tenant_id, :supplier_id, :store_id,
                :receiving_order_id, :window_id,
                :scheduled_earliest, :scheduled_latest,
                :actual_signed_at, :violation_minutes, :violation_kind, :now
            )
            ON CONFLICT (tenant_id, receiving_order_id) DO NOTHING
            RETURNING
                id::text                    AS id,
                tenant_id::text             AS tenant_id,
                supplier_id::text           AS supplier_id,
                store_id::text              AS store_id,
                receiving_order_id::text    AS receiving_order_id,
                window_id::text             AS window_id,
                scheduled_earliest,
                scheduled_latest,
                actual_signed_at,
                violation_minutes,
                violation_kind,
                recorded_at
            """
        ),
        {
            "id": new_id,
            "tenant_id": _uuid_str(tenant_id),
            "supplier_id": _uuid_str(supplier_id),
            "store_id": _uuid_str(store_id),
            "receiving_order_id": _uuid_str(receiving_order_id),
            "window_id": _uuid_str(window_id) if window_id else None,
            "scheduled_earliest": scheduled_earliest,
            "scheduled_latest": scheduled_latest,
            "actual_signed_at": actual_signed_at,
            "violation_minutes": violation_minutes,
            "violation_kind": violation_kind,
            "now": now,
        },
    )
    row = result.mappings().first()
    if row is None:
        # ON CONFLICT DO NOTHING — 已存在记录
        logger.info(
            "delivery_violation_already_recorded",
            tenant_id=str(tenant_id),
            receiving_order_id=receiving_order_id,
        )
        return None

    logger.info(
        "delivery_violation_recorded",
        violation_id=new_id,
        tenant_id=str(tenant_id),
        supplier_id=str(supplier_id),
        receiving_order_id=receiving_order_id,
        violation_minutes=violation_minutes,
        violation_kind=violation_kind,
    )
    return dict(row)


async def count_violations(
    db: AsyncSession,
    tenant_id: str,
    supplier_id: str,
    *,
    period_start: date,
    period_end: date,
) -> int:
    """统计 supplier 在 [period_start, period_end] 区间内的违约次数。

    supplier_scoring_engine._aggregate_dimensions_from_db 调用此函数扣 delivery_rate 分。
    """
    await _set_tenant(db, tenant_id)

    result = await db.execute(
        text(
            """
            SELECT COUNT(*) AS cnt
            FROM supplier_delivery_violations
            WHERE tenant_id   = :tenant_id
              AND supplier_id = :supplier_id
              AND recorded_at::DATE BETWEEN :start AND :end
            """
        ),
        {
            "tenant_id": _uuid_str(tenant_id),
            "supplier_id": _uuid_str(supplier_id),
            "start": period_start,
            "end": period_end,
        },
    )
    row = result.mappings().first()
    return int(row["cnt"]) if row else 0
