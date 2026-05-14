"""Tier 1 — yield_standard_service 契约测试（PRD-06 / 毛利底线硬约束）

CLAUDE.md §17 Tier 1 三条硬约束之一：毛利底线 — 任何折扣/赠送不可使单笔毛利低于设定阈值。
PRD-06 扩展：商品出料率标准库 — 每原料维护季节性出料率标准（春菠菜 65% / 夏 50%），
BOM 反算购买量自动除以 yield_rate；实际 vs 标准超 ±tolerance_pct 触发预警。

测试基于真实餐厅场景（CLAUDE.md §20）：

  1. CRUD 4 用例（create/list/get/soft_delete）
  2. 二级审批 2 用例（approve 成功 / self-approve 拒绝）
  3. RLS 1 用例（跨 tenant set_config 必须被调用）
  4. calculate_purchase_qty 4 用例
     - 单 yield_rate 0.65（净 60kg → 毛 ≈ 92.3kg）
     - 多 season 优先级（具体 summer 0.5 优先于 all 0.6）
     - 草稿态不用（list 已审批过滤后 fallback）
     - effective_to 过期不用（DB 过滤后空 list fallback）
  5. Anomaly callback 2 用例（超 tolerance 触发 / 未超不触发）

mock 风格：AsyncMock — 参考 test_weight_standard_service_tier1.py（v428 同模式）。
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

# 本机 Python 3.9 环境 stub 注入会污染 sys.modules（feedback_pytest_stub_setdefault_pitfall.md 教训）
# 故 < 3.10 跳过，CI Python 3.11 真跑（沿用 PR #553 / #633 模式）
if sys.version_info < (3, 10):
    pytest.skip(
        "需要 Python 3.10+（生产环境为 3.11）— 本机 3.9 跳过避免 sys.modules 污染",
        allow_module_level=True,
    )

from services.tx_supply.src.services.yield_standard_service import (  # noqa: E402
    _pick_standard,
    approve_yield_standard,
    calculate_purchase_qty,
    create_yield_standard,
    get_yield_standard,
    list_yield_standards,
    soft_delete_yield_standard,
)


# ─── 测试常量（徐记海鲜餐厅场景）─────────────────────────────────────────────

_TENANT_XUJI = "11111111-aaaa-aaaa-aaaa-111111111111"
_TENANT_CZYZ = "22222222-bbbb-bbbb-bbbb-222222222222"
_INGREDIENT_SPINACH = "aaaaaaaa-0001-0001-0001-aaaaaaaaaaaa"  # 菠菜（春 65% / 夏 50%）
_USER_BUYER = "cccccccc-0003-0003-0003-cccccccccccc"  # 采购总监（创建人）
_USER_FINANCE = "dddddddd-0004-0004-0004-dddddddddddd"  # 财务总监（审批人）
_STD_ID = "eeeeeeee-0005-0005-0005-eeeeeeeeeeee"


# ─── DB Mock 工厂 ────────────────────────────────────────────────────────────


def _mk_db_for_returning(*, returning_row: dict | None) -> AsyncMock:
    """模拟 DB：INSERT/UPDATE ... RETURNING 路径。"""
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        result = MagicMock()

        if "set_config" in sql:
            return MagicMock()

        if "RETURNING" in sql.upper():
            result.mappings.return_value.first.return_value = returning_row
            return result

        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


def _mk_db_for_list(*, rows: list) -> AsyncMock:
    """模拟 DB：list_yield_standards SELECT 路径。"""
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        result = MagicMock()

        if "set_config" in sql:
            return MagicMock()

        if "SELECT" in sql.upper() and "ingredient_yield_standards" in sql:
            result.mappings.return_value.__iter__ = lambda self: iter(rows)
            return result

        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


def _mk_db_for_get(*, row: dict | None) -> AsyncMock:
    """模拟 DB：get_yield_standard 单条 SELECT 路径。"""
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        result = MagicMock()

        if "set_config" in sql:
            return MagicMock()

        if "SELECT" in sql.upper() and "ingredient_yield_standards" in sql:
            result.mappings.return_value.first.return_value = row
            return result

        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


def _mk_db_for_delete(*, affected: int) -> AsyncMock:
    """模拟 DB：UPDATE is_deleted 软删路径。"""
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)

        if "set_config" in sql:
            return MagicMock()

        if "UPDATE ingredient_yield_standards" in sql and "is_deleted = TRUE" in sql:
            result = MagicMock()
            result.rowcount = affected
            return result

        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


def _row_factory(
    *,
    approved_by: str | None = None,
    created_by: str = _USER_BUYER,
    yield_rate: Decimal = Decimal("0.6500"),
    season: str = "all",
    tolerance_pct: Decimal = Decimal("5.0"),
    std_id: str = _STD_ID,
) -> dict:
    """构造一行 standards 字典（list / get 通用）。"""
    return {
        "id": std_id,
        "tenant_id": _TENANT_XUJI,
        "ingredient_id": _INGREDIENT_SPINACH,
        "process_id": None,
        "yield_rate": yield_rate,
        "season": season,
        "effective_from": date(2026, 5, 1),
        "effective_to": None,
        "tolerance_pct": tolerance_pct,
        "approved_by": approved_by,
        "approved_at": datetime(2026, 5, 14, tzinfo=timezone.utc) if approved_by else None,
        "notes": None,
        "created_by": created_by,
        "created_at": datetime(2026, 5, 14, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 5, 14, tzinfo=timezone.utc),
        "is_deleted": False,
    }


# ─── 1. CRUD ──────────────────────────────────────────────────────────────────


class TestCRUD:
    @pytest.mark.asyncio
    async def test_create_returns_draft(self):
        """创建出料率标准 → approved_by=NULL（草稿态）。"""
        row = _row_factory(approved_by=None)
        db = _mk_db_for_returning(returning_row=row)

        result = await create_yield_standard(
            db=db,
            tenant_id=_TENANT_XUJI,
            ingredient_id=_INGREDIENT_SPINACH,
            yield_rate=Decimal("0.65"),
            season="spring",
            effective_from=date(2026, 5, 1),
            created_by=_USER_BUYER,
        )
        assert result["approved_by"] is None, "新建必须草稿态"
        assert result["created_by"] == _USER_BUYER

        # 验证 RLS set_config 被调用
        sqls = [str(call.args[0]) for call in db.execute.call_args_list]
        assert any("set_config" in s for s in sqls), "必须设置 RLS 租户上下文"

    @pytest.mark.asyncio
    async def test_list_only_active_filters_drafts_and_deleted(self):
        """list_yield_standards(only_active=True) 仅返回已审批 + 时效内 + 未删除。"""
        row = _row_factory(approved_by=_USER_FINANCE)
        db = _mk_db_for_list(rows=[row])

        items = await list_yield_standards(
            db=db, tenant_id=_TENANT_XUJI, ingredient_id=_INGREDIENT_SPINACH, only_active=True
        )
        assert len(items) == 1

        # 验证 SQL 包含 active 子句
        sqls = [str(call.args[0]) for call in db.execute.call_args_list]
        active_sql = next((s for s in sqls if "ingredient_yield_standards" in s), "")
        assert "approved_by IS NOT NULL" in active_sql, "active 模式必须过滤 approved_by"
        assert "is_deleted = FALSE" in active_sql, "active 模式必须过滤 is_deleted"
        assert "effective_from" in active_sql, "active 模式必须按时效窗口过滤"

    @pytest.mark.asyncio
    async def test_get_no_lock_default(self):
        """get_yield_standard 默认 lock=False（read-only 路径）。"""
        row = _row_factory(approved_by=_USER_FINANCE)
        db = _mk_db_for_get(row=row)

        result = await get_yield_standard(db, _TENANT_XUJI, _STD_ID)
        assert result is not None
        assert result["id"] == _STD_ID

        sqls = [str(call.args[0]) for call in db.execute.call_args_list]
        select_sql = next((s for s in sqls if "ingredient_yield_standards" in s), "")
        assert "FOR UPDATE" not in select_sql, "默认 lock=False 不应加 FOR UPDATE"

    @pytest.mark.asyncio
    async def test_get_with_lock_adds_for_update(self):
        """get_yield_standard(lock=True) 加 FOR UPDATE（mutation 路径 row-lock pattern）。"""
        row = _row_factory(approved_by=None)
        db = _mk_db_for_get(row=row)

        await get_yield_standard(db, _TENANT_XUJI, _STD_ID, lock=True)

        sqls = [str(call.args[0]) for call in db.execute.call_args_list]
        select_sql = next((s for s in sqls if "ingredient_yield_standards" in s), "")
        assert "FOR UPDATE" in select_sql, "lock=True 必须加 FOR UPDATE 行锁（与 PR-A/B 一致）"

    @pytest.mark.asyncio
    async def test_soft_delete_affected_one_returns_true(self):
        """soft_delete 影响 1 行 → 返回 True。"""
        db = _mk_db_for_delete(affected=1)
        deleted = await soft_delete_yield_standard(db, _TENANT_XUJI, _STD_ID)
        assert deleted is True

    @pytest.mark.asyncio
    async def test_soft_delete_zero_rows_returns_false(self):
        """soft_delete 影响 0 行（已删 / 不存在）→ 返回 False。"""
        db = _mk_db_for_delete(affected=0)
        deleted = await soft_delete_yield_standard(db, _TENANT_XUJI, _STD_ID)
        assert deleted is False


# ─── 2. 二级审批 ──────────────────────────────────────────────────────────────


class TestApprove:
    @pytest.mark.asyncio
    async def test_approve_success_by_independent_user(self):
        """approver_id != created_by → 审批成功，approved_by 写入。"""
        existing = _row_factory(approved_by=None, created_by=_USER_BUYER)
        approved = _row_factory(approved_by=_USER_FINANCE, created_by=_USER_BUYER)

        db = AsyncMock()

        async def execute_side_effect(query, params=None):
            sql = str(query)
            result = MagicMock()
            if "set_config" in sql:
                return MagicMock()
            if "SELECT" in sql.upper() and "ingredient_yield_standards" in sql:
                result.mappings.return_value.first.return_value = existing
                return result
            if "UPDATE ingredient_yield_standards" in sql and "approved_by" in sql:
                result.mappings.return_value.first.return_value = approved
                return result
            return MagicMock()

        db.execute = AsyncMock(side_effect=execute_side_effect)

        result = await approve_yield_standard(
            db=db,
            tenant_id=_TENANT_XUJI,
            std_id=_STD_ID,
            approver_id=_USER_FINANCE,
        )
        assert result["approved_by"] == _USER_FINANCE
        assert result["created_by"] == _USER_BUYER

    @pytest.mark.asyncio
    async def test_self_approve_rejected(self):
        """approver_id == created_by → 拒绝（二级审批必须独立签字）。"""
        existing = _row_factory(approved_by=None, created_by=_USER_BUYER)

        db = AsyncMock()

        async def execute_side_effect(query, params=None):
            sql = str(query)
            result = MagicMock()
            if "set_config" in sql:
                return MagicMock()
            if "SELECT" in sql.upper() and "ingredient_yield_standards" in sql:
                result.mappings.return_value.first.return_value = existing
                return result
            return MagicMock()

        db.execute = AsyncMock(side_effect=execute_side_effect)

        with pytest.raises(ValueError, match="不能与 created_by 相同"):
            await approve_yield_standard(
                db=db,
                tenant_id=_TENANT_XUJI,
                std_id=_STD_ID,
                approver_id=_USER_BUYER,  # ← 自己审自己
            )


# ─── 3. RLS 跨租户隔离 ────────────────────────────────────────────────────────


class TestRLS:
    @pytest.mark.asyncio
    async def test_list_calls_set_config_each_invocation(self):
        """每次 service 调用前必须 set_config('app.tenant_id', :tid, true)。

        RLS 防漂移：query 前不设置租户上下文 → 跨租户数据泄漏 P0.
        """
        db = _mk_db_for_list(rows=[])

        await list_yield_standards(
            db=db, tenant_id=_TENANT_XUJI, ingredient_id=_INGREDIENT_SPINACH
        )
        await list_yield_standards(
            db=db, tenant_id=_TENANT_CZYZ, ingredient_id=_INGREDIENT_SPINACH
        )

        set_config_calls = [
            call for call in db.execute.call_args_list
            if "set_config" in str(call.args[0])
        ]
        assert len(set_config_calls) >= 2, "每次 list 必须独立 set_config（跨租户隔离）"


# ─── 4. calculate_purchase_qty ───────────────────────────────────────────────


class TestCalculatePurchaseQty:
    @pytest.mark.asyncio
    async def test_single_standard_0_65_for_60kg_net(self):
        """场景：徐记海鲜春菠菜 yield_rate=0.65，需净菜 60kg → 毛菜 ≈ 92.3077kg。"""
        row = _row_factory(
            approved_by=_USER_FINANCE,
            yield_rate=Decimal("0.6500"),
            season="all",
        )
        db = _mk_db_for_list(rows=[row])

        purchase_qty, meta = await calculate_purchase_qty(
            db=db,
            tenant_id=_TENANT_XUJI,
            ingredient_id=_INGREDIENT_SPINACH,
            required_net_qty_kg=Decimal("60"),
            season="all",
        )
        # 60 / 0.65 = 92.3076923...
        assert purchase_qty == Decimal("92.3077"), f"60 / 0.65 ≈ 92.3077kg，实际 {purchase_qty}"
        assert meta["standard_id"] == _STD_ID
        assert meta["yield_rate"] == Decimal("0.6500")
        assert meta["season_matched"] == "all"
        assert meta["anomaly_detected"] is False

    @pytest.mark.asyncio
    async def test_specific_season_priority_over_all(self):
        """多 season 优先级：summer 具体 0.5 优先于 all fallback 0.6。

        场景：菠菜 summer standard 0.5 + all standard 0.6，summer 优先用 0.5
        """
        summer_row = _row_factory(
            approved_by=_USER_FINANCE,
            yield_rate=Decimal("0.5000"),
            season="summer",
            std_id="ffffffff-0006-0006-0006-ffffffffffff",
        )
        all_row = _row_factory(
            approved_by=_USER_FINANCE,
            yield_rate=Decimal("0.6000"),
            season="all",
            std_id="eeeeeeee-0005-0005-0005-eeeeeeeeeeee",
        )
        db = _mk_db_for_list(rows=[summer_row, all_row])

        purchase_qty, meta = await calculate_purchase_qty(
            db=db,
            tenant_id=_TENANT_XUJI,
            ingredient_id=_INGREDIENT_SPINACH,
            required_net_qty_kg=Decimal("50"),
            season="summer",
        )
        # 50 / 0.5 = 100kg（用 summer 具体，不是 all 0.6）
        assert purchase_qty == Decimal("100.0000"), f"50 / 0.5 = 100kg，实际 {purchase_qty}"
        assert meta["season_matched"] == "summer", "必须优先 summer 具体匹配"
        assert meta["yield_rate"] == Decimal("0.5000")

    @pytest.mark.asyncio
    async def test_draft_not_applied_fallback_to_original(self):
        """草稿态 standard 不应用（list_yield_standards only_active=True 已过滤）→ fallback 原值。

        本测试验证：DB 端 active 过滤后空 list → calculate_purchase_qty 返回原值（不反算）。
        """
        db = _mk_db_for_list(rows=[])  # DB-level only_active=True 过滤草稿后空

        purchase_qty, meta = await calculate_purchase_qty(
            db=db,
            tenant_id=_TENANT_XUJI,
            ingredient_id=_INGREDIENT_SPINACH,
            required_net_qty_kg=Decimal("60"),
            season="all",
        )
        assert purchase_qty == Decimal("60.0000"), "无 active 标 → fallback 原值"
        assert meta["standard_id"] is None
        assert meta["yield_rate"] is None

    @pytest.mark.asyncio
    async def test_expired_standard_not_applied(self):
        """effective_to 已过期的标准 — DB 端过滤后不返回 → fallback 原值。"""
        db = _mk_db_for_list(rows=[])  # DB 端 effective_to < today 过滤后空

        purchase_qty, meta = await calculate_purchase_qty(
            db=db,
            tenant_id=_TENANT_XUJI,
            ingredient_id=_INGREDIENT_SPINACH,
            required_net_qty_kg=Decimal("60"),
            season="all",
            today=date(2027, 1, 1),  # 远过 effective_to
        )
        assert purchase_qty == Decimal("60.0000"), "过期标 → fallback 原值"
        assert meta["standard_id"] is None

    @pytest.mark.asyncio
    async def test_pick_standard_helper_specific_priority(self):
        """_pick_standard 工具函数：具体 season 优先 'all' fallback。"""
        standards = [
            _row_factory(season="all", yield_rate=Decimal("0.6")),
            _row_factory(season="winter", yield_rate=Decimal("0.55")),
        ]
        picked = _pick_standard(standards, season="winter")
        assert picked is not None
        assert picked["season"] == "winter"

    @pytest.mark.asyncio
    async def test_pick_standard_helper_fallback_to_all(self):
        """_pick_standard：无具体匹配时 fallback 到 'all'。"""
        standards = [_row_factory(season="all", yield_rate=Decimal("0.6"))]
        picked = _pick_standard(standards, season="summer")
        assert picked is not None
        assert picked["season"] == "all"


# ─── 5. Anomaly callback ─────────────────────────────────────────────────────


class TestAnomalyCallback:
    @pytest.mark.asyncio
    async def test_anomaly_triggers_when_actual_exceeds_tolerance(self):
        """实测 vs 标准差超 tolerance_pct → 触发 callback。

        场景：标 yield_rate=0.65 tolerance 5%，实测 0.55（偏差 15.38% > 5%）→ 触发预警
        """
        row = _row_factory(
            approved_by=_USER_FINANCE,
            yield_rate=Decimal("0.6500"),
            tolerance_pct=Decimal("5.0"),
        )
        db = _mk_db_for_list(rows=[row])

        captured: list[dict] = []

        async def on_anomaly(payload: dict) -> None:
            captured.append(payload)

        await calculate_purchase_qty(
            db=db,
            tenant_id=_TENANT_XUJI,
            ingredient_id=_INGREDIENT_SPINACH,
            required_net_qty_kg=Decimal("60"),
            season="all",
            actual_yield_rate=Decimal("0.55"),  # 偏差 (0.65-0.55)/0.65 = 15.38% > tol 5%
            on_anomaly_callback=on_anomaly,
        )
        assert len(captured) == 1, "偏差超 tolerance 必须触发 callback"
        payload = captured[0]
        assert Decimal(payload["diff_pct"]) > Decimal(payload["tolerance_pct"])
        assert payload["standard_yield_rate"] == "0.6500"
        assert payload["actual_yield_rate"] == "0.55"

    @pytest.mark.asyncio
    async def test_anomaly_not_triggered_within_tolerance(self):
        """实测 vs 标准差未超 tolerance_pct → 不触发 callback。

        场景：标 yield_rate=0.65 tolerance 5%，实测 0.64（偏差 1.54% < 5%）→ 不触发
        """
        row = _row_factory(
            approved_by=_USER_FINANCE,
            yield_rate=Decimal("0.6500"),
            tolerance_pct=Decimal("5.0"),
        )
        db = _mk_db_for_list(rows=[row])

        captured: list[dict] = []

        async def on_anomaly(payload: dict) -> None:
            captured.append(payload)

        await calculate_purchase_qty(
            db=db,
            tenant_id=_TENANT_XUJI,
            ingredient_id=_INGREDIENT_SPINACH,
            required_net_qty_kg=Decimal("60"),
            season="all",
            actual_yield_rate=Decimal("0.64"),  # 偏差 1.54% < tolerance 5%
            on_anomaly_callback=on_anomaly,
        )
        assert captured == [], "偏差未超 tolerance 不应触发 callback"
