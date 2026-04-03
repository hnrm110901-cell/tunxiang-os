"""自动采购推荐 API 路由

端点：
  GET  /procurement/recommend/{store_id}           - 获取采购建议
  POST /procurement/recommend/{store_id}/apply     - 将建议转为正式采购申请
  GET  /procurement/suppliers/{ingredient_id}/scores - 供应商评分
  GET  /procurement/alerts/{store_id}              - 紧急库存预警

统一响应格式: {"ok": bool, "data": {}, "error": {}}

# ROUTER REGISTRATION:
# from .api.procurement_recommend_routes import router as procurement_recommend_router
# app.include_router(procurement_recommend_router, prefix="/api/v1/procurement")
"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel

from shared.ontology.src.database import get_db as _get_db

router = APIRouter(tags=["procurement-recommend"])


# ─── 请求/响应模型 ───


class ApplyRecommendRequest(BaseModel):
    recommendation_ids: List[str]
    requester_id: str = "auto_procurement_agent"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /procurement/recommend/{store_id}
#  获取门店采购建议列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/recommend/{store_id}")
async def get_procurement_recommendations(
    store_id: str,
    reorder_cycle_days: int = Query(2, ge=1, le=30, description="采购周期（天）"),
    forecast_days: int = Query(7, ge=1, le=90, description="预测天数"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db=Depends(_get_db),
):
    """获取门店采购建议

    基于近期销量预测 + 当前库存 + 安全库存策略，
    生成各原料的采购建议，按紧急程度排序（urgent优先）。

    建议单状态为 draft，需人工调用 /apply 转为正式申购。
    """
    from ..services.auto_procurement import AutoProcurementService

    svc = AutoProcurementService()
    recommendations = await svc.generate_recommendations(
        store_id=store_id,
        tenant_id=x_tenant_id,
        db=db,
        reorder_cycle_days=reorder_cycle_days,
        forecast_days=forecast_days,
    )

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "total": len(recommendations),
            "urgent_count": sum(1 for r in recommendations if r.is_urgent),
            "recommendations": [r.model_dump() for r in recommendations],
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /procurement/recommend/{store_id}/apply
#  将建议转为正式采购申请（需人工确认触发）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/recommend/{store_id}/apply")
async def apply_recommendations(
    store_id: str,
    body: ApplyRecommendRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db=Depends(_get_db),
):
    """将采购建议转为正式申购单

    由人工确认后触发，调用现有申购流程（创建 draft 申购单，
    后续走正常审批流程）。

    Args:
        recommendation_ids: 要采纳的建议ID列表
        requester_id: 操作人ID
    """
    from ..services.auto_procurement import AutoProcurementService

    if not body.recommendation_ids:
        raise HTTPException(status_code=400, detail="recommendation_ids 不可为空")

    # 重新生成建议单（通过store_id + tenant_id确保数据新鲜度）
    svc = AutoProcurementService()
    all_recommendations = await svc.generate_recommendations(
        store_id=store_id,
        tenant_id=x_tenant_id,
        db=db,
    )

    # 按ID过滤用户选择的建议
    selected_ids = set(body.recommendation_ids)
    selected = [r for r in all_recommendations if r.recommendation_id in selected_ids]

    if not selected:
        raise HTTPException(
            status_code=404,
            detail="未找到匹配的采购建议，建议可能已过期，请重新获取",
        )

    try:
        result = await svc.create_requisition_from_recommendations(
            recommendations=selected,
            store_id=store_id,
            tenant_id=x_tenant_id,
            db=db,
            requester_id=body.requester_id,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /procurement/suppliers/{ingredient_id}/scores
#  供应商评分查询
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/suppliers/{ingredient_id}/scores")
async def get_supplier_scores(
    ingredient_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db=Depends(_get_db),
):
    """查询该原料的所有供应商评分

    返回各供应商的历史准期率、质量合格率和综合评分，
    用于采购决策参考。

    评分公式：准期率×0.5 + 质量合格率×0.3 + 价格竞争力×0.2
    """
    from sqlalchemy import text

    from ..services.auto_procurement import AutoProcurementService

    svc = AutoProcurementService()

    # 查询该原料的所有历史供应商
    try:
        sql = text("""
            SELECT DISTINCT supplier_id, supplier_name
            FROM receiving_records
            WHERE ingredient_id = :ingredient_id
              AND tenant_id = :tenant_id
              AND is_deleted = FALSE
        """)
        result = await db.execute(sql, {
            "ingredient_id": ingredient_id,
            "tenant_id": x_tenant_id,
        })
        suppliers = result.fetchall()
    except Exception:
        suppliers = []

    scores = []
    for row in suppliers:
        supplier_id = str(row.supplier_id)
        score_data = await svc.get_supplier_score(
            supplier_id=supplier_id,
            ingredient_id=ingredient_id,
            tenant_id=x_tenant_id,
            db=db,
        )
        composite_score = svc.calc_supplier_score(
            on_time_rate=score_data["on_time_rate"],
            quality_rate=score_data["quality_rate"],
            price_score=score_data["price_score"],
        )
        scores.append({
            "supplier_id": supplier_id,
            "supplier_name": getattr(row, "supplier_name", ""),
            "on_time_rate": round(score_data["on_time_rate"], 3),
            "quality_rate": round(score_data["quality_rate"], 3),
            "price_score": round(score_data["price_score"], 3),
            "composite_score": round(composite_score, 3),
            "total_deliveries": score_data["total_deliveries"],
        })

    # 按综合评分降序
    scores.sort(key=lambda s: s["composite_score"], reverse=True)

    return {
        "ok": True,
        "data": {
            "ingredient_id": ingredient_id,
            "supplier_count": len(scores),
            "scores": scores,
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /procurement/alerts/{store_id}
#  紧急库存预警（库存低于3天用量）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/alerts/{store_id}")
async def get_procurement_alerts(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db=Depends(_get_db),
):
    """获取紧急采购预警

    筛选库存低于3天用量的原料，标记为urgent，
    供采购负责人优先处理。

    Returns:
        {
          "store_id": str,
          "urgent_count": int,
          "alerts": [
            {
              "ingredient_id": str,
              "ingredient_name": str,
              "current_qty": float,
              "daily_consumption": float,
              "days_remaining": float,
              "recommended_qty": float,
              "supplier_name": str | None,
            }
          ]
        }
    """
    from ..services.auto_procurement import AutoProcurementService

    svc = AutoProcurementService()
    all_recommendations = await svc.generate_recommendations(
        store_id=store_id,
        tenant_id=x_tenant_id,
        db=db,
    )

    urgent_alerts = [
        {
            "ingredient_id": r.ingredient_id,
            "ingredient_name": r.ingredient_name,
            "current_qty": r.current_qty,
            "unit": r.unit,
            "daily_consumption": r.daily_consumption,
            "days_remaining": r.days_remaining,
            "recommended_qty": r.recommended_qty,
            "estimated_cost_fen": r.estimated_cost_fen,
            "supplier_name": r.supplier_name,
            "recommendation_id": r.recommendation_id,
        }
        for r in all_recommendations
        if r.is_urgent
    ]

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "urgent_count": len(urgent_alerts),
            "alerts": urgent_alerts,
        },
    }
