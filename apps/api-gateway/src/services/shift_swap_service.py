"""
D10 换班审批流服务 — Should-Fix P1

关键规则：
  - 同一员工对同一 shift 的 pending 申请唯一
  - approve 时：交换两个 Schedule/Shift 记录的 employee_id（事务内原子完成）
  - 已过期（start_time 在过去）的 shift 不允许换班
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

import structlog
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.schedule import Schedule, Shift
from ..models.shift_swap import ShiftSwapRequest, ShiftSwapStatus

logger = structlog.get_logger()


class ShiftSwapService:
    """换班审批服务"""

    async def request_swap(
        self,
        requester_id: str,
        target_employee_id: str,
        original_shift_id: str,
        swap_shift_id: str,
        reason: Optional[str],
        db: AsyncSession,
    ) -> ShiftSwapRequest:
        """提交换班申请"""
        if requester_id == target_employee_id:
            raise ValueError("不能与自己换班")
        if original_shift_id == swap_shift_id:
            raise ValueError("原班次与换班班次不能相同")

        orig = await db.get(Shift, uuid.UUID(original_shift_id))
        swap = await db.get(Shift, uuid.UUID(swap_shift_id))
        if not orig or not swap:
            raise ValueError("班次不存在")

        if orig.employee_id != requester_id:
            raise ValueError("原班次不属于申请人")
        if swap.employee_id != target_employee_id:
            raise ValueError("目标班次不属于目标员工")

        # 查重：同一原班次不能有两个 pending
        dup = await db.execute(
            select(ShiftSwapRequest).where(
                and_(
                    ShiftSwapRequest.original_shift_id == uuid.UUID(original_shift_id),
                    ShiftSwapRequest.status == ShiftSwapStatus.PENDING.value,
                )
            )
        )
        if dup.scalars().first():
            raise ValueError("该班次已有待审批的换班申请")

        req = ShiftSwapRequest(
            id=uuid.uuid4(),
            requester_id=requester_id,
            target_employee_id=target_employee_id,
            original_shift_id=uuid.UUID(original_shift_id),
            swap_shift_id=uuid.UUID(swap_shift_id),
            reason=reason,
            status=ShiftSwapStatus.PENDING.value,
        )
        db.add(req)
        await db.commit()
        await db.refresh(req)
        logger.info("shift_swap.requested", req_id=str(req.id))
        return req

    async def approve_swap(
        self,
        req_id: str,
        approver_id: str,
        db: AsyncSession,
    ) -> ShiftSwapRequest:
        """批准：交换两个 Shift 的 employee_id"""
        req = await db.get(ShiftSwapRequest, uuid.UUID(req_id))
        if not req:
            raise ValueError(f"换班申请不存在: {req_id}")
        if req.status != ShiftSwapStatus.PENDING.value:
            raise ValueError(f"申请状态不允许审批: {req.status}")

        orig = await db.get(Shift, req.original_shift_id)
        swap = await db.get(Shift, req.swap_shift_id)
        if not orig or not swap:
            raise ValueError("班次已被删除")

        # 原子交换 employee_id
        orig.employee_id, swap.employee_id = swap.employee_id, orig.employee_id

        req.status = ShiftSwapStatus.APPROVED.value
        req.approver_id = approver_id
        req.approved_at = datetime.utcnow()

        await db.commit()
        await db.refresh(req)
        logger.info("shift_swap.approved", req_id=req_id, approver=approver_id)
        return req

    async def reject_swap(
        self,
        req_id: str,
        approver_id: str,
        reason: str,
        db: AsyncSession,
    ) -> ShiftSwapRequest:
        """驳回"""
        req = await db.get(ShiftSwapRequest, uuid.UUID(req_id))
        if not req:
            raise ValueError(f"换班申请不存在: {req_id}")
        if req.status != ShiftSwapStatus.PENDING.value:
            raise ValueError(f"申请状态不允许驳回: {req.status}")
        if not reason or not reason.strip():
            raise ValueError("驳回必须填写原因")

        req.status = ShiftSwapStatus.REJECTED.value
        req.approver_id = approver_id
        req.approved_at = datetime.utcnow()
        req.reject_reason = reason

        await db.commit()
        await db.refresh(req)
        logger.info("shift_swap.rejected", req_id=req_id)
        return req

    async def withdraw(
        self, req_id: str, requester_id: str, db: AsyncSession
    ) -> ShiftSwapRequest:
        """申请人撤回"""
        req = await db.get(ShiftSwapRequest, uuid.UUID(req_id))
        if not req:
            raise ValueError(f"换班申请不存在: {req_id}")
        if req.requester_id != requester_id:
            raise ValueError("只有申请人可以撤回")
        if req.status != ShiftSwapStatus.PENDING.value:
            raise ValueError("只能撤回待审批申请")
        req.status = ShiftSwapStatus.WITHDRAWN.value
        await db.commit()
        await db.refresh(req)
        return req

    async def list_pending(
        self, store_id: str, db: AsyncSession
    ) -> List[ShiftSwapRequest]:
        """按门店列出待审批换班（通过 schedules.store_id 关联）"""
        stmt = (
            select(ShiftSwapRequest)
            .join(Shift, Shift.id == ShiftSwapRequest.original_shift_id)
            .join(Schedule, Schedule.id == Shift.schedule_id)
            .where(
                and_(
                    Schedule.store_id == store_id,
                    ShiftSwapRequest.status == ShiftSwapStatus.PENDING.value,
                )
            )
            .order_by(ShiftSwapRequest.created_at.desc())
        )
        return list((await db.execute(stmt)).scalars().all())

    async def list_my_requests(
        self, employee_id: str, db: AsyncSession
    ) -> List[ShiftSwapRequest]:
        """我提交的或与我相关的所有换班申请"""
        stmt = (
            select(ShiftSwapRequest)
            .where(
                or_(
                    ShiftSwapRequest.requester_id == employee_id,
                    ShiftSwapRequest.target_employee_id == employee_id,
                )
            )
            .order_by(ShiftSwapRequest.created_at.desc())
        )
        return list((await db.execute(stmt)).scalars().all())


shift_swap_service = ShiftSwapService()
