"""外卖异议工作流 — 自动裁决+人工复核

核心逻辑:
1. 接收平台异议(webhook或手动录入)
2. 自动裁决: 金额≤5000分(¥50)自动接受
3. 超过阈值→转人工复核
4. 人工复核: 接受/拒绝/上报
5. 拒绝时生成反驳证据(关联订单/出餐时间/骑手GPS)

状态机: pending → auto_accepted(≤¥50)
        pending → manual_review(>¥50) → accepted/rejected/escalated
"""

import uuid as _uuid
from datetime import datetime
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# 自动接受阈值(分) — 创始人决策点，可按需调整
AUTO_ACCEPT_THRESHOLD_FEN: int = 5000  # ¥50

_VALID_CHANNELS = ("meituan", "eleme", "douyin")
_VALID_DISPUTE_TYPES = (
    "refund", "deduction", "penalty",
    "missing_item", "quality", "late_delivery", "other",
)
_VALID_STATUSES = (
    "pending", "auto_accepted", "manual_review",
    "accepted", "rejected", "escalated",
)
_VALID_REVIEW_ACTIONS = ("accept", "reject", "escalate")


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS 租户上下文。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


class DeliveryDisputeService:
    """外卖异议工作流服务。"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id

    # ──────────────────────────────────────────────
    # 创建异议 + 自动裁决
    # ──────────────────────────────────────────────

    async def create_dispute(
        self,
        store_id: str,
        dispute_data: dict,
    ) -> dict:
        """创建异议 + 自动裁决。

        Args:
            store_id: 门店ID
            dispute_data: 异议数据，包含:
                order_id (str): 订单ID
                channel (str): 渠道 meituan/eleme/douyin
                dispute_type (str): 异议类型
                disputed_amount_fen (int): 争议金额(分)
                platform_dispute_id (str, optional): 平台争议单号
                platform_evidence (dict, optional): 平台证据

        Returns:
            创建后的异议记录(含自动裁决结果)
        """
        # 参数校验
        order_id = dispute_data.get("order_id")
        if not order_id:
            raise ValueError("order_id 不能为空")

        channel = dispute_data.get("channel", "")
        if channel not in _VALID_CHANNELS:
            raise ValueError(f"channel 必须为 {_VALID_CHANNELS} 之一，收到: {channel!r}")

        dispute_type = dispute_data.get("dispute_type", "")
        if dispute_type not in _VALID_DISPUTE_TYPES:
            raise ValueError(f"dispute_type 必须为 {_VALID_DISPUTE_TYPES} 之一，收到: {dispute_type!r}")

        disputed_amount_fen = dispute_data.get("disputed_amount_fen")
        if disputed_amount_fen is None or not isinstance(disputed_amount_fen, int) or disputed_amount_fen < 0:
            raise ValueError("disputed_amount_fen 必须为非负整数(分)")

        platform_dispute_id = dispute_data.get("platform_dispute_id")
        platform_evidence = dispute_data.get("platform_evidence", {})

        # 自动裁决
        auto_accepted, auto_accept_reason = await self._auto_judge(
            disputed_amount_fen=disputed_amount_fen,
            dispute_type=dispute_type,
            channel=channel,
        )

        if auto_accepted:
            status = "auto_accepted"
            resolution_amount_fen = disputed_amount_fen
        else:
            status = "manual_review"
            resolution_amount_fen = None

        dispute_id = str(_uuid.uuid4())
        now = datetime.utcnow()

        await _set_tenant(self.db, self.tenant_id)

        try:
            await self.db.execute(
                text("""
                    INSERT INTO delivery_disputes (
                        id, tenant_id, store_id, order_id,
                        channel, dispute_type, platform_dispute_id,
                        disputed_amount_fen,
                        auto_accepted, auto_accept_reason,
                        status, resolution_amount_fen,
                        platform_evidence,
                        created_at, updated_at
                    ) VALUES (
                        :id, :tenant_id, :store_id, :order_id,
                        :channel, :dispute_type, :platform_dispute_id,
                        :disputed_amount_fen,
                        :auto_accepted, :auto_accept_reason,
                        :status, :resolution_amount_fen,
                        :platform_evidence::JSONB,
                        :now, :now
                    )
                """),
                {
                    "id": _uuid.UUID(dispute_id),
                    "tenant_id": _uuid.UUID(self.tenant_id),
                    "store_id": _uuid.UUID(store_id),
                    "order_id": _uuid.UUID(order_id),
                    "channel": channel,
                    "dispute_type": dispute_type,
                    "platform_dispute_id": platform_dispute_id,
                    "disputed_amount_fen": disputed_amount_fen,
                    "auto_accepted": auto_accepted,
                    "auto_accept_reason": auto_accept_reason,
                    "status": status,
                    "resolution_amount_fen": resolution_amount_fen,
                    "platform_evidence": _json_dumps(platform_evidence),
                    "now": now,
                },
            )
            await self.db.commit()
        except SQLAlchemyError:
            await self.db.rollback()
            log.exception("delivery_dispute.create_failed", store_id=store_id)
            raise

        log.info(
            "delivery_dispute.created",
            dispute_id=dispute_id,
            store_id=store_id,
            channel=channel,
            status=status,
            auto_accepted=auto_accepted,
            disputed_amount_fen=disputed_amount_fen,
        )

        return {
            "id": dispute_id,
            "tenant_id": self.tenant_id,
            "store_id": store_id,
            "order_id": order_id,
            "channel": channel,
            "dispute_type": dispute_type,
            "platform_dispute_id": platform_dispute_id,
            "disputed_amount_fen": disputed_amount_fen,
            "auto_accepted": auto_accepted,
            "auto_accept_reason": auto_accept_reason,
            "status": status,
            "resolution_amount_fen": resolution_amount_fen,
            "platform_evidence": platform_evidence,
            "store_evidence": {},
            "reviewer_id": None,
            "reviewed_at": None,
            "review_note": None,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }

    # ──────────────────────────────────────────────
    # 人工复核
    # ──────────────────────────────────────────────

    async def review_dispute(
        self,
        dispute_id: str,
        action: str,
        reviewer_id: str,
        note: Optional[str] = None,
        resolution_amount_fen: Optional[int] = None,
        store_evidence: Optional[dict] = None,
    ) -> dict:
        """人工复核: accept/reject/escalate。

        Args:
            dispute_id: 异议ID
            action: accept / reject / escalate
            reviewer_id: 复核人ID
            note: 复核备注
            resolution_amount_fen: 最终结算金额(分), accept时必填
            store_evidence: 商户反驳证据(reject时建议提供)

        Returns:
            更新后的异议记录
        """
        if action not in _VALID_REVIEW_ACTIONS:
            raise ValueError(f"action 必须为 {_VALID_REVIEW_ACTIONS} 之一，收到: {action!r}")

        await _set_tenant(self.db, self.tenant_id)

        # 查询当前异议
        dispute = await self._get_dispute_by_id(dispute_id)
        if not dispute:
            raise ValueError(f"异议不存在: {dispute_id}")

        current_status = dispute["status"]
        if current_status not in ("pending", "manual_review"):
            raise ValueError(
                f"异议状态为 {current_status!r}，只有 pending/manual_review 状态可以复核"
            )

        # 确定新状态
        status_map = {
            "accept": "accepted",
            "reject": "rejected",
            "escalate": "escalated",
        }
        new_status = status_map[action]

        # accept 时需要 resolution_amount_fen
        if action == "accept":
            if resolution_amount_fen is None:
                resolution_amount_fen = dispute["disputed_amount_fen"]
        elif action == "reject":
            resolution_amount_fen = 0

        now = datetime.utcnow()

        update_params: dict = {
            "dispute_id": _uuid.UUID(dispute_id),
            "status": new_status,
            "reviewer_id": _uuid.UUID(reviewer_id),
            "reviewed_at": now,
            "review_note": note,
            "resolution_amount_fen": resolution_amount_fen,
            "now": now,
        }

        update_sql = """
            UPDATE delivery_disputes SET
                status = :status,
                reviewer_id = :reviewer_id,
                reviewed_at = :reviewed_at,
                review_note = :review_note,
                resolution_amount_fen = :resolution_amount_fen,
                updated_at = :now
        """

        if store_evidence is not None:
            update_sql += ", store_evidence = :store_evidence::JSONB"
            update_params["store_evidence"] = _json_dumps(store_evidence)

        update_sql += " WHERE id = :dispute_id AND is_deleted = false"

        try:
            await self.db.execute(text(update_sql), update_params)
            await self.db.commit()
        except SQLAlchemyError:
            await self.db.rollback()
            log.exception("delivery_dispute.review_failed", dispute_id=dispute_id)
            raise

        log.info(
            "delivery_dispute.reviewed",
            dispute_id=dispute_id,
            action=action,
            reviewer_id=reviewer_id,
            new_status=new_status,
        )

        # 返回更新后的记录
        return await self._get_dispute_by_id(dispute_id)  # type: ignore[return-value]

    # ──────────────────────────────────────────────
    # 查询异议列表(分页)
    # ──────────────────────────────────────────────

    async def get_disputes(
        self,
        store_id: str,
        status: Optional[str] = None,
        channel: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """查询异议列表(分页)。

        Args:
            store_id: 门店ID
            status: 可选，按状态筛选
            channel: 可选，按渠道筛选
            page: 页码(从1开始)
            size: 每页条数

        Returns:
            {items: [], total: int, page: int, size: int}
        """
        await _set_tenant(self.db, self.tenant_id)

        where = "WHERE tenant_id = :tid AND store_id = :store_id AND is_deleted = false"
        params: dict = {
            "tid": _uuid.UUID(self.tenant_id),
            "store_id": _uuid.UUID(store_id),
        }

        if status:
            if status not in _VALID_STATUSES:
                raise ValueError(f"status 必须为 {_VALID_STATUSES} 之一，收到: {status!r}")
            where += " AND status = :status"
            params["status"] = status

        if channel:
            if channel not in _VALID_CHANNELS:
                raise ValueError(f"channel 必须为 {_VALID_CHANNELS} 之一，收到: {channel!r}")
            where += " AND channel = :channel"
            params["channel"] = channel

        # 总数
        count_result = await self.db.execute(
            text(f"SELECT COUNT(*) FROM delivery_disputes {where}"),
            params,
        )
        total: int = count_result.scalar() or 0

        # 分页查询
        params["limit"] = size
        params["offset"] = (page - 1) * size

        rows_result = await self.db.execute(
            text(f"""
                SELECT id, tenant_id, store_id, order_id,
                       channel, dispute_type, platform_dispute_id,
                       disputed_amount_fen,
                       auto_accepted, auto_accept_reason,
                       status, reviewer_id, reviewed_at, review_note,
                       platform_evidence, store_evidence,
                       resolution_amount_fen,
                       created_at, updated_at
                FROM delivery_disputes
                {where}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )

        items = [_row_to_dict(r) for r in rows_result.fetchall()]

        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        }

    # ──────────────────────────────────────────────
    # 异议详情
    # ──────────────────────────────────────────────

    async def get_dispute_detail(self, dispute_id: str) -> Optional[dict]:
        """获取单条异议详情。"""
        await _set_tenant(self.db, self.tenant_id)
        return await self._get_dispute_by_id(dispute_id)

    # ──────────────────────────────────────────────
    # 异议统计
    # ──────────────────────────────────────────────

    async def get_dispute_stats(
        self,
        store_id: str,
        period_start: str,
        period_end: str,
    ) -> dict:
        """异议统计: 按渠道/类型/状态汇总, 自动接受率, 平均处理时长。

        Args:
            store_id: 门店ID
            period_start: 开始日期(ISO格式)
            period_end: 结束日期(ISO格式)

        Returns:
            统计结果
        """
        await _set_tenant(self.db, self.tenant_id)

        base_where = """
            WHERE tenant_id = :tid
              AND store_id = :store_id
              AND is_deleted = false
              AND created_at >= :period_start::TIMESTAMPTZ
              AND created_at < :period_end::TIMESTAMPTZ
        """
        params: dict = {
            "tid": _uuid.UUID(self.tenant_id),
            "store_id": _uuid.UUID(store_id),
            "period_start": period_start,
            "period_end": period_end,
        }

        # 总览
        overview_result = await self.db.execute(
            text(f"""
                SELECT
                    COUNT(*) AS total_count,
                    COALESCE(SUM(disputed_amount_fen), 0) AS total_disputed_fen,
                    COALESCE(SUM(resolution_amount_fen), 0) AS total_resolution_fen,
                    COUNT(*) FILTER (WHERE auto_accepted = true) AS auto_accepted_count,
                    COUNT(*) FILTER (WHERE status = 'rejected') AS rejected_count,
                    COUNT(*) FILTER (WHERE status = 'escalated') AS escalated_count,
                    AVG(EXTRACT(EPOCH FROM (reviewed_at - created_at)))
                        FILTER (WHERE reviewed_at IS NOT NULL) AS avg_review_seconds
                FROM delivery_disputes
                {base_where}
            """),
            params,
        )
        overview_row = overview_result.fetchone()

        total_count: int = overview_row[0] if overview_row else 0
        auto_accepted_count: int = overview_row[3] if overview_row else 0
        auto_accept_rate: float = (
            round(auto_accepted_count / total_count, 4)
            if total_count > 0
            else 0.0
        )
        avg_review_seconds: Optional[float] = (
            round(float(overview_row[6]), 1)
            if overview_row and overview_row[6] is not None
            else None
        )

        # 按渠道汇总
        channel_result = await self.db.execute(
            text(f"""
                SELECT channel,
                       COUNT(*) AS count,
                       COALESCE(SUM(disputed_amount_fen), 0) AS total_fen
                FROM delivery_disputes
                {base_where}
                GROUP BY channel
                ORDER BY count DESC
            """),
            params,
        )
        by_channel = [
            {"channel": r[0], "count": r[1], "total_disputed_fen": r[2]}
            for r in channel_result.fetchall()
        ]

        # 按类型汇总
        type_result = await self.db.execute(
            text(f"""
                SELECT dispute_type,
                       COUNT(*) AS count,
                       COALESCE(SUM(disputed_amount_fen), 0) AS total_fen
                FROM delivery_disputes
                {base_where}
                GROUP BY dispute_type
                ORDER BY count DESC
            """),
            params,
        )
        by_type = [
            {"dispute_type": r[0], "count": r[1], "total_disputed_fen": r[2]}
            for r in type_result.fetchall()
        ]

        # 按状态汇总
        status_result = await self.db.execute(
            text(f"""
                SELECT status,
                       COUNT(*) AS count
                FROM delivery_disputes
                {base_where}
                GROUP BY status
                ORDER BY count DESC
            """),
            params,
        )
        by_status = [
            {"status": r[0], "count": r[1]}
            for r in status_result.fetchall()
        ]

        return {
            "store_id": store_id,
            "period_start": period_start,
            "period_end": period_end,
            "overview": {
                "total_count": total_count,
                "total_disputed_fen": overview_row[1] if overview_row else 0,
                "total_resolution_fen": overview_row[2] if overview_row else 0,
                "auto_accepted_count": auto_accepted_count,
                "auto_accept_rate": auto_accept_rate,
                "rejected_count": overview_row[4] if overview_row else 0,
                "escalated_count": overview_row[5] if overview_row else 0,
                "avg_review_seconds": avg_review_seconds,
            },
            "by_channel": by_channel,
            "by_type": by_type,
            "by_status": by_status,
        }

    # ──────────────────────────────────────────────
    # 内部方法
    # ──────────────────────────────────────────────

    async def _auto_judge(
        self,
        disputed_amount_fen: int,
        dispute_type: str,
        channel: str,
    ) -> tuple[bool, Optional[str]]:
        """自动裁决逻辑。

        规则:
        - ≤5000分(¥50): 自动接受, reason="金额低于自动接受阈值¥50"
        - missing_item 且金额≤3000分(¥30): 自动接受, reason="缺品异议且金额≤¥30,自动接受"
        - 其他: 转人工

        Returns:
            (auto_accepted, reason) 元组
        """
        if disputed_amount_fen <= AUTO_ACCEPT_THRESHOLD_FEN:
            return True, f"金额{disputed_amount_fen / 100:.2f}元低于自动接受阈值¥{AUTO_ACCEPT_THRESHOLD_FEN / 100:.0f}"

        # missing_item 且金额合理(≤单品均价约¥30)
        if dispute_type == "missing_item" and disputed_amount_fen <= 3000:
            return True, "缺品异议且金额≤¥30,自动接受"

        log.info(
            "delivery_dispute.manual_review_required",
            disputed_amount_fen=disputed_amount_fen,
            dispute_type=dispute_type,
            channel=channel,
        )
        return False, None

    async def _get_dispute_by_id(self, dispute_id: str) -> Optional[dict]:
        """按ID查询单条异议。"""
        result = await self.db.execute(
            text("""
                SELECT id, tenant_id, store_id, order_id,
                       channel, dispute_type, platform_dispute_id,
                       disputed_amount_fen,
                       auto_accepted, auto_accept_reason,
                       status, reviewer_id, reviewed_at, review_note,
                       platform_evidence, store_evidence,
                       resolution_amount_fen,
                       created_at, updated_at
                FROM delivery_disputes
                WHERE id = :dispute_id AND is_deleted = false
            """),
            {"dispute_id": _uuid.UUID(dispute_id)},
        )
        row = result.fetchone()
        if not row:
            return None
        return _row_to_dict(row)


# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────


def _row_to_dict(row: tuple) -> dict:  # type: ignore[type-arg]
    """将查询行转换为字典。"""
    return {
        "id": str(row[0]),
        "tenant_id": str(row[1]),
        "store_id": str(row[2]),
        "order_id": str(row[3]),
        "channel": row[4],
        "dispute_type": row[5],
        "platform_dispute_id": row[6],
        "disputed_amount_fen": row[7],
        "auto_accepted": row[8],
        "auto_accept_reason": row[9],
        "status": row[10],
        "reviewer_id": str(row[11]) if row[11] else None,
        "reviewed_at": row[12].isoformat() if row[12] else None,
        "review_note": row[13],
        "platform_evidence": row[14] if row[14] else {},
        "store_evidence": row[15] if row[15] else {},
        "resolution_amount_fen": row[16],
        "created_at": row[17].isoformat() if row[17] else None,
        "updated_at": row[18].isoformat() if row[18] else None,
    }


def _json_dumps(obj: dict) -> str:
    """安全JSON序列化。"""
    import json

    return json.dumps(obj, ensure_ascii=False, default=str)
