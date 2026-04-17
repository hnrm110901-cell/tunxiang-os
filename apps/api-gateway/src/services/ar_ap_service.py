"""
AR/AP 应收应付服务 — D7-P0 Must-Fix Task 2

核心能力：
  - create_ar / receive_ar: 应收创建 + 收款
  - create_ap / pay_ap: 应付创建 + 付款
  - aging_report: 账龄分析（0-30 / 31-60 / 61-90 / 90+）
  - mark_overdue: 定时任务标记逾期

金额字段统一以「分」存储，*_yuan 用于展示。
应收应付变更同时调用 voucher_service 写会计凭证：
  - AR 创建：借 应收账款1122 / 贷 主营业务收入6001
  - AR 收款：借 银行存款1002 / 贷 应收账款1122
  - AP 创建：借 库存商品1405（或费用类）/ 贷 应付账款2202
  - AP 付款：借 应付账款2202 / 贷 银行存款1002
"""

import uuid
from datetime import date as date_type
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundError, ValidationError
from src.models.ar_ap import (
    AccountPayable,
    AccountReceivable,
    APPayment,
    APStatus,
    ARPayment,
    ARStatus,
)
from src.services.voucher_service import VoucherService

logger = structlog.get_logger()


def _fen_to_yuan(fen: Optional[int]) -> float:
    return round((fen or 0) / 100, 2) if fen is not None else 0.0


class ARAPService:
    """应收应付台账服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._voucher = VoucherService(db)

    # ══════════════════════════════════════════════════════════════
    # 应收 AR
    # ══════════════════════════════════════════════════════════════

    async def create_ar(
        self,
        customer_name: str,
        amount_fen: int,
        operator_id: Optional[uuid.UUID] = None,
        customer_id: Optional[uuid.UUID] = None,
        customer_type: str = "credit_account",
        store_id: Optional[uuid.UUID] = None,
        brand_id: Optional[uuid.UUID] = None,
        source_bill_id: Optional[uuid.UUID] = None,
        source_ref: Optional[str] = None,
        due_date: Optional[date_type] = None,
        issue_date: Optional[date_type] = None,
        remark: Optional[str] = None,
        generate_voucher: bool = True,
    ) -> Dict[str, Any]:
        """创建应收"""
        if amount_fen <= 0:
            raise ValidationError("应收金额必须大于0")

        ar_no = await self._generate_ar_no(issue_date or date_type.today())
        ar = AccountReceivable(
            brand_id=brand_id,
            store_id=store_id,
            customer_type=customer_type,
            customer_id=customer_id,
            customer_name=customer_name,
            ar_no=ar_no,
            source_bill_id=source_bill_id,
            source_ref=source_ref,
            amount_fen=amount_fen,
            received_fen=0,
            issue_date=issue_date or date_type.today(),
            due_date=due_date,
            status=ARStatus.OPEN,
            remark=remark,
        )
        self.db.add(ar)
        await self.db.flush()

        if generate_voucher:
            # 借 应收账款1122 / 贷 主营业务收入6001
            await self._voucher.create_voucher(
                entries=[
                    {"account_code": "1122", "debit_fen": amount_fen, "summary": f"应收 {customer_name}"},
                    {"account_code": "6001", "credit_fen": amount_fen, "summary": f"挂账结算收入 {ar_no}"},
                ],
                summary=f"AR创建 {ar_no} {customer_name}",
                brand_id=brand_id,
                store_id=store_id,
                source_type="ar_create",
                source_id=ar.id,
                created_by=operator_id,
                commit=False,
            )

        await self.db.commit()
        await self.db.refresh(ar)
        logger.info("ar_created", ar_id=str(ar.id), ar_no=ar_no, amount_yuan=_fen_to_yuan(amount_fen))
        return self._ar_to_dict(ar)

    async def receive_ar(
        self,
        ar_id: uuid.UUID,
        amount_fen: int,
        operator_id: Optional[uuid.UUID] = None,
        payment_method: Optional[str] = "bank_transfer",
        payment_date: Optional[date_type] = None,
        reference_no: Optional[str] = None,
        remark: Optional[str] = None,
        generate_voucher: bool = True,
    ) -> Dict[str, Any]:
        """应收收款"""
        if amount_fen <= 0:
            raise ValidationError("收款金额必须大于0")

        ar = await self._get_ar_for_update(ar_id)
        if ar.status in (ARStatus.CLOSED, ARStatus.WRITTEN_OFF):
            raise ValidationError(f"应收状态为 {ar.status.value}，无法收款")

        outstanding = (ar.amount_fen or 0) - (ar.received_fen or 0)
        if amount_fen > outstanding:
            raise ValidationError(
                f"收款金额 {_fen_to_yuan(amount_fen)} 元超过应收余额 {_fen_to_yuan(outstanding)} 元"
            )

        ar.received_fen = (ar.received_fen or 0) + amount_fen
        if ar.received_fen >= ar.amount_fen:
            ar.status = ARStatus.CLOSED
        else:
            ar.status = ARStatus.PARTIAL

        payment = ARPayment(
            ar_id=ar.id,
            amount_fen=amount_fen,
            payment_date=payment_date or date_type.today(),
            payment_method=payment_method,
            reference_no=reference_no,
            operator_id=operator_id,
            remark=remark,
        )
        self.db.add(payment)

        if generate_voucher:
            # 借 银行存款1002 / 贷 应收账款1122
            await self._voucher.create_voucher(
                entries=[
                    {"account_code": "1002", "debit_fen": amount_fen, "summary": f"收款 {ar.customer_name}"},
                    {"account_code": "1122", "credit_fen": amount_fen, "summary": f"核销 {ar.ar_no}"},
                ],
                summary=f"AR收款 {ar.ar_no}",
                brand_id=ar.brand_id,
                store_id=ar.store_id,
                source_type="ar_receive",
                source_id=ar.id,
                created_by=operator_id,
                commit=False,
            )

        await self.db.commit()
        await self.db.refresh(ar)

        logger.info("ar_received", ar_id=str(ar_id), amount_yuan=_fen_to_yuan(amount_fen), status=ar.status.value)
        return self._ar_to_dict(ar)

    async def list_ar(
        self,
        store_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        customer_id: Optional[uuid.UUID] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        conditions = []
        if store_id:
            conditions.append(AccountReceivable.store_id == store_id)
        if status:
            conditions.append(AccountReceivable.status == ARStatus(status))
        if customer_id:
            conditions.append(AccountReceivable.customer_id == customer_id)

        count_stmt = select(func.count(AccountReceivable.id))
        if conditions:
            count_stmt = count_stmt.where(and_(*conditions))
        total = (await self.db.execute(count_stmt)).scalar() or 0

        stmt = select(AccountReceivable)
        if conditions:
            stmt = stmt.where(and_(*conditions))
        stmt = stmt.order_by(AccountReceivable.issue_date.desc()).limit(limit).offset(offset)
        rows = (await self.db.execute(stmt)).scalars().all()

        return {"total": total, "items": [self._ar_to_dict(r) for r in rows]}

    async def get_ar(self, ar_id: uuid.UUID) -> Dict[str, Any]:
        ar = await self._get_ar_or_raise(ar_id)
        pay_stmt = select(ARPayment).where(ARPayment.ar_id == ar_id).order_by(ARPayment.created_at.desc())
        payments = (await self.db.execute(pay_stmt)).scalars().all()
        d = self._ar_to_dict(ar)
        d["payments"] = [
            {
                "id": str(p.id),
                "amount_fen": p.amount_fen,
                "amount_yuan": _fen_to_yuan(p.amount_fen),
                "payment_date": p.payment_date.isoformat() if p.payment_date else None,
                "payment_method": p.payment_method,
                "reference_no": p.reference_no,
                "remark": p.remark,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in payments
        ]
        return d

    # ══════════════════════════════════════════════════════════════
    # 应付 AP
    # ══════════════════════════════════════════════════════════════

    async def create_ap(
        self,
        supplier_name: str,
        amount_fen: int,
        operator_id: Optional[uuid.UUID] = None,
        supplier_id: Optional[uuid.UUID] = None,
        store_id: Optional[uuid.UUID] = None,
        brand_id: Optional[uuid.UUID] = None,
        source_po_id: Optional[uuid.UUID] = None,
        source_ref: Optional[str] = None,
        due_date: Optional[date_type] = None,
        issue_date: Optional[date_type] = None,
        expense_account_code: str = "1405",  # 默认借 库存商品；可传 5001/6601 等成本/费用科目
        remark: Optional[str] = None,
        generate_voucher: bool = True,
    ) -> Dict[str, Any]:
        """创建应付"""
        if amount_fen <= 0:
            raise ValidationError("应付金额必须大于0")

        ap_no = await self._generate_ap_no(issue_date or date_type.today())
        ap = AccountPayable(
            brand_id=brand_id,
            store_id=store_id,
            supplier_id=supplier_id,
            supplier_name=supplier_name,
            ap_no=ap_no,
            source_po_id=source_po_id,
            source_ref=source_ref,
            amount_fen=amount_fen,
            paid_fen=0,
            issue_date=issue_date or date_type.today(),
            due_date=due_date,
            status=APStatus.OPEN,
            remark=remark,
        )
        self.db.add(ap)
        await self.db.flush()

        if generate_voucher:
            # 借 费用/存货科目 / 贷 应付账款2202
            await self._voucher.create_voucher(
                entries=[
                    {"account_code": expense_account_code, "debit_fen": amount_fen, "summary": f"采购 {supplier_name}"},
                    {"account_code": "2202", "credit_fen": amount_fen, "summary": f"应付 {ap_no}"},
                ],
                summary=f"AP创建 {ap_no} {supplier_name}",
                brand_id=brand_id,
                store_id=store_id,
                source_type="ap_create",
                source_id=ap.id,
                created_by=operator_id,
                commit=False,
            )

        await self.db.commit()
        await self.db.refresh(ap)
        logger.info("ap_created", ap_id=str(ap.id), ap_no=ap_no, amount_yuan=_fen_to_yuan(amount_fen))
        return self._ap_to_dict(ap)

    async def pay_ap(
        self,
        ap_id: uuid.UUID,
        amount_fen: int,
        operator_id: Optional[uuid.UUID] = None,
        payment_method: Optional[str] = "bank_transfer",
        payment_date: Optional[date_type] = None,
        reference_no: Optional[str] = None,
        remark: Optional[str] = None,
        generate_voucher: bool = True,
    ) -> Dict[str, Any]:
        """应付付款"""
        if amount_fen <= 0:
            raise ValidationError("付款金额必须大于0")

        ap = await self._get_ap_for_update(ap_id)
        if ap.status in (APStatus.CLOSED, APStatus.CANCELLED):
            raise ValidationError(f"应付状态为 {ap.status.value}，无法付款")

        outstanding = (ap.amount_fen or 0) - (ap.paid_fen or 0)
        if amount_fen > outstanding:
            raise ValidationError(
                f"付款金额 {_fen_to_yuan(amount_fen)} 元超过应付余额 {_fen_to_yuan(outstanding)} 元"
            )

        ap.paid_fen = (ap.paid_fen or 0) + amount_fen
        if ap.paid_fen >= ap.amount_fen:
            ap.status = APStatus.CLOSED
        else:
            ap.status = APStatus.PARTIAL

        payment = APPayment(
            ap_id=ap.id,
            amount_fen=amount_fen,
            payment_date=payment_date or date_type.today(),
            payment_method=payment_method,
            reference_no=reference_no,
            operator_id=operator_id,
            remark=remark,
        )
        self.db.add(payment)

        if generate_voucher:
            # 借 应付账款2202 / 贷 银行存款1002
            await self._voucher.create_voucher(
                entries=[
                    {"account_code": "2202", "debit_fen": amount_fen, "summary": f"付款 {ap.supplier_name}"},
                    {"account_code": "1002", "credit_fen": amount_fen, "summary": f"核销 {ap.ap_no}"},
                ],
                summary=f"AP付款 {ap.ap_no}",
                brand_id=ap.brand_id,
                store_id=ap.store_id,
                source_type="ap_pay",
                source_id=ap.id,
                created_by=operator_id,
                commit=False,
            )

        await self.db.commit()
        await self.db.refresh(ap)

        logger.info("ap_paid", ap_id=str(ap_id), amount_yuan=_fen_to_yuan(amount_fen), status=ap.status.value)
        return self._ap_to_dict(ap)

    async def list_ap(
        self,
        store_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        supplier_id: Optional[uuid.UUID] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        conditions = []
        if store_id:
            conditions.append(AccountPayable.store_id == store_id)
        if status:
            conditions.append(AccountPayable.status == APStatus(status))
        if supplier_id:
            conditions.append(AccountPayable.supplier_id == supplier_id)

        count_stmt = select(func.count(AccountPayable.id))
        if conditions:
            count_stmt = count_stmt.where(and_(*conditions))
        total = (await self.db.execute(count_stmt)).scalar() or 0

        stmt = select(AccountPayable)
        if conditions:
            stmt = stmt.where(and_(*conditions))
        stmt = stmt.order_by(AccountPayable.issue_date.desc()).limit(limit).offset(offset)
        rows = (await self.db.execute(stmt)).scalars().all()
        return {"total": total, "items": [self._ap_to_dict(r) for r in rows]}

    async def get_ap(self, ap_id: uuid.UUID) -> Dict[str, Any]:
        ap = await self._get_ap_or_raise(ap_id)
        pay_stmt = select(APPayment).where(APPayment.ap_id == ap_id).order_by(APPayment.created_at.desc())
        payments = (await self.db.execute(pay_stmt)).scalars().all()
        d = self._ap_to_dict(ap)
        d["payments"] = [
            {
                "id": str(p.id),
                "amount_fen": p.amount_fen,
                "amount_yuan": _fen_to_yuan(p.amount_fen),
                "payment_date": p.payment_date.isoformat() if p.payment_date else None,
                "payment_method": p.payment_method,
                "reference_no": p.reference_no,
                "remark": p.remark,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in payments
        ]
        return d

    # ══════════════════════════════════════════════════════════════
    # 账龄报表
    # ══════════════════════════════════════════════════════════════

    async def aging_report(
        self,
        kind: str = "ar",   # "ar" or "ap"
        store_id: Optional[uuid.UUID] = None,
        as_of: Optional[date_type] = None,
    ) -> Dict[str, Any]:
        """账龄分析（0-30 / 31-60 / 61-90 / 90+ 天，按 issue_date 计）"""
        as_of = as_of or date_type.today()

        if kind == "ar":
            model = AccountReceivable
            open_statuses = [ARStatus.OPEN, ARStatus.PARTIAL, ARStatus.OVERDUE]
            outstanding_expr = (model.amount_fen - model.received_fen)
        elif kind == "ap":
            model = AccountPayable
            open_statuses = [APStatus.OPEN, APStatus.PARTIAL, APStatus.OVERDUE]
            outstanding_expr = (model.amount_fen - model.paid_fen)
        else:
            raise ValidationError("kind 必须为 ar 或 ap")

        conditions = [model.status.in_(open_statuses)]
        if store_id:
            conditions.append(model.store_id == store_id)

        stmt = select(model).where(and_(*conditions))
        rows = (await self.db.execute(stmt)).scalars().all()

        buckets = {"0_30": 0, "31_60": 0, "61_90": 0, "90_plus": 0}
        bucket_items: Dict[str, List[Dict[str, Any]]] = {k: [] for k in buckets}
        for r in rows:
            outstanding = (r.amount_fen or 0) - ((r.received_fen if kind == "ar" else r.paid_fen) or 0)
            if outstanding <= 0:
                continue
            days = (as_of - r.issue_date).days
            if days <= 30:
                key = "0_30"
            elif days <= 60:
                key = "31_60"
            elif days <= 90:
                key = "61_90"
            else:
                key = "90_plus"
            buckets[key] += outstanding
            bucket_items[key].append(
                {
                    "id": str(r.id),
                    "no": r.ar_no if kind == "ar" else r.ap_no,
                    "party_name": r.customer_name if kind == "ar" else r.supplier_name,
                    "outstanding_fen": outstanding,
                    "outstanding_yuan": _fen_to_yuan(outstanding),
                    "days_overdue": days,
                    "issue_date": r.issue_date.isoformat() if r.issue_date else None,
                    "due_date": r.due_date.isoformat() if r.due_date else None,
                }
            )

        total_fen = sum(buckets.values())
        return {
            "kind": kind,
            "as_of": as_of.isoformat(),
            "total_fen": total_fen,
            "total_yuan": _fen_to_yuan(total_fen),
            "buckets": {
                k: {
                    "amount_fen": v,
                    "amount_yuan": _fen_to_yuan(v),
                    "count": len(bucket_items[k]),
                    "items": bucket_items[k],
                }
                for k, v in buckets.items()
            },
        }

    async def mark_overdue(self, as_of: Optional[date_type] = None) -> Dict[str, int]:
        """标记逾期（应收/应付）— 供 Celery 定时任务调用"""
        as_of = as_of or date_type.today()
        ar_count = 0
        ap_count = 0

        # AR: due_date < as_of 且 status in (OPEN, PARTIAL)
        ar_stmt = select(AccountReceivable).where(
            and_(
                AccountReceivable.due_date < as_of,
                AccountReceivable.status.in_([ARStatus.OPEN, ARStatus.PARTIAL]),
            )
        )
        ars = (await self.db.execute(ar_stmt)).scalars().all()
        for ar in ars:
            ar.status = ARStatus.OVERDUE
            ar_count += 1

        ap_stmt = select(AccountPayable).where(
            and_(
                AccountPayable.due_date < as_of,
                AccountPayable.status.in_([APStatus.OPEN, APStatus.PARTIAL]),
            )
        )
        aps = (await self.db.execute(ap_stmt)).scalars().all()
        for ap in aps:
            ap.status = APStatus.OVERDUE
            ap_count += 1

        await self.db.commit()
        logger.info("ar_ap_overdue_marked", ar_count=ar_count, ap_count=ap_count)
        return {"ar_marked": ar_count, "ap_marked": ap_count}

    # ══════════════════════════════════════════════════════════════
    # 私有
    # ══════════════════════════════════════════════════════════════

    async def _generate_ar_no(self, d: date_type) -> str:
        date_str = d.strftime("%Y%m%d")
        stmt = select(func.count(AccountReceivable.id)).where(AccountReceivable.ar_no.like(f"AR{date_str}%"))
        count = (await self.db.execute(stmt)).scalar() or 0
        return f"AR{date_str}{count + 1:06d}"

    async def _generate_ap_no(self, d: date_type) -> str:
        date_str = d.strftime("%Y%m%d")
        stmt = select(func.count(AccountPayable.id)).where(AccountPayable.ap_no.like(f"AP{date_str}%"))
        count = (await self.db.execute(stmt)).scalar() or 0
        return f"AP{date_str}{count + 1:06d}"

    async def _get_ar_for_update(self, ar_id: uuid.UUID) -> AccountReceivable:
        stmt = select(AccountReceivable).where(AccountReceivable.id == ar_id).with_for_update()
        r = (await self.db.execute(stmt)).scalar_one_or_none()
        if not r:
            raise NotFoundError(f"应收 {ar_id} 不存在")
        return r

    async def _get_ar_or_raise(self, ar_id: uuid.UUID) -> AccountReceivable:
        stmt = select(AccountReceivable).where(AccountReceivable.id == ar_id)
        r = (await self.db.execute(stmt)).scalar_one_or_none()
        if not r:
            raise NotFoundError(f"应收 {ar_id} 不存在")
        return r

    async def _get_ap_for_update(self, ap_id: uuid.UUID) -> AccountPayable:
        stmt = select(AccountPayable).where(AccountPayable.id == ap_id).with_for_update()
        r = (await self.db.execute(stmt)).scalar_one_or_none()
        if not r:
            raise NotFoundError(f"应付 {ap_id} 不存在")
        return r

    async def _get_ap_or_raise(self, ap_id: uuid.UUID) -> AccountPayable:
        stmt = select(AccountPayable).where(AccountPayable.id == ap_id)
        r = (await self.db.execute(stmt)).scalar_one_or_none()
        if not r:
            raise NotFoundError(f"应付 {ap_id} 不存在")
        return r

    @staticmethod
    def _ar_to_dict(ar: AccountReceivable) -> Dict[str, Any]:
        outstanding = (ar.amount_fen or 0) - (ar.received_fen or 0)
        return {
            "id": str(ar.id),
            "ar_no": ar.ar_no,
            "brand_id": str(ar.brand_id) if ar.brand_id else None,
            "store_id": str(ar.store_id) if ar.store_id else None,
            "customer_type": ar.customer_type,
            "customer_id": str(ar.customer_id) if ar.customer_id else None,
            "customer_name": ar.customer_name,
            "source_bill_id": str(ar.source_bill_id) if ar.source_bill_id else None,
            "source_ref": ar.source_ref,
            "amount_fen": ar.amount_fen,
            "amount_yuan": _fen_to_yuan(ar.amount_fen),
            "received_fen": ar.received_fen,
            "received_yuan": _fen_to_yuan(ar.received_fen),
            "outstanding_fen": outstanding,
            "outstanding_yuan": _fen_to_yuan(outstanding),
            "issue_date": ar.issue_date.isoformat() if ar.issue_date else None,
            "due_date": ar.due_date.isoformat() if ar.due_date else None,
            "status": ar.status.value,
            "remark": ar.remark,
            "created_at": ar.created_at.isoformat() if ar.created_at else None,
        }

    @staticmethod
    def _ap_to_dict(ap: AccountPayable) -> Dict[str, Any]:
        outstanding = (ap.amount_fen or 0) - (ap.paid_fen or 0)
        return {
            "id": str(ap.id),
            "ap_no": ap.ap_no,
            "brand_id": str(ap.brand_id) if ap.brand_id else None,
            "store_id": str(ap.store_id) if ap.store_id else None,
            "supplier_id": str(ap.supplier_id) if ap.supplier_id else None,
            "supplier_name": ap.supplier_name,
            "source_po_id": str(ap.source_po_id) if ap.source_po_id else None,
            "source_ref": ap.source_ref,
            "amount_fen": ap.amount_fen,
            "amount_yuan": _fen_to_yuan(ap.amount_fen),
            "paid_fen": ap.paid_fen,
            "paid_yuan": _fen_to_yuan(ap.paid_fen),
            "outstanding_fen": outstanding,
            "outstanding_yuan": _fen_to_yuan(outstanding),
            "issue_date": ap.issue_date.isoformat() if ap.issue_date else None,
            "due_date": ap.due_date.isoformat() if ap.due_date else None,
            "status": ap.status.value,
            "remark": ap.remark,
            "created_at": ap.created_at.isoformat() if ap.created_at else None,
        }


def get_ar_ap_service(db: AsyncSession) -> ARAPService:
    return ARAPService(db)
