"""预订/排队/宴会 API — Sprint 3 全端点

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""
from typing import Optional

from fastapi import APIRouter, Depends, Request, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.reservation_service import ReservationService
from ..services.queue_service import QueueService
from ..services.banquet_lifecycle import BanquetLifecycleService

router = APIRouter(prefix="/api/v1", tags=["booking"])


# ─── 通用辅助 ───

def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> dict:
    raise HTTPException(
        status_code=code,
        detail={"ok": False, "data": None, "error": {"message": msg}},
    )


# ═══════════════════════════════════════════════════════════
# 预订 Reservation
# ═══════════════════════════════════════════════════════════

class CreateReservationReq(BaseModel):
    store_id: str
    customer_name: str
    phone: str
    type: str = "regular"
    date: str = Field(description="YYYY-MM-DD")
    time: str = Field(description="HH:MM")
    party_size: int = Field(ge=1)
    room_name: Optional[str] = None
    special_requests: Optional[str] = None
    deposit_required: bool = False
    deposit_amount_fen: int = 0
    consumer_id: Optional[str] = None


class UpdateReservationStatusReq(BaseModel):
    action: str = Field(description="confirm/arrive/seat/complete/cancel/no_show")
    table_no: Optional[str] = None
    confirmed_by: Optional[str] = "system"
    reason: Optional[str] = None
    cancel_fee_fen: int = 0


@router.post("/reservations")
async def create_reservation(req: CreateReservationReq, request: Request):
    """创建预订"""
    tenant_id = _get_tenant_id(request)
    svc = ReservationService(tenant_id=tenant_id, store_id=req.store_id)
    try:
        result = svc.create_reservation(
            store_id=req.store_id,
            customer_name=req.customer_name,
            phone=req.phone,
            type=req.type,
            date=req.date,
            time=req.time,
            party_size=req.party_size,
            room_name=req.room_name,
            special_requests=req.special_requests,
            deposit_required=req.deposit_required,
            deposit_amount_fen=req.deposit_amount_fen,
            consumer_id=req.consumer_id,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.put("/reservations/{reservation_id}/status")
async def update_reservation_status(
    reservation_id: str,
    req: UpdateReservationStatusReq,
    request: Request,
):
    """更新预订状态（确认/到店/入座/完成/取消/爽约）"""
    tenant_id = _get_tenant_id(request)
    svc = ReservationService(tenant_id=tenant_id, store_id="")
    try:
        if req.action == "confirm":
            result = svc.confirm_reservation(reservation_id, confirmed_by=req.confirmed_by or "system")
        elif req.action == "arrive":
            result = svc.customer_arrived(reservation_id)
        elif req.action == "seat":
            if not req.table_no:
                _err("table_no is required for seating")
            result = svc.seat_reservation(reservation_id, req.table_no)
        elif req.action == "complete":
            result = svc.complete_reservation(reservation_id)
        elif req.action == "cancel":
            result = svc.cancel_reservation(
                reservation_id,
                reason=req.reason or "customer_request",
                cancel_fee_fen=req.cancel_fee_fen,
            )
        elif req.action == "no_show":
            result = svc.mark_no_show(reservation_id)
        else:
            _err(f"Unknown action: {req.action}")
            return
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.get("/reservations")
async def list_reservations(
    request: Request,
    store_id: str = Query(...),
    date: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
):
    """查询预订列表"""
    tenant_id = _get_tenant_id(request)
    svc = ReservationService(tenant_id=tenant_id, store_id=store_id)
    result = svc.list_reservations(store_id=store_id, date=date, status=status, type=type)
    return _ok(result)


@router.get("/reservations/time-slots")
async def get_time_slots(
    request: Request,
    store_id: str = Query(...),
    date: str = Query(...),
    party_size: int = Query(..., ge=1),
):
    """查询可用时段"""
    tenant_id = _get_tenant_id(request)
    svc = ReservationService(tenant_id=tenant_id, store_id=store_id)
    result = svc.get_time_slots(store_id=store_id, date=date, party_size=party_size)
    return _ok(result)


@router.get("/reservations/stats")
async def get_reservation_stats(
    request: Request,
    store_id: str = Query(...),
    start_date: str = Query(...),
    end_date: str = Query(...),
):
    """预订统计"""
    tenant_id = _get_tenant_id(request)
    svc = ReservationService(tenant_id=tenant_id, store_id=store_id)
    result = svc.get_reservation_stats(store_id=store_id, date_range=(start_date, end_date))
    return _ok(result)


# ═══════════════════════════════════════════════════════════
# 排队 Queue
# ═══════════════════════════════════════════════════════════

class TakeNumberReq(BaseModel):
    store_id: str
    customer_name: str
    phone: str
    party_size: int = Field(ge=1)
    source: str = "walk_in"
    vip_priority: bool = False


class CallNumberReq(BaseModel):
    queue_id: str


class SeatQueueReq(BaseModel):
    queue_id: str
    table_no: str


class SkipQueueReq(BaseModel):
    queue_id: str
    reason: str = "no_show"


class SyncMeituanReq(BaseModel):
    store_id: str
    meituan_data: list[dict]


@router.post("/queues")
async def take_queue_number(req: TakeNumberReq, request: Request):
    """取排队号"""
    tenant_id = _get_tenant_id(request)
    svc = QueueService(tenant_id=tenant_id, store_id=req.store_id)
    try:
        result = svc.take_number(
            store_id=req.store_id,
            customer_name=req.customer_name,
            phone=req.phone,
            party_size=req.party_size,
            source=req.source,
            vip_priority=req.vip_priority,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.post("/queues/call")
async def call_queue_number(req: CallNumberReq, request: Request):
    """叫号"""
    tenant_id = _get_tenant_id(request)
    svc = QueueService(tenant_id=tenant_id, store_id="")
    try:
        result = svc.call_number(req.queue_id)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.post("/queues/call-next")
async def call_next_queue(
    request: Request,
    store_id: str = Query(...),
    prefix: str = Query(""),
):
    """自动叫下一号"""
    tenant_id = _get_tenant_id(request)
    svc = QueueService(tenant_id=tenant_id, store_id=store_id)
    result = svc.call_next(store_id=store_id, prefix=prefix)
    if result is None:
        return _ok({"message": "No waiting customers"})
    return _ok(result)


@router.post("/queues/seat")
async def seat_queue_customer(req: SeatQueueReq, request: Request):
    """排队入座"""
    tenant_id = _get_tenant_id(request)
    svc = QueueService(tenant_id=tenant_id, store_id="")
    try:
        result = svc.seat_customer(req.queue_id, req.table_no)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.post("/queues/skip")
async def skip_queue_customer(req: SkipQueueReq, request: Request):
    """过号"""
    tenant_id = _get_tenant_id(request)
    svc = QueueService(tenant_id=tenant_id, store_id="")
    try:
        result = svc.skip_customer(req.queue_id, reason=req.reason)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.get("/queues/board")
async def get_queue_board(
    request: Request,
    store_id: str = Query(...),
):
    """排队看板"""
    tenant_id = _get_tenant_id(request)
    svc = QueueService(tenant_id=tenant_id, store_id=store_id)
    result = svc.get_queue_board(store_id=store_id)
    return _ok(result)


@router.get("/queues/estimate")
async def estimate_wait_time(
    request: Request,
    store_id: str = Query(...),
    party_size: int = Query(..., ge=1),
):
    """预估等位时间"""
    tenant_id = _get_tenant_id(request)
    svc = QueueService(tenant_id=tenant_id, store_id=store_id)
    result = svc.estimate_wait_time(store_id=store_id, party_size=party_size)
    return _ok(result)


@router.get("/queues/history")
async def get_queue_history(
    request: Request,
    store_id: str = Query(...),
    date: str = Query(...),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
):
    """排队历史"""
    tenant_id = _get_tenant_id(request)
    svc = QueueService(tenant_id=tenant_id, store_id=store_id)
    result = svc.get_queue_history(store_id=store_id, date=date, page=page, size=size)
    return _ok(result)


@router.post("/queues/sync-meituan")
async def sync_meituan_queue(req: SyncMeituanReq, request: Request):
    """美团排队同步"""
    tenant_id = _get_tenant_id(request)
    svc = QueueService(tenant_id=tenant_id, store_id=req.store_id)
    result = svc.sync_meituan_queue(store_id=req.store_id, meituan_data=req.meituan_data)
    return _ok(result)


# ═══════════════════════════════════════════════════════════
# 宴会 Banquet
# ═══════════════════════════════════════════════════════════

class CreateLeadReq(BaseModel):
    store_id: str
    customer_name: str
    phone: str
    event_type: str
    estimated_tables: int = Field(ge=1)
    estimated_budget_fen: int = Field(ge=1)
    event_date: str
    special_requirements: Optional[str] = None
    referral_source: Optional[str] = None


class UpdateLeadStageReq(BaseModel):
    target_stage: str


class AddFollowupReq(BaseModel):
    content: str
    next_action: str
    next_date: str


class CreateQuotationReq(BaseModel):
    proposal_tier: str
    adjustments: Optional[list[dict]] = None


class CreateContractReq(BaseModel):
    quotation_id: str
    terms: dict = Field(default_factory=dict)
    deposit_rate: float = 0.3


class CollectDepositReq(BaseModel):
    amount_fen: int = Field(ge=1)
    method: str
    trade_no: Optional[str] = None


class ConfirmMenuReq(BaseModel):
    final_menu_items: list[dict]


class UpdateChecklistReq(BaseModel):
    status: str
    notes: Optional[str] = None


class SettleBanquetReq(BaseModel):
    actual_tables: int = Field(ge=1)
    actual_guests: int = Field(ge=1)
    additional_charges: Optional[list[dict]] = None
    deductions: Optional[list[dict]] = None


class CollectFeedbackReq(BaseModel):
    satisfaction_score: int = Field(ge=1, le=10)
    feedback_text: str


class ArchiveCaseReq(BaseModel):
    photos: Optional[list[str]] = None
    highlights: Optional[list[str]] = None


# ─── Lead endpoints ───

@router.post("/banquet/leads")
async def create_banquet_lead(req: CreateLeadReq, request: Request):
    """创建宴会线索"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetLifecycleService(tenant_id=tenant_id, store_id=req.store_id)
    try:
        result = svc.create_lead(
            store_id=req.store_id,
            customer_name=req.customer_name,
            phone=req.phone,
            event_type=req.event_type,
            estimated_tables=req.estimated_tables,
            estimated_budget_fen=req.estimated_budget_fen,
            event_date=req.event_date,
            special_requirements=req.special_requirements,
            referral_source=req.referral_source,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.put("/banquet/leads/{lead_id}/stage")
async def update_lead_stage(lead_id: str, req: UpdateLeadStageReq, request: Request):
    """更新线索阶段"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetLifecycleService(tenant_id=tenant_id, store_id="")
    try:
        result = svc.update_lead_stage(lead_id, req.target_stage)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.post("/banquet/leads/{lead_id}/followup")
async def add_followup(lead_id: str, req: AddFollowupReq, request: Request):
    """添加跟进记录"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetLifecycleService(tenant_id=tenant_id, store_id="")
    try:
        result = svc.add_followup_record(
            lead_id=lead_id,
            content=req.content,
            next_action=req.next_action,
            next_date=req.next_date,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── Proposal & Quotation endpoints ───

@router.post("/banquet/leads/{lead_id}/proposal")
async def generate_proposal(lead_id: str, request: Request):
    """AI生成宴会方案"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetLifecycleService(tenant_id=tenant_id, store_id="")
    try:
        result = svc.generate_proposal(lead_id)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.post("/banquet/leads/{lead_id}/quotation")
async def create_quotation(lead_id: str, req: CreateQuotationReq, request: Request):
    """创建正式报价"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetLifecycleService(tenant_id=tenant_id, store_id="")
    try:
        result = svc.create_quotation(
            lead_id=lead_id,
            proposal_tier=req.proposal_tier,
            adjustments=req.adjustments,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── Contract & Deposit endpoints ───

@router.post("/banquet/leads/{lead_id}/contract")
async def create_contract(lead_id: str, req: CreateContractReq, request: Request):
    """创建宴会合同"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetLifecycleService(tenant_id=tenant_id, store_id="")
    try:
        result = svc.create_contract(
            lead_id=lead_id,
            quotation_id=req.quotation_id,
            terms=req.terms,
            deposit_rate=req.deposit_rate,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.post("/banquet/contracts/{contract_id}/deposit")
async def collect_deposit(contract_id: str, req: CollectDepositReq, request: Request):
    """收取定金"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetLifecycleService(tenant_id=tenant_id, store_id="")
    try:
        result = svc.collect_deposit(
            contract_id=contract_id,
            amount_fen=req.amount_fen,
            method=req.method,
            trade_no=req.trade_no,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── Menu & Preparation endpoints ───

@router.post("/banquet/contracts/{contract_id}/confirm-menu")
async def confirm_menu(contract_id: str, req: ConfirmMenuReq, request: Request):
    """确认最终菜单"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetLifecycleService(tenant_id=tenant_id, store_id="")
    try:
        result = svc.confirm_menu(contract_id=contract_id, final_menu_items=req.final_menu_items)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.post("/banquet/contracts/{contract_id}/checklist")
async def generate_checklist(contract_id: str, request: Request):
    """生成筹备检查清单"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetLifecycleService(tenant_id=tenant_id, store_id="")
    try:
        result = svc.generate_prep_checklist(contract_id=contract_id)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.put("/banquet/checklists/{item_id}")
async def update_checklist_item(item_id: str, req: UpdateChecklistReq, request: Request):
    """更新检查清单项"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetLifecycleService(tenant_id=tenant_id, store_id="")
    try:
        result = svc.update_checklist_item(
            checklist_item_id=item_id,
            status=req.status,
            notes=req.notes,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── Execution endpoints ───

@router.post("/banquet/contracts/{contract_id}/execute")
async def start_execution(contract_id: str, request: Request):
    """开始执行宴会"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetLifecycleService(tenant_id=tenant_id, store_id="")
    try:
        result = svc.start_execution(contract_id=contract_id)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── Settlement & Feedback endpoints ───

@router.post("/banquet/contracts/{contract_id}/settle")
async def settle_banquet(contract_id: str, req: SettleBanquetReq, request: Request):
    """宴会结算"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetLifecycleService(tenant_id=tenant_id, store_id="")
    try:
        result = svc.settle_banquet(
            contract_id=contract_id,
            actual_tables=req.actual_tables,
            actual_guests=req.actual_guests,
            additional_charges=req.additional_charges,
            deductions=req.deductions,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.post("/banquet/contracts/{contract_id}/feedback")
async def collect_feedback(contract_id: str, req: CollectFeedbackReq, request: Request):
    """收集客户反馈"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetLifecycleService(tenant_id=tenant_id, store_id="")
    try:
        result = svc.collect_feedback(
            contract_id=contract_id,
            satisfaction_score=req.satisfaction_score,
            feedback_text=req.feedback_text,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.post("/banquet/contracts/{contract_id}/archive")
async def archive_as_case(contract_id: str, req: ArchiveCaseReq, request: Request):
    """归档为案例"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetLifecycleService(tenant_id=tenant_id, store_id="")
    try:
        result = svc.archive_as_case(
            contract_id=contract_id,
            photos=req.photos,
            highlights=req.highlights,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── Analytics endpoints ───

@router.get("/banquet/pipeline")
async def get_pipeline(
    request: Request,
    store_id: str = Query(...),
):
    """宴会销售漏斗"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetLifecycleService(tenant_id=tenant_id, store_id=store_id)
    result = svc.get_banquet_pipeline(store_id=store_id)
    return _ok(result)


@router.get("/banquet/revenue")
async def get_revenue(
    request: Request,
    store_id: str = Query(...),
    start_date: str = Query(...),
    end_date: str = Query(...),
):
    """宴会营收统计"""
    tenant_id = _get_tenant_id(request)
    svc = BanquetLifecycleService(tenant_id=tenant_id, store_id=store_id)
    result = svc.get_banquet_revenue(store_id=store_id, date_range=(start_date, end_date))
    return _ok(result)
