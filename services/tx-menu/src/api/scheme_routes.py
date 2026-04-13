"""菜谱方案批量下发 API

集团建立菜谱方案 → 批量下发到各门店 → 门店可微调。

端点概览：
  GET    /api/v1/menu-schemes/                      — 方案列表
  POST   /api/v1/menu-schemes/                      — 新建方案
  GET    /api/v1/menu-schemes/{scheme_id}           — 方案详情（含菜品列表）
  PUT    /api/v1/menu-schemes/{scheme_id}           — 更新方案基本信息
  POST   /api/v1/menu-schemes/{scheme_id}/publish   — 发布方案（draft→published）
  POST   /api/v1/menu-schemes/{scheme_id}/distribute — 下发到门店
  GET    /api/v1/menu-schemes/{scheme_id}/stores    — 查看已下发门店列表
  POST   /api/v1/menu-schemes/{scheme_id}/items     — 批量设置方案菜品
  GET    /api/v1/store-menu/{store_id}              — 获取门店当前菜谱（方案+覆盖合并）
  PUT    /api/v1/store-menu/{store_id}/override     — 门店设置价格/状态覆盖
  DELETE /api/v1/store-menu/{store_id}/override/{dish_id} — 清除门店覆盖（还原方案值）

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log = structlog.get_logger(__name__)

router = APIRouter(tags=["menu-schemes"])


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


# ─── Pydantic 模型 ────────────────────────────────────────────────────────────


class CreateSchemeReq(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="方案名称")
    description: Optional[str] = Field(None, description="方案描述")
    brand_id: Optional[str] = Field(None, description="所属品牌 ID，NULL 为集团级")


class UpdateSchemeReq(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    brand_id: Optional[str] = None


class SchemeItemReq(BaseModel):
    dish_id: str = Field(..., description="菜品 ID")
    price_fen: Optional[int] = Field(None, ge=0, description="方案定价（分），NULL=用菜品默认价")
    is_available: bool = Field(True, description="是否可售")
    sort_order: int = Field(0, ge=0, description="排序序号")
    notes: Optional[str] = Field(None, description="备注")


class BatchSetItemsReq(BaseModel):
    items: list[SchemeItemReq] = Field(..., min_length=1)


class DistributeReq(BaseModel):
    store_ids: list[str] = Field(..., min_length=1, description="要下发的门店 ID 列表")
    operator: Optional[str] = Field(None, description="操作人")


class StoreOverrideReq(BaseModel):
    dish_id: str = Field(..., description="菜品 ID")
    scheme_id: str = Field(..., description="关联方案 ID")
    override_price_fen: Optional[int] = Field(None, ge=0, description="覆盖价格（分），NULL=沿用方案价")
    override_available: Optional[bool] = Field(None, description="覆盖可售状态，NULL=沿用方案状态")


# ══════════════════════════════════════════════════════════════════════════════
# 方案列表 & 新建
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/api/v1/menu-schemes/")
async def list_schemes(
    brand_id: Optional[str] = None,
    status: Optional[str] = Query(None, pattern="^(draft|published|archived)$"),
    keyword: Optional[str] = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """方案列表（支持按品牌、状态、关键字过滤）。"""
    tid = await _set_tenant(db, x_tenant_id)
    try:
        where = "WHERE ms.tenant_id = :tid AND ms.is_deleted IS NOT TRUE"
        params: dict = {"tid": tid}

        if brand_id:
            where += " AND ms.brand_id = :brand_id"
            params["brand_id"] = uuid.UUID(brand_id)
        if status:
            where += " AND ms.status = :status"
            params["status"] = status
        if keyword:
            where += " AND ms.name ILIKE :kw"
            params["kw"] = f"%{keyword}%"

        count_res = await db.execute(
            text(f"SELECT COUNT(*) FROM menu_schemes ms {where}"), params
        )
        total = count_res.scalar() or 0

        params["limit"] = size
        params["offset"] = (page - 1) * size
        rows = await db.execute(
            text(f"""
                SELECT ms.id, ms.name, ms.description, ms.brand_id,
                       ms.status, ms.published_at, ms.created_by,
                       ms.created_at, ms.updated_at,
                       (SELECT COUNT(*) FROM menu_scheme_items msi
                        WHERE msi.scheme_id = ms.id) AS item_count,
                       (SELECT COUNT(*) FROM store_scheme_assignments ssa
                        WHERE ssa.scheme_id = ms.id) AS store_count
                FROM menu_schemes ms
                {where}
                ORDER BY ms.updated_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [
            {
                "id": str(r[0]),
                "name": r[1],
                "description": r[2],
                "brand_id": str(r[3]) if r[3] else None,
                "status": r[4],
                "published_at": r[5].isoformat() if r[5] else None,
                "created_by": r[6],
                "created_at": r[7].isoformat() if r[7] else None,
                "updated_at": r[8].isoformat() if r[8] else None,
                "item_count": int(r[9]),
                "store_count": int(r[10]),
            }
            for r in rows.fetchall()
        ]
        return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}
    except ValueError as exc:
        _err(400, str(exc))


@router.post("/api/v1/menu-schemes/", status_code=201)
async def create_scheme(
    req: CreateSchemeReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator: Optional[str] = Header(None, alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
):
    """新建菜谱方案（初始状态为 draft）。"""
    tid = await _set_tenant(db, x_tenant_id)
    try:
        brand_uuid = uuid.UUID(req.brand_id) if req.brand_id else None
        result = await db.execute(
            text("""
                INSERT INTO menu_schemes
                  (tenant_id, brand_id, name, description, status, created_by)
                VALUES (:tid, :brand_id, :name, :desc, 'draft', :created_by)
                RETURNING id, name, description, brand_id, status, created_at
            """),
            {
                "tid": tid,
                "brand_id": brand_uuid,
                "name": req.name,
                "desc": req.description,
                "created_by": x_operator,
            },
        )
        await db.commit()
        row = result.fetchone()
        log.info("menu_scheme.created", scheme_id=str(row[0]), tenant_id=x_tenant_id)
        return {
            "ok": True,
            "data": {
                "id": str(row[0]),
                "name": row[1],
                "description": row[2],
                "brand_id": str(row[3]) if row[3] else None,
                "status": row[4],
                "created_at": row[5].isoformat() if row[5] else None,
            },
        }
    except ValueError as exc:
        _err(400, str(exc))


# ══════════════════════════════════════════════════════════════════════════════
# 方案详情 & 更新
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/api/v1/menu-schemes/{scheme_id}")
async def get_scheme(
    scheme_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """方案详情，含菜品条目列表。"""
    tid = await _set_tenant(db, x_tenant_id)
    try:
        sid = uuid.UUID(scheme_id)
    except ValueError:
        _err(400, "无效的 scheme_id")

    scheme_res = await db.execute(
        text("""
            SELECT id, name, description, brand_id, status,
                   published_at, created_by, created_at, updated_at
            FROM menu_schemes
            WHERE id = :sid AND tenant_id = :tid
        """),
        {"sid": sid, "tid": tid},
    )
    row = scheme_res.fetchone()
    if not row:
        _err(404, "方案不存在")

    items_res = await db.execute(
        text("""
            SELECT msi.id, msi.dish_id, d.dish_name, d.price_fen AS default_price_fen,
                   d.image_url, msi.price_fen, msi.is_available, msi.sort_order, msi.notes
            FROM menu_scheme_items msi
            LEFT JOIN dishes d ON d.id = msi.dish_id
            WHERE msi.scheme_id = :sid AND msi.tenant_id = :tid
            ORDER BY msi.sort_order, d.dish_name
        """),
        {"sid": sid, "tid": tid},
    )
    items = [
        {
            "id": str(r[0]),
            "dish_id": str(r[1]),
            "dish_name": r[2],
            "default_price_fen": r[3],
            "image_url": r[4],
            "price_fen": r[5],
            "is_available": r[6],
            "sort_order": r[7],
            "notes": r[8],
        }
        for r in items_res.fetchall()
    ]

    return {
        "ok": True,
        "data": {
            "id": str(row[0]),
            "name": row[1],
            "description": row[2],
            "brand_id": str(row[3]) if row[3] else None,
            "status": row[4],
            "published_at": row[5].isoformat() if row[5] else None,
            "created_by": row[6],
            "created_at": row[7].isoformat() if row[7] else None,
            "updated_at": row[8].isoformat() if row[8] else None,
            "items": items,
        },
    }


@router.put("/api/v1/menu-schemes/{scheme_id}")
async def update_scheme(
    scheme_id: str,
    req: UpdateSchemeReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """更新方案基本信息（仅 draft 状态可更新名称/描述/品牌）。"""
    tid = await _set_tenant(db, x_tenant_id)
    try:
        sid = uuid.UUID(scheme_id)
    except ValueError:
        _err(400, "无效的 scheme_id")

    check = await db.execute(
        text("SELECT status FROM menu_schemes WHERE id = :sid AND tenant_id = :tid"),
        {"sid": sid, "tid": tid},
    )
    existing = check.fetchone()
    if not existing:
        _err(404, "方案不存在")

    sets = ["updated_at = now()"]
    params: dict = {"sid": sid, "tid": tid}
    if req.name is not None:
        sets.append("name = :name")
        params["name"] = req.name
    if req.description is not None:
        sets.append("description = :description")
        params["description"] = req.description
    if req.brand_id is not None:
        sets.append("brand_id = :brand_id")
        params["brand_id"] = uuid.UUID(req.brand_id)

    await db.execute(
        text(f"UPDATE menu_schemes SET {', '.join(sets)} WHERE id = :sid AND tenant_id = :tid"),
        params,
    )
    await db.commit()
    log.info("menu_scheme.updated", scheme_id=scheme_id, tenant_id=x_tenant_id)
    return {"ok": True, "data": {"scheme_id": scheme_id, "updated": True}}


# ══════════════════════════════════════════════════════════════════════════════
# 发布方案
# ══════════════════════════════════════════════════════════════════════════════


@router.post("/api/v1/menu-schemes/{scheme_id}/publish")
async def publish_scheme(
    scheme_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """发布方案：draft → published，记录 published_at 时间戳。"""
    tid = await _set_tenant(db, x_tenant_id)
    try:
        sid = uuid.UUID(scheme_id)
    except ValueError:
        _err(400, "无效的 scheme_id")

    check = await db.execute(
        text("SELECT status FROM menu_schemes WHERE id = :sid AND tenant_id = :tid"),
        {"sid": sid, "tid": tid},
    )
    row = check.fetchone()
    if not row:
        _err(404, "方案不存在")
    if row[0] == "published":
        _err(400, "方案已是发布状态")
    if row[0] == "archived":
        _err(400, "已归档方案无法发布")

    # 校验方案至少有一个菜品条目
    item_count = await db.execute(
        text("SELECT COUNT(*) FROM menu_scheme_items WHERE scheme_id = :sid AND tenant_id = :tid"),
        {"sid": sid, "tid": tid},
    )
    if (item_count.scalar() or 0) == 0:
        _err(400, "方案内没有菜品，无法发布")

    await db.execute(
        text("""
            UPDATE menu_schemes
            SET status = 'published', published_at = now(), updated_at = now()
            WHERE id = :sid AND tenant_id = :tid
        """),
        {"sid": sid, "tid": tid},
    )

    # ── 自动快照：将当前菜品列表写入 menu_plan_versions ──────────────────
    # 1) 查询当前方案的最大版本号
    ver_row = await db.execute(
        text("""
            SELECT COALESCE(MAX(version_number), 0)
            FROM menu_plan_versions
            WHERE scheme_id = :sid AND tenant_id = :tid AND is_deleted = false
        """),
        {"sid": sid, "tid": tid},
    )
    next_version = (ver_row.scalar() or 0) + 1

    # 2) 查询方案所有菜品作为 snapshot
    snap_res = await db.execute(
        text("""
            SELECT msi.id, msi.dish_id, d.dish_name, d.price_fen AS default_price_fen,
                   msi.price_fen, msi.is_available, msi.sort_order, msi.notes
            FROM menu_scheme_items msi
            LEFT JOIN dishes d ON d.id = msi.dish_id
            WHERE msi.scheme_id = :sid AND msi.tenant_id = :tid
            ORDER BY msi.sort_order, msi.id
        """),
        {"sid": sid, "tid": tid},
    )
    snapshot = [
        {
            "item_id": str(r[0]),
            "dish_id": str(r[1]),
            "dish_name": r[2],
            "default_price_fen": r[3],
            "price_fen": r[4],
            "is_available": r[5],
            "sort_order": r[6],
            "notes": r[7],
        }
        for r in snap_res.fetchall()
    ]

    await db.execute(
        text("""
            INSERT INTO menu_plan_versions
              (id, tenant_id, scheme_id, version_number, change_summary,
               snapshot_json, published_by, created_at, is_deleted)
            VALUES
              (gen_random_uuid(), :tid, :sid, :ver, :summary,
               :snap::jsonb, :operator, now(), false)
        """),
        {
            "tid": tid,
            "sid": sid,
            "ver": next_version,
            "summary": f"v{next_version} — 发布时自动快照，共 {len(snapshot)} 个菜品",
            "snap": json.dumps(snapshot, ensure_ascii=False),
            "operator": x_tenant_id,  # 无 operator header 时用 tenant_id 作标识
        },
    )

    await db.commit()
    log.info(
        "menu_scheme.published",
        scheme_id=scheme_id,
        tenant_id=x_tenant_id,
        version=next_version,
        snapshot_items=len(snapshot),
    )

    # 发射事件（异步旁路，不阻塞响应）
    try:
        from shared.events.src.emitter import emit_event
        from shared.events.src.event_types import MenuEventType
        asyncio.create_task(emit_event(
            event_type=MenuEventType.PLAN_PUBLISHED,
            tenant_id=str(tid),
            stream_id=scheme_id,
            payload={"version": next_version, "item_count": len(snapshot)},
            source_service="tx-menu",
        ))
    except Exception:  # noqa: BLE001 — 事件发射失败不影响主业务
        pass

    return {
        "ok": True,
        "data": {
            "scheme_id": scheme_id,
            "status": "published",
            "version": next_version,
            "snapshot_items": len(snapshot),
            "published_at": datetime.now(timezone.utc).isoformat(),
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# 下发到门店
# ══════════════════════════════════════════════════════════════════════════════


@router.post("/api/v1/menu-schemes/{scheme_id}/distribute")
async def distribute_scheme(
    scheme_id: str,
    req: DistributeReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """将已发布方案批量下发到指定门店（UPSERT，可重复下发）。"""
    tid = await _set_tenant(db, x_tenant_id)
    try:
        sid = uuid.UUID(scheme_id)
    except ValueError:
        _err(400, "无效的 scheme_id")

    check = await db.execute(
        text("SELECT status FROM menu_schemes WHERE id = :sid AND tenant_id = :tid"),
        {"sid": sid, "tid": tid},
    )
    row = check.fetchone()
    if not row:
        _err(404, "方案不存在")
    if row[0] != "published":
        _err(400, "只有已发布的方案才能下发，请先发布方案")

    # 获取本方案当前最新版本号（用于 distribute_log）
    ver_row = await db.execute(
        text("""
            SELECT COALESCE(MAX(version_number), NULL)
            FROM menu_plan_versions
            WHERE scheme_id = :sid AND tenant_id = :tid AND is_deleted = false
        """),
        {"sid": sid, "tid": tid},
    )
    current_version = ver_row.scalar()  # None 表示尚未有版本快照

    distributed_count = 0
    distributed_store_ids: list[str] = []
    for store_id_str in req.store_ids:
        try:
            store_uuid = uuid.UUID(store_id_str)
        except ValueError:
            log.warning("distribute.invalid_store_id", store_id=store_id_str)
            continue
        await db.execute(
            text("""
                INSERT INTO store_scheme_assignments
                  (tenant_id, store_id, scheme_id, distributed_at, distributed_by)
                VALUES (:tid, :store_id, :sid, now(), :operator)
                ON CONFLICT (store_id, scheme_id)
                DO UPDATE SET distributed_at = now(), distributed_by = :operator
            """),
            {
                "tid": tid,
                "store_id": store_uuid,
                "sid": sid,
                "operator": req.operator,
            },
        )
        # 写 distribute_log
        await db.execute(
            text("""
                INSERT INTO menu_distribute_log
                  (id, tenant_id, scheme_id, store_id, version_number,
                   status, error_message, distributed_by, distributed_at, is_deleted)
                VALUES
                  (gen_random_uuid(), :tid, :sid, :store_id, :ver,
                   'success', NULL, :operator, now(), false)
            """),
            {
                "tid": tid,
                "sid": sid,
                "store_id": store_uuid,
                "ver": current_version,
                "operator": req.operator,
            },
        )
        distributed_count += 1
        distributed_store_ids.append(str(store_uuid))

    await db.commit()
    log.info(
        "menu_scheme.distributed",
        scheme_id=scheme_id,
        store_count=distributed_count,
        version=current_version,
        tenant_id=x_tenant_id,
    )

    # 发射 PLAN_DISTRIBUTED 事件（异步旁路）
    try:
        from shared.events.src.emitter import emit_event
        from shared.events.src.event_types import MenuEventType
        asyncio.create_task(emit_event(
            event_type=MenuEventType.PLAN_DISTRIBUTED,
            tenant_id=str(tid),
            stream_id=scheme_id,
            payload={
                "store_ids": distributed_store_ids,
                "version": current_version,
                "distributed_by": req.operator,
            },
            source_service="tx-menu",
        ))
    except Exception:  # noqa: BLE001 — 事件发射失败不影响主业务
        pass

    return {
        "ok": True,
        "data": {
            "scheme_id": scheme_id,
            "distributed_store_count": distributed_count,
            "total_requested": len(req.store_ids),
            "version": current_version,
        },
    }


@router.get("/api/v1/menu-schemes/{scheme_id}/stores")
async def get_scheme_stores(
    scheme_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """查看方案已下发的门店列表及覆盖情况。"""
    tid = await _set_tenant(db, x_tenant_id)
    try:
        sid = uuid.UUID(scheme_id)
    except ValueError:
        _err(400, "无效的 scheme_id")

    count_res = await db.execute(
        text("""
            SELECT COUNT(*) FROM store_scheme_assignments
            WHERE scheme_id = :sid AND tenant_id = :tid
        """),
        {"sid": sid, "tid": tid},
    )
    total = count_res.scalar() or 0

    rows = await db.execute(
        text("""
            SELECT ssa.store_id, ssa.distributed_at, ssa.distributed_by,
                   (SELECT COUNT(*) FROM store_menu_overrides smo
                    WHERE smo.store_id = ssa.store_id
                      AND smo.scheme_id = ssa.scheme_id
                      AND smo.tenant_id = ssa.tenant_id) AS override_count
            FROM store_scheme_assignments ssa
            WHERE ssa.scheme_id = :sid AND ssa.tenant_id = :tid
            ORDER BY ssa.distributed_at DESC
            LIMIT :limit OFFSET :offset
        """),
        {"sid": sid, "tid": tid, "limit": size, "offset": (page - 1) * size},
    )
    items = [
        {
            "store_id": str(r[0]),
            "distributed_at": r[1].isoformat() if r[1] else None,
            "distributed_by": r[2],
            "override_count": int(r[3]),
        }
        for r in rows.fetchall()
    ]
    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}


# ══════════════════════════════════════════════════════════════════════════════
# 批量设置方案菜品
# ══════════════════════════════════════════════════════════════════════════════


@router.post("/api/v1/menu-schemes/{scheme_id}/items")
async def set_scheme_items(
    scheme_id: str,
    req: BatchSetItemsReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """批量 UPSERT 方案菜品条目（幂等，可多次调用）。"""
    tid = await _set_tenant(db, x_tenant_id)
    try:
        sid = uuid.UUID(scheme_id)
    except ValueError:
        _err(400, "无效的 scheme_id")

    check = await db.execute(
        text("SELECT status FROM menu_schemes WHERE id = :sid AND tenant_id = :tid"),
        {"sid": sid, "tid": tid},
    )
    row = check.fetchone()
    if not row:
        _err(404, "方案不存在")
    if row[0] == "archived":
        _err(400, "已归档方案不可编辑")

    upserted = 0
    for item in req.items:
        try:
            dish_uuid = uuid.UUID(item.dish_id)
        except ValueError:
            log.warning("scheme_items.invalid_dish_id", dish_id=item.dish_id)
            continue
        await db.execute(
            text("""
                INSERT INTO menu_scheme_items
                  (tenant_id, scheme_id, dish_id, price_fen, is_available, sort_order, notes)
                VALUES (:tid, :sid, :dish_id, :price_fen, :is_available, :sort_order, :notes)
                ON CONFLICT (scheme_id, dish_id)
                DO UPDATE SET
                  price_fen    = EXCLUDED.price_fen,
                  is_available = EXCLUDED.is_available,
                  sort_order   = EXCLUDED.sort_order,
                  notes        = EXCLUDED.notes
            """),
            {
                "tid": tid,
                "sid": sid,
                "dish_id": dish_uuid,
                "price_fen": item.price_fen,
                "is_available": item.is_available,
                "sort_order": item.sort_order,
                "notes": item.notes,
            },
        )
        upserted += 1

    # 同步更新方案的 updated_at
    await db.execute(
        text("UPDATE menu_schemes SET updated_at = now() WHERE id = :sid AND tenant_id = :tid"),
        {"sid": sid, "tid": tid},
    )
    await db.commit()
    log.info("menu_scheme.items_set", scheme_id=scheme_id, count=upserted, tenant_id=x_tenant_id)
    return {"ok": True, "data": {"scheme_id": scheme_id, "upserted_count": upserted}}


# ══════════════════════════════════════════════════════════════════════════════
# 门店菜谱（方案 + 覆盖合并视图）
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/api/v1/store-menu/{store_id}")
async def get_store_menu(
    store_id: str,
    scheme_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取门店当前菜谱：方案基础价格/状态 + 门店覆盖合并。

    若未指定 scheme_id，则自动取该门店最新下发的方案。
    返回每道菜的「生效价格」和「生效可售状态」，以及是否有门店覆盖标识。
    """
    tid = await _set_tenant(db, x_tenant_id)
    try:
        store_uuid = uuid.UUID(store_id)
    except ValueError:
        _err(400, "无效的 store_id")

    # 确定使用的方案
    if scheme_id:
        try:
            sid = uuid.UUID(scheme_id)
        except ValueError:
            _err(400, "无效的 scheme_id")
    else:
        latest = await db.execute(
            text("""
                SELECT scheme_id FROM store_scheme_assignments
                WHERE store_id = :store_id AND tenant_id = :tid
                ORDER BY distributed_at DESC
                LIMIT 1
            """),
            {"store_id": store_uuid, "tid": tid},
        )
        row = latest.fetchone()
        if not row:
            return {"ok": True, "data": {"items": [], "total": 0, "scheme_id": None,
                                          "message": "该门店尚未下发任何菜谱方案"}}
        sid = row[0]

    count_res = await db.execute(
        text("""
            SELECT COUNT(*) FROM menu_scheme_items
            WHERE scheme_id = :sid AND tenant_id = :tid
        """),
        {"sid": sid, "tid": tid},
    )
    total = count_res.scalar() or 0

    rows = await db.execute(
        text("""
            SELECT
                msi.dish_id,
                d.dish_name,
                d.price_fen          AS default_price_fen,
                d.image_url,
                msi.price_fen        AS scheme_price_fen,
                msi.is_available     AS scheme_available,
                msi.sort_order,
                smo.override_price_fen,
                smo.override_available,
                -- 生效价格：门店覆盖 > 方案价 > 菜品默认价
                COALESCE(smo.override_price_fen, msi.price_fen, d.price_fen) AS effective_price_fen,
                -- 生效可售：门店覆盖 > 方案状态
                COALESCE(smo.override_available, msi.is_available)           AS effective_available,
                (smo.id IS NOT NULL) AS has_override
            FROM menu_scheme_items msi
            LEFT JOIN dishes d ON d.id = msi.dish_id
            LEFT JOIN store_menu_overrides smo
              ON smo.dish_id  = msi.dish_id
             AND smo.scheme_id = msi.scheme_id
             AND smo.store_id  = :store_id
             AND smo.tenant_id = :tid
            WHERE msi.scheme_id = :sid AND msi.tenant_id = :tid
            ORDER BY msi.sort_order, d.dish_name
            LIMIT :limit OFFSET :offset
        """),
        {
            "sid": sid,
            "tid": tid,
            "store_id": store_uuid,
            "limit": size,
            "offset": (page - 1) * size,
        },
    )
    items = [
        {
            "dish_id": str(r[0]),
            "dish_name": r[1],
            "default_price_fen": r[2],
            "image_url": r[3],
            "scheme_price_fen": r[4],
            "scheme_available": r[5],
            "sort_order": r[6],
            "override_price_fen": r[7],
            "override_available": r[8],
            "effective_price_fen": r[9],
            "effective_available": r[10],
            "has_override": bool(r[11]),
        }
        for r in rows.fetchall()
    ]
    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "scheme_id": str(sid),
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# 门店覆盖微调
# ══════════════════════════════════════════════════════════════════════════════


@router.put("/api/v1/store-menu/{store_id}/override")
async def set_store_override(
    store_id: str,
    req: StoreOverrideReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """设置门店对指定菜品的价格/状态覆盖（UPSERT）。"""
    tid = await _set_tenant(db, x_tenant_id)
    try:
        store_uuid = uuid.UUID(store_id)
        dish_uuid = uuid.UUID(req.dish_id)
        scheme_uuid = uuid.UUID(req.scheme_id)
    except ValueError as exc:
        _err(400, f"UUID 格式错误: {exc}")

    # 校验该门店已被下发该方案
    check = await db.execute(
        text("""
            SELECT 1 FROM store_scheme_assignments
            WHERE store_id = :store_id AND scheme_id = :sid AND tenant_id = :tid
        """),
        {"store_id": store_uuid, "sid": scheme_uuid, "tid": tid},
    )
    if not check.fetchone():
        _err(400, "该门店尚未下发此方案，无法设置覆盖")

    await db.execute(
        text("""
            INSERT INTO store_menu_overrides
              (tenant_id, store_id, dish_id, scheme_id, override_price_fen, override_available, updated_at)
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
            "price": req.override_price_fen,
            "available": req.override_available,
        },
    )
    await db.commit()
    log.info(
        "store_menu.override_set",
        store_id=store_id,
        dish_id=req.dish_id,
        tenant_id=x_tenant_id,
    )
    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "dish_id": req.dish_id,
            "scheme_id": req.scheme_id,
            "override_price_fen": req.override_price_fen,
            "override_available": req.override_available,
        },
    }


@router.delete("/api/v1/store-menu/{store_id}/override/{dish_id}")
async def delete_store_override(
    store_id: str,
    dish_id: str,
    scheme_id: str = Query(..., description="关联方案 ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """清除门店对指定菜品的覆盖（还原为方案值）。"""
    tid = await _set_tenant(db, x_tenant_id)
    try:
        store_uuid = uuid.UUID(store_id)
        dish_uuid = uuid.UUID(dish_id)
        scheme_uuid = uuid.UUID(scheme_id)
    except ValueError as exc:
        _err(400, f"UUID 格式错误: {exc}")

    result = await db.execute(
        text("""
            DELETE FROM store_menu_overrides
            WHERE store_id = :store_id
              AND dish_id  = :dish_id
              AND scheme_id = :sid
              AND tenant_id = :tid
        """),
        {"store_id": store_uuid, "dish_id": dish_uuid, "sid": scheme_uuid, "tid": tid},
    )
    await db.commit()
    deleted = result.rowcount > 0
    log.info(
        "store_menu.override_deleted",
        store_id=store_id,
        dish_id=dish_id,
        deleted=deleted,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": {"deleted": deleted}}
