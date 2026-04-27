"""E2 日营业汇总 API 路由 — 真实DB + RLS

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
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/ops/daily-summary", tags=["ops-daily-summary"])
log = structlog.get_logger(__name__)

# 异常折扣阈值（折扣率 > 30%）
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
#  内部辅助
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


async def _aggregate_orders(
    store_id: str,
    summary_date: date,
    tenant_id: str,
    db: AsyncSession,
) -> Dict[str, Any]:
    """从 orders 表聚合当日数据。"""
    try:
        result = await db.execute(
            text(
                """
                SELECT
                  COUNT(*) AS total_orders,
                  COUNT(*) FILTER (WHERE channel = 'dine_in') AS dine_in_orders,
                  COUNT(*) FILTER (WHERE channel = 'takeaway') AS takeaway_orders,
                  COUNT(*) FILTER (WHERE channel = 'banquet') AS banquet_orders,
                  COALESCE(SUM(original_amount_fen), 0) AS total_revenue_fen,
                  COALESCE(SUM(actual_amount_fen), 0) AS actual_revenue_fen,
                  COALESCE(SUM(discount_amount_fen), 0) AS total_discount_fen,
                  MAX(discount_pct) AS max_discount_pct,
                  COUNT(*) FILTER (
                    WHERE discount_pct > :threshold AND approved_by IS NULL
                  ) AS abnormal_discounts,
                  CASE WHEN COUNT(*) > 0
                       THEN COALESCE(SUM(actual_amount_fen), 0) / COUNT(*) END AS avg_table_value_fen
                FROM orders
                WHERE store_id = :store_id
                  AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  AND DATE(created_at AT TIME ZONE 'Asia/Shanghai') = :summary_date
                  AND is_deleted = false
                """
            ),
            {
                "store_id": store_id,
                "summary_date": summary_date,
                "threshold": _ABNORMAL_DISCOUNT_THRESHOLD * 100,
            },
        )
        row = result.fetchone()
        if row:
            return {
                "total_orders": row.total_orders or 0,
                "dine_in_orders": row.dine_in_orders or 0,
                "takeaway_orders": row.takeaway_orders or 0,
                "banquet_orders": row.banquet_orders or 0,
                "total_revenue_fen": row.total_revenue_fen or 0,
                "actual_revenue_fen": row.actual_revenue_fen or 0,
                "total_discount_fen": row.total_discount_fen or 0,
                "avg_table_value_fen": row.avg_table_value_fen or 0,
                "max_discount_pct": row.max_discount_pct,
                "abnormal_discounts": row.abnormal_discounts or 0,
            }
    except SQLAlchemyError as exc:
        log.error(
            "daily_summary_aggregate_error", exc_info=True, error=str(exc), store_id=store_id, tenant_id=tenant_id
        )

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


def _serialize_row(row_mapping: dict) -> dict:
    result = {}
    for key, val in row_mapping.items():
        if val is None:
            result[key] = None
        elif hasattr(val, "isoformat"):
            result[key] = val.isoformat()
        elif hasattr(val, "hex"):
            result[key] = str(val)
        else:
            result[key] = val
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/generate", status_code=201)
async def generate_daily_summary(
    body: GenerateSummaryRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    E2: 自动生成（或刷新）日营业汇总。
    聚合 orders 表统计当日订单总数/收入/折扣/各渠道分布，
    识别异常折扣（折扣率>30%且未经审批），计算人均消费。
    """
    await _set_rls(db, x_tenant_id)

    try:
        # 检查是否已锁定
        existing_result = await db.execute(
            text(
                """
                SELECT id, status, created_at FROM daily_summaries
                WHERE store_id = :store_id
                  AND summary_date = :summary_date
                  AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  AND is_deleted = false
                LIMIT 1
                """
            ),
            {"store_id": body.store_id, "summary_date": body.summary_date},
        )
        existing = existing_result.fetchone()

        if existing and existing.status == "locked":
            raise HTTPException(status_code=409, detail="日汇总已锁定，无法重新生成")

        aggregated = await _aggregate_orders(body.store_id, body.summary_date, x_tenant_id, db)

        now = datetime.now(tz=timezone.utc)
        if existing:
            summary_id = str(existing.id)
            await db.execute(
                text(
                    """
                    UPDATE daily_summaries SET
                      total_orders = :total_orders,
                      dine_in_orders = :dine_in_orders,
                      takeaway_orders = :takeaway_orders,
                      banquet_orders = :banquet_orders,
                      total_revenue_fen = :total_revenue_fen,
                      actual_revenue_fen = :actual_revenue_fen,
                      total_discount_fen = :total_discount_fen,
                      avg_table_value_fen = :avg_table_value_fen,
                      max_discount_pct = :max_discount_pct,
                      abnormal_discounts = :abnormal_discounts,
                      status = 'draft',
                      updated_at = :now
                    WHERE id = :id
                      AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                    """
                ),
                {**aggregated, "id": summary_id, "now": now},
            )
        else:
            summary_id = str(uuid.uuid4())
            await db.execute(
                text(
                    """
                    INSERT INTO daily_summaries
                      (id, tenant_id, store_id, summary_date,
                       total_orders, dine_in_orders, takeaway_orders, banquet_orders,
                       total_revenue_fen, actual_revenue_fen, total_discount_fen,
                       avg_table_value_fen, max_discount_pct, abnormal_discounts,
                       status, created_at, updated_at)
                    VALUES
                      (:id, NULLIF(current_setting('app.tenant_id', true), '')::uuid,
                       :store_id, :summary_date,
                       :total_orders, :dine_in_orders, :takeaway_orders, :banquet_orders,
                       :total_revenue_fen, :actual_revenue_fen, :total_discount_fen,
                       :avg_table_value_fen, :max_discount_pct, :abnormal_discounts,
                       'draft', :now, :now)
                    """
                ),
                {
                    "id": summary_id,
                    "store_id": body.store_id,
                    "summary_date": body.summary_date,
                    **aggregated,
                    "now": now,
                },
            )

        record = {
            "id": summary_id,
            "tenant_id": x_tenant_id,
            "store_id": body.store_id,
            "summary_date": body.summary_date.isoformat(),
            **aggregated,
            "status": "draft",
            "confirmed_by": None,
            "confirmed_at": None,
            "created_at": existing.created_at.isoformat()
            if existing and hasattr(existing.created_at, "isoformat")
            else now.isoformat(),
            "updated_at": now.isoformat(),
        }

        log.info(
            "daily_summary_generated",
            summary_id=summary_id,
            store_id=body.store_id,
            summary_date=body.summary_date.isoformat(),
            tenant_id=x_tenant_id,
            total_orders=aggregated["total_orders"],
            actual_revenue_fen=aggregated["actual_revenue_fen"],
            abnormal_discounts=aggregated["abnormal_discounts"],
        )
        return {"ok": True, "data": record}

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("daily_summary_generate_db_error", exc_info=True, error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="生成日汇总失败") from exc


@router.get("/multi-store")
async def multi_store_summary(
    summary_date: date = Query(..., description="汇总日期"),
    store_ids: Optional[str] = Query(None, description="逗号分隔的门店ID列表，为空则查全部"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """E2: 多门店汇总对比（总部视角）。按实收金额降序排列。"""
    await _set_rls(db, x_tenant_id)

    try:
        where_clauses = [
            "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid",
            "summary_date = :summary_date",
            "is_deleted = false",
        ]
        params: dict = {"summary_date": summary_date}

        target_stores = None
        if store_ids:
            target_stores = [s.strip() for s in store_ids.split(",") if s.strip()]
            if target_stores:
                where_clauses.append("store_id = ANY(:store_ids)")
                params["store_ids"] = target_stores

        where_sql = " AND ".join(where_clauses)

        rows_result = await db.execute(
            text(
                f"""
                SELECT id, store_id, summary_date, total_orders, dine_in_orders,
                       takeaway_orders, banquet_orders, total_revenue_fen,
                       actual_revenue_fen, total_discount_fen, avg_table_value_fen,
                       max_discount_pct, abnormal_discounts, status,
                       confirmed_by, confirmed_at, created_at, updated_at
                FROM daily_summaries
                WHERE {where_sql}
                ORDER BY actual_revenue_fen DESC
                """
            ),
            params,
        )
        items: List[Dict[str, Any]] = [_serialize_row(dict(row._mapping)) for row in rows_result]

        total_revenue = sum(s.get("actual_revenue_fen", 0) or 0 for s in items)
        total_orders = sum(s.get("total_orders", 0) or 0 for s in items)
        total_abnormal = sum(s.get("abnormal_discounts", 0) or 0 for s in items)

        return {
            "ok": True,
            "data": {
                "summary_date": summary_date.isoformat(),
                "store_count": len(items),
                "total_revenue_fen": total_revenue,
                "total_orders": total_orders,
                "total_abnormal_discounts": total_abnormal,
                "stores": items,
            },
        }

    except SQLAlchemyError as exc:
        log.error("multi_store_summary_db_error", exc_info=True, error=str(exc), tenant_id=x_tenant_id)
        return {
            "ok": True,
            "data": {
                "summary_date": summary_date.isoformat(),
                "store_count": 0,
                "total_revenue_fen": 0,
                "total_orders": 0,
                "total_abnormal_discounts": 0,
                "stores": [],
            },
        }


@router.get("/{store_id}")
async def get_daily_summary(
    store_id: str,
    summary_date: Optional[date] = Query(None, description="汇总日期，默认今日"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """E2: 查询门店日汇总。"""
    await _set_rls(db, x_tenant_id)
    target_date = summary_date or date.today()

    try:
        result = await db.execute(
            text(
                """
                SELECT id, store_id, summary_date, total_orders, dine_in_orders,
                       takeaway_orders, banquet_orders, total_revenue_fen,
                       actual_revenue_fen, total_discount_fen, avg_table_value_fen,
                       max_discount_pct, abnormal_discounts, status,
                       confirmed_by, confirmed_at, created_at, updated_at
                FROM daily_summaries
                WHERE store_id = :store_id
                  AND summary_date = :summary_date
                  AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  AND is_deleted = false
                LIMIT 1
                """
            ),
            {"store_id": store_id, "summary_date": target_date},
        )
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="日汇总记录不存在，请先调用 generate 端点")

        return {"ok": True, "data": _serialize_row(dict(row._mapping))}

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("get_daily_summary_db_error", exc_info=True, error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="查询日汇总失败") from exc


@router.post("/{summary_id}/confirm")
async def confirm_daily_summary(
    summary_id: str,
    body: ConfirmSummaryRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """E2: 确认日汇总并锁定，锁定后不可重新生成。"""
    await _set_rls(db, x_tenant_id)

    try:
        check_result = await db.execute(
            text(
                """
                SELECT id, store_id, status FROM daily_summaries
                WHERE id = :id
                  AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  AND is_deleted = false
                LIMIT 1
                """
            ),
            {"id": summary_id},
        )
        record = check_result.fetchone()
        if not record:
            raise HTTPException(status_code=404, detail="日汇总记录不存在")
        if record.status == "locked":
            raise HTTPException(status_code=409, detail="日汇总已锁定")

        now = datetime.now(tz=timezone.utc)
        await db.execute(
            text(
                """
                UPDATE daily_summaries
                SET status = 'locked', confirmed_by = :confirmed_by,
                    confirmed_at = :now, updated_at = :now
                WHERE id = :id
                  AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                """
            ),
            {"id": summary_id, "confirmed_by": body.confirmed_by, "now": now},
        )

        row_result = await db.execute(
            text(
                """
                SELECT id, store_id, summary_date, total_orders, actual_revenue_fen,
                       status, confirmed_by, confirmed_at, updated_at
                FROM daily_summaries WHERE id = :id
                """
            ),
            {"id": summary_id},
        )
        updated = row_result.fetchone()
        data = _serialize_row(dict(updated._mapping)) if updated else {"id": summary_id}

        log.info(
            "daily_summary_confirmed",
            summary_id=summary_id,
            store_id=record.store_id,
            confirmed_by=body.confirmed_by,
            tenant_id=x_tenant_id,
        )
        return {"ok": True, "data": data}

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("confirm_daily_summary_db_error", exc_info=True, error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="确认日汇总失败") from exc
