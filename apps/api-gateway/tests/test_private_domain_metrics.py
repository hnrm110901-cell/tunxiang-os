"""
private_domain_metrics 单元测试

覆盖：
  - get_owned_audience（正常 + 零数据 + SQL 错误降级）
  - get_customer_value（复购率计算 + yuan 转换 + 零买家）
  - get_journey_health（完成率计算 + 信号计数）
  - get_lifecycle_funnel（已知状态 + unknown 分流）
  - get_full_metrics（聚合结构 + 必要字段）
"""

import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("APP_ENV", "test")

from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from src.services.private_domain_metrics import (
    get_owned_audience,
    get_customer_value,
    get_journey_health,
    get_lifecycle_funnel,
    get_full_metrics,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _row(*values):
    """构造单行查询结果（通过序号访问）。"""
    row = MagicMock()
    row.__getitem__ = lambda self, i: values[i]
    return row


def _make_db(scalar_returns):
    """
    构造多次 scalar 调用的 AsyncMock DB。
    scalar_returns: 每次 fetchone 依序返回的值列表（每个值对应一次 _scalar 调用）。
    """
    db = AsyncMock()
    rows = [_row(v) for v in scalar_returns]
    db.execute.return_value.fetchone.side_effect = rows
    return db


# ════════════════════════════════════════════════════════════════════════════════
# get_owned_audience
# ════════════════════════════════════════════════════════════════════════════════

class TestGetOwnedAudience:
    @pytest.mark.asyncio
    async def test_returns_correct_structure(self):
        db = _make_db([1250, 420, 890, 45])
        result = await get_owned_audience("S001", db)

        assert result["total_members"]    == 1250
        assert result["active_members"]   == 420
        assert result["wxwork_connected"] == 890
        assert result["new_this_month"]   == 45

    @pytest.mark.asyncio
    async def test_active_rate_calculated(self):
        db = _make_db([100, 40, 60, 5])
        result = await get_owned_audience("S001", db)
        assert result["active_rate"] == pytest.approx(0.4)

    @pytest.mark.asyncio
    async def test_connect_rate_calculated(self):
        db = _make_db([200, 50, 100, 10])
        result = await get_owned_audience("S001", db)
        assert result["connect_rate"] == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_zero_total_members_safe(self):
        db = _make_db([0, 0, 0, 0])
        result = await get_owned_audience("S001", db)
        assert result["active_rate"]  == 0.0
        assert result["connect_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_sql_error_returns_zero(self):
        db = AsyncMock()
        db.execute.side_effect = Exception("DB error")
        result = await get_owned_audience("S001", db)
        assert result["total_members"] == 0
        assert result["active_rate"]   == 0.0


# ════════════════════════════════════════════════════════════════════════════════
# get_customer_value
# ════════════════════════════════════════════════════════════════════════════════

class TestGetCustomerValue:
    @pytest.mark.asyncio
    async def test_repeat_rate_calculated(self):
        # total_buyers=100, repeat_buyers=42, avg_ltv=38550, avg_aov=12830, avg_freq=3.2
        db = _make_db([100, 42, 38550, 12830, 3.2])
        result = await get_customer_value("S001", db)
        assert result["repeat_rate_30d"] == pytest.approx(0.42)

    @pytest.mark.asyncio
    async def test_yuan_conversion(self):
        db = _make_db([1, 1, 38550, 12830, 3.2])
        result = await get_customer_value("S001", db)
        assert result["avg_ltv_yuan"]         == pytest.approx(385.5)
        assert result["avg_order_value_yuan"] == pytest.approx(128.3)

    @pytest.mark.asyncio
    async def test_zero_buyers_safe(self):
        db = _make_db([0, 0, 0, 0, 0])
        result = await get_customer_value("S001", db)
        assert result["repeat_rate_30d"]      == 0.0
        assert result["avg_ltv_yuan"]         == 0.0
        assert result["avg_order_value_yuan"] == 0.0

    @pytest.mark.asyncio
    async def test_sql_error_returns_zero(self):
        db = AsyncMock()
        db.execute.side_effect = Exception("DB error")
        result = await get_customer_value("S001", db)
        assert result["repeat_rate_30d"] == 0.0


# ════════════════════════════════════════════════════════════════════════════════
# get_journey_health
# ════════════════════════════════════════════════════════════════════════════════

class TestGetJourneyHealth:
    @pytest.mark.asyncio
    async def test_completion_rate_calculated(self):
        # running=45, completed=320, total_90d=450, bad_review=3, churn_risk=12
        db = _make_db([45, 320, 450, 3, 12])
        result = await get_journey_health("S001", db)
        assert result["completion_rate"]    == pytest.approx(round(320 / 450, 3))
        assert result["running_journeys"]   == 45
        assert result["bad_review_signals"] == 3
        assert result["churn_risk_count"]   == 12

    @pytest.mark.asyncio
    async def test_zero_journeys_safe(self):
        db = _make_db([0, 0, 0, 0, 0])
        result = await get_journey_health("S001", db)
        assert result["completion_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_sql_error_returns_zero(self):
        db = AsyncMock()
        db.execute.side_effect = Exception("DB error")
        result = await get_journey_health("S001", db)
        assert result["completion_rate"]    == 0.0
        assert result["running_journeys"]   == 0


# ════════════════════════════════════════════════════════════════════════════════
# get_lifecycle_funnel
# ════════════════════════════════════════════════════════════════════════════════

class TestGetLifecycleFunnel:
    @pytest.mark.asyncio
    async def test_known_states_distributed(self):
        # Simulate rows: [("repeat", 650), ("vip", 90), ("at_risk", 65)]
        db = AsyncMock()
        rows = [
            _row("repeat", 650),
            _row("vip", 90),
            _row("at_risk", 65),
        ]
        db.execute.return_value.fetchall.return_value = rows
        # No unknown rows, so second query returns 0
        db.execute.return_value.fetchone.return_value = _row(0)

        result = await get_lifecycle_funnel("S001", db)

        assert result["repeat"]   == 650
        assert result["vip"]      == 90
        assert result["at_risk"]  == 65
        assert result["lead"]     == 0

    @pytest.mark.asyncio
    async def test_unknown_split_by_frequency(self):
        """_unknown 成员按 frequency=0 分配到 first_order_pending，其余到 repeat。"""
        db = AsyncMock()
        rows = [_row("_unknown", 100)]
        db.execute.return_value.fetchall.return_value = rows
        # 30 members have frequency=0
        db.execute.return_value.fetchone.return_value = _row(30)

        result = await get_lifecycle_funnel("S001", db)

        assert result["first_order_pending"] == 30
        assert result["repeat"]              == 70

    @pytest.mark.asyncio
    async def test_sql_error_returns_empty_funnel(self):
        db = AsyncMock()
        db.execute.side_effect = Exception("DB error")
        result = await get_lifecycle_funnel("S001", db)
        # All states should be 0
        assert all(v == 0 for v in result.values())


# ════════════════════════════════════════════════════════════════════════════════
# get_full_metrics
# ════════════════════════════════════════════════════════════════════════════════

class TestGetFullMetrics:
    @pytest.mark.asyncio
    async def test_returns_all_top_level_keys(self):
        db = AsyncMock()
        # get_owned_audience: 4 scalar queries
        # get_customer_value: 5 scalar queries
        # get_journey_health: 5 scalar queries
        # get_lifecycle_funnel: 1 fetchall + 1 fetchone
        db.execute.return_value.fetchone.return_value = _row(0)
        db.execute.return_value.fetchall.return_value = []

        result = await get_full_metrics("S001", db)

        assert result["store_id"]         == "S001"
        assert "as_of"                    in result
        assert "owned_audience"           in result
        assert "customer_value"           in result
        assert "journey_health"           in result
        assert "lifecycle_funnel"         in result

    @pytest.mark.asyncio
    async def test_lifecycle_funnel_has_all_9_states(self):
        db = AsyncMock()
        db.execute.return_value.fetchone.return_value = _row(0)
        db.execute.return_value.fetchall.return_value = []

        result = await get_full_metrics("S001", db)
        funnel = result["lifecycle_funnel"]

        expected_states = {
            "lead", "registered", "first_order_pending",
            "repeat", "high_frequency", "vip",
            "at_risk", "dormant", "lost",
        }
        assert expected_states == set(funnel.keys())
