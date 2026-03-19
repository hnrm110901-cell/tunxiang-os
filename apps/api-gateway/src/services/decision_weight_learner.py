"""
决策权重在线学习器（Online Weight Learner）

解决的问题：
  decision_priority_engine 的权重 (0.40/0.30/0.20/0.10) 是硬编码常量，
  系统永远不会从执行反馈中学习。本模块实现了：

  每次决策执行后 → 根据"预期收益 vs 实际收益"的偏差 →
  用策略梯度思想更新各维度权重 → 门店专属权重逐渐收敛到"最适合该门店的"优先级策略。

算法：Policy Gradient + EMA（无需 GPU，适合在线单样本更新）

  设决策的四维归一化分数：F, U, C, E ∈ [0,1]
  当前权重：W = {financial, urgency, confidence, execution}
  执行结果：accuracy_ratio = actual_impact / expected_saving (outcome调整后)

  credit_i = W_i * score_i                   # 维度 i 对决策分的贡献
  advantage = accuracy_ratio - 1.0           # 超出/低于预期的幅度
  gradient_i = advantage * score_i           # 高分维度承担更多credit/blame
  W_new_i = W_i + lr * gradient_i            # 梯度步进
  → normalize(clip(W_new, 0.05, 0.60))       # 归一化 + 截断

优先级：门店专属权重 > 全局权重 > 硬编码默认值
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.weight_learning import DecisionWeightConfig

logger = structlog.get_logger()

# ── 超参数 ────────────────────────────────────────────────────────────────────
LEARNING_RATE   = 0.08     # 每步更新幅度（偏小以保证稳定）
WEIGHT_MIN      = 0.05     # 单维度权重下限
WEIGHT_MAX      = 0.60     # 单维度权重上限
MAX_HISTORY     = 20       # 最多保留多少条历史快照

# ── 硬编码默认值（系统初始状态，等同原有逻辑）────────────────────────────────
DEFAULT_WEIGHTS: Dict[str, float] = {
    "financial":  0.40,
    "urgency":    0.30,
    "confidence": 0.20,
    "execution":  0.10,
}

# ── 维度字段名映射 ────────────────────────────────────────────────────────────
_DB_FIELDS = {
    "financial":  "w_financial",
    "urgency":    "w_urgency",
    "confidence": "w_confidence",
    "execution":  "w_execution",
}


# ═══════════════════════════════════════════════════════════════════════════════
# 纯函数（无 IO，可独立单元测试）
# ═══════════════════════════════════════════════════════════════════════════════

def compute_accuracy_ratio(
    outcome: str,
    actual_impact_yuan: float,
    expected_saving_yuan: float,
) -> float:
    """
    将执行结果转换为 accuracy_ratio（0.0 – 2.0）。

    - success:  actual / expected，上限 2.0（超额完成不无限奖励）
    - partial:  0.5 × (actual / expected)，再上限 1.0
    - failure:  0.0（完全未兑现）
    """
    base = actual_impact_yuan / max(expected_saving_yuan, 1.0)
    if outcome == "success":
        return min(2.0, base)
    if outcome == "partial":
        return min(1.0, base * 0.5)
    return 0.0   # failure


def compute_gradient(
    weights: Dict[str, float],
    dim_scores_0_100: Dict[str, float],
    accuracy_ratio: float,
) -> Dict[str, float]:
    """
    计算各维度权重的梯度方向（相对分数偏差法）。

    advantage = accuracy_ratio - 1.0（正：超预期，负：不达预期）
    gradient_i = advantage × (score_i - mean_score) / 100

    使用"相对于均值的偏差"而非绝对分数，原因：
      - 若用绝对分数，所有维度梯度同号 → normalize 后相互抵消，权重不收敛
      - 用相对偏差，梯度之和 ≈ 0 → normalize 几乎不改变权重总量
      - 高于均值的维度获得正梯度（成功时增权，失败时减权）
      - 低于均值的维度获得负梯度（成功时减权，失败时增权）

    结果：持续成功的决策中，最"关键"维度的权重逐步上升。
    """
    advantage = accuracy_ratio - 1.0
    scores = [dim_scores_0_100.get(d, 0.0) for d in weights]
    mean_score = sum(scores) / len(scores) if scores else 50.0
    return {
        dim: advantage * ((dim_scores_0_100.get(dim, 0.0) - mean_score) / 100.0)
        for dim in weights
    }


def apply_gradient(
    weights: Dict[str, float],
    gradient: Dict[str, float],
    lr: float = LEARNING_RATE,
) -> Dict[str, float]:
    """
    梯度步进 → 迭代 clip+normalize 直到所有权重在 [WEIGHT_MIN, WEIGHT_MAX] 内。

    单次 clip→normalize 可能导致归一化后某维度仍低于 WEIGHT_MIN，
    因此最多迭代 10 次直至稳定（通常 1-2 次即收敛）。
    """
    updated = {
        dim: weights[dim] + lr * gradient.get(dim, 0.0)
        for dim in weights
    }
    for _ in range(10):
        clipped = {k: max(WEIGHT_MIN, min(WEIGHT_MAX, v)) for k, v in updated.items()}
        total = sum(clipped.values())
        if total <= 0:
            return DEFAULT_WEIGHTS.copy()
        normalized = {k: round(v / total, 6) for k, v in clipped.items()}
        if all(WEIGHT_MIN - 1e-9 <= v <= WEIGHT_MAX + 1e-9 for v in normalized.values()):
            return normalized
        updated = normalized
    return normalized


# ═══════════════════════════════════════════════════════════════════════════════
# DB IO 层
# ═══════════════════════════════════════════════════════════════════════════════

class DecisionWeightLearner:
    """
    决策权重在线学习器。

    典型用法（在 execution_feedback_service 中调用）：

        learner = DecisionWeightLearner()
        await learner.update_from_feedback(
            store_id=store_id,
            dim_scores={"financial": 75, "urgency": 60, "confidence": 80, "execution": 100},
            outcome=outcome,
            actual_impact_yuan=actual_impact_yuan,
            expected_saving_yuan=expected_saving_yuan,
            db=db,
        )
    """

    async def get_weights(
        self,
        store_id: str,
        db: AsyncSession,
    ) -> Dict[str, float]:
        """
        获取该门店的当前权重。

        查找顺序：门店专属 → 全局 → 硬编码默认
        """
        store_scope = f"store:{store_id}"
        for scope in (store_scope, "global"):
            row = await db.get(DecisionWeightConfig, scope)
            if row is not None:
                return {
                    "financial":  row.w_financial,
                    "urgency":    row.w_urgency,
                    "confidence": row.w_confidence,
                    "execution":  row.w_execution,
                }
        return DEFAULT_WEIGHTS.copy()

    async def update_from_feedback(
        self,
        store_id:             str,
        dim_scores:           Dict[str, float],   # {"financial":75, "urgency":60, ...}
        outcome:              str,                # "success" | "partial" | "failure"
        actual_impact_yuan:   float,
        expected_saving_yuan: float,
        db:                   AsyncSession,
    ) -> Dict[str, float]:
        """
        从一次执行反馈中学习，更新门店专属权重，返回更新后的权重。

        若 expected_saving_yuan <= 0，跳过学习（无法计算 accuracy_ratio）。
        """
        if expected_saving_yuan <= 0:
            logger.debug("weight_learner.skip_zero_expected", store_id=store_id)
            return await self.get_weights(store_id, db)

        scope = f"store:{store_id}"
        row = await db.get(DecisionWeightConfig, scope)
        if row is None:
            # 用全局权重或默认值初始化门店专属配置
            global_row = await db.get(DecisionWeightConfig, "global")
            row = DecisionWeightConfig(
                id=scope,
                w_financial  = global_row.w_financial  if global_row else DEFAULT_WEIGHTS["financial"],
                w_urgency    = global_row.w_urgency    if global_row else DEFAULT_WEIGHTS["urgency"],
                w_confidence = global_row.w_confidence if global_row else DEFAULT_WEIGHTS["confidence"],
                w_execution  = global_row.w_execution  if global_row else DEFAULT_WEIGHTS["execution"],
                sample_count = 0,
                update_history = [],
            )
            db.add(row)

        current_weights = {
            "financial":  row.w_financial,
            "urgency":    row.w_urgency,
            "confidence": row.w_confidence,
            "execution":  row.w_execution,
        }

        accuracy_ratio = compute_accuracy_ratio(outcome, actual_impact_yuan, expected_saving_yuan)
        gradient       = compute_gradient(current_weights, dim_scores, accuracy_ratio)
        new_weights    = apply_gradient(current_weights, gradient)

        # 记录历史快照（保留最近 MAX_HISTORY 条）
        snapshot = {
            "ts":             datetime.utcnow().isoformat(),
            "outcome":        outcome,
            "accuracy_ratio": round(accuracy_ratio, 4),
            "before":         {k: round(v, 4) for k, v in current_weights.items()},
            "after":          {k: round(v, 4) for k, v in new_weights.items()},
        }
        history = list(row.update_history or [])
        history.append(snapshot)
        if len(history) > MAX_HISTORY:
            history = history[-MAX_HISTORY:]

        # 写回 DB
        row.w_financial  = new_weights["financial"]
        row.w_urgency    = new_weights["urgency"]
        row.w_confidence = new_weights["confidence"]
        row.w_execution  = new_weights["execution"]
        row.sample_count = (row.sample_count or 0) + 1
        row.last_updated = datetime.utcnow()
        row.update_history = history

        try:
            await db.commit()
            logger.info(
                "weight_learner.updated",
                store_id=store_id,
                outcome=outcome,
                accuracy_ratio=round(accuracy_ratio, 3),
                before=current_weights,
                after=new_weights,
            )
        except Exception as exc:
            await db.rollback()
            logger.warning("weight_learner.commit_failed", store_id=store_id, error=str(exc))

        return new_weights

    async def get_weight_history(
        self,
        store_id: str,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """返回门店权重当前值 + 进化历史，用于前端可视化。"""
        scope = f"store:{store_id}"
        row = await db.get(DecisionWeightConfig, scope)
        weights = await self.get_weights(store_id, db)
        return {
            "store_id":     store_id,
            "scope":        scope,
            "weights":      weights,
            "sample_count": row.sample_count if row else 0,
            "last_updated": row.last_updated.isoformat() if (row and row.last_updated) else None,
            "history":      (row.update_history or []) if row else [],
            "is_default":   row is None,
        }
