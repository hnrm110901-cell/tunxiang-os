"""stream_report_routes — SSE 流式报告 AI 解读接口

供前端实时接收长文本经营报告解读（P&L分析/库存分析/成本健康诊断等）。
使用 Server-Sent Events，前端通过 EventSource 连接。

路由：
  POST /api/v1/reports/stream  — 流式 AI 解读指定报告数据
  GET  /api/v1/reports/stream/health — 健康检查
"""

from __future__ import annotations

import json
from typing import AsyncGenerator, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/reports/stream", tags=["reports-stream"])


class StreamReportRequest(BaseModel):
    """流式报告解读请求"""

    prompt: str  # 解读指令（用户自然语言，如"解读本月P&L异常"）
    report_data: dict = {}  # 报告数据（如 finance_profit_loss 输出）
    report_type: str = "auto"  # 报告类型（auto=自动检测，或 pl/inventory/cost_health）
    store_id: Optional[str] = None


def _get_model_router():
    """获取 ModelRouter 实例（不可用时返回 None，降级处理）"""
    try:
        from tx_agent.src.services.model_router import ModelRouter  # type: ignore[import]

        return ModelRouter()
    except ImportError:
        logger.warning("stream_report_routes.model_router_not_available")
        return None


def _report_type_to_task_type(report_type: str) -> str:
    """将报告类型映射到 ModelRouter 任务类型。"""
    mapping = {
        "pl": "cost_analysis",
        "inventory": "standard_analysis",
        "cost_health": "cost_analysis",
        "dashboard": "dashboard_brief",
        "auto": "auto",
    }
    return mapping.get(report_type, "standard_analysis")


@router.post("")
async def stream_report_analysis(
    body: StreamReportRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> StreamingResponse:
    """流式 AI 报告解读接口（SSE）

    前端连接方式：
    ```javascript
    const es = new EventSource('/api/v1/reports/stream', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Tenant-ID': tenantId},
      body: JSON.stringify({
        prompt: '解读本月P&L成本率异常原因并给出建议',
        report_data: plData,
        report_type: 'pl',
      })
    });
    es.onmessage = (e) => console.log(JSON.parse(e.data).text);
    es.addEventListener('done', () => es.close());
    es.addEventListener('error', (e) => console.error(JSON.parse(e.data).error));
    ```
    """
    try:
        UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid X-Tenant-ID")

    model_router = _get_model_router()
    if model_router is None:
        raise HTTPException(
            status_code=503,
            detail="AI 服务暂不可用（ModelRouter 未初始化），请检查 ANTHROPIC_API_KEY 配置",
        )

    # 构建消息：将报告数据作为上下文注入 prompt
    report_text = json.dumps(body.report_data, ensure_ascii=False, indent=2) if body.report_data else ""
    content = body.prompt
    if report_text:
        content = f"{body.prompt}\n\n报告数据：\n{report_text}"

    messages = [{"role": "user", "content": content}]
    task_type = _report_type_to_task_type(body.report_type)

    async def generate() -> AsyncGenerator[str, None]:
        """SSE 事件流生成器"""
        try:
            full_text = ""
            async for chunk in model_router.stream_complete(
                tenant_id=x_tenant_id,
                task_type=task_type,
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
                "stream_report_analysis_completed",
                tenant_id=x_tenant_id,
                report_type=body.report_type,
                task_type=task_type,
                total_chars=len(full_text),
            )
        except (RuntimeError, ValueError) as exc:
            error_payload = json.dumps({"error": str(exc), "done": True}, ensure_ascii=False)
            yield f"event: error\ndata: {error_payload}\n\n"
            logger.error(
                "stream_report_analysis_error",
                tenant_id=x_tenant_id,
                report_type=body.report_type,
                error=str(exc),
            )

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
async def stream_report_health() -> dict:
    """流式报告服务健康检查"""
    model_router = _get_model_router()
    return {
        "ok": True,
        "service": "stream-report-analysis",
        "model_router_available": model_router is not None,
    }
