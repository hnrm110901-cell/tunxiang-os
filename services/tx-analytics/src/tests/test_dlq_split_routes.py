"""dlq_split_routes 测试 (PRD-11 sub-C / 2026-05-16).

覆盖端点:
  GET  /api/v1/dlq/split-attribution?status=&limit=&offset=
  GET  /api/v1/dlq/split-attribution/{id}
  POST /api/v1/dlq/split-attribution/{id}/acknowledge

mock 模式: 同 test_cost_attribution_routes — sys.modules 注入假
shared.ontology.src.database.
"""

from __future__ import annotations

import os
import sys
import types
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock


# ─── 假模块注入 ───────────────────────────────────────────────────────


def _setup_structlog_stub():
    """仅在 structlog 未真实可用时 stub. 避免污染 shared.ontology.src.database
    (CLAUDE memory: stub setdefault ordering fragile, 优先用真模块 + patch.object)."""
    if "structlog" not in sys.modules:
        sl = types.ModuleType("structlog")
        sl.get_logger = MagicMock(
            return_value=MagicMock(
                warning=MagicMock(),
                info=MagicMock(),
            )
        )
        sys.modules["structlog"] = sl


_setup_structlog_stub()

_svc_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _svc_root not in sys.path:
    sys.path.insert(0, _svc_root)

import api.dlq_split_routes as _dlq_mod  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

_app = FastAPI()
_app.include_router(_dlq_mod.router)
_client = TestClient(_app)

TENANT = "test-tenant-dlq"
HEADERS = {"X-Tenant-ID": TENANT}


def _dlq_row(
    id="aaaaaaaa-1111-1111-1111-111111111111",
    event_id="bbbbbbbb-2222-2222-2222-222222222222",
    event_type="inventory.split_attributed",
    order_id="cccccccc-3333-3333-3333-333333333333",
    error_class="ValueError",
    error_msg="dish 不允许分享 (allow_share=False)",
    payload=None,
    acknowledged_at=None,
):
    if payload is None:
        payload = {"order_id": str(order_id), "items": [{"share_count": 3}]}
    row = MagicMock()
    row.id = id
    row.event_id = event_id
    row.event_type = event_type
    row.order_id = order_id
    row.order_item_id = None
    row.dish_id = None
    row.error_class = error_class
    row.error_msg = error_msg
    row.payload = payload
    row.occurred_at = datetime(2026, 5, 16, 12, 0, 0, tzinfo=timezone.utc)
    row.created_at = datetime(2026, 5, 16, 12, 0, 5, tzinfo=timezone.utc)
    row.acknowledged_at = acknowledged_at
    row.acknowledged_by = None
    row.ack_notes = None
    return row


def _override_db(*, list_rows=None, unack_row=None, detail_row=None, update_row=None):
    """构造 fake get_db_with_tenant.

    list_rows: 第一个 execute 返回 fetchall
    unack_row: 第二个 execute 返回 fetchone (列表端点的 unack count)
    detail_row: detail endpoint 返回 fetchone
    update_row: acknowledge endpoint 返回 fetchone
    """

    async def _fake(tenant_id: str):
        session = AsyncMock()
        call_count = {"n": 0}

        async def _execute(*args, **kwargs):
            er = MagicMock()
            call_count["n"] += 1
            n = call_count["n"]
            if list_rows is not None and n == 1:
                er.fetchall.return_value = list_rows
                er.fetchone.return_value = None
                return er
            if unack_row is not None and n == 2:
                er.fetchone.return_value = unack_row
                er.fetchall.return_value = []
                return er
            if detail_row is not None:
                er.fetchone.return_value = detail_row
                er.fetchall.return_value = []
                return er
            if update_row is not None:
                er.fetchone.return_value = update_row
                er.fetchall.return_value = []
                return er
            er.fetchall.return_value = []
            er.fetchone.return_value = None
            return er

        session.execute = _execute
        session.commit = AsyncMock()
        yield session

    return _fake


def _unack_count_row(count=0):
    row = MagicMock()
    row.unack_count = count
    return row


def _update_row(id="aaaaaaaa-1111-1111-1111-111111111111"):
    row = MagicMock()
    row.id = id
    return row


# ═══════════════════════════════════════
# GET /api/v1/dlq/split-attribution
# ═══════════════════════════════════════


class TestListDlq:
    def test_returns_empty_list_default(self):
        from unittest.mock import patch

        with patch.object(
            _dlq_mod,
            "get_db_with_tenant",
            _override_db(list_rows=[], unack_row=_unack_count_row(0)),
        ):
            resp = _client.get(
                "/api/v1/dlq/split-attribution", headers=HEADERS
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["items"] == []
        assert body["data"]["page"]["limit"] == 50
        assert body["data"]["summary"]["unack_count"] == 0

    def test_returns_rows_with_unack_count(self):
        from unittest.mock import patch

        rows = [_dlq_row(), _dlq_row(id="dddddddd-4444-4444-4444-444444444444")]
        with patch.object(
            _dlq_mod,
            "get_db_with_tenant",
            _override_db(list_rows=rows, unack_row=_unack_count_row(5)),
        ):
            resp = _client.get(
                "/api/v1/dlq/split-attribution?status=unack&limit=10",
                headers=HEADERS,
            )
        body = resp.json()
        assert len(body["data"]["items"]) == 2
        assert body["data"]["items"][0]["error_class"] == "ValueError"
        assert body["data"]["page"]["count"] == 2
        assert body["data"]["page"]["limit"] == 10
        assert body["data"]["summary"]["unack_count"] == 5

    def test_status_filter_unack_ack_all(self):
        from unittest.mock import patch

        for s in ("unack", "ack", "all"):
            with patch.object(
                _dlq_mod,
                "get_db_with_tenant",
                _override_db(list_rows=[], unack_row=_unack_count_row(0)),
            ):
                resp = _client.get(
                    f"/api/v1/dlq/split-attribution?status={s}",
                    headers=HEADERS,
                )
            assert resp.status_code == 200, f"status={s} failed"

    def test_invalid_status_returns_400(self):
        from unittest.mock import patch

        with patch.object(
            _dlq_mod,
            "get_db_with_tenant",
            _override_db(list_rows=[], unack_row=_unack_count_row(0)),
        ):
            resp = _client.get(
                "/api/v1/dlq/split-attribution?status=bogus", headers=HEADERS
            )
        assert resp.status_code == 400

    def test_limit_bounds(self):
        """limit 超 200 → 422 (Query ge/le validation)."""
        from unittest.mock import patch

        with patch.object(
            _dlq_mod,
            "get_db_with_tenant",
            _override_db(list_rows=[], unack_row=_unack_count_row(0)),
        ):
            resp = _client.get(
                "/api/v1/dlq/split-attribution?limit=999", headers=HEADERS
            )
        assert resp.status_code == 422


# ═══════════════════════════════════════
# GET /api/v1/dlq/split-attribution/{id}
# ═══════════════════════════════════════


class TestGetDetail:
    def test_returns_detail(self):
        from unittest.mock import patch

        row = _dlq_row()
        with patch.object(
            _dlq_mod, "get_db_with_tenant", _override_db(detail_row=row)
        ):
            resp = _client.get(
                "/api/v1/dlq/split-attribution/aaaaaaaa-1111-1111-1111-111111111111",
                headers=HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["error_class"] == "ValueError"
        assert body["data"]["acknowledged_at"] is None
        assert isinstance(body["data"]["payload"], dict)

    def test_returns_404_when_missing(self):
        from unittest.mock import patch

        with patch.object(
            _dlq_mod, "get_db_with_tenant", _override_db(detail_row=None)
        ):
            resp = _client.get(
                "/api/v1/dlq/split-attribution/notfound-uuid", headers=HEADERS
            )
        assert resp.status_code == 404


# ═══════════════════════════════════════
# POST /api/v1/dlq/split-attribution/{id}/acknowledge
# ═══════════════════════════════════════


class TestAcknowledge:
    def test_ack_success(self):
        from unittest.mock import patch

        with patch.object(
            _dlq_mod, "get_db_with_tenant", _override_db(update_row=_update_row())
        ):
            resp = _client.post(
                "/api/v1/dlq/split-attribution/aaaaaaaa-1111-1111-1111-111111111111/acknowledge",
                json={
                    "notes": "确认后已通知供应链",
                    "acknowledged_by_user_id": "11111111-aaaa-aaaa-aaaa-111111111111",
                },
                headers=HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["id"] == "aaaaaaaa-1111-1111-1111-111111111111"
        assert "acknowledged_at" in body["data"]

    def test_ack_returns_404_when_already_acked(self):
        from unittest.mock import patch

        # UPDATE 返回 None = 已 ack 或不存在
        with patch.object(
            _dlq_mod, "get_db_with_tenant", _override_db(update_row=None)
        ):
            resp = _client.post(
                "/api/v1/dlq/split-attribution/aaaaaaaa-1111-1111-1111-111111111111/acknowledge",
                json={"notes": ""},
                headers=HEADERS,
            )
        assert resp.status_code == 404

    def test_invalid_user_id_returns_422(self):
        from unittest.mock import patch

        with patch.object(
            _dlq_mod, "get_db_with_tenant", _override_db(update_row=_update_row())
        ):
            resp = _client.post(
                "/api/v1/dlq/split-attribution/aaaaaaaa-1111-1111-1111-111111111111/acknowledge",
                json={
                    "notes": "",
                    "acknowledged_by_user_id": "not-a-uuid",
                },
                headers=HEADERS,
            )
        assert resp.status_code == 422

    def test_minimal_payload_ok(self):
        """空 notes / 无 user_id 也允许 (运营批量自动 ack 场景)."""
        from unittest.mock import patch

        with patch.object(
            _dlq_mod, "get_db_with_tenant", _override_db(update_row=_update_row())
        ):
            resp = _client.post(
                "/api/v1/dlq/split-attribution/aaaaaaaa-1111-1111-1111-111111111111/acknowledge",
                json={},
                headers=HEADERS,
            )
        assert resp.status_code == 200


# ═══════════════════════════════════════
# 静默吞防御
# ═══════════════════════════════════════


class TestNoSilentSwallow:
    def test_no_broad_except_exception(self):
        import inspect

        src = inspect.getsource(_dlq_mod)
        assert "except Exception" not in src, (
            "dlq_split_routes 禁止 broad except Exception"
        )
