"""菜品生命周期 API 路由测试

覆盖 dish_lifecycle_routes.py 和 lifecycle_router 的主要端点：
  - GET  /health-scores
  - GET  /health-scores/{dish_id}
  - GET  /sellout-warnings/{store_id}
  - GET  /api/v1/menu/lifecycle/stages
  - GET  /api/v1/menu/lifecycle/report
  - POST /api/v1/dishes/{id}/lifecycle/advance
  - POST /api/v1/dishes/{id}/lifecycle/retire

使用 FastAPI TestClient + dependency_overrides，不连接真实数据库。
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ─── 构建测试用 FastAPI App ────────────────────────────────────────────────────

# 用独立 app 避免依赖完整 main.py 的启动逻辑
app = FastAPI()

# 延迟导入路由，确保 sys.path 设置正确
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

from api.dish_lifecycle_routes import lifecycle_router, router

from shared.ontology.src.database import get_db

app.include_router(router, prefix="/dish-lifecycle")
app.include_router(lifecycle_router)  # lifecycle_router 自带 /api/v1 前缀

# ─── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
DISH_ID = str(uuid.uuid4())
OPERATOR_ID = str(uuid.uuid4())

HEADERS = {"X-Tenant-ID": TENANT_ID}


# ─── Mock DB 工厂 ──────────────────────────────────────────────────────────────


def _make_mock_db() -> AsyncMock:
    """返回不连接真实数据库的 AsyncSession mock"""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.close = AsyncMock()
    return db


def _override_get_db():
    """依赖覆盖：用 AsyncMock 替代真实 DB session"""
    db = _make_mock_db()
    # 默认 execute 返回空结果
    mock_result = MagicMock()
    mock_result.fetchone.return_value = None
    mock_result.fetchall.return_value = []
    mock_result.scalar_one_or_none.return_value = None
    db.execute.return_value = mock_result
    return db


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def override_db():
    """每个测试自动覆盖 get_db 依赖"""
    app.dependency_overrides[get_db] = _override_get_db
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


# ─── 1. 健康评分列表 ──────────────────────────────────────────────────────────


class TestHealthScores:
    def test_list_health_scores_returns_200(self, client):
        """GET /dish-lifecycle/health-scores 返回 200，结构正确"""
        mock_score = MagicMock()
        mock_score.total_score = 75.0
        mock_score.to_dict.return_value = {"dish_id": DISH_ID, "total_score": 75.0}

        with patch("api.dish_lifecycle_routes.DishHealthScoreEngine") as MockEngine:
            instance = MockEngine.return_value
            instance.score_all_dishes = AsyncMock(return_value=[mock_score])

            resp = client.get(
                "/dish-lifecycle/health-scores",
                params={"store_id": STORE_ID},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "scores" in body["data"]
        assert body["data"]["count"] == 1
        assert body["data"]["low_health_count"] == 0

    def test_list_health_scores_missing_store_id_returns_422(self, client):
        """GET /dish-lifecycle/health-scores 缺少必填 store_id 返回 422"""
        resp = client.get("/dish-lifecycle/health-scores", headers=HEADERS)
        assert resp.status_code == 422

    def test_get_single_health_score_returns_200(self, client):
        """GET /dish-lifecycle/health-scores/{dish_id} 菜品存在时返回 200"""
        mock_score = MagicMock()
        mock_score.total_score = 55.0
        mock_score.to_dict.return_value = {
            "dish_id": DISH_ID,
            "total_score": 55.0,
            "margin_score": 20.0,
            "sales_rank_score": 20.0,
            "review_score": 15.0,
        }

        with patch("api.dish_lifecycle_routes.DishHealthScoreEngine") as MockEngine:
            instance = MockEngine.return_value
            instance.score_dish = AsyncMock(return_value=mock_score)

            resp = client.get(
                f"/dish-lifecycle/health-scores/{DISH_ID}",
                params={"store_id": STORE_ID},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["score"]["dish_id"] == DISH_ID

    def test_get_single_health_score_not_found(self, client):
        """GET /dish-lifecycle/health-scores/{dish_id} 菜品不存在时返回 ok=False"""
        with patch("api.dish_lifecycle_routes.DishHealthScoreEngine") as MockEngine:
            instance = MockEngine.return_value
            instance.score_dish = AsyncMock(return_value=None)

            resp = client.get(
                f"/dish-lifecycle/health-scores/{DISH_ID}",
                params={"store_id": STORE_ID},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "DISH_NOT_FOUND"


# ─── 2. 沽清预警 ──────────────────────────────────────────────────────────────


class TestSelloutWarnings:
    def test_sellout_warnings_returns_200(self, client):
        """GET /dish-lifecycle/sellout-warnings/{store_id} 返回 200"""
        mock_warning = MagicMock()
        mock_warning.to_dict.return_value = {
            "dish_id": DISH_ID,
            "days_remaining": 1.5,
            "warning_level": "critical",
        }

        with patch("api.dish_lifecycle_routes.DishLifecycleService") as MockSvc:
            instance = MockSvc.return_value
            instance.check_sellout_warnings = AsyncMock(return_value=[mock_warning])

            resp = client.get(
                f"/dish-lifecycle/sellout-warnings/{STORE_ID}",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["count"] == 1
        assert len(body["data"]["warnings"]) == 1

    def test_sellout_warnings_empty_list(self, client):
        """无预警时返回空列表"""
        with patch("api.dish_lifecycle_routes.DishLifecycleService") as MockSvc:
            instance = MockSvc.return_value
            instance.check_sellout_warnings = AsyncMock(return_value=[])

            resp = client.get(
                f"/dish-lifecycle/sellout-warnings/{STORE_ID}",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["data"]["count"] == 0


# ─── 3. 生命周期阶段列表（lifecycle_router） ──────────────────────────────────


class TestLifecycleStages:
    def test_list_stages_returns_200(self, client):
        """GET /api/v1/menu/lifecycle/stages 返回 200，包含6个阶段"""
        resp = client.get("/api/v1/menu/lifecycle/stages", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total"] == 6
        stage_names = [s["stage"] for s in body["data"]["stages"]]
        assert "research" in stage_names
        assert "discontinued" in stage_names

    def test_stages_order_is_correct(self, client):
        """阶段列表按 order 字段从小到大排列"""
        resp = client.get("/api/v1/menu/lifecycle/stages", headers=HEADERS)
        stages = resp.json()["data"]["stages"]
        orders = [s["order"] for s in stages]
        assert orders == sorted(orders)


# ─── 4. 生命周期报告（lifecycle_router） ──────────────────────────────────────


class TestLifecycleReport:
    def test_lifecycle_report_returns_200(self, client):
        """GET /api/v1/menu/lifecycle/report 返回 200，包含各阶段统计"""
        # mock execute 返回 COUNT 数据
        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("full", 10),
            ("pilot", 3),
            ("sunset", 1),
        ]
        mock_db.execute.return_value = mock_result

        app.dependency_overrides[get_db] = lambda: mock_db

        resp = client.get("/api/v1/menu/lifecycle/report", headers=HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "stages" in body["data"]
        assert "total" in body["data"]
        # 确认 full 阶段有 10 个菜品
        full_stage = next(s for s in body["data"]["stages"] if s["stage"] == "full")
        assert full_stage["count"] == 10

    def test_lifecycle_report_with_store_filter(self, client):
        """GET /api/v1/menu/lifecycle/report?store_id=... 带门店筛选"""
        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("full", 5)]
        mock_db.execute.return_value = mock_result

        app.dependency_overrides[get_db] = lambda: mock_db

        resp = client.get(
            "/api/v1/menu/lifecycle/report",
            params={"store_id": STORE_ID},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ─── 5. 推进生命周期（lifecycle_router） ──────────────────────────────────────


class TestAdvanceLifecycle:
    def test_advance_lifecycle_success(self, client):
        """POST /api/v1/dishes/{id}/lifecycle/advance 正常推进返回 200"""
        dish_uuid = str(uuid.uuid4())

        # mock: 菜品存在，当前 stage=testing
        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (
            dish_uuid,  # id
            "剁椒鱼头",  # dish_name
            "testing",  # lifecycle_stage
            False,  # is_deleted
        )
        mock_db.execute.return_value = mock_result

        app.dependency_overrides[get_db] = lambda: mock_db

        resp = client.post(
            f"/api/v1/dishes/{dish_uuid}/lifecycle/advance",
            json={
                "target_stage": "pilot",
                "reason": "评测通过，推进试卖",
                "operator_id": OPERATOR_ID,
            },
            headers=HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["to_stage"] == "pilot"
        assert body["data"]["from_stage"] == "testing"

    def test_advance_lifecycle_invalid_stage_returns_400(self, client):
        """POST /api/v1/dishes/{id}/lifecycle/advance 无效 stage 返回 400"""
        dish_uuid = str(uuid.uuid4())
        resp = client.post(
            f"/api/v1/dishes/{dish_uuid}/lifecycle/advance",
            json={
                "target_stage": "invalid_stage",
                "reason": "测试",
                "operator_id": OPERATOR_ID,
            },
            headers=HEADERS,
        )
        assert resp.status_code == 400

    def test_advance_lifecycle_to_discontinued_returns_400(self, client):
        """POST advance 不允许直接推进到 discontinued"""
        dish_uuid = str(uuid.uuid4())
        resp = client.post(
            f"/api/v1/dishes/{dish_uuid}/lifecycle/advance",
            json={
                "target_stage": "discontinued",
                "reason": "应该用 retire 接口",
                "operator_id": OPERATOR_ID,
            },
            headers=HEADERS,
        )
        assert resp.status_code == 400

    def test_advance_lifecycle_dish_not_found_returns_404(self, client):
        """POST advance 菜品不存在时返回 404"""
        dish_uuid = str(uuid.uuid4())

        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_db.execute.return_value = mock_result

        app.dependency_overrides[get_db] = lambda: mock_db

        resp = client.post(
            f"/api/v1/dishes/{dish_uuid}/lifecycle/advance",
            json={
                "target_stage": "pilot",
                "reason": "推进",
                "operator_id": OPERATOR_ID,
            },
            headers=HEADERS,
        )
        assert resp.status_code == 404


# ─── 6. 下线菜品（retire） ────────────────────────────────────────────────────


class TestRetireDish:
    def test_retire_dish_success(self, client):
        """POST /api/v1/dishes/{id}/lifecycle/retire 正常下线返回 200"""
        dish_uuid = str(uuid.uuid4())

        mock_db = _make_mock_db()

        # 第一次 execute：查询菜品基本信息
        dish_result = MagicMock()
        dish_result.fetchone.return_value = (
            dish_uuid,
            "小炒肉",
            "full",
            False,
        )

        # 第二次 execute：UPDATE dishes（无返回值需求）
        update_result = MagicMock()
        update_result.fetchone.return_value = None

        # 第三次 execute：UPDATE channel_menu_items RETURNING channel
        channels_result = MagicMock()
        channels_result.fetchall.return_value = [("dine_in",), ("takeaway",)]

        mock_db.execute.side_effect = [
            AsyncMock(return_value=dish_result)(),
            AsyncMock(return_value=update_result)(),
            AsyncMock(return_value=channels_result)(),
        ]

        app.dependency_overrides[get_db] = lambda: mock_db

        resp = client.post(
            f"/api/v1/dishes/{dish_uuid}/lifecycle/retire",
            headers=HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["current_stage"] == "discontinued"
        assert "dine_in" in body["data"]["channels_retired"]

    def test_retire_dish_not_found_returns_404(self, client):
        """POST retire 菜品不存在时返回 404"""
        dish_uuid = str(uuid.uuid4())

        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_db.execute.return_value = mock_result

        app.dependency_overrides[get_db] = lambda: mock_db

        resp = client.post(
            f"/api/v1/dishes/{dish_uuid}/lifecycle/retire",
            headers=HEADERS,
        )
        assert resp.status_code == 404
