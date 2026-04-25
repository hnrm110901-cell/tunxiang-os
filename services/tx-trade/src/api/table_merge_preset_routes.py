"""时段拼桌预设 API — 预设管理/手动执行/回滚/日志查询

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

import json
import uuid
from typing import Optional

import sqlalchemy as sa
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.table_merge_preset_service import TableMergePresetService

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/table-presets", tags=["table-presets"])


# ─── 工具函数 ───


def _get_tenant_id(request: Request) -> uuid.UUID:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return uuid.UUID(str(tid))


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> dict:
    raise HTTPException(
        status_code=code,
        detail={"ok": False, "data": None, "error": {"message": msg}},
    )


# ─── 请求模型 ───


class MergeRuleItem(BaseModel):
    group_name: str = Field(..., description="分组名称，如 A1+A2大桌")
    table_nos: list[str] = Field(..., min_length=2, description="参与拼桌的桌号列表")
    effective_seats: int = Field(..., ge=1, description="拼桌后有效座位数")
    target_scene: str = Field(default="", description="目标场景：聚餐/快翻等")


class CreatePresetReq(BaseModel):
    store_id: uuid.UUID
    preset_name: str = Field(..., max_length=50, description="方案名称")
    market_session_id: Optional[uuid.UUID] = Field(
        default=None,
        description="关联市别ID（NULL=仅手动触发）",
    )
    merge_rules: list[MergeRuleItem] = Field(..., min_length=1)
    auto_trigger: bool = Field(default=False, description="市别切换时是否自动执行")
    priority: int = Field(default=0, description="同市别多方案时优先级")


class UpdatePresetReq(BaseModel):
    preset_name: Optional[str] = Field(default=None, max_length=50)
    market_session_id: Optional[uuid.UUID] = None
    merge_rules: Optional[list[MergeRuleItem]] = None
    auto_trigger: Optional[bool] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None


# ─── 1. 列出门店所有拼桌预设 ───


@router.get("/{store_id}")
async def list_presets(
    store_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """列出门店所有拼桌预设（不含已删除）"""
    tenant_id = _get_tenant_id(request)
    rows = (
        (
            await db.execute(
                sa.text(
                    "SELECT id, store_id, preset_name, market_session_id, "
                    "merge_rules, auto_trigger, priority, is_active, "
                    "created_at, updated_at "
                    "FROM table_merge_presets "
                    "WHERE store_id = :sid AND tenant_id = :tid AND is_deleted = FALSE "
                    "ORDER BY priority DESC, created_at DESC"
                ),
                {"sid": str(store_id), "tid": str(tenant_id)},
            )
        )
        .mappings()
        .all()
    )

    items = [
        {
            "id": str(r["id"]),
            "store_id": str(r["store_id"]),
            "preset_name": r["preset_name"],
            "market_session_id": str(r["market_session_id"]) if r["market_session_id"] else None,
            "merge_rules": r["merge_rules"],
            "auto_trigger": r["auto_trigger"],
            "priority": r["priority"],
            "is_active": r["is_active"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        for r in rows
    ]
    return _ok(items)


# ─── 2. 创建预设 ───


@router.post("")
async def create_preset(
    req: CreatePresetReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """创建拼桌预设"""
    tenant_id = _get_tenant_id(request)
    preset_id = str(uuid.uuid4())
    rules_json = json.dumps(
        [r.model_dump() for r in req.merge_rules],
        ensure_ascii=False,
    )

    await db.execute(
        sa.text(
            "INSERT INTO table_merge_presets "
            "(id, tenant_id, store_id, preset_name, market_session_id, "
            "merge_rules, auto_trigger, priority) "
            "VALUES (:id, :tid, :sid, :name, :msid, :rules::jsonb, :at, :pri)"
        ),
        {
            "id": preset_id,
            "tid": str(tenant_id),
            "sid": str(req.store_id),
            "name": req.preset_name,
            "msid": str(req.market_session_id) if req.market_session_id else None,
            "rules": rules_json,
            "at": req.auto_trigger,
            "pri": req.priority,
        },
    )
    await db.commit()

    logger.info(
        "preset_created",
        preset_id=preset_id,
        store_id=str(req.store_id),
        tenant_id=str(tenant_id),
    )
    return _ok({"id": preset_id})


# ─── 3. 修改预设 ───


@router.put("/{preset_id}")
async def update_preset(
    preset_id: uuid.UUID,
    req: UpdatePresetReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """修改拼桌预设"""
    tenant_id = _get_tenant_id(request)

    # 构建动态 SET 子句
    set_parts: list[str] = []
    params: dict = {
        "pid": str(preset_id),
        "tid": str(tenant_id),
    }

    if req.preset_name is not None:
        set_parts.append("preset_name = :name")
        params["name"] = req.preset_name
    if req.market_session_id is not None:
        set_parts.append("market_session_id = :msid")
        params["msid"] = str(req.market_session_id)
    if req.merge_rules is not None:
        set_parts.append("merge_rules = :rules::jsonb")
        params["rules"] = json.dumps(
            [r.model_dump() for r in req.merge_rules],
            ensure_ascii=False,
        )
    if req.auto_trigger is not None:
        set_parts.append("auto_trigger = :at")
        params["at"] = req.auto_trigger
    if req.priority is not None:
        set_parts.append("priority = :pri")
        params["pri"] = req.priority
    if req.is_active is not None:
        set_parts.append("is_active = :active")
        params["active"] = req.is_active

    if not set_parts:
        _err("无更新字段")

    set_parts.append("updated_at = NOW()")
    set_clause = ", ".join(set_parts)

    result = await db.execute(
        sa.text(
            f"UPDATE table_merge_presets SET {set_clause} WHERE id = :pid AND tenant_id = :tid AND is_deleted = FALSE"
        ),
        params,
    )

    if result.rowcount == 0:
        _err("预设不存在", 404)

    await db.commit()
    return _ok({"id": str(preset_id), "updated": True})


# ─── 4. 软删除预设 ───


@router.delete("/{preset_id}")
async def delete_preset(
    preset_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """软删除拼桌预设"""
    tenant_id = _get_tenant_id(request)

    result = await db.execute(
        sa.text(
            "UPDATE table_merge_presets "
            "SET is_deleted = TRUE, is_active = FALSE, updated_at = NOW() "
            "WHERE id = :pid AND tenant_id = :tid AND is_deleted = FALSE"
        ),
        {"pid": str(preset_id), "tid": str(tenant_id)},
    )

    if result.rowcount == 0:
        _err("预设不存在", 404)

    await db.commit()
    return _ok({"id": str(preset_id), "deleted": True})


# ─── 5. 手动执行预设 ───


@router.post("/{preset_id}/execute")
async def execute_preset(
    preset_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """手动执行拼桌预设

    逐组检查桌台状态：
    - 所有桌台 free → 执行合并
    - 有桌台 occupied → 跳过该组（不打断用餐客人）
    """
    tenant_id = _get_tenant_id(request)
    operator_id_str = request.headers.get("X-Operator-ID")
    operator_id = uuid.UUID(operator_id_str) if operator_id_str else None

    svc = TableMergePresetService(db, str(tenant_id))
    try:
        result = await svc.execute_preset(
            preset_id=preset_id,
            triggered_by="manual",
            operator_id=operator_id,
        )
        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── 6. 手动回滚 ───


@router.post("/{preset_id}/rollback")
async def rollback_preset(
    preset_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """回滚拼桌执行 — 将合并的桌台恢复为 free

    注意：preset_id 此处实际为 log_id（执行日志ID），
    因为回滚针对的是某次具体执行，而非预设本身。
    """
    tenant_id = _get_tenant_id(request)
    svc = TableMergePresetService(db, str(tenant_id))
    try:
        result = await svc.rollback_log(log_id=preset_id)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── 7. 执行日志查询 ───


@router.get("/logs/{store_id}")
async def list_logs(
    store_id: uuid.UUID,
    request: Request,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """查询门店拼桌执行日志"""
    tenant_id = _get_tenant_id(request)
    offset = (page - 1) * size

    # 总数
    total_row = (
        await db.execute(
            sa.text("SELECT COUNT(*) FROM table_merge_logs WHERE store_id = :sid AND tenant_id = :tid"),
            {"sid": str(store_id), "tid": str(tenant_id)},
        )
    ).scalar()

    # 分页数据
    rows = (
        (
            await db.execute(
                sa.text(
                    "SELECT id, preset_id, trigger_type, market_session_id, "
                    "executed_merges, skipped_merges, executed_at, "
                    "executed_by, rollback_at, created_at "
                    "FROM table_merge_logs "
                    "WHERE store_id = :sid AND tenant_id = :tid "
                    "ORDER BY executed_at DESC "
                    "LIMIT :lim OFFSET :off"
                ),
                {
                    "sid": str(store_id),
                    "tid": str(tenant_id),
                    "lim": size,
                    "off": offset,
                },
            )
        )
        .mappings()
        .all()
    )

    items = [
        {
            "id": str(r["id"]),
            "preset_id": str(r["preset_id"]) if r["preset_id"] else None,
            "trigger_type": r["trigger_type"],
            "market_session_id": str(r["market_session_id"]) if r["market_session_id"] else None,
            "executed_merges": r["executed_merges"],
            "skipped_merges": r["skipped_merges"],
            "executed_at": r["executed_at"].isoformat() if r["executed_at"] else None,
            "executed_by": str(r["executed_by"]) if r["executed_by"] else None,
            "rollback_at": r["rollback_at"].isoformat() if r["rollback_at"] else None,
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]

    return _ok({"items": items, "total": total_row})
