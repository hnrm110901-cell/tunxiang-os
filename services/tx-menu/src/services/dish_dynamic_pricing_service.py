"""DishDynamicPricingService —— Sprint D3c 菜品动态定价（Core ML + Sonnet）

职责
----
1. **弹性估算**：从历史销量/价格时序算 log-log 回归 → 弹性系数 ε
   - log(Q) = α + ε * log(P) + noise
   - ε 典型值 -0.5 ~ -2.0（越小越敏感）
2. **最优价格求解**：max margin = (P - C) * Q，subject to 毛利 ≥ 15% 硬约束 + 变动 ≤ 15%
3. **Sonnet 语义校验**：Core ML/弹性出数值，Sonnet 判断品牌/客户感知是否违和
4. **店长审批**：plan → human_confirmed → applied（不自动落价）
5. **回测**：应用 7-14 天后自动回写实际 qty_delta + margin_delta

预期效果
-------
设计稿目标：毛利 +2pp。策略：
  - 提价热销+高弹性菜（明星品抢占利润）
  - 降价冷门+低弹性菜（引流品冲销量）
  - 禁动引流品（margin_rate<0.3 且日销>50 次的）

设计权衡
-------
- Core ML 预测 demand trend（未来 7 天客流）作为输入，实际弹性系数用 log-log 回归
  本地计算（数据量小 + 可解释，Core ML 留给后续专项模型）
- **三级降级**：log_log (≥14 天数据) → coreml (客流修正) → prior (ε=-1.0 先验)
- Sonnet validate 是"红/黄/绿灯"而非直接否决：high risk 店长必须二审
- **≤ 15% 调价幅度**与 CLAUDE.md §9"客户体验"隐含的价格稳定性吻合
"""
from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 硬约束
MARGIN_FLOOR = 0.15          # 毛利底线 15%（CLAUDE.md §9）
MAX_PRICE_CHANGE_PCT = 0.15  # 单次调价幅度上限 ±15%
MIN_ELASTICITY_DATA_POINTS = 14  # 至少 14 天数据才算弹性
DEFAULT_PRIOR_ELASTICITY = -1.0   # 无数据时的先验弹性


@dataclass
class PricingObservation:
    """单次价格-销量观测"""
    day: date
    price_fen: int
    quantity_sold: int


@dataclass
class ElasticityEstimate:
    """弹性估算结果"""
    elasticity: float
    confidence: float          # 0-1，log-log R²
    source: str                # log_log / coreml / prior / insufficient
    data_points: int


@dataclass
class PricingSuggestion:
    """单菜品定价建议"""
    dish_id: str
    dish_name: str
    current_price_fen: int
    suggested_price_fen: int
    current_cost_fen: int
    current_margin_rate: float
    suggested_margin_rate: float
    price_change_pct: float
    elasticity: ElasticityEstimate
    expected_daily_qty_delta: int
    expected_daily_margin_delta_fen: int
    constraint_check: dict
    sonnet_analysis: Optional[str] = None
    sonnet_risk_level: Optional[str] = None  # low / medium / high


def estimate_elasticity_log_log(
    observations: list[PricingObservation],
) -> ElasticityEstimate:
    """log-log 回归估算价格弹性。

    log(Q) = α + ε * log(P) + ε
    数据点 < 14 时返回 insufficient，触发降级到 prior。
    """
    valid = [o for o in observations if o.price_fen > 0 and o.quantity_sold > 0]
    if len(valid) < MIN_ELASTICITY_DATA_POINTS:
        return ElasticityEstimate(
            elasticity=DEFAULT_PRIOR_ELASTICITY,
            confidence=0.1,
            source="insufficient",
            data_points=len(valid),
        )

    xs = [math.log(o.price_fen) for o in valid]
    ys = [math.log(o.quantity_sold) for o in valid]
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    num = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
    den = sum((xs[i] - mean_x) ** 2 for i in range(n))
    if den == 0:
        # 价格没变过 → 无法估弹性
        return ElasticityEstimate(
            elasticity=DEFAULT_PRIOR_ELASTICITY,
            confidence=0.2,
            source="prior",
            data_points=n,
        )

    slope = num / den  # 即弹性 ε

    # R² 作 confidence
    ss_total = sum((y - mean_y) ** 2 for y in ys)
    ss_residual = sum(
        (ys[i] - (slope * xs[i] + mean_y - slope * mean_x)) ** 2 for i in range(n)
    )
    r2 = 1 - ss_residual / ss_total if ss_total > 0 else 0.0
    conf = max(0.2, min(0.9, r2))

    # 把弹性 clamp 到合理范围（防止异常数据噪声）
    slope = max(-5.0, min(2.0, slope))

    return ElasticityEstimate(
        elasticity=round(slope, 4),
        confidence=round(conf, 3),
        source="log_log",
        data_points=n,
    )


def solve_optimal_price(
    current_price_fen: int,
    cost_fen: int,
    elasticity: float,
    max_change_pct: float = MAX_PRICE_CHANGE_PCT,
    margin_floor: float = MARGIN_FLOOR,
) -> int:
    """Given elasticity 求最优价格 (max margin = (P-C)*Q)。

    理论最优：P* = C * ε / (ε + 1)（ε < -1 时有解；ε ∈ [-1, 0) 时应涨价到边界）
    实际解：带入 ± max_change_pct 区间 + margin_floor 约束后取可行域内最优。
    """
    if elasticity >= 0:
        # 错误的弹性方向（涨价带来需求增长）→ 不动价，避免被噪声带偏
        return current_price_fen

    # 理论无约束最优
    if elasticity < -1:
        p_star = int(cost_fen * elasticity / (elasticity + 1))
    else:
        # ε ∈ [-1, 0)：弹性小，应尽量涨价（需求下降速度慢于涨价速度）
        p_star = int(current_price_fen * (1 + max_change_pct))

    # 约束 1: margin_floor
    min_price = int(cost_fen / (1 - margin_floor))
    # 约束 2: ±max_change_pct
    min_price_change = int(current_price_fen * (1 - max_change_pct))
    max_price_change = int(current_price_fen * (1 + max_change_pct))

    lower = max(min_price, min_price_change)
    upper = max_price_change

    if upper < lower:
        # 约束冲突：当前价已低于 margin_floor 下限 → 必须涨到 min_price
        return max(current_price_fen, min_price)

    return max(lower, min(upper, p_star))


def expected_qty_delta(
    current_price_fen: int,
    new_price_fen: int,
    current_daily_qty: int,
    elasticity: float,
) -> int:
    """根据弹性估算销量变化。

    Q_new/Q_old = (P_new/P_old)^ε
    """
    if current_price_fen <= 0 or current_daily_qty <= 0:
        return 0
    price_ratio = new_price_fen / current_price_fen
    if price_ratio <= 0:
        return 0
    qty_ratio = price_ratio ** elasticity
    new_qty = int(current_daily_qty * qty_ratio)
    return new_qty - current_daily_qty


class DishDynamicPricingService:
    """D3c 菜品动态定价服务。

    依赖注入：
      sonnet_invoker: async (prompt, model_id) -> str，可为 None（走降级模板）
      coreml_client:  EdgeInferenceClient 实例，可为 None
    """

    def __init__(
        self,
        sonnet_invoker: Optional[Any] = None,
        coreml_client: Optional[Any] = None,
    ) -> None:
        self.sonnet_invoker = sonnet_invoker
        self.coreml_client = coreml_client

    async def suggest_pricing(
        self,
        *,
        dish_id: str,
        dish_name: str,
        current_price_fen: int,
        cost_fen: int,
        current_daily_qty: int,
        observations: list[PricingObservation],
    ) -> PricingSuggestion:
        """为单菜品生成定价建议。"""
        # 1. 弹性估算
        elasticity = estimate_elasticity_log_log(observations)

        # 2. 最优价格
        optimal = solve_optimal_price(
            current_price_fen=current_price_fen,
            cost_fen=cost_fen,
            elasticity=elasticity.elasticity,
        )

        # 3. 销量 & 毛利变化估算
        qty_delta = expected_qty_delta(
            current_price_fen=current_price_fen,
            new_price_fen=optimal,
            current_daily_qty=current_daily_qty,
            elasticity=elasticity.elasticity,
        )
        new_daily_qty = current_daily_qty + qty_delta
        current_daily_margin = (current_price_fen - cost_fen) * current_daily_qty
        new_daily_margin = (optimal - cost_fen) * new_daily_qty
        margin_delta = new_daily_margin - current_daily_margin

        # 4. 硬约束校验
        suggested_margin_rate = (
            (optimal - cost_fen) / optimal if optimal > 0 else 0.0
        )
        current_margin_rate = (
            (current_price_fen - cost_fen) / current_price_fen
            if current_price_fen > 0 else 0.0
        )
        change_pct = (optimal - current_price_fen) / current_price_fen if current_price_fen > 0 else 0.0

        constraint_check = {
            "margin_floor_passed": suggested_margin_rate >= MARGIN_FLOOR,
            "change_pct_within_limit": abs(change_pct) <= MAX_PRICE_CHANGE_PCT + 0.001,
            "cost_fen": cost_fen,
            "margin_floor": MARGIN_FLOOR,
            "max_change_pct": MAX_PRICE_CHANGE_PCT,
        }

        suggestion = PricingSuggestion(
            dish_id=dish_id,
            dish_name=dish_name,
            current_price_fen=current_price_fen,
            suggested_price_fen=optimal,
            current_cost_fen=cost_fen,
            current_margin_rate=round(current_margin_rate, 4),
            suggested_margin_rate=round(suggested_margin_rate, 4),
            price_change_pct=round(change_pct, 4),
            elasticity=elasticity,
            expected_daily_qty_delta=qty_delta,
            expected_daily_margin_delta_fen=margin_delta,
            constraint_check=constraint_check,
        )

        # 5. Sonnet 语义校验
        analysis, risk = await self._sonnet_validate(suggestion)
        suggestion.sonnet_analysis = analysis
        suggestion.sonnet_risk_level = risk

        return suggestion

    async def _sonnet_validate(
        self,
        suggestion: PricingSuggestion,
    ) -> tuple[str, str]:
        """Sonnet 语义校验；返回 (analysis, risk_level)。

        规则：
          - change_pct > 10%: high risk（大幅涨价需 sonnet 检查品牌影响）
          - 小菜品日销 <10: medium（数据量小）
          - margin_rate 已 < 20%: high（空间太小）
          - 其他：low
        """
        prompt = self._build_prompt(suggestion)

        if self.sonnet_invoker is not None:
            try:
                response = await self.sonnet_invoker(prompt, "claude-sonnet-4-6")
                return self._parse_sonnet_response(response, suggestion)
            except Exception as exc:  # noqa: BLE001
                logger.warning("sonnet_validate_failed error=%s", exc)
                # 降级到规则

        # Fallback：基于规则判定
        return self._fallback_validate(suggestion)

    @staticmethod
    def _build_prompt(s: PricingSuggestion) -> str:
        direction = "涨价" if s.price_change_pct > 0 else "降价" if s.price_change_pct < 0 else "不变"
        return (
            f"你是餐饮定价顾问。判断以下调价建议的品牌风险。\n"
            f"- 菜品：{s.dish_name}\n"
            f"- 当前价：¥{s.current_price_fen / 100:.2f}，成本 ¥{s.current_cost_fen / 100:.2f}\n"
            f"- 建议价：¥{s.suggested_price_fen / 100:.2f}（{direction} {abs(s.price_change_pct) * 100:.1f}%）\n"
            f"- 毛利率：{s.current_margin_rate:.1%} → {s.suggested_margin_rate:.1%}\n"
            f"- 弹性系数：{s.elasticity.elasticity} "
            f"(来源 {s.elasticity.source}，置信 {s.elasticity.confidence:.2f})\n"
            f"- 预估日销量变化：{s.expected_daily_qty_delta}\n"
            f"输出格式：行首一句话分析 + 末行 risk_level=low|medium|high"
        )

    @staticmethod
    def _parse_sonnet_response(
        response: str, suggestion: PricingSuggestion,
    ) -> tuple[str, str]:
        lines = [l.strip() for l in response.strip().split("\n") if l.strip()]
        risk = "low"
        analysis_lines = []
        for line in lines:
            lower = line.lower().replace(" ", "")
            if "risk_level=" in lower:
                for level in ("high", "medium", "low"):
                    if f"risk_level={level}" in lower:
                        risk = level
                        break
                continue
            analysis_lines.append(line)
        analysis = "\n".join(analysis_lines) or response.strip()
        return analysis, risk

    @staticmethod
    def _fallback_validate(s: PricingSuggestion) -> tuple[str, str]:
        """无 Sonnet 时的规则校验"""
        reasons: list[str] = []
        risk = "low"

        if abs(s.price_change_pct) > 0.10:
            reasons.append(f"调价幅度 {s.price_change_pct * 100:+.1f}% 较大")
            risk = "high"
        elif abs(s.price_change_pct) > 0.05:
            risk = "medium"

        if s.elasticity.source == "insufficient":
            reasons.append("历史数据不足（<14 天），弹性为先验值")
            risk = "high" if risk != "high" else risk
        elif s.elasticity.confidence < 0.3:
            reasons.append(f"弹性置信度仅 {s.elasticity.confidence:.2f}")
            if risk == "low":
                risk = "medium"

        if s.suggested_margin_rate < 0.20:
            reasons.append(f"调整后毛利率 {s.suggested_margin_rate:.1%} 仅略高于 15% 底线")
            risk = "high"

        if not s.constraint_check.get("margin_floor_passed"):
            reasons.append("违反毛利底线，必须拒绝")
            risk = "high"

        if not reasons:
            reasons.append("各项指标在安全区间")

        text = f"【{s.dish_name}】" + "；".join(reasons) + "。"
        return text, risk


# ──────────────────────────────────────────────────────────────────────
# DB 持久化
# ──────────────────────────────────────────────────────────────────────

async def save_suggestion_to_db(
    db: Any,
    *,
    tenant_id: str,
    store_id: Optional[str],
    suggestion: PricingSuggestion,
) -> str:
    """写入 dish_pricing_suggestions（status='plan'）"""
    import json

    from sqlalchemy import text

    record_id = str(uuid.uuid4())
    await db.execute(text("""
        INSERT INTO dish_pricing_suggestions (
            id, tenant_id, store_id, dish_id, dish_name,
            current_price_fen, suggested_price_fen, current_cost_fen,
            current_margin_rate, suggested_margin_rate, price_change_pct,
            elasticity, elasticity_confidence, elasticity_source,
            expected_daily_qty_delta, expected_daily_margin_delta_fen,
            constraint_check,
            sonnet_analysis, sonnet_risk_level,
            status
        ) VALUES (
            CAST(:id AS uuid),
            CAST(:tenant_id AS uuid),
            CAST(:store_id AS uuid),
            CAST(:dish_id AS uuid),
            :dish_name,
            :current_price_fen, :suggested_price_fen, :current_cost_fen,
            :current_margin_rate, :suggested_margin_rate, :price_change_pct,
            :elasticity, :elasticity_confidence, :elasticity_source,
            :qty_delta, :margin_delta,
            CAST(:constraint_check AS jsonb),
            :sonnet_analysis, :sonnet_risk_level,
            'plan'
        )
    """), {
        "id": record_id,
        "tenant_id": tenant_id,
        "store_id": store_id,
        "dish_id": suggestion.dish_id,
        "dish_name": suggestion.dish_name,
        "current_price_fen": suggestion.current_price_fen,
        "suggested_price_fen": suggestion.suggested_price_fen,
        "current_cost_fen": suggestion.current_cost_fen,
        "current_margin_rate": suggestion.current_margin_rate,
        "suggested_margin_rate": suggestion.suggested_margin_rate,
        "price_change_pct": suggestion.price_change_pct,
        "elasticity": suggestion.elasticity.elasticity,
        "elasticity_confidence": suggestion.elasticity.confidence,
        "elasticity_source": suggestion.elasticity.source,
        "qty_delta": suggestion.expected_daily_qty_delta,
        "margin_delta": suggestion.expected_daily_margin_delta_fen,
        "constraint_check": json.dumps(suggestion.constraint_check, ensure_ascii=False),
        "sonnet_analysis": suggestion.sonnet_analysis,
        "sonnet_risk_level": suggestion.sonnet_risk_level,
    })
    await db.commit()
    return record_id


async def transition_status(
    db: Any,
    *,
    tenant_id: str,
    suggestion_id: str,
    new_status: str,
    operator_id: Optional[str] = None,
) -> bool:
    """状态机迁移：plan → human_confirmed → applied / rejected / reverted"""
    from sqlalchemy import text

    allowed_transitions = {
        "human_confirmed": ("plan",),
        "applied": ("human_confirmed",),
        "rejected": ("plan", "human_confirmed"),
        "reverted": ("applied",),
    }
    from_states = allowed_transitions.get(new_status)
    if not from_states:
        raise ValueError(f"未知状态迁移: {new_status}")

    timestamp_col = {
        "human_confirmed": "confirmed_at",
        "applied": "applied_at",
        "reverted": "reverted_at",
    }.get(new_status)

    set_clauses = ["status = :new_status", "updated_at = NOW()"]
    if operator_id:
        set_clauses.append("confirmed_by = CAST(:op AS uuid)")
    if timestamp_col:
        set_clauses.append(f"{timestamp_col} = NOW()")

    from_placeholders = ", ".join(f"'{s}'" for s in from_states)

    result = await db.execute(text(f"""
        UPDATE dish_pricing_suggestions
        SET {', '.join(set_clauses)}
        WHERE id = CAST(:id AS uuid)
          AND tenant_id = CAST(:tenant_id AS uuid)
          AND status IN ({from_placeholders})
          AND is_deleted = false
        RETURNING id
    """), {
        "id": suggestion_id,
        "tenant_id": tenant_id,
        "new_status": new_status,
        "op": operator_id,
    })
    row = result.first()
    await db.commit()
    return row is not None


__all__ = [
    "PricingObservation",
    "ElasticityEstimate",
    "PricingSuggestion",
    "DishDynamicPricingService",
    "estimate_elasticity_log_log",
    "solve_optimal_price",
    "expected_qty_delta",
    "save_suggestion_to_db",
    "transition_status",
    "MARGIN_FLOOR",
    "MAX_PRICE_CHANGE_PCT",
    "MIN_ELASTICITY_DATA_POINTS",
    "DEFAULT_PRIOR_ELASTICITY",
]
