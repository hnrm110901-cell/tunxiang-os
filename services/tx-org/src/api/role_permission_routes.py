"""角色权限管理 API — 接入真实 DB（role_configs 表）

端点列表（prefix=/api/v1/org）：
  GET    /permissions/tree        — 权限树（静态配置）
  GET    /roles-admin             — 角色列表（来自 role_configs DB）
  POST   /roles-admin             — 创建角色（写入 role_configs DB）
  PATCH  /roles-admin/{role_id}   — 更新角色权限（写入 role_configs DB）
  DELETE /roles-admin/{role_id}   — 删除角色（软删除 role_configs）
  GET    /user-roles              — 用户角色列表（graceful fallback 内存数据）
  PATCH  /user-roles/{user_id}    — 更新用户角色（graceful fallback）
  POST   /user-roles/batch        — 批量设置用户角色（graceful fallback）
  GET    /audit-logs              — 操作日志（graceful fallback 内存数据）

DB 失败时：列表类端点返回空集合，不返回 500。
所有接口需 X-Tenant-ID header（user-roles/audit-logs 端点除外，保持前向兼容）。

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
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

ALL_PERM_KEYS = [
    child["key"]
    for group in PERMISSION_TREE
    for child in group["children"]
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  用户角色/审计日志：内存 fallback（role_configs 无 user 关联表）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_MOCK_USERS: list[dict] = [
    {"id": "u-001", "name": "张伟", "phone": "138****1234", "store": "旗舰店", "roles": ["超级管理员"], "last_login": "2026-04-02 09:30:00", "status": "active"},
    {"id": "u-002", "name": "李娜", "phone": "139****5678", "store": "万达店", "roles": ["品牌经理"], "last_login": "2026-04-02 08:15:00", "status": "active"},
    {"id": "u-003", "name": "王芳", "phone": "136****9012", "store": "步行街店", "roles": ["店长"], "last_login": "2026-04-01 18:20:00", "status": "active"},
    {"id": "u-004", "name": "赵敏", "phone": "137****3456", "store": "大学城店", "roles": ["收银员"], "last_login": "2026-04-02 07:55:00", "status": "active"},
    {"id": "u-005", "name": "刘洋", "phone": "135****7890", "store": "旗舰店", "roles": ["区域经理"], "last_login": "2026-04-01 17:00:00", "status": "active"},
]

_now = datetime.now()
_MOCK_AUDIT_LOGS: list[dict] = [
    {"id": "log-001", "time": (_now - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S"), "operator": "张伟", "action": "修改权限", "target": "品牌经理", "ip": "192.168.1.100", "detail": "新增营销管理-审批权限"},
    {"id": "log-002", "time": (_now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"), "operator": "张伟", "action": "登录", "target": "系统", "ip": "192.168.1.100", "detail": "总部后台登录成功"},
    {"id": "log-003", "time": (_now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"), "operator": "李娜", "action": "修改权限", "target": "区域经理", "ip": "10.0.0.55", "detail": "新增供应链-新增权限"},
    {"id": "log-004", "time": (_now - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S"), "operator": "张伟", "action": "删除", "target": "临时活动角色", "ip": "192.168.1.100", "detail": "删除自定义角色：临时活动角色"},
    {"id": "log-005", "time": (_now - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S"), "operator": "李娜", "action": "审批", "target": "门店折扣申请#2046", "ip": "10.0.0.55", "detail": "审批通过，折扣率85%"},
]


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
    tid = getattr(request.state, "tenant_id", None) or request.headers.get(
        "X-Tenant-ID", ""
    )
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
        items.append({
            "id": d["id"],
            "name": d.get("role_name", ""),
            "code": d.get("role_code", ""),
            "level": d.get("level", 5),
            "is_preset": False,
            "status": "active",
            "permissions": perms,
            "permission_count": len(perms),
            "created_at": d.get("created_at"),
        })

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
    return _ok({
        "id": d["id"],
        "name": d.get("role_name", ""),
        "code": d.get("role_code", ""),
        "level": d.get("level", 5),
        "permissions": perms,
        "permission_count": len(perms),
        "updated_at": d.get("updated_at"),
    })


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
#  端点 — 用户角色（内存 fallback，待 employee_role_assignments 完整对接后替换）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/user-roles")
async def list_user_roles(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    keyword: str = Query(default=""),
) -> dict:
    """GET /api/v1/org/user-roles — 用户角色列表（内存 fallback）"""
    filtered = _MOCK_USERS
    if keyword:
        filtered = [u for u in _MOCK_USERS if keyword in u["name"] or keyword in u["phone"]]
    total = len(filtered)
    start = (page - 1) * size
    items = filtered[start: start + size]
    return _ok({"items": items, "total": total, "page": page, "size": size})


@router.patch("/user-roles/{user_id}")
async def update_user_roles(user_id: str, req: UpdateUserRolesReq) -> dict:
    """PATCH /api/v1/org/user-roles/{user_id} — 更新用户角色（内存 fallback）"""
    for u in _MOCK_USERS:
        if u["id"] == user_id:
            u["roles"] = req.roles
            log.info("user_roles_updated", user_id=user_id, roles=req.roles)
            return _ok({"id": u["id"], "name": u["name"], "roles": u["roles"]})
    return _err(f"用户 {user_id} 不存在", 404)


@router.post("/user-roles/batch")
async def batch_set_user_roles(req: BatchUserRolesReq) -> dict:
    """POST /api/v1/org/user-roles/batch — 批量设置用户角色（内存 fallback）"""
    updated_ids = []
    for u in _MOCK_USERS:
        if u["id"] in req.user_ids:
            u["roles"] = req.roles
            updated_ids.append(u["id"])
    log.info("batch_roles_set", count=len(updated_ids), roles=req.roles)
    return _ok({"updated_count": len(updated_ids), "user_ids": updated_ids})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点 — 操作日志（内存 fallback，待 audit_logs 表建立后接入）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/audit-logs")
async def list_audit_logs(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    keyword: str = Query(default=""),
    action: str = Query(default=""),
    start_time: str = Query(default=""),
    end_time: str = Query(default=""),
) -> dict:
    """GET /api/v1/org/audit-logs — 操作日志列表（内存 fallback）"""
    filtered = list(_MOCK_AUDIT_LOGS)
    if keyword:
        filtered = [
            log_item for log_item in filtered
            if keyword in log_item["operator"] or keyword in log_item.get("target", "")
        ]
    if action:
        filtered = [log_item for log_item in filtered if log_item["action"] == action]
    if start_time:
        filtered = [log_item for log_item in filtered if log_item["time"] >= start_time]
    if end_time:
        filtered = [log_item for log_item in filtered if log_item["time"] <= end_time]
    total = len(filtered)
    start = (page - 1) * size
    items = filtered[start: start + size]
    return _ok({"items": items, "total": total, "page": page, "size": size})
