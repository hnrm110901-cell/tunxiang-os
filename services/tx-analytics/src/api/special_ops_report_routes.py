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

数据来源：
  order_operations_log
    (id, tenant_id, store_id, order_id, op_type, amount, operated_by,
     operated_at, approved_by, reason, extra JSONB)

  op_type 枚举值（与实现相关）：
    gift          — 赠菜
    price_change  — 变价
    void          — 废单
    estimate      — 估清
    rush          — 催单
    limit         — 限量
    cleanup       — 沾清
    transfer      — 转台
    split         — 拆单
    merge         — 并单
    discount      — 折扣
    refund        — 退菜

  所有查询均包含 tenant_id + store_id 过滤，operated_at 日期范围过滤。
"""

from __future__ import annotations

import csv
import io
from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

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


def _op_base_query(op_type: str) -> str:
    """生成按 op_type 过滤的通用 order_operations_log 查询片段。"""
    return f"""
        SELECT
            ool.id,
            ool.order_id,
            ool.op_type,
            ool.amount,
            ool.operated_by,
            ool.operated_at,
            ool.approved_by,
            ool.reason,
            ool.extra
        FROM order_operations_log ool
        WHERE ool.tenant_id   = :tenant_id
          AND ool.store_id    = :store_id
          AND ool.op_type     = '{op_type}'
          AND DATE(ool.operated_at) BETWEEN :d_from AND :d_to
        ORDER BY ool.operated_at DESC
    """


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
    db: AsyncSession = Depends(get_db),
):
    """赠菜报表 — 含操作人/赠菜金额/审批人/原因

    查询逻辑：
      - 从 order_operations_log 取 op_type='gift' 的记录
      - LEFT JOIN employees 两次以获取操作人和审批人姓名
      - 可按 operated_by 过滤特定操作人
      - 汇总：总赠菜次数、总赠菜金额（amount 字段，分为单位）
    """
    tenant_id = _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    op_filter = "AND ool.operated_by = :operated_by" if operated_by else ""
    params: dict = {
        "tenant_id": tenant_id,
        "store_id": store_id,
        "d_from": str(d_from),
        "d_to": str(d_to),
    }
    if operated_by:
        params["operated_by"] = operated_by

    rows = await db.execute(
        text(
            f"""
            SELECT
                ool.id,
                ool.order_id,
                ool.amount                                          AS gift_amount_fen,
                ool.operated_by,
                op_emp.employee_name                                AS operator_name,
                ool.approved_by,
                ap_emp.employee_name                                AS approver_name,
                ool.reason,
                ool.operated_at,
                ool.extra
            FROM order_operations_log ool
            LEFT JOIN employees op_emp
                   ON op_emp.id::text = ool.operated_by
                  AND op_emp.tenant_id = ool.tenant_id
                  AND op_emp.is_deleted = FALSE
            LEFT JOIN employees ap_emp
                   ON ap_emp.id::text = ool.approved_by
                  AND ap_emp.tenant_id = ool.tenant_id
                  AND ap_emp.is_deleted = FALSE
            WHERE ool.tenant_id  = :tenant_id
              AND ool.store_id   = :store_id
              AND ool.op_type    = 'gift'
              AND DATE(ool.operated_at) BETWEEN :d_from AND :d_to
              {op_filter}
            ORDER BY ool.operated_at DESC
            """
        ),
        params,
    )
    items = [dict(r) for r in rows.mappings()]
    total_count = len(items)
    total_amount_fen = sum(r.get("gift_amount_fen") or 0 for r in items)

    if format == "csv":
        return _csv_response(items, f"gifts_{d_from}_{d_to}.csv")
    return _ok({"total_count": total_count, "total_amount_fen": total_amount_fen, "items": items})


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
    db: AsyncSession = Depends(get_db),
):
    """变价报表 — 含原价/变价/变价差额/操作人

    查询逻辑：
      - 从 order_operations_log 取 op_type='price_change' 的记录
      - extra JSONB 字段存储 {original_price_fen, changed_price_fen, dish_id, dish_name}
      - amount 字段 = changed_price_fen - original_price_fen（负数为降价）
      - 汇总：总变价次数、总差额金额（可正可负）
    """
    tenant_id = _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    rows = await db.execute(
        text(
            """
            SELECT
                ool.id,
                ool.order_id,
                ool.amount                                              AS diff_amount_fen,
                (ool.extra->>'original_price_fen')::bigint              AS original_price_fen,
                (ool.extra->>'changed_price_fen')::bigint               AS changed_price_fen,
                ool.extra->>'dish_id'                                   AS dish_id,
                ool.extra->>'dish_name'                                 AS dish_name,
                ool.operated_by,
                emp.employee_name                                       AS operator_name,
                ool.reason,
                ool.operated_at
            FROM order_operations_log ool
            LEFT JOIN employees emp
                   ON emp.id::text = ool.operated_by
                  AND emp.tenant_id = ool.tenant_id
                  AND emp.is_deleted = FALSE
            WHERE ool.tenant_id  = :tenant_id
              AND ool.store_id   = :store_id
              AND ool.op_type    = 'price_change'
              AND DATE(ool.operated_at) BETWEEN :d_from AND :d_to
            ORDER BY ool.operated_at DESC
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "d_from": str(d_from),
            "d_to": str(d_to),
        },
    )
    items = [dict(r) for r in rows.mappings()]
    total_diff_fen = sum(r.get("diff_amount_fen") or 0 for r in items)

    if format == "csv":
        return _csv_response(items, f"price_changes_{d_from}_{d_to}.csv")
    return _ok({"total_count": len(items), "total_diff_amount_fen": total_diff_fen, "items": items})


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
    db: AsyncSession = Depends(get_db),
):
    """废单报表 — 作废订单明细/金额/操作人/废单原因

    查询逻辑：
      - 从 order_operations_log 取 op_type='void' 的记录
      - amount 字段 = 废单的原订单金额（分）
      - extra JSONB 可携带 {table_no, order_status_before}
      - LEFT JOIN employees 获取操作人姓名
    """
    tenant_id = _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    rows = await db.execute(
        text(
            """
            SELECT
                ool.id,
                ool.order_id,
                ool.amount                                              AS void_amount_fen,
                ool.extra->>'table_no'                                  AS table_no,
                ool.operated_by,
                emp.employee_name                                       AS operator_name,
                ool.approved_by,
                ap_emp.employee_name                                    AS approver_name,
                ool.reason                                              AS void_reason,
                ool.operated_at                                         AS voided_at
            FROM order_operations_log ool
            LEFT JOIN employees emp
                   ON emp.id::text = ool.operated_by
                  AND emp.tenant_id = ool.tenant_id
                  AND emp.is_deleted = FALSE
            LEFT JOIN employees ap_emp
                   ON ap_emp.id::text = ool.approved_by
                  AND ap_emp.tenant_id = ool.tenant_id
                  AND ap_emp.is_deleted = FALSE
            WHERE ool.tenant_id  = :tenant_id
              AND ool.store_id   = :store_id
              AND ool.op_type    = 'void'
              AND DATE(ool.operated_at) BETWEEN :d_from AND :d_to
            ORDER BY ool.operated_at DESC
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "d_from": str(d_from),
            "d_to": str(d_to),
        },
    )
    items = [dict(r) for r in rows.mappings()]
    total_amount_fen = sum(r.get("void_amount_fen") or 0 for r in items)

    if format == "csv":
        return _csv_response(items, f"voids_{d_from}_{d_to}.csv")
    return _ok({"total_count": len(items), "total_amount_fen": total_amount_fen, "items": items})


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
    db: AsyncSession = Depends(get_db),
):
    """估清报表 — 菜品估清时间/操作人/影响订单数

    查询逻辑（接入真实数据）：
      SELECT ool.id, ool.order_id,
             ool.extra->>'dish_id' AS dish_id,
             ool.extra->>'dish_name' AS dish_name,
             ool.extra->>'affected_orders' AS affected_orders,
             emp.employee_name AS operator_name,
             ool.operated_at AS estimated_at
      FROM order_operations_log ool
      LEFT JOIN employees emp ON emp.id::text = ool.operated_by ...
      WHERE ool.tenant_id=:tenant_id AND ool.store_id=:store_id
        AND ool.op_type='estimate'
        AND DATE(ool.operated_at) BETWEEN :d_from AND :d_to
      ORDER BY ool.operated_at DESC
    """
    tenant_id = _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    rows = await db.execute(
        text(
            """
            SELECT
                ool.id,
                ool.order_id,
                ool.extra->>'dish_id'                                       AS dish_id,
                ool.extra->>'dish_name'                                     AS dish_name,
                (ool.extra->>'affected_orders')::int                        AS affected_orders,
                ool.operated_by,
                emp.employee_name                                           AS operator_name,
                ool.operated_at                                             AS estimated_at
            FROM order_operations_log ool
            LEFT JOIN employees emp
                   ON emp.id::text = ool.operated_by
                  AND emp.tenant_id = ool.tenant_id
                  AND emp.is_deleted = FALSE
            WHERE ool.tenant_id  = :tenant_id
              AND ool.store_id   = :store_id
              AND ool.op_type    = 'estimate'
              AND DATE(ool.operated_at) BETWEEN :d_from AND :d_to
            ORDER BY ool.operated_at DESC
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "d_from": str(d_from),
            "d_to": str(d_to),
        },
    )
    items = [dict(r) for r in rows.mappings()]

    if format == "csv":
        return _csv_response(items, f"estimates_{d_from}_{d_to}.csv")
    return _ok({"total_count": len(items), "items": items})


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
    db: AsyncSession = Depends(get_db),
):
    """催单报表 — 催单次数/菜品/桌号/等待时长

    查询逻辑：
      SELECT ool.order_id, ool.extra->>'table_no', ool.extra->>'dish_name',
             ool.extra->>'wait_minutes'::float, emp.employee_name AS operator_name,
             ool.operated_at AS rushed_at
      FROM order_operations_log ool
      LEFT JOIN employees emp ...
      WHERE ool.op_type='rush' AND ool.tenant_id=:tenant_id AND ool.store_id=:store_id
        AND DATE(operated_at) BETWEEN :d_from AND :d_to
      ORDER BY ool.operated_at DESC
    """
    tenant_id = _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    rows = await db.execute(
        text(
            """
            SELECT
                ool.id,
                ool.order_id,
                ool.extra->>'table_no'                                      AS table_no,
                ool.extra->>'dish_name'                                     AS dish_name,
                (ool.extra->>'wait_minutes')::float                         AS wait_minutes,
                ool.operated_by,
                emp.employee_name                                           AS operator_name,
                ool.operated_at                                             AS rushed_at
            FROM order_operations_log ool
            LEFT JOIN employees emp
                   ON emp.id::text = ool.operated_by
                  AND emp.tenant_id = ool.tenant_id
                  AND emp.is_deleted = FALSE
            WHERE ool.tenant_id  = :tenant_id
              AND ool.store_id   = :store_id
              AND ool.op_type    = 'rush'
              AND DATE(ool.operated_at) BETWEEN :d_from AND :d_to
            ORDER BY ool.operated_at DESC
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "d_from": str(d_from),
            "d_to": str(d_to),
        },
    )
    items = [dict(r) for r in rows.mappings()]

    if format == "csv":
        return _csv_response(items, f"rush_orders_{d_from}_{d_to}.csv")
    return _ok({"total_count": len(items), "items": items})


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
    db: AsyncSession = Depends(get_db),
):
    """限量报表 — 菜品限量设置/实际售出/触发次数

    查询逻辑：
      SELECT ool.extra->>'dish_id', ool.extra->>'dish_name',
             (ool.extra->>'limit_qty')::int AS limit_qty,
             (ool.extra->>'sold_qty')::int AS sold_qty,
             COUNT(*) AS triggered_count,
             emp.employee_name AS operator_name,
             ool.operated_at AS set_at
      FROM order_operations_log ool LEFT JOIN employees emp ...
      WHERE ool.op_type='limit' AND ool.tenant_id=:tenant_id AND ool.store_id=:store_id
        AND DATE(operated_at) BETWEEN :d_from AND :d_to
      GROUP BY dish_id, dish_name, limit_qty, sold_qty, operator_name, set_at
      ORDER BY triggered_count DESC
    """
    tenant_id = _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    rows = await db.execute(
        text(
            """
            SELECT
                ool.extra->>'dish_id'                                       AS dish_id,
                ool.extra->>'dish_name'                                     AS dish_name,
                (ool.extra->>'limit_qty')::int                              AS limit_qty,
                (ool.extra->>'sold_qty')::int                               AS sold_qty,
                COUNT(*)                                                    AS triggered_count,
                ool.operated_by,
                emp.employee_name                                           AS operator_name,
                MIN(ool.operated_at)                                        AS first_set_at,
                MAX(ool.operated_at)                                        AS last_set_at
            FROM order_operations_log ool
            LEFT JOIN employees emp
                   ON emp.id::text = ool.operated_by
                  AND emp.tenant_id = ool.tenant_id
                  AND emp.is_deleted = FALSE
            WHERE ool.tenant_id  = :tenant_id
              AND ool.store_id   = :store_id
              AND ool.op_type    = 'limit'
              AND DATE(ool.operated_at) BETWEEN :d_from AND :d_to
            GROUP BY
                ool.extra->>'dish_id',
                ool.extra->>'dish_name',
                (ool.extra->>'limit_qty')::int,
                (ool.extra->>'sold_qty')::int,
                ool.operated_by,
                emp.employee_name
            ORDER BY triggered_count DESC
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "d_from": str(d_from),
            "d_to": str(d_to),
        },
    )
    items = [dict(r) for r in rows.mappings()]

    if format == "csv":
        return _csv_response(items, f"limits_{d_from}_{d_to}.csv")
    return _ok({"total_count": len(items), "items": items})


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
    db: AsyncSession = Depends(get_db),
):
    """沾清报表 — 沾清操作明细/操作人/桌号/金额影响

    查询逻辑：
      SELECT ool.id, ool.order_id, ool.amount AS amount_cleared_fen,
             ool.extra->>'table_no', emp.employee_name AS operator_name,
             ool.reason, ool.operated_at AS cleared_at
      FROM order_operations_log ool LEFT JOIN employees emp ...
      WHERE ool.op_type='cleanup' AND tenant/store/date 过滤
      ORDER BY ool.operated_at DESC
    """
    tenant_id = _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    rows = await db.execute(
        text(
            """
            SELECT
                ool.id,
                ool.order_id,
                ool.amount                                                  AS amount_cleared_fen,
                ool.extra->>'table_no'                                      AS table_no,
                ool.operated_by,
                emp.employee_name                                           AS operator_name,
                ool.reason,
                ool.operated_at                                             AS cleared_at
            FROM order_operations_log ool
            LEFT JOIN employees emp
                   ON emp.id::text = ool.operated_by
                  AND emp.tenant_id = ool.tenant_id
                  AND emp.is_deleted = FALSE
            WHERE ool.tenant_id  = :tenant_id
              AND ool.store_id   = :store_id
              AND ool.op_type    = 'cleanup'
              AND DATE(ool.operated_at) BETWEEN :d_from AND :d_to
            ORDER BY ool.operated_at DESC
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "d_from": str(d_from),
            "d_to": str(d_to),
        },
    )
    items = [dict(r) for r in rows.mappings()]
    total_amount_fen = sum(r.get("amount_cleared_fen") or 0 for r in items)

    if format == "csv":
        return _csv_response(items, f"cleanups_{d_from}_{d_to}.csv")
    return _ok({"total_count": len(items), "total_amount_fen": total_amount_fen, "items": items})


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
    db: AsyncSession = Depends(get_db),
):
    """转台报表 — 转台操作记录/源桌/目标桌/操作人

    查询逻辑：
      SELECT ool.order_id, ool.extra->>'from_table', ool.extra->>'to_table',
             emp.employee_name AS operator_name, ool.operated_at AS transferred_at
      FROM order_operations_log ool LEFT JOIN employees emp ...
      WHERE ool.op_type='transfer' AND tenant/store/date 过滤
      ORDER BY ool.operated_at DESC
    """
    tenant_id = _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    rows = await db.execute(
        text(
            """
            SELECT
                ool.id,
                ool.order_id,
                ool.extra->>'from_table'                                    AS from_table,
                ool.extra->>'to_table'                                      AS to_table,
                ool.operated_by,
                emp.employee_name                                           AS operator_name,
                ool.operated_at                                             AS transferred_at
            FROM order_operations_log ool
            LEFT JOIN employees emp
                   ON emp.id::text = ool.operated_by
                  AND emp.tenant_id = ool.tenant_id
                  AND emp.is_deleted = FALSE
            WHERE ool.tenant_id  = :tenant_id
              AND ool.store_id   = :store_id
              AND ool.op_type    = 'transfer'
              AND DATE(ool.operated_at) BETWEEN :d_from AND :d_to
            ORDER BY ool.operated_at DESC
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "d_from": str(d_from),
            "d_to": str(d_to),
        },
    )
    items = [dict(r) for r in rows.mappings()]

    if format == "csv":
        return _csv_response(items, f"transfers_{d_from}_{d_to}.csv")
    return _ok({"total_count": len(items), "items": items})


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
    db: AsyncSession = Depends(get_db),
):
    """拆单报表 — 拆单操作记录/原单/拆后子单/操作人

    查询逻辑：
      SELECT ool.order_id AS original_order_id,
             ool.extra->'split_orders' AS split_orders,   -- JSONB数组
             ool.extra->>'table_no', ool.amount AS total_amount_fen,
             emp.employee_name AS operator_name, ool.operated_at AS split_at
      FROM order_operations_log ool LEFT JOIN employees emp ...
      WHERE ool.op_type='split' AND tenant/store/date 过滤
      ORDER BY ool.operated_at DESC
    """
    tenant_id = _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    rows = await db.execute(
        text(
            """
            SELECT
                ool.id,
                ool.order_id                                                AS original_order_id,
                ool.extra->'split_orders'                                   AS split_orders,
                ool.extra->>'table_no'                                      AS table_no,
                ool.amount                                                  AS total_amount_fen,
                ool.operated_by,
                emp.employee_name                                           AS operator_name,
                ool.operated_at                                             AS split_at
            FROM order_operations_log ool
            LEFT JOIN employees emp
                   ON emp.id::text = ool.operated_by
                  AND emp.tenant_id = ool.tenant_id
                  AND emp.is_deleted = FALSE
            WHERE ool.tenant_id  = :tenant_id
              AND ool.store_id   = :store_id
              AND ool.op_type    = 'split'
              AND DATE(ool.operated_at) BETWEEN :d_from AND :d_to
            ORDER BY ool.operated_at DESC
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "d_from": str(d_from),
            "d_to": str(d_to),
        },
    )
    items = [dict(r) for r in rows.mappings()]

    if format == "csv":
        return _csv_response(items, f"splits_{d_from}_{d_to}.csv")
    return _ok({"total_count": len(items), "items": items})


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
    db: AsyncSession = Depends(get_db),
):
    """并单报表 — 并单操作记录/源订单/合并后主单/操作人

    查询逻辑：
      SELECT ool.order_id AS merged_order_id,
             ool.extra->'source_orders' AS source_orders,  -- JSONB数组
             ool.extra->>'table_no', ool.amount AS total_amount_fen,
             emp.employee_name AS operator_name, ool.operated_at AS merged_at
      FROM order_operations_log ool LEFT JOIN employees emp ...
      WHERE ool.op_type='merge' AND tenant/store/date 过滤
      ORDER BY ool.operated_at DESC
    """
    tenant_id = _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    rows = await db.execute(
        text(
            """
            SELECT
                ool.id,
                ool.order_id                                                AS merged_order_id,
                ool.extra->'source_orders'                                  AS source_orders,
                ool.extra->>'table_no'                                      AS table_no,
                ool.amount                                                  AS total_amount_fen,
                ool.operated_by,
                emp.employee_name                                           AS operator_name,
                ool.operated_at                                             AS merged_at
            FROM order_operations_log ool
            LEFT JOIN employees emp
                   ON emp.id::text = ool.operated_by
                  AND emp.tenant_id = ool.tenant_id
                  AND emp.is_deleted = FALSE
            WHERE ool.tenant_id  = :tenant_id
              AND ool.store_id   = :store_id
              AND ool.op_type    = 'merge'
              AND DATE(ool.operated_at) BETWEEN :d_from AND :d_to
            ORDER BY ool.operated_at DESC
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "d_from": str(d_from),
            "d_to": str(d_to),
        },
    )
    items = [dict(r) for r in rows.mappings()]

    if format == "csv":
        return _csv_response(items, f"merges_{d_from}_{d_to}.csv")
    return _ok({"total_count": len(items), "items": items})


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
    db: AsyncSession = Depends(get_db),
):
    """折扣操作报表 — 折扣类型/金额/操作人/授权人

    查询逻辑：
      SELECT ool.id, ool.order_id, ool.amount AS discount_amount_fen,
             ool.extra->>'discount_type', ool.extra->>'table_no',
             op_emp.employee_name AS operator_name,
             ap_emp.employee_name AS approver_name,
             ool.operated_at
      FROM order_operations_log ool
      LEFT JOIN employees op_emp ON op_emp.id::text = ool.operated_by ...
      LEFT JOIN employees ap_emp ON ap_emp.id::text = ool.approved_by ...
      WHERE ool.op_type='discount' AND tenant/store/date 过滤
      ORDER BY ool.operated_at DESC
    """
    tenant_id = _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    rows = await db.execute(
        text(
            """
            SELECT
                ool.id,
                ool.order_id,
                ool.amount                                                  AS discount_amount_fen,
                ool.extra->>'discount_type'                                 AS discount_type,
                ool.extra->>'table_no'                                      AS table_no,
                ool.operated_by,
                op_emp.employee_name                                        AS operator_name,
                ool.approved_by,
                ap_emp.employee_name                                        AS approver_name,
                ool.operated_at
            FROM order_operations_log ool
            LEFT JOIN employees op_emp
                   ON op_emp.id::text = ool.operated_by
                  AND op_emp.tenant_id = ool.tenant_id
                  AND op_emp.is_deleted = FALSE
            LEFT JOIN employees ap_emp
                   ON ap_emp.id::text = ool.approved_by
                  AND ap_emp.tenant_id = ool.tenant_id
                  AND ap_emp.is_deleted = FALSE
            WHERE ool.tenant_id  = :tenant_id
              AND ool.store_id   = :store_id
              AND ool.op_type    = 'discount'
              AND DATE(ool.operated_at) BETWEEN :d_from AND :d_to
            ORDER BY ool.operated_at DESC
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "d_from": str(d_from),
            "d_to": str(d_to),
        },
    )
    items = [dict(r) for r in rows.mappings()]
    total_discount_amount_fen = sum(r.get("discount_amount_fen") or 0 for r in items)

    if format == "csv":
        return _csv_response(items, f"discount_ops_{d_from}_{d_to}.csv")
    return _ok({"total_count": len(items), "total_discount_amount_fen": total_discount_amount_fen, "items": items})


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
    db: AsyncSession = Depends(get_db),
):
    """退菜报表 — 退菜明细/退菜原因/退款金额/操作人

    查询逻辑：
      SELECT ool.id, ool.order_id, ool.amount AS refund_amount_fen,
             ool.extra->>'dish_name', ool.extra->>'table_no',
             ool.reason AS refund_reason,
             emp.employee_name AS operator_name,
             ool.operated_at AS refunded_at
      FROM order_operations_log ool LEFT JOIN employees emp ...
      WHERE ool.op_type='refund' AND tenant/store/date 过滤
      ORDER BY ool.operated_at DESC
    """
    tenant_id = _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    rows = await db.execute(
        text(
            """
            SELECT
                ool.id,
                ool.order_id,
                ool.amount                                                  AS refund_amount_fen,
                ool.extra->>'dish_name'                                     AS dish_name,
                ool.extra->>'dish_id'                                       AS dish_id,
                ool.extra->>'table_no'                                      AS table_no,
                ool.reason                                                  AS refund_reason,
                ool.operated_by,
                emp.employee_name                                           AS operator_name,
                ool.operated_at                                             AS refunded_at
            FROM order_operations_log ool
            LEFT JOIN employees emp
                   ON emp.id::text = ool.operated_by
                  AND emp.tenant_id = ool.tenant_id
                  AND emp.is_deleted = FALSE
            WHERE ool.tenant_id  = :tenant_id
              AND ool.store_id   = :store_id
              AND ool.op_type    = 'refund'
              AND DATE(ool.operated_at) BETWEEN :d_from AND :d_to
            ORDER BY ool.operated_at DESC
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "d_from": str(d_from),
            "d_to": str(d_to),
        },
    )
    items = [dict(r) for r in rows.mappings()]
    total_refund_amount_fen = sum(r.get("refund_amount_fen") or 0 for r in items)

    if format == "csv":
        return _csv_response(items, f"refunds_{d_from}_{d_to}.csv")
    return _ok({"total_count": len(items), "total_refund_amount_fen": total_refund_amount_fen, "items": items})


# ──────────────────────────────────────────────
# 13. 特殊操作日汇总
# ──────────────────────────────────────────────


@router.get("/summary")
async def api_special_ops_summary(
    store_id: Optional[str] = Query(None, description="门店ID"),
    date: Optional[str] = Query(None, description="业务日期 YYYY-MM-DD，默认今日"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """特殊操作日汇总 — 当日各类特殊操作次数/金额汇总

    查询逻辑：
      一次聚合查询，按 op_type 汇总 order_operations_log 中当日所有操作的次数和金额。
      使用 FILTER 子句实现多类型并行统计，避免多次查询。
    """
    tenant_id = _require_tenant(x_tenant_id)
    _require_store(store_id)
    target_date = _parse_date(date)

    row = await db.execute(
        text(
            """
            SELECT
                COUNT(*) FILTER (WHERE op_type = 'gift')          AS gifts_count,
                COALESCE(SUM(amount) FILTER (WHERE op_type = 'gift'), 0)
                                                                   AS gifts_amount_fen,
                COUNT(*) FILTER (WHERE op_type = 'price_change')   AS price_changes_count,
                COALESCE(SUM(amount) FILTER (WHERE op_type = 'price_change'), 0)
                                                                   AS price_changes_diff_fen,
                COUNT(*) FILTER (WHERE op_type = 'void')           AS voids_count,
                COALESCE(SUM(amount) FILTER (WHERE op_type = 'void'), 0)
                                                                   AS voids_amount_fen,
                COUNT(*) FILTER (WHERE op_type = 'estimate')       AS estimates_count,
                COUNT(*) FILTER (WHERE op_type = 'rush')           AS rush_orders_count,
                COUNT(*) FILTER (WHERE op_type = 'limit')          AS limits_count,
                COUNT(*) FILTER (WHERE op_type = 'cleanup')        AS cleanups_count,
                COALESCE(SUM(amount) FILTER (WHERE op_type = 'cleanup'), 0)
                                                                   AS cleanups_amount_fen,
                COUNT(*) FILTER (WHERE op_type = 'transfer')       AS transfers_count,
                COUNT(*) FILTER (WHERE op_type = 'split')          AS splits_count,
                COUNT(*) FILTER (WHERE op_type = 'merge')          AS merges_count,
                COUNT(*) FILTER (WHERE op_type = 'discount')       AS discounts_count,
                COALESCE(SUM(amount) FILTER (WHERE op_type = 'discount'), 0)
                                                                   AS discounts_amount_fen,
                COUNT(*) FILTER (WHERE op_type = 'refund')         AS refunds_count,
                COALESCE(SUM(amount) FILTER (WHERE op_type = 'refund'), 0)
                                                                   AS refunds_amount_fen
            FROM order_operations_log
            WHERE tenant_id  = :tenant_id
              AND store_id   = :store_id
              AND DATE(operated_at) = :target_date
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "target_date": str(target_date),
        },
    )
    r = row.mappings().first()

    data = {
        "date": str(target_date),
        "gifts_count": int(r["gifts_count"] or 0) if r else 0,
        "gifts_amount_fen": int(r["gifts_amount_fen"] or 0) if r else 0,
        "price_changes_count": int(r["price_changes_count"] or 0) if r else 0,
        "price_changes_diff_fen": int(r["price_changes_diff_fen"] or 0) if r else 0,
        "voids_count": int(r["voids_count"] or 0) if r else 0,
        "voids_amount_fen": int(r["voids_amount_fen"] or 0) if r else 0,
        "estimates_count": int(r["estimates_count"] or 0) if r else 0,
        "rush_orders_count": int(r["rush_orders_count"] or 0) if r else 0,
        "limits_count": int(r["limits_count"] or 0) if r else 0,
        "cleanups_count": int(r["cleanups_count"] or 0) if r else 0,
        "cleanups_amount_fen": int(r["cleanups_amount_fen"] or 0) if r else 0,
        "transfers_count": int(r["transfers_count"] or 0) if r else 0,
        "splits_count": int(r["splits_count"] or 0) if r else 0,
        "merges_count": int(r["merges_count"] or 0) if r else 0,
        "discounts_count": int(r["discounts_count"] or 0) if r else 0,
        "discounts_amount_fen": int(r["discounts_amount_fen"] or 0) if r else 0,
        "refunds_count": int(r["refunds_count"] or 0) if r else 0,
        "refunds_amount_fen": int(r["refunds_amount_fen"] or 0) if r else 0,
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
    gift_threshold: int = Query(5, description="赠菜次数预警阈值（超过则触发）"),
    void_threshold: int = Query(3, description="废单次数预警阈值"),
    price_change_threshold: int = Query(10, description="变价次数预警阈值"),
    format: Optional[str] = Query(None, description="format=csv 返回CSV文件"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """风险预警 — 识别特殊操作异常频率操作人，辅助稽核管控

    预警规则：
    - 同一操作人同日赠菜次数 > gift_threshold（默认 5）
    - 同一操作人同日废单次数 > void_threshold（默认 3）
    - 同一操作人同日变价次数 > price_change_threshold（默认 10）

    风险等级：
    - 触发任意一条阈值：medium
    - 触发两条或以上：high
    - 单日赠菜金额 > 5000元 或 废单金额 > 10000元：high（覆盖）

    查询逻辑：
      按 (operated_by, op_type, DATE(operated_at)) 分组统计频次和金额，
      HAVING 过滤触发阈值的记录，LEFT JOIN employees 获取操作人姓名。
    """
    tenant_id = _require_tenant(x_tenant_id)
    _require_store(store_id)
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    rows = await db.execute(
        text(
            """
            WITH operator_daily AS (
                SELECT
                    ool.operated_by,
                    DATE(ool.operated_at)                        AS op_date,
                    ool.op_type,
                    COUNT(*)                                     AS op_count,
                    COALESCE(SUM(ABS(ool.amount)), 0)            AS total_amount_fen
                FROM order_operations_log ool
                WHERE ool.tenant_id  = :tenant_id
                  AND ool.store_id   = :store_id
                  AND ool.op_type    IN ('gift', 'void', 'price_change')
                  AND DATE(ool.operated_at) BETWEEN :d_from AND :d_to
                GROUP BY ool.operated_by, DATE(ool.operated_at), ool.op_type
            ),
            flagged AS (
                SELECT
                    od.operated_by,
                    od.op_date,
                    od.op_type                                   AS risk_type,
                    od.op_count,
                    od.total_amount_fen,
                    CASE
                        WHEN od.op_type = 'gift'
                             AND (od.op_count > :gift_threshold
                                  OR od.total_amount_fen > 500000) THEN TRUE
                        WHEN od.op_type = 'void'
                             AND (od.op_count > :void_threshold
                                  OR od.total_amount_fen > 1000000) THEN TRUE
                        WHEN od.op_type = 'price_change'
                             AND od.op_count > :price_change_threshold   THEN TRUE
                        ELSE FALSE
                    END                                          AS is_flagged
                FROM operator_daily od
            )
            SELECT
                f.operated_by                                    AS operator_id,
                emp.employee_name                                AS operator_name,
                f.op_date,
                f.risk_type,
                f.op_count,
                f.total_amount_fen,
                -- 风险等级: 单条超阈值=medium, 金额超限=high
                CASE
                    WHEN (f.op_type = 'gift' AND f.total_amount_fen > 500000)
                      OR (f.op_type = 'void' AND f.total_amount_fen > 1000000) THEN 'high'
                    ELSE 'medium'
                END                                              AS risk_level
            FROM flagged f
            LEFT JOIN employees emp
                   ON emp.id::text = f.operated_by
                  AND emp.tenant_id = :tenant_id
                  AND emp.is_deleted = FALSE
            WHERE f.is_flagged = TRUE
            ORDER BY f.op_date DESC, f.total_amount_fen DESC
            """
        ),
        {
            "tenant_id": tenant_id,
            "store_id": store_id,
            "d_from": str(d_from),
            "d_to": str(d_to),
            "gift_threshold": gift_threshold,
            "void_threshold": void_threshold,
            "price_change_threshold": price_change_threshold,
        },
    )
    items = [dict(r) for r in rows.mappings()]

    if format == "csv":
        return _csv_response(items, f"risk_alert_{d_from}_{d_to}.csv")
    return _ok({"alert_count": len(items), "items": items})
