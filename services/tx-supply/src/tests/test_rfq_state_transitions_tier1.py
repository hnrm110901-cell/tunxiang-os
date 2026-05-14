"""rfq_service state transitions 契约测试（PRD-04 sub-C / Phase 2 W9-W10 / T2 normal）

sub-C 范围：4 state transitions + 供应商报价 + 比价表 + list。

测试基于真实餐厅场景（CLAUDE.md §20）：

  1. publish_rfq  : 仅 draft → published, 其余状态拒绝
  2. close_rfq    : 仅 quoting → comparing, 其余状态拒绝
  3. cancel_rfq   : 任何非终态 → cancelled (reason 必填), awarded/cancelled 拒绝
  4. submit_quote : 邀请校验 + SKU 校验 + ON CONFLICT 覆盖 + 首报跃迁 published→quoting
  5. get_rfq_comparison : 按 SKU 汇总 + AI 推荐 (lowest price)
  6. list_rfqs    : status 过滤 + limit/offset 校验

mock 风格沿用 test_rfq_service_tier1.py — AsyncMock + SQL 字符串匹配。
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

if sys.version_info < (3, 10):
    pytest.skip(
        "需要 Python 3.10+（生产环境为 3.11）— 本机 3.9 跳过避免 sys.modules 污染",
        allow_module_level=True,
    )

from services.tx_supply.src.services.rfq_service import (  # noqa: E402
    cancel_rfq,
    close_rfq,
    get_rfq_comparison,
    list_rfqs,
    publish_rfq,
    submit_quote,
)


# ─── 测试常量（徐记海鲜场景）────────────────────────────────────────────────

_TENANT_XUJI = "11111111-aaaa-aaaa-aaaa-111111111111"
_USER_BUYER = "cccccccc-0003-0003-0003-cccccccccccc"
_RFQ_ID = "eeeeeeee-0005-0005-0005-eeeeeeeeeeee"
_INGREDIENT_ID = "11111111-0008-0008-0008-111111111111"
_INGREDIENT_ID_2 = "11111111-0009-0009-0009-111111111111"
_SUPPLIER_A = "22222222-0009-0009-0009-222222222222"
_SUPPLIER_B = "33333333-000a-000a-000a-333333333333"
_QUOTE_ID = "ffffffff-0006-0006-0006-ffffffffffff"
_INVITEE_ID = "44444444-0001-0001-0001-444444444444"
_ITEM_ID = "55555555-0001-0001-0001-555555555555"


def _rfq_row(*, status: str = "draft", rfq_id: str = _RFQ_ID) -> dict:
    return {
        "id": rfq_id,
        "tenant_id": _TENANT_XUJI,
        "rfq_number": None,
        "initiator_id": _USER_BUYER,
        "deadline": datetime(2026, 6, 1, tzinfo=timezone.utc),
        "status": status,
        "notes": None,
        "created_by": _USER_BUYER,
        "created_at": datetime(2026, 5, 15, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 5, 15, tzinfo=timezone.utc),
        "is_deleted": False,
    }


def _mk_db_transition(*, rfq: dict | None) -> tuple[AsyncMock, list[str]]:
    """模拟 state transition 路径：SELECT rfqs FOR UPDATE → UPDATE rfqs。"""
    sql_log: list[str] = []
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        sql_log.append(sql)
        result = MagicMock()
        if "set_config" in sql:
            return MagicMock()
        if "SELECT" in sql.upper() and "FROM rfqs" in sql:
            result.mappings.return_value.first.return_value = rfq
            return result
        if "UPDATE rfqs" in sql:
            return MagicMock()
        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db, sql_log


def _mk_db_submit_quote(
    *,
    rfq: dict | None,
    invitee_exists: bool = True,
    item_exists: bool = True,
    quote_returning: dict | None = None,
) -> tuple[AsyncMock, list[str]]:
    """模拟 submit_quote 多路径：rfqs SELECT FOR UPDATE → invitee SELECT → item SELECT
    → quotes INSERT ON CONFLICT → invitees UPDATE → rfqs UPDATE (首报)。
    """
    sql_log: list[str] = []
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        sql_log.append(sql)
        result = MagicMock()
        if "set_config" in sql:
            return MagicMock()
        if "SELECT" in sql.upper() and "FROM rfqs" in sql:
            result.mappings.return_value.first.return_value = rfq
            return result
        if "FROM rfq_invitees" in sql and "SELECT" in sql.upper():
            result.mappings.return_value.first.return_value = (
                {"id": _INVITEE_ID} if invitee_exists else None
            )
            return result
        if "FROM rfq_items" in sql and "SELECT" in sql.upper():
            result.mappings.return_value.first.return_value = (
                {"id": _ITEM_ID} if item_exists else None
            )
            return result
        if "INSERT INTO rfq_quotes" in sql:
            result.mappings.return_value.first.return_value = quote_returning
            return result
        if "UPDATE rfqs" in sql:
            # §19 round-1 P1-2: submit_quote 用 rowcount > 0 判定 published→quoting
            # 跃迁是否实际发生 — mock 须显式 set rowcount=1（首报场景）。
            mock = MagicMock()
            mock.rowcount = 1
            return mock
        if "UPDATE rfq_invitees" in sql:
            return MagicMock()
        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db, sql_log


def _mk_db_comparison(
    *,
    rfq: dict | None,
    items: list[dict],
    quotes: list[dict],
) -> AsyncMock:
    """模拟 get_rfq_comparison：rfqs SELECT → items SELECT → quotes SELECT。"""
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        result = MagicMock()
        if "set_config" in sql:
            return MagicMock()
        if "FROM rfqs" in sql and "SELECT" in sql.upper():
            result.mappings.return_value.first.return_value = rfq
            return result
        if "FROM rfq_items" in sql and "SELECT" in sql.upper():
            result.mappings.return_value.all.return_value = items
            return result
        if "FROM rfq_quotes" in sql and "SELECT" in sql.upper():
            result.mappings.return_value.all.return_value = quotes
            return result
        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


def _mk_db_list(rows: list[dict]) -> AsyncMock:
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        result = MagicMock()
        if "set_config" in sql:
            return MagicMock()
        if "FROM rfqs" in sql and "SELECT" in sql.upper():
            result.mappings.return_value.all.return_value = rows
            return result
        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


# ─── 1. publish_rfq ───────────────────────────────────────────────────────────


class TestPublishRFQ:
    @pytest.mark.asyncio
    async def test_publish_draft_succeeds(self):
        """draft → published — 标准成功路径。"""
        db, sql_log = _mk_db_transition(rfq=_rfq_row(status="draft"))
        result = await publish_rfq(db, _TENANT_XUJI, _RFQ_ID)
        assert result["status"] == "published"
        # 校验 FOR UPDATE 行锁 + UPDATE 跃迁
        assert any("FOR UPDATE" in s for s in sql_log), "publish 必须 FOR UPDATE 行锁"
        update_sqls = [s for s in sql_log if "UPDATE rfqs" in s]
        assert update_sqls, "必须 UPDATE rfqs.status"
        assert "published" in update_sqls[0]

    @pytest.mark.asyncio
    async def test_publish_not_found(self):
        db, _ = _mk_db_transition(rfq=None)
        with pytest.raises(ValueError, match="不存在"):
            await publish_rfq(db, _TENANT_XUJI, _RFQ_ID)

    @pytest.mark.parametrize(
        "status", ["published", "quoting", "comparing", "awarded", "cancelled"]
    )
    @pytest.mark.asyncio
    async def test_publish_rejects_non_draft(self, status):
        """非 draft 拒绝 publish — 防止重复发布或绕过状态机。"""
        db, _ = _mk_db_transition(rfq=_rfq_row(status=status))
        with pytest.raises(ValueError, match="仅 'draft' 可 publish"):
            await publish_rfq(db, _TENANT_XUJI, _RFQ_ID)


# ─── 2. close_rfq ─────────────────────────────────────────────────────────────


class TestCloseRFQ:
    @pytest.mark.asyncio
    async def test_close_quoting_succeeds(self):
        """quoting → comparing — 截止收报价进入比价审核。"""
        db, sql_log = _mk_db_transition(rfq=_rfq_row(status="quoting"))
        result = await close_rfq(db, _TENANT_XUJI, _RFQ_ID)
        assert result["status"] == "comparing"
        assert any("FOR UPDATE" in s for s in sql_log)
        update_sqls = [s for s in sql_log if "UPDATE rfqs" in s]
        assert any("comparing" in s for s in update_sqls)

    @pytest.mark.parametrize(
        "status", ["draft", "published", "comparing", "awarded", "cancelled"]
    )
    @pytest.mark.asyncio
    async def test_close_rejects_non_quoting(self, status):
        db, _ = _mk_db_transition(rfq=_rfq_row(status=status))
        with pytest.raises(ValueError, match="仅 'quoting' 可 close"):
            await close_rfq(db, _TENANT_XUJI, _RFQ_ID)

    @pytest.mark.asyncio
    async def test_close_not_found(self):
        db, _ = _mk_db_transition(rfq=None)
        with pytest.raises(ValueError, match="不存在"):
            await close_rfq(db, _TENANT_XUJI, _RFQ_ID)


# ─── 3. cancel_rfq ────────────────────────────────────────────────────────────


class TestCancelRFQ:
    @pytest.mark.asyncio
    async def test_cancel_reason_required(self):
        db, _ = _mk_db_transition(rfq=_rfq_row(status="draft"))
        with pytest.raises(ValueError, match="reason"):
            await cancel_rfq(db, _TENANT_XUJI, _RFQ_ID, reason="   ")

    @pytest.mark.parametrize("status", ["draft", "published", "quoting", "comparing"])
    @pytest.mark.asyncio
    async def test_cancel_non_terminal_succeeds(self, status):
        """任何非终态 → cancelled（含 audit reason 拼接到 notes）。"""
        db, sql_log = _mk_db_transition(rfq=_rfq_row(status=status))
        result = await cancel_rfq(
            db, _TENANT_XUJI, _RFQ_ID, reason="SKU 录错"
        )
        assert result["status"] == "cancelled"
        update_sqls = [s for s in sql_log if "UPDATE rfqs" in s]
        assert any("cancelled" in s for s in update_sqls)
        # notes 拼接 audit reason
        assert any("notes" in s for s in update_sqls)

    @pytest.mark.asyncio
    async def test_cancel_awarded_rejected(self):
        """awarded 是终态, 不可 cancel — 防止已中标后撤单破坏资金链路。"""
        db, _ = _mk_db_transition(rfq=_rfq_row(status="awarded"))
        with pytest.raises(ValueError, match="awarded.*终态"):
            await cancel_rfq(db, _TENANT_XUJI, _RFQ_ID, reason="撤回")

    @pytest.mark.asyncio
    async def test_cancel_already_cancelled_rejected(self):
        """重复 cancel 幂等拒绝。"""
        db, _ = _mk_db_transition(rfq=_rfq_row(status="cancelled"))
        with pytest.raises(ValueError, match="幂等"):
            await cancel_rfq(db, _TENANT_XUJI, _RFQ_ID, reason="dup")

    @pytest.mark.asyncio
    async def test_cancel_not_found(self):
        db, _ = _mk_db_transition(rfq=None)
        with pytest.raises(ValueError, match="不存在"):
            await cancel_rfq(db, _TENANT_XUJI, _RFQ_ID, reason="x")


# ─── 4. submit_quote ──────────────────────────────────────────────────────────


def _quote_returning_row(unit_price_fen: int = 88800) -> dict:
    return {
        "id": _QUOTE_ID,
        "tenant_id": _TENANT_XUJI,
        "rfq_id": _RFQ_ID,
        "supplier_id": _SUPPLIER_A,
        "ingredient_id": _INGREDIENT_ID,
        "unit_price_fen": unit_price_fen,
        "qty_offered": None,
        "valid_until": None,
        "notes": None,
        "submitted_at": datetime(2026, 5, 16, tzinfo=timezone.utc),
    }


class TestSubmitQuote:
    @pytest.mark.asyncio
    async def test_submit_quote_first_time_transitions_to_quoting(self):
        """首报: published → quoting 跃迁 + invitees.responded_at 更新。"""
        db, sql_log = _mk_db_submit_quote(
            rfq=_rfq_row(status="published"),
            invitee_exists=True,
            item_exists=True,
            quote_returning=_quote_returning_row(),
        )
        result = await submit_quote(
            db,
            _TENANT_XUJI,
            _RFQ_ID,
            supplier_id=_SUPPLIER_A,
            ingredient_id=_INGREDIENT_ID,
            unit_price_fen=88800,
        )
        assert result["unit_price_fen"] == 88800
        # 验证关键 SQL: FOR UPDATE + ON CONFLICT + UPDATE rfqs status=quoting
        assert any("FOR UPDATE" in s for s in sql_log)
        assert any("ON CONFLICT" in s for s in sql_log)
        assert any("UPDATE rfqs" in s and "quoting" in s for s in sql_log), (
            "首报必须跃迁 status='published' → 'quoting'"
        )
        assert any("UPDATE rfq_invitees" in s for s in sql_log), (
            "必须更新 invitee.responded_at"
        )

    @pytest.mark.asyncio
    async def test_submit_quote_quoting_status_no_transition(self):
        """已 quoting: 不再跃迁 status (只覆盖报价)。"""
        db, sql_log = _mk_db_submit_quote(
            rfq=_rfq_row(status="quoting"),
            quote_returning=_quote_returning_row(),
        )
        await submit_quote(
            db,
            _TENANT_XUJI,
            _RFQ_ID,
            supplier_id=_SUPPLIER_A,
            ingredient_id=_INGREDIENT_ID,
            unit_price_fen=99900,
        )
        # status 跃迁 UPDATE 不应出现
        rfq_status_updates = [
            s for s in sql_log if "UPDATE rfqs" in s and "quoting" in s
        ]
        assert not rfq_status_updates, "quoting → quoting 不应再跃迁"

    @pytest.mark.parametrize(
        "status", ["draft", "comparing", "awarded", "cancelled"]
    )
    @pytest.mark.asyncio
    async def test_submit_quote_rejects_invalid_status(self, status):
        """非 published/quoting → 拒绝报价。"""
        db, _ = _mk_db_submit_quote(
            rfq=_rfq_row(status=status),
            quote_returning=_quote_returning_row(),
        )
        with pytest.raises(ValueError, match="published.*quoting"):
            await submit_quote(
                db,
                _TENANT_XUJI,
                _RFQ_ID,
                supplier_id=_SUPPLIER_A,
                ingredient_id=_INGREDIENT_ID,
                unit_price_fen=10000,
            )

    @pytest.mark.asyncio
    async def test_submit_quote_rejects_non_invitee(self):
        """非邀请供应商报价 → 拒绝（合规审计 + 防外部刺探）。"""
        db, _ = _mk_db_submit_quote(
            rfq=_rfq_row(status="published"),
            invitee_exists=False,
            quote_returning=_quote_returning_row(),
        )
        with pytest.raises(ValueError, match="未被邀请"):
            await submit_quote(
                db,
                _TENANT_XUJI,
                _RFQ_ID,
                supplier_id=_SUPPLIER_B,  # 未在邀请列表
                ingredient_id=_INGREDIENT_ID,
                unit_price_fen=10000,
            )

    @pytest.mark.asyncio
    async def test_submit_quote_rejects_unknown_ingredient(self):
        """ingredient 不在 rfq_items → 拒绝（防供应商瞎报跨 SKU）。"""
        db, _ = _mk_db_submit_quote(
            rfq=_rfq_row(status="published"),
            invitee_exists=True,
            item_exists=False,
            quote_returning=_quote_returning_row(),
        )
        with pytest.raises(ValueError, match="不在.*明细范围"):
            await submit_quote(
                db,
                _TENANT_XUJI,
                _RFQ_ID,
                supplier_id=_SUPPLIER_A,
                ingredient_id=_INGREDIENT_ID_2,  # 不在 RFQ items
                unit_price_fen=10000,
            )

    @pytest.mark.asyncio
    async def test_submit_quote_rejects_zero_price(self):
        """unit_price_fen <= 0 → 拒绝（CHECK 约束兜底前先服务层校验）。"""
        db, _ = _mk_db_submit_quote(
            rfq=_rfq_row(status="published"),
            quote_returning=_quote_returning_row(),
        )
        with pytest.raises(ValueError, match="unit_price_fen 必须 > 0"):
            await submit_quote(
                db,
                _TENANT_XUJI,
                _RFQ_ID,
                supplier_id=_SUPPLIER_A,
                ingredient_id=_INGREDIENT_ID,
                unit_price_fen=0,
            )

    @pytest.mark.asyncio
    async def test_submit_quote_rejects_negative_qty(self):
        db, _ = _mk_db_submit_quote(
            rfq=_rfq_row(status="published"),
            quote_returning=_quote_returning_row(),
        )
        with pytest.raises(ValueError, match="qty_offered"):
            await submit_quote(
                db,
                _TENANT_XUJI,
                _RFQ_ID,
                supplier_id=_SUPPLIER_A,
                ingredient_id=_INGREDIENT_ID,
                unit_price_fen=100,
                qty_offered=Decimal("-1"),
            )

    @pytest.mark.asyncio
    async def test_submit_quote_uses_on_conflict_upsert(self):
        """覆盖报价路径必须走 ON CONFLICT DO UPDATE (允许供应商截止前修改)。"""
        db, sql_log = _mk_db_submit_quote(
            rfq=_rfq_row(status="quoting"),
            quote_returning=_quote_returning_row(unit_price_fen=77700),
        )
        await submit_quote(
            db,
            _TENANT_XUJI,
            _RFQ_ID,
            supplier_id=_SUPPLIER_A,
            ingredient_id=_INGREDIENT_ID,
            unit_price_fen=77700,
        )
        insert_sql = next((s for s in sql_log if "INSERT INTO rfq_quotes" in s), "")
        assert "ON CONFLICT" in insert_sql
        assert "DO UPDATE" in insert_sql


# ─── 5. get_rfq_comparison ────────────────────────────────────────────────────


class TestGetRFQComparison:
    @pytest.mark.asyncio
    async def test_comparison_aggregates_quotes_and_picks_lowest_as_ai_recommended(self):
        """AI 推荐 = 最低价 quote_id (sub-C heuristic v1)。"""
        items = [
            {
                "id": _ITEM_ID,
                "ingredient_id": _INGREDIENT_ID,
                "qty_required": Decimal("10"),
                "qty_unit": "kg",
                "spec_notes": None,
            }
        ]
        # 两条 quote, 不同价格 — 期望最低价 quote_lowest 是 AI 推荐
        quotes = [
            {
                "quote_id": "quote-lowest-001",
                "supplier_id": _SUPPLIER_A,
                "ingredient_id": _INGREDIENT_ID,
                "unit_price_fen": 80000,
                "qty_offered": None,
                "valid_until": None,
                "notes": None,
                "submitted_at": datetime(2026, 5, 16, tzinfo=timezone.utc),
            },
            {
                "quote_id": "quote-higher-002",
                "supplier_id": _SUPPLIER_B,
                "ingredient_id": _INGREDIENT_ID,
                "unit_price_fen": 99900,
                "qty_offered": None,
                "valid_until": None,
                "notes": None,
                "submitted_at": datetime(2026, 5, 16, tzinfo=timezone.utc),
            },
        ]
        db = _mk_db_comparison(rfq=_rfq_row(status="comparing"), items=items, quotes=quotes)
        result = await get_rfq_comparison(db, _TENANT_XUJI, _RFQ_ID)

        assert result["rfq"]["id"] == _RFQ_ID
        assert len(result["items"]) == 1
        it = result["items"][0]
        assert len(it["quotes"]) == 2
        assert it["ai_recommended_quote_id"] == "quote-lowest-001", (
            "AI 推荐必须是最低价 quote (80000 fen)"
        )
        assert "80000" in it["ai_recommendation_reason"]

    @pytest.mark.asyncio
    async def test_comparison_empty_quotes_no_ai_recommendation(self):
        """无报价 → ai_recommended_quote_id = None, reason='无报价'。"""
        items = [
            {
                "id": _ITEM_ID,
                "ingredient_id": _INGREDIENT_ID,
                "qty_required": Decimal("10"),
                "qty_unit": "kg",
                "spec_notes": None,
            }
        ]
        db = _mk_db_comparison(
            rfq=_rfq_row(status="published"), items=items, quotes=[]
        )
        result = await get_rfq_comparison(db, _TENANT_XUJI, _RFQ_ID)
        assert result["items"][0]["ai_recommended_quote_id"] is None
        assert result["items"][0]["ai_recommendation_reason"] == "无报价"

    @pytest.mark.asyncio
    async def test_comparison_rfq_not_found(self):
        db = _mk_db_comparison(rfq=None, items=[], quotes=[])
        with pytest.raises(ValueError, match="不存在"):
            await get_rfq_comparison(db, _TENANT_XUJI, _RFQ_ID)


# ─── 6. list_rfqs ─────────────────────────────────────────────────────────────


class TestListRFQs:
    @pytest.mark.asyncio
    async def test_list_returns_rows(self):
        rows = [_rfq_row(status="draft"), _rfq_row(status="quoting")]
        db = _mk_db_list(rows)
        result = await list_rfqs(db, _TENANT_XUJI)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_with_status_filter_uses_status_param(self):
        """status_filter 触发不同 SQL 常量 (避免 f-string baseline 守门)。"""
        rows = [_rfq_row(status="awarded")]
        db = _mk_db_list(rows)
        await list_rfqs(db, _TENANT_XUJI, status_filter="awarded")
        sqls = [str(call.args[0]) for call in db.execute.call_args_list]
        rfq_sql = next((s for s in sqls if "FROM rfqs" in s), "")
        assert "status = :status" in rfq_sql

    @pytest.mark.asyncio
    async def test_list_rejects_invalid_limit(self):
        db = _mk_db_list([])
        with pytest.raises(ValueError, match="limit"):
            await list_rfqs(db, _TENANT_XUJI, limit=0)
        with pytest.raises(ValueError, match="limit"):
            await list_rfqs(db, _TENANT_XUJI, limit=300)

    @pytest.mark.asyncio
    async def test_list_rejects_negative_offset(self):
        db = _mk_db_list([])
        with pytest.raises(ValueError, match="offset"):
            await list_rfqs(db, _TENANT_XUJI, offset=-1)
