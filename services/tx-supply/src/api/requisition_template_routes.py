"""requisition_template_routes — 申购模板 API（PRD-07 / Phase 2 W10 / T2）

接口列表:
  Templates:
    POST   /api/v1/supply/requisition-templates                   创建模板（含明细）
    GET    /api/v1/supply/requisition-templates                   列表 (?category=&only_active=)
    GET    /api/v1/supply/requisition-templates/{template_id}     单条详情 (含明细)
    PATCH  /api/v1/supply/requisition-templates/{template_id}     更新（不改 items）
    DELETE /api/v1/supply/requisition-templates/{template_id}     软删

  Warehouse bindings:
    POST   /api/v1/supply/requisition-templates/{template_id}/bindings  仓库绑定
    GET    /api/v1/supply/requisition-templates/warehouses/{warehouse_id}/bindings  按仓库查绑定
    DELETE /api/v1/supply/requisition-templates/bindings/{binding_id}   解除绑定

  一键发起申购:
    POST   /api/v1/supply/requisition-templates/{template_id}/generate  生成草稿 (含 AI 推荐量)

设计要点：
  - 一键发起返回 GeneratedRequisitionDraft 草稿（不入库），前端 review 后调 existing
    /api/v1/supply/requisitions 入库走审批流（services/tx-supply/src/services/requisition.py）
  - AI 推荐量复用 SmartReplenishmentService（fail-open 不阻塞模板生成）
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db as _get_db

from ..models.requisition_template_models import (
    BindingCreate,
    GenerateFromTemplateRequest,
    TemplateCategory,
    TemplateCreate,
    TemplateUpdate,
)
from ..services.requisition_template_service import (
    create_binding,
    create_template,
    delete_binding,
    delete_template,
    generate_from_template,
    get_template,
    list_bindings_for_warehouse,
    list_templates,
    update_template,
)

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/supply/requisition-templates",
    tags=["requisition-templates"],
)


# ─── Templates CRUD ──────────────────────────────────────────────────────────


@router.post("")
async def create_supply_requisition_template(
    body: TemplateCreate,
    x_user_id: str = Header(..., alias="X-User-ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """创建申购模板（同事务原子写 requisition_templates + requisition_template_items）。

    业务场景：总部采购总监为门店预设"海鲜/蔬菜/调料/酒水"标准模板, 80% SKU 不变。
    """
    try:
        item = await create_template(
            db=db,
            tenant_id=x_tenant_id,
            name=body.name,
            category=body.category.value,
            items=[
                {
                    "ingredient_id": str(it.ingredient_id),
                    "default_qty": it.default_qty,
                    "qty_method": it.qty_method.value,
                    "qty_unit": it.qty_unit,
                    "sort_order": it.sort_order,
                    "notes": it.notes,
                }
                for it in body.items
            ],
            created_by=x_user_id,
            notes=body.notes,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail={"code": "TEMPLATE_CREATE_VALIDATION", "message": str(e)},
        ) from e
    return {"ok": True, "data": item}


@router.get("")
async def list_supply_requisition_templates(
    category: TemplateCategory | None = Query(default=None),
    only_active: bool = Query(default=True),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """模板列表 — created_at 倒序; category / only_active 过滤。"""
    try:
        items = await list_templates(
            db=db,
            tenant_id=x_tenant_id,
            category=category.value if category else None,
            only_active=only_active,
            limit=limit,
            offset=offset,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail={"code": "TEMPLATE_LIST_INVALID", "message": str(e)},
        ) from e
    return {"ok": True, "data": items}


@router.get("/{template_id}")
async def get_supply_requisition_template(
    template_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """单条模板详情（含明细 items）。"""
    item = await get_template(db=db, tenant_id=x_tenant_id, template_id=template_id)
    if item is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "TEMPLATE_NOT_FOUND",
                "message": f"template_id={template_id} 不存在或已删除",
            },
        )
    return {"ok": True, "data": item}


@router.patch("/{template_id}")
async def update_supply_requisition_template(
    template_id: str,
    body: TemplateUpdate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """更新模板基本信息（不改 items）。"""
    try:
        item = await update_template(
            db=db,
            tenant_id=x_tenant_id,
            template_id=template_id,
            name=body.name,
            category=body.category.value if body.category else None,
            is_active=body.is_active,
            notes=body.notes,
        )
    except ValueError as e:
        msg = str(e)
        if "不存在" in msg:
            raise HTTPException(
                status_code=404,
                detail={"code": "TEMPLATE_NOT_FOUND", "message": msg},
            ) from e
        raise HTTPException(
            status_code=422,
            detail={"code": "TEMPLATE_UPDATE_INVALID", "message": msg},
        ) from e
    return {"ok": True, "data": item}


@router.delete("/{template_id}")
async def delete_supply_requisition_template(
    template_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """软删模板（is_deleted=TRUE + is_active=FALSE）。"""
    ok = await delete_template(db=db, tenant_id=x_tenant_id, template_id=template_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "TEMPLATE_NOT_FOUND",
                "message": f"template_id={template_id} 不存在或已删除",
            },
        )
    return {"ok": True, "data": {"deleted": True, "template_id": template_id}}


# ─── Warehouse bindings ──────────────────────────────────────────────────────


@router.post("/{template_id}/bindings")
async def create_supply_requisition_template_binding(
    template_id: str,
    body: BindingCreate,
    x_user_id: str = Header(..., alias="X-User-ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """绑定模板到仓库。UNIQUE(warehouse_id, template_id) 防重绑。

    body.template_id 必须与 path template_id 一致（路由层校验）。
    """
    if str(body.template_id) != template_id:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "BINDING_TEMPLATE_MISMATCH",
                "message": f"body.template_id={body.template_id} 与 path={template_id} 不一致",
            },
        )
    try:
        item = await create_binding(
            db=db,
            tenant_id=x_tenant_id,
            warehouse_id=str(body.warehouse_id),
            template_id=template_id,
            created_by=x_user_id,
            auto_trigger_cron=body.auto_trigger_cron,
            priority=body.priority,
        )
    except ValueError as e:
        msg = str(e)
        if "不存在" in msg:
            raise HTTPException(
                status_code=404,
                detail={"code": "TEMPLATE_NOT_FOUND", "message": msg},
            ) from e
        # §19 round-1 P1-1: 重复绑定 → 409 Conflict (IntegrityError 由 service 转 ValueError)
        if "重复绑定" in msg:
            raise HTTPException(
                status_code=409,
                detail={"code": "BINDING_DUPLICATE", "message": msg},
            ) from e
        raise HTTPException(
            status_code=422,
            detail={"code": "BINDING_CREATE_INVALID", "message": msg},
        ) from e
    return {"ok": True, "data": item}


@router.get("/warehouses/{warehouse_id}/bindings")
async def list_supply_warehouse_bindings(
    warehouse_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """按仓库查绑定（含模板基本信息 JOIN）— priority 升序。"""
    items = await list_bindings_for_warehouse(
        db=db, tenant_id=x_tenant_id, warehouse_id=warehouse_id
    )
    return {"ok": True, "data": items}


@router.delete("/bindings/{binding_id}")
async def delete_supply_requisition_template_binding(
    binding_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """解除仓库绑定（软删）。"""
    ok = await delete_binding(db=db, tenant_id=x_tenant_id, binding_id=binding_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "BINDING_NOT_FOUND",
                "message": f"binding_id={binding_id} 不存在或已删除",
            },
        )
    return {"ok": True, "data": {"deleted": True, "binding_id": binding_id}}


# ─── 一键发起申购 ───────────────────────────────────────────────────────────


@router.post("/{template_id}/generate")
async def generate_supply_requisition_from_template(
    template_id: str,
    body: GenerateFromTemplateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """一键基于模板生成申购单草稿。

    业务场景：门店店长在 RequisitionTemplatesPage 上点【一键发起申购】 → 选 store_id
    → 后端调本接口 → 返回 GeneratedRequisitionDraft（含 AI 推荐量）→ 前端 review
    后调 existing /api/v1/supply/requisitions 入库走审批流。

    AI 推荐失败 fail-open（item.suggested_qty=None + qty_source 标注原因），不阻塞草稿生成。
    """
    try:
        item = await generate_from_template(
            db=db,
            tenant_id=x_tenant_id,
            template_id=template_id,
            store_id=str(body.store_id) if body.store_id else None,
            notes=body.notes,
        )
    except ValueError as e:
        msg = str(e)
        if "不存在" in msg:
            raise HTTPException(
                status_code=404,
                detail={"code": "TEMPLATE_NOT_FOUND", "message": msg},
            ) from e
        if "禁用" in msg:
            raise HTTPException(
                status_code=409,
                detail={"code": "TEMPLATE_INACTIVE", "message": msg},
            ) from e
        raise HTTPException(
            status_code=422,
            detail={"code": "TEMPLATE_GENERATE_INVALID", "message": msg},
        ) from e
    return {"ok": True, "data": item}


__all__ = ["router"]
