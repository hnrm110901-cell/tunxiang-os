"""菜谱方案批量下发 V2 + 门店Override机制 — 天财商龙对齐版

端点概览：

  A. 菜谱方案管理
     POST /api/v1/menu-plans                          — 创建菜谱方案
     GET  /api/v1/menu-plans                          — 品牌菜谱方案列表
     GET  /api/v1/menu-plans/{plan_id}                — 方案详情含品项列表
     PUT  /api/v1/menu-plans/{plan_id}                — 更新方案（草稿状态可编辑）
     POST /api/v1/menu-plans/{plan_id}/publish        — 发布方案（draft→published）
     POST /api/v1/menu-plans/{plan_id}/push           — 批量推送到门店
     GET  /api/v1/menu-plans/push-tasks/{task_id}     — 推送任务进度查询

  B. 门店Override机制
     GET    /api/v1/menu-plans/store-overrides/{store_id}                — 门店Override列表
     POST   /api/v1/menu-plans/store-overrides/{store_id}               — 创建Override
     DELETE /api/v1/menu-plans/store-overrides/{store_id}/{override_id} — 撤销Override
     GET    /api/v1/menu-plans/effective/{store_id}                      — 门店当前生效菜单

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。

推送实现：BackgroundTasks 异步执行，进度写入 menu_push_logs 表。
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from shared.events.src.emitter import emit_event
from shared.events.src.event_types import MenuEventType

log = structlog.get_logger(__name__)

router = APIRouter(tags=["menu-plan-v2"])


# ─── 辅助函数 ──────────────────────────────────────────────────────────────────


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


async def _fetch_plan(db: AsyncSession, plan_id: uuid.UUID, tid: uuid.UUID) -> dict:
    """查询方案基本信息，不存在则 404。"""
    res = await db.execute(
        text("""
            SELECT id, name, description, brand_id, status, effective_date, created_at, updated_at
            FROM menu_plans_v2
            WHERE id = :pid AND tenant_id = :tid AND is_deleted IS NOT TRUE
        """),
        {"pid": plan_id, "tid": tid},
    )
    row = res.fetchone()
    if not row:
        _err(404, "菜谱方案不存在")
    return {
        "id": str(row[0]),
        "name": row[1],
        "description": row[2],
        "brand_id": str(row[3]) if row[3] else None,
        "status": row[4],
        "effective_date": row[5].isoformat() if row[5] else None,
        "created_at": row[6].isoformat() if row[6] else None,
        "updated_at": row[7].isoformat() if row[7] else None,
    }


# ─── Pydantic 模型 ────────────────────────────────────────────────────────────


class MenuPlanItemReq(BaseModel):
    dish_id: str = Field(..., description="菜品 ID")
    price: Optional[int] = Field(None, ge=0, description="价格（分）")
    is_available: bool = Field(True, description="是否可用")


class CreateMenuPlanReq(BaseModel):
    name: str = Field(..., max_length=100, description="方案名称")
    description: Optional[str] = Field(None, max_length=500)
    brand_id: str = Field(..., description="品牌 ID")
    effective_date: Optional[str] = Field(None, description="生效日期 YYYY-MM-DD")
    menu_items: List[MenuPlanItemReq] = Field(default_factory=list)


class UpdateMenuPlanReq(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    effective_date: Optional[str] = None
    menu_items: Optional[List[MenuPlanItemReq]] = None


class PushMenuPlanReq(BaseModel):
    store_ids: List[str] = Field(default_factory=list, description="指定门店，空则推送到品牌全部门店")
    push_mode: str = Field("immediate", pattern="^(immediate|scheduled)$")
    scheduled_at: Optional[str] = Field(None, description="push_mode=scheduled 时必填，ISO8601")
    override_store_settings: bool = Field(False, description="是否覆盖门店自定义")


class StoreOverrideReq(BaseModel):
    dish_id: str = Field(..., description="菜品 ID")
    override_type: str = Field(..., pattern="^(price|availability|portion)$", description="覆盖类型")
    value: str = Field(..., description="覆盖值（价格传分整数字符串，可用状态传 true/false）")
    reason: Optional[str] = Field(None, max_length=200)
    valid_from: Optional[str] = Field(None, description="YYYY-MM-DD")
    valid_until: Optional[str] = Field(None, description="YYYY-MM-DD")


# ══════════════════════════════════════════════════════════════════════════════
# A. 菜谱方案管理
# ══════════════════════════════════════════════════════════════════════════════


@router.post("/api/v1/menu-plans", status_code=201)
async def create_menu_plan(
    req: CreateMenuPlanReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator: Optional[str] = Header(None, alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
):
    """创建菜谱方案（初始状态为 draft）。"""
    tid = await _set_tenant(db, x_tenant_id)
    try:
        brand_uuid = uuid.UUID(req.brand_id)
    except ValueError:
        _err(400, "无效的 brand_id")

    plan_id = uuid.uuid4()
    effective_date = None
    if req.effective_date:
        try:
            from datetime import date
            effective_date = date.fromisoformat(req.effective_date)
        except ValueError:
            _err(400, "无效的 effective_date 格式，应为 YYYY-MM-DD")

    await db.execute(
        text("""
            INSERT INTO menu_plans_v2
              (id, tenant_id, name, description, brand_id, status, effective_date, created_by)
            VALUES (:id, :tid, :name, :desc, :brand_id, 'draft', :eff_date, :operator)
        """),
        {
            "id": plan_id,
            "tid": tid,
            "name": req.name,
            "desc": req.description,
            "brand_id": brand_uuid,
            "eff_date": effective_date,
            "operator": x_operator,
        },
    )

    # 插入品项
    inserted_items = 0
    for item in req.menu_items:
        try:
            dish_uuid = uuid.UUID(item.dish_id)
        except ValueError:
            log.warning("create_plan.invalid_dish_id", dish_id=item.dish_id)
            continue
        await db.execute(
            text("""
                INSERT INTO menu_plan_v2_items
                  (tenant_id, plan_id, dish_id, price_fen, is_available)
                VALUES (:tid, :plan_id, :dish_id, :price, :available)
            """),
            {
                "tid": tid,
                "plan_id": plan_id,
                "dish_id": dish_uuid,
                "price": item.price,
                "available": item.is_available,
            },
        )
        inserted_items += 1

    await db.commit()
    log.info("menu_plan_v2.created", plan_id=str(plan_id), tenant_id=x_tenant_id)
    return {
        "ok": True,
        "data": {
            "id": str(plan_id),
            "name": req.name,
            "status": "draft",
            "items_count": inserted_items,
        },
    }


@router.get("/api/v1/menu-plans")
async def list_menu_plans(
    brand_id: str = Query(..., description="品牌 ID"),
    status: Optional[str] = Query(None, pattern="^(draft|published|archived)$"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """品牌菜谱方案列表。"""
    tid = await _set_tenant(db, x_tenant_id)
    try:
        brand_uuid = uuid.UUID(brand_id)
    except ValueError:
        _err(400, "无效的 brand_id")

    where = "WHERE tenant_id = :tid AND brand_id = :brand_id AND is_deleted IS NOT TRUE"
    params: dict = {"tid": tid, "brand_id": brand_uuid}

    if status:
        where += " AND status = :status"
        params["status"] = status

    count_res = await db.execute(
        text(f"SELECT COUNT(*) FROM menu_plans_v2 {where}"), params
    )
    total = count_res.scalar() or 0

    params["limit"] = size
    params["offset"] = (page - 1) * size
    rows = await db.execute(
        text(f"""
            SELECT p.id, p.name, p.description, p.status, p.effective_date,
                   p.created_at, p.updated_at,
                   (SELECT COUNT(*) FROM menu_plan_v2_items i
                    WHERE i.plan_id = p.id AND i.tenant_id = p.tenant_id) AS items_count
            FROM menu_plans_v2 p
            {where}
            ORDER BY p.created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items = [
        {
            "id": str(r[0]),
            "name": r[1],
            "description": r[2],
            "status": r[3],
            "effective_date": r[4].isoformat() if r[4] else None,
            "created_at": r[5].isoformat() if r[5] else None,
            "updated_at": r[6].isoformat() if r[6] else None,
            "items_count": r[7] or 0,
        }
        for r in rows.fetchall()
    ]
    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}


@router.get("/api/v1/menu-plans/push-tasks/{task_id}")
async def get_push_task_progress(
    task_id: str = Path(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """推送任务进度查询。返回总数/成功/失败/待处理及各门店详情。"""
    tid = await _set_tenant(db, x_tenant_id)
    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError:
        _err(400, "无效的 task_id")

    # 查询任务元数据
    task_res = await db.execute(
        text("""
            SELECT id, plan_id, total_stores, created_at, push_mode, scheduled_at
            FROM menu_push_tasks
            WHERE id = :task_id AND tenant_id = :tid
        """),
        {"task_id": task_uuid, "tid": tid},
    )
    task_row = task_res.fetchone()
    if not task_row:
        _err(404, "推送任务不存在")

    # 统计各状态数量
    stats_res = await db.execute(
        text("""
            SELECT status, COUNT(*) AS cnt
            FROM menu_push_logs
            WHERE task_id = :task_id AND tenant_id = :tid
            GROUP BY status
        """),
        {"task_id": task_uuid, "tid": tid},
    )
    stats = {row[0]: row[1] for row in stats_res.fetchall()}

    # 各门店详情
    detail_rows = await db.execute(
        text("""
            SELECT store_id, status, error_message, pushed_at
            FROM menu_push_logs
            WHERE task_id = :task_id AND tenant_id = :tid
            ORDER BY pushed_at DESC NULLS LAST
            LIMIT 200
        """),
        {"task_id": task_uuid, "tid": tid},
    )
    details = [
        {
            "store_id": str(r[0]),
            "status": r[1],
            "error": r[2],
            "pushed_at": r[3].isoformat() if r[3] else None,
        }
        for r in detail_rows.fetchall()
    ]

    return {
        "ok": True,
        "data": {
            "task_id": task_id,
            "plan_id": str(task_row[1]),
            "total": task_row[2],
            "success": stats.get("success", 0),
            "failed": stats.get("failed", 0),
            "pending": stats.get("pending", 0),
            "push_mode": task_row[4],
            "scheduled_at": task_row[5].isoformat() if task_row[5] else None,
            "created_at": task_row[3].isoformat() if task_row[3] else None,
            "details": details,
        },
    }


@router.get("/api/v1/menu-plans/store-overrides/{store_id}")
async def list_store_overrides_v2(
    store_id: str = Path(...),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """查询门店对品牌方案的Override列表。"""
    tid = await _set_tenant(db, x_tenant_id)
    try:
        store_uuid = uuid.UUID(store_id)
    except ValueError:
        _err(400, "无效的 store_id")

    count_res = await db.execute(
        text("""
            SELECT COUNT(*) FROM menu_plan_store_overrides
            WHERE store_id = :store_id AND tenant_id = :tid AND is_deleted IS NOT TRUE
        """),
        {"store_id": store_uuid, "tid": tid},
    )
    total = count_res.scalar() or 0

    rows = await db.execute(
        text("""
            SELECT o.id, o.dish_id, d.dish_name, o.override_type, o.value,
                   o.reason, o.valid_from, o.valid_until, o.created_at
            FROM menu_plan_store_overrides o
            LEFT JOIN dishes d ON d.id = o.dish_id
            WHERE o.store_id = :store_id AND o.tenant_id = :tid AND o.is_deleted IS NOT TRUE
            ORDER BY o.created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        {
            "store_id": store_uuid,
            "tid": tid,
            "limit": size,
            "offset": (page - 1) * size,
        },
    )
    items = [
        {
            "id": str(r[0]),
            "dish_id": str(r[1]),
            "dish_name": r[2],
            "override_type": r[3],
            "value": r[4],
            "reason": r[5],
            "valid_from": r[6].isoformat() if r[6] else None,
            "valid_until": r[7].isoformat() if r[7] else None,
            "created_at": r[8].isoformat() if r[8] else None,
        }
        for r in rows.fetchall()
    ]
    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}


@router.get("/api/v1/menu-plans/effective/{store_id}")
async def get_effective_menu(
    store_id: str = Path(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取门店当前生效菜单：品牌方案 + 门店Override合并后的最终结果。"""
    tid = await _set_tenant(db, x_tenant_id)
    try:
        store_uuid = uuid.UUID(store_id)
    except ValueError:
        _err(400, "无效的 store_id")

    # 找到该门店当前激活的推送方案
    plan_res = await db.execute(
        text("""
            SELECT plan_id FROM menu_store_active_plans
            WHERE store_id = :store_id AND tenant_id = :tid AND is_active = TRUE
            ORDER BY activated_at DESC
            LIMIT 1
        """),
        {"store_id": store_uuid, "tid": tid},
    )
    plan_row = plan_res.fetchone()

    if not plan_row:
        return {"ok": True, "data": {"store_id": store_id, "plan_id": None, "items": [], "note": "无激活方案"}}

    plan_id = plan_row[0]

    # 拉取方案品项
    items_res = await db.execute(
        text("""
            SELECT
                i.dish_id,
                d.dish_name,
                i.price_fen           AS brand_price_fen,
                i.is_available        AS brand_is_available,
                -- 门店Override（取当天有效的，按创建时间取最新）
                o.override_type,
                o.value               AS override_value
            FROM menu_plan_v2_items i
            LEFT JOIN dishes d ON d.id = i.dish_id AND d.tenant_id = i.tenant_id
            LEFT JOIN LATERAL (
                SELECT override_type, value
                FROM menu_plan_store_overrides
                WHERE store_id = :store_id
                  AND dish_id = i.dish_id
                  AND tenant_id = :tid
                  AND is_deleted IS NOT TRUE
                  AND (valid_from IS NULL OR valid_from <= CURRENT_DATE)
                  AND (valid_until IS NULL OR valid_until >= CURRENT_DATE)
                ORDER BY created_at DESC
                LIMIT 1
            ) o ON TRUE
            WHERE i.plan_id = :plan_id AND i.tenant_id = :tid
            ORDER BY d.dish_name
        """),
        {"plan_id": plan_id, "store_id": store_uuid, "tid": tid},
    )

    items = []
    for r in items_res.fetchall():
        # 合并逻辑：Override 存在时覆盖品牌方案字段
        price_fen = r[2]
        is_available = r[3]
        has_override = r[4] is not None

        if has_override:
            if r[4] == "price":
                try:
                    price_fen = int(r[5])
                except (TypeError, ValueError):
                    pass
            elif r[4] == "availability":
                is_available = r[5].lower() == "true" if r[5] else is_available

        items.append({
            "dish_id": str(r[0]),
            "dish_name": r[1],
            "price_fen": price_fen,
            "is_available": is_available,
            "has_store_override": has_override,
            "override_type": r[4],
        })

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "plan_id": str(plan_id),
            "items": items,
            "total": len(items),
        },
    }


@router.get("/api/v1/menu-plans/{plan_id}")
async def get_menu_plan_detail(
    plan_id: str = Path(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """方案详情含品项列表。"""
    tid = await _set_tenant(db, x_tenant_id)
    try:
        pid = uuid.UUID(plan_id)
    except ValueError:
        _err(400, "无效的 plan_id")

    plan = await _fetch_plan(db, pid, tid)

    # 查询品项列表
    items_res = await db.execute(
        text("""
            SELECT i.dish_id, d.dish_name, i.price_fen, i.is_available, i.created_at
            FROM menu_plan_v2_items i
            LEFT JOIN dishes d ON d.id = i.dish_id AND d.tenant_id = i.tenant_id
            WHERE i.plan_id = :pid AND i.tenant_id = :tid
            ORDER BY d.dish_name
        """),
        {"pid": pid, "tid": tid},
    )
    items = [
        {
            "dish_id": str(r[0]),
            "dish_name": r[1],
            "price_fen": r[2],
            "is_available": r[3],
            "created_at": r[4].isoformat() if r[4] else None,
        }
        for r in items_res.fetchall()
    ]

    plan["menu_items"] = items
    plan["items_count"] = len(items)
    return {"ok": True, "data": plan}


@router.put("/api/v1/menu-plans/{plan_id}")
async def update_menu_plan(
    req: UpdateMenuPlanReq,
    plan_id: str = Path(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """更新方案（仅 draft 状态可编辑）。"""
    tid = await _set_tenant(db, x_tenant_id)
    try:
        pid = uuid.UUID(plan_id)
    except ValueError:
        _err(400, "无效的 plan_id")

    plan = await _fetch_plan(db, pid, tid)
    if plan["status"] != "draft":
        _err(400, f"只有草稿状态的方案可以编辑，当前状态: {plan['status']}")

    # 构建动态更新字段
    set_parts = ["updated_at = now()"]
    params: dict = {"pid": pid, "tid": tid}

    if req.name is not None:
        set_parts.append("name = :name")
        params["name"] = req.name
    if req.description is not None:
        set_parts.append("description = :desc")
        params["desc"] = req.description
    if req.effective_date is not None:
        try:
            from datetime import date
            params["eff_date"] = date.fromisoformat(req.effective_date)
        except ValueError:
            _err(400, "无效的 effective_date 格式")
        set_parts.append("effective_date = :eff_date")

    if len(set_parts) > 1:
        await db.execute(
            text(f"UPDATE menu_plans_v2 SET {', '.join(set_parts)} WHERE id = :pid AND tenant_id = :tid"),
            params,
        )

    # 如果提供了 menu_items，替换所有品项
    if req.menu_items is not None:
        await db.execute(
            text("DELETE FROM menu_plan_v2_items WHERE plan_id = :pid AND tenant_id = :tid"),
            {"pid": pid, "tid": tid},
        )
        for item in req.menu_items:
            try:
                dish_uuid = uuid.UUID(item.dish_id)
            except ValueError:
                log.warning("update_plan.invalid_dish_id", dish_id=item.dish_id)
                continue
            await db.execute(
                text("""
                    INSERT INTO menu_plan_v2_items
                      (tenant_id, plan_id, dish_id, price_fen, is_available)
                    VALUES (:tid, :plan_id, :dish_id, :price, :available)
                """),
                {
                    "tid": tid,
                    "plan_id": pid,
                    "dish_id": dish_uuid,
                    "price": item.price,
                    "available": item.is_available,
                },
            )

    await db.commit()
    log.info("menu_plan_v2.updated", plan_id=plan_id, tenant_id=x_tenant_id)
    return {"ok": True, "data": {"plan_id": plan_id, "updated": True}}


@router.post("/api/v1/menu-plans/{plan_id}/publish")
async def publish_menu_plan(
    plan_id: str = Path(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator: Optional[str] = Header(None, alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
):
    """发布方案：draft → published。"""
    tid = await _set_tenant(db, x_tenant_id)
    try:
        pid = uuid.UUID(plan_id)
    except ValueError:
        _err(400, "无效的 plan_id")

    plan = await _fetch_plan(db, pid, tid)
    if plan["status"] != "draft":
        _err(400, f"只有草稿状态的方案可以发布，当前状态: {plan['status']}")

    # 校验：方案至少有一个品项
    count_res = await db.execute(
        text("SELECT COUNT(*) FROM menu_plan_v2_items WHERE plan_id = :pid AND tenant_id = :tid"),
        {"pid": pid, "tid": tid},
    )
    item_count = count_res.scalar() or 0
    if item_count == 0:
        _err(400, "方案中至少需要有一个菜品才能发布")

    now = datetime.now(timezone.utc)
    await db.execute(
        text("""
            UPDATE menu_plans_v2
            SET status = 'published', published_at = :now, published_by = :operator, updated_at = :now
            WHERE id = :pid AND tenant_id = :tid
        """),
        {"now": now, "operator": x_operator, "pid": pid, "tid": tid},
    )
    await db.commit()

    log.info("menu_plan_v2.published", plan_id=plan_id, tenant_id=x_tenant_id)

    asyncio.create_task(emit_event(
        event_type=MenuEventType.PLAN_DISTRIBUTED,
        tenant_id=tid,
        stream_id=plan_id,
        payload={"plan_id": plan_id, "operator": x_operator, "action": "publish"},
        source_service="tx-menu",
        metadata={"operator_id": x_operator or ""},
    ))

    return {
        "ok": True,
        "data": {
            "plan_id": plan_id,
            "status": "published",
            "published_at": now.isoformat(),
        },
    }


async def _execute_push_task(
    task_id: uuid.UUID,
    plan_id: uuid.UUID,
    store_ids: list[uuid.UUID],
    override_store_settings: bool,
    tid: uuid.UUID,
    db_factory,
):
    """后台任务：逐门店推送菜谱方案，写入 menu_push_logs。"""
    from shared.ontology.src.database import AsyncSessionLocal

    async with AsyncSessionLocal() as bg_db:
        try:
            await bg_db.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": str(tid)},
            )
        except Exception:
            log.warning("push_task.set_tenant_failed", task_id=str(task_id))

        success = 0
        failed = 0

        for store_id in store_ids:
            try:
                # 写入/更新门店激活方案
                await bg_db.execute(
                    text("""
                        INSERT INTO menu_store_active_plans
                          (tenant_id, store_id, plan_id, is_active, activated_at, override_store_settings)
                        VALUES (:tid, :store_id, :plan_id, TRUE, now(), :override)
                        ON CONFLICT (tenant_id, store_id)
                        DO UPDATE SET
                          plan_id                = EXCLUDED.plan_id,
                          is_active              = TRUE,
                          activated_at           = now(),
                          override_store_settings = EXCLUDED.override_store_settings
                    """),
                    {
                        "tid": tid,
                        "store_id": store_id,
                        "plan_id": plan_id,
                        "override": override_store_settings,
                    },
                )

                # 写推送日志
                await bg_db.execute(
                    text("""
                        INSERT INTO menu_push_logs
                          (tenant_id, task_id, plan_id, store_id, status, pushed_at)
                        VALUES (:tid, :task_id, :plan_id, :store_id, 'success', now())
                        ON CONFLICT (task_id, store_id)
                        DO UPDATE SET status = 'success', pushed_at = now(), error_message = NULL
                    """),
                    {"tid": tid, "task_id": task_id, "plan_id": plan_id, "store_id": store_id},
                )
                success += 1

            except Exception as exc:
                log.error("push_task.store_failed", store_id=str(store_id), error=str(exc))
                try:
                    await bg_db.execute(
                        text("""
                            INSERT INTO menu_push_logs
                              (tenant_id, task_id, plan_id, store_id, status, error_message, pushed_at)
                            VALUES (:tid, :task_id, :plan_id, :store_id, 'failed', :err, now())
                            ON CONFLICT (task_id, store_id)
                            DO UPDATE SET status = 'failed', error_message = :err, pushed_at = now()
                        """),
                        {
                            "tid": tid,
                            "task_id": task_id,
                            "plan_id": plan_id,
                            "store_id": store_id,
                            "err": str(exc)[:500],
                        },
                    )
                except Exception as log_exc:
                    log.error("push_task.log_failed", error=str(log_exc))
                failed += 1

        await bg_db.commit()
        log.info(
            "push_task.completed",
            task_id=str(task_id),
            total=len(store_ids),
            success=success,
            failed=failed,
        )


@router.post("/api/v1/menu-plans/{plan_id}/push", status_code=202)
async def push_menu_plan(
    req: PushMenuPlanReq,
    background_tasks: BackgroundTasks,
    plan_id: str = Path(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator: Optional[str] = Header(None, alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
):
    """批量推送菜谱方案到门店。使用 BackgroundTasks 异步执行，立即返回 task_id。"""
    tid = await _set_tenant(db, x_tenant_id)
    try:
        pid = uuid.UUID(plan_id)
    except ValueError:
        _err(400, "无效的 plan_id")

    plan = await _fetch_plan(db, pid, tid)
    if plan["status"] != "published":
        _err(400, "只有已发布的方案才能推送到门店")

    # 校验定时推送参数
    scheduled_dt = None
    if req.push_mode == "scheduled":
        if not req.scheduled_at:
            _err(400, "push_mode=scheduled 时必须提供 scheduled_at")
        try:
            scheduled_dt = datetime.fromisoformat(req.scheduled_at.replace("Z", "+00:00"))
        except ValueError:
            _err(400, "无效的 scheduled_at 格式，应为 ISO8601")

    # 解析目标门店列表
    store_uuids: list[uuid.UUID] = []
    if req.store_ids:
        for sid_str in req.store_ids:
            try:
                store_uuids.append(uuid.UUID(sid_str))
            except ValueError:
                _err(400, f"无效的 store_id: {sid_str}")
    else:
        # 推送到品牌全部门店
        brand_id = plan["brand_id"]
        if not brand_id:
            _err(400, "方案未关联品牌，无法自动获取门店列表，请指定 store_ids")
        try:
            brand_uuid = uuid.UUID(brand_id)
        except ValueError:
            _err(400, "方案 brand_id 格式无效")
        stores_res = await db.execute(
            text("""
                SELECT id FROM stores
                WHERE brand_id = :brand_id AND tenant_id = :tid AND is_deleted IS NOT TRUE
            """),
            {"brand_id": brand_uuid, "tid": tid},
        )
        store_uuids = [row[0] for row in stores_res.fetchall()]

    if not store_uuids:
        _err(400, "未找到任何目标门店")

    total_stores = len(store_uuids)
    task_id = uuid.uuid4()

    # 创建推送任务记录
    await db.execute(
        text("""
            INSERT INTO menu_push_tasks
              (id, tenant_id, plan_id, total_stores, push_mode, scheduled_at,
               override_store_settings, created_by)
            VALUES (:id, :tid, :plan_id, :total, :mode, :sched_at, :override, :operator)
        """),
        {
            "id": task_id,
            "tid": tid,
            "plan_id": pid,
            "total": total_stores,
            "mode": req.push_mode,
            "sched_at": scheduled_dt,
            "override": req.override_store_settings,
            "operator": x_operator,
        },
    )

    # 预创建 pending 日志
    for store_uuid in store_uuids:
        await db.execute(
            text("""
                INSERT INTO menu_push_logs
                  (tenant_id, task_id, plan_id, store_id, status)
                VALUES (:tid, :task_id, :plan_id, :store_id, 'pending')
                ON CONFLICT (task_id, store_id) DO NOTHING
            """),
            {"tid": tid, "task_id": task_id, "plan_id": pid, "store_id": store_uuid},
        )

    await db.commit()

    # 立即模式：加入后台任务；定时模式：记录待执行（生产环境由调度器触发）
    if req.push_mode == "immediate":
        background_tasks.add_task(
            _execute_push_task,
            task_id,
            pid,
            store_uuids,
            req.override_store_settings,
            tid,
            None,
        )

    log.info(
        "menu_plan_v2.push_queued",
        plan_id=plan_id,
        task_id=str(task_id),
        total_stores=total_stores,
        push_mode=req.push_mode,
        tenant_id=x_tenant_id,
    )

    return {
        "ok": True,
        "data": {
            "task_id": str(task_id),
            "total_stores": total_stores,
            "queued_count": total_stores if req.push_mode == "immediate" else 0,
            "push_mode": req.push_mode,
            "scheduled_at": req.scheduled_at,
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# B. 门店Override机制
# ══════════════════════════════════════════════════════════════════════════════


@router.post("/api/v1/menu-plans/store-overrides/{store_id}", status_code=201)
async def create_store_override(
    req: StoreOverrideReq,
    store_id: str = Path(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator: Optional[str] = Header(None, alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
):
    """创建门店Override：允许门店在品牌方案基础上修改特定菜品的价格/可用状态/份量。"""
    tid = await _set_tenant(db, x_tenant_id)
    try:
        store_uuid = uuid.UUID(store_id)
    except ValueError:
        _err(400, "无效的 store_id")
    try:
        dish_uuid = uuid.UUID(req.dish_id)
    except ValueError:
        _err(400, "无效的 dish_id")

    valid_from = None
    valid_until = None
    if req.valid_from:
        try:
            from datetime import date
            valid_from = date.fromisoformat(req.valid_from)
        except ValueError:
            _err(400, "无效的 valid_from 格式，应为 YYYY-MM-DD")
    if req.valid_until:
        try:
            from datetime import date
            valid_until = date.fromisoformat(req.valid_until)
        except ValueError:
            _err(400, "无效的 valid_until 格式，应为 YYYY-MM-DD")

    override_id = uuid.uuid4()
    await db.execute(
        text("""
            INSERT INTO menu_plan_store_overrides
              (id, tenant_id, store_id, dish_id, override_type, value,
               reason, valid_from, valid_until, created_by)
            VALUES (:id, :tid, :store_id, :dish_id, :otype, :value,
                    :reason, :vf, :vu, :operator)
        """),
        {
            "id": override_id,
            "tid": tid,
            "store_id": store_uuid,
            "dish_id": dish_uuid,
            "otype": req.override_type,
            "value": req.value,
            "reason": req.reason,
            "vf": valid_from,
            "vu": valid_until,
            "operator": x_operator,
        },
    )
    await db.commit()

    log.info(
        "store_override_v2.created",
        override_id=str(override_id),
        store_id=store_id,
        dish_id=req.dish_id,
        override_type=req.override_type,
        tenant_id=x_tenant_id,
    )

    asyncio.create_task(emit_event(
        event_type=MenuEventType.STORE_OVERRIDE_SET,
        tenant_id=tid,
        stream_id=store_id,
        payload={
            "store_id": store_id,
            "dish_id": req.dish_id,
            "override_type": req.override_type,
            "operator": x_operator,
        },
        store_id=store_id,
        source_service="tx-menu",
        metadata={"operator_id": x_operator or ""},
    ))

    return {
        "ok": True,
        "data": {
            "id": str(override_id),
            "store_id": store_id,
            "dish_id": req.dish_id,
            "override_type": req.override_type,
        },
    }


@router.delete("/api/v1/menu-plans/store-overrides/{store_id}/{override_id}", status_code=200)
async def delete_store_override(
    store_id: str = Path(...),
    override_id: str = Path(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator: Optional[str] = Header(None, alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
):
    """撤销Override，恢复到品牌方案配置。"""
    tid = await _set_tenant(db, x_tenant_id)
    try:
        store_uuid = uuid.UUID(store_id)
        override_uuid = uuid.UUID(override_id)
    except ValueError:
        _err(400, "无效的 store_id 或 override_id")

    result = await db.execute(
        text("""
            UPDATE menu_plan_store_overrides
            SET is_deleted = TRUE, updated_at = now()
            WHERE id = :oid AND store_id = :store_id AND tenant_id = :tid AND is_deleted IS NOT TRUE
        """),
        {"oid": override_uuid, "store_id": store_uuid, "tid": tid},
    )
    if result.rowcount == 0:
        _err(404, "Override 不存在或已撤销")

    await db.commit()
    log.info(
        "store_override_v2.deleted",
        override_id=override_id,
        store_id=store_id,
        tenant_id=x_tenant_id,
    )

    asyncio.create_task(emit_event(
        event_type=MenuEventType.STORE_OVERRIDE_RESET,
        tenant_id=tid,
        stream_id=store_id,
        payload={"store_id": store_id, "override_id": override_id, "operator": x_operator},
        store_id=store_id,
        source_service="tx-menu",
        metadata={"operator_id": x_operator or ""},
    ))

    return {"ok": True, "data": {"override_id": override_id, "revoked": True}}
