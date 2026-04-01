"""
今日特供引擎

将三类信号整合，生成今日推荐特供方案：
1. 临期食材（expiry ≤ 3天）→ 原料特供菜
2. 高库存食材（库存 > 平均消耗的3倍）→ 清库特供
3. 成本率超标菜品 → 价格调整推荐

使用 SmartMenuAgent 的 push_expiry_specials action 生成方案，
同时调用 suggest_alternatives 补充缺货菜品替代方案。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional
from uuid import UUID
from datetime import datetime, timezone

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class SpecialDish:
    dish_id: str
    dish_name: str
    original_price_fen: int
    special_price_fen: int
    discount_rate: float  # 0.0-1.0
    reason: str  # "临期食材" | "高库存清货" | "成本优化"
    ingredient_name: str
    expiry_days: Optional[int] = None  # 临期天数
    sales_script: str = ""  # 服务员推销话术
    banner_text: str = ""  # 菜单横幅文字
    pushed: bool = False  # 是否已推送


@dataclass
class SpecialsReport:
    store_id: str
    date: str
    specials: list[SpecialDish]
    alternatives: list[dict]  # 缺货替代建议
    generated_at: str
    pushed_at: Optional[str] = None

    @property
    def total_specials(self) -> int:
        return len(self.specials)

    @property
    def pushed_count(self) -> int:
        return sum(1 for s in self.specials if s.pushed)


class SpecialsEngine:
    """今日特供引擎（每日由 cron 或手动触发）"""

    _reports: dict[str, SpecialsReport] = {}  # key: f"{tenant_id}:{store_id}:{date}"

    @classmethod
    async def generate_specials(
        cls,
        tenant_id: str,
        store_id: str,
        master_agent,  # MasterAgent instance for calling SmartMenuAgent
    ) -> SpecialsReport:
        """生成今日特供方案"""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"{tenant_id}:{store_id}:{today}"

        # 调用 SmartMenuAgent.push_expiry_specials
        try:
            result = await master_agent.dispatch(
                agent_id="smart_menu",
                action="push_expiry_specials",
                params={
                    "store_id": store_id,
                    "tenant_id": tenant_id,
                    "days_threshold": 3,  # 3天内临期
                    "auto_push": False,  # 先生成，人工确认后再推送
                },
            )
            specials_data = result.get("specials", [])
        except (ValueError, RuntimeError) as exc:
            logger.warning("specials_generation_failed", store_id=store_id, error=str(exc))
            specials_data = []

        # 调用 SmartMenuAgent.suggest_alternatives（低库存替代）
        try:
            alt_result = await master_agent.dispatch(
                agent_id="smart_menu",
                action="suggest_alternatives",
                params={
                    "store_id": store_id,
                    "tenant_id": tenant_id,
                },
            )
            alternatives = alt_result.get("alternatives", [])
        except (ValueError, RuntimeError) as exc:
            logger.warning("alternatives_fetch_failed", store_id=store_id, error=str(exc))
            alternatives = []

        specials = [
            SpecialDish(
                dish_id=s.get("dish_id", ""),
                dish_name=s.get("dish_name", ""),
                original_price_fen=s.get("original_price_fen", 0),
                special_price_fen=s.get("special_price_fen", 0),
                discount_rate=s.get("discount_rate", 0.0),
                reason=s.get("reason", "临期食材"),
                ingredient_name=s.get("ingredient_name", ""),
                expiry_days=s.get("expiry_days"),
                sales_script=s.get("sales_script", ""),
                banner_text=s.get("banner_text", ""),
            )
            for s in specials_data
        ]

        report = SpecialsReport(
            store_id=store_id,
            date=today,
            specials=specials,
            alternatives=alternatives,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        cls._reports[key] = report
        logger.info("specials_generated", store_id=store_id, count=len(specials))
        return report

    @classmethod
    async def push_specials(
        cls,
        tenant_id: str,
        store_id: str,
        special_ids: list[str],  # 选择推送的菜品 ID
        master_agent,
    ) -> dict:
        """确认并推送选中的特供菜到 POS + 小程序"""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"{tenant_id}:{store_id}:{today}"
        report = cls._reports.get(key)
        if not report:
            return {"ok": False, "error": "请先生成今日特供方案"}

        selected = [s for s in report.specials if s.dish_id in special_ids]

        try:
            push_result = await master_agent.dispatch(
                agent_id="smart_menu",
                action="push_expiry_specials",
                params={
                    "store_id": store_id,
                    "tenant_id": tenant_id,
                    "specials": [
                        {
                            "dish_id": s.dish_id,
                            "special_price_fen": s.special_price_fen,
                            "banner_text": s.banner_text,
                        }
                        for s in selected
                    ],
                    "auto_push": True,  # 真正推送
                },
            )
            for s in selected:
                s.pushed = True
            report.pushed_at = datetime.now(timezone.utc).isoformat()
            return {"ok": True, "pushed_count": len(selected), "result": push_result}
        except (ValueError, RuntimeError) as exc:
            logger.warning("specials_push_failed", store_id=store_id, error=str(exc))
            return {"ok": False, "error": str(exc)}

    @classmethod
    def get_report(cls, tenant_id: str, store_id: str) -> Optional[SpecialsReport]:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return cls._reports.get(f"{tenant_id}:{store_id}:{today}")
