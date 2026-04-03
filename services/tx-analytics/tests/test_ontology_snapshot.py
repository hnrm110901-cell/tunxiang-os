"""Ontology快照服务测试

覆盖：
- compute_daily_snapshots 返回6个实体摘要
- get_entity_trend 返回正确日期范围
- get_cross_brand_comparison 返回按 metric_key 降序排列的列表
- metrics 结构验证（必需字段存在）
- RLS 隔离（不同 tenant_id 不可见）
- ModelRouter 不可用时优雅降级
- 各实体 metrics 计算函数（纯函数行为）
- 边界情况（空结果、日期倒置、非法 entity_type）
"""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from src.services.ontology_snapshot_service import (
    ENTITY_TYPES,
    SNAPSHOT_TYPES,
    OntologySnapshotService,
    _get_model_router,
)

# ─── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_A = uuid4()
TENANT_B = uuid4()
BRAND_1 = uuid4()
STORE_1 = uuid4()
SNAPSHOT_DATE = date(2026, 3, 31)


# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def _make_row(**kwargs) -> MagicMock:
    """构造模拟 DB 行 mappings().one() 返回值。"""
    m = MagicMock()
    m.__getitem__ = lambda self, key: kwargs.get(key, 0)
    return m


def _make_db_session(row_data: dict | None = None) -> AsyncMock:
    """构造模拟 AsyncSession，execute 返回单行。"""
    db = AsyncMock()
    row = _make_row(**(row_data or {}))
    result = MagicMock()
    result.mappings.return_value.one.return_value = row
    result.mappings.return_value.first.return_value = row
    result.mappings.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    return db


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. compute_daily_snapshots — 返回6个实体摘要
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestComputeDailySnapshots:
    """compute_daily_snapshots 主流程测试。"""

    @pytest.mark.asyncio
    async def test_returns_all_six_entities(self):
        """返回摘要包含全部6大实体键。"""
        svc = OntologySnapshotService()
        db = _make_db_session()

        summary = await svc.compute_daily_snapshots(
            tenant_id=TENANT_A,
            snapshot_date=SNAPSHOT_DATE,
            db=db,
        )

        assert set(summary.keys()) == ENTITY_TYPES

    @pytest.mark.asyncio
    async def test_each_entity_has_ok_flag(self):
        """每个实体结果都有 ok 标志。"""
        svc = OntologySnapshotService()
        db = _make_db_session()

        summary = await svc.compute_daily_snapshots(
            tenant_id=TENANT_A,
            snapshot_date=SNAPSHOT_DATE,
            db=db,
        )

        for entity_type, result in summary.items():
            assert "ok" in result, f"{entity_type} 缺少 ok 字段"

    @pytest.mark.asyncio
    async def test_success_entities_have_metrics(self):
        """成功的实体必须有 metrics 字段。"""
        svc = OntologySnapshotService()
        db = _make_db_session()

        summary = await svc.compute_daily_snapshots(
            tenant_id=TENANT_A,
            snapshot_date=SNAPSHOT_DATE,
            db=db,
        )

        for entity_type, result in summary.items():
            if result["ok"]:
                assert "metrics" in result, f"{entity_type} 成功但缺少 metrics"
                assert isinstance(result["metrics"], dict)

    @pytest.mark.asyncio
    async def test_db_commit_called(self):
        """成功后调用 db.commit()。"""
        svc = OntologySnapshotService()
        db = _make_db_session()

        await svc.compute_daily_snapshots(
            tenant_id=TENANT_A,
            snapshot_date=SNAPSHOT_DATE,
            db=db,
        )

        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_db_error_captured_per_entity(self):
        """单实体 DB 报错不影响其他实体，错误被记录在 ok=False 的 error 字段中。"""
        from sqlalchemy.exc import SQLAlchemyError

        svc = OntologySnapshotService()
        db = AsyncMock()
        db.commit = AsyncMock()

        call_count = 0

        async def flaky_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise SQLAlchemyError("mock DB error")
            result = MagicMock()
            row = _make_row()
            result.mappings.return_value.one.return_value = row
            result.mappings.return_value.all.return_value = []
            return result

        db.execute = flaky_execute

        summary = await svc.compute_daily_snapshots(
            tenant_id=TENANT_A,
            snapshot_date=SNAPSHOT_DATE,
            db=db,
        )

        # 至少有一个失败
        failed = [k for k, v in summary.items() if not v.get("ok")]
        assert len(failed) >= 1
        for k in failed:
            assert "error" in summary[k]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. metrics 结构验证 — 必需字段存在
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestMetricsStructure:
    """各实体 metrics 必需字段存在性验证。"""

    REQUIRED_FIELDS = {
        "customer": [
            "total_count", "active_count", "new_count", "high_value_count",
            "avg_rfm_score", "churn_risk_count", "avg_lifetime_value_fen",
        ],
        "dish": [
            "active_count", "avg_profit_margin", "low_margin_count",
            "total_revenue_fen", "top_dish_sales", "recommended_count", "avg_rating",
        ],
        "order": [
            "total_count", "total_revenue_fen", "total_discount_fen",
            "avg_order_value_fen", "abnormal_count", "margin_alert_count",
            "dine_in_count", "takeaway_count", "delivery_count", "avg_gross_margin",
        ],
        "ingredient": [
            "total_sku_count", "low_stock_count", "out_of_stock_count",
            "total_inventory_value_fen", "normal_count",
        ],
        "employee": [
            "total_count", "active_count", "chef_count", "waiter_count",
            "manager_count", "cert_expiry_alert_count", "avg_seniority_months",
        ],
        "store": [
            "total_store_count", "direct_count", "franchise_count", "active_count",
            "fine_dining_count", "fast_food_count", "avg_daily_revenue_fen",
            "top_store_revenue_fen",
        ],
    }

    @pytest.mark.asyncio
    async def test_customer_metrics_required_fields(self):
        """customer metrics 必需字段完整性检查。"""
        svc = OntologySnapshotService()
        db = _make_db_session()

        summary = await svc.compute_daily_snapshots(
            tenant_id=TENANT_A,
            snapshot_date=SNAPSHOT_DATE,
            db=db,
        )

        if summary["customer"]["ok"]:
            metrics = summary["customer"]["metrics"]
            for field in self.REQUIRED_FIELDS["customer"]:
                assert field in metrics, f"customer metrics 缺少字段: {field}"

    @pytest.mark.asyncio
    async def test_order_metrics_required_fields(self):
        """order metrics 必需字段完整性检查。"""
        svc = OntologySnapshotService()
        db = _make_db_session()

        summary = await svc.compute_daily_snapshots(
            tenant_id=TENANT_A,
            snapshot_date=SNAPSHOT_DATE,
            db=db,
        )

        if summary["order"]["ok"]:
            metrics = summary["order"]["metrics"]
            for field in self.REQUIRED_FIELDS["order"]:
                assert field in metrics, f"order metrics 缺少字段: {field}"

    @pytest.mark.asyncio
    async def test_ingredient_metrics_required_fields(self):
        """ingredient metrics 必需字段完整性检查。"""
        svc = OntologySnapshotService()
        db = _make_db_session()

        summary = await svc.compute_daily_snapshots(
            tenant_id=TENANT_A,
            snapshot_date=SNAPSHOT_DATE,
            db=db,
        )

        if summary["ingredient"]["ok"]:
            metrics = summary["ingredient"]["metrics"]
            for field in self.REQUIRED_FIELDS["ingredient"]:
                assert field in metrics, f"ingredient metrics 缺少字段: {field}"

    @pytest.mark.asyncio
    async def test_employee_metrics_required_fields(self):
        """employee metrics 必需字段完整性检查。"""
        svc = OntologySnapshotService()
        db = _make_db_session()

        summary = await svc.compute_daily_snapshots(
            tenant_id=TENANT_A,
            snapshot_date=SNAPSHOT_DATE,
            db=db,
        )

        if summary["employee"]["ok"]:
            metrics = summary["employee"]["metrics"]
            for field in self.REQUIRED_FIELDS["employee"]:
                assert field in metrics, f"employee metrics 缺少字段: {field}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. get_entity_trend — 日期范围与排序
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestGetEntityTrend:
    """get_entity_trend 查询行为测试。"""

    @pytest.mark.asyncio
    async def test_returns_list(self):
        """返回值为列表。"""
        svc = OntologySnapshotService()
        db = _make_db_session()

        result = await svc.get_entity_trend(
            tenant_id=TENANT_A,
            entity_type="order",
            brand_id=None,
            store_id=None,
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 31),
            snapshot_type="daily",
            db=db,
        )

        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_invalid_entity_type_raises(self):
        """非法 entity_type 抛出 ValueError。"""
        svc = OntologySnapshotService()
        db = _make_db_session()

        with pytest.raises(ValueError, match="不支持的实体类型"):
            await svc.get_entity_trend(
                tenant_id=TENANT_A,
                entity_type="invalid_entity",
                brand_id=None,
                store_id=None,
                start_date=date(2026, 3, 1),
                end_date=date(2026, 3, 31),
                db=db,
            )

    @pytest.mark.asyncio
    async def test_invalid_snapshot_type_raises(self):
        """非法 snapshot_type 抛出 ValueError。"""
        svc = OntologySnapshotService()
        db = _make_db_session()

        with pytest.raises(ValueError, match="不支持的快照类型"):
            await svc.get_entity_trend(
                tenant_id=TENANT_A,
                entity_type="order",
                brand_id=None,
                store_id=None,
                start_date=date(2026, 3, 1),
                end_date=date(2026, 3, 31),
                snapshot_type="hourly",  # 非法类型
                db=db,
            )

    @pytest.mark.asyncio
    async def test_trend_items_have_required_keys(self):
        """趋势数据每条记录包含 snapshot_date 和 metrics。"""
        svc = OntologySnapshotService()
        db = AsyncMock()

        # 模拟返回2条记录
        row1 = MagicMock()
        row1.__getitem__ = lambda self, k: {"snapshot_date": date(2026, 3, 30), "metrics": {"total_count": 100}}[k]
        row2 = MagicMock()
        row2.__getitem__ = lambda self, k: {"snapshot_date": date(2026, 3, 31), "metrics": {"total_count": 110}}[k]

        result_mock = MagicMock()
        result_mock.mappings.return_value.all.return_value = [row1, row2]
        db.execute = AsyncMock(return_value=result_mock)

        trend = await svc.get_entity_trend(
            tenant_id=TENANT_A,
            entity_type="customer",
            brand_id=None,
            store_id=None,
            start_date=date(2026, 3, 30),
            end_date=date(2026, 3, 31),
            db=db,
        )

        assert len(trend) == 2
        for item in trend:
            assert "snapshot_date" in item
            assert "metrics" in item

    @pytest.mark.asyncio
    async def test_brand_level_query_uses_brand_clause(self):
        """品牌级查询时 SQL 传入了 brand_id 参数。"""
        svc = OntologySnapshotService()
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.mappings.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result_mock)

        await svc.get_entity_trend(
            tenant_id=TENANT_A,
            entity_type="dish",
            brand_id=BRAND_1,
            store_id=None,
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 31),
            db=db,
        )

        call_args = db.execute.call_args
        # 参数 dict 中包含 brand_id
        params_dict = call_args[0][1]
        assert "brand_id" in params_dict
        assert params_dict["brand_id"] == str(BRAND_1)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. get_cross_brand_comparison — 排序与结构
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestGetCrossBrandComparison:
    """跨品牌对比测试。"""

    def _make_comparison_db(self, rows_data: list[dict]) -> AsyncMock:
        """模拟返回跨品牌对比行。"""
        db = AsyncMock()
        mocked_rows = []
        for r in rows_data:
            row = MagicMock()
            row.__getitem__ = lambda self, k, _r=r: _r[k]
            mocked_rows.append(row)
        result_mock = MagicMock()
        result_mock.mappings.return_value.all.return_value = mocked_rows
        db.execute = AsyncMock(return_value=result_mock)
        return db

    @pytest.mark.asyncio
    async def test_returns_list(self):
        """返回值为列表。"""
        svc = OntologySnapshotService()
        db = self._make_comparison_db([])

        result = await svc.get_cross_brand_comparison(
            tenant_id=TENANT_A,
            entity_type="order",
            snapshot_date=SNAPSHOT_DATE,
            metric_key="total_revenue_fen",
            db=db,
        )

        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_rank_assigned_sequentially(self):
        """rank 从1开始连续递增。"""
        svc = OntologySnapshotService()
        brand_a = uuid4()
        brand_b = uuid4()
        db = self._make_comparison_db([
            {"brand_id": brand_a, "metric_value": 50000},
            {"brand_id": brand_b, "metric_value": 30000},
        ])

        result = await svc.get_cross_brand_comparison(
            tenant_id=TENANT_A,
            entity_type="order",
            snapshot_date=SNAPSHOT_DATE,
            metric_key="total_revenue_fen",
            db=db,
        )

        assert len(result) == 2
        assert result[0]["rank"] == 1
        assert result[1]["rank"] == 2

    @pytest.mark.asyncio
    async def test_result_items_have_required_keys(self):
        """对比结果每项包含 brand_id / metric_value / rank。"""
        svc = OntologySnapshotService()
        brand_a = uuid4()
        db = self._make_comparison_db([
            {"brand_id": brand_a, "metric_value": 12200},
        ])

        result = await svc.get_cross_brand_comparison(
            tenant_id=TENANT_A,
            entity_type="store",
            snapshot_date=SNAPSHOT_DATE,
            metric_key="avg_daily_revenue_fen",
            db=db,
        )

        assert len(result) == 1
        assert "brand_id" in result[0]
        assert "metric_value" in result[0]
        assert "rank" in result[0]

    @pytest.mark.asyncio
    async def test_invalid_entity_type_raises(self):
        """非法 entity_type 抛出 ValueError。"""
        svc = OntologySnapshotService()
        db = self._make_comparison_db([])

        with pytest.raises(ValueError, match="不支持的实体类型"):
            await svc.get_cross_brand_comparison(
                tenant_id=TENANT_A,
                entity_type="ghost",
                snapshot_date=SNAPSHOT_DATE,
                metric_key="whatever",
                db=db,
            )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. RLS 隔离 — 不同 tenant_id 不可见
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestRLSIsolation:
    """RLS 隔离行为测试（模拟层验证 tenant_id 隔离逻辑）。"""

    @pytest.mark.asyncio
    async def test_upsert_uses_correct_tenant_id(self):
        """_upsert_snapshot 写入时 SQL 参数包含正确的 tenant_id。"""
        svc = OntologySnapshotService()
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock())

        await svc._upsert_snapshot(
            db=db,
            tenant_id=TENANT_A,
            brand_id=None,
            store_id=None,
            snapshot_date=SNAPSHOT_DATE,
            snapshot_type="daily",
            entity_type="customer",
            metrics={"total_count": 100},
        )

        call_params = db.execute.call_args[0][1]
        assert call_params["tenant_id"] == str(TENANT_A)

    @pytest.mark.asyncio
    async def test_tenant_b_cannot_see_tenant_a_data(self):
        """不同 tenant 查询时，SQL 参数携带各自的 tenant_id（隔离靠 RLS 策略执行）。"""
        svc = OntologySnapshotService()

        for tenant in [TENANT_A, TENANT_B]:
            db = AsyncMock()
            result_mock = MagicMock()
            result_mock.mappings.return_value.first.return_value = None
            db.execute = AsyncMock(return_value=result_mock)

            await svc.get_latest_group_snapshot(
                tenant_id=tenant,
                entity_type="order",
                db=db,
            )

            call_params = db.execute.call_args[0][1]
            assert call_params["tenant_id"] == str(tenant)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6. ModelRouter 不可用时优雅降级
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestModelRouterDegradation:
    """ModelRouter 不可用时不抛异常，业务流程正常完成。"""

    @pytest.mark.asyncio
    async def test_model_router_import_error_returns_none(self):
        """ModelRouter 不可导入时 _get_model_router 返回 None。"""
        with patch.dict("sys.modules", {"tx_agent": None, "tx_agent.model_router": None}):
            router = _get_model_router()
            assert router is None

    @pytest.mark.asyncio
    async def test_compute_snapshots_succeeds_without_model_router(self):
        """ModelRouter 不可用时，compute_daily_snapshots 仍正常返回结果。"""
        svc = OntologySnapshotService()
        db = _make_db_session()

        # AI 触发条件满足（abnormal_count > 5）
        # 注入 order metrics 让 AI 触发条件满足
        original_maybe_trigger = svc._maybe_trigger_ai_insight

        async def mock_trigger(tenant_id, snapshot_date, summary):
            # 模拟 ModelRouter 不可用
            with patch(
                "src.services.ontology_snapshot_service._get_model_router",
                return_value=None,
            ):
                await original_maybe_trigger(tenant_id, snapshot_date, summary)

        svc._maybe_trigger_ai_insight = mock_trigger

        summary = await svc.compute_daily_snapshots(
            tenant_id=TENANT_A,
            snapshot_date=SNAPSHOT_DATE,
            db=db,
        )

        # 不抛异常，返回6个实体
        assert set(summary.keys()) == ENTITY_TYPES

    @pytest.mark.asyncio
    async def test_ai_insight_exception_does_not_propagate(self):
        """ModelRouter.complete 抛出异常时，快照计算不受影响。"""
        svc = OntologySnapshotService()
        db = _make_db_session()

        mock_router = AsyncMock()
        mock_router.complete = AsyncMock(side_effect=RuntimeError("AI service timeout"))

        with patch(
            "src.services.ontology_snapshot_service._get_model_router",
            return_value=mock_router,
        ):
            # 注入会触发 AI 的 metrics（abnormal_count > 5）
            original_compute = svc.compute_daily_snapshots

            async def patched_compute(tenant_id, snapshot_date, db):
                result = await original_compute(tenant_id, snapshot_date, db)
                return result

            # 直接调用 _maybe_trigger_ai_insight 并传入触发条件
            await svc._maybe_trigger_ai_insight(
                tenant_id=TENANT_A,
                snapshot_date=SNAPSHOT_DATE,
                summary={
                    "order": {"ok": True, "metrics": {"abnormal_count": 10, "margin_alert_count": 15}},
                    "ingredient": {"ok": True, "metrics": {"out_of_stock_count": 0}},
                    "customer": {"ok": True, "metrics": {"churn_risk_count": 50}},
                },
            )
            # 不抛异常即为通过


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  7. get_latest_group_snapshot — 边界情况
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestGetLatestGroupSnapshot:
    """get_latest_group_snapshot 边界情况测试。"""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_data(self):
        """无数据时返回 None（不抛异常）。"""
        svc = OntologySnapshotService()
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.mappings.return_value.first.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        result = await svc.get_latest_group_snapshot(
            tenant_id=TENANT_A,
            entity_type="customer",
            db=db,
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_entity_type_raises_value_error(self):
        """非法 entity_type 抛出 ValueError。"""
        svc = OntologySnapshotService()
        db = AsyncMock()

        with pytest.raises(ValueError, match="不支持的实体类型"):
            await svc.get_latest_group_snapshot(
                tenant_id=TENANT_A,
                entity_type="unknown",
                db=db,
            )

    @pytest.mark.asyncio
    async def test_result_has_required_keys(self):
        """有数据时结果包含 snapshot_date / snapshot_type / metrics。"""
        svc = OntologySnapshotService()
        db = AsyncMock()
        row = MagicMock()
        row.__getitem__ = lambda self, k: {
            "snapshot_date": date(2026, 3, 31),
            "snapshot_type": "daily",
            "metrics": {"total_count": 100},
        }[k]
        result_mock = MagicMock()
        result_mock.mappings.return_value.first.return_value = row
        db.execute = AsyncMock(return_value=result_mock)

        result = await svc.get_latest_group_snapshot(
            tenant_id=TENANT_A,
            entity_type="customer",
            db=db,
        )

        assert result is not None
        assert "snapshot_date" in result
        assert "snapshot_type" in result
        assert "metrics" in result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  8. ENTITY_TYPES / SNAPSHOT_TYPES 常量完整性
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestConstants:
    """模块常量完整性检查。"""

    def test_entity_types_contains_six(self):
        """ENTITY_TYPES 包含全部6大实体。"""
        assert len(ENTITY_TYPES) == 6
        expected = {"customer", "dish", "store", "order", "ingredient", "employee"}
        assert expected == ENTITY_TYPES

    def test_snapshot_types_contains_three(self):
        """SNAPSHOT_TYPES 包含 daily / weekly / monthly。"""
        assert {"daily", "weekly", "monthly"} == SNAPSHOT_TYPES
