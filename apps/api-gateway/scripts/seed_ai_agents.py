"""
种子脚本 — 上架 6 个 AI 数智员工 + 3 档定价

运行：
  cd apps/api-gateway && python -m scripts.seed_ai_agents

幂等：按 application.code 去重，已存在则更新。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List

from sqlalchemy import select

from src.core.database import AsyncSessionLocal
from src.models.app_marketplace import Application, AppPricingTier


# 6 个数智员工定义（单位：分）
AI_AGENTS: List[Dict[str, Any]] = [
    {
        "code": "ai.contract_specialist",
        "name": "合同专员 Agent",
        "description": "合同到期提醒 / 自动续签 / 离职协议 / 电子签约全流程",
        "feature_flags": {"labor_contract": True, "e_signature": True},
        "supported_roles": ["hq_hr", "store_manager"],
        "tiers": [
            {"tier": "basic", "fee_fen": 29900, "limits": {"templates": 10}, "features": ["到期提醒", "标准续签"]},
            {"tier": "pro", "fee_fen": 59900, "limits": {"templates": 9999}, "features": ["无限模板", "离职协议"]},
            {"tier": "enterprise", "fee_fen": 99900, "limits": {"templates": 9999}, "features": ["SSO", "合规审计"]},
        ],
    },
    {
        "code": "ai.interviewer",
        "name": "AI 面试官 Agent",
        "description": "自动出题 + 视频转文字 + 情感分析 + 四维评分",
        "feature_flags": {"llm_generation": True, "emotion": True},
        "supported_roles": ["hq_hr", "recruiter"],
        "tiers": [
            {"tier": "basic", "fee_fen": 9900, "limits": {"interviews_per_month": 100}, "features": ["标准岗位题库"]},
            {"tier": "pro", "fee_fen": 19900, "limits": {"interviews_per_month": 99999}, "features": ["无限次数", "情感分析"]},
            {"tier": "enterprise", "fee_fen": 39900, "limits": {"interviews_per_month": 99999}, "features": ["视频转写", "自定义评分卡"]},
        ],
    },
    {
        "code": "ai.scheduler",
        "name": "排班专员 Agent",
        "description": "基于营业额预测自动生成周排班 + 规则引擎",
        "feature_flags": {"auto_schedule": True, "forecast_based": True},
        "supported_roles": ["store_manager", "floor_manager"],
        "tiers": [
            {"tier": "basic", "fee_fen": 39900, "limits": {"stores": 1}, "features": ["单店排班"]},
            {"tier": "pro", "fee_fen": 79900, "limits": {"stores": 5}, "features": ["多店联排"]},
            {"tier": "enterprise", "fee_fen": 149900, "limits": {"stores": 9999}, "features": ["集团级 + API"]},
        ],
    },
    {
        "code": "ai.auditor",
        "name": "执行过程审计员 Agent",
        "description": "监控 Agent 操作日志 + 异常模式识别 + 风险报告",
        "feature_flags": {"log_scan": True, "risk_report": True},
        "supported_roles": ["hq_compliance", "ceo"],
        "tiers": [
            {"tier": "basic", "fee_fen": 49900, "limits": {"scan_per_day": 4}, "features": ["基础扫描"]},
            {"tier": "pro", "fee_fen": 99900, "limits": {"scan_per_day": 24}, "features": ["每小时扫描"]},
            {"tier": "enterprise", "fee_fen": 199900, "limits": {"scan_per_day": 9999}, "features": ["实时 + 自定义规则"]},
        ],
    },
    {
        "code": "ai.receptionist",
        "name": "员工服务接待员 Agent",
        "description": "员工 HR 自助问答 / 政策查询 / 请假发起",
        "feature_flags": {"hr_assistant": True, "voice": False},
        "supported_roles": ["employee", "store_manager"],
        "tiers": [
            {"tier": "basic", "fee_fen": 19900, "limits": {"chats_per_month": 5000}, "features": ["文本问答"]},
            {"tier": "pro", "fee_fen": 39900, "limits": {"chats_per_month": 99999}, "features": ["语音", "多语言"]},
            {"tier": "enterprise", "fee_fen": 69900, "limits": {"chats_per_month": 99999}, "features": ["知识库定制"]},
        ],
    },
    {
        "code": "ai.performance_expert",
        "name": "绩效专家 Agent",
        "description": "低绩效归因 + 改进建议 + 预期 ¥ 影响量化",
        "feature_flags": {"attribution": True, "peer_benchmark": True},
        "supported_roles": ["ceo", "hq_operations"],
        "tiers": [
            {"tier": "basic", "fee_fen": 29900, "limits": {"analyses_per_month": 20}, "features": ["单店分析"]},
            {"tier": "pro", "fee_fen": 59900, "limits": {"analyses_per_month": 200}, "features": ["多店对比"]},
            {"tier": "enterprise", "fee_fen": 59900, "limits": {"analyses_per_month": 9999}, "features": ["集团 + API 推送"]},
        ],
    },
]


async def upsert_agent(session, spec: Dict[str, Any]) -> None:
    r = await session.execute(
        select(Application).where(Application.code == spec["code"])
    )
    app = r.scalars().first()
    if app:
        app.name = spec["name"]
        app.description = spec["description"]
        app.status = "published"
        app.feature_flags_json = spec["feature_flags"]
        app.supported_roles_json = spec["supported_roles"]
        # 清空旧 tier
        for t in list(app.tiers):
            await session.delete(t)
    else:
        app = Application(
            id=uuid.uuid4(),
            code=spec["code"],
            name=spec["name"],
            category="ai_agent",
            description=spec["description"],
            provider="tunxiang",
            price_model="monthly",
            price_fen=spec["tiers"][0]["fee_fen"],
            version="1.0.0",
            status="published",
            trial_days=14,
            feature_flags_json=spec["feature_flags"],
            supported_roles_json=spec["supported_roles"],
        )
        session.add(app)
    await session.flush()

    for t in spec["tiers"]:
        session.add(AppPricingTier(
            id=uuid.uuid4(),
            app_id=app.id,
            tier_name=t["tier"],
            monthly_fee_fen=t["fee_fen"],
            usage_limits_json=t["limits"],
            features_json=t["features"],
        ))


async def main():
    async with AsyncSessionLocal() as session:
        for spec in AI_AGENTS:
            await upsert_agent(session, spec)
        await session.commit()
        print(f"✅ 已上架 {len(AI_AGENTS)} 个 AI 数智员工")


if __name__ == "__main__":
    asyncio.run(main())
