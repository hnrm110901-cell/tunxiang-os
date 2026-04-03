"""市场趋势扫描服务 — 扫描菜品/食材趋势并计算趋势评分

负责：
  - 从抖音/美团平台扫描菜品趋势
  - 扫描食材/原料趋势
  - 计算 0-100 趋势评分
  - 写入 market_trend_signals 表
"""
import uuid
from datetime import date, timedelta
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

# 趋势方向判断阈值
_RISING_THRESHOLD = 60.0    # score >= 60 且方向为 rising → rising
_DECLINING_THRESHOLD = 30.0  # score < 30 → declining


class TrendScannerService:
    """市场趋势扫描服务"""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def scan_dish_trends(
        self,
        tenant_id: uuid.UUID,
        city: str,
        cuisine_type: str,
    ) -> dict[str, Any]:
        """
        扫描指定城市/菜系的热门菜品趋势，写入 market_trend_signals。

        数据来源：抖音热门菜品接口（DouyinAdapter.fetch_trending_dishes）
        """
        log = logger.bind(
            tenant_id=str(tenant_id),
            city=city,
            cuisine_type=cuisine_type,
        )
        import time
        t0 = time.monotonic()

        try:
            import os

            from adapters.douyin_adapter import DouyinAdapter
            adapter = DouyinAdapter(
                client_key=os.environ.get("DOUYIN_CLIENT_KEY", ""),
                client_secret=os.environ.get("DOUYIN_CLIENT_SECRET", ""),
            )
            try:
                trending_dishes = await adapter.fetch_trending_dishes(city, cuisine_type)
            finally:
                await adapter.close()
        except Exception as exc:  # noqa: BLE001 — 外部API/爬虫场景异常类型不可预测
            log.error("trend_scanner.scan_dish_trends.fetch_failed", error=str(exc))
            return {"ok": False, "error": str(exc), "saved": 0}

        saved = 0
        for dish in trending_dishes:
            scored = self.score_trend_signal(
                keyword=dish.keyword,
                source_data={
                    "mention_count": dish.mention_count,
                    "view_count": dish.view_count,
                    "platform_score": float(dish.trend_score),
                    "trend_direction": dish.trend_direction,
                },
            )

            try:
                await self._db.execute(
                    text("""
                        INSERT INTO market_trend_signals (
                            id, tenant_id, signal_type, keyword, category,
                            trend_score, trend_direction, source, region,
                            period_start, period_end, raw_data
                        ) VALUES (
                            :id, :tenant_id, 'dish_trend', :keyword, :category,
                            :trend_score, :trend_direction, 'douyin', :region,
                            :period_start, :period_end, :raw_data::jsonb
                        )
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "tenant_id": str(tenant_id),
                        "keyword": dish.keyword,
                        "category": dish.category,
                        "trend_score": scored["score"],
                        "trend_direction": scored["direction"],
                        "region": city,
                        "period_start": dish.period_start.isoformat(),
                        "period_end": dish.period_end.isoformat(),
                        "raw_data": _to_json(dish.raw_data),
                    },
                )
                saved += 1
            except Exception as exc:  # noqa: BLE001 — 外部API/爬虫场景异常类型不可预测
                log.warning("trend_scanner.insert_failed", keyword=dish.keyword, error=str(exc))

        await self._db.commit()

        elapsed = time.monotonic() - t0
        log.info(
            "trend_scanner.scan_dish_trends.done",
            total_fetched=len(trending_dishes),
            saved=saved,
            elapsed_ms=round(elapsed * 1000),
        )
        return {
            "ok": True,
            "city": city,
            "cuisine_type": cuisine_type,
            "source": "douyin",
            "fetched": len(trending_dishes),
            "saved": saved,
        }

    async def scan_ingredient_trends(
        self,
        tenant_id: uuid.UUID,
        category: str,
        region: str = "全国",
    ) -> dict[str, Any]:
        """
        扫描食材/原料趋势信号。

        数据来源：美团点评聚合食材搜索趋势（当前为模拟实现，
        正式接入时替换为真实美团食材趋势 API）
        """
        log = logger.bind(
            tenant_id=str(tenant_id),
            category=category,
            region=region,
        )
        import time
        t0 = time.monotonic()

        # 占位符：从 review_intel 表中提取食材关键词频次作为趋势信号
        # 生产中应替换为真实的食材趋势数据 API
        try:
            period_end = date.today()
            period_start = period_end - timedelta(days=7)

            # 从近7天自有门店点评中提取食材相关关键词
            result = await self._db.execute(
                text("""
                    SELECT content FROM review_intel
                    WHERE tenant_id = :tenant_id
                      AND is_own_store = TRUE
                      AND review_date >= :since
                    ORDER BY review_date DESC
                    LIMIT 200
                """),
                {"tenant_id": str(tenant_id), "since": period_start.isoformat()},
            )
            rows = result.fetchall()
            texts = [r[0] for r in rows if r[0]]
        except Exception as exc:  # noqa: BLE001 — 外部API/爬虫场景异常类型不可预测
            log.error("trend_scanner.scan_ingredient_trends.fetch_failed", error=str(exc))
            return {"ok": False, "error": str(exc), "saved": 0}

        # 简单词频统计作为趋势信号（生产中用 NLP 模型替换）
        keyword_counts = _count_ingredient_keywords(texts, category)

        saved = 0
        for keyword, count in keyword_counts.items():
            scored = self.score_trend_signal(
                keyword=keyword,
                source_data={"mention_count": count, "source": "review_intel"},
            )

            try:
                await self._db.execute(
                    text("""
                        INSERT INTO market_trend_signals (
                            id, tenant_id, signal_type, keyword, category,
                            trend_score, trend_direction, source, region,
                            period_start, period_end, raw_data
                        ) VALUES (
                            :id, :tenant_id, 'ingredient_trend', :keyword, :category,
                            :trend_score, :trend_direction, 'aggregated', :region,
                            :period_start, :period_end, :raw_data::jsonb
                        )
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "tenant_id": str(tenant_id),
                        "keyword": keyword,
                        "category": category,
                        "trend_score": scored["score"],
                        "trend_direction": scored["direction"],
                        "region": region,
                        "period_start": period_start.isoformat(),
                        "period_end": period_end.isoformat(),
                        "raw_data": _to_json({"mention_count": count}),
                    },
                )
                saved += 1
            except Exception as exc:  # noqa: BLE001 — 外部API/爬虫场景异常类型不可预测
                log.warning("trend_scanner.ingredient_insert_failed", keyword=keyword, error=str(exc))

        await self._db.commit()

        elapsed = time.monotonic() - t0
        log.info(
            "trend_scanner.scan_ingredient_trends.done",
            keywords_found=len(keyword_counts),
            saved=saved,
            elapsed_ms=round(elapsed * 1000),
        )
        return {
            "ok": True,
            "category": category,
            "region": region,
            "source": "aggregated",
            "keywords_found": len(keyword_counts),
            "saved": saved,
        }

    def score_trend_signal(
        self,
        keyword: str,
        source_data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        计算趋势信号评分（0-100）和方向。

        评分算法（加权综合）：
          - 平台热度指数（platform_score，0-100）权重 50%
          - 提及次数（mention_count）对数归一化 权重 30%
          - 播放量（view_count）对数归一化 权重 20%
          - 若无平台热度数据，则只用后两项
        """
        import math

        platform_score = float(source_data.get("platform_score", 0))
        mention_count = int(source_data.get("mention_count", 0))
        view_count = int(source_data.get("view_count", 0))

        # 对数归一化（以 10000 为基准，100% = 10000 次提及）
        mention_score = min(100.0, math.log1p(mention_count) / math.log1p(10000) * 100)
        view_score = min(100.0, math.log1p(view_count) / math.log1p(1_000_000) * 100)

        if platform_score > 0:
            final_score = (platform_score * 0.5) + (mention_score * 0.3) + (view_score * 0.2)
        else:
            # 无平台热度数据，按 6:4 分配
            final_score = (mention_score * 0.6) + (view_score * 0.4)

        final_score = round(final_score, 2)

        # 方向判断（综合平台方向信号）
        platform_direction = source_data.get("trend_direction", "")
        if platform_direction == "rising" or (final_score >= _RISING_THRESHOLD and not platform_direction):
            direction = "rising"
        elif platform_direction == "declining" or (final_score < _DECLINING_THRESHOLD and not platform_direction):
            direction = "declining"
        else:
            direction = "stable"

        return {
            "keyword": keyword,
            "score": final_score,
            "direction": direction,
            "components": {
                "platform_score": platform_score,
                "mention_score": round(mention_score, 2),
                "view_score": round(view_score, 2),
            },
        }


# ─── 内部辅助函数 ───

# 食材相关关键词词典（生产中应从配置或 NLP 模型获取）
_INGREDIENT_KEYWORDS_MAP: dict[str, list[str]] = {
    "海鲜": ["生蚝", "龙虾", "鲍鱼", "扇贝", "螃蟹", "虾", "鱼", "海参", "海胆"],
    "牛肉": ["牛排", "牛腩", "牛肉", "和牛", "安格斯", "雪花牛"],
    "猪肉": ["五花肉", "排骨", "猪蹄", "猪肚", "腊肉", "叉烧"],
    "蔬菜": ["菌菇", "松茸", "竹笋", "莲藕", "山药", "芦笋"],
    "调料": ["花椒", "辣椒", "藤椒", "麻椒", "香料", "酱料"],
}


def _count_ingredient_keywords(texts: list[str], category: str) -> dict[str, int]:
    """从文本列表中统计食材关键词出现次数"""
    keywords = _INGREDIENT_KEYWORDS_MAP.get(category, [])
    if not keywords:
        # category 不在预设列表中，尝试以 category 本身作为单个关键词
        keywords = [category]

    counts: dict[str, int] = {}
    for text_item in texts:
        for kw in keywords:
            if kw in text_item:
                counts[kw] = counts.get(kw, 0) + 1

    # 只保留有实际提及的关键词，按频次排序取 top 10
    sorted_counts = dict(
        sorted(counts.items(), key=lambda x: x[1], reverse=True)[:10]
    )
    return sorted_counts


def _to_json(data: dict[str, Any]) -> str:
    """序列化为 JSON 字符串"""
    import json
    return json.dumps(data, ensure_ascii=False, default=str)
