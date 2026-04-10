"""外卖运营 & 全渠道接单路由测试

覆盖文件：
  - api/delivery_ops_routes.py   — 15 个端点（外卖配置/忙碌模式/差评/健康度/对账）
  - api/omni_channel_routes.py   — 9 个端点（webhook/接单面板/统一订单列表/渠道统计）

测试清单（共 10 个）：
  delivery_ops_routes（5 个）
    T1. GET  /api/v1/delivery/config/{store_id}          — 正常查询所有平台配置
    T2. PUT  /api/v1/delivery/config/{store_id}/{platform} — 正常更新配置
    T3. POST /api/v1/delivery/busy-mode/{store_id}/{platform} — 正常开启忙碌模式
    T4. DELETE /api/v1/delivery/busy-mode/{store_id}/{platform} — 配置不存在返回 404
    T5. GET  /api/v1/delivery/config/{store_id}/{platform} — DeliveryOpsError → 400

  omni_channel_routes（5 个）
    T6.  GET  /api/v1/omni/orders/pending              — 正常查询待接单列表
    T7.  POST /api/v1/omni/orders/{id}/accept          — 正常接单（ok=True）
    T8.  POST /api/v1/omni/orders/{id}/reject          — 正常拒单（ok=True）
    T9.  GET  /api/v1/omni/orders/pending              — 缺少 X-Tenant-ID 返回 400
    T10. POST /api/v1/omni/orders/{id}/accept          — OmniChannelError → 404
"""
from __future__ import annotations

import os
import sys
import types
import uuid

# ─── 路径准备 ──────────────────────────────────────────────────────────────────
_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
_ROOT_DIR = os.path.abspath(os.path.join(_TESTS_DIR, "..", "..", "..", ".."))

for _p in [_SRC_DIR, _ROOT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ─── 建立 src 包层级（使相对导入正常工作） ────────────────────────────────────

def _ensure_pkg(pkg_name: str, pkg_path: str) -> None:
    if pkg_name not in sys.modules:
        mod = types.ModuleType(pkg_name)
        mod.__path__ = [pkg_path]
        mod.__package__ = pkg_name
        sys.modules[pkg_name] = mod


_ensure_pkg("src",           _SRC_DIR)
_ensure_pkg("src.api",       os.path.join(_SRC_DIR, "api"))
_ensure_pkg("src.models",    os.path.join(_SRC_DIR, "models"))
_ensure_pkg("src.services",  os.path.join(_SRC_DIR, "services"))
_ensure_pkg("src.repositories", os.path.join(_SRC_DIR, "repositories"))

# ─── 注入 shared.events 存根（delivery_ops_service 导入它） ───────────────────

def _ensure_stub(name: str, attrs: dict | None = None) -> types.ModuleType:
    """如果模块还未注册，创建一个轻量存根。"""
    if name not in sys.modules:
        mod = types.ModuleType(name)
        for k, v in (attrs or {}).items():
            setattr(mod, k, v)
        sys.modules[name] = mod
    return sys.modules[name]

_ensure_stub("shared.events", {"UniversalPublisher": object})
_ensure_stub("shared.adapters")
_ensure_stub("shared.adapters.base")
_ensure_stub("shared.adapters.base.src")
_ensure_stub("shared.adapters.base.src.adapter", {"APIError": Exception})

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.ontology.src.database import get_db  # noqa: E402

# ─── 导入被测路由 ───────────────────────────────────────────────────────────────

# delivery_ops_routes
from src.api.delivery_ops_routes import router as delivery_ops_router  # type: ignore[import]

# omni_channel_routes 依赖 omni_channel_service — 先注入存根再导入路由
# (避免 omni_channel_service 在导入时连接真实 DB 或触发副作用)
from src.services.omni_channel_service import (  # type: ignore[import]
    OmniChannelError,
    OmniChannelService,
    UnsupportedPlatformError,
)
from src.api.omni_channel_routes import router as omni_channel_router  # type: ignore[import]

# ─── 公共常量 ──────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID  = str(uuid.uuid4())
_HEADERS  = {"X-Tenant-ID": TENANT_ID}


# ─── 工具函数 ──────────────────────────────────────────────────────────────────

def _override_db(db_mock):
    """生成 FastAPI dependency override 函数。"""
    def _dep():
        return db_mock
    return _dep


def _make_app_ops(db_mock):
    app = FastAPI()
    app.include_router(delivery_ops_router)
    app.dependency_overrides[get_db] = _override_db(db_mock)
    return app


def _make_app_omni(db_mock):
    app = FastAPI()
    app.include_router(omni_channel_router, prefix="/api/v1")
    app.dependency_overrides[get_db] = _override_db(db_mock)
    return app


def _make_db():
    db = AsyncMock()
    db.commit  = AsyncMock()
    db.execute = AsyncMock()
    return db


def _make_store_config(platform: str = "meituan") -> MagicMock:
    cfg = MagicMock()
    cfg.id                      = uuid.uuid4()
    cfg.store_id                = uuid.UUID(STORE_ID)
    cfg.platform                = platform
    cfg.auto_accept             = True
    cfg.auto_accept_max_per_hour = 30
    cfg.busy_mode               = False
    cfg.busy_mode_prep_time_min = 40
    cfg.normal_prep_time_min    = 25
    cfg.current_prep_time_min   = 25
    cfg.busy_mode_started_at    = None
    cfg.busy_mode_auto_off_at   = None
    cfg.max_delivery_distance_km = 5.0
    cfg.is_active               = True
    cfg.updated_at              = datetime.now(timezone.utc)
    cfg.created_at              = datetime.now(timezone.utc)
    # model_dump 返回简单 dict，满足路由的 .model_dump(mode="json") 调用
    cfg.model_dump.return_value = {
        "id": str(cfg.id),
        "store_id": str(cfg.store_id),
        "platform": platform,
        "auto_accept": True,
        "busy_mode": False,
        "current_prep_time_min": 25,
    }
    return cfg


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# T1 — GET /api/v1/delivery/config/{store_id} 正常查询所有平台配置
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_get_all_configs_ok():
    """正常查询门店三个平台配置，返回 ok=True 且 data 列表长度 == 3。"""
    db = _make_db()
    configs = [_make_store_config(p) for p in ("meituan", "eleme", "douyin")]

    with patch(
        "src.api.delivery_ops_routes.DeliveryOpsService.get_all_store_configs",
        new=AsyncMock(return_value=configs),
    ):
        app = _make_app_ops(db)
        client = TestClient(app)
        resp = client.get(
            f"/api/v1/delivery/config/{STORE_ID}",
            headers=_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert isinstance(body["data"], list)
    assert len(body["data"]) == 3


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# T2 — PUT /api/v1/delivery/config/{store_id}/{platform} 正常更新配置
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_update_config_ok():
    """正常更新美团配置（出餐时间改为 30 分钟），ok=True。"""
    db = _make_db()
    cfg = _make_store_config("meituan")
    cfg.model_dump.return_value["normal_prep_time_min"] = 30

    with patch(
        "src.api.delivery_ops_routes.DeliveryOpsService.update_store_config",
        new=AsyncMock(return_value=cfg),
    ):
        app = _make_app_ops(db)
        client = TestClient(app)
        resp = client.put(
            f"/api/v1/delivery/config/{STORE_ID}/meituan",
            json={"normal_prep_time_min": 30},
            headers=_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["normal_prep_time_min"] == 30


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# T3 — POST /api/v1/delivery/busy-mode/{store_id}/{platform} 正常开启忙碌模式
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_enable_busy_mode_ok():
    """正常开启美团忙碌模式（duration_minutes=120），ok=True 且 busy_mode==True。"""
    db = _make_db()
    cfg = _make_store_config("meituan")
    cfg.busy_mode = True
    cfg.model_dump.return_value["busy_mode"] = True

    with patch(
        "src.api.delivery_ops_routes.DeliveryOpsService.enable_busy_mode",
        new=AsyncMock(return_value=cfg),
    ):
        app = _make_app_ops(db)
        client = TestClient(app)
        resp = client.post(
            f"/api/v1/delivery/busy-mode/{STORE_ID}/meituan",
            json={"duration_minutes": 120},
            headers=_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["busy_mode"] is True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# T4 — DELETE /api/v1/delivery/busy-mode/{store_id}/{platform} 配置不存在 → 404
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_disable_busy_mode_config_not_found_returns_404():
    """ConfigNotFoundError 时路由应返回 404。"""
    from src.services.delivery_ops_service import ConfigNotFoundError  # type: ignore[import]

    db = _make_db()

    with patch(
        "src.api.delivery_ops_routes.DeliveryOpsService.disable_busy_mode",
        new=AsyncMock(side_effect=ConfigNotFoundError("配置不存在")),
    ):
        app = _make_app_ops(db)
        client = TestClient(app)
        resp = client.delete(
            f"/api/v1/delivery/busy-mode/{STORE_ID}/eleme",
            headers=_HEADERS,
        )

    assert resp.status_code == 404
    assert "配置不存在" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# T5 — GET /api/v1/delivery/config/{store_id}/{platform} DeliveryOpsError → 400
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_get_config_ops_error_returns_400():
    """DeliveryOpsService 抛出 DeliveryOpsError 时路由应返回 400。"""
    from src.services.delivery_ops_service import DeliveryOpsError  # type: ignore[import]

    db = _make_db()

    with patch(
        "src.api.delivery_ops_routes.DeliveryOpsService.get_store_config",
        new=AsyncMock(side_effect=DeliveryOpsError("数据库查询失败")),
    ):
        app = _make_app_ops(db)
        client = TestClient(app)
        resp = client.get(
            f"/api/v1/delivery/config/{STORE_ID}/douyin",
            headers=_HEADERS,
        )

    assert resp.status_code == 400
    assert "数据库查询失败" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# T6 — GET /api/v1/omni/orders/pending 正常查询待接单列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _make_unified_order(platform: str = "meituan") -> MagicMock:
    o = MagicMock()
    o.internal_order_id = str(uuid.uuid4())
    o.platform          = platform
    o.platform_order_id = f"{platform[:2].upper()}{uuid.uuid4().hex[:8]}"
    o.status            = "pending"
    o.total_fen         = 4800
    o.notes             = None
    o.customer_phone    = "138****0000"
    o.delivery_address  = "某某路1号"
    o.created_at        = datetime.now(timezone.utc)
    o.items             = []
    return o


def test_get_pending_orders_ok():
    """正常查询所有平台待接单列表，返回 ok=True 且 data 包含 2 条。"""
    db = _make_db()
    orders = [_make_unified_order("meituan"), _make_unified_order("eleme")]

    with patch(
        "src.api.omni_channel_routes.OmniChannelService.get_pending_orders",
        new=AsyncMock(return_value=orders),
    ):
        app = _make_app_omni(db)
        client = TestClient(app)
        resp = client.get(
            "/api/v1/omni/orders/pending",
            params={"store_id": STORE_ID},
            headers=_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["data"]) == 2
    assert body["data"][0]["platform"] == "meituan"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# T7 — POST /api/v1/omni/orders/{id}/accept 正常接单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_accept_order_ok():
    """正常接单（estimated_minutes=20），ok=True 且 data 包含 accepted=True。"""
    db = _make_db()
    order_id = str(uuid.uuid4())
    result_data = {"order_id": order_id, "accepted": True, "estimated_minutes": 20}

    with patch(
        "src.api.omni_channel_routes.OmniChannelService.accept_order",
        new=AsyncMock(return_value=result_data),
    ):
        app = _make_app_omni(db)
        client = TestClient(app)
        resp = client.post(
            f"/api/v1/omni/orders/{order_id}/accept",
            json={"estimated_minutes": 20},
            headers=_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["accepted"] is True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# T8 — POST /api/v1/omni/orders/{id}/reject 正常拒单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_reject_order_ok():
    """正常拒单（reason_code=2），ok=True。"""
    db = _make_db()
    order_id = str(uuid.uuid4())
    result_data = {"order_id": order_id, "rejected": True, "reason_code": 2}

    with patch(
        "src.api.omni_channel_routes.OmniChannelService.reject_order",
        new=AsyncMock(return_value=result_data),
    ):
        app = _make_app_omni(db)
        client = TestClient(app)
        resp = client.post(
            f"/api/v1/omni/orders/{order_id}/reject",
            json={"reason_code": 2},
            headers=_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["rejected"] is True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# T9 — GET /api/v1/omni/orders/pending 缺少 X-Tenant-ID → 400
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_get_pending_orders_missing_tenant_returns_400():
    """不传 X-Tenant-ID，_get_tenant_id 应触发 400。"""
    db = _make_db()
    app = _make_app_omni(db)
    client = TestClient(app)
    resp = client.get(
        "/api/v1/omni/orders/pending",
        params={"store_id": STORE_ID},
        # 故意不传 X-Tenant-ID
    )

    assert resp.status_code == 400
    assert "X-Tenant-ID" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# T10 — POST /api/v1/omni/orders/{id}/accept OmniChannelError → 404
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_accept_order_omni_error_returns_404():
    """OmniChannelService.accept_order 抛出 OmniChannelError 时应返回 404。"""
    db = _make_db()
    order_id = str(uuid.uuid4())

    with patch(
        "src.api.omni_channel_routes.OmniChannelService.accept_order",
        new=AsyncMock(side_effect=OmniChannelError(f"订单 {order_id} 不存在")),
    ):
        app = _make_app_omni(db)
        client = TestClient(app)
        resp = client.post(
            f"/api/v1/omni/orders/{order_id}/accept",
            json={"estimated_minutes": 20},
            headers=_HEADERS,
        )

    assert resp.status_code == 404
    assert order_id in resp.json()["detail"]
