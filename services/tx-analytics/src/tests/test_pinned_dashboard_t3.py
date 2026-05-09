"""Tier 3（RLS 路径全局 Tier 1） — S4-04 PR2.B 驾驶舱 Pin service DB swap 测试

PR2.B 范围：service 层从 in-memory dict 切到 PG (v403 dashboard_pinned)。

本文件用 mock AsyncSession 验证 SQL shape + 调用顺序 + 参数绑定 + 输入校验：
  - add_pin → INSERT ... RETURNING + UPDATE 软删 FIFO 二次 execute
  - list_pins → SELECT ORDER BY pinned_at DESC LIMIT N
  - remove_pin → UPDATE is_deleted=TRUE WHERE pin_id (rowcount > 0 = True)
  - 跨 tenant remove → RLS 阻挡可见性 → rowcount=0 → False（mock 模拟）
  - 输入校验：tenant_id / pinner_user_id / pin_id 必填非空

不在本文件（留 PR2.B-2 真 PG fixture）：
  - FIFO 行为：第 21 条把第 1 条挤掉的真状态校验
  - RLS 跨 tenant 反测：tenant=A pin 不出现在 tenant=B list
  - WITH CHECK 反测：INSERT 时 tenant_id != current_setting → IntegrityError
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from ..services.pinned_dashboard import (
    PIN_LIMIT_PER_TENANT,
    PinnedItem,
    add_pin,
    list_pins,
    remove_pin,
)


TENANT_A = str(uuid.uuid4())
TENANT_B = str(uuid.uuid4())
USER_A1 = str(uuid.uuid4())
USER_B1 = str(uuid.uuid4())

_SAMPLE_SURFACE = {
    "version": "0.8",
    "surface": {
        "id": "card-1",
        "type": "card",
        "props": {"title": "本周营收", "severity": "info"},
        "children": [
            {"id": "t1", "type": "text", "props": {"content": "+12.3%"}},
        ],
    },
}


# ─────────────── helpers ───────────────


def _mock_insert_returning_row(
    *,
    pin_id: str | None = None,
    tenant_id: str = TENANT_A,
    pinner_user_id: str = USER_A1,
    surface: dict | None = None,
) -> MagicMock:
    """构造 INSERT ... RETURNING 的 mock 返回 — mappings().one() 形态。"""
    row = {
        "pin_id": uuid.UUID(pin_id) if pin_id else uuid.uuid4(),
        "tenant_id": uuid.UUID(tenant_id),
        "pinner_user_id": uuid.UUID(pinner_user_id),
        "pinned_at": datetime.now(timezone.utc),
        "surface_snapshot": surface or _SAMPLE_SURFACE,
        "source_query_id": None,
        "source_natural_query": None,
    }
    insert_result = MagicMock()
    insert_result.mappings.return_value.one.return_value = row
    return insert_result


def _mock_session_for_add(insert_row: MagicMock) -> AsyncMock:
    """add_pin 调 2 次 session.execute：INSERT + FIFO UPDATE。"""
    session = AsyncMock()
    update_result = MagicMock(rowcount=0)
    session.execute = AsyncMock(side_effect=[insert_row, update_result])
    return session


def _mock_session_for_list(rows: list[dict]) -> AsyncMock:
    """list_pins 调 1 次 session.execute：SELECT。"""
    session = AsyncMock()
    select_result = MagicMock()
    select_result.mappings.return_value = rows
    session.execute = AsyncMock(return_value=select_result)
    return session


def _mock_session_for_remove(rowcount: int) -> AsyncMock:
    """remove_pin 调 1 次 session.execute：UPDATE，rowcount 决定返回 True/False。"""
    session = AsyncMock()
    update_result = MagicMock(rowcount=rowcount)
    session.execute = AsyncMock(return_value=update_result)
    return session


# ─────────────── 输入校验（防 RLS 绕过） ───────────────


class TestPinValidationT3:
    """tenant_id / pinner_user_id / pin_id 必填非空 — service 层早拒，减少 DB roundtrip。"""

    @pytest.mark.asyncio
    async def test_add_pin_empty_tenant_id_rejected(self):
        session = AsyncMock()
        with pytest.raises(ValueError, match="tenant_id"):
            await add_pin(
                session,
                tenant_id="",
                pinner_user_id=USER_A1,
                surface_snapshot=_SAMPLE_SURFACE,
            )
        session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_pin_empty_pinner_user_id_rejected(self):
        session = AsyncMock()
        with pytest.raises(ValueError, match="pinner_user_id"):
            await add_pin(
                session,
                tenant_id=TENANT_A,
                pinner_user_id="",
                surface_snapshot=_SAMPLE_SURFACE,
            )
        session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_pins_empty_tenant_id_rejected(self):
        session = AsyncMock()
        with pytest.raises(ValueError, match="tenant_id"):
            await list_pins(session, "")
        session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_remove_pin_empty_tenant_id_rejected(self):
        session = AsyncMock()
        with pytest.raises(ValueError, match="tenant_id"):
            await remove_pin(session, tenant_id="", pin_id="any")
        session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_remove_pin_empty_pin_id_rejected(self):
        session = AsyncMock()
        with pytest.raises(ValueError, match="pin_id"):
            await remove_pin(session, tenant_id=TENANT_A, pin_id="")
        session.execute.assert_not_called()


# ─────────────── add_pin SQL shape ───────────────


class TestAddPinSqlShapeT3:
    """add_pin 发出的 SQL 必须含 INSERT ... RETURNING + UPDATE 软删 FIFO。"""

    @pytest.mark.asyncio
    async def test_add_pin_emits_insert_then_fifo_update(self):
        """店长 Pin 一条洞察 → 第 1 次 execute = INSERT ... RETURNING；
        第 2 次 = FIFO 软删 UPDATE。"""
        session = _mock_session_for_add(
            _mock_insert_returning_row(tenant_id=TENANT_A, pinner_user_id=USER_A1)
        )
        await add_pin(
            session,
            tenant_id=TENANT_A,
            pinner_user_id=USER_A1,
            surface_snapshot=_SAMPLE_SURFACE,
        )
        assert session.execute.await_count == 2, (
            "add_pin 必须发出 2 条 SQL（INSERT + FIFO UPDATE）"
        )

        first_sql = str(session.execute.await_args_list[0].args[0])
        assert "INSERT INTO dashboard_pinned" in first_sql
        assert "RETURNING" in first_sql

        second_sql = str(session.execute.await_args_list[1].args[0])
        assert "UPDATE dashboard_pinned" in second_sql
        assert "is_deleted = TRUE" in second_sql
        assert "ORDER BY pinned_at DESC" in second_sql
        assert "LIMIT" in second_sql

    @pytest.mark.asyncio
    async def test_add_pin_insert_binds_tenant_pinner_jsonb(self):
        """INSERT 必须带 tenant_id::uuid + pinner_user_id::uuid + surface::jsonb cast。"""
        session = _mock_session_for_add(_mock_insert_returning_row())
        await add_pin(
            session,
            tenant_id=TENANT_A,
            pinner_user_id=USER_A1,
            surface_snapshot=_SAMPLE_SURFACE,
        )
        first_call = session.execute.await_args_list[0]
        sql = str(first_call.args[0])
        params = first_call.args[1]
        assert ":tenant_id::uuid" in sql
        assert ":pinner_user_id::uuid" in sql
        assert ":surface_snapshot::jsonb" in sql
        assert params["tenant_id"] == TENANT_A
        assert params["pinner_user_id"] == USER_A1
        # surface_snapshot 必须 json.dumps 为字符串再 ::jsonb cast
        assert params["surface_snapshot"] == json.dumps(
            _SAMPLE_SURFACE, ensure_ascii=False
        )

    @pytest.mark.asyncio
    async def test_add_pin_fifo_limit_uses_module_constant(self):
        """FIFO UPDATE 必须用 PIN_LIMIT_PER_TENANT 作 LIMIT 参数（防被偷偷改）。"""
        session = _mock_session_for_add(_mock_insert_returning_row())
        await add_pin(
            session,
            tenant_id=TENANT_A,
            pinner_user_id=USER_A1,
            surface_snapshot=_SAMPLE_SURFACE,
        )
        second_call = session.execute.await_args_list[1]
        params = second_call.args[1]
        assert params["limit"] == PIN_LIMIT_PER_TENANT

    @pytest.mark.asyncio
    async def test_add_pin_returns_pinned_item_from_returning_row(self):
        """RETURNING 行 → PinnedItem dataclass，UUID/datetime 类型转换正确。"""
        pin_id = str(uuid.uuid4())
        insert_row = _mock_insert_returning_row(
            pin_id=pin_id, tenant_id=TENANT_A, pinner_user_id=USER_A1
        )
        session = _mock_session_for_add(insert_row)
        item = await add_pin(
            session,
            tenant_id=TENANT_A,
            pinner_user_id=USER_A1,
            surface_snapshot=_SAMPLE_SURFACE,
        )
        assert isinstance(item, PinnedItem)
        assert item.pin_id == pin_id
        assert item.tenant_id == TENANT_A
        assert item.pinner_user_id == USER_A1
        assert item.surface_snapshot == _SAMPLE_SURFACE
        # to_dict 形态稳定（PR2.C 路由层 / PR2.D 前端依赖）
        assert set(item.to_dict().keys()) == {
            "pin_id",
            "tenant_id",
            "pinner_user_id",
            "pinned_at",
            "surface_snapshot",
            "source_query_id",
            "source_natural_query",
        }


# ─────────────── list_pins SQL shape ───────────────


class TestListPinsSqlShapeT3:
    """list_pins 发出 SELECT，依赖 RLS 自动 tenant 过滤。"""

    @pytest.mark.asyncio
    async def test_list_pins_select_orders_newest_first_with_limit(self):
        session = _mock_session_for_list([])
        await list_pins(session, TENANT_A)
        assert session.execute.await_count == 1
        sql = str(session.execute.await_args.args[0])
        assert "FROM dashboard_pinned" in sql
        assert "WHERE is_deleted = FALSE" in sql
        assert "ORDER BY pinned_at DESC" in sql
        assert "LIMIT" in sql

    @pytest.mark.asyncio
    async def test_list_pins_does_not_filter_tenant_explicitly(self):
        """RLS USING 自动 tenant 过滤 — service 层 SQL 不应再写 :tenant_id bind
        （依赖 set_config('app.tenant_id') 注入，避免 service 层与 session 漂移）。"""
        session = _mock_session_for_list([])
        await list_pins(session, TENANT_A)
        sql = str(session.execute.await_args.args[0])
        assert ":tenant_id" not in sql

    @pytest.mark.asyncio
    async def test_list_pins_maps_rows_to_pinned_items(self):
        rows = [
            {
                "pin_id": uuid.uuid4(),
                "tenant_id": uuid.UUID(TENANT_A),
                "pinner_user_id": uuid.UUID(USER_A1),
                "pinned_at": datetime.now(timezone.utc),
                "surface_snapshot": {"v": i},
                "source_query_id": None,
                "source_natural_query": None,
            }
            for i in range(3)
        ]
        session = _mock_session_for_list(rows)
        pins = await list_pins(session, TENANT_A)
        assert len(pins) == 3
        assert all(isinstance(p, PinnedItem) for p in pins)
        assert [p.surface_snapshot["v"] for p in pins] == [0, 1, 2]


# ─────────────── remove_pin SQL shape ───────────────


class TestRemovePinSqlShapeT3:
    """remove_pin 发出 UPDATE 软删，rowcount 决定返回 True/False。"""

    @pytest.mark.asyncio
    async def test_remove_pin_emits_soft_delete_update(self):
        session = _mock_session_for_remove(rowcount=1)
        ok = await remove_pin(session, tenant_id=TENANT_A, pin_id=str(uuid.uuid4()))
        assert ok is True
        sql = str(session.execute.await_args.args[0])
        assert "UPDATE dashboard_pinned" in sql
        assert "is_deleted = TRUE" in sql
        assert ":pin_id::uuid" in sql
        # 已软删的行不应被重复 update（is_deleted=FALSE 守门）
        assert "AND is_deleted = FALSE" in sql

    @pytest.mark.asyncio
    async def test_remove_pin_returns_false_on_rowcount_zero(self):
        """跨 tenant remove：RLS USING 阻挡可见性 → rowcount=0 → False，不抛异常。
        重复 remove 已软删行：rowcount=0 → False（幂等）。"""
        session = _mock_session_for_remove(rowcount=0)
        ok = await remove_pin(session, tenant_id=TENANT_A, pin_id=str(uuid.uuid4()))
        assert ok is False

    @pytest.mark.asyncio
    async def test_remove_pin_handles_none_rowcount(self):
        """某些 driver 在 UPDATE 0 行时返回 rowcount=None — 必须 fallback 到 False。"""
        session = AsyncMock()
        update_result = MagicMock(rowcount=None)
        session.execute = AsyncMock(return_value=update_result)
        ok = await remove_pin(session, tenant_id=TENANT_A, pin_id=str(uuid.uuid4()))
        assert ok is False
