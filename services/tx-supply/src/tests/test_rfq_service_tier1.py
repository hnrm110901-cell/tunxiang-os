"""Tier 1 — rfq_service award 路径契约测试（PRD-04 sub-B / Tier 1 资金路径前置）

CLAUDE.md §17 Tier 1 三条硬约束之一：毛利底线（合规审计 + 二级审批不可绕过）。
PRD-04 award: row-lock + 二级审批 + RLHF 信号 + UNIQUE(rfq_id) 防重复中标。

测试基于真实餐厅场景（CLAUDE.md §20）：

  1. create_rfq 4 用例（基本 / items 写入 / invitees 写入 / RLS set_config / deadline 校验）
  2. get_rfq lock pattern 2 用例（lock=False default 无 FOR UPDATE / lock=True 加 FOR UPDATE）
  3. award_rfq Tier 1 7 用例
     - 二级审批 self-approve 拒绝（approver == created_by）
     - reason 必填校验
     - rfq 不存在 / 已 awarded / 已 cancelled 拒绝
     - quote 跨 rfq 中标拒绝（合规审计）
     - 成功 award + status → 'awarded'
     - ai_recommendation_followed True/False/None 三态写入

mock 风格：AsyncMock — 参考 test_yield_standard_service_tier1.py / test_delivery_window_service_tier1.py
（v428/v429/v430 同模式）。
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
    award_rfq,
    create_rfq,
    get_rfq,
)


# ─── 测试常量（徐记海鲜 RFQ 场景）────────────────────────────────────────────

_TENANT_XUJI = "11111111-aaaa-aaaa-aaaa-111111111111"
_USER_BUYER = "cccccccc-0003-0003-0003-cccccccccccc"  # 采购员（initiator + RFQ.created_by）
_USER_DIRECTOR = "dddddddd-0004-0004-0004-dddddddddddd"  # 采购总监（独立 approver）
_RFQ_ID = "eeeeeeee-0005-0005-0005-eeeeeeeeeeee"
_QUOTE_ID = "ffffffff-0006-0006-0006-ffffffffffff"
_QUOTE_ID_OTHER_RFQ = "00000000-0007-0007-0007-000000000000"
_INGREDIENT_ID = "11111111-0008-0008-0008-111111111111"
_SUPPLIER_A = "22222222-0009-0009-0009-222222222222"
_SUPPLIER_B = "33333333-000a-000a-000a-333333333333"


def _rfq_row(
    *,
    status: str = "draft",
    created_by: str = _USER_BUYER,
    rfq_id: str = _RFQ_ID,
) -> dict:
    """构造 RFQ 主表行（get_rfq 返回值模拟）。"""
    return {
        "id": rfq_id,
        "tenant_id": _TENANT_XUJI,
        "rfq_number": None,
        "initiator_id": created_by,
        "deadline": datetime(2026, 6, 1, tzinfo=timezone.utc),
        "status": status,
        "notes": None,
        "created_by": created_by,
        "created_at": datetime(2026, 5, 15, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 5, 15, tzinfo=timezone.utc),
        "is_deleted": False,
    }


def _quote_row(
    *,
    rfq_id: str = _RFQ_ID,
    quote_id: str = _QUOTE_ID,
    supplier_id: str = _SUPPLIER_A,
    unit_price_fen: int = 88800,
) -> dict:
    return {
        "id": quote_id,
        "rfq_id": rfq_id,
        "supplier_id": supplier_id,
        "ingredient_id": _INGREDIENT_ID,
        "unit_price_fen": unit_price_fen,
    }


# ─── DB Mock 工厂 ────────────────────────────────────────────────────────────


def _mk_db_create() -> tuple[AsyncMock, list]:
    """模拟 create_rfq 多个 INSERT 路径（rfqs + rfq_items + rfq_invitees）。"""
    sql_log: list[str] = []
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        sql_log.append(sql)
        result = MagicMock()
        if "set_config" in sql:
            return MagicMock()
        if "INSERT INTO rfqs" in sql:
            result.mappings.return_value.first.return_value = _rfq_row()
            return result
        if "INSERT INTO rfq_items" in sql:
            result.mappings.return_value.first.return_value = {
                "id": params["id"] if params else "item-id",
                "tenant_id": _TENANT_XUJI,
                "rfq_id": _RFQ_ID,
                "ingredient_id": _INGREDIENT_ID,
                "qty_required": Decimal("10"),
                "qty_unit": "kg",
                "spec_notes": None,
                "created_at": datetime(2026, 5, 15, tzinfo=timezone.utc),
            }
            return result
        if "INSERT INTO rfq_invitees" in sql:
            result.mappings.return_value.first.return_value = {
                "id": params["id"] if params else "invitee-id",
                "tenant_id": _TENANT_XUJI,
                "rfq_id": _RFQ_ID,
                "supplier_id": _SUPPLIER_A,
                "invited_at": datetime(2026, 5, 15, tzinfo=timezone.utc),
                "responded_at": None,
            }
            return result
        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db, sql_log


def _mk_db_get(*, row: dict | None) -> AsyncMock:
    """模拟 get_rfq 单条 SELECT 路径。"""
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        result = MagicMock()
        if "set_config" in sql:
            return MagicMock()
        if "SELECT" in sql.upper() and "FROM rfqs" in sql:
            result.mappings.return_value.first.return_value = row
            return result
        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


def _mk_db_award(
    *,
    rfq: dict | None,
    quote: dict | None,
    award_result: dict | None,
) -> AsyncMock:
    """模拟 award_rfq 多步路径：SELECT rfq FOR UPDATE → SELECT quote → INSERT award → UPDATE rfqs."""
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        result = MagicMock()
        if "set_config" in sql:
            return MagicMock()
        if "SELECT" in sql.upper() and "FROM rfqs" in sql and "FOR UPDATE" in sql:
            result.mappings.return_value.first.return_value = rfq
            return result
        if "SELECT" in sql.upper() and "FROM rfq_quotes" in sql:
            result.mappings.return_value.first.return_value = quote
            return result
        if "INSERT INTO rfq_awards" in sql:
            result.mappings.return_value.first.return_value = award_result
            return result
        if "UPDATE rfqs" in sql:
            return MagicMock()
        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


# ─── 1. create_rfq ────────────────────────────────────────────────────────────


class TestCreateRFQ:
    @pytest.mark.asyncio
    async def test_create_rfq_returns_draft_with_items_and_invitees(self):
        """create_rfq 写入 rfqs + items + invitees，返回 status='draft'。"""
        db, sql_log = _mk_db_create()
        future = datetime.now(timezone.utc) + timedelta(days=7)
        result = await create_rfq(
            db,
            _TENANT_XUJI,
            initiator_id=_USER_BUYER,
            deadline=future,
            items=[
                {
                    "ingredient_id": _INGREDIENT_ID,
                    "qty_required": Decimal("10"),
                    "qty_unit": "kg",
                }
            ],
            invited_supplier_ids=[_SUPPLIER_A, _SUPPLIER_B],
            created_by=_USER_BUYER,
        )
        assert result["status"] == "draft"
        assert len(result["items"]) == 1
        assert len(result["invitees"]) == 2

        # 验证 SQL 顺序：rfqs INSERT → items INSERT → invitees INSERT
        inserts = [s for s in sql_log if "INSERT INTO" in s]
        assert any("rfqs" in s for s in inserts)
        assert any("rfq_items" in s for s in inserts)
        assert any("rfq_invitees" in s for s in inserts)

    @pytest.mark.asyncio
    async def test_create_rfq_rejects_past_deadline(self):
        """deadline 必须在未来 — 防止采购员误填过期 RFQ。"""
        db, _ = _mk_db_create()
        past = datetime.now(timezone.utc) - timedelta(days=1)
        with pytest.raises(ValueError, match="deadline"):
            await create_rfq(
                db,
                _TENANT_XUJI,
                initiator_id=_USER_BUYER,
                deadline=past,
                items=[{"ingredient_id": _INGREDIENT_ID, "qty_required": Decimal("1")}],
                invited_supplier_ids=[_SUPPLIER_A],
                created_by=_USER_BUYER,
            )

    @pytest.mark.asyncio
    async def test_create_rfq_rejects_empty_items(self):
        """空 items 列表拒绝 — 询价单必须至少一项 SKU。"""
        db, _ = _mk_db_create()
        future = datetime.now(timezone.utc) + timedelta(days=7)
        with pytest.raises(ValueError, match="至少"):
            await create_rfq(
                db,
                _TENANT_XUJI,
                initiator_id=_USER_BUYER,
                deadline=future,
                items=[],
                invited_supplier_ids=[_SUPPLIER_A],
                created_by=_USER_BUYER,
            )

    @pytest.mark.asyncio
    async def test_create_rfq_sets_tenant_rls(self):
        """每次 create 前调 set_config('app.tenant_id') — RLS 强制。"""
        db, sql_log = _mk_db_create()
        future = datetime.now(timezone.utc) + timedelta(days=7)
        await create_rfq(
            db,
            _TENANT_XUJI,
            initiator_id=_USER_BUYER,
            deadline=future,
            items=[{"ingredient_id": _INGREDIENT_ID, "qty_required": Decimal("1")}],
            invited_supplier_ids=[],
            created_by=_USER_BUYER,
        )
        assert any("set_config" in s for s in sql_log), "必须设置 RLS 租户上下文"


# ─── 2. get_rfq lock pattern ────────────────────────────────────────────────


class TestGetRFQLockPattern:
    @pytest.mark.asyncio
    async def test_get_rfq_no_lock_default(self):
        """get_rfq 默认 lock=False（read-only 路径）— 无 FOR UPDATE。"""
        db = _mk_db_get(row=_rfq_row())
        result = await get_rfq(db, _TENANT_XUJI, _RFQ_ID)
        assert result is not None
        sqls = [str(call.args[0]) for call in db.execute.call_args_list]
        rfq_sql = next((s for s in sqls if "FROM rfqs" in s), "")
        assert "FOR UPDATE" not in rfq_sql, "默认 lock=False 不应加 FOR UPDATE"

    @pytest.mark.asyncio
    async def test_get_rfq_with_lock_adds_for_update(self):
        """get_rfq(lock=True) 加 FOR UPDATE — mutation 路径行锁（PR-A/B/C/D/E pattern）。"""
        db = _mk_db_get(row=_rfq_row())
        await get_rfq(db, _TENANT_XUJI, _RFQ_ID, lock=True)
        sqls = [str(call.args[0]) for call in db.execute.call_args_list]
        rfq_sql = next((s for s in sqls if "FROM rfqs" in s), "")
        assert "FOR UPDATE" in rfq_sql, "lock=True 必须加 FOR UPDATE 行锁"


# ─── 3. award_rfq Tier 1 ────────────────────────────────────────────────────


class TestAwardRFQTier1:
    @pytest.mark.asyncio
    async def test_award_reason_required(self):
        """reason 必填 — 合规审计（选 A 不选 B 的理由）。"""
        db = _mk_db_award(rfq=None, quote=None, award_result=None)
        with pytest.raises(ValueError, match="reason"):
            await award_rfq(
                db,
                _TENANT_XUJI,
                _RFQ_ID,
                selected_quote_id=_QUOTE_ID,
                reason="   ",  # whitespace only
                approver_id=_USER_DIRECTOR,
            )

    @pytest.mark.asyncio
    async def test_award_rfq_not_found(self):
        """rfq_id 不存在 → ValueError 不存在。"""
        db = _mk_db_award(rfq=None, quote=None, award_result=None)
        with pytest.raises(ValueError, match="不存在"):
            await award_rfq(
                db,
                _TENANT_XUJI,
                _RFQ_ID,
                selected_quote_id=_QUOTE_ID,
                reason="lowest",
                approver_id=_USER_DIRECTOR,
            )

    @pytest.mark.asyncio
    async def test_award_already_awarded_rejected(self):
        """rfq.status='awarded' → 拒绝重复中标。"""
        db = _mk_db_award(
            rfq=_rfq_row(status="awarded"),
            quote=None,
            award_result=None,
        )
        with pytest.raises(ValueError, match="已 award"):
            await award_rfq(
                db,
                _TENANT_XUJI,
                _RFQ_ID,
                selected_quote_id=_QUOTE_ID,
                reason="lowest",
                approver_id=_USER_DIRECTOR,
            )

    @pytest.mark.asyncio
    async def test_award_cancelled_rejected(self):
        """rfq.status='cancelled' → 拒绝 award。"""
        db = _mk_db_award(
            rfq=_rfq_row(status="cancelled"),
            quote=None,
            award_result=None,
        )
        with pytest.raises(ValueError, match="已 cancel"):
            await award_rfq(
                db,
                _TENANT_XUJI,
                _RFQ_ID,
                selected_quote_id=_QUOTE_ID,
                reason="lowest",
                approver_id=_USER_DIRECTOR,
            )

    @pytest.mark.asyncio
    async def test_award_db_level_self_approve_rejected(self):
        """approver_id == rfq.created_by → DB 层校验拒绝（防 self-approve）。

        §19 round-1 P1-A 教训：路由层无法可靠得知 rfq.created_by，参数层 self-approve
        检查已删除，DB 层 (rfq.created_by != approver_id) 是唯一 SoT。
        """
        db = _mk_db_award(
            rfq=_rfq_row(created_by=_USER_BUYER),  # rfq 由采购员创建
            quote=None,
            award_result=None,
        )
        with pytest.raises(ValueError, match="不能与 rfq.created_by"):
            await award_rfq(
                db,
                _TENANT_XUJI,
                _RFQ_ID,
                selected_quote_id=_QUOTE_ID,
                reason="lowest",
                approver_id=_USER_BUYER,  # approver 与 rfq.created_by 同 → DB 层拒绝
            )

    @pytest.mark.asyncio
    async def test_award_quote_must_belong_to_rfq(self):
        """selected_quote_id 必须属于本 rfq — 合规审计防跨 rfq 中标。"""
        db = _mk_db_award(
            rfq=_rfq_row(),
            quote=None,  # quote SELECT 返回 None — 不属于本 rfq
            award_result=None,
        )
        with pytest.raises(ValueError, match="不属于"):
            await award_rfq(
                db,
                _TENANT_XUJI,
                _RFQ_ID,
                selected_quote_id=_QUOTE_ID_OTHER_RFQ,
                reason="lowest",
                approver_id=_USER_DIRECTOR,
            )

    @pytest.mark.asyncio
    async def test_award_for_update_lock_used(self):
        """award_rfq 内部调 get_rfq(lock=True) — SELECT FOR UPDATE 行锁串行化。"""
        award_dict = {
            "id": "award-id",
            "tenant_id": _TENANT_XUJI,
            "rfq_id": _RFQ_ID,
            "selected_quote_id": _QUOTE_ID,
            "reason": "lowest",
            "ai_recommendation_followed": True,
            "approved_by": _USER_DIRECTOR,
            "approved_at": datetime(2026, 5, 15, tzinfo=timezone.utc),
            "created_by": _USER_BUYER,
            "created_at": datetime(2026, 5, 15, tzinfo=timezone.utc),
        }
        db = _mk_db_award(
            rfq=_rfq_row(),
            quote=_quote_row(),
            award_result=award_dict,
        )
        await award_rfq(
            db,
            _TENANT_XUJI,
            _RFQ_ID,
            selected_quote_id=_QUOTE_ID,
            reason="lowest",
            approver_id=_USER_DIRECTOR,
            ai_recommendation_followed=True,
        )
        sqls = [str(call.args[0]) for call in db.execute.call_args_list]
        rfq_select = next((s for s in sqls if "FROM rfqs" in s and "FOR UPDATE" in s), "")
        assert rfq_select, "award 路径必须用 SELECT FOR UPDATE 串行化（PR-A/B/C/D/E pattern）"

    @pytest.mark.asyncio
    async def test_award_rlhf_followed_true(self):
        """ai_recommendation_followed=True 写入（采购员采纳 AI 推荐）。"""
        award_dict = {
            "id": "award-id",
            "tenant_id": _TENANT_XUJI,
            "rfq_id": _RFQ_ID,
            "selected_quote_id": _QUOTE_ID,
            "reason": "AI recommend",
            "ai_recommendation_followed": True,
            "approved_by": _USER_DIRECTOR,
            "approved_at": datetime(2026, 5, 15, tzinfo=timezone.utc),
            "created_by": _USER_BUYER,
            "created_at": datetime(2026, 5, 15, tzinfo=timezone.utc),
        }
        db = _mk_db_award(
            rfq=_rfq_row(),
            quote=_quote_row(),
            award_result=award_dict,
        )
        result = await award_rfq(
            db,
            _TENANT_XUJI,
            _RFQ_ID,
            selected_quote_id=_QUOTE_ID,
            reason="AI recommend",
            approver_id=_USER_DIRECTOR,
            ai_recommendation_followed=True,
        )
        assert result["ai_recommendation_followed"] is True

    @pytest.mark.asyncio
    async def test_award_rlhf_followed_false(self):
        """ai_recommendation_followed=False（采购员未采纳 AI — 关键 RLHF 信号）。"""
        award_dict = {
            "id": "award-id",
            "tenant_id": _TENANT_XUJI,
            "rfq_id": _RFQ_ID,
            "selected_quote_id": _QUOTE_ID,
            "reason": "went lower",
            "ai_recommendation_followed": False,
            "approved_by": _USER_DIRECTOR,
            "approved_at": datetime(2026, 5, 15, tzinfo=timezone.utc),
            "created_by": _USER_BUYER,
            "created_at": datetime(2026, 5, 15, tzinfo=timezone.utc),
        }
        db = _mk_db_award(
            rfq=_rfq_row(),
            quote=_quote_row(),
            award_result=award_dict,
        )
        result = await award_rfq(
            db,
            _TENANT_XUJI,
            _RFQ_ID,
            selected_quote_id=_QUOTE_ID,
            reason="went lower",
            approver_id=_USER_DIRECTOR,
            ai_recommendation_followed=False,
        )
        assert result["ai_recommendation_followed"] is False

    @pytest.mark.asyncio
    async def test_award_rfqs_status_updated_to_awarded(self):
        """award 成功后 UPDATE rfqs.status='awarded'（同事务原子）。"""
        award_dict = {
            "id": "award-id",
            "tenant_id": _TENANT_XUJI,
            "rfq_id": _RFQ_ID,
            "selected_quote_id": _QUOTE_ID,
            "reason": "lowest",
            "ai_recommendation_followed": None,
            "approved_by": _USER_DIRECTOR,
            "approved_at": datetime(2026, 5, 15, tzinfo=timezone.utc),
            "created_by": _USER_BUYER,
            "created_at": datetime(2026, 5, 15, tzinfo=timezone.utc),
        }
        db = _mk_db_award(
            rfq=_rfq_row(),
            quote=_quote_row(),
            award_result=award_dict,
        )
        await award_rfq(
            db,
            _TENANT_XUJI,
            _RFQ_ID,
            selected_quote_id=_QUOTE_ID,
            reason="lowest",
            approver_id=_USER_DIRECTOR,
        )
        sqls = [str(call.args[0]) for call in db.execute.call_args_list]
        update_sql = next((s for s in sqls if "UPDATE rfqs" in s and "awarded" in s), "")
        assert update_sql, "award 成功必须 UPDATE rfqs.status='awarded'"
