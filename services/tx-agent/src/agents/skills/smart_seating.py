"""智能排座 Agent — 全局排座优化 | 边缘+云端

灵感来源：Anolla (22-25% 更高上座率) / SevenRooms (自动排座算法)

能力：
  1. global_optimize_seating — 全局排座优化（多预约同时排最优解）
  2. predict_turnover       — 翻台时间预测
  3. balance_server_load    — 服务员负载均衡
  4. suggest_table_merge    — 拼桌/合桌建议
  5. forecast_availability  — 可用性预测

与 table_dispatch 的区别：
  table_dispatch 推荐单桌最优，smart_seating 做全局多预约排座最优化。
"""
from datetime import datetime, timedelta
from typing import Any

import structlog

from ..base import AgentResult, SkillAgent

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 区域优先级：VIP 优先分配到高级区域
PREMIUM_ZONES = {"window", "private_room", "vip", "terrace"}

# 清洁翻台所需时间（分钟）
TABLE_CLEANING_MINUTES = 5

# 容量浪费惩罚阈值
CAPACITY_WASTE_PENALTY_THRESHOLD = 2

# 拼桌等待下限（分钟）
MERGE_WAIT_THRESHOLD_MINUTES = 15

# 拼桌最大单方人数
MERGE_MAX_PARTY_SIZE = 2

# 服务员过载阈值
SERVER_OVERLOAD_RATIO = 0.8

# 翻台预测基准时间（分钟）
BASE_TURNOVER = {"lunch": 55, "dinner": 75}

# 翻台预测置信度基准
TURNOVER_BASE_CONFIDENCE = 0.80


class SmartSeatingAgent(SkillAgent):
    """全局排座优化、翻台预测、服务员负载均衡、拼桌建议、可用性预测"""

    agent_id = "smart_seating"
    agent_name = "智能排座"
    description = "全局排座优化、翻台预测、服务员负载均衡、拼桌建议、可用性预测"
    priority = "P0"
    run_location = "edge+cloud"
    agent_level = 2  # auto with rollback

    def get_supported_actions(self) -> list[str]:
        return [
            "global_optimize_seating",
            "predict_turnover",
            "balance_server_load",
            "suggest_table_merge",
            "forecast_availability",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch: dict[str, Any] = {
            "global_optimize_seating": self._global_optimize_seating,
            "predict_turnover": self._predict_turnover,
            "balance_server_load": self._balance_server_load,
            "suggest_table_merge": self._suggest_table_merge,
            "forecast_availability": self._forecast_availability,
        }
        handler = dispatch.get(action)
        if not handler:
            return AgentResult(
                success=False,
                action=action,
                error=f"不支持的操作: {action}",
            )
        return await handler(params)

    # ------------------------------------------------------------------
    # 1. 全局排座优化
    # ------------------------------------------------------------------
    async def _global_optimize_seating(self, params: dict) -> AgentResult:
        """优化所有即将到来的预约的排座方案，最大化整体收入和上座率。

        与 table_dispatch.suggest_seating 不同，这里同时考虑所有预约，
        做全局最优分配而非逐个贪心推荐。
        """
        reservations: list[dict] = params.get("upcoming_reservations", [])
        tables: list[dict] = params.get("tables", [])
        current_time_str: str | None = params.get("current_time")

        if not reservations:
            return AgentResult(
                success=True,
                action="global_optimize_seating",
                data={"seating_plan": [], "unassigned": [], "utilization_forecast": 0.0},
                reasoning="无待排预约",
                confidence=1.0,
            )

        if not tables:
            unassigned = [r["id"] for r in reservations]
            return AgentResult(
                success=True,
                action="global_optimize_seating",
                data={"seating_plan": [], "unassigned": unassigned, "utilization_forecast": 0.0},
                reasoning="无可用桌台，所有预约未分配",
                confidence=0.9,
            )

        current_time = _parse_time(current_time_str) if current_time_str else datetime.now()

        # 排序：时间 → VIP 优先 → 消费潜力降序
        sorted_reservations = sorted(
            reservations,
            key=lambda r: (
                r.get("time", ""),
                0 if r.get("is_vip") else 1,
                -(r.get("spend_potential_fen", 0)),
            ),
        )

        # 构建桌台可用时间线: table_id -> earliest_available_time
        table_availability: dict[str, datetime] = {}
        for t in tables:
            tid = t["table_id"]
            status = t.get("current_status", "free")
            if status == "free":
                table_availability[tid] = current_time
            else:
                end_est = t.get("current_guest_end_estimate")
                if end_est:
                    end_dt = _parse_time(end_est)
                    table_availability[tid] = _add_minutes(end_dt, TABLE_CLEANING_MINUTES)
                else:
                    # 未知结束时间，保守估计 60 分钟后可用
                    table_availability[tid] = _add_minutes(current_time, 60)

        table_map: dict[str, dict] = {t["table_id"]: t for t in tables}
        assigned_tables: set[str] = set()  # 已分配给某个时间段的桌台
        seating_plan: list[dict] = []
        unassigned: list[str] = []

        # 记录每张桌台的已排时间段列表 [(start, end)]
        table_schedule: dict[str, list[tuple[datetime, datetime]]] = {
            t["table_id"]: [] for t in tables
        }

        for res in sorted_reservations:
            res_id = res["id"]
            party_size = res.get("party_size", 2)
            res_time = _parse_time(res["time"]) if isinstance(res.get("time"), str) else current_time
            duration_min = res.get("duration_estimate_min", 60)
            is_vip = res.get("is_vip", False)
            preferred_zone = res.get("preferred_zone")
            spend_potential = res.get("spend_potential_fen", 0)

            res_end = _add_minutes(res_time, duration_min)

            best_table: str | None = None
            best_score: float = -999.0
            best_reasoning: str = ""

            for t in tables:
                tid = t["table_id"]
                capacity = t.get("capacity", 4)
                zone = t.get("zone", "")
                min_spend = t.get("min_spend_fen", 0)

                # 容量检查
                if capacity < party_size:
                    continue

                # 时间冲突检查
                avail_time = table_availability.get(tid, current_time)
                if avail_time > res_time:
                    continue

                # 检查已排时间段冲突
                has_conflict = False
                for sched_start, sched_end in table_schedule[tid]:
                    cleaning_end = _add_minutes(sched_end, TABLE_CLEANING_MINUTES)
                    if res_time < cleaning_end and res_end > sched_start:
                        has_conflict = True
                        break
                if has_conflict:
                    continue

                # 消费潜力 vs 最低消费
                if spend_potential > 0 and min_spend > 0 and spend_potential < min_spend:
                    continue

                # 评分
                score = 50.0

                # 容量匹配：浪费越少越好
                waste = capacity - party_size
                if waste > CAPACITY_WASTE_PENALTY_THRESHOLD:
                    score -= (waste - CAPACITY_WASTE_PENALTY_THRESHOLD) * 8
                score -= waste * 3

                # VIP 加分
                if is_vip and zone in PREMIUM_ZONES:
                    score += 25

                # 偏好区域
                if preferred_zone and zone == preferred_zone:
                    score += 20

                # 高消费客人分配大桌
                if spend_potential > 50000 and capacity >= 6:
                    score += 15
                elif spend_potential > 30000 and capacity >= 4:
                    score += 10

                # 时间间隙优化：桌台越早空出、与下一段的间隙越紧凑越好
                gap_minutes = (res_time - avail_time).total_seconds() / 60
                if gap_minutes < 10:
                    score += 10  # 紧凑利用
                elif gap_minutes < 30:
                    score += 5

                if score > best_score:
                    best_score = score
                    best_table = tid
                    factors = []
                    if waste == 0:
                        factors.append("容量完美匹配")
                    elif waste <= 2:
                        factors.append(f"浪费{waste}座可接受")
                    if is_vip and zone in PREMIUM_ZONES:
                        factors.append(f"VIP尊享{zone}区")
                    if preferred_zone and zone == preferred_zone:
                        factors.append("命中偏好区域")
                    best_reasoning = "；".join(factors) if factors else f"综合评分最优({score:.0f})"

            if best_table:
                table_schedule[best_table].append((res_time, res_end))
                seating_plan.append({
                    "reservation_id": res_id,
                    "assigned_table": best_table,
                    "score": round(best_score, 1),
                    "reasoning": best_reasoning,
                })
            else:
                unassigned.append(res_id)

        # 计算利用率预测
        total_table_minutes = len(tables) * 180  # 假设 3 小时营业窗口
        occupied_minutes = 0
        for _tid, slots in table_schedule.items():
            for start, end in slots:
                occupied_minutes += (end - start).total_seconds() / 60
        utilization = round(occupied_minutes / total_table_minutes, 4) if total_table_minutes > 0 else 0.0

        assigned_count = len(seating_plan)
        total_count = len(reservations)

        logger.info(
            "global_seating_optimized",
            tenant_id=self.tenant_id,
            store_id=self.store_id,
            total_reservations=total_count,
            assigned=assigned_count,
            unassigned=len(unassigned),
            utilization_forecast=utilization,
        )

        return AgentResult(
            success=True,
            action="global_optimize_seating",
            data={
                "seating_plan": seating_plan,
                "unassigned": unassigned,
                "utilization_forecast": utilization,
                "assigned_count": assigned_count,
                "total_reservations": total_count,
            },
            reasoning=f"全局排座完成: {assigned_count}/{total_count} 预约已分配，"
                      f"预测利用率 {utilization:.0%}，{len(unassigned)} 个未分配",
            confidence=0.85 if not unassigned else 0.70,
            inference_layer="edge",
        )

    # ------------------------------------------------------------------
    # 2. 翻台时间预测
    # ------------------------------------------------------------------
    async def _predict_turnover(self, params: dict) -> AgentResult:
        """基于用餐属性预测翻台时间（分钟）。"""
        party_size: int = params.get("party_size", 2)
        order_items_count: int = params.get("order_items_count", 5)
        has_dessert: bool = params.get("has_dessert", False)
        has_drinks: bool = params.get("has_drinks", False)
        meal_period: str = params.get("meal_period", "lunch")
        is_vip: bool = params.get("is_vip", False)
        day_of_week: int = params.get("day_of_week", 0)  # 0=Monday, 6=Sunday

        base_min = BASE_TURNOVER.get(meal_period, 65)
        factors: list[str] = [f"基础({meal_period})={base_min}min"]
        adjustment = 0

        # 人数调整
        if party_size > 6:
            adjustment += 25
            factors.append(f"大桌({party_size}人)+25min")
        elif party_size > 4:
            adjustment += 15
            factors.append(f"中桌({party_size}人)+15min")

        # 甜品
        if has_dessert:
            adjustment += 10
            factors.append("甜品+10min")

        # 饮品
        if has_drinks:
            adjustment += 8
            factors.append("饮品+8min")

        # VIP
        if is_vip:
            adjustment += 15
            factors.append("VIP+15min")

        # 周末晚餐
        is_weekend = day_of_week >= 5
        if is_weekend and meal_period == "dinner":
            adjustment += 10
            factors.append("周末晚餐+10min")

        # 菜品数量影响（超过 8 道菜额外加时间）
        if order_items_count > 12:
            extra = 10
            adjustment += extra
            factors.append(f"菜品多({order_items_count}道)+{extra}min")
        elif order_items_count > 8:
            extra = 5
            adjustment += extra
            factors.append(f"菜品较多({order_items_count}道)+{extra}min")

        predicted = base_min + adjustment

        # ±10% 方差范围
        variance_min = round(predicted * 0.9)
        variance_max = round(predicted * 1.1)

        # 置信度：因素越多越不确定
        confidence = max(0.55, TURNOVER_BASE_CONFIDENCE - len(factors) * 0.03)

        logger.info(
            "turnover_predicted",
            tenant_id=self.tenant_id,
            party_size=party_size,
            meal_period=meal_period,
            predicted_min=predicted,
        )

        return AgentResult(
            success=True,
            action="predict_turnover",
            data={
                "predicted_minutes": predicted,
                "range_min": variance_min,
                "range_max": variance_max,
                "confidence": round(confidence, 2),
                "factors": factors,
                "party_size": party_size,
                "meal_period": meal_period,
            },
            reasoning=f"预测翻台 {predicted}min (范围 {variance_min}-{variance_max})，"
                      f"基于 {len(factors)} 个因素",
            confidence=round(confidence, 2),
            inference_layer="edge",
        )

    # ------------------------------------------------------------------
    # 3. 服务员负载均衡
    # ------------------------------------------------------------------
    async def _balance_server_load(self, params: dict) -> AgentResult:
        """为新分配的桌台推荐最优服务员，保持负载均衡。"""
        servers: list[dict] = params.get("servers", [])
        new_table: dict = params.get("new_assignment_table", {})

        if not servers:
            return AgentResult(
                success=False,
                action="balance_server_load",
                error="无可用服务员数据",
            )

        table_zone = new_table.get("zone", "")
        is_vip_table = new_table.get("zone", "") in PREMIUM_ZONES

        # 筛选同区域服务员（如有），否则全部参与
        zone_servers = [s for s in servers if s.get("zone") == table_zone]
        candidates = zone_servers if zone_servers else servers

        scored: list[dict] = []
        alerts: list[str] = []

        for s in candidates:
            sid = s["id"]
            name = s.get("name", sid)
            current_tables = s.get("current_tables", 0)
            max_tables = s.get("max_tables", 5)
            skill_level = s.get("skill_level", 1)

            load_ratio = current_tables / max_tables if max_tables > 0 else 1.0

            # 过载警告
            if load_ratio >= SERVER_OVERLOAD_RATIO:
                alerts.append(f"{name} 负载已达 {load_ratio:.0%} ({current_tables}/{max_tables})")

            # 评分：负载越低越好
            score = (1 - load_ratio) * 60

            # 技能等级对 VIP 桌台加分
            if is_vip_table:
                score += skill_level * 10
            else:
                score += skill_level * 3

            # 同区域加分
            if s.get("zone") == table_zone:
                score += 15

            scored.append({
                "server_id": sid,
                "server_name": name,
                "score": round(score, 1),
                "current_load": f"{current_tables}/{max_tables}",
                "load_ratio": round(load_ratio, 2),
                "skill_level": skill_level,
            })

        scored.sort(key=lambda x: x["score"], reverse=True)
        recommended = scored[0] if scored else None

        # 所有服务员的负载分布
        load_distribution = [
            {
                "server_id": s["id"],
                "server_name": s.get("name", s["id"]),
                "current_tables": s.get("current_tables", 0),
                "max_tables": s.get("max_tables", 5),
            }
            for s in servers
        ]

        logger.info(
            "server_load_balanced",
            tenant_id=self.tenant_id,
            recommended_server=recommended["server_id"] if recommended else None,
            alerts_count=len(alerts),
        )

        return AgentResult(
            success=True,
            action="balance_server_load",
            data={
                "recommended_server": recommended,
                "alternatives": scored[1:3],
                "load_distribution": load_distribution,
                "alerts": alerts,
                "table_zone": table_zone,
                "is_vip_table": is_vip_table,
            },
            reasoning=f"推荐服务员 {recommended['server_name'] if recommended else '无'}，"
                      f"评分 {recommended['score'] if recommended else 0}，"
                      f"{len(alerts)} 条过载警告",
            confidence=0.85,
            inference_layer="edge",
        )

    # ------------------------------------------------------------------
    # 4. 拼桌/合桌建议
    # ------------------------------------------------------------------
    async def _suggest_table_merge(self, params: dict) -> AgentResult:
        """为长时间等位的小团体生成拼桌建议，释放小桌资源。"""
        waiting_parties: list[dict] = params.get("waiting_parties", [])
        available_tables: list[dict] = params.get("available_tables", [])

        # 筛选符合拼桌条件的等位组：人数 <= 2 且等待 > 15 分钟
        eligible = [
            p for p in waiting_parties
            if p.get("party_size", 1) <= MERGE_MAX_PARTY_SIZE
            and p.get("wait_minutes", 0) >= MERGE_WAIT_THRESHOLD_MINUTES
        ]

        if len(eligible) < 2:
            return AgentResult(
                success=True,
                action="suggest_table_merge",
                data={
                    "merge_suggestions": [],
                    "estimated_wait_reduction_min": 0,
                    "eligible_parties": len(eligible),
                },
                reasoning=f"仅 {len(eligible)} 组符合拼桌条件（需 >=2 组），暂无建议",
                confidence=0.9,
            )

        # 按等待时间降序，优先匹配等待最久的
        eligible.sort(key=lambda p: -p.get("wait_minutes", 0))

        # 可用于拼桌的 4 人桌
        merge_tables = [
            t for t in available_tables
            if t.get("capacity", 0) >= 4
        ]
        merge_tables.sort(key=lambda t: t.get("capacity", 99))  # 优先小桌

        suggestions: list[dict] = []
        used_parties: set[str] = set()
        used_tables: set[str] = set()

        for i in range(len(eligible)):
            p1 = eligible[i]
            p1_id = p1["id"]
            if p1_id in used_parties:
                continue

            for j in range(i + 1, len(eligible)):
                p2 = eligible[j]
                p2_id = p2["id"]
                if p2_id in used_parties:
                    continue

                combined_size = p1.get("party_size", 1) + p2.get("party_size", 1)

                # 找一张能容纳的桌子
                assigned_table: str | None = None
                for t in merge_tables:
                    tid = t.get("table_id", "")
                    if tid in used_tables:
                        continue
                    if t.get("capacity", 0) >= combined_size:
                        assigned_table = tid
                        used_tables.add(tid)
                        break

                if not assigned_table:
                    continue

                space_saved = combined_size  # 释放的小桌座位数
                suggestions.append({
                    "parties": [p1_id, p2_id],
                    "party_details": [
                        {"id": p1_id, "size": p1.get("party_size", 1), "wait_min": p1.get("wait_minutes", 0)},
                        {"id": p2_id, "size": p2.get("party_size", 1), "wait_min": p2.get("wait_minutes", 0)},
                    ],
                    "shared_table": assigned_table,
                    "combined_size": combined_size,
                    "space_saved": space_saved,
                })
                used_parties.add(p1_id)
                used_parties.add(p2_id)
                break  # p1 已匹配，下一个

        # 平均等待缩减估计
        if suggestions:
            total_wait = sum(
                s["party_details"][0]["wait_min"] + s["party_details"][1]["wait_min"]
                for s in suggestions
            )
            avg_reduction = round(total_wait / (len(suggestions) * 2) * 0.6)
        else:
            avg_reduction = 0

        logger.info(
            "table_merge_suggested",
            tenant_id=self.tenant_id,
            suggestions_count=len(suggestions),
            eligible_parties=len(eligible),
        )

        return AgentResult(
            success=True,
            action="suggest_table_merge",
            data={
                "merge_suggestions": suggestions,
                "estimated_wait_reduction_min": avg_reduction,
                "eligible_parties": len(eligible),
                "total_waiting": len(waiting_parties),
            },
            reasoning=f"生成 {len(suggestions)} 条拼桌建议，"
                      f"预计平均减少等待 {avg_reduction} 分钟，"
                      f"{len(eligible)} 组符合条件",
            confidence=0.75,
            inference_layer="edge",
        )

    # ------------------------------------------------------------------
    # 5. 可用性预测
    # ------------------------------------------------------------------
    async def _forecast_availability(self, params: dict) -> AgentResult:
        """预测目标时间点的桌台可用情况。"""
        store_id: str = params.get("store_id", self.store_id or "")
        target_time_str: str = params.get("target_time", "")
        tables: list[dict] = params.get("tables", [])
        upcoming_reservations: list[dict] = params.get("upcoming_reservations", [])

        if not tables:
            return AgentResult(
                success=False,
                action="forecast_availability",
                error="无桌台数据",
            )

        if not target_time_str:
            return AgentResult(
                success=False,
                action="forecast_availability",
                error="缺少 target_time 参数",
            )

        target_time = _parse_time(target_time_str)

        # 预约占用映射: table_id -> [(start, end)]
        reservation_schedule: dict[str, list[tuple[datetime, datetime]]] = {}
        for res in upcoming_reservations:
            assigned_table = res.get("assigned_table")
            if not assigned_table:
                continue
            res_time = _parse_time(res["time"]) if isinstance(res.get("time"), str) else target_time
            duration = res.get("duration_estimate_min", 60)
            res_end = _add_minutes(res_time, duration)
            reservation_schedule.setdefault(assigned_table, []).append((res_time, res_end))

        available_tables: list[str] = []
        by_zone: dict[str, dict] = {}

        for t in tables:
            tid = t["table_id"]
            zone = t.get("zone", "main")
            capacity = t.get("capacity", 4)
            status = t.get("current_status", "free")

            if zone not in by_zone:
                by_zone[zone] = {"total": 0, "available": 0, "tables": []}
            by_zone[zone]["total"] += 1

            # 判断目标时间是否可用
            is_available = True

            # 当前占用检查
            if status != "free":
                end_est = t.get("current_guest_end_estimate")
                if end_est:
                    end_dt = _parse_time(end_est)
                    ready_time = _add_minutes(end_dt, TABLE_CLEANING_MINUTES)
                    if ready_time > target_time:
                        is_available = False
                else:
                    # 无结束时间估计，保守认为不可用
                    is_available = False

            # 预约冲突检查
            if is_available and tid in reservation_schedule:
                for res_start, res_end in reservation_schedule[tid]:
                    buffer_end = _add_minutes(res_end, TABLE_CLEANING_MINUTES)
                    # 目标时间落在预约时间段内
                    if res_start <= target_time < buffer_end:
                        is_available = False
                        break

            if is_available:
                available_tables.append(tid)
                by_zone[zone]["available"] += 1
                by_zone[zone]["tables"].append({"table_id": tid, "capacity": capacity})

        available_count = len(available_tables)
        total_count = len(tables)

        # 如果无可用桌台，找最近可用时段（向后搜索最多 120 分钟）
        next_available_slot: str | None = None
        if available_count == 0:
            for offset_min in range(5, 125, 5):
                check_time = _add_minutes(target_time, offset_min)
                found_any = False
                for t in tables:
                    tid = t["table_id"]
                    end_est = t.get("current_guest_end_estimate")
                    if end_est:
                        ready = _add_minutes(_parse_time(end_est), TABLE_CLEANING_MINUTES)
                        if ready <= check_time:
                            # 还需检查预约冲突
                            conflict = False
                            if tid in reservation_schedule:
                                for rs, re_ in reservation_schedule[tid]:
                                    if rs <= check_time < _add_minutes(re_, TABLE_CLEANING_MINUTES):
                                        conflict = True
                                        break
                            if not conflict:
                                found_any = True
                                break
                if found_any:
                    next_available_slot = check_time.isoformat()
                    break

        # 置信度
        confidence = 0.90
        if total_count < 5:
            confidence -= 0.10
        reserved_ratio = len(upcoming_reservations) / max(total_count, 1)
        if reserved_ratio > 0.8:
            confidence -= 0.10

        logger.info(
            "availability_forecasted",
            tenant_id=self.tenant_id,
            store_id=store_id,
            target_time=target_time_str,
            available=available_count,
            total=total_count,
        )

        return AgentResult(
            success=True,
            action="forecast_availability",
            data={
                "store_id": store_id,
                "target_time": target_time_str,
                "available_at_target": available_count,
                "total_tables": total_count,
                "by_zone": by_zone,
                "next_available_slot": next_available_slot,
                "confidence": round(confidence, 2),
            },
            reasoning=f"门店 {store_id} 在 {target_time_str} 预计 {available_count}/{total_count} 张桌可用"
                      + (f"，最近可用时段 {next_available_slot}" if next_available_slot else ""),
            confidence=round(confidence, 2),
            inference_layer="edge",
        )


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _parse_time(time_str: str) -> datetime:
    """解析 ISO 格式时间字符串，兼容多种常见格式。"""
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(time_str, fmt)
        except ValueError:
            continue
    # 带时区后缀的 ISO 格式（去掉尾部 Z 或 +xx:xx）
    cleaned = time_str.replace("Z", "").split("+")[0]
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError as e:
        raise ValueError(f"无法解析时间: {time_str}") from e


def _add_minutes(dt: datetime, minutes: int) -> datetime:
    """返回 dt 加上指定分钟数后的时间。"""
    return dt + timedelta(minutes=minutes)
