"""企业挂账与协议客户中心（B6）— 月结结算

高端正餐场景（徐记海鲜）：月结账单生成、对账、收款确认、消费分析。
所有金额单位：分（fen）。

v251 迁移后全部操作持久化到 enterprise_bills 表，内存存储已完全移除。
"""

import json
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .enterprise_account import EnterpriseAccountService

logger = structlog.get_logger()


class EnterpriseBillingService:
    """企业月结结算服务

    功能：月结账单生成、账单明细、收款确认、对账单、未结账单、消费分析。
    """

    BILL_STATUS = ("draft", "issued", "partial_paid", "paid", "overdue")

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self._account_svc = EnterpriseAccountService(db, tenant_id)

    async def generate_monthly_bill(
        self,
        enterprise_id: str,
        month: str,
    ) -> dict:
        """生成月结账单

        Args:
            enterprise_id: 企业ID
            month: 账期月份，格式 "YYYY-MM"（如 "2026-03"）
        """
        # 校验企业存在
        enterprise = await self._account_svc.get_enterprise(enterprise_id)

        # 幂等：已存在则返回现有账单
        existing = await self.db.execute(
            text("""
                SELECT id::text, tenant_id::text, bill_no, enterprise_id::text,
                       enterprise_name, month, total_amount_fen, paid_amount_fen,
                       outstanding_fen, order_count, status, issued_at, paid_at,
                       line_items, created_at, updated_at
                FROM enterprise_bills
                WHERE tenant_id = :tid::uuid
                  AND enterprise_id = :eid::uuid
                  AND month = :month
            """),
            {"tid": self.tenant_id, "eid": enterprise_id, "month": month},
        )
        existing_row = existing.mappings().fetchone()
        if existing_row:
            raise ValueError(f"企业 {enterprise['name']} 的 {month} 月结账单已存在")

        # 汇总当月签单记录（status 不限，取已授权的签单）
        signs_result = await self.db.execute(
            text("""
                SELECT id::text, order_id::text, signer_name, amount_fen, created_at
                FROM enterprise_sign_records
                WHERE tenant_id = :tid::uuid
                  AND enterprise_id = :eid::uuid
                  AND TO_CHAR(created_at AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM') = :month
                ORDER BY created_at
            """),
            {"tid": self.tenant_id, "eid": enterprise_id, "month": month},
        )
        month_signs = [dict(row) for row in signs_result.mappings().all()]

        total_amount_fen = sum(r["amount_fen"] for r in month_signs)
        order_count = len(month_signs)

        line_items = [
            {
                "sign_id": r["id"],
                "order_id": r["order_id"],
                "signer_name": r["signer_name"],
                "amount_fen": r["amount_fen"],
                "signed_at": r["created_at"].isoformat()
                if hasattr(r["created_at"], "isoformat")
                else str(r["created_at"]),
            }
            for r in month_signs
        ]

        import uuid as _uuid

        bill_no = f"BILL{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{_uuid.uuid4().hex[:4].upper()}"

        try:
            result = await self.db.execute(
                text("""
                    INSERT INTO enterprise_bills
                        (tenant_id, bill_no, enterprise_id, enterprise_name,
                         month, total_amount_fen, paid_amount_fen, outstanding_fen,
                         order_count, status, line_items)
                    VALUES
                        (:tid::uuid, :bill_no, :eid::uuid, :ename,
                         :month, :total, 0, :total,
                         :order_count, 'issued', :line_items::jsonb)
                    RETURNING id::text, tenant_id::text, bill_no, enterprise_id::text,
                              enterprise_name, month, total_amount_fen, paid_amount_fen,
                              outstanding_fen, order_count, status, issued_at, paid_at,
                              line_items, created_at, updated_at
                """),
                {
                    "tid": self.tenant_id,
                    "bill_no": bill_no,
                    "eid": enterprise_id,
                    "ename": enterprise["name"],
                    "month": month,
                    "total": total_amount_fen,
                    "order_count": order_count,
                    "line_items": json.dumps(line_items, ensure_ascii=False),
                },
            )
            bill = dict(result.mappings().fetchone())
            await self.db.commit()
            logger.info(
                "monthly_bill_generated",
                bill_id=bill["id"],
                bill_no=bill_no,
                enterprise_id=enterprise_id,
                month=month,
                total_amount_fen=total_amount_fen,
                order_count=order_count,
                tenant_id=self.tenant_id,
            )
            return bill
        except SQLAlchemyError as exc:
            await self.db.rollback()
            logger.error("monthly_bill_generate_failed", error=str(exc), exc_info=True)
            raise ValueError(f"月结账单生成失败: {exc}") from exc

    async def _get_bill_row(self, bill_id: str) -> dict:
        """查询账单行，不存在或非本租户时抛 ValueError。"""
        result = await self.db.execute(
            text("""
                SELECT id::text, tenant_id::text, bill_no, enterprise_id::text,
                       enterprise_name, month, total_amount_fen, paid_amount_fen,
                       outstanding_fen, order_count, status, issued_at, paid_at,
                       line_items, created_at, updated_at
                FROM enterprise_bills
                WHERE id = :bid::uuid AND tenant_id = :tid::uuid
            """),
            {"bid": bill_id, "tid": self.tenant_id},
        )
        row = result.mappings().fetchone()
        if row is None:
            raise ValueError(f"账单不存在: {bill_id}")
        return dict(row)

    async def get_bill_detail(self, bill_id: str) -> dict:
        """获取账单明细 — 基础信息 + line_items 列表"""
        bill = await self._get_bill_row(bill_id)
        return bill  # line_items 已包含在 bill 中

    async def confirm_payment(
        self,
        bill_id: str,
        payment_method: str,
        amount_fen: Optional[int] = None,
    ) -> dict:
        """确认收款 — 企业支付月结账单"""
        bill = await self._get_bill_row(bill_id)

        if bill["status"] == "paid":
            raise ValueError(f"账单已结清: {bill_id}")

        pay_amount = amount_fen if amount_fen is not None else bill["outstanding_fen"]
        if pay_amount <= 0:
            raise ValueError("收款金额必须大于0")
        if pay_amount > bill["outstanding_fen"]:
            raise ValueError(f"收款金额 {pay_amount} 超过未结余额 {bill['outstanding_fen']}")

        new_paid = bill["paid_amount_fen"] + pay_amount
        new_outstanding = bill["outstanding_fen"] - pay_amount
        new_status = "paid" if new_outstanding == 0 else "partial_paid"

        try:
            await self.db.execute(
                text("""
                    UPDATE enterprise_bills
                    SET paid_amount_fen = :paid,
                        outstanding_fen = :outstanding,
                        status          = :status,
                        payment_method  = :method,
                        paid_at         = CASE WHEN :status = 'paid' THEN NOW() ELSE paid_at END,
                        updated_at      = NOW()
                    WHERE id = :bid::uuid AND tenant_id = :tid::uuid
                """),
                {
                    "paid": new_paid,
                    "outstanding": new_outstanding,
                    "status": new_status,
                    "method": payment_method,
                    "bid": bill_id,
                    "tid": self.tenant_id,
                },
            )
            # 释放企业已用额度
            await self.db.execute(
                text("""
                    UPDATE enterprise_accounts
                    SET used_fen   = GREATEST(0, used_fen - :pay_amount),
                        updated_at = NOW()
                    WHERE id = :eid::uuid AND tenant_id = :tid::uuid
                """),
                {
                    "pay_amount": pay_amount,
                    "eid": bill["enterprise_id"],
                    "tid": self.tenant_id,
                },
            )
            await self.db.commit()
            logger.info(
                "bill_payment_confirmed",
                bill_id=bill_id,
                payment_method=payment_method,
                pay_amount_fen=pay_amount,
                outstanding_fen=new_outstanding,
                new_status=new_status,
                tenant_id=self.tenant_id,
            )
            return {
                "bill_id": bill_id,
                "payment_method": payment_method,
                "pay_amount_fen": pay_amount,
                "total_paid_fen": new_paid,
                "outstanding_fen": new_outstanding,
                "status": new_status,
            }
        except SQLAlchemyError as exc:
            await self.db.rollback()
            logger.error("bill_payment_failed", error=str(exc), exc_info=True)
            raise ValueError(f"收款确认失败: {exc}") from exc

    async def generate_statement(
        self,
        enterprise_id: str,
        month: str,
    ) -> dict:
        """生成对账单（PDF数据结构）"""
        enterprise = await self._account_svc.get_enterprise(enterprise_id)

        result = await self.db.execute(
            text("""
                SELECT id::text, bill_no, month, total_amount_fen, paid_amount_fen,
                       outstanding_fen, status, order_count, issued_at, line_items
                FROM enterprise_bills
                WHERE tenant_id = :tid::uuid
                  AND enterprise_id = :eid::uuid
                  AND month = :month
            """),
            {"tid": self.tenant_id, "eid": enterprise_id, "month": month},
        )
        target_bill = result.mappings().fetchone()
        if target_bill is None:
            raise ValueError(f"企业 {enterprise['name']} 的 {month} 月结账单不存在，请先生成账单")

        target_bill = dict(target_bill)
        line_items = target_bill.get("line_items") or []

        statement = {
            "title": f"{enterprise['name']} — {month} 对账单",
            "enterprise": {
                "id": enterprise_id,
                "name": enterprise["name"],
                "contact": enterprise["contact"],
                "billing_cycle": enterprise["billing_cycle"],
            },
            "bill": {
                "bill_no": target_bill["bill_no"],
                "month": month,
                "total_amount_fen": target_bill["total_amount_fen"],
                "paid_amount_fen": target_bill["paid_amount_fen"],
                "outstanding_fen": target_bill["outstanding_fen"],
                "status": target_bill["status"],
                "order_count": target_bill["order_count"],
                "issued_at": target_bill["issued_at"].isoformat()
                if hasattr(target_bill["issued_at"], "isoformat")
                else str(target_bill["issued_at"]),
            },
            "line_items": line_items,
            "summary": {
                "total_signs": len(line_items),
                "total_amount_fen": target_bill["total_amount_fen"],
                "avg_per_sign_fen": (target_bill["total_amount_fen"] // len(line_items) if line_items else 0),
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "format": "pdf_data",
        }

        logger.info(
            "statement_generated",
            enterprise_id=enterprise_id,
            month=month,
            total_amount_fen=target_bill["total_amount_fen"],
            tenant_id=self.tenant_id,
        )
        return statement

    async def get_outstanding_bills(self, enterprise_id: str) -> list[dict]:
        """查询企业未结账单"""
        await self._account_svc.get_enterprise(enterprise_id)  # 校验存在

        result = await self.db.execute(
            text("""
                SELECT id::text, bill_no, month, total_amount_fen, paid_amount_fen,
                       outstanding_fen, status, order_count, issued_at, updated_at
                FROM enterprise_bills
                WHERE tenant_id = :tid::uuid
                  AND enterprise_id = :eid::uuid
                  AND status IN ('issued', 'partial_paid', 'overdue')
                ORDER BY issued_at
            """),
            {"tid": self.tenant_id, "eid": enterprise_id},
        )
        bills = [dict(row) for row in result.mappings().all()]

        logger.info(
            "outstanding_bills_queried",
            enterprise_id=enterprise_id,
            count=len(bills),
            total_outstanding_fen=sum(b["outstanding_fen"] for b in bills),
            tenant_id=self.tenant_id,
        )
        return bills

    async def get_enterprise_analytics(self, enterprise_id: str) -> dict:
        """企业消费分析 — 总消费 / 月均 / 签单次数 / 客单价 / 账期履约"""
        enterprise = await self._account_svc.get_enterprise(enterprise_id)

        # 签单汇总
        signs_r = await self.db.execute(
            text("""
                SELECT COALESCE(SUM(amount_fen), 0)::bigint AS total_sign_amount_fen,
                       COUNT(*)::int AS sign_count
                FROM enterprise_sign_records
                WHERE tenant_id = :tid::uuid AND enterprise_id = :eid::uuid
            """),
            {"tid": self.tenant_id, "eid": enterprise_id},
        )
        signs_row = signs_r.mappings().fetchone()
        total_sign_amount_fen = signs_row["total_sign_amount_fen"]
        sign_count = signs_row["sign_count"]
        avg_sign_fen = total_sign_amount_fen // sign_count if sign_count > 0 else 0

        # 账单汇总
        bills_r = await self.db.execute(
            text("""
                SELECT COUNT(*)::int                                              AS total_bills,
                       COUNT(*) FILTER (WHERE status = 'paid')::int              AS paid_bills,
                       COUNT(*) FILTER (WHERE status = 'overdue')::int           AS overdue_bills,
                       COALESCE(SUM(outstanding_fen) FILTER (
                           WHERE status IN ('issued', 'partial_paid', 'overdue')
                       ), 0)::bigint AS total_outstanding_fen,
                       COUNT(DISTINCT month)::int                                AS monthly_count
                FROM enterprise_bills
                WHERE tenant_id = :tid::uuid AND enterprise_id = :eid::uuid
            """),
            {"tid": self.tenant_id, "eid": enterprise_id},
        )
        bills_row = bills_r.mappings().fetchone()
        total_bills = bills_row["total_bills"]
        paid_bills = bills_row["paid_bills"]
        overdue_bills = bills_row["overdue_bills"]
        total_outstanding_fen = bills_row["total_outstanding_fen"]
        monthly_count = bills_row["monthly_count"]
        avg_monthly_fen = total_sign_amount_fen // monthly_count if monthly_count > 0 else 0

        analytics = {
            "enterprise_id": enterprise_id,
            "enterprise_name": enterprise["name"],
            "credit_limit_fen": enterprise["credit_limit_fen"],
            "credit_used_fen": enterprise["used_fen"],
            "credit_utilization": (
                round(enterprise["used_fen"] / enterprise["credit_limit_fen"], 4)
                if enterprise["credit_limit_fen"] > 0
                else 0
            ),
            "total_sign_amount_fen": total_sign_amount_fen,
            "total_sign_count": sign_count,
            "avg_sign_fen": avg_sign_fen,
            "total_bills": total_bills,
            "paid_bills": paid_bills,
            "overdue_bills": overdue_bills,
            "total_outstanding_fen": total_outstanding_fen,
            "monthly_count": monthly_count,
            "avg_monthly_fen": avg_monthly_fen,
            "payment_compliance_rate": (round(paid_bills / total_bills, 4) if total_bills > 0 else 1.0),
        }

        logger.info(
            "enterprise_analytics_queried",
            enterprise_id=enterprise_id,
            total_sign_amount_fen=total_sign_amount_fen,
            sign_count=sign_count,
            outstanding_fen=total_outstanding_fen,
            tenant_id=self.tenant_id,
        )
        return analytics
