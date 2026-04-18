"""
1-on-1 AI 辅助服务
- summarize_meeting: 根据 notes 生成结构化总结
- suggest_topics: 基于历史面谈 + 近期绩效建议话题
失败容错：写入空字段，不中断主流程。
"""

from __future__ import annotations

import json
from typing import Dict, List

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.one_on_one import OneOnOneMeeting
from .llm_gateway import get_llm_gateway

logger = structlog.get_logger()


class OneOnOneAIService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def summarize_meeting(self, meeting_id) -> str:
        m = (
            await self.db.execute(select(OneOnOneMeeting).where(OneOnOneMeeting.id == meeting_id))
        ).scalar_one_or_none()
        if m is None or not m.notes:
            return ""

        prompt = (
            "以下是一次 1-on-1 面谈的原始记录，请用中文输出结构化总结（严格 JSON 格式）：\n"
            '{"key_insights": [..], "sentiment": "positive|neutral|negative", '
            '"action_items": [{"item":"","owner":"","due":"YYYY-MM-DD"}]}\n\n'
            f"面谈记录:\n{m.notes}"
        )
        try:
            gateway = get_llm_gateway()
            resp = await gateway.chat(
                messages=[{"role": "user", "content": prompt}],
                system="你是人力资源专家，擅长从面谈记录中提炼关键洞察。仅输出 JSON。",
                temperature=0.3,
                max_tokens=800,
            )
            raw = (resp.get("content") or resp.get("text") or "").strip()
            m.ai_summary = raw
            # 若能解析且 action_items 非空且原字段为空 → 补充
            try:
                parsed = json.loads(raw)
                if not m.action_items_json and parsed.get("action_items"):
                    m.action_items_json = parsed["action_items"]
            except Exception:  # noqa: BLE001
                pass
            await self.db.flush()
            return raw
        except Exception as e:  # noqa: BLE001
            logger.warning("one_on_one_summarize_failed", meeting_id=str(meeting_id), error=str(e))
            m.ai_summary = ""
            await self.db.flush()
            return ""

    async def suggest_topics(self, manager_id: str, participant_id: str) -> List[str]:
        """基于最近 3 次面谈记录 + 参与人职位建议话题。失败返回通用 3 条。"""
        stmt = (
            select(OneOnOneMeeting)
            .where(
                OneOnOneMeeting.initiator_id == manager_id,
                OneOnOneMeeting.participant_id == participant_id,
                OneOnOneMeeting.status == "completed",
            )
            .order_by(OneOnOneMeeting.scheduled_at.desc())
            .limit(3)
        )
        recent = list((await self.db.execute(stmt)).scalars().all())
        history = "\n".join(f"[{m.scheduled_at.date()}] {m.notes or ''}" for m in recent)

        prompt = (
            f"基于以下近期 1-on-1 面谈历史，请为管理者建议本次面谈的 3 个优先话题（中文，JSON 数组）：\n"
            f"{history or '（无历史记录）'}"
        )
        try:
            gateway = get_llm_gateway()
            resp = await gateway.chat(
                messages=[{"role": "user", "content": prompt}],
                system="你是人力资源专家。仅输出 JSON 数组，不要解释。",
                temperature=0.5,
                max_tokens=400,
            )
            raw = (resp.get("content") or resp.get("text") or "").strip()
            topics = json.loads(raw)
            if isinstance(topics, list):
                return [str(t) for t in topics][:5]
        except Exception as e:  # noqa: BLE001
            logger.warning("one_on_one_suggest_topics_failed", error=str(e))
        return ["最近工作挑战", "职业发展方向", "团队协作反馈"]
