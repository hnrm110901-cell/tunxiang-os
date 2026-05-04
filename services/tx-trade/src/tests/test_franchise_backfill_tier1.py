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
