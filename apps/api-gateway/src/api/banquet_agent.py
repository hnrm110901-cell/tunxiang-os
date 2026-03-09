"""
宴会管理 Agent — Phase 9 核心路由
路由前缀：/api/v1/banquet-agent

与现有 banquet.py（吉日/BEO）并存，专注 CRM+线索+订单+Agent 能力。
"""
import uuid
from datetime import date as date_type, datetime
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from sqlalchemy.orm import selectinload

from src.core.database import get_db
from src.core.security import get_current_user
from src.models.user import User
from src.models.banquet import (
    BanquetHall, BanquetCustomer, BanquetLead, BanquetOrder,
    MenuPackage, ExecutionTask, BanquetPaymentRecord,
    BanquetHallBooking, BanquetKpiDaily,
    LeadStageEnum, OrderStatusEnum, BanquetTypeEnum,
    BanquetHallType, PaymentTypeEnum, DepositStatusEnum,
)
import sys
from pathlib import Path as _Path

def _load_banquet_agents():
    """懒加载 Banquet Agent（与 workforce_auto_schedule_service 同一模式）"""
    repo_root = _Path(__file__).resolve().parents[4]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from packages.agents.banquet.src.agent import (
        FollowupAgent, QuotationAgent, SchedulingAgent,
        ExecutionAgent, ReviewAgent,
    )
    return FollowupAgent, QuotationAgent, SchedulingAgent, ExecutionAgent, ReviewAgent

_FollowupAgent, _QuotationAgent, _SchedulingAgent, _ExecutionAgent, _ReviewAgent = _load_banquet_agents()

router = APIRouter(prefix="/api/v1/banquet-agent", tags=["banquet-agent"])

_LEAD_STAGE_LABELS: dict[str, str] = {
    "new":              "初步询价",
    "contacted":        "已联系",
    "visit_scheduled":  "预约看厅",
    "quoted":           "意向确认",
    "waiting_decision": "等待决策",
    "deposit_pending":  "锁台",
    "won":              "已签约",
    "lost":             "已流失",
}

_followup   = _FollowupAgent()
_quotation  = _QuotationAgent()
_scheduling = _SchedulingAgent()
_execution  = _ExecutionAgent()
_review     = _ReviewAgent()


# ────────── Schemas ──────────────────────────────────────────────────────────

class HallCreateReq(BaseModel):
    name: str
    hall_type: BanquetHallType
    max_tables: int = Field(ge=1, default=1)
    max_people: int = Field(ge=1)
    min_spend_yuan: float = Field(ge=0, default=0)
    floor_area_m2: Optional[float] = None
    description: Optional[str] = None


class CustomerCreateReq(BaseModel):
    name: str
    phone: str
    wechat_id: Optional[str] = None
    customer_type: Optional[str] = None
    company_name: Optional[str] = None
    source: Optional[str] = None
    remark: Optional[str] = None


class LeadCreateReq(BaseModel):
    customer_id: str
    banquet_type: BanquetTypeEnum
    expected_date: Optional[date_type] = None
    expected_people_count: Optional[int] = None
    expected_budget_yuan: Optional[float] = None
    preferred_hall_type: Optional[BanquetHallType] = None
    source_channel: Optional[str] = None
    owner_user_id: Optional[str] = None


class LeadStageUpdateReq(BaseModel):
    stage: LeadStageEnum
    followup_content: Optional[str] = None   # legacy field name
    followup_note:    Optional[str] = None   # Phase 2 frontend field name
    next_followup_days: Optional[int] = Field(None, ge=1, le=30)


class OrderCreateReq(BaseModel):
    lead_id: Optional[str] = None
    customer_id: str
    banquet_type: BanquetTypeEnum
    banquet_date: date_type
    people_count: int = Field(ge=1)
    table_count: int = Field(ge=1)
    package_id: Optional[str] = None
    total_amount_yuan: float = Field(ge=0)
    deposit_yuan: float = Field(ge=0, default=0)
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    hall_id: Optional[str] = None
    slot_name: str = "all_day"
    remark: Optional[str] = None


class PaymentReq(BaseModel):
    payment_type: PaymentTypeEnum = PaymentTypeEnum.BALANCE   # default: 尾款
    amount_yuan: float = Field(gt=0)
    payment_method: Optional[str] = None
    receipt_no: Optional[str] = None


# ────────── 宴会厅 ────────────────────────────────────────────────────────────

@router.get("/stores/{store_id}/halls")
async def list_halls(
    store_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """查询门店宴会厅列表"""
    result = await db.execute(
        select(BanquetHall).where(
            and_(BanquetHall.store_id == store_id, BanquetHall.is_active == True)
        )
    )
    halls = result.scalars().all()
    return {
        "store_id": store_id,
        "total": len(halls),
        "items": [
            {
                "id": h.id, "name": h.name, "hall_type": h.hall_type.value,
                "max_tables": h.max_tables, "max_people": h.max_people,
                "min_spend_yuan": h.min_spend_fen / 100,
            }
            for h in halls
        ],
    }


@router.post("/stores/{store_id}/halls", status_code=status.HTTP_201_CREATED)
async def create_hall(
    store_id: str,
    body: HallCreateReq,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    hall = BanquetHall(
        id=str(uuid.uuid4()),
        store_id=store_id,
        name=body.name,
        hall_type=body.hall_type,
        max_tables=body.max_tables,
        max_people=body.max_people,
        min_spend_fen=int(body.min_spend_yuan * 100),
        floor_area_m2=body.floor_area_m2,
        description=body.description,
    )
    db.add(hall)
    await db.commit()
    return {"id": hall.id, "name": hall.name}


# ────────── 宴会客户 CRM ──────────────────────────────────────────────────────

@router.get("/stores/{store_id}/customers")
async def list_customers(
    store_id: str,
    q: Optional[str] = Query(None, description="搜索姓名/手机"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = select(BanquetCustomer).where(BanquetCustomer.store_id == store_id)
    if q:
        stmt = stmt.where(
            BanquetCustomer.name.ilike(f"%{q}%") |
            BanquetCustomer.phone.contains(q)
        )
    result = await db.execute(stmt.order_by(BanquetCustomer.total_banquet_amount_fen.desc()))
    customers = result.scalars().all()
    return {
        "store_id": store_id,
        "total": len(customers),
        "items": [
            {
                "id": c.id, "name": c.name, "phone": c.phone,
                "vip_level": c.vip_level,
                "total_banquet_count": c.total_banquet_count,
                "total_banquet_amount_yuan": c.total_banquet_amount_fen / 100,
                "source": c.source,
            }
            for c in customers
        ],
    }


@router.post("/stores/{store_id}/customers", status_code=status.HTTP_201_CREATED)
async def create_customer(
    store_id: str,
    body: CustomerCreateReq,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing = await db.execute(
        select(BanquetCustomer).where(
            and_(BanquetCustomer.store_id == store_id, BanquetCustomer.phone == body.phone)
        )
    )
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail="该手机号客户已存在")
    brand_id = getattr(current_user, "brand_id", store_id)
    customer = BanquetCustomer(
        id=str(uuid.uuid4()),
        brand_id=brand_id,
        store_id=store_id,
        name=body.name,
        phone=body.phone,
        wechat_id=body.wechat_id,
        customer_type=body.customer_type,
        company_name=body.company_name,
        source=body.source,
        remark=body.remark,
    )
    db.add(customer)
    await db.commit()
    return {"id": customer.id, "name": customer.name}


# ────────── 宴会线索 ──────────────────────────────────────────────────────────

@router.get("/stores/{store_id}/leads")
async def list_leads(
    store_id: str,
    stage: Optional[str] = Query(None),
    owner_user_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = (
        select(BanquetLead)
        .options(selectinload(BanquetLead.customer))
        .where(BanquetLead.store_id == store_id)
    )
    if stage:
        try:
            stmt = stmt.where(BanquetLead.current_stage == LeadStageEnum(stage))
        except ValueError:
            pass  # 无效阶段值 → 忽略过滤，返回全部
    if owner_user_id:
        stmt = stmt.where(BanquetLead.owner_user_id == owner_user_id)
    result = await db.execute(stmt.order_by(BanquetLead.created_at.desc()))
    leads = result.scalars().all()
    return {
        "total": len(leads),
        "items": [
            {
                # Phase 2 frontend fields
                "banquet_id":    l.id,
                "banquet_type":  l.banquet_type.value,
                "expected_date": str(l.expected_date) if l.expected_date else None,
                "contact_name":  l.customer.name if l.customer else None,
                "budget_yuan":   (l.expected_budget_fen or 0) / 100,
                "stage":         l.current_stage.value,
                "stage_label":   _LEAD_STAGE_LABELS.get(l.current_stage.value, l.current_stage.value),
                # Legacy fields (backward compat)
                "id":                   l.id,
                "expected_people_count": l.expected_people_count,
                "expected_budget_yuan":  (l.expected_budget_fen or 0) / 100,
                "current_stage":         l.current_stage.value,
                "owner_user_id":         l.owner_user_id,
                "last_followup_at":      l.last_followup_at.isoformat() if l.last_followup_at else None,
            }
            for l in leads
        ],
    }


@router.post("/stores/{store_id}/leads", status_code=status.HTTP_201_CREATED)
async def create_lead(
    store_id: str,
    body: LeadCreateReq,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    lead = BanquetLead(
        id=str(uuid.uuid4()),
        store_id=store_id,
        customer_id=body.customer_id,
        banquet_type=body.banquet_type,
        expected_date=body.expected_date,
        expected_people_count=body.expected_people_count,
        expected_budget_fen=int(body.expected_budget_yuan * 100) if body.expected_budget_yuan else None,
        preferred_hall_type=body.preferred_hall_type,
        source_channel=body.source_channel,
        owner_user_id=body.owner_user_id,
        last_followup_at=datetime.utcnow(),
    )
    db.add(lead)
    await db.commit()
    return {"id": lead.id, "current_stage": lead.current_stage.value}


@router.patch("/stores/{store_id}/leads/{lead_id}/stage")
async def update_lead_stage(
    store_id: str,
    lead_id: str,
    body: LeadStageUpdateReq,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """推进线索阶段 + 记录跟进内容（LeadFollowupRecord）"""
    result = await db.execute(
        select(BanquetLead).where(
            and_(BanquetLead.id == lead_id, BanquetLead.store_id == store_id)
        )
    )
    lead = result.scalars().first()
    if not lead:
        raise HTTPException(status_code=404, detail="线索不存在")

    stage_before = lead.current_stage   # 变更前阶段，在 mutation 前保存
    lead.current_stage = body.stage
    lead.last_followup_at = datetime.utcnow()

    next_followup_at = None
    if body.next_followup_days:
        from datetime import timedelta
        next_followup_at = datetime.utcnow() + timedelta(days=body.next_followup_days)

    note_content = body.followup_content or body.followup_note or "（无跟进内容）"

    from src.models.banquet import LeadFollowupRecord
    record = LeadFollowupRecord(
        id=str(uuid.uuid4()),
        lead_id=lead_id,
        followup_type="wechat",          # 默认类型；后续可在 body 中扩展
        content=note_content,
        stage_before=stage_before,
        stage_after=body.stage,
        next_followup_at=next_followup_at,
        created_by=str(current_user.id),
    )
    db.add(record)
    await db.commit()
    return {
        "lead_id": lead_id,
        "stage_before": stage_before.value,
        "new_stage": lead.current_stage.value,
        "last_followup_at": lead.last_followup_at.isoformat(),
        "next_followup_at": next_followup_at.isoformat() if next_followup_at else None,
    }


# ────────── 宴会订单 ──────────────────────────────────────────────────────────

@router.get("/stores/{store_id}/orders")
async def list_orders(
    store_id: str,
    status: Optional[str] = Query(None, description="订单状态（Phase 2 前端参数名）"),
    order_status: Optional[str] = Query(None, description="订单状态（旧参数名，兼容保留）"),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = select(BanquetOrder).where(BanquetOrder.store_id == store_id)
    effective_status = status or order_status
    if effective_status:
        try:
            stmt = stmt.where(BanquetOrder.order_status == OrderStatusEnum(effective_status))
        except ValueError:
            pass  # 无效状态值 → 忽略过滤，返回全部
    if date_from:
        stmt = stmt.where(BanquetOrder.banquet_date >= date_from)
    if date_to:
        stmt = stmt.where(BanquetOrder.banquet_date <= date_to)
    result = await db.execute(stmt.order_by(BanquetOrder.banquet_date))
    orders = result.scalars().all()
    return {
        "total": len(orders),
        "items": [
            {
                # Phase 2 frontend fields
                "banquet_id":   o.id,
                "banquet_type": o.banquet_type.value,
                "banquet_date": str(o.banquet_date),
                "table_count":  o.table_count,
                "amount_yuan":  o.total_amount_fen / 100,
                "status":       o.order_status.value,
                # Legacy fields (backward compat)
                "id":                 o.id,
                "people_count":       o.people_count,
                "order_status":       o.order_status.value,
                "deposit_status":     o.deposit_status.value,
                "total_amount_yuan":  o.total_amount_fen / 100,
                "paid_yuan":          o.paid_fen / 100,
                "balance_yuan":       (o.total_amount_fen - o.paid_fen) / 100,
            }
            for o in orders
        ],
    }


@router.post("/stores/{store_id}/orders", status_code=status.HTTP_201_CREATED)
async def create_order(
    store_id: str,
    body: OrderCreateReq,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    order = BanquetOrder(
        id=str(uuid.uuid4()),
        lead_id=body.lead_id,
        customer_id=body.customer_id,
        store_id=store_id,
        banquet_type=body.banquet_type,
        banquet_date=body.banquet_date,
        people_count=body.people_count,
        table_count=body.table_count,
        package_id=body.package_id,
        total_amount_fen=int(body.total_amount_yuan * 100),
        deposit_fen=int(body.deposit_yuan * 100),
        contact_name=body.contact_name,
        contact_phone=body.contact_phone,
        remark=body.remark,
    )
    db.add(order)
    await db.commit()
    return {"id": order.id, "order_status": order.order_status.value}


@router.post("/stores/{store_id}/orders/{order_id}/confirm")
async def confirm_order(
    store_id: str,
    order_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """确认订单 → ExecutionAgent 自动生成执行任务"""
    result = await db.execute(
        select(BanquetOrder).where(
            and_(BanquetOrder.id == order_id, BanquetOrder.store_id == store_id)
        )
    )
    order = result.scalars().first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.order_status != OrderStatusEnum.DRAFT:
        raise HTTPException(status_code=400, detail=f"当前状态 {order.order_status.value} 不可确认")

    order.order_status = OrderStatusEnum.CONFIRMED
    tasks = await _execution.generate_tasks_for_order(order=order, db=db)
    return {
        "order_id": order_id,
        "order_status": order.order_status.value,
        "tasks_generated": len(tasks),
        "message": f"订单已确认，自动生成 {len(tasks)} 个执行任务。",
    }


@router.post("/stores/{store_id}/orders/{order_id}/payment")
async def add_payment(
    store_id: str,
    order_id: str,
    body: PaymentReq,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """收款登记"""
    result = await db.execute(
        select(BanquetOrder).where(
            and_(BanquetOrder.id == order_id, BanquetOrder.store_id == store_id)
        )
    )
    order = result.scalars().first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")

    payment = BanquetPaymentRecord(
        id=str(uuid.uuid4()),
        banquet_order_id=order_id,
        payment_type=body.payment_type,
        amount_fen=int(body.amount_yuan * 100),
        paid_at=datetime.utcnow(),
        payment_method=body.payment_method,
        receipt_no=body.receipt_no,
        created_by=str(current_user.id),
    )
    db.add(payment)
    order.paid_fen += payment.amount_fen
    # 更新定金状态
    if order.paid_fen >= order.deposit_fen:
        order.deposit_status = DepositStatusEnum.PAID
    elif order.paid_fen > 0:
        order.deposit_status = DepositStatusEnum.PARTIAL
    await db.commit()
    return {
        "payment_id": payment.id,
        "paid_yuan": order.paid_fen / 100,
        "balance_yuan": (order.total_amount_fen - order.paid_fen) / 100,
        "deposit_status": order.deposit_status.value,
    }


# ────────── Agent 接口 ────────────────────────────────────────────────────────

@router.get("/stores/{store_id}/agent/followup-scan")
async def agent_followup_scan(
    store_id: str,
    dry_run: bool = Query(True, description="true=仅扫描不写库"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """跟进提醒 Agent：扫描停滞线索 → 企微提醒文本"""
    results = await _followup.scan_stale_leads(store_id=store_id, db=db, dry_run=dry_run)
    return {"store_id": store_id, "dry_run": dry_run, "stale_lead_count": len(results), "items": results}


@router.get("/stores/{store_id}/agent/quote-recommend")
async def agent_quote_recommend(
    store_id: str,
    people_count: int = Query(..., ge=1),
    budget_yuan: float = Query(..., gt=0),
    banquet_type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """报价推荐 Agent：按人数+预算推荐套餐（含¥毛利估算）"""
    return await _quotation.recommend_packages(
        store_id=store_id,
        people_count=people_count,
        budget_fen=int(budget_yuan * 100),
        banquet_type=banquet_type,
        db=db,
    )


@router.get("/stores/{store_id}/agent/hall-recommend")
async def agent_hall_recommend(
    store_id: str,
    target_date: str = Query(..., description="YYYY-MM-DD"),
    slot_name: str = Query("all_day", description="lunch/dinner/all_day"),
    people_count: int = Query(..., ge=1),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """排期推荐 Agent：查可用厅房，排除冲突档期"""
    from datetime import date
    d = date.fromisoformat(target_date)
    return await _scheduling.recommend_halls(
        store_id=store_id, target_date=d, slot_name=slot_name, people_count=people_count, db=db
    )


@router.post("/stores/{store_id}/orders/{order_id}/review")
async def agent_generate_review(
    store_id: str,
    order_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """复盘 Agent：宴会完成后自动生成复盘草稿（含¥收入/利润分析）"""
    result = await db.execute(
        select(BanquetOrder).where(
            and_(BanquetOrder.id == order_id, BanquetOrder.store_id == store_id)
        )
    )
    order = result.scalars().first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.order_status not in {OrderStatusEnum.COMPLETED, OrderStatusEnum.SETTLED}:
        raise HTTPException(status_code=400, detail="订单尚未完成")
    return await _review.generate_review(order=order, db=db)


# ────────── 驾驶舱 ────────────────────────────────────────────────────────────

@router.get("/stores/{store_id}/dashboard")
async def banquet_dashboard(
    store_id: str,
    year:  Optional[int] = Query(None, description="年份（整数，与 month 整数配合使用）"),
    month: Optional[str] = Query(None, description="月份：可为整数 '3' 或 YYYY-MM 字符串 '2026-03'"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """宴会经营驾驶舱：本月收入/订单数/转化率/档期利用率"""
    from datetime import date as _date
    # 解析年月：支持 ?year=2026&month=3 和 ?month=2026-03 两种形式
    if month and "-" in str(month):
        y, m = map(int, month.split("-"))
    elif year and month:
        y, m = year, int(month)
    elif month:
        today = _date.today()
        y, m = today.year, int(month)
    else:
        today = _date.today()
        y, m = today.year, today.month

    # KPI 日报聚合
    kpi_result = await db.execute(
        select(
            func.sum(BanquetKpiDaily.revenue_fen).label("revenue_fen"),
            func.sum(BanquetKpiDaily.gross_profit_fen).label("profit_fen"),
            func.sum(BanquetKpiDaily.order_count).label("order_count"),
            func.sum(BanquetKpiDaily.lead_count).label("lead_count"),
            func.avg(BanquetKpiDaily.hall_utilization_pct).label("avg_utilization"),
        ).where(
            and_(
                BanquetKpiDaily.store_id == store_id,
                func.extract("year", BanquetKpiDaily.stat_date) == y,
                func.extract("month", BanquetKpiDaily.stat_date) == m,
            )
        )
    )
    row = kpi_result.first()
    revenue_yuan = (row.revenue_fen or 0) / 100
    profit_yuan  = (row.profit_fen  or 0) / 100
    order_count  = row.order_count  or 0
    lead_count   = row.lead_count   or 0
    utilization  = round(row.avg_utilization or 0, 1)
    conversion   = round(order_count / lead_count * 100, 1) if lead_count > 0 else 0

    return {
        "store_id": store_id,
        "year": y,
        "month": m,
        # Phase 2 frontend fields (DashboardData interface)
        "revenue_yuan":     revenue_yuan,
        "gross_margin_pct": round(profit_yuan / revenue_yuan * 100, 1) if revenue_yuan > 0 else 0,
        "order_count":      order_count,
        "conversion_rate":  conversion,       # alias: conversion_rate_pct
        "room_utilization": utilization,      # alias: hall_utilization_pct
        # Legacy / additional fields
        "gross_profit_yuan":   profit_yuan,
        "lead_count":          lead_count,
        "conversion_rate_pct": conversion,
        "hall_utilization_pct": utilization,
        "summary": (
            f"{y}年{m}月宴会收入¥{revenue_yuan:.0f}，"
            f"毛利¥{profit_yuan:.0f}，"
            f"转化率{conversion}%，档期利用率{utilization}%。"
        ),
    }
