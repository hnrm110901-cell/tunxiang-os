"""菜单排名引擎 — 5因子加权评分

迁移自 tunxiang V2.x menu_ranker.py
纯函数部分（评分计算），无 DB 依赖。

权重：30%趋势 + 25%毛利 + 20%库存 + 15%时段 + 10%低退单
"""
from dataclasses import dataclass
from typing import Optional


WEIGHTS = {
    "trend": 0.30,
    "margin": 0.25,
    "stock": 0.20,
    "time_slot": 0.15,
    "low_refund": 0.10,
}


@dataclass
class DishScore:
    dish_id: str
    dish_name: str
    trend: float = 0.0
    margin: float = 0.0
    stock: float = 0.0
    time_slot: float = 0.0
    low_refund: float = 0.0

    @property
    def total(self) -> float:
        return round(
            self.trend * WEIGHTS["trend"]
            + self.margin * WEIGHTS["margin"]
            + self.stock * WEIGHTS["stock"]
            + self.time_slot * WEIGHTS["time_slot"]
            + self.low_refund * WEIGHTS["low_refund"],
            4,
        )

    @property
    def highlight(self) -> Optional[str]:
        if self.trend >= 0.8:
            return "销量持续上升"
        if self.margin >= 0.8:
            return "高毛利推荐"
        if self.stock >= 0.9:
            return "库存充足"
        if self.low_refund >= 0.9:
            return "顾客满意度高"
        return None


# ─── 纯函数：5因子评分 ───

def calc_trend_score(recent_sales: int, prev_sales: int) -> float:
    """趋势评分：近7天 vs 前7天"""
    if prev_sales <= 0:
        return 0.5
    trend_rate = (recent_sales - prev_sales) / max(prev_sales, 1)
    return min(1.0, max(0.0, 0.5 + trend_rate * 0.5))


def calc_margin_score(price_fen: int, cost_fen: int) -> float:
    """毛利评分"""
    if price_fen <= 0:
        return 0.3
    margin_rate = (price_fen - cost_fen) / price_fen
    return min(1.0, max(0.0, margin_rate))


def calc_stock_score(current_stock: float, min_stock: float) -> float:
    """库存评分：3段线性"""
    if min_stock <= 0:
        return 0.5
    ratio = current_stock / min_stock
    if ratio >= 3.0:
        return 1.0
    if ratio <= 0.5:
        return 0.0
    return round((ratio - 0.5) / 2.5, 4)


def calc_time_slot_score(dish: dict, time_slot: str) -> float:
    """时段评分：查表"""
    mapping = {
        "lunch": dish.get("lunch_sales_pct", 0.5),
        "dinner": dish.get("dinner_sales_pct", 0.5),
        "breakfast": dish.get("breakfast_sales_pct", 0.3),
        "off_peak": 0.3,
    }
    return mapping.get(time_slot, 0.3)


def calc_low_refund_score(refund_rate: float) -> float:
    """低退单评分：退单率10%=0分"""
    return max(0.0, 1.0 - refund_rate * 10)


# ─── 排名计算 ───

def compute_ranking(
    dishes: list[dict],
    time_slot: str = "lunch",
    limit: int = 10,
) -> list[dict]:
    """计算菜品排名

    Args:
        dishes: 菜品列表，每项含 id/name/price_fen/cost_fen/recent_sales/prev_sales/
                current_stock/min_stock/refund_rate/lunch_sales_pct/dinner_sales_pct
        time_slot: 当前时段 lunch/dinner/breakfast/off_peak
        limit: 返回条数

    Returns:
        排名列表 [{rank, dish_id, dish_name, total_score, scores, highlight}]
    """
    scored = []
    for d in dishes:
        ds = DishScore(
            dish_id=d.get("dish_id", d.get("id", "")),
            dish_name=d.get("dish_name", d.get("name", "")),
            trend=calc_trend_score(d.get("recent_sales", 0), d.get("prev_sales", 0)),
            margin=calc_margin_score(d.get("price_fen", 0), d.get("cost_fen", 0)),
            stock=calc_stock_score(d.get("current_stock", 0), d.get("min_stock", 1)),
            time_slot=calc_time_slot_score(d, time_slot),
            low_refund=calc_low_refund_score(d.get("refund_rate", 0)),
        )
        scored.append(ds)

    scored.sort(key=lambda s: s.total, reverse=True)

    return [
        {
            "rank": i + 1,
            "dish_id": s.dish_id,
            "dish_name": s.dish_name,
            "total_score": s.total,
            "scores": {
                "trend": s.trend,
                "margin": s.margin,
                "stock": s.stock,
                "time_slot": s.time_slot,
                "low_refund": s.low_refund,
            },
            "highlight": s.highlight,
        }
        for i, s in enumerate(scored[:limit])
    ]
