"""中央厨房 API 路由

生产计划->加工任务->配送路由->门店签收
供应链模块核心功能：生产计划→工单→配送→门店收货确认 完整链路。

路由前缀：/api/v1/supply/central-kitchen
认证头：X-Tenant-ID（所有接口必填）

端点列表：
  GET  /kitchens                            中央厨房列表
  POST /kitchens                            新建中央厨房档案
  GET  /kitchens/{id}/dashboard            中央厨房看板（path-param 版）

  GET  /plans                              生产计划列表
  POST /plans                              创建生产计划
  GET  /plans/{id}                         计划详情
  POST /plans/{id}/confirm                 确认计划，生成工单
  PUT  /plans/{id}/start                   开始生产（confirmed→in_progress）
  POST /plans/{id}/distribute              从计划批量创建多门店配送单

  PUT  /orders/{id}/complete               完成生产工单（记录实际产量）
  GET  /production-orders                  生产工单列表
  PUT  /production-orders/{id}/progress    更新工单进度（通用版）

  GET  /distribution                       配送单列表
  POST /distribution                       创建配送单
  POST /distribution/{id}/deliver         标记已发出
  POST /distribution/{id}/receive         门店确认收货（POST 版）
  PUT  /distribution/{id}/confirm         门店确认收货（PUT 版，RESTful 语义）

  GET  /dashboard                          日看板（query-param 版）
  GET  /demand-forecast                    需求预测
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from shared.ontology.src.database import get_db

log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/supply/central-kitchen",
    tags=["central_kitchen"],
)


# ─── 请求体模型（Pydantic V2）───────────────────────────────────────────────


class CreateKitchenRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="中央厨房名称")
    address: Optional[str] = Field(None, max_length=255, description="地址")
    capacity_daily: float = Field(0.0, ge=0, description="日产能（份/公斤，视菜品单位）")
    manager_id: Optional[str] = Field(None, description="负责人员工 ID")
    contact_phone: Optional[str] = Field(None, max_length=20, description="联系电话")


class PlanItemInput(BaseModel):
    dish_id: str = Field(..., description="菜品 ID")
    dish_name: str = Field(..., min_length=1, description="菜品名称")
    quantity: float = Field(..., gt=0, description="计划产量")
    unit: str = Field("份", description="单位")
    target_stores: List[str] = Field(default_factory=list, description="目标门店 ID 列表")


class CreateProductionPlanRequest(BaseModel):
    kitchen_id: str = Field(..., description="中央厨房 ID")
    plan_date: str = Field(..., description="生产日期 YYYY-MM-DD")
    items: List[PlanItemInput] = Field(
        default_factory=list,
        description="生产菜品清单，留空则自动从需求预测生成",
    )
    created_by: Optional[str] = Field(None, description="创建人员工 ID")


class ConfirmPlanRequest(BaseModel):
    operator_id: str = Field(..., description="确认操作人员工 ID")


class UpdateProgressRequest(BaseModel):
    status: str = Field(
        ...,
        description="新状态：in_progress / completed / cancelled",
    )
    quantity_done: Optional[float] = Field(
        None,
        ge=0,
        description="已完成数量（status=completed 时必填）",
    )


# ─── DB 依赖占位（由 main.py 覆盖） ───


async def _get_db():
    """数据库会话依赖 — 由 main.py 覆盖"""
    raise NotImplementedError("DB session dependency not configured")


# ─── 请求模型 ───
class DistributionItemInput(BaseModel):
    dish_id: str = Field(..., description="菜品 ID")
    dish_name: str = Field(..., min_length=1, description="菜品名称")
    quantity: float = Field(..., gt=0, description="配送数量")
    unit: str = Field("份", description="单位")


class CreateDistributionOrderRequest(BaseModel):
    kitchen_id: str = Field(..., description="中央厨房 ID")
    target_store_id: str = Field(..., description="目标门店 ID")
    items: List[DistributionItemInput] = Field(..., min_length=1, description="配送明细")
    scheduled_at: str = Field(..., description="计划配送时间（ISO 8601）")
    driver_name: Optional[str] = Field(None, max_length=50, description="司机姓名")
    driver_phone: Optional[str] = Field(None, max_length=20, description="司机电话")


class ReceivingItemInput(BaseModel):
    dish_id: str = Field(..., description="菜品 ID")
    dish_name: str = Field(..., description="菜品名称")
    received_qty: float = Field(..., ge=0, description="实收数量")
    unit: str = Field("份", description="单位")
    variance_notes: Optional[str] = Field(None, description="差异备注")


class StoreReceivingRequest(BaseModel):
    store_id: str = Field(..., description="收货门店 ID")
    confirmed_by: str = Field(..., description="确认人员工 ID")
    items: List[ReceivingItemInput] = Field(..., min_length=1, description="实收明细")
    notes: Optional[str] = Field(None, description="整单备注")


class StoreAssignmentInput(BaseModel):
    """计划维度配送分配：一个门店分配一批菜品"""
    store_id: str = Field(..., description="目标门店 ID")
    items: List[DistributionItemInput] = Field(..., min_length=1, description="该门店配送明细")
    scheduled_at: str = Field(..., description="计划配送时间（ISO 8601）")
    driver_name: Optional[str] = Field(None, max_length=50, description="司机姓名")
    driver_phone: Optional[str] = Field(None, max_length=20, description="司机电话")


class PlanDistributeRequest(BaseModel):
    """从生产计划创建多门店配送单"""
    store_assignments: List[StoreAssignmentInput] = Field(
        ..., min_length=1, description="各门店配送分配"
    )


# ─── 厨房档案 ──────────────────────────────────────────────────────────────


@router.get("/kitchens", summary="中央厨房列表")
async def list_kitchens(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """返回当前租户的所有中央厨房档案。"""
    from ..services.central_kitchen_service import CentralKitchenService

    svc = CentralKitchenService(db, x_tenant_id)
    try:
        kitchens = await svc.list_kitchens()
        return {"ok": True, "data": {"items": [k.model_dump() for k in kitchens]}}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/kitchens", summary="新建中央厨房档案", status_code=201)
async def create_kitchen(
    body: CreateKitchenRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """创建中央厨房档案（名称/地址/日产能/负责人/联系电话）。"""
    from ..services.central_kitchen_service import CentralKitchenService

    svc = CentralKitchenService(db, x_tenant_id)
    try:
        kitchen = await svc.create_kitchen(
            name=body.name,
            address=body.address,
            capacity_daily=body.capacity_daily,
            manager_id=body.manager_id,
            contact_phone=body.contact_phone,
        )
        await db.commit()
        return {"ok": True, "data": kitchen.model_dump()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ─── 生产计划 ──────────────────────────────────────────────────────────────


@router.get("/plans", summary="生产计划列表")
async def list_production_plans(
    kitchen_id: Optional[str] = Query(None, description="按厨房过滤"),
    plan_date: Optional[str] = Query(None, description="按日期过滤 YYYY-MM-DD"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """查询生产计划列表，支持按厨房/日期/状态过滤。"""
    from ..services.central_kitchen_service import CentralKitchenService

    svc = CentralKitchenService(db, x_tenant_id)
    try:
        result = await svc.list_production_plans(
            kitchen_id=kitchen_id,
            plan_date=plan_date,
            status=status,
            page=page,
            size=size,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/plans", summary="创建生产计划", status_code=201)
async def create_production_plan(
    body: CreateProductionPlanRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """创建生产计划草稿。

    - items 留空时自动从需求预测（近30天历史均值）生成菜品建议量
    - 周末目标日期自动 ×1.3 权重
    """
    from ..services.central_kitchen_service import CentralKitchenService

    svc = CentralKitchenService(db, x_tenant_id)
    try:
        items_raw = [i.model_dump() for i in body.items]
        plan = await svc.create_production_plan(
            kitchen_id=body.kitchen_id,
            plan_date=body.plan_date,
            tenant_id=x_tenant_id,
            store_ids=body.store_ids,
            db=db,
            items=items_raw,
            created_by=body.created_by,
        )
        await db.commit()
        return {"ok": True, "data": plan.model_dump()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/plans/{plan_id}", summary="生产计划详情")
async def get_production_plan(
    plan_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """查询单个生产计划详情（含菜品清单）。"""
    from ..services.central_kitchen_service import CentralKitchenService

    svc = CentralKitchenService(db, x_tenant_id)
    try:
        plan = await svc.get_production_plan(plan_id=plan_id)
        return {"ok": True, "data": plan.model_dump()}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/plans/{plan_id}/confirm", summary="确认生产计划")
async def confirm_production_plan(
    plan_id: str,
    body: ConfirmPlanRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """确认草稿生产计划，自动为每个菜品生成独立生产工单。"""
    from ..services.central_kitchen_service import CentralKitchenService

    svc = CentralKitchenService(db, x_tenant_id)
    try:
        plan = await svc.confirm_production_plan(
            plan_id=plan_id,
            operator_id=body.operator_id,
        )
        await db.commit()
        return {"ok": True, "data": plan.model_dump()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/plans/{plan_id}/start", summary="开始生产")
async def start_production(
    plan_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """开始生产：将已确认计划状态更新为 in_progress，所有 pending 工单同步开始。

    状态机：confirmed → in_progress
    """
    from ..services.central_kitchen_service import CentralKitchenService

    svc = CentralKitchenService(db, x_tenant_id)
    try:
        plan = await svc.start_production(plan_id=plan_id)
        await db.commit()
        return {"ok": True, "data": plan.model_dump()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ─── 生产工单 ──────────────────────────────────────────────────────────────


@router.get("/production-orders", summary="生产工单列表")
async def list_production_orders(
    kitchen_id: Optional[str] = Query(None, description="按厨房过滤"),
    plan_id: Optional[str] = Query(None, description="按计划过滤"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """查询生产工单列表，支持按厨房/计划/状态过滤。"""
    from ..services.central_kitchen_service import CentralKitchenService

    svc = CentralKitchenService(db, x_tenant_id)
    try:
        result = await svc.list_production_orders(
            kitchen_id=kitchen_id,
            plan_id=plan_id,
            status=status,
            page=page,
            size=size,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/orders/{order_id}/complete", summary="完成生产工单")
async def complete_production_order(
    order_id: str,
    actual_qty: float = Query(..., ge=0, description="实际产量"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """完成单个生产工单，记录实际产量。

    若计划内所有工单均完成，计划自动升为 completed。
    """
    from ..services.central_kitchen_service import CentralKitchenService

    svc = CentralKitchenService(db, x_tenant_id)
    try:
        order = await svc.complete_production_order(
            order_id=order_id,
            actual_qty=actual_qty,
        )
        await db.commit()
        return {"ok": True, "data": order.model_dump()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put(
    "/production-orders/{order_id}/progress",
    summary="更新生产工单进度",
)
async def update_production_progress(
    order_id: str,
    body: UpdateProgressRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """更新工单状态（pending→in_progress→completed / cancelled）。

    completed 状态须同时提供 quantity_done。
    """
    from ..services.central_kitchen_service import CentralKitchenService

    svc = CentralKitchenService(db, x_tenant_id)
    try:
        order = await svc.update_production_progress(
            order_id=order_id,
            status=body.status,
            quantity_done=body.quantity_done,
        )
        await db.commit()
        return {"ok": True, "data": order.model_dump()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ─── 配送单 ────────────────────────────────────────────────────────────────


@router.get("/distribution", summary="配送单列表")
async def list_distribution_orders(
    kitchen_id: Optional[str] = Query(None, description="按厨房过滤"),
    store_id: Optional[str] = Query(None, description="按目标门店过滤"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """查询配送单列表，支持按厨房/门店/状态过滤。"""
    from ..services.central_kitchen_service import CentralKitchenService

    svc = CentralKitchenService(db, x_tenant_id)
    try:
        result = await svc.list_distribution_orders(
            kitchen_id=kitchen_id,
            store_id=store_id,
            status=status,
            page=page,
            size=size,
        )
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/distribution", summary="创建配送单", status_code=201)
async def create_distribution_order(
    body: CreateDistributionOrderRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """创建从中央厨房到门店的配送单。"""
    from ..services.central_kitchen_service import CentralKitchenService

    svc = CentralKitchenService(db, x_tenant_id)
    try:
        items_raw = [i.model_dump() for i in body.items]
        order = await svc.create_distribution_order(
            kitchen_id=body.kitchen_id,
            store_id=body.target_store_id,
            items=items_raw,
            scheduled_at=body.scheduled_at,
            driver_name=body.driver_name,
            driver_phone=body.driver_phone,
        )
        await db.commit()
        return {"ok": True, "data": order.model_dump()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/distribution/{order_id}/deliver", summary="标记配送单已发出")
async def mark_distribution_dispatched(
    order_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """将配送单状态从 pending 更新为 dispatched（货已出库发车）。"""
    from ..services.central_kitchen_service import CentralKitchenService

    svc = CentralKitchenService(db, x_tenant_id)
    try:
        order = await svc.mark_dispatched(order_id=order_id)
        await db.commit()
        return {"ok": True, "data": order.model_dump()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/distribution/{order_id}/receive", summary="门店确认收货")
async def store_receive(
    order_id: str,
    body: StoreReceivingRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """门店确认收货，记录实收数量，差异 >5% 自动生成差异备注。"""
    from ..services.central_kitchen_service import CentralKitchenService

    svc = CentralKitchenService(db, x_tenant_id)
    try:
        items_raw = [i.model_dump() for i in body.items]
        confirmation = await svc.confirm_store_receiving(
            distribution_order_id=order_id,
            store_id=body.store_id,
            confirmed_by=body.confirmed_by,
            items=items_raw,
            notes=body.notes,
        )
        await db.commit()
        return {"ok": True, "data": confirmation.model_dump()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/distribution/{order_id}/confirm", summary="门店确认收货（PUT 别名）")
async def store_receive_confirm(
    order_id: str,
    body: StoreReceivingRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """门店确认收货 PUT 版本（与 POST /receive 功能相同，语义更符合 REST 规范）。

    差异 >5% 自动生成 variance_notes。
    """
    from ..services.central_kitchen_service import CentralKitchenService

    svc = CentralKitchenService(db, x_tenant_id)
    try:
        items_raw = [i.model_dump() for i in body.items]
        confirmation = await svc.confirm_store_receiving(
            distribution_order_id=order_id,
            store_id=body.store_id,
            confirmed_by=body.confirmed_by,
            items=items_raw,
            notes=body.notes,
        )
        await db.commit()
        return {"ok": True, "data": confirmation.model_dump()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/plans/{plan_id}/distribute", summary="从生产计划创建多门店配送单", status_code=201)
async def plan_distribute(
    plan_id: str,
    body: PlanDistributeRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """从已确认/进行中的生产计划批量创建各门店配送单。

    每个 store_assignment 对应一张独立配送单，返回所有创建的配送单列表。
    """
    from ..services.central_kitchen_service import CentralKitchenService

    svc = CentralKitchenService(db, x_tenant_id)
    try:
        # 先校验计划存在且属于当前租户
        plan = await svc.get_production_plan(plan_id=plan_id)
        if plan.status not in ("confirmed", "in_progress"):
            raise ValueError(
                f"计划状态为 {plan.status}，只有 confirmed 或 in_progress 状态可创建配送单"
            )

        created_orders = []
        for assignment in body.store_assignments:
            items_raw = [i.model_dump() for i in assignment.items]
            order = await svc.create_distribution_order(
                kitchen_id=plan.kitchen_id,
                store_id=assignment.store_id,
                items=items_raw,
                scheduled_at=assignment.scheduled_at,
                driver_name=assignment.driver_name,
                driver_phone=assignment.driver_phone,
            )
            created_orders.append(order.model_dump())

        await db.commit()
        return {"ok": True, "data": {"items": created_orders, "total": len(created_orders)}}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ─── 看板与预测 ────────────────────────────────────────────────────────────


@router.get("/dashboard", summary="中央厨房日看板")
async def get_daily_dashboard(
    kitchen_id: str = Query(..., description="中央厨房 ID"),
    date: str = Query(..., description="日期 YYYY-MM-DD"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """日看板：当日生产计划总数/工单状态分布/配送单状态分布。"""
    from ..services.central_kitchen_service import CentralKitchenService

    svc = CentralKitchenService(db, x_tenant_id)
    try:
        dashboard = await svc.get_daily_dashboard(kitchen_id=kitchen_id, date=date)
        return {"ok": True, "data": dashboard.model_dump()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/demand-forecast", summary="需求预测")
async def demand_forecast(
    kitchen_id: str = Query(..., description="中央厨房 ID"),
    target_date: str = Query(..., description="预测日期 YYYY-MM-DD"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """基于近30天历史消耗预测各菜品需求量（周末×1.3）。"""
    from ..services.central_kitchen_service import CentralKitchenService

    svc = CentralKitchenService(db, x_tenant_id)
    try:
        forecast = await svc.forecast_demand(kitchen_id=kitchen_id, target_date=target_date)
        return {"ok": True, "data": forecast.model_dump()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/kitchens/{kitchen_id}/dashboard", summary="中央厨房看板（path-param 版）")
async def get_kitchen_dashboard(
    kitchen_id: str,
    date: str = Query(..., description="日期 YYYY-MM-DD"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """通过路径参数指定厨房 ID 的日看板。

    返回：今日计划数/工单状态汇总/配送单状态汇总。
    """
    from ..services.central_kitchen_service import CentralKitchenService

    svc = CentralKitchenService(db, x_tenant_id)
    try:
        dashboard = await svc.get_daily_dashboard(kitchen_id=kitchen_id, date=date)
        return {"ok": True, "data": dashboard.model_dump()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
