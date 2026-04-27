"""NPS调查服务 — 客户满意度追踪与分析

负责：
  - 发送NPS调查、记录回复
  - NPS仪表盘（得分计算、趋势、回复率）
  - 按门店NPS分解
  - 贬损者跟进列表
  - 反馈文本自动主题提取
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# 反馈文本主题关键词映射
_FEEDBACK_TAGS: dict[str, list[str]] = {
    "服务": ["服务", "态度", "热情", "冷漠", "不理人", "服务员"],
    "口味": ["口味", "好吃", "难吃", "味道", "太咸", "太淡", "正宗"],
    "价格": ["价格", "贵", "便宜", "实惠", "不值", "性价比"],
    "速度": ["速度", "上菜慢", "等太久", "快", "催"],
    "环境": ["环境", "干净", "脏", "氛围", "装修", "噪音"],
    "卫生": ["卫生", "不卫生", "头发", "虫", "苍蝇", "过期"],
    "态度": ["态度", "态度差", "没礼貌", "冷淡", "友好", "耐心"],
}


def _extract_tags(feedback_text: str) -> list[str]:
    """从反馈文本中提取主题标签（关键词匹配）"""
    if not feedback_text:
        return []
    tags: list[str] = []
    text_lower = feedback_text.lower()
    for tag, keywords in _FEEDBACK_TAGS.items():
        for kw in keywords:
            if kw in text_lower:
                tags.append(tag)
                break
    return tags


class NPSService:
    """NPS调查与分析服务

    NPS = % 推荐者(9-10) - % 贬损者(0-6)
    被动者(7-8)不参与计算。
    """

    async def send_survey(
        self,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        store_id: uuid.UUID,
        order_id: uuid.UUID | None,
        db: AsyncSession,
        channel: str = "wechat",
    ) -> dict[str, Any]:
        """创建NPS调查记录（待回复状态）

        参数：
          - tenant_id: 租户ID
          - customer_id: 客户ID
          - store_id: 门店ID
          - order_id: 可选关联订单ID
          - db: 数据库会话
          - channel: 发送渠道（wechat/sms/app）
        """
        log = logger.bind(
            tenant_id=str(tenant_id),
            customer_id=str(customer_id),
            store_id=str(store_id),
        )

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        survey_id = uuid.uuid4()
        now = datetime.now(tz=timezone.utc)

        await db.execute(
            text("""
                INSERT INTO nps_surveys (
                    id, tenant_id, customer_id, store_id,
                    order_id, channel, sent_at
                ) VALUES (
                    :id, :tenant_id, :customer_id, :store_id,
                    :order_id, :channel, :sent_at
                )
            """),
            {
                "id": str(survey_id),
                "tenant_id": str(tenant_id),
                "customer_id": str(customer_id),
                "store_id": str(store_id),
                "order_id": str(order_id) if order_id else None,
                "channel": channel,
                "sent_at": now.isoformat(),
            },
        )
        await db.commit()

        log.info("nps_service.survey_sent", survey_id=str(survey_id), channel=channel)
        return {
            "survey_id": str(survey_id),
            "customer_id": str(customer_id),
            "store_id": str(store_id),
            "channel": channel,
            "sent_at": now.isoformat(),
        }

    async def record_response(
        self,
        tenant_id: uuid.UUID,
        survey_id: uuid.UUID,
        nps_score: int,
        feedback_text: str | None,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """记录NPS调查回复

        参数：
          - tenant_id: 租户ID
          - survey_id: 调查ID
          - nps_score: NPS评分(0-10)
          - feedback_text: 可选反馈文本
          - db: 数据库会话
        """
        log = logger.bind(tenant_id=str(tenant_id), survey_id=str(survey_id))

        if nps_score < 0 or nps_score > 10:
            raise ValueError(f"NPS评分必须在0-10之间，收到: {nps_score}")

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        now = datetime.now(tz=timezone.utc)

        # 提取反馈主题标签
        tags = _extract_tags(feedback_text) if feedback_text else []

        # 计算回复时间
        result = await db.execute(
            text("""
                SELECT sent_at FROM nps_surveys
                WHERE id = :survey_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = false
            """),
            {"survey_id": str(survey_id), "tenant_id": str(tenant_id)},
        )
        row = result.fetchone()
        if not row:
            raise ValueError(f"调查不存在: {survey_id}")

        sent_at = row[0]
        response_time_sec = int((now - sent_at).total_seconds()) if sent_at else None

        await db.execute(
            text("""
                UPDATE nps_surveys
                SET nps_score = :nps_score,
                    feedback_text = :feedback_text,
                    tags = :tags::jsonb,
                    responded_at = :responded_at,
                    response_time_sec = :response_time_sec,
                    updated_at = :updated_at
                WHERE id = :survey_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = false
            """),
            {
                "survey_id": str(survey_id),
                "tenant_id": str(tenant_id),
                "nps_score": nps_score,
                "feedback_text": feedback_text,
                "tags": json.dumps(tags, ensure_ascii=False),
                "responded_at": now.isoformat(),
                "response_time_sec": response_time_sec,
                "updated_at": now.isoformat(),
            },
        )
        await db.commit()

        category = "promoter" if nps_score >= 9 else ("detractor" if nps_score <= 6 else "passive")
        log.info(
            "nps_service.response_recorded",
            nps_score=nps_score,
            category=category,
            tags=tags,
        )
        return {
            "survey_id": str(survey_id),
            "nps_score": nps_score,
            "category": category,
            "tags": tags,
            "response_time_sec": response_time_sec,
        }

    async def get_nps_dashboard(
        self,
        tenant_id: uuid.UUID,
        db: AsyncSession,
        store_id: uuid.UUID | None = None,
        days: int = 30,
    ) -> dict[str, Any]:
        """NPS仪表盘：得分、趋势、回复率

        NPS = (推荐者数 / 总回复数 * 100) - (贬损者数 / 总回复数 * 100)

        参数：
          - tenant_id: 租户ID
          - db: 数据库会话
          - store_id: 可选门店筛选
          - days: 统计周期（天）
        """
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        now = datetime.now(tz=timezone.utc)
        period_start = (now - timedelta(days=days)).isoformat()

        store_filter = ""
        params: dict[str, Any] = {
            "tenant_id": str(tenant_id),
            "start": period_start,
            "end": now.isoformat(),
        }
        if store_id:
            store_filter = "AND store_id = :store_id"
            params["store_id"] = str(store_id)

        # 总体统计
        result = await db.execute(
            text(f"""
                SELECT
                    COUNT(*) AS total_sent,
                    COUNT(responded_at) AS total_responded,
                    COUNT(*) FILTER (WHERE is_promoter = true) AS promoters,
                    COUNT(*) FILTER (WHERE is_detractor = true) AS detractors,
                    COUNT(*) FILTER (WHERE nps_score BETWEEN 7 AND 8) AS passives,
                    COALESCE(AVG(nps_score) FILTER (WHERE responded_at IS NOT NULL), 0) AS avg_score,
                    COALESCE(AVG(response_time_sec) FILTER (WHERE response_time_sec IS NOT NULL), 0) AS avg_response_time
                FROM nps_surveys
                WHERE tenant_id = :tenant_id
                  AND sent_at BETWEEN :start AND :end
                  AND is_deleted = false
                  {store_filter}
            """),
            params,
        )
        row = result.fetchone()

        total_sent = int(row[0] or 0)
        total_responded = int(row[1] or 0)
        promoters = int(row[2] or 0)
        detractors = int(row[3] or 0)
        passives = int(row[4] or 0)
        avg_score = float(row[5] or 0)
        avg_response_time = int(row[6] or 0)

        # NPS计算
        if total_responded > 0:
            nps_score = round(
                (promoters / total_responded * 100) - (detractors / total_responded * 100),
                1,
            )
            response_rate = round(total_responded / total_sent * 100, 1) if total_sent > 0 else 0.0
        else:
            nps_score = 0.0
            response_rate = 0.0

        # 周趋势
        trend_result = await db.execute(
            text(f"""
                SELECT
                    DATE_TRUNC('week', sent_at) AS week_start,
                    COUNT(responded_at) AS responded,
                    COUNT(*) FILTER (WHERE is_promoter = true) AS promo,
                    COUNT(*) FILTER (WHERE is_detractor = true) AS detract
                FROM nps_surveys
                WHERE tenant_id = :tenant_id
                  AND sent_at BETWEEN :start AND :end
                  AND is_deleted = false
                  {store_filter}
                GROUP BY week_start
                ORDER BY week_start
            """),
            params,
        )
        trend_rows = trend_result.fetchall()
        trend = []
        for tr in trend_rows:
            resp = int(tr[1] or 0)
            promo = int(tr[2] or 0)
            det = int(tr[3] or 0)
            week_nps = round((promo / resp * 100) - (det / resp * 100), 1) if resp > 0 else 0.0
            trend.append(
                {
                    "date": tr[0].strftime("%Y-%m-%d") if tr[0] else "",
                    "nps_score": week_nps,
                    "responded": resp,
                    "promoters": promo,
                    "detractors": det,
                }
            )

        return {
            "nps_score": nps_score,
            "total_sent": total_sent,
            "total_responded": total_responded,
            "response_rate": response_rate,
            "promoters": promoters,
            "passives": passives,
            "detractors": detractors,
            "avg_score": round(avg_score, 1),
            "avg_response_time_sec": avg_response_time,
            "period_days": days,
            "trend": trend,
        }

    async def get_nps_by_store(
        self,
        tenant_id: uuid.UUID,
        db: AsyncSession,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        """按门店分解NPS

        返回每个门店的NPS得分和回复统计。
        """
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        now = datetime.now(tz=timezone.utc)
        period_start = (now - timedelta(days=days)).isoformat()

        result = await db.execute(
            text("""
                SELECT
                    store_id,
                    COUNT(*) AS total_sent,
                    COUNT(responded_at) AS total_responded,
                    COUNT(*) FILTER (WHERE is_promoter = true) AS promoters,
                    COUNT(*) FILTER (WHERE is_detractor = true) AS detractors,
                    COALESCE(AVG(nps_score) FILTER (WHERE responded_at IS NOT NULL), 0) AS avg_score
                FROM nps_surveys
                WHERE tenant_id = :tenant_id
                  AND sent_at BETWEEN :start AND :end
                  AND is_deleted = false
                GROUP BY store_id
                ORDER BY avg_score DESC
            """),
            {
                "tenant_id": str(tenant_id),
                "start": period_start,
                "end": now.isoformat(),
            },
        )
        rows = result.fetchall()
        stores = []
        for row in rows:
            responded = int(row[2] or 0)
            promo = int(row[3] or 0)
            det = int(row[4] or 0)
            nps = round((promo / responded * 100) - (det / responded * 100), 1) if responded > 0 else 0.0
            stores.append(
                {
                    "store_id": str(row[0]),
                    "nps_score": nps,
                    "total_sent": int(row[1] or 0),
                    "total_responded": responded,
                    "promoters": promo,
                    "detractors": det,
                    "avg_score": round(float(row[5] or 0), 1),
                }
            )
        return stores

    async def get_detractor_list(
        self,
        tenant_id: uuid.UUID,
        db: AsyncSession,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        """获取贬损者列表，用于跟进

        返回评分<=6的客户列表，按评分升序排列（最不满意的优先）。
        """
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        now = datetime.now(tz=timezone.utc)
        period_start = (now - timedelta(days=days)).isoformat()

        result = await db.execute(
            text("""
                SELECT
                    s.id, s.customer_id, s.store_id, s.order_id,
                    s.nps_score, s.feedback_text, s.tags,
                    s.responded_at, s.channel
                FROM nps_surveys s
                WHERE s.tenant_id = :tenant_id
                  AND s.is_detractor = true
                  AND s.responded_at IS NOT NULL
                  AND s.sent_at BETWEEN :start AND :end
                  AND s.is_deleted = false
                ORDER BY s.nps_score ASC, s.responded_at DESC
                LIMIT 100
            """),
            {
                "tenant_id": str(tenant_id),
                "start": period_start,
                "end": now.isoformat(),
            },
        )
        rows = result.fetchall()
        detractors = []
        for row in rows:
            tags = row[6] if isinstance(row[6], list) else json.loads(row[6]) if row[6] else []
            detractors.append(
                {
                    "survey_id": str(row[0]),
                    "customer_id": str(row[1]),
                    "store_id": str(row[2]),
                    "order_id": str(row[3]) if row[3] else None,
                    "nps_score": int(row[4]) if row[4] is not None else None,
                    "feedback_text": row[5],
                    "tags": tags,
                    "responded_at": row[7].isoformat() if row[7] else None,
                    "channel": row[8],
                }
            )
        return detractors
