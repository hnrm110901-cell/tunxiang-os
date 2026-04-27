"""Sprint E4 — 异议工作流测试

覆盖：
  · ResponseTemplate：渲染 / 变量扩展 / suggested_refund / 缺失占位保留
  · list_templates / get_template / recommend_template：类型匹配 + 退到 other
  · render_template 便捷函数：*_fen 自动→*_yuan
  · DisputeIngestInput / MerchantResponseInput / PlatformRulingInput 合法性
  · ALLOWED_TRANSITIONS 状态机：所有合法转换 + 非法拒绝
  · TERMINAL_STATUSES：终态无转出
  · v288 迁移静态断言

不覆盖（需 DB / FastAPI）：
  · DisputeService 方法（需 AsyncSession mock，留 integration test）
  · API 端点
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "services" / "tx-trade" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services.dispute_response_templates import (  # noqa: E402
    BUILTIN_TEMPLATES,
    ResponseTemplate,
    get_template,
    list_templates,
    recommend_template,
    render_template,
)
from services.dispute_service import (  # noqa: E402
    ALLOWED_TRANSITIONS,
    DEFAULT_MERCHANT_SLA,
    TERMINAL_STATUSES,
    DisputeError,
    DisputeIngestInput,
    MerchantResponseInput,
    PlatformRulingInput,
)

# ─────────────────────────────────────────────────────────────
# 1. ResponseTemplate
# ─────────────────────────────────────────────────────────────


class TestResponseTemplate:
    def _template(self) -> ResponseTemplate:
        return ResponseTemplate(
            template_id="test_01",
            dispute_type="missing_item",
            title="test",
            content="订单 {order_no} 退款 {refund_amount_yuan} 元",
            recommended_action="accept_full",
            suggested_refund_ratio=1.0,
        )

    def test_render_basic(self):
        t = self._template()
        out = t.render({"order_no": "MT001", "refund_amount_yuan": "28.00"})
        assert "MT001" in out
        assert "28.00" in out

    def test_render_auto_yuan_from_fen(self):
        """*_fen → *_yuan 自动扩展"""
        t = self._template()
        out = t.render({"order_no": "X", "refund_amount_fen": 2800})
        assert "28.00" in out

    def test_render_keeps_missing_placeholders(self):
        t = self._template()
        out = t.render({"order_no": "X"})
        # refund_amount_yuan 未提供 → 保留占位
        assert "{refund_amount_yuan}" in out

    def test_render_ignores_none_values(self):
        t = self._template()
        out = t.render({"order_no": None, "refund_amount_yuan": "5.00"})
        assert "{order_no}" in out  # None 不替换
        assert "5.00" in out

    def test_suggested_refund_fen(self):
        t = self._template()
        assert t.suggested_refund_fen(10000) == 10000  # 100%

    def test_suggested_refund_fen_with_partial_ratio(self):
        t = ResponseTemplate(
            template_id="t",
            dispute_type="late_delivery",
            title="t",
            content="x",
            recommended_action="offer_partial",
            suggested_refund_ratio=0.3,
        )
        assert t.suggested_refund_fen(10000) == 3000

    def test_suggested_refund_fen_none_when_no_ratio(self):
        t = ResponseTemplate(
            template_id="t", dispute_type="other", title="t",
            content="x", recommended_action="dispute",
        )
        assert t.suggested_refund_fen(10000) is None

    def test_suggested_refund_fen_none_when_no_claim(self):
        t = self._template()
        assert t.suggested_refund_fen(None) is None

    def test_to_dict_contract(self):
        t = self._template()
        d = t.to_dict()
        for key in (
            "template_id", "dispute_type", "title", "content",
            "recommended_action", "suggested_refund_ratio",
        ):
            assert key in d


# ─────────────────────────────────────────────────────────────
# 2. Template Registry
# ─────────────────────────────────────────────────────────────


class TestTemplateRegistry:
    def test_builtin_templates_nonempty(self):
        assert len(BUILTIN_TEMPLATES) >= 15

    def test_list_all_returns_full_set(self):
        assert len(list_templates()) == len(BUILTIN_TEMPLATES)

    def test_list_by_dispute_type(self):
        missing = list_templates("missing_item")
        assert len(missing) >= 1
        assert all(t.dispute_type == "missing_item" for t in missing)

    def test_list_unknown_type_returns_empty(self):
        assert list_templates("nonexistent_type") == []

    def test_get_template_exists(self):
        assert get_template("missing_item_full_refund") is not None

    def test_get_template_unknown_returns_none(self):
        assert get_template("nonexistent") is None

    def test_recommend_template_matches_type(self):
        t = recommend_template("foreign_object")
        assert t is not None
        assert t.dispute_type == "foreign_object"

    def test_recommend_template_falls_back_to_other(self):
        """未注册的 dispute_type 会退到 'other' 类型"""
        t = recommend_template("unknown_type_12345")
        assert t is not None
        assert t.dispute_type == "other"

    def test_all_templates_cover_9_dispute_types(self):
        """确保 9 类 dispute_type 都有至少一个模板"""
        types_covered = {t.dispute_type for t in BUILTIN_TEMPLATES}
        for expected in (
            "quality_issue",
            "missing_item",
            "wrong_item",
            "foreign_object",
            "late_delivery",
            "cold_food",
            "packaging",
            "billing_error",
            "portion_size",
            "service",
            "other",
        ):
            assert expected in types_covered, f"缺少 {expected} 模板"


# ─────────────────────────────────────────────────────────────
# 3. render_template 便捷函数
# ─────────────────────────────────────────────────────────────


class TestRenderTemplateHelper:
    def test_basic_render(self):
        t = get_template("missing_item_full_refund")
        assert t is not None
        out = render_template(
            t,
            order_no="MT001",
            store_name="长沙旗舰店",
            customer_claim_fen=2800,
            dish_names="鱼香肉丝",
        )
        assert "MT001" in out
        assert "长沙旗舰店" in out
        assert "28.00" in out  # refund_amount_yuan 自动换算
        assert "鱼香肉丝" in out

    def test_render_with_extra(self):
        t = get_template("late_delivery_partial_refund_rider_fault")
        assert t is not None
        out = render_template(
            t,
            order_no="MT002",
            customer_claim_fen=5000,
            extra={"delay_minutes": 25, "prep_minutes": 15},
        )
        assert "25" in out
        assert "15" in out

    def test_render_uses_ratio_for_refund(self):
        t = get_template("late_delivery_partial_refund_rider_fault")
        assert t is not None
        out = render_template(
            t,
            order_no="X",
            customer_claim_fen=10000,  # 100 元
            extra={"delay_minutes": 20, "prep_minutes": 10},
        )
        # 30% 退款 = 3000 fen = 30.00 元
        assert "30.00" in out


# ─────────────────────────────────────────────────────────────
# 4. Input dataclass 合法性
# ─────────────────────────────────────────────────────────────


class TestInputValidation:
    def test_ingest_input_defaults_timestamps(self):
        inp = DisputeIngestInput(
            platform="meituan",
            platform_dispute_id="D001",
            platform_order_id="MT001",
            dispute_type="missing_item",
        )
        assert inp.raised_at is not None
        assert inp.raised_at.tzinfo is not None
        assert inp.customer_evidence_urls == []

    def test_ingest_input_custom_sla(self):
        from datetime import timedelta as _td

        inp = DisputeIngestInput(
            platform="meituan",
            platform_dispute_id="D",
            platform_order_id="O",
            dispute_type="other",
            merchant_sla=_td(hours=48),
        )
        assert inp.merchant_sla.total_seconds() == 48 * 3600

    def test_merchant_response_valid_accept_full(self):
        r = MerchantResponseInput(
            action="accept_full",
            response_text="同意全额退款",
        )
        assert r.action == "accept_full"

    def test_merchant_response_valid_offer_partial(self):
        r = MerchantResponseInput(
            action="offer_partial",
            response_text="部分退款",
            offered_refund_fen=1500,
        )
        assert r.offered_refund_fen == 1500

    def test_merchant_response_offer_partial_requires_refund(self):
        with pytest.raises(DisputeError, match="offered_refund_fen"):
            MerchantResponseInput(
                action="offer_partial",
                response_text="t",
                offered_refund_fen=None,
            )

    def test_merchant_response_offer_partial_rejects_negative(self):
        with pytest.raises(DisputeError, match="offered_refund_fen"):
            MerchantResponseInput(
                action="offer_partial",
                response_text="t",
                offered_refund_fen=-100,
            )

    def test_merchant_response_rejects_unknown_action(self):
        with pytest.raises(DisputeError, match="action"):
            MerchantResponseInput(
                action="unknown", response_text="x"
            )

    def test_merchant_response_rejects_empty_text(self):
        with pytest.raises(DisputeError, match="response_text"):
            MerchantResponseInput(action="dispute", response_text="  ")

    def test_merchant_response_dispute_no_refund_required(self):
        """dispute 动作不需要 offered_refund_fen"""
        r = MerchantResponseInput(
            action="dispute",
            response_text="我方无责",
        )
        assert r.offered_refund_fen is None

    def test_platform_ruling_accepts_zero_refund(self):
        r = PlatformRulingInput(
            platform_decision="商家胜诉",
            platform_refund_fen=0,
        )
        assert r.platform_refund_fen == 0


# ─────────────────────────────────────────────────────────────
# 5. 状态机
# ─────────────────────────────────────────────────────────────


class TestStateMachine:
    def test_opened_to_pending_merchant_allowed(self):
        assert "pending_merchant" in ALLOWED_TRANSITIONS["opened"]

    def test_pending_merchant_to_merchant_accepted(self):
        assert "merchant_accepted" in ALLOWED_TRANSITIONS["pending_merchant"]

    def test_pending_merchant_to_merchant_offered(self):
        assert "merchant_offered" in ALLOWED_TRANSITIONS["pending_merchant"]

    def test_pending_merchant_to_merchant_disputed(self):
        assert "merchant_disputed" in ALLOWED_TRANSITIONS["pending_merchant"]

    def test_pending_merchant_to_expired_allowed(self):
        assert "expired" in ALLOWED_TRANSITIONS["pending_merchant"]

    def test_pending_merchant_to_withdrawn(self):
        assert "withdrawn" in ALLOWED_TRANSITIONS["pending_merchant"]

    def test_cannot_skip_straight_to_resolved(self):
        """pending_merchant → resolved_refund_full 必须经过商家响应或 expired"""
        assert "resolved_refund_full" not in ALLOWED_TRANSITIONS["pending_merchant"]

    def test_merchant_disputed_to_platform_reviewing(self):
        assert "platform_reviewing" in ALLOWED_TRANSITIONS["merchant_disputed"]

    def test_platform_reviewing_to_all_resolutions(self):
        allowed = ALLOWED_TRANSITIONS["platform_reviewing"]
        for s in (
            "resolved_refund_full",
            "resolved_refund_partial",
            "resolved_merchant_win",
        ):
            assert s in allowed

    def test_expired_can_recover(self):
        """SLA 过期仍然可以走人工（升级 / 补偿）"""
        allowed = ALLOWED_TRANSITIONS["expired"]
        assert "resolved_refund_full" in allowed
        assert "escalated" in allowed

    def test_terminal_states_have_no_transitions(self):
        for terminal in (
            "resolved_refund_full",
            "resolved_refund_partial",
            "resolved_merchant_win",
            "withdrawn",
        ):
            assert ALLOWED_TRANSITIONS[terminal] == set(), (
                f"终态 {terminal} 不应有转出"
            )

    def test_terminal_statuses_constant(self):
        assert "resolved_refund_full" in TERMINAL_STATUSES
        assert "withdrawn" in TERMINAL_STATUSES
        assert "pending_merchant" not in TERMINAL_STATUSES

    def test_escalated_allows_resolutions(self):
        """人工介入后仍可解决"""
        allowed = ALLOWED_TRANSITIONS["escalated"]
        assert "resolved_refund_full" in allowed
        assert "resolved_refund_partial" in allowed

    def test_default_sla_is_24_hours(self):
        assert DEFAULT_MERCHANT_SLA.total_seconds() == 24 * 3600


# ─────────────────────────────────────────────────────────────
# 6. v288 迁移静态断言
# ─────────────────────────────────────────────────────────────


class TestV288Migration:
    @pytest.fixture
    def migration_source(self) -> str:
        path = (
            ROOT
            / "shared"
            / "db-migrations"
            / "versions"
            / "v288_delivery_disputes.py"
        )
        return path.read_text(encoding="utf-8")

    def test_revision_chain(self, migration_source):
        assert 'revision = "v288_delivery_disputes"' in migration_source
        assert 'down_revision = "v287_xhs_verify"' in migration_source

    def test_both_tables(self, migration_source):
        assert "delivery_disputes" in migration_source
        assert "delivery_dispute_messages" in migration_source

    def test_all_11_dispute_types(self, migration_source):
        for t in (
            "quality_issue",
            "missing_item",
            "wrong_item",
            "foreign_object",
            "late_delivery",
            "cold_food",
            "packaging",
            "billing_error",
            "portion_size",
            "service",
            "other",
        ):
            assert f"'{t}'" in migration_source

    def test_all_13_statuses(self, migration_source):
        for s in (
            "opened",
            "pending_merchant",
            "merchant_accepted",
            "merchant_offered",
            "merchant_disputed",
            "platform_reviewing",
            "resolved_refund_full",
            "resolved_refund_partial",
            "resolved_merchant_win",
            "withdrawn",
            "escalated",
            "expired",
            "error",
        ):
            assert f"'{s}'" in migration_source

    def test_message_sender_roles(self, migration_source):
        for r in ("customer", "merchant", "platform", "agent", "system"):
            assert f"'{r}'" in migration_source

    def test_message_types(self, migration_source):
        for t in ("text", "image", "video", "system_note", "refund_offer", "ruling"):
            assert f"'{t}'" in migration_source

    def test_sla_fields(self, migration_source):
        assert "merchant_deadline_at" in migration_source
        assert "sla_breached" in migration_source

    def test_merchant_and_platform_refund_fields(self, migration_source):
        assert "merchant_offered_refund_fen" in migration_source
        assert "platform_refund_fen" in migration_source
        assert "customer_claim_amount_fen" in migration_source

    def test_unique_idempotent(self, migration_source):
        assert "ux_delivery_disputes_platform_id" in migration_source

    def test_rls_both_tables(self, migration_source):
        assert (
            "ALTER TABLE delivery_disputes ENABLE ROW LEVEL SECURITY"
            in migration_source
        )
        assert (
            "ALTER TABLE delivery_dispute_messages ENABLE ROW LEVEL SECURITY"
            in migration_source
        )

    def test_pending_sla_queue_index(self, migration_source):
        """运营必需的队列索引"""
        assert "idx_delivery_disputes_pending_sla" in migration_source

    def test_breached_scan_index(self, migration_source):
        assert "idx_delivery_disputes_breached" in migration_source

    def test_response_template_id_field(self, migration_source):
        assert "merchant_response_template_id" in migration_source

    def test_raw_payload_preserved(self, migration_source):
        assert "raw_payload" in migration_source


# ─────────────────────────────────────────────────────────────
# 7. SLA helper（纯逻辑不依赖 DB）
# ─────────────────────────────────────────────────────────────


class TestSLADeadlineLogic:
    def test_default_sla_computes_24h_ahead(self):
        raised = datetime(2026, 4, 24, 10, 0, tzinfo=timezone.utc)
        deadline = raised + DEFAULT_MERCHANT_SLA
        assert deadline == datetime(2026, 4, 25, 10, 0, tzinfo=timezone.utc)
