"""#710 YYYY-MM dedup Phase 2 Lane D — tx-trade regression tests

验证 get_chef_schedule 的 parse_year_month 集成：
- 畸形输入 → ValueError（通过 None branch）
- 合法输入 → (year, month) 正确解包
"""

from __future__ import annotations

import pytest

from ..services import chef_at_home as cah_mod
from ..services.chef_at_home import get_chef_schedule, list_available_chefs

TENANT = "tenant-changsha-001"


@pytest.fixture(autouse=True)
def clear_state():
    """每个测试开始前清空内存存储"""
    cah_mod._bookings.clear()
    cah_mod._chefs.clear()
    cah_mod._ratings.clear()
    cah_mod._chef_schedules.clear()
    yield


class TestGetChefScheduleYYYYMM:
    """get_chef_schedule month 参数解析回归测试"""

    @pytest.mark.asyncio
    async def test_single_digit_month_raises(self):
        """'2026-3' 单月无补零 → parse_year_month 返回 None → ValueError"""
        # 先确保有厨师
        chefs = await list_available_chefs(
            date="2026-03-01",
            area="长沙",
            cuisine_type=None,
            tenant_id=TENANT,
            db=None,
        )
        chef_id = chefs[0]["id"]

        with pytest.raises(ValueError, match="month must be YYYY-MM format"):
            await get_chef_schedule(
                chef_id=chef_id,
                month="2026-3",
                tenant_id=TENANT,
                db=None,
            )

    @pytest.mark.asyncio
    async def test_empty_string_raises(self):
        """'' 空字符串 → parse_year_month 返回 None → ValueError"""
        chefs = await list_available_chefs(
            date="2026-03-01",
            area="长沙",
            cuisine_type=None,
            tenant_id=TENANT,
            db=None,
        )
        chef_id = chefs[0]["id"]

        with pytest.raises(ValueError, match="month must be YYYY-MM format"):
            await get_chef_schedule(
                chef_id=chef_id,
                month="",
                tenant_id=TENANT,
                db=None,
            )

    @pytest.mark.asyncio
    async def test_abc_raises(self):
        """'abc' 非日期字符串 → parse_year_month 返回 None → ValueError"""
        chefs = await list_available_chefs(
            date="2026-03-01",
            area="长沙",
            cuisine_type=None,
            tenant_id=TENANT,
            db=None,
        )
        chef_id = chefs[0]["id"]

        with pytest.raises(ValueError, match="month must be YYYY-MM format"):
            await get_chef_schedule(
                chef_id=chef_id,
                month="abc",
                tenant_id=TENANT,
                db=None,
            )

    @pytest.mark.asyncio
    async def test_valid_month_proceeds(self):
        """'2026-03' 合法输入 → (2026, 3) 正确解包，返回 calendar 列表"""
        chefs = await list_available_chefs(
            date="2026-03-01",
            area="长沙",
            cuisine_type=None,
            tenant_id=TENANT,
            db=None,
        )
        chef_id = chefs[0]["id"]

        result = await get_chef_schedule(
            chef_id=chef_id,
            month="2026-03",
            tenant_id=TENANT,
            db=None,
        )
        assert result["month"] == "2026-03"
        assert len(result["calendar"]) == 31  # 3月有31天
