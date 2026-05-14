"""requisition_template_service 契约测试（PRD-07 / Phase 2 W10 / T2）

测试基于真实餐厅场景（CLAUDE.md §20）：

  1. create_template 5 用例（空 items 拒绝 / fixed 必须 default_qty / 基本 4 行 / RLS / items 写入顺序）
  2. get_template 3 用例（含 items / 不存在 None / RLS set_config）
  3. list_templates 6 用例（all / only_active / category / 同时 / limit 校验 / offset 校验）
  4. update_template 3 用例（fields not None / not found / COALESCE 保留原值）
  5. delete_template 2 用例（成功 / 不存在 False）
  6. create_binding 3 用例（template 不存在拒绝 / 成功 / RLS）
  7. list_bindings_for_warehouse 2 用例（JOIN template 字段 / RLS）
  8. delete_binding 2 用例（成功 / 不存在 False）
  9. generate_from_template 5 用例（fixed → 模板默认 / ai_predicted no store → 跳过 fail-open
     / ai_predicted with store → AI 推荐填充 / last_order → fail-open / 模板已禁用拒绝）

mock 风格沿用 test_rfq_*_tier1.py — AsyncMock + SQL 字符串匹配 + smart_replenishment Mock 注入。
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if sys.version_info < (3, 10):
    pytest.skip(
        "需要 Python 3.10+（生产环境为 3.11）— 本机 3.9 跳过避免 sys.modules 污染",
        allow_module_level=True,
    )

from services.tx_supply.src.services.requisition_template_service import (  # noqa: E402
    create_binding,
    create_template,
    delete_binding,
    delete_template,
    generate_from_template,
    get_template,
    list_bindings_for_warehouse,
    list_templates,
    update_template,
)


# ─── 测试常量（徐记海鲜场景）────────────────────────────────────────────────

_TENANT_XUJI = "11111111-aaaa-aaaa-aaaa-111111111111"
_USER_BUYER = "cccccccc-0003-0003-0003-cccccccccccc"
_TEMPLATE_ID = "22222222-0001-0001-0001-222222222222"
_BINDING_ID = "33333333-0001-0001-0001-333333333333"
_WAREHOUSE_ID = "44444444-0001-0001-0001-444444444444"
_STORE_ID = "55555555-0001-0001-0001-555555555555"
_INGREDIENT_A = "66666666-0001-0001-0001-666666666666"
_INGREDIENT_B = "77777777-0001-0001-0001-777777777777"


def _tpl_row(*, is_active: bool = True, is_deleted: bool = False, name: str = "海鲜模板") -> dict:
    return {
        "id": _TEMPLATE_ID,
        "tenant_id": _TENANT_XUJI,
        "name": name,
        "category": "seafood",
        "is_active": is_active,
        "notes": None,
        "created_by": _USER_BUYER,
        "created_at": datetime(2026, 5, 15, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 5, 15, tzinfo=timezone.utc),
        "is_deleted": is_deleted,
    }


def _tpl_item_row(
    *,
    ingredient_id: str = _INGREDIENT_A,
    qty_method: str = "fixed",
    default_qty: Decimal | None = Decimal("10"),
) -> dict:
    return {
        "id": "item-id",
        "tenant_id": _TENANT_XUJI,
        "template_id": _TEMPLATE_ID,
        "ingredient_id": ingredient_id,
        "default_qty": default_qty,
        "qty_method": qty_method,
        "qty_unit": "kg",
        "sort_order": 0,
        "notes": None,
    }


# ─── DB Mock 工厂 ────────────────────────────────────────────────────────────


def _mk_db_create() -> tuple[AsyncMock, list[str]]:
    """模拟 create_template 多 INSERT 路径（templates + items）。"""
    sql_log: list[str] = []
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        sql_log.append(sql)
        result = MagicMock()
        if "set_config" in sql:
            return MagicMock()
        if "INSERT INTO requisition_templates" in sql:
            result.mappings.return_value.first.return_value = _tpl_row()
            return result
        if "INSERT INTO requisition_template_items" in sql:
            iid = params["ingredient_id"] if params else _INGREDIENT_A
            method = params["qty_method"] if params else "fixed"
            qty = params["default_qty"] if params else Decimal("10")
            result.mappings.return_value.first.return_value = _tpl_item_row(
                ingredient_id=iid, qty_method=method, default_qty=qty
            )
            return result
        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db, sql_log


def _mk_db_get(*, tpl_row: dict | None, items: list[dict] | None = None) -> AsyncMock:
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        result = MagicMock()
        if "set_config" in sql:
            return MagicMock()
        if "FROM requisition_templates" in sql:
            result.mappings.return_value.first.return_value = tpl_row
            return result
        if "FROM requisition_template_items" in sql:
            result.mappings.return_value.all.return_value = items or []
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
        if "FROM requisition_templates" in sql:
            result.mappings.return_value.all.return_value = rows
            return result
        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db, sql_log


def _mk_db_update(*, tpl_row: dict | None) -> tuple[AsyncMock, list[str]]:
    sql_log: list[str] = []
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        sql_log.append(sql)
        result = MagicMock()
        result.rowcount = 1
        if "set_config" in sql:
            return MagicMock()
        if "FROM requisition_templates" in sql:
            result.mappings.return_value.first.return_value = tpl_row
            return result
        if "FROM requisition_template_items" in sql:
            result.mappings.return_value.all.return_value = []
            return result
        if "UPDATE requisition_templates" in sql:
            return result
        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db, sql_log


def _mk_db_binding(*, tpl_row: dict | None) -> tuple[AsyncMock, list[str]]:
    sql_log: list[str] = []
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        sql_log.append(sql)
        result = MagicMock()
        result.rowcount = 1
        if "set_config" in sql:
            return MagicMock()
        if "FROM requisition_templates" in sql:
            result.mappings.return_value.first.return_value = tpl_row
            return result
        if "FROM requisition_template_items" in sql:
            result.mappings.return_value.all.return_value = []
            return result
        if "INSERT INTO warehouse_requisition_template_bindings" in sql:
            result.mappings.return_value.first.return_value = {
                "id": _BINDING_ID,
                "tenant_id": _TENANT_XUJI,
                "warehouse_id": _WAREHOUSE_ID,
                "template_id": _TEMPLATE_ID,
                "auto_trigger_cron": params.get("cron") if params else None,
                "priority": 0,
                "created_by": _USER_BUYER,
                "created_at": datetime(2026, 5, 15, tzinfo=timezone.utc),
            }
            return result
        if "FROM warehouse_requisition_template_bindings" in sql:
            result.mappings.return_value.all.return_value = [
                {
                    "id": _BINDING_ID,
                    "tenant_id": _TENANT_XUJI,
                    "warehouse_id": _WAREHOUSE_ID,
                    "template_id": _TEMPLATE_ID,
                    "auto_trigger_cron": None,
                    "priority": 0,
                    "created_by": _USER_BUYER,
                    "created_at": datetime(2026, 5, 15, tzinfo=timezone.utc),
                    "template_name": "海鲜模板",
                    "template_category": "seafood",
                    "template_is_active": True,
                }
            ]
            return result
        if "UPDATE warehouse_requisition_template_bindings" in sql:
            return result
        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db, sql_log


# ─── 1. create_template ──────────────────────────────────────────────────────


class TestCreateTemplate:
    @pytest.mark.asyncio
    async def test_create_with_4_items(self):
        db, sql_log = _mk_db_create()
        result = await create_template(
            db,
            _TENANT_XUJI,
            name="海鲜模板",
            category="seafood",
            items=[
                {"ingredient_id": _INGREDIENT_A, "default_qty": Decimal("5"), "qty_method": "fixed"},
                {"ingredient_id": _INGREDIENT_B, "default_qty": None, "qty_method": "ai_predicted"},
            ],
            created_by=_USER_BUYER,
        )
        assert result["name"] == "海鲜模板"
        assert len(result["items"]) == 2
        # 验证 SQL 顺序：templates INSERT → items INSERT × 2
        insert_tpls = [s for s in sql_log if "INSERT INTO requisition_templates" in s]
        insert_items = [s for s in sql_log if "INSERT INTO requisition_template_items" in s]
        assert len(insert_tpls) == 1
        assert len(insert_items) == 2

    @pytest.mark.asyncio
    async def test_rejects_empty_items(self):
        db, _ = _mk_db_create()
        with pytest.raises(ValueError, match="至少"):
            await create_template(
                db, _TENANT_XUJI, name="x", category="seafood", items=[], created_by=_USER_BUYER
            )

    @pytest.mark.asyncio
    async def test_rejects_empty_name(self):
        db, _ = _mk_db_create()
        with pytest.raises(ValueError, match="name"):
            await create_template(
                db,
                _TENANT_XUJI,
                name="   ",
                category="seafood",
                items=[{"ingredient_id": _INGREDIENT_A, "default_qty": Decimal("1"), "qty_method": "fixed"}],
                created_by=_USER_BUYER,
            )

    @pytest.mark.asyncio
    async def test_fixed_method_requires_default_qty(self):
        """qty_method='fixed' 必须有 default_qty — 防止生成草稿时空数量。"""
        db, _ = _mk_db_create()
        with pytest.raises(ValueError, match="fixed.*必须"):
            await create_template(
                db,
                _TENANT_XUJI,
                name="x",
                category="seafood",
                items=[{"ingredient_id": _INGREDIENT_A, "qty_method": "fixed"}],  # default_qty 缺
                created_by=_USER_BUYER,
            )

    @pytest.mark.asyncio
    async def test_sets_tenant_rls(self):
        db, sql_log = _mk_db_create()
        await create_template(
            db,
            _TENANT_XUJI,
            name="x",
            category="seafood",
            items=[{"ingredient_id": _INGREDIENT_A, "default_qty": Decimal("1"), "qty_method": "fixed"}],
            created_by=_USER_BUYER,
        )
        assert any("set_config" in s for s in sql_log)

    @pytest.mark.asyncio
    async def test_create_duplicate_ingredient_raises_value_error(self):
        """§19 round-1 P1-1: DB UNIQUE(template_id, ingredient_id) violation
        被服务层捕获转 ValueError，路由层映射 422，不应 HTTP 500。
        """
        from sqlalchemy.exc import IntegrityError

        db = AsyncMock()
        sql_log: list[str] = []

        async def execute_side_effect(query, params=None):
            sql = str(query)
            sql_log.append(sql)
            result = MagicMock()
            if "set_config" in sql:
                return MagicMock()
            if "INSERT INTO requisition_templates" in sql:
                result.mappings.return_value.first.return_value = _tpl_row()
                return result
            if "INSERT INTO requisition_template_items" in sql:
                # 模拟 UNIQUE violation
                raise IntegrityError("duplicate ingredient", None, None)
            return MagicMock()

        db.execute = AsyncMock(side_effect=execute_side_effect)

        with pytest.raises(ValueError, match="重复"):
            await create_template(
                db,
                _TENANT_XUJI,
                name="海鲜模板",
                category="seafood",
                items=[
                    {"ingredient_id": _INGREDIENT_A, "default_qty": Decimal("5"), "qty_method": "fixed"},
                ],
                created_by=_USER_BUYER,
            )


# ─── 2. get_template ─────────────────────────────────────────────────────────


class TestGetTemplate:
    @pytest.mark.asyncio
    async def test_returns_template_with_items(self):
        db = _mk_db_get(tpl_row=_tpl_row(), items=[_tpl_item_row(), _tpl_item_row(ingredient_id=_INGREDIENT_B)])
        result = await get_template(db, _TENANT_XUJI, _TEMPLATE_ID)
        assert result is not None
        assert result["name"] == "海鲜模板"
        assert len(result["items"]) == 2

    @pytest.mark.asyncio
    async def test_not_found_returns_none(self):
        db = _mk_db_get(tpl_row=None)
        result = await get_template(db, _TENANT_XUJI, _TEMPLATE_ID)
        assert result is None

    @pytest.mark.asyncio
    async def test_sets_tenant_rls(self):
        db = _mk_db_get(tpl_row=_tpl_row(), items=[])
        await get_template(db, _TENANT_XUJI, _TEMPLATE_ID)
        sqls = [str(call.args[0]) for call in db.execute.call_args_list]
        assert any("set_config" in s for s in sqls)


# ─── 3. list_templates ───────────────────────────────────────────────────────


class TestListTemplates:
    @pytest.mark.asyncio
    async def test_returns_rows(self):
        db, _ = _mk_db_list([_tpl_row(), _tpl_row(name="蔬菜模板")])
        result = await list_templates(db, _TENANT_XUJI, only_active=False)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_only_active_uses_active_filter(self):
        db, sql_log = _mk_db_list([_tpl_row()])
        await list_templates(db, _TENANT_XUJI, only_active=True, category=None)
        rfq_sql = next((s for s in sql_log if "FROM requisition_templates" in s), "")
        assert "is_active = TRUE" in rfq_sql

    @pytest.mark.asyncio
    async def test_category_filter_uses_param(self):
        db, sql_log = _mk_db_list([_tpl_row()])
        await list_templates(db, _TENANT_XUJI, only_active=False, category="seafood")
        rfq_sql = next((s for s in sql_log if "FROM requisition_templates" in s), "")
        assert "category = :category" in rfq_sql

    @pytest.mark.asyncio
    async def test_active_and_category_combined(self):
        db, sql_log = _mk_db_list([_tpl_row()])
        await list_templates(db, _TENANT_XUJI, only_active=True, category="seafood")
        rfq_sql = next((s for s in sql_log if "FROM requisition_templates" in s), "")
        assert "is_active = TRUE" in rfq_sql
        assert "category = :category" in rfq_sql

    @pytest.mark.asyncio
    async def test_rejects_invalid_limit(self):
        db, _ = _mk_db_list([])
        with pytest.raises(ValueError, match="limit"):
            await list_templates(db, _TENANT_XUJI, limit=0)
        with pytest.raises(ValueError, match="limit"):
            await list_templates(db, _TENANT_XUJI, limit=300)

    @pytest.mark.asyncio
    async def test_rejects_negative_offset(self):
        db, _ = _mk_db_list([])
        with pytest.raises(ValueError, match="offset"):
            await list_templates(db, _TENANT_XUJI, offset=-1)


# ─── 4. update_template ──────────────────────────────────────────────────────


class TestUpdateTemplate:
    @pytest.mark.asyncio
    async def test_update_name(self):
        db, sql_log = _mk_db_update(tpl_row=_tpl_row(name="新名"))
        result = await update_template(db, _TENANT_XUJI, _TEMPLATE_ID, name="新名")
        assert result["name"] == "新名"
        update_sqls = [s for s in sql_log if "UPDATE requisition_templates" in s]
        assert update_sqls

    @pytest.mark.asyncio
    async def test_no_fields_rejected(self):
        db, _ = _mk_db_update(tpl_row=_tpl_row())
        with pytest.raises(ValueError, match="至少"):
            await update_template(db, _TENANT_XUJI, _TEMPLATE_ID)

    @pytest.mark.asyncio
    async def test_not_found(self):
        db, _ = _mk_db_update(tpl_row=None)
        with pytest.raises(ValueError, match="不存在"):
            await update_template(db, _TENANT_XUJI, _TEMPLATE_ID, name="x")


# ─── 5. delete_template ──────────────────────────────────────────────────────


class TestDeleteTemplate:
    @pytest.mark.asyncio
    async def test_delete_success(self):
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.rowcount = 1

        async def execute_side_effect(query, params=None):
            r = MagicMock()
            r.rowcount = 1
            return r

        db.execute = AsyncMock(side_effect=execute_side_effect)
        ok = await delete_template(db, _TENANT_XUJI, _TEMPLATE_ID)
        assert ok is True

    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        db = AsyncMock()

        async def execute_side_effect(query, params=None):
            r = MagicMock()
            r.rowcount = 0
            return r

        db.execute = AsyncMock(side_effect=execute_side_effect)
        ok = await delete_template(db, _TENANT_XUJI, _TEMPLATE_ID)
        assert ok is False


# ─── 6. create_binding ───────────────────────────────────────────────────────


class TestCreateBinding:
    @pytest.mark.asyncio
    async def test_template_not_found_rejected(self):
        db, _ = _mk_db_binding(tpl_row=None)
        with pytest.raises(ValueError, match="不存在"):
            await create_binding(
                db,
                _TENANT_XUJI,
                warehouse_id=_WAREHOUSE_ID,
                template_id=_TEMPLATE_ID,
                created_by=_USER_BUYER,
            )

    @pytest.mark.asyncio
    async def test_success(self):
        db, sql_log = _mk_db_binding(tpl_row=_tpl_row())
        result = await create_binding(
            db,
            _TENANT_XUJI,
            warehouse_id=_WAREHOUSE_ID,
            template_id=_TEMPLATE_ID,
            created_by=_USER_BUYER,
            auto_trigger_cron="0 6 * * *",
        )
        assert result["warehouse_id"] == _WAREHOUSE_ID
        insert_sqls = [s for s in sql_log if "INSERT INTO warehouse_requisition_template_bindings" in s]
        assert insert_sqls

    @pytest.mark.asyncio
    async def test_duplicate_binding_raises_value_error(self):
        """§19 round-1 P1-1: 重复 (warehouse_id, template_id) UNIQUE violation
        被服务层捕获转 ValueError("重复绑定")，路由层映射 409 Conflict。
        """
        from sqlalchemy.exc import IntegrityError

        db = AsyncMock()

        async def execute_side_effect(query, params=None):
            sql = str(query)
            result = MagicMock()
            if "set_config" in sql:
                return MagicMock()
            if "FROM requisition_templates" in sql:
                result.mappings.return_value.first.return_value = _tpl_row()
                return result
            if "FROM requisition_template_items" in sql:
                result.mappings.return_value.all.return_value = []
                return result
            if "INSERT INTO warehouse_requisition_template_bindings" in sql:
                raise IntegrityError("duplicate binding", None, None)
            return MagicMock()

        db.execute = AsyncMock(side_effect=execute_side_effect)

        with pytest.raises(ValueError, match="重复绑定"):
            await create_binding(
                db,
                _TENANT_XUJI,
                warehouse_id=_WAREHOUSE_ID,
                template_id=_TEMPLATE_ID,
                created_by=_USER_BUYER,
            )


# ─── 7. list_bindings_for_warehouse ──────────────────────────────────────────


class TestListBindingsForWarehouse:
    @pytest.mark.asyncio
    async def test_returns_with_template_info(self):
        db, _ = _mk_db_binding(tpl_row=_tpl_row())
        result = await list_bindings_for_warehouse(db, _TENANT_XUJI, _WAREHOUSE_ID)
        assert len(result) == 1
        # JOIN 出的 template 字段
        assert result[0]["template_name"] == "海鲜模板"


# ─── 8. delete_binding ───────────────────────────────────────────────────────


class TestDeleteBinding:
    @pytest.mark.asyncio
    async def test_delete_success(self):
        db = AsyncMock()

        async def execute_side_effect(query, params=None):
            r = MagicMock()
            r.rowcount = 1
            return r

        db.execute = AsyncMock(side_effect=execute_side_effect)
        ok = await delete_binding(db, _TENANT_XUJI, _BINDING_ID)
        assert ok is True

    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        db = AsyncMock()

        async def execute_side_effect(query, params=None):
            r = MagicMock()
            r.rowcount = 0
            return r

        db.execute = AsyncMock(side_effect=execute_side_effect)
        ok = await delete_binding(db, _TENANT_XUJI, _BINDING_ID)
        assert ok is False


# ─── 9. generate_from_template ───────────────────────────────────────────────


class TestGenerateFromTemplate:
    @pytest.mark.asyncio
    async def test_fixed_uses_template_default(self):
        """qty_method='fixed' 直接使用 default_qty。"""
        tpl_row = _tpl_row()
        items = [_tpl_item_row(qty_method="fixed", default_qty=Decimal("5"))]
        db = _mk_db_get(tpl_row=tpl_row, items=items)
        result = await generate_from_template(db, _TENANT_XUJI, _TEMPLATE_ID)
        assert len(result["items"]) == 1
        assert result["items"][0]["suggested_qty"] == Decimal("5")
        assert result["items"][0]["qty_source"] == "模板默认"

    @pytest.mark.asyncio
    async def test_ai_predicted_without_store_skipped(self):
        """qty_method='ai_predicted' 但 store_id 缺 → qty_source 标 '缺 store_id 跳过'。"""
        items = [_tpl_item_row(qty_method="ai_predicted", default_qty=None)]
        db = _mk_db_get(tpl_row=_tpl_row(), items=items)
        result = await generate_from_template(db, _TENANT_XUJI, _TEMPLATE_ID, store_id=None)
        assert result["items"][0]["suggested_qty"] is None
        assert "缺 store_id" in result["items"][0]["qty_source"]

    @pytest.mark.asyncio
    async def test_ai_predicted_with_store_calls_smart_replenishment(self):
        """qty_method='ai_predicted' + store_id → 调 smart_replenishment, 写入推荐量。"""
        items = [_tpl_item_row(qty_method="ai_predicted", default_qty=None)]
        db = _mk_db_get(tpl_row=_tpl_row(), items=items)

        mock_recommendation = MagicMock()
        mock_recommendation.ingredient_id = _INGREDIENT_A
        mock_recommendation.recommend_qty = 8.5

        with patch(
            "services.tx_supply.src.services.smart_replenishment.SmartReplenishmentService"
        ) as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.check_and_recommend = AsyncMock(return_value=[mock_recommendation])
            result = await generate_from_template(
                db, _TENANT_XUJI, _TEMPLATE_ID, store_id=_STORE_ID
            )

        assert len(result["items"]) == 1
        assert result["items"][0]["suggested_qty"] == Decimal("8.5")
        assert result["items"][0]["qty_source"] == "AI 推荐"

    @pytest.mark.asyncio
    async def test_ai_predicted_fail_open_when_smart_replenishment_raises(self):
        """smart_replenishment 抛 RuntimeError → fail-open，留 None + 标记原因。"""
        items = [_tpl_item_row(qty_method="ai_predicted", default_qty=None)]
        db = _mk_db_get(tpl_row=_tpl_row(), items=items)

        with patch(
            "services.tx_supply.src.services.smart_replenishment.SmartReplenishmentService"
        ) as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.check_and_recommend = AsyncMock(side_effect=RuntimeError("PG conn fail"))
            result = await generate_from_template(
                db, _TENANT_XUJI, _TEMPLATE_ID, store_id=_STORE_ID
            )

        assert result["items"][0]["suggested_qty"] is None
        assert "fail-open" in result["items"][0]["qty_source"]

    @pytest.mark.asyncio
    async def test_ai_predicted_fail_open_when_db_operational_error(self):
        """§19 round-1 P1-2: 真实 DB 故障抛 sqlalchemy.exc.OperationalError —
        必须被 fail-open 捕获 (P0-1 修复后扩 SQLAlchemyError 覆盖)。
        """
        from sqlalchemy.exc import OperationalError

        items = [_tpl_item_row(qty_method="ai_predicted", default_qty=None)]
        db = _mk_db_get(tpl_row=_tpl_row(), items=items)

        with patch(
            "services.tx_supply.src.services.smart_replenishment.SmartReplenishmentService"
        ) as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.check_and_recommend = AsyncMock(
                side_effect=OperationalError("connection refused", None, None)
            )
            result = await generate_from_template(
                db, _TENANT_XUJI, _TEMPLATE_ID, store_id=_STORE_ID
            )

        assert result["items"][0]["suggested_qty"] is None
        assert "fail-open" in result["items"][0]["qty_source"]

    @pytest.mark.asyncio
    async def test_ai_predicted_fail_open_when_os_error(self):
        """§19 round-1 P0-1: 网络层 OSError (timeout / DNS / refused) 也走 fail-open。"""
        items = [_tpl_item_row(qty_method="ai_predicted", default_qty=None)]
        db = _mk_db_get(tpl_row=_tpl_row(), items=items)

        with patch(
            "services.tx_supply.src.services.smart_replenishment.SmartReplenishmentService"
        ) as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.check_and_recommend = AsyncMock(
                side_effect=OSError("network unreachable")
            )
            result = await generate_from_template(
                db, _TENANT_XUJI, _TEMPLATE_ID, store_id=_STORE_ID
            )

        assert result["items"][0]["suggested_qty"] is None
        assert "fail-open" in result["items"][0]["qty_source"]

    @pytest.mark.asyncio
    async def test_inactive_template_rejected(self):
        db = _mk_db_get(tpl_row=_tpl_row(is_active=False), items=[])
        with pytest.raises(ValueError, match="禁用"):
            await generate_from_template(db, _TENANT_XUJI, _TEMPLATE_ID)

    @pytest.mark.asyncio
    async def test_not_found_rejected(self):
        db = _mk_db_get(tpl_row=None)
        with pytest.raises(ValueError, match="不存在"):
            await generate_from_template(db, _TENANT_XUJI, _TEMPLATE_ID)
