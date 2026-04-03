"""stream_routes — SSE 流式 AI 分析接口

供前端实时接收长文本分析（经营报告/P&L解读/库存分析等）。
使用 Server-Sent Events，前端通过 EventSource 连接。
"""
from __future__ import annotations

import json
from typing import AsyncGenerator, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..services.model_router import ModelRouter

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/stream", tags=["stream"])


class StreamAnalysisRequest(BaseModel):
    """流式分析请求"""
    prompt: str                           # 分析指令（用户自然语言）
    context: dict = {}                    # 业务上下文数据（如 P&L 数据、库存数据等）
    task_type: str = "auto"              # 任务类型（auto=自动检测）
    store_id: Optional[str] = None


@router.post("/analysis")
async def stream_analysis(
    body: StreamAnalysisRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> StreamingResponse:
    """流式 AI 分析接口（SSE）

    前端连接方式：
    ```javascript
    const es = new EventSource('/api/v1/stream/analysis', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Tenant-ID': tenantId},
      body: JSON.stringify({prompt: '分析本月成本率异常原因', context: plData})
    });
    es.onmessage = (e) => console.log(JSON.parse(e.data).text);
    es.addEventListener('done', () => es.close());
    ```
    """
    try:
        UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid X-Tenant-ID")

    model_router = ModelRouter()

    # 构建消息
    context_text = json.dumps(body.context, ensure_ascii=False, indent=2) if body.context else ""
    content = body.prompt
    if context_text:
        content = f"{body.prompt}\n\n数据上下文：\n{context_text}"

    messages = [{"role": "user", "content": content}]

    async def generate() -> AsyncGenerator[str, None]:
        """SSE 事件流生成器"""
        try:
            full_text = ""
            async for chunk in model_router.stream_complete(
                tenant_id=x_tenant_id,
                task_type=body.task_type,
                messages=messages,
            ):
                full_text += chunk
                # SSE 格式：data: {...}\n\n
                payload = json.dumps({"text": chunk, "done": False}, ensure_ascii=False)
                yield f"data: {payload}\n\n"

            # 发送完成事件
            done_payload = json.dumps(
                {"text": "", "done": True, "total_length": len(full_text)},
                ensure_ascii=False,
            )
            yield f"event: done\ndata: {done_payload}\n\n"

            logger.info(
                "stream_analysis_completed",
                tenant_id=x_tenant_id,
                task_type=body.task_type,
                total_chars=len(full_text),
            )
        except (RuntimeError, ValueError) as exc:
            error_payload = json.dumps({"error": str(exc), "done": True}, ensure_ascii=False)
            yield f"event: error\ndata: {error_payload}\n\n"
            logger.error("stream_analysis_error", tenant_id=x_tenant_id, error=str(exc))

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Nginx 禁用缓冲
            "Connection": "keep-alive",
        },
    )


@router.get("/health")
async def stream_health() -> dict:
    """流式服务健康检查"""
    return {"ok": True, "service": "stream-analysis"}
