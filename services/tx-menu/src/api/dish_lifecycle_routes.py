"""菜品生命周期AI — API路由

端点列表：
    GET  /dish-lifecycle/health-scores          菜品健康评分列表（按门店）
    GET  /dish-lifecycle/health-scores/{dish_id} 单品评分明细
    GET  /dish-lifecycle/sellout-warnings/{store_id} 沽清预警
    GET  /dish-lifecycle/removal-suggestions/{store_id} 下架建议
    POST /dish-lifecycle/run-checks             触发每日检查（管理员/定时任务）
    GET  /dish-lifecycle/new-dish-report/{dish_id} 新品评测报告

# ROUTER REGISTRATION:
# from .api.dish_lifecycle_routes import router as dish_lifecycle_router
# app.include_router(dish_lifecycle_router, prefix="/api/v1/dish-lifecycle")
"""
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.dish_health_score import DishHealthScoreEngine, ScoreWeights
from ..services.dish_lifecycle import DishLifecycleService

router = APIRouter(tags=["dish-lifecycle"])


# ─── 依赖注入占位 ─────────────────────────────────────────────────────────────


async def get_db() -> AsyncSession:  # type: ignore[override]
    """数据库会话依赖 — 由 main.py 中 app.dependency_overrides 注入"""
    raise NotImplementedError("DB session dependency not configured")


# ─── 请求模型 ─────────────────────────────────────────────────────────────────


class RunChecksReq(BaseModel):
    tenant_id: str


# ─── 端点 ─────────────────────────────────────────────────────────────────────


@router.get("/health-scores")
async def list_health_scores(
    store_id: str = Query(..., description="门店ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取门店所有菜品健康评分列表（按综合评分升序，最差在前）

    Returns:
        scores: 健康评分列表
        count: 菜品总数
        low_health_count: 低健康分菜品数（< 40分）
    """
    engine = DishHealthScoreEngine()
    scores = await engine.score_all_dishes(store_id=store_id, tenant_id=x_tenant_id, db=db)
    low_health_count = sum(1 for s in scores if s.total_score < 40.0)
    return {
        "ok": True,
        "data": {
            "scores": [s.to_dict() for s in scores],
            "count": len(scores),
            "low_health_count": low_health_count,
        },
    }


@router.get("/health-scores/{dish_id}")
async def get_health_score(
    dish_id: str,
    store_id: str = Query(..., description="门店ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取单道菜健康评分明细（含三维子分）

    Returns:
        score: 评分详情（含 margin_score / sales_rank_score / review_score）
    """
    engine = DishHealthScoreEngine()
    score = await engine.score_dish(
        dish_id=dish_id,
        store_id=store_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    if score is None:
        return {"ok": False, "error": {"code": "DISH_NOT_FOUND", "message": "菜品不存在或无数据"}}
    return {"ok": True, "data": {"score": score.to_dict()}}


@router.get("/sellout-warnings/{store_id}")
async def get_sellout_warnings(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取门店沽清预警列表（库存低于2天用量）

    Returns:
        warnings: 预警列表（含 days_remaining / warning_level）
    """
    svc = DishLifecycleService()
    warnings = await svc.check_sellout_warnings(
        store_id=store_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {
        "ok": True,
        "data": {
            "warnings": [w.to_dict() for w in warnings],
            "count": len(warnings),
        },
    }


@router.get("/removal-suggestions/{store_id}")
async def get_removal_suggestions(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取下架建议列表（含理由和数据支撑）

    触发条件：
    - 健康分 < 40 持续30天
    - 评测期内零销量
    - 毛利率持续低于10%

    Returns:
        suggestions: 建议列表（含 reason / evidence / priority）
    """
    svc = DishLifecycleService()
    suggestions = await svc.generate_removal_suggestions(
        store_id=store_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {
        "ok": True,
        "data": {
            "suggestions": [s.to_dict() for s in suggestions],
            "count": len(suggestions),
        },
    }


@router.post("/run-checks")
async def run_daily_checks(
    req: RunChecksReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """触发每日生命周期检查（管理员 / 定时任务专用）

    执行：新品7天评测 + 健康分低于阈值菜品标记。
    沽清预警和下架建议请分别调用对应端点（需要 store_id）。

    Returns:
        run_at: 执行时间
        eval_reports: 评测报告摘要
        low_health_dishes: 本次被标记为低健康状态的菜品ID列表
    """
    # X-Tenant-ID header 与 body 中的 tenant_id 必须一致（双重校验）
    if req.tenant_id != x_tenant_id:
        return {
            "ok": False,
            "error": {
                "code": "TENANT_MISMATCH",
                "message": "X-Tenant-ID 与请求体 tenant_id 不匹配",
            },
        }

    svc = DishLifecycleService()
    result = await svc.run_daily_checks(tenant_id=x_tenant_id, db=db)
    return {"ok": True, "data": result}


@router.get("/new-dish-report/{dish_id}")
async def get_new_dish_report(
    dish_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取新品评测报告

    返回指定菜品的7天评测结果，含销量、毛利率、评测结论和建议。

    Returns:
        report: 评测报告（verdict / suggestions / eval_sales / margin_rate）
    """
    svc = DishLifecycleService()
    # 触发全租户评测并过滤出指定菜品
    reports = await svc.check_new_dish_evaluations(tenant_id=x_tenant_id, db=db)
    matching = [r.to_dict() for r in reports if r.dish_id == dish_id]

    if not matching:
        return {
            "ok": False,
            "error": {
                "code": "REPORT_NOT_FOUND",
                "message": "该菜品暂无评测报告（可能未到评测期或已过期）",
            },
        }
    return {"ok": True, "data": {"report": matching[0]}}
