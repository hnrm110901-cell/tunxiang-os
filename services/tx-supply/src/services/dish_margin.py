"""
菜品毛利计算服务
dish_margin.py

功能：
- 基于BOM理论成本 + 售价计算单品毛利
- 批量菜品毛利计算
- 四象限分类（明星/耕马/谜题/狗）
- 渠道毛利差异（堂食 vs 外卖含平台佣金）

金额单位统一使用分（fen, int）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 枚举 & 常量
# ---------------------------------------------------------------------------


class Channel(str, Enum):
    DINE_IN = "dine_in"  # 堂食
    DELIVERY = "delivery"  # 外卖
    TAKEOUT = "takeout"  # 自提


QUADRANT_STAR = "star"  # 高毛利 + 高销量 —— 明星
QUADRANT_PLOW_HORSE = "plow_horse"  # 低毛利 + 高销量 —— 耕马
QUADRANT_PUZZLE = "puzzle"  # 高毛利 + 低销量 —— 谜题
QUADRANT_DOG = "dog"  # 低毛利 + 低销量 —— 狗

# 毛利率阈值：高于此值视为"高毛利"
DEFAULT_HIGH_MARGIN_THRESHOLD: float = 0.60
# 相对销量阈值：高于此值视为"高销量"（调用方传入相对值，如 1.0 = 均值）
DEFAULT_HIGH_VOLUME_THRESHOLD: float = 1.0


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DishMarginResult:
    """单品毛利计算结果"""

    dish_name: str
    channel: str

    # 价格（分）
    selling_price_fen: int
    bom_cost_fen: int

    # 渠道费率
    platform_commission_rate: float  # 0.0 ~ 1.0，堂食时为 0

    # 计算结果（分）
    platform_fee_fen: int  # 平台佣金（分）
    effective_revenue_fen: int  # 扣佣后有效营收（分）
    gross_profit_fen: int  # 毛利额（分）

    # 比率
    gross_margin_rate: float  # 毛利率 = gross_profit_fen / effective_revenue_fen
    cost_rate: float  # 成本率 = bom_cost_fen / effective_revenue_fen

    # 四象限（需调用 classify_dish_quadrant 填充，默认空字符串）
    quadrant: str = ""


@dataclass
class BatchMarginSummary:
    """批量计算汇总"""

    total_dishes: int
    avg_gross_margin_rate: float
    high_margin_count: int  # 毛利率 >= 阈值
    low_margin_count: int
    results: list[DishMarginResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 核心纯函数
# ---------------------------------------------------------------------------


def calculate_dish_margin(
    dish_name: str,
    selling_price_fen: int,
    bom_cost_fen: int,
    channel: str = Channel.DINE_IN,
    platform_commission_rate: float = 0.0,
) -> DishMarginResult:
    """
    计算单品毛利。

    Args:
        dish_name:                菜品名称
        selling_price_fen:        售价（分，> 0）
        bom_cost_fen:             BOM理论成本（分，>= 0）
        channel:                  渠道 "dine_in" | "delivery" | "takeout"
        platform_commission_rate: 平台佣金率 0.0 ~ 1.0
                                  堂食时应传 0.0；外卖时如美团约 0.18~0.22

    Returns:
        DishMarginResult

    Raises:
        ValueError: 参数不合法时
    """
    log = logger.bind(
        dish_name=dish_name,
        selling_price_fen=selling_price_fen,
        bom_cost_fen=bom_cost_fen,
        channel=channel,
        platform_commission_rate=platform_commission_rate,
    )

    # --- 参数校验 ---
    if selling_price_fen <= 0:
        raise ValueError(f"selling_price_fen 必须大于 0，当前值：{selling_price_fen}")
    if bom_cost_fen < 0:
        raise ValueError(f"bom_cost_fen 不能为负数，当前值：{bom_cost_fen}")
    if not (0.0 <= platform_commission_rate < 1.0):
        raise ValueError(f"platform_commission_rate 必须在 [0, 1) 之间，当前值：{platform_commission_rate}")

    # --- 计算平台佣金（向下取整到分） ---
    platform_fee_fen: int = int(selling_price_fen * platform_commission_rate)

    # --- 有效营收 = 售价 - 平台佣金 ---
    effective_revenue_fen: int = selling_price_fen - platform_fee_fen

    # --- 毛利额 ---
    gross_profit_fen: int = effective_revenue_fen - bom_cost_fen

    # --- 毛利率 & 成本率（以有效营收为分母，避免除以0） ---
    if effective_revenue_fen > 0:
        gross_margin_rate: float = gross_profit_fen / effective_revenue_fen
        cost_rate: float = bom_cost_fen / effective_revenue_fen
    else:
        gross_margin_rate = 0.0
        cost_rate = 1.0

    result = DishMarginResult(
        dish_name=dish_name,
        channel=channel,
        selling_price_fen=selling_price_fen,
        bom_cost_fen=bom_cost_fen,
        platform_commission_rate=platform_commission_rate,
        platform_fee_fen=platform_fee_fen,
        effective_revenue_fen=effective_revenue_fen,
        gross_profit_fen=gross_profit_fen,
        gross_margin_rate=gross_margin_rate,
        cost_rate=cost_rate,
    )

    log.info(
        "dish_margin_calculated",
        gross_profit_fen=gross_profit_fen,
        gross_margin_rate=round(gross_margin_rate, 4),
    )
    return result


def batch_dish_margin(dishes: list[dict]) -> list[DishMarginResult]:
    """
    批量计算菜品毛利。

    Args:
        dishes: 每项 dict 对应 calculate_dish_margin 的参数：
            {
                "dish_name": str,
                "selling_price_fen": int,
                "bom_cost_fen": int,
                "channel": str,                   # 可选，默认 "dine_in"
                "platform_commission_rate": float  # 可选，默认 0.0
            }

    Returns:
        与输入顺序一致的 DishMarginResult 列表

    Note:
        单项计算失败时记录错误日志并跳过该项，不中断整批次处理。
    """
    log = logger.bind(batch_size=len(dishes))
    log.info("batch_dish_margin_start")

    results: list[DishMarginResult] = []

    for idx, dish in enumerate(dishes):
        try:
            result = calculate_dish_margin(
                dish_name=dish["dish_name"],
                selling_price_fen=dish["selling_price_fen"],
                bom_cost_fen=dish["bom_cost_fen"],
                channel=dish.get("channel", Channel.DINE_IN),
                platform_commission_rate=dish.get("platform_commission_rate", 0.0),
            )
            results.append(result)
        except (KeyError, ValueError) as exc:
            logger.warning(
                "batch_dish_margin_item_skipped",
                index=idx,
                dish=dish,
                error=str(exc),
            )

    log.info("batch_dish_margin_done", success_count=len(results), skip_count=len(dishes) - len(results))
    return results


def classify_dish_quadrant(
    margin_rate: float,
    relative_sales_volume: float,
    high_margin_threshold: float = DEFAULT_HIGH_MARGIN_THRESHOLD,
    high_volume_threshold: float = DEFAULT_HIGH_VOLUME_THRESHOLD,
) -> Literal["star", "plow_horse", "puzzle", "dog"]:
    """
    菜品四象限分类（Boston Matrix 餐饮改编版）。

    象限定义：
        star       明星 —— 高毛利 + 高销量（重点推广）
        plow_horse 耕马 —— 低毛利 + 高销量（走量保营收）
        puzzle     谜题 —— 高毛利 + 低销量（提升曝光）
        dog        狗   —— 低毛利 + 低销量（考虑下架）

    Args:
        margin_rate:            毛利率（0.0 ~ 1.0）
        relative_sales_volume:  相对销量（与门店均值之比，1.0 = 均值）
        high_margin_threshold:  高毛利判断阈值，默认 0.60
        high_volume_threshold:  高销量判断阈值，默认 1.0（均值）

    Returns:
        四象限标签字符串
    """
    is_high_margin: bool = margin_rate >= high_margin_threshold
    is_high_volume: bool = relative_sales_volume >= high_volume_threshold

    if is_high_margin and is_high_volume:
        quadrant = QUADRANT_STAR
    elif not is_high_margin and is_high_volume:
        quadrant = QUADRANT_PLOW_HORSE
    elif is_high_margin and not is_high_volume:
        quadrant = QUADRANT_PUZZLE
    else:
        quadrant = QUADRANT_DOG

    logger.debug(
        "dish_quadrant_classified",
        margin_rate=round(margin_rate, 4),
        relative_sales_volume=round(relative_sales_volume, 4),
        quadrant=quadrant,
    )
    return quadrant  # type: ignore[return-value]


def enrich_quadrant(
    result: DishMarginResult,
    relative_sales_volume: float,
    high_margin_threshold: float = DEFAULT_HIGH_MARGIN_THRESHOLD,
    high_volume_threshold: float = DEFAULT_HIGH_VOLUME_THRESHOLD,
) -> DishMarginResult:
    """
    为已有的 DishMarginResult 补充四象限分类，返回新实例（frozen dataclass）。

    Args:
        result:                 来自 calculate_dish_margin 的结果
        relative_sales_volume:  该菜品相对于门店均值的销量比
        high_margin_threshold:  高毛利判断阈值
        high_volume_threshold:  高销量判断阈值

    Returns:
        带有 quadrant 字段的新 DishMarginResult
    """
    quadrant = classify_dish_quadrant(
        margin_rate=result.gross_margin_rate,
        relative_sales_volume=relative_sales_volume,
        high_margin_threshold=high_margin_threshold,
        high_volume_threshold=high_volume_threshold,
    )
    # frozen=True，需用 dataclasses.replace
    from dataclasses import replace

    return replace(result, quadrant=quadrant)


def build_batch_summary(
    results: list[DishMarginResult],
    high_margin_threshold: float = DEFAULT_HIGH_MARGIN_THRESHOLD,
) -> BatchMarginSummary:
    """
    对批量计算结果进行汇总统计。

    Args:
        results:               batch_dish_margin 返回值
        high_margin_threshold: 高毛利判断阈值

    Returns:
        BatchMarginSummary
    """
    if not results:
        return BatchMarginSummary(
            total_dishes=0,
            avg_gross_margin_rate=0.0,
            high_margin_count=0,
            low_margin_count=0,
            results=[],
        )

    total = len(results)
    avg_rate = sum(r.gross_margin_rate for r in results) / total
    high_count = sum(1 for r in results if r.gross_margin_rate >= high_margin_threshold)

    return BatchMarginSummary(
        total_dishes=total,
        avg_gross_margin_rate=avg_rate,
        high_margin_count=high_count,
        low_margin_count=total - high_count,
        results=results,
    )
