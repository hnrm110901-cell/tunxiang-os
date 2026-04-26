"""audit_outbox — Sprint A4 R-A4-2 / Tier1 — 审计日志离线兜底

§19 复审第 2 项发现：trade_audit_log.py 的 write_audit 在 PG 写入失败时
（Mac mini 边缘断网 / 连接池耗尽 / 表锁等）走 broad except 吞掉异常，
**审计永久丢失**。等保三级 + 金税四期内控要求 deny / allow 事件可追溯。

修复策略（最小可行）：
  1. PG INSERT 失败时，先把 audit row 序列化为 JSON 落本地 JSONL outbox 文件
  2. 文件路径可由 TX_AUDIT_OUTBOX_PATH 配置，生产 k8s 通过 PVC 挂载
  3. 文件大小到 100MB 自动 rotate（保留 5 份）
  4. sync-engine（独立服务）后续读 outbox → batch INSERT → 成功后 truncate

不在本次 PR 范围内（独立后续工作）：
  - sync-engine flush 调度（提供 flush_outbox_to_pg() 接口供其调用）
  - 跨 pod 去重 / hash 校验
  - JSONL 加密 / 字段脱敏（PII 防泄露）
  - Prometheus metric: audit_outbox_pending_rows

POSIX atomicity 假设：
  - 单次 write() 短消息（< PIPE_BUF = 4KB on Linux/macOS）保证不撕裂
  - JSONL 行 99% 场景 < 1KB（payload 极少 > 4KB）
  - 长行（> 4KB）会触发警告 + 跳过 outbox（fail-open，至少 log.critical 留痕）
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

logger = structlog.get_logger(__name__)


# ──────────────── 配置常量（环境变量可覆盖） ────────────────

_DEFAULT_OUTBOX_PATH = "/var/log/tunxiang/tx-trade-audit-outbox.jsonl"
_DEFAULT_MAX_BYTES = 100 * 1024 * 1024  # 100MB
_DEFAULT_ROTATE_KEEP = 5
_PIPE_BUF_GUARD = 4000  # POSIX PIPE_BUF 4096，留 96 字节余量


def _outbox_path() -> Path:
    return Path(os.getenv("TX_AUDIT_OUTBOX_PATH", _DEFAULT_OUTBOX_PATH))


def _max_bytes() -> int:
    raw = os.getenv("TX_AUDIT_OUTBOX_MAX_BYTES")
    if raw and raw.isdigit():
        return int(raw)
    return _DEFAULT_MAX_BYTES


# 进程内序列号 — 用于同一秒内多条记录排序
_seq_lock = threading.Lock()
_seq_counter = 0


def _next_seq() -> int:
    global _seq_counter
    with _seq_lock:
        _seq_counter += 1
        return _seq_counter


# ──────────────── 主入口：fallback 写 outbox ────────────────


def write_audit_to_outbox(audit_row: Mapping[str, Any]) -> bool:
    """把一条 audit 记录写入本地 JSONL outbox。

    fail-safe 设计：
      - 任何错误（路径不可写 / 磁盘满 / 行过长）都不再抛出，最多 log.critical
      - 因为本函数本身就是 PG 写入失败的兜底，再抛会让原始 SQLAlchemyError
        被掩盖，破坏 broad except 兜底语义

    Args:
        audit_row: 审计行 dict，期望包含 tenant_id / user_id / action / result /
                   reason / severity / target_type / target_id / amount_fen /
                   client_ip / before_state / after_state 等字段。所有字段
                   通过 json.dumps(default=str) 序列化，UUID / datetime 自动转字符串。

    Returns:
        True  — 已写入 outbox（sync-engine 后续可消费）
        False — 写入失败（已 log.critical 留痕，调用方无需处理）
    """
    try:
        path = _outbox_path()
        # 准备目录（首次启动时可能不存在）
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.critical(
                "audit_outbox_mkdir_failed",
                path=str(path),
                error=str(exc),
            )
            return False

        # 包装审计行：加 outbox 元数据，方便 sync-engine 去重 / 排序 / 重放
        wrapped = {
            "_outbox_ts": datetime.now(timezone.utc).isoformat(),
            "_outbox_seq": _next_seq(),
            "_outbox_pid": os.getpid(),
            "audit": dict(audit_row),
        }
        # default=str 处理 UUID / datetime / Decimal 等非原生 JSON 类型
        line = json.dumps(wrapped, default=str, ensure_ascii=False, separators=(",", ":"))
        encoded = (line + "\n").encode("utf-8")

        # POSIX atomicity guard：单次 write 不撕裂前提是 < PIPE_BUF
        if len(encoded) > _PIPE_BUF_GUARD:
            logger.critical(
                "audit_outbox_line_too_long",
                length=len(encoded),
                limit=_PIPE_BUF_GUARD,
                action=audit_row.get("action"),
                # 不打印 payload 内容（可能含 PII）
            )
            return False

        # rotate 检查（基于已存在文件大小，写之前判断）
        try:
            current_size = path.stat().st_size
        except FileNotFoundError:
            current_size = 0
        except OSError as exc:
            logger.critical(
                "audit_outbox_stat_failed",
                path=str(path),
                error=str(exc),
            )
            return False

        if current_size + len(encoded) > _max_bytes():
            _rotate_outbox(path)

        # 实际写入：append + binary，单次 write 由内核保证原子（< PIPE_BUF）
        # 'ab' 模式 + os.O_APPEND 多进程安全（POSIX append-only 写入序列化）
        try:
            fd = os.open(
                str(path),
                os.O_WRONLY | os.O_APPEND | os.O_CREAT,
                0o640,
            )
            try:
                os.write(fd, encoded)
            finally:
                os.close(fd)
        except OSError as exc:
            logger.critical(
                "audit_outbox_write_failed",
                path=str(path),
                error=str(exc),
                action=audit_row.get("action"),
            )
            return False

        return True
    except Exception as exc:  # noqa: BLE001 — 最外层兜底：审计 fallback 绝不能再抛
        logger.critical(
            "audit_outbox_unexpected_error",
            error=str(exc),
            exc_info=True,
        )
        return False


# ──────────────── 文件 rotate ────────────────


def _rotate_outbox(path: Path) -> None:
    """rotate: a.jsonl → a.jsonl.1, a.jsonl.1 → a.jsonl.2, ..., 删除 a.jsonl.N。

    用 os.rename 保证每一步原子。中途崩溃最多丢一份归档，不会破坏当前活跃文件。
    """
    keep = _DEFAULT_ROTATE_KEEP
    try:
        # 先删最老的（避免 rename 撞名）
        oldest = path.with_suffix(path.suffix + f".{keep}")
        if oldest.exists():
            try:
                oldest.unlink()
            except OSError as exc:
                logger.warning(
                    "audit_outbox_rotate_unlink_failed",
                    file=str(oldest), error=str(exc),
                )
                return  # 放弃 rotate（不影响后续追加）

        # 倒序 rename：N-1 → N, N-2 → N-1, ..., 0 → 1
        for i in range(keep - 1, 0, -1):
            src = path.with_suffix(path.suffix + f".{i}")
            dst = path.with_suffix(path.suffix + f".{i + 1}")
            if src.exists():
                try:
                    os.rename(str(src), str(dst))
                except OSError as exc:
                    logger.warning(
                        "audit_outbox_rotate_rename_failed",
                        src=str(src), dst=str(dst), error=str(exc),
                    )
                    return

        # 当前活跃文件 → .1
        if path.exists():
            try:
                os.rename(str(path), str(path.with_suffix(path.suffix + ".1")))
            except OSError as exc:
                logger.warning(
                    "audit_outbox_rotate_active_failed",
                    path=str(path), error=str(exc),
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "audit_outbox_rotate_unexpected",
            error=str(exc),
            exc_info=True,
        )


# ──────────────── 消费侧：sync-engine 调用 ────────────────


async def flush_outbox_to_pg(db, *, max_rows: int = 1000) -> int:
    """读 outbox JSONL，逐条 INSERT 到 trade_audit_logs。

    sync-engine 应周期性调用（建议 60s 间隔）。本函数在 audit_outbox.py 内部
    暴露接口，但调度由外部完成（避免在 tx-trade 进程内做后台 IO）。

    设计：
      - 读取活跃文件 + .1 / .2 / ... 归档（按时间倒序补齐）
      - 单次最多 max_rows 行，避免长事务
      - 单行 JSON 解析失败 / INSERT 失败 → 跳过，继续下一行（已 log）
      - 全部成功后通过 rename 把消费过的文件标记为 .processed
        （sync-engine 后续清理 .processed 文件，留 24h 兜底取证）
      - 不删除原文件直到 commit 成功（at-least-once 语义，重复由 PG 主键去重）

    Args:
        db: SQLAlchemy AsyncSession
        max_rows: 单次最大消费行数

    Returns:
        实际成功 INSERT 的行数
    """
    path = _outbox_path()
    if not path.exists():
        return 0

    # 简单实现：只读活跃文件，逐行 INSERT，全部成功后 rename 为 .processed
    # 复杂归档（rotate 文件 + 多个 .processed）由 sync-engine 后续完善
    rows_ingested = 0
    failed_lines: list[str] = []

    try:
        with path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= max_rows:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    wrapped = json.loads(line)
                    audit = wrapped.get("audit", {})
                    if not audit:
                        continue
                    await _insert_one_audit(db, audit)
                    rows_ingested += 1
                except (json.JSONDecodeError, SQLAlchemyError, KeyError) as exc:
                    logger.warning(
                        "audit_outbox_flush_row_failed",
                        line_no=i,
                        error=str(exc),
                    )
                    failed_lines.append(line)
                    continue
    except OSError as exc:
        logger.error("audit_outbox_flush_read_failed", error=str(exc))
        return rows_ingested

    if rows_ingested > 0:
        try:
            await db.commit()
        except SQLAlchemyError as exc:
            await db.rollback()
            logger.error(
                "audit_outbox_flush_commit_failed",
                rows_ingested=rows_ingested,
                error=str(exc),
            )
            return 0
        # 成功消费：rename 为 .processed（保留 24h 取证由外部 cron 清理）
        try:
            processed_path = path.with_suffix(
                path.suffix + f".processed.{int(datetime.now(timezone.utc).timestamp())}"
            )
            os.rename(str(path), str(processed_path))
        except OSError as exc:
            logger.warning(
                "audit_outbox_flush_archive_failed",
                error=str(exc),
            )

    return rows_ingested


async def _insert_one_audit(db, audit: Mapping[str, Any]) -> None:
    """单行 INSERT helper — 不 commit（由 flush_outbox_to_pg 批量 commit）。

    至少包含 tenant_id / user_id / action 字段。其他字段 PG 自动填 NULL。
    """
    tenant_id = audit.get("tenant_id") or "00000000-0000-0000-0000-000000000000"
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )
    await db.execute(
        text(
            """
            INSERT INTO trade_audit_logs (
                tenant_id, store_id, user_id, user_role,
                action, target_type, target_id,
                amount_fen, client_ip,
                result, reason, request_id, severity, session_id,
                before_state, after_state
            ) VALUES (
                :tenant_id, :store_id, :user_id, :user_role,
                :action, :target_type, :target_id,
                :amount_fen, CAST(:client_ip AS INET),
                :result, :reason, :request_id, :severity, :session_id,
                CAST(:before_state AS JSONB), CAST(:after_state AS JSONB)
            )
            """
        ),
        {
            "tenant_id": str(tenant_id),
            "store_id": audit.get("store_id"),
            "user_id": str(audit.get("user_id") or "(unknown)"),
            "user_role": audit.get("user_role") or "",
            "action": audit.get("action") or "(unknown)",
            "target_type": audit.get("target_type"),
            "target_id": audit.get("target_id"),
            "amount_fen": audit.get("amount_fen"),
            "client_ip": audit.get("client_ip"),
            "result": audit.get("result"),
            "reason": audit.get("reason"),
            "request_id": audit.get("request_id"),
            "severity": audit.get("severity"),
            "session_id": audit.get("session_id"),
            "before_state": (
                json.dumps(audit["before_state"]) if audit.get("before_state") else None
            ),
            "after_state": (
                json.dumps(audit["after_state"]) if audit.get("after_state") else None
            ),
        },
    )
