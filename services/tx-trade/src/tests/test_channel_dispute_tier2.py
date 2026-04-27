"""test_channel_dispute_tier2 — Sprint E4 异议工作流 Service+路由覆盖

Tier 2 覆盖（CLAUDE.md §17）：
  1. open_dispute_below_threshold_auto_accepts
     — claim ≤ threshold 且 type 不在 NON_AUTO_ACCEPT_TYPES → state=auto_accepted
       + decision_reason 含 "auto_accept under threshold"
       + 旁路 DISPUTE_OPENED + DISPUTE_AUTO_ACCEPTED 两条事件
  2. open_dispute_above_threshold_pending
     — claim > threshold → state=pending；不发 AUTO_ACCEPTED 事件
  3. resolve_dispute_accepts_with_reason_and_operator
     — pending → accepted 时 decision_by/at/reason 全部落地，发 DISPUTE_RESOLVED
  4. resolve_already_resolved_dispute_returns_409
     — state=accepted/rejected/auto_accepted 时再次 resolve → 409 ALREADY_RESOLVED
  5. cross_tenant_resolve_403
     — body.tenant_id != X-Tenant-ID → 403 TENANT_MISMATCH
"""

from __future__ import annotations

import os
import sys
import types
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

# ─── 路径准备 ──────────────────────────────────────────────────────────────────

_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
_ROOT_DIR = os.path.abspath(os.path.join(_TESTS_DIR, "..", "..", "..", ".."))

for _p in [_SRC_DIR, _ROOT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _ensure_pkg(name: str, path: str) -> None:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod


_ensure_pkg("src", _SRC_DIR)
_ensure_pkg("src.api", os.path.join(_SRC_DIR, "api"))
_ensure_pkg("src.services", os.path.join(_SRC_DIR, "services"))
_ensure_pkg("src.schemas", os.path.join(_SRC_DIR, "schemas"))
_ensure_pkg("src.security", os.path.join(_SRC_DIR, "security"))

os.environ.setdefault("TX_AUTH_ENABLED", "false")

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.schemas.channel_dispute import (  # noqa: E402
    DEFAULT_AUTO_ACCEPT_THRESHOLD_FEN,
    OpenDisputeRequest,
)
from src.services.channel_dispute_service import (  # noqa: E402
    ChannelDisputeService,
    DisputeAlreadyResolvedError,
)

TENANT_A = "00000000-0000-0000-0000-00000000000a"
STORE_ID = str(uuid.uuid4())
CANONICAL_ORDER_ID = str(uuid.uuid4())


def _build_open_request(
    *,
    tenant_id: str = TENANT_A,
    external_dispute_id: str = "DISP-001",
    dispute_type: str = "missing_item",
    claimed_amount_fen: int = 3000,
) -> OpenDisputeRequest:
    return OpenDisputeRequest(
        tenant_id=uuid.UUID(tenant_id),
        store_id=uuid.UUID(STORE_ID),
        canonical_order_id=uuid.UUID(CANONICAL_ORDER_ID),
        channel_code="meituan",
        external_dispute_id=external_dispute_id,
        dispute_type=dispute_type,  # type: ignore[arg-type]
        claimed_amount_fen=claimed_amount_fen,
        opened_at=datetime.now(timezone.utc),
        payload={"raw": "platform-original"},
    )


def _row(req: OpenDisputeRequest, *, state: str = "pending", **overrides) -> dict:
    now = datetime.now(timezone.utc)
    base = {
        "id": uuid.uuid4(),
        "tenant_id": req.tenant_id,
        "store_id": req.store_id,
        "canonical_order_id": req.canonical_order_id,
        "channel_code": req.channel_code,
        "external_dispute_id": req.external_dispute_id,
        "dispute_type": req.dispute_type,
        "claimed_amount_fen": req.claimed_amount_fen,
        "state": state,
        "auto_accept_threshold_fen": DEFAULT_AUTO_ACCEPT_THRESHOLD_FEN,
        "decision_reason": None,
        "decision_by": None,
        "decision_at": None,
        "payload": req.payload,
        "opened_at": req.opened_at,
        "created_at": now,
        "updated_at": now,
        "is_deleted": False,
    }
    base.update(overrides)
    return base


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


# ─── Service 用例 ────────────────────────────────────────────────────────────


class TestChannelDisputeServiceTier2:
    @pytest.mark.asyncio
    async def test_open_dispute_below_threshold_auto_accepts(self):
        """claim ≤ threshold + type 可 auto_accept → state=auto_accepted，发 2 条事件。"""
        req = _build_open_request(claimed_amount_fen=3000)  # < 5000
        # service 层先 SELECT 后 INSERT；模拟 INSERT 后 DB 返回的行 state=auto_accepted
        new_row = _row(req, state="auto_accepted",
                       decision_reason="auto_accept under threshold (claim=3000 <= threshold=5000)",
                       decision_at=datetime.now(timezone.utc))

        emitted_events = []

        async def fake_emit(**kwargs):
            emitted_events.append(kwargs)
            return "evt-id"

        db = _make_db()
        svc = ChannelDisputeService(db, tenant_id=TENANT_A)

        with patch.object(
            svc._repo, "get_by_external", AsyncMock(return_value=None)
        ), patch.object(
            svc._repo, "insert", AsyncMock(return_value=new_row)
        ) as mock_insert, patch(
            "src.services.channel_dispute_service.emit_event", new=fake_emit
        ):
            record, created = await svc.open_dispute(
                req, auto_accept_threshold_fen=DEFAULT_AUTO_ACCEPT_THRESHOLD_FEN
            )
            import asyncio as _aio
            pending = [t for t in _aio.all_tasks() if t is not _aio.current_task()]
            await _aio.gather(*pending, return_exceptions=True)

        assert created is True
        assert record.state == "auto_accepted"
        assert "auto_accept under threshold" in (record.decision_reason or "")
        # insert 时传入的 state 应为 auto_accepted
        called_kwargs = mock_insert.await_args.kwargs
        assert called_kwargs["state"] == "auto_accepted"
        assert called_kwargs["auto_accept_threshold_fen"] == DEFAULT_AUTO_ACCEPT_THRESHOLD_FEN
        # 两条事件：DISPUTE_OPENED + DISPUTE_AUTO_ACCEPTED
        types_emitted = {e["event_type"].value for e in emitted_events}
        assert "channel.dispute_opened" in types_emitted
        assert "channel.dispute_auto_accepted" in types_emitted

    @pytest.mark.asyncio
    async def test_open_dispute_above_threshold_pending(self):
        """claim > threshold → state=pending；只发 DISPUTE_OPENED 一条事件。"""
        req = _build_open_request(claimed_amount_fen=10000)  # > 5000
        new_row = _row(req, state="pending")

        emitted_events = []

        async def fake_emit(**kwargs):
            emitted_events.append(kwargs)
            return "evt-id"

        db = _make_db()
        svc = ChannelDisputeService(db, tenant_id=TENANT_A)

        with patch.object(
            svc._repo, "get_by_external", AsyncMock(return_value=None)
        ), patch.object(
            svc._repo, "insert", AsyncMock(return_value=new_row)
        ) as mock_insert, patch(
            "src.services.channel_dispute_service.emit_event", new=fake_emit
        ):
            record, created = await svc.open_dispute(
                req, auto_accept_threshold_fen=DEFAULT_AUTO_ACCEPT_THRESHOLD_FEN
            )
            import asyncio as _aio
            pending = [t for t in _aio.all_tasks() if t is not _aio.current_task()]
            await _aio.gather(*pending, return_exceptions=True)

        assert created is True
        assert record.state == "pending"
        assert mock_insert.await_args.kwargs["state"] == "pending"
        types_emitted = {e["event_type"].value for e in emitted_events}
        assert "channel.dispute_opened" in types_emitted
        assert "channel.dispute_auto_accepted" not in types_emitted

    @pytest.mark.asyncio
    async def test_resolve_dispute_accepts_with_reason_and_operator(self):
        """pending → accepted 时 decision_by/at/reason 全部落地，发 DISPUTE_RESOLVED。"""
        req = _build_open_request(claimed_amount_fen=10000)
        existing_row = _row(req, state="pending")
        operator_id = str(uuid.uuid4())
        decision_at_mock = datetime.now(timezone.utc)
        resolved_row = _row(
            req,
            state="accepted",
            decision_reason="customer provided photo evidence",
            decision_by=uuid.UUID(operator_id),
            decision_at=decision_at_mock,
        )
        resolved_row["id"] = existing_row["id"]

        emitted_events = []

        async def fake_emit(**kwargs):
            emitted_events.append(kwargs)
            return "evt-id"

        db = _make_db()
        svc = ChannelDisputeService(db, tenant_id=TENANT_A)

        with patch.object(
            svc._repo, "get", AsyncMock(return_value=existing_row)
        ), patch.object(
            svc._repo, "resolve", AsyncMock(return_value=resolved_row)
        ) as mock_resolve, patch(
            "src.services.channel_dispute_service.emit_event", new=fake_emit
        ):
            record = await svc.resolve_dispute(
                dispute_id=str(existing_row["id"]),
                decision="accepted",
                reason="customer provided photo evidence",
                operator_id=operator_id,
            )
            import asyncio as _aio
            pending = [t for t in _aio.all_tasks() if t is not _aio.current_task()]
            await _aio.gather(*pending, return_exceptions=True)

        assert record.state == "accepted"
        assert record.decision_reason == "customer provided photo evidence"
        assert str(record.decision_by) == operator_id
        # resolve 调用参数包含 operator_id 与 reason
        ka = mock_resolve.await_args.kwargs
        assert ka["new_state"] == "accepted"
        assert ka["decision_reason"] == "customer provided photo evidence"
        assert ka["decision_by"] == operator_id
        # 事件
        assert any(
            e["event_type"].value == "channel.dispute_resolved" for e in emitted_events
        )

    @pytest.mark.asyncio
    async def test_resolve_already_resolved_dispute_returns_409(self):
        """已 accepted 的异议再次裁决 → DisputeAlreadyResolvedError（路由层 409）。"""
        req = _build_open_request()
        already_row = _row(req, state="accepted")  # 终态

        db = _make_db()
        svc = ChannelDisputeService(db, tenant_id=TENANT_A)

        with patch.object(
            svc._repo, "get", AsyncMock(return_value=already_row)
        ), patch.object(
            svc._repo, "resolve", AsyncMock()
        ) as mock_resolve:
            with pytest.raises(DisputeAlreadyResolvedError):
                await svc.resolve_dispute(
                    dispute_id=str(already_row["id"]),
                    decision="rejected",
                    reason="late",
                    operator_id=str(uuid.uuid4()),
                )

        # 已是终态，不应再调用 resolve
        mock_resolve.assert_not_awaited()


# ─── 路由层用例 ────────────────────────────────────────────────────────────


class TestChannelDisputeRouterTier2:
    def test_cross_tenant_resolve_403(self):
        """body.tenant_id != X-Tenant-ID 时 POST resolve → 403 TENANT_MISMATCH。"""
        from shared.ontology.src.database import get_db
        from src.api.channel_dispute_routes import router as dr

        test_app = FastAPI(title="test-app")
        test_app.include_router(dr)

        async def fake_get_db():
            yield AsyncMock()

        test_app.dependency_overrides[get_db] = fake_get_db
        client = TestClient(test_app)

        body = {
            "tenant_id": str(uuid.UUID(TENANT_A)),
            "decision": "accepted",
            "reason": "ok",
        }
        # X-Tenant-ID 故意与 body.tenant_id 不一致
        resp = client.post(
            f"/api/v1/channels/disputes/{uuid.uuid4()}/resolve",
            headers={"X-Tenant-ID": "00000000-0000-0000-0000-000000000099"},
            json=body,
        )
        assert resp.status_code == 403
        # 可能是 TENANT_MISMATCH 或 USER_TENANT_MISMATCH（看哪一层先命中）
        assert resp.json()["detail"] in ("TENANT_MISMATCH", "USER_TENANT_MISMATCH")
