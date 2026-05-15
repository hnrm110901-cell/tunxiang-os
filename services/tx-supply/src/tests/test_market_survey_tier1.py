"""market_survey_service 契约测试（PRD-13 sub-A / Phase 2 W11 / T2 normal）

测试基于真实餐厅场景（CLAUDE.md §20）:
徐记海鲜采购总监凌晨 5 点出门马王堆海鲜批发市场调研:
  - draft 调研 (location='马王堆海鲜批发市场', market_type=wholesale)
  - 拍照 + 录入 12 个 SKU 价格 (鲈鱼 28/斤 / 罗非鱼 12/斤 ...)
  - 提交进训练池 (status: draft → submitted → verified)

测试范围:
  1. 主表 CRUD: create (4) / get (2) / list filter (3) / update (4) / delete (1) = 14
  2. status transition: 合法 (3) + 非法 (3) + idempotent (1) = 7
  3. items CRUD: add (3) / list / update (2) / delete = 7
  4. photos CRUD: add (3) / list / update / delete = 6
  5. get_survey_detail 聚合: 1

mock 风格沿用 test_share_split_tier1.py (含 _FakeResult plain class + asyncpg rollback 守门).
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

from services.tx_supply.src.services.market_survey_service import (  # noqa: E402
    add_item,
    add_photo,
    create_survey,
    delete_item,
    delete_photo,
    delete_survey,
    get_photo,
    get_survey,
    get_survey_detail,
    list_items_by_survey,
    list_photos_by_survey,
    list_surveys,
    transition_status,
    update_item,
    update_photo,
    update_survey,
)


# ─── 测试常量（徐记海鲜场景）────────────────────────────────────────────────

_TENANT_XUJI = "11111111-aaaa-aaaa-aaaa-111111111111"
_SURVEYOR = "cccccccc-0003-0003-0003-cccccccccccc"  # 采购总监 employee_id
_SURVEY_ID = "44444444-0001-0001-0001-444444444444"
_ITEM_ID = "55555555-0001-0001-0001-555555555555"
_PHOTO_ID = "66666666-0001-0001-0001-666666666666"
_INGREDIENT_LUYU = "22222222-0001-0001-0001-222222222222"  # 鲈鱼


def _survey_row(
    *,
    market_type: str = "wholesale",
    location_name: str = "马王堆海鲜批发市场",
    status: str = "draft",
    is_deleted: bool = False,
) -> dict:
    return {
        "id": _SURVEY_ID,
        "tenant_id": _TENANT_XUJI,
        "surveyor_id": _SURVEYOR,
        "market_type": market_type,
        "location_name": location_name,
        "surveyed_at": datetime(2026, 5, 15, 5, 0, tzinfo=timezone.utc),
        "status": status,
        "notes": None,
        "created_at": datetime(2026, 5, 15, 5, 0, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 5, 15, 5, 0, tzinfo=timezone.utc),
        "is_deleted": is_deleted,
    }


def _item_row(
    *,
    survey_id: str = _SURVEY_ID,
    ingredient_id: str | None = _INGREDIENT_LUYU,
    ingredient_name: str = "鲈鱼",
    unit_price_fen: int = 2800,  # 28 元/斤
    qty_per_unit: Decimal = Decimal("1"),
    unit: str = "斤",
    is_deleted: bool = False,
) -> dict:
    return {
        "id": _ITEM_ID,
        "tenant_id": _TENANT_XUJI,
        "survey_id": survey_id,
        "ingredient_id": ingredient_id,
        "ingredient_name": ingredient_name,
        "unit_price_fen": unit_price_fen,
        "qty_per_unit": qty_per_unit,
        "unit": unit,
        "notes": None,
        "created_at": datetime(2026, 5, 15, 5, 5, tzinfo=timezone.utc),
        "is_deleted": is_deleted,
    }


def _photo_row(
    *,
    survey_id: str = _SURVEY_ID,
    item_id: str | None = None,
    photo_url: str = "https://cos.example.com/photo1.jpg",
    caption: str | None = None,
    is_deleted: bool = False,
) -> dict:
    return {
        "id": _PHOTO_ID,
        "tenant_id": _TENANT_XUJI,
        "survey_id": survey_id,
        "item_id": item_id,
        "photo_url": photo_url,
        "caption": caption,
        "exif_meta": None,
        "uploaded_at": datetime(2026, 5, 15, 5, 10, tzinfo=timezone.utc),
        "created_at": datetime(2026, 5, 15, 5, 10, tzinfo=timezone.utc),
        "is_deleted": is_deleted,
    }


class _FakeResult:
    """plain class 替 MagicMock 链 (PRD-08 P0-3 lesson, deterministic in Python 3.11)."""

    def __init__(self, row):
        self._row = row
        self.rowcount = 1 if row is not None else 0

    def mappings(self):
        return self

    def first(self):
        return self._row

    def all(self):
        return [self._row] if self._row else []


# ─── DB Mock 工厂 ────────────────────────────────────────────────────────────


def _mk_db_create_survey(*, fail_with: Exception | None = None):
    sql_log: list[str] = []
    db = AsyncMock()
    rollback_called: dict[str, bool] = {"v": False}

    async def rollback_side_effect():
        rollback_called["v"] = True

    async def execute_side_effect(query, params=None):
        sql = str(query)
        sql_log.append(sql)
        if "set_config" in sql:
            return _FakeResult(None)
        if "INSERT INTO market_surveys" in sql:
            if fail_with is not None:
                raise fail_with
            return _FakeResult(_survey_row())
        return _FakeResult(None)

    db.execute = AsyncMock(side_effect=execute_side_effect)
    db.rollback = AsyncMock(side_effect=rollback_side_effect)
    return db, sql_log, rollback_called


def _mk_db_get_survey(*, row: dict | None) -> AsyncMock:
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        if "set_config" in sql:
            return _FakeResult(None)
        if "FROM market_surveys" in sql:
            return _FakeResult(row)
        return _FakeResult(None)

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


def _mk_db_list_surveys(rows: list[dict]):
    sql_log: list[str] = []
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        sql_log.append(sql)
        if "set_config" in sql:
            return _FakeResult(None)
        if "FROM market_surveys" in sql:
            res = MagicMock()
            res.mappings.return_value.all.return_value = rows
            return res
        return _FakeResult(None)

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db, sql_log


def _mk_db_update_survey(*, get_row: dict | None):
    sql_log: list[str] = []
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        sql_log.append(sql)
        if "set_config" in sql:
            return _FakeResult(None)
        if "FROM market_surveys" in sql:
            return _FakeResult(get_row)
        if "UPDATE market_surveys" in sql:
            return _FakeResult(get_row)
        return _FakeResult(None)

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db, sql_log


def _mk_db_transition(*, current_status: str):
    sql_log: list[str] = []
    db = AsyncMock()
    current = {"status": current_status}

    async def execute_side_effect(query, params=None):
        sql = str(query)
        sql_log.append(sql)
        if "set_config" in sql:
            return _FakeResult(None)
        if "FROM market_surveys" in sql:
            return _FakeResult(_survey_row(status=current["status"]))
        if "UPDATE market_surveys" in sql and "status" in sql:
            # 模拟 status 落库后, 后续 get 拿到新 status
            if params and "status" in params:
                current["status"] = params["status"]
            return _FakeResult(_survey_row(status=current["status"]))
        return _FakeResult(None)

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db, sql_log


def _mk_db_add_item(*, parent_survey: dict | None, fail_with: Exception | None = None):
    sql_log: list[str] = []
    db = AsyncMock()
    rollback_called: dict[str, bool] = {"v": False}

    async def rollback_side_effect():
        rollback_called["v"] = True

    async def execute_side_effect(query, params=None):
        sql = str(query)
        sql_log.append(sql)
        if "set_config" in sql:
            return _FakeResult(None)
        if "FROM market_surveys" in sql:
            return _FakeResult(parent_survey)
        if "INSERT INTO market_survey_items" in sql:
            if fail_with is not None:
                raise fail_with
            return _FakeResult(_item_row())
        return _FakeResult(None)

    db.execute = AsyncMock(side_effect=execute_side_effect)
    db.rollback = AsyncMock(side_effect=rollback_side_effect)
    return db, sql_log, rollback_called


def _mk_db_add_photo(
    *,
    parent_survey: dict | None,
    parent_item: dict | None = None,
):
    sql_log: list[str] = []
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        sql_log.append(sql)
        if "set_config" in sql:
            return _FakeResult(None)
        if "FROM market_surveys" in sql:
            return _FakeResult(parent_survey)
        if "FROM market_survey_items" in sql:
            return _FakeResult(parent_item)
        if "INSERT INTO market_survey_photos" in sql:
            return _FakeResult(_photo_row())
        return _FakeResult(None)

    db.execute = AsyncMock(side_effect=execute_side_effect)
    db.rollback = AsyncMock()
    return db, sql_log


# ═════════════════════════════════════════════════════════════════════════════
# 1. 主表 CRUD
# ═════════════════════════════════════════════════════════════════════════════


class TestCreateSurvey:
    @pytest.mark.asyncio
    async def test_create_wholesale_basic(self):
        """凌晨 5 点采购总监到马王堆海鲜批发市场调研."""
        db, sql_log, _ = _mk_db_create_survey()
        result = await create_survey(
            db,
            _TENANT_XUJI,
            surveyor_id=_SURVEYOR,
            market_type="wholesale",
            location_name="马王堆海鲜批发市场",
            surveyed_at=datetime(2026, 5, 15, 5, 0, tzinfo=timezone.utc),
        )
        assert result["market_type"] == "wholesale"
        assert result["status"] == "draft"  # 默认 draft
        insert_sqls = [s for s in sql_log if "INSERT INTO market_surveys" in s]
        assert len(insert_sqls) == 1

    @pytest.mark.asyncio
    async def test_create_invalid_market_type_raises(self):
        """market_type 必须是 4 枚举之一."""
        db, _, _ = _mk_db_create_survey()
        with pytest.raises(ValueError, match="market_type"):
            await create_survey(
                db,
                _TENANT_XUJI,
                surveyor_id=_SURVEYOR,
                market_type="black_market",  # 非法
                location_name="某市场",
                surveyed_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
            )

    @pytest.mark.asyncio
    async def test_create_empty_location_name_raises(self):
        """location_name 不能为空字符串."""
        db, _, _ = _mk_db_create_survey()
        with pytest.raises(ValueError, match="location_name"):
            await create_survey(
                db,
                _TENANT_XUJI,
                surveyor_id=_SURVEYOR,
                market_type="wholesale",
                location_name="   ",  # 空白
                surveyed_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
            )

    @pytest.mark.asyncio
    async def test_create_integrity_error_rollback_and_reset_rls(self):
        """IntegrityError 后 rollback + 重设 RLS (PRD-08 P0-3 lesson).

        asyncpg IntegrityError 不 rollback 会触 InFailedSqlTransactionError → 500.
        """
        from sqlalchemy.exc import IntegrityError

        fake_orig = Exception("duplicate")
        db, sql_log, rollback_called = _mk_db_create_survey(
            fail_with=IntegrityError(None, None, fake_orig)
        )
        with pytest.raises(ValueError, match="IntegrityError"):
            await create_survey(
                db,
                _TENANT_XUJI,
                surveyor_id=_SURVEYOR,
                market_type="wholesale",
                location_name="马王堆",
                surveyed_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
            )
        # rollback 被调
        assert rollback_called["v"] is True
        # rollback 后必须重设 RLS (set_config 第二次)
        set_configs = [s for s in sql_log if "set_config" in s]
        assert len(set_configs) >= 2


class TestGetSurvey:
    @pytest.mark.asyncio
    async def test_get_hit(self):
        db = _mk_db_get_survey(row=_survey_row())
        result = await get_survey(db, _TENANT_XUJI, _SURVEY_ID)
        assert result is not None
        assert result["market_type"] == "wholesale"

    @pytest.mark.asyncio
    async def test_get_miss(self):
        db = _mk_db_get_survey(row=None)
        result = await get_survey(db, _TENANT_XUJI, _SURVEY_ID)
        assert result is None


class TestListSurveys:
    @pytest.mark.asyncio
    async def test_list_no_filter(self):
        db, sql_log = _mk_db_list_surveys([_survey_row()])
        items = await list_surveys(db, _TENANT_XUJI)
        assert len(items) == 1
        # 主查 SQL 不包含过滤条件
        list_sqls = [s for s in sql_log if "FROM market_surveys" in s]
        assert any("market_type =" not in s and "status =" not in s for s in list_sqls)

    @pytest.mark.asyncio
    async def test_list_filter_by_market_type(self):
        """采购总监查批发市场 vs 早市价格分布."""
        db, sql_log = _mk_db_list_surveys([_survey_row(market_type="wholesale")])
        items = await list_surveys(db, _TENANT_XUJI, market_type="wholesale")
        assert len(items) == 1
        list_sqls = [s for s in sql_log if "FROM market_surveys" in s]
        assert any("market_type = :market_type" in s for s in list_sqls)

    @pytest.mark.asyncio
    async def test_list_filter_by_status_submitted(self):
        """审核员查 submitted 列表."""
        db, sql_log = _mk_db_list_surveys([_survey_row(status="submitted")])
        items = await list_surveys(db, _TENANT_XUJI, status="submitted")
        assert len(items) == 1
        list_sqls = [s for s in sql_log if "FROM market_surveys" in s]
        assert any("status = :status" in s for s in list_sqls)

    @pytest.mark.asyncio
    async def test_list_invalid_market_type_raises(self):
        db, _ = _mk_db_list_surveys([])
        with pytest.raises(ValueError, match="market_type"):
            await list_surveys(db, _TENANT_XUJI, market_type="bogus")


class TestUpdateSurvey:
    @pytest.mark.asyncio
    async def test_update_single_field(self):
        db, sql_log = _mk_db_update_survey(get_row=_survey_row())
        result = await update_survey(
            db,
            _TENANT_XUJI,
            _SURVEY_ID,
            updates={"notes": "5 点已抵达"},
        )
        assert result is not None
        update_sqls = [s for s in sql_log if "UPDATE market_surveys" in s]
        assert len(update_sqls) == 1
        assert "notes = :notes" in update_sqls[0]

    @pytest.mark.asyncio
    async def test_update_market_type_none_raises(self):
        """NOT NULL 字段 market_type=None 必须拦 (PRD-11 P1-1 lesson)."""
        db, _ = _mk_db_update_survey(get_row=_survey_row())
        with pytest.raises(ValueError, match="market_type"):
            await update_survey(
                db,
                _TENANT_XUJI,
                _SURVEY_ID,
                updates={"market_type": None},
            )

    @pytest.mark.asyncio
    async def test_update_location_name_empty_raises(self):
        """location_name 空字符串拦 (NOT NULL 列 + 业务非空)."""
        db, _ = _mk_db_update_survey(get_row=_survey_row())
        with pytest.raises(ValueError, match="location_name"):
            await update_survey(
                db,
                _TENANT_XUJI,
                _SURVEY_ID,
                updates={"location_name": "   "},
            )

    @pytest.mark.asyncio
    async def test_update_no_fields_raises(self):
        db, _ = _mk_db_update_survey(get_row=_survey_row())
        with pytest.raises(ValueError, match="至少提供一个更新字段"):
            await update_survey(db, _TENANT_XUJI, _SURVEY_ID, updates={})

    @pytest.mark.asyncio
    async def test_update_not_found_raises(self):
        db, _ = _mk_db_update_survey(get_row=None)
        with pytest.raises(ValueError, match="不存在"):
            await update_survey(
                db,
                _TENANT_XUJI,
                _SURVEY_ID,
                updates={"notes": "x"},
            )


class TestDeleteSurvey:
    @pytest.mark.asyncio
    async def test_delete_soft(self):
        db, _ = _mk_db_update_survey(get_row=_survey_row())
        ok = await delete_survey(db, _TENANT_XUJI, _SURVEY_ID)
        assert ok is True


# ═════════════════════════════════════════════════════════════════════════════
# 2. status transition
# ═════════════════════════════════════════════════════════════════════════════


class TestTransitionStatus:
    @pytest.mark.asyncio
    async def test_draft_to_submitted_ok(self):
        """移动端提交调研 → 进训练池候选."""
        db, sql_log = _mk_db_transition(current_status="draft")
        result = await transition_status(
            db, _TENANT_XUJI, _SURVEY_ID, target_status="submitted"
        )
        assert result["status"] == "submitted"
        update_sqls = [s for s in sql_log if "UPDATE market_surveys" in s and "status" in s]
        assert len(update_sqls) == 1

    @pytest.mark.asyncio
    async def test_submitted_to_verified_ok(self):
        """采购总监审核合格 → 进训练池."""
        db, _ = _mk_db_transition(current_status="submitted")
        result = await transition_status(
            db, _TENANT_XUJI, _SURVEY_ID, target_status="verified"
        )
        assert result["status"] == "verified"

    @pytest.mark.asyncio
    async def test_submitted_back_to_draft_ok(self):
        """审核员退回起草 (信息不全)."""
        db, _ = _mk_db_transition(current_status="submitted")
        result = await transition_status(
            db, _TENANT_XUJI, _SURVEY_ID, target_status="draft"
        )
        assert result["status"] == "draft"

    @pytest.mark.asyncio
    async def test_draft_to_verified_illegal_raises(self):
        """skip 提交 直接 verified 非法."""
        db, _ = _mk_db_transition(current_status="draft")
        with pytest.raises(ValueError, match="非法 status 转换"):
            await transition_status(
                db, _TENANT_XUJI, _SURVEY_ID, target_status="verified"
            )

    @pytest.mark.asyncio
    async def test_verified_to_submitted_illegal_raises(self):
        """verified 是终态, 不可改 (历史数据稳定)."""
        db, _ = _mk_db_transition(current_status="verified")
        with pytest.raises(ValueError, match="非法 status 转换"):
            await transition_status(
                db, _TENANT_XUJI, _SURVEY_ID, target_status="submitted"
            )

    @pytest.mark.asyncio
    async def test_idempotent_same_status(self):
        """同 status idempotent — 不写 DB."""
        db, sql_log = _mk_db_transition(current_status="submitted")
        result = await transition_status(
            db, _TENANT_XUJI, _SURVEY_ID, target_status="submitted"
        )
        assert result["status"] == "submitted"
        update_sqls = [
            s for s in sql_log if "UPDATE market_surveys" in s and "status" in s
        ]
        assert len(update_sqls) == 0  # 同状态不写 DB

    @pytest.mark.asyncio
    async def test_invalid_target_status_raises(self):
        db, _ = _mk_db_transition(current_status="draft")
        with pytest.raises(ValueError, match="target_status"):
            await transition_status(
                db, _TENANT_XUJI, _SURVEY_ID, target_status="archived"
            )


# ═════════════════════════════════════════════════════════════════════════════
# 3. items CRUD
# ═════════════════════════════════════════════════════════════════════════════


class TestAddItem:
    @pytest.mark.asyncio
    async def test_add_basic_with_ingredient_id(self):
        """录入鲈鱼 28元/斤 (有系统 ingredient 对应)."""
        db, sql_log, _ = _mk_db_add_item(parent_survey=_survey_row())
        result = await add_item(
            db,
            _TENANT_XUJI,
            survey_id=_SURVEY_ID,
            ingredient_id=_INGREDIENT_LUYU,
            ingredient_name="鲈鱼",
            unit_price_fen=2800,
            qty_per_unit=Decimal("1"),
            unit="斤",
        )
        assert result["ingredient_name"] == "鲈鱼"
        assert result["unit_price_fen"] == 2800
        insert_sqls = [s for s in sql_log if "INSERT INTO market_survey_items" in s]
        assert len(insert_sqls) == 1

    @pytest.mark.asyncio
    async def test_add_free_text_ingredient_fallback(self):
        """系统无对应 ingredient — 自由文本兜底 (海鲜调研常见)."""
        db, _, _ = _mk_db_add_item(parent_survey=_survey_row())
        result = await add_item(
            db,
            _TENANT_XUJI,
            survey_id=_SURVEY_ID,
            ingredient_id=None,  # NULL = 自由文本
            ingredient_name="梭子蟹（活体）",
            unit_price_fen=8000,
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_add_parent_survey_missing_raises(self):
        """survey_id 不存在 → ValueError."""
        db, _, _ = _mk_db_add_item(parent_survey=None)
        with pytest.raises(ValueError, match="不存在"):
            await add_item(
                db,
                _TENANT_XUJI,
                survey_id=_SURVEY_ID,
                ingredient_name="鲈鱼",
                unit_price_fen=2800,
            )

    @pytest.mark.asyncio
    async def test_add_negative_price_raises(self):
        db, _, _ = _mk_db_add_item(parent_survey=_survey_row())
        with pytest.raises(ValueError, match="unit_price_fen"):
            await add_item(
                db,
                _TENANT_XUJI,
                survey_id=_SURVEY_ID,
                ingredient_name="鲈鱼",
                unit_price_fen=-1,
            )

    @pytest.mark.asyncio
    async def test_add_zero_qty_raises(self):
        db, _, _ = _mk_db_add_item(parent_survey=_survey_row())
        with pytest.raises(ValueError, match="qty_per_unit"):
            await add_item(
                db,
                _TENANT_XUJI,
                survey_id=_SURVEY_ID,
                ingredient_name="鲈鱼",
                unit_price_fen=2800,
                qty_per_unit=Decimal("0"),
            )


class TestUpdateItem:
    def _mk_db_item_update(self, get_row):
        sql_log: list[str] = []
        db = AsyncMock()

        async def execute_side_effect(query, params=None):
            sql = str(query)
            sql_log.append(sql)
            if "set_config" in sql:
                return _FakeResult(None)
            if "FROM market_survey_items" in sql:
                return _FakeResult(get_row)
            if "UPDATE market_survey_items" in sql:
                return _FakeResult(get_row)
            return _FakeResult(None)

        db.execute = AsyncMock(side_effect=execute_side_effect)
        return db, sql_log

    @pytest.mark.asyncio
    async def test_update_price_only(self):
        """采购总监修正价格 (录错)."""
        db, sql_log = self._mk_db_item_update(_item_row())
        result = await update_item(
            db, _TENANT_XUJI, _ITEM_ID, updates={"unit_price_fen": 3000}
        )
        assert result is not None
        update_sqls = [s for s in sql_log if "UPDATE market_survey_items" in s]
        assert any("unit_price_fen = :unit_price_fen" in s for s in update_sqls)

    @pytest.mark.asyncio
    async def test_update_price_none_raises(self):
        """unit_price_fen=None NOT NULL → ValueError (PRD-11 P1-1 lesson)."""
        db, _ = self._mk_db_item_update(_item_row())
        with pytest.raises(ValueError, match="unit_price_fen"):
            await update_item(
                db, _TENANT_XUJI, _ITEM_ID, updates={"unit_price_fen": None}
            )

    @pytest.mark.asyncio
    async def test_update_qty_per_unit_none_raises(self):
        db, _ = self._mk_db_item_update(_item_row())
        with pytest.raises(ValueError, match="qty_per_unit"):
            await update_item(
                db, _TENANT_XUJI, _ITEM_ID, updates={"qty_per_unit": None}
            )

    @pytest.mark.asyncio
    async def test_update_ingredient_id_to_null_allowed(self):
        """ingredient_id=None 允许 (改为自由文本兜底)."""
        db, _ = self._mk_db_item_update(_item_row())
        # 同时改 ingredient_name 让业务上合理
        result = await update_item(
            db,
            _TENANT_XUJI,
            _ITEM_ID,
            updates={"ingredient_id": None, "ingredient_name": "野生石斑"},
        )
        assert result is not None


class TestListItemsBySurvey:
    @pytest.mark.asyncio
    async def test_list_returns_items(self):
        db = AsyncMock()

        async def execute_side_effect(query, params=None):
            sql = str(query)
            if "set_config" in sql:
                return _FakeResult(None)
            if "FROM market_survey_items" in sql:
                res = MagicMock()
                res.mappings.return_value.all.return_value = [_item_row(), _item_row()]
                return res
            return _FakeResult(None)

        db.execute = AsyncMock(side_effect=execute_side_effect)
        items = await list_items_by_survey(db, _TENANT_XUJI, _SURVEY_ID)
        assert len(items) == 2


class TestDeleteItem:
    @pytest.mark.asyncio
    async def test_delete_soft(self):
        db = AsyncMock()

        async def execute_side_effect(query, params=None):
            sql = str(query)
            if "set_config" in sql:
                return _FakeResult(None)
            if "UPDATE market_survey_items" in sql:
                return _FakeResult(_item_row())
            return _FakeResult(None)

        db.execute = AsyncMock(side_effect=execute_side_effect)
        ok = await delete_item(db, _TENANT_XUJI, _ITEM_ID)
        assert ok is True


# ═════════════════════════════════════════════════════════════════════════════
# 4. photos CRUD
# ═════════════════════════════════════════════════════════════════════════════


class TestAddPhoto:
    @pytest.mark.asyncio
    async def test_add_cover_photo_no_item_id(self):
        """调研封面图 (item_id=None) — 早市全景照."""
        db, sql_log = _mk_db_add_photo(parent_survey=_survey_row())
        result = await add_photo(
            db,
            _TENANT_XUJI,
            survey_id=_SURVEY_ID,
            photo_url="https://cos.example.com/cover.jpg",
        )
        assert result is not None
        insert_sqls = [s for s in sql_log if "INSERT INTO market_survey_photos" in s]
        assert len(insert_sqls) == 1

    @pytest.mark.asyncio
    async def test_add_item_level_photo(self):
        """item-level 价签照 (鲈鱼价签近景)."""
        db, _ = _mk_db_add_photo(
            parent_survey=_survey_row(),
            parent_item=_item_row(survey_id=_SURVEY_ID),
        )
        result = await add_photo(
            db,
            _TENANT_XUJI,
            survey_id=_SURVEY_ID,
            item_id=_ITEM_ID,
            photo_url="https://cos.example.com/luyu_price.jpg",
            caption="鲈鱼 28 元/斤 价签",
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_add_photo_cross_survey_item_raises(self):
        """item_id 属于别的 survey → ValueError (业务校验)."""
        other_item = _item_row(survey_id="99999999-0009-0009-0009-999999999999")
        db, _ = _mk_db_add_photo(
            parent_survey=_survey_row(),
            parent_item=other_item,
        )
        with pytest.raises(ValueError, match="不属于"):
            await add_photo(
                db,
                _TENANT_XUJI,
                survey_id=_SURVEY_ID,
                item_id=_ITEM_ID,
                photo_url="https://cos.example.com/x.jpg",
            )

    @pytest.mark.asyncio
    async def test_add_photo_empty_url_raises(self):
        db, _ = _mk_db_add_photo(parent_survey=_survey_row())
        with pytest.raises(ValueError, match="photo_url"):
            await add_photo(
                db,
                _TENANT_XUJI,
                survey_id=_SURVEY_ID,
                photo_url="   ",
            )


class TestUpdatePhoto:
    @pytest.mark.asyncio
    async def test_update_caption_only(self):
        db = AsyncMock()

        async def execute_side_effect(query, params=None):
            sql = str(query)
            if "set_config" in sql:
                return _FakeResult(None)
            if "FROM market_survey_photos" in sql:
                return _FakeResult(_photo_row())
            if "UPDATE market_survey_photos" in sql:
                return _FakeResult(_photo_row())
            return _FakeResult(None)

        db.execute = AsyncMock(side_effect=execute_side_effect)
        result = await update_photo(
            db, _TENANT_XUJI, _PHOTO_ID, updates={"caption": "鲈鱼 28/斤"}
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_update_no_field_raises(self):
        db = AsyncMock()

        async def execute_side_effect(query, params=None):
            sql = str(query)
            if "set_config" in sql:
                return _FakeResult(None)
            return _FakeResult(_photo_row())

        db.execute = AsyncMock(side_effect=execute_side_effect)
        with pytest.raises(ValueError, match="至少提供一个更新字段"):
            await update_photo(db, _TENANT_XUJI, _PHOTO_ID, updates={})


class TestListPhotosBySurvey:
    @pytest.mark.asyncio
    async def test_list_returns_photos(self):
        db = AsyncMock()

        async def execute_side_effect(query, params=None):
            sql = str(query)
            if "set_config" in sql:
                return _FakeResult(None)
            if "FROM market_survey_photos" in sql:
                res = MagicMock()
                res.mappings.return_value.all.return_value = [_photo_row()]
                return res
            return _FakeResult(None)

        db.execute = AsyncMock(side_effect=execute_side_effect)
        photos = await list_photos_by_survey(db, _TENANT_XUJI, _SURVEY_ID)
        assert len(photos) == 1


class TestDeletePhoto:
    @pytest.mark.asyncio
    async def test_delete_soft(self):
        db = AsyncMock()

        async def execute_side_effect(query, params=None):
            sql = str(query)
            if "set_config" in sql:
                return _FakeResult(None)
            if "UPDATE market_survey_photos" in sql:
                return _FakeResult(_photo_row())
            return _FakeResult(None)

        db.execute = AsyncMock(side_effect=execute_side_effect)
        ok = await delete_photo(db, _TENANT_XUJI, _PHOTO_ID)
        assert ok is True


# ═════════════════════════════════════════════════════════════════════════════
# 5. get_survey_detail 聚合
# ═════════════════════════════════════════════════════════════════════════════


class TestGetSurveyDetail:
    @pytest.mark.asyncio
    async def test_detail_aggregates_survey_items_photos(self):
        """UI 详情页一次性加载: 主表 + items + photos."""
        db = AsyncMock()

        async def execute_side_effect(query, params=None):
            sql = str(query)
            if "set_config" in sql:
                return _FakeResult(None)
            if "FROM market_surveys" in sql:
                return _FakeResult(_survey_row())
            if "FROM market_survey_items" in sql:
                res = MagicMock()
                res.mappings.return_value.all.return_value = [_item_row()]
                return res
            if "FROM market_survey_photos" in sql:
                res = MagicMock()
                res.mappings.return_value.all.return_value = [_photo_row()]
                return res
            return _FakeResult(None)

        db.execute = AsyncMock(side_effect=execute_side_effect)
        detail = await get_survey_detail(db, _TENANT_XUJI, _SURVEY_ID)
        assert detail is not None
        assert detail["survey"]["id"] == _SURVEY_ID
        assert len(detail["items"]) == 1
        assert len(detail["photos"]) == 1

    @pytest.mark.asyncio
    async def test_detail_returns_none_when_survey_missing(self):
        db = AsyncMock()

        async def execute_side_effect(query, params=None):
            sql = str(query)
            if "set_config" in sql:
                return _FakeResult(None)
            return _FakeResult(None)

        db.execute = AsyncMock(side_effect=execute_side_effect)
        detail = await get_survey_detail(db, _TENANT_XUJI, _SURVEY_ID)
        assert detail is None
