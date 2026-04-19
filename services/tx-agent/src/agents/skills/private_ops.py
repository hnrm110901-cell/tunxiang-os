"""#9 私域运营 Agent — P2 | 云端

来源：private_domain + people_agent + reservation + banquet
能力：私域全链路、绩效评分、人力成本、预订、宴会

迁移自 tunxiang V2.x people_agent/agent.py + reservation/agent.py + banquet/agent.py
"""

import os
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from ..base import AgentResult, SkillAgent

logger = structlog.get_logger(__name__)


# 绩效规则（6种岗位）— 迁移自 performance/agent.py
ROLE_WEIGHTS = {
    "manager": {"revenue": 0.3, "cost_rate": 0.25, "customer_sat": 0.2, "staff_mgmt": 0.15, "compliance": 0.1},
    "waiter": {"service_count": 0.3, "tips": 0.2, "complaints": 0.2, "upsell": 0.15, "attendance": 0.15},
    "chef": {"dish_quality": 0.3, "speed": 0.25, "waste": 0.2, "consistency": 0.15, "hygiene": 0.1},
    "cashier": {"accuracy": 0.35, "speed": 0.25, "customer_sat": 0.2, "attendance": 0.2},
}


class PrivateOpsAgent(SkillAgent):
    agent_id = "private_ops"
    agent_name = "私域运营"
    description = "私域全链路运营、绩效评分、人力成本、预订管理、宴会"
    priority = "P2"
    run_location = "cloud"

    def get_supported_actions(self) -> list[str]:
        return [
            "get_private_domain_dashboard",
            "trigger_campaign",
            "advance_journey",
            "optimize_shift",
            "score_performance",
            "analyze_labor_cost",
            "warn_attendance",
            "create_reservation",
            "manage_banquet",
            "generate_beo",
            "allocate_seating",
            "check_journey_trigger",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "score_performance": self._score_performance,
            "analyze_labor_cost": self._analyze_labor_cost,
            "warn_attendance": self._warn_attendance,
            "allocate_seating": self._allocate_seating,
            "generate_beo": self._generate_beo,
            "get_private_domain_dashboard": self._pd_dashboard,
            "trigger_campaign": self._trigger_campaign,
            "advance_journey": self._advance_journey,
            "optimize_shift": self._optimize_shift,
            "create_reservation": self._create_reservation,
            "manage_banquet": self._manage_banquet,
            "check_journey_trigger": self._check_journey_trigger,
        }
        handler = dispatch.get(action)
        if handler:
            return await handler(params)
        return AgentResult(success=False, action=action, error=f"Unsupported: {action}")

    async def _score_performance(self, params: dict) -> AgentResult:
        """员工绩效评分（加权多指标）"""
        role = params.get("role", "waiter")
        metrics = params.get("metrics", {})
        weights = ROLE_WEIGHTS.get(role, ROLE_WEIGHTS["waiter"])

        dimension_scores = {}
        for dim, weight in weights.items():
            value = metrics.get(dim, 50)
            dimension_scores[dim] = {"value": value, "weight": weight, "weighted": round(value * weight, 1)}

        total = sum(d["weighted"] for d in dimension_scores.values())

        # 红线处罚
        penalties = []
        if metrics.get("food_safety_violation"):
            total = min(total, 30)
            penalties.append("食安违规（封顶30分）")
        if metrics.get("customer_complaint_serious"):
            total *= 0.7
            penalties.append("严重客诉（扣30%）")

        # 提成计算（简化）
        base_salary_fen = params.get("base_salary_fen", 500000)  # 默认5000元/月
        commission_rate = 0.03 if total >= 90 else 0.02 if total >= 70 else 0.01
        commission_fen = round(base_salary_fen * commission_rate)

        return AgentResult(
            success=True,
            action="score_performance",
            data={
                "role": role,
                "total_score": round(total, 1),
                "grade": "A" if total >= 90 else "B" if total >= 80 else "C" if total >= 60 else "D",
                "dimensions": dimension_scores,
                "penalties": penalties,
                "commission_fen": commission_fen,
                "commission_yuan": round(commission_fen / 100, 2),
            },
            reasoning=f"{role} 绩效 {total:.0f} 分，提成 ¥{commission_fen / 100:.0f}",
            confidence=0.9,
        )

    async def _analyze_labor_cost(self, params: dict) -> AgentResult:
        """人力成本分析"""
        total_wage_fen = params.get("total_wage_fen", 0)
        revenue_fen = params.get("revenue_fen", 0)
        staff_count = params.get("staff_count", 0)
        target_rate = params.get("target_rate", 0.25)

        labor_rate = total_wage_fen / revenue_fen if revenue_fen > 0 else 0
        per_capita_fen = total_wage_fen // staff_count if staff_count > 0 else 0
        over_budget_fen = max(0, total_wage_fen - int(revenue_fen * target_rate))

        return AgentResult(
            success=True,
            action="analyze_labor_cost",
            data={
                "labor_cost_rate": round(labor_rate, 4),
                "labor_cost_rate_pct": round(labor_rate * 100, 1),
                "total_wage_yuan": round(total_wage_fen / 100, 2),
                "per_capita_yuan": round(per_capita_fen / 100, 2),
                "revenue_yuan": round(revenue_fen / 100, 2),
                "target_rate": target_rate,
                "over_budget_yuan": round(over_budget_fen / 100, 2),
                "status": "critical" if labor_rate > 0.35 else "warning" if labor_rate > target_rate else "ok",
            },
            reasoning=f"人力成本率 {labor_rate * 100:.1f}%，目标 {target_rate * 100:.0f}%",
            confidence=0.9,
        )

    async def _warn_attendance(self, params: dict) -> AgentResult:
        """出勤异常预警"""
        records = params.get("records", [])
        warnings = []

        for r in records:
            emp_name = r.get("name", "")
            late_count = r.get("late_count", 0)
            absent_count = r.get("absent_count", 0)
            early_leave = r.get("early_leave_count", 0)

            total_issues = late_count + absent_count * 3 + early_leave
            if total_issues >= 5:
                level = "high"
            elif total_issues >= 3:
                level = "medium"
            elif total_issues >= 1:
                level = "low"
            else:
                continue

            warnings.append(
                {
                    "employee": emp_name,
                    "level": level,
                    "late": late_count,
                    "absent": absent_count,
                    "early_leave": early_leave,
                    "issue_score": total_issues,
                }
            )

        warnings.sort(key=lambda w: w["issue_score"], reverse=True)
        return AgentResult(
            success=True,
            action="warn_attendance",
            data={"warnings": warnings, "total": len(warnings)},
            reasoning=f"发现 {len(warnings)} 个出勤异常",
            confidence=0.9,
        )

    async def _allocate_seating(self, params: dict) -> AgentResult:
        """智能座位分配"""
        guest_count = params.get("guest_count", 2)
        preferences = params.get("preferences", [])  # ["包间", "靠窗"]
        tables = params.get("available_tables", [])

        if not tables:
            return AgentResult(success=False, action="allocate_seating", error="无可用桌台")

        # 匹配：座位数 >= 客人数，且尽量不浪费
        candidates = [t for t in tables if t.get("seats", 0) >= guest_count]
        if not candidates:
            candidates = tables  # 无完美匹配时选最大桌

        # 按偏好加分
        def score_table(t):
            s = 100 - abs(t.get("seats", 0) - guest_count) * 5  # 座位匹配度
            if preferences:
                for pref in preferences:
                    if pref in (t.get("area", "") + t.get("type", "")):
                        s += 50
            return s

        candidates.sort(key=score_table, reverse=True)
        best = candidates[0]

        return AgentResult(
            success=True,
            action="allocate_seating",
            data={
                "table_no": best.get("table_no"),
                "area": best.get("area"),
                "seats": best.get("seats"),
                "match_score": score_table(best),
            },
            reasoning=f"推荐桌台 {best.get('table_no')}（{best.get('area')}，{best.get('seats')}座）",
            confidence=0.85,
        )

    async def _generate_beo(self, params: dict) -> AgentResult:
        """生成宴会执行单（BEO）"""
        event_name = params.get("event_name", "宴会")
        guest_count = params.get("guest_count", 0)
        menu_items = params.get("menu_items", [])
        event_date = params.get("event_date", "")
        special_requests = params.get("special_requests", [])

        total_cost_fen = sum(item.get("price_fen", 0) * item.get("quantity", 1) for item in menu_items)

        beo = {
            "event_name": event_name,
            "event_date": event_date,
            "guest_count": guest_count,
            "menu": menu_items,
            "total_cost_yuan": round(total_cost_fen / 100, 2),
            "per_guest_yuan": round(total_cost_fen / 100 / max(1, guest_count), 2),
            "special_requests": special_requests,
            "timeline": [
                {"time": "T-7", "task": "确认菜单和人数"},
                {"time": "T-3", "task": "食材采购+场地布置准备"},
                {"time": "T-1", "task": "食材到货检查+试菜"},
                {"time": "T-0 -2h", "task": "场地布置+设备检查"},
                {"time": "T-0 -30m", "task": "全员到位+最终确认"},
            ],
        }

        return AgentResult(
            success=True,
            action="generate_beo",
            data=beo,
            reasoning=f"宴会执行单：{event_name}，{guest_count}人，¥{total_cost_fen / 100:.0f}",
            confidence=0.9,
        )

    async def _pd_dashboard(self, params: dict) -> AgentResult:
        """私域仪表盘 — 聚合 tx-member + tx-growth 真实数据"""
        member_base_url = os.getenv("TX_MEMBER_SERVICE_URL", "http://tx-member:8000")
        growth_base_url = os.getenv("TX_GROWTH_SERVICE_URL", "http://tx-growth:8000")
        tenant_id = str(params.get("tenant_id", ""))
        headers = {"X-Tenant-ID": tenant_id}

        # 构建日期范围（近 30 天）
        now = datetime.now(timezone.utc)
        end_date = now.strftime("%Y-%m-%d")
        start_date = (now.replace(day=1) if now.day > 1 else now).strftime("%Y-%m-%d")
        date_params = {"start_date": start_date, "end_date": end_date}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # 1. 获取总会员数
                growth_resp = await client.get(
                    f"{member_base_url}/api/v1/member/analytics/growth",
                    headers=headers,
                    params=date_params,
                )
                growth_resp.raise_for_status()

                # 2. 获取活跃率
                activity_resp = await client.get(
                    f"{member_base_url}/api/v1/member/analytics/activity",
                    headers=headers,
                    params=date_params,
                )
                activity_resp.raise_for_status()

                # 3. 获取流失风险数
                churn_resp = await client.get(
                    f"{member_base_url}/api/v1/member/analytics/churn-prediction",
                    headers=headers,
                )
                churn_resp.raise_for_status()

                # 4. 获取活跃旅程数
                journey_resp = await client.get(
                    f"{growth_base_url}/api/v1/growth/journeys",
                    headers=headers,
                    params={"status": "active", "size": 1},
                )
                journey_resp.raise_for_status()

        except httpx.ConnectError as e:
            logger.warning("pd_dashboard_connect_error", error=str(e))
            return AgentResult(
                success=True,
                action="get_private_domain_dashboard",
                data={
                    "degraded": True,
                    "reason": "service_unavailable",
                    "total_members": 0,
                    "active_pct": 0.0,
                    "churn_risk_count": 0,
                    "active_journeys": 0,
                },
                reasoning="内部服务连接失败，返回降级数据",
                confidence=0.3,
            )
        except httpx.TimeoutException as e:
            logger.warning("pd_dashboard_timeout", error=str(e))
            return AgentResult(
                success=True,
                action="get_private_domain_dashboard",
                data={
                    "degraded": True,
                    "reason": "timeout",
                    "total_members": 0,
                    "active_pct": 0.0,
                    "churn_risk_count": 0,
                    "active_journeys": 0,
                },
                reasoning="内部服务请求超时，返回降级数据",
                confidence=0.3,
            )
        except httpx.HTTPStatusError as e:
            logger.warning("pd_dashboard_http_error", status=e.response.status_code, error=str(e))
            return AgentResult(
                success=True,
                action="get_private_domain_dashboard",
                data={
                    "degraded": True,
                    "reason": f"http_{e.response.status_code}",
                    "total_members": 0,
                    "active_pct": 0.0,
                    "churn_risk_count": 0,
                    "active_journeys": 0,
                },
                reasoning=f"内部服务返回 HTTP {e.response.status_code}，返回降级数据",
                confidence=0.3,
            )

        growth_data = growth_resp.json().get("data", {})
        activity_data = activity_resp.json().get("data", {})
        churn_data = churn_resp.json().get("data", {})
        journey_data = journey_resp.json().get("data", {})

        total_members = growth_data.get("total", 0)
        active_pct = activity_data.get("active_rate", 0.0)
        churn_risk_count = churn_data.get("high_risk_count", 0)
        active_journeys = journey_data.get("total", 0)

        logger.info(
            "pd_dashboard_fetched",
            tenant_id=tenant_id,
            total_members=total_members,
            active_pct=active_pct,
            churn_risk_count=churn_risk_count,
            active_journeys=active_journeys,
        )

        return AgentResult(
            success=True,
            action="get_private_domain_dashboard",
            data={
                "total_members": total_members,
                "active_pct": active_pct,
                "churn_risk_count": churn_risk_count,
                "active_journeys": active_journeys,
                "last_updated": datetime.now(timezone.utc).isoformat(),
            },
            reasoning=f"私域总览: {total_members}会员，活跃率{active_pct:.1%}，{churn_risk_count}高风险流失",
            confidence=0.9,
        )

    async def _trigger_campaign(self, params: dict) -> AgentResult:
        """触发营销活动 — 激活已有活动或创建新活动"""
        campaign_id = params.get("campaign_id")
        base_url = os.getenv("TX_GROWTH_SERVICE_URL", "http://tx-growth:8000")
        tenant_id = str(params.get("tenant_id", ""))
        headers = {"X-Tenant-ID": tenant_id}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                if campaign_id:
                    resp = await client.post(
                        f"{base_url}/api/v1/growth/campaigns/{campaign_id}/activate",
                        headers=headers,
                    )
                else:
                    resp = await client.post(
                        f"{base_url}/api/v1/growth/campaigns",
                        headers=headers,
                        json=params,
                    )
                resp.raise_for_status()

        except httpx.ConnectError as e:
            logger.warning("trigger_campaign_connect_error", error=str(e))
            return AgentResult(
                success=False,
                action="trigger_campaign",
                data={"degraded": True, "reason": "service_unavailable"},
                error="tx-growth 服务不可用",
                confidence=0.0,
            )
        except httpx.TimeoutException as e:
            logger.warning("trigger_campaign_timeout", error=str(e))
            return AgentResult(
                success=False,
                action="trigger_campaign",
                data={"degraded": True, "reason": "timeout"},
                error="tx-growth 服务请求超时",
                confidence=0.0,
            )
        except httpx.HTTPStatusError as e:
            logger.warning("trigger_campaign_http_error", status=e.response.status_code, error=str(e))
            return AgentResult(
                success=False,
                action="trigger_campaign",
                data={"degraded": True, "reason": f"http_{e.response.status_code}"},
                error=f"tx-growth 返回 HTTP {e.response.status_code}",
                confidence=0.0,
            )

        data = resp.json().get("data", {})
        logger.info("trigger_campaign_success", tenant_id=tenant_id, campaign_id=campaign_id)
        return AgentResult(
            success=True,
            action="trigger_campaign",
            data={"ok": True, "campaign": data},
            reasoning=f"营销活动{'激活' if campaign_id else '创建'}成功",
            confidence=0.85,
        )

    async def _advance_journey(self, params: dict) -> AgentResult:
        """推进用户旅程到下一步"""
        journey_id = params.get("journey_id")
        customer_id = params.get("customer_id")
        base_url = os.getenv("TX_GROWTH_SERVICE_URL", "http://tx-growth:8000")
        tenant_id = str(params.get("tenant_id", ""))
        headers = {"X-Tenant-ID": tenant_id}

        if not journey_id:
            return AgentResult(
                success=False,
                action="advance_journey",
                error="缺少必要参数: journey_id",
                confidence=0.0,
            )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{base_url}/api/v1/growth/journeys/{journey_id}/advance",
                    headers=headers,
                    json={"customer_id": customer_id},
                )
                resp.raise_for_status()

        except httpx.ConnectError as e:
            logger.warning("advance_journey_connect_error", journey_id=journey_id, error=str(e))
            return AgentResult(
                success=False,
                action="advance_journey",
                data={"degraded": True, "reason": "service_unavailable"},
                error="tx-growth 服务不可用",
                confidence=0.0,
            )
        except httpx.TimeoutException as e:
            logger.warning("advance_journey_timeout", journey_id=journey_id, error=str(e))
            return AgentResult(
                success=False,
                action="advance_journey",
                data={"degraded": True, "reason": "timeout"},
                error="tx-growth 服务请求超时",
                confidence=0.0,
            )
        except httpx.HTTPStatusError as e:
            logger.warning(
                "advance_journey_http_error", journey_id=journey_id, status=e.response.status_code, error=str(e)
            )
            return AgentResult(
                success=False,
                action="advance_journey",
                data={"degraded": True, "reason": f"http_{e.response.status_code}"},
                error=f"tx-growth 返回 HTTP {e.response.status_code}",
                confidence=0.0,
            )

        data = resp.json().get("data", {})
        logger.info("advance_journey_success", tenant_id=tenant_id, journey_id=journey_id, customer_id=customer_id)
        return AgentResult(
            success=True,
            action="advance_journey",
            data=data,
            reasoning=f"旅程 {journey_id} 推进成功",
            confidence=0.9,
        )

    async def _optimize_shift(self, params: dict) -> AgentResult:
        employees = params.get("employees", [])
        forecast = params.get("traffic_forecast", [50] * 12)
        return AgentResult(
            success=True,
            action="optimize_shift",
            data={
                "schedule": [{"employee": e.get("name", ""), "shift": "09:00-17:00"} for e in employees[:10]],
                "staff_count": len(employees),
                "peak_staff": max(1, max(forecast) // 15),
            },
            reasoning=f"为 {len(employees)} 人优化排班",
            confidence=0.75,
        )

    async def _create_reservation(self, params: dict) -> AgentResult:
        guest_count = params.get("guest_count", 2)
        date = params.get("date", "")
        name = params.get("customer_name", "")
        return AgentResult(
            success=True,
            action="create_reservation",
            data={
                "reservation_id": "new",
                "guest_count": guest_count,
                "date": date,
                "customer_name": name,
                "status": "confirmed",
            },
            reasoning=f"预订已创建: {name} {guest_count}人 {date}",
            confidence=0.95,
        )

    async def _manage_banquet(self, params: dict) -> AgentResult:
        event_name = params.get("event_name", "")
        stage = params.get("stage", "lead")
        next_stage = {"lead": "confirmed", "confirmed": "executing", "executing": "review"}.get(stage, "completed")
        return AgentResult(
            success=True,
            action="manage_banquet",
            data={"event_name": event_name, "current_stage": stage, "next_stage": next_stage},
            reasoning=f"宴会 {event_name}: {stage} → {next_stage}",
            confidence=0.9,
        )

    # ─── 事件驱动：订单支付后检查私域旅程触发条件 ───

    async def _check_journey_trigger(self, params: dict) -> AgentResult:
        """trade.order.paid 事件触发：根据订单特征决定是否启动私域旅程

        触发逻辑：
        - 首次消费客户 → 触发 new_customer 欢迎旅程
        - 沉默客户（30天未来）再消费 → 触发 reactivation 召回旅程
        - 高价值订单（≥500元）→ 触发 vip_retention 维护旅程
        - 生日月消费 → 触发 birthday 关怀旅程
        """
        event_data = params.get("event_data", {})
        customer_id = params.get("customer_id") or event_data.get("customer_id")
        store_id = params.get("store_id") or self.store_id
        order_amount_fen = params.get("total_fen") or event_data.get("total_fen", 0)
        order_count = params.get("order_count") or event_data.get("order_count", 1)
        days_since_last = params.get("days_since_last_order") or event_data.get("days_since_last_order", 0)
        is_birthday_month = params.get("is_birthday_month") or event_data.get("is_birthday_month", False)

        # 若有 DB，从会员历史补充缺失字段
        if self._db and customer_id:
            from sqlalchemy import text

            row = await self._db.execute(
                text("""
                SELECT
                    COUNT(DISTINCT o.id) as order_count,
                    EXTRACT(DAY FROM NOW() - MAX(o.completed_at)) as days_since_last,
                    EXTRACT(MONTH FROM NOW()) = EXTRACT(MONTH FROM c.birth_date) as is_birthday_month
                FROM orders o
                JOIN customers c ON c.id = o.customer_id
                WHERE o.tenant_id = :tenant_id
                  AND o.customer_id = :customer_id
                  AND o.status = 'completed'
                GROUP BY c.birth_date
            """),
                {"tenant_id": self.tenant_id, "customer_id": customer_id},
            )
            r = dict(row.mappings().first() or {})
            if r:
                order_count = int(r.get("order_count") or order_count)
                days_since_last = float(r.get("days_since_last") or days_since_last)
                is_birthday_month = bool(r.get("is_birthday_month") or is_birthday_month)

        # 旅程触发规则（按优先级）
        triggered_journeys: list[dict] = []

        if order_count == 1:
            triggered_journeys.append(
                {
                    "journey_type": "new_customer",
                    "reason": "首次消费，启动欢迎旅程",
                    "priority": 1,
                }
            )

        if days_since_last >= 30 and order_count > 1:
            triggered_journeys.append(
                {
                    "journey_type": "reactivation",
                    "reason": f"沉默{int(days_since_last)}天后再消费，触发召回旅程",
                    "priority": 2,
                }
            )

        if order_amount_fen >= 50000:  # ≥500元
            triggered_journeys.append(
                {
                    "journey_type": "vip_retention",
                    "reason": f"高价值订单 ¥{order_amount_fen / 100:.0f}，触发VIP维护旅程",
                    "priority": 3,
                }
            )

        if is_birthday_month:
            triggered_journeys.append(
                {
                    "journey_type": "birthday",
                    "reason": "生日月消费，触发生日关怀旅程",
                    "priority": 4,
                }
            )

        # 取最高优先级旅程（优先级数字越小越高）
        best_journey = min(triggered_journeys, key=lambda j: j["priority"]) if triggered_journeys else None

        logger.info(
            "journey_trigger_checked",
            customer_id=customer_id,
            store_id=store_id,
            triggered_count=len(triggered_journeys),
            best_journey=best_journey.get("journey_type") if best_journey else None,
        )

        return AgentResult(
            success=True,
            action="check_journey_trigger",
            data={
                "customer_id": customer_id,
                "store_id": store_id,
                "should_trigger": len(triggered_journeys) > 0,
                "triggered_journeys": triggered_journeys,
                "recommended_journey": best_journey,
                "order_amount_fen": order_amount_fen,
                "order_count": order_count,
                "days_since_last": days_since_last,
            },
            reasoning=(f"检查旅程触发：{'触发 ' + best_journey['journey_type'] if best_journey else '无需触发旅程'}"),
            confidence=0.88,
        )
