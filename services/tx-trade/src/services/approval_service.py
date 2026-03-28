"""折扣审批服务 — 毛利底线触发时的审批流程

当 cashier_engine.apply_discount() 检测到折扣后毛利低于底线时，
创建审批单由店长在企业微信或系统内审批。

审批流程:
  1. 收银员申请折扣 → 毛利底线告警 → 创建审批单
  2. 企业微信通知店长
  3. 店长批准/拒绝
  4. 批准后自动执行折扣

所有金额单位：分（fen）。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


# ─── 审批状态 ───

APPROVAL_STATUS = ("pending", "approved", "rejected", "expired", "cancelled")


class ApprovalService:
    """折扣审批服务

    使用方式:
        svc = ApprovalService(db, tenant_id)
        result = await svc.create_approval(order_id, discount_info, reason)
        await svc.approve(approval_id, approver_id)
    """

    # 审批超时（分钟）
    APPROVAL_TIMEOUT_MIN = 30

    def __init__(self, db: AsyncSession, tenant_id: str, store_id: str = ""):
        self.db = db
        self.tenant_id = tenant_id
        self.store_id = store_id

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  创建审批
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def create_approval(
        self,
        order_id: str,
        discount_info: dict[str, Any],
        reason: str,
        *,
        requester_id: str = "",
        store_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """创建折扣审批单

        Args:
            order_id: 订单ID
            discount_info: 折扣详情
                {discount_type, discount_value, discount_fen,
                 current_margin, margin_floor, new_final_fen}
            reason: 申请原因
            requester_id: 申请人ID
            store_id: 门店ID

        Returns:
            {approval_id, order_id, status, discount_info, created_at}
        """
        import json

        approval_id = f"APR-{uuid.uuid4().hex[:10].upper()}"
        now = datetime.now(timezone.utc).isoformat()
        effective_store = store_id or self.store_id

        tenant_uuid = uuid.UUID(self.tenant_id)
        store_uuid = uuid.UUID(effective_store) if effective_store else None

        # 写入 notifications 表作为审批记录
        # 用 type='alert' + source='approval_service' 标识审批单
        await self.db.execute(
            text(
                "INSERT INTO notifications "
                "(id, tenant_id, title, message, type, priority, store_id, "
                "extra_data, source, created_at, updated_at, is_deleted) "
                "VALUES (:id, :tid, :title, :msg, 'alert', 'urgent', :sid, "
                ":extra, 'approval_service', NOW(), NOW(), false)"
            ),
            {
                "id": str(uuid.uuid4()),
                "tid": str(tenant_uuid),
                "title": f"[折扣审批] {approval_id}",
                "msg": (
                    f"订单 {order_id} 申请折扣，毛利率 "
                    f"{discount_info.get('current_margin', 'N/A')} "
                    f"低于底线 {discount_info.get('margin_floor', 'N/A')}。"
                    f"原因: {reason}"
                ),
                "sid": str(store_uuid) if store_uuid else None,
                "extra": json.dumps({
                    "approval_id": approval_id,
                    "order_id": order_id,
                    "status": "pending",
                    "discount_info": discount_info,
                    "reason": reason,
                    "requester_id": requester_id,
                    "approver_id": None,
                    "approved_at": None,
                    "rejected_at": None,
                    "reject_reason": None,
                }),
            },
        )

        await self.db.commit()

        # 发送企业微信通知（失败不阻塞）
        await self._notify_wecom_approval(
            approval_id=approval_id,
            order_id=order_id,
            discount_info=discount_info,
            reason=reason,
            store_id=effective_store,
        )

        logger.info(
            "approval_created",
            approval_id=approval_id,
            order_id=order_id,
            discount_type=discount_info.get("discount_type"),
            margin=discount_info.get("current_margin"),
        )

        return {
            "approval_id": approval_id,
            "order_id": order_id,
            "status": "pending",
            "discount_info": discount_info,
            "reason": reason,
            "requester_id": requester_id,
            "created_at": now,
        }

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  批准
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def approve(
        self,
        approval_id: str,
        approver_id: str,
    ) -> dict[str, Any]:
        """批准折扣审批

        批准后自动通过 CashierEngine 执行折扣。

        Args:
            approval_id: 审批ID
            approver_id: 审批人ID

        Returns:
            {approval_id, status, approver_id, approved_at, discount_applied}
        """
        record = await self._get_approval_record(approval_id)
        if not record:
            raise ValueError(f"审批单不存在: {approval_id}")

        extra = record["extra_data"]
        if extra.get("status") != "pending":
            raise ValueError(
                f"审批单 {approval_id} 当前状态为 {extra.get('status')}，无法批准"
            )

        # 检查审批是否已过期
        await self._check_and_expire(record, extra)
        if extra.get("status") == "expired":
            raise ValueError(
                f"审批单 {approval_id} 已超时（{self.APPROVAL_TIMEOUT_MIN}分钟），自动过期"
            )

        now = datetime.now(timezone.utc).isoformat()
        extra["status"] = "approved"
        extra["approver_id"] = approver_id
        extra["approved_at"] = now

        await self._update_approval_record(record["id"], extra, is_read=True)
        await self.db.commit()

        # 执行折扣
        discount_applied = False
        order_id = extra.get("order_id")
        discount_info = extra.get("discount_info", {})

        if order_id and discount_info and discount_info.get("discount_value"):
            try:
                from .cashier_engine import CashierEngine

                engine = CashierEngine(self.db, self.tenant_id)
                result = await engine.apply_discount(
                    order_id=order_id,
                    discount_type=discount_info.get("discount_type", ""),
                    discount_value=discount_info.get("discount_value", 0),
                    reason=f"审批通过: {extra.get('reason', '')}",
                    approval_id=approval_id,
                )
                discount_applied = result.get("applied", False)
            except (ValueError, KeyError, ImportError) as exc:
                logger.error(
                    "approval_discount_exec_failed",
                    approval_id=approval_id,
                    error=str(exc),
                )

        logger.info(
            "approval_approved",
            approval_id=approval_id,
            approver_id=approver_id,
            discount_applied=discount_applied,
        )

        return {
            "approval_id": approval_id,
            "status": "approved",
            "approver_id": approver_id,
            "approved_at": now,
            "discount_applied": discount_applied,
            "order_id": order_id,
        }

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  拒绝
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def reject(
        self,
        approval_id: str,
        approver_id: str,
        reason: str = "",
    ) -> dict[str, Any]:
        """拒绝折扣审批

        Args:
            approval_id: 审批ID
            approver_id: 审批人ID
            reason: 拒绝原因

        Returns:
            {approval_id, status, approver_id, rejected_at, reason}
        """
        record = await self._get_approval_record(approval_id)
        if not record:
            raise ValueError(f"审批单不存在: {approval_id}")

        extra = record["extra_data"]
        if extra.get("status") != "pending":
            raise ValueError(
                f"审批单 {approval_id} 当前状态为 {extra.get('status')}，无法拒绝"
            )

        # 检查审批是否已过期
        await self._check_and_expire(record, extra)
        if extra.get("status") == "expired":
            raise ValueError(
                f"审批单 {approval_id} 已超时（{self.APPROVAL_TIMEOUT_MIN}分钟），自动过期"
            )

        now = datetime.now(timezone.utc).isoformat()
        extra["status"] = "rejected"
        extra["approver_id"] = approver_id
        extra["rejected_at"] = now
        extra["reject_reason"] = reason

        await self._update_approval_record(record["id"], extra, is_read=True)
        await self.db.commit()

        logger.info(
            "approval_rejected",
            approval_id=approval_id,
            approver_id=approver_id,
            reason=reason,
        )

        return {
            "approval_id": approval_id,
            "status": "rejected",
            "approver_id": approver_id,
            "rejected_at": now,
            "reject_reason": reason,
            "order_id": extra.get("order_id"),
        }

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  查询
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def get_approval(self, approval_id: str) -> Optional[dict[str, Any]]:
        """获取单个审批详情"""
        record = await self._get_approval_record(approval_id)
        if not record:
            return None
        return self._format_approval(record)

    async def list_approvals(
        self,
        *,
        status: Optional[str] = None,
        store_id: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict[str, Any]:
        """查询审批列表

        Args:
            status: 按状态筛选 pending/approved/rejected
            store_id: 按门店筛选
            page: 页码
            size: 每页条数

        Returns:
            {items: [...], total, page, size}
        """
        import json as json_lib

        tenant_uuid = uuid.UUID(self.tenant_id)

        conditions = [
            "tenant_id = :tid",
            "source = 'approval_service'",
        ]
        bind_params: dict[str, Any] = {"tid": str(tenant_uuid)}

        if status:
            conditions.append("extra_data->>'status' = :st")
            bind_params["st"] = status
        if store_id:
            conditions.append("store_id = :sid")
            bind_params["sid"] = store_id

        where_clause = " AND ".join(conditions)

        # Count
        count_result = await self.db.execute(
            text(f"SELECT COUNT(*) FROM notifications WHERE {where_clause}"),
            bind_params,
        )
        total = count_result.scalar() or 0

        # Query
        offset = (page - 1) * size
        bind_params["lim"] = size
        bind_params["off"] = offset
        result = await self.db.execute(
            text(
                f"SELECT id, title, message, store_id, extra_data, created_at "
                f"FROM notifications WHERE {where_clause} "
                f"ORDER BY created_at DESC LIMIT :lim OFFSET :off"
            ),
            bind_params,
        )
        rows = result.fetchall()

        items = []
        for row in rows:
            extra = row[4] if isinstance(row[4], dict) else json_lib.loads(row[4] or "{}")
            items.append({
                "id": str(row[0]),
                "approval_id": extra.get("approval_id"),
                "order_id": extra.get("order_id"),
                "status": extra.get("status"),
                "discount_info": extra.get("discount_info"),
                "reason": extra.get("reason"),
                "requester_id": extra.get("requester_id"),
                "approver_id": extra.get("approver_id"),
                "store_id": str(row[3]) if row[3] else None,
                "created_at": row[5].isoformat() if row[5] else None,
            })

        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        }

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  内部方法
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def _check_and_expire(
        self, record: dict[str, Any], extra: dict[str, Any]
    ) -> None:
        """检查审批单是否已超时，超时则自动标记为 expired"""
        from datetime import timedelta

        created_at = record.get("created_at")
        if not created_at:
            return

        # created_at 可能是 datetime 对象或字符串
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)

        # 确保有时区信息
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        deadline = created_at + timedelta(minutes=self.APPROVAL_TIMEOUT_MIN)
        if datetime.now(timezone.utc) > deadline:
            extra["status"] = "expired"
            await self._update_approval_record(record["id"], extra)
            logger.info(
                "approval_auto_expired",
                approval_id=extra.get("approval_id"),
                created_at=created_at.isoformat(),
            )

    async def _get_approval_record(
        self, approval_id: str
    ) -> Optional[dict[str, Any]]:
        """根据 approval_id 从 notifications 表查找审批记录"""
        import json as json_lib

        tenant_uuid = uuid.UUID(self.tenant_id)

        result = await self.db.execute(
            text(
                "SELECT id, title, message, store_id, extra_data, created_at "
                "FROM notifications "
                "WHERE tenant_id = :tid "
                "AND source = 'approval_service' "
                "AND extra_data->>'approval_id' = :aid "
                "LIMIT 1"
            ),
            {"tid": str(tenant_uuid), "aid": approval_id},
        )
        row = result.fetchone()
        if not row:
            return None

        extra = row[4] if isinstance(row[4], dict) else json_lib.loads(row[4] or "{}")

        return {
            "id": str(row[0]),
            "title": row[1],
            "message": row[2],
            "store_id": str(row[3]) if row[3] else None,
            "extra_data": extra,
            "created_at": row[5],
        }

    async def _update_approval_record(
        self,
        record_id: str,
        extra_data: dict[str, Any],
        *,
        is_read: bool = False,
    ) -> None:
        """更新审批记录的 extra_data"""
        import json as json_lib

        params: dict[str, Any] = {
            "rid": record_id,
            "extra": json_lib.dumps(extra_data),
        }

        set_clauses = ["extra_data = :extra::jsonb", "updated_at = NOW()"]
        if is_read:
            set_clauses.append("is_read = true")
            set_clauses.append("read_at = NOW()")

        await self.db.execute(
            text(
                f"UPDATE notifications SET {', '.join(set_clauses)} "
                f"WHERE id = :rid::uuid"
            ),
            params,
        )

    async def _notify_wecom_approval(
        self,
        *,
        approval_id: str,
        order_id: str,
        discount_info: dict[str, Any],
        reason: str,
        store_id: str,
    ) -> None:
        """通过企业微信通知店长审批"""
        import os

        webhook_url = os.getenv("WECOM_APPROVAL_WEBHOOK", "")
        if not webhook_url:
            logger.info(
                "wecom_approval_skip_no_webhook",
                approval_id=approval_id,
            )
            return

        margin_pct = discount_info.get("current_margin")
        floor_pct = discount_info.get("margin_floor")
        discount_fen = discount_info.get("discount_fen", 0)

        margin_str = f"{margin_pct:.1%}" if isinstance(margin_pct, (int, float)) else str(margin_pct)
        floor_str = f"{floor_pct:.1%}" if isinstance(floor_pct, (int, float)) else str(floor_pct)

        content = (
            f"**折扣审批申请**\n"
            f"> 审批编号: {approval_id}\n"
            f"> 订单ID: {order_id}\n"
            f"> 折扣金额: {discount_fen / 100:.2f}元\n"
            f"> 折后毛利: {margin_str}\n"
            f"> 毛利底线: {floor_str}\n"
            f"> 申请原因: {reason}\n\n"
            f"请尽快在系统内审批。"
        )

        try:
            from services.tx_ops.src.services.notification_service import NotificationService
            notif_svc = NotificationService(self.db, self.tenant_id)
            await notif_svc.send_wecom(
                webhook_url=webhook_url,
                content=content,
                msg_type="markdown",
                store_id=store_id,
            )
        except (ImportError, ConnectionError, TimeoutError, ValueError) as exc:
            # 通知失败不阻塞审批流程
            logger.warning(
                "wecom_approval_notify_failed",
                approval_id=approval_id,
                error=str(exc),
            )

    def _format_approval(self, record: dict[str, Any]) -> dict[str, Any]:
        """格式化审批记录输出"""
        extra = record.get("extra_data", {})
        return {
            "approval_id": extra.get("approval_id"),
            "order_id": extra.get("order_id"),
            "status": extra.get("status"),
            "discount_info": extra.get("discount_info"),
            "reason": extra.get("reason"),
            "requester_id": extra.get("requester_id"),
            "approver_id": extra.get("approver_id"),
            "approved_at": extra.get("approved_at"),
            "rejected_at": extra.get("rejected_at"),
            "reject_reason": extra.get("reject_reason"),
            "store_id": record.get("store_id"),
            "created_at": record["created_at"].isoformat()
            if record.get("created_at") else None,
        }
