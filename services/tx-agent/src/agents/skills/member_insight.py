"""#4 会员洞察 Agent — P1 | 云端

来源：private_domain(11方法) + service(7方法)
能力：RFM分析、行为信号、流失检测、旅程触发、差评处理、服务质量

迁移自 tunxiang V2.x private_domain/agent.py + service/agent.py
"""
from datetime import datetime, timezone
from typing import Any, Optional
import structlog
from ..base import SkillAgent, AgentResult

logger = structlog.get_logger(__name__)


# RFM 分层阈值
RFM_THRESHOLDS = {
    "R": [7, 30, 90, 180],    # 天数：S1(≤7) S2(≤30) S3(≤90) S4(≤180) S5(>180)
    "F": [12, 6, 3, 1],       # 次数：S1(≥12) S2(≥6) S3(≥3) S4(≥1) S5(0)
    "M": [500000, 200000, 80000, 20000],  # 分：S1(≥5000元) S2(≥2000) S3(≥800) S4(≥200) S5(<200)
}

# 旅程模板
JOURNEY_TEMPLATES = {
    "new_customer": {"name": "新客欢迎", "steps": ["欢迎短信", "首单优惠推送", "7天回访"]},
    "vip_retention": {"name": "VIP维护", "steps": ["专属优惠", "生日祝福", "季度回馈"]},
    "reactivation": {"name": "流失召回", "steps": ["温馨提醒", "召回优惠券", "二次提醒", "人工跟进"]},
    "review_repair": {"name": "差评修复", "steps": ["致歉回复", "补偿方案", "回访确认"]},
    "birthday": {"name": "生日关怀", "steps": ["生日祝福", "专属折扣", "到店惊喜"]},
}


class MemberInsightAgent(SkillAgent):
    agent_id = "member_insight"
    agent_name = "会员洞察"
    description = "RFM分析、用户旅程、流失检测、差评处理、服务质量"
    priority = "P1"
    run_location = "cloud"

    def get_supported_actions(self) -> list[str]:
        return [
            "analyze_rfm", "detect_signals", "detect_competitor",
            "trigger_journey", "get_churn_risks", "process_bad_review",
            "monitor_service_quality", "handle_complaint", "collect_feedback",
            "rfm_analysis",
        ]

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

            analyzed.append({
                "customer_id": m.get("customer_id"),
                "r_score": r_score, "f_score": f_score, "m_score": m_score,
                "level": level,
            })

        total = len(members)
        distribution = {k: {"count": v, "pct": round(v / total * 100, 1)} for k, v in segments.items()}

        return AgentResult(
            success=True, action="analyze_rfm",
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
                at_risk.append({
                    "customer_id": m.get("customer_id"),
                    "name": m.get("name", ""),
                    "risk_score": round(risk, 2),
                    "recency_days": recency,
                    "total_spent_yuan": round(monetary / 100, 2),
                    "recommended_action": "召回优惠券" if risk > 0.7 else "温馨提醒",
                })

        at_risk.sort(key=lambda x: x["risk_score"], reverse=True)

        return AgentResult(
            success=True, action="get_churn_risks",
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
            return AgentResult(success=False, action="trigger_journey",
                             error=f"未知旅程类型: {journey_type}，可选: {list(JOURNEY_TEMPLATES.keys())}")

        return AgentResult(
            success=True, action="trigger_journey",
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
        reply = f"尊敬的顾客，感谢您的反馈。"
        if issues:
            reply += f"对于您提到的{'、'.join(issues[:3])}问题，我们深表歉意。"
        reply += "我们会立即改进，期待您再次光临。"

        return AgentResult(
            success=True, action="process_bad_review",
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
                signals.append({"type": "churn_risk", "customer_id": m.get("customer_id"),
                               "detail": f"{recency}天未消费", "priority": 1})

            # 生日提醒（简化：检查 birth_date 字段存在）
            if birthday:
                signals.append({"type": "birthday", "customer_id": m.get("customer_id"),
                               "detail": f"生日: {birthday}", "priority": 2})

        signals.sort(key=lambda s: s["priority"])
        return AgentResult(
            success=True, action="detect_signals",
            data={"signals": signals[:30], "total": len(signals)},
            reasoning=f"检测到 {len(signals)} 个行为信号",
            confidence=0.8,
        )

    async def _monitor_quality(self, params: dict) -> AgentResult:
        """服务质量监控"""
        feedbacks = params.get("feedbacks", [])
        if not feedbacks:
            return AgentResult(success=True, action="monitor_service_quality",
                             data={"avg_rating": 0, "total": 0}, confidence=0.5)

        ratings = [f.get("rating", 3) for f in feedbacks]
        avg = sum(ratings) / len(ratings)
        bad_count = sum(1 for r in ratings if r <= 2)
        bad_rate = bad_count / len(ratings) * 100

        return AgentResult(
            success=True, action="monitor_service_quality",
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
                signals.append({"competitor": name, "type": "price_drop", "detail": f"降价{abs(c['price_change_pct'])}%"})
            if c.get("new_campaign"):
                signals.append({"competitor": name, "type": "campaign", "detail": c["new_campaign"]})
        return AgentResult(success=True, action="detect_competitor",
                         data={"signals": signals, "total": len(signals)},
                         reasoning=f"检测到 {len(signals)} 个竞对动态", confidence=0.7)

    async def _handle_complaint(self, params: dict) -> AgentResult:
        """投诉处理"""
        complaint_type = params.get("type", "other")
        priority = {"food_quality": 1, "service": 2, "hygiene": 1}.get(complaint_type, 3)
        return AgentResult(success=True, action="handle_complaint",
                         data={"type": complaint_type, "priority": priority,
                               "assigned_to": "store_manager" if priority <= 2 else "duty_manager",
                               "follow_up_hours": 24 if priority == 1 else 48},
                         reasoning=f"投诉 {complaint_type}，优先级 {priority}", confidence=0.85)

    async def _collect_feedback(self, params: dict) -> AgentResult:
        """收集反馈"""
        feedback = params.get("feedback", {})
        return AgentResult(success=True, action="collect_feedback",
                         data={"stored": True, "rating": feedback.get("rating", 0),
                               "category": feedback.get("category", "general")},
                         reasoning="反馈已收集", confidence=0.95)

    # ─── RFM分析（真实DB） ───

    async def _rfm_analysis(self, params: dict) -> AgentResult:
        store_id = params.get("store_id") or self.store_id
        top_n = params.get("top_n", 20)

        if self._db:
            from sqlalchemy import text
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc)

            rows = await self._db.execute(text("""
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
            """), {"tenant_id": self.tenant_id, "store_id": store_id, "top_n": top_n})

            members = []
            for row in rows.mappings():
                r = dict(row)
                recency = float(r.get("recency_days") or 90)
                frequency = int(r.get("frequency") or 1)
                monetary = int(r.get("monetary_fen") or 0)

                # RFM评分（各1-5分）
                r_score = 5 if recency <= 7 else (4 if recency <= 14 else (3 if recency <= 30 else (2 if recency <= 60 else 1)))
                f_score = 5 if frequency >= 10 else (4 if frequency >= 6 else (3 if frequency >= 3 else (2 if frequency >= 2 else 1)))
                m_score = 5 if monetary >= 50000 else (4 if monetary >= 20000 else (3 if monetary >= 10000 else (2 if monetary >= 5000 else 1)))
                total = r_score + f_score + m_score

                segment = "高价值" if total >= 13 else ("成长型" if total >= 10 else ("潜在" if total >= 7 else "流失风险"))

                members.append({
                    "customer_id": str(r["customer_id"]),
                    "recency_days": round(recency, 1),
                    "frequency": frequency,
                    "monetary_fen": monetary,
                    "rfm_score": total,
                    "segment": segment,
                    "r_score": r_score, "f_score": f_score, "m_score": m_score,
                })

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
                        messages=[{"role": "user", "content":
                            f"近90天会员分布：{seg_summary}，共{len(members)}名活跃会员。"
                            f"高价值均消费{sum(m['monetary_fen'] for m in members if m['segment']=='高价值') // max(1, segments.get('高价值', 1)) / 100:.0f}元。"
                            f"请给出运营建议。"}],
                        max_tokens=200,
                        db=self._db,
                    )
                except Exception as exc:  # noqa: BLE001 — Claude不可用时降级
                    logger.warning("member_insight_llm_fallback", error=str(exc))

            return AgentResult(
                success=True, action="rfm_analysis",
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
            success=True, action="rfm_analysis",
            data={"members": members, "total_analyzed": len(members), "segments": {}},
            reasoning="无DB连接，返回传入数据",
            confidence=0.5,
        )
