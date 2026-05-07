"""Tier 1 — P0-7 tx-ops 事件总线覆盖测试

验收：5 类关键状态变更发射 emit_event，对应差距文档 Part E §7 + Part C §C.8

覆盖范围：
  1. 巡店报告提交（submit）→ SafetyInspectionEventType.INSPECTION_COMPLETED
  2. 巡店报告提交低分（score < 60）→ SafetyInspectionEventType.INSPECTION_FAILED
  3. 门店确认巡店报告（acknowledge）→ SafetyInspectionEventType.INSPECTION_ACKNOWLEDGED
  4. 审批实例发起（create_instance）→ ApprovalEventType.INITIATED
  5. 审批动作—通过（act approve, final status=approved）→ ApprovalEventType.APPROVED
  6. sad-path：纯查询（GET）不发射 emit_event

Mock 模式：monkeypatch asyncio.create_task + emit_event，断言 payload 字段。
参考：services/tx-trade/src/tests/test_banquet_lead_tier1.py（fake_emit 模式）
"""

from __future__ import annotations

import asyncio
import os
import sys
import types
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

# ─── 路径准备 ────────────────────────────────────────────────────────────────
_THIS_DIR = os.path.dirname(__file__)
_ROOT_DIR = os.path.abspath(os.path.join(_THIS_DIR, "..", ".."))
_OPS_SRC = os.path.abspath(os.path.join(_ROOT_DIR, "services", "tx-ops", "src"))

for _p in [_ROOT_DIR, _OPS_SRC]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ─── sys.modules 存根（避免真实DB / Redis 依赖）────────────────────────────


def _stub(name: str, **attrs):
    if name not in sys.modules:
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod
    return sys.modules[name]


def _ensure_pkg(name: str, path: str) -> None:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod


# 共享事件枚举（从真实源导入 — 仅用枚举，不触发 Redis / asyncpg）
_events_src = os.path.join(_ROOT_DIR, "shared", "events", "src")
_ensure_pkg("shared", os.path.join(_ROOT_DIR, "shared"))
_ensure_pkg("shared.events", os.path.join(_ROOT_DIR, "shared", "events"))
_ensure_pkg("shared.events.src", _events_src)

# 用真实 event_types（纯枚举，无 IO 依赖）
import importlib.util as _ilu

_et_spec = _ilu.spec_from_file_location(
    "shared.events.src.event_types",
    os.path.join(_events_src, "event_types.py"),
)
_et_mod = _ilu.module_from_spec(_et_spec)  # type: ignore[arg-type]
_et_spec.loader.exec_module(_et_mod)  # type: ignore[union-attr]
sys.modules["shared.events.src.event_types"] = _et_mod

from shared.events.src.event_types import (  # noqa: E402
    ApprovalEventType,
    SafetyInspectionEventType,
)

# emit_event 存根（测试中替换为 fake）
_emitter_mod = types.ModuleType("shared.events.src.emitter")


async def _noop_emit(*args: Any, **kwargs: Any) -> str:  # type: ignore[return]
    return "fake-event-id"


_emitter_mod.emit_event = _noop_emit
sys.modules["shared.events.src.emitter"] = _emitter_mod

# shared.ontology 存根
_ensure_pkg("shared.ontology", os.path.join(_ROOT_DIR, "shared", "ontology"))
_ensure_pkg("shared.ontology.src", os.path.join(_ROOT_DIR, "shared", "ontology", "src"))

_db_mod = types.ModuleType("shared.ontology.src.database")


async def _get_db_placeholder():  # noqa: ANN202
    yield None  # pragma: no cover


_db_mod.get_db = _get_db_placeholder
sys.modules["shared.ontology.src.database"] = _db_mod

# shared.security 存根
_ensure_pkg("shared.security", os.path.join(_ROOT_DIR, "shared", "security"))
_ensure_pkg("shared.security.src", os.path.join(_ROOT_DIR, "shared", "security", "src"))

_sec_mod = types.ModuleType("shared.security.src.error_handler")


def _safe_http_exception(status_code: int, msg: str, exc: Exception) -> Exception:
    from fastapi import HTTPException

    return HTTPException(status_code=status_code, detail=msg)


_sec_mod.safe_http_exception = _safe_http_exception
sys.modules["shared.security.src.error_handler"] = _sec_mod

# ─── 被测模块导入 ─────────────────────────────────────────────────────────────
_ensure_pkg("src", _OPS_SRC)
_ensure_pkg("src.api", os.path.join(_OPS_SRC, "api"))

# 导入 inspection_routes
_insp_spec = _ilu.spec_from_file_location(
    "src.api.inspection_routes",
    os.path.join(_OPS_SRC, "api", "inspection_routes.py"),
)
_insp_mod = _ilu.module_from_spec(_insp_spec)  # type: ignore[arg-type]
_insp_spec.loader.exec_module(_insp_mod)  # type: ignore[union-attr]
sys.modules["src.api.inspection_routes"] = _insp_mod

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
STORE_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
INSPECTOR_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


@pytest.fixture
def emitted_events() -> List[Dict[str, Any]]:
    return []


@pytest.fixture
def fake_emit(emitted_events: List[Dict[str, Any]]):
    """替换 emit_event 为收集器，返回列表引用以便断言。"""
    collected = emitted_events

    async def _fake(**kwargs: Any) -> str:
        collected.append(kwargs)
        return "fake-event-id"

    return _fake


# ─────────────────────────────────────────────────────────────────────────────
# 1. 巡店提交 → INSPECTION_COMPLETED (score >= 60)
# ─────────────────────────────────────────────────────────────────────────────


class TestInspectionSubmitEmitsEvent:
    """场景：督导完成巡店后提交报告（总分 85），系统应发射 INSPECTION_COMPLETED。"""

    @pytest.mark.asyncio
    async def test_submit_inspection_emits_completed_event(
        self,
        fake_emit,
        emitted_events: List[Dict[str, Any]],
        monkeypatch,
    ):
        """submit_inspection → emit INSPECTION_COMPLETED（score=85，pass）"""
        import uuid

        from src.api import inspection_routes as ir

        report_id = str(uuid.uuid4())
        store_id = STORE_ID

        monkeypatch.setattr(ir.asyncio, "create_task", lambda coro: asyncio.ensure_future(coro))

        # 替换 emitter.emit_event
        monkeypatch.setattr(ir, "emit_event", fake_emit)

        # 构造 mock DB 返回（已提交状态，得分 85）
        # 直接用真实 dict — _serialize_row 调用 dict(row)，dict(dict) = copy
        _row_data = {
            "id": report_id,
            "tenant_id": TENANT_ID,
            "store_id": store_id,
            "inspection_date": "2026-05-07",
            "inspector_id": INSPECTOR_ID,
            "overall_score": 85.0,
            "dimensions": [],
            "photos": [],
            "action_items": [],
            "notes": None,
            "ack_notes": None,
            "status": "submitted",
            "acknowledged_by": None,
            "acknowledged_at": None,
            "created_at": "2026-05-07T10:00:00",
            "updated_at": "2026-05-07T10:01:00",
            "is_deleted": False,
        }
        _existing_data = {"status": "draft"}

        # db.execute() 返回一个普通 MagicMock（非 AsyncMock），确保链式调用是同步的
        # 调用顺序：1) _set_tenant 2) SELECT status check 3) UPDATE RETURNING
        _exec_set_tenant = MagicMock()

        _exec_result_check = MagicMock()
        _exec_result_check.mappings.return_value.one_or_none.return_value = _existing_data

        _exec_result_row = MagicMock()
        _exec_result_row.mappings.return_value.one.return_value = _row_data

        mock_db = AsyncMock()
        # 每次 await db.execute() 按顺序返回不同结果
        mock_db.execute = AsyncMock(side_effect=[_exec_set_tenant, _exec_result_check, _exec_result_row])
        mock_db.commit = AsyncMock()

        # 调用 submit_inspection
        body = MagicMock()
        body.final_notes = None

        await ir.submit_inspection(
            report_id=report_id,
            body=body,
            x_tenant_id=TENANT_ID,
            db=mock_db,
        )

        # 等待所有 asyncio tasks
        await asyncio.sleep(0)

        assert len(emitted_events) >= 1, "应发射至少 1 个事件"
        evt = emitted_events[0]
        assert evt["event_type"] == SafetyInspectionEventType.INSPECTION_COMPLETED
        assert evt["tenant_id"] == TENANT_ID
        assert evt["stream_id"] == report_id
        assert evt["payload"]["report_id"] == report_id
        assert evt["source_service"] == "tx-ops"


# ─────────────────────────────────────────────────────────────────────────────
# 2. 巡店提交低分 → INSPECTION_FAILED (score < 60)
# ─────────────────────────────────────────────────────────────────────────────


class TestInspectionSubmitFailedEvent:
    """场景：巡店发现严重问题（总分 45），系统应发射 INSPECTION_FAILED。"""

    @pytest.mark.asyncio
    async def test_submit_inspection_emits_failed_event_when_score_below_60(
        self,
        fake_emit,
        emitted_events: List[Dict[str, Any]],
        monkeypatch,
    ):
        """submit_inspection(score=45) → emit INSPECTION_FAILED"""
        import uuid

        from src.api import inspection_routes as ir

        report_id = str(uuid.uuid4())

        monkeypatch.setattr(ir.asyncio, "create_task", lambda coro: asyncio.ensure_future(coro))
        monkeypatch.setattr(ir, "emit_event", fake_emit)

        _row_data2 = {
            "id": report_id,
            "store_id": STORE_ID,
            "inspector_id": INSPECTOR_ID,
            "inspection_date": "2026-05-07",
            "overall_score": 45.0,
            "action_items": [],
            "status": "submitted",
            "acknowledged_by": None,
            "acknowledged_at": None,
        }

        _exec_set_tenant2 = MagicMock()

        _exec_result_check2 = MagicMock()
        _exec_result_check2.mappings.return_value.one_or_none.return_value = {"status": "draft"}

        _exec_result_row2 = MagicMock()
        _exec_result_row2.mappings.return_value.one.return_value = _row_data2

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[_exec_set_tenant2, _exec_result_check2, _exec_result_row2])
        mock_db.commit = AsyncMock()

        body = MagicMock()
        body.final_notes = "严重违规，需立即整改"

        await ir.submit_inspection(
            report_id=report_id,
            body=body,
            x_tenant_id=TENANT_ID,
            db=mock_db,
        )
        await asyncio.sleep(0)

        assert len(emitted_events) >= 1
        evt = emitted_events[0]
        assert evt["event_type"] == SafetyInspectionEventType.INSPECTION_FAILED, (
            f"低分巡店应发射 INSPECTION_FAILED，实际为 {evt['event_type']}"
        )
        assert evt["tenant_id"] == TENANT_ID


# ─────────────────────────────────────────────────────────────────────────────
# 3. 门店确认巡店报告 → INSPECTION_ACKNOWLEDGED
# ─────────────────────────────────────────────────────────────────────────────


class TestInspectionAcknowledgeEmitsEvent:
    """场景：门店店长收到督导报告后在系统中确认，系统发射 INSPECTION_ACKNOWLEDGED。"""

    @pytest.mark.asyncio
    async def test_acknowledge_inspection_emits_acknowledged_event(
        self,
        fake_emit,
        emitted_events: List[Dict[str, Any]],
        monkeypatch,
    ):
        """acknowledge_inspection → emit INSPECTION_ACKNOWLEDGED"""
        import uuid

        from src.api import inspection_routes as ir

        report_id = str(uuid.uuid4())
        ack_by = "manager-001"

        monkeypatch.setattr(ir.asyncio, "create_task", lambda coro: asyncio.ensure_future(coro))
        monkeypatch.setattr(ir, "emit_event", fake_emit)

        _row_data3 = {
            "id": report_id,
            "store_id": STORE_ID,
            "inspector_id": INSPECTOR_ID,
            "overall_score": 78.0,
            "status": "acknowledged",
            "acknowledged_by": ack_by,
            "acknowledged_at": "2026-05-07T12:00:00",
        }

        _exec_set_tenant3 = MagicMock()

        _exec_result_check3 = MagicMock()
        _exec_result_check3.mappings.return_value.one_or_none.return_value = {"status": "submitted"}

        _exec_result_row3 = MagicMock()
        _exec_result_row3.mappings.return_value.one.return_value = _row_data3

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[_exec_set_tenant3, _exec_result_check3, _exec_result_row3])
        mock_db.commit = AsyncMock()

        body = MagicMock()
        body.acknowledged_by = ack_by
        body.ack_notes = "已知悉，将安排整改"

        await ir.acknowledge_inspection(
            report_id=report_id,
            body=body,
            x_tenant_id=TENANT_ID,
            db=mock_db,
        )
        await asyncio.sleep(0)

        assert len(emitted_events) >= 1
        evt = emitted_events[0]
        assert evt["event_type"] == SafetyInspectionEventType.INSPECTION_ACKNOWLEDGED
        assert evt["tenant_id"] == TENANT_ID
        assert evt["stream_id"] == report_id
        assert evt["payload"]["acknowledged_by"] == ack_by


# ─────────────────────────────────────────────────────────────────────────────
# 4. 审批实例发起 → ApprovalEventType.INITIATED
# ─────────────────────────────────────────────────────────────────────────────


class TestApprovalInitiatedEmitsEvent:
    """场景：收银员申请大额折扣，系统发起审批流，发射 APPROVAL_INITIATED 事件。"""

    @pytest.mark.asyncio
    async def test_create_approval_instance_emits_initiated_event(
        self,
        fake_emit,
        emitted_events: List[Dict[str, Any]],
        monkeypatch,
    ):
        """create_instance → emit ApprovalEventType.INITIATED"""
        import uuid

        # 需要为 approval_workflow_routes 设置存根
        _ensure_pkg("src.services", os.path.join(_OPS_SRC, "services"))

        # 存根 approval_engine
        _ae_mod = types.ModuleType("src.services.approval_engine")
        instance_id = str(uuid.uuid4())

        async def _fake_create_instance(**kwargs):
            return {
                "id": instance_id,
                "business_type": kwargs.get("business_type"),
                "business_id": kwargs.get("business_id"),
                "title": kwargs.get("title"),
                "status": "pending",
                "total_steps": 2,
                "current_step": 1,
            }

        fake_engine = MagicMock()
        fake_engine.create_instance = _fake_create_instance
        _ae_mod.approval_engine = fake_engine
        sys.modules["src.services.approval_engine"] = _ae_mod

        # 导入审批路由（设置 __package__ 以确保相对导入可用）
        _appr_spec = _ilu.spec_from_file_location(
            "src.api.approval_workflow_routes",
            os.path.join(_OPS_SRC, "api", "approval_workflow_routes.py"),
        )
        _appr_mod = _ilu.module_from_spec(_appr_spec)  # type: ignore[arg-type]
        _appr_mod.__package__ = "src.api"
        _appr_spec.loader.exec_module(_appr_mod)  # type: ignore[union-attr]
        sys.modules["src.api.approval_workflow_routes"] = _appr_mod

        import src.api.approval_workflow_routes as aw  # noqa: E402

        monkeypatch.setattr(aw.asyncio, "create_task", lambda coro: asyncio.ensure_future(coro))
        monkeypatch.setattr(aw, "emit_event", fake_emit)

        body = MagicMock()
        body.business_type = "discount"
        body.business_id = "order-001"
        body.title = "大额折扣审批"
        body.description = "桌8折扣超出授权"
        body.initiator_id = "cashier-001"
        body.initiator_name = "小李"
        body.amount_fen = 5000  # 50元
        body.deadline_hours = None

        mock_db = AsyncMock()

        await aw.create_instance(body=body, x_tenant_id=TENANT_ID, db=mock_db)
        await asyncio.sleep(0)

        assert len(emitted_events) >= 1
        evt = emitted_events[0]
        assert evt["event_type"] == ApprovalEventType.INITIATED
        assert evt["tenant_id"] == TENANT_ID
        assert evt["payload"]["business_type"] == "discount"
        assert evt["payload"]["amount_fen"] == 5000
        assert evt["source_service"] == "tx-ops"


# ─────────────────────────────────────────────────────────────────────────────
# 5. 审批通过 → ApprovalEventType.APPROVED
# ─────────────────────────────────────────────────────────────────────────────


class TestApprovalActEmitsEvent:
    """场景：主管同意折扣申请（末节点 approve），系统发射 APPROVAL_APPROVED。"""

    @pytest.mark.asyncio
    async def test_act_approve_final_emits_approved_event(
        self,
        fake_emit,
        emitted_events: List[Dict[str, Any]],
        monkeypatch,
    ):
        """act_on_instance(approve, final) → emit ApprovalEventType.APPROVED"""
        import uuid

        _ensure_pkg("src.services", os.path.join(_OPS_SRC, "services"))
        instance_id = str(uuid.uuid4())

        _ae_mod = types.ModuleType("src.services.approval_engine")

        async def _fake_act(**kwargs):
            return {
                "id": instance_id,
                "status": "approved",
                "business_type": "discount",
                "business_id": "order-001",
                "amount_fen": 5000,
            }

        fake_engine = MagicMock()
        fake_engine.act = _fake_act
        _ae_mod.approval_engine = fake_engine
        sys.modules["src.services.approval_engine"] = _ae_mod

        _appr_spec2 = _ilu.spec_from_file_location(
            "src.api.approval_workflow_routes",
            os.path.join(_OPS_SRC, "api", "approval_workflow_routes.py"),
        )
        _appr_mod2 = _ilu.module_from_spec(_appr_spec2)  # type: ignore[arg-type]
        _appr_mod2.__package__ = "src.api"
        _appr_spec2.loader.exec_module(_appr_mod2)  # type: ignore[union-attr]
        sys.modules["src.api.approval_workflow_routes"] = _appr_mod2

        import src.api.approval_workflow_routes as aw  # noqa: E402

        monkeypatch.setattr(aw.asyncio, "create_task", lambda coro: asyncio.ensure_future(coro))
        monkeypatch.setattr(aw, "emit_event", fake_emit)

        body = MagicMock()
        body.approver_id = "manager-001"
        body.approver_name = "王主管"
        body.action = "approve"
        body.comment = "金额合规，同意"

        mock_db = AsyncMock()

        await aw.act_on_instance(instance_id=instance_id, body=body, x_tenant_id=TENANT_ID, db=mock_db)
        await asyncio.sleep(0)

        assert len(emitted_events) >= 1
        evt = emitted_events[0]
        assert evt["event_type"] == ApprovalEventType.APPROVED
        assert evt["stream_id"] == instance_id
        assert evt["payload"]["approver_id"] == "manager-001"
        assert evt["payload"]["amount_fen"] == 5000


# ─────────────────────────────────────────────────────────────────────────────
# 6. sad-path：纯查询 GET 不发射 emit_event
# ─────────────────────────────────────────────────────────────────────────────


class TestReadOnlyPathDoesNotEmit:
    """场景：GET 巡店历史列表（纯查询），不应发射任何 emit_event。"""

    @pytest.mark.asyncio
    async def test_list_inspections_does_not_emit_event(
        self,
        fake_emit,
        emitted_events: List[Dict[str, Any]],
        monkeypatch,
    ):
        """GET /inspections 纯查询不触发 emit_event。"""
        from src.api import inspection_routes as ir

        monkeypatch.setattr(ir.asyncio, "create_task", lambda coro: asyncio.ensure_future(coro))
        monkeypatch.setattr(ir, "emit_event", fake_emit)

        _exec_set_tenant_list = MagicMock()

        _exec_count_result = MagicMock()
        _exec_count_result.scalar_one.return_value = 0

        _exec_list_result = MagicMock()
        _exec_list_result.mappings.return_value.all.return_value = []

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[_exec_set_tenant_list, _exec_count_result, _exec_list_result])

        await ir.list_inspections(
            store_id=STORE_ID,
            inspector_id=None,
            status=None,
            start_date=None,
            end_date=None,
            page=1,
            size=20,
            x_tenant_id=TENANT_ID,
            db=mock_db,
        )
        await asyncio.sleep(0)

        assert len(emitted_events) == 0, (
            f"纯查询不应发射事件，实际发射了 {len(emitted_events)} 个"
        )
