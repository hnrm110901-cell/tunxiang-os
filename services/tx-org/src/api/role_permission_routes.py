"""角色权限管理 API — 全量接入真实 DB

端点列表（prefix=/api/v1/org）：
  GET    /permissions/tree        — 权限树（静态配置）
  GET    /roles-admin             — 角色列表（来自 role_configs DB）
  POST   /roles-admin             — 创建角色（写入 role_configs DB）
  PATCH  /roles-admin/{role_id}   — 更新角色权限（写入 role_configs DB）
  DELETE /roles-admin/{role_id}   — 删除角色（软删除 role_configs）
  GET    /user-roles              — 用户角色列表（employees JOIN roles DB 查询）
  PATCH  /user-roles/{user_id}    — 更新用户角色（employees DB 写入）
  POST   /user-roles/batch        — 批量设置用户角色（employees DB 批量写入）
  GET    /audit-logs              — 操作日志（audit_logs DB 查询）

DB 失败时：列表类端点返回空集合，不返回 500。
所有接口需 X-Tenant-ID header。

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""

from __future__ import annotations

from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/org", tags=["role-permission-admin"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  静态权限树（不入 DB，业务定义在代码层维护）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PERMISSION_TREE = [
    {
        "key": "store",
        "title": "门店管理",
        "children": [
            {"key": "store:view", "title": "查看"},
            {"key": "store:create", "title": "新增"},
            {"key": "store:edit", "title": "编辑"},
            {"key": "store:delete", "title": "删除"},
            {"key": "store:approve", "title": "审批"},
        ],
    },
    {
        "key": "dish",
        "title": "菜品管理",
        "children": [
            {"key": "dish:view", "title": "查看"},
            {"key": "dish:create", "title": "新增"},
            {"key": "dish:edit", "title": "编辑"},
            {"key": "dish:delete", "title": "删除"},
            {"key": "dish:approve", "title": "审批"},
        ],
    },
    {
        "key": "order",
        "title": "订单管理",
        "children": [
            {"key": "order:view", "title": "查看"},
            {"key": "order:create", "title": "新增"},
            {"key": "order:edit", "title": "编辑"},
            {"key": "order:delete", "title": "删除"},
            {"key": "order:approve", "title": "审批"},
        ],
    },
    {
        "key": "member",
        "title": "会员管理",
        "children": [
            {"key": "member:view", "title": "查看"},
            {"key": "member:create", "title": "新增"},
            {"key": "member:edit", "title": "编辑"},
            {"key": "member:delete", "title": "删除"},
            {"key": "member:approve", "title": "审批"},
        ],
    },
    {
        "key": "finance",
        "title": "财务管理",
        "children": [
            {"key": "finance:view", "title": "查看"},
            {"key": "finance:create", "title": "新增"},
            {"key": "finance:edit", "title": "编辑"},
            {"key": "finance:delete", "title": "删除"},
            {"key": "finance:approve", "title": "审批"},
        ],
    },
    {
        "key": "marketing",
        "title": "营销管理",
        "children": [
            {"key": "marketing:view", "title": "查看"},
            {"key": "marketing:create", "title": "新增"},
            {"key": "marketing:edit", "title": "编辑"},
            {"key": "marketing:delete", "title": "删除"},
            {"key": "marketing:approve", "title": "审批"},
        ],
    },
    {
        "key": "supply",
        "title": "供应链",
        "children": [
            {"key": "supply:view", "title": "查看"},
            {"key": "supply:create", "title": "新增"},
            {"key": "supply:edit", "title": "编辑"},
            {"key": "supply:delete", "title": "删除"},
            {"key": "supply:approve", "title": "审批"},
        ],
    },
    {
        "key": "system",
        "title": "系统设置",
        "children": [
            {"key": "system:view", "title": "查看"},
            {"key": "system:create", "title": "新增"},
            {"key": "system:edit", "title": "编辑"},
            {"key": "system:delete", "title": "删除"},
            {"key": "system:approve", "title": "审批"},
        ],
    },
]

ALL_PERM_KEYS = [child["key"] for group in PERMISSION_TREE for child in group["children"]]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class CreateRoleReq(BaseModel):
    name: str = Field(..., max_length=50, description="角色名称")
    description: str = Field(default="", max_length=200, description="角色描述")
    permissions: list[str] = Field(default_factory=list, description="权限 key 列表")
    level: int = Field(default=5, ge=1, le=10, description="角色级别 1-10")


class UpdateRoleReq(BaseModel):
    permissions: list[str] = Field(default_factory=list, description="权限 key 列表")
    description: Optional[str] = Field(default=None, max_length=200)
    level: Optional[int] = Field(default=None, ge=1, le=10)


class UpdateUserRolesReq(BaseModel):
    roles: list[str]


class BatchUserRolesReq(BaseModel):
    user_ids: list[str]
    roles: list[str]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  辅助
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, status: int = 400) -> dict[str, Any]:
    return {"ok": False, "data": None, "error": {"message": msg, "status": status}}


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _row_to_dict(row: Any) -> dict[str, Any]:
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif hasattr(v, "__str__") and type(v).__name__ == "UUID":
            d[k] = str(v)
    return d


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点 — 权限树（静态）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/permissions/tree")
async def get_permission_tree() -> dict:
    """GET /api/v1/org/permissions/tree — 返回静态权限树结构"""
    return _ok(PERMISSION_TREE)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点 — role_configs DB CRUD
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/roles-admin")
async def list_roles_admin(
    request: Request,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    keyword: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """GET /api/v1/org/roles-admin — 角色列表（来自 role_configs DB）"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    conditions = ["tenant_id = :tid::uuid", "is_deleted = FALSE"]
    params: dict[str, Any] = {"tid": tenant_id}

    if keyword:
        conditions.append("(role_name ILIKE :kw OR description ILIKE :kw)")
        params["kw"] = f"%{keyword}%"

    where_clause = " AND ".join(conditions)

    try:
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM role_configs WHERE {where_clause}"),
            params,
        )
        total = count_result.scalar() or 0

        offset = (page - 1) * size
        params["limit"] = size
        params["offset"] = offset

        result = await db.execute(
            text(
                f"SELECT id, role_name, role_code, level, "
                f"       COALESCE(permissions_json, '[]'::jsonb) AS permissions_json, "
                f"       is_deleted, created_at, updated_at "
                f"FROM role_configs "
                f"WHERE {where_clause} "
                f"ORDER BY level ASC, created_at ASC "
                f"LIMIT :limit OFFSET :offset"
            ),
            params,
        )
        rows = result.mappings().fetchall()
    except SQLAlchemyError as exc:
        log.error("list_roles_admin_db_error", error=str(exc), exc_info=True)
        # graceful fallback：返回空列表，不返回 500
        return _ok({"items": [], "total": 0, "page": page, "size": size, "_db_error": True})

    items = []
    for row in rows:
        d = _row_to_dict(row)
        perms = d.get("permissions_json") or []
        if isinstance(perms, str):
            import json

            try:
                perms = json.loads(perms)
            except (ValueError, TypeError):
                perms = []
        items.append(
            {
                "id": d["id"],
                "name": d.get("role_name", ""),
                "code": d.get("role_code", ""),
                "level": d.get("level", 5),
                "is_preset": False,
                "status": "active",
                "permissions": perms,
                "permission_count": len(perms),
                "created_at": d.get("created_at"),
            }
        )

    log.info("roles_admin_listed", tenant_id=tenant_id, total=total, page=page)
    return _ok({"items": items, "total": total, "page": page, "size": size})


@router.post("/roles-admin")
async def create_role_admin(
    req: CreateRoleReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """POST /api/v1/org/roles-admin — 创建自定义角色（写入 role_configs DB）"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    import json as _json

    perms_json = _json.dumps(req.permissions, ensure_ascii=False)
    # role_code 由 name 生成（小写+下划线）
    role_code = req.name.lower().replace(" ", "_").replace("-", "_")[:30]

    try:
        result = await db.execute(
            text(
                "INSERT INTO role_configs "
                "(tenant_id, role_name, role_code, level, permissions_json) "
                "VALUES "
                "(:tid::uuid, :role_name, :role_code, :level, :permissions_json::jsonb) "
                "RETURNING id, role_name, role_code, level, "
                "          COALESCE(permissions_json, '[]'::jsonb) AS permissions_json, "
                "          created_at"
            ),
            {
                "tid": tenant_id,
                "role_name": req.name,
                "role_code": role_code,
                "level": req.level,
                "permissions_json": perms_json,
            },
        )
        row = result.mappings().first()
        await db.commit()
    except SQLAlchemyError as exc:
        log.error("create_role_admin_db_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=503, detail="数据库服务暂时不可用") from exc

    d = _row_to_dict(row)
    perms = d.get("permissions_json") or []
    if isinstance(perms, str):
        import json

        try:
            perms = json.loads(perms)
        except (ValueError, TypeError):
            perms = []

    new_role = {
        "id": d["id"],
        "name": d.get("role_name", ""),
        "code": d.get("role_code", ""),
        "level": d.get("level", 5),
        "is_preset": False,
        "status": "active",
        "permissions": perms,
        "permission_count": len(perms),
        "created_at": d.get("created_at"),
    }
    log.info("role_created", tenant_id=tenant_id, role_id=d["id"], name=req.name)
    return _ok(new_role)


@router.patch("/roles-admin/{role_id}")
async def update_role_admin(
    role_id: str,
    req: UpdateRoleReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """PATCH /api/v1/org/roles-admin/{role_id} — 更新角色权限和描述"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    import json as _json

    perms_json = _json.dumps(req.permissions, ensure_ascii=False)

    set_parts = ["permissions_json = :permissions_json::jsonb", "updated_at = NOW()"]
    params: dict[str, Any] = {
        "permissions_json": perms_json,
        "role_id": role_id,
        "tid": tenant_id,
    }

    if req.level is not None:
        set_parts.append("level = :level")
        params["level"] = req.level

    set_clause = ", ".join(set_parts)

    try:
        result = await db.execute(
            text(
                f"UPDATE role_configs "
                f"SET {set_clause} "
                f"WHERE id = :role_id::uuid "
                f"AND tenant_id = :tid::uuid "
                f"AND is_deleted = FALSE "
                f"RETURNING id, role_name, role_code, level, "
                f"          COALESCE(permissions_json, '[]'::jsonb) AS permissions_json, "
                f"          updated_at"
            ),
            params,
        )
        row = result.mappings().first()
        await db.commit()
    except SQLAlchemyError as exc:
        log.error("update_role_admin_db_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=503, detail="数据库服务暂时不可用") from exc

    if not row:
        return _err(f"角色 {role_id} 不存在", 404)

    d = _row_to_dict(row)
    perms = d.get("permissions_json") or []
    if isinstance(perms, str):
        import json

        try:
            perms = json.loads(perms)
        except (ValueError, TypeError):
            perms = []

    log.info(
        "role_updated",
        tenant_id=tenant_id,
        role_id=role_id,
        perm_count=len(perms),
    )
    return _ok(
        {
            "id": d["id"],
            "name": d.get("role_name", ""),
            "code": d.get("role_code", ""),
            "level": d.get("level", 5),
            "permissions": perms,
            "permission_count": len(perms),
            "updated_at": d.get("updated_at"),
        }
    )


@router.delete("/roles-admin/{role_id}")
async def delete_role_admin(
    role_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """DELETE /api/v1/org/roles-admin/{role_id} — 软删除角色（预设角色不可删除）"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    # 先查询是否存在且是否预设
    try:
        fetch_result = await db.execute(
            text(
                "SELECT id, is_preset FROM role_configs "
                "WHERE id = :role_id::uuid "
                "AND tenant_id = :tid::uuid "
                "AND is_deleted = FALSE"
            ),
            {"role_id": role_id, "tid": tenant_id},
        )
        row = fetch_result.mappings().first()
    except SQLAlchemyError as exc:
        log.error("delete_role_admin_fetch_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=503, detail="数据库服务暂时不可用") from exc

    if not row:
        return _err(f"角色 {role_id} 不存在", 404)

    if row["is_preset"]:
        return _err("预设角色不可删除", 403)

    try:
        await db.execute(
            text(
                "UPDATE role_configs "
                "SET is_deleted = TRUE, updated_at = NOW() "
                "WHERE id = :role_id::uuid "
                "AND tenant_id = :tid::uuid"
            ),
            {"role_id": role_id, "tid": tenant_id},
        )
        await db.commit()
    except SQLAlchemyError as exc:
        log.error("delete_role_admin_update_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=503, detail="数据库服务暂时不可用") from exc

    log.info("role_deleted", tenant_id=tenant_id, role_id=role_id)
    return _ok({"deleted": True, "role_id": role_id})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点 — 用户角色（employees JOIN roles 真实 DB 查询）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/user-roles")
async def list_user_roles(
    request: Request,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    keyword: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """GET /api/v1/org/user-roles — 用户角色列表（employees JOIN roles DB 查询）"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    conditions = ["e.tenant_id = :tid::uuid", "e.status != 'resigned'"]
    params: dict[str, Any] = {"tid": tenant_id}

    if keyword:
        conditions.append("(e.full_name ILIKE :kw OR e.phone ILIKE :kw)")
        params["kw"] = f"%{keyword}%"

    where_clause = " AND ".join(conditions)

    try:
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM employees e WHERE {where_clause}"),
            params,
        )
        total = count_result.scalar() or 0

        offset = (page - 1) * size
        params["limit"] = size
        params["offset"] = offset

        result = await db.execute(
            text(
                f"SELECT e.id, e.full_name, e.phone, e.status, e.employment_type, "
                f"       e.store_id, e.created_at, "
                f"       r.id AS role_id, r.name AS role_name, "
                f"       COALESCE(r.permissions, '[]'::jsonb) AS permissions "
                f"FROM employees e "
                f"LEFT JOIN roles r ON r.id = e.role_id AND r.tenant_id = :tid::uuid "
                f"WHERE {where_clause} "
                f"ORDER BY e.created_at DESC "
                f"LIMIT :limit OFFSET :offset"
            ),
            params,
        )
        rows = result.mappings().fetchall()
    except SQLAlchemyError as exc:
        log.error("list_user_roles_db_error", error=str(exc), exc_info=True)
        return _ok({"items": [], "total": 0, "page": page, "size": size, "_db_error": True})

    items = []
    for row in rows:
        d = _row_to_dict(row)
        perms = d.get("permissions") or []
        if isinstance(perms, str):
            import json

            try:
                perms = json.loads(perms)
            except (ValueError, TypeError):
                perms = []
        items.append(
            {
                "id": d["id"],
                "name": d.get("full_name", ""),
                "phone": d.get("phone", ""),
                "store_id": d.get("store_id"),
                "status": d.get("status", ""),
                "employment_type": d.get("employment_type", ""),
                "role_id": d.get("role_id"),
                "roles": [d["role_name"]] if d.get("role_name") else [],
                "permissions": perms,
                "created_at": d.get("created_at"),
            }
        )

    log.info("user_roles_listed", tenant_id=tenant_id, total=total, page=page)
    return _ok({"items": items, "total": total, "page": page, "size": size})


@router.patch("/user-roles/{user_id}")
async def update_user_roles(
    user_id: str,
    req: UpdateUserRolesReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """PATCH /api/v1/org/user-roles/{user_id} — 更新员工角色（按角色名查询 roles 表后写入 employees）"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    # req.roles 传角色名列表，取第一个匹配的角色 id 写入 employees.role_id
    role_id: Optional[str] = None
    role_name: Optional[str] = None
    if req.roles:
        try:
            role_result = await db.execute(
                text("SELECT id, name FROM roles WHERE tenant_id = :tid::uuid AND name = :rname LIMIT 1"),
                {"tid": tenant_id, "rname": req.roles[0]},
            )
            role_row = role_result.mappings().first()
            if role_row:
                role_id = str(role_row["id"])
                role_name = role_row["name"]
        except SQLAlchemyError as exc:
            log.error("update_user_roles_role_lookup_error", error=str(exc), exc_info=True)
            raise HTTPException(status_code=503, detail="数据库服务暂时不可用") from exc

    try:
        result = await db.execute(
            text(
                "UPDATE employees "
                "SET role_id = :role_id::uuid, updated_at = NOW() "
                "WHERE id = :uid::uuid AND tenant_id = :tid::uuid "
                "RETURNING id, full_name, phone, status"
            ),
            {"role_id": role_id, "uid": user_id, "tid": tenant_id},
        )
        row = result.mappings().first()
        await db.commit()
    except SQLAlchemyError as exc:
        log.error("update_user_roles_db_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=503, detail="数据库服务暂时不可用") from exc

    if not row:
        return _err(f"用户 {user_id} 不存在", 404)

    d = _row_to_dict(row)
    log.info("user_roles_updated", user_id=user_id, roles=req.roles)
    return _ok(
        {
            "id": d["id"],
            "name": d.get("full_name", ""),
            "roles": [role_name] if role_name else req.roles,
        }
    )


@router.post("/user-roles/batch")
async def batch_set_user_roles(
    req: BatchUserRolesReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """POST /api/v1/org/user-roles/batch — 批量设置员工角色（按角色名查询后批量更新 employees）"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    role_id: Optional[str] = None
    if req.roles:
        try:
            role_result = await db.execute(
                text("SELECT id FROM roles WHERE tenant_id = :tid::uuid AND name = :rname LIMIT 1"),
                {"tid": tenant_id, "rname": req.roles[0]},
            )
            role_row = role_result.mappings().first()
            if role_row:
                role_id = str(role_row["id"])
        except SQLAlchemyError as exc:
            log.error("batch_set_user_roles_role_lookup_error", error=str(exc), exc_info=True)
            raise HTTPException(status_code=503, detail="数据库服务暂时不可用") from exc

    updated_ids: list[str] = []
    try:
        for uid in req.user_ids:
            res = await db.execute(
                text(
                    "UPDATE employees "
                    "SET role_id = :role_id::uuid, updated_at = NOW() "
                    "WHERE id = :uid::uuid AND tenant_id = :tid::uuid "
                    "RETURNING id"
                ),
                {"role_id": role_id, "uid": uid, "tid": tenant_id},
            )
            if res.mappings().first():
                updated_ids.append(uid)
        await db.commit()
    except SQLAlchemyError as exc:
        log.error("batch_set_user_roles_db_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=503, detail="数据库服务暂时不可用") from exc

    log.info("batch_roles_set", count=len(updated_ids), roles=req.roles)
    return _ok({"updated_count": len(updated_ids), "user_ids": updated_ids})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点 — 操作日志（audit_logs 真实 DB 查询，SQLAlchemyError fallback 空列表）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/audit-logs")
async def list_audit_logs(
    request: Request,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    keyword: str = Query(default=""),
    action: str = Query(default=""),
    start_time: str = Query(default=""),
    end_time: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """GET /api/v1/org/audit-logs — 操作日志列表（audit_logs DB 查询，DB 失败返回空列表）"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    conditions = ["tenant_id = :tid::uuid"]
    params: dict[str, Any] = {"tid": tenant_id}

    if keyword:
        # keyword 匹配操作人 id（user_id）、resource_type 或 details 文本
        conditions.append("(al.user_id::text ILIKE :kw OR al.resource_type ILIKE :kw OR al.details::text ILIKE :kw)")
        params["kw"] = f"%{keyword}%"

    if action:
        conditions.append("al.action = :action")
        params["action"] = action

    if start_time:
        conditions.append("al.created_at >= :start_time::timestamptz")
        params["start_time"] = start_time

    if end_time:
        conditions.append("al.created_at <= :end_time::timestamptz")
        params["end_time"] = end_time

    where_clause = " AND ".join(conditions)

    try:
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM audit_logs al WHERE {where_clause}"),
            params,
        )
        total = count_result.scalar() or 0

        offset = (page - 1) * size
        params["limit"] = size
        params["offset"] = offset

        result = await db.execute(
            text(
                f"SELECT al.id, al.user_id, al.action, al.resource_type, "
                f"       al.resource_id, al.ip_address, al.user_agent, "
                f"       al.created_at, al.details "
                f"FROM audit_logs al "
                f"WHERE {where_clause} "
                f"ORDER BY al.created_at DESC "
                f"LIMIT :limit OFFSET :offset"
            ),
            params,
        )
        rows = result.mappings().fetchall()
    except SQLAlchemyError as exc:
        log.error("list_audit_logs_db_error", error=str(exc), exc_info=True)
        return _ok({"items": [], "total": 0, "page": page, "size": size, "_db_error": True})

    items = []
    for row in rows:
        d = _row_to_dict(row)
        details = d.get("details") or {}
        if isinstance(details, str):
            import json

            try:
                details = json.loads(details)
            except (ValueError, TypeError):
                details = {}
        items.append(
            {
                "id": d["id"],
                "time": d.get("created_at"),
                "user_id": d.get("user_id"),
                "action": d.get("action", ""),
                "resource_type": d.get("resource_type", ""),
                "resource_id": d.get("resource_id"),
                "ip": d.get("ip_address", ""),
                "user_agent": d.get("user_agent", ""),
                "detail": details,
            }
        )

    log.info("audit_logs_listed", tenant_id=tenant_id, total=total, page=page)
    return _ok({"items": items, "total": total, "page": page, "size": size})
