"""
行业方案服务 — 一键安装一整套应用组合

4 个餐饮子行业方案：
  - restaurant_fullservice 正餐连锁
  - restaurant_qsr        快餐连锁
  - restaurant_hotpot     火锅连锁
  - restaurant_teabar     茶饮咖啡
"""

from __future__ import annotations

from typing import Any, Dict, List

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.app_marketplace import Application
from ..app_marketplace_service import AppMarketplaceService

logger = structlog.get_logger()


# 行业方案 → 应用 code 清单 + 默认档位
INDUSTRY_SOLUTIONS: Dict[str, Dict[str, Any]] = {
    "restaurant_fullservice": {
        "name": "正餐连锁全套方案",
        "description": "HR + 合规 + BI + 6 个数智员工全开",
        "apps": [
            ("ai.contract_specialist", "pro"),
            ("ai.interviewer", "pro"),
            ("ai.scheduler", "basic"),
            ("ai.auditor", "enterprise"),
            ("ai.receptionist", "pro"),
            ("ai.performance_expert", "enterprise"),
            ("self.hr_profile", "pro"),
            ("self.payroll", "pro"),
            ("self.performance", "pro"),
            ("self.attendance", "pro"),
            ("self.okr", "pro"),
        ],
        "kpi_pack": ["翻台率", "人力成本率", "食材成本率", "客单价", "复购率"],
    },
    "restaurant_qsr": {
        "name": "快餐连锁精简方案",
        "description": "去 OKR / 九宫格，聚焦效率与成本",
        "apps": [
            ("ai.contract_specialist", "basic"),
            ("ai.scheduler", "basic"),
            ("ai.receptionist", "basic"),
            ("self.hr_profile", "basic"),
            ("self.payroll", "basic"),
            ("self.attendance", "basic"),
        ],
        "kpi_pack": ["出餐速度", "人力成本率", "客流量"],
    },
    "restaurant_hotpot": {
        "name": "火锅连锁方案",
        "description": "加食材追溯 + 存酒管理",
        "apps": [
            ("ai.contract_specialist", "basic"),
            ("ai.interviewer", "basic"),
            ("ai.scheduler", "basic"),
            ("ai.performance_expert", "pro"),
            ("self.hr_profile", "basic"),
            ("self.payroll", "basic"),
            # 食材追溯 / 存酒管理（若未上架则跳过）
            ("self.ingredient_trace", "basic"),
            ("self.wine_storage", "basic"),
        ],
        "kpi_pack": ["食材追溯率", "客单价", "存酒复购率"],
    },
    "restaurant_teabar": {
        "name": "茶饮咖啡方案",
        "description": "加会员积分 + 外卖整合",
        "apps": [
            ("ai.scheduler", "basic"),
            ("ai.receptionist", "basic"),
            ("self.hr_profile", "basic"),
            ("self.payroll", "basic"),
            ("self.member_loyalty", "basic"),
            ("self.delivery_integration", "basic"),
        ],
        "kpi_pack": ["外卖占比", "会员复购率", "新品转化率"],
    },
}


class IndustrySolutionService:
    """行业方案一键安装"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._marketplace = AppMarketplaceService(db)

    def list_solutions(self) -> List[Dict[str, Any]]:
        return [{
            "code": code,
            "name": spec["name"],
            "description": spec["description"],
            "app_count": len(spec["apps"]),
            "kpi_pack": spec["kpi_pack"],
        } for code, spec in INDUSTRY_SOLUTIONS.items()]

    async def install_industry_solution(
        self,
        tenant_id: str,
        solution_code: str,
        installed_by: str | None = None,
    ) -> Dict[str, Any]:
        spec = INDUSTRY_SOLUTIONS.get(solution_code)
        if not spec:
            raise ValueError(f"unknown solution: {solution_code}")

        installed: List[Dict[str, Any]] = []
        skipped: List[str] = []
        for app_code, tier in spec["apps"]:
            # 按 code 查 app
            r = await self.db.execute(
                select(Application).where(Application.code == app_code)
            )
            app = r.scalars().first()
            if not app:
                skipped.append(app_code)
                continue
            res = await self._marketplace.install_app(
                tenant_id=tenant_id,
                app_id=str(app.id),
                tier_name=tier,
                installed_by=installed_by,
            )
            installed.append(res)

        logger.info("industry_solution_installed",
                    tenant=tenant_id, solution=solution_code,
                    installed=len(installed), skipped=len(skipped))
        return {
            "tenant_id": tenant_id,
            "solution_code": solution_code,
            "solution_name": spec["name"],
            "installed_apps": installed,
            "skipped_apps": skipped,
            "kpi_pack": spec["kpi_pack"],
        }


def get_industry_solution_service(db: AsyncSession) -> IndustrySolutionService:
    return IndustrySolutionService(db)
