"""
DemandPredictor 单元测试

覆盖：
  - DemandPrediction.confidence（纯函数）
  - DemandPredictor.scan_upcoming_visitors：
      - 返回候选列表
      - 正确过滤 horizon_days
      - DB 异常返回空列表
      - SQL 参数正确传递
  - trigger_demand_predictions Beat 计划已注册
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("APP_ENV", "test")

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.demand_predictor import DemandPrediction, DemandPredictor


# ════════════════════════════════════════════════════════════════════════════════
# DemandPrediction.confidence（纯函数）
# ════════════════════════════════════════════════════════════════════════════════


class TestDemandPredictionConfidence:
    def _make(self, order_count: int) -> DemandPrediction:
        return DemandPrediction(
            customer_id="C001",
            store_id="S001",
            wechat_openid=None,
            avg_interval_days=7.0,
            recency_days=5,
            days_until_visit=2.0,
            order_count=order_count,
        )

    def test_minimum_floor_at_03(self):
        """2 次消费 → base=0.2 → floor 到 0.3。"""
        assert self._make(2).confidence == 0.3

    def test_linear_growth(self):
        """5 次消费 → base=0.5。"""
        assert self._make(5).confidence == 0.5

    def test_max_cap_at_10(self):
        """10 次消费 → base=1.0。"""
        assert self._make(10).confidence == 1.0

    def test_over_10_still_capped(self):
        """20 次消费 → 仍然 1.0。"""
        assert self._make(20).confidence == 1.0


# ════════════════════════════════════════════════════════════════════════════════
# DemandPredictor.scan_upcoming_visitors
# ════════════════════════════════════════════════════════════════════════════════


def _make_db_row(
    customer_id="C001",
    store_id="S001",
    wechat_openid="wx_001",
    order_count=5,
    avg_interval_days=7.0,
    recency_days=6,
    days_until_visit=1.0,
):
    """Helper: create a mock DB row."""
    row = MagicMock()
    values = [customer_id, store_id, wechat_openid, order_count,
              avg_interval_days, recency_days, days_until_visit]
    row.__getitem__ = lambda self, i: values[i]
    return row


class TestScanUpcomingVisitors:
    @pytest.mark.asyncio
    async def test_returns_predictions_for_candidates(self):
        """DB 返回 2 行 → 返回 2 个 DemandPrediction。"""
        rows = [
            _make_db_row("C001", "S001", "wx_1", 5, 7.0, 6, 1.0),
            _make_db_row("C002", "S001", "wx_2", 8, 14.0, 13, 1.0),
        ]
        db = AsyncMock()
        db.execute.return_value.fetchall.return_value = rows

        predictor = DemandPredictor()
        result = await predictor.scan_upcoming_visitors("S001", db)

        assert len(result) == 2
        assert result[0].customer_id == "C001"
        assert result[1].customer_id == "C002"
        assert result[0].days_until_visit == 1.0
        assert result[1].avg_interval_days == 14.0

    @pytest.mark.asyncio
    async def test_returns_empty_on_no_candidates(self):
        """DB 返回空 → 返回空列表。"""
        db = AsyncMock()
        db.execute.return_value.fetchall.return_value = []

        predictor = DemandPredictor()
        result = await predictor.scan_upcoming_visitors("S001", db)

        assert result == []

    @pytest.mark.asyncio
    async def test_db_error_returns_empty_list(self):
        """DB 抛异常 → 静默返回空列表，不抛出。"""
        db = AsyncMock()
        db.execute.side_effect = Exception("connection timeout")

        predictor = DemandPredictor()
        result = await predictor.scan_upcoming_visitors("S001", db)

        assert result == []

    @pytest.mark.asyncio
    async def test_passes_store_id_and_horizon_to_sql(self):
        """store_id 和 horizon_days 通过参数化 SQL 传递。"""
        db = AsyncMock()
        db.execute.return_value.fetchall.return_value = []

        predictor = DemandPredictor()
        await predictor.scan_upcoming_visitors("S999", db, horizon_days=7)

        call_args = db.execute.call_args
        params = call_args.args[1]  # 第二个位置参数是 SQL 绑定参数
        assert params["store_id"] == "S999"
        assert params["horizon_days"] == 7

    @pytest.mark.asyncio
    async def test_default_horizon_is_3(self):
        """默认 horizon_days=3。"""
        db = AsyncMock()
        db.execute.return_value.fetchall.return_value = []

        predictor = DemandPredictor()
        await predictor.scan_upcoming_visitors("S001", db)

        params = db.execute.call_args.args[1]
        assert params["horizon_days"] == 3

    @pytest.mark.asyncio
    async def test_wechat_openid_can_be_none(self):
        """wechat_openid 为 None 时正常处理。"""
        rows = [_make_db_row("C001", "S001", None, 3, 5.0, 4, 1.0)]
        db = AsyncMock()
        db.execute.return_value.fetchall.return_value = rows

        predictor = DemandPredictor()
        result = await predictor.scan_upcoming_visitors("S001", db)

        assert len(result) == 1
        assert result[0].wechat_openid is None

    @pytest.mark.asyncio
    async def test_order_count_parsed_as_int(self):
        """order_count 字段转为 int（DB 可能返回 Decimal）。"""
        row = MagicMock()
        # 模拟 Decimal / float 类型
        row.__getitem__ = lambda self, i: [
            "C001", "S001", "wx_1", 5.0, 7.5, 6, 1.5
        ][i]
        db = AsyncMock()
        db.execute.return_value.fetchall.return_value = [row]

        predictor = DemandPredictor()
        result = await predictor.scan_upcoming_visitors("S001", db)

        assert isinstance(result[0].order_count, int)
        assert result[0].order_count == 5


# ════════════════════════════════════════════════════════════════════════════════
# Beat Schedule 验证
# ════════════════════════════════════════════════════════════════════════════════


class TestBeatSchedule:
    def test_trigger_demand_predictions_registered(self):
        """trigger-demand-predictions 已注册到 Beat 调度。"""
        with patch("src.core.config.settings"):
            from src.core.celery_app import celery_app

        schedule = celery_app.conf.beat_schedule
        assert "trigger-demand-predictions" in schedule
        entry = schedule["trigger-demand-predictions"]
        assert entry["task"] == "src.core.celery_tasks.trigger_demand_predictions"
        assert entry["options"]["queue"] == "default"
