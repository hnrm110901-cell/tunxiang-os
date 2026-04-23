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

import json
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.events.src.projector import ProjectorBase
from shared.events.src.projectors.channel_margin import ChannelMarginProjector

# ── 被测模块 ──────────────────────────────────────────────────────────────────
from shared.events.src.projectors.discount_health import (
    DiscountHealthProjector,
    _classify_leak_type,
)
from shared.events.src.projectors.energy_efficiency import EnergyEfficiencyProjector
from shared.events.src.projectors.safety_compliance import (
    SafetyComplianceProjector,
    _iso_week_monday,
)

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
        event = _make_event(
            "discount.applied",
            {
                "discount_fen": 500,
                "margin_passed": True,
                "approval_id": None,
                "discount_type": "percent_off",
            },
        )

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
        event = _make_event(
            "discount.applied",
            {
                "discount_fen": 200,
                "margin_passed": True,
                "approval_id": None,
            },
        )

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
        event = _make_event(
            "safety.sample_logged",
            {
                "sample_id": str(uuid.uuid4()),
                "dish_name": "红烧肉",
                "sample_weight_g": 130.0,
                "meal_period": "lunch",
            },
        )

        await self.proj.handle(event, conn)

        sqls = [c[0][0] for c in conn.execute.call_args_list]
        assert any("sample_logged_count" in s for s in sqls)

    @pytest.mark.asyncio
    async def test_inspection_done_updates_score(self):
        """safety.inspection_done 应触发 inspection_done + 1 和 compliance_score 更新。"""
        conn = _mock_conn()
        event = _make_event(
            "safety.inspection_done",
            {
                "inspection_id": str(uuid.uuid4()),
                "total_items": 20,
                "passed_items": 18,
                "overall_score": 90.0,
                "violations": [],
            },
        )

        await self.proj.handle(event, conn)

        sqls = [c[0][0] for c in conn.execute.call_args_list]
        # 列名是 inspection_done（不是 inspection_count）
        assert any("inspection_done" in s for s in sqls)

    @pytest.mark.asyncio
    async def test_violation_found_increments_count(self):
        """safety.violation_found 应触发 violation_count + 1。"""
        conn = _mock_conn()
        event = _make_event(
            "safety.violation_found",
            {
                "violation_id": str(uuid.uuid4()),
                "severity": "major",
                "violation_type": "expired_ingredient",
            },
        )

        await self.proj.handle(event, conn)

        sqls = [c[0][0] for c in conn.execute.call_args_list]
        assert any("violation_count" in s for s in sqls)

    @pytest.mark.asyncio
    async def test_temperature_recorded_non_compliant(self):
        """safety.temperature_recorded with anomaly 应记录异常。"""
        conn = _mock_conn()
        event = _make_event(
            "safety.temperature_recorded",
            {
                "record_id": str(uuid.uuid4()),
                "location": "refrigerator",
                "temp_celsius": 12.0,
                "compliant": False,
            },
        )

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

    @pytest.mark.asyncio
    async def test_safety_projector_handles_haccp_completed(self):
        """safety.haccp_check_completed 应触发 UPSERT 初始化行
        + UPDATE haccp_total_checks/haccp_passed_checks/haccp_pass_rate。
        overall_passed=True 时 pass_delta=1，critical_failures=0。
        """
        conn = _mock_conn()
        event = _make_event(
            "safety.haccp_check_completed",
            {
                "check_id": str(uuid.uuid4()),
                "overall_passed": True,
                "critical_failures": 0,
                "control_points_checked": 12,
                "control_points_passed": 12,
            },
        )

        await self.proj.handle(event, conn)

        # 2次 execute：INSERT ON CONFLICT DO NOTHING + HACCP UPDATE
        assert conn.execute.call_count == 2

        sqls = [c[0][0] for c in conn.execute.call_args_list]
        # 第1次：行初始化 UPSERT
        assert any("INSERT INTO mv_safety_compliance" in s for s in sqls)
        # 第2次：HACCP 合格率更新，包含关键字段
        assert any("haccp_total_checks" in s for s in sqls)
        assert any("haccp_passed_checks" in s for s in sqls)
        assert any("haccp_pass_rate" in s for s in sqls)

        # 验证传入参数：pass_delta=1，critical_failures=0
        update_call = conn.execute.call_args_list[1]
        args = update_call[0]
        # args: (sql, tenant_id, store_id, stat_week, pass_delta, critical_failures, event_id)
        assert args[4] == 1  # pass_delta（overall_passed=True）
        assert args[5] == 0  # critical_failures

    @pytest.mark.asyncio
    async def test_safety_projector_handles_haccp_critical(self):
        """safety.haccp_critical_failure 应触发 UPSERT 初始化行
        + UPDATE haccp_critical_failures / haccp_critical_alert_count。
        passed_checks 不递增（本次未通过）。
        """
        conn = _mock_conn()
        event = _make_event(
            "safety.haccp_critical_failure",
            {
                "check_id": str(uuid.uuid4()),
                "control_point": "冷链温度",
                "critical_failures": 2,
                "corrective_action_required": True,
            },
        )

        await self.proj.handle(event, conn)

        # 2次 execute：INSERT ON CONFLICT DO NOTHING + critical UPDATE
        assert conn.execute.call_count == 2

        sqls = [c[0][0] for c in conn.execute.call_args_list]
        assert any("INSERT INTO mv_safety_compliance" in s for s in sqls)
        # critical UPDATE 包含关键字段
        assert any("haccp_critical_failures" in s for s in sqls)
        assert any("haccp_critical_alert_count" in s for s in sqls)
        # haccp_passed_checks 不递增（不加分）——SET 子句中不含 "haccp_passed_checks +"
        update_sql = conn.execute.call_args_list[1][0][0]
        assert "haccp_passed_checks      =" not in update_sql
        assert "haccp_passed_checks =" not in update_sql

        # 验证传入参数：critical_failures=2
        update_call = conn.execute.call_args_list[1]
        args = update_call[0]
        # args: (sql, tenant_id, store_id, stat_week, critical_failures, event_id)
        assert args[4] == 2  # critical_failures 来自 payload


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
        event = _make_event(
            "energy.reading_captured",
            {
                "meter_type": "electricity",
                "electricity_kwh": 15.5,
                "cost_fen": 1200,
            },
        )

        await self.proj.handle(event, conn)

        sqls = [c[0][0] for c in conn.execute.call_args_list]
        assert any("electricity_kwh" in s for s in sqls)
        # 最后一次应是 _recalc_ratio
        assert any("energy_revenue_ratio" in s for s in sqls)

    @pytest.mark.asyncio
    async def test_anomaly_detected_increments_count(self):
        """energy.anomaly_detected 应触发 anomaly_count + 1。"""
        conn = _mock_conn()
        event = _make_event(
            "energy.anomaly_detected",
            {
                "anomaly_type": "off_hours_usage",
                "value": 5.0,
                "is_off_hours": True,
            },
        )

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
        event = _make_event(
            "energy.reading_captured",
            {
                "meter_type": "gas",
                "gas_m3": 3.2,
                "electricity_kwh": 0,
            },
        )

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
        assert args[5] == 3.2  # gas_m3 位置

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
        checkpoint_sqls = [c[0][0] for c in mock_conn.execute.call_args_list if "projector_checkpoints" in c[0][0]]
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
        reset_sqls = [c[0][0] for c in mock_conn.execute.call_args_list if "last_rebuilt_at" in c[0][0]]
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
            assert projector_cls.event_types, f"{projector_cls.name} 未声明 event_types"

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
        event = _make_event(
            "opinion.mention_captured",
            {
                "platform": "dianping",
                "sentiment": "positive",
                "rating": 5.0,
                "content": "服务很好！",
            },
        )

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
        event = _make_event(
            "opinion.mention_captured",
            {
                "platform": "meituan",
                "sentiment": "negative",
                "rating": 1.0,
                "content": "等太久了",
            },
        )

        await self.proj.handle(event, conn)

        sqls = [c[0][0] for c in conn.execute.call_args_list]
        assert any("negative_count" in s for s in sqls)

    @pytest.mark.asyncio
    async def test_handle_neutral_mention_increments_neutral_count(self):
        """opinion.mention_captured (neutral) 应增加 neutral_count。"""
        conn = _mock_conn()
        event = _make_event(
            "opinion.mention_captured",
            {
                "platform": "weibo",
                "sentiment": "neutral",
                "content": "还行",
            },
        )

        await self.proj.handle(event, conn)

        sqls = [c[0][0] for c in conn.execute.call_args_list]
        assert any("neutral_count" in s for s in sqls)

    @pytest.mark.asyncio
    async def test_handle_resolved_updates_mention(self):
        """opinion.resolved 应更新 public_opinion_mentions.is_resolved=true。"""
        conn = _mock_conn()
        mention_id = str(uuid.uuid4())
        event = _make_event(
            "opinion.resolved",
            {
                "mention_id": mention_id,
                "resolution_note": "已联系顾客致歉",
            },
        )

        await self.proj.handle(event, conn)

        sqls = [c[0][0] for c in conn.execute.call_args_list]
        assert any("is_resolved" in s for s in sqls)
        assert any("public_opinion_mentions" in s for s in sqls)

    @pytest.mark.asyncio
    async def test_handle_resolved_no_mention_id_skips(self):
        """opinion.resolved 缺少 mention_id 时应静默跳过（不执行 UPDATE）。"""
        conn = _mock_conn()
        event = _make_event(
            "opinion.resolved",
            {
                "resolution_note": "已处理",
                # 缺少 mention_id
            },
        )

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
        event = _make_event(
            "opinion.mention_captured",
            {
                "platform": "dianping",
                "sentiment": "positive",
                "rating": 4.5,
                "sentiment_score": 0.85,
            },
        )

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

    def test_safety_projector_covers_haccp_events(self):
        """SafetyComplianceProjector 应包含 HACCP 两个事件类型。"""
        from shared.events.src.event_types import SafetyEventType

        assert SafetyEventType.HACCP_CHECK_COMPLETED.value == "safety.haccp_check_completed"
        assert SafetyEventType.HACCP_CRITICAL_FAILURE.value == "safety.haccp_critical_failure"
        assert "safety.haccp_check_completed" in SafetyComplianceProjector.event_types
        assert "safety.haccp_critical_failure" in SafetyComplianceProjector.event_types


# ══════════════════════════════════════════════════════════════════════════════
#  G. ChannelMarginProjector
# ══════════════════════════════════════════════════════════════════════════════


class TestChannelMarginProjector:
    @pytest.fixture
    def projector(self):
        from shared.events.src.projectors.channel_margin import ChannelMarginProjector

        return ChannelMarginProjector(tenant_id="11111111-1111-1111-1111-111111111111")

    def _make_conn(self):
        conn = MagicMock()
        conn.execute = AsyncMock()
        return conn

    def _make_event(self, event_type: str, payload: dict, store_id="22222222-2222-2222-2222-222222222222"):
        return {
            "event_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "event_type": event_type,
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "store_id": store_id,
            "occurred_at": "2026-04-04T10:00:00+00:00",
            "payload": payload,
        }

    @pytest.mark.asyncio
    async def test_order_synced_increments_gross_revenue(self, projector):
        """channel.order_synced 累计 GMV 和订单数"""
        conn = self._make_conn()
        event = self._make_event("channel.order_synced", {"channel": "meituan", "amount_fen": 5000})
        await projector.handle(event, conn)
        # INSERT + UPDATE + _recalc = 至少3次 execute
        assert conn.execute.call_count >= 3
        # 验证 UPDATE 调用包含 gross_revenue_fen + order_count
        calls_sql = [str(c.args[0]) for c in conn.execute.call_args_list]
        assert any("gross_revenue_fen" in sql for sql in calls_sql)

    @pytest.mark.asyncio
    async def test_commission_calc_increments_commission(self, projector):
        """channel.commission_calc 累计佣金"""
        conn = self._make_conn()
        event = self._make_event("channel.commission_calc", {"channel": "eleme", "commission_fen": 200})
        await projector.handle(event, conn)
        calls_sql = [str(c.args[0]) for c in conn.execute.call_args_list]
        assert any("commission_fen" in sql for sql in calls_sql)

    @pytest.mark.asyncio
    async def test_promotion_applied_increments_subsidy(self, projector):
        """channel.promotion_applied 累计平台补贴"""
        conn = self._make_conn()
        event = self._make_event("channel.promotion_applied", {"channel": "douyin", "subsidy_fen": 300})
        await projector.handle(event, conn)
        calls_sql = [str(c.args[0]) for c in conn.execute.call_args_list]
        assert any("promotion_subsidy_fen" in sql for sql in calls_sql)

    @pytest.mark.asyncio
    async def test_recalc_called_after_update(self, projector):
        """每次事件处理后都调用 _recalc_margin（更新 net_revenue_fen / gross_margin_rate）"""
        conn = self._make_conn()
        event = self._make_event("channel.order_synced", {"channel": "meituan", "amount_fen": 1000})
        await projector.handle(event, conn)
        calls_sql = [str(c.args[0]) for c in conn.execute.call_args_list]
        assert any("net_revenue_fen" in sql for sql in calls_sql)
        assert any("gross_margin_rate" in sql for sql in calls_sql)

    @pytest.mark.asyncio
    async def test_no_store_id_skips_event(self, projector):
        """缺少 store_id 时跳过，不执行任何 DB 操作"""
        conn = self._make_conn()
        event = self._make_event("channel.order_synced", {"channel": "meituan", "amount_fen": 1000}, store_id=None)
        event.pop("store_id")
        await projector.handle(event, conn)
        conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_string_occurred_at_parsed(self, projector):
        """ISO 字符串格式的 occurred_at 能正确解析为 date"""
        conn = self._make_conn()
        event = self._make_event("channel.order_synced", {"channel": "meituan", "amount_fen": 100})
        event["occurred_at"] = "2026-04-04T08:30:00+08:00"
        await projector.handle(event, conn)
        assert conn.execute.call_count >= 1

    @pytest.mark.asyncio
    async def test_unknown_channel_uses_unknown_string(self, projector):
        """payload 中无 channel 字段时，默认 channel='unknown'"""
        conn = self._make_conn()
        event = self._make_event("channel.order_synced", {"amount_fen": 500})  # 无 channel 字段
        await projector.handle(event, conn)
        # 验证 INSERT 调用包含 'unknown'（channel 参数）
        call_args_list = conn.execute.call_args_list
        assert any("unknown" in str(c) for c in call_args_list)


# ══════════════════════════════════════════════════════════════════════════════
#  H. StorePnlProjector
# ══════════════════════════════════════════════════════════════════════════════


from shared.events.src.projectors.store_pnl import StorePnlProjector


class TestStorePnlProjector:
    def setup_method(self):
        self.proj = StorePnlProjector(tenant_id=TENANT_ID)

    @pytest.mark.asyncio
    async def test_order_paid_increments_revenue(self):
        """order.paid 应累计 gross_revenue_fen 和 order_count。"""
        conn = _mock_conn()
        event = _make_event("order.paid", {"final_amount_fen": 8800})
        await self.proj.handle(event, conn)
        # INSERT + UPDATE order_count/revenue + _recalc = 3次
        assert conn.execute.call_count == 3
        sqls = [c[0][0] for c in conn.execute.call_args_list]
        assert any("gross_revenue_fen" in s for s in sqls)
        assert any("order_count" in s for s in sqls)

    @pytest.mark.asyncio
    async def test_order_paid_with_customer_id_increments_customer_count(self):
        """order.paid 含 customer_id 时，customer_count 增量参数应为 1。"""
        conn = _mock_conn()
        event = _make_event(
            "order.paid",
            {
                "final_amount_fen": 5000,
                "customer_id": str(uuid.uuid4()),
            },
        )
        await self.proj.handle(event, conn)
        # 找 UPDATE mv_store_pnl ... order_count 的调用，验证 customer_count delta=1
        update_call = None
        for c in conn.execute.call_args_list:
            if "customer_count" in c[0][0]:
                update_call = c
                break
        assert update_call is not None
        # args: (sql, tenant_id, store_id, stat_date, final_fen, customer_delta, event_id)
        args = update_call[0]
        assert args[5] == 1  # customer_count delta

    @pytest.mark.asyncio
    async def test_order_paid_triggers_recalc(self):
        """order.paid 后应调用 _recalc_pnl_rates（avg_check_fen 和 gross_margin_rate 出现在 SQL 中）。"""
        conn = _mock_conn()
        event = _make_event("order.paid", {"final_amount_fen": 12000})
        await self.proj.handle(event, conn)
        sqls = [c[0][0] for c in conn.execute.call_args_list]
        assert any("avg_check_fen" in s for s in sqls)
        assert any("gross_margin_rate" in s for s in sqls)

    @pytest.mark.asyncio
    async def test_member_recharged_increments_stored_value(self):
        """member.recharged 应累计 stored_value_new_fen（amount + gift）。"""
        conn = _mock_conn()
        event = _make_event(
            "member.recharged",
            {
                "amount_fen": 10000,
                "gift_amount_fen": 500,
            },
        )
        await self.proj.handle(event, conn)
        sqls = [c[0][0] for c in conn.execute.call_args_list]
        assert any("stored_value_new_fen" in s for s in sqls)
        # 验证 amount 参数 = 10000 + 500 = 10500
        update_call = None
        for c in conn.execute.call_args_list:
            if "stored_value_new_fen" in c[0][0]:
                update_call = c
                break
        assert update_call is not None
        args = update_call[0]
        assert args[4] == 10500  # amount_fen + gift_amount_fen

    @pytest.mark.asyncio
    async def test_channel_commission_reduces_net_revenue(self):
        """channel.commission_calc 应使 net_revenue_fen 减少（SQL 含减法操作）。"""
        conn = _mock_conn()
        event = _make_event("channel.commission_calc", {"commission_fen": 300})
        await self.proj.handle(event, conn)
        sqls = [c[0][0] for c in conn.execute.call_args_list]
        # UPDATE 中 net_revenue_fen 减去佣金
        assert any("net_revenue_fen  = net_revenue_fen - $4" in s for s in sqls)
        # channel.commission_calc 也触发 _recalc
        assert any("gross_margin_rate" in s for s in sqls)

    @pytest.mark.asyncio
    async def test_no_store_id_skips_event(self):
        """缺少 store_id 的事件不应触发任何 execute。"""
        conn = _mock_conn()
        event = _make_event("order.paid", {"final_amount_fen": 5000})
        event["store_id"] = None
        await self.proj.handle(event, conn)
        conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_settlement_advance_consumed(self):
        """settlement.advance_consumed 应累计 stored_value_consumed_fen。"""
        conn = _mock_conn()
        event = _make_event("settlement.advance_consumed", {"amount_fen": 2000})
        await self.proj.handle(event, conn)
        # INSERT + UPDATE stored_value_consumed_fen = 2次
        assert conn.execute.call_count == 2
        sqls = [c[0][0] for c in conn.execute.call_args_list]
        assert any("stored_value_consumed_fen" in s for s in sqls)
        # 验证金额参数
        update_call = None
        for c in conn.execute.call_args_list:
            if "stored_value_consumed_fen" in c[0][0]:
                update_call = c
                break
        assert update_call is not None
        args = update_call[0]
        assert args[4] == 2000


# ══════════════════════════════════════════════════════════════════════════════
#  I. DailySettlementProjector（Team C）
# ══════════════════════════════════════════════════════════════════════════════


class TestDailySettlementProjector:
    @pytest.fixture
    def projector(self):
        from shared.events.src.projectors.daily_settlement import DailySettlementProjector

        return DailySettlementProjector(tenant_id="11111111-1111-1111-1111-111111111111")

    def _make_conn(self):
        conn = MagicMock()
        conn.execute = AsyncMock()
        return conn

    def _make_event(self, event_type: str, payload: dict, store_id="22222222-2222-2222-2222-222222222222"):
        return {
            "event_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "event_type": event_type,
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "store_id": store_id,
            "occurred_at": "2026-04-04T23:00:00+00:00",
            "payload": payload,
        }

    @pytest.mark.asyncio
    async def test_payment_confirmed_wechat_increments_wechat_fen(self, projector):
        """payment.confirmed wechat 渠道 → wechat_received_fen++ 且 total_revenue_fen++"""
        conn = self._make_conn()
        event = self._make_event("payment.confirmed", {"channel": "wechat", "amount_fen": 8800})
        await projector.handle(event, conn)
        calls_sql = [str(c.args[0]) for c in conn.execute.call_args_list]
        assert any("total_revenue_fen" in sql for sql in calls_sql)

    @pytest.mark.asyncio
    async def test_cash_declared_calculates_discrepancy(self, projector):
        """payment.cash_declared 记录现金差异 = declared - system"""
        conn = self._make_conn()
        event = self._make_event("payment.cash_declared", {"declared_fen": 50000, "system_fen": 49000})
        await projector.handle(event, conn)
        calls_sql = [str(c.args[0]) for c in conn.execute.call_args_list]
        assert any("cash_discrepancy_fen" in sql for sql in calls_sql)
        # 差异值 1000 应出现在某次 execute 调用的参数中
        all_args = [str(c) for c in conn.execute.call_args_list]
        assert any("1000" in s for s in all_args)

    @pytest.mark.asyncio
    async def test_daily_closed_sets_status_closed(self, projector):
        """settlement.daily_closed → status='closed'"""
        conn = self._make_conn()
        event = self._make_event("settlement.daily_closed", {"operator_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"})
        await projector.handle(event, conn)
        calls_sql = [str(c.args[0]) for c in conn.execute.call_args_list]
        assert any("'closed'" in sql or "closed" in sql for sql in calls_sql)

    @pytest.mark.asyncio
    async def test_discrepancy_found_appends_pending_items(self, projector):
        """settlement.discrepancy_found → pending_items jsonb concat"""
        conn = self._make_conn()
        event = self._make_event(
            "settlement.discrepancy_found",
            {
                "discrepancy_type": "cash_short",
                "amount_fen": 500,
                "description": "现金少500",
            },
        )
        await projector.handle(event, conn)
        calls_sql = [str(c.args[0]) for c in conn.execute.call_args_list]
        assert any("pending_items" in sql for sql in calls_sql)

    @pytest.mark.asyncio
    async def test_advance_consumed_increments_stored_value(self, projector):
        """settlement.advance_consumed → stored_value_consumed_fen++"""
        conn = self._make_conn()
        event = self._make_event("settlement.advance_consumed", {"amount_fen": 3000})
        await projector.handle(event, conn)
        calls_sql = [str(c.args[0]) for c in conn.execute.call_args_list]
        assert any("stored_value_consumed_fen" in sql for sql in calls_sql)

    @pytest.mark.asyncio
    async def test_no_store_id_skips_event(self, projector):
        """缺少 store_id 时跳过，不触发任何 execute"""
        conn = self._make_conn()
        event = self._make_event("payment.confirmed", {"channel": "wechat", "amount_fen": 100})
        event.pop("store_id")
        await projector.handle(event, conn)
        conn.execute.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
#  J. MemberClvProjector（Team C）
# ══════════════════════════════════════════════════════════════════════════════


class TestMemberClvProjector:
    @pytest.fixture
    def projector(self):
        from shared.events.src.projectors.member_clv import MemberClvProjector

        return MemberClvProjector(tenant_id="11111111-1111-1111-1111-111111111111")

    def _make_conn(self):
        conn = MagicMock()
        conn.execute = AsyncMock()
        return conn

    def _make_event(self, event_type: str, payload: dict):
        return {
            "event_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "event_type": event_type,
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "store_id": "22222222-2222-2222-2222-222222222222",
            "occurred_at": "2026-04-04T23:00:00+00:00",
            "payload": payload,
        }

    @pytest.mark.asyncio
    async def test_order_paid_increments_visit_and_spend(self, projector):
        """order.paid → visit_count+1 且 total_spend_fen += amount"""
        conn = self._make_conn()
        event = self._make_event(
            "order.paid",
            {
                "customer_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                "final_amount_fen": 9900,
            },
        )
        await projector.handle(event, conn)
        calls_sql = [str(c.args[0]) for c in conn.execute.call_args_list]
        assert any("visit_count" in sql for sql in calls_sql)
        assert any("total_spend_fen" in sql for sql in calls_sql)

    @pytest.mark.asyncio
    async def test_order_paid_no_customer_id_skips(self, projector):
        """order.paid payload 无 customer_id → 0 execute"""
        conn = self._make_conn()
        event = self._make_event("order.paid", {"final_amount_fen": 9900})
        await projector.handle(event, conn)
        conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_recharged_increments_stored_value(self, projector):
        """member.recharged → stored_value_balance_fen += amount + gift"""
        conn = self._make_conn()
        event = self._make_event(
            "member.recharged",
            {
                "customer_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                "amount_fen": 10000,
                "gift_amount_fen": 500,
            },
        )
        await projector.handle(event, conn)
        calls_sql = [str(c.args[0]) for c in conn.execute.call_args_list]
        assert any("stored_value_balance_fen" in sql for sql in calls_sql)
        # 总计 10500 应出现在参数中
        all_args = [str(c) for c in conn.execute.call_args_list]
        assert any("10500" in s for s in all_args)

    @pytest.mark.asyncio
    async def test_consumed_decreases_stored_value(self, projector):
        """member.consumed → stored_value_balance_fen -= amount（GREATEST 防负数）"""
        conn = self._make_conn()
        event = self._make_event(
            "member.consumed",
            {
                "customer_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                "amount_fen": 3000,
            },
        )
        await projector.handle(event, conn)
        calls_sql = [str(c.args[0]) for c in conn.execute.call_args_list]
        assert any("stored_value_balance_fen" in sql for sql in calls_sql)
        # SQL 应包含 GREATEST 防止余额为负
        assert any("GREATEST" in sql for sql in calls_sql)

    @pytest.mark.asyncio
    async def test_voucher_used_increments_count(self, projector):
        """member.voucher_used → voucher_used_count+1"""
        conn = self._make_conn()
        event = self._make_event(
            "member.voucher_used",
            {
                "customer_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                "face_value_fen": 2000,
            },
        )
        await projector.handle(event, conn)
        calls_sql = [str(c.args[0]) for c in conn.execute.call_args_list]
        assert any("voucher_used_count" in sql for sql in calls_sql)

    @pytest.mark.asyncio
    async def test_churn_predicted_sets_probability(self, projector):
        """member.churn_predicted → churn_probability=0.85"""
        conn = self._make_conn()
        event = self._make_event(
            "member.churn_predicted",
            {
                "customer_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                "churn_probability": 0.85,
                "next_visit_days": 30,
            },
        )
        await projector.handle(event, conn)
        calls_sql = [str(c.args[0]) for c in conn.execute.call_args_list]
        assert any("churn_probability" in sql for sql in calls_sql)
        # 概率值 0.85 应出现在参数中
        all_args = [str(c) for c in conn.execute.call_args_list]
        assert any("0.85" in s for s in all_args)


# ══════════════════════════════════════════════════════════════════════════════
#  K. InventoryBomProjector（Team C）
# ══════════════════════════════════════════════════════════════════════════════


class TestInventoryBomProjector:
    @pytest.fixture
    def projector(self):
        from shared.events.src.projectors.inventory_bom import InventoryBomProjector

        return InventoryBomProjector(tenant_id="11111111-1111-1111-1111-111111111111")

    def _make_conn(self):
        conn = MagicMock()
        conn.execute = AsyncMock()
        return conn

    def _make_event(self, event_type: str, payload: dict, store_id="22222222-2222-2222-2222-222222222222"):
        return {
            "event_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "event_type": event_type,
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "store_id": store_id,
            "occurred_at": "2026-04-04T23:00:00+00:00",
            "payload": payload,
        }

    @pytest.mark.asyncio
    async def test_consumed_increments_theoretical_and_actual(self, projector):
        """inventory.consumed → theoretical_usage_g++ 且 actual_usage_g++"""
        conn = self._make_conn()
        event = self._make_event(
            "inventory.consumed",
            {
                "ingredient_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
                "ingredient_name": "猪肉",
                "quantity_g": 200.0,
                "theoretical_g": 190.0,
            },
        )
        await projector.handle(event, conn)
        calls_sql = [str(c.args[0]) for c in conn.execute.call_args_list]
        assert any("theoretical_usage_g" in sql for sql in calls_sql)
        assert any("actual_usage_g" in sql for sql in calls_sql)

    @pytest.mark.asyncio
    async def test_consumed_no_ingredient_id_skips(self, projector):
        """payload 无 ingredient_id → 0 execute"""
        conn = self._make_conn()
        event = self._make_event(
            "inventory.consumed",
            {
                "ingredient_name": "猪肉",
                "quantity_g": 200.0,
            },
        )
        await projector.handle(event, conn)
        conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_wasted_increments_waste_g(self, projector):
        """inventory.wasted → waste_g++"""
        conn = self._make_conn()
        event = self._make_event(
            "inventory.wasted",
            {
                "ingredient_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
                "ingredient_name": "鸡蛋",
                "quantity_g": 50.0,
            },
        )
        await projector.handle(event, conn)
        calls_sql = [str(c.args[0]) for c in conn.execute.call_args_list]
        assert any("waste_g" in sql for sql in calls_sql)

    @pytest.mark.asyncio
    async def test_recalc_called_after_consumed(self, projector):
        """inventory.consumed 后调用 _recalc_loss（SQL 包含 unexplained_loss_g 或 loss_rate）"""
        conn = self._make_conn()
        event = self._make_event(
            "inventory.consumed",
            {
                "ingredient_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
                "ingredient_name": "面粉",
                "quantity_g": 300.0,
            },
        )
        await projector.handle(event, conn)
        calls_sql = [str(c.args[0]) for c in conn.execute.call_args_list]
        assert any("unexplained_loss_g" in sql or "loss_rate" in sql for sql in calls_sql)

    @pytest.mark.asyncio
    async def test_recalc_called_after_wasted(self, projector):
        """inventory.wasted 后也调用 _recalc_loss"""
        conn = self._make_conn()
        event = self._make_event(
            "inventory.wasted",
            {
                "ingredient_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
                "ingredient_name": "油",
                "quantity_g": 100.0,
            },
        )
        await projector.handle(event, conn)
        calls_sql = [str(c.args[0]) for c in conn.execute.call_args_list]
        assert any("unexplained_loss_g" in sql or "loss_rate" in sql for sql in calls_sql)

    @pytest.mark.asyncio
    async def test_no_store_id_skips_event(self, projector):
        """无 store_id → 跳过，不触发任何 execute"""
        conn = self._make_conn()
        event = self._make_event(
            "inventory.consumed",
            {
                "ingredient_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
                "quantity_g": 100.0,
            },
        )
        event.pop("store_id")
        await projector.handle(event, conn)
        conn.execute.assert_not_called()
