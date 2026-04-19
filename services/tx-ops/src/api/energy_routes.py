"""能耗管理 API 路由 — Phase 4 IoT事件驱动

端点：
  POST /api/v1/ops/energy/readings          — 抄表数据上报（IoT电表/燃气表/水表）
  POST /api/v1/ops/energy/benchmarks        — 设置能耗基准线
  GET  /api/v1/ops/energy/snapshot          — 当日能耗快照（读 mv_energy_efficiency）
  GET  /api/v1/ops/energy/budgets           — 列出月度预算（按年月过滤）
  POST /api/v1/ops/energy/budgets           — 设置月度预算（UPSERT）
  GET  /api/v1/ops/energy/alert-rules       — 列出告警规则
  POST /api/v1/ops/energy/alert-rules       — 创建告警规则
  DELETE /api/v1/ops/energy/alert-rules/{rule_id} — 删除告警规则
  GET  /api/v1/ops/energy/budget-vs-actual  — 本月预算 vs 实际对比

每个读数发射 EnergyEventType.READING_CAPTURED 事件，
异常读数同时发射 EnergyEventType.ANOMALY_DETECTED，
设置预算发射 EnergyEventType.BUDGET_SET，
创建告警规则发射 EnergyEventType.ALERT_RULE_CREATED，
由 EnergyEfficiencyProjector 异步消费并更新 mv_energy_efficiency 视图。

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import EnergyEventType
from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/ops/energy", tags=["energy"])
log = structlog.get_logger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class EnergyReadingReq(BaseModel):
    """能耗抄表请求（IoT电表/燃气表/水表上报或人工录入）"""

    store_id: str = Field(..., description="门店ID")
    meter_id: str = Field(..., description="仪表编号（电表/燃气表/水表）")
    meter_type: str = Field(..., description="仪表类型：electricity/gas/water")
    reading_value: float = Field(..., description="当前表值（kWh / m³）")
    delta_value: float = Field(..., description="本次读数增量（kWh / m³）")
    unit: str = Field(..., description="计量单位：kWh / m³")
    revenue_fen: Optional[int] = Field(None, description="对应时段营业收入（分），用于计算能耗比")
    source: str = Field(default="iot", description="数据来源：iot / manual")
    recorded_at: Optional[datetime] = Field(None, description="实际采集时间（IoT设备时间戳）")


class EnergyBenchmarkReq(BaseModel):
    """能耗基准线设置"""

    store_id: str = Field(..., description="门店ID")
    meter_type: str = Field(..., description="仪表类型：electricity/gas/water")
    daily_limit: float = Field(..., description="日用量上限（kWh / m³）")
    revenue_ratio_limit: float = Field(..., description="能耗/营收比上限（如 0.08 表示 8%）")
    effective_date: Optional[date] = Field(None, description="生效日期，默认今日")


class EnergyBudgetReq(BaseModel):
    """月度能耗预算设置（UPSERT by tenant+store+year+month）"""

    store_id: str = Field(..., description="门店ID")
    budget_year: int = Field(..., description="预算年份")
    budget_month: int = Field(..., ge=1, le=12, description="预算月份（1-12）")
    electricity_kwh_budget: Optional[float] = Field(None, description="月度电量预算（kWh）")
    gas_m3_budget: Optional[float] = Field(None, description="月度燃气预算（m³）")
    water_ton_budget: Optional[float] = Field(None, description="月度用水预算（吨）")
    total_cost_budget_fen: Optional[int] = Field(None, description="月度总能耗成本预算（分）")


class EnergyAlertRuleReq(BaseModel):
    """能耗告警规则创建"""

    store_id: str = Field(..., description="门店ID")
    rule_name: str = Field(..., max_length=100, description="规则名称")
    metric: str = Field(
        ...,
        description="监控指标：electricity_kwh|gas_m3|water_ton|cost_fen|ratio",
    )
    threshold_type: str = Field(
        ...,
        description="阈值类型：absolute|budget_pct|yoy_pct",
    )
    threshold_value: float = Field(..., description="阈值（绝对值/百分比，如 90.0 表示 90%）")
    severity: str = Field(default="warning", description="严重程度：info|warning|critical")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  异常检测阈值（简化规则，投影器中有更完整的统计逻辑）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_ANOMALY_RATIO_THRESHOLD = 0.15  # 能耗/营收比超过 15% 判定为异常
_ANOMALY_DELTA_MULTIPLIER = 3.0  # 增量超过基准 3 倍判定为异常

_VALID_METRICS = {"electricity_kwh", "gas_m3", "water_ton", "cost_fen", "ratio"}
_VALID_THRESHOLD_TYPES = {"absolute", "budget_pct", "yoy_pct"}
_VALID_SEVERITIES = {"info", "warning", "critical"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DB 辅助函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  路由实现
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/readings", status_code=201)
async def capture_energy_reading(
    req: EnergyReadingReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """接收 IoT 电表/燃气表/水表读数（或人工录入）。

    自动计算能耗/营收比，超过阈值时额外发射 ANOMALY_DETECTED 事件。
    两个事件均异步发射，不阻塞接口响应。
    """
    reading_id = str(uuid.uuid4())
    recorded_at = req.recorded_at or datetime.now(timezone.utc)
    stat_date = recorded_at.date() if hasattr(recorded_at, "date") else date.today()

    # 能耗/营收比
    revenue_fen = req.revenue_fen or 0
    energy_revenue_ratio = req.delta_value / (revenue_fen / 100) if revenue_fen > 0 else None

    is_anomaly = energy_revenue_ratio is not None and energy_revenue_ratio > _ANOMALY_RATIO_THRESHOLD

    # 按仪表类型映射到投影器期望的字段名
    _meter_field = {
        "electricity": "electricity_kwh",
        "gas": "gas_m3",
        "water": "water_ton",
    }
    energy_field = _meter_field.get(req.meter_type, "electricity_kwh")

    payload = {
        "reading_id": reading_id,
        "meter_id": req.meter_id,
        "meter_type": req.meter_type,
        energy_field: req.delta_value,  # EnergyEfficiencyProjector 读取此字段
        "delta_value": req.delta_value,  # 保留原值便于审计
        "unit": req.unit,
        "cost_fen": 0,  # IoT 侧暂不传成本，由管理后台录入
        "revenue_fen": revenue_fen,
        "energy_revenue_ratio": energy_revenue_ratio,
        "source": req.source,
        "recorded_at": recorded_at.isoformat(),
    }

    asyncio.create_task(
        emit_event(
            event_type=EnergyEventType.READING_CAPTURED,
            tenant_id=x_tenant_id,
            stream_id=reading_id,
            payload=payload,
            store_id=req.store_id,
            source_service="tx-ops",
            metadata={"stat_date": stat_date.isoformat(), "meter_type": req.meter_type},
        )
    )

    if is_anomaly:
        asyncio.create_task(
            emit_event(
                event_type=EnergyEventType.ANOMALY_DETECTED,
                tenant_id=x_tenant_id,
                stream_id=reading_id,
                payload={
                    **payload,
                    "anomaly_reason": f"能耗/营收比 {energy_revenue_ratio:.2%} 超过阈值 {_ANOMALY_RATIO_THRESHOLD:.0%}",
                },
                store_id=req.store_id,
                source_service="tx-ops",
                metadata={"stat_date": stat_date.isoformat(), "severity": "warning"},
            )
        )

    log.info(
        "energy_reading_captured",
        reading_id=reading_id,
        store_id=req.store_id,
        meter_type=req.meter_type,
        delta=req.delta_value,
        is_anomaly=is_anomaly,
    )

    return {
        "ok": True,
        "data": {
            "reading_id": reading_id,
            "meter_id": req.meter_id,
            "meter_type": req.meter_type,
            "delta_value": req.delta_value,
            "unit": req.unit,
            "energy_revenue_ratio": round(energy_revenue_ratio, 4) if energy_revenue_ratio else None,
            "is_anomaly": is_anomaly,
            "store_id": req.store_id,
        },
    }


@router.post("/benchmarks", status_code=201)
async def set_energy_benchmark(
    req: EnergyBenchmarkReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """设置门店能耗基准线（日用量上限 + 能耗/营收比上限）。

    发射 EnergyEventType.BENCHMARK_SET 事件，
    EnergyEfficiencyProjector 更新基准参数。
    """
    benchmark_id = str(uuid.uuid4())
    effective_date = req.effective_date or date.today()

    asyncio.create_task(
        emit_event(
            event_type=EnergyEventType.BENCHMARK_SET,
            tenant_id=x_tenant_id,
            stream_id=benchmark_id,
            payload={
                "benchmark_id": benchmark_id,
                "meter_type": req.meter_type,
                "daily_limit": req.daily_limit,
                "revenue_ratio_limit": req.revenue_ratio_limit,
                "effective_date": effective_date.isoformat(),
            },
            store_id=req.store_id,
            source_service="tx-ops",
            metadata={"meter_type": req.meter_type},
        )
    )

    log.info(
        "energy_benchmark_set",
        benchmark_id=benchmark_id,
        store_id=req.store_id,
        meter_type=req.meter_type,
        daily_limit=req.daily_limit,
    )

    return {
        "ok": True,
        "data": {
            "benchmark_id": benchmark_id,
            "meter_type": req.meter_type,
            "daily_limit": req.daily_limit,
            "revenue_ratio_limit": req.revenue_ratio_limit,
            "effective_date": effective_date.isoformat(),
            "store_id": req.store_id,
        },
    }


@router.get("/snapshot")
async def get_energy_snapshot(
    store_id: str = Query(..., description="门店ID"),
    stat_date: Optional[date] = Query(None, description="统计日期，默认今日（agent路径忽略此参数，读最新行）"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """读取 mv_energy_efficiency 物化视图，返回最新能耗快照（Phase 3）。

    通过 EnergyMonitorAgent.analyze_from_mv() 读取，< 5ms 快速路径。
    视图无数据时 Agent 自动 fallback 到 Claude Haiku 推理。
    用于能耗仪表盘和 Agent 决策。
    """
    from services.tx_brain.src.agents.energy_monitor import energy_monitor

    result = await energy_monitor.analyze_from_mv(x_tenant_id, store_id)

    # mv_fast_path：直接返回视图数据，附加格式化字段
    if result.get("inference_layer") == "mv_fast_path":
        data = dict(result["data"])

        # 序列化特殊类型
        if data.get("updated_at") and hasattr(data["updated_at"], "isoformat"):
            data["updated_at"] = data["updated_at"].isoformat()
        if data.get("stat_date") and hasattr(data["stat_date"], "isoformat"):
            data["stat_date"] = data["stat_date"].isoformat()

        data["source"] = "mv_energy_efficiency"
        data["energy_cost_yuan"] = round(int(data.get("energy_cost_fen") or 0) / 100, 2)

        ratio = float(data.get("energy_revenue_ratio") or 0)
        data["efficiency_level"] = (
            "优秀" if ratio <= 0.05 else "良好" if ratio <= 0.08 else "警告" if ratio <= 0.12 else "超标"
        )
        return {"ok": True, "data": data}

    # fallback 路径：Agent 已通过 Claude 推理，直接返回分析结果
    result["store_id"] = store_id
    result["stat_date"] = (stat_date or date.today()).isoformat()
    result["source"] = "agent_analysis"
    return {"ok": True, "data": result}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  预算管理端点 — energy_budgets 表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/budgets")
async def list_energy_budgets(
    store_id: str = Query(..., description="门店ID"),
    year: Optional[int] = Query(None, description="过滤年份"),
    month: Optional[int] = Query(None, description="过滤月份（1-12）"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """列出门店月度能耗预算（按年月过滤）。

    数据来源：energy_budgets 表。
    """
    try:
        await _set_tenant(db, x_tenant_id)

        conditions = [
            "tenant_id = :tenant_id",
            "store_id = :store_id",
            "is_deleted = FALSE",
        ]
        params: Dict[str, Any] = {
            "tenant_id": x_tenant_id,
            "store_id": store_id,
        }

        if year is not None:
            conditions.append("EXTRACT(YEAR FROM TO_DATE(period_value, 'YYYY-MM'))::INT = :year")
            params["year"] = year
        if month is not None:
            conditions.append("EXTRACT(MONTH FROM TO_DATE(period_value, 'YYYY-MM'))::INT = :month")
            params["month"] = month

        where = " AND ".join(conditions)
        rows = await db.execute(
            text(f"""
                SELECT id, tenant_id, store_id, period_type, period_value,
                       electricity_budget_kwh, gas_budget_m3, water_budget_ton,
                       cost_budget_fen, is_active, created_at, updated_at
                FROM energy_budgets
                WHERE {where}
                ORDER BY period_value DESC
            """),
            params,
        )
        items = [dict(r._mapping) for r in rows.fetchall()]
        # 序列化时间戳
        for item in items:
            for k in ("created_at", "updated_at"):
                if item.get(k) and hasattr(item[k], "isoformat"):
                    item[k] = item[k].isoformat()
            for k in ("electricity_budget_kwh", "gas_budget_m3", "water_budget_ton"):
                if item.get(k) is not None:
                    item[k] = float(item[k])
            item["id"] = str(item["id"])
            item["tenant_id"] = str(item["tenant_id"])
            item["store_id"] = str(item["store_id"])

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("energy_budgets_list_error", error=str(exc))
        raise HTTPException(status_code=500, detail="查询能耗预算失败") from exc

    log.info("energy_budgets_listed", tenant_id=x_tenant_id, store_id=store_id, count=len(items))
    return {"ok": True, "data": {"items": items, "total": len(items)}}


@router.post("/budgets", status_code=201)
async def set_energy_budget(
    req: EnergyBudgetReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """设置门店月度能耗预算（UPSERT）。

    同一 tenant+store+period_value 重复提交时覆盖已有预算。
    发射 EnergyEventType.BUDGET_SET 事件。
    """
    period_value = f"{req.budget_year:04d}-{req.budget_month:02d}"

    try:
        await _set_tenant(db, x_tenant_id)

        result = await db.execute(
            text("""
                INSERT INTO energy_budgets
                    (tenant_id, store_id, period_type, period_value,
                     electricity_budget_kwh, gas_budget_m3, water_budget_ton,
                     cost_budget_fen, is_active, updated_at)
                VALUES
                    (:tenant_id, :store_id, 'monthly', :period_value,
                     :electricity_budget_kwh, :gas_budget_m3, :water_budget_ton,
                     :cost_budget_fen, TRUE, NOW())
                ON CONFLICT (tenant_id, store_id, period_type, period_value)
                DO UPDATE SET
                    electricity_budget_kwh = EXCLUDED.electricity_budget_kwh,
                    gas_budget_m3          = EXCLUDED.gas_budget_m3,
                    water_budget_ton       = EXCLUDED.water_budget_ton,
                    cost_budget_fen        = EXCLUDED.cost_budget_fen,
                    is_active              = TRUE,
                    updated_at             = NOW()
                RETURNING id, tenant_id, store_id, period_type, period_value,
                          electricity_budget_kwh, gas_budget_m3, water_budget_ton,
                          cost_budget_fen, is_active, created_at, updated_at
            """),
            {
                "tenant_id": x_tenant_id,
                "store_id": req.store_id,
                "period_value": period_value,
                "electricity_budget_kwh": req.electricity_kwh_budget,
                "gas_budget_m3": req.gas_m3_budget,
                "water_budget_ton": req.water_ton_budget,
                "cost_budget_fen": req.total_cost_budget_fen,
            },
        )
        await db.commit()
        row = result.fetchone()
        budget_record: Dict[str, Any] = dict(row._mapping)
        budget_id = str(budget_record["id"])
        budget_record["id"] = budget_id
        budget_record["tenant_id"] = str(budget_record["tenant_id"])
        budget_record["store_id"] = str(budget_record["store_id"])
        for k in ("created_at", "updated_at"):
            if budget_record.get(k) and hasattr(budget_record[k], "isoformat"):
                budget_record[k] = budget_record[k].isoformat()
        for k in ("electricity_budget_kwh", "gas_budget_m3", "water_budget_ton"):
            if budget_record.get(k) is not None:
                budget_record[k] = float(budget_record[k])

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("energy_budget_set_error", error=str(exc))
        raise HTTPException(status_code=500, detail="保存能耗预算失败") from exc

    asyncio.create_task(
        emit_event(
            event_type=EnergyEventType.BUDGET_SET,
            tenant_id=x_tenant_id,
            stream_id=budget_id,
            payload=budget_record,
            store_id=req.store_id,
            source_service="tx-ops",
            metadata={
                "budget_year": req.budget_year,
                "budget_month": req.budget_month,
            },
        )
    )

    log.info(
        "energy_budget_set",
        budget_id=budget_id,
        store_id=req.store_id,
        period_value=period_value,
    )
    return {"ok": True, "data": budget_record}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  告警规则端点 — energy_alert_rules 表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/alert-rules")
async def list_energy_alert_rules(
    store_id: str = Query(..., description="门店ID"),
    active_only: bool = Query(True, description="仅返回启用中的规则"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """列出门店能耗告警规则。

    数据来源：energy_alert_rules 表。
    """
    try:
        await _set_tenant(db, x_tenant_id)

        conditions = [
            "tenant_id = :tenant_id",
            "store_id = :store_id",
            "is_deleted = FALSE",
        ]
        params: Dict[str, Any] = {
            "tenant_id": x_tenant_id,
            "store_id": store_id,
        }
        if active_only:
            conditions.append("is_active = TRUE")

        where = " AND ".join(conditions)
        rows = await db.execute(
            text(f"""
                SELECT id, tenant_id, store_id, rule_name, metric,
                       threshold, comparison, alert_level, is_active,
                       created_at, updated_at
                FROM energy_alert_rules
                WHERE {where}
                ORDER BY created_at DESC
            """),
            params,
        )
        items = [dict(r._mapping) for r in rows.fetchall()]
        for item in items:
            item["id"] = str(item["id"])
            item["tenant_id"] = str(item["tenant_id"])
            item["store_id"] = str(item["store_id"])
            if item.get("threshold") is not None:
                item["threshold"] = float(item["threshold"])
            for k in ("created_at", "updated_at"):
                if item.get(k) and hasattr(item[k], "isoformat"):
                    item[k] = item[k].isoformat()

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("energy_alert_rules_list_error", error=str(exc))
        raise HTTPException(status_code=500, detail="查询告警规则失败") from exc

    log.info(
        "energy_alert_rules_listed",
        tenant_id=x_tenant_id,
        store_id=store_id,
        count=len(items),
    )
    return {"ok": True, "data": {"items": items, "total": len(items)}}


@router.post("/alert-rules", status_code=201)
async def create_energy_alert_rule(
    req: EnergyAlertRuleReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """创建能耗告警规则。

    发射 EnergyEventType.ALERT_RULE_CREATED 事件。
    """
    if req.metric not in _VALID_METRICS:
        raise HTTPException(
            status_code=422,
            detail=f"metric 必须是 {_VALID_METRICS} 之一",
        )
    if req.threshold_type not in _VALID_THRESHOLD_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"threshold_type 必须是 {_VALID_THRESHOLD_TYPES} 之一",
        )
    if req.severity not in _VALID_SEVERITIES:
        raise HTTPException(
            status_code=422,
            detail=f"severity 必须是 {_VALID_SEVERITIES} 之一",
        )

    try:
        await _set_tenant(db, x_tenant_id)

        result = await db.execute(
            text("""
                INSERT INTO energy_alert_rules
                    (tenant_id, store_id, rule_name, metric,
                     threshold, comparison, alert_level, is_active)
                VALUES
                    (:tenant_id, :store_id, :rule_name, :metric,
                     :threshold, :comparison, :alert_level, TRUE)
                RETURNING id, tenant_id, store_id, rule_name, metric,
                          threshold, comparison, alert_level, is_active,
                          created_at, updated_at
            """),
            {
                "tenant_id": x_tenant_id,
                "store_id": req.store_id,
                "rule_name": req.rule_name,
                "metric": req.metric,
                "threshold": req.threshold_value,
                "comparison": req.threshold_type,
                "alert_level": req.severity,
            },
        )
        await db.commit()
        row = result.fetchone()
        rule_record: Dict[str, Any] = dict(row._mapping)
        rule_id = str(rule_record["id"])
        rule_record["id"] = rule_id
        rule_record["tenant_id"] = str(rule_record["tenant_id"])
        rule_record["store_id"] = str(rule_record["store_id"])
        if rule_record.get("threshold") is not None:
            rule_record["threshold"] = float(rule_record["threshold"])
        for k in ("created_at", "updated_at"):
            if rule_record.get(k) and hasattr(rule_record[k], "isoformat"):
                rule_record[k] = rule_record[k].isoformat()

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("energy_alert_rule_create_error", error=str(exc))
        raise HTTPException(status_code=500, detail="创建告警规则失败") from exc

    asyncio.create_task(
        emit_event(
            event_type=EnergyEventType.ALERT_RULE_CREATED,
            tenant_id=x_tenant_id,
            stream_id=rule_id,
            payload=rule_record,
            store_id=req.store_id,
            source_service="tx-ops",
            metadata={"metric": req.metric, "severity": req.severity},
        )
    )

    log.info(
        "energy_alert_rule_created",
        rule_id=rule_id,
        store_id=req.store_id,
        metric=req.metric,
        threshold_type=req.threshold_type,
        severity=req.severity,
    )
    return {"ok": True, "data": rule_record}


@router.delete("/alert-rules/{rule_id}", status_code=200)
async def delete_energy_alert_rule(
    rule_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """软删除能耗告警规则（is_deleted = TRUE）。"""
    try:
        await _set_tenant(db, x_tenant_id)

        result = await db.execute(
            text("""
                UPDATE energy_alert_rules
                SET is_deleted = TRUE, is_active = FALSE, updated_at = NOW()
                WHERE id = :rule_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
                RETURNING id
            """),
            {"rule_id": rule_id, "tenant_id": x_tenant_id},
        )
        await db.commit()
        if result.fetchone() is None:
            raise HTTPException(status_code=404, detail="告警规则不存在")

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("energy_alert_rule_delete_error", error=str(exc))
        raise HTTPException(status_code=500, detail="删除告警规则失败") from exc

    log.info("energy_alert_rule_deleted", rule_id=rule_id, tenant_id=x_tenant_id)
    return {"ok": True, "data": {"rule_id": rule_id, "deleted": True}}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  预算 vs 实际对比端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/budget-vs-actual")
async def get_budget_vs_actual(
    store_id: str = Query(..., description="门店ID"),
    year: Optional[int] = Query(None, description="查询年份，默认当前年"),
    month: Optional[int] = Query(None, description="查询月份（1-12），默认当前月"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """本月预算 vs 实际用量对比。

    预算来源：energy_budgets 表。
    实际值来源：mv_energy_efficiency 物化视图（通过 EnergyMonitorAgent.analyze_from_mv）。

    返回格式：
    {
      "year": 2026, "month": 4,
      "electricity": {"budget_kwh": 5000, "actual_kwh": 4230, "usage_pct": 84.6},
      "gas": {...},
      "water": {...},
      "total_cost": {"budget_fen": 50000, "actual_fen": 43200, "usage_pct": 86.4},
      "alert_triggered": false
    }
    """
    from services.tx_brain.src.agents.energy_monitor import energy_monitor

    today = date.today()
    query_year = year or today.year
    query_month = month or today.month
    period_value = f"{query_year:04d}-{query_month:02d}"

    # 读取预算（DB）
    budget: Optional[Dict[str, Any]] = None
    try:
        await _set_tenant(db, x_tenant_id)
        row = await db.execute(
            text("""
                SELECT electricity_budget_kwh, gas_budget_m3, water_budget_ton, cost_budget_fen
                FROM energy_budgets
                WHERE tenant_id = :tenant_id
                  AND store_id  = :store_id
                  AND period_value = :period_value
                  AND is_deleted = FALSE
                LIMIT 1
            """),
            {"tenant_id": x_tenant_id, "store_id": store_id, "period_value": period_value},
        )
        found = row.fetchone()
        if found:
            budget = dict(found._mapping)

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("energy_budget_vs_actual_db_error", error=str(exc))
        raise HTTPException(status_code=500, detail="查询预算数据失败") from exc

    # 读取实际值（mv_energy_efficiency）
    mv_result = await energy_monitor.analyze_from_mv(x_tenant_id, store_id)
    mv_data: Dict[str, Any] = {}
    if mv_result.get("inference_layer") == "mv_fast_path":
        mv_data = dict(mv_result.get("data", {}))

    def _usage_pct(actual: Optional[float], budget_val: Optional[float]) -> Optional[float]:
        """计算使用率百分比（保留1位小数），预算或实际为 None 时返回 None。"""
        if actual is None or budget_val is None or budget_val == 0:
            return None
        return round(actual / budget_val * 100, 1)

    # 实际电量：mv 中存储的是当日累计，月度汇总暂用当日值（Phase 4 简化）
    actual_elec = float(mv_data.get("electricity_kwh") or 0) or None
    actual_gas = float(mv_data.get("gas_m3") or 0) or None
    actual_water = float(mv_data.get("water_ton") or 0) or None
    actual_cost = int(mv_data.get("energy_cost_fen") or 0) or None

    budget_elec = float(budget["electricity_budget_kwh"]) if budget and budget.get("electricity_budget_kwh") else None
    budget_gas = float(budget["gas_budget_m3"]) if budget and budget.get("gas_budget_m3") else None
    budget_water = float(budget["water_budget_ton"]) if budget and budget.get("water_budget_ton") else None
    budget_cost = int(budget["cost_budget_fen"]) if budget and budget.get("cost_budget_fen") else None

    # 读取活跃告警规则（DB）用于触发检测
    alert_triggered = False
    try:
        rules_rows = await db.execute(
            text("""
                SELECT metric, threshold, comparison
                FROM energy_alert_rules
                WHERE tenant_id = :tenant_id
                  AND store_id  = :store_id
                  AND is_active = TRUE
                  AND is_deleted = FALSE
            """),
            {"tenant_id": x_tenant_id, "store_id": store_id},
        )
        active_rules = [dict(r._mapping) for r in rules_rows.fetchall()]
        alert_triggered = _check_alert_triggered_from_rules(
            active_rules=active_rules,
            actual_elec=actual_elec,
            actual_gas=actual_gas,
            actual_water=actual_water,
            actual_cost=actual_cost,
            budget_elec=budget_elec,
            budget_gas=budget_gas,
            budget_water=budget_water,
            budget_cost=budget_cost,
        )
    except SQLAlchemyError as exc:
        # 告警检测失败不影响主流程，仅记录日志
        log.warning("energy_alert_check_error", error=str(exc))

    result: Dict[str, Any] = {
        "year": query_year,
        "month": query_month,
        "store_id": store_id,
        "electricity": {
            "budget_kwh": budget_elec,
            "actual_kwh": actual_elec,
            "usage_pct": _usage_pct(actual_elec, budget_elec),
        },
        "gas": {
            "budget_m3": budget_gas,
            "actual_m3": actual_gas,
            "usage_pct": _usage_pct(actual_gas, budget_gas),
        },
        "water": {
            "budget_ton": budget_water,
            "actual_ton": actual_water,
            "usage_pct": _usage_pct(actual_water, budget_water),
        },
        "total_cost": {
            "budget_fen": budget_cost,
            "actual_fen": actual_cost,
            "usage_pct": _usage_pct(
                float(actual_cost) if actual_cost else None,
                float(budget_cost) if budget_cost else None,
            ),
        },
        "alert_triggered": alert_triggered,
        "data_source": "mv_energy_efficiency",
        "note": "实际值为当日快照，月度汇总将在 Phase 5 接入时序数据库",
    }

    log.info(
        "energy_budget_vs_actual",
        store_id=store_id,
        year=query_year,
        month=query_month,
        alert_triggered=alert_triggered,
    )
    return {"ok": True, "data": result}


def _check_alert_triggered_from_rules(
    active_rules: List[Dict[str, Any]],
    actual_elec: Optional[float],
    actual_gas: Optional[float],
    actual_water: Optional[float],
    actual_cost: Optional[int],
    budget_elec: Optional[float],
    budget_gas: Optional[float],
    budget_water: Optional[float],
    budget_cost: Optional[int],
) -> bool:
    """对照已从 DB 查出的 active_rules 列表，判断是否有规则触发。

    仅检查 budget_pct（需预算）和 absolute 类型规则。
    """
    _metric_actual_budget_map: Dict[str, tuple] = {
        "electricity_kwh": (actual_elec, budget_elec),
        "gas_m3": (actual_gas, budget_gas),
        "water_ton": (actual_water, budget_water),
        "cost_fen": (
            float(actual_cost) if actual_cost else None,
            float(budget_cost) if budget_cost else None,
        ),
    }

    for rule in active_rules:
        threshold = float(rule["threshold"])
        metric = rule["metric"]
        comparison = rule["comparison"]

        if comparison == "budget_pct" and metric in _metric_actual_budget_map:
            actual_v, budget_v = _metric_actual_budget_map[metric]
            if actual_v is not None and budget_v and budget_v > 0:
                pct = actual_v / budget_v * 100
                if pct >= threshold:
                    return True

        elif comparison == "absolute" and metric in _metric_actual_budget_map:
            actual_v, _ = _metric_actual_budget_map[metric]
            if actual_v is not None and actual_v >= threshold:
                return True

    return False
