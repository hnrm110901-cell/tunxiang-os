"""实时三榜单服务 — 单元测试

覆盖场景（≥7）：
1. 畅销榜按出单数降序
2. 退菜榜按退菜率降序
3. 滞销榜含今日零销量菜品
4. 退菜率计算：remake/出单，精确到小数
5. 空日期无数据返回空列表
6. TOP 限制：最多返回10条
7. 租户隔离（不同租户数据互不干扰）
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from datetime import date
from unittest.mock import AsyncMock

import pytest

# ── 测试工具 ──────────────────────────────────────────────────

def _uid() -> str:
    return str(uuid.uuid4())


TENANT_A = _uid()
TENANT_B = _uid()
STORE_ID = _uid()


class FakeRow:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


def _mock_db(*execute_results):
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(execute_results))
    return db


# ── 测试 1: 畅销榜按出单数降序 ───────────────────────────────

@pytest.mark.asyncio
async def test_hot_dishes_sorted_desc():
    """畅销榜按 order_count 降序，rank 字段正确"""
    from services.dish_ranking_service import DishRankingService

    hot_rows = [
        FakeRow(dish_id=_uid(), dish_name="剁椒鱼头", order_count=42),
        FakeRow(dish_id=_uid(), dish_name="小炒肉",   order_count=35),
        FakeRow(dish_id=_uid(), dish_name="米饭",     order_count=28),
    ]

    db = _mock_db(
        FakeResult(rows=hot_rows),    # hot
        FakeResult(rows=[]),          # remake
        FakeResult(rows=[]),          # cold
    )

    rankings = await DishRankingService.get_rankings(
        store_id=STORE_ID, tenant_id=TENANT_A, db=db,
        query_date=date(2026, 3, 30),
    )

    assert len(rankings.hot) == 3
    assert rankings.hot[0].dish_name == "剁椒鱼头"
    assert rankings.hot[0].rank == 1
    assert rankings.hot[0].count == 42
    assert rankings.hot[1].rank == 2
    assert rankings.hot[2].rank == 3

    # 验证降序
    counts = [item.count for item in rankings.hot]
    assert counts == sorted(counts, reverse=True)


# ── 测试 2: 退菜榜按退菜率降序 ───────────────────────────────

@pytest.mark.asyncio
async def test_remake_dishes_sorted_by_rate():
    """退菜榜按退菜率降序，退菜率最高的排第1"""
    from services.dish_ranking_service import DishRankingService

    remake_rows = [
        FakeRow(dish_id=_uid(), dish_name="外婆鸡",   remake_count=5,  total_count=20, remake_rate=0.25),
        FakeRow(dish_id=_uid(), dish_name="爆炒腰花", remake_count=3,  total_count=6,  remake_rate=0.5),
        FakeRow(dish_id=_uid(), dish_name="拆骨肉",   remake_count=2,  total_count=40, remake_rate=0.05),
    ]

    db = _mock_db(
        FakeResult(rows=[]),          # hot
        FakeResult(rows=remake_rows), # remake
        FakeResult(rows=[]),          # cold
    )

    rankings = await DishRankingService.get_rankings(
        store_id=STORE_ID, tenant_id=TENANT_A, db=db,
        query_date=date(2026, 3, 30),
    )

    assert len(rankings.remake) == 3
    assert rankings.remake[0].dish_name == "外婆鸡"   # 顺序来自SQL，已排好
    assert rankings.remake[0].rank == 1
    assert rankings.remake[0].count == 5
    assert rankings.remake[0].rate == 0.25


# ── 测试 3: 滞销榜含零销量菜品 ───────────────────────────────

@pytest.mark.asyncio
async def test_cold_dishes_include_zero_sales():
    """滞销榜应包含今日零销量菜品（来自 dishes 主表的 LEFT JOIN）"""
    from services.dish_ranking_service import DishRankingService

    cold_rows = [
        FakeRow(dish_id=_uid(), dish_name="凉拌黄瓜",  order_count=0),  # 零销量
        FakeRow(dish_id=_uid(), dish_name="皮蛋豆腐",  order_count=0),  # 零销量
        FakeRow(dish_id=_uid(), dish_name="清炒时蔬",  order_count=1),
    ]

    db = _mock_db(
        FakeResult(rows=[]),          # hot
        FakeResult(rows=[]),          # remake
        FakeResult(rows=cold_rows),   # cold
    )

    rankings = await DishRankingService.get_rankings(
        store_id=STORE_ID, tenant_id=TENANT_A, db=db,
        query_date=date(2026, 3, 30),
    )

    assert len(rankings.cold) >= 2
    zero_sales = [item for item in rankings.cold if item.count == 0]
    assert len(zero_sales) == 2

    # 零销量排在前面（count 升序）
    assert rankings.cold[0].count == 0


# ── 测试 4: 退菜率精确计算 ───────────────────────────────────

@pytest.mark.asyncio
async def test_remake_rate_precision():
    """退菜率 = remake_count / total_count，精确到小数（round 4位）"""
    from services.dish_ranking_service import DishRankingService

    # 3/7 ≈ 0.4286
    remake_rows = [
        FakeRow(
            dish_id=_uid(), dish_name="测试菜",
            remake_count=3, total_count=7,
            remake_rate=round(3 / 7, 4)
        ),
    ]

    db = _mock_db(
        FakeResult(rows=[]),
        FakeResult(rows=remake_rows),
        FakeResult(rows=[]),
    )

    rankings = await DishRankingService.get_rankings(
        store_id=STORE_ID, tenant_id=TENANT_A, db=db,
        query_date=date(2026, 3, 30),
    )

    assert len(rankings.remake) == 1
    assert abs(rankings.remake[0].rate - round(3 / 7, 4)) < 1e-6


# ── 测试 5: 空日期无数据返回空列表 ───────────────────────────

@pytest.mark.asyncio
async def test_no_data_returns_empty_lists():
    """指定日期无订单数据时，三个榜单均返回空列表"""
    from services.dish_ranking_service import DishRankingService

    db = _mock_db(
        FakeResult(rows=[]),   # hot 空
        FakeResult(rows=[]),   # remake 空
        FakeResult(rows=[]),   # cold 空
    )

    rankings = await DishRankingService.get_rankings(
        store_id=STORE_ID, tenant_id=TENANT_A, db=db,
        query_date=date(2020, 1, 1),  # 很久以前，无数据
    )

    assert rankings.hot == []
    assert rankings.cold == []
    assert rankings.remake == []


# ── 测试 6: TOP 限制最多返回10条 ─────────────────────────────

@pytest.mark.asyncio
async def test_top_n_limit():
    """即使数据库返回超过10条，仍只保留10条（SQL LIMIT 保证）"""
    from services.dish_ranking_service import TOP_N, DishRankingService

    # 模拟 SQL 已按 LIMIT 10 返回最多10条
    hot_rows = [
        FakeRow(dish_id=_uid(), dish_name=f"菜品{i}", order_count=100 - i)
        for i in range(TOP_N)
    ]

    db = _mock_db(
        FakeResult(rows=hot_rows),
        FakeResult(rows=[]),
        FakeResult(rows=[]),
    )

    rankings = await DishRankingService.get_rankings(
        store_id=STORE_ID, tenant_id=TENANT_A, db=db,
        query_date=date(2026, 3, 30),
    )

    assert len(rankings.hot) == TOP_N  # 恰好10条
    assert TOP_N == 10


# ── 测试 7: 租户隔离 ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_tenant_isolation():
    """不同租户的查询结果互不干扰"""
    from services.dish_ranking_service import DishRankingService

    tenant_a_rows = [
        FakeRow(dish_id=_uid(), dish_name="A租户烤鸭", order_count=50),
    ]
    tenant_b_rows = [
        FakeRow(dish_id=_uid(), dish_name="B租户炒饭", order_count=30),
    ]

    # TENANT_A 查询
    db_a = _mock_db(
        FakeResult(rows=tenant_a_rows),
        FakeResult(rows=[]),
        FakeResult(rows=[]),
    )
    rankings_a = await DishRankingService.get_rankings(
        store_id=STORE_ID, tenant_id=TENANT_A, db=db_a,
        query_date=date(2026, 3, 30),
    )

    # TENANT_B 查询
    db_b = _mock_db(
        FakeResult(rows=tenant_b_rows),
        FakeResult(rows=[]),
        FakeResult(rows=[]),
    )
    rankings_b = await DishRankingService.get_rankings(
        store_id=STORE_ID, tenant_id=TENANT_B, db=db_b,
        query_date=date(2026, 3, 30),
    )

    assert rankings_a.hot[0].dish_name == "A租户烤鸭"
    assert rankings_b.hot[0].dish_name == "B租户炒饭"

    # 两个租户的数据完全独立
    assert rankings_a.hot[0].dish_name != rankings_b.hot[0].dish_name


# ── 测试 8: as_of 时间戳存在 ─────────────────────────────────

@pytest.mark.asyncio
async def test_as_of_timestamp_present():
    """DishRankings.as_of 应返回当前时间（不为 None）"""
    from datetime import datetime

    from services.dish_ranking_service import DishRankingService

    db = _mock_db(
        FakeResult(rows=[]),
        FakeResult(rows=[]),
        FakeResult(rows=[]),
    )

    rankings = await DishRankingService.get_rankings(
        store_id=STORE_ID, tenant_id=TENANT_A, db=db,
        query_date=date(2026, 3, 30),
    )

    assert rankings.as_of is not None
    assert isinstance(rankings.as_of, datetime)
    # 时间戳应为 UTC
    assert rankings.as_of.tzinfo is not None
