"""宴会售后服务 — 评价收集/转介绍/复购提醒"""

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


class BanquetAftercareService:
    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id

    async def submit_feedback(
        self,
        banquet_id: str,
        overall_score: int,
        food_score: int = 0,
        service_score: int = 0,
        venue_score: int = 0,
        value_score: int = 0,
        comments: str = None,
        improvement_suggestions: str = None,
        would_recommend: bool = True,
        customer_name: str = None,
        customer_phone: str = None,
    ) -> dict:
        if not 1 <= overall_score <= 5:
            raise ValueError("评分范围1-5")
        fid = str(uuid.uuid4())
        await self.db.execute(
            text("""
            INSERT INTO banquet_feedbacks (id, tenant_id, banquet_id, customer_name, customer_phone, overall_score, food_score, service_score, venue_score, value_score, comments, improvement_suggestions, would_recommend)
            VALUES (:id, :tid, :bid, :name, :phone, :overall, :food, :svc, :venue, :value, :comments, :improve, :recommend)
        """),
            {
                "id": fid,
                "tid": self.tenant_id,
                "bid": banquet_id,
                "name": customer_name,
                "phone": customer_phone,
                "overall": overall_score,
                "food": food_score,
                "svc": service_score,
                "venue": venue_score,
                "value": value_score,
                "comments": comments,
                "improve": improvement_suggestions,
                "recommend": would_recommend,
            },
        )
        await self.db.flush()
        logger.info("banquet_feedback_submitted", banquet_id=banquet_id, score=overall_score)
        return {"id": fid, "overall_score": overall_score}

    async def reply_feedback(self, feedback_id: str, reply_content: str, replied_by: str) -> dict:
        now = datetime.now(timezone.utc)
        await self.db.execute(
            text(
                "UPDATE banquet_feedbacks SET reply_content = :reply, replied_by = :by, replied_at = :now WHERE id = :id AND tenant_id = :tid AND is_deleted = FALSE"
            ),
            {"id": feedback_id, "tid": self.tenant_id, "reply": reply_content, "by": replied_by, "now": now},
        )
        await self.db.flush()
        return {"id": feedback_id, "replied": True}

    async def list_feedbacks(
        self, banquet_id: str = None, store_id: str = None, min_score: int = None, page: int = 1, size: int = 20
    ) -> dict:
        conditions = ["bf.tenant_id = :tid", "bf.is_deleted = FALSE"]
        params: dict = {"tid": self.tenant_id, "offset": (page - 1) * size, "limit": size}
        if banquet_id:
            conditions.append("bf.banquet_id = :bid")
            params["bid"] = banquet_id
        if min_score:
            conditions.append("bf.overall_score >= :min")
            params["min"] = min_score
        where = " AND ".join(conditions)
        count_row = await self.db.execute(text(f"SELECT COUNT(*) FROM banquet_feedbacks bf WHERE {where}"), params)
        total = count_row.scalar_one()
        rows = await self.db.execute(
            text(
                f"SELECT * FROM banquet_feedbacks bf WHERE {where} ORDER BY bf.created_at DESC OFFSET :offset LIMIT :limit"
            ),
            params,
        )
        return {"items": [dict(r) for r in rows.mappings().all()], "total": total, "page": page, "size": size}

    async def get_satisfaction_stats(self, store_id: str = None) -> dict:
        sql = """
            SELECT COUNT(*) AS total, AVG(overall_score) AS avg_score, AVG(food_score) AS avg_food,
                   AVG(service_score) AS avg_service, AVG(venue_score) AS avg_venue,
                   SUM(CASE WHEN would_recommend THEN 1 ELSE 0 END) AS recommend_count
            FROM banquet_feedbacks WHERE tenant_id = :tid AND is_deleted = FALSE
        """
        params: dict = {"tid": self.tenant_id}
        row = await self.db.execute(text(sql), params)
        r = row.mappings().first()
        total = r["total"] or 0
        return {
            "total_feedbacks": total,
            "avg_overall": round(float(r["avg_score"] or 0), 1),
            "avg_food": round(float(r["avg_food"] or 0), 1),
            "avg_service": round(float(r["avg_service"] or 0), 1),
            "avg_venue": round(float(r["avg_venue"] or 0), 1),
            "nps_rate": round(r["recommend_count"] / max(total, 1) * 100, 1),
        }

    async def create_referral(
        self,
        referrer_banquet_id: str,
        referred_name: str,
        referred_phone: str,
        referrer_name: str = None,
        referrer_phone: str = None,
        reward_type: str = "coupon",
        reward_value_fen: int = 0,
    ) -> dict:
        rid = str(uuid.uuid4())
        await self.db.execute(
            text("""
            INSERT INTO banquet_referrals (id, tenant_id, referrer_banquet_id, referrer_name, referrer_phone, referred_name, referred_phone, referrer_reward_type, referrer_reward_value_fen, status)
            VALUES (:id, :tid, :rbid, :rname, :rphone, :dname, :dphone, :rtype, :rvalue, 'pending')
        """),
            {
                "id": rid,
                "tid": self.tenant_id,
                "rbid": referrer_banquet_id,
                "rname": referrer_name,
                "rphone": referrer_phone,
                "dname": referred_name,
                "dphone": referred_phone,
                "rtype": reward_type,
                "rvalue": reward_value_fen,
            },
        )
        await self.db.flush()
        logger.info("banquet_referral_created", referrer_banquet_id=referrer_banquet_id, referred=referred_name)
        return {"id": rid, "status": "pending"}

    async def convert_referral(self, referral_id: str, lead_id: str) -> dict:
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            text(
                "UPDATE banquet_referrals SET status = 'converted', referred_lead_id = :lid, converted_at = :now WHERE id = :id AND tenant_id = :tid AND status IN ('pending','contacted') AND is_deleted = FALSE RETURNING id"
            ),
            {"id": referral_id, "tid": self.tenant_id, "lid": lead_id, "now": now},
        )
        if not result.mappings().first():
            raise ValueError(f"转介绍不存在或已处理: {referral_id}")
        await self.db.flush()
        return {"id": referral_id, "status": "converted", "lead_id": lead_id}

    async def list_referrals(self, banquet_id: str = None, status: str = None) -> list:
        sql = "SELECT * FROM banquet_referrals WHERE tenant_id = :tid AND is_deleted = FALSE"
        params: dict = {"tid": self.tenant_id}
        if banquet_id:
            sql += " AND referrer_banquet_id = :bid"
            params["bid"] = banquet_id
        if status:
            sql += " AND status = :status"
            params["status"] = status
        sql += " ORDER BY created_at DESC"
        rows = await self.db.execute(text(sql), params)
        return [dict(r) for r in rows.mappings().all()]
