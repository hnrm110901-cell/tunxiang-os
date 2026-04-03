"""私域运营数据看板单元测试"""
from unittest.mock import AsyncMock, patch

import pytest

from ..services.private_domain_dashboard import (
    _compute_member_health_score,
    get_member_health,
    get_private_domain_dashboard,
)

# ─── _compute_member_health_score ─────────────────────────────────────────────

def test_health_score_all_vip():
    dist = {"S5": 100}
    result = _compute_member_health_score({"distribution": dist})
    assert result["score"] == 80.0  # 50 + 30
    assert result["vip_rate"] == 100.0
    assert result["churn_risk_rate"] == 0.0
    assert result["retention_rate"] == 100.0


def test_health_score_all_churn():
    dist = {"S1": 100}
    result = _compute_member_health_score({"distribution": dist})
    assert result["score"] == 30.0  # 50 - 20
    assert result["churn_risk_rate"] == 100.0
    assert result["vip_rate"] == 0.0


def test_health_score_mixed():
    dist = {"S1": 20, "S2": 30, "S3": 30, "S4": 15, "S5": 5}
    result = _compute_member_health_score({"distribution": dist})
    assert 0 <= result["score"] <= 100
    assert result["total_members"] == 100
    assert result["retention_rate"] == 50.0  # S3+S4+S5 = 50%


def test_health_score_empty():
    result = _compute_member_health_score({})
    assert result["score"] == 50.0  # default baseline
    assert result["total_members"] == 1  # uses 1 to avoid division by zero


# ─── get_member_health ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_member_health_success():
    mock_response = {
        "data": {
            "distribution": {"S1": 10, "S2": 20, "S3": 40, "S4": 20, "S5": 10}
        }
    }
    with patch(
        "services.tx_analytics.src.services.private_domain_dashboard._get",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        result = await get_member_health("tenant-123")
        assert result["score"] is not None
        assert "retention_rate" in result
        assert "vip_rate" in result
        assert "churn_risk_rate" in result


@pytest.mark.asyncio
async def test_get_member_health_upstream_down():
    with patch(
        "services.tx_analytics.src.services.private_domain_dashboard._get",
        new_callable=AsyncMock,
        return_value={},  # empty = upstream down
    ):
        result = await get_member_health("tenant-123")
        assert result.get("score") is None
        assert "error" in result


# ─── get_private_domain_dashboard ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dashboard_partial_failure():
    """一个模块失败不应导致整体仪表盘失败"""
    health_result = {"score": 72.5, "retention_rate": 65.0, "vip_rate": 25.0, "churn_risk_rate": 10.0, "distribution": {}, "total_members": 100}
    wecom_result = Exception("Connection refused")
    funnel_result = {"total_active_journeys": 3, "overall_conversion_rate": 12.5}
    roi_result = {"period_days": 30, "trend": [], "degraded": False}

    with patch(
        "services.tx_analytics.src.services.private_domain_dashboard.get_member_health",
        new_callable=AsyncMock,
        return_value=health_result,
    ), patch(
        "services.tx_analytics.src.services.private_domain_dashboard.get_wecom_reach_efficiency",
        new_callable=AsyncMock,
        side_effect=wecom_result,
    ), patch(
        "services.tx_analytics.src.services.private_domain_dashboard.get_journey_funnel",
        new_callable=AsyncMock,
        return_value=funnel_result,
    ), patch(
        "services.tx_analytics.src.services.private_domain_dashboard.get_roi_trend",
        new_callable=AsyncMock,
        return_value=roi_result,
    ):
        result = await get_private_domain_dashboard("tenant-123")

        assert result["member_health"]["score"] == 72.5
        assert "error" in result["wecom_reach_efficiency"]
        assert result["journey_funnel"]["total_active_journeys"] == 3
        assert result["roi_trend"]["period_days"] == 30
        assert "cross_brand_comparison" not in result  # group_id not provided


@pytest.mark.asyncio
async def test_dashboard_includes_cross_brand_when_group_id_given():
    with patch(
        "services.tx_analytics.src.services.private_domain_dashboard.get_member_health",
        new_callable=AsyncMock,
        return_value={"score": 60.0},
    ), patch(
        "services.tx_analytics.src.services.private_domain_dashboard.get_wecom_reach_efficiency",
        new_callable=AsyncMock,
        return_value={"messages_sent": 500},
    ), patch(
        "services.tx_analytics.src.services.private_domain_dashboard.get_journey_funnel",
        new_callable=AsyncMock,
        return_value={"total_active_journeys": 2},
    ), patch(
        "services.tx_analytics.src.services.private_domain_dashboard.get_roi_trend",
        new_callable=AsyncMock,
        return_value={"trend": []},
    ), patch(
        "services.tx_analytics.src.services.private_domain_dashboard.get_cross_brand_comparison",
        new_callable=AsyncMock,
        return_value={"brands": [{"name": "品牌A"}, {"name": "品牌B"}]},
    ):
        result = await get_private_domain_dashboard("tenant-123", group_id="group-001")

        assert "cross_brand_comparison" in result
        assert len(result["cross_brand_comparison"]["brands"]) == 2
