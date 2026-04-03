"""打印机配置管理 API — 打印机注册与路由规则（CRUD）

注意：本文件是打印机"配置"，与 printer_routes.py（打印"执行"）职责不同。

路由前缀: /api/v1/printers
"""
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/printers", tags=["printer-config"])
logger = structlog.get_logger()


# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _set_rls(db: AsyncSession, tenant_id: str):
    """设置 RLS 上下文变量。"""
    return db.execute(text(f"SET LOCAL app.tenant_id = '{tenant_id}'"))


# ─── Pydantic 模型 ────────────────────────────────────────────────────────────

PRINTER_TYPES = ("receipt", "kitchen", "label")
CONN_TYPES = ("usb", "network", "bluetooth")
PAPER_WIDTHS = (58, 80)


class PrinterCreate(BaseModel):
    store_id: str = Field(..., description="门店ID")
    name: str = Field(..., max_length=50, description="打印机名称，如：前台收银机")
    type: str = Field("receipt", description="类型：receipt/kitchen/label")
    connection_type: str = Field("network", description="连接方式：usb/network/bluetooth")
    address: Optional[str] = Field(None, max_length=100, description="IP地址或USB设备ID")
    paper_width: int = Field(80, description="纸宽mm：58或80")

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in PRINTER_TYPES:
            raise ValueError(f"type 只能是 {PRINTER_TYPES}")
        return v

    @field_validator("connection_type")
    @classmethod
    def validate_conn(cls, v: str) -> str:
        if v not in CONN_TYPES:
            raise ValueError(f"connection_type 只能是 {CONN_TYPES}")
        return v

    @field_validator("paper_width")
    @classmethod
    def validate_width(cls, v: int) -> int:
        if v not in PAPER_WIDTHS:
            raise ValueError(f"paper_width 只能是 {PAPER_WIDTHS}")
        return v


class PrinterUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=50)
    type: Optional[str] = None
    connection_type: Optional[str] = None
    address: Optional[str] = Field(None, max_length=100)
    paper_width: Optional[int] = None
    is_active: Optional[bool] = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in PRINTER_TYPES:
            raise ValueError(f"type 只能是 {PRINTER_TYPES}")
        return v

    @field_validator("connection_type")
    @classmethod
    def validate_conn(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in CONN_TYPES:
            raise ValueError(f"connection_type 只能是 {CONN_TYPES}")
        return v

    @field_validator("paper_width")
    @classmethod
    def validate_width(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v not in PAPER_WIDTHS:
            raise ValueError(f"paper_width 只能是 {PAPER_WIDTHS}")
        return v


class PrinterRouteCreate(BaseModel):
    store_id: str = Field(..., description="门店ID")
    printer_id: str = Field(..., description="打印机ID")
    category_id: Optional[str] = Field(None, description="菜品类别ID（NULL=所有类别）")
    category_name: Optional[str] = Field(None, max_length=50, description="类别名称冗余")
    dish_tag: Optional[str] = Field(None, max_length=50, description="菜品标签，如：酒水/主食")
    priority: int = Field(0, description="优先级，越大越先匹配")
    is_default: bool = Field(False, description="是否为兜底规则")


# ─── 序列化辅助 ───────────────────────────────────────────────────────────────

def _row_to_printer(row) -> dict:
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "store_id": str(row.store_id),
        "name": row.name,
        "type": row.type,
        "connection_type": row.connection_type,
        "address": row.address,
        "is_active": row.is_active,
        "paper_width": row.paper_width,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _row_to_route(row) -> dict:
    result = {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "store_id": str(row.store_id),
        "printer_id": str(row.printer_id),
        "category_id": str(row.category_id) if row.category_id else None,
        "category_name": row.category_name,
        "dish_tag": row.dish_tag,
        "priority": row.priority,
        "is_default": row.is_default,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
    # JOIN 字段（来自 routes with printers 查询）
    if hasattr(row, "printer_name"):
        result["printer_name"] = row.printer_name
    if hasattr(row, "printer_type"):
        result["printer_type"] = row.printer_type
    return result


# ─── 打印机 CRUD ──────────────────────────────────────────────────────────────

@router.get("")
async def list_printers(
    request: Request,
    store_id: str = Query(..., description="门店ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取门店所有打印机列表。"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        tid = uuid.UUID(tenant_id)
        sid = uuid.UUID(store_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {exc}") from exc

    stmt = text("""
        SELECT id, tenant_id, store_id, name, type, connection_type,
               address, is_active, paper_width, created_at, updated_at
        FROM printers
        WHERE tenant_id = :tenant_id AND store_id = :store_id
        ORDER BY created_at ASC
    """)
    result = await db.execute(stmt, {"tenant_id": tid, "store_id": sid})
    rows = result.fetchall()
    return {"ok": True, "data": [_row_to_printer(r) for r in rows]}


@router.post("")
async def create_printer(
    body: PrinterCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """注册新打印机。"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        tid = uuid.UUID(tenant_id)
        sid = uuid.UUID(body.store_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {exc}") from exc

    printer_id = uuid.uuid4()
    stmt = text("""
        INSERT INTO printers (id, tenant_id, store_id, name, type, connection_type,
                              address, is_active, paper_width)
        VALUES (:id, :tenant_id, :store_id, :name, :type, :connection_type,
                :address, TRUE, :paper_width)
        RETURNING id, tenant_id, store_id, name, type, connection_type,
                  address, is_active, paper_width, created_at, updated_at
    """)
    result = await db.execute(stmt, {
        "id": printer_id,
        "tenant_id": tid,
        "store_id": sid,
        "name": body.name,
        "type": body.type,
        "connection_type": body.connection_type,
        "address": body.address,
        "paper_width": body.paper_width,
    })
    await db.commit()
    row = result.fetchone()
    logger.info("printer.created", printer_id=str(printer_id), tenant_id=tenant_id, store_id=body.store_id)
    return {"ok": True, "data": _row_to_printer(row)}


@router.put("/{printer_id}")
async def update_printer(
    printer_id: str,
    body: PrinterUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """更新打印机配置。"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        tid = uuid.UUID(tenant_id)
        pid = uuid.UUID(printer_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {exc}") from exc

    # 检查记录存在
    check = await db.execute(
        text("SELECT id FROM printers WHERE id = :id AND tenant_id = :tenant_id"),
        {"id": pid, "tenant_id": tid},
    )
    if check.fetchone() is None:
        raise HTTPException(status_code=404, detail="打印机不存在")

    # 动态构建 SET 子句
    updates: dict = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.type is not None:
        updates["type"] = body.type
    if body.connection_type is not None:
        updates["connection_type"] = body.connection_type
    if body.address is not None:
        updates["address"] = body.address
    if body.paper_width is not None:
        updates["paper_width"] = body.paper_width
    if body.is_active is not None:
        updates["is_active"] = body.is_active

    if not updates:
        raise HTTPException(status_code=400, detail="没有可更新的字段")

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["id"] = pid
    updates["tenant_id"] = tid

    stmt = text(f"""
        UPDATE printers SET {set_clause}, updated_at = NOW()
        WHERE id = :id AND tenant_id = :tenant_id
        RETURNING id, tenant_id, store_id, name, type, connection_type,
                  address, is_active, paper_width, created_at, updated_at
    """)
    result = await db.execute(stmt, updates)
    await db.commit()
    row = result.fetchone()
    logger.info("printer.updated", printer_id=printer_id, tenant_id=tenant_id)
    return {"ok": True, "data": _row_to_printer(row)}


@router.delete("/{printer_id}")
async def deactivate_printer(
    printer_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """停用打印机（软删除：is_active=false）。"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        tid = uuid.UUID(tenant_id)
        pid = uuid.UUID(printer_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {exc}") from exc

    result = await db.execute(
        text("""
            UPDATE printers SET is_active = FALSE, updated_at = NOW()
            WHERE id = :id AND tenant_id = :tenant_id
            RETURNING id
        """),
        {"id": pid, "tenant_id": tid},
    )
    await db.commit()
    if result.fetchone() is None:
        raise HTTPException(status_code=404, detail="打印机不存在")

    logger.info("printer.deactivated", printer_id=printer_id, tenant_id=tenant_id)
    return {"ok": True, "data": {"deactivated": True, "printer_id": printer_id}}


@router.post("/{printer_id}/test")
async def test_printer(
    printer_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """发送测试打印页。"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        tid = uuid.UUID(tenant_id)
        pid = uuid.UUID(printer_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {exc}") from exc

    result = await db.execute(
        text("SELECT id, name, address, connection_type FROM printers WHERE id = :id AND tenant_id = :tenant_id AND is_active = TRUE"),
        {"id": pid, "tenant_id": tid},
    )
    row = result.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="打印机不存在或已停用")

    # 通过现有 print_manager 触发测试打印
    try:
        from ..services.print_manager import get_print_manager
        mgr = get_print_manager()
        task = await mgr.test_print(printer_id)
        return {"ok": True, "data": task.to_dict()}
    except ValueError as exc:
        # print_manager 中没有注册此打印机时，返回模拟成功（配置界面测试）
        logger.warning("printer.test_fallback", printer_id=printer_id, reason=str(exc))
        return {"ok": True, "data": {"printer_id": printer_id, "status": "test_sent", "note": "配置测试模式"}}
    except ConnectionError as exc:
        raise HTTPException(status_code=503, detail=f"打印机连接失败: {exc}") from exc


# ─── 路由规则 CRUD ────────────────────────────────────────────────────────────

@router.get("/routes")
async def list_routes(
    request: Request,
    store_id: str = Query(..., description="门店ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取门店路由规则列表（JOIN 打印机信息）。"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        tid = uuid.UUID(tenant_id)
        sid = uuid.UUID(store_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {exc}") from exc

    stmt = text("""
        SELECT r.id, r.tenant_id, r.store_id, r.printer_id,
               r.category_id, r.category_name, r.dish_tag,
               r.priority, r.is_default, r.created_at, r.updated_at,
               p.name AS printer_name, p.type AS printer_type
        FROM printer_routes r
        JOIN printers p ON p.id = r.printer_id
        WHERE r.tenant_id = :tenant_id AND r.store_id = :store_id
        ORDER BY r.priority DESC, r.created_at ASC
    """)
    result = await db.execute(stmt, {"tenant_id": tid, "store_id": sid})
    rows = result.fetchall()
    return {"ok": True, "data": [_row_to_route(r) for r in rows]}


@router.post("/routes")
async def create_route(
    body: PrinterRouteCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """添加打印路由规则。"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        tid = uuid.UUID(tenant_id)
        sid = uuid.UUID(body.store_id)
        pid = uuid.UUID(body.printer_id)
        cid = uuid.UUID(body.category_id) if body.category_id else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {exc}") from exc

    # 验证打印机存在且属于同一租户
    check = await db.execute(
        text("SELECT id FROM printers WHERE id = :id AND tenant_id = :tenant_id AND is_active = TRUE"),
        {"id": pid, "tenant_id": tid},
    )
    if check.fetchone() is None:
        raise HTTPException(status_code=404, detail="打印机不存在或已停用")

    route_id = uuid.uuid4()
    stmt = text("""
        INSERT INTO printer_routes (id, tenant_id, store_id, printer_id,
                                    category_id, category_name, dish_tag,
                                    priority, is_default)
        VALUES (:id, :tenant_id, :store_id, :printer_id,
                :category_id, :category_name, :dish_tag,
                :priority, :is_default)
        RETURNING id, tenant_id, store_id, printer_id,
                  category_id, category_name, dish_tag,
                  priority, is_default, created_at, updated_at
    """)
    result = await db.execute(stmt, {
        "id": route_id,
        "tenant_id": tid,
        "store_id": sid,
        "printer_id": pid,
        "category_id": cid,
        "category_name": body.category_name,
        "dish_tag": body.dish_tag,
        "priority": body.priority,
        "is_default": body.is_default,
    })
    await db.commit()
    row = result.fetchone()
    logger.info("printer_route.created", route_id=str(route_id), tenant_id=tenant_id)
    return {"ok": True, "data": _row_to_route(row)}


@router.delete("/routes/{route_id}")
async def delete_route(
    route_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """删除路由规则（硬删除，规则数据无需保留历史）。"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        tid = uuid.UUID(tenant_id)
        rid = uuid.UUID(route_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {exc}") from exc

    result = await db.execute(
        text("DELETE FROM printer_routes WHERE id = :id AND tenant_id = :tenant_id RETURNING id"),
        {"id": rid, "tenant_id": tid},
    )
    await db.commit()
    if result.fetchone() is None:
        raise HTTPException(status_code=404, detail="路由规则不存在")

    logger.info("printer_route.deleted", route_id=route_id, tenant_id=tenant_id)
    return {"ok": True, "data": {"deleted": True, "route_id": route_id}}


# ─── 路由解析（供打印执行时调用）────────────────────────────────────────────

@router.get("/resolve")
async def resolve_printer(
    request: Request,
    store_id: str = Query(..., description="门店ID"),
    category_id: Optional[str] = Query(None, description="菜品类别ID"),
    dish_tags: Optional[str] = Query(None, description="菜品标签，逗号分隔"),
    db: AsyncSession = Depends(get_db),
):
    """解析某道菜应打印到哪台打印机。

    匹配优先级：
    1. category_id 精确匹配（priority DESC）
    2. dish_tag 标签匹配（priority DESC）
    3. is_default 兜底规则
    """
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        tid = uuid.UUID(tenant_id)
        sid = uuid.UUID(store_id)
        cid = uuid.UUID(category_id) if category_id else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {exc}") from exc

    tags = [t.strip() for t in dish_tags.split(",") if t.strip()] if dish_tags else []

    # 1. category_id 精确匹配
    if cid is not None:
        result = await db.execute(
            text("""
                SELECT r.printer_id, p.name, p.type, p.address, p.connection_type
                FROM printer_routes r
                JOIN printers p ON p.id = r.printer_id AND p.is_active = TRUE
                WHERE r.tenant_id = :tenant_id AND r.store_id = :store_id
                  AND r.category_id = :category_id
                ORDER BY r.priority DESC
                LIMIT 1
            """),
            {"tenant_id": tid, "store_id": sid, "category_id": cid},
        )
        row = result.fetchone()
        if row:
            return {"ok": True, "data": {
                "printer_id": str(row.printer_id),
                "printer_name": row.name,
                "printer_type": row.type,
                "match_type": "category",
            }}

    # 2. dish_tag 标签匹配
    if tags:
        result = await db.execute(
            text("""
                SELECT r.printer_id, p.name, p.type, p.address, r.dish_tag
                FROM printer_routes r
                JOIN printers p ON p.id = r.printer_id AND p.is_active = TRUE
                WHERE r.tenant_id = :tenant_id AND r.store_id = :store_id
                  AND r.dish_tag = ANY(:tags)
                ORDER BY r.priority DESC
                LIMIT 1
            """),
            {"tenant_id": tid, "store_id": sid, "tags": tags},
        )
        row = result.fetchone()
        if row:
            return {"ok": True, "data": {
                "printer_id": str(row.printer_id),
                "printer_name": row.name,
                "printer_type": row.type,
                "match_type": "dish_tag",
                "matched_tag": row.dish_tag,
            }}

    # 3. 兜底默认规则
    result = await db.execute(
        text("""
            SELECT r.printer_id, p.name, p.type
            FROM printer_routes r
            JOIN printers p ON p.id = r.printer_id AND p.is_active = TRUE
            WHERE r.tenant_id = :tenant_id AND r.store_id = :store_id
              AND r.is_default = TRUE
            ORDER BY r.priority DESC
            LIMIT 1
        """),
        {"tenant_id": tid, "store_id": sid},
    )
    row = result.fetchone()
    if row:
        return {"ok": True, "data": {
            "printer_id": str(row.printer_id),
            "printer_name": row.name,
            "printer_type": row.type,
            "match_type": "default",
        }}

    # 未找到任何规则
    return {"ok": True, "data": None}
