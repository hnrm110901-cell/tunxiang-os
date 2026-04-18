"""T5.1.3 — OntologyEvent 具体 schema 的 TDD 测试.

覆盖:
- order_events: OrderCreatedPayload / OrderPaidPayload
- invoice_events: InvoiceVerifiedPayload
- finance_events: CashFlowSnapshotPayload
- 字段校验 (金额 >=0, 类型枚举, 必填)
- 演进规则: 新增可选字段向后兼容
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.events.schemas.base import OntologyEvent
from shared.events.schemas.finance_events import CashFlowSnapshotPayload
from shared.events.schemas.invoice_events import (
    InvoiceType,
    InvoiceVerifiedPayload,
)
from shared.events.schemas.order_events import (
    OrderChannel,
    OrderCreatedPayload,
    OrderPaidPayload,
    PaymentMethod,
)

# ======================================================================
# §1 OrderCreatedPayload
# ======================================================================

class TestOrderCreatedPayload:
    def test_constructs_with_required_fields(self) -> None:
        p = OrderCreatedPayload(
            order_id="o-1",
            store_id="s-1",
            total_fen=8800,
            created_by="emp-42",
        )
        assert p.order_id == "o-1"
        assert p.total_fen == 8800
        assert p.table_id is None

    def test_optional_table_id(self) -> None:
        p = OrderCreatedPayload(
            order_id="o-1",
            store_id="s-1",
            total_fen=8800,
            created_by="emp-1",
            table_id="T-08",
        )
        assert p.table_id == "T-08"

    def test_is_subclass_of_ontology_event(self) -> None:
        p = OrderCreatedPayload(
            order_id="o-1", store_id="s-1", total_fen=1, created_by="e-1"
        )
        assert isinstance(p, OntologyEvent)

    def test_negative_total_fen_rejected(self) -> None:
        """金额严格 >=0, 负数被 Pydantic 拒绝."""
        with pytest.raises(ValidationError):
            OrderCreatedPayload(
                order_id="o-1", store_id="s-1", total_fen=-100, created_by="e"
            )

    def test_is_frozen(self) -> None:
        p = OrderCreatedPayload(
            order_id="o-1", store_id="s-1", total_fen=1, created_by="e"
        )
        with pytest.raises(ValidationError):
            p.total_fen = 999  # type: ignore[misc]


# ======================================================================
# §2 OrderPaidPayload
# ======================================================================

class TestOrderPaidPayload:
    def test_constructs_with_required_fields(self) -> None:
        p = OrderPaidPayload(
            order_id="o-1",
            store_id="s-1",
            total_fen=8800,
            paid_fen=8800,
            payment_method=PaymentMethod.WECHAT,
            channel=OrderChannel.DINE_IN,
        )
        assert p.payment_method == PaymentMethod.WECHAT
        assert p.channel == OrderChannel.DINE_IN

    def test_payment_method_enum_rejects_invalid(self) -> None:
        with pytest.raises(ValidationError):
            OrderPaidPayload(
                order_id="o-1",
                store_id="s-1",
                total_fen=1000,
                paid_fen=1000,
                payment_method="bitcoin",  # type: ignore[arg-type]
                channel=OrderChannel.DINE_IN,
            )

    def test_channel_enum_rejects_invalid(self) -> None:
        with pytest.raises(ValidationError):
            OrderPaidPayload(
                order_id="o-1",
                store_id="s-1",
                total_fen=1000,
                paid_fen=1000,
                payment_method=PaymentMethod.CASH,
                channel="time_travel",  # type: ignore[arg-type]
            )

    def test_paid_fen_can_be_partial(self) -> None:
        """paid_fen 可小于 total_fen (部分支付场景)."""
        p = OrderPaidPayload(
            order_id="o-1",
            store_id="s-1",
            total_fen=10000,
            paid_fen=5000,
            payment_method=PaymentMethod.CASH,
            channel=OrderChannel.DINE_IN,
        )
        assert p.paid_fen < p.total_fen


# ======================================================================
# §3 InvoiceVerifiedPayload
# ======================================================================

class TestInvoiceVerifiedPayload:
    def test_constructs_with_required_fields(self) -> None:
        p = InvoiceVerifiedPayload(
            invoice_no="INV-001",
            supplier_tax_id="91110108MA01234567",
            amount_fen=100000,
            tax_fen=6000,
            invoice_type=InvoiceType.FULLY_ELECTRONIC,
            verified_at="2026-04-18T10:00:00+00:00",
        )
        assert p.invoice_no == "INV-001"
        assert p.three_way_match_id is None

    def test_three_way_match_id_optional(self) -> None:
        p = InvoiceVerifiedPayload(
            invoice_no="INV-002",
            supplier_tax_id="91000000000000000X",
            amount_fen=50000,
            tax_fen=3000,
            invoice_type=InvoiceType.PAPER,
            verified_at="2026-04-18T10:00:00+00:00",
            three_way_match_id="match-abc",
        )
        assert p.three_way_match_id == "match-abc"

    def test_invoice_type_enum_enforced(self) -> None:
        with pytest.raises(ValidationError):
            InvoiceVerifiedPayload(
                invoice_no="X",
                supplier_tax_id="91",
                amount_fen=100,
                tax_fen=6,
                invoice_type="hologram_foil",  # type: ignore[arg-type]
                verified_at="2026-04-18T10:00:00+00:00",
            )

    def test_negative_tax_rejected(self) -> None:
        with pytest.raises(ValidationError):
            InvoiceVerifiedPayload(
                invoice_no="X",
                supplier_tax_id="91",
                amount_fen=100,
                tax_fen=-6,
                invoice_type=InvoiceType.PAPER,
                verified_at="2026-04-18T10:00:00+00:00",
            )


# ======================================================================
# §4 CashFlowSnapshotPayload
# ======================================================================

class TestCashFlowSnapshotPayload:
    def test_constructs_with_required_fields(self) -> None:
        p = CashFlowSnapshotPayload(
            store_id="s-1",
            snapshot_date="2026-04-18",
            cash_on_hand_fen=500_000,
            projected_7d_inflow_fen=300_000,
            projected_7d_outflow_fen=420_000,
            days_until_dry=12,
            confidence=0.85,
        )
        assert p.days_until_dry == 12

    def test_days_until_dry_can_be_none(self) -> None:
        """None 表示 >30 天或充裕."""
        p = CashFlowSnapshotPayload(
            store_id="s-1",
            snapshot_date="2026-04-18",
            cash_on_hand_fen=10_000_000,
            projected_7d_inflow_fen=5_000_000,
            projected_7d_outflow_fen=3_000_000,
            days_until_dry=None,
            confidence=0.95,
        )
        assert p.days_until_dry is None

    def test_confidence_range_0_to_1(self) -> None:
        with pytest.raises(ValidationError):
            CashFlowSnapshotPayload(
                store_id="s-1",
                snapshot_date="2026-04-18",
                cash_on_hand_fen=0,
                projected_7d_inflow_fen=0,
                projected_7d_outflow_fen=0,
                days_until_dry=0,
                confidence=1.5,
            )
        with pytest.raises(ValidationError):
            CashFlowSnapshotPayload(
                store_id="s-1",
                snapshot_date="2026-04-18",
                cash_on_hand_fen=0,
                projected_7d_inflow_fen=0,
                projected_7d_outflow_fen=0,
                days_until_dry=0,
                confidence=-0.01,
            )

    def test_negative_cash_on_hand_allowed_for_overdraft(self) -> None:
        """允许负值: 现金可能透支 (银行额度)."""
        p = CashFlowSnapshotPayload(
            store_id="s-1",
            snapshot_date="2026-04-18",
            cash_on_hand_fen=-50_000,  # 透支
            projected_7d_inflow_fen=100_000,
            projected_7d_outflow_fen=80_000,
            days_until_dry=3,
            confidence=0.7,
        )
        assert p.cash_on_hand_fen < 0

    def test_schema_version_default_1_0(self) -> None:
        assert CashFlowSnapshotPayload.schema_version == "1.0"


# ======================================================================
# §5 演进规则验证 (只加不改)
# ======================================================================

class TestSchemaEvolution:
    def test_all_schemas_forbid_extra_fields(self) -> None:
        """所有 schema 继承 extra='forbid', 未知字段被拒."""
        with pytest.raises(ValidationError):
            OrderCreatedPayload(  # type: ignore[call-arg]
                order_id="o",
                store_id="s",
                total_fen=1,
                created_by="e",
                unknown_extra="x",
            )

    def test_all_schemas_are_immutable(self) -> None:
        """所有 schema frozen=True."""
        p = OrderPaidPayload(
            order_id="o",
            store_id="s",
            total_fen=1,
            paid_fen=1,
            payment_method=PaymentMethod.CASH,
            channel=OrderChannel.DINE_IN,
        )
        with pytest.raises(ValidationError):
            p.paid_fen = 999  # type: ignore[misc]
