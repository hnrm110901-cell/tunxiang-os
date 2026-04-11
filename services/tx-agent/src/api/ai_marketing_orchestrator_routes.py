"""AI营销编排 Agent API 路由

暴露 AiMarketingOrchestratorAgent 的营销触达能力：
  POST /api/v1/agent/ai-marketing/trigger        — 手动触发营销动作
  POST /api/v1/agent/ai-marketing/batch-trigger  — 批量触发（分群）
  GET  /api/v1/agent/ai-marketing/health-score   — 营销健康评分
  GET  /api/v1/agent/ai-marketing/touch-log      — 触达记录查询

所有接口需要 X-Tenant-ID 请求头。
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/agent/ai-marketing", tags=["ai-marketing"])


def _require_tenant(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return x_tenant_id


def _get_agent(tenant_id: str, store_id: Optional[str] = None) -> Any:
    from ..agents.skills.ai_marketing_orchestrator import AiMarketingOrchestratorAgent
    return AiMarketingOrchestratorAgent(tenant_id=tenant_id, store_id=store_id)


# ─────────────────────────────────────────────────────────────────────────────
# 请求模型
# ─────────────────────────────────────────────────────────────────────────────

class TriggerBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    action: str  # execute_post_order_touch / execute_welcome_journey / etc.
    member_id: str
    store_id: str
    extra_context: dict[str, Any] = {}


class BatchTriggerBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    action: str
    member_ids: list[str]
    store_id: str
    extra_context: dict[str, Any] = {}


# ─────────────────────────────────────────────────────────────────────────────
# 路由
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/trigger")
async def trigger_marketing_action(
    body: TriggerBody,
    tenant_id: str = Depends(_require_tenant),
) -> dict[str, Any]:
    """手动触发单个会员的营销动作

    适用于：事件系统直接调用、运营人员手动触发、A/B 测试单次验证。
    """
    agent = _get_agent(tenant_id, body.store_id)

    if body.action not in agent.get_supported_actions():
        raise HTTPException(
            status_code=422,
            detail=f"不支持的 action: {body.action}。支持：{agent.get_supported_actions()}",
        )

    params = {
        "member_id": body.member_id,
        "store_id": body.store_id,
        **body.extra_context,
    }

    result = await agent.execute(body.action, params)
    return {
        "ok": result.success,
        "data": {
            "action": result.action,
            "reasoning": result.reasoning,
            "confidence": result.confidence,
            "constraints_passed": result.constraints_passed,
            "data": result.data,
            "execution_ms": result.execution_ms,
        },
    }


@router.post("/batch-trigger")
async def batch_trigger_marketing_action(
    body: BatchTriggerBody,
    tenant_id: str = Depends(_require_tenant),
) -> dict[str, Any]:
    """批量触发分群营销动作（异步处理，返回 job_id）

    大批量（>200人）推荐使用此接口，系统后台异步分批处理。
    """
    if len(body.member_ids) == 0:
        raise HTTPException(status_code=422, detail="member_ids 不能为空")

    if len(body.member_ids) > 10000:
        raise HTTPException(status_code=422, detail="单次批量不超过10000人，请分批提交")

    job_id = f"batch_{uuid.uuid4().hex[:12]}"

    # 对于小批量（<=50），直接同步执行
    if len(body.member_ids) <= 50:
        agent = _get_agent(tenant_id, body.store_id)
        results = []
        for mid in body.member_ids:
            params = {"member_id": mid, "store_id": body.store_id, **body.extra_context}
            r = await agent.execute(body.action, params)
            results.append({"member_id": mid, "success": r.success, "data": r.data})

        return {
            "ok": True,
            "data": {
                "job_id": job_id,
                "mode": "sync",
                "total": len(body.member_ids),
                "results": results,
            },
        }

    # 大批量：写入任务队列（这里 mock 为 queued，生产接入 Redis Queue/APScheduler）
    logger.info(
        "batch_marketing_queued",
        job_id=job_id,
        tenant_id=tenant_id,
        action=body.action,
        member_count=len(body.member_ids),
    )
    return {
        "ok": True,
        "data": {
            "job_id": job_id,
            "mode": "async",
            "total": len(body.member_ids),
            "status": "queued",
            "estimated_seconds": len(body.member_ids) // 10,
        },
    }


@router.get("/health-score")
async def get_marketing_health_score(
    store_id: str = Query(...),
    channel_count: int = Query(default=2),
    monthly_touches_per_member: float = Query(default=1.5),
    avg_open_rate: float = Query(default=0.06),
    attributed_order_pct: float = Query(default=0.2),
    tenant_id: str = Depends(_require_tenant),
) -> dict[str, Any]:
    """获取门店营销健康评分（0-100）

    评分维度：
    - 渠道覆盖率 (35分): 已接入渠道数 / 6个主渠道
    - 触达频率 (25分): 月均每会员触达次数
    - 内容质量 (25分): 平均打开率
    - 归因率 (15分): 可归因到营销的订单占比
    """
    agent = _get_agent(tenant_id, store_id)
    result = await agent.execute(
        "get_marketing_health_score",
        {
            "store_id": store_id,
            "channel_count": channel_count,
            "monthly_touches_per_member": monthly_touches_per_member,
            "avg_open_rate": avg_open_rate,
            "attributed_order_pct": attributed_order_pct,
        },
    )
    return {"ok": result.success, "data": result.data}


@router.get("/touch-log")
async def get_touch_log(
    store_id: str = Query(...),
    days: int = Query(default=7, ge=1, le=90),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    tenant_id: str = Depends(_require_tenant),
) -> dict[str, Any]:
    """查询近期营销触达记录

    支持按门店、时间范围、状态筛选。
    数据来源：marketing_touch_log 表。
    """
    # 生产环境：查询 marketing_touch_log 表
    # 当前返回 mock 数据
    mock_items = [
        {
            "touch_id": f"touch_{i:04d}",
            "member_id": f"mbr_{i:06d}",
            "channel": ["sms", "wechat_subscribe", "wecom_chat"][i % 3],
            "campaign_type": ["post_order_touch", "birthday_care", "winback_journey"][i % 3],
            "status": ["sent", "delivered", "clicked"][i % 3],
            "sent_at": f"2026-04-{10 + (i % 2):02d}T{10 + i:02d}:00:00Z",
            "attribution_revenue_fen": [0, 8800, 12000][i % 3],
        }
        for i in range(1, min(size + 1, 6))
    ]

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "days": days,
            "total": 128,
            "page": page,
            "size": size,
            "items": mock_items,
        },
    }
