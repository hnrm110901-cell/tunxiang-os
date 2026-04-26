"""宴会智能报价Agent — 历史数据+季节+成本→最优价格

基于历史宴会数据、季节性因素、食材成本波动，为新宴会推荐最优报价。
"""

import json
import uuid
from datetime import datetime

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

SEASON_FACTORS = {
    1: 1.15,
    2: 1.20,
    3: 1.0,
    4: 1.0,
    5: 1.10,
    6: 1.05,
    7: 0.95,
    8: 0.95,
    9: 1.05,
    10: 1.20,
    11: 1.10,
    12: 1.25,
}
EVENT_MARGIN_TARGET = {
    "wedding": 0.45,
    "birthday": 0.40,
    "business": 0.50,
    "tour_group": 0.30,
    "conference": 0.35,
    "annual_party": 0.45,
}


class BanquetPricingAgent:
    agent_id = "banquet_pricing"
    agent_name = "宴会智能报价"

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id

    async def suggest_price(
        self, store_id: str, event_type: str, table_count: int, guest_count: int, event_month: int = None
    ) -> dict:
        """基于历史数据推荐报价"""
        if not event_month:
            event_month = datetime.now().month
        # 查询历史同类型宴会均价
        row = await self.db.execute(
            text("""
            SELECT AVG(total_amount_fen / NULLIF(table_count, 0)) AS avg_per_table,
                   COUNT(*) AS history_count,
                   MIN(total_amount_fen / NULLIF(table_count, 0)) AS min_per_table,
                   MAX(total_amount_fen / NULLIF(table_count, 0)) AS max_per_table
            FROM banquets
            WHERE store_id = :sid AND tenant_id = :tid AND event_type = :etype
              AND status IN ('completed','settled') AND is_deleted = FALSE
        """),
            {"sid": store_id, "tid": self.tenant_id, "etype": event_type},
        )
        hist = row.mappings().first()
        history_count = hist["history_count"] or 0
        if history_count >= 3:
            base_per_table = int(hist["avg_per_table"])
        else:
            base_per_table = {
                "wedding": 128800,
                "birthday": 98800,
                "business": 158800,
                "tour_group": 58800,
                "conference": 48800,
                "annual_party": 118800,
            }.get(event_type, 98800)
        season = SEASON_FACTORS.get(event_month, 1.0)
        margin = EVENT_MARGIN_TARGET.get(event_type, 0.40)
        recommended_per_table = int(base_per_table * season)
        recommended_total = recommended_per_table * table_count
        confidence = min(0.95, 0.5 + history_count * 0.05)
        result = {
            "recommended_per_table_fen": recommended_per_table,
            "recommended_total_fen": recommended_total,
            "price_range": {"min_fen": int(recommended_per_table * 0.85), "max_fen": int(recommended_per_table * 1.15)},
            "season_factor": season,
            "target_margin": margin,
            "history_count": history_count,
            "confidence": round(confidence, 2),
            "reasoning": f"基于{history_count}次历史{event_type}数据, {event_month}月季节系数{season}, 目标毛利率{margin * 100}%",
        }
        # 记录决策
        await self.db.execute(
            text("""
            INSERT INTO banquet_ai_decisions (id, tenant_id, store_id, agent_type, decision_type, input_context_json, recommendation_json, reasoning, confidence)
            VALUES (:id, :tid, :sid, 'pricing', 'quote_pricing', :input::jsonb, :rec::jsonb, :reason, :conf)
        """),
            {
                "id": str(uuid.uuid4()),
                "tid": self.tenant_id,
                "sid": store_id,
                "input": json.dumps({"event_type": event_type, "tables": table_count, "month": event_month}),
                "rec": json.dumps(result, ensure_ascii=False, default=str),
                "reason": result["reasoning"],
                "conf": confidence,
            },
        )
        await self.db.flush()
        logger.info(
            "banquet_pricing_suggested", store_id=store_id, event_type=event_type, per_table=recommended_per_table
        )
        return result

    async def suggest_menu(self, event_type: str, tier: str, budget_per_table_fen: int) -> dict:
        """基于预算推荐套餐"""
        row = await self.db.execute(
            text("""
            SELECT id, name, per_table_price_fen, dishes_json, tier
            FROM banquet_menu_templates
            WHERE tenant_id = :tid AND event_type = :etype AND is_active = TRUE AND is_deleted = FALSE
            ORDER BY ABS(per_table_price_fen - :budget) LIMIT 3
        """),
            {"tid": self.tenant_id, "etype": event_type, "budget": budget_per_table_fen},
        )
        templates = [dict(r) for r in row.mappings().all()]
        return {
            "budget_per_table_fen": budget_per_table_fen,
            "recommended_templates": templates,
            "best_match": templates[0] if templates else None,
        }
