"""Sprint D3a — RFM 触达 API 端点

  POST /api/v1/member/rfm/outreach/plan
    入参：{segment_filter: ["S4","S5"], limit: 200, target_store_id: "..."}
    出参：OutreachPlan（campaign_id + candidates + 预估 ROI），写入
          rfm_outreach_campaigns 表 status='plan_generated'

  POST /api/v1/member/rfm/outreach/execute/{campaign_id}
    店长确认后执行：更新 status='sending' → 调 tx-growth 渠道发送 →
    成功后置 status='sent'。实际渠道调用由独立 worker 异步消费此状态。

注：本 PR 只构建规划层（决策+文案），不直接触达。归因和真实触达通过
独立 worker（`services/tx-member/src/workers/rfm_outreach_worker.py` 后续 PR）
消费 status 变化驱动。
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.rfm_outreach_service import (
    CustomerSnapshot,
    RFMOutreachService,
    save_plan_to_db,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/member/rfm/outreach", tags=["member-rfm-outreach"])


# ── 请求/响应模型 ─────────────────────────────────────────────────

class OutreachPlanRequest(BaseModel):
    """生成 RFM 触达规划"""
    segment_filter: list[str] = Field(
        default_factory=lambda: ["S4", "S5"],
        description="仅保留这些分层（默认 S4/S5 沉睡客户）",
    )
    limit: int = Field(default=200, ge=1, le=2000, description="最多输出候选数")
    store_id: Optional[str] = Field(default=None, description="筛选门店（UUID）")
    campaign_name: Optional[str] = Field(default=None, max_length=200)
    auto_confirm: bool = Field(
        default=False,
        description="True 时直接 status=human_confirmed（自动化需 x-operator-id）",
    )


class OutreachCandidateResponse(BaseModel):
    customer_id: str
    segment: str
    cf_score: float
    top_items: list[str]
    message: Optional[str]
    estimated_uplift_fen: int


class OutreachPlanResponse(BaseModel):
    campaign_id: str
    status: str
    segment: str
    target_count: int
    estimated_revenue_fen: int
    model_id: str
    candidates: list[OutreachCandidateResponse]


# ── 端点 ─────────────────────────────────────────────────────────

@router.post("/plan", response_model=dict)
async def generate_outreach_plan(
    req: OutreachPlanRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: Optional[str] = Header(None, alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """生成 RFM 触达规划。

    算法：
      1. 从 DB 拉取客户 RFM 快照（候选池 + 活跃参考人群）
      2. CF + Haiku 生成每位候选的 top_items 和文案
      3. 写入 rfm_outreach_campaigns（status='plan_generated'），返规划结果
    """
    _parse_uuid(x_tenant_id, "X-Tenant-ID")

    # 1. 拉取候选客户（不筛 segment，service 层按 segment_filter 处理）
    try:
        candidates = await _fetch_customer_snapshots(
            db, tenant_id=x_tenant_id, store_id=req.store_id, limit=req.limit,
            recency_min_days=30,  # 至少 30 天没来（节省无意义 CF 计算）
        )
        active_peers = await _fetch_customer_snapshots(
            db, tenant_id=x_tenant_id, store_id=req.store_id, limit=500,
            recency_min_days=None, recency_max_days=14,  # 14 天内到店的活跃人
        )
    except SQLAlchemyError as exc:
        logger.exception("rfm_outreach_db_fetch_failed")
        raise HTTPException(status_code=500, detail=f"客户数据读取失败: {exc}") from exc

    if not candidates:
        return {
            "ok": True,
            "data": {
                "campaign_id": None,
                "status": "no_candidates",
                "target_count": 0,
                "message": "当前筛选条件下无沉睡客户候选",
            },
        }

    # 2. 构建规划
    service = RFMOutreachService()  # 注入 ModelRouter 在生产 wire
    plan = await service.build_plan(
        tenant_id=x_tenant_id,
        store_id=req.store_id,
        candidates=candidates,
        active_peers=active_peers,
        target_segments=req.segment_filter,
        campaign_name=req.campaign_name,
    )

    if plan.target_count == 0:
        return {
            "ok": True,
            "data": {
                "campaign_id": None,
                "status": "no_candidates",
                "target_count": 0,
                "message": f"segment_filter={req.segment_filter} 下无候选",
            },
        }

    # 3. 写 DB（视 auto_confirm 决定是否直接置 human_confirmed）
    confirmed_by = x_operator_id if (req.auto_confirm and x_operator_id) else None
    try:
        saved = await save_plan_to_db(db, plan, confirmed_by=confirmed_by)
    except SQLAlchemyError as exc:
        logger.exception("rfm_outreach_save_failed")
        raise HTTPException(status_code=500, detail=f"规划持久化失败: {exc}") from exc

    return {
        "ok": True,
        "data": {
            "campaign_id": saved["campaign_id"],
            "status": saved["status"],
            "segment": plan.segment,
            "target_count": plan.target_count,
            "estimated_revenue_fen": plan.estimated_revenue_fen,
            "model_id": plan.model_id,
            "candidates": [
                {
                    "customer_id": c.customer_id,
                    "segment": c.segment,
                    "cf_score": c.cf_score,
                    "top_items": c.top_items,
                    "message": c.outreach_message,
                    "estimated_uplift_fen": c.estimated_uplift_fen,
                }
                for c in plan.candidates[:50]  # 预览只返前 50
            ],
        },
    }


@router.post("/execute/{campaign_id}", response_model=dict)
async def execute_outreach_campaign(
    campaign_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: str = Header(..., alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """确认并触发触达发送（状态机 human_confirmed → sending）。

    实际渠道调用由 `rfm_outreach_worker` 异步消费 status='sending' 驱动。
    本端点只完成状态迁移和确认人审计。
    """
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(campaign_id, "campaign_id")
    _parse_uuid(x_operator_id, "X-Operator-ID")

    try:
        result = await db.execute(text("""
            UPDATE rfm_outreach_campaigns
            SET status = 'sending',
                confirmed_by = CAST(:op AS uuid),
                confirmed_at = COALESCE(confirmed_at, NOW()),
                updated_at = NOW()
            WHERE id = CAST(:cid AS uuid)
              AND tenant_id = CAST(:tid AS uuid)
              AND status IN ('plan_generated', 'human_confirmed')
              AND is_deleted = false
            RETURNING id, status, target_count
        """), {"cid": campaign_id, "tid": x_tenant_id, "op": x_operator_id})
        row = result.mappings().first()
        await db.commit()
    except SQLAlchemyError as exc:
        logger.exception("rfm_outreach_execute_failed")
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"状态迁移失败: {exc}") from exc

    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"campaign_id={campaign_id} 不存在或状态不允许执行",
        )

    return {
        "ok": True,
        "data": {
            "campaign_id": str(row["id"]),
            "status": row["status"],
            "target_count": row["target_count"],
            "message": "已切换到 sending 状态，worker 将异步触达",
        },
    }


# ── 辅助 ─────────────────────────────────────────────────────────

def _parse_uuid(value: str, field_name: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=400, detail=f"{field_name} 非法 UUID: {value!r}"
        ) from exc


async def _fetch_customer_snapshots(
    db: AsyncSession,
    *,
    tenant_id: str,
    store_id: Optional[str],
    limit: int,
    recency_min_days: Optional[int] = None,
    recency_max_days: Optional[int] = None,
) -> list[CustomerSnapshot]:
    """从 DB 读客户的 RFM + 最常点菜品快照。

    优先读 mv_member_clv（已有 v148 物化视图），缺数据时降级到 customers + orders 实时聚合。
    """
    params: dict[str, Any] = {"tenant_id": tenant_id, "limit": limit}
    store_filter = ""
    if store_id:
        store_filter = "AND c.store_id = CAST(:store_id AS uuid)"
        params["store_id"] = store_id

    recency_conditions: list[str] = []
    if recency_min_days is not None:
        recency_conditions.append("recency_days >= :r_min")
        params["r_min"] = recency_min_days
    if recency_max_days is not None:
        recency_conditions.append("recency_days <= :r_max")
        params["r_max"] = recency_max_days
    recency_filter = (" AND " + " AND ".join(recency_conditions)) if recency_conditions else ""

    # 简化版：直接从 customers + orders 实时聚合。生产应读 mv_member_clv。
    try:
        result = await db.execute(text(f"""
            WITH snap AS (
                SELECT
                    c.id::text AS customer_id,
                    c.name,
                    CASE
                        WHEN MAX(o.paid_at) IS NULL THEN 999
                        ELSE EXTRACT(DAY FROM NOW() - MAX(o.paid_at))::int
                    END AS recency_days,
                    COUNT(DISTINCT o.id) AS frequency,
                    COALESCE(SUM(o.total_fen), 0)::bigint AS monetary_fen,
                    ARRAY_AGG(DISTINCT oi.dish_id::text)
                        FILTER (WHERE oi.dish_id IS NOT NULL) AS preferred_items
                FROM customers c
                LEFT JOIN orders o
                    ON o.customer_id = c.id
                    AND o.tenant_id = c.tenant_id
                    AND o.status = 'paid'
                    AND o.paid_at >= NOW() - INTERVAL '12 months'
                LEFT JOIN order_items oi ON oi.order_id = o.id
                WHERE c.tenant_id = CAST(:tenant_id AS uuid)
                  AND c.is_deleted = false
                  {store_filter}
                GROUP BY c.id, c.name
            )
            SELECT *
            FROM snap
            WHERE 1=1 {recency_filter}
            ORDER BY recency_days DESC
            LIMIT :limit
        """), params)
        rows = [dict(r) for r in result.mappings()]
    except SQLAlchemyError:
        logger.exception("rfm_snapshot_query_failed")
        return []

    snapshots: list[CustomerSnapshot] = []
    for row in rows:
        items = row.get("preferred_items") or []
        snapshots.append(CustomerSnapshot(
            customer_id=row["customer_id"],
            name=row.get("name"),
            recency_days=int(row["recency_days"]),
            frequency=int(row["frequency"] or 0),
            monetary_fen=int(row["monetary_fen"] or 0),
            preferred_items=[str(i) for i in items if i],
        ))
    return snapshots
