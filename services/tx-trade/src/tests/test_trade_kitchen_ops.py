"""厨房运营路由测试 — 覆盖 allergen + dispatch_rule + course_firing + cook_time

使用 TestClient + dependency_overrides[get_db] 方式 mock AsyncSession，
避免真实数据库依赖。
测试以 `src` 为包根（services/tx-trade 作为工作目录）运行。
"""
import sys
import uuid
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ─── 全局 sys.modules stub（必须在导入路由前完成） ───

_db_module = MagicMock()
sys.modules.setdefault("shared", MagicMock())
sys.modules.setdefault("shared.ontology", MagicMock())
sys.modules.setdefault("shared.ontology.src", MagicMock())
sys.modules.setdefault("shared.ontology.src.database", _db_module)
_db_module.get_db = MagicMock()

sys.modules.setdefault("structlog", MagicMock())

# allergen_service stub
_allergen_svc_stub = MagicMock()
sys.modules["src.services.allergen_service"] = _allergen_svc_stub

# dispatch_rule_engine stub
_dispatch_engine_stub = MagicMock()
_dispatch_engine_stub.dispatch_rule_engine = MagicMock()
_dispatch_engine_stub.invalidate_store_cache = MagicMock()
sys.modules["src.services.dispatch_rule_engine"] = _dispatch_engine_stub

# dispatch_rule ORM model stub
_dispatch_rule_model_stub = MagicMock()
sys.modules["src.models.dispatch_rule"] = _dispatch_rule_model_stub
sys.modules["src.models"] = MagicMock()

# production_dept ORM model stub
_prod_dept_model_stub = MagicMock()
sys.modules["src.models.production_dept"] = _prod_dept_model_stub

# course_firing_service stub
_course_firing_svc_stub = MagicMock()
sys.modules["src.services.course_firing_service"] = _course_firing_svc_stub

# cook_time_stats stub
_cook_time_svc_stub = MagicMock()
sys.modules["src.services.cook_time_stats"] = _cook_time_svc_stub

# src.db stub (course_firing_routes 用 from ..db import get_db)
_src_db_stub = MagicMock()
_src_db_stub.get_db = MagicMock()
sys.modules["src.db"] = _src_db_stub


TENANT_ID = str(uuid.uuid4())
ORDER_ID = str(uuid.uuid4())
ITEM_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
DISH_ID = str(uuid.uuid4())
DEPT_ID = str(uuid.uuid4())
RULE_ID = str(uuid.uuid4())


def _async_db_override(db: AsyncMock):
    async def _override():
        yield db
    return _override


# ═══════════════════════════════════════════════════════════════
# 1. allergen_routes — 过敏原管理
# ═══════════════════════════════════════════════════════════════


class TestAllergenRoutes:
    """过敏原 API 测试 (allergen_routes.py)"""

    def _build_app(self, svc_mock=None) -> tuple[TestClient, MagicMock]:
        if svc_mock is None:
            svc_mock = MagicMock()
            svc_mock.check_dishes_for_member = AsyncMock(return_value=[])
            svc_mock.set_dish_allergens = AsyncMock(
                return_value={"dish_id": DISH_ID, "allergen_codes": ["gluten"], "total": 1}
            )
            svc_mock.get_dish_allergens = AsyncMock(
                return_value=[{"allergen_code": "gluten", "allergen_label": "麸质", "severity": "high"}]
            )

        _allergen_svc_stub.AllergenService = MagicMock(return_value=svc_mock)
        _allergen_svc_stub.AllergenService.get_allergen_summary = MagicMock(
            return_value={"gluten": "麸质", "dairy": "乳制品", "nuts": "坚果"}
        )

        import src.api.allergen_routes as mod
        from shared.ontology.src.database import get_db

        db = AsyncMock()
        app = FastAPI()
        app.include_router(mod.router)
        app.dependency_overrides[get_db] = _async_db_override(db)
        return TestClient(app, raise_server_exceptions=False), svc_mock

    def test_get_allergen_codes_success(self):
        """GET /api/v1/allergens/codes 返回所有过敏原代码"""
        client, _ = self._build_app()
        resp = client.get(
            "/api/v1/allergens/codes",
            headers={"X-Tenant-ID": TENANT_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert isinstance(data["data"], dict)

    def test_get_allergen_codes_missing_tenant(self):
        """缺少 X-Tenant-ID 返回 400"""
        client, _ = self._build_app()
        resp = client.get("/api/v1/allergens/codes")
        assert resp.status_code == 400

    def test_check_allergens_empty_dish_ids(self):
        """dish_ids 为空时直接返回空列表，不调用 service"""
        client, svc = self._build_app()
        resp = client.post(
            "/api/v1/allergens/check",
            json={"dish_ids": [], "member_id": "mem_001"},
            headers={"X-Tenant-ID": TENANT_ID},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["data"] == []
        svc.check_dishes_for_member.assert_not_called()

    def test_check_allergens_with_dishes(self):
        """有菜品时返回过敏预警"""
        client, svc = self._build_app()
        svc.check_dishes_for_member = AsyncMock(
            return_value=[
                {
                    "dish_id": DISH_ID,
                    "dish_name": "麻辣小龙虾",
                    "alerts": [
                        {"allergen_code": "shellfish", "allergen_label": "甲壳类", "severity": "critical"}
                    ],
                }
            ]
        )
        resp = client.post(
            "/api/v1/allergens/check",
            json={"dish_ids": [DISH_ID], "member_id": "mem_001"},
            headers={"X-Tenant-ID": TENANT_ID},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_set_dish_allergens_success(self):
        """POST /api/v1/dishes/{dish_id}/allergens 设置过敏原成功"""
        client, _ = self._build_app()
        resp = client.post(
            f"/api/v1/dishes/{DISH_ID}/allergens",
            json={"allergen_codes": ["gluten", "dairy"]},
            headers={"X-Tenant-ID": TENANT_ID},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_set_dish_allergens_value_error(self):
        """无效过敏原代码时返回 400"""
        with patch("src.api.allergen_routes.AllergenService") as mock_cls:
            svc = MagicMock()
            svc.set_dish_allergens = AsyncMock(side_effect=ValueError("无效的过敏原代码"))
            mock_cls.return_value = svc

            import src.api.allergen_routes as mod
            from shared.ontology.src.database import get_db

            db = AsyncMock()
            app = FastAPI()
            app.include_router(mod.router)
            app.dependency_overrides[get_db] = _async_db_override(db)
            client = TestClient(app, raise_server_exceptions=False)

            resp = client.post(
                f"/api/v1/dishes/{DISH_ID}/allergens",
                json={"allergen_codes": ["unknown_code"]},
                headers={"X-Tenant-ID": TENANT_ID},
            )
        assert resp.status_code == 400

    def test_get_dish_allergens_success(self):
        """GET /api/v1/dishes/{dish_id}/allergens 返回过敏原列表"""
        client, _ = self._build_app()
        resp = client.get(
            f"/api/v1/dishes/{DISH_ID}/allergens",
            headers={"X-Tenant-ID": TENANT_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["dish_id"] == DISH_ID
        assert "items" in data["data"]
        assert data["data"]["total"] == 1


# ═══════════════════════════════════════════════════════════════
# 2. dispatch_rule_routes — 档口路由规则
# ═══════════════════════════════════════════════════════════════


class TestDispatchRuleRoutes:
    """档口路由规则 API 测试 (dispatch_rule_routes.py)"""

    def _build_app(self) -> TestClient:
        import src.api.dispatch_rule_routes as mod
        from shared.ontology.src.database import get_db

        db = AsyncMock()
        app = FastAPI()
        app.include_router(mod.router)
        app.dependency_overrides[get_db] = _async_db_override(db)
        return TestClient(app, raise_server_exceptions=False)

    def test_list_rules_missing_tenant(self):
        """GET /{store_id} 缺少 tenant 返回 400"""
        client = self._build_app()
        resp = client.get(f"/api/v1/dispatch-rules/{STORE_ID}")
        assert resp.status_code == 400

    def test_create_rule_missing_tenant(self):
        """POST /{store_id} 缺少 tenant 返回 400"""
        client = self._build_app()
        resp = client.post(
            f"/api/v1/dispatch-rules/{STORE_ID}",
            json={"name": "新规则", "target_dept_id": DEPT_ID},
        )
        assert resp.status_code == 400

    def test_create_rule_invalid_time_format(self):
        """时间格式错误时返回 400"""
        client = self._build_app()
        resp = client.post(
            f"/api/v1/dispatch-rules/{STORE_ID}",
            json={
                "name": "时段规则",
                "target_dept_id": DEPT_ID,
                "match_time_start": "25:99",  # 无效时间
            },
            headers={"X-Tenant-ID": TENANT_ID},
        )
        assert resp.status_code in (400, 422)

    def test_update_rule_missing_tenant(self):
        """PUT /{rule_id} 缺少 tenant 返回 400"""
        client = self._build_app()
        resp = client.put(
            f"/api/v1/dispatch-rules/{RULE_ID}",
            json={"name": "更新名称"},
        )
        assert resp.status_code == 400

    def test_delete_rule_missing_tenant(self):
        """DELETE /{rule_id} 缺少 tenant 返回 400"""
        client = self._build_app()
        resp = client.delete(f"/api/v1/dispatch-rules/{RULE_ID}")
        assert resp.status_code == 400

    def test_simulate_routing_missing_dish_id(self):
        """GET /{store_id}/simulate 缺少 dish_id 返回 400"""
        client = self._build_app()
        resp = client.get(
            f"/api/v1/dispatch-rules/{STORE_ID}/simulate",
            headers={"X-Tenant-ID": TENANT_ID},
            params={"channel": "dine_in"},
        )
        assert resp.status_code == 400
        assert "dish_id" in resp.json()["detail"]


# ═══════════════════════════════════════════════════════════════
# 3. course_firing_routes — 打菜时机控制
# ═══════════════════════════════════════════════════════════════


def _make_course_mock(name: str = "course_1", status: str = "holding") -> MagicMock:
    cs = MagicMock()
    cs.course_name = name
    cs.course_label = f"第{name[-1]}道"
    cs.sort_order = 1
    cs.status = status
    cs.dish_count = 3
    cs.fired_count = 0
    cs.done_count = 0
    cs.fired_at = None
    cs.fired_by = None
    return cs


class TestCourseFiringRoutes:
    """打菜时机 API 测试 (course_firing_routes.py)"""

    def _build_app(self) -> TestClient:
        import src.api.course_firing_routes as mod
        from src.db import get_db

        db = AsyncMock()
        app = FastAPI()
        app.include_router(mod.router)
        app.dependency_overrides[get_db] = _async_db_override(db)
        return TestClient(app, raise_server_exceptions=False)

    def test_fire_course_success(self):
        """POST /{order_id}/courses/{course_name}/fire 开火成功"""
        course = _make_course_mock("course_1", "fired")
        course.fired_at = datetime.now(timezone.utc)

        with patch(
            "src.api.course_firing_routes.fire_course",
            new=AsyncMock(return_value=course),
        ):
            client = self._build_app()
            resp = client.post(
                f"/api/v1/orders/{ORDER_ID}/courses/course_1/fire",
                json={"operator_id": "op_001"},
                headers={"X-Tenant-ID": TENANT_ID},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["course_name"] == "course_1"
        assert data["data"]["status"] == "fired"

    def test_fire_course_not_found(self):
        """课程不存在时返回 404"""
        with patch(
            "src.api.course_firing_routes.fire_course",
            new=AsyncMock(side_effect=LookupError("课程不存在")),
        ):
            client = self._build_app()
            resp = client.post(
                f"/api/v1/orders/{ORDER_ID}/courses/no_such/fire",
                json={"operator_id": "op_001"},
                headers={"X-Tenant-ID": TENANT_ID},
            )
        assert resp.status_code == 404

    def test_fire_course_already_fired(self):
        """已开火的课程再次开火时返回 400"""
        with patch(
            "src.api.course_firing_routes.fire_course",
            new=AsyncMock(side_effect=ValueError("课程已开火")),
        ):
            client = self._build_app()
            resp = client.post(
                f"/api/v1/orders/{ORDER_ID}/courses/course_1/fire",
                json={"operator_id": "op_001"},
                headers={"X-Tenant-ID": TENANT_ID},
            )
        assert resp.status_code == 400

    def test_get_courses_status_success(self):
        """GET /{order_id}/courses 返回所有课程状态"""
        courses = [_make_course_mock("course_1"), _make_course_mock("course_2")]
        with patch(
            "src.api.course_firing_routes.get_courses_status",
            new=AsyncMock(return_value=courses),
        ):
            client = self._build_app()
            resp = client.get(
                f"/api/v1/orders/{ORDER_ID}/courses",
                headers={"X-Tenant-ID": TENANT_ID},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["total"] == 2
        assert len(data["data"]["items"]) == 2

    def test_assign_course_success(self):
        """PATCH /{order_id}/items/{item_id}/course 分配课程成功"""
        with patch(
            "src.api.course_firing_routes.assign_course",
            new=AsyncMock(return_value=None),
        ):
            client = self._build_app()
            resp = client.patch(
                f"/api/v1/orders/{ORDER_ID}/items/{ITEM_ID}/course",
                json={"course_name": "course_2"},
                headers={"X-Tenant-ID": TENANT_ID},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["course_name"] == "course_2"

    def test_get_fire_suggestion_success(self):
        """GET /{order_id}/courses/suggestion 返回开火建议"""
        suggestion = {"should_fire": True, "course_name": "course_1", "reason": "主菜已出完"}
        with patch(
            "src.api.course_firing_routes.check_fire_suggestion",
            new=AsyncMock(return_value=suggestion),
        ):
            client = self._build_app()
            resp = client.get(
                f"/api/v1/orders/{ORDER_ID}/courses/suggestion",
                headers={"X-Tenant-ID": TENANT_ID},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["suggestion"]["should_fire"] is True


# ═══════════════════════════════════════════════════════════════
# 4. cook_time_routes — 制作时间基准
# ═══════════════════════════════════════════════════════════════


class TestCookTimeRoutes:
    """制作时间 API 测试 (cook_time_routes.py)"""

    def _build_app(self, svc_mock=None) -> tuple[TestClient, MagicMock]:
        if svc_mock is None:
            svc_mock = MagicMock()
            svc_mock.get_expected_duration_with_meta = AsyncMock(
                return_value={
                    "estimated_seconds": 480,
                    "source": "baseline",
                    "reliable": True,
                    "p50_seconds": 480,
                    "p90_seconds": 720,
                    "sample_count": 30,
                }
            )
            _now = datetime.now(timezone.utc)
            svc_mock.estimate_queue_clear_time = AsyncMock(
                return_value={
                    "estimated_clear_at": _now,
                    "pending_count": 4,
                    "total_expected_seconds": 1440,
                    "concurrent_capacity": 2,
                }
            )
            svc_mock.get_dept_baselines = AsyncMock(return_value=[])
            svc_mock.get_dept_timeout_thresholds = AsyncMock(
                return_value={
                    "warn_seconds": 576,
                    "critical_seconds": 720,
                    "source": "baseline",
                }
            )

        _cook_time_svc_stub.CookTimeStatsService = MagicMock(return_value=svc_mock)

        import src.api.cook_time_routes as mod
        from shared.ontology.src.database import get_db

        db = AsyncMock()
        app = FastAPI()
        app.include_router(mod.router)
        app.dependency_overrides[get_db] = _async_db_override(db)
        return TestClient(app, raise_server_exceptions=False), svc_mock

    def test_get_expected_duration_success(self):
        """GET /expected/{dish_id}?dept_id=... 返回预期制作时间"""
        client, _ = self._build_app()
        resp = client.get(
            f"/api/v1/cook-time/expected/{DISH_ID}",
            params={"dept_id": DEPT_ID},
            headers={"X-Tenant-ID": TENANT_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["estimated_seconds"] == 480
        assert data["data"]["dish_id"] == DISH_ID
        assert data["data"]["dept_id"] == DEPT_ID

    def test_get_expected_duration_missing_dept_id(self):
        """缺少 dept_id 时返回 400"""
        client, _ = self._build_app()
        resp = client.get(
            f"/api/v1/cook-time/expected/{DISH_ID}",
            headers={"X-Tenant-ID": TENANT_ID},
        )
        assert resp.status_code == 400
        assert "dept_id" in resp.json()["detail"]

    def test_get_expected_duration_missing_tenant(self):
        """缺少 X-Tenant-ID 返回 400"""
        client, _ = self._build_app()
        resp = client.get(
            f"/api/v1/cook-time/expected/{DISH_ID}",
            params={"dept_id": DEPT_ID},
        )
        assert resp.status_code == 400

    def test_estimate_queue_clear_time_success(self):
        """GET /queue-estimate/{dept_id} 返回队列预估"""
        client, _ = self._build_app()
        resp = client.get(
            f"/api/v1/cook-time/queue-estimate/{DEPT_ID}",
            params={"concurrent_capacity": 2},
            headers={"X-Tenant-ID": TENANT_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "estimated_wait_minutes" in data["data"]
        assert data["data"]["concurrent_capacity"] == 2
        assert data["data"]["pending_count"] == 4

    def test_trigger_recompute_returns_accepted(self):
        """POST /recompute/{dept_id} 立即返回 accepted"""
        client, _ = self._build_app()
        resp = client.post(
            f"/api/v1/cook-time/recompute/{DEPT_ID}",
            headers={"X-Tenant-ID": TENANT_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["status"] == "accepted"
        assert data["data"]["dept_id"] == DEPT_ID

    def test_get_dept_baselines_success(self):
        """GET /baselines/{dept_id} 返回基准数据"""
        client, _ = self._build_app()
        resp = client.get(
            f"/api/v1/cook-time/baselines/{DEPT_ID}",
            headers={"X-Tenant-ID": TENANT_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["dept_id"] == DEPT_ID
        assert "baselines" in data["data"]

    def test_get_timeout_thresholds_success(self):
        """GET /thresholds/{dept_id}?dish_id=... 返回动态超时阈值"""
        client, _ = self._build_app()
        resp = client.get(
            f"/api/v1/cook-time/thresholds/{DEPT_ID}",
            params={"dish_id": DISH_ID},
            headers={"X-Tenant-ID": TENANT_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["warn_seconds"] == 576
        assert data["data"]["critical_seconds"] == 720
        assert data["data"]["source"] == "baseline"
        assert data["data"]["dept_id"] == DEPT_ID
        assert data["data"]["dish_id"] == DISH_ID

    def test_get_timeout_thresholds_missing_tenant(self):
        """缺少 X-Tenant-ID 时返回 400"""
        client, _ = self._build_app()
        resp = client.get(
            f"/api/v1/cook-time/thresholds/{DEPT_ID}",
            params={"dish_id": DISH_ID},
        )
        assert resp.status_code == 400
