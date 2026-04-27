"""外部数据采集层路由测试 — test_intel_router.py

覆盖 routers/intel_router.py（11 个端点）：
  GET    /intel/competitors                   — 列出竞对品牌（基础+过滤参数）
  POST   /intel/competitors                   — 新增竞对品牌
  GET    /intel/competitors/{id}/snapshots    — 竞对快照列表
  POST   /intel/competitors/{id}/snapshot     — 手动触发竞对快照（外部服务调用）
  GET    /intel/reviews                       — 点评情报列表（多种过滤参数）
  POST   /intel/reviews/collect              — 手动触发点评采集
  GET    /intel/trends                       — 市场趋势信号列表
  POST   /intel/trends/scan/dishes           — 菜品趋势扫描
  POST   /intel/trends/scan/ingredients      — 食材趋势扫描
  POST   /intel/tasks                        — 创建采集任务
  GET    /intel/tasks                        — 列出采集任务
  PATCH  /intel/tasks/{id}                   — 更新采集任务状态

测试策略：
  - 通过 app.dependency_overrides 注入 mock DB，避免真实数据库调用
  - 外部服务（CompetitorMonitorExtService、ReviewCollectorService、TrendScannerService）
    通过 sys.modules 预注入桩模块
  - 覆盖 happy path、参数过滤、错误场景（无更新字段、404）
"""

import importlib.util
import pathlib
import sys
import types
import uuid

# ─── 注入假模块（路由顶层 import 所需）──────────────────────────────────────

_fake_structlog = types.ModuleType("structlog")
_fake_structlog.get_logger = lambda *a, **kw: types.SimpleNamespace(
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

# ─── 外部服务桩（intel_router.py 内部 import）──────────────────────────────

_svc_mod = types.ModuleType("services")
sys.modules.setdefault("services", _svc_mod)


# competitor_monitor_ext 桩
class _CompetitorMonitorExtService:
    def __init__(self, db):
        pass

    async def run_competitor_snapshot(self, tenant_id, competitor_id):
        return {"ok": True, "snapshot_id": str(uuid.uuid4())}


_competitor_ext_mod = types.ModuleType("services.competitor_monitor_ext")
_competitor_ext_mod.CompetitorMonitorExtService = _CompetitorMonitorExtService
sys.modules["services.competitor_monitor_ext"] = _competitor_ext_mod


# review_collector 桩
class _ReviewCollectorService:
    def __init__(self, db):
        pass

    async def collect_store_reviews(self, tenant_id, source, platform_store_id, is_own_store, days):
        return {"ok": True, "collected": 5}


_review_collector_mod = types.ModuleType("services.review_collector")
_review_collector_mod.ReviewCollectorService = _ReviewCollectorService
sys.modules["services.review_collector"] = _review_collector_mod


# trend_scanner 桩
class _TrendScannerService:
    def __init__(self, db):
        pass

    async def scan_dish_trends(self, tenant_id, city, cuisine_type):
        return {"ok": True, "trends_found": 3}

    async def scan_ingredient_trends(self, tenant_id, category, region):
        return {"ok": True, "trends_found": 2}


_trend_scanner_mod = types.ModuleType("services.trend_scanner")
_trend_scanner_mod.TrendScannerService = _TrendScannerService
sys.modules["services.trend_scanner"] = _trend_scanner_mod

# pydantic（路由用到 BaseModel / Field）
try:
    import pydantic  # noqa: F401
except ImportError:
    pass

# ─── 加载被测路由 ────────────────────────────────────────────────────────────

from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

_route_path = pathlib.Path(__file__).parent.parent / "routers" / "intel_router.py"
_spec = importlib.util.spec_from_file_location("intel_router", _route_path)
_intel_router_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_intel_router_mod)

TENANT_ID = str(uuid.uuid4())
COMP_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}


def _make_app(mock_db: AsyncMock) -> TestClient:
    """创建挂载 intel_router 的 FastAPI 测试 app"""
    app = FastAPI()
    app.include_router(_intel_router_mod.router)

    async def _override_get_db():
        yield mock_db

    app.dependency_overrides[_intel_router_mod.get_db] = _override_get_db
    return TestClient(app, raise_server_exceptions=False)


def _scalar_mock(value):
    m = MagicMock()
    m.scalar.return_value = value
    return m


def _fetchall_mock(rows):
    m = MagicMock()
    m.fetchall.return_value = rows
    return m


def _mapping_row(*values, keys=None):
    """构建模拟数据库行（支持 _mapping 访问）"""
    keys = keys or []
    d = dict(zip(keys, values))
    m = MagicMock()
    m._mapping = d
    return m


# ═══════════════════════════════════════════════════════════════════════════════
# 测试：GET /intel/competitors — 列出竞对品牌
# ═══════════════════════════════════════════════════════════════════════════════


class TestListCompetitors:
    """GET /intel/competitors — 3 个测试"""

    def test_list_competitors_empty(self):
        """无竞对品牌时返回空列表"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_mock(0),  # COUNT
                _fetchall_mock([]),  # SELECT rows
            ]
        )
        client = _make_app(mock_db)
        resp = client.get("/intel/competitors", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total"] == 0
        assert body["data"]["items"] == []

    def test_list_competitors_with_rows(self):
        """有数据时正确返回分页信息"""
        mock_db = AsyncMock()
        row = _mapping_row("长沙麻辣香锅", "湘菜", "mid_range", keys=["name", "cuisine_type", "price_tier"])
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_mock(1),
                _fetchall_mock([row]),
            ]
        )
        client = _make_app(mock_db)
        resp = client.get("/intel/competitors", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 1
        assert len(data["items"]) == 1

    def test_list_competitors_missing_tenant_id(self):
        """缺少 X-Tenant-ID 时返回 422"""
        mock_db = AsyncMock()
        client = _make_app(mock_db)
        resp = client.get("/intel/competitors")
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# 测试：POST /intel/competitors — 新增竞对品牌
# ═══════════════════════════════════════════════════════════════════════════════


class TestCreateCompetitor:
    """POST /intel/competitors — 2 个测试"""

    def test_create_competitor_success(self):
        """成功创建竞对品牌，返回 201"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())
        mock_db.commit = AsyncMock()
        client = _make_app(mock_db)
        resp = client.post(
            "/intel/competitors",
            headers=HEADERS,
            json={
                "name": "竞品A",
                "cuisine_type": "川菜",
                "price_tier": "mid_range",
                "city": "长沙",
                "district": "芙蓉区",
                "platform_ids": {"meituan": "mt_001"},
                "is_active": True,
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["ok"] is True
        assert "id" in body["data"]
        assert body["data"]["name"] == "竞品A"

    def test_create_competitor_invalid_price_tier(self):
        """price_tier 不合法时返回 422"""
        mock_db = AsyncMock()
        client = _make_app(mock_db)
        resp = client.post(
            "/intel/competitors",
            headers=HEADERS,
            json={"name": "竞品B", "price_tier": "invalid_tier"},
        )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# 测试：GET /intel/competitors/{id}/snapshots
# ═══════════════════════════════════════════════════════════════════════════════


class TestListCompetitorSnapshots:
    """GET /intel/competitors/{id}/snapshots — 1 个测试"""

    def test_list_snapshots(self):
        """正确分页返回竞对快照"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_mock(0),
                _fetchall_mock([]),
            ]
        )
        client = _make_app(mock_db)
        resp = client.get(f"/intel/competitors/{COMP_ID}/snapshots", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 测试：GET /intel/reviews — 点评情报
# ═══════════════════════════════════════════════════════════════════════════════


class TestListReviews:
    """GET /intel/reviews — 2 个测试"""

    def test_list_reviews_no_filter(self):
        """无过滤参数时正常返回"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_mock(2),
                _fetchall_mock([]),
            ]
        )
        client = _make_app(mock_db)
        resp = client.get("/intel/reviews", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 2

    def test_list_reviews_filter_own_store(self):
        """is_own_store=true 过滤时正常返回"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_mock(1),
                _fetchall_mock([]),
            ]
        )
        client = _make_app(mock_db)
        resp = client.get("/intel/reviews?is_own_store=true&source=meituan", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 测试：GET /intel/trends — 市场趋势
# ═══════════════════════════════════════════════════════════════════════════════


class TestListTrends:
    """GET /intel/trends — 1 个测试"""

    def test_list_trends_with_min_score(self):
        """min_score 过滤正常工作"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_mock(5),
                _fetchall_mock([]),
            ]
        )
        client = _make_app(mock_db)
        resp = client.get("/intel/trends?min_score=60", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 5


# ═══════════════════════════════════════════════════════════════════════════════
# 测试：POST /intel/trends/scan/dishes — 菜品趋势扫描
# ═══════════════════════════════════════════════════════════════════════════════


class TestScanDishTrends:
    """POST /intel/trends/scan/dishes — 1 个测试"""

    def test_scan_dish_trends_success(self):
        """菜品趋势扫描成功，调用外部服务"""
        mock_db = AsyncMock()
        client = _make_app(mock_db)
        resp = client.post(
            "/intel/trends/scan/dishes",
            headers=HEADERS,
            json={"city": "长沙", "cuisine_type": "湘菜"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# 测试：POST /intel/trends/scan/ingredients — 食材趋势扫描
# ═══════════════════════════════════════════════════════════════════════════════


class TestScanIngredientTrends:
    """POST /intel/trends/scan/ingredients — 1 个测试"""

    def test_scan_ingredient_trends_success(self):
        """食材趋势扫描成功"""
        mock_db = AsyncMock()
        client = _make_app(mock_db)
        resp = client.post(
            "/intel/trends/scan/ingredients",
            headers=HEADERS,
            json={"category": "海鲜", "region": "湖南"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# 测试：POST /intel/tasks — 创建采集任务
# ═══════════════════════════════════════════════════════════════════════════════


class TestCreateCrawlTask:
    """POST /intel/tasks — 2 个测试"""

    def test_create_task_success(self):
        """成功创建采集任务"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())
        mock_db.commit = AsyncMock()
        client = _make_app(mock_db)
        resp = client.post(
            "/intel/tasks",
            headers=HEADERS,
            json={
                "task_type": "competitor_snapshot",
                "target_config": {"brand_id": COMP_ID},
                "schedule_cron": "0 8 * * *",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["task_type"] == "competitor_snapshot"
        assert body["data"]["status"] == "active"

    def test_create_task_invalid_type(self):
        """task_type 不合法时返回 422"""
        mock_db = AsyncMock()
        client = _make_app(mock_db)
        resp = client.post(
            "/intel/tasks",
            headers=HEADERS,
            json={"task_type": "unknown_task"},
        )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# 测试：GET /intel/tasks — 列出采集任务
# ═══════════════════════════════════════════════════════════════════════════════


class TestListCrawlTasks:
    """GET /intel/tasks — 1 个测试"""

    def test_list_tasks(self):
        """正常列出采集任务"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_mock(3),
                _fetchall_mock([]),
            ]
        )
        client = _make_app(mock_db)
        resp = client.get("/intel/tasks", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 3


# ═══════════════════════════════════════════════════════════════════════════════
# 测试：PATCH /intel/tasks/{id} — 更新采集任务
# ═══════════════════════════════════════════════════════════════════════════════


class TestUpdateCrawlTask:
    """PATCH /intel/tasks/{id} — 2 个测试"""

    def test_update_task_status_success(self):
        """更新任务状态成功"""
        task_id = str(uuid.uuid4())
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        client = _make_app(mock_db)
        resp = client.patch(
            f"/intel/tasks/{task_id}",
            headers=HEADERS,
            json={"status": "paused"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["updated"] is True

    def test_update_task_no_fields(self):
        """未提供更新字段时返回 400"""
        task_id = str(uuid.uuid4())
        mock_db = AsyncMock()
        client = _make_app(mock_db)
        resp = client.patch(
            f"/intel/tasks/{task_id}",
            headers=HEADERS,
            json={},
        )
        assert resp.status_code == 400
