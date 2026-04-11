"""预测结果驱动智能排班 API — 基于客流预测生成排班建议

端点：
  GET  /api/v1/org/smart-schedule/{store_id}/suggestion  — 基于客流预测生成排班建议
  POST /api/v1/org/smart-schedule/{store_id}/apply        — 一键应用排班建议
  GET  /api/v1/org/smart-schedule/labor-forecast           — 集团级人力需求预测
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/org/smart-schedule", tags=["smart-schedule"])


# ──────────────────────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────────────────────

def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


def _err(msg: str, status: int = 400) -> HTTPException:
    return HTTPException(status_code=status, detail={"ok": False, "error": {"message": msg}})


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, TRUE)"),
                     {"tid": tenant_id})


def _serialize_row(row: Any) -> dict[str, Any]:
    d = dict(row._mapping)
    for k, v in d.items():
        if isinstance(v, uuid.UUID):
            d[k] = str(v)
        elif isinstance(v, datetime):
            d[k] = v.isoformat()
        elif isinstance(v, date):
            d[k] = str(v)
    return d


# ──────────────────────────────────────────────────────────────────────────────
# 时段定义 & 客流预测模型
# ──────────────────────────────────────────────────────────────────────────────

# 餐饮标准营业时段（可由配置覆盖）
DEFAULT_TIME_SLOTS = [
    ("09:00-11:00", 0.15),   # 早茶/备料
    ("11:00-13:00", 0.35),   # 午市高峰
    ("13:00-17:00", 0.10),   # 下午闲时
    ("17:00-19:30", 0.30),   # 晚市高峰
    ("19:30-22:00", 0.10),   # 晚市收尾
]

# 人效比：每N位客流需要1名员工
DEFAULT_TRAFFIC_PER_STAFF = 15

# 每小时人力成本（分），默认按25元/小时
DEFAULT_HOURLY_COST_FEN = 2500


async def _predict_daily_traffic(
    db: AsyncSession,
    store_id: str,
    tenant_id: str,
    target_date: date,
) -> int:
    """基于历史订单数据预测某日客流量。

    策略：取同一星期几近4周的平均客流作为预测值。
    """
    try:
        row = await db.execute(text("""
            SELECT COALESCE(AVG(daily_count), 0)::int AS avg_traffic
            FROM (
                SELECT DATE(created_at) AS d, COUNT(*) AS daily_count
                FROM orders
                WHERE tenant_id = :tid
                  AND store_id  = :store_id
                  AND is_deleted = FALSE
                  AND created_at >= :since
                  AND EXTRACT(DOW FROM created_at) = :dow
                GROUP BY DATE(created_at)
            ) sub
        """), {
            "tid": tenant_id,
            "store_id": store_id,
            "since": target_date - timedelta(days=28),
            "dow": target_date.isoweekday() % 7,  # PG DOW: Sunday=0
        })
        result = row.fetchone()
        traffic = int(result.avg_traffic) if result and result.avg_traffic else 0
        # 兜底：无历史数据时给一个基准值
        return traffic if traffic > 0 else 80
    except SQLAlchemyError:
        return 80  # 预测失败时使用保守基准


async def _get_available_employees(
    db: AsyncSession,
    store_id: str,
    tenant_id: str,
    target_date: date,
) -> list[dict[str, Any]]:
    """获取门店可排班员工列表（排除当日已请假的）。"""
    try:
        rows = await db.execute(text("""
            SELECT e.id, e.name, e.role,
                   COALESCE(e.hourly_rate_fen, :default_rate) AS hourly_rate_fen
            FROM employees e
            WHERE e.tenant_id = :tid
              AND e.store_id  = :store_id
              AND e.is_deleted = FALSE
              AND e.status = 'active'
              AND e.id NOT IN (
                  SELECT employee_id FROM leave_records
                  WHERE tenant_id = :tid
                    AND :target_date BETWEEN start_date AND end_date
                    AND status = 'approved'
                    AND is_deleted = FALSE
              )
            ORDER BY e.name
        """), {
            "tid": tenant_id,
            "store_id": store_id,
            "target_date": target_date,
            "default_rate": DEFAULT_HOURLY_COST_FEN,
        })
        return [_serialize_row(r) for r in rows]
    except SQLAlchemyError:
        return []


# ──────────────────────────────────────────────────────────────────────────────
# Pydantic 模型
# ──────────────────────────────────────────────────────────────────────────────

class ApplyScheduleRequest(BaseModel):
    schedule_id: uuid.UUID = Field(..., description="排班建议ID")


# ──────────────────────────────────────────────────────────────────────────────
# GET /{store_id}/suggestion — 基于客流预测生成排班建议
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/{store_id}/suggestion")
async def get_schedule_suggestion(
    store_id: uuid.UUID,
    start_date: date = Query(..., description="开始日期"),
    end_date: date = Query(..., description="结束日期"),
    traffic_per_staff: int = Query(DEFAULT_TRAFFIC_PER_STAFF, ge=1,
                                    description="人效比：每N位客流需1名员工"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """基于客流预测生成排班建议。

    逻辑：客流预测 -> 每时段需要人数(客流/人效比) -> 匹配可用员工 -> 生成排班方案。
    输出：每时段建议人数 + 推荐员工列表 + 预估人力成本。
    """
    if end_date < start_date:
        raise _err("end_date 不能早于 start_date")
    if (end_date - start_date).days > 14:
        raise _err("日期范围不能超过14天")

    try:
        await _set_rls(db, x_tenant_id)
        sid = str(store_id)

        daily_suggestions: list[dict[str, Any]] = []
        current = start_date

        while current <= end_date:
            # 1. 预测当日客流
            predicted_traffic = await _predict_daily_traffic(
                db, sid, x_tenant_id, current)

            # 2. 获取可用员工
            employees = await _get_available_employees(
                db, sid, x_tenant_id, current)

            # 3. 按时段分配人力
            slots: list[dict[str, Any]] = []
            total_cost_fen = 0
            emp_idx = 0

            for slot_name, traffic_ratio in DEFAULT_TIME_SLOTS:
                slot_traffic = int(predicted_traffic * traffic_ratio)
                headcount = max(1, round(slot_traffic / traffic_per_staff))

                # 分配员工（轮转分配）
                assigned = []
                for _ in range(min(headcount, len(employees))):
                    emp = employees[emp_idx % len(employees)] if employees else {}
                    if emp:
                        assigned.append({
                            "employee_id": emp["id"],
                            "name": emp.get("name", ""),
                        })
                    emp_idx += 1

                # 计算时段时长（小时）
                parts = slot_name.split("-")
                h1, m1 = map(int, parts[0].split(":"))
                h2, m2 = map(int, parts[1].split(":"))
                hours = (h2 * 60 + m2 - h1 * 60 - m1) / 60

                slot_cost = int(headcount * hours * DEFAULT_HOURLY_COST_FEN)
                total_cost_fen += slot_cost

                slots.append({
                    "time_slot": slot_name,
                    "predicted_traffic": slot_traffic,
                    "required_headcount": headcount,
                    "assigned_employees": assigned,
                    "labor_cost_fen": slot_cost,
                })

            # 4. 写入建议记录
            schedule_id = uuid.uuid4()
            await db.execute(text("""
                INSERT INTO smart_schedules
                    (id, tenant_id, store_id, schedule_date, status, source,
                     total_labor_cost_fen, predicted_traffic)
                VALUES (:id, :tid, :store_id, :sdate, 'draft', 'ai_suggested',
                        :cost, :traffic)
            """), {
                "id": str(schedule_id), "tid": x_tenant_id,
                "store_id": sid, "sdate": current,
                "cost": total_cost_fen, "traffic": predicted_traffic,
            })

            for slot in slots:
                await db.execute(text("""
                    INSERT INTO smart_schedule_slots
                        (id, tenant_id, schedule_id, time_slot, predicted_traffic,
                         required_headcount, assigned_employee_ids, labor_cost_fen)
                    VALUES (gen_random_uuid(), :tid, :schedule_id, :time_slot,
                            :traffic, :headcount, :emp_ids::jsonb, :cost)
                """), {
                    "tid": x_tenant_id,
                    "schedule_id": str(schedule_id),
                    "time_slot": slot["time_slot"],
                    "traffic": slot["predicted_traffic"],
                    "headcount": slot["required_headcount"],
                    "emp_ids": str([e["employee_id"] for e in slot["assigned_employees"]]).replace("'", '"'),
                    "cost": slot["labor_cost_fen"],
                })

            daily_suggestions.append({
                "schedule_id": str(schedule_id),
                "date": str(current),
                "predicted_traffic": predicted_traffic,
                "total_labor_cost_fen": total_cost_fen,
                "available_employees": len(employees),
                "slots": slots,
            })
            current += timedelta(days=1)

        await db.commit()

        logger.info("smart_schedule.suggestion.generated",
                    store_id=sid, days=len(daily_suggestions))

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("smart_schedule.suggestion.failed", error=str(exc))
        raise _err(f"生成排班建议失败：{exc}", 500) from exc

    return _ok({
        "store_id": str(store_id),
        "start_date": str(start_date),
        "end_date": str(end_date),
        "traffic_per_staff": traffic_per_staff,
        "days": daily_suggestions,
        "total_days": len(daily_suggestions),
    })


# ──────────────────────────────────────────────────────────────────────────────
# POST /{store_id}/apply — 一键应用排班建议
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/{store_id}/apply")
async def apply_schedule(
    store_id: uuid.UUID,
    body: ApplyScheduleRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """一键应用排班建议，写入排班表并标记来源=ai_suggested。"""
    try:
        await _set_rls(db, x_tenant_id)
        sid = str(store_id)
        schedule_id = str(body.schedule_id)

        # 1. 校验建议存在且为draft
        row = await db.execute(text("""
            SELECT id, schedule_date, status
            FROM smart_schedules
            WHERE id = :sid AND tenant_id = :tid AND store_id = :store_id
        """), {"sid": schedule_id, "tid": x_tenant_id, "store_id": sid})
        schedule = row.fetchone()

        if schedule is None:
            raise _err("排班建议不存在", 404)
        if schedule.status != "draft":
            raise _err(f"排班建议状态为 {schedule.status}，仅 draft 可应用")

        # 2. 读取时段明细
        slots_row = await db.execute(text("""
            SELECT time_slot, required_headcount, assigned_employee_ids
            FROM smart_schedule_slots
            WHERE schedule_id = :sid AND tenant_id = :tid
              AND is_deleted = FALSE
            ORDER BY time_slot
        """), {"sid": schedule_id, "tid": x_tenant_id})
        slots = slots_row.fetchall()

        # 3. 写入排班表（work_schedules）
        records_written = 0
        for slot in slots:
            emp_ids = slot.assigned_employee_ids or []
            for emp_id in emp_ids:
                await db.execute(text("""
                    INSERT INTO work_schedules
                        (id, tenant_id, store_id, employee_id, schedule_date,
                         shift_start, shift_end, source, created_at)
                    VALUES (gen_random_uuid(), :tid, :store_id, :emp_id,
                            :sdate, :shift_start, :shift_end, 'ai_suggested', NOW())
                    ON CONFLICT DO NOTHING
                """), {
                    "tid": x_tenant_id,
                    "store_id": sid,
                    "emp_id": emp_id,
                    "sdate": schedule.schedule_date,
                    "shift_start": slot.time_slot.split("-")[0],
                    "shift_end": slot.time_slot.split("-")[1],
                })
                records_written += 1

        # 4. 更新建议状态
        await db.execute(text("""
            UPDATE smart_schedules SET status = 'applied', updated_at = NOW()
            WHERE id = :sid AND tenant_id = :tid
        """), {"sid": schedule_id, "tid": x_tenant_id})

        await db.commit()
        logger.info("smart_schedule.applied", schedule_id=schedule_id,
                    records=records_written)

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("smart_schedule.apply.failed", error=str(exc))
        raise _err(f"应用排班失败：{exc}", 500) from exc

    return _ok({
        "schedule_id": schedule_id,
        "store_id": str(store_id),
        "applied": True,
        "records_written": records_written,
    })


# ──────────────────────────────────────────────────────────────────────────────
# GET /labor-forecast — 集团级人力需求预测
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/labor-forecast")
async def labor_forecast(
    days: int = Query(7, ge=1, le=30, description="预测天数"),
    traffic_per_staff: int = Query(DEFAULT_TRAFFIC_PER_STAFF, ge=1),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """集团级人力需求预测：各门店未来N天每日需要人数汇总。"""
    try:
        await _set_rls(db, x_tenant_id)

        # 获取租户下所有活跃门店
        stores_row = await db.execute(text("""
            SELECT id, name FROM stores
            WHERE tenant_id = :tid AND is_deleted = FALSE
            ORDER BY name
        """), {"tid": x_tenant_id})
        stores = stores_row.fetchall()

        today = date.today()
        store_forecasts: list[dict[str, Any]] = []

        for store in stores:
            store_id = str(store.id)
            daily_data: list[dict[str, Any]] = []

            for offset in range(days):
                target = today + timedelta(days=offset)
                traffic = await _predict_daily_traffic(
                    db, store_id, x_tenant_id, target)
                headcount = max(1, round(traffic / traffic_per_staff))
                daily_data.append({
                    "date": str(target),
                    "predicted_traffic": traffic,
                    "required_headcount": headcount,
                })

            store_forecasts.append({
                "store_id": store_id,
                "store_name": getattr(store, "name", ""),
                "daily_forecast": daily_data,
                "total_headcount": sum(d["required_headcount"] for d in daily_data),
            })

        logger.info("smart_schedule.labor_forecast",
                    stores=len(store_forecasts), days=days)

    except SQLAlchemyError as exc:
        logger.error("smart_schedule.labor_forecast.failed", error=str(exc))
        raise _err(f"人力需求预测失败：{exc}", 500) from exc

    return _ok({
        "forecast_days": days,
        "store_count": len(store_forecasts),
        "stores": store_forecasts,
        "grand_total_headcount": sum(s["total_headcount"] for s in store_forecasts),
    })
