"""员工深度业务逻辑 (A6) — 业绩归因、提成计算、培训管理、绩效卡

所有金额单位：分(fen)。
提成计算: 基础提成 + 推菜提成 + 开瓶提成 + 加单提成
"""
from __future__ import annotations

import uuid
from datetime import datetime, date, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import select, func, and_, text, extract
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Employee, Order, OrderItem

logger = structlog.get_logger(__name__)

# ── 提成比例常量（分） ────────────────────────────────────────
COMMISSION_BASE_RATE = 0.005         # 基础提成: 服务订单金额的 0.5%
COMMISSION_RECOMMEND_RATE = 0.02     # 推菜提成: 推荐菜品金额的 2%
COMMISSION_BOTTLE_FEN = 500          # 开瓶提成: 每瓶 500 分(5元)
COMMISSION_UPSELL_RATE = 0.03        # 加单提成: 加单金额的 3%

# ── 培训状态 ─────────────────────────────────────────────────
TRAINING_STATUS_PENDING = "pending"
TRAINING_STATUS_IN_PROGRESS = "in_progress"
TRAINING_STATUS_COMPLETED = "completed"
TRAINING_STATUS_FAILED = "failed"

def _to_uuid(val: str) -> uuid.UUID:
    return uuid.UUID(val)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS tenant 上下文"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ── 1. 业绩归因 ─────────────────────────────────────────────


async def calculate_performance_attribution(
    employee_id: str,
    date_range: tuple[str, str],
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """业绩归因 — 服务桌数/推荐菜品/加单率

    通过 waiter_id 关联订单，统计员工服务效能。

    Returns:
        {tables_served, orders_served, total_revenue_fen,
         recommended_dishes, upsell_count, upsell_rate, avg_per_table_fen}
    """
    await _set_tenant(db, tenant_id)
    tid = _to_uuid(tenant_id)
    start_dt = datetime.fromisoformat(date_range[0]).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(date_range[1]).replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc,
    )

    # 该员工服务的订单
    orders_result = await db.execute(
        select(
            func.count(Order.id).label("order_count"),
            func.count(func.distinct(Order.table_number)).label("table_count"),
            func.coalesce(func.sum(Order.total_amount_fen), 0).label("total_revenue_fen"),
            func.coalesce(func.sum(Order.guest_count), 0).label("total_guests"),
        )
        .where(Order.tenant_id == tid)
        .where(Order.waiter_id == employee_id)
        .where(Order.is_deleted == False)  # noqa: E712
        .where(Order.order_time >= start_dt)
        .where(Order.order_time <= end_dt)
    )
    row = orders_result.one()
    order_count = row.order_count or 0
    table_count = row.table_count or 0
    total_revenue_fen = row.total_revenue_fen or 0
    total_guests = row.total_guests or 0

    # 推荐菜品统计（is_recommended 的菜品在该员工服务的订单中）
    recommend_result = await db.execute(
        select(
            func.count(OrderItem.id).label("recommend_count"),
            func.coalesce(func.sum(OrderItem.subtotal_fen), 0).label("recommend_amount_fen"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.tenant_id == tid)
        .where(Order.waiter_id == employee_id)
        .where(Order.is_deleted == False)  # noqa: E712
        .where(Order.order_time >= start_dt)
        .where(Order.order_time <= end_dt)
        .where(OrderItem.gift_flag == False)  # noqa: E712
    )
    rec_row = recommend_result.one()
    total_items = rec_row.recommend_count or 0
    total_item_amount_fen = rec_row.recommend_amount_fen or 0

    # 加单统计（同一桌多次下单视为加单，简化为 order_count - table_count）
    upsell_count = max(order_count - table_count, 0)
    upsell_rate = round(upsell_count / max(table_count, 1), 4)

    avg_per_table_fen = total_revenue_fen // max(table_count, 1)

    logger.info(
        "performance_attribution_calculated",
        employee_id=employee_id,
        tables_served=table_count,
        orders=order_count,
        total_revenue_fen=total_revenue_fen,
        tenant_id=tenant_id,
    )

    return {
        "employee_id": employee_id,
        "date_range": list(date_range),
        "tables_served": table_count,
        "orders_served": order_count,
        "total_guests": total_guests,
        "total_revenue_fen": total_revenue_fen,
        "total_items_sold": total_items,
        "total_item_amount_fen": total_item_amount_fen,
        "upsell_count": upsell_count,
        "upsell_rate": upsell_rate,
        "avg_per_table_fen": avg_per_table_fen,
    }


# ── 2. 提成计算 ──────────────────────────────────────────────


async def calculate_commission(
    employee_id: str,
    month: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """提成计算 — 基础 + 推菜 + 开瓶 + 加单

    月份格式: "2026-03"
    所有提成金额单位: 分(fen)

    Returns:
        {base_commission_fen, recommend_commission_fen,
         bottle_commission_fen, upsell_commission_fen,
         total_commission_fen, details}
    """
    await _set_tenant(db, tenant_id)
    tid = _to_uuid(tenant_id)

    # 解析月份
    year, mon = month.split("-")
    start_dt = datetime(int(year), int(mon), 1, tzinfo=timezone.utc)
    if int(mon) == 12:
        end_dt = datetime(int(year) + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end_dt = datetime(int(year), int(mon) + 1, 1, tzinfo=timezone.utc)

    # 基础提成: 服务订单总额 * 0.5%
    base_result = await db.execute(
        select(
            func.coalesce(func.sum(Order.total_amount_fen), 0).label("total"),
            func.count(Order.id).label("cnt"),
        )
        .where(Order.tenant_id == tid)
        .where(Order.waiter_id == employee_id)
        .where(Order.is_deleted == False)  # noqa: E712
        .where(Order.order_time >= start_dt)
        .where(Order.order_time < end_dt)
    )
    base_row = base_result.one()
    service_total_fen = base_row.total or 0
    service_order_count = base_row.cnt or 0
    base_commission_fen = int(service_total_fen * COMMISSION_BASE_RATE)

    # 推菜提成: 推荐菜品(含 is_recommended 标记的菜品)金额 * 2%
    # 简化: 取该员工服务订单中所有菜品金额的2%
    recommend_result = await db.execute(
        select(func.coalesce(func.sum(OrderItem.subtotal_fen), 0))
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.tenant_id == tid)
        .where(Order.waiter_id == employee_id)
        .where(Order.is_deleted == False)  # noqa: E712
        .where(Order.order_time >= start_dt)
        .where(Order.order_time < end_dt)
        .where(OrderItem.gift_flag == False)  # noqa: E712
    )
    recommend_amount_fen = recommend_result.scalar() or 0
    recommend_commission_fen = int(recommend_amount_fen * COMMISSION_RECOMMEND_RATE)

    # 开瓶提成: 酒水类菜品数量 * 每瓶提成
    # 简化: 匹配菜品名称含"酒"/"酒水"/"红酒"/"白酒"/"啤酒"的 quantity
    bottle_result = await db.execute(
        select(func.coalesce(func.sum(OrderItem.quantity), 0))
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.tenant_id == tid)
        .where(Order.waiter_id == employee_id)
        .where(Order.is_deleted == False)  # noqa: E712
        .where(Order.order_time >= start_dt)
        .where(Order.order_time < end_dt)
        .where(
            OrderItem.item_name.ilike("%酒%")
            | OrderItem.item_name.ilike("%wine%")
            | OrderItem.item_name.ilike("%beer%")
        )
    )
    bottle_count = int(bottle_result.scalar() or 0)
    bottle_commission_fen = bottle_count * COMMISSION_BOTTLE_FEN

    # 加单提成: 同一桌号多次下单的增量金额 * 3%
    # 简化: 取订单数 - 桌数差额 * 平均客单价 * 3%
    table_result = await db.execute(
        select(func.count(func.distinct(Order.table_number)))
        .where(Order.tenant_id == tid)
        .where(Order.waiter_id == employee_id)
        .where(Order.is_deleted == False)  # noqa: E712
        .where(Order.order_time >= start_dt)
        .where(Order.order_time < end_dt)
        .where(Order.table_number.isnot(None))
    )
    unique_tables = table_result.scalar() or 0
    upsell_orders = max(service_order_count - unique_tables, 0)
    avg_order_fen = service_total_fen // max(service_order_count, 1)
    upsell_amount_fen = upsell_orders * avg_order_fen
    upsell_commission_fen = int(upsell_amount_fen * COMMISSION_UPSELL_RATE)

    total_commission_fen = (
        base_commission_fen
        + recommend_commission_fen
        + bottle_commission_fen
        + upsell_commission_fen
    )

    logger.info(
        "commission_calculated",
        employee_id=employee_id,
        month=month,
        total_commission_fen=total_commission_fen,
        base=base_commission_fen,
        recommend=recommend_commission_fen,
        bottle=bottle_commission_fen,
        upsell=upsell_commission_fen,
        tenant_id=tenant_id,
    )

    return {
        "employee_id": employee_id,
        "month": month,
        "base_commission_fen": base_commission_fen,
        "recommend_commission_fen": recommend_commission_fen,
        "bottle_commission_fen": bottle_commission_fen,
        "upsell_commission_fen": upsell_commission_fen,
        "total_commission_fen": total_commission_fen,
        "details": {
            "service_total_fen": service_total_fen,
            "service_order_count": service_order_count,
            "recommend_amount_fen": recommend_amount_fen,
            "bottle_count": bottle_count,
            "upsell_orders": upsell_orders,
            "upsell_amount_fen": upsell_amount_fen,
        },
    }


# ── 3. 培训管理 ──────────────────────────────────────────────


async def manage_training(
    employee_id: str,
    training_plan: dict[str, Any],
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """培训管理 — 课程/考核/认证

    training_plan 结构:
        {
            "action": "assign" | "complete" | "fail" | "certify",
            "course_id": str,
            "course_name": str,
            "category": "food_safety" | "service" | "cooking" | "management",
            "score": int (0-100, 仅 complete/fail 时),
            "certificate_id": str (仅 certify 时),
        }

    Returns:
        {training_id, status, message}
    """
    await _set_tenant(db, tenant_id)
    action = training_plan.get("action", "assign")
    course_id = training_plan.get("course_id", str(uuid.uuid4()))
    course_name = training_plan.get("course_name", "未命名课程")
    category = training_plan.get("category", "service")
    eid = _to_uuid(employee_id)
    tid = _to_uuid(tenant_id)
    now = datetime.now(timezone.utc)

    if action == "assign":
        training_id = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO employee_trainings
                    (id, tenant_id, employee_id, course_id, course_name, category,
                     status, pass_threshold, assigned_at, created_at, updated_at)
                VALUES
                    (:id, :tid, :eid, :course_id, :course_name, :category,
                     'pending', :pass_threshold, :now, :now, :now)
            """),
            {
                "id": training_id,
                "tid": tid,
                "eid": eid,
                "course_id": course_id,
                "course_name": course_name,
                "category": category,
                "pass_threshold": training_plan.get("pass_threshold", 60),
                "now": now,
            },
        )
        await db.flush()
        logger.info("training_assigned", employee_id=employee_id,
                    training_id=str(training_id), course_name=course_name,
                    tenant_id=tenant_id)
        return {
            "training_id": str(training_id),
            "status": TRAINING_STATUS_PENDING,
            "message": f"已分配培训课程: {course_name}",
        }

    # 查找已有培训记录
    row_result = await db.execute(
        text("""
            SELECT id, status, pass_threshold, score, course_name
            FROM employee_trainings
            WHERE tenant_id = :tid AND employee_id = :eid AND course_id = :course_id
            ORDER BY assigned_at DESC
            LIMIT 1
        """),
        {"tid": tid, "eid": eid, "course_id": course_id},
    )
    existing = row_result.fetchone()

    if not existing:
        return {
            "training_id": None,
            "status": "not_found",
            "message": f"未找到课程 {course_id} 的培训记录",
        }

    training_id_str = str(existing.id)

    if action == "complete":
        score = training_plan.get("score", 0)
        pass_threshold = existing.pass_threshold or 60
        new_status = TRAINING_STATUS_COMPLETED if score >= pass_threshold else TRAINING_STATUS_FAILED
        msg = (
            f"培训完成: {existing.course_name}, 得分{score}"
            if new_status == TRAINING_STATUS_COMPLETED
            else f"培训未通过: {existing.course_name}, 得分{score}, 及格线{pass_threshold}"
        )
        await db.execute(
            text("""
                UPDATE employee_trainings
                SET status = :status, score = :score, completed_at = :now, updated_at = :now
                WHERE id = :id AND tenant_id = :tid
            """),
            {"status": new_status, "score": score, "now": now,
             "id": existing.id, "tid": tid},
        )
        # 更新 Employee 的 training_completed 列表
        if new_status == TRAINING_STATUS_COMPLETED:
            emp_result = await db.execute(
                select(Employee)
                .where(Employee.id == eid)
                .where(Employee.tenant_id == tid)
            )
            emp = emp_result.scalar_one_or_none()
            if emp:
                completed = list(emp.training_completed or [])
                if course_id not in completed:
                    completed.append(course_id)
                    emp.training_completed = completed
        await db.flush()
        logger.info("training_completed", employee_id=employee_id,
                    course_id=course_id, score=score,
                    passed=new_status == TRAINING_STATUS_COMPLETED,
                    tenant_id=tenant_id)
        return {"training_id": training_id_str, "status": new_status, "message": msg}

    elif action == "certify":
        cert_id = training_plan.get("certificate_id", str(uuid.uuid4()))
        await db.execute(
            text("""
                UPDATE employee_trainings
                SET status = 'completed', certificate_id = :cert_id, updated_at = :now
                WHERE id = :id AND tenant_id = :tid
            """),
            {"cert_id": cert_id, "now": now, "id": existing.id, "tid": tid},
        )
        await db.flush()
        logger.info("training_certified", employee_id=employee_id,
                    course_id=course_id, certificate_id=cert_id, tenant_id=tenant_id)
        return {
            "training_id": training_id_str,
            "status": TRAINING_STATUS_COMPLETED,
            "message": f"已颁发认证: {cert_id}",
            "certificate_id": cert_id,
        }

    return {
        "training_id": None,
        "status": "unknown_action",
        "message": f"未知操作: {action}",
    }


# ── 4. 培训进度 ──────────────────────────────────────────────


async def get_training_progress(
    employee_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """培训进度 — 已完成/进行中/待开始

    Returns:
        {completed, in_progress, pending, failed, total, completion_rate, trainings}
    """
    await _set_tenant(db, tenant_id)
    eid = _to_uuid(employee_id)
    tid = _to_uuid(tenant_id)

    result = await db.execute(
        text("""
            SELECT id, course_id, course_name, category, status,
                   pass_threshold, score, certificate_id,
                   assigned_at, started_at, completed_at
            FROM employee_trainings
            WHERE tenant_id = :tid AND employee_id = :eid
            ORDER BY assigned_at DESC
        """),
        {"tid": tid, "eid": eid},
    )
    rows = result.fetchall()

    trainings = [
        {
            "training_id": str(r.id),
            "course_id": r.course_id,
            "course_name": r.course_name,
            "category": r.category,
            "status": r.status,
            "pass_threshold": r.pass_threshold,
            "score": r.score,
            "certificate_id": r.certificate_id,
            "assigned_at": r.assigned_at.isoformat() if r.assigned_at else None,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        }
        for r in rows
    ]

    cnt_completed = sum(1 for t in trainings if t["status"] == TRAINING_STATUS_COMPLETED)
    cnt_in_progress = sum(1 for t in trainings if t["status"] == TRAINING_STATUS_IN_PROGRESS)
    cnt_pending = sum(1 for t in trainings if t["status"] == TRAINING_STATUS_PENDING)
    cnt_failed = sum(1 for t in trainings if t["status"] == TRAINING_STATUS_FAILED)
    total = len(trainings)
    completion_rate = round(cnt_completed / max(total, 1), 4)

    by_category: dict[str, dict] = {}
    for t in trainings:
        cat = t.get("category", "other")
        if cat not in by_category:
            by_category[cat] = {"total": 0, "completed": 0}
        by_category[cat]["total"] += 1
        if t["status"] == TRAINING_STATUS_COMPLETED:
            by_category[cat]["completed"] += 1

    logger.info("training_progress_queried", employee_id=employee_id,
                total=total, completed=cnt_completed,
                completion_rate=completion_rate, tenant_id=tenant_id)

    return {
        "employee_id": employee_id,
        "completed": cnt_completed,
        "in_progress": cnt_in_progress,
        "pending": cnt_pending,
        "failed": cnt_failed,
        "total": total,
        "completion_rate": completion_rate,
        "by_category": by_category,
        "trainings": trainings,
    }


# ── 5. 员工绩效卡 ────────────────────────────────────────────


async def get_employee_scorecard(
    employee_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """员工绩效卡 — 多维雷达

    维度:
      1. 服务量 — 服务桌数/订单数
      2. 营收贡献 — 服务订单总额
      3. 客户满意 — 基于投诉率/好评
      4. 效率 — 平均服务时长
      5. 技能成长 — 培训完成率
      6. 出勤 — 基于排班到岗

    各维度 0-100 分。

    Returns:
        {dimensions, overall_score, rank_percentile, trend}
    """
    await _set_tenant(db, tenant_id)
    tid = _to_uuid(tenant_id)
    eid = _to_uuid(employee_id)

    # 获取员工信息
    emp_result = await db.execute(
        select(Employee)
        .where(Employee.id == eid)
        .where(Employee.tenant_id == tid)
        .where(Employee.is_deleted == False)  # noqa: E712
    )
    employee = emp_result.scalar_one_or_none()
    if not employee:
        return {"error": "employee_not_found", "employee_id": employee_id}

    now = datetime.now(timezone.utc)
    # 近30天数据
    from datetime import timedelta
    start_30d = now - timedelta(days=30)

    # ── 维度1: 服务量 ──
    service_result = await db.execute(
        select(
            func.count(Order.id).label("order_count"),
            func.count(func.distinct(Order.table_number)).label("table_count"),
        )
        .where(Order.tenant_id == tid)
        .where(Order.waiter_id == employee_id)
        .where(Order.is_deleted == False)  # noqa: E712
        .where(Order.order_time >= start_30d)
    )
    svc_row = service_result.one()
    order_count_30d = svc_row.order_count or 0
    table_count_30d = svc_row.table_count or 0
    # 假设月目标300桌
    service_score = min(int(table_count_30d / 3), 100)

    # ── 维度2: 营收贡献 ──
    revenue_result = await db.execute(
        select(func.coalesce(func.sum(Order.total_amount_fen), 0))
        .where(Order.tenant_id == tid)
        .where(Order.waiter_id == employee_id)
        .where(Order.is_deleted == False)  # noqa: E712
        .where(Order.order_time >= start_30d)
    )
    revenue_30d_fen = revenue_result.scalar() or 0
    # 假设月目标 50 万分(5000元)
    revenue_score = min(int(revenue_30d_fen / 5000), 100)

    # ── 维度3: 客户满意 ──
    complaint_result = await db.execute(
        select(func.count(Order.id))
        .where(Order.tenant_id == tid)
        .where(Order.waiter_id == employee_id)
        .where(Order.is_deleted == False)  # noqa: E712
        .where(Order.order_time >= start_30d)
        .where(Order.abnormal_flag == True)  # noqa: E712
    )
    complaint_count = complaint_result.scalar() or 0
    complaint_rate = complaint_count / max(order_count_30d, 1)
    satisfaction_score = max(int((1 - complaint_rate) * 100), 0)

    # ── 维度4: 效率 ──
    efficiency_result = await db.execute(
        select(func.avg(Order.serve_duration_min))
        .where(Order.tenant_id == tid)
        .where(Order.waiter_id == employee_id)
        .where(Order.is_deleted == False)  # noqa: E712
        .where(Order.order_time >= start_30d)
        .where(Order.serve_duration_min.isnot(None))
    )
    avg_serve_min = efficiency_result.scalar()
    # 假设目标30分钟，越快分越高
    if avg_serve_min is not None and avg_serve_min > 0:
        efficiency_score = max(int((1 - max(float(avg_serve_min) - 15, 0) / 30) * 100), 0)
    else:
        efficiency_score = 50  # 无数据给中间分

    # ── 维度5: 技能成长 ──
    training_data = await get_training_progress(employee_id, tenant_id, db)
    skill_score = int(training_data["completion_rate"] * 100)

    # ── 维度6: 出勤 ──
    # 简化: 基于 employment_status
    if employee.employment_status == "regular":
        attendance_score = 90
    elif employee.employment_status == "probation":
        attendance_score = 75
    else:
        attendance_score = 60

    # ── 综合得分 ──
    dimensions = {
        "service_volume": {"score": service_score, "label": "服务量",
                           "detail": f"桌数{table_count_30d}/订单{order_count_30d}"},
        "revenue": {"score": revenue_score, "label": "营收贡献",
                     "detail": f"总额{revenue_30d_fen}分"},
        "satisfaction": {"score": satisfaction_score, "label": "客户满意",
                          "detail": f"投诉{complaint_count}单"},
        "efficiency": {"score": efficiency_score, "label": "效率",
                        "detail": f"平均出餐{avg_serve_min or 'N/A'}分钟"},
        "skill_growth": {"score": skill_score, "label": "技能成长",
                          "detail": f"完成率{training_data['completion_rate']*100:.0f}%"},
        "attendance": {"score": attendance_score, "label": "出勤",
                        "detail": employee.employment_status},
    }

    scores = [d["score"] for d in dimensions.values()]
    overall_score = round(sum(scores) / len(scores), 1)

    # 门店内排名百分位（简化: 基于总分估算）
    rank_percentile = min(overall_score / 100, 1.0)

    logger.info(
        "employee_scorecard_generated",
        employee_id=employee_id,
        overall_score=overall_score,
        service=service_score,
        revenue=revenue_score,
        tenant_id=tenant_id,
    )

    return {
        "employee_id": employee_id,
        "emp_name": employee.emp_name,
        "role": employee.role,
        "store_id": str(employee.store_id),
        "dimensions": dimensions,
        "overall_score": overall_score,
        "rank_percentile": rank_percentile,
        "period": "last_30_days",
        "generated_at": now.isoformat(),
    }
