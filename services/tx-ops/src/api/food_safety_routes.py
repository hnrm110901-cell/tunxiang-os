"""食品安全合规 API 路由 — Phase 4 事件总线驱动

端点（4条核心合规义务路由）：
  POST /api/v1/ops/food-safety/samples           — 留样登记
  POST /api/v1/ops/food-safety/temperatures      — 温度记录
  POST /api/v1/ops/food-safety/inspections       — 检查完成
  POST /api/v1/ops/food-safety/violations        — 违规登记
  GET  /api/v1/ops/food-safety/summary           — 当日合规汇总（读 mv_safety_compliance）

每个写操作发射对应 SafetyEventType 事件，由 SafetyComplianceProjector
异步消费并更新 mv_safety_compliance 物化视图。

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timezone
from typing import Any, List, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import SafetyEventType

router = APIRouter(prefix="/api/v1/ops/food-safety", tags=["food-safety"])
log = structlog.get_logger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class FoodSampleReq(BaseModel):
    """留样登记请求"""
    store_id: str = Field(..., description="门店ID")
    dish_name: str = Field(..., description="菜品名称")
    sample_weight_g: float = Field(..., description="留样重量（克），要求 ≥ 125g")
    meal_period: str = Field(..., description="餐次：breakfast/lunch/dinner/other")
    sampler_id: str = Field(..., description="留样人员工号")
    storage_temp_celsius: float = Field(default=4.0, description="储存温度（摄氏度），要求 ≤ 4°C")
    expiry_hours: int = Field(default=48, description="保存时长（小时），法规要求 ≥ 48h")
    notes: Optional[str] = None


class TemperatureRecordReq(BaseModel):
    """温度记录请求"""
    store_id: str = Field(..., description="门店ID")
    location: str = Field(..., description="测温位置：refrigerator/freezer/hot_display/prep_area")
    temp_celsius: float = Field(..., description="实测温度（摄氏度）")
    recorder_id: str = Field(..., description="记录人员工号")
    equipment_id: Optional[str] = Field(None, description="设备编号")
    notes: Optional[str] = None


class SafetyInspectionReq(BaseModel):
    """食安检查完成请求"""
    store_id: str = Field(..., description="门店ID")
    inspector_id: str = Field(..., description="检查员工号")
    checklist_type: str = Field(..., description="检查类型：daily/weekly/monthly/surprise")
    items: List[dict[str, Any]] = Field(default_factory=list, description="检查项列表，每项包含 {item, passed, notes}")
    overall_score: float = Field(..., ge=0, le=100, description="综合评分（0-100）")
    violations: List[str] = Field(default_factory=list, description="发现的违规项列表")
    corrective_actions: List[str] = Field(default_factory=list, description="整改措施列表")


class SafetyViolationReq(BaseModel):
    """违规登记请求"""
    store_id: str = Field(..., description="门店ID")
    violation_type: str = Field(..., description="违规类型：expired_ingredient/improper_storage/hygiene/temperature/other")
    severity: str = Field(..., description="严重程度：minor/major/critical")
    description: str = Field(..., description="违规详情")
    reporter_id: str = Field(..., description="上报人员工号")
    corrective_action: Optional[str] = Field(None, description="已采取整改措施")
    ingredient_id: Optional[str] = Field(None, description="涉及食材ID（如适用）")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  温度合规阈值
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_TEMP_THRESHOLDS = {
    "refrigerator": {"min": 0, "max": 8, "unit": "冷藏"},
    "freezer": {"min": -25, "max": -15, "unit": "冷冻"},
    "hot_display": {"min": 60, "max": 90, "unit": "热展示柜"},
    "prep_area": {"min": 10, "max": 25, "unit": "备餐区"},
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  路由实现
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/samples", status_code=201)
async def log_food_sample(
    req: FoodSampleReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """登记食品留样（市场监管总局要求：集体用餐每份≥125g，保存48h）。

    成功后异步发射 SafetyEventType.SAMPLE_LOGGED 事件，
    SafetyComplianceProjector 消费并更新 mv_safety_compliance.sample_count。
    """
    if req.sample_weight_g < 125:
        raise HTTPException(
            status_code=422,
            detail=f"留样重量 {req.sample_weight_g}g 不足，法规要求 ≥ 125g",
        )
    if req.storage_temp_celsius > 4:
        raise HTTPException(
            status_code=422,
            detail=f"储存温度 {req.storage_temp_celsius}°C 超标，法规要求 ≤ 4°C",
        )
    if req.expiry_hours < 48:
        raise HTTPException(
            status_code=422,
            detail=f"保存时长 {req.expiry_hours}h 不足，法规要求 ≥ 48h",
        )

    sample_id = str(uuid.uuid4())
    logged_at = datetime.now(timezone.utc)

    asyncio.create_task(emit_event(
        event_type=SafetyEventType.SAMPLE_LOGGED,
        tenant_id=x_tenant_id,
        stream_id=sample_id,
        payload={
            "sample_id": sample_id,
            "dish_name": req.dish_name,
            "sample_weight_g": req.sample_weight_g,
            "meal_period": req.meal_period,
            "sampler_id": req.sampler_id,
            "storage_temp_celsius": req.storage_temp_celsius,
            "expiry_hours": req.expiry_hours,
            "notes": req.notes,
        },
        store_id=req.store_id,
        source_service="tx-ops",
        metadata={"stat_date": date.today().isoformat()},
    ))

    log.info(
        "food_safety_sample_logged",
        sample_id=sample_id,
        store_id=req.store_id,
        dish_name=req.dish_name,
        weight_g=req.sample_weight_g,
    )

    return {
        "ok": True,
        "data": {
            "sample_id": sample_id,
            "dish_name": req.dish_name,
            "sample_weight_g": req.sample_weight_g,
            "meal_period": req.meal_period,
            "storage_temp_celsius": req.storage_temp_celsius,
            "expiry_at": logged_at.isoformat(),
            "compliant": True,
            "store_id": req.store_id,
        },
    }


@router.post("/temperatures", status_code=201)
async def record_temperature(
    req: TemperatureRecordReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """记录食品安全温度（冷藏/冷冻/热展示/备餐区）。

    自动判定是否合规；超标时同时发射 TEMPERATURE_RECORDED（anomaly=True）
    供 SafetyComplianceProjector 扣分。
    """
    threshold = _TEMP_THRESHOLDS.get(req.location)
    compliant = True
    anomaly_detail = None

    if threshold:
        t_min, t_max = threshold["min"], threshold["max"]
        if not (t_min <= req.temp_celsius <= t_max):
            compliant = False
            anomaly_detail = (
                f"{threshold['unit']}温度 {req.temp_celsius}°C 超出"
                f"合规范围 [{t_min}, {t_max}]°C"
            )

    record_id = str(uuid.uuid4())

    asyncio.create_task(emit_event(
        event_type=SafetyEventType.TEMPERATURE_RECORDED,
        tenant_id=x_tenant_id,
        stream_id=record_id,
        payload={
            "record_id": record_id,
            "location": req.location,
            "temp_celsius": req.temp_celsius,
            "recorder_id": req.recorder_id,
            "equipment_id": req.equipment_id,
            "compliant": compliant,
            "anomaly_detail": anomaly_detail,
            "notes": req.notes,
        },
        store_id=req.store_id,
        source_service="tx-ops",
        metadata={"stat_date": date.today().isoformat()},
    ))

    log.info(
        "food_safety_temperature_recorded",
        record_id=record_id,
        store_id=req.store_id,
        location=req.location,
        temp_celsius=req.temp_celsius,
        compliant=compliant,
    )

    return {
        "ok": True,
        "data": {
            "record_id": record_id,
            "location": req.location,
            "temp_celsius": req.temp_celsius,
            "compliant": compliant,
            "anomaly_detail": anomaly_detail,
            "store_id": req.store_id,
        },
    }


@router.post("/inspections", status_code=201)
async def complete_inspection(
    req: SafetyInspectionReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """提交食安检查完成记录（日检/周检/月检/飞检）。

    检查项 passed_count / total_count 及综合评分写入事件，
    由投影器更新 mv_safety_compliance.compliance_score。
    """
    inspection_id = str(uuid.uuid4())
    total_items = len(req.items)
    passed_items = sum(1 for i in req.items if i.get("passed", False))

    asyncio.create_task(emit_event(
        event_type=SafetyEventType.INSPECTION_DONE,
        tenant_id=x_tenant_id,
        stream_id=inspection_id,
        payload={
            "inspection_id": inspection_id,
            "inspector_id": req.inspector_id,
            "checklist_type": req.checklist_type,
            "total_items": total_items,
            "passed_items": passed_items,
            "overall_score": req.overall_score,
            "violations": req.violations,
            "corrective_actions": req.corrective_actions,
        },
        store_id=req.store_id,
        source_service="tx-ops",
        metadata={"stat_date": date.today().isoformat()},
    ))

    log.info(
        "food_safety_inspection_done",
        inspection_id=inspection_id,
        store_id=req.store_id,
        checklist_type=req.checklist_type,
        overall_score=req.overall_score,
        violations=len(req.violations),
    )

    return {
        "ok": True,
        "data": {
            "inspection_id": inspection_id,
            "checklist_type": req.checklist_type,
            "total_items": total_items,
            "passed_items": passed_items,
            "pass_rate": round(passed_items / total_items, 4) if total_items else 1.0,
            "overall_score": req.overall_score,
            "violations_count": len(req.violations),
            "store_id": req.store_id,
        },
    }


@router.post("/violations", status_code=201)
async def log_violation(
    req: SafetyViolationReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """登记食品安全违规（含严重程度分级）。

    critical 级别违规同时触发实时告警（由 tx-agent 消费 VIOLATION_FOUND 事件后推送）。
    """
    violation_id = str(uuid.uuid4())

    asyncio.create_task(emit_event(
        event_type=SafetyEventType.VIOLATION_FOUND,
        tenant_id=x_tenant_id,
        stream_id=violation_id,
        payload={
            "violation_id": violation_id,
            "violation_type": req.violation_type,
            "severity": req.severity,
            "description": req.description,
            "reporter_id": req.reporter_id,
            "corrective_action": req.corrective_action,
            "ingredient_id": req.ingredient_id,
        },
        store_id=req.store_id,
        source_service="tx-ops",
        metadata={
            "stat_date": date.today().isoformat(),
            "requires_immediate_action": req.severity == "critical",
        },
    ))

    log.warning(
        "food_safety_violation_logged",
        violation_id=violation_id,
        store_id=req.store_id,
        violation_type=req.violation_type,
        severity=req.severity,
    )

    return {
        "ok": True,
        "data": {
            "violation_id": violation_id,
            "violation_type": req.violation_type,
            "severity": req.severity,
            "store_id": req.store_id,
            "requires_immediate_action": req.severity == "critical",
        },
    }


@router.get("/summary")
async def get_safety_summary(
    store_id: str = Query(..., description="门店ID"),
    stat_week: Optional[date] = Query(None, description="ISO周一日期（默认本周）"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """读取 mv_safety_compliance 物化视图，返回周度食安合规汇总（Phase 3）。

    直接读取投影视图，< 5ms，无需联表聚合。
    用于食安合规仪表盘和 Agent 决策。
    """
    import os
    from datetime import timedelta

    import asyncpg

    # 计算当周 ISO 周一
    today = date.today()
    if stat_week is None:
        stat_week = today - timedelta(days=today.weekday())

    db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/tunxiang")

    try:
        conn = await asyncpg.connect(db_url)
        try:
            await conn.execute("SELECT set_config('app.tenant_id', $1, TRUE)", x_tenant_id)
            row = await conn.fetchrow("""
                SELECT
                    sample_count, temperature_check_count, temperature_anomaly_count,
                    inspection_count, violation_count, critical_violation_count,
                    compliance_score, updated_at
                FROM mv_safety_compliance
                WHERE tenant_id = $1 AND store_id = $2 AND stat_week = $3
            """, x_tenant_id, store_id, stat_week)
        finally:
            await conn.close()
    except Exception as exc:  # noqa: BLE001 — DB不可用时降级
        log.warning("food_safety_summary_db_error", error=str(exc))
        raise HTTPException(status_code=500, detail=f"读取合规数据失败: {exc}")

    if not row:
        return {
            "ok": True,
            "data": {
                "store_id": store_id,
                "stat_week": stat_week.isoformat(),
                "message": "本周暂无食安合规数据",
                "source": "mv_safety_compliance",
            },
        }

    data = dict(row)
    if data.get("updated_at"):
        data["updated_at"] = data["updated_at"].isoformat()
    data["store_id"] = store_id
    data["stat_week"] = stat_week.isoformat()
    data["source"] = "mv_safety_compliance"
    data["compliance_level"] = (
        "优秀" if float(data.get("compliance_score") or 0) >= 90 else
        "合格" if float(data.get("compliance_score") or 0) >= 75 else
        "警告" if float(data.get("compliance_score") or 0) >= 60 else
        "危险"
    )

    return {"ok": True, "data": data}
