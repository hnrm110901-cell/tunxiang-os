"""Course Firing Service — 打菜时机控制"""
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.kds_task import KDSTask
from ..models.order_course import OrderCourse

logger = structlog.get_logger()

MAC_STATION_URL = os.getenv("MAC_STATION_URL", "http://localhost:8000")

COURSE_SORT = {
    "appetizer": 1,
    "main": 2,
    "dessert": 3,
    "drink": 4,
}

COURSE_LABELS = {
    "appetizer": "前菜",
    "main": "主菜",
    "dessert": "甜品",
    "drink": "饮品",
}

VALID_COURSES = set(COURSE_SORT.keys())


@dataclass
class CourseStatus:
    course_name: str
    course_label: str
    sort_order: int
    status: str
    dish_count: int
    fired_count: int
    done_count: int
    fired_at: Optional[datetime]
    fired_by: Optional[str]


async def assign_course(
    order_id: str,
    item_id: str,
    course_name: str,
    tenant_id: str,
    db: AsyncSession,
) -> None:
    if course_name not in VALID_COURSES:
        raise ValueError(f"course_name must be one of {sorted(VALID_COURSES)}")

    tid = uuid.UUID(tenant_id)
    oid = uuid.UUID(order_id)
    iid = uuid.UUID(item_id)

    await db.execute(
        update(KDSTask)
        .where(
            KDSTask.tenant_id == tid,
            KDSTask.order_item_id == iid,
            KDSTask.is_deleted.is_(False),
        )
        .values(course_name=course_name, course_status="hold")
    )

    result = await db.execute(
        select(OrderCourse).where(
            OrderCourse.tenant_id == tid,
            OrderCourse.order_id == oid,
            OrderCourse.course_name == course_name,
            OrderCourse.is_deleted.is_(False),
        )
    )
    existing = result.scalar_one_or_none()

    if existing is None:
        course = OrderCourse(
            tenant_id=tid,
            order_id=oid,
            course_name=course_name,
            course_label=COURSE_LABELS[course_name],
            sort_order=COURSE_SORT[course_name],
            status="waiting",
        )
        db.add(course)

    await db.commit()

    logger.info(
        "course_firing.assign",
        order_id=order_id,
        item_id=item_id,
        course_name=course_name,
    )


async def fire_course(
    order_id: str,
    course_name: str,
    operator_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> OrderCourse:
    if course_name not in VALID_COURSES:
        raise ValueError(f"course_name must be one of {sorted(VALID_COURSES)}")

    tid = uuid.UUID(tenant_id)
    oid = uuid.UUID(order_id)

    result = await db.execute(
        select(OrderCourse).where(
            OrderCourse.tenant_id == tid,
            OrderCourse.order_id == oid,
            OrderCourse.course_name == course_name,
            OrderCourse.is_deleted.is_(False),
        )
    )
    course = result.scalar_one_or_none()
    if course is None:
        raise LookupError(f"order_course not found: order={order_id} course={course_name}")
    if course.status == "fired":
        raise ValueError(f"course {course_name} already fired")

    now = datetime.now(timezone.utc)

    await db.execute(
        update(KDSTask)
        .where(
            KDSTask.tenant_id == tid,
            KDSTask.course_name == course_name,
            KDSTask.course_status == "hold",
            KDSTask.is_deleted.is_(False),
        )
        .values(course_status="fired")
    )

    await db.execute(
        update(OrderCourse)
        .where(OrderCourse.id == course.id)
        .values(
            status="fired",
            fired_at=now,
            fired_by=uuid.UUID(operator_id),
        )
    )
    await db.commit()
    await db.refresh(course)

    logger.info(
        "course_firing.fired",
        order_id=order_id,
        course_name=course_name,
        operator_id=operator_id,
    )

    await _broadcast_course_fired(order_id, course_name, tenant_id)
    return course


async def get_courses_status(
    order_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> list[CourseStatus]:
    tid = uuid.UUID(tenant_id)
    oid = uuid.UUID(order_id)

    courses_result = await db.execute(
        select(OrderCourse)
        .where(
            OrderCourse.tenant_id == tid,
            OrderCourse.order_id == oid,
            OrderCourse.is_deleted.is_(False),
        )
        .order_by(OrderCourse.sort_order.asc())
    )
    courses = list(courses_result.scalars().all())

    statuses: list[CourseStatus] = []
    for course in courses:
        tasks_result = await db.execute(
            select(KDSTask).where(
                KDSTask.tenant_id == tid,
                KDSTask.course_name == course.course_name,
                KDSTask.is_deleted.is_(False),
            )
        )
        tasks = list(tasks_result.scalars().all())

        dish_count = len(tasks)
        fired_count = sum(1 for t in tasks if t.course_status == "fired")
        done_count = sum(1 for t in tasks if t.status == "done")

        statuses.append(CourseStatus(
            course_name=course.course_name,
            course_label=course.course_label,
            sort_order=course.sort_order,
            status=course.status,
            dish_count=dish_count,
            fired_count=fired_count,
            done_count=done_count,
            fired_at=course.fired_at,
            fired_by=str(course.fired_by) if course.fired_by else None,
        ))

    return statuses


async def check_fire_suggestion(
    order_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> Optional[str]:
    statuses = await get_courses_status(order_id, tenant_id, db)

    fired_courses = [s for s in statuses if s.status == "fired"]
    if not fired_courses:
        return None

    latest_fired = max(fired_courses, key=lambda s: s.sort_order)
    if latest_fired.dish_count == 0:
        return None

    completion_rate = latest_fired.done_count / latest_fired.dish_count
    if completion_rate < 0.7:
        return None

    waiting_courses = sorted(
        [s for s in statuses if s.status == "waiting"],
        key=lambda s: s.sort_order,
    )
    if not waiting_courses:
        return None

    next_course = waiting_courses[0]
    pct = int(completion_rate * 100)
    return f"{latest_fired.course_label}已上齐{pct}%，是否开火{next_course.course_label}？"


async def _broadcast_course_fired(
    order_id: str,
    course_name: str,
    tenant_id: str,
) -> None:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            await client.post(
                f"{MAC_STATION_URL}/api/kds/broadcast",
                json={
                    "event": "course_fired",
                    "data": {
                        "order_id": order_id,
                        "course_name": course_name,
                    },
                },
                headers={"X-Tenant-ID": tenant_id},
            )
    except httpx.RequestError as e:
        logger.warning("course_firing.broadcast.failed", error=str(e))
