"""AI引用监测Worker — 定期检测品牌在AI搜索引擎中的引用情况

调度频率：每周（由tx-intel/main.py APScheduler触发）
核心流程：
  1. 遍历所有活跃租户
  2. 为每个租户展开预定义查询模板（城市×菜系×品牌名）
  3. 对每个查询在所有AI平台上执行引用检测
  4. 结果写入ai_citation_monitors表

查询模板：
  - "{city}最好的{cuisine}餐厅"
  - "{brand_name}怎么样"
  - "{city}{cuisine}推荐"
"""

from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# 预定义查询模板
_QUERY_TEMPLATES = [
    "{city}最好的{cuisine}餐厅",
    "{brand_name}怎么样",
    "{city}{cuisine}推荐",
]

# 目标AI平台
_AI_PLATFORMS = ["chatgpt", "perplexity", "google_ai", "baidu_ai", "xiaohongshu"]


class CitationMonitorWorker:
    """AI引用监测定时Worker

    每周执行一次，遍历所有租户，在AI搜索引擎中检测品牌引用。
    """

    async def tick(self, db: AsyncSession) -> dict[str, Any]:
        """单次tick：遍历租户，执行引用检测

        Returns: {tenants_checked: int, total_queries: int, mentions_found: int, errors: int}
        """
        from ..services.geo_seo_service import GeoSEOService

        svc = GeoSEOService()
        stats: dict[str, Any] = {
            "tenants_checked": 0,
            "total_queries": 0,
            "mentions_found": 0,
            "errors": 0,
        }

        # 查找所有有GEO档案的活跃租户
        tenant_rows = await db.execute(
            text("""
                SELECT DISTINCT tenant_id
                FROM geo_brand_profiles
                WHERE is_deleted = FALSE
                LIMIT 100
            """),
        )
        tenant_ids = [str(r[0]) for r in tenant_rows.all()]

        for tid_str in tenant_ids:
            try:
                # 设置RLS上下文
                await db.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": tid_str},
                )

                # 获取租户的品牌信息
                profile_row = await db.execute(
                    text("""
                        SELECT store_name, cuisine_type, address
                        FROM geo_brand_profiles
                        WHERE tenant_id = :tid
                          AND is_deleted = FALSE
                        LIMIT 1
                    """),
                    {"tid": tid_str},
                )
                profile = profile_row.mappings().first()
                if not profile:
                    continue

                brand_name = profile["store_name"] or "餐厅"
                cuisine = profile["cuisine_type"] or "美食"
                city = "长沙"  # 默认城市，真实实现从address解析

                # 展开查询模板
                import uuid

                tenant_uuid = uuid.UUID(tid_str)
                for tpl in _QUERY_TEMPLATES:
                    query = tpl.format(
                        city=city,
                        cuisine=cuisine,
                        brand_name=brand_name,
                    )
                    for platform in _AI_PLATFORMS:
                        try:
                            result = await svc.check_ai_citation(
                                tenant_id=tenant_uuid,
                                query=query,
                                platform=platform,
                                db=db,
                            )
                            stats["total_queries"] += 1
                            if result.get("mention_found"):
                                stats["mentions_found"] += 1
                        except (ValueError, KeyError) as exc:
                            log.warning(
                                "citation_worker.query_failed",
                                tenant_id=tid_str,
                                query=query,
                                platform=platform,
                                error=str(exc),
                            )
                            stats["errors"] += 1

                stats["tenants_checked"] += 1
                log.info(
                    "citation_worker.tenant_done",
                    tenant_id=tid_str,
                    brand=brand_name,
                )

            except (ValueError, KeyError) as exc:
                log.error(
                    "citation_worker.tenant_error",
                    tenant_id=tid_str,
                    error=str(exc),
                )
                stats["errors"] += 1

        log.info("citation_worker.tick_complete", **stats)
        return stats
