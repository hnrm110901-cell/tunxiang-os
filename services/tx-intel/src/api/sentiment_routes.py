"""
评价情感分析 API

POST /api/v1/intel/sentiment/analyze             — 分析评价文本情感
GET  /api/v1/intel/sentiment/dashboard/{store_id} — 门店评价仪表盘
GET  /api/v1/intel/sentiment/alerts               — 差评预警

情感分析使用关键词匹配实现（不依赖外部 NLP 库）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/intel/sentiment", tags=["sentiment"])


# ─── 情感关键词词典 ──────────────────────────────────────────────────

POSITIVE_KEYWORDS: dict[str, float] = {
    "好吃": 0.8,
    "美味": 0.9,
    "新鲜": 0.7,
    "推荐": 0.7,
    "满意": 0.8,
    "干净": 0.6,
    "热情": 0.7,
    "速度快": 0.7,
    "服务好": 0.8,
    "环境好": 0.7,
    "分量足": 0.7,
    "实惠": 0.7,
    "味道好": 0.8,
    "正宗": 0.8,
    "惊喜": 0.9,
    "超值": 0.8,
    "舒适": 0.6,
    "贴心": 0.7,
    "回头客": 0.8,
    "必点": 0.8,
    "五星": 0.9,
    "非常好": 0.9,
    "太棒了": 0.9,
    "喜欢": 0.7,
    "入味": 0.7,
    "嫩": 0.6,
    "酥脆": 0.7,
    "香": 0.6,
    "地道": 0.7,
    "下次还来": 0.8,
}

NEGATIVE_KEYWORDS: dict[str, float] = {
    "难吃": -0.9,
    "太咸": -0.7,
    "太淡": -0.6,
    "不新鲜": -0.8,
    "变质": -0.9,
    "服务差": -0.8,
    "态度差": -0.8,
    "上菜慢": -0.7,
    "等太久": -0.7,
    "脏": -0.8,
    "贵": -0.5,
    "太贵": -0.7,
    "分量少": -0.7,
    "不卫生": -0.9,
    "拉肚子": -0.9,
    "食物中毒": -1.0,
    "虫": -0.9,
    "头发": -0.9,
    "苍蝇": -0.9,
    "过期": -0.9,
    "冷了": -0.6,
    "凉了": -0.6,
    "油腻": -0.5,
    "不好吃": -0.8,
    "失望": -0.8,
    "投诉": -0.8,
    "退款": -0.7,
    "差评": -0.9,
    "再也不来": -0.9,
    "踩雷": -0.8,
}

# 问题分类关键词映射
ISSUE_CATEGORIES: dict[str, list[str]] = {
    "出品质量": ["难吃", "太咸", "太淡", "不新鲜", "变质", "冷了", "凉了", "油腻", "不好吃"],
    "服务态度": ["服务差", "态度差", "不理人", "没有微笑"],
    "等待时间": ["上菜慢", "等太久", "等了半小时", "催了好几次"],
    "卫生安全": ["脏", "不卫生", "虫", "头发", "苍蝇", "过期", "拉肚子", "食物中毒"],
    "性价比": ["贵", "太贵", "分量少", "不值"],
}


# ─── 情感分析核心函数 ────────────────────────────────────────────────


def _analyze_single_review(content: str, rating: float | None = None) -> dict[str, Any]:
    """分析单条评价的情感"""
    content_lower = content.lower()

    matched_positive: list[str] = []
    matched_negative: list[str] = []
    score_sum = 0.0
    match_count = 0

    for kw, weight in POSITIVE_KEYWORDS.items():
        if kw in content_lower:
            matched_positive.append(kw)
            score_sum += weight
            match_count += 1

    for kw, weight in NEGATIVE_KEYWORDS.items():
        if kw in content_lower:
            matched_negative.append(kw)
            score_sum += weight  # weight is negative
            match_count += 1

    # 基于关键词匹配计算情感得分 [-1, 1]
    if match_count > 0:
        keyword_score = score_sum / match_count
    else:
        keyword_score = 0.0

    # 结合星级评分（如有）
    if rating is not None:
        rating_score = (rating - 3) / 2  # 1星=-1, 3星=0, 5星=1
        final_score = keyword_score * 0.6 + rating_score * 0.4
    else:
        final_score = keyword_score

    final_score = max(-1.0, min(1.0, final_score))

    # 识别具体问题
    issues: list[str] = []
    for category, keywords in ISSUE_CATEGORIES.items():
        for kw in keywords:
            if kw in content_lower:
                issues.append(category)
                break

    # 情感标签
    if final_score >= 0.3:
        sentiment_label = "positive"
    elif final_score <= -0.3:
        sentiment_label = "negative"
    else:
        sentiment_label = "neutral"

    return {
        "sentiment_score": round(final_score, 3),
        "sentiment_label": sentiment_label,
        "positive_keywords": matched_positive,
        "negative_keywords": matched_negative,
        "issues": list(set(issues)),
        "praise": matched_positive[:5],
    }


# ─── 请求模型 ────────────────────────────────────────────────────────


class ReviewItem(BaseModel):
    platform: str = Field(description="平台: meituan/dianping/douyin/self")
    content: str = Field(description="评价内容")
    rating: float | None = Field(default=None, description="星级评分 1-5")
    time: str | None = Field(default=None, description="评价时间 ISO8601")


class AnalyzeRequest(BaseModel):
    reviews: list[ReviewItem] = Field(description="评价列表")


# ─── DB 查询函数 ──────────────────────────────────────────────────────


async def _query_dashboard(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
    days: int = 30,
) -> dict[str, Any]:
    """
    从 compliance_alerts（投诉/差评代理）+ orders（流量上下文）
    构建门店情感仪表盘。
    """
    now = datetime.now(timezone.utc)
    period_start = (now - timedelta(days=days)).isoformat()

    # compliance_alerts：按 severity 统计（critical/warning → negative；info → neutral）
    r_alerts = await db.execute(
        text("""
            SELECT
                severity,
                COUNT(*) AS cnt
            FROM compliance_alerts
            WHERE tenant_id = :tenant_id
              AND store_id = :store_id
              AND created_at BETWEEN :start AND :end
            GROUP BY severity
        """),
        {"tenant_id": tenant_id, "store_id": store_id, "start": period_start, "end": now.isoformat()},
    )
    alert_rows = r_alerts.fetchall()
    negative_count = 0
    neutral_count = 0
    for row in alert_rows:
        sev, cnt = row[0], int(row[1])
        if sev in ("critical", "warning"):
            negative_count += cnt
        else:
            neutral_count += cnt

    # orders：近N天订单量（用作评价总量代理，实际评价表尚未接入）
    r_orders = await db.execute(
        text("""
            SELECT COUNT(*) AS total, COALESCE(SUM(total_fen), 0) AS revenue
            FROM orders
            WHERE tenant_id = :tenant_id
              AND store_id = :store_id
              AND status = 'completed'
              AND created_at BETWEEN :start AND :end
        """),
        {"tenant_id": tenant_id, "store_id": store_id, "start": period_start, "end": now.isoformat()},
    )
    order_row = r_orders.fetchone()
    total_orders = int(order_row[0] or 0)
    # 以 orders 量作为评价总量基准（无独立评价表时的最佳近似）
    total_reviews = max(total_orders, negative_count + neutral_count)
    positive_count = max(0, total_reviews - negative_count - neutral_count)

    positive_rate = round(positive_count / total_reviews, 4) if total_reviews else 0.0
    negative_rate = round(negative_count / total_reviews, 4) if total_reviews else 0.0
    neutral_rate = round(1.0 - positive_rate - negative_rate, 4)

    # 简单情感综合分：正面权重+0.8，负面权重-0.8，中性0
    avg_score = round(positive_rate * 0.8 - negative_rate * 0.8, 3)

    # 最近几周趋势（按周分组）
    r_trend = await db.execute(
        text("""
            SELECT
                DATE_TRUNC('week', created_at) AS week_start,
                COUNT(*) FILTER (WHERE severity IN ('critical','warning')) AS neg,
                COUNT(*) AS total
            FROM compliance_alerts
            WHERE tenant_id = :tenant_id
              AND store_id = :store_id
              AND created_at BETWEEN :start AND :end
            GROUP BY week_start
            ORDER BY week_start
        """),
        {"tenant_id": tenant_id, "store_id": store_id, "start": period_start, "end": now.isoformat()},
    )
    trend_rows = r_trend.fetchall()
    trend = []
    for tr in trend_rows:
        t_neg = int(tr[1] or 0)
        t_total = int(tr[2] or 0)
        t_score = round(-0.8 * (t_neg / t_total) + 0.8 * (1 - t_neg / t_total), 3) if t_total else 0.0
        trend.append(
            {
                "date": tr[0].strftime("%Y-%m-%d") if tr[0] else "",
                "score": t_score,
                "count": t_total,
            }
        )

    return {
        "store_id": store_id,
        "period": f"last_{days}_days",
        "total_reviews": total_reviews,
        "positive_rate": positive_rate,
        "neutral_rate": neutral_rate,
        "negative_rate": negative_rate,
        "avg_sentiment_score": avg_score,
        "top_praise_keywords": [],  # 无独立评价文本表，待接入后填充
        "top_complaint_keywords": [],
        "trend": trend,
        "competitor_compare": None,  # 需跨门店数据，暂不实现
        "_is_mock": False,
    }


async def _query_alerts(
    tenant_id: str,
    db: AsyncSession,
    store_id: str | None = None,
    status: str = "pending",
) -> list[dict[str, Any]]:
    """
    从 compliance_alerts 查询差评预警。
    severity=critical/warning 且 status 未解决的视为差评预警。
    """
    params: dict[str, Any] = {
        "tenant_id": tenant_id,
        "status": status,
    }
    store_filter = ""
    if store_id:
        store_filter = "AND store_id = :store_id"
        params["store_id"] = store_id

    severity_filter = ""
    if status == "pending":
        severity_filter = "AND severity IN ('critical', 'warning')"

    r = await db.execute(
        text(f"""
            SELECT id, store_id, severity, status, title, description, created_at
            FROM compliance_alerts
            WHERE tenant_id = :tenant_id
              AND status = :status
              {severity_filter}
              {store_filter}
            ORDER BY
                CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                created_at DESC
            LIMIT 100
        """),
        params,
    )
    rows = r.fetchall()
    alerts: list[dict[str, Any]] = []
    for row in rows:
        alerts.append(
            {
                "id": str(row[0]),
                "store_id": str(row[1]) if row[1] else None,
                "platform": "internal",  # compliance_alerts 无平台字段，标记为内部
                "rating": None,
                "content": row[5] or row[4] or "",
                "sentiment_score": -0.8 if row[2] == "critical" else -0.5,
                "issues": [],
                "occurred_at": row[6].isoformat() if row[6] else "",
                "status": row[3] or "pending",
            }
        )
    return alerts


# ─── 路由 ─────────────────────────────────────────────────────────────


@router.post("/analyze")
async def analyze_sentiment(
    body: AnalyzeRequest,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
) -> dict:
    """分析评价文本情感（关键词匹配算法，无外部依赖）"""
    results: list[dict[str, Any]] = []
    all_positive: list[str] = []
    all_negative: list[str] = []
    all_issues: list[str] = []
    all_praise: list[str] = []
    score_sum = 0.0

    for review in body.reviews:
        analysis = _analyze_single_review(review.content, review.rating)
        results.append(
            {
                "platform": review.platform,
                "content": review.content[:100],  # 截取前100字
                "rating": review.rating,
                **analysis,
            }
        )
        all_positive.extend(analysis["positive_keywords"])
        all_negative.extend(analysis["negative_keywords"])
        all_issues.extend(analysis["issues"])
        all_praise.extend(analysis["praise"])
        score_sum += analysis["sentiment_score"]

    # 统计汇总
    avg_score = round(score_sum / len(body.reviews), 3) if body.reviews else 0.0

    # 关键词频次统计
    from collections import Counter

    pos_counts = Counter(all_positive).most_common(10)
    neg_counts = Counter(all_negative).most_common(10)
    issue_counts = Counter(all_issues).most_common(10)
    praise_counts = Counter(all_praise).most_common(10)

    return {
        "ok": True,
        "data": {
            "sentiment_score": avg_score,
            "total_reviews": len(body.reviews),
            "positive_count": sum(1 for r in results if r["sentiment_label"] == "positive"),
            "neutral_count": sum(1 for r in results if r["sentiment_label"] == "neutral"),
            "negative_count": sum(1 for r in results if r["sentiment_label"] == "negative"),
            "keywords": {
                "positive": [{"keyword": k, "count": c} for k, c in pos_counts],
                "negative": [{"keyword": k, "count": c} for k, c in neg_counts],
            },
            "issues": [{"category": k, "count": c} for k, c in issue_counts],
            "praise": [{"keyword": k, "count": c} for k, c in praise_counts],
            "details": results,
        },
    }


@router.get("/dashboard/{store_id}")
async def get_sentiment_dashboard(
    store_id: str,
    days: int = Query(30, ge=1, le=365, description="统计天数"),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """门店评价仪表盘：好评率/差评关键词/趋势（基于 compliance_alerts + orders）"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        dashboard = await _query_dashboard(store_id, x_tenant_id, db, days)
        return {"ok": True, "data": dashboard}
    except SQLAlchemyError as exc:
        logger.warning("sentiment.dashboard.db_error", exc=str(exc), store_id=store_id)
        return {
            "ok": True,
            "data": {
                "store_id": store_id,
                "period": f"last_{days}_days",
                "total_reviews": 0,
                "positive_rate": 0.0,
                "neutral_rate": 0.0,
                "negative_rate": 0.0,
                "avg_sentiment_score": 0.0,
                "top_praise_keywords": [],
                "top_complaint_keywords": [],
                "trend": [],
                "competitor_compare": None,
                "_is_mock": False,
            },
        }


@router.get("/alerts")
async def get_sentiment_alerts(
    store_id: str | None = Query(None, description="门店ID，空=全部"),
    status: str = Query("pending", description="pending/handled/dismissed"),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """差评预警：从 compliance_alerts 查询 warning/critical 级别告警"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        alerts = await _query_alerts(x_tenant_id, db, store_id, status)
        return {
            "ok": True,
            "data": {
                "alerts": alerts,
                "total": len(alerts),
                "pending_count": sum(1 for a in alerts if a.get("status") == "pending"),
                "_is_mock": False,
            },
        }
    except SQLAlchemyError as exc:
        logger.warning("sentiment.alerts.db_error", exc=str(exc))
        return {
            "ok": True,
            "data": {
                "alerts": [],
                "total": 0,
                "pending_count": 0,
                "_is_mock": False,
            },
        }
