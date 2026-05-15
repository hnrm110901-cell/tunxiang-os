"""share_split_service 契约测试（PRD-11 sub-A / Phase 2 W11 / T2 + Tier 1 邻接）

测试基于真实餐厅场景（CLAUDE.md §20）:
徐记海鲜 1 份酸菜鱼分给 2 人吃 → cost 分摊场景:
- EVEN: ¥98 BOM cost 9800 fen → 2 人各 4900 fen
- WEIGHTED: weights=[3,2] → 5880 / 3920 (按 60%/40% 切分)
- MANUAL: amounts_fen=[5000, 4800] → strict sum check pass
- 异常: dish 不允许分享 / 超过 max_share_count / sum mismatch / etc.

  1. CRUD: create 4 (含 P0-3 软禁用 row IntegrityError 路径) + get 2 + list 4 + update 5 + delete 2 = 17
  2. resolve_split: EVEN 4 + WEIGHTED 4 + MANUAL 4 + 边界 2 = 14
  3. apply_split: 5 (rule 缺/禁用/不允许分享/超上限/正常)

mock 风格沿用 test_dept_whitelist_tier1.py (含 _FakeResult plain class + asyncpg rollback 守门).
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

from services.tx_supply.src.models.share_split_models import (  # noqa: E402
    ShareSplitMethod,
    ShareSplitSpec,
)
from services.tx_supply.src.services.share_split_service import (  # noqa: E402
    apply_split,
    create_rule,
    delete_rule,
    get_rule,
    get_rule_by_dish,
    list_rules,
    resolve_split,
    update_rule,
)


# ─── 测试常量（徐记海鲜场景）────────────────────────────────────────────────

_TENANT_XUJI = "11111111-aaaa-aaaa-aaaa-111111111111"
_USER_BUYER = "cccccccc-0003-0003-0003-cccccccccccc"
_DISH_SUANCAIYU = "22222222-0001-0001-0001-222222222222"  # 酸菜鱼
_DISH_HOTPOT = "22222222-0002-0002-0002-222222222222"  # 火锅
_RULE_ID = "33333333-0001-0001-0001-333333333333"


def _rule_row(
    *,
    dish_id: str = _DISH_SUANCAIYU,
    allow_share: bool = True,
    default_method: str = "even",
    max_share_count: int | None = None,
    is_active: bool = True,
    is_deleted: bool = False,
) -> dict:
    return {
        "id": _RULE_ID,
        "tenant_id": _TENANT_XUJI,
        "dish_id": dish_id,
        "allow_share": allow_share,
        "default_method": default_method,
        "max_share_count": max_share_count,
        "is_active": is_active,
        "notes": None,
        "created_by": _USER_BUYER,
        "created_at": datetime(2026, 5, 15, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 5, 15, tzinfo=timezone.utc),
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


def _mk_db_create(*, fail_with: Exception | None = None, existing_row: dict | None = None):
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
        if "INSERT INTO share_split_rules" in sql:
            if fail_with is not None:
                raise fail_with
            return _FakeResult(_rule_row())
        if "FROM share_split_rules" in sql and "dish_id" in sql:
            return _FakeResult(existing_row)
        return _FakeResult(None)

    db.execute = AsyncMock(side_effect=execute_side_effect)
    db.rollback = AsyncMock(side_effect=rollback_side_effect)
    return db, sql_log, rollback_called


def _mk_db_get(*, row: dict | None) -> AsyncMock:
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        if "set_config" in sql:
            return _FakeResult(None)
        if "FROM share_split_rules" in sql:
            return _FakeResult(row)
        return _FakeResult(None)

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


def _mk_db_list(rows: list[dict]):
    sql_log: list[str] = []
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        sql_log.append(sql)
        if "set_config" in sql:
            return _FakeResult(None)
        if "FROM share_split_rules" in sql:
            res = MagicMock()
            res.mappings.return_value.all.return_value = rows
            return res
        return _FakeResult(None)

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db, sql_log


def _mk_db_update(*, get_row: dict | None):
    sql_log: list[str] = []
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        sql_log.append(sql)
        if "set_config" in sql:
            return _FakeResult(None)
        if "FROM share_split_rules" in sql:
            return _FakeResult(get_row)
        if "UPDATE share_split_rules" in sql:
            return _FakeResult(get_row)
        return _FakeResult(None)

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db, sql_log


# ─── 1. CRUD: create_rule ────────────────────────────────────────────────────


class TestCreateRule:
    @pytest.mark.asyncio
    async def test_create_suancaiyu_even_method(self):
        db, sql_log, _ = _mk_db_create()
        result = await create_rule(
            db,
            _TENANT_XUJI,
            dish_id=_DISH_SUANCAIYU,
            created_by=_USER_BUYER,
            allow_share=True,
            default_method="even",
        )
        assert result["dish_id"] == _DISH_SUANCAIYU
        insert_sqls = [s for s in sql_log if "INSERT INTO share_split_rules" in s]
        assert len(insert_sqls) == 1

    @pytest.mark.asyncio
    async def test_rejects_invalid_method(self):
        db, _, _ = _mk_db_create()
        with pytest.raises(ValueError, match="default_method"):
            await create_rule(
                db,
                _TENANT_XUJI,
                dish_id=_DISH_SUANCAIYU,
                created_by=_USER_BUYER,
                default_method="bogus_method",
            )

    @pytest.mark.asyncio
    async def test_rejects_max_share_below_2(self):
        db, _, _ = _mk_db_create()
        with pytest.raises(ValueError, match="max_share_count"):
            await create_rule(
                db,
                _TENANT_XUJI,
                dish_id=_DISH_SUANCAIYU,
                created_by=_USER_BUYER,
                max_share_count=1,
            )

    @pytest.mark.asyncio
    async def test_duplicate_active_raises_already_exists(self):
        """UNIQUE violation when row is_active=TRUE → "已存在" (路由 409)."""
        from sqlalchemy.exc import IntegrityError

        db, _, rollback_called = _mk_db_create(
            fail_with=IntegrityError("duplicate", None, None),
            existing_row=_rule_row(is_active=True),
        )
        with pytest.raises(ValueError, match="已存在"):
            await create_rule(
                db,
                _TENANT_XUJI,
                dish_id=_DISH_SUANCAIYU,
                created_by=_USER_BUYER,
            )
        # P0-3 守门: rollback 必须调用
        db.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_duplicate_soft_disabled_returns_patch_guidance_p0_2(self):
        """PRD-08 P0-2 lesson 同模式: 软禁用 row 给 PATCH 引导."""
        from sqlalchemy.exc import IntegrityError

        db, _, rollback_called = _mk_db_create(
            fail_with=IntegrityError("duplicate", None, None),
            existing_row=_rule_row(is_active=False),
        )
        with pytest.raises(ValueError) as exc_info:
            await create_rule(
                db,
                _TENANT_XUJI,
                dish_id=_DISH_SUANCAIYU,
                created_by=_USER_BUYER,
            )
        msg = str(exc_info.value)
        assert "已存在但被禁用" in msg
        assert _RULE_ID in msg
        assert "PATCH" in msg
        db.rollback.assert_awaited_once()


# ─── 2. CRUD: get / list / update / delete ──────────────────────────────────


class TestGetListUpdateDelete:
    @pytest.mark.asyncio
    async def test_get_rule_returns_row(self):
        db = _mk_db_get(row=_rule_row())
        result = await get_rule(db, _TENANT_XUJI, _RULE_ID)
        assert result is not None
        assert result["dish_id"] == _DISH_SUANCAIYU

    @pytest.mark.asyncio
    async def test_get_rule_not_found(self):
        db = _mk_db_get(row=None)
        assert await get_rule(db, _TENANT_XUJI, _RULE_ID) is None

    @pytest.mark.asyncio
    async def test_get_rule_by_dish_returns_row(self):
        db = _mk_db_get(row=_rule_row())
        result = await get_rule_by_dish(db, _TENANT_XUJI, _DISH_SUANCAIYU)
        assert result is not None
        assert result["dish_id"] == _DISH_SUANCAIYU

    @pytest.mark.asyncio
    async def test_list_rules_returns_rows(self):
        db, _ = _mk_db_list([_rule_row(), _rule_row(dish_id=_DISH_HOTPOT)])
        result = await list_rules(db, _TENANT_XUJI)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_rules_only_active(self):
        db, sql_log = _mk_db_list([_rule_row()])
        await list_rules(db, _TENANT_XUJI, only_active=True)
        active_sql = next((s for s in sql_log if "is_active = TRUE" in s), "")
        assert "is_active = TRUE" in active_sql

    @pytest.mark.asyncio
    async def test_list_rejects_invalid_limit(self):
        db, _ = _mk_db_list([])
        with pytest.raises(ValueError, match="limit"):
            await list_rules(db, _TENANT_XUJI, limit=0)

    @pytest.mark.asyncio
    async def test_update_allow_share(self):
        db, sql_log = _mk_db_update(get_row=_rule_row(allow_share=False))
        result = await update_rule(
            db, _TENANT_XUJI, _RULE_ID, updates={"allow_share": False}
        )
        assert result["allow_share"] is False
        update_sqls = [s for s in sql_log if "UPDATE share_split_rules" in s]
        assert update_sqls
        assert "allow_share = :allow_share" in update_sqls[0]

    @pytest.mark.asyncio
    async def test_update_max_share_count_to_null_p0_1_regression(self):
        """PRD-08 P0-1 lesson 同模式: max_share_count=None 必须能写 NULL."""
        db, sql_log = _mk_db_update(get_row=_rule_row(max_share_count=None))
        result = await update_rule(
            db,
            _TENANT_XUJI,
            _RULE_ID,
            updates={"max_share_count": None},
        )
        assert result["max_share_count"] is None
        update_sqls = [s for s in sql_log if "UPDATE share_split_rules" in s]
        assert "max_share_count = :max_share_count" in update_sqls[0]
        assert "COALESCE" not in update_sqls[0]

    @pytest.mark.asyncio
    async def test_update_no_fields_rejected(self):
        db, _ = _mk_db_update(get_row=_rule_row())
        with pytest.raises(ValueError, match="至少"):
            await update_rule(db, _TENANT_XUJI, _RULE_ID, updates={})

    @pytest.mark.asyncio
    async def test_update_not_found(self):
        db, _ = _mk_db_update(get_row=None)
        with pytest.raises(ValueError, match="不存在"):
            await update_rule(
                db, _TENANT_XUJI, _RULE_ID, updates={"allow_share": False}
            )

    @pytest.mark.asyncio
    async def test_update_rejects_invalid_method(self):
        db, _ = _mk_db_update(get_row=_rule_row())
        with pytest.raises(ValueError, match="default_method"):
            await update_rule(
                db, _TENANT_XUJI, _RULE_ID, updates={"default_method": "bogus"}
            )

    @pytest.mark.asyncio
    async def test_delete_rule_success(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_FakeResult(_rule_row()))
        assert await delete_rule(db, _TENANT_XUJI, _RULE_ID) is True

    @pytest.mark.asyncio
    async def test_delete_rule_not_found(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_FakeResult(None))
        assert await delete_rule(db, _TENANT_XUJI, _RULE_ID) is False


# ─── 3. resolve_split: EVEN ─────────────────────────────────────────────────


class TestResolveSplitEven:
    def test_even_split_2_no_remainder(self):
        """¥98 (9800 fen) ÷ 2 = 4900/4900, 无余数."""
        spec = ShareSplitSpec(method=ShareSplitMethod.EVEN, count=2)
        result = resolve_split(spec, 9800)
        assert result.method == ShareSplitMethod.EVEN
        assert result.count == 2
        assert [s.attributed_cost_fen for s in result.shares] == [4900, 4900]
        assert sum(s.attributed_cost_fen for s in result.shares) == 9800

    def test_even_split_3_with_remainder(self):
        """100 fen ÷ 3 = 34/33/33 (余 1 fen 给 share[0])."""
        spec = ShareSplitSpec(method=ShareSplitMethod.EVEN, count=3)
        result = resolve_split(spec, 100)
        amounts = [s.attributed_cost_fen for s in result.shares]
        assert sum(amounts) == 100
        # 余数 1 fen 分给 share[0]
        assert amounts == [34, 33, 33]

    def test_even_split_4_remainder_2(self):
        """101 fen ÷ 4 = 26/25/25/25 (余 1 fen 给 share[0])."""
        spec = ShareSplitSpec(method=ShareSplitMethod.EVEN, count=4)
        result = resolve_split(spec, 101)
        amounts = [s.attributed_cost_fen for s in result.shares]
        assert sum(amounts) == 101
        assert amounts == [26, 25, 25, 25]

    def test_even_split_zero_cost(self):
        """0 cost 也支持 (赠品场景), 所有 share 都 0."""
        spec = ShareSplitSpec(method=ShareSplitMethod.EVEN, count=2)
        result = resolve_split(spec, 0)
        assert all(s.attributed_cost_fen == 0 for s in result.shares)


# ─── 4. resolve_split: WEIGHTED ─────────────────────────────────────────────


class TestResolveSplitWeighted:
    def test_weighted_3_2_no_remainder(self):
        """¥98 (9800 fen) × [3,2] / 5 = 5880, 3920 — 整除."""
        spec = ShareSplitSpec(
            method=ShareSplitMethod.WEIGHTED,
            count=2,
            weights=[Decimal("3"), Decimal("2")],
        )
        result = resolve_split(spec, 9800)
        amounts = [s.attributed_cost_fen for s in result.shares]
        assert amounts == [5880, 3920]
        assert sum(amounts) == 9800

    def test_weighted_remainder_to_largest(self):
        """100 fen × [1,1,1] / 3 → 33/33/33, 余 1 给 weight 最大 (tie → 第一个 index)."""
        spec = ShareSplitSpec(
            method=ShareSplitMethod.WEIGHTED,
            count=3,
            weights=[Decimal("1"), Decimal("1"), Decimal("1")],
        )
        result = resolve_split(spec, 100)
        amounts = [s.attributed_cost_fen for s in result.shares]
        assert sum(amounts) == 100
        # 余 1 fen 给 share[0] (tie 时降序排第一)
        assert amounts == [34, 33, 33]

    def test_weighted_unequal_with_remainder(self):
        """101 fen × [3,2] / 5 = 60.6 / 40.4 → trunc [60,40] 余 1 → [61,40]."""
        spec = ShareSplitSpec(
            method=ShareSplitMethod.WEIGHTED,
            count=2,
            weights=[Decimal("3"), Decimal("2")],
        )
        result = resolve_split(spec, 101)
        amounts = [s.attributed_cost_fen for s in result.shares]
        assert sum(amounts) == 101
        # weight 大的 share[0] 拿 remainder
        assert amounts == [61, 40]

    def test_weighted_zero_weights_raises(self):
        """sum(weights)=0 → ValueError."""
        # pydantic validator 已拦截 weight=0 (每项必须 > 0), 这里测试 resolve 内部守门
        # 直接构造非法 spec 跳过 pydantic 校验
        spec = ShareSplitSpec(
            method=ShareSplitMethod.WEIGHTED,
            count=2,
            weights=[Decimal("1"), Decimal("1")],
        )
        spec.weights = [Decimal("0"), Decimal("0")]  # 绕过 pydantic 直接改
        with pytest.raises(ValueError, match="sum"):
            resolve_split(spec, 100)


# ─── 5. resolve_split: MANUAL ───────────────────────────────────────────────


class TestResolveSplitManual:
    def test_manual_strict_sum_pass(self):
        """amounts_fen=[5000, 4800], total 9800 (匹配) — pass."""
        spec = ShareSplitSpec(
            method=ShareSplitMethod.MANUAL,
            count=2,
            amounts_fen=[5000, 4800],
        )
        result = resolve_split(spec, 9800)
        amounts = [s.attributed_cost_fen for s in result.shares]
        assert amounts == [5000, 4800]

    def test_manual_strict_sum_mismatch_raises(self):
        """amounts_fen=[5000, 4000], total 9000 ≠ 9800 → ValueError."""
        spec = ShareSplitSpec(
            method=ShareSplitMethod.MANUAL,
            count=2,
            amounts_fen=[5000, 4000],
        )
        with pytest.raises(ValueError, match="MANUAL"):
            resolve_split(spec, 9800)

    def test_manual_weight_normalized_from_amounts(self):
        """weight = amount / total (反推)."""
        spec = ShareSplitSpec(
            method=ShareSplitMethod.MANUAL,
            count=2,
            amounts_fen=[7000, 3000],
        )
        result = resolve_split(spec, 10000)
        assert result.shares[0].weight == Decimal("0.7")
        assert result.shares[1].weight == Decimal("0.3")

    def test_manual_zero_cost_zero_amounts(self):
        """0 total + [0, 0] amounts → 通过, weights 全 0."""
        spec = ShareSplitSpec(
            method=ShareSplitMethod.MANUAL,
            count=2,
            amounts_fen=[0, 0],
        )
        result = resolve_split(spec, 0)
        assert all(s.attributed_cost_fen == 0 for s in result.shares)
        assert all(s.weight == Decimal(0) for s in result.shares)


# ─── 6. apply_split (rule + spec 综合) ───────────────────────────────────────


class TestApplySplit:
    @pytest.mark.asyncio
    async def test_apply_split_no_rule_raises(self):
        """dish 未配置 share_split_rule → ValueError."""
        db = _mk_db_get(row=None)
        spec = ShareSplitSpec(method=ShareSplitMethod.EVEN, count=2)
        with pytest.raises(ValueError, match="未配置"):
            await apply_split(db, _TENANT_XUJI, dish_id=_DISH_SUANCAIYU, spec=spec, bom_cost_total_fen=100)

    @pytest.mark.asyncio
    async def test_apply_split_rule_disabled_raises(self):
        """rule.is_active=FALSE → ValueError."""
        db = _mk_db_get(row=_rule_row(is_active=False))
        spec = ShareSplitSpec(method=ShareSplitMethod.EVEN, count=2)
        with pytest.raises(ValueError, match="禁用"):
            await apply_split(db, _TENANT_XUJI, dish_id=_DISH_SUANCAIYU, spec=spec, bom_cost_total_fen=100)

    @pytest.mark.asyncio
    async def test_apply_split_allow_share_false_raises(self):
        """rule.allow_share=FALSE → ValueError."""
        db = _mk_db_get(row=_rule_row(allow_share=False))
        spec = ShareSplitSpec(method=ShareSplitMethod.EVEN, count=2)
        with pytest.raises(ValueError, match="不允许分享"):
            await apply_split(db, _TENANT_XUJI, dish_id=_DISH_SUANCAIYU, spec=spec, bom_cost_total_fen=100)

    @pytest.mark.asyncio
    async def test_apply_split_exceeds_max_share_count(self):
        """spec.count > rule.max_share_count → ValueError."""
        db = _mk_db_get(row=_rule_row(max_share_count=3))
        spec = ShareSplitSpec(method=ShareSplitMethod.EVEN, count=5)
        with pytest.raises(ValueError, match="超过"):
            await apply_split(db, _TENANT_XUJI, dish_id=_DISH_SUANCAIYU, spec=spec, bom_cost_total_fen=100)

    @pytest.mark.asyncio
    async def test_apply_split_happy_path(self):
        """正常路径: 规则允许 + spec 有效 → resolve 成功."""
        db = _mk_db_get(row=_rule_row(allow_share=True, max_share_count=4))
        spec = ShareSplitSpec(method=ShareSplitMethod.EVEN, count=2)
        result = await apply_split(
            db, _TENANT_XUJI, dish_id=_DISH_SUANCAIYU, spec=spec, bom_cost_total_fen=9800
        )
        assert result.method == ShareSplitMethod.EVEN
        assert result.count == 2
        assert sum(s.attributed_cost_fen for s in result.shares) == 9800
