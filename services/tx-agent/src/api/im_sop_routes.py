"""Phase S2: IM全闭环 — API路由

SOP <-> IM双向桥接端点。
路由前缀: /api/v1/agent/im-sop

端点：
  POST /push/task-card        — 推送任务卡
  POST /push/alert-card       — 推送预警卡
  POST /push/coaching-card    — 推送教练卡
  POST /push/corrective-card  — 推送纠正卡
  POST /callback              — IM回调处理
  POST /photo-upload          — 照片上传
  GET  /interactions           — 列出交互记录（分页）
  GET  /quick-actions          — 列出快捷操作
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from services.tx_agent.src.services.im_sop_bridge_service import (
    IMSOPBridgeService,
)
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/agent/im-sop", tags=["im-sop"])


# ══════════════════════════════════════════════
# Pydantic 请求/响应模型
# ══════════════════════════════════════════════


# ── 通用 ──

class OkResponse(BaseModel):
    ok: bool
    data: dict | None = None
    error: dict | None = None


# ── 推送请求 ──

class TaskItem(BaseModel):
    """任务列表项"""
    task_name: str = Field(..., description="任务名称")
    status: str = Field("pending", description="任务状态")
    priority: str = Field("normal", description="优先级")
    due_at: str | None = Field(None, description="截止时间ISO格式")
    instance_id: str | None = Field(None, description="任务实例ID")
    task_code: str | None = Field(None, description="任务代码")


class PushTaskCardRequest(BaseModel):
    """推送任务卡请求"""
    store_id: str = Field(..., description="门店ID")
    user_id: str = Field(..., description="接收人ID")
    slot_name: str = Field(..., description="时段名称")
    tasks: list[TaskItem] = Field(..., description="任务列表", min_length=1)
    ai_insight: str | None = Field(None, description="AI智能洞察")
    channel: str = Field("wecom", description="IM通道: wecom/dingtalk/feishu")


class PushAlertCardRequest(BaseModel):
    """推送预警卡请求"""
    store_id: str = Field(..., description="门店ID")
    user_id: str = Field(..., description="接收人ID")
    alert_type: str = Field(
        ..., description="预警类型: overdue/violation/anomaly/threshold"
    )
    anomalies: list[dict] = Field(
        ...,
        description="异常列表 [{title, description, severity}]",
        min_length=1,
    )
    analysis: str | None = Field(None, description="AI分析结论")
    channel: str = Field("wecom", description="IM通道")


class CoachingContent(BaseModel):
    """教练内容"""
    title: str | None = Field(None, description="标题")
    summary: str | None = Field(None, description="摘要")
    metrics: dict | None = Field(None, description="指标数据")
    suggestions: list[str] | None = Field(None, description="建议列表")
    highlights: list[str] | None = Field(None, description="亮点")
    issues: list[str] | None = Field(None, description="问题")


class PushCoachingCardRequest(BaseModel):
    """推送教练卡请求"""
    store_id: str = Field(..., description="门店ID")
    user_id: str = Field(..., description="接收人ID")
    coaching_type: str = Field(
        ...,
        description="教练类型: morning_brief/slot_review/daily_report/tip",
    )
    content: CoachingContent = Field(..., description="教练内容")
    channel: str = Field("wecom", description="IM通道")


class CorrectiveActionDetail(BaseModel):
    """纠正动作详情"""
    id: str = Field(..., description="纠正动作ID")
    title: str = Field(..., description="标题")
    description: str = Field(..., description="描述")
    severity: str = Field("warning", description="严重程度")
    due_at: str | None = Field(None, description="截止时间")
    action_type: str | None = Field(None, description="动作类型")
    source_instance_id: str | None = Field(None, description="来源任务实例ID")


class PushCorrectiveCardRequest(BaseModel):
    """推送纠正卡请求"""
    store_id: str = Field(..., description="门店ID")
    user_id: str = Field(..., description="责任人ID")
    action: CorrectiveActionDetail = Field(..., description="纠正动作详情")
    channel: str = Field("wecom", description="IM通道")


# ── 回调请求 ──

class IMCallbackRequest(BaseModel):
    """IM回调请求"""
    store_id: str = Field(..., description="门店ID")
    user_id: str = Field(..., description="操作人ID")
    action_code: str = Field(..., description="操作代码")
    instance_id: str | None = Field(None, description="关联任务实例ID")
    action_id: str | None = Field(None, description="关联纠正动作ID")
    reply_to: str | None = Field(None, description="回复消息ID")
    note: str | None = Field(None, description="备注")
    extra: dict | None = Field(None, description="额外数据")


class PhotoUploadRequest(BaseModel):
    """照片上传请求"""
    store_id: str = Field(..., description="门店ID")
    user_id: str = Field(..., description="上传人ID")
    instance_id: str = Field(..., description="任务实例ID")
    photo_url: str = Field(..., description="照片URL")
    note: str | None = Field(None, description="备注")
    channel: str = Field("wecom", description="IM通道")


# ══════════════════════════════════════════════
# 依赖注入
# ══════════════════════════════════════════════

async def get_db() -> AsyncSession:
    """数据库会话依赖 — 由main.py中的lifespan注入"""
    # 占位：实际由 app.state.db_session_factory 注入
    raise NotImplementedError("DB session dependency not configured")


def _get_service(db: AsyncSession) -> IMSOPBridgeService:
    return IMSOPBridgeService(db)


def _require_tenant(x_tenant_id: str = Header(...)) -> str:
    """从请求头提取tenant_id"""
    return x_tenant_id


# ══════════════════════════════════════════════
# 推送端点
# ══════════════════════════════════════════════


@router.post("/push/task-card", response_model=OkResponse)
async def push_task_card(
    body: PushTaskCardRequest,
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    """推送SOP任务卡到IM

    将当前时段的SOP任务列表以卡片形式推送到指定IM通道。
    卡片包含任务清单、AI洞察和快捷操作按钮。
    """
    svc = _get_service(db)
    result = await svc.push_task_card(
        tenant_id=tenant_id,
        store_id=body.store_id,
        user_id=body.user_id,
        slot_name=body.slot_name,
        tasks=[t.model_dump() for t in body.tasks],
        ai_insight=body.ai_insight,
        channel=body.channel,
    )
    return OkResponse(ok=result.get("ok", False), data=result)


@router.post("/push/alert-card", response_model=OkResponse)
async def push_alert_card(
    body: PushAlertCardRequest,
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    """推送异常预警卡到IM

    当SOP执行检测到异常时，向负责人推送预警卡片。
    """
    svc = _get_service(db)
    result = await svc.push_alert_card(
        tenant_id=tenant_id,
        store_id=body.store_id,
        user_id=body.user_id,
        alert_type=body.alert_type,
        anomalies=body.anomalies,
        analysis=body.analysis,
        channel=body.channel,
    )
    return OkResponse(ok=result.get("ok", False), data=result)


@router.post("/push/coaching-card", response_model=OkResponse)
async def push_coaching_card(
    body: PushCoachingCardRequest,
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    """推送AI教练卡到IM

    推送晨报摘要、时段复盘、日报总结等教练内容。
    """
    svc = _get_service(db)
    result = await svc.push_coaching_card(
        tenant_id=tenant_id,
        store_id=body.store_id,
        user_id=body.user_id,
        coaching_type=body.coaching_type,
        content=body.content.model_dump(),
        channel=body.channel,
    )
    return OkResponse(ok=result.get("ok", False), data=result)


@router.post("/push/corrective-card", response_model=OkResponse)
async def push_corrective_card(
    body: PushCorrectiveCardRequest,
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    """推送纠正动作卡到IM

    当SOP任务不合规时，向责任人推送纠正卡片。
    """
    svc = _get_service(db)
    result = await svc.push_corrective_card(
        tenant_id=tenant_id,
        store_id=body.store_id,
        user_id=body.user_id,
        action=body.action.model_dump(),
        channel=body.channel,
    )
    return OkResponse(ok=result.get("ok", False), data=result)


# ══════════════════════════════════════════════
# 回调端点
# ══════════════════════════════════════════════


@router.post("/callback", response_model=OkResponse)
async def handle_im_callback(
    body: IMCallbackRequest,
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    """处理IM回调（快捷操作按钮点击）

    解析回调数据中的action_code，执行对应的快捷操作
    （一键确认/拍照上传/标记异常/呼叫支援/快速备注）。
    """
    svc = _get_service(db)
    result = await svc.handle_im_callback(
        tenant_id=tenant_id,
        store_id=body.store_id,
        user_id=body.user_id,
        callback_data={
            "action_code": body.action_code,
            "instance_id": body.instance_id,
            "action_id": body.action_id,
            "reply_to": body.reply_to,
            "note": body.note,
            "extra": body.extra or {},
        },
    )
    return OkResponse(ok=result.get("ok", False), data=result)


@router.post("/photo-upload", response_model=OkResponse)
async def handle_photo_upload(
    body: PhotoUploadRequest,
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    """处理IM照片上传（任务拍照确认）

    员工通过IM上传照片作为任务完成凭证。
    照片URL记录到交互日志，并关联到任务实例。
    """
    svc = _get_service(db)
    result = await svc.handle_photo_upload(
        tenant_id=tenant_id,
        store_id=body.store_id,
        user_id=body.user_id,
        instance_id=body.instance_id,
        photo_url=body.photo_url,
        note=body.note,
        channel=body.channel,
    )
    return OkResponse(ok=result.get("ok", False), data=result)


# ══════════════════════════════════════════════
# 查询端点
# ══════════════════════════════════════════════


@router.get("/interactions", response_model=OkResponse)
async def list_interactions(
    store_id: str = Query(..., description="门店ID"),
    user_id: str | None = Query(None, description="筛选用户ID"),
    direction: str | None = Query(None, description="筛选方向: outbound/inbound"),
    message_type: str | None = Query(None, description="筛选消息类型"),
    instance_id: str | None = Query(None, description="筛选关联任务实例"),
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(20, ge=1, le=100, description="每页条数"),
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    """列出IM交互记录（分页）

    查询指定门店的IM交互日志，支持按用户、方向、消息类型筛选。
    """
    svc = _get_service(db)
    result = await svc.list_interactions(
        tenant_id=tenant_id,
        store_id=store_id,
        user_id=user_id,
        direction=direction,
        message_type=message_type,
        instance_id=instance_id,
        page=page,
        size=size,
    )
    return OkResponse(ok=True, data=result)


@router.get("/quick-actions", response_model=OkResponse)
async def list_quick_actions(
    include_system: bool = Query(True, description="是否包含系统级通用操作"),
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    """列出所有快捷操作定义

    返回当前租户可用的快捷操作列表，包括系统级通用操作。
    """
    svc = _get_service(db)
    items = await svc.list_quick_actions(
        tenant_id=tenant_id,
        include_system=include_system,
    )
    return OkResponse(ok=True, data={"items": items, "total": len(items)})
