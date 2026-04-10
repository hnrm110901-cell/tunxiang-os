"""渠道结算对账 API 路由

端点：
  POST  /api/v1/finance/bills/import              — 导入平台账单
  GET   /api/v1/finance/bills                      — 账单列表
  GET   /api/v1/finance/bills/{id}                 — 账单详情
  POST  /api/v1/finance/bills/{id}/reconcile       — 触发自动核对
  GET   /api/v1/finance/pl/channel                 — 渠道P&L
  GET   /api/v1/finance/pl/summary                 — 所有渠道P&L汇总
  GET   /api/v1/finance/discrepancies              — 差异清单
  POST  /api/v1/finance/discrepancies/{id}/resolve — 标记已处理
  GET   /api/v1/finance/discrepancies/summary      — 差异汇总统计
  GET   /api/v1/finance/forecast/receivable        — 未来30天到账预测
"""
import uuid
from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from pydantic import BaseModel
from services.channel_pl_calculator import ChannelPLCalculator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/finance", tags=["settlement"])

_calculator = ChannelPLCalculator()


# ─── 请求模型 ─────────────────────────────────────────────────────────────────

class BillImportRequest(BaseModel):
    store_id: str
    platform: str                   # meituan / eleme / douyin
    bill_period: str                # 如 2026-03
    bill_type: str = "monthly"      # monthly / weekly / daily
    total_orders: int = 0
    gross_amount_fen: int = 0
    commission_fen: int = 0
    subsidy_fen: int = 0
    other_deductions_fen: int = 0
    actual_receive_fen: int = 0
    bill_file_url: Optional[str] = None
    orders: list[dict] = []         # [{platform_order_id, amount_fen}, ...]


class ResolveRequest(BaseModel):
    resolve_note: str


# ─── 依赖注入 ─────────────────────────────────────────────────────────────────

async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _parse_uuid(val: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(val)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"无效的 {field_name}: {val}") from exc


def _parse_date(val: str, field_name: str) -> date:
    try:
        return date.fromisoformat(val)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"日期格式错误 {field_name}: {val}，请使用 YYYY-MM-DD") from exc


# ─── POST /bills/import ───────────────────────────────────────────────────────

@router.post("/bills/import", summary="导入平台账单")
async def import_bill(
    body: BillImportRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """导入美团/饿了么/抖音平台账单。

    - platform: meituan / eleme / douyin
    - bill_period: 账期，格式 YYYY-MM（月结）或 YYYY-MM-DD（日结/周结）
    - orders: 可选，明细订单列表，存入 raw_data 供后续逐单核对使用
    """
    valid_platforms = {"meituan", "eleme", "douyin"}
    if body.platform not in valid_platforms:
        raise HTTPException(status_code=400, detail=f"platform 必须是: {', '.join(valid_platforms)}")

    valid_bill_types = {"monthly", "weekly", "daily"}
    if body.bill_type not in valid_bill_types:
        raise HTTPException(status_code=400, detail=f"bill_type 必须是: {', '.join(valid_bill_types)}")

    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    sid = _parse_uuid(body.store_id, "store_id")

    import json
    raw_data = json.dumps({"orders": body.orders}, ensure_ascii=False)

    try:
        result = await db.execute(
            text("""
                INSERT INTO platform_bills (
                    tenant_id, store_id, platform, bill_period, bill_type,
                    total_orders, gross_amount_fen, commission_fen,
                    subsidy_fen, other_deductions_fen, actual_receive_fen,
                    bill_file_url, raw_data, status
                ) VALUES (
                    :tenant_id::UUID, :store_id::UUID, :platform, :bill_period, :bill_type,
                    :total_orders, :gross_amount_fen, :commission_fen,
                    :subsidy_fen, :other_deductions_fen, :actual_receive_fen,
                    :bill_file_url, :raw_data::JSONB, 'imported'
                )
                ON CONFLICT (tenant_id, store_id, platform, bill_period)
                DO UPDATE SET
                    total_orders = EXCLUDED.total_orders,
                    gross_amount_fen = EXCLUDED.gross_amount_fen,
                    commission_fen = EXCLUDED.commission_fen,
                    subsidy_fen = EXCLUDED.subsidy_fen,
                    other_deductions_fen = EXCLUDED.other_deductions_fen,
                    actual_receive_fen = EXCLUDED.actual_receive_fen,
                    bill_file_url = EXCLUDED.bill_file_url,
                    raw_data = EXCLUDED.raw_data,
                    status = 'imported',
                    updated_at = NOW()
                RETURNING id, status, created_at
            """),
            {
                "tenant_id": str(tid),
                "store_id": str(sid),
                "platform": body.platform,
                "bill_period": body.bill_period,
                "bill_type": body.bill_type,
                "total_orders": body.total_orders,
                "gross_amount_fen": body.gross_amount_fen,
                "commission_fen": body.commission_fen,
                "subsidy_fen": body.subsidy_fen,
                "other_deductions_fen": body.other_deductions_fen,
                "actual_receive_fen": body.actual_receive_fen,
                "bill_file_url": body.bill_file_url,
                "raw_data": raw_data,
            },
        )
        row = result.mappings().first()
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — 最外层HTTP兜底，返回500错误响应
        logger.error("import_bill.failed", store_id=body.store_id, platform=body.platform, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="账单导入失败") from exc

    logger.info("bill_imported", bill_id=str(row["id"]), platform=body.platform, bill_period=body.bill_period)
    return {
        "ok": True,
        "data": {
            "bill_id": str(row["id"]),
            "status": row["status"],
            "platform": body.platform,
            "bill_period": body.bill_period,
        },
        "error": None,
    }


# ─── GET /bills ───────────────────────────────────────────────────────────────

@router.get("/bills", summary="账单列表")
async def list_bills(
    store_id: Optional[str] = Query(None, description="门店ID"),
    platform: Optional[str] = Query(None, description="平台: meituan/eleme/douyin"),
    bill_period: Optional[str] = Query(None, description="账期: 如 2026-03"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """账单列表，支持按平台/账期/门店筛选，分页返回。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")

    where_clauses = ["tenant_id = :tenant_id::UUID"]
    params: dict = {"tenant_id": str(tid)}

    if store_id:
        sid = _parse_uuid(store_id, "store_id")
        where_clauses.append("store_id = :store_id::UUID")
        params["store_id"] = str(sid)

    if platform:
        where_clauses.append("platform = :platform")
        params["platform"] = platform

    if bill_period:
        where_clauses.append("bill_period = :bill_period")
        params["bill_period"] = bill_period

    where_sql = " AND ".join(where_clauses)
    offset = (page - 1) * size
    params["limit"] = size
    params["offset"] = offset

    try:
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM platform_bills WHERE {where_sql}"),
            params,
        )
        total = count_result.scalar()

        items_result = await db.execute(
            text(f"""
                SELECT id, store_id, platform, bill_period, bill_type,
                       total_orders, gross_amount_fen, commission_fen,
                       subsidy_fen, other_deductions_fen, actual_receive_fen,
                       bill_file_url, status, created_at, updated_at
                FROM platform_bills
                WHERE {where_sql}
                ORDER BY bill_period DESC, created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [dict(row) for row in items_result.mappings().all()]
    except Exception as exc:  # noqa: BLE001 — 最外层HTTP兜底，返回500错误响应
        logger.error("list_bills.failed", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询账单列表失败") from exc

    # UUID/date 序列化
    for item in items:
        for k, v in item.items():
            if isinstance(v, uuid.UUID):
                item[k] = str(v)
            elif hasattr(v, "isoformat"):
                item[k] = v.isoformat()

    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}, "error": None}


# ─── GET /bills/{id} ─────────────────────────────────────────────────────────

@router.get("/bills/{bill_id}", summary="账单详情")
async def get_bill(
    bill_id: str = Path(..., description="账单ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """获取单张账单的完整详情，含 raw_data 订单明细。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    bid = _parse_uuid(bill_id, "bill_id")

    try:
        result = await db.execute(
            text("""
                SELECT id, store_id, platform, bill_period, bill_type,
                       total_orders, gross_amount_fen, commission_fen,
                       subsidy_fen, other_deductions_fen, actual_receive_fen,
                       bill_file_url, raw_data, status, created_at, updated_at
                FROM platform_bills
                WHERE id = :bill_id::UUID AND tenant_id = :tenant_id::UUID
            """),
            {"bill_id": str(bid), "tenant_id": str(tid)},
        )
        row = result.mappings().first()
    except Exception as exc:  # noqa: BLE001 — 最外层HTTP兜底，返回500错误响应
        logger.error("get_bill.failed", bill_id=bill_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询账单失败") from exc

    if row is None:
        raise HTTPException(status_code=404, detail=f"账单不存在: {bill_id}")

    data = dict(row)
    for k, v in data.items():
        if isinstance(v, uuid.UUID):
            data[k] = str(v)
        elif hasattr(v, "isoformat"):
            data[k] = v.isoformat()

    return {"ok": True, "data": data, "error": None}


# ─── POST /bills/{id}/reconcile ──────────────────────────────────────────────

@router.post("/bills/{bill_id}/reconcile", summary="触发自动核对")
async def reconcile_bill(
    bill_id: str = Path(..., description="账单ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """将平台账单与系统订单逐单核对，生成差异记录并更新账单状态为 reconciled。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    bid = _parse_uuid(bill_id, "bill_id")

    try:
        result = await _calculator.reconcile_bill(bid, tid, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — 最外层HTTP兜底，返回500错误响应
        logger.error("reconcile_bill.failed", bill_id=bill_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="账单核对失败") from exc

    return {"ok": True, "data": result.model_dump(), "error": None}


# ─── GET /pl/channel ─────────────────────────────────────────────────────────

@router.get("/pl/channel", summary="渠道P&L报表")
async def get_channel_pl(
    store_id: str = Query(..., description="门店ID"),
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    channel_id: Optional[str] = Query(None, description="渠道ID，不传则返回所有渠道"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """按渠道计算指定时段的 P&L：收入、佣金、食材成本、毛利、毛利率。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    sid = _parse_uuid(store_id, "store_id")
    s_date = _parse_date(start_date, "start_date")
    e_date = _parse_date(end_date, "end_date")

    if s_date > e_date:
        raise HTTPException(status_code=400, detail="start_date 不能晚于 end_date")

    try:
        report = await _calculator.calculate_channel_pl(
            store_id=sid,
            tenant_id=tid,
            start_date=s_date,
            end_date=e_date,
            channel_id=channel_id,
            db=db,
        )
    except Exception as exc:  # noqa: BLE001 — 最外层HTTP兜底，返回500错误响应
        logger.error("get_channel_pl.failed", store_id=store_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="渠道P&L计算失败") from exc

    return {"ok": True, "data": report.model_dump(), "error": None}


# ─── GET /pl/summary ─────────────────────────────────────────────────────────

@router.get("/pl/summary", summary="所有渠道P&L汇总")
async def get_pl_summary(
    store_id: str = Query(..., description="门店ID"),
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """返回所有渠道的 P&L 汇总，含总收入、总毛利、整体毛利率。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    sid = _parse_uuid(store_id, "store_id")
    s_date = _parse_date(start_date, "start_date")
    e_date = _parse_date(end_date, "end_date")

    if s_date > e_date:
        raise HTTPException(status_code=400, detail="start_date 不能晚于 end_date")

    try:
        report = await _calculator.calculate_channel_pl(
            store_id=sid,
            tenant_id=tid,
            start_date=s_date,
            end_date=e_date,
            channel_id=None,
            db=db,
        )
    except Exception as exc:  # noqa: BLE001 — 最外层HTTP兜底，返回500错误响应
        logger.error("get_pl_summary.failed", store_id=store_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="P&L汇总计算失败") from exc

    summary = {
        "store_id": str(report.store_id),
        "start_date": str(report.start_date),
        "end_date": str(report.end_date),
        "channel_count": len(report.channels),
        "total_gross_revenue_fen": report.total_gross_revenue_fen,
        "total_gross_profit_fen": report.total_gross_profit_fen,
        "overall_margin": report.overall_margin,
        "channels": [ch.model_dump() for ch in report.channels],
    }
    return {"ok": True, "data": summary, "error": None}


# ─── GET /discrepancies ───────────────────────────────────────────────────────

@router.get("/discrepancies", summary="差异清单")
async def list_discrepancies(
    store_id: str = Query(..., description="门店ID"),
    platform: Optional[str] = Query(None, description="平台: meituan/eleme/douyin"),
    status: Optional[str] = Query("open", description="状态: open/resolved/disputed/waived"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """查询结算差异清单，默认只返回待处理（open）的差异。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    sid = _parse_uuid(store_id, "store_id")

    where_clauses = ["tenant_id = :tenant_id::UUID", "store_id = :store_id::UUID"]
    params: dict = {"tenant_id": str(tid), "store_id": str(sid)}

    if platform:
        where_clauses.append("platform = :platform")
        params["platform"] = platform

    if status:
        valid_statuses = {"open", "resolved", "disputed", "waived"}
        if status not in valid_statuses:
            raise HTTPException(status_code=400, detail=f"status 必须是: {', '.join(valid_statuses)}")
        where_clauses.append("status = :status")
        params["status"] = status

    where_sql = " AND ".join(where_clauses)
    offset = (page - 1) * size
    params["limit"] = size
    params["offset"] = offset

    try:
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM settlement_discrepancies WHERE {where_sql}"),
            params,
        )
        total = count_result.scalar()

        items_result = await db.execute(
            text(f"""
                SELECT id, store_id, platform, bill_id,
                       platform_order_id, internal_order_id,
                       platform_amount_fen, system_amount_fen, diff_fen,
                       discrepancy_type, status,
                       resolved_at, resolved_by, resolve_note, created_at
                FROM settlement_discrepancies
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [dict(row) for row in items_result.mappings().all()]
    except Exception as exc:  # noqa: BLE001 — 最外层HTTP兜底，返回500错误响应
        logger.error("list_discrepancies.failed", store_id=store_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询差异清单失败") from exc

    for item in items:
        for k, v in item.items():
            if isinstance(v, uuid.UUID):
                item[k] = str(v)
            elif hasattr(v, "isoformat"):
                item[k] = v.isoformat()

    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}, "error": None}


# ─── POST /discrepancies/{id}/resolve ────────────────────────────────────────

@router.post("/discrepancies/{discrepancy_id}/resolve", summary="标记差异已处理")
async def resolve_discrepancy(
    discrepancy_id: str = Path(..., description="差异记录ID"),
    body: ResolveRequest = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """将差异记录标记为已处理（resolved），记录处理说明。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    did = _parse_uuid(discrepancy_id, "discrepancy_id")

    try:
        result = await db.execute(
            text("""
                UPDATE settlement_discrepancies
                SET status = 'resolved',
                    resolved_at = NOW(),
                    resolve_note = :resolve_note
                WHERE id = :discrepancy_id::UUID
                  AND tenant_id = :tenant_id::UUID
                  AND status = 'open'
                RETURNING id, status, resolved_at
            """),
            {
                "discrepancy_id": str(did),
                "tenant_id": str(tid),
                "resolve_note": body.resolve_note,
            },
        )
        row = result.mappings().first()
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — 最外层HTTP兜底，返回500错误响应
        logger.error("resolve_discrepancy.failed", discrepancy_id=discrepancy_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="标记处理失败") from exc

    if row is None:
        raise HTTPException(status_code=404, detail=f"差异记录不存在或已处理: {discrepancy_id}")

    return {
        "ok": True,
        "data": {
            "discrepancy_id": str(did),
            "status": row["status"],
            "resolved_at": row["resolved_at"].isoformat() if row["resolved_at"] else None,
        },
        "error": None,
    }


# ─── GET /discrepancies/summary ──────────────────────────────────────────────

@router.get("/discrepancies/summary", summary="差异汇总统计")
async def get_discrepancy_summary(
    store_id: str = Query(..., description="门店ID"),
    platform: Optional[str] = Query(None, description="平台: meituan/eleme/douyin"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """差异汇总：总量、待处理数、总差异金额、差异率。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    sid = _parse_uuid(store_id, "store_id")

    try:
        summary = await _calculator.get_discrepancy_summary(
            store_id=sid,
            tenant_id=tid,
            platform=platform,
            db=db,
        )
    except Exception as exc:  # noqa: BLE001 — 最外层HTTP兜底，返回500错误响应
        logger.error("get_discrepancy_summary.failed", store_id=store_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="差异汇总统计失败") from exc

    return {"ok": True, "data": summary.model_dump(), "error": None}


# ─── GET /forecast/receivable ────────────────────────────────────────────────

@router.get("/forecast/receivable", summary="未来到账预测")
async def get_receivable_forecast(
    store_id: str = Query(..., description="门店ID"),
    days_ahead: int = Query(30, ge=1, le=90, description="预测天数，默认30天"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """根据历史外卖订单和各平台结算周期，预测未来资金到账时间和金额。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    sid = _parse_uuid(store_id, "store_id")

    try:
        forecasts = await _calculator.generate_receivable_forecast(
            store_id=sid,
            tenant_id=tid,
            days_ahead=days_ahead,
            db=db,
        )
    except Exception as exc:  # noqa: BLE001 — 最外层HTTP兜底，返回500错误响应
        logger.error("get_receivable_forecast.failed", store_id=store_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="到账预测生成失败") from exc

    items = [f.model_dump() for f in forecasts]
    for item in items:
        for k, v in item.items():
            if isinstance(v, uuid.UUID):
                item[k] = str(v)
            elif hasattr(v, "isoformat"):
                item[k] = v.isoformat()

    total_expected = sum(f.expected_amount_fen for f in forecasts)
    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "days_ahead": days_ahead,
            "forecast_count": len(forecasts),
            "total_expected_fen": total_expected,
            "items": items,
        },
        "error": None,
    }
