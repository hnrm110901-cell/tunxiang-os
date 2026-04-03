"""口味做法管理 API — 菜品做法/忌口/辣度/甜度模板

品智POS核心需求：菜品做法的增删查 + 通用模板。
统一响应格式: {"ok": bool, "data": {}, "error": {}}

端点：
  GET  /api/v1/dishes/{dish_id}/practices            获取菜品可选做法
  POST /api/v1/dishes/{dish_id}/practices            添加做法
  DELETE /api/v1/dishes/{dish_id}/practices/{id}     删除做法
  GET  /api/v1/practices/templates                    通用做法模板
"""
import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..services import dish_practice_service as svc

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1", tags=["dish-practices"])


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get(
        "X-Tenant-ID", ""
    )
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


# ─── 请求模型 ───


class AddPracticeReq(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, description="做法名称")
    additional_price_fen: int = Field(
        default=0, ge=0, description="加价（分），0表示不加价"
    )
    materials: list[dict] = Field(
        default_factory=list,
        description='配料调整 [{"name": "辣椒", "amount": "少许"}]',
    )
    category: str = Field(
        default="",
        description="做法分类: spicy / sweetness / avoid / extra",
    )


# ─── 通用做法模板（无路径参数，放在前面避免路由冲突） ───


@router.get("/practices/templates")
async def get_practice_templates() -> dict:
    """获取通用做法模板（辣度/甜度/忌口/加料）

    门店可基于模板快速批量配置菜品做法。
    """
    templates = await svc.get_practice_templates()
    return {"ok": True, "data": templates}


# ─── 菜品做法 CRUD ───


@router.get("/dishes/{dish_id}/practices")
async def get_dish_practices(dish_id: str, request: Request) -> dict:
    """获取菜品可选做法列表"""
    tenant_id = _get_tenant_id(request)
    practices = await svc.get_dish_practices(dish_id, tenant_id)
    return {"ok": True, "data": practices}


@router.post("/dishes/{dish_id}/practices")
async def add_dish_practice(
    dish_id: str,
    body: AddPracticeReq,
    request: Request,
) -> dict:
    """添加菜品做法（如微辣、不要香菜、加蛋）"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await svc.add_dish_practice(
            dish_id=dish_id,
            name=body.name,
            additional_price_fen=body.additional_price_fen,
            materials=body.materials,
            tenant_id=tenant_id,
            category=body.category,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/dishes/{dish_id}/practices/{practice_id}")
async def delete_dish_practice(
    dish_id: str,
    practice_id: str,
    request: Request,
) -> dict:
    """删除菜品做法"""
    tenant_id = _get_tenant_id(request)
    removed = await svc.remove_dish_practice(dish_id, practice_id, tenant_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"做法不存在: {practice_id}")
    return {"ok": True, "data": {"practice_id": practice_id, "deleted": True}}
