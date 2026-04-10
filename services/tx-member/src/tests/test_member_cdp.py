"""积分兑换商城路由 + 积分管理路由 测试

覆盖文件：
  - api/points_mall_routes.py  (10 端点，积分兑换全流程)
  - api/points_routes.py       (9 端点，积分获取/消耗/规则/余额/月结算)

场景（共 10 个）：
─── points_mall_routes.py ────────────────────────────────────────────────────
1.  GET  /api/v1/member/points-mall/products          — 正常查询商品列表，返回分页数据
2.  GET  /api/v1/member/points-mall/products/{id}     — 商品详情正常返回
3.  GET  /api/v1/member/points-mall/products/{id}     — 商品不存在 → 404
4.  POST /api/v1/member/points-mall/redeem            — 积分兑换成功（原子事务）
5.  POST /api/v1/member/points-mall/redeem            — 积分不足 → 422
─── points_routes.py ─────────────────────────────────────────────────────────
6.  POST /api/v1/member/points/earn                   — 正常积分获取，响应含 earned/new_balance
7.  POST /api/v1/member/points/spend                  — 正常积分消耗（抵现）
8.  PUT  /api/v1/member/points/types/{id}/multiplier  — 积分倍数设置，响应含 multiplier
9.  GET  /api/v1/member/points/cards/{id}/balance     — 积分余额查询，响应结构完整
10. GET  /api/v1/member/points/settlement/{month}     — 跨店积分月结算，响应含 month

注意：
- points_mall_routes.py 使用相对导入 `from ..services.points_mall_v2 import func`，
  因此服务函数 at import time 绑定到路由模块本地名称。
  需通过 unittest.mock.patch("src.api.points_mall_routes.<func>") 来替换。
- services/tx-member 目录加入 sys.path，使 `src` 作为顶层包被导入。
- shared.ontology.src.database 和 structlog 在 import 前注入为存根。
"""
from __future__ import annotations

import os
import sys
import types
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

# ─── sys.path：services/tx-member 为包根，src 为子包 ──────────────────────

_SERVICE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _SERVICE_DIR not in sys.path:
    sys.path.insert(0, _SERVICE_DIR)

_SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

# ─── 注入 shared.ontology.src.database 存根（points_mall_routes 绝对导入） ──

for _mod_name in (
    "shared",
    "shared.ontology",
    "shared.ontology.src",
    "shared.ontology.src.database",
):
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = types.ModuleType(_mod_name)

_db_mod = sys.modules["shared.ontology.src.database"]


async def _fake_get_db():  # type: ignore[override]
    from sqlalchemy.ext.asyncio import AsyncSession
    yield AsyncMock(spec=AsyncSession)


_db_mod.get_db = _fake_get_db  # type: ignore[attr-defined]

# ─── 注入 structlog 存根 ────────────────────────────────────────────────────

if "structlog" not in sys.modules:
    _structlog_stub = types.ModuleType("structlog")
    _structlog_stub.get_logger = lambda *a, **kw: MagicMock()  # type: ignore[attr-defined]
    sys.modules["structlog"] = _structlog_stub

# ─── 注入 src.services.points_mall_v2 存根（满足相对导入）───────────────────
# 路由通过 `from ..services.points_mall_v2 import ...` 在模块加载时绑定函数。
# 存根必须在 import src.api.points_mall_routes 前存在于 sys.modules，
# 这样路由绑定的本地名称指向存根中的 AsyncMock。
# 测试时通过 patch("src.api.points_mall_routes.<func>") 替换已绑定的名称。

for _pkg in ("src.services",):
    if _pkg not in sys.modules:
        _m = types.ModuleType(_pkg)
        sys.modules[_pkg] = _m

_svc_stub = types.ModuleType("src.services.points_mall_v2")
for _fn_name in (
    "list_products",
    "get_product",
    "create_product",
    "update_product",
    "redeem",
    "get_customer_orders",
    "get_order_detail",
    "fulfill_order",
    "cancel_order",
    "get_order_stats",
):
    setattr(_svc_stub, _fn_name, AsyncMock())

sys.modules["src.services.points_mall_v2"] = _svc_stub

# ─── 加载路由（包名方式，解析相对导入）──────────────────────────────────────

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import src.api.points_mall_routes as _mall_mod  # noqa: E402
import src.api.points_routes as _pts_mod  # noqa: E402

_MALL_PREFIX = "src.api.points_mall_routes"

mall_app = FastAPI()
mall_app.include_router(_mall_mod.router)

pts_app = FastAPI()
pts_app.include_router(_pts_mod.router)

# ─── 公共常量 ───────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
PRODUCT_ID = str(uuid.uuid4())
CUSTOMER_ID = str(uuid.uuid4())
ORDER_ID = str(uuid.uuid4())
CARD_ID = str(uuid.uuid4())
CARD_TYPE_ID = str(uuid.uuid4())

_MALL_HEADERS = {"X-Tenant-ID": TENANT_ID}
_PTS_HEADERS = {"X-Tenant-ID": TENANT_ID}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1：GET /api/v1/member/points-mall/products — 正常分页查询
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_mall_list_products_success():
    """list_products 返回含 items/total 分页结构 → 200，data.items 长度=2"""
    fake_page = {
        "items": [
            {"id": PRODUCT_ID, "name": "招牌菜兑换券", "points_required": 500, "stock": 50},
            {"id": str(uuid.uuid4()), "name": "咖啡兑换", "points_required": 200, "stock": -1},
        ],
        "total": 2,
        "page": 1,
        "size": 20,
    }
    with patch(f"{_MALL_PREFIX}.list_products", new=AsyncMock(return_value=fake_page)):
        client = TestClient(mall_app)
        resp = client.get(
            "/api/v1/member/points-mall/products?page=1&size=20",
            headers=_MALL_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["error"] is None
    assert len(body["data"]["items"]) == 2
    assert body["data"]["total"] == 2


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2：GET /api/v1/member/points-mall/products/{id} — 商品详情正常返回
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_mall_get_product_success():
    """get_product 返回商品详情 → 200，data.id 与路径一致，product_type=dish"""
    fake_product = {
        "id": PRODUCT_ID,
        "name": "招牌菜兑换券",
        "product_type": "dish",
        "points_required": 500,
        "stock": 50,
        "is_active": True,
        "customer_redeemed_count": 0,
    }
    with patch(f"{_MALL_PREFIX}.get_product", new=AsyncMock(return_value=fake_product)):
        client = TestClient(mall_app)
        resp = client.get(
            f"/api/v1/member/points-mall/products/{PRODUCT_ID}",
            headers=_MALL_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["id"] == PRODUCT_ID
    assert body["data"]["points_required"] == 500
    assert body["data"]["product_type"] == "dish"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3：GET /api/v1/member/points-mall/products/{id} — 商品不存在 → 404
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_mall_get_product_not_found():
    """get_product 抛出 ValueError('product_not_found') → HTTP 404（路由 status_map 正确）"""
    with patch(
        f"{_MALL_PREFIX}.get_product",
        new=AsyncMock(side_effect=ValueError("product_not_found")),
    ):
        client = TestClient(mall_app)
        resp = client.get(
            f"/api/v1/member/points-mall/products/{uuid.uuid4()}",
            headers=_MALL_HEADERS,
        )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "product_not_found"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4：POST /api/v1/member/points-mall/redeem — 积分兑换成功
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_mall_redeem_success():
    """redeem 完成原子事务 → 200，data 含 order_id / points_spent / status=pending"""
    fake_order = {
        "order_id": ORDER_ID,
        "product_id": PRODUCT_ID,
        "customer_id": CUSTOMER_ID,
        "points_spent": 500,
        "quantity": 1,
        "status": "pending",
    }
    with patch(f"{_MALL_PREFIX}.redeem", new=AsyncMock(return_value=fake_order)):
        client = TestClient(mall_app)
        resp = client.post(
            "/api/v1/member/points-mall/redeem",
            headers=_MALL_HEADERS,
            json={
                "product_id": PRODUCT_ID,
                "customer_id": CUSTOMER_ID,
                "quantity": 1,
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["order_id"] == ORDER_ID
    assert body["data"]["points_spent"] == 500
    assert body["data"]["status"] == "pending"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5：POST /api/v1/member/points-mall/redeem — 积分不足 → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_mall_redeem_insufficient_points():
    """redeem 抛出 ValueError('insufficient_points') → HTTP 422（业务逻辑校验）"""
    with patch(
        f"{_MALL_PREFIX}.redeem",
        new=AsyncMock(side_effect=ValueError("insufficient_points")),
    ):
        client = TestClient(mall_app)
        resp = client.post(
            "/api/v1/member/points-mall/redeem",
            headers=_MALL_HEADERS,
            json={
                "product_id": PRODUCT_ID,
                "customer_id": CUSTOMER_ID,
                "quantity": 99,  # 超出持有积分
            },
        )

    assert resp.status_code == 422
    assert "insufficient_points" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6：POST /api/v1/member/points/earn — 正常积分获取
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_pts_earn_points_success():
    """POST /earn 消费来源积分请求 → 200，响应含 card_id / earned / new_balance"""
    client = TestClient(pts_app)
    resp = client.post(
        "/api/v1/member/points/earn",
        headers=_PTS_HEADERS,
        json={
            "card_id": CARD_ID,
            "source": "consume",
            "amount": 100,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["card_id"] == CARD_ID
    assert body["data"]["source"] == "consume"
    assert body["data"]["earned"] == 100
    assert "new_balance" in body["data"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7：POST /api/v1/member/points/spend — 积分抵现消耗
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_pts_spend_points_cash_offset():
    """POST /spend purpose=cash_offset → 200，响应含 spent=50 / new_balance"""
    client = TestClient(pts_app)
    resp = client.post(
        "/api/v1/member/points/spend",
        headers=_PTS_HEADERS,
        json={
            "card_id": CARD_ID,
            "amount": 50,
            "purpose": "cash_offset",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["card_id"] == CARD_ID
    assert body["data"]["purpose"] == "cash_offset"
    assert body["data"]["spent"] == 50
    assert "new_balance" in body["data"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 8：PUT /api/v1/member/points/types/{id}/multiplier — 积分倍数设置
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_pts_set_multiplier_member_day():
    """PUT /multiplier 会员日 3× → 200，响应含 multiplier=3.0 / card_type_id / conditions"""
    client = TestClient(pts_app)
    resp = client.put(
        f"/api/v1/member/points/types/{CARD_TYPE_ID}/multiplier",
        headers=_PTS_HEADERS,
        json={
            "multiplier": 3.0,
            "conditions": {"event": "member_day", "weekday": 6},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["card_type_id"] == CARD_TYPE_ID
    assert body["data"]["multiplier"] == 3.0
    assert body["data"]["conditions"]["event"] == "member_day"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 9：GET /api/v1/member/points/cards/{id}/balance — 积分余额查询
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_pts_get_balance_structure():
    """GET /balance → 200，响应含 card_id / points(int) / growth_value(int)"""
    client = TestClient(pts_app)
    resp = client.get(
        f"/api/v1/member/points/cards/{CARD_ID}/balance",
        headers=_PTS_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["card_id"] == CARD_ID
    assert "points" in data
    assert "growth_value" in data
    assert isinstance(data["points"], int)
    assert isinstance(data["growth_value"], int)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 10：GET /api/v1/member/points/settlement/{month} — 跨店积分月结算
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_pts_cross_store_settlement():
    """GET /settlement/2026-03 → 200，响应含 month / store_settlements / 合计字段"""
    client = TestClient(pts_app)
    resp = client.get(
        "/api/v1/member/points/settlement/2026-03",
        headers=_PTS_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["month"] == "2026-03"
    assert "store_settlements" in data
    assert "total_points_earned" in data
    assert "total_points_spent" in data
