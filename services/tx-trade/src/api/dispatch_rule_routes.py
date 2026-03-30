"""档口路由规则管理 API

支持多品牌/多渠道/时段的档口路由规则增删改查，以及规则测试和路由模拟。

所有接口需要 X-Tenant-ID header。
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..models.dispatch_rule import DispatchRule
from ..models.production_dept import ProductionDept
from ..services.dispatch_rule_engine import dispatch_rule_engine, invalidate_store_cache

router = APIRouter(prefix="/api/v1/dispatch-rules", tags=["dispatch-rules"])
logger = structlog.get_logger()


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


# ─── 请求/响应模型 ───


class DispatchRuleCreate(BaseModel):
    name: str = Field(..., max_length=100, description="规则名称")
    priority: int = Field(0, description="优先级，越大越先匹配")

    match_dish_id: Optional[str] = Field(None, description="按菜品ID匹配（UUID字符串）")
    match_dish_category: Optional[str] = Field(None, max_length=50, description="按菜品分类匹配")
    match_brand_id: Optional[str] = Field(None, description="按品牌ID匹配（UUID字符串）")
    match_channel: Optional[str] = Field(
        None,
        description="按渠道匹配：dine_in/takeaway/delivery/reservation"
    )
    match_time_start: Optional[str] = Field(None, description="时段开始，格式 HH:MM，如 11:00")
    match_time_end: Optional[str] = Field(None, description="时段结束，格式 HH:MM，如 14:00")
    match_day_type: Optional[str] = Field(
        None,
        description="工作日类型：weekday/weekend/holiday"
    )

    target_dept_id: str = Field(..., description="目标档口ID（UUID字符串）")
    target_printer_id: Optional[str] = Field(None, description="覆盖打印机ID（可选）")
    is_active: bool = Field(True, description="是否启用")


class DispatchRuleUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    priority: Optional[int] = None

    match_dish_id: Optional[str] = None
    match_dish_category: Optional[str] = Field(None, max_length=50)
    match_brand_id: Optional[str] = None
    match_channel: Optional[str] = None
    match_time_start: Optional[str] = None
    match_time_end: Optional[str] = None
    match_day_type: Optional[str] = None

    target_dept_id: Optional[str] = None
    target_printer_id: Optional[str] = None
    is_active: Optional[bool] = None


class RuleTestRequest(BaseModel):
    dish_id: Optional[str] = Field(None, description="测试菜品ID")
    dish_category: Optional[str] = Field(None, description="测试菜品分类")
    brand_id: Optional[str] = Field(None, description="测试品牌ID")
    channel: Optional[str] = Field(None, description="测试渠道")
    order_time: Optional[str] = Field(None, description="测试时间（ISO8601），默认当前时间")


class SimulateRequest(BaseModel):
    dish_id: str = Field(..., description="菜品ID")
    dish_category: Optional[str] = Field(None, description="菜品分类")
    brand_id: Optional[str] = Field(None, description="品牌ID")
    channel: Optional[str] = Field(None, description="渠道")
    order_time: Optional[str] = Field(None, description="下单时间（ISO8601）")


def _parse_time(val: Optional[str]):
    """解析 HH:MM 格式的时间字符串。"""
    if val is None:
        return None
    from datetime import time as _time
    try:
        h, m = val.split(":")
        return _time(int(h), int(m))
    except (ValueError, AttributeError) as exc:
        raise HTTPException(status_code=400, detail=f"时间格式错误 '{val}'，应为 HH:MM") from exc


def _rule_to_dict(rule: DispatchRule) -> dict:
    return {
        "id": str(rule.id),
        "name": rule.name,
        "priority": rule.priority,
        "match_dish_id": str(rule.match_dish_id) if rule.match_dish_id else None,
        "match_dish_category": rule.match_dish_category,
        "match_brand_id": str(rule.match_brand_id) if rule.match_brand_id else None,
        "match_channel": rule.match_channel,
        "match_time_start": rule.match_time_start.strftime("%H:%M") if rule.match_time_start else None,
        "match_time_end": rule.match_time_end.strftime("%H:%M") if rule.match_time_end else None,
        "match_day_type": rule.match_day_type,
        "target_dept_id": str(rule.target_dept_id),
        "target_printer_id": str(rule.target_printer_id) if rule.target_printer_id else None,
        "is_active": rule.is_active,
        "store_id": str(rule.store_id),
        "tenant_id": str(rule.tenant_id),
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
        "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
    }


# ─── 端点 ───


@router.get("/{store_id}")
async def list_rules(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """列出门店所有路由规则（按 priority DESC 排序）。"""
    tenant_id = _get_tenant_id(request)
    tid = uuid.UUID(tenant_id)
    sid = uuid.UUID(store_id)

    stmt = (
        select(DispatchRule)
        .where(
            and_(
                DispatchRule.tenant_id == tid,
                DispatchRule.store_id == sid,
                DispatchRule.is_deleted == False,  # noqa: E712
            )
        )
        .order_by(DispatchRule.priority.desc())
    )
    result = await db.execute(stmt)
    rules = result.scalars().all()

    return {"ok": True, "data": [_rule_to_dict(r) for r in rules]}


@router.post("/{store_id}")
async def create_rule(
    store_id: str,
    body: DispatchRuleCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """创建新的路由规则。"""
    tenant_id = _get_tenant_id(request)
    log = logger.bind(tenant_id=tenant_id, store_id=store_id)

    try:
        rule = DispatchRule(
            tenant_id=uuid.UUID(tenant_id),
            store_id=uuid.UUID(store_id),
            name=body.name,
            priority=body.priority,
            match_dish_id=uuid.UUID(body.match_dish_id) if body.match_dish_id else None,
            match_dish_category=body.match_dish_category,
            match_brand_id=uuid.UUID(body.match_brand_id) if body.match_brand_id else None,
            match_channel=body.match_channel,
            match_time_start=_parse_time(body.match_time_start),
            match_time_end=_parse_time(body.match_time_end),
            match_day_type=body.match_day_type,
            target_dept_id=uuid.UUID(body.target_dept_id),
            target_printer_id=uuid.UUID(body.target_printer_id) if body.target_printer_id else None,
            is_active=body.is_active,
        )
        db.add(rule)
        await db.flush()
        await db.refresh(rule)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"参数格式错误：{exc}") from exc

    invalidate_store_cache(tenant_id, store_id)
    log.info("dispatch_rule.created", rule_id=str(rule.id))
    return {"ok": True, "data": _rule_to_dict(rule)}


@router.put("/{rule_id}")
async def update_rule(
    rule_id: str,
    body: DispatchRuleUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """更新路由规则。"""
    tenant_id = _get_tenant_id(request)
    tid = uuid.UUID(tenant_id)
    rid = uuid.UUID(rule_id)

    stmt = select(DispatchRule).where(
        and_(
            DispatchRule.id == rid,
            DispatchRule.tenant_id == tid,
            DispatchRule.is_deleted == False,  # noqa: E712
        )
    )
    result = await db.execute(stmt)
    rule = result.scalar_one_or_none()

    if rule is None:
        raise HTTPException(status_code=404, detail="规则不存在")

    try:
        if body.name is not None:
            rule.name = body.name
        if body.priority is not None:
            rule.priority = body.priority
        if body.match_dish_id is not None:
            rule.match_dish_id = uuid.UUID(body.match_dish_id)
        if body.match_dish_category is not None:
            rule.match_dish_category = body.match_dish_category
        if body.match_brand_id is not None:
            rule.match_brand_id = uuid.UUID(body.match_brand_id)
        if body.match_channel is not None:
            rule.match_channel = body.match_channel
        if body.match_time_start is not None:
            rule.match_time_start = _parse_time(body.match_time_start)
        if body.match_time_end is not None:
            rule.match_time_end = _parse_time(body.match_time_end)
        if body.match_day_type is not None:
            rule.match_day_type = body.match_day_type
        if body.target_dept_id is not None:
            rule.target_dept_id = uuid.UUID(body.target_dept_id)
        if body.target_printer_id is not None:
            rule.target_printer_id = uuid.UUID(body.target_printer_id)
        if body.is_active is not None:
            rule.is_active = body.is_active
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"参数格式错误：{exc}") from exc

    await db.flush()
    await db.refresh(rule)

    invalidate_store_cache(tenant_id, str(rule.store_id))
    logger.info("dispatch_rule.updated", rule_id=rule_id, tenant_id=tenant_id)
    return {"ok": True, "data": _rule_to_dict(rule)}


@router.delete("/{rule_id}")
async def delete_rule(
    rule_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """软删除路由规则。"""
    tenant_id = _get_tenant_id(request)
    tid = uuid.UUID(tenant_id)
    rid = uuid.UUID(rule_id)

    stmt = select(DispatchRule).where(
        and_(
            DispatchRule.id == rid,
            DispatchRule.tenant_id == tid,
            DispatchRule.is_deleted == False,  # noqa: E712
        )
    )
    result = await db.execute(stmt)
    rule = result.scalar_one_or_none()

    if rule is None:
        raise HTTPException(status_code=404, detail="规则不存在")

    rule.is_deleted = True
    await db.flush()

    invalidate_store_cache(tenant_id, str(rule.store_id))
    logger.info("dispatch_rule.deleted", rule_id=rule_id, tenant_id=tenant_id)
    return {"ok": True, "data": {"deleted": True, "rule_id": rule_id}}


@router.post("/{rule_id}/test")
async def test_rule(
    rule_id: str,
    body: RuleTestRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """测试某条规则是否匹配给定上下文。

    管理员可用于验证规则配置是否符合预期。
    """
    tenant_id = _get_tenant_id(request)

    result = await dispatch_rule_engine.test_rule(
        rule_id=rule_id,
        test_context={
            "dish_id": body.dish_id,
            "dish_category": body.dish_category,
            "brand_id": body.brand_id,
            "channel": body.channel,
            "order_time": body.order_time,
        },
        tenant_id=tenant_id,
        db=db,
    )

    if result.get("reason") == "rule_not_found":
        raise HTTPException(status_code=404, detail="规则不存在")

    return {"ok": True, "data": result}


@router.get("/{store_id}/simulate")
async def simulate_routing(
    store_id: str,
    request: Request,
    dish_id: str = "",
    dish_category: str = "",
    brand_id: str = "",
    channel: str = "",
    order_time: str = "",
    db: AsyncSession = Depends(get_db),
):
    """模拟一个订单项的完整路由结果。

    返回最终路由到的档口信息，以及匹配的规则详情（或fallback原因）。
    """
    tenant_id = _get_tenant_id(request)
    log = logger.bind(tenant_id=tenant_id, store_id=store_id)

    if not dish_id:
        raise HTTPException(status_code=400, detail="dish_id 必填")

    parsed_order_time: datetime
    if order_time:
        try:
            parsed_order_time = datetime.fromisoformat(order_time)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"order_time 格式错误：{exc}") from exc
    else:
        parsed_order_time = datetime.now(timezone.utc)

    try:
        dept_id, printer_id = await dispatch_rule_engine.resolve_dept(
            dish_id=dish_id,
            dish_category=dish_category or None,
            brand_id=brand_id or None,
            channel=channel or None,
            order_time=parsed_order_time,
            store_id=store_id,
            tenant_id=tenant_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    dept_info: dict = {}
    if dept_id is not None:
        tid = uuid.UUID(tenant_id)
        dept_stmt = select(ProductionDept).where(
            and_(
                ProductionDept.id == dept_id,
                ProductionDept.tenant_id == tid,
                ProductionDept.is_deleted == False,  # noqa: E712
            )
        )
        dept_result = await db.execute(dept_stmt)
        dept = dept_result.scalar_one_or_none()
        if dept:
            dept_info = {
                "dept_id": str(dept.id),
                "dept_name": dept.dept_name,
                "dept_code": dept.dept_code,
                "printer_address": dept.printer_address,
            }

    log.info(
        "dispatch_rule.simulate",
        dish_id=dish_id, dept_id=str(dept_id) if dept_id else None,
    )
    return {
        "ok": True,
        "data": {
            "dept": dept_info if dept_info else None,
            "printer_id_override": str(printer_id) if printer_id else None,
            "matched": dept_id is not None,
        }
    }
