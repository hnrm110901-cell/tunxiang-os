"""特殊操作报表 API 路由

GET /api/v1/reports/special-ops/gifts         赠菜报表
GET /api/v1/reports/special-ops/price-changes 变价报表
GET /api/v1/reports/special-ops/voids         废单报表
GET /api/v1/reports/special-ops/estimates     估清报表
GET /api/v1/reports/special-ops/rush-orders   催单报表
GET /api/v1/reports/special-ops/limits        限量报表
GET /api/v1/reports/special-ops/cleanups      沾清报表
GET /api/v1/reports/special-ops/transfers     转台报表
GET /api/v1/reports/special-ops/splits        拆单报表
GET /api/v1/reports/special-ops/merges        并单报表
GET /api/v1/reports/special-ops/discounts     折扣操作报表
GET /api/v1/reports/special-ops/refunds       退菜报表
GET /api/v1/reports/special-ops/summary       特殊操作日汇总
GET /api/v1/reports/special-ops/risk-alert    风险预警（异常频率操作人）

公共参数：
  ?store_id=<UUID>              门店ID（必填）
  ?date_from=YYYY-MM-DD         起始日期
  ?date_to=YYYY-MM-DD           截止日期
  ?format=csv                   返回 CSV 文件

响应格式：{"code": 0, "data": {...}, "message": "ok"}
"""
from __future__ import annotations

import csv
import io
from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/reports/special-ops", tags=["special-ops-reports"])


# ──────────────────────────────────────────────
# 公共辅助
# ──────────────────────────────────────────────

def _require_store(store_id: Optional[str]) -> str:
    if not store_id:
        raise HTTPException(status_code=400, detail="store_id query parameter is required")
    return store_id


def _require_tenant(tenant_id: Optional[str]) -> str:
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    return tenant_id


def _parse_date(date_str: Optional[str], default: Optional[date] = None) -> date:
    if not date_str:
        return default or date.today()
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid date format '{date_str}', expected YYYY-MM-DD",
        )


def _ok(data: object) -> dict:
    return {"code": 0, "data": data, "message": "ok"}


def _csv_response(rows: list[dict], filename: str) -> StreamingResponse:
    if not rows:
        content = ""
    else:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
        content = buf.getvalue()
    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _simple_list_endpoint(
    store_id: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
    format: Optional[str],
    x_tenant_id: Optional[str],
    filename_prefix: str,
) -> tuple[list[dict], str, str]:
    """通用参数校验，返回 (items, d_from, d_to) 占位结果"""
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)
    return [], str(d_from), str(d_to)


# ──────────────────────────────────────────────
# 1. 赠菜报表
# ──────────────────────────────────────────────

@router.get("/gifts")
async def api_gifts(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    operated_by: Optional[str] = Query(None, description="操作员工ID，不传则返回全部"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """赠菜报表 — 含操作人/菜品/赠菜金额/审批状态"""
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # TODO: 接入真实数据库查询
    # 返回: [{order_id, table_no, dish_name, gift_amount, operator, approved_by, created_at, reason}]
    items: list[dict] = []

    if format == "csv":
        return _csv_response(items, f"gifts_{d_from}_{d_to}.csv")
    return _ok({"total_count": 0, "total_amount": 0.0, "items": items})


# ──────────────────────────────────────────────
# 2. 变价报表
# ──────────────────────────────────────────────

@router.get("/price-changes")
async def api_price_changes(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """变价报表 — 含原价/变价/变价差额/操作人"""
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # TODO: 接入真实数据库查询
    # 返回: [{order_id, dish_name, original_price, changed_price, diff_amount, operator, created_at, reason}]
    items: list[dict] = []

    if format == "csv":
        return _csv_response(items, f"price_changes_{d_from}_{d_to}.csv")
    return _ok({"total_count": 0, "total_diff_amount": 0.0, "items": items})


# ──────────────────────────────────────────────
# 3. 废单报表
# ──────────────────────────────────────────────

@router.get("/voids")
async def api_voids(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """废单报表 — 作废订单明细/金额/操作人/废单原因"""
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # TODO: 接入真实数据库查询
    # 返回: [{order_id, table_no, amount, operator, void_reason, voided_at}]
    items: list[dict] = []

    if format == "csv":
        return _csv_response(items, f"voids_{d_from}_{d_to}.csv")
    return _ok({"total_count": 0, "total_amount": 0.0, "items": items})


# ──────────────────────────────────────────────
# 4. 估清报表
# ──────────────────────────────────────────────

@router.get("/estimates")
async def api_estimates(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """估清报表 — 菜品估清时间/操作人/影响订单数"""
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # TODO: 接入真实数据库查询
    # 返回: [{dish_id, dish_name, estimated_at, operator, affected_orders}]
    items: list[dict] = []

    if format == "csv":
        return _csv_response(items, f"estimates_{d_from}_{d_to}.csv")
    return _ok({"total_count": 0, "items": items})


# ──────────────────────────────────────────────
# 5. 催单报表
# ──────────────────────────────────────────────

@router.get("/rush-orders")
async def api_rush_orders(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """催单报表 — 催单次数/菜品/桌号/等待时长"""
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # TODO: 接入真实数据库查询
    # 返回: [{order_id, table_no, dish_name, rush_count, wait_minutes, operator, rushed_at}]
    items: list[dict] = []

    if format == "csv":
        return _csv_response(items, f"rush_orders_{d_from}_{d_to}.csv")
    return _ok({"total_count": 0, "items": items})


# ──────────────────────────────────────────────
# 6. 限量报表
# ──────────────────────────────────────────────

@router.get("/limits")
async def api_limits(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """限量报表 — 菜品限量设置/实际售出/触发次数"""
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # TODO: 接入真实数据库查询
    # 返回: [{dish_id, dish_name, limit_qty, sold_qty, triggered_count, operator, set_at}]
    items: list[dict] = []

    if format == "csv":
        return _csv_response(items, f"limits_{d_from}_{d_to}.csv")
    return _ok({"total_count": 0, "items": items})


# ──────────────────────────────────────────────
# 7. 沾清报表
# ──────────────────────────────────────────────

@router.get("/cleanups")
async def api_cleanups(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """沾清报表 — 沾清操作明细/操作人/桌号/金额影响"""
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # TODO: 接入真实数据库查询
    # 返回: [{order_id, table_no, amount_cleared, operator, cleared_at, reason}]
    items: list[dict] = []

    if format == "csv":
        return _csv_response(items, f"cleanups_{d_from}_{d_to}.csv")
    return _ok({"total_count": 0, "total_amount": 0.0, "items": items})


# ──────────────────────────────────────────────
# 8. 转台报表
# ──────────────────────────────────────────────

@router.get("/transfers")
async def api_transfers(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """转台报表 — 转台操作记录/源桌/目标桌/操作人"""
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # TODO: 接入真实数据库查询
    # 返回: [{order_id, from_table, to_table, operator, transferred_at}]
    items: list[dict] = []

    if format == "csv":
        return _csv_response(items, f"transfers_{d_from}_{d_to}.csv")
    return _ok({"total_count": 0, "items": items})


# ──────────────────────────────────────────────
# 9. 拆单报表
# ──────────────────────────────────────────────

@router.get("/splits")
async def api_splits(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """拆单报表 — 拆单操作记录/原单/拆后子单/操作人"""
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # TODO: 接入真实数据库查询
    # 返回: [{original_order_id, split_orders, table_no, operator, split_at, total_amount}]
    items: list[dict] = []

    if format == "csv":
        return _csv_response(items, f"splits_{d_from}_{d_to}.csv")
    return _ok({"total_count": 0, "items": items})


# ──────────────────────────────────────────────
# 10. 并单报表
# ──────────────────────────────────────────────

@router.get("/merges")
async def api_merges(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """并单报表 — 并单操作记录/源订单/合并后主单/操作人"""
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # TODO: 接入真实数据库查询
    # 返回: [{merged_order_id, source_orders, table_no, operator, merged_at, total_amount}]
    items: list[dict] = []

    if format == "csv":
        return _csv_response(items, f"merges_{d_from}_{d_to}.csv")
    return _ok({"total_count": 0, "items": items})


# ──────────────────────────────────────────────
# 11. 折扣操作报表
# ──────────────────────────────────────────────

@router.get("/discounts")
async def api_discount_ops(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """折扣操作报表 — 折扣类型/金额/操作人/授权人"""
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # TODO: 接入真实数据库查询
    # 返回: [{order_id, table_no, discount_type, discount_amount, operator, approved_by, created_at}]
    items: list[dict] = []

    if format == "csv":
        return _csv_response(items, f"discount_ops_{d_from}_{d_to}.csv")
    return _ok({"total_count": 0, "total_discount_amount": 0.0, "items": items})


# ──────────────────────────────────────────────
# 12. 退菜报表
# ──────────────────────────────────────────────

@router.get("/refunds")
async def api_refunds(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """退菜报表 — 退菜明细/退菜原因/退款金额/操作人"""
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # TODO: 接入真实数据库查询
    # 返回: [{order_id, table_no, dish_name, refund_amount, refund_reason, operator, refunded_at}]
    items: list[dict] = []

    if format == "csv":
        return _csv_response(items, f"refunds_{d_from}_{d_to}.csv")
    return _ok({"total_count": 0, "total_refund_amount": 0.0, "items": items})


# ──────────────────────────────────────────────
# 13. 特殊操作日汇总
# ──────────────────────────────────────────────

@router.get("/summary")
async def api_special_ops_summary(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date: Optional[str] = Query(None, description="业务日期 YYYY-MM-DD，默认今日"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """特殊操作日汇总 — 当日各类特殊操作次数/金额汇总"""
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    target_date = _parse_date(date)

    # TODO: 接入真实数据库查询
    data = {
        "date": str(target_date),
        "gifts_count": 0,
        "gifts_amount": 0.0,
        "price_changes_count": 0,
        "price_changes_diff": 0.0,
        "voids_count": 0,
        "voids_amount": 0.0,
        "estimates_count": 0,
        "rush_orders_count": 0,
        "limits_count": 0,
        "cleanups_count": 0,
        "transfers_count": 0,
        "splits_count": 0,
        "merges_count": 0,
        "discounts_count": 0,
        "discounts_amount": 0.0,
        "refunds_count": 0,
        "refunds_amount": 0.0,
    }

    if format == "csv":
        return _csv_response([data], f"special_ops_summary_{target_date}.csv")
    return _ok(data)


# ──────────────────────────────────────────────
# 14. 风险预警（异常频率操作人）
# ──────────────────────────────────────────────

@router.get("/risk-alert")
async def api_risk_alert(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD，默认今日"),
    date_to: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，默认今日"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """风险预警 — 识别特殊操作异常频率操作人，辅助稽核管控

    预警规则（示例）：
    - 同一操作人同日赠菜次数 > 5 次
    - 同一操作人同日废单次数 > 3 次
    - 同一操作人同日变价次数 > 10 次
    - 同一操作人同日折扣操作金额占营业额 > 20%
    """
    _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    # TODO: 接入真实数据库查询，按预警规则筛选异常操作人
    # 返回: [{operator_id, operator_name, risk_type, op_count, amount, risk_level: low/medium/high}]
    items: list[dict] = []

    if format == "csv":
        return _csv_response(items, f"risk_alert_{d_from}_{d_to}.csv")
    return _ok({"alert_count": 0, "items": items})
