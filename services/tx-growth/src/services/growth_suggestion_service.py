"""Agent策略建议管理 — 管理growth_agent_strategy_suggestions表

从Agent生成建议到人工审核到发布执行的全流程。
发布时联动 growth_journey_service 创建enrollment。

金额单位：分(fen)
"""
import asyncio
import json
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event

GROWTH_EVT_PREFIX = "growth"

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 审核状态机
# ---------------------------------------------------------------------------

_REVIEW_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"pending_review"},
    "pending_review": {"approved", "rejected", "revised"},
    "approved": {"published"},
    "revised": {"published"},
    "rejected": set(),       # 终态
    "published": set(),      # 终态
    "expired": set(),        # 终态
}


# ---------------------------------------------------------------------------
# GrowthSuggestionService
# ---------------------------------------------------------------------------


class GrowthSuggestionService:
    """Agent策略建议管理"""

    VALID_REVIEW_STATES = (
        "draft", "pending_review", "approved", "rejected",
        "revised", "published", "expired",
    )
    VALID_SUGGESTION_TYPES = (
        "repurchase", "reactivation", "repair", "upsell",
        "referral", "retention", "winback",
    )

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    async def _set_tenant(self, db: AsyncSession, tenant_id: str) -> None:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

    def _validate_transition(self, current: str, target: str) -> None:
        allowed = _REVIEW_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise ValueError(
                f"Invalid review_state transition: '{current}' -> '{target}'. "
                f"Allowed from '{current}': {allowed}"
            )

    # ------------------------------------------------------------------
    # 创建建议
    # ------------------------------------------------------------------

    async def create_suggestion(
        self, data: dict, tenant_id: str, db: AsyncSession
    ) -> dict:
        """创建策略建议 (初始 review_state='draft')"""
        await self._set_tenant(db, tenant_id)

        suggestion_id = str(uuid4())
        suggestion_type = data.get("suggestion_type", "repurchase")
        if suggestion_type not in self.VALID_SUGGESTION_TYPES:
            raise ValueError(f"Invalid suggestion_type: {suggestion_type}")

        customer_id = data.get("customer_id")
        template_id = data.get("template_id")
        agent_id = data.get("agent_id")
        confidence_score = data.get("confidence_score", 0.0)
        reasoning = data.get("reasoning")
        suggested_channel = data.get("suggested_channel")
        suggested_timing = data.get("suggested_timing")
        suggested_offer_json = json.dumps(data.get("suggested_offer", {}))
        suggested_message = data.get("suggested_message")
        context_json = json.dumps(data.get("context", {}))

        result = await db.execute(
            text("""
                INSERT INTO growth_agent_strategy_suggestions
                    (id, tenant_id, customer_id, suggestion_type, template_id,
                     agent_id, confidence_score, reasoning,
                     suggested_channel, suggested_timing,
                     suggested_offer_json, suggested_message,
                     context_json, review_state)
                VALUES
                    (:id, :tenant_id, :customer_id, :suggestion_type, :template_id,
                     :agent_id, :confidence_score, :reasoning,
                     :suggested_channel, :suggested_timing,
                     :suggested_offer_json::jsonb, :suggested_message,
                     :context_json::jsonb, 'draft')
                RETURNING id, tenant_id, customer_id, suggestion_type, template_id,
                          agent_id, confidence_score, reasoning,
                          suggested_channel, suggested_timing,
                          suggested_offer_json, suggested_message,
                          review_state, created_at, updated_at
            """),
            {
                "id": suggestion_id,
                "tenant_id": tenant_id,
                "customer_id": str(customer_id) if customer_id else None,
                "suggestion_type": suggestion_type,
                "template_id": str(template_id) if template_id else None,
                "agent_id": agent_id,
                "confidence_score": confidence_score,
                "reasoning": reasoning,
                "suggested_channel": suggested_channel,
                "suggested_timing": suggested_timing,
                "suggested_offer_json": suggested_offer_json,
                "suggested_message": suggested_message,
                "context_json": context_json,
            },
        )
        suggestion = dict(result.fetchone()._mapping)

        logger.info(
            "suggestion_created",
            suggestion_id=suggestion_id,
            suggestion_type=suggestion_type,
            tenant_id=tenant_id,
        )
        return suggestion

    # ------------------------------------------------------------------
    # 提交审核（draft -> pending_review）
    # ------------------------------------------------------------------

    async def submit_for_review(
        self, suggestion_id: UUID, tenant_id: str, db: AsyncSession
    ) -> dict:
        """提交审核: draft -> pending_review"""
        await self._set_tenant(db, tenant_id)

        # 查当前状态
        cur = await db.execute(
            text("""
                SELECT review_state FROM growth_agent_strategy_suggestions
                WHERE tenant_id = :tid AND id = :sid AND is_deleted = false
            """),
            {"tid": tenant_id, "sid": str(suggestion_id)},
        )
        cur_row = cur.fetchone()
        if cur_row is None:
            raise ValueError(f"Suggestion {suggestion_id} not found")

        self._validate_transition(cur_row._mapping["review_state"], "pending_review")

        result = await db.execute(
            text("""
                UPDATE growth_agent_strategy_suggestions
                SET review_state = 'pending_review', updated_at = NOW()
                WHERE tenant_id = :tid AND id = :sid AND is_deleted = false
                RETURNING id, review_state, updated_at
            """),
            {"tid": tenant_id, "sid": str(suggestion_id)},
        )
        updated = dict(result.fetchone()._mapping)
        logger.info("suggestion_submitted_for_review", suggestion_id=str(suggestion_id))
        return updated

    # ------------------------------------------------------------------
    # 分页查询
    # ------------------------------------------------------------------

    async def list_suggestions(
        self,
        review_state: Optional[str],
        suggestion_type: Optional[str],
        customer_id: Optional[UUID],
        tenant_id: str,
        page: int,
        size: int,
        db: AsyncSession,
    ) -> dict:
        """分页+过滤查询建议列表"""
        await self._set_tenant(db, tenant_id)

        where_clauses = ["tenant_id = :tid", "is_deleted = false"]
        params: dict = {"tid": tenant_id}

        if review_state is not None:
            where_clauses.append("review_state = :state")
            params["state"] = review_state
        if suggestion_type is not None:
            where_clauses.append("suggestion_type = :stype")
            params["stype"] = suggestion_type
        if customer_id is not None:
            where_clauses.append("customer_id = :cid")
            params["cid"] = str(customer_id)

        where_sql = " AND ".join(where_clauses)
        offset = (page - 1) * size

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM growth_agent_strategy_suggestions WHERE {where_sql}"),
            params,
        )
        total = count_result.scalar() or 0

        params["lim"] = size
        params["off"] = offset
        rows_result = await db.execute(
            text(f"""
                SELECT id, tenant_id, customer_id, suggestion_type, template_id,
                       agent_id, confidence_score, reasoning,
                       suggested_channel, suggested_timing,
                       suggested_message, review_state,
                       reviewer_id, reviewer_note,
                       published_at, published_enrollment_id,
                       created_at, updated_at
                FROM growth_agent_strategy_suggestions
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT :lim OFFSET :off
            """),
            params,
        )
        items = [dict(r._mapping) for r in rows_result.fetchall()]
        return {"items": items, "total": total}

    # ------------------------------------------------------------------
    # 查询单个建议
    # ------------------------------------------------------------------

    async def get_suggestion(
        self, suggestion_id: UUID, tenant_id: str, db: AsyncSession
    ) -> Optional[dict]:
        """查询单个建议"""
        await self._set_tenant(db, tenant_id)

        result = await db.execute(
            text("""
                SELECT id, tenant_id, customer_id, suggestion_type, template_id,
                       agent_id, confidence_score, reasoning,
                       suggested_channel, suggested_timing,
                       suggested_offer_json, suggested_message,
                       context_json, review_state,
                       reviewer_id, reviewer_note,
                       revised_channel, revised_timing,
                       revised_offer_json, revised_message,
                       published_at, published_enrollment_id,
                       created_at, updated_at
                FROM growth_agent_strategy_suggestions
                WHERE tenant_id = :tid AND id = :sid AND is_deleted = false
            """),
            {"tid": tenant_id, "sid": str(suggestion_id)},
        )
        row = result.fetchone()
        if row is None:
            return None
        return dict(row._mapping)

    # ------------------------------------------------------------------
    # 审核建议
    # ------------------------------------------------------------------

    async def review_suggestion(
        self,
        suggestion_id: UUID,
        result_action: str,
        reviewer_id: UUID,
        note: Optional[str],
        revised_data: Optional[dict],
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """审核建议: pending_review -> approved / rejected / revised"""
        await self._set_tenant(db, tenant_id)

        # 查当前状态
        cur = await db.execute(
            text("""
                SELECT review_state FROM growth_agent_strategy_suggestions
                WHERE tenant_id = :tid AND id = :sid AND is_deleted = false
            """),
            {"tid": tenant_id, "sid": str(suggestion_id)},
        )
        cur_row = cur.fetchone()
        if cur_row is None:
            raise ValueError(f"Suggestion {suggestion_id} not found")

        if result_action == "approved":
            target_state = "approved"
        elif result_action == "rejected":
            target_state = "rejected"
        elif result_action == "revised":
            target_state = "revised"
        else:
            raise ValueError(f"Invalid review result: {result_action}")

        self._validate_transition(cur_row._mapping["review_state"], target_state)

        # 构建UPDATE
        set_parts = [
            "review_state = :target_state",
            "reviewer_id = :reviewer_id",
            "reviewer_note = :note",
            "updated_at = NOW()",
        ]
        params: dict = {
            "tid": tenant_id,
            "sid": str(suggestion_id),
            "target_state": target_state,
            "reviewer_id": str(reviewer_id),
            "note": note,
        }

        if result_action == "revised" and revised_data:
            if "channel" in revised_data:
                set_parts.append("revised_channel = :revised_channel")
                params["revised_channel"] = revised_data["channel"]
            if "timing" in revised_data:
                set_parts.append("revised_timing = :revised_timing")
                params["revised_timing"] = revised_data["timing"]
            if "offer" in revised_data:
                set_parts.append("revised_offer_json = :revised_offer_json::jsonb")
                params["revised_offer_json"] = json.dumps(revised_data["offer"])
            if "message" in revised_data:
                set_parts.append("revised_message = :revised_message")
                params["revised_message"] = revised_data["message"]

        set_sql = ", ".join(set_parts)
        result = await db.execute(
            text(f"""
                UPDATE growth_agent_strategy_suggestions
                SET {set_sql}
                WHERE tenant_id = :tid AND id = :sid AND is_deleted = false
                RETURNING id, review_state, reviewer_id, reviewer_note,
                          revised_channel, revised_timing, revised_message,
                          updated_at
            """),
            params,
        )
        updated = dict(result.fetchone()._mapping)

        asyncio.create_task(
            emit_event(
                event_type=f"{GROWTH_EVT_PREFIX}.suggestion.reviewed",
                tenant_id=tenant_id,
                stream_id=str(suggestion_id),
                payload={
                    "suggestion_id": str(suggestion_id),
                    "review_result": result_action,
                    "reviewer_id": str(reviewer_id),
                },
                source_service="tx-growth",
            )
        )
        logger.info(
            "suggestion_reviewed",
            suggestion_id=str(suggestion_id),
            result=result_action,
            reviewer_id=str(reviewer_id),
            tenant_id=tenant_id,
        )
        return updated

    # ------------------------------------------------------------------
    # 发布建议（创建enrollment）
    # ------------------------------------------------------------------

    async def publish_suggestion(
        self, suggestion_id: UUID, tenant_id: str, db: AsyncSession
    ) -> dict:
        """发布建议: approved/revised -> published，创建enrollment"""
        await self._set_tenant(db, tenant_id)

        # 查完整建议数据
        cur = await db.execute(
            text("""
                SELECT id, review_state, customer_id, template_id, suggestion_type
                FROM growth_agent_strategy_suggestions
                WHERE tenant_id = :tid AND id = :sid AND is_deleted = false
            """),
            {"tid": tenant_id, "sid": str(suggestion_id)},
        )
        cur_row = cur.fetchone()
        if cur_row is None:
            raise ValueError(f"Suggestion {suggestion_id} not found")

        suggestion = cur_row._mapping
        current_state = suggestion["review_state"]

        if current_state not in ("approved", "revised"):
            raise ValueError(
                f"Cannot publish suggestion in state '{current_state}', "
                "must be 'approved' or 'revised'"
            )

        customer_id = suggestion["customer_id"]
        template_id = suggestion["template_id"]

        # 创建enrollment
        enrollment_id: Optional[str] = None
        if customer_id and template_id:
            from services.growth_journey_service import GrowthJourneyService

            journey_svc = GrowthJourneyService()
            try:
                enrollment = await journey_svc.enroll_customer(
                    customer_id=UUID(str(customer_id)),
                    template_id=UUID(str(template_id)),
                    source="agent_suggestion",
                    event_type=f"suggestion.{suggestion['suggestion_type']}",
                    event_id=str(suggestion_id),
                    suggestion_id=suggestion_id,
                    tenant_id=tenant_id,
                    db=db,
                )
                enrollment_id = str(enrollment["id"])
            except ValueError as exc:
                logger.warning(
                    "publish_suggestion_enroll_failed",
                    suggestion_id=str(suggestion_id),
                    error=str(exc),
                )
                # 仍然发布，只是不创建enrollment
                enrollment_id = None

        # 更新建议状态
        result = await db.execute(
            text("""
                UPDATE growth_agent_strategy_suggestions
                SET review_state = 'published',
                    published_at = NOW(),
                    published_enrollment_id = :enrollment_id,
                    updated_at = NOW()
                WHERE tenant_id = :tid AND id = :sid AND is_deleted = false
                RETURNING id, review_state, published_at, published_enrollment_id, updated_at
            """),
            {
                "tid": tenant_id,
                "sid": str(suggestion_id),
                "enrollment_id": enrollment_id,
            },
        )
        updated = dict(result.fetchone()._mapping)

        asyncio.create_task(
            emit_event(
                event_type=f"{GROWTH_EVT_PREFIX}.suggestion.published",
                tenant_id=tenant_id,
                stream_id=str(suggestion_id),
                payload={
                    "suggestion_id": str(suggestion_id),
                    "customer_id": str(customer_id) if customer_id else None,
                    "template_id": str(template_id) if template_id else None,
                    "enrollment_id": enrollment_id,
                },
                source_service="tx-growth",
            )
        )
        logger.info(
            "suggestion_published",
            suggestion_id=str(suggestion_id),
            enrollment_id=enrollment_id,
            tenant_id=tenant_id,
        )
        return updated

    # ------------------------------------------------------------------
    # 过期处理
    # ------------------------------------------------------------------

    async def expire_stale(
        self, hours: int, tenant_id: str, db: AsyncSession
    ) -> dict:
        """超时未审核的建议自动expired"""
        await self._set_tenant(db, tenant_id)

        result = await db.execute(
            text("""
                UPDATE growth_agent_strategy_suggestions
                SET review_state = 'expired', updated_at = NOW()
                WHERE tenant_id = :tid
                  AND review_state IN ('draft', 'pending_review')
                  AND created_at < NOW() - make_interval(hours => :hours)
                  AND is_deleted = false
                RETURNING id
            """),
            {"tid": tenant_id, "hours": hours},
        )
        expired_rows = result.fetchall()
        expired_count = len(expired_rows)

        if expired_count > 0:
            asyncio.create_task(
                emit_event(
                    event_type=f"{GROWTH_EVT_PREFIX}.suggestion.batch_expired",
                    tenant_id=tenant_id,
                    stream_id=tenant_id,
                    payload={
                        "expired_count": expired_count,
                        "threshold_hours": hours,
                    },
                    source_service="tx-growth",
                )
            )

        logger.info(
            "suggestions_expired",
            expired_count=expired_count,
            threshold_hours=hours,
            tenant_id=tenant_id,
        )
        return {"expired_count": expired_count, "threshold_hours": hours}
