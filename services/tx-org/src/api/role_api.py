"""角色级别 API"""
import uuid
from typing import Optional, Literal
from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/org", tags=["org-roles"])


class CreateRoleReq(BaseModel):
    role_name: str
    role_code: str
    role_level: int = Field(ge=1, le=10)
    max_discount_pct: int = Field(default=100, ge=0, le=100)
    max_tip_off_fen: int = Field(default=0, ge=0)
    max_gift_fen: int = Field(default=0, ge=0)
    max_order_gift_fen: int = Field(default=0, ge=0)
    data_query_limit: Literal["unlimited", "7d", "30d", "90d", "1y"] = "7d"


# 模拟数据
_MOCK_ROLES = [
    {
        "id": str(uuid.uuid4()),
        "role_name": "服务员",
        "role_code": "waiter",
        "role_level": 1,
        "max_discount_pct": 100,
        "max_tip_off_fen": 0,
        "max_gift_fen": 0,
        "max_order_gift_fen": 0,
        "data_query_limit": "7d",
    },
    {
        "id": str(uuid.uuid4()),
        "role_name": "店长",
        "role_code": "store_manager",
        "role_level": 7,
        "max_discount_pct": 70,
        "max_tip_off_fen": 5000,
        "max_gift_fen": 10000,
        "max_order_gift_fen": 20000,
        "data_query_limit": "90d",
    },
    {
        "id": str(uuid.uuid4()),
        "role_name": "区域经理",
        "role_code": "area_manager",
        "role_level": 9,
        "max_discount_pct": 50,
        "max_tip_off_fen": 10000,
        "max_gift_fen": 30000,
        "max_order_gift_fen": 50000,
        "data_query_limit": "unlimited",
    },
]


@router.get("/roles")
async def list_roles(page: int = 1, size: int = 20):
    """获取角色列表"""
    return {"ok": True, "data": {"items": _MOCK_ROLES, "total": len(_MOCK_ROLES)}}


@router.post("/roles")
async def create_role(req: CreateRoleReq):
    """新建角色"""
    role_data = {
        "id": str(uuid.uuid4()),
        **req.model_dump(),
    }
    return {"ok": True, "data": role_data}
