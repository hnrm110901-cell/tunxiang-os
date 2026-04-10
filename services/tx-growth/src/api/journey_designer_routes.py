"""客户旅程编排 API 路由

前缀: /api/v1/growth/journeys

端点:
  GET   /                      — 旅程列表
  GET   /{journey_id}          — 旅程详情（含节点）
  POST  /                      — 创建旅程
  PUT   /{journey_id}          — 更新旅程
  PATCH /{journey_id}/status   — 启动/暂停/结束
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/growth/journeys", tags=["journey-designer"])


# ─── Mock 数据 ───────────────────────────────────────────────

_MOCK_JOURNEYS: dict[str, dict[str, Any]] = {
    "j001": {
        "journey_id": "j001",
        "name": "新客首次到店欢迎旅程",
        "description": "新客首次消费后自动触发，引导注册会员、领券、储值",
        "status": "running",
        "trigger": {"event": "order.paid", "conditions": [{"field": "is_first_visit", "operator": "eq", "value": True}]},
        "target_segment": "新客",
        "enrolled_count": 4218,
        "completed_count": 3500,
        "conversion_rate": 0.83,
        "nodes": [
            {"node_id": "n1", "type": "trigger", "name": "首次消费", "config": {"event": "order.paid"}, "position": {"x": 100, "y": 200}, "next_nodes": ["n2"]},
            {"node_id": "n2", "type": "delay", "name": "等待30分钟", "config": {"duration_minutes": 30}, "position": {"x": 300, "y": 200}, "next_nodes": ["n3"]},
            {"node_id": "n3", "type": "action", "name": "发送欢迎短信", "config": {"channel": "sms", "template": "welcome_new"}, "position": {"x": 500, "y": 200}, "next_nodes": ["n4"]},
            {"node_id": "n4", "type": "condition", "name": "是否已注册会员", "config": {"field": "is_member", "operator": "eq", "value": True}, "position": {"x": 700, "y": 200}, "next_nodes": ["n5", "n6"]},
            {"node_id": "n5", "type": "action", "name": "推送新客券", "config": {"channel": "wechat", "coupon_id": "c001"}, "position": {"x": 900, "y": 100}, "next_nodes": []},
            {"node_id": "n6", "type": "action", "name": "推送注册引导", "config": {"channel": "sms", "template": "register_guide"}, "position": {"x": 900, "y": 300}, "next_nodes": []},
        ],
        "created_at": "2026-01-15T10:00:00Z",
        "updated_at": "2026-04-01T15:30:00Z",
        "created_by": "admin",
    },
    "j002": {
        "journey_id": "j002",
        "name": "沉默客户唤醒旅程",
        "description": "30天未到店的会员，通过多触点逐步唤醒",
        "status": "running",
        "trigger": {"event": "member.dormant", "conditions": [{"field": "days_since_last_visit", "operator": "gte", "value": 30}]},
        "target_segment": "沉默预警",
        "enrolled_count": 8600,
        "completed_count": 5200,
        "conversion_rate": 0.38,
        "nodes": [
            {"node_id": "n1", "type": "trigger", "name": "30天未到店", "config": {"event": "member.dormant"}, "position": {"x": 100, "y": 200}, "next_nodes": ["n2"]},
            {"node_id": "n2", "type": "action", "name": "发送唤醒短信", "config": {"channel": "sms", "template": "dormant_recall_1"}, "position": {"x": 300, "y": 200}, "next_nodes": ["n3"]},
            {"node_id": "n3", "type": "delay", "name": "等待3天", "config": {"duration_minutes": 4320}, "position": {"x": 500, "y": 200}, "next_nodes": ["n4"]},
            {"node_id": "n4", "type": "condition", "name": "是否回访", "config": {"field": "has_visited", "operator": "eq", "value": True}, "position": {"x": 700, "y": 200}, "next_nodes": ["n5", "n6"]},
            {"node_id": "n5", "type": "action", "name": "发送感谢", "config": {"channel": "wechat", "template": "thank_you"}, "position": {"x": 900, "y": 100}, "next_nodes": []},
            {"node_id": "n6", "type": "action", "name": "推送大额券", "config": {"channel": "sms", "coupon_id": "c005"}, "position": {"x": 900, "y": 300}, "next_nodes": ["n7"]},
            {"node_id": "n7", "type": "delay", "name": "等待7天", "config": {"duration_minutes": 10080}, "position": {"x": 1100, "y": 300}, "next_nodes": ["n8"]},
            {"node_id": "n8", "type": "action", "name": "人工跟进", "config": {"channel": "task", "assign_to": "store_manager"}, "position": {"x": 1300, "y": 300}, "next_nodes": []},
        ],
        "created_at": "2026-02-01T10:00:00Z",
        "updated_at": "2026-03-20T14:00:00Z",
        "created_by": "admin",
    },
    "j003": {
        "journey_id": "j003",
        "name": "生日关怀旅程",
        "description": "会员生日前3天触发，包含祝福、专属券、生日特权提醒",
        "status": "running",
        "trigger": {"event": "member.birthday_approaching", "conditions": [{"field": "days_to_birthday", "operator": "lte", "value": 3}]},
        "target_segment": "全部会员",
        "enrolled_count": 12000,
        "completed_count": 10800,
        "conversion_rate": 0.72,
        "nodes": [
            {"node_id": "n1", "type": "trigger", "name": "生日前3天", "config": {"event": "member.birthday_approaching"}, "position": {"x": 100, "y": 200}, "next_nodes": ["n2"]},
            {"node_id": "n2", "type": "action", "name": "发送生日祝福", "config": {"channel": "wechat", "template": "birthday_wish"}, "position": {"x": 300, "y": 200}, "next_nodes": ["n3"]},
            {"node_id": "n3", "type": "action", "name": "发放生日券", "config": {"channel": "system", "coupon_id": "c004"}, "position": {"x": 500, "y": 200}, "next_nodes": ["n4"]},
            {"node_id": "n4", "type": "delay", "name": "生日当天", "config": {"duration_minutes": 4320}, "position": {"x": 700, "y": 200}, "next_nodes": ["n5"]},
            {"node_id": "n5", "type": "action", "name": "生日当天提醒", "config": {"channel": "sms", "template": "birthday_day"}, "position": {"x": 900, "y": 200}, "next_nodes": []},
        ],
        "created_at": "2026-01-10T10:00:00Z",
        "updated_at": "2026-01-10T10:00:00Z",
        "created_by": "admin",
    },
    "j004": {
        "journey_id": "j004",
        "name": "高价值客户培育旅程",
        "description": "识别消费潜力高的客户，通过VIP服务逐步提升消费频次和客单",
        "status": "paused",
        "trigger": {"event": "member.rfm_upgraded", "conditions": [{"field": "rfm_code", "operator": "in", "value": ["101", "110"]}]},
        "target_segment": "重要发展客户",
        "enrolled_count": 3200,
        "completed_count": 1800,
        "conversion_rate": 0.45,
        "nodes": [
            {"node_id": "n1", "type": "trigger", "name": "RFM升级", "config": {"event": "member.rfm_upgraded"}, "position": {"x": 100, "y": 200}, "next_nodes": ["n2"]},
            {"node_id": "n2", "type": "action", "name": "分配专属顾问", "config": {"channel": "task", "assign_to": "vip_advisor"}, "position": {"x": 300, "y": 200}, "next_nodes": ["n3"]},
            {"node_id": "n3", "type": "action", "name": "推送VIP权益", "config": {"channel": "wechat", "template": "vip_benefits"}, "position": {"x": 500, "y": 200}, "next_nodes": ["n4"]},
            {"node_id": "n4", "type": "delay", "name": "等待7天", "config": {"duration_minutes": 10080}, "position": {"x": 700, "y": 200}, "next_nodes": ["n5"]},
            {"node_id": "n5", "type": "action", "name": "邀请品鉴活动", "config": {"channel": "sms", "template": "vip_tasting_invite"}, "position": {"x": 900, "y": 200}, "next_nodes": []},
        ],
        "created_at": "2026-03-01T10:00:00Z",
        "updated_at": "2026-04-05T09:00:00Z",
        "created_by": "admin",
    },
    "j005": {
        "journey_id": "j005",
        "name": "宴席后续跟进旅程",
        "description": "宴席结束后自动跟进，收集反馈、推荐下次预订",
        "status": "draft",
        "trigger": {"event": "banquet.completed", "conditions": []},
        "target_segment": "宴席客户",
        "enrolled_count": 0,
        "completed_count": 0,
        "conversion_rate": 0.0,
        "nodes": [
            {"node_id": "n1", "type": "trigger", "name": "宴席结束", "config": {"event": "banquet.completed"}, "position": {"x": 100, "y": 200}, "next_nodes": ["n2"]},
            {"node_id": "n2", "type": "delay", "name": "等待2小时", "config": {"duration_minutes": 120}, "position": {"x": 300, "y": 200}, "next_nodes": ["n3"]},
            {"node_id": "n3", "type": "action", "name": "发送感谢+评价邀请", "config": {"channel": "sms", "template": "banquet_feedback"}, "position": {"x": 500, "y": 200}, "next_nodes": ["n4"]},
            {"node_id": "n4", "type": "delay", "name": "等待30天", "config": {"duration_minutes": 43200}, "position": {"x": 700, "y": 200}, "next_nodes": ["n5"]},
            {"node_id": "n5", "type": "action", "name": "推送下次宴席优惠", "config": {"channel": "wechat", "template": "banquet_promo"}, "position": {"x": 900, "y": 200}, "next_nodes": []},
        ],
        "created_at": "2026-04-08T10:00:00Z",
        "updated_at": "2026-04-08T10:00:00Z",
        "created_by": "admin",
    },
}


# ─── 请求模型 ────────────────────────────────────────────────

class JourneyNodeConfig(BaseModel):
    node_id: str = Field(..., description="节点唯一ID")
    type: str = Field(..., description="节点类型: trigger/delay/condition/action")
    name: str = Field(..., description="节点名称")
    config: dict = Field(default_factory=dict, description="节点配置")
    position: dict = Field(default_factory=lambda: {"x": 0, "y": 0}, description="画布位置")
    next_nodes: list[str] = Field(default_factory=list, description="后续节点ID列表")


class CreateJourneyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="旅程名称")
    description: Optional[str] = None
    trigger: dict = Field(..., description="触发条件配置")
    target_segment: Optional[str] = Field(None, description="目标人群")
    nodes: list[JourneyNodeConfig] = Field(..., min_length=1, description="旅程节点列表")


class UpdateJourneyRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=100, description="旅程名称")
    description: Optional[str] = None
    trigger: Optional[dict] = None
    target_segment: Optional[str] = None
    nodes: Optional[list[JourneyNodeConfig]] = None


class StatusChangeRequest(BaseModel):
    action: str = Field(..., description="操作: start/pause/stop")


# ─── 辅助函数 ────────────────────────────────────────────────

def _require_tenant(x_tenant_id: Optional[str]) -> uuid.UUID:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-ID must be a valid UUID")


def ok(data: Any) -> dict:
    return {"ok": True, "data": data}


# ─── 端点 ────────────────────────────────────────────────────

@router.get("/")
async def list_journeys(
    status: Optional[str] = Query(None, description="状态筛选: draft/running/paused/stopped"),
    keyword: Optional[str] = Query(None, description="名称搜索"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """旅程列表"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("list_journeys", tenant_id=str(tenant_id), status=status)

    items = list(_MOCK_JOURNEYS.values())
    if status:
        items = [j for j in items if j["status"] == status]
    if keyword:
        items = [j for j in items if keyword in j["name"] or keyword in (j.get("description") or "")]

    # 列表不返回 nodes 详情
    list_items = []
    for j in items:
        item = {k: v for k, v in j.items() if k != "nodes"}
        item["node_count"] = len(j.get("nodes", []))
        list_items.append(item)

    total = len(list_items)
    offset = (page - 1) * size
    paged = list_items[offset: offset + size]

    return ok({
        "items": paged,
        "total": total,
        "page": page,
        "size": size,
    })


@router.get("/{journey_id}")
async def get_journey(
    journey_id: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """旅程详情（含节点定义）"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("get_journey", tenant_id=str(tenant_id), journey_id=journey_id)

    journey = _MOCK_JOURNEYS.get(journey_id)
    if not journey:
        raise HTTPException(status_code=404, detail=f"旅程不存在: {journey_id}")

    return ok(journey)


@router.post("/")
async def create_journey(
    body: CreateJourneyRequest,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """创建旅程"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("create_journey", tenant_id=str(tenant_id), name=body.name)

    journey_id = f"j{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()

    new_journey = {
        "journey_id": journey_id,
        "name": body.name,
        "description": body.description,
        "status": "draft",
        "trigger": body.trigger,
        "target_segment": body.target_segment,
        "enrolled_count": 0,
        "completed_count": 0,
        "conversion_rate": 0.0,
        "nodes": [n.model_dump() for n in body.nodes],
        "created_at": now,
        "updated_at": now,
        "created_by": "current_user",
    }

    return ok(new_journey)


@router.put("/{journey_id}")
async def update_journey(
    journey_id: str,
    body: UpdateJourneyRequest,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """更新旅程（运行中的旅程不允许修改节点）"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("update_journey", tenant_id=str(tenant_id), journey_id=journey_id)

    journey = _MOCK_JOURNEYS.get(journey_id)
    if not journey:
        raise HTTPException(status_code=404, detail=f"旅程不存在: {journey_id}")

    if journey["status"] == "running" and body.nodes is not None:
        raise HTTPException(
            status_code=422,
            detail="运行中的旅程不允许修改节点，请先暂停",
        )

    # Mock: 构建更新后的数据
    updated = dict(journey)
    if body.name is not None:
        updated["name"] = body.name
    if body.description is not None:
        updated["description"] = body.description
    if body.trigger is not None:
        updated["trigger"] = body.trigger
    if body.target_segment is not None:
        updated["target_segment"] = body.target_segment
    if body.nodes is not None:
        updated["nodes"] = [n.model_dump() for n in body.nodes]
    updated["updated_at"] = datetime.now(timezone.utc).isoformat()

    return ok(updated)


@router.patch("/{journey_id}/status")
async def change_journey_status(
    journey_id: str,
    body: StatusChangeRequest,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """启动/暂停/结束旅程"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info(
        "change_journey_status",
        tenant_id=str(tenant_id),
        journey_id=journey_id,
        action=body.action,
    )

    journey = _MOCK_JOURNEYS.get(journey_id)
    if not journey:
        raise HTTPException(status_code=404, detail=f"旅程不存在: {journey_id}")

    valid_transitions = {
        "start": {"draft", "paused"},
        "pause": {"running"},
        "stop": {"running", "paused"},
    }

    if body.action not in valid_transitions:
        raise HTTPException(
            status_code=422,
            detail=f"无效操作: {body.action}，可用操作: start/pause/stop",
        )

    current_status = journey["status"]
    allowed_from = valid_transitions[body.action]
    if current_status not in allowed_from:
        raise HTTPException(
            status_code=422,
            detail=f"当前状态 {current_status} 不允许执行 {body.action}，"
                   f"要求状态: {', '.join(sorted(allowed_from))}",
        )

    new_status_map = {"start": "running", "pause": "paused", "stop": "stopped"}
    new_status = new_status_map[body.action]

    return ok({
        "journey_id": journey_id,
        "previous_status": current_status,
        "current_status": new_status,
        "action": body.action,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
