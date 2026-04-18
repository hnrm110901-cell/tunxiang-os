"""
AI 面试官 Agent — 单元测试

覆盖：
  1) LLM 不可用时回退到内置题库
  2) 评分四维 + 推荐等级
"""

import sys
from unittest.mock import MagicMock

sys.modules.setdefault("src.core.config", MagicMock(settings=MagicMock()))

import pytest  # noqa: E402

from src.services.ai_agent_market.interviewer_agent import InterviewerAgent  # noqa: E402


@pytest.mark.asyncio
async def test_generate_questions_fallback(monkeypatch):
    agent = InterviewerAgent()
    # 强制 gateway 为 None → 走 fallback 题库
    monkeypatch.setattr(agent, "_gateway", lambda: None)
    res = await agent.generate_questions(job_title="服务员")
    assert res["source"] == "fallback"
    assert len(res["questions"]) >= 3


def test_score_candidate():
    agent = InterviewerAgent()
    answers = [
        {"dimension": "professional",
         "answer_text": "我在连锁品牌工作 3 年，精通 POS 操作，熟悉所有主菜推荐话术，客诉处理有方法",
         "keywords_hit": 3},
        {"dimension": "communication",
         "answer_text": "我擅长与客人沟通，能用普通话和本地话切换",
         "keywords_hit": 2},
        {"dimension": "stability",
         "answer_text": "上一份工作做了 2 年因店铺关闭离职",
         "keywords_hit": 2},
        {"dimension": "culture_fit",
         "answer_text": "认同以客为尊的理念，愿意团队协作",
         "keywords_hit": 3},
    ]
    res = agent.score_candidate(answers)
    assert 0 <= res["overall"] <= 100
    assert set(res["dimensions"].keys()) == {
        "professional", "communication", "stability", "culture_fit",
    }
    assert res["recommendation"] in {"强烈推荐", "推荐", "观察", "不推荐"}


def test_score_empty():
    agent = InterviewerAgent()
    res = agent.score_candidate([])
    assert res["overall"] == 0
