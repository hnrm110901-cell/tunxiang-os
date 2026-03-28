"""成本偏差分析 — 理论 vs 实际差异归因

对门店某日的成本偏差进行深度分析：
- 哪些菜品偏差最大
- 哪些原料偏差最大
- 偏差原因归类
- 建议改善动作

金额单位: 分(fen), int
"""
import uuid
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

import structlog

log = structlog.get_logger()

# ─── 偏差归因类别 ───
VARIANCE_CAUSES = {
    "price_fluctuation": "采购价格波动",
    "over_portioning": "超量投料",
    "waste_excess": "损耗超标",
    "recipe_deviation": "配方偏差",
    "inventory_error": "盘点误差",
    "supplier_change": "供应商变更",
    "unknown": "原因待查",
}

# ─── 建议动作模板 ───
ACTION_TEMPLATES = {
    "price_fluctuation": "与供应商谈判价格或寻找替代供应商；考虑锁价采购合同",
    "over_portioning": "加强出品标准化培训；使用定量工具（电子秤/量杯）",
    "waste_excess": "优化备料计划，减少预制量；检查存储条件",
    "recipe_deviation": "核实BOM配方准确性；更新配方版本",
    "inventory_error": "加强盘点流程；考虑使用RFID/条码管理",
    "supplier_change": "评估新供应商的性价比；建立供应商比价机制",
    "unknown": "进一步调查，记录并追踪",
}


# ─── 纯函数 ───

def compute_dish_variance(
    dish_name: str,
    theoretical_cost_fen: int,
    actual_cost_fen: int,
    quantity_sold: int,
) -> dict:
    """纯函数：计算单个菜品的成本偏差

    Returns:
        {
            "dish_name": str,
            "theoretical_cost_fen": int,
            "actual_cost_fen": int,
            "variance_fen": int,          -- 正=超支
            "variance_rate_pct": Decimal,
            "quantity_sold": int,
            "total_variance_fen": int,    -- 偏差 * 销量
        }
    """
    variance_fen = actual_cost_fen - theoretical_cost_fen
    if theoretical_cost_fen > 0:
        variance_rate = (
            Decimal(variance_fen) / Decimal(theoretical_cost_fen) * 100
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        variance_rate = Decimal("0.00")

    return {
        "dish_name": dish_name,
        "theoretical_cost_fen": theoretical_cost_fen,
        "actual_cost_fen": actual_cost_fen,
        "variance_fen": variance_fen,
        "variance_rate_pct": variance_rate,
        "quantity_sold": quantity_sold,
        "total_variance_fen": variance_fen * quantity_sold,
    }


def classify_variance_cause(
    variance_rate_pct: Decimal,
    price_changed: bool = False,
    waste_above_target: bool = False,
) -> str:
    """纯函数：推断偏差原因

    简单规则引擎，实际项目中可升级为 ML 模型。
    """
    if price_changed:
        return "price_fluctuation"
    if waste_above_target:
        return "waste_excess"
    if abs(variance_rate_pct) > Decimal("20.00"):
        return "recipe_deviation"
    if abs(variance_rate_pct) > Decimal("10.00"):
        return "over_portioning"
    return "unknown"


def generate_actions(causes: list[str]) -> list[dict]:
    """纯函数：根据偏差原因生成建议动作"""
    seen = set()
    actions = []
    for cause in causes:
        if cause in seen:
            continue
        seen.add(cause)
        actions.append({
            "cause": cause,
            "cause_label": VARIANCE_CAUSES.get(cause, cause),
            "action": ACTION_TEMPLATES.get(cause, "进一步分析"),
        })
    return actions


def build_variance_report(
    store_id: str,
    report_date: str,
    total_theoretical_fen: int,
    total_actual_fen: int,
    dish_variances: list[dict],
    ingredient_variances: list[dict],
) -> dict:
    """纯函数：组装偏差分析报告"""
    total_variance = total_actual_fen - total_theoretical_fen
    if total_theoretical_fen > 0:
        overall_variance_rate = (
            Decimal(total_variance) / Decimal(total_theoretical_fen) * 100
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        overall_variance_rate = Decimal("0.00")

    # 按偏差绝对值排序，取前5
    top_dish_variances = sorted(
        dish_variances,
        key=lambda x: abs(x.get("total_variance_fen", 0)),
        reverse=True,
    )[:5]

    top_ingredient_variances = sorted(
        ingredient_variances,
        key=lambda x: abs(x.get("variance_fen", 0)),
        reverse=True,
    )[:5]

    # 收集所有原因
    all_causes = [d.get("cause", "unknown") for d in dish_variances if d.get("cause")]
    all_causes.extend(d.get("cause", "unknown") for d in ingredient_variances if d.get("cause"))
    actions = generate_actions(all_causes)

    return {
        "store_id": store_id,
        "date": report_date,
        "total_theoretical_cost_fen": total_theoretical_fen,
        "total_actual_cost_fen": total_actual_fen,
        "total_variance_fen": total_variance,
        "overall_variance_rate_pct": overall_variance_rate,
        "top_dish_variances": top_dish_variances,
        "top_ingredient_variances": top_ingredient_variances,
        "suggested_actions": actions,
    }


# ─── 业务函数 ───

def analyze_cost_variance(
    store_id: uuid.UUID,
    target_date: date,
    tenant_id: uuid.UUID,
    db,
) -> dict:
    """成本偏差分析入口

    Returns:
        {
            "store_id", "date",
            "total_theoretical_cost_fen", "total_actual_cost_fen",
            "total_variance_fen", "overall_variance_rate_pct",
            "top_dish_variances": [菜品偏差TOP5],
            "top_ingredient_variances": [原料偏差TOP5],
            "suggested_actions": [建议动作],
        }
    """
    # 1. 获取菜品级偏差数据
    dish_variances = _calculate_dish_level_variances(store_id, target_date, tenant_id, db)

    # 2. 获取原料级偏差数据
    ingredient_variances = _calculate_ingredient_level_variances(store_id, target_date, tenant_id, db)

    # 3. 汇总
    total_theoretical = sum(d.get("theoretical_cost_fen", 0) * d.get("quantity_sold", 1) for d in dish_variances)
    total_actual = sum(d.get("actual_cost_fen", 0) * d.get("quantity_sold", 1) for d in dish_variances)

    # 如果无菜品级数据，从原料级汇总
    if total_theoretical == 0 and total_actual == 0:
        total_theoretical = sum(d.get("theoretical_fen", 0) for d in ingredient_variances)
        total_actual = sum(d.get("actual_fen", 0) for d in ingredient_variances)

    report = build_variance_report(
        store_id=str(store_id),
        report_date=str(target_date),
        total_theoretical_fen=total_theoretical,
        total_actual_fen=total_actual,
        dish_variances=dish_variances,
        ingredient_variances=ingredient_variances,
    )

    log.info(
        "cost_variance.analyzed",
        store_id=str(store_id),
        date=str(target_date),
        variance_fen=report["total_variance_fen"],
        variance_rate=str(report["overall_variance_rate_pct"]),
        action_count=len(report["suggested_actions"]),
    )
    return report


# ─── DB 访问与计算 ───

def _calculate_dish_level_variances(
    store_id: uuid.UUID,
    target_date: date,
    tenant_id: uuid.UUID,
    db,
) -> list[dict]:
    """计算菜品级成本偏差"""
    sold_dishes = _get_daily_sold_with_costs(store_id, target_date, tenant_id, db)

    variances = []
    for dish in sold_dishes:
        theoretical = dish.get("theoretical_cost_fen", 0) or 0
        actual = dish.get("actual_cost_fen", 0) or theoretical  # 无实际成本时用理论值
        qty = dish.get("quantity_sold", 0)

        v = compute_dish_variance(
            dish_name=dish.get("dish_name", ""),
            theoretical_cost_fen=theoretical,
            actual_cost_fen=actual,
            quantity_sold=qty,
        )

        # 归因
        cause = classify_variance_cause(
            variance_rate_pct=v["variance_rate_pct"],
            price_changed=dish.get("price_changed", False),
            waste_above_target=dish.get("waste_above_target", False),
        )
        v["cause"] = cause
        v["cause_label"] = VARIANCE_CAUSES.get(cause, cause)
        v["dish_id"] = str(dish.get("dish_id", ""))

        variances.append(v)

    return variances


def _calculate_ingredient_level_variances(
    store_id: uuid.UUID,
    target_date: date,
    tenant_id: uuid.UUID,
    db,
) -> list[dict]:
    """计算原料级成本偏差（理论消耗 vs 实际消耗）"""
    if db is None:
        return []
    try:
        from sqlalchemy import text

        # 取当日实际消耗
        result = db.execute(text("""
            SELECT it.ingredient_id,
                   i.ingredient_name,
                   SUM(ABS(it.quantity)) as actual_qty,
                   SUM(ABS(it.total_cost_fen)) as actual_fen,
                   AVG(ABS(it.unit_cost_fen)) as avg_unit_price_fen
            FROM ingredient_transactions it
            JOIN ingredients i ON it.ingredient_id = i.id
            WHERE it.store_id = :store_id
              AND it.tenant_id = :tenant_id
              AND it.transaction_type = 'usage'
              AND DATE(it.transaction_time) = :target_date
              AND it.is_deleted = FALSE
            GROUP BY it.ingredient_id, i.ingredient_name
        """), {"store_id": store_id, "tenant_id": tenant_id, "target_date": target_date})

        variances = []
        for row in result.mappings().all():
            actual_fen = int(row.get("actual_fen", 0) or 0)
            # 理论消耗需要从 BOM + 销量推算（简化：用 actual * 0.95 模拟）
            theoretical_fen = int(actual_fen * Decimal("0.95"))  # 占位逻辑

            variance_fen = actual_fen - theoretical_fen
            cause = classify_variance_cause(
                variance_rate_pct=Decimal("5.26") if theoretical_fen > 0 else Decimal("0"),
            )

            variances.append({
                "ingredient_id": str(row["ingredient_id"]),
                "ingredient_name": row.get("ingredient_name", ""),
                "theoretical_fen": theoretical_fen,
                "actual_fen": actual_fen,
                "variance_fen": variance_fen,
                "cause": cause,
                "cause_label": VARIANCE_CAUSES.get(cause, cause),
            })
        return variances

    except (ImportError, AttributeError):
        return []


def _get_daily_sold_with_costs(
    store_id: uuid.UUID,
    target_date: date,
    tenant_id: uuid.UUID,
    db,
) -> list[dict]:
    """查询当日售出菜品及其理论/实际成本"""
    if db is None:
        return []
    try:
        from sqlalchemy import text
        result = db.execute(text("""
            SELECT oi.dish_id, d.dish_name,
                   SUM(oi.quantity) as quantity_sold,
                   AVG(oi.food_cost_fen) as theoretical_cost_fen,
                   d.cost_fen as dish_base_cost_fen
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.id
            JOIN dishes d ON oi.dish_id = d.id
            WHERE o.store_id = :store_id
              AND o.tenant_id = :tenant_id
              AND DATE(o.order_time) = :target_date
              AND o.status IN ('completed', 'paid')
              AND o.is_deleted = FALSE
              AND oi.is_deleted = FALSE
            GROUP BY oi.dish_id, d.dish_name, d.cost_fen
        """), {"store_id": store_id, "tenant_id": tenant_id, "target_date": target_date})
        rows = []
        for row in result.mappings().all():
            rows.append({
                "dish_id": row["dish_id"],
                "dish_name": row.get("dish_name", ""),
                "quantity_sold": int(row.get("quantity_sold", 0)),
                "theoretical_cost_fen": int(row.get("theoretical_cost_fen") or row.get("dish_base_cost_fen") or 0),
                "actual_cost_fen": int(row.get("dish_base_cost_fen") or row.get("theoretical_cost_fen") or 0),
                "price_changed": False,
                "waste_above_target": False,
            })
        return rows
    except (ImportError, AttributeError):
        return []
