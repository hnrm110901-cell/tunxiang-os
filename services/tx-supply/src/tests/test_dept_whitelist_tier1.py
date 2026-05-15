"""dept_whitelist_service 契约测试（PRD-08 / Phase 2 W11 / T2 + Tier 1 邻接）

测试基于真实餐厅场景（CLAUDE.md §20）：
徐记海鲜后厨档口 — 早餐档（dept_A） / 海鲜档（dept_B），龙虾（ingredient_lobster）
是高端海鲜，早餐档不应能领；海鲜档是合法领料。

  1. create_whitelist 4 用例（成功 / max_qty NULL 不限量 / max_qty<=0 拒 / 重复 IntegrityError → ValueError）
  2. get_whitelist 2 用例（存在 / 不存在 None）
  3. list_whitelists 6 用例（all / dept_id / only_active / 同时 / limit 校验 / offset 校验）
  4. update_whitelist 3 用例（更新成功 / 不存在 / 无字段拒）
  5. delete_whitelist 2 用例（成功 / 不存在 False）
  6. bulk_authorize 3 用例（含 created + updated 混合 / 拒空 items / 超 200 拒）
  7. validate_ingredient_allowed 6 用例（不存在拒 / 软禁用拒 / NULL 不限量允 / qty 未提供仅校验存在性允 /
     qty 超限拒 / raise_on_violation=False 返回 dict）

mock 风格沿用 test_requisition_template_tier1.py — AsyncMock + SQL 字符串匹配。
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

if sys.version_info < (3, 10):
    pytest.skip(
        "需要 Python 3.10+（生产环境为 3.11）— 本机 3.9 跳过避免 sys.modules 污染",
        allow_module_level=True,
    )

from services.tx_supply.src.models.dept_whitelist_models import (  # noqa: E402
    IngredientNotAllowedError,
)
from services.tx_supply.src.services.dept_whitelist_service import (  # noqa: E402
    bulk_authorize,
    create_whitelist,
    delete_whitelist,
    get_whitelist,
    list_whitelists,
    update_whitelist,
    validate_ingredient_allowed,
)


# ─── 测试常量（徐记海鲜场景）────────────────────────────────────────────────

_TENANT_XUJI = "11111111-aaaa-aaaa-aaaa-111111111111"
_USER_FOOD_SAFETY = "cccccccc-0005-0005-0005-cccccccccccc"  # 食安总监
_DEPT_BREAKFAST = "22222222-0001-0001-0001-222222222222"  # 早餐档
_DEPT_SEAFOOD = "22222222-0002-0002-0002-222222222222"  # 海鲜档
_INGREDIENT_LOBSTER = "33333333-0001-0001-0001-333333333333"  # 龙虾
_INGREDIENT_PORK_BUN = "33333333-0002-0002-0002-333333333333"  # 肉包
_WHITELIST_ID = "44444444-0001-0001-0001-444444444444"


def _wl_row(
    *,
    dept_id: str = _DEPT_SEAFOOD,
    ingredient_id: str = _INGREDIENT_LOBSTER,
    max_qty_per_day: Decimal | None = None,
    is_active: bool = True,
    is_deleted: bool = False,
) -> dict:
    return {
        "id": _WHITELIST_ID,
        "tenant_id": _TENANT_XUJI,
        "dept_id": dept_id,
        "ingredient_id": ingredient_id,
        "max_qty_per_day": max_qty_per_day,
        "is_active": is_active,
        "notes": None,
        "created_by": _USER_FOOD_SAFETY,
        "created_at": datetime(2026, 5, 15, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 5, 15, tzinfo=timezone.utc),
        "is_deleted": is_deleted,
    }


# ─── DB Mock 工厂 ────────────────────────────────────────────────────────────


def _mk_db_create(*, fail_with: Exception | None = None) -> tuple[AsyncMock, list[str]]:
    sql_log: list[str] = []
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        sql_log.append(sql)
        result = MagicMock()
        if "set_config" in sql:
            return MagicMock()
        if "INSERT INTO department_ingredient_whitelists" in sql:
            if fail_with is not None:
                raise fail_with
            result.mappings.return_value.first.return_value = _wl_row(
                max_qty_per_day=params.get("max_qty_per_day") if params else None,
                dept_id=str(params.get("dept_id")) if params else _DEPT_SEAFOOD,
                ingredient_id=str(params.get("ingredient_id")) if params else _INGREDIENT_LOBSTER,
            )
            return result
        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db, sql_log


def _mk_db_get(*, row: dict | None) -> AsyncMock:
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        result = MagicMock()
        if "set_config" in sql:
            return MagicMock()
        if "FROM department_ingredient_whitelists" in sql:
            result.mappings.return_value.first.return_value = row
            return result
        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


def _mk_db_list(rows: list[dict]) -> tuple[AsyncMock, list[str]]:
    sql_log: list[str] = []
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        sql_log.append(sql)
        result = MagicMock()
        if "set_config" in sql:
            return MagicMock()
        if "FROM department_ingredient_whitelists" in sql:
            result.mappings.return_value.all.return_value = rows
            return result
        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db, sql_log


def _mk_db_update(*, get_row: dict | None) -> tuple[AsyncMock, list[str]]:
    sql_log: list[str] = []
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        sql_log.append(sql)
        result = MagicMock()
        result.rowcount = 1
        if "set_config" in sql:
            return MagicMock()
        if "FROM department_ingredient_whitelists" in sql:
            result.mappings.return_value.first.return_value = get_row
            return result
        if "UPDATE department_ingredient_whitelists" in sql:
            return result
        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db, sql_log


# ─── 1. create_whitelist ─────────────────────────────────────────────────────


class TestCreateWhitelist:
    @pytest.mark.asyncio
    async def test_creates_seafood_dept_lobster_unlimited(self):
        """海鲜档 + 龙虾 + max_qty_per_day=NULL → 创建成功，不限量语义。"""
        db, sql_log = _mk_db_create()
        result = await create_whitelist(
            db,
            _TENANT_XUJI,
            dept_id=_DEPT_SEAFOOD,
            ingredient_id=_INGREDIENT_LOBSTER,
            created_by=_USER_FOOD_SAFETY,
            max_qty_per_day=None,
        )
        assert result["dept_id"] == _DEPT_SEAFOOD
        assert result["max_qty_per_day"] is None
        insert_sqls = [s for s in sql_log if "INSERT INTO department_ingredient_whitelists" in s]
        assert len(insert_sqls) == 1
        assert any("set_config" in s for s in sql_log)

    @pytest.mark.asyncio
    async def test_creates_with_daily_limit(self):
        """早餐档 + 肉包 + max_qty=50kg/天 → 创建成功，限额生效。"""
        db, _ = _mk_db_create()
        result = await create_whitelist(
            db,
            _TENANT_XUJI,
            dept_id=_DEPT_BREAKFAST,
            ingredient_id=_INGREDIENT_PORK_BUN,
            created_by=_USER_FOOD_SAFETY,
            max_qty_per_day=Decimal("50"),
        )
        assert result["max_qty_per_day"] == Decimal("50")

    @pytest.mark.asyncio
    async def test_rejects_zero_max_qty(self):
        """max_qty_per_day=0 → ValueError（应为 NULL=不限量 或 >0 数字）。"""
        db, _ = _mk_db_create()
        with pytest.raises(ValueError, match="max_qty_per_day"):
            await create_whitelist(
                db,
                _TENANT_XUJI,
                dept_id=_DEPT_SEAFOOD,
                ingredient_id=_INGREDIENT_LOBSTER,
                created_by=_USER_FOOD_SAFETY,
                max_qty_per_day=Decimal("0"),
            )

    @pytest.mark.asyncio
    async def test_duplicate_raises_value_error(self):
        """UNIQUE (tenant, dept, ingredient) violation → ValueError("已存在")，路由层 409。"""
        from sqlalchemy.exc import IntegrityError

        db, _ = _mk_db_create(
            fail_with=IntegrityError("duplicate whitelist", None, None)
        )
        with pytest.raises(ValueError, match="已存在"):
            await create_whitelist(
                db,
                _TENANT_XUJI,
                dept_id=_DEPT_SEAFOOD,
                ingredient_id=_INGREDIENT_LOBSTER,
                created_by=_USER_FOOD_SAFETY,
            )


# ─── 2. get_whitelist ────────────────────────────────────────────────────────


class TestGetWhitelist:
    @pytest.mark.asyncio
    async def test_returns_row_when_exists(self):
        db = _mk_db_get(row=_wl_row())
        result = await get_whitelist(db, _TENANT_XUJI, _WHITELIST_ID)
        assert result is not None
        assert result["dept_id"] == _DEPT_SEAFOOD

    @pytest.mark.asyncio
    async def test_not_found_returns_none(self):
        db = _mk_db_get(row=None)
        result = await get_whitelist(db, _TENANT_XUJI, _WHITELIST_ID)
        assert result is None


# ─── 3. list_whitelists ──────────────────────────────────────────────────────


class TestListWhitelists:
    @pytest.mark.asyncio
    async def test_returns_rows(self):
        db, _ = _mk_db_list([_wl_row(), _wl_row(dept_id=_DEPT_BREAKFAST)])
        result = await list_whitelists(db, _TENANT_XUJI, only_active=False)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_dept_filter_uses_param(self):
        db, sql_log = _mk_db_list([_wl_row()])
        await list_whitelists(db, _TENANT_XUJI, dept_id=_DEPT_SEAFOOD, only_active=False)
        list_sql = next((s for s in sql_log if "FROM department_ingredient_whitelists" in s), "")
        assert "dept_id = :dept_id" in list_sql

    @pytest.mark.asyncio
    async def test_only_active_uses_active_filter(self):
        db, sql_log = _mk_db_list([_wl_row()])
        await list_whitelists(db, _TENANT_XUJI, only_active=True)
        list_sql = next((s for s in sql_log if "FROM department_ingredient_whitelists" in s), "")
        assert "is_active = TRUE" in list_sql

    @pytest.mark.asyncio
    async def test_dept_and_active_combined(self):
        db, sql_log = _mk_db_list([_wl_row()])
        await list_whitelists(
            db, _TENANT_XUJI, dept_id=_DEPT_SEAFOOD, only_active=True
        )
        list_sql = next((s for s in sql_log if "FROM department_ingredient_whitelists" in s), "")
        assert "dept_id = :dept_id" in list_sql
        assert "is_active = TRUE" in list_sql

    @pytest.mark.asyncio
    async def test_rejects_invalid_limit(self):
        db, _ = _mk_db_list([])
        with pytest.raises(ValueError, match="limit"):
            await list_whitelists(db, _TENANT_XUJI, limit=0)
        with pytest.raises(ValueError, match="limit"):
            await list_whitelists(db, _TENANT_XUJI, limit=300)

    @pytest.mark.asyncio
    async def test_rejects_negative_offset(self):
        db, _ = _mk_db_list([])
        with pytest.raises(ValueError, match="offset"):
            await list_whitelists(db, _TENANT_XUJI, offset=-1)


# ─── 4. update_whitelist ─────────────────────────────────────────────────────


class TestUpdateWhitelist:
    @pytest.mark.asyncio
    async def test_update_max_qty(self):
        db, sql_log = _mk_db_update(get_row=_wl_row(max_qty_per_day=Decimal("100")))
        result = await update_whitelist(
            db, _TENANT_XUJI, _WHITELIST_ID, max_qty_per_day=Decimal("100")
        )
        assert result["max_qty_per_day"] == Decimal("100")
        assert any("UPDATE department_ingredient_whitelists" in s for s in sql_log)

    @pytest.mark.asyncio
    async def test_no_fields_rejected(self):
        db, _ = _mk_db_update(get_row=_wl_row())
        with pytest.raises(ValueError, match="至少"):
            await update_whitelist(db, _TENANT_XUJI, _WHITELIST_ID)

    @pytest.mark.asyncio
    async def test_not_found_rejected(self):
        db, _ = _mk_db_update(get_row=None)
        with pytest.raises(ValueError, match="不存在"):
            await update_whitelist(
                db, _TENANT_XUJI, _WHITELIST_ID, is_active=False
            )


# ─── 5. delete_whitelist ─────────────────────────────────────────────────────


class TestDeleteWhitelist:
    @pytest.mark.asyncio
    async def test_delete_success(self):
        db = AsyncMock()

        async def execute_side_effect(query, params=None):
            r = MagicMock()
            r.rowcount = 1
            return r

        db.execute = AsyncMock(side_effect=execute_side_effect)
        ok = await delete_whitelist(db, _TENANT_XUJI, _WHITELIST_ID)
        assert ok is True

    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        db = AsyncMock()

        async def execute_side_effect(query, params=None):
            r = MagicMock()
            r.rowcount = 0
            return r

        db.execute = AsyncMock(side_effect=execute_side_effect)
        ok = await delete_whitelist(db, _TENANT_XUJI, _WHITELIST_ID)
        assert ok is False


# ─── 6. bulk_authorize ───────────────────────────────────────────────────────


class TestBulkAuthorize:
    @pytest.mark.asyncio
    async def test_mixed_create_and_update(self):
        """前两条 (dept, ingredient) 已存在 → UPDATE；后一条不存在 → INSERT。"""
        update_call_count = {"n": 0}
        db = AsyncMock()

        async def execute_side_effect(query, params=None):
            sql = str(query)
            result = MagicMock()
            if "set_config" in sql:
                return MagicMock()
            if "UPDATE department_ingredient_whitelists" in sql and "is_deleted = FALSE" in sql:
                # UPSERT BY PAIR — 前两次命中（返回 row），第三次不命中
                update_call_count["n"] += 1
                if update_call_count["n"] <= 2:
                    result.mappings.return_value.first.return_value = _wl_row(
                        ingredient_id=str(params.get("ingredient_id")) if params else _INGREDIENT_LOBSTER,
                        max_qty_per_day=params.get("max_qty_per_day") if params else None,
                    )
                else:
                    result.mappings.return_value.first.return_value = None
                return result
            if "INSERT INTO department_ingredient_whitelists" in sql:
                # 第三条新建
                result.mappings.return_value.first.return_value = _wl_row(
                    ingredient_id=str(params.get("ingredient_id")) if params else "new-ing",
                    max_qty_per_day=params.get("max_qty_per_day") if params else None,
                )
                return result
            return MagicMock()

        db.execute = AsyncMock(side_effect=execute_side_effect)

        result = await bulk_authorize(
            db,
            _TENANT_XUJI,
            dept_id=_DEPT_SEAFOOD,
            items=[
                {"ingredient_id": _INGREDIENT_LOBSTER, "max_qty_per_day": None},
                {
                    "ingredient_id": _INGREDIENT_PORK_BUN,
                    "max_qty_per_day": Decimal("30"),
                },
                {"ingredient_id": "new-ing-id", "max_qty_per_day": None},
            ],
            created_by=_USER_FOOD_SAFETY,
        )
        assert result["updated_count"] == 2
        assert result["created_count"] == 1
        assert len(result["items"]) == 3

    @pytest.mark.asyncio
    async def test_rejects_empty_items(self):
        db = AsyncMock()
        with pytest.raises(ValueError, match="items 不可为空"):
            await bulk_authorize(
                db, _TENANT_XUJI, dept_id=_DEPT_SEAFOOD, items=[], created_by=_USER_FOOD_SAFETY
            )

    @pytest.mark.asyncio
    async def test_rejects_too_many_items(self):
        db = AsyncMock()
        with pytest.raises(ValueError, match="数量超限"):
            await bulk_authorize(
                db,
                _TENANT_XUJI,
                dept_id=_DEPT_SEAFOOD,
                items=[{"ingredient_id": f"ing-{i}"} for i in range(201)],
                created_by=_USER_FOOD_SAFETY,
            )


# ─── 7. validate_ingredient_allowed ──────────────────────────────────────────


class TestValidateIngredientAllowed:
    @pytest.mark.asyncio
    async def test_no_whitelist_raises(self):
        """早餐档无龙虾白名单 → raise IngredientNotAllowedError（核心反串货场景）。"""
        db = _mk_db_get(row=None)
        with pytest.raises(IngredientNotAllowedError) as exc_info:
            await validate_ingredient_allowed(
                db,
                _TENANT_XUJI,
                dept_id=_DEPT_BREAKFAST,
                ingredient_id=_INGREDIENT_LOBSTER,
                ingredient_name_hint="波士顿龙虾",
            )
        assert exc_info.value.dept_id == _DEPT_BREAKFAST
        assert exc_info.value.ingredient_id == _INGREDIENT_LOBSTER
        assert "波士顿龙虾" in exc_info.value.message or "未授权" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_inactive_whitelist_raises(self):
        """白名单存在但 is_active=FALSE（软禁用）→ raise。"""
        db = _mk_db_get(row=_wl_row(is_active=False))
        with pytest.raises(IngredientNotAllowedError):
            await validate_ingredient_allowed(
                db,
                _TENANT_XUJI,
                dept_id=_DEPT_BREAKFAST,
                ingredient_id=_INGREDIENT_LOBSTER,
            )

    @pytest.mark.asyncio
    async def test_unlimited_allowed(self):
        """max_qty_per_day=NULL → 不限量，allowed=True。"""
        db = _mk_db_get(row=_wl_row(max_qty_per_day=None))
        result = await validate_ingredient_allowed(
            db,
            _TENANT_XUJI,
            dept_id=_DEPT_SEAFOOD,
            ingredient_id=_INGREDIENT_LOBSTER,
            qty=Decimal("999"),  # 任意大数也允许
        )
        assert result["allowed"] is True
        assert result["max_qty_per_day"] is None

    @pytest.mark.asyncio
    async def test_qty_not_provided_only_validates_existence(self):
        """max_qty_per_day=50 但 qty 未提供 → 仅校验存在性，allowed=True。"""
        db = _mk_db_get(row=_wl_row(max_qty_per_day=Decimal("50")))
        result = await validate_ingredient_allowed(
            db,
            _TENANT_XUJI,
            dept_id=_DEPT_BREAKFAST,
            ingredient_id=_INGREDIENT_PORK_BUN,
            qty=None,
        )
        assert result["allowed"] is True
        assert result["max_qty_per_day"] == Decimal("50")

    @pytest.mark.asyncio
    async def test_qty_exceeds_daily_limit_raises(self):
        """max_qty=50, qty=60 → 超限 raise。"""
        db = _mk_db_get(row=_wl_row(max_qty_per_day=Decimal("50")))
        with pytest.raises(IngredientNotAllowedError) as exc_info:
            await validate_ingredient_allowed(
                db,
                _TENANT_XUJI,
                dept_id=_DEPT_BREAKFAST,
                ingredient_id=_INGREDIENT_PORK_BUN,
                qty=Decimal("60"),
            )
        assert "60" in exc_info.value.message
        assert "50" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_raise_on_violation_false_returns_dict(self):
        """raise_on_violation=False → 返回 {allowed: False, reason: ...} 不抛。"""
        db = _mk_db_get(row=None)
        result = await validate_ingredient_allowed(
            db,
            _TENANT_XUJI,
            dept_id=_DEPT_BREAKFAST,
            ingredient_id=_INGREDIENT_LOBSTER,
            raise_on_violation=False,
        )
        assert result["allowed"] is False
        assert "白名单" in result["reason"]
