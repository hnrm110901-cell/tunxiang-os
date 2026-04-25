"""宴会现场订单服务 — 加菜/加酒水/特殊需求/审批"""
import json
import uuid
from datetime import datetime, timezone
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
logger = structlog.get_logger()

class BanquetLiveOrderService:
    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id

    async def create_live_order(self, banquet_id: str, order_type: str, items_json: list, amount_fen: int, quantity: int = 1, requested_by: str = None, requested_name: str = None, notes: str = None) -> dict:
        oid = str(uuid.uuid4())
        await self.db.execute(text("""
            INSERT INTO banquet_live_orders (id, tenant_id, banquet_id, order_type, items_json, amount_fen, quantity, requested_by, requested_name, notes, status)
            VALUES (:id, :tid, :bid, :otype, :items::jsonb, :amt, :qty, :rby, :rname, :notes, 'pending')
        """), {"id": oid, "tid": self.tenant_id, "bid": banquet_id, "otype": order_type, "items": json.dumps(items_json, ensure_ascii=False), "amt": amount_fen, "qty": quantity, "rby": requested_by, "rname": requested_name, "notes": notes})
        await self.db.flush()
        logger.info("banquet_live_order_created", id=oid, banquet_id=banquet_id, type=order_type, amount=amount_fen)
        return {"id": oid, "order_type": order_type, "amount_fen": amount_fen, "status": "pending"}

    async def approve(self, live_order_id: str, approved_by: str) -> dict:
        now = datetime.now(timezone.utc)
        result = await self.db.execute(text("UPDATE banquet_live_orders SET status = 'approved', approved_by = :by, approved_at = :now, updated_at = :now WHERE id = :id AND tenant_id = :tid AND status = 'pending' AND is_deleted = FALSE RETURNING id"), {"id": live_order_id, "tid": self.tenant_id, "by": approved_by, "now": now})
        if not result.mappings().first(): raise ValueError(f"现场订单不存在或已处理: {live_order_id}")
        await self.db.flush()
        return {"id": live_order_id, "status": "approved"}

    async def reject(self, live_order_id: str, reason: str) -> dict:
        result = await self.db.execute(text("UPDATE banquet_live_orders SET status = 'rejected', reject_reason = :reason, updated_at = NOW() WHERE id = :id AND tenant_id = :tid AND status = 'pending' AND is_deleted = FALSE RETURNING id"), {"id": live_order_id, "tid": self.tenant_id, "reason": reason})
        if not result.mappings().first(): raise ValueError(f"现场订单不存在或已处理: {live_order_id}")
        await self.db.flush()
        return {"id": live_order_id, "status": "rejected"}

    async def fulfill(self, live_order_id: str) -> dict:
        now = datetime.now(timezone.utc)
        await self.db.execute(text("UPDATE banquet_live_orders SET status = 'fulfilled', fulfilled_at = :now, updated_at = :now WHERE id = :id AND tenant_id = :tid AND status = 'approved' AND is_deleted = FALSE"), {"id": live_order_id, "tid": self.tenant_id, "now": now})
        await self.db.flush()
        return {"id": live_order_id, "status": "fulfilled"}

    async def list_by_banquet(self, banquet_id: str, status: str = None) -> list:
        sql = "SELECT * FROM banquet_live_orders WHERE banquet_id = :bid AND tenant_id = :tid AND is_deleted = FALSE"
        params: dict = {"bid": banquet_id, "tid": self.tenant_id}
        if status:
            sql += " AND status = :status"
            params["status"] = status
        sql += " ORDER BY created_at"
        rows = await self.db.execute(text(sql), params)
        return [dict(r) for r in rows.mappings().all()]

    async def get_live_total(self, banquet_id: str) -> dict:
        row = await self.db.execute(text("SELECT COALESCE(SUM(amount_fen), 0) AS total, COUNT(*) AS count FROM banquet_live_orders WHERE banquet_id = :bid AND tenant_id = :tid AND status IN ('approved','fulfilled') AND is_deleted = FALSE"), {"bid": banquet_id, "tid": self.tenant_id})
        r = row.mappings().first()
        return {"total_fen": r["total"], "count": r["count"]}
