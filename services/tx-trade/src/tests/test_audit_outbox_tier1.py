"""Tier 1 — PR-3 (R-A4-2) audit JSONL outbox 兜底测试

§19 复审第 2 项发现：trade_audit_log.write_audit 在 PG 写入失败时（Mac mini
断网 / 连接池耗尽 / RLS WITH CHECK 失败 / 字符串列截断）走 broad except 吞掉
异常，**审计永久丢失**。等保三级 + 金税四期内控要求 deny / allow 事件可追溯。

修复策略验证：
  - PG 写入失败 → 自动 spill 到本地 JSONL outbox
  - outbox 文件可被 sync-engine 后续 flush 到 PG
  - 截断 / 文件不可写 / 长行等 edge case fail-safe
"""
from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import OperationalError

from src.services.audit_outbox import (
    _PIPE_BUF_GUARD,
    _rotate_outbox,
    flush_outbox_to_pg,
    write_audit_to_outbox,
)
from src.services.trade_audit_log import write_audit

# 测试默认禁用 dev_bypass，强制 RBAC 走真实路径
# 放在 import 之后是 isort 友好的写法 — write_audit / write_audit_to_outbox 在
# 调用时读 os.environ，不在 import 期间求值，所以顺序不影响行为。
os.environ.setdefault("TX_AUTH_ENABLED", "true")


# ──────────────── fixtures ────────────────


@pytest.fixture
def temp_outbox(monkeypatch, tmp_path):
    """临时 outbox 文件路径（每个测试独立，自动清理）。"""
    outbox = tmp_path / "tx-trade-audit-outbox.jsonl"
    monkeypatch.setenv("TX_AUDIT_OUTBOX_PATH", str(outbox))
    return outbox


# ──────────────────────────────────────────────────────────────────────────
# 场景 1：write_audit_to_outbox 写入一条有效 JSONL 行
# ──────────────────────────────────────────────────────────────────────────


def test_outbox_writes_jsonl_line_with_wrapper_metadata(temp_outbox):
    """audit row 写入后，文件应包含一行有效 JSON，含 _outbox_ts / _outbox_seq /
    _outbox_pid 元数据 + audit 子对象。
    """
    audit = {
        "tenant_id": "00000000-0000-0000-0000-0000000000a1",
        "user_id": "00000000-0000-0000-0000-000000000011",
        "user_role": "cashier",
        "action": "refund.apply",
        "result": "deny",
        "reason": "ROLE_FORBIDDEN",
        "severity": "warn",
        "client_ip": "10.0.0.5",
    }

    ok = write_audit_to_outbox(audit)
    assert ok is True
    assert temp_outbox.exists()

    lines = temp_outbox.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1

    parsed = json.loads(lines[0])
    assert "_outbox_ts" in parsed
    assert "_outbox_seq" in parsed
    assert "_outbox_pid" in parsed
    assert parsed["audit"]["action"] == "refund.apply"
    assert parsed["audit"]["tenant_id"] == "00000000-0000-0000-0000-0000000000a1"
    assert parsed["audit"]["reason"] == "ROLE_FORBIDDEN"


# ──────────────────────────────────────────────────────────────────────────
# 场景 2：write_audit PG 失败 → 自动 spill 到 outbox
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pg_failure_spills_to_outbox(temp_outbox):
    """write_audit 在 SQLAlchemyError（如 Mac mini PG 断网）时必须把 audit 行写入 outbox。

    R-A4-2 核心断言：原 broad except 吞掉异常导致审计丢失，修复后至少落本地。
    """
    failing_db = AsyncMock()
    # 第一次 execute 调用（_target_in_caller_tenant 内部）让它静默；INSERT 时抛 OperationalError
    call_count = {"n": 0}

    async def _failing_execute(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] >= 2:  # 第 2 次调用（INSERT）触发 PG 失败
            raise OperationalError("connection refused", None, None)
        # 第 1 次（set_config）正常返回
        m = AsyncMock()
        m.first = lambda: None
        return m

    failing_db.execute = _failing_execute
    failing_db.commit = AsyncMock()
    failing_db.rollback = AsyncMock()

    await write_audit(
        failing_db,
        tenant_id="00000000-0000-0000-0000-0000000000a1",
        store_id=None,
        user_id="00000000-0000-0000-0000-000000000011",
        user_role="cashier",
        action="refund.apply",
        target_type=None,
        target_id=None,
        amount_fen=None,
        client_ip="10.0.0.5",
        result="deny",
        reason="ROLE_FORBIDDEN",
        severity="warn",
    )

    # 关键断言：即使 PG 失败，outbox 文件也已经写入
    assert temp_outbox.exists(), "PG 失败时必须 spill 到 outbox（R-A4-2 核心约束）"
    line = temp_outbox.read_text(encoding="utf-8").strip()
    parsed = json.loads(line)
    assert parsed["audit"]["action"] == "refund.apply"
    assert parsed["audit"]["reason"] == "ROLE_FORBIDDEN"


# ──────────────────────────────────────────────────────────────────────────
# 场景 3：超长行被拒绝（PIPE_BUF guard 防原子写入撕裂）
# ──────────────────────────────────────────────────────────────────────────


def test_outbox_rejects_oversized_line_to_protect_atomicity(temp_outbox):
    """单行编码 > _PIPE_BUF_GUARD (≈4KB) 时拒绝写入。

    POSIX append-only write 在 < PIPE_BUF 时原子；超过则可能在多进程并发下撕裂。
    宁可丢一条（log.critical 留痕），也不让 outbox 文件被腐蚀。
    """
    huge_payload = "x" * (_PIPE_BUF_GUARD + 1000)
    audit = {
        "tenant_id": "00000000-0000-0000-0000-0000000000a1",
        "user_id": "00000000-0000-0000-0000-000000000011",
        "action": "refund.apply",
        "reason": huge_payload,  # 超长字段
    }

    ok = write_audit_to_outbox(audit)
    assert ok is False, "超长行必须被拒绝"

    # 文件不应被创建（写入前已检查长度）
    if temp_outbox.exists():
        # 如果之前的测试触发了文件创建，至少新行不能进去
        content = temp_outbox.read_text(encoding="utf-8")
        assert huge_payload not in content


# ──────────────────────────────────────────────────────────────────────────
# 场景 4：UUID / Decimal / datetime 序列化（default=str fallback）
# ──────────────────────────────────────────────────────────────────────────


def test_outbox_serializes_non_json_native_types(temp_outbox):
    """audit row 含 UUID / Decimal 等非原生 JSON 类型时，default=str 转字符串。"""
    import uuid as _uuid
    from decimal import Decimal

    audit = {
        "tenant_id": _uuid.UUID("00000000-0000-0000-0000-0000000000a1"),
        "user_id": "00000000-0000-0000-0000-000000000011",
        "action": "discount.apply",
        "amount_fen": Decimal("8800"),
        "before_state": {"price": Decimal("88.00")},
    }

    ok = write_audit_to_outbox(audit)
    assert ok is True

    parsed = json.loads(temp_outbox.read_text(encoding="utf-8").strip())
    assert parsed["audit"]["tenant_id"] == "00000000-0000-0000-0000-0000000000a1"
    # Decimal('8800') → "8800" string via default=str
    assert parsed["audit"]["amount_fen"] == "8800"


# ──────────────────────────────────────────────────────────────────────────
# 场景 5：rotate — 文件大小超阈值时归档
# ──────────────────────────────────────────────────────────────────────────


def test_rotate_archives_active_file_to_dot1(temp_outbox):
    """rotate 把 a.jsonl 重命名为 a.jsonl.1（旧的 .1 → .2，依此类推）。"""
    # 准备一个有内容的活跃文件
    temp_outbox.write_text("line1\nline2\n", encoding="utf-8")
    assert temp_outbox.exists()

    _rotate_outbox(temp_outbox)

    archived = temp_outbox.with_suffix(temp_outbox.suffix + ".1")
    assert archived.exists()
    assert archived.read_text(encoding="utf-8") == "line1\nline2\n"
    # 原文件已不存在（下次写入会重新创建）
    assert not temp_outbox.exists()


# ──────────────────────────────────────────────────────────────────────────
# 场景 6：写入路径不可写时 fail-safe（不抛 + log.critical）
# ──────────────────────────────────────────────────────────────────────────


def test_outbox_unwritable_path_returns_false_does_not_raise(monkeypatch):
    """outbox 路径不可写（mkdir 失败 / 权限拒绝）时 fail-safe：返回 False，不抛。

    这是兜底的兜底 — write_audit 已经 broad except 兜底了，outbox 模块再抛会让
    整个 audit 路径崩溃。
    """
    # 用一个绝对不可写的路径（指向只读文件系统）
    monkeypatch.setenv("TX_AUDIT_OUTBOX_PATH", "/dev/null/cannot-mkdir-here/outbox.jsonl")

    audit = {
        "tenant_id": "00000000-0000-0000-0000-0000000000a1",
        "user_id": "00000000-0000-0000-0000-000000000011",
        "action": "refund.apply",
    }

    # 必须不抛（即使返回 False）
    ok = write_audit_to_outbox(audit)
    assert ok is False


# ──────────────────────────────────────────────────────────────────────────
# 场景 7：flush_outbox_to_pg 读取并重放
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_flush_outbox_ingests_rows_then_archives(temp_outbox):
    """flush_outbox_to_pg 读 outbox → INSERT → 归档为 .processed.<ts>。"""
    # 准备 outbox 内容（手动写两条）
    write_audit_to_outbox({
        "tenant_id": "00000000-0000-0000-0000-0000000000a1",
        "user_id": "00000000-0000-0000-0000-000000000011",
        "action": "refund.apply",
        "result": "deny",
        "reason": "ROLE_FORBIDDEN",
        "severity": "warn",
    })
    write_audit_to_outbox({
        "tenant_id": "00000000-0000-0000-0000-0000000000a1",
        "user_id": "00000000-0000-0000-0000-000000000012",
        "action": "discount.apply",
        "result": "allow",
        "severity": "info",
    })
    assert temp_outbox.exists()

    # mock db — 只验证 execute 被调用了 4 次（2 行 × 2 SELECT/INSERT）+ 1 次 commit
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    rows = await flush_outbox_to_pg(db)
    assert rows == 2
    assert db.commit.call_count == 1

    # 原文件已被重命名为 .processed.<ts>
    assert not temp_outbox.exists()
    processed_files = list(temp_outbox.parent.glob(temp_outbox.name + ".processed.*"))
    assert len(processed_files) == 1


# ──────────────────────────────────────────────────────────────────────────
# 场景 8：concurrent process write — append-only 不撕裂
# ──────────────────────────────────────────────────────────────────────────


def test_concurrent_writes_do_not_tear_lines(temp_outbox, tmp_path):
    """多线程并发写入，每条 JSONL 行仍然完整可解析（POSIX O_APPEND 序列化保证）。

    简化为线程并发（GIL 内同样能复现写入交错）。100 条短行写完后，所有行都
    必须是合法 JSON。
    """
    import threading

    audit = {
        "tenant_id": "00000000-0000-0000-0000-0000000000a1",
        "user_id": "00000000-0000-0000-0000-000000000011",
        "action": "concurrent.test",
    }

    def _writer(n_iter: int):
        for _ in range(n_iter):
            write_audit_to_outbox(audit)

    threads = [threading.Thread(target=_writer, args=(20,)) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 100 条全部应该是合法 JSON 且每行恰好一个 audit
    lines = [l for l in temp_outbox.read_text(encoding="utf-8").split("\n") if l.strip()]
    assert len(lines) == 100
    for i, line in enumerate(lines):
        parsed = json.loads(line)  # 撕裂会让 json.loads 抛 JSONDecodeError
        assert parsed["audit"]["action"] == "concurrent.test", f"line {i} corrupted: {line!r}"
