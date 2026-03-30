"""菜品生命周期AI 单元测试

覆盖：
1. 新品7天评测：上架后7天内标记"试运营"，自动统计销量/毛利
2. 评测期结束：销量<阈值 → 建议下架；毛利<15% → 建议调价
3. 沽清预警：库存低于2天销量时预警
4. 菜品健康评分：毛利率(40%) + 销量排名(30%) + 点评分(30%)
5. 低健康分菜品（<40分）自动进入"待优化"状态
6. 下架建议列表（包含理由）
7. tenant_id 隔离
"""
import sys
import os
import asyncio
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

import pytest

from services.dish_health_score import (
    DishHealthScoreEngine,
    ScoreWeights,
    MARGIN_FULL_SCORE_RATE,
    MARGIN_ZERO_SCORE_RATE,
    inject_dish_score_data,
    _clear_score_store,
)
from services.dish_lifecycle import (
    DishLifecycleService,
    inject_dish_lifecycle_data,
    _clear_lifecycle_store,
    _get_notifications,
    LOW_SALES_THRESHOLD,
    LOW_MARGIN_THRESHOLD,
    REMOVAL_MARGIN_CRITICAL,
    REMOVAL_LOW_HEALTH_DAYS,
)

TENANT_A = "tenant-test-aaa"
TENANT_B = "tenant-test-bbb"
STORE_1 = "store-001"
STORE_2 = "store-002"


# ─── 辅助函数 ─────────────────────────────────────────────────────────────────

def run(coro):
    """同步执行 async 函数（pytest-asyncio 可选时使用）"""
    return asyncio.get_event_loop().run_until_complete(coro)


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


# ─── 1. 菜品健康评分 ──────────────────────────────────────────────────────────


class TestDishHealthScoreEngine:
    def setup_method(self):
        _clear_score_store()

    def _inject(self, dish_id, store_id, tenant_id,
                price=5000, cost=2000, total_sales=100,
                return_count=0, total_orders=100):
        inject_dish_score_data(dish_id, store_id, tenant_id, {
            "price_fen": price,
            "cost_fen": cost,
            "total_sales": total_sales,
            "return_count": return_count,
            "total_orders": total_orders,
        })

    def test_high_margin_full_score(self):
        """毛利率>=30%应获得毛利维度满分"""
        self._inject("dish-1", STORE_1, TENANT_A, price=5000, cost=2000)  # 毛利60%
        engine = DishHealthScoreEngine()
        score = run(engine.score_dish("dish-1", STORE_1, TENANT_A, db=None))
        assert score is not None
        assert score.margin_score == 40.0

    def test_low_margin_zero_score(self):
        """毛利率<=15%应获得毛利维度0分"""
        self._inject("dish-1", STORE_1, TENANT_A, price=5000, cost=4400)  # 毛利12%
        engine = DishHealthScoreEngine()
        score = run(engine.score_dish("dish-1", STORE_1, TENANT_A, db=None))
        assert score is not None
        assert score.margin_score == 0.0

    def test_margin_linear_interpolation(self):
        """毛利率在15%-30%之间线性插值"""
        # 毛利22.5% → 恰好在15%和30%中间 → 应得20分
        self._inject("dish-1", STORE_1, TENANT_A, price=4000, cost=3100)  # ~22.5%
        engine = DishHealthScoreEngine()
        score = run(engine.score_dish("dish-1", STORE_1, TENANT_A, db=None))
        assert score is not None
        assert 0.0 < score.margin_score < 40.0

    def test_sales_rank_percentile(self):
        """销量排名百分位正确映射到评分"""
        # 注入10道菜，dish-top 排名最高
        for i in range(10):
            self._inject(f"filler-{i}", STORE_1, TENANT_A, total_sales=(i + 1) * 10)
        self._inject("dish-top", STORE_1, TENANT_A, total_sales=999)

        engine = DishHealthScoreEngine()
        score = run(engine.score_dish("dish-top", STORE_1, TENANT_A, db=None))
        assert score is not None
        assert score.sales_percentile > 0.9     # 销量最高，百分位接近1
        assert score.sales_rank_score > 25.0    # 接近满分30

    def test_zero_return_rate_full_review_score(self):
        """零退菜率应获得点评维度满分"""
        self._inject("dish-1", STORE_1, TENANT_A, return_count=0, total_orders=100)
        engine = DishHealthScoreEngine()
        score = run(engine.score_dish("dish-1", STORE_1, TENANT_A, db=None))
        assert score is not None
        assert score.review_score == 30.0

    def test_high_return_rate_zero_review_score(self):
        """退菜率>=20%应获得点评维度0分"""
        self._inject("dish-1", STORE_1, TENANT_A, return_count=25, total_orders=100)  # 25%
        engine = DishHealthScoreEngine()
        score = run(engine.score_dish("dish-1", STORE_1, TENANT_A, db=None))
        assert score is not None
        assert score.review_score == 0.0

    def test_total_score_is_sum_of_dimensions(self):
        """综合评分 == 三维子分之和"""
        self._inject("dish-1", STORE_1, TENANT_A, price=5000, cost=2000,
                     total_sales=50, return_count=5, total_orders=100)
        engine = DishHealthScoreEngine()
        score = run(engine.score_dish("dish-1", STORE_1, TENANT_A, db=None))
        assert score is not None
        assert abs(score.total_score - (
            score.margin_score + score.sales_rank_score + score.review_score
        )) < 0.01

    def test_score_not_found_returns_none(self):
        """无数据菜品返回 None"""
        engine = DishHealthScoreEngine()
        score = run(engine.score_dish("dish-nonexistent", STORE_1, TENANT_A, db=None))
        assert score is None

    def test_tenant_id_required(self):
        """tenant_id为空应抛出 ValueError"""
        engine = DishHealthScoreEngine()
        with pytest.raises(ValueError):
            run(engine.score_dish("dish-1", STORE_1, "", db=None))

    def test_healthy_status(self):
        """高分菜品状态为 healthy"""
        self._inject("dish-1", STORE_1, TENANT_A, price=5000, cost=2000,
                     total_sales=200, return_count=0, total_orders=100)
        engine = DishHealthScoreEngine()
        score = run(engine.score_dish("dish-1", STORE_1, TENANT_A, db=None))
        assert score is not None
        assert score.status == "healthy"

    def test_critical_status(self):
        """极低分菜品状态为 critical"""
        # 毛利率极低 + 退菜率高 + 销量最低
        self._inject("dish-1", STORE_1, TENANT_A, price=5000, cost=4800,
                     total_sales=1, return_count=30, total_orders=100)
        engine = DishHealthScoreEngine()
        score = run(engine.score_dish("dish-1", STORE_1, TENANT_A, db=None))
        assert score is not None
        assert score.status == "critical"
        assert score.total_score < 40.0

    def test_custom_weights(self):
        """自定义权重生效"""
        weights = ScoreWeights(margin=50.0, sales_rank=30.0, review=20.0)
        engine = DishHealthScoreEngine(weights=weights)
        self._inject("dish-1", STORE_1, TENANT_A, price=5000, cost=2000,
                     total_sales=100, return_count=0, total_orders=100)
        score = run(engine.score_dish("dish-1", STORE_1, TENANT_A, db=None))
        assert score is not None
        assert score.margin_score == 50.0       # 毛利率60%，满分50

    def test_weights_must_sum_to_100(self):
        """权重合计不等于100应抛出 ValueError"""
        with pytest.raises(ValueError):
            ScoreWeights(margin=40.0, sales_rank=40.0, review=40.0)

    def test_batch_score_sorted_ascending(self):
        """批量评分按综合分升序返回"""
        self._inject("dish-bad", STORE_1, TENANT_A, price=5000, cost=4800,
                     total_sales=1, return_count=30, total_orders=100)
        self._inject("dish-good", STORE_1, TENANT_A, price=5000, cost=2000,
                     total_sales=200, return_count=0, total_orders=100)
        engine = DishHealthScoreEngine()
        scores = run(engine.score_all_dishes(STORE_1, TENANT_A, db=None))
        assert len(scores) == 2
        assert scores[0].dish_id == "dish-bad"  # 最差在前
        assert scores[0].total_score < scores[1].total_score


# ─── 2. 新品7天评测 ──────────────────────────────────────────────────────────


class TestNewDishEvaluation:
    def setup_method(self):
        _clear_lifecycle_store()

    def _inject_new_dish(self, dish_id, store_id, tenant_id,
                         launched_days_ago=7, eval_sales=20,
                         price=5000, cost=2000):
        inject_dish_lifecycle_data(dish_id, store_id, tenant_id, {
            "launched_at": _days_ago(launched_days_ago),
            "eval_period_sales": eval_sales,
            "price_fen": price,
            "cost_fen": cost,
            "total_sales": eval_sales,
            "stock_qty": 50.0,
            "daily_avg_sales": 5.0,
            "return_count": 0,
            "total_orders": eval_sales,
            "low_health_since": None,
        })

    def test_passing_dish_verdict_pass(self):
        """销量和毛利均达标时评测通过"""
        self._inject_new_dish("dish-pass", STORE_1, TENANT_A,
                              eval_sales=20, price=5000, cost=2000)
        svc = DishLifecycleService()
        reports = run(svc.check_new_dish_evaluations(TENANT_A))
        assert any(r.dish_id == "dish-pass" and r.verdict == "pass" for r in reports)

    def test_low_sales_verdict_low_sales(self):
        """评测期销量低于阈值，评测结论为 low_sales"""
        self._inject_new_dish("dish-low-sales", STORE_1, TENANT_A,
                              eval_sales=LOW_SALES_THRESHOLD - 1)
        svc = DishLifecycleService()
        reports = run(svc.check_new_dish_evaluations(TENANT_A))
        matching = [r for r in reports if r.dish_id == "dish-low-sales"]
        assert matching
        assert matching[0].verdict == "low_sales"
        assert len(matching[0].suggestions) > 0

    def test_low_margin_verdict_low_margin(self):
        """毛利率低于阈值，评测结论为 low_margin"""
        # 毛利率 10% < 15%
        self._inject_new_dish("dish-low-margin", STORE_1, TENANT_A,
                              eval_sales=20, price=5000, cost=4500)
        svc = DishLifecycleService()
        reports = run(svc.check_new_dish_evaluations(TENANT_A))
        matching = [r for r in reports if r.dish_id == "dish-low-margin"]
        assert matching
        assert "low_margin" in matching[0].verdict or "failed" in matching[0].verdict
        assert any("调价" in s or "成本" in s for s in matching[0].suggestions)

    def test_both_fail_verdict_failed(self):
        """销量和毛利均不达标，评测结论为 failed"""
        self._inject_new_dish("dish-failed", STORE_1, TENANT_A,
                              eval_sales=0, price=5000, cost=4500)
        svc = DishLifecycleService()
        reports = run(svc.check_new_dish_evaluations(TENANT_A))
        matching = [r for r in reports if r.dish_id == "dish-failed"]
        assert matching
        assert matching[0].verdict == "failed"
        assert len(matching[0].suggestions) >= 2

    def test_not_yet_7_days_not_included(self):
        """上架未满7天的新品不进入评测"""
        self._inject_new_dish("dish-too-new", STORE_1, TENANT_A,
                              launched_days_ago=3)
        svc = DishLifecycleService()
        reports = run(svc.check_new_dish_evaluations(TENANT_A))
        assert not any(r.dish_id == "dish-too-new" for r in reports)

    def test_much_older_dish_not_included(self):
        """上架超过8天的菜品不进入7天评测窗口"""
        self._inject_new_dish("dish-old", STORE_1, TENANT_A,
                              launched_days_ago=30)
        svc = DishLifecycleService()
        reports = run(svc.check_new_dish_evaluations(TENANT_A))
        assert not any(r.dish_id == "dish-old" for r in reports)

    def test_low_sales_generates_notification(self):
        """低销量评测结果生成通知"""
        self._inject_new_dish("dish-notify", STORE_1, TENANT_A,
                              eval_sales=0)
        svc = DishLifecycleService()
        run(svc.check_new_dish_evaluations(TENANT_A))
        notifications = _get_notifications()
        assert any(n["dish_id"] == "dish-notify" for n in notifications)

    def test_tenant_id_required(self):
        """tenant_id 为空应抛出 ValueError"""
        svc = DishLifecycleService()
        with pytest.raises(ValueError):
            run(svc.check_new_dish_evaluations(""))


# ─── 3. 沽清预警 ─────────────────────────────────────────────────────────────


class TestSelloutWarnings:
    def setup_method(self):
        _clear_lifecycle_store()

    def _inject_dish(self, dish_id, store_id, tenant_id,
                     stock_qty=10.0, daily_avg=5.0):
        inject_dish_lifecycle_data(dish_id, store_id, tenant_id, {
            "launched_at": _days_ago(30),
            "eval_period_sales": 50,
            "price_fen": 5000,
            "cost_fen": 2000,
            "total_sales": 150,
            "stock_qty": stock_qty,
            "daily_avg_sales": daily_avg,
            "return_count": 0,
            "total_orders": 150,
            "low_health_since": None,
        })

    def test_stock_below_2_days_triggers_warning(self):
        """库存低于2天销量时触发预警"""
        self._inject_dish("dish-warn", STORE_1, TENANT_A, stock_qty=5, daily_avg=5)
        # 剩余1天库存
        svc = DishLifecycleService()
        warnings = run(svc.check_sellout_warnings(STORE_1, TENANT_A))
        assert any(w.dish_id == "dish-warn" for w in warnings)

    def test_stock_above_2_days_no_warning(self):
        """库存超过2天销量时不预警"""
        self._inject_dish("dish-safe", STORE_1, TENANT_A, stock_qty=20, daily_avg=5)
        # 剩余4天库存
        svc = DishLifecycleService()
        warnings = run(svc.check_sellout_warnings(STORE_1, TENANT_A))
        assert not any(w.dish_id == "dish-safe" for w in warnings)

    def test_urgent_level_when_less_than_1_day(self):
        """库存不足1天时预警级别为 urgent"""
        self._inject_dish("dish-urgent", STORE_1, TENANT_A, stock_qty=3, daily_avg=10)
        # 剩余0.3天
        svc = DishLifecycleService()
        warnings = run(svc.check_sellout_warnings(STORE_1, TENANT_A))
        matching = [w for w in warnings if w.dish_id == "dish-urgent"]
        assert matching
        assert matching[0].warning_level == "urgent"

    def test_warning_level_when_1_to_2_days(self):
        """库存1-2天之间预警级别为 warning"""
        self._inject_dish("dish-warning", STORE_1, TENANT_A, stock_qty=8, daily_avg=5)
        # 剩余1.6天
        svc = DishLifecycleService()
        warnings = run(svc.check_sellout_warnings(STORE_1, TENANT_A))
        matching = [w for w in warnings if w.dish_id == "dish-warning"]
        assert matching
        assert matching[0].warning_level == "warning"

    def test_zero_daily_sales_no_warning(self):
        """日均销量为0的菜品不参与预警计算"""
        self._inject_dish("dish-zero-sales", STORE_1, TENANT_A, stock_qty=5, daily_avg=0)
        svc = DishLifecycleService()
        warnings = run(svc.check_sellout_warnings(STORE_1, TENANT_A))
        assert not any(w.dish_id == "dish-zero-sales" for w in warnings)

    def test_days_remaining_calculation(self):
        """days_remaining 计算正确"""
        self._inject_dish("dish-calc", STORE_1, TENANT_A, stock_qty=9, daily_avg=6)
        # 9/6 = 1.5天
        svc = DishLifecycleService()
        warnings = run(svc.check_sellout_warnings(STORE_1, TENANT_A))
        matching = [w for w in warnings if w.dish_id == "dish-calc"]
        assert matching
        assert abs(matching[0].days_remaining - 1.5) < 0.01

    def test_tenant_id_required(self):
        """tenant_id 为空应抛出 ValueError"""
        svc = DishLifecycleService()
        with pytest.raises(ValueError):
            run(svc.check_sellout_warnings(STORE_1, ""))


# ─── 4. 低健康分自动进入待优化 ───────────────────────────────────────────────


class TestLowHealthFlagging:
    def setup_method(self):
        _clear_lifecycle_store()
        _clear_score_store()

    def _inject_unhealthy_dish(self, dish_id, store_id, tenant_id):
        """注入低健康分菜品（毛利极低 + 高退菜率）"""
        inject_dish_lifecycle_data(dish_id, store_id, tenant_id, {
            "launched_at": _days_ago(30),
            "eval_period_sales": 10,
            "price_fen": 5000,
            "cost_fen": 4900,   # 毛利2%
            "total_sales": 10,
            "stock_qty": 20.0,
            "daily_avg_sales": 3.0,
            "return_count": 30,
            "total_orders": 50,
            "low_health_since": None,
        })
        inject_dish_score_data(dish_id, store_id, tenant_id, {
            "price_fen": 5000,
            "cost_fen": 4900,
            "total_sales": 10,
            "return_count": 30,
            "total_orders": 50,
        })

    def test_low_health_dish_gets_flagged(self):
        """低健康分菜品在夜批后被标记 low_health_since"""
        self._inject_unhealthy_dish("dish-bad", STORE_1, TENANT_A)
        svc = DishLifecycleService()
        result = run(svc.run_daily_checks(TENANT_A))
        assert "dish-bad" in result["low_health_dishes"]

    def test_healthy_dish_not_flagged(self):
        """高健康分菜品不被标记"""
        inject_dish_lifecycle_data("dish-healthy", STORE_1, TENANT_A, {
            "launched_at": _days_ago(30),
            "eval_period_sales": 100,
            "price_fen": 5000,
            "cost_fen": 2000,
            "total_sales": 100,
            "stock_qty": 50.0,
            "daily_avg_sales": 5.0,
            "return_count": 0,
            "total_orders": 100,
            "low_health_since": None,
        })
        inject_dish_score_data("dish-healthy", STORE_1, TENANT_A, {
            "price_fen": 5000,
            "cost_fen": 2000,
            "total_sales": 100,
            "return_count": 0,
            "total_orders": 100,
        })
        svc = DishLifecycleService()
        result = run(svc.run_daily_checks(TENANT_A))
        assert "dish-healthy" not in result["low_health_dishes"]


# ─── 5. 下架建议 ─────────────────────────────────────────────────────────────


class TestRemovalSuggestions:
    def setup_method(self):
        _clear_lifecycle_store()

    def _inject(self, dish_id, store_id, tenant_id, **overrides):
        defaults = {
            "launched_at": _days_ago(30),
            "eval_period_sales": 20,
            "price_fen": 5000,
            "cost_fen": 2000,
            "total_sales": 100,
            "stock_qty": 50.0,
            "daily_avg_sales": 5.0,
            "return_count": 0,
            "total_orders": 100,
            "low_health_since": None,
        }
        defaults.update(overrides)
        inject_dish_lifecycle_data(dish_id, store_id, tenant_id, defaults)

    def test_low_health_30_days_suggests_removal(self):
        """健康分低于40持续30天建议下架"""
        self._inject("dish-low", STORE_1, TENANT_A,
                     low_health_since=_days_ago(REMOVAL_LOW_HEALTH_DAYS + 1))
        svc = DishLifecycleService()
        suggestions = run(svc.generate_removal_suggestions(STORE_1, TENANT_A))
        matching = [s for s in suggestions if s.dish_id == "dish-low"]
        assert matching
        assert matching[0].priority == "high"
        assert "30天" in matching[0].reason

    def test_zero_eval_sales_suggests_removal(self):
        """评测期内零销量建议下架"""
        self._inject("dish-zero", STORE_1, TENANT_A, eval_period_sales=0)
        svc = DishLifecycleService()
        suggestions = run(svc.generate_removal_suggestions(STORE_1, TENANT_A))
        matching = [s for s in suggestions if s.dish_id == "dish-zero"]
        assert matching
        assert matching[0].priority == "high"
        assert "零销量" in matching[0].reason

    def test_critical_margin_suggests_removal(self):
        """毛利率低于10%建议下架"""
        # 毛利率 4% < 10%
        self._inject("dish-margin", STORE_1, TENANT_A,
                     price_fen=5000, cost_fen=4800)
        svc = DishLifecycleService()
        suggestions = run(svc.generate_removal_suggestions(STORE_1, TENANT_A))
        matching = [s for s in suggestions if s.dish_id == "dish-margin"]
        assert matching
        assert "毛利率" in matching[0].reason

    def test_healthy_dish_no_removal_suggestion(self):
        """健康菜品不产生下架建议"""
        self._inject("dish-good", STORE_1, TENANT_A,
                     price_fen=5000, cost_fen=2000, eval_period_sales=30)
        svc = DishLifecycleService()
        suggestions = run(svc.generate_removal_suggestions(STORE_1, TENANT_A))
        assert not any(s.dish_id == "dish-good" for s in suggestions)

    def test_suggestion_includes_evidence(self):
        """下架建议包含数据支撑(evidence)"""
        self._inject("dish-ev", STORE_1, TENANT_A, eval_period_sales=0)
        svc = DishLifecycleService()
        suggestions = run(svc.generate_removal_suggestions(STORE_1, TENANT_A))
        matching = [s for s in suggestions if s.dish_id == "dish-ev"]
        assert matching
        assert isinstance(matching[0].evidence, dict)
        assert len(matching[0].evidence) > 0

    def test_tenant_id_required(self):
        """tenant_id 为空应抛出 ValueError"""
        svc = DishLifecycleService()
        with pytest.raises(ValueError):
            run(svc.generate_removal_suggestions(STORE_1, ""))


# ─── 6. Tenant 隔离 ───────────────────────────────────────────────────────────


class TestTenantIsolation:
    def setup_method(self):
        _clear_lifecycle_store()
        _clear_score_store()

    def test_score_tenant_isolation(self):
        """不同租户菜品评分互不干扰"""
        inject_dish_score_data("dish-shared-id", STORE_1, TENANT_A, {
            "price_fen": 5000,
            "cost_fen": 2000,
            "total_sales": 100,
            "return_count": 0,
            "total_orders": 100,
        })
        inject_dish_score_data("dish-shared-id", STORE_1, TENANT_B, {
            "price_fen": 5000,
            "cost_fen": 4800,
            "total_sales": 1,
            "return_count": 50,
            "total_orders": 100,
        })
        engine = DishHealthScoreEngine()
        score_a = run(engine.score_dish("dish-shared-id", STORE_1, TENANT_A, db=None))
        score_b = run(engine.score_dish("dish-shared-id", STORE_1, TENANT_B, db=None))
        assert score_a is not None
        assert score_b is not None
        assert score_a.total_score > score_b.total_score

    def test_sellout_warning_tenant_isolation(self):
        """沽清预警按租户隔离，不同租户数据互不影响"""
        inject_dish_lifecycle_data("dish-x", STORE_1, TENANT_A, {
            "launched_at": _days_ago(30),
            "stock_qty": 3.0,
            "daily_avg_sales": 5.0,
            "price_fen": 5000,
            "cost_fen": 2000,
            "total_sales": 50,
            "eval_period_sales": 50,
            "return_count": 0,
            "total_orders": 50,
            "low_health_since": None,
        })
        # TENANT_B 有足够库存
        inject_dish_lifecycle_data("dish-x", STORE_1, TENANT_B, {
            "launched_at": _days_ago(30),
            "stock_qty": 100.0,
            "daily_avg_sales": 5.0,
            "price_fen": 5000,
            "cost_fen": 2000,
            "total_sales": 50,
            "eval_period_sales": 50,
            "return_count": 0,
            "total_orders": 50,
            "low_health_since": None,
        })
        svc = DishLifecycleService()
        warnings_a = run(svc.check_sellout_warnings(STORE_1, TENANT_A))
        warnings_b = run(svc.check_sellout_warnings(STORE_1, TENANT_B))

        assert any(w.dish_id == "dish-x" for w in warnings_a)
        assert not any(w.dish_id == "dish-x" for w in warnings_b)

    def test_eval_report_tenant_isolation(self):
        """新品评测报告按租户隔离"""
        # TENANT_A: 低销量菜品
        inject_dish_lifecycle_data("dish-y", STORE_1, TENANT_A, {
            "launched_at": _days_ago(7),
            "eval_period_sales": 0,
            "price_fen": 5000,
            "cost_fen": 2000,
            "total_sales": 0,
            "stock_qty": 10.0,
            "daily_avg_sales": 0.0,
            "return_count": 0,
            "total_orders": 0,
            "low_health_since": None,
        })
        # TENANT_B: 高销量菜品（但不应出现在TENANT_A报告中）
        inject_dish_lifecycle_data("dish-z", STORE_1, TENANT_B, {
            "launched_at": _days_ago(7),
            "eval_period_sales": 100,
            "price_fen": 5000,
            "cost_fen": 2000,
            "total_sales": 100,
            "stock_qty": 50.0,
            "daily_avg_sales": 5.0,
            "return_count": 0,
            "total_orders": 100,
            "low_health_since": None,
        })
        svc = DishLifecycleService()
        reports_a = run(svc.check_new_dish_evaluations(TENANT_A))
        # TENANT_A 只看到自己的菜品
        assert all(r.tenant_id == TENANT_A for r in reports_a)
        assert not any(r.dish_id == "dish-z" for r in reports_a)
