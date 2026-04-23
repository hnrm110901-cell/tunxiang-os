"""折扣审计链 API 路由

GET  /api/v1/discount/audit-log           — 审计记录列表（manager/owner）
GET  /api/v1/discount/audit-log/summary   — 按操作员汇总统计
GET  /api/v1/discount/audit-log/high-risk — 高风险折扣记录

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..security.rbac import UserContext, require_role
from ..services.discount_audit_service import DiscountAuditService

router = APIRouter(prefix="/api/v1/discount", tags=["discount-audit"])


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


@router.get("/audit-log")
async def get_audit_log(
    request: Request,
    store_id: Optional[str] = Query(None),
    operator_id: Optional[str] = Query(None),
    action_type: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    min_discount_amount: Optional[Decimal] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(require_role("admin", "tenant_admin", "auditor", "audit_admin")),
):
    """GET /api/v1/discount/audit-log — 折扣审计记录列表（管理员/审计员）"""
    tenant_id = _get_tenant_id(request)
    svc = DiscountAuditService(db, tenant_id)

    try:
        result = await svc.get_audit_log(
            store_id=store_id,
            operator_id=operator_id,
            action_type=action_type,
            date_from=date_from,
            date_to=date_to,
            min_discount_amount=min_discount_amount,
            page=page,
            size=size,
        )
        return _ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database error") from exc


@router.get("/audit-log/summary")
async def get_audit_summary(
    request: Request,
    store_id: Optional[str] = Query(None),
    period: str = Query("today", pattern="^(today|week|month)$"),
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(require_role("admin", "tenant_admin", "auditor", "audit_admin")),
):
    """GET /api/v1/discount/audit-log/summary — 按操作员汇总折扣统计"""
    from datetime import timedelta, timezone

    tenant_id = _get_tenant_id(request)
    svc = DiscountAuditService(db, tenant_id)

    now = datetime.now(timezone.utc)
    if period == "today":
        date_from = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        date_from = now - timedelta(days=7)
    else:
        date_from = now - timedelta(days=30)

    try:
        log_result = await svc.get_audit_log(
            store_id=store_id,
            date_from=date_from,
            size=1000,
        )
        high_risk_result = await svc.get_high_risk_summary(
            store_id=store_id,
            threshold_pct=30,
            date_from=date_from,
        )

        items = log_result.get("items", [])
        total_count = log_result.get("total", 0)
        total_discount = sum(float(i["discount_amount"]) for i in items)
        high_risk_count = sum(op["high_risk_count"] for op in high_risk_result.get("summary", []))

        return _ok(
            {
                "period": period,
                "total_count": total_count,
                "total_discount_amount": round(total_discount, 2),
                "high_risk_count": high_risk_count,
                "by_operator": high_risk_result.get("summary", []),
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database error") from exc


@router.get("/audit-log/high-risk")
async def get_high_risk(
    request: Request,
    store_id: Optional[str] = Query(None),
    threshold_pct: int = Query(30, ge=1, le=100),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(require_role("admin", "tenant_admin", "auditor", "audit_admin")),
):
    """GET /api/v1/discount/audit-log/high-risk — 折扣率超过阈值的记录列表"""
    from decimal import Decimal

    tenant_id = _get_tenant_id(request)
    svc = DiscountAuditService(db, tenant_id)

    try:
        result = await svc.get_audit_log(
            store_id=store_id,
            page=page,
            size=size,
        )
        threshold = Decimal(threshold_pct) / 100
        high_risk_items = [
            item
            for item in result["items"]
            if Decimal(item["original_amount"]) > 0
            and Decimal(item["discount_amount"]) / Decimal(item["original_amount"]) >= threshold
        ]

        summary_result = await svc.get_high_risk_summary(
            store_id=store_id,
            threshold_pct=threshold_pct,
        )

        return _ok(
            {
                "items": high_risk_items,
                "threshold_pct": threshold_pct,
                "operator_summary": summary_result.get("summary", []),
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database error") from exc
