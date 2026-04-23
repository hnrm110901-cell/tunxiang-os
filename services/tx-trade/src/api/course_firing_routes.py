"""Course Firing API 路由 — 打菜时机控制"""

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..services.course_firing_service import (
    assign_course,
    check_fire_suggestion,
    fire_course,
    get_courses_status,
)

router = APIRouter(prefix="/api/v1/orders", tags=["course-firing"])


class FireCourseRequest(BaseModel):
    operator_id: str


class AssignCourseRequest(BaseModel):
    course_name: str


def _serialize_course_status(cs) -> dict:
    return {
        "course_name": cs.course_name,
        "course_label": cs.course_label,
        "sort_order": cs.sort_order,
        "status": cs.status,
        "dish_count": cs.dish_count,
        "fired_count": cs.fired_count,
        "done_count": cs.done_count,
        "fired_at": cs.fired_at.isoformat() if cs.fired_at else None,
        "fired_by": cs.fired_by,
    }


@router.post("/{order_id}/courses/{course_name}/fire")
async def api_fire_course(
    order_id: str,
    course_name: str,
    body: FireCourseRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """开火指定课程，将对应KDS任务从hold状态推送到厨房。"""
    try:
        course = await fire_course(
            order_id=order_id,
            course_name=course_name,
            operator_id=body.operator_id,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {
            "ok": True,
            "data": {
                "order_id": order_id,
                "course_name": course.course_name,
                "course_label": course.course_label,
                "status": course.status,
                "fired_at": course.fired_at.isoformat() if course.fired_at else None,
            },
        }
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{order_id}/courses")
async def api_get_courses(
    order_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取该订单所有课程的状态。"""
    statuses = await get_courses_status(
        order_id=order_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {
        "ok": True,
        "data": {
            "items": [_serialize_course_status(s) for s in statuses],
            "total": len(statuses),
        },
    }


@router.patch("/{order_id}/items/{item_id}/course")
async def api_assign_course(
    order_id: str,
    item_id: str,
    body: AssignCourseRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """修改菜品所属课程，并将KDS任务设为hold状态。"""
    try:
        await assign_course(
            order_id=order_id,
            item_id=item_id,
            course_name=body.course_name,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": {"order_id": order_id, "item_id": item_id, "course_name": body.course_name}}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{order_id}/courses/suggestion")
async def api_get_suggestion(
    order_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取开火建议（服务员端定时轮询）。"""
    suggestion = await check_fire_suggestion(
        order_id=order_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {"ok": True, "data": {"suggestion": suggestion}}
