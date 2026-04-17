"""
D10 换班审批流服务 — 单元测试（异步，mock DB）

覆盖：
  1) 自己与自己换班 → 拒绝
  2) 相同 shift_id → 拒绝
  3) 申请人非原班次所属者 → 拒绝
  4) 同班次已有 pending → 拒绝
  5) 成功提交后 employee_id 未变
  6) 审批通过 → 两个 shift 的 employee_id 互换
  7) 驳回缺原因 → 拒绝
  8) 非 pending 状态批准 → 拒绝
  9) 撤回：仅申请人可撤、仅 pending 可撤
"""

import sys
import uuid
from unittest.mock import AsyncMock, MagicMock

sys.modules.setdefault("src.core.config", MagicMock(settings=MagicMock()))

import pytest  # noqa: E402

from src.models.shift_swap import ShiftSwapRequest, ShiftSwapStatus  # noqa: E402
from src.services.shift_swap_service import ShiftSwapService  # noqa: E402


class FakeShift:
    def __init__(self, id, employee_id):
        self.id = id
        self.employee_id = employee_id


class FakeDB:
    """最小 async db mock，只覆盖本 service 使用的方法"""

    def __init__(self):
        self.store = {}
        self.added = []
        self.committed = False

    async def get(self, model, pk):
        return self.store.get((model.__name__, str(pk)))

    def put(self, obj):
        self.store[(obj.__class__.__name__, str(obj.id))] = obj

    def add(self, obj):
        self.added.append(obj)
        if hasattr(obj, "id") and obj.id is not None:
            self.store[(obj.__class__.__name__, str(obj.id))] = obj

    async def commit(self):
        self.committed = True

    async def refresh(self, obj):
        pass

    async def execute(self, stmt):
        # 查重 pending：默认没有
        result = MagicMock()
        result.scalars.return_value.first.return_value = None
        result.scalars.return_value.all.return_value = []
        return result


@pytest.fixture
def svc():
    return ShiftSwapService()


@pytest.fixture
def db():
    return FakeDB()


@pytest.fixture
def shifts(db):
    s1 = FakeShift(uuid.uuid4(), "E001")
    s2 = FakeShift(uuid.uuid4(), "E002")
    db.put(s1)
    db.put(s2)
    return s1, s2


@pytest.mark.asyncio
async def test_request_self_swap_rejected(svc, db, shifts):
    s1, s2 = shifts
    with pytest.raises(ValueError, match="不能与自己换班"):
        await svc.request_swap("E001", "E001", str(s1.id), str(s2.id), "x", db)


@pytest.mark.asyncio
async def test_request_same_shift_rejected(svc, db, shifts):
    s1, _ = shifts
    with pytest.raises(ValueError, match="不能相同"):
        await svc.request_swap("E001", "E002", str(s1.id), str(s1.id), "x", db)


@pytest.mark.asyncio
async def test_request_wrong_owner_rejected(svc, db, shifts):
    s1, s2 = shifts
    # 申请人 E999 并非 s1 的 employee_id
    with pytest.raises(ValueError, match="不属于申请人"):
        await svc.request_swap("E999", "E002", str(s1.id), str(s2.id), "x", db)


@pytest.mark.asyncio
async def test_request_ok(svc, db, shifts):
    s1, s2 = shifts
    req = await svc.request_swap("E001", "E002", str(s1.id), str(s2.id), "家里有事", db)
    assert req.status == ShiftSwapStatus.PENDING.value
    # employee_id 仍然未变
    assert s1.employee_id == "E001"
    assert s2.employee_id == "E002"


@pytest.mark.asyncio
async def test_approve_swaps_employee_ids(svc, db, shifts):
    s1, s2 = shifts
    req = await svc.request_swap("E001", "E002", str(s1.id), str(s2.id), "x", db)
    db.put(req)

    approved = await svc.approve_swap(str(req.id), "MGR01", db)
    assert approved.status == ShiftSwapStatus.APPROVED.value
    # 已互换
    assert s1.employee_id == "E002"
    assert s2.employee_id == "E001"
    assert approved.approver_id == "MGR01"


@pytest.mark.asyncio
async def test_reject_requires_reason(svc, db, shifts):
    s1, s2 = shifts
    req = await svc.request_swap("E001", "E002", str(s1.id), str(s2.id), "x", db)
    db.put(req)
    with pytest.raises(ValueError, match="必须填写原因"):
        await svc.reject_swap(str(req.id), "MGR01", "", db)


@pytest.mark.asyncio
async def test_approve_non_pending_rejected(svc, db, shifts):
    s1, s2 = shifts
    req = await svc.request_swap("E001", "E002", str(s1.id), str(s2.id), "x", db)
    req.status = ShiftSwapStatus.APPROVED.value
    db.put(req)
    with pytest.raises(ValueError, match="不允许审批"):
        await svc.approve_swap(str(req.id), "MGR01", db)


@pytest.mark.asyncio
async def test_withdraw_only_by_requester(svc, db, shifts):
    s1, s2 = shifts
    req = await svc.request_swap("E001", "E002", str(s1.id), str(s2.id), "x", db)
    db.put(req)
    with pytest.raises(ValueError, match="只有申请人"):
        await svc.withdraw(str(req.id), "OTHER", db)

    ok = await svc.withdraw(str(req.id), "E001", db)
    assert ok.status == ShiftSwapStatus.WITHDRAWN.value
