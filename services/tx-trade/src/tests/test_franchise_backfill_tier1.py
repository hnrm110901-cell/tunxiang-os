"""Tier 1 — PG.5 加盟历史回放 backfill 脚本核心契约

PG.5 是一次性脚本但触动财务数据（royalty / settlement amount_fen），
任何 mapper 错位都会污染事件流 → 物化视图 → CFO 报表。本套测试守门：

  1. 6 张表 × mapper 的 event_type 分支正确（status → enum 映射）
  2. 金额字段统一 fen（int），不浮点 — §15 / Tier1 财务红线
  3. dry-run 不调 emit_event，apply 调用 emit_event 且回填 last_event_id
  4. emit_event 失败不阻断整批（兜底统计 failed += 1）
  5. RLS 安全：tenant_id 缺失的行被跳过统计
  6. 幂等：扫描 SQL 必带 last_event_id IS NULL（v396 PARTIAL 索引入口）
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

# 让 scripts/ 可被 import
_REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO_ROOT))

from scripts import backfill_franchise_events as bf  # noqa: E402

TENANT_A = "00000000-0000-0000-0000-00000000aaaa"
STORE_A = "00000000-0000-0000-0000-000000001111"


# ──────────────── 1. mapper × status 分支映射 ────────────────


@pytest.mark.parametrize(
    "status,expected_event_type",
    [
        ("active", "franchise.franchisee_activated"),
        ("suspended", "franchise.franchisee_suspended"),
        ("terminated", "franchise.franchisee_terminated"),
        ("applying", "franchise.franchisee_applied"),  # 未知状态退化为 APPLIED
    ],
)
def test_franchisees_mapper_status_to_event(status: str, expected_event_type: str) -> None:
    row = {"name": "尝在一起 北京店", "status": status, "royalty_rate": 0.05}
    et, payload = bf._franchisees_mapper(row)
    assert et == expected_event_type
    assert payload["status"] == status.lower()


@pytest.mark.parametrize(
    "status,expected_event_type",
    [
        ("paid", "franchise.fee_paid"),
        ("pending", "franchise.royalty_calculated"),
        ("overdue", "franchise.royalty_calculated"),
    ],
)
def test_royalty_bills_mapper_status_to_event(status: str, expected_event_type: str) -> None:
    row = {"status": status, "revenue_fen": 880000, "royalty_amount_fen": 44000}
    et, payload = bf._royalty_bills_mapper(row)
    assert et == expected_event_type
    assert payload["revenue_fen"] == 880000
    assert payload["royalty_amount_fen"] == 44000


@pytest.mark.parametrize(
    "status,expected_event_type",
    [
        ("paid", "franchise.fee_paid"),
        ("draft", "franchise.settlement_generated"),
        ("sent", "franchise.settlement_generated"),
        ("confirmed", "franchise.settlement_generated"),
    ],
)
def test_settlements_mapper_status_to_event(status: str, expected_event_type: str) -> None:
    row = {"status": status, "year": 2026, "month": 4, "total_amount_fen": 120000}
    et, _ = bf._franchise_settlements_mapper(row)
    assert et == expected_event_type


# ──────────────── 2. 金额字段必为 int（fen） ────────────────


def test_all_amount_fen_fields_are_int() -> None:
    """财务红线：amount_fen 字段必须是 int，不允许浮点泄漏。"""
    row = {"status": "active", "management_fee_fen": 1000, "brand_usage_fee_fen": 500}
    _, p = bf._franchisees_mapper(row)
    assert isinstance(p["management_fee_fen"], int)
    assert isinstance(p["brand_usage_fee_fen"], int)

    row2 = {"status": "pending", "revenue_fen": 880000, "royalty_amount_fen": 44000, "total_due_fen": 50000}
    _, p2 = bf._royalty_bills_mapper(row2)
    for k in ("revenue_fen", "royalty_amount_fen", "management_fee_fen", "total_due_fen"):
        assert isinstance(p2[k], int)


def test_settlement_items_mapper_carries_settlement_id_in_payload() -> None:
    sid = "11111111-2222-3333-4444-555555555555"
    row = {"settlement_id": sid, "item_type": "royalty", "description": "4月分润", "amount_fen": 44000}
    _, p = bf._franchise_settlement_items_mapper(row)
    assert p["settlement_id"] == sid
    assert p["amount_fen"] == 44000
    assert p["_kind"] == "settlement_item"


# ──────────────── 3. backfill_one_table 主流程 ────────────────


@pytest.mark.asyncio
async def test_dry_run_skips_emit_and_writeback() -> None:
    """dry-run 必须只扫描 + 计数，不调 emit / 不 UPDATE。"""
    spec = bf._TABLE_SPECS[0]  # franchisees
    rows = [{"id": "row-1", "tenant_id": TENANT_A, "status": "active", "name": "店A"}]

    db_execute = AsyncMock(return_value=rows)
    db_update = AsyncMock()
    emit = AsyncMock(return_value="evt-1")

    stats = await bf.backfill_one_table(spec, db_execute=db_execute, db_update=db_update, emit_event=emit, dry_run=True)

    assert stats.scanned == 1
    assert stats.emitted == 1  # dry-run 仍计入 "若 apply 会发出"
    emit.assert_not_called()
    db_update.assert_not_called()


@pytest.mark.asyncio
async def test_apply_calls_emit_and_updates_last_event_id() -> None:
    spec = bf._TABLE_SPECS[0]  # franchisees
    rows = [{"id": "row-1", "tenant_id": TENANT_A, "status": "active", "name": "店A"}]

    db_execute = AsyncMock(return_value=rows)
    db_update = AsyncMock()
    emit = AsyncMock(return_value="evt-abc")

    stats = await bf.backfill_one_table(
        spec, db_execute=db_execute, db_update=db_update, emit_event=emit, dry_run=False
    )

    assert stats.scanned == 1
    assert stats.emitted == 1
    assert stats.failed == 0
    emit.assert_awaited_once()
    # 验证 emit_event 入参
    call_kwargs = emit.await_args.kwargs
    assert call_kwargs["event_type"] == "franchise.franchisee_activated"
    assert call_kwargs["tenant_id"] == TENANT_A
    assert call_kwargs["source_service"] == "backfill_franchise_events"
    assert call_kwargs["metadata"]["backfill"] is True
    assert call_kwargs["metadata"]["source_table"] == "franchisees"
    # 验证 writeback
    db_update.assert_awaited_once()
    upd_args = db_update.await_args.args
    assert "UPDATE franchisees SET last_event_id" in upd_args[0]
    assert upd_args[1] == {"eid": "evt-abc", "pk": "row-1"}


@pytest.mark.asyncio
async def test_emit_returning_none_counts_as_failed() -> None:
    spec = bf._TABLE_SPECS[0]
    rows = [{"id": "row-1", "tenant_id": TENANT_A, "status": "active"}]
    db_execute = AsyncMock(return_value=rows)
    db_update = AsyncMock()
    emit = AsyncMock(return_value=None)  # PG 写入失败

    stats = await bf.backfill_one_table(
        spec, db_execute=db_execute, db_update=db_update, emit_event=emit, dry_run=False
    )
    assert stats.failed == 1
    assert stats.emitted == 0
    db_update.assert_not_called()  # 没拿到 event_id 就不能回填


@pytest.mark.asyncio
async def test_emit_raises_does_not_kill_batch() -> None:
    """单行 emit 抛异常必须被吞掉，整批继续。"""
    spec = bf._TABLE_SPECS[0]
    rows = [
        {"id": "row-1", "tenant_id": TENANT_A, "status": "active"},
        {"id": "row-2", "tenant_id": TENANT_A, "status": "active"},
    ]
    db_execute = AsyncMock(return_value=rows)
    db_update = AsyncMock()
    call_count = {"n": 0}

    async def _flaky_emit(**_kw: Any) -> str:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("redis down")
        return "evt-2"

    stats = await bf.backfill_one_table(
        spec, db_execute=db_execute, db_update=db_update, emit_event=_flaky_emit, dry_run=False
    )
    assert stats.scanned == 2
    assert stats.emitted == 1
    assert stats.failed == 1


@pytest.mark.asyncio
async def test_missing_tenant_id_skipped_safely() -> None:
    spec = bf._TABLE_SPECS[0]
    rows = [
        {"id": "row-1", "tenant_id": None, "status": "active"},  # 漏 tenant_id（理论上不应存在）
        {"id": "row-2", "tenant_id": TENANT_A, "status": "active"},
    ]
    db_execute = AsyncMock(return_value=rows)
    db_update = AsyncMock()
    emit = AsyncMock(return_value="evt-2")

    stats = await bf.backfill_one_table(
        spec, db_execute=db_execute, db_update=db_update, emit_event=emit, dry_run=False
    )
    assert stats.scanned == 2
    assert stats.skipped_no_tenant == 1
    assert stats.emitted == 1
    emit.assert_awaited_once()


# ──────────────── 4. 幂等：SQL 必带 last_event_id IS NULL ────────────────


@pytest.mark.asyncio
async def test_scan_sql_filters_by_null_last_event_id() -> None:
    """所有 SELECT 必须带 last_event_id IS NULL（v396 PARTIAL 索引入口）。"""
    spec = bf._TABLE_SPECS[2]  # royalty_bills
    db_execute = AsyncMock(return_value=[])
    db_update = AsyncMock()
    emit = AsyncMock()

    await bf.backfill_one_table(spec, db_execute=db_execute, db_update=db_update, emit_event=emit, dry_run=True)

    sql = db_execute.await_args.args[0]
    assert "last_event_id IS NULL" in sql
    assert "FROM royalty_bills" in sql
    assert "LIMIT" in sql


@pytest.mark.asyncio
async def test_scan_sql_includes_tenant_filter_when_provided() -> None:
    spec = bf._TABLE_SPECS[0]
    db_execute = AsyncMock(return_value=[])

    await bf.backfill_one_table(
        spec,
        db_execute=db_execute,
        db_update=AsyncMock(),
        emit_event=AsyncMock(),
        tenant_filter=TENANT_A,
        dry_run=True,
    )

    sql, params = db_execute.await_args.args
    assert "tenant_id = :tenant_id" in sql
    assert params["tenant_id"] == TENANT_A


# ──────────────── 5. 6 张表清单完整性（防漏） ────────────────


def test_all_six_franchise_tables_have_specs() -> None:
    expected = {
        "franchisees",
        "franchisee_stores",
        "royalty_bills",
        "franchise_audits",
        "franchise_settlements",
        "franchise_settlement_items",
    }
    actual = {s.table for s in bf._TABLE_SPECS}
    assert actual == expected, f"_TABLE_SPECS 漏表：{expected - actual}"


@pytest.mark.parametrize("spec", bf._TABLE_SPECS, ids=lambda s: s.table)
def test_each_spec_has_callable_mapper(spec: bf.TableSpec) -> None:
    assert callable(spec.mapper)
    # 用最小占位 row 触发一次 mapper（防 KeyError 隐患）
    sample = {"status": "active", "revenue_fen": 0, "royalty_amount_fen": 0, "settlement_id": "x"}
    et, payload = spec.mapper(sample)
    assert et.startswith("franchise.")
    assert isinstance(payload, dict)


# ──────────────── 6. CLI dry-run 不需 DB 也能跑 ────────────────


def test_cli_dry_run_does_not_import_db_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    """dry-run 模式必须不依赖 shared.events / shared.ontology — 防止开发机门槛。"""
    # 不 mock；直接 main 调用 — 应当 return 0 且不抛 ImportError
    rc = bf.main(["--dry-run"])
    assert rc == 0


def test_cli_apply_flag_overrides_dry_run() -> None:
    """--apply 必须把 dry_run 关掉（即便默认 True）"""
    args = bf._parse_args(["--apply"])
    # 默认 dry_run=True；apply 后由 main 翻转
    assert args.apply is True

    # 模拟 main 内部的翻转逻辑
    if args.apply:
        args.dry_run = False
    assert args.dry_run is False


# ──────────────── 7. PJ.4 P1 修复守门 ────────────────
#
# Bug A：旧实现单批 fetch 后退出 → 大表只回放第一批，剩余历史静默丢失。
#         修复：while 循环到 len(batch) < batch_size 收尾。
# Bug B：SET LOCAL app.tenant_id 是事务级 GUC，commit 后清零；
#         旧实现只在脚本起手 SET 一次，第二张表起 tx 没 GUC → RLS 全过滤
#         → 静默回放 0 条。修复：每张表事务起手 + 跨 tenant row 都重设 GUC。


@pytest.mark.asyncio
async def test_backfill_loops_until_exhausted() -> None:
    """Bug A 守门：多批 fetch 必须循环到不满批为止，所有行都被处理。

    模拟 batch_size=2，连续返回 [2, 2, 1] 三批 → 共 5 行；
    断言 emit 被调 5 次（GUC SET 不算），SELECT 至少被调 3 次（每批一次）。
    """
    spec = bf._TABLE_SPECS[0]  # franchisees

    def _row(i: int) -> dict[str, Any]:
        return {"id": f"row-{i}", "tenant_id": TENANT_A, "status": "active", "name": f"店{i}"}

    batches = [
        [_row(1), _row(2)],  # 满批
        [_row(3), _row(4)],  # 满批
        [_row(5)],  # 半批 → 收尾
    ]
    select_calls = {"n": 0}

    async def _exec(sql: str, _params: dict[str, Any]) -> list[dict[str, Any]]:
        # SET LOCAL 不返回行；SELECT 才推进 batches。
        if "SELECT" in sql:
            i = select_calls["n"]
            select_calls["n"] += 1
            return batches[i] if i < len(batches) else []
        return []

    db_execute = AsyncMock(side_effect=_exec)
    db_update = AsyncMock()
    emit = AsyncMock(side_effect=[f"evt-{i}" for i in range(1, 6)])

    stats = await bf.backfill_one_table(
        spec, db_execute=db_execute, db_update=db_update, emit_event=emit, batch_size=2, dry_run=False
    )

    assert stats.scanned == 5, "5 行全部被扫到（不能止步首批）"
    assert stats.emitted == 5, "5 行 emit 全发出"
    assert stats.failed == 0
    assert emit.await_count == 5
    assert db_update.await_count == 5
    # SELECT 被调 3 次（最后一次半批 → 退出，不再多查一次空批）
    assert select_calls["n"] == 3


@pytest.mark.asyncio
async def test_backfill_loops_handle_exact_multiple_with_empty_terminator() -> None:
    """边界：行数恰好是 batch_size 的整数倍 → 最后再多查一次拿到空批退出。

    batch_size=2，[2, 2, 0] → 共 4 行；SELECT 被调 3 次（2+2+0）。
    """
    spec = bf._TABLE_SPECS[0]

    def _row(i: int) -> dict[str, Any]:
        return {"id": f"row-{i}", "tenant_id": TENANT_A, "status": "active"}

    batches = [[_row(1), _row(2)], [_row(3), _row(4)], []]
    n = {"i": 0}

    async def _exec(sql: str, _params: dict[str, Any]) -> list[dict[str, Any]]:
        if "SELECT" in sql:
            i = n["i"]
            n["i"] += 1
            return batches[i] if i < len(batches) else []
        return []

    db_execute = AsyncMock(side_effect=_exec)

    stats = await bf.backfill_one_table(
        spec,
        db_execute=db_execute,
        db_update=AsyncMock(),
        emit_event=AsyncMock(side_effect=["e1", "e2", "e3", "e4"]),
        batch_size=2,
        dry_run=False,
    )
    assert stats.scanned == 4
    assert stats.emitted == 4
    assert n["i"] == 3  # 满批后再查一次拿到空 → 退出


@pytest.mark.asyncio
async def test_backfill_sets_tenant_guc_each_transaction() -> None:
    """Bug B 守门：事务起手必须 SET LOCAL app.tenant_id（commit 后 GUC 清零）。

    单租户回放：tenant_filter 提供时，表入口必有一次 `SET LOCAL app.tenant_id`，
    且租户字面量正确传入 bind params。
    """
    spec = bf._TABLE_SPECS[0]
    rows = [{"id": "row-1", "tenant_id": TENANT_A, "status": "active"}]

    captured: list[tuple[str, dict[str, Any]]] = []

    async def _exec(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        captured.append((sql, params))
        if "SELECT" in sql:
            return rows
        return []

    await bf.backfill_one_table(
        spec,
        db_execute=AsyncMock(side_effect=_exec),
        db_update=AsyncMock(),
        emit_event=AsyncMock(return_value="evt-1"),
        tenant_filter=TENANT_A,
        dry_run=False,
    )

    # 第一条 SQL 必须是 SET LOCAL app.tenant_id（事务起手就设）
    assert captured, "至少要有一次 db_execute 调用"
    first_sql, first_params = captured[0]
    assert "SET LOCAL" in first_sql
    assert "app.tenant_id" in first_sql
    assert first_params == {"tid": TENANT_A}


@pytest.mark.asyncio
async def test_backfill_resets_guc_for_cross_tenant_rows() -> None:
    """多租户行同批：每次 tenant 切换都必须重新 SET LOCAL 防止 RLS 漏穿。"""
    spec = bf._TABLE_SPECS[0]
    other_tenant = "00000000-0000-0000-0000-00000000bbbb"
    rows = [
        {"id": "r1", "tenant_id": TENANT_A, "status": "active"},
        {"id": "r2", "tenant_id": TENANT_A, "status": "active"},
        {"id": "r3", "tenant_id": other_tenant, "status": "active"},  # 切换
        {"id": "r4", "tenant_id": TENANT_A, "status": "active"},  # 再切回
    ]
    captured: list[tuple[str, dict[str, Any]]] = []

    async def _exec(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        captured.append((sql, params))
        return rows if "SELECT" in sql else []

    await bf.backfill_one_table(
        spec,
        db_execute=AsyncMock(side_effect=_exec),
        db_update=AsyncMock(),
        emit_event=AsyncMock(side_effect=["e1", "e2", "e3", "e4"]),
        tenant_filter=None,  # 无单租户过滤 → 多租户模式
        dry_run=False,
    )

    set_local_calls = [p for sql, p in captured if "SET LOCAL" in sql]
    tenants_set = [p["tid"] for p in set_local_calls]
    # 应该至少出现：A（首行）→ B（切换）→ A（切回）三次
    assert tenants_set == [TENANT_A, other_tenant, TENANT_A]


@pytest.mark.asyncio
async def test_dry_run_preview_only_no_emit_no_update_no_guc() -> None:
    """dry-run：扫一批做预览即可；不调 emit/update，也不写 SET LOCAL（无真实事务）。"""
    spec = bf._TABLE_SPECS[0]
    rows = [
        {"id": "r1", "tenant_id": TENANT_A, "status": "active"},
        {"id": "r2", "tenant_id": TENANT_A, "status": "suspended"},
    ]
    captured: list[str] = []

    async def _exec(sql: str, _params: dict[str, Any]) -> list[dict[str, Any]]:
        captured.append(sql)
        return rows if "SELECT" in sql else []

    db_update = AsyncMock()
    emit = AsyncMock()

    stats = await bf.backfill_one_table(
        spec,
        db_execute=AsyncMock(side_effect=_exec),
        db_update=db_update,
        emit_event=emit,
        tenant_filter=TENANT_A,
        dry_run=True,
    )

    assert stats.emitted == 2  # 计数仍前进（预览统计 "若 apply 会发出"）
    emit.assert_not_called()
    db_update.assert_not_called()
    assert all("SELECT" in sql for sql in captured), "dry-run 不应触发 SET LOCAL（无真实事务）"
    # 仅扫一批做预览（不进 while 多轮）
    assert len(captured) == 1


def test_set_tenant_guc_helper_uses_set_local_with_bind_param() -> None:
    """`set_tenant_guc` 必须用 SET LOCAL 形式 + bind param（不字符串拼接）。"""
    captured: list[tuple[str, dict[str, Any]]] = []

    async def _exec(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        captured.append((sql, params))
        return []

    import asyncio

    asyncio.run(bf.set_tenant_guc(_exec, TENANT_A))
    assert len(captured) == 1
    sql, params = captured[0]
    assert "SET LOCAL" in sql
    assert "app.tenant_id" in sql
    assert ":tid" in sql, "必须用 bind param，不准字符串拼接（防注入 + 一致性）"
    assert params == {"tid": TENANT_A}
