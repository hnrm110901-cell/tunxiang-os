"""宴会合同管理服务 — 电子合同生成/签署/变更/终止

从报价单一键生成合同 → 条款模板填充 → 签署 → 变更管理(留痕) → 付款计划追踪。
金额单位: 分(fen)。
"""

import json
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

# 默认取消政策
DEFAULT_CANCEL_TERMS = {
    "rules": [
        {"days_before": 30, "penalty_rate": 0, "desc": "提前30天以上取消,全额退定金"},
        {"days_before": 15, "penalty_rate": 30, "desc": "提前15-30天取消,扣30%定金"},
        {"days_before": 7, "penalty_rate": 50, "desc": "提前7-15天取消,扣50%定金"},
        {"days_before": 0, "penalty_rate": 100, "desc": "7天内取消,定金不退"},
    ],
    "amendment_free_count": 2,
    "amendment_fee_fen": 0,
}


class BanquetContractService:
    """宴会合同管理"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id

    async def generate_from_quote(
        self,
        banquet_id: str,
        quote_id: str,
        party_b_name: str,
        party_b_license: str | None = None,
        terms_override: dict | None = None,
    ) -> dict:
        """从报价单生成合同"""
        # 获取宴会信息
        row = await self.db.execute(
            text("""
                SELECT b.host_name, b.host_phone, b.event_date, b.event_name,
                       b.table_count, b.guest_count, b.store_id
                FROM banquets b
                WHERE b.id = :bid AND b.tenant_id = :tid AND b.is_deleted = FALSE
            """),
            {"bid": banquet_id, "tid": self.tenant_id},
        )
        banquet = row.mappings().first()
        if not banquet:
            raise ValueError(f"宴会不存在: {banquet_id}")

        # 获取报价
        row2 = await self.db.execute(
            text("""
                SELECT q.menu_json, q.final_fen, q.venue_fee_fen, q.service_fee_fen,
                       q.decoration_fee_fen, q.drink_fee_fen
                FROM banquet_quotes q
                WHERE q.id = :qid AND q.tenant_id = :tid AND q.is_deleted = FALSE
            """),
            {"qid": quote_id, "tid": self.tenant_id},
        )
        quote = row2.mappings().first()
        if not quote:
            raise ValueError(f"报价不存在: {quote_id}")

        contract_no = f"BCT-{uuid.uuid4().hex[:12].upper()}"
        total_fen = quote["final_fen"] or 0
        deposit_ratio = 30
        deposit_fen = int(total_fen * deposit_ratio / 100)
        balance_fen = total_fen - deposit_fen

        event_date = banquet["event_date"]
        deposit_due = event_date - timedelta(days=30) if event_date else None
        payment_schedule = [
            {
                "due_date": deposit_due.isoformat() if deposit_due else None,
                "amount_fen": deposit_fen,
                "description": "定金",
                "status": "pending",
            },
            {
                "due_date": event_date.isoformat() if event_date else None,
                "amount_fen": balance_fen,
                "description": "尾款",
                "status": "pending",
            },
        ]

        terms = terms_override or DEFAULT_CANCEL_TERMS
        cid = str(uuid.uuid4())

        await self.db.execute(
            text("""
                INSERT INTO banquet_contracts (id, tenant_id, contract_no, banquet_id,
                    party_a_name, party_a_phone, party_b_name, party_b_license,
                    event_date, event_name, table_count, guest_count,
                    menu_snapshot_json, terms_json, total_fen, deposit_ratio,
                    deposit_fen, payment_schedule_json, status)
                VALUES (:id, :tid, :no, :bid,
                    :pa_name, :pa_phone, :pb_name, :pb_license,
                    :edate, :ename, :tables, :guests,
                    :menu::jsonb, :terms::jsonb, :total, :ratio,
                    :deposit, :schedule::jsonb, 'draft')
            """),
            {
                "id": cid,
                "tid": self.tenant_id,
                "no": contract_no,
                "bid": banquet_id,
                "pa_name": banquet["host_name"],
                "pa_phone": banquet["host_phone"],
                "pb_name": party_b_name,
                "pb_license": party_b_license,
                "edate": event_date,
                "ename": banquet["event_name"],
                "tables": banquet["table_count"],
                "guests": banquet["guest_count"],
                "menu": json.dumps(quote["menu_json"], ensure_ascii=False) if quote["menu_json"] else "[]",
                "terms": json.dumps(terms, ensure_ascii=False),
                "total": total_fen,
                "ratio": deposit_ratio,
                "deposit": deposit_fen,
                "schedule": json.dumps(payment_schedule, ensure_ascii=False, default=str),
            },
        )
        await self.db.flush()

        logger.info("banquet_contract_generated", contract_no=contract_no, banquet_id=banquet_id, total_fen=total_fen)
        return {
            "id": cid,
            "contract_no": contract_no,
            "total_fen": total_fen,
            "deposit_fen": deposit_fen,
            "status": "draft",
        }

    async def sign_contract(self, contract_id: str, signed_by_customer: str) -> dict:
        """签署合同"""
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            text("""
                UPDATE banquet_contracts
                SET status = 'signed', signed_at = :now, signed_by_customer = :signer, updated_at = :now
                WHERE id = :cid AND tenant_id = :tid AND status IN ('draft', 'pending_sign') AND is_deleted = FALSE
                RETURNING id, contract_no, banquet_id
            """),
            {"cid": contract_id, "tid": self.tenant_id, "now": now, "signer": signed_by_customer},
        )
        row = result.mappings().first()
        if not row:
            raise ValueError(f"合同不存在或状态不允许签署: {contract_id}")
        await self.db.flush()
        logger.info("banquet_contract_signed", contract_id=contract_id)
        return {"id": str(row["id"]), "contract_no": row["contract_no"], "status": "signed"}

    async def create_amendment(
        self,
        contract_id: str,
        change_type: str,
        old_value: dict,
        new_value: dict,
        reason: str,
        price_diff_fen: int = 0,
    ) -> dict:
        """创建合同变更"""
        # 获取当前最大amendment_no
        row = await self.db.execute(
            text("""
                SELECT COALESCE(MAX(amendment_no), 0) + 1 AS next_no
                FROM banquet_contract_amendments
                WHERE contract_id = :cid AND tenant_id = :tid AND is_deleted = FALSE
            """),
            {"cid": contract_id, "tid": self.tenant_id},
        )
        next_no = row.scalar_one()

        aid = str(uuid.uuid4())
        await self.db.execute(
            text("""
                INSERT INTO banquet_contract_amendments
                    (id, tenant_id, contract_id, amendment_no, change_type,
                     old_value_json, new_value_json, reason, price_diff_fen, status)
                VALUES (:id, :tid, :cid, :no, :ctype,
                    :old::jsonb, :new::jsonb, :reason, :diff, 'pending')
            """),
            {
                "id": aid,
                "tid": self.tenant_id,
                "cid": contract_id,
                "no": next_no,
                "ctype": change_type,
                "old": json.dumps(old_value, ensure_ascii=False, default=str),
                "new": json.dumps(new_value, ensure_ascii=False, default=str),
                "reason": reason,
                "diff": price_diff_fen,
            },
        )
        await self.db.flush()
        logger.info("banquet_contract_amendment_created", contract_id=contract_id, amendment_no=next_no)
        return {"id": aid, "amendment_no": next_no, "change_type": change_type, "status": "pending"}

    async def approve_amendment(self, amendment_id: str, approved_by: str) -> dict:
        """批准变更"""
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            text("""
                UPDATE banquet_contract_amendments
                SET status = 'approved', approved_by = :approver, approved_at = :now, updated_at = :now
                WHERE id = :aid AND tenant_id = :tid AND status = 'pending' AND is_deleted = FALSE
                RETURNING id, contract_id, price_diff_fen
            """),
            {"aid": amendment_id, "tid": self.tenant_id, "approver": approved_by, "now": now},
        )
        row = result.mappings().first()
        if not row:
            raise ValueError(f"变更不存在或已处理: {amendment_id}")

        # 更新合同amendment_count和总价
        await self.db.execute(
            text("""
                UPDATE banquet_contracts
                SET amendment_count = amendment_count + 1,
                    total_fen = total_fen + :diff,
                    status = 'amended',
                    updated_at = :now
                WHERE id = :cid AND tenant_id = :tid AND is_deleted = FALSE
            """),
            {"cid": str(row["contract_id"]), "tid": self.tenant_id, "diff": row["price_diff_fen"], "now": now},
        )
        await self.db.flush()
        logger.info("banquet_contract_amendment_approved", amendment_id=amendment_id)
        return {"id": str(row["id"]), "status": "approved"}

    async def reject_amendment(self, amendment_id: str, approved_by: str) -> dict:
        """拒绝变更"""
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            text("""
                UPDATE banquet_contract_amendments
                SET status = 'rejected', approved_by = :approver, approved_at = :now, updated_at = :now
                WHERE id = :aid AND tenant_id = :tid AND status = 'pending' AND is_deleted = FALSE
                RETURNING id
            """),
            {"aid": amendment_id, "tid": self.tenant_id, "approver": approved_by, "now": now},
        )
        if not result.mappings().first():
            raise ValueError(f"变更不存在或已处理: {amendment_id}")
        await self.db.flush()
        return {"id": amendment_id, "status": "rejected"}

    async def terminate_contract(self, contract_id: str, reason: str) -> dict:
        """终止合同"""
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            text("""
                UPDATE banquet_contracts
                SET status = 'terminated', updated_at = :now
                WHERE id = :cid AND tenant_id = :tid AND status IN ('draft','pending_sign','signed','amended') AND is_deleted = FALSE
                RETURNING id, contract_no
            """),
            {"cid": contract_id, "tid": self.tenant_id, "now": now},
        )
        row = result.mappings().first()
        if not row:
            raise ValueError(f"合同不存在或状态不允许终止: {contract_id}")
        await self.db.flush()
        logger.info("banquet_contract_terminated", contract_id=contract_id, reason=reason)
        return {"id": str(row["id"]), "contract_no": row["contract_no"], "status": "terminated"}

    async def get_contract(self, contract_id: str) -> dict:
        """获取合同详情"""
        row = await self.db.execute(
            text("SELECT * FROM banquet_contracts WHERE id = :cid AND tenant_id = :tid AND is_deleted = FALSE"),
            {"cid": contract_id, "tid": self.tenant_id},
        )
        contract = row.mappings().first()
        if not contract:
            raise ValueError(f"合同不存在: {contract_id}")
        return dict(contract)

    async def get_contract_by_banquet(self, banquet_id: str) -> dict | None:
        """按宴会ID获取合同"""
        row = await self.db.execute(
            text(
                "SELECT * FROM banquet_contracts WHERE banquet_id = :bid AND tenant_id = :tid AND is_deleted = FALSE ORDER BY created_at DESC LIMIT 1"
            ),
            {"bid": banquet_id, "tid": self.tenant_id},
        )
        contract = row.mappings().first()
        return dict(contract) if contract else None

    async def list_amendments(self, contract_id: str) -> list:
        """列出合同变更"""
        rows = await self.db.execute(
            text(
                "SELECT * FROM banquet_contract_amendments WHERE contract_id = :cid AND tenant_id = :tid AND is_deleted = FALSE ORDER BY amendment_no"
            ),
            {"cid": contract_id, "tid": self.tenant_id},
        )
        return [dict(r) for r in rows.mappings().all()]

    async def get_payment_schedule(self, contract_id: str) -> list:
        """获取付款计划"""
        row = await self.db.execute(
            text(
                "SELECT payment_schedule_json FROM banquet_contracts WHERE id = :cid AND tenant_id = :tid AND is_deleted = FALSE"
            ),
            {"cid": contract_id, "tid": self.tenant_id},
        )
        result = row.scalar_one_or_none()
        return result or []

    async def record_payment(self, contract_id: str, schedule_index: int, payment_method: str) -> dict:
        """记录付款"""
        contract = await self.get_contract(contract_id)
        schedule = contract.get("payment_schedule_json", [])
        if schedule_index < 0 or schedule_index >= len(schedule):
            raise ValueError(f"付款计划索引越界: {schedule_index}")

        schedule[schedule_index]["status"] = "paid"
        schedule[schedule_index]["payment_method"] = payment_method
        schedule[schedule_index]["paid_at"] = datetime.now(timezone.utc).isoformat()

        import json

        await self.db.execute(
            text(
                "UPDATE banquet_contracts SET payment_schedule_json = :schedule::jsonb, updated_at = NOW() WHERE id = :cid AND tenant_id = :tid"
            ),
            {"schedule": json.dumps(schedule, ensure_ascii=False), "cid": contract_id, "tid": self.tenant_id},
        )
        await self.db.flush()
        logger.info("banquet_contract_payment_recorded", contract_id=contract_id, index=schedule_index)
        return {"contract_id": contract_id, "schedule_index": schedule_index, "status": "paid"}
