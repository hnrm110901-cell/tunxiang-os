"""KDS 出餐调度 API — 分单/队列/操作/超时预警

所有接口需要 X-Tenant-ID header。

Sprint C3 扩展（Tier1）：
  - GET /api/v1/kds/orders/delta       — 增量订单同步（cursor + limit）
  - POST /api/v1/kds/device/heartbeat  — 设备心跳 + edge_device_registry upsert
  两接口要求 RBAC require_role（A4 基建）。
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..security.rbac import UserContext, require_role
from ..services.cooking_scheduler import calculate_cooking_order, get_dept_load
from ..services.cooking_timeout import check_timeouts, get_timeout_config
from ..services.device_registry_service import (
    ALLOWED_DEVICE_KINDS,
    DeviceRegistryService,
    HealthStatus,
)
from ..services.kds_actions import (
    batch_scan_complete,
    check_rush_overdue,
    confirm_rush,
    finish_cooking,
    get_task_timeline,
    report_shortage,
    request_remake,
    request_rush,
    scan_complete_dish,
    start_cooking,
)
from ..services.kds_delta_service import KDSDeltaService
from ..services.kds_dispatch import (
    dispatch_order_to_kds,
    get_dept_queue,
    get_kds_tasks_by_dept,
    get_store_kds_overview,
    resolve_dept_for_dish,
)

router = APIRouter(prefix="/api/v1/kds", tags=["kds"])


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


# ─── 请求模型 ───


class DispatchItem(BaseModel):
    dish_id: str
    item_name: str
    quantity: int = 1
    order_item_id: Optional[str] = None
    notes: Optional[str] = None


class DispatchReq(BaseModel):
    items: list[DispatchItem]
    table_number: Optional[str] = None
    order_no: Optional[str] = None


class RushReq(BaseModel):
    dish_id: str


class RemakeReq(BaseModel):
    reason: str


class ShortageReq(BaseModel):
    ingredient_id: str


class RushConfirmReq(BaseModel):
    promised_minutes: int  # 承诺在多少分钟内完成（厨师设定）


class ScanCompleteReq(BaseModel):
    barcode: str


class BatchScanReq(BaseModel):
    barcodes: list[str]


# ─── 分单与队列 ───


@router.post("/dispatch/{order_id}")
async def api_dispatch_order(
    order_id: str,
    body: DispatchReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """分单 — 将订单菜品自动分配到对应档口

    自动完成菜品->出品部门映射，无需前端传 kitchen_station。
    分单后自动：
    1. 回写 OrderItem.kds_station
    2. 为每个档口生成厨打单并发送到打印机
    """
    tenant_id = _get_tenant_id(request)
    items = [item.model_dump() for item in body.items]
    result = await dispatch_order_to_kds(
        order_id,
        items,
        tenant_id,
        db,
        table_number=body.table_number or "",
        order_no=body.order_no or "",
    )

    # 智能排序
    sorted_tasks = await calculate_cooking_order(result["dept_tasks"], db)

    return {"ok": True, "data": {"dept_tasks": sorted_tasks}}


@router.get("/tasks")
async def api_kds_tasks(
    request: Request,
    dept_id: str = Query(description="档口ID — KDS设备按档口拉取待出品任务"),
    status: Optional[str] = Query(
        default=None,
        description="任务状态过滤：pending/cooking/done/cancelled（不传=pending+cooking）",
    ),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """KDS任务查询 — 按档口ID查询待出品任务列表（KDS屏轮询接口）。

    KDS平板定时调用此接口获取本档口的待出品任务。
    返回 pending+cooking 状态的任务，按优先级+创建时间排序。

    示例：GET /api/v1/kds/tasks?dept_id=xxx&status=pending
    """
    tenant_id = _get_tenant_id(request)
    try:
        tasks, total = await get_kds_tasks_by_dept(
            dept_id=dept_id,
            tenant_id=tenant_id,
            db=db,
            status=status,
            page=page,
            size=size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "data": {"items": tasks, "total": total, "page": page, "size": size}}


@router.get("/queue/{dept_id}")
async def api_dept_queue(
    dept_id: str,
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """档口队列 — 获取某档口当前待出品任务（兼容接口）

    新接口请使用 GET /api/v1/kds/tasks?dept_id=xxx。
    本接口保留兼容旧版 KDS 客户端。
    """
    tenant_id = _get_tenant_id(request)
    queue = await get_dept_queue(dept_id, store_id, tenant_id, db)
    return {"ok": True, "data": {"items": queue, "total": len(queue)}}


@router.get("/overview/{store_id}")
async def api_store_overview(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """全店概览 — 所有档口的实时负载"""
    tenant_id = _get_tenant_id(request)
    overview = await get_store_kds_overview(store_id, tenant_id, db)
    return {"ok": True, "data": {"depts": overview, "total": len(overview)}}


@router.get("/load/{dept_id}")
async def api_dept_load(
    dept_id: str,
    db: AsyncSession = Depends(get_db),
):
    """档口负载 — pending/in_progress/avg_wait"""
    load = await get_dept_load(dept_id, db)
    return {"ok": True, "data": load}


@router.get("/resolve-dept/{dish_id}")
async def api_resolve_dept(
    dish_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """查询菜品对应的出品档口（供加菜场景使用）"""
    tenant_id = _get_tenant_id(request)
    dept = await resolve_dept_for_dish(dish_id, tenant_id, db)
    if not dept:
        return {"ok": True, "data": None, "message": "该菜品未配置出品档口映射"}
    return {"ok": True, "data": dept}


# ─── KDS 操作 ───


@router.post("/task/{task_id}/start")
async def api_start_cooking(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """开始制作"""
    operator_id = request.headers.get("X-Operator-ID", "unknown")
    result = await start_cooking(task_id, operator_id, db)
    return result


@router.post("/task/{task_id}/finish")
async def api_finish_cooking(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """完成出品"""
    operator_id = request.headers.get("X-Operator-ID", "unknown")
    result = await finish_cooking(task_id, operator_id, db)
    return result


@router.post("/task/{task_id}/rush")
async def api_rush(
    task_id: str,
    body: RushReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """催菜 — 自动推送催单到 KDS + 发送催菜厨打单到档口打印机"""
    tenant_id = _get_tenant_id(request)
    result = await request_rush(task_id, body.dish_id, db, tenant_id=tenant_id)
    return result


@router.post("/task/{task_id}/remake")
async def api_remake(
    task_id: str,
    body: RemakeReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """重做 — 自动推送重做通知到 KDS + 发送重做厨打单到档口打印机"""
    tenant_id = _get_tenant_id(request)
    result = await request_remake(task_id, body.reason, db, tenant_id=tenant_id)
    return result


@router.post("/task/{task_id}/shortage")
async def api_shortage(
    task_id: str,
    body: ShortageReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """缺料上报"""
    result = await report_shortage(task_id, body.ingredient_id, db)
    return result


@router.get("/task/{task_id}/timeline")
async def api_task_timeline(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """任务时间线"""
    result = await get_task_timeline(task_id, db)
    return result


@router.post("/task/{task_id}/rush/confirm")
async def api_rush_confirm(
    task_id: str,
    body: RushConfirmReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """厨师确认催菜 + 设置承诺完成时间

    厨师在 KDS 屏幕上确认催单并承诺分钟数后调用。
    承诺时间将推送到 web-crew（服务员端），让服务员可以告知顾客。
    """
    tenant_id = _get_tenant_id(request)
    operator_id = request.headers.get("X-Operator-ID", "unknown")
    result = await confirm_rush(
        task_id,
        body.promised_minutes,
        operator_id,
        db,
        tenant_id=tenant_id,
    )
    return result


@router.get("/task/{task_id}/rush/status")
async def api_rush_status(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """查询催菜SLA状态

    返回当前任务的催菜次数、承诺时间及是否已超时。
    """
    import uuid as _uuid

    from sqlalchemy import and_, select

    from ..models.kds_task import KDSTask

    tenant_id = _get_tenant_id(request)

    try:
        tid = _uuid.UUID(tenant_id)
        task_uuid = _uuid.UUID(task_id)
    except ValueError:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="无效的 task_id 或 tenant_id")

    from datetime import datetime, timezone

    stmt = select(KDSTask).where(
        and_(
            KDSTask.id == task_uuid,
            KDSTask.tenant_id == tid,
            KDSTask.is_deleted == False,  # noqa: E712
        )
    )
    db_task = (await db.execute(stmt)).scalar_one_or_none()
    if db_task is None:
        return {"ok": False, "error": f"任务 {task_id} 不存在"}

    now = datetime.now(timezone.utc)
    promised_at = db_task.promised_at
    is_overdue = promised_at is not None and db_task.status not in ("done", "cancelled") and promised_at < now

    return {
        "ok": True,
        "data": {
            "task_id": task_id,
            "status": db_task.status,
            "rush_count": db_task.rush_count,
            "last_rush_at": db_task.last_rush_at.isoformat() if db_task.last_rush_at else None,
            "promised_at": promised_at.isoformat() if promised_at else None,
            "is_overdue": is_overdue,
            "overdue_sec": int((now - promised_at).total_seconds()) if is_overdue else 0,
        },
    }


@router.post("/rush/overdue-check")
async def api_rush_overdue_check(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """催菜SLA超时批量检查（供定时任务调用）

    扫描所有承诺时间已到期但任务未完成的记录，触发升级告警推送。
    建议每分钟调用一次。
    """
    tenant_id = _get_tenant_id(request)
    result = await check_rush_overdue(tenant_id, db)
    return result


# ─── 扫码划菜 ───


@router.post("/scan-complete")
async def api_scan_complete(
    body: ScanCompleteReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """单个扫码划菜 — 扫描条码确认菜品出品完成

    扫码后自动：
    1. 更新 order_item 的扫码状态
    2. 关联 KDS Task 标记为 done
    3. 记录划菜日志（含出品耗时）
    4. 检查订单是否全部完成
    """
    tenant_id = _get_tenant_id(request)
    scanned_by = request.headers.get("X-Operator-ID", "unknown")
    result = await scan_complete_dish(
        barcode=body.barcode,
        scanned_by=scanned_by,
        db=db,
        tenant_id=tenant_id,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "扫码失败"))
    return result


@router.post("/batch-scan")
async def api_batch_scan(
    body: BatchScanReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """批量扫码划菜 — 一次确认多个菜品出品完成

    适用场景：同桌多道菜同时出品，一次性扫描所有条码。
    单次最多50个条码。
    """
    tenant_id = _get_tenant_id(request)
    scanned_by = request.headers.get("X-Operator-ID", "unknown")
    result = await batch_scan_complete(
        barcodes=body.barcodes,
        scanned_by=scanned_by,
        db=db,
        tenant_id=tenant_id,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "批量扫码失败"))
    return result


# ─── 超时预警 ───


@router.get("/timeouts/{store_id}")
async def api_check_timeouts(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """超时检查 — 自动推送 warning/critical 到 KDS + 管理员手机"""
    tenant_id = _get_tenant_id(request)
    items = await check_timeouts(store_id, tenant_id, db)
    return {
        "ok": True,
        "data": {
            "items": items,
            "total": len(items),
            "critical": len([i for i in items if i["status"] == "critical"]),
            "warning": len([i for i in items if i["status"] == "warning"]),
        },
    }


@router.get("/timeouts/{store_id}/config")
async def api_timeout_config(
    store_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取超时配置"""
    config = await get_timeout_config(store_id, db)
    return {"ok": True, "data": config}


# ─── Sprint C3: KDS delta + device heartbeat ─────────────────────────────────


class DeviceHeartbeatReq(BaseModel):
    """KDS / POS / 其他终端心跳请求体。

    device_kind 枚举：pos / kds / crew_phone / tv_menu / reception / mac_mini
    （与 v271 edge_device_registry CHECK 约束一致）
    """

    device_id: str = Field(..., min_length=1, max_length=64)
    device_kind: str = Field(..., min_length=1, max_length=16)
    store_id: str = Field(..., min_length=1)
    device_label: Optional[str] = Field(None, max_length=64)
    os_version: Optional[str] = Field(None, max_length=32)
    app_version: Optional[str] = Field(None, max_length=32)
    buffer_backlog: int = Field(0, ge=0)
    health_status: str = Field(HealthStatus.HEALTHY.value, max_length=16)


@router.get("/orders/delta")
async def api_kds_orders_delta(
    request: Request,
    store_id: str = Query(..., description="门店 UUID"),
    cursor: Optional[str] = Query(None, description="ISO8601 起点，首次不传"),
    device_id: Optional[str] = Query(None, description="设备 ID（审计用）"),
    device_kind: Optional[str] = Query(
        None,
        description="终端类型；kds=剔除客户手机号/金额等敏感字段",
    ),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(require_role("cashier", "kds", "store_manager", "admin")),
):
    """Sprint C3 — KDS 订单增量同步。

    返回 cursor 之后 status ∈ (pending/confirmed/preparing/ready) 的订单，
    按 updated_at 升序。response:
        {
          "ok": true,
          "data": {
            "orders": [...],
            "next_cursor": "2026-04-24T18:00:12Z",
            "server_time": "2026-04-24T18:00:20Z",
            "poll_interval_ms": 5000
          }
        }
    """
    # 三方租户一致性校验（与 A3 offline_sync 一致模式）
    tenant_id = request.headers.get("X-Tenant-ID") or getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    if user.tenant_id and user.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="USER_TENANT_MISMATCH")

    if device_kind is not None and device_kind not in ALLOWED_DEVICE_KINDS:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_DEVICE_KIND",
                "message": f"device_kind must be one of {sorted(ALLOWED_DEVICE_KINDS)}",
            },
        )

    svc = KDSDeltaService(db=db, tenant_id=tenant_id)
    try:
        result = await svc.get_orders_delta(
            store_id=store_id,
            cursor=cursor,
            device_kind=device_kind,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError:
        # 交由全局 exception handler 记录；给客户端统一 500 结构
        raise HTTPException(status_code=500, detail="DB_ERROR")

    # datetime → ISO8601 字符串，便于前端直接赋给下一轮 cursor
    def _iso(dt: Optional[datetime]) -> Optional[str]:
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    # 将 orders 里 updated_at 字段也序列化（前端兼容）
    serialized_orders = []
    for o in result["orders"]:
        copy = dict(o)
        if isinstance(copy.get("updated_at"), datetime):
            copy["updated_at"] = _iso(copy["updated_at"])
        serialized_orders.append(copy)

    return {
        "ok": True,
        "data": {
            "orders": serialized_orders,
            "next_cursor": _iso(result["next_cursor"]),
            "server_time": _iso(result["server_time"]),
            # 建议 KDS 轮询 5s；断网恢复可临时缩短
            "poll_interval_ms": 5000,
            "device_id": device_id,
            "device_kind": device_kind,
        },
    }


@router.post("/device/heartbeat")
async def api_kds_device_heartbeat(
    body: DeviceHeartbeatReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(require_role("cashier", "kds", "store_manager", "admin")),
):
    """Sprint C3 — 设备心跳：upsert edge_device_registry，更新 last_seen_at。

    KDS 默认 30s 一次心跳；POS / crew_phone 遵循各自节奏。
    返回 server_time 供客户端校准时钟 + 建议 poll_interval_ms。
    """
    tenant_id = request.headers.get("X-Tenant-ID") or getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    if user.tenant_id and user.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="USER_TENANT_MISMATCH")

    svc = DeviceRegistryService(db=db, tenant_id=tenant_id)
    try:
        await svc.heartbeat(
            device_id=body.device_id,
            device_kind=body.device_kind,
            store_id=body.store_id,
            device_label=body.device_label,
            os_version=body.os_version,
            app_version=body.app_version,
            buffer_backlog=body.buffer_backlog,
            health_status=body.health_status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError:
        raise HTTPException(status_code=500, detail="DB_ERROR")

    now = datetime.now(timezone.utc)
    return {
        "ok": True,
        "data": {
            "device_id": body.device_id,
            "device_kind": body.device_kind,
            "server_time": now.isoformat().replace("+00:00", "Z"),
            # 建议各终端类型的默认心跳间隔（ms）
            "poll_interval_ms": 30000 if body.device_kind == "kds" else 60000,
        },
    }
