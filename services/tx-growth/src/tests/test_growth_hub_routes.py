"""增长中枢 V2 API 路由测试 — api/growth_hub_routes.py

覆盖场景：
1.  GET  /api/v1/growth/customers/{id}/profile          — 正常返回客户增长画像
2.  GET  /api/v1/growth/customers/{id}/profile          — X-Tenant-ID 格式错误 → 400
3.  GET  /api/v1/growth/customers/{id}/profile          — 画像不存在返回 err
4.  PATCH /api/v1/growth/customers/{id}/profile         — 正常更新增长画像
5.  GET  /api/v1/growth/journey-templates               — 正常返回旅程模板列表
6.  POST /api/v1/growth/journey-templates               — 正常创建旅程模板
7.  GET  /api/v1/growth/journey-templates/{id}          — 模板存在时返回详情
8.  GET  /api/v1/growth/journey-templates/{id}          — 模板不存在返回 err
9.  PUT  /api/v1/growth/journey-templates/{id}          — 正常更新旅程模板
10. POST /api/v1/growth/journey-templates/{id}/activate — 激活旅程模板
11. POST /api/v1/growth/journey-templates/{id}/deactivate — 停用旅程模板
12. GET  /api/v1/growth/journey-enrollments             — 正常返回旅程参与列表
13. POST /api/v1/growth/journey-enrollments             — 正常创建旅程参与
14. GET  /api/v1/growth/journey-enrollments/{id}        — 参与存在时返回详情
15. PATCH /api/v1/growth/journey-enrollments/{id}/state — 正常更新参与状态
16. GET  /api/v1/growth/touch-executions                — 正常返回触达执行列表
17. POST /api/v1/growth/touch-executions                — 正常创建触达执行
18. PATCH /api/v1/growth/touch-executions/{id}          — 更新触达执行状态
19. PATCH /api/v1/growth/touch-executions/{id}/attribution — 更新触达归因
20. GET  /api/v1/growth/service-repair-cases            — 正常返回服务修复列表
21. POST /api/v1/growth/service-repair-cases            — 正常创建服务修复
22. GET  /api/v1/growth/service-repair-cases/{id}       — 修复案例存在时返回详情
23. PATCH /api/v1/growth/service-repair-cases/{id}/state — 更新修复状态
24. PATCH /api/v1/growth/service-repair-cases/{id}/compensation — 更新补偿方案
25. GET  /api/v1/growth/agent-suggestions               — 正常返回策略建议列表
26. POST /api/v1/growth/agent-suggestions               — 正常创建策略建议
27. GET  /api/v1/growth/agent-suggestions/{id}          — 建议存在时返回详情
28. POST /api/v1/growth/agent-suggestions/{id}/review   — 审核策略建议
29. POST /api/v1/growth/agent-suggestions/{id}/publish  — 发布策略建议
30. PATCH /api/v1/growth/customers/{id}/profile         — ValueError 路径返回 err
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import types as _types
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── stub: structlog ──────────────────────────────────────────────────────────
_structlog_mod = _types.ModuleType("structlog")
_structlog_mod.get_logger = lambda *a, **kw: MagicMock()
sys.modules.setdefault("structlog", _structlog_mod)

# ── stub: sqlalchemy ─────────────────────────────────────────────────────────
import sqlalchemy as _sa

sys.modules.setdefault("sqlalchemy", _sa)

# ── stub: shared.ontology.src.database (async_session_factory) ──────────────
_shared_mod = _types.ModuleType("shared")
_ont_mod = _types.ModuleType("shared.ontology")
_ont_src_mod = _types.ModuleType("shared.ontology.src")
_ont_db_mod = _types.ModuleType("shared.ontology.src.database")

# async_session_factory returns an async context manager yielding a mock db
_MOCK_DB = AsyncMock()
_MOCK_DB.execute = AsyncMock()
_MOCK_DB.commit = AsyncMock()


@asynccontextmanager
async def _fake_session_factory():
    yield _MOCK_DB


_ont_db_mod.async_session_factory = _fake_session_factory

sys.modules.setdefault("shared", _shared_mod)
sys.modules["shared.ontology"] = _ont_mod
sys.modules["shared.ontology.src"] = _ont_src_mod
sys.modules["shared.ontology.src.database"] = _ont_db_mod

# ── stub: services.growth_profile_service ───────────────────────────────────
_svc_services = _types.ModuleType("services")
sys.modules.setdefault("services", _svc_services)

_profile_svc_mod = _types.ModuleType("services.growth_profile_service")


class _FakeGrowthProfileService:
    async def get_profile(self, customer_id, tenant_id, db):
        return {"customer_id": str(customer_id), "repurchase_stage": "active"}

    async def update_profile(self, customer_id, tenant_id, data, db):
        return {"customer_id": str(customer_id), **data}

    async def batch_compute_p1_fields(self, tenant_id, db):
        return {"updated_count": 0, "duration_ms": 0}


_profile_svc_mod.GrowthProfileService = _FakeGrowthProfileService
sys.modules["services.growth_profile_service"] = _profile_svc_mod

# ── stub: services.growth_journey_service ────────────────────────────────────
_journey_svc_mod = _types.ModuleType("services.growth_journey_service")


class _FakeGrowthJourneyService:
    async def list_templates(self, tenant_id, db, **kw):
        return {"items": [], "total": 0}

    async def create_template(self, tenant_id, data, db):
        return {"id": str(uuid.uuid4()), **data}

    async def get_template(self, template_id, tenant_id, db):
        return {"id": template_id, "name": "旅程模板"}

    async def update_template(self, template_id, tenant_id, data, db):
        return {"id": template_id, **data}

    async def activate_template(self, template_id, tenant_id, db):
        return {"id": template_id, "is_active": True}

    async def deactivate_template(self, template_id, tenant_id, db):
        return {"id": template_id, "is_active": False}

    async def list_enrollments(self, tenant_id, db, **kw):
        return {"items": [], "total": 0}

    async def create_enrollment(self, tenant_id, data, db):
        return {"id": str(uuid.uuid4()), **data}

    async def get_enrollment(self, enrollment_id, tenant_id, db):
        return {"id": enrollment_id, "journey_state": "active"}

    async def update_enrollment_state(self, enrollment_id, tenant_id, data, db):
        return {"id": enrollment_id, **data}


_journey_svc_mod.GrowthJourneyService = _FakeGrowthJourneyService
sys.modules["services.growth_journey_service"] = _journey_svc_mod

# ── stub: services.growth_touch_service ──────────────────────────────────────
_touch_svc_mod = _types.ModuleType("services.growth_touch_service")


class _FakeGrowthTouchService:
    async def list_executions(self, tenant_id, db, **kw):
        return {"items": [], "total": 0}

    async def create_execution(self, tenant_id, data, db):
        return {"id": str(uuid.uuid4()), **data}

    async def update_execution_state(self, execution_id, tenant_id, data, db):
        return {"id": execution_id, **data}

    async def update_attribution(self, execution_id, tenant_id, data, db):
        return {"id": execution_id, **data}


_touch_svc_mod.GrowthTouchService = _FakeGrowthTouchService
sys.modules["services.growth_touch_service"] = _touch_svc_mod

# ── stub: services.growth_repair_service ─────────────────────────────────────
_repair_svc_mod = _types.ModuleType("services.growth_repair_service")


class _FakeGrowthRepairService:
    async def list_cases(self, tenant_id, db, **kw):
        return {"items": [], "total": 0}

    async def create_case(self, tenant_id, data, db):
        return {"id": str(uuid.uuid4()), **data}

    async def get_case(self, case_id, tenant_id, db):
        return {"id": case_id, "repair_state": "open"}

    async def update_case_state(self, case_id, tenant_id, data, db):
        return {"id": case_id, **data}

    async def update_compensation(self, case_id, tenant_id, data, db):
        return {"id": case_id, **data}


_repair_svc_mod.GrowthRepairService = _FakeGrowthRepairService
sys.modules["services.growth_repair_service"] = _repair_svc_mod

# ── stub: services.growth_suggestion_service ─────────────────────────────────
_suggestion_svc_mod = _types.ModuleType("services.growth_suggestion_service")


class _FakeGrowthSuggestionService:
    async def list_suggestions(self, tenant_id, db, **kw):
        return {"items": [], "total": 0}

    async def create_suggestion(self, tenant_id, data, db):
        return {"id": str(uuid.uuid4()), **data}

    async def get_suggestion(self, suggestion_id, tenant_id, db):
        return {"id": suggestion_id, "suggestion_type": "reactivation"}

    async def review_suggestion(self, suggestion_id, tenant_id, data, db):
        return {"id": suggestion_id, **data}

    async def publish_suggestion(self, suggestion_id, tenant_id, db):
        return {"id": suggestion_id, "published": True}


_suggestion_svc_mod.GrowthSuggestionService = _FakeGrowthSuggestionService
sys.modules["services.growth_suggestion_service"] = _suggestion_svc_mod

# ── stub: services.growth_brand_service ─────────────────────────────────────
_brand_svc_mod = _types.ModuleType("services.growth_brand_service")


class _FakeGrowthBrandService:
    async def list_brand_configs(self, tenant_id, db):
        return {"items": [], "total": 0}

    async def upsert_brand_config(self, brand_id, data, tenant_id, db):
        return {"id": str(uuid.uuid4()), "brand_id": str(brand_id), **data}

    async def get_brand_config(self, brand_id, tenant_id, db):
        return {"id": str(uuid.uuid4()), "brand_id": str(brand_id), "brand_name": "Test"}

    async def check_brand_budget(self, brand_id, tenant_id, db):
        return {"daily_budget": 100, "daily_used": 0, "can_touch": True}

    async def check_brand_frequency(self, brand_id, customer_id, tenant_id, db):
        return {"within_limit": True, "daily_count": 0, "weekly_count": 0}


_brand_svc_mod.GrowthBrandService = _FakeGrowthBrandService
sys.modules["services.growth_brand_service"] = _brand_svc_mod

# ── stub: services.growth_experiment_service ────────────────────────────────
_experiment_svc_mod = _types.ModuleType("services.growth_experiment_service")


class _FakeGrowthExperimentService:
    async def get_experiment_summary(self, template_id, tenant_id, db):
        return {"template_id": str(template_id), "variants": [], "total_samples": 0}

    async def select_variant(self, template_id, tenant_id, db):
        return {"selected_variant": "A", "probability": 1.0}

    async def should_auto_pause(self, template_id, min_samples, tenant_id, db):
        return {"should_pause": False, "reason": "样本不足"}

    async def auto_iterate(self, tenant_id, db, **kw):
        return {"paused_variants": [], "actions_taken": 0}

    async def auto_adjust_journey_params(self, tenant_id, db):
        return {"adjustments": [], "total": 0}


_experiment_svc_mod.GrowthExperimentService = _FakeGrowthExperimentService
sys.modules["services.growth_experiment_service"] = _experiment_svc_mod

# ── stub: services.growth_cross_brand_service ──────────────────────────────
_cross_brand_svc_mod = _types.ModuleType("services.growth_cross_brand_service")


class _FakeGrowthCrossBrandService:
    async def get_customer_cross_brand_profile(self, customer_id, tenant_id, db):
        return {"customer_id": str(customer_id), "brands": [], "total_brands": 0}

    async def check_cross_brand_frequency(self, customer_id, tenant_id, db):
        return {"within_limit": True}

    async def find_cross_brand_opportunities(self, tenant_id, db, **kw):
        return {"items": [], "total": 0}

    async def get_cross_brand_recommendation(self, customer_id, source_brand_id, target_brand_id, tenant_id, db):
        return {"recommendation": "none"}


_cross_brand_svc_mod.GrowthCrossBrandService = _FakeGrowthCrossBrandService
sys.modules["services.growth_cross_brand_service"] = _cross_brand_svc_mod

# ── stub: services.growth_store_capability_service ─────────────────────────
_store_cap_svc_mod = _types.ModuleType("services.growth_store_capability_service")


class _FakeGrowthStoreCapabilityService:
    async def get_store_capabilities(self, store_id, tenant_id, db):
        return {"store_id": str(store_id), "capabilities": []}

    async def get_store_growth_readiness(self, store_id, tenant_id, db):
        return {"store_id": str(store_id), "readiness_score": 0}

    async def get_all_stores_readiness(self, tenant_id, db):
        return {"stores": [], "total": 0}

    async def match_journey_to_stores(self, journey_code, tenant_id, db):
        return {"stores": [], "total": 0}


_store_cap_svc_mod.GrowthStoreCapabilityService = _FakeGrowthStoreCapabilityService
sys.modules["services.growth_store_capability_service"] = _store_cap_svc_mod

# ── stub: services.weather_signal_proxy ────────────────────────────────────
_weather_svc_mod = _types.ModuleType("services.weather_signal_proxy")


class _FakeWeatherSignalService:
    async def get_weather_signal(self, city, target_date=None):
        return {"city": city, "weather": "晴", "recommendations": []}

    async def get_weekly_forecast_signals(self, city):
        return {"city": city, "forecasts": []}


_weather_svc_mod.WeatherSignalService = _FakeWeatherSignalService
sys.modules["services.weather_signal_proxy"] = _weather_svc_mod

# ── stub: services.calendar_signal_proxy ───────────────────────────────────
_calendar_svc_mod = _types.ModuleType("services.calendar_signal_proxy")


class _FakeCalendarSignalService:
    def get_upcoming_events(self, days_ahead=14):
        return []

    def get_growth_triggers(self):
        return []

    def get_event_by_date(self, target_date):
        return None


_calendar_svc_mod.CalendarSignalService = _FakeCalendarSignalService
sys.modules["services.calendar_signal_proxy"] = _calendar_svc_mod

# ── stub: seeds.growth_offer_seeds ─────────────────────────────────────────
_seeds_mod = _types.ModuleType("seeds")
sys.modules.setdefault("seeds", _seeds_mod)
_offer_seeds_mod = _types.ModuleType("seeds.growth_offer_seeds")
_offer_seeds_mod.GROWTH_OFFER_PACKS = [
    {
        "id": "offer_001",
        "pack_type": "first_to_second",
        "mechanism_type": "micro_commitment",
        "name": "首单转二访-微承诺礼包",
        "offers": [{"type": "coupon", "value_fen": 500}],
    },
    {
        "id": "offer_002",
        "pack_type": "reactivation",
        "mechanism_type": "loss_aversion",
        "name": "沉默唤醒-损失厌恶礼包",
        "offers": [{"type": "coupon", "value_fen": 1000}],
    },
]
sys.modules["seeds.growth_offer_seeds"] = _offer_seeds_mod

# ── 导入被测路由 ──────────────────────────────────────────────────────────────
from api.growth_hub_routes import router  # noqa: E402

# ── 构建测试 App ──────────────────────────────────────────────────────────────
app = FastAPI()
app.include_router(router)
client = TestClient(app, raise_server_exceptions=False)

# ── 通用常量 ──────────────────────────────────────────────────────────────────
TENANT_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}
BAD_TENANT_HEADERS = {"X-Tenant-ID": "not-a-valid-uuid"}

CUSTOMER_ID = str(uuid.uuid4())
TEMPLATE_ID = str(uuid.uuid4())
ENROLLMENT_ID = str(uuid.uuid4())
EXECUTION_ID = str(uuid.uuid4())
CASE_ID = str(uuid.uuid4())
SUGGESTION_ID = str(uuid.uuid4())


# ── 辅助：重置 _MOCK_DB ──────────────────────────────────────────────────────
def _reset_db():
    _MOCK_DB.execute.reset_mock()
    _MOCK_DB.commit.reset_mock()


# ===========================================================================
# Customer Growth Profile 端点
# ===========================================================================


class TestGetGrowthProfile:
    def test_get_profile_ok(self):
        _reset_db()
        resp = client.get(f"/api/v1/growth/customers/{CUSTOMER_ID}/profile", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "customer_id" in body["data"]

    def test_get_profile_bad_tenant(self):
        resp = client.get(
            f"/api/v1/growth/customers/{CUSTOMER_ID}/profile",
            headers=BAD_TENANT_HEADERS,
        )
        assert resp.status_code == 400

    def test_get_profile_not_found(self):
        """当 service 返回 None 时，响应 ok=False。"""
        _reset_db()
        from api import growth_hub_routes as _mod

        original = _mod._profile_svc.get_profile

        async def _return_none(*a, **kw):
            return None

        _mod._profile_svc.get_profile = _return_none
        try:
            resp = client.get(f"/api/v1/growth/customers/{CUSTOMER_ID}/profile", headers=HEADERS)
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is False
        finally:
            _mod._profile_svc.get_profile = original


class TestUpdateGrowthProfile:
    def test_update_profile_ok(self):
        _reset_db()
        resp = client.patch(
            f"/api/v1/growth/customers/{CUSTOMER_ID}/profile",
            headers=HEADERS,
            json={"repurchase_stage": "second_purchase", "growth_opt_out": False},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True

    def test_update_profile_value_error(self):
        """service 抛出 ValueError 时，响应 ok=False。"""
        _reset_db()
        from api import growth_hub_routes as _mod

        original = _mod._profile_svc.update_profile

        async def _raise(*a, **kw):
            raise ValueError("无效的 repurchase_stage 值")

        _mod._profile_svc.update_profile = _raise
        try:
            resp = client.patch(
                f"/api/v1/growth/customers/{CUSTOMER_ID}/profile",
                headers=HEADERS,
                json={"repurchase_stage": "invalid_stage"},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is False
        finally:
            _mod._profile_svc.update_profile = original


# ===========================================================================
# Journey Templates 端点
# ===========================================================================


class TestJourneyTemplates:
    _TEMPLATE_PAYLOAD = {
        "code": "J001",
        "name": "首单转二单旅程",
        "journey_type": "first_to_second",
        "mechanism_family": "hook",
        "entry_rule_json": {},
        "exit_rule_json": {},
        "pause_rule_json": {},
        "priority": 100,
        "steps": [],
    }

    def test_list_templates_ok(self):
        _reset_db()
        resp = client.get("/api/v1/growth/journey-templates", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "items" in body["data"]

    def test_list_templates_with_filters(self):
        _reset_db()
        resp = client.get(
            "/api/v1/growth/journey-templates?journey_type=first_to_second&is_active=true",
            headers=HEADERS,
        )
        assert resp.status_code == 200

    def test_create_template_ok(self):
        _reset_db()
        resp = client.post(
            "/api/v1/growth/journey-templates",
            headers=HEADERS,
            json=self._TEMPLATE_PAYLOAD,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True

    def test_get_template_ok(self):
        _reset_db()
        resp = client.get(f"/api/v1/growth/journey-templates/{TEMPLATE_ID}", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["id"] == TEMPLATE_ID

    def test_get_template_not_found(self):
        _reset_db()
        from api import growth_hub_routes as _mod

        original = _mod._journey_svc.get_template

        async def _none(*a, **kw):
            return None

        _mod._journey_svc.get_template = _none
        try:
            resp = client.get(f"/api/v1/growth/journey-templates/{TEMPLATE_ID}", headers=HEADERS)
            assert resp.status_code == 200
            assert resp.json()["ok"] is False
        finally:
            _mod._journey_svc.get_template = original

    def test_update_template_ok(self):
        _reset_db()
        resp = client.put(
            f"/api/v1/growth/journey-templates/{TEMPLATE_ID}",
            headers=HEADERS,
            json={**self._TEMPLATE_PAYLOAD, "name": "更新后的旅程"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_activate_template_ok(self):
        _reset_db()
        resp = client.post(
            f"/api/v1/growth/journey-templates/{TEMPLATE_ID}/activate",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["is_active"] is True

    def test_deactivate_template_ok(self):
        _reset_db()
        resp = client.post(
            f"/api/v1/growth/journey-templates/{TEMPLATE_ID}/deactivate",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["is_active"] is False


# ===========================================================================
# Journey Enrollments 端点
# ===========================================================================


class TestJourneyEnrollments:
    _ENROLLMENT_PAYLOAD = {
        "customer_id": CUSTOMER_ID,
        "journey_template_id": TEMPLATE_ID,
        "enrollment_source": "rule_engine",
    }

    def test_list_enrollments_ok(self):
        _reset_db()
        resp = client.get("/api/v1/growth/journey-enrollments", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True

    def test_create_enrollment_ok(self):
        _reset_db()
        resp = client.post(
            "/api/v1/growth/journey-enrollments",
            headers=HEADERS,
            json=self._ENROLLMENT_PAYLOAD,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_get_enrollment_ok(self):
        _reset_db()
        resp = client.get(f"/api/v1/growth/journey-enrollments/{ENROLLMENT_ID}", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["id"] == ENROLLMENT_ID

    def test_get_enrollment_not_found(self):
        _reset_db()
        from api import growth_hub_routes as _mod

        original = _mod._journey_svc.get_enrollment

        async def _none(*a, **kw):
            return None

        _mod._journey_svc.get_enrollment = _none
        try:
            resp = client.get(f"/api/v1/growth/journey-enrollments/{ENROLLMENT_ID}", headers=HEADERS)
            assert resp.status_code == 200
            assert resp.json()["ok"] is False
        finally:
            _mod._journey_svc.get_enrollment = original

    def test_update_enrollment_state_ok(self):
        _reset_db()
        resp = client.patch(
            f"/api/v1/growth/journey-enrollments/{ENROLLMENT_ID}/state",
            headers=HEADERS,
            json={"journey_state": "paused", "pause_reason": "客户要求暂停"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ===========================================================================
# Touch Executions 端点
# ===========================================================================


class TestTouchExecutions:
    _TOUCH_PAYLOAD = {
        "customer_id": CUSTOMER_ID,
        "touch_template_code": "WELCOME_COUPON",
        "channel": "sms",
        "variables": {},
    }

    def test_list_touch_executions_ok(self):
        _reset_db()
        resp = client.get("/api/v1/growth/touch-executions", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_list_with_filters(self):
        _reset_db()
        resp = client.get(
            "/api/v1/growth/touch-executions?channel=sms&execution_state=sent",
            headers=HEADERS,
        )
        assert resp.status_code == 200

    def test_create_touch_execution_ok(self):
        _reset_db()
        resp = client.post(
            "/api/v1/growth/touch-executions",
            headers=HEADERS,
            json=self._TOUCH_PAYLOAD,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_update_execution_state_ok(self):
        _reset_db()
        resp = client.patch(
            f"/api/v1/growth/touch-executions/{EXECUTION_ID}",
            headers=HEADERS,
            json={"execution_state": "delivered"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_update_attribution_ok(self):
        _reset_db()
        resp = client.patch(
            f"/api/v1/growth/touch-executions/{EXECUTION_ID}/attribution",
            headers=HEADERS,
            json={
                "attributed_order_id": str(uuid.uuid4()),
                "attributed_revenue_fen": 8800,
                "attributed_gross_profit_fen": 3200,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True


# ===========================================================================
# Service Repair Cases 端点
# ===========================================================================


class TestServiceRepairCases:
    _CASE_PAYLOAD = {
        "customer_id": CUSTOMER_ID,
        "source_type": "complaint",
        "severity": "high",
        "summary": "客户反映菜品变质",
    }

    def test_list_repair_cases_ok(self):
        _reset_db()
        resp = client.get("/api/v1/growth/service-repair-cases", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_create_repair_case_ok(self):
        _reset_db()
        resp = client.post(
            "/api/v1/growth/service-repair-cases",
            headers=HEADERS,
            json=self._CASE_PAYLOAD,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_get_repair_case_ok(self):
        _reset_db()
        resp = client.get(f"/api/v1/growth/service-repair-cases/{CASE_ID}", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["id"] == CASE_ID

    def test_get_repair_case_not_found(self):
        _reset_db()
        from api import growth_hub_routes as _mod

        original = _mod._repair_svc.get_case

        async def _none(*a, **kw):
            return None

        _mod._repair_svc.get_case = _none
        try:
            resp = client.get(f"/api/v1/growth/service-repair-cases/{CASE_ID}", headers=HEADERS)
            assert resp.status_code == 200
            assert resp.json()["ok"] is False
        finally:
            _mod._repair_svc.get_case = original

    def test_update_repair_state_ok(self):
        _reset_db()
        resp = client.patch(
            f"/api/v1/growth/service-repair-cases/{CASE_ID}/state",
            headers=HEADERS,
            json={"repair_state": "resolved"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_update_compensation_ok(self):
        _reset_db()
        resp = client.patch(
            f"/api/v1/growth/service-repair-cases/{CASE_ID}/compensation",
            headers=HEADERS,
            json={
                "compensation_plan_json": {"options": ["coupon_50", "free_dish"]},
                "compensation_selected": "coupon_50",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ===========================================================================
# Agent Strategy Suggestions 端点
# ===========================================================================


class TestAgentSuggestions:
    _SUGGESTION_PAYLOAD = {
        "customer_id": CUSTOMER_ID,
        "suggestion_type": "reactivation",
        "priority": "high",
        "explanation_summary": "客户60天未消费，建议发放唤醒优惠券",
        "requires_human_review": False,
    }

    def test_list_suggestions_ok(self):
        _reset_db()
        resp = client.get("/api/v1/growth/agent-suggestions", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_list_suggestions_with_filters(self):
        _reset_db()
        resp = client.get(
            "/api/v1/growth/agent-suggestions?suggestion_type=reactivation&review_state=pending",
            headers=HEADERS,
        )
        assert resp.status_code == 200

    def test_create_suggestion_ok(self):
        _reset_db()
        resp = client.post(
            "/api/v1/growth/agent-suggestions",
            headers=HEADERS,
            json=self._SUGGESTION_PAYLOAD,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_get_suggestion_ok(self):
        _reset_db()
        resp = client.get(f"/api/v1/growth/agent-suggestions/{SUGGESTION_ID}", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["id"] == SUGGESTION_ID

    def test_get_suggestion_not_found(self):
        _reset_db()
        from api import growth_hub_routes as _mod

        original = _mod._suggestion_svc.get_suggestion

        async def _none(*a, **kw):
            return None

        _mod._suggestion_svc.get_suggestion = _none
        try:
            resp = client.get(f"/api/v1/growth/agent-suggestions/{SUGGESTION_ID}", headers=HEADERS)
            assert resp.status_code == 200
            assert resp.json()["ok"] is False
        finally:
            _mod._suggestion_svc.get_suggestion = original

    def test_review_suggestion_ok(self):
        _reset_db()
        resp = client.post(
            f"/api/v1/growth/agent-suggestions/{SUGGESTION_ID}/review",
            headers=HEADERS,
            json={
                "review_result": "approved",
                "reviewer_id": str(uuid.uuid4()),
                "reviewer_note": "策略合理，同意执行",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_publish_suggestion_ok(self):
        _reset_db()
        resp = client.post(
            f"/api/v1/growth/agent-suggestions/{SUGGESTION_ID}/publish",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["published"] is True

    def test_bad_tenant_id_returns_400(self):
        """所有端点应拒绝无效 X-Tenant-ID。"""
        resp = client.get(
            "/api/v1/growth/agent-suggestions",
            headers=BAD_TENANT_HEADERS,
        )
        assert resp.status_code == 400


# ===========================================================================
# 辅助：Mock DB 结果构造器
# ===========================================================================


class _MockRow:
    """模拟 SQLAlchemy Row 对象，支持索引访问。"""

    def __init__(self, *values):
        self._values = values

    def __getitem__(self, idx):
        return self._values[idx]

    def __len__(self):
        return len(self._values)


class _MockResult:
    """模拟 SQLAlchemy CursorResult。"""

    def __init__(self, rows=None, scalar_value=None):
        self._rows = rows or []
        self._scalar_value = scalar_value

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    def scalar(self):
        return self._scalar_value


def _setup_dashboard_mocks():
    """为 dashboard-stats 端点设置一系列 db.execute 返回值。"""
    # dashboard-stats 内部按顺序调用 12 次 db.execute
    # 1-profile_stats, 2-enrollment_stats, 3-touch_stats, 4-suggestion_stats,
    # 5-mech_stats, 6-identifiable, 7-first_join, 8-thirty_day, 9-recall, 10-per_customer
    # 加上两次 set_config
    profile_row = _MockRow(100, 30, 20, 15, 5, 3)
    enrollment_row = _MockRow(50, 20, 5, 15, 10)
    touch_row = _MockRow(200, 180, 60, 30, 20, 88000)
    suggestion_row = _MockRow(15, 5, 6, 3, 1)
    mech_rows = [_MockRow("hook", 80, 60, 30, 15, 10, 50000, 20000)]
    id_row = _MockRow(500, 400)
    fj_row = _MockRow(100, 80)
    td_row = _MockRow(200, 50)
    rc_row = _MockRow(30, 18)
    pc_row = _MockRow(50, 100000, 40000)

    call_count = {"n": 0}
    results = [
        _MockResult(),  # set_config
        _MockResult(rows=[profile_row]),  # profile_stats
        _MockResult(rows=[enrollment_row]),  # enrollment_stats
        _MockResult(rows=[touch_row]),  # touch_stats
        _MockResult(rows=[suggestion_row]),  # suggestion_stats
        _MockResult(rows=mech_rows),  # mech_stats
        _MockResult(rows=[id_row]),  # identifiable
        _MockResult(rows=[fj_row]),  # first_join
        _MockResult(rows=[td_row]),  # thirty_day
        _MockResult(rows=[rc_row]),  # recall
        _MockResult(rows=[pc_row]),  # per_customer
    ]

    async def _mock_execute(*a, **kw):
        idx = call_count["n"]
        call_count["n"] += 1
        if idx < len(results):
            return results[idx]
        return _MockResult()

    _MOCK_DB.execute = AsyncMock(side_effect=_mock_execute)


def _setup_empty_db_mocks(num_calls=20):
    """所有 db.execute 返回空结果。"""

    async def _mock_execute(*a, **kw):
        return _MockResult()

    _MOCK_DB.execute = AsyncMock(side_effect=_mock_execute)


def _setup_db_error_mocks():
    """db.execute 第二次调用（set_config 之后）抛异常。"""
    call_count = {"n": 0}

    async def _mock_execute(*a, **kw):
        call_count["n"] += 1
        if call_count["n"] <= 1:
            return _MockResult()  # set_config
        raise RuntimeError("DB connection lost")

    _MOCK_DB.execute = AsyncMock(side_effect=_mock_execute)


BRAND_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())


# ===========================================================================
# Dashboard Stats 端点
# ===========================================================================


class TestDashboardStats:
    def test_dashboard_stats_ok(self):
        _reset_db()
        _setup_dashboard_mocks()
        resp = client.get("/api/v1/growth/dashboard-stats", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        d = body["data"]
        assert "profiles" in d
        assert "enrollments" in d
        assert "touches_7d" in d
        assert "suggestions_7d" in d
        assert "funnel" in d
        assert "conversion_rates" in d
        assert "mechanism_summary" in d
        assert "core_metrics" in d
        assert d["profiles"]["total"] == 100

    def test_dashboard_stats_empty_db(self):
        _reset_db()
        _setup_empty_db_mocks()
        resp = client.get("/api/v1/growth/dashboard-stats", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        # 空数据时也应返回结构（可能 ok=True 带零值 或 ok=False）
        assert "ok" in body

    def test_dashboard_stats_bad_tenant(self):
        resp = client.get("/api/v1/growth/dashboard-stats", headers=BAD_TENANT_HEADERS)
        assert resp.status_code == 400


# ===========================================================================
# Attribution 端点
# ===========================================================================


class TestAttributionByMechanism:
    def test_by_mechanism_ok(self):
        _reset_db()
        rows = [_MockRow("hook", 100, 80, 40, 20, 15, 50000, 20000)]

        call_count = {"n": 0}

        async def _mock_exec(*a, **kw):
            call_count["n"] += 1
            if call_count["n"] <= 1:
                return _MockResult()
            return _MockResult(rows=rows)

        _MOCK_DB.execute = AsyncMock(side_effect=_mock_exec)
        resp = client.get("/api/v1/growth/attribution/by-mechanism?days=7", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "items" in body["data"]
        assert body["data"]["days"] == 7

    def test_by_mechanism_empty(self):
        _reset_db()
        _setup_empty_db_mocks()
        resp = client.get("/api/v1/growth/attribution/by-mechanism", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["items"] == []

    def test_by_mechanism_bad_tenant(self):
        resp = client.get("/api/v1/growth/attribution/by-mechanism", headers=BAD_TENANT_HEADERS)
        assert resp.status_code == 400


class TestAttributionByJourneyTemplate:
    def test_by_journey_template_ok(self):
        _reset_db()
        rows = [_MockRow("首单转二访V2", "first_to_second", "hook", 50, 30, 5, 120, 40, 20, 100000)]

        call_count = {"n": 0}

        async def _mock_exec(*a, **kw):
            call_count["n"] += 1
            if call_count["n"] <= 1:
                return _MockResult()
            return _MockResult(rows=rows)

        _MOCK_DB.execute = AsyncMock(side_effect=_mock_exec)
        resp = client.get("/api/v1/growth/attribution/by-journey-template?days=14", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert len(body["data"]["items"]) == 1
        item = body["data"]["items"][0]
        assert item["template_name"] == "首单转二访V2"
        assert item["journey_type"] == "first_to_second"

    def test_by_journey_template_empty(self):
        _reset_db()
        _setup_empty_db_mocks()
        resp = client.get("/api/v1/growth/attribution/by-journey-template", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["items"] == []

    def test_by_journey_template_bad_tenant(self):
        resp = client.get("/api/v1/growth/attribution/by-journey-template", headers=BAD_TENANT_HEADERS)
        assert resp.status_code == 400


class TestAttributionByStore:
    def test_by_store_ok(self):
        _reset_db()
        store_uuid = uuid.uuid4()
        rows = [_MockRow(store_uuid, 60, 30, 10, 40000)]

        call_count = {"n": 0}

        async def _mock_exec(*a, **kw):
            call_count["n"] += 1
            if call_count["n"] <= 1:
                return _MockResult()
            return _MockResult(rows=rows)

        _MOCK_DB.execute = AsyncMock(side_effect=_mock_exec)
        resp = client.get("/api/v1/growth/attribution/by-store?days=7", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "items" in body["data"]
        assert body["data"]["total"] == 1
        assert body["data"]["days"] == 7

    def test_by_store_empty(self):
        _reset_db()
        _setup_empty_db_mocks()
        resp = client.get("/api/v1/growth/attribution/by-store", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["items"] == []

    def test_by_store_bad_tenant(self):
        resp = client.get("/api/v1/growth/attribution/by-store", headers=BAD_TENANT_HEADERS)
        assert resp.status_code == 400


class TestRepairEffectiveness:
    def test_repair_effectiveness_ok(self):
        _reset_db()
        rows = [_MockRow(20, 12, 3, 2, 3, 48.5, 15.2)]

        call_count = {"n": 0}

        async def _mock_exec(*a, **kw):
            call_count["n"] += 1
            if call_count["n"] <= 1:
                return _MockResult()
            return _MockResult(rows=rows)

        _MOCK_DB.execute = AsyncMock(side_effect=_mock_exec)
        resp = client.get("/api/v1/growth/attribution/repair-effectiveness?days=30", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        d = body["data"]
        assert d["total_cases"] == 20
        assert d["recovered"] == 12
        assert d["recovery_rate"] == 60.0
        assert d["avg_recovery_hours"] == 48.5

    def test_repair_effectiveness_empty(self):
        _reset_db()
        rows = [_MockRow(0, 0, 0, 0, 0, None, None)]

        call_count = {"n": 0}

        async def _mock_exec(*a, **kw):
            call_count["n"] += 1
            if call_count["n"] <= 1:
                return _MockResult()
            return _MockResult(rows=rows)

        _MOCK_DB.execute = AsyncMock(side_effect=_mock_exec)
        resp = client.get("/api/v1/growth/attribution/repair-effectiveness", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total_cases"] == 0
        assert body["data"]["recovery_rate"] == 0

    def test_repair_effectiveness_bad_tenant(self):
        resp = client.get("/api/v1/growth/attribution/repair-effectiveness", headers=BAD_TENANT_HEADERS)
        assert resp.status_code == 400


# ===========================================================================
# Brand Config 端点
# ===========================================================================


class TestBrandConfigs:
    def test_list_brand_configs_ok(self):
        _reset_db()
        _setup_empty_db_mocks(2)
        from api import growth_hub_routes as _mod

        original = _mod._brand_svc.list_brand_configs

        async def _mock_list(*a, **kw):
            return {"items": [{"id": BRAND_ID, "brand_name": "品牌A", "growth_enabled": True}], "total": 1}

        _mod._brand_svc.list_brand_configs = _mock_list
        try:
            resp = client.get("/api/v1/growth/brand-configs", headers=HEADERS)
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["data"]["total"] == 1
        finally:
            _mod._brand_svc.list_brand_configs = original

    def test_list_brand_configs_empty(self):
        _reset_db()
        _setup_empty_db_mocks(2)
        from api import growth_hub_routes as _mod

        original = _mod._brand_svc.list_brand_configs

        async def _mock_list(*a, **kw):
            return {"items": [], "total": 0}

        _mod._brand_svc.list_brand_configs = _mock_list
        try:
            resp = client.get("/api/v1/growth/brand-configs", headers=HEADERS)
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["data"]["items"] == []
        finally:
            _mod._brand_svc.list_brand_configs = original

    def test_list_brand_configs_bad_tenant(self):
        resp = client.get("/api/v1/growth/brand-configs", headers=BAD_TENANT_HEADERS)
        assert resp.status_code == 400

    def test_create_brand_config_ok(self):
        _reset_db()
        _setup_empty_db_mocks(2)
        from api import growth_hub_routes as _mod

        original = _mod._brand_svc.upsert_brand_config

        async def _mock_upsert(*a, **kw):
            return {
                "id": str(uuid.uuid4()),
                "brand_id": str(kw.get("brand_id", BRAND_ID)),
                "brand_name": "品牌A",
                "growth_enabled": True,
                "daily_touch_budget": 100,
            }

        _mod._brand_svc.upsert_brand_config = _mock_upsert
        try:
            resp = client.post(
                f"/api/v1/growth/brand-configs?brand_id={BRAND_ID}",
                headers=HEADERS,
                json={
                    "brand_name": "品牌A",
                    "growth_enabled": True,
                    "daily_touch_budget": 100,
                    "monthly_offer_budget_fen": 1000000,
                },
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["data"]["brand_name"] == "品牌A"
        finally:
            _mod._brand_svc.upsert_brand_config = original

    def test_create_brand_config_bad_tenant(self):
        resp = client.post(
            f"/api/v1/growth/brand-configs?brand_id={BRAND_ID}",
            headers=BAD_TENANT_HEADERS,
            json={"brand_name": "品牌A"},
        )
        assert resp.status_code == 400

    def test_get_brand_config_ok(self):
        _reset_db()
        _setup_empty_db_mocks(2)
        from api import growth_hub_routes as _mod

        original = _mod._brand_svc.get_brand_config

        async def _mock_get(*a, **kw):
            return {
                "id": str(uuid.uuid4()),
                "brand_id": BRAND_ID,
                "brand_name": "品牌A",
                "growth_enabled": True,
                "daily_touch_budget": 100,
            }

        _mod._brand_svc.get_brand_config = _mock_get
        try:
            resp = client.get(f"/api/v1/growth/brand-configs/{BRAND_ID}", headers=HEADERS)
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["data"]["brand_name"] == "品牌A"
        finally:
            _mod._brand_svc.get_brand_config = original

    def test_get_brand_config_not_found(self):
        _reset_db()
        _setup_empty_db_mocks(2)
        from api import growth_hub_routes as _mod

        original = _mod._brand_svc.get_brand_config

        async def _mock_none(*a, **kw):
            return None

        _mod._brand_svc.get_brand_config = _mock_none
        try:
            resp = client.get(f"/api/v1/growth/brand-configs/{BRAND_ID}", headers=HEADERS)
            assert resp.status_code == 404
        finally:
            _mod._brand_svc.get_brand_config = original

    def test_budget_check_ok(self):
        _reset_db()
        _setup_empty_db_mocks(2)
        from api import growth_hub_routes as _mod

        original = _mod._brand_svc.check_brand_budget

        async def _mock_budget(*a, **kw):
            return {
                "daily_budget": 100,
                "daily_used": 35,
                "monthly_budget_fen": 1000000,
                "monthly_used_fen": 250000,
                "can_touch": True,
            }

        _mod._brand_svc.check_brand_budget = _mock_budget
        try:
            resp = client.get(f"/api/v1/growth/brand-configs/{BRAND_ID}/budget-check", headers=HEADERS)
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["data"]["can_touch"] is True
        finally:
            _mod._brand_svc.check_brand_budget = original

    def test_budget_check_bad_tenant(self):
        resp = client.get(
            f"/api/v1/growth/brand-configs/{BRAND_ID}/budget-check",
            headers=BAD_TENANT_HEADERS,
        )
        assert resp.status_code == 400


# ===========================================================================
# Dashboard Stats by Brand 端点
# ===========================================================================


class TestDashboardStatsByBrand:
    def test_by_brand_ok(self):
        _reset_db()
        brand_uuid = uuid.uuid4()
        profiles_row = [_MockRow(brand_uuid, 80, 15, 5)]
        enrollments_row = [_MockRow(brand_uuid, 40, 15, 10)]
        touches_row = [_MockRow(brand_uuid, 100, 30, 10, 50000)]
        suggestions_row = [_MockRow(brand_uuid, 10, 6, 2)]

        call_count = {"n": 0}
        all_results = [
            _MockResult(),  # SET LOCAL
            _MockResult(rows=profiles_row),  # profiles by brand
            _MockResult(rows=enrollments_row),  # enrollments by brand
            _MockResult(rows=touches_row),  # touches by brand
            _MockResult(rows=suggestions_row),  # suggestions by brand
        ]

        async def _mock_exec(*a, **kw):
            idx = call_count["n"]
            call_count["n"] += 1
            if idx < len(all_results):
                return all_results[idx]
            return _MockResult()

        _MOCK_DB.execute = AsyncMock(side_effect=_mock_exec)
        resp = client.get("/api/v1/growth/dashboard-stats/by-brand", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        d = body["data"]
        assert "profiles_by_brand" in d
        assert "enrollments_by_brand" in d
        assert "touches_by_brand" in d
        assert "suggestions_by_brand" in d

    def test_by_brand_empty(self):
        _reset_db()
        _setup_empty_db_mocks()
        resp = client.get("/api/v1/growth/dashboard-stats/by-brand", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True

    def test_by_brand_bad_tenant(self):
        resp = client.get("/api/v1/growth/dashboard-stats/by-brand", headers=BAD_TENANT_HEADERS)
        assert resp.status_code == 400


# ===========================================================================
# Cross-Brand 端点
# ===========================================================================


class TestCrossBrand:
    def test_opportunities_ok(self):
        _reset_db()
        _setup_empty_db_mocks(2)
        from api import growth_hub_routes as _mod

        original = _mod._cross_brand_svc.find_cross_brand_opportunities

        async def _mock_find(*a, **kw):
            return {
                "items": [
                    {
                        "customer_id": CUSTOMER_ID,
                        "brand_count": 3,
                        "opportunity_type": "cross_sell",
                    }
                ],
                "total": 1,
            }

        _mod._cross_brand_svc.find_cross_brand_opportunities = _mock_find
        try:
            resp = client.get("/api/v1/growth/cross-brand/opportunities?min_brands=2", headers=HEADERS)
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["data"]["total"] == 1
        finally:
            _mod._cross_brand_svc.find_cross_brand_opportunities = original

    def test_opportunities_empty(self):
        _reset_db()
        _setup_empty_db_mocks(2)
        from api import growth_hub_routes as _mod

        original = _mod._cross_brand_svc.find_cross_brand_opportunities

        async def _mock_empty(*a, **kw):
            return {"items": [], "total": 0}

        _mod._cross_brand_svc.find_cross_brand_opportunities = _mock_empty
        try:
            resp = client.get("/api/v1/growth/cross-brand/opportunities", headers=HEADERS)
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["data"]["items"] == []
        finally:
            _mod._cross_brand_svc.find_cross_brand_opportunities = original

    def test_opportunities_bad_tenant(self):
        resp = client.get("/api/v1/growth/cross-brand/opportunities", headers=BAD_TENANT_HEADERS)
        assert resp.status_code == 400

    def test_customer_profile_ok(self):
        _reset_db()
        _setup_empty_db_mocks(2)
        from api import growth_hub_routes as _mod

        original = _mod._cross_brand_svc.get_customer_cross_brand_profile

        async def _mock_profile(*a, **kw):
            return {
                "customer_id": CUSTOMER_ID,
                "brands": [
                    {"brand_id": BRAND_ID, "brand_name": "品牌A", "order_count": 5},
                ],
                "total_brands": 1,
                "total_orders": 5,
            }

        _mod._cross_brand_svc.get_customer_cross_brand_profile = _mock_profile
        try:
            resp = client.get(
                f"/api/v1/growth/cross-brand/customers/{CUSTOMER_ID}/profile",
                headers=HEADERS,
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["data"]["customer_id"] == CUSTOMER_ID
        finally:
            _mod._cross_brand_svc.get_customer_cross_brand_profile = original

    def test_customer_profile_bad_tenant(self):
        resp = client.get(
            f"/api/v1/growth/cross-brand/customers/{CUSTOMER_ID}/profile",
            headers=BAD_TENANT_HEADERS,
        )
        assert resp.status_code == 400

    def test_customer_profile_error(self):
        _reset_db()
        _setup_empty_db_mocks(2)
        from api import growth_hub_routes as _mod

        original = _mod._cross_brand_svc.get_customer_cross_brand_profile

        async def _mock_err(*a, **kw):
            raise ValueError("客户不存在")

        _mod._cross_brand_svc.get_customer_cross_brand_profile = _mock_err
        try:
            resp = client.get(
                f"/api/v1/growth/cross-brand/customers/{CUSTOMER_ID}/profile",
                headers=HEADERS,
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is False
        finally:
            _mod._cross_brand_svc.get_customer_cross_brand_profile = original


# ===========================================================================
# Experiment 端点
# ===========================================================================


class TestExperiments:
    def test_experiment_summary_ok(self):
        _reset_db()
        _setup_empty_db_mocks(2)
        from api import growth_hub_routes as _mod

        original = _mod._experiment_svc.get_experiment_summary

        async def _mock_summary(*a, **kw):
            return {
                "template_id": TEMPLATE_ID,
                "variants": [
                    {"variant_code": "A", "sample_count": 100, "conversion_rate": 12.5},
                    {"variant_code": "B", "sample_count": 95, "conversion_rate": 15.2},
                ],
                "total_samples": 195,
                "status": "running",
            }

        _mod._experiment_svc.get_experiment_summary = _mock_summary
        try:
            resp = client.get(f"/api/v1/growth/experiments/{TEMPLATE_ID}/summary", headers=HEADERS)
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["data"]["total_samples"] == 195
            assert len(body["data"]["variants"]) == 2
        finally:
            _mod._experiment_svc.get_experiment_summary = original

    def test_experiment_summary_error(self):
        _reset_db()
        _setup_empty_db_mocks(2)
        from api import growth_hub_routes as _mod

        original = _mod._experiment_svc.get_experiment_summary

        async def _mock_err(*a, **kw):
            raise ValueError("实验不存在")

        _mod._experiment_svc.get_experiment_summary = _mock_err
        try:
            resp = client.get(f"/api/v1/growth/experiments/{TEMPLATE_ID}/summary", headers=HEADERS)
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is False
        finally:
            _mod._experiment_svc.get_experiment_summary = original

    def test_experiment_summary_bad_tenant(self):
        resp = client.get(
            f"/api/v1/growth/experiments/{TEMPLATE_ID}/summary",
            headers=BAD_TENANT_HEADERS,
        )
        assert resp.status_code == 400

    def test_select_variant_ok(self):
        _reset_db()
        _setup_empty_db_mocks(2)
        from api import growth_hub_routes as _mod

        original = _mod._experiment_svc.select_variant

        async def _mock_select(*a, **kw):
            return {
                "selected_variant": "B",
                "probability": 0.68,
                "method": "thompson_sampling",
            }

        _mod._experiment_svc.select_variant = _mock_select
        try:
            resp = client.get(
                f"/api/v1/growth/experiments/{TEMPLATE_ID}/select-variant",
                headers=HEADERS,
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["data"]["selected_variant"] == "B"
        finally:
            _mod._experiment_svc.select_variant = original

    def test_select_variant_error(self):
        _reset_db()
        _setup_empty_db_mocks(2)
        from api import growth_hub_routes as _mod

        original = _mod._experiment_svc.select_variant

        async def _mock_err(*a, **kw):
            raise ValueError("无可用variant")

        _mod._experiment_svc.select_variant = _mock_err
        try:
            resp = client.get(
                f"/api/v1/growth/experiments/{TEMPLATE_ID}/select-variant",
                headers=HEADERS,
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is False
        finally:
            _mod._experiment_svc.select_variant = original

    def test_auto_iterate_ok(self):
        _reset_db()
        _setup_empty_db_mocks(2)
        from api import growth_hub_routes as _mod

        original = _mod._experiment_svc.auto_iterate

        async def _mock_iterate(*a, **kw):
            return {
                "paused_variants": ["A_low"],
                "adjusted_traffic": {"B": 0.7, "C": 0.3},
                "actions_taken": 2,
            }

        _mod._experiment_svc.auto_iterate = _mock_iterate
        try:
            resp = client.post("/api/v1/growth/experiments/auto-iterate", headers=HEADERS)
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["data"]["actions_taken"] == 2
        finally:
            _mod._experiment_svc.auto_iterate = original

    def test_auto_iterate_bad_tenant(self):
        resp = client.post(
            "/api/v1/growth/experiments/auto-iterate",
            headers=BAD_TENANT_HEADERS,
        )
        assert resp.status_code == 400

    def test_adjustments_ok(self):
        _reset_db()
        _setup_empty_db_mocks(2)
        from api import growth_hub_routes as _mod

        original = _mod._experiment_svc.auto_adjust_journey_params

        async def _mock_adjust(*a, **kw):
            return {
                "adjustments": [
                    {
                        "template_id": TEMPLATE_ID,
                        "suggestion": "降低hook机制占比，增加loss_aversion",
                        "confidence": 0.85,
                    }
                ],
                "total": 1,
            }

        _mod._experiment_svc.auto_adjust_journey_params = _mock_adjust
        try:
            resp = client.get("/api/v1/growth/experiments/adjustments", headers=HEADERS)
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["data"]["total"] == 1
        finally:
            _mod._experiment_svc.auto_adjust_journey_params = original

    def test_adjustments_empty(self):
        _reset_db()
        _setup_empty_db_mocks(2)
        from api import growth_hub_routes as _mod

        original = _mod._experiment_svc.auto_adjust_journey_params

        async def _mock_empty(*a, **kw):
            return {"adjustments": [], "total": 0}

        _mod._experiment_svc.auto_adjust_journey_params = _mock_empty
        try:
            resp = client.get("/api/v1/growth/experiments/adjustments", headers=HEADERS)
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["data"]["adjustments"] == []
        finally:
            _mod._experiment_svc.auto_adjust_journey_params = original


# ===========================================================================
# Segment Rules & Offer Packs 端点
# ===========================================================================


class TestSegmentRulesPresets:
    def test_presets_ok(self):
        _reset_db()
        # segment-rules/presets 内部执行: SET LOCAL + 5次查询
        call_count = {"n": 0}
        results = [
            _MockResult(),  # SET LOCAL
            _MockResult(scalar_value=25),  # preset_no_second_visit_7d
            _MockResult(scalar_value=10),  # preset_silent_with_benefit
            _MockResult(scalar_value=8),  # preset_high_priority_reactivation
            _MockResult(scalar_value=15),  # preset_active_repair
            _MockResult(scalar_value=5),  # preset 5
        ]

        async def _mock_exec(*a, **kw):
            idx = call_count["n"]
            call_count["n"] += 1
            if idx < len(results):
                return results[idx]
            return _MockResult(scalar_value=0)

        _MOCK_DB.execute = AsyncMock(side_effect=_mock_exec)
        resp = client.get("/api/v1/growth/segment-rules/presets", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "presets" in body["data"]
        assert len(body["data"]["presets"]) > 0

    def test_presets_bad_tenant(self):
        resp = client.get("/api/v1/growth/segment-rules/presets", headers=BAD_TENANT_HEADERS)
        assert resp.status_code == 400

    def test_presets_empty_counts(self):
        _reset_db()
        _setup_empty_db_mocks(20)
        resp = client.get("/api/v1/growth/segment-rules/presets", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True


class TestTagDistribution:
    def test_tag_distribution_ok(self):
        _reset_db()
        repurchase_rows = [_MockRow("first_order_done", 50), _MockRow("stable_repeat", 30)]
        reactivation_rows = [_MockRow("high", 20), _MockRow("medium", 15)]
        repair_rows = [_MockRow("active", 5)]

        call_count = {"n": 0}
        results = [
            _MockResult(),  # SET LOCAL
            _MockResult(rows=repurchase_rows),  # repurchase_stage
            _MockResult(rows=reactivation_rows),  # reactivation_priority
            _MockResult(rows=repair_rows),  # service_repair_status
        ]

        async def _mock_exec(*a, **kw):
            idx = call_count["n"]
            call_count["n"] += 1
            if idx < len(results):
                return results[idx]
            return _MockResult()

        _MOCK_DB.execute = AsyncMock(side_effect=_mock_exec)
        resp = client.get("/api/v1/growth/segment-rules/tag-distribution", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        d = body["data"]
        assert "repurchase_stage" in d
        assert "reactivation_priority" in d
        assert "service_repair_status" in d
        assert len(d["repurchase_stage"]) == 2

    def test_tag_distribution_empty(self):
        _reset_db()
        _setup_empty_db_mocks()
        resp = client.get("/api/v1/growth/segment-rules/tag-distribution", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True

    def test_tag_distribution_bad_tenant(self):
        resp = client.get("/api/v1/growth/segment-rules/tag-distribution", headers=BAD_TENANT_HEADERS)
        assert resp.status_code == 400


class TestOfferPacks:
    def test_offer_packs_ok(self):
        _reset_db()
        resp = client.get("/api/v1/growth/offer-packs", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "items" in body["data"]
        assert "total" in body["data"]

    def test_offer_packs_with_filter(self):
        _reset_db()
        resp = client.get(
            "/api/v1/growth/offer-packs?pack_type=first_to_second",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True

    def test_offer_packs_bad_tenant(self):
        resp = client.get("/api/v1/growth/offer-packs", headers=BAD_TENANT_HEADERS)
        assert resp.status_code == 400


# ===========================================================================
# P1 Distribution & Recompute 端点
# ===========================================================================


class TestP1Distribution:
    def test_p1_distribution_ok(self):
        _reset_db()
        psych_rows = [_MockRow("close", 40), _MockRow("medium", 30)]
        super_rows = [_MockRow("gold", 20), _MockRow("silver", 35)]
        milestone_rows = [_MockRow("newcomer", 50)]
        referral_rows = [_MockRow("family_dinner", 15)]

        call_count = {"n": 0}
        results = [
            _MockResult(),  # SET LOCAL
            _MockResult(rows=psych_rows),  # psych_distance
            _MockResult(rows=super_rows),  # super_user
            _MockResult(rows=milestone_rows),  # milestones
            _MockResult(rows=referral_rows),  # referral
        ]

        async def _mock_exec(*a, **kw):
            idx = call_count["n"]
            call_count["n"] += 1
            if idx < len(results):
                return results[idx]
            return _MockResult()

        _MOCK_DB.execute = AsyncMock(side_effect=_mock_exec)
        resp = client.get("/api/v1/growth/p1/distribution", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        d = body["data"]
        assert "psych_distance" in d
        assert "super_user" in d
        assert "milestones" in d
        assert "referral" in d
        assert len(d["psych_distance"]) == 2

    def test_p1_distribution_empty(self):
        _reset_db()
        _setup_empty_db_mocks()
        resp = client.get("/api/v1/growth/p1/distribution", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True

    def test_p1_distribution_bad_tenant(self):
        resp = client.get("/api/v1/growth/p1/distribution", headers=BAD_TENANT_HEADERS)
        assert resp.status_code == 400


class TestP1Recompute:
    def test_p1_recompute_ok(self):
        _reset_db()
        _setup_empty_db_mocks(2)
        from api import growth_hub_routes as _mod

        original = _mod._profile_svc.batch_compute_p1_fields

        async def _mock_compute(*a, **kw):
            return {"updated_count": 150, "duration_ms": 3200}

        _mod._profile_svc.batch_compute_p1_fields = _mock_compute
        try:
            resp = client.post("/api/v1/growth/p1/recompute", headers=HEADERS)
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["data"]["updated_count"] == 150
        finally:
            _mod._profile_svc.batch_compute_p1_fields = original

    def test_p1_recompute_error(self):
        _reset_db()
        _setup_empty_db_mocks(2)
        from api import growth_hub_routes as _mod

        original = _mod._profile_svc.batch_compute_p1_fields

        async def _mock_err(*a, **kw):
            raise ValueError("计算失败：数据不足")

        _mod._profile_svc.batch_compute_p1_fields = _mock_err
        try:
            resp = client.post("/api/v1/growth/p1/recompute", headers=HEADERS)
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is False
        finally:
            _mod._profile_svc.batch_compute_p1_fields = original

    def test_p1_recompute_bad_tenant(self):
        resp = client.post("/api/v1/growth/p1/recompute", headers=BAD_TENANT_HEADERS)
        assert resp.status_code == 400


# ===========================================================================
# Signals — 天气 & 日历 端点
# ===========================================================================


class TestWeatherSignal:
    def test_weather_signal_ok(self):
        _reset_db()
        from api import growth_hub_routes as _mod

        original = _mod._weather_svc.get_weather_signal

        async def _mock_weather(*a, **kw):
            return {
                "city": "长沙",
                "date": "2026-04-06",
                "weather": "晴",
                "temperature_high": 28,
                "temperature_low": 18,
                "impact": {"outdoor_dining": "positive", "delivery": "neutral"},
                "recommendations": ["适合推广户外就餐活动"],
            }

        _mod._weather_svc.get_weather_signal = _mock_weather
        try:
            resp = client.get("/api/v1/growth/signals/weather?city=长沙", headers=HEADERS)
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["data"]["city"] == "长沙"
            assert "recommendations" in body["data"]
        finally:
            _mod._weather_svc.get_weather_signal = original

    def test_weather_signal_error(self):
        _reset_db()
        from api import growth_hub_routes as _mod

        original = _mod._weather_svc.get_weather_signal

        async def _mock_err(*a, **kw):
            raise ValueError("城市不在服务范围内")

        _mod._weather_svc.get_weather_signal = _mock_err
        try:
            resp = client.get("/api/v1/growth/signals/weather?city=未知城市", headers=HEADERS)
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is False
        finally:
            _mod._weather_svc.get_weather_signal = original

    def test_weather_signal_bad_tenant(self):
        resp = client.get("/api/v1/growth/signals/weather?city=长沙", headers=BAD_TENANT_HEADERS)
        assert resp.status_code == 400


class TestCalendarTriggers:
    def test_calendar_triggers_ok(self):
        _reset_db()
        from api import growth_hub_routes as _mod

        original = _mod._calendar_svc.get_growth_triggers

        def _mock_triggers():
            return [
                {
                    "event_name": "端午节",
                    "trigger_type": "festival",
                    "days_until": 3,
                    "recommended_actions": ["推送粽子礼盒套餐", "启动节日储值活动"],
                }
            ]

        _mod._calendar_svc.get_growth_triggers = _mock_triggers
        try:
            resp = client.get("/api/v1/growth/signals/calendar/triggers", headers=HEADERS)
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert len(body["data"]) == 1
            assert body["data"][0]["event_name"] == "端午节"
        finally:
            _mod._calendar_svc.get_growth_triggers = original

    def test_calendar_triggers_empty(self):
        _reset_db()
        from api import growth_hub_routes as _mod

        original = _mod._calendar_svc.get_growth_triggers

        def _mock_empty():
            return []

        _mod._calendar_svc.get_growth_triggers = _mock_empty
        try:
            resp = client.get("/api/v1/growth/signals/calendar/triggers", headers=HEADERS)
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["data"] == []
        finally:
            _mod._calendar_svc.get_growth_triggers = original

    def test_calendar_triggers_bad_tenant(self):
        resp = client.get("/api/v1/growth/signals/calendar/triggers", headers=BAD_TENANT_HEADERS)
        assert resp.status_code == 400


# ===========================================================================
# Stores — 就绪度排行 端点
# ===========================================================================


class TestStoresReadinessRanking:
    def test_readiness_ranking_ok(self):
        _reset_db()
        _setup_empty_db_mocks(2)
        from api import growth_hub_routes as _mod

        original = _mod._store_cap_svc.get_all_stores_readiness

        async def _mock_ranking(*a, **kw):
            return {
                "stores": [
                    {"store_id": STORE_ID, "store_name": "长沙万达店", "readiness_score": 92, "rank": 1},
                    {"store_id": str(uuid.uuid4()), "store_name": "长沙IFS店", "readiness_score": 85, "rank": 2},
                ],
                "total": 2,
            }

        _mod._store_cap_svc.get_all_stores_readiness = _mock_ranking
        try:
            resp = client.get("/api/v1/growth/stores/readiness-ranking", headers=HEADERS)
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["data"]["total"] == 2
            assert body["data"]["stores"][0]["rank"] == 1
        finally:
            _mod._store_cap_svc.get_all_stores_readiness = original

    def test_readiness_ranking_empty(self):
        _reset_db()
        _setup_empty_db_mocks(2)
        from api import growth_hub_routes as _mod

        original = _mod._store_cap_svc.get_all_stores_readiness

        async def _mock_empty(*a, **kw):
            return {"stores": [], "total": 0}

        _mod._store_cap_svc.get_all_stores_readiness = _mock_empty
        try:
            resp = client.get("/api/v1/growth/stores/readiness-ranking", headers=HEADERS)
            assert resp.status_code == 200
            body = resp.json()
            assert body["ok"] is True
            assert body["data"]["stores"] == []
        finally:
            _mod._store_cap_svc.get_all_stores_readiness = original

    def test_readiness_ranking_bad_tenant(self):
        resp = client.get("/api/v1/growth/stores/readiness-ranking", headers=BAD_TENANT_HEADERS)
        assert resp.status_code == 400
