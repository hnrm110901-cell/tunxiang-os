"""权限检查 API — 10级角色体系

提供收银系统调用的权限校验端点：

  POST /api/v1/permissions/check-discount     折扣权限检查
  POST /api/v1/permissions/check-operation    通用操作权限检查（抹零/赠送/退单/改价）
  GET  /api/v1/roles/{role_id}/limits         查询角色限制配置
  PUT  /api/v1/roles/{role_id}/limits         更新角色限制配置（需高级权限）

所有接口需 X-Tenant-ID header。
统一响应格式: {"ok": bool, "data": {}, "error": null}
"""
from __future__ import annotations

from typing import Literal, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from services.permission_service import PermissionCheckResult, PermissionService
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/permissions", tags=["permissions"])
role_limits_router = APIRouter(prefix="/api/v1/roles", tags=["role-limits"])

_svc = PermissionService()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  辅助
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _get_tenant(x_tenant_id: Optional[str]) -> UUID:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    try:
        return UUID(x_tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="X-Tenant-ID 格式无效") from exc


def _ok(data: dict) -> dict:
    return {"ok": True, "data": data, "error": None}


def _result_to_dict(result: PermissionCheckResult) -> dict:
    return {
        "allowed": result.allowed,
        "require_approval": result.require_approval,
        "approver_min_level": result.approver_min_level,
        "message": result.message,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求/响应模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class CheckDiscountReq(BaseModel):
    employee_id: UUID
    discount_rate: float = Field(
        ge=0.0, le=100.0,
        description="折扣率百分比，如 85.0 = 打85折（即8.5折）",
    )
    store_id: Optional[UUID] = None
    order_id: Optional[UUID] = None


OperationType = Literal["void_order", "modify_price", "gift", "wipeoff"]


class CheckOperationReq(BaseModel):
    employee_id: UUID
    operation: OperationType = Field(description="操作类型")
    amount_fen: Optional[int] = Field(
        default=None, ge=0,
        description="涉及金额（分），gift/wipeoff 时必填",
    )
    store_id: Optional[UUID] = None
    order_id: Optional[UUID] = None


class PermissionCheckResp(BaseModel):
    allowed: bool
    require_approval: bool
    approver_min_level: int
    message: str


class RoleLimitsResp(BaseModel):
    role_config_id: str
    role_name: str
    level: int
    max_discount_rate: float
    max_wipeoff_fen: int
    max_gift_fen: int
    data_query_days: int
    can_void_order: bool
    can_modify_price: bool
    can_override_discount: bool


class UpdateRoleLimitsReq(BaseModel):
    level: Optional[int] = Field(default=None, ge=1, le=10)
    max_discount_rate: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    max_wipeoff_fen: Optional[int] = Field(default=None, ge=0)
    max_gift_fen: Optional[int] = Field(default=None, ge=0)
    data_query_days: Optional[int] = Field(default=None, ge=0)
    can_void_order: Optional[bool] = None
    can_modify_price: Optional[bool] = None
    can_override_discount: Optional[bool] = None
    # 操作人信息，用于级别校验
    operator_employee_id: UUID = Field(description="执行此更新的员工ID（需同级或更高级别）")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点实现
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/check-discount", response_model=None)
async def check_discount(
    req: CheckDiscountReq,
    request: Request,
    x_tenant_id: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """折扣权限检查

    Body: {employee_id, discount_rate, store_id?, order_id?}
    返回: {allowed, require_approval, approver_min_level, message}

    - allowed=True → 直接执行
    - allowed=False, require_approval=True → 需上级审批，approver_min_level 指定最低审批级别
    - allowed=False, require_approval=False → 直接拒绝
    """
    tenant_id = _get_tenant(x_tenant_id)
    client_ip = request.client.host if request.client else None

    result = await _svc.check_discount_permission(
        employee_id=req.employee_id,
        discount_rate=req.discount_rate,
        tenant_id=tenant_id,
        session=db,
        store_id=req.store_id,
        order_id=req.order_id,
        request_ip=client_ip,
    )
    await db.commit()
    return _ok(_result_to_dict(result))


@router.post("/check-operation", response_model=None)
async def check_operation(
    req: CheckOperationReq,
    request: Request,
    x_tenant_id: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """通用操作权限检查

    Body: {employee_id, operation, amount_fen?, store_id?, order_id?}

    operation 取值：
      - void_order   退单（amount_fen 不需要）
      - modify_price 改价（amount_fen 不需要）
      - gift         赠送（amount_fen 必填，单位：分）
      - wipeoff      抹零（amount_fen 必填，单位：分）
    """
    tenant_id = _get_tenant(x_tenant_id)
    client_ip = request.client.host if request.client else None

    if req.operation in ("gift", "wipeoff") and req.amount_fen is None:
        raise HTTPException(
            status_code=422,
            detail=f"operation={req.operation} 时 amount_fen 不能为空",
        )

    if req.operation == "void_order":
        result = await _svc.check_void_order_permission(
            employee_id=req.employee_id,
            tenant_id=tenant_id,
            session=db,
            store_id=req.store_id,
            order_id=req.order_id,
            request_ip=client_ip,
        )
    elif req.operation == "modify_price":
        result = await _svc.check_modify_price_permission(
            employee_id=req.employee_id,
            tenant_id=tenant_id,
            session=db,
            store_id=req.store_id,
            order_id=req.order_id,
            request_ip=client_ip,
        )
    elif req.operation == "gift":
        result = await _svc.check_gift_permission(
            employee_id=req.employee_id,
            amount_fen=req.amount_fen,  # type: ignore[arg-type]
            tenant_id=tenant_id,
            session=db,
            store_id=req.store_id,
            order_id=req.order_id,
            request_ip=client_ip,
        )
    else:  # wipeoff
        result = await _svc.check_wipeoff_permission(
            employee_id=req.employee_id,
            amount_fen=req.amount_fen,  # type: ignore[arg-type]
            tenant_id=tenant_id,
            session=db,
            store_id=req.store_id,
            order_id=req.order_id,
            request_ip=client_ip,
        )

    await db.commit()
    return _ok(_result_to_dict(result))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  角色限制配置 CRUD
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@role_limits_router.get("/{role_id}/limits", response_model=None)
async def get_role_limits(
    role_id: UUID,
    x_tenant_id: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询角色的所有限制配置"""
    tenant_id = _get_tenant(x_tenant_id)

    sql = text("""
        SELECT
            id, role_name, level,
            max_discount_rate, max_wipeoff_fen, max_gift_fen_v2 AS max_gift_fen,
            data_query_days,
            can_void_order, can_modify_price, can_override_discount
        FROM role_configs
        WHERE id = :role_id
          AND tenant_id = :tenant_id
          AND is_deleted = FALSE
    """)
    result = await db.execute(sql, {"role_id": str(role_id), "tenant_id": str(tenant_id)})
    row = result.mappings().first()

    if row is None:
        raise HTTPException(status_code=404, detail="角色不存在")

    return _ok({
        "role_config_id": str(row["id"]),
        "role_name": row["role_name"],
        "level": row["level"],
        "max_discount_rate": float(row["max_discount_rate"]),
        "max_wipeoff_fen": int(row["max_wipeoff_fen"]),
        "max_gift_fen": int(row["max_gift_fen"]),
        "data_query_days": int(row["data_query_days"]),
        "can_void_order": bool(row["can_void_order"]),
        "can_modify_price": bool(row["can_modify_price"]),
        "can_override_discount": bool(row["can_override_discount"]),
    })


@role_limits_router.put("/{role_id}/limits", response_model=None)
async def update_role_limits(
    role_id: UUID,
    req: UpdateRoleLimitsReq,
    x_tenant_id: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新角色限制配置

    安全约束：操作人角色级别必须 >= 被修改角色的当前级别。
    即：只有同级或更高级别的角色才能修改角色配置。
    """
    tenant_id = _get_tenant(x_tenant_id)

    # 1. 查询被修改角色的当前级别
    sql_target = text("""
        SELECT id, level FROM role_configs
        WHERE id = :role_id AND tenant_id = :tenant_id AND is_deleted = FALSE
    """)
    target_result = await db.execute(
        sql_target, {"role_id": str(role_id), "tenant_id": str(tenant_id)}
    )
    target_row = target_result.mappings().first()
    if target_row is None:
        raise HTTPException(status_code=404, detail="角色不存在")

    target_level = int(target_row["level"])

    # 2. 查询操作人的角色级别
    operator_role = await _svc.get_employee_role_snapshot(
        employee_id=req.operator_employee_id,
        tenant_id=tenant_id,
        session=db,
    )
    if operator_role is None:
        raise HTTPException(status_code=403, detail="操作人未分配角色，无权修改")

    if operator_role.level < target_level:
        raise HTTPException(
            status_code=403,
            detail=f"操作人角色级别（{operator_role.level}）低于被修改角色级别（{target_level}），无权修改",
        )

    # 3. 构建动态 SET 子句（只更新传入的字段）
    updates: dict[str, object] = {}
    if req.level is not None:
        # 不能将角色级别提升到高于自己的级别
        if req.level > operator_role.level:
            raise HTTPException(
                status_code=403,
                detail=f"不能将角色级别设置为高于自己的级别（操作人 Level {operator_role.level}）",
            )
        updates["level"] = req.level
    if req.max_discount_rate is not None:
        updates["max_discount_rate"] = req.max_discount_rate
    if req.max_wipeoff_fen is not None:
        updates["max_wipeoff_fen"] = req.max_wipeoff_fen
    if req.max_gift_fen is not None:
        updates["max_gift_fen_v2"] = req.max_gift_fen
    if req.data_query_days is not None:
        updates["data_query_days"] = req.data_query_days
    if req.can_void_order is not None:
        updates["can_void_order"] = req.can_void_order
    if req.can_modify_price is not None:
        updates["can_modify_price"] = req.can_modify_price
    if req.can_override_discount is not None:
        updates["can_override_discount"] = req.can_override_discount

    if not updates:
        raise HTTPException(status_code=422, detail="至少需要提供一个更新字段")

    set_clauses = ", ".join(f"{col} = :{col}" for col in updates)
    params = {**updates, "role_id": str(role_id), "tenant_id": str(tenant_id)}

    sql_update = text(f"""
        UPDATE role_configs
        SET {set_clauses}, updated_at = NOW()
        WHERE id = :role_id AND tenant_id = :tenant_id AND is_deleted = FALSE
        RETURNING id, role_name, level, max_discount_rate,
                  max_wipeoff_fen, max_gift_fen_v2 AS max_gift_fen,
                  data_query_days, can_void_order, can_modify_price, can_override_discount
    """)
    update_result = await db.execute(sql_update, params)
    updated_row = update_result.mappings().first()
    await db.commit()

    if updated_row is None:
        raise HTTPException(status_code=404, detail="更新失败，角色不存在")

    logger.info(
        "role_limits_updated",
        role_id=str(role_id),
        operator_employee_id=str(req.operator_employee_id),
        operator_level=operator_role.level,
        updates=list(updates.keys()),
    )

    return _ok({
        "role_config_id": str(updated_row["id"]),
        "role_name": updated_row["role_name"],
        "level": updated_row["level"],
        "max_discount_rate": float(updated_row["max_discount_rate"]),
        "max_wipeoff_fen": int(updated_row["max_wipeoff_fen"]),
        "max_gift_fen": int(updated_row["max_gift_fen"]),
        "data_query_days": int(updated_row["data_query_days"]),
        "can_void_order": bool(updated_row["can_void_order"]),
        "can_modify_price": bool(updated_row["can_modify_price"]),
        "can_override_discount": bool(updated_row["can_override_discount"]),
        "updated_by_level": operator_role.level,
    })
