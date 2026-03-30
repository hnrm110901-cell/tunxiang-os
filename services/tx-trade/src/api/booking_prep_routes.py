"""预订备餐联动 API — KDS 预备单端点

路由注册（在 main.py 中添加）:
    from .api.booking_prep_routes import router as booking_prep_router
    app.include_router(booking_prep_router, prefix="/api/v1/booking-prep")

所有接口需 X-Tenant-ID header。
统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from fastapi import APIRouter, HTTPException, Request

from ..services.booking_prep_service import BookingPrepService

router = APIRouter(tags=["booking-prep"])


# ─── 通用辅助 ───

def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: object) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> None:
    """抛出 HTTPException，返回类型为 None 以明确不会返回值。"""
    raise HTTPException(
        status_code=code,
        detail={"ok": False, "data": None, "error": {"message": msg}},
    )


# ─── 端点 ───

@router.get("/today-summary/{store_id}")
async def get_today_summary(store_id: str, request: Request) -> dict:
    """预订汇总看板数据。

    返回今日预订数、本周预订数、菜品需求 TOP10。
    """
    tenant_id = _get_tenant_id(request)
    summary = BookingPrepService.get_today_summary(
        store_id=store_id,
        tenant_id=tenant_id,
    )
    return _ok(summary.to_dict())


@router.get("/pending/{store_id}")
async def get_pending_tasks(store_id: str, request: Request) -> dict:
    """待备餐任务列表（KDS备餐视图数据源）。

    返回状态为 pending/started 的任务，按就餐时间升序排列。
    """
    tenant_id = _get_tenant_id(request)
    tasks = BookingPrepService.get_pending_prep_tasks(
        store_id=store_id,
        tenant_id=tenant_id,
    )
    return _ok({"items": [t.to_dict() for t in tasks], "total": len(tasks)})


@router.post("/booking/{booking_id}/generate")
async def generate_prep_tasks(booking_id: str, request: Request) -> dict:
    """手动触发备餐任务生成（幂等）。

    根据预订中的菜品信息生成备餐任务，重复调用返回已有任务。
    """
    tenant_id = _get_tenant_id(request)
    try:
        tasks = BookingPrepService.generate_prep_tasks(
            booking_id=booking_id,
            tenant_id=tenant_id,
        )
    except ValueError as e:
        _err(str(e))
    return _ok({"items": [t.to_dict() for t in tasks], "total": len(tasks)})


@router.post("/task/{task_id}/start")
async def start_prep_task(task_id: str, request: Request) -> dict:
    """开始备餐（pending → started）。"""
    tenant_id = _get_tenant_id(request)
    try:
        task = BookingPrepService.mark_prep_started(
            task_id=task_id,
            tenant_id=tenant_id,
        )
    except ValueError as e:
        _err(str(e))
    return _ok(task.to_dict())


@router.post("/task/{task_id}/done")
async def done_prep_task(task_id: str, request: Request) -> dict:
    """完成备餐（started → done）。"""
    tenant_id = _get_tenant_id(request)
    try:
        task = BookingPrepService.mark_prep_done(
            task_id=task_id,
            tenant_id=tenant_id,
        )
    except ValueError as e:
        _err(str(e))
    return _ok(task.to_dict())
