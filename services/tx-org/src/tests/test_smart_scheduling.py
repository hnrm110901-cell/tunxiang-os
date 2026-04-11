"""预测驱动智能排班 — 单元测试

5个测试：
  1. TestSuggestionBasic          — 生成排班建议，返回时段+人数+成本
  2. TestSuggestionDateRange      — end_date < start_date 返回400
  3. TestApplySchedule            — 应用排班建议写入work_schedules
  4. TestApplyNonExistent         — 应用不存在的排班返回404
  5. TestLaborForecast            — 集团级人力需求预测返回多门店汇总
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.smart_scheduling_routes import router

TENANT_ID = "11111111-1111-1111-1111-111111111111"
STORE_ID = "22222222-2222-2222-2222-222222222222"
HEADERS = {"X-Tenant-ID": TENANT_ID}


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


class _MockRow:
    def __init__(self, d: dict[str, Any]) -> None:
        self._d = d

    @property
    def _mapping(self) -> dict[str, Any]:
        return self._d

    def __getattr__(self, name: str) -> Any:
        if name in self._d:
            return self._d[name]
        raise AttributeError(name)


def _make_db_mock() -> AsyncMock:
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = None
    mock_result.__iter__ = MagicMock(return_value=iter([]))
    mock_result.rowcount = 0
    mock_db.execute.return_value = mock_result
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()
    return mock_db


# ──────────────────────────────────────────────────────────────────────────────
# Test 1: 生成排班建议基本流程
# ──────────────────────────────────────────────────────────────────────────────

class TestSuggestionBasic:
    def test_suggestion_returns_slots(self) -> None:
        """排班建议应返回时段分配方案（含人数和成本）。"""
        app = _make_app()
        mock_db = _make_db_mock()

        # 模拟客流预测返回80人
        traffic_result = MagicMock()
        traffic_result.fetchone.return_value = _MockRow({"avg_traffic": 80})

        # 模拟员工列表
        emp_rows = [
            _MockRow({"id": "emp-1", "name": "张三", "role": "waiter",
                       "hourly_rate_fen": 2500}),
            _MockRow({"id": "emp-2", "name": "李四", "role": "chef",
                       "hourly_rate_fen": 3000}),
        ]
        emp_result = MagicMock()
        emp_result.__iter__ = MagicMock(return_value=iter(emp_rows))

        # 写入操作返回空结果
        write_result = MagicMock()
        write_result.__iter__ = MagicMock(return_value=iter([]))
        write_result.fetchone.return_value = None

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:  # set_rls
                return write_result
            if call_count == 2:  # predict traffic
                return traffic_result
            if call_count == 3:  # get employees
                return emp_result
            return write_result

        mock_db.execute = AsyncMock(side_effect=side_effect)

        with patch("api.smart_scheduling_routes.get_db", return_value=mock_db):
            app.dependency_overrides[router.dependencies] = lambda: mock_db
            from shared.ontology.src.database import get_db
            app.dependency_overrides[get_db] = lambda: mock_db

            client = TestClient(app)
            resp = client.get(
                f"/api/v1/org/smart-schedule/{STORE_ID}/suggestion",
                params={"start_date": "2026-04-10", "end_date": "2026-04-10"},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["total_days"] == 1
        assert len(data["days"]) == 1
        day = data["days"][0]
        assert "slots" in day
        assert len(day["slots"]) == 5  # 5个默认时段
        assert day["slots"][0]["required_headcount"] >= 1


# ──────────────────────────────────────────────────────────────────────────────
# Test 2: 日期范围校验
# ──────────────────────────────────────────────────────────────────────────────

class TestSuggestionDateRange:
    def test_end_before_start_returns_400(self) -> None:
        """end_date 早于 start_date 应返回400。"""
        app = _make_app()
        mock_db = _make_db_mock()

        from shared.ontology.src.database import get_db
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        resp = client.get(
            f"/api/v1/org/smart-schedule/{STORE_ID}/suggestion",
            params={"start_date": "2026-04-15", "end_date": "2026-04-10"},
            headers=HEADERS,
        )
        assert resp.status_code == 400


# ──────────────────────────────────────────────────────────────────────────────
# Test 3: 应用排班建议
# ──────────────────────────────────────────────────────────────────────────────

class TestApplySchedule:
    def test_apply_draft_schedule(self) -> None:
        """应用draft状态的排班建议应成功。"""
        app = _make_app()
        mock_db = _make_db_mock()

        schedule_row = _MockRow({
            "id": str(uuid.uuid4()),
            "schedule_date": date(2026, 4, 10),
            "status": "draft",
        })
        schedule_result = MagicMock()
        schedule_result.fetchone.return_value = schedule_row

        slot_rows = [
            _MockRow({
                "time_slot": "11:00-13:00",
                "required_headcount": 3,
                "assigned_employee_ids": ["emp-1", "emp-2"],
            }),
        ]
        slots_result = MagicMock()
        slots_result.fetchall.return_value = slot_rows

        write_result = MagicMock()
        write_result.rowcount = 1

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:  # set_rls
                return write_result
            if call_count == 2:  # get schedule
                return schedule_result
            if call_count == 3:  # get slots
                return slots_result
            return write_result

        mock_db.execute = AsyncMock(side_effect=side_effect)

        from shared.ontology.src.database import get_db
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        resp = client.post(
            f"/api/v1/org/smart-schedule/{STORE_ID}/apply",
            json={"schedule_id": str(uuid.uuid4())},
            headers=HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["applied"] is True
        assert body["data"]["records_written"] == 2  # 2 employees


# ──────────────────────────────────────────────────────────────────────────────
# Test 4: 应用不存在的排班
# ──────────────────────────────────────────────────────────────────────────────

class TestApplyNonExistent:
    def test_apply_missing_schedule_returns_404(self) -> None:
        """应用不存在的排班建议应返回404。"""
        app = _make_app()
        mock_db = _make_db_mock()

        from shared.ontology.src.database import get_db
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        resp = client.post(
            f"/api/v1/org/smart-schedule/{STORE_ID}/apply",
            json={"schedule_id": str(uuid.uuid4())},
            headers=HEADERS,
        )
        assert resp.status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# Test 5: 集团人力需求预测
# ──────────────────────────────────────────────────────────────────────────────

class TestLaborForecast:
    def test_labor_forecast_returns_stores(self) -> None:
        """集团级预测应返回各门店的每日人力需求。"""
        app = _make_app()
        mock_db = _make_db_mock()

        # Mock stores list
        store_rows = [
            _MockRow({"id": uuid.UUID(STORE_ID), "name": "旗舰店"}),
        ]
        stores_result = MagicMock()
        stores_result.fetchall.return_value = store_rows
        stores_result.__iter__ = MagicMock(return_value=iter(store_rows))

        # Mock traffic prediction
        traffic_result = MagicMock()
        traffic_result.fetchone.return_value = _MockRow({"avg_traffic": 100})

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:  # set_rls
                return MagicMock()
            if call_count == 2:  # get stores
                return stores_result
            return traffic_result  # all subsequent = traffic predictions

        mock_db.execute = AsyncMock(side_effect=side_effect)

        from shared.ontology.src.database import get_db
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        resp = client.get(
            "/api/v1/org/smart-schedule/labor-forecast",
            params={"days": 3},
            headers=HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["store_count"] == 1
        assert data["forecast_days"] == 3
        assert len(data["stores"]) == 1
        assert len(data["stores"][0]["daily_forecast"]) == 3
        assert data["grand_total_headcount"] > 0
