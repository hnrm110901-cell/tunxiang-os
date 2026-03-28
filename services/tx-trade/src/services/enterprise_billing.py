"""企业挂账与协议客户中心（B6）— 月结结算

高端正餐场景（徐记海鲜）：月结账单生成、对账、收款确认、消费分析。
所有金额单位：分（fen）。
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from .enterprise_account import (
    _enterprises,
    _sign_records,
)

logger = structlog.get_logger()


# ─── 内存模拟存储（生产环境替换为数据库表） ───
_bills: dict[str, dict] = {}
_bill_items: dict[str, list[dict]] = {}  # bill_id -> [line_items]


class EnterpriseBillingService:
    """企业月结结算服务

    功能：月结账单生成、账单明细、收款确认、对账单、未结账单、消费分析。
    """

    # 账单状态
    BILL_STATUS = ("draft", "issued", "partial_paid", "paid", "overdue")

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id

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
        enterprise = _enterprises.get(enterprise_id)
        if not enterprise:
            raise ValueError(f"企业不存在: {enterprise_id}")
        if enterprise["tenant_id"] != self.tenant_id:
            raise ValueError(f"企业不存在: {enterprise_id}")

        # 检查是否已生成该月账单
        for bill in _bills.values():
            if (
                bill["enterprise_id"] == enterprise_id
                and bill["month"] == month
                and bill["tenant_id"] == self.tenant_id
            ):
                raise ValueError(f"企业 {enterprise['name']} 的 {month} 月结账单已存在")

        # 汇总该企业当月签单记录
        month_signs = [
            r for r in _sign_records.values()
            if r["enterprise_id"] == enterprise_id
            and r["tenant_id"] == self.tenant_id
            and r["signed_at"].startswith(month)
            and r["status"] == "signed"
        ]

        total_amount_fen = sum(r["amount_fen"] for r in month_signs)
        order_count = len(month_signs)

        bill_id = str(uuid.uuid4())
        bill_no = f"BILL{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"
        now = datetime.now(timezone.utc)

        bill = {
            "id": bill_id,
            "tenant_id": self.tenant_id,
            "bill_no": bill_no,
            "enterprise_id": enterprise_id,
            "enterprise_name": enterprise["name"],
            "month": month,
            "total_amount_fen": total_amount_fen,
            "paid_amount_fen": 0,
            "outstanding_fen": total_amount_fen,
            "order_count": order_count,
            "status": "issued",
            "issued_at": now.isoformat(),
            "paid_at": None,
            "created_at": now.isoformat(),
        }
        _bills[bill_id] = bill

        # 保存账单明细（逐笔签单）
        line_items = [
            {
                "sign_id": r["id"],
                "order_id": r["order_id"],
                "signer_name": r["signer_name"],
                "amount_fen": r["amount_fen"],
                "signed_at": r["signed_at"],
            }
            for r in month_signs
        ]
        _bill_items[bill_id] = line_items

        logger.info(
            "monthly_bill_generated",
            bill_id=bill_id,
            bill_no=bill_no,
            enterprise_id=enterprise_id,
            month=month,
            total_amount_fen=total_amount_fen,
            order_count=order_count,
            tenant_id=self.tenant_id,
        )

        return bill

    async def get_bill_detail(self, bill_id: str) -> dict:
        """获取账单明细 — 逐笔签单记录

        Returns:
            账单基础信息 + line_items 列表
        """
        bill = _bills.get(bill_id)
        if not bill:
            raise ValueError(f"账单不存在: {bill_id}")
        if bill["tenant_id"] != self.tenant_id:
            raise ValueError(f"账单不存在: {bill_id}")

        line_items = _bill_items.get(bill_id, [])

        return {
            **bill,
            "line_items": line_items,
        }

    async def confirm_payment(
        self,
        bill_id: str,
        payment_method: str,
        amount_fen: Optional[int] = None,
    ) -> dict:
        """确认收款 — 企业支付月结账单

        Args:
            bill_id: 账单ID
            payment_method: 支付方式（bank_transfer/check/cash/wechat）
            amount_fen: 本次收款金额（分），默认为未结余额全额
        """
        bill = _bills.get(bill_id)
        if not bill:
            raise ValueError(f"账单不存在: {bill_id}")
        if bill["tenant_id"] != self.tenant_id:
            raise ValueError(f"账单不存在: {bill_id}")
        if bill["status"] == "paid":
            raise ValueError(f"账单已结清: {bill_id}")

        pay_amount = amount_fen if amount_fen is not None else bill["outstanding_fen"]

        if pay_amount <= 0:
            raise ValueError("收款金额必须大于0")
        if pay_amount > bill["outstanding_fen"]:
            raise ValueError(
                f"收款金额 {pay_amount} 超过未结余额 {bill['outstanding_fen']}"
            )

        now = datetime.now(timezone.utc)

        bill["paid_amount_fen"] += pay_amount
        bill["outstanding_fen"] -= pay_amount

        if bill["outstanding_fen"] == 0:
            bill["status"] = "paid"
            bill["paid_at"] = now.isoformat()
        else:
            bill["status"] = "partial_paid"

        # 释放企业已用额度
        enterprise = _enterprises.get(bill["enterprise_id"])
        if enterprise:
            enterprise["used_fen"] = max(0, enterprise["used_fen"] - pay_amount)
            enterprise["updated_at"] = now.isoformat()

        logger.info(
            "bill_payment_confirmed",
            bill_id=bill_id,
            payment_method=payment_method,
            pay_amount_fen=pay_amount,
            outstanding_fen=bill["outstanding_fen"],
            new_status=bill["status"],
            tenant_id=self.tenant_id,
        )

        return {
            "bill_id": bill_id,
            "payment_method": payment_method,
            "pay_amount_fen": pay_amount,
            "total_paid_fen": bill["paid_amount_fen"],
            "outstanding_fen": bill["outstanding_fen"],
            "status": bill["status"],
        }

    async def generate_statement(
        self,
        enterprise_id: str,
        month: str,
    ) -> dict:
        """生成对账单（PDF数据结构）

        返回可用于PDF渲染的结构化数据。

        Args:
            enterprise_id: 企业ID
            month: 账期月份 "YYYY-MM"
        """
        enterprise = _enterprises.get(enterprise_id)
        if not enterprise:
            raise ValueError(f"企业不存在: {enterprise_id}")
        if enterprise["tenant_id"] != self.tenant_id:
            raise ValueError(f"企业不存在: {enterprise_id}")

        # 查找该月账单
        target_bill = None
        for bill in _bills.values():
            if (
                bill["enterprise_id"] == enterprise_id
                and bill["month"] == month
                and bill["tenant_id"] == self.tenant_id
            ):
                target_bill = bill
                break

        if not target_bill:
            raise ValueError(f"企业 {enterprise['name']} 的 {month} 月结账单不存在，请先生成账单")

        line_items = _bill_items.get(target_bill["id"], [])

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
                "issued_at": target_bill["issued_at"],
            },
            "line_items": line_items,
            "summary": {
                "total_signs": len(line_items),
                "total_amount_fen": target_bill["total_amount_fen"],
                "avg_per_sign_fen": (
                    target_bill["total_amount_fen"] // len(line_items)
                    if line_items else 0
                ),
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

    async def get_outstanding_bills(
        self,
        enterprise_id: str,
    ) -> list[dict]:
        """查询企业未结账单"""
        enterprise = _enterprises.get(enterprise_id)
        if not enterprise:
            raise ValueError(f"企业不存在: {enterprise_id}")
        if enterprise["tenant_id"] != self.tenant_id:
            raise ValueError(f"企业不存在: {enterprise_id}")

        outstanding = [
            bill for bill in _bills.values()
            if bill["enterprise_id"] == enterprise_id
            and bill["tenant_id"] == self.tenant_id
            and bill["status"] in ("issued", "partial_paid", "overdue")
        ]

        # 按发出时间排序
        outstanding.sort(key=lambda b: b["issued_at"])

        logger.info(
            "outstanding_bills_queried",
            enterprise_id=enterprise_id,
            count=len(outstanding),
            total_outstanding_fen=sum(b["outstanding_fen"] for b in outstanding),
            tenant_id=self.tenant_id,
        )

        return outstanding

    async def get_enterprise_analytics(
        self,
        enterprise_id: str,
    ) -> dict:
        """企业消费分析

        返回：总消费、月均消费、签单次数、客单价、账期履约情况。
        """
        enterprise = _enterprises.get(enterprise_id)
        if not enterprise:
            raise ValueError(f"企业不存在: {enterprise_id}")
        if enterprise["tenant_id"] != self.tenant_id:
            raise ValueError(f"企业不存在: {enterprise_id}")

        # 统计所有签单记录
        all_signs = [
            r for r in _sign_records.values()
            if r["enterprise_id"] == enterprise_id
            and r["tenant_id"] == self.tenant_id
        ]

        total_sign_amount_fen = sum(r["amount_fen"] for r in all_signs)
        sign_count = len(all_signs)
        avg_sign_fen = total_sign_amount_fen // sign_count if sign_count > 0 else 0

        # 统计账单
        all_bills = [
            b for b in _bills.values()
            if b["enterprise_id"] == enterprise_id
            and b["tenant_id"] == self.tenant_id
        ]
        total_bills = len(all_bills)
        paid_bills = len([b for b in all_bills if b["status"] == "paid"])
        overdue_bills = len([b for b in all_bills if b["status"] == "overdue"])
        total_outstanding_fen = sum(
            b["outstanding_fen"] for b in all_bills
            if b["status"] in ("issued", "partial_paid", "overdue")
        )

        # 月份列表（去重）
        months = sorted(set(b["month"] for b in all_bills))
        monthly_count = len(months)
        avg_monthly_fen = total_sign_amount_fen // monthly_count if monthly_count > 0 else 0

        analytics = {
            "enterprise_id": enterprise_id,
            "enterprise_name": enterprise["name"],
            "credit_limit_fen": enterprise["credit_limit_fen"],
            "credit_used_fen": enterprise["used_fen"],
            "credit_utilization": (
                round(enterprise["used_fen"] / enterprise["credit_limit_fen"], 4)
                if enterprise["credit_limit_fen"] > 0 else 0
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
            "payment_compliance_rate": (
                round(paid_bills / total_bills, 4) if total_bills > 0 else 1.0
            ),
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
