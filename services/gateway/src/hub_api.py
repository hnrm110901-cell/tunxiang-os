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


# ─── Customers 扩展 (Wave 2) ───


@router.get("/customers")
async def list_customers(
    status: Optional[str] = None,
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(get_db_no_rls),
):
    """客户列表（带健康分/ARR/门店数/NPS/续约日）"""
    try:
        data = await hub_service.hub_list_customers(db, status, page, size)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.get("/customers/{customer_id}")
async def get_customer(customer_id: str, db: AsyncSession = Depends(get_db_no_rls)):
    """客户详情"""
    try:
        data = await hub_service.hub_get_customer(db, customer_id)
        if not data:
            raise HTTPException(status_code=404, detail=f"客户 {customer_id} 不存在")
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.get("/customers/{customer_id}/playbooks")
async def customer_playbooks(customer_id: str, db: AsyncSession = Depends(get_db_no_rls)):
    """客户订阅的 Playbook 列表"""
    try:
        data = await hub_service.hub_customer_playbooks(db, customer_id)
        if data is None:
            raise HTTPException(status_code=404, detail=f"客户 {customer_id} 不存在")
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.post("/customers/{customer_id}/playbooks/{playbook_id}/run")
async def run_customer_playbook(
    customer_id: str,
    playbook_id: str,
    db: AsyncSession = Depends(get_db_no_rls),
):
    """手动触发客户 Playbook"""
    try:
        data = await hub_service.hub_run_customer_playbook(db, customer_id, playbook_id)
        if not data:
            raise HTTPException(status_code=404, detail=f"客户 {customer_id} 不存在")
        if data.get("error") == "playbook_not_found":
            raise HTTPException(status_code=404, detail=f"Playbook {playbook_id} 不存在")
        logger.info(
            "hub.customer.playbook.run",
            customer_id=customer_id,
            playbook_id=playbook_id,
        )
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.get("/customers/{customer_id}/journey")
async def customer_journey(customer_id: str, db: AsyncSession = Depends(get_db_no_rls)):
    """客户旅程阶段"""
    try:
        data = await hub_service.hub_customer_journey(db, customer_id)
        if not data:
            raise HTTPException(status_code=404, detail=f"客户 {customer_id} 不存在")
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


# ─── Incidents 事件响应 ───


class CreateIncidentBody(BaseModel):
    title: str = Field(..., min_length=1)
    priority: str = Field(..., pattern="^(P0|P1|P2)$")
    description: str = Field(..., min_length=1)
    affected_services: list[str] = Field(default_factory=list)
    affected_customers: list[str] = Field(default_factory=list)


class UpdateIncidentBody(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = Field(None, pattern="^(P0|P1|P2)$")
    commander: Optional[str] = None


@router.get("/incidents")
async def list_incidents(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(get_db_no_rls),
):
    """Incident 列表（status/priority 过滤）"""
    try:
        data = await hub_service.hub_list_incidents(db, priority, status, page, size)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.post("/incidents")
async def create_incident(
    body: CreateIncidentBody,
    db: AsyncSession = Depends(get_db_no_rls),
):
    """声明新 Incident"""
    try:
        data = await hub_service.hub_create_incident(db, body.model_dump())
        logger.info(
            "hub.incident.create",
            title=body.title,
            priority=body.priority,
        )
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.get("/incidents/{incident_id}")
async def get_incident(incident_id: str, db: AsyncSession = Depends(get_db_no_rls)):
    """Incident 详情"""
    try:
        data = await hub_service.hub_get_incident(db, incident_id)
        if not data:
            raise HTTPException(status_code=404, detail=f"Incident {incident_id} 不存在")
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.patch("/incidents/{incident_id}")
async def update_incident(
    incident_id: str,
    body: UpdateIncidentBody,
    db: AsyncSession = Depends(get_db_no_rls),
):
    """更新 Incident（状态/优先级/指挥官）"""
    try:
        data = await hub_service.hub_update_incident(
            db, incident_id, body.model_dump(exclude_none=True),
        )
        if not data:
            raise HTTPException(status_code=404, detail=f"Incident {incident_id} 不存在")
        logger.info(
            "hub.incident.update",
            incident_id=incident_id,
            updates=body.model_dump(exclude_none=True),
        )
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.get("/incidents/{incident_id}/timeline")
async def incident_timeline(incident_id: str, db: AsyncSession = Depends(get_db_no_rls)):
    """Incident 时间线"""
    try:
        data = await hub_service.hub_incident_timeline(db, incident_id)
        if data is None:
            raise HTTPException(status_code=404, detail=f"Incident {incident_id} 不存在")
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.post("/incidents/{incident_id}/postmortem")
async def incident_postmortem(incident_id: str, db: AsyncSession = Depends(get_db_no_rls)):
    """生成 Postmortem 草稿"""
    try:
        data = await hub_service.hub_incident_postmortem(db, incident_id)
        if not data:
            raise HTTPException(status_code=404, detail=f"Incident {incident_id} 不存在")
        logger.info("hub.incident.postmortem", incident_id=incident_id)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


# ─── Migrations 迁移管理 ───


class CreateMigrationBody(BaseModel):
    name: str = Field(..., min_length=1)
    source_system: str = Field(..., min_length=1)
    merchant_id: str = Field(..., min_length=1)
    engineer: str = Field(..., min_length=1)


@router.get("/migrations")
async def list_migrations(
    status: Optional[str] = None,
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(get_db_no_rls),
):
    """迁移项目列表"""
    try:
        data = await hub_service.hub_list_migrations(db, status, page, size)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.post("/migrations")
async def create_migration(
    body: CreateMigrationBody,
    db: AsyncSession = Depends(get_db_no_rls),
):
    """创建迁移项目"""
    try:
        data = await hub_service.hub_create_migration(db, body.model_dump())
        logger.info(
            "hub.migration.create",
            name=body.name,
            source_system=body.source_system,
            merchant_id=body.merchant_id,
        )
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.get("/migrations/{migration_id}")
async def get_migration(migration_id: str, db: AsyncSession = Depends(get_db_no_rls)):
    """迁移详情（含五阶段进度）"""
    try:
        data = await hub_service.hub_get_migration(db, migration_id)
        if not data:
            raise HTTPException(status_code=404, detail=f"迁移项目 {migration_id} 不存在")
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.patch("/migrations/{migration_id}/advance")
async def advance_migration(migration_id: str, db: AsyncSession = Depends(get_db_no_rls)):
    """推进迁移到下一阶段"""
    try:
        data = await hub_service.hub_advance_migration(db, migration_id)
        if not data:
            raise HTTPException(status_code=404, detail=f"迁移项目 {migration_id} 不存在")
        if data.get("error"):
            raise HTTPException(status_code=409, detail=data.get("reason", data["error"]))
        logger.info("hub.migration.advance", migration_id=migration_id)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.post("/migrations/{migration_id}/rollback")
async def rollback_migration(migration_id: str, db: AsyncSession = Depends(get_db_no_rls)):
    """回滚迁移到上一检查点"""
    try:
        data = await hub_service.hub_rollback_migration(db, migration_id)
        if not data:
            raise HTTPException(status_code=404, detail=f"迁移项目 {migration_id} 不存在")
        if data.get("error"):
            raise HTTPException(status_code=409, detail=data.get("reason", data["error"]))
        logger.info("hub.migration.rollback", migration_id=migration_id)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.post("/migrations/{migration_id}/pause")
async def pause_migration(migration_id: str, db: AsyncSession = Depends(get_db_no_rls)):
    """暂停迁移"""
    try:
        data = await hub_service.hub_pause_migration(db, migration_id)
        if not data:
            raise HTTPException(status_code=404, detail=f"迁移项目 {migration_id} 不存在")
        if data.get("error"):
            raise HTTPException(status_code=409, detail=data.get("error"))
        logger.info("hub.migration.pause", migration_id=migration_id)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.post("/migrations/{migration_id}/resume")
async def resume_migration(migration_id: str, db: AsyncSession = Depends(get_db_no_rls)):
    """恢复迁移"""
    try:
        data = await hub_service.hub_resume_migration(db, migration_id)
        if not data:
            raise HTTPException(status_code=404, detail=f"迁移项目 {migration_id} 不存在")
        if data.get("error"):
            raise HTTPException(status_code=409, detail=data.get("reason", data.get("error")))
        logger.info("hub.migration.resume", migration_id=migration_id)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


# ─── Adapters 扩展 ───
# 注意：/adapters/matrix 必须在 /adapters/{id} 前面，避免路由冲突


@router.get("/adapters/matrix")
async def adapters_matrix(db: AsyncSession = Depends(get_db_no_rls)):
    """适配器 x 商户状态矩阵（15适配器 x 10商户）"""
    try:
        data = await hub_service.hub_adapters_matrix(db)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.get("/adapters/{adapter_id}")
async def get_adapter(adapter_id: str, db: AsyncSession = Depends(get_db_no_rls)):
    """适配器详情"""
    try:
        data = await hub_service.hub_get_adapter(db, adapter_id)
        if not data:
            raise HTTPException(status_code=404, detail=f"适配器 {adapter_id} 不存在")
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.get("/adapters/{adapter_id}/mapping")
async def adapter_mapping(adapter_id: str, db: AsyncSession = Depends(get_db_no_rls)):
    """适配器字段映射配置"""
    try:
        data = await hub_service.hub_adapter_mapping(db, adapter_id)
        if not data:
            raise HTTPException(status_code=404, detail=f"适配器 {adapter_id} 不存在")
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.get("/adapters/{adapter_id}/timeline")
async def adapter_timeline(adapter_id: str, db: AsyncSession = Depends(get_db_no_rls)):
    """适配器事件时间线"""
    try:
        data = await hub_service.hub_adapter_timeline(db, adapter_id)
        if data is None:
            raise HTTPException(status_code=404, detail=f"适配器 {adapter_id} 不存在")
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.post("/adapters/{adapter_id}/sync")
async def adapter_sync(adapter_id: str, db: AsyncSession = Depends(get_db_no_rls)):
    """手动触发适配器同步"""
    try:
        data = await hub_service.hub_adapter_sync(db, adapter_id)
        if not data:
            raise HTTPException(status_code=404, detail=f"适配器 {adapter_id} 不存在")
        logger.info("hub.adapter.sync", adapter_id=adapter_id)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


# ─── Playbooks 剧本库 ───


class RunPlaybookBody(BaseModel):
    target_id: str = Field(..., min_length=1)
    target_type: str = Field(..., min_length=1)


@router.get("/playbooks")
async def list_playbooks(db: AsyncSession = Depends(get_db_no_rls)):
    """剧本库列表"""
    try:
        data = await hub_service.hub_list_playbooks(db)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.get("/playbooks/{playbook_id}")
async def get_playbook(playbook_id: str, db: AsyncSession = Depends(get_db_no_rls)):
    """剧本详情"""
    try:
        data = await hub_service.hub_get_playbook(db, playbook_id)
        if not data:
            raise HTTPException(status_code=404, detail=f"Playbook {playbook_id} 不存在")
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.post("/playbooks/{playbook_id}/run")
async def run_playbook(
    playbook_id: str,
    body: RunPlaybookBody,
    db: AsyncSession = Depends(get_db_no_rls),
):
    """触发 Playbook 执行"""
    try:
        data = await hub_service.hub_run_playbook(
            db, playbook_id, body.target_id, body.target_type,
        )
        if not data:
            raise HTTPException(status_code=404, detail=f"Playbook {playbook_id} 不存在")
        logger.info(
            "hub.playbook.run",
            playbook_id=playbook_id,
            target_id=body.target_id,
            target_type=body.target_type,
        )
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.get("/playbooks/{playbook_id}/runs")
async def playbook_runs(playbook_id: str, db: AsyncSession = Depends(get_db_no_rls)):
    """Playbook 执行历史"""
    try:
        data = await hub_service.hub_playbook_runs(db, playbook_id)
        if data is None:
            raise HTTPException(status_code=404, detail=f"Playbook {playbook_id} 不存在")
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


# ─── Wave 3: Settings API ───


@router.get("/settings/flags")
async def list_flags(db: AsyncSession = Depends(get_db_no_rls)):
    """所有 feature flags"""
    try:
        data = await hub_service.hub_list_flags(db)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


class UpdateFlagBody(BaseModel):
    value: bool
    rollout_pct: Optional[int] = Field(None, ge=0, le=100)


@router.patch("/settings/flags/{name}")
async def update_flag(
    name: str,
    body: UpdateFlagBody,
    db: AsyncSession = Depends(get_db_no_rls),
):
    """更新 flag 值"""
    try:
        data = await hub_service.hub_update_flag(db, name, body.value, body.rollout_pct)
        if not data:
            raise HTTPException(status_code=404, detail=f"Flag {name} 不存在")
        logger.info("hub.settings.flag.update", name=name, value=body.value, rollout_pct=body.rollout_pct)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.get("/settings/releases")
async def list_releases(db: AsyncSession = Depends(get_db_no_rls)):
    """各环境发布状态"""
    try:
        data = await hub_service.hub_list_releases(db)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


class DeployBody(BaseModel):
    app: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    env: str = Field(..., pattern="^(dev|test|uat|pilot|prod)$")


@router.post("/settings/releases/deploy")
async def deploy_release(
    body: DeployBody,
    db: AsyncSession = Depends(get_db_no_rls),
):
    """触发部署"""
    try:
        data = await hub_service.hub_deploy_release(db, body.app, body.version, body.env)
        logger.info("hub.settings.deploy", app=body.app, version=body.version, env=body.env)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.get("/settings/security/users")
async def list_security_users(db: AsyncSession = Depends(get_db_no_rls)):
    """用户列表"""
    try:
        data = await hub_service.hub_list_security_users(db)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.get("/settings/security/roles")
async def list_security_roles(db: AsyncSession = Depends(get_db_no_rls)):
    """角色列表"""
    try:
        data = await hub_service.hub_list_security_roles(db)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.get("/settings/security/audit")
async def list_audit_logs(db: AsyncSession = Depends(get_db_no_rls)):
    """审计日志"""
    try:
        data = await hub_service.hub_list_audit_logs(db)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.get("/settings/knowledge")
async def list_knowledge(db: AsyncSession = Depends(get_db_no_rls)):
    """知识库文档列表"""
    try:
        data = await hub_service.hub_list_knowledge(db)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


class KnowledgeSearchBody(BaseModel):
    query: str = Field(..., min_length=1, max_length=512)
    top_k: int = Field(default=5, ge=1, le=20)


@router.post("/settings/knowledge/search")
async def search_knowledge(body: KnowledgeSearchBody, db: AsyncSession = Depends(get_db_no_rls)):
    """RAG 搜索"""
    try:
        data = await hub_service.hub_search_knowledge(db, body.query, body.top_k)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.get("/settings/tenancy")
async def list_tenancy(db: AsyncSession = Depends(get_db_no_rls)):
    """租户列表+统计"""
    try:
        data = await hub_service.hub_list_tenancy(db)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


# ─── Wave 3: Workbench API ───


class ExecuteCommandBody(BaseModel):
    command: str = Field(..., min_length=1, max_length=2048)


@router.post("/workbench/execute")
async def workbench_execute(body: ExecuteCommandBody, db: AsyncSession = Depends(get_db_no_rls)):
    """执行命令"""
    try:
        data = await hub_service.hub_workbench_execute(db, body.command)
        logger.info("hub.workbench.execute", command=body.command[:80])
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


# ─── Wave 3: Journey API ───


@router.get("/journeys")
async def list_journeys(db: AsyncSession = Depends(get_db_no_rls)):
    """Journey 模板列表"""
    try:
        data = await hub_service.hub_list_journeys(db)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.get("/journeys/{journey_id}")
async def get_journey(journey_id: str, db: AsyncSession = Depends(get_db_no_rls)):
    """Journey 详情（含节点+连线）"""
    try:
        data = await hub_service.hub_get_journey(db, journey_id)
        if not data:
            raise HTTPException(status_code=404, detail=f"Journey {journey_id} 不存在")
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


class SaveJourneyBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)


@router.put("/journeys/{journey_id}")
async def save_journey(
    journey_id: str,
    body: SaveJourneyBody,
    db: AsyncSession = Depends(get_db_no_rls),
):
    """保存 Journey"""
    try:
        data = await hub_service.hub_save_journey(db, journey_id, body.model_dump())
        logger.info("hub.journey.save", journey_id=journey_id, name=body.name, nodes=len(body.nodes))
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


class RunJourneyBody(BaseModel):
    customer_id: str = Field(..., min_length=1)


@router.post("/journeys/{journey_id}/run")
async def run_journey(
    journey_id: str,
    body: RunJourneyBody,
    db: AsyncSession = Depends(get_db_no_rls),
):
    """为客户启动 Journey"""
    try:
        data = await hub_service.hub_run_journey(db, journey_id, body.customer_id)
        if not data:
            raise HTTPException(status_code=404, detail=f"Journey {journey_id} 不存在")
        logger.info("hub.journey.run", journey_id=journey_id, customer_id=body.customer_id)
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e


@router.get("/journeys/{journey_id}/instances")
async def list_journey_instances(journey_id: str, db: AsyncSession = Depends(get_db_no_rls)):
    """运行实例列表"""
    try:
        data = await hub_service.hub_list_journey_instances(db, journey_id)
        if data is None:
            raise HTTPException(status_code=404, detail=f"Journey {journey_id} 不存在")
        return {"ok": True, "data": data}
    except ProgrammingError as e:
        raise _pg_unavailable(e) from e
