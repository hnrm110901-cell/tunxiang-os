"""扩展 API 路由测试 — 品牌发布 & 渠道映射

覆盖：
  - brand_publish_routes.py （14 个端点，测试5个）
  - channel_mapping_routes.py（14 个端点，测试5个）

测试分类：
  - 正常查询/创建
  - 业务校验失败（无效参数、缺少 header）
  - DB 错误 / 404

使用 FastAPI TestClient + dependency_overrides[get_db]，不连真实数据库。
相对导入通过 sys.modules 存根解决。
"""

from __future__ import annotations

import os
import sys
import types
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ─── sys.path 设置 ─────────────────────────────────────────────────────────────

_SRC = os.path.join(os.path.dirname(__file__), "..")
_ROOT = os.path.join(_SRC, "..", "..", "..", "..")
for p in (_SRC, _ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

# ─── sys.modules 存根：阻断相对导入链 ─────────────────────────────────────────


def _stub(name: str, **attrs):
    """向 sys.modules 注入最小存根模块，避免因相对导入链失败。"""
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules.setdefault(name, m)
    return m


# shared.ontology.src.database 存根
_db_stub = _stub("shared.ontology.src.database")

# BrandPublishService 存根（路由内用 from ..services.brand_publish_service import BrandPublishService）
_bps_class = MagicMock()
_bps_stub = _stub("services.brand_publish_service", BrandPublishService=_bps_class)

# ChannelMappingService 存根
_cms_class = MagicMock()
_cms_stub = _stub("services.channel_mapping_service", ChannelMappingService=_cms_class)

# structlog 存根（避免 structlog 配置问题）
if "structlog" not in sys.modules:
    _sl = _stub("structlog")
    _sl.get_logger = MagicMock(return_value=MagicMock())

# ─── 懒加载路由，确保存根先于导入 ──────────────────────────────────────────────

from shared.ontology.src.database import get_db  # noqa: E402 — 用存根模块

# 为 get_db 提供默认实现（存根模块原来没有）
if not hasattr(get_db, "__call__"):

    async def get_db():  # type: ignore[misc]
        yield None


from api.brand_publish_routes import router as bp_router  # noqa: E402
from api.channel_mapping_routes import router as cm_router  # noqa: E402

# ─── 构建测试 App ──────────────────────────────────────────────────────────────

app = FastAPI()
app.include_router(bp_router)
app.include_router(cm_router)

# ─── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
DISH_ID = str(uuid.uuid4())
PLAN_ID = str(uuid.uuid4())
RULE_ID = str(uuid.uuid4())

HEADERS = {"X-Tenant-ID": TENANT_ID}


# ─── Mock DB 工厂 ──────────────────────────────────────────────────────────────


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.close = AsyncMock()
    _res = MagicMock()
    _res.fetchone.return_value = None
    _res.fetchall.return_value = []
    _res.scalar.return_value = 0
    _res.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=_res)
    return db


def _db_with_rows(*rows, scalar: int = 0) -> AsyncMock:
    """返回能产出指定行的 AsyncSession mock。"""
    db = _make_db()
    res = MagicMock()
    res.fetchall.return_value = list(rows)
    res.fetchone.return_value = rows[0] if rows else None
    res.scalar.return_value = scalar
    db.execute = AsyncMock(return_value=res)
    return db


# ─── autouse fixture：每个测试重置 dependency_overrides ──────────────────────


@pytest.fixture(autouse=True)
def reset_overrides():
    app.dependency_overrides[get_db] = lambda: _make_db()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


# ══════════════════════════════════════════════════════════════════════════════
# 一、brand_publish_routes.py 的 5 个测试
# ══════════════════════════════════════════════════════════════════════════════


class TestBrandPublishRoutes:
    # ── BP-1: GET /api/v1/menu/brand-dishes 正常查询 ─────────────────────────

    def test_list_brand_dishes_returns_200(self, client):
        """GET /brand-dishes 带合法 tenant_id 返回 200，分页结构正确。"""
        # 第一次 execute：set_config；第二次：COUNT；第三次：SELECT rows
        db = _make_db()
        set_cfg_res = MagicMock()
        set_cfg_res.fetchall.return_value = []
        count_res = MagicMock()
        count_res.scalar.return_value = 3
        row = (
            uuid.UUID(DISH_ID),
            "红烧肉",
            "D001",
            4800,
            "经典湘菜",
            "http://img/1.jpg",
            uuid.UUID(STORE_ID),
            True,
            uuid.UUID(TENANT_ID),
            None,
        )
        rows_res = MagicMock()
        rows_res.fetchall.return_value = [row]

        db.execute = AsyncMock(side_effect=[set_cfg_res, count_res, rows_res])
        app.dependency_overrides[get_db] = lambda: db

        resp = client.get(
            "/api/v1/menu/brand-dishes",
            params={"page": 1, "size": 20},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["page"] == 1
        assert body["data"]["size"] == 20

    # ── BP-2: GET /api/v1/menu/brand-dishes 缺少 X-Tenant-ID header ──────────

    def test_list_brand_dishes_missing_tenant_header_returns_422(self, client):
        """GET /brand-dishes 缺少必填 X-Tenant-ID header 应返回 422。"""
        resp = client.get("/api/v1/menu/brand-dishes", params={"page": 1, "size": 20})
        assert resp.status_code == 422

    # ── BP-3: POST /api/v1/menu/publish-plans 正常创建 ────────────────────────

    def test_create_publish_plan_returns_201(self, client):
        """POST /publish-plans 合法请求返回 201，data 来自 service mock。"""
        plan_data = {
            "plan_id": PLAN_ID,
            "plan_name": "春节发布方案",
            "status": "draft",
        }
        mock_svc_instance = AsyncMock()
        mock_svc_instance.create_publish_plan = AsyncMock(return_value=plan_data)
        _bps_class.return_value = mock_svc_instance

        resp = client.post(
            "/api/v1/menu/publish-plans",
            json={
                "plan_name": "春节发布方案",
                "target_type": "all_stores",
            },
            headers=HEADERS,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["plan_name"] == "春节发布方案"

    # ── BP-4: POST /api/v1/menu/publish-plans 业务校验失败（service 抛 ValueError）

    def test_create_publish_plan_service_error_returns_400(self, client):
        """POST /publish-plans 当 service 抛 ValueError 时应返回 400。"""
        mock_svc_instance = AsyncMock()
        mock_svc_instance.create_publish_plan = AsyncMock(side_effect=ValueError("brand_id 不存在"))
        _bps_class.return_value = mock_svc_instance

        resp = client.post(
            "/api/v1/menu/publish-plans",
            json={
                "plan_name": "非法方案",
                "target_type": "region",
                "brand_id": "bad-uuid",
            },
            headers=HEADERS,
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["detail"]["ok"] is False

    # ── BP-5: GET /api/v1/menu/publish-plans/{plan_id} 方案不存在返回 404 ────

    def test_get_publish_plan_not_found_returns_404(self, client):
        """GET /publish-plans/{plan_id} 方案不存在时 service 抛 ValueError → 404。"""
        fake_plan_id = str(uuid.uuid4())
        mock_svc_instance = AsyncMock()
        mock_svc_instance.get_publish_plan = AsyncMock(side_effect=ValueError(f"发布方案 {fake_plan_id} 不存在"))
        _bps_class.return_value = mock_svc_instance

        resp = client.get(
            f"/api/v1/menu/publish-plans/{fake_plan_id}",
            headers=HEADERS,
        )
        assert resp.status_code == 404
        body = resp.json()
        assert body["detail"]["ok"] is False


# ══════════════════════════════════════════════════════════════════════════════
# 二、channel_mapping_routes.py 的 5 个测试
# ══════════════════════════════════════════════════════════════════════════════


class TestChannelMappingRoutes:
    # ── CM-1: GET /api/v1/menu/channels 正常查询渠道列表 ─────────────────────

    def test_list_channels_returns_200(self, client):
        """GET /channels 合法请求返回 200，包含渠道列表。"""
        # DB 返回各渠道菜品数
        count_res = MagicMock()
        count_res.fetchall.return_value = [
            ("dine_in", 12),
            ("meituan", 8),
        ]
        # 第一次 execute: set_config；第二次: count query
        set_cfg_res = MagicMock()
        set_cfg_res.fetchall.return_value = []
        db = _make_db()
        db.execute = AsyncMock(side_effect=[set_cfg_res, count_res])
        app.dependency_overrides[get_db] = lambda: db

        resp = client.get(
            "/api/v1/menu/channels",
            params={"store_id": STORE_ID},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        channels = body["data"]["channels"]
        assert isinstance(channels, list)
        assert len(channels) == 5  # _CHANNELS 共5个渠道

        # dine_in 的 dish_count 应映射到返回值
        dine_in = next(c for c in channels if c["channel"] == "dine_in")
        assert dine_in["dish_count"] == 12

    # ── CM-2: GET /api/v1/menu/channels 缺少 X-Tenant-ID → 400 ──────────────

    def test_list_channels_missing_tenant_id_returns_400(self, client):
        """GET /channels 缺少 X-Tenant-ID header 应返回 400。"""
        resp = client.get(
            "/api/v1/menu/channels",
            params={"store_id": STORE_ID},
            # 故意不传 HEADERS
        )
        assert resp.status_code == 400
        assert "X-Tenant-ID" in resp.json()["detail"]

    # ── CM-3: GET /api/v1/menu/channels/{channel}/dishes 正常查询渠道菜品 ────

    def test_list_channel_dishes_returns_200(self, client):
        """GET /channels/dine_in/dishes 合法渠道和门店返回 200。"""
        dish_row = (
            uuid.UUID(DISH_ID),  # cmi.id
            uuid.UUID(DISH_ID),  # cmi.dish_id
            "剁椒鱼头",  # d.dish_name
            5800,  # base_price_fen
            None,  # channel_price_fen
            5800,  # effective_price_fen
            True,  # is_available
            0,  # sort_order
            "http://img/dish.jpg",  # image_url
            uuid.UUID(STORE_ID),  # category_id
        )
        set_cfg_res = MagicMock()
        set_cfg_res.fetchall.return_value = []
        rows_res = MagicMock()
        rows_res.fetchall.return_value = [dish_row]
        db = _make_db()
        db.execute = AsyncMock(side_effect=[set_cfg_res, rows_res])
        app.dependency_overrides[get_db] = lambda: db

        resp = client.get(
            "/api/v1/menu/channels/dine_in/dishes",
            params={"store_id": STORE_ID},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["channel"] == "dine_in"
        assert body["data"]["total"] == 1
        assert body["data"]["items"][0]["dish_name"] == "剁椒鱼头"

    # ── CM-4: GET /api/v1/menu/channels/{channel}/dishes 非法渠道 → 400 ──────

    def test_list_channel_dishes_invalid_channel_returns_400(self, client):
        """GET /channels/{invalid}/dishes 使用不支持的渠道名应返回 400。"""
        resp = client.get(
            "/api/v1/menu/channels/wechat_pay/dishes",
            params={"store_id": STORE_ID},
            headers=HEADERS,
        )
        assert resp.status_code == 400
        body = resp.json()
        assert "不支持的渠道" in body["detail"]

    # ── CM-5: POST /api/v1/menu/channels/{channel}/publish 无可发布菜品 → 422

    def test_publish_to_channel_no_dishes_returns_422(self, client):
        """POST /channels/meituan/publish 渠道无可用菜品时应返回 422。"""
        set_cfg_res = MagicMock()
        set_cfg_res.fetchall.return_value = []
        # channel_menu_items 查询返回空列表
        empty_res = MagicMock()
        empty_res.fetchall.return_value = []
        db = _make_db()
        db.execute = AsyncMock(side_effect=[set_cfg_res, empty_res])
        app.dependency_overrides[get_db] = lambda: db

        resp = client.post(
            "/api/v1/menu/channels/meituan/publish",
            params={"store_id": STORE_ID},
            headers=HEADERS,
        )
        assert resp.status_code == 422
        assert "没有可发布的菜品" in resp.json()["detail"]
