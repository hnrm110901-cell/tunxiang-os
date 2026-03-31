"""
出餐时间预测 + 翻台时机预测 API 路由

端点：
  GET /api/v1/predict/dish-time/{dish_id}
      params: store_id, dept_id
      返回该菜品当前预计制作时间

  GET /api/v1/predict/order/{order_id}/completion
      返回该订单预计出餐完成时间

  GET /api/v1/predict/table/{table_no}/turn
      params: store_id, order_id(可选), seats(可选), elapsed_minutes(可选)
      返回翻台时间预测

  GET /api/v1/predict/busy-periods
      params: store_id, date(YYYY-MM-DD)
      返回今日高峰时段预测列表

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from __future__ import annotations

from datetime import date as dt_date
from typing import Optional

import structlog
from fastapi import APIRouter, Header, Query, Request

router = APIRouter(prefix="/api/v1/predict", tags=["prediction"])

log = structlog.get_logger(__name__)


# ─── 租户ID提取 ───

def _get_tenant_id(request: Request) -> str:
    return (
        getattr(request.state, "tenant_id", None)
        or request.headers.get("X-Tenant-ID", "")
        or "default"
    )


# ─── 数据库依赖（软依赖，无DB时降级Mock） ───

async def _try_get_db():
    """尝试获取数据库会话。返回 None 时降级到 Mock 规则引擎。"""
    try:
        from shared.ontology.src.database import async_session_factory  # type: ignore[import]
        async with async_session_factory() as session:
            yield session
    except (ImportError, RuntimeError, Exception):  # noqa: BLE001 — 最外层兜底，DB不可用时返回None
        yield None


# ─── 路由 ───

@router.get("/dish-time/{dish_id}")
async def get_dish_time_prediction(
    dish_id: str,
    request: Request,
    store_id: str = Query(default="", description="门店ID"),
    dept_id: str = Query(default="", description="档口ID"),
) -> dict:
    """
    菜品出餐时间预测。

    返回该菜品在当前时段、当前队列深度下的预计制作时间。
    优先调用 Core ML（边缘推理），不可用时降级规则引擎。
    """
    tenant_id = _get_tenant_id(request)
    try:
        from ..services.prediction_service import predict_dish_time
    except ImportError:
        from services.prediction_service import predict_dish_time  # type: ignore[no-redef]

    result = await predict_dish_time(
        dish_id=dish_id,
        dept_id=dept_id or "default",
        store_id=store_id or "default",
        tenant_id=tenant_id,
        db=None,  # 当前路由不依赖DB session，规则引擎独立运行
    )
    return {"ok": True, "data": result.to_dict()}


@router.get("/order/{order_id}/completion")
async def get_order_completion_prediction(
    order_id: str,
    request: Request,
) -> dict:
    """
    订单整体出餐完成时间预测。

    获取订单所有未出餐菜品并预测最大制作时间。
    无法获取订单数据时降级到 Mock 预测。
    """
    tenant_id = _get_tenant_id(request)
    try:
        from ..services.prediction_service import predict_order_completion
    except ImportError:
        from services.prediction_service import predict_order_completion  # type: ignore[no-redef]

    # 尝试获取DB session，失败时用 None 触发 Mock 降级
    db = None
    try:
        from shared.ontology.src.database import async_session_factory  # type: ignore[import]
        async with async_session_factory() as session:
            result = await predict_order_completion(
                order_id=order_id,
                tenant_id=tenant_id,
                db=session,
            )
            return {"ok": True, "data": result.to_dict()}
    except (ImportError, Exception):  # noqa: BLE001
        pass

    result = await predict_order_completion(
        order_id=order_id,
        tenant_id=tenant_id,
        db=db,
    )
    return {"ok": True, "data": result.to_dict()}


@router.get("/table/{table_no}/turn")
async def get_table_turn_prediction(
    table_no: str,
    request: Request,
    store_id: str = Query(default="", description="门店ID"),
    order_id: str = Query(default="", description="当前订单ID（可选）"),
    seats: int = Query(default=4, description="桌台座位数"),
    elapsed_minutes: int = Query(default=0, description="已就餐分钟数"),
) -> dict:
    """
    桌台翻台时机预测。

    预计该桌台还需多少分钟结束就餐。
    置信度 high/medium 时提供候位提醒建议。
    """
    tenant_id = _get_tenant_id(request)
    try:
        from ..services.prediction_service import predict_table_turn
    except ImportError:
        from services.prediction_service import predict_table_turn  # type: ignore[no-redef]

    db = None
    try:
        from shared.ontology.src.database import async_session_factory  # type: ignore[import]
        async with async_session_factory() as session:
            result = await predict_table_turn(
                table_no=table_no,
                order_id=order_id,
                store_id=store_id or "default",
                tenant_id=tenant_id,
                db=session,
                seats=seats,
                elapsed_minutes=elapsed_minutes,
            )
            return {"ok": True, "data": result.to_dict()}
    except (ImportError, Exception):  # noqa: BLE001
        pass

    result = await predict_table_turn(
        table_no=table_no,
        order_id=order_id,
        store_id=store_id or "default",
        tenant_id=tenant_id,
        db=db,
        seats=seats,
        elapsed_minutes=elapsed_minutes,
    )
    return {"ok": True, "data": result.to_dict()}


@router.get("/busy-periods")
async def get_busy_periods(
    request: Request,
    store_id: str = Query(default="", description="门店ID"),
    date: str = Query(default="", description="日期 YYYY-MM-DD，默认今日"),
) -> dict:
    """
    今日高峰时段预测。

    基于历史客流数据识别高峰时段，无数据时返回通用午晚高峰模板。
    """
    tenant_id = _get_tenant_id(request)
    if not date:
        date = dt_date.today().isoformat()

    try:
        from ..services.prediction_service import get_busy_period_forecast
    except ImportError:
        from services.prediction_service import get_busy_period_forecast  # type: ignore[no-redef]

    db = None
    periods: list = []
    try:
        from shared.ontology.src.database import async_session_factory  # type: ignore[import]
        async with async_session_factory() as session:
            periods = await get_busy_period_forecast(
                store_id=store_id or "default",
                date=date,
                tenant_id=tenant_id,
                db=session,
            )
    except (ImportError, Exception):  # noqa: BLE001
        periods = await get_busy_period_forecast(
            store_id=store_id or "default",
            date=date,
            tenant_id=tenant_id,
            db=db,
        )

    return {"ok": True, "data": {"date": date, "periods": [p.to_dict() for p in periods]}}
