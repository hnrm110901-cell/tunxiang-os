"""Course Firing Service — 上菜节奏控制（宴席 + 散台/VIP）

支持两种模式：
- 宴席模式：厨师长手动推进各课程（fire_course）
- 散台/VIP模式：自动按菜品分类分配课程，按预设延时自动开火或手动调整
"""
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.kds_task import KDSTask
from ..models.order_course import OrderCourse

logger = structlog.get_logger()

MAC_STATION_URL = os.getenv("MAC_STATION_URL", "http://localhost:8000")

COURSE_SORT = {
    "drink": 0,
    "appetizer": 1,
    "main": 2,
    "soup": 3,
    "staple": 4,
    "dessert": 5,
}

COURSE_LABELS = {
    "drink": "饮品",
    "appetizer": "前菜",
    "main": "主菜",
    "soup": "汤品",
    "staple": "主食",
    "dessert": "甜品",
}

# 散台/VIP默认延时（分钟），相对首道课程开火时间
COURSE_DEFAULT_DELAY = {
    "drink": 0,
    "appetizer": 0,
    "main": 10,
    "soup": 20,
    "staple": 25,
    "dessert": 30,
}

# 菜品分类 → 课程名称映射
CATEGORY_TO_COURSE: dict[str, str] = {
    "凉菜": "appetizer",
    "冷菜": "appetizer",
    "前菜": "appetizer",
    "热菜": "main",
    "海鲜": "main",
    "炒菜": "main",
    "蒸菜": "main",
    "烧烤": "main",
    "汤": "soup",
    "汤品": "soup",
    "煲汤": "soup",
    "主食": "staple",
    "粉面": "staple",
    "米饭": "staple",
    "面点": "staple",
    "甜品": "dessert",
    "甜点": "dessert",
    "水果": "dessert",
    "果盘": "dessert",
    "饮品": "drink",
    "饮料": "drink",
    "酒水": "drink",
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
    delay_minutes: int
    scheduled_fire_at: Optional[datetime]
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
            delay_minutes=course.delay_minutes,
            scheduled_fire_at=course.scheduled_fire_at,
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


@dataclass
class AutoAssignItem:
    """auto_assign_courses 的输入项"""
    item_id: str
    dish_category: str  # 菜品分类（如"凉菜"、"热菜"、"汤"等）


async def auto_assign_courses(
    order_id: str,
    items: list[AutoAssignItem],
    tenant_id: str,
    db: AsyncSession,
) -> list[OrderCourse]:
    """根据菜品分类自动为散台/VIP订单分配课程。

    每个菜品按其分类映射到对应课程，创建OrderCourse记录并设置默认延时。
    未匹配到分类的菜品默认分配到main课程。
    """
    tid = uuid.UUID(tenant_id)
    oid = uuid.UUID(order_id)

    # 按课程聚合items
    course_items: dict[str, list[uuid.UUID]] = {}
    for item in items:
        course_name = CATEGORY_TO_COURSE.get(item.dish_category, "main")
        course_items.setdefault(course_name, []).append(uuid.UUID(item.item_id))

    created_courses: list[OrderCourse] = []

    for course_name, item_ids in course_items.items():
        # 检查是否已存在该课程
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
            delay = COURSE_DEFAULT_DELAY.get(course_name, 0)
            course = OrderCourse(
                tenant_id=tid,
                order_id=oid,
                course_name=course_name,
                course_label=COURSE_LABELS[course_name],
                sort_order=COURSE_SORT[course_name],
                status="waiting",
                delay_minutes=delay,
            )
            db.add(course)
            created_courses.append(course)

        # 将对应KDS任务标记为hold并关联课程
        for iid in item_ids:
            await db.execute(
                update(KDSTask)
                .where(
                    KDSTask.tenant_id == tid,
                    KDSTask.order_item_id == iid,
                    KDSTask.is_deleted.is_(False),
                )
                .values(course_name=course_name, course_status="hold")
            )

    await db.commit()

    logger.info(
        "course_firing.auto_assign",
        order_id=order_id,
        courses_created=len(created_courses),
        total_items=len(items),
    )

    return created_courses


async def adjust_course_delay(
    order_id: str,
    course_name: str,
    delay_minutes: int,
    tenant_id: str,
    db: AsyncSession,
) -> OrderCourse:
    """厨师/经理调整某课程的延迟时间（分钟）。

    如果首道课程已开火（有scheduled_fire_at基准），则同步更新scheduled_fire_at。
    """
    if course_name not in VALID_COURSES:
        raise ValueError(f"course_name must be one of {sorted(VALID_COURSES)}")
    if delay_minutes < 0:
        raise ValueError("delay_minutes must be non-negative")

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
        raise ValueError(f"course {course_name} already fired, cannot adjust delay")

    update_values: dict = {
        "delay_minutes": delay_minutes,
    }

    # 如果有基准开火时间（首道课程已开火），重新计算scheduled_fire_at
    base_time = await _get_base_fire_time(oid, tid, db)
    if base_time is not None:
        update_values["scheduled_fire_at"] = base_time + timedelta(minutes=delay_minutes)

    await db.execute(
        update(OrderCourse)
        .where(OrderCourse.id == course.id)
        .values(**update_values)
    )
    await db.commit()
    await db.refresh(course)

    logger.info(
        "course_firing.delay_adjusted",
        order_id=order_id,
        course_name=course_name,
        delay_minutes=delay_minutes,
    )

    return course


async def rush_course(
    order_id: str,
    course_name: str,
    operator_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> OrderCourse:
    """立即催火一个处于waiting/hold状态的课程，跳过延时等待。"""
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
    if course.status == "completed":
        raise ValueError(f"course {course_name} already completed")

    now = datetime.now(timezone.utc)

    # 将关联KDS任务从hold推送到fired
    await db.execute(
        update(KDSTask)
        .where(
            KDSTask.tenant_id == tid,
            KDSTask.order_item_id.in_(
                select(KDSTask.order_item_id).where(
                    KDSTask.tenant_id == tid,
                    KDSTask.course_name == course_name,
                    KDSTask.course_status == "hold",
                    KDSTask.is_deleted.is_(False),
                )
            ),
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
        "course_firing.rushed",
        order_id=order_id,
        course_name=course_name,
        operator_id=operator_id,
    )

    await _broadcast_course_fired(order_id, course_name, tenant_id)
    return course


async def hold_course(
    order_id: str,
    course_name: str,
    tenant_id: str,
    db: AsyncSession,
) -> OrderCourse:
    """暂停一个尚未开火的课程，将其状态设为hold。"""
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
        raise ValueError(f"course {course_name} already fired, cannot hold")
    if course.status == "completed":
        raise ValueError(f"course {course_name} already completed, cannot hold")
    if course.status == "hold":
        raise ValueError(f"course {course_name} is already on hold")

    await db.execute(
        update(OrderCourse)
        .where(OrderCourse.id == course.id)
        .values(status="hold", scheduled_fire_at=None)
    )
    await db.commit()
    await db.refresh(course)

    logger.info(
        "course_firing.held",
        order_id=order_id,
        course_name=course_name,
    )

    return course


async def _get_base_fire_time(
    order_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> Optional[datetime]:
    """获取首道课程的开火时间作为基准时间。

    如果首道课程尚未开火，返回None。
    """
    result = await db.execute(
        select(OrderCourse)
        .where(
            OrderCourse.tenant_id == tenant_id,
            OrderCourse.order_id == order_id,
            OrderCourse.status == "fired",
            OrderCourse.is_deleted.is_(False),
        )
        .order_by(OrderCourse.sort_order.asc())
        .limit(1)
    )
    first_fired = result.scalar_one_or_none()
    if first_fired is not None and first_fired.fired_at is not None:
        return first_fired.fired_at
    return None


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
