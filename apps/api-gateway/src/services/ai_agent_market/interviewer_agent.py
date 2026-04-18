"""
AI 面试官 Agent — 标准化岗位自动出题 + 候选人情感/评分

能力：
  1. generate_questions(job_title, level) 根据岗位生成 6~10 道结构化面试题
  2. score_candidate(answers_json) 四维评分（专业/沟通/稳定性/文化匹配）

LLM 失败时回退到内置规则题库，保证离线可用。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog

from ..llm_gateway import get_llm_gateway

logger = structlog.get_logger()

# 标准化岗位内置题库（LLM 不可用时回退）
_FALLBACK_QUESTIONS: Dict[str, List[str]] = {
    "服务员": [
        "请简述你理解的好服务包含哪几个要素？",
        "客人投诉菜品太咸，你会怎么处理？",
        "你过去一份工作最久做了多久？为什么离开？",
        "给你三桌客人同时需要加水/加菜/结账，你怎么排序？",
        "遇到喝醉闹事的客人你会怎么办？",
        "你期望的月薪是多少？能接受哪种排班？",
    ],
    "传菜员": [
        "你怎么保证上菜顺序和温度？",
        "托盘一次最多能稳稳端几盘？",
        "菜走错台了你会怎么处理？",
    ],
    "收银员": [
        "客人对小票金额有异议，你会如何核对？",
        "遇到假钞/拒付你会怎么处理？",
        "你接触过哪些收银系统？",
    ],
}


class InterviewerAgent:
    """AI 面试官 Agent — 对外可售"""

    def __init__(self):
        self._gw = None

    def _gateway(self):
        if self._gw is None:
            try:
                self._gw = get_llm_gateway()
            except Exception:
                self._gw = None
        return self._gw

    async def generate_questions(
        self,
        job_title: str,
        level: str = "junior",
        extra_requirements: Optional[str] = None,
    ) -> Dict[str, Any]:
        """为岗位生成面试题列表（走 LLM，失败回退内置题库）"""
        prompt = (
            f"你是资深餐饮 HR。请为【{job_title}】({level})生成 8 道结构化面试题，"
            f"覆盖专业技能、沟通协作、稳定性、文化匹配 4 个维度。"
        )
        if extra_requirements:
            prompt += f" 额外要求：{extra_requirements}。"
        prompt += " 仅输出题目列表，每行一题，不要编号前缀。"

        gw = self._gateway()
        if gw is not None:
            try:
                resp = await gw.chat(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=500,
                )
                text = resp.get("content") if isinstance(resp, dict) else str(resp)
                questions = [q.strip("-•*.0123456789 ") for q in (text or "").splitlines() if q.strip()]
                if questions:
                    return {
                        "job_title": job_title,
                        "level": level,
                        "source": "llm",
                        "questions": questions[:10],
                    }
            except Exception as exc:
                logger.warning("interviewer_llm_failed", err=str(exc))

        return {
            "job_title": job_title,
            "level": level,
            "source": "fallback",
            "questions": _FALLBACK_QUESTIONS.get(job_title, _FALLBACK_QUESTIONS["服务员"]),
        }

    def score_candidate(
        self,
        answers: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        简单评分：每条 answer 结构 {question, answer_text, keywords_hit:int}
        四维评分用关键词命中比例 + 字数加权（LLM fallback 算法）。
        """
        if not answers:
            return {"overall": 0, "dimensions": {}}

        dim_map = {
            "professional": 0.0,
            "communication": 0.0,
            "stability": 0.0,
            "culture_fit": 0.0,
        }
        for ans in answers:
            txt = (ans.get("answer_text") or "").strip()
            hits = int(ans.get("keywords_hit") or 0)
            length_factor = min(len(txt) / 80, 1.0)
            quality = min(hits * 0.2 + length_factor * 0.5, 1.0) * 100
            tag = (ans.get("dimension") or "professional").lower()
            if tag not in dim_map:
                tag = "professional"
            dim_map[tag] = max(dim_map[tag], quality)

        overall = round(sum(dim_map.values()) / len(dim_map), 1)
        return {
            "overall": overall,
            "dimensions": {k: round(v, 1) for k, v in dim_map.items()},
            "recommendation": (
                "强烈推荐" if overall >= 80
                else "推荐" if overall >= 65
                else "观察" if overall >= 50
                else "不推荐"
            ),
        }
