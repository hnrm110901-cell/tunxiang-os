"""菜品健康评分引擎

三维评分体系（0-100分）：
- 毛利率维度（默认权重 40分）：毛利率>30%得满分，<15%得0分，线性插值
- 销量排名维度（默认权重 30分）：在同租户同门店菜品中的销量排名百分位
- 点评维度（默认权重 30分）：基于退菜率/差评率（目前用订单退菜率代替）

权重通过 ScoreWeights 配置，可按业务需要调整。
所有操作强制 tenant_id 租户隔离。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import structlog

log = structlog.get_logger(__name__)


# ─── 权重配置 ────────────────────────────────────────────────────────────────


@dataclass
class ScoreWeights:
    """评分权重配置（三维合计必须 == 100）"""

    margin: float = 40.0  # 毛利率维度满分
    sales_rank: float = 30.0  # 销量排名维度满分
    review: float = 30.0  # 点评维度满分

    def __post_init__(self) -> None:
        total = self.margin + self.sales_rank + self.review
        if abs(total - 100.0) > 0.01:
            raise ValueError(f"权重合计必须为100，当前为 {total}")


# 毛利率评分边界
MARGIN_FULL_SCORE_RATE = 0.30  # 毛利率 >= 30% → 满分
MARGIN_ZERO_SCORE_RATE = 0.15  # 毛利率 <= 15% → 0分


# ─── 数据模型 ─────────────────────────────────────────────────────────────────


@dataclass
class DishHealthScore:
    """菜品健康评分结果"""

    dish_id: str
    tenant_id: str
    store_id: str
    total_score: float  # 综合评分 0-100
    margin_score: float  # 毛利率维度得分
    sales_rank_score: float  # 销量排名维度得分
    review_score: float  # 点评维度得分
    margin_rate: float  # 实际毛利率
    sales_percentile: float  # 销量百分位（0-1）
    return_rate: float  # 退菜率（0-1）
    weights: ScoreWeights  # 使用的权重配置
    status: str  # healthy / needs_attention / critical
    calculated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "dish_id": self.dish_id,
            "tenant_id": self.tenant_id,
            "store_id": self.store_id,
            "total_score": round(self.total_score, 2),
            "margin_score": round(self.margin_score, 2),
            "sales_rank_score": round(self.sales_rank_score, 2),
            "review_score": round(self.review_score, 2),
            "margin_rate": round(self.margin_rate, 4),
            "sales_percentile": round(self.sales_percentile, 4),
            "return_rate": round(self.return_rate, 4),
            "status": self.status,
            "calculated_at": self.calculated_at,
            "weights": {
                "margin": self.weights.margin,
                "sales_rank": self.weights.sales_rank,
                "review": self.weights.review,
            },
        }


# ─── 内存测试存储（与 dish_intelligence.py 同样模式） ─────────────────────────

_dish_data: dict[str, dict] = {}  # key: "{tenant_id}:{dish_id}"
_store_dish_index: dict[str, list[str]] = {}  # key: "{tenant_id}:{store_id}" → [dish_id, ...]


def inject_dish_score_data(dish_id: str, store_id: str, tenant_id: str, data: dict) -> None:
    """注入菜品评分所需数据（供测试使用）

    data 结构:
        price_fen: int          -- 售价（分）
        cost_fen: int           -- 成本（分）
        total_sales: int        -- 累计销量
        return_count: int       -- 退菜/差评次数
        total_orders: int       -- 总订单数（用于计算退菜率）
    """
    key = f"{tenant_id}:{dish_id}"
    _dish_data[key] = {
        **data,
        "dish_id": dish_id,
        "store_id": store_id,
        "tenant_id": tenant_id,
    }
    store_key = f"{tenant_id}:{store_id}"
    if store_key not in _store_dish_index:
        _store_dish_index[store_key] = []
    if dish_id not in _store_dish_index[store_key]:
        _store_dish_index[store_key].append(dish_id)


def _clear_score_store() -> None:
    """清空内部存储，仅供测试用"""
    _dish_data.clear()
    _store_dish_index.clear()


# ─── 核心引擎 ─────────────────────────────────────────────────────────────────


class DishHealthScoreEngine:
    """菜品健康评分引擎（支持单品评分和批量评分）"""

    def __init__(self, weights: Optional[ScoreWeights] = None):
        self.weights = weights or ScoreWeights()

    # ── 维度计算 ──

    def _calc_margin_score(self, margin_rate: float) -> float:
        """毛利率维度评分（线性插值）

        margin_rate >= MARGIN_FULL_SCORE_RATE → 满分
        margin_rate <= MARGIN_ZERO_SCORE_RATE → 0分
        中间线性插值
        """
        if margin_rate >= MARGIN_FULL_SCORE_RATE:
            return self.weights.margin
        if margin_rate <= MARGIN_ZERO_SCORE_RATE:
            return 0.0
        ratio = (margin_rate - MARGIN_ZERO_SCORE_RATE) / (MARGIN_FULL_SCORE_RATE - MARGIN_ZERO_SCORE_RATE)
        return round(ratio * self.weights.margin, 4)

    def _calc_sales_rank_score(self, sales_percentile: float) -> float:
        """销量排名维度评分（直接按百分位线性映射）"""
        return round(max(0.0, min(sales_percentile, 1.0)) * self.weights.sales_rank, 4)

    def _calc_review_score(self, return_rate: float) -> float:
        """点评维度评分（退菜率越低分越高）

        return_rate == 0   → 满分
        return_rate >= 0.2 → 0分
        中间线性插值
        """
        MAX_BAD_RATE = 0.20
        if return_rate <= 0.0:
            return self.weights.review
        if return_rate >= MAX_BAD_RATE:
            return 0.0
        ratio = 1.0 - (return_rate / MAX_BAD_RATE)
        return round(ratio * self.weights.review, 4)

    @staticmethod
    def _determine_status(score: float) -> str:
        """根据综合评分判定状态"""
        if score >= 60.0:
            return "healthy"
        if score >= 40.0:
            return "needs_attention"
        return "critical"

    # ── 从内存数据计算（测试用路径） ──

    def _score_from_memory(
        self,
        dish_id: str,
        store_id: str,
        tenant_id: str,
    ) -> Optional[DishHealthScore]:
        """从注入的内存数据计算评分（用于单元测试）"""
        key = f"{tenant_id}:{dish_id}"
        data = _dish_data.get(key)
        if not data:
            return None

        # 毛利率
        price_fen = data.get("price_fen", 0)
        cost_fen = data.get("cost_fen", 0)
        margin_rate = (price_fen - cost_fen) / price_fen if price_fen > 0 else 0.0

        # 销量百分位
        store_key = f"{tenant_id}:{store_id}"
        dish_ids = _store_dish_index.get(store_key, [])
        all_sales = [_dish_data.get(f"{tenant_id}:{did}", {}).get("total_sales", 0) for did in dish_ids]
        my_sales = data.get("total_sales", 0)
        if all_sales:
            sales_percentile = sum(1 for s in all_sales if s <= my_sales) / len(all_sales)
        else:
            sales_percentile = 0.5

        # 退菜率
        total_orders = data.get("total_orders", 0)
        return_count = data.get("return_count", 0)
        return_rate = return_count / total_orders if total_orders > 0 else 0.0

        # 三维评分
        margin_score = self._calc_margin_score(margin_rate)
        sales_rank_score = self._calc_sales_rank_score(sales_percentile)
        review_score = self._calc_review_score(return_rate)
        total_score = margin_score + sales_rank_score + review_score

        return DishHealthScore(
            dish_id=dish_id,
            tenant_id=tenant_id,
            store_id=store_id,
            total_score=total_score,
            margin_score=margin_score,
            sales_rank_score=sales_rank_score,
            review_score=review_score,
            margin_rate=margin_rate,
            sales_percentile=sales_percentile,
            return_rate=return_rate,
            weights=self.weights,
            status=self._determine_status(total_score),
        )

    # ── 异步公开接口 ──

    async def score_dish(
        self,
        dish_id: str,
        store_id: str,
        tenant_id: str,
        db: object = None,
    ) -> Optional[DishHealthScore]:
        """计算单道菜评分及各维度明细

        当 db=None 时使用内存数据（测试模式）；
        生产环境中 db 为 AsyncSession，通过 SQL 查询数据。
        """
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")

        if db is None:
            result = self._score_from_memory(dish_id, store_id, tenant_id)
        else:
            result = await self._score_from_db(dish_id, store_id, tenant_id, db)

        if result:
            log.info(
                "dish_health_scored",
                dish_id=dish_id,
                store_id=store_id,
                tenant_id=tenant_id,
                total_score=result.total_score,
                status=result.status,
            )
        return result

    async def score_all_dishes(
        self,
        store_id: str,
        tenant_id: str,
        db: object = None,
    ) -> list[DishHealthScore]:
        """批量评分，用于生成门店健康报告

        返回列表按综合评分升序（最差在前，便于优先处理）。
        """
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")

        if db is None:
            store_key = f"{tenant_id}:{store_id}"
            dish_ids = _store_dish_index.get(store_key, [])
            scores = []
            for did in dish_ids:
                s = self._score_from_memory(did, store_id, tenant_id)
                if s:
                    scores.append(s)
        else:
            scores = await self._score_all_from_db(store_id, tenant_id, db)

        scores.sort(key=lambda x: x.total_score)
        log.info(
            "dish_health_batch_scored",
            store_id=store_id,
            tenant_id=tenant_id,
            dish_count=len(scores),
        )
        return scores

    # ── DB 查询路径（生产用） ──

    async def _score_from_db(
        self,
        dish_id: str,
        store_id: str,
        tenant_id: str,
        db: object,
    ) -> Optional[DishHealthScore]:
        """从数据库计算单品评分（生产路径）"""
        from sqlalchemy import text

        tenant_uuid = uuid.UUID(tenant_id)
        dish_uuid = uuid.UUID(dish_id)

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        # 基础价格与成本
        dish_row = (
            (
                await db.execute(
                    text("""
                SELECT price_fen, cost_fen, total_sales
                FROM dishes
                WHERE id = :dish_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = false
            """),
                    {"dish_id": dish_uuid, "tenant_id": tenant_uuid},
                )
            )
            .mappings()
            .first()
        )

        if not dish_row:
            log.warning("dish_not_found_for_score", dish_id=dish_id, tenant_id=tenant_id)
            return None

        price_fen = int(dish_row["price_fen"] or 0)
        cost_fen = int(dish_row["cost_fen"] or 0)
        my_sales = int(dish_row["total_sales"] or 0)
        margin_rate = (price_fen - cost_fen) / price_fen if price_fen > 0 else 0.0

        # 门店所有菜品销量（用于百分位）
        all_sales_result = await db.execute(
            text("""
                SELECT total_sales
                FROM dishes
                WHERE tenant_id = :tenant_id
                  AND is_deleted = false
                  AND is_available = true
            """),
            {"tenant_id": tenant_uuid},
        )
        all_sales = [int(r[0] or 0) for r in all_sales_result.fetchall()]
        sales_percentile = sum(1 for s in all_sales if s <= my_sales) / len(all_sales) if all_sales else 0.5

        # 退菜率（近30天退菜次数 / 总订单行数）
        return_row = (
            (
                await db.execute(
                    text("""
                SELECT
                    COUNT(*) FILTER (WHERE oi.is_returned = true) AS return_count,
                    COUNT(*) AS total_count
                FROM order_items oi
                WHERE oi.dish_id = :dish_id
                  AND oi.tenant_id = :tenant_id
                  AND oi.created_at >= NOW() - INTERVAL '30 days'
            """),
                    {"dish_id": dish_uuid, "tenant_id": tenant_uuid},
                )
            )
            .mappings()
            .first()
        )

        return_count = int(return_row["return_count"] or 0) if return_row else 0
        total_orders = int(return_row["total_count"] or 0) if return_row else 0
        return_rate = return_count / total_orders if total_orders > 0 else 0.0

        # 三维评分
        margin_score = self._calc_margin_score(margin_rate)
        sales_rank_score = self._calc_sales_rank_score(sales_percentile)
        review_score = self._calc_review_score(return_rate)
        total_score = margin_score + sales_rank_score + review_score

        return DishHealthScore(
            dish_id=dish_id,
            tenant_id=tenant_id,
            store_id=store_id,
            total_score=total_score,
            margin_score=margin_score,
            sales_rank_score=sales_rank_score,
            review_score=review_score,
            margin_rate=margin_rate,
            sales_percentile=sales_percentile,
            return_rate=return_rate,
            weights=self.weights,
            status=self._determine_status(total_score),
        )

    async def _score_all_from_db(
        self,
        store_id: str,
        tenant_id: str,
        db: object,
    ) -> list[DishHealthScore]:
        """从数据库批量评分（生产路径）"""
        from sqlalchemy import text

        tenant_uuid = uuid.UUID(tenant_id)

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        dishes_result = await db.execute(
            text("""
                SELECT id
                FROM dishes
                WHERE tenant_id = :tenant_id
                  AND is_deleted = false
                  AND is_available = true
            """),
            {"tenant_id": tenant_uuid},
        )
        dish_ids = [str(r[0]) for r in dishes_result.fetchall()]

        scores = []
        for did in dish_ids:
            s = await self._score_from_db(did, store_id, tenant_id, db)
            if s:
                scores.append(s)
        return scores
