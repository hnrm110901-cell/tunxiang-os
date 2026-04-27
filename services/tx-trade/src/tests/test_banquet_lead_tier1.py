"""Tier 1 测试 — 宴会商机漏斗（Track D / Sprint R1）

验收：全部通过才允许 banquet_lead 模块上线。

核心场景（对齐 CLAUDE.md §17/§20 Tier 1 用例基于餐厅场景）：
  - 婚宴线索从被预订台记录到真实签约的完整流程
  - 销售经理按月月考核：所管商机转化率要可追溯
  - 渠道归因：美团/婚礼纪等付费渠道的ROI必须能算
  - 租户隔离：尝在一起的商机绝不能跨到最黔线

关联实现：
  services/tx-trade/src/services/banquet_lead_service.py
  services/tx-trade/src/repositories/banquet_lead_repo.py
  services/tx-trade/src/api/banquet_lead_routes.py
  services/tx-trade/src/services/banquet_funnel_projector.py
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import date, datetime, timezone
from typing import Any

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for p in [ROOT, SRC]:
    if p not in sys.path:
        sys.path.insert(0, p)

from shared.ontology.src.extensions.banquet_leads import (
    BanquetLead,
    BanquetType,
    LeadStage,
    SourceChannel,
)
from src.repositories.banquet_lead_repo import InMemoryBanquetLeadRepository
from src.services.banquet_lead_service import (
    BanquetLeadService,
    InvalidationReasonMissingError,
    InvalidStageTransitionError,
)

TENANT_A = uuid.UUID("00000000-0000-0000-0000-000000000001")
TENANT_B = uuid.UUID("00000000-0000-0000-0000-000000000002")
STORE_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def repo() -> InMemoryBanquetLeadRepository:
    return InMemoryBanquetLeadRepository()


@pytest.fixture
def emitted() -> list[dict[str, Any]]:
    return []


@pytest.fixture
def service(
    repo: InMemoryBanquetLeadRepository, emitted: list[dict[str, Any]]
) -> BanquetLeadService:
    """BanquetLeadService 实例，事件发射 patch 为 in-memory 记录。"""

    async def _fake_emit(**kwargs: Any) -> str:
        emitted.append(kwargs)
        return str(uuid.uuid4())

    svc = BanquetLeadService(repo=repo, emit_event=_fake_emit)
    return svc


# ─────────────────────────────────────────────────────────────────────────
# T1. 创建商机 → stage=all + 写入 CREATED 事件
# ─────────────────────────────────────────────────────────────────────────


class TestBanquetLeadCreate:
    """新客打电话预订婚宴 → 预订台同事录入系统。"""

    @pytest.mark.asyncio
    async def test_create_lead_writes_event_with_stage_all(
        self,
        service: BanquetLeadService,
        emitted: list[dict[str, Any]],
    ):
        """创建商机后 stage=all，同步发射 CREATED 事件（含完整 payload）。"""
        customer_id = uuid.uuid4()
        sales_employee_id = uuid.uuid4()

        lead = await service.create_lead(
            customer_id=customer_id,
            banquet_type=BanquetType.WEDDING,
            source_channel=SourceChannel.BOOKING_DESK,
            sales_employee_id=sales_employee_id,
            estimated_amount_fen=3_000_000,  # 30000 元
            estimated_tables=20,
            scheduled_date=date(2026, 10, 1),
            tenant_id=TENANT_A,
            store_id=STORE_ID,
        )

        assert isinstance(lead, BanquetLead)
        assert lead.stage == LeadStage.ALL
        assert lead.tenant_id == TENANT_A
        assert lead.estimated_amount_fen == 3_000_000
        assert lead.source_channel == SourceChannel.BOOKING_DESK

        # 事件发射
        assert len(emitted) == 1
        evt = emitted[0]
        assert evt["event_type"].value == "banquet.lead_created"
        assert evt["tenant_id"] == TENANT_A
        assert evt["stream_id"] == str(lead.lead_id)
        assert evt["payload"]["stage"] == "all"
        assert evt["payload"]["customer_id"] == str(customer_id)
        assert evt["payload"]["banquet_type"] == "wedding"
        assert evt["payload"]["source_channel"] == "booking_desk"
        assert evt["payload"]["estimated_amount_fen"] == 3_000_000


# ─────────────────────────────────────────────────────────────────────────
# T2. 合法状态流转：all → opportunity → order → converted
# ─────────────────────────────────────────────────────────────────────────


class TestStageTransitions:
    @pytest.mark.asyncio
    async def test_valid_stage_transitions(
        self,
        service: BanquetLeadService,
        emitted: list[dict[str, Any]],
    ):
        """王老板咨询 → 签意向 → 签合同 → 转预订：四步 happy path。"""
        lead = await service.create_lead(
            customer_id=uuid.uuid4(),
            banquet_type=BanquetType.WEDDING,
            source_channel=SourceChannel.REFERRAL,
            sales_employee_id=uuid.uuid4(),
            estimated_amount_fen=5_000_000,
            estimated_tables=30,
            scheduled_date=date(2026, 12, 12),
            tenant_id=TENANT_A,
        )
        operator_id = uuid.uuid4()

        lead2 = await service.transition_stage(
            lead_id=lead.lead_id,
            next_stage=LeadStage.OPPORTUNITY,
            operator_id=operator_id,
            tenant_id=TENANT_A,
        )
        assert lead2.stage == LeadStage.OPPORTUNITY
        assert lead2.previous_stage == LeadStage.ALL

        lead3 = await service.transition_stage(
            lead_id=lead.lead_id,
            next_stage=LeadStage.ORDER,
            operator_id=operator_id,
            tenant_id=TENANT_A,
        )
        assert lead3.stage == LeadStage.ORDER
        assert lead3.previous_stage == LeadStage.OPPORTUNITY

        reservation_id = uuid.uuid4()
        lead4 = await service.convert_to_reservation(
            lead_id=lead.lead_id,
            reservation_id=reservation_id,
            operator_id=operator_id,
            tenant_id=TENANT_A,
        )
        assert lead4.converted_reservation_id == reservation_id

        event_types = [evt["event_type"].value for evt in emitted]
        assert event_types == [
            "banquet.lead_created",
            "banquet.lead_stage_changed",
            "banquet.lead_stage_changed",
            "banquet.lead_converted",
        ]

    @pytest.mark.asyncio
    async def test_invalid_stage_transition_raises(
        self, service: BanquetLeadService
    ):
        """order 阶段不能倒退回 opportunity（销售不能反悔）。"""
        lead = await service.create_lead(
            customer_id=uuid.uuid4(),
            banquet_type=BanquetType.CORPORATE,
            source_channel=SourceChannel.INTERNAL,
            sales_employee_id=uuid.uuid4(),
            estimated_amount_fen=2_000_000,
            estimated_tables=10,
            scheduled_date=None,
            tenant_id=TENANT_A,
        )
        operator_id = uuid.uuid4()

        await service.transition_stage(
            lead_id=lead.lead_id,
            next_stage=LeadStage.OPPORTUNITY,
            operator_id=operator_id,
            tenant_id=TENANT_A,
        )
        await service.transition_stage(
            lead_id=lead.lead_id,
            next_stage=LeadStage.ORDER,
            operator_id=operator_id,
            tenant_id=TENANT_A,
        )

        with pytest.raises(InvalidStageTransitionError):
            await service.transition_stage(
                lead_id=lead.lead_id,
                next_stage=LeadStage.OPPORTUNITY,
                operator_id=operator_id,
                tenant_id=TENANT_A,
            )

    @pytest.mark.asyncio
    async def test_invalid_without_reason_raises(
        self, service: BanquetLeadService
    ):
        """置失效时必填 invalidation_reason（用于Agent分析流失原因）。"""
        lead = await service.create_lead(
            customer_id=uuid.uuid4(),
            banquet_type=BanquetType.BIRTHDAY,
            source_channel=SourceChannel.MEITUAN,
            sales_employee_id=uuid.uuid4(),
            estimated_amount_fen=800_000,
            estimated_tables=5,
            scheduled_date=None,
            tenant_id=TENANT_A,
        )

        with pytest.raises(InvalidationReasonMissingError):
            await service.transition_stage(
                lead_id=lead.lead_id,
                next_stage=LeadStage.INVALID,
                operator_id=uuid.uuid4(),
                tenant_id=TENANT_A,
                invalidation_reason=None,
            )

    @pytest.mark.asyncio
    async def test_idempotent_transition(
        self,
        service: BanquetLeadService,
        emitted: list[dict[str, Any]],
    ):
        """重复 transition 到同一 stage 返回当前状态，不重复发事件。"""
        lead = await service.create_lead(
            customer_id=uuid.uuid4(),
            banquet_type=BanquetType.WEDDING,
            source_channel=SourceChannel.HUNLIJI,
            sales_employee_id=uuid.uuid4(),
            estimated_amount_fen=4_000_000,
            estimated_tables=25,
            scheduled_date=date(2026, 9, 9),
            tenant_id=TENANT_A,
        )
        operator_id = uuid.uuid4()

        lead1 = await service.transition_stage(
            lead_id=lead.lead_id,
            next_stage=LeadStage.OPPORTUNITY,
            operator_id=operator_id,
            tenant_id=TENANT_A,
        )
        n_events_after_first = len(emitted)

        lead2 = await service.transition_stage(
            lead_id=lead.lead_id,
            next_stage=LeadStage.OPPORTUNITY,
            operator_id=operator_id,
            tenant_id=TENANT_A,
        )
        assert lead2.stage == lead1.stage
        assert lead2.lead_id == lead1.lead_id
        assert len(emitted) == n_events_after_first, (
            "幂等：重复 transition 到同一 stage 不应重复发射事件"
        )


# ─────────────────────────────────────────────────────────────────────────
# T3. 按销售员工维度聚合转化率
# ─────────────────────────────────────────────────────────────────────────


class TestConversionRate:
    @pytest.mark.asyncio
    async def test_conversion_rate_by_sales_employee(
        self, service: BanquetLeadService
    ):
        """
        徐记海鲜：4 个销售员共 10 个样本商机，统计各员工漏斗。

        样本分布（手工构造）：
          员工 A：2 个 all，1 个 opportunity，1 个 order → 4 总，转化率 1/4 = 25%
          员工 B：1 个 all，1 个 order                  → 2 总，转化率 1/2 = 50%
          员工 C：1 个 invalid                          → 1 总，转化率 0
          员工 D：3 个 opportunity                      → 3 总，转化率 0
        """
        emp_a, emp_b, emp_c, emp_d = [uuid.uuid4() for _ in range(4)]

        # 直接批量构造（绕过 transition，借用 repo.seed 已 stage 的 lead）
        samples = [
            (emp_a, LeadStage.ALL),
            (emp_a, LeadStage.ALL),
            (emp_a, LeadStage.OPPORTUNITY),
            (emp_a, LeadStage.ORDER),
            (emp_b, LeadStage.ALL),
            (emp_b, LeadStage.ORDER),
            (emp_c, LeadStage.INVALID),
            (emp_d, LeadStage.OPPORTUNITY),
            (emp_d, LeadStage.OPPORTUNITY),
            (emp_d, LeadStage.OPPORTUNITY),
        ]
        period_start = datetime(2026, 4, 1, tzinfo=timezone.utc)
        period_end = datetime(2026, 4, 30, tzinfo=timezone.utc)

        for emp_id, stage in samples:
            await service._repo.seed_lead(  # test hook
                tenant_id=TENANT_A,
                sales_employee_id=emp_id,
                banquet_type=BanquetType.WEDDING,
                source_channel=SourceChannel.BOOKING_DESK,
                stage=stage,
                estimated_amount_fen=1_000_000,
                estimated_tables=10,
                scheduled_date=None,
                stage_changed_at=datetime(2026, 4, 15, tzinfo=timezone.utc),
                invalidation_reason="test" if stage == LeadStage.INVALID else None,
            )

        result = await service.compute_conversion_rate(
            tenant_id=TENANT_A,
            period_start=period_start,
            period_end=period_end,
            group_by="sales_employee_id",
        )

        # 返回结构：{group_key: {"all":N, "opportunity":N, "order":N, "invalid":N, "total":N, "conversion_rate":float}}
        assert str(emp_a) in result
        emp_a_stats = result[str(emp_a)]
        assert emp_a_stats["all"] == 2
        assert emp_a_stats["opportunity"] == 1
        assert emp_a_stats["order"] == 1
        assert emp_a_stats["invalid"] == 0
        assert emp_a_stats["total"] == 4
        assert abs(emp_a_stats["conversion_rate"] - 0.25) < 1e-6

        emp_b_stats = result[str(emp_b)]
        assert emp_b_stats["total"] == 2
        assert abs(emp_b_stats["conversion_rate"] - 0.5) < 1e-6

        emp_c_stats = result[str(emp_c)]
        assert emp_c_stats["invalid"] == 1
        assert emp_c_stats["conversion_rate"] == 0.0

        emp_d_stats = result[str(emp_d)]
        assert emp_d_stats["opportunity"] == 3
        assert emp_d_stats["conversion_rate"] == 0.0


# ─────────────────────────────────────────────────────────────────────────
# T4. 渠道归因：7+ 渠道的 ROI 表
# ─────────────────────────────────────────────────────────────────────────


class TestSourceAttribution:
    @pytest.mark.asyncio
    async def test_source_attribution_7_channels(
        self, service: BanquetLeadService
    ):
        """
        8 个渠道各造 1 个 order 阶段商机，验证归因表覆盖所有渠道。
        """
        all_channels = [
            SourceChannel.BOOKING_DESK,
            SourceChannel.REFERRAL,
            SourceChannel.HUNLIJI,
            SourceChannel.DIANPING,
            SourceChannel.INTERNAL,
            SourceChannel.MEITUAN,
            SourceChannel.GAODE,
            SourceChannel.BAIDU,
        ]
        for ch in all_channels:
            await service._repo.seed_lead(
                tenant_id=TENANT_A,
                sales_employee_id=uuid.uuid4(),
                banquet_type=BanquetType.WEDDING,
                source_channel=ch,
                stage=LeadStage.ORDER,
                estimated_amount_fen=1_000_000,
                estimated_tables=10,
                scheduled_date=None,
                stage_changed_at=datetime(2026, 4, 15, tzinfo=timezone.utc),
            )

        result = await service.source_attribution(
            tenant_id=TENANT_A,
            period_start=datetime(2026, 4, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 4, 30, tzinfo=timezone.utc),
        )

        assert isinstance(result, list)
        channel_keys = {row["source_channel"] for row in result}
        assert channel_keys == {c.value for c in all_channels}, (
            "归因表必须覆盖 8 个渠道"
        )

        # 每个渠道 total=1, converted=1, conversion_rate=1.0
        for row in result:
            assert row["total"] == 1
            assert row["converted"] == 1
            assert abs(row["conversion_rate"] - 1.0) < 1e-6


# ─────────────────────────────────────────────────────────────────────────
# T5. 租户隔离
# ─────────────────────────────────────────────────────────────────────────


class TestTenantIsolation:
    @pytest.mark.asyncio
    async def test_tenant_isolation_rls(
        self, service: BanquetLeadService
    ):
        """
        租户 A 的漏斗查询绝对不含租户 B 的数据。
        场景：尝在一起 tenant_A 与最黔线 tenant_B 共用同一份部署。
        """
        await service._repo.seed_lead(
            tenant_id=TENANT_A,
            sales_employee_id=uuid.uuid4(),
            banquet_type=BanquetType.WEDDING,
            source_channel=SourceChannel.MEITUAN,
            stage=LeadStage.ORDER,
            estimated_amount_fen=1_000_000,
            estimated_tables=10,
            scheduled_date=None,
            stage_changed_at=datetime(2026, 4, 15, tzinfo=timezone.utc),
        )
        await service._repo.seed_lead(
            tenant_id=TENANT_B,
            sales_employee_id=uuid.uuid4(),
            banquet_type=BanquetType.WEDDING,
            source_channel=SourceChannel.MEITUAN,
            stage=LeadStage.ORDER,
            estimated_amount_fen=9_999_999,
            estimated_tables=50,
            scheduled_date=None,
            stage_changed_at=datetime(2026, 4, 15, tzinfo=timezone.utc),
        )

        result_a = await service.source_attribution(
            tenant_id=TENANT_A,
            period_start=datetime(2026, 4, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 4, 30, tzinfo=timezone.utc),
        )

        # 租户 A 只看到 1 个 meituan 渠道，总金额=1,000,000
        meituan_rows = [row for row in result_a if row["source_channel"] == "meituan"]
        assert len(meituan_rows) == 1
        assert meituan_rows[0]["total"] == 1
        assert meituan_rows[0]["estimated_amount_fen_total"] == 1_000_000, (
            "RLS 隔离失败：租户 A 看到了租户 B 的金额"
        )


# ─────────────────────────────────────────────────────────────────────────
# T6. 独立验证 P1-3：订金退款触发 lead.stage=invalid（因果链关联）
# ─────────────────────────────────────────────────────────────────────────


class TestDepositRefundInvalidates:
    """徐记海鲜婚宴退宴场景：客户付订金后新郎新娘闹掰要求退宴 →
    财务退款 → banquet_lead.stage 自动切 invalid，
    且新发射的 lead_stage_changed 事件携带 causation_id = deposit_event_id，
    保证下游 Agent 能回溯退款原因。
    """

    @pytest.mark.asyncio
    async def test_deposit_refunded_triggers_lead_invalid(
        self,
        service: BanquetLeadService,
        emitted: list[dict[str, Any]],
    ):
        """deposit 退款事件 → handle_deposit_refunded →
          - lead.stage = invalid
          - invalidation_reason 包含"订金退款"前缀 + 原因
          - causation_id 关联到 deposit_event_id
        """
        # 场景：客户已付订金 5 万（订单已转到 order 阶段）
        lead = await service.create_lead(
            customer_id=uuid.uuid4(),
            banquet_type=BanquetType.WEDDING,
            source_channel=SourceChannel.REFERRAL,
            sales_employee_id=uuid.uuid4(),
            estimated_amount_fen=5_000_000,  # 5 万元
            estimated_tables=30,
            scheduled_date=None,
            tenant_id=TENANT_A,
        )
        operator_id = uuid.uuid4()
        # 推进到 order（已收订金的状态）
        await service.transition_stage(
            lead_id=lead.lead_id,
            next_stage=LeadStage.OPPORTUNITY,
            operator_id=operator_id,
            tenant_id=TENANT_A,
        )
        await service.transition_stage(
            lead_id=lead.lead_id,
            next_stage=LeadStage.ORDER,
            operator_id=operator_id,
            tenant_id=TENANT_A,
        )

        # 客户取消宴席：财务发起退款，deposit.refunded 事件 ID 如下
        deposit_event_id = uuid.uuid4()

        result = await service.handle_deposit_refunded(
            lead_id=lead.lead_id,
            tenant_id=TENANT_A,
            deposit_event_id=deposit_event_id,
            refund_reason="新郎新娘取消婚礼",
            operator_id=operator_id,
        )

        # 断言 1：stage 被切到 invalid
        assert result.stage == LeadStage.INVALID
        # 断言 2：invalidation_reason 包含"订金退款"前缀 + 业务原因
        assert result.invalidation_reason is not None
        assert "订金退款" in result.invalidation_reason
        assert "新郎新娘取消婚礼" in result.invalidation_reason

        # 断言 3：最后一条 lead_stage_changed 事件的 causation_id == deposit_event_id
        stage_changed_events = [
            e
            for e in emitted
            if e["event_type"].value == "banquet.lead_stage_changed"
        ]
        assert len(stage_changed_events) >= 1, (
            "应至少发射一条 lead_stage_changed（order→invalid）"
        )
        last_change = stage_changed_events[-1]
        assert last_change["causation_id"] == deposit_event_id, (
            "独立验证 P1-3：lead_stage_changed.causation_id 必须等于 deposit_event_id"
        )
        assert last_change["payload"]["next_stage"] == "invalid"

    @pytest.mark.asyncio
    async def test_deposit_refund_preserves_causation_chain(
        self,
        service: BanquetLeadService,
        emitted: list[dict[str, Any]],
    ):
        """lead_stage_changed 事件的 causation_id 必须严格等于 deposit_refunded
        的 event_id，实现完整因果链：

            deposit.refunded (event_id=E1)
                └─> banquet.lead_stage_changed (causation_id=E1)
                        └─> (R2) 销售佣金回收 Saga
                        └─> (R2) 场地档期释放
        """
        lead = await service.create_lead(
            customer_id=uuid.uuid4(),
            banquet_type=BanquetType.CORPORATE,
            source_channel=SourceChannel.INTERNAL,
            sales_employee_id=uuid.uuid4(),
            estimated_amount_fen=2_000_000,
            estimated_tables=10,
            scheduled_date=None,
            tenant_id=TENANT_A,
        )
        # 直接从 all → invalid 也是合法流转（企业客户订金后取消）
        # 不需要经过 opportunity / order

        # 独特的 UUID 便于后续强等值断言
        deposit_event_id = uuid.uuid4()

        emitted.clear()
        await service.handle_deposit_refunded(
            lead_id=lead.lead_id,
            tenant_id=TENANT_A,
            deposit_event_id=deposit_event_id,
            refund_reason="企业活动推迟",
        )

        # 因果链：必须有且仅有一条 lead_stage_changed 事件，且 causation_id 精确匹配
        stage_events = [
            e
            for e in emitted
            if e["event_type"].value == "banquet.lead_stage_changed"
        ]
        assert len(stage_events) == 1, (
            "单次 deposit 退款只应触发一次 stage_changed（幂等）"
        )
        stage_evt = stage_events[0]
        assert stage_evt["causation_id"] == deposit_event_id, (
            f"causation_id 不匹配：expected {deposit_event_id}, "
            f"got {stage_evt['causation_id']}"
        )
        # stream_id 是 lead_id，payload.next_stage=invalid
        assert stage_evt["stream_id"] == str(lead.lead_id)
        assert stage_evt["payload"]["next_stage"] == "invalid"
        assert "订金退款" in stage_evt["payload"]["invalidation_reason"]

        # 幂等再调一次不应再发事件
        emitted.clear()
        await service.handle_deposit_refunded(
            lead_id=lead.lead_id,
            tenant_id=TENANT_A,
            deposit_event_id=uuid.uuid4(),  # 即便换新 event_id 也不应再改动
            refund_reason="重复退款请求",
        )
        assert emitted == [], (
            "lead 已 invalid 后再收 deposit.refunded 应幂等短路，不重发事件"
        )
