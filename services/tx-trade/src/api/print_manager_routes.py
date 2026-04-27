"""打印管理可视化中心 API — 打印任务队列 + 配置导入导出

路由前缀: /api/v1/print

模块4.2 打印管理可视化中心：
  GET  /api/v1/print/tasks               — 打印任务队列（分页，status: pending/done/failed）
  POST /api/v1/print/tasks/{id}/retry    — 失败任务重打
  DELETE /api/v1/print/tasks/{id}        — 取消待打任务
  POST /api/v1/print/test-page           — 打印测试页
  GET  /api/v1/print/config/export/{store_id} — 导出打印机配置（JSON）
  POST /api/v1/print/config/import       — 导入打印机配置（新门店克隆）
"""

import uuid
from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/print", tags=["print-manager"])
logger = structlog.get_logger()


# ─── 工具函数 ─────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS 上下文变量。"""
    await db.execute(text(f"SET LOCAL app.tenant_id = '{tenant_id}'"))


# ─── Pydantic 模型 ────────────────────────────────────────────────────────────

TASK_STATUSES = ("pending", "printing", "done", "failed")


class TestPageRequest(BaseModel):
    printer_id: str = Field(..., description="打印机ID")
    store_id: str = Field(..., description="门店ID")


class ConfigImportRequest(BaseModel):
    store_id: str = Field(..., description="目标门店ID（新门店克隆）")
    config: dict = Field(..., description="从 export 接口获取的配置JSON")
    overwrite: bool = Field(False, description="是否覆盖同名打印机（默认跳过重复）")


# ─── 序列化辅助 ───────────────────────────────────────────────────────────────


def _row_to_task(row) -> dict:
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "printer_id": str(row.printer_id),
        "printer_name": getattr(row, "printer_name", None),
        "content_preview": (row.content or "")[:80],
        "status": row.status,
        "retry_count": row.retry_count,
        "error_message": getattr(row, "error_message", None),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


# ─── 打印任务队列 ────────────────────────────────────────────────────────────


@router.get("/tasks")
async def list_print_tasks(
    request: Request,
    store_id: str = Query(..., description="门店ID"),
    status: Optional[str] = Query(None, description="任务状态过滤：pending/printing/done/failed"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取打印任务队列（分页，支持状态过滤）。"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        tid = uuid.UUID(tenant_id)
        sid = uuid.UUID(store_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {exc}") from exc

    if status and status not in TASK_STATUSES:
        raise HTTPException(status_code=400, detail=f"status 只能是 {TASK_STATUSES}")

    # 构建过滤条件
    where_clause = "WHERE pt.tenant_id = :tenant_id AND p.store_id = :store_id"
    params: dict = {"tenant_id": tid, "store_id": sid}

    if status:
        where_clause += " AND pt.status = :status"
        params["status"] = status

    count_stmt = text(f"""
        SELECT COUNT(*) FROM print_tasks pt
        JOIN printers p ON p.id = pt.printer_id
        {where_clause}
    """)
    count_result = await db.execute(count_stmt, params)
    total = count_result.scalar() or 0

    offset = (page - 1) * size
    params["limit"] = size
    params["offset"] = offset

    stmt = text(f"""
        SELECT pt.id, pt.tenant_id, pt.printer_id, pt.content, pt.status,
               pt.retry_count, pt.error_message, pt.created_at, pt.updated_at,
               p.name AS printer_name
        FROM print_tasks pt
        JOIN printers p ON p.id = pt.printer_id
        {where_clause}
        ORDER BY pt.created_at DESC
        LIMIT :limit OFFSET :offset
    """)
    result = await db.execute(stmt, params)
    rows = result.fetchall()

    return {
        "ok": True,
        "data": {
            "items": [_row_to_task(r) for r in rows],
            "total": total,
            "page": page,
            "size": size,
        },
    }


@router.post("/tasks/{task_id}/retry")
async def retry_print_task(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """重新打印失败任务（将 failed 状态重置为 pending）。"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        tid = uuid.UUID(tenant_id)
        task_uuid = uuid.UUID(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {exc}") from exc

    # 只允许重试 failed 状态的任务
    check = await db.execute(
        text("SELECT id, status FROM print_tasks WHERE id = :id AND tenant_id = :tenant_id"),
        {"id": task_uuid, "tenant_id": tid},
    )
    row = check.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="打印任务不存在")
    if row.status != "failed":
        raise HTTPException(
            status_code=422,
            detail=f"只能重试 failed 状态的任务，当前状态：{row.status}",
        )

    result = await db.execute(
        text("""
            UPDATE print_tasks
            SET status = 'pending', retry_count = retry_count + 1,
                error_message = NULL, updated_at = NOW()
            WHERE id = :id AND tenant_id = :tenant_id
            RETURNING id, tenant_id, printer_id, content, status,
                      retry_count, error_message, created_at, updated_at
        """),
        {"id": task_uuid, "tenant_id": tid},
    )
    await db.commit()
    row = result.fetchone()

    logger.info("print_task.retried", task_id=task_id, tenant_id=tenant_id)
    return {"ok": True, "data": _row_to_task(row)}


@router.delete("/tasks/{task_id}")
async def cancel_print_task(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """取消待打任务（只能取消 pending 状态的任务）。"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        tid = uuid.UUID(tenant_id)
        task_uuid = uuid.UUID(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {exc}") from exc

    check = await db.execute(
        text("SELECT id, status FROM print_tasks WHERE id = :id AND tenant_id = :tenant_id"),
        {"id": task_uuid, "tenant_id": tid},
    )
    row = check.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="打印任务不存在")
    if row.status not in ("pending",):
        raise HTTPException(
            status_code=422,
            detail=f"只能取消 pending 状态的任务，当前状态：{row.status}",
        )

    await db.execute(
        text("DELETE FROM print_tasks WHERE id = :id AND tenant_id = :tenant_id"),
        {"id": task_uuid, "tenant_id": tid},
    )
    await db.commit()

    logger.info("print_task.cancelled", task_id=task_id, tenant_id=tenant_id)
    return {"ok": True, "data": {"cancelled": True, "task_id": task_id}}


@router.post("/test-page")
async def send_test_page(
    body: TestPageRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """打印测试页（向指定打印机发送测试内容）。"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        tid = uuid.UUID(tenant_id)
        pid = uuid.UUID(body.printer_id)
        sid = uuid.UUID(body.store_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {exc}") from exc

    # 验证打印机存在
    printer_row = await db.execute(
        text("SELECT id, name, address, is_active FROM printers WHERE id = :id AND tenant_id = :tenant_id"),
        {"id": pid, "tenant_id": tid},
    )
    printer = printer_row.fetchone()
    if printer is None:
        raise HTTPException(status_code=404, detail="打印机不存在")
    if not printer.is_active:
        raise HTTPException(status_code=422, detail="打印机已停用，无法发送测试页")

    test_content = (
        f"======== 打印测试 ========\n"
        f"打印机: {printer.name}\n"
        f"地址: {printer.address or 'N/A'}\n"
        f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"租户: {tenant_id[:8]}...\n"
        f"==========================\n"
        f"测试打印成功！"
    )

    # 写入任务队列
    task_id = uuid.uuid4()
    result = await db.execute(
        text("""
            INSERT INTO print_tasks (id, tenant_id, printer_id, content, status, retry_count)
            VALUES (:id, :tenant_id, :printer_id, :content, 'pending', 0)
            RETURNING id, tenant_id, printer_id, content, status,
                      retry_count, error_message, created_at, updated_at
        """),
        {
            "id": task_id,
            "tenant_id": tid,
            "printer_id": pid,
            "content": test_content,
        },
    )
    await db.commit()
    row = result.fetchone()

    # 尝试通过 print_manager 实际触发打印（可选，失败不影响任务记录）
    try:
        from ..services.print_manager import get_print_manager

        mgr = get_print_manager()
        await mgr.test_print(body.printer_id)
    except (ValueError, AttributeError, ImportError):
        pass  # print_manager 不可用时静默降级，任务已记录
    except ConnectionError as exc:
        logger.warning("test_page.connection_failed", printer_id=body.printer_id, error=str(exc))

    logger.info("print_task.test_page_created", task_id=str(task_id), printer_id=body.printer_id)
    return {"ok": True, "data": _row_to_task(row)}


# ─── 配置导入导出 ─────────────────────────────────────────────────────────────


@router.get("/config/export/{store_id}")
async def export_printer_config(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """导出门店打印机配置（JSON），用于新门店克隆。"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        tid = uuid.UUID(tenant_id)
        sid = uuid.UUID(store_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {exc}") from exc

    # 查询打印机
    printers_result = await db.execute(
        text("""
            SELECT id, name, type, connection_type, address, is_active, paper_width
            FROM printers
            WHERE tenant_id = :tenant_id AND store_id = :store_id
            ORDER BY created_at ASC
        """),
        {"tenant_id": tid, "store_id": sid},
    )
    printers = printers_result.fetchall()

    # 查询路由规则
    routes_result = await db.execute(
        text("""
            SELECT r.printer_id, r.category_id, r.category_name,
                   r.dish_tag, r.priority, r.is_default
            FROM printer_routes r
            WHERE r.tenant_id = :tenant_id AND r.store_id = :store_id
            ORDER BY r.priority DESC
        """),
        {"tenant_id": tid, "store_id": sid},
    )
    routes = routes_result.fetchall()

    # 构建打印机ID映射（用名称作为克隆时的匹配键）
    printers_export = []
    printer_id_map = {}
    for p in printers:
        entry = {
            "name": p.name,
            "type": p.type,
            "connection_type": p.connection_type,
            "address": p.address,
            "is_active": p.is_active,
            "paper_width": p.paper_width,
        }
        printers_export.append(entry)
        printer_id_map[str(p.id)] = p.name

    # 路由规则（用打印机名称代替ID，方便跨门店迁移）
    routes_export = []
    for r in routes:
        routes_export.append(
            {
                "printer_name": printer_id_map.get(str(r.printer_id), str(r.printer_id)),
                "category_id": str(r.category_id) if r.category_id else None,
                "category_name": r.category_name,
                "dish_tag": r.dish_tag,
                "priority": r.priority,
                "is_default": r.is_default,
            }
        )

    config_payload = {
        "version": "1.0",
        "exported_at": datetime.now().isoformat(),
        "source_store_id": store_id,
        "printers": printers_export,
        "routes": routes_export,
    }

    logger.info("printer_config.exported", store_id=store_id, tenant_id=tenant_id, printer_count=len(printers_export))
    return {
        "ok": True,
        "data": config_payload,
    }


@router.post("/config/import")
async def import_printer_config(
    body: ConfigImportRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """导入打印机配置（新门店克隆）。

    将 export 接口返回的配置导入到目标门店。
    overwrite=False（默认）跳过同名打印机。
    overwrite=True 覆盖同名打印机配置。
    """
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        tid = uuid.UUID(tenant_id)
        sid = uuid.UUID(body.store_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {exc}") from exc

    config = body.config
    printers_data = config.get("printers", [])
    routes_data = config.get("routes", [])

    if not isinstance(printers_data, list):
        raise HTTPException(status_code=422, detail="config.printers 必须是列表")

    # 查询目标门店已有打印机（按名称索引）
    existing_result = await db.execute(
        text("SELECT id, name FROM printers WHERE tenant_id = :tenant_id AND store_id = :store_id"),
        {"tenant_id": tid, "store_id": sid},
    )
    existing_printers = {row.name: str(row.id) for row in existing_result.fetchall()}

    created_count = 0
    skipped_count = 0
    updated_count = 0
    name_to_new_id: dict[str, str] = {}

    for p in printers_data:
        name = p.get("name", "")
        if not name:
            continue

        if name in existing_printers:
            name_to_new_id[name] = existing_printers[name]
            if body.overwrite:
                # 覆盖：更新现有打印机配置
                await db.execute(
                    text("""
                        UPDATE printers
                        SET type = :type, connection_type = :connection_type,
                            address = :address, paper_width = :paper_width,
                            updated_at = NOW()
                        WHERE name = :name AND tenant_id = :tenant_id AND store_id = :store_id
                    """),
                    {
                        "name": name,
                        "type": p.get("type", "receipt"),
                        "connection_type": p.get("connection_type", "network"),
                        "address": p.get("address"),
                        "paper_width": p.get("paper_width", 80),
                        "tenant_id": tid,
                        "store_id": sid,
                    },
                )
                updated_count += 1
            else:
                skipped_count += 1
            continue

        # 新建打印机
        new_pid = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO printers (id, tenant_id, store_id, name, type,
                                      connection_type, address, is_active, paper_width)
                VALUES (:id, :tenant_id, :store_id, :name, :type,
                        :connection_type, :address, :is_active, :paper_width)
            """),
            {
                "id": new_pid,
                "tenant_id": tid,
                "store_id": sid,
                "name": name,
                "type": p.get("type", "receipt"),
                "connection_type": p.get("connection_type", "network"),
                "address": p.get("address"),
                "is_active": p.get("is_active", True),
                "paper_width": p.get("paper_width", 80),
            },
        )
        name_to_new_id[name] = str(new_pid)
        created_count += 1

    # 导入路由规则（仅在新建了打印机的情况下）
    routes_created = 0
    for r in routes_data:
        printer_name = r.get("printer_name", "")
        new_pid_str = name_to_new_id.get(printer_name)
        if not new_pid_str:
            continue

        try:
            new_pid = uuid.UUID(new_pid_str)
        except ValueError:
            continue

        route_id = uuid.uuid4()
        try:
            cat_id = uuid.UUID(r["category_id"]) if r.get("category_id") else None
        except ValueError:
            cat_id = None

        try:
            await db.execute(
                text("""
                    INSERT INTO printer_routes (id, tenant_id, store_id, printer_id,
                                                category_id, category_name, dish_tag,
                                                priority, is_default)
                    VALUES (:id, :tenant_id, :store_id, :printer_id,
                            :category_id, :category_name, :dish_tag,
                            :priority, :is_default)
                """),
                {
                    "id": route_id,
                    "tenant_id": tid,
                    "store_id": sid,
                    "printer_id": new_pid,
                    "category_id": cat_id,
                    "category_name": r.get("category_name"),
                    "dish_tag": r.get("dish_tag"),
                    "priority": r.get("priority", 0),
                    "is_default": r.get("is_default", False),
                },
            )
            routes_created += 1
        except Exception as exc:  # noqa: BLE001 — 路由写入失败不阻断整体导入
            logger.warning("config_import.route_failed", error=str(exc))

    await db.commit()

    logger.info(
        "printer_config.imported",
        store_id=body.store_id,
        tenant_id=tenant_id,
        created=created_count,
        updated=updated_count,
        skipped=skipped_count,
        routes=routes_created,
    )
    return {
        "ok": True,
        "data": {
            "store_id": body.store_id,
            "printers_created": created_count,
            "printers_updated": updated_count,
            "printers_skipped": skipped_count,
            "routes_created": routes_created,
        },
    }
