"""Tier 1 — PG.6 v396 索引必须 CREATE INDEX CONCURRENTLY 防退化（PJ.2）

CodeRabbit 在 PG.6 (v396 加盟表 last_event_id 列 + 索引) 发现：
  默认 `CREATE INDEX` 持有 ACCESS EXCLUSIVE 锁，阻塞目标表所有 INSERT/UPDATE/DELETE，
  导致生产部署期间加盟相关 API（franchisees/royalty_bills/franchise_audits 等）全停。

修复策略：
  - 所有 CREATE INDEX → CREATE INDEX CONCURRENTLY IF NOT EXISTS（不阻塞写入）
  - downgrade DROP INDEX → DROP INDEX CONCURRENTLY IF EXISTS
  - 索引语句必须放在 op.get_context().autocommit_block() 内
    （PostgreSQL 限制：CREATE INDEX CONCURRENTLY 不能在事务内执行）
  - IF NOT EXISTS / IF EXISTS 让 alembic 重跑保持幂等

本测试纯 source-level grep，不依赖 DB / alembic 运行环境，
任何回归（重新引入阻塞索引、忘记 autocommit_block）即时 fail。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_V396_PATH = _REPO_ROOT / "shared/db-migrations/versions/v396_franchise_last_event_id.py"


def _read_v396() -> str:
    assert _V396_PATH.exists(), f"v396 migration 不存在：{_V396_PATH}"
    return _V396_PATH.read_text(encoding="utf-8")


def _strip_comments_and_docstring(text: str) -> str:
    """移除模块 docstring 与行注释，避免误伤文档/注释里的 'CREATE INDEX' 字样。"""
    # 移除三引号 docstring（贪婪匹配模块顶部第一段三引号块就够）
    text = re.sub(r'"""[\s\S]*?"""', "", text, count=1)
    # 移除每行 # 之后的内容
    cleaned_lines: list[str] = []
    for line in text.splitlines():
        # 找到首个不在字符串内的 # — 简化处理：只剥离行首到 # 之间无 ' " 的注释
        if "#" in line:
            # 当前行只要不含成对引号包住 #，直接从 # 截断
            if line.count('"') % 2 == 0 and line.count("'") % 2 == 0:
                line = line.split("#", 1)[0]
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


# ──────────────── 守门 1：所有 CREATE INDEX 必须带 CONCURRENTLY + IF NOT EXISTS ────────────────


def test_v396_all_create_index_use_concurrently() -> None:
    """v396 必须出现至少一处 CREATE INDEX CONCURRENTLY IF NOT EXISTS。"""
    text = _read_v396()
    assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS" in text, (
        "v396 必须使用 CREATE INDEX CONCURRENTLY IF NOT EXISTS — "
        "默认 CREATE INDEX 持 ACCESS EXCLUSIVE 锁会阻塞加盟表写入。"
    )


def test_v396_no_blocking_create_index() -> None:
    """v396 不允许出现裸 CREATE INDEX（必须 CONCURRENTLY）。注释/docstring 已剥离。"""
    code = _strip_comments_and_docstring(_read_v396())
    # 匹配 CREATE INDEX 后面紧跟非 CONCURRENTLY 的形式（允许 IF NOT EXISTS 在前在后无所谓）
    pattern = re.compile(r"CREATE\s+INDEX\s+(?!CONCURRENTLY\b)", re.IGNORECASE)
    matches = [m.group(0) for m in pattern.finditer(code)]
    assert not matches, (
        f"v396 仍存在阻塞型 CREATE INDEX（未带 CONCURRENTLY）：{matches}\n"
        "生产部署期间会阻塞加盟相关 API 写入。"
    )


# ──────────────── 守门 2：CONCURRENTLY 必须配合 autocommit_block ────────────────


def test_v396_uses_autocommit_block() -> None:
    """CREATE INDEX CONCURRENTLY 不能在事务内执行 → 必须用 autocommit_block。"""
    text = _read_v396()
    assert "autocommit_block" in text, (
        "v396 使用了 CREATE INDEX CONCURRENTLY，必须放在 "
        "with op.get_context().autocommit_block(): 块内 — "
        "否则 PostgreSQL 会报 ‘CREATE INDEX CONCURRENTLY cannot run inside a transaction block’。"
    )


# ──────────────── 守门 3：downgrade DROP INDEX 必须 CONCURRENTLY + IF EXISTS ────────────────


def test_v396_downgrade_drop_index_concurrently() -> None:
    """downgrade 也必须用 DROP INDEX CONCURRENTLY IF EXISTS 保持对称且不阻塞。"""
    text = _read_v396()
    assert "DROP INDEX CONCURRENTLY IF EXISTS" in text, (
        "v396 downgrade() 必须使用 DROP INDEX CONCURRENTLY IF EXISTS — "
        "回滚时同样不应阻塞加盟表写入。"
    )


def test_v396_downgrade_no_blocking_drop_index() -> None:
    """downgrade 不允许出现未带 CONCURRENTLY 的裸 DROP INDEX。"""
    code = _strip_comments_and_docstring(_read_v396())
    pattern = re.compile(r"DROP\s+INDEX\s+(?!CONCURRENTLY\b)", re.IGNORECASE)
    matches = [m.group(0) for m in pattern.finditer(code)]
    assert not matches, (
        f"v396 downgrade 仍存在阻塞型 DROP INDEX（未带 CONCURRENTLY）：{matches}"
    )


# ──────────────── 守门 4：六张加盟表索引覆盖完整 ────────────────


def test_v396_covers_all_six_franchise_tables() -> None:
    """六张加盟表（v060/v066 创建）的 last_event_id 索引必须全部覆盖。"""
    text = _read_v396()
    franchise_tables = (
        "franchisees",
        "franchisee_stores",
        "royalty_bills",
        "franchise_audits",
        "franchise_settlements",
        "franchise_settlement_items",
    )
    for table in franchise_tables:
        assert table in text, f"v396 缺少加盟表 {table} 的索引定义"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
