"""损耗告警 + 采购反馈 API 路由

端点:
  GET  /api/v1/supply/yield-alerts/{store_id}              — 告警列表(支持status/severity过滤)
  GET  /api/v1/supply/yield-alerts/{store_id}/trend         — 损耗趋势(按原料)
  POST /api/v1/supply/yield-alerts/{alert_id}/acknowledge   — 确认告警
  POST /api/v1/supply/yield-alerts/{alert_id}/resolve       — 解决告警
  PUT  /api/v1/supply/yield-alerts/thresholds               — 设置告警阈值
  POST /api/v1/supply/yield-alerts/{store_id}/scan          — 手动触发当日扫描
  GET  /api/v1/supply/procurement-feedback/{store_id}/accuracy — 预测准确率
  POST /api/v1/supply/procurement-feedback                   — 录入反馈

统一响应格式: {"ok": bool, "data": {}, "error": {}}

# ROUTER REGISTRATION:
# from .api.yield_alert_routes import router as yield_alert_router
# app.include_router(yield_alert_router)
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from shared.ontology.src.database import get_db as _get_db

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["yield-alerts"])


# ─── 请求/响应模型 ───────────────────────────────────────


class ResolveAlertRequest(BaseModel):
    resolved_by: str = Field(..., description="解决人ID")
    note: str = Field(..., min_length=1, max_length=500, description="解决说明")


class ThresholdUpdateRequest(BaseModel):
    warning_pct: Optional[float] = Field(
        None, ge=1.0, le=50.0, description="警告阈值(%)"
    )
    critical_pct: Optional[float] = Field(
        None, ge=5.0, le=80.0, description="严重阈值(%)"
    )


class FeedbackRequest(BaseModel):
    store_id: str
    ingredient_id: str
    recommended_qty: float = Field(..., gt=0, description="建议采购量")
    actual_purchased_qty: Optional[float] = Field(None, ge=0, description="实际采购量")
    actual_consumed_qty: Optional[float] = Field(None, ge=0, description="实际消耗量")
    waste_qty: float = Field(0.0, ge=0, description="浪费量")
    feedback_date: Optional[str] = Field(None, description="反馈日期 YYYY-MM-DD")
    weather_condition: Optional[str] = Field(
        None, description="天气: sunny/cloudy/rainy/heavy_rain/snow"
    )
    is_holiday: bool = Field(False, description="是否节假日")
    holiday_name: Optional[str] = Field(None, max_length=50, description="节假日名称")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /api/v1/supply/yield-alerts/{store_id}
#  告警列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/api/v1/supply/yield-alerts/{store_id}")
async def list_yield_alerts(
    store_id: str,
    status: Optional[str] = Query(None, description="状态过滤: open/acknowledged/resolved"),
    severity: Optional[str] = Query(None, description="严重程度: warning/critical"),
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(20, ge=1, le=100, description="每页大小"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db=Depends(_get_db),
):
    """获取门店损耗告警列表

    支持按状态(open/acknowledged/resolved)、严重程度(warning/critical)、
    日期范围过滤。按日期倒序、严重程度优先排序。
    """
    from ..services.yield_alert_service import YieldAlertService

    svc = YieldAlertService()

    # 解析日期
    parsed_start: date | None = None
    parsed_end: date | None = None
    if start_date:
        try:
            parsed_start = date.fromisoformat(start_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="start_date 格式错误, 应为 YYYY-MM-DD")
    if end_date:
        try:
            parsed_end = date.fromisoformat(end_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="end_date 格式错误, 应为 YYYY-MM-DD")

    # 校验 status/severity 枚举值
    valid_statuses = {"open", "acknowledged", "resolved"}
    if status and status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"status 应为 {valid_statuses} 之一",
        )
    valid_severities = {"warning", "critical"}
    if severity and severity not in valid_severities:
        raise HTTPException(
            status_code=400,
            detail=f"severity 应为 {valid_severities} 之一",
        )

    result = await svc.get_alerts(
        store_id=store_id,
        tenant_id=x_tenant_id,
        db=db,
        status=status,
        severity=severity,
        start_date=parsed_start,
        end_date=parsed_end,
        page=page,
        size=size,
    )

    return {"ok": True, "data": result}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /api/v1/supply/yield-alerts/{store_id}/trend
#  损耗趋势
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/api/v1/supply/yield-alerts/{store_id}/trend")
async def get_yield_trend(
    store_id: str,
    ingredient_id: Optional[str] = Query(None, description="原料ID(不传=全部)"),
    days: int = Query(30, ge=1, le=365, description="回溯天数"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db=Depends(_get_db),
):
    """获取门店损耗趋势

    按日汇总差异率, 返回趋势数据 + TOP5超标原料 + 统计摘要。
    可选按单一原料查看趋势。
    """
    from ..services.yield_alert_service import YieldAlertService

    svc = YieldAlertService()
    result = await svc.get_yield_trend(
        store_id=store_id,
        tenant_id=x_tenant_id,
        db=db,
        ingredient_id=ingredient_id,
        days=days,
    )

    return {"ok": True, "data": result}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /api/v1/supply/yield-alerts/{alert_id}/acknowledge
#  确认告警
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/api/v1/supply/yield-alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db=Depends(_get_db),
):
    """确认告警

    将告警从 open 状态变更为 acknowledged。
    表示已知悉该损耗异常, 正在处理。
    """
    from ..services.yield_alert_service import YieldAlertService

    svc = YieldAlertService()
    result = await svc.acknowledge_alert(
        alert_id=alert_id,
        tenant_id=x_tenant_id,
        db=db,
    )

    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "操作失败"))

    return {"ok": True, "data": result}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /api/v1/supply/yield-alerts/{alert_id}/resolve
#  解决告警
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/api/v1/supply/yield-alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: str,
    body: ResolveAlertRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db=Depends(_get_db),
):
    """解决告警

    将告警标记为已解决, 需提供解决人ID和说明。
    支持从 open 或 acknowledged 状态变更。
    """
    from ..services.yield_alert_service import YieldAlertService

    svc = YieldAlertService()
    result = await svc.resolve_alert(
        alert_id=alert_id,
        resolved_by=body.resolved_by,
        note=body.note,
        tenant_id=x_tenant_id,
        db=db,
    )

    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "操作失败"))

    return {"ok": True, "data": result}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PUT /api/v1/supply/yield-alerts/thresholds
#  设置告警阈值
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.put("/api/v1/supply/yield-alerts/thresholds")
async def update_thresholds(
    body: ThresholdUpdateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """设置告警阈值

    调整 warning (默认8%) 和 critical (默认15%) 的触发阈值。
    warning_pct 必须小于 critical_pct。
    """
    from ..services.yield_alert_service import YieldAlertService

    svc = YieldAlertService()
    try:
        result = svc.update_thresholds(
            warning_pct=body.warning_pct,
            critical_pct=body.critical_pct,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"ok": True, "data": result}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /api/v1/supply/yield-alerts/{store_id}/scan
#  手动触发当日扫描 (管理员/调试用)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/api/v1/supply/yield-alerts/{store_id}/scan")
async def trigger_daily_scan(
    store_id: str,
    target_date: Optional[str] = Query(None, description="扫描日期 YYYY-MM-DD(默认今天)"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db=Depends(_get_db),
):
    """手动触发损耗扫描

    扫描指定门店和日期的理论vs实际用量差异,
    自动生成告警记录。通常由定时任务在每日22:00自动执行。
    """
    from ..services.yield_alert_service import YieldAlertService

    svc = YieldAlertService()

    scan_date = date.today()
    if target_date:
        try:
            scan_date = date.fromisoformat(target_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="target_date 格式错误, 应为 YYYY-MM-DD")

    alerts = await svc.generate_alerts(
        store_id=store_id,
        target_date=scan_date,
        tenant_id=x_tenant_id,
        db=db,
    )

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "scan_date": scan_date.isoformat(),
            "alerts_generated": len(alerts),
            "critical_count": sum(1 for a in alerts if a["severity"] == "critical"),
            "warning_count": sum(1 for a in alerts if a["severity"] == "warning"),
            "alerts": [
                {
                    "id": a["id"],
                    "ingredient_name": a["ingredient_name"],
                    "variance_pct": a["variance_pct"],
                    "severity": a["severity"],
                    "shift_id": a.get("shift_id"),
                    "root_cause": a["root_cause"],
                    "root_cause_label": a.get("root_cause_label", ""),
                }
                for a in alerts
            ],
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /api/v1/supply/procurement-feedback/{store_id}/accuracy
#  预测准确率
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/api/v1/supply/procurement-feedback/{store_id}/accuracy")
async def get_forecast_accuracy(
    store_id: str,
    period_days: int = Query(30, ge=1, le=365, description="统计周期(天)"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db=Depends(_get_db),
):
    """获取采购预测准确率

    使用 MAPE (Mean Absolute Percentage Error) 指标:
      MAPE = AVG(|actual_consumed - recommended| / actual_consumed) * 100
      准确率 = 100 - MAPE

    返回:
    - MAPE 和准确率
    - 偏差分布 (预测过高/过低/准确)
    - 最差原料TOP5
    """
    from ..services.procurement_feedback_service import ProcurementFeedbackService

    svc = ProcurementFeedbackService()
    result = await svc.get_forecast_accuracy(
        store_id=store_id,
        tenant_id=x_tenant_id,
        db=db,
        period_days=period_days,
    )

    return {"ok": True, "data": result}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /api/v1/supply/procurement-feedback
#  录入采购反馈
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/api/v1/supply/procurement-feedback")
async def record_procurement_feedback(
    body: FeedbackRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db=Depends(_get_db),
):
    """录入采购反馈

    记录建议量 vs 实际采购量 vs 实际消耗量,
    自动计算偏差率和修正系数。

    每日收货完成后调用, 构成预测->执行->反馈的闭环。
    """
    from ..services.procurement_feedback_service import ProcurementFeedbackService

    svc = ProcurementFeedbackService()

    # 解析日期
    feedback_date: date | None = None
    if body.feedback_date:
        try:
            feedback_date = date.fromisoformat(body.feedback_date)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="feedback_date 格式错误, 应为 YYYY-MM-DD",
            )

    # 校验天气枚举
    valid_weather = {"sunny", "cloudy", "rainy", "heavy_rain", "snow"}
    if body.weather_condition and body.weather_condition not in valid_weather:
        raise HTTPException(
            status_code=400,
            detail=f"weather_condition 应为 {valid_weather} 之一",
        )

    result = await svc.record_feedback(
        store_id=body.store_id,
        ingredient_id=body.ingredient_id,
        recommended_qty=body.recommended_qty,
        actual_purchased_qty=body.actual_purchased_qty,
        actual_consumed_qty=body.actual_consumed_qty,
        tenant_id=x_tenant_id,
        db=db,
        feedback_date=feedback_date,
        weather_condition=body.weather_condition,
        is_holiday=body.is_holiday,
        holiday_name=body.holiday_name,
        waste_qty=body.waste_qty,
    )

    return {"ok": True, "data": result}
