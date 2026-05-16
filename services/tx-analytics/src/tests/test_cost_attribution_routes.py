"""cost_attribution_routes 测试 (PRD-11 sub-C / 2026-05-16).

覆盖端点:
  GET /api/v1/cost-attribution/orders/{order_id}
  GET /api/v1/cost-attribution/dishes/{dish_id}/summary
  GET /api/v1/cost-attribution/summary

mock 模式: 沿用 test_anomaly_routes.py — sys.modules 注入假
shared.ontology.src.database, FastAPI TestClient 跑.
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

# 路径设置 (与 anomaly 测试一致)
_svc_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _svc_root not in sys.path:
    sys.path.insert(0, _svc_root)

import api.cost_attribution_routes as _cost_mod  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

_app = FastAPI()
_app.include_router(_cost_mod.router)
_client = TestClient(_app)

TENANT = "test-tenant-cost-attr"
HEADERS = {"X-Tenant-ID": TENANT}


def _row(
    id="11111111-1111-1111-1111-111111111111",
    source_event_id="22222222-2222-2222-2222-222222222222",
    order_id="33333333-3333-3333-3333-333333333333",
    order_item_id="44444444-4444-4444-4444-444444444444",
    dish_id="55555555-5555-5555-5555-555555555555",
    method="even",
    share_count=2,
    bom_cost_total_fen=6800,
    shares=None,
    occurred_at=None,
):
    """构造 cost_attribution_summary Row-like MagicMock."""
    if shares is None:
        shares = [
            {"share_index": 0, "weight": "0.5", "attributed_cost_fen": 3400},
            {"share_index": 1, "weight": "0.5", "attributed_cost_fen": 3400},
        ]
    row = MagicMock()
    row.id = id
    row.source_event_id = source_event_id
    row.order_id = order_id
    row.order_item_id = order_item_id
    row.dish_id = dish_id
    row.method = method
    row.share_count = share_count
    row.bom_cost_total_fen = bom_cost_total_fen
    row.shares = shares
    row.occurred_at = occurred_at or datetime(2026, 5, 16, 12, 0, 0, tzinfo=timezone.utc)
    row.created_at = datetime(2026, 5, 16, 12, 0, 5, tzinfo=timezone.utc)
    return row


def _agg_row(share_count=2, event_count=10, total_bom_fen=68000, avg_bom_fen=6800):
    row = MagicMock()
    row.share_count = share_count
    row.event_count = event_count
    row.total_bom_fen = total_bom_fen
    row.avg_bom_fen = avg_bom_fen
    return row


def _summary_row(
    total_events=100,
    share_split_events=30,
    total_bom_fen=680000,
    avg_share_count=2.5,
    distinct_orders=80,
    distinct_dishes=15,
):
    row = MagicMock()
    row.total_events = total_events
    row.share_split_events = share_split_events
    row.total_bom_fen = total_bom_fen
    row.avg_share_count = avg_share_count
    row.distinct_orders = distinct_orders
    row.distinct_dishes = distinct_dishes
    return row


def _override_db(rows=None, agg_rows=None, summary_row=None):
    """构造一个 fake get_db_with_tenant 让 route 用 session execute 返回指定数据."""

    async def _fake(tenant_id: str):
        session = AsyncMock()
        results_queue = []
        # order 端点: 单 SELECT → fetchall
        # dish summary: 单 SELECT (GROUP BY) → fetchall
        # summary: 单 SELECT → fetchone
        # dlq list 等不在本测试

        async def _execute(*args, **kwargs):
            er = MagicMock()
            if rows is not None:
                er.fetchall.return_value = rows
            else:
                er.fetchall.return_value = []
            if agg_rows is not None and rows is None:
                er.fetchall.return_value = agg_rows
            if summary_row is not None:
                er.fetchone.return_value = summary_row
            else:
                er.fetchone.return_value = None
            return er

        session.execute = _execute
        session.commit = AsyncMock()
        yield session

    return _fake


# ═══════════════════════════════════════
# GET /api/v1/cost-attribution/orders/{order_id}
# ═══════════════════════════════════════


class TestGetOrderAttribution:
    def test_returns_ok_true_empty(self):
        from unittest.mock import patch

        with patch.object(_cost_mod, "get_db_with_tenant", _override_db(rows=[])):
            resp = _client.get(
                "/api/v1/cost-attribution/orders/33333333-3333-3333-3333-333333333333",
                headers=HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["order_id"] == "33333333-3333-3333-3333-333333333333"
        assert body["data"]["attributions"] == []
        assert body["data"]["summary"]["item_count"] == 0
        assert body["data"]["summary"]["total_bom_cost_fen"] == 0
        assert "generated_at" in body["data"]

    def test_returns_attributions_when_rows_present(self):
        from unittest.mock import patch

        rows = [_row(bom_cost_total_fen=6800), _row(bom_cost_total_fen=12000)]
        with patch.object(_cost_mod, "get_db_with_tenant", _override_db(rows=rows)):
            resp = _client.get(
                "/api/v1/cost-attribution/orders/33333333-3333-3333-3333-333333333333",
                headers=HEADERS,
            )
        body = resp.json()
        assert body["ok"] is True
        attributions = body["data"]["attributions"]
        assert len(attributions) == 2
        assert attributions[0]["bom_cost_total_fen"] == 6800
        assert attributions[0]["method"] == "even"
        assert attributions[0]["share_count"] == 2
        assert isinstance(attributions[0]["shares"], list)
        assert len(attributions[0]["shares"]) == 2
        # summary 累加
        assert body["data"]["summary"]["item_count"] == 2
        assert body["data"]["summary"]["total_bom_cost_fen"] == 18800

    def test_shares_as_json_string_parsed(self):
        """asyncpg 老版本 / 测试 mock 给字符串 shares — route 自行 json.loads."""
        from unittest.mock import patch

        r = _row(shares='[{"share_index":0,"weight":"1","attributed_cost_fen":6800}]')
        with patch.object(_cost_mod, "get_db_with_tenant", _override_db(rows=[r])):
            resp = _client.get(
                "/api/v1/cost-attribution/orders/33333333-3333-3333-3333-333333333333",
                headers=HEADERS,
            )
        body = resp.json()
        attributions = body["data"]["attributions"]
        assert len(attributions) == 1
        assert attributions[0]["shares"][0]["attributed_cost_fen"] == 6800


# ═══════════════════════════════════════
# GET /api/v1/cost-attribution/dishes/{dish_id}/summary
# ═══════════════════════════════════════


class TestGetDishSummary:
    def test_returns_distribution_and_summary(self):
        from unittest.mock import patch

        agg_rows = [
            _agg_row(share_count=2, event_count=10, total_bom_fen=68000, avg_bom_fen=6800),
            _agg_row(share_count=4, event_count=5, total_bom_fen=40000, avg_bom_fen=8000),
        ]
        with patch.object(_cost_mod, "get_db_with_tenant", _override_db(rows=agg_rows)):
            resp = _client.get(
                "/api/v1/cost-attribution/dishes/55555555-5555-5555-5555-555555555555/summary",
                headers=HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        dist = body["data"]["distribution"]
        assert len(dist) == 2
        assert dist[0]["share_count"] == 2
        assert dist[0]["event_count"] == 10
        s = body["data"]["summary"]
        assert s["total_events"] == 15
        assert s["total_bom_fen"] == 108000
        assert s["avg_bom_fen"] == 7200

    def test_date_filter_passes(self):
        """from/to 参数被接受且不报 422."""
        from unittest.mock import patch

        with patch.object(_cost_mod, "get_db_with_tenant", _override_db(rows=[])):
            resp = _client.get(
                "/api/v1/cost-attribution/dishes/55555555-5555-5555-5555-555555555555/summary"
                "?from=2026-05-01&to=2026-05-31",
                headers=HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["from"] == "2026-05-01"
        assert body["data"]["to"] == "2026-05-31"

    def test_invalid_date_returns_422(self):
        from unittest.mock import patch

        with patch.object(_cost_mod, "get_db_with_tenant", _override_db(rows=[])):
            resp = _client.get(
                "/api/v1/cost-attribution/dishes/55555555-5555-5555-5555-555555555555/summary"
                "?from=not-a-date",
                headers=HEADERS,
            )
        # FastAPI Query parsing 失败 → 422
        assert resp.status_code == 422


# ═══════════════════════════════════════
# GET /api/v1/cost-attribution/summary
# ═══════════════════════════════════════


class TestGetSummary:
    def test_returns_summary_when_row_present(self):
        from unittest.mock import patch

        srow = _summary_row()
        with patch.object(
            _cost_mod, "get_db_with_tenant", _override_db(summary_row=srow)
        ):
            resp = _client.get(
                "/api/v1/cost-attribution/summary?from=2026-05-01&to=2026-05-31",
                headers=HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        s = body["data"]["summary"]
        assert s["total_events"] == 100
        assert s["share_split_events"] == 30
        assert s["share_split_ratio"] == 0.3
        assert s["total_bom_fen"] == 680000
        assert s["avg_share_count"] == 2.5
        assert s["distinct_orders"] == 80
        assert s["distinct_dishes"] == 15

    def test_returns_zero_when_no_row(self):
        from unittest.mock import patch

        with patch.object(
            _cost_mod, "get_db_with_tenant", _override_db(summary_row=None)
        ):
            resp = _client.get(
                "/api/v1/cost-attribution/summary",
                headers=HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        s = body["data"]["summary"]
        assert s["total_events"] == 0
        assert s["share_split_ratio"] == 0.0


# ═══════════════════════════════════════
# 静默吞: route 不静默吞异常 (用 inspect 校验关键 except 块)
# ═══════════════════════════════════════


class TestNoSilentSwallow:
    def test_route_module_only_catches_sqlalchemy_error(self):
        """关键: route 内 except 必须是 SQLAlchemyError, 不是 broad Exception."""
        import inspect

        src = inspect.getsource(_cost_mod)
        # 不应出现 broad except Exception (CLAUDE.md 十四 异常处理)
        assert "except Exception" not in src, (
            "cost_attribution_routes 禁止 broad except Exception"
        )
