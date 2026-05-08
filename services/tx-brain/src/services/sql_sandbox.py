"""NLQ SQL 沙箱执行器 — S4-02 Tier 1 后端核心。

职责：
  1. 危险关键字防火墙（assert_safe_sql）— 第一关：拒绝写入语句、多语句、SECURITY DEFINER
  2. PG statement_timeout 注入（防 LLM 输出长查询拖死 DB）
  3. 行数上限 enforce（防意外超大结果集占用内存 / 超长响应）
  4. 异常类型化（UnsafeSqlError / SandboxTimeoutError / RowLimitExceeded）

调用约定（路由层负责）：
  - 用 TenantSession(tenant_id) 注入 app.tenant_id（RLS 强制） + 校验 UUID
  - 用 readonly DB role 连接（生产部署：tx_nlq_readonly，仅 SELECT 权限）
  - 本模块在已注入 tenant 的 session 上跑

S4-02 Issue #289 / Tier 1：read-only + RLS 不可绕 + 防火墙 + 超时 + 行限

后续优化（follow-up）：
  - 沙箱 result.columns 含全部映射（暂用 rows[0].keys() 快速派生）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from .nlq_keyword_firewall import UnsafeSqlError, assert_safe_sql

# 行数上限（防 LLM 输出无 LIMIT 全表查询）
DEFAULT_MAX_ROWS = 10000

# PG statement_timeout（防 LLM 输出 pg_sleep / 笛卡尔积长查询）
DEFAULT_TIMEOUT_MS = 5000


class SandboxTimeoutError(RuntimeError):
    """PG statement_timeout 触发（asyncpg QueryCanceledError）。"""


class RowLimitExceeded(RuntimeError):
    """结果集行数超过沙箱上限。"""


@dataclass
class SandboxResult:
    rows: list[Mapping[str, Any]] = field(default_factory=list)
    row_count: int = 0
    columns: list[str] = field(default_factory=list)
    truncated: bool = False


__all__ = (
    "DEFAULT_MAX_ROWS",
    "DEFAULT_TIMEOUT_MS",
    "RowLimitExceeded",
    "SandboxResult",
    "SandboxTimeoutError",
    "UnsafeSqlError",
    "run_safe_query",
)


async def run_safe_query(
    session: AsyncSession,
    sql: str,
    *,
    max_rows: int = DEFAULT_MAX_ROWS,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> SandboxResult:
    """在已注入 tenant_id 的 session 上跑 NLQ SQL，按沙箱规则约束。

    Tier 1 安全前置（调用方负责）：
      - TenantSession(tenant_id) 注入 app.tenant_id（RLS 强制）
      - readonly DB role 连接（不能用 superuser）

    Args:
        session: 已注入 app.tenant_id 的 AsyncSession
        sql: LLM 生成的 SQL（仅 SELECT/WITH）
        max_rows: 行数上限（默认 10000）
        timeout_ms: PG statement_timeout（默认 5000ms）

    Raises:
        UnsafeSqlError: SQL 含写入关键字 / 多语句 / SECURITY DEFINER 等
        SandboxTimeoutError: PG statement_timeout 触发
        RowLimitExceeded: 结果集行数 > max_rows
        ValueError: timeout_ms 非正数
        RuntimeError: session 处于 AUTOCOMMIT 模式（SET LOCAL 会静默失效）
    """
    # 第一关：防火墙（在 DB 调用前）
    assert_safe_sql(sql)

    # 校验 timeout_ms（PG SET 命令不接受 bind parameter，必须强制 int 防注入）
    timeout_ms_int = int(timeout_ms)
    if timeout_ms_int <= 0:
        raise ValueError(f"timeout_ms 必须为正整数，收到 {timeout_ms!r}")

    # 事务前置：SET LOCAL statement_timeout 仅在事务内生效。
    # 调用方若错用 AUTOCOMMIT engine 取 session，PG 会接受 SET LOCAL 但事务边界
    # 立即结束，超时防护静默失效，沙箱失去第二关。fail-fast 杜绝该路径。
    if not session.in_transaction():
        raise RuntimeError(
            "run_safe_query 必须在已开启的事务中调用 — "
            "AUTOCOMMIT 模式下 SET LOCAL statement_timeout 会静默失效，沙箱失去超时防护"
        )

    # 第二关：超时注入（SET LOCAL 仅本事务生效，与 set_config('app.tenant_id') 同 session）
    await session.execute(
        text(f"SET LOCAL statement_timeout = '{timeout_ms_int}ms'")
    )

    # 第三关：DB 层 LIMIT 包装（WITH ... SELECT * FROM ... LIMIT N+1）
    # 把 row-count enforce 从 Python 层下推到 DB，防 LLM 误生成笛卡尔积返回 N×M 行
    # 后用 list(result.mappings()) 把整个结果集物化到 Python 内存，OOM 沙箱进程。
    # firewall 接受 "SELECT 1;"（单尾分号），但 PG 不允许 CTE body 内含 ;，须先剥离。
    user_sql = sql.rstrip().rstrip(";").rstrip()
    wrapped_sql = (
        f"WITH __nlq_user_query AS ({user_sql}) "
        f"SELECT * FROM __nlq_user_query LIMIT {max_rows + 1}"
    )

    # 第四关：执行 + 异常类型化
    try:
        result = await session.execute(text(wrapped_sql))
    except DBAPIError as exc:
        # asyncpg QueryCanceledError 透过 sqlalchemy DBAPIError 包装上来
        if "canceling statement due to statement timeout" in str(exc):
            raise SandboxTimeoutError(
                f"NLQ 查询超时（{timeout_ms_int}ms 上限触发）"
            ) from exc
        raise

    # 行数上限：DB 已 LIMIT N+1，返回 == N+1 即触发；fetch 上限恒定 N+1 行
    rows = list(result.mappings())
    if len(rows) > max_rows:
        raise RowLimitExceeded(
            f"NLQ 查询超过沙箱上限 {max_rows} 行（DB LIMIT {max_rows + 1} 触发）"
        )

    cols = list(rows[0].keys()) if rows else []
    return SandboxResult(
        rows=rows,
        row_count=len(rows),
        columns=cols,
        truncated=False,
    )
