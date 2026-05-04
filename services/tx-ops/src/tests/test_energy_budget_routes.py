"""能耗预算相关端点测试 — Round 78

覆盖范围（10 个测试）：
  - GET  /budgets          — 有数据返回列表 / 空列表
  - POST /budgets          — UPSERT正常 / emit_event(energy.budget_set)验证
  - GET  /alert-rules      — 有规则列表 / active_only过滤
  - POST /alert-rules      — 正常创建 / emit_event(energy.alert_rule_created)验证 / 无效metric→422
  - GET  /budget-vs-actual — 有预算有实际数据 / 无预算（空响应）/ alert_triggered=True场景

技术约束：
  - budgets/alert-rules 端点使用模块级内存存储，不依赖 DB
  - budget-vs-actual 依赖 energy_monitor.analyze_from_mv，通过 patch 隔离
  - 每个测试类使用 setup_method 清理内存存储，避免测试间污染
  - emit_event 通过 patch("asyncio.create_task") 拦截
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
import services.tx_ops.src.api.energy_routes as energy_module
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


# ── 内存存储清理工具 ───────────────────────────────────────────────────────────


def _clear_stores():
    """清空 energy_routes 模块级内存存储，隔离测试副作用。"""
    energy_module._budget_store.clear()
    energy_module._alert_rule_store.clear()


# ── analyze_from_mv Mock 工具 ─────────────────────────────────────────────────


def _mock_mv_fast_path(electricity_kwh=None, gas_m3=None, water_ton=None, energy_cost_fen=None):
    """返回 mv_fast_path 推理层数据的 mock 结果。"""

    async def _analyze(tenant_id, store_id):
        return {
            "inference_layer": "mv_fast_path",
            "data": {
                "electricity_kwh": electricity_kwh,
                "gas_m3": gas_m3,
                "water_ton": water_ton,
                "energy_cost_fen": energy_cost_fen,
                "energy_revenue_ratio": 0.06,
                "updated_at": None,
                "stat_date": None,
            },
        }

    return _analyze


def _mock_mv_no_data():
    """返回 agent_analysis 路径（无 mv 数据）的 mock 结果。"""

    async def _analyze(tenant_id, store_id):
        return {
            "inference_layer": "agent_analysis",
            "data": {},
        }

    return _analyze


# ══════════════════════════════════════════════════════════════════════════════
#  GET /budgets — 列出月度预算
# ══════════════════════════════════════════════════════════════════════════════


class TestListEnergyBudgets:
    """GET /api/v1/ops/energy/budgets"""

    def setup_method(self):
        _clear_stores()

    def _seed_budget(self, year: int = 2026, month: int = 4):
        """向内存存储写入一条预算记录。"""
        key = f"{TENANT_ID}:{STORE_ID}:{year}:{month}"
        energy_module._budget_store[key] = {
            "budget_id": str(uuid.uuid4()),
            "tenant_id": TENANT_ID,
            "store_id": STORE_ID,
            "budget_year": year,
            "budget_month": month,
            "electricity_kwh_budget": 5000.0,
            "gas_m3_budget": 200.0,
            "water_ton_budget": 80.0,
            "total_cost_budget_fen": 60000,
            "updated_at": "2026-04-01T00:00:00+00:00",
        }

    def test_returns_budget_list_when_data_exists(self):
        """有预算数据时，返回包含 items 和 total 的响应。"""
        self._seed_budget(2026, 4)

        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/ops/energy/budgets",
                params={"store_id": STORE_ID, "year": 2026, "month": 4},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["total"] == 1
        assert len(data["data"]["items"]) == 1
        assert data["data"]["items"][0]["electricity_kwh_budget"] == 5000.0

    def test_returns_empty_when_no_budgets(self):
        """无预算数据时，items 为空列表，total=0。"""
        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/ops/energy/budgets",
                params={"store_id": STORE_ID},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["items"] == []
        assert data["data"]["total"] == 0


# ══════════════════════════════════════════════════════════════════════════════
#  POST /budgets — 设置月度预算（UPSERT）
# ══════════════════════════════════════════════════════════════════════════════


class TestSetEnergyBudget:
    """POST /api/v1/ops/energy/budgets"""

    def setup_method(self):
        _clear_stores()

    _valid_payload = {
        "store_id": STORE_ID,
        "budget_year": 2026,
        "budget_month": 5,
        "electricity_kwh_budget": 4800.0,
        "gas_m3_budget": 180.0,
        "water_ton_budget": 75.0,
        "total_cost_budget_fen": 55000,
    }

    def test_creates_budget_and_returns_record(self):
        """正常 UPSERT，返回预算记录含 budget_id，状态码 201。"""
        with patch("asyncio.create_task"):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/ops/energy/budgets",
                    json=self._valid_payload,
                    headers=HEADERS,
                )

        assert resp.status_code == 201
        data = resp.json()
        assert data["ok"] is True
        assert "budget_id" in data["data"]
        assert data["data"]["budget_year"] == 2026
        assert data["data"]["budget_month"] == 5
        assert data["data"]["electricity_kwh_budget"] == 4800.0

    def test_emit_event_budget_set_called(self):
        """POST /budgets 成功后，asyncio.create_task 被调用一次（BUDGET_SET 事件）。"""
        with patch("asyncio.create_task") as mock_task:
            with TestClient(app) as client:
                client.post(
                    "/api/v1/ops/energy/budgets",
                    json=self._valid_payload,
                    headers=HEADERS,
                )
        assert mock_task.call_count == 1

    def test_upsert_keeps_same_budget_id(self):
        """同一 tenant+store+year+month 重复提交时，budget_id 保持不变（UPSERT）。"""
        with patch("asyncio.create_task"):
            with TestClient(app) as client:
                resp1 = client.post(
                    "/api/v1/ops/energy/budgets",
                    json=self._valid_payload,
                    headers=HEADERS,
                )
                resp2 = client.post(
                    "/api/v1/ops/energy/budgets",
                    json={**self._valid_payload, "electricity_kwh_budget": 9999.0},
                    headers=HEADERS,
                )

        id1 = resp1.json()["data"]["budget_id"]
        id2 = resp2.json()["data"]["budget_id"]
        assert id1 == id2  # UPSERT 保留旧 id


# ══════════════════════════════════════════════════════════════════════════════
#  GET /alert-rules — 列出告警规则
# ══════════════════════════════════════════════════════════════════════════════


class TestListEnergyAlertRules:
    """GET /api/v1/ops/energy/alert-rules"""

    def setup_method(self):
        _clear_stores()

    def _seed_rule(self, is_active: bool = True):
        """直接向内存存储写入一条告警规则。"""
        energy_module._alert_rule_store.append(
            {
                "rule_id": str(uuid.uuid4()),
                "tenant_id": TENANT_ID,
                "store_id": STORE_ID,
                "rule_name": "电耗超预算90%告警",
                "metric": "electricity_kwh",
                "threshold_type": "budget_pct",
                "threshold_value": 90.0,
                "severity": "warning",
                "is_active": is_active,
                "created_at": "2026-04-01T00:00:00+00:00",
            }
        )

    def test_returns_all_active_rules_by_default(self):
        """默认 active_only=True，只返回启用中的规则。"""
        self._seed_rule(is_active=True)
        self._seed_rule(is_active=False)  # 此条不应出现

        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/ops/energy/alert-rules",
                params={"store_id": STORE_ID},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["total"] == 1
        assert all(r["is_active"] for r in data["data"]["items"])

    def test_active_only_false_returns_all_rules(self):
        """active_only=false 时，同时返回启用和禁用的规则。"""
        self._seed_rule(is_active=True)
        self._seed_rule(is_active=False)

        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/ops/energy/alert-rules",
                params={"store_id": STORE_ID, "active_only": "false"},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["total"] == 2


# ══════════════════════════════════════════════════════════════════════════════
#  POST /alert-rules — 创建告警规则
# ══════════════════════════════════════════════════════════════════════════════


class TestCreateEnergyAlertRule:
    """POST /api/v1/ops/energy/alert-rules"""

    def setup_method(self):
        _clear_stores()

    _valid_payload = {
        "store_id": STORE_ID,
        "rule_name": "燃气超用警告",
        "metric": "gas_m3",
        "threshold_type": "budget_pct",
        "threshold_value": 85.0,
        "severity": "warning",
    }

    def test_creates_rule_successfully(self):
        """正常创建，返回 rule_id，状态码 201，规则写入内存存储。"""
        with patch("asyncio.create_task"):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/ops/energy/alert-rules",
                    json=self._valid_payload,
                    headers=HEADERS,
                )

        assert resp.status_code == 201
        data = resp.json()
        assert data["ok"] is True
        assert "rule_id" in data["data"]
        assert data["data"]["metric"] == "gas_m3"
        assert data["data"]["is_active"] is True
        # 确认写入内存存储
        assert len(energy_module._alert_rule_store) == 1

    def test_emit_event_alert_rule_created_called(self):
        """POST /alert-rules 成功后，create_task 被调用一次（ALERT_RULE_CREATED 事件）。"""
        with patch("asyncio.create_task") as mock_task:
            with TestClient(app) as client:
                client.post(
                    "/api/v1/ops/energy/alert-rules",
                    json=self._valid_payload,
                    headers=HEADERS,
                )
        assert mock_task.call_count == 1

    def test_invalid_metric_returns_422(self):
        """无效的 metric 值触发端点内校验，返回 422。"""
        payload_bad_metric = {**self._valid_payload, "metric": "invalid_metric"}

        with patch("asyncio.create_task"):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/ops/energy/alert-rules",
                    json=payload_bad_metric,
                    headers=HEADERS,
                )

        assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
#  GET /budget-vs-actual — 预算 vs 实际对比
# ══════════════════════════════════════════════════════════════════════════════


class TestBudgetVsActual:
    """GET /api/v1/ops/energy/budget-vs-actual"""

    def setup_method(self):
        _clear_stores()

    def _seed_budget(self):
        """写入2026年4月预算。"""
        key = f"{TENANT_ID}:{STORE_ID}:2026:4"
        energy_module._budget_store[key] = {
            "budget_id": str(uuid.uuid4()),
            "tenant_id": TENANT_ID,
            "store_id": STORE_ID,
            "budget_year": 2026,
            "budget_month": 4,
            "electricity_kwh_budget": 5000.0,
            "gas_m3_budget": 200.0,
            "water_ton_budget": 80.0,
            "total_cost_budget_fen": 60000,
            "updated_at": "2026-04-01T00:00:00+00:00",
        }

    def test_returns_comparison_with_budget_and_actual(self):
        """有预算且有 mv 实际数据时，返回各能源对比及 usage_pct。"""
        self._seed_budget()

        with patch(
            "services.tx_ops.src.api.energy_routes.energy_monitor.analyze_from_mv",
            side_effect=_mock_mv_fast_path(
                electricity_kwh=4230.0,
                gas_m3=160.0,
                water_ton=60.0,
                energy_cost_fen=52000,
            ),
        ):
            with TestClient(app) as client:
                resp = client.get(
                    "/api/v1/ops/energy/budget-vs-actual",
                    params={"store_id": STORE_ID, "year": 2026, "month": 4},
                    headers=HEADERS,
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        result = data["data"]
        assert result["year"] == 2026
        assert result["month"] == 4
        # 电量：4230/5000 = 84.6%
        assert result["electricity"]["budget_kwh"] == 5000.0
        assert result["electricity"]["actual_kwh"] == 4230.0
        assert result["electricity"]["usage_pct"] == pytest.approx(84.6, abs=0.1)
        assert "alert_triggered" in result

    def test_returns_none_values_when_no_budget(self):
        """无预算记录时，budget 字段全为 None，usage_pct 为 None。"""
        with patch(
            "services.tx_ops.src.api.energy_routes.energy_monitor.analyze_from_mv",
            side_effect=_mock_mv_fast_path(electricity_kwh=4230.0),
        ):
            with TestClient(app) as client:
                resp = client.get(
                    "/api/v1/ops/energy/budget-vs-actual",
                    params={"store_id": STORE_ID, "year": 2026, "month": 4},
                    headers=HEADERS,
                )

        assert resp.status_code == 200
        data = resp.json()
        result = data["data"]
        assert result["electricity"]["budget_kwh"] is None
        assert result["electricity"]["usage_pct"] is None
        assert result["alert_triggered"] is False

    def test_alert_triggered_true_when_threshold_exceeded(self):
        """实际用量超过告警规则阈值时，alert_triggered=True。"""
        self._seed_budget()

        # 写入一条 budget_pct 规则：电耗超过 80% 即告警
        energy_module._alert_rule_store.append(
            {
                "rule_id": str(uuid.uuid4()),
                "tenant_id": TENANT_ID,
                "store_id": STORE_ID,
                "rule_name": "电耗超80%告警",
                "metric": "electricity_kwh",
                "threshold_type": "budget_pct",
                "threshold_value": 80.0,
                "severity": "warning",
                "is_active": True,
                "created_at": "2026-04-01T00:00:00+00:00",
            }
        )

        # 实际用电 4500 kWh，预算 5000 kWh → 90% > 80% → 触发告警
        with patch(
            "services.tx_ops.src.api.energy_routes.energy_monitor.analyze_from_mv",
            side_effect=_mock_mv_fast_path(electricity_kwh=4500.0),
        ):
            with TestClient(app) as client:
                resp = client.get(
                    "/api/v1/ops/energy/budget-vs-actual",
                    params={"store_id": STORE_ID, "year": 2026, "month": 4},
                    headers=HEADERS,
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["alert_triggered"] is True
