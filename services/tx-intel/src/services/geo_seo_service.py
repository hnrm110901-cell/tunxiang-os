"""GEO搜索优化服务 — 品牌结构化数据 + AI引用监测

负责：
  - 生成Schema.org Restaurant JSON-LD结构化数据
  - AI搜索引擎品牌引用检测（ChatGPT/Perplexity/Google AI/百度AI/小红书）
  - 批量引用检测（预定义查询模板 × 平台矩阵）
  - GEO SEO仪表盘聚合（档案数、引用率、平均SEO分）
  - 内容优化建议（基于SEO评分缺失项）
  - SEO评分计算（0-100，基于档案完整度）
"""

import json
import uuid
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# AI平台列表
_AI_PLATFORMS = ["chatgpt", "perplexity", "google_ai", "baidu_ai", "xiaohongshu"]

# 预定义查询模板
_QUERY_TEMPLATES = [
    "{city}最好的{cuisine}餐厅",
    "{brand_name}怎么样",
    "{city}{cuisine}推荐",
]


class GeoSEOService:
    """GEO搜索优化服务

    管理门店在各平台的结构化品牌档案，追踪AI搜索引擎
    对品牌的引用情况，提供SEO优化建议。
    """

    # ─── 结构化数据生成 ─────────────────────────────────

    async def generate_structured_data(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """为门店生成Schema.org Restaurant JSON-LD结构化数据

        从stores表读取门店信息，构建JSON-LD，写入/更新geo_brand_profiles。
        为每个支持的平台创建一条记录。

        Returns: {"store_id": str, "platforms_updated": int, "seo_score": int}
        """
        log = logger.bind(
            tenant_id=str(tenant_id),
            store_id=str(store_id),
        )

        # 读取门店基本信息
        store_row = await db.execute(
            text("""
                SELECT id, name, address, phone, latitude, longitude
                FROM stores
                WHERE id = :store_id
                  AND tenant_id = :tid
                  AND is_deleted = FALSE
                LIMIT 1
            """),
            {"store_id": str(store_id), "tid": str(tenant_id)},
        )
        store = store_row.mappings().first()
        if not store:
            log.warning("geo_seo.store_not_found")
            return {"store_id": str(store_id), "platforms_updated": 0, "seo_score": 0}

        # 读取菜品亮点（销量前5）
        menu_row = await db.execute(
            text("""
                SELECT name, price_fen
                FROM dishes
                WHERE store_id = :store_id
                  AND tenant_id = :tid
                  AND is_deleted = FALSE
                ORDER BY created_at DESC
                LIMIT 5
            """),
            {"store_id": str(store_id), "tid": str(tenant_id)},
        )
        menu_highlights = [{"name": r["name"], "price_fen": r["price_fen"]} for r in menu_row.mappings().all()]

        # 构建Schema.org Restaurant JSON-LD
        json_ld: dict[str, Any] = {
            "@context": "https://schema.org",
            "@type": "Restaurant",
            "name": store["name"],
            "address": {
                "@type": "PostalAddress",
                "streetAddress": store["address"] or "",
            },
            "telephone": store["phone"] or "",
        }
        if store["latitude"] and store["longitude"]:
            json_ld["geo"] = {
                "@type": "GeoCoordinates",
                "latitude": store["latitude"],
                "longitude": store["longitude"],
            }
        if menu_highlights:
            json_ld["hasMenu"] = {
                "@type": "Menu",
                "hasMenuSection": {
                    "@type": "MenuSection",
                    "name": "招牌菜",
                    "hasMenuItem": [{"@type": "MenuItem", "name": h["name"]} for h in menu_highlights],
                },
            }

        structured_json = json.dumps(json_ld, ensure_ascii=False)
        menu_json = json.dumps(menu_highlights, ensure_ascii=False)

        # 为所有平台upsert geo_brand_profiles
        platforms = ["google", "baidu", "chatgpt", "perplexity", "xiaohongshu", "dianping"]
        platforms_updated = 0

        for platform in platforms:
            # 先计算seo_score
            profile_data = {
                "store_name": store["name"],
                "address": store["address"],
                "phone": store["phone"],
                "latitude": store["latitude"],
                "longitude": store["longitude"],
                "menu_highlights": menu_highlights,
                "business_hours": {},
                "cuisine_type": None,
            }
            score = self.calculate_seo_score(profile_data)

            await db.execute(
                text("""
                    INSERT INTO geo_brand_profiles
                        (tenant_id, store_id, platform, structured_data,
                         store_name, address, phone, latitude, longitude,
                         menu_highlights, seo_score, updated_at)
                    VALUES
                        (:tid, :store_id, :platform, :structured_data ::jsonb,
                         :store_name, :address, :phone, :lat, :lng,
                         :menu_highlights ::jsonb, :score, NOW())
                    ON CONFLICT (tenant_id, store_id, platform)
                        WHERE is_deleted = false
                    DO UPDATE SET
                        structured_data = EXCLUDED.structured_data,
                        store_name = EXCLUDED.store_name,
                        address = EXCLUDED.address,
                        phone = EXCLUDED.phone,
                        latitude = EXCLUDED.latitude,
                        longitude = EXCLUDED.longitude,
                        menu_highlights = EXCLUDED.menu_highlights,
                        seo_score = EXCLUDED.seo_score,
                        updated_at = NOW()
                """),
                {
                    "tid": str(tenant_id),
                    "store_id": str(store_id),
                    "platform": platform,
                    "structured_data": structured_json,
                    "store_name": store["name"],
                    "address": store["address"],
                    "phone": store["phone"],
                    "lat": store["latitude"],
                    "lng": store["longitude"],
                    "menu_highlights": menu_json,
                    "score": score,
                },
            )
            platforms_updated += 1

        await db.commit()
        log.info(
            "geo_seo.structured_data_generated",
            platforms_updated=platforms_updated,
            seo_score=score,
        )
        return {
            "store_id": str(store_id),
            "platforms_updated": platforms_updated,
            "seo_score": score,
        }

    # ─── AI引用检测 ────────────────────────────────────

    async def check_ai_citation(
        self,
        tenant_id: uuid.UUID,
        query: str,
        platform: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """检测AI搜索引擎中品牌是否被引用

        当前为模拟实现：真实版本将调用各平台API获取AI生成回答，
        解析其中是否提及品牌。模拟逻辑基于查询关键词概率生成结果。

        Returns: {"query": str, "platform": str, "mention_found": bool, ...}
        """
        log = logger.bind(
            tenant_id=str(tenant_id),
            query=query,
            platform=platform,
        )

        # 模拟：基于query长度和平台做伪随机判定
        # 真实实现会调用ChatGPT/Perplexity/Google AI等API
        hash_val = hash(f"{str(tenant_id)}:{query}:{platform}") % 100
        mention_found = hash_val < 35  # ~35%引用率模拟

        mention_text = None
        mention_position = None
        competitor_mentions: list[dict[str, Any]] = []
        sentiment = "neutral"

        if mention_found:
            mention_text = f"在回答「{query}」时提到了您的品牌，推荐其菜品特色和服务。"
            mention_position = (hash_val % 5) + 1
            sentiment = "positive" if hash_val < 20 else "neutral"
        else:
            competitor_mentions = [
                {"name": "海底捞", "position": 1},
                {"name": "太二酸菜鱼", "position": 2},
            ]

        # 获取当前最大check_round
        round_row = await db.execute(
            text("""
                SELECT COALESCE(MAX(check_round), 0) AS max_round
                FROM ai_citation_monitors
                WHERE tenant_id = :tid
                  AND query = :query
                  AND platform = :platform
                  AND is_deleted = FALSE
            """),
            {"tid": str(tenant_id), "query": query, "platform": platform},
        )
        max_round = round_row.scalar() or 0

        await db.execute(
            text("""
                INSERT INTO ai_citation_monitors
                    (tenant_id, query, platform, mention_found, mention_text,
                     mention_position, competitor_mentions, sentiment,
                     checked_at, check_round)
                VALUES
                    (:tid, :query, :platform, :found, :mtext,
                     :mpos, :competitors ::jsonb, :sentiment,
                     NOW(), :round)
            """),
            {
                "tid": str(tenant_id),
                "query": query,
                "platform": platform,
                "found": mention_found,
                "mtext": mention_text,
                "mpos": mention_position,
                "competitors": json.dumps(competitor_mentions, ensure_ascii=False),
                "sentiment": sentiment,
                "round": max_round + 1,
            },
        )
        await db.commit()

        log.info(
            "geo_seo.citation_checked",
            mention_found=mention_found,
            check_round=max_round + 1,
        )
        return {
            "query": query,
            "platform": platform,
            "mention_found": mention_found,
            "mention_text": mention_text,
            "mention_position": mention_position,
            "competitor_mentions": competitor_mentions,
            "sentiment": sentiment,
            "check_round": max_round + 1,
        }

    # ─── 批量引用检测 ──────────────────────────────────

    async def batch_check_citations(
        self,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """批量运行预定义查询模板 × 平台矩阵

        从门店档案中提取品牌名和城市，展开查询模板后逐一检测。

        Returns: {"total_checks": int, "mentions_found": int, "results": [...]}
        """
        log = logger.bind(tenant_id=str(tenant_id))

        # 获取品牌信息（从已有档案推断）
        profile_row = await db.execute(
            text("""
                SELECT DISTINCT store_name, address, cuisine_type
                FROM geo_brand_profiles
                WHERE tenant_id = :tid
                  AND is_deleted = FALSE
                LIMIT 1
            """),
            {"tid": str(tenant_id)},
        )
        profile = profile_row.mappings().first()

        brand_name = profile["store_name"] if profile else "我的餐厅"
        city = "长沙"  # 默认城市，真实实现从address解析
        cuisine = profile["cuisine_type"] if profile and profile["cuisine_type"] else "海鲜"

        # 展开查询模板
        queries: list[str] = []
        for tpl in _QUERY_TEMPLATES:
            q = tpl.format(city=city, cuisine=cuisine, brand_name=brand_name)
            queries.append(q)

        results: list[dict[str, Any]] = []
        mentions_found = 0

        for query in queries:
            for platform in _AI_PLATFORMS:
                result = await self.check_ai_citation(tenant_id, query, platform, db)
                results.append(result)
                if result["mention_found"]:
                    mentions_found += 1

        total = len(results)
        log.info(
            "geo_seo.batch_citations_done",
            total_checks=total,
            mentions_found=mentions_found,
        )
        return {
            "total_checks": total,
            "mentions_found": mentions_found,
            "citation_rate": round(mentions_found / total * 100, 1) if total else 0,
            "results": results,
        }

    # ─── GEO SEO仪表盘 ────────────────────────────────

    async def get_seo_dashboard(
        self,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """聚合GEO SEO仪表盘数据

        Returns:
          - total_profiles: 档案总数
          - stores_with_profiles: 有档案的门店数
          - avg_seo_score: 平均SEO评分
          - citation_rate: 引用率（%）
          - platform_breakdown: 按平台分解的统计
          - score_distribution: 分数区间分布
        """
        log = logger.bind(tenant_id=str(tenant_id))

        # 档案统计
        profile_stats = await db.execute(
            text("""
                SELECT
                    COUNT(*) AS total_profiles,
                    COUNT(DISTINCT store_id) AS stores_with_profiles,
                    COALESCE(AVG(seo_score), 0) AS avg_seo_score,
                    COUNT(*) FILTER (WHERE seo_score >= 80) AS high_score_count,
                    COUNT(*) FILTER (WHERE seo_score >= 50 AND seo_score < 80) AS mid_score_count,
                    COUNT(*) FILTER (WHERE seo_score < 50) AS low_score_count
                FROM geo_brand_profiles
                WHERE tenant_id = :tid
                  AND is_deleted = FALSE
            """),
            {"tid": str(tenant_id)},
        )
        ps = profile_stats.mappings().first()

        # 按平台分解
        platform_rows = await db.execute(
            text("""
                SELECT
                    platform,
                    COUNT(*) AS profile_count,
                    COALESCE(AVG(seo_score), 0) AS avg_score,
                    COUNT(*) FILTER (WHERE citation_found = TRUE) AS citations_found
                FROM geo_brand_profiles
                WHERE tenant_id = :tid
                  AND is_deleted = FALSE
                GROUP BY platform
                ORDER BY platform
            """),
            {"tid": str(tenant_id)},
        )
        platform_breakdown = [
            {
                "platform": r["platform"],
                "profile_count": r["profile_count"],
                "avg_score": round(float(r["avg_score"]), 1),
                "citations_found": r["citations_found"],
            }
            for r in platform_rows.mappings().all()
        ]

        # 引用监测统计
        citation_stats = await db.execute(
            text("""
                SELECT
                    COUNT(*) AS total_checks,
                    COUNT(*) FILTER (WHERE mention_found = TRUE) AS mentions_found
                FROM ai_citation_monitors
                WHERE tenant_id = :tid
                  AND is_deleted = FALSE
            """),
            {"tid": str(tenant_id)},
        )
        cs = citation_stats.mappings().first()
        total_checks = cs["total_checks"] if cs else 0
        mentions_found = cs["mentions_found"] if cs else 0

        dashboard = {
            "total_profiles": ps["total_profiles"] if ps else 0,
            "stores_with_profiles": ps["stores_with_profiles"] if ps else 0,
            "avg_seo_score": round(float(ps["avg_seo_score"]), 1) if ps else 0,
            "score_distribution": {
                "high": ps["high_score_count"] if ps else 0,
                "mid": ps["mid_score_count"] if ps else 0,
                "low": ps["low_score_count"] if ps else 0,
            },
            "citation_rate": round(mentions_found / total_checks * 100, 1) if total_checks else 0,
            "total_citation_checks": total_checks,
            "total_mentions_found": mentions_found,
            "platform_breakdown": platform_breakdown,
        }

        log.info("geo_seo.dashboard_fetched", avg_score=dashboard["avg_seo_score"])
        return dashboard

    # ─── 优化建议 ──────────────────────────────────────

    async def optimize_content_suggestions(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """基于SEO评分缺失项，给出具体优化建议

        Returns: {"store_id": str, "current_score": int, "suggestions": [...], "potential_score": int}
        """
        log = logger.bind(
            tenant_id=str(tenant_id),
            store_id=str(store_id),
        )

        # 读取该门店的第一个档案（任意平台，内容相同）
        row = await db.execute(
            text("""
                SELECT store_name, address, phone, cuisine_type,
                       latitude, longitude, business_hours, menu_highlights,
                       seo_score
                FROM geo_brand_profiles
                WHERE tenant_id = :tid
                  AND store_id = :store_id
                  AND is_deleted = FALSE
                LIMIT 1
            """),
            {"tid": str(tenant_id), "store_id": str(store_id)},
        )
        profile = row.mappings().first()

        if not profile:
            log.warning("geo_seo.profile_not_found_for_optimization")
            return {
                "store_id": str(store_id),
                "current_score": 0,
                "suggestions": [{"field": "profile", "message": "请先生成品牌档案", "points": 100}],
                "potential_score": 100,
            }

        current_score = profile["seo_score"]
        suggestions: list[dict[str, Any]] = []

        if not profile["store_name"]:
            suggestions.append({"field": "store_name", "message": "添加门店名称", "points": 10})
        if not profile["address"]:
            suggestions.append({"field": "address", "message": "添加详细地址", "points": 10})
        if not profile["phone"]:
            suggestions.append({"field": "phone", "message": "添加联系电话", "points": 10})
        if not profile["cuisine_type"]:
            suggestions.append({"field": "cuisine_type", "message": "添加菜系类型（如：海鲜、湘菜）", "points": 10})

        hours = profile["business_hours"]
        if not hours or hours == {} or hours == "{}":
            suggestions.append({"field": "business_hours", "message": "添加营业时间", "points": 15})

        highlights = profile["menu_highlights"]
        if not highlights or highlights == [] or highlights == "[]":
            suggestions.append({"field": "menu_highlights", "message": "添加招牌菜品", "points": 15})

        if not profile["latitude"] or not profile["longitude"]:
            suggestions.append({"field": "coordinates", "message": "添加门店经纬度坐标", "points": 15})

        # 额外建议：照片（结构化数据中检测）
        suggestions.append({"field": "photos", "message": "上传门店和菜品照片以提升排名", "points": 15})

        potential_score = min(100, current_score + sum(s["points"] for s in suggestions))

        log.info(
            "geo_seo.optimization_suggestions",
            current_score=current_score,
            suggestion_count=len(suggestions),
            potential_score=potential_score,
        )
        return {
            "store_id": str(store_id),
            "current_score": current_score,
            "suggestions": suggestions,
            "potential_score": potential_score,
        }

    # ─── SEO评分计算 ──────────────────────────────────

    @staticmethod
    def calculate_seo_score(profile: dict[str, Any]) -> int:
        """基于档案完整度计算SEO评分（0-100）

        评分权重：
          - store_name:      10分
          - address:         10分
          - phone:           10分
          - business_hours:  15分
          - menu_highlights: 15分
          - photos:          15分（当前暂不评估，预留）
          - cuisine_type:    10分
          - coordinates:     15分（latitude + longitude）
        """
        score = 0

        if profile.get("store_name"):
            score += 10
        if profile.get("address"):
            score += 10
        if profile.get("phone"):
            score += 10
        if profile.get("cuisine_type"):
            score += 10

        hours = profile.get("business_hours")
        if hours and hours != {} and hours != "{}":
            score += 15

        highlights = profile.get("menu_highlights")
        if highlights and highlights != [] and highlights != "[]" and len(highlights) > 0:
            score += 15

        # photos: 预留15分，当前不评估（未来接入图片存储后启用）
        # score += 15

        lat = profile.get("latitude")
        lng = profile.get("longitude")
        if lat is not None and lng is not None:
            score += 15

        return min(100, max(0, score))
