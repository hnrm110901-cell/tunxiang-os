"""流失预测评分引擎 — V1 领域专家权重模型

输入信号：
  - Recency: 距最后下单天数
  - Frequency trend: 近30天 vs 前30天到店频次变化率
  - Monetary trend: 近30天 vs 前30天消费金额变化率
  - Cancel rate: 近90天取消订单比率
  - Complaint count: 近90天投诉/差评数
  - NPS score: 最近一次NPS评分（如有）

输出：
  - score: 0-100（越高越可能流失）
  - risk_tier: warm(40-59) / urgent(60-79) / critical(80+)
  - root_cause: price/taste/competition/moved/seasonal/service/unknown
  - signals: 各维度数值快照

V1不依赖ML训练，使用领域专家权重。V2将用prediction_models表存储训练模型。
"""

import json
import uuid
from typing import Any, Optional

import structlog
from sqlalchemy import text

log = structlog.get_logger(__name__)


class ChurnScorerError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# V1 专家权重配置
# ---------------------------------------------------------------------------

WEIGHTS = {
    "recency": 0.30,  # 距最后下单天数（最重要）
    "frequency_trend": 0.20,  # 到店频次变化
    "monetary_trend": 0.15,  # 消费金额变化
    "cancel_rate": 0.15,  # 取消率
    "complaint_count": 0.10,  # 投诉数
    "nps_detractor": 0.10,  # NPS贬损者
}

# 天数→评分映射（线性插值）
RECENCY_SCORE_MAP = [
    (7, 0),  # 7天内到店 → 0分
    (14, 10),  # 14天 → 10分
    (30, 30),  # 30天 → 30分
    (60, 60),  # 60天 → 60分
    (90, 80),  # 90天 → 80分
    (180, 95),  # 180天 → 95分
    (365, 100),  # 365天 → 100分
]

# 根因判定规则
ROOT_CAUSE_RULES = [
    ("complaint_count", 2, "service"),  # 投诉≥2次 → 服务问题
    ("monetary_trend", -0.5, "price"),  # 消费额降50%+ → 价格敏感
    ("frequency_trend", -0.7, "taste"),  # 频次降70%+ → 口味变化
    ("cancel_rate", 0.3, "service"),  # 取消率>30% → 服务问题
]


class ChurnScorer:
    """流失预测评分引擎"""

    async def score_customer(
        self,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """为单个客户计算流失评分"""
        signals = await self._collect_signals(tenant_id, customer_id, db)
        score = self._calculate_score(signals)
        risk_tier = self._classify_tier(score)
        root_cause = self._infer_root_cause(signals)

        # 获取上次评分
        prev = await self._get_previous_score(tenant_id, customer_id, db)
        previous_score = prev["score"] if prev else None
        score_delta = score - previous_score if previous_score is not None else 0

        # 写入churn_scores
        score_id = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO churn_scores (
                    id, tenant_id, customer_id, score, risk_tier,
                    signals, root_cause, scored_at,
                    previous_score, score_delta, model_version
                ) VALUES (
                    :id, :tenant_id, :customer_id, :score, :risk_tier,
                    :signals::jsonb, :root_cause, NOW(),
                    :previous_score, :score_delta, 'v1_expert_weights'
                )
            """),
            {
                "id": str(score_id),
                "tenant_id": str(tenant_id),
                "customer_id": str(customer_id),
                "score": score,
                "risk_tier": risk_tier,
                "signals": json.dumps(signals),
                "root_cause": root_cause,
                "previous_score": previous_score,
                "score_delta": score_delta,
            },
        )

        log.info(
            "customer_scored",
            customer_id=str(customer_id),
            score=score,
            risk_tier=risk_tier,
            root_cause=root_cause,
            delta=score_delta,
        )

        return {
            "score_id": str(score_id),
            "customer_id": str(customer_id),
            "score": score,
            "risk_tier": risk_tier,
            "root_cause": root_cause,
            "signals": signals,
            "previous_score": previous_score,
            "score_delta": score_delta,
        }

    async def batch_score(
        self,
        tenant_id: uuid.UUID,
        db: Any,
        *,
        limit: int = 5000,
    ) -> dict:
        """批量评分所有活跃会员"""
        # 获取有订单记录的会员列表
        result = await db.execute(
            text("""
                SELECT DISTINCT m.id AS customer_id
                FROM members m
                WHERE m.tenant_id = :tenant_id
                  AND m.is_deleted = FALSE
                  AND m.lifecycle_stage != 'new'
                ORDER BY m.id
                LIMIT :limit
            """),
            {"tenant_id": str(tenant_id), "limit": limit},
        )
        customer_ids = [row["customer_id"] for row in result.mappings().all()]

        stats = {"total": len(customer_ids), "scored": 0, "errors": 0, "warm": 0, "urgent": 0, "critical": 0}

        for cid in customer_ids:
            try:
                r = await self.score_customer(tenant_id, uuid.UUID(str(cid)), db)
                stats["scored"] += 1
                stats[r["risk_tier"]] += 1
            except (OSError, RuntimeError, ValueError) as exc:
                stats["errors"] += 1
                log.error("batch_score_error", customer_id=str(cid), error=str(exc))

        log.info("batch_score_finished", tenant_id=str(tenant_id), **stats)
        return stats

    async def get_risk_dashboard(
        self,
        tenant_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """获取流失风险大盘"""
        result = await db.execute(
            text("""
                SELECT
                    risk_tier,
                    COUNT(*) AS count,
                    AVG(score) AS avg_score,
                    COUNT(*) FILTER (WHERE journey_triggered_at IS NOT NULL) AS intervened
                FROM churn_scores cs
                INNER JOIN (
                    SELECT customer_id, MAX(scored_at) AS latest
                    FROM churn_scores
                    WHERE tenant_id = :tenant_id AND is_deleted = FALSE
                    GROUP BY customer_id
                ) latest_cs ON cs.customer_id = latest_cs.customer_id AND cs.scored_at = latest_cs.latest
                WHERE cs.tenant_id = :tenant_id AND cs.is_deleted = FALSE
                GROUP BY risk_tier
            """),
            {"tenant_id": str(tenant_id)},
        )
        tiers = {}
        total = 0
        for row in result.mappings().all():
            tier = row["risk_tier"]
            count = row["count"]
            tiers[tier] = {
                "count": count,
                "avg_score": round(float(row["avg_score"] or 0), 1),
                "intervened": row["intervened"],
            }
            total += count

        return {
            "total_scored": total,
            "tiers": tiers,
            "intervention_rate": round(sum(t["intervened"] for t in tiers.values()) / max(total, 1) * 100, 1),
        }

    # ===================================================================
    # 私有方法
    # ===================================================================

    async def _collect_signals(
        self,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """从会员表和订单表收集评分信号"""
        result = await db.execute(
            text("""
                SELECT
                    EXTRACT(DAY FROM NOW() - MAX(o.created_at))::int AS days_since_last,
                    COUNT(*) FILTER (WHERE o.created_at > NOW() - INTERVAL '30 days') AS orders_30d,
                    COUNT(*) FILTER (WHERE o.created_at > NOW() - INTERVAL '60 days'
                                     AND o.created_at <= NOW() - INTERVAL '30 days') AS orders_prev_30d,
                    COALESCE(SUM(o.total_amount_fen) FILTER (WHERE o.created_at > NOW() - INTERVAL '30 days'), 0) AS spend_30d_fen,
                    COALESCE(SUM(o.total_amount_fen) FILTER (WHERE o.created_at > NOW() - INTERVAL '60 days'
                                     AND o.created_at <= NOW() - INTERVAL '30 days'), 0) AS spend_prev_30d_fen,
                    COUNT(*) FILTER (WHERE o.status = 'cancelled'
                                     AND o.created_at > NOW() - INTERVAL '90 days') AS cancelled_90d,
                    COUNT(*) FILTER (WHERE o.created_at > NOW() - INTERVAL '90 days') AS total_90d
                FROM orders o
                WHERE o.tenant_id = :tenant_id
                  AND o.customer_id = :customer_id
                  AND o.is_deleted = FALSE
            """),
            {"tenant_id": str(tenant_id), "customer_id": str(customer_id)},
        )
        row = result.mappings().first()

        if not row or row["days_since_last"] is None:
            return {
                "days_since_last": 999,
                "frequency_trend": -1.0,
                "monetary_trend": -1.0,
                "cancel_rate": 0.0,
                "complaint_count": 0,
                "nps_score": None,
            }

        orders_30d = row["orders_30d"] or 0
        orders_prev = row["orders_prev_30d"] or 0
        freq_trend = (orders_30d - orders_prev) / max(orders_prev, 1)

        spend_30d = row["spend_30d_fen"] or 0
        spend_prev = row["spend_prev_30d_fen"] or 0
        money_trend = (spend_30d - spend_prev) / max(spend_prev, 1)

        total_90d = row["total_90d"] or 0
        cancelled = row["cancelled_90d"] or 0
        cancel_rate = cancelled / max(total_90d, 1)

        # 查询投诉数（从order_reviews或public_opinion_mentions）
        complaint_result = await db.execute(
            text("""
                SELECT COUNT(*) FROM order_reviews
                WHERE tenant_id = :tenant_id
                  AND customer_id = :customer_id
                  AND overall_rating <= 2
                  AND created_at > NOW() - INTERVAL '90 days'
                  AND is_deleted = FALSE
            """),
            {"tenant_id": str(tenant_id), "customer_id": str(customer_id)},
        )
        complaint_count = complaint_result.scalar() or 0

        return {
            "days_since_last": row["days_since_last"] or 999,
            "frequency_trend": round(freq_trend, 3),
            "monetary_trend": round(money_trend, 3),
            "cancel_rate": round(cancel_rate, 3),
            "complaint_count": complaint_count,
            "nps_score": None,  # V2: integrate NPS
            "orders_30d": orders_30d,
            "orders_prev_30d": orders_prev,
            "spend_30d_fen": spend_30d,
            "spend_prev_30d_fen": spend_prev,
        }

    def _calculate_score(self, signals: dict) -> int:
        """加权计算流失评分(0-100)"""
        # Recency分数
        days = signals.get("days_since_last", 999)
        recency_score = self._interpolate_recency(days)

        # Frequency trend分数 (趋势越负=越可能流失)
        freq = signals.get("frequency_trend", 0)
        freq_score = max(0, min(100, 50 - freq * 50))  # -1.0→100, 0→50, +1.0→0

        # Monetary trend分数
        money = signals.get("monetary_trend", 0)
        money_score = max(0, min(100, 50 - money * 50))

        # Cancel rate分数
        cancel = signals.get("cancel_rate", 0)
        cancel_score = min(100, cancel * 200)  # 50%取消率→100分

        # Complaint分数
        complaints = signals.get("complaint_count", 0)
        complaint_score = min(100, complaints * 40)  # 2.5次→100分

        # NPS贬损者分数
        nps = signals.get("nps_score")
        nps_score = 80 if (nps is not None and nps <= 6) else 0

        # 加权求和
        total = (
            WEIGHTS["recency"] * recency_score
            + WEIGHTS["frequency_trend"] * freq_score
            + WEIGHTS["monetary_trend"] * money_score
            + WEIGHTS["cancel_rate"] * cancel_score
            + WEIGHTS["complaint_count"] * complaint_score
            + WEIGHTS["nps_detractor"] * nps_score
        )

        return max(0, min(100, int(round(total))))

    @staticmethod
    def _interpolate_recency(days: int) -> float:
        """线性插值：天数→Recency评分"""
        if days <= RECENCY_SCORE_MAP[0][0]:
            return RECENCY_SCORE_MAP[0][1]
        for i in range(1, len(RECENCY_SCORE_MAP)):
            d1, s1 = RECENCY_SCORE_MAP[i - 1]
            d2, s2 = RECENCY_SCORE_MAP[i]
            if days <= d2:
                ratio = (days - d1) / (d2 - d1)
                return s1 + ratio * (s2 - s1)
        return RECENCY_SCORE_MAP[-1][1]

    @staticmethod
    def _classify_tier(score: int) -> str:
        if score >= 80:
            return "critical"
        if score >= 60:
            return "urgent"
        if score >= 40:
            return "warm"
        return "warm"  # <40 still classified but low priority

    @staticmethod
    def _infer_root_cause(signals: dict) -> str:
        """基于信号推断流失根因"""
        for signal_key, threshold, cause in ROOT_CAUSE_RULES:
            val = signals.get(signal_key, 0)
            if (
                signal_key in ("complaint_count",)
                and val >= threshold
                or signal_key in ("monetary_trend", "frequency_trend")
                and val <= threshold
                or signal_key == "cancel_rate"
                and val >= threshold
            ):
                return cause
        return "unknown"

    async def _get_previous_score(
        self,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        db: Any,
    ) -> Optional[dict]:
        result = await db.execute(
            text("""
                SELECT score, risk_tier, scored_at
                FROM churn_scores
                WHERE tenant_id = :tenant_id
                  AND customer_id = :customer_id
                  AND is_deleted = FALSE
                ORDER BY scored_at DESC
                LIMIT 1
            """),
            {"tenant_id": str(tenant_id), "customer_id": str(customer_id)},
        )
        row = result.mappings().first()
        return dict(row) if row else None
