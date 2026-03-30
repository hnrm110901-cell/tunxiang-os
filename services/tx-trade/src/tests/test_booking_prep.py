"""预订备餐联动服务测试 — 8 个场景

场景清单：
1. 今日汇总：今日预订数正确
2. 菜品需求聚合：多桌点同款菜合并数量
3. 生成备餐任务：幂等性（重复调用）
4. 备餐任务状态流转：pending → started → done
5. 档口分配：烤鸭 → 烤制档口（roast）
6. 距就餐时间排序（最近先显示）
7. 待备餐列表只含未完成（pending/started）
8. 租户隔离
"""
import pytest
from datetime import datetime, timezone, timedelta

from ..services import booking_prep_service as bps_mod
from ..services.booking_prep_service import (
    BookingPrepService,
    _register_booking,
    _clear_store,
)

TENANT_A = "tenant-a-001"
TENANT_B = "tenant-b-002"
STORE = "store-xujihaixian-wanbao"


@pytest.fixture(autouse=True)
def clear_state():
    """每个测试前清空内存存储，保持隔离。"""
    _clear_store()
    bps_mod._bookings.clear()
    yield
    _clear_store()
    bps_mod._bookings.clear()


def _now_plus(hours: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


# ═══════════════════════════════════════════════════════════
# 场景 1: 今日汇总 — 今日预订数正确
# ═══════════════════════════════════════════════════════════

class TestTodaySummaryCount:
    """今日预订数应精确统计当日预订，不含昨日/明日。"""

    def test_today_count_is_accurate(self):
        # 今日两桌预订
        _register_booking(TENANT_A, "book-001", STORE, _now_plus(2), [
            {"dish_id": "d1", "dish_name": "红烧肉", "quantity": 1},
        ])
        _register_booking(TENANT_A, "book-002", STORE, _now_plus(4), [
            {"dish_id": "d2", "dish_name": "小炒肉", "quantity": 2},
        ])
        # 明日预订（不应计入今日）
        _register_booking(TENANT_A, "book-003", STORE, _now_plus(26), [
            {"dish_id": "d3", "dish_name": "蒸鱼", "quantity": 1},
        ])

        summary = BookingPrepService.get_today_summary(STORE, TENANT_A)

        assert summary.today_count == 2, f"今日预订应为2桌，实际={summary.today_count}"

    def test_week_count_includes_today(self):
        _register_booking(TENANT_A, "book-001", STORE, _now_plus(2), [
            {"dish_id": "d1", "dish_name": "红烧肉", "quantity": 1},
        ])
        summary = BookingPrepService.get_today_summary(STORE, TENANT_A)
        assert summary.week_count >= 1


# ═══════════════════════════════════════════════════════════
# 场景 2: 菜品需求聚合 — 多桌同款菜合并数量
# ═══════════════════════════════════════════════════════════

class TestDishAggregation:
    """同一门店本周多桌点同款菜，总量应累加，预订桌数应去重计数。"""

    def test_same_dish_across_bookings_aggregated(self):
        # 三桌都点了"口味虾"
        for i, qty in enumerate([2, 3, 1], start=1):
            _register_booking(TENANT_A, f"book-{i:03d}", STORE, _now_plus(i * 2), [
                {"dish_id": "d-kouwei", "dish_name": "口味虾", "quantity": qty},
            ])

        summary = BookingPrepService.get_today_summary(STORE, TENANT_A)
        dish_map = {d.dish_name: d for d in summary.top_dishes}

        assert "口味虾" in dish_map, "口味虾应出现在 top_dishes 中"
        assert dish_map["口味虾"].total_qty == 6, f"口味虾总量应为6，实际={dish_map['口味虾'].total_qty}"
        assert dish_map["口味虾"].booking_count == 3, f"预订桌数应为3，实际={dish_map['口味虾'].booking_count}"

    def test_top10_limit(self):
        # 注册 12 种不同菜品
        for i in range(12):
            _register_booking(TENANT_A, f"book-{i:03d}", STORE, _now_plus(1), [
                {"dish_id": f"d-{i}", "dish_name": f"菜品{i:02d}", "quantity": 12 - i},
            ])

        summary = BookingPrepService.get_today_summary(STORE, TENANT_A)
        assert len(summary.top_dishes) <= 10, "top_dishes 最多10条"


# ═══════════════════════════════════════════════════════════
# 场景 3: 生成备餐任务 — 幂等性
# ═══════════════════════════════════════════════════════════

class TestGeneratePrepTasksIdempotent:
    """重复调用 generate_prep_tasks 不应创建重复记录。"""

    def test_idempotent_returns_same_tasks(self):
        _register_booking(TENANT_A, "book-001", STORE, _now_plus(3), [
            {"dish_id": "d1", "dish_name": "烤鸭", "quantity": 1},
            {"dish_id": "d2", "dish_name": "小炒肉", "quantity": 2},
        ])

        tasks_first = BookingPrepService.generate_prep_tasks("book-001", TENANT_A)
        tasks_second = BookingPrepService.generate_prep_tasks("book-001", TENANT_A)

        assert len(tasks_first) == 2
        assert len(tasks_second) == 2
        # 任务 ID 应相同（内存存储中是同一批对象）
        ids_first = {t.id for t in tasks_first}
        ids_second = {t.id for t in tasks_second}
        assert ids_first == ids_second, "幂等调用应返回相同任务 ID"

    def test_generate_raises_for_unknown_booking(self):
        with pytest.raises(ValueError, match="不存在"):
            BookingPrepService.generate_prep_tasks("nonexistent-booking", TENANT_A)

    def test_generate_raises_for_empty_items(self):
        _register_booking(TENANT_A, "book-empty", STORE, _now_plus(2), [])
        with pytest.raises(ValueError, match="没有菜品信息"):
            BookingPrepService.generate_prep_tasks("book-empty", TENANT_A)


# ═══════════════════════════════════════════════════════════
# 场景 4: 状态流转 — pending → started → done
# ═══════════════════════════════════════════════════════════

class TestTaskStatusTransition:
    """备餐任务应按 pending→started→done 顺序流转，不可跳步或逆转。"""

    def test_full_state_machine(self):
        _register_booking(TENANT_A, "book-001", STORE, _now_plus(2), [
            {"dish_id": "d1", "dish_name": "小炒肉", "quantity": 1},
        ])
        tasks = BookingPrepService.generate_prep_tasks("book-001", TENANT_A)
        assert len(tasks) == 1
        task = tasks[0]

        assert task.status == "pending"

        # pending → started
        started = BookingPrepService.mark_prep_started(task.id, TENANT_A)
        assert started.status == "started"
        assert started.prep_start_at is not None

        # started → done
        done = BookingPrepService.mark_prep_done(task.id, TENANT_A)
        assert done.status == "done"

    def test_cannot_start_done_task(self):
        _register_booking(TENANT_A, "book-002", STORE, _now_plus(2), [
            {"dish_id": "d1", "dish_name": "炒青菜", "quantity": 1},
        ])
        tasks = BookingPrepService.generate_prep_tasks("book-002", TENANT_A)
        task = tasks[0]
        BookingPrepService.mark_prep_started(task.id, TENANT_A)
        BookingPrepService.mark_prep_done(task.id, TENANT_A)

        with pytest.raises(ValueError, match="pending"):
            BookingPrepService.mark_prep_started(task.id, TENANT_A)

    def test_cannot_done_pending_task(self):
        _register_booking(TENANT_A, "book-003", STORE, _now_plus(2), [
            {"dish_id": "d1", "dish_name": "蒸鱼", "quantity": 1},
        ])
        tasks = BookingPrepService.generate_prep_tasks("book-003", TENANT_A)
        task = tasks[0]

        with pytest.raises(ValueError, match="started"):
            BookingPrepService.mark_prep_done(task.id, TENANT_A)


# ═══════════════════════════════════════════════════════════
# 场景 5: 档口分配 — 烤鸭 → 烤制档口
# ═══════════════════════════════════════════════════════════

class TestDeptAssignment:
    """档口应根据菜品名称关键词自动分配，烤鸭应分配到 roast。"""

    def test_roast_duck_assigned_to_roast_dept(self):
        _register_booking(TENANT_A, "book-001", STORE, _now_plus(3), [
            {"dish_id": "d1", "dish_name": "北京烤鸭", "quantity": 2},
        ])
        tasks = BookingPrepService.generate_prep_tasks("book-001", TENANT_A)
        assert tasks[0].dept_id == "roast", f"烤鸭应分配到 roast，实际={tasks[0].dept_id}"

    def test_stir_fry_assigned_to_wok(self):
        _register_booking(TENANT_A, "book-002", STORE, _now_plus(3), [
            {"dish_id": "d2", "dish_name": "小炒肉", "quantity": 1},
        ])
        tasks = BookingPrepService.generate_prep_tasks("book-002", TENANT_A)
        assert tasks[0].dept_id == "wok"

    def test_steam_dish_assigned_to_steam(self):
        _register_booking(TENANT_A, "book-003", STORE, _now_plus(3), [
            {"dish_id": "d3", "dish_name": "清蒸鲈鱼", "quantity": 1},
        ])
        tasks = BookingPrepService.generate_prep_tasks("book-003", TENANT_A)
        assert tasks[0].dept_id == "steam"

    def test_unknown_dish_falls_back_to_wok(self):
        _register_booking(TENANT_A, "book-004", STORE, _now_plus(3), [
            {"dish_id": "d4", "dish_name": "神秘特色菜", "quantity": 1},
        ])
        tasks = BookingPrepService.generate_prep_tasks("book-004", TENANT_A)
        assert tasks[0].dept_id == "wok", "未知菜品应兜底到 wok"

    def test_explicit_dept_id_overrides_auto(self):
        """item 携带 dept_id 时应优先使用，不做关键词匹配。"""
        _register_booking(TENANT_A, "book-005", STORE, _now_plus(3), [
            {"dish_id": "d5", "dish_name": "烤鸭", "quantity": 1, "dept_id": "cold"},
        ])
        tasks = BookingPrepService.generate_prep_tasks("book-005", TENANT_A)
        assert tasks[0].dept_id == "cold", "显式指定的 dept_id 应优先"


# ═══════════════════════════════════════════════════════════
# 场景 6: 距就餐时间排序（最近先显示）
# ═══════════════════════════════════════════════════════════

class TestPendingTasksSortedByDiningTime:
    """待备餐列表应按就餐时间升序排列，最近开餐的排最前。"""

    def test_tasks_sorted_by_dining_time_asc(self):
        # book-late: 4小时后
        _register_booking(TENANT_A, "book-late", STORE, _now_plus(4), [
            {"dish_id": "d1", "dish_name": "炒青菜", "quantity": 1},
        ])
        # book-soon: 1小时后（应排前面）
        _register_booking(TENANT_A, "book-soon", STORE, _now_plus(1), [
            {"dish_id": "d2", "dish_name": "蒸鱼", "quantity": 1},
        ])
        # book-mid: 2小时后
        _register_booking(TENANT_A, "book-mid", STORE, _now_plus(2), [
            {"dish_id": "d3", "dish_name": "红烧肉", "quantity": 1},
        ])

        BookingPrepService.generate_prep_tasks("book-late", TENANT_A)
        BookingPrepService.generate_prep_tasks("book-soon", TENANT_A)
        BookingPrepService.generate_prep_tasks("book-mid", TENANT_A)

        pending = BookingPrepService.get_pending_prep_tasks(STORE, TENANT_A)
        assert len(pending) == 3

        booking_ids_in_order = [t.booking_id for t in pending]
        assert booking_ids_in_order == ["book-soon", "book-mid", "book-late"], (
            f"排序错误: {booking_ids_in_order}"
        )


# ═══════════════════════════════════════════════════════════
# 场景 7: 待备餐列表只含未完成任务
# ═══════════════════════════════════════════════════════════

class TestPendingListExcludesDone:
    """get_pending_prep_tasks 不应返回 done 状态的任务。"""

    def test_done_tasks_not_in_pending_list(self):
        _register_booking(TENANT_A, "book-done", STORE, _now_plus(1), [
            {"dish_id": "d1", "dish_name": "小炒肉", "quantity": 1},
        ])
        _register_booking(TENANT_A, "book-pending", STORE, _now_plus(2), [
            {"dish_id": "d2", "dish_name": "蒸鱼", "quantity": 1},
        ])

        tasks_done_booking = BookingPrepService.generate_prep_tasks("book-done", TENANT_A)
        tasks_pending_booking = BookingPrepService.generate_prep_tasks("book-pending", TENANT_A)

        # 完成 book-done 的所有任务
        for t in tasks_done_booking:
            BookingPrepService.mark_prep_started(t.id, TENANT_A)
            BookingPrepService.mark_prep_done(t.id, TENANT_A)

        pending = BookingPrepService.get_pending_prep_tasks(STORE, TENANT_A)
        pending_ids = {t.booking_id for t in pending}

        assert "book-done" not in pending_ids, "已完成预订的任务不应出现在待备餐列表"
        assert "book-pending" in pending_ids, "未完成预订的任务应出现在待备餐列表"

    def test_started_tasks_included_in_pending(self):
        """started 状态（进行中）的任务应包含在待备餐列表。"""
        _register_booking(TENANT_A, "book-started", STORE, _now_plus(1), [
            {"dish_id": "d1", "dish_name": "红烧肉", "quantity": 1},
        ])
        tasks = BookingPrepService.generate_prep_tasks("book-started", TENANT_A)
        BookingPrepService.mark_prep_started(tasks[0].id, TENANT_A)

        pending = BookingPrepService.get_pending_prep_tasks(STORE, TENANT_A)
        statuses = {t.status for t in pending}
        assert "started" in statuses, "进行中任务应包含在待备餐列表"


# ═══════════════════════════════════════════════════════════
# 场景 8: 租户隔离
# ═══════════════════════════════════════════════════════════

class TestTenantIsolation:
    """不同租户的任务和汇总数据应完全隔离，互不可见。"""

    def test_tasks_isolated_by_tenant(self):
        _register_booking(TENANT_A, "book-a", STORE, _now_plus(2), [
            {"dish_id": "d1", "dish_name": "小炒肉", "quantity": 1},
        ])
        _register_booking(TENANT_B, "book-b", STORE, _now_plus(2), [
            {"dish_id": "d2", "dish_name": "蒸鱼", "quantity": 1},
        ])

        BookingPrepService.generate_prep_tasks("book-a", TENANT_A)
        BookingPrepService.generate_prep_tasks("book-b", TENANT_B)

        tasks_a = BookingPrepService.get_pending_prep_tasks(STORE, TENANT_A)
        tasks_b = BookingPrepService.get_pending_prep_tasks(STORE, TENANT_B)

        booking_ids_a = {t.booking_id for t in tasks_a}
        booking_ids_b = {t.booking_id for t in tasks_b}

        assert "book-a" in booking_ids_a and "book-b" not in booking_ids_a, (
            "租户A不应看到租户B的任务"
        )
        assert "book-b" in booking_ids_b and "book-a" not in booking_ids_b, (
            "租户B不应看到租户A的任务"
        )

    def test_summary_isolated_by_tenant(self):
        _register_booking(TENANT_A, "book-a", STORE, _now_plus(2), [
            {"dish_id": "d1", "dish_name": "小炒肉", "quantity": 1},
        ])

        summary_a = BookingPrepService.get_today_summary(STORE, TENANT_A)
        summary_b = BookingPrepService.get_today_summary(STORE, TENANT_B)

        assert summary_a.today_count == 1
        assert summary_b.today_count == 0, "租户B不应看到租户A的预订数据"

    def test_generate_cannot_access_other_tenant_booking(self):
        """租户A不能生成租户B的预订任务。"""
        _register_booking(TENANT_B, "book-b", STORE, _now_plus(2), [
            {"dish_id": "d1", "dish_name": "炒青菜", "quantity": 1},
        ])
        with pytest.raises(ValueError, match="不存在"):
            BookingPrepService.generate_prep_tasks("book-b", TENANT_A)
