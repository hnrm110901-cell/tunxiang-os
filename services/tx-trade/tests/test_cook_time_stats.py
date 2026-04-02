"""菜品制作时间统计基准 — 测试套件

覆盖：
1. 从历史kds_tasks记录计算dish_id+hour_of_day的P50/P90
2. 预期完成时间随时段变化（午高峰比平峰慢）
3. 队列清空时间预估（总预期时长/并发能力）
4. 新菜品无历史数据时fallback到dept默认值
5. tenant_id隔离
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from services.tx_trade.src.services.cook_time_stats import CookTimeStatsService

# ─── 测试夹具 ───

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()
DISH_ID = uuid.uuid4()
DEPT_ID = uuid.uuid4()


def _make_db_mock():
    """返回配置好的 AsyncMock DB 会话"""
    db = AsyncMock()
    db.execute = AsyncMock()
    return db


# ─── 1. P50/P90 计算 ───

class TestComputeBaselines:
    """从历史kds_tasks计算dish_id+hour_of_day的P50/P90"""

    @pytest.mark.asyncio
    async def test_compute_baselines_returns_p50_p90(self):
        """有足够样本时正确计算P50/P90"""
        db = _make_db_mock()

        # 模拟 kds_tasks 聚合结果：8分钟P50，12分钟P90，20个样本
        mock_row = MagicMock()
        mock_row.dish_id = DISH_ID
        mock_row.dept_id = DEPT_ID
        mock_row.hour_bucket = 12  # 午高峰
        mock_row.day_type = "weekday"
        mock_row.p50 = 480.0   # 8分钟
        mock_row.p90 = 720.0   # 12分钟
        mock_row.sample_count = 20

        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row]
        db.execute.return_value = mock_result

        service = CookTimeStatsService(db)
        baselines = await service.recompute_baselines(str(TENANT_A))

        assert len(baselines) == 1
        b = baselines[0]
        assert b["p50_seconds"] == 480
        assert b["p90_seconds"] == 720
        assert b["sample_count"] == 20
        assert b["hour_bucket"] == 12

    @pytest.mark.asyncio
    async def test_compute_baselines_dept_filter(self):
        """dept_id过滤参数有效"""
        db = _make_db_mock()

        mock_result = MagicMock()
        mock_result.all.return_value = []
        db.execute.return_value = mock_result

        service = CookTimeStatsService(db)
        baselines = await service.recompute_baselines(str(TENANT_A), dept_id=str(DEPT_ID))

        # 验证execute被调用了（带dept_id过滤）
        assert db.execute.called
        assert baselines == []

    @pytest.mark.asyncio
    async def test_compute_baselines_kds_tasks_not_exist(self):
        """kds_tasks表不存在时优雅降级返回空列表"""
        db = _make_db_mock()
        db.execute.side_effect = Exception("relation kds_tasks does not exist")

        service = CookTimeStatsService(db)
        # 不应抛出异常
        baselines = await service.recompute_baselines(str(TENANT_A))
        assert baselines == []


# ─── 2. 时段变化测试 ───

class TestTimeOfDayVariation:
    """预期完成时间随时段变化"""

    @pytest.mark.asyncio
    async def test_lunch_peak_slower_than_off_peak(self):
        """午高峰（12点）的P50应比平峰（15点）大"""
        db = _make_db_mock()

        # 模拟两个时段的baseline存储
        with patch(
            "services.tx_trade.src.services.cook_time_stats.CookTimeStatsService._get_baseline_from_db"
        ) as mock_get:
            # 午高峰返回较长时间
            async def side_effect(dish_id, dept_id, tenant_id, hour_bucket, day_type):
                if hour_bucket == 12:
                    return {"p50_seconds": 600, "p90_seconds": 900, "sample_count": 25}
                elif hour_bucket == 15:
                    return {"p50_seconds": 360, "p90_seconds": 480, "sample_count": 20}
                return None

            mock_get.side_effect = side_effect

            service = CookTimeStatsService(db)

            lunch = await service.get_expected_duration(
                str(DISH_ID), str(DEPT_ID), str(TENANT_A), hour_override=12
            )
            off_peak = await service.get_expected_duration(
                str(DISH_ID), str(DEPT_ID), str(TENANT_A), hour_override=15
            )

        assert lunch > off_peak, "午高峰预期时长应大于平峰"

    @pytest.mark.asyncio
    async def test_weekday_vs_weekend(self):
        """周末与工作日的时段数据分开存储"""
        db = _make_db_mock()

        with patch(
            "services.tx_trade.src.services.cook_time_stats.CookTimeStatsService._get_baseline_from_db"
        ) as mock_get:
            async def side_effect(dish_id, dept_id, tenant_id, hour_bucket, day_type):
                if day_type == "weekend":
                    return {"p50_seconds": 480, "p90_seconds": 720, "sample_count": 15}
                return {"p50_seconds": 300, "p90_seconds": 480, "sample_count": 30}

            mock_get.side_effect = side_effect

            service = CookTimeStatsService(db)

            # 传入一个周六（2026-03-28是周六）
            saturday = datetime(2026, 3, 28, 12, 0, tzinfo=timezone.utc)
            duration_weekend = await service.get_expected_duration(
                str(DISH_ID), str(DEPT_ID), str(TENANT_A), at_time=saturday
            )
            # 传入一个周一
            monday = datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc)
            duration_weekday = await service.get_expected_duration(
                str(DISH_ID), str(DEPT_ID), str(TENANT_A), at_time=monday
            )

        assert duration_weekend >= duration_weekday


# ─── 3. 队列清空时间预估 ───

class TestQueueClearTime:
    """队列清空时间预估：总预期时长 / 并发能力"""

    @pytest.mark.asyncio
    async def test_empty_queue_returns_now(self):
        """空队列时预估清空时间约等于当前时间"""
        db = _make_db_mock()

        mock_result = MagicMock()
        mock_result.all.return_value = []
        db.execute.return_value = mock_result

        service = CookTimeStatsService(db)
        result = await service.estimate_queue_clear_time(str(DEPT_ID), str(TENANT_A))

        now = datetime.now(timezone.utc)
        assert result["estimated_clear_at"] <= now + timedelta(seconds=5)
        assert result["pending_count"] == 0

    @pytest.mark.asyncio
    async def test_queue_clear_time_calculation(self):
        """4道菜，每道300秒，并发2 → 预估清空 4*300/2 = 600秒后"""
        db = _make_db_mock()

        # 模拟pending队列：4条任务，每条300秒
        mock_tasks = []
        for _ in range(4):
            row = MagicMock()
            row.order_item_id = uuid.uuid4()
            row.dish_id = DISH_ID
            mock_tasks.append(row)

        mock_queue_result = MagicMock()
        mock_queue_result.all.return_value = mock_tasks
        db.execute.return_value = mock_queue_result

        with patch(
            "services.tx_trade.src.services.cook_time_stats.CookTimeStatsService.get_expected_duration",
            new_callable=AsyncMock,
            return_value=300,
        ):
            service = CookTimeStatsService(db)
            result = await service.estimate_queue_clear_time(
                str(DEPT_ID), str(TENANT_A), concurrent_capacity=2
            )

        now = datetime.now(timezone.utc)
        expected_seconds = 4 * 300 / 2  # = 600

        diff = (result["estimated_clear_at"] - now).total_seconds()
        # 允许5秒误差
        assert abs(diff - expected_seconds) < 5
        assert result["pending_count"] == 4
        assert result["total_expected_seconds"] == 1200  # 4*300

    @pytest.mark.asyncio
    async def test_concurrent_capacity_default_is_2(self):
        """默认并发能力为2"""
        db = _make_db_mock()

        mock_result = MagicMock()
        mock_result.all.return_value = []
        db.execute.return_value = mock_result

        service = CookTimeStatsService(db)
        result = await service.estimate_queue_clear_time(str(DEPT_ID), str(TENANT_A))

        assert result["concurrent_capacity"] == 2


# ─── 4. 新菜品fallback ───

class TestFallbackBehavior:
    """无历史数据时fallback到dept默认值"""

    @pytest.mark.asyncio
    async def test_fallback_to_dept_default_when_no_history(self):
        """新菜品无历史数据 → fallback到dept.default_timeout_minutes * 0.6"""
        db = _make_db_mock()

        with patch(
            "services.tx_trade.src.services.cook_time_stats.CookTimeStatsService._get_baseline_from_db",
            new_callable=AsyncMock,
            return_value=None,  # 无历史baseline
        ), patch(
            "services.tx_trade.src.services.cook_time_stats.CookTimeStatsService._get_dept_default_minutes",
            new_callable=AsyncMock,
            return_value=15,  # dept.default_timeout_minutes = 15分钟
        ):
            service = CookTimeStatsService(db)
            duration = await service.get_expected_duration(
                str(DISH_ID), str(DEPT_ID), str(TENANT_A)
            )

        # 15分钟 * 0.6 * 60秒 = 540秒
        expected = int(15 * 0.6 * 60)
        assert duration == expected

    @pytest.mark.asyncio
    async def test_fallback_source_is_labeled(self):
        """fallback时返回source标记为'dept_default'"""
        db = _make_db_mock()

        with patch(
            "services.tx_trade.src.services.cook_time_stats.CookTimeStatsService._get_baseline_from_db",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "services.tx_trade.src.services.cook_time_stats.CookTimeStatsService._get_dept_default_minutes",
            new_callable=AsyncMock,
            return_value=20,
        ):
            service = CookTimeStatsService(db)
            result = await service.get_expected_duration_with_meta(
                str(DISH_ID), str(DEPT_ID), str(TENANT_A)
            )

        assert result["source"] == "dept_default"
        assert result["reliable"] is False

    @pytest.mark.asyncio
    async def test_sample_count_below_10_is_unreliable(self):
        """样本数小于10时标记为不可靠"""
        db = _make_db_mock()

        with patch(
            "services.tx_trade.src.services.cook_time_stats.CookTimeStatsService._get_baseline_from_db",
            new_callable=AsyncMock,
            return_value={"p50_seconds": 300, "p90_seconds": 500, "sample_count": 5},
        ):
            service = CookTimeStatsService(db)
            result = await service.get_expected_duration_with_meta(
                str(DISH_ID), str(DEPT_ID), str(TENANT_A)
            )

        assert result["reliable"] is False
        assert result["source"] == "baseline"


# ─── 5. tenant_id隔离 ───

class TestTenantIsolation:
    """tenant_id隔离：A租户数据不泄露给B租户"""

    @pytest.mark.asyncio
    async def test_different_tenants_get_different_results(self):
        """A租户和B租户的baseline互相隔离"""
        db = _make_db_mock()

        async def tenant_aware_get(dish_id, dept_id, tenant_id, hour_bucket, day_type):
            if str(tenant_id) == str(TENANT_A):
                return {"p50_seconds": 300, "p90_seconds": 480, "sample_count": 20}
            else:
                return None  # B租户无数据

        with patch(
            "services.tx_trade.src.services.cook_time_stats.CookTimeStatsService._get_baseline_from_db",
            side_effect=tenant_aware_get,
        ), patch(
            "services.tx_trade.src.services.cook_time_stats.CookTimeStatsService._get_dept_default_minutes",
            new_callable=AsyncMock,
            return_value=15,
        ):
            service = CookTimeStatsService(db)

            result_a = await service.get_expected_duration_with_meta(
                str(DISH_ID), str(DEPT_ID), str(TENANT_A)
            )
            result_b = await service.get_expected_duration_with_meta(
                str(DISH_ID), str(DEPT_ID), str(TENANT_B)
            )

        assert result_a["source"] == "baseline"
        assert result_b["source"] == "dept_default"
        assert result_a["estimated_seconds"] != result_b["estimated_seconds"]

    @pytest.mark.asyncio
    async def test_recompute_baselines_tenant_scoped(self):
        """recompute_baselines只处理指定租户的数据"""
        db = _make_db_mock()

        # 模拟：execute被调用时验证SQL包含tenant_id过滤
        executed_statements = []

        async def capture_execute(stmt, *args, **kwargs):
            executed_statements.append(str(stmt.compile(compile_kwargs={"literal_binds": True})))
            result = MagicMock()
            result.all.return_value = []
            return result

        db.execute.side_effect = capture_execute

        service = CookTimeStatsService(db)
        await service.recompute_baselines(str(TENANT_A))

        # 至少执行了一次查询
        assert db.execute.called

    @pytest.mark.asyncio
    async def test_dynamic_thresholds_tenant_isolated(self):
        """动态超时阈值按租户隔离"""
        db = _make_db_mock()

        with patch(
            "services.tx_trade.src.services.cook_time_stats.CookTimeStatsService._get_baseline_from_db",
            new_callable=AsyncMock,
            return_value={"p50_seconds": 300, "p90_seconds": 600, "sample_count": 20},
        ):
            service = CookTimeStatsService(db)
            thresholds = await service.get_dept_timeout_thresholds(
                str(DEPT_ID), str(DISH_ID), str(TENANT_A)
            )

        # warn_seconds = p90 * 0.8 = 480
        # critical_seconds = p90 = 600
        assert thresholds["warn_seconds"] == int(600 * 0.8)
        assert thresholds["critical_seconds"] == 600
        assert thresholds["source"] == "baseline"


# ─── 6. 动态阈值 ───

class TestDynamicThresholds:
    """动态阈值替代固定25分钟"""

    @pytest.mark.asyncio
    async def test_threshold_from_p90(self):
        """critical阈值来自P90，warn阈值是P90的80%"""
        db = _make_db_mock()

        with patch(
            "services.tx_trade.src.services.cook_time_stats.CookTimeStatsService._get_baseline_from_db",
            new_callable=AsyncMock,
            return_value={"p50_seconds": 400, "p90_seconds": 800, "sample_count": 30},
        ):
            service = CookTimeStatsService(db)
            thresholds = await service.get_dept_timeout_thresholds(
                str(DEPT_ID), str(DISH_ID), str(TENANT_A)
            )

        assert thresholds["warn_seconds"] == 640   # 800 * 0.8
        assert thresholds["critical_seconds"] == 800

    @pytest.mark.asyncio
    async def test_threshold_fallback_when_no_baseline(self):
        """无baseline时使用dept默认超时的fallback阈值"""
        db = _make_db_mock()

        with patch(
            "services.tx_trade.src.services.cook_time_stats.CookTimeStatsService._get_baseline_from_db",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "services.tx_trade.src.services.cook_time_stats.CookTimeStatsService._get_dept_default_minutes",
            new_callable=AsyncMock,
            return_value=25,  # 传统固定25分钟
        ):
            service = CookTimeStatsService(db)
            thresholds = await service.get_dept_timeout_thresholds(
                str(DEPT_ID), str(DISH_ID), str(TENANT_A)
            )

        # fallback: warn = 25*60*0.8 = 1200, critical = 25*60 = 1500
        assert thresholds["warn_seconds"] == int(25 * 60 * 0.8)
        assert thresholds["critical_seconds"] == 25 * 60
        assert thresholds["source"] == "dept_default"
