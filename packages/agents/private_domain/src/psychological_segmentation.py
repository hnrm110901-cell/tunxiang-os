"""
心理距离分层模块 — B1·方向一
基于《思考，快与慢》解释水平理论 + 《怪诞行为学》锚定效应

核心洞见：
- 传统 RFM 只描述"顾客做了什么"，解释水平理论揭示"顾客在哪个心理距离"
- recency_days 相对于 avg_visit_interval 的比值（而非绝对天数）才是真正的距离度量
- 不同心理距离对应完全不同的触达内容策略（错配会适得其反）
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional


# ── 心理距离枚举 ──────────────────────────────────────────────────────────────


class PsychologicalDistance(str, Enum):
    NEAR_SITUATIONAL   = "near_situational"    # 比平时晚一点，只是情境未触发
    NEAR_HABIT_BREAK   = "near_habit_break"    # 打破了一次习惯循环
    MID_FADING         = "mid_fading"          # 品牌印象开始模糊
    FAR_ABSTRACT       = "far_abstract"        # 品牌已变成抽象概念
    LOST_RECONSTRUCTED = "lost_reconstructed"  # 需要重新建立整个价值认知


# ── 触达策略矩阵 ──────────────────────────────────────────────────────────────
# 理论来源：解释水平理论（抽象vs具体）+ 锚定效应（高折扣锚会拉低价值感知）

DISTANCE_STRATEGY: Dict[str, Dict[str, str]] = {
    PsychologicalDistance.NEAR_SITUATIONAL: {
        "description": "近5天内有消费相关搜索/浏览，只是没来",
        "wrong_action": "发优惠券（不需要让利）",
        "right_action":  "发「上次您点的XX今天有新做法」",
        "principle":     "具体情境激活，无需让利",
        "content_level": "concrete",   # 具体化内容
    },
    PsychologicalDistance.NEAR_HABIT_BREAK: {
        "description": "5-14天，打破了固有习惯节奏",
        "wrong_action": "问「您有什么不满意」（引入负面认知）",
        "right_action":  "发「您的老位置已为您保留」",
        "principle":     "归属感，不引入负面认知",
        "content_level": "concrete",
    },
    PsychologicalDistance.MID_FADING: {
        "description": "15-30天，品牌印象开始模糊",
        "wrong_action": "发品牌介绍（抽象，效果差）",
        "right_action":  "发「您认识的张厨师新研发了XX」",
        "principle":     "用具体的人而非品牌降低心理距离",
        "content_level": "concrete_person",  # 具体的人
    },
    PsychologicalDistance.FAR_ABSTRACT: {
        "description": "30-60天，品牌已变成「那家店」的抽象概念",
        "wrong_action": "高折扣轰炸（锚定效应反噬，顾客只有折扣才来）",
        "right_action":  "发带场景图的「这个秋天适合一家人」",
        "principle":     "重建具体价值联想，避免折扣锚点",
        "content_level": "scene_imagery",
    },
    PsychologicalDistance.LOST_RECONSTRUCTED: {
        "description": "60天+，需要重新建立整个价值认知",
        "wrong_action": "任何文字内容（解释水平太高，文字无效）",
        "right_action":  "线下员工一对一私信 + 超高价值首单",
        "principle":     "重新建立关系，Agent退出自动化",
        "content_level": "human_intervention",  # 人工介入
    },
}


# ── 核心分类函数 ──────────────────────────────────────────────────────────────


def classify_psychological_distance(
    recency_days: int,
    avg_visit_interval: float,
    visit_regularity: float = 0.5,
    last_interaction_days: Optional[int] = None,
) -> PsychologicalDistance:
    """
    根据解释水平理论计算顾客心理距离。

    关键区别：使用 recency_days / avg_visit_interval 的比值（ratio），
    而不是固定的30/60/90天阈值——相同的缺席天数对不同消费频率的顾客含义截然不同。

    Args:
        recency_days:          距上次消费的天数
        avg_visit_interval:    历史平均消费间隔（天），至少1天
        visit_regularity:      历史访问规律性 0-1（越高越有固定节奏）
        last_interaction_days: 最后一次品牌互动距今天数（含推送打开、浏览等非消费行为）
                               None 表示未知

    Returns:
        PsychologicalDistance 枚举值
    """
    interval = max(avg_visit_interval, 1.0)
    ratio = recency_days / interval

    # 如果最近有非消费互动（打开推送/浏览菜单），心理距离更近
    if last_interaction_days is not None and last_interaction_days <= recency_days:
        # 互动信号降低一档距离（ratio 折扣）
        ratio *= 0.7

    if ratio < 1.2:
        return PsychologicalDistance.NEAR_SITUATIONAL
    elif ratio < 2.0:
        return PsychologicalDistance.NEAR_HABIT_BREAK
    elif ratio < 3.5:
        return PsychologicalDistance.MID_FADING
    elif ratio < 6.0:
        return PsychologicalDistance.FAR_ABSTRACT
    else:
        return PsychologicalDistance.LOST_RECONSTRUCTED


def get_distance_strategy(distance: PsychologicalDistance) -> Dict[str, Any]:
    """返回对应心理距离的触达策略字典（含 right_action / principle / content_level）。"""
    return DISTANCE_STRATEGY[distance]


def classify_with_strategy(
    recency_days: int,
    avg_visit_interval: float,
    visit_regularity: float = 0.5,
    last_interaction_days: Optional[int] = None,
) -> Dict[str, Any]:
    """
    一步返回心理距离分类 + 触达策略。

    Returns:
        {
            "distance": PsychologicalDistance,
            "strategy": { right_action, principle, content_level, ... }
        }
    """
    distance = classify_psychological_distance(
        recency_days, avg_visit_interval, visit_regularity, last_interaction_days
    )
    return {
        "distance": distance,
        "strategy": get_distance_strategy(distance),
    }
