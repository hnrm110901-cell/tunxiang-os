"""通用报表引擎测试 — report_engine.py + report_registry.py

使用 mock AsyncSession 验证:
1. ReportRegistry 注册与查询
2. ReportEngine 执行报表(含金额转换)
3. ReportEngine 参数校验(缺少必填参数)
4. ReportEngine 报表不存在异常
5. ReportRenderer.to_json 输出格式
6. ReportRenderer.to_csv 输出格式
7. ReportRenderer.to_summary 文字摘要
8. ReportScheduler 创建与列出定时任务
9. ReportScheduler 执行定时任务
10. 多维度交叉查询(门店x日期)
"""
import os
import sys
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.report_engine import (
    DimensionDef,
    FilterDef,
    MetricDef,
    ReportCategory,
    ReportDefinition,
    ReportEngine,
    ReportInactiveError,
    ReportNotFoundError,
    ReportParamError,
    ReportRenderer,
    ReportResult,
    ReportScheduler,
)
from services.report_registry import ReportRegistry, create_default_registry

# ─── Mock 工具 ───

def _make_mock_db(rows: list[dict], scalar_value=None):
    """构建 mock AsyncSession"""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value = rows
    mock_result.mappings.return_value.first.return_value = rows[0] if rows else None
    mock_result.scalar.return_value = scalar_value
    mock_db.execute = AsyncMock(return_value=mock_result)
    return mock_db


def _make_simple_report() -> ReportDefinition:
    """构建一个简单测试报表定义"""
    return ReportDefinition(
        report_id="test_revenue",
        name="测试营收报表",
        category=ReportCategory.REVENUE,
        description="测试用营收报表",
        sql_template="""
            SELECT DATE(created_at) AS report_date,
                   COALESCE(SUM(total_fen), 0) AS revenue_fen,
                   COUNT(*) AS order_count
            FROM orders
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND DATE(created_at) = :target_date
              AND status = 'paid'
              AND is_deleted = FALSE
            GROUP BY DATE(created_at)
        """,
        dimensions=[DimensionDef(name="report_date", label="日期")],
        metrics=[
            MetricDef(name="revenue_fen", label="营收(分)", unit="yuan", is_money_fen=True),
            MetricDef(name="order_count", label="订单数", unit="count"),
        ],
        filters=[
            FilterDef(name="store_id", label="门店", field_type="string", required=True),
            FilterDef(name="target_date", label="日期", field_type="date", required=True),
        ],
        default_sort="revenue_fen",
        permissions=["admin", "store_manager"],
    )


# ─── 1. 注册中心测试 ───

def test_registry_register_and_get():
    """注册报表后能通过ID获取"""
    registry = ReportRegistry()
    report_def = _make_simple_report()
    registry.register(report_def)

    assert registry.count() == 1
    retrieved = registry.get("test_revenue")
    assert retrieved is not None
    assert retrieved.name == "测试营收报表"
    assert retrieved.category == ReportCategory.REVENUE


def test_registry_get_by_category():
    """按分类查询返回正确报表"""
    registry = ReportRegistry()
    report_def = _make_simple_report()
    registry.register(report_def)

    revenue_reports = registry.get_by_category("revenue")
    assert len(revenue_reports) == 1
    assert revenue_reports[0].report_id == "test_revenue"

    dish_reports = registry.get_by_category("dish")
    assert len(dish_reports) == 0


def test_registry_duplicate_raises():
    """重复注册应抛出异常"""
    registry = ReportRegistry()
    report_def = _make_simple_report()
    registry.register(report_def)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(report_def)


def test_default_registry_has_builtin_reports():
    """默认注册中心应包含所有内置报表"""
    registry = create_default_registry()
    assert registry.count() >= 18  # 至少18个内置报表
    categories = registry.categories()
    assert "revenue" in categories
    assert "dish" in categories
    assert "audit" in categories
    assert "margin" in categories


# ─── 2. 报表引擎测试 ───

@pytest.mark.asyncio
async def test_engine_execute_report():
    """执行报表返回正确结果(含金额fen→yuan转换)"""
    registry = ReportRegistry()
    registry.register(_make_simple_report())
    engine = ReportEngine(registry=registry)

    mock_db = _make_mock_db([
        {"report_date": date(2026, 3, 27), "revenue_fen": 150000, "order_count": 50},
    ])

    result = await engine.execute_report(
        report_id="test_revenue",
        params={"store_id": "store_001", "target_date": "2026-03-27"},
        tenant_id="tenant_001",
        db=mock_db,
    )

    assert result.report_id == "test_revenue"
    assert result.report_name == "测试营收报表"
    assert len(result.rows) == 1

    row = result.rows[0]
    # 原始分值保留
    assert row["revenue_fen"] == 150000
    # 自动转换为元
    assert row["revenue_yuan"] == 1500.00
    # 非金额字段不变
    assert row["order_count"] == 50


@pytest.mark.asyncio
async def test_engine_missing_required_param():
    """缺少必填参数应抛出 ReportParamError"""
    registry = ReportRegistry()
    registry.register(_make_simple_report())
    engine = ReportEngine(registry=registry)

    mock_db = _make_mock_db([])

    with pytest.raises(ReportParamError, match="Missing required parameter"):
        await engine.execute_report(
            report_id="test_revenue",
            params={"store_id": "store_001"},  # 缺少 target_date
            tenant_id="tenant_001",
            db=mock_db,
        )


@pytest.mark.asyncio
async def test_engine_report_not_found():
    """查询不存在的报表应抛出 ReportNotFoundError"""
    registry = ReportRegistry()
    engine = ReportEngine(registry=registry)
    mock_db = _make_mock_db([])

    with pytest.raises(ReportNotFoundError):
        await engine.execute_report(
            report_id="nonexistent",
            params={},
            tenant_id="tenant_001",
            db=mock_db,
        )


@pytest.mark.asyncio
async def test_engine_inactive_report():
    """停用的报表应抛出 ReportInactiveError"""
    report_def = _make_simple_report()
    report_def.is_active = False

    registry = ReportRegistry()
    registry.register(report_def)
    engine = ReportEngine(registry=registry)
    mock_db = _make_mock_db([])

    with pytest.raises(ReportInactiveError):
        await engine.execute_report(
            report_id="test_revenue",
            params={"store_id": "s1", "target_date": "2026-03-27"},
            tenant_id="tenant_001",
            db=mock_db,
        )


# ─── 3. 渲染器测试 ───

def test_renderer_to_json():
    """to_json 返回标准JSON结构"""
    result = ReportResult(
        report_id="test_revenue",
        report_name="测试营收报表",
        executed_at=datetime(2026, 3, 27, 10, 0, 0, tzinfo=timezone.utc),
        params={"store_id": "store_001"},
        columns=["report_date", "revenue_fen", "order_count"],
        rows=[{"report_date": "2026-03-27", "revenue_yuan": 1500.0, "order_count": 50}],
        total_rows=1,
    )

    json_output = ReportRenderer.to_json(result)
    assert json_output["report_id"] == "test_revenue"
    assert json_output["total_rows"] == 1
    assert len(json_output["rows"]) == 1
    assert json_output["executed_at"] == "2026-03-27T10:00:00+00:00"


def test_renderer_to_csv():
    """to_csv 返回正确的CSV格式"""
    result = ReportResult(
        report_id="test_revenue",
        report_name="测试营收报表",
        executed_at=datetime(2026, 3, 27, 10, 0, 0, tzinfo=timezone.utc),
        params={},
        columns=["report_date", "revenue_yuan", "order_count"],
        rows=[
            {"report_date": "2026-03-27", "revenue_yuan": 1500.0, "order_count": 50},
            {"report_date": "2026-03-28", "revenue_yuan": 1800.0, "order_count": 60},
        ],
        total_rows=2,
    )

    csv_output = ReportRenderer.to_csv(result)
    lines = csv_output.strip().split("\n")
    assert len(lines) == 3  # header + 2 data rows
    assert "report_date" in lines[0]
    assert "1500.0" in lines[1]


def test_renderer_to_csv_empty():
    """空结果集to_csv返回空字符串"""
    result = ReportResult(
        report_id="test_revenue",
        report_name="测试",
        executed_at=datetime(2026, 3, 27, tzinfo=timezone.utc),
        params={},
        columns=[],
        rows=[],
        total_rows=0,
    )
    assert ReportRenderer.to_csv(result) == ""


def test_renderer_to_summary():
    """to_summary 返回可读的中文摘要"""
    result = ReportResult(
        report_id="test_revenue",
        report_name="测试营收报表",
        executed_at=datetime(2026, 3, 27, 10, 0, 0, tzinfo=timezone.utc),
        params={"store_id": "store_001"},
        columns=["report_date", "revenue_yuan"],
        rows=[
            {"report_date": "2026-03-27", "revenue_yuan": 1500.0},
        ],
        total_rows=1,
    )

    summary = ReportRenderer.to_summary(result)
    assert "测试营收报表" in summary
    assert "总行数: 1" in summary
    assert "store_001" in summary


# ─── 4. 调度器测试 ───

@pytest.mark.asyncio
async def test_scheduler_create_and_list():
    """创建定时任务后能从列表中查到"""
    registry = ReportRegistry()
    registry.register(_make_simple_report())
    engine = ReportEngine(registry=registry)
    renderer = ReportRenderer()
    scheduler = ReportScheduler(engine=engine, renderer=renderer)

    mock_db = _make_mock_db([])

    config = await scheduler.schedule_report(
        report_id="test_revenue",
        cron_expression="0 8 * * *",
        recipients=["user_001"],
        channel="webhook",
        tenant_id="tenant_001",
        db=mock_db,
    )

    assert config.report_id == "test_revenue"
    assert config.cron_expression == "0 8 * * *"

    schedules = await scheduler.get_schedule_list("tenant_001")
    assert len(schedules) == 1
    assert schedules[0]["report_id"] == "test_revenue"


@pytest.mark.asyncio
async def test_scheduler_run_scheduled():
    """执行定时任务返回成功结果"""
    registry = ReportRegistry()
    registry.register(_make_simple_report())
    engine = ReportEngine(registry=registry)
    renderer = ReportRenderer()
    scheduler = ReportScheduler(engine=engine, renderer=renderer)

    mock_db = _make_mock_db([
        {"report_date": date(2026, 3, 27), "revenue_fen": 100000, "order_count": 30},
    ])

    await scheduler.schedule_report(
        report_id="test_revenue",
        cron_expression="0 8 * * *",
        recipients=["user_001"],
        channel="webhook",
        tenant_id="tenant_001",
        db=mock_db,
        params={"store_id": "store_001", "target_date": "2026-03-27"},
    )

    results = await scheduler.run_scheduled("tenant_001", mock_db)
    assert len(results) == 1
    assert results[0]["status"] == "success"
    assert results[0]["rows_generated"] == 1


# ─── 5. 多维度交叉查询 ───

@pytest.mark.asyncio
async def test_cross_dimension_store_date():
    """多维度交叉查询(门店x日期)正确执行"""
    cross_report = ReportDefinition(
        report_id="cross_store_date",
        name="门店x日期交叉",
        category=ReportCategory.REVENUE,
        description="测试多维度交叉",
        sql_template="""
            SELECT s.store_name, DATE(o.created_at) AS report_date,
                   COALESCE(SUM(o.total_fen), 0) AS revenue_fen
            FROM orders o
            JOIN stores s ON s.id = o.store_id
            WHERE o.tenant_id = :tenant_id
              AND DATE(o.created_at) BETWEEN :start_date AND :end_date
              AND o.status = 'paid'
              AND o.is_deleted = FALSE
            GROUP BY s.store_name, DATE(o.created_at)
        """,
        dimensions=[
            DimensionDef(name="store_name", label="门店"),
            DimensionDef(name="report_date", label="日期"),
        ],
        metrics=[
            MetricDef(name="revenue_fen", label="营收(分)", unit="yuan", is_money_fen=True),
        ],
        filters=[
            FilterDef(name="start_date", label="开始日期", field_type="date", required=True),
            FilterDef(name="end_date", label="结束日期", field_type="date", required=True),
        ],
        default_sort="revenue_fen",
    )

    registry = ReportRegistry()
    registry.register(cross_report)
    engine = ReportEngine(registry=registry)

    mock_db = _make_mock_db([
        {"store_name": "旗舰店", "report_date": date(2026, 3, 27), "revenue_fen": 200000},
        {"store_name": "旗舰店", "report_date": date(2026, 3, 28), "revenue_fen": 180000},
        {"store_name": "分店A", "report_date": date(2026, 3, 27), "revenue_fen": 120000},
    ])

    result = await engine.execute_report(
        report_id="cross_store_date",
        params={"start_date": "2026-03-27", "end_date": "2026-03-28"},
        tenant_id="tenant_001",
        db=mock_db,
    )

    assert len(result.rows) == 3
    # 验证金额转换
    assert result.rows[0]["revenue_yuan"] == 2000.00
    assert result.rows[2]["revenue_yuan"] == 1200.00
    # 验证维度数据保留
    assert result.rows[0]["store_name"] == "旗舰店"


# ─── 6. 引擎元数据 ───

@pytest.mark.asyncio
async def test_engine_list_reports():
    """list_reports 返回报表目录"""
    registry = create_default_registry()
    engine = ReportEngine(registry=registry)

    all_reports = await engine.list_reports()
    assert len(all_reports) >= 18

    revenue_reports = await engine.list_reports(category="revenue")
    assert len(revenue_reports) >= 5
    for r in revenue_reports:
        assert r["category"] == "revenue"


@pytest.mark.asyncio
async def test_engine_get_metadata():
    """get_report_metadata 返回完整元数据"""
    registry = create_default_registry()
    engine = ReportEngine(registry=registry)

    meta = await engine.get_report_metadata("rev_daily_summary")
    assert meta["report_id"] == "rev_daily_summary"
    assert meta["name"] == "日营收汇总"
    assert len(meta["filters"]) >= 2
    assert len(meta["metrics"]) >= 2
    assert any(m["is_money_fen"] for m in meta["metrics"])
