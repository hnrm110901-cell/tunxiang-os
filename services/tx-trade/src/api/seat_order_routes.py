"""座位点单 API Routes"""
from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.seat_order_service import (
    OrderSeat,
    SeatSummary,
    SplitBill,
    assign_item_to_seat,
    calculate_split,
    generate_self_pay_link,
    get_seat_summary,
    init_seats,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/orders", tags=["seat-order"])


# ─── 请求体 ───

class InitSeatsBody(BaseModel):
    seat_count: int = Field(..., ge=1, le=20)


class AssignSeatBody(BaseModel):
    seat_no: Optional[int] = Field(None, ge=1, le=20)
    seat_label: Optional[str] = Field(None, max_length=50)


class CalculateSplitBody(BaseModel):
    split_mode: str = Field(..., pattern="^(individual|grouped|equal)$")
    seat_groups: Optional[list[list[int]]] = None


# ─── 响应体 ───

class SeatsResponse(BaseModel):
    ok: bool = True
    data: list[OrderSeat]


class SeatSummaryResponse(BaseModel):
    ok: bool = True
    data: list[SeatSummary]


class SplitBillResponse(BaseModel):
    ok: bool = True
    data: list[SplitBill]


class SelfPayLinkResponse(BaseModel):
    ok: bool = True
    data: dict


# ─── 路由 ───

@router.post("/{order_id}/seats/init", response_model=SeatsResponse, status_code=status.HTTP_201_CREATED)
async def init_order_seats(
    order_id: UUID,
    body: InitSeatsBody,
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    try:
        seats = await init_seats(
            order_id=order_id,
            seat_count=body.seat_count,
            tenant_id=x_tenant_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except IntegrityError as exc:
        log.error("init_seats_db_error", order_id=str(order_id), error=str(exc))
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="座位初始化冲突，请勿重复调用")
    return SeatsResponse(data=seats)


@router.get("/{order_id}/seats", response_model=SeatSummaryResponse)
async def list_order_seats(
    order_id: UUID,
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    summaries = await get_seat_summary(order_id=order_id, tenant_id=x_tenant_id, db=db)
    return SeatSummaryResponse(data=summaries)


@router.patch("/{order_id}/items/{item_id}/seat", status_code=status.HTTP_200_OK)
async def assign_item_seat(
    order_id: UUID,
    item_id: UUID,
    body: AssignSeatBody,
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    try:
        await assign_item_to_seat(
            order_item_id=item_id,
            seat_no=body.seat_no,
            seat_label=body.seat_label,
            tenant_id=x_tenant_id,
            db=db,
        )
    except NoResultFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return {"ok": True, "data": {"item_id": str(item_id), "seat_no": body.seat_no}}


@router.post("/{order_id}/seats/calculate-split", response_model=SplitBillResponse)
async def calculate_order_split(
    order_id: UUID,
    body: CalculateSplitBody,
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    try:
        bills = await calculate_split(
            order_id=order_id,
            split_mode=body.split_mode,
            seat_groups=body.seat_groups,
            tenant_id=x_tenant_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return SplitBillResponse(data=bills)


@router.post("/{order_id}/seats/{seat_no}/self-pay-link", response_model=SelfPayLinkResponse)
async def get_self_pay_link(
    order_id: UUID,
    seat_no: int,
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    try:
        token = await generate_self_pay_link(
            order_id=order_id,
            seat_no=seat_no,
            tenant_id=x_tenant_id,
            db=db,
        )
    except NoResultFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return SelfPayLinkResponse(data={"token": token, "order_id": str(order_id), "seat_no": seat_no})
