"""宴会结算服务 — 生成结算单/定金抵扣/加菜汇总/发票/B2B月结"""
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

class BanquetSettlementService:
    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id

    async def generate_settlement(self, banquet_id: str) -> dict:
        b = await self.db.execute(text("SELECT * FROM banquets WHERE id = :bid AND tenant_id = :tid AND is_deleted = FALSE"), {"bid": banquet_id, "tid": self.tenant_id})
        banquet = b.mappings().first()
        if not banquet: raise ValueError(f"宴会不存在: {banquet_id}")
        contract_amount = banquet["total_amount_fen"] or 0
        deposit_paid = banquet["deposit_amount_fen"] if banquet["deposit_paid"] else 0
        live_row = await self.db.execute(text("SELECT COALESCE(SUM(amount_fen), 0) AS total FROM banquet_live_orders WHERE banquet_id = :bid AND tenant_id = :tid AND status IN ('approved','fulfilled') AND is_deleted = FALSE"), {"bid": banquet_id, "tid": self.tenant_id})
        live_amount = live_row.scalar_one()
        subtotal = contract_amount + live_amount
        balance_due = subtotal - deposit_paid
        settlement_no = f"BST-{uuid.uuid4().hex[:12].upper()}"
        sid = str(uuid.uuid4())
        await self.db.execute(text("""
            INSERT INTO banquet_settlements (id, tenant_id, settlement_no, banquet_id, store_id,
                contract_amount_fen, deposit_paid_fen, live_order_amount_fen,
                subtotal_fen, balance_due_fen)
            VALUES (:id, :tid, :no, :bid, :sid, :contract, :deposit, :live, :subtotal, :balance)
        """), {"id": sid, "tid": self.tenant_id, "no": settlement_no, "bid": banquet_id, "sid": str(banquet["store_id"]),
               "contract": contract_amount, "deposit": deposit_paid, "live": live_amount, "subtotal": subtotal, "balance": balance_due})
        # 生成明细行
        items = [
            {"type": "deposit_offset", "name": "定金抵扣", "qty": 1, "price": -deposit_paid, "source": "contract"},
            {"type": "dish", "name": "合同菜品费用", "qty": 1, "price": contract_amount, "source": "contract"},
        ]
        if live_amount > 0:
            items.append({"type": "live_add", "name": "现场加菜/酒水", "qty": 1, "price": live_amount, "source": "live_order"})
        for item in items:
            await self.db.execute(text("""
                INSERT INTO banquet_settlement_items (id, tenant_id, settlement_id, item_type, item_name, quantity, unit_price_fen, subtotal_fen, source)
                VALUES (:id, :tid, :sid, :type, :name, :qty, :price, :subtotal, :source)
            """), {"id": str(uuid.uuid4()), "tid": self.tenant_id, "sid": sid, "type": item["type"], "name": item["name"], "qty": item["qty"], "price": item["price"], "subtotal": item["price"], "source": item["source"]})
        await self.db.flush()
        logger.info("banquet_settlement_generated", settlement_no=settlement_no, subtotal=subtotal, balance=balance_due)
        return {"id": sid, "settlement_no": settlement_no, "contract_amount_fen": contract_amount, "deposit_paid_fen": deposit_paid, "live_order_amount_fen": live_amount, "subtotal_fen": subtotal, "balance_due_fen": balance_due}

    async def finalize(self, settlement_id: str, payment_method: str, payment_ref: str = None) -> dict:
        now = datetime.now(timezone.utc)
        result = await self.db.execute(text("""
            UPDATE banquet_settlements SET payment_method = :pm, payment_ref = :ref, settled_at = :now, updated_at = :now
            WHERE id = :id AND tenant_id = :tid AND settled_at IS NULL AND is_deleted = FALSE
            RETURNING id, banquet_id
        """), {"id": settlement_id, "tid": self.tenant_id, "pm": payment_method, "ref": payment_ref, "now": now})
        row = result.mappings().first()
        if not row:
            raise ValueError(f"结算单不存在或已结算: {settlement_id}")
        # 更新宴会状态为settled (原子性: 只有completed状态才能settled)
        bid = row["banquet_id"]
        if bid:
            await self.db.execute(text("UPDATE banquets SET status = 'settled', settled_at = :now, updated_at = :now WHERE id = :bid AND tenant_id = :tid AND status = 'completed'"), {"bid": str(bid), "tid": self.tenant_id, "now": now})
        await self.db.flush()
        logger.info("banquet_settlement_finalized", settlement_id=settlement_id)
        return {"id": settlement_id, "status": "settled", "payment_method": payment_method}

    async def get_settlement(self, settlement_id: str) -> dict:
        row = await self.db.execute(text("SELECT * FROM banquet_settlements WHERE id = :id AND tenant_id = :tid AND is_deleted = FALSE"), {"id": settlement_id, "tid": self.tenant_id})
        s = row.mappings().first()
        if not s: raise ValueError(f"结算单不存在: {settlement_id}")
        items = await self.db.execute(text("SELECT * FROM banquet_settlement_items WHERE settlement_id = :sid AND tenant_id = :tid AND is_deleted = FALSE"), {"sid": settlement_id, "tid": self.tenant_id})
        result = dict(s)
        result["items"] = [dict(i) for i in items.mappings().all()]
        return result

    async def get_by_banquet(self, banquet_id: str) -> dict | None:
        row = await self.db.execute(text("SELECT id FROM banquet_settlements WHERE banquet_id = :bid AND tenant_id = :tid AND is_deleted = FALSE ORDER BY created_at DESC LIMIT 1"), {"bid": banquet_id, "tid": self.tenant_id})
        sid = row.scalar_one_or_none()
        if not sid: return None
        return await self.get_settlement(str(sid))

    async def request_invoice(self, settlement_id: str) -> dict:
        await self.db.execute(text("UPDATE banquet_settlements SET invoice_status = 'requested', updated_at = NOW() WHERE id = :id AND tenant_id = :tid AND invoice_status = 'none'"), {"id": settlement_id, "tid": self.tenant_id})
        await self.db.flush()
        return {"id": settlement_id, "invoice_status": "requested"}
