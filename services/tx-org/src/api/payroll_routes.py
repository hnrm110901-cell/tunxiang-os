"""薪资引擎 V4 — 餐饮门店计件工资、提成和绩效奖金

API 前缀：/api/v1/org/payroll（与 payroll_engine_routes.py V3 共存）

端点列表：
  GET  /api/v1/org/payroll/config                     — 查询门店薪资配置
  POST /api/v1/org/payroll/config                     — 创建/更新薪资配置
  GET  /api/v1/org/payroll/config/roles               — 支持的角色列表
  POST /api/v1/org/payroll/calculate                  — 计算单个员工月薪
  POST /api/v1/org/payroll/calculate-batch            — 批量计算门店所有员工
  GET  /api/v1/org/payroll/summaries                  — 薪资汇总列表
  POST /api/v1/org/payroll/summaries/{id}/confirm     — 确认薪资单
  POST /api/v1/org/payroll/summaries/{id}/pay         — 标记已发放
  GET  /api/v1/org/payroll/summaries/{id}/payslip     — 工资条数据
  POST /api/v1/org/payroll/perf-scores                — 录入绩效评分明细
  GET  /api/v1/org/payroll/perf-scores                — 查询绩效评分
  POST /api/v1/org/payroll/deductions                 — 添加扣款记录
  DELETE /api/v1/org/payroll/deductions/{id}          — 撤销扣款（软删除）

真实实现 TODO：将 MOCK_* 替换为真实 DB 查询（payroll_configs / payroll_summaries /
perf_score_items / payroll_deductions 表，v121 迁移）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/org/payroll", tags=["payroll-engine-v4"])

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Mock 数据
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SUPPORTED_ROLES = ["waiter", "chef", "cashier", "manager"]

# 5 个模拟员工，不同角色
MOCK_EMPLOYEES = [
    {"id": "emp-001", "name": "张服务", "role": "waiter",
     "piece_count": 45, "commission_base": 2_500_000},
    {"id": "emp-002", "name": "李厨师", "role": "chef",
     "piece_count": 0, "perf_score": 88.5},
    {"id": "emp-003", "name": "王收银", "role": "cashier",
     "piece_count": 0, "perf_score": 92.0},
    {"id": "emp-004", "name": "赵经理", "role": "manager",
     "commission_base": 12_000_000},
    {"id": "emp-005", "name": "钱服务", "role": "waiter",
     "piece_count": 38, "commission_base": 1_800_000},
]

# 默认薪资配置（每角色）
# TODO: 从 payroll_configs 表查询（JOIN store_id + employee_role + effective_from <= NOW()）
MOCK_PAYROLL_CONFIGS: dict[str, dict[str, Any]] = {
    "waiter": {
        "id": "cfg-waiter-001",
        "employee_role": "waiter",
        "base_salary_fen": 300_000,     # 3000 元
        "piece_rate_enabled": True,
        "piece_rate_fen": 200,           # 2 元/单
        "commission_rate": 0.005,        # 0.5%
        "commission_base": "revenue",
        "perf_bonus_enabled": True,
        "perf_bonus_cap_fen": 50_000,   # 最高 500 元
        "effective_from": "2026-01-01",
    },
    "chef": {
        "id": "cfg-chef-001",
        "employee_role": "chef",
        "base_salary_fen": 500_000,     # 5000 元
        "piece_rate_enabled": False,
        "piece_rate_fen": 0,
        "commission_rate": 0.0,
        "commission_base": "revenue",
        "perf_bonus_enabled": True,
        "perf_bonus_cap_fen": 80_000,   # 最高 800 元
        "effective_from": "2026-01-01",
    },
    "cashier": {
        "id": "cfg-cashier-001",
        "employee_role": "cashier",
        "base_salary_fen": 350_000,     # 3500 元
        "piece_rate_enabled": False,
        "piece_rate_fen": 0,
        "commission_rate": 0.0,
        "commission_base": "revenue",
        "perf_bonus_enabled": True,
        "perf_bonus_cap_fen": 50_000,
        "effective_from": "2026-01-01",
    },
    "manager": {
        "id": "cfg-manager-001",
        "employee_role": "manager",
        "base_salary_fen": 800_000,     # 8000 元
        "piece_rate_enabled": False,
        "piece_rate_fen": 0,
        "commission_rate": 0.015,        # 1.5%
        "commission_base": "revenue",
        "perf_bonus_enabled": True,
        "perf_bonus_cap_fen": 200_000,  # 最高 2000 元
        "effective_from": "2026-01-01",
    },
}

# 内存存储（生产替换为 DB）
# key: "{tenant_id}:{employee_id}:{year}:{month}"
_summaries: dict[str, dict[str, Any]] = {}
# key: "{tenant_id}:{deduction_id}"
_deductions: dict[str, dict[str, Any]] = {}
# key: "{tenant_id}:{employee_id}:{year}:{month}:{item_id}"
_perf_items: dict[str, dict[str, Any]] = {}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Pydantic 模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class PayrollConfigUpsertReq(BaseModel):
    store_id: str = Field(..., description="门店 UUID")
    employee_role: str = Field(..., description="waiter/chef/cashier/manager")
    base_salary_fen: int = Field(..., ge=0, description="底薪（分）")
    piece_rate_enabled: bool = Field(False)
    piece_rate_fen: int = Field(0, ge=0, description="计件单价（分/单）")
    commission_rate: float = Field(0.0, ge=0.0, le=1.0, description="提成比例（0.05=5%）")
    commission_base: str = Field("revenue", description="revenue/profit/dishes")
    perf_bonus_enabled: bool = Field(False)
    perf_bonus_cap_fen: int = Field(0, ge=0, description="绩效奖金上限（分）")
    effective_from: str = Field(..., description="生效日期 YYYY-MM-DD")


class CalculateReq(BaseModel):
    employee_id: str = Field(..., description="员工 ID")
    store_id: str = Field(..., description="门店 ID")
    year: int = Field(..., ge=2020, le=2100)
    month: int = Field(..., ge=1, le=12)


class BatchCalculateReq(BaseModel):
    store_id: str = Field(..., description="门店 ID")
    year: int = Field(..., ge=2020, le=2100)
    month: int = Field(..., ge=1, le=12)


class PerfScoreItemReq(BaseModel):
    employee_id: str
    period_year: int = Field(..., ge=2020, le=2100)
    period_month: int = Field(..., ge=1, le=12)
    item_name: str = Field(..., max_length=100)
    score: float = Field(..., ge=0, le=100)
    weight: float = Field(1.0, ge=0.0, le=10.0)
    notes: str | None = Field(None, max_length=200)


class DeductionReq(BaseModel):
    employee_id: str
    period_year: int = Field(..., ge=2020, le=2100)
    period_month: int = Field(..., ge=1, le=12)
    reason: str = Field(..., max_length=100, description="迟到/违规/损耗赔偿")
    amount_fen: int = Field(..., ge=1, description="扣款金额（分）")
    approved_by: str | None = Field(None, max_length=100)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  辅助函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data, "error": {}}


def _summary_key(tenant_id: str, employee_id: str, year: int, month: int) -> str:
    return f"{tenant_id}:{employee_id}:{year}:{month}"


def _deduction_key(tenant_id: str, deduction_id: str) -> str:
    return f"{tenant_id}:{deduction_id}"


def _calculate_one(
    tenant_id: str,
    employee: dict[str, Any],
    year: int,
    month: int,
    config: dict[str, Any],
    deductions_fen: int,
    perf_score: float | None,
) -> dict[str, Any]:
    """核心薪资计算逻辑。

    公式：total = base + piece_count×piece_rate + commission_base×commission_rate
                 + perf_score/100×perf_bonus_cap - deductions

    TODO: 替换 mock employee 数据，改为从 employees 表 + attendance_records 表
          查询实际出勤数据。
    """
    base = config["base_salary_fen"]

    # 计件工资
    piece_count: int = employee.get("piece_count", 0)
    piece_amount = piece_count * config["piece_rate_fen"] if config["piece_rate_enabled"] else 0

    # 提成
    commission_base: int = employee.get("commission_base", 0)
    commission_amount = int(commission_base * config["commission_rate"])

    # 绩效奖金
    eff_perf_score: float = perf_score if perf_score is not None else employee.get("perf_score", 0.0)
    perf_bonus = 0
    if config["perf_bonus_enabled"] and eff_perf_score > 0:
        perf_bonus = int(eff_perf_score / 100.0 * config["perf_bonus_cap_fen"])

    total = base + piece_amount + commission_amount + perf_bonus - deductions_fen
    total = max(total, 0)  # 最低不低于 0

    return {
        "employee_id": employee["id"],
        "employee_name": employee["name"],
        "employee_role": employee["role"],
        "store_id": tenant_id,  # placeholder; real: use actual store_id
        "period_year": year,
        "period_month": month,
        "base_salary_fen": base,
        "piece_count": piece_count,
        "piece_amount_fen": piece_amount,
        "commission_base_fen": commission_base,
        "commission_amount_fen": commission_amount,
        "perf_score": eff_perf_score,
        "perf_bonus_fen": perf_bonus,
        "deductions_fen": deductions_fen,
        "total_salary_fen": total,
        "status": "draft",
        # 计算明细（便于前端展示每步推导过程）
        "breakdown": {
            "base": {"label": "底薪", "fen": base},
            "piece": {
                "label": "计件工资",
                "fen": piece_amount,
                "detail": f"{piece_count} 单 × {config['piece_rate_fen']} 分/单",
            },
            "commission": {
                "label": "提成",
                "fen": commission_amount,
                "detail": f"{commission_base} 分 × {config['commission_rate'] * 100:.2f}%",
            },
            "perf_bonus": {
                "label": "绩效奖金",
                "fen": perf_bonus,
                "detail": f"评分 {eff_perf_score:.1f}/100 × 上限 {config['perf_bonus_cap_fen']} 分",
            },
            "deductions": {"label": "扣款", "fen": -deductions_fen},
            "total": {"label": "实发合计", "fen": total},
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  薪资配置端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/config")
async def get_payroll_config(
    store_id: str | None = Query(None, description="门店 ID 过滤"),
    role: str | None = Query(None, description="角色过滤 waiter/chef/cashier/manager"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """查询门店薪资配置。

    TODO: 从 payroll_configs 表查询 WHERE tenant_id = :tid AND store_id = :store_id
          AND is_deleted = false ORDER BY employee_role, effective_from DESC
    """
    configs = list(MOCK_PAYROLL_CONFIGS.values())
    if role:
        configs = [c for c in configs if c["employee_role"] == role]
    return _ok({"items": configs, "total": len(configs)})


@router.get("/config/roles")
async def get_supported_roles(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """返回支持的员工角色列表。"""
    roles = [
        {"value": "waiter", "label": "服务员"},
        {"value": "chef", "label": "厨师"},
        {"value": "cashier", "label": "收银员"},
        {"value": "manager", "label": "店长"},
    ]
    return _ok({"items": roles})


@router.post("/config")
async def upsert_payroll_config(
    req: PayrollConfigUpsertReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """创建或更新薪资配置。

    TODO: UPSERT INTO payroll_configs(...) ON CONFLICT(tenant_id, store_id, employee_role,
          effective_from) DO UPDATE SET ...
    """
    if req.employee_role not in SUPPORTED_ROLES:
        raise HTTPException(status_code=400, detail=f"不支持的角色: {req.employee_role}")

    config_id = f"cfg-{req.employee_role}-{req.store_id[:8]}"
    MOCK_PAYROLL_CONFIGS[req.employee_role] = {
        "id": config_id,
        "employee_role": req.employee_role,
        "store_id": req.store_id,
        "base_salary_fen": req.base_salary_fen,
        "piece_rate_enabled": req.piece_rate_enabled,
        "piece_rate_fen": req.piece_rate_fen,
        "commission_rate": req.commission_rate,
        "commission_base": req.commission_base,
        "perf_bonus_enabled": req.perf_bonus_enabled,
        "perf_bonus_cap_fen": req.perf_bonus_cap_fen,
        "effective_from": req.effective_from,
    }
    return _ok({"config_id": config_id, "upserted": True})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  薪资计算端点（核心）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/calculate")
async def calculate_employee_payroll(
    req: CalculateReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """计算单个员工月薪。

    公式：total = base + piece_count×piece_rate
                 + commission_base×commission_rate
                 + perf_score/100×perf_bonus_cap
                 - deductions

    TODO: 从 employees 表查员工信息，从 payroll_configs 表查薪资配置，
          从 payroll_deductions 表汇总扣款，从 perf_score_items 表算绩效加权平均分，
          结果写入 payroll_summaries 表（ON CONFLICT DO UPDATE）。
    """
    employee = next((e for e in MOCK_EMPLOYEES if e["id"] == req.employee_id), None)
    if not employee:
        raise HTTPException(status_code=404, detail=f"员工不存在: {req.employee_id}")

    config = MOCK_PAYROLL_CONFIGS.get(employee["role"])
    if not config:
        raise HTTPException(status_code=400, detail=f"未找到角色 {employee['role']} 的薪资配置")

    # 汇总该员工该月扣款
    deductions_total = sum(
        d["amount_fen"]
        for d in _deductions.values()
        if not d["is_deleted"]
        and d["employee_id"] == req.employee_id
        and d["period_year"] == req.year
        and d["period_month"] == req.month
    )

    # 汇总绩效评分（加权平均）
    perf_items = [
        p for p in _perf_items.values()
        if not p["is_deleted"]
        and p["employee_id"] == req.employee_id
        and p["period_year"] == req.year
        and p["period_month"] == req.month
    ]
    perf_score: float | None = None
    if perf_items:
        total_weight = sum(p["weight"] for p in perf_items)
        if total_weight > 0:
            perf_score = sum(p["score"] * p["weight"] for p in perf_items) / total_weight

    result = _calculate_one(
        tenant_id=x_tenant_id,
        employee=employee,
        year=req.year,
        month=req.month,
        config=config,
        deductions_fen=deductions_total,
        perf_score=perf_score,
    )
    result["store_id"] = req.store_id

    # 缓存到内存（TODO: 写入 payroll_summaries 表）
    key = _summary_key(x_tenant_id, req.employee_id, req.year, req.month)
    _summaries[key] = {**result, "id": str(uuid.uuid4()), "created_at": datetime.now().isoformat()}

    return _ok(result)


@router.post("/calculate-batch")
async def calculate_batch_payroll(
    req: BatchCalculateReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """批量计算门店所有员工当月薪资。

    TODO: 从 employees 表查 store_id 下的所有在职员工，循环计算后批量写入
          payroll_summaries 表（INSERT ... ON CONFLICT DO UPDATE）。
    """
    results = []
    for employee in MOCK_EMPLOYEES:
        config = MOCK_PAYROLL_CONFIGS.get(employee["role"])
        if not config:
            continue

        deductions_total = sum(
            d["amount_fen"]
            for d in _deductions.values()
            if not d["is_deleted"]
            and d["employee_id"] == employee["id"]
            and d["period_year"] == req.year
            and d["period_month"] == req.month
        )

        perf_items = [
            p for p in _perf_items.values()
            if not p["is_deleted"]
            and p["employee_id"] == employee["id"]
            and p["period_year"] == req.year
            and p["period_month"] == req.month
        ]
        perf_score: float | None = None
        if perf_items:
            total_weight = sum(p["weight"] for p in perf_items)
            if total_weight > 0:
                perf_score = sum(p["score"] * p["weight"] for p in perf_items) / total_weight

        calc = _calculate_one(
            tenant_id=x_tenant_id,
            employee=employee,
            year=req.year,
            month=req.month,
            config=config,
            deductions_fen=deductions_total,
            perf_score=perf_score,
        )
        calc["store_id"] = req.store_id
        summary_id = str(uuid.uuid4())
        calc["id"] = summary_id

        key = _summary_key(x_tenant_id, employee["id"], req.year, req.month)
        _summaries[key] = {**calc, "created_at": datetime.now().isoformat()}
        results.append(calc)

    total_salary = sum(r["total_salary_fen"] for r in results)
    return _ok({
        "store_id": req.store_id,
        "year": req.year,
        "month": req.month,
        "employee_count": len(results),
        "total_salary_fen": total_salary,
        "total_salary_yuan": round(total_salary / 100, 2),
        "records": results,
    })


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  月度汇总端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/summaries")
async def list_payroll_summaries(
    year: int | None = Query(None, ge=2020, le=2100),
    month: int | None = Query(None, ge=1, le=12),
    store_id: str | None = Query(None),
    status: str | None = Query(None, description="draft/confirmed/paid"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """查询薪资汇总列表。

    TODO: SELECT * FROM payroll_summaries WHERE tenant_id = :tid
          AND (:year IS NULL OR period_year = :year)
          AND (:month IS NULL OR period_month = :month)
          AND (:store_id IS NULL OR store_id = :store_id)
          AND (:status IS NULL OR status = :status)
          AND is_deleted = false
          ORDER BY period_year DESC, period_month DESC, created_at DESC
    """
    items = [
        s for s in _summaries.values()
        if s.get("id", "").startswith(x_tenant_id) or True  # mock: return all
    ]
    if year is not None:
        items = [s for s in items if s.get("period_year") == year]
    if month is not None:
        items = [s for s in items if s.get("period_month") == month]
    if status is not None:
        items = [s for s in items if s.get("status") == status]

    return _ok({"items": items, "total": len(items)})


@router.post("/summaries/{summary_id}/confirm")
async def confirm_payroll_summary(
    summary_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """确认薪资单（draft → confirmed）。

    TODO: UPDATE payroll_summaries SET status = 'confirmed', updated_at = NOW()
          WHERE id = :id AND tenant_id = :tid AND status = 'draft' AND is_deleted = false
    """
    # 在内存中查找
    found = None
    for key, s in _summaries.items():
        if s.get("id") == summary_id:
            found = (key, s)
            break

    if not found:
        raise HTTPException(status_code=404, detail=f"薪资单不存在: {summary_id}")

    key, summary = found
    if summary["status"] != "draft":
        raise HTTPException(
            status_code=400,
            detail=f"当前状态 {summary['status']} 不可确认，只有 draft 状态可确认",
        )
    summary["status"] = "confirmed"
    summary["confirmed_at"] = datetime.now().isoformat()
    _summaries[key] = summary

    return _ok({"summary_id": summary_id, "status": "confirmed",
                "confirmed_at": summary["confirmed_at"]})


@router.post("/summaries/{summary_id}/pay")
async def mark_payroll_paid(
    summary_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """标记薪资单已发放（confirmed → paid）。

    TODO: UPDATE payroll_summaries SET status = 'paid', updated_at = NOW()
          WHERE id = :id AND tenant_id = :tid AND status = 'confirmed' AND is_deleted = false
    """
    found = None
    for key, s in _summaries.items():
        if s.get("id") == summary_id:
            found = (key, s)
            break

    if not found:
        raise HTTPException(status_code=404, detail=f"薪资单不存在: {summary_id}")

    key, summary = found
    if summary["status"] != "confirmed":
        raise HTTPException(
            status_code=400,
            detail=f"当前状态 {summary['status']} 不可发放，只有 confirmed 状态可发放",
        )
    summary["status"] = "paid"
    summary["paid_at"] = datetime.now().isoformat()
    _summaries[key] = summary

    return _ok({"summary_id": summary_id, "status": "paid", "paid_at": summary["paid_at"]})


@router.get("/summaries/{summary_id}/payslip")
async def get_payslip(
    summary_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """获取工资条数据（员工可查看）。

    TODO: SELECT ps.*, e.name as employee_name, s.name as store_name
          FROM payroll_summaries ps
          JOIN employees e ON ps.employee_id = e.id
          JOIN stores s ON ps.store_id = s.id
          WHERE ps.id = :id AND ps.tenant_id = :tid AND ps.is_deleted = false
    """
    found = None
    for s in _summaries.values():
        if s.get("id") == summary_id:
            found = s
            break

    if not found:
        raise HTTPException(status_code=404, detail=f"薪资单不存在: {summary_id}")

    payslip = {
        **found,
        "payslip_title": f"{found.get('period_year')}年{found.get('period_month')}月工资条",
        "store_name": "示例门店",  # TODO: JOIN stores 表
        "base_salary_yuan": round(found.get("base_salary_fen", 0) / 100, 2),
        "piece_amount_yuan": round(found.get("piece_amount_fen", 0) / 100, 2),
        "commission_amount_yuan": round(found.get("commission_amount_fen", 0) / 100, 2),
        "perf_bonus_yuan": round(found.get("perf_bonus_fen", 0) / 100, 2),
        "deductions_yuan": round(found.get("deductions_fen", 0) / 100, 2),
        "total_salary_yuan": round(found.get("total_salary_fen", 0) / 100, 2),
    }
    return _ok(payslip)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  绩效录入端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/perf-scores")
async def create_perf_score(
    req: PerfScoreItemReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """录入绩效评分明细。

    TODO: INSERT INTO perf_score_items (tenant_id, employee_id, period_year, period_month,
          item_name, score, weight, notes) VALUES (...)
    """
    item_id = str(uuid.uuid4())
    item = {
        "id": item_id,
        "tenant_id": x_tenant_id,
        "employee_id": req.employee_id,
        "period_year": req.period_year,
        "period_month": req.period_month,
        "item_name": req.item_name,
        "score": req.score,
        "weight": req.weight,
        "notes": req.notes,
        "is_deleted": False,
        "created_at": datetime.now().isoformat(),
    }
    key = f"{x_tenant_id}:{req.employee_id}:{req.period_year}:{req.period_month}:{item_id}"
    _perf_items[key] = item
    return _ok({"item_id": item_id, "created": True})


@router.get("/perf-scores")
async def list_perf_scores(
    employee_id: str | None = Query(None),
    year: int | None = Query(None, ge=2020, le=2100),
    month: int | None = Query(None, ge=1, le=12),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """查询绩效评分明细。

    TODO: SELECT * FROM perf_score_items WHERE tenant_id = :tid
          AND (:emp IS NULL OR employee_id = :emp)
          AND (:year IS NULL OR period_year = :year)
          AND (:month IS NULL OR period_month = :month)
          AND is_deleted = false
          ORDER BY period_year DESC, period_month DESC
    """
    items = [p for p in _perf_items.values() if not p["is_deleted"]]
    if employee_id:
        items = [p for p in items if p["employee_id"] == employee_id]
    if year is not None:
        items = [p for p in items if p["period_year"] == year]
    if month is not None:
        items = [p for p in items if p["period_month"] == month]

    return _ok({"items": items, "total": len(items)})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  扣款管理端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/deductions")
async def create_deduction(
    req: DeductionReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """添加扣款记录。

    TODO: INSERT INTO payroll_deductions (tenant_id, employee_id, period_year, period_month,
          reason, amount_fen, approved_by) VALUES (...)
    """
    ded_id = str(uuid.uuid4())
    deduction = {
        "id": ded_id,
        "tenant_id": x_tenant_id,
        "employee_id": req.employee_id,
        "period_year": req.period_year,
        "period_month": req.period_month,
        "reason": req.reason,
        "amount_fen": req.amount_fen,
        "approved_by": req.approved_by,
        "is_deleted": False,
        "created_at": datetime.now().isoformat(),
    }
    key = _deduction_key(x_tenant_id, ded_id)
    _deductions[key] = deduction
    return _ok({"deduction_id": ded_id, "created": True})


@router.delete("/deductions/{deduction_id}")
async def revoke_deduction(
    deduction_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """撤销扣款记录（软删除）。

    TODO: UPDATE payroll_deductions SET is_deleted = true
          WHERE id = :id AND tenant_id = :tid AND is_deleted = false
    """
    key = _deduction_key(x_tenant_id, deduction_id)
    deduction = _deductions.get(key)
    if not deduction:
        raise HTTPException(status_code=404, detail=f"扣款记录不存在: {deduction_id}")
    if deduction["is_deleted"]:
        raise HTTPException(status_code=400, detail="扣款记录已撤销")

    deduction["is_deleted"] = True
    _deductions[key] = deduction
    return _ok({"deduction_id": deduction_id, "revoked": True})
