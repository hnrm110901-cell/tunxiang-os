"""过敏原管理 API 路由

GET  /api/v1/allergens/codes
     返回所有支持的过敏原代码和中文标签

POST /api/v1/allergens/check
     body: { dish_ids: list[str], member_id: str, dish_names?: dict[str,str] }
     检查菜品列表对该会员是否有过敏风险
     返回：[{ dish_id, dish_name, alerts: [{allergen_code, allergen_label, severity}] }]

POST /api/v1/dishes/{dish_id}/allergens
     body: { allergen_codes: list[str] }
     设置菜品过敏原（需管理员权限）

GET  /api/v1/dishes/{dish_id}/allergens
     获取菜品过敏原列表

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.allergen_service import AllergenService

router = APIRouter(tags=["allergens"])


# ──────────────────────────────────────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(message: str, code: str = "ALLERGEN_ERROR") -> dict:
    return {"ok": False, "data": None, "error": {"code": code, "message": message}}


# ──────────────────────────────────────────────────────────────────────────────
# 请求模型
# ──────────────────────────────────────────────────────────────────────────────


class CheckAllergensReq(BaseModel):
    dish_ids: list[str]
    member_id: str
    dish_names: Optional[dict[str, str]] = None  # {dish_id: dish_name}，前端可选传入


class SetDishAllergensReq(BaseModel):
    allergen_codes: list[str]


# ──────────────────────────────────────────────────────────────────────────────
# 路由
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/api/v1/allergens/codes")
async def get_allergen_codes(request: Request):
    """GET /api/v1/allergens/codes — 返回所有支持的过敏原代码和中文标签"""
    _get_tenant_id(request)  # 仍需校验 tenant header
    summary = AllergenService.get_allergen_summary()
    return _ok(summary)


@router.post("/api/v1/allergens/check")
async def check_allergens(
    body: CheckAllergensReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """POST /api/v1/allergens/check — 批量检查菜品对会员的过敏风险

    Request body:
        dish_ids:   菜品 ID 列表
        member_id:  会员 ID
        dish_names: 可选，{dish_id: dish_name}，不传则以 dish_id 作为显示名

    Response data: [{dish_id, dish_name, alerts: [{allergen_code, allergen_label, severity}]}]
    仅返回有预警的菜品。
    """
    tenant_id = _get_tenant_id(request)

    if not body.dish_ids:
        return _ok([])

    svc = AllergenService(db, tenant_id)
    dish_names = body.dish_names or {}

    try:
        results = await svc.check_dishes_for_member(
            dish_ids=body.dish_ids,
            dish_names=dish_names,
            member_id=body.member_id,
        )
        return _ok(results)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="数据库查询失败") from exc


@router.post("/api/v1/dishes/{dish_id}/allergens")
async def set_dish_allergens(
    dish_id: str,
    body: SetDishAllergensReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """POST /api/v1/dishes/{dish_id}/allergens — 设置菜品过敏原（全量替换）

    需要管理员或 owner 权限（调用方通过 middleware 验证，此层不重复校验）。
    """
    tenant_id = _get_tenant_id(request)
    svc = AllergenService(db, tenant_id)

    try:
        result = await svc.set_dish_allergens(
            dish_id=dish_id,
            allergen_codes=body.allergen_codes,
        )
        return _ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="数据库写入失败") from exc


@router.get("/api/v1/dishes/{dish_id}/allergens")
async def get_dish_allergens(
    dish_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """GET /api/v1/dishes/{dish_id}/allergens — 获取菜品过敏原列表"""
    tenant_id = _get_tenant_id(request)
    svc = AllergenService(db, tenant_id)

    try:
        items = await svc.get_dish_allergens(dish_id=dish_id)
        return _ok({"dish_id": dish_id, "items": items, "total": len(items)})
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="数据库查询失败") from exc
