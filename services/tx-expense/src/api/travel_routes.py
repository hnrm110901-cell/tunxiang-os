"""
差旅费用 API 路由

负责差旅申请全生命周期管理。
共12个端点：创建/列表/详情/更新/提交/行程管理/补贴计算/完成结算/统计/分摊。

金额约定：所有金额字段单位为分(fen)，1元=100分。
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
import src.services.travel_expense_service as _travel_svc

router = APIRouter()
log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 依赖注入
# ---------------------------------------------------------------------------

async def get_tenant_id(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> UUID:
    try:
        return UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的租户ID格式")


async def get_current_user(x_user_id: str = Header(..., alias="X-User-ID")) -> UUID:
    try:
        return UUID(x_user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的用户ID格式")


# ---------------------------------------------------------------------------
# Pydantic Schema
# ---------------------------------------------------------------------------

class TravelRequestCreate(BaseModel):
    brand_id: UUID
    store_id: UUID
    traveler_id: UUID
    planned_start_date: date
    planned_end_date: date
    departure_city: Optional[str] = None
    destination_cities: List[str] = []
    planned_stores: List[str] = []
    task_type: str = "inspection"
    transport_mode: str = "train"
    estimated_cost_fen: int = Field(0, ge=0, description="预估总费用，单位：分(fen)")
    inspection_task_id: Optional[UUID] = None
    notes: Optional[str] = None


class TravelRequestUpdate(BaseModel):
    departure_city: Optional[str] = None
    destination_cities: Optional[List[str]] = None
    planned_stores: Optional[List[str]] = None
    planned_start_date: Optional[date] = None
    planned_end_date: Optional[date] = None
    transport_mode: Optional[str] = None
    estimated_cost_fen: Optional[int] = Field(None, ge=0)
    notes: Optional[str] = None
    task_type: Optional[str] = None


class TravelItineraryCreate(BaseModel):
    store_id: UUID
    store_name: Optional[str] = None
    sequence_order: Optional[int] = None
    itinerary_status: str = "planned"


class TravelItineraryUpdate(BaseModel):
    store_name: Optional[str] = None
    checkin_time: Optional[str] = None          # ISO 8601 字符串，由服务层解析
    checkout_time: Optional[str] = None
    duration_minutes: Optional[int] = None
    checkin_location: Optional[Dict[str, Any]] = None
    checkout_location: Optional[Dict[str, Any]] = None
    gps_track: Optional[List[Dict[str, Any]]] = None
    leg_mileage_km: Optional[str] = None        # Decimal 字符串
    itinerary_status: Optional[str] = None
    skip_reason: Optional[str] = None
    sequence_order: Optional[int] = None
    distance_from_store_m: Optional[int] = None
    is_mileage_anomaly: Optional[bool] = None
    anomaly_reason: Optional[str] = None


class CompleteTravel(BaseModel):
    actual_start_date: Optional[date] = None
    actual_end_date: Optional[date] = None
    total_cost_fen: int = Field(..., ge=0, description="实际总费用，单位：分(fen)")
    mileage_allowance_fen: Optional[int] = Field(None, ge=0, description="里程补贴，单位：分(fen)")
    total_mileage_km: Optional[str] = None      # Decimal 字符串


class PaginatedResponse(BaseModel):
    data: List[Any]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# 端点实现
# ---------------------------------------------------------------------------

@router.post("/requests", status_code=status.HTTP_201_CREATED)
async def create_travel_request(
    body: TravelRequestCreate,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    创建差旅申请（草稿状态）

    - 金额字段 estimated_cost_fen 单位为分(fen)，例如：50000分 = 500元
    - 创建后状态为 draft，调用 /submit 提交审批
    - inspection_task_id 不为空时关联巡店任务（A5自动生成时使用）
    """
    try:
        data = body.model_dump()
        result = await _travel_svc.create_travel_request(
            db=db,
            tenant_id=tenant_id,
            applicant_id=current_user_id,
            data=data,
        )
        await db.commit()
        log.info(
            "travel_request_created_via_api",
            tenant_id=str(tenant_id),
            request_id=str(result.id),
        )
        return {"ok": True, "data": _serialize_request(result)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.error("travel_request_create_failed", error=str(exc), tenant_id=str(tenant_id), exc_info=True)
        raise HTTPException(status_code=500, detail="创建差旅申请失败，请稍后重试")


@router.get("/requests")
async def list_travel_requests(
    travel_status: Optional[str] = Query(None, alias="status", description="状态过滤"),
    applicant_id: Optional[UUID] = Query(None, description="申请人ID过滤"),
    traveler_id: Optional[UUID] = Query(None, description="出行人ID过滤"),
    brand_id: Optional[UUID] = Query(None, description="品牌ID过滤"),
    store_id: Optional[UUID] = Query(None, description="门店ID过滤"),
    date_from: Optional[date] = Query(None, description="计划出发日期起始（含）"),
    date_to: Optional[date] = Query(None, description="计划返回日期截止（含）"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse:
    """
    查询差旅申请列表

    支持按状态、申请人、出行人、品牌、门店、日期范围过滤，支持分页。
    """
    try:
        filters = {
            k: v for k, v in {
                "status": travel_status,
                "applicant_id": applicant_id,
                "traveler_id": traveler_id,
                "brand_id": brand_id,
                "store_id": store_id,
                "date_from": date_from,
                "date_to": date_to,
                "page": page,
                "page_size": page_size,
            }.items() if v is not None
        }
        items, total = await _travel_svc.list_travel_requests(
            db=db,
            tenant_id=tenant_id,
            filters=filters,
        )
        return PaginatedResponse(
            data=[_serialize_request(r) for r in items],
            total=total,
            page=page,
            page_size=page_size,
        )
    except Exception as exc:
        log.error("travel_requests_list_failed", error=str(exc), tenant_id=str(tenant_id), exc_info=True)
        raise HTTPException(status_code=500, detail="查询差旅申请列表失败，请稍后重试")


@router.get("/requests/{request_id}")
async def get_travel_request(
    request_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """获取差旅申请详情（含行程明细和费用分摊）"""
    try:
        result = await _travel_svc.get_travel_request(
            db=db, tenant_id=tenant_id, request_id=request_id
        )
        return {"ok": True, "data": _serialize_request(result, with_relations=True)}
    except LookupError:
        raise HTTPException(status_code=404, detail="差旅申请不存在或无权访问")
    except Exception as exc:
        log.error("travel_request_get_failed", error=str(exc), request_id=str(request_id), exc_info=True)
        raise HTTPException(status_code=500, detail="获取差旅申请详情失败，请稍后重试")


@router.put("/requests/{request_id}")
async def update_travel_request(
    request_id: UUID,
    body: TravelRequestUpdate,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    更新草稿差旅申请

    - 只允许 draft 状态的申请进行更新
    - 日期变更会自动重算计划天数
    """
    try:
        data = {k: v for k, v in body.model_dump().items() if v is not None}
        result = await _travel_svc.update_travel_request(
            db=db,
            tenant_id=tenant_id,
            request_id=request_id,
            data=data,
        )
        await db.commit()
        log.info("travel_request_updated_via_api", request_id=str(request_id), tenant_id=str(tenant_id))
        return {"ok": True, "data": _serialize_request(result)}
    except LookupError:
        raise HTTPException(status_code=404, detail="差旅申请不存在或无权修改")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.error("travel_request_update_failed", error=str(exc), request_id=str(request_id), exc_info=True)
        raise HTTPException(status_code=500, detail="更新差旅申请失败，请稍后重试")


@router.post("/requests/{request_id}/submit")
async def submit_travel_request(
    request_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    提交差旅申请（触发审批流）

    - 只允许申请人本人提交 draft 状态的申请
    - 提交后状态变为 pending_approval
    """
    try:
        result = await _travel_svc.submit_travel_request(
            db=db,
            tenant_id=tenant_id,
            request_id=request_id,
            applicant_id=current_user_id,
        )
        await db.commit()
        log.info("travel_request_submitted_via_api", request_id=str(request_id), tenant_id=str(tenant_id))
        return {"ok": True, "data": _serialize_request(result)}
    except LookupError:
        raise HTTPException(status_code=404, detail="差旅申请不存在或无权提交")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.error("travel_request_submit_failed", error=str(exc), request_id=str(request_id), exc_info=True)
        raise HTTPException(status_code=500, detail="提交差旅申请失败，请稍后重试")


@router.post("/requests/{request_id}/itineraries", status_code=status.HTTP_201_CREATED)
async def add_itinerary(
    request_id: UUID,
    body: TravelItineraryCreate,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    添加行程明细

    - 草稿/已批准/出行中状态均可添加
    - sequence_order 不传时自动追加到末尾
    """
    try:
        result = await _travel_svc.add_itinerary(
            db=db,
            tenant_id=tenant_id,
            request_id=request_id,
            data=body.model_dump(),
        )
        await db.commit()
        log.info(
            "travel_itinerary_added_via_api",
            request_id=str(request_id),
            itinerary_id=str(result.id),
        )
        return {"ok": True, "data": _serialize_itinerary(result)}
    except LookupError:
        raise HTTPException(status_code=404, detail="差旅申请不存在或无权操作")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.error("travel_itinerary_add_failed", error=str(exc), request_id=str(request_id), exc_info=True)
        raise HTTPException(status_code=500, detail="添加行程明细失败，请稍后重试")


@router.put("/requests/{request_id}/itineraries/{itinerary_id}")
async def update_itinerary(
    request_id: UUID,
    itinerary_id: UUID,
    body: TravelItineraryUpdate,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    更新行程明细

    - 支持签到/签退时间更新（自动计算停留时长）
    - 支持GPS轨迹数据更新
    """
    try:
        data = {k: v for k, v in body.model_dump().items() if v is not None}
        result = await _travel_svc.update_itinerary(
            db=db,
            tenant_id=tenant_id,
            request_id=request_id,
            itinerary_id=itinerary_id,
            data=data,
        )
        await db.commit()
        return {"ok": True, "data": _serialize_itinerary(result)}
    except LookupError:
        raise HTTPException(status_code=404, detail="行程明细不存在或无权操作")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.error("travel_itinerary_update_failed", error=str(exc), itinerary_id=str(itinerary_id), exc_info=True)
        raise HTTPException(status_code=500, detail="更新行程明细失败，请稍后重试")


@router.delete("/requests/{request_id}/itineraries/{itinerary_id}")
async def delete_itinerary(
    request_id: UUID,
    itinerary_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    删除行程明细

    - 只允许 draft 状态的申请删除行程
    """
    try:
        await _travel_svc.delete_itinerary(
            db=db,
            tenant_id=tenant_id,
            request_id=request_id,
            itinerary_id=itinerary_id,
        )
        await db.commit()
        log.info(
            "travel_itinerary_deleted_via_api",
            request_id=str(request_id),
            itinerary_id=str(itinerary_id),
        )
        return {"ok": True, "message": "行程明细已删除"}
    except LookupError:
        raise HTTPException(status_code=404, detail="行程明细不存在或无权操作")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.error("travel_itinerary_delete_failed", error=str(exc), itinerary_id=str(itinerary_id), exc_info=True)
        raise HTTPException(status_code=500, detail="删除行程明细失败，请稍后重试")


@router.get("/requests/{request_id}/allowances")
async def get_allowances(
    request_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    查看差旅补贴计算

    - 按计划天数和目的地城市差标计算餐补 + 住宿补贴
    - 无差标配置时使用系统默认值（餐补80元/天，住宿300元/天）
    - 金额单位为分(fen)
    """
    try:
        result = await _travel_svc.calculate_allowances(
            db=db, tenant_id=tenant_id, request_id=request_id
        )
        return {"ok": True, "data": result}
    except LookupError:
        raise HTTPException(status_code=404, detail="差旅申请不存在或无权访问")
    except Exception as exc:
        log.error("travel_allowances_failed", error=str(exc), request_id=str(request_id), exc_info=True)
        raise HTTPException(status_code=500, detail="计算差旅补贴失败，请稍后重试")


@router.post("/requests/{request_id}/complete")
async def complete_travel(
    request_id: UUID,
    body: CompleteTravel,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    完成差旅，填写实际费用（IN_PROGRESS/APPROVED → COMPLETED）

    - 填写实际出行日期和总费用后标记为已完成
    - 完成后自动按门店签到时长分摊差旅费用
    - 金额单位为分(fen)
    """
    try:
        actual_amounts = body.model_dump(exclude_none=True)
        result = await _travel_svc.complete_travel(
            db=db,
            tenant_id=tenant_id,
            request_id=request_id,
            actual_amounts=actual_amounts,
        )
        await db.commit()
        log.info(
            "travel_request_completed_via_api",
            request_id=str(request_id),
            total_cost_fen=result.total_cost_fen,
        )
        return {"ok": True, "data": _serialize_request(result, with_relations=True)}
    except LookupError:
        raise HTTPException(status_code=404, detail="差旅申请不存在或无权操作")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.error("travel_complete_failed", error=str(exc), request_id=str(request_id), exc_info=True)
        raise HTTPException(status_code=500, detail="完成差旅申请失败，请稍后重试")


@router.get("/stats")
async def get_travel_stats(
    brand_id: Optional[UUID] = Query(None, description="品牌ID（不传则汇总所有品牌）"),
    store_id: Optional[UUID] = Query(None, description="门店ID"),
    date_from: Optional[date] = Query(None, description="统计开始日期"),
    date_to: Optional[date] = Query(None, description="统计结束日期"),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    差旅统计看板

    返回差旅申请数量、费用汇总、状态分布、交通方式分布、平均天数等指标。
    金额单位为分(fen)。
    """
    try:
        filters = {
            k: v for k, v in {
                "brand_id": brand_id,
                "store_id": store_id,
                "date_from": date_from,
                "date_to": date_to,
            }.items() if v is not None
        }
        result = await _travel_svc.get_stats(
            db=db, tenant_id=tenant_id, filters=filters
        )
        return {"ok": True, "data": result}
    except Exception as exc:
        log.error("travel_stats_failed", error=str(exc), tenant_id=str(tenant_id), exc_info=True)
        raise HTTPException(status_code=500, detail="获取差旅统计数据失败，请稍后重试")


@router.get("/requests/{request_id}/allocations")
async def get_travel_allocations(
    request_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    查看差旅费用分摊明细

    - 返回该差旅申请按门店分摊的费用明细
    - 分摊比例基于各门店实际签到时长
    - 金额单位为分(fen)
    """
    try:
        request = await _travel_svc.get_travel_request(
            db=db, tenant_id=tenant_id, request_id=request_id
        )
        allocations = request.allocations or []
        data = [
            {
                "id": str(a.id),
                "store_id": str(a.store_id),
                "brand_id": str(a.brand_id),
                "allocation_basis": a.allocation_basis,
                "basis_value": float(a.basis_value) if a.basis_value is not None else None,
                "allocation_rate": float(a.allocation_rate),
                "total_travel_cost_fen": a.total_travel_cost_fen,
                "allocated_amount_fen": a.allocated_amount_fen,
                "is_attributed": a.is_attributed,
                "attributed_at": a.attributed_at.isoformat() if a.attributed_at else None,
            }
            for a in allocations
        ]
        return {"ok": True, "data": data, "total": len(data)}
    except LookupError:
        raise HTTPException(status_code=404, detail="差旅申请不存在或无权访问")
    except Exception as exc:
        log.error("travel_allocations_get_failed", error=str(exc), request_id=str(request_id), exc_info=True)
        raise HTTPException(status_code=500, detail="获取费用分摊明细失败，请稍后重试")


# ---------------------------------------------------------------------------
# 序列化辅助
# ---------------------------------------------------------------------------

def _serialize_request(request: Any, with_relations: bool = False) -> Dict[str, Any]:
    """将 TravelRequest ORM 对象序列化为 dict（兼容 JSON 序列化）。"""
    data: Dict[str, Any] = {
        "id": str(request.id),
        "tenant_id": str(request.tenant_id),
        "brand_id": str(request.brand_id),
        "store_id": str(request.store_id),
        "traveler_id": str(request.traveler_id),
        "applicant_id": str(request.applicant_id),
        "inspection_task_id": str(request.inspection_task_id) if request.inspection_task_id else None,
        "task_type": request.task_type,
        "departure_city": request.departure_city,
        "destination_cities": request.destination_cities or [],
        "planned_stores": request.planned_stores or [],
        "planned_start_date": request.planned_start_date.isoformat() if request.planned_start_date else None,
        "planned_end_date": request.planned_end_date.isoformat() if request.planned_end_date else None,
        "planned_days": request.planned_days,
        "staff_level": request.staff_level,
        "applicable_standards": request.applicable_standards or {},
        "transport_mode": request.transport_mode,
        "estimated_cost_fen": request.estimated_cost_fen or 0,
        "status": request.status,
        "approval_instance_id": str(request.approval_instance_id) if request.approval_instance_id else None,
        "actual_start_date": request.actual_start_date.isoformat() if request.actual_start_date else None,
        "actual_end_date": request.actual_end_date.isoformat() if request.actual_end_date else None,
        "actual_days": request.actual_days,
        "total_mileage_km": float(request.total_mileage_km) if request.total_mileage_km else None,
        "total_cost_fen": request.total_cost_fen or 0,
        "mileage_allowance_fen": request.mileage_allowance_fen or 0,
        "expense_application_id": str(request.expense_application_id) if request.expense_application_id else None,
        "notes": request.notes,
        "created_at": request.created_at.isoformat() if request.created_at else None,
        "updated_at": request.updated_at.isoformat() if request.updated_at else None,
    }

    if with_relations:
        try:
            data["itineraries"] = [_serialize_itinerary(i) for i in (request.itineraries or [])]
            data["allocations"] = [
                {
                    "id": str(a.id),
                    "store_id": str(a.store_id),
                    "allocation_basis": a.allocation_basis,
                    "allocation_rate": float(a.allocation_rate),
                    "allocated_amount_fen": a.allocated_amount_fen,
                    "is_attributed": a.is_attributed,
                }
                for a in (request.allocations or [])
            ]
        except (AttributeError, TypeError):
            # 关系懒加载可能未初始化，安全降级
            data["itineraries"] = []
            data["allocations"] = []

    return data


def _serialize_itinerary(itinerary: Any) -> Dict[str, Any]:
    """将 TravelItinerary ORM 对象序列化为 dict。"""
    return {
        "id": str(itinerary.id),
        "tenant_id": str(itinerary.tenant_id),
        "travel_request_id": str(itinerary.travel_request_id),
        "store_id": str(itinerary.store_id),
        "store_name": itinerary.store_name,
        "checkin_time": itinerary.checkin_time.isoformat() if itinerary.checkin_time else None,
        "checkout_time": itinerary.checkout_time.isoformat() if itinerary.checkout_time else None,
        "duration_minutes": itinerary.duration_minutes,
        "checkin_location": itinerary.checkin_location,
        "checkout_location": itinerary.checkout_location,
        "gps_track": itinerary.gps_track or [],
        "distance_from_store_m": itinerary.distance_from_store_m,
        "leg_mileage_km": float(itinerary.leg_mileage_km) if itinerary.leg_mileage_km else None,
        "is_mileage_anomaly": itinerary.is_mileage_anomaly,
        "anomaly_reason": itinerary.anomaly_reason,
        "itinerary_status": itinerary.itinerary_status,
        "skip_reason": itinerary.skip_reason,
        "sequence_order": itinerary.sequence_order,
        "created_at": itinerary.created_at.isoformat() if itinerary.created_at else None,
    }
