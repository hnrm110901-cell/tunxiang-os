"""价格台账 API（v366）

8 个端点：
  GET  /api/v1/supply/price-ledger
  GET  /api/v1/supply/price-ledger/{ingredient_id}/trend
  GET  /api/v1/supply/price-ledger/{ingredient_id}/compare
  POST /api/v1/supply/price-alert-rules
  GET  /api/v1/supply/price-alert-rules
  GET  /api/v1/supply/price-alerts/active
  POST /api/v1/supply/price-alerts/{alert_id}/ack
  GET  /api/v1/supply/price-ledger/export

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有端点必须读取 X-Tenant-ID header，并由 service 层 SET LOCAL app.tenant_id。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db as _get_db

from ..models.price_ledger import (
    AlertAckIn,
    AlertRuleIn,
    PriceRecordIn,
)
from ..services.price_ledger_service import (
    acknowledge_alert,
    compare_suppliers,
    compute_trend,
    create_alert_rule,
    export_ledger_csv,
    list_active_alerts,
    list_alert_rules,
    query_ledger,
    record_price,
)

router = APIRouter(prefix="/api/v1/supply", tags=["price-ledger"])


# ──────────────────────────────────────────────────────────────────────
# 1. GET /price-ledger — 台账列表
# ──────────────────────────────────────────────────────────────────────


@router.get("/price-ledger")
async def get_price_ledger(
    ingredient_id: Optional[str] = Query(None),
    supplier_id: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    result = await query_ledger(
        tenant_id=x_tenant_id,
        db=db,
        ingredient_id=ingredient_id,
        supplier_id=supplier_id,
        date_from=date_from,
        date_to=date_to,
        page=page,
        size=size,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return {
        "ok": True,
        "data": {
            "items": result["items"],
            "total": result["total"],
            "page": result["page"],
            "size": result["size"],
        },
    }


# ──────────────────────────────────────────────────────────────────────
# 1b. POST /price-ledger — 手工录入价格快照（兼容入口）
# ──────────────────────────────────────────────────────────────────────


@router.post("/price-ledger")
async def post_price_record(
    body: PriceRecordIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    result = await record_price(
        tenant_id=x_tenant_id,
        ingredient_id=body.ingredient_id,
        supplier_id=body.supplier_id,
        unit_price_fen=body.unit_price_fen,
        db=db,
        quantity_unit=body.quantity_unit,
        captured_at=body.captured_at,
        source_doc_type=body.source_doc_type or "manual",
        source_doc_id=body.source_doc_id,
        source_doc_no=body.source_doc_no,
        store_id=body.store_id,
        notes=body.notes,
        created_by=body.created_by,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return {
        "ok": True,
        "data": {
            "record": result["data"],
            "duplicated": result.get("duplicated", False),
            "alerts": result.get("alerts", []),
        },
    }


# ──────────────────────────────────────────────────────────────────────
# 2. GET /price-ledger/{ingredient_id}/trend
# ──────────────────────────────────────────────────────────────────────


@router.get("/price-ledger/{ingredient_id}/trend")
async def get_trend(
    ingredient_id: str,
    bucket: str = Query("week", pattern="^(week|month)$"),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    supplier_id: Optional[str] = Query(None),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    result = await compute_trend(
        tenant_id=x_tenant_id,
        ingredient_id=ingredient_id,
        db=db,
        bucket=bucket,
        date_from=date_from,
        date_to=date_to,
        supplier_id=supplier_id,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return {"ok": True, "data": result}


# ──────────────────────────────────────────────────────────────────────
# 3. GET /price-ledger/{ingredient_id}/compare
# ──────────────────────────────────────────────────────────────────────


@router.get("/price-ledger/{ingredient_id}/compare")
async def get_compare(
    ingredient_id: str,
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    result = await compare_suppliers(
        tenant_id=x_tenant_id,
        ingredient_id=ingredient_id,
        db=db,
        date_from=date_from,
        date_to=date_to,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return {"ok": True, "data": result}


# ──────────────────────────────────────────────────────────────────────
# 4. POST /price-alert-rules
# ──────────────────────────────────────────────────────────────────────


@router.post("/price-alert-rules")
async def create_rule(
    body: AlertRuleIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    result = await create_alert_rule(
        tenant_id=x_tenant_id,
        rule_type=body.rule_type,
        threshold_value=body.threshold_value,
        db=db,
        ingredient_id=body.ingredient_id,
        baseline_window_days=body.baseline_window_days,
        enabled=body.enabled,
        created_by=body.created_by,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return {"ok": True, "data": result["data"]}


# ──────────────────────────────────────────────────────────────────────
# 5. GET /price-alert-rules
# ──────────────────────────────────────────────────────────────────────


@router.get("/price-alert-rules")
async def list_rules(
    enabled_only: bool = Query(False),
    ingredient_id: Optional[str] = Query(None),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    result = await list_alert_rules(
        tenant_id=x_tenant_id,
        db=db,
        enabled_only=enabled_only,
        ingredient_id=ingredient_id,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return {"ok": True, "data": {"items": result["items"], "total": result["total"]}}


# ──────────────────────────────────────────────────────────────────────
# 6. GET /price-alerts/active
# ──────────────────────────────────────────────────────────────────────


@router.get("/price-alerts/active")
async def get_active_alerts(
    severity: Optional[str] = Query(None),
    ingredient_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    result = await list_active_alerts(
        tenant_id=x_tenant_id,
        db=db,
        severity=severity,
        ingredient_id=ingredient_id,
        limit=limit,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return {"ok": True, "data": {"items": result["items"], "total": result["total"]}}


# ──────────────────────────────────────────────────────────────────────
# 7. POST /price-alerts/{alert_id}/ack
# ──────────────────────────────────────────────────────────────────────


@router.post("/price-alerts/{alert_id}/ack")
async def ack_alert(
    alert_id: str,
    body: AlertAckIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    result = await acknowledge_alert(
        tenant_id=x_tenant_id,
        alert_id=alert_id,
        acked_by=body.acked_by,
        db=db,
        ack_comment=body.ack_comment,
        new_status=body.new_status,
    )
    if not result.get("ok"):
        # 区分 not found 与其他
        msg = result.get("error", "")
        if "not found" in str(msg).lower():
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "data": result["data"]}


# ──────────────────────────────────────────────────────────────────────
# 8. GET /price-ledger/export — CSV 导出
# ──────────────────────────────────────────────────────────────────────


@router.get("/price-ledger/export")
async def export_csv(
    ingredient_id: Optional[str] = Query(None),
    supplier_id: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> PlainTextResponse:
    csv_text = await export_ledger_csv(
        tenant_id=x_tenant_id,
        db=db,
        ingredient_id=ingredient_id,
        supplier_id=supplier_id,
        date_from=date_from,
        date_to=date_to,
    )
    return PlainTextResponse(
        csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=price_ledger.csv"},
    )
