"""菜品→档口映射管理 API

dish_dept_mappings 表（v115 创建）：
  id, tenant_id, store_id(可NULL=集团通用), dish_id, dept_id, dept_name,
  is_primary, priority, created_at, updated_at, is_deleted

端点：
  GET    /api/v1/kds/dish-dept-mappings                      查询映射列表
  POST   /api/v1/kds/dish-dept-mappings                      创建/更新映射（upsert）
  DELETE /api/v1/kds/dish-dept-mappings/{mapping_id}         软删除映射
  POST   /api/v1/kds/dish-dept-mappings/batch                批量导入
  GET    /api/v1/kds/dish-dept-mappings/by-dish/{dish_id}    查询某菜品的所有映射
  GET    /api/v1/kds/departments                             查询门店档口列表
"""

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/kds", tags=["dish-dept-mapping"])


# ─── 工具函数 ─────────────────────────────────────────────────────────────────


def _tenant(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data) -> dict:
    return {"ok": True, "data": data, "error": None}


async def _rls(db: AsyncSession, tid: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tid})


def _row_to_mapping(row) -> dict:
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "store_id": str(row.store_id) if row.store_id else None,
        "dish_id": str(row.dish_id),
        "dept_id": str(row.dept_id),
        "dept_name": row.dept_name,
        "is_primary": row.is_primary,
        "priority": row.priority,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


# ─── 请求模型 ─────────────────────────────────────────────────────────────────


class MappingCreateReq(BaseModel):
    dish_id: str = Field(..., description="菜品ID")
    dept_id: str = Field(..., description="档口ID")
    dept_name: str = Field(..., description="档口名称")
    store_id: Optional[str] = Field(default=None, description="门店ID，NULL=集团通用")
    is_primary: bool = Field(default=False, description="是否主出品档口")
    priority: int = Field(default=0, description="优先级，数字越小越优先")


class BatchMappingItem(BaseModel):
    dish_id: str
    dept_id: str
    dept_name: str
    store_id: Optional[str] = None
    is_primary: bool = False
    priority: int = 0


class BatchMappingReq(BaseModel):
    mappings: list[BatchMappingItem] = Field(..., min_length=1, max_length=500)
    store_id: Optional[str] = Field(default=None, description="批量操作统一门店ID（可被单条覆盖）")
    replace_existing: bool = Field(
        default=False,
        description="True=先删除该store_id下所有现有映射，再批量插入（全量替换模式）",
    )


# ─── GET /dish-dept-mappings ──────────────────────────────────────────────────


@router.get("/dish-dept-mappings", summary="查询菜品-档口映射列表")
async def list_dish_dept_mappings(
    request: Request,
    store_id: Optional[str] = Query(default=None, description="门店ID，不传=查全部（含集团通用）"),
    dept_id: Optional[str] = Query(default=None, description="档口ID过滤"),
    dish_id: Optional[str] = Query(default=None, description="菜品ID过滤"),
    is_primary: Optional[bool] = Query(default=None, description="是否只查主档口"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tid = _tenant(request)
    await _rls(db, tid)

    conditions = [
        "m.tenant_id = :tenant_id",
        "m.is_deleted = false",
    ]
    params: dict = {"tenant_id": tid, "offset": (page - 1) * size, "limit": size}

    if store_id:
        conditions.append("(m.store_id = :store_id OR m.store_id IS NULL)")
        params["store_id"] = store_id
    if dept_id:
        conditions.append("m.dept_id = :dept_id")
        params["dept_id"] = dept_id
    if dish_id:
        conditions.append("m.dish_id = :dish_id")
        params["dish_id"] = dish_id
    if is_primary is not None:
        conditions.append("m.is_primary = :is_primary")
        params["is_primary"] = is_primary

    where_clause = " AND ".join(conditions)

    count_sql = text(f"SELECT COUNT(*) FROM dish_dept_mappings m WHERE {where_clause}")
    count_result = await db.execute(count_sql, params)
    total = count_result.scalar() or 0

    list_sql = text(f"""
        SELECT m.id, m.tenant_id, m.store_id, m.dish_id, m.dept_id, m.dept_name,
               m.is_primary, m.priority, m.created_at, m.updated_at
        FROM dish_dept_mappings m
        WHERE {where_clause}
        ORDER BY m.is_primary DESC, m.priority ASC, m.created_at DESC
        LIMIT :limit OFFSET :offset
    """)
    result = await db.execute(list_sql, params)
    rows = result.fetchall()

    items = [_row_to_mapping(r) for r in rows]
    return _ok({"items": items, "total": total, "page": page, "size": size})


# ─── POST /dish-dept-mappings ─────────────────────────────────────────────────


@router.post("/dish-dept-mappings", summary="创建/更新菜品-档口映射（upsert）")
async def upsert_dish_dept_mapping(
    req: MappingCreateReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """按 tenant_id + dish_id + dept_id 做 upsert。

    同一菜品+同一档口只保留一条记录，重复插入时更新字段。
    """
    tid = _tenant(request)
    await _rls(db, tid)

    now_sql = text("SELECT NOW()")
    now_result = await db.execute(now_sql)
    now = now_result.scalar()

    # 检查是否已存在（含软删除的）
    check_sql = text("""
        SELECT id, is_deleted FROM dish_dept_mappings
        WHERE tenant_id = :tenant_id
          AND dish_id = :dish_id
          AND dept_id = :dept_id
          AND (store_id = :store_id OR (store_id IS NULL AND :store_id IS NULL))
        LIMIT 1
    """)
    check_result = await db.execute(
        check_sql,
        {
            "tenant_id": tid,
            "dish_id": req.dish_id,
            "dept_id": req.dept_id,
            "store_id": req.store_id,
        },
    )
    existing = check_result.fetchone()

    if existing:
        mapping_id = existing.id
        update_sql = text("""
            UPDATE dish_dept_mappings
            SET dept_name  = :dept_name,
                is_primary = :is_primary,
                priority   = :priority,
                is_deleted = false,
                updated_at = :now
            WHERE id = :id
            RETURNING id, tenant_id, store_id, dish_id, dept_id, dept_name,
                      is_primary, priority, created_at, updated_at
        """)
        result = await db.execute(
            update_sql,
            {
                "dept_name": req.dept_name,
                "is_primary": req.is_primary,
                "priority": req.priority,
                "now": now,
                "id": mapping_id,
            },
        )
        row = result.fetchone()
        action = "updated"
    else:
        new_id = str(uuid.uuid4())
        insert_sql = text("""
            INSERT INTO dish_dept_mappings
              (id, tenant_id, store_id, dish_id, dept_id, dept_name,
               is_primary, priority, created_at, updated_at, is_deleted)
            VALUES
              (:id, :tenant_id, :store_id, :dish_id, :dept_id, :dept_name,
               :is_primary, :priority, :now, :now, false)
            RETURNING id, tenant_id, store_id, dish_id, dept_id, dept_name,
                      is_primary, priority, created_at, updated_at
        """)
        result = await db.execute(
            insert_sql,
            {
                "id": new_id,
                "tenant_id": tid,
                "store_id": req.store_id,
                "dish_id": req.dish_id,
                "dept_id": req.dept_id,
                "dept_name": req.dept_name,
                "is_primary": req.is_primary,
                "priority": req.priority,
                "now": now,
            },
        )
        row = result.fetchone()
        action = "created"

    await db.commit()
    logger.info("dish_dept_mapping_upsert", action=action, dish_id=req.dish_id, dept_id=req.dept_id)
    return _ok({"mapping": _row_to_mapping(row), "action": action})


# ─── DELETE /dish-dept-mappings/{mapping_id} ─────────────────────────────────


@router.delete("/dish-dept-mappings/{mapping_id}", summary="软删除菜品-档口映射")
async def delete_dish_dept_mapping(
    mapping_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tid = _tenant(request)
    await _rls(db, tid)

    # 校验存在性
    check_sql = text("""
        SELECT id FROM dish_dept_mappings
        WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = false
    """)
    check_result = await db.execute(check_sql, {"id": mapping_id, "tenant_id": tid})
    if not check_result.fetchone():
        raise HTTPException(status_code=404, detail="映射记录不存在或已删除")

    del_sql = text("""
        UPDATE dish_dept_mappings
        SET is_deleted = true, updated_at = NOW()
        WHERE id = :id AND tenant_id = :tenant_id
    """)
    await db.execute(del_sql, {"id": mapping_id, "tenant_id": tid})
    await db.commit()

    logger.info("dish_dept_mapping_deleted", mapping_id=mapping_id)
    return _ok({"mapping_id": mapping_id, "deleted": True})


# ─── POST /dish-dept-mappings/batch ──────────────────────────────────────────


@router.post("/dish-dept-mappings/batch", summary="批量导入菜品-档口映射")
async def batch_set_dish_dept_mappings(
    req: BatchMappingReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """批量 upsert 菜品→档口映射。

    replace_existing=True：先软删除 store_id 下所有现有映射，再全量插入。
    replace_existing=False：逐条 upsert，不删除未出现的映射。
    """
    tid = _tenant(request)
    await _rls(db, tid)

    now_sql = text("SELECT NOW()")
    now_result = await db.execute(now_sql)
    now = now_result.scalar()

    if req.replace_existing and req.store_id:
        del_sql = text("""
            UPDATE dish_dept_mappings
            SET is_deleted = true, updated_at = :now
            WHERE tenant_id = :tenant_id
              AND store_id = :store_id
              AND is_deleted = false
        """)
        await db.execute(del_sql, {"tenant_id": tid, "store_id": req.store_id, "now": now})

    created_count = 0
    updated_count = 0
    errors = []

    for idx, item in enumerate(req.mappings):
        effective_store_id = item.store_id or req.store_id
        try:
            check_sql = text("""
                SELECT id, is_deleted FROM dish_dept_mappings
                WHERE tenant_id = :tenant_id
                  AND dish_id   = :dish_id
                  AND dept_id   = :dept_id
                  AND (store_id = :store_id OR (store_id IS NULL AND :store_id IS NULL))
                LIMIT 1
            """)
            check_result = await db.execute(
                check_sql,
                {
                    "tenant_id": tid,
                    "dish_id": item.dish_id,
                    "dept_id": item.dept_id,
                    "store_id": effective_store_id,
                },
            )
            existing = check_result.fetchone()

            if existing:
                upd_sql = text("""
                    UPDATE dish_dept_mappings
                    SET dept_name  = :dept_name,
                        is_primary = :is_primary,
                        priority   = :priority,
                        is_deleted = false,
                        updated_at = :now
                    WHERE id = :id
                """)
                await db.execute(
                    upd_sql,
                    {
                        "dept_name": item.dept_name,
                        "is_primary": item.is_primary,
                        "priority": item.priority,
                        "now": now,
                        "id": existing.id,
                    },
                )
                updated_count += 1
            else:
                ins_sql = text("""
                    INSERT INTO dish_dept_mappings
                      (id, tenant_id, store_id, dish_id, dept_id, dept_name,
                       is_primary, priority, created_at, updated_at, is_deleted)
                    VALUES
                      (:id, :tenant_id, :store_id, :dish_id, :dept_id, :dept_name,
                       :is_primary, :priority, :now, :now, false)
                """)
                await db.execute(
                    ins_sql,
                    {
                        "id": str(uuid.uuid4()),
                        "tenant_id": tid,
                        "store_id": effective_store_id,
                        "dish_id": item.dish_id,
                        "dept_id": item.dept_id,
                        "dept_name": item.dept_name,
                        "is_primary": item.is_primary,
                        "priority": item.priority,
                        "now": now,
                    },
                )
                created_count += 1
        except Exception as exc:  # noqa: BLE001 — 批量操作允许部分失败，收集错误
            errors.append({"index": idx, "dish_id": item.dish_id, "error": str(exc)})

    await db.commit()
    logger.info(
        "dish_dept_mapping_batch",
        created=created_count,
        updated=updated_count,
        errors=len(errors),
    )
    return _ok(
        {
            "created": created_count,
            "updated": updated_count,
            "total": len(req.mappings),
            "errors": errors,
        }
    )


# ─── GET /dish-dept-mappings/by-dish/{dish_id} ───────────────────────────────


@router.get("/dish-dept-mappings/by-dish/{dish_id}", summary="查询某菜品的所有档口映射")
async def get_mappings_by_dish(
    dish_id: str,
    request: Request,
    store_id: Optional[str] = Query(default=None, description="门店ID，不传=集团通用"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tid = _tenant(request)
    await _rls(db, tid)

    params: dict = {"tenant_id": tid, "dish_id": dish_id}
    store_filter = ""
    if store_id:
        store_filter = "AND (m.store_id = :store_id OR m.store_id IS NULL)"
        params["store_id"] = store_id

    sql = text(f"""
        SELECT m.id, m.tenant_id, m.store_id, m.dish_id, m.dept_id, m.dept_name,
               m.is_primary, m.priority, m.created_at, m.updated_at
        FROM dish_dept_mappings m
        WHERE m.tenant_id = :tenant_id
          AND m.dish_id   = :dish_id
          AND m.is_deleted = false
          {store_filter}
        ORDER BY m.is_primary DESC, m.priority ASC
    """)
    result = await db.execute(sql, params)
    rows = result.fetchall()

    items = [_row_to_mapping(r) for r in rows]
    return _ok(
        {
            "dish_id": dish_id,
            "mappings": items,
            "total": len(items),
        }
    )


# ─── GET /departments ─────────────────────────────────────────────────────────


@router.get("/departments", summary="查询门店档口列表")
async def list_departments(
    request: Request,
    store_id: Optional[str] = Query(default=None, description="门店ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询档口列表。

    优先从 kds_departments 表查询；若该表不存在或无数据，则
    从 dish_dept_mappings 表聚合 dept_id/dept_name 作为兜底。
    """
    tid = _tenant(request)
    await _rls(db, tid)

    # 尝试从 kds_departments 表查询
    try:
        params: dict = {"tenant_id": tid}
        store_filter = ""
        if store_id:
            store_filter = "AND (d.store_id = :store_id OR d.store_id IS NULL)"
            params["store_id"] = store_id

        dept_sql = text(f"""
            SELECT d.id, d.store_id, d.dept_name, d.dept_code,
                   d.display_order, d.is_active, d.created_at
            FROM kds_departments d
            WHERE d.tenant_id = :tenant_id
              AND d.is_deleted = false
              {store_filter}
            ORDER BY d.display_order ASC, d.created_at ASC
        """)
        result = await db.execute(dept_sql, params)
        rows = result.fetchall()

        if rows:
            items = [
                {
                    "id": str(r.id),
                    "store_id": str(r.store_id) if r.store_id else None,
                    "dept_name": r.dept_name,
                    "dept_code": r.dept_code if hasattr(r, "dept_code") else None,
                    "display_order": r.display_order if hasattr(r, "display_order") else 0,
                    "is_active": r.is_active if hasattr(r, "is_active") else True,
                }
                for r in rows
            ]
            return _ok({"items": items, "total": len(items), "source": "kds_departments"})
    except Exception as exc:  # noqa: BLE001 — kds_departments 表可能不存在，降级处理
        logger.warning("kds_departments_query_failed", error=str(exc))

    # 降级：从 dish_dept_mappings 聚合
    params2: dict = {"tenant_id": tid}
    store_filter2 = ""
    if store_id:
        store_filter2 = "AND (store_id = :store_id OR store_id IS NULL)"
        params2["store_id"] = store_id

    fallback_sql = text(f"""
        SELECT DISTINCT dept_id, dept_name
        FROM dish_dept_mappings
        WHERE tenant_id = :tenant_id
          AND is_deleted = false
          {store_filter2}
        ORDER BY dept_name
    """)
    result2 = await db.execute(fallback_sql, params2)
    rows2 = result2.fetchall()

    items2 = [
        {
            "id": str(r.dept_id),
            "store_id": store_id,
            "dept_name": r.dept_name,
            "dept_code": None,
            "display_order": 0,
            "is_active": True,
        }
        for r in rows2
    ]
    return _ok({"items": items2, "total": len(items2), "source": "dish_dept_mappings"})
