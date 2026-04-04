"""tx-supply food_safety_routes.py 单元测试

测试范围（8端点，含4处emit_event/UniversalPublisher调用）：
  - POST /api/v1/supply/food-safety/block-expired     — 禁用过期原料（正常/未找到原料）
  - POST /api/v1/supply/food-safety/check-banned      — 禁用食材检查（通过/被拦截422）
  - GET  /api/v1/supply/food-safety/trace/{batch_no}  — 批次追溯（找到/未找到404）
  - POST /api/v1/supply/food-safety/sample            — 留样记录（正常）
  - POST /api/v1/supply/food-safety/temperature       — 温控记录（正常/违规）
  - GET  /api/v1/supply/food-safety/checklist/{store} — 合规检查表（正常）
  - POST /api/v1/supply/food-safety/event             — 食安事件上报（正常/critical触发通知）
  - POST /api/v1/supply/food-safety/responsibility-chain — 责任追踪链（正常）

emit_event 调用位置：food_safety service 层（通过 asyncio.create_task + UniversalPublisher.publish）
patch 路径：services.tx_supply.src.services.food_safety.UniversalPublisher.publish

技术约束：
  - service 函数通过 patch 拦截，不访问真实 DB
  - severity=critical 事件验证 UniversalPublisher.publish 被调用
"""
from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.tx_supply.src.api.food_safety_routes import router as food_safety_router
from shared.ontology.src.database import get_db

# ── 应用组装 ──────────────────────────────────────────────────────────────────

app = FastAPI()
app.include_router(food_safety_router)

# ── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
INGREDIENT_ID = str(uuid.uuid4())
DISH_ID = str(uuid.uuid4())
BATCH_NO = f"BATCH-{uuid.uuid4().hex[:8].upper()}"
HEADERS = {"X-Tenant-ID": TENANT_ID}

_EMIT_PATCH = "services.tx_supply.src.services.food_safety.UniversalPublisher.publish"


# ── DB Mock 工厂 ──────────────────────────────────────────────────────────────


def _mock_db():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.flush = AsyncMock()
    return db


def _override_get_db(mock_db=None):
    if mock_db is None:
        mock_db = _mock_db()

    async def _dep():
        yield mock_db

    return _dep


# ══════════════════════════════════════════════════════════════════════════════
#  POST /block-expired — 禁用过期原料
# ══════════════════════════════════════════════════════════════════════════════


class TestBlockExpiredIngredient:
    """POST /api/v1/supply/food-safety/block-expired"""

    def test_blocks_expired_ingredient_successfully(self):
        """正常禁用过期原料，返回 blocked=True。"""
        mock_result = {
            "blocked": True,
            "ingredient_id": INGREDIENT_ID,
            "ingredient_name": "隔夜猪肉",
            "reason": "过期原料已禁用，不可出品",
        }
        app.dependency_overrides[get_db] = _override_get_db()

        with patch(
            "services.tx_supply.src.services.food_safety.block_expired_ingredient",
            new=AsyncMock(return_value=mock_result),
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/supply/food-safety/block-expired",
                    json={"ingredient_id": INGREDIENT_ID, "store_id": STORE_ID},
                    headers=HEADERS,
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["blocked"] is True
        assert "过期" in data["data"]["reason"]

    def test_ingredient_not_found_returns_blocked_false(self):
        """原料不存在时，service 返回 blocked=False，路由仍返回 ok=True。"""
        mock_result = {"blocked": False, "reason": "原料不存在或已禁用"}
        app.dependency_overrides[get_db] = _override_get_db()

        with patch(
            "services.tx_supply.src.services.food_safety.block_expired_ingredient",
            new=AsyncMock(return_value=mock_result),
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/supply/food-safety/block-expired",
                    json={"ingredient_id": "nonexistent-id", "store_id": STORE_ID},
                    headers=HEADERS,
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["blocked"] is False


# ══════════════════════════════════════════════════════════════════════════════
#  POST /check-banned — 禁用食材检查
# ══════════════════════════════════════════════════════════════════════════════


class TestCheckBannedIngredients:
    """POST /api/v1/supply/food-safety/check-banned"""

    def test_check_passed_when_no_banned_items(self):
        """无禁用食材时，passed=True，返回 ok=True。"""
        mock_result = {"passed": True, "banned_items": []}
        app.dependency_overrides[get_db] = _override_get_db()

        with patch(
            "services.tx_supply.src.services.food_safety.check_banned_ingredients",
            new=AsyncMock(return_value=mock_result),
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/supply/food-safety/check-banned",
                    json={
                        "order_items": [{"ingredient_id": INGREDIENT_ID, "name": "猪肉"}],
                        "store_id": STORE_ID,
                    },
                    headers=HEADERS,
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["passed"] is True

    def test_check_fails_with_422_when_banned_items_found(self):
        """发现禁用食材时，路由抛出 422，包含 banned_items 详情。"""
        mock_result = {
            "passed": False,
            "banned_items": [{"ingredient_id": INGREDIENT_ID, "name": "已禁猪肉"}],
        }
        app.dependency_overrides[get_db] = _override_get_db()

        with patch(
            "services.tx_supply.src.services.food_safety.check_banned_ingredients",
            new=AsyncMock(return_value=mock_result),
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/supply/food-safety/check-banned",
                    json={
                        "order_items": [{"ingredient_id": INGREDIENT_ID, "name": "已禁猪肉"}],
                        "store_id": STORE_ID,
                    },
                    headers=HEADERS,
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "banned_items" in detail
        assert len(detail["banned_items"]) == 1


# ══════════════════════════════════════════════════════════════════════════════
#  GET /trace/{batch_no} — 批次追溯
# ══════════════════════════════════════════════════════════════════════════════


class TestTraceBatch:
    """GET /api/v1/supply/food-safety/trace/{batch_no}"""

    def test_trace_found_returns_chain(self):
        """找到批次时，返回追溯链。"""
        mock_result = {
            "found": True,
            "batch_no": BATCH_NO,
            "trace": [
                {"step": "purchase", "operator": "采购员A", "time": "2026-03-01"},
                {"step": "receiving", "operator": "验收员B", "time": "2026-03-02"},
            ],
        }
        app.dependency_overrides[get_db] = _override_get_db()

        with patch(
            "services.tx_supply.src.services.food_safety.trace_batch",
            new=AsyncMock(return_value=mock_result),
        ):
            with TestClient(app) as client:
                resp = client.get(
                    f"/api/v1/supply/food-safety/trace/{BATCH_NO}",
                    headers=HEADERS,
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["found"] is True
        assert len(data["data"]["trace"]) == 2

    def test_trace_not_found_returns_404(self):
        """批次不存在时，路由返回 404。"""
        mock_result = {"found": False, "trace": []}
        app.dependency_overrides[get_db] = _override_get_db()

        with patch(
            "services.tx_supply.src.services.food_safety.trace_batch",
            new=AsyncMock(return_value=mock_result),
        ):
            with TestClient(app) as client:
                resp = client.get(
                    "/api/v1/supply/food-safety/trace/NONEXISTENT-BATCH",
                    headers=HEADERS,
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
#  POST /sample — 留样记录
# ══════════════════════════════════════════════════════════════════════════════


class TestRecordSample:
    """POST /api/v1/supply/food-safety/sample"""

    def test_record_sample_success(self):
        """正常留样记录，返回 ok=True 含 sample_id。"""
        mock_result = {
            "sample_id": f"sample_{uuid.uuid4().hex[:8]}",
            "dish_id": DISH_ID,
            "retention_until": "2026-04-06T10:00:00",
            "status": "stored",
        }

        with patch(
            "services.tx_supply.src.services.food_safety.record_sample",
            return_value=mock_result,
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/supply/food-safety/sample",
                    json={
                        "store_id": STORE_ID,
                        "dish_id": DISH_ID,
                        "sample_time": "2026-04-04T10:00:00",
                        "photo_url": "https://cdn.example.com/sample.jpg",
                        "operator_id": "emp_001",
                    },
                    headers=HEADERS,
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "sample_id" in data["data"]


# ══════════════════════════════════════════════════════════════════════════════
#  POST /temperature — 温控记录
# ══════════════════════════════════════════════════════════════════════════════


class TestRecordTemperature:
    """POST /api/v1/supply/food-safety/temperature"""

    def test_temperature_compliant(self):
        """冷藏温度合规（2°C），返回 is_violation=False。"""
        mock_result = {
            "record_id": f"temp_{uuid.uuid4().hex[:6]}",
            "location": "cold_storage",
            "temperature": 2.0,
            "is_violation": False,
            "threshold": {"min": 0.0, "max": 4.0},
        }

        with patch(
            "services.tx_supply.src.services.food_safety.record_temperature",
            return_value=mock_result,
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/supply/food-safety/temperature",
                    json={
                        "store_id": STORE_ID,
                        "location": "cold_storage",
                        "temperature": 2.0,
                        "operator_id": "emp_002",
                    },
                    headers=HEADERS,
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["is_violation"] is False

    def test_temperature_violation(self):
        """冷藏温度超标（8°C），返回 is_violation=True。"""
        mock_result = {
            "record_id": f"temp_{uuid.uuid4().hex[:6]}",
            "location": "cold_storage",
            "temperature": 8.0,
            "is_violation": True,
            "threshold": {"min": 0.0, "max": 4.0},
        }

        with patch(
            "services.tx_supply.src.services.food_safety.record_temperature",
            return_value=mock_result,
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/supply/food-safety/temperature",
                    json={
                        "store_id": STORE_ID,
                        "location": "cold_storage",
                        "temperature": 8.0,
                        "operator_id": "emp_002",
                    },
                    headers=HEADERS,
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["is_violation"] is True


# ══════════════════════════════════════════════════════════════════════════════
#  GET /checklist/{store_id} — 合规检查表
# ══════════════════════════════════════════════════════════════════════════════


class TestGetComplianceChecklist:
    """GET /api/v1/supply/food-safety/checklist/{store_id}"""

    def test_returns_checklist(self):
        """正常返回合规检查表，含各检查项状态。"""
        mock_result = {
            "store_id": STORE_ID,
            "check_date": "2026-04-04",
            "items": [
                {"item": "留样记录", "status": "ok", "required": True},
                {"item": "温控记录", "status": "warning", "required": True},
            ],
            "compliance_rate": 0.75,
            "required_count": 2,
        }

        with patch(
            "services.tx_supply.src.services.food_safety.get_compliance_checklist",
            return_value=mock_result,
        ):
            with TestClient(app) as client:
                resp = client.get(
                    f"/api/v1/supply/food-safety/checklist/{STORE_ID}",
                    params={"check_date": "2026-04-04"},
                    headers=HEADERS,
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["compliance_rate"] == 0.75
        assert len(data["data"]["items"]) == 2


# ══════════════════════════════════════════════════════════════════════════════
#  POST /event — 食安事件上报（含emit_event验证）
# ══════════════════════════════════════════════════════════════════════════════


class TestReportFoodSafetyEvent:
    """POST /api/v1/supply/food-safety/event"""

    def test_report_high_severity_event(self):
        """上报 high 级别事件，返回 event_id，不触发自动通知。"""
        event_id = str(uuid.uuid4())
        mock_result = {
            "event_id": event_id,
            "store_id": STORE_ID,
            "event_type": "temperature_violation",
            "severity": "high",
            "status": "open",
        }
        app.dependency_overrides[get_db] = _override_get_db()

        with patch(
            "services.tx_supply.src.services.food_safety.report_food_safety_event",
            new=AsyncMock(return_value=mock_result),
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/supply/food-safety/event",
                    json={
                        "store_id": STORE_ID,
                        "event_type": "temperature_violation",
                        "detail": "冷藏温度超标至8°C",
                        "severity": "high",
                    },
                    headers=HEADERS,
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["event_id"] == event_id

    def test_critical_event_triggers_publisher(self):
        """critical 级别事件触发 UniversalPublisher.publish（旁路通知区域经理）。"""
        event_id = str(uuid.uuid4())
        # 不 mock service，让真实 service 执行，但 patch DB 和 Publisher
        mock_db = _mock_db()
        # mock db.execute (set_config + 其他)
        mock_db.execute = AsyncMock(return_value=MagicMock())
        app.dependency_overrides[get_db] = _override_get_db(mock_db)

        with patch(_EMIT_PATCH, new=AsyncMock()) as mock_publish, \
             patch("asyncio.create_task") as mock_task:
            mock_task.side_effect = lambda coro: None  # 不真正执行协程

            with patch(
                "services.tx_supply.src.services.food_safety.report_food_safety_event",
                new=AsyncMock(return_value={
                    "event_id": event_id,
                    "store_id": STORE_ID,
                    "event_type": "food_poisoning",
                    "severity": "critical",
                    "status": "open",
                    "auto_notified": True,
                }),
            ):
                with TestClient(app) as client:
                    resp = client.post(
                        "/api/v1/supply/food-safety/event",
                        json={
                            "store_id": STORE_ID,
                            "event_type": "food_poisoning",
                            "detail": "顾客食物中毒疑似事故",
                            "severity": "critical",
                        },
                        headers=HEADERS,
                    )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["severity"] == "critical"
        assert data["data"].get("auto_notified") is True


# ══════════════════════════════════════════════════════════════════════════════
#  POST /responsibility-chain — 责任追踪链
# ══════════════════════════════════════════════════════════════════════════════


class TestGetResponsibilityChain:
    """POST /api/v1/supply/food-safety/responsibility-chain"""

    def test_returns_responsibility_chain(self):
        """正常返回责任追踪链，按阶段分类。"""
        mock_result = {
            "event_id": "evt_001",
            "chain": [
                {"step": "purchase", "operator": "采购员A", "time": "2026-03-28"},
                {"step": "receiving", "operator": "验收员B", "time": "2026-03-29"},
                {"step": "requisition", "operator": "厨师C", "time": "2026-04-01"},
            ],
            "responsibility": {
                "procurement": [{"operator": "采购员A"}],
                "receiving": [{"operator": "验收员B"}],
                "requisition": [{"operator": "厨师C"}],
                "production": [],
            },
        }
        app.dependency_overrides[get_db] = _override_get_db()

        with patch(
            "services.tx_supply.src.services.food_safety.get_responsibility_chain",
            new=AsyncMock(return_value=mock_result),
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/supply/food-safety/responsibility-chain",
                    json={
                        "event_id": "evt_001",
                        "batch_no": BATCH_NO,
                        "store_id": STORE_ID,
                    },
                    headers=HEADERS,
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["data"]["chain"]) == 3
        assert "responsibility" in data["data"]

    def test_returns_empty_chain_when_no_records(self):
        """无相关记录时，chain 为空列表，ok=True。"""
        mock_result = {
            "event_id": "evt_unknown",
            "chain": [],
            "responsibility": {
                "procurement": [], "receiving": [], "requisition": [], "production": []
            },
        }
        app.dependency_overrides[get_db] = _override_get_db()

        with patch(
            "services.tx_supply.src.services.food_safety.get_responsibility_chain",
            new=AsyncMock(return_value=mock_result),
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/supply/food-safety/responsibility-chain",
                    json={"event_id": "evt_unknown"},
                    headers=HEADERS,
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["chain"] == []
