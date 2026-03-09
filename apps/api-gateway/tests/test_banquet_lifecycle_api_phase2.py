"""
Banquet Lifecycle API — Phase 2 单元测试

覆盖端点（API 层转换逻辑，不依赖真实 DB）：
  - get_pipeline          : 返回数组格式 + stage_label + leads 字段映射
  - get_availability_calendar : 返回 days 别名 + capacity 字段
"""

import pytest
from datetime import date
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch


# ── helpers ────────────────────────────────────────────────────────────────────

def _mock_user():
    u = MagicMock()
    u.id = "user-001"
    return u


def _make_pipeline_service_response(stages_override: Optional[dict] = None):
    """Simulate what BanquetLifecycleService.get_pipeline() returns (dict of lists)."""
    stages = {
        "lead":        [
            {
                "reservation_id":  "RES-001",
                "customer_name":   "婚礼客户A",
                "customer_phone":  "13800001111",
                "reservation_date": "2026-09-18",
                "party_size":      200,
                "estimated_budget": 50000.0,
                "room_name":       "宴会厅A",
                "banquet_stage":   "lead",
                "room_locked_at":  None,
                "signed_at":       None,
            }
        ],
        "intent":      [],
        "room_lock":   [],
        "signed":      [],
        "preparation": [],
        "service":     [],
        "completed":   [],
        "cancelled":   [],
    }
    if stages_override:
        stages.update(stages_override)
    return {
        "store_id":               "S001",
        "stages":                 stages,
        "stage_counts":           {k: len(v) for k, v in stages.items()},
        "total_banquets":         sum(len(v) for v in stages.values()),
        "total_confirmed_revenue": 50000.0,
    }


def _make_calendar_service_response(year=2026, month=9, max_capacity=200):
    """Simulate what BanquetLifecycleService.get_availability_calendar() returns."""
    calendar = [
        {
            "date":            f"{year}-{month:02d}-{d:02d}",
            "weekday":         "周一",
            "confirmed_count": 1 if d == 18 else 0,
            "locked_count":    1 if d == 20 else 0,
            "total_guests":    200 if d == 18 else 0,
            "available":       True,
            "capacity_pct":    100.0 if d == 18 else 0.0,
            "demand_factor":   1.5 if d == 20 else 1.0,
            "is_auspicious":   d == 20,
            "auspicious_label": "好日子" if d == 20 else None,
        }
        for d in range(1, 31)
    ]
    return {
        "store_id":           "S001",
        "year":               year,
        "month":              month,
        "max_capacity":       max_capacity,
        "calendar":           calendar,
        "auspicious_days":    1,
        "fully_booked_days":  0,
    }


# ── get_pipeline ───────────────────────────────────────────────────────────────

class TestGetPipeline:

    @pytest.mark.asyncio
    async def test_response_is_array_of_stages(self):
        """stages in response must be a list (array), not a dict."""
        from src.api.banquet_lifecycle import get_pipeline

        svc_response = _make_pipeline_service_response()

        with patch("src.api.banquet_lifecycle.BanquetLifecycleService") as MockSvc:
            instance = MockSvc.return_value
            instance.get_pipeline = AsyncMock(return_value=svc_response)

            result = await get_pipeline(
                store_id="S001",
                event_date_gte=None,
                event_date_lte=None,
                db=AsyncMock(),
                _=_mock_user(),
            )

        assert isinstance(result["stages"], list)

    @pytest.mark.asyncio
    async def test_each_stage_has_required_fields(self):
        """Each stage object must have stage, stage_label, count, leads."""
        from src.api.banquet_lifecycle import get_pipeline

        svc_response = _make_pipeline_service_response()

        with patch("src.api.banquet_lifecycle.BanquetLifecycleService") as MockSvc:
            instance = MockSvc.return_value
            instance.get_pipeline = AsyncMock(return_value=svc_response)

            result = await get_pipeline(
                store_id="S001",
                event_date_gte=None, event_date_lte=None,
                db=AsyncMock(), _=_mock_user(),
            )

        for stage_obj in result["stages"]:
            assert "stage"       in stage_obj
            assert "stage_label" in stage_obj
            assert "count"       in stage_obj
            assert "leads"       in stage_obj
            assert isinstance(stage_obj["leads"], list)

    @pytest.mark.asyncio
    async def test_stage_labels_are_chinese(self):
        """stage_label must be the Chinese name, not the enum key."""
        from src.api.banquet_lifecycle import get_pipeline, _PIPELINE_STAGE_LABELS

        svc_response = _make_pipeline_service_response()

        with patch("src.api.banquet_lifecycle.BanquetLifecycleService") as MockSvc:
            instance = MockSvc.return_value
            instance.get_pipeline = AsyncMock(return_value=svc_response)

            result = await get_pipeline(
                store_id="S001",
                event_date_gte=None, event_date_lte=None,
                db=AsyncMock(), _=_mock_user(),
            )

        by_stage = {s["stage"]: s for s in result["stages"]}
        assert by_stage["lead"]["stage_label"]   == "商机"
        assert by_stage["signed"]["stage_label"] == "已签约"

    @pytest.mark.asyncio
    async def test_cancelled_excluded_from_pipeline(self):
        """cancelled stage should be excluded (not shown in the sales pipeline view)."""
        from src.api.banquet_lifecycle import get_pipeline

        svc_response = _make_pipeline_service_response({
            "cancelled": [
                {
                    "reservation_id": "RES-CANCELLED",
                    "customer_name":  "退单客户",
                    "customer_phone": "13900000001",
                    "reservation_date": "2026-08-01",
                    "party_size": 50,
                    "estimated_budget": 10000.0,
                    "room_name": "宴会厅B",
                    "banquet_stage": "cancelled",
                    "room_locked_at": None,
                    "signed_at": None,
                }
            ]
        })

        with patch("src.api.banquet_lifecycle.BanquetLifecycleService") as MockSvc:
            instance = MockSvc.return_value
            instance.get_pipeline = AsyncMock(return_value=svc_response)

            result = await get_pipeline(
                store_id="S001",
                event_date_gte=None, event_date_lte=None,
                db=AsyncMock(), _=_mock_user(),
            )

        stage_keys = [s["stage"] for s in result["stages"]]
        assert "cancelled" not in stage_keys

    @pytest.mark.asyncio
    async def test_lead_items_have_frontend_fields(self):
        """Each lead in leads[] must have banquet_id, expected_date, contact_name, amount_yuan."""
        from src.api.banquet_lifecycle import get_pipeline

        svc_response = _make_pipeline_service_response()

        with patch("src.api.banquet_lifecycle.BanquetLifecycleService") as MockSvc:
            instance = MockSvc.return_value
            instance.get_pipeline = AsyncMock(return_value=svc_response)

            result = await get_pipeline(
                store_id="S001",
                event_date_gte=None, event_date_lte=None,
                db=AsyncMock(), _=_mock_user(),
            )

        by_stage = {s["stage"]: s for s in result["stages"]}
        lead_stage = by_stage["lead"]
        assert lead_stage["count"] == 1

        lead_item = lead_stage["leads"][0]
        assert "banquet_id"    in lead_item
        assert "expected_date" in lead_item
        assert "contact_name"  in lead_item
        assert "amount_yuan"   in lead_item
        assert lead_item["banquet_id"]    == "RES-001"
        assert lead_item["contact_name"]  == "婚礼客户A"
        assert lead_item["expected_date"] == "2026-09-18"
        assert lead_item["amount_yuan"]   == 50000.0

    @pytest.mark.asyncio
    async def test_empty_store_returns_zero_counts(self):
        """All-empty pipeline should return stages with count=0."""
        from src.api.banquet_lifecycle import get_pipeline

        svc_response = _make_pipeline_service_response({
            "lead": [], "intent": [], "room_lock": [], "signed": [],
            "preparation": [], "service": [], "completed": [],
        })

        with patch("src.api.banquet_lifecycle.BanquetLifecycleService") as MockSvc:
            instance = MockSvc.return_value
            instance.get_pipeline = AsyncMock(return_value=svc_response)

            result = await get_pipeline(
                store_id="S999",
                event_date_gte=None, event_date_lte=None,
                db=AsyncMock(), _=_mock_user(),
            )

        assert all(s["count"] == 0 for s in result["stages"])

    @pytest.mark.asyncio
    async def test_count_matches_leads_length(self):
        """count field must equal len(leads) for each stage."""
        from src.api.banquet_lifecycle import get_pipeline

        extra_lead = {
            "reservation_id":  "RES-002",
            "customer_name":   "婚礼客户B",
            "customer_phone":  "13800002222",
            "reservation_date": "2026-10-01",
            "party_size":      150,
            "estimated_budget": 30000.0,
            "room_name":       "宴会厅B",
            "banquet_stage":   "lead",
            "room_locked_at":  None,
            "signed_at":       None,
        }
        svc_response = _make_pipeline_service_response({
            "lead": [
                svc_response_lead := {
                    "reservation_id":  "RES-001",
                    "customer_name":   "婚礼客户A",
                    "customer_phone":  "13800001111",
                    "reservation_date": "2026-09-18",
                    "party_size":      200,
                    "estimated_budget": 50000.0,
                    "room_name":       "宴会厅A",
                    "banquet_stage":   "lead",
                    "room_locked_at":  None,
                    "signed_at":       None,
                },
                extra_lead,
            ]
        })

        with patch("src.api.banquet_lifecycle.BanquetLifecycleService") as MockSvc:
            instance = MockSvc.return_value
            instance.get_pipeline = AsyncMock(return_value=svc_response)

            result = await get_pipeline(
                store_id="S001",
                event_date_gte=None, event_date_lte=None,
                db=AsyncMock(), _=_mock_user(),
            )

        by_stage = {s["stage"]: s for s in result["stages"]}
        assert by_stage["lead"]["count"] == 2
        assert len(by_stage["lead"]["leads"]) == 2


# ── get_availability_calendar ──────────────────────────────────────────────────

class TestGetAvailabilityCalendar:

    @pytest.mark.asyncio
    async def test_response_has_days_key(self):
        """Response must include 'days' key (alias for calendar) for frontend."""
        from src.api.banquet_lifecycle import get_availability_calendar

        svc_resp = _make_calendar_service_response()

        with patch("src.api.banquet_lifecycle.BanquetLifecycleService") as MockSvc:
            instance = MockSvc.return_value
            instance.get_availability_calendar = AsyncMock(return_value=svc_resp)

            result = await get_availability_calendar(
                store_id="S001", year=2026, month=9,
                max_capacity=200,
                db=AsyncMock(), _=_mock_user(),
            )

        assert "days" in result
        assert isinstance(result["days"], list)

    @pytest.mark.asyncio
    async def test_days_matches_calendar(self):
        """days[] and calendar[] must be the same data."""
        from src.api.banquet_lifecycle import get_availability_calendar

        svc_resp = _make_calendar_service_response()

        with patch("src.api.banquet_lifecycle.BanquetLifecycleService") as MockSvc:
            instance = MockSvc.return_value
            instance.get_availability_calendar = AsyncMock(return_value=svc_resp)

            result = await get_availability_calendar(
                store_id="S001", year=2026, month=9, max_capacity=200,
                db=AsyncMock(), _=_mock_user(),
            )

        assert len(result["days"]) == len(result["calendar"])
        assert result["days"][0]["date"] == result["calendar"][0]["date"]

    @pytest.mark.asyncio
    async def test_each_day_has_capacity_field(self):
        """Each day entry must include 'capacity' = max_capacity."""
        from src.api.banquet_lifecycle import get_availability_calendar

        svc_resp = _make_calendar_service_response(max_capacity=300)

        with patch("src.api.banquet_lifecycle.BanquetLifecycleService") as MockSvc:
            instance = MockSvc.return_value
            instance.get_availability_calendar = AsyncMock(return_value=svc_resp)

            result = await get_availability_calendar(
                store_id="S001", year=2026, month=9, max_capacity=300,
                db=AsyncMock(), _=_mock_user(),
            )

        for day in result["days"]:
            assert "capacity" in day
            assert day["capacity"] == 300

    @pytest.mark.asyncio
    async def test_existing_day_fields_preserved(self):
        """confirmed_count, locked_count, is_auspicious must still be present."""
        from src.api.banquet_lifecycle import get_availability_calendar

        svc_resp = _make_calendar_service_response()

        with patch("src.api.banquet_lifecycle.BanquetLifecycleService") as MockSvc:
            instance = MockSvc.return_value
            instance.get_availability_calendar = AsyncMock(return_value=svc_resp)

            result = await get_availability_calendar(
                store_id="S001", year=2026, month=9, max_capacity=200,
                db=AsyncMock(), _=_mock_user(),
            )

        day18 = next(d for d in result["days"] if d["date"].endswith("-18"))
        assert day18["confirmed_count"] == 1
        assert day18["is_auspicious"]   is False

        day20 = next(d for d in result["days"] if d["date"].endswith("-20"))
        assert day20["locked_count"]  == 1
        assert day20["is_auspicious"] is True

    @pytest.mark.asyncio
    async def test_invalid_month_raises_422(self):
        """month=13 should raise HTTPException 422 (handled by FastAPI route)."""
        from fastapi import HTTPException
        from src.api.banquet_lifecycle import get_availability_calendar

        with patch("src.api.banquet_lifecycle.BanquetLifecycleService"):
            with pytest.raises(HTTPException) as exc_info:
                await get_availability_calendar(
                    store_id="S001", year=2026, month=13, max_capacity=200,
                    db=AsyncMock(), _=_mock_user(),
                )
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_correct_day_count_for_month(self):
        """September has 30 days → days[] should have 30 entries."""
        from src.api.banquet_lifecycle import get_availability_calendar

        svc_resp = _make_calendar_service_response(year=2026, month=9)

        with patch("src.api.banquet_lifecycle.BanquetLifecycleService") as MockSvc:
            instance = MockSvc.return_value
            instance.get_availability_calendar = AsyncMock(return_value=svc_resp)

            result = await get_availability_calendar(
                store_id="S001", year=2026, month=9, max_capacity=200,
                db=AsyncMock(), _=_mock_user(),
            )

        assert len(result["days"]) == 30
