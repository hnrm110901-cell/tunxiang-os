"""外部数据采集层 FastAPI 路由 — Market Intel OS 外部数据入口

端点列表：
  GET  /intel/competitors                — 列出竞对品牌
  POST /intel/competitors                — 新增竞对品牌
  GET  /intel/competitors/{id}/snapshots — 竞对快照列表
  POST /intel/competitors/{id}/snapshot  — 手动触发竞对快照采集
  GET  /intel/reviews                    — 点评情报列表（支持 is_own_store 过滤）
  POST /intel/reviews/collect            — 手动触发点评采集
  GET  /intel/trends                     — 市场趋势信号列表
  POST /intel/trends/scan                — 手动触发趋势扫描
  POST /intel/tasks                      — 创建采集任务
  GET  /intel/tasks                      — 列出采集任务
  PATCH /intel/tasks/{id}                — 更新采集任务状态

所有端点通过 X-Tenant-ID header 传递租户 ID（由 Gateway 注入）。
"""
import uuid
from datetime import date
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

router = APIRouter(prefix="/intel", tags=["market-intel-external"])


# ─── 依赖项 ───

async def get_db() -> AsyncSession:  # type: ignore[return]
    """数据库 session 依赖（由应用 lifespan 中注入真实实现）"""
    raise NotImplementedError("请在应用启动时注入 DB session factory")


async def get_tenant_id(x_tenant_id: Annotated[str, Header()]) -> uuid.UUID:
    """从请求头解析租户 ID"""
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-ID 格式无效")


# ─── 请求/响应模型 ───

class CompetitorBrandCreate(BaseModel):
    name: str = Field(..., max_length=100)
    cuisine_type: str | None = Field(None, max_length=50)
    price_tier: str | None = Field(None, pattern="^(economy|mid_range|mid_premium|premium|luxury)$")
    city: str | None = Field(None, max_length=50)
    district: str | None = Field(None, max_length=50)
    platform_ids: dict[str, str] = Field(default_factory=dict)
    is_active: bool = True


class CollectReviewsReq(BaseModel):
    source: str = Field(..., pattern="^(meituan|douyin|eleme|dianping)$")
    platform_store_id: str = Field(..., max_length=100)
    is_own_store: bool = True
    days: int = Field(7, ge=1, le=90)


class ScanTrendsReq(BaseModel):
    city: str = Field(..., max_length=50)
    cuisine_type: str = Field(..., max_length=50)


class ScanIngredientTrendsReq(BaseModel):
    category: str = Field(..., max_length=50)
    region: str = Field("全国", max_length=50)


class CrawlTaskCreate(BaseModel):
    task_type: str = Field(
        ...,
        pattern="^(competitor_snapshot|own_store_reviews|competitor_reviews|dish_trends|ingredient_trends)$",
    )
    target_config: dict[str, Any] = Field(default_factory=dict)
    schedule_cron: str | None = Field(None, max_length=50)


class CrawlTaskPatch(BaseModel):
    status: str | None = Field(None, pattern="^(active|paused|error|completed)$")
    schedule_cron: str | None = Field(None, max_length=50)
    target_config: dict[str, Any] | None = None


# ─── 通用响应工具 ───

def ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


def err(message: str, status_code: int = 400) -> None:
    raise HTTPException(status_code=status_code, detail={"ok": False, "data": None, "error": message})


# ═══════════════════════════════════════
# 竞对品牌
# ═══════════════════════════════════════

@router.get("/competitors")
async def list_competitors(
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    city: str | None = Query(None),
    cuisine_type: str | None = Query(None),
    is_active: bool = Query(True),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> dict:
    """列出竞对品牌（支持城市/菜系过滤）"""
    conditions = ["tenant_id = :tenant_id", "is_active = :is_active"]
    params: dict[str, Any] = {
        "tenant_id": str(tenant_id),
        "is_active": is_active,
        "offset": (page - 1) * size,
        "limit": size,
    }
    if city:
        conditions.append("city = :city")
        params["city"] = city
    if cuisine_type:
        conditions.append("cuisine_type = :cuisine_type")
        params["cuisine_type"] = cuisine_type

    where = " AND ".join(conditions)
    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM competitor_brands WHERE {where}"),
        {k: v for k, v in params.items() if k not in ("offset", "limit")},
    )
    total = count_result.scalar() or 0

    rows = await db.execute(
        text(f"""
            SELECT id, name, cuisine_type, price_tier, city, district,
                   platform_ids, is_active, created_at
            FROM competitor_brands
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items = [dict(r._mapping) for r in rows.fetchall()]
    return ok({"items": items, "total": total, "page": page, "size": size})


@router.post("/competitors", status_code=201)
async def create_competitor(
    req: CompetitorBrandCreate,
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """新增竞对品牌档案"""
    brand_id = uuid.uuid4()
    import json
    await db.execute(
        text("""
            INSERT INTO competitor_brands
                (id, tenant_id, name, cuisine_type, price_tier, city, district,
                 platform_ids, is_active)
            VALUES
                (:id, :tenant_id, :name, :cuisine_type, :price_tier, :city, :district,
                 :platform_ids::jsonb, :is_active)
        """),
        {
            "id": str(brand_id),
            "tenant_id": str(tenant_id),
            "name": req.name,
            "cuisine_type": req.cuisine_type,
            "price_tier": req.price_tier,
            "city": req.city,
            "district": req.district,
            "platform_ids": json.dumps(req.platform_ids, ensure_ascii=False),
            "is_active": req.is_active,
        },
    )
    await db.commit()
    logger.info("intel_router.competitor_created", brand_id=str(brand_id), name=req.name)
    return ok({"id": str(brand_id), "name": req.name})


@router.get("/competitors/{competitor_id}/snapshots")
async def list_competitor_snapshots(
    competitor_id: uuid.UUID,
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> dict:
    """获取竞对快照列表（按时间倒序）"""
    params: dict[str, Any] = {
        "tenant_id": str(tenant_id),
        "brand_id": str(competitor_id),
        "offset": (page - 1) * size,
        "limit": size,
    }
    count_result = await db.execute(
        text("""
            SELECT COUNT(*) FROM competitor_snapshots
            WHERE tenant_id = :tenant_id AND competitor_brand_id = :brand_id
        """),
        {"tenant_id": str(tenant_id), "brand_id": str(competitor_id)},
    )
    total = count_result.scalar() or 0

    rows = await db.execute(
        text("""
            SELECT id, snapshot_date, avg_rating, review_count,
                   price_range, top_dishes, active_promotions, source, created_at
            FROM competitor_snapshots
            WHERE tenant_id = :tenant_id AND competitor_brand_id = :brand_id
            ORDER BY snapshot_date DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items = [dict(r._mapping) for r in rows.fetchall()]
    return ok({"items": items, "total": total, "page": page, "size": size})


@router.post("/competitors/{competitor_id}/snapshot")
async def trigger_competitor_snapshot(
    competitor_id: uuid.UUID,
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """手动触发竞对快照采集"""
    from services.competitor_monitor_ext import CompetitorMonitorExtService
    svc = CompetitorMonitorExtService(db)
    result = await svc.run_competitor_snapshot(tenant_id, competitor_id)
    if not result.get("ok"):
        err(result.get("error", "采集失败"), 500)
    return ok(result)


# ═══════════════════════════════════════
# 点评情报
# ═══════════════════════════════════════

@router.get("/reviews")
async def list_reviews(
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    is_own_store: bool | None = Query(None),
    source: str | None = Query(None),
    source_store_id: str | None = Query(None),
    since: date | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> dict:
    """列出点评情报（支持 is_own_store、来源、门店 ID、时间过滤）"""
    conditions = ["tenant_id = :tenant_id"]
    params: dict[str, Any] = {
        "tenant_id": str(tenant_id),
        "offset": (page - 1) * size,
        "limit": size,
    }
    if is_own_store is not None:
        conditions.append("is_own_store = :is_own_store")
        params["is_own_store"] = is_own_store
    if source:
        conditions.append("source = :source")
        params["source"] = source
    if source_store_id:
        conditions.append("source_store_id = :source_store_id")
        params["source_store_id"] = source_store_id
    if since:
        conditions.append("review_date >= :since")
        params["since"] = since.isoformat()

    where = " AND ".join(conditions)
    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM review_intel WHERE {where}"),
        {k: v for k, v in params.items() if k not in ("offset", "limit")},
    )
    total = count_result.scalar() or 0

    rows = await db.execute(
        text(f"""
            SELECT id, source, source_store_id, is_own_store,
                   content, rating, sentiment_score, topics,
                   author_level, review_date, collected_at
            FROM review_intel
            WHERE {where}
            ORDER BY review_date DESC, collected_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items = [dict(r._mapping) for r in rows.fetchall()]
    return ok({"items": items, "total": total, "page": page, "size": size})


@router.post("/reviews/collect")
async def collect_reviews(
    req: CollectReviewsReq,
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """手动触发点评采集"""
    from services.review_collector import ReviewCollectorService
    svc = ReviewCollectorService(db)
    result = await svc.collect_store_reviews(
        tenant_id=tenant_id,
        source=req.source,
        platform_store_id=req.platform_store_id,
        is_own_store=req.is_own_store,
        days=req.days,
    )
    if not result.get("ok"):
        err(result.get("error", "采集失败"), 500)
    return ok(result)


# ═══════════════════════════════════════
# 市场趋势
# ═══════════════════════════════════════

@router.get("/trends")
async def list_trends(
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    signal_type: str | None = Query(None),
    region: str | None = Query(None),
    trend_direction: str | None = Query(None),
    min_score: float = Query(0.0, ge=0, le=100),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> dict:
    """列出市场趋势信号"""
    conditions = ["tenant_id = :tenant_id", "trend_score >= :min_score"]
    params: dict[str, Any] = {
        "tenant_id": str(tenant_id),
        "min_score": min_score,
        "offset": (page - 1) * size,
        "limit": size,
    }
    if signal_type:
        conditions.append("signal_type = :signal_type")
        params["signal_type"] = signal_type
    if region:
        conditions.append("region = :region")
        params["region"] = region
    if trend_direction:
        conditions.append("trend_direction = :trend_direction")
        params["trend_direction"] = trend_direction

    where = " AND ".join(conditions)
    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM market_trend_signals WHERE {where}"),
        {k: v for k, v in params.items() if k not in ("offset", "limit")},
    )
    total = count_result.scalar() or 0

    rows = await db.execute(
        text(f"""
            SELECT id, signal_type, keyword, category, trend_score,
                   trend_direction, source, region, period_start, period_end, created_at
            FROM market_trend_signals
            WHERE {where}
            ORDER BY trend_score DESC, created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items = [dict(r._mapping) for r in rows.fetchall()]
    return ok({"items": items, "total": total, "page": page, "size": size})


@router.post("/trends/scan/dishes")
async def scan_dish_trends(
    req: ScanTrendsReq,
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """手动触发菜品趋势扫描"""
    from services.trend_scanner import TrendScannerService
    svc = TrendScannerService(db)
    result = await svc.scan_dish_trends(tenant_id, req.city, req.cuisine_type)
    if not result.get("ok"):
        err(result.get("error", "扫描失败"), 500)
    return ok(result)


@router.post("/trends/scan/ingredients")
async def scan_ingredient_trends(
    req: ScanIngredientTrendsReq,
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """手动触发食材趋势扫描"""
    from services.trend_scanner import TrendScannerService
    svc = TrendScannerService(db)
    result = await svc.scan_ingredient_trends(tenant_id, req.category, req.region)
    if not result.get("ok"):
        err(result.get("error", "扫描失败"), 500)
    return ok(result)


# ═══════════════════════════════════════
# 采集任务调度
# ═══════════════════════════════════════

@router.post("/tasks", status_code=201)
async def create_crawl_task(
    req: CrawlTaskCreate,
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """创建采集任务"""
    import json
    task_id = uuid.uuid4()
    await db.execute(
        text("""
            INSERT INTO intel_crawl_tasks
                (id, tenant_id, task_type, target_config, schedule_cron, status)
            VALUES
                (:id, :tenant_id, :task_type, :target_config::jsonb, :schedule_cron, 'active')
        """),
        {
            "id": str(task_id),
            "tenant_id": str(tenant_id),
            "task_type": req.task_type,
            "target_config": json.dumps(req.target_config, ensure_ascii=False),
            "schedule_cron": req.schedule_cron,
        },
    )
    await db.commit()
    logger.info("intel_router.task_created", task_id=str(task_id), task_type=req.task_type)
    return ok({"id": str(task_id), "task_type": req.task_type, "status": "active"})


@router.get("/tasks")
async def list_crawl_tasks(
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    task_type: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> dict:
    """列出采集任务"""
    conditions = ["tenant_id = :tenant_id"]
    params: dict[str, Any] = {
        "tenant_id": str(tenant_id),
        "offset": (page - 1) * size,
        "limit": size,
    }
    if task_type:
        conditions.append("task_type = :task_type")
        params["task_type"] = task_type
    if status:
        conditions.append("status = :status")
        params["status"] = status

    where = " AND ".join(conditions)
    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM intel_crawl_tasks WHERE {where}"),
        {k: v for k, v in params.items() if k not in ("offset", "limit")},
    )
    total = count_result.scalar() or 0

    rows = await db.execute(
        text(f"""
            SELECT id, task_type, target_config, schedule_cron,
                   last_run_at, next_run_at, status, error_log, created_at
            FROM intel_crawl_tasks
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items = [dict(r._mapping) for r in rows.fetchall()]
    return ok({"items": items, "total": total, "page": page, "size": size})


@router.patch("/tasks/{task_id}")
async def update_crawl_task(
    task_id: uuid.UUID,
    req: CrawlTaskPatch,
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """更新采集任务状态或配置"""
    import json

    updates: list[str] = []
    params: dict[str, Any] = {
        "task_id": str(task_id),
        "tenant_id": str(tenant_id),
    }

    if req.status is not None:
        updates.append("status = :status")
        params["status"] = req.status
    if req.schedule_cron is not None:
        updates.append("schedule_cron = :schedule_cron")
        params["schedule_cron"] = req.schedule_cron
    if req.target_config is not None:
        updates.append("target_config = :target_config::jsonb")
        params["target_config"] = json.dumps(req.target_config, ensure_ascii=False)

    if not updates:
        err("未提供任何更新字段")

    result = await db.execute(
        text(f"""
            UPDATE intel_crawl_tasks
            SET {', '.join(updates)}
            WHERE id = :task_id AND tenant_id = :tenant_id
        """),
        params,
    )
    await db.commit()

    if result.rowcount == 0:
        err("采集任务不存在", 404)

    return ok({"id": str(task_id), "updated": True})
