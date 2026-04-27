"""成本健康指数 API 路由

多品牌成本健康指数引擎：跨品牌/跨门店对标食材成本、人力成本、损耗率。

端点：
  GET /cost-health/store/{id}          — 单店成本健康报告
  GET /cost-health/group/heatmap       — 集团热力图（所有门店排序）
  GET /cost-health/brand/{id}/benchmark — 品牌成本基准
  GET /cost-health/alerts              — 成本异常预警列表
  GET /cost-health/store/{id}/suggestions — AI 成本优化建议

所有接口：
  - 需要 X-Tenant-ID header（RLS 隔离）
  - 计算结果允许1小时缓存（Cache-Control 头）
  - AI 建议仅在 health_score < 65 时触发
"""

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.cost_health_engine import (
    CostHealthEngine,
    _cache_get,
    _cache_set,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/cost-health", tags=["cost-health"])

# 1小时缓存（秒）
_CACHE_MAX_AGE = 3600


# ── 依赖注入 ──────────────────────────────────────────────────────────────────


def _require_tenant(x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID")) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header 必填")
    return x_tenant_id


async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _cached_response(data: dict, cache_seconds: int = _CACHE_MAX_AGE) -> JSONResponse:
    """带缓存头的 JSON 响应"""
    return JSONResponse(
        content={"ok": True, "data": data},
        headers={"Cache-Control": f"max-age={cache_seconds}, private"},
    )


# ── 1. 单店成本健康报告 ───────────────────────────────────────────────────────


@router.get(
    "/store/{store_id}",
    summary="单店成本健康报告",
    description=("返回单店三维度（食材/人力/损耗）成本健康评分、健康等级、与品牌基准的偏差分析，以及异常维度标记。"),
)
async def get_store_cost_health(
    store_id: str,
    days: int = Query(default=30, ge=7, le=365, description="统计周期（天），最少7天最多365天"),
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """单店成本健康报告

    - ingredient_cost_rate: 食材成本率（来自 order_items + orders）
    - labor_cost_rate: 人力成本率（来自 crew_shifts + employees）
    - waste_rate: 损耗率（来自 waste_records + purchase_orders）
    - health_score: 三维度加权综合分 0-100
    - health_level: healthy（≥80）/ warning（≥65）/ critical（<65）
    - benchmark: 同品牌其他门店的中位数
    - deviation: 与基准的相对偏差（正=高于基准，负=低于基准）
    """
    cache_key = f"store_cost_health:{tenant_id}:{store_id}:{days}"
    cached = _cache_get(cache_key)
    if cached:
        return _cached_response(cached)

    engine = CostHealthEngine()
    try:
        report = await engine.calc_store_cost_health(
            store_id=store_id,
            tenant_id=tenant_id,
            period_days=days,
            db=db,
        )
    except (ValueError, TypeError) as exc:
        logger.error(
            "get_store_cost_health.failed",
            store_id=store_id,
            tenant_id=tenant_id,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "get_store_cost_health.internal_error",
            store_id=store_id,
            tenant_id=tenant_id,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="成本健康报告生成失败") from exc

    result = report.model_dump()
    _cache_set(cache_key, result)
    return _cached_response(result)


# ── 2. 集团成本热力图 ─────────────────────────────────────────────────────────


@router.get(
    "/group/heatmap",
    summary="集团成本热力图",
    description=("返回该租户所有门店的成本健康状态，按 health_score 升序排列（高风险门店排前）。支持跨品牌对比。"),
)
async def get_group_cost_heatmap(
    days: int = Query(default=30, ge=7, le=365, description="统计周期（天）"),
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """集团成本热力图

    按 health_score 升序排列，critical → warning → healthy。
    用于总部快速识别高风险门店，优先干预。
    """
    cache_key = f"group_cost_heatmap:{tenant_id}:{days}"
    cached = _cache_get(cache_key)
    if cached:
        return _cached_response(cached)

    engine = CostHealthEngine()
    try:
        reports = await engine.get_group_cost_heatmap(
            tenant_id=tenant_id,
            period_days=days,
            db=db,
        )
    except (ValueError, TypeError) as exc:
        logger.error(
            "get_group_cost_heatmap.failed",
            tenant_id=tenant_id,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "get_group_cost_heatmap.internal_error",
            tenant_id=tenant_id,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="集团热力图生成失败") from exc

    result = {
        "stores": [r.model_dump() for r in reports],
        "summary": {
            "total_stores": len(reports),
            "critical_count": sum(1 for r in reports if r.health_level == "critical"),
            "warning_count": sum(1 for r in reports if r.health_level == "warning"),
            "healthy_count": sum(1 for r in reports if r.health_level == "healthy"),
        },
    }
    _cache_set(cache_key, result)
    return _cached_response(result)


# ── 3. 品牌成本基准 ───────────────────────────────────────────────────────────


@router.get(
    "/brand/{brand_id}/benchmark",
    summary="品牌成本基准",
    description=("返回该品牌所有门店的成本分布统计（中位数/均值/四分位数），作为门店对标的参考线。"),
)
async def get_brand_cost_benchmark(
    brand_id: str,
    days: int = Query(default=30, ge=7, le=365, description="统计周期（天）"),
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """品牌成本基准

    - median_*: 中位数（推荐用于对标，抗异常值）
    - mean_*: 均值
    - p25/p75_ingredient: 食材成本率分布四分位
    - store_count: 纳入计算的门店数
    """
    cache_key = f"brand_benchmark:{tenant_id}:{brand_id}:{days}"
    cached = _cache_get(cache_key)
    if cached:
        return _cached_response(cached)

    engine = CostHealthEngine()
    try:
        benchmark = await engine.get_brand_cost_benchmark(
            brand_id=brand_id,
            tenant_id=tenant_id,
            period_days=days,
            db=db,
        )
    except (ValueError, TypeError) as exc:
        logger.error(
            "get_brand_cost_benchmark.failed",
            brand_id=brand_id,
            tenant_id=tenant_id,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "get_brand_cost_benchmark.internal_error",
            brand_id=brand_id,
            tenant_id=tenant_id,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="品牌基准计算失败") from exc

    result = benchmark.model_dump()
    _cache_set(cache_key, result)
    return _cached_response(result)


# ── 4. 成本异常预警列表 ───────────────────────────────────────────────────────


@router.get(
    "/alerts",
    summary="成本异常预警列表",
    description=(
        "返回该租户所有成本异常门店（任意维度偏差超出品牌均值±15%）。按异常严重程度（health_score 升序）排列。"
    ),
)
async def get_cost_alerts(
    days: int = Query(default=30, ge=7, le=365, description="统计周期（天）"),
    level: Optional[str] = Query(
        default=None,
        description="过滤等级：critical / warning / all（默认）",
    ),
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """成本异常预警列表

    返回所有触发异常标记的门店，字段包含：
    - 具体异常维度（食材/人力/损耗）
    - 与品牌基准的偏差值
    - 健康等级
    """
    cache_key = f"cost_alerts:{tenant_id}:{days}:{level}"
    cached = _cache_get(cache_key)
    if cached:
        return _cached_response(cached)

    engine = CostHealthEngine()
    try:
        all_reports = await engine.get_group_cost_heatmap(
            tenant_id=tenant_id,
            period_days=days,
            db=db,
        )
    except (ValueError, TypeError) as exc:
        logger.error(
            "get_cost_alerts.failed",
            tenant_id=tenant_id,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "get_cost_alerts.internal_error",
            tenant_id=tenant_id,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="成本预警获取失败") from exc

    # 筛选有异常标记的门店
    anomaly_reports = [r for r in all_reports if r.is_ingredient_anomaly or r.is_labor_anomaly or r.is_waste_anomaly]

    # 按等级过滤
    if level == "critical":
        anomaly_reports = [r for r in anomaly_reports if r.health_level == "critical"]
    elif level == "warning":
        anomaly_reports = [r for r in anomaly_reports if r.health_level == "warning"]

    alerts = []
    for r in anomaly_reports:
        anomaly_dimensions = []
        if r.is_ingredient_anomaly:
            anomaly_dimensions.append(
                {
                    "dimension": "ingredient_cost_rate",
                    "label": "食材成本率",
                    "actual": r.ingredient_cost_rate,
                    "benchmark": r.benchmark_ingredient,
                    "deviation": r.ingredient_deviation,
                }
            )
        if r.is_labor_anomaly:
            anomaly_dimensions.append(
                {
                    "dimension": "labor_cost_rate",
                    "label": "人力成本率",
                    "actual": r.labor_cost_rate,
                    "benchmark": r.benchmark_labor,
                    "deviation": r.labor_deviation,
                }
            )
        if r.is_waste_anomaly:
            anomaly_dimensions.append(
                {
                    "dimension": "waste_rate",
                    "label": "损耗率",
                    "actual": r.waste_rate,
                    "benchmark": r.benchmark_waste,
                    "deviation": r.waste_deviation,
                }
            )

        alerts.append(
            {
                "store_id": r.store_id,
                "store_name": r.store_name,
                "brand_id": r.brand_id,
                "health_score": r.health_score,
                "health_level": r.health_level,
                "anomaly_dimensions": anomaly_dimensions,
                "needs_ai_suggestion": r.health_score < 65.0,
            }
        )

    result = {
        "alerts": alerts,
        "total_anomaly_stores": len(alerts),
    }
    _cache_set(cache_key, result)
    return _cached_response(result)


# ── 5. AI 成本优化建议 ────────────────────────────────────────────────────────


@router.get(
    "/store/{store_id}/suggestions",
    summary="AI 成本优化建议",
    description=(
        "当门店 health_score < 65 时，调用 ModelRouter 生成具体的成本降低建议。"
        "健康门店（≥65分）直接返回空，不消耗 AI 配额。"
    ),
)
async def get_cost_suggestions(
    store_id: str,
    days: int = Query(default=30, ge=7, le=365, description="统计周期（天）"),
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """AI 成本优化建议

    触发条件：health_score < 65（warning + critical）。
    输出：200字内的具体成本改进建议，聚焦异常维度。

    healthy 门店：直接返回 {"triggered": false, "suggestion": ""}，不调用 AI。
    """
    cache_key = f"cost_suggestions:{tenant_id}:{store_id}:{days}"
    cached = _cache_get(cache_key)
    if cached:
        return _cached_response(cached)

    engine = CostHealthEngine()
    try:
        report = await engine.calc_store_cost_health(
            store_id=store_id,
            tenant_id=tenant_id,
            period_days=days,
            db=db,
        )
        benchmark = await engine.get_brand_cost_benchmark(
            brand_id=report.brand_id,
            tenant_id=tenant_id,
            period_days=days,
            db=db,
        )
    except (ValueError, TypeError) as exc:
        logger.error(
            "get_cost_suggestions.calc_failed",
            store_id=store_id,
            tenant_id=tenant_id,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "get_cost_suggestions.internal_error",
            store_id=store_id,
            tenant_id=tenant_id,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="成本建议生成失败") from exc

    # 健康门店不触发 AI
    if report.health_score >= 65.0:
        result = {
            "store_id": store_id,
            "health_score": report.health_score,
            "health_level": report.health_level,
            "triggered": False,
            "suggestion": "",
            "reason": "health_score >= 65，成本状态良好，无需AI干预",
        }
        _cache_set(cache_key, result)
        return _cached_response(result)

    # 需要 AI 建议时，从应用状态获取 ModelRouter
    # 实际部署中通过 app.state.model_router 注入
    try:
        from fastapi import Request  # noqa: F401

        # ModelRouter 在 main.py 中挂载到 app.state
        # 此处通过模块导入获取实例
        from tx_agent.src.services.model_router import ModelRouter  # type: ignore[import]

        model_router = ModelRouter()
    except ImportError:
        logger.warning(
            "get_cost_suggestions.model_router_unavailable",
            store_id=store_id,
        )
        model_router = None

    suggestion = ""
    if model_router:
        try:
            suggestion = await engine.generate_cost_optimization_suggestion(
                store_report=report,
                brand_benchmark=benchmark,
                model_router=model_router,
            )
        except (ValueError, RuntimeError) as exc:
            logger.error(
                "get_cost_suggestions.ai_failed",
                store_id=store_id,
                error=str(exc),
                exc_info=True,
            )
            # AI 失败不阻断响应，降级为无建议
            suggestion = ""

    result = {
        "store_id": store_id,
        "store_name": report.store_name,
        "health_score": report.health_score,
        "health_level": report.health_level,
        "triggered": True,
        "suggestion": suggestion,
        "cost_summary": {
            "ingredient_cost_rate": report.ingredient_cost_rate,
            "labor_cost_rate": report.labor_cost_rate,
            "waste_rate": report.waste_rate,
            "anomaly_dimensions": [
                dim
                for dim, is_anomaly in [
                    ("食材成本率", report.is_ingredient_anomaly),
                    ("人力成本率", report.is_labor_anomaly),
                    ("损耗率", report.is_waste_anomaly),
                ]
                if is_anomaly
            ],
        },
    }
    _cache_set(cache_key, result)
    return _cached_response(result)
