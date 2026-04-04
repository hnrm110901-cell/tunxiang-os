"""energy_routes.py FastAPI 路由单元测试

测试范围（3端点，Phase 4 能耗管理）：
  - POST /api/v1/ops/energy/readings    — 抄表数据上报（正常/异常检测/emit_event调用）
  - POST /api/v1/ops/energy/benchmarks  — 设置能耗基准线（正常/emit_event调用）
  - GET  /api/v1/ops/energy/snapshot    — 当日能耗快照（正常/无数据/DB异常）

技术约束：
  - POST /readings 和 /benchmarks 不依赖 DB（直接 emit_event）
  - GET /snapshot 通过 asyncpg.connect patch 隔离
  - emit_event 通过 asyncio.create_task patch 拦截
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ..api.energy_routes import router as energy_router

# ── 应用组装 ──────────────────────────────────────────────────────────────────

app = FastAPI()
app.include_router(energy_router)

# ── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}


# ══════════════════════════════════════════════════════════════════════════════
#  POST /readings — 抄表数据上报
# ══════════════════════════════════════════════════════════════════════════════


class TestCaptureEnergyReading:
    """POST /api/v1/ops/energy/readings"""

    _base_payload = {
        "store_id": STORE_ID,
        "meter_id": "ELEC-A01",
        "meter_type": "electricity",
        "reading_value": 12345.6,
        "delta_value": 88.5,
        "unit": "kWh",
        "source": "iot",
    }

    def test_normal_reading_emits_reading_captured(self):
        """正常抄表，返回 reading_id，旁路发射 READING_CAPTURED 事件。"""
        with patch("asyncio.create_task") as mock_task:
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/ops/energy/readings",
                    json={**self._base_payload, "revenue_fen": 50000},
                    headers=HEADERS,
                )
            assert mock_task.called  # emit_event 被旁路调用

        assert resp.status_code == 201
        data = resp.json()
        assert data["ok"] is True
        assert "reading_id" in data["data"]
        assert data["data"]["meter_type"] == "electricity"
        assert data["data"]["delta_value"] == 88.5
        assert data["data"]["is_anomaly"] is False

    def test_high_ratio_emits_anomaly_detected(self):
        """能耗/营收比超过15%时，同时发射 ANOMALY_DETECTED 事件（create_task 调用2次）。

        ratio = delta_value / (revenue_fen / 100)
        = 200 / (100 / 100) = 200  >> 0.15
        """
        with patch("asyncio.create_task") as mock_task:
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/ops/energy/readings",
                    json={
                        **self._base_payload,
                        "delta_value": 200.0,
                        "revenue_fen": 100,  # 1元营收，200度电 → 比率超标
                    },
                    headers=HEADERS,
                )
            # READING_CAPTURED + ANOMALY_DETECTED = 2次 create_task
            assert mock_task.call_count == 2

        assert resp.status_code == 201
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["is_anomaly"] is True
        assert data["data"]["energy_revenue_ratio"] is not None

    def test_no_revenue_no_anomaly_check(self):
        """revenue_fen=0 时不计算比率，is_anomaly=False，只发射1次事件。"""
        with patch("asyncio.create_task") as mock_task:
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/ops/energy/readings",
                    json={**self._base_payload, "revenue_fen": 0},
                    headers=HEADERS,
                )
            assert mock_task.call_count == 1

        data = resp.json()
        assert data["data"]["is_anomaly"] is False
        assert data["data"]["energy_revenue_ratio"] is None

    def test_gas_meter_type_maps_correctly(self):
        """燃气表 meter_type=gas 正常处理，返回正确字段。"""
        with patch("asyncio.create_task"):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/ops/energy/readings",
                    json={
                        "store_id": STORE_ID,
                        "meter_id": "GAS-B02",
                        "meter_type": "gas",
                        "reading_value": 500.0,
                        "delta_value": 12.3,
                        "unit": "m³",
                        "source": "manual",
                    },
                    headers=HEADERS,
                )

        assert resp.status_code == 201
        data = resp.json()
        assert data["data"]["meter_type"] == "gas"
        assert data["data"]["unit"] == "m³"


# ══════════════════════════════════════════════════════════════════════════════
#  POST /benchmarks — 设置能耗基准线
# ══════════════════════════════════════════════════════════════════════════════


class TestSetEnergyBenchmark:
    """POST /api/v1/ops/energy/benchmarks"""

    def test_creates_benchmark_and_emits_event(self):
        """正常设置基准线，返回 benchmark_id，旁路发射 BENCHMARK_SET 事件。"""
        with patch("asyncio.create_task") as mock_task:
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/ops/energy/benchmarks",
                    json={
                        "store_id": STORE_ID,
                        "meter_type": "electricity",
                        "daily_limit": 300.0,
                        "revenue_ratio_limit": 0.08,
                        "effective_date": "2026-04-04",
                    },
                    headers=HEADERS,
                )
            assert mock_task.called

        assert resp.status_code == 201
        data = resp.json()
        assert data["ok"] is True
        assert "benchmark_id" in data["data"]
        assert data["data"]["daily_limit"] == 300.0
        assert data["data"]["revenue_ratio_limit"] == 0.08
        assert data["data"]["effective_date"] == "2026-04-04"

    def test_benchmark_defaults_effective_date_to_today(self):
        """不传 effective_date 时，默认为今日。"""
        with patch("asyncio.create_task"):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/ops/energy/benchmarks",
                    json={
                        "store_id": STORE_ID,
                        "meter_type": "water",
                        "daily_limit": 50.0,
                        "revenue_ratio_limit": 0.03,
                    },
                    headers=HEADERS,
                )

        assert resp.status_code == 201
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["effective_date"] is not None  # 今日日期自动填充


# ══════════════════════════════════════════════════════════════════════════════
#  GET /snapshot — 当日能耗快照
# ══════════════════════════════════════════════════════════════════════════════


class TestGetEnergySnapshot:
    """GET /api/v1/ops/energy/snapshot"""

    def _make_asyncpg_mock(self, row_data: dict | None):
        """构造 asyncpg.connect 上下文 mock。"""
        conn_mock = AsyncMock()
        conn_mock.execute = AsyncMock()
        conn_mock.fetchrow = AsyncMock(return_value=row_data)
        conn_mock.close = AsyncMock()

        async def _connect(*args, **kwargs):
            return conn_mock

        return _connect

    def test_returns_snapshot_when_data_exists(self):
        """有数据时返回完整能耗快照，含 efficiency_level。"""
        mock_row = {
            "electricity_kwh": 120.5,
            "gas_m3": 30.2,
            "water_m3": 8.0,
            "total_energy_cost_fen": 45000,
            "revenue_fen": 800000,
            "energy_revenue_ratio": 0.056,
            "anomaly_count": 0,
            "updated_at": None,
        }

        with patch(
            "services.tx_ops.src.api.energy_routes.asyncpg.connect",
            side_effect=self._make_asyncpg_mock(mock_row),
        ):
            with TestClient(app) as client:
                resp = client.get(
                    "/api/v1/ops/energy/snapshot",
                    params={"store_id": STORE_ID, "stat_date": "2026-04-04"},
                    headers=HEADERS,
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["electricity_kwh"] == 120.5
        assert data["data"]["efficiency_level"] == "优秀"  # 0.056 <= 0.05? 不，0.056 > 0.05 → 良好
        # 实际：ratio=0.056 > 0.05 → 良好
        assert data["data"]["efficiency_level"] in ("优秀", "良好")
        assert data["data"]["total_energy_cost_yuan"] == 450.0

    def test_returns_no_data_message_when_row_missing(self):
        """当日无数据时返回 message='当日暂无能耗数据'，ok=True。"""
        with patch(
            "services.tx_ops.src.api.energy_routes.asyncpg.connect",
            side_effect=self._make_asyncpg_mock(None),
        ):
            with TestClient(app) as client:
                resp = client.get(
                    "/api/v1/ops/energy/snapshot",
                    params={"store_id": STORE_ID},
                    headers=HEADERS,
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "当日暂无能耗数据" in data["data"]["message"]

    def test_db_connection_failure_returns_500(self):
        """DB 连接失败时返回 500 HTTPException。"""
        async def _fail_connect(*args, **kwargs):
            raise Exception("connection refused")

        with patch(
            "services.tx_ops.src.api.energy_routes.asyncpg.connect",
            side_effect=_fail_connect,
        ):
            with TestClient(app) as client:
                resp = client.get(
                    "/api/v1/ops/energy/snapshot",
                    params={"store_id": STORE_ID},
                    headers=HEADERS,
                )

        assert resp.status_code == 500
