"""危机响应 Agent — P1 | 云端

舆情危机评估、AI生成回应草稿、SLA临期自动升级。
"""

import json
from typing import Any

import structlog

from ..base import AgentResult, SkillAgent

logger = structlog.get_logger(__name__)

# 危机回应提示词模板
_CRISIS_RESPONSE_PROMPT = (
    "你是{brand_name}的公关经理。以下是一条{severity}级别的{alert_type}预警：\n"
    "平台：{platform}\n"
    "内容摘要：{summary}\n"
    "请生成一份{tone}的官方回应（不超过200字），要求：\n"
    "1. 诚恳道歉（如果确实有问题）\n"
    "2. 说明已采取的措施\n"
    "3. 承诺改进\n"
    "4. 留下联系方式"
)

# 预警类型中文映射
_ALERT_TYPE_MAP = {
    "negative_spike": "负面口碑激增",
    "crisis": "舆情危机",
    "trending_negative": "负面趋势",
    "rating_drop": "评分下降",
    "competitor_attack": "竞品攻击",
}

# 严重级别对应的语调
_SEVERITY_TONE_MAP = {
    "critical": "极其严肃且诚恳",
    "high": "严肃且负责",
    "medium": "诚恳且温和",
    "low": "轻松且正面",
}


class CrisisResponderAgent(SkillAgent):
    agent_id = "crisis_responder"
    agent_name = "危机响应"
    description = "舆情危机评估、AI生成回应草稿、SLA临期自动升级"
    priority = "P1"
    run_location = "cloud"

    # 纯舆情PR分析，不触发毛利/食安/客户体验业务约束
    constraint_scope = set()
    constraint_waived_reason = (
        "危机响应Agent纯舆情PR分析与回应生成，输出回应草稿供运营审核，"
        "不直接操作毛利/食安/客户体验三条业务约束维度"
    )

    def get_supported_actions(self) -> list[str]:
        return [
            "assess_crisis",
            "generate_response_draft",
            "monitor_sla",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "assess_crisis": self._assess_crisis,
            "generate_response_draft": self._generate_response_draft,
            "monitor_sla": self._monitor_sla,
        }
        handler = dispatch.get(action)
        if handler:
            return await handler(params)
        return AgentResult(success=False, action=action, error=f"不支持的操作: {action}")

    async def _assess_crisis(self, params: dict[str, Any]) -> AgentResult:
        """评估危机严重程度，推荐响应优先级"""
        alert_type = params.get("alert_type", "negative_spike")
        severity = params.get("severity", "medium")
        trigger_data = params.get("trigger_data", {})
        platform = params.get("platform", "dianping")

        # 综合评估危机分数
        score = 0.0

        # 1. 基于严重级别
        severity_scores = {"critical": 40, "high": 30, "medium": 20, "low": 10}
        score += severity_scores.get(severity, 20)

        # 2. 基于平台影响力
        platform_weight = {
            "weibo": 1.5,       # 微博传播力强
            "xiaohongshu": 1.3, # 小红书种草影响大
            "douyin": 1.4,      # 抖音短视频传播快
            "dianping": 1.2,    # 大众点评直接影响到店
            "meituan": 1.1,     # 美团影响外卖
            "wechat": 1.0,      # 微信私域传播
            "google": 0.8,      # Google 国内影响较小
        }
        score *= platform_weight.get(platform, 1.0)

        # 3. 基于激增倍率
        spike_ratio = trigger_data.get("spike_ratio", 1)
        if spike_ratio >= 5:
            score += 20
        elif spike_ratio >= 3:
            score += 10

        # 评估结果
        if score >= 60:
            priority = "P0"
            urgency = "立即处理"
            recommended_response_min = 15
        elif score >= 40:
            priority = "P1"
            urgency = "30分钟内处理"
            recommended_response_min = 30
        elif score >= 25:
            priority = "P2"
            urgency = "2小时内处理"
            recommended_response_min = 120
        else:
            priority = "P3"
            urgency = "24小时内处理"
            recommended_response_min = 1440

        return AgentResult(
            success=True,
            action="assess_crisis",
            data={
                "crisis_score": round(score, 1),
                "priority": priority,
                "urgency": urgency,
                "recommended_response_min": recommended_response_min,
                "alert_type": alert_type,
                "alert_type_desc": _ALERT_TYPE_MAP.get(alert_type, alert_type),
                "platform": platform,
                "severity": severity,
                "factors": {
                    "severity_base": severity_scores.get(severity, 20),
                    "platform_multiplier": platform_weight.get(platform, 1.0),
                    "spike_bonus": 20 if spike_ratio >= 5 else (10 if spike_ratio >= 3 else 0),
                },
            },
            reasoning=(
                f"危机评分 {round(score, 1)}，{urgency}。"
                f"平台{platform}（权重{platform_weight.get(platform, 1.0)}x），"
                f"级别{severity}，类型{_ALERT_TYPE_MAP.get(alert_type, alert_type)}"
            ),
            confidence=0.85,
        )

    async def _generate_response_draft(self, params: dict[str, Any]) -> AgentResult:
        """调用 tx-brain 生成危机回应草稿"""
        brand_name = params.get("brand_name", "我们的餐厅")
        severity = params.get("severity", "medium")
        alert_type = params.get("alert_type", "negative_spike")
        platform = params.get("platform", "dianping")
        summary = params.get("summary", "")

        tone = _SEVERITY_TONE_MAP.get(severity, "诚恳且温和")
        alert_type_desc = _ALERT_TYPE_MAP.get(alert_type, alert_type)

        prompt = _CRISIS_RESPONSE_PROMPT.format(
            brand_name=brand_name,
            severity=severity,
            alert_type=alert_type_desc,
            platform=platform,
            summary=summary,
            tone=tone,
        )

        # 调用 tx-brain
        response_draft = await self._call_brain(prompt)

        return AgentResult(
            success=True,
            action="generate_response_draft",
            data={
                "response_draft": response_draft,
                "tone": tone,
                "platform": platform,
                "alert_type": alert_type_desc,
                "prompt_used": prompt,
                "brand_name": brand_name,
            },
            reasoning=(
                f"为{brand_name}在{platform}的{alert_type_desc}生成{tone}回应草稿，"
                f"共{len(response_draft)}字"
            ),
            confidence=0.8,
        )

    async def _monitor_sla(self, params: dict[str, Any]) -> AgentResult:
        """检查所有临期SLA预警，建议升级

        params:
          - pending_alerts: [{alert_id, severity, created_at_iso, sla_target_sec, response_status}]
          - current_time_iso: 当前时间ISO字符串
        """
        from datetime import datetime, timezone

        pending_alerts = params.get("pending_alerts", [])
        current_time_iso = params.get("current_time_iso")

        if current_time_iso:
            now = datetime.fromisoformat(current_time_iso)
        else:
            now = datetime.now(tz=timezone.utc)

        approaching_sla: list[dict[str, Any]] = []
        breached_sla: list[dict[str, Any]] = []

        for alert in pending_alerts:
            created_at = datetime.fromisoformat(str(alert["created_at_iso"]))
            sla_target_sec = int(alert.get("sla_target_sec", 1800))
            elapsed_sec = int((now - created_at).total_seconds())
            remaining_sec = sla_target_sec - elapsed_sec

            alert_info = {
                "alert_id": str(alert["alert_id"]),
                "severity": alert.get("severity", "medium"),
                "elapsed_sec": elapsed_sec,
                "sla_target_sec": sla_target_sec,
                "remaining_sec": max(remaining_sec, 0),
                "response_status": alert.get("response_status", "pending"),
            }

            if remaining_sec <= 0:
                breached_sla.append(alert_info)
            elif remaining_sec <= sla_target_sec * 0.25:
                # 剩余不到25%时间
                approaching_sla.append(alert_info)

        # 按剩余时间排序
        approaching_sla.sort(key=lambda x: x["remaining_sec"])
        breached_sla.sort(key=lambda x: x["elapsed_sec"], reverse=True)

        total_monitored = len(pending_alerts)
        needs_escalation = len(breached_sla) + len(approaching_sla)

        return AgentResult(
            success=True,
            action="monitor_sla",
            data={
                "total_monitored": total_monitored,
                "approaching_sla": approaching_sla,
                "breached_sla": breached_sla,
                "needs_escalation": needs_escalation,
                "escalation_ids": [a["alert_id"] for a in breached_sla],
            },
            reasoning=(
                f"监控 {total_monitored} 条预警，"
                f"{len(breached_sla)} 条已超SLA，"
                f"{len(approaching_sla)} 条即将超期"
            ),
            confidence=0.95,
        )

    async def _call_brain(self, prompt: str) -> str:
        """调用 tx-brain Claude API 生成回应

        生产环境通过 HTTP 调用 tx-brain :8010，
        此处含降级实现。
        """
        import httpx

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    "http://localhost:8010/api/v1/brain/complete",
                    json={
                        "model": "claude-haiku",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 300,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = str(data.get("data", {}).get("content", ""))
                    if content:
                        return content
        except (httpx.HTTPError, KeyError, TypeError) as exc:
            logger.warning("crisis_responder.brain_call_fallback", error=str(exc))

        # 降级模板回应
        return (
            "尊敬的顾客，我们已关注到您的反馈，对此深表歉意。"
            "我们已第一时间成立专项小组调查处理此事，"
            "并将持续改进我们的服务品质。"
            "如需进一步沟通，请拨打我们的客服热线。"
            "感谢您的宝贵意见。"
        )
