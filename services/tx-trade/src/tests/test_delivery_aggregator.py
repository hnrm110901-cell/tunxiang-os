"""
Y-A5 外卖聚合深度 — 测试套件
测试目标：delivery_aggregator_routes + aggregator_reconcile_routes
共 15 个测试用例
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ..api import aggregator_reconcile_routes as rec_mod
from ..api import delivery_aggregator_routes as agg_mod
from ..api.aggregator_reconcile_routes import router as reconcile_router

# ──────────────────────────────────────────────────────────────────────────────
# 测试 App 初始化（隔离内存存储，避免测试互相污染）
# ──────────────────────────────────────────────────────────────────────────────
from ..api.delivery_aggregator_routes import router as aggregator_router


@pytest.fixture(autouse=True)
def _clear_stores():
    """每个测试前清空内存存储，保证隔离性"""
    agg_mod._ORDERS.clear()
    agg_mod._IDEMPOTENCY_KEYS.clear()
    agg_mod._METRICS_STORE.clear()
    rec_mod._RECONCILE_RESULTS.clear()
    rec_mod._DISCREPANCIES.clear()
    yield
    agg_mod._ORDERS.clear()
    agg_mod._IDEMPOTENCY_KEYS.clear()
    agg_mod._METRICS_STORE.clear()
    rec_mod._RECONCILE_RESULTS.clear()
    rec_mod._DISCREPANCIES.clear()


@pytest.fixture
def app():
    _app = FastAPI()
    _app.include_router(aggregator_router)
    _app.include_router(reconcile_router)
    return _app


@pytest.fixture
def client(app):
    return TestClient(app)


# ──────────────────────────────────────────────────────────────────────────────
# 公共测试数据
# ──────────────────────────────────────────────────────────────────────────────

TENANT_ID = "test-tenant-001"
SIGN_HEADER = {"X-Platform-Sign": "mock-sign-abc123", "X-Tenant-ID": TENANT_ID}

BASE_PAYLOAD = {
    "platform_order_id": "PLAT-ORDER-0001",
    "store_id": "store-001",
    "items": [
        {
            "dish_name": "剁椒鱼头",
            "quantity": 1,
            "unit_price_fen": 12800,
            "spec": "大份",
        }
    ],
    "total_fen": 12800,
    "customer_phone": "13812345678",
    "estimated_delivery_at": "2026-04-07T18:30:00+08:00",
    "platform_status": "new",
    "extra": {"remark": "不要辣"},
}


def _make_payload(**overrides):
    return {**BASE_PAYLOAD, **overrides}


# ──────────────────────────────────────────────────────────────────────────────
# 1. test_webhook_meituan_new_order
# ──────────────────────────────────────────────────────────────────────────────


def test_webhook_meituan_new_order(client):
    """美团新订单 Webhook → 落库成功，is_new=True"""
    resp = client.post(
        "/api/v1/trade/aggregator/webhook/meituan",
        json=_make_payload(platform_order_id="MT-0001"),
        headers=SIGN_HEADER,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["is_new"] is True
    assert "aggregator_order_id" in data["data"]
    # platform_ack 应包含美团 ACK 格式
    assert data["data"]["platform_ack"].get("errno") == 0


# ──────────────────────────────────────────────────────────────────────────────
# 2. test_webhook_eleme_new_order
# ──────────────────────────────────────────────────────────────────────────────


def test_webhook_eleme_new_order(client):
    """饿了么新订单 Webhook → 落库成功，ACK 格式符合饿了么规范"""
    resp = client.post(
        "/api/v1/trade/aggregator/webhook/eleme",
        json=_make_payload(platform_order_id="EL-0001"),
        headers=SIGN_HEADER,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["is_new"] is True
    # 饿了么 ACK: {"code": 200, "msg": "success"}
    assert data["data"]["platform_ack"].get("code") == 200


# ──────────────────────────────────────────────────────────────────────────────
# 3. test_webhook_douyin_new_order
# ──────────────────────────────────────────────────────────────────────────────


def test_webhook_douyin_new_order(client):
    """抖音新订单 Webhook → 落库成功，ACK 格式符合抖音规范"""
    resp = client.post(
        "/api/v1/trade/aggregator/webhook/douyin",
        json=_make_payload(platform_order_id="DY-0001"),
        headers=SIGN_HEADER,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["is_new"] is True
    # 抖音 ACK: {"err_no": 0, "err_tips": "success"}
    assert data["data"]["platform_ack"].get("err_no") == 0


# ──────────────────────────────────────────────────────────────────────────────
# 4. test_webhook_missing_sign_returns_401
# ──────────────────────────────────────────────────────────────────────────────


def test_webhook_missing_sign_returns_401(client):
    """缺少 X-Platform-Sign header → 401 SIGN_INVALID"""
    resp = client.post(
        "/api/v1/trade/aggregator/webhook/meituan",
        json=_make_payload(platform_order_id="MT-NO-SIGN"),
        headers={"X-Tenant-ID": TENANT_ID},  # 故意不传 X-Platform-Sign
    )
    assert resp.status_code == 401
    data = resp.json()
    assert data["detail"]["error"]["code"] == "SIGN_INVALID"


# ──────────────────────────────────────────────────────────────────────────────
# 5. test_webhook_idempotent_duplicate
# ──────────────────────────────────────────────────────────────────────────────


def test_webhook_idempotent_duplicate(client):
    """相同平台单号重复推送 → 第二次 is_new=False，内存中只有一条订单"""
    payload = _make_payload(platform_order_id="MT-DUPE-0001")

    # 第一次推送
    r1 = client.post(
        "/api/v1/trade/aggregator/webhook/meituan",
        json=payload,
        headers=SIGN_HEADER,
    )
    assert r1.status_code == 200
    assert r1.json()["data"]["is_new"] is True
    order_id_1 = r1.json()["data"]["aggregator_order_id"]

    # 第二次推送（相同 platform_order_id）
    r2 = client.post(
        "/api/v1/trade/aggregator/webhook/meituan",
        json=payload,
        headers=SIGN_HEADER,
    )
    assert r2.status_code == 200
    assert r2.json()["data"]["is_new"] is False
    order_id_2 = r2.json()["data"]["aggregator_order_id"]

    # 幂等：返回同一条记录 ID
    assert order_id_1 == order_id_2

    # 内存中只有一条订单
    assert len(agg_mod._ORDERS) == 1


# ──────────────────────────────────────────────────────────────────────────────
# 6. test_accept_order
# ──────────────────────────────────────────────────────────────────────────────


def test_accept_order(client):
    """接单：new → accepted 状态流转"""
    # 先推一条新单
    resp = client.post(
        "/api/v1/trade/aggregator/webhook/meituan",
        json=_make_payload(platform_order_id="MT-ACCEPT-001", platform_status="new"),
        headers=SIGN_HEADER,
    )
    order_id = resp.json()["data"]["aggregator_order_id"]

    # 接单
    acc_resp = client.post(
        f"/api/v1/trade/aggregator/orders/{order_id}/accept",
        headers={"X-Tenant-ID": TENANT_ID},
    )
    assert acc_resp.status_code == 200
    data = acc_resp.json()
    assert data["ok"] is True
    assert data["data"]["status"] == "accepted"


# ──────────────────────────────────────────────────────────────────────────────
# 7. test_cancel_order
# ──────────────────────────────────────────────────────────────────────────────


def test_cancel_order(client):
    """取消单：new → cancelled 状态流转"""
    resp = client.post(
        "/api/v1/trade/aggregator/webhook/eleme",
        json=_make_payload(platform_order_id="EL-CANCEL-001", platform_status="new"),
        headers=SIGN_HEADER,
    )
    order_id = resp.json()["data"]["aggregator_order_id"]

    cancel_resp = client.post(
        f"/api/v1/trade/aggregator/orders/{order_id}/cancel",
        json={"reason": "顾客主动取消"},
        headers={"X-Tenant-ID": TENANT_ID},
    )
    assert cancel_resp.status_code == 200
    data = cancel_resp.json()
    assert data["ok"] is True
    assert data["data"]["status"] == "cancelled"


# ──────────────────────────────────────────────────────────────────────────────
# 8. test_aggregator_orders_list
# ──────────────────────────────────────────────────────────────────────────────


def test_aggregator_orders_list(client):
    """聚合订单列表：推入3条单（美团/饿了么/抖音各一），分页查询全部返回"""
    for platform, oid in [("meituan", "MT-L001"), ("eleme", "EL-L001"), ("douyin", "DY-L001")]:
        client.post(
            f"/api/v1/trade/aggregator/webhook/{platform}",
            json=_make_payload(platform_order_id=oid),
            headers=SIGN_HEADER,
        )

    resp = client.get(
        "/api/v1/trade/aggregator/orders?page=1&size=20",
        headers={"X-Tenant-ID": TENANT_ID},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["total"] == 3
    assert len(data["data"]["items"]) == 3


# ──────────────────────────────────────────────────────────────────────────────
# 9. test_aggregator_order_detail
# ──────────────────────────────────────────────────────────────────────────────


def test_aggregator_order_detail(client):
    """聚合订单详情：包含 items、platform_label 等完整字段"""
    resp = client.post(
        "/api/v1/trade/aggregator/webhook/meituan",
        json=_make_payload(platform_order_id="MT-DETAIL-001"),
        headers=SIGN_HEADER,
    )
    order_id = resp.json()["data"]["aggregator_order_id"]

    detail_resp = client.get(
        f"/api/v1/trade/aggregator/orders/{order_id}",
        headers={"X-Tenant-ID": TENANT_ID},
    )
    assert detail_resp.status_code == 200
    detail = detail_resp.json()["data"]
    assert detail["id"] == order_id
    assert detail["platform"] == "meituan"
    assert detail["platform_label"] == "美团外卖"
    assert "items" in detail
    assert len(detail["items"]) == 1
    assert detail["items"][0]["dish_name"] == "剁椒鱼头"


# ──────────────────────────────────────────────────────────────────────────────
# 10. test_platforms_status
# ──────────────────────────────────────────────────────────────────────────────


def test_platforms_status(client):
    """平台状态：返回3个平台，字段结构正确"""
    # 先推一条美团单以产生数据
    client.post(
        "/api/v1/trade/aggregator/webhook/meituan",
        json=_make_payload(platform_order_id="MT-STATUS-001"),
        headers=SIGN_HEADER,
    )

    resp = client.get(
        "/api/v1/trade/aggregator/platforms/status",
        headers={"X-Tenant-ID": TENANT_ID},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "platforms" in data
    platforms = data["platforms"]
    assert len(platforms) == 3

    platform_ids = {p["platform"] for p in platforms}
    assert platform_ids == {"meituan", "eleme", "douyin"}

    # 美团今日应有1单
    mt = next(p for p in platforms if p["platform"] == "meituan")
    assert mt["today_order_count"] >= 1
    assert "online" in mt
    assert "today_success_rate" in mt


# ──────────────────────────────────────────────────────────────────────────────
# 11. test_metrics_success_rate
# ──────────────────────────────────────────────────────────────────────────────


def test_metrics_success_rate(client):
    """监控指标：推入成功 Webhook 后，success_rate 应为 1.0"""
    client.post(
        "/api/v1/trade/aggregator/webhook/meituan",
        json=_make_payload(platform_order_id="MT-METRIC-001"),
        headers=SIGN_HEADER,
    )
    client.post(
        "/api/v1/trade/aggregator/webhook/eleme",
        json=_make_payload(platform_order_id="EL-METRIC-001"),
        headers=SIGN_HEADER,
    )

    resp = client.get(
        "/api/v1/trade/aggregator/metrics",
        headers={"X-Tenant-ID": TENANT_ID},
    )
    assert resp.status_code == 200
    metrics = resp.json()["data"]
    assert metrics["total_requests"] == 2
    assert metrics["success_rate"] == 1.0
    assert metrics["avg_latency_ms"] >= 0


# ──────────────────────────────────────────────────────────────────────────────
# 12. test_metrics_by_platform
# ──────────────────────────────────────────────────────────────────────────────


def test_metrics_by_platform(client):
    """监控指标 by_platform：各平台细分统计"""
    for platform, oid in [("meituan", "MT-BP-001"), ("eleme", "EL-BP-001")]:
        client.post(
            f"/api/v1/trade/aggregator/webhook/{platform}",
            json=_make_payload(platform_order_id=oid),
            headers=SIGN_HEADER,
        )

    resp = client.get(
        "/api/v1/trade/aggregator/metrics",
        headers={"X-Tenant-ID": TENANT_ID},
    )
    assert resp.status_code == 200
    by_platform = resp.json()["data"]["by_platform"]
    assert "meituan" in by_platform
    assert "eleme" in by_platform
    assert by_platform["meituan"]["total_requests"] == 1
    assert by_platform["eleme"]["total_requests"] == 1
    # douyin 没有请求，不应出现在 by_platform 中
    assert "douyin" not in by_platform


# ──────────────────────────────────────────────────────────────────────────────
# 13. test_reconcile_run
# ──────────────────────────────────────────────────────────────────────────────


def test_reconcile_run(client):
    """手动触发对账：返回 task_id，状态为 running"""
    resp = client.post(
        "/api/v1/trade/aggregator-reconcile/run",
        json={"platform": "meituan", "date": "2026-04-07"},
        headers={"X-Tenant-ID": TENANT_ID},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "task_id" in data["data"]
    assert data["data"]["status"] == "running"
    assert data["data"]["platform"] == "meituan"


# ──────────────────────────────────────────────────────────────────────────────
# 14. test_reconcile_discrepancies
# ──────────────────────────────────────────────────────────────────────────────


def test_reconcile_discrepancies(client):
    """
    对账后差异单列表：
    - 触发对账（同步执行 background task）
    - 查询差异单列表，应有差异单
    - 差异单字段结构正确（platform、discrepancy_type、discrepancy_amount_fen）
    """
    # 直接调用对账逻辑（同步）以绕过 BackgroundTasks
    rec_mod._run_reconcile_logic(
        task_id="test-task-001",
        tenant_id=TENANT_ID,
        platform="meituan",
        reconcile_date="2026-04-07",
        store_id=None,
    )

    resp = client.get(
        "/api/v1/trade/aggregator-reconcile/discrepancies",
        headers={"X-Tenant-ID": TENANT_ID},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] > 0
    disc = data["items"][0]
    assert "platform" in disc
    assert "discrepancy_type" in disc
    assert "discrepancy_amount_fen" in disc
    assert disc["discrepancy_type"] in ("local_only", "platform_only", "amount_mismatch")
    assert not disc["resolved"]


# ──────────────────────────────────────────────────────────────────────────────
# 15. test_reconcile_discrepancy_amount_is_integer
# ──────────────────────────────────────────────────────────────────────────────


def test_reconcile_discrepancy_amount_is_integer(client):
    """差异金额必须是整数（分），不允许浮点数"""
    rec_mod._run_reconcile_logic(
        task_id="test-task-002",
        tenant_id=TENANT_ID,
        platform="eleme",
        reconcile_date="2026-04-07",
        store_id=None,
    )

    resp = client.get(
        "/api/v1/trade/aggregator-reconcile/discrepancies",
        headers={"X-Tenant-ID": TENANT_ID},
    )
    items = resp.json()["data"]["items"]
    assert len(items) > 0

    for disc in items:
        amount = disc["discrepancy_amount_fen"]
        # 必须是整数类型（int）
        assert isinstance(amount, int), (
            f"discrepancy_amount_fen 必须为整数，实际类型：{type(amount).__name__}，值：{amount}"
        )
        # 不允许 None
        assert amount is not None
        # 金额必须 >= 0
        assert amount >= 0
