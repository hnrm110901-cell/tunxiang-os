"""NLQ SSE 端点 — S4-02 PR2.C Tier 1 后端入口

POST /api/v1/brain/nlq/query
  request:  { nl_query: str }  + header X-Tenant-ID
  response: text/event-stream（SSE 流）
    event: sql      data: {"sql": "<已校验的 reports.* SELECT>"}
    event: result   data: {"rows": [...], "row_count": N, "columns": [...]}
    event: done     data: {}
    -- 错误路径（任一阶段失败时只发一个 error，前后无 done） --
    event: error    data: {"kind": <generation|sandbox_timeout|row_limit|llm_timeout|internal>,
                            "message": <人类可读>}

调用链：
  request → Depends(_get_db_with_tenant) 注入 AsyncSession + app.tenant_id（RLS 强制）
         → Depends(_get_sql_generator) factory 从 ANTHROPIC_API_KEY env 构造（缺失 503）
         → SqlGenerator.generate() 防火墙 + reports.* 白名单
         → run_safe_query 沙箱（PG statement_timeout + LIMIT N+1 + RLS via session）

CLAUDE.md §17 Tier 1：read-only + RLS 不可绕 + 防火墙 + 白名单 + 沙箱
Refs: issue #289
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.sql_generator import (
    SqlGenerationError,
    SqlGenerator,
    create_default_sql_generator,
)
from ..services.sql_sandbox import (
    RowLimitExceeded,
    SandboxResult,
    SandboxTimeoutError,
    run_safe_query,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/brain", tags=["nlq"])


# ─── Pydantic schemas ────────────────────────────────────────────────────


class NLQRequest(BaseModel):
    """NLQ 查询请求体。"""

    nl_query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="用户自然语言问题",
    )


# ─── FastAPI dependencies ────────────────────────────────────────────────


async def _get_db_with_tenant(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> AsyncGenerator[AsyncSession, None]:
    """注入带 RLS 隔离的 DB session（set_config app.tenant_id）。"""
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _get_sql_generator() -> SqlGenerator:
    """工厂构造 SqlGenerator（ANTHROPIC_API_KEY 缺失 → 503）。

    分离为模块级函数（非 lambda）让测试可 dependency_overrides。
    """
    try:
        return create_default_sql_generator()
    except ValueError as exc:
        # ANTHROPIC_API_KEY 未设置 / MigrationRouter 初始化失败
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"NLQ 服务暂不可用：{exc}",
        ) from exc


# 类型别名：sandbox runner 的签名（让 dependency_overrides 能注入函数引用）
RunSafeQuery = Callable[[AsyncSession, str], Awaitable[SandboxResult]]


def _get_run_safe_query() -> RunSafeQuery:
    """返回 run_safe_query 函数引用（让测试可 override 注入 mock）。"""
    return run_safe_query


# ─── SSE 事件辅助 ────────────────────────────────────────────────────────


def _format_sse_event(kind: str, data: dict[str, Any]) -> str:
    """构造 SSE 帧：`event: <kind>\\ndata: <json>\\n\\n`。

    JSON 编码自动处理换行/特殊字符（防破帧注入）。
    """
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {kind}\ndata: {payload}\n\n"


# ─── 路由 ────────────────────────────────────────────────────────────────


@router.post(
    "/nlq/query",
    summary="NLQ 自然语言查询（SSE 流）",
)
async def nlq_query(
    body: NLQRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_request_id: str = Header(default="", alias="X-Request-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
    sql_gen: SqlGenerator = Depends(_get_sql_generator),
    runner: RunSafeQuery = Depends(_get_run_safe_query),
) -> StreamingResponse:
    """NLQ 端点 — LLM 生成 SQL → 沙箱执行 → SSE 流回放。

    Headers:
      X-Tenant-ID: 必填 UUID（驱动 RLS app.tenant_id）
      X-Request-ID: 选填 UUID（请求追踪）

    Responses:
      200 + text/event-stream（含 sql / result / done 或单 error event）
      422: nl_query 缺失或超长 / X-Tenant-ID 缺失
      503: ANTHROPIC_API_KEY 未设置（_get_sql_generator 抛 HTTPException）
    """
    # request_id 落 generator 调用追踪（factory 没传时用 tenant_id 兜底）
    from uuid import UUID, uuid4

    tenant_uuid = UUID(x_tenant_id)
    request_uuid = UUID(x_request_id) if x_request_id else uuid4()

    async def event_stream() -> AsyncGenerator[str, None]:
        # 阶段 1：LLM 生成 SQL（防火墙 + reports 白名单已在 generator 内做过）
        try:
            sql = await sql_gen.generate(
                tenant_id=tenant_uuid,
                request_id=request_uuid,
                nl_query=body.nl_query,
            )
        except SqlGenerationError as exc:
            yield _format_sse_event(
                "error", {"kind": "generation", "message": str(exc)}
            )
            return
        except TimeoutError as exc:
            yield _format_sse_event(
                "error", {"kind": "llm_timeout", "message": str(exc)}
            )
            return

        yield _format_sse_event("sql", {"sql": sql})

        # 阶段 2：沙箱执行（PG statement_timeout + LIMIT N+1 + RLS）
        try:
            result: SandboxResult = await runner(db, sql)
        except SandboxTimeoutError as exc:
            yield _format_sse_event(
                "error", {"kind": "sandbox_timeout", "message": str(exc)}
            )
            return
        except RowLimitExceeded as exc:
            yield _format_sse_event(
                "error", {"kind": "row_limit", "message": str(exc)}
            )
            return

        # 阶段 3：结果 → SSE
        # SandboxResult.rows 是 list[Mapping]；转成 list[dict] 让 JSON 可序列化
        rows_serializable = [dict(r) for r in result.rows]
        yield _format_sse_event(
            "result",
            {
                "rows": rows_serializable,
                "row_count": result.row_count,
                "columns": list(result.columns),
            },
        )
        yield _format_sse_event("done", {})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # nginx 不缓存 SSE
        },
    )
