"""D7 自动派单 API 路由 — 6 个端点

端点:
  POST /api/v1/dispatch/alert         处理 Agent 预警 → 自动派单
  GET  /api/v1/dispatch/rules         获取派单规则
  PUT  /api/v1/dispatch/rules         设置派单规则
  POST /api/v1/dispatch/sla-check     SLA 检查(超时升级)
  GET  /api/v1/dispatch/dashboard     派单看板
  GET  /api/v1/dispatch/notifications 通知历史

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from ..services.auto_dispatch import (
    check_sla,
    get_dispatch_dashboard,
    get_dispatch_rules,
    process_agent_alert,
    set_dispatch_rule,
)
from ..services.notification_engine import (
    get_notification_history,
    send_alert_notification,
)

router = APIRouter(prefix="/api/v1/dispatch", tags=["dispatch"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class AlertRequest(BaseModel):
    alert_type: str = Field(..., description="预警类型")
    store_id: str = Field(..., description="门店 ID")
    source_agent: str = Field("unknown", description="来源 Agent")
    summary: str = Field("", description="预警摘要")
    detail: Dict[str, Any] = Field(default_factory=dict, description="预警详情")
    severity: Optional[str] = Field(None, description="严重级别覆盖")


class SetRuleRequest(BaseModel):
    alert_type: str = Field(..., description="预警类型")
    assignee_role: str = Field(..., description="指派角色")
    escalation_minutes: int = Field(30, description="超时升级时间(分钟)")


class AssigneeInfo(BaseModel):
    id: str
    name: str = ""
    role: str = ""


class AlertNotifyRequest(BaseModel):
    alert_type: str
    store_id: str
    summary: str = ""
    severity: str = "normal"
    task_id: str = ""
    assignees: List[AssigneeInfo]
    channels: Optional[List[str]] = None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/alert")
async def handle_agent_alert(
    body: AlertRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """处理 Agent 预警 → 自动创建任务 + 派发。"""
    try:
        result = await process_agent_alert(
            alert=body.model_dump(),
            tenant_id=x_tenant_id,
            db=None,
        )
        # 自动发送通知(mock)
        assignees = [{"id": role, "name": role, "role": role} for role in result.get("assignee_roles", [])]
        if assignees:
            notify_alert = {
                "alert_type": body.alert_type,
                "store_id": body.store_id,
                "summary": body.summary,
                "severity": result.get("severity", "normal"),
                "task_id": result.get("task_id", ""),
            }
            await send_alert_notification(
                alert=notify_alert,
                assignees=assignees,
                tenant_id=x_tenant_id,
                db=None,
            )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/rules")
async def get_rules(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """获取派单规则。"""
    result = await get_dispatch_rules(tenant_id=x_tenant_id, db=None)
    return {"ok": True, "data": result}


@router.put("/rules")
async def update_rule(
    body: SetRuleRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """设置/更新派单规则。"""
    result = await set_dispatch_rule(
        alert_type=body.alert_type,
        assignee_role=body.assignee_role,
        escalation_minutes=body.escalation_minutes,
        tenant_id=x_tenant_id,
        db=None,
    )
    return {"ok": True, "data": result}


@router.post("/sla-check")
async def sla_check(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """SLA 检查 — 超时未处理自动升级。"""
    result = await check_sla(tenant_id=x_tenant_id, db=None)
    return {"ok": True, "data": result}


@router.get("/dashboard")
async def dispatch_dashboard(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """派单看板 — 待处理/处理中/已超时/已完成。"""
    result = await get_dispatch_dashboard(
        store_id=store_id,
        tenant_id=x_tenant_id,
        db=None,
    )
    return {"ok": True, "data": result}


@router.get("/notifications")
async def notification_history(
    recipient_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """通知历史查询。"""
    result = await get_notification_history(
        recipient_id=recipient_id,
        tenant_id=x_tenant_id,
        db=None,
    )
    return {"ok": True, "data": result}
