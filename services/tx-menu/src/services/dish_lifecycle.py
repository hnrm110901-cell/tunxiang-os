"""菜品生命周期AI服务

负责：
- 新品7天评测期管理（销量/毛利达标检测，自动建议）
- 沽清预警（库存低于2天用量时预警）
- 菜品下架建议（多维度综合判断）
- 每日夜批作业（new dish eval + sellout warning + health score）

所有方法显式传入 tenant_id，强制租户隔离。
不创建 Alembic 文件，不修改 main.py。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog

from .dish_health_score import DishHealthScoreEngine, DishHealthScore, ScoreWeights

log = structlog.get_logger(__name__)


# ─── 阈值常量 ─────────────────────────────────────────────────────────────────

NEW_DISH_EVAL_DAYS: int = 7            # 新品评测期天数
SELLOUT_WARNING_DAYS: int = 2          # 低于N天销量时预警
LOW_HEALTH_THRESHOLD: float = 40.0    # 健康分低于此值进入待优化
LOW_SALES_THRESHOLD: int = 5          # 评测期内销量低于此值建议下架
LOW_MARGIN_THRESHOLD: float = 0.15    # 毛利率低于此值建议调价
REMOVAL_MARGIN_CRITICAL: float = 0.10  # 毛利率持续低于此值纳入下架建议
REMOVAL_LOW_HEALTH_DAYS: int = 30     # 健康分低于40持续此天数→下架建议


# ─── 内存数据存储（测试用，与 dish_intelligence 同样模式） ──────────────────


_dishes: dict[str, dict] = {}               # key: "{tenant_id}:{dish_id}"
_store_dish_index: dict[str, list[str]] = {}  # key: "{tenant_id}:{store_id}" → [dish_id, ...]
_dish_health_history: dict[str, list[dict]] = {}  # key: "{tenant_id}:{dish_id}" → [score_record, ...]
_notifications: list[dict] = []             # 生成的通知列表


def inject_dish_lifecycle_data(dish_id: str, store_id: str, tenant_id: str, data: dict) -> None:
    """注入菜品生命周期数据（供测试使用）

    data 结构:
        price_fen: int              -- 售价（分）
        cost_fen: int               -- 成本（分）
        launched_at: str(ISO)       -- 上架时间
        total_sales: int            -- 累计销量
        eval_period_sales: int      -- 评测期内销量
        stock_qty: float            -- 当前库存（份数/kg等）
        daily_avg_sales: float      -- 日均销量
        return_count: int           -- 退菜次数
        total_orders: int           -- 总订单数
        low_health_since: str|None  -- 健康分低于40的起始日期（ISO），None表示未进入
    """
    key = f"{tenant_id}:{dish_id}"
    _dishes[key] = {
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


def _clear_lifecycle_store() -> None:
    """清空内部存储，仅供测试用"""
    _dishes.clear()
    _store_dish_index.clear()
    _dish_health_history.clear()
    _notifications.clear()


def _get_notifications() -> list[dict]:
    """获取已生成的通知列表（测试用）"""
    return list(_notifications)


# ─── 数据模型 ─────────────────────────────────────────────────────────────────


@dataclass
class EvalReport:
    """新品评测报告"""
    dish_id: str
    tenant_id: str
    store_id: str
    eval_period_days: int
    eval_sales: int                     # 评测期销量
    margin_rate: float                  # 评测期毛利率
    verdict: str                        # pass / low_sales / low_margin / failed
    suggestions: list[str] = field(default_factory=list)
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "dish_id": self.dish_id,
            "tenant_id": self.tenant_id,
            "store_id": self.store_id,
            "eval_period_days": self.eval_period_days,
            "eval_sales": self.eval_sales,
            "margin_rate": round(self.margin_rate, 4),
            "verdict": self.verdict,
            "suggestions": self.suggestions,
            "evaluated_at": self.evaluated_at,
        }


@dataclass
class SelloutWarning:
    """沽清预警"""
    dish_id: str
    tenant_id: str
    store_id: str
    stock_qty: float                    # 当前库存
    daily_avg_sales: float              # 日均销量
    days_remaining: float               # 预计剩余天数
    warning_level: str                  # urgent (<1天) / warning (<2天)

    def to_dict(self) -> dict:
        return {
            "dish_id": self.dish_id,
            "tenant_id": self.tenant_id,
            "store_id": self.store_id,
            "stock_qty": self.stock_qty,
            "daily_avg_sales": round(self.daily_avg_sales, 2),
            "days_remaining": round(self.days_remaining, 2),
            "warning_level": self.warning_level,
        }


@dataclass
class RemovalSuggestion:
    """下架建议"""
    dish_id: str
    tenant_id: str
    store_id: str
    reason: str                         # 下架主因
    evidence: dict                      # 数据支撑
    priority: str                       # high / medium

    def to_dict(self) -> dict:
        return {
            "dish_id": self.dish_id,
            "tenant_id": self.tenant_id,
            "store_id": self.store_id,
            "reason": self.reason,
            "evidence": self.evidence,
            "priority": self.priority,
        }


# ─── 主服务 ───────────────────────────────────────────────────────────────────


class DishLifecycleService:
    """菜品生命周期AI服务"""

    NEW_DISH_EVAL_DAYS = NEW_DISH_EVAL_DAYS
    SELLOUT_WARNING_DAYS = SELLOUT_WARNING_DAYS
    LOW_HEALTH_THRESHOLD = LOW_HEALTH_THRESHOLD

    def __init__(self, weights: Optional[ScoreWeights] = None):
        self._score_engine = DishHealthScoreEngine(weights=weights)

    # ── 新品7天评测 ──

    async def check_new_dish_evaluations(
        self,
        tenant_id: str,
        db: object = None,
    ) -> list[EvalReport]:
        """检查所有7天评测期到期的新品

        逻辑：
        1. 查找所有 launched_at 在 7天前左右 的菜品
        2. 统计评测期内：销量、毛利率
        3. 生成评测报告
        4. 销量低 → 建议下架通知
        5. 毛利低 → 建议调价通知
        """
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")

        if db is None:
            return await self._check_evals_from_memory(tenant_id)
        return await self._check_evals_from_db(tenant_id, db)

    async def _check_evals_from_memory(self, tenant_id: str) -> list[EvalReport]:
        """从内存数据执行新品评测（测试路径）"""
        now = datetime.now(timezone.utc)
        cutoff_start = now - timedelta(days=self.NEW_DISH_EVAL_DAYS + 1)
        cutoff_end = now - timedelta(days=self.NEW_DISH_EVAL_DAYS - 1)

        reports = []
        for key, data in _dishes.items():
            if not key.startswith(f"{tenant_id}:"):
                continue

            launched_at_str = data.get("launched_at")
            if not launched_at_str:
                continue

            launched_at = datetime.fromisoformat(launched_at_str)
            if launched_at.tzinfo is None:
                launched_at = launched_at.replace(tzinfo=timezone.utc)

            if not (cutoff_start <= launched_at <= cutoff_end):
                continue

            report = self._build_eval_report(data)
            reports.append(report)

            # 生成通知
            self._emit_eval_notifications(report)

        log.info(
            "new_dish_evals_checked",
            tenant_id=tenant_id,
            report_count=len(reports),
        )
        return reports

    def _build_eval_report(self, data: dict) -> EvalReport:
        """构建单品评测报告"""
        dish_id = data["dish_id"]
        store_id = data.get("store_id", "")
        tenant_id = data["tenant_id"]

        price_fen = data.get("price_fen", 0)
        cost_fen = data.get("cost_fen", 0)
        margin_rate = (price_fen - cost_fen) / price_fen if price_fen > 0 else 0.0
        eval_sales = data.get("eval_period_sales", data.get("total_sales", 0))

        suggestions = []
        verdict = "pass"

        if eval_sales < LOW_SALES_THRESHOLD:
            verdict = "low_sales" if verdict == "pass" else "failed"
            suggestions.append(
                f"评测期({self.NEW_DISH_EVAL_DAYS}天)销量仅{eval_sales}份，"
                f"低于阈值{LOW_SALES_THRESHOLD}份，建议下架或调整菜品"
            )

        if margin_rate < LOW_MARGIN_THRESHOLD:
            verdict = "low_margin" if verdict == "pass" else "failed"
            suggestions.append(
                f"评测期毛利率{margin_rate:.1%}，"
                f"低于警戒线{LOW_MARGIN_THRESHOLD:.0%}，建议调价或降低食材成本"
            )

        return EvalReport(
            dish_id=dish_id,
            tenant_id=tenant_id,
            store_id=store_id,
            eval_period_days=self.NEW_DISH_EVAL_DAYS,
            eval_sales=eval_sales,
            margin_rate=margin_rate,
            verdict=verdict,
            suggestions=suggestions,
        )

    def _emit_eval_notifications(self, report: EvalReport) -> None:
        """将评测结论写入通知列表"""
        if report.verdict == "pass":
            return
        _notifications.append({
            "type": "new_dish_eval",
            "dish_id": report.dish_id,
            "tenant_id": report.tenant_id,
            "store_id": report.store_id,
            "verdict": report.verdict,
            "suggestions": report.suggestions,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    async def _check_evals_from_db(self, tenant_id: str, db: object) -> list[EvalReport]:
        """从数据库执行新品评测（生产路径）"""
        from sqlalchemy import text

        tenant_uuid = uuid.UUID(tenant_id)
        now = datetime.now(timezone.utc)
        cutoff_start = now - timedelta(days=self.NEW_DISH_EVAL_DAYS + 1)
        cutoff_end = now - timedelta(days=self.NEW_DISH_EVAL_DAYS - 1)

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        result = await db.execute(
            text("""
                SELECT
                    d.id,
                    d.store_id,
                    d.price_fen,
                    d.cost_fen,
                    d.created_at AS launched_at,
                    COALESCE(SUM(oi.quantity), 0) AS eval_sales
                FROM dishes d
                LEFT JOIN order_items oi
                    ON oi.dish_id = d.id
                    AND oi.tenant_id = d.tenant_id
                    AND oi.created_at BETWEEN d.created_at AND d.created_at + INTERVAL '7 days'
                WHERE d.tenant_id = :tenant_id
                  AND d.is_deleted = false
                  AND d.created_at BETWEEN :cutoff_start AND :cutoff_end
                GROUP BY d.id, d.store_id, d.price_fen, d.cost_fen, d.created_at
            """),
            {
                "tenant_id": tenant_uuid,
                "cutoff_start": cutoff_start,
                "cutoff_end": cutoff_end,
            },
        )

        reports = []
        for row in result.mappings().all():
            price_fen = int(row["price_fen"] or 0)
            cost_fen = int(row["cost_fen"] or 0)
            margin_rate = (price_fen - cost_fen) / price_fen if price_fen > 0 else 0.0
            eval_sales = int(row["eval_sales"])

            suggestions = []
            verdict = "pass"
            if eval_sales < LOW_SALES_THRESHOLD:
                verdict = "low_sales"
                suggestions.append(
                    f"评测期销量{eval_sales}份，低于阈值{LOW_SALES_THRESHOLD}份，建议下架"
                )
            if margin_rate < LOW_MARGIN_THRESHOLD:
                verdict = "low_margin" if verdict == "pass" else "failed"
                suggestions.append(
                    f"毛利率{margin_rate:.1%}，低于警戒线{LOW_MARGIN_THRESHOLD:.0%}，建议调价"
                )

            report = EvalReport(
                dish_id=str(row["id"]),
                tenant_id=tenant_id,
                store_id=str(row["store_id"]) if row["store_id"] else "",
                eval_period_days=self.NEW_DISH_EVAL_DAYS,
                eval_sales=eval_sales,
                margin_rate=margin_rate,
                verdict=verdict,
                suggestions=suggestions,
            )
            reports.append(report)
            self._emit_eval_notifications(report)

        log.info(
            "new_dish_evals_db_checked",
            tenant_id=tenant_id,
            report_count=len(reports),
        )
        return reports

    # ── 沽清预警 ──

    async def check_sellout_warnings(
        self,
        store_id: str,
        tenant_id: str,
        db: object = None,
    ) -> list[SelloutWarning]:
        """沽清预警：库存低于2天销量时预警

        对比当前库存 vs 日均销量 × SELLOUT_WARNING_DAYS。
        """
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")

        if db is None:
            return await self._sellout_from_memory(store_id, tenant_id)
        return await self._sellout_from_db(store_id, tenant_id, db)

    async def _sellout_from_memory(
        self, store_id: str, tenant_id: str
    ) -> list[SelloutWarning]:
        """从内存数据执行沽清预警（测试路径）"""
        store_key = f"{tenant_id}:{store_id}"
        dish_ids = _store_dish_index.get(store_key, [])
        warnings = []

        for did in dish_ids:
            key = f"{tenant_id}:{did}"
            data = _dishes.get(key, {})

            stock_qty = float(data.get("stock_qty", 0))
            daily_avg = float(data.get("daily_avg_sales", 0))

            if daily_avg <= 0:
                continue

            days_remaining = stock_qty / daily_avg
            if days_remaining < self.SELLOUT_WARNING_DAYS:
                warning_level = "urgent" if days_remaining < 1 else "warning"
                warnings.append(SelloutWarning(
                    dish_id=did,
                    tenant_id=tenant_id,
                    store_id=store_id,
                    stock_qty=stock_qty,
                    daily_avg_sales=daily_avg,
                    days_remaining=days_remaining,
                    warning_level=warning_level,
                ))

        log.info(
            "sellout_warnings_checked",
            store_id=store_id,
            tenant_id=tenant_id,
            warning_count=len(warnings),
        )
        return warnings

    async def _sellout_from_db(
        self, store_id: str, tenant_id: str, db: object
    ) -> list[SelloutWarning]:
        """从数据库执行沽清预警（生产路径）"""
        from sqlalchemy import text

        tenant_uuid = uuid.UUID(tenant_id)
        store_uuid = uuid.UUID(store_id)

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        # 查询各菜品库存与近7天日均销量
        result = await db.execute(
            text("""
                SELECT
                    d.id AS dish_id,
                    COALESCE(inv.stock_qty, 0) AS stock_qty,
                    COALESCE(
                        SUM(oi.quantity) FILTER (
                            WHERE oi.created_at >= NOW() - INTERVAL '7 days'
                        ) / 7.0,
                        0
                    ) AS daily_avg_sales
                FROM dishes d
                LEFT JOIN dish_inventory inv
                    ON inv.dish_id = d.id
                    AND inv.store_id = :store_id
                    AND inv.tenant_id = d.tenant_id
                    AND inv.is_deleted = false
                LEFT JOIN order_items oi
                    ON oi.dish_id = d.id
                    AND oi.tenant_id = d.tenant_id
                WHERE d.tenant_id = :tenant_id
                  AND d.store_id = :store_id
                  AND d.is_deleted = false
                  AND d.is_available = true
                GROUP BY d.id, inv.stock_qty
            """),
            {"tenant_id": tenant_uuid, "store_id": store_uuid},
        )

        warnings = []
        for row in result.mappings().all():
            stock_qty = float(row["stock_qty"])
            daily_avg = float(row["daily_avg_sales"])

            if daily_avg <= 0:
                continue

            days_remaining = stock_qty / daily_avg
            if days_remaining < self.SELLOUT_WARNING_DAYS:
                warning_level = "urgent" if days_remaining < 1 else "warning"
                warnings.append(SelloutWarning(
                    dish_id=str(row["dish_id"]),
                    tenant_id=tenant_id,
                    store_id=store_id,
                    stock_qty=stock_qty,
                    daily_avg_sales=daily_avg,
                    days_remaining=days_remaining,
                    warning_level=warning_level,
                ))

        log.info(
            "sellout_warnings_db_checked",
            store_id=store_id,
            tenant_id=tenant_id,
            warning_count=len(warnings),
        )
        return warnings

    # ── 下架建议 ──

    async def generate_removal_suggestions(
        self,
        store_id: str,
        tenant_id: str,
        db: object = None,
    ) -> list[RemovalSuggestion]:
        """生成下架建议列表

        触发条件（满足任一）：
        1. 健康分 < 40 持续 REMOVAL_LOW_HEALTH_DAYS 天
        2. 评测期内销量为0
        3. 毛利率持续低于 REMOVAL_MARGIN_CRITICAL(10%)
        """
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")

        if db is None:
            return await self._removal_from_memory(store_id, tenant_id)
        return await self._removal_from_db(store_id, tenant_id, db)

    async def _removal_from_memory(
        self, store_id: str, tenant_id: str
    ) -> list[RemovalSuggestion]:
        """从内存数据生成下架建议（测试路径）"""
        store_key = f"{tenant_id}:{store_id}"
        dish_ids = _store_dish_index.get(store_key, [])
        suggestions = []
        now = datetime.now(timezone.utc)

        for did in dish_ids:
            key = f"{tenant_id}:{did}"
            data = _dishes.get(key, {})

            price_fen = data.get("price_fen", 0)
            cost_fen = data.get("cost_fen", 0)
            margin_rate = (price_fen - cost_fen) / price_fen if price_fen > 0 else 0.0
            eval_sales = data.get("eval_period_sales", None)
            low_health_since_str = data.get("low_health_since")

            # 条件1：健康分低于40持续30天
            if low_health_since_str:
                low_health_since = datetime.fromisoformat(low_health_since_str)
                if low_health_since.tzinfo is None:
                    low_health_since = low_health_since.replace(tzinfo=timezone.utc)
                low_health_days = (now - low_health_since).days
                if low_health_days >= REMOVAL_LOW_HEALTH_DAYS:
                    suggestions.append(RemovalSuggestion(
                        dish_id=did,
                        tenant_id=tenant_id,
                        store_id=store_id,
                        reason="健康分持续低于40分超过30天",
                        evidence={
                            "low_health_since": low_health_since_str,
                            "low_health_days": low_health_days,
                        },
                        priority="high",
                    ))
                    continue

            # 条件2：评测期销量为0
            if eval_sales is not None and eval_sales == 0:
                suggestions.append(RemovalSuggestion(
                    dish_id=did,
                    tenant_id=tenant_id,
                    store_id=store_id,
                    reason="新品评测期内零销量",
                    evidence={
                        "eval_period_days": self.NEW_DISH_EVAL_DAYS,
                        "eval_sales": 0,
                    },
                    priority="high",
                ))
                continue

            # 条件3：毛利率持续低于10%
            if margin_rate < REMOVAL_MARGIN_CRITICAL:
                suggestions.append(RemovalSuggestion(
                    dish_id=did,
                    tenant_id=tenant_id,
                    store_id=store_id,
                    reason=f"毛利率{margin_rate:.1%}持续低于警戒线{REMOVAL_MARGIN_CRITICAL:.0%}",
                    evidence={
                        "margin_rate": round(margin_rate, 4),
                        "threshold": REMOVAL_MARGIN_CRITICAL,
                        "price_fen": price_fen,
                        "cost_fen": cost_fen,
                    },
                    priority="medium",
                ))

        log.info(
            "removal_suggestions_generated",
            store_id=store_id,
            tenant_id=tenant_id,
            suggestion_count=len(suggestions),
        )
        return suggestions

    async def _removal_from_db(
        self, store_id: str, tenant_id: str, db: object
    ) -> list[RemovalSuggestion]:
        """从数据库生成下架建议（生产路径）"""
        from sqlalchemy import text

        tenant_uuid = uuid.UUID(tenant_id)
        store_uuid = uuid.UUID(store_id)
        now = datetime.now(timezone.utc)
        health_cutoff = now - timedelta(days=REMOVAL_LOW_HEALTH_DAYS)

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        result = await db.execute(
            text("""
                SELECT
                    d.id,
                    d.price_fen,
                    d.cost_fen,
                    d.created_at AS launched_at,
                    COALESCE(dhs.low_health_since, NULL) AS low_health_since,
                    COALESCE(
                        SUM(oi.quantity) FILTER (
                            WHERE oi.created_at BETWEEN d.created_at
                                AND d.created_at + INTERVAL '7 days'
                        ),
                        0
                    ) AS eval_sales
                FROM dishes d
                LEFT JOIN dish_health_status dhs
                    ON dhs.dish_id = d.id
                    AND dhs.tenant_id = d.tenant_id
                LEFT JOIN order_items oi
                    ON oi.dish_id = d.id
                    AND oi.tenant_id = d.tenant_id
                WHERE d.tenant_id = :tenant_id
                  AND d.store_id = :store_id
                  AND d.is_deleted = false
                  AND d.is_available = true
                GROUP BY d.id, d.price_fen, d.cost_fen, d.created_at, dhs.low_health_since
            """),
            {"tenant_id": tenant_uuid, "store_id": store_uuid},
        )

        suggestions = []
        for row in result.mappings().all():
            dish_id = str(row["id"])
            price_fen = int(row["price_fen"] or 0)
            cost_fen = int(row["cost_fen"] or 0)
            margin_rate = (price_fen - cost_fen) / price_fen if price_fen > 0 else 0.0
            eval_sales = int(row["eval_sales"])
            low_health_since = row["low_health_since"]

            # 条件1
            if low_health_since and low_health_since <= health_cutoff:
                suggestions.append(RemovalSuggestion(
                    dish_id=dish_id,
                    tenant_id=tenant_id,
                    store_id=store_id,
                    reason="健康分持续低于40分超过30天",
                    evidence={
                        "low_health_since": low_health_since.isoformat(),
                        "low_health_days": (now - low_health_since).days,
                    },
                    priority="high",
                ))
                continue

            # 条件2
            launched_at = row["launched_at"]
            if launched_at:
                days_since_launch = (now - launched_at.replace(tzinfo=timezone.utc)).days
                if days_since_launch >= self.NEW_DISH_EVAL_DAYS and eval_sales == 0:
                    suggestions.append(RemovalSuggestion(
                        dish_id=dish_id,
                        tenant_id=tenant_id,
                        store_id=store_id,
                        reason="新品评测期内零销量",
                        evidence={
                            "eval_period_days": self.NEW_DISH_EVAL_DAYS,
                            "eval_sales": 0,
                        },
                        priority="high",
                    ))
                    continue

            # 条件3
            if margin_rate < REMOVAL_MARGIN_CRITICAL:
                suggestions.append(RemovalSuggestion(
                    dish_id=dish_id,
                    tenant_id=tenant_id,
                    store_id=store_id,
                    reason=f"毛利率{margin_rate:.1%}持续低于警戒线{REMOVAL_MARGIN_CRITICAL:.0%}",
                    evidence={
                        "margin_rate": round(margin_rate, 4),
                        "threshold": REMOVAL_MARGIN_CRITICAL,
                        "price_fen": price_fen,
                        "cost_fen": cost_fen,
                    },
                    priority="medium",
                ))

        log.info(
            "removal_suggestions_db_generated",
            store_id=store_id,
            tenant_id=tenant_id,
            suggestion_count=len(suggestions),
        )
        return suggestions

    # ── 每日夜批 ──

    async def run_daily_checks(
        self,
        tenant_id: str,
        db: object = None,
    ) -> dict:
        """每日夜批：新品评测 + 健康评分更新

        下架建议和沽清预警需要 store_id，由调用方分别对每个门店触发。
        此方法执行不依赖特定门店的全局任务。

        Returns:
            {
                "eval_reports": [...],
                "run_at": str,
                "tenant_id": str,
            }
        """
        if not tenant_id:
            raise ValueError("tenant_id 不能为空")

        run_at = datetime.now(timezone.utc).isoformat()

        log.info("daily_checks_started", tenant_id=tenant_id, run_at=run_at)

        eval_reports = await self.check_new_dish_evaluations(tenant_id, db)

        # 健康分低于阈值的菜品标记为待优化（内存模式下更新标记）
        low_health_dishes = await self._flag_low_health_dishes(tenant_id, db)

        log.info(
            "daily_checks_completed",
            tenant_id=tenant_id,
            eval_count=len(eval_reports),
            low_health_count=len(low_health_dishes),
        )

        return {
            "tenant_id": tenant_id,
            "run_at": run_at,
            "eval_reports": [r.to_dict() for r in eval_reports],
            "low_health_dishes": low_health_dishes,
        }

    async def _flag_low_health_dishes(
        self,
        tenant_id: str,
        db: object,
    ) -> list[str]:
        """找出健康分低于阈值的菜品，标记为待优化状态"""
        if db is not None:
            return []   # 生产路径：由调用方对每门店分别触发

        now_str = datetime.now(timezone.utc).isoformat()
        flagged = []

        for key, data in _dishes.items():
            if not key.startswith(f"{tenant_id}:"):
                continue
            dish_id = data["dish_id"]
            store_id = data.get("store_id", "")

            score = await self._score_engine.score_dish(dish_id, store_id, tenant_id, db=None)
            if score and score.total_score < self.LOW_HEALTH_THRESHOLD:
                # 记录首次进入低健康状态的时间
                if not data.get("low_health_since"):
                    data["low_health_since"] = now_str
                flagged.append(dish_id)
                log.info(
                    "dish_flagged_low_health",
                    dish_id=dish_id,
                    score=score.total_score,
                    tenant_id=tenant_id,
                )

        return flagged
