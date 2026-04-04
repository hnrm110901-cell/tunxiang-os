"""Course Firing API 路由 — 上菜节奏控制（宴席 + 散台/VIP）"""
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..services.course_firing_service import (
    AutoAssignItem,
    adjust_course_delay,
    assign_course,
    auto_assign_courses,
    check_fire_suggestion,
    fire_course,
    get_courses_status,
    hold_course,
    rush_course,
)

router = APIRouter(prefix="/api/v1/trade/orders", tags=["course-firing"])


class FireCourseRequest(BaseModel):
    operator_id: str


class AssignCourseRequest(BaseModel):
    course_name: str


class AutoAssignItemRequest(BaseModel):
    item_id: str
    dish_category: str = Field(..., description="菜品分类（如凉菜、热菜、汤、主食、甜品、饮品）")


class AutoAssignRequest(BaseModel):
    items: list[AutoAssignItemRequest] = Field(..., min_length=1)


class AdjustDelayRequest(BaseModel):
    delay_minutes: int = Field(..., ge=0, description="相对首道课程的延迟分钟数")


class RushCourseRequest(BaseModel):
    operator_id: str


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


@router.post("/{order_id}/courses/auto-assign")
async def api_auto_assign_courses(
    order_id: str,
    body: AutoAssignRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """根据菜品分类自动分配课程（散台/VIP上菜节奏控制）。

    将订单中的菜品按分类（凉菜/热菜/汤/主食/甜品/饮品）映射到课程，
    并设置默认延时间隔。饮品立即出品，前菜0分钟，主菜10分钟，
    汤品20分钟，主食25分钟，甜品30分钟。
    """
    items = [
        AutoAssignItem(item_id=it.item_id, dish_category=it.dish_category)
        for it in body.items
    ]
    try:
        courses = await auto_assign_courses(
            order_id=order_id,
            items=items,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {
            "ok": True,
            "data": {
                "order_id": order_id,
                "courses_created": len(courses),
                "courses": [
                    {
                        "course_name": c.course_name,
                        "course_label": c.course_label,
                        "sort_order": c.sort_order,
                        "delay_minutes": c.delay_minutes,
                        "status": c.status,
                    }
                    for c in courses
                ],
            },
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{order_id}/courses/{course_name}/delay")
async def api_adjust_course_delay(
    order_id: str,
    course_name: str,
    body: AdjustDelayRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """调整指定课程的延迟时间（厨师/经理可手动覆盖默认延时）。"""
    try:
        course = await adjust_course_delay(
            order_id=order_id,
            course_name=course_name,
            delay_minutes=body.delay_minutes,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {
            "ok": True,
            "data": {
                "order_id": order_id,
                "course_name": course.course_name,
                "course_label": course.course_label,
                "delay_minutes": course.delay_minutes,
                "scheduled_fire_at": course.scheduled_fire_at.isoformat() if course.scheduled_fire_at else None,
                "status": course.status,
            },
        }
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{order_id}/courses/{course_name}/rush")
async def api_rush_course(
    order_id: str,
    course_name: str,
    body: RushCourseRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """立即催火指定课程，跳过延时等待（催菜/VIP加急）。"""
    try:
        course = await rush_course(
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


@router.post("/{order_id}/courses/{course_name}/hold")
async def api_hold_course(
    order_id: str,
    course_name: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """暂停指定课程，阻止其自动开火（客人暂停用餐等场景）。"""
    try:
        course = await hold_course(
            order_id=order_id,
            course_name=course_name,
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
            },
        }
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
