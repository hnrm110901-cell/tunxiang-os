"""weight_standard_service — 商品扣秤标准库（PRD-02 / Tier 1 毛利底线）

核心业务逻辑：
  1. CRUD（草稿态 approved_by=NULL，必须独立 approve 才生效）
  2. 二级审批 approve_weight_standard（不允许 self-approve：approver_id != created_by）
  3. calculate_net_weight — 收货时按 active standards 自动扣秤
     - 多类扣秤项叠加（ice + packaging + leaves 多条同时应用）
     - actual_pct vs standard_pct 差超 tolerance_pct 时触发 anomaly callback
     - effective_from <= today AND (effective_to IS NULL OR today < effective_to)

设计要点：
  - RLS 标准模式：每次操作前 set_config('app.tenant_id', :tid, true)
  - lock 参数沿用 PR-A/B/C/D/E 行锁 pattern（mutation 路径默认 False，调用方 lock=True）
  - raw SQL text() 路径与 cert_service 对齐
  - 金额无关，weight 用 Decimal(10,4) kg
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Awaitable, Callable, Optional, Union

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

logger = structlog.get_logger(__name__)

_DBConn = Union[AsyncConnection, AsyncSession]

# 异常 callback 签名：接收 payload dict，返回 awaitable 或 None
AnomalyCallback = Callable[[dict], Optional[Awaitable[None]]]


def _uuid_str(val: str | uuid.UUID) -> str:
    return str(val)


async def _set_tenant(db: _DBConn, tenant_id: str) -> None:
    """设置 RLS 租户上下文（与 cert_service 同 pattern）。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


# ─── CRUD ─────────────────────────────────────────────────────────────────────


async def list_weight_standards(
    db: AsyncSession,
    tenant_id: str,
    ingredient_id: str,
    *,
    only_active: bool = True,
    today: Optional[date] = None,
) -> list[dict]:
    """列出某 ingredient 的扣秤标准。

    only_active=True 时：
      - approved_by IS NOT NULL（已审批生效）
      - is_deleted = FALSE
      - effective_from <= today AND (effective_to IS NULL OR today < effective_to)

    only_active=False 时返回包含草稿/已删的所有记录（管理后台列表用）。
    """
    await _set_tenant(db, tenant_id)

    today_val = today or date.today()
    where_clauses = [
        "tenant_id = :tenant_id",
        "ingredient_id = :ingredient_id",
    ]
    if only_active:
        where_clauses.append("approved_by IS NOT NULL")
        where_clauses.append("is_deleted = FALSE")
        where_clauses.append("effective_from <= :today")
        where_clauses.append("(effective_to IS NULL OR :today < effective_to)")

    where_sql = " AND ".join(where_clauses)
    sql = f"""
        SELECT
            id::text                   AS id,
            tenant_id::text            AS tenant_id,
            ingredient_id::text        AS ingredient_id,
            deduct_type,
            deduct_method,
            deduct_value,
            tolerance_pct,
            effective_from,
            effective_to,
            approved_by::text          AS approved_by,
            approved_at,
            notes,
            created_by::text           AS created_by,
            created_at,
            updated_at,
            is_deleted
        FROM ingredient_weight_standards
        WHERE {where_sql}
        ORDER BY effective_from DESC, created_at DESC
    """
    result = await db.execute(
        text(sql),
        {
            "tenant_id": _uuid_str(tenant_id),
            "ingredient_id": _uuid_str(ingredient_id),
            "today": today_val,
        },
    )
    return [dict(r) for r in result.mappings()]


async def get_weight_standard(
    db: AsyncSession,
    tenant_id: str,
    std_id: str,
    *,
    lock: bool = False,
) -> Optional[dict]:
    """单条扣秤标准查询。

    lock=True 时加 FOR UPDATE 行锁（mutation 路径 — approve / soft_delete 用）。
    沿用 PR-A/B/C/D/E row-lock pattern：read-only 入口 lock=False 默认。
    """
    await _set_tenant(db, tenant_id)

    lock_clause = " FOR UPDATE" if lock else ""
    result = await db.execute(
        text(
            f"""
            SELECT
                id::text                   AS id,
                tenant_id::text            AS tenant_id,
                ingredient_id::text        AS ingredient_id,
                deduct_type,
                deduct_method,
                deduct_value,
                tolerance_pct,
                effective_from,
                effective_to,
                approved_by::text          AS approved_by,
                approved_at,
                notes,
                created_by::text           AS created_by,
                created_at,
                updated_at,
                is_deleted
            FROM ingredient_weight_standards
            WHERE id        = :std_id
              AND tenant_id = :tenant_id
              AND is_deleted = FALSE
            LIMIT 1{lock_clause}
            """
        ),
        {"std_id": std_id, "tenant_id": _uuid_str(tenant_id)},
    )
    row = result.mappings().first()
    return dict(row) if row is not None else None


async def create_weight_standard(
    db: AsyncSession,
    tenant_id: str,
    *,
    ingredient_id: str,
    deduct_type: str,
    deduct_method: str,
    deduct_value: Decimal,
    effective_from: date,
    created_by: str,
    tolerance_pct: Decimal = Decimal("2.0"),
    effective_to: Optional[date] = None,
    notes: Optional[str] = None,
) -> dict:
    """新建扣秤标准（草稿态 — approved_by=NULL，必须调 approve 才生效）。"""
    if effective_to is not None and effective_to <= effective_from:
        raise ValueError("effective_to 必须晚于 effective_from")
    if deduct_value < 0:
        raise ValueError("deduct_value 不能为负")
    if tolerance_pct < 0 or tolerance_pct > 100:
        raise ValueError("tolerance_pct 必须在 [0, 100] 范围")

    await _set_tenant(db, tenant_id)

    new_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    result = await db.execute(
        text(
            """
            INSERT INTO ingredient_weight_standards (
                id, tenant_id, ingredient_id,
                deduct_type, deduct_method, deduct_value, tolerance_pct,
                effective_from, effective_to,
                approved_by, approved_at,
                notes, created_by, created_at, updated_at, is_deleted
            )
            VALUES (
                :id, :tenant_id, :ingredient_id,
                :deduct_type, :deduct_method, :deduct_value, :tolerance_pct,
                :effective_from, :effective_to,
                NULL, NULL,
                :notes, :created_by, :now, :now, FALSE
            )
            RETURNING
                id::text                   AS id,
                tenant_id::text            AS tenant_id,
                ingredient_id::text        AS ingredient_id,
                deduct_type,
                deduct_method,
                deduct_value,
                tolerance_pct,
                effective_from,
                effective_to,
                approved_by::text          AS approved_by,
                approved_at,
                notes,
                created_by::text           AS created_by,
                created_at,
                updated_at,
                is_deleted
            """
        ),
        {
            "id": new_id,
            "tenant_id": _uuid_str(tenant_id),
            "ingredient_id": _uuid_str(ingredient_id),
            "deduct_type": deduct_type,
            "deduct_method": deduct_method,
            "deduct_value": deduct_value,
            "tolerance_pct": tolerance_pct,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "notes": notes,
            "created_by": _uuid_str(created_by),
            "now": now,
        },
    )
    row = result.mappings().first()
    if row is None:
        raise ValueError("create_weight_standard failed — RETURNING 无结果")

    logger.info(
        "weight_standard_created",
        std_id=new_id,
        tenant_id=str(tenant_id),
        ingredient_id=str(ingredient_id),
        deduct_type=deduct_type,
        deduct_method=deduct_method,
    )
    return dict(row)


async def approve_weight_standard(
    db: AsyncSession,
    tenant_id: str,
    std_id: str,
    approver_id: str,
) -> dict:
    """二级审批：approver_id 必须 != created_by（防 self-approve）。

    审批前 approved_by IS NULL（草稿态）；审批后 approved_by + approved_at 写入。
    UPDATE 用 FOR UPDATE 行锁串行化重复审批请求。
    """
    await _set_tenant(db, tenant_id)

    # 先 lock=True 查到 created_by + approved_by 状态
    existing = await get_weight_standard(db, tenant_id, std_id, lock=True)
    if existing is None:
        raise ValueError(f"std_id={std_id} 不存在或已删除")

    if existing.get("approved_by") is not None:
        raise ValueError(f"std_id={std_id} 已审批，不能重复审批")

    if str(existing["created_by"]) == str(approver_id):
        raise ValueError(
            f"approver_id={approver_id} 不能与 created_by 相同（二级审批必须独立签字）"
        )

    now = datetime.now(timezone.utc)
    result = await db.execute(
        text(
            """
            UPDATE ingredient_weight_standards
            SET approved_by = :approver_id,
                approved_at = :now,
                updated_at  = :now
            WHERE id        = :std_id
              AND tenant_id = :tenant_id
              AND approved_by IS NULL
              AND is_deleted = FALSE
            RETURNING
                id::text                   AS id,
                tenant_id::text            AS tenant_id,
                ingredient_id::text        AS ingredient_id,
                deduct_type,
                deduct_method,
                deduct_value,
                tolerance_pct,
                effective_from,
                effective_to,
                approved_by::text          AS approved_by,
                approved_at,
                notes,
                created_by::text           AS created_by,
                created_at,
                updated_at,
                is_deleted
            """
        ),
        {
            "std_id": std_id,
            "tenant_id": _uuid_str(tenant_id),
            "approver_id": _uuid_str(approver_id),
            "now": now,
        },
    )
    row = result.mappings().first()
    if row is None:
        raise ValueError(f"approve_weight_standard failed — std_id={std_id} 并发已审批")

    logger.info(
        "weight_standard_approved",
        std_id=std_id,
        tenant_id=str(tenant_id),
        approver_id=str(approver_id),
    )
    return dict(row)


async def soft_delete_weight_standard(
    db: AsyncSession,
    tenant_id: str,
    std_id: str,
) -> bool:
    """软删扣秤标准。

    软删后 list_weight_standards(only_active=True) 不再返回，calculate_net_weight 自动忽略。
    """
    await _set_tenant(db, tenant_id)

    now = datetime.now(timezone.utc)
    result = await db.execute(
        text(
            """
            UPDATE ingredient_weight_standards
            SET is_deleted = TRUE,
                updated_at = :now
            WHERE id        = :std_id
              AND tenant_id = :tenant_id
              AND is_deleted = FALSE
            """
        ),
        {"std_id": std_id, "tenant_id": _uuid_str(tenant_id), "now": now},
    )
    affected = result.rowcount if result.rowcount is not None else 0
    deleted = affected > 0
    if deleted:
        logger.info(
            "weight_standard_soft_deleted",
            std_id=std_id,
            tenant_id=str(tenant_id),
        )
    return deleted


# ─── 自动扣秤计算 ─────────────────────────────────────────────────────────────


def _apply_deduction(gross_kg: Decimal, method: str, value: Decimal) -> Decimal:
    """单条 deduction 应用：返回扣减的 kg 数。

    percentage: gross * value / 100
    fixed_kg:   value（直接 kg）
    """
    if method == "percentage":
        return (gross_kg * value / Decimal("100")).quantize(Decimal("0.0001"))
    if method == "fixed_kg":
        return value.quantize(Decimal("0.0001"))
    raise ValueError(f"未知 deduct_method={method!r}")


async def calculate_net_weight(
    db: AsyncSession,
    tenant_id: str,
    ingredient_id: str,
    gross_weight_kg: Decimal,
    *,
    today: Optional[date] = None,
    actual_total_deduction_kg: Optional[Decimal] = None,
    on_anomaly_callback: Optional[AnomalyCallback] = None,
) -> tuple[Decimal, list[dict]]:
    """按 active standards 自动扣秤计算净重。

    GIVEN ingredient 的 active standards [ice 8%, packaging 0.3kg, leaves 12%]
          gross_weight_kg = 100kg
    THEN  按顺序叠加扣减 → net = gross - sum(deductions)
          返回 (net_weight_kg, applied_deductions)

    Anomaly 触发：actual_total_deduction_kg 给出时与 standard 计算值对比，
    差值超过 tolerance_pct（取所有 applied 中 max tolerance）时调 callback。
    """
    if gross_weight_kg <= 0:
        raise ValueError("gross_weight_kg 必须 > 0")

    standards = await list_weight_standards(
        db, tenant_id, ingredient_id, only_active=True, today=today
    )

    applied: list[dict] = []
    total_deduction = Decimal("0")
    max_tolerance = Decimal("0")

    for std in standards:
        method = std["deduct_method"]
        value = Decimal(str(std["deduct_value"]))
        tol = Decimal(str(std["tolerance_pct"]))
        ded_kg = _apply_deduction(gross_weight_kg, method, value)
        total_deduction += ded_kg
        if tol > max_tolerance:
            max_tolerance = tol
        applied.append(
            {
                "std_id": std["id"],
                "deduct_type": std["deduct_type"],
                "deduct_method": method,
                "deduct_value": str(value),
                "tolerance_pct": str(tol),
                "deduction_kg": str(ded_kg),
            }
        )

    # 净重不允许为负（扣秤超过毛重时强制夹到 0）
    if total_deduction > gross_weight_kg:
        logger.warning(
            "weight_deduction_exceeds_gross_clamped",
            tenant_id=str(tenant_id),
            ingredient_id=str(ingredient_id),
            gross_weight_kg=str(gross_weight_kg),
            total_deduction=str(total_deduction),
        )
        total_deduction = gross_weight_kg

    net_weight = (gross_weight_kg - total_deduction).quantize(Decimal("0.0001"))

    # Anomaly 检测：actual 与 standard 偏差超 max_tolerance
    if (
        actual_total_deduction_kg is not None
        and on_anomaly_callback is not None
        and standards
    ):
        # 偏差以毛重为基数的百分比
        diff_kg = (actual_total_deduction_kg - total_deduction).copy_abs()
        diff_pct = (diff_kg * Decimal("100") / gross_weight_kg).quantize(Decimal("0.01"))
        if diff_pct > max_tolerance:
            payload = {
                "ingredient_id": str(ingredient_id),
                "gross_weight_kg": str(gross_weight_kg),
                "standard_deduction_kg": str(total_deduction),
                "actual_deduction_kg": str(actual_total_deduction_kg),
                "diff_pct": str(diff_pct),
                "tolerance_pct": str(max_tolerance),
                "applied_standards": applied,
            }
            cb_result = on_anomaly_callback(payload)
            if cb_result is not None:
                await cb_result

    return net_weight, applied


# ─── 收货扣秤日志写入 ──────────────────────────────────────────────────────────


async def record_weight_deduction(
    db: AsyncSession,
    tenant_id: str,
    *,
    receiving_order_id: str,
    receiving_order_item_id: str,
    ingredient_id: str,
    gross_weight_kg: Decimal,
    net_weight_kg: Decimal,
    deductions: list[dict],
    anomaly_detected: bool = False,
) -> str:
    """写一行收货扣秤日志（receiving_weight_deductions）。返回新行 id。"""
    await _set_tenant(db, tenant_id)

    import json

    new_id = str(uuid.uuid4())
    await db.execute(
        text(
            """
            INSERT INTO receiving_weight_deductions (
                id, tenant_id, receiving_order_id, receiving_order_item_id,
                ingredient_id, gross_weight_kg, net_weight_kg, deductions,
                anomaly_detected, created_at
            )
            VALUES (
                :id, :tenant_id, :receiving_order_id, :receiving_order_item_id,
                :ingredient_id, :gross, :net, CAST(:deductions AS JSONB),
                :anomaly, NOW()
            )
            """
        ),
        {
            "id": new_id,
            "tenant_id": _uuid_str(tenant_id),
            "receiving_order_id": _uuid_str(receiving_order_id),
            "receiving_order_item_id": _uuid_str(receiving_order_item_id),
            "ingredient_id": _uuid_str(ingredient_id),
            "gross": gross_weight_kg,
            "net": net_weight_kg,
            "deductions": json.dumps(deductions),
            "anomaly": anomaly_detected,
        },
    )
    return new_id
