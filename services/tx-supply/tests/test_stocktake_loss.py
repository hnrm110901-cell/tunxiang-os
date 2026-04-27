"""盘亏处理审批闭环 — 服务层测试（mock AsyncSession）

覆盖场景：
  1.  test_auto_create_case_from_stocktake_calculates_amount_correctly
  2.  test_auto_create_skipped_when_below_threshold
  3.  test_submit_for_approval_chain_3_nodes_for_high_amount
  4.  test_submit_for_approval_chain_1_node_for_low_amount
  5.  test_submit_for_approval_chain_2_nodes_for_medium_amount
  6.  test_approve_current_node_advances_to_next
  7.  test_final_approve_sets_status_approved
  8.  test_reject_at_any_node_sets_status_rejected
  9.  test_state_machine_rejects_invalid_transition (DRAFT 不能直接 → APPROVED)
  10. test_writeoff_only_allowed_when_approved
  11. test_cross_tenant_isolation
  12. test_case_no_format_LOSS_YYYYMMDD_NNNN
  13. test_approve_role_mismatch_raises_permission_error
  14. test_determine_approval_chain_thresholds
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from models.stocktake_loss import (  # noqa: E402
    ApproverRole,
    CaseStatus,
    InvalidStateTransition,
    LossItemInput,
    ResponsiblePartyType,
)
from services.stocktake_loss_service import (  # noqa: E402
    LARGE_AMOUNT_THRESHOLD_FEN,
    SMALL_AMOUNT_THRESHOLD_FEN,
    ApprovalPermissionError,
    WriteoffStateError,
    _determine_approval_chain,
    approve,
    auto_create_loss_case_from_stocktake,
    create_loss_case,
    reject,
    submit_for_approval,
    writeoff,
)

TENANT_A = str(uuid.uuid4())
TENANT_B = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
USER_ID = str(uuid.uuid4())


# ─────────────────────────────────────────────────────────────────────
# 通用 mock 工具
# ─────────────────────────────────────────────────────────────────────


class FakeDB:
    """轻量 mock AsyncSession：对每条 SQL 返回 scripted result。

    使用方式：
        db = FakeDB()
        db.queue.append(("SELECT", [{"id": ...}]))   # mappings().all() 返回 list
        db.queue.append(("UPDATE", None))            # 写操作不需要 result
    """

    def __init__(self) -> None:
        self.queue: list[tuple[str, Any]] = []
        self.executed: list[tuple[str, dict | None]] = []
        self.flush = AsyncMock()
        self.add = MagicMock()

    async def execute(self, query, params=None):
        sql_str = str(query) if hasattr(query, "__str__") else ""
        self.executed.append((sql_str, params))

        if not self.queue:
            return _empty_result()

        kind, data = self.queue.pop(0)
        if kind == "ROW":
            return _scalar_row_result(data)
        if kind == "ROWS":
            return _rows_result(data)
        if kind == "ONE":
            return _one_result(data)
        return _empty_result()


def _empty_result() -> MagicMock:
    r = MagicMock()
    mp = MagicMock()
    mp.all = MagicMock(return_value=[])
    mp.one_or_none = MagicMock(return_value=None)
    mp.one = MagicMock(side_effect=Exception("no row"))
    r.mappings = MagicMock(return_value=mp)
    return r


def _scalar_row_result(row: dict) -> MagicMock:
    """模拟 mappings().one_or_none() 返回单行"""
    r = MagicMock()
    mp = MagicMock()
    mp.one_or_none = MagicMock(return_value=row)
    mp.one = MagicMock(return_value=row)
    mp.all = MagicMock(return_value=[row])
    r.mappings = MagicMock(return_value=mp)
    return r


def _rows_result(rows: list[dict]) -> MagicMock:
    """模拟 mappings().all() 返回多行"""
    r = MagicMock()
    mp = MagicMock()
    mp.all = MagicMock(return_value=rows)
    mp.one_or_none = MagicMock(return_value=rows[0] if rows else None)
    mp.one = MagicMock(return_value=rows[0] if rows else None)
    r.mappings = MagicMock(return_value=mp)
    return r


def _one_result(row: dict) -> MagicMock:
    """模拟 mappings().one() 返回单行（用于 fn_next_loss_case_no 等）"""
    r = MagicMock()
    mp = MagicMock()
    mp.one = MagicMock(return_value=row)
    mp.one_or_none = MagicMock(return_value=row)
    mp.all = MagicMock(return_value=[row])
    r.mappings = MagicMock(return_value=mp)
    return r


def _make_case_row(
    *,
    case_id: str | None = None,
    case_status: str = "DRAFT",
    net_loss_fen: int = 200_000,
    total_loss_fen: int = 250_000,
    total_gain_fen: int = 50_000,
    tenant_id: str = TENANT_A,
    store_id: str = STORE_ID,
) -> dict[str, Any]:
    cid = case_id or str(uuid.uuid4())
    return {
        "id": uuid.UUID(cid),
        "tenant_id": uuid.UUID(tenant_id),
        "stocktake_id": uuid.uuid4(),
        "store_id": uuid.UUID(store_id),
        "case_no": "LOSS-20260427-0001",
        "total_loss_amount_fen": total_loss_fen,
        "total_gain_amount_fen": total_gain_fen,
        "net_loss_amount_fen": net_loss_fen,
        "responsible_party_type": None,
        "responsible_party_id": None,
        "responsible_reason": None,
        "case_status": case_status,
        "created_by": uuid.UUID(USER_ID),
        "submitted_at": None,
        "final_approved_at": None,
        "written_off_at": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "is_deleted": False,
    }


# ─────────────────────────────────────────────────────────────────────
# Test 1 + 12: auto_create_case calculates amount correctly + case_no format
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auto_create_case_from_stocktake_calculates_amount_correctly():
    """盘点完成后自动建案：金额按 |diff| * unit_cost 累加，盘亏/盘盈分别累加。"""
    stocktake_id = str(uuid.uuid4())
    ing1 = str(uuid.uuid4())
    ing2 = str(uuid.uuid4())

    db = FakeDB()
    # 1) set_config
    db.queue.append(("ROW", None))
    # 2) SELECT stocktakes (status = completed)
    db.queue.append(
        (
            "ROW",
            {
                "id": uuid.UUID(stocktake_id),
                "store_id": uuid.UUID(STORE_ID),
                "status": "completed",
            },
        )
    )
    # 3) SELECT stocktake_items diff rows
    # 鸡腿：账面 10kg / 实盘 8kg = 盘亏 2kg；cost_price 30 元/kg → loss = 2 * 3000 = 6000 分
    # 大葱：账面 5kg / 实盘 6kg = 盘盈 1kg；cost_price 5 元/kg → gain = 1 * 500 = 500 分
    # net_loss = 6000 - 500 = 5500 分（未达 100000 阈值，应跳过）
    # 为达到阈值，调高鸡腿差异：10kg → 8kg、cost_price = 1000 元/kg = 100000 分/kg → loss = 2 * 100000 = 200000 分
    db.queue.append(
        (
            "ROWS",
            [
                {
                    "ingredient_id": uuid.UUID(ing1),
                    "expected_qty": 10.0,
                    "actual_qty": 8.0,
                    "cost_price": 1000.0,  # 元
                },
                {
                    "ingredient_id": uuid.UUID(ing2),
                    "expected_qty": 5.0,
                    "actual_qty": 6.0,
                    "cost_price": 5.0,
                },
            ],
        )
    )
    # 4) fn_next_loss_case_no
    db.queue.append(("ONE", {"case_no": "LOSS-20260427-0001"}))
    # 5) INSERT cases
    db.queue.append(("ROW", None))
    # 6) INSERT items x 2
    db.queue.append(("ROW", None))
    db.queue.append(("ROW", None))

    result = await auto_create_loss_case_from_stocktake(
        stocktake_id=stocktake_id,
        tenant_id=TENANT_A,
        db=db,
        created_by=USER_ID,
    )

    assert result is not None
    assert result["case_no"] == "LOSS-20260427-0001"
    # 鸡腿盘亏 2kg * 100000 分/kg = 200000 分
    assert result["total_loss_amount_fen"] == 200_000
    # 大葱盘盈 1kg * 500 分/kg = 500 分
    assert result["total_gain_amount_fen"] == 500
    # 净亏 = 199500 分
    assert result["net_loss_amount_fen"] == 199_500
    assert result["item_count"] == 2
    assert result["case_status"] == "DRAFT"
    # 案件号格式：LOSS-YYYYMMDD-NNNN
    import re

    assert re.match(r"^LOSS-\d{8}-\d{4}$", result["case_no"])


# ─────────────────────────────────────────────────────────────────────
# Test 2: auto_create skipped when below threshold
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auto_create_skipped_when_below_threshold():
    """净亏损金额 < 1000 元（100000 分），不应建案。"""
    stocktake_id = str(uuid.uuid4())
    ing1 = str(uuid.uuid4())

    db = FakeDB()
    db.queue.append(("ROW", None))  # set_config
    db.queue.append(
        (
            "ROW",
            {
                "id": uuid.UUID(stocktake_id),
                "store_id": uuid.UUID(STORE_ID),
                "status": "completed",
            },
        )
    )
    # 损失 50 元 = 5000 分（远低于 100000 阈值）
    db.queue.append(
        (
            "ROWS",
            [
                {
                    "ingredient_id": uuid.UUID(ing1),
                    "expected_qty": 5.0,
                    "actual_qty": 4.0,
                    "cost_price": 50.0,  # 50 元/kg
                },
            ],
        )
    )

    result = await auto_create_loss_case_from_stocktake(
        stocktake_id=stocktake_id,
        tenant_id=TENANT_A,
        db=db,
        created_by=USER_ID,
    )

    assert result is None
    # 不应触发后续 INSERT，所以队列里没有 fn_next_loss_case_no 调用
    assert "fn_next_loss_case_no" not in "\n".join(s for s, _ in db.executed)


# ─────────────────────────────────────────────────────────────────────
# Test 3 + 4 + 5: submit_for_approval chain length by amount
# ─────────────────────────────────────────────────────────────────────


def test_determine_approval_chain_thresholds():
    """审批链长度按金额规则。"""
    # < 5000 元：1 节点
    chain_low = _determine_approval_chain(SMALL_AMOUNT_THRESHOLD_FEN - 1)
    assert chain_low == [ApproverRole.STORE_MANAGER]

    # 5000-50000 元：2 节点
    chain_mid = _determine_approval_chain(SMALL_AMOUNT_THRESHOLD_FEN)
    assert chain_mid == [ApproverRole.STORE_MANAGER, ApproverRole.REGIONAL_MANAGER]

    chain_mid_high = _determine_approval_chain(LARGE_AMOUNT_THRESHOLD_FEN - 1)
    assert chain_mid_high == [ApproverRole.STORE_MANAGER, ApproverRole.REGIONAL_MANAGER]

    # > 50000 元：3 节点
    chain_high = _determine_approval_chain(LARGE_AMOUNT_THRESHOLD_FEN)
    assert chain_high == [
        ApproverRole.STORE_MANAGER,
        ApproverRole.REGIONAL_MANAGER,
        ApproverRole.FINANCE,
    ]


@pytest.mark.asyncio
async def test_submit_for_approval_chain_3_nodes_for_high_amount():
    """净亏损 > 50000 元 → 审批链 3 节点（店长 + 区域 + 财务）。"""
    case_id = str(uuid.uuid4())
    db = FakeDB()
    # _set_tenant
    db.queue.append(("ROW", None))
    # _fetch_case_row（DRAFT 状态，net_loss = 60000 元 = 6,000,000 分）
    db.queue.append(
        (
            "ROW",
            _make_case_row(
                case_id=case_id,
                case_status="DRAFT",
                net_loss_fen=6_000_000,
            ),
        )
    )
    # _transition_status -> _fetch_case_row 再读
    db.queue.append(
        (
            "ROW",
            _make_case_row(
                case_id=case_id,
                case_status="DRAFT",
                net_loss_fen=6_000_000,
            ),
        )
    )
    # UPDATE 状态
    db.queue.append(("ROW", None))
    # INSERT 节点 x 3
    db.queue.append(("ROW", None))
    db.queue.append(("ROW", None))
    db.queue.append(("ROW", None))

    result = await submit_for_approval(
        case_id=case_id, tenant_id=TENANT_A, db=db, submitted_by=USER_ID
    )

    assert result["case_status"] == "PENDING_APPROVAL"
    assert result["approval_chain"] == [
        "STORE_MANAGER",
        "REGIONAL_MANAGER",
        "FINANCE",
    ]
    assert result["current_node_seq"] == 1


@pytest.mark.asyncio
async def test_submit_for_approval_chain_1_node_for_low_amount():
    """净亏损 < 5000 元 → 审批链仅 1 节点（店长）。"""
    case_id = str(uuid.uuid4())
    db = FakeDB()
    db.queue.append(("ROW", None))  # set_config
    case_row = _make_case_row(
        case_id=case_id,
        case_status="DRAFT",
        net_loss_fen=200_000,  # 2000 元 < 5000 元
    )
    db.queue.append(("ROW", case_row))
    db.queue.append(("ROW", case_row))  # _transition_status 再读
    db.queue.append(("ROW", None))  # UPDATE
    db.queue.append(("ROW", None))  # INSERT 节点 x 1

    result = await submit_for_approval(
        case_id=case_id, tenant_id=TENANT_A, db=db, submitted_by=USER_ID
    )

    assert result["approval_chain"] == ["STORE_MANAGER"]


# ─────────────────────────────────────────────────────────────────────
# Test 6: approve current node advances to next
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_approve_current_node_advances_to_next():
    """中间节点通过：状态保持 PENDING_APPROVAL，next 节点变为当前。"""
    case_id = str(uuid.uuid4())
    db = FakeDB()
    db.queue.append(("ROW", None))  # set_config
    db.queue.append(
        (
            "ROW",
            _make_case_row(case_id=case_id, case_status="PENDING_APPROVAL"),
        )
    )
    # _find_current_pending_node：返回第 1 节点（STORE_MANAGER）
    node1_id = uuid.uuid4()
    db.queue.append(
        (
            "ROW",
            {
                "id": node1_id,
                "approval_node_seq": 1,
                "approver_role": "STORE_MANAGER",
            },
        )
    )
    # UPDATE 节点 decision
    db.queue.append(("ROW", None))
    # _is_last_node：max_seq = 3（说明不是最后一个）
    db.queue.append(("ROW", {"max_seq": 3}))

    result = await approve(
        case_id=case_id,
        approver_id=USER_ID,
        approver_role=ApproverRole.STORE_MANAGER,
        tenant_id=TENANT_A,
        db=db,
        comment="同意，金额合理",
    )

    assert result["case_status"] == "PENDING_APPROVAL"
    assert result["is_final"] is False
    assert result["approved_node_seq"] == 1


# ─────────────────────────────────────────────────────────────────────
# Test 7: final node approve sets case status APPROVED
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_final_approve_sets_status_approved():
    """最后节点通过：状态变为 APPROVED 并记录 final_approved_at + 触发事件。"""
    case_id = str(uuid.uuid4())
    db = FakeDB()
    db.queue.append(("ROW", None))  # set_config
    case_row = _make_case_row(case_id=case_id, case_status="PENDING_APPROVAL")
    db.queue.append(("ROW", case_row))
    # 当前节点是最后节点（seq = 1 = max_seq）
    db.queue.append(
        (
            "ROW",
            {
                "id": uuid.uuid4(),
                "approval_node_seq": 1,
                "approver_role": "STORE_MANAGER",
            },
        )
    )
    db.queue.append(("ROW", None))  # UPDATE 节点 decision
    db.queue.append(("ROW", {"max_seq": 1}))  # _is_last_node
    # _transition_status -> _fetch_case_row
    db.queue.append(("ROW", case_row))
    db.queue.append(("ROW", None))  # UPDATE case 状态

    result = await approve(
        case_id=case_id,
        approver_id=USER_ID,
        approver_role=ApproverRole.STORE_MANAGER,
        tenant_id=TENANT_A,
        db=db,
    )

    assert result["case_status"] == "APPROVED"
    assert result["is_final"] is True


# ─────────────────────────────────────────────────────────────────────
# Test 8: reject at any node
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reject_at_any_node_sets_status_rejected():
    """任一节点驳回 → 案件状态 REJECTED（终态）。"""
    case_id = str(uuid.uuid4())
    db = FakeDB()
    db.queue.append(("ROW", None))  # set_config
    case_row = _make_case_row(case_id=case_id, case_status="PENDING_APPROVAL")
    db.queue.append(("ROW", case_row))
    # 当前节点是中间节点（seq=2），即使如此驳回也终止
    db.queue.append(
        (
            "ROW",
            {
                "id": uuid.uuid4(),
                "approval_node_seq": 2,
                "approver_role": "REGIONAL_MANAGER",
            },
        )
    )
    db.queue.append(("ROW", None))  # UPDATE 节点 decision
    # _transition_status -> _fetch_case_row + UPDATE
    db.queue.append(("ROW", case_row))
    db.queue.append(("ROW", None))

    result = await reject(
        case_id=case_id,
        approver_id=USER_ID,
        approver_role=ApproverRole.REGIONAL_MANAGER,
        tenant_id=TENANT_A,
        db=db,
        comment="缺少证据，请补充",
    )

    assert result["case_status"] == "REJECTED"
    assert result["rejected_node_seq"] == 2


# ─────────────────────────────────────────────────────────────────────
# Test 9: state machine rejects invalid transition
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_state_machine_rejects_invalid_transition():
    """DRAFT 不能直接 → APPROVED；必须经过 PENDING_APPROVAL。"""
    case_id = str(uuid.uuid4())
    db = FakeDB()
    db.queue.append(("ROW", None))  # set_config
    # 模拟尝试在 DRAFT 状态直接调用 approve（绕过 submit）
    case_row = _make_case_row(case_id=case_id, case_status="DRAFT")
    db.queue.append(("ROW", case_row))

    from services.stocktake_loss_service import CaseValidationError

    # approve 函数会先校验 case_status 是 PENDING_APPROVAL 否则抛 CaseValidationError
    with pytest.raises(CaseValidationError):
        await approve(
            case_id=case_id,
            approver_id=USER_ID,
            approver_role=ApproverRole.STORE_MANAGER,
            tenant_id=TENANT_A,
            db=db,
        )

    # 同时校验状态机本身的转换规则（独立测试）
    from models.stocktake_loss import assert_can_transition

    with pytest.raises(InvalidStateTransition):
        assert_can_transition(CaseStatus.DRAFT, CaseStatus.APPROVED)
    with pytest.raises(InvalidStateTransition):
        assert_can_transition(CaseStatus.DRAFT, CaseStatus.WRITTEN_OFF)
    with pytest.raises(InvalidStateTransition):
        assert_can_transition(CaseStatus.REJECTED, CaseStatus.APPROVED)
    with pytest.raises(InvalidStateTransition):
        assert_can_transition(CaseStatus.WRITTEN_OFF, CaseStatus.DRAFT)


# ─────────────────────────────────────────────────────────────────────
# Test 10: writeoff only allowed when APPROVED
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_writeoff_only_allowed_when_approved():
    """状态非 APPROVED 时核销应抛 WriteoffStateError。"""
    case_id = str(uuid.uuid4())
    db = FakeDB()
    db.queue.append(("ROW", None))  # set_config
    # 案件还在 PENDING_APPROVAL
    db.queue.append(
        (
            "ROW",
            _make_case_row(case_id=case_id, case_status="PENDING_APPROVAL"),
        )
    )

    with pytest.raises(WriteoffStateError):
        await writeoff(
            case_id=case_id,
            writeoff_voucher_no="V-2026-001",
            writeoff_amount_fen=200_000,
            accounting_subject="管理费用-存货损失",
            finance_user_id=USER_ID,
            tenant_id=TENANT_A,
            db=db,
        )

    # APPROVED 状态可以核销（验证正常路径）
    db2 = FakeDB()
    db2.queue.append(("ROW", None))  # set_config
    case_row = _make_case_row(case_id=case_id, case_status="APPROVED")
    db2.queue.append(("ROW", case_row))
    # INSERT writeoff
    db2.queue.append(("ROW", None))
    # _transition_status -> _fetch_case_row
    db2.queue.append(("ROW", case_row))
    # UPDATE 状态
    db2.queue.append(("ROW", None))

    result = await writeoff(
        case_id=case_id,
        writeoff_voucher_no="V-2026-001",
        writeoff_amount_fen=200_000,
        accounting_subject="管理费用-存货损失",
        finance_user_id=USER_ID,
        tenant_id=TENANT_A,
        db=db2,
    )
    assert result["case_status"] == "WRITTEN_OFF"


# ─────────────────────────────────────────────────────────────────────
# Test 11: cross tenant isolation
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cross_tenant_isolation():
    """tenant B 试图读 tenant A 的案件 → CaseNotFoundError。

    模拟 RLS 已生效：fetch 返回 None。
    """
    case_id = str(uuid.uuid4())
    db = FakeDB()
    db.queue.append(("ROW", None))  # set_config (B)
    # RLS 过滤后 query 返回空
    db.queue.append(("ROW", None))

    from services.stocktake_loss_service import CaseNotFoundError, get_case_detail

    with pytest.raises(CaseNotFoundError):
        await get_case_detail(case_id, TENANT_B, db)


# ─────────────────────────────────────────────────────────────────────
# Test 13: approve role mismatch raises permission error
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_approve_role_mismatch_raises_permission_error():
    """approver_role 与当前节点要求不一致 → ApprovalPermissionError。"""
    case_id = str(uuid.uuid4())
    db = FakeDB()
    db.queue.append(("ROW", None))  # set_config
    db.queue.append(
        (
            "ROW",
            _make_case_row(case_id=case_id, case_status="PENDING_APPROVAL"),
        )
    )
    # 当前节点要求 STORE_MANAGER
    db.queue.append(
        (
            "ROW",
            {
                "id": uuid.uuid4(),
                "approval_node_seq": 1,
                "approver_role": "STORE_MANAGER",
            },
        )
    )

    with pytest.raises(ApprovalPermissionError):
        await approve(
            case_id=case_id,
            approver_id=USER_ID,
            approver_role=ApproverRole.FINANCE,  # 角色不匹配
            tenant_id=TENANT_A,
            db=db,
        )


# ─────────────────────────────────────────────────────────────────────
# Test 14: create_loss_case manual path
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_loss_case_manual_with_responsible_party():
    """手动建案：可指定 responsible_party 和 reason_code。"""
    db = FakeDB()
    db.queue.append(("ROW", None))  # set_config
    # fn_next_loss_case_no
    db.queue.append(("ONE", {"case_no": "LOSS-20260427-0002"}))
    # INSERT case
    db.queue.append(("ROW", None))
    # INSERT items x 1
    db.queue.append(("ROW", None))

    result = await create_loss_case(
        tenant_id=TENANT_A,
        stocktake_id=str(uuid.uuid4()),
        store_id=STORE_ID,
        items=[
            LossItemInput(
                ingredient_id=str(uuid.uuid4()),
                expected_qty=10.0,
                actual_qty=7.0,
                unit_cost_fen=50_000,  # 500 元/kg
                reason_code=None,  # type: ignore
            )
        ],
        created_by=USER_ID,
        db=db,
        responsible_party_type=ResponsiblePartyType.EMPLOYEE,
        responsible_party_id=USER_ID,
        responsible_reason="员工漏登领料",
    )

    # 损失 = 3 * 50000 = 150000 分
    assert result["total_loss_amount_fen"] == 150_000
    assert result["total_gain_amount_fen"] == 0
    assert result["net_loss_amount_fen"] == 150_000
    assert result["case_no"] == "LOSS-20260427-0002"
    assert result["case_status"] == "DRAFT"
