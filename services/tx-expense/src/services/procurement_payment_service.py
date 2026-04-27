"""
采购付款联动服务
负责采购付款单的完整生命周期：自动创建、审批、付款、发票匹配、对账。

金额约定：所有金额存储为分(fen)，入参/出参统一用分，展示层负责转换。

设计原则：
  - 幂等性：create_from_purchase_order 通过 (tenant_id, purchase_order_id) 唯一键保证
  - 跨服务调用：fetch_purchase_order_from_supply 通过 httpx 调用 tx-supply，10s 超时
  - 失败隔离：外部服务调用失败返回 None 并记录错误日志，不向上抛出
  - 所有 DB 查询显式传入 tenant_id
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models.procurement_payment import (
    ProcurementPayment,
    ProcurementPaymentItem,
    ProcurementReconciliation,
)

logger = structlog.get_logger(__name__)


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


class ProcurementPaymentService:
    """采购付款联动服务（无状态，所有方法接收显式 db session）。"""

    TX_SUPPLY_URL: str = os.getenv("TX_SUPPLY_URL", "http://localhost:8006")

    # ─────────────────────────────────────────────────────────────────────────
    # 创建 & 查询
    # ─────────────────────────────────────────────────────────────────────────

    async def create_from_purchase_order(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        order_data: dict,
    ) -> ProcurementPayment:
        """从采购订单数据创建付款单（幂等：purchase_order_id 唯一键保护）。

        order_data 预期字段（均为可选，但 purchase_order_id 和 total_amount 必须存在）：
            purchase_order_id  (str UUID 或 UUID, 必填)
            purchase_order_no  (str, 可选)
            supplier_id        (str UUID 或 UUID, 可选)
            supplier_name      (str, 可选)
            total_amount       (int 分, 必填)
            payment_type       (str, 可选, 默认 purchase)
            due_date           (str ISO date 或 date, 可选)
            items              (list[dict], 可选)
            created_by         (str UUID 或 UUID, 可选)

        Returns:
            ProcurementPayment — 新建或已存在的付款单。
        """
        log = logger.bind(tenant_id=str(tenant_id))

        # 解析 purchase_order_id
        raw_order_id = order_data.get("purchase_order_id")
        if raw_order_id is None:
            raise ValueError("order_data 必须包含 purchase_order_id")
        purchase_order_id = raw_order_id if isinstance(raw_order_id, uuid.UUID) else uuid.UUID(str(raw_order_id))

        total_amount = order_data.get("total_amount")
        if total_amount is None:
            raise ValueError("order_data 必须包含 total_amount（单位：分）")

        # 解析可选字段
        supplier_id: Optional[uuid.UUID] = None
        raw_supplier_id = order_data.get("supplier_id")
        if raw_supplier_id:
            supplier_id = raw_supplier_id if isinstance(raw_supplier_id, uuid.UUID) else uuid.UUID(str(raw_supplier_id))

        created_by: Optional[uuid.UUID] = None
        raw_created_by = order_data.get("created_by")
        if raw_created_by:
            created_by = raw_created_by if isinstance(raw_created_by, uuid.UUID) else uuid.UUID(str(raw_created_by))

        due_date = order_data.get("due_date")
        if isinstance(due_date, str) and due_date:
            from datetime import date as _date

            due_date = _date.fromisoformat(due_date)

        payment = ProcurementPayment(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            purchase_order_id=purchase_order_id,
            purchase_order_no=order_data.get("purchase_order_no"),
            supplier_id=supplier_id,
            supplier_name=order_data.get("supplier_name"),
            payment_type=order_data.get("payment_type", "purchase"),
            total_amount=int(total_amount),
            paid_amount=0,
            status="pending",
            due_date=due_date,
            notes=order_data.get("notes"),
            created_by=created_by,
        )
        db.add(payment)

        try:
            await db.flush()
        except IntegrityError:
            # 唯一键冲突：该采购订单的付款单已存在，查询并返回已有记录
            await db.rollback()
            existing = await self._get_by_purchase_order_id(db, tenant_id, purchase_order_id)
            if existing is None:
                raise LookupError(
                    f"ProcurementPayment for purchase_order_id={purchase_order_id} "
                    f"exists but cannot be fetched for tenant {tenant_id}"
                )
            log.info(
                "procurement_payment_already_exists",
                purchase_order_id=str(purchase_order_id),
                payment_id=str(existing.id),
            )
            return existing

        # 创建付款条目（若提供）
        items_data: list[dict] = order_data.get("items") or []
        if items_data:
            payment_items = []
            for item in items_data:
                raw_item_supplier_id = item.get("order_item_id")
                order_item_id = uuid.UUID(str(raw_item_supplier_id)) if raw_item_supplier_id else None
                pi = ProcurementPaymentItem(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    payment_id=payment.id,
                    order_item_id=order_item_id,
                    product_name=item.get("product_name"),
                    quantity=item.get("quantity"),
                    unit_price=item.get("unit_price"),
                    amount=int(item["amount"]),
                )
                payment_items.append(pi)
            db.add_all(payment_items)
            await db.flush()

        log.info(
            "procurement_payment_created",
            payment_id=str(payment.id),
            purchase_order_id=str(purchase_order_id),
            total_amount=payment.total_amount,
            item_count=len(items_data),
        )
        return payment

    async def get_payment(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        payment_id: uuid.UUID,
    ) -> ProcurementPayment:
        """查询单张付款单，预加载 items 和 reconciliations。

        Raises:
            LookupError: 找不到或跨租户访问时抛出（路由层转换为 404）。
        """
        stmt = (
            select(ProcurementPayment)
            .where(
                ProcurementPayment.id == payment_id,
                ProcurementPayment.tenant_id == tenant_id,
                ProcurementPayment.is_deleted == False,  # noqa: E712
            )
            .options(
                selectinload(ProcurementPayment.items),
                selectinload(ProcurementPayment.reconciliations),
            )
        )
        result = await db.execute(stmt)
        payment = result.scalar_one_or_none()
        if payment is None:
            raise LookupError(f"ProcurementPayment {payment_id} not found for tenant {tenant_id}")
        return payment

    async def list_payments(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        filters: dict,
    ) -> tuple[list[ProcurementPayment], int]:
        """列出付款单，支持多条件过滤，按 created_at DESC 排序。

        filters 支持字段：
            status        (str)
            supplier_id   (UUID 或 str)
            payment_type  (str)
            page          (int, 默认 1)
            page_size     (int, 默认 20)

        Returns:
            (items, total_count)
        """
        base_where = [
            ProcurementPayment.tenant_id == tenant_id,
            ProcurementPayment.is_deleted == False,  # noqa: E712
        ]

        if filters.get("status"):
            base_where.append(ProcurementPayment.status == filters["status"])
        if filters.get("supplier_id"):
            sid = filters["supplier_id"]
            if isinstance(sid, str):
                sid = uuid.UUID(sid)
            base_where.append(ProcurementPayment.supplier_id == sid)
        if filters.get("payment_type"):
            base_where.append(ProcurementPayment.payment_type == filters["payment_type"])

        count_stmt = select(func.count()).select_from(ProcurementPayment).where(*base_where)
        count_result = await db.execute(count_stmt)
        total_count = count_result.scalar_one()

        page = max(1, int(filters.get("page", 1)))
        page_size = max(1, min(100, int(filters.get("page_size", 20))))
        offset = (page - 1) * page_size

        items_stmt = (
            select(ProcurementPayment)
            .where(*base_where)
            .order_by(ProcurementPayment.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        items_result = await db.execute(items_stmt)
        items = list(items_result.scalars().all())

        return items, total_count

    async def update_payment(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        payment_id: uuid.UUID,
        data: dict,
    ) -> ProcurementPayment:
        """更新付款单字段（仅 pending 状态允许修改）。

        可更新字段：purchase_order_no、supplier_name、payment_type、due_date、notes。

        Raises:
            LookupError: 找不到时抛出。
            ValueError: 状态不允许编辑时抛出。
        """
        payment = await self.get_payment(db, tenant_id, payment_id)

        if payment.status not in ("pending",):
            raise ValueError(f"付款单状态为 '{payment.status}'，只有 pending 状态允许编辑")

        updatable = {"purchase_order_no", "supplier_name", "payment_type", "due_date", "notes"}
        for field in updatable:
            if field in data:
                setattr(payment, field, data[field])

        payment.updated_at = _now_utc()
        await db.flush()

        logger.info(
            "procurement_payment_updated",
            tenant_id=str(tenant_id),
            payment_id=str(payment_id),
            updated_fields=list(data.keys()),
        )
        return payment

    # ─────────────────────────────────────────────────────────────────────────
    # 状态流转
    # ─────────────────────────────────────────────────────────────────────────

    async def approve_payment(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        payment_id: uuid.UUID,
        approved_by: uuid.UUID,
    ) -> ProcurementPayment:
        """审批通过付款单（pending → approved）。

        Raises:
            LookupError: 找不到时抛出。
            ValueError: 状态不是 pending 时抛出。
        """
        payment = await self.get_payment(db, tenant_id, payment_id)

        if payment.status != "pending":
            raise ValueError(f"付款单状态为 '{payment.status}'，只有 pending 状态可以审批通过")

        payment.status = "approved"
        payment.updated_at = _now_utc()
        await db.flush()

        logger.info(
            "procurement_payment_approved",
            tenant_id=str(tenant_id),
            payment_id=str(payment_id),
            approved_by=str(approved_by),
        )
        return payment

    async def mark_paid(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        payment_id: uuid.UUID,
        paid_amount: int,
    ) -> ProcurementPayment:
        """标记付款单已付（approved → paid）并更新已付金额。

        Args:
            paid_amount: 本次实付金额（分）。

        Raises:
            LookupError: 找不到时抛出。
            ValueError: 状态不是 approved 时抛出，或金额非正数时抛出。
        """
        if paid_amount <= 0:
            raise ValueError(f"paid_amount 必须为正整数（分），收到：{paid_amount}")

        payment = await self.get_payment(db, tenant_id, payment_id)

        if payment.status != "approved":
            raise ValueError(f"付款单状态为 '{payment.status}'，只有 approved 状态可以标记为已付")

        payment.paid_amount = paid_amount
        payment.status = "paid"
        payment.updated_at = _now_utc()
        await db.flush()

        logger.info(
            "procurement_payment_marked_paid",
            tenant_id=str(tenant_id),
            payment_id=str(payment_id),
            paid_amount=paid_amount,
            total_amount=payment.total_amount,
        )
        return payment

    # ─────────────────────────────────────────────────────────────────────────
    # 发票匹配 & 对账
    # ─────────────────────────────────────────────────────────────────────────

    async def match_invoice(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        payment_id: uuid.UUID,
        invoice_id: uuid.UUID,
    ) -> dict:
        """将发票与付款条目匹配。

        将 payment_id 下所有未匹配条目（invoice_id IS NULL）更新为 invoice_id。

        Returns:
            {
                "payment_id": str,
                "invoice_id": str,
                "matched_items": int,  # 本次匹配的条目数
                "already_matched": int, # 已有匹配的条目数（本次跳过）
            }
        """
        payment = await self.get_payment(db, tenant_id, payment_id)

        matched = 0
        already_matched = 0
        for item in payment.items:
            if item.is_deleted:
                continue
            if item.invoice_id is None:
                item.invoice_id = invoice_id
                matched += 1
            else:
                already_matched += 1

        await db.flush()

        logger.info(
            "procurement_invoice_matched",
            tenant_id=str(tenant_id),
            payment_id=str(payment_id),
            invoice_id=str(invoice_id),
            matched_items=matched,
            already_matched=already_matched,
        )
        return {
            "payment_id": str(payment_id),
            "invoice_id": str(invoice_id),
            "matched_items": matched,
            "already_matched": already_matched,
        }

    async def reconcile(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        payment_id: uuid.UUID,
    ) -> ProcurementReconciliation:
        """创建对账记录：比较付款单金额 vs 发票条目总金额，记录差异。

        差异金额 = payment.total_amount - 发票条目总金额（分）。
        差异 = 0 → matched；差异 ≠ 0 → discrepancy。

        Returns:
            新建的 ProcurementReconciliation 对象。
        """
        payment = await self.get_payment(db, tenant_id, payment_id)

        # 计算已匹配发票的条目总金额
        invoice_amount = sum(
            item.amount for item in payment.items if not item.is_deleted and item.invoice_id is not None
        )
        payment_amount = payment.total_amount
        discrepancy = payment_amount - invoice_amount

        if discrepancy == 0:
            recon_status = "matched"
        else:
            recon_status = "discrepancy"

        recon = ProcurementReconciliation(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            payment_id=payment_id,
            reconciliation_status=recon_status,
            payment_amount=payment_amount,
            invoice_amount=invoice_amount,
            discrepancy_amount=discrepancy,
            reconciled_at=_now_utc(),
        )
        db.add(recon)
        await db.flush()

        logger.info(
            "procurement_reconciliation_created",
            tenant_id=str(tenant_id),
            payment_id=str(payment_id),
            reconciliation_id=str(recon.id),
            status=recon_status,
            discrepancy_amount=discrepancy,
        )
        return recon

    # ─────────────────────────────────────────────────────────────────────────
    # 统计
    # ─────────────────────────────────────────────────────────────────────────

    async def get_supplier_payment_stats(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        supplier_id: uuid.UUID,
    ) -> dict:
        """供应商付款统计。

        Returns:
            {
                "supplier_id": str,
                "total_payments": int,      # 付款单总数
                "total_amount": int,        # 总付款金额（分）
                "paid_amount": int,         # 已付金额合计（分）
                "pending_amount": int,      # 待付金额合计（分）
                "avg_payment_days": float,  # 平均账期天数（从创建到 paid，无法计算时为 None）
            }
        """
        base_where = [
            ProcurementPayment.tenant_id == tenant_id,
            ProcurementPayment.supplier_id == supplier_id,
            ProcurementPayment.is_deleted == False,  # noqa: E712
        ]

        stats_stmt = select(
            func.count().label("total_payments"),
            func.coalesce(func.sum(ProcurementPayment.total_amount), 0).label("total_amount"),
            func.coalesce(func.sum(ProcurementPayment.paid_amount), 0).label("paid_amount_sum"),
        ).where(*base_where)
        stats_result = await db.execute(stats_stmt)
        row = stats_result.mappings().one()

        total_payments = int(row["total_payments"])
        total_amount = int(row["total_amount"])
        paid_amount_sum = int(row["paid_amount_sum"])
        pending_amount = total_amount - paid_amount_sum

        # 平均账期天数：仅对 paid 状态的付款单计算（updated_at - created_at）
        paid_stmt = select(
            ProcurementPayment.created_at,
            ProcurementPayment.updated_at,
        ).where(
            *base_where,
            ProcurementPayment.status == "paid",
        )
        paid_result = await db.execute(paid_stmt)
        paid_rows = paid_result.all()

        avg_days: Optional[float] = None
        if paid_rows:
            day_diffs = []
            for r in paid_rows:
                if r.created_at and r.updated_at:
                    delta = r.updated_at - r.created_at
                    day_diffs.append(delta.total_seconds() / 86400)
            if day_diffs:
                avg_days = round(sum(day_diffs) / len(day_diffs), 1)

        logger.info(
            "supplier_payment_stats_fetched",
            tenant_id=str(tenant_id),
            supplier_id=str(supplier_id),
            total_payments=total_payments,
        )
        return {
            "supplier_id": str(supplier_id),
            "total_payments": total_payments,
            "total_amount": total_amount,
            "paid_amount": paid_amount_sum,
            "pending_amount": pending_amount,
            "avg_payment_days": avg_days,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # 跨服务调用 tx-supply
    # ─────────────────────────────────────────────────────────────────────────

    async def fetch_purchase_order_from_supply(
        self,
        tenant_id: uuid.UUID,
        order_id: uuid.UUID,
    ) -> Optional[dict]:
        """HTTP 调用 tx-supply 获取采购订单详情。

        失败时返回 None 并记录 error 日志，不向上抛出异常。
        超时：10 秒。
        """
        url = f"{self.TX_SUPPLY_URL}/api/v1/supply/purchase-orders/{order_id}"
        log = logger.bind(
            tenant_id=str(tenant_id),
            order_id=str(order_id),
            url=url,
        )
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    url,
                    headers={"X-Tenant-ID": str(tenant_id)},
                )
                resp.raise_for_status()
                data = resp.json()
                log.info(
                    "purchase_order_fetched_from_supply",
                    status_code=resp.status_code,
                )
                return data.get("data") or data
        except httpx.TimeoutException as exc:
            log.error(
                "purchase_order_fetch_timeout",
                error=str(exc),
                exc_info=True,
            )
            return None
        except httpx.HTTPStatusError as exc:
            log.error(
                "purchase_order_fetch_http_error",
                status_code=exc.response.status_code,
                error=str(exc),
                exc_info=True,
            )
            return None
        except httpx.RequestError as exc:
            log.error(
                "purchase_order_fetch_request_error",
                error=str(exc),
                exc_info=True,
            )
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # 内部辅助
    # ─────────────────────────────────────────────────────────────────────────

    async def _get_by_purchase_order_id(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        purchase_order_id: uuid.UUID,
    ) -> Optional[ProcurementPayment]:
        """按 purchase_order_id 查询付款单（幂等创建时使用）。"""
        stmt = select(ProcurementPayment).where(
            ProcurementPayment.tenant_id == tenant_id,
            ProcurementPayment.purchase_order_id == purchase_order_id,
            ProcurementPayment.is_deleted == False,  # noqa: E712
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def cancel_payment_by_order_id(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        purchase_order_id: uuid.UUID,
    ) -> Optional[ProcurementPayment]:
        """根据采购订单ID查找付款单并标记为 cancelled（事件消费者调用）。

        若未找到对应付款单，返回 None（非异常，订单可能从未生成付款单）。

        Returns:
            被取消的 ProcurementPayment，或 None。
        """
        payment = await self._get_by_purchase_order_id(db, tenant_id, purchase_order_id)
        if payment is None:
            logger.info(
                "procurement_payment_cancel_no_record",
                tenant_id=str(tenant_id),
                purchase_order_id=str(purchase_order_id),
            )
            return None

        if payment.status == "cancelled":
            logger.info(
                "procurement_payment_already_cancelled",
                tenant_id=str(tenant_id),
                payment_id=str(payment.id),
            )
            return payment

        payment.status = "cancelled"
        payment.updated_at = _now_utc()
        await db.flush()

        logger.info(
            "procurement_payment_cancelled_by_order",
            tenant_id=str(tenant_id),
            payment_id=str(payment.id),
            purchase_order_id=str(purchase_order_id),
        )
        return payment
