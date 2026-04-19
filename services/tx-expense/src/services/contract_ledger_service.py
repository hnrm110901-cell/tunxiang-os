"""
合同台账服务
负责合同的完整生命周期管理：登记、查询、付款计划、预警生成、统计。

金额约定：所有金额存储为分(fen)，入参/出参统一用分，展示层负责转换。
幂等约定：generate_alerts 按 (tenant_id, contract_id, alert_type, 日期) 去重，
         同一天不重复创建同类型预警记录。
"""

from __future__ import annotations

import uuid
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models.contract import Contract, ContractAlert, ContractPayment

logger = structlog.get_logger(__name__)


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _today() -> date:
    return date.today()


# ─────────────────────────────────────────────────────────────────────────────
# ContractLedgerService
# ─────────────────────────────────────────────────────────────────────────────


class ContractLedgerService:
    """合同台账服务：12个方法覆盖合同全生命周期。"""

    # -------------------------------------------------------------------------
    # 合同 CRUD
    # -------------------------------------------------------------------------

    async def create_contract(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        created_by: uuid.UUID,
        data: dict,
    ) -> Contract:
        """登记新合同。

        data 支持字段：
            contract_no, contract_name, contract_type,
            counterparty_name, counterparty_contact,
            total_amount, start_date, end_date,
            auto_renew, renewal_notice_days, status,
            store_id, responsible_person, file_url, notes
        """
        log = logger.bind(tenant_id=str(tenant_id), created_by=str(created_by))

        if not data.get("contract_name"):
            raise ValueError("contract_name 不能为空")

        contract = Contract(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            created_by=created_by,
            contract_no=data.get("contract_no"),
            contract_name=data["contract_name"],
            contract_type=data.get("contract_type"),
            counterparty_name=data.get("counterparty_name"),
            counterparty_contact=data.get("counterparty_contact"),
            total_amount=data.get("total_amount"),
            paid_amount=data.get("paid_amount", 0),
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
            auto_renew=data.get("auto_renew", False),
            renewal_notice_days=data.get("renewal_notice_days", 30),
            status=data.get("status", "active"),
            store_id=data.get("store_id"),
            responsible_person=data.get("responsible_person"),
            file_url=data.get("file_url"),
            notes=data.get("notes"),
        )
        db.add(contract)
        await db.flush()

        log.info(
            "contract_created",
            contract_id=str(contract.id),
            contract_name=contract.contract_name,
            contract_type=contract.contract_type,
        )
        return contract

    async def get_contract(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        contract_id: uuid.UUID,
    ) -> Contract:
        """查询单个合同，预加载付款计划。

        Raises:
            LookupError: 不存在或跨租户访问。
        """
        stmt = (
            select(Contract)
            .where(
                Contract.id == contract_id,
                Contract.tenant_id == tenant_id,
                Contract.is_deleted == False,  # noqa: E712
            )
            .options(
                selectinload(Contract.payments),
                selectinload(Contract.alerts),
            )
        )
        result = await db.execute(stmt)
        contract = result.scalar_one_or_none()
        if contract is None:
            raise LookupError(f"Contract {contract_id} not found for tenant {tenant_id}")
        return contract

    async def list_contracts(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        filters: dict,
    ) -> list[Contract]:
        """查询合同列表，支持多条件过滤。

        filters 支持：
            status (str), contract_type (str),
            store_id (UUID), expiring_within_days (int)
        """
        base_where = [
            Contract.tenant_id == tenant_id,
            Contract.is_deleted == False,  # noqa: E712
        ]

        if filters.get("status"):
            base_where.append(Contract.status == filters["status"])
        if filters.get("contract_type"):
            base_where.append(Contract.contract_type == filters["contract_type"])
        if filters.get("store_id"):
            base_where.append(Contract.store_id == filters["store_id"])
        if filters.get("expiring_within_days") is not None:
            today = _today()
            cutoff = today + timedelta(days=int(filters["expiring_within_days"]))
            base_where.extend(
                [
                    Contract.end_date >= today,
                    Contract.end_date <= cutoff,
                ]
            )

        stmt = (
            select(Contract)
            .where(*base_where)
            .order_by(Contract.end_date.asc().nullslast(), Contract.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def update_contract(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        contract_id: uuid.UUID,
        data: dict,
    ) -> Contract:
        """更新合同信息。terminated 状态的合同不允许更新（用 terminate_contract）。"""
        contract = await self.get_contract(db, tenant_id, contract_id)

        if contract.status == "terminated":
            raise ValueError("已终止的合同不允许更新，请使用 terminate_contract")

        updatable_fields = {
            "contract_no",
            "contract_name",
            "contract_type",
            "counterparty_name",
            "counterparty_contact",
            "total_amount",
            "start_date",
            "end_date",
            "auto_renew",
            "renewal_notice_days",
            "status",
            "store_id",
            "responsible_person",
            "file_url",
            "notes",
        }
        for field in updatable_fields:
            if field in data:
                setattr(contract, field, data[field])

        await db.flush()

        logger.info(
            "contract_updated",
            tenant_id=str(tenant_id),
            contract_id=str(contract_id),
            updated_fields=list(data.keys()),
        )
        return contract

    async def terminate_contract(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        contract_id: uuid.UUID,
        reason: str,
    ) -> Contract:
        """终止合同，记录终止原因到 notes。"""
        contract = await self.get_contract(db, tenant_id, contract_id)

        if contract.status == "terminated":
            raise ValueError("合同已处于终止状态")

        contract.status = "terminated"
        existing_notes = contract.notes or ""
        term_note = f"[终止] {_today().isoformat()}: {reason}"
        contract.notes = f"{existing_notes}；{term_note}" if existing_notes else term_note

        await db.flush()

        logger.info(
            "contract_terminated",
            tenant_id=str(tenant_id),
            contract_id=str(contract_id),
            reason=reason,
        )
        return contract

    # -------------------------------------------------------------------------
    # 付款计划
    # -------------------------------------------------------------------------

    async def add_payment_plan(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        contract_id: uuid.UUID,
        data: dict,
    ) -> ContractPayment:
        """为合同添加付款计划期次。

        data 必填：due_date, planned_amount
        data 可选：period_name, notes
        """
        # 确认合同存在且属于该租户
        await self.get_contract(db, tenant_id, contract_id)

        if not data.get("due_date"):
            raise ValueError("due_date 不能为空")
        if not data.get("planned_amount"):
            raise ValueError("planned_amount 不能为空")

        payment = ContractPayment(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            contract_id=contract_id,
            period_name=data.get("period_name"),
            due_date=data["due_date"],
            planned_amount=int(data["planned_amount"]),
            actual_amount=None,
            status="pending",
            notes=data.get("notes"),
        )
        db.add(payment)
        await db.flush()

        logger.info(
            "contract_payment_plan_added",
            tenant_id=str(tenant_id),
            contract_id=str(contract_id),
            payment_id=str(payment.id),
            due_date=str(data["due_date"]),
            planned_amount=payment.planned_amount,
        )
        return payment

    async def mark_payment_paid(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        payment_id: uuid.UUID,
        actual_amount: int,
    ) -> ContractPayment:
        """标记付款计划已付，并更新合同的 paid_amount 累计值。"""
        stmt = select(ContractPayment).where(
            ContractPayment.id == payment_id,
            ContractPayment.tenant_id == tenant_id,
            ContractPayment.is_deleted == False,  # noqa: E712
        )
        result = await db.execute(stmt)
        payment = result.scalar_one_or_none()

        if payment is None:
            raise LookupError(f"ContractPayment {payment_id} not found for tenant {tenant_id}")
        if payment.status == "paid":
            raise ValueError("该付款计划已标记为已付")
        if actual_amount <= 0:
            raise ValueError("actual_amount 必须大于0（单位：分）")

        payment.actual_amount = actual_amount
        payment.status = "paid"
        payment.paid_at = _now_utc()
        await db.flush()

        # 同步更新合同的 paid_amount 汇总
        sum_stmt = select(func.coalesce(func.sum(ContractPayment.actual_amount), 0)).where(
            ContractPayment.contract_id == payment.contract_id,
            ContractPayment.tenant_id == tenant_id,
            ContractPayment.status == "paid",
            ContractPayment.is_deleted == False,  # noqa: E712
        )
        sum_result = await db.execute(sum_stmt)
        total_paid = int(sum_result.scalar_one())

        await db.execute(
            update(Contract)
            .where(
                Contract.id == payment.contract_id,
                Contract.tenant_id == tenant_id,
            )
            .values(paid_amount=total_paid)
        )
        await db.flush()

        logger.info(
            "contract_payment_marked_paid",
            tenant_id=str(tenant_id),
            payment_id=str(payment_id),
            actual_amount=actual_amount,
            contract_paid_total=total_paid,
        )
        return payment

    # -------------------------------------------------------------------------
    # 预警查询
    # -------------------------------------------------------------------------

    async def check_expiring_contracts(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
    ) -> list[Contract]:
        """查询 end_date 在 (today, today+renewal_notice_days] 之间的合同。

        以合同自身配置的 renewal_notice_days 为基准，返回需要关注的合同。
        使用最大值 renewal_notice_days=90 作为查询上界，避免漏查。
        """
        today = _today()
        # 上界：取合理最大值，确保捡出所有即将到期合同，Service 层再精细过滤
        max_notice_days = 90
        cutoff = today + timedelta(days=max_notice_days)

        stmt = (
            select(Contract)
            .where(
                Contract.tenant_id == tenant_id,
                Contract.is_deleted == False,  # noqa: E712
                Contract.status == "active",
                Contract.end_date > today,
                Contract.end_date <= cutoff,
            )
            .order_by(Contract.end_date.asc())
        )
        result = await db.execute(stmt)
        contracts = list(result.scalars().all())

        # 精细过滤：只返回距 end_date <= renewal_notice_days 的合同
        return [c for c in contracts if c.end_date is not None and (c.end_date - today).days <= c.renewal_notice_days]

    async def get_overdue_payments(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
    ) -> list[ContractPayment]:
        """查询逾期未付的付款计划（due_date < today AND status = 'pending'）。"""
        today = _today()
        stmt = (
            select(ContractPayment)
            .where(
                ContractPayment.tenant_id == tenant_id,
                ContractPayment.is_deleted == False,  # noqa: E712
                ContractPayment.status == "pending",
                ContractPayment.due_date < today,
            )
            .order_by(ContractPayment.due_date.asc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def generate_alerts(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
    ) -> list[ContractAlert]:
        """批量生成预警记录（幂等：今天已创建同类型同合同的预警则跳过）。

        预警场景：
        1. expiry — 合同即将到期（end_date 在 renewal_notice_days 内）
        2. payment_due — 付款计划今日到期（due_date = today）
        3. auto_renew — 合同设置了自动续约且30天内到期
        4. overdue — 付款已逾期
        """
        today = _today()
        today_str = today.isoformat()
        new_alerts: list[ContractAlert] = []

        # ── 1. 查已有今日预警（幂等去重基准）────────────────────────────────────
        existing_stmt = select(ContractAlert).where(
            ContractAlert.tenant_id == tenant_id,
            func.date(ContractAlert.created_at) == today,
        )
        existing_result = await db.execute(existing_stmt)
        existing_today = existing_result.scalars().all()
        existing_keys = {(str(a.contract_id), a.alert_type) for a in existing_today}

        # ── 2. 即将到期 & 自动续约预警 ──────────────────────────────────────────
        expiring = await self.check_expiring_contracts(db, tenant_id)
        for contract in expiring:
            days_left = (contract.end_date - today).days if contract.end_date else None
            if days_left is None:
                continue

            # expiry 预警
            key_expiry = (str(contract.id), "expiry")
            if key_expiry not in existing_keys:
                alert = ContractAlert(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    contract_id=contract.id,
                    alert_type="expiry",
                    alert_days_before=days_left,
                    message=(
                        f"合同【{contract.contract_name}】将于 {contract.end_date} 到期，"
                        f"剩余 {days_left} 天，请及时处理续签事宜。"
                    ),
                    is_sent=False,
                )
                db.add(alert)
                new_alerts.append(alert)
                existing_keys.add(key_expiry)

            # auto_renew 预警（30天内到期且设置了自动续约）
            if contract.auto_renew and days_left <= 30:
                key_renew = (str(contract.id), "auto_renew")
                if key_renew not in existing_keys:
                    alert = ContractAlert(
                        id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        contract_id=contract.id,
                        alert_type="auto_renew",
                        alert_days_before=days_left,
                        message=(
                            f"合同【{contract.contract_name}】设置了自动续约，"
                            f"将于 {contract.end_date}（{days_left}天后）自动续签，"
                            f"如需终止请尽快处理。"
                        ),
                        is_sent=False,
                    )
                    db.add(alert)
                    new_alerts.append(alert)
                    existing_keys.add(key_renew)

        # ── 3. 付款到期 & 逾期预警 ──────────────────────────────────────────────
        overdue_payments = await self.get_overdue_payments(db, tenant_id)
        for payment in overdue_payments:
            days_overdue = (today - payment.due_date).days

            key_overdue = (str(payment.contract_id), "overdue")
            if key_overdue not in existing_keys:
                # 获取合同名称
                contract_stmt = select(Contract.contract_name).where(
                    Contract.id == payment.contract_id,
                    Contract.tenant_id == tenant_id,
                )
                contract_res = await db.execute(contract_stmt)
                contract_name = contract_res.scalar_one_or_none() or "未知合同"

                alert = ContractAlert(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    contract_id=payment.contract_id,
                    alert_type="overdue",
                    alert_days_before=0,
                    message=(
                        f"合同【{contract_name}】付款计划【{payment.period_name or payment.due_date}】"
                        f"已逾期 {days_overdue} 天，计划金额 {payment.planned_amount / 100:.2f} 元，"
                        f"请及时安排付款。"
                    ),
                    is_sent=False,
                )
                db.add(alert)
                new_alerts.append(alert)
                existing_keys.add(key_overdue)

        # ── 4. 今日到期付款预警 ────────────────────────────────────────────────
        due_today_stmt = select(ContractPayment).where(
            ContractPayment.tenant_id == tenant_id,
            ContractPayment.is_deleted == False,  # noqa: E712
            ContractPayment.status == "pending",
            ContractPayment.due_date == today,
        )
        due_today_result = await db.execute(due_today_stmt)
        due_today_payments = due_today_result.scalars().all()

        for payment in due_today_payments:
            key_due = (str(payment.contract_id), "payment_due")
            if key_due not in existing_keys:
                contract_stmt = select(Contract.contract_name).where(
                    Contract.id == payment.contract_id,
                    Contract.tenant_id == tenant_id,
                )
                contract_res = await db.execute(contract_stmt)
                contract_name = contract_res.scalar_one_or_none() or "未知合同"

                alert = ContractAlert(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    contract_id=payment.contract_id,
                    alert_type="payment_due",
                    alert_days_before=0,
                    message=(
                        f"合同【{contract_name}】付款计划【{payment.period_name or today}】"
                        f"今日到期，计划金额 {payment.planned_amount / 100:.2f} 元，"
                        f"请确认付款。"
                    ),
                    is_sent=False,
                )
                db.add(alert)
                new_alerts.append(alert)
                existing_keys.add(key_due)

        if new_alerts:
            await db.flush()

        logger.info(
            "contract_alerts_generated",
            tenant_id=str(tenant_id),
            count=len(new_alerts),
            check_date=today_str,
        )
        return new_alerts

    # -------------------------------------------------------------------------
    # 日历与统计
    # -------------------------------------------------------------------------

    async def get_payment_calendar(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        year: int,
        month: int,
    ) -> dict:
        """按日期返回指定月份的付款计划。

        Returns::
            {
                "year": int,
                "month": int,
                "days": {
                    "YYYY-MM-DD": [
                        {"payment_id": str, "contract_id": str,
                         "period_name": str, "planned_amount": int,
                         "status": str}
                    ]
                },
                "total_planned_fen": int,
                "total_paid_fen": int,
            }
        """
        # 计算月份起止日
        _, last_day = monthrange(year, month)
        month_start = date(year, month, 1)
        month_end = date(year, month, last_day)

        stmt = (
            select(ContractPayment)
            .where(
                ContractPayment.tenant_id == tenant_id,
                ContractPayment.is_deleted == False,  # noqa: E712
                ContractPayment.due_date >= month_start,
                ContractPayment.due_date <= month_end,
            )
            .order_by(ContractPayment.due_date.asc())
        )
        result = await db.execute(stmt)
        payments = result.scalars().all()

        days: dict[str, list] = {}
        total_planned = 0
        total_paid = 0

        for p in payments:
            day_key = p.due_date.isoformat()
            if day_key not in days:
                days[day_key] = []
            days[day_key].append(
                {
                    "payment_id": str(p.id),
                    "contract_id": str(p.contract_id),
                    "period_name": p.period_name,
                    "planned_amount": p.planned_amount,
                    "actual_amount": p.actual_amount,
                    "status": p.status,
                }
            )
            total_planned += p.planned_amount
            if p.status == "paid" and p.actual_amount:
                total_paid += p.actual_amount

        return {
            "year": year,
            "month": month,
            "days": days,
            "total_planned_fen": total_planned,
            "total_paid_fen": total_paid,
        }

    async def get_stats(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
    ) -> dict:
        """合同台账统计看板。

        Returns::
            {
                "total_count": int,
                "by_status": {"active": int, "expired": int, ...},
                "by_type": {"rental": int, "service": int, ...},
                "total_amount_fen": int,
                "total_paid_fen": int,
                "expiring_30days": int,   # 30天内到期
                "overdue_payments": int,  # 逾期未付笔数
            }
        """
        base_where = [
            Contract.tenant_id == tenant_id,
            Contract.is_deleted == False,  # noqa: E712
        ]

        # 总数 + 金额汇总
        total_stmt = select(
            func.count().label("total_count"),
            func.coalesce(func.sum(Contract.total_amount), 0).label("total_amount"),
            func.coalesce(func.sum(Contract.paid_amount), 0).label("paid_amount"),
        ).where(*base_where)
        total_result = await db.execute(total_stmt)
        total_row = total_result.mappings().one()

        # 按状态分组
        by_status_stmt = (
            select(Contract.status, func.count().label("count")).where(*base_where).group_by(Contract.status)
        )
        by_status_result = await db.execute(by_status_stmt)
        by_status = {row["status"]: int(row["count"]) for row in by_status_result.mappings().all()}

        # 按类型分组
        by_type_stmt = (
            select(Contract.contract_type, func.count().label("count"))
            .where(*base_where)
            .group_by(Contract.contract_type)
        )
        by_type_result = await db.execute(by_type_stmt)
        by_type = {(row["contract_type"] or "unknown"): int(row["count"]) for row in by_type_result.mappings().all()}

        # 30天内到期
        today = _today()
        cutoff_30 = today + timedelta(days=30)
        expiring_30_stmt = (
            select(func.count())
            .select_from(Contract)
            .where(
                Contract.tenant_id == tenant_id,
                Contract.is_deleted == False,  # noqa: E712
                Contract.status == "active",
                Contract.end_date >= today,
                Contract.end_date <= cutoff_30,
            )
        )
        expiring_30_result = await db.execute(expiring_30_stmt)
        expiring_30 = int(expiring_30_result.scalar_one())

        # 逾期未付笔数
        overdue_stmt = (
            select(func.count())
            .select_from(ContractPayment)
            .where(
                ContractPayment.tenant_id == tenant_id,
                ContractPayment.is_deleted == False,  # noqa: E712
                ContractPayment.status == "pending",
                ContractPayment.due_date < today,
            )
        )
        overdue_result = await db.execute(overdue_stmt)
        overdue_count = int(overdue_result.scalar_one())

        return {
            "total_count": int(total_row["total_count"]),
            "total_amount_fen": int(total_row["total_amount"]),
            "total_paid_fen": int(total_row["paid_amount"]),
            "by_status": by_status,
            "by_type": by_type,
            "expiring_30days": expiring_30,
            "overdue_payments": overdue_count,
        }
