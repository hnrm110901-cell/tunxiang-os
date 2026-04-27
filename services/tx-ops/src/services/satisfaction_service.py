"""满意度评分服务 — Sprint G4

管理顾客满意度评分（整体/食物/服务/速度），
差评自动告警，NPS 计算，满意度仪表盘。

评分范围 1-5，整体 ≤ 2 自动标记为差评。
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


class SatisfactionService:
    """满意度评分服务。"""

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  submit_rating — 提交评分
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def submit_rating(
        self,
        db: AsyncSession,
        store_id: uuid.UUID,
        tenant_id: uuid.UUID,
        order_id: Optional[uuid.UUID],
        overall_score: int,
        food_score: Optional[int] = None,
        service_score: Optional[int] = None,
        speed_score: Optional[int] = None,
        comment: Optional[str] = None,
        source: str = "miniapp",
        journey_id: Optional[uuid.UUID] = None,
    ) -> dict[str, Any]:
        """提交评分。

        如果 overall_score <= 2: 立即生成差评告警。
        """
        # 参数校验
        for label, val in [
            ("overall_score", overall_score),
            ("food_score", food_score),
            ("service_score", service_score),
            ("speed_score", speed_score),
        ]:
            if val is not None and not (1 <= val <= 5):
                raise ValueError(f"{label} 必须在 1-5 之间，当前值: {val}")

        if source not in ("miniapp", "pos", "manual"):
            raise ValueError(f"无效来源: {source}，有效值: miniapp/pos/manual")

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        # 自动关联 journey
        if journey_id is None and order_id is not None:
            jr = await db.execute(
                text("""
                    SELECT id FROM customer_journey_timings
                    WHERE order_id = :order_id
                      AND tenant_id = :tenant_id
                      AND is_deleted = FALSE
                    ORDER BY created_at DESC LIMIT 1
                """),
                {"order_id": str(order_id), "tenant_id": str(tenant_id)},
            )
            found = jr.scalar_one_or_none()
            if found:
                journey_id = found

        result = await db.execute(
            text("""
                INSERT INTO satisfaction_ratings
                    (tenant_id, store_id, order_id, journey_id,
                     overall_score, food_score, service_score, speed_score,
                     comment, source)
                VALUES
                    (:tenant_id, :store_id, :order_id, :journey_id,
                     :overall_score, :food_score, :service_score, :speed_score,
                     :comment, :source)
                RETURNING id, tenant_id, store_id, order_id, journey_id,
                          overall_score, food_score, service_score, speed_score,
                          comment, source, is_negative, created_at
            """),
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "order_id": str(order_id) if order_id else None,
                "journey_id": str(journey_id) if journey_id else None,
                "overall_score": overall_score,
                "food_score": food_score,
                "service_score": service_score,
                "speed_score": speed_score,
                "comment": comment,
                "source": source,
            },
        )
        row = result.mappings().first()
        rating_id = row["id"]
        await db.commit()

        log.info(
            "satisfaction_rating_submitted",
            rating_id=str(rating_id),
            store_id=str(store_id),
            overall_score=overall_score,
            is_negative=row["is_negative"],
        )

        # 差评告警
        if overall_score <= 2:
            await self._trigger_negative_alert(
                db, store_id, tenant_id, rating_id, order_id, overall_score, comment
            )

        return {
            "id": str(row["id"]),
            "tenant_id": str(row["tenant_id"]),
            "store_id": str(row["store_id"]),
            "order_id": str(row["order_id"]) if row["order_id"] else None,
            "journey_id": str(row["journey_id"]) if row["journey_id"] else None,
            "overall_score": row["overall_score"],
            "food_score": row["food_score"],
            "service_score": row["service_score"],
            "speed_score": row["speed_score"],
            "comment": row["comment"],
            "source": row["source"],
            "is_negative": row["is_negative"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }

    async def _trigger_negative_alert(
        self,
        db: AsyncSession,
        store_id: uuid.UUID,
        tenant_id: uuid.UUID,
        rating_id: uuid.UUID,
        order_id: Optional[uuid.UUID],
        overall_score: int,
        comment: Optional[str],
    ) -> None:
        """差评告警：尝试写入 notifications 表，失败则 structlog.warning。"""
        alert_title = f"差评告警: 评分{overall_score}/5"
        alert_body = f"顾客评分 {overall_score}/5"
        if comment:
            alert_body += f"，评语: {comment[:200]}"

        try:
            # 尝试写入 notifications 表
            await db.execute(
                text("""
                    INSERT INTO notifications
                        (tenant_id, store_id, title, body, category, severity, metadata)
                    VALUES
                        (:tenant_id, :store_id, :title, :body, 'satisfaction', 'high',
                         jsonb_build_object(
                            'rating_id', :rating_id::TEXT,
                            'order_id', :order_id::TEXT,
                            'overall_score', :score
                         ))
                """),
                {
                    "tenant_id": str(tenant_id),
                    "store_id": str(store_id),
                    "title": alert_title,
                    "body": alert_body,
                    "rating_id": str(rating_id),
                    "order_id": str(order_id) if order_id else None,
                    "score": overall_score,
                },
            )
            await db.commit()
            log.info(
                "negative_alert_created",
                rating_id=str(rating_id),
                store_id=str(store_id),
            )
        except SQLAlchemyError:
            # notifications 表可能不存在，降级为日志告警
            log.warning(
                "negative_rating_alert",
                rating_id=str(rating_id),
                store_id=str(store_id),
                order_id=str(order_id) if order_id else None,
                overall_score=overall_score,
                comment=comment[:200] if comment else None,
                note="无法写入notifications表，已输出日志告警",
            )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  get_satisfaction_dashboard — 满意度仪表盘
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def get_satisfaction_dashboard(
        self,
        db: AsyncSession,
        store_id: uuid.UUID,
        tenant_id: uuid.UUID,
        date_from: date,
        date_to: date,
    ) -> dict[str, Any]:
        """满意度仪表盘。

        - 总体评分 (1-5 均值) + NPS
        - 四维度评分 (食物/服务/速度/整体)
        - 差评 TOP 原因 (comment 词频分析)
        - 趋势 (日/周)
        """
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        # 1) 总体评分 + 四维度均值
        score_result = await db.execute(
            text("""
                SELECT
                    COUNT(*)                              AS total_ratings,
                    ROUND(AVG(overall_score)::NUMERIC, 2) AS overall_avg,
                    ROUND(AVG(food_score)::NUMERIC, 2)    AS food_avg,
                    ROUND(AVG(service_score)::NUMERIC, 2) AS service_avg,
                    ROUND(AVG(speed_score)::NUMERIC, 2)   AS speed_avg,
                    COUNT(*) FILTER (WHERE is_negative)   AS negative_count,
                    COUNT(*) FILTER (WHERE overall_score >= 4) AS promoter_count,
                    COUNT(*) FILTER (WHERE overall_score <= 2) AS detractor_count
                FROM satisfaction_ratings
                WHERE store_id = :store_id
                  AND tenant_id = :tenant_id
                  AND created_at >= :date_from::DATE
                  AND created_at < (:date_to::DATE + INTERVAL '1 day')
                  AND is_deleted = FALSE
            """),
            {
                "store_id": str(store_id),
                "tenant_id": str(tenant_id),
                "date_from": date_from,
                "date_to": date_to,
            },
        )
        s = score_result.mappings().first()
        total = int(s["total_ratings"]) if s else 0

        # NPS = (推荐者% - 贬损者%)。映射: 4-5星=推荐者, 1-2星=贬损者
        nps = 0.0
        if total > 0:
            promoter_pct = int(s["promoter_count"]) * 100.0 / total
            detractor_pct = int(s["detractor_count"]) * 100.0 / total
            nps = round(promoter_pct - detractor_pct, 1)

        # 2) 评分分布
        dist_result = await db.execute(
            text("""
                SELECT overall_score, COUNT(*) AS cnt
                FROM satisfaction_ratings
                WHERE store_id = :store_id
                  AND tenant_id = :tenant_id
                  AND created_at >= :date_from::DATE
                  AND created_at < (:date_to::DATE + INTERVAL '1 day')
                  AND is_deleted = FALSE
                GROUP BY overall_score
                ORDER BY overall_score
            """),
            {
                "store_id": str(store_id),
                "tenant_id": str(tenant_id),
                "date_from": date_from,
                "date_to": date_to,
            },
        )
        distribution = {
            int(row["overall_score"]): int(row["cnt"])
            for row in dist_result.mappings().all()
        }

        # 3) 差评评语词频（简单中文分词：按标点和空格分割）
        comment_result = await db.execute(
            text("""
                SELECT comment
                FROM satisfaction_ratings
                WHERE store_id = :store_id
                  AND tenant_id = :tenant_id
                  AND created_at >= :date_from::DATE
                  AND created_at < (:date_to::DATE + INTERVAL '1 day')
                  AND is_negative = TRUE
                  AND comment IS NOT NULL
                  AND comment != ''
                  AND is_deleted = FALSE
            """),
            {
                "store_id": str(store_id),
                "tenant_id": str(tenant_id),
                "date_from": date_from,
                "date_to": date_to,
            },
        )
        negative_comments = [
            row["comment"] for row in comment_result.mappings().all()
        ]
        top_keywords = self._extract_keywords(negative_comments)

        # 4) 每日趋势
        trend_result = await db.execute(
            text("""
                SELECT
                    DATE(created_at) AS rating_date,
                    COUNT(*) AS cnt,
                    ROUND(AVG(overall_score)::NUMERIC, 2) AS avg_score,
                    COUNT(*) FILTER (WHERE is_negative) AS negative_cnt
                FROM satisfaction_ratings
                WHERE store_id = :store_id
                  AND tenant_id = :tenant_id
                  AND created_at >= :date_from::DATE
                  AND created_at < (:date_to::DATE + INTERVAL '1 day')
                  AND is_deleted = FALSE
                GROUP BY DATE(created_at)
                ORDER BY DATE(created_at)
            """),
            {
                "store_id": str(store_id),
                "tenant_id": str(tenant_id),
                "date_from": date_from,
                "date_to": date_to,
            },
        )
        trends = [
            {
                "date": str(row["rating_date"]),
                "count": int(row["cnt"]),
                "avg_score": float(row["avg_score"]) if row["avg_score"] else 0.0,
                "negative_count": int(row["negative_cnt"]),
            }
            for row in trend_result.mappings().all()
        ]

        log.info(
            "satisfaction_dashboard_computed",
            store_id=str(store_id),
            total_ratings=total,
            nps=nps,
        )

        return {
            "date_range": [str(date_from), str(date_to)],
            "total_ratings": total,
            "scores": {
                "overall": float(s["overall_avg"]) if s and s["overall_avg"] else None,
                "food": float(s["food_avg"]) if s and s["food_avg"] else None,
                "service": float(s["service_avg"]) if s and s["service_avg"] else None,
                "speed": float(s["speed_avg"]) if s and s["speed_avg"] else None,
            },
            "nps": nps,
            "negative_count": int(s["negative_count"]) if s else 0,
            "distribution": distribution,
            "top_negative_keywords": top_keywords,
            "negative_comments_sample": negative_comments[:10],
            "trends": trends,
        }

    @staticmethod
    def _extract_keywords(comments: list[str], top_n: int = 10) -> list[dict[str, Any]]:
        """从差评评语中提取高频关键词。

        简单实现：按常见分隔符切分，过滤停用词，统计词频。
        生产环境可接入 jieba 分词。
        """
        import re

        stop_words = {
            "的", "了", "是", "在", "我", "有", "和", "就", "不", "人",
            "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去",
            "你", "会", "着", "没有", "看", "好", "自己", "这", "他", "她",
            "吗", "这个", "那个", "什么", "怎么", "为什么", "但是", "还是",
            "可以", "没", "太", "真", "比较", "非常",
        }
        counter: Counter[str] = Counter()
        for comment in comments:
            # 简单切分：按非中文字符和常见标点分割
            tokens = re.findall(r"[\u4e00-\u9fff]{2,}", comment)
            for token in tokens:
                if token not in stop_words:
                    counter[token] += 1

        return [
            {"keyword": kw, "count": cnt}
            for kw, cnt in counter.most_common(top_n)
        ]

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  get_negative_alerts — 差评告警列表
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def get_negative_alerts(
        self,
        db: AsyncSession,
        store_id: uuid.UUID,
        tenant_id: uuid.UUID,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """差评告警列表（30秒 SLA 要求快速返回）。

        返回最近的差评记录，按时间倒序。
        """
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        result = await db.execute(
            text("""
                SELECT
                    sr.id,
                    sr.order_id,
                    sr.journey_id,
                    sr.overall_score,
                    sr.food_score,
                    sr.service_score,
                    sr.speed_score,
                    sr.comment,
                    sr.source,
                    sr.created_at,
                    cjt.table_id,
                    t.name AS table_name
                FROM satisfaction_ratings sr
                LEFT JOIN customer_journey_timings cjt ON cjt.id = sr.journey_id
                LEFT JOIN tables t ON t.id = cjt.table_id
                WHERE sr.store_id = :store_id
                  AND sr.tenant_id = :tenant_id
                  AND sr.is_negative = TRUE
                  AND sr.is_deleted = FALSE
                ORDER BY sr.created_at DESC
                LIMIT :limit
            """),
            {
                "store_id": str(store_id),
                "tenant_id": str(tenant_id),
                "limit": limit,
            },
        )

        alerts = [
            {
                "rating_id": str(row["id"]),
                "order_id": str(row["order_id"]) if row["order_id"] else None,
                "journey_id": str(row["journey_id"]) if row["journey_id"] else None,
                "table_name": row["table_name"],
                "overall_score": row["overall_score"],
                "food_score": row["food_score"],
                "service_score": row["service_score"],
                "speed_score": row["speed_score"],
                "comment": row["comment"],
                "source": row["source"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "elapsed_since_minutes": round(
                    (datetime.now(timezone.utc) - row["created_at"]).total_seconds() / 60, 1
                ) if row["created_at"] else None,
            }
            for row in result.mappings().all()
        ]

        log.info(
            "negative_alerts_fetched",
            store_id=str(store_id),
            count=len(alerts),
        )
        return alerts
