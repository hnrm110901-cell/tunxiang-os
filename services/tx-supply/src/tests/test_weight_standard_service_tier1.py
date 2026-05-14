"""Tier 1 — weight_standard_service 契约测试（PRD-02 / 毛利底线硬约束）

CLAUDE.md §17 Tier 1 三条硬约束之一：毛利底线 — 任何折扣/赠送不可使单笔毛利低于设定阈值。
PRD-02 扩展：商品扣秤标准库 — 每 SKU 维护标准扣秤项 → 收货时自动扣秤 → 超过 ±tolerance_pct 报警。

测试基于真实餐厅场景（CLAUDE.md §20）：

  1. CRUD 4 用例（create/list/get/soft_delete）
  2. 二级审批 2 用例（approve 成功 / self-approve 拒绝）
  3. RLS 1 用例（跨 tenant set_config 必须被调用）
  4. calculate_net_weight 4 用例
     - 单类 ice 8%（毛重 100kg → 净 92kg）
     - 多类叠加 ice 8% + packaging 0.3kg（毛重 100kg → 净 91.7kg）
     - fixed_kg 类（毛重 50kg packaging 0.3kg → 净 49.7kg）
     - effective_to 过期标准不应用
  5. Anomaly callback 2 用例（超 tolerance 触发 / 未超不触发）

mock 风格：AsyncMock — 参考 test_doc_number_tier1.py / test_cert_blocking_tier1.py。
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

# 本机 Python 3.9 环境 stub 注入会污染 sys.modules（feedback_pytest_stub_setdefault_pitfall.md 教训）
# 故 < 3.10 跳过，CI Python 3.11 真跑（沿用 PR #553 模式）
if sys.version_info < (3, 10):
    pytest.skip(
        "需要 Python 3.10+（生产环境为 3.11）— 本机 3.9 跳过避免 sys.modules 污染",
        allow_module_level=True,
    )

from services.tx_supply.src.services.weight_standard_service import (  # noqa: E402
    _apply_deduction,
    approve_weight_standard,
    calculate_net_weight,
    create_weight_standard,
    get_weight_standard,
    list_weight_standards,
    record_weight_deduction,
    soft_delete_weight_standard,
)


# ─── 测试常量（徐记海鲜餐厅场景）─────────────────────────────────────────────

_TENANT_XUJI = "11111111-aaaa-aaaa-aaaa-111111111111"
_TENANT_CZYZ = "22222222-bbbb-bbbb-bbbb-222222222222"
_INGREDIENT_FISH = "aaaaaaaa-0001-0001-0001-aaaaaaaaaaaa"  # 海鲜（鲈鱼，冰块 8% 标）
_INGREDIENT_VEG = "bbbbbbbb-0002-0002-0002-bbbbbbbbbbbb"  # 蔬菜（菜叶损耗 12% 标）
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
    """模拟 DB：list_weight_standards SELECT 路径。"""
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        result = MagicMock()

        if "set_config" in sql:
            return MagicMock()

        if "SELECT" in sql.upper() and "ingredient_weight_standards" in sql:
            result.mappings.return_value.__iter__ = lambda self: iter(rows)
            return result

        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


def _mk_db_for_get(*, row: dict | None) -> AsyncMock:
    """模拟 DB：get_weight_standard 单条 SELECT 路径。"""
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        result = MagicMock()

        if "set_config" in sql:
            return MagicMock()

        if "SELECT" in sql.upper() and "ingredient_weight_standards" in sql:
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

        if "UPDATE ingredient_weight_standards" in sql and "is_deleted = TRUE" in sql:
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
    deduct_type: str = "ice",
    deduct_method: str = "percentage",
    deduct_value: Decimal = Decimal("8.0"),
    tolerance_pct: Decimal = Decimal("2.0"),
) -> dict:
    """构造一行 standards 字典（list / get 通用）。"""
    return {
        "id": _STD_ID,
        "tenant_id": _TENANT_XUJI,
        "ingredient_id": _INGREDIENT_FISH,
        "deduct_type": deduct_type,
        "deduct_method": deduct_method,
        "deduct_value": deduct_value,
        "tolerance_pct": tolerance_pct,
        "effective_from": date(2026, 5, 1),
        "effective_to": None,
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
        """创建扣秤标准 → approved_by=NULL（草稿态）。"""
        row = _row_factory(approved_by=None)
        db = _mk_db_for_returning(returning_row=row)

        result = await create_weight_standard(
            db=db,
            tenant_id=_TENANT_XUJI,
            ingredient_id=_INGREDIENT_FISH,
            deduct_type="ice",
            deduct_method="percentage",
            deduct_value=Decimal("8.0"),
            effective_from=date(2026, 5, 1),
            created_by=_USER_BUYER,
        )
        assert result["approved_by"] is None, "新建必须草稿态"
        assert result["deduct_type"] == "ice"
        assert result["created_by"] == _USER_BUYER

        # 验证 RLS set_config 被调用
        sqls = [str(call.args[0]) for call in db.execute.call_args_list]
        assert any("set_config" in s for s in sqls), "必须设置 RLS 租户上下文"

    @pytest.mark.asyncio
    async def test_list_only_active_filters_drafts_and_deleted(self):
        """list_weight_standards(only_active=True) 仅返回已审批 + 时效内 + 未删除。"""
        # mock 端无需复杂过滤（DB-level 子句负责）— 只验证查询参数 + SQL 包含 active 子句
        row = _row_factory(approved_by=_USER_FINANCE)
        db = _mk_db_for_list(rows=[row])

        items = await list_weight_standards(
            db=db, tenant_id=_TENANT_XUJI, ingredient_id=_INGREDIENT_FISH, only_active=True
        )
        assert len(items) == 1

        # 验证 SQL 包含 active 子句
        sqls = [str(call.args[0]) for call in db.execute.call_args_list]
        active_sql = next((s for s in sqls if "ingredient_weight_standards" in s), "")
        assert "approved_by IS NOT NULL" in active_sql, "active 模式必须过滤 approved_by"
        assert "is_deleted = FALSE" in active_sql, "active 模式必须过滤 is_deleted"
        assert "effective_from" in active_sql, "active 模式必须按时效窗口过滤"

    @pytest.mark.asyncio
    async def test_get_no_lock_default(self):
        """get_weight_standard 默认 lock=False（read-only 路径）。"""
        row = _row_factory(approved_by=_USER_FINANCE)
        db = _mk_db_for_get(row=row)

        result = await get_weight_standard(db, _TENANT_XUJI, _STD_ID)
        assert result is not None
        assert result["id"] == _STD_ID

        sqls = [str(call.args[0]) for call in db.execute.call_args_list]
        select_sql = next((s for s in sqls if "ingredient_weight_standards" in s), "")
        assert "FOR UPDATE" not in select_sql, "默认 lock=False 不应加 FOR UPDATE"

    @pytest.mark.asyncio
    async def test_get_with_lock_adds_for_update(self):
        """get_weight_standard(lock=True) 加 FOR UPDATE（mutation 路径 row-lock pattern）。"""
        row = _row_factory(approved_by=None)
        db = _mk_db_for_get(row=row)

        await get_weight_standard(db, _TENANT_XUJI, _STD_ID, lock=True)

        sqls = [str(call.args[0]) for call in db.execute.call_args_list]
        select_sql = next((s for s in sqls if "ingredient_weight_standards" in s), "")
        assert "FOR UPDATE" in select_sql, "lock=True 必须加 FOR UPDATE 行锁（与 PR-A/B 一致）"

    @pytest.mark.asyncio
    async def test_soft_delete_affected_one_returns_true(self):
        """soft_delete 影响 1 行 → 返回 True。"""
        db = _mk_db_for_delete(affected=1)
        deleted = await soft_delete_weight_standard(db, _TENANT_XUJI, _STD_ID)
        assert deleted is True

    @pytest.mark.asyncio
    async def test_soft_delete_zero_rows_returns_false(self):
        """soft_delete 影响 0 行（已删 / 不存在）→ 返回 False。"""
        db = _mk_db_for_delete(affected=0)
        deleted = await soft_delete_weight_standard(db, _TENANT_XUJI, _STD_ID)
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
            if "SELECT" in sql.upper() and "ingredient_weight_standards" in sql:
                # get_weight_standard(lock=True) call
                result.mappings.return_value.first.return_value = existing
                return result
            if "UPDATE ingredient_weight_standards" in sql and "approved_by" in sql:
                result.mappings.return_value.first.return_value = approved
                return result
            return MagicMock()

        db.execute = AsyncMock(side_effect=execute_side_effect)

        result = await approve_weight_standard(
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
            if "SELECT" in sql.upper() and "ingredient_weight_standards" in sql:
                result.mappings.return_value.first.return_value = existing
                return result
            return MagicMock()

        db.execute = AsyncMock(side_effect=execute_side_effect)

        with pytest.raises(ValueError, match="不能与 created_by 相同"):
            await approve_weight_standard(
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

        await list_weight_standards(
            db=db, tenant_id=_TENANT_XUJI, ingredient_id=_INGREDIENT_FISH
        )
        await list_weight_standards(
            db=db, tenant_id=_TENANT_CZYZ, ingredient_id=_INGREDIENT_FISH
        )

        # 两次调用都必须各自 set_config
        set_config_calls = [
            call for call in db.execute.call_args_list
            if "set_config" in str(call.args[0])
        ]
        assert len(set_config_calls) >= 2, "每次 list 必须独立 set_config（跨租户隔离）"


# ─── 4. calculate_net_weight ─────────────────────────────────────────────────


class TestCalculateNetWeight:
    @pytest.mark.asyncio
    async def test_single_ice_8pct_on_100kg(self):
        """场景：徐记海鲜鲈鱼，毛重 100kg + 冰块 8% 标 → 净 92kg。"""
        row = _row_factory(
            approved_by=_USER_FINANCE,
            deduct_type="ice",
            deduct_method="percentage",
            deduct_value=Decimal("8.0"),
        )
        db = _mk_db_for_list(rows=[row])

        net, applied = await calculate_net_weight(
            db=db,
            tenant_id=_TENANT_XUJI,
            ingredient_id=_INGREDIENT_FISH,
            gross_weight_kg=Decimal("100"),
        )
        assert net == Decimal("92.0000"), f"100kg - 8% = 92kg，实际 {net}"
        assert len(applied) == 1
        assert applied[0]["deduct_type"] == "ice"
        assert applied[0]["deduction_kg"] == "8.0000"

    @pytest.mark.asyncio
    async def test_multi_deductions_stack(self):
        """多类叠加：100kg + ice 8% + packaging 0.3kg → 100 - 8 - 0.3 = 91.7kg。"""
        rows = [
            _row_factory(
                approved_by=_USER_FINANCE,
                deduct_type="ice",
                deduct_method="percentage",
                deduct_value=Decimal("8.0"),
            ),
            _row_factory(
                approved_by=_USER_FINANCE,
                deduct_type="packaging",
                deduct_method="fixed_kg",
                deduct_value=Decimal("0.3"),
            ),
        ]
        db = _mk_db_for_list(rows=rows)

        net, applied = await calculate_net_weight(
            db=db,
            tenant_id=_TENANT_XUJI,
            ingredient_id=_INGREDIENT_FISH,
            gross_weight_kg=Decimal("100"),
        )
        assert net == Decimal("91.7000"), f"100 - 8 - 0.3 = 91.7kg，实际 {net}"
        assert len(applied) == 2, "两类扣秤都必须 applied"

    @pytest.mark.asyncio
    async def test_fixed_kg_only(self):
        """场景：纯 fixed_kg — packaging 0.3kg 标，毛重 50kg → 净 49.7kg。"""
        row = _row_factory(
            approved_by=_USER_FINANCE,
            deduct_type="packaging",
            deduct_method="fixed_kg",
            deduct_value=Decimal("0.3"),
        )
        db = _mk_db_for_list(rows=[row])

        net, _ = await calculate_net_weight(
            db=db,
            tenant_id=_TENANT_XUJI,
            ingredient_id=_INGREDIENT_FISH,
            gross_weight_kg=Decimal("50"),
        )
        assert net == Decimal("49.7000"), f"50 - 0.3 = 49.7kg，实际 {net}"

    @pytest.mark.asyncio
    async def test_expired_standard_not_applied(self):
        """effective_to 已过期的标准 — DB 端过滤（list_weight_standards only_active=True）后不返回。

        本测试验证 calculate_net_weight 接收空 list 时直接返回 gross 全额（无扣秤）。
        """
        db = _mk_db_for_list(rows=[])  # DB 端 effective_to < today 过滤后空 list

        net, applied = await calculate_net_weight(
            db=db,
            tenant_id=_TENANT_XUJI,
            ingredient_id=_INGREDIENT_FISH,
            gross_weight_kg=Decimal("100"),
            today=date(2027, 1, 1),  # 强制使用 2027 today（远过 effective_to）
        )
        assert net == Decimal("100.0000"), "无 active 标 → 净重等于毛重"
        assert applied == [], "无 active 标 → applied 为空"

    @pytest.mark.asyncio
    async def test_apply_deduction_helper_percentage(self):
        """_apply_deduction percentage 方法：100kg × 8% = 8kg。"""
        assert _apply_deduction(Decimal("100"), "percentage", Decimal("8.0")) == Decimal("8.0000")

    @pytest.mark.asyncio
    async def test_apply_deduction_helper_fixed_kg(self):
        """_apply_deduction fixed_kg 方法：直接返回 value。"""
        assert _apply_deduction(Decimal("100"), "fixed_kg", Decimal("0.3")) == Decimal("0.3000")


# ─── 5. Anomaly callback ─────────────────────────────────────────────────────


class TestAnomalyCallback:
    @pytest.mark.asyncio
    async def test_anomaly_triggers_when_actual_exceeds_tolerance(self):
        """实测 vs 标准差超 tolerance_pct → 触发 callback。

        场景：标 ice 8% tolerance 2%，毛重 100kg 实测扣 11kg（标 8kg, 偏差 3%）→ 触发预警
        """
        row = _row_factory(
            approved_by=_USER_FINANCE,
            deduct_method="percentage",
            deduct_value=Decimal("8.0"),
            tolerance_pct=Decimal("2.0"),
        )
        db = _mk_db_for_list(rows=[row])

        captured: list[dict] = []

        async def on_anomaly(payload: dict) -> None:
            captured.append(payload)

        await calculate_net_weight(
            db=db,
            tenant_id=_TENANT_XUJI,
            ingredient_id=_INGREDIENT_FISH,
            gross_weight_kg=Decimal("100"),
            actual_total_deduction_kg=Decimal("11"),  # 标 8, 实 11 → 偏差 3% > tolerance 2%
            on_anomaly_callback=on_anomaly,
        )
        assert len(captured) == 1, "偏差超 tolerance 必须触发 callback"
        payload = captured[0]
        assert Decimal(payload["diff_pct"]) > Decimal(payload["tolerance_pct"])
        assert payload["standard_deduction_kg"] == "8.0000"
        assert payload["actual_deduction_kg"] == "11"

    @pytest.mark.asyncio
    async def test_anomaly_not_triggered_within_tolerance(self):
        """实测 vs 标准差未超 tolerance_pct → 不触发 callback。

        场景：标 ice 8% tolerance 2%，毛重 100kg 实测扣 9kg（标 8kg, 偏差 1%）→ 不触发
        """
        row = _row_factory(
            approved_by=_USER_FINANCE,
            deduct_method="percentage",
            deduct_value=Decimal("8.0"),
            tolerance_pct=Decimal("2.0"),
        )
        db = _mk_db_for_list(rows=[row])

        captured: list[dict] = []

        async def on_anomaly(payload: dict) -> None:
            captured.append(payload)

        await calculate_net_weight(
            db=db,
            tenant_id=_TENANT_XUJI,
            ingredient_id=_INGREDIENT_FISH,
            gross_weight_kg=Decimal("100"),
            actual_total_deduction_kg=Decimal("9"),  # 标 8, 实 9 → 偏差 1% < tolerance 2%
            on_anomaly_callback=on_anomaly,
        )
        assert captured == [], "偏差未超 tolerance 不应触发 callback"
