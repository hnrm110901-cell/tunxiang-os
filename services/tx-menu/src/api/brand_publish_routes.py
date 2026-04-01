"""品牌→门店菜品三级发布体系 API

端点概览：
  A. 品牌菜品库
     GET  /api/v1/menu/brand-dishes

  B. 发布方案
     POST /api/v1/menu/publish-plans
     GET  /api/v1/menu/publish-plans
     GET  /api/v1/menu/publish-plans/{plan_id}
     POST /api/v1/menu/publish-plans/{plan_id}/items
     POST /api/v1/menu/publish-plans/{plan_id}/execute

  C. 门店菜品微调
     GET  /api/v1/menu/store-dishes
     PUT  /api/v1/menu/store-dishes/{dish_id}/override
     POST /api/v1/menu/store-dishes/batch-toggle

  D. 调价规则
     POST /api/v1/menu/price-rules
     GET  /api/v1/menu/price-rules
     PUT  /api/v1/menu/price-rules/{rule_id}
     POST /api/v1/menu/price-rules/{rule_id}/dishes

  E. 生效价格查询
     GET  /api/v1/menu/effective-price

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""
from datetime import datetime, time, date
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from shared.ontology.src.database import get_db

from ..services.brand_publish_service import BrandPublishService

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/menu", tags=["brand-publish"])


# ─── 依赖注入占位（由 main.py 的 app.dependency_overrides 注入）───



# ─── 辅助 ───

def _err(status: int, msg: str):
    raise HTTPException(
        status_code=status,
        detail={"ok": False, "error": {"message": msg}},
    )


def _svc(db: AsyncSession, tenant_id: str) -> BrandPublishService:
    return BrandPublishService(db=db, tenant_id=tenant_id)


# ══════════════════════════════════════════════════════
# A. 品牌菜品库
# ══════════════════════════════════════════════════════


@router.get("/brand-dishes")
async def list_brand_dishes(
    brand_id: Optional[str] = None,
    category_id: Optional[str] = None,
    keyword: Optional[str] = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """品牌菜品库列表（is_brand_standard=true 的菜品）。"""
    from sqlalchemy import text
    import uuid

    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        tid = uuid.UUID(x_tenant_id)

        where = "WHERE d.tenant_id = :tid AND d.is_deleted = false AND d.is_brand_standard = true"
        params: dict = {"tid": tid}

        if brand_id:
            where += " AND d.brand_id = :brand_id"
            params["brand_id"] = uuid.UUID(brand_id)
        if category_id:
            where += " AND d.category_id = :category_id"
            params["category_id"] = uuid.UUID(category_id)
        if keyword:
            where += " AND d.dish_name ILIKE :keyword"
            params["keyword"] = f"%{keyword}%"

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM dishes d {where}"),
            params,
        )
        total = count_result.scalar() or 0

        params["limit"] = size
        params["offset"] = (page - 1) * size
        rows_result = await db.execute(
            text(f"""
                SELECT d.id, d.dish_name, d.dish_code, d.price_fen,
                       d.description, d.image_url, d.category_id,
                       d.is_available, d.brand_id, d.created_at
                FROM dishes d
                {where}
                ORDER BY d.sort_order, d.dish_name
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [
            {
                "id": str(r[0]),
                "dish_name": r[1],
                "dish_code": r[2],
                "price_fen": r[3],
                "description": r[4],
                "image_url": r[5],
                "category_id": str(r[6]) if r[6] else None,
                "is_available": r[7],
                "brand_id": str(r[8]) if r[8] else None,
                "created_at": r[9].isoformat() if r[9] else None,
            }
            for r in rows_result.fetchall()
        ]
        return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}
    except ValueError as exc:
        _err(400, str(exc))


# ══════════════════════════════════════════════════════
# B. 发布方案
# ══════════════════════════════════════════════════════


class CreatePublishPlanReq(BaseModel):
    plan_name: str = Field(..., min_length=1, max_length=200)
    target_type: str = Field(
        ...,
        pattern="^(all_stores|region|stores)$",
        description="all_stores | region | stores",
    )
    target_ids: Optional[list[str]] = Field(
        None, description="区域名列表（region）或门店 ID 列表（stores）"
    )
    brand_id: Optional[str] = None
    created_by: Optional[str] = None


class PlanItemReq(BaseModel):
    dish_id: str
    override_price_fen: Optional[int] = Field(
        None, ge=0, description="可选覆盖价（分），NULL=使用品牌标准价"
    )
    is_available: bool = True


class AddPlanItemsReq(BaseModel):
    items: list[PlanItemReq] = Field(..., min_length=1)


@router.post("/publish-plans", status_code=201)
async def create_publish_plan(
    req: CreatePublishPlanReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """创建发布方案（草稿状态）。"""
    try:
        plan = await _svc(db, x_tenant_id).create_publish_plan(
            plan_name=req.plan_name,
            target_type=req.target_type,
            target_ids=req.target_ids,
            brand_id=req.brand_id,
            created_by=req.created_by,
        )
        return {"ok": True, "data": plan}
    except ValueError as exc:
        _err(400, str(exc))


@router.get("/publish-plans")
async def list_publish_plans(
    brand_id: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """列出发布方案（支持按 brand_id / status 筛选）。"""
    result = await _svc(db, x_tenant_id).list_publish_plans(
        page=page, size=size, brand_id=brand_id, status=status
    )
    return {"ok": True, "data": result}


@router.get("/publish-plans/{plan_id}")
async def get_publish_plan(
    plan_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取发布方案详情（含菜品列表）。"""
    try:
        plan = await _svc(db, x_tenant_id).get_publish_plan(plan_id)
        return {"ok": True, "data": plan}
    except ValueError as exc:
        _err(404, str(exc))


@router.post("/publish-plans/{plan_id}/items", status_code=201)
async def add_plan_items(
    plan_id: str,
    req: AddPlanItemsReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """向发布方案添加菜品（草稿状态才可修改）。"""
    try:
        items = await _svc(db, x_tenant_id).add_items_to_plan(
            plan_id=plan_id,
            items=[i.model_dump() for i in req.items],
        )
        return {"ok": True, "data": {"plan_id": plan_id, "items": items, "count": len(items)}}
    except ValueError as exc:
        _err(400, str(exc))


@router.post("/publish-plans/{plan_id}/execute")
async def execute_publish_plan(
    plan_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """执行发布方案：将品牌菜品推送到目标门店。

    - 已有微调记录的门店菜品：不覆盖 is_available（保留门店主动下架决策）
    - 无记录的菜品：新建 store_dish_overrides，默认上架
    """
    try:
        result = await _svc(db, x_tenant_id).execute_publish_plan(plan_id)
        return {"ok": True, "data": result}
    except ValueError as exc:
        _err(400, str(exc))


# ══════════════════════════════════════════════════════
# C. 门店菜品微调
# ══════════════════════════════════════════════════════


class StoreDishOverrideReq(BaseModel):
    local_price_fen: Optional[int] = Field(
        None, ge=0, description="门店售价（分），NULL=使用品牌/方案价"
    )
    local_name: Optional[str] = Field(None, max_length=200)
    local_description: Optional[str] = None
    local_image_url: Optional[str] = Field(None, max_length=500)
    is_available: Optional[bool] = None
    sort_order: Optional[int] = None
    updated_by: Optional[str] = None


class BatchToggleReq(BaseModel):
    store_id: str
    dish_ids: list[str] = Field(..., min_length=1)
    is_available: bool
    updated_by: Optional[str] = None


@router.get("/store-dishes")
async def list_store_dishes(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取门店生效菜单（品牌菜品 + 门店微调合并后的完整列表）。"""
    try:
        items = await _svc(db, x_tenant_id).get_store_dishes(store_id)
        return {"ok": True, "data": {"store_id": store_id, "items": items, "total": len(items)}}
    except ValueError as exc:
        _err(400, str(exc))


@router.put("/store-dishes/{dish_id}/override")
async def override_store_dish(
    dish_id: str,
    req: StoreDishOverrideReq,
    store_id: str = Query(..., description="门店 ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """门店对品牌菜品进行微调（改价/改名/改图/上下架）。"""
    try:
        data = req.model_dump(exclude_none=True)
        updated_by = data.pop("updated_by", None)
        result = await _svc(db, x_tenant_id).override_store_dish(
            store_id=store_id,
            dish_id=dish_id,
            data=data,
            updated_by=updated_by,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        _err(400, str(exc))


@router.post("/store-dishes/batch-toggle")
async def batch_toggle_dishes(
    req: BatchToggleReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """批量上下架门店菜品。"""
    try:
        result = await _svc(db, x_tenant_id).batch_toggle_dishes(
            store_id=req.store_id,
            dish_ids=req.dish_ids,
            is_available=req.is_available,
            updated_by=req.updated_by,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        _err(400, str(exc))


# ══════════════════════════════════════════════════════
# D. 调价规则
# ══════════════════════════════════════════════════════


class CreatePriceRuleReq(BaseModel):
    store_id: Optional[str] = Field(None, description="NULL=品牌级规则")
    rule_name: str = Field(..., min_length=1, max_length=200)
    rule_type: str = Field(
        ...,
        pattern="^(time_period|channel|date_range|holiday)$",
    )
    channel: Optional[str] = Field(
        None,
        pattern="^(dine_in|delivery|takeout|self_order)$",
        description="NULL=所有渠道",
    )
    time_start: Optional[time] = Field(None, description="时段开始（HH:MM）")
    time_end: Optional[time] = Field(None, description="时段结束（HH:MM）")
    date_start: Optional[date] = None
    date_end: Optional[date] = None
    weekdays: Optional[list[int]] = Field(
        None, description="生效星期 [1-7]，1=周一，7=周日"
    )
    adjustment_type: str = Field(
        ..., pattern="^(percentage|fixed_add|fixed_price)$"
    )
    adjustment_value: float = Field(
        ..., description="百分比（10=+10%）/ 固定加减金额（分）/ 固定价格（分）"
    )
    priority: int = Field(0, ge=0, description="优先级，值越大越先命中")
    is_active: bool = True


class UpdatePriceRuleReq(BaseModel):
    rule_name: Optional[str] = Field(None, max_length=200)
    channel: Optional[str] = None
    time_start: Optional[time] = None
    time_end: Optional[time] = None
    date_start: Optional[date] = None
    date_end: Optional[date] = None
    weekdays: Optional[list[int]] = None
    adjustment_type: Optional[str] = None
    adjustment_value: Optional[float] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None


class BindDishesToRuleReq(BaseModel):
    dish_ids: list[str] = Field(..., min_length=1)


@router.post("/price-rules", status_code=201)
async def create_price_rule(
    req: CreatePriceRuleReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """创建调价规则（时段/渠道/日期范围/节假日）。"""
    try:
        data = req.model_dump()
        # time/date 转字符串以适配 DB
        for field in ("time_start", "time_end"):
            if data[field] is not None:
                data[field] = data[field]
        for field in ("date_start", "date_end"):
            if data[field] is not None:
                data[field] = data[field]
        rule = await _svc(db, x_tenant_id).create_price_rule(data)
        return {"ok": True, "data": rule}
    except ValueError as exc:
        _err(400, str(exc))


@router.get("/price-rules")
async def list_price_rules(
    store_id: Optional[str] = None,
    is_active: Optional[bool] = None,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """列出调价规则（?store_id=xxx 可过滤门店+品牌级规则）。"""
    rules = await _svc(db, x_tenant_id).list_price_rules(
        store_id=store_id, is_active=is_active
    )
    return {"ok": True, "data": {"rules": rules, "total": len(rules)}}


@router.put("/price-rules/{rule_id}")
async def update_price_rule(
    rule_id: str,
    req: UpdatePriceRuleReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """更新调价规则。"""
    try:
        data = {k: v for k, v in req.model_dump().items() if v is not None}
        rule = await _svc(db, x_tenant_id).update_price_rule(rule_id, data)
        return {"ok": True, "data": rule}
    except ValueError as exc:
        _err(400, str(exc))


@router.post("/price-rules/{rule_id}/dishes", status_code=201)
async def bind_dishes_to_rule(
    rule_id: str,
    req: BindDishesToRuleReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """将菜品绑定到调价规则（支持批量）。"""
    try:
        result = await _svc(db, x_tenant_id).bind_dishes_to_rule(
            rule_id=rule_id, dish_ids=req.dish_ids
        )
        return {"ok": True, "data": {"rule_id": rule_id, "bindings": result, "count": len(result)}}
    except ValueError as exc:
        _err(400, str(exc))


# ══════════════════════════════════════════════════════
# E. 生效价格查询
# ══════════════════════════════════════════════════════


@router.get("/effective-price")
async def get_effective_price(
    dish_id: str = Query(..., description="菜品 ID"),
    store_id: str = Query(..., description="门店 ID"),
    channel: str = Query(..., description="渠道: dine_in|delivery|takeout|self_order"),
    at_datetime: Optional[str] = Query(
        None,
        description="查询时间点（ISO 格式，默认当前时间）",
    ),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """查询某菜品在指定门店/渠道/时间的生效价格。

    价格优先级（从高到低）：
      1. 门店调价规则（时段/渠道/日期，取最高优先级命中规则）
      2. 门店覆盖价（store_dish_overrides.local_price_fen）
      3. 发布方案覆盖价（最新已发布方案的 override_price_fen）
      4. 品牌标准价（dishes.price_fen）
    """
    try:
        parsed_dt: Optional[datetime] = None
        if at_datetime:
            parsed_dt = datetime.fromisoformat(at_datetime)

        result = await _svc(db, x_tenant_id).get_effective_price(
            dish_id=dish_id,
            store_id=store_id,
            channel=channel,
            at_datetime=parsed_dt,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        _err(400, str(exc))
