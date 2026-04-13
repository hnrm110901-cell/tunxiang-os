"""交接班AI智能摘要 API 路由

涵盖:
- POST /api/v1/crew/generate-shift-summary — SSE 流式生成本班摘要（调用 Claude API）
- GET  /api/v1/crew/shift-summary-history  — 历史摘要列表
"""
import json
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["crew-shift-summary"])

# ---------- Pydantic 模型 ----------

class ShiftData(BaseModel):
    table_count: int = Field(..., description="接待桌次")
    revenue_fen: int = Field(..., description="营业额（分）")
    turnover_rate: float = Field(..., description="翻台率")
    satisfaction: Optional[int] = Field(None, description="员工满意度百分比")
    pending_count: Optional[int] = Field(0, description="未完成事项数")
    complaint_count: Optional[int] = Field(0, description="投诉数")


class GenerateSummaryRequest(BaseModel):
    crew_id: str = Field(..., description="服务员ID")
    shift_data: ShiftData = Field(..., description="本班次数据")


# ---------- Claude API 调用（SSE 流式） ----------

SYSTEM_PROMPT = (
    "你是餐厅管理助手，请用3句话生成本班次工作摘要，包含："
    "1)接待情况 2)营业额亮点 3)需要关注的问题。"
    "语气简洁专业，直接输出摘要内容，不要有任何前缀说明。"
)


def _build_user_prompt(data: ShiftData) -> str:
    revenue_yuan = data.revenue_fen / 100
    lines = [
        "本班次数据如下：",
        f"- 接待桌次：{data.table_count} 桌",
        f"- 营业额：{revenue_yuan:.0f} 元",
        f"- 翻台率：{data.turnover_rate:.1f} 次",
    ]
    if data.satisfaction is not None:
        lines.append(f"- 员工满意度：{data.satisfaction}%")
    if data.pending_count:
        lines.append(f"- 未完成事项：{data.pending_count} 条")
    if data.complaint_count:
        lines.append(f"- 顾客投诉：{data.complaint_count} 条")
    return "\n".join(lines)


async def _stream_claude(user_prompt: str):
    """
    调用 Claude API (claude-haiku-4-5-20251001) streaming，
    以 SSE 格式 yield 每个 chunk。
    """
    try:
        import anthropic  # type: ignore
    except ImportError:
        # anthropic SDK 未安装时回退空流
        async for chunk in _empty_stream():
            yield chunk
        return

    try:
        client = anthropic.AsyncAnthropic()
        async with client.messages.stream(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            async for text in stream.text_stream:
                payload = json.dumps({"chunk": text, "done": False}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
        # 发送结束标志
        yield f"data: {json.dumps({'chunk': '', 'done': True})}\n\n"
    except anthropic.APIConnectionError as e:
        logger.warning("claude_api_connection_error", error=str(e))
        async for chunk in _empty_stream():
            yield chunk
    except anthropic.RateLimitError as e:
        logger.warning("claude_api_rate_limit", error=str(e))
        async for chunk in _empty_stream():
            yield chunk
    except anthropic.APIStatusError as e:
        logger.error("claude_api_status_error", status_code=e.status_code, error=str(e))
        async for chunk in _empty_stream():
            yield chunk


async def _empty_stream():
    """Claude API 不可用时的降级空流（返回空数组信号，不输出伪造内容）。"""
    yield f"data: {json.dumps({'chunk': '', 'done': True})}\n\n"


# ---------- DB 历史摘要查询 ----------

async def _fetch_history_from_db(
    db: AsyncSession,
    crew_id: str,
    tenant_id: str,
) -> list[dict[str, Any]]:
    """从 crew_shift_summaries 查询历史摘要，按 created_at 降序，最多返回 20 条。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )
    sql = text("""
        SELECT
            id::text                                            AS id,
            crew_id::text                                       AS crew_id,
            summary,
            shift_date,
            shift_label,
            TO_CHAR(created_at AT TIME ZONE 'Asia/Shanghai', 'MM-DD HH24:MI') AS created_at_label
        FROM crew_shift_summaries
        WHERE crew_id = :crew_id::uuid
          AND is_deleted = FALSE
        ORDER BY created_at DESC
        LIMIT 20
    """)
    result = await db.execute(sql, {"crew_id": crew_id})
    rows = result.mappings().all()
    items = []
    for row in rows:
        items.append({
            "id":         row["id"],
            "crew_id":    row["crew_id"],
            "summary":    row["summary"],
            "shift_date": row["shift_date"].isoformat() if row["shift_date"] else "",
            "shift_label": row["shift_label"] or "",
            "created_at": row["created_at_label"] or "",
        })
    return items


# ---------- 路由 ----------

@router.post("/api/v1/crew/generate-shift-summary")
async def generate_shift_summary(
    body: GenerateSummaryRequest,
    x_operator_id: str = Header(default="op-001", alias="X-Operator-ID"),
    x_tenant_id: str   = Header(default="",       alias="X-Tenant-ID"),
):
    """
    生成本班次AI智能摘要（SSE 流式响应）。

    - 从请求体读取本班数据（生产环境可从DB查询补充更多维度）
    - 构建 prompt，调用 Claude API (claude-haiku-4-5-20251001) streaming
    - 以 SSE 格式流式返回：data: {"chunk": "...", "done": false}\\n\\n
    - 结束：data: {"chunk": "", "done": true}\\n\\n
    - Claude API 不可用时立即发送 done:true 空流，不输出伪造内容
    """
    log = logger.bind(
        operator_id=x_operator_id,
        tenant_id=x_tenant_id,
        crew_id=body.crew_id,
    )
    log.info(
        "shift_summary_generate",
        table_count=body.shift_data.table_count,
        revenue_fen=body.shift_data.revenue_fen,
    )

    user_prompt = _build_user_prompt(body.shift_data)

    return StreamingResponse(
        _stream_claude(user_prompt),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/v1/crew/shift-summary-history")
async def get_shift_summary_history(
    x_operator_id: str = Header(default="op-001", alias="X-Operator-ID"),
    x_tenant_id: str   = Header(default="",       alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    获取历史摘要列表。

    从 crew_shift_summaries 表查询，按 created_at 降序。
    DB 不可用时降级返回空列表。
    """
    log = logger.bind(operator_id=x_operator_id, tenant_id=x_tenant_id)
    try:
        items = await _fetch_history_from_db(db, x_operator_id, x_tenant_id)
        log.info("shift_summary_history_ok", count=len(items))
        return {"ok": True, "data": {"items": items, "total": len(items)}}
    except SQLAlchemyError as e:
        log.warning("shift_summary_history_db_error", error=str(e))
        return {"ok": True, "data": {"items": [], "total": 0}}
    except ValueError as e:
        log.warning("shift_summary_history_value_error", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001 — MLPS3-P0: 最外层HTTP兜底
        log.error("shift_summary_history_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")
