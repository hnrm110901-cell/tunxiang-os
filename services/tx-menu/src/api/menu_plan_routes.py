"""菜谱方案批量下发与门店差异化 — 模块3.4

新端点（在 scheme_routes.py 已有基础上扩展）：

  # 菜谱方案版本管理
  GET  /api/v1/menu/plans/{id}/versions           — 版本历史列表
  POST /api/v1/menu/plans/{id}/versions           — 手动创建版本快照
  POST /api/v1/menu/plans/{id}/rollback/{ver}     — 回滚到指定版本
  GET  /api/v1/menu/plans/{id}/distribute-log     — 下发日志（门店/时间/状态）

  # 门店菜谱差异化（补充 scheme_routes.py 未覆盖的接口）
  GET  /api/v1/menu/store/{store_id}/overrides        — 覆盖配置列表
  PUT  /api/v1/menu/store/{store_id}/overrides        — 批量 UPSERT 覆盖
  POST /api/v1/menu/store/{store_id}/reset            — 重置为集团方案（清空所有覆盖）
  GET  /api/v1/menu/store/{store_id}/pending-updates  — 待更新通知

  # 菜品分组批量操作
  POST /api/v1/menu/categories/reorder    — 分类拖拽排序
  POST /api/v1/menu/items/batch-toggle    — 批量启用/禁用
  POST /api/v1/menu/items/batch-assign    — 批量指定分类

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。

事件总线：
  - 回滚操作发射 MenuEventType.PLAN_ROLLED_BACK
  - 下发操作发射 MenuEventType.PLAN_DISTRIBUTED（扩展现有 scheme_routes distribute 端点）
  - 重置覆盖发射 MenuEventType.STORE_OVERRIDE_RESET
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from shared.events.src.emitter import emit_event
from shared.events.src.event_types import MenuEventType

log = structlog.get_logger(__name__)

router = APIRouter(tags=["menu-plan-v245"])


# ─── 辅助 ────────────────────────────────────────────────────────────────────


def _err(status: int, msg: str):
    raise HTTPException(
        status_code=status,
        detail={"ok": False, "error": {"message": msg}},
    )


async def _set_tenant(db: AsyncSession, tenant_id: str) -> uuid.UUID:
    """设置 RLS session 变量并返回 UUID。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )
    try:
        return uuid.UUID(tenant_id)
    except ValueError:
        _err(400, f"无效的 tenant_id: {tenant_id}")


async def _fetch_scheme(db: AsyncSession, sid: uuid.UUID, tid: uuid.UUID) -> dict:
    """查询方案基本信息，不存在则 404。"""
    res = await db.execute(
        text("""
            SELECT id, name, status, published_at
            FROM menu_schemes
            WHERE id = :sid AND tenant_id = :tid AND is_deleted IS NOT TRUE
        """),
        {"sid": sid, "tid": tid},
    )
    row = res.fetchone()
    if not row:
        _err(404, "方案不存在")
    return {"id": str(row[0]), "name": row[1], "status": row[2], "published_at": row[3]}


# ─── Pydantic 模型 ────────────────────────────────────────────────────────────


class CreateVersionReq(BaseModel):
    change_summary: Optional[str] = Field(None, max_length=500, description="变更摘要")


class StoreOverrideBatchItem(BaseModel):
    dish_id: str = Field(..., description="菜品 ID")
    scheme_id: str = Field(..., description="关联方案 ID")
    override_price_fen: Optional[int] = Field(None, ge=0, description="覆盖价格（分）")
    override_available: Optional[bool] = Field(None, description="覆盖可售状态")


class BatchStoreOverrideReq(BaseModel):
    items: list[StoreOverrideBatchItem] = Field(..., min_length=1)


class CategoryReorderItem(BaseModel):
    category_id: str = Field(..., description="分类 ID")
    sort_order: int = Field(..., ge=0)


class CategoryReorderReq(BaseModel):
    items: list[CategoryReorderItem] = Field(..., min_length=1)


class BatchToggleReq(BaseModel):
    dish_ids: list[str] = Field(..., min_length=1, description="菜品 ID 列表")
    scheme_id: str = Field(..., description="方案 ID（操作范围限定在此方案内）")
    is_available: bool = Field(..., description="True=启用 / False=禁用")


class BatchAssignReq(BaseModel):
    dish_ids: list[str] = Field(..., min_length=1, description="菜品 ID 列表")
    category_id: str = Field(..., description="目标分类 ID")


# ══════════════════════════════════════════════════════════════════════════════
# 版本管理
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/api/v1/menu/plans/{plan_id}/versions")
async def list_plan_versions(
    plan_id: str = Path(...),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """方案版本历史列表（按版本号降序）。"""
    tid = await _set_tenant(db, x_tenant_id)
    try:
        sid = uuid.UUID(plan_id)
    except ValueError:
        _err(400, "无效的 plan_id")

    await _fetch_scheme(db, sid, tid)

    count_res = await db.execute(
        text("SELECT COUNT(*) FROM menu_plan_versions WHERE scheme_id = :sid AND tenant_id = :tid"),
        {"sid": sid, "tid": tid},
    )
    total = count_res.scalar() or 0

    rows = await db.execute(
        text("""
            SELECT id, version_number, change_summary, published_by, created_at,
                   jsonb_array_length(snapshot_json) AS item_count
            FROM menu_plan_versions
            WHERE scheme_id = :sid AND tenant_id = :tid
            ORDER BY version_number DESC
            LIMIT :limit OFFSET :offset
        """),
        {"sid": sid, "tid": tid, "limit": size, "offset": (page - 1) * size},
    )
    items = [
        {
            "id": str(r[0]),
            "version_number": r[1],
            "change_summary": r[2],
            "published_by": r[3],
            "created_at": r[4].isoformat() if r[4] else None,
            "item_count": r[5] or 0,
        }
        for r in rows.fetchall()
    ]
    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}


@router.post("/api/v1/menu/plans/{plan_id}/versions", status_code=201)
async def create_plan_version(
    req: CreateVersionReq,
    plan_id: str = Path(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator: Optional[str] = Header(None, alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
):
    """手动为已发布方案创建版本快照（快照当前所有菜品条目）。"""
    tid = await _set_tenant(db, x_tenant_id)
    try:
        sid = uuid.UUID(plan_id)
    except ValueError:
        _err(400, "无效的 plan_id")

    scheme = await _fetch_scheme(db, sid, tid)
    if scheme["status"] not in ("published",):
        _err(400, "只有已发布方案可以创建版本快照")

    # 获取当前最大版本号
    max_ver_res = await db.execute(
        text("""
            SELECT COALESCE(MAX(version_number), 0) FROM menu_plan_versions
            WHERE scheme_id = :sid AND tenant_id = :tid
        """),
        {"sid": sid, "tid": tid},
    )
    next_ver = (max_ver_res.scalar() or 0) + 1

    # 生成菜品快照
    items_res = await db.execute(
        text("""
            SELECT jsonb_agg(jsonb_build_object(
                'dish_id', dish_id::text,
                'price_fen', price_fen,
                'is_available', is_available,
                'sort_order', sort_order,
                'notes', notes
            ) ORDER BY sort_order)
            FROM menu_scheme_items
            WHERE scheme_id = :sid AND tenant_id = :tid
        """),
        {"sid": sid, "tid": tid},
    )
    snapshot = items_res.scalar() or "[]"

    result = await db.execute(
        text("""
            INSERT INTO menu_plan_versions
              (tenant_id, scheme_id, version_number, change_summary, snapshot_json, published_by)
            VALUES (:tid, :sid, :ver, :summary, :snapshot::jsonb, :operator)
            RETURNING id, version_number, created_at
        """),
        {
            "tid": tid,
            "sid": sid,
            "ver": next_ver,
            "summary": req.change_summary,
            "snapshot": snapshot if isinstance(snapshot, str) else "[]",
            "operator": x_operator,
        },
    )
    await db.commit()
    row = result.fetchone()
    log.info("menu_plan_version.created", plan_id=plan_id, version=next_ver, tenant_id=x_tenant_id)
    return {
        "ok": True,
        "data": {
            "id": str(row[0]),
            "version_number": row[1],
            "created_at": row[2].isoformat() if row[2] else None,
        },
    }


@router.post("/api/v1/menu/plans/{plan_id}/rollback/{version_number}")
async def rollback_plan_version(
    plan_id: str = Path(...),
    version_number: int = Path(..., ge=1),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator: Optional[str] = Header(None, alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
):
    """回滚方案到指定版本快照（替换当前所有 menu_scheme_items）。"""
    tid = await _set_tenant(db, x_tenant_id)
    try:
        sid = uuid.UUID(plan_id)
    except ValueError:
        _err(400, "无效的 plan_id")

    await _fetch_scheme(db, sid, tid)

    ver_res = await db.execute(
        text("""
            SELECT id, snapshot_json FROM menu_plan_versions
            WHERE scheme_id = :sid AND version_number = :ver AND tenant_id = :tid
        """),
        {"sid": sid, "ver": version_number, "tid": tid},
    )
    ver_row = ver_res.fetchone()
    if not ver_row:
        _err(404, f"版本 {version_number} 不存在")

    snapshot: list = ver_row[1] if ver_row[1] else []

    # 删除当前所有条目，重新插入快照数据
    await db.execute(
        text("DELETE FROM menu_scheme_items WHERE scheme_id = :sid AND tenant_id = :tid"),
        {"sid": sid, "tid": tid},
    )
    for item in snapshot:
        try:
            dish_uuid = uuid.UUID(str(item.get("dish_id", "")))
        except ValueError:
            log.warning("rollback.invalid_dish_id", dish_id=item.get("dish_id"))
            continue
        await db.execute(
            text("""
                INSERT INTO menu_scheme_items
                  (tenant_id, scheme_id, dish_id, price_fen, is_available, sort_order, notes)
                VALUES (:tid, :sid, :dish_id, :price_fen, :is_available, :sort_order, :notes)
                ON CONFLICT (scheme_id, dish_id) DO UPDATE SET
                  price_fen    = EXCLUDED.price_fen,
                  is_available = EXCLUDED.is_available,
                  sort_order   = EXCLUDED.sort_order,
                  notes        = EXCLUDED.notes
            """),
            {
                "tid": tid,
                "sid": sid,
                "dish_id": dish_uuid,
                "price_fen": item.get("price_fen"),
                "is_available": item.get("is_available", True),
                "sort_order": item.get("sort_order", 0),
                "notes": item.get("notes"),
            },
        )

    await db.execute(
        text("UPDATE menu_schemes SET updated_at = now() WHERE id = :sid AND tenant_id = :tid"),
        {"sid": sid, "tid": tid},
    )
    await db.commit()
    log.info("menu_plan.rolled_back", plan_id=plan_id, version=version_number, tenant_id=x_tenant_id)

    asyncio.create_task(emit_event(
        event_type=MenuEventType.PLAN_ROLLED_BACK,
        tenant_id=tid,
        stream_id=plan_id,
        payload={"version_number": version_number, "operator": x_operator},
        source_service="tx-menu",
        metadata={"operator_id": x_operator or ""},
    ))

    return {
        "ok": True,
        "data": {
            "plan_id": plan_id,
            "rolled_back_to_version": version_number,
            "items_restored": len(snapshot),
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# 下发日志
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/api/v1/menu/plans/{plan_id}/distribute-log")
async def get_distribute_log(
    plan_id: str = Path(...),
    store_id: Optional[str] = Query(None, description="按门店过滤"),
    status: Optional[str] = Query(None, pattern="^(success|failed|pending)$"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """方案下发日志（门店 / 时间 / 状态，支持过滤）。"""
    tid = await _set_tenant(db, x_tenant_id)
    try:
        sid = uuid.UUID(plan_id)
    except ValueError:
        _err(400, "无效的 plan_id")

    where = "WHERE scheme_id = :sid AND tenant_id = :tid"
    params: dict = {"sid": sid, "tid": tid}

    if store_id:
        try:
            params["store_id"] = uuid.UUID(store_id)
        except ValueError:
            _err(400, "无效的 store_id")
        where += " AND store_id = :store_id"
    if status:
        where += " AND status = :status"
        params["status"] = status

    count_res = await db.execute(
        text(f"SELECT COUNT(*) FROM menu_distribute_log {where}"), params
    )
    total = count_res.scalar() or 0

    params["limit"] = size
    params["offset"] = (page - 1) * size
    rows = await db.execute(
        text(f"""
            SELECT id, store_id, version_number, status, error_message,
                   distributed_by, distributed_at
            FROM menu_distribute_log
            {where}
            ORDER BY distributed_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items = [
        {
            "id": str(r[0]),
            "store_id": str(r[1]),
            "version_number": r[2],
            "status": r[3],
            "error_message": r[4],
            "distributed_by": r[5],
            "distributed_at": r[6].isoformat() if r[6] else None,
        }
        for r in rows.fetchall()
    ]
    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}


# ══════════════════════════════════════════════════════════════════════════════
# 门店差异化 — 覆盖配置
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/api/v1/menu/store/{store_id}/overrides")
async def list_store_overrides(
    store_id: str = Path(...),
    scheme_id: Optional[str] = Query(None, description="按方案过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """门店覆盖配置列表（价格/可售状态已覆盖的菜品）。"""
    tid = await _set_tenant(db, x_tenant_id)
    try:
        store_uuid = uuid.UUID(store_id)
    except ValueError:
        _err(400, "无效的 store_id")

    where = "WHERE smo.store_id = :store_id AND smo.tenant_id = :tid"
    params: dict = {"store_id": store_uuid, "tid": tid}

    if scheme_id:
        try:
            params["scheme_id"] = uuid.UUID(scheme_id)
        except ValueError:
            _err(400, "无效的 scheme_id")
        where += " AND smo.scheme_id = :scheme_id"

    count_res = await db.execute(
        text(f"SELECT COUNT(*) FROM store_menu_overrides smo {where}"), params
    )
    total = count_res.scalar() or 0

    params["limit"] = size
    params["offset"] = (page - 1) * size
    rows = await db.execute(
        text(f"""
            SELECT smo.id, smo.dish_id, d.dish_name, smo.scheme_id,
                   smo.override_price_fen, smo.override_available,
                   msi.price_fen AS scheme_price_fen, msi.is_available AS scheme_available,
                   smo.updated_at
            FROM store_menu_overrides smo
            LEFT JOIN dishes d ON d.id = smo.dish_id
            LEFT JOIN menu_scheme_items msi
              ON msi.dish_id = smo.dish_id AND msi.scheme_id = smo.scheme_id
            {where}
            ORDER BY smo.updated_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items = [
        {
            "id": str(r[0]),
            "dish_id": str(r[1]),
            "dish_name": r[2],
            "scheme_id": str(r[3]),
            "override_price_fen": r[4],
            "override_available": r[5],
            "scheme_price_fen": r[6],
            "scheme_available": r[7],
            "updated_at": r[8].isoformat() if r[8] else None,
        }
        for r in rows.fetchall()
    ]
    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}


@router.put("/api/v1/menu/store/{store_id}/overrides", status_code=200)
async def batch_upsert_store_overrides(
    req: BatchStoreOverrideReq,
    store_id: str = Path(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator: Optional[str] = Header(None, alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
):
    """批量 UPSERT 门店菜品覆盖（价格/可售状态微调）。"""
    tid = await _set_tenant(db, x_tenant_id)
    try:
        store_uuid = uuid.UUID(store_id)
    except ValueError:
        _err(400, "无效的 store_id")

    upserted = 0
    for item in req.items:
        try:
            dish_uuid = uuid.UUID(item.dish_id)
            scheme_uuid = uuid.UUID(item.scheme_id)
        except ValueError as exc:
            log.warning("batch_override.invalid_uuid", error=str(exc))
            continue

        await db.execute(
            text("""
                INSERT INTO store_menu_overrides
                  (tenant_id, store_id, dish_id, scheme_id,
                   override_price_fen, override_available, updated_at)
                VALUES (:tid, :store_id, :dish_id, :sid, :price, :available, now())
                ON CONFLICT (store_id, dish_id, scheme_id)
                DO UPDATE SET
                  override_price_fen = EXCLUDED.override_price_fen,
                  override_available = EXCLUDED.override_available,
                  updated_at         = now()
            """),
            {
                "tid": tid,
                "store_id": store_uuid,
                "dish_id": dish_uuid,
                "sid": scheme_uuid,
                "price": item.override_price_fen,
                "available": item.override_available,
            },
        )
        upserted += 1

    await db.commit()
    log.info("store_menu.batch_override", store_id=store_id, count=upserted, tenant_id=x_tenant_id)

    asyncio.create_task(emit_event(
        event_type=MenuEventType.STORE_OVERRIDE_SET,
        tenant_id=tid,
        stream_id=store_id,
        payload={"store_id": store_id, "upserted_count": upserted, "operator": x_operator},
        store_id=store_id,
        source_service="tx-menu",
        metadata={"operator_id": x_operator or ""},
    ))

    return {"ok": True, "data": {"store_id": store_id, "upserted_count": upserted}}


@router.post("/api/v1/menu/store/{store_id}/reset")
async def reset_store_overrides(
    store_id: str = Path(...),
    scheme_id: Optional[str] = Query(None, description="仅重置此方案的覆盖，NULL=重置所有"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator: Optional[str] = Header(None, alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
):
    """重置门店为集团方案：删除该门店所有（或指定方案的）覆盖配置。"""
    tid = await _set_tenant(db, x_tenant_id)
    try:
        store_uuid = uuid.UUID(store_id)
    except ValueError:
        _err(400, "无效的 store_id")

    params: dict = {"store_id": store_uuid, "tid": tid}
    extra_where = ""
    if scheme_id:
        try:
            params["scheme_id"] = uuid.UUID(scheme_id)
        except ValueError:
            _err(400, "无效的 scheme_id")
        extra_where = " AND scheme_id = :scheme_id"

    result = await db.execute(
        text(f"""
            DELETE FROM store_menu_overrides
            WHERE store_id = :store_id AND tenant_id = :tid{extra_where}
        """),
        params,
    )
    await db.commit()
    deleted_count = result.rowcount
    log.info("store_menu.reset", store_id=store_id, deleted=deleted_count, tenant_id=x_tenant_id)

    asyncio.create_task(emit_event(
        event_type=MenuEventType.STORE_OVERRIDE_RESET,
        tenant_id=tid,
        stream_id=store_id,
        payload={"store_id": store_id, "deleted_count": deleted_count, "scheme_id": scheme_id},
        store_id=store_id,
        source_service="tx-menu",
        metadata={"operator_id": x_operator or ""},
    ))

    return {"ok": True, "data": {"store_id": store_id, "deleted_override_count": deleted_count}}


@router.get("/api/v1/menu/store/{store_id}/pending-updates")
async def get_pending_updates(
    store_id: str = Path(...),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """门店待处理通知：已下发新版本但门店尚未确认/应用的方案列表。

    判断逻辑：store_scheme_assignments 中 distributed_at > store_confirmed_at（或门店从未确认）。
    注意：store_scheme_assignments 表无 confirmed_at 字段时退化为返回全部最近下发记录。
    """
    tid = await _set_tenant(db, x_tenant_id)
    try:
        store_uuid = uuid.UUID(store_id)
    except ValueError:
        _err(400, "无效的 store_id")

    # 查询最近 7 天内下发但尚未确认的记录（从 distribute_log 查 pending 状态）
    count_res = await db.execute(
        text("""
            SELECT COUNT(*) FROM menu_distribute_log
            WHERE store_id = :store_id AND tenant_id = :tid AND status = 'pending'
        """),
        {"store_id": store_uuid, "tid": tid},
    )
    total = count_res.scalar() or 0

    rows = await db.execute(
        text("""
            SELECT dl.id, dl.scheme_id, ms.name AS scheme_name, dl.version_number,
                   dl.distributed_at, dl.distributed_by
            FROM menu_distribute_log dl
            LEFT JOIN menu_schemes ms ON ms.id = dl.scheme_id
            WHERE dl.store_id = :store_id AND dl.tenant_id = :tid AND dl.status = 'pending'
            ORDER BY dl.distributed_at DESC
            LIMIT :limit OFFSET :offset
        """),
        {"store_id": store_uuid, "tid": tid, "limit": size, "offset": (page - 1) * size},
    )
    items = [
        {
            "log_id": str(r[0]),
            "scheme_id": str(r[1]),
            "scheme_name": r[2],
            "version_number": r[3],
            "distributed_at": r[4].isoformat() if r[4] else None,
            "distributed_by": r[5],
        }
        for r in rows.fetchall()
    ]
    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}


# ══════════════════════════════════════════════════════════════════════════════
# 菜品分组批量操作
# ══════════════════════════════════════════════════════════════════════════════


@router.post("/api/v1/menu/categories/reorder")
async def reorder_categories(
    req: CategoryReorderReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """分类拖拽排序：批量更新 dish_categories 的 sort_order。"""
    tid = await _set_tenant(db, x_tenant_id)
    updated = 0
    for item in req.items:
        try:
            cat_uuid = uuid.UUID(item.category_id)
        except ValueError:
            log.warning("reorder_categories.invalid_id", category_id=item.category_id)
            continue
        result = await db.execute(
            text("""
                UPDATE dish_categories
                SET sort_order = :sort_order, updated_at = now()
                WHERE id = :cat_id AND tenant_id = :tid
            """),
            {"sort_order": item.sort_order, "cat_id": cat_uuid, "tid": tid},
        )
        if result.rowcount > 0:
            updated += 1

    await db.commit()
    log.info("categories.reordered", count=updated, tenant_id=x_tenant_id)
    return {"ok": True, "data": {"updated_count": updated}}


@router.post("/api/v1/menu/items/batch-toggle")
async def batch_toggle_items(
    req: BatchToggleReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """批量启用/禁用方案内菜品（修改 menu_scheme_items.is_available）。"""
    tid = await _set_tenant(db, x_tenant_id)
    try:
        sid = uuid.UUID(req.scheme_id)
    except ValueError:
        _err(400, "无效的 scheme_id")

    updated = 0
    for dish_id_str in req.dish_ids:
        try:
            dish_uuid = uuid.UUID(dish_id_str)
        except ValueError:
            log.warning("batch_toggle.invalid_dish_id", dish_id=dish_id_str)
            continue
        result = await db.execute(
            text("""
                UPDATE menu_scheme_items
                SET is_available = :is_available
                WHERE scheme_id = :sid AND dish_id = :dish_id AND tenant_id = :tid
            """),
            {"is_available": req.is_available, "sid": sid, "dish_id": dish_uuid, "tid": tid},
        )
        if result.rowcount > 0:
            updated += 1

    await db.commit()
    log.info(
        "menu_items.batch_toggled",
        scheme_id=req.scheme_id,
        count=updated,
        is_available=req.is_available,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": {"updated_count": updated, "is_available": req.is_available}}


@router.post("/api/v1/menu/items/batch-assign")
async def batch_assign_category(
    req: BatchAssignReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """批量将菜品指定到某分类（修改 dishes.category_id）。"""
    tid = await _set_tenant(db, x_tenant_id)
    try:
        cat_uuid = uuid.UUID(req.category_id)
    except ValueError:
        _err(400, "无效的 category_id")

    updated = 0
    for dish_id_str in req.dish_ids:
        try:
            dish_uuid = uuid.UUID(dish_id_str)
        except ValueError:
            log.warning("batch_assign.invalid_dish_id", dish_id=dish_id_str)
            continue
        result = await db.execute(
            text("""
                UPDATE dishes
                SET category_id = :cat_id, updated_at = now()
                WHERE id = :dish_id AND tenant_id = :tid
            """),
            {"cat_id": cat_uuid, "dish_id": dish_uuid, "tid": tid},
        )
        if result.rowcount > 0:
            updated += 1

    await db.commit()
    log.info(
        "dishes.batch_assigned",
        category_id=req.category_id,
        count=updated,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": {"updated_count": updated, "category_id": req.category_id}}
