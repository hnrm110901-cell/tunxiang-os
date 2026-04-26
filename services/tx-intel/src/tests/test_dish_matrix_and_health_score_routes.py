"""菜品四象限 & 经营健康度评分 路由测试

覆盖：
  GET /api/v1/intel/dish-matrix               — 菜品四象限（DB数据 / 空数据回落mock / DB异常）
  GET /api/v1/intel/dish-matrix/recommendations — 建议列表（优先级过滤 / DB异常回落）
  GET /api/v1/intel/health-score              — 综合评分（正常 / DB异常回落 / store_id过滤）
  GET /api/v1/intel/health-score/breakdown    — 分项明细（正常 / DB异常回落）

测试策略：
  - 通过 app.dependency_overrides 注入 mock_db
  - AsyncMock.side_effect 顺序匹配路由内 execute 调用顺序
  - 覆盖 happy path + 空数据 + DB异常回落 + 参数校验
"""

import sys
import types
import uuid

# ─── 注入假模块 ───────────────────────────────────────────────────────────────

_fake_structlog = types.ModuleType("structlog")
_fake_structlog.get_logger = lambda: types.SimpleNamespace(
    warning=lambda *a, **kw: None,
    info=lambda *a, **kw: None,
)
sys.modules.setdefault("structlog", _fake_structlog)

_fake_sa = types.ModuleType("sqlalchemy")
_fake_sa.text = lambda sql: sql
_fake_sa_exc = types.ModuleType("sqlalchemy.exc")


class _SQLAlchemyError(Exception):
    pass


_fake_sa_exc.SQLAlchemyError = _SQLAlchemyError
_fake_sa_async = types.ModuleType("sqlalchemy.ext.asyncio")
_fake_sa_async.AsyncSession = object
sys.modules.setdefault("sqlalchemy", _fake_sa)
sys.modules.setdefault("sqlalchemy.exc", _fake_sa_exc)
sys.modules.setdefault("sqlalchemy.ext", types.ModuleType("sqlalchemy.ext"))
sys.modules.setdefault("sqlalchemy.ext.asyncio", _fake_sa_async)

# ─── 导入路由模块 ─────────────────────────────────────────────────────────────

import importlib.util
import pathlib

_base = pathlib.Path(__file__).parent.parent / "api"

_dm_spec = importlib.util.spec_from_file_location("dish_matrix_routes", _base / "dish_matrix_routes.py")
_dm_mod = importlib.util.module_from_spec(_dm_spec)
_dm_spec.loader.exec_module(_dm_mod)

_hs_spec = importlib.util.spec_from_file_location("health_score_routes", _base / "health_score_routes.py")
_hs_mod = importlib.util.module_from_spec(_hs_spec)
_hs_spec.loader.exec_module(_hs_mod)

from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

TENANT_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}


def _make_dm_app(mock_db: AsyncMock) -> TestClient:
    app = FastAPI()
    app.include_router(_dm_mod.router)

    async def _override():
        yield mock_db

    app.dependency_overrides[_dm_mod.get_db] = _override
    return TestClient(app, raise_server_exceptions=False)


def _make_hs_app(mock_db: AsyncMock) -> TestClient:
    app = FastAPI()
    app.include_router(_hs_mod.router)

    async def _override():
        yield mock_db

    app.dependency_overrides[_hs_mod.get_db] = _override
    return TestClient(app, raise_server_exceptions=False)


# ─── 工具函数 ─────────────────────────────────────────────────────────────────


def _scalar_mock(value):
    m = MagicMock()
    m.scalar.return_value = value
    return m


def _fetchone_mock(row):
    m = MagicMock()
    m.fetchone.return_value = row
    return m


def _fetchall_mock(rows):
    m = MagicMock()
    m.fetchall.return_value = rows
    return m


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/v1/intel/dish-matrix
# ═══════════════════════════════════════════════════════════════════════════════


class TestDishMatrix:
    """菜品四象限分析接口"""

    def _dish_rows(self):
        """伪造 fetchall 返回的菜品数据行（dish_name, dish_id, sales_count, gross_margin_pct）"""
        return [
            ("招牌红烧肉", uuid.uuid4(), 320, 0.68),
            ("辣椒炒肉", uuid.uuid4(), 280, 0.72),
            ("白米饭", uuid.uuid4(), 450, 0.35),
            ("老坛酸菜鱼", uuid.uuid4(), 380, 0.42),
            ("松茸炖土鸡", uuid.uuid4(), 45, 0.71),
            ("和牛刺身", uuid.uuid4(), 28, 0.65),
            ("茄子炒肉", uuid.uuid4(), 62, 0.28),
            ("素炒时蔬", uuid.uuid4(), 55, 0.22),
        ]

    def test_dish_matrix_happy_path_with_data(self):
        """DB 返回菜品数据 → 返回四象限分类结果，_is_mock=False"""
        mock_db = AsyncMock()
        dish_result = _fetchall_mock(self._dish_rows())
        # execute 调用：_set_rls + 菜品查询
        mock_db.execute = AsyncMock(side_effect=[MagicMock(), dish_result])
        client = _make_dm_app(mock_db)

        resp = client.get("/api/v1/intel/dish-matrix", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["_is_mock"] is False
        assert "quadrants" in data
        quadrants = data["quadrants"]
        # 四个象限都存在
        assert set(quadrants.keys()) >= {"star", "cash_cow", "question_mark", "dog"}
        assert data["metadata"]["total_dishes"] == 8

    def test_dish_matrix_empty_db_returns_mock(self):
        """DB 返回空列表 → 自动回落 mock 数据，_is_mock=True"""
        mock_db = AsyncMock()
        empty_result = _fetchall_mock([])
        mock_db.execute = AsyncMock(side_effect=[MagicMock(), empty_result])
        client = _make_dm_app(mock_db)

        resp = client.get("/api/v1/intel/dish-matrix", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["_is_mock"] is True

    def test_dish_matrix_db_error_returns_mock(self):
        """DB 异常 → 返回 mock 数据"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=_SQLAlchemyError("timeout"))
        client = _make_dm_app(mock_db)

        resp = client.get("/api/v1/intel/dish-matrix", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["_is_mock"] is True

    def test_dish_matrix_with_store_id(self):
        """传入 store_id 参数 → 正常处理（不报错）"""
        mock_db = AsyncMock()
        dish_result = _fetchall_mock(self._dish_rows())
        mock_db.execute = AsyncMock(side_effect=[MagicMock(), dish_result])
        client = _make_dm_app(mock_db)

        resp = client.get(
            "/api/v1/intel/dish-matrix?store_id=store-001",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_dish_matrix_period_days_validation(self):
        """period_days 超出范围（<7 或 >90）→ 422"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())
        client = _make_dm_app(mock_db)

        resp = client.get("/api/v1/intel/dish-matrix?period_days=3", headers=HEADERS)
        assert resp.status_code == 422

        resp2 = client.get("/api/v1/intel/dish-matrix?period_days=91", headers=HEADERS)
        assert resp2.status_code == 422

    def test_dish_matrix_missing_tenant_header(self):
        """缺少 X-Tenant-ID → 422"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())
        client = _make_dm_app(mock_db)
        resp = client.get("/api/v1/intel/dish-matrix")
        assert resp.status_code == 422

    def test_dish_matrix_invalid_tenant_id(self):
        """X-Tenant-ID 格式无效 → 400"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())
        client = _make_dm_app(mock_db)
        resp = client.get(
            "/api/v1/intel/dish-matrix",
            headers={"X-Tenant-ID": "not-uuid"},
        )
        assert resp.status_code == 400

    def test_dish_matrix_quadrant_classification_logic(self):
        """四象限分类：只有高销量+高毛利的菜进 star"""
        # 直接测试纯函数 _classify_quadrant
        assert _dm_mod._classify_quadrant(200, 0.7, 100, 0.5) == "star"
        assert _dm_mod._classify_quadrant(200, 0.3, 100, 0.5) == "cash_cow"
        assert _dm_mod._classify_quadrant(50, 0.7, 100, 0.5) == "question_mark"
        assert _dm_mod._classify_quadrant(50, 0.3, 100, 0.5) == "dog"


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/v1/intel/dish-matrix/recommendations
# ═══════════════════════════════════════════════════════════════════════════════


class TestDishRecommendations:
    """菜品运营建议接口"""

    def _dish_rows_with_dogs(self):
        return [
            ("招牌红烧肉", uuid.uuid4(), 320, 0.68),
            ("白米饭", uuid.uuid4(), 450, 0.35),
            ("茄子炒肉", uuid.uuid4(), 62, 0.28),
            ("素炒时蔬", uuid.uuid4(), 55, 0.22),
        ]

    def test_recommendations_happy_path(self):
        """正常场景 → 返回建议列表"""
        mock_db = AsyncMock()
        dish_result = _fetchall_mock(self._dish_rows_with_dogs())
        mock_db.execute = AsyncMock(side_effect=[MagicMock(), dish_result])
        client = _make_dm_app(mock_db)

        resp = client.get("/api/v1/intel/dish-matrix/recommendations", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert "recommendations" in data
        assert "total" in data

    def test_recommendations_priority_filter_high(self):
        """priority=high → 只返回 high 优先级建议（dog 象限）"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=_SQLAlchemyError("db error"))
        client = _make_dm_app(mock_db)

        resp = client.get(
            "/api/v1/intel/dish-matrix/recommendations?priority=high",
            headers=HEADERS,
        )
        body = resp.json()
        for rec in body["data"]["recommendations"]:
            assert rec["priority"] == "high"

    def test_recommendations_priority_filter_medium(self):
        """priority=medium → 只返回 medium 优先级（question_mark 象限）"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=_SQLAlchemyError("db error"))
        client = _make_dm_app(mock_db)

        resp = client.get(
            "/api/v1/intel/dish-matrix/recommendations?priority=medium",
            headers=HEADERS,
        )
        body = resp.json()
        for rec in body["data"]["recommendations"]:
            assert rec["priority"] == "medium"

    def test_recommendations_db_error_returns_mock(self):
        """DB 异常 → 返回 mock 建议，_is_mock=True"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=_SQLAlchemyError("timeout"))
        client = _make_dm_app(mock_db)

        resp = client.get("/api/v1/intel/dish-matrix/recommendations", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["_is_mock"] is True
        assert body["data"]["total"] >= 0

    def test_recommendations_schema(self):
        """响应结构包含必要字段"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=_SQLAlchemyError("db"))
        client = _make_dm_app(mock_db)
        resp = client.get("/api/v1/intel/dish-matrix/recommendations", headers=HEADERS)
        body = resp.json()
        assert "ok" in body
        assert "data" in body
        assert "error" in body
        assert "recommendations" in body["data"]
        assert "total" in body["data"]


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/v1/intel/health-score
# ═══════════════════════════════════════════════════════════════════════════════


class TestHealthScore:
    """经营健康度综合评分接口"""

    def _build_db_side_effects_normal(self) -> list:
        """
        health-score 查询顺序（_set_rls + 5个维度查询）：
          1. set_config
          2. _query_revenue_trend: 本月营收(fetchone) + 上月营收(fetchone) = 2次
          3. _query_cost_control:  本月revenue(scalar) + 本月cost(scalar) = 2次
          4. _query_customer_satisfaction: orders统计(fetchone) = 1次
          5. _query_operational_efficiency: avg_minutes(scalar) = 1次
          6. _query_inventory_health: expiry_count(scalar) = 1次
        总计 = 1 + 2 + 2 + 1 + 1 + 1 = 8次
        """
        effects = []
        # set_config
        effects.append(MagicMock())
        # revenue_trend: 本月 revenue=500000 days=20, 上月 revenue=400000 days=28
        r_this = MagicMock()
        r_this.fetchone.return_value = (500000, 20)
        effects.append(r_this)
        r_last = MagicMock()
        r_last.fetchone.return_value = (400000, 28)
        effects.append(r_last)
        # cost_control: revenue=500000, cost=200000 → ratio=40% → score=100
        effects.append(_scalar_mock(500000))
        effects.append(_scalar_mock(200000))
        # customer_satisfaction: completed=200, refunded=2 → rate=1% → score≈100
        r_cust = MagicMock()
        r_cust.fetchone.return_value = (200, 2)
        effects.append(r_cust)
        # operational_efficiency: avg_min=15 → score=100
        effects.append(_scalar_mock(15))
        # inventory_health: expiry_count=0 → score=100
        effects.append(_scalar_mock(0))
        return effects

    def test_health_score_happy_path(self):
        """正常场景 → 返回 0-100 评分，_is_mock=False"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=self._build_db_side_effects_normal())
        client = _make_hs_app(mock_db)

        resp = client.get("/api/v1/intel/health-score", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["_is_mock"] is False
        assert 0 <= data["overall_score"] <= 100
        assert data["grade"] in ("A", "B", "C", "D")
        assert len(data["dimensions"]) == 5

    def test_health_score_db_error_returns_mock(self):
        """DB 异常 → 回落 mock 数据，_is_mock=True"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=_SQLAlchemyError("connection refused"))
        client = _make_hs_app(mock_db)

        resp = client.get("/api/v1/intel/health-score", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["_is_mock"] is True
        assert 0 <= body["data"]["overall_score"] <= 100

    def test_health_score_with_store_id(self):
        """传入 store_id → 正常处理"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=self._build_db_side_effects_normal())
        client = _make_hs_app(mock_db)

        resp = client.get(
            "/api/v1/intel/health-score?store_id=store-abc",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_health_score_dimensions_structure(self):
        """dimensions 字段包含 key/label/score/weight/grade"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=_SQLAlchemyError("db"))
        client = _make_hs_app(mock_db)
        resp = client.get("/api/v1/intel/health-score", headers=HEADERS)
        dims = resp.json()["data"]["dimensions"]
        for dim in dims:
            assert "key" in dim
            assert "label" in dim
            assert "score" in dim
            assert "weight" in dim
            assert "grade" in dim

    def test_health_score_missing_tenant_header(self):
        """缺少 X-Tenant-ID → 422"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())
        client = _make_hs_app(mock_db)
        resp = client.get("/api/v1/intel/health-score")
        assert resp.status_code == 422

    def test_health_score_invalid_tenant_id(self):
        """X-Tenant-ID 格式无效 → 400"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())
        client = _make_hs_app(mock_db)
        resp = client.get(
            "/api/v1/intel/health-score",
            headers={"X-Tenant-ID": "bad-id"},
        )
        assert resp.status_code == 400

    def test_health_score_alerts_present(self):
        """alerts 字段存在（可为空列表）"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=_SQLAlchemyError("db"))
        client = _make_hs_app(mock_db)
        resp = client.get("/api/v1/intel/health-score", headers=HEADERS)
        data = resp.json()["data"]
        assert "alerts" in data
        assert isinstance(data["alerts"], list)

    def test_health_score_grade_calculation(self):
        """纯函数 _score_to_grade 返回正确等级"""
        assert _hs_mod._score_to_grade(95) == "A"
        assert _hs_mod._score_to_grade(80) == "B"
        assert _hs_mod._score_to_grade(65) == "C"
        assert _hs_mod._score_to_grade(50) == "D"

    def test_health_score_calc_overall_weighted(self):
        """纯函数 _calc_overall 加权计算正确"""
        dim_scores = {
            "revenue_trend": 100.0,
            "cost_control": 100.0,
            "customer_satisfaction": 100.0,
            "operational_efficiency": 100.0,
            "inventory_health": 100.0,
        }
        result = _hs_mod._calc_overall(dim_scores)
        assert result == 100.0

    def test_health_score_build_alerts_triggers(self):
        """_build_alerts 在分数低时触发警报"""
        low_scores = {
            "revenue_trend": 50,
            "cost_control": 40,
            "customer_satisfaction": 50,
            "operational_efficiency": 50,
            "inventory_health": 40,
        }
        alerts = _hs_mod._build_alerts(low_scores)
        assert len(alerts) >= 3


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/v1/intel/health-score/breakdown
# ═══════════════════════════════════════════════════════════════════════════════


class TestHealthScoreBreakdown:
    """分项评分明细接口"""

    def _build_db_effects(self) -> list:
        """与 health-score 相同的 8次 execute 顺序"""
        effects = [MagicMock()]  # set_config
        r1 = MagicMock()
        r1.fetchone.return_value = (300000, 15)
        effects.append(r1)
        r2 = MagicMock()
        r2.fetchone.return_value = (280000, 28)
        effects.append(r2)
        effects.append(_scalar_mock(300000))  # revenue
        effects.append(_scalar_mock(130000))  # cost (ratio≈43% → score=100)
        r3 = MagicMock()
        r3.fetchone.return_value = (150, 1)  # refund_rate≈0.66%
        effects.append(r3)
        effects.append(_scalar_mock(12))  # avg_min=12 → score=100
        effects.append(_scalar_mock(3))  # expiry_count=3 → score=92
        return effects

    def test_breakdown_happy_path(self):
        """正常场景 → 返回含 breakdown 的分项明细"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=self._build_db_effects())
        client = _make_hs_app(mock_db)

        resp = client.get("/api/v1/intel/health-score/breakdown", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["_is_mock"] is False
        assert "breakdown" in data
        assert len(data["breakdown"]) == 5
        # 每个 breakdown 条目包含 benchmark
        for item in data["breakdown"]:
            assert "benchmark" in item
            assert "weighted_contribution" in item

    def test_breakdown_db_error_returns_mock(self):
        """DB 异常 → 返回 mock 分项明细，_is_mock=True"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=_SQLAlchemyError("db down"))
        client = _make_hs_app(mock_db)

        resp = client.get("/api/v1/intel/health-score/breakdown", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["_is_mock"] is True
        assert len(body["data"]["breakdown"]) == 5

    def test_breakdown_weighted_contribution_correct(self):
        """weighted_contribution = score × weight，精度2位小数"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=self._build_db_effects())
        client = _make_hs_app(mock_db)

        resp = client.get("/api/v1/intel/health-score/breakdown", headers=HEADERS)
        for item in resp.json()["data"]["breakdown"]:
            expected = round(item["score"] * item["weight"], 2)
            assert abs(item["weighted_contribution"] - expected) < 0.01

    def test_breakdown_missing_tenant_header(self):
        """缺少 X-Tenant-ID → 422"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())
        client = _make_hs_app(mock_db)
        resp = client.get("/api/v1/intel/health-score/breakdown")
        assert resp.status_code == 422

    def test_breakdown_invalid_tenant_id(self):
        """X-Tenant-ID 格式无效 → 400"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())
        client = _make_hs_app(mock_db)
        resp = client.get(
            "/api/v1/intel/health-score/breakdown",
            headers={"X-Tenant-ID": "bad-id"},
        )
        assert resp.status_code == 400

    def test_breakdown_schema_complete(self):
        """响应包含完整 {ok, data, error} 结构"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=_SQLAlchemyError("db"))
        client = _make_hs_app(mock_db)
        resp = client.get("/api/v1/intel/health-score/breakdown", headers=HEADERS)
        body = resp.json()
        assert "ok" in body
        assert "data" in body
        assert "error" in body
        assert "overall_score" in body["data"]
        assert "grade" in body["data"]
        assert "alerts" in body["data"]
