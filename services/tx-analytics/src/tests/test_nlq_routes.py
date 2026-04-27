"""对话式经营助手 NLQ Engine 路由测试

覆盖端点：
  POST /api/v1/nlq/ask              — 自然语言提问（意图匹配+Claude兜底+空输入）
  GET  /api/v1/nlq/suggestions      — 推荐问题（时段动态）
  GET  /api/v1/nlq/history          — 历史记录
  POST /api/v1/nlq/execute-action   — 执行操作（已知+未知action）
  POST /api/v1/nlq/query            — 旧版兼容端点
"""

import sys
import types
from unittest.mock import AsyncMock, MagicMock

# ─── 预置假模块 ───


def _make_db_module():
    mod = types.ModuleType("shared.ontology.src.database")

    async def _fake_get_db_with_tenant(tenant_id: str):
        session = AsyncMock()
        # 默认 execute 返回空结果集
        mock_result = MagicMock()
        mock_result.keys.return_value = ["col1"]
        mock_result.fetchall.return_value = []
        session.execute.return_value = mock_result
        session.commit = AsyncMock()
        session.flush = AsyncMock()
        yield session

    mod.get_db_with_tenant = _fake_get_db_with_tenant
    return mod


def _setup_sys_modules():
    for name in ["shared", "shared.ontology", "shared.ontology.src"]:
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["shared.ontology.src.database"] = _make_db_module()

    if "structlog" not in sys.modules:
        mock_logger = MagicMock()
        mock_logger.bind.return_value = mock_logger
        sl = types.ModuleType("structlog")
        sl.get_logger = MagicMock(return_value=mock_logger)
        sys.modules["structlog"] = sl


_setup_sys_modules()

# ─── 导入路由（httpx 使用真实模块，由 starlette 依赖） ───
import os

_svc_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _svc_root not in sys.path:
    sys.path.insert(0, _svc_root)

import api.nlq_routes as _nlq_mod
from fastapi import FastAPI
from fastapi.testclient import TestClient

_app = FastAPI()
_app.include_router(_nlq_mod.router)
_client = TestClient(_app)

TENANT = "test-tenant-analytics"
HEADERS = {"X-Tenant-ID": TENANT}


# ═══════════════════════════════════════
# 意图匹配单元测试
# ═══════════════════════════════════════


class TestIntentMatching:
    """测试 50 个模板的正则意图匹配"""

    def test_revenue_today(self):
        result = _nlq_mod.match_intent("今天营业额多少")
        assert result is not None
        assert result["intent"] == "revenue_today"

    def test_revenue_yesterday(self):
        result = _nlq_mod.match_intent("昨天营业额")
        assert result is not None
        assert result["intent"] == "revenue_yesterday"

    def test_top_dishes(self):
        result = _nlq_mod.match_intent("最畅销的菜品是什么")
        assert result is not None
        assert result["intent"] == "top_dishes"

    def test_new_members(self):
        result = _nlq_mod.match_intent("今天新增会员多少")
        assert result is not None
        assert result["intent"] == "new_members_today"

    def test_repurchase_rate(self):
        result = _nlq_mod.match_intent("会员复购率是多少")
        assert result is not None
        assert result["intent"] == "repurchase_rate"

    def test_anomaly(self):
        result = _nlq_mod.match_intent("今天有什么异常吗")
        assert result is not None
        assert result["intent"] == "anomalies_today"

    def test_inventory_alert(self):
        result = _nlq_mod.match_intent("有哪些食材快断货了")
        assert result is not None
        assert result["intent"] == "inventory_alert"

    def test_gross_margin(self):
        result = _nlq_mod.match_intent("今天毛利多少")
        assert result is not None
        assert result["intent"] == "gross_margin"

    def test_no_match(self):
        result = _nlq_mod.match_intent("量子力学和相对论的关系")
        assert result is None

    def test_daily_report(self):
        result = _nlq_mod.match_intent("帮我生成日报")
        assert result is not None
        assert result["intent"] == "daily_report"

    def test_top_store(self):
        result = _nlq_mod.match_intent("哪个门店营业额最高")
        assert result is not None
        assert result["intent"] == "top_store"

    def test_void_orders(self):
        result = _nlq_mod.match_intent("今天废单多少")
        assert result is not None
        assert result["intent"] == "void_orders"

    def test_peak_hours(self):
        result = _nlq_mod.match_intent("今天客流分布怎样")
        assert result is not None
        assert result["intent"] == "peak_hours"

    def test_churned_members(self):
        result = _nlq_mod.match_intent("沉睡会员有多少")
        assert result is not None
        assert result["intent"] == "churned_members"

    def test_channel_breakdown(self):
        result = _nlq_mod.match_intent("堂食外卖占比如何")
        assert result is not None
        assert result["intent"] == "channel_breakdown"


# ═══════════════════════════════════════
# POST /api/v1/nlq/ask
# ═══════════════════════════════════════


class TestNLQAsk:
    def test_ask_returns_ok_with_intent(self):
        """命中模板的问题返回 ok:True + intent"""
        resp = _client.post(
            "/api/v1/nlq/ask",
            json={"question": "今天营业额多少"},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["intent"] == "revenue_today"
        assert body["data"]["session_id"]  # 非空
        assert body["data"]["source"] == "sql_template"

    def test_ask_returns_actions_for_inventory_alert(self):
        """库存预警问题返回可执行操作"""
        resp = _client.post(
            "/api/v1/nlq/ask",
            json={"question": "有哪些食材库存不足"},
            headers=HEADERS,
        )
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["intent"] == "inventory_alert"
        actions = body["data"]["actions"]
        assert len(actions) >= 1
        assert actions[0]["action_id"] == "create_purchase_order"

    def test_ask_with_context(self):
        """带上下文参数正常工作"""
        resp = _client.post(
            "/api/v1/nlq/ask",
            json={
                "question": "今天营业额多少",
                "context": {"store_id": "store-001"},
                "session_id": "test-session-123",
            },
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["session_id"] == "test-session-123"

    def test_ask_returns_chart_type(self):
        """返回建议图表类型"""
        resp = _client.post(
            "/api/v1/nlq/ask",
            json={"question": "最畅销的菜品"},
            headers=HEADERS,
        )
        body = resp.json()
        assert body["data"]["chart_type"] == "bar"

    def test_ask_empty_question_fails_validation(self):
        """空问题触发 Pydantic 校验 422"""
        resp = _client.post(
            "/api/v1/nlq/ask",
            json={"question": ""},
            headers=HEADERS,
        )
        assert resp.status_code == 422

    def test_ask_generated_at_present(self):
        """返回生成时间戳"""
        resp = _client.post(
            "/api/v1/nlq/ask",
            json={"question": "今天营业额"},
            headers=HEADERS,
        )
        body = resp.json()
        assert "generated_at" in body["data"]


# ═══════════════════════════════════════
# GET /api/v1/nlq/suggestions
# ═══════════════════════════════════════


class TestNLQSuggestions:
    def test_returns_ok_true(self):
        resp = _client.get("/api/v1/nlq/suggestions", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_returns_at_least_8_suggestions(self):
        """返回至少8条推荐（4基础+4时段）"""
        resp = _client.get("/api/v1/nlq/suggestions", headers=HEADERS)
        data = resp.json()["data"]
        assert len(data) >= 8

    def test_suggestions_have_required_fields(self):
        """每条建议含 id/text/category"""
        resp = _client.get("/api/v1/nlq/suggestions", headers=HEADERS)
        for item in resp.json()["data"]:
            assert "id" in item
            assert "text" in item
            assert "category" in item


# ═══════════════════════════════════════
# GET /api/v1/nlq/history
# ═══════════════════════════════════════


class TestNLQHistory:
    def test_returns_ok_true(self):
        resp = _client.get("/api/v1/nlq/history", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_returns_data_list(self):
        """返回 data 为列表"""
        resp = _client.get("/api/v1/nlq/history", headers=HEADERS)
        body = resp.json()
        assert isinstance(body["data"], list)


# ═══════════════════════════════════════
# POST /api/v1/nlq/execute-action
# ═══════════════════════════════════════


class TestNLQExecuteAction:
    def test_unknown_action_returns_error(self):
        """未知 action_id 返回 ok:False"""
        resp = _client.post(
            "/api/v1/nlq/execute-action",
            json={"action_id": "nonexistent_action"},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "UNKNOWN_ACTION"


# ═══════════════════════════════════════
# POST /api/v1/nlq/query (兼容旧端点)
# ═══════════════════════════════════════


class TestNLQQueryCompat:
    def test_query_compat_works(self):
        """旧版 /query 端点仍然可用"""
        resp = _client.post(
            "/api/v1/nlq/query",
            json={"question": "今天营业额多少"},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["intent"] == "revenue_today"


# ═══════════════════════════════════════
# 格式化辅助函数测试
# ═══════════════════════════════════════


class TestFormatHelpers:
    def test_fen_to_yuan(self):
        assert _nlq_mod._fen_to_yuan(123456) == "\u00a51,234.56"
        assert _nlq_mod._fen_to_yuan(0) == "\u00a50.00"

    def test_build_time_params(self):
        params = _nlq_mod._build_time_params()
        assert "today_start" in params
        assert "tomorrow_start" in params
        assert "week_start" in params
        assert "month_start" in params
        assert "today_date" in params

    def test_format_answer_no_rows(self):
        tpl = {"intent": "revenue_today", "answer_tpl": "test {revenue}"}
        result = _nlq_mod._format_answer(tpl, [])
        assert "暂无数据" in result

    def test_generate_actions_inventory(self):
        actions = _nlq_mod._generate_actions("inventory_alert", [])
        assert len(actions) >= 1
        assert actions[0]["action_id"] == "create_purchase_order"

    def test_generate_actions_empty(self):
        actions = _nlq_mod._generate_actions("revenue_today", [])
        assert actions == []
