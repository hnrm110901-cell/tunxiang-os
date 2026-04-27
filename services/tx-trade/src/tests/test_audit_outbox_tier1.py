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
from unittest.mock import AsyncMock, MagicMock

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
async def test_flush_outbox_ingests_rows_then_cleans_up(temp_outbox):
    """flush_outbox_to_pg 读 outbox → INSERT → commit 后删除 .flushing 文件。

    P1 修复（PR #111 codex review #1）：
      - 旧行为：成功后整个 outbox rename 为 .processed.<ts>，但若 max_rows
        截断 / 行解析失败 → 剩余行被永久 archive 成 .processed → 数据丢失
      - 新行为：rename-first 冻结 → 处理 → leftover/poison 分流 → 全部消费
        完成后 .flushing 文件直接 unlink（不再保留 .processed 归档）。
    """
    # 准备 outbox 内容（手动写两条）
    write_audit_to_outbox(
        {
            "tenant_id": "00000000-0000-0000-0000-0000000000a1",
            "user_id": "00000000-0000-0000-0000-000000000011",
            "action": "refund.apply",
            "result": "deny",
            "reason": "ROLE_FORBIDDEN",
            "severity": "warn",
        }
    )
    write_audit_to_outbox(
        {
            "tenant_id": "00000000-0000-0000-0000-0000000000a1",
            "user_id": "00000000-0000-0000-0000-000000000012",
            "action": "discount.apply",
            "result": "allow",
            "severity": "info",
        }
    )
    assert temp_outbox.exists()

    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    rows = await flush_outbox_to_pg(db)
    assert rows == 2
    assert db.commit.call_count == 1

    # 原文件被 rename + 处理后 unlink（不再保留 .processed 归档）
    assert not temp_outbox.exists()
    flushing_files = list(temp_outbox.parent.glob(temp_outbox.name + ".flushing.*"))
    assert len(flushing_files) == 0, "flushing file should be unlinked after successful flush"


# ──────────────────────────────────────────────────────────────────────────
# P1 修复回归保护：max_rows 上限不丢余下行
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_flush_outbox_max_rows_preserves_leftover(temp_outbox):
    """outbox 有 5 行 + max_rows=3 → 只 INSERT 前 3 行，剩 2 行回写 outbox。

    P1 修复回归保护（PR #111 codex review #1 第 1 条）：
    旧代码 break out 后无条件 archive 整个文件 → 行 4/5 永久丢失。
    新代码必须把行 4/5 append 回 outbox.jsonl 等下次 flush。
    """
    for i in range(5):
        write_audit_to_outbox(
            {
                "tenant_id": "00000000-0000-0000-0000-0000000000a1",
                "user_id": f"00000000-0000-0000-0000-{i:012d}",
                "action": f"test.row_{i}",
                "result": "allow",
            }
        )
    assert len([l for l in temp_outbox.read_text("utf-8").splitlines() if l.strip()]) == 5

    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    rows = await flush_outbox_to_pg(db, max_rows=3)
    assert rows == 3, "前 3 行应该 INSERT 成功"

    # 剩 2 行回写到主 outbox
    assert temp_outbox.exists(), "主 outbox 必须存在（写回 leftover 重建文件）"
    remaining = [l for l in temp_outbox.read_text("utf-8").splitlines() if l.strip()]
    assert len(remaining) == 2, f"剩余 2 行必须回写，实际 {len(remaining)}"
    # 行序保持
    for i, line in enumerate(remaining):
        parsed = json.loads(line)
        assert parsed["audit"]["action"] == f"test.row_{i + 3}"

    # .flushing 文件已删除
    flushing_files = list(temp_outbox.parent.glob(temp_outbox.name + ".flushing.*"))
    assert len(flushing_files) == 0


# ──────────────────────────────────────────────────────────────────────────
# P1 修复回归保护：transient INSERT 失败 → 整批 retry，已 INSERT 行也回收
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_flush_outbox_transient_failure_rolls_back_and_requeues_all(temp_outbox):
    """前 2 行 INSERT 成功，第 3 行触发 SQLAlchemyError → rollback 整批 → 全部 5 行回写。

    避免部分提交语义混乱：只有"全部 commit 成功"或"全部留待下次"两个稳态。
    """
    from sqlalchemy.exc import SQLAlchemyError

    for i in range(5):
        write_audit_to_outbox(
            {
                "tenant_id": "00000000-0000-0000-0000-0000000000a1",
                "user_id": f"00000000-0000-0000-0000-{i:012d}",
                "action": f"test.row_{i}",
            }
        )

    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    # 模拟 _insert_one_audit 的两次 execute 调用（set_config + INSERT）
    # 第 3 行的 INSERT 抛 SQLAlchemyError
    insert_call_count = {"n": 0}

    async def execute_side_effect(query, params=None):
        sql = str(query)
        if "INSERT INTO trade_audit_logs" in sql:
            insert_call_count["n"] += 1
            if insert_call_count["n"] == 3:
                raise SQLAlchemyError("simulated transient failure")
        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)

    rows = await flush_outbox_to_pg(db)
    assert rows == 0, "transient 失败必须 rollback 整批"
    db.rollback.assert_awaited()

    # 5 行全部回写到主 outbox
    assert temp_outbox.exists()
    remaining = [l for l in temp_outbox.read_text("utf-8").splitlines() if l.strip()]
    assert len(remaining) == 5, f"全部 5 行必须回收为 leftover，实际 {len(remaining)}"


# ──────────────────────────────────────────────────────────────────────────
# P1 修复回归保护：JSON 解析失败 → poison 文件不无限重试
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_flush_outbox_unparseable_lines_go_to_poison(temp_outbox):
    """损坏行 / 空 audit envelope → 移到 .poison 文件，不再重试。

    避免一条永远失败的行让 outbox 永远清不空（类似 Kafka 的死信队列模式）。
    """
    # 写 1 条好行
    write_audit_to_outbox(
        {
            "tenant_id": "00000000-0000-0000-0000-0000000000a1",
            "user_id": "00000000-0000-0000-0000-000000000011",
            "action": "good.row",
        }
    )
    # 手动追加：1 条 JSON 解析失败 + 1 条空 audit envelope
    with temp_outbox.open("a", encoding="utf-8") as f:
        f.write("this is not json{\n")
        f.write('{"_outbox_ts":"2026-04-26T00:00:00Z","_outbox_seq":1,"audit":{}}\n')

    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    rows = await flush_outbox_to_pg(db)
    assert rows == 1, "好行成功 INSERT"

    # 主 outbox 应该被清空（好行已入库，2 条坏行进 poison 不回流）
    if temp_outbox.exists():
        remaining = [l for l in temp_outbox.read_text("utf-8").splitlines() if l.strip()]
        assert len(remaining) == 0, "坏行不应回流到主 outbox"

    # poison 文件存在且包含 2 条坏行
    poison_path = temp_outbox.with_suffix(temp_outbox.suffix + ".poison")
    assert poison_path.exists(), "坏行必须移到 .poison 文件"
    poison_lines = [l for l in poison_path.read_text("utf-8").splitlines() if l.strip()]
    assert len(poison_lines) == 2


# ──────────────────────────────────────────────────────────────────────────
# P1 #2 修复回归保护：retained .flushing 文件被自动重试（不卡死）
# PR #111 chatgpt-codex-connector review #2
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_flush_outbox_retains_flushing_file_after_writeback_failure(temp_outbox, tmp_path, monkeypatch):
    """leftover writeback 失败 → .flushing 文件保留，下次 flush 必须自动重试它。

    模拟：
      1. write_audit_to_outbox 写 5 行
      2. 第一次 flush：max_rows=10（够全部成功），但模拟 _append_lines_to_outbox
         给主 outbox 写 leftover 时失败 → .flushing 文件保留
      3. 第二次 flush：主 outbox 不存在（无新 audit），但有 retained .flushing →
         必须仍然处理它（不能 return 0 直接退出）

    P1 修复回归保护：原代码看 path.exists() 为 False 即 return 0，retained
    .flushing 永远不被处理。修复后扫描 .flushing.* glob 自动重试。
    """
    # 准备 5 行（其中 2 行 max_rows=2 会触发 leftover）
    for i in range(5):
        write_audit_to_outbox(
            {
                "tenant_id": "00000000-0000-0000-0000-0000000000a1",
                "user_id": f"00000000-0000-0000-0000-{i:012d}",
                "action": f"test.row_{i}",
            }
        )

    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    # 第一次 flush：max_rows=2，会产 3 行 leftover
    # 注入 _append_lines_to_outbox 失败 → 保留 .flushing
    from src.services import audit_outbox as outbox_mod

    original_append = outbox_mod._append_lines_to_outbox
    append_failures = {"count": 0}

    def failing_append(path, lines):
        # 主 outbox 写入失败（模拟磁盘满 / 权限错）
        if str(path) == str(temp_outbox):
            append_failures["count"] += 1
            return False
        # 其他文件（.poison）正常写
        return original_append(path, lines)

    monkeypatch.setattr(outbox_mod, "_append_lines_to_outbox", failing_append)

    rows_first = await flush_outbox_to_pg(db, max_rows=2)
    assert rows_first == 2  # 前 2 行 INSERT 成功
    assert append_failures["count"] >= 1  # leftover writeback 至少试了一次

    # 主 outbox 不存在（rename 走了），剩 3 行卡在 .flushing
    assert not temp_outbox.exists()
    flushing_files = list(temp_outbox.parent.glob(temp_outbox.name + ".flushing.*"))
    assert len(flushing_files) == 1, "leftover writeback 失败 → .flushing 必须保留"

    # 第二次 flush：恢复 _append_lines_to_outbox 正常工作
    monkeypatch.setattr(outbox_mod, "_append_lines_to_outbox", original_append)

    # 关键回归保护：主 outbox 不存在 + 有 retained .flushing → 必须处理它
    rows_second = await flush_outbox_to_pg(db, max_rows=10)
    assert rows_second == 3, "retained .flushing 的 3 行必须在第二次 flush 被处理"

    # .flushing 已被消费删除
    flushing_files_after = list(temp_outbox.parent.glob(temp_outbox.name + ".flushing.*"))
    assert len(flushing_files_after) == 0


@pytest.mark.asyncio
async def test_flush_outbox_processes_retained_when_main_missing(temp_outbox, tmp_path):
    """主 outbox 不存在但有 retained .flushing → 仍然处理（不 short-circuit return 0）。

    最直接的回归保护：手动伪造一个 .flushing 文件（模拟前次失败遗留），
    主 outbox 完全不存在 → 调 flush 必须 INSERT retained 行。
    """
    # 手动创建 retained .flushing 文件（模拟前次写回失败保留下来）
    retained = temp_outbox.with_suffix(temp_outbox.suffix + ".flushing.1700000000000")
    retained.write_text(
        json.dumps(
            {
                "_outbox_ts": "2026-04-26T00:00:00Z",
                "_outbox_seq": 1,
                "audit": {
                    "tenant_id": "00000000-0000-0000-0000-0000000000a1",
                    "user_id": "00000000-0000-0000-0000-000000000011",
                    "action": "retained.row",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert retained.exists()
    assert not temp_outbox.exists()

    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    rows = await flush_outbox_to_pg(db)
    assert rows == 1, "retained 行必须被消费（即便主 outbox 不存在）"
    assert not retained.exists(), "消费后 .flushing 必须删除"
    assert db.commit.call_count == 1


@pytest.mark.asyncio
async def test_flush_outbox_processes_retained_in_fifo_order(temp_outbox, tmp_path):
    """多个 .flushing 文件 → 按 ts 升序处理（旧的先入库）。"""
    # 创建 3 个 retained .flushing，时间戳递增
    for ts, action in [(1000, "old.row"), (2000, "mid.row"), (3000, "new.row")]:
        flushing = temp_outbox.with_suffix(temp_outbox.suffix + f".flushing.{ts}")
        flushing.write_text(
            json.dumps(
                {
                    "_outbox_ts": "2026-04-26T00:00:00Z",
                    "_outbox_seq": 1,
                    "audit": {
                        "tenant_id": "00000000-0000-0000-0000-0000000000a1",
                        "user_id": "00000000-0000-0000-0000-000000000011",
                        "action": action,
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

    inserted_actions: list[str] = []
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        if "INSERT INTO trade_audit_logs" in sql and params:
            inserted_actions.append(params.get("action", ""))
        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)

    rows = await flush_outbox_to_pg(db)
    assert rows == 3
    # 旧文件（ts=1000）的行先 INSERT
    assert inserted_actions == ["old.row", "mid.row", "new.row"], f"FIFO 顺序错误: {inserted_actions}"


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
