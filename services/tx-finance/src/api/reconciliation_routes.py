"""采购三单对账 API 路由

端点清单：
  POST   /reconciliation/match/{purchase_order_id}  — 单笔三单匹配
  POST   /reconciliation/batch                       — 批量匹配（按条件）
  GET    /reconciliation/variances                   — 差异报告 ?days=30
  PUT    /reconciliation/variances/{id}/resolve      — 手动核销差异
  POST   /reconciliation/auto-approve                — 自动核销小额差异

注册方式（在 tx-finance/src/main.py 中添加）：
  from api.reconciliation_routes import router as reconciliation_router
  app.include_router(reconciliation_router, prefix="/api/v1")
"""
import uuid
from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from services.three_way_match_engine import (
    BatchMatchResult,
    MatchResult,
    MatchStatus,
    PurchaseOrderNotFoundError,
    ThreeWayMatchEngine,
    ThreeWayMatchError,
    VarianceItem,
)
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger()
router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])

# 单例引擎
_engine = ThreeWayMatchEngine()


# ── 依赖注入 ──────────────────────────────────────────────────────────────────


async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    """从 Header 提取 tenant_id，返回带 RLS 的 DB session。"""
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _get_tenant_id(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    """解析 tenant_id，校验格式。"""
    try:
        uuid.UUID(x_tenant_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"X-Tenant-ID 格式错误: {exc}",
        ) from exc
    return x_tenant_id


# ── 请求/响应 Schema ──────────────────────────────────────────────────────────


class BatchMatchRequest(BaseModel):
    """批量匹配请求"""

    supplier_id: Optional[str] = Field(None, description="按供应商 ID 过滤")
    date_from: Optional[date] = Field(None, description="起始日期 YYYY-MM-DD")
    date_to: Optional[date] = Field(None, description="结束日期 YYYY-MM-DD")


class ResolveVarianceRequest(BaseModel):
    """手动核销差异请求"""

    note: str = Field(..., min_length=1, max_length=500, description="核销说明")
    resolved_by: Optional[str] = Field(None, description="操作人 ID（可选）")


class AutoApproveRequest(BaseModel):
    """自动核销请求"""

    max_amount_yuan: float = Field(
        100.0,
        gt=0,
        le=1000,
        description="自动核销上限（元），默认100元",
    )


class MatchResultResponse(BaseModel):
    """单笔匹配结果响应"""

    ok: bool = True
    data: dict


class BatchMatchResponse(BaseModel):
    """批量匹配响应"""

    ok: bool = True
    data: dict


# ── 端点 ──────────────────────────────────────────────────────────────────────


@router.post(
    "/match/{purchase_order_id}",
    summary="单笔三单匹配",
    description="对指定采购订单执行采购单×收货记录×发票三单自动匹配，返回匹配结果和差异明细。",
)
async def match_single_purchase_order(
    purchase_order_id: str,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_get_tenant_id),
):
    """单笔三单匹配 — 传入采购订单 ID，自动匹配收货和发票。"""
    try:
        uuid.UUID(purchase_order_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"purchase_order_id 格式错误: {exc}",
        ) from exc

    try:
        result: MatchResult = await _engine.match_purchase_order(
            purchase_order_id=purchase_order_id,
            tenant_id=tenant_id,
            db=db,
        )
    except PurchaseOrderNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ThreeWayMatchError as exc:
        logger.error(
            "api.match_single.failed",
            purchase_order_id=purchase_order_id,
            tenant_id=tenant_id,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="三单匹配执行失败",
        ) from exc

    return {
        "ok": True,
        "data": {
            "purchase_order_id": result.purchase_order_id,
            "status": result.status.value,
            "status_label": result.status.value,
            "po_amount_yuan": result.po_amount_fen / 100,
            "recv_amount_yuan": result.recv_amount_fen / 100,
            "inv_amount_yuan": result.inv_amount_fen / 100 if result.inv_amount_fen else None,
            "variance_amount_yuan": result.variance_amount_fen / 100,
            "line_variances": result.line_variances,
            "suggestion": result.suggestion,
            "matched_at": result.matched_at.isoformat(),
        },
    }


@router.post(
    "/batch",
    summary="批量三单匹配",
    description="对符合条件的采购订单批量执行三单匹配，返回统计汇总和各单匹配结果。",
)
async def batch_match(
    body: BatchMatchRequest,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_get_tenant_id),
):
    """批量匹配 — 支持按供应商/日期区间过滤。"""
    try:
        batch: BatchMatchResult = await _engine.batch_match(
            tenant_id=tenant_id,
            db=db,
            supplier_id=body.supplier_id,
            date_from=body.date_from,
            date_to=body.date_to,
        )
    except ThreeWayMatchError as exc:
        logger.error(
            "api.batch_match.failed",
            tenant_id=tenant_id,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="批量匹配执行失败",
        ) from exc

    return {
        "ok": True,
        "data": {
            "tenant_id": batch.tenant_id,
            "total": batch.total,
            "matched": batch.matched,
            "variance_count": batch.variance_count,
            "missing_count": batch.missing_count,
            "auto_approved": batch.auto_approved,
            "total_variance_yuan": batch.total_variance_fen / 100,
            "match_rate": round(batch.matched / batch.total, 4) if batch.total > 0 else 0.0,
            "executed_at": batch.executed_at.isoformat(),
            "results": [
                {
                    "purchase_order_id": r.purchase_order_id,
                    "status": r.status.value,
                    "variance_amount_yuan": r.variance_amount_fen / 100,
                }
                for r in batch.results
            ],
        },
    }


@router.get(
    "/variances",
    summary="差异报告",
    description="查询近 N 天内的未核销差异清单，按差异金额降序排列。",
)
async def get_variance_report(
    days: int = Query(30, ge=1, le=365, description="查询天数，默认30天"),
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_get_tenant_id),
):
    """差异报告 — 按供应商/金额排序的差异清单。"""
    try:
        variances: list[VarianceItem] = await _engine.get_variance_report(
            tenant_id=tenant_id,
            db=db,
            period_days=days,
        )
    except Exception as exc:
        logger.error(
            "api.get_variance_report.failed",
            tenant_id=tenant_id,
            days=days,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="差异报告查询失败",
        ) from exc

    return {
        "ok": True,
        "data": {
            "period_days": days,
            "total_variance_items": len(variances),
            "total_variance_yuan": sum(v.variance_amount_fen for v in variances) / 100,
            "items": [
                {
                    "id": v.id,
                    "purchase_order_id": v.purchase_order_id,
                    "supplier_id": v.supplier_id,
                    "status": v.status.value,
                    "variance_amount_yuan": v.variance_amount_fen / 100,
                    "po_amount_yuan": v.po_amount_fen / 100,
                    "recv_amount_yuan": v.recv_amount_fen / 100,
                    "inv_amount_yuan": v.inv_amount_fen / 100 if v.inv_amount_fen else None,
                    "line_variances": v.line_variances,
                    "suggestion": v.suggestion,
                    "created_at": v.created_at.isoformat(),
                }
                for v in variances
            ],
        },
    }


@router.put(
    "/variances/{variance_id}/resolve",
    summary="手动核销差异",
    description="人工审核并核销指定差异记录，需提供核销说明。",
)
async def resolve_variance(
    variance_id: str,
    body: ResolveVarianceRequest,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_get_tenant_id),
):
    """手动核销差异 — 写入审计日志，将状态改为 resolved。"""
    try:
        uuid.UUID(variance_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"variance_id 格式错误: {exc}",
        ) from exc

    try:
        await _engine._approve_variance(
            variance_id=variance_id,
            tenant_id=tenant_id,
            note=body.note,
            db=db,
            resolved_by=body.resolved_by,
        )
        # 手动核销状态改为 resolved（而非 auto_approved）

        from models.three_way_match import ThreeWayMatchRecord
        from sqlalchemy import update

        tid = uuid.UUID(tenant_id)
        vid = uuid.UUID(variance_id)
        await db.execute(
            update(ThreeWayMatchRecord)
            .where(ThreeWayMatchRecord.id == vid, ThreeWayMatchRecord.tenant_id == tid)
            .values(status=MatchStatus.RESOLVED.value)
        )
        await db.commit()
    except ThreeWayMatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.error(
            "api.resolve_variance.failed",
            variance_id=variance_id,
            tenant_id=tenant_id,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="核销操作失败",
        ) from exc

    return {
        "ok": True,
        "data": {
            "variance_id": variance_id,
            "status": MatchStatus.RESOLVED.value,
            "note": body.note,
        },
    }


@router.post(
    "/auto-approve",
    summary="自动核销小额差异",
    description="批量自动核销差异金额在阈值以内的记录，返回处理数量。默认阈值100元。",
)
async def auto_approve_small_variances(
    body: AutoApproveRequest,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_get_tenant_id),
):
    """自动核销 — 差异 ≤ max_amount_yuan 的记录全部核销，写入审计日志。"""
    max_amount_fen = round(body.max_amount_yuan * 100)

    try:
        count = await _engine.auto_approve_small_variances(
            tenant_id=tenant_id,
            db=db,
            max_amount_fen=max_amount_fen,
        )
        await db.commit()
    except Exception as exc:
        logger.error(
            "api.auto_approve.failed",
            tenant_id=tenant_id,
            max_amount_fen=max_amount_fen,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="自动核销执行失败",
        ) from exc

    return {
        "ok": True,
        "data": {
            "approved_count": count,
            "max_amount_yuan": body.max_amount_yuan,
            "message": f"已自动核销 {count} 条小额差异（≤{body.max_amount_yuan:.0f}元）",
        },
    }
