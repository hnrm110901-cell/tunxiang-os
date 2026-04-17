"""
D8 采购单审批流服务 — Should-Fix P1

关键业务规则：
  - 审批级别按金额分档：
      <1 万（<1,000,000 分）：店长
      1-5 万（1,000,000 ~ 5,000,000 分）：区域经理
      >5 万（>5,000,000 分）：老板
  - 状态机：draft → pending_approval → approved/rejected
  - 每次操作写入 PurchaseApprovalLog
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.purchase_approval import ApprovalAction, ApprovalLevel, PurchaseApprovalLog
from ..models.supply_chain import PurchaseOrder

logger = structlog.get_logger()


# 金额分档阈值（分）
LEVEL_THRESHOLD_REGIONAL_FEN = 1_000_000   # 1 万
LEVEL_THRESHOLD_BOSS_FEN = 5_000_000       # 5 万


class PurchaseApprovalService:
    """采购单审批流服务"""

    def _required_level(self, amount_fen: int) -> ApprovalLevel:
        """根据金额判定所需审批级别"""
        if amount_fen < LEVEL_THRESHOLD_REGIONAL_FEN:
            return ApprovalLevel.STORE_MANAGER
        if amount_fen < LEVEL_THRESHOLD_BOSS_FEN:
            return ApprovalLevel.REGIONAL_MANAGER
        return ApprovalLevel.BOSS

    async def submit_for_approval(
        self,
        po_id: str,
        requester: str,
        db: AsyncSession,
    ) -> PurchaseOrder:
        """提交采购单进入审批流：draft → pending_approval"""
        po = await db.get(PurchaseOrder, po_id)
        if not po:
            raise ValueError(f"采购单不存在: {po_id}")
        if po.status not in ("pending", "draft"):
            raise ValueError(f"采购单状态不允许提交审批: {po.status}")

        po.status = "pending_approval"
        po.updated_at = datetime.utcnow()

        level = self._required_level(po.total_amount or 0)
        log = PurchaseApprovalLog(
            po_id=po_id,
            level=level.value,
            action=ApprovalAction.SUBMIT.value,
            approver_id=requester,
            amount_snapshot_fen=po.total_amount or 0,
            reason=None,
        )
        db.add(log)
        await db.commit()
        await db.refresh(po)
        logger.info("purchase_approval.submitted", po_id=po_id, level=level.value)
        return po

    async def approve(
        self,
        po_id: str,
        approver: str,
        level: ApprovalLevel,
        db: AsyncSession,
    ) -> PurchaseOrder:
        """审批通过"""
        po = await db.get(PurchaseOrder, po_id)
        if not po:
            raise ValueError(f"采购单不存在: {po_id}")
        if po.status != "pending_approval":
            raise ValueError(f"采购单状态不允许审批: {po.status}")

        required = self._required_level(po.total_amount or 0)
        if level != required:
            raise ValueError(
                f"审批级别不匹配：需要 {required.value}，当前 {level.value}"
            )

        po.status = "approved"
        po.approved_by = approver
        po.approved_at = datetime.utcnow()
        po.updated_at = datetime.utcnow()

        log = PurchaseApprovalLog(
            po_id=po_id,
            level=level.value,
            action=ApprovalAction.APPROVE.value,
            approver_id=approver,
            amount_snapshot_fen=po.total_amount or 0,
        )
        db.add(log)
        await db.commit()
        await db.refresh(po)
        logger.info("purchase_approval.approved", po_id=po_id, approver=approver)
        return po

    async def reject(
        self,
        po_id: str,
        approver: str,
        reason: str,
        db: AsyncSession,
    ) -> PurchaseOrder:
        """审批驳回"""
        po = await db.get(PurchaseOrder, po_id)
        if not po:
            raise ValueError(f"采购单不存在: {po_id}")
        if po.status != "pending_approval":
            raise ValueError(f"采购单状态不允许驳回: {po.status}")
        if not reason or not reason.strip():
            raise ValueError("驳回必须填写原因")

        po.status = "rejected"
        po.updated_at = datetime.utcnow()

        log = PurchaseApprovalLog(
            po_id=po_id,
            level=self._required_level(po.total_amount or 0).value,
            action=ApprovalAction.REJECT.value,
            approver_id=approver,
            amount_snapshot_fen=po.total_amount or 0,
            reason=reason,
        )
        db.add(log)
        await db.commit()
        await db.refresh(po)
        logger.info("purchase_approval.rejected", po_id=po_id, reason=reason)
        return po

    async def get_approval_history(
        self,
        po_id: str,
        db: AsyncSession,
    ) -> List[PurchaseApprovalLog]:
        """查询某采购单的审批历史"""
        stmt = (
            select(PurchaseApprovalLog)
            .where(PurchaseApprovalLog.po_id == po_id)
            .order_by(PurchaseApprovalLog.created_at.asc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())


purchase_approval_service = PurchaseApprovalService()
