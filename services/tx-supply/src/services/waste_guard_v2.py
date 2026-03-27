"""损耗监控V2 — V1深度版(579行) → 替换V3

TOP5损耗 + 根因分析 + 整改跟踪 + AI预测

与 waste_guard_service.py (V3纯函数) 配合：
- waste_guard_service.py: 底层计算（损耗率/分级/TOP5构建）
- waste_guard_v2.py: 业务编排层，整合记录/分析/整改/预测

金额单位统一为"分"(fen)，重量单位"千克"(kg)。
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from services.waste_guard_service import (
    ROOT_CAUSE_ACTIONS,
    action_for_causes,
    build_top5_item,
    build_waste_rate_summary,
    classify_waste_status,
    compute_waste_change,
    compute_waste_rate,
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  损耗类型 & 根因映射
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

WASTE_TYPES = {
    "expired": "过期",
    "spoiled": "变质",
    "overproduction": "超产",
    "damage": "破损",
    "theft": "盗损",
    "other": "其他",
}

# 根因分析映射（损耗类型 → 可能的根本原因）
ROOT_CAUSE_MAP: Dict[str, List[Dict[str, Any]]] = {
    "expired": [
        {"root_cause": "over_procurement", "probability": 0.45, "description": "采购量过大，超出消耗速度"},
        {"root_cause": "demand_overestimate", "probability": 0.30, "description": "需求预测过高"},
        {"root_cause": "fifo_violation", "probability": 0.25, "description": "未遵循先进先出原则"},
    ],
    "spoiled": [
        {"root_cause": "temperature_issue", "probability": 0.40, "description": "储存温度不达标"},
        {"root_cause": "handling_error", "probability": 0.30, "description": "操作不规范导致污染"},
        {"root_cause": "storage_duration", "probability": 0.30, "description": "储存时间过长"},
    ],
    "overproduction": [
        {"root_cause": "prep_overestimate", "probability": 0.50, "description": "备餐量预估过高"},
        {"root_cause": "demand_drop", "probability": 0.30, "description": "突发客流下降（天气/事件）"},
        {"root_cause": "menu_change", "probability": 0.20, "description": "菜品调整导致剩余"},
    ],
    "damage": [
        {"root_cause": "handling_error", "probability": 0.50, "description": "搬运/操作不当"},
        {"root_cause": "packaging_issue", "probability": 0.30, "description": "包装防护不足"},
        {"root_cause": "equipment_issue", "probability": 0.20, "description": "设备故障导致损坏"},
    ],
    "theft": [
        {"root_cause": "internal_control", "probability": 0.60, "description": "内控流程薄弱"},
        {"root_cause": "monitoring_gap", "probability": 0.40, "description": "监控盲区"},
    ],
    "other": [
        {"root_cause": "unknown", "probability": 1.0, "description": "原因待排查"},
    ],
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  食材成本参考（长沙餐饮市场 2026）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

INGREDIENT_COST_PER_KG_FEN: Dict[str, int] = {
    "ING001": 4_000,   # 猪肉 40元/kg
    "ING002": 5_000,   # 牛肉 50元/kg
    "ING003": 3_000,   # 鸡肉 30元/kg
    "ING004": 8_000,   # 鲜虾 80元/kg
    "ING005": 12_000,  # 活鱼 120元/kg
    "ING006": 800,     # 大米 8元/kg
    "ING007": 600,     # 面粉 6元/kg
    "ING008": 1_200,   # 食用油 12元/kg
    "ING009": 500,     # 青菜 5元/kg
    "ING010": 1_500,   # 辣椒/调料 15元/kg
}

INGREDIENT_NAMES: Dict[str, str] = {
    "ING001": "猪肉",
    "ING002": "牛肉",
    "ING003": "鸡肉",
    "ING004": "鲜虾",
    "ING005": "活鱼",
    "ING006": "大米",
    "ING007": "面粉",
    "ING008": "食用油",
    "ING009": "青菜",
    "ING010": "辣椒/调料",
}


class WasteGuardV2:
    """损耗监控V2 — V1深度版

    TOP5损耗+根因分析+整改跟踪+AI预测
    """

    def __init__(self) -> None:
        self._waste_records: List[Dict[str, Any]] = []
        self._waste_counter = 0
        self._improvement_plans: Dict[str, Dict[str, Any]] = {}
        self._plan_counter = 0

    # ──────────────────────────────────────────────────────
    #  Record Waste
    # ──────────────────────────────────────────────────────

    def record_waste(
        self,
        store_id: str,
        ingredient_id: str,
        quantity_kg: float,
        waste_type: str,
        reason: str,
        recorded_by: str,
        batch_id: Optional[str] = None,
        record_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """记录损耗事件

        waste_type: expired/spoiled/overproduction/damage/theft/other

        Args:
            store_id: 门店ID
            ingredient_id: 食材ID
            quantity_kg: 损耗重量(kg)
            waste_type: 损耗类型
            reason: 损耗原因描述
            recorded_by: 记录人
            batch_id: 批次号
            record_date: 记录日期 YYYY-MM-DD
        """
        if waste_type not in WASTE_TYPES:
            return {"ok": False, "error": f"Invalid waste type: {waste_type}"}

        if quantity_kg <= 0:
            return {"ok": False, "error": "Quantity must be positive"}

        cost_per_kg = INGREDIENT_COST_PER_KG_FEN.get(ingredient_id, 2_000)
        waste_cost_fen = int(quantity_kg * cost_per_kg)

        self._waste_counter += 1
        waste_id = f"WST-{self._waste_counter:06d}"

        record = {
            "waste_id": waste_id,
            "store_id": store_id,
            "ingredient_id": ingredient_id,
            "ingredient_name": INGREDIENT_NAMES.get(ingredient_id, "未知食材"),
            "quantity_kg": quantity_kg,
            "waste_type": waste_type,
            "waste_type_label": WASTE_TYPES.get(waste_type, "其他"),
            "reason": reason,
            "cost_per_kg_fen": cost_per_kg,
            "waste_cost_fen": waste_cost_fen,
            "waste_cost_yuan": round(waste_cost_fen / 100, 2),
            "recorded_by": recorded_by,
            "batch_id": batch_id,
            "record_date": record_date or date.today().isoformat(),
            "created_at": datetime.now().isoformat(),
        }
        self._waste_records.append(record)

        return {
            "ok": True,
            "waste_id": waste_id,
            "ingredient_name": record["ingredient_name"],
            "quantity_kg": quantity_kg,
            "waste_cost_yuan": record["waste_cost_yuan"],
            "waste_type": waste_type,
        }

    # ──────────────────────────────────────────────────────
    #  Dashboard
    # ──────────────────────────────────────────────────────

    def get_waste_dashboard(
        self,
        store_id: str,
        start_date: str,
        end_date: str,
        revenue_fen: int = 0,
        prev_waste_fen: int = 0,
    ) -> Dict[str, Any]:
        """损耗看板

        TOP5 by amount, TOP5 by cost, trend, by type, by reason
        """
        records = [
            r for r in self._waste_records
            if r["store_id"] == store_id
            and start_date <= r["record_date"] <= end_date
        ]

        if not records:
            return {
                "store_id": store_id,
                "period": {"start": start_date, "end": end_date},
                "total_waste_fen": 0,
                "total_waste_yuan": 0,
                "total_quantity_kg": 0,
                "top5_by_cost": [],
                "top5_by_quantity": [],
                "by_type": {},
                "by_reason": {},
                "waste_rate_summary": None,
            }

        total_waste_fen = sum(r["waste_cost_fen"] for r in records)
        total_qty_kg = sum(r["quantity_kg"] for r in records)

        # Aggregate by ingredient
        by_ingredient: Dict[str, Dict[str, Any]] = {}
        for r in records:
            ing_id = r["ingredient_id"]
            if ing_id not in by_ingredient:
                by_ingredient[ing_id] = {
                    "ingredient_id": ing_id,
                    "ingredient_name": r["ingredient_name"],
                    "total_cost_fen": 0,
                    "total_qty_kg": 0.0,
                    "waste_types": [],
                }
            by_ingredient[ing_id]["total_cost_fen"] += r["waste_cost_fen"]
            by_ingredient[ing_id]["total_qty_kg"] += r["quantity_kg"]
            by_ingredient[ing_id]["waste_types"].append(r["waste_type"])

        # TOP5 by cost
        sorted_by_cost = sorted(
            by_ingredient.values(), key=lambda x: x["total_cost_fen"], reverse=True
        )[:5]
        top5_cost = []
        for rank, item in enumerate(sorted_by_cost, 1):
            # Get root causes from the dominant waste type
            type_counter: Dict[str, int] = {}
            for wt in item["waste_types"]:
                type_counter[wt] = type_counter.get(wt, 0) + 1
            dominant_type = max(type_counter, key=type_counter.get) if type_counter else "other"
            root_causes = ROOT_CAUSE_MAP.get(dominant_type, ROOT_CAUSE_MAP["other"])

            top5_cost.append(build_top5_item(
                rank=rank,
                item_name=item["ingredient_name"],
                waste_cost_fen=item["total_cost_fen"],
                waste_qty=item["total_qty_kg"],
                total_waste_fen=total_waste_fen,
                root_causes=root_causes,
            ))

        # TOP5 by quantity
        sorted_by_qty = sorted(
            by_ingredient.values(), key=lambda x: x["total_qty_kg"], reverse=True
        )[:5]
        top5_qty = [
            {
                "rank": rank,
                "ingredient_name": item["ingredient_name"],
                "total_qty_kg": round(item["total_qty_kg"], 2),
                "total_cost_yuan": round(item["total_cost_fen"] / 100, 2),
            }
            for rank, item in enumerate(sorted_by_qty, 1)
        ]

        # By type
        by_type: Dict[str, Dict[str, Any]] = {}
        for r in records:
            wt = r["waste_type"]
            if wt not in by_type:
                by_type[wt] = {"label": WASTE_TYPES.get(wt, wt), "count": 0, "cost_fen": 0, "qty_kg": 0.0}
            by_type[wt]["count"] += 1
            by_type[wt]["cost_fen"] += r["waste_cost_fen"]
            by_type[wt]["qty_kg"] += r["quantity_kg"]

        # Add yuan and percentage
        for wt, data in by_type.items():
            data["cost_yuan"] = round(data["cost_fen"] / 100, 2)
            data["cost_pct"] = round(data["cost_fen"] / total_waste_fen * 100, 1) if total_waste_fen > 0 else 0
            data["qty_kg"] = round(data["qty_kg"], 2)

        # Waste rate summary
        waste_rate_summary = None
        if revenue_fen > 0:
            waste_rate_summary = build_waste_rate_summary(
                waste_fen=total_waste_fen,
                revenue_fen=revenue_fen,
                prev_waste_fen=prev_waste_fen,
                start_date=start_date,
                end_date=end_date,
            )

        return {
            "store_id": store_id,
            "period": {"start": start_date, "end": end_date},
            "total_waste_fen": total_waste_fen,
            "total_waste_yuan": round(total_waste_fen / 100, 2),
            "total_quantity_kg": round(total_qty_kg, 2),
            "record_count": len(records),
            "top5_by_cost": top5_cost,
            "top5_by_quantity": top5_qty,
            "by_type": by_type,
            "waste_rate_summary": waste_rate_summary,
        }

    # ──────────────────────────────────────────────────────
    #  Root Cause Analysis
    # ──────────────────────────────────────────────────────

    def analyze_root_cause(
        self,
        store_id: str,
        ingredient_id: str,
        days: int = 30,
    ) -> Dict[str, Any]:
        """根因分析

        Root cause mapping:
        expired -> procurement quantity too high or demand overestimate
        spoiled -> storage temperature or handling
        overproduction -> prep quantity vs actual orders gap
        """
        end_date = date.today()
        start_date = end_date - timedelta(days=days)

        records = [
            r for r in self._waste_records
            if r["store_id"] == store_id
            and r["ingredient_id"] == ingredient_id
            and start_date.isoformat() <= r["record_date"] <= end_date.isoformat()
        ]

        if not records:
            return {
                "store_id": store_id,
                "ingredient_id": ingredient_id,
                "ingredient_name": INGREDIENT_NAMES.get(ingredient_id, "未知"),
                "analysis_period_days": days,
                "total_records": 0,
                "root_causes": [],
                "recommendations": ["数据不足，建议持续记录损耗事件"],
            }

        # Aggregate by waste type
        type_counts: Dict[str, int] = {}
        type_cost: Dict[str, int] = {}
        total_cost = 0
        total_qty = 0.0

        for r in records:
            wt = r["waste_type"]
            type_counts[wt] = type_counts.get(wt, 0) + 1
            type_cost[wt] = type_cost.get(wt, 0) + r["waste_cost_fen"]
            total_cost += r["waste_cost_fen"]
            total_qty += r["quantity_kg"]

        # Build root cause analysis
        root_causes: List[Dict[str, Any]] = []
        for wt, count in sorted(type_counts.items(), key=lambda x: x[1], reverse=True):
            causes = ROOT_CAUSE_MAP.get(wt, ROOT_CAUSE_MAP["other"])
            cost = type_cost.get(wt, 0)
            cost_pct = round(cost / total_cost * 100, 1) if total_cost > 0 else 0

            for cause in causes:
                root_causes.append({
                    "waste_type": wt,
                    "waste_type_label": WASTE_TYPES.get(wt, wt),
                    "root_cause": cause["root_cause"],
                    "description": cause["description"],
                    "probability": cause["probability"],
                    "occurrence_count": count,
                    "cost_fen": cost,
                    "cost_pct": cost_pct,
                })

        # Sort by weighted priority (cost * probability)
        root_causes.sort(
            key=lambda x: x["cost_fen"] * x["probability"],
            reverse=True,
        )

        # Generate recommendations
        recommendations: List[str] = []
        seen_actions: set = set()
        for rc in root_causes[:3]:
            action = ROOT_CAUSE_ACTIONS.get(rc["root_cause"], ROOT_CAUSE_ACTIONS.get("unknown", ""))
            if action and action not in seen_actions:
                recommendations.append(action)
                seen_actions.add(action)

        return {
            "store_id": store_id,
            "ingredient_id": ingredient_id,
            "ingredient_name": INGREDIENT_NAMES.get(ingredient_id, "未知"),
            "analysis_period_days": days,
            "total_records": len(records),
            "total_cost_fen": total_cost,
            "total_cost_yuan": round(total_cost / 100, 2),
            "total_quantity_kg": round(total_qty, 2),
            "type_breakdown": {
                wt: {
                    "label": WASTE_TYPES.get(wt, wt),
                    "count": cnt,
                    "cost_fen": type_cost.get(wt, 0),
                }
                for wt, cnt in type_counts.items()
            },
            "root_causes": root_causes,
            "recommendations": recommendations,
        }

    # ──────────────────────────────────────────────────────
    #  Improvement Plan
    # ──────────────────────────────────────────────────────

    def create_improvement_plan(
        self,
        store_id: str,
        waste_analysis: Dict[str, Any],
        target_reduction_pct: float = 20.0,
        duration_days: int = 30,
    ) -> Dict[str, Any]:
        """生成整改计划

        Generate actionable improvement plan with targets
        """
        self._plan_counter += 1
        plan_id = f"IMP-{self._plan_counter:06d}"

        recommendations = waste_analysis.get("recommendations", [])
        root_causes = waste_analysis.get("root_causes", [])
        current_cost = waste_analysis.get("total_cost_fen", 0)
        target_cost = int(current_cost * (1 - target_reduction_pct / 100))

        # Build action items from root causes
        action_items: List[Dict[str, Any]] = []
        for i, rc in enumerate(root_causes[:5]):
            action = ROOT_CAUSE_ACTIONS.get(rc.get("root_cause", "unknown"), "排查原因")
            action_items.append({
                "item_id": f"{plan_id}-A{i+1:02d}",
                "root_cause": rc.get("root_cause", "unknown"),
                "description": rc.get("description", ""),
                "action": action,
                "priority": "high" if i < 2 else "medium",
                "status": "pending",
                "assigned_to": None,
                "due_date": (date.today() + timedelta(days=7 * (i + 1))).isoformat(),
            })

        plan = {
            "plan_id": plan_id,
            "store_id": store_id,
            "ingredient_id": waste_analysis.get("ingredient_id"),
            "ingredient_name": waste_analysis.get("ingredient_name"),
            "status": "active",
            "created_at": datetime.now().isoformat(),
            "start_date": date.today().isoformat(),
            "end_date": (date.today() + timedelta(days=duration_days)).isoformat(),
            "baseline_cost_fen": current_cost,
            "target_cost_fen": target_cost,
            "target_reduction_pct": target_reduction_pct,
            "action_items": action_items,
            "recommendations": recommendations,
        }

        self._improvement_plans[plan_id] = plan

        return {
            "ok": True,
            "plan_id": plan_id,
            "target_reduction_pct": target_reduction_pct,
            "baseline_cost_yuan": round(current_cost / 100, 2),
            "target_cost_yuan": round(target_cost / 100, 2),
            "action_count": len(action_items),
            "duration_days": duration_days,
        }

    def track_improvement(
        self,
        plan_id: str,
    ) -> Dict[str, Any]:
        """跟踪整改效果

        Compare waste before/after improvement plan
        """
        plan = self._improvement_plans.get(plan_id)
        if not plan:
            return {"ok": False, "error": f"Plan {plan_id} not found"}

        store_id = plan["store_id"]
        ingredient_id = plan.get("ingredient_id")
        start_date = plan["start_date"]
        end_date = plan["end_date"]
        baseline_cost = plan["baseline_cost_fen"]

        # Calculate current waste since plan started
        records_since = [
            r for r in self._waste_records
            if r["store_id"] == store_id
            and (ingredient_id is None or r["ingredient_id"] == ingredient_id)
            and start_date <= r["record_date"] <= end_date
        ]

        current_cost = sum(r["waste_cost_fen"] for r in records_since)
        current_qty = sum(r["quantity_kg"] for r in records_since)

        # Calculate progress
        target_cost = plan["target_cost_fen"]
        reduction_achieved_fen = baseline_cost - current_cost
        reduction_pct = round(reduction_achieved_fen / baseline_cost * 100, 1) if baseline_cost > 0 else 0
        target_pct = plan["target_reduction_pct"]
        progress_pct = round(reduction_pct / target_pct * 100, 1) if target_pct > 0 else 0
        progress_pct = min(100, progress_pct)

        # Action item status
        actions = plan.get("action_items", [])
        completed = sum(1 for a in actions if a["status"] == "completed")
        total_actions = len(actions)

        on_track = reduction_pct >= target_pct * 0.5  # At least 50% of target

        return {
            "plan_id": plan_id,
            "store_id": store_id,
            "ingredient_name": plan.get("ingredient_name"),
            "status": plan["status"],
            "period": {"start": start_date, "end": end_date},
            "baseline_cost_yuan": round(baseline_cost / 100, 2),
            "current_cost_yuan": round(current_cost / 100, 2),
            "target_cost_yuan": round(target_cost / 100, 2),
            "reduction_achieved_yuan": round(reduction_achieved_fen / 100, 2),
            "reduction_pct": reduction_pct,
            "target_reduction_pct": target_pct,
            "progress_pct": progress_pct,
            "on_track": on_track,
            "action_items_completed": completed,
            "action_items_total": total_actions,
            "current_quantity_kg": round(current_qty, 2),
        }

    # ──────────────────────────────────────────────────────
    #  Waste Prediction
    # ──────────────────────────────────────────────────────

    def predict_waste(
        self,
        store_id: str,
        ingredient_id: str,
        days_ahead: int = 7,
    ) -> Dict[str, Any]:
        """预测损耗

        Based on historical waste patterns + demand forecast
        """
        # Get historical data (last 30 days)
        end_date = date.today()
        start_date = end_date - timedelta(days=30)

        historical = [
            r for r in self._waste_records
            if r["store_id"] == store_id
            and r["ingredient_id"] == ingredient_id
            and start_date.isoformat() <= r["record_date"] <= end_date.isoformat()
        ]

        if not historical:
            return {
                "store_id": store_id,
                "ingredient_id": ingredient_id,
                "ingredient_name": INGREDIENT_NAMES.get(ingredient_id, "未知"),
                "prediction_days": days_ahead,
                "has_data": False,
                "message": "历史数据不足，无法预测",
                "daily_predictions": [],
            }

        # Calculate daily averages
        total_qty = sum(r["quantity_kg"] for r in historical)
        total_cost = sum(r["waste_cost_fen"] for r in historical)
        days_with_data = len(set(r["record_date"] for r in historical))
        avg_daily_qty = total_qty / max(days_with_data, 1)
        avg_daily_cost = total_cost / max(days_with_data, 1)

        # Day of week pattern
        dow_waste: Dict[int, List[float]] = {i: [] for i in range(7)}
        for r in historical:
            d = date.fromisoformat(r["record_date"])
            dow_waste[d.weekday()].append(r["quantity_kg"])

        dow_avg: Dict[int, float] = {}
        for dow, vals in dow_waste.items():
            dow_avg[dow] = sum(vals) / len(vals) if vals else avg_daily_qty

        # Generate predictions
        cost_per_kg = INGREDIENT_COST_PER_KG_FEN.get(ingredient_id, 2_000)
        daily_predictions: List[Dict[str, Any]] = []
        total_predicted_cost = 0

        for d in range(days_ahead):
            pred_date = end_date + timedelta(days=d + 1)
            dow = pred_date.weekday()
            predicted_qty = round(dow_avg.get(dow, avg_daily_qty), 2)
            predicted_cost = int(predicted_qty * cost_per_kg)
            total_predicted_cost += predicted_cost

            daily_predictions.append({
                "date": pred_date.isoformat(),
                "day_of_week": pred_date.strftime("%A"),
                "predicted_qty_kg": predicted_qty,
                "predicted_cost_fen": predicted_cost,
                "predicted_cost_yuan": round(predicted_cost / 100, 2),
                "confidence": 0.75 if days_with_data >= 7 else 0.50,
            })

        return {
            "store_id": store_id,
            "ingredient_id": ingredient_id,
            "ingredient_name": INGREDIENT_NAMES.get(ingredient_id, "未知"),
            "prediction_days": days_ahead,
            "has_data": True,
            "historical_summary": {
                "days_analyzed": 30,
                "records_count": len(historical),
                "avg_daily_qty_kg": round(avg_daily_qty, 2),
                "avg_daily_cost_yuan": round(avg_daily_cost / 100, 2),
            },
            "total_predicted_cost_fen": total_predicted_cost,
            "total_predicted_cost_yuan": round(total_predicted_cost / 100, 2),
            "daily_predictions": daily_predictions,
        }

    # ──────────────────────────────────────────────────────
    #  Cost Impact
    # ──────────────────────────────────────────────────────

    def get_waste_cost_impact(
        self,
        store_id: str,
        month: str,
        revenue_fen: int = 0,
        cogs_fen: int = 0,
    ) -> Dict[str, Any]:
        """损耗成本影响分析

        Total waste cost, waste rate vs revenue, vs COGS
        """
        # Get month's records
        records = [
            r for r in self._waste_records
            if r["store_id"] == store_id
            and r["record_date"].startswith(month)
        ]

        total_waste_fen = sum(r["waste_cost_fen"] for r in records)
        total_qty_kg = sum(r["quantity_kg"] for r in records)

        waste_vs_revenue = 0.0
        waste_vs_cogs = 0.0
        if revenue_fen > 0:
            waste_vs_revenue = round(total_waste_fen / revenue_fen * 100, 2)
        if cogs_fen > 0:
            waste_vs_cogs = round(total_waste_fen / cogs_fen * 100, 2)

        # Annualized impact
        annual_waste_est = total_waste_fen * 12

        # If waste reduced by 50%, annual savings
        potential_savings = int(annual_waste_est * 0.5)

        return {
            "store_id": store_id,
            "month": month,
            "total_waste_fen": total_waste_fen,
            "total_waste_yuan": round(total_waste_fen / 100, 2),
            "total_quantity_kg": round(total_qty_kg, 2),
            "record_count": len(records),
            "waste_vs_revenue_pct": waste_vs_revenue,
            "waste_vs_cogs_pct": waste_vs_cogs,
            "annual_waste_estimate_yuan": round(annual_waste_est / 100, 2),
            "potential_annual_savings_yuan": round(potential_savings / 100, 2),
            "status": classify_waste_status(waste_vs_revenue if revenue_fen > 0 else None),
        }
