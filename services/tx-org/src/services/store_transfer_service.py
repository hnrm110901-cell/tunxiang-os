"""
门店借调与成本分摊服务 -- 纯函数实现（无 DB 依赖）

核心能力：
- 借调单创建
- 工时拆分（按借调记录自动拆分工时到各门店）
- 成本分摊（按工时占比分摊薪资成本）
- 三表生成（明细分摊表 / 薪资汇总表 / 成本分析表）

金额单位统一为"分"（fen），与 V2.x 保持一致。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Dict, List

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  借调单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def create_transfer_order(
    employee_id: str,
    employee_name: str,
    from_store_id: str,
    from_store_name: str,
    to_store_id: str,
    to_store_name: str,
    start_date: str,
    end_date: str,
    reason: str = "",
) -> dict:
    """创建借调单。

    Args:
        employee_id: 员工ID
        employee_name: 员工姓名
        from_store_id: 原门店ID
        from_store_name: 原门店名称
        to_store_id: 借调目标门店ID
        to_store_name: 借调目标门店名称
        start_date: 开始日期（YYYY-MM-DD）
        end_date: 结束日期（YYYY-MM-DD）
        reason: 借调原因

    Returns:
        借调单字典
    """
    if from_store_id == to_store_id:
        raise ValueError("原门店与目标门店不能相同")

    parsed_start = date.fromisoformat(start_date)
    parsed_end = date.fromisoformat(end_date)
    if parsed_end < parsed_start:
        raise ValueError("结束日期不能早于开始日期")

    order_id = str(uuid.uuid4())
    now = datetime.now().isoformat()

    return {
        "id": order_id,
        "employee_id": employee_id,
        "employee_name": employee_name,
        "from_store_id": from_store_id,
        "from_store_name": from_store_name,
        "to_store_id": to_store_id,
        "to_store_name": to_store_name,
        "start_date": start_date,
        "end_date": end_date,
        "reason": reason,
        "status": "pending",
        "approved_by": None,
        "approved_at": None,
        "created_at": now,
    }


def approve_transfer_order(order: dict, approver_id: str) -> dict:
    """审批借调单。

    Args:
        order: 借调单字典
        approver_id: 审批人ID

    Returns:
        更新后的借调单
    """
    if order.get("status") != "pending":
        raise ValueError(f"借调单状态为 {order.get('status')}，无法审批")

    updated = dict(order)
    updated["status"] = "approved"
    updated["approved_by"] = approver_id
    updated["approved_at"] = datetime.now().isoformat()
    return updated


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  工时拆分
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def compute_time_split(
    transfers: List[Dict[str, Any]],
    attendance_records: List[Dict[str, Any]],
) -> Dict[str, Dict[str, float]]:
    """按借调记录自动拆分工时到各门店。

    对于每条考勤记录，检查该员工在该日期是否处于借调期内：
    - 如果是，将工时归入借调目标门店
    - 如果不是，将工时归入考勤记录中的 store_id（原门店）

    Args:
        transfers: [{"employee_id", "from_store_id", "to_store_id", "start_date", "end_date"}]
        attendance_records: [{"employee_id", "date", "hours", "store_id"}]

    Returns:
        {"employee_id": {"store_a": 120.5, "store_b": 40.0}} (小时)
    """
    # 预处理借调记录：按员工分组
    transfer_map: Dict[str, List[Dict[str, Any]]] = {}
    for t in transfers:
        emp_id = t["employee_id"]
        if emp_id not in transfer_map:
            transfer_map[emp_id] = []
        transfer_map[emp_id].append(
            {
                "from_store_id": t["from_store_id"],
                "to_store_id": t["to_store_id"],
                "start_date": date.fromisoformat(t["start_date"]),
                "end_date": date.fromisoformat(t["end_date"]),
            }
        )

    result: Dict[str, Dict[str, float]] = {}

    for record in attendance_records:
        emp_id = record["employee_id"]
        rec_date = date.fromisoformat(record["date"])
        hours = float(record["hours"])
        original_store = record["store_id"]

        # 确定该条考勤应归入哪个门店
        target_store = original_store
        emp_transfers = transfer_map.get(emp_id, [])
        for t in emp_transfers:
            if t["start_date"] <= rec_date <= t["end_date"]:
                # 员工在借调期内，工时归入目标门店
                target_store = t["to_store_id"]
                break

        if emp_id not in result:
            result[emp_id] = {}
        result[emp_id][target_store] = result[emp_id].get(target_store, 0.0) + hours

    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  成本分摊
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def compute_cost_split(
    time_split: Dict[str, Dict[str, float]],
    salary_data: Dict[str, int],
) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """按工时占比分摊成本。

    对于 time_split 中的每个员工，按各门店工时占比分摊薪资各项。
    使用最大余额法保证分摊后总额与原始总额一致（分级别精度无误差）。

    Args:
        time_split: compute_time_split 的结果
            {"employee_id": {"store_a": 120.5, "store_b": 40.0}}
        salary_data: {"base_fen": X, "overtime_fen": X, "social_fen": X, "bonus_fen": X}

    Returns:
        {
            "employee_id": {
                "store_a": {
                    "wage_fen": X,
                    "social_fen": X,
                    "bonus_fen": X,
                    "total_fen": X,
                    "ratio": 0.75
                },
                "store_b": {...}
            }
        }
    """
    base_fen = salary_data.get("base_fen", 0)
    overtime_fen = salary_data.get("overtime_fen", 0)
    social_fen = salary_data.get("social_fen", 0)
    bonus_fen = salary_data.get("bonus_fen", 0)

    # 工资 = 基本工资 + 加班费
    total_wage_fen = base_fen + overtime_fen

    result: Dict[str, Dict[str, Dict[str, Any]]] = {}

    for emp_id, store_hours in time_split.items():
        total_hours = sum(store_hours.values())
        if total_hours <= 0:
            continue

        stores = sorted(store_hours.keys())
        ratios = {s: store_hours[s] / total_hours for s in stores}

        # 使用最大余额法分摊每项金额
        wage_alloc = _largest_remainder_split(total_wage_fen, stores, ratios)
        social_alloc = _largest_remainder_split(social_fen, stores, ratios)
        bonus_alloc = _largest_remainder_split(bonus_fen, stores, ratios)

        emp_result: Dict[str, Dict[str, Any]] = {}
        for s in stores:
            w = wage_alloc[s]
            sc = social_alloc[s]
            b = bonus_alloc[s]
            emp_result[s] = {
                "wage_fen": w,
                "social_fen": sc,
                "bonus_fen": b,
                "total_fen": w + sc + b,
                "ratio": round(ratios[s], 6),
            }

        result[emp_id] = emp_result

    return result


def _largest_remainder_split(
    total_fen: int,
    stores: List[str],
    ratios: Dict[str, float],
) -> Dict[str, int]:
    """最大余额法分摊整数金额，保证总和精确等于 total_fen。

    Args:
        total_fen: 待分摊总金额（分）
        stores: 门店ID列表（已排序）
        ratios: 各门店占比

    Returns:
        {"store_id": 分配金额(分)}
    """
    if not stores:
        return {}

    # 先按比例计算浮点值
    float_values = {s: total_fen * ratios[s] for s in stores}
    # 向下取整
    floor_values = {s: int(float_values[s]) for s in stores}
    # 余额
    remainders = {s: float_values[s] - floor_values[s] for s in stores}
    # 差额
    diff = total_fen - sum(floor_values.values())

    # 按余额从大到小排序，将差额分配给余额最大的门店
    sorted_stores = sorted(stores, key=lambda s: remainders[s], reverse=True)
    for i in range(diff):
        floor_values[sorted_stores[i]] += 1

    return floor_values


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  三表生成
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def generate_detail_report(
    employee_id: str,
    time_split: Dict[str, float],
    cost_split: Dict[str, Dict[str, Any]],
) -> dict:
    """明细分摊表：展示单个员工各门店的工时与成本分摊明细。

    Args:
        employee_id: 员工ID
        time_split: 该员工的工时拆分 {"store_a": 120.5, "store_b": 40.0}
        cost_split: 该员工的成本分摊 {"store_a": {"wage_fen":..., ...}, ...}

    Returns:
        {
            "employee_id": "xxx",
            "total_hours": 160.5,
            "total_cost_fen": xxxxx,
            "stores": [
                {
                    "store_id": "store_a",
                    "hours": 120.5,
                    "ratio": 0.75,
                    "wage_fen": X,
                    "social_fen": X,
                    "bonus_fen": X,
                    "total_fen": X
                },
                ...
            ]
        }
    """
    total_hours = sum(time_split.values())
    total_cost_fen = sum(s.get("total_fen", 0) for s in cost_split.values())

    stores_detail = []
    for store_id in sorted(cost_split.keys()):
        cs = cost_split[store_id]
        stores_detail.append(
            {
                "store_id": store_id,
                "hours": time_split.get(store_id, 0.0),
                "ratio": cs.get("ratio", 0.0),
                "wage_fen": cs.get("wage_fen", 0),
                "social_fen": cs.get("social_fen", 0),
                "bonus_fen": cs.get("bonus_fen", 0),
                "total_fen": cs.get("total_fen", 0),
            }
        )

    return {
        "employee_id": employee_id,
        "total_hours": total_hours,
        "total_cost_fen": total_cost_fen,
        "stores": stores_detail,
    }


def generate_summary_report(
    all_employees_cost_split: List[Dict[str, Any]],
) -> dict:
    """薪资汇总表：按门店汇总所有员工的成本分摊。

    Args:
        all_employees_cost_split: 每个元素为
            {"employee_id": "xxx", "cost_split": {"store_a": {"wage_fen":..., ...}, ...}}

    Returns:
        {
            "stores": {
                "store_a": {
                    "employee_count": 3,
                    "total_wage_fen": X,
                    "total_social_fen": X,
                    "total_bonus_fen": X,
                    "grand_total_fen": X
                },
                ...
            },
            "grand_total_fen": X
        }
    """
    store_summary: Dict[str, Dict[str, Any]] = {}

    for item in all_employees_cost_split:
        cost_split = item.get("cost_split", {})
        for store_id, costs in cost_split.items():
            if store_id not in store_summary:
                store_summary[store_id] = {
                    "employee_count": 0,
                    "total_wage_fen": 0,
                    "total_social_fen": 0,
                    "total_bonus_fen": 0,
                    "grand_total_fen": 0,
                    "employees": set(),
                }
            s = store_summary[store_id]
            emp_id = item.get("employee_id", "")
            if emp_id not in s["employees"]:
                s["employees"].add(emp_id)
                s["employee_count"] += 1
            s["total_wage_fen"] += costs.get("wage_fen", 0)
            s["total_social_fen"] += costs.get("social_fen", 0)
            s["total_bonus_fen"] += costs.get("bonus_fen", 0)
            s["grand_total_fen"] += costs.get("total_fen", 0)

    # 清理 set（不可序列化）
    grand_total = 0
    for store_id in store_summary:
        store_summary[store_id].pop("employees", None)
        grand_total += store_summary[store_id]["grand_total_fen"]

    return {
        "stores": store_summary,
        "grand_total_fen": grand_total,
    }


def generate_cost_analysis_report(
    summary: dict,
    budget_data: Dict[str, int],
) -> dict:
    """成本分析表：实际 vs 预算 + 环比。

    Args:
        summary: generate_summary_report 的结果
        budget_data: 各门店预算
            {"store_a": {"budget_fen": X, "last_period_fen": X}, ...}

    Returns:
        {
            "stores": {
                "store_a": {
                    "actual_fen": X,
                    "budget_fen": X,
                    "variance_fen": X,         # 实际 - 预算
                    "variance_rate": 0.05,     # 偏差比率
                    "last_period_fen": X,
                    "mom_change_fen": X,       # 环比变化金额
                    "mom_rate": 0.03           # 环比变化率
                },
                ...
            },
            "total_actual_fen": X,
            "total_budget_fen": X,
            "total_variance_fen": X
        }
    """
    stores_analysis: Dict[str, Dict[str, Any]] = {}
    total_actual = 0
    total_budget = 0

    store_summaries = summary.get("stores", {})

    # 汇总所有出现的门店（summary + budget_data）
    all_stores = set(store_summaries.keys()) | set(budget_data.keys())

    for store_id in sorted(all_stores):
        actual = store_summaries.get(store_id, {}).get("grand_total_fen", 0)
        budget_info = budget_data.get(store_id, {})
        budget = budget_info.get("budget_fen", 0)
        last_period = budget_info.get("last_period_fen", 0)

        variance = actual - budget
        variance_rate = round(variance / budget, 6) if budget != 0 else 0.0

        mom_change = actual - last_period
        mom_rate = round(mom_change / last_period, 6) if last_period != 0 else 0.0

        stores_analysis[store_id] = {
            "actual_fen": actual,
            "budget_fen": budget,
            "variance_fen": variance,
            "variance_rate": variance_rate,
            "last_period_fen": last_period,
            "mom_change_fen": mom_change,
            "mom_rate": mom_rate,
        }

        total_actual += actual
        total_budget += budget

    return {
        "stores": stores_analysis,
        "total_actual_fen": total_actual,
        "total_budget_fen": total_budget,
        "total_variance_fen": total_actual - total_budget,
    }
