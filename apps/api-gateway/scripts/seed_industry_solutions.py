"""
种子脚本 — 上架 4 个行业方案（作为 category=industry_solution 的 Application）

运行：
  cd apps/api-gateway && python -m scripts.seed_industry_solutions

幂等：按 code 去重。真正的「应用组合」在 industry_solution_service.INDUSTRY_SOLUTIONS 定义。
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select

from src.core.database import AsyncSessionLocal
from src.models.app_marketplace import Application
from src.services.ai_agent_market.industry_solution_service import INDUSTRY_SOLUTIONS


# 行业方案定价（按月包套）
SOLUTION_PRICING_FEN = {
    "restaurant_fullservice": 299900,  # ¥2999
    "restaurant_qsr":        149900,  # ¥1499
    "restaurant_hotpot":     199900,  # ¥1999
    "restaurant_teabar":      99900,  # ¥999
}


async def main():
    async with AsyncSessionLocal() as session:
        for code, spec in INDUSTRY_SOLUTIONS.items():
            r = await session.execute(
                select(Application).where(Application.code == f"industry.{code}")
            )
            app = r.scalars().first()
            price = SOLUTION_PRICING_FEN.get(code, 99900)
            apps_list = [a[0] for a in spec["apps"]]
            if app:
                app.name = spec["name"]
                app.description = spec["description"]
                app.price_fen = price
                app.status = "published"
                app.feature_flags_json = {"apps": apps_list, "kpi_pack": spec["kpi_pack"]}
            else:
                session.add(Application(
                    id=uuid.uuid4(),
                    code=f"industry.{code}",
                    name=spec["name"],
                    category="industry_solution",
                    description=spec["description"],
                    provider="tunxiang",
                    price_model="monthly",
                    price_fen=price,
                    status="published",
                    trial_days=7,
                    feature_flags_json={"apps": apps_list, "kpi_pack": spec["kpi_pack"]},
                    supported_roles_json=["ceo", "hq_operations"],
                ))
        await session.commit()
        print(f"✅ 已上架 {len(INDUSTRY_SOLUTIONS)} 个行业方案")


if __name__ == "__main__":
    asyncio.run(main())
