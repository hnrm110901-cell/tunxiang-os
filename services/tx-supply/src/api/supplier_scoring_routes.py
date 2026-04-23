"""供应商评分 API 路由

端点：
  POST /api/v1/suppliers/{supplier_id}/score     — 手动触发评分
  GET  /api/v1/suppliers/{supplier_id}/scores    — 查询评分历史
  GET  /api/v1/suppliers/ranking                 — 按综合分排名

统一响应格式：{"ok": bool, "data": {}, "error": {}}

# ROUTER REGISTRATION:
# from .api.supplier_scoring_routes import router as supplier_scoring_router
# app.include_router(supplier_scoring_router)
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db as _get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/suppliers", tags=["supplier-scoring"])


# ─────────────────────────────────────────────────────────────────────────────
# 请求 / 响应模型
# ─────────────────────────────────────────────────────────────────────────────


class TriggerScoreRequest(BaseModel):
    """POST /suppliers/{id}/score 请求体"""

    supplier_name: str = Field(description="供应商名称（用于 AI Prompt）")
    period_start: date = Field(description="评分周期开始日期")
    period_end: date = Field(description="评分周期结束日期")
    enable_ai_insight: bool = Field(
        default=True,
        description="是否允许触发 AI 洞察（仍受内部阈值控制）",
    )


class ScoreHistoryItem(BaseModel):
    id: str
    period_start: date
    period_end: date
    composite_score: float
    delivery_rate: Optional[float] = None
    quality_rate: Optional[float] = None
    price_stability: Optional[float] = None
    response_speed: Optional[float] = None
    compliance_rate: Optional[float] = None
    ai_insight: Optional[str] = None
    created_at: Optional[str] = None


class RankingItem(BaseModel):
    supplier_id: str
    supplier_name: str
    composite_score: Optional[float] = None
    tier: Optional[str] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    rank: int


# ─────────────────────────────────────────────────────────────────────────────
# ModelRouter 惰性加载（避免循环导入）
# ─────────────────────────────────────────────────────────────────────────────


def _get_model_router():
    """惰性获取 ModelRouter 实例。若模块不存在则返回 None（优雅降级）。"""
    try:
        from shared.core.model_router import ModelRouter  # type: ignore[import]

        return ModelRouter()
    except ImportError:
        logger.warning(
            "supplier_scoring_routes.model_router_unavailable",
            reason="shared.core.model_router 模块不存在，AI 洞察将被跳过",
        )
        return None


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/suppliers/{supplier_id}/score
# 手动触发评分
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/{supplier_id}/score")
async def trigger_supplier_score(
    supplier_id: str,
    body: TriggerScoreRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """手动触发供应商评分。

    从 purchasing_orders / receiving_orders 聚合五维度数据，
    写入 supplier_score_history，视情况生成 AI 洞察。
    """
    from ..services.supplier_scoring_engine import SupplierScoringEngine

    log = logger.bind(
        tenant_id=x_tenant_id,
        supplier_id=supplier_id,
        period_start=str(body.period_start),
        period_end=str(body.period_end),
    )

    if body.period_end < body.period_start:
        raise HTTPException(
            status_code=400,
            detail="period_end 必须晚于或等于 period_start",
        )

    model_router = _get_model_router() if body.enable_ai_insight else None

    try:
        engine = SupplierScoringEngine()
        result = await engine.calculate_period_score(
            supplier_id=supplier_id,
            supplier_name=body.supplier_name,
            tenant_id=x_tenant_id,
            period_start=body.period_start,
            period_end=body.period_end,
            db=db,
            model_router=model_router,
        )

        log.info(
            "supplier_score_triggered",
            composite_score=result.composite_score,
            tier=result.tier,
        )

        return {
            "ok": True,
            "data": {
                "supplier_id": result.supplier_id,
                "period_start": str(result.period_start),
                "period_end": str(result.period_end),
                "composite_score": result.composite_score,
                "tier": result.tier,
                "tier_label": _tier_label(result.tier),
                "dimensions": result.dimensions.model_dump(),
                "ai_insight": result.ai_insight,
                "history_id": result.history_id,
            },
        }

    except ValueError as exc:
        log.warning("supplier_score_value_error", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (ProgrammingError, OperationalError) as exc:
        log.error("supplier_score_db_error", error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=503,
            detail="数据库错误，请检查 v064 迁移是否已运行",
        ) from exc


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/suppliers/{supplier_id}/scores
# 查询评分历史
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{supplier_id}/scores")
async def get_supplier_score_history(
    supplier_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """查询供应商评分历史，按评分周期倒序排列。"""
    log = logger.bind(tenant_id=x_tenant_id, supplier_id=supplier_id)

    # 设置 RLS 租户上下文
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": x_tenant_id},
    )

    offset = (page - 1) * size

    count_sql = text("""
        SELECT COUNT(*) AS total
        FROM supplier_score_history
        WHERE tenant_id = :tenant_id
          AND supplier_id = :supplier_id::UUID
          AND is_deleted = FALSE
    """)
    list_sql = text("""
        SELECT
            id::TEXT,
            period_start, period_end,
            composite_score,
            delivery_rate, quality_rate, price_stability,
            response_speed, compliance_rate,
            ai_insight,
            created_at::TEXT
        FROM supplier_score_history
        WHERE tenant_id = :tenant_id
          AND supplier_id = :supplier_id::UUID
          AND is_deleted = FALSE
        ORDER BY period_start DESC
        LIMIT :size OFFSET :offset
    """)

    params = {
        "tenant_id": x_tenant_id,
        "supplier_id": supplier_id,
        "size": size,
        "offset": offset,
    }

    try:
        total_row = (await db.execute(count_sql, params)).fetchone()
        total = total_row.total if total_row else 0

        rows = (await db.execute(list_sql, params)).fetchall()
        items = [dict(r._mapping) for r in rows]

        log.info("supplier_scores_fetched", count=len(items), total=total)

        return {
            "ok": True,
            "data": {
                "items": items,
                "total": total,
                "page": page,
                "size": size,
            },
        }

    except (ProgrammingError, OperationalError) as exc:
        log.error("supplier_scores_db_error", error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=503,
            detail="数据库错误，请检查 v064 迁移是否已运行",
        ) from exc


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/suppliers/ranking
# 按综合分排名（取各供应商最新一期评分）
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/ranking")
async def get_supplier_ranking(
    limit: int = Query(20, ge=1, le=100, description="返回前 N 名"),
    tier: Optional[str] = Query(None, description="按分级筛选: premium/qualified/watch/eliminate"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """按综合分排名。

    取每个供应商最近一期的评分，结合 supplier_profiles 获取供应商名称，
    按 composite_score 降序排列。
    """
    log = logger.bind(tenant_id=x_tenant_id)

    # 设置 RLS 租户上下文
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": x_tenant_id},
    )

    # 按每个供应商取最新一期评分
    ranking_sql = text("""
        WITH latest_scores AS (
            SELECT DISTINCT ON (sh.supplier_id)
                sh.supplier_id::TEXT,
                sp.supplier_name,
                sh.composite_score,
                sh.period_start,
                sh.period_end,
                CASE
                    WHEN sh.composite_score >= 85 THEN 'premium'
                    WHEN sh.composite_score >= 70 THEN 'qualified'
                    WHEN sh.composite_score >= 55 THEN 'watch'
                    ELSE 'eliminate'
                END AS tier
            FROM supplier_score_history sh
            JOIN supplier_profiles sp
              ON sp.id = sh.supplier_id
             AND sp.tenant_id = sh.tenant_id
             AND sp.is_deleted = FALSE
            WHERE sh.tenant_id = :tenant_id
              AND sh.is_deleted = FALSE
            ORDER BY sh.supplier_id, sh.period_start DESC
        )
        SELECT *
        FROM latest_scores
        WHERE (:tier IS NULL OR tier = :tier)
        ORDER BY composite_score DESC
        LIMIT :limit
    """)

    try:
        rows = (
            await db.execute(
                ranking_sql,
                {
                    "tenant_id": x_tenant_id,
                    "tier": tier,
                    "limit": limit,
                },
            )
        ).fetchall()

        ranking = []
        for i, r in enumerate(rows, start=1):
            item = dict(r._mapping)
            item["rank"] = i
            item["tier_label"] = _tier_label(item.get("tier", ""))
            ranking.append(item)

        log.info("supplier_ranking_fetched", count=len(ranking))

        return {
            "ok": True,
            "data": {
                "items": ranking,
                "total": len(ranking),
            },
        }

    except (ProgrammingError, OperationalError) as exc:
        log.error("supplier_ranking_db_error", error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=503,
            detail="数据库错误，请检查 v064 迁移是否已运行",
        ) from exc


# ─────────────────────────────────────────────────────────────────────────────
# 内部辅助
# ─────────────────────────────────────────────────────────────────────────────


def _tier_label(tier: str) -> str:
    """将英文分级转换为中文标签。"""
    return {
        "premium": "优质供应商",
        "qualified": "合格",
        "watch": "观察期",
        "eliminate": "淘汰候选",
    }.get(tier, tier)
