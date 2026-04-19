"""预订/排队/宴会 API — Sprint 3 全端点

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。

修复:
  - [DB-SESSION] _get_db_session 改为 AsyncGenerator + Depends，确保 commit/rollback 生命周期正确
  - [PAGINATION] 预订列表 list_reservations 增加分页参数
  - [VALIDATION] phone 空字符串校验 (Pydantic min_length)
  - [RETURN] _err() 之后不再有 unreachable code
"""

from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.banquet_lifecycle import BanquetLifecycleService
from ..services.queue_service import QueueService
from ..services.reservation_service import ReservationService

router = APIRouter(prefix="/api/v1", tags=["booking"])


# ─── 通用辅助 ───


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


async def _get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """获取带租户隔离的DB session — 通过 Depends 注入，保证 generator 生命周期完整。

    修复说明: 原实现用 `async for ... return` 从 generator 中提取 session，
    导致 generator 永远无法走到 yield 之后的 commit/rollback。
    改为 yield 形式，由 FastAPI Depends 自动管理生命周期。
    """
    tenant_id = _get_tenant_id(request)
    async for session in get_db_with_tenant(tenant_id):
        yield session


def _ok(data: object) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> None:
    """抛出 HTTPException。返回类型标注为 None 以明确不会返回值。"""
    raise HTTPException(
        status_code=code,
        detail={"ok": False, "data": None, "error": {"message": msg}},
    )


# ═══════════════════════════════════════════════════════════
# 预订 Reservation
# ═══════════════════════════════════════════════════════════


class CreateReservationReq(BaseModel):
    store_id: str
    customer_name: str = Field(min_length=1)
    phone: str = Field(min_length=1, description="手机号，不能为空")
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
async def create_reservation(
    req: CreateReservationReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """创建预订"""
    tenant_id = _get_tenant_id(request)
    svc = ReservationService(db=db, tenant_id=tenant_id, store_id=req.store_id)
    try:
        result = await svc.create_reservation(
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
    db: AsyncSession = Depends(_get_db_session),
):
    """更新预订状态（确认/到店/入座/完成/取消/爽约）"""
    tenant_id = _get_tenant_id(request)
    svc = ReservationService(db=db, tenant_id=tenant_id, store_id="")
    try:
        if req.action == "confirm":
            result = await svc.confirm_reservation(reservation_id, confirmed_by=req.confirmed_by or "system")
        elif req.action == "arrive":
            result = await svc.customer_arrived(reservation_id)
        elif req.action == "seat":
            if not req.table_no:
                _err("table_no is required for seating")
            result = await svc.seat_reservation(reservation_id, req.table_no)  # type: ignore[arg-type]

            # v149：预订入座 → 自动开台（创建 dining_session）
            # 异步执行，不阻断预订流程
            import asyncio

            from sqlalchemy import text as _text

            from ..services.dining_session_service import DiningSessionService

            async def _auto_open_from_booking() -> None:
                try:
                    # 查询预订详情（桌台ID、guest_count、waiter_id）
                    bk = await db.execute(
                        _text("""
                            SELECT r.store_id, r.guest_count, r.waiter_id,
                                   t.id AS table_id, t.zone_id
                            FROM reservations r
                            LEFT JOIN tables t ON t.table_no = r.table_no
                                               AND t.store_id = r.store_id
                                               AND t.tenant_id = :tid
                            WHERE r.id        = :rid
                              AND r.tenant_id = :tid
                        """),
                        {"rid": reservation_id, "tid": tenant_id},
                    )
                    bk_row = bk.mappings().one_or_none()
                    if not bk_row or not bk_row["table_id"]:
                        return

                    ds_svc = DiningSessionService(db, tenant_id)
                    # 检查是否已有活跃会话（避免重复开台）
                    existing = await ds_svc.get_active_session_by_table(bk_row["store_id"], bk_row["table_id"])
                    if existing:
                        return

                    await ds_svc.open_table(
                        store_id=bk_row["store_id"],
                        table_id=bk_row["table_id"],
                        guest_count=bk_row["guest_count"] or 1,
                        lead_waiter_id=bk_row["waiter_id"] or bk_row["store_id"],
                        zone_id=bk_row["zone_id"],
                        booking_id=reservation_id,
                        session_type="dine_in",
                    )
                except Exception:  # noqa: BLE001 — 异步后台任务，捕获所有异常防止崩溃
                    import structlog

                    structlog.get_logger().warning(
                        "booking_auto_open_table_failed",
                        reservation_id=reservation_id,
                        tenant_id=tenant_id,
                        exc_info=True,
                    )

            asyncio.create_task(_auto_open_from_booking())
        elif req.action == "complete":
            result = await svc.complete_reservation(reservation_id)
        elif req.action == "cancel":
            result = await svc.cancel_reservation(
                reservation_id,
                reason=req.reason or "customer_request",
                cancel_fee_fen=req.cancel_fee_fen,
            )
        elif req.action == "no_show":
            result = await svc.mark_no_show(reservation_id)
        else:
            _err(f"Unknown action: {req.action}")
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.get("/reservations")
async def list_reservations(
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
    store_id: str = Query(...),
    date: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(50, ge=1, le=200, description="每页条数"),
):
    """查询预订列表（带分页）

    修复说明: 原实现无分页，全表扫描风险。
    """
    tenant_id = _get_tenant_id(request)
    svc = ReservationService(db=db, tenant_id=tenant_id, store_id=store_id)
    result = await svc.list_reservations(
        store_id=store_id,
        date=date,
        status=status,
        type=type,
        page=page,
        size=size,
    )
    return _ok(result)


@router.get("/reservations/time-slots")
async def get_time_slots(
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
    store_id: str = Query(...),
    date: str = Query(...),
    party_size: int = Query(..., ge=1),
):
    """查询可用时段"""
    tenant_id = _get_tenant_id(request)
    svc = ReservationService(db=db, tenant_id=tenant_id, store_id=store_id)
    result = await svc.get_time_slots(store_id=store_id, date=date, party_size=party_size)
    return _ok(result)


@router.get("/reservations/stats")
async def get_reservation_stats(
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
    store_id: str = Query(...),
    start_date: str = Query(...),
    end_date: str = Query(...),
):
    """预订统计"""
    tenant_id = _get_tenant_id(request)
    svc = ReservationService(db=db, tenant_id=tenant_id, store_id=store_id)
    result = await svc.get_reservation_stats(store_id=store_id, date_range=(start_date, end_date))
    return _ok(result)


# ═══════════════════════════════════════════════════════════
# 排队 Queue
# ═══════════════════════════════════════════════════════════


class TakeNumberReq(BaseModel):
    store_id: str
    customer_name: str = Field(min_length=1)
    phone: str = Field(min_length=1, description="手机号，不能为空")
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
async def take_queue_number(
    req: TakeNumberReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """取排队号"""
    tenant_id = _get_tenant_id(request)
    svc = QueueService(db=db, tenant_id=tenant_id, store_id=req.store_id)
    try:
        result = await svc.take_number(
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
async def call_queue_number(
    req: CallNumberReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """叫号"""
    tenant_id = _get_tenant_id(request)
    svc = QueueService(db=db, tenant_id=tenant_id, store_id="")
    try:
        result = await svc.call_number(req.queue_id)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.post("/queues/call-next")
async def call_next_queue(
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
    store_id: str = Query(...),
    prefix: str = Query(""),
):
    """自动叫下一号"""
    tenant_id = _get_tenant_id(request)
    svc = QueueService(db=db, tenant_id=tenant_id, store_id=store_id)
    result = await svc.call_next(store_id=store_id, prefix=prefix)
    if result is None:
        return _ok({"message": "No waiting customers"})
    return _ok(result)


@router.post("/queues/seat")
async def seat_queue_customer(
    req: SeatQueueReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """排队入座"""
    tenant_id = _get_tenant_id(request)
    svc = QueueService(db=db, tenant_id=tenant_id, store_id="")
    try:
        result = await svc.seat_customer(req.queue_id, req.table_no)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.post("/queues/skip")
async def skip_queue_customer(
    req: SkipQueueReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """过号"""
    tenant_id = _get_tenant_id(request)
    svc = QueueService(db=db, tenant_id=tenant_id, store_id="")
    try:
        result = await svc.skip_customer(req.queue_id, reason=req.reason)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.get("/queues/board")
async def get_queue_board(
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
    store_id: str = Query(...),
):
    """排队看板"""
    tenant_id = _get_tenant_id(request)
    svc = QueueService(db=db, tenant_id=tenant_id, store_id=store_id)
    result = await svc.get_queue_board(store_id=store_id)
    return _ok(result)


@router.get("/queues/estimate")
async def estimate_wait_time(
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
    store_id: str = Query(...),
    party_size: int = Query(..., ge=1),
):
    """预估等位时间"""
    tenant_id = _get_tenant_id(request)
    svc = QueueService(db=db, tenant_id=tenant_id, store_id=store_id)
    result = await svc.estimate_wait_time(store_id=store_id, party_size=party_size)
    return _ok(result)


@router.get("/queues/history")
async def get_queue_history(
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
    store_id: str = Query(...),
    date: str = Query(...),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
):
    """排队历史"""
    tenant_id = _get_tenant_id(request)
    svc = QueueService(db=db, tenant_id=tenant_id, store_id=store_id)
    result = await svc.get_queue_history(store_id=store_id, date=date, page=page, size=size)
    return _ok(result)


@router.post("/queues/sync-meituan")
async def sync_meituan_queue(
    req: SyncMeituanReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """美团排队同步"""
    tenant_id = _get_tenant_id(request)
    svc = QueueService(db=db, tenant_id=tenant_id, store_id=req.store_id)
    result = await svc.sync_meituan_queue(store_id=req.store_id, meituan_data=req.meituan_data)
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
