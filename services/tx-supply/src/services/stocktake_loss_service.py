"""盘亏处理审批闭环 Service — 案件 / 审批 / 核销

涵盖完整业务流程：
  盘点完成 → auto_create_loss_case_from_stocktake（金额超阈值才建案）
  手动建案 → create_loss_case
  追加明细 → add_items
  指派责任 → assign_responsibility
  提交审批 → submit_for_approval（按金额自动确定审批链长度）
  审批决策 → approve / reject（多节点状态机）
  财务核销 → writeoff（仅 APPROVED 可核销）
  查询统计 → list_cases / get_case_detail / get_loss_stats

关键约束：
  - 状态机严格单向（CaseStatus 枚举 + ALLOWED_TRANSITIONS 校验）
  - 金额单位全部为分（int / BIGINT）
  - 审批权限：approver_role 必须匹配当前节点要求
  - 事件总线：CASE_CREATED / SUBMITTED / APPROVED / REJECTED / WRITTEN_OFF
  - 案件号生成：调用 PG fn_next_loss_case_no(tenant_id, date) advisory lock
  - 审批链规则：< 5000 元（500000 分）= 1 节点；< 50000 元 = 2 节点；否则 = 3 节点
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import StocktakeLossEventType

# Imports work both in production (relative within tx-supply package) and in
# tests where src/ is added to sys.path directly. `models` becomes top-level.
try:
    from models.stocktake_loss import (  # type: ignore[no-redef]
        ALLOWED_TRANSITIONS,
        ApproverRole,
        CaseStatus,
        InvalidStateTransition,
        LossItemInput,
        ResponsiblePartyType,
    )
except ImportError:  # pragma: no cover
    from ..models.stocktake_loss import (  # type: ignore[no-redef]
        ALLOWED_TRANSITIONS,
        ApproverRole,
        CaseStatus,
        InvalidStateTransition,
        LossItemInput,
        ResponsiblePartyType,
    )

log = structlog.get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────
# 业务常量
# ─────────────────────────────────────────────────────────────────────

# 自动建案阈值：净亏损金额 >= 1000 元（100000 分）才建案
AUTO_CREATE_THRESHOLD_FEN: int = 100_000

# 审批链规则（按净亏损金额）
SMALL_AMOUNT_THRESHOLD_FEN: int = 500_000  # 5000 元
LARGE_AMOUNT_THRESHOLD_FEN: int = 5_000_000  # 50000 元


# ─────────────────────────────────────────────────────────────────────
# 业务异常
# ─────────────────────────────────────────────────────────────────────


class CaseNotFoundError(Exception):
    """案件不存在或不属于当前租户"""


class CaseValidationError(Exception):
    """案件入参非法（例如金额、责任方等）"""


class ApprovalPermissionError(Exception):
    """审批权限不匹配（approver_role 与当前节点不一致）"""


class WriteoffStateError(Exception):
    """核销时状态非法（仅 APPROVED 可核销）"""


# ─────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS 上下文 app.tenant_id"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


def _determine_approval_chain(net_loss_fen: int) -> list[ApproverRole]:
    """根据净亏损金额确定审批链节点（按业务约定）。

    < 5000 元（500000 分）       — 仅店长（1 节点）
    5000 - 50000 元              — 店长 + 区域经理（2 节点）
    > 50000 元（5000000 分）     — 店长 + 区域经理 + 财务（3 节点）
    """
    if net_loss_fen < SMALL_AMOUNT_THRESHOLD_FEN:
        return [ApproverRole.STORE_MANAGER]
    if net_loss_fen < LARGE_AMOUNT_THRESHOLD_FEN:
        return [ApproverRole.STORE_MANAGER, ApproverRole.REGIONAL_MANAGER]
    return [
        ApproverRole.STORE_MANAGER,
        ApproverRole.REGIONAL_MANAGER,
        ApproverRole.FINANCE,
    ]


def _emit_async(
    *,
    event_type: StocktakeLossEventType,
    tenant_id: str,
    stream_id: str,
    payload: dict[str, Any],
    store_id: Optional[str] = None,
    causation_id: Optional[str] = None,
) -> None:
    """通过 asyncio.create_task 旁路写入事件，不阻塞主流程。"""
    asyncio.create_task(
        emit_event(
            event_type=event_type,
            tenant_id=tenant_id,
            stream_id=stream_id,
            payload=payload,
            store_id=store_id,
            source_service="tx-supply",
            causation_id=causation_id,
        )
    )


async def _generate_case_no(
    db: AsyncSession,
    tenant_id: str,
    target_date: Optional[date] = None,
) -> str:
    """生成案件号：LOSS-YYYYMMDD-NNNN（PG 函数 + advisory lock 保证原子）。"""
    target_date = target_date or datetime.now(timezone.utc).date()
    result = await db.execute(
        text("SELECT fn_next_loss_case_no(:tid::uuid, :d::date) AS case_no"),
        {"tid": str(tenant_id), "d": target_date.isoformat()},
    )
    row = result.mappings().one()
    return str(row["case_no"])


async def _fetch_case_row(
    db: AsyncSession, case_id: str, tenant_id: str
) -> dict[str, Any]:
    """读取案件主表行（已设置 RLS 后调用）；不存在则抛 CaseNotFoundError。"""
    result = await db.execute(
        text("""
            SELECT id, tenant_id, stocktake_id, store_id, case_no,
                   total_loss_amount_fen, total_gain_amount_fen,
                   net_loss_amount_fen, responsible_party_type,
                   responsible_party_id, responsible_reason,
                   case_status, created_by, submitted_at,
                   final_approved_at, written_off_at,
                   created_at, updated_at, is_deleted
            FROM stocktake_loss_cases
            WHERE id = :cid::uuid AND tenant_id = :tid::uuid
              AND is_deleted = FALSE
        """),
        {"cid": case_id, "tid": tenant_id},
    )
    row = result.mappings().one_or_none()
    if not row:
        raise CaseNotFoundError(f"Case {case_id} not found for tenant {tenant_id}")
    return dict(row)


async def _transition_status(
    db: AsyncSession,
    case_id: str,
    tenant_id: str,
    target: CaseStatus,
    extra_columns: Optional[dict[str, Any]] = None,
) -> None:
    """状态机迁移（带合法性校验）；写 DB 并触发审计日志。"""
    case = await _fetch_case_row(db, case_id, tenant_id)
    current = CaseStatus(case["case_status"])
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise InvalidStateTransition(current, target)

    extra_columns = extra_columns or {}
    sets = ["case_status = :status"]
    params: dict[str, Any] = {
        "status": target.value,
        "cid": case_id,
        "tid": tenant_id,
    }
    for col, val in extra_columns.items():
        sets.append(f"{col} = :{col}")
        params[col] = val

    await db.execute(
        text(
            f"UPDATE stocktake_loss_cases "
            f"SET {', '.join(sets)} "
            f"WHERE id = :cid::uuid AND tenant_id = :tid::uuid"
        ),
        params,
    )
    log.info(
        "stocktake_loss.transition",
        case_id=case_id,
        from_status=current.value,
        to_status=target.value,
    )


# ─────────────────────────────────────────────────────────────────────
# 1. auto_create_loss_case_from_stocktake — 盘点完成钩子
# ─────────────────────────────────────────────────────────────────────


async def auto_create_loss_case_from_stocktake(
    stocktake_id: str,
    tenant_id: str,
    db: AsyncSession,
    *,
    created_by: str,
    threshold_fen: int = AUTO_CREATE_THRESHOLD_FEN,
) -> Optional[dict[str, Any]]:
    """盘点完成后自动建案（净亏损 >= threshold_fen 才建）。

    Returns:
        建案则返回案件 dict；金额未超阈值则返回 None。
    """
    await _set_tenant(db, tenant_id)

    # 校验 stocktake 存在并完成
    stocktake_row = await db.execute(
        text("""
            SELECT id, store_id, status
            FROM stocktakes
            WHERE id = :sid::uuid AND tenant_id = :tid::uuid
              AND is_deleted = FALSE
        """),
        {"sid": stocktake_id, "tid": tenant_id},
    )
    st = stocktake_row.mappings().one_or_none()
    if not st:
        raise CaseValidationError(f"Stocktake {stocktake_id} not found")
    if st["status"] != "completed":
        raise CaseValidationError(
            f"Stocktake must be completed before auto-create-case (got {st['status']})"
        )
    store_id = str(st["store_id"])

    # 拉取所有差异行（actual != expected 才纳入）
    items_result = await db.execute(
        text("""
            SELECT ingredient_id,
                   expected_qty,
                   actual_qty,
                   COALESCE(cost_price, 0) AS cost_price
            FROM stocktake_items
            WHERE stocktake_id = :sid::uuid AND tenant_id = :tid::uuid
              AND actual_qty IS NOT NULL
              AND ABS(actual_qty - expected_qty) > 0.001
              AND is_deleted = FALSE
        """),
        {"sid": stocktake_id, "tid": tenant_id},
    )
    diff_rows = items_result.mappings().all()

    total_loss_fen = 0
    total_gain_fen = 0
    items_payload: list[dict[str, Any]] = []
    for r in diff_rows:
        # 金额必须用 Decimal 才能避免分位浮点误差（宪法第十节硬约束）
        # cost_price 是 NUMERIC(10,4) 元，转回分用 Decimal * 100 再 int 截断
        # expected_qty / actual_qty 是 NUMERIC(14,3) — 也用 Decimal 算 diff
        expected = Decimal(str(r["expected_qty"]))
        actual = Decimal(str(r["actual_qty"]))
        diff = actual - expected
        unit_cost_fen = int(Decimal(str(r["cost_price"])) * 100)
        diff_amount_abs_fen = int(abs(diff) * unit_cost_fen)
        if diff < 0:  # 盘亏
            total_loss_fen += diff_amount_abs_fen
            sign = -1
        else:  # 盘盈
            total_gain_fen += diff_amount_abs_fen
            sign = 1

        items_payload.append(
            {
                "ingredient_id": str(r["ingredient_id"]),
                # API 层向后兼容：返回 float 便于 JSON 序列化（数量字段非金额）
                "expected_qty": float(expected),
                "actual_qty": float(actual),
                "unit_cost_fen": unit_cost_fen,
                "diff_amount_fen": sign * diff_amount_abs_fen,
            }
        )

    net_loss_fen = total_loss_fen - total_gain_fen
    if net_loss_fen < threshold_fen:
        log.info(
            "stocktake_loss.auto_create_skipped",
            stocktake_id=stocktake_id,
            net_loss_fen=net_loss_fen,
            threshold_fen=threshold_fen,
        )
        return None

    # 生成案件号 + INSERT 主记录
    case_id = str(uuid.uuid4())
    case_no = await _generate_case_no(db, tenant_id)
    now = datetime.now(timezone.utc)

    await db.execute(
        text("""
            INSERT INTO stocktake_loss_cases
                (id, tenant_id, stocktake_id, store_id, case_no,
                 total_loss_amount_fen, total_gain_amount_fen,
                 case_status, created_by, created_at, updated_at)
            VALUES
                (:id::uuid, :tid::uuid, :sid::uuid, :store_id::uuid, :case_no,
                 :loss, :gain,
                 'DRAFT', :created_by::uuid, :now, :now)
        """),
        {
            "id": case_id,
            "tid": tenant_id,
            "sid": stocktake_id,
            "store_id": store_id,
            "case_no": case_no,
            "loss": total_loss_fen,
            "gain": total_gain_fen,
            "created_by": created_by,
            "now": now,
        },
    )

    # 批量插明细
    for it in items_payload:
        await db.execute(
            text("""
                INSERT INTO stocktake_loss_items
                    (id, tenant_id, case_id, ingredient_id,
                     expected_qty, actual_qty, unit_cost_fen, diff_amount_fen,
                     created_at, updated_at)
                VALUES
                    (gen_random_uuid(), :tid::uuid, :cid::uuid, :ing::uuid,
                     :exp, :act, :cost, :diff, :now, :now)
            """),
            {
                "tid": tenant_id,
                "cid": case_id,
                "ing": it["ingredient_id"],
                "exp": it["expected_qty"],
                "act": it["actual_qty"],
                "cost": it["unit_cost_fen"],
                "diff": it["diff_amount_fen"],
                "now": now,
            },
        )

    await db.flush()

    # 事件：CASE_CREATED
    _emit_async(
        event_type=StocktakeLossEventType.CASE_CREATED,
        tenant_id=tenant_id,
        stream_id=case_id,
        payload={
            "case_no": case_no,
            "stocktake_id": stocktake_id,
            "store_id": store_id,
            "total_loss_amount_fen": total_loss_fen,
            "total_gain_amount_fen": total_gain_fen,
            "net_loss_amount_fen": net_loss_fen,
            "item_count": len(items_payload),
            "auto_created": True,
        },
        store_id=store_id,
        causation_id=stocktake_id,
    )

    log.info(
        "stocktake_loss.auto_created",
        case_id=case_id,
        case_no=case_no,
        net_loss_fen=net_loss_fen,
        item_count=len(items_payload),
    )

    return {
        "case_id": case_id,
        "case_no": case_no,
        "stocktake_id": stocktake_id,
        "store_id": store_id,
        "total_loss_amount_fen": total_loss_fen,
        "total_gain_amount_fen": total_gain_fen,
        "net_loss_amount_fen": net_loss_fen,
        "case_status": CaseStatus.DRAFT.value,
        "item_count": len(items_payload),
    }


# ─────────────────────────────────────────────────────────────────────
# 2. create_loss_case — 手动建案
# ─────────────────────────────────────────────────────────────────────


async def create_loss_case(
    *,
    tenant_id: str,
    stocktake_id: str,
    store_id: str,
    items: list[LossItemInput],
    created_by: str,
    db: AsyncSession,
    responsible_party_type: Optional[ResponsiblePartyType] = None,
    responsible_party_id: Optional[str] = None,
    responsible_reason: Optional[str] = None,
) -> dict[str, Any]:
    """手动登记盘亏案件（不依赖 stocktake 完成钩子）。"""
    await _set_tenant(db, tenant_id)

    case_id = str(uuid.uuid4())
    case_no = await _generate_case_no(db, tenant_id)
    now = datetime.now(timezone.utc)

    total_loss_fen = 0
    total_gain_fen = 0
    item_rows: list[dict[str, Any]] = []
    for it in items:
        diff = it.actual_qty - it.expected_qty
        diff_abs_fen = int(round(abs(diff) * it.unit_cost_fen))
        sign = -1 if diff < 0 else 1
        if diff < 0:
            total_loss_fen += diff_abs_fen
        elif diff > 0:
            total_gain_fen += diff_abs_fen
        item_rows.append(
            {
                "ingredient_id": it.ingredient_id,
                "batch_no": it.batch_no,
                "expected_qty": it.expected_qty,
                "actual_qty": it.actual_qty,
                "unit_cost_fen": it.unit_cost_fen,
                "diff_amount_fen": sign * diff_abs_fen,
                "reason_code": it.reason_code.value if it.reason_code else None,
                "reason_detail": it.reason_detail,
            }
        )

    await db.execute(
        text("""
            INSERT INTO stocktake_loss_cases
                (id, tenant_id, stocktake_id, store_id, case_no,
                 total_loss_amount_fen, total_gain_amount_fen,
                 responsible_party_type, responsible_party_id, responsible_reason,
                 case_status, created_by, created_at, updated_at)
            VALUES
                (:id::uuid, :tid::uuid, :sid::uuid, :store_id::uuid, :case_no,
                 :loss, :gain,
                 :rpt, :rpi, :rsn,
                 'DRAFT', :created_by::uuid, :now, :now)
        """),
        {
            "id": case_id,
            "tid": tenant_id,
            "sid": stocktake_id,
            "store_id": store_id,
            "case_no": case_no,
            "loss": total_loss_fen,
            "gain": total_gain_fen,
            "rpt": responsible_party_type.value if responsible_party_type else None,
            "rpi": responsible_party_id,
            "rsn": responsible_reason,
            "created_by": created_by,
            "now": now,
        },
    )

    for r in item_rows:
        await db.execute(
            text("""
                INSERT INTO stocktake_loss_items
                    (id, tenant_id, case_id, ingredient_id, batch_no,
                     expected_qty, actual_qty, unit_cost_fen, diff_amount_fen,
                     reason_code, reason_detail, created_at, updated_at)
                VALUES
                    (gen_random_uuid(), :tid::uuid, :cid::uuid, :ing::uuid, :batch,
                     :exp, :act, :cost, :diff,
                     :reason, :detail, :now, :now)
            """),
            {
                "tid": tenant_id,
                "cid": case_id,
                "ing": r["ingredient_id"],
                "batch": r["batch_no"],
                "exp": r["expected_qty"],
                "act": r["actual_qty"],
                "cost": r["unit_cost_fen"],
                "diff": r["diff_amount_fen"],
                "reason": r["reason_code"],
                "detail": r["reason_detail"],
                "now": now,
            },
        )

    await db.flush()

    net_loss_fen = total_loss_fen - total_gain_fen
    _emit_async(
        event_type=StocktakeLossEventType.CASE_CREATED,
        tenant_id=tenant_id,
        stream_id=case_id,
        payload={
            "case_no": case_no,
            "stocktake_id": stocktake_id,
            "store_id": store_id,
            "total_loss_amount_fen": total_loss_fen,
            "total_gain_amount_fen": total_gain_fen,
            "net_loss_amount_fen": net_loss_fen,
            "item_count": len(item_rows),
            "auto_created": False,
        },
        store_id=store_id,
        causation_id=stocktake_id,
    )

    log.info(
        "stocktake_loss.manual_created",
        case_id=case_id,
        case_no=case_no,
        net_loss_fen=net_loss_fen,
    )

    return {
        "case_id": case_id,
        "case_no": case_no,
        "stocktake_id": stocktake_id,
        "store_id": store_id,
        "total_loss_amount_fen": total_loss_fen,
        "total_gain_amount_fen": total_gain_fen,
        "net_loss_amount_fen": net_loss_fen,
        "case_status": CaseStatus.DRAFT.value,
        "item_count": len(item_rows),
    }


# ─────────────────────────────────────────────────────────────────────
# 3. add_items — 追加明细（仅 DRAFT 状态可追加）
# ─────────────────────────────────────────────────────────────────────


async def add_items(
    case_id: str,
    items: list[LossItemInput],
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """在 DRAFT 状态追加明细，并重算金额聚合。"""
    await _set_tenant(db, tenant_id)
    case = await _fetch_case_row(db, case_id, tenant_id)
    if case["case_status"] != CaseStatus.DRAFT.value:
        raise CaseValidationError(
            f"Cannot add items: case is {case['case_status']}, not DRAFT"
        )

    now = datetime.now(timezone.utc)
    add_loss = 0
    add_gain = 0
    for it in items:
        diff = it.actual_qty - it.expected_qty
        diff_abs_fen = int(round(abs(diff) * it.unit_cost_fen))
        sign = -1 if diff < 0 else 1
        if diff < 0:
            add_loss += diff_abs_fen
        elif diff > 0:
            add_gain += diff_abs_fen

        await db.execute(
            text("""
                INSERT INTO stocktake_loss_items
                    (id, tenant_id, case_id, ingredient_id, batch_no,
                     expected_qty, actual_qty, unit_cost_fen, diff_amount_fen,
                     reason_code, reason_detail, created_at, updated_at)
                VALUES
                    (gen_random_uuid(), :tid::uuid, :cid::uuid, :ing::uuid, :batch,
                     :exp, :act, :cost, :diff,
                     :reason, :detail, :now, :now)
            """),
            {
                "tid": tenant_id,
                "cid": case_id,
                "ing": it.ingredient_id,
                "batch": it.batch_no,
                "exp": it.expected_qty,
                "act": it.actual_qty,
                "cost": it.unit_cost_fen,
                "diff": sign * diff_abs_fen,
                "reason": it.reason_code.value if it.reason_code else None,
                "detail": it.reason_detail,
                "now": now,
            },
        )

    new_loss = case["total_loss_amount_fen"] + add_loss
    new_gain = case["total_gain_amount_fen"] + add_gain
    await db.execute(
        text("""
            UPDATE stocktake_loss_cases
            SET total_loss_amount_fen = :loss,
                total_gain_amount_fen = :gain
            WHERE id = :cid::uuid AND tenant_id = :tid::uuid
        """),
        {"loss": new_loss, "gain": new_gain, "cid": case_id, "tid": tenant_id},
    )
    await db.flush()

    return {
        "case_id": case_id,
        "added": len(items),
        "total_loss_amount_fen": new_loss,
        "total_gain_amount_fen": new_gain,
        "net_loss_amount_fen": new_loss - new_gain,
    }


# ─────────────────────────────────────────────────────────────────────
# 4. assign_responsibility
# ─────────────────────────────────────────────────────────────────────


async def assign_responsibility(
    case_id: str,
    party_type: ResponsiblePartyType,
    party_id: Optional[str],
    reason: Optional[str],
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """指派责任方（DRAFT 或 PENDING_APPROVAL 状态可改）。"""
    await _set_tenant(db, tenant_id)
    case = await _fetch_case_row(db, case_id, tenant_id)
    if case["case_status"] not in (
        CaseStatus.DRAFT.value,
        CaseStatus.PENDING_APPROVAL.value,
    ):
        raise CaseValidationError(
            f"Cannot reassign responsibility: case is {case['case_status']}"
        )

    await db.execute(
        text("""
            UPDATE stocktake_loss_cases
            SET responsible_party_type = :pt,
                responsible_party_id   = :pid,
                responsible_reason     = :rsn
            WHERE id = :cid::uuid AND tenant_id = :tid::uuid
        """),
        {
            "pt": party_type.value,
            "pid": party_id,
            "rsn": reason,
            "cid": case_id,
            "tid": tenant_id,
        },
    )
    await db.flush()
    return {
        "case_id": case_id,
        "responsible_party_type": party_type.value,
        "responsible_party_id": party_id,
        "responsible_reason": reason,
    }


# ─────────────────────────────────────────────────────────────────────
# 5. submit_for_approval — DRAFT → PENDING_APPROVAL（建审批节点）
# ─────────────────────────────────────────────────────────────────────


async def submit_for_approval(
    case_id: str,
    tenant_id: str,
    db: AsyncSession,
    *,
    submitted_by: str,
    approval_chain: Optional[list[ApproverRole]] = None,
) -> dict[str, Any]:
    """从 DRAFT 提交至 PENDING_APPROVAL，按金额自动产生审批链节点。

    若调用方提供 approval_chain，则使用该自定义链；否则按净亏损金额自动决策：
        < 5000 元（500000 分）       — STORE_MANAGER
        5000-50000 元                 — STORE_MANAGER → REGIONAL_MANAGER
        > 50000 元（5000000 分）     — STORE_MANAGER → REGIONAL_MANAGER → FINANCE
    """
    await _set_tenant(db, tenant_id)
    case = await _fetch_case_row(db, case_id, tenant_id)

    net_loss_fen = int(case["net_loss_amount_fen"] or 0)
    chain = approval_chain or _determine_approval_chain(net_loss_fen)
    if not chain:
        raise CaseValidationError("Approval chain cannot be empty")

    now = datetime.now(timezone.utc)

    # 状态机校验 + 写主记录
    await _transition_status(
        db,
        case_id,
        tenant_id,
        CaseStatus.PENDING_APPROVAL,
        extra_columns={"submitted_at": now},
    )

    # 写所有审批节点（decision = NULL，待审）
    for seq, role in enumerate(chain, start=1):
        await db.execute(
            text("""
                INSERT INTO stocktake_loss_approvals
                    (id, tenant_id, case_id, approval_node_seq, approver_role,
                     created_at, updated_at)
                VALUES
                    (gen_random_uuid(), :tid::uuid, :cid::uuid, :seq, :role,
                     :now, :now)
            """),
            {
                "tid": tenant_id,
                "cid": case_id,
                "seq": seq,
                "role": role.value,
                "now": now,
            },
        )

    await db.flush()

    _emit_async(
        event_type=StocktakeLossEventType.SUBMITTED,
        tenant_id=tenant_id,
        stream_id=case_id,
        payload={
            "case_no": case["case_no"],
            "store_id": str(case["store_id"]),
            "net_loss_amount_fen": net_loss_fen,
            "approval_chain": [r.value for r in chain],
            "submitted_by": submitted_by,
        },
        store_id=str(case["store_id"]),
    )

    log.info(
        "stocktake_loss.submitted",
        case_id=case_id,
        chain=[r.value for r in chain],
        net_loss_fen=net_loss_fen,
    )

    return {
        "case_id": case_id,
        "case_no": case["case_no"],
        "case_status": CaseStatus.PENDING_APPROVAL.value,
        "approval_chain": [r.value for r in chain],
        "current_node_seq": 1,
    }


# ─────────────────────────────────────────────────────────────────────
# 内部：定位当前待审批节点
# ─────────────────────────────────────────────────────────────────────


async def _find_current_pending_node(
    db: AsyncSession, case_id: str, tenant_id: str
) -> dict[str, Any]:
    """返回当前 decision IS NULL 的最小 seq 节点，找不到则抛 CaseValidationError。"""
    result = await db.execute(
        text("""
            SELECT id, approval_node_seq, approver_role
            FROM stocktake_loss_approvals
            WHERE case_id = :cid::uuid AND tenant_id = :tid::uuid
              AND decision IS NULL
              AND is_deleted = FALSE
            ORDER BY approval_node_seq ASC
            LIMIT 1
        """),
        {"cid": case_id, "tid": tenant_id},
    )
    row = result.mappings().one_or_none()
    if not row:
        raise CaseValidationError(f"No pending approval node for case {case_id}")
    return dict(row)


async def _is_last_node(
    db: AsyncSession, case_id: str, tenant_id: str, seq: int
) -> bool:
    """该节点是否是最后一个节点。"""
    result = await db.execute(
        text("""
            SELECT MAX(approval_node_seq) AS max_seq
            FROM stocktake_loss_approvals
            WHERE case_id = :cid::uuid AND tenant_id = :tid::uuid
              AND is_deleted = FALSE
        """),
        {"cid": case_id, "tid": tenant_id},
    )
    row = result.mappings().one()
    return int(row["max_seq"] or 0) == seq


# ─────────────────────────────────────────────────────────────────────
# 6. approve — 当前节点通过
# ─────────────────────────────────────────────────────────────────────


async def approve(
    case_id: str,
    approver_id: str,
    approver_role: ApproverRole,
    tenant_id: str,
    db: AsyncSession,
    *,
    comment: Optional[str] = None,
) -> dict[str, Any]:
    """当前待审批节点通过。

    - 校验 approver_role 与节点 approver_role 一致
    - 节点 decision = APPROVED；最后节点通过则状态 → APPROVED
    """
    await _set_tenant(db, tenant_id)
    case = await _fetch_case_row(db, case_id, tenant_id)
    if case["case_status"] != CaseStatus.PENDING_APPROVAL.value:
        raise CaseValidationError(
            f"Cannot approve: case is {case['case_status']}, not PENDING_APPROVAL"
        )

    node = await _find_current_pending_node(db, case_id, tenant_id)
    if node["approver_role"] != approver_role.value:
        raise ApprovalPermissionError(
            f"Role mismatch: node requires {node['approver_role']}, "
            f"got {approver_role.value}"
        )

    now = datetime.now(timezone.utc)
    await db.execute(
        text("""
            UPDATE stocktake_loss_approvals
            SET decision = 'APPROVED',
                approver_id = :aid::uuid,
                comment = :comment,
                approved_at = :now
            WHERE id = :nid::uuid AND tenant_id = :tid::uuid
        """),
        {
            "aid": approver_id,
            "comment": comment,
            "now": now,
            "nid": node["id"],
            "tid": tenant_id,
        },
    )

    is_last = await _is_last_node(
        db, case_id, tenant_id, int(node["approval_node_seq"])
    )

    if is_last:
        await _transition_status(
            db,
            case_id,
            tenant_id,
            CaseStatus.APPROVED,
            extra_columns={"final_approved_at": now},
        )
        _emit_async(
            event_type=StocktakeLossEventType.APPROVED,
            tenant_id=tenant_id,
            stream_id=case_id,
            payload={
                "case_no": case["case_no"],
                "store_id": str(case["store_id"]),
                "net_loss_amount_fen": int(case["net_loss_amount_fen"] or 0),
                "final_approver_id": approver_id,
                "final_approver_role": approver_role.value,
            },
            store_id=str(case["store_id"]),
        )
        new_status = CaseStatus.APPROVED.value
    else:
        new_status = CaseStatus.PENDING_APPROVAL.value

    await db.flush()

    log.info(
        "stocktake_loss.approved_node",
        case_id=case_id,
        node_seq=node["approval_node_seq"],
        approver_role=approver_role.value,
        is_last=is_last,
        new_status=new_status,
    )

    return {
        "case_id": case_id,
        "case_status": new_status,
        "approved_node_seq": int(node["approval_node_seq"]),
        "is_final": is_last,
    }


# ─────────────────────────────────────────────────────────────────────
# 7. reject — 任一节点驳回
# ─────────────────────────────────────────────────────────────────────


async def reject(
    case_id: str,
    approver_id: str,
    approver_role: ApproverRole,
    tenant_id: str,
    db: AsyncSession,
    *,
    comment: Optional[str] = None,
) -> dict[str, Any]:
    """任一节点驳回 → 状态变 REJECTED（终态）。"""
    await _set_tenant(db, tenant_id)
    case = await _fetch_case_row(db, case_id, tenant_id)
    if case["case_status"] != CaseStatus.PENDING_APPROVAL.value:
        raise CaseValidationError(
            f"Cannot reject: case is {case['case_status']}, not PENDING_APPROVAL"
        )

    node = await _find_current_pending_node(db, case_id, tenant_id)
    if node["approver_role"] != approver_role.value:
        raise ApprovalPermissionError(
            f"Role mismatch: node requires {node['approver_role']}, "
            f"got {approver_role.value}"
        )

    now = datetime.now(timezone.utc)
    await db.execute(
        text("""
            UPDATE stocktake_loss_approvals
            SET decision = 'REJECTED',
                approver_id = :aid::uuid,
                comment = :comment,
                approved_at = :now
            WHERE id = :nid::uuid AND tenant_id = :tid::uuid
        """),
        {
            "aid": approver_id,
            "comment": comment,
            "now": now,
            "nid": node["id"],
            "tid": tenant_id,
        },
    )

    await _transition_status(db, case_id, tenant_id, CaseStatus.REJECTED)
    await db.flush()

    _emit_async(
        event_type=StocktakeLossEventType.REJECTED,
        tenant_id=tenant_id,
        stream_id=case_id,
        payload={
            "case_no": case["case_no"],
            "store_id": str(case["store_id"]),
            "net_loss_amount_fen": int(case["net_loss_amount_fen"] or 0),
            "rejected_node_seq": int(node["approval_node_seq"]),
            "rejected_by": approver_id,
            "rejected_role": approver_role.value,
            "comment": comment,
        },
        store_id=str(case["store_id"]),
    )

    log.info(
        "stocktake_loss.rejected",
        case_id=case_id,
        node_seq=node["approval_node_seq"],
        approver_role=approver_role.value,
    )

    return {
        "case_id": case_id,
        "case_status": CaseStatus.REJECTED.value,
        "rejected_node_seq": int(node["approval_node_seq"]),
    }


# ─────────────────────────────────────────────────────────────────────
# 8. writeoff — 财务核销（仅 APPROVED 可核销）
# ─────────────────────────────────────────────────────────────────────


async def writeoff(
    case_id: str,
    *,
    writeoff_voucher_no: str,
    writeoff_amount_fen: int,
    accounting_subject: Optional[str],
    finance_user_id: str,
    tenant_id: str,
    db: AsyncSession,
    attachment_url: Optional[str] = None,
    comment: Optional[str] = None,
) -> dict[str, Any]:
    """财务核销 — 案件状态 APPROVED → WRITTEN_OFF；写凭证。"""
    await _set_tenant(db, tenant_id)
    case = await _fetch_case_row(db, case_id, tenant_id)
    if case["case_status"] != CaseStatus.APPROVED.value:
        raise WriteoffStateError(
            f"Cannot writeoff: case is {case['case_status']}, not APPROVED"
        )
    if writeoff_amount_fen <= 0:
        raise CaseValidationError("writeoff_amount_fen must be > 0")

    now = datetime.now(timezone.utc)
    writeoff_id = str(uuid.uuid4())

    await db.execute(
        text("""
            INSERT INTO stocktake_loss_writeoffs
                (id, tenant_id, case_id, writeoff_voucher_no,
                 writeoff_amount_fen, accounting_subject,
                 writeoff_at, finance_user_id, attachment_url, comment,
                 created_at, updated_at)
            VALUES
                (:id::uuid, :tid::uuid, :cid::uuid, :voucher,
                 :amount, :subject,
                 :now, :fuid::uuid, :att, :cmt,
                 :now, :now)
        """),
        {
            "id": writeoff_id,
            "tid": tenant_id,
            "cid": case_id,
            "voucher": writeoff_voucher_no,
            "amount": writeoff_amount_fen,
            "subject": accounting_subject or "管理费用-存货损失",
            "fuid": finance_user_id,
            "att": attachment_url,
            "cmt": comment,
            "now": now,
        },
    )

    await _transition_status(
        db,
        case_id,
        tenant_id,
        CaseStatus.WRITTEN_OFF,
        extra_columns={"written_off_at": now},
    )
    await db.flush()

    _emit_async(
        event_type=StocktakeLossEventType.WRITTEN_OFF,
        tenant_id=tenant_id,
        stream_id=case_id,
        payload={
            "case_no": case["case_no"],
            "store_id": str(case["store_id"]),
            "writeoff_voucher_no": writeoff_voucher_no,
            "writeoff_amount_fen": writeoff_amount_fen,
            "accounting_subject": accounting_subject or "管理费用-存货损失",
            "finance_user_id": finance_user_id,
        },
        store_id=str(case["store_id"]),
    )

    log.info(
        "stocktake_loss.written_off",
        case_id=case_id,
        voucher=writeoff_voucher_no,
        amount_fen=writeoff_amount_fen,
    )

    return {
        "case_id": case_id,
        "writeoff_id": writeoff_id,
        "case_status": CaseStatus.WRITTEN_OFF.value,
        "writeoff_voucher_no": writeoff_voucher_no,
        "writeoff_amount_fen": writeoff_amount_fen,
    }


# ─────────────────────────────────────────────────────────────────────
# 9. list_cases / get_case_detail
# ─────────────────────────────────────────────────────────────────────


async def list_cases(
    tenant_id: str,
    db: AsyncSession,
    *,
    status: Optional[CaseStatus] = None,
    store_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """列出案件（按 created_at DESC）。"""
    await _set_tenant(db, tenant_id)
    sql = """
        SELECT id, case_no, stocktake_id, store_id, case_status,
               total_loss_amount_fen, total_gain_amount_fen,
               net_loss_amount_fen, responsible_party_type,
               created_at, submitted_at, final_approved_at, written_off_at
        FROM stocktake_loss_cases
        WHERE tenant_id = :tid::uuid AND is_deleted = FALSE
    """
    params: dict[str, Any] = {"tid": tenant_id, "lim": limit, "off": offset}
    if status:
        sql += " AND case_status = :status"
        params["status"] = status.value
    if store_id:
        sql += " AND store_id = :sid::uuid"
        params["sid"] = store_id
    sql += " ORDER BY created_at DESC LIMIT :lim OFFSET :off"

    result = await db.execute(text(sql), params)
    rows = result.mappings().all()
    return {
        "items": [
            {
                "case_id": str(r["id"]),
                "case_no": r["case_no"],
                "stocktake_id": str(r["stocktake_id"]),
                "store_id": str(r["store_id"]),
                "case_status": r["case_status"],
                "total_loss_amount_fen": int(r["total_loss_amount_fen"]),
                "total_gain_amount_fen": int(r["total_gain_amount_fen"]),
                "net_loss_amount_fen": int(r["net_loss_amount_fen"] or 0),
                "responsible_party_type": r["responsible_party_type"],
                "created_at": r["created_at"].isoformat()
                if r["created_at"]
                else None,
                "submitted_at": r["submitted_at"].isoformat()
                if r["submitted_at"]
                else None,
                "final_approved_at": r["final_approved_at"].isoformat()
                if r["final_approved_at"]
                else None,
                "written_off_at": r["written_off_at"].isoformat()
                if r["written_off_at"]
                else None,
            }
            for r in rows
        ],
        "total": len(rows),
    }


async def get_case_detail(
    case_id: str, tenant_id: str, db: AsyncSession
) -> dict[str, Any]:
    """获取案件完整详情（含明细 + 审批节点 + 核销凭证）。"""
    await _set_tenant(db, tenant_id)
    case = await _fetch_case_row(db, case_id, tenant_id)

    items_res = await db.execute(
        text("""
            SELECT id, ingredient_id, batch_no,
                   expected_qty, actual_qty, diff_qty,
                   unit_cost_fen, diff_amount_fen,
                   reason_code, reason_detail, created_at
            FROM stocktake_loss_items
            WHERE case_id = :cid::uuid AND tenant_id = :tid::uuid
              AND is_deleted = FALSE
            ORDER BY created_at ASC
        """),
        {"cid": case_id, "tid": tenant_id},
    )
    approvals_res = await db.execute(
        text("""
            SELECT id, approval_node_seq, approver_role, approver_id,
                   decision, comment, approved_at, created_at
            FROM stocktake_loss_approvals
            WHERE case_id = :cid::uuid AND tenant_id = :tid::uuid
              AND is_deleted = FALSE
            ORDER BY approval_node_seq ASC
        """),
        {"cid": case_id, "tid": tenant_id},
    )
    writeoffs_res = await db.execute(
        text("""
            SELECT id, writeoff_voucher_no, writeoff_amount_fen,
                   accounting_subject, writeoff_at, finance_user_id,
                   attachment_url, comment
            FROM stocktake_loss_writeoffs
            WHERE case_id = :cid::uuid AND tenant_id = :tid::uuid
              AND is_deleted = FALSE
            ORDER BY writeoff_at DESC
        """),
        {"cid": case_id, "tid": tenant_id},
    )

    return {
        "case": {
            "case_id": str(case["id"]),
            "case_no": case["case_no"],
            "stocktake_id": str(case["stocktake_id"]),
            "store_id": str(case["store_id"]),
            "case_status": case["case_status"],
            "total_loss_amount_fen": int(case["total_loss_amount_fen"]),
            "total_gain_amount_fen": int(case["total_gain_amount_fen"]),
            "net_loss_amount_fen": int(case["net_loss_amount_fen"] or 0),
            "responsible_party_type": case["responsible_party_type"],
            "responsible_party_id": str(case["responsible_party_id"])
            if case["responsible_party_id"]
            else None,
            "responsible_reason": case["responsible_reason"],
            "created_at": case["created_at"].isoformat()
            if case["created_at"]
            else None,
            "submitted_at": case["submitted_at"].isoformat()
            if case["submitted_at"]
            else None,
            "final_approved_at": case["final_approved_at"].isoformat()
            if case["final_approved_at"]
            else None,
            "written_off_at": case["written_off_at"].isoformat()
            if case["written_off_at"]
            else None,
        },
        "items": [
            {
                "item_id": str(r["id"]),
                "ingredient_id": str(r["ingredient_id"]),
                "batch_no": r["batch_no"],
                "expected_qty": float(r["expected_qty"]),
                "actual_qty": float(r["actual_qty"]),
                "diff_qty": float(r["diff_qty"]) if r["diff_qty"] is not None else 0.0,
                "unit_cost_fen": int(r["unit_cost_fen"]),
                "diff_amount_fen": int(r["diff_amount_fen"]),
                "reason_code": r["reason_code"],
                "reason_detail": r["reason_detail"],
            }
            for r in items_res.mappings().all()
        ],
        "approvals": [
            {
                "approval_id": str(r["id"]),
                "approval_node_seq": int(r["approval_node_seq"]),
                "approver_role": r["approver_role"],
                "approver_id": str(r["approver_id"]) if r["approver_id"] else None,
                "decision": r["decision"],
                "comment": r["comment"],
                "approved_at": r["approved_at"].isoformat()
                if r["approved_at"]
                else None,
            }
            for r in approvals_res.mappings().all()
        ],
        "writeoffs": [
            {
                "writeoff_id": str(r["id"]),
                "writeoff_voucher_no": r["writeoff_voucher_no"],
                "writeoff_amount_fen": int(r["writeoff_amount_fen"]),
                "accounting_subject": r["accounting_subject"],
                "writeoff_at": r["writeoff_at"].isoformat()
                if r["writeoff_at"]
                else None,
                "finance_user_id": str(r["finance_user_id"]),
                "attachment_url": r["attachment_url"],
                "comment": r["comment"],
            }
            for r in writeoffs_res.mappings().all()
        ],
    }


# ─────────────────────────────────────────────────────────────────────
# 10. get_loss_stats — 损失统计
# ─────────────────────────────────────────────────────────────────────


async def get_loss_stats(
    tenant_id: str,
    db: AsyncSession,
    *,
    from_date: str,
    to_date: str,
    store_id: Optional[str] = None,
) -> dict[str, Any]:
    """损失统计 — 按原因 / 责任方 / 门店三个维度聚合。

    时间范围按 created_at 过滤；只统计未删除案件。
    """
    await _set_tenant(db, tenant_id)

    base_filter = """
        WHERE c.tenant_id = :tid::uuid AND c.is_deleted = FALSE
          AND c.created_at >= :from_date::timestamptz
          AND c.created_at < (:to_date::date + INTERVAL '1 day')
    """
    params: dict[str, Any] = {
        "tid": tenant_id,
        "from_date": from_date,
        "to_date": to_date,
    }
    if store_id:
        base_filter += " AND c.store_id = :sid::uuid"
        params["sid"] = store_id

    # 总览
    total_res = await db.execute(
        text(
            f"""
            SELECT COUNT(*) AS case_count,
                   COALESCE(SUM(c.total_loss_amount_fen), 0) AS total_loss,
                   COALESCE(SUM(c.total_gain_amount_fen), 0) AS total_gain,
                   COALESCE(SUM(c.net_loss_amount_fen), 0) AS net_loss
            FROM stocktake_loss_cases c
            {base_filter}
            """
        ),
        params,
    )
    total = total_res.mappings().one()

    # 按状态
    by_status_res = await db.execute(
        text(
            f"""
            SELECT c.case_status,
                   COUNT(*) AS case_count,
                   COALESCE(SUM(c.net_loss_amount_fen), 0) AS net_loss
            FROM stocktake_loss_cases c
            {base_filter}
            GROUP BY c.case_status
            ORDER BY net_loss DESC
            """
        ),
        params,
    )

    # 按责任方
    by_party_res = await db.execute(
        text(
            f"""
            SELECT COALESCE(c.responsible_party_type, 'UNASSIGNED') AS party_type,
                   COUNT(*) AS case_count,
                   COALESCE(SUM(c.net_loss_amount_fen), 0) AS net_loss
            FROM stocktake_loss_cases c
            {base_filter}
            GROUP BY c.responsible_party_type
            ORDER BY net_loss DESC
            """
        ),
        params,
    )

    # 按门店
    by_store_res = await db.execute(
        text(
            f"""
            SELECT c.store_id,
                   COUNT(*) AS case_count,
                   COALESCE(SUM(c.net_loss_amount_fen), 0) AS net_loss
            FROM stocktake_loss_cases c
            {base_filter}
            GROUP BY c.store_id
            ORDER BY net_loss DESC
            LIMIT 20
            """
        ),
        params,
    )

    # 按原因（基于 items 表聚合差异金额）
    item_filter = base_filter.replace("c.is_deleted", "i.is_deleted")
    # 修正：i 上没有 created_at；用 c.created_at 即可
    by_reason_res = await db.execute(
        text(
            f"""
            SELECT COALESCE(i.reason_code, 'UNCATEGORIZED') AS reason_code,
                   COUNT(i.id) AS item_count,
                   COALESCE(SUM(ABS(i.diff_amount_fen)), 0) AS amount_fen
            FROM stocktake_loss_items i
            JOIN stocktake_loss_cases c ON c.id = i.case_id AND c.tenant_id = i.tenant_id
            {base_filter}
              AND i.tenant_id = :tid::uuid
            GROUP BY i.reason_code
            ORDER BY amount_fen DESC
            """
        ),
        params,
    )

    return {
        "total": {
            "case_count": int(total["case_count"]),
            "total_loss_amount_fen": int(total["total_loss"]),
            "total_gain_amount_fen": int(total["total_gain"]),
            "net_loss_amount_fen": int(total["net_loss"]),
        },
        "by_status": [
            {
                "case_status": r["case_status"],
                "case_count": int(r["case_count"]),
                "net_loss_amount_fen": int(r["net_loss"]),
            }
            for r in by_status_res.mappings().all()
        ],
        "by_responsible_party": [
            {
                "party_type": r["party_type"],
                "case_count": int(r["case_count"]),
                "net_loss_amount_fen": int(r["net_loss"]),
            }
            for r in by_party_res.mappings().all()
        ],
        "by_store": [
            {
                "store_id": str(r["store_id"]),
                "case_count": int(r["case_count"]),
                "net_loss_amount_fen": int(r["net_loss"]),
            }
            for r in by_store_res.mappings().all()
        ],
        "by_reason": [
            {
                "reason_code": r["reason_code"],
                "item_count": int(r["item_count"]),
                "amount_fen": int(r["amount_fen"]),
            }
            for r in by_reason_res.mappings().all()
        ],
    }


__all__ = [
    "AUTO_CREATE_THRESHOLD_FEN",
    "SMALL_AMOUNT_THRESHOLD_FEN",
    "LARGE_AMOUNT_THRESHOLD_FEN",
    "CaseNotFoundError",
    "CaseValidationError",
    "ApprovalPermissionError",
    "WriteoffStateError",
    "_determine_approval_chain",
    "auto_create_loss_case_from_stocktake",
    "create_loss_case",
    "add_items",
    "assign_responsibility",
    "submit_for_approval",
    "approve",
    "reject",
    "writeoff",
    "list_cases",
    "get_case_detail",
    "get_loss_stats",
]
