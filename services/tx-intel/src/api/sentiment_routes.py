"""
评价情感分析 API

POST /api/v1/intel/sentiment/analyze             — 分析评价文本情感
GET  /api/v1/intel/sentiment/dashboard/{store_id} — 门店评价仪表盘
GET  /api/v1/intel/sentiment/alerts               — 差评预警

情感分析使用关键词匹配实现（不依赖外部 NLP 库）。
"""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/intel/sentiment", tags=["sentiment"])


# ─── 情感关键词词典 ──────────────────────────────────────────────────

POSITIVE_KEYWORDS: dict[str, float] = {
    "好吃": 0.8, "美味": 0.9, "新鲜": 0.7, "推荐": 0.7, "满意": 0.8,
    "干净": 0.6, "热情": 0.7, "速度快": 0.7, "服务好": 0.8, "环境好": 0.7,
    "分量足": 0.7, "实惠": 0.7, "味道好": 0.8, "正宗": 0.8, "惊喜": 0.9,
    "超值": 0.8, "舒适": 0.6, "贴心": 0.7, "回头客": 0.8, "必点": 0.8,
    "五星": 0.9, "非常好": 0.9, "太棒了": 0.9, "喜欢": 0.7, "入味": 0.7,
    "嫩": 0.6, "酥脆": 0.7, "香": 0.6, "地道": 0.7, "下次还来": 0.8,
}

NEGATIVE_KEYWORDS: dict[str, float] = {
    "难吃": -0.9, "太咸": -0.7, "太淡": -0.6, "不新鲜": -0.8, "变质": -0.9,
    "服务差": -0.8, "态度差": -0.8, "上菜慢": -0.7, "等太久": -0.7, "脏": -0.8,
    "贵": -0.5, "太贵": -0.7, "分量少": -0.7, "不卫生": -0.9, "拉肚子": -0.9,
    "食物中毒": -1.0, "虫": -0.9, "头发": -0.9, "苍蝇": -0.9, "过期": -0.9,
    "冷了": -0.6, "凉了": -0.6, "油腻": -0.5, "不好吃": -0.8, "失望": -0.8,
    "投诉": -0.8, "退款": -0.7, "差评": -0.9, "再也不来": -0.9, "踩雷": -0.8,
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


# ─── Mock 数据 ────────────────────────────────────────────────────────

def _mock_dashboard(store_id: str) -> dict[str, Any]:
    return {
        "store_id": store_id,
        "period": "last_30_days",
        "total_reviews": 286,
        "positive_rate": 0.82,
        "neutral_rate": 0.11,
        "negative_rate": 0.07,
        "avg_sentiment_score": 0.58,
        "top_praise_keywords": [
            {"keyword": "好吃", "count": 98},
            {"keyword": "服务好", "count": 72},
            {"keyword": "环境好", "count": 56},
            {"keyword": "分量足", "count": 45},
            {"keyword": "新鲜", "count": 38},
        ],
        "top_complaint_keywords": [
            {"keyword": "上菜慢", "count": 12},
            {"keyword": "太咸", "count": 8},
            {"keyword": "分量少", "count": 5},
            {"keyword": "服务差", "count": 3},
        ],
        "trend": [
            {"date": "2026-03-10", "score": 0.55, "count": 12},
            {"date": "2026-03-17", "score": 0.60, "count": 15},
            {"date": "2026-03-24", "score": 0.52, "count": 11},
            {"date": "2026-03-31", "score": 0.62, "count": 14},
        ],
        "competitor_compare": {
            "self_score": 0.58,
            "category_avg": 0.52,
            "rank_in_area": 3,
            "total_in_area": 18,
        },
        "_is_mock": True,
    }


def _mock_alerts() -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    return [
        {
            "id": "alert-001",
            "store_id": "S001",
            "platform": "meituan",
            "rating": 1,
            "content": "等了四十分钟才上菜，而且菜都凉了，服务员态度也不好，失望",
            "sentiment_score": -0.82,
            "issues": ["等待时间", "出品质量", "服务态度"],
            "occurred_at": (now - timedelta(hours=2)).isoformat(),
            "status": "pending",
        },
        {
            "id": "alert-002",
            "store_id": "S001",
            "platform": "dianping",
            "rating": 2,
            "content": "菜品味道一般，太咸了，分量也比以前少了",
            "sentiment_score": -0.65,
            "issues": ["出品质量", "性价比"],
            "occurred_at": (now - timedelta(hours=5)).isoformat(),
            "status": "pending",
        },
    ]


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
        results.append({
            "platform": review.platform,
            "content": review.content[:100],  # 截取前100字
            "rating": review.rating,
            **analysis,
        })
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
) -> dict:
    """门店评价仪表盘：好评率/差评关键词/趋势/竞对对比"""
    # Phase 1: 返回 mock 数据结构，待 sentiment_cache 表接入后替换
    dashboard = _mock_dashboard(store_id)
    dashboard["period"] = f"last_{days}_days"
    return {"ok": True, "data": dashboard}


@router.get("/alerts")
async def get_sentiment_alerts(
    store_id: str | None = Query(None, description="门店ID，空=全部"),
    status: str = Query("pending", description="pending/handled/dismissed"),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
) -> dict:
    """差评预警：新增 1-2 星评价实时推送"""
    # Phase 1: 返回 mock 数据，待实时评价采集管道接入后替换
    alerts = _mock_alerts()
    if store_id:
        alerts = [a for a in alerts if a.get("store_id") == store_id]
    if status:
        alerts = [a for a in alerts if a.get("status") == status]

    return {
        "ok": True,
        "data": {
            "alerts": alerts,
            "total": len(alerts),
            "pending_count": sum(1 for a in alerts if a.get("status") == "pending"),
            "_is_mock": True,
        },
    }
