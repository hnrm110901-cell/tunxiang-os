"""人效指标 API"""
from typing import Optional
from fastapi import APIRouter, Query
from services.labor_efficiency_service import (
    INDUSTRY_BENCHMARKS,
    compute_store_efficiency,
    compare_stores,
    generate_efficiency_alerts,
    get_boss_view,
    get_hr_view,
    get_manager_view,
    get_staff_view,
)

router = APIRouter(prefix="/api/v1/org/efficiency", tags=["efficiency"])


# ── 模拟数据（后续接入真实数据源） ────────────────────────────────

def _mock_store_data(store_id: str) -> dict:
    """临时模拟门店数据，后续替换为 DB 查询。"""
    return {
        "store_id": store_id,
        "store_name": f"门店-{store_id}",
        "total_labor_fen": 250_000_00,
        "total_revenue_fen": 1_000_000_00,
        "headcount": 15,
        "total_work_hours": 2400.0,
        "total_guests": 3200,
        "productive_hours": 1920.0,
        "total_hours": 2400.0,
        "employees": [],
        "peak_hours": [11, 12, 17, 18, 19],
        "scheduled_hours": 2400.0,
        "required_hours": 2300.0,
    }


def _mock_brand_data(brand_id: str = "brand_1") -> dict:
    """临时模拟品牌数据。"""
    stores = [_mock_store_data(f"store_{i}") for i in range(1, 4)]
    return {
        "brand_id": brand_id,
        "brand_name": "示例品牌",
        "stores": stores,
        "monthly_labor_fen": [240_000_00, 250_000_00, 260_000_00],
        "monthly_revenue_fen": [950_000_00, 1_000_000_00, 1_050_000_00],
        "total_headcount": 45,
        "total_positions": 50,
        "resignations_this_month": 3,
        "avg_tenure_months": 18,
        "open_positions": 5,
        "avg_salary_fen": 550_000,
    }


def _mock_employee_data(emp_id: str = "emp_1") -> dict:
    """临时模拟员工数据。"""
    return {
        "emp_id": emp_id,
        "emp_name": "张三",
        "hours_worked": 176.0,
        "revenue_fen": 2_800_000,
        "guests_served": 280,
        "attendance": {
            "present_days": 22,
            "absent_days": 0,
            "late_count": 1,
            "early_leave_count": 0,
        },
        "salary": {
            "base_fen": 400_000,
            "commission_fen": 80_000,
            "bonus_fen": 30_000,
            "deduction_fen": 5_000,
            "net_fen": 505_000,
        },
    }


# ── API 端点 ──────────────────────────────────────────────────

@router.get("/benchmark")
async def get_benchmark():
    """行业基准值。"""
    return {"ok": True, "data": INDUSTRY_BENCHMARKS}


@router.get("/compare")
async def get_compare(store_ids: str = Query(..., description="逗号分隔的门店ID列表")):
    """多门店人效对比。"""
    ids = [sid.strip() for sid in store_ids.split(",") if sid.strip()]
    stores_data = [_mock_store_data(sid) for sid in ids]
    result = compare_stores(stores_data)
    return {"ok": True, "data": result}


@router.get("/alerts")
async def get_alerts(store_id: Optional[str] = None):
    """人效预警。"""
    if store_id:
        sd = _mock_store_data(store_id)
        report = compute_store_efficiency(sd)
        alerts = report["alerts"]
    else:
        brand = _mock_brand_data()
        alerts = []
        for sd in brand["stores"]:
            report = compute_store_efficiency(sd)
            for alert in report["alerts"]:
                alert["store_id"] = sd["store_id"]
                alert["store_name"] = sd["store_name"]
                alerts.append(alert)
    return {"ok": True, "data": {"alerts": alerts}}


@router.get("/dashboard")
async def get_dashboard(
    role: str = Query(..., description="角色: boss|hr|manager|staff"),
    store_id: Optional[str] = None,
    emp_id: Optional[str] = None,
    brand_id: Optional[str] = None,
):
    """多角色看板。"""
    if role == "boss":
        data = get_boss_view(_mock_brand_data(brand_id or "brand_1"))
    elif role == "hr":
        data = get_hr_view(_mock_brand_data(brand_id or "brand_1"))
    elif role == "manager":
        sd = _mock_store_data(store_id or "store_1")
        data = get_manager_view(sd)
    elif role == "staff":
        data = get_staff_view(_mock_employee_data(emp_id or "emp_1"))
    else:
        return {"ok": False, "error": {"code": "INVALID_ROLE", "message": f"不支持的角色: {role}，请使用 boss|hr|manager|staff"}}
    return {"ok": True, "data": data}


@router.get("/{store_id}")
async def get_store_efficiency(store_id: str):
    """门店人效报告。"""
    sd = _mock_store_data(store_id)
    report = compute_store_efficiency(sd)
    return {"ok": True, "data": report}
