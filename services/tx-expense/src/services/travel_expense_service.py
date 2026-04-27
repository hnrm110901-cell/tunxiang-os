"""
差旅费用 Service 层
负责差旅申请全生命周期管理：创建草稿、行程管理、补贴计算、完成结算、统计。

屯象OS核心差异化：巡店任务（来自tx-ops服务）自动生成差旅申请草稿，
督导去门店巡检的差旅无需手工填写。

金额约定：所有金额存储为分(fen)，BigInteger，展示层除以100转元。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models.expense_enums import TravelStatus
from ..models.travel import TravelAllocation, TravelItinerary, TravelRequest

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 内部辅助
# ─────────────────────────────────────────────────────────────────────────────


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _assert_tenant(obj: Any, tenant_id: uuid.UUID, label: str = "resource") -> None:
    """校验对象归属，防止跨租户访问。"""
    if obj is None or obj.tenant_id != tenant_id:
        raise LookupError(f"{label} not found for tenant {tenant_id}")


def _calc_planned_days(start: date, end: date) -> int:
    """计划天数 = 结束日期 - 开始日期 + 1（含首尾两天）。"""
    delta = (end - start).days + 1
    return max(delta, 1)


# ─────────────────────────────────────────────────────────────────────────────
# 差旅申请 CRUD
# ─────────────────────────────────────────────────────────────────────────────


async def create_travel_request(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    applicant_id: uuid.UUID,
    data: dict,
) -> TravelRequest:
    """创建差旅申请草稿。

    data 必填字段：
        brand_id, store_id, traveler_id,
        planned_start_date (date), planned_end_date (date),
        transport_mode (str, 默认 "train")
    可选字段：
        departure_city, destination_cities (list), planned_stores (list),
        task_type (str), inspection_task_id (uuid),
        estimated_cost_fen (int), notes (str)
    """
    log = logger.bind(tenant_id=str(tenant_id), applicant_id=str(applicant_id))

    planned_start: date = data["planned_start_date"]
    planned_end: date = data["planned_end_date"]
    if planned_end < planned_start:
        raise ValueError("planned_end_date must be >= planned_start_date")

    request = TravelRequest(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        brand_id=data["brand_id"],
        store_id=data["store_id"],
        traveler_id=data["traveler_id"],
        applicant_id=applicant_id,
        inspection_task_id=data.get("inspection_task_id"),
        task_type=data.get("task_type", "inspection"),
        departure_city=data.get("departure_city"),
        destination_cities=data.get("destination_cities", []),
        planned_stores=data.get("planned_stores", []),
        planned_start_date=planned_start,
        planned_end_date=planned_end,
        planned_days=_calc_planned_days(planned_start, planned_end),
        transport_mode=data.get("transport_mode", "train"),
        estimated_cost_fen=data.get("estimated_cost_fen", 0),
        status=TravelStatus.DRAFT.value,
        notes=data.get("notes"),
        applicable_standards={},
    )
    db.add(request)
    await db.flush()

    log.info(
        "travel_request_created",
        request_id=str(request.id),
        task_type=request.task_type,
        planned_days=request.planned_days,
    )
    return request


async def get_travel_request(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    request_id: uuid.UUID,
) -> TravelRequest:
    """查询单条差旅申请，预加载行程和分摊明细。

    Raises:
        LookupError: 不存在或跨租户访问。
    """
    stmt = (
        select(TravelRequest)
        .where(
            TravelRequest.id == request_id,
            TravelRequest.tenant_id == tenant_id,
            TravelRequest.is_deleted == False,  # noqa: E712
        )
        .options(
            selectinload(TravelRequest.itineraries),
            selectinload(TravelRequest.allocations),
        )
    )
    result = await db.execute(stmt)
    request = result.scalar_one_or_none()

    if request is None:
        raise LookupError(f"TravelRequest {request_id} not found for tenant {tenant_id}")

    return request


async def list_travel_requests(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    filters: dict,
) -> tuple[list[TravelRequest], int]:
    """列出差旅申请，支持多条件过滤，按 created_at DESC 排序。

    filters 支持字段：
        status (str), applicant_id (UUID), traveler_id (UUID),
        brand_id (UUID), store_id (UUID),
        date_from (date), date_to (date),
        page (int, 默认1), page_size (int, 默认20)

    Returns:
        (items, total_count)
    """
    base_where = [
        TravelRequest.tenant_id == tenant_id,
        TravelRequest.is_deleted == False,  # noqa: E712
    ]

    if filters.get("status"):
        base_where.append(TravelRequest.status == filters["status"])
    if filters.get("applicant_id"):
        base_where.append(TravelRequest.applicant_id == filters["applicant_id"])
    if filters.get("traveler_id"):
        base_where.append(TravelRequest.traveler_id == filters["traveler_id"])
    if filters.get("brand_id"):
        base_where.append(TravelRequest.brand_id == filters["brand_id"])
    if filters.get("store_id"):
        base_where.append(TravelRequest.store_id == filters["store_id"])
    if filters.get("date_from"):
        base_where.append(TravelRequest.planned_start_date >= filters["date_from"])
    if filters.get("date_to"):
        base_where.append(TravelRequest.planned_end_date <= filters["date_to"])

    count_stmt = select(func.count()).select_from(TravelRequest).where(*base_where)
    count_result = await db.execute(count_stmt)
    total_count = count_result.scalar_one()

    page: int = max(int(filters.get("page", 1)), 1)
    page_size: int = min(int(filters.get("page_size", 20)), 100)
    offset = (page - 1) * page_size

    items_stmt = (
        select(TravelRequest)
        .where(*base_where)
        .order_by(TravelRequest.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    items_result = await db.execute(items_stmt)
    items = list(items_result.scalars().all())

    return items, total_count


async def update_travel_request(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    request_id: uuid.UUID,
    data: dict,
) -> TravelRequest:
    """更新草稿差旅申请（仅 DRAFT 状态允许编辑）。

    可更新字段：departure_city, destination_cities, planned_stores,
        planned_start_date, planned_end_date, transport_mode,
        estimated_cost_fen, notes, task_type
    """
    request = await get_travel_request(db, tenant_id, request_id)

    if request.status != TravelStatus.DRAFT.value:
        raise ValueError(
            f"Cannot update travel request in status '{request.status}'. Only DRAFT requests can be edited."
        )

    allowed_fields = {
        "departure_city",
        "destination_cities",
        "planned_stores",
        "transport_mode",
        "estimated_cost_fen",
        "notes",
        "task_type",
    }
    for field in allowed_fields:
        if field in data:
            setattr(request, field, data[field])

    # 若日期变更，同步重算天数
    if "planned_start_date" in data or "planned_end_date" in data:
        new_start = data.get("planned_start_date", request.planned_start_date)
        new_end = data.get("planned_end_date", request.planned_end_date)
        if new_end < new_start:
            raise ValueError("planned_end_date must be >= planned_start_date")
        request.planned_start_date = new_start
        request.planned_end_date = new_end
        request.planned_days = _calc_planned_days(new_start, new_end)

    await db.flush()

    logger.info(
        "travel_request_updated",
        tenant_id=str(tenant_id),
        request_id=str(request_id),
        updated_fields=list(data.keys()),
    )
    return request


async def submit_travel_request(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    request_id: uuid.UUID,
    applicant_id: uuid.UUID,
) -> TravelRequest:
    """提交差旅申请（DRAFT → PENDING_APPROVAL）。

    提交时固化申请人信息到 applicable_standards 快照中。
    """
    request = await get_travel_request(db, tenant_id, request_id)

    if request.status != TravelStatus.DRAFT.value:
        raise ValueError(
            f"Cannot submit travel request in status '{request.status}'. Only DRAFT requests can be submitted."
        )

    # 校验申请人匹配
    if request.applicant_id != applicant_id:
        raise ValueError(f"Only the applicant ({request.applicant_id}) can submit this travel request.")

    # 快照提交时的申请状态
    request.status = TravelStatus.PENDING_APPROVAL.value
    request.applicable_standards = {
        **(request.applicable_standards or {}),
        "submitted_at": _now_utc().isoformat(),
        "planned_days": request.planned_days,
        "transport_mode": request.transport_mode,
    }
    await db.flush()

    logger.info(
        "travel_request_submitted",
        tenant_id=str(tenant_id),
        request_id=str(request_id),
        applicant_id=str(applicant_id),
        planned_days=request.planned_days,
    )
    return request


# ─────────────────────────────────────────────────────────────────────────────
# 行程明细 CRUD
# ─────────────────────────────────────────────────────────────────────────────


async def add_itinerary(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    request_id: uuid.UUID,
    data: dict,
) -> TravelItinerary:
    """向差旅申请添加行程明细。

    data 必填：store_id (UUID)
    可选：store_name, sequence_order (int), checkin_time, checkout_time,
          leg_mileage_km, itinerary_status
    """
    request = await get_travel_request(db, tenant_id, request_id)

    # 允许 DRAFT / APPROVED 状态添加行程（审批通过后才能实际出行签到）
    if request.status not in (TravelStatus.DRAFT.value, TravelStatus.APPROVED.value, TravelStatus.IN_PROGRESS.value):
        raise ValueError(f"Cannot add itinerary to travel request in status '{request.status}'.")

    # 自动推算下一个 sequence_order
    max_order_stmt = select(func.coalesce(func.max(TravelItinerary.sequence_order), -1)).where(
        TravelItinerary.travel_request_id == request_id,
        TravelItinerary.tenant_id == tenant_id,
    )
    max_order_result = await db.execute(max_order_stmt)
    next_order = (max_order_result.scalar_one() or -1) + 1

    itinerary = TravelItinerary(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        travel_request_id=request_id,
        store_id=data["store_id"],
        store_name=data.get("store_name"),
        sequence_order=data.get("sequence_order", next_order),
        checkin_time=data.get("checkin_time"),
        checkout_time=data.get("checkout_time"),
        leg_mileage_km=data.get("leg_mileage_km"),
        itinerary_status=data.get("itinerary_status", "planned"),
        gps_track=[],
        is_mileage_anomaly=False,
    )
    db.add(itinerary)
    await db.flush()

    # 同步更新 planned_stores
    store_id_str = str(data["store_id"])
    if store_id_str not in [str(s) for s in (request.planned_stores or [])]:
        request.planned_stores = list(request.planned_stores or []) + [store_id_str]
        await db.flush()

    logger.info(
        "travel_itinerary_added",
        tenant_id=str(tenant_id),
        request_id=str(request_id),
        itinerary_id=str(itinerary.id),
        store_id=str(data["store_id"]),
        sequence_order=itinerary.sequence_order,
    )
    return itinerary


async def update_itinerary(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    request_id: uuid.UUID,
    itinerary_id: uuid.UUID,
    data: dict,
) -> TravelItinerary:
    """更新行程明细。

    可更新字段：store_name, checkin_time, checkout_time, duration_minutes,
        checkin_location, checkout_location, gps_track,
        leg_mileage_km, itinerary_status, skip_reason, sequence_order
    """
    stmt = select(TravelItinerary).where(
        TravelItinerary.id == itinerary_id,
        TravelItinerary.travel_request_id == request_id,
        TravelItinerary.tenant_id == tenant_id,
    )
    result = await db.execute(stmt)
    itinerary = result.scalar_one_or_none()

    if itinerary is None:
        raise LookupError(f"TravelItinerary {itinerary_id} not found for request {request_id} and tenant {tenant_id}")

    allowed_fields = {
        "store_name",
        "checkin_time",
        "checkout_time",
        "duration_minutes",
        "checkin_location",
        "checkout_location",
        "gps_track",
        "leg_mileage_km",
        "itinerary_status",
        "skip_reason",
        "sequence_order",
        "distance_from_store_m",
        "is_mileage_anomaly",
        "anomaly_reason",
    }
    for field in allowed_fields:
        if field in data:
            setattr(itinerary, field, data[field])

    # 若签到/签退时间均有值，自动计算停留时长
    if itinerary.checkin_time and itinerary.checkout_time:
        delta = itinerary.checkout_time - itinerary.checkin_time
        itinerary.duration_minutes = max(int(delta.total_seconds() / 60), 0)

    await db.flush()

    logger.info(
        "travel_itinerary_updated",
        tenant_id=str(tenant_id),
        request_id=str(request_id),
        itinerary_id=str(itinerary_id),
        updated_fields=list(data.keys()),
    )
    return itinerary


async def delete_itinerary(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    request_id: uuid.UUID,
    itinerary_id: uuid.UUID,
) -> None:
    """删除行程明细（仅 DRAFT 状态允许删除）。"""
    request = await get_travel_request(db, tenant_id, request_id)

    if request.status != TravelStatus.DRAFT.value:
        raise ValueError(
            f"Cannot delete itinerary from travel request in status '{request.status}'. "
            "Only DRAFT requests allow itinerary deletion."
        )

    stmt = select(TravelItinerary).where(
        TravelItinerary.id == itinerary_id,
        TravelItinerary.travel_request_id == request_id,
        TravelItinerary.tenant_id == tenant_id,
    )
    result = await db.execute(stmt)
    itinerary = result.scalar_one_or_none()

    if itinerary is None:
        raise LookupError(f"TravelItinerary {itinerary_id} not found for request {request_id}")

    await db.delete(itinerary)
    await db.flush()

    logger.info(
        "travel_itinerary_deleted",
        tenant_id=str(tenant_id),
        request_id=str(request_id),
        itinerary_id=str(itinerary_id),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 补贴计算
# ─────────────────────────────────────────────────────────────────────────────

# 默认补贴标准（分/天），没有差标配置时使用
_DEFAULT_MEAL_ALLOWANCE_PER_DAY_FEN = 8000  # 餐补 80元/天
_DEFAULT_ACCOMMODATION_PER_DAY_FEN = 30000  # 住宿 300元/天（无差标时的兜底）


async def calculate_allowances(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    request_id: uuid.UUID,
) -> dict:
    """计算差旅补贴（餐补 + 住宿补贴）。

    逻辑：
    1. 获取差旅申请的天数和目的地城市
    2. 尝试通过 expense_standard_service 查询城市差标
    3. 按天数计算各项补贴

    Returns:
        {
            "planned_days": int,
            "meal_allowance_fen": int,        # 餐补总额（分）
            "accommodation_fen": int,          # 住宿补贴总额（分）
            "total_allowance_fen": int,        # 合计（分）
            "per_day": {
                "meal_fen": int,
                "accommodation_fen": int,
            },
            "standards_applied": bool,         # 是否应用了差标规则
            "destination_city": str | None,
            "city_tier": str | None,
        }
    """
    request = await get_travel_request(db, tenant_id, request_id)
    days = request.planned_days or 1

    # 尝试解析目的地城市（取第一个目的地）
    destination_city: Optional[str] = None
    destination_cities = request.destination_cities or []
    if destination_cities:
        destination_city = str(destination_cities[0])

    # 尝试通过差标服务查询城市住宿/餐补标准
    meal_per_day_fen = _DEFAULT_MEAL_ALLOWANCE_PER_DAY_FEN
    accommodation_per_day_fen = _DEFAULT_ACCOMMODATION_PER_DAY_FEN
    city_tier: Optional[str] = None
    standards_applied = False

    if destination_city and request.staff_level:
        try:
            import src.services.expense_standard_service as _std_svc  # 延迟导入避免循环

            # 查询住宿差标
            accom_standard = await _std_svc.find_standard(
                db=db,
                tenant_id=tenant_id,
                brand_id=request.brand_id,
                staff_level=request.staff_level,
                destination_city=destination_city,
                expense_type="accommodation",
            )
            if accom_standard:
                accommodation_per_day_fen = accom_standard.daily_limit
                city_tier = getattr(accom_standard, "city_tier", None)
                standards_applied = True

            # 查询餐补差标
            meal_standard = await _std_svc.find_standard(
                db=db,
                tenant_id=tenant_id,
                brand_id=request.brand_id,
                staff_level=request.staff_level,
                destination_city=destination_city,
                expense_type="meal",
            )
            if meal_standard:
                meal_per_day_fen = meal_standard.daily_limit
                standards_applied = True

        except (ImportError, AttributeError, LookupError) as exc:
            # 差标查询失败时使用默认值，不阻断流程
            logger.warning(
                "travel_allowance_standard_lookup_failed",
                tenant_id=str(tenant_id),
                request_id=str(request_id),
                destination_city=destination_city,
                error=str(exc),
            )

    meal_total_fen = meal_per_day_fen * days
    accommodation_total_fen = accommodation_per_day_fen * days
    total_allowance_fen = meal_total_fen + accommodation_total_fen

    logger.info(
        "travel_allowances_calculated",
        tenant_id=str(tenant_id),
        request_id=str(request_id),
        days=days,
        meal_total_fen=meal_total_fen,
        accommodation_total_fen=accommodation_total_fen,
        standards_applied=standards_applied,
    )

    return {
        "planned_days": days,
        "meal_allowance_fen": meal_total_fen,
        "accommodation_fen": accommodation_total_fen,
        "total_allowance_fen": total_allowance_fen,
        "per_day": {
            "meal_fen": meal_per_day_fen,
            "accommodation_fen": accommodation_per_day_fen,
        },
        "standards_applied": standards_applied,
        "destination_city": destination_city,
        "city_tier": city_tier,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 完成差旅（填写实际费用）
# ─────────────────────────────────────────────────────────────────────────────


async def complete_travel(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    request_id: uuid.UUID,
    actual_amounts: dict,
) -> TravelRequest:
    """完成差旅，填写实际费用（IN_PROGRESS → COMPLETED）。

    actual_amounts 字段：
        actual_start_date (date), actual_end_date (date),
        total_cost_fen (int),
        mileage_allowance_fen (int, 可选),
        total_mileage_km (Decimal, 可选)
    完成后自动按行程时长分摊费用到各门店。
    """
    request = await get_travel_request(db, tenant_id, request_id)

    if request.status not in (TravelStatus.IN_PROGRESS.value, TravelStatus.APPROVED.value):
        raise ValueError(
            f"Cannot complete travel request in status '{request.status}'. Request must be IN_PROGRESS or APPROVED."
        )

    actual_start: Optional[date] = actual_amounts.get("actual_start_date")
    actual_end: Optional[date] = actual_amounts.get("actual_end_date")

    if actual_start and actual_end and actual_end < actual_start:
        raise ValueError("actual_end_date must be >= actual_start_date")

    if actual_start:
        request.actual_start_date = actual_start
    if actual_end:
        request.actual_end_date = actual_end
    if actual_start and actual_end:
        request.actual_days = _calc_planned_days(actual_start, actual_end)

    if "total_cost_fen" in actual_amounts:
        request.total_cost_fen = int(actual_amounts["total_cost_fen"])
    if "mileage_allowance_fen" in actual_amounts:
        request.mileage_allowance_fen = int(actual_amounts["mileage_allowance_fen"])
    if "total_mileage_km" in actual_amounts:
        request.total_mileage_km = Decimal(str(actual_amounts["total_mileage_km"]))

    request.status = TravelStatus.COMPLETED.value
    await db.flush()

    # 自动计算门店分摊
    try:
        await _auto_allocate(db, tenant_id, request)
    except (SQLAlchemyError, ValueError) as exc:
        logger.error(
            "travel_auto_allocation_failed",
            tenant_id=str(tenant_id),
            request_id=str(request_id),
            error=str(exc),
            exc_info=True,
        )

    logger.info(
        "travel_request_completed",
        tenant_id=str(tenant_id),
        request_id=str(request_id),
        total_cost_fen=request.total_cost_fen,
        actual_days=request.actual_days,
    )
    return request


async def _auto_allocate(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    request: TravelRequest,
) -> None:
    """按各门店实际签到时长自动分摊差旅费用到门店成本中心。

    分摊规则：
    - 有实际签到时长（duration_minutes > 0）：按时长比例分摊（duration模式）
    - 否则：平均分摊（equal模式）
    """
    total_cost_fen = request.total_cost_fen or 0
    if total_cost_fen <= 0:
        return

    # 查询所有已完成的行程（有签到/签退记录）
    itinerary_stmt = select(TravelItinerary).where(
        TravelItinerary.travel_request_id == request.id,
        TravelItinerary.tenant_id == tenant_id,
    )
    itinerary_result = await db.execute(itinerary_stmt)
    itineraries = list(itinerary_result.scalars().all())

    if not itineraries:
        return

    # 去重：同一个门店可能有多条记录，合并时长
    store_durations: dict[str, int] = {}
    for itin in itineraries:
        sid = str(itin.store_id)
        store_durations[sid] = store_durations.get(sid, 0) + (itin.duration_minutes or 0)

    total_duration = sum(store_durations.values())
    allocation_basis = "duration" if total_duration > 0 else "equal"

    # 清除旧分摊记录
    old_alloc_stmt = select(TravelAllocation).where(
        TravelAllocation.travel_request_id == request.id,
        TravelAllocation.tenant_id == tenant_id,
    )
    old_alloc_result = await db.execute(old_alloc_stmt)
    old_allocs = old_alloc_result.scalars().all()
    for old in old_allocs:
        await db.delete(old)
    await db.flush()

    store_ids = list(store_durations.keys())
    n = len(store_ids)
    allocations = []

    for idx, store_id_str in enumerate(store_ids):
        duration = store_durations[store_id_str]

        if allocation_basis == "duration":
            rate = Decimal(str(duration)) / Decimal(str(total_duration))
        else:
            # 最后一个门店取剩余，保证总额精确
            rate = Decimal("1") / Decimal(str(n))

        # 最后一条确保总额准确（消除四舍五入误差）
        if idx == n - 1:
            already_allocated = sum(a.allocated_amount_fen for a in allocations)
            allocated_fen = total_cost_fen - already_allocated
        else:
            allocated_fen = int(Decimal(str(total_cost_fen)) * rate)

        alloc = TravelAllocation(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            travel_request_id=request.id,
            store_id=uuid.UUID(store_id_str),
            brand_id=request.brand_id,
            allocation_basis=allocation_basis,
            basis_value=Decimal(str(duration)) if allocation_basis == "duration" else None,
            allocation_rate=rate,
            total_travel_cost_fen=total_cost_fen,
            allocated_amount_fen=allocated_fen,
            is_attributed=False,
        )
        allocations.append(alloc)

    db.add_all(allocations)
    await db.flush()

    logger.info(
        "travel_allocations_created",
        tenant_id=str(tenant_id),
        request_id=str(request.id),
        store_count=len(allocations),
        allocation_basis=allocation_basis,
        total_cost_fen=total_cost_fen,
    )


# ─────────────────────────────────────────────────────────────────────────────
# A5 专用：从巡店任务自动创建差旅申请草稿
# ─────────────────────────────────────────────────────────────────────────────


async def create_from_inspection_task(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    task_data: dict,
) -> TravelRequest:
    """从巡店任务数据创建差旅申请草稿（A5 Agent 专用）。

    task_data 结构（来自 tx-ops 巡店任务事件）：
        task_id (str/UUID)          - 巡店任务ID
        supervisor_id (str/UUID)    - 督导员工ID
        brand_id (str/UUID)         - 品牌ID
        store_id (str/UUID)         - 督导所属门店（申请人所属门店）
        target_stores (list[dict])  - 计划巡查的门店列表，每个元素含：
                                        store_id, store_name, city
        departure_city (str)        - 出发城市
        planned_start_date (str/date) - 计划出发日期
        planned_end_date (str/date)  - 计划返回日期（可选，默认等于开始日期）
        transport_mode (str)        - 交通方式（可选，默认 "train"）
        notes (str)                 - 备注（可选）

    Returns:
        新创建的 TravelRequest（status=DRAFT），含初始行程明细。

    Raises:
        ValueError: 必填字段缺失。
        LookupError: 已存在关联此任务的差旅申请时抛出（防重复创建）。
    """
    log = logger.bind(tenant_id=str(tenant_id), task_id=str(task_data.get("task_id")))

    # 必填字段校验
    required_keys = ("task_id", "supervisor_id", "brand_id", "store_id", "planned_start_date")
    missing = [k for k in required_keys if not task_data.get(k)]
    if missing:
        raise ValueError(f"Missing required fields in task_data: {missing}")

    # 解析字段
    task_id = uuid.UUID(str(task_data["task_id"]))
    supervisor_id = uuid.UUID(str(task_data["supervisor_id"]))
    brand_id = uuid.UUID(str(task_data["brand_id"]))
    store_id = uuid.UUID(str(task_data["store_id"]))

    # 日期处理
    raw_start = task_data["planned_start_date"]
    if isinstance(raw_start, str):
        planned_start = date.fromisoformat(raw_start)
    else:
        planned_start = raw_start

    raw_end = task_data.get("planned_end_date", raw_start)
    if isinstance(raw_end, str):
        planned_end = date.fromisoformat(raw_end)
    else:
        planned_end = raw_end or planned_start

    # 幂等保护：已存在时直接返回，避免重复创建
    existing_stmt = select(TravelRequest).where(
        TravelRequest.tenant_id == tenant_id,
        TravelRequest.inspection_task_id == task_id,
        TravelRequest.is_deleted == False,  # noqa: E712
    )
    existing_result = await db.execute(existing_stmt)
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        log.info(
            "travel_request_already_exists_for_task",
            request_id=str(existing.id),
            status=existing.status,
        )
        return existing

    # 提取目的地城市列表
    target_stores: list[dict] = task_data.get("target_stores", [])
    destination_cities = list({s["city"] for s in target_stores if s.get("city")})
    planned_store_ids = [str(s["store_id"]) for s in target_stores if s.get("store_id")]

    # 创建差旅申请
    request = TravelRequest(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        brand_id=brand_id,
        store_id=store_id,
        traveler_id=supervisor_id,
        applicant_id=supervisor_id,  # 督导本人申请
        inspection_task_id=task_id,
        task_type="inspection",
        departure_city=task_data.get("departure_city"),
        destination_cities=destination_cities,
        planned_stores=planned_store_ids,
        planned_start_date=planned_start,
        planned_end_date=planned_end,
        planned_days=_calc_planned_days(planned_start, planned_end),
        transport_mode=task_data.get("transport_mode", "train"),
        estimated_cost_fen=0,
        status=TravelStatus.DRAFT.value,
        notes=task_data.get("notes") or f"由巡店任务 {task_id} 自动生成",
        applicable_standards={
            "source": "auto_generated",
            "task_id": str(task_id),
            "created_by": "a5_travel_assistant",
        },
    )
    db.add(request)
    await db.flush()

    # 为每个目标门店创建行程明细
    for idx, target_store in enumerate(target_stores):
        if not target_store.get("store_id"):
            continue
        itinerary = TravelItinerary(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            travel_request_id=request.id,
            store_id=uuid.UUID(str(target_store["store_id"])),
            store_name=target_store.get("store_name"),
            sequence_order=idx,
            itinerary_status="planned",
            gps_track=[],
            is_mileage_anomaly=False,
        )
        db.add(itinerary)

    await db.flush()

    log.info(
        "travel_request_created_from_inspection_task",
        request_id=str(request.id),
        task_id=str(task_id),
        supervisor_id=str(supervisor_id),
        target_store_count=len(target_stores),
        planned_days=request.planned_days,
    )
    return request


# ─────────────────────────────────────────────────────────────────────────────
# 统计看板
# ─────────────────────────────────────────────────────────────────────────────


async def get_stats(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    filters: dict,
) -> dict:
    """差旅统计看板。

    filters 支持：brand_id (UUID), store_id (UUID),
                  date_from (date), date_to (date)

    Returns:
        {
            "total_count": int,
            "total_estimated_cost_fen": int,
            "total_actual_cost_fen": int,
            "by_status": {status: count},
            "by_transport_mode": {mode: count},
            "avg_days": float,
            "pending_count": int,     # 待审批数
            "in_progress_count": int, # 出行中数
        }
    """
    base_where = [
        TravelRequest.tenant_id == tenant_id,
        TravelRequest.is_deleted == False,  # noqa: E712
    ]

    if filters.get("brand_id"):
        base_where.append(TravelRequest.brand_id == filters["brand_id"])
    if filters.get("store_id"):
        base_where.append(TravelRequest.store_id == filters["store_id"])
    if filters.get("date_from"):
        base_where.append(TravelRequest.planned_start_date >= filters["date_from"])
    if filters.get("date_to"):
        base_where.append(TravelRequest.planned_end_date <= filters["date_to"])

    # 总数 + 总费用
    total_stmt = select(
        func.count().label("total_count"),
        func.coalesce(func.sum(TravelRequest.estimated_cost_fen), 0).label("total_estimated_cost_fen"),
        func.coalesce(func.sum(TravelRequest.total_cost_fen), 0).label("total_actual_cost_fen"),
        func.coalesce(func.avg(TravelRequest.planned_days), 0).label("avg_days"),
    ).where(*base_where)
    total_result = await db.execute(total_stmt)
    total_row = total_result.mappings().one()

    # 按状态分组
    by_status_stmt = (
        select(TravelRequest.status, func.count().label("count")).where(*base_where).group_by(TravelRequest.status)
    )
    by_status_result = await db.execute(by_status_stmt)
    by_status = {row["status"]: int(row["count"]) for row in by_status_result.mappings().all()}

    # 按交通方式分组
    by_transport_stmt = (
        select(TravelRequest.transport_mode, func.count().label("count"))
        .where(*base_where)
        .group_by(TravelRequest.transport_mode)
    )
    by_transport_result = await db.execute(by_transport_stmt)
    by_transport = {row["transport_mode"]: int(row["count"]) for row in by_transport_result.mappings().all()}

    pending_count = by_status.get(TravelStatus.PENDING_APPROVAL.value, 0)
    in_progress_count = by_status.get(TravelStatus.IN_PROGRESS.value, 0)

    return {
        "total_count": int(total_row["total_count"]),
        "total_estimated_cost_fen": int(total_row["total_estimated_cost_fen"]),
        "total_actual_cost_fen": int(total_row["total_actual_cost_fen"]),
        "avg_days": float(total_row["avg_days"]),
        "by_status": by_status,
        "by_transport_mode": by_transport,
        "pending_count": pending_count,
        "in_progress_count": in_progress_count,
    }
