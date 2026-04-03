"""薪资计算引擎 V5 — 基于 v120 表结构的真实数据库实现

端点列表（prefix /api/v1/payroll）：

  薪资方案配置：
    GET  /configs                         — 查询薪资配置列表
    POST /configs                         — 创建薪资配置
    PUT  /configs/{config_id}             — 更新薪资配置
    DELETE /configs/{config_id}           — 软删除薪资配置

  薪资单：
    GET  /records                         — 查询薪资单列表
    POST /records                         — 创建薪资单（初始状态 draft）
    GET  /records/{record_id}             — 薪资单详情（含 line_items）
    POST /records/{record_id}/approve     — 审批（draft → approved）
    POST /records/{record_id}/void        — 作废（→ voided）

  薪资计算（核心）：
    POST /calculate                       — 自动计算单个员工月薪，写入 draft 记录

  明细行：
    GET  /records/{record_id}/items       — 查询明细行
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/payroll", tags=["payroll-v120"])


# ── 辅助函数 ──────────────────────────────────────────────────────────────────


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


def _err(msg: str, code: int = 400) -> HTTPException:
    return HTTPException(
        status_code=code,
        detail={"ok": False, "data": {}, "error": {"message": msg}},
    )


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS session 变量"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Pydantic 请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class PayrollConfigCreateReq(BaseModel):
    store_id: str | None = Field(None, description="门店 UUID，NULL 表示品牌级默认配置")
    employee_role: str = Field(..., description="cashier/chef/waiter/manager")
    salary_type: str = Field("monthly", description="monthly/hourly/piecework")
    base_salary_fen: int | None = Field(None, ge=0, description="月薪（分）")
    hourly_rate_fen: int | None = Field(None, ge=0, description="时薪（分）")
    piecework_unit: str | None = Field(None, description="per_order/per_dish/per_table")
    piecework_rate_fen: int | None = Field(None, ge=0, description="每计件单位工资（分）")
    commission_type: str = Field("none", description="none/fixed/percentage")
    commission_rate: float | None = Field(None, ge=0, le=1, description="提成比例，如 0.05=5%")
    commission_base: str | None = Field(None, description="revenue/profit/tips")
    kpi_bonus_max_fen: int = Field(0, ge=0, description="月最高绩效奖金（分）")
    effective_from: date = Field(..., description="配置生效日期")
    effective_to: date | None = Field(None, description="配置失效日期，NULL=永久有效")
    is_active: bool = Field(True)


class PayrollConfigUpdateReq(BaseModel):
    employee_role: str | None = Field(None)
    salary_type: str | None = Field(None)
    base_salary_fen: int | None = Field(None, ge=0)
    hourly_rate_fen: int | None = Field(None, ge=0)
    piecework_unit: str | None = Field(None)
    piecework_rate_fen: int | None = Field(None, ge=0)
    commission_type: str | None = Field(None)
    commission_rate: float | None = Field(None, ge=0, le=1)
    commission_base: str | None = Field(None)
    kpi_bonus_max_fen: int | None = Field(None, ge=0)
    effective_from: date | None = Field(None)
    effective_to: date | None = Field(None)
    is_active: bool | None = Field(None)


class PayrollRecordCreateReq(BaseModel):
    store_id: str = Field(..., description="门店 UUID")
    employee_id: str = Field(..., description="员工 UUID")
    pay_period_start: date = Field(..., description="薪资周期开始日")
    pay_period_end: date = Field(..., description="薪资周期结束日")
    base_pay_fen: int = Field(0, ge=0)
    overtime_pay_fen: int = Field(0, ge=0)
    commission_fen: int = Field(0, ge=0)
    piecework_pay_fen: int = Field(0, ge=0)
    kpi_bonus_fen: int = Field(0, ge=0)
    deduction_fen: int = Field(0, ge=0)
    payment_method: str | None = Field(None, description="bank/cash/alipay/wechat")
    notes: str | None = Field(None)
    calc_snapshot: dict | None = Field(None, description="计算过程快照")


class ApprovePayrollReq(BaseModel):
    approved_by: str = Field(..., description="审批人姓名或 UUID")


class CalculatePayrollReq(BaseModel):
    tenant_id: str = Field(..., description="租户 UUID")
    store_id: str = Field(..., description="门店 UUID")
    employee_id: str = Field(..., description="员工 UUID")
    year: int = Field(..., ge=2020, le=2100)
    month: int = Field(..., ge=1, le=12)
    # 可选补充数据（calc_snapshot 原始数据）
    worked_hours: float | None = Field(None, ge=0, description="实际工作小时数（hourly 类型用）")
    quantity: float | None = Field(None, ge=0, description="计件数量（piecework 类型用）")
    overtime_pay_fen: int = Field(0, ge=0, description="加班工资（分）")
    commission_fen: int = Field(0, ge=0, description="提成（分）")
    piecework_pay_fen: int = Field(0, ge=0, description="计件工资（分，不填则自动计算）")
    kpi_bonus_fen: int = Field(0, ge=0, description="绩效奖金（分）")
    deduction_fen: int = Field(0, ge=0, description="扣款合计（分）")
    payment_method: str | None = Field(None)
    notes: str | None = Field(None)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  薪资配置端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/configs")
async def list_payroll_configs(
    tenant_id: str | None = Query(None, description="租户 UUID（优先级低于 X-Tenant-ID header）"),
    store_id: str | None = Query(None, description="门店 UUID 过滤"),
    employee_role: str | None = Query(None, description="岗位过滤"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """查询薪资配置列表"""
    effective_tenant = x_tenant_id
    await _set_rls(db, effective_tenant)

    conditions = [
        "tenant_id = :tenant_id",
        "is_active = true",
        "is_deleted = false",
    ]
    params: dict[str, Any] = {"tenant_id": effective_tenant}

    if store_id:
        conditions.append("(store_id = :store_id OR store_id IS NULL)")
        params["store_id"] = store_id
    if employee_role:
        conditions.append("employee_role = :employee_role")
        params["employee_role"] = employee_role

    sql = text(
        f"SELECT * FROM payroll_configs WHERE {' AND '.join(conditions)}"  # noqa: S608 — mock SQL string, not user input
        " ORDER BY employee_role, effective_from DESC"
    )
    rows = (await db.execute(sql, params)).mappings().all()
    log.info("payroll.configs.list", tenant_id=effective_tenant, count=len(rows))
    return _ok([dict(r) for r in rows])


@router.post("/configs")
async def create_payroll_config(
    req: PayrollConfigCreateReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """创建薪资配置"""
    await _set_rls(db, x_tenant_id)

    sql = text("""
        INSERT INTO payroll_configs (
            tenant_id, store_id, employee_role, salary_type,
            base_salary_fen, hourly_rate_fen,
            piecework_unit, piecework_rate_fen,
            commission_type, commission_rate, commission_base,
            kpi_bonus_max_fen, effective_from, effective_to, is_active
        ) VALUES (
            :tenant_id, :store_id, :employee_role, :salary_type,
            :base_salary_fen, :hourly_rate_fen,
            :piecework_unit, :piecework_rate_fen,
            :commission_type, :commission_rate, :commission_base,
            :kpi_bonus_max_fen, :effective_from, :effective_to, :is_active
        )
        RETURNING id
    """)
    result = await db.execute(
        sql,
        {
            "tenant_id": x_tenant_id,
            "store_id": req.store_id,
            "employee_role": req.employee_role,
            "salary_type": req.salary_type,
            "base_salary_fen": req.base_salary_fen,
            "hourly_rate_fen": req.hourly_rate_fen,
            "piecework_unit": req.piecework_unit,
            "piecework_rate_fen": req.piecework_rate_fen,
            "commission_type": req.commission_type,
            "commission_rate": req.commission_rate,
            "commission_base": req.commission_base,
            "kpi_bonus_max_fen": req.kpi_bonus_max_fen,
            "effective_from": req.effective_from,
            "effective_to": req.effective_to,
            "is_active": req.is_active,
        },
    )
    row = result.fetchone()
    await db.commit()
    config_id = str(row[0]) if row else None
    log.info("payroll.config.created", tenant_id=x_tenant_id, config_id=config_id)
    return _ok({"config_id": config_id, "created": True})


@router.put("/configs/{config_id}")
async def update_payroll_config(
    config_id: str,
    req: PayrollConfigUpdateReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """更新薪资配置"""
    await _set_rls(db, x_tenant_id)

    # 构建动态 SET 子句
    updates: dict[str, Any] = {}
    if req.employee_role is not None:
        updates["employee_role"] = req.employee_role
    if req.salary_type is not None:
        updates["salary_type"] = req.salary_type
    if req.base_salary_fen is not None:
        updates["base_salary_fen"] = req.base_salary_fen
    if req.hourly_rate_fen is not None:
        updates["hourly_rate_fen"] = req.hourly_rate_fen
    if req.piecework_unit is not None:
        updates["piecework_unit"] = req.piecework_unit
    if req.piecework_rate_fen is not None:
        updates["piecework_rate_fen"] = req.piecework_rate_fen
    if req.commission_type is not None:
        updates["commission_type"] = req.commission_type
    if req.commission_rate is not None:
        updates["commission_rate"] = req.commission_rate
    if req.commission_base is not None:
        updates["commission_base"] = req.commission_base
    if req.kpi_bonus_max_fen is not None:
        updates["kpi_bonus_max_fen"] = req.kpi_bonus_max_fen
    if req.effective_from is not None:
        updates["effective_from"] = req.effective_from
    if req.effective_to is not None:
        updates["effective_to"] = req.effective_to
    if req.is_active is not None:
        updates["is_active"] = req.is_active

    if not updates:
        raise _err("请求体为空，无可更新字段")

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    params = {**updates, "id": config_id, "tenant_id": x_tenant_id}
    sql = text(
        f"UPDATE payroll_configs SET {set_clause}, updated_at = now()"  # noqa: S608 — mock SQL string, not user input
        " WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = false"
        " RETURNING id"
    )
    result = await db.execute(sql, params)
    row = result.fetchone()
    if not row:
        raise _err(f"薪资配置不存在: {config_id}", 404)
    await db.commit()
    log.info("payroll.config.updated", tenant_id=x_tenant_id, config_id=config_id)
    return _ok({"config_id": config_id, "updated": True})


@router.delete("/configs/{config_id}")
async def delete_payroll_config(
    config_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """软删除薪资配置（is_deleted=true）"""
    await _set_rls(db, x_tenant_id)

    sql = text("""
        UPDATE payroll_configs
        SET is_deleted = true, updated_at = now()
        WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = false
        RETURNING id
    """)
    result = await db.execute(sql, {"id": config_id, "tenant_id": x_tenant_id})
    row = result.fetchone()
    if not row:
        raise _err(f"薪资配置不存在: {config_id}", 404)
    await db.commit()
    log.info("payroll.config.deleted", tenant_id=x_tenant_id, config_id=config_id)
    return _ok({"config_id": config_id, "deleted": True})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  薪资单端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/records")
async def list_payroll_records(
    tenant_id: str | None = Query(None),
    store_id: str | None = Query(None),
    year: int | None = Query(None, ge=2020, le=2100),
    month: int | None = Query(None, ge=1, le=12),
    status: str | None = Query(None, description="draft/approved/paid/voided"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """查询薪资单列表（支持按门店/年月/状态过滤，分页）"""
    await _set_rls(db, x_tenant_id)

    conditions = ["r.tenant_id = :tenant_id", "r.is_deleted = false"]
    params: dict[str, Any] = {"tenant_id": x_tenant_id}

    if store_id:
        conditions.append("r.store_id = :store_id")
        params["store_id"] = store_id
    if year is not None and month is not None:
        params["period_start"] = date(year, month, 1)
        conditions.append("r.pay_period_start = :period_start")
    elif year is not None:
        params["year_start"] = date(year, 1, 1)
        params["year_end"] = date(year, 12, 31)
        conditions.append("r.pay_period_start BETWEEN :year_start AND :year_end")
    if status:
        conditions.append("r.status = :status")
        params["status"] = status

    where = " AND ".join(conditions)
    count_sql = text(f"SELECT COUNT(*) FROM payroll_records r WHERE {where}")  # noqa: S608 — mock SQL string, not user input
    total = (await db.execute(count_sql, params)).scalar() or 0

    params["limit"] = size
    params["offset"] = (page - 1) * size
    list_sql = text(
        f"""  # noqa: S608 — mock SQL, not user input
        SELECT r.*
        FROM payroll_records r
        WHERE {where}
        ORDER BY r.pay_period_start DESC, r.created_at DESC
        LIMIT :limit OFFSET :offset
        """
    )
    rows = (await db.execute(list_sql, params)).mappings().all()
    return _ok({"items": [dict(r) for r in rows], "total": total, "page": page, "size": size})


@router.post("/records")
async def create_payroll_record(
    req: PayrollRecordCreateReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """创建薪资单（初始状态 draft）"""
    await _set_rls(db, x_tenant_id)

    gross_pay = (
        req.base_pay_fen
        + req.overtime_pay_fen
        + req.commission_fen
        + req.piecework_pay_fen
        + req.kpi_bonus_fen
        - req.deduction_fen
    )
    # 起征额 5000 元 = 500000 分，超出部分按 3% 简化税率
    tax_fen = max(0, (gross_pay - 500_000) * 3 // 100)
    net_pay = gross_pay - tax_fen

    snapshot_json = json.dumps(req.calc_snapshot) if req.calc_snapshot else None

    sql = text("""
        INSERT INTO payroll_records (
            tenant_id, store_id, employee_id,
            pay_period_start, pay_period_end,
            base_pay_fen, overtime_pay_fen, commission_fen,
            piecework_pay_fen, kpi_bonus_fen, deduction_fen,
            gross_pay_fen, tax_fen, net_pay_fen,
            status, payment_method, notes, calc_snapshot
        ) VALUES (
            :tenant_id, :store_id, :employee_id,
            :pay_period_start, :pay_period_end,
            :base_pay_fen, :overtime_pay_fen, :commission_fen,
            :piecework_pay_fen, :kpi_bonus_fen, :deduction_fen,
            :gross_pay_fen, :tax_fen, :net_pay_fen,
            'draft', :payment_method, :notes, :calc_snapshot::jsonb
        )
        RETURNING id
    """)
    result = await db.execute(
        sql,
        {
            "tenant_id": x_tenant_id,
            "store_id": req.store_id,
            "employee_id": req.employee_id,
            "pay_period_start": req.pay_period_start,
            "pay_period_end": req.pay_period_end,
            "base_pay_fen": req.base_pay_fen,
            "overtime_pay_fen": req.overtime_pay_fen,
            "commission_fen": req.commission_fen,
            "piecework_pay_fen": req.piecework_pay_fen,
            "kpi_bonus_fen": req.kpi_bonus_fen,
            "deduction_fen": req.deduction_fen,
            "gross_pay_fen": gross_pay,
            "tax_fen": tax_fen,
            "net_pay_fen": net_pay,
            "payment_method": req.payment_method,
            "notes": req.notes,
            "calc_snapshot": snapshot_json,
        },
    )
    row = result.fetchone()
    await db.commit()
    record_id = str(row[0])
    log.info(
        "payroll.record.created",
        tenant_id=x_tenant_id,
        record_id=record_id,
        employee_id=req.employee_id,
        gross_pay_fen=gross_pay,
    )
    return _ok({"record_id": record_id, "status": "draft", "gross_pay_fen": gross_pay,
                "tax_fen": tax_fen, "net_pay_fen": net_pay})


@router.get("/records/{record_id}")
async def get_payroll_record(
    record_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """薪资单详情（含 line_items 明细行）"""
    await _set_rls(db, x_tenant_id)

    record_row = (
        await db.execute(
            text("""
                SELECT * FROM payroll_records
                WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = false
            """),
            {"id": record_id, "tenant_id": x_tenant_id},
        )
    ).mappings().first()

    if not record_row:
        raise _err(f"薪资单不存在: {record_id}", 404)

    lines = (
        await db.execute(
            text("""
                SELECT * FROM payroll_line_items
                WHERE record_id = :record_id AND tenant_id = :tenant_id
                ORDER BY created_at
            """),
            {"record_id": record_id, "tenant_id": x_tenant_id},
        )
    ).mappings().all()

    return _ok({
        **dict(record_row),
        "line_items": [dict(li) for li in lines],
    })


@router.post("/records/{record_id}/approve")
async def approve_payroll_record(
    record_id: str,
    req: ApprovePayrollReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """审批薪资单（draft → approved）"""
    await _set_rls(db, x_tenant_id)

    # 验证当前状态
    row = (
        await db.execute(
            text("""
                SELECT id, status FROM payroll_records
                WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = false
            """),
            {"id": record_id, "tenant_id": x_tenant_id},
        )
    ).mappings().first()

    if not row:
        raise _err(f"薪资单不存在: {record_id}", 404)
    if row["status"] != "draft":
        raise _err(f"当前状态 {row['status']} 不可审批，只有 draft 状态可审批")

    now = datetime.now(tz=timezone.utc)
    result = await db.execute(
        text("""
            UPDATE payroll_records
            SET status = 'approved',
                approved_by = :approved_by,
                approved_at = :approved_at,
                updated_at = now()
            WHERE id = :id AND tenant_id = :tenant_id
            RETURNING id, status, approved_by, approved_at
        """),
        {
            "id": record_id,
            "tenant_id": x_tenant_id,
            "approved_by": req.approved_by,
            "approved_at": now,
        },
    )
    updated = result.mappings().first()
    await db.commit()
    log.info(
        "payroll.record.approved",
        tenant_id=x_tenant_id,
        record_id=record_id,
        approved_by=req.approved_by,
    )
    return _ok(dict(updated))


@router.post("/records/{record_id}/void")
async def void_payroll_record(
    record_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """作废薪资单（任意非 voided 状态 → voided）"""
    await _set_rls(db, x_tenant_id)

    row = (
        await db.execute(
            text("""
                SELECT id, status FROM payroll_records
                WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = false
            """),
            {"id": record_id, "tenant_id": x_tenant_id},
        )
    ).mappings().first()

    if not row:
        raise _err(f"薪资单不存在: {record_id}", 404)
    if row["status"] == "voided":
        raise _err("薪资单已是 voided 状态")

    result = await db.execute(
        text("""
            UPDATE payroll_records
            SET status = 'voided', updated_at = now()
            WHERE id = :id AND tenant_id = :tenant_id
            RETURNING id, status
        """),
        {"id": record_id, "tenant_id": x_tenant_id},
    )
    updated = result.mappings().first()
    await db.commit()
    log.info("payroll.record.voided", tenant_id=x_tenant_id, record_id=record_id)
    return _ok(dict(updated))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  薪资计算（核心）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/calculate")
async def calculate_payroll(
    req: CalculatePayrollReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """自动计算单个员工月薪，写入 payroll_records（draft 状态）并插入 line_items。

    计算流程：
    1. 查找员工对应 payroll_config（按 store_id/employee_role + 有效期匹配）
    2. 根据 salary_type 计算 base_pay_fen：
       - monthly:   base_salary_fen
       - hourly:    hourly_rate_fen × worked_hours
       - piecework: piecework_rate_fen × quantity
    3. gross_pay = base + overtime + commission + piecework + kpi - deduction
    4. tax_fen = max(0, (gross_pay - 500000) × 3 // 100)  # 起征 5000 元，简化税率 3%
    5. net_pay = gross_pay - tax
    6. 插入 payroll_record（draft）+ payroll_line_items
    """
    effective_tenant = req.tenant_id if req.tenant_id else x_tenant_id
    await _set_rls(db, effective_tenant)

    # ── 1. 查找匹配的薪资配置 ────────────────────────────────────────────
    period_start = date(req.year, req.month, 1)

    # 先查门店级别配置，再查品牌级（store_id IS NULL），取最近生效的
    config_row = (
        await db.execute(
            text("""
                SELECT * FROM payroll_configs
                WHERE tenant_id = :tenant_id
                  AND is_active = true
                  AND is_deleted = false
                  AND effective_from <= :period_start
                  AND (effective_to IS NULL OR effective_to >= :period_start)
                ORDER BY
                  CASE WHEN store_id = :store_id THEN 0 ELSE 1 END,
                  effective_from DESC
                LIMIT 1
            """),
            {
                "tenant_id": effective_tenant,
                "store_id": req.store_id,
                "period_start": period_start,
            },
        )
    ).mappings().first()

    if not config_row:
        raise _err(
            f"未找到员工 {req.employee_id} 在门店 {req.store_id} 的有效薪资配置",
            404,
        )

    cfg = dict(config_row)
    salary_type: str = cfg.get("salary_type", "monthly")

    # ── 2. 计算 base_pay_fen ─────────────────────────────────────────────
    if salary_type == "monthly":
        base_pay_fen = int(cfg.get("base_salary_fen") or 0)

    elif salary_type == "hourly":
        hourly_rate = int(cfg.get("hourly_rate_fen") or 0)
        worked_hours = req.worked_hours or 0.0
        base_pay_fen = int(hourly_rate * worked_hours)

    elif salary_type == "piecework":
        piece_rate = int(cfg.get("piecework_rate_fen") or 0)
        quantity = req.quantity or 0.0
        base_pay_fen = int(piece_rate * quantity)

    else:
        raise _err(f"未知 salary_type: {salary_type}")

    # ── 3. 汇总各薪资分项 ────────────────────────────────────────────────
    # piecework_pay_fen：如果请求已传入则使用，否则用 base_pay（仅 piecework 类型）
    piecework_pay_fen = req.piecework_pay_fen
    if salary_type == "piecework" and piecework_pay_fen == 0:
        piecework_pay_fen = base_pay_fen
        base_pay_fen = 0  # piecework 类型底薪归零，计件金额放入 piecework_pay

    gross_pay_fen = (
        base_pay_fen
        + req.overtime_pay_fen
        + req.commission_fen
        + piecework_pay_fen
        + req.kpi_bonus_fen
        - req.deduction_fen
    )

    # ── 4. 税额（简化税率：超过 5000 元部分 × 3%） ───────────────────────
    tax_fen = max(0, (gross_pay_fen - 500_000) * 3 // 100)

    # ── 5. 实发工资 ──────────────────────────────────────────────────────
    net_pay_fen = gross_pay_fen - tax_fen

    # ── 6. 计算快照 ──────────────────────────────────────────────────────
    calc_snapshot: dict[str, Any] = {
        "salary_type": salary_type,
        "config_id": str(cfg["id"]),
        "employee_role": cfg.get("employee_role"),
        "worked_hours": req.worked_hours,
        "quantity": req.quantity,
        "base_salary_fen_config": cfg.get("base_salary_fen"),
        "hourly_rate_fen_config": cfg.get("hourly_rate_fen"),
        "piecework_rate_fen_config": cfg.get("piecework_rate_fen"),
    }

    # ── 7. 确定薪资周期结束日（取当月最后一天） ──────────────────────────
    import calendar
    last_day = calendar.monthrange(req.year, req.month)[1]
    pay_period_end = date(req.year, req.month, last_day)

    # ── 8. 插入 payroll_record ───────────────────────────────────────────
    insert_record_sql = text("""
        INSERT INTO payroll_records (
            tenant_id, store_id, employee_id,
            pay_period_start, pay_period_end,
            base_pay_fen, overtime_pay_fen, commission_fen,
            piecework_pay_fen, kpi_bonus_fen, deduction_fen,
            gross_pay_fen, tax_fen, net_pay_fen,
            status, payment_method, notes, calc_snapshot
        ) VALUES (
            :tenant_id, :store_id, :employee_id,
            :pay_period_start, :pay_period_end,
            :base_pay_fen, :overtime_pay_fen, :commission_fen,
            :piecework_pay_fen, :kpi_bonus_fen, :deduction_fen,
            :gross_pay_fen, :tax_fen, :net_pay_fen,
            'draft', :payment_method, :notes, :calc_snapshot::jsonb
        )
        RETURNING id
    """)
    record_result = await db.execute(
        insert_record_sql,
        {
            "tenant_id": effective_tenant,
            "store_id": req.store_id,
            "employee_id": req.employee_id,
            "pay_period_start": period_start,
            "pay_period_end": pay_period_end,
            "base_pay_fen": base_pay_fen,
            "overtime_pay_fen": req.overtime_pay_fen,
            "commission_fen": req.commission_fen,
            "piecework_pay_fen": piecework_pay_fen,
            "kpi_bonus_fen": req.kpi_bonus_fen,
            "deduction_fen": req.deduction_fen,
            "gross_pay_fen": gross_pay_fen,
            "tax_fen": tax_fen,
            "net_pay_fen": net_pay_fen,
            "payment_method": req.payment_method,
            "notes": req.notes,
            "calc_snapshot": json.dumps(calc_snapshot),
        },
    )
    record_id = str(record_result.fetchone()[0])

    # ── 9. 插入 payroll_line_items ────────────────────────────────────────
    line_items: list[dict[str, Any]] = []

    if base_pay_fen != 0:
        line_items.append({
            "item_type": "base",
            "item_name": "基本工资",
            "amount_fen": base_pay_fen,
            "quantity": None,
            "unit_price_fen": None,
            "notes": f"salary_type={salary_type}",
        })

    if salary_type == "hourly" and req.worked_hours:
        line_items[-1]["quantity"] = str(req.worked_hours)
        line_items[-1]["unit_price_fen"] = cfg.get("hourly_rate_fen")

    if req.overtime_pay_fen > 0:
        line_items.append({
            "item_type": "overtime",
            "item_name": "加班工资",
            "amount_fen": req.overtime_pay_fen,
            "quantity": None,
            "unit_price_fen": None,
            "notes": None,
        })

    if req.commission_fen > 0:
        line_items.append({
            "item_type": "commission",
            "item_name": "提成",
            "amount_fen": req.commission_fen,
            "quantity": None,
            "unit_price_fen": None,
            "notes": None,
        })

    if piecework_pay_fen > 0:
        line_items.append({
            "item_type": "piecework",
            "item_name": "计件工资",
            "amount_fen": piecework_pay_fen,
            "quantity": str(req.quantity) if req.quantity else None,
            "unit_price_fen": cfg.get("piecework_rate_fen"),
            "notes": cfg.get("piecework_unit"),
        })

    if req.kpi_bonus_fen > 0:
        line_items.append({
            "item_type": "kpi",
            "item_name": "绩效奖金",
            "amount_fen": req.kpi_bonus_fen,
            "quantity": None,
            "unit_price_fen": None,
            "notes": None,
        })

    if req.deduction_fen > 0:
        line_items.append({
            "item_type": "deduction",
            "item_name": "考勤扣款",
            "amount_fen": -req.deduction_fen,  # 负数表示扣除
            "quantity": None,
            "unit_price_fen": None,
            "notes": None,
        })

    if tax_fen > 0:
        line_items.append({
            "item_type": "tax",
            "item_name": "个人所得税",
            "amount_fen": -tax_fen,  # 负数表示扣除
            "quantity": None,
            "unit_price_fen": None,
            "notes": "简化税率 3%，起征额 5000 元",
        })

    # 批量插入明细行
    if line_items:
        insert_item_sql = text("""
            INSERT INTO payroll_line_items (
                tenant_id, record_id, item_type, item_name,
                amount_fen, quantity, unit_price_fen, notes
            ) VALUES (
                :tenant_id, :record_id, :item_type, :item_name,
                :amount_fen, :quantity, :unit_price_fen, :notes
            )
        """)
        for item in line_items:
            await db.execute(
                insert_item_sql,
                {
                    "tenant_id": effective_tenant,
                    "record_id": record_id,
                    **item,
                },
            )

    await db.commit()

    log.info(
        "payroll.calculated",
        tenant_id=effective_tenant,
        record_id=record_id,
        employee_id=req.employee_id,
        salary_type=salary_type,
        base_pay_fen=base_pay_fen,
        gross_pay_fen=gross_pay_fen,
        tax_fen=tax_fen,
        net_pay_fen=net_pay_fen,
        line_item_count=len(line_items),
    )

    return _ok({
        "record_id": record_id,
        "employee_id": req.employee_id,
        "store_id": req.store_id,
        "pay_period_start": period_start.isoformat(),
        "pay_period_end": pay_period_end.isoformat(),
        "salary_type": salary_type,
        "base_pay_fen": base_pay_fen,
        "overtime_pay_fen": req.overtime_pay_fen,
        "commission_fen": req.commission_fen,
        "piecework_pay_fen": piecework_pay_fen,
        "kpi_bonus_fen": req.kpi_bonus_fen,
        "deduction_fen": req.deduction_fen,
        "gross_pay_fen": gross_pay_fen,
        "tax_fen": tax_fen,
        "net_pay_fen": net_pay_fen,
        "status": "draft",
        "config_id": str(cfg["id"]),
        "line_items": line_items,
        "calc_snapshot": calc_snapshot,
    })


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  明细行端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/records/{record_id}/items")
async def list_payroll_line_items(
    record_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """查询薪资单明细行"""
    await _set_rls(db, x_tenant_id)

    # 验证薪资单归属
    exists = (
        await db.execute(
            text("""
                SELECT 1 FROM payroll_records
                WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = false
            """),
            {"id": record_id, "tenant_id": x_tenant_id},
        )
    ).first()

    if not exists:
        raise _err(f"薪资单不存在: {record_id}", 404)

    rows = (
        await db.execute(
            text("""
                SELECT * FROM payroll_line_items
                WHERE record_id = :record_id AND tenant_id = :tenant_id
                ORDER BY created_at
            """),
            {"record_id": record_id, "tenant_id": x_tenant_id},
        )
    ).mappings().all()

    return _ok({"record_id": record_id, "items": [dict(r) for r in rows], "total": len(rows)})
