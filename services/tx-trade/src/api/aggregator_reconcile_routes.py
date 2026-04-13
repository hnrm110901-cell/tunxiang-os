"""
外卖聚合对账 — 多平台订单异常单补偿与差异核销
Y-A5 对账模块

端点（prefix /api/v1/trade/aggregator-reconcile）：
  POST   /run                            手动触发对账任务（指定平台+日期）
  GET    /results                        对账结果列表（分页）
  GET    /results/{date}/{platform}      某日某平台对账详情
  GET    /discrepancies                  差异单列表（本地有/平台无，或金额不符）
  POST   /discrepancies/{id}/resolve     人工标记差异已处理
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Path, Query
from fastapi import status as http_status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import async_session_factory

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/trade/aggregator-reconcile",
    tags=["aggregator-reconcile"],
)

# ──────────────────────────────────────────────────────────────────────────────
# 内存存储（mock 层）
# ──────────────────────────────────────────────────────────────────────────────

# 对账结果：key = "{date}:{platform}:{tenant_id}"
_RECONCILE_RESULTS: dict[str, dict] = {}

# 差异单：key = discrepancy_id
_DISCREPANCIES: dict[str, dict] = {}

SUPPORTED_PLATFORMS = {"meituan", "eleme", "douyin"}

PLATFORM_LABELS = {
    "meituan": "美团外卖",
    "eleme": "饿了么",
    "douyin": "抖音外卖",
}

# ──────────────────────────────────────────────────────────────────────────────
# Pydantic 模型
# ──────────────────────────────────────────────────────────────────────────────


class ReconcileRunRequest(BaseModel):
    platform: str = Field(description="对账平台：meituan/eleme/douyin")
    date: str = Field(description="对账日期，格式 YYYY-MM-DD")
    store_id: Optional[str] = Field(default=None, description="指定门店，为空则对账所有门店")


class ResolveDiscrepancyRequest(BaseModel):
    resolution: str = Field(min_length=1, max_length=500, description="处理说明")
    resolved_by: Optional[str] = Field(default=None, max_length=100, description="处理人")


# ──────────────────────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_str() -> str:
    return _now().isoformat()


def _get_platform_orders_placeholder(platform: str, reconcile_date: str) -> list[dict]:
    """
    平台侧订单占位函数 — 未来替换为各平台对账 API 调用。
    美团：POST /waimai/order/queryOrderDetail
    饿了么：GET /api/v3/order/order_list
    抖音：POST /goodlife/v1/order/query
    当前返回空列表，差异计算将标记所有本地订单为 local_only。
    """
    return []


async def _fetch_local_orders(
    db: AsyncSession,
    platform: str,
    reconcile_date: str,
    store_id: Optional[str],
) -> list[dict]:
    """
    从 orders 表查询指定平台当天的已支付订单（RLS 已由调用方 session 保障）。
    """
    try:
        params: dict = {
            "platform": platform,
            "reconcile_date": reconcile_date,
        }
        store_filter = ""
        if store_id:
            store_filter = " AND store_id = :store_id"
            params["store_id"] = store_id

        result = await db.execute(
            text(f"""
                SELECT
                    external_order_id  AS platform_order_id,
                    total_fen,
                    status
                FROM orders
                WHERE channel = :platform
                  AND status = 'paid'
                  AND DATE(created_at AT TIME ZONE 'Asia/Shanghai') = :reconcile_date::date
                  {store_filter}
                ORDER BY created_at
            """),
            params,
        )
        rows = result.fetchall()
        return [
            {
                "platform_order_id": row[0] or f"LOCAL-{uuid.uuid4().hex[:8]}",
                "total_fen": int(row[1]),
                "status": row[2],
            }
            for row in rows
        ]
    except SQLAlchemyError as exc:
        logger.warning(
            "aggregator_reconcile.local_orders_query_fail",
            platform=platform,
            reconcile_date=reconcile_date,
            error=str(exc),
        )
        return []


async def _run_reconcile_logic(
    task_id: str,
    tenant_id: str,
    platform: str,
    reconcile_date: str,
    store_id: Optional[str],
) -> dict:
    """
    对账核心逻辑（异步执行，由后台任务调用）：
    1. 从 orders 表拉取本地订单
    2. 拉取平台订单（占位，待接入平台 API）
    3. 找出三类差异：local_only / platform_only / amount_mismatch
    4. 写入 _RECONCILE_RESULTS 和 _DISCREPANCIES
    """
    platform_orders = _get_platform_orders_placeholder(platform, reconcile_date)

    async with async_session_factory() as db:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )
        local_orders = await _fetch_local_orders(db, platform, reconcile_date, store_id)

    local_map = {o["platform_order_id"]: o for o in local_orders}
    platform_map = {o["platform_order_id"]: o for o in platform_orders}

    discrepancy_list: list[dict] = []

    # 找出 local_only（本地有，平台无）
    for pid, local_o in local_map.items():
        if pid not in platform_map:
            disc_id = f"disc-{uuid.uuid4().hex[:12]}"
            disc = {
                "id": disc_id,
                "task_id": task_id,
                "tenant_id": tenant_id,
                "platform": platform,
                "reconcile_date": reconcile_date,
                "store_id": store_id,
                "discrepancy_type": "local_only",
                "platform_order_id": pid,
                "local_amount_fen": int(local_o["total_fen"]),
                "platform_amount_fen": None,
                "discrepancy_amount_fen": int(local_o["total_fen"]),  # 必须是整数
                "local_status": local_o["status"],
                "platform_status": None,
                "resolved": False,
                "resolution": None,
                "resolved_by": None,
                "resolved_at": None,
                "created_at": _now_str(),
            }
            discrepancy_list.append(disc)
            _DISCREPANCIES[disc_id] = disc

    # 找出 platform_only（平台有，本地无）
    for pid, plat_o in platform_map.items():
        if pid not in local_map:
            disc_id = f"disc-{uuid.uuid4().hex[:12]}"
            disc = {
                "id": disc_id,
                "task_id": task_id,
                "tenant_id": tenant_id,
                "platform": platform,
                "reconcile_date": reconcile_date,
                "store_id": store_id,
                "discrepancy_type": "platform_only",
                "platform_order_id": pid,
                "local_amount_fen": None,
                "platform_amount_fen": int(plat_o["total_fen"]),
                "discrepancy_amount_fen": int(plat_o["total_fen"]),  # 必须是整数
                "local_status": None,
                "platform_status": plat_o["status"],
                "resolved": False,
                "resolution": None,
                "resolved_by": None,
                "resolved_at": None,
                "created_at": _now_str(),
            }
            discrepancy_list.append(disc)
            _DISCREPANCIES[disc_id] = disc

    # 找出 amount_mismatch（金额不符）
    for pid in set(local_map) & set(platform_map):
        local_o = local_map[pid]
        plat_o = platform_map[pid]
        if int(local_o["total_fen"]) != int(plat_o["total_fen"]):
            diff = int(local_o["total_fen"]) - int(plat_o["total_fen"])
            disc_id = f"disc-{uuid.uuid4().hex[:12]}"
            disc = {
                "id": disc_id,
                "task_id": task_id,
                "tenant_id": tenant_id,
                "platform": platform,
                "reconcile_date": reconcile_date,
                "store_id": store_id,
                "discrepancy_type": "amount_mismatch",
                "platform_order_id": pid,
                "local_amount_fen": int(local_o["total_fen"]),
                "platform_amount_fen": int(plat_o["total_fen"]),
                "discrepancy_amount_fen": int(abs(diff)),  # 必须是整数
                "local_status": local_o["status"],
                "platform_status": plat_o["status"],
                "resolved": False,
                "resolution": None,
                "resolved_by": None,
                "resolved_at": None,
                "created_at": _now_str(),
            }
            discrepancy_list.append(disc)
            _DISCREPANCIES[disc_id] = disc

    matched = len(set(local_map) & set(platform_map))
    total_discrepancy_fen: int = sum(int(d["discrepancy_amount_fen"]) for d in discrepancy_list)

    result_key = f"{reconcile_date}:{platform}:{tenant_id}"
    result = {
        "task_id": task_id,
        "tenant_id": tenant_id,
        "platform": platform,
        "platform_label": PLATFORM_LABELS.get(platform, platform),
        "reconcile_date": reconcile_date,
        "store_id": store_id,
        "local_count": len(local_orders),
        "platform_count": len(platform_orders),
        "matched": matched,
        "discrepancy_count": len(discrepancy_list),
        "discrepancy_ids": [d["id"] for d in discrepancy_list],
        "total_discrepancy_fen": total_discrepancy_fen,
        "status": "completed",
        "completed_at": _now_str(),
        "_data_source": "db",
    }
    _RECONCILE_RESULTS[result_key] = result

    logger.info(
        "aggregator_reconcile.completed",
        task_id=task_id,
        platform=platform,
        reconcile_date=reconcile_date,
        local_count=len(local_orders),
        platform_count=len(platform_orders),
        discrepancy_count=len(discrepancy_list),
        total_discrepancy_fen=total_discrepancy_fen,
        tenant_id=tenant_id,
    )
    return result


# ──────────────────────────────────────────────────────────────────────────────
# 端点 1：手动触发对账
# ──────────────────────────────────────────────────────────────────────────────


@router.post("/run", summary="手动触发对账任务（指定平台+日期）")
async def run_reconcile(
    body: ReconcileRunRequest,
    background_tasks: BackgroundTasks,
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    """
    手动触发对账：拉取本地聚合订单与平台数据对比，找出差异单。

    对账结果异步完成（BackgroundTasks），可通过 GET /results/{date}/{platform} 查询。
    """
    if body.platform not in SUPPORTED_PLATFORMS:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail={
                "ok": False,
                "error": {
                    "code": "UNSUPPORTED_PLATFORM",
                    "message": f"不支持的平台：{body.platform}",
                },
            },
        )

    # 校验日期格式
    try:
        date.fromisoformat(body.date)
    except ValueError:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail={
                "ok": False,
                "error": {"code": "INVALID_DATE", "message": f"日期格式错误：{body.date}，应为 YYYY-MM-DD"},
            },
        )

    task_id = f"reconcile-{uuid.uuid4().hex[:12]}"

    background_tasks.add_task(
        _run_reconcile_logic,
        task_id=task_id,
        tenant_id=x_tenant_id,
        platform=body.platform,
        reconcile_date=body.date,
        store_id=body.store_id,
    )

    logger.info(
        "aggregator_reconcile.triggered",
        task_id=task_id,
        platform=body.platform,
        date=body.date,
        store_id=body.store_id,
        tenant_id=x_tenant_id,
    )

    return {
        "ok": True,
        "data": {
            "task_id": task_id,
            "platform": body.platform,
            "date": body.date,
            "store_id": body.store_id,
            "status": "running",
            "note": "对账任务已提交后台，可通过 GET /results/{date}/{platform} 查询结果",
        },
        "error": None,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 端点 2：对账结果列表
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/results", summary="对账结果列表（分页）")
async def list_reconcile_results(
    platform: Optional[str] = Query(None, description="平台过滤"),
    date_from: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    results = [
        r for r in _RECONCILE_RESULTS.values() if r["tenant_id"] == x_tenant_id
    ]

    if platform:
        results = [r for r in results if r["platform"] == platform]
    if date_from:
        results = [r for r in results if r["reconcile_date"] >= date_from]
    if date_to:
        results = [r for r in results if r["reconcile_date"] <= date_to]

    results.sort(key=lambda r: r.get("completed_at", ""), reverse=True)
    total = len(results)
    page_items = results[(page - 1) * size : page * size]

    return {
        "ok": True,
        "data": {
            "items": page_items,
            "total": total,
            "page": page,
            "size": size,
        },
        "error": None,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 端点 3：某日某平台对账详情
# ──────────────────────────────────────────────────────────────────────────────


@router.get(
    "/results/{reconcile_date}/{platform}",
    summary="某日某平台对账详情",
)
async def get_reconcile_result(
    reconcile_date: str = Path(..., description="对账日期 YYYY-MM-DD"),
    platform: str = Path(..., description="平台：meituan/eleme/douyin"),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    result_key = f"{reconcile_date}:{platform}:{x_tenant_id}"
    result = _RECONCILE_RESULTS.get(result_key)

    if result is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={
                "ok": False,
                "error": {
                    "code": "RESULT_NOT_FOUND",
                    "message": f"{reconcile_date} 日 {platform} 对账结果不存在，请先触发对账",
                },
            },
        )

    # 附带差异单摘要
    discrepancies = [
        _DISCREPANCIES[d_id]
        for d_id in result.get("discrepancy_ids", [])
        if d_id in _DISCREPANCIES
    ]

    return {
        "ok": True,
        "data": {
            **result,
            "discrepancies": discrepancies,
        },
        "error": None,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 端点 4：差异单列表
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/discrepancies", summary="差异单列表（本地有/平台无，或金额不符）")
async def list_discrepancies(
    platform: Optional[str] = Query(None, description="平台过滤"),
    discrepancy_type: Optional[str] = Query(
        None, description="差异类型：local_only/platform_only/amount_mismatch"
    ),
    resolved: Optional[bool] = Query(None, description="是否已处理"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    items = [d for d in _DISCREPANCIES.values() if d["tenant_id"] == x_tenant_id]

    if platform:
        items = [d for d in items if d["platform"] == platform]
    if discrepancy_type:
        items = [d for d in items if d["discrepancy_type"] == discrepancy_type]
    if resolved is not None:
        items = [d for d in items if d["resolved"] == resolved]

    items.sort(key=lambda d: d["created_at"], reverse=True)
    total = len(items)
    page_items = items[(page - 1) * size : page * size]

    # 汇总差异金额
    total_discrepancy_fen: int = sum(int(d["discrepancy_amount_fen"]) for d in items)
    unresolved_fen: int = sum(
        int(d["discrepancy_amount_fen"]) for d in items if not d["resolved"]
    )

    return {
        "ok": True,
        "data": {
            "items": page_items,
            "total": total,
            "page": page,
            "size": size,
            "total_discrepancy_fen": total_discrepancy_fen,
            "unresolved_fen": unresolved_fen,
        },
        "error": None,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 端点 5：人工标记差异已处理
# ──────────────────────────────────────────────────────────────────────────────


@router.post(
    "/discrepancies/{discrepancy_id}/resolve",
    summary="人工标记差异已处理",
)
async def resolve_discrepancy(
    discrepancy_id: str = Path(..., description="差异单ID"),
    body: ResolveDiscrepancyRequest = ...,
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
) -> dict:
    disc = _DISCREPANCIES.get(discrepancy_id)

    if disc is None or disc["tenant_id"] != x_tenant_id:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={
                "ok": False,
                "error": {
                    "code": "DISCREPANCY_NOT_FOUND",
                    "message": f"差异单 {discrepancy_id} 不存在",
                },
            },
        )

    if disc["resolved"]:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail={
                "ok": False,
                "error": {
                    "code": "ALREADY_RESOLVED",
                    "message": f"差异单 {discrepancy_id} 已处理",
                },
            },
        )

    disc["resolved"] = True
    disc["resolution"] = body.resolution
    disc["resolved_by"] = body.resolved_by
    disc["resolved_at"] = _now_str()

    logger.info(
        "aggregator_reconcile.discrepancy_resolved",
        discrepancy_id=discrepancy_id,
        platform=disc["platform"],
        discrepancy_type=disc["discrepancy_type"],
        resolved_by=body.resolved_by,
        tenant_id=x_tenant_id,
    )

    return {
        "ok": True,
        "data": disc,
        "error": None,
    }
