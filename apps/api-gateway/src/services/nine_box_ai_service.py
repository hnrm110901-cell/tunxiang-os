"""
九宫格 AI 发展建议服务
基于 assessment.strengths / development_areas / nine_box_cell → LLM 生成发展计划。
失败容错：返回空字符串，不阻塞主流程。
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.talent_assessment import TalentAssessment
from .llm_gateway import get_llm_gateway
from .talent_assessment_service import CELL_LABEL

logger = structlog.get_logger()


class NineBoxAIService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def generate_development_plan(self, assessment_id) -> str:
        ta = (
            await self.db.execute(select(TalentAssessment).where(TalentAssessment.id == assessment_id))
        ).scalar_one_or_none()
        if ta is None:
            return ""

        prompt = (
            f"一名餐饮连锁员工的人才盘点结果：\n"
            f"- 九宫格象限：cell={ta.nine_box_cell} ({CELL_LABEL.get(ta.nine_box_cell, '')})\n"
            f"- 业绩评分：{ta.performance_score}/5\n"
            f"- 潜力评分：{ta.potential_score}/5\n"
            f"- 优势：{ta.strengths or '未填写'}\n"
            f"- 待发展项：{ta.development_areas or '未填写'}\n"
            f"- 职业方向：{ta.career_path or '未填写'}\n\n"
            f"请用中文输出一份300字以内的发展建议，包含：1) 短期(3个月)行动 "
            f"2) 中期(6-12个月)能力目标 3) 一项具体岗位/项目锻炼建议。"
        )

        try:
            gateway = get_llm_gateway()
            resp = await gateway.chat(
                messages=[{"role": "user", "content": prompt}],
                system="你是连锁餐饮人力资源总监，擅长基于九宫格人才盘点给出可执行的发展建议。",
                temperature=0.6,
                max_tokens=600,
            )
            plan = (resp.get("content") or resp.get("text") or "").strip()
            ta.ai_development_plan = plan
            await self.db.flush()
            return plan
        except Exception as e:  # noqa: BLE001
            logger.warning("nine_box_ai_generate_failed", assessment_id=str(assessment_id), error=str(e))
            return ""
