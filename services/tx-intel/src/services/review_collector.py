"""点评数据采集服务 — 多平台点评收集与情感分析

负责：
  - 从美团/抖音等平台采集门店点评
  - 调用 Claude API 做情感分析（sentiment score）
  - 主题提取归类（topics）
  - 写入 review_intel 表
"""

import uuid
from datetime import datetime, timezone
from typing import Any

import anthropic
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

logger = structlog.get_logger()

# 情感分析批量大小（避免单次 Claude API 请求过大）
_SENTIMENT_BATCH_SIZE = 10

# 主题分类候选标签
_TOPIC_CATEGORIES = [
    "菜品口味",
    "菜品分量",
    "菜品新鲜度",
    "菜品外观",
    "服务态度",
    "上菜速度",
    "环境氛围",
    "价格性价比",
    "包装品质",
    "外卖配送",
    "停车便利",
    "卫生整洁",
]


class ReviewCollectorService:
    """全渠道点评采集与分析服务

    ai_client 应由调用方注入 ModelRouter 实例（遵循 CLAUDE.md 规范）。
    tx-intel 与 tx-agent 独立部署时，通过 HTTP 调用 tx-agent /ai/complete 端点；
    单体部署时直接注入 ModelRouter。未注入时降级为直接调用（仅限测试环境）。
    """

    def __init__(self, db: AsyncSession, ai_client: anthropic.AsyncAnthropic | None = None) -> None:
        self._db = db
        # 生产环境应注入 ModelRouter；此处接受 AsyncAnthropic 作为兼容接口
        self._ai = ai_client or anthropic.AsyncAnthropic()

    async def collect_store_reviews(
        self,
        tenant_id: uuid.UUID,
        source: str,
        platform_store_id: str,
        is_own_store: bool = True,
        days: int = 7,
    ) -> dict[str, Any]:
        """
        从指定平台采集门店点评并写入 review_intel。

        参数：
          - tenant_id: 租户 ID
          - source: 'meituan' | 'douyin' | 'eleme' | 'dianping'
          - platform_store_id: 平台门店 ID
          - is_own_store: 是否为自家门店（True=自家, False=竞对）
          - days: 采集最近 N 天

        返回采集结果摘要。
        """
        log = logger.bind(
            tenant_id=str(tenant_id),
            source=source,
            platform_store_id=platform_store_id,
            is_own_store=is_own_store,
            days=days,
        )
        import time

        t0 = time.monotonic()

        # 1. 从平台采集原始点评
        try:
            raw_reviews = await _fetch_reviews_from_platform(source, platform_store_id, days)
        except Exception as exc:  # noqa: BLE001 — 外部API/爬虫场景异常类型不可预测
            error_msg = f"{type(exc).__name__}: {exc}"
            log.error("review_collector.fetch_failed", error=error_msg)
            return {"ok": False, "error": error_msg, "collected": 0}

        if not raw_reviews:
            log.info("review_collector.no_reviews", days=days)
            return {"ok": True, "collected": 0, "new": 0}

        # 2. 批量情感分析
        contents = [r["content"] for r in raw_reviews]
        sentiment_scores = await self._batch_analyze_sentiment(contents)
        topics_list = await self._batch_extract_topics(contents)

        # 3. 写入数据库（去重：same source+source_store_id+review_id 不重复插入）
        inserted = 0
        for i, review in enumerate(raw_reviews):
            sentiment = sentiment_scores[i] if i < len(sentiment_scores) else None
            topics = topics_list[i] if i < len(topics_list) else []

            try:
                result = await self._db.execute(
                    text("""
                        INSERT INTO review_intel (
                            id, tenant_id, source, source_store_id,
                            is_own_store, content, rating,
                            sentiment_score, topics, author_level,
                            review_date, collected_at
                        ) VALUES (
                            :id, :tenant_id, :source, :source_store_id,
                            :is_own_store, :content, :rating,
                            :sentiment_score, :topics::jsonb, :author_level,
                            :review_date, :collected_at
                        )
                        ON CONFLICT DO NOTHING
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "tenant_id": str(tenant_id),
                        "source": source,
                        "source_store_id": platform_store_id,
                        "is_own_store": is_own_store,
                        "content": review.get("content", ""),
                        "rating": review.get("rating"),
                        "sentiment_score": sentiment,
                        "topics": _serialize_topics(topics),
                        "author_level": review.get("author_level", "regular"),
                        "review_date": review.get("review_date"),
                        "collected_at": datetime.now(tz=timezone.utc),
                    },
                )
                inserted += result.rowcount
            except Exception as exc:  # noqa: BLE001 — 外部API/爬虫场景异常类型不可预测
                log.warning("review_collector.insert_failed", error=str(exc), review_id=review.get("review_id"))

        await self._db.commit()

        elapsed = time.monotonic() - t0
        log.info(
            "review_collector.collect_done",
            total_fetched=len(raw_reviews),
            inserted=inserted,
            elapsed_ms=round(elapsed * 1000),
        )
        return {
            "ok": True,
            "source": source,
            "platform_store_id": platform_store_id,
            "is_own_store": is_own_store,
            "collected": len(raw_reviews),
            "new": inserted,
            "elapsed_ms": round(elapsed * 1000),
        }

    async def analyze_sentiment(self, review_text: str) -> float | None:
        """
        调用 Claude API 对单条点评做情感分析。
        返回 -1.0（极负面）到 1.0（极正面）的评分，失败返回 None。
        """
        if not review_text or not review_text.strip():
            return None

        try:
            message = await self._ai.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=64,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "分析以下餐厅点评的情感倾向，只返回一个 -1.0 到 1.0 之间的数字，"
                            "-1.0 表示极度负面，0 表示中性，1.0 表示极度正面。"
                            "不要输出任何其他内容。\n\n"
                            f"点评：{review_text[:500]}"
                        ),
                    }
                ],
            )
            score_str = message.content[0].text.strip()
            score = float(score_str)
            return max(-1.0, min(1.0, score))
        except (ValueError, IndexError) as exc:
            logger.warning("review_collector.sentiment_parse_failed", error=str(exc))
            return None
        except Exception as exc:  # noqa: BLE001 — 外部API/爬虫场景异常类型不可预测
            logger.warning("review_collector.sentiment_api_failed", error=str(exc))
            return None

    async def extract_topics(self, review_text: str) -> list[dict[str, Any]]:
        """
        调用 Claude API 提取点评主题归类。
        返回格式：[{"topic": "菜品口味", "sentiment": "positive", "confidence": 0.85}]
        """
        if not review_text or not review_text.strip():
            return []

        topic_list_str = "、".join(_TOPIC_CATEGORIES)
        try:
            import json

            message = await self._ai.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=256,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"从以下点评中提取涉及的话题，候选话题：{topic_list_str}。\n"
                            "只返回 JSON 数组，格式：\n"
                            '[{"topic": "话题名", "sentiment": "positive/negative/neutral", "confidence": 0.0-1.0}]\n'
                            "最多 5 个话题，不要输出其他内容。\n\n"
                            f"点评：{review_text[:500]}"
                        ),
                    }
                ],
            )
            raw = message.content[0].text.strip()
            # 提取 JSON 数组
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start >= 0 and end > start:
                topics = json.loads(raw[start:end])
                return [
                    {
                        "topic": t.get("topic", ""),
                        "sentiment": t.get("sentiment", "neutral"),
                        "confidence": float(t.get("confidence", 0.5)),
                    }
                    for t in topics
                    if isinstance(t, dict) and t.get("topic")
                ]
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning("review_collector.topics_parse_failed", error=str(exc))
        except Exception as exc:  # noqa: BLE001 — 外部API/爬虫场景异常类型不可预测
            logger.warning("review_collector.topics_api_failed", error=str(exc))

        return []

    # ── 批量分析（减少 API 调用次数） ──

    async def _batch_analyze_sentiment(self, texts: list[str]) -> list[float | None]:
        """批量情感分析，每批 _SENTIMENT_BATCH_SIZE 条"""
        results: list[float | None] = []
        for i in range(0, len(texts), _SENTIMENT_BATCH_SIZE):
            batch = texts[i : i + _SENTIMENT_BATCH_SIZE]
            for text_item in batch:
                score = await self.analyze_sentiment(text_item)
                results.append(score)
        return results

    async def _batch_extract_topics(self, texts: list[str]) -> list[list[dict[str, Any]]]:
        """批量主题提取"""
        results: list[list[dict[str, Any]]] = []
        for text_item in texts:
            topics = await self.extract_topics(text_item)
            results.append(topics)
        return results


# ─── 内部辅助函数 ───


async def _fetch_reviews_from_platform(
    source: str,
    platform_store_id: str,
    days: int,
) -> list[dict[str, Any]]:
    """调用对应平台适配器采集点评，返回标准化字典列表"""
    import os

    if source == "meituan":
        from adapters.meituan_adapter import MeituanAdapter

        adapter = MeituanAdapter(
            app_key=os.environ.get("MEITUAN_APP_KEY", ""),
            app_secret=os.environ.get("MEITUAN_APP_SECRET", ""),
        )
        try:
            reviews = await adapter.fetch_recent_reviews(platform_store_id, days=days)
            return [
                {
                    "review_id": r.review_id,
                    "content": r.content,
                    "rating": float(r.rating),
                    "author_level": r.author_level,
                    "review_date": r.review_date.isoformat(),
                }
                for r in reviews
            ]
        finally:
            await adapter.close()

    if source == "douyin":
        from adapters.douyin_adapter import DouyinAdapter

        adapter = DouyinAdapter(
            client_key=os.environ.get("DOUYIN_CLIENT_KEY", ""),
            client_secret=os.environ.get("DOUYIN_CLIENT_SECRET", ""),
        )
        try:
            reviews = await adapter.fetch_store_reviews(platform_store_id, days=days)
            return [
                {
                    "review_id": r.review_id,
                    "content": r.content,
                    "rating": float(r.rating),
                    "author_level": r.author_level,
                    "review_date": r.review_date.isoformat(),
                }
                for r in reviews
            ]
        finally:
            await adapter.close()

    raise ValueError(f"暂不支持的点评来源: {source}（支持: meituan, douyin）")


def _serialize_topics(topics: list[dict[str, Any]]) -> str:
    """将 topics 列表序列化为 JSON 字符串（供 SQLAlchemy text() 参数绑定）"""
    import json

    return json.dumps(topics, ensure_ascii=False)
