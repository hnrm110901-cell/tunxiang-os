"""应用审核服务 — PostgreSQL 异步实现"""

from uuid import uuid4

import structlog
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import REVIEW_DECISIONS

log = structlog.get_logger(__name__)

# 审核决策 → 应用状态映射
_DECISION_TO_STATUS = {
    "approved": "published",
    "rejected": "rejected",
    "needs_revision": "needs_changes",
}


class ForgeReviewService:
    """应用审核、待审列表、审核历史"""

    # ── 审核应用 ─────────────────────────────────────────────
    async def review_app(
        self,
        db: AsyncSession,
        *,
        app_id: str,
        reviewer_id: str,
        decision: str,
        review_notes: str = "",
    ) -> dict:
        if decision not in REVIEW_DECISIONS:
            raise HTTPException(
                status_code=422,
                detail=f"无效的审核决策: {decision}，可选: {sorted(REVIEW_DECISIONS)}",
            )

        # ── 验证应用存在且处于待审核状态 ──
        app_check = await db.execute(
            text("""
                SELECT app_id, status, current_version
                FROM forge_apps
                WHERE app_id = :aid AND is_deleted = false
            """),
            {"aid": app_id},
        )
        app_row = app_check.mappings().first()
        if not app_row:
            raise HTTPException(status_code=404, detail=f"应用不存在: {app_id}")
        if app_row["status"] != "pending_review":
            raise HTTPException(
                status_code=422,
                detail=f"应用当前状态为 {app_row['status']}，仅 pending_review 可审核",
            )

        review_id = f"rev_{uuid4().hex[:12]}"

        # ── 插入审核记录 ──
        result = await db.execute(
            text("""
                INSERT INTO forge_reviews
                    (id, tenant_id, review_id, app_id, reviewer_id,
                     decision, review_notes, reviewed_at)
                VALUES
                    (gen_random_uuid(), current_setting('app.tenant_id')::uuid,
                     :review_id, :app_id, :reviewer_id,
                     :decision, :review_notes, NOW())
                RETURNING review_id, app_id, reviewer_id, decision,
                          review_notes, reviewed_at
            """),
            {
                "review_id": review_id,
                "app_id": app_id,
                "reviewer_id": reviewer_id,
                "decision": decision,
                "review_notes": review_notes,
            },
        )
        review_row = dict(result.mappings().one())

        # ── 更新应用状态 ──
        new_status = _DECISION_TO_STATUS[decision]
        update_parts = "status = :new_status, updated_at = NOW()"
        if decision == "approved":
            update_parts += ", published_at = NOW()"

        await db.execute(
            text(f"""
                UPDATE forge_apps
                SET {update_parts}
                WHERE app_id = :aid AND is_deleted = false
            """),
            {"new_status": new_status, "aid": app_id},
        )

        # 如果通过审核，同步更新版本状态
        if decision == "approved":
            await db.execute(
                text("""
                    UPDATE forge_app_versions
                    SET status = 'published', published_at = NOW()
                    WHERE app_id = :aid
                      AND version = :ver
                      AND is_deleted = false
                """),
                {"aid": app_id, "ver": app_row["current_version"]},
            )

        log.info(
            "app_reviewed",
            review_id=review_id,
            app_id=app_id,
            decision=decision,
            new_status=new_status,
        )
        return review_row

    # ── 待审核列表 ───────────────────────────────────────────
    async def get_pending_reviews(
        self,
        db: AsyncSession,
        *,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        params: dict = {"limit": size, "offset": (page - 1) * size}

        count_result = await db.execute(
            text("""
                SELECT COUNT(*)
                FROM forge_apps a
                WHERE a.status = 'pending_review' AND a.is_deleted = false
            """),
        )
        total = count_result.scalar_one()

        result = await db.execute(
            text("""
                SELECT
                    a.app_id, a.app_name, a.category, a.description,
                    a.current_version, a.created_at,
                    d.developer_id, d.name AS developer_name, d.company AS developer_company
                FROM forge_apps a
                LEFT JOIN forge_developers d ON d.developer_id = a.developer_id
                    AND d.is_deleted = false
                WHERE a.status = 'pending_review' AND a.is_deleted = false
                ORDER BY a.created_at ASC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [dict(r) for r in result.mappings().all()]
        return {"items": items, "total": total}

    # ── 审核历史 ─────────────────────────────────────────────
    async def get_review_history(self, db: AsyncSession, app_id: str) -> list[dict]:
        result = await db.execute(
            text("""
                SELECT review_id, app_id, reviewer_id, decision,
                       review_notes, reviewed_at
                FROM forge_reviews
                WHERE app_id = :aid AND is_deleted = false
                ORDER BY reviewed_at DESC
            """),
            {"aid": app_id},
        )
        return [dict(r) for r in result.mappings().all()]
