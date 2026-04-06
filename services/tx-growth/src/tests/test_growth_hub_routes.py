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
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
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
            resp = client.get(
                f"/api/v1/growth/customers/{CUSTOMER_ID}/profile", headers=HEADERS
            )
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
        resp = client.get(
            f"/api/v1/growth/journey-templates/{TEMPLATE_ID}", headers=HEADERS
        )
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
            resp = client.get(
                f"/api/v1/growth/journey-templates/{TEMPLATE_ID}", headers=HEADERS
            )
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
        resp = client.get(
            f"/api/v1/growth/journey-enrollments/{ENROLLMENT_ID}", headers=HEADERS
        )
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
            resp = client.get(
                f"/api/v1/growth/journey-enrollments/{ENROLLMENT_ID}", headers=HEADERS
            )
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
        resp = client.get(
            f"/api/v1/growth/service-repair-cases/{CASE_ID}", headers=HEADERS
        )
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
            resp = client.get(
                f"/api/v1/growth/service-repair-cases/{CASE_ID}", headers=HEADERS
            )
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
        resp = client.get(
            f"/api/v1/growth/agent-suggestions/{SUGGESTION_ID}", headers=HEADERS
        )
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
            resp = client.get(
                f"/api/v1/growth/agent-suggestions/{SUGGESTION_ID}", headers=HEADERS
            )
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
