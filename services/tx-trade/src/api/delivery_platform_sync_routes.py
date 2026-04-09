"""外卖平台集成同步 API — 菜单推送 / 估清同步 / 对账汇总

端点（prefix /api/v1/delivery/platform-sync）：

  菜单同步：
    POST  /menu-sync/{platform}        将 POS 菜单推送到指定外卖平台
    GET   /menu-sync/status            各平台菜单同步状态

  估清同步：
    POST  /soldout-sync                将 POS 估清状态同步到所有外卖平台
    GET   /soldout-sync/log            估清同步日志

  对账：
    GET   /reconciliation              外卖平台订单对账（跨平台汇总）

所有端点已接入 DB：
  - delivery_menu_sync_tasks     菜单同步任务记录
  - delivery_soldout_sync_log    估清同步日志
  - delivery_orders / aggregator_orders 用于对账查询
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/delivery/platform-sync", tags=["delivery-platform-sync"])

SUPPORTED_PLATFORMS = {"meituan", "eleme", "douyin"}

PLATFORM_LABELS: dict[str, str] = {
    "meituan": "美团外卖",
    "eleme": "饿了么",
    "douyin": "抖音外卖",
}


# ── DB 依赖 ──────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get(
        "X-Tenant-ID", request.headers.get("X-Tenant-Id", "")
    )
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


async def _get_db(request: Request):
    tenant_id = _get_tenant_id(request)
    async for session in get_db_with_tenant(tenant_id):
        yield session


def _validate_platform(platform: str) -> None:
    if platform not in SUPPORTED_PLATFORMS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的平台: {platform}，有效值: {sorted(SUPPORTED_PLATFORMS)}",
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Pydantic 模型 ────────────────────────────────────────────────────────────


class MenuSyncItem(BaseModel):
    """单个菜品同步信息"""
    dish_id: str = Field(min_length=1, max_length=100)
    dish_name: str = Field(min_length=1, max_length=200)
    price_fen: int = Field(ge=0, description="价格（分）")
    category: Optional[str] = Field(default=None, max_length=100)
    is_available: bool = Field(default=True)
    spec_list: Optional[list[dict]] = Field(default=None, description="规格列表")


class MenuSyncRequest(BaseModel):
    """菜单同步请求体"""
    store_id: str = Field(min_length=1, max_length=100)
    items: list[MenuSyncItem] = Field(min_length=1, max_length=500)
    sync_mode: str = Field(default="incremental", pattern="^(full|incremental)$")


class SoldoutSyncRequest(BaseModel):
    """估清同步请求体"""
    store_id: str = Field(min_length=1, max_length=100)
    soldout_items: list[dict] = Field(
        min_length=1,
        description="估清菜品列表，每项含 dish_id, dish_name, reason(可选)",
    )
    platforms: Optional[list[str]] = Field(
        default=None,
        description="指定推送平台，不传则推送到所有已授权平台",
    )


# ── 1. 菜单同步：推送 POS 菜单到外卖平台 ─────────────────────────────────────


@router.post("/menu-sync/{platform}", summary="将 POS 菜单推送到外卖平台")
async def push_menu_to_platform(
    request: Request,
    platform: str = Path(..., description="目标平台: meituan / eleme / douyin"),
    body: MenuSyncRequest = ...,
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """将 POS 菜品数据推送到指定外卖平台。

    同步模式：
      - full: 全量覆盖（平台侧菜单完全替换为本次推送内容）
      - incremental: 增量更新（仅更新本次包含的菜品）

    流程：写入 delivery_menu_sync_tasks 任务记录 → 异步推送到平台 API →
    平台回调更新 task 状态。当前版本同步写入任务记录，平台推送标记为 pending。
    """
    _validate_platform(platform)
    tenant_id = _get_tenant_id(request)
    task_id = str(uuid.uuid4())

    items_json = json.dumps([item.model_dump() for item in body.items])

    await db.execute(
        text("""
            INSERT INTO delivery_menu_sync_tasks
                (id, tenant_id, store_id, platform, sync_mode, items_count,
                 items_snapshot, status, created_at)
            VALUES
                (:id, :tid, :sid, :platform, :mode, :cnt,
                 :items::jsonb, 'pending', :now)
        """),
        {
            "id": task_id,
            "tid": tenant_id,
            "sid": body.store_id,
            "platform": platform,
            "mode": body.sync_mode,
            "cnt": len(body.items),
            "items": items_json,
            "now": _now(),
        },
    )
    await db.commit()

    logger.info(
        "menu_sync.task_created",
        task_id=task_id,
        platform=platform,
        store_id=body.store_id,
        items_count=len(body.items),
        sync_mode=body.sync_mode,
    )

    return {
        "ok": True,
        "data": {
            "task_id": task_id,
            "platform": platform,
            "platform_label": PLATFORM_LABELS.get(platform, platform),
            "store_id": body.store_id,
            "items_count": len(body.items),
            "sync_mode": body.sync_mode,
            "status": "pending",
            "message": f"菜单同步任务已创建，等待推送到{PLATFORM_LABELS.get(platform, platform)}",
        },
        "error": None,
    }


# ── 2. 菜单同步状态查询 ─────────────────────────────────────────────────────


@router.get("/menu-sync/status", summary="各平台菜单同步状态")
async def get_menu_sync_status(
    request: Request,
    store_id: Optional[str] = Query(None, description="门店 ID，不传则查全部"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """返回各平台最近一次菜单同步任务的状态。

    包含：任务 ID、同步模式、菜品数量、状态、创建时间、完成时间。
    """
    tenant_id = _get_tenant_id(request)

    conds = ["tenant_id = :tid"]
    params: dict = {"tid": tenant_id}
    if store_id:
        conds.append("store_id = :sid")
        params["sid"] = store_id

    where = " AND ".join(conds)

    rows = await db.execute(
        text(f"""
            SELECT DISTINCT ON (platform)
                id, store_id, platform, sync_mode, items_count,
                status, error_message, created_at, completed_at
            FROM delivery_menu_sync_tasks
            WHERE {where}
            ORDER BY platform, created_at DESC
        """),
        params,
    )
    results = rows.fetchall()

    platforms_status = []
    seen_platforms = set()
    for r in results:
        d = dict(r._mapping)
        d["platform_label"] = PLATFORM_LABELS.get(d["platform"], d["platform"])
        platforms_status.append(d)
        seen_platforms.add(d["platform"])

    # 未同步过的平台也列出
    for pid in SUPPORTED_PLATFORMS - seen_platforms:
        platforms_status.append({
            "platform": pid,
            "platform_label": PLATFORM_LABELS[pid],
            "status": "never_synced",
            "items_count": 0,
            "sync_mode": None,
            "created_at": None,
            "completed_at": None,
        })

    return {
        "ok": True,
        "data": {"platforms": platforms_status},
        "error": None,
    }


# ── 3. 估清同步：将 POS 估清推送到所有外卖平台 ────────────────────────────────


@router.post("/soldout-sync", summary="将 POS 估清状态同步到外卖平台")
async def sync_soldout_to_platforms(
    request: Request,
    body: SoldoutSyncRequest = ...,
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """将 POS 估清（售罄）菜品状态同步推送到各外卖平台。

    如果指定 platforms 列表，仅推送到对应平台；否则推送到所有已支持平台。

    每个平台生成一条同步日志，记录推送结果。
    当前版本同步写入日志，实际平台调用标记为 pending。
    """
    tenant_id = _get_tenant_id(request)
    target_platforms = body.platforms or list(SUPPORTED_PLATFORMS)

    # 校验平台列表
    for p in target_platforms:
        _validate_platform(p)

    batch_id = str(uuid.uuid4())
    now = _now()
    sync_results = []

    for platform in target_platforms:
        log_id = str(uuid.uuid4())
        items_json = json.dumps(body.soldout_items)

        await db.execute(
            text("""
                INSERT INTO delivery_soldout_sync_log
                    (id, tenant_id, store_id, platform, batch_id,
                     soldout_items, items_count, status, created_at)
                VALUES
                    (:id, :tid, :sid, :platform, :bid,
                     :items::jsonb, :cnt, 'pending', :now)
            """),
            {
                "id": log_id,
                "tid": tenant_id,
                "sid": body.store_id,
                "platform": platform,
                "bid": batch_id,
                "items": items_json,
                "cnt": len(body.soldout_items),
                "now": now,
            },
        )

        sync_results.append({
            "log_id": log_id,
            "platform": platform,
            "platform_label": PLATFORM_LABELS.get(platform, platform),
            "status": "pending",
            "items_count": len(body.soldout_items),
        })

    await db.commit()

    logger.info(
        "soldout_sync.batch_created",
        batch_id=batch_id,
        store_id=body.store_id,
        platforms=target_platforms,
        items_count=len(body.soldout_items),
    )

    return {
        "ok": True,
        "data": {
            "batch_id": batch_id,
            "store_id": body.store_id,
            "platforms": sync_results,
            "total_platforms": len(sync_results),
            "total_soldout_items": len(body.soldout_items),
        },
        "error": None,
    }


# ── 4. 估清同步日志 ─────────────────────────────────────────────────────────


@router.get("/soldout-sync/log", summary="估清同步日志")
async def get_soldout_sync_log(
    request: Request,
    store_id: Optional[str] = Query(None, description="门店 ID"),
    platform: Optional[str] = Query(None, description="平台筛选"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """查询估清同步日志，支持按门店、平台筛选，分页返回。"""
    tenant_id = _get_tenant_id(request)

    if platform:
        _validate_platform(platform)

    conds = ["tenant_id = :tid"]
    params: dict = {"tid": tenant_id, "limit": size, "offset": (page - 1) * size}
    if store_id:
        conds.append("store_id = :sid")
        params["sid"] = store_id
    if platform:
        conds.append("platform = :platform")
        params["platform"] = platform

    where = " AND ".join(conds)

    total = (
        await db.execute(
            text(f"SELECT COUNT(*) FROM delivery_soldout_sync_log WHERE {where}"),
            params,
        )
    ).scalar() or 0

    rows = await db.execute(
        text(f"""
            SELECT id, store_id, platform, batch_id, items_count,
                   status, error_message, created_at, completed_at
            FROM delivery_soldout_sync_log
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items = []
    for r in rows.fetchall():
        d = dict(r._mapping)
        d["platform_label"] = PLATFORM_LABELS.get(d["platform"], d["platform"])
        items.append(d)

    return {
        "ok": True,
        "data": {"items": items, "total": total, "page": page, "size": size},
        "error": None,
    }


# ── 5. 外卖平台对账汇总 ─────────────────────────────────────────────────────


@router.get("/reconciliation", summary="外卖平台订单对账（跨平台汇总）")
async def get_reconciliation_overview(
    request: Request,
    store_id: Optional[str] = Query(None, description="门店 ID"),
    platform: Optional[str] = Query(None, description="平台筛选"),
    date_from: Optional[date] = Query(None, description="开始日期，默认 7 天前"),
    date_to: Optional[date] = Query(None, description="结束日期，默认今天"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """跨平台外卖订单对账汇总。

    聚合查询 delivery_orders 表（终态订单），按平台分组统计：
      - 订单总数 / 完成数 / 取消数 / 退款数
      - 平台总金额 / 佣金总额 / 商户应收总额
      - 实收 vs 应收差异金额（对账差异）

    可按门店、平台、日期范围筛选。
    """
    tenant_id = _get_tenant_id(request)

    if platform:
        _validate_platform(platform)

    if date_to is None:
        date_to = date.today()
    if date_from is None:
        date_from = date_to - timedelta(days=7)
    if date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from 不能晚于 date_to")

    conds = ["tenant_id = :tid", "created_at::date >= :d_from", "created_at::date <= :d_to"]
    params: dict = {"tid": tenant_id, "d_from": date_from, "d_to": date_to}

    if store_id:
        conds.append("store_id = :sid")
        params["sid"] = store_id
    if platform:
        conds.append("platform = :platform")
        params["platform"] = platform

    where = " AND ".join(conds)

    rows = await db.execute(
        text(f"""
            SELECT
                platform,
                COUNT(*) AS total_orders,
                COUNT(*) FILTER (WHERE status = 'completed') AS completed_count,
                COUNT(*) FILTER (WHERE status = 'cancelled') AS cancelled_count,
                COUNT(*) FILTER (WHERE status = 'refunded') AS refunded_count,
                COALESCE(SUM(total_fen), 0) AS total_amount_fen,
                COALESCE(SUM(commission_fen), 0) AS total_commission_fen,
                COALESCE(SUM(merchant_receive_fen), 0) AS total_merchant_receive_fen,
                COALESCE(SUM(actual_revenue_fen), 0) AS total_actual_revenue_fen,
                COALESCE(
                    SUM(actual_revenue_fen) - SUM(merchant_receive_fen), 0
                ) AS discrepancy_fen
            FROM delivery_orders
            WHERE {where}
            GROUP BY platform
            ORDER BY platform
        """),
        params,
    )

    platform_summaries = []
    grand_total_orders = 0
    grand_total_amount = 0
    grand_discrepancy = 0

    for r in rows.fetchall():
        d = dict(r._mapping)
        d["platform_label"] = PLATFORM_LABELS.get(d["platform"], d["platform"])
        platform_summaries.append(d)
        grand_total_orders += d["total_orders"]
        grand_total_amount += d["total_amount_fen"]
        grand_discrepancy += d["discrepancy_fen"]

    return {
        "ok": True,
        "data": {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "grand_total_orders": grand_total_orders,
            "grand_total_amount_fen": grand_total_amount,
            "grand_discrepancy_fen": grand_discrepancy,
            "by_platform": platform_summaries,
        },
        "error": None,
    }
