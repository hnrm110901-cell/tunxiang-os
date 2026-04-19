"""
上线交付 API 单元测试（onboarding_routes）

测试场景：
  1. GET /templates — 返回所有业态模板
  2. POST /start — 创建会话（新客户 / 天财迁移预填入）
  3. POST /{sid}/answer — 单问/批量回答
  4. GET /{sid}/preview — 实时预览
  5. POST /{sid}/confirm — 确认（缺必填时应报错）
  6. DeliveryAgent 20问覆盖度检查
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ..api.onboarding_routes import DELIVERY_QUESTIONS, REQUIRED_KEYS, router

# ── 测试应用 ──────────────────────────────────────────────────────────

app = FastAPI()
app.include_router(router)
client = TestClient(app, raise_server_exceptions=True)

TENANT_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

# 完整的 20 问答案集（用于 confirm 测试）
FULL_ANSWERS = {
    "restaurant_type": "casual_dining",
    "store_name": "测试餐厅",
    "table_count": 20,
    "vip_room_count": 2,
    "kds_zones": [],
    "printer_count": 3,
    "employee_max_discount": 0.88,
    "manager_max_discount": 0.80,
    "min_spend_yuan": 0,
    "service_fee_rate": 0.0,
    "payment_methods": ["wechat", "alipay", "cash"],
    "point_rate": 1.0,
    "point_redeem_rate": 100.0,
    "channels_enabled": ["meituan"],
    "inventory_level": "ingredient",
    "employee_roles": ["cashier", "waiter", "manager"],
    "has_piecework_commission": False,
    "shifts": [
        {"shift_name": "午市", "start_time": "10:30", "end_time": "14:30"},
        {"shift_name": "晚市", "start_time": "17:00", "end_time": "21:30"},
    ],
    "settlement_cutoff": "02:00",
    "daily_report_phones": "",
}


# ── GET /templates ────────────────────────────────────────────────────


def test_list_templates_returns_five():
    resp = client.get("/api/v1/onboarding/templates")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 5


def test_list_templates_has_required_fields():
    resp = client.get("/api/v1/onboarding/templates")
    for tpl in resp.json()["data"]:
        assert "type" in tpl
        assert "display_name" in tpl
        assert "description" in tpl


# ── POST /start ───────────────────────────────────────────────────────


def test_start_session_new_customer():
    resp = client.post(
        "/api/v1/onboarding/start",
        json={
            "tenant_id": TENANT_ID,
            "migration_source": "new",
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "session_id" in data
    assert data["answered_count"] == 0
    assert data["next_question"] is not None
    assert data["next_question"]["required"] is True


def test_start_session_with_prefilled():
    """天财迁移：传入 prefilled_answers 应跳过已知问题"""
    resp = client.post(
        "/api/v1/onboarding/start",
        json={
            "tenant_id": TENANT_ID,
            "migration_source": "tiancai",
            "prefilled_answers": {
                "restaurant_type": "casual_dining",
                "store_name": "天财切换门店",
                "table_count": 25,
            },
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["answered_count"] == 3
    assert data["progress_pct"] > 0


def test_start_session_returns_session_id():
    resp = client.post("/api/v1/onboarding/start", json={"tenant_id": TENANT_ID})
    sid = resp.json()["data"]["session_id"]
    assert len(sid) == 36  # UUID 格式


# ── POST /{sid}/answer ────────────────────────────────────────────────


def _create_session() -> str:
    resp = client.post("/api/v1/onboarding/start", json={"tenant_id": TENANT_ID})
    return resp.json()["data"]["session_id"]


def test_answer_single_question():
    sid = _create_session()
    resp = client.post(
        f"/api/v1/onboarding/{sid}/answer",
        json={
            "key": "restaurant_type",
            "value": "hot_pot",
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["answered_count"] == 1


def test_answer_batch_questions():
    sid = _create_session()
    resp = client.post(
        f"/api/v1/onboarding/{sid}/answer",
        json={
            "answers": {
                "restaurant_type": "banquet",
                "store_name": "宴席大酒楼",
                "table_count": 30,
            },
        },
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["answered_count"] == 3


def test_answer_nonexistent_session_returns_404():
    resp = client.post(
        "/api/v1/onboarding/nonexistent-id/answer",
        json={
            "key": "restaurant_type",
            "value": "casual_dining",
        },
    )
    assert resp.status_code == 404


def test_answer_requires_key_or_answers():
    sid = _create_session()
    resp = client.post(f"/api/v1/onboarding/{sid}/answer", json={})
    assert resp.status_code == 422


# ── GET /{sid}/preview ────────────────────────────────────────────────


def test_preview_returns_config_package():
    sid = _create_session()
    client.post(
        f"/api/v1/onboarding/{sid}/answer",
        json={
            "answers": {"restaurant_type": "casual_dining"},
        },
    )
    resp = client.get(f"/api/v1/onboarding/{sid}/preview")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "config_preview" in data
    assert data["config_preview"]["restaurant_type"] == "casual_dining"


def test_preview_shows_unanswered_required():
    sid = _create_session()
    resp = client.get(f"/api/v1/onboarding/{sid}/preview")
    assert resp.json()["data"]["is_ready"] is False
    assert len(resp.json()["data"]["unanswered_required"]) > 0


# ── POST /{sid}/confirm ───────────────────────────────────────────────


def test_confirm_fails_without_required_answers():
    sid = _create_session()
    # 只回答了一个非必填问题
    client.post(
        f"/api/v1/onboarding/{sid}/answer",
        json={
            "key": "vip_room_count",
            "value": 2,
        },
    )
    resp = client.post(f"/api/v1/onboarding/{sid}/confirm")
    assert resp.status_code == 422


def test_confirm_succeeds_with_all_required():
    sid = _create_session()
    # 批量回答所有必填问题
    client.post(f"/api/v1/onboarding/{sid}/answer", json={"answers": FULL_ANSWERS})
    resp = client.post(f"/api/v1/onboarding/{sid}/confirm")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "config_package" in data
    assert data["config_package"]["restaurant_type"] == "casual_dining"


def test_confirm_locks_session():
    """确认后不能再修改答案"""
    sid = _create_session()
    client.post(f"/api/v1/onboarding/{sid}/answer", json={"answers": FULL_ANSWERS})
    client.post(f"/api/v1/onboarding/{sid}/confirm")

    resp = client.post(
        f"/api/v1/onboarding/{sid}/answer",
        json={
            "key": "store_name",
            "value": "尝试修改",
        },
    )
    assert resp.status_code == 409


def test_double_confirm_returns_409():
    sid = _create_session()
    client.post(f"/api/v1/onboarding/{sid}/answer", json={"answers": FULL_ANSWERS})
    client.post(f"/api/v1/onboarding/{sid}/confirm")
    resp = client.post(f"/api/v1/onboarding/{sid}/confirm")
    assert resp.status_code == 409


# ── 20问覆盖度元测试 ──────────────────────────────────────────────────


def test_twenty_questions_coverage():
    """20问中必须覆盖关键配置域"""
    all_keys = {q["key"] for q in DELIVERY_QUESTIONS}
    critical_domains = {
        "restaurant_type",  # 业态
        "table_count",  # 桌台
        "printer_count",  # 打印机
        "employee_max_discount",  # 折扣守护
        "payment_methods",  # 支付
        "channels_enabled",  # 外卖
        "shifts",  # 营业时段
        "employee_roles",  # 员工
        "point_rate",  # 积分
    }
    missing = critical_domains - all_keys
    assert not missing, f"20问缺少关键配置域：{missing}"


def test_required_questions_subset_of_all():
    all_keys = {q["key"] for q in DELIVERY_QUESTIONS}
    assert REQUIRED_KEYS.issubset(all_keys), "REQUIRED_KEYS 中有不在 DELIVERY_QUESTIONS 的 key"


def test_required_questions_have_hint():
    """必填问题必须有 hint，方便引导商户"""
    for q in DELIVERY_QUESTIONS:
        if q.get("required"):
            assert q.get("hint") or q.get("example"), f"必填问题 {q['key']} 缺少 hint 或 example"
