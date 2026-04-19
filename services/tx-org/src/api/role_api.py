"""角色级别 API — 支持10级权限体系

CRUD 端点：
  GET    /api/v1/org/roles                     列出角色
  POST   /api/v1/org/roles                     创建角色
  GET    /api/v1/org/roles/{role_id}           查询单个角色
  PATCH  /api/v1/org/roles/{role_id}           更新角色（含10级权限字段）
  DELETE /api/v1/org/roles/{role_id}           软删除角色

  GET    /api/v1/org/role-level-defaults       查询10级默认配置模板

安全约束：
  - 更新/删除角色时，operator_employee_id 的角色级别必须 >= 被操作角色级别
  - 创建角色时，level 不能高于操作人自身级别
  - 只有 Level 10 管理员可创建 Level 10 角色
"""

import uuid
from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from services.permission_service import PermissionService
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/org", tags=["org-roles"])

_perm_svc = PermissionService()


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


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class CreateRoleReq(BaseModel):
    role_name: str = Field(max_length=50)
    role_code: str = Field(max_length=30)
    level: int = Field(ge=1, le=10, description="1-10级，数字越大权限越高")
    max_discount_rate: float = Field(default=100.0, ge=0.0, le=100.0, description="最低折扣率(%)，0=无限制（仅管理员）")
    max_wipeoff_fen: int = Field(default=0, ge=0, description="抹零上限(分)")
    max_gift_fen: int = Field(default=0, ge=0, description="赠送上限(分)")
    data_query_days: int = Field(default=30, ge=0, description="可查询历史天数，9999=无限制")
    can_void_order: bool = Field(default=False)
    can_modify_price: bool = Field(default=False)
    can_override_discount: bool = Field(default=False)
    # 操作人（权限校验用）
    operator_employee_id: UUID = Field(description="创建者员工ID，用于级别约束校验")


class PatchRoleReq(BaseModel):
    role_name: Optional[str] = Field(default=None, max_length=50)
    level: Optional[int] = Field(default=None, ge=1, le=10)
    max_discount_rate: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    max_wipeoff_fen: Optional[int] = Field(default=None, ge=0)
    max_gift_fen: Optional[int] = Field(default=None, ge=0)
    data_query_days: Optional[int] = Field(default=None, ge=0)
    can_void_order: Optional[bool] = None
    can_modify_price: Optional[bool] = None
    can_override_discount: Optional[bool] = None
    operator_employee_id: UUID = Field(description="操作人员工ID，级别需 >= 被修改角色的级别")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点实现
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/roles")
async def list_roles(
    page: int = 1,
    size: int = 20,
    x_tenant_id: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取当前租户角色列表（按级别排序）"""
    tenant_id = _get_tenant(x_tenant_id)
    offset = (page - 1) * size

    count_sql = text("""
        SELECT COUNT(*) FROM role_configs
        WHERE tenant_id = :tenant_id AND is_deleted = FALSE
    """)
    items_sql = text("""
        SELECT id, role_name, role_code, level,
               max_discount_rate, max_wipeoff_fen, max_gift_fen_v2 AS max_gift_fen,
               data_query_days, can_void_order, can_modify_price, can_override_discount,
               created_at, updated_at
        FROM role_configs
        WHERE tenant_id = :tenant_id AND is_deleted = FALSE
        ORDER BY level ASC, created_at ASC
        LIMIT :size OFFSET :offset
    """)

    total_result = await db.execute(count_sql, {"tenant_id": str(tenant_id)})
    total = total_result.scalar_one()

    items_result = await db.execute(items_sql, {"tenant_id": str(tenant_id), "size": size, "offset": offset})
    rows = items_result.mappings().all()

    items = [
        {
            "id": str(r["id"]),
            "role_name": r["role_name"],
            "role_code": r["role_code"],
            "level": r["level"],
            "max_discount_rate": float(r["max_discount_rate"]),
            "max_wipeoff_fen": int(r["max_wipeoff_fen"]),
            "max_gift_fen": int(r["max_gift_fen"]),
            "data_query_days": int(r["data_query_days"]),
            "can_void_order": bool(r["can_void_order"]),
            "can_modify_price": bool(r["can_modify_price"]),
            "can_override_discount": bool(r["can_override_discount"]),
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        for r in rows
    ]

    return _ok({"items": items, "total": total, "page": page, "size": size})


@router.post("/roles")
async def create_role(
    req: CreateRoleReq,
    x_tenant_id: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """新建角色 — 创建者级别必须 >= 新角色级别"""
    tenant_id = _get_tenant(x_tenant_id)

    # 校验操作人级别
    operator_role = await _perm_svc.get_employee_role_snapshot(
        employee_id=req.operator_employee_id,
        tenant_id=tenant_id,
        session=db,
    )
    if operator_role is None:
        raise HTTPException(status_code=403, detail="操作人未分配角色，无权创建角色")
    if req.level > operator_role.level:
        raise HTTPException(
            status_code=403,
            detail=f"不能创建高于自己级别的角色（自身 Level {operator_role.level}，目标 Level {req.level}）",
        )

    role_id = str(uuid.uuid4())
    sql = text("""
        INSERT INTO role_configs
            (id, tenant_id, role_name, role_code, role_level, level,
             max_discount_rate, max_wipeoff_fen, max_gift_fen_v2,
             data_query_days, can_void_order, can_modify_price, can_override_discount,
             max_discount_pct, max_tip_off_fen, max_gift_fen, max_order_gift_fen,
             data_query_limit)
        VALUES
            (:id, :tenant_id, :role_name, :role_code, :level, :level,
             :max_discount_rate, :max_wipeoff_fen, :max_gift_fen,
             :data_query_days, :can_void_order, :can_modify_price, :can_override_discount,
             :max_discount_pct_legacy, :max_wipeoff_fen, :max_gift_fen, 0,
             :data_query_limit_legacy)
        RETURNING id, role_name, level
    """)
    # 兼容旧字段（v1时代）
    data_query_days = req.data_query_days
    if data_query_days >= 9999:
        data_query_limit_legacy = "unlimited"
    elif data_query_days >= 365:
        data_query_limit_legacy = "1y"
    elif data_query_days >= 90:
        data_query_limit_legacy = "90d"
    elif data_query_days >= 30:
        data_query_limit_legacy = "30d"
    else:
        data_query_limit_legacy = "7d"

    result = await db.execute(
        sql,
        {
            "id": role_id,
            "tenant_id": str(tenant_id),
            "role_name": req.role_name,
            "role_code": req.role_code,
            "level": req.level,
            "max_discount_rate": req.max_discount_rate,
            "max_wipeoff_fen": req.max_wipeoff_fen,
            "max_gift_fen": req.max_gift_fen,
            "data_query_days": req.data_query_days,
            "can_void_order": req.can_void_order,
            "can_modify_price": req.can_modify_price,
            "can_override_discount": req.can_override_discount,
            "max_discount_pct_legacy": int(req.max_discount_rate),
            "data_query_limit_legacy": data_query_limit_legacy,
        },
    )
    await db.commit()
    row = result.mappings().first()

    logger.info(
        "role_created",
        role_id=role_id,
        operator_employee_id=str(req.operator_employee_id),
        level=req.level,
    )

    return _ok(
        {
            "id": str(row["id"]),
            "role_name": row["role_name"],
            "level": row["level"],
        }
    )


@router.get("/roles/{role_id}")
async def get_role(
    role_id: UUID,
    x_tenant_id: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询单个角色详情"""
    tenant_id = _get_tenant(x_tenant_id)

    sql = text("""
        SELECT id, role_name, role_code, level,
               max_discount_rate, max_wipeoff_fen, max_gift_fen_v2 AS max_gift_fen,
               data_query_days, can_void_order, can_modify_price, can_override_discount,
               created_at, updated_at
        FROM role_configs
        WHERE id = :role_id AND tenant_id = :tenant_id AND is_deleted = FALSE
    """)
    result = await db.execute(sql, {"role_id": str(role_id), "tenant_id": str(tenant_id)})
    row = result.mappings().first()

    if row is None:
        raise HTTPException(status_code=404, detail="角色不存在")

    return _ok(
        {
            "id": str(row["id"]),
            "role_name": row["role_name"],
            "role_code": row["role_code"],
            "level": row["level"],
            "max_discount_rate": float(row["max_discount_rate"]),
            "max_wipeoff_fen": int(row["max_wipeoff_fen"]),
            "max_gift_fen": int(row["max_gift_fen"]),
            "data_query_days": int(row["data_query_days"]),
            "can_void_order": bool(row["can_void_order"]),
            "can_modify_price": bool(row["can_modify_price"]),
            "can_override_discount": bool(row["can_override_discount"]),
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }
    )


@router.patch("/roles/{role_id}")
async def patch_role(
    role_id: UUID,
    req: PatchRoleReq,
    x_tenant_id: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新角色 — 操作人级别必须 >= 被操作角色级别"""
    tenant_id = _get_tenant(x_tenant_id)

    # 查询被修改角色的当前级别
    check_sql = text("""
        SELECT level FROM role_configs
        WHERE id = :role_id AND tenant_id = :tenant_id AND is_deleted = FALSE
    """)
    check_result = await db.execute(check_sql, {"role_id": str(role_id), "tenant_id": str(tenant_id)})
    target_row = check_result.mappings().first()
    if target_row is None:
        raise HTTPException(status_code=404, detail="角色不存在")

    target_level = int(target_row["level"])

    # 校验操作人级别
    operator_role = await _perm_svc.get_employee_role_snapshot(
        employee_id=req.operator_employee_id,
        tenant_id=tenant_id,
        session=db,
    )
    if operator_role is None:
        raise HTTPException(status_code=403, detail="操作人未分配角色，无权修改")
    if operator_role.level < target_level:
        raise HTTPException(
            status_code=403,
            detail=f"操作人级别（{operator_role.level}）低于被修改角色级别（{target_level}），无权修改",
        )
    if req.level is not None and req.level > operator_role.level:
        raise HTTPException(
            status_code=403,
            detail=f"不能将角色级别提升到高于自己的级别（操作人 Level {operator_role.level}）",
        )

    # 构建动态 UPDATE
    updates: dict[str, object] = {}
    if req.role_name is not None:
        updates["role_name"] = req.role_name
    if req.level is not None:
        updates["level"] = req.level
        updates["role_level"] = req.level  # 同步旧字段
    if req.max_discount_rate is not None:
        updates["max_discount_rate"] = req.max_discount_rate
        updates["max_discount_pct"] = int(req.max_discount_rate)
    if req.max_wipeoff_fen is not None:
        updates["max_wipeoff_fen"] = req.max_wipeoff_fen
        updates["max_tip_off_fen"] = req.max_wipeoff_fen
    if req.max_gift_fen is not None:
        updates["max_gift_fen_v2"] = req.max_gift_fen
        updates["max_gift_fen"] = req.max_gift_fen
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

    update_sql = text(f"""
        UPDATE role_configs
        SET {set_clauses}, updated_at = NOW()
        WHERE id = :role_id AND tenant_id = :tenant_id AND is_deleted = FALSE
        RETURNING id, role_name, level
    """)
    update_result = await db.execute(update_sql, params)
    updated_row = update_result.mappings().first()
    await db.commit()

    if updated_row is None:
        raise HTTPException(status_code=404, detail="更新失败")

    logger.info(
        "role_updated",
        role_id=str(role_id),
        operator_employee_id=str(req.operator_employee_id),
        updates=list(updates.keys()),
    )

    return _ok(
        {
            "id": str(updated_row["id"]),
            "role_name": updated_row["role_name"],
            "level": updated_row["level"],
            "updated": True,
        }
    )


@router.delete("/roles/{role_id}")
async def delete_role(
    role_id: UUID,
    operator_employee_id: UUID,
    x_tenant_id: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """软删除角色（逻辑删除，不物理删除，保留留痕）"""
    tenant_id = _get_tenant(x_tenant_id)

    # 查询被删除角色的级别
    check_sql = text("""
        SELECT level FROM role_configs
        WHERE id = :role_id AND tenant_id = :tenant_id AND is_deleted = FALSE
    """)
    check_result = await db.execute(check_sql, {"role_id": str(role_id), "tenant_id": str(tenant_id)})
    target_row = check_result.mappings().first()
    if target_row is None:
        raise HTTPException(status_code=404, detail="角色不存在")

    target_level = int(target_row["level"])

    operator_role = await _perm_svc.get_employee_role_snapshot(
        employee_id=operator_employee_id,
        tenant_id=tenant_id,
        session=db,
    )
    if operator_role is None or operator_role.level < target_level:
        raise HTTPException(
            status_code=403,
            detail="操作人级别不足，无权删除该角色",
        )

    delete_sql = text("""
        UPDATE role_configs
        SET is_deleted = TRUE, updated_at = NOW()
        WHERE id = :role_id AND tenant_id = :tenant_id
    """)
    await db.execute(delete_sql, {"role_id": str(role_id), "tenant_id": str(tenant_id)})
    await db.commit()

    logger.info(
        "role_deleted",
        role_id=str(role_id),
        operator_employee_id=str(operator_employee_id),
        target_level=target_level,
    )

    return _ok({"deleted": True, "role_id": str(role_id)})


@router.get("/role-level-defaults")
async def get_role_level_defaults(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询10级默认角色模板（系统级，无需租户过滤）"""
    sql = text("""
        SELECT level, level_name, max_discount_rate, max_wipeoff_fen, max_gift_fen,
               data_query_days, can_void_order, can_modify_price, can_override_discount,
               description
        FROM role_level_defaults
        ORDER BY level ASC
    """)
    result = await db.execute(sql)
    rows = result.mappings().all()

    items = [
        {
            "level": r["level"],
            "level_name": r["level_name"],
            "max_discount_rate": float(r["max_discount_rate"]),
            "max_wipeoff_fen": int(r["max_wipeoff_fen"]),
            "max_gift_fen": int(r["max_gift_fen"]),
            "data_query_days": int(r["data_query_days"]),
            "can_void_order": bool(r["can_void_order"]),
            "can_modify_price": bool(r["can_modify_price"]),
            "can_override_discount": bool(r["can_override_discount"]),
            "description": r["description"],
        }
        for r in rows
    ]

    return _ok({"items": items, "total": len(items)})
