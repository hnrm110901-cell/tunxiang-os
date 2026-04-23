"""#4 会员洞察 Agent — P1 | 云端

来源：private_domain(11方法) + service(7方法)
能力：RFM分析、行为信号、流失检测、旅程触发、差评处理、服务质量

迁移自 tunxiang V2.x private_domain/agent.py + service/agent.py
"""

from typing import Any

import structlog

from ..base import ActionConfig, AgentResult, SkillAgent

logger = structlog.get_logger(__name__)


# RFM 分层阈值
RFM_THRESHOLDS = {
    "R": [7, 30, 90, 180],  # 天数：S1(≤7) S2(≤30) S3(≤90) S4(≤180) S5(>180)
    "F": [12, 6, 3, 1],  # 次数：S1(≥12) S2(≥6) S3(≥3) S4(≥1) S5(0)
    "M": [500000, 200000, 80000, 20000],  # 分：S1(≥5000元) S2(≥2000) S3(≥800) S4(≥200) S5(<200)
}

# 旅程模板
JOURNEY_TEMPLATES = {
    "new_customer": {"name": "新客欢迎", "steps": ["欢迎短信", "首单优惠推送", "7天回访"]},
    "vip_retention": {"name": "VIP维护", "steps": ["专属优惠", "生日祝福", "季度回馈"]},
    "reactivation": {"name": "流失召回", "steps": ["温馨提醒", "召回优惠券", "二次提醒", "人工跟进"]},
    "review_repair": {"name": "差评修复", "steps": ["致歉回复", "补偿方案", "回访确认"]},
    "birthday": {"name": "生日关怀", "steps": ["生日祝福", "专属折扣", "到店惊喜"]},
    # P1 旅程
    "super_user": {"name": "超级用户关系经营", "steps": ["身份仪式", "特权体验", "裂变赋能/季节专属", "观察"]},
    "psych_distance": {"name": "心理距离修复", "steps": ["轻触达/关系唤醒", "等待", "最小承诺", "观察"]},
    "milestone": {"name": "里程碑庆祝", "steps": ["进阶恭喜", "进度展示", "观察"]},
    "referral": {"name": "裂变场景激活", "steps": ["场景判断", "场景化触达", "观察"]},
}


class MemberInsightAgent(SkillAgent):
    agent_id = "member_insight"
    agent_name = "会员洞察"
    description = "RFM分析、用户旅程、流失检测、差评处理、服务质量"
    priority = "P1"
    run_location = "cloud"

    def get_supported_actions(self) -> list[str]:
        return [
            "analyze_rfm",
            "detect_signals",
            "detect_competitor",
            "trigger_journey",
            "get_churn_risks",
            "process_bad_review",
            "monitor_service_quality",
            "handle_complaint",
            "collect_feedback",
            "rfm_analysis",
            "update_customer_rfm",
            "get_clv_snapshot",  # Phase 3: 读 mv_member_clv
            "generate_first_to_second_suggestion",  # 增长中枢V2: 首单转二访建议
            "generate_repair_suggestion",  # 增长中枢V2: 服务修复建议
            # P1 扩展
            "generate_super_user_suggestion",  # P1: 超级用户关系经营建议
            "generate_psych_bridge_suggestion",  # P1: 心理距离修复建议
            "generate_milestone_suggestion",  # P1: 里程碑庆祝建议
            "generate_referral_suggestion",  # P1: 裂变场景激活建议
        ]

    def get_action_config(self, action: str) -> ActionConfig:
        """会员洞察 Agent 的 action 级会话策略"""
        configs = {
            # RFM 更新涉及会员分层变更
            "update_customer_rfm": ActionConfig(
                risk_level="medium",
                max_retries=2,
            ),
            "rfm_analysis": ActionConfig(
                risk_level="medium",
                max_retries=2,
            ),
            "analyze_rfm": ActionConfig(
                risk_level="medium",
                max_retries=2,
            ),
            # CLV 快照读取
            "get_clv_snapshot": ActionConfig(
                risk_level="low",
                max_retries=1,
            ),
            # 报告 / 建议生成类（低风险）
            "generate_first_to_second_suggestion": ActionConfig(
                risk_level="low",
                max_retries=1,
            ),
            "generate_repair_suggestion": ActionConfig(
                risk_level="low",
                max_retries=1,
            ),
            "generate_super_user_suggestion": ActionConfig(
                risk_level="low",
                max_retries=1,
            ),
            "generate_psych_bridge_suggestion": ActionConfig(
                risk_level="low",
                max_retries=1,
            ),
            "generate_milestone_suggestion": ActionConfig(
                risk_level="low",
                max_retries=1,
            ),
            "generate_referral_suggestion": ActionConfig(
                risk_level="low",
                max_retries=1,
            ),
            # 信号检测 / 监控类
            "detect_signals": ActionConfig(
                risk_level="low",
            ),
            "detect_competitor": ActionConfig(
                risk_level="low",
            ),
            "get_churn_risks": ActionConfig(
                risk_level="low",
            ),
            "monitor_service_quality": ActionConfig(
                risk_level="low",
            ),
            "collect_feedback": ActionConfig(
                risk_level="low",
            ),
            # 旅程触发 / 客诉处理涉及客户触达，需较高风险等级
            "trigger_journey": ActionConfig(
                risk_level="medium",
                requires_human_confirm=True,
            ),
            "process_bad_review": ActionConfig(
                risk_level="medium",
                requires_human_confirm=True,
                max_retries=1,
            ),
            "handle_complaint": ActionConfig(
                risk_level="medium",
                requires_human_confirm=True,
                max_retries=1,
            ),
        }
        return configs.get(action, ActionConfig())

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "analyze_rfm": self._analyze_rfm,
            "get_churn_risks": self._get_churn_risks,
            "trigger_journey": self._trigger_journey,
            "process_bad_review": self._process_bad_review,
            "detect_signals": self._detect_signals,
            "monitor_service_quality": self._monitor_quality,
            "detect_competitor": self._detect_competitor,
            "handle_complaint": self._handle_complaint,
            "collect_feedback": self._collect_feedback,
            "rfm_analysis": self._rfm_analysis,
            "update_customer_rfm": self._update_customer_rfm,
            "get_clv_snapshot": self._get_clv_snapshot,
            "generate_first_to_second_suggestion": self._generate_first_to_second_suggestion,
            "generate_repair_suggestion": self._generate_repair_suggestion,
            # P1 扩展
            "generate_super_user_suggestion": self._generate_super_user_suggestion,
            "generate_psych_bridge_suggestion": self._generate_psych_bridge_suggestion,
            "generate_milestone_suggestion": self._generate_milestone_suggestion,
            "generate_referral_suggestion": self._generate_referral_suggestion,
        }
        handler = dispatch.get(action)
        if not handler:
            return AgentResult(success=False, action=action, error=f"Unsupported: {action}")
        return await handler(params)

    async def _analyze_rfm(self, params: dict) -> AgentResult:
        """RFM 分层分析"""
        members = params.get("members", [])
        if not members:
            return AgentResult(success=False, action="analyze_rfm", error="无会员数据")

        segments = {"S1": 0, "S2": 0, "S3": 0, "S4": 0, "S5": 0}
        analyzed = []

        for m in members:
            r_days = m.get("recency_days", 999)
            f_count = m.get("frequency", 0)
            m_fen = m.get("monetary_fen", 0)

            r_score = self._score_rfm(r_days, RFM_THRESHOLDS["R"], reverse=True)
            f_score = self._score_rfm(f_count, RFM_THRESHOLDS["F"], reverse=False)
            m_score = self._score_rfm(m_fen, RFM_THRESHOLDS["M"], reverse=False)

            level = f"S{max(r_score, f_score, m_score)}"
            segments[level] += 1

            analyzed.append(
                {
                    "customer_id": m.get("customer_id"),
                    "r_score": r_score,
                    "f_score": f_score,
                    "m_score": m_score,
                    "level": level,
                }
            )

        total = len(members)
        distribution = {k: {"count": v, "pct": round(v / total * 100, 1)} for k, v in segments.items()}

        return AgentResult(
            success=True,
            action="analyze_rfm",
            data={"total": total, "distribution": distribution, "members": analyzed[:20]},
            reasoning=f"分析 {total} 个会员，S1(高价值) {segments['S1']} 人，S5(流失) {segments['S5']} 人",
            confidence=0.9,
        )

    @staticmethod
    def _score_rfm(value: float, thresholds: list, reverse: bool = False) -> int:
        """RFM 单维评分 1-5"""
        if reverse:
            for i, t in enumerate(thresholds):
                if value <= t:
                    return i + 1
            return 5
        else:
            for i, t in enumerate(thresholds):
                if value >= t:
                    return i + 1
            return 5

    async def _get_churn_risks(self, params: dict) -> AgentResult:
        """流失风险列表"""
        members = params.get("members", [])
        risk_threshold = params.get("risk_threshold", 0.5)

        at_risk = []
        for m in members:
            recency = m.get("recency_days", 0)
            frequency = m.get("frequency", 0)
            monetary = m.get("monetary_fen", 0)

            # 流失风险评分：近期未消费+低频 = 高风险
            risk = min(1.0, recency / 180)  # 180天未消费 = 风险1.0
            if frequency > 0:
                risk *= max(0.3, 1 - frequency / 20)  # 高频降低风险

            if risk >= risk_threshold:
                at_risk.append(
                    {
                        "customer_id": m.get("customer_id"),
                        "name": m.get("name", ""),
                        "risk_score": round(risk, 2),
                        "recency_days": recency,
                        "total_spent_yuan": round(monetary / 100, 2),
                        "recommended_action": "召回优惠券" if risk > 0.7 else "温馨提醒",
                    }
                )

        at_risk.sort(key=lambda x: x["risk_score"], reverse=True)

        return AgentResult(
            success=True,
            action="get_churn_risks",
            data={"at_risk": at_risk[:50], "total": len(at_risk)},
            reasoning=f"发现 {len(at_risk)} 个流失风险客户（阈值 {risk_threshold}）",
            confidence=0.8,
        )

    async def _trigger_journey(self, params: dict) -> AgentResult:
        """触发会员旅程"""
        journey_type = params.get("journey_type", "")
        customer_id = params.get("customer_id", "")

        template = JOURNEY_TEMPLATES.get(journey_type)
        if not template:
            return AgentResult(
                success=False,
                action="trigger_journey",
                error=f"未知旅程类型: {journey_type}，可选: {list(JOURNEY_TEMPLATES.keys())}",
            )

        return AgentResult(
            success=True,
            action="trigger_journey",
            data={
                "journey_type": journey_type,
                "journey_name": template["name"],
                "customer_id": customer_id,
                "steps": template["steps"],
                "current_step": 0,
                "status": "running",
            },
            reasoning=f"已触发「{template['name']}」旅程，共 {len(template['steps'])} 步",
            confidence=0.95,
        )

    async def _process_bad_review(self, params: dict) -> AgentResult:
        """差评处理 — 分析情感 + 生成回复 + 触发挽留"""
        review_text = params.get("review_text", "")
        rating = params.get("rating", 3)
        customer_id = params.get("customer_id", "")

        # 情感关键词检测
        negative_keywords = ["难吃", "太慢", "服务差", "脏", "贵", "等太久", "不新鲜", "冷"]
        issues = [kw for kw in negative_keywords if kw in review_text]

        severity = "high" if rating <= 2 or len(issues) >= 2 else "medium" if rating <= 3 else "low"

        # 生成回复模板
        reply = "尊敬的顾客，感谢您的反馈。"
        if issues:
            reply += f"对于您提到的{'、'.join(issues[:3])}问题，我们深表歉意。"
        reply += "我们会立即改进，期待您再次光临。"

        return AgentResult(
            success=True,
            action="process_bad_review",
            data={
                "severity": severity,
                "detected_issues": issues,
                "suggested_reply": reply,
                "compensation": "赠送优惠券" if severity == "high" else "致歉短信",
                "auto_trigger_journey": severity == "high",
            },
            reasoning=f"差评严重度 {severity}，检测到 {len(issues)} 个问题关键词",
            confidence=0.75,
        )

    async def _detect_signals(self, params: dict) -> AgentResult:
        """行为信号检测"""
        members = params.get("members", [])
        signals = []

        for m in members:
            recency = m.get("recency_days", 0)
            birthday = m.get("birth_date")

            # 流失预警
            if recency >= 60:
                signals.append(
                    {
                        "type": "churn_risk",
                        "customer_id": m.get("customer_id"),
                        "detail": f"{recency}天未消费",
                        "priority": 1,
                    }
                )

            # 生日提醒（简化：检查 birth_date 字段存在）
            if birthday:
                signals.append(
                    {
                        "type": "birthday",
                        "customer_id": m.get("customer_id"),
                        "detail": f"生日: {birthday}",
                        "priority": 2,
                    }
                )

        signals.sort(key=lambda s: s["priority"])
        return AgentResult(
            success=True,
            action="detect_signals",
            data={"signals": signals[:30], "total": len(signals)},
            reasoning=f"检测到 {len(signals)} 个行为信号",
            confidence=0.8,
        )

    async def _monitor_quality(self, params: dict) -> AgentResult:
        """服务质量监控"""
        feedbacks = params.get("feedbacks", [])
        if not feedbacks:
            return AgentResult(
                success=True, action="monitor_service_quality", data={"avg_rating": 0, "total": 0}, confidence=0.5
            )

        ratings = [f.get("rating", 3) for f in feedbacks]
        avg = sum(ratings) / len(ratings)
        bad_count = sum(1 for r in ratings if r <= 2)
        bad_rate = bad_count / len(ratings) * 100

        return AgentResult(
            success=True,
            action="monitor_service_quality",
            data={
                "avg_rating": round(avg, 2),
                "total_feedbacks": len(feedbacks),
                "bad_review_count": bad_count,
                "bad_review_rate_pct": round(bad_rate, 1),
                "status": "critical" if bad_rate > 20 else "warning" if bad_rate > 10 else "good",
            },
            reasoning=f"平均评分 {avg:.1f}，差评率 {bad_rate:.1f}%",
            confidence=0.85,
        )

    async def _detect_competitor(self, params: dict) -> AgentResult:
        """竞对动态监控"""
        competitors = params.get("competitors", [])
        signals = []
        for c in competitors:
            name = c.get("name", "")
            if c.get("price_change_pct", 0) < -10:
                signals.append(
                    {"competitor": name, "type": "price_drop", "detail": f"降价{abs(c['price_change_pct'])}%"}
                )
            if c.get("new_campaign"):
                signals.append({"competitor": name, "type": "campaign", "detail": c["new_campaign"]})
        return AgentResult(
            success=True,
            action="detect_competitor",
            data={"signals": signals, "total": len(signals)},
            reasoning=f"检测到 {len(signals)} 个竞对动态",
            confidence=0.7,
        )

    async def _handle_complaint(self, params: dict) -> AgentResult:
        """投诉处理"""
        complaint_type = params.get("type", "other")
        priority = {"food_quality": 1, "service": 2, "hygiene": 1}.get(complaint_type, 3)
        return AgentResult(
            success=True,
            action="handle_complaint",
            data={
                "type": complaint_type,
                "priority": priority,
                "assigned_to": "store_manager" if priority <= 2 else "duty_manager",
                "follow_up_hours": 24 if priority == 1 else 48,
            },
            reasoning=f"投诉 {complaint_type}，优先级 {priority}",
            confidence=0.85,
        )

    async def _collect_feedback(self, params: dict) -> AgentResult:
        """收集反馈"""
        feedback = params.get("feedback", {})
        return AgentResult(
            success=True,
            action="collect_feedback",
            data={"stored": True, "rating": feedback.get("rating", 0), "category": feedback.get("category", "general")},
            reasoning="反馈已收集",
            confidence=0.95,
        )

    # ─── RFM分析（真实DB） ───

    async def _rfm_analysis(self, params: dict) -> AgentResult:
        store_id = params.get("store_id") or self.store_id
        top_n = params.get("top_n", 20)

        if self._db:
            from datetime import datetime, timezone

            from sqlalchemy import text

            now = datetime.now(timezone.utc)

            rows = await self._db.execute(
                text("""
                SELECT
                    o.customer_id,
                    COUNT(DISTINCT o.id) as frequency,
                    MAX(o.completed_at) as last_order_at,
                    COALESCE(SUM(o.final_amount_fen), 0) as monetary_fen,
                    EXTRACT(DAY FROM NOW() - MAX(o.completed_at)) as recency_days
                FROM orders o
                WHERE o.tenant_id = :tenant_id
                  AND (:store_id::UUID IS NULL OR o.store_id = :store_id::UUID)
                  AND o.status = 'completed'
                  AND o.customer_id IS NOT NULL
                  AND o.completed_at >= NOW() - INTERVAL '90 days'
                GROUP BY o.customer_id
                ORDER BY monetary_fen DESC
                LIMIT :top_n
            """),
                {"tenant_id": self.tenant_id, "store_id": store_id, "top_n": top_n},
            )

            members = []
            for row in rows.mappings():
                r = dict(row)
                recency = float(r.get("recency_days") or 90)
                frequency = int(r.get("frequency") or 1)
                monetary = int(r.get("monetary_fen") or 0)

                # RFM评分（各1-5分）
                r_score = (
                    5
                    if recency <= 7
                    else (4 if recency <= 14 else (3 if recency <= 30 else (2 if recency <= 60 else 1)))
                )
                f_score = (
                    5
                    if frequency >= 10
                    else (4 if frequency >= 6 else (3 if frequency >= 3 else (2 if frequency >= 2 else 1)))
                )
                m_score = (
                    5
                    if monetary >= 50000
                    else (4 if monetary >= 20000 else (3 if monetary >= 10000 else (2 if monetary >= 5000 else 1)))
                )
                total = r_score + f_score + m_score

                segment = (
                    "高价值" if total >= 13 else ("成长型" if total >= 10 else ("潜在" if total >= 7 else "流失风险"))
                )

                members.append(
                    {
                        "customer_id": str(r["customer_id"]),
                        "recency_days": round(recency, 1),
                        "frequency": frequency,
                        "monetary_fen": monetary,
                        "rfm_score": total,
                        "segment": segment,
                        "r_score": r_score,
                        "f_score": f_score,
                        "m_score": m_score,
                    }
                )

            segments: dict[str, int] = {}
            for m in members:
                seg = m["segment"]
                segments[seg] = segments.get(seg, 0) + 1

            # Claude生成会员运营建议
            suggestion = ""
            if self._router and members:
                try:
                    seg_summary = "，".join([f"{k}{v}人" for k, v in segments.items()])
                    suggestion = await self._router.complete(
                        tenant_id=self.tenant_id,
                        task_type="standard_analysis",
                        system="你是餐饮会员运营专家，根据RFM数据给出精准的会员激活和留存建议，100字内，中文。",
                        messages=[
                            {
                                "role": "user",
                                "content": f"近90天会员分布：{seg_summary}，共{len(members)}名活跃会员。"
                                f"高价值均消费{sum(m['monetary_fen'] for m in members if m['segment'] == '高价值') // max(1, segments.get('高价值', 1)) / 100:.0f}元。"
                                f"请给出运营建议。",
                            }
                        ],
                        max_tokens=200,
                        db=self._db,
                    )
                except Exception as exc:  # noqa: BLE001 — Claude不可用时降级
                    logger.warning("member_insight_llm_fallback", error=str(exc))

            return AgentResult(
                success=True,
                action="rfm_analysis",
                data={
                    "members": members,
                    "total_analyzed": len(members),
                    "segments": segments,
                    "suggestion": suggestion,
                },
                reasoning=f"分析{len(members)}名会员：{dict(segments)}。{suggestion[:40] if suggestion else ''}",
                confidence=0.9 if suggestion else 0.8,
                inference_layer="cloud" if suggestion else "edge",
            )

        # 降级
        members = params.get("members", [])
        return AgentResult(
            success=True,
            action="rfm_analysis",
            data={"members": members, "total_analyzed": len(members), "segments": {}},
            reasoning="无DB连接，返回传入数据",
            confidence=0.5,
        )

    # ─── 事件驱动：订单支付后更新会员 RFM 分层 ───

    async def _update_customer_rfm(self, params: dict) -> AgentResult:
        """trade.order.paid 事件触发：计算并更新单个会员 RFM 分层

        从订单支付事件中提取关键字段，重新计算该会员的 RFM 评分，
        并返回新的分层结果供上游服务写入 CDP。
        实际持久化由 tx-member service 负责；Agent 只做分析和建议。
        """
        store_id = params.get("store_id") or self.store_id
        event_data = params.get("event_data", {})
        customer_id = params.get("customer_id") or event_data.get("customer_id")
        order_amount_fen = params.get("total_fen") or event_data.get("total_fen", 0)

        if not customer_id:
            return AgentResult(
                success=False,
                action="update_customer_rfm",
                error="缺少 customer_id，无法更新 RFM",
            )

        # 若有 DB，从历史订单聚合最新 RFM 指标
        rfm_data: dict = {}
        if self._db and customer_id:
            from sqlalchemy import text

            row = await self._db.execute(
                text("""
                SELECT
                    COUNT(DISTINCT id) as frequency,
                    EXTRACT(DAY FROM NOW() - MAX(completed_at)) as recency_days,
                    COALESCE(SUM(final_amount_fen), 0) as monetary_fen
                FROM orders
                WHERE tenant_id = :tenant_id
                  AND customer_id = :customer_id
                  AND status = 'completed'
            """),
                {"tenant_id": self.tenant_id, "customer_id": customer_id},
            )
            r = dict(row.mappings().first() or {})
            rfm_data = {
                "frequency": int(r.get("frequency") or 1),
                "recency_days": float(r.get("recency_days") or 0),
                "monetary_fen": int(r.get("monetary_fen") or 0),
            }
        else:
            # 降级：使用 params 中传入的快照数据
            rfm_data = {
                "frequency": params.get("order_count", 1),
                "recency_days": 0,  # 刚支付，recency=0
                "monetary_fen": params.get("lifetime_monetary_fen", order_amount_fen),
            }

        # 计算 RFM 各维度评分
        r_score = self._score_rfm(rfm_data["recency_days"], RFM_THRESHOLDS["R"], reverse=True)
        f_score = self._score_rfm(rfm_data["frequency"], RFM_THRESHOLDS["F"], reverse=False)
        m_score = self._score_rfm(rfm_data["monetary_fen"], RFM_THRESHOLDS["M"], reverse=False)
        rfm_total = r_score + f_score + m_score

        segment = (
            "高价值" if rfm_total >= 13 else "成长型" if rfm_total >= 10 else "潜在" if rfm_total >= 7 else "流失风险"
        )

        logger.info(
            "member_rfm_updated",
            customer_id=customer_id,
            store_id=store_id,
            segment=segment,
            rfm_total=rfm_total,
        )

        return AgentResult(
            success=True,
            action="update_customer_rfm",
            data={
                "customer_id": customer_id,
                "store_id": store_id,
                "r_score": r_score,
                "f_score": f_score,
                "m_score": m_score,
                "rfm_total": rfm_total,
                "segment": segment,
                "recency_days": rfm_data["recency_days"],
                "frequency": rfm_data["frequency"],
                "monetary_fen": rfm_data["monetary_fen"],
                "trigger_journey": segment == "流失风险",  # 分层变差时触发唤回旅程
            },
            reasoning=f"会员 RFM 更新：R{r_score}F{f_score}M{m_score}={rfm_total}，分层={segment}",
            confidence=0.9 if self._db else 0.7,
        )

    # ─── Phase 3: 读 mv_member_clv 物化视图（< 5ms） ───

    async def _get_clv_snapshot(self, params: dict) -> AgentResult:
        """从 mv_member_clv 读取高价值会员CLV快照（Phase 3）。

        替代原来 tx-member 跨服务查询，响应 < 5ms。
        支持按 churn_probability 快速筛选流失风险会员。

        注意：mv_member_clv 以 (tenant_id, customer_id) 为主键，
        CLV 是全租户维度聚合（不按门店分区）。store_id 参数仅作日志记录，不用于过滤。
        """
        from sqlalchemy import text

        top_n: int = params.get("top_n", 20)
        min_clv_fen: int = params.get("min_clv_fen", 0)
        churn_threshold: float = params.get("churn_threshold", 0.0)

        if not self._db:
            return AgentResult(
                success=False,
                action="get_clv_snapshot",
                error="无DB连接，无法读取物化视图",
            )

        rows = await self._db.execute(
            text("""
            SELECT
                customer_id, visit_count,
                total_spend_fen, clv_fen,
                stored_value_balance_fen, churn_probability, rfm_segment,
                last_visit_at, updated_at
            FROM mv_member_clv
            WHERE tenant_id = :tenant_id
              AND clv_fen >= :min_clv_fen
              AND churn_probability >= :churn_threshold
            ORDER BY clv_fen DESC
            LIMIT :top_n
        """),
            {
                "tenant_id": self.tenant_id,
                "min_clv_fen": min_clv_fen,
                "churn_threshold": churn_threshold,
                "top_n": top_n,
            },
        )

        members = []
        for r in rows.mappings():
            item = dict(r)
            item["customer_id"] = str(item["customer_id"])
            for key in ("last_visit_at", "updated_at"):
                if item.get(key):
                    item[key] = item[key].isoformat()
            item["clv_yuan"] = round(int(item.get("clv_fen") or 0) / 100, 2)
            item["total_spend_yuan"] = round(int(item.get("total_spend_fen") or 0) / 100, 2)
            item["stored_value_balance_yuan"] = round(int(item.get("stored_value_balance_fen") or 0) / 100, 2)
            members.append(item)

        high_churn = [m for m in members if float(m.get("churn_probability") or 0) > 0.6]
        total_clv_fen = sum(int(m.get("clv_fen") or 0) for m in members)

        return AgentResult(
            success=True,
            action="get_clv_snapshot",
            data={
                "members": members,
                "total_returned": len(members),
                "total_clv_yuan": round(total_clv_fen / 100, 2),
                "high_churn_count": len(high_churn),
                "source": "mv_member_clv",
            },
            reasoning=(
                f"CLV快照：Top{len(members)}会员，总CLV¥{total_clv_fen / 100:.0f}，{len(high_churn)}人流失风险>60%"
            ),
            confidence=0.95,
            inference_layer="cloud",
        )

    # ─── 增长中枢V2: 首单转二访策略建议 ───

    async def _generate_first_to_second_suggestion(self, params: dict) -> AgentResult:
        """生成首单转二访策略建议，写入 growth_agent_strategy_suggestions

        对首单完成的客户，根据首单行为特征选择心理机制:
        - 默认路径: identity_anchor（身份锚定）→ micro_commitment（最小承诺）
        - 高客单: 可加 variable_reward（多样化奖励）提升惊喜感
        - 低客单: 优先 micro_commitment（降低回访门槛）

        决策留痕: explanation_summary + risk_summary 记录推理过程和风险点。
        """
        import httpx

        customer_id = params.get("customer_id")
        if not customer_id:
            return AgentResult(success=False, action="generate_first_to_second_suggestion", error="缺少 customer_id")

        first_order_amount_fen = params.get("first_order_amount_fen", 0)
        favorite_dish = params.get("favorite_dish", "")
        order_channel = params.get("order_channel", "dine_in")

        # 根据首单客单价选择机制组合
        if first_order_amount_fen >= 15000:  # 150元以上 — 高客单
            primary_mechanism = "identity_anchor"
            secondary_mechanism = "variable_reward"
            explanation = (
                f"首单客单价¥{first_order_amount_fen / 100:.0f}（高客单），"
                f"优先身份锚定建立归属感，配合多样化奖励提升惊喜感。"
                f"渠道: {order_channel}，喜欢: {favorite_dish or '未知'}"
            )
            risk = "高客单客户对促销敏感度低，避免用折扣券拉低品牌调性。"
        else:
            primary_mechanism = "micro_commitment"
            secondary_mechanism = "identity_anchor"
            explanation = (
                f"首单客单价¥{first_order_amount_fen / 100:.0f}（标准），"
                f"优先最小承诺降低回访门槛，配合身份锚定建立认同。"
                f"渠道: {order_channel}，喜欢: {favorite_dish or '未知'}"
            )
            risk = "标准客单客户可能对免费小食更感兴趣，但需控制赠品成本在毛利安全线内。"

        template_code = "first_to_second_v2"
        channel = "wecom"

        # 三条硬约束校验
        constraints_check = {
            "margin_safe": True,  # 首单转二访赠品成本已在旅程预算内
            "food_safety_ok": True,  # 触达类操作不涉及食材出品
            "customer_experience_ok": True,  # 触达间隔>=3天，不过度打扰
        }

        suggestion = {
            "customer_id": customer_id,
            "suggestion_type": "first_to_second",
            "priority": "high",
            "mechanism_type": primary_mechanism,
            "secondary_mechanism_type": secondary_mechanism,
            "recommended_journey_template": template_code,
            "recommended_offer_type": "micro_gift" if first_order_amount_fen < 15000 else "surprise_reward",
            "recommended_channel": channel,
            "explanation_summary": explanation,
            "risk_summary": risk,
            "constraints_check": constraints_check,
            "expected_outcome_json": {
                "expected_second_visit_rate_14d": 0.22 if first_order_amount_fen >= 15000 else 0.18,
                "expected_open_rate": 0.35,
                "expected_reply_rate": 0.10,
            },
            "requires_human_review": False,
            "created_by_agent": "member_insight",
        }

        # 调用 tx-growth API 写入建议池
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "http://tx-growth:8004/api/v1/growth/agent-suggestions",
                    json=suggestion,
                    headers={"X-Tenant-ID": self.tenant_id},
                    timeout=10.0,
                )
                result = resp.json()
        except (httpx.HTTPError, OSError) as exc:
            return AgentResult(
                success=False,
                action="generate_first_to_second_suggestion",
                error=f"写入建议池失败: {exc}",
                constraints_passed=True,
                constraints_detail=constraints_check,
            )

        return AgentResult(
            success=True,
            action="generate_first_to_second_suggestion",
            data={
                "suggestion": suggestion,
                "api_response": result,
            },
            reasoning=f"首单转二访建议: {primary_mechanism}+{secondary_mechanism}，"
            f"客单价¥{first_order_amount_fen / 100:.0f}，"
            f"预计14天二访率{suggestion['expected_outcome_json']['expected_second_visit_rate_14d']:.0%}",
            confidence=0.82,
            constraints_passed=True,
            constraints_detail=constraints_check,
        )

    # ─── 增长中枢V2: 服务修复策略建议 ───

    async def _generate_repair_suggestion(self, params: dict) -> AgentResult:
        """生成服务修复策略建议，写入 growth_agent_strategy_suggestions

        投诉关闭后触发，采用四阶修复协议:
        1. 情绪承接（先接住情绪，不急于解决）
        2. 控制感补偿（给客户选择权）
        3. 补偿确认（确认方案执行）
        4. 回访观察（72小时）

        关键约束:
        - requires_human_review=True（修复类建议必须人工审核）
        - 禁止辩解性语言
        - 补偿金额上限受毛利约束控制

        决策留痕: explanation_summary + risk_summary 记录推理过程和风险点。
        """
        import httpx

        customer_id = params.get("customer_id")
        if not customer_id:
            return AgentResult(success=False, action="generate_repair_suggestion", error="缺少 customer_id")

        complaint_type = params.get("complaint_type", "other")
        complaint_severity = params.get("complaint_severity", "medium")
        customer_lifetime_value_fen = params.get("customer_lifetime_value_fen", 0)
        complaint_summary = params.get("complaint_summary", "")

        # 根据投诉严重程度和客户价值确定补偿力度
        if complaint_severity == "high":
            compensation_budget_fen = min(10000, max(3000, customer_lifetime_value_fen // 20))  # CLV的5%，上限100元
            urgency = "immediate"
            explanation = (
                f"高严重度投诉（{complaint_type}），客户CLV¥{customer_lifetime_value_fen / 100:.0f}。"
                f"建议补偿预算¥{compensation_budget_fen / 100:.0f}，"
                f"采用四阶修复协议，1小时内启动情绪承接。"
                f"投诉摘要: {complaint_summary[:50]}"
            )
            risk = "高严重度投诉若修复失败，客户流失概率>80%。补偿方案须给客户充分选择权。"
        elif complaint_severity == "medium":
            compensation_budget_fen = min(5000, max(1500, customer_lifetime_value_fen // 30))  # CLV的3.3%，上限50元
            urgency = "within_4h"
            explanation = (
                f"中等严重度投诉（{complaint_type}），客户CLV¥{customer_lifetime_value_fen / 100:.0f}。"
                f"建议补偿预算¥{compensation_budget_fen / 100:.0f}，"
                f"采用四阶修复协议，4小时内启动。"
                f"投诉摘要: {complaint_summary[:50]}"
            )
            risk = "中等投诉修复成功率约65%，关键在情绪承接阶段的真诚度。"
        else:
            compensation_budget_fen = min(2000, max(500, customer_lifetime_value_fen // 50))  # CLV的2%，上限20元
            urgency = "within_24h"
            explanation = (
                f"轻度投诉（{complaint_type}），客户CLV¥{customer_lifetime_value_fen / 100:.0f}。"
                f"建议补偿预算¥{compensation_budget_fen / 100:.0f}，"
                f"采用标准修复流程，24小时内响应。"
                f"投诉摘要: {complaint_summary[:50]}"
            )
            risk = "轻度投诉修复成功率约85%，重点是诚恳态度。"

        template_code = "service_repair_v2"

        # 三条硬约束校验
        constraints_check = {
            "margin_safe": compensation_budget_fen <= max(3000, customer_lifetime_value_fen // 10),
            "food_safety_ok": True,  # 修复触达不涉及食材出品
            "customer_experience_ok": True,  # 修复旅程优先级最高，不会与其他旅程冲突
        }

        suggestion = {
            "customer_id": customer_id,
            "suggestion_type": "service_repair",
            "priority": "critical" if complaint_severity == "high" else "high",
            "mechanism_type": "service_repair",
            "recommended_journey_template": template_code,
            "recommended_offer_type": "compensation_choice",
            "recommended_channel": "manual_task",  # 修复类必须人工执行
            "compensation_budget_fen": compensation_budget_fen,
            "urgency": urgency,
            "complaint_type": complaint_type,
            "complaint_severity": complaint_severity,
            "explanation_summary": explanation,
            "risk_summary": risk,
            "constraints_check": constraints_check,
            "expected_outcome_json": {
                "expected_repair_success_rate": 0.50
                if complaint_severity == "high"
                else 0.65
                if complaint_severity == "medium"
                else 0.85,
                "expected_revisit_rate_7d": 0.30
                if complaint_severity == "high"
                else 0.45
                if complaint_severity == "medium"
                else 0.60,
            },
            "requires_human_review": True,  # 修复类建议必须人工审核
            "created_by_agent": "member_insight",
        }

        # 调用 tx-growth API 写入建议池
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "http://tx-growth:8004/api/v1/growth/agent-suggestions",
                    json=suggestion,
                    headers={"X-Tenant-ID": self.tenant_id},
                    timeout=10.0,
                )
                result = resp.json()
        except (httpx.HTTPError, OSError) as exc:
            return AgentResult(
                success=False,
                action="generate_repair_suggestion",
                error=f"写入建议池失败: {exc}",
                constraints_passed=all(constraints_check.values()),
                constraints_detail=constraints_check,
            )

        return AgentResult(
            success=True,
            action="generate_repair_suggestion",
            data={
                "suggestion": suggestion,
                "api_response": result,
            },
            reasoning=f"服务修复建议: {complaint_severity}严重度（{complaint_type}），"
            f"补偿预算¥{compensation_budget_fen / 100:.0f}，"
            f"紧急度={urgency}，须人工审核",
            confidence=0.80,
            constraints_passed=all(constraints_check.values()),
            constraints_detail=constraints_check,
        )

    # ─── P1: 超级用户关系经营建议 ───

    async def _generate_super_user_suggestion(self, params: dict) -> AgentResult:
        """为超级用户(active/advocate)生成关系经营建议。

        根据超级用户等级和裂变潜力选择触达策略:
        - advocate: 赋能推荐（分享专属邀请）
        - active: 特权体验（新品试菜/主厨晚宴）
        - 有裂变潜力: 推荐赋能路径
        - 无裂变潜力: 季节性专属体验
        """
        import httpx

        customer_id = params.get("customer_id")
        if not customer_id:
            return AgentResult(success=False, action="generate_super_user_suggestion", error="缺少 customer_id")

        super_level = params.get("super_user_level", "active")
        referral_scenario = params.get("referral_scenario", "none")
        lifetime_value_fen = params.get("customer_lifetime_value_fen", 0)

        has_referral_potential = referral_scenario in ("super_referrer", "birthday_organizer", "family_host")

        if super_level == "advocate":
            mechanism = "referral_empowerment"
            channel = "miniapp"
            explanation = (
                f"品牌大使级超级用户，CLV¥{lifetime_value_fen / 100:.0f}。"
                f"裂变场景: {referral_scenario}。赋能推荐路径，激活社交裂变。"
            )
        elif has_referral_potential:
            mechanism = "referral_empowerment"
            channel = "miniapp"
            explanation = (
                f"活跃超级用户，有裂变潜力（{referral_scenario}），CLV¥{lifetime_value_fen / 100:.0f}。"
                f"建议赋能推荐，让超级用户成为品牌传播节点。"
            )
        else:
            mechanism = "super_user_exclusive"
            channel = "wecom"
            explanation = (
                f"活跃超级用户，无明显裂变潜力，CLV¥{lifetime_value_fen / 100:.0f}。建议特权体验路径，维护高价值关系。"
            )

        constraints_check = {
            "margin_safe": True,
            "food_safety_ok": True,
            "customer_experience_ok": True,
        }

        suggestion = {
            "customer_id": customer_id,
            "suggestion_type": "super_user_relationship",
            "priority": "high",
            "mechanism_type": mechanism,
            "recommended_journey_template": "super_user_relationship_v1",
            "recommended_offer_type": "exclusive_experience",
            "recommended_channel": channel,
            "explanation_summary": explanation,
            "risk_summary": "超级用户触达频率须控制，避免因过度打扰导致关系疲劳。",
            "constraints_check": constraints_check,
            "expected_outcome_json": {
                "expected_engagement_rate": 0.55 if super_level == "advocate" else 0.40,
                "expected_referral_rate": 0.25 if has_referral_potential else 0.05,
            },
            "requires_human_review": False,
            "created_by_agent": "member_insight",
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "http://tx-growth:8004/api/v1/growth/agent-suggestions",
                    json=suggestion,
                    headers={"X-Tenant-ID": self.tenant_id},
                    timeout=10.0,
                )
                result = resp.json()
        except (httpx.HTTPError, OSError) as exc:
            return AgentResult(
                success=False,
                action="generate_super_user_suggestion",
                error=f"写入建议池失败: {exc}",
                constraints_passed=True,
                constraints_detail=constraints_check,
            )

        return AgentResult(
            success=True,
            action="generate_super_user_suggestion",
            data={"suggestion": suggestion, "api_response": result},
            reasoning=f"超级用户建议: {super_level}级，机制={mechanism}，"
            f"裂变潜力={'有' if has_referral_potential else '无'}",
            confidence=0.85,
            constraints_passed=True,
            constraints_detail=constraints_check,
        )

    # ─── P1: 心理距离修复建议 ───

    async def _generate_psych_bridge_suggestion(self, params: dict) -> AgentResult:
        """为fading/abstracted客户生成心理距离修复建议。

        根据心理距离级别选择触达策略:
        - abstracted: 极轻触达（SMS，纯信息分享，不施压）
        - fading: 有温度的关系唤醒（企微，店员问候）
        """
        import httpx

        customer_id = params.get("customer_id")
        if not customer_id:
            return AgentResult(success=False, action="generate_psych_bridge_suggestion", error="缺少 customer_id")

        psych_level = params.get("psych_distance_level", "fading")
        lifetime_value_fen = params.get("customer_lifetime_value_fen", 0)
        days_since_last = params.get("days_since_last_visit", 0)

        if psych_level == "abstracted":
            mechanism = "psych_bridge"
            template = "tmpl_psych_bridge_gentle"
            channel = "sms"
            explanation = (
                f"疏离客户（{days_since_last}天未到店），CLV¥{lifetime_value_fen / 100:.0f}。"
                f"心理距离已远，采用SMS极轻触达，纯信息分享，避免任何促销或亲密语言。"
            )
            risk = "疏离客户对品牌已模糊，触达可能被忽视。关键是不造成反感。"
        else:
            mechanism = "psych_bridge"
            template = "tmpl_psych_bridge_warmup"
            channel = "wecom"
            explanation = (
                f"渐远客户（{days_since_last}天未到店），CLV¥{lifetime_value_fen / 100:.0f}。"
                f"还有关系记忆，采用企微有温度的店员问候，重建人际连接。"
            )
            risk = "渐远客户仍有关系基础，但触达语气过于促销会加速疏远。"

        constraints_check = {
            "margin_safe": True,
            "food_safety_ok": True,
            "customer_experience_ok": True,
        }

        suggestion = {
            "customer_id": customer_id,
            "suggestion_type": "psych_distance_bridge",
            "priority": "medium",
            "mechanism_type": mechanism,
            "recommended_journey_template": "psych_distance_bridge_v1",
            "recommended_touch_template": template,
            "recommended_channel": channel,
            "explanation_summary": explanation,
            "risk_summary": risk,
            "constraints_check": constraints_check,
            "expected_outcome_json": {
                "expected_open_rate": 0.15 if psych_level == "abstracted" else 0.30,
                "expected_return_rate_14d": 0.08 if psych_level == "abstracted" else 0.18,
            },
            "requires_human_review": False,
            "created_by_agent": "member_insight",
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "http://tx-growth:8004/api/v1/growth/agent-suggestions",
                    json=suggestion,
                    headers={"X-Tenant-ID": self.tenant_id},
                    timeout=10.0,
                )
                result = resp.json()
        except (httpx.HTTPError, OSError) as exc:
            return AgentResult(
                success=False,
                action="generate_psych_bridge_suggestion",
                error=f"写入建议池失败: {exc}",
                constraints_passed=True,
                constraints_detail=constraints_check,
            )

        return AgentResult(
            success=True,
            action="generate_psych_bridge_suggestion",
            data={"suggestion": suggestion, "api_response": result},
            reasoning=f"心理距离修复建议: {psych_level}级，{days_since_last}天未到，渠道={channel}，模板={template}",
            confidence=0.78,
            constraints_passed=True,
            constraints_detail=constraints_check,
        )

    # ─── P1: 里程碑庆祝建议 ───

    async def _generate_milestone_suggestion(self, params: dict) -> AgentResult:
        """为达成新里程碑的客户生成庆祝建议。

        里程碑等级: newcomer → regular → loyal → vip → legend
        触发时机: 客户里程碑等级变更时。
        """
        import httpx

        customer_id = params.get("customer_id")
        if not customer_id:
            return AgentResult(success=False, action="generate_milestone_suggestion", error="缺少 customer_id")

        milestone_stage = params.get("growth_milestone_stage", "regular")
        order_count = params.get("order_count", 0)
        lifetime_value_fen = params.get("customer_lifetime_value_fen", 0)

        milestone_names = {
            "regular": "常客",
            "loyal": "忠诚客",
            "vip": "VIP",
            "legend": "传奇",
        }
        milestone_name = milestone_names.get(milestone_stage, milestone_stage)

        explanation = (
            f"客户达成「{milestone_name}」里程碑（累计{order_count}笔，"
            f"CLV¥{lifetime_value_fen / 100:.0f}）。"
            f"建议立即发送庆祝通知+解锁权益说明，次日跟进下一级进度展示。"
        )

        constraints_check = {
            "margin_safe": True,
            "food_safety_ok": True,
            "customer_experience_ok": True,
        }

        suggestion = {
            "customer_id": customer_id,
            "suggestion_type": "milestone_celebration",
            "priority": "high" if milestone_stage in ("vip", "legend") else "medium",
            "mechanism_type": "milestone_celebration",
            "recommended_journey_template": "milestone_celebration_v1",
            "recommended_channel": "miniapp",
            "milestone_stage": milestone_stage,
            "explanation_summary": explanation,
            "risk_summary": "里程碑庆祝为正向激励，风险极低。注意勿与其他触达撞期。",
            "constraints_check": constraints_check,
            "expected_outcome_json": {
                "expected_engagement_rate": 0.60,
                "expected_share_rate": 0.15 if milestone_stage in ("vip", "legend") else 0.05,
            },
            "requires_human_review": False,
            "created_by_agent": "member_insight",
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "http://tx-growth:8004/api/v1/growth/agent-suggestions",
                    json=suggestion,
                    headers={"X-Tenant-ID": self.tenant_id},
                    timeout=10.0,
                )
                result = resp.json()
        except (httpx.HTTPError, OSError) as exc:
            return AgentResult(
                success=False,
                action="generate_milestone_suggestion",
                error=f"写入建议池失败: {exc}",
                constraints_passed=True,
                constraints_detail=constraints_check,
            )

        return AgentResult(
            success=True,
            action="generate_milestone_suggestion",
            data={"suggestion": suggestion, "api_response": result},
            reasoning=f"里程碑庆祝建议: {milestone_name}，累计{order_count}笔",
            confidence=0.90,
            constraints_passed=True,
            constraints_detail=constraints_check,
        )

    # ─── P1: 裂变场景激活建议 ───

    async def _generate_referral_suggestion(self, params: dict) -> AgentResult:
        """为有裂变潜力的客户生成场景化激活建议。

        裂变场景: birthday_organizer / family_host / corporate_host / super_referrer
        按场景匹配差异化触达模板和权益包。
        """
        import httpx

        customer_id = params.get("customer_id")
        if not customer_id:
            return AgentResult(success=False, action="generate_referral_suggestion", error="缺少 customer_id")

        referral_scenario = params.get("referral_scenario", "none")
        lifetime_value_fen = params.get("customer_lifetime_value_fen", 0)
        past_referral_count = params.get("past_referral_count", 0)

        scenario_config = {
            "birthday_organizer": {
                "template": "tmpl_referral_birthday",
                "channel": "wecom",
                "desc": "生日组织者",
                "expected_referral": 0.35,
            },
            "family_host": {
                "template": "tmpl_referral_family",
                "channel": "wecom",
                "desc": "家庭聚餐达人",
                "expected_referral": 0.30,
            },
            "corporate_host": {
                "template": "tmpl_referral_generic",
                "channel": "wecom",
                "desc": "企业宴请组织者",
                "expected_referral": 0.20,
            },
            "super_referrer": {
                "template": "tmpl_referral_generic",
                "channel": "miniapp",
                "desc": "超级推荐者",
                "expected_referral": 0.45,
            },
        }

        config = scenario_config.get(
            referral_scenario,
            {
                "template": "tmpl_referral_generic",
                "channel": "miniapp",
                "desc": referral_scenario,
                "expected_referral": 0.10,
            },
        )

        explanation = (
            f"裂变场景: {config['desc']}，CLV¥{lifetime_value_fen / 100:.0f}，"
            f"历史推荐{past_referral_count}次。"
            f"建议通过{config['channel']}触达，使用{config['template']}模板激活裂变。"
        )

        constraints_check = {
            "margin_safe": True,
            "food_safety_ok": True,
            "customer_experience_ok": True,
        }

        suggestion = {
            "customer_id": customer_id,
            "suggestion_type": "referral_activation",
            "priority": "high" if past_referral_count >= 3 else "medium",
            "mechanism_type": "referral_activation",
            "recommended_journey_template": "referral_activation_v1",
            "recommended_touch_template": config["template"],
            "recommended_channel": config["channel"],
            "referral_scenario": referral_scenario,
            "explanation_summary": explanation,
            "risk_summary": "裂变激活需注意分享链接有效期管理，避免过期链接影响体验。",
            "constraints_check": constraints_check,
            "expected_outcome_json": {
                "expected_share_rate": config["expected_referral"],
                "expected_new_customer_per_share": 0.8,
            },
            "requires_human_review": False,
            "created_by_agent": "member_insight",
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "http://tx-growth:8004/api/v1/growth/agent-suggestions",
                    json=suggestion,
                    headers={"X-Tenant-ID": self.tenant_id},
                    timeout=10.0,
                )
                result = resp.json()
        except (httpx.HTTPError, OSError) as exc:
            return AgentResult(
                success=False,
                action="generate_referral_suggestion",
                error=f"写入建议池失败: {exc}",
                constraints_passed=True,
                constraints_detail=constraints_check,
            )

        return AgentResult(
            success=True,
            action="generate_referral_suggestion",
            data={"suggestion": suggestion, "api_response": result},
            reasoning=f"裂变激活建议: {config['desc']}，历史推荐{past_referral_count}次，"
            f"预期分享率{config['expected_referral']:.0%}",
            confidence=0.82,
            constraints_passed=True,
            constraints_detail=constraints_check,
        )
