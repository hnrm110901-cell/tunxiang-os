"""纠正动作服务 — CRUD + 状态流转（resolve/verify/escalate）

纠正动作由调度引擎自动创建（超时、异常事件等），
门店管理人员通过此服务查看、处理、验证、升级。

状态流转：open → resolved → verified
                → escalated → resolved → verified
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class CorrectiveActionService:
    """纠正动作服务"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ──────────────────────────────────────────────
    # 列表 & 详情
    # ──────────────────────────────────────────────

    async def list_actions(
        self,
        tenant_id: str,
        store_id: str,
        *,
        page: int = 1,
        size: int = 20,
        status: str | None = None,
        severity: str | None = None,
    ) -> dict:
        """分页列出门店纠正动作"""
        tid = UUID(tenant_id)
        sid = UUID(store_id)
        params: dict = {
            "tenant_id": tid,
            "store_id": sid,
            "limit": size,
            "offset": (page - 1) * size,
        }
        filters = ""
        if status is not None:
            filters += " AND ca.status = :status"
            params["status"] = status
        if severity is not None:
            filters += " AND ca.severity = :severity"
            params["severity"] = severity

        # 总数
        count_result = await self.db.execute(
            text(f"""
                SELECT COUNT(*) AS total
                FROM sop_corrective_actions ca
                WHERE ca.tenant_id = :tenant_id
                  AND ca.store_id = :store_id
                  AND ca.is_deleted = FALSE
                  {filters}
            """),
            params,
        )
        total = count_result.scalar() or 0

        # 数据
        result = await self.db.execute(
            text(f"""
                SELECT
                    ca.id,
                    ca.store_id,
                    ca.source_instance_id,
                    ca.action_type,
                    ca.severity,
                    ca.title,
                    ca.description,
                    ca.assignee_id,
                    ca.due_at,
                    ca.status,
                    ca.resolution,
                    ca.resolved_at,
                    ca.verified_by,
                    ca.verified_at,
                    ca.escalated_to,
                    ca.escalated_at,
                    ca.created_at,
                    ca.updated_at
                FROM sop_corrective_actions ca
                WHERE ca.tenant_id = :tenant_id
                  AND ca.store_id = :store_id
                  AND ca.is_deleted = FALSE
                  {filters}
                ORDER BY
                    CASE ca.severity
                        WHEN 'critical' THEN 0
                        WHEN 'warning' THEN 1
                        ELSE 2
                    END,
                    ca.created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = result.fetchall()

        items = [self._row_to_dict(r) for r in rows]
        return {"items": items, "total": total}

    async def get_action(
        self, tenant_id: str, action_id: str,
    ) -> dict | None:
        """获取单个纠正动作详情"""
        tid = UUID(tenant_id)
        aid = UUID(action_id)

        result = await self.db.execute(
            text("""
                SELECT
                    ca.id,
                    ca.store_id,
                    ca.source_instance_id,
                    ca.action_type,
                    ca.severity,
                    ca.title,
                    ca.description,
                    ca.assignee_id,
                    ca.due_at,
                    ca.status,
                    ca.resolution,
                    ca.resolved_at,
                    ca.verified_by,
                    ca.verified_at,
                    ca.escalated_to,
                    ca.escalated_at,
                    ca.created_at,
                    ca.updated_at
                FROM sop_corrective_actions ca
                WHERE ca.id = :action_id
                  AND ca.tenant_id = :tenant_id
                  AND ca.is_deleted = FALSE
            """),
            {"action_id": aid, "tenant_id": tid},
        )
        row = result.fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    # ──────────────────────────────────────────────
    # 状态流转
    # ──────────────────────────────────────────────

    async def resolve(
        self, tenant_id: str, action_id: str, resolution: dict,
    ) -> dict:
        """解决纠正动作（open/escalated → resolved）"""
        tid = UUID(tenant_id)
        aid = UUID(action_id)
        now = datetime.now(timezone.utc)

        # 原子状态转换：WHERE 同时校验旧状态
        result = await self.db.execute(
            text("""
                UPDATE sop_corrective_actions
                SET status = 'resolved',
                    resolution = :resolution,
                    updated_at = :now
                WHERE id = :action_id
                  AND tenant_id = :tenant_id
                  AND status IN ('open', 'escalated')
                  AND is_deleted = FALSE
                RETURNING id
            """),
            {
                "action_id": aid,
                "tenant_id": tid,
                "resolution": resolution,
                "now": now,
            },
        )
        if result.fetchone() is None:
            row = await self._get_action_row(tid, aid)
            if row is None:
                raise ValueError(f"纠正动作不存在: {action_id}")
            raise ValueError(f"状态不允许解决: {row.status}")
        await self.db.flush()

        logger.info(
            "corrective_action.resolve",
            action_id=action_id,
        )

        return {
            "action_id": action_id,
            "status": "resolved",
            "resolved_at": now.isoformat(),
        }

    async def verify(
        self, tenant_id: str, action_id: str, verified_by: str,
    ) -> dict:
        """验证纠正动作（resolved → verified）"""
        tid = UUID(tenant_id)
        aid = UUID(action_id)
        now = datetime.now(timezone.utc)

        # 原子状态转换
        result = await self.db.execute(
            text("""
                UPDATE sop_corrective_actions
                SET status = 'verified',
                    verified_by = :verified_by,
                    verified_at = :now,
                    updated_at = :now
                WHERE id = :action_id
                  AND tenant_id = :tenant_id
                  AND status = 'resolved'
                  AND is_deleted = FALSE
                RETURNING id
            """),
            {
                "action_id": aid,
                "tenant_id": tid,
                "verified_by": UUID(verified_by),
                "now": now,
            },
        )
        if result.fetchone() is None:
            row = await self._get_action_row(tid, aid)
            if row is None:
                raise ValueError(f"纠正动作不存在: {action_id}")
            raise ValueError(f"状态不允许验证: {row.status}")
        await self.db.flush()

        logger.info(
            "corrective_action.verify",
            action_id=action_id,
            verified_by=verified_by,
        )

        return {
            "action_id": action_id,
            "status": "verified",
            "verified_by": verified_by,
            "verified_at": now.isoformat(),
        }

    async def escalate(
        self, tenant_id: str, action_id: str, escalated_to: str,
    ) -> dict:
        """升级纠正动作（open → escalated）"""
        tid = UUID(tenant_id)
        aid = UUID(action_id)
        now = datetime.now(timezone.utc)

        row = await self._get_action_row(tid, aid)
        if row is None:
            raise ValueError(f"纠正动作不存在: {action_id}")
        if row.status != "open":
            raise ValueError(f"状态不允许升级: {row.status}")

        await self.db.execute(
            text("""
                UPDATE sop_corrective_actions
                SET status = 'escalated',
                    escalated_to = :escalated_to,
                    escalated_at = :now,
                    updated_at = :now
                WHERE id = :action_id AND tenant_id = :tenant_id
            """),
            {
                "action_id": aid,
                "tenant_id": tid,
                "escalated_to": UUID(escalated_to),
                "now": now,
            },
        )
        await self.db.flush()

        logger.info(
            "corrective_action.escalate",
            action_id=action_id,
            escalated_to=escalated_to,
        )

        return {
            "action_id": action_id,
            "status": "escalated",
            "escalated_to": escalated_to,
            "escalated_at": now.isoformat(),
        }

    # ──────────────────────────────────────────────
    # 统计概况
    # ──────────────────────────────────────────────

    async def get_summary(
        self, tenant_id: str, store_id: str,
    ) -> dict:
        """纠正动作统计概况"""
        tid = UUID(tenant_id)
        sid = UUID(store_id)

        result = await self.db.execute(
            text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status = 'open') AS open_count,
                    COUNT(*) FILTER (WHERE status = 'resolved') AS resolved_count,
                    COUNT(*) FILTER (WHERE status = 'verified') AS verified_count,
                    COUNT(*) FILTER (WHERE status = 'escalated') AS escalated_count,
                    COUNT(*) FILTER (WHERE severity = 'critical') AS critical_count,
                    COUNT(*) FILTER (WHERE severity = 'warning') AS warning_count,
                    COUNT(*) FILTER (WHERE severity = 'critical' AND status = 'open') AS critical_open,
                    AVG(EXTRACT(EPOCH FROM (resolved_at - created_at)) / 60)
                        FILTER (WHERE resolved_at IS NOT NULL) AS avg_resolve_min
                FROM sop_corrective_actions
                WHERE tenant_id = :tenant_id
                  AND store_id = :store_id
                  AND is_deleted = FALSE
            """),
            {"tenant_id": tid, "store_id": sid},
        )
        row = result.fetchone()

        return {
            "store_id": store_id,
            "total": row.total if row else 0,
            "open": row.open_count if row else 0,
            "resolved": row.resolved_count if row else 0,
            "verified": row.verified_count if row else 0,
            "escalated": row.escalated_count if row else 0,
            "critical_total": row.critical_count if row else 0,
            "critical_open": row.critical_open if row else 0,
            "warning_total": row.warning_count if row else 0,
            "avg_resolve_minutes": round(row.avg_resolve_min, 1) if row and row.avg_resolve_min else None,
        }

    # ──────────────────────────────────────────────
    # 内部辅助
    # ──────────────────────────────────────────────

    async def _get_action_row(self, tid: UUID, aid: UUID):
        """获取纠正动作行"""
        result = await self.db.execute(
            text("""
                SELECT id, status
                FROM sop_corrective_actions
                WHERE id = :action_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
            """),
            {"action_id": aid, "tenant_id": tid},
        )
        return result.fetchone()

    @staticmethod
    def _row_to_dict(r) -> dict:
        """行转字典"""
        return {
            "action_id": str(r.id),
            "store_id": str(r.store_id),
            "source_instance_id": str(r.source_instance_id) if r.source_instance_id else None,
            "action_type": r.action_type,
            "severity": r.severity,
            "title": r.title,
            "description": r.description,
            "assignee_id": str(r.assignee_id) if r.assignee_id else None,
            "due_at": r.due_at.isoformat() if r.due_at else None,
            "status": r.status,
            "resolution": r.resolution,
            "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
            "verified_by": str(r.verified_by) if r.verified_by else None,
            "verified_at": r.verified_at.isoformat() if r.verified_at else None,
            "escalated_to": str(r.escalated_to) if r.escalated_to else None,
            "escalated_at": r.escalated_at.isoformat() if r.escalated_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
