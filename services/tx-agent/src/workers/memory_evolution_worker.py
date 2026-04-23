"""每日记忆进化 Worker（Phase S4: 记忆进化闭环）

调度建议: cron 表达式 "0 2 * * *" (每日凌晨2点)
注册方式: 在 scheduler 中注册 MemoryEvolutionWorker().run

流程:
  1. 遍历活跃租户
  2. 对每个租户执行信号分析 + 偏好推断
  3. 将推断结果写入记忆系统
  4. 强化/弱化已有记忆
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.feedback_evolution_service import FeedbackEvolutionService

logger = structlog.get_logger(__name__)


@dataclass
class EvolutionStats:
    """单次执行的统计结果"""

    tenants_processed: int = 0
    tenants_failed: int = 0
    users_analyzed: int = 0
    memories_created: int = 0
    memories_updated: int = 0
    errors: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tenants_processed": self.tenants_processed,
            "tenants_failed": self.tenants_failed,
            "users_analyzed": self.users_analyzed,
            "memories_created": self.memories_created,
            "memories_updated": self.memories_updated,
            "errors": self.errors,
        }


class MemoryEvolutionWorker:
    """每日记忆进化任务

    1. 分析所有用户信号
    2. 推断新偏好 -> 写入记忆
    3. 强化/弱化已有记忆
    """

    def _get_active_tenant_ids(self) -> list[str]:
        """从环境变量读取活跃租户列表

        环境变量 ACTIVE_TENANT_IDS: 逗号分隔的 tenant_id 列表
        示例: "tid_001,tid_002,tid_003"
        """
        raw = os.environ.get("ACTIVE_TENANT_IDS", "")
        if not raw.strip():
            logger.warning(
                "memory_evolution.no_active_tenants",
                hint="设置环境变量 ACTIVE_TENANT_IDS",
            )
            return []
        return [tid.strip() for tid in raw.split(",") if tid.strip()]

    async def _process_tenant(
        self,
        tenant_id: str,
        stats: EvolutionStats,
    ) -> None:
        """对单个租户执行记忆进化，失败不抛出"""
        log = logger.bind(tenant_id=tenant_id)
        log.info("memory_evolution.tenant_start")

        db: AsyncSession | None = None
        try:
            async for session in get_db_with_tenant(tenant_id):
                db = session
                break

            if db is None:
                log.error("memory_evolution.db_session_failed")
                stats.tenants_failed += 1
                stats.errors.append({
                    "tenant_id": tenant_id,
                    "error": "无法获取数据库会话",
                })
                return

            svc = FeedbackEvolutionService(db)

            # 执行记忆进化
            result = await svc.evolve_memories(tenant_id=tenant_id)

            stats.users_analyzed += result.get("users_analyzed", 0)
            stats.memories_created += result.get("memories_created", 0)
            stats.memories_updated += result.get("memories_updated", 0)

            await db.commit()
            stats.tenants_processed += 1

            log.info(
                "memory_evolution.tenant_done",
                users_analyzed=result.get("users_analyzed", 0),
                memories_created=result.get("memories_created", 0),
                memories_updated=result.get("memories_updated", 0),
            )

        except Exception as exc:  # 最外层兜底，单租户失败不影响其他
            stats.tenants_failed += 1
            stats.errors.append({
                "tenant_id": tenant_id,
                "error": str(exc),
            })
            log.error(
                "memory_evolution.tenant_failed",
                error=str(exc),
                exc_info=True,
            )
            if db is not None:
                await db.rollback()

    async def run(self) -> dict:
        """遍历所有活跃租户，执行记忆进化

        Returns:
            统计字典: tenants_processed, users_analyzed, memories_created 等
        """
        logger.info("memory_evolution.run_start")
        stats = EvolutionStats()

        tenant_ids = self._get_active_tenant_ids()
        if not tenant_ids:
            logger.warning("memory_evolution.skip", reason="无活跃租户")
            return stats.to_dict()

        logger.info("memory_evolution.tenants_loaded", count=len(tenant_ids))

        for tenant_id in tenant_ids:
            await self._process_tenant(tenant_id, stats)

        logger.info("memory_evolution.run_done", **stats.to_dict())
        return stats.to_dict()
