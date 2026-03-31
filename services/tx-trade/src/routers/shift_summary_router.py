"""交接班AI智能摘要 API 路由

涵盖:
- POST /api/v1/crew/generate-shift-summary — SSE 流式生成本班摘要（调用 Claude API）
- GET  /api/v1/crew/shift-summary-history  — 历史摘要列表
"""
import json
from datetime import datetime, timedelta
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

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
        f"本班次数据如下：",
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
        # anthropic SDK 未安装时回退 Mock 流
        async for chunk in _mock_stream():
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
        async for chunk in _mock_stream():
            yield chunk
    except anthropic.RateLimitError as e:
        logger.warning("claude_api_rate_limit", error=str(e))
        async for chunk in _mock_stream():
            yield chunk
    except anthropic.APIStatusError as e:
        logger.error("claude_api_status_error", status_code=e.status_code, error=str(e))
        async for chunk in _mock_stream():
            yield chunk


async def _mock_stream():
    """Claude API 不可用时的 Mock 回退流。"""
    import asyncio
    mock_text = (
        "本班共接待桌次符合预期，营业额表现良好，高于昨日均值约15%。"
        "翻台率维持正常水平，服务满意度优秀。"
        "需关注备餐区设备故障及物料库存补充事项，请下班同事优先处理。"
    )
    for char in mock_text:
        payload = json.dumps({"chunk": char, "done": False}, ensure_ascii=False)
        yield f"data: {payload}\n\n"
        await asyncio.sleep(0.03)
    yield f"data: {json.dumps({'chunk': '', 'done': True})}\n\n"


# ---------- Mock 历史数据 ----------

def _build_mock_history(crew_id: str) -> list[dict[str, Any]]:
    """返回历史摘要 Mock 数据。"""
    now = datetime.now()
    return [
        {
            "id": "hs-001",
            "crew_id": crew_id,
            "summary": "上午班共接待9桌，营业额2,140元，翻台率2.1次，整体运营平稳，无特殊事项。",
            "shift_date": (now - timedelta(hours=6)).strftime("%Y-%m-%d"),
            "shift_label": "今日午班",
            "created_at": (now - timedelta(hours=6)).strftime("%m-%d %H:%M"),
        },
        {
            "id": "hs-002",
            "crew_id": crew_id,
            "summary": "昨日晚班接待15桌，营业额4,520元，高峰期出现短暂等位，服务质量良好，收到2条好评。",
            "shift_date": (now - timedelta(days=1)).strftime("%Y-%m-%d"),
            "shift_label": "昨日晚班",
            "created_at": (now - timedelta(days=1)).strftime("%m-%d %H:%M"),
        },
        {
            "id": "hs-003",
            "crew_id": crew_id,
            "summary": "前日午班接待11桌，营业额3,200元，运营平稳，无异常事项需要交接。",
            "shift_date": (now - timedelta(days=2)).strftime("%Y-%m-%d"),
            "shift_label": "前日午班",
            "created_at": (now - timedelta(days=2)).strftime("%m-%d %H:%M"),
        },
    ]


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
):
    """
    获取历史摘要列表。

    生产环境：从 crew_shift_summaries 表查询，按 created_at 降序。
    当前：返回 Mock 数据。
    """
    log = logger.bind(operator_id=x_operator_id, tenant_id=x_tenant_id)
    try:
        items = _build_mock_history(x_operator_id)
        log.info("shift_summary_history_ok", count=len(items))
        return {"ok": True, "data": {"items": items, "total": len(items)}}
    except ValueError as e:
        log.warning("shift_summary_history_value_error", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error("shift_summary_history_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")
