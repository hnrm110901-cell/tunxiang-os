"""薪资管理路由 — 接入真实 DB（payroll_records / payroll_configs 表）

端点列表（prefix=/api/v1/finance/payroll）：
  GET    /summary                    — 本月薪资汇总（headcount/应发/已发/待审批）
  GET    /records                    — 薪资单列表（分页，支持多维过滤）
  GET    /records/{record_id}        — 薪资单详情（含明细行）
  POST   /records                    — 创建草稿薪资单（存入 payroll_records）
  PATCH  /records/{record_id}/approve — 审批通过（draft → approved）
  PATCH  /records/{record_id}/mark-paid — 标记已发（approved → paid）
  GET    /configs                    — 查询薪资方案配置（payroll_configs）
  POST   /configs                    — 新建或更新薪资方案配置
  GET    /history                    — 近6个月发薪历史汇总

DB 失败时：列表类端点返回空集合（graceful fallback），写操作返回 503。
所有接口需 X-Tenant-ID header。

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/finance/payroll", tags=["payroll"])


# ── 辅助 ─────────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data, "error": None}


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _row_to_dict(row: Any) -> dict[str, Any]:
    """将 SQLAlchemy mapping 行转换为 JSON 可序列化字典。"""
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif hasattr(v, "__str__") and type(v).__name__ == "UUID":
            d[k] = str(v)
    return d


# ── 请求模型 ─────────────────────────────────────────────────────────────────


class CreateRecordRequest(BaseModel):
    store_id: str
    employee_id: str
    pay_period_start: date
    pay_period_end: date
    base_pay_fen: int = 0
    overtime_pay_fen: int = 0
    commission_fen: int = 0
    piecework_pay_fen: int = 0
    kpi_bonus_fen: int = 0
    deduction_fen: int = 0
    tax_fen: int = 0
    notes: Optional[str] = None
    calc_snapshot: Optional[dict] = None


class UpsertConfigRequest(BaseModel):
    store_id: Optional[str] = None
    employee_role: str
    salary_type: str = "monthly"
    base_salary_fen: Optional[int] = None
    hourly_rate_fen: Optional[int] = None
    commission_type: str = "none"
    commission_rate: Optional[float] = None
    commission_base: Optional[str] = None
    kpi_bonus_max_fen: int = 0
    effective_from: date = date.today()
    effective_to: Optional[date] = None


# ── 薪资汇总 ─────────────────────────────────────────────────────────────────


@router.get("/summary")
async def get_payroll_summary(
    request: Request,
    month: str = Query("2026-03", description="格式 YYYY-MM"),
    store_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GET /api/v1/finance/payroll/summary — 月度薪资汇总"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    # 将 YYYY-MM 转换为日期范围
    try:
        year, month_num = int(month[:4]), int(month[5:7])
        period_start = date(year, month_num, 1)
        # 月末计算
        if month_num == 12:
            period_end = date(year + 1, 1, 1)
        else:
            period_end = date(year, month_num + 1, 1)
    except (ValueError, IndexError) as exc:
        raise HTTPException(status_code=400, detail=f"month 格式错误，应为 YYYY-MM，收到: {month}") from exc

    conditions = [
        "tenant_id = :tid::uuid",
        "pay_period_start >= :period_start",
        "pay_period_start < :period_end",
        "is_deleted = FALSE",
    ]
    params: dict[str, Any] = {
        "tid": tenant_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    if store_id:
        conditions.append("store_id = :store_id::uuid")
        params["store_id"] = store_id

    where_clause = " AND ".join(conditions)

    try:
        result = await db.execute(
            text(
                f"SELECT "
                f"  COUNT(*) AS headcount, "
                f"  COALESCE(SUM(gross_pay_fen), 0) AS gross_total, "
                f"  COALESCE(SUM(CASE WHEN status = 'paid' THEN net_pay_fen ELSE 0 END), 0) AS paid_total, "
                f"  COUNT(CASE WHEN status = 'draft' THEN 1 END) AS pending_approval "
                f"FROM payroll_records "
                f"WHERE {where_clause}"
            ),
            params,
        )
        row = result.mappings().first()
    except SQLAlchemyError as exc:
        log.error("payroll_summary_db_error", error=str(exc), exc_info=True)
        # graceful fallback
        return _ok(
            {
                "month": month,
                "headcount": 0,
                "gross_total": 0,
                "paid_total": 0,
                "pending_approval": 0,
                "_db_error": True,
            }
        )

    return _ok(
        {
            "month": month,
            "headcount": int(row["headcount"] or 0),
            "gross_total": int(row["gross_total"] or 0),
            "paid_total": int(row["paid_total"] or 0),
            "pending_approval": int(row["pending_approval"] or 0),
        }
    )


# ── 薪资单列表 ───────────────────────────────────────────────────────────────


@router.get("/records")
async def list_payroll_records(
    request: Request,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    store_id: Optional[str] = Query(None),
    employee_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    month: Optional[str] = Query(None, description="格式 YYYY-MM"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GET /api/v1/finance/payroll/records — 分页查询薪资单列表"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    conditions = ["tenant_id = :tid::uuid", "is_deleted = FALSE"]
    params: dict[str, Any] = {"tid": tenant_id}

    if store_id:
        conditions.append("store_id = :store_id::uuid")
        params["store_id"] = store_id
    if employee_id:
        conditions.append("employee_id = :employee_id::uuid")
        params["employee_id"] = employee_id
    if status:
        conditions.append("status = :status")
        params["status"] = status
    if month:
        try:
            year, month_num = int(month[:4]), int(month[5:7])
            period_start = date(year, month_num, 1)
            period_end = date(year, month_num + 1, 1) if month_num < 12 else date(year + 1, 1, 1)
            conditions.append("pay_period_start >= :ps AND pay_period_start < :pe")
            params["ps"] = period_start
            params["pe"] = period_end
        except (ValueError, IndexError):
            pass  # 忽略格式错误，不过滤月份

    where_clause = " AND ".join(conditions)

    try:
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM payroll_records WHERE {where_clause}"),
            params,
        )
        total = count_result.scalar() or 0

        offset = (page - 1) * size
        params["limit"] = size
        params["offset"] = offset

        result = await db.execute(
            text(
                f"SELECT id, tenant_id, store_id, employee_id, "
                f"       pay_period_start, pay_period_end, "
                f"       base_pay_fen, overtime_pay_fen, commission_fen, "
                f"       piecework_pay_fen, kpi_bonus_fen, deduction_fen, "
                f"       gross_pay_fen, tax_fen, net_pay_fen, "
                f"       status, approved_by, approved_at, payment_method, notes, "
                f"       created_at, updated_at "
                f"FROM payroll_records "
                f"WHERE {where_clause} "
                f"ORDER BY pay_period_start DESC, created_at DESC "
                f"LIMIT :limit OFFSET :offset"
            ),
            params,
        )
        items = [_row_to_dict(r) for r in result.mappings().fetchall()]
    except SQLAlchemyError as exc:
        log.error("list_payroll_records_db_error", error=str(exc), exc_info=True)
        return _ok({"items": [], "total": 0, "_db_error": True})

    log.info("payroll_records_listed", tenant_id=tenant_id, total=total, page=page)
    return _ok({"items": items, "total": total, "page": page, "size": size})


# ── 薪资单详情 ───────────────────────────────────────────────────────────────


@router.get("/records/{record_id}")
async def get_payroll_record(
    record_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GET /api/v1/finance/payroll/records/{record_id} — 薪资单详情（含明细行）"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        result = await db.execute(
            text(
                "SELECT id, tenant_id, store_id, employee_id, "
                "       pay_period_start, pay_period_end, "
                "       base_pay_fen, overtime_pay_fen, commission_fen, "
                "       piecework_pay_fen, kpi_bonus_fen, deduction_fen, "
                "       gross_pay_fen, tax_fen, net_pay_fen, "
                "       status, approved_by, approved_at, payment_method, "
                "       notes, calc_snapshot, created_at, updated_at "
                "FROM payroll_records "
                "WHERE id = :record_id::uuid "
                "AND tenant_id = :tid::uuid "
                "AND is_deleted = FALSE"
            ),
            {"record_id": record_id, "tid": tenant_id},
        )
        record_row = result.mappings().first()
    except SQLAlchemyError as exc:
        log.error("get_payroll_record_db_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=503, detail="数据库服务暂时不可用") from exc

    if not record_row:
        raise HTTPException(status_code=404, detail=f"薪资单不存在: {record_id}")

    record = _row_to_dict(record_row)

    # 查询明细行
    try:
        lines_result = await db.execute(
            text(
                "SELECT id, item_type, item_name, amount_fen, quantity, unit_price_fen, notes "
                "FROM payroll_line_items "
                "WHERE record_id = :record_id::uuid "
                "AND tenant_id = :tid::uuid "
                "ORDER BY created_at ASC"
            ),
            {"record_id": record_id, "tid": tenant_id},
        )
        line_items = [_row_to_dict(r) for r in lines_result.mappings().fetchall()]
    except SQLAlchemyError:
        line_items = []

    record["line_items"] = line_items
    return _ok(record)


# ── 创建薪资单 ───────────────────────────────────────────────────────────────


@router.post("/records")
async def create_payroll_record(
    body: CreateRecordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """POST /api/v1/finance/payroll/records — 创建草稿薪资单"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    gross_pay_fen = (
        body.base_pay_fen
        + body.overtime_pay_fen
        + body.commission_fen
        + body.piecework_pay_fen
        + body.kpi_bonus_fen
        - body.deduction_fen
    )
    net_pay_fen = gross_pay_fen - body.tax_fen

    import json as _json

    snapshot_json = _json.dumps(body.calc_snapshot) if body.calc_snapshot else None

    try:
        result = await db.execute(
            text(
                "INSERT INTO payroll_records "
                "(tenant_id, store_id, employee_id, pay_period_start, pay_period_end, "
                " base_pay_fen, overtime_pay_fen, commission_fen, piecework_pay_fen, "
                " kpi_bonus_fen, deduction_fen, gross_pay_fen, tax_fen, net_pay_fen, "
                " status, notes, calc_snapshot) "
                "VALUES "
                "(:tid::uuid, :store_id::uuid, :employee_id::uuid, "
                " :pay_period_start, :pay_period_end, "
                " :base_pay_fen, :overtime_pay_fen, :commission_fen, :piecework_pay_fen, "
                " :kpi_bonus_fen, :deduction_fen, :gross_pay_fen, :tax_fen, :net_pay_fen, "
                " 'draft', :notes, :calc_snapshot::jsonb) "
                "RETURNING id, store_id, employee_id, pay_period_start, pay_period_end, "
                "          gross_pay_fen, net_pay_fen, status, created_at"
            ),
            {
                "tid": tenant_id,
                "store_id": body.store_id,
                "employee_id": body.employee_id,
                "pay_period_start": body.pay_period_start,
                "pay_period_end": body.pay_period_end,
                "base_pay_fen": body.base_pay_fen,
                "overtime_pay_fen": body.overtime_pay_fen,
                "commission_fen": body.commission_fen,
                "piecework_pay_fen": body.piecework_pay_fen,
                "kpi_bonus_fen": body.kpi_bonus_fen,
                "deduction_fen": body.deduction_fen,
                "gross_pay_fen": gross_pay_fen,
                "tax_fen": body.tax_fen,
                "net_pay_fen": net_pay_fen,
                "notes": body.notes,
                "calc_snapshot": snapshot_json,
            },
        )
        row = result.mappings().first()
        await db.commit()
    except SQLAlchemyError as exc:
        log.error("create_payroll_record_db_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=503, detail="数据库服务暂时不可用") from exc

    new_record = _row_to_dict(row)
    log.info(
        "payroll_record_created",
        tenant_id=tenant_id,
        record_id=new_record.get("id"),
        employee_id=body.employee_id,
    )
    return _ok(new_record)


# ── 审批薪资单 ───────────────────────────────────────────────────────────────


@router.patch("/records/{record_id}/approve")
async def approve_payroll_record(
    record_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """PATCH /api/v1/finance/payroll/records/{record_id}/approve — draft → approved"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        fetch_result = await db.execute(
            text(
                "SELECT id, status FROM payroll_records "
                "WHERE id = :record_id::uuid "
                "AND tenant_id = :tid::uuid "
                "AND is_deleted = FALSE"
            ),
            {"record_id": record_id, "tid": tenant_id},
        )
        row = fetch_result.mappings().first()
    except SQLAlchemyError as exc:
        log.error("approve_payroll_fetch_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=503, detail="数据库服务暂时不可用") from exc

    if not row:
        raise HTTPException(status_code=404, detail=f"薪资单不存在: {record_id}")
    if row["status"] != "draft":
        raise HTTPException(
            status_code=400,
            detail=f"薪资单当前状态为 {row['status']}，仅 draft 状态可审批",
        )

    try:
        update_result = await db.execute(
            text(
                "UPDATE payroll_records "
                "SET status = 'approved', approved_at = NOW(), updated_at = NOW() "
                "WHERE id = :record_id::uuid "
                "AND tenant_id = :tid::uuid "
                "RETURNING id, status, approved_at, updated_at"
            ),
            {"record_id": record_id, "tid": tenant_id},
        )
        updated_row = update_result.mappings().first()
        await db.commit()
    except SQLAlchemyError as exc:
        log.error("approve_payroll_update_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=503, detail="数据库服务暂时不可用") from exc

    result_dict = _row_to_dict(updated_row)
    log.info("payroll_record_approved", tenant_id=tenant_id, record_id=record_id)
    return _ok(result_dict)


# ── 标记已发 ─────────────────────────────────────────────────────────────────


@router.patch("/records/{record_id}/mark-paid")
async def mark_payroll_paid(
    record_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """PATCH /api/v1/finance/payroll/records/{record_id}/mark-paid — approved → paid"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        fetch_result = await db.execute(
            text(
                "SELECT id, status FROM payroll_records "
                "WHERE id = :record_id::uuid "
                "AND tenant_id = :tid::uuid "
                "AND is_deleted = FALSE"
            ),
            {"record_id": record_id, "tid": tenant_id},
        )
        row = fetch_result.mappings().first()
    except SQLAlchemyError as exc:
        log.error("mark_paid_fetch_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=503, detail="数据库服务暂时不可用") from exc

    if not row:
        raise HTTPException(status_code=404, detail=f"薪资单不存在: {record_id}")
    if row["status"] != "approved":
        raise HTTPException(
            status_code=400,
            detail=f"薪资单当前状态为 {row['status']}，仅 approved 状态可标记已发",
        )

    try:
        update_result = await db.execute(
            text(
                "UPDATE payroll_records "
                "SET status = 'paid', payment_method = 'bank', updated_at = NOW() "
                "WHERE id = :record_id::uuid "
                "AND tenant_id = :tid::uuid "
                "RETURNING id, status, payment_method, updated_at"
            ),
            {"record_id": record_id, "tid": tenant_id},
        )
        updated_row = update_result.mappings().first()
        await db.commit()
    except SQLAlchemyError as exc:
        log.error("mark_paid_update_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=503, detail="数据库服务暂时不可用") from exc

    result_dict = _row_to_dict(updated_row)
    log.info("payroll_record_paid", tenant_id=tenant_id, record_id=record_id)
    return _ok(result_dict)


# ── 薪资方案配置 ─────────────────────────────────────────────────────────────


@router.get("/configs")
async def list_payroll_configs(
    request: Request,
    store_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GET /api/v1/finance/payroll/configs — 查询薪资方案配置列表"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    conditions = ["tenant_id = :tid::uuid", "is_deleted = FALSE", "is_active = TRUE"]
    params: dict[str, Any] = {"tid": tenant_id}

    if store_id:
        conditions.append("(store_id = :store_id::uuid OR store_id IS NULL)")
        params["store_id"] = store_id

    where_clause = " AND ".join(conditions)

    try:
        result = await db.execute(
            text(
                f"SELECT id, tenant_id, store_id, employee_role, salary_type, "
                f"       base_salary_fen, hourly_rate_fen, commission_type, commission_rate, "
                f"       commission_base, kpi_bonus_max_fen, effective_from, effective_to, "
                f"       is_active, created_at, updated_at "
                f"FROM payroll_configs "
                f"WHERE {where_clause} "
                f"ORDER BY employee_role ASC, effective_from DESC"
            ),
            params,
        )
        items = [_row_to_dict(r) for r in result.mappings().fetchall()]
    except SQLAlchemyError as exc:
        log.error("list_payroll_configs_db_error", error=str(exc), exc_info=True)
        return _ok({"items": [], "total": 0, "_db_error": True})

    return _ok({"items": items, "total": len(items)})


@router.post("/configs")
async def upsert_payroll_config(
    body: UpsertConfigRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """POST /api/v1/finance/payroll/configs — 新建或更新薪资方案配置"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        # 先停用同角色旧方案（同 store_id + employee_role）
        await db.execute(
            text(
                "UPDATE payroll_configs "
                "SET is_active = FALSE, updated_at = NOW() "
                "WHERE tenant_id = :tid::uuid "
                "AND employee_role = :employee_role "
                "AND store_id IS NOT DISTINCT FROM :store_id "
                "AND is_active = TRUE "
                "AND is_deleted = FALSE"
            ),
            {
                "tid": tenant_id,
                "employee_role": body.employee_role,
                "store_id": body.store_id,
            },
        )

        # 插入新方案
        result = await db.execute(
            text(
                "INSERT INTO payroll_configs "
                "(tenant_id, store_id, employee_role, salary_type, "
                " base_salary_fen, hourly_rate_fen, commission_type, commission_rate, "
                " commission_base, kpi_bonus_max_fen, effective_from, effective_to, is_active) "
                "VALUES "
                "(:tid::uuid, :store_id, :employee_role, :salary_type, "
                " :base_salary_fen, :hourly_rate_fen, :commission_type, :commission_rate, "
                " :commission_base, :kpi_bonus_max_fen, :effective_from, :effective_to, TRUE) "
                "RETURNING id, employee_role, salary_type, base_salary_fen, hourly_rate_fen, "
                "          commission_type, kpi_bonus_max_fen, effective_from, is_active, created_at"
            ),
            {
                "tid": tenant_id,
                "store_id": body.store_id,
                "employee_role": body.employee_role,
                "salary_type": body.salary_type,
                "base_salary_fen": body.base_salary_fen,
                "hourly_rate_fen": body.hourly_rate_fen,
                "commission_type": body.commission_type,
                "commission_rate": body.commission_rate,
                "commission_base": body.commission_base,
                "kpi_bonus_max_fen": body.kpi_bonus_max_fen,
                "effective_from": body.effective_from,
                "effective_to": body.effective_to,
            },
        )
        row = result.mappings().first()
        await db.commit()
    except SQLAlchemyError as exc:
        log.error("upsert_payroll_config_db_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=503, detail="数据库服务暂时不可用") from exc

    config = _row_to_dict(row)
    log.info(
        "payroll_config_upserted",
        tenant_id=tenant_id,
        config_id=config.get("id"),
        employee_role=body.employee_role,
    )
    return _ok(config)


# ── 发薪历史（近6个月汇总）───────────────────────────────────────────────────


@router.get("/history")
async def get_payroll_history(
    request: Request,
    store_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GET /api/v1/finance/payroll/history — 近6个月发薪历史（按月汇总）"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    conditions = [
        "tenant_id = :tid::uuid",
        "is_deleted = FALSE",
        "pay_period_start >= NOW() - INTERVAL '6 months'",
    ]
    params: dict[str, Any] = {"tid": tenant_id}

    if store_id:
        conditions.append("store_id = :store_id::uuid")
        params["store_id"] = store_id

    where_clause = " AND ".join(conditions)

    try:
        result = await db.execute(
            text(
                f"SELECT "
                f"  TO_CHAR(DATE_TRUNC('month', pay_period_start), 'YYYY-MM') AS month, "
                f"  COUNT(DISTINCT employee_id) AS headcount, "
                f"  COALESCE(SUM(gross_pay_fen), 0) AS gross_pay, "
                f"  COALESCE(SUM(net_pay_fen), 0) AS net_pay, "
                f"  CASE WHEN COUNT(*) FILTER (WHERE status NOT IN ('paid', 'voided')) = 0 "
                f"       THEN 'settled' ELSE 'in_progress' END AS status "
                f"FROM payroll_records "
                f"WHERE {where_clause} "
                f"GROUP BY DATE_TRUNC('month', pay_period_start) "
                f"ORDER BY DATE_TRUNC('month', pay_period_start) ASC"
            ),
            params,
        )
        items = [_row_to_dict(r) for r in result.mappings().fetchall()]
    except SQLAlchemyError as exc:
        log.error("payroll_history_db_error", error=str(exc), exc_info=True)
        return _ok({"items": [], "total": 0, "_db_error": True})

    return _ok({"items": items, "total": len(items)})
