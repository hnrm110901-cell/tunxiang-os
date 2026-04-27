"""Sprint E4 — 异议工作流服务 + 状态机 + SLA 追踪

职责：
  1. ingest_dispute — 从平台 webhook / 手动入口创建 dispute
  2. draft_response — 根据 dispute_type 推荐模板 + 渲染
  3. submit_merchant_response — 商家提交响应，状态机迁移
  4. record_platform_ruling — 平台裁决推送，状态 → resolved_*
  5. escalate / withdraw — 边缘状态迁移
  6. sweep_breached_slas — cron 回扫过期 dispute，标 sla_breached=true + expired

状态机（12 态）：

    opened
      └─ auto → pending_merchant (在 ingest_dispute 里做)
          ├─ merchant_accepted (提全额退款)
          ├─ merchant_offered (提部分退款)
          ├─ merchant_disputed (申辩)
          ├─ expired (SLA 超时)
          └─ withdrawn (顾客撤诉)
              └─ all → platform_reviewing
                  ├─ resolved_refund_full
                  ├─ resolved_refund_partial
                  └─ resolved_merchant_win

    任意中间态 → escalated (人工介入)
    任意 → error (异常)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .dispute_response_templates import (
    ResponseTemplate,
    get_template,
    recommend_template,
    render_template,
)

logger = logging.getLogger(__name__)

# 默认 SLA：商家 24h 内必须响应
DEFAULT_MERCHANT_SLA = timedelta(hours=24)

# 允许的转换：当前 status → 目标 status 集合
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "opened": {"pending_merchant", "withdrawn", "escalated", "error"},
    "pending_merchant": {
        "merchant_accepted",
        "merchant_offered",
        "merchant_disputed",
        "expired",
        "withdrawn",
        "escalated",
        "error",
    },
    "merchant_accepted": {
        "platform_reviewing",
        "resolved_refund_full",
        "escalated",
        "error",
    },
    "merchant_offered": {
        "platform_reviewing",
        "resolved_refund_partial",
        "resolved_refund_full",
        "escalated",
        "error",
    },
    "merchant_disputed": {
        "platform_reviewing",
        "resolved_merchant_win",
        "resolved_refund_partial",
        "resolved_refund_full",
        "escalated",
        "error",
    },
    "platform_reviewing": {
        "resolved_refund_full",
        "resolved_refund_partial",
        "resolved_merchant_win",
        "escalated",
        "error",
    },
    "expired": {"resolved_refund_full", "escalated", "error"},
    # 终态
    "resolved_refund_full": set(),
    "resolved_refund_partial": set(),
    "resolved_merchant_win": set(),
    "withdrawn": set(),
    "escalated": {"resolved_refund_full", "resolved_refund_partial",
                   "resolved_merchant_win", "error"},
    "error": {"escalated", "resolved_refund_full"},
}

TERMINAL_STATUSES = frozenset({
    "resolved_refund_full",
    "resolved_refund_partial",
    "resolved_merchant_win",
    "withdrawn",
})


class DisputeError(Exception):
    """状态机 / 业务校验失败"""


# ─────────────────────────────────────────────────────────────
# 数据类
# ─────────────────────────────────────────────────────────────


@dataclass
class DisputeIngestInput:
    platform: str
    platform_dispute_id: str
    platform_order_id: str
    dispute_type: str
    dispute_reason: Optional[str] = None
    customer_claim_amount_fen: Optional[int] = None
    customer_evidence_urls: list[str] = None  # type: ignore[assignment]
    raised_at: Optional[datetime] = None
    canonical_order_id: Optional[str] = None
    store_id: Optional[str] = None
    brand_id: Optional[str] = None
    source: str = "webhook"
    raw_payload: Optional[dict[str, Any]] = None
    merchant_sla: timedelta = DEFAULT_MERCHANT_SLA

    def __post_init__(self) -> None:
        if self.customer_evidence_urls is None:
            self.customer_evidence_urls = []
        if self.raised_at is None:
            self.raised_at = datetime.now(tz=timezone.utc)
        if self.raw_payload is None:
            self.raw_payload = {}


@dataclass
class MerchantResponseInput:
    action: str  # accept_full / offer_partial / dispute
    response_text: str
    offered_refund_fen: Optional[int] = None
    evidence_urls: list[str] = None  # type: ignore[assignment]
    template_id: Optional[str] = None
    responded_by: Optional[str] = None

    def __post_init__(self) -> None:
        if self.evidence_urls is None:
            self.evidence_urls = []
        if self.action not in ("accept_full", "offer_partial", "dispute"):
            raise DisputeError(f"action 非法: {self.action!r}")
        if self.action == "offer_partial" and (
            self.offered_refund_fen is None or self.offered_refund_fen < 0
        ):
            raise DisputeError("offer_partial 必须提供 offered_refund_fen >= 0")
        if not self.response_text.strip():
            raise DisputeError("response_text 不能为空")


@dataclass
class PlatformRulingInput:
    platform_decision: str
    platform_refund_fen: int
    merchant_win: bool = False  # True → resolved_merchant_win
    escalate: bool = False  # True → escalated
    ruled_at: Optional[datetime] = None


@dataclass
class DraftResponseResult:
    """draft_response 返回给前端的数据"""

    template: ResponseTemplate
    rendered_text: str
    suggested_refund_fen: Optional[int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "template": self.template.to_dict(),
            "rendered_text": self.rendered_text,
            "suggested_refund_fen": self.suggested_refund_fen,
        }


# ─────────────────────────────────────────────────────────────
# DisputeService
# ─────────────────────────────────────────────────────────────


class DisputeService:
    """异议工作流核心服务"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self._db = db
        self._tenant_id = tenant_id

    # ── 1. Ingest ──

    async def ingest_dispute(self, inp: DisputeIngestInput) -> dict[str, Any]:
        """幂等创建 dispute 记录，初始 status='pending_merchant'"""
        deadline = (inp.raised_at or datetime.now(tz=timezone.utc)) + inp.merchant_sla

        params = {
            "tenant_id": self._tenant_id,
            "canonical_order_id": inp.canonical_order_id,
            "platform": inp.platform,
            "platform_dispute_id": inp.platform_dispute_id,
            "platform_order_id": inp.platform_order_id,
            "store_id": inp.store_id,
            "brand_id": inp.brand_id,
            "dispute_type": inp.dispute_type,
            "dispute_reason": inp.dispute_reason,
            "customer_claim_amount_fen": inp.customer_claim_amount_fen,
            "customer_evidence_urls": json.dumps(
                inp.customer_evidence_urls, ensure_ascii=False
            ),
            "raised_at": inp.raised_at,
            "merchant_deadline_at": deadline,
            "source": inp.source,
            "raw_payload": json.dumps(inp.raw_payload, ensure_ascii=False),
        }

        row = await self._db.execute(
            text("""
                INSERT INTO delivery_disputes (
                    tenant_id, canonical_order_id, platform, platform_dispute_id,
                    platform_order_id, store_id, brand_id,
                    dispute_type, dispute_reason, customer_claim_amount_fen,
                    customer_evidence_urls,
                    status, raised_at, merchant_deadline_at,
                    source, raw_payload
                ) VALUES (
                    CAST(:tenant_id AS uuid), CAST(:canonical_order_id AS uuid),
                    :platform, :platform_dispute_id, :platform_order_id,
                    CAST(:store_id AS uuid), CAST(:brand_id AS uuid),
                    :dispute_type, :dispute_reason, :customer_claim_amount_fen,
                    CAST(:customer_evidence_urls AS jsonb),
                    'pending_merchant', :raised_at, :merchant_deadline_at,
                    :source, CAST(:raw_payload AS jsonb)
                )
                ON CONFLICT (tenant_id, platform, platform_dispute_id)
                    WHERE is_deleted = false
                DO UPDATE SET
                    raw_payload = EXCLUDED.raw_payload,
                    updated_at = NOW()
                RETURNING id, status, (xmax = 0) AS was_new
            """),
            params,
        )
        rec = row.mappings().first()
        dispute_id = str(rec["id"])
        was_new = bool(rec["was_new"])

        if was_new:
            await self._insert_system_message(
                dispute_id=dispute_id,
                content=(
                    f"异议单已创建。类型：{inp.dispute_type}，"
                    f"商家需在 {deadline.isoformat()} 前响应。"
                ),
            )
        await self._db.commit()

        return {
            "dispute_id": dispute_id,
            "status": rec["status"],
            "was_new": was_new,
            "merchant_deadline_at": deadline.isoformat(),
        }

    # ── 2. Draft Response ──

    async def draft_response(
        self,
        *,
        dispute_id: str,
        template_id: Optional[str] = None,
        extra_variables: Optional[dict[str, Any]] = None,
    ) -> DraftResponseResult:
        """生成商家响应草稿

        - template_id 指定 → 用指定模板
        - 不指定 → 按 dispute_type 自动推荐
        """
        dispute = await self._fetch_dispute(dispute_id)
        if dispute is None:
            raise DisputeError(f"dispute {dispute_id} 不存在")

        template = None
        if template_id:
            template = get_template(template_id)
            if template is None:
                raise DisputeError(f"模板 {template_id} 不存在")
        else:
            template = recommend_template(
                dispute["dispute_type"],
                customer_claim_fen=dispute.get("customer_claim_amount_fen"),
            )
            if template is None:
                raise DisputeError(
                    f"未找到 dispute_type={dispute['dispute_type']} 的推荐模板"
                )

        rendered = render_template(
            template,
            order_no=dispute.get("platform_order_id"),
            store_name=None,  # 前端补充（tenant 的门店名）
            customer_claim_fen=dispute.get("customer_claim_amount_fen"),
            extra=extra_variables,
        )
        suggested = template.suggested_refund_fen(
            dispute.get("customer_claim_amount_fen")
        )

        return DraftResponseResult(
            template=template,
            rendered_text=rendered,
            suggested_refund_fen=suggested,
        )

    # ── 3. Submit Merchant Response ──

    async def submit_merchant_response(
        self, *, dispute_id: str, response: MerchantResponseInput
    ) -> dict[str, Any]:
        """商家响应 → 状态机迁移"""
        dispute = await self._fetch_dispute(dispute_id)
        if dispute is None:
            raise DisputeError(f"dispute {dispute_id} 不存在")

        current_status = dispute["status"]
        target = {
            "accept_full": "merchant_accepted",
            "offer_partial": "merchant_offered",
            "dispute": "merchant_disputed",
        }[response.action]

        self._assert_transition(current_status, target)

        # 更新主表
        await self._db.execute(
            text("""
                UPDATE delivery_disputes SET
                    status = :target,
                    merchant_response_template_id = :template_id,
                    merchant_response = :response_text,
                    merchant_offered_refund_fen = :refund_fen,
                    merchant_evidence_urls = CAST(:evidence AS jsonb),
                    merchant_responded_at = NOW(),
                    responded_by = CAST(:responded_by AS uuid),
                    updated_at = NOW()
                WHERE id = CAST(:id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
            """),
            {
                "id": dispute_id,
                "tenant_id": self._tenant_id,
                "target": target,
                "template_id": response.template_id,
                "response_text": response.response_text,
                "refund_fen": response.offered_refund_fen,
                "evidence": json.dumps(
                    response.evidence_urls, ensure_ascii=False
                ),
                "responded_by": response.responded_by,
            },
        )

        # 加消息
        msg_type = (
            "refund_offer"
            if response.action in ("accept_full", "offer_partial")
            else "text"
        )
        await self._insert_message(
            dispute_id=dispute_id,
            sender_role="merchant",
            sender_id=response.responded_by,
            message_type=msg_type,
            content=response.response_text,
            attachment_urls=response.evidence_urls,
            linked_refund_fen=response.offered_refund_fen,
        )
        await self._db.commit()

        return {
            "dispute_id": dispute_id,
            "previous_status": current_status,
            "status": target,
            "merchant_offered_refund_fen": response.offered_refund_fen,
        }

    # ── 4. Platform Ruling ──

    async def record_platform_ruling(
        self, *, dispute_id: str, ruling: PlatformRulingInput
    ) -> dict[str, Any]:
        """平台裁决（通常由 webhook 触发）"""
        dispute = await self._fetch_dispute(dispute_id)
        if dispute is None:
            raise DisputeError(f"dispute {dispute_id} 不存在")

        current_status = dispute["status"]
        customer_claim = dispute.get("customer_claim_amount_fen") or 0

        # 决定目标状态
        if ruling.escalate:
            target = "escalated"
        elif ruling.merchant_win or ruling.platform_refund_fen == 0:
            target = "resolved_merchant_win"
        elif customer_claim > 0 and ruling.platform_refund_fen >= customer_claim:
            target = "resolved_refund_full"
        else:
            target = "resolved_refund_partial"

        self._assert_transition(current_status, target)

        ruled_at = ruling.ruled_at or datetime.now(tz=timezone.utc)
        is_terminal = target in TERMINAL_STATUSES

        await self._db.execute(
            text("""
                UPDATE delivery_disputes SET
                    status = :target,
                    platform_decision = :decision,
                    platform_refund_fen = :refund,
                    platform_ruled_at = :ruled_at,
                    closed_at = CASE WHEN :is_terminal THEN NOW() ELSE closed_at END,
                    updated_at = NOW()
                WHERE id = CAST(:id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
            """),
            {
                "id": dispute_id,
                "tenant_id": self._tenant_id,
                "target": target,
                "decision": ruling.platform_decision,
                "refund": ruling.platform_refund_fen,
                "ruled_at": ruled_at,
                "is_terminal": is_terminal,
            },
        )

        await self._insert_message(
            dispute_id=dispute_id,
            sender_role="platform",
            message_type="ruling",
            content=ruling.platform_decision,
            linked_refund_fen=ruling.platform_refund_fen,
        )
        await self._db.commit()

        return {
            "dispute_id": dispute_id,
            "previous_status": current_status,
            "status": target,
            "platform_refund_fen": ruling.platform_refund_fen,
            "closed": is_terminal,
        }

    # ── 5. Edge ──

    async def escalate(
        self, *, dispute_id: str, reason: str, escalated_by: Optional[str] = None
    ) -> dict[str, Any]:
        dispute = await self._fetch_dispute(dispute_id)
        if dispute is None:
            raise DisputeError(f"dispute {dispute_id} 不存在")
        self._assert_transition(dispute["status"], "escalated")

        await self._db.execute(
            text("""
                UPDATE delivery_disputes SET
                    status = 'escalated',
                    updated_at = NOW()
                WHERE id = CAST(:id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
            """),
            {"id": dispute_id, "tenant_id": self._tenant_id},
        )
        await self._insert_message(
            dispute_id=dispute_id,
            sender_role="system",
            sender_id=escalated_by,
            content=f"[escalated] {reason}",
        )
        await self._db.commit()
        return {"dispute_id": dispute_id, "status": "escalated"}

    async def withdraw(self, *, dispute_id: str, reason: Optional[str] = None) -> dict[str, Any]:
        dispute = await self._fetch_dispute(dispute_id)
        if dispute is None:
            raise DisputeError(f"dispute {dispute_id} 不存在")
        self._assert_transition(dispute["status"], "withdrawn")

        await self._db.execute(
            text("""
                UPDATE delivery_disputes SET
                    status = 'withdrawn',
                    closed_at = NOW(),
                    updated_at = NOW()
                WHERE id = CAST(:id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
            """),
            {"id": dispute_id, "tenant_id": self._tenant_id},
        )
        if reason:
            await self._insert_message(
                dispute_id=dispute_id,
                sender_role="customer",
                content=f"[withdrawn] {reason}",
            )
        await self._db.commit()
        return {"dispute_id": dispute_id, "status": "withdrawn"}

    # ── 6. SLA Sweep ──

    async def sweep_breached_slas(self, *, now: Optional[datetime] = None) -> int:
        """cron 扫过期未响应的 dispute → status=expired + sla_breached=true

        返回处理行数
        """
        now = now or datetime.now(tz=timezone.utc)
        result = await self._db.execute(
            text("""
                UPDATE delivery_disputes SET
                    status = 'expired',
                    sla_breached = true,
                    closed_at = NOW(),
                    updated_at = NOW()
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND is_deleted = false
                  AND status = 'pending_merchant'
                  AND merchant_deadline_at < :now
                RETURNING id
            """),
            {"tenant_id": self._tenant_id, "now": now},
        )
        affected = [row["id"] for row in result.mappings()]
        for did in affected:
            await self._insert_message(
                dispute_id=str(did),
                sender_role="system",
                content="[sla_breached] 商家 SLA 超时，自动转 expired",
            )
        await self._db.commit()
        return len(affected)

    # ─────────────────────────────────────────────────────────────
    # 内部
    # ─────────────────────────────────────────────────────────────

    async def _fetch_dispute(self, dispute_id: str) -> Optional[dict[str, Any]]:
        row = await self._db.execute(
            text("""
                SELECT id, canonical_order_id, platform, platform_dispute_id,
                       platform_order_id, store_id, brand_id,
                       dispute_type, dispute_reason, customer_claim_amount_fen,
                       status, raised_at, merchant_deadline_at, sla_breached,
                       merchant_response, merchant_offered_refund_fen,
                       platform_refund_fen, closed_at
                FROM delivery_disputes
                WHERE id = CAST(:id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
                  AND is_deleted = false
                LIMIT 1
            """),
            {"id": dispute_id, "tenant_id": self._tenant_id},
        )
        rec = row.mappings().first()
        return dict(rec) if rec else None

    def _assert_transition(self, current: str, target: str) -> None:
        allowed = ALLOWED_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise DisputeError(
                f"状态转换 {current} → {target} 不允许。"
                f"允许的目标：{sorted(allowed) or '(终态)'}"
            )

    async def _insert_message(
        self,
        *,
        dispute_id: str,
        sender_role: str,
        content: Optional[str] = None,
        sender_id: Optional[str] = None,
        message_type: str = "text",
        attachment_urls: Optional[list[str]] = None,
        linked_refund_fen: Optional[int] = None,
        raw_payload: Optional[dict[str, Any]] = None,
    ) -> str:
        row = await self._db.execute(
            text("""
                INSERT INTO delivery_dispute_messages (
                    tenant_id, dispute_id, sender_role, sender_id,
                    message_type, content, attachment_urls,
                    linked_refund_fen, raw_payload
                ) VALUES (
                    CAST(:tenant_id AS uuid), CAST(:dispute_id AS uuid),
                    :sender_role, :sender_id, :message_type, :content,
                    CAST(:attachment_urls AS jsonb),
                    :linked_refund_fen, CAST(:raw_payload AS jsonb)
                )
                RETURNING id
            """),
            {
                "tenant_id": self._tenant_id,
                "dispute_id": dispute_id,
                "sender_role": sender_role,
                "sender_id": sender_id,
                "message_type": message_type,
                "content": content,
                "attachment_urls": json.dumps(
                    attachment_urls or [], ensure_ascii=False
                ),
                "linked_refund_fen": linked_refund_fen,
                "raw_payload": json.dumps(raw_payload or {}, ensure_ascii=False),
            },
        )
        return str(row.scalar_one())

    async def _insert_system_message(
        self, *, dispute_id: str, content: str
    ) -> None:
        await self._insert_message(
            dispute_id=dispute_id,
            sender_role="system",
            content=content,
            message_type="system_note",
        )
