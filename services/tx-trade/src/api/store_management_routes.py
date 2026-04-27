"""门店管理 & 桌台配置 API

端点（10个）：
  GET    /api/v1/trade/stores                — 门店列表
  POST   /api/v1/trade/stores                — 新增门店
  GET    /api/v1/trade/stores/{store_id}     — 门店详情
  PATCH  /api/v1/trade/stores/{store_id}     — 更新门店状态
  DELETE /api/v1/trade/stores/{store_id}     — 删除门店（软删）

  GET    /api/v1/trade/tables                — 桌台列表（按 store_id 过滤）
  POST   /api/v1/trade/tables                — 新增桌台
  GET    /api/v1/trade/tables/{table_id}     — 桌台详情
  PATCH  /api/v1/trade/tables/{table_id}     — 修改桌台
  DELETE /api/v1/trade/tables/{table_id}     — 删除桌台（软删）

统一响应格式: {"ok": bool, "data": {}, "error": None}
所有接口需 X-Tenant-ID header。

DB 表说明：
  stores.store_name        ↔ API name
  stores.operation_mode    ↔ API type  (direct / franchise)
  tables.table_no          ↔ API number
  tables.seats             ↔ API capacity
  tables.config->>shape    ↔ API shape
  tables.config->>note     ↔ API note
"""

import json
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(tags=["store-management"])


# ─── 工具 ──────────────────────────────────────────────────────────────────────


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    """在当前 DB 会话中设置 RLS app.tenant_id。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _row_to_store(row) -> dict:
    """将 stores 行映射为 API 响应字典。"""
    d = dict(row._mapping)
    # 字段别名：store_name → name，operation_mode → type
    d["name"] = d.pop("store_name", "")
    d["type"] = d.pop("operation_mode", "direct") or "direct"
    # 将 UUID/datetime 转为字符串
    for k in ("id", "tenant_id", "manager_id"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    for k in ("created_at", "updated_at"):
        if d.get(k) is not None:
            d[k] = d[k].isoformat()
    return d


def _row_to_table(row) -> dict:
    """将 tables 行映射为 API 响应字典。"""
    d = dict(row._mapping)
    # 字段别名：table_no → number，seats → capacity
    d["number"] = d.pop("table_no", "")
    d["capacity"] = d.pop("seats", 0)
    # 从 config JSON 提取 shape / note
    config = d.pop("config", None) or {}
    d["shape"] = config.get("shape", "square")
    d["note"] = config.get("note", "")
    # 将 UUID/datetime 转为字符串
    for k in ("id", "tenant_id", "store_id"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    for k in ("created_at", "updated_at"):
        if d.get(k) is not None:
            d[k] = d[k].isoformat()
    return d


# ─── 请求/响应模型 ─────────────────────────────────────────────────────────────


class StoreCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    type: str = Field("direct", pattern="^(direct|franchise)$")
    city: str = Field(..., min_length=1, max_length=32)
    address: str = Field(..., min_length=1, max_length=128)
    status: str = Field("active", pattern="^(active|suspended)$")
    manager: str = Field("", max_length=32)
    phone: Optional[str] = Field(None, max_length=20)


class StorePatch(BaseModel):
    status: Optional[str] = Field(None, pattern="^(active|suspended)$")
    name: Optional[str] = Field(None, max_length=64)
    manager: Optional[str] = Field(None, max_length=32)
    phone: Optional[str] = Field(None, max_length=20)
    address: Optional[str] = Field(None, max_length=128)


class TableCreate(BaseModel):
    store_id: str
    number: str = Field(..., min_length=1, max_length=16)
    area: str = Field("大厅", max_length=16)
    capacity: int = Field(4, ge=1, le=30)
    shape: str = Field("square", pattern="^(square|round|rectangle)$")
    note: Optional[str] = Field("", max_length=128)


class TablePatch(BaseModel):
    number: Optional[str] = Field(None, max_length=16)
    area: Optional[str] = Field(None, max_length=16)
    capacity: Optional[int] = Field(None, ge=1, le=30)
    shape: Optional[str] = Field(None, pattern="^(square|round|rectangle)$")
    status: Optional[str] = Field(None, pattern="^(available|occupied|reserved|cleaning)$")
    note: Optional[str] = Field(None, max_length=128)


# ─── 门店端点 ──────────────────────────────────────────────────────────────────


@router.get("/api/v1/trade/stores")
async def list_stores(
    request: Request,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """门店列表（支持按状态/类型/城市过滤）"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    conditions = ["is_deleted = false"]
    params: dict = {}
    if status:
        conditions.append("status = :status")
        params["status"] = status
    if type:
        conditions.append("operation_mode = :type")
        params["type"] = type
    if city:
        conditions.append("city = :city")
        params["city"] = city

    where = " AND ".join(conditions)
    offset = (page - 1) * size

    try:
        count_res = await db.execute(
            text(f"SELECT COUNT(*) FROM stores WHERE {where}"),
            params,
        )
        total = count_res.scalar() or 0

        rows = await db.execute(
            text(
                f"SELECT id, tenant_id, store_name, store_code, city, address, status,"
                f" phone, operation_mode, is_deleted, created_at, updated_at"
                f" FROM stores WHERE {where}"
                f" ORDER BY created_at DESC LIMIT :size OFFSET :offset"
            ),
            {**params, "size": size, "offset": offset},
        )
        items = [_row_to_store(r) for r in rows]
    except SQLAlchemyError:
        items = []
        total = 0

    return _ok({"items": items, "total": total, "page": page, "size": size})


@router.post("/api/v1/trade/stores", status_code=201)
async def create_store(
    request: Request,
    body: StoreCreate,
    db: AsyncSession = Depends(get_db),
):
    """新增门店"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    new_id = str(uuid.uuid4())
    store_code = "S-" + new_id[:8].upper()

    try:
        row = await db.execute(
            text("""
                INSERT INTO stores
                    (id, tenant_id, store_name, store_code, city, address, status,
                     phone, operation_mode, is_deleted)
                VALUES
                    (:id, :tenant_id, :store_name, :store_code, :city, :address, :status,
                     :phone, :operation_mode, false)
                RETURNING id, tenant_id, store_name, store_code, city, address, status,
                          phone, operation_mode, is_deleted, created_at, updated_at
            """),
            {
                "id": new_id,
                "tenant_id": tenant_id,
                "store_name": body.name,
                "store_code": store_code,
                "city": body.city,
                "address": body.address,
                "status": body.status,
                "phone": body.phone or "",
                "operation_mode": body.type,
            },
        )
        await db.commit()
        store = _row_to_store(row.one())
        return _ok(store)
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=503, detail=f"门店创建失败: {exc}")


@router.get("/api/v1/trade/stores/{store_id}")
async def get_store(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """门店详情"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        row = await db.execute(
            text("""
                SELECT id, tenant_id, store_name, store_code, city, address, status,
                       phone, operation_mode, is_deleted, created_at, updated_at
                FROM stores
                WHERE id = :store_id AND is_deleted = false
            """),
            {"store_id": store_id},
        )
        rec = row.one_or_none()
    except SQLAlchemyError:
        rec = None

    if rec is None:
        raise HTTPException(status_code=404, detail="Store not found")
    return _ok(_row_to_store(rec))


@router.patch("/api/v1/trade/stores/{store_id}")
async def patch_store(
    store_id: str,
    body: StorePatch,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """更新门店信息/状态"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    # 先确认存在
    try:
        exists = await db.execute(
            text("SELECT id FROM stores WHERE id = :store_id AND is_deleted = false"),
            {"store_id": store_id},
        )
        if exists.one_or_none() is None:
            raise HTTPException(status_code=404, detail="Store not found")
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="查询门店失败")

    # 构建 SET 片段
    set_parts = ["updated_at = NOW()"]
    params: dict = {"store_id": store_id}

    if body.name is not None:
        set_parts.append("store_name = :store_name")
        params["store_name"] = body.name
    if body.status is not None:
        set_parts.append("status = :status")
        params["status"] = body.status
    if body.phone is not None:
        set_parts.append("phone = :phone")
        params["phone"] = body.phone
    if body.address is not None:
        set_parts.append("address = :address")
        params["address"] = body.address

    try:
        row = await db.execute(
            text(
                f"UPDATE stores SET {', '.join(set_parts)}"
                f" WHERE id = :store_id AND is_deleted = false"
                f" RETURNING id, tenant_id, store_name, store_code, city, address, status,"
                f"           phone, operation_mode, is_deleted, created_at, updated_at"
            ),
            params,
        )
        await db.commit()
        rec = row.one_or_none()
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=503, detail=f"门店更新失败: {exc}")

    if rec is None:
        raise HTTPException(status_code=404, detail="Store not found")
    return _ok(_row_to_store(rec))


@router.delete("/api/v1/trade/stores/{store_id}")
async def delete_store(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """软删除门店"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        row = await db.execute(
            text("""
                UPDATE stores
                SET is_deleted = true, updated_at = NOW()
                WHERE id = :store_id AND is_deleted = false
                RETURNING id
            """),
            {"store_id": store_id},
        )
        await db.commit()
        rec = row.one_or_none()
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=503, detail=f"门店删除失败: {exc}")

    if rec is None:
        raise HTTPException(status_code=404, detail="Store not found")
    return _ok({"message": "Store deleted", "id": store_id})


# ─── 桌台端点 ──────────────────────────────────────────────────────────────────


@router.get("/api/v1/trade/tables")
async def list_tables(
    request: Request,
    store_id: Optional[str] = Query(None),
    area: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """桌台列表（按 store_id / area / status 过滤）"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    conditions = ["is_deleted = false"]
    params: dict = {}
    if store_id:
        conditions.append("store_id = :store_id")
        params["store_id"] = store_id
    if area:
        conditions.append("area = :area")
        params["area"] = area
    if status:
        conditions.append("status = :status")
        params["status"] = status

    where = " AND ".join(conditions)
    offset = (page - 1) * size

    try:
        count_res = await db.execute(
            text(f"SELECT COUNT(*) FROM tables WHERE {where}"),
            params,
        )
        total = count_res.scalar() or 0

        rows = await db.execute(
            text(
                f"SELECT id, tenant_id, store_id, table_no, area, seats, status,"
                f" config, is_deleted, created_at, updated_at"
                f" FROM tables WHERE {where}"
                f" ORDER BY sort_order, table_no LIMIT :size OFFSET :offset"
            ),
            {**params, "size": size, "offset": offset},
        )
        items = [_row_to_table(r) for r in rows]
    except SQLAlchemyError:
        items = []
        total = 0

    return _ok({"items": items, "total": total, "page": page, "size": size})


@router.post("/api/v1/trade/tables", status_code=201)
async def create_table(
    request: Request,
    body: TableCreate,
    db: AsyncSession = Depends(get_db),
):
    """新增桌台"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    # 校验门店存在且属于本租户
    try:
        store_check = await db.execute(
            text("SELECT id FROM stores WHERE id = :store_id AND is_deleted = false"),
            {"store_id": body.store_id},
        )
        if store_check.one_or_none() is None:
            raise HTTPException(status_code=404, detail="Store not found")
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="门店查询失败")

    new_id = str(uuid.uuid4())
    config = {"shape": body.shape, "note": body.note or ""}

    try:
        row = await db.execute(
            text("""
                INSERT INTO tables
                    (id, tenant_id, store_id, table_no, area, seats, status, config, is_deleted)
                VALUES
                    (:id, :tenant_id, :store_id, :table_no, :area, :seats, 'available', :config, false)
                RETURNING id, tenant_id, store_id, table_no, area, seats, status,
                          config, is_deleted, created_at, updated_at
            """),
            {
                "id": new_id,
                "tenant_id": tenant_id,
                "store_id": body.store_id,
                "table_no": body.number,
                "area": body.area,
                "seats": body.capacity,
                "config": json.dumps(config),
            },
        )
        await db.commit()
        table = _row_to_table(row.one())
        return _ok(table)
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=503, detail=f"桌台创建失败: {exc}")


@router.get("/api/v1/trade/tables/{table_id}")
async def get_table(
    table_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """桌台详情"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        row = await db.execute(
            text("""
                SELECT id, tenant_id, store_id, table_no, area, seats, status,
                       config, is_deleted, created_at, updated_at
                FROM tables
                WHERE id = :table_id AND is_deleted = false
            """),
            {"table_id": table_id},
        )
        rec = row.one_or_none()
    except SQLAlchemyError:
        rec = None

    if rec is None:
        raise HTTPException(status_code=404, detail="Table not found")
    return _ok(_row_to_table(rec))


@router.patch("/api/v1/trade/tables/{table_id}")
async def patch_table(
    table_id: str,
    body: TablePatch,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """修改桌台配置"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    # 先读取现有行以便合并 config
    try:
        existing_row = await db.execute(
            text("""
                SELECT id, config FROM tables
                WHERE id = :table_id AND is_deleted = false
            """),
            {"table_id": table_id},
        )
        existing = existing_row.one_or_none()
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="桌台查询失败")

    if existing is None:
        raise HTTPException(status_code=404, detail="Table not found")

    # 合并 config（shape / note 存在 config JSON 中）
    current_config: dict = {}
    if existing.config:
        try:
            current_config = json.loads(existing.config) if isinstance(existing.config, str) else dict(existing.config)
        except (ValueError, TypeError):
            current_config = {}

    set_parts = ["updated_at = NOW()"]
    params: dict = {"table_id": table_id}

    if body.number is not None:
        set_parts.append("table_no = :table_no")
        params["table_no"] = body.number
    if body.area is not None:
        set_parts.append("area = :area")
        params["area"] = body.area
    if body.capacity is not None:
        set_parts.append("seats = :seats")
        params["seats"] = body.capacity
    if body.status is not None:
        set_parts.append("status = :status")
        params["status"] = body.status
    if body.shape is not None:
        current_config["shape"] = body.shape
    if body.note is not None:
        current_config["note"] = body.note

    # 如果 shape/note 有变更，写回 config
    if body.shape is not None or body.note is not None:
        set_parts.append("config = :config")
        params["config"] = json.dumps(current_config)

    try:
        row = await db.execute(
            text(
                f"UPDATE tables SET {', '.join(set_parts)}"
                f" WHERE id = :table_id AND is_deleted = false"
                f" RETURNING id, tenant_id, store_id, table_no, area, seats, status,"
                f"           config, is_deleted, created_at, updated_at"
            ),
            params,
        )
        await db.commit()
        rec = row.one_or_none()
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=503, detail=f"桌台更新失败: {exc}")

    if rec is None:
        raise HTTPException(status_code=404, detail="Table not found")
    return _ok(_row_to_table(rec))


@router.delete("/api/v1/trade/tables/{table_id}")
async def delete_table(
    table_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """软删除桌台"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        row = await db.execute(
            text("""
                UPDATE tables
                SET is_deleted = true, updated_at = NOW()
                WHERE id = :table_id AND is_deleted = false
                RETURNING id
            """),
            {"table_id": table_id},
        )
        await db.commit()
        rec = row.one_or_none()
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=503, detail=f"桌台删除失败: {exc}")

    if rec is None:
        raise HTTPException(status_code=404, detail="Table not found")
    return _ok({"message": "Table deleted", "id": table_id})
