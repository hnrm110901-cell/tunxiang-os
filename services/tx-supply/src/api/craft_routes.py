"""BOM 工艺管理 API 路由

提供加工工艺卡、档口工艺路由、替代料规则、BOM 版本管理。
统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/supply/craft", tags=["craft"])


# ─── 请求模型 ───


class CraftStep(BaseModel):
    seq: int
    name: str
    duration_seconds: int = 0
    temperature: Optional[float] = None
    tool: Optional[str] = None
    notes: Optional[str] = None


class CreateCraftCardRequest(BaseModel):
    dish_id: str
    steps: list[CraftStep]


class DeptRoute(BaseModel):
    seq: int
    dept_id: str
    process_name: str
    estimated_seconds: int = 0


class SetDeptRoutingRequest(BaseModel):
    dish_id: str
    dept_sequence: list[DeptRoute]


class SubstituteItem(BaseModel):
    substitute_id: str
    ratio: float = 1.0
    priority: int = 1
    conditions: Optional[str] = None


class SetSubstituteRulesRequest(BaseModel):
    ingredient_id: str
    substitutes: list[SubstituteItem]


class ManageBomVersionRequest(BaseModel):
    template_id: str
    action: str  # review / approved / draft / archived
    operator_id: Optional[str] = None


# ─── 依赖 ───


def _get_tenant_id(x_tenant_id: str = Header(...)) -> str:
    """从请求头提取 tenant_id"""
    return x_tenant_id


# ─── 工艺卡 ───


@router.post("/cards")
async def create_craft_card(
    body: CreateCraftCardRequest,
    tenant_id: str = Depends(_get_tenant_id),
):
    """创建加工工艺卡（步骤/时间/温度/工具）"""
    from ..services.bom_craft import create_craft_card as svc

    try:
        result = await svc(
            dish_id=body.dish_id,
            steps=[s.model_dump() for s in body.steps],
            tenant_id=tenant_id,
            db=None,  # 实际部署时通过 Depends 注入
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── 档口路由 ───


@router.post("/routing")
async def set_dept_routing(
    body: SetDeptRoutingRequest,
    tenant_id: str = Depends(_get_tenant_id),
):
    """设置档口工艺路由（哪道工序在哪个档口）"""
    from ..services.bom_craft import set_dept_routing as svc

    try:
        result = await svc(
            dish_id=body.dish_id,
            dept_sequence=[d.model_dump() for d in body.dept_sequence],
            tenant_id=tenant_id,
            db=None,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── 替代料规则 ───


@router.post("/substitutes")
async def set_substitute_rules(
    body: SetSubstituteRulesRequest,
    tenant_id: str = Depends(_get_tenant_id),
):
    """设置原料替代规则"""
    from ..services.bom_craft import set_substitute_rules as svc

    try:
        result = await svc(
            ingredient_id=body.ingredient_id,
            substitutes=[s.model_dump() for s in body.substitutes],
            tenant_id=tenant_id,
            db=None,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── BOM 版本管理 ───


@router.post("/bom-version")
async def manage_bom_version(
    body: ManageBomVersionRequest,
    tenant_id: str = Depends(_get_tenant_id),
):
    """BOM 版本状态管理（draft/review/approved/archived）"""
    from ..services.bom_craft import manage_bom_version as svc

    try:
        result = await svc(
            template_id=body.template_id,
            action=body.action,
            tenant_id=tenant_id,
            db=None,
            operator_id=body.operator_id,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
