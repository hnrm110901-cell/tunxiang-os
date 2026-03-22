"""门店健康指数 — 5 维度加权综合评分

迁移自 tunxiang V2.x store_health_service.py
纯函数 + Service 类，可独立运行无 DB 依赖（纯函数部分）。

维度权重：
  营收完成率 30% + 翻台率 20% + 成本率 25% + 客诉率 15% + 人效 10%
"""
from typing import Optional

# ─── 权重配置 ───

WEIGHTS = {
    "revenue_completion": 0.30,
    "table_turnover": 0.20,
    "cost_rate": 0.25,
    "complaint_rate": 0.15,
    "staff_efficiency": 0.10,
}

TURNOVER_TARGET = 2.0          # 翻台率目标：2次/天
STAFF_EFFICIENCY_TARGET = 500  # 人效目标：500元/人/天


# ─── 纯函数：综合评分 ───

def compute_health_score(dimension_scores: dict[str, Optional[float]]) -> float:
    """加权综合评分（缺失维度自动归一化，不拉低分数）

    Args:
        dimension_scores: {"revenue_completion": 85.0, "table_turnover": None, ...}

    Returns:
        0-100 综合健康分
    """
    available = {k: v for k, v in dimension_scores.items() if v is not None}
    if not available:
        return 50.0

    total_weight = sum(WEIGHTS.get(k, 0) for k in available)
    if total_weight <= 0:
        return 50.0

    score = sum(v * WEIGHTS.get(k, 0) for k, v in available.items()) / total_weight
    return round(score, 1)


def classify_health(score: float) -> str:
    """健康度分级

    Returns:
        excellent(≥85) / good(≥70) / warning(≥50) / critical(<50)
    """
    if score >= 85:
        return "excellent"
    if score >= 70:
        return "good"
    if score >= 50:
        return "warning"
    return "critical"


# ─── 纯函数：维度得分计算 ───

def score_revenue_completion(
    actual_fen: int,
    monthly_target_yuan: float,
    days_in_month: int = 30,
) -> Optional[float]:
    """营收完成率得分"""
    if monthly_target_yuan <= 0 or days_in_month <= 0:
        return None
    daily_target_fen = monthly_target_yuan * 100 / days_in_month
    if daily_target_fen <= 0:
        return None
    return min(100.0, actual_fen / daily_target_fen * 100)


def score_table_turnover(distinct_tables_used: int, total_seats: int) -> Optional[float]:
    """翻台率得分"""
    if total_seats <= 0:
        return None
    turns = distinct_tables_used / total_seats
    return min(100.0, turns / TURNOVER_TARGET * 100)


def score_cost_rate(variance_status: Optional[str]) -> Optional[float]:
    """成本率得分（基于偏差状态）"""
    if variance_status is None:
        return None
    mapping = {"ok": 100.0, "warning": 60.0, "critical": 20.0}
    return mapping.get(variance_status, 50.0)


def score_complaint_rate(fail_count: int, total_count: int) -> Optional[float]:
    """客诉率得分：0%投诉=100分，50%投诉=0分"""
    if total_count <= 0:
        return None
    fail_rate = fail_count / total_count
    return max(0.0, 100.0 - fail_rate * 200)


def score_staff_efficiency(revenue_yuan: float, staff_count: int) -> Optional[float]:
    """人效得分"""
    if staff_count <= 0 or revenue_yuan <= 0:
        return None
    rev_per_staff = revenue_yuan / staff_count
    return min(100.0, rev_per_staff / STAFF_EFFICIENCY_TARGET * 100)


def find_weakest_dimension(dimension_scores: dict[str, Optional[float]]) -> Optional[str]:
    """找到最弱维度"""
    available = {k: v for k, v in dimension_scores.items() if v is not None}
    if not available:
        return None
    return min(available, key=available.get)
