"""能耗管理 API 路由 — Phase 4 IoT事件驱动

端点：
  POST /api/v1/ops/energy/readings     — 抄表数据上报（IoT电表/燃气表/水表）
  POST /api/v1/ops/energy/benchmarks   — 设置能耗基准线
  GET  /api/v1/ops/energy/snapshot     — 当日能耗快照（读 mv_energy_efficiency）

每个读数发射 EnergyEventType.READING_CAPTURED 事件，
异常读数同时发射 EnergyEventType.ANOMALY_DETECTED，
由 EnergyEfficiencyProjector 异步消费并更新 mv_energy_efficiency 视图。

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import EnergyEventType

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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  异常检测阈值（简化规则，投影器中有更完整的统计逻辑）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_ANOMALY_RATIO_THRESHOLD = 0.15   # 能耗/营收比超过 15% 判定为异常
_ANOMALY_DELTA_MULTIPLIER = 3.0   # 增量超过基准 3 倍判定为异常


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
    energy_revenue_ratio = (
        req.delta_value / (revenue_fen / 100) if revenue_fen > 0 else None
    )

    is_anomaly = (
        energy_revenue_ratio is not None and energy_revenue_ratio > _ANOMALY_RATIO_THRESHOLD
    )

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
        energy_field: req.delta_value,       # EnergyEfficiencyProjector 读取此字段
        "delta_value": req.delta_value,      # 保留原值便于审计
        "unit": req.unit,
        "cost_fen": 0,                       # IoT 侧暂不传成本，由管理后台录入
        "revenue_fen": revenue_fen,
        "energy_revenue_ratio": energy_revenue_ratio,
        "source": req.source,
        "recorded_at": recorded_at.isoformat(),
    }

    asyncio.create_task(emit_event(
        event_type=EnergyEventType.READING_CAPTURED,
        tenant_id=x_tenant_id,
        stream_id=reading_id,
        payload=payload,
        store_id=req.store_id,
        source_service="tx-ops",
        metadata={"stat_date": stat_date.isoformat(), "meter_type": req.meter_type},
    ))

    if is_anomaly:
        asyncio.create_task(emit_event(
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
        ))

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

    asyncio.create_task(emit_event(
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
    ))

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
            "优秀" if ratio <= 0.05 else
            "良好" if ratio <= 0.08 else
            "警告" if ratio <= 0.12 else
            "超标"
        )
        return {"ok": True, "data": data}

    # fallback 路径：Agent 已通过 Claude 推理，直接返回分析结果
    result["store_id"] = store_id
    result["stat_date"] = (stat_date or date.today()).isoformat()
    result["source"] = "agent_analysis"
    return {"ok": True, "data": result}
