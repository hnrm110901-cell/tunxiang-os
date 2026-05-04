"""活鲜库存 API -- 状态跟踪/损耗/鱼缸库存/按重定价/仪表盘
           + 海鲜专项管理（鱼缸水质/活鲜收货入库/死亡损耗/死亡率/综合预警）

所有接口需要 X-Tenant-ID header。重量单位：克(g)。金额单位：分(fen)。
"""

from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from services.tx_supply.src.services import live_seafood_v2
from services.tx_supply.src.services import seafood_management_service as svc
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db as _get_db

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/supply/seafood", tags=["seafood"])


# ─── 请求模型 ─────────────────────────────────────────────────────────────────


class TrackStatusRequest(BaseModel):
    ingredient_id: str
    store_id: str
    status: str = Field(description="alive|weak|dead")
    weight_g: float = Field(gt=0, description="称重(克)")


class LiveLossRequest(BaseModel):
    store_id: str
    start_date: date
    end_date: date


class PriceByWeightRequest(BaseModel):
    ingredient_id: str
    weight_g: float = Field(gt=0, description="称重(克)")


class TransferRequest(BaseModel):
    from_store_id: str
    from_warehouse_type: str = Field(description="central|store|dept")
    to_store_id: str
    to_warehouse_type: str = Field(description="central|store|dept")
    items: list[dict] = Field(description="[{ingredient_id, quantity_g}]")


# ─── 新增：海鲜专项管理请求模型 ───────────────────────────────────────────────


class StockIntakeRequest(BaseModel):
    """活鲜收货入库请求。产地证明+检疫证为食安硬约束必填项。"""

    ingredient_id: str = Field(description="原料ID（关联 ingredients 表）")
    species: str = Field(min_length=1, max_length=50, description="品种名称，如：草鱼/龙虾")
    spec: str = Field(default="", max_length=100, description="规格描述，如：500g-1kg/只")
    origin: str = Field(min_length=1, max_length=100, description="产地，如：湖南湘潭")
    quantity_kg: float = Field(gt=0, description="入库重量(kg)")
    unit_price_fen: int = Field(ge=0, description="进货单价(分/kg)")
    supplier_name: str = Field(min_length=1, max_length=100, description="供应商名称")
    origin_certificate_no: str = Field(min_length=1, description="产地证明编号（食安合规必填）")
    quarantine_certificate_no: str = Field(min_length=1, description="检疫证编号（食安合规必填）")
    operator_id: str = Field(description="操作人员工ID")
    tank_id: Optional[str] = Field(default=None, description="入缸ID（可选）")
    notes: Optional[str] = Field(default=None, max_length=500, description="备注")


class MortalityRequest(BaseModel):
    """死亡损耗记录请求。"""

    ingredient_id: str
    species: str = Field(min_length=1, max_length=50, description="品种名称")
    quantity_kg: float = Field(gt=0, description="死亡重量(kg)")
    reason: str = Field(
        min_length=1,
        max_length=200,
        description="死亡原因，如：运输应激/水质异常/自然死亡/疾病",
    )
    operator_id: str
    tank_id: Optional[str] = Field(default=None, description="所在鱼缸ID")
    notes: Optional[str] = Field(default=None, max_length=500)


class TankReadingRequest(BaseModel):
    """水质检测数据记录请求。"""

    tank_id: str = Field(min_length=1, description="鱼缸/水族箱ID")
    temperature: Optional[float] = Field(default=None, ge=-5.0, le=50.0, description="水温(℃)")
    salinity_ppt: Optional[float] = Field(default=None, ge=0.0, le=50.0, description="盐度(ppt，千分比)")
    dissolved_oxygen_mgl: Optional[float] = Field(default=None, ge=0.0, le=30.0, description="溶解氧(mg/L)")
    ph: Optional[float] = Field(default=None, ge=0.0, le=14.0, description="pH值")
    operator_id: str
    notes: Optional[str] = Field(default=None, max_length=500)


# ─── 依赖注入占位 ─────────────────────────────────────────────────────────────


# ─── 原有端点（保持不变） ─────────────────────────────────────────────────────


@router.post("/track-status")
async def api_track_live_status(
    body: TrackStatusRequest,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    """记录活鲜状态变更（alive/weak/dead，不可逆）"""
    try:
        result = await live_seafood_v2.track_live_status(
            ingredient_id=body.ingredient_id,
            store_id=body.store_id,
            status=body.status,
            weight_g=body.weight_g,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/loss")
async def api_calculate_live_loss(
    body: LiveLossRequest,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    """计算活鲜损耗（死亡/品质降级/称重差）"""
    try:
        result = await live_seafood_v2.calculate_live_loss(
            store_id=body.store_id,
            date_range=(body.start_date, body.end_date),
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/tanks/{store_id}")
async def api_get_tank_inventory(
    store_id: str,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    """获取门店鱼缸/水箱分区库存"""
    result = await live_seafood_v2.get_tank_inventory(
        store_id=store_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {"ok": True, "data": result}


@router.post("/price")
async def api_price_by_weight(
    body: PriceByWeightRequest,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    """按重量实时定价（活鲜时价）"""
    try:
        result = await live_seafood_v2.price_by_weight(
            ingredient_id=body.ingredient_id,
            weight_g=body.weight_g,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/dashboard/{store_id}")
async def api_get_seafood_dashboard(
    store_id: str,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    """活鲜仪表盘（库存/损耗/价值/预警）"""
    result = await live_seafood_v2.get_seafood_dashboard(
        store_id=store_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {"ok": True, "data": result}


# ─── 新增端点：海鲜专项管理 ──────────────────────────────────────────────────


@router.get("/tanks", summary="鱼缸/水族箱列表")
async def api_list_tanks(
    store_id: str = Query(..., description="门店ID"),
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
):
    """鱼缸/水族箱列表，含最新水温/盐度/溶氧/pH 读数。"""
    result = await svc.list_tanks(
        store_id=store_id,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": result}


@router.get("/stock", summary="活鲜库存列表")
async def api_list_seafood_stock(
    store_id: str = Query(..., description="门店ID"),
    species: Optional[str] = Query(default=None, description="品种过滤"),
    origin: Optional[str] = Query(default=None, description="产地过滤"),
    spec: Optional[str] = Query(default=None, description="规格过滤"),
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
):
    """活鲜库存查询，按品种/规格/产地过滤。含产地证明和检疫证记录。"""
    result = await svc.list_stock(
        store_id=store_id,
        tenant_id=x_tenant_id,
        species=species,
        origin=origin,
        spec=spec,
    )
    return {"ok": True, "data": result}


@router.post("/stock/intake", summary="活鲜收货入库", status_code=201)
async def api_intake_stock(
    store_id: str = Query(..., description="门店ID"),
    body: StockIntakeRequest = ...,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
):
    """活鲜收货入库。产地证明（origin_certificate_no）和检疫证（quarantine_certificate_no）
    为食安硬约束必填项，缺失时拒绝入库。"""
    try:
        result = await svc.intake_stock(
            store_id=store_id,
            tenant_id=x_tenant_id,
            ingredient_id=body.ingredient_id,
            species=body.species,
            spec=body.spec,
            origin=body.origin,
            quantity_kg=body.quantity_kg,
            unit_price_fen=body.unit_price_fen,
            supplier_name=body.supplier_name,
            origin_certificate_no=body.origin_certificate_no,
            quarantine_certificate_no=body.quarantine_certificate_no,
            operator_id=body.operator_id,
            tank_id=body.tank_id,
            notes=body.notes,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/stock/mortality", summary="记录死亡损耗", status_code=201)
async def api_record_mortality(
    store_id: str = Query(..., description="门店ID"),
    body: MortalityRequest = ...,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
):
    """记录活鲜死亡损耗（品种/数量/原因）。自动从库存中扣减（FIFO）。"""
    try:
        result = await svc.record_mortality(
            store_id=store_id,
            tenant_id=x_tenant_id,
            ingredient_id=body.ingredient_id,
            species=body.species,
            quantity_kg=body.quantity_kg,
            reason=body.reason,
            operator_id=body.operator_id,
            tank_id=body.tank_id,
            notes=body.notes,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/mortality-rate", summary="死亡率统计")
async def api_get_mortality_rate(
    store_id: str = Query(..., description="门店ID"),
    days: int = Query(default=7, ge=1, le=90, description="统计天数，7 或 30"),
    species: Optional[str] = Query(default=None, description="指定品种（空=全部）"),
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
):
    """死亡率统计（近7天/30天，按品种汇总）。死亡率 > 5%/天的品种会被标记 is_alert=true。"""
    result = await svc.get_mortality_rate(
        store_id=store_id,
        tenant_id=x_tenant_id,
        days=days,
        species=species,
    )
    return {"ok": True, "data": result}


@router.post("/tank-reading", summary="记录水质检测数据", status_code=201)
async def api_record_tank_reading(
    store_id: str = Query(..., description="门店ID"),
    body: TankReadingRequest = ...,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
):
    """记录水质检测数据（水温/盐度/溶氧/pH）。水温超出品种适宜范围或 pH 异常时自动生成预警。"""
    result = await svc.record_tank_reading(
        store_id=store_id,
        tenant_id=x_tenant_id,
        tank_id=body.tank_id,
        temperature=body.temperature,
        salinity_ppt=body.salinity_ppt,
        dissolved_oxygen_mgl=body.dissolved_oxygen_mgl,
        ph=body.ph,
        operator_id=body.operator_id,
        notes=body.notes,
    )
    return {"ok": True, "data": result}


@router.get("/alerts", summary="综合预警")
async def api_get_alerts(
    store_id: str = Query(..., description="门店ID"),
    min_stock_kg: float = Query(default=5.0, ge=0, description="库存低预警阈值(kg)，默认5kg"),
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
):
    """综合预警：死亡率异常（>5%/天）/ 水质异常（水温/pH） / 库存低（< 安全库存）。"""
    result = await svc.get_alerts(
        store_id=store_id,
        tenant_id=x_tenant_id,
        min_stock_kg_threshold=min_stock_kg,
    )
    return {"ok": True, "data": result}
