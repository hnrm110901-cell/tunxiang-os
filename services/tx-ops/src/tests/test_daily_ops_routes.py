"""日清日结路由层测试 — 覆盖 daily_ops.py HTTP 端点（共 12 个测试）

覆盖范围（daily_ops.py，prefix=/api/v1/ops）：
  GET  /daily/{store_id}                          — 正常返回 / 带 date 参数
  POST /daily/{store_id}/nodes/{node_code}/start  — 正常 / 未知 node → ok=False
  POST /daily/{store_id}/nodes/{node_code}/complete — 正常提交
  POST /daily/{store_id}/nodes/{node_code}/skip   — 正常跳过
  GET  /daily/{store_id}/timeline                 — 正常时间轴
  GET  /daily/{store_id}/review                   — 正常复盘
  GET  /daily/{store_id}/rectifications           — 正常列表 / 带 status 参数
  POST /daily/{store_id}/rectifications           — 正常创建

技术约束：
  - sys.modules 存根注入（在导入路由前完成）
  - daily_ops.py 内联 import services，patch 对应函数
  - 无真实 DB（daily_ops.py 不使用 get_db）
"""
from __future__ import annotations

import sys
import types
import uuid
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  sys.modules 存根注入（必须在导入路由前完成）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _ensure_stub(module_path: str, attrs: dict | None = None) -> types.ModuleType:
    if module_path not in sys.modules:
        mod = types.ModuleType(module_path)
        if attrs:
            for k, v in attrs.items():
                setattr(mod, k, v)
        sys.modules[module_path] = mod
    return sys.modules[module_path]


# shared.ontology 层（daily_ops.py 不直接 import，但子模块可能需要）
_ensure_stub("shared")
_ensure_stub("shared.ontology")
_ensure_stub("shared.ontology.src")
_db_mod = _ensure_stub("shared.ontology.src.database")
if not hasattr(_db_mod, "get_db"):
    async def _placeholder_get_db():  # pragma: no cover
        yield None
    _db_mod.get_db = _placeholder_get_db

# structlog 存根
if "structlog" not in sys.modules:
    _sl = types.ModuleType("structlog")
    _sl.get_logger = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
    sys.modules["structlog"] = _sl

# daily_ops_service 存根（daily_ops.py 内联 import，预占位）
_ensure_stub("src")
_ensure_stub("src.services")
_daily_svc = _ensure_stub("src.services.daily_ops_service")
_daily_svc.compute_flow_progress = MagicMock(
    return_value={"completed": 0, "total": 8, "percentage": 0, "status": "not_started", "current_node": "E1"}
)
_daily_svc.get_flow_timeline = MagicMock(
    return_value=[{"node": f"E{i}", "status": "pending"} for i in range(1, 9)]
)
_daily_svc.get_node_definition = MagicMock(
    return_value={"name": "开店准备", "check_items": []}
)
_daily_svc.compute_node_check_result = MagicMock(
    return_value={"passed": True, "score": 100}
)

# ── 导入路由 ────────────────────────────────────────────────────────────────────
from ..api.daily_ops import router as daily_ops_router  # noqa: E402

# ── FastAPI 应用 ─────────────────────────────────────────────────────────────────
app = FastAPI()
app.include_router(daily_ops_router)
client = TestClient(app)

# ── 常量 ──────────────────────────────────────────────────────────────────────────
STORE = str(uuid.uuid4())


# ══════════════════════════════════════════════════════════════════════════════════
#  GET /api/v1/ops/daily/{store_id}
# ══════════════════════════════════════════════════════════════════════════════════


class TestGetDailyFlow:
    """GET /api/v1/ops/daily/{store_id}"""

    def test_get_daily_flow_success(self):
        """正常返回当日流程状态。"""
        with patch("src.services.daily_ops_service.compute_flow_progress",
                   return_value={"completed": 3, "total": 8, "status": "in_progress", "current_node": "E4"}
                   ) as mock_progress, \
             patch("src.services.daily_ops_service.get_flow_timeline",
                   return_value=[]) as mock_timeline:
            resp = client.get(f"/api/v1/ops/daily/{STORE}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["store_id"] == STORE
        assert body["data"]["date"] == "today"

    def test_get_daily_flow_with_date_param(self):
        """带 date 参数时，响应中 date 字段等于传入值。"""
        resp = client.get(f"/api/v1/ops/daily/{STORE}?date=2026-04-06")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["date"] == "2026-04-06"

    def test_get_daily_flow_contains_progress_and_timeline(self):
        """响应 data 包含 progress 和 timeline 字段。"""
        resp = client.get(f"/api/v1/ops/daily/{STORE}")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "progress" in data
        assert "timeline" in data


# ══════════════════════════════════════════════════════════════════════════════════
#  POST /api/v1/ops/daily/{store_id}/nodes/{node_code}/start
# ══════════════════════════════════════════════════════════════════════════════════


class TestStartNode:
    """POST /api/v1/ops/daily/{store_id}/nodes/{node_code}/start"""

    def test_start_node_success(self):
        """已知节点 E1，正常返回 in_progress 状态。"""
        with patch("src.services.daily_ops_service.get_node_definition",
                   return_value={"name": "开店准备", "check_items": [{"id": "c1", "label": "检查"}]}):
            resp = client.post(f"/api/v1/ops/daily/{STORE}/nodes/E1/start")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["node_code"] == "E1"
        assert body["data"]["status"] == "in_progress"

    def test_start_node_unknown_returns_error(self):
        """未知节点（get_node_definition 返回空），返回 ok=False + INVALID_NODE。"""
        with patch("src.services.daily_ops_service.get_node_definition", return_value={}):
            resp = client.post(f"/api/v1/ops/daily/{STORE}/nodes/E99/start")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "INVALID_NODE"

    def test_start_node_with_operator_id(self):
        """带 operator_id 参数仍正常返回。"""
        with patch("src.services.daily_ops_service.get_node_definition",
                   return_value={"name": "营业巡航", "check_items": []}):
            resp = client.post(f"/api/v1/ops/daily/{STORE}/nodes/E2/start?operator_id=op-001")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ══════════════════════════════════════════════════════════════════════════════════
#  POST /api/v1/ops/daily/{store_id}/nodes/{node_code}/complete
# ══════════════════════════════════════════════════════════════════════════════════


class TestCompleteNode:
    """POST /api/v1/ops/daily/{store_id}/nodes/{node_code}/complete"""

    def test_complete_node_success(self):
        """提交检查结果，返回 completed 状态及 check_result。"""
        payload = [{"item_id": "c1", "passed": True}]
        with patch("src.services.daily_ops_service.compute_node_check_result",
                   return_value={"passed": True, "score": 100}):
            resp = client.post(
                f"/api/v1/ops/daily/{STORE}/nodes/E1/complete",
                json=payload,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["status"] == "completed"
        assert body["data"]["node_code"] == "E1"

    def test_complete_node_empty_results(self):
        """空检查结果列表仍可提交成功。"""
        with patch("src.services.daily_ops_service.compute_node_check_result",
                   return_value={"passed": False, "score": 0}):
            resp = client.post(f"/api/v1/ops/daily/{STORE}/nodes/E3/complete", json=[])
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ══════════════════════════════════════════════════════════════════════════════════
#  POST /api/v1/ops/daily/{store_id}/nodes/{node_code}/skip
# ══════════════════════════════════════════════════════════════════════════════════


class TestSkipNode:
    """POST /api/v1/ops/daily/{store_id}/nodes/{node_code}/skip"""

    def test_skip_node_success(self):
        """正常跳过节点，返回 skipped 状态。"""
        resp = client.post(f"/api/v1/ops/daily/{STORE}/nodes/E5/skip?reason=设备故障")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["status"] == "skipped"
        assert body["data"]["node_code"] == "E5"
        assert body["data"]["reason"] == "设备故障"

    def test_skip_node_default_reason(self):
        """不带 reason 参数，reason 默认为空字符串。"""
        resp = client.post(f"/api/v1/ops/daily/{STORE}/nodes/E2/skip")
        assert resp.status_code == 200
        assert resp.json()["data"]["reason"] == ""


# ══════════════════════════════════════════════════════════════════════════════════
#  GET /api/v1/ops/daily/{store_id}/timeline
# ══════════════════════════════════════════════════════════════════════════════════


class TestGetTimeline:
    """GET /api/v1/ops/daily/{store_id}/timeline"""

    def test_get_timeline_success(self):
        """正常返回 timeline 列表。"""
        fake_timeline = [{"node": "E1", "status": "completed"}, {"node": "E2", "status": "pending"}]
        with patch("src.services.daily_ops_service.get_flow_timeline", return_value=fake_timeline):
            resp = client.get(f"/api/v1/ops/daily/{STORE}/timeline")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert isinstance(body["data"]["timeline"], list)


# ══════════════════════════════════════════════════════════════════════════════════
#  GET /api/v1/ops/daily/{store_id}/review
# ══════════════════════════════════════════════════════════════════════════════════


class TestGetReview:
    """GET /api/v1/ops/daily/{store_id}/review"""

    def test_get_review_success(self):
        """正常返回复盘数据（E7），包含三个固定字段。"""
        resp = client.get(f"/api/v1/ops/daily/{STORE}/review")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert "top3_issues" in data
        assert "agent_suggestions" in data
        assert "kpi_comparison" in data


# ══════════════════════════════════════════════════════════════════════════════════
#  GET & POST /api/v1/ops/daily/{store_id}/rectifications
# ══════════════════════════════════════════════════════════════════════════════════


class TestRectifications:
    """GET/POST /api/v1/ops/daily/{store_id}/rectifications"""

    def test_list_rectifications_success(self):
        """正常返回整改任务列表，含 items 和 total。"""
        resp = client.get(f"/api/v1/ops/daily/{STORE}/rectifications")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "items" in body["data"]
        assert "total" in body["data"]

    def test_list_rectifications_with_status_filter(self):
        """带 status 过滤参数仍返回 200。"""
        resp = client.get(f"/api/v1/ops/daily/{STORE}/rectifications?status=pending")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_create_rectification_success(self):
        """POST 新建整改任务，返回 rectification_id 和 pending 状态。"""
        payload = {"title": "卫生问题整改", "priority": "high"}
        resp = client.post(f"/api/v1/ops/daily/{STORE}/rectifications", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["rectification_id"] == "new"
        assert body["data"]["status"] == "pending"
