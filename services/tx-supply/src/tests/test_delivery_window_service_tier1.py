"""Tier 1 — delivery_window_service 契约测试（PRD-05 / 食安硬约束）

CLAUDE.md §17 Tier 1 三条硬约束之一：食安合规 — 临期/过期食材不可用于出品。
PRD-05 扩展：供应商配送时间窗 — 生鲜必须 4-7 点到货（厨房 9 点开档前完成质检/分拣），
违约自动记 supplier_delivery_violations + 扣 supplier_scoring.delivery_rate 分。

测试基于真实餐厅场景（CLAUDE.md §20）：

  1. CRUD 6 用例（create/list active 过滤/get/get-lock/soft_delete 2 路径）
  2. 二级审批 2 用例（approve 成功 / self-approve 拒绝）
  3. RLS 1 用例（set_config 必须调用）
  4. check_delivery_window 6 用例
     - 无配置 → fail-open within=True, weekday_matched=False
     - weekday 不匹配 → fail-open
     - 正常窗内 → within=True
     - 晚到 → violation_kind=late, minutes 正确
     - 早到 → violation_kind=early, minutes 正确
     - 边界容忍（latest + grace 刚好）→ within=True
  5. record_violation 2 用例（写日志 / ON CONFLICT 幂等返回 None）
  6. count_violations 1 用例（聚合 supplier 期间次数）

mock 风格：AsyncMock — 参考 test_yield_standard_service_tier1.py / test_weight_standard_service_tier1.py。
"""

from __future__ import annotations

import sys
from datetime import date, datetime, time, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

# 本机 Python 3.9 环境 stub 注入会污染 sys.modules（feedback_pytest_stub_setdefault_pitfall.md 教训）
# 故 < 3.10 跳过，CI Python 3.11 真跑（沿用 PR #553 / #633 模式）
if sys.version_info < (3, 10):
    pytest.skip(
        "需要 Python 3.10+（生产环境为 3.11）— 本机 3.9 跳过避免 sys.modules 污染",
        allow_module_level=True,
    )

from services.tx_supply.src.services.delivery_window_service import (  # noqa: E402
    _pick_window_for_weekday,
    _time_to_minutes,
    _weekday_bit,
    approve_delivery_window,
    check_delivery_window,
    count_violations,
    create_delivery_window,
    get_delivery_window,
    list_delivery_windows,
    record_violation,
    soft_delete_delivery_window,
)


# ─── 测试常量（徐记海鲜餐厅场景）─────────────────────────────────────────────

_TENANT_XUJI = "11111111-aaaa-aaaa-aaaa-111111111111"
_TENANT_CZYZ = "22222222-bbbb-bbbb-bbbb-222222222222"
_SUPPLIER_FRESH = "aaaaaaaa-0001-0001-0001-aaaaaaaaaaaa"  # 生鲜供应商 — 早班 4-7 点到货
_STORE_HQ = "bbbbbbbb-0002-0002-0002-bbbbbbbbbbbb"
_USER_MGR = "cccccccc-0003-0003-0003-cccccccccccc"  # 店长（创建人）
_USER_DIRECTOR = "dddddddd-0004-0004-0004-dddddddddddd"  # 区域督导（审批人）
_WINDOW_ID = "eeeeeeee-0005-0005-0005-eeeeeeeeeeee"
_ORDER_ID = "ffffffff-0006-0006-0006-ffffffffffff"


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
    """模拟 DB：list_delivery_windows SELECT 路径。"""
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        result = MagicMock()

        if "set_config" in sql:
            return MagicMock()

        if "SELECT" in sql.upper() and "supplier_delivery_windows" in sql:
            result.mappings.return_value.__iter__ = lambda self: iter(rows)
            return result

        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


def _mk_db_for_get(*, row: dict | None) -> AsyncMock:
    """模拟 DB：get_delivery_window 单条 SELECT 路径。"""
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        result = MagicMock()

        if "set_config" in sql:
            return MagicMock()

        if "SELECT" in sql.upper() and "supplier_delivery_windows" in sql:
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

        if "UPDATE supplier_delivery_windows" in sql and "is_deleted = TRUE" in sql:
            result = MagicMock()
            result.rowcount = affected
            return result

        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


def _mk_db_for_count(*, count: int) -> AsyncMock:
    """模拟 DB：COUNT(*) 聚合路径。"""
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        result = MagicMock()

        if "set_config" in sql:
            return MagicMock()

        if "COUNT(*)" in sql and "supplier_delivery_violations" in sql:
            result.mappings.return_value.first.return_value = {"cnt": count}
            return result

        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


def _window_row(
    *,
    approved_by: str | None = _USER_DIRECTOR,
    created_by: str = _USER_MGR,
    weekday_mask: int = 127,
    earliest: time = time(4, 0),
    latest: time = time(7, 0),
    grace: int = 15,
    auto_reject: bool = False,
    window_id: str = _WINDOW_ID,
) -> dict:
    """构造一行 delivery_windows 字典（list / get 通用）。"""
    return {
        "id": window_id,
        "tenant_id": _TENANT_XUJI,
        "supplier_id": _SUPPLIER_FRESH,
        "store_id": _STORE_HQ,
        "weekday_mask": weekday_mask,
        "earliest_time": earliest,
        "latest_time": latest,
        "grace_minutes": grace,
        "auto_reject_on_late": auto_reject,
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
        """创建配送时间窗 → approved_by=NULL（草稿态）。"""
        row = _window_row(approved_by=None)
        db = _mk_db_for_returning(returning_row=row)

        result = await create_delivery_window(
            db=db,
            tenant_id=_TENANT_XUJI,
            supplier_id=_SUPPLIER_FRESH,
            store_id=_STORE_HQ,
            earliest_time=time(4, 0),
            latest_time=time(7, 0),
            created_by=_USER_MGR,
        )
        assert result["approved_by"] is None, "新建必须草稿态"
        assert result["created_by"] == _USER_MGR

        sqls = [str(call.args[0]) for call in db.execute.call_args_list]
        assert any("set_config" in s for s in sqls), "必须设置 RLS 租户上下文"

    @pytest.mark.asyncio
    async def test_list_only_active_filters_drafts_and_deleted(self):
        """list_delivery_windows(only_active=True) 仅返回已审批 + 未删除。"""
        row = _window_row(approved_by=_USER_DIRECTOR)
        db = _mk_db_for_list(rows=[row])

        items = await list_delivery_windows(
            db=db,
            tenant_id=_TENANT_XUJI,
            supplier_id=_SUPPLIER_FRESH,
            only_active=True,
        )
        assert len(items) == 1

        sqls = [str(call.args[0]) for call in db.execute.call_args_list]
        active_sql = next(
            (s for s in sqls if "supplier_delivery_windows" in s), ""
        )
        assert "approved_by IS NOT NULL" in active_sql, "active 过滤 approved_by"
        assert "is_deleted = FALSE" in active_sql, "active 过滤 is_deleted"

    @pytest.mark.asyncio
    async def test_get_no_lock_default(self):
        """get_delivery_window 默认 lock=False（read-only 路径）。"""
        row = _window_row(approved_by=_USER_DIRECTOR)
        db = _mk_db_for_get(row=row)

        result = await get_delivery_window(db, _TENANT_XUJI, _WINDOW_ID)
        assert result is not None
        assert result["id"] == _WINDOW_ID

        sqls = [str(call.args[0]) for call in db.execute.call_args_list]
        select_sql = next(
            (s for s in sqls if "supplier_delivery_windows" in s), ""
        )
        assert "FOR UPDATE" not in select_sql, "默认 lock=False 不应加 FOR UPDATE"

    @pytest.mark.asyncio
    async def test_get_with_lock_adds_for_update(self):
        """get_delivery_window(lock=True) 加 FOR UPDATE（mutation 路径 row-lock pattern）。"""
        row = _window_row(approved_by=None)
        db = _mk_db_for_get(row=row)

        await get_delivery_window(db, _TENANT_XUJI, _WINDOW_ID, lock=True)

        sqls = [str(call.args[0]) for call in db.execute.call_args_list]
        select_sql = next(
            (s for s in sqls if "supplier_delivery_windows" in s), ""
        )
        assert "FOR UPDATE" in select_sql, "lock=True 必须加 FOR UPDATE 行锁（与 PR-A/B 一致）"

    @pytest.mark.asyncio
    async def test_soft_delete_affected_one_returns_true(self):
        """soft_delete 影响 1 行 → 返回 True。"""
        db = _mk_db_for_delete(affected=1)
        deleted = await soft_delete_delivery_window(db, _TENANT_XUJI, _WINDOW_ID)
        assert deleted is True

    @pytest.mark.asyncio
    async def test_soft_delete_zero_rows_returns_false(self):
        """soft_delete 影响 0 行（已删 / 不存在）→ 返回 False。"""
        db = _mk_db_for_delete(affected=0)
        deleted = await soft_delete_delivery_window(db, _TENANT_XUJI, _WINDOW_ID)
        assert deleted is False


# ─── 2. 二级审批 ──────────────────────────────────────────────────────────────


class TestApprove:
    @pytest.mark.asyncio
    async def test_approve_success_by_independent_user(self):
        """approver_id != created_by → 审批成功，approved_by 写入。"""
        existing = _window_row(approved_by=None, created_by=_USER_MGR)
        approved = _window_row(approved_by=_USER_DIRECTOR, created_by=_USER_MGR)

        db = AsyncMock()

        async def execute_side_effect(query, params=None):
            sql = str(query)
            result = MagicMock()
            if "set_config" in sql:
                return MagicMock()
            if "SELECT" in sql.upper() and "supplier_delivery_windows" in sql:
                result.mappings.return_value.first.return_value = existing
                return result
            if "UPDATE supplier_delivery_windows" in sql and "approved_by" in sql:
                result.mappings.return_value.first.return_value = approved
                return result
            return MagicMock()

        db.execute = AsyncMock(side_effect=execute_side_effect)

        result = await approve_delivery_window(
            db=db,
            tenant_id=_TENANT_XUJI,
            window_id=_WINDOW_ID,
            approver_id=_USER_DIRECTOR,
        )
        assert result["approved_by"] == _USER_DIRECTOR
        assert result["created_by"] == _USER_MGR

    @pytest.mark.asyncio
    async def test_self_approve_rejected(self):
        """approver_id == created_by → 拒绝（二级审批必须独立签字）。"""
        existing = _window_row(approved_by=None, created_by=_USER_MGR)

        db = AsyncMock()

        async def execute_side_effect(query, params=None):
            sql = str(query)
            result = MagicMock()
            if "set_config" in sql:
                return MagicMock()
            if "SELECT" in sql.upper() and "supplier_delivery_windows" in sql:
                result.mappings.return_value.first.return_value = existing
                return result
            return MagicMock()

        db.execute = AsyncMock(side_effect=execute_side_effect)

        with pytest.raises(ValueError, match="不能与 created_by 相同"):
            await approve_delivery_window(
                db=db,
                tenant_id=_TENANT_XUJI,
                window_id=_WINDOW_ID,
                approver_id=_USER_MGR,
            )


# ─── 3. RLS ───────────────────────────────────────────────────────────────────


class TestRLS:
    @pytest.mark.asyncio
    async def test_set_tenant_called_on_every_operation(self):
        """每次 service 调用必须先调 set_config('app.tenant_id', ...) — RLS 强制。"""
        db = _mk_db_for_list(rows=[])

        await list_delivery_windows(db, _TENANT_XUJI, _SUPPLIER_FRESH)

        # 验证 set_config 被调用 + tenant_id 参数正确
        set_tenant_calls = [
            call for call in db.execute.call_args_list
            if "set_config" in str(call.args[0])
        ]
        assert len(set_tenant_calls) >= 1, "至少调用一次 set_config"
        # params 是第二个位置参数
        params = set_tenant_calls[0].args[1]
        assert params["tid"] == _TENANT_XUJI, "tenant_id 必须正确传入"


# ─── 4. 时间窗合规性检查 ─────────────────────────────────────────────────────


class TestCheckDeliveryWindow:
    @pytest.mark.asyncio
    async def test_no_config_fail_open(self):
        """无任何配置 → fail-open: within=True, weekday_matched=False（不阻塞收货）。"""
        db = _mk_db_for_list(rows=[])

        result = await check_delivery_window(
            db,
            _TENANT_XUJI,
            supplier_id=_SUPPLIER_FRESH,
            store_id=_STORE_HQ,
            signed_at=datetime(2026, 5, 15, 10, 0, tzinfo=timezone.utc),
        )
        assert result["within_window"] is True
        assert result["weekday_matched"] is False
        assert result["violation_minutes"] == 0
        assert result["violation_kind"] is None

    @pytest.mark.asyncio
    async def test_weekday_mismatch_fail_open(self):
        """配置存在但 weekday_mask 不匹配 → fail-open。"""
        # weekday_mask=1 (仅周一)；signed_at 是周五 (bit 4 = 16)
        row = _window_row(weekday_mask=1)
        db = _mk_db_for_list(rows=[row])

        # 2026-05-15 是周五（weekday()=4 → bit=16）
        result = await check_delivery_window(
            db,
            _TENANT_XUJI,
            supplier_id=_SUPPLIER_FRESH,
            store_id=_STORE_HQ,
            signed_at=datetime(2026, 5, 15, 5, 0, tzinfo=timezone.utc),
        )
        assert result["weekday_matched"] is False
        assert result["within_window"] is True

    @pytest.mark.asyncio
    async def test_within_window_normal(self):
        """正常窗口内 4:00-7:00 grace=15 → signed_at 04:30 → within=True。"""
        row = _window_row(
            earliest=time(4, 0), latest=time(7, 0), grace=15, weekday_mask=127
        )
        db = _mk_db_for_list(rows=[row])

        result = await check_delivery_window(
            db,
            _TENANT_XUJI,
            supplier_id=_SUPPLIER_FRESH,
            store_id=_STORE_HQ,
            signed_at=datetime(2026, 5, 15, 4, 30, tzinfo=timezone.utc),
        )
        assert result["within_window"] is True
        assert result["weekday_matched"] is True
        assert result["violation_minutes"] == 0
        assert result["violation_kind"] is None

    @pytest.mark.asyncio
    async def test_late_violation_after_latest_plus_grace(self):
        """晚到 — 4:00-7:00 grace=15 → signed_at 07:45 → late by 30 分钟。"""
        # latest=420min, grace=15 → late_limit=435min；07:45=465min → late 30min
        row = _window_row(
            earliest=time(4, 0), latest=time(7, 0), grace=15, weekday_mask=127
        )
        db = _mk_db_for_list(rows=[row])

        result = await check_delivery_window(
            db,
            _TENANT_XUJI,
            supplier_id=_SUPPLIER_FRESH,
            store_id=_STORE_HQ,
            signed_at=datetime(2026, 5, 15, 7, 45, tzinfo=timezone.utc),
        )
        assert result["within_window"] is False
        assert result["violation_kind"] == "late"
        assert result["violation_minutes"] == 30

    @pytest.mark.asyncio
    async def test_early_violation_before_earliest_minus_grace(self):
        """早到 — 4:00-7:00 grace=15 → signed_at 03:00 → early by 45 分钟。"""
        # earliest=240min, grace=15 → early_limit=225min；03:00=180min → early 45min
        row = _window_row(
            earliest=time(4, 0), latest=time(7, 0), grace=15, weekday_mask=127
        )
        db = _mk_db_for_list(rows=[row])

        result = await check_delivery_window(
            db,
            _TENANT_XUJI,
            supplier_id=_SUPPLIER_FRESH,
            store_id=_STORE_HQ,
            signed_at=datetime(2026, 5, 15, 3, 0, tzinfo=timezone.utc),
        )
        assert result["within_window"] is False
        assert result["violation_kind"] == "early"
        assert result["violation_minutes"] == 45

    @pytest.mark.asyncio
    async def test_grace_boundary_inclusive(self):
        """容忍边界 — 4:00-7:00 grace=15 → signed_at 07:15 刚好 = latest+grace → within=True。"""
        row = _window_row(
            earliest=time(4, 0), latest=time(7, 0), grace=15, weekday_mask=127
        )
        db = _mk_db_for_list(rows=[row])

        result = await check_delivery_window(
            db,
            _TENANT_XUJI,
            supplier_id=_SUPPLIER_FRESH,
            store_id=_STORE_HQ,
            signed_at=datetime(2026, 5, 15, 7, 15, tzinfo=timezone.utc),
        )
        assert result["within_window"] is True, "边界 latest+grace 应 inclusive 视为合规"
        assert result["violation_minutes"] == 0


# ─── 5. 违约日志写入 ────────────────────────────────────────────────────────


class TestRecordViolation:
    @pytest.mark.asyncio
    async def test_record_returns_dict_on_first_insert(self):
        """首次记录 → INSERT 成功 → RETURNING 返回 dict。"""
        returning = {
            "id": "vvvvvvvv-0007-0007-0007-vvvvvvvvvvvv",
            "tenant_id": _TENANT_XUJI,
            "supplier_id": _SUPPLIER_FRESH,
            "store_id": _STORE_HQ,
            "receiving_order_id": _ORDER_ID,
            "window_id": _WINDOW_ID,
            "scheduled_earliest": time(4, 0),
            "scheduled_latest": time(7, 0),
            "actual_signed_at": datetime(2026, 5, 15, 7, 45, tzinfo=timezone.utc),
            "violation_minutes": 30,
            "violation_kind": "late",
            "recorded_at": datetime(2026, 5, 15, 7, 46, tzinfo=timezone.utc),
        }
        db = _mk_db_for_returning(returning_row=returning)

        result = await record_violation(
            db,
            _TENANT_XUJI,
            supplier_id=_SUPPLIER_FRESH,
            store_id=_STORE_HQ,
            receiving_order_id=_ORDER_ID,
            window_id=_WINDOW_ID,
            scheduled_earliest=time(4, 0),
            scheduled_latest=time(7, 0),
            actual_signed_at=datetime(2026, 5, 15, 7, 45, tzinfo=timezone.utc),
            violation_minutes=30,
            violation_kind="late",
        )
        assert result is not None
        assert result["violation_kind"] == "late"
        assert result["violation_minutes"] == 30

    @pytest.mark.asyncio
    async def test_record_idempotent_returns_none_on_conflict(self):
        """重复记录同 receiving_order_id → ON CONFLICT DO NOTHING → 返回 None。"""
        # RETURNING 路径 returning_row=None 模拟 ON CONFLICT
        db = _mk_db_for_returning(returning_row=None)

        result = await record_violation(
            db,
            _TENANT_XUJI,
            supplier_id=_SUPPLIER_FRESH,
            store_id=_STORE_HQ,
            receiving_order_id=_ORDER_ID,
            window_id=_WINDOW_ID,
            scheduled_earliest=time(4, 0),
            scheduled_latest=time(7, 0),
            actual_signed_at=datetime(2026, 5, 15, 7, 45, tzinfo=timezone.utc),
            violation_minutes=30,
            violation_kind="late",
        )
        assert result is None, "ON CONFLICT 命中应返回 None — supplier_scoring 不双计"

        # 验证 SQL 含 ON CONFLICT 子句
        sqls = [str(call.args[0]) for call in db.execute.call_args_list]
        insert_sql = next(
            (s for s in sqls if "INSERT INTO supplier_delivery_violations" in s), ""
        )
        assert "ON CONFLICT" in insert_sql, "必须 ON CONFLICT DO NOTHING 防双计"


# ─── 6. 违约次数聚合（supplier_scoring 扣分基础）──────────────────────────


class TestCountViolations:
    @pytest.mark.asyncio
    async def test_count_returns_int(self):
        """COUNT(*) 聚合返回 supplier 在 period 内违约次数。"""
        db = _mk_db_for_count(count=7)

        cnt = await count_violations(
            db,
            _TENANT_XUJI,
            _SUPPLIER_FRESH,
            period_start=date(2026, 5, 1),
            period_end=date(2026, 5, 31),
        )
        assert cnt == 7
        assert isinstance(cnt, int)


# ─── 7. 纯函数 helper 单元测试 ────────────────────────────────────────────


class TestHelpers:
    def test_weekday_bit_monday_to_sunday(self):
        """Monday=bit 0=1, ..., Sunday=bit 6=64（与 Python date.weekday() 对齐）。"""
        # 2026-05-11 周一
        assert _weekday_bit(datetime(2026, 5, 11)) == 1
        # 2026-05-15 周五
        assert _weekday_bit(datetime(2026, 5, 15)) == 16
        # 2026-05-17 周日
        assert _weekday_bit(datetime(2026, 5, 17)) == 64

    def test_time_to_minutes(self):
        """TIME → 分钟数。"""
        assert _time_to_minutes(time(0, 0)) == 0
        assert _time_to_minutes(time(4, 0)) == 240
        assert _time_to_minutes(time(7, 30)) == 450
        assert _time_to_minutes(time(23, 59)) == 23 * 60 + 59

    def test_pick_window_for_weekday(self):
        """位匹配挑窗 — list 已按 created_at DESC，取首条匹配。"""
        # weekday_mask=2 (周二) vs weekday_bit=1 (周一) → 不匹配
        w1 = _window_row(weekday_mask=2, window_id="w1")
        w2 = _window_row(weekday_mask=127, window_id="w2")
        assert _pick_window_for_weekday([w1, w2], weekday_bit=1) == w2

        # 多条匹配取首条
        w3 = _window_row(weekday_mask=127, window_id="w3")
        assert _pick_window_for_weekday([w3, w2], weekday_bit=1) == w3

        # 无匹配返回 None
        w4 = _window_row(weekday_mask=2)
        assert _pick_window_for_weekday([w4], weekday_bit=1) is None
