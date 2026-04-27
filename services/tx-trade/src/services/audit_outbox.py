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

import asyncio
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
                    file=str(oldest),
                    error=str(exc),
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
                        src=str(src),
                        dst=str(dst),
                        error=str(exc),
                    )
                    return

        # 当前活跃文件 → .1
        if path.exists():
            try:
                os.rename(str(path), str(path.with_suffix(path.suffix + ".1")))
            except OSError as exc:
                logger.warning(
                    "audit_outbox_rotate_active_failed",
                    path=str(path),
                    error=str(exc),
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

    at-least-once 保证（两轮 §19 P1 复审修复）：
      - rename-first 把活跃 outbox 冻结为 .flushing.<ts>（concurrent 写入自动
        转到新建的 outbox.jsonl，不会被本批次锁住，也不会被本批次截断丢失）
      - **每次进入都先扫描 retained .flushing.* 文件**（PR #111 codex P1 #2
        修复）：如果上次 flush 在写回 leftover/poison 时失败 → 当时保留了
        .flushing 文件，本次必须自动重试它们。否则一旦没有新 audit 写入主
        outbox，retained 文件永远不被处理，形成"数据在盘上但被排除在 flush
        循环外"的卡死状态。
      - 单 .flushing 文件三类输出：
          * processed   — 已 INSERT；commit 成功后丢弃，commit 失败回收为 leftover
          * leftover    — 超出 max_rows / 单行 transient 失败 / commit 失败 →
                          append 回主 outbox（保持顺序），下次 flush 重试
          * poison      — JSON 解析失败 / 缺 audit envelope → append 到 .poison
                          文件供运维 triage（不再无限重试）
      - 单行 transient 失败时 rollback + 整批 retry（避免部分 commit）：所有
        已 INSERT 但未 commit 的行 + 失败行 + 后续行 都进 leftover
      - leftover/poison 写回失败 → 保留 .flushing.<ts> 文件，下次 flush 自动
        把它当作 retained 重试

    Args:
        db: SQLAlchemy AsyncSession
        max_rows: 单次成功 INSERT 行数上限（跨多个 .flushing 文件共享预算）

    Returns:
        本轮 flush 跨所有 .flushing 文件累计成功 INSERT + commit 的行数
    """
    path = _outbox_path()

    # ── Step 1: 收集所有待处理的 .flushing 文件
    # 来源 A：retained .flushing.<ts>（上次 flush 写回失败留下，必须优先重试）
    # 来源 B：当前活跃 outbox（rename → 新 .flushing.<now-ts>）
    flushing_files = _gather_flushing_files(path)

    # 总是同时尝试 adopt 当前主 outbox（即便 retained 存在，也别让新 audit 排队太久）
    flush_ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    if path.exists():
        new_flushing = path.with_suffix(path.suffix + f".flushing.{flush_ts}")
        try:
            os.rename(str(path), str(new_flushing))
            flushing_files.append(new_flushing)
        except FileNotFoundError:
            pass  # 并发 flush 已经 adopt
        except OSError as exc:
            logger.error("audit_outbox_flush_rename_failed", error=str(exc))
            # 不 return 0：可能仍有 retained .flushing 要处理

    if not flushing_files:
        return 0  # 真正没数据要处理

    # ── Step 2: FIFO 顺序处理（旧 .flushing 优先，retained 数据先入库）
    flushing_files.sort(key=lambda p: _flushing_ts_or_zero(p, path))

    total_ingested = 0
    for flushing_path in flushing_files:
        if total_ingested >= max_rows:
            # 预算耗尽：剩余 .flushing 文件留到下次 flush 自动重试
            logger.info(
                "audit_outbox_flush_budget_exhausted",
                ingested=total_ingested,
                remaining_files=len(flushing_files) - flushing_files.index(flushing_path),
            )
            break
        remaining_budget = max_rows - total_ingested
        ingested = await _process_one_flushing_file(
            db,
            outbox_path=path,
            flushing_path=flushing_path,
            max_rows=remaining_budget,
        )
        total_ingested += ingested

    return total_ingested


def _gather_flushing_files(outbox_path: Path) -> list[Path]:
    """扫 outbox 父目录里所有 retained .flushing.* 文件（不含 .read-failed）。"""
    parent = outbox_path.parent
    if not parent.exists():
        return []
    pattern = outbox_path.name + ".flushing.*"
    try:
        return [p for p in parent.glob(pattern) if p.is_file()]
    except OSError as exc:
        logger.warning("audit_outbox_flush_scan_failed", error=str(exc))
        return []


def _flushing_ts_or_zero(flushing_path: Path, outbox_path: Path) -> int:
    """从 .flushing.<ts> 后缀解析 ts；解析失败返回 0（视为最旧）。"""
    name = flushing_path.name
    prefix = outbox_path.name + ".flushing."
    if not name.startswith(prefix):
        return 0
    suffix = name[len(prefix) :]
    try:
        return int(suffix)
    except ValueError:
        return 0


async def _process_one_flushing_file(
    db,
    *,
    outbox_path: Path,
    flushing_path: Path,
    max_rows: int,
) -> int:
    """处理一个 .flushing 文件：读取 → INSERT → commit → 写回 leftover/poison。

    leftover 写回**主 outbox** path（不是 flushing_path），所以 retained 文件
    在被消费后就不再存在。下次 flush 看到主 outbox 有 leftover 时按正常流程
    再 rename + 处理。

    Returns:
        本次 flushing 文件成功 INSERT + commit 的行数
    """
    flush_ts = int(datetime.now(timezone.utc).timestamp() * 1000)

    # ── Step 1: 读全部行进内存
    try:
        with flushing_path.open("r", encoding="utf-8") as f:
            all_lines = f.readlines()
    except OSError as exc:
        logger.error(
            "audit_outbox_flush_read_failed",
            flushing_path=str(flushing_path),
            error=str(exc),
        )
        # 读失败 — 改名为 .read-failed 让运维 triage（不丢、不再被本函数 retain）
        try:
            os.rename(
                str(flushing_path),
                str(outbox_path.with_suffix(outbox_path.suffix + f".read-failed.{flush_ts}")),
            )
        except OSError:
            pass
        return 0

    # ── Step 2: 处理每一行，分流到 processed / leftover / poison
    processed_lines: list[str] = []
    leftover_lines: list[str] = []
    poison_lines: list[str] = []

    aborted_at_index = len(all_lines)
    for i, raw_line in enumerate(all_lines):
        line_with_nl = raw_line if raw_line.endswith("\n") else raw_line + "\n"
        stripped = raw_line.strip()
        if not stripped:
            continue
        if len(processed_lines) >= max_rows:
            aborted_at_index = i
            break

        try:
            wrapped = json.loads(stripped)
            audit = wrapped.get("audit") or {}
        except (json.JSONDecodeError, AttributeError, TypeError) as exc:
            poison_lines.append(line_with_nl)
            logger.warning(
                "audit_outbox_flush_poison_line",
                line_no=i,
                error=str(exc),
            )
            continue

        if not audit:
            poison_lines.append(line_with_nl)
            logger.warning("audit_outbox_flush_empty_audit", line_no=i)
            continue

        try:
            await _insert_one_audit(db, audit)
            processed_lines.append(line_with_nl)
        except SQLAlchemyError as exc:
            try:
                await db.rollback()
            except SQLAlchemyError:
                pass
            logger.warning(
                "audit_outbox_flush_row_failed",
                line_no=i,
                error=str(exc),
            )
            leftover_lines.extend(processed_lines)
            leftover_lines.append(line_with_nl)
            processed_lines = []
            aborted_at_index = i + 1
            break

    # 超出 max_rows / transient 中断后的剩余行
    for raw_line in all_lines[aborted_at_index:]:
        line_with_nl = raw_line if raw_line.endswith("\n") else raw_line + "\n"
        if raw_line.strip():
            leftover_lines.append(line_with_nl)

    # ── Step 3: commit
    rows_ingested = 0
    if processed_lines:
        try:
            await db.commit()
            rows_ingested = len(processed_lines)
        except SQLAlchemyError as exc:
            try:
                await db.rollback()
            except SQLAlchemyError:
                pass
            logger.error(
                "audit_outbox_flush_commit_failed",
                rows_attempted=len(processed_lines),
                error=str(exc),
            )
            leftover_lines = list(processed_lines) + leftover_lines
            processed_lines = []
            rows_ingested = 0

    # ── Step 4: 写回 leftover 到主 outbox
    leftover_ok = _append_lines_to_outbox(outbox_path, leftover_lines) if leftover_lines else True
    if not leftover_ok:
        logger.error(
            "audit_outbox_flush_leftover_writeback_failed",
            flushing_path=str(flushing_path),
            leftover_count=len(leftover_lines),
        )

    # ── Step 5: poison 行 append 到 .poison
    poison_path = outbox_path.with_suffix(outbox_path.suffix + ".poison")
    poison_ok = _append_lines_to_outbox(poison_path, poison_lines) if poison_lines else True
    if not poison_ok:
        logger.error(
            "audit_outbox_flush_poison_writeback_failed",
            flushing_path=str(flushing_path),
            poison_count=len(poison_lines),
        )

    # ── Step 6: 决定如何处理 .flushing 文件
    if leftover_ok and poison_ok:
        # 全部 leftover/poison 落盘成功 → 安全删除 .flushing
        try:
            flushing_path.unlink()
        except OSError as exc:
            logger.warning(
                "audit_outbox_flush_cleanup_failed",
                path=str(flushing_path),
                error=str(exc),
            )
        return rows_ingested

    # leftover/poison 写回失败 → 必须保留未处理行供下次 retry。
    # 关键：如果有 partial commit (rows_ingested > 0)，必须把 .flushing 重写为
    # 只含"写回失败的未处理行"，否则下次 retry 会重新 INSERT 已 commit 行（重复审计）。
    unprocessed: list[str] = []
    if not leftover_ok:
        unprocessed.extend(leftover_lines)
    if not poison_ok:
        unprocessed.extend(poison_lines)

    if rows_ingested > 0 and unprocessed:
        # 原子重写：tmp + rename 替换 .flushing 内容
        # 失败时回退到"保留原 .flushing"（at-least-once，retry 时已 commit 行重复 INSERT，
        # 在 PG 层依靠 trade_audit_logs id 自动唯一接受重复，运维通过 audit_outbox_flush_*
        # log 关联 ID 排查）
        rewrite_tmp = flushing_path.with_suffix(flushing_path.suffix + ".rewriting")
        try:
            rewrite_tmp.write_text("".join(unprocessed), encoding="utf-8")
            os.rename(str(rewrite_tmp), str(flushing_path))
            logger.info(
                "audit_outbox_flush_rewrote_after_partial_commit",
                flushing_path=str(flushing_path),
                committed=rows_ingested,
                retained=len(unprocessed),
            )
        except OSError as exc:
            logger.error(
                "audit_outbox_flush_rewrite_failed",
                flushing_path=str(flushing_path),
                error=str(exc),
            )
            # 清理 tmp 文件
            try:
                rewrite_tmp.unlink()
            except OSError:
                pass
            # 回退：保留原 .flushing（含已 commit 行）。下次 retry 重复 INSERT 由
            # PG / 运维侧解决（不丢审计 > 重复审计）

    return rows_ingested


def _append_lines_to_outbox(path: Path, lines: list[str]) -> bool:
    """append 一组行到 outbox 风格文件（POSIX O_APPEND 多进程安全）。

    返回 True 表示全部成功；False 表示有 OSError，调用方需保留源文件不删。
    """
    if not lines:
        return True
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = "".join(lines).encode("utf-8")
        fd = os.open(
            str(path),
            os.O_WRONLY | os.O_APPEND | os.O_CREAT,
            0o640,
        )
        try:
            os.write(fd, encoded)
        finally:
            os.close(fd)
        return True
    except OSError as exc:
        logger.error(
            "audit_outbox_append_failed",
            path=str(path),
            count=len(lines),
            error=str(exc),
        )
        return False


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
            "before_state": (json.dumps(audit["before_state"]) if audit.get("before_state") else None),
            "after_state": (json.dumps(audit["after_state"]) if audit.get("after_state") else None),
        },
    )


# ──────────────────────────────────────────────────────────────────────────
#  PR-4 — 后台 flusher 循环
#
#  PR-3 落了 outbox 写入侧；本节负责让 outbox 真正被消费。tx-trade 在云端
#  跑，outbox 是 cloud PVC，flusher 也跑在 tx-trade 同 pod（不走 sync-engine
#  —— sync-engine 仅处理 Mac mini ↔ cloud 跨机同步，云端 pod 内的 PVC →
#  PG flush 应该自包含）。
#
#  生产配置（k8s helm values 推荐）：
#    - 60s 间隔（默认）— 200 桌并发场景下 deny 率 < 1%，单次 flush ~10ms
#    - 单实例运行（每个 pod 自己的 PVC + 自己的 flusher，避免跨 pod 锁竞争）
#    - 紧急关停：环境变量 TX_AUDIT_OUTBOX_FLUSHER_DISABLED=true（运维手动
#      关闭以便排查 outbox 文件，不需要重新部署）
# ──────────────────────────────────────────────────────────────────────────


_FLUSHER_DEFAULT_INTERVAL_SECONDS: float = 60.0


async def _flusher_loop(
    session_factory,
    stop_event: asyncio.Event,
    interval_seconds: float,
) -> None:
    """后台 task：周期性 flush outbox 到 PG。

    永不 raise — 每次迭代独立异常处理，PG 临时不可用 / 网络抖动 / 文件系统
    瞬时错误都不能让 loop 死掉。stop_event 触发时立刻唤醒并优雅退出。

    Args:
        session_factory: 异步上下文管理器，async with session_factory() as s
        stop_event: 外部传入；.set() 后下次 sleep 立刻返回，loop 退出
        interval_seconds: 两次 flush 之间的最小间隔（成功 flush 时也按此 sleep）
    """
    logger.info(
        "audit_outbox_flusher_loop_started",
        interval_seconds=interval_seconds,
    )
    while not stop_event.is_set():
        try:
            async with session_factory() as session:
                rows = await flush_outbox_to_pg(session)
                if rows > 0:
                    logger.info(
                        "audit_outbox_flusher_iteration",
                        rows_ingested=rows,
                    )
        except Exception:  # noqa: BLE001 — loop 必须永生
            logger.warning(
                "audit_outbox_flusher_iteration_failed",
                exc_info=True,
            )
        # 可中断 sleep — stop_event.set() 立即唤醒
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            # stop_event 触发了，跳出 loop
            break
        except asyncio.TimeoutError:
            # 正常的 interval 到期，进入下一轮
            continue
    logger.info("audit_outbox_flusher_loop_stopped")


def _flusher_disabled_by_env() -> bool:
    return os.getenv("TX_AUDIT_OUTBOX_FLUSHER_DISABLED", "").strip().lower() in {
        "true",
        "1",
        "yes",
    }


def start_audit_outbox_flusher(
    session_factory,
    *,
    interval_seconds: float = _FLUSHER_DEFAULT_INTERVAL_SECONDS,
) -> tuple[asyncio.Task, asyncio.Event]:
    """启动 outbox flusher 后台 task。lifespan 调用方应保留 (task, event) 对，
    在 yield 结束后 event.set() + await task 完成 graceful shutdown。

    紧急关停：环境变量 TX_AUDIT_OUTBOX_FLUSHER_DISABLED=true → 返回一个
    立即完成的 noop task + 已 set 的 event，调用方 lifespan 代码无需 if-else。
    （outbox 写入仍正常工作，只是不自动重放；运维可手动 SCP 文件 + 跑 cron 工具）

    Returns:
        (task, stop_event) — 配套使用：
            stop_event.set()
            await asyncio.wait_for(task, timeout=10)
    """
    stop_event = asyncio.Event()
    if _flusher_disabled_by_env():
        stop_event.set()

        async def _noop() -> None:
            return

        task = asyncio.create_task(_noop())
        logger.info("audit_outbox_flusher_disabled_by_env")
        return task, stop_event

    task = asyncio.create_task(
        _flusher_loop(session_factory, stop_event, interval_seconds),
    )
    return task, stop_event
