"""宴会增长Agent — 需求预测/复购提醒/转介绍激励/流失预警"""
import uuid
from datetime import date, datetime, timedelta, timezone
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

MONTH_NAMES = {1: "1月", 2: "2月", 3: "3月", 4: "4月", 5: "5月", 6: "6月", 7: "7月", 8: "8月", 9: "9月", 10: "10月", 11: "11月", 12: "12月"}

class BanquetGrowthAgent:
    agent_id = "banquet_growth"
    agent_name = "宴会增长"

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id

    async def forecast_demand(self, store_id: str, target_month: str) -> dict:
        """需求预测(按月/按类型)"""
        import json
        # 查询历史同月数据
        month_num = int(target_month.split("-")[1])
        rows = await self.db.execute(text("""
            SELECT event_type, COUNT(*) AS cnt, SUM(total_amount_fen) AS revenue
            FROM banquets
            WHERE store_id = :sid AND tenant_id = :tid
              AND EXTRACT(MONTH FROM event_date) = :m
              AND status IN ('completed','settled') AND is_deleted = FALSE
            GROUP BY event_type
        """), {"sid": store_id, "tid": self.tenant_id, "m": month_num})
        history = {r["event_type"]: {"count": r["cnt"], "revenue": r["revenue"]} for r in rows.mappings().all()}
        # 查询同月去年总趋势
        total_row = await self.db.execute(text("""
            SELECT COUNT(*) AS total FROM banquets
            WHERE store_id = :sid AND tenant_id = :tid AND EXTRACT(MONTH FROM event_date) = :m
              AND status IN ('completed','settled') AND is_deleted = FALSE
        """), {"sid": store_id, "tid": self.tenant_id, "m": month_num})
        hist_total = total_row.scalar_one() or 0
        # 简单预测: 历史均值 * 1.1 (增长因子)
        growth_factor = 1.1
        forecasts = []
        for etype in ["wedding", "birthday", "business", "tour_group", "conference", "annual_party"]:
            h = history.get(etype, {"count": 0, "revenue": 0})
            pred_count = max(1, int(h["count"] * growth_factor))
            pred_revenue = int((h["revenue"] or 0) * growth_factor)
            forecasts.append({"event_type": etype, "predicted_count": pred_count, "predicted_revenue_fen": pred_revenue})
            # 写入预测表
            await self.db.execute(text("""
                INSERT INTO banquet_demand_forecasts (id, tenant_id, store_id, forecast_month, event_type, predicted_count, predicted_revenue_fen, factors_json)
                VALUES (:id, :tid, :sid, :month, :etype, :cnt, :rev, :factors::jsonb)
                ON CONFLICT (tenant_id, store_id, forecast_month, event_type) WHERE is_deleted = FALSE
                DO UPDATE SET predicted_count = :cnt, predicted_revenue_fen = :rev, updated_at = NOW()
            """), {"id": str(uuid.uuid4()), "tid": self.tenant_id, "sid": store_id, "month": target_month, "etype": etype, "cnt": pred_count, "rev": pred_revenue, "factors": json.dumps({"growth_factor": growth_factor, "history_count": h["count"]})})
        await self.db.flush()
        total_predicted = sum(f["predicted_count"] for f in forecasts)
        total_revenue = sum(f["predicted_revenue_fen"] for f in forecasts)
        logger.info("banquet_demand_forecast", store_id=store_id, month=target_month, total=total_predicted)
        return {"store_id": store_id, "month": target_month, "total_predicted": total_predicted, "total_revenue_fen": total_revenue, "by_type": forecasts}

    async def find_reorder_opportunities(self, store_id: str) -> list:
        """发现复购机会(周年/节庆/高价值客户)"""
        now = datetime.now(timezone.utc)
        # 去年同月完成的宴会 → 周年复购提醒
        rows = await self.db.execute(text("""
            SELECT b.id, b.banquet_no, b.host_name, b.host_phone, b.event_type, b.event_date, b.total_amount_fen
            FROM banquets b
            WHERE b.store_id = :sid AND b.tenant_id = :tid
              AND b.status IN ('completed','settled') AND b.is_deleted = FALSE
              AND EXTRACT(MONTH FROM b.event_date) = EXTRACT(MONTH FROM CURRENT_DATE)
              AND EXTRACT(YEAR FROM b.event_date) < EXTRACT(YEAR FROM CURRENT_DATE)
        """), {"sid": store_id, "tid": self.tenant_id})
        opportunities = []
        for r in rows.mappings().all():
            opportunities.append({"banquet_id": str(r["id"]), "host_name": r["host_name"], "host_phone": r["host_phone"], "event_type": r["event_type"], "last_event_date": r["event_date"].isoformat() if r["event_date"] else None, "last_amount_fen": r["total_amount_fen"], "opportunity_type": "anniversary", "message": f"{r['host_name']}去年{r['event_type']}客户，建议联系复购"})
        return opportunities

    async def detect_churn_risk(self, store_id: str, days_threshold: int = 90) -> list:
        """流失预警: 高价值客户N天未询价"""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_threshold)
        rows = await self.db.execute(text("""
            SELECT bl.customer_name, bl.phone, bl.company, MAX(bl.created_at) AS last_inquiry,
                   COUNT(*) AS total_inquiries
            FROM banquet_leads bl
            WHERE bl.store_id = :sid AND bl.tenant_id = :tid AND bl.is_deleted = FALSE
              AND bl.status IN ('won','contracted')
            GROUP BY bl.customer_name, bl.phone, bl.company
            HAVING MAX(bl.created_at) < :cutoff AND COUNT(*) >= 2
            ORDER BY MAX(bl.created_at)
        """), {"sid": store_id, "tid": self.tenant_id, "cutoff": cutoff})
        return [{"customer_name": r["customer_name"], "phone": r["phone"], "company": r["company"], "last_inquiry": r["last_inquiry"].isoformat() if r["last_inquiry"] else None, "total_inquiries": r["total_inquiries"], "days_since": (datetime.now(timezone.utc) - r["last_inquiry"]).days if r["last_inquiry"] else None} for r in rows.mappings().all()]
