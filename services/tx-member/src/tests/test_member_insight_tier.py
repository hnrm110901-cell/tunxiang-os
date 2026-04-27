"""会员洞察 + 等级 + 奖励兑换 + RFM + 平台绑定 + 发票测试

覆盖场景（共 18 个）：

member_insight_routes.py（3个）：
1.  POST /api/v1/members/{id}/insights/generate — 正常生成洞察
2.  GET  /api/v1/members/{id}/insights/latest  — 缓存命中
3.  GET  /api/v1/members/{id}/insights/latest  — 缓存未命中 → 404

rewards_routes.py（3个）：
4.  GET  /api/v1/member/rewards/               — 正常商品列表（空）
5.  POST /api/v1/member/rewards/redeem         — 商品不存在 → 404
6.  POST /api/v1/member/rewards/redeem         — 积分不足 → ok=False INSUFFICIENT_POINTS

rfm_routes.py（3个）：
7.  POST /api/v1/member/rfm/trigger-update     — 正常触发更新
8.  GET  /api/v1/member/rfm/distribution       — 正常等级分布
9.  GET  /api/v1/member/rfm/changes            — 正常今日变化（空）

tier_routes.py（3个）：
10. GET  /api/v1/member/tiers                  — 正常等级列表
11. POST /api/v1/member/tiers                  — 缺少 name → 422
12. GET  /api/v1/member/tiers/{id}             — 等级不存在 → 404

platform_routes.py（3个）：
13. POST /api/v1/member/platform/meituan/order — 无效租户ID → 400
14. POST /api/v1/member/platform/douyin/order  — 正常绑定
15. GET  /api/v1/member/platform/stats         — 正常统计

invoice_routes.py（3个）：
16. GET  /api/v1/member/invoice-titles         — 正常发票抬头列表
17. POST /api/v1/member/invoice-titles         — 缺少 customer_id → 422
18. GET  /api/v1/member/invoices               — 正常历史发票（空）
"""

import os
import sys
import types
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

# ─── sys.path ─────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ─── 存根注入 ──────────────────────────────────────────────────────────────


def _inject_stubs():
    # shared.ontology.src.database
    db_mod = types.ModuleType("shared.ontology.src.database")

    async def _fake_get_db_with_tenant(tenant_id):  # noqa: ARG001
        yield AsyncMock()

    db_mod.get_db_with_tenant = _fake_get_db_with_tenant
    db_mod.get_db = MagicMock()
    sys.modules.setdefault("shared", types.ModuleType("shared"))
    sys.modules.setdefault("shared.ontology", types.ModuleType("shared.ontology"))
    sys.modules.setdefault("shared.ontology.src", types.ModuleType("shared.ontology.src"))
    sys.modules["shared.ontology.src.database"] = db_mod

    # structlog
    structlog_mod = types.ModuleType("structlog")
    structlog_mod.get_logger = MagicMock(return_value=MagicMock())
    sys.modules.setdefault("structlog", structlog_mod)

    # shared.ontology.src.entities（rfm_routes 用到 Customer ORM）
    entities_mod = types.ModuleType("shared.ontology.src.entities")
    _customer_cls = MagicMock()
    _customer_cls.tenant_id = MagicMock()
    _customer_cls.is_deleted = MagicMock()
    _customer_cls.is_merged = MagicMock()
    _customer_cls.rfm_level = MagicMock()
    _customer_cls.id = MagicMock()
    _customer_cls.rfm_updated_at = MagicMock()
    _customer_cls.r_score = MagicMock()
    _customer_cls.display_name = MagicMock()
    _customer_cls.primary_phone = MagicMock()
    entities_mod.Customer = _customer_cls
    sys.modules["shared.ontology.src.entities"] = entities_mod

    # workers.rfm_updater（rfm_routes 直接导入）
    rfm_updater_mod = types.ModuleType("workers.rfm_updater")
    _mock_rfm_updater = MagicMock()
    _mock_rfm_updater.update_tenant_rfm = AsyncMock(return_value=10)
    _mock_rfm_updater.update_all_tenants = AsyncMock(
        return_value={"total_tenants": 1, "total_updated": 10, "elapsed_seconds": 0.5}
    )
    rfm_updater_mod.RFMUpdater = MagicMock(return_value=_mock_rfm_updater)
    sys.modules.setdefault("workers", types.ModuleType("workers"))
    sys.modules["workers.rfm_updater"] = rfm_updater_mod

    # services.platform_binding_service（platform_routes 用裸路径导入）
    _mock_pbs = MagicMock()
    _mock_pbs.bind_meituan_order = AsyncMock(return_value={"customer_id": str(uuid.uuid4())})
    _mock_pbs.bind_douyin_order = AsyncMock(return_value={"customer_id": str(uuid.uuid4())})
    _mock_pbs.bind_platform_user = AsyncMock(return_value={"customer_id": str(uuid.uuid4())})
    _mock_pbs.get_platform_binding_stats = AsyncMock(
        return_value={"meituan": {"total_bound": 5}, "douyin": {"total_bound": 3}}
    )
    _mock_pbs.merge_platform_duplicates = AsyncMock(return_value={"merged_count": 2})
    pbs_mod = types.ModuleType("services.platform_binding_service")
    pbs_mod.PlatformBindingService = MagicMock(return_value=_mock_pbs)
    sys.modules.setdefault("services", types.ModuleType("services"))
    sys.modules["services.platform_binding_service"] = pbs_mod

    return _mock_rfm_updater, _mock_pbs


_MOCK_RFM_UPDATER, _MOCK_PBS = _inject_stubs()


# ─── 辅助 ─────────────────────────────────────────────────────────────────


def _uid() -> str:
    return str(uuid.uuid4())


TENANT_ID = _uid()
HEADERS = {"X-Tenant-ID": TENANT_ID}


# ─── 加载路由模块 ─────────────────────────────────────────────────────────
import importlib  # noqa: E402

# --- member_insight_routes（无 DB 依赖，使用内存缓存）---
insight_mod = importlib.import_module("api.member_insight_routes")
insight_app = FastAPI()
insight_app.include_router(insight_mod.router)
# 每次测试前清空缓存
insight_mod._insight_cache.clear()

# --- rewards_routes ---
rewards_mod = importlib.import_module("api.rewards_routes")
rewards_app = FastAPI()
rewards_app.include_router(rewards_mod.router)


def _rewards_override(db_mock):
    async def _dep():
        return db_mock

    rewards_app.dependency_overrides[rewards_mod.get_db] = _dep


# --- rfm_routes ---
rfm_mod = importlib.import_module("api.rfm_routes")
rfm_app = FastAPI()
rfm_app.include_router(rfm_mod.router)


def _rfm_override(db_mock):
    async def _dep():
        return db_mock

    rfm_app.dependency_overrides[rfm_mod.get_db] = _dep


# --- tier_routes ---
tier_mod = importlib.import_module("api.tier_routes")
tier_app = FastAPI()
tier_app.include_router(tier_mod.router)


def _tier_override(db_mock):
    async def _dep():
        return db_mock

    tier_app.dependency_overrides[tier_mod.get_db] = _dep


# --- platform_routes（使用 get_db_with_tenant context manager） ---
platform_mod = importlib.import_module("api.platform_routes")
platform_app = FastAPI()
platform_app.include_router(platform_mod.router)
# 注入 _binding_service 单例
platform_mod._binding_service = _MOCK_PBS


# --- invoice_routes ---
invoice_mod = importlib.import_module("api.invoice_routes")
invoice_app = FastAPI()
invoice_app.include_router(invoice_mod.router)


def _invoice_override(db_mock):
    async def _dep():
        return db_mock

    invoice_app.dependency_overrides[invoice_mod.get_db] = _dep


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ★ member_insight_routes — 3 个测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# 场景 1: POST generate — 正常生成
def test_insight_generate_ok():
    """生成洞察正常返回，包含 profile / alerts / suggestions 字段。"""
    insight_mod._insight_cache.clear()
    member_id = _uid()
    client = TestClient(insight_app)
    resp = client.post(
        f"/api/v1/members/{member_id}/insights/generate",
        json={"order_id": _uid(), "store_id": _uid()},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["member_id"] == member_id
    assert "profile" in body
    assert "alerts" in body
    assert "suggestions" in body
    # 生成后缓存应有该 member_id
    assert member_id in insight_mod._insight_cache


# 场景 2: GET latest — 缓存命中
def test_insight_latest_cache_hit():
    """缓存中存在洞察时，GET latest 直接返回，不重新生成。"""
    member_id = _uid()
    fake_insight = {
        "member_id": member_id,
        "generated_at": "2026-01-01T00:00:00+00:00",
        "profile": {
            "visit_count": 10,
            "last_visit": "2026-01-01",
            "avg_spend_fen": 30000,
            "favorite_dishes": [],
            "avoided_items": [],
            "preferences": [],
        },
        "alerts": [],
        "suggestions": [],
        "service_tips": "test tip",
    }
    insight_mod._insight_cache[member_id] = fake_insight

    client = TestClient(insight_app)
    resp = client.get(
        f"/api/v1/members/{member_id}/insights/latest",
        headers=HEADERS,
    )

    assert resp.status_code == 200
    assert resp.json()["member_id"] == member_id


# 场景 3: GET latest — 缓存未命中 → 404
def test_insight_latest_cache_miss():
    """缓存中无洞察时，GET latest 返回 404。"""
    insight_mod._insight_cache.clear()
    client = TestClient(insight_app)
    resp = client.get(
        f"/api/v1/members/{_uid()}/insights/latest",
        headers=HEADERS,
    )

    assert resp.status_code == 404
    assert "generate" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ★ rewards_routes — 3 个测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# 场景 4: GET / — 正常商品列表（空）
def test_rewards_list_ok():
    """商品列表正常查询，返回 ok=True 和空列表。"""
    db = AsyncMock()
    cnt_result = MagicMock()
    cnt_result.scalar.return_value = 0
    rows_result = MagicMock()
    rows_result.all.return_value = []
    db.execute = AsyncMock(
        side_effect=[
            MagicMock(),  # _set_rls (set_config)
            cnt_result,  # COUNT(*)
            rows_result,  # SELECT items
        ]
    )
    _rewards_override(db)

    client = TestClient(rewards_app)
    resp = client.get("/api/v1/member/rewards/", headers=HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 0


# 场景 5: POST /redeem — 商品不存在 → 404
def test_rewards_redeem_not_found():
    """兑换时商品不存在（product_row.first()=None），返回 404。"""
    db = AsyncMock()
    product_result = MagicMock()
    product_result.first.return_value = None
    db.execute = AsyncMock(
        side_effect=[
            MagicMock(),  # _set_rls
            product_result,  # SELECT product FOR UPDATE
        ]
    )
    _rewards_override(db)

    client = TestClient(rewards_app)
    resp = client.post(
        "/api/v1/member/rewards/redeem",
        json={"reward_id": _uid(), "customer_id": _uid()},
        headers=HEADERS,
    )

    assert resp.status_code == 404
    assert "reward_not_found" in resp.json()["detail"]


# 场景 6: POST /redeem — 积分不足
def test_rewards_redeem_insufficient_points():
    """会员积分不足时返回 ok=False，code=INSUFFICIENT_POINTS。"""
    db = AsyncMock()

    # product row: id, name, points_required=1000, stock=-1, is_active=T, is_deleted=F, valid_from=None, valid_until=None
    product_row = (uuid.uuid4(), "咖啡券", 1000, -1, True, False, None, None)
    product_result = MagicMock()
    product_result.first.return_value = product_row

    # card row: id=uuid, points=50（不足）
    card_row = (uuid.uuid4(), 50)
    card_result = MagicMock()
    card_result.first.return_value = card_row

    db.execute = AsyncMock(
        side_effect=[
            MagicMock(),  # _set_rls
            product_result,  # SELECT product FOR UPDATE
            card_result,  # SELECT member_cards FOR UPDATE
        ]
    )
    _rewards_override(db)

    client = TestClient(rewards_app)
    resp = client.post(
        "/api/v1/member/rewards/redeem",
        json={"reward_id": _uid(), "customer_id": _uid()},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "INSUFFICIENT_POINTS"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ★ rfm_routes — 3 个测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# 场景 7: POST /trigger-update — 正常触发
def test_rfm_trigger_update_ok():
    """手动触发 RFM 更新，RFMUpdater.update_tenant_rfm 被调用，返回 ok=True。"""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    _rfm_override(db)
    _MOCK_RFM_UPDATER.update_tenant_rfm = AsyncMock(return_value=15)

    client = TestClient(rfm_app)
    resp = client.post(
        "/api/v1/member/rfm/trigger-update",
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total_updated"] == 15


# 场景 8: GET /distribution — 正常分布
def test_rfm_distribution_ok():
    """查询 RFM 等级分布，返回包含 S1-S5 的 distribution 列表。"""
    db = AsyncMock()
    rls_result = MagicMock()
    dist_result = MagicMock()
    dist_result.all.return_value = [("S1", 10), ("S2", 5)]
    db.execute = AsyncMock(side_effect=[rls_result, dist_result])
    _rfm_override(db)

    client = TestClient(rfm_app)
    resp = client.get(
        "/api/v1/member/rfm/distribution",
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    levels = [d["level"] for d in body["data"]["distribution"]]
    assert "S1" in levels
    assert "S3" in levels  # 补全缺失等级


# 场景 9: GET /changes — 正常今日变化（空，降级查询）
def test_rfm_changes_ok():
    """today changes 接口正常返回，即使 rfm_change_logs 不存在也不报 500。"""
    db = AsyncMock()
    rls_result = MagicMock()
    # 模拟 rfm_change_logs 表查询成功但返回空结果
    count_result = MagicMock()
    count_result.scalar.return_value = 0
    rows_result = MagicMock()
    rows_result.all.return_value = []
    db.execute = AsyncMock(side_effect=[rls_result, count_result, rows_result])
    _rfm_override(db)

    client = TestClient(rfm_app)
    resp = client.get(
        "/api/v1/member/rfm/changes",
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ★ tier_routes — 3 个测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# 场景 10: GET /tiers — 正常等级列表
def test_tier_list_ok():
    """查询等级列表正常返回 ok=True。"""
    db = AsyncMock()
    rows_result = MagicMock()
    rows_result.all.return_value = []
    db.execute = AsyncMock(side_effect=[MagicMock(), rows_result])
    _tier_override(db)

    client = TestClient(tier_app)
    resp = client.get("/api/v1/member/tiers", headers=HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "tiers" in body["data"]


# 场景 11: POST /tiers — 缺少 name → 422
def test_tier_create_missing_name():
    """新建等级缺少必填的 name 字段，Pydantic 验证失败返回 422。"""
    client = TestClient(tier_app)
    resp = client.post(
        "/api/v1/member/tiers",
        json={"level": 2},  # 缺少 name
        headers=HEADERS,
    )
    assert resp.status_code == 422


# 场景 12: GET /tiers/{id} — 等级不存在 → 404
def test_tier_get_not_found():
    """等级不存在时返回 404。"""
    db = AsyncMock()
    not_found_result = MagicMock()
    not_found_result.first.return_value = None
    db.execute = AsyncMock(side_effect=[MagicMock(), not_found_result])
    _tier_override(db)

    client = TestClient(tier_app)
    resp = client.get(
        f"/api/v1/member/tiers/{_uid()}",
        headers=HEADERS,
    )

    assert resp.status_code == 404
    assert "等级不存在" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ★ platform_routes — 3 个测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# 场景 13: POST /platform/meituan/order — 无效租户ID → 400
def test_platform_meituan_invalid_tenant():
    """X-Tenant-ID 不是有效 UUID 时返回 400。"""
    client = TestClient(platform_app)
    resp = client.post(
        "/api/v1/member/platform/meituan/order",
        json={"order_no": "MT-001", "amount_fen": 5000, "store_id": _uid()},
        headers={"X-Tenant-ID": "not-a-uuid"},
    )

    assert resp.status_code == 400
    assert "invalid_tenant_id" in resp.json()["detail"]


# 场景 14: POST /platform/douyin/order — 正常绑定
def test_platform_douyin_order_ok():
    """抖音订单绑定成功，返回 ok=True 和 customer_id。"""
    customer_id = _uid()
    _MOCK_PBS.bind_douyin_order = AsyncMock(return_value={"customer_id": customer_id})

    # platform_routes 使用 async with get_db_with_tenant(...)
    # 需要 patch 模块级的 get_db_with_tenant
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _fake_ctx(tenant_id):  # noqa: ARG001
        yield AsyncMock()

    with patch.object(platform_mod, "get_db_with_tenant", _fake_ctx):
        client = TestClient(platform_app)
        resp = client.post(
            "/api/v1/member/platform/douyin/order",
            json={"order_no": "DY-001", "amount_fen": 8000, "store_id": _uid()},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["customer_id"] == customer_id


# 场景 15: GET /platform/stats — 正常统计
def test_platform_stats_ok():
    """平台绑定统计接口正常返回各平台数据。"""
    stats = {"meituan": {"total_bound": 100}, "douyin": {"total_bound": 80}}
    _MOCK_PBS.get_platform_binding_stats = AsyncMock(return_value=stats)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _fake_ctx(tenant_id):  # noqa: ARG001
        yield AsyncMock()

    with patch.object(platform_mod, "get_db_with_tenant", _fake_ctx):
        client = TestClient(platform_app)
        resp = client.get(
            "/api/v1/member/platform/stats",
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "meituan" in body["data"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ★ invoice_routes — 3 个测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# 场景 16: GET /invoice-titles — 正常列表
def test_invoice_titles_list_ok():
    """查询发票抬头列表，返回 ok=True 和空列表。"""
    db = AsyncMock()
    rows_result = MagicMock()
    rows_result.all.return_value = []
    db.execute = AsyncMock(side_effect=[MagicMock(), rows_result])
    _invoice_override(db)

    client = TestClient(invoice_app)
    resp = client.get(
        "/api/v1/member/invoice-titles",
        params={"customer_id": _uid()},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 0


# 场景 17: POST /invoice-titles — 缺少 customer_id → 422
def test_invoice_title_create_missing_field():
    """创建发票抬头缺少 customer_id 字段，返回 422。"""
    client = TestClient(invoice_app)
    resp = client.post(
        "/api/v1/member/invoice-titles",
        json={"title": "张三", "type": "personal"},  # 缺少 customer_id
        headers=HEADERS,
    )
    assert resp.status_code == 422


# 场景 18: GET /invoices — 正常历史发票（空）
def test_invoices_list_ok():
    """查询历史发票列表，返回 ok=True 和 total=0。"""
    db = AsyncMock()
    cnt_result = MagicMock()
    cnt_result.scalar.return_value = 0
    rows_result = MagicMock()
    rows_result.all.return_value = []
    db.execute = AsyncMock(
        side_effect=[
            MagicMock(),  # _set_rls
            cnt_result,  # COUNT(*)
            rows_result,  # SELECT items
        ]
    )
    _invoice_override(db)

    client = TestClient(invoice_app)
    resp = client.get(
        "/api/v1/member/invoices",
        params={"customer_id": _uid()},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 0
