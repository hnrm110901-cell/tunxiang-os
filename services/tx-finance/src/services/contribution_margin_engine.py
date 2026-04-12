"""
边际贡献与保本点分析引擎（Phase 2A）
contribution_margin_engine.py

功能：
- 成本行为分类：fixed（固定）/ variable（变动）/ semi_variable（半变动）
- 菜品边际贡献率 = (售价 - 变动成本) / 售价
- 门店加权平均边际贡献率
- 保本营业额 = 固定成本 / 加权平均边际贡献率
- 保本客单数 = 保本营业额 / 平均客单价
- 时段保本分析（午市 / 晚市 / 宵夜）

金额单位统一使用分（fen, int）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 枚举 & 常量
# ---------------------------------------------------------------------------

class CostBehaviorType(str, Enum):
    FIXED = "fixed"                    # 固定成本（与营业额无关）
    VARIABLE = "variable"              # 完全变动成本（随营业额线性变化）
    SEMI_VARIABLE = "semi_variable"    # 半变动成本（底薪 + 绩效）


class MealPeriod(str, Enum):
    LUNCH = "lunch"      # 午市
    DINNER = "dinner"    # 晚市
    SUPPER = "supper"    # 宵夜
    ALL_DAY = "all_day"  # 全天（用于不区分时段的场景）


# ---------------------------------------------------------------------------
# 配置数据模型
# ---------------------------------------------------------------------------

@dataclass
class CostBehaviorConfig:
    """
    门店成本行为配置。

    固定成本示例（月度，分）：
        rent_fen            房租
        mgmt_salary_fen     管理人员工资
        depreciation_fen    设备折旧
        insurance_fen       保险
        other_fixed_fen     其他固定支出

    变动成本：
        variable_rate       变动成本率（食材 + 包装 + 外卖佣金），如 0.40 表示 40%

    半变动成本（员工底薪 + 绩效）：
        semi_variable_base_fen          固定底薪部分（月度，分）
        semi_variable_variable_rate     绩效/浮动部分占营业额比率
    """

    # 固定成本明细（分，月度）
    fixed_costs: dict[str, int] = field(default_factory=dict)
    # 示例 key：rent_fen / mgmt_salary_fen / depreciation_fen / insurance_fen / other_fixed_fen

    # 变动成本率（0.0 ~ 1.0）
    variable_rate: float = 0.0

    # 半变动成本：固定底薪部分（分，月度）
    semi_variable_base_fen: int = 0

    # 半变动成本：变动比率（0.0 ~ 1.0）
    semi_variable_variable_rate: float = 0.0

    def validate(self) -> None:
        """校验配置合法性，不合法时抛出 ValueError。"""
        if not (0.0 <= self.variable_rate <= 1.0):
            raise ValueError(
                f"variable_rate 必须在 [0, 1]，当前值：{self.variable_rate}"
            )
        if not (0.0 <= self.semi_variable_variable_rate <= 1.0):
            raise ValueError(
                f"semi_variable_variable_rate 必须在 [0, 1]，当前值：{self.semi_variable_variable_rate}"
            )
        if self.semi_variable_base_fen < 0:
            raise ValueError(
                f"semi_variable_base_fen 不能为负数，当前值：{self.semi_variable_base_fen}"
            )
        for key, val in self.fixed_costs.items():
            if val < 0:
                raise ValueError(f"fixed_costs[{key}] 不能为负数，当前值：{val}")

    @property
    def total_fixed_fen(self) -> int:
        """月度总固定成本（含半变动成本固定部分），单位：分。"""
        return sum(self.fixed_costs.values()) + self.semi_variable_base_fen

    @property
    def total_variable_rate(self) -> float:
        """合并后总变动成本率 = 完全变动率 + 半变动变动率。"""
        return self.variable_rate + self.semi_variable_variable_rate


# ---------------------------------------------------------------------------
# 结果数据模型
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DishContributionResult:
    """单品边际贡献计算结果"""

    dish_name: str
    selling_price_fen: int
    variable_cost_fen: int          # 该品的变动成本（分）
    contribution_margin_fen: int    # 边际贡献额（分）
    contribution_margin_rate: float  # 边际贡献率


@dataclass(frozen=True)
class StoreBreakEvenResult:
    """门店保本点计算结果"""

    # 输入汇总
    total_fixed_cost_fen: int        # 月度总固定成本（分）
    weighted_avg_cm_rate: float      # 加权平均边际贡献率
    avg_check_fen: int               # 平均客单价（分）

    # 保本点
    break_even_revenue_fen: int      # 保本营业额（分）
    break_even_covers: int           # 保本客单数（桌/单）

    # 安全边际相关（若传入实际营业额则计算）
    actual_revenue_fen: int | None = None
    safety_margin_fen: int | None = None      # 安全边际额（分）
    safety_margin_rate: float | None = None   # 安全边际率


@dataclass(frozen=True)
class PeriodBreakEvenResult:
    """单时段保本分析结果"""

    period: str                       # 时段标识（MealPeriod）
    period_fixed_cost_fen: int        # 分摊到本时段的固定成本（分）
    period_variable_rate: float       # 本时段综合变动成本率
    avg_check_fen: int                # 本时段平均客单价（分）

    break_even_revenue_fen: int       # 时段保本营业额（分）
    break_even_covers: int            # 时段保本客单数

    actual_revenue_fen: int | None = None
    is_profitable: bool | None = None  # 实际营收是否覆盖时段固定成本


# ---------------------------------------------------------------------------
# 引擎类
# ---------------------------------------------------------------------------

class ContributionMarginEngine:
    """
    边际贡献与保本点分析引擎。

    所有方法均为静态/类方法，无状态，可直接调用。
    """

    # ------------------------------------------------------------------
    # 1. 单品边际贡献
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_dish_contribution(
        dish_data: dict[str, Any],
        config: CostBehaviorConfig,
    ) -> DishContributionResult:
        """
        计算单品边际贡献。

        变动成本 = selling_price_fen × config.total_variable_rate
        如果 dish_data 中提供了 custom_variable_cost_fen，则优先使用该值（用于
        BOM成本已知时精确计算，而非按比率估算）。

        Args:
            dish_data: {
                "dish_name": str,
                "selling_price_fen": int,
                "custom_variable_cost_fen": int   # 可选，若提供则覆盖比率计算
            }
            config: 成本行为配置

        Returns:
            DishContributionResult
        """
        config.validate()

        dish_name: str = dish_data["dish_name"]
        selling_price_fen: int = dish_data["selling_price_fen"]

        if selling_price_fen <= 0:
            raise ValueError(
                f"selling_price_fen 必须大于 0，菜品：{dish_name}，当前值：{selling_price_fen}"
            )

        # 变动成本：优先使用精确值，否则按比率估算
        if "custom_variable_cost_fen" in dish_data:
            variable_cost_fen: int = int(dish_data["custom_variable_cost_fen"])
        else:
            variable_cost_fen = int(selling_price_fen * config.total_variable_rate)

        contribution_margin_fen: int = selling_price_fen - variable_cost_fen
        contribution_margin_rate: float = (
            contribution_margin_fen / selling_price_fen if selling_price_fen > 0 else 0.0
        )

        log = logger.bind(
            dish_name=dish_name,
            selling_price_fen=selling_price_fen,
            variable_cost_fen=variable_cost_fen,
            contribution_margin_fen=contribution_margin_fen,
            contribution_margin_rate=round(contribution_margin_rate, 4),
        )
        log.info("dish_contribution_calculated")

        return DishContributionResult(
            dish_name=dish_name,
            selling_price_fen=selling_price_fen,
            variable_cost_fen=variable_cost_fen,
            contribution_margin_fen=contribution_margin_fen,
            contribution_margin_rate=contribution_margin_rate,
        )

    @staticmethod
    def calculate_weighted_avg_cm_rate(
        dish_contributions: list[DishContributionResult],
        sales_volumes: list[int],
    ) -> float:
        """
        按销量加权计算门店平均边际贡献率。

        Args:
            dish_contributions: 菜品边际贡献列表
            sales_volumes:      各菜品对应的销量（与 dish_contributions 顺序一致）

        Returns:
            加权平均边际贡献率

        Raises:
            ValueError: 列表长度不一致或总营收为 0
        """
        if len(dish_contributions) != len(sales_volumes):
            raise ValueError(
                f"dish_contributions 长度 ({len(dish_contributions)}) 与 "
                f"sales_volumes 长度 ({len(sales_volumes)}) 不一致"
            )

        total_revenue_fen: int = sum(
            d.selling_price_fen * v
            for d, v in zip(dish_contributions, sales_volumes)
        )
        total_cm_fen: int = sum(
            d.contribution_margin_fen * v
            for d, v in zip(dish_contributions, sales_volumes)
        )

        if total_revenue_fen <= 0:
            raise ValueError("总营收为 0，无法计算加权平均边际贡献率")

        rate = total_cm_fen / total_revenue_fen
        logger.info(
            "weighted_avg_cm_rate_calculated",
            total_revenue_fen=total_revenue_fen,
            total_cm_fen=total_cm_fen,
            weighted_avg_cm_rate=round(rate, 4),
        )
        return rate

    # ------------------------------------------------------------------
    # 2. 门店保本点
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_store_break_even(
        config: CostBehaviorConfig,
        avg_check_fen: int,
        weighted_avg_cm_rate: float | None = None,
        actual_revenue_fen: int | None = None,
    ) -> StoreBreakEvenResult:
        """
        计算门店月度保本点。

        保本营业额公式：
            break_even_revenue = total_fixed_cost / weighted_avg_cm_rate

        保本客单数：
            break_even_covers = ceil(break_even_revenue / avg_check_fen)

        Args:
            config:                成本行为配置
            avg_check_fen:         平均客单价（分，> 0）
            weighted_avg_cm_rate:  加权平均边际贡献率（可选）。
                                   若为 None，则用 (1 - config.total_variable_rate) 估算。
            actual_revenue_fen:    当月实际营业额（分，可选），用于计算安全边际。

        Returns:
            StoreBreakEvenResult
        """
        import math

        config.validate()

        if avg_check_fen <= 0:
            raise ValueError(f"avg_check_fen 必须大于 0，当前值：{avg_check_fen}")

        # 加权平均边际贡献率：未提供则按成本结构估算
        cm_rate: float = (
            weighted_avg_cm_rate
            if weighted_avg_cm_rate is not None
            else (1.0 - config.total_variable_rate)
        )
        if cm_rate <= 0:
            raise ValueError(
                f"边际贡献率必须大于 0，当前值：{cm_rate}。"
                "请检查 variable_rate + semi_variable_variable_rate 是否已超过 1.0。"
            )

        total_fixed = config.total_fixed_fen
        break_even_revenue_fen: int = math.ceil(total_fixed / cm_rate)
        break_even_covers: int = math.ceil(break_even_revenue_fen / avg_check_fen)

        # 安全边际
        safety_margin_fen: int | None = None
        safety_margin_rate: float | None = None
        if actual_revenue_fen is not None:
            safety_margin_fen = actual_revenue_fen - break_even_revenue_fen
            safety_margin_rate = (
                safety_margin_fen / actual_revenue_fen if actual_revenue_fen > 0 else 0.0
            )

        logger.info(
            "store_break_even_calculated",
            total_fixed_cost_fen=total_fixed,
            cm_rate=round(cm_rate, 4),
            break_even_revenue_fen=break_even_revenue_fen,
            break_even_covers=break_even_covers,
            safety_margin_fen=safety_margin_fen,
        )

        return StoreBreakEvenResult(
            total_fixed_cost_fen=total_fixed,
            weighted_avg_cm_rate=cm_rate,
            avg_check_fen=avg_check_fen,
            break_even_revenue_fen=break_even_revenue_fen,
            break_even_covers=break_even_covers,
            actual_revenue_fen=actual_revenue_fen,
            safety_margin_fen=safety_margin_fen,
            safety_margin_rate=safety_margin_rate,
        )

    # ------------------------------------------------------------------
    # 3. 时段保本分析
    # ------------------------------------------------------------------

    @staticmethod
    def analyze_period_break_even(
        periods: list[dict[str, Any]],
        config: CostBehaviorConfig,
    ) -> list[PeriodBreakEvenResult]:
        """
        多时段保本分析。

        固定成本按时段权重分摊；每个时段可拥有独立的变动成本率（外卖比例不同）
        和平均客单价。

        Args:
            periods: 时段列表，每项格式：
                {
                    "period": str,                    # MealPeriod 值或自定义标签
                    "weight": float,                  # 固定成本分摊权重（各时段之和应为 1.0）
                    "avg_check_fen": int,             # 本时段平均客单价（分）
                    "variable_rate_override": float,  # 可选，覆盖 config.total_variable_rate
                    "actual_revenue_fen": int,        # 可选，本时段实际营收
                }
            config: 成本行为配置（提供总固定成本基准）

        Returns:
            与输入顺序一致的 PeriodBreakEvenResult 列表

        Raises:
            ValueError: 权重之和偏差超过 0.01
        """
        import math

        config.validate()

        # 校验权重之和
        total_weight: float = sum(p.get("weight", 0.0) for p in periods)
        if abs(total_weight - 1.0) > 0.01:
            raise ValueError(
                f"各时段 weight 之和应为 1.0，当前合计：{total_weight:.4f}"
            )

        total_fixed = config.total_fixed_fen
        results: list[PeriodBreakEvenResult] = []

        for period_data in periods:
            period_label: str = period_data["period"]
            weight: float = float(period_data.get("weight", 0.0))
            avg_check_fen: int = int(period_data["avg_check_fen"])
            actual_revenue_fen: int | None = period_data.get("actual_revenue_fen")

            if avg_check_fen <= 0:
                raise ValueError(
                    f"时段 {period_label} 的 avg_check_fen 必须大于 0，当前值：{avg_check_fen}"
                )

            # 分摊固定成本
            period_fixed_cost_fen: int = math.ceil(total_fixed * weight)

            # 本时段变动成本率（允许覆盖，用于外卖占比高的时段）
            period_variable_rate: float = float(
                period_data.get("variable_rate_override", config.total_variable_rate)
            )
            if not (0.0 <= period_variable_rate < 1.0):
                raise ValueError(
                    f"时段 {period_label} 的 variable_rate_override 必须在 [0, 1)，"
                    f"当前值：{period_variable_rate}"
                )

            period_cm_rate: float = 1.0 - period_variable_rate
            if period_cm_rate <= 0:
                raise ValueError(
                    f"时段 {period_label} 的边际贡献率为 0 或负数，请检查变动成本率配置"
                )

            # 时段保本点
            break_even_revenue_fen: int = math.ceil(period_fixed_cost_fen / period_cm_rate)
            break_even_covers: int = math.ceil(break_even_revenue_fen / avg_check_fen)

            # 是否盈利
            is_profitable: bool | None = None
            if actual_revenue_fen is not None:
                is_profitable = actual_revenue_fen >= break_even_revenue_fen

            logger.info(
                "period_break_even_calculated",
                period=period_label,
                weight=weight,
                period_fixed_cost_fen=period_fixed_cost_fen,
                break_even_revenue_fen=break_even_revenue_fen,
                break_even_covers=break_even_covers,
                is_profitable=is_profitable,
            )

            results.append(
                PeriodBreakEvenResult(
                    period=period_label,
                    period_fixed_cost_fen=period_fixed_cost_fen,
                    period_variable_rate=period_variable_rate,
                    avg_check_fen=avg_check_fen,
                    break_even_revenue_fen=break_even_revenue_fen,
                    break_even_covers=break_even_covers,
                    actual_revenue_fen=actual_revenue_fen,
                    is_profitable=is_profitable,
                )
            )

        return results

    # ------------------------------------------------------------------
    # 4. 汇总报告（便捷方法）
    # ------------------------------------------------------------------

    @classmethod
    def full_analysis(
        cls,
        config: CostBehaviorConfig,
        avg_check_fen: int,
        dish_contributions: list[DishContributionResult] | None = None,
        sales_volumes: list[int] | None = None,
        periods: list[dict[str, Any]] | None = None,
        actual_revenue_fen: int | None = None,
    ) -> dict[str, Any]:
        """
        一次性执行完整的边际贡献与保本点分析，返回汇总报告 dict。

        Args:
            config:               成本行为配置
            avg_check_fen:        平均客单价（分）
            dish_contributions:   菜品边际贡献列表（可选）
            sales_volumes:        对应销量（可选，与 dish_contributions 配套）
            periods:              时段配置列表（可选）
            actual_revenue_fen:   当月实际营业额（可选）

        Returns:
            {
                "store_break_even": StoreBreakEvenResult,
                "weighted_avg_cm_rate": float,
                "period_analysis": list[PeriodBreakEvenResult] | None,
            }
        """
        config.validate()

        # 加权平均边际贡献率
        if dish_contributions and sales_volumes:
            weighted_rate = cls.calculate_weighted_avg_cm_rate(dish_contributions, sales_volumes)
        else:
            weighted_rate = 1.0 - config.total_variable_rate

        # 门店保本点
        store_result = cls.calculate_store_break_even(
            config=config,
            avg_check_fen=avg_check_fen,
            weighted_avg_cm_rate=weighted_rate,
            actual_revenue_fen=actual_revenue_fen,
        )

        # 时段分析
        period_results: list[PeriodBreakEvenResult] | None = None
        if periods:
            period_results = cls.analyze_period_break_even(periods, config)

        logger.info(
            "full_analysis_complete",
            break_even_revenue_fen=store_result.break_even_revenue_fen,
            break_even_covers=store_result.break_even_covers,
            weighted_avg_cm_rate=round(weighted_rate, 4),
        )

        return {
            "store_break_even": store_result,
            "weighted_avg_cm_rate": weighted_rate,
            "period_analysis": period_results,
        }
