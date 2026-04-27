"""P0 报表种子数据加载器

启动时幂等加载 20 张 P0 报表种子到 report_configs 表。
使用 ON CONFLICT(id) DO NOTHING 保证幂等。
"""

from __future__ import annotations

import json

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_no_rls

from ..seed_p0_reports import P0_REPORTS

logger = structlog.get_logger(__name__)

_INSERT_SQL = text("""
INSERT INTO report_configs
    (id, tenant_id, name, description, category, sql_template,
     default_params, dimensions, metrics, filters, is_system, is_active)
VALUES
    (:id, :tenant_id, :name, :description, :category, :sql_template,
     :default_params::jsonb, :dimensions::jsonb, :metrics::jsonb, :filters::jsonb,
     TRUE, TRUE)
ON CONFLICT (id) DO NOTHING
""")

# 系统级种子使用固定的 "system" 租户 UUID（全零）
_SYSTEM_TENANT_ID = "00000000-0000-0000-0000-000000000000"


async def load_p0_seeds() -> int:
    """加载 P0 报表种子数据到 DB，返回实际插入行数。

    幂等：ON CONFLICT(id) DO NOTHING，重复调用安全。
    使用 get_db_no_rls 跳过 RLS，因为种子写入的 tenant_id 是系统级的。
    """
    inserted = 0
    async for db in get_db_no_rls():
        db: AsyncSession
        for report in P0_REPORTS:
            result = await db.execute(
                _INSERT_SQL,
                {
                    "id": report["id"],
                    "tenant_id": _SYSTEM_TENANT_ID,
                    "name": report["name"],
                    "description": report["description"],
                    "category": report["category"],
                    "sql_template": report["sql_template"],
                    "default_params": json.dumps(report["default_params"], ensure_ascii=False),
                    "dimensions": json.dumps(report["dimensions"], ensure_ascii=False),
                    "metrics": json.dumps(report["metrics"], ensure_ascii=False),
                    "filters": json.dumps(report["filters"], ensure_ascii=False),
                },
            )
            if result.rowcount and result.rowcount > 0:
                inserted += 1

    logger.info("p0_report_seeds_loaded", total=len(P0_REPORTS), inserted=inserted)
    return inserted
