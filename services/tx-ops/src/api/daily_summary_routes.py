"""E2 日营业汇总 API 路由

端点:
  POST /api/v1/ops/daily-summary/generate         自动生成日汇总
  GET  /api/v1/ops/daily-summary/{store_id}       查询日汇总
  POST /api/v1/ops/daily-summary/{id}/confirm     确认日汇总（锁定）
  GET  /api/v1/ops/daily-summary/multi-store      多门店汇总对比

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/ops/daily-summary", tags=["ops-daily-summary"])
log = structlog.get_logger(__name__)

# ─── 内存存储（生产替换为 asyncpg）────────────────────────────────────────────
_summaries: Dict[str, Dict[str, Any]] = {}

# 异常折扣阈值（折扣率 > 30%，即 discount/original > 0.30）
_ABNORMAL_DISCOUNT_THRESHOLD = 0.30


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class GenerateSummaryRequest(BaseModel):
    store_id: str = Field(..., description="门店ID")
    summary_date: date = Field(..., description="汇总日期")


class ConfirmSummaryRequest(BaseModel):
    confirmed_by: str = Field(..., description="确认人UUID")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  内部聚合逻辑（模拟 SQL 聚合，生产对接 asyncpg）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _aggregate_orders(
    store_id: str,
    summary_date: date,
    tenant_id: str,
) -> Dict[str, Any]:
    """
    聚合订单数据。
    生产环境替换为 asyncpg SQL:
      SELECT
        COUNT(*) AS total_orders,
        COUNT(*) FILTER (WHERE channel='dine_in') AS dine_in_orders,
        COUNT(*) FILTER (WHERE channel='takeaway') AS takeaway_orders,
        COUNT(*) FILTER (WHERE channel='banquet') AS banquet_orders,
        SUM(original_amount_fen) AS total_revenue_fen,
        SUM(actual_amount_fen) AS actual_revenue_fen,
        SUM(discount_amount_fen) AS total_discount_fen,
        MAX(discount_pct) AS max_discount_pct,
        COUNT(*) FILTER (WHERE discount_pct > 30 AND approved_by IS NULL) AS abnormal_discounts,
        CASE WHEN COUNT(*) > 0
             THEN SUM(actual_amount_fen) / COUNT(*) END AS avg_table_value_fen
      FROM orders
      WHERE store_id = $1
        AND DATE(created_at AT TIME ZONE 'Asia/Shanghai') = $2
        AND tenant_id = current_setting('app.tenant_id')::uuid
        AND is_deleted = false;
    """
    # mock 数据，生产对接真实 orders 表
    return {
        "total_orders": 0,
        "dine_in_orders": 0,
        "takeaway_orders": 0,
        "banquet_orders": 0,
        "total_revenue_fen": 0,
        "actual_revenue_fen": 0,
        "total_discount_fen": 0,
        "avg_table_value_fen": 0,
        "max_discount_pct": None,
        "abnormal_discounts": 0,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/generate", status_code=201)
async def generate_daily_summary(
    body: GenerateSummaryRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """
    E2: 自动生成（或刷新）日营业汇总。
    聚合 orders 表统计当日订单总数/收入/折扣/各渠道分布，
    识别异常折扣（折扣率>30%且未经审批），计算人均消费。
    """
    # 已锁定的不允许重新生成
    key = f"{x_tenant_id}:{body.store_id}:{body.summary_date.isoformat()}"
    existing = _summaries.get(key)
    if existing and existing["status"] == "locked":
        raise HTTPException(status_code=409, detail="日汇总已锁定，无法重新生成")

    aggregated = await _aggregate_orders(body.store_id, body.summary_date, x_tenant_id)

    now = datetime.now(tz=timezone.utc)
    summary_id = existing["id"] if existing else str(uuid.uuid4())
    record: Dict[str, Any] = {
        "id": summary_id,
        "tenant_id": x_tenant_id,
        "store_id": body.store_id,
        "summary_date": body.summary_date.isoformat(),
        **aggregated,
        "status": "draft",
        "confirmed_by": None,
        "confirmed_at": None,
        "created_at": existing["created_at"] if existing else now.isoformat(),
        "updated_at": now.isoformat(),
        "is_deleted": False,
    }
    _summaries[key] = record

    log.info("daily_summary_generated",
             summary_id=summary_id, store_id=body.store_id,
             summary_date=body.summary_date.isoformat(), tenant_id=x_tenant_id,
             total_orders=aggregated["total_orders"],
             actual_revenue_fen=aggregated["actual_revenue_fen"],
             abnormal_discounts=aggregated["abnormal_discounts"])
    return {"ok": True, "data": record}


@router.get("/multi-store")
async def multi_store_summary(
    summary_date: date = Query(..., description="汇总日期"),
    store_ids: Optional[str] = Query(None, description="逗号分隔的门店ID列表，为空则查全部"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """E2: 多门店汇总对比（总部视角）。按实收金额降序排列。"""
    date_str = summary_date.isoformat()
    target_stores = set(store_ids.split(",")) if store_ids else None

    items: List[Dict[str, Any]] = []
    for k, s in _summaries.items():
        if s["tenant_id"] != x_tenant_id:
            continue
        if s["summary_date"] != date_str:
            continue
        if s.get("is_deleted"):
            continue
        if target_stores and s["store_id"] not in target_stores:
            continue
        items.append(s)

    items.sort(key=lambda s: s["actual_revenue_fen"], reverse=True)

    total_revenue = sum(s["actual_revenue_fen"] for s in items)
    total_orders = sum(s["total_orders"] for s in items)
    total_abnormal = sum(s["abnormal_discounts"] for s in items)

    return {
        "ok": True,
        "data": {
            "summary_date": date_str,
            "store_count": len(items),
            "total_revenue_fen": total_revenue,
            "total_orders": total_orders,
            "total_abnormal_discounts": total_abnormal,
            "stores": items,
        },
    }


@router.get("/{store_id}")
async def get_daily_summary(
    store_id: str,
    summary_date: Optional[date] = Query(None, description="汇总日期，默认今日"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """E2: 查询门店日汇总。"""
    target_date = summary_date or date.today()
    key = f"{x_tenant_id}:{store_id}:{target_date.isoformat()}"
    record = _summaries.get(key)
    if not record:
        raise HTTPException(status_code=404, detail="日汇总记录不存在，请先调用 generate 端点")
    return {"ok": True, "data": record}


@router.post("/{summary_id}/confirm")
async def confirm_daily_summary(
    summary_id: str,
    body: ConfirmSummaryRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """E2: 确认日汇总并锁定，锁定后不可重新生成。"""
    record = next(
        (s for s in _summaries.values()
         if s["id"] == summary_id and s["tenant_id"] == x_tenant_id),
        None,
    )
    if not record:
        raise HTTPException(status_code=404, detail="日汇总记录不存在")
    if record["status"] == "locked":
        raise HTTPException(status_code=409, detail="日汇总已锁定")

    now = datetime.now(tz=timezone.utc)
    record.update(
        status="locked",
        confirmed_by=body.confirmed_by,
        confirmed_at=now.isoformat(),
        updated_at=now.isoformat(),
    )
    log.info("daily_summary_confirmed", summary_id=summary_id,
             store_id=record["store_id"], confirmed_by=body.confirmed_by,
             tenant_id=x_tenant_id)
    return {"ok": True, "data": record}
