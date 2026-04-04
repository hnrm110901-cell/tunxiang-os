"""投影器端到端集成测试 — Mock asyncpg，不依赖真实数据库

覆盖范围：
  A. DiscountHealthProjector — 全部事件路径 + _classify_leak_type
  B. SafetyComplianceProjector — 留样/检查/违规/温度
  C. EnergyEfficiencyProjector — 抄表/异常/营收
  D. ProjectorBase — 无 store_id 事件跳过、检查点推进、rebuild 重置
  E. 黑盒流程：_process_backlog 调用链 + checkpoint UPSERT

测试策略：
  - 用 AsyncMock 替换 asyncpg conn.execute / pool.acquire
  - 直接调用 handle() 方法验证 SQL 参数
  - 不依赖 PostgreSQL、Redis 或任何网络资源
"""
from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

# ── 被测模块 ──────────────────────────────────────────────────────────────────

from shared.events.src.projectors.discount_health import (
    DiscountHealthProjector,
    _classify_leak_type,
)
from shared.events.src.projectors.safety_compliance import (
    SafetyComplianceProjector,
    _iso_week_monday,
)
from shared.events.src.projectors.energy_efficiency import EnergyEfficiencyProjector
from shared.events.src.projectors.channel_margin import ChannelMarginProjector
from shared.events.src.projector import ProjectorBase

# ── 测试固定值 ─────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
EVENT_ID = str(uuid.uuid4())
TODAY = datetime(2026, 4, 4, 10, 30, 0, tzinfo=timezone.utc)
TODAY_DATE = TODAY.date()
THIS_MONDAY = TODAY_DATE - timedelta(days=TODAY_DATE.weekday())


def _make_event(event_type: str, payload: dict | None = None, store_id: str | None = None) -> dict:
    """构造最小化事件字典。"""
    return {
        "event_id": EVENT_ID,
        "event_type": event_type,
        "tenant_id": TENANT_ID,
        "store_id": store_id or STORE_ID,
        "occurred_at": TODAY,
        "payload": payload or {},
        "metadata": {},
        "causation_id": None,
    }


def _mock_conn() -> AsyncMock:
    """返回一个支持 await conn.execute(...) 和 async with conn.transaction() 的 mock 连接。"""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(return_value=None)

    # conn.transaction() 需要返回 async context manager
    @asynccontextmanager
    async def _noop_txn():
        yield

    conn.transaction = MagicMock(side_effect=lambda: _noop_txn())
    return conn


# ══════════════════════════════════════════════════════════════════════════════
#  A. DiscountHealthProjector
# ══════════════════════════════════════════════════════════════════════════════


class TestDiscountHealthProjector:

    def setup_method(self):
        self.proj = DiscountHealthProjector(tenant_id=TENANT_ID)

    @pytest.mark.asyncio
    async def test_order_paid_increments_total_orders(self):
        """order.paid 事件应触发两次 execute：UPSERT 初始化行 + UPDATE total_orders + 1。"""
        conn = _mock_conn()
        event = _make_event("order.paid", {"final_amount_fen": 8800})

        await self.proj.handle(event, conn)

        assert conn.execute.call_count == 2
        # 第1次：INSERT ... ON CONFLICT DO NOTHING
        first_sql = conn.execute.call_args_list[0][0][0]
        assert "INSERT INTO mv_discount_health" in first_sql
        # 第2次：UPDATE total_orders
        second_sql = conn.execute.call_args_list[1][0][0]
        assert "total_orders = total_orders + 1" in second_sql

    @pytest.mark.asyncio
    async def test_discount_applied_updates_stats(self):
        """discount.applied 应触发：UPSERT + UPDATE discounted_orders + _recalc_discount_rate。"""
        conn = _mock_conn()
        event = _make_event("discount.applied", {
            "discount_fen": 500,
            "margin_passed": True,
            "approval_id": None,
            "discount_type": "percent_off",
        })

        await self.proj.handle(event, conn)

        # 3次 execute：INSERT + UPDATE discounted_orders + UPDATE discount_rate
        assert conn.execute.call_count == 3
        sqls = [c[0][0] for c in conn.execute.call_args_list]
        assert any("discounted_orders" in s for s in sqls)
        assert any("discount_rate" in s for s in sqls)

    @pytest.mark.asyncio
    async def test_discount_applied_unauthorized_increments_count(self):
        """无授权折扣（approval_id=None）应使 unauthorized_count + 1。"""
        conn = _mock_conn()
        event = _make_event("discount.applied", {
            "discount_fen": 200,
            "margin_passed": True,
            "approval_id": None,
        })

        await self.proj.handle(event, conn)

        # 找 UPDATE discounted_orders 的调用
        update_call = None
        for c in conn.execute.call_args_list:
            if "discounted_orders" in c[0][0]:
                update_call = c
                break
        assert update_call is not None
        # 第5个参数（$5）是 unauthorized_count_delta = 0 if has_approval else 1
        args = update_call[0]
        # args: (sql, tenant_id, store_id, stat_date, discount_fen, unauthorized_delta, threshold_delta, leak_json, event_id)
        assert args[5] == 1  # unauthorized

    @pytest.mark.asyncio
    async def test_discount_authorized_decrements_unauthorized(self):
        """discount.authorized 应触发 unauthorized_count - 1 更新。"""
        conn = _mock_conn()
        event = _make_event("discount.authorized", {"approval_id": str(uuid.uuid4())})

        await self.proj.handle(event, conn)

        sqls = [c[0][0] for c in conn.execute.call_args_list]
        assert any("unauthorized_count - 1" in s for s in sqls)

    @pytest.mark.asyncio
    async def test_discount_threshold_exceeded_increments_breaches(self):
        conn = _mock_conn()
        event = _make_event("discount.threshold_exceeded", {})

        await self.proj.handle(event, conn)

        sqls = [c[0][0] for c in conn.execute.call_args_list]
        assert any("threshold_breaches = threshold_breaches + 1" in s for s in sqls)

    @pytest.mark.asyncio
    async def test_no_store_id_skips_event(self):
        """缺少 store_id 的事件不应触发任何 execute。"""
        conn = _mock_conn()
        event = _make_event("order.paid", store_id=None)
        event["store_id"] = None

        await self.proj.handle(event, conn)

        conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_string_occurred_at_parsed(self):
        """occurred_at 为 ISO 字符串时应能正常解析。"""
        conn = _mock_conn()
        event = _make_event("order.paid")
        event["occurred_at"] = "2026-04-04T10:30:00+00:00"

        await self.proj.handle(event, conn)

        assert conn.execute.call_count == 2  # UPSERT + UPDATE


# ══════════════════════════════════════════════════════════════════════════════
#  A2. _classify_leak_type
# ══════════════════════════════════════════════════════════════════════════════


class TestClassifyLeakType:

    def test_no_approval_no_margin(self):
        payload = {"approval_id": None, "margin_passed": False}
        assert _classify_leak_type(payload) == "unauthorized_margin_breach"

    def test_no_approval_margin_ok(self):
        payload = {"approval_id": None, "margin_passed": True}
        assert _classify_leak_type(payload) == "unauthorized_discount"

    def test_with_approval_margin_breach(self):
        payload = {"approval_id": "app-001", "margin_passed": False}
        assert _classify_leak_type(payload) == "authorized_margin_breach"

    def test_free_item(self):
        payload = {"approval_id": "app-001", "margin_passed": True, "discount_type": "free_item"}
        assert _classify_leak_type(payload) == "free_item"

    def test_percent_off(self):
        payload = {"approval_id": "app-001", "margin_passed": True, "discount_type": "percent_off"}
        assert _classify_leak_type(payload) == "percent_discount"

    def test_normal_discount(self):
        payload = {"approval_id": "app-001", "margin_passed": True, "discount_type": "fixed_amount"}
        assert _classify_leak_type(payload) == "normal_discount"


# ══════════════════════════════════════════════════════════════════════════════
#  B. SafetyComplianceProjector
# ══════════════════════════════════════════════════════════════════════════════


class TestSafetyComplianceProjector:

    def setup_method(self):
        self.proj = SafetyComplianceProjector(tenant_id=TENANT_ID)

    @pytest.mark.asyncio
    async def test_sample_logged_increments_count(self):
        """safety.sample_logged 应触发 sample_logged_count + 1。"""
        conn = _mock_conn()
        event = _make_event("safety.sample_logged", {
            "sample_id": str(uuid.uuid4()),
            "dish_name": "红烧肉",
            "sample_weight_g": 130.0,
            "meal_period": "lunch",
        })

        await self.proj.handle(event, conn)

        sqls = [c[0][0] for c in conn.execute.call_args_list]
        assert any("sample_logged_count" in s for s in sqls)

    @pytest.mark.asyncio
    async def test_inspection_done_updates_score(self):
        """safety.inspection_done 应触发 inspection_done + 1 和 compliance_score 更新。"""
        conn = _mock_conn()
        event = _make_event("safety.inspection_done", {
            "inspection_id": str(uuid.uuid4()),
            "total_items": 20,
            "passed_items": 18,
            "overall_score": 90.0,
            "violations": [],
        })

        await self.proj.handle(event, conn)

        sqls = [c[0][0] for c in conn.execute.call_args_list]
        # 列名是 inspection_done（不是 inspection_count）
        assert any("inspection_done" in s for s in sqls)

    @pytest.mark.asyncio
    async def test_violation_found_increments_count(self):
        """safety.violation_found 应触发 violation_count + 1。"""
        conn = _mock_conn()
        event = _make_event("safety.violation_found", {
            "violation_id": str(uuid.uuid4()),
            "severity": "major",
            "violation_type": "expired_ingredient",
        })

        await self.proj.handle(event, conn)

        sqls = [c[0][0] for c in conn.execute.call_args_list]
        assert any("violation_count" in s for s in sqls)

    @pytest.mark.asyncio
    async def test_temperature_recorded_non_compliant(self):
        """safety.temperature_recorded with anomaly 应记录异常。"""
        conn = _mock_conn()
        event = _make_event("safety.temperature_recorded", {
            "record_id": str(uuid.uuid4()),
            "location": "refrigerator",
            "temp_celsius": 12.0,
            "compliant": False,
        })

        await self.proj.handle(event, conn)

        # 至少执行了 UPSERT
        assert conn.execute.call_count >= 1

    @pytest.mark.asyncio
    async def test_no_store_id_skips(self):
        conn = _mock_conn()
        event = _make_event("safety.sample_logged")
        event["store_id"] = None

        await self.proj.handle(event, conn)

        conn.execute.assert_not_called()

    def test_iso_week_monday(self):
        """_iso_week_monday 应返回该日期所在周的周一。"""
        # 2026-04-04 是周六，对应周一是 2026-03-30
        dt = datetime(2026, 4, 4, tzinfo=timezone.utc)
        monday = _iso_week_monday(dt)
        assert monday == date(2026, 3, 30)
        assert monday.weekday() == 0  # 0 = 周一


# ══════════════════════════════════════════════════════════════════════════════
#  C. EnergyEfficiencyProjector
# ══════════════════════════════════════════════════════════════════════════════


class TestEnergyEfficiencyProjector:

    def setup_method(self):
        self.proj = EnergyEfficiencyProjector(tenant_id=TENANT_ID)

    @pytest.mark.asyncio
    async def test_reading_captured_accumulates_electricity(self):
        """energy.reading_captured 应累加 electricity_kwh。"""
        conn = _mock_conn()
        event = _make_event("energy.reading_captured", {
            "meter_type": "electricity",
            "electricity_kwh": 15.5,
            "cost_fen": 1200,
        })

        await self.proj.handle(event, conn)

        sqls = [c[0][0] for c in conn.execute.call_args_list]
        assert any("electricity_kwh" in s for s in sqls)
        # 最后一次应是 _recalc_ratio
        assert any("energy_revenue_ratio" in s for s in sqls)

    @pytest.mark.asyncio
    async def test_anomaly_detected_increments_count(self):
        """energy.anomaly_detected 应触发 anomaly_count + 1。"""
        conn = _mock_conn()
        event = _make_event("energy.anomaly_detected", {
            "anomaly_type": "off_hours_usage",
            "value": 5.0,
            "is_off_hours": True,
        })

        await self.proj.handle(event, conn)

        sqls = [c[0][0] for c in conn.execute.call_args_list]
        # SQL 有缩进空白：'anomaly_count      = anomaly_count + 1'
        assert any("anomaly_count" in s and "anomaly_count + 1" in s for s in sqls)

    @pytest.mark.asyncio
    async def test_order_paid_accumulates_revenue(self):
        """order.paid 应累加 revenue_fen，并触发 _recalc_ratio。"""
        conn = _mock_conn()
        event = _make_event("order.paid", {"final_amount_fen": 12800})

        await self.proj.handle(event, conn)

        sqls = [c[0][0] for c in conn.execute.call_args_list]
        # SQL 有缩进空白：'revenue_fen   = revenue_fen + $4'
        assert any("revenue_fen" in s and "revenue_fen + $4" in s for s in sqls)
        assert any("energy_revenue_ratio" in s for s in sqls)

    @pytest.mark.asyncio
    async def test_gas_reading_uses_gas_field(self):
        """燃气表读数应累加 gas_m3，不影响 electricity_kwh。"""
        conn = _mock_conn()
        event = _make_event("energy.reading_captured", {
            "meter_type": "gas",
            "gas_m3": 3.2,
            "electricity_kwh": 0,
        })

        await self.proj.handle(event, conn)

        # UPDATE 调用的参数中 gas 值应非零
        update_call = None
        for c in conn.execute.call_args_list:
            if "gas_m3" in c[0][0]:
                update_call = c
                break
        assert update_call is not None
        args = update_call[0]
        # args: (sql, tenant_id, store_id, stat_date, electricity, gas, water, cost_fen, event_id)
        assert args[5] == 3.2   # gas_m3 位置

    @pytest.mark.asyncio
    async def test_no_store_id_skips(self):
        conn = _mock_conn()
        event = _make_event("energy.reading_captured")
        event["store_id"] = None

        await self.proj.handle(event, conn)

        conn.execute.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
#  D. ProjectorBase — 通用逻辑
# ══════════════════════════════════════════════════════════════════════════════


class _ConcreteProjector(ProjectorBase):
    """最简投影器子类，用于测试基类行为。"""
    name = "test_projector"
    event_types = {"order.paid"}
    handle_calls: list = []

    async def handle(self, event: dict, conn: object) -> None:
        self.handle_calls.append(event["event_type"])


class TestProjectorBase:

    @pytest.mark.asyncio
    async def test_process_backlog_calls_handle_for_each_event(self):
        """_process_backlog 应对每条事件调用 handle()，并更新 checkpoint。"""
        proj = _ConcreteProjector(tenant_id=TENANT_ID)
        proj.handle_calls = []

        fake_event_row = {
            "event_id": uuid.uuid4(),
            "event_type": "order.paid",
            "tenant_id": TENANT_ID,
            "store_id": STORE_ID,
            "occurred_at": TODAY,
            "payload": json.dumps({"final_amount_fen": 1000}),
            "metadata": json.dumps({}),
            "causation_id": None,
        }

        # _fetch_next_batch 用单独的 acquire，_process_backlog 内处理也用 acquire
        # 第一次 fetch 返回1条事件，第二次（下一轮）返回空 → 结束循环
        fetch_results = [[fake_event_row], []]
        fetch_call_count = 0

        mock_conn = _mock_conn()

        def _fetch_side_effect(*args, **kwargs):
            nonlocal fetch_call_count
            result = fetch_results[min(fetch_call_count, len(fetch_results) - 1)]
            fetch_call_count += 1
            return result

        mock_conn.fetch = AsyncMock(side_effect=_fetch_side_effect)

        @asynccontextmanager
        async def _acquire():
            yield mock_conn

        mock_pool = MagicMock()
        mock_pool.acquire = _acquire

        await proj._process_backlog(pool=mock_pool)

        assert proj.handle_calls == ["order.paid"]
        # 应有一次 INSERT INTO projector_checkpoints
        checkpoint_sqls = [
            c[0][0] for c in mock_conn.execute.call_args_list
            if "projector_checkpoints" in c[0][0]
        ]
        assert len(checkpoint_sqls) >= 1

    @pytest.mark.asyncio
    async def test_rebuild_resets_checkpoint(self):
        """rebuild() 应先将 projector_checkpoints.last_event_id 置 NULL，再重播。"""
        proj = _ConcreteProjector(tenant_id=TENANT_ID)
        proj.handle_calls = []

        mock_conn = _mock_conn()
        mock_conn.fetch = AsyncMock(return_value=[])  # 无积压事件
        mock_conn.fetchrow = AsyncMock(return_value=None)

        @asynccontextmanager
        async def _acquire():
            yield mock_conn

        mock_pool = MagicMock()
        mock_pool.acquire = _acquire
        mock_pool.close = AsyncMock()

        # asyncpg 在函数体内 import，需通过 sys.modules 注入 fake 模块
        import sys
        import types
        fake_asyncpg = types.ModuleType("asyncpg")
        fake_asyncpg.create_pool = AsyncMock(return_value=mock_pool)  # type: ignore[attr-defined]

        original = sys.modules.get("asyncpg")
        sys.modules["asyncpg"] = fake_asyncpg
        try:
            await proj.rebuild()
        finally:
            if original is None:
                sys.modules.pop("asyncpg", None)
            else:
                sys.modules["asyncpg"] = original

        # 检查点 RESET 调用：INSERT ... last_rebuilt_at = NOW()
        reset_sqls = [
            c[0][0] for c in mock_conn.execute.call_args_list
            if "last_rebuilt_at" in c[0][0]
        ]
        assert len(reset_sqls) >= 1

    def test_projector_name_uniqueness(self):
        """所有已注册投影器的 name 必须不重复。"""
        from shared.events.src.projectors import ALL_PROJECTORS
        names = [p.name for p in ALL_PROJECTORS]
        assert len(names) == len(set(names)), f"投影器名称重复: {names}"

    def test_all_projectors_have_event_types(self):
        """每个投影器必须声明至少一个关注事件类型。"""
        from shared.events.src.projectors import ALL_PROJECTORS
        for projector_cls in ALL_PROJECTORS:
            assert projector_cls.event_types, (
                f"{projector_cls.name} 未声明 event_types"
            )

    def test_all_projectors_instantiable(self):
        """所有投影器类应能以 tenant_id 正常实例化。"""
        from shared.events.src.projectors import ALL_PROJECTORS
        for projector_cls in ALL_PROJECTORS:
            instance = projector_cls(tenant_id=TENANT_ID)
            assert instance.name
            assert str(instance.tenant_id) == TENANT_ID


# ══════════════════════════════════════════════════════════════════════════════
#  E. 事件类型覆盖率验证
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
#  F. PublicOpinionProjector（Round 65-66 新增模块）
# ══════════════════════════════════════════════════════════════════════════════


from shared.events.src.projectors.public_opinion import PublicOpinionProjector


class TestPublicOpinionProjector:
    """测试舆情投影器的各事件路径（不连真实数据库）。"""

    def setup_method(self):
        self.proj = PublicOpinionProjector(tenant_id=TENANT_ID)

    @pytest.mark.asyncio
    async def test_handle_positive_mention_increments_positive_count(self):
        """opinion.mention_captured (positive) 应 UPSERT 统计行并增加 positive_count。"""
        conn = _mock_conn()
        event = _make_event("opinion.mention_captured", {
            "platform": "dianping",
            "sentiment": "positive",
            "rating": 5.0,
            "content": "服务很好！",
        })

        await self.proj.handle(event, conn)

        sqls = [c[0][0] for c in conn.execute.call_args_list]
        # 第1次：INSERT INTO mv_public_opinion ... ON CONFLICT DO NOTHING
        assert any("INSERT INTO mv_public_opinion" in s for s in sqls)
        # 第2次：UPDATE ... positive_count + 1
        assert any("positive_count" in s for s in sqls)

    @pytest.mark.asyncio
    async def test_handle_negative_mention_increments_negative_count(self):
        """opinion.mention_captured (negative) 应增加 negative_count。"""
        conn = _mock_conn()
        event = _make_event("opinion.mention_captured", {
            "platform": "meituan",
            "sentiment": "negative",
            "rating": 1.0,
            "content": "等太久了",
        })

        await self.proj.handle(event, conn)

        sqls = [c[0][0] for c in conn.execute.call_args_list]
        assert any("negative_count" in s for s in sqls)

    @pytest.mark.asyncio
    async def test_handle_neutral_mention_increments_neutral_count(self):
        """opinion.mention_captured (neutral) 应增加 neutral_count。"""
        conn = _mock_conn()
        event = _make_event("opinion.mention_captured", {
            "platform": "weibo",
            "sentiment": "neutral",
            "content": "还行",
        })

        await self.proj.handle(event, conn)

        sqls = [c[0][0] for c in conn.execute.call_args_list]
        assert any("neutral_count" in s for s in sqls)

    @pytest.mark.asyncio
    async def test_handle_resolved_updates_mention(self):
        """opinion.resolved 应更新 public_opinion_mentions.is_resolved=true。"""
        conn = _mock_conn()
        mention_id = str(uuid.uuid4())
        event = _make_event("opinion.resolved", {
            "mention_id": mention_id,
            "resolution_note": "已联系顾客致歉",
        })

        await self.proj.handle(event, conn)

        sqls = [c[0][0] for c in conn.execute.call_args_list]
        assert any("is_resolved" in s for s in sqls)
        assert any("public_opinion_mentions" in s for s in sqls)

    @pytest.mark.asyncio
    async def test_handle_resolved_no_mention_id_skips(self):
        """opinion.resolved 缺少 mention_id 时应静默跳过（不执行 UPDATE）。"""
        conn = _mock_conn()
        event = _make_event("opinion.resolved", {
            "resolution_note": "已处理",
            # 缺少 mention_id
        })

        await self.proj.handle(event, conn)

        # 不应执行任何 UPDATE public_opinion_mentions 操作
        sqls = [c[0][0] for c in conn.execute.call_args_list]
        assert not any("public_opinion_mentions" in s for s in sqls)

    @pytest.mark.asyncio
    async def test_missing_store_id_skips_without_error(self):
        """缺少 store_id 的事件应静默跳过，不触发任何数据库操作。"""
        conn = _mock_conn()
        event = _make_event("opinion.mention_captured", {"sentiment": "positive"})
        event["store_id"] = None

        await self.proj.handle(event, conn)

        conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_mention_with_rating_triggers_avg_recalc(self):
        """带 rating 的 mention 应触发 avg_rating 重新计算（额外的 UPDATE）。"""
        conn = _mock_conn()
        event = _make_event("opinion.mention_captured", {
            "platform": "dianping",
            "sentiment": "positive",
            "rating": 4.5,
            "sentiment_score": 0.85,
        })

        await self.proj.handle(event, conn)

        # 至少 3 次：INSERT + UPDATE sentiment_count + UPDATE avg_rating + UPDATE avg_sentiment_score
        assert conn.execute.call_count >= 3


# ══════════════════════════════════════════════════════════════════════════════
#  E. 事件类型覆盖率验证
# ══════════════════════════════════════════════════════════════════════════════


class TestEventTypeCoverage:
    """验证投影器事件类型覆盖了主要业务域。"""

    def test_discount_projector_covers_core_events(self):
        assert "discount.applied" in DiscountHealthProjector.event_types
        assert "order.paid" in DiscountHealthProjector.event_types

    def test_safety_projector_covers_phase4_events(self):
        assert "safety.sample_logged" in SafetyComplianceProjector.event_types
        assert "safety.inspection_done" in SafetyComplianceProjector.event_types
        assert "safety.violation_found" in SafetyComplianceProjector.event_types
        assert "safety.temperature_recorded" in SafetyComplianceProjector.event_types

    def test_energy_projector_covers_iot_events(self):
        assert "energy.reading_captured" in EnergyEfficiencyProjector.event_types
        assert "energy.anomaly_detected" in EnergyEfficiencyProjector.event_types

    def test_channel_projector_registered(self):
        from shared.events.src.projectors import ALL_PROJECTORS
        names = {p.name for p in ALL_PROJECTORS}
        assert "channel_margin" in names

    def test_settlement_projector_registered(self):
        from shared.events.src.projectors import ALL_PROJECTORS
        names = {p.name for p in ALL_PROJECTORS}
        assert "daily_settlement" in names

    def test_public_opinion_projector_covers_events(self):
        assert "opinion.mention_captured" in PublicOpinionProjector.event_types
        assert "opinion.resolved" in PublicOpinionProjector.event_types

    def test_opinion_event_type_enum_values(self):
        """OpinionEventType 枚举值与投影器 event_types 字符串完全吻合。"""
        from shared.events.src.event_types import OpinionEventType
        assert OpinionEventType.MENTION_CAPTURED.value == "opinion.mention_captured"
        assert OpinionEventType.RESOLVED.value == "opinion.resolved"
        # 枚举值应在投影器中能找到
        assert OpinionEventType.MENTION_CAPTURED.value in PublicOpinionProjector.event_types
        assert OpinionEventType.RESOLVED.value in PublicOpinionProjector.event_types

    def test_channel_commission_calc_event_type_exists(self):
        """CHANNEL.COMMISSION_CALC 事件类型在 ChannelEventType 中已注册。"""
        from shared.events.src.event_types import ChannelEventType
        assert ChannelEventType.COMMISSION_CALC.value == "channel.commission_calc"
        assert "channel.commission_calc" in ChannelMarginProjector.event_types
