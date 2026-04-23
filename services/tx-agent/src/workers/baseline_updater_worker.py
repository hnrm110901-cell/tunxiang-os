"""每周基线更新 Worker（Phase S3: AI运营教练）

调度建议: cron 表达式 "0 3 * * 1" (每周一凌晨3点)
注册方式: 在 scheduler 中注册 BaselineUpdaterWorker().run

流程:
  1. 遍历活跃租户的所有门店
  2. 基于过去4周数据计算各指标基线
  3. 写入/更新 store_baselines 表
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)


@dataclass
class BaselineStats:
    """单次执行的统计结果"""

    tenants_processed: int = 0
    tenants_failed: int = 0
    stores_updated: int = 0
    baselines_computed: int = 0
    errors: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tenants_processed": self.tenants_processed,
            "tenants_failed": self.tenants_failed,
            "stores_updated": self.stores_updated,
            "baselines_computed": self.baselines_computed,
            "errors": self.errors,
        }


class BaselineUpdaterWorker:
    """每周基线更新任务

    基于过去4周的经营数据，计算各指标的基线值（均值、标准差、趋势）。
    基线用于AI Coach判断当前经营状态是否异常。
    """

    def _get_active_tenant_ids(self) -> list[str]:
        """从环境变量读取活跃租户列表"""
        raw = os.environ.get("ACTIVE_TENANT_IDS", "")
        if not raw.strip():
            logger.warning(
                "baseline_update.no_active_tenants",
                hint="设置环境变量 ACTIVE_TENANT_IDS",
            )
            return []
        return [tid.strip() for tid in raw.split(",") if tid.strip()]

    async def _process_tenant(
        self,
        tenant_id: str,
        stats: BaselineStats,
    ) -> None:
        """对单个租户更新基线，失败不抛出"""
        log = logger.bind(tenant_id=tenant_id)
        log.info("baseline_update.tenant_start")

        db: AsyncSession | None = None
        try:
            async for session in get_db_with_tenant(tenant_id):
                db = session
                break

            if db is None:
                log.error("baseline_update.db_session_failed")
                stats.tenants_failed += 1
                stats.errors.append({
                    "tenant_id": tenant_id,
                    "error": "无法获取数据库会话",
                })
                return

            # TODO: 接入真实基线计算逻辑
            # 1. 查询该租户下所有活跃门店
            # 2. 对每个门店查询过去4周的经营数据
            # 3. 计算基线指标（均值/标准差/趋势）
            # 4. 写入 store_baselines 表

            log.info(
                "baseline_update.tenant_done",
                hint="基线计算逻辑待接入真实数据源",
            )

            await db.commit()
            stats.tenants_processed += 1

        except Exception as exc:  # 最外层兜底，单租户失败不影响其他
            stats.tenants_failed += 1
            stats.errors.append({
                "tenant_id": tenant_id,
                "error": str(exc),
            })
            log.error(
                "baseline_update.tenant_failed",
                error=str(exc),
                exc_info=True,
            )
            if db is not None:
                await db.rollback()

    async def run(self) -> dict:
        """遍历所有活跃租户，更新基线

        Returns:
            统计字典
        """
        logger.info("baseline_update.run_start")
        stats = BaselineStats()

        tenant_ids = self._get_active_tenant_ids()
        if not tenant_ids:
            logger.warning("baseline_update.skip", reason="无活跃租户")
            return stats.to_dict()

        logger.info("baseline_update.tenants_loaded", count=len(tenant_ids))

        for tenant_id in tenant_ids:
            await self._process_tenant(tenant_id, stats)

        logger.info("baseline_update.run_done", **stats.to_dict())
        return stats.to_dict()
