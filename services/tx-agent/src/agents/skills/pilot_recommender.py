"""试点门店推荐 Agent — P1 | 云端

试点门店筛选、门店画像对比、试点方案设计、试点效果监测、推广可行性评估、门店聚类分析。
扩展：一键从情报建议创建试点计划、活跃试点状态汇总。
"""
import uuid
from typing import Any

from ..base import AgentResult, SkillAgent

# 门店评估维度
STORE_EVAL_DIMENSIONS = [
    "客流量", "客单价", "会员占比", "服务评分", "管理能力", "位置优势", "设备完备度",
]


class PilotRecommenderAgent(SkillAgent):
    agent_id = "pilot_recommender"
    agent_name = "试点门店推荐"
    description = "试点门店筛选、门店画像对比、试点方案设计、效果监测、推广可行性、门店聚类"
    priority = "P1"
    run_location = "cloud"

    def get_supported_actions(self) -> list[str]:
        return [
            "recommend_pilot_stores",
            "compare_store_profiles",
            "design_pilot_plan",
            "monitor_pilot_effect",
            "assess_rollout_feasibility",
            "cluster_stores",
            "create_pilot_from_recommendation",
            "get_pilot_status_summary",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "recommend_pilot_stores": self._recommend_pilots,
            "compare_store_profiles": self._compare_profiles,
            "design_pilot_plan": self._design_plan,
            "monitor_pilot_effect": self._monitor_effect,
            "assess_rollout_feasibility": self._assess_rollout,
            "cluster_stores": self._cluster_stores,
            "create_pilot_from_recommendation": self._create_pilot_from_recommendation,
            "get_pilot_status_summary": self._get_pilot_status_summary,
        }
        handler = dispatch.get(action)
        if handler:
            return await handler(params)
        return AgentResult(success=False, action=action, error=f"不支持的操作: {action}")

    async def _recommend_pilots(self, params: dict) -> AgentResult:
        """试点门店筛选"""
        stores = params.get("stores", [])
        project_type = params.get("project_type", "新品试销")
        pilot_count = params.get("pilot_count", 3)
        requirements = params.get("requirements", [])

        scored = []
        for s in stores:
            score = 0
            # 基础指标评分
            score += min(25, s.get("daily_traffic", 0) / 20)  # 客流量
            score += min(20, s.get("avg_rating", 0) * 4)  # 服务评分
            score += min(15, s.get("member_pct", 0) / 5)  # 会员占比
            score += min(15, s.get("manager_score", 0) / 7)  # 管理能力
            score += 10 if s.get("has_full_equipment") else 0  # 设备完备
            score += 10 if s.get("is_representative") else 0  # 代表性
            score += 5 if s.get("past_pilot_success") else 0  # 历史试点成功

            # 特殊要求匹配
            for req in requirements:
                if req in s.get("features", []):
                    score += 5

            scored.append({
                "store_id": s.get("store_id"),
                "store_name": s.get("store_name", ""),
                "city": s.get("city", ""),
                "district": s.get("district", ""),
                "pilot_score": round(score, 1),
                "daily_traffic": s.get("daily_traffic", 0),
                "avg_rating": s.get("avg_rating", 0),
                "member_pct": s.get("member_pct", 0),
            })

        scored.sort(key=lambda x: x["pilot_score"], reverse=True)
        recommended = scored[:pilot_count]

        return AgentResult(
            success=True, action="recommend_pilot_stores",
            data={
                "recommended": recommended,
                "project_type": project_type,
                "total_evaluated": len(stores),
                "pilot_count": len(recommended),
                "avg_score": round(sum(r["pilot_score"] for r in recommended) / max(1, len(recommended)), 1),
            },
            reasoning=f"为「{project_type}」推荐 {len(recommended)} 家试点门店，"
                      f"平均评分 {sum(r['pilot_score'] for r in recommended) / max(1, len(recommended)):.1f}",
            confidence=0.8,
        )

    async def _compare_profiles(self, params: dict) -> AgentResult:
        """门店画像对比"""
        stores = params.get("stores", [])

        if len(stores) < 2:
            return AgentResult(success=False, action="compare_store_profiles", error="至少需要2家门店进行对比")

        dimensions = ["daily_revenue_yuan", "daily_traffic", "avg_ticket_yuan", "member_pct",
                     "avg_rating", "staff_count", "table_count"]

        comparison = []
        for s in stores:
            profile = {
                "store_id": s.get("store_id"),
                "store_name": s.get("store_name", ""),
            }
            for dim in dimensions:
                profile[dim] = s.get(dim, 0)
            comparison.append(profile)

        # 找出各维度的最优门店
        best_in = {}
        for dim in dimensions:
            best_store = max(comparison, key=lambda x: x.get(dim, 0))
            best_in[dim] = best_store["store_name"]

        return AgentResult(
            success=True, action="compare_store_profiles",
            data={
                "comparison": comparison,
                "dimensions": dimensions,
                "best_in_each": best_in,
                "total_stores": len(stores),
            },
            reasoning=f"对比 {len(stores)} 家门店画像，涵盖 {len(dimensions)} 个维度",
            confidence=0.85,
        )

    async def _design_plan(self, params: dict) -> AgentResult:
        """试点方案设计"""
        project_name = params.get("project_name", "")
        pilot_stores = params.get("pilot_stores", [])
        duration_days = params.get("duration_days", 14)
        kpis = params.get("kpis", [])

        plan = {
            "project_name": project_name,
            "pilot_stores": [{"store_id": s.get("store_id"), "store_name": s.get("store_name")} for s in pilot_stores],
            "duration_days": duration_days,
            "phases": [
                {"phase": "准备期", "days": "D-7 到 D-1", "tasks": ["培训门店人员", "准备物料", "配置系统", "确认KPI"]},
                {"phase": "试点期", "days": f"D1 到 D{duration_days}", "tasks": ["每日数据收集", "问题记录", "周中复盘"]},
                {"phase": "总结期", "days": f"D{duration_days + 1} 到 D{duration_days + 3}", "tasks": ["数据汇总", "效果评估", "推广决策"]},
            ],
            "kpis": kpis if kpis else ["日均销量", "顾客满意度", "操作效率", "毛利率"],
            "control_group": "未参与试点的同类型门店",
            "data_collection_frequency": "每日",
            "escalation_rules": [
                "任一KPI下降超过20%，立即上报",
                "顾客投诉激增，暂停试点评估",
            ],
        }

        return AgentResult(
            success=True, action="design_pilot_plan",
            data=plan,
            reasoning=f"设计「{project_name}」试点方案: {len(pilot_stores)}家门店，{duration_days}天",
            confidence=0.85,
        )

    async def _monitor_effect(self, params: dict) -> AgentResult:
        """试点效果监测"""
        pilot_data = params.get("pilot_data", [])
        control_data = params.get("control_data", [])
        kpis = params.get("kpis", [])

        metrics = []
        for kpi in kpis:
            pilot_value = sum(d.get(kpi, 0) for d in pilot_data) / max(1, len(pilot_data))
            control_value = sum(d.get(kpi, 0) for d in control_data) / max(1, len(control_data))
            lift = round((pilot_value - control_value) / max(0.01, control_value) * 100, 1)

            metrics.append({
                "kpi": kpi,
                "pilot_avg": round(pilot_value, 2),
                "control_avg": round(control_value, 2),
                "lift_pct": lift,
                "status": "达标" if lift > 0 else "未达标",
            })

        overall_positive = sum(1 for m in metrics if m["lift_pct"] > 0)

        return AgentResult(
            success=True, action="monitor_pilot_effect",
            data={
                "metrics": metrics,
                "overall_assessment": "正面" if overall_positive > len(metrics) / 2 else "待观察",
                "pilot_stores_count": len(pilot_data),
                "control_stores_count": len(control_data),
            },
            reasoning=f"试点监测: {overall_positive}/{len(metrics)} 个KPI正向，"
                      f"整体{'正面' if overall_positive > len(metrics) / 2 else '待观察'}",
            confidence=0.8,
        )

    async def _assess_rollout(self, params: dict) -> AgentResult:
        """推广可行性评估"""
        pilot_results = params.get("pilot_results", {})
        total_stores = params.get("total_stores", 0)
        rollout_budget_fen = params.get("rollout_budget_fen", 0)

        kpi_pass_rate = pilot_results.get("kpi_pass_rate", 0)
        customer_satisfaction = pilot_results.get("customer_satisfaction", 0)
        operational_feasibility = pilot_results.get("operational_feasibility_score", 0)
        roi = pilot_results.get("roi", 0)

        # 综合评估
        readiness_score = round(
            kpi_pass_rate * 0.3 + customer_satisfaction * 0.25 +
            operational_feasibility * 0.25 + min(100, roi * 20) * 0.2, 1)

        decision = "全面推广" if readiness_score >= 75 else "分批推广" if readiness_score >= 55 else "继续试点" if readiness_score >= 40 else "暂停推广"

        rollout_plan = None
        if decision in ("全面推广", "分批推广"):
            batch_size = total_stores if decision == "全面推广" else max(5, total_stores // 3)
            rollout_plan = {
                "strategy": decision,
                "first_batch_stores": batch_size,
                "total_stores": total_stores,
                "estimated_rollout_weeks": max(1, total_stores // batch_size * 2),
                "estimated_cost_yuan": round(rollout_budget_fen / 100, 2),
            }

        return AgentResult(
            success=True, action="assess_rollout_feasibility",
            data={
                "readiness_score": readiness_score,
                "decision": decision,
                "evaluation": {
                    "kpi_pass_rate": kpi_pass_rate,
                    "customer_satisfaction": customer_satisfaction,
                    "operational_feasibility": operational_feasibility,
                    "roi": roi,
                },
                "rollout_plan": rollout_plan,
            },
            reasoning=f"推广可行性评分 {readiness_score}，决策: {decision}",
            confidence=0.75,
        )

    async def _cluster_stores(self, params: dict) -> AgentResult:
        """门店聚类分析"""
        stores = params.get("stores", [])

        # 简化聚类：按客流+客单价二维分4类
        if not stores:
            return AgentResult(success=False, action="cluster_stores", error="无门店数据")

        traffic_values = [s.get("daily_traffic", 0) for s in stores]
        ticket_values = [s.get("avg_ticket_fen", 0) for s in stores]
        traffic_mid = sorted(traffic_values)[len(traffic_values) // 2]
        ticket_mid = sorted(ticket_values)[len(ticket_values) // 2]

        clusters = {
            "高流量高客单": [],
            "高流量低客单": [],
            "低流量高客单": [],
            "低流量低客单": [],
        }

        for s in stores:
            traffic = s.get("daily_traffic", 0)
            ticket = s.get("avg_ticket_fen", 0)

            if traffic >= traffic_mid and ticket >= ticket_mid:
                cluster = "高流量高客单"
            elif traffic >= traffic_mid and ticket < ticket_mid:
                cluster = "高流量低客单"
            elif traffic < traffic_mid and ticket >= ticket_mid:
                cluster = "低流量高客单"
            else:
                cluster = "低流量低客单"

            clusters[cluster].append({
                "store_id": s.get("store_id"),
                "store_name": s.get("store_name", ""),
                "daily_traffic": traffic,
                "avg_ticket_yuan": round(ticket / 100, 2),
                "cluster": cluster,
            })

        return AgentResult(
            success=True, action="cluster_stores",
            data={
                "clusters": {k: {"count": len(v), "stores": v[:5]} for k, v in clusters.items()},
                "total_stores": len(stores),
                "traffic_median": traffic_mid,
                "ticket_median_yuan": round(ticket_mid / 100, 2),
            },
            reasoning="门店聚类: " + ", ".join(f"{k}{len(v)}家" for k, v in clusters.items() if v),
            confidence=0.75,
        )

    async def _create_pilot_from_recommendation(self, params: dict) -> AgentResult:
        """一键从情报建议创建试点计划（draft 状态）

        params 示例：
        {
            "tenant_id": "uuid",
            "recommendation_data": {
                "name": "引入麻辣香锅试点",
                "pilot_type": "new_dish",
                "hypothesis": "引入麻辣香锅可提升年轻客群复购率15%",
                "recommendation_source": "intel_report",
                "source_ref_id": "uuid",
                "start_date": "2026-04-01",
                "end_date": "2026-04-14",
                "success_criteria": [{"metric": "total_sales", "operator": "gt", "threshold": 30}]
            },
            "target_stores": [{"store_id": "uuid", "store_name": "长沙解放西店"}],
            "control_stores": []
        }
        """
        tenant_id_str = params.get("tenant_id", "")
        recommendation_data = params.get("recommendation_data", {})
        target_stores = params.get("target_stores", [])
        control_stores = params.get("control_stores", [])

        if not tenant_id_str:
            return AgentResult(success=False, action="create_pilot_from_recommendation", error="缺少 tenant_id")
        if not recommendation_data.get("name"):
            return AgentResult(success=False, action="create_pilot_from_recommendation", error="缺少试点名称")
        if not target_stores:
            return AgentResult(success=False, action="create_pilot_from_recommendation", error="缺少目标门店列表")

        pilot_draft = {
            "pilot_id": str(uuid.uuid4()),
            "tenant_id": tenant_id_str,
            "name": recommendation_data.get("name", ""),
            "pilot_type": recommendation_data.get("pilot_type", "new_dish"),
            "recommendation_source": recommendation_data.get("recommendation_source", "intel_report"),
            "source_ref_id": recommendation_data.get("source_ref_id"),
            "hypothesis": recommendation_data.get("hypothesis", ""),
            "target_stores": target_stores,
            "control_stores": control_stores,
            "start_date": recommendation_data.get("start_date", ""),
            "end_date": recommendation_data.get("end_date", ""),
            "status": "draft",
            "success_criteria": recommendation_data.get("success_criteria", []),
            "note": "由 Agent 自动从情报建议生成，需人工确认后激活",
        }

        return AgentResult(
            success=True, action="create_pilot_from_recommendation",
            data={
                "pilot_draft": pilot_draft,
                "next_step": "调用 POST /api/v1/pilots 提交此草稿，再调用 POST /api/v1/pilots/{id}/activate 激活",
                "stores_selected": len(target_stores),
            },
            reasoning=f"从情报建议生成试点草稿「{pilot_draft['name']}」，"
                      f"目标 {len(target_stores)} 家门店，等待人工确认",
            confidence=0.85,
        )

    async def _get_pilot_status_summary(self, params: dict) -> AgentResult:
        """所有活跃试点的状态汇总

        params: {"active_pilots": [...]}  — 传入从 pilot_programs 查询到的活跃试点列表
        """
        active_pilots = params.get("active_pilots", [])

        summary = []
        for p in active_pilots:
            days_elapsed = p.get("days_elapsed", 0)
            total_days = p.get("total_days", 1)
            progress_pct = round(days_elapsed / max(1, total_days) * 100, 1)

            status_flag = "正常"
            if p.get("kpi_pass_rate", 0) < 0.4:
                status_flag = "预警：KPI达标率偏低"
            elif progress_pct >= 80 and p.get("kpi_pass_rate", 0) >= 0.8:
                status_flag = "优秀：可提前收尾"

            summary.append({
                "pilot_id": p.get("pilot_id", ""),
                "name": p.get("name", ""),
                "pilot_type": p.get("pilot_type", ""),
                "progress_pct": progress_pct,
                "days_remaining": max(0, total_days - days_elapsed),
                "kpi_pass_rate": p.get("kpi_pass_rate", 0),
                "status_flag": status_flag,
                "store_count": len(p.get("target_stores", [])),
            })

        summary.sort(key=lambda x: x["progress_pct"], reverse=True)
        warning_count = sum(1 for s in summary if "预警" in s["status_flag"])

        return AgentResult(
            success=True, action="get_pilot_status_summary",
            data={
                "active_count": len(summary),
                "warning_count": warning_count,
                "pilots": summary,
            },
            reasoning=f"汇总 {len(summary)} 个活跃试点，{warning_count} 个预警",
            confidence=0.8,
        )
