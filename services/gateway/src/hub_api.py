"""Hub API — 屯象科技运维管理端

跨租户操作，使用 get_db_no_rls() 读 PostgreSQL（v132 platform_* / hub_* 表）。
需 platform-admin 级认证与 Nginx 白名单（生产）。
"""

from __future__ import annotations

from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_no_rls

from . import hub_service

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/hub", tags=["hub"])


def _pg_unavailable(exc: ProgrammingError) -> HTTPException:
    logger.warning("hub_pg_schema_missing", error=str(exc))
    return HTTPException(
        status_code=503,
        detail="Hub PG 未就绪：请执行 alembic upgrade 至 v132_platform_hub",
    )


# ─── 商户管理 ───


@router.get("/merchants")
async def list_merchants(
    status: Optional[str] = None,
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(get_db_no_rls),
):
    """列出所有商户（platform_tenants + 门店数聚合）"""
    try:
        data = await hub_service.hub_list_merchants(db, status, page, size)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


class CreateMerchantBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    plan_template: str = Field(..., pattern="^(lite|standard|pro)$")
    merchant_code: Optional[str] = Field(None, max_length=32)
    subscription_expires_at: Optional[str] = Field(None, description="YYYY-MM-DD")


class UpdateMerchantBody(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    plan_template: Optional[str] = Field(None, pattern="^(lite|standard|pro)$")
    status: Optional[str] = Field(None, pattern="^(active|trial|suspended|churned)$")
    subscription_expires_at: Optional[str] = Field(None, description="YYYY-MM-DD")


@router.post("/merchants")
async def create_merchant(
    body: CreateMerchantBody,
    db: AsyncSession = Depends(get_db_no_rls),
):
    """新建商户（开户）— INSERT platform_tenants"""
    try:
        merchant_id = await hub_service.hub_create_merchant(db, body.model_dump())
        return {"ok": True, "data": {"merchant_id": merchant_id, "status": "created"}}
    except IntegrityError as e:
        logger.warning("hub.create_merchant.conflict", error=str(e))
        raise HTTPException(status_code=409, detail="商户编码或名称已存在") from e
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.patch("/merchants/{merchant_id}")
async def update_merchant(
    merchant_id: str,
    body: UpdateMerchantBody,
    db: AsyncSession = Depends(get_db_no_rls),
):
    """更新商户（续费/升级/停用）— UPDATE platform_tenants"""
    try:
        updated = await hub_service.hub_update_merchant(db, merchant_id, body.model_dump(exclude_none=True))
        if not updated:
            raise HTTPException(status_code=404, detail=f"商户 {merchant_id} 不存在")
        return {"ok": True, "data": {"merchant_id": merchant_id, "updated": True}}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


# ─── 全局门店 ───


@router.get("/stores")
async def list_all_stores(
    merchant_id: Optional[str] = None,
    online: Optional[bool] = None,
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(get_db_no_rls),
):
    """全局门店列表（stores + hub_store_overlay + platform_tenants）"""
    try:
        data = await hub_service.hub_list_stores(db, merchant_id, online, page, size)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


# ─── 模板管理 ───


@router.get("/templates")
async def list_templates():
    """模板列表（代码内行业模板对比，与 PG 无关）"""
    from .templates import compare_templates

    return {"ok": True, "data": compare_templates()}


@router.post("/merchants/{merchant_id}/template")
async def assign_template(
    merchant_id: str,
    template_id: str,
    db: AsyncSession = Depends(get_db_no_rls),
):
    """为商户分配模板 — UPDATE platform_tenants.plan_template"""
    try:
        updated = await hub_service.hub_update_merchant(db, merchant_id, {"plan_template": template_id})
        if not updated:
            raise HTTPException(status_code=404, detail=f"商户 {merchant_id} 不存在")
        return {"ok": True, "data": {"merchant_id": merchant_id, "template": template_id}}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


# ─── Adapter 监控 ───


@router.get("/adapters")
async def list_adapter_status(db: AsyncSession = Depends(get_db_no_rls)):
    """Adapter 连接状态（hub_adapter_connections）"""
    try:
        data = await hub_service.hub_list_adapters(db)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


# ─── Agent 全局监控 ───


@router.get("/agents/health")
async def agent_global_health(db: AsyncSession = Depends(get_db_no_rls)):
    """Agent 健康度（hub_agent_metrics_daily）"""
    try:
        data = await hub_service.hub_agent_health(db)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


# ─── 计费账单 ───


@router.get("/billing")
async def get_billing(month: Optional[str] = None, db: AsyncSession = Depends(get_db_no_rls)):
    """计费账单（hub_billing_monthly）"""
    try:
        data = await hub_service.hub_get_billing(db, month)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


# ─── 部署管理 ───


@router.get("/deployment/mac-minis")
async def list_mac_minis(db: AsyncSession = Depends(get_db_no_rls)):
    """Mac mini 舰队（hub_edge_devices）"""
    try:
        data = await hub_service.hub_list_mac_minis(db)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


class PushUpdateBody(BaseModel):
    store_ids: list[str] = Field(default_factory=list)
    target_version: str = ""


@router.post("/deployment/push-update")
async def push_update(
    body: PushUpdateBody,
    db: AsyncSession = Depends(get_db_no_rls),
):
    """远程推送软件更新 — 更新 hub_edge_devices.client_version 目标版本并记录操作"""
    try:
        pushed = await hub_service.hub_push_update(db, body.store_ids, body.target_version)
        logger.info(
            "hub.push_update",
            store_count=len(body.store_ids),
            target_version=body.target_version,
            matched=pushed,
        )
        return {"ok": True, "data": {"pushed": pushed, "target_version": body.target_version}}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


# ─── 工单系统 ───


@router.get("/tickets")
async def list_tickets(status: Optional[str] = None, db: AsyncSession = Depends(get_db_no_rls)):
    """工单列表（hub_tickets）"""
    try:
        data = await hub_service.hub_list_tickets(db, status)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


class CreateTicketBody(BaseModel):
    merchant_name: str = Field(..., min_length=1, max_length=100)
    title: str = Field(..., min_length=1, max_length=255)
    priority: str = Field(..., pattern="^(low|medium|high|urgent)$")
    assignee: Optional[str] = Field(None, max_length=64)
    tenant_id: Optional[str] = Field(None, description="UUID 字符串，可选")


@router.post("/tickets")
async def create_ticket(
    body: CreateTicketBody,
    db: AsyncSession = Depends(get_db_no_rls),
):
    """新建工单 — INSERT hub_tickets"""
    try:
        ticket_id = await hub_service.hub_create_ticket(db, body.model_dump())
        return {"ok": True, "data": {"ticket_id": ticket_id}}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


# ─── 平台数据 ───


@router.get("/platform/stats")
async def platform_stats(db: AsyncSession = Depends(get_db_no_rls)):
    """平台运营数据（聚合 + hub_agent_metrics_daily）"""
    try:
        data = await hub_service.hub_platform_stats(db)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


# ─── Today 今日看板 ───


@router.get("/today")
async def today_dashboard(db: AsyncSession = Depends(get_db_no_rls)):
    """今日看板：待办、告警、Incident、续约提醒、关键指标"""
    try:
        data = await hub_service.hub_today(db)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


# ─── Stream 全局事件流 (SSE) ───


@router.get("/stream")
async def global_stream():
    """全局事件流（SSE）— edge/service/ticket/agent/adapter 事件"""
    logger.info("hub.stream.connect")
    return StreamingResponse(
        hub_service.hub_stream_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─── Edges 边缘节点 ───


@router.get("/edges/topology")
async def edges_topology(db: AsyncSession = Depends(get_db_no_rls)):
    """Tailscale 拓扑视图"""
    try:
        data = await hub_service.hub_edges_topology(db)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.get("/edges")
async def list_edges(
    status: Optional[str] = None,
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(get_db_no_rls),
):
    """边缘节点列表（替代 /deployment/mac-minis）"""
    try:
        data = await hub_service.hub_list_edges(db, status, page, size)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.get("/edges/{sn}")
async def get_edge(sn: str, db: AsyncSession = Depends(get_db_no_rls)):
    """单个边缘节点详情"""
    try:
        data = await hub_service.hub_get_edge(db, sn)
        if not data:
            raise HTTPException(status_code=404, detail=f"边缘节点 {sn} 不存在")
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.get("/edges/{sn}/timeline")
async def edge_timeline(sn: str, db: AsyncSession = Depends(get_db_no_rls)):
    """节点事件时间线"""
    try:
        # 先验证节点存在
        edge = await hub_service.hub_get_edge(db, sn)
        if not edge:
            raise HTTPException(status_code=404, detail=f"边缘节点 {sn} 不存在")
        data = await hub_service.hub_edge_timeline(db, sn)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.post("/edges/{sn}/wake")
async def edge_wake(sn: str, db: AsyncSession = Depends(get_db_no_rls)):
    """唤醒边缘节点（WOL）"""
    try:
        data = await hub_service.hub_edge_wake(db, sn)
        if not data.get("success"):
            raise HTTPException(status_code=404, detail=data.get("error", "操作失败"))
        logger.info("hub.edge.wake", sn=sn)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.post("/edges/{sn}/reboot")
async def edge_reboot(sn: str, db: AsyncSession = Depends(get_db_no_rls)):
    """重启边缘节点"""
    try:
        data = await hub_service.hub_edge_reboot(db, sn)
        if not data.get("success"):
            raise HTTPException(status_code=404, detail=data.get("error", "操作失败"))
        logger.info("hub.edge.reboot", sn=sn)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


class EdgePushBody(BaseModel):
    target_version: str = Field(..., min_length=1, max_length=32)
    force: bool = Field(default=False)


@router.post("/edges/{sn}/push")
async def edge_push(
    sn: str,
    body: EdgePushBody,
    db: AsyncSession = Depends(get_db_no_rls),
):
    """推送更新到单个边缘节点"""
    try:
        data = await hub_service.hub_edge_push(db, sn, body.target_version, body.force)
        if not data.get("success"):
            raise HTTPException(status_code=404, detail=data.get("error", "操作失败"))
        logger.info("hub.edge.push", sn=sn, target_version=body.target_version, force=body.force)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


# ─── Services 微服务 ───


@router.get("/services")
async def list_services():
    """17 个微服务列表 + 健康状态"""
    data = await hub_service.hub_list_services()
    return {"ok": True, "data": data}


@router.get("/services/{name}")
async def get_service(name: str):
    """单个服务详情"""
    data = await hub_service.hub_get_service(name)
    if not data:
        raise HTTPException(status_code=404, detail=f"服务 {name} 不存在")
    return {"ok": True, "data": data}


@router.get("/services/{name}/slos")
async def service_slos(name: str):
    """服务 SLO 列表"""
    data = await hub_service.hub_service_slos(name)
    if data is None:
        raise HTTPException(status_code=404, detail=f"服务 {name} 不存在")
    return {"ok": True, "data": data}


@router.get("/services/{name}/timeline")
async def service_timeline(name: str):
    """服务事件时间线"""
    data = await hub_service.hub_service_timeline(name)
    if data is None:
        raise HTTPException(status_code=404, detail=f"服务 {name} 不存在")
    return {"ok": True, "data": data}


# ─── Copilot Chat ───


class CopilotChatContext(BaseModel):
    workspace: str = Field(default="Hub", max_length=64)
    object_id: Optional[str] = Field(default=None, max_length=128)
    tab: Optional[str] = Field(default=None, max_length=64)


class CopilotChatBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=4096)
    context: CopilotChatContext = Field(default_factory=CopilotChatContext)
    thread_id: Optional[str] = Field(default=None, max_length=64)


@router.post("/copilot/chat")
async def copilot_chat(body: CopilotChatBody):
    """Copilot 对话（SSE 流式响应）"""
    logger.info(
        "hub.copilot.chat",
        message_len=len(body.message),
        workspace=body.context.workspace,
        thread_id=body.thread_id,
    )
    return StreamingResponse(
        hub_service.hub_copilot_chat(
            message=body.message,
            context=body.context.model_dump(),
            thread_id=body.thread_id,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─── Customers 客户扩展 ───


@router.get("/customers/{customer_id}/health")
async def customer_health(customer_id: str, db: AsyncSession = Depends(get_db_no_rls)):
    """客户健康分构成（多维模型：SLA/NPS/Adapter延迟/活跃度/工单量）"""
    try:
        data = await hub_service.hub_customer_health(db, customer_id)
        if not data:
            raise HTTPException(status_code=404, detail=f"客户 {customer_id} 不存在")
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.get("/customers/{customer_id}/timeline")
async def customer_timeline(customer_id: str, db: AsyncSession = Depends(get_db_no_rls)):
    """客户生命周期时间线"""
    try:
        data = await hub_service.hub_customer_timeline(db, customer_id)
        if data is None:
            raise HTTPException(status_code=404, detail=f"客户 {customer_id} 不存在")
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e
