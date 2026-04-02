"""大厨到家服务测试

测试场景：
1. 创建预约 — 完整流程验证
2. 价格计算 — 服务费阶梯(4人以下/4-8人/8人以上)
3. 厨师列表查询 — 区域+菜系筛选
4. 预约确认+开始服务+完成服务 — 全生命周期
5. 评价服务 — 评分+评论+厨师评分更新
6. 预约历史 — 分页查询
7. 厨师排期 — 按月查询+冲突检测
8. 边界校验 — 无菜品/无效厨师/状态不允许
"""

import pytest

from ..services import chef_at_home as cah_mod
from ..services.chef_at_home import (
    _calc_service_fee_fen,
    calculate_price,
    complete_service,
    confirm_booking,
    create_booking,
    get_booking_history,
    get_chef_schedule,
    list_available_chefs,
    rate_service,
    start_service,
)

TENANT = "tenant-changsha-001"


@pytest.fixture(autouse=True)
def clear_state():
    """每个测试开始前清空内存存储"""
    cah_mod._bookings.clear()
    cah_mod._chefs.clear()
    cah_mod._ratings.clear()
    cah_mod._chef_schedules.clear()
    yield


def _sample_dishes():
    return [
        {"dish_id": "D001", "name": "剁椒鱼头", "quantity": 1, "price_fen": 16800},
        {"dish_id": "D002", "name": "清蒸龙虾", "quantity": 1, "price_fen": 28800},
    ]


# ═══════════════════════════════════════════════════════════
# 1. 价格计算 — 服务费阶梯
# ═══════════════════════════════════════════════════════════

class TestPriceCalculation:
    """验证价格计算逻辑：菜品费+服务费(阶梯)+食材费+交通费"""

    def test_service_fee_under_4_guests(self):
        """4人以下服务费600元=60000分"""
        assert _calc_service_fee_fen(1) == 60000
        assert _calc_service_fee_fen(2) == 60000
        assert _calc_service_fee_fen(3) == 60000

    def test_service_fee_4_to_8_guests(self):
        """4-8人服务费800元=80000分"""
        assert _calc_service_fee_fen(4) == 80000
        assert _calc_service_fee_fen(6) == 80000
        assert _calc_service_fee_fen(7) == 80000

    def test_service_fee_over_8_guests(self):
        """8人以上服务费1200元=120000分"""
        assert _calc_service_fee_fen(8) == 120000
        assert _calc_service_fee_fen(10) == 120000
        assert _calc_service_fee_fen(20) == 120000

    @pytest.mark.asyncio
    async def test_calculate_price_total(self):
        """总价 = 菜品费 + 服务费 + 食材费 + 交通费"""
        dishes = _sample_dishes()
        result = await calculate_price(
            dishes=dishes, guest_count=4, distance_km=10.0,
            tenant_id=TENANT, db=None,
        )

        # 菜品费: 16800 + 28800 = 45600
        assert result["dish_total_fen"] == 45600
        # 服务费: 4人 -> 80000
        assert result["service_fee_fen"] == 80000
        # 食材费: 4 * 15000 = 60000
        assert result["ingredient_fee_fen"] == 60000
        # 交通费: 10 * 500 = 5000
        assert result["transport_fee_fen"] == 5000
        # 总计
        assert result["total_fen"] == 45600 + 80000 + 60000 + 5000


# ═══════════════════════════════════════════════════════════
# 2. 厨师列表查询
# ═══════════════════════════════════════════════════════════

class TestChefListing:
    """验证厨师列表筛选逻辑"""

    @pytest.mark.asyncio
    async def test_list_all_chefs_in_area(self):
        """查询长沙区域所有可用厨师"""
        chefs = await list_available_chefs(
            date="2026-04-01", area="长沙", cuisine_type=None,
            tenant_id=TENANT, db=None,
        )
        assert len(chefs) == 3  # 示例数据有3位厨师

    @pytest.mark.asyncio
    async def test_filter_by_cuisine_type(self):
        """按菜系筛选"""
        chefs = await list_available_chefs(
            date="2026-04-01", area="长沙", cuisine_type="粤菜",
            tenant_id=TENANT, db=None,
        )
        assert len(chefs) == 1
        assert chefs[0]["name"] == "李师傅"

    @pytest.mark.asyncio
    async def test_filter_wrong_area_returns_empty(self):
        """查询不存在的区域返回空"""
        chefs = await list_available_chefs(
            date="2026-04-01", area="北京", cuisine_type=None,
            tenant_id=TENANT, db=None,
        )
        assert len(chefs) == 0


# ═══════════════════════════════════════════════════════════
# 3. 创建预约
# ═══════════════════════════════════════════════════════════

class TestCreateBooking:
    """验证预约创建"""

    @pytest.mark.asyncio
    async def test_create_booking_success(self):
        """正常创建预约"""
        # 先获取一个厨师ID
        chefs = await list_available_chefs(
            date="2026-04-01", area="长沙", cuisine_type=None,
            tenant_id=TENANT, db=None,
        )
        chef_id = chefs[0]["id"]

        booking = await create_booking(
            customer_id="cust-001",
            dishes=_sample_dishes(),
            chef_id=chef_id,
            service_datetime="2026-04-01T18:00:00",
            address="长沙市岳麓区麓山南路123号",
            guest_count=4,
            tenant_id=TENANT,
            db=None,
        )

        assert booking["status"] == "pending"
        assert booking["guest_count"] == 4
        assert booking["total_fen"] > 0
        assert booking["chef_id"] == chef_id
        assert len(booking["dishes"]) == 2

    @pytest.mark.asyncio
    async def test_create_booking_no_dishes_fails(self):
        """没有菜品时创建失败"""
        chefs = await list_available_chefs(
            date="2026-04-01", area="长沙", cuisine_type=None,
            tenant_id=TENANT, db=None,
        )
        with pytest.raises(ValueError, match="至少选择一道菜品"):
            await create_booking(
                customer_id="cust-001", dishes=[],
                chef_id=chefs[0]["id"],
                service_datetime="2026-04-01T18:00:00",
                address="test", guest_count=4,
                tenant_id=TENANT, db=None,
            )

    @pytest.mark.asyncio
    async def test_create_booking_invalid_chef_fails(self):
        """无效厨师ID创建失败"""
        cah_mod._ensure_sample_chefs(TENANT)
        with pytest.raises(ValueError, match="厨师不存在"):
            await create_booking(
                customer_id="cust-001", dishes=_sample_dishes(),
                chef_id="INVALID_ID",
                service_datetime="2026-04-01T18:00:00",
                address="test", guest_count=4,
                tenant_id=TENANT, db=None,
            )


# ═══════════════════════════════════════════════════════════
# 4. 全生命周期 — 确认→开始→完成→评价
# ═══════════════════════════════════════════════════════════

class TestBookingLifecycle:
    """验证预约全生命周期流转"""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        """pending → confirmed → cooking → completed → rated"""
        chefs = await list_available_chefs(
            date="2026-04-01", area="长沙", cuisine_type=None,
            tenant_id=TENANT, db=None,
        )
        chef_id = chefs[0]["id"]

        # 创建
        booking = await create_booking(
            customer_id="cust-001", dishes=_sample_dishes(),
            chef_id=chef_id, service_datetime="2026-04-01T18:00:00",
            address="长沙市", guest_count=6,
            tenant_id=TENANT, db=None,
        )
        assert booking["status"] == "pending"

        # 确认
        booking = await confirm_booking(
            booking_id=booking["id"], payment_id="pay-001",
            tenant_id=TENANT, db=None,
        )
        assert booking["status"] == "confirmed"
        assert booking["payment_id"] == "pay-001"

        # 厨师开始服务
        booking = await start_service(
            booking_id=booking["id"], chef_id=chef_id,
            tenant_id=TENANT, db=None,
        )
        assert booking["status"] == "cooking"

        # 完成服务
        booking = await complete_service(
            booking_id=booking["id"],
            photos=["https://img.example.com/1.jpg", "https://img.example.com/2.jpg"],
            tenant_id=TENANT, db=None,
        )
        assert booking["status"] == "completed"
        assert len(booking["photos"]) == 2

        # 评价
        booking = await rate_service(
            booking_id=booking["id"], rating=5,
            comment="厨艺精湛，服务一流！",
            tenant_id=TENANT, db=None,
        )
        assert booking["status"] == "rated"
        assert booking["rating"] == 5
        assert booking["comment"] == "厨艺精湛，服务一流！"

    @pytest.mark.asyncio
    async def test_cannot_start_pending_booking(self):
        """pending状态不能直接开始服务"""
        chefs = await list_available_chefs(
            date="2026-04-01", area="长沙", cuisine_type=None,
            tenant_id=TENANT, db=None,
        )
        chef_id = chefs[0]["id"]

        booking = await create_booking(
            customer_id="cust-001", dishes=_sample_dishes(),
            chef_id=chef_id, service_datetime="2026-04-01T18:00:00",
            address="长沙市", guest_count=2,
            tenant_id=TENANT, db=None,
        )

        with pytest.raises(ValueError, match="不允许开始服务"):
            await start_service(
                booking_id=booking["id"], chef_id=chef_id,
                tenant_id=TENANT, db=None,
            )


# ═══════════════════════════════════════════════════════════
# 5. 预约历史
# ═══════════════════════════════════════════════════════════

class TestBookingHistory:
    """验证预约历史分页查询"""

    @pytest.mark.asyncio
    async def test_booking_history_pagination(self):
        """分页查询预约历史"""
        chefs = await list_available_chefs(
            date="2026-04-01", area="长沙", cuisine_type=None,
            tenant_id=TENANT, db=None,
        )
        chef_id = chefs[0]["id"]

        # 创建3笔预约（厨师状态需要恢复）
        for i in range(3):
            cah_mod._chefs[chef_id]["status"] = "available"
            await create_booking(
                customer_id="cust-page",
                dishes=_sample_dishes(),
                chef_id=chef_id,
                service_datetime=f"2026-04-0{i+1}T18:00:00",
                address="长沙市", guest_count=4,
                tenant_id=TENANT, db=None,
            )

        result = await get_booking_history(
            customer_id="cust-page", tenant_id=TENANT, db=None,
            page=1, size=2,
        )
        assert result["total"] == 3
        assert len(result["items"]) == 2
        assert result["page"] == 1


# ═══════════════════════════════════════════════════════════
# 6. 厨师排期
# ═══════════════════════════════════════════════════════════

class TestChefSchedule:
    """验证厨师排期查询"""

    @pytest.mark.asyncio
    async def test_chef_schedule_month(self):
        """查询厨师某月排期"""
        chefs = await list_available_chefs(
            date="2026-04-01", area="长沙", cuisine_type=None,
            tenant_id=TENANT, db=None,
        )
        chef_id = chefs[0]["id"]

        schedule = await get_chef_schedule(
            chef_id=chef_id, month="2026-04",
            tenant_id=TENANT, db=None,
        )
        assert schedule["chef_id"] == chef_id
        assert schedule["month"] == "2026-04"
        assert len(schedule["calendar"]) == 30  # 4月有30天
        # 所有日期都可用（还没有预约）
        assert all(d["available"] for d in schedule["calendar"])

    @pytest.mark.asyncio
    async def test_schedule_shows_booked_dates(self):
        """确认预约后，排期中该日期不可用"""
        chefs = await list_available_chefs(
            date="2026-04-15", area="长沙", cuisine_type=None,
            tenant_id=TENANT, db=None,
        )
        chef_id = chefs[0]["id"]

        booking = await create_booking(
            customer_id="cust-001", dishes=_sample_dishes(),
            chef_id=chef_id, service_datetime="2026-04-15T18:00:00",
            address="长沙市", guest_count=4,
            tenant_id=TENANT, db=None,
        )
        await confirm_booking(
            booking_id=booking["id"], payment_id="pay-002",
            tenant_id=TENANT, db=None,
        )

        schedule = await get_chef_schedule(
            chef_id=chef_id, month="2026-04",
            tenant_id=TENANT, db=None,
        )
        # 4月15日应标记为不可用
        apr15 = next(d for d in schedule["calendar"] if d["date"] == "2026-04-15")
        assert apr15["available"] is False
        assert "2026-04-15" in schedule["booked_dates"]
