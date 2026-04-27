"""记忆整合 Worker — 每日凌晨执行记忆衰减+整合+清理

调度建议: cron 表达式 "0 3 * * *" (每日凌晨3点)
注册方式: 在 scheduler 中注册 MemoryConsolidationWorker().run
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.memory_evolution_service import MemoryEvolutionService

logger = structlog.get_logger(__name__)


@dataclass
class ConsolidationStats:
    """单次执行的统计结果"""

    tenants_processed: int = 0
    tenants_failed: int = 0
    memories_decayed: int = 0
    memories_consolidated: int = 0
    memories_expired: int = 0
    errors: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tenants_processed": self.tenants_processed,
            "tenants_failed": self.tenants_failed,
            "memories_decayed": self.memories_decayed,
            "memories_consolidated": self.memories_consolidated,
            "memories_expired": self.memories_expired,
            "errors": self.errors,
        }


class MemoryConsolidationWorker:
    """每日记忆维护任务

    1. 记忆衰减: confidence 随时间降低（未访问的记忆逐渐淡化）
    2. 记忆整合: 合并相似记忆（减少冗余，提升检索质量）
    3. 清理过期: 标记 valid_until 已过期的记忆为 is_deleted
    """

    def _get_active_tenant_ids(self) -> list[str]:
        """从环境变量读取活跃租户列表

        环境变量 ACTIVE_TENANT_IDS: 逗号分隔的 tenant_id 列表
        示例: "tid_001,tid_002,tid_003"
        """
        raw = os.environ.get("ACTIVE_TENANT_IDS", "")
        if not raw.strip():
            logger.warning("memory_consolidation.no_active_tenants", hint="设置环境变量 ACTIVE_TENANT_IDS")
            return []
        return [tid.strip() for tid in raw.split(",") if tid.strip()]

    async def _process_tenant(
        self,
        tenant_id: str,
        stats: ConsolidationStats,
    ) -> None:
        """对单个租户执行记忆维护，失败不抛出"""
        log = logger.bind(tenant_id=tenant_id)
        log.info("memory_consolidation.tenant_start")

        db: AsyncSession | None = None
        try:
            async for session in get_db_with_tenant(tenant_id):
                db = session
                break

            if db is None:
                log.error("memory_consolidation.db_session_failed")
                stats.tenants_failed += 1
                stats.errors.append(
                    {
                        "tenant_id": tenant_id,
                        "error": "无法获取数据库会话",
                    }
                )
                return

            svc = MemoryEvolutionService(db)

            # 1. 记忆衰减
            decayed = await svc.decay_memories(tenant_id=tenant_id)
            stats.memories_decayed += decayed
            log.info("memory_consolidation.decay_done", decayed=decayed)

            # 2. 记忆整合
            consolidated = await svc.consolidate_memories(tenant_id=tenant_id)
            stats.memories_consolidated += consolidated
            log.info("memory_consolidation.consolidate_done", consolidated=consolidated)

            # 3. 清理过期
            expired = await svc.cleanup_expired(tenant_id=tenant_id)
            stats.memories_expired += expired
            log.info("memory_consolidation.cleanup_done", expired=expired)

            await db.commit()
            stats.tenants_processed += 1
            log.info("memory_consolidation.tenant_done", decayed=decayed, consolidated=consolidated, expired=expired)

        except Exception as exc:  # 最外层兜底，单租户失败不影响其他
            stats.tenants_failed += 1
            stats.errors.append(
                {
                    "tenant_id": tenant_id,
                    "error": str(exc),
                }
            )
            log.error("memory_consolidation.tenant_failed", error=str(exc), exc_info=True)
            if db is not None:
                await db.rollback()

    async def run(self) -> dict:
        """遍历所有活跃租户，执行记忆维护

        Returns:
            统计字典: tenants_processed, memories_decayed, memories_consolidated 等
        """
        logger.info("memory_consolidation.run_start")
        stats = ConsolidationStats()

        tenant_ids = self._get_active_tenant_ids()
        if not tenant_ids:
            logger.warning("memory_consolidation.skip", reason="无活跃租户")
            return stats.to_dict()

        logger.info("memory_consolidation.tenants_loaded", count=len(tenant_ids))

        for tenant_id in tenant_ids:
            await self._process_tenant(tenant_id, stats)

        logger.info("memory_consolidation.run_done", **stats.to_dict())
        return stats.to_dict()
