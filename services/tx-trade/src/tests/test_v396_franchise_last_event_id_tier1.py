"""Tier 1 — v396 加盟表 last_event_id 字段 + 索引静态校验

PG.6 — 配合 PB.3（加盟接入事件总线）落地；为 PG.5 加盟历史回放 backfill
准备字段（events.event_id 回填到行）。

v396 必须满足：
  1. revision = "v396"，down_revision = "v395"
  2. 6 张加盟表全部 ADD COLUMN IF NOT EXISTS last_event_id UUID
  3. 每张表两个索引：
     - idx_<table>_last_event           — (tenant_id, last_event_id) 反查
     - idx_<table>_last_event_null      — PARTIAL WHERE last_event_id IS NULL
       （PG.5 backfill 入口）
  4. downgrade 反向（DROP INDEX → DROP COLUMN）

测试模式：把 alembic.op.execute 替换为捕获器，import 后调用 upgrade/downgrade，
反查实际渲染的 SQL — 既验证模板正确，又验证 _FRANCHISE_TABLES 完整。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_MIGRATION_PATH = _REPO_ROOT / "shared" / "db-migrations" / "versions" / "v396_franchise_last_event_id.py"

EXPECTED_TABLES = (
    "franchisees",
    "franchisee_stores",
    "royalty_bills",
    "franchise_audits",
    "franchise_settlements",
    "franchise_settlement_items",
)


@pytest.fixture(scope="module")
def migration_src() -> str:
    assert _MIGRATION_PATH.is_file(), f"v396 迁移文件不存在：{_MIGRATION_PATH}"
    return _MIGRATION_PATH.read_text(encoding="utf-8")


@pytest.fixture
def captured_sql() -> dict[str, list[str]]:
    """import 迁移模块、用 mock 替换 op.execute，调 upgrade/downgrade，捕获渲染的 SQL。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location("v396_module", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    captured: dict[str, list[str]] = {"upgrade": [], "downgrade": []}

    op_mock = MagicMock()
    with patch.dict("sys.modules", {"alembic": MagicMock(op=op_mock)}):
        spec.loader.exec_module(module)

    def _capture(target: str) -> Any:
        def _fn(sql: str, *_a, **_kw) -> None:
            captured[target].append(str(sql))

        return _fn

    op_mock.execute.side_effect = _capture("upgrade")
    module.upgrade()
    op_mock.execute.side_effect = _capture("downgrade")
    module.downgrade()

    return captured


# ──────────────── 1. revision/down_revision 衔接 ────────────────


def test_revision_is_v396(migration_src: str) -> None:
    assert 'revision: str = "v396"' in migration_src


def test_down_revision_chains_to_v395(migration_src: str) -> None:
    assert 'down_revision: Union[str, None] = "v395"' in migration_src


# ──────────────── 2. 6 张表全部加列 ────────────────


@pytest.mark.parametrize("table", EXPECTED_TABLES)
def test_each_franchise_table_adds_last_event_id(table: str, captured_sql: dict[str, list[str]]) -> None:
    expected = f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS last_event_id UUID"
    assert any(expected in sql for sql in captured_sql["upgrade"]), f"{table} 未加 last_event_id 列"


# ──────────────── 3. 6 张表 × 2 个索引 ────────────────


@pytest.mark.parametrize("table", EXPECTED_TABLES)
def test_each_table_has_compound_index(table: str, captured_sql: dict[str, list[str]]) -> None:
    """主索引：(tenant_id, last_event_id) — 反查事件归属

    PJ.2 改 CONCURRENTLY 后，单条 SQL 字面量被 PEP8 拆成多行 f-string 拼接，
    captured_sql 收到的是已合并的完整字符串。这里用 substring 检查同时
    覆盖 CONCURRENTLY 与非 CONCURRENTLY 写法（向前兼容）。
    """
    head = f"CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_{table}_last_event"
    tail = f"ON {table} (tenant_id, last_event_id)"
    assert any(head in sql and tail in sql for sql in captured_sql["upgrade"]), (
        f"{table} 缺 CONCURRENTLY 主索引（PJ.2 生产零阻塞要求）"
    )


@pytest.mark.parametrize("table", EXPECTED_TABLES)
def test_each_table_has_partial_null_index(table: str, captured_sql: dict[str, list[str]]) -> None:
    """PARTIAL 索引：定位未纳入事件流的旧行 — PG.5 backfill 入口"""
    head = f"CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_{table}_last_event_null"
    tail = f"ON {table} (tenant_id) WHERE last_event_id IS NULL"
    assert any(head in sql and tail in sql for sql in captured_sql["upgrade"]), (
        f"{table} 缺 CONCURRENTLY PARTIAL NULL 索引（PJ.2 生产零阻塞要求）"
    )


# ──────────────── 4. downgrade 完整反向 ────────────────


@pytest.mark.parametrize("table", EXPECTED_TABLES)
def test_downgrade_drops_column(table: str, captured_sql: dict[str, list[str]]) -> None:
    expected = f"ALTER TABLE {table} DROP COLUMN IF EXISTS last_event_id"
    assert any(expected in sql for sql in captured_sql["downgrade"]), f"{table} downgrade 未 DROP 列"


@pytest.mark.parametrize("table", EXPECTED_TABLES)
def test_downgrade_drops_both_indexes(table: str, captured_sql: dict[str, list[str]]) -> None:
    null_idx = f"DROP INDEX CONCURRENTLY IF EXISTS idx_{table}_last_event_null"
    main_idx = f"DROP INDEX CONCURRENTLY IF EXISTS idx_{table}_last_event"
    assert any(null_idx in sql for sql in captured_sql["downgrade"]), f"{table} downgrade 未 DROP NULL 索引"
    assert any(main_idx in sql for sql in captured_sql["downgrade"]), f"{table} downgrade 未 DROP 主索引"


# ──────────────── 5. 加盟表清单完整性（防止漏加） ────────────────


def test_franchise_tables_tuple_matches_expected(migration_src: str) -> None:
    """v396 的 _FRANCHISE_TABLES 必须与本测试 EXPECTED_TABLES 一一对应。"""
    for table in EXPECTED_TABLES:
        assert f'"{table}"' in migration_src, f"_FRANCHISE_TABLES 漏 {table}"


def test_no_unintended_table_modifications(captured_sql: dict[str, list[str]]) -> None:
    """防漂移：除 6 张加盟表外不应触碰其他表。"""
    import re

    for stmt in captured_sql["upgrade"] + captured_sql["downgrade"]:
        for tbl in re.findall(r"ALTER TABLE (\w+)", stmt):
            assert tbl in EXPECTED_TABLES, f"v396 误改非加盟表：{tbl}"


# ──────────────── 6. 操作总数对账（6 表 × 3 op = 18 upgrade / 18 downgrade） ────────────────


def test_upgrade_emits_18_statements(captured_sql: dict[str, list[str]]) -> None:
    """6 张表 × （1 ADD COLUMN + 2 CREATE INDEX）= 18 个 DDL"""
    assert len(captured_sql["upgrade"]) == 18, f"upgrade 应有 18 条 SQL，实际 {len(captured_sql['upgrade'])}"


def test_downgrade_emits_18_statements(captured_sql: dict[str, list[str]]) -> None:
    """6 张表 × （2 DROP INDEX + 1 DROP COLUMN）= 18 个 DDL"""
    assert len(captured_sql["downgrade"]) == 18, f"downgrade 应有 18 条 SQL，实际 {len(captured_sql['downgrade'])}"
