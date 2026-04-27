"""改进建议引擎 — 基于差评聚合的门店改进推荐

负责：
  - 聚合差评关键词，按主题分组
  - 按频次排名
  - 生成可执行的改进建议
  - 输出受影响门店和示例评价
"""

import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# 主题关键词映射（差评维度）
_THEME_KEYWORDS: dict[str, list[str]] = {
    "菜品口味": ["难吃", "太咸", "太淡", "不好吃", "味道差", "不新鲜", "变质", "油腻", "不正宗"],
    "服务态度": ["服务差", "态度差", "不理人", "冷漠", "没礼貌", "不耐心", "不热情"],
    "上菜速度": ["上菜慢", "等太久", "等了半小时", "催了好几次", "出菜慢"],
    "环境卫生": ["脏", "不卫生", "头发", "虫", "苍蝇", "过期", "不干净", "有异味"],
    "菜品分量": ["分量少", "太少", "量不够", "不值", "缩水"],
    "性价比": ["贵", "太贵", "价格高", "不实惠", "不划算", "宰客"],
    "菜品温度": ["冷了", "凉了", "不热", "温度不够"],
}

# 每个主题对应的改进建议模板
_RECOMMENDATION_TEMPLATES: dict[str, str] = {
    "菜品口味": "建议：1)组织厨师团队复盘菜品标准化流程 2)加强出品前试味环节 3)收集顾客口味偏好数据，优化调味方案",
    "服务态度": "建议：1)开展服务意识培训（每周1次） 2)设立服务之星评选激励 3)建立顾客反馈即时响应机制",
    "上菜速度": "建议：1)优化后厨动线和备料流程 2)引入KDS出餐管理系统监控时效 3)高峰时段增加预制菜比例",
    "环境卫生": "建议：1)加强每日卫生检查频次（午餐前/晚餐前/打烊后） 2)完善食材存储标准 3)定期第三方卫生审计",
    "菜品分量": "建议：1)制定标准化菜品分量手册（含图片参照） 2)定期抽检出品重量 3)确保菜单图片与实际一致",
    "性价比": "建议：1)优化定价策略，增加高性价比套餐 2)提升菜品品质匹配价格定位 3)适当推出会员专属优惠",
    "菜品温度": "建议：1)缩短出餐到上桌的传菜时间 2)使用保温设备（加热灯/保温箱） 3)优化厨房出品节奏",
}


class ImprovementRecommender:
    """基于差评聚合的改进建议引擎

    从order_reviews和nps_surveys的负面反馈中提取关键词，
    按主题聚合后生成可执行的改进建议。
    """

    async def generate_recommendations(
        self,
        tenant_id: uuid.UUID,
        db: AsyncSession,
        store_id: uuid.UUID | None = None,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        """生成改进建议

        参数：
          - tenant_id: 租户ID
          - db: 数据库会话
          - store_id: 可选门店筛选
          - days: 分析周期（天）

        返回按频次排名的改进建议列表。
        """
        log = logger.bind(tenant_id=str(tenant_id), days=days)

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        now = datetime.now(tz=timezone.utc)
        period_start = (now - timedelta(days=days)).isoformat()

        # 1. 收集差评文本（从order_reviews）
        store_filter = ""
        params: dict[str, Any] = {
            "tenant_id": str(tenant_id),
            "start": period_start,
            "end": now.isoformat(),
        }
        if store_id:
            store_filter = "AND store_id = :store_id"
            params["store_id"] = str(store_id)

        negative_texts: list[dict[str, Any]] = []

        # 从order_reviews获取差评
        try:
            result = await db.execute(
                text(f"""
                    SELECT id, store_id, review_text, rating, platform
                    FROM order_reviews
                    WHERE tenant_id = :tenant_id
                      AND rating <= 3
                      AND review_text IS NOT NULL
                      AND review_text != ''
                      AND created_at BETWEEN :start AND :end
                      AND is_deleted = false
                      {store_filter}
                    ORDER BY created_at DESC
                    LIMIT 500
                """),
                params,
            )
            for row in result.fetchall():
                negative_texts.append(
                    {
                        "id": str(row[0]),
                        "store_id": str(row[1]) if row[1] else None,
                        "text": row[2],
                        "rating": float(row[3]) if row[3] is not None else None,
                        "source": "order_review",
                        "platform": row[4],
                    }
                )
        except Exception as exc:  # noqa: BLE001 — order_reviews表可能不存在
            log.debug("improvement_recommender.order_reviews_query_failed", error=str(exc))

        # 从nps_surveys获取贬损者反馈
        try:
            result = await db.execute(
                text(f"""
                    SELECT id, store_id, feedback_text, nps_score
                    FROM nps_surveys
                    WHERE tenant_id = :tenant_id
                      AND is_detractor = true
                      AND feedback_text IS NOT NULL
                      AND feedback_text != ''
                      AND sent_at BETWEEN :start AND :end
                      AND is_deleted = false
                      {store_filter}
                    ORDER BY sent_at DESC
                    LIMIT 200
                """),
                params,
            )
            for row in result.fetchall():
                negative_texts.append(
                    {
                        "id": str(row[0]),
                        "store_id": str(row[1]) if row[1] else None,
                        "text": row[2],
                        "rating": None,
                        "source": "nps_survey",
                        "platform": "nps",
                    }
                )
        except Exception as exc:  # noqa: BLE001 — nps_surveys表可能不存在
            log.debug("improvement_recommender.nps_surveys_query_failed", error=str(exc))

        if not negative_texts:
            log.info("improvement_recommender.no_negative_feedback")
            return []

        # 2. 按主题聚合
        theme_counter: Counter[str] = Counter()
        theme_stores: dict[str, set[str]] = {}
        theme_examples: dict[str, list[dict[str, Any]]] = {}

        for item in negative_texts:
            text_content = item["text"].lower()
            matched_themes: set[str] = set()

            for theme, keywords in _THEME_KEYWORDS.items():
                for kw in keywords:
                    if kw in text_content:
                        matched_themes.add(theme)
                        break

            for theme in matched_themes:
                theme_counter[theme] += 1

                if theme not in theme_stores:
                    theme_stores[theme] = set()
                if item["store_id"]:
                    theme_stores[theme].add(item["store_id"])

                if theme not in theme_examples:
                    theme_examples[theme] = []
                if len(theme_examples[theme]) < 3:
                    theme_examples[theme].append(
                        {
                            "id": item["id"],
                            "text": item["text"][:200],
                            "rating": item["rating"],
                            "source": item["source"],
                        }
                    )

        # 3. 排名并生成建议
        total_negative = len(negative_texts)
        recommendations = []

        for theme, frequency in theme_counter.most_common():
            pct = round(frequency / total_negative * 100, 1)
            recommendation_text = _RECOMMENDATION_TEMPLATES.get(
                theme,
                f"建议：针对「{theme}」问题开展专项改进，制定量化目标并跟踪执行效果。",
            )

            recommendations.append(
                {
                    "theme": theme,
                    "frequency": frequency,
                    "pct_of_negative": pct,
                    "affected_stores": sorted(theme_stores.get(theme, set())),
                    "example_reviews": theme_examples.get(theme, []),
                    "recommendation_text": recommendation_text,
                }
            )

        log.info(
            "improvement_recommender.recommendations_generated",
            total_negative=total_negative,
            themes_found=len(recommendations),
        )
        return recommendations
