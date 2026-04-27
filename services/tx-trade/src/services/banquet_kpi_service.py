"""宴会KPI看板服务 — 快照生成/趋势/对标排名"""

import uuid
from datetime import date, timedelta

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


class BanquetKPIService:
    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id

    async def generate_snapshot(self, store_id: str, period: str, period_date: date) -> dict:
        """生成KPI快照"""
        if period == "daily":
            df, dt = period_date, period_date
        elif period == "weekly":
            df = period_date - timedelta(days=period_date.weekday())
            dt = df + timedelta(days=6)
        else:
            df = period_date.replace(day=1)
            next_month = (df.replace(day=28) + timedelta(days=4)).replace(day=1)
            dt = next_month - timedelta(days=1)
        # 线索
        leads = await self.db.execute(
            text(
                "SELECT COUNT(*) FROM banquet_leads WHERE store_id = :sid AND tenant_id = :tid AND created_at::date BETWEEN :df AND :dt AND is_deleted = FALSE"
            ),
            {"sid": store_id, "tid": self.tenant_id, "df": df, "dt": dt},
        )
        leads_count = leads.scalar_one() or 0
        won = await self.db.execute(
            text(
                "SELECT COUNT(*) FROM banquet_leads WHERE store_id = :sid AND tenant_id = :tid AND status = 'won' AND created_at::date BETWEEN :df AND :dt AND is_deleted = FALSE"
            ),
            {"sid": store_id, "tid": self.tenant_id, "df": df, "dt": dt},
        )
        won_count = won.scalar_one() or 0
        conversion = round(won_count / max(leads_count, 1) * 100, 1)
        # 宴会
        bq = await self.db.execute(
            text("""
            SELECT COUNT(*) AS cnt, COALESCE(SUM(total_amount_fen), 0) AS rev,
                   COALESCE(SUM(table_count), 0) AS tables, COALESCE(SUM(guest_count), 0) AS guests,
                   COALESCE(AVG(total_amount_fen / NULLIF(table_count, 0)), 0) AS avg_table
            FROM banquets WHERE store_id = :sid AND tenant_id = :tid AND event_date BETWEEN :df AND :dt
              AND status IN ('completed','settled') AND is_deleted = FALSE
        """),
            {"sid": store_id, "tid": self.tenant_id, "df": df, "dt": dt},
        )
        b = bq.mappings().first()
        # 满意度
        sat = await self.db.execute(
            text(
                "SELECT COALESCE(AVG(overall_score), 0) FROM banquet_feedbacks bf JOIN banquets bq ON bq.id = bf.banquet_id WHERE bq.store_id = :sid AND bf.tenant_id = :tid AND bq.event_date BETWEEN :df AND :dt AND bf.is_deleted = FALSE"
            ),
            {"sid": store_id, "tid": self.tenant_id, "df": df, "dt": dt},
        )
        satisfaction = round(float(sat.scalar_one() or 0), 1)

        sid = str(uuid.uuid4())
        await self.db.execute(
            text("""
            INSERT INTO banquet_kpi_snapshots (id, tenant_id, store_id, period, period_date, leads_count, conversion_rate, bookings_count, revenue_fen, avg_per_table_fen, total_tables, total_guests, customer_satisfaction)
            VALUES (:id, :tid, :sid, :period, :pdate, :leads, :conv, :bookings, :rev, :avg, :tables, :guests, :sat)
            ON CONFLICT (tenant_id, store_id, period, period_date) WHERE is_deleted = FALSE
            DO UPDATE SET leads_count = :leads, conversion_rate = :conv, bookings_count = :bookings, revenue_fen = :rev, avg_per_table_fen = :avg, total_tables = :tables, total_guests = :guests, customer_satisfaction = :sat
        """),
            {
                "id": sid,
                "tid": self.tenant_id,
                "sid": store_id,
                "period": period,
                "pdate": period_date,
                "leads": leads_count,
                "conv": conversion,
                "bookings": b["cnt"],
                "rev": b["rev"],
                "avg": int(b["avg_table"]),
                "tables": b["tables"],
                "guests": b["guests"],
                "sat": satisfaction,
            },
        )
        await self.db.flush()
        return {
            "store_id": store_id,
            "period": period,
            "date": period_date.isoformat(),
            "leads": leads_count,
            "conversion_rate": conversion,
            "bookings": b["cnt"],
            "revenue_fen": b["rev"],
            "avg_per_table_fen": int(b["avg_table"]),
            "satisfaction": satisfaction,
        }

    async def get_dashboard(
        self, store_id: str, period: str = "monthly", date_from: date = None, date_to: date = None
    ) -> dict:
        """经营看板"""
        sql = "SELECT * FROM banquet_kpi_snapshots WHERE store_id = :sid AND tenant_id = :tid AND period = :period AND is_deleted = FALSE"
        params: dict = {"sid": store_id, "tid": self.tenant_id, "period": period}
        if date_from:
            sql += " AND period_date >= :df"
            params["df"] = date_from
        if date_to:
            sql += " AND period_date <= :dt"
            params["dt"] = date_to
        sql += " ORDER BY period_date DESC LIMIT 12"
        rows = await self.db.execute(text(sql), params)
        snapshots = [dict(r) for r in rows.mappings().all()]
        return {"store_id": store_id, "period": period, "snapshots": snapshots}

    async def generate_benchmarks(self, store_id: str, period_date: date) -> list:
        """生成跨店对标"""
        metrics = ["revenue_fen", "conversion_rate", "bookings_count", "avg_per_table_fen", "customer_satisfaction"]
        results = []
        for metric in metrics:
            row = await self.db.execute(
                text(f"""
                SELECT AVG({metric}) AS brand_avg, MAX({metric}) AS brand_best
                FROM banquet_kpi_snapshots
                WHERE tenant_id = :tid AND period = 'monthly' AND period_date = :d AND is_deleted = FALSE
            """),
                {"tid": self.tenant_id, "d": period_date},
            )
            brand = row.mappings().first()
            store_row = await self.db.execute(
                text(
                    f"SELECT {metric} FROM banquet_kpi_snapshots WHERE store_id = :sid AND tenant_id = :tid AND period = 'monthly' AND period_date = :d AND is_deleted = FALSE"
                ),
                {"sid": store_id, "tid": self.tenant_id, "d": period_date},
            )
            store_val = store_row.scalar_one_or_none() or 0
            bid = str(uuid.uuid4())
            await self.db.execute(
                text("""
                INSERT INTO banquet_competitive_benchmarks (id, tenant_id, store_id, period, period_date, metric_name, store_value, brand_avg, brand_best)
                VALUES (:id, :tid, :sid, 'monthly', :d, :metric, :sv, :ba, :bb)
            """),
                {
                    "id": bid,
                    "tid": self.tenant_id,
                    "sid": store_id,
                    "d": period_date,
                    "metric": metric,
                    "sv": float(store_val),
                    "ba": float(brand["brand_avg"] or 0),
                    "bb": float(brand["brand_best"] or 0),
                },
            )
            results.append(
                {
                    "metric": metric,
                    "store_value": float(store_val),
                    "brand_avg": float(brand["brand_avg"] or 0),
                    "brand_best": float(brand["brand_best"] or 0),
                }
            )
        await self.db.flush()
        return results
