"""统一SQL查询层测试 — sql_queries.py

使用 mock AsyncSession 验证:
1. query_daily_revenue 正确解析营收数据
2. query_order_count 返回分状态统计
3. query_dish_sales 返回菜品明细列表
4. query_hourly_distribution 返回小时分布
5. query_payment_breakdown 计算支付占比
6. query_table_sessions 计算翻台率
7. query_returns 汇总退菜数据
8. query_alerts_today 返回排序后告警
"""

import os
import sys
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.sql_queries import (
    query_alerts_today,
    query_daily_revenue,
    query_dish_sales,
    query_hourly_distribution,
    query_order_count,
    query_payment_breakdown,
    query_returns,
    query_table_sessions,
)

# ─── Mock 数据库会话工具 ───


def _make_mock_db(rows: list[dict], scalar_value=None):
    """构建 mock AsyncSession，返回预设行数据"""
    mock_db = AsyncMock()

    # 构建 mappings 返回
    mapping_results = [MagicMock(**r, __getitem__=lambda self, k: getattr(self, k)) for r in rows]

    # 更简单的方式: 直接让 mappings().all() 返回 rows
    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value = rows
    mock_result.mappings.return_value.first.return_value = rows[0] if rows else None
    mock_result.scalar.return_value = scalar_value

    mock_db.execute = AsyncMock(return_value=mock_result)
    return mock_db


def _make_multi_execute_db(results_list: list):
    """构建支持多次 execute 调用的 mock db，每次调用返回不同结果"""
    mock_db = AsyncMock()
    mock_results = []
    for rows, scalar_val in results_list:
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = rows
        mock_result.mappings.return_value.first.return_value = rows[0] if rows else None
        mock_result.scalar.return_value = scalar_val
        mock_results.append(mock_result)

    mock_db.execute = AsyncMock(side_effect=mock_results)
    return mock_db


# ═══════════════════════════════════════════════
# 1. query_daily_revenue
# ═══════════════════════════════════════════════


class TestQueryDailyRevenue:
    @pytest.mark.asyncio
    async def test_returns_revenue_and_count(self):
        """正常查询返回营收和订单数"""
        db = _make_mock_db([{"revenue_fen": 856000, "order_count": 128}])

        result = await query_daily_revenue("store-001", date(2026, 3, 27), "tenant-01", db)

        assert result["revenue_fen"] == 856000
        assert result["order_count"] == 128
        assert result["avg_ticket_fen"] == 856000 // 128

    @pytest.mark.asyncio
    async def test_zero_orders_returns_zero_avg(self):
        """零订单时客单价为0"""
        db = _make_mock_db([{"revenue_fen": 0, "order_count": 0}])

        result = await query_daily_revenue("store-001", date(2026, 3, 27), "tenant-01", db)

        assert result["revenue_fen"] == 0
        assert result["order_count"] == 0
        assert result["avg_ticket_fen"] == 0

    @pytest.mark.asyncio
    async def test_no_rows_returns_defaults(self):
        """无查询结果返回默认值"""
        db = _make_mock_db([])

        result = await query_daily_revenue("store-001", date(2026, 3, 27), "tenant-01", db)

        assert result["revenue_fen"] == 0
        assert result["order_count"] == 0


# ═══════════════════════════════════════════════
# 2. query_order_count
# ═══════════════════════════════════════════════


class TestQueryOrderCount:
    @pytest.mark.asyncio
    async def test_returns_status_breakdown(self):
        """返回各状态订单数"""
        db = _make_mock_db(
            [
                {
                    "total": 150,
                    "paid": 128,
                    "cancelled": 12,
                    "refunded": 10,
                }
            ]
        )

        result = await query_order_count("store-001", date(2026, 3, 27), "tenant-01", db)

        assert result["total"] == 150
        assert result["paid"] == 128
        assert result["cancelled"] == 12
        assert result["refunded"] == 10


# ═══════════════════════════════════════════════
# 3. query_dish_sales
# ═══════════════════════════════════════════════


class TestQueryDishSales:
    @pytest.mark.asyncio
    async def test_returns_dish_list(self):
        """返回菜品销售明细"""
        db = _make_mock_db(
            [
                {
                    "dish_id": "dish-001",
                    "dish_name": "剁椒鱼头",
                    "category": "招牌菜",
                    "sales_qty": 45,
                    "sales_amount_fen": 585000,
                },
                {
                    "dish_id": "dish-002",
                    "dish_name": "小炒肉",
                    "category": "湘菜",
                    "sales_qty": 38,
                    "sales_amount_fen": 228000,
                },
            ]
        )

        result = await query_dish_sales(
            "store-001",
            (date(2026, 3, 20), date(2026, 3, 27)),
            "tenant-01",
            db,
        )

        assert len(result) == 2
        assert result[0]["dish_name"] == "剁椒鱼头"
        assert result[0]["sales_qty"] == 45
        assert result[0]["sales_amount_fen"] == 585000


# ═══════════════════════════════════════════════
# 4. query_hourly_distribution
# ═══════════════════════════════════════════════


class TestQueryHourlyDistribution:
    @pytest.mark.asyncio
    async def test_returns_hourly_data(self):
        """返回按小时分布"""
        db = _make_mock_db(
            [
                {"hour": 11, "revenue_fen": 120000, "order_count": 15},
                {"hour": 12, "revenue_fen": 280000, "order_count": 35},
                {"hour": 18, "revenue_fen": 202000, "order_count": 28},
            ]
        )

        result = await query_hourly_distribution("store-001", date(2026, 3, 27), "tenant-01", db)

        assert len(result) == 3
        assert result[0]["hour"] == 11
        assert result[1]["revenue_fen"] == 280000


# ═══════════════════════════════════════════════
# 5. query_payment_breakdown
# ═══════════════════════════════════════════════


class TestQueryPaymentBreakdown:
    @pytest.mark.asyncio
    async def test_calculates_pct(self):
        """支付方式占比正确计算"""
        db = _make_mock_db(
            [
                {"payment_method": "wechat", "amount_fen": 600000, "count": 80},
                {"payment_method": "alipay", "amount_fen": 300000, "count": 35},
                {"payment_method": "cash", "amount_fen": 100000, "count": 13},
            ]
        )

        result = await query_payment_breakdown("store-001", date(2026, 3, 27), "tenant-01", db)

        assert len(result) == 3
        assert result[0]["payment_method"] == "wechat"
        assert result[0]["pct"] == 60.0  # 600000 / 1000000 * 100


# ═══════════════════════════════════════════════
# 6. query_table_sessions
# ═══════════════════════════════════════════════


class TestQueryTableSessions:
    @pytest.mark.asyncio
    async def test_calculates_turnover(self):
        """翻台率正确计算"""
        # 两次 execute: 第一次查桌台总数，第二次查会话
        db = _make_multi_execute_db(
            [
                ([], 20),  # total_tables = 20
                ([{"occupied_sessions": 36, "avg_duration_minutes": 45.5}], None),
            ]
        )

        result = await query_table_sessions("store-001", date(2026, 3, 27), "tenant-01", db)

        assert result["total_tables"] == 20
        assert result["occupied_sessions"] == 36
        assert result["turnover_rate"] == 1.8  # 36 / 20
        assert result["avg_duration_minutes"] == 45.5


# ═══════════════════════════════════════════════
# 7. query_returns
# ═══════════════════════════════════════════════


class TestQueryReturns:
    @pytest.mark.asyncio
    async def test_returns_summary(self):
        """退菜汇总正确"""
        db = _make_multi_execute_db(
            [
                # 按菜品汇总
                (
                    [
                        {"dish_id": "d1", "dish_name": "剁椒鱼头", "return_qty": 3, "return_amount_fen": 39000},
                        {"dish_id": "d2", "dish_name": "小炒肉", "return_qty": 1, "return_amount_fen": 6000},
                    ],
                    None,
                ),
                # 按原因汇总
                (
                    [
                        {"reason": "taste", "count": 2},
                        {"reason": "slow", "count": 2},
                    ],
                    None,
                ),
            ]
        )

        result = await query_returns(
            "store-001",
            (date(2026, 3, 20), date(2026, 3, 27)),
            "tenant-01",
            db,
        )

        assert result["total_return_qty"] == 4
        assert result["total_return_amount_fen"] == 45000
        assert len(result["by_dish"]) == 2
        assert len(result["by_reason"]) == 2


# ═══════════════════════════════════════════════
# 8. query_alerts_today
# ═══════════════════════════════════════════════


class TestQueryAlertsToday:
    @pytest.mark.asyncio
    async def test_returns_sorted_alerts(self):
        """告警按严重级别排序返回"""
        now = datetime(2026, 3, 27, 12, 0, tzinfo=timezone.utc)
        db = _make_mock_db(
            [
                {
                    "id": "a1",
                    "type": "discount_anomaly",
                    "severity": "critical",
                    "title": "异常折扣",
                    "detail": "8号桌全单5折",
                    "time": now,
                    "status": "pending",
                    "action_required": True,
                },
                {
                    "id": "a2",
                    "type": "stockout",
                    "severity": "warning",
                    "title": "临近售罄",
                    "detail": "小龙虾剩3份",
                    "time": now,
                    "status": "acknowledged",
                    "action_required": False,
                },
            ]
        )

        result = await query_alerts_today("store-001", "tenant-01", db)

        assert len(result) == 2
        assert result[0]["severity"] == "critical"
        assert result[0]["action_required"] is True
