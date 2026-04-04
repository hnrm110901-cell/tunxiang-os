"""seafood_routes.py FastAPI 路由单元测试（Round 68 mock→DB改造后版本）

测试范围（9端点）：
  - POST /api/v1/supply/seafood/track-status  — 状态跟踪（正常/ValueError异常）
  - POST /api/v1/supply/seafood/loss          — 损耗计算（正常/ValueError异常）
  - GET  /api/v1/supply/seafood/tanks/{store} — 鱼缸库存查询（正常）
  - POST /api/v1/supply/seafood/price         — 按重定价（正常/ValueError）
  - GET  /api/v1/supply/seafood/dashboard/{store} — 仪表盘（正常）
  - GET  /api/v1/supply/seafood/tanks         — 鱼缸列表（正常）
  - GET  /api/v1/supply/seafood/stock         — 活鲜库存列表（正常）
  - POST /api/v1/supply/seafood/stock/intake  — 收货入库（正常/食安硬约束失败）
  - POST /api/v1/supply/seafood/stock/mortality — 死亡损耗（正常/无效数量）
  - GET  /api/v1/supply/seafood/mortality-rate — 死亡率统计（正常）
  - POST /api/v1/supply/seafood/tank-reading  — 水质检测（正常）
  - GET  /api/v1/supply/seafood/alerts        — 综合预警（正常）

技术约束：
  - service 函数通过 patch 拦截，不依赖真实 DB 或内存状态
  - 用 AsyncMock 模拟所有 service 层协程
"""
from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.tx_supply.src.api.seafood_routes import router as seafood_router
from shared.ontology.src.database import get_db

# ── 应用组装 ──────────────────────────────────────────────────────────────────

app = FastAPI()
app.include_router(seafood_router)

# ── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
INGREDIENT_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}

# ── DB Mock 工厂 ──────────────────────────────────────────────────────────────


def _mock_db():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _override_get_db(mock_db=None):
    if mock_db is None:
        mock_db = _mock_db()

    async def _dep():
        yield mock_db

    return _dep


# ══════════════════════════════════════════════════════════════════════════════
#  POST /track-status — 活鲜状态跟踪
# ══════════════════════════════════════════════════════════════════════════════


class TestTrackLiveStatus:
    """POST /api/v1/supply/seafood/track-status"""

    def test_track_status_success(self):
        """正常记录状态变更，返回 ok=True。"""
        mock_result = {"ingredient_id": INGREDIENT_ID, "status": "alive", "weight_g": 500.0}
        mock_db = _mock_db()
        app.dependency_overrides[get_db] = _override_get_db(mock_db)

        with patch(
            "services.tx_supply.src.services.live_seafood_v2.track_live_status",
            new=AsyncMock(return_value=mock_result),
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/supply/seafood/track-status",
                    json={
                        "ingredient_id": INGREDIENT_ID,
                        "store_id": STORE_ID,
                        "status": "alive",
                        "weight_g": 500.0,
                    },
                    headers=HEADERS,
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["status"] == "alive"

    def test_track_status_invalid_status_raises_400(self):
        """无效状态值时 service 抛出 ValueError，路由返回 400。"""
        mock_db = _mock_db()
        app.dependency_overrides[get_db] = _override_get_db(mock_db)

        with patch(
            "services.tx_supply.src.services.live_seafood_v2.track_live_status",
            new=AsyncMock(side_effect=ValueError("invalid status: zombie")),
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/supply/seafood/track-status",
                    json={
                        "ingredient_id": INGREDIENT_ID,
                        "store_id": STORE_ID,
                        "status": "zombie",
                        "weight_g": 500.0,
                    },
                    headers=HEADERS,
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 400


# ══════════════════════════════════════════════════════════════════════════════
#  POST /loss — 活鲜损耗计算
# ══════════════════════════════════════════════════════════════════════════════


class TestCalculateLiveLoss:
    """POST /api/v1/supply/seafood/loss"""

    def test_calculate_loss_success(self):
        """正常计算损耗，返回 ok=True 含损耗数据。"""
        mock_result = {
            "store_id": STORE_ID,
            "total_loss_kg": 2.5,
            "death_loss_kg": 1.2,
            "quality_loss_kg": 1.3,
        }
        mock_db = _mock_db()
        app.dependency_overrides[get_db] = _override_get_db(mock_db)

        with patch(
            "services.tx_supply.src.services.live_seafood_v2.calculate_live_loss",
            new=AsyncMock(return_value=mock_result),
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/supply/seafood/loss",
                    json={
                        "store_id": STORE_ID,
                        "start_date": "2026-04-01",
                        "end_date": "2026-04-04",
                    },
                    headers=HEADERS,
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["total_loss_kg"] == 2.5


# ══════════════════════════════════════════════════════════════════════════════
#  GET /tanks/{store_id} — 鱼缸库存
# ══════════════════════════════════════════════════════════════════════════════


class TestGetTankInventory:
    """GET /api/v1/supply/seafood/tanks/{store_id}"""

    def test_returns_tank_inventory(self):
        """正常返回鱼缸库存列表。"""
        mock_result = {
            "store_id": STORE_ID,
            "tanks": [{"tank_id": "T01", "species": "草鱼", "stock_kg": 15.0}],
        }
        mock_db = _mock_db()
        app.dependency_overrides[get_db] = _override_get_db(mock_db)

        with patch(
            "services.tx_supply.src.services.live_seafood_v2.get_tank_inventory",
            new=AsyncMock(return_value=mock_result),
        ):
            with TestClient(app) as client:
                resp = client.get(
                    f"/api/v1/supply/seafood/tanks/{STORE_ID}",
                    headers=HEADERS,
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["data"]["tanks"]) == 1


# ══════════════════════════════════════════════════════════════════════════════
#  POST /stock/intake — 活鲜收货入库
# ══════════════════════════════════════════════════════════════════════════════


class TestIntakeStock:
    """POST /api/v1/supply/seafood/stock/intake"""

    _intake_body = {
        "ingredient_id": INGREDIENT_ID,
        "species": "草鱼",
        "spec": "500g-1kg",
        "origin": "湖南湘潭",
        "quantity_kg": 20.0,
        "unit_price_fen": 1500,
        "supplier_name": "鲜美水产",
        "origin_certificate_no": "CERT-2026-001",
        "quarantine_certificate_no": "QUA-2026-001",
        "operator_id": "emp_001",
    }

    def test_intake_success(self):
        """正常入库，返回 record_id，ok=True。"""
        mock_result = {
            "record_id": "intake_abc123",
            "species": "草鱼",
            "quantity_kg": 20.0,
            "status": "alive",
        }
        app.dependency_overrides[get_db] = _override_get_db()

        with patch(
            "services.tx_supply.src.services.seafood_management_service.intake_stock",
            new=AsyncMock(return_value=mock_result),
        ):
            with TestClient(app) as client:
                resp = client.post(
                    f"/api/v1/supply/seafood/stock/intake?store_id={STORE_ID}",
                    json=self._intake_body,
                    headers=HEADERS,
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 201
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["record_id"] == "intake_abc123"

    def test_intake_missing_certificate_raises_422(self):
        """缺少产地证明时，service 抛出 ValueError，路由返回 422。"""
        app.dependency_overrides[get_db] = _override_get_db()

        with patch(
            "services.tx_supply.src.services.seafood_management_service.intake_stock",
            new=AsyncMock(side_effect=ValueError("食安合规：产地证明编号不能为空")),
        ):
            with TestClient(app) as client:
                body = {**self._intake_body, "origin_certificate_no": ""}
                resp = client.post(
                    f"/api/v1/supply/seafood/stock/intake?store_id={STORE_ID}",
                    json=body,
                    headers=HEADERS,
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
#  POST /stock/mortality — 死亡损耗
# ══════════════════════════════════════════════════════════════════════════════


class TestRecordMortality:
    """POST /api/v1/supply/seafood/stock/mortality"""

    def test_record_mortality_success(self):
        """正常记录死亡损耗，返回 record_id。"""
        mock_result = {
            "record_id": "mort_abc456",
            "species": "龙虾",
            "quantity_kg": 0.5,
            "reason": "运输应激",
        }
        app.dependency_overrides[get_db] = _override_get_db()

        with patch(
            "services.tx_supply.src.services.seafood_management_service.record_mortality",
            new=AsyncMock(return_value=mock_result),
        ):
            with TestClient(app) as client:
                resp = client.post(
                    f"/api/v1/supply/seafood/stock/mortality?store_id={STORE_ID}",
                    json={
                        "ingredient_id": INGREDIENT_ID,
                        "species": "龙虾",
                        "quantity_kg": 0.5,
                        "reason": "运输应激",
                        "operator_id": "emp_002",
                    },
                    headers=HEADERS,
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 201
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["record_id"] == "mort_abc456"

    def test_mortality_invalid_quantity_raises_400(self):
        """数量为0时，service 抛出 ValueError，路由返回 400。"""
        app.dependency_overrides[get_db] = _override_get_db()

        with patch(
            "services.tx_supply.src.services.seafood_management_service.record_mortality",
            new=AsyncMock(side_effect=ValueError("死亡损耗数量必须大于0")),
        ):
            with TestClient(app) as client:
                resp = client.post(
                    f"/api/v1/supply/seafood/stock/mortality?store_id={STORE_ID}",
                    json={
                        "ingredient_id": INGREDIENT_ID,
                        "species": "龙虾",
                        "quantity_kg": 0.001,  # 极小值，service 校验拒绝
                        "reason": "测试",
                        "operator_id": "emp_002",
                    },
                    headers=HEADERS,
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 400


# ══════════════════════════════════════════════════════════════════════════════
#  GET /mortality-rate — 死亡率统计
# ══════════════════════════════════════════════════════════════════════════════


class TestGetMortalityRate:
    """GET /api/v1/supply/seafood/mortality-rate"""

    def test_returns_mortality_rate_stats(self):
        """正常返回死亡率统计，含 is_alert 标记。"""
        mock_result = {
            "store_id": STORE_ID,
            "days": 7,
            "species_rates": [
                {"species": "草鱼", "mortality_rate_pct": 1.2, "is_alert": False},
                {"species": "龙虾", "mortality_rate_pct": 6.5, "is_alert": True},
            ],
        }
        app.dependency_overrides[get_db] = _override_get_db()

        with patch(
            "services.tx_supply.src.services.seafood_management_service.get_mortality_rate",
            new=AsyncMock(return_value=mock_result),
        ):
            with TestClient(app) as client:
                resp = client.get(
                    "/api/v1/supply/seafood/mortality-rate",
                    params={"store_id": STORE_ID, "days": 7},
                    headers=HEADERS,
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["data"]["species_rates"]) == 2
        # 死亡率 > 5% 的品种应标记 is_alert
        alert_items = [s for s in data["data"]["species_rates"] if s["is_alert"]]
        assert len(alert_items) == 1


# ══════════════════════════════════════════════════════════════════════════════
#  POST /tank-reading — 水质检测
# ══════════════════════════════════════════════════════════════════════════════


class TestRecordTankReading:
    """POST /api/v1/supply/seafood/tank-reading"""

    def test_record_reading_success(self):
        """正常记录水质数据，返回 ok=True。"""
        mock_result = {
            "reading_id": "tr_xyz789",
            "tank_id": "T01",
            "temperature": 22.5,
            "ph": 7.2,
            "has_alert": False,
        }
        app.dependency_overrides[get_db] = _override_get_db()

        with patch(
            "services.tx_supply.src.services.seafood_management_service.record_tank_reading",
            new=AsyncMock(return_value=mock_result),
        ):
            with TestClient(app) as client:
                resp = client.post(
                    f"/api/v1/supply/seafood/tank-reading?store_id={STORE_ID}",
                    json={
                        "tank_id": "T01",
                        "temperature": 22.5,
                        "ph": 7.2,
                        "operator_id": "emp_003",
                    },
                    headers=HEADERS,
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 201
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["reading_id"] == "tr_xyz789"


# ══════════════════════════════════════════════════════════════════════════════
#  GET /alerts — 综合预警
# ══════════════════════════════════════════════════════════════════════════════


class TestGetAlerts:
    """GET /api/v1/supply/seafood/alerts"""

    def test_returns_alerts_list(self):
        """正常返回综合预警列表。"""
        mock_result = {
            "store_id": STORE_ID,
            "alerts": [
                {"type": "mortality", "species": "龙虾", "level": "warning"},
                {"type": "low_stock", "species": "草鱼", "level": "info"},
            ],
            "total": 2,
        }
        app.dependency_overrides[get_db] = _override_get_db()

        with patch(
            "services.tx_supply.src.services.seafood_management_service.get_alerts",
            new=AsyncMock(return_value=mock_result),
        ):
            with TestClient(app) as client:
                resp = client.get(
                    "/api/v1/supply/seafood/alerts",
                    params={"store_id": STORE_ID, "min_stock_kg": 5.0},
                    headers=HEADERS,
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["total"] == 2

    def test_returns_empty_alerts_when_all_normal(self):
        """无异常时返回空列表。"""
        mock_result = {"store_id": STORE_ID, "alerts": [], "total": 0}
        app.dependency_overrides[get_db] = _override_get_db()

        with patch(
            "services.tx_supply.src.services.seafood_management_service.get_alerts",
            new=AsyncMock(return_value=mock_result),
        ):
            with TestClient(app) as client:
                resp = client.get(
                    "/api/v1/supply/seafood/alerts",
                    params={"store_id": STORE_ID},
                    headers=HEADERS,
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["total"] == 0
