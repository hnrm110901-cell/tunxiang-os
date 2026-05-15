"""dept_whitelist_routes — 部门用料白名单 API（PRD-08 / Phase 2 W11 / T2 + Tier 1 邻接）

接口列表:
  CRUD:
    POST   /api/v1/supply/dept-whitelists                          新建白名单
    GET    /api/v1/supply/dept-whitelists                          列表 (?dept_id=&only_active=)
    GET    /api/v1/supply/dept-whitelists/{whitelist_id}           单条
    PATCH  /api/v1/supply/dept-whitelists/{whitelist_id}           更新
    DELETE /api/v1/supply/dept-whitelists/{whitelist_id}           软删

  矩阵编辑器:
    POST   /api/v1/supply/dept-whitelists/bulk-authorize           一次性给部门授权多食材 (upsert)

  校验入口（前端预校验 + 外部 service 调用入口）:
    POST   /api/v1/supply/dept-whitelists/validate                 校验某部门是否可领某食材

设计要点：
  - IngredientNotAllowedError → 403 Forbidden（合规层面）
  - ValueError("已存在") → 409 Conflict（重复白名单）
  - ValueError("不存在") → 404 Not Found
  - 其他 ValueError → 422 Unprocessable Entity
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db as _get_db

from ..models.dept_whitelist_models import (
    BulkAuthorizeRequest,
    IngredientNotAllowedError,
    ValidateRequest,
    WhitelistCreate,
    WhitelistUpdate,
)
from ..services.dept_whitelist_service import (
    bulk_authorize,
    create_whitelist,
    delete_whitelist,
    get_whitelist,
    list_whitelists,
    update_whitelist,
    validate_ingredient_allowed,
)

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/supply/dept-whitelists",
    tags=["dept-whitelists"],
)


# ─── CRUD ────────────────────────────────────────────────────────────────────


@router.post("")
async def create_supply_dept_whitelist(
    body: WhitelistCreate,
    x_user_id: str = Header(..., alias="X-User-ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """新建白名单 (tenant_id, dept_id, ingredient_id) 唯一。

    业务场景：食安总监 / 采购总监授权早餐档可领"肉包/豆浆"等基础食材。
    """
    try:
        item = await create_whitelist(
            db=db,
            tenant_id=x_tenant_id,
            dept_id=str(body.dept_id),
            ingredient_id=str(body.ingredient_id),
            created_by=x_user_id,
            max_qty_per_day=body.max_qty_per_day,
            notes=body.notes,
        )
    except ValueError as e:
        msg = str(e)
        if "已存在" in msg:
            raise HTTPException(
                status_code=409,
                detail={"code": "WHITELIST_DUPLICATE", "message": msg},
            ) from e
        raise HTTPException(
            status_code=422,
            detail={"code": "WHITELIST_CREATE_INVALID", "message": msg},
        ) from e
    return {"ok": True, "data": item}


@router.get("")
async def list_supply_dept_whitelists(
    dept_id: str | None = Query(default=None),
    only_active: bool = Query(default=True),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """白名单列表 — created_at 倒序; dept_id / only_active 过滤。"""
    try:
        items = await list_whitelists(
            db=db,
            tenant_id=x_tenant_id,
            dept_id=dept_id,
            only_active=only_active,
            limit=limit,
            offset=offset,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail={"code": "WHITELIST_LIST_INVALID", "message": str(e)},
        ) from e
    return {"ok": True, "data": items}


@router.get("/{whitelist_id}")
async def get_supply_dept_whitelist(
    whitelist_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """单条白名单详情。"""
    item = await get_whitelist(db=db, tenant_id=x_tenant_id, whitelist_id=whitelist_id)
    if item is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "WHITELIST_NOT_FOUND",
                "message": f"whitelist_id={whitelist_id} 不存在或已删除",
            },
        )
    return {"ok": True, "data": item}


@router.patch("/{whitelist_id}")
async def update_supply_dept_whitelist(
    whitelist_id: str,
    body: WhitelistUpdate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """更新白名单。max_qty_per_day / is_active / notes 任一字段。

    §19 round-1 P0-1 fix: body.model_dump(exclude_unset=True) 区分"未提供"
    vs "显式 None" — 让 max_qty_per_day 能被 PATCH 回 NULL (不限量),
    is_active=FALSE 也能被显式禁用. JSON body 中字段不出现 → 不动;
    出现 (含 null) → 写入.
    """
    updates = body.model_dump(exclude_unset=True)
    try:
        item = await update_whitelist(
            db=db,
            tenant_id=x_tenant_id,
            whitelist_id=whitelist_id,
            updates=updates,
        )
    except ValueError as e:
        msg = str(e)
        if "不存在" in msg:
            raise HTTPException(
                status_code=404,
                detail={"code": "WHITELIST_NOT_FOUND", "message": msg},
            ) from e
        raise HTTPException(
            status_code=422,
            detail={"code": "WHITELIST_UPDATE_INVALID", "message": msg},
        ) from e
    return {"ok": True, "data": item}


@router.delete("/{whitelist_id}")
async def delete_supply_dept_whitelist(
    whitelist_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """软删白名单（is_deleted=TRUE + is_active=FALSE）。"""
    ok = await delete_whitelist(db=db, tenant_id=x_tenant_id, whitelist_id=whitelist_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "WHITELIST_NOT_FOUND",
                "message": f"whitelist_id={whitelist_id} 不存在或已删除",
            },
        )
    return {"ok": True, "data": {"deleted": True, "whitelist_id": whitelist_id}}


# ─── 矩阵编辑器 ─────────────────────────────────────────────────────────────


@router.post("/bulk-authorize")
async def bulk_authorize_supply_dept_whitelist(
    body: BulkAuthorizeRequest,
    x_user_id: str = Header(..., alias="X-User-ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """一个部门一次性授权多食材（矩阵编辑器场景）。

    业务场景：食安总监打开"部门-食材矩阵编辑器"，选择"早餐档"行 → 勾选 10
    种允许食材（含限额）→ 一键提交。已存在的 (dept_id, ingredient_id)
    upsert（恢复 is_active + 更新 max_qty_per_day）；不存在的 INSERT 新行。
    """
    # §19 round-1 P1-1 fix: per-item model_dump(exclude_unset=True) 区分"未提供"
    # vs "显式 None" — caller 未在 JSON body 里写 max_qty_per_day 字段时不擦原限额.
    items_dump: list[dict] = []
    for it in body.items:
        item_dict: dict = {"ingredient_id": str(it.ingredient_id)}
        provided = it.model_dump(exclude_unset=True)
        if "max_qty_per_day" in provided:
            item_dict["max_qty_per_day"] = it.max_qty_per_day
        if "notes" in provided:
            item_dict["notes"] = it.notes
        items_dump.append(item_dict)
    try:
        result = await bulk_authorize(
            db=db,
            tenant_id=x_tenant_id,
            dept_id=str(body.dept_id),
            items=items_dump,
            created_by=x_user_id,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail={"code": "WHITELIST_BULK_AUTHORIZE_INVALID", "message": str(e)},
        ) from e
    return {"ok": True, "data": result}


# ─── 校验入口 ────────────────────────────────────────────────────────────────


@router.post("/validate")
async def validate_supply_dept_whitelist(
    body: ValidateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """校验某部门是否可领某食材。

    业务场景：前端在用户提交领料前调本接口预校验，UI 显示绿勾 / 红叉。
    实际硬阻塞由 dept_issue.create_issue_order 在服务端最终把关。

    设计：raise_on_violation=False — 返回 {allowed, reason} 而非抛错（路由层
    不抛 403, 由前端按 allowed=False 显示阻塞理由）。
    """
    try:
        result = await validate_ingredient_allowed(
            db=db,
            tenant_id=x_tenant_id,
            dept_id=str(body.dept_id),
            ingredient_id=str(body.ingredient_id),
            qty=body.qty,
            raise_on_violation=False,
        )
    except IngredientNotAllowedError as e:
        # 兜底：raise_on_violation=False 路径不应抛此异常，但防御性处理
        raise HTTPException(
            status_code=403,
            detail={"code": "INGREDIENT_NOT_ALLOWED", "message": e.message},
        ) from e
    return {"ok": True, "data": result}


__all__ = ["router"]
