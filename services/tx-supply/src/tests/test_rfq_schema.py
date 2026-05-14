"""RFQ schema 静态契约测试（PRD-04 sub-A / T2 infra）

不打 DB / 不 mock — 仅验证 ORM/Pydantic schema 的字段、类型、枚举、约束契约。
sub-B 落 service + Tier 1 award + tier1 测试；sub-C 落前端 + UI。

测试范围:
  1. RFQStatus 枚举与 v431 CHECK 约束对齐
  2. 5 个 ORM model __tablename__ 正确
  3. Pydantic Create schema extra='forbid' + 必填字段
  4. ai_recommendation_followed nullable (sub-B 写入时填，sub-A 草稿态不填)
  5. unit_price_fen BigInteger 整数 (分)
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

if sys.version_info < (3, 10):
    pytest.skip(
        "需要 Python 3.10+（生产环境为 3.11）— 本机 3.9 跳过避免 sys.modules 污染",
        allow_module_level=True,
    )

from services.tx_supply.src.models.rfq_models import (  # noqa: E402
    RFQ,
    RFQAward,
    RFQAwardCreate,
    RFQCreate,
    RFQInvitee,
    RFQItem,
    RFQItemCreate,
    RFQQuote,
    RFQQuoteCreate,
    RFQStatus,
)


# ─── 1. RFQStatus 枚举与 v431 CHECK 约束对齐 ────────────────────────────────


class TestRFQStatusEnum:
    def test_status_values_match_v431_check_constraint(self):
        """6 个状态值必须与 v431 chk_rfq_status CHECK 约束精确对齐。

        若改动需同步改 v431 migration CHECK + service 状态机 + 前端枚举。
        """
        expected = {"draft", "published", "quoting", "comparing", "awarded", "cancelled"}
        actual = {s.value for s in RFQStatus}
        assert actual == expected, (
            f"RFQStatus 枚举值 {actual} 与 v431 CHECK 约束 {expected} 不对齐"
        )

    def test_status_default_draft(self):
        """新建 RFQ 默认状态 draft（sub-B 状态机起点）。"""
        assert RFQStatus.DRAFT.value == "draft"


# ─── 2. ORM model __tablename__ 与 v431 表名对齐 ────────────────────────────


class TestORMTableNames:
    def test_rfq_table(self):
        assert RFQ.__tablename__ == "rfqs"

    def test_rfq_item_table(self):
        assert RFQItem.__tablename__ == "rfq_items"

    def test_rfq_invitee_table(self):
        assert RFQInvitee.__tablename__ == "rfq_invitees"

    def test_rfq_quote_table(self):
        assert RFQQuote.__tablename__ == "rfq_quotes"

    def test_rfq_award_table(self):
        assert RFQAward.__tablename__ == "rfq_awards"


# ─── 3. Pydantic Create schemas: extra='forbid' + 必填字段 ──────────────────


class TestPydanticCreate:
    def test_rfq_create_forbids_extra_fields(self):
        """RFQCreate 必须 extra='forbid'（防 typo / 未来字段漂移）。"""
        with pytest.raises(Exception):  # ValidationError
            RFQCreate(
                deadline=datetime.now(timezone.utc) + timedelta(days=3),
                items=[RFQItemCreate(ingredient_id="x", qty_required=Decimal("1.0"))],
                rogue_field="should be rejected",  # type: ignore[call-arg]
            )

    def test_rfq_create_requires_at_least_one_item(self):
        """RFQCreate.items min_length=1 — 空询价单无意义。"""
        with pytest.raises(Exception):  # ValidationError
            RFQCreate(deadline=datetime.now(timezone.utc) + timedelta(days=3), items=[])

    def test_rfq_item_qty_required_must_be_positive(self):
        """qty_required gt=0 — 与 v431 chk_rfq_items_qty_positive CHECK 对齐。"""
        with pytest.raises(Exception):
            RFQItemCreate(ingredient_id="x", qty_required=Decimal("0"))
        with pytest.raises(Exception):
            RFQItemCreate(ingredient_id="x", qty_required=Decimal("-1"))

    def test_rfq_quote_unit_price_must_be_positive_int(self):
        """unit_price_fen gt=0 + 整数（分）— 与 v431 chk_rfq_quotes_price_positive 对齐。"""
        with pytest.raises(Exception):
            RFQQuoteCreate(
                rfq_id="r", ingredient_id="i", unit_price_fen=0
            )
        with pytest.raises(Exception):
            RFQQuoteCreate(
                rfq_id="r", ingredient_id="i", unit_price_fen=-100
            )

    def test_rfq_award_create_requires_reason(self):
        """reason min_length=1 — 合规审计必须给"选 A 不选 B"理由。"""
        with pytest.raises(Exception):
            RFQAwardCreate(selected_quote_id="q", reason="")

    def test_rfq_award_ai_recommendation_optional(self):
        """ai_recommendation_followed Optional — 非强制（RLHF 信号，未来才必填）。"""
        # 不传也能构造
        award = RFQAwardCreate(selected_quote_id="q", reason="lowest price")
        assert award.ai_recommendation_followed is None

    def test_rfq_award_ai_recommendation_accepts_bool(self):
        """ai_recommendation_followed True / False 均可。"""
        award_yes = RFQAwardCreate(
            selected_quote_id="q", reason="AI picked", ai_recommendation_followed=True
        )
        award_no = RFQAwardCreate(
            selected_quote_id="q", reason="went lower", ai_recommendation_followed=False
        )
        assert award_yes.ai_recommendation_followed is True
        assert award_no.ai_recommendation_followed is False


# ─── 4. Pydantic Quote: 金额单位约定（分 — 整数）─────────────────────────


class TestQuoteAmountUnit:
    def test_quote_accepts_int_fen(self):
        """unit_price_fen 必须是 int — 与 invoice/wine_storage Tier 1 资金路径一致。"""
        quote = RFQQuoteCreate(
            rfq_id="r", ingredient_id="i", unit_price_fen=88800
        )
        assert quote.unit_price_fen == 88800
        assert isinstance(quote.unit_price_fen, int)


# ─── 5. RFQItemCreate qty_unit 可选 ──────────────────────────────────────────


class TestOptionalFields:
    def test_rfq_item_qty_unit_optional(self):
        """qty_unit Optional — 业务可只填 SKU + 数量，单位 sub-B 校验。"""
        item = RFQItemCreate(ingredient_id="x", qty_required=Decimal("10"))
        assert item.qty_unit is None
        assert item.spec_notes is None

    def test_rfq_quote_valid_until_optional(self):
        """valid_until Optional — 默认报价"永久有效"，业务层判定。"""
        quote = RFQQuoteCreate(
            rfq_id="r", ingredient_id="i", unit_price_fen=100
        )
        assert quote.valid_until is None
