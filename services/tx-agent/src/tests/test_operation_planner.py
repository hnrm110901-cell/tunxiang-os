"""OperationPlanner 测试套件

覆盖：
  - PLAN_MODE_RULES 阈值逻辑（should_plan）
  - submit()：Plan Mode 触发/跳过，AI 影响分析，DB 写入
  - _analyze_impact()：正常解析、AI 失败降级
  - confirm() / cancel()：DB 状态流转 mock

运行：
  pytest services/tx-agent/src/tests/test_operation_planner.py -v
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.operation_planner import (
    ImpactAnalysis,
    OperationPlan,
    OperationPlanner,
    OperationStatus,
    PLAN_MODE_RULES,
    RiskLevel,
)


# ─────────────────────────────────────────────────────────────────────────────
# 辅助工具
# ─────────────────────────────────────────────────────────────────────────────

def _make_mock_router(json_text: str) -> MagicMock:
    """构造返回指定 JSON 文本的 ModelRouter mock"""
    router = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(text=json_text)]
    router.complete = AsyncMock(return_value=response)
    return router


_IMPACT_JSON_LOW = (
    '{"affected_stores": 5, "affected_employees": 0, "affected_members": 0,'
    ' "financial_impact_fen": 50000, "risk_level": "low",'
    ' "impact_summary": "影响5家门店", "warnings": [], "reversible": true}'
)

_IMPACT_JSON_HIGH = (
    '{"affected_stores": 20, "affected_employees": 50, "affected_members": 0,'
    ' "financial_impact_fen": 500000, "risk_level": "high",'
    ' "impact_summary": "高风险操作", "warnings": ["注意薪资计算精度"], "reversible": false}'
)


def _make_mock_db_record(
    plan_id: UUID,
    operation_type: str = "store.clone",
    status: str = OperationStatus.PENDING_CONFIRM.value,
    risk_level: str = RiskLevel.LOW.value,
    impact_json: dict | None = None,
    operator_id: UUID | None = None,
    expires_at: datetime | None = None,
) -> MagicMock:
    """构造 OperationPlanModel mock 记录"""
    if impact_json is None:
        impact_json = {
            "affected_stores": 5,
            "affected_employees": 0,
            "affected_members": 0,
            "financial_impact_fen": 50000,
            "risk_level": risk_level,
            "impact_summary": "影响5家门店",
            "warnings": [],
            "reversible": True,
        }
    record = MagicMock()
    record.id = plan_id
    record.tenant_id = uuid4()
    record.operation_type = operation_type
    record.operation_params = {}
    record.impact_analysis = impact_json
    record.status = status
    record.risk_level = risk_level
    record.operator_id = operator_id or uuid4()
    record.confirmed_by = None
    record.confirmed_at = None
    record.executed_at = None
    record.created_at = datetime.now(timezone.utc)
    record.expires_at = expires_at or (datetime.now(timezone.utc) + timedelta(minutes=30))
    record.is_deleted = False
    return record


def _make_mock_db(record=None) -> AsyncMock:
    """构造 AsyncSession mock，支持 execute/flush/add"""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    if record is not None:
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = record
        db.execute = AsyncMock(return_value=result_mock)
    else:
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)
    return db


# ─────────────────────────────────────────────────────────────────────────────
# 1. PLAN_MODE_RULES / should_plan()
# ─────────────────────────────────────────────────────────────────────────────

class TestPlanModeRules:
    """触发规则阈值测试"""

    def test_bulk_price_update_below_threshold_no_plan(self):
        """菜品批量改价门店数 < 3，不触发"""
        planner = OperationPlanner(model_router=MagicMock(), db=MagicMock())
        assert planner.should_plan("menu.price.bulk_update", {"store_count": 2}) is False

    def test_bulk_price_update_at_threshold_triggers(self):
        """菜品批量改价门店数 == 3，触发"""
        planner = OperationPlanner(model_router=MagicMock(), db=MagicMock())
        assert planner.should_plan("menu.price.bulk_update", {"store_count": 3}) is True

    def test_bulk_price_update_above_threshold_triggers(self):
        """菜品批量改价门店数 > 3，触发"""
        planner = OperationPlanner(model_router=MagicMock(), db=MagicMock())
        assert planner.should_plan("menu.price.bulk_update", {"store_count": 10}) is True

    def test_payroll_recalculate_always_triggers(self):
        """薪资重算：始终触发（always 规则）"""
        planner = OperationPlanner(model_router=MagicMock(), db=MagicMock())
        assert planner.should_plan("payroll.recalculate", {}) is True

    def test_store_clone_always_triggers(self):
        """快速开店克隆：始终触发（always 规则）"""
        planner = OperationPlanner(model_router=MagicMock(), db=MagicMock())
        assert planner.should_plan("store.clone", {}) is True

    def test_member_points_below_threshold_no_plan(self):
        """会员积分调整 < 100 人，不触发"""
        planner = OperationPlanner(model_router=MagicMock(), db=MagicMock())
        assert planner.should_plan("member.points.bulk_adjust", {"member_count": 99}) is False

    def test_member_points_at_threshold_triggers(self):
        """会员积分调整 >= 100 人，触发"""
        planner = OperationPlanner(model_router=MagicMock(), db=MagicMock())
        assert planner.should_plan("member.points.bulk_adjust", {"member_count": 100}) is True

    def test_role_bulk_change_below_threshold_no_plan(self):
        """角色批量变更 < 10 人，不触发"""
        planner = OperationPlanner(model_router=MagicMock(), db=MagicMock())
        assert planner.should_plan("org.role.bulk_change", {"employee_count": 9}) is False

    def test_role_bulk_change_at_threshold_triggers(self):
        """角色批量变更 >= 10 人，触发"""
        planner = OperationPlanner(model_router=MagicMock(), db=MagicMock())
        assert planner.should_plan("org.role.bulk_change", {"employee_count": 10}) is True

    def test_supply_price_below_threshold_no_plan(self):
        """食材价格调整幅度 < 20%，不触发"""
        planner = OperationPlanner(model_router=MagicMock(), db=MagicMock())
        assert planner.should_plan("supply.price.bulk_update", {"price_change_pct": 15}) is False

    def test_supply_price_at_threshold_triggers(self):
        """食材价格调整幅度 >= 20%，触发"""
        planner = OperationPlanner(model_router=MagicMock(), db=MagicMock())
        assert planner.should_plan("supply.price.bulk_update", {"price_change_pct": 20}) is True

    def test_unknown_operation_no_plan(self):
        """未知操作类型，不触发"""
        planner = OperationPlanner(model_router=MagicMock(), db=MagicMock())
        assert planner.should_plan("some.unknown.operation", {}) is False

    def test_should_plan_missing_threshold_field_treated_as_zero(self):
        """params 中缺少阈值字段时，视为 0，应返回 False（低于阈值）"""
        planner = OperationPlanner(model_router=MagicMock(), db=MagicMock())
        # store_count 缺失，视为 0，低于阈值 3
        assert planner.should_plan("menu.price.bulk_update", {}) is False


# ─────────────────────────────────────────────────────────────────────────────
# 2. submit()
# ─────────────────────────────────────────────────────────────────────────────

class TestOperationPlannerSubmit:
    """submit() 提交操作计划"""

    @pytest.mark.asyncio
    async def test_submit_below_threshold_returns_none(self):
        """未触发 Plan Mode 时返回 None"""
        planner = OperationPlanner(
            model_router=_make_mock_router(_IMPACT_JSON_LOW),
            db=_make_mock_db(),
        )
        result = await planner.submit(
            operation_type="menu.price.bulk_update",
            params={"store_count": 1},  # 低于阈值 3
            operator_id=str(uuid4()),
            tenant_id=str(uuid4()),
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_submit_creates_plan_record_in_db(self):
        """触发 Plan Mode 时应调用 db.add 并 flush"""
        db = _make_mock_db()
        # 给 flush 之后 record.id 一个模拟值
        captured_record: list = []

        def capture_add(record):
            record.id = uuid4()
            captured_record.append(record)

        db.add = MagicMock(side_effect=capture_add)

        planner = OperationPlanner(
            model_router=_make_mock_router(_IMPACT_JSON_LOW),
            db=db,
        )
        result = await planner.submit(
            operation_type="store.clone",
            params={"source_store_id": str(uuid4())},
            operator_id=str(uuid4()),
            tenant_id=str(uuid4()),
        )

        db.add.assert_called_once()
        db.flush.assert_called_once()
        assert result is not None

    @pytest.mark.asyncio
    async def test_submit_returns_plan_with_pending_status(self):
        """返回的 OperationPlan 状态应为 PENDING_CONFIRM"""
        db = _make_mock_db()

        def capture_add(record):
            record.id = uuid4()
            # 设置 record 上其他必要属性（_model_to_plan 需要读取）
            record.tenant_id = uuid4()
            record.operation_params = {}
            record.impact_analysis = {
                "affected_stores": 5,
                "affected_employees": 0,
                "affected_members": 0,
                "financial_impact_fen": 50000,
                "risk_level": "low",
                "impact_summary": "test",
                "warnings": [],
                "reversible": True,
            }
            record.confirmed_by = None
            record.confirmed_at = None
            record.executed_at = None
            record.created_at = datetime.now(timezone.utc)
            record.expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
            record.operator_id = uuid4()

        db.add = MagicMock(side_effect=capture_add)
        planner = OperationPlanner(
            model_router=_make_mock_router(_IMPACT_JSON_LOW),
            db=db,
        )
        result = await planner.submit(
            operation_type="store.clone",
            params={},
            operator_id=str(uuid4()),
            tenant_id=str(uuid4()),
        )
        assert result is not None
        assert result.status == OperationStatus.PENDING_CONFIRM

    @pytest.mark.asyncio
    async def test_submit_plan_has_plan_id(self):
        """返回的 OperationPlan 应有非空 plan_id"""
        db = _make_mock_db()
        new_id = uuid4()

        def capture_add(record):
            record.id = new_id
            record.tenant_id = uuid4()
            record.operation_params = {}
            record.impact_analysis = {
                "affected_stores": 0, "affected_employees": 0,
                "affected_members": 0, "financial_impact_fen": 0,
                "risk_level": "low", "impact_summary": "",
                "warnings": [], "reversible": True,
            }
            record.confirmed_by = None
            record.confirmed_at = None
            record.executed_at = None
            record.created_at = datetime.now(timezone.utc)
            record.expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
            record.operator_id = uuid4()

        db.add = MagicMock(side_effect=capture_add)
        planner = OperationPlanner(
            model_router=_make_mock_router(_IMPACT_JSON_LOW),
            db=db,
        )
        result = await planner.submit(
            operation_type="payroll.recalculate",
            params={},
            operator_id=str(uuid4()),
            tenant_id=str(uuid4()),
        )
        assert result is not None
        assert result.plan_id == str(new_id)


# ─────────────────────────────────────────────────────────────────────────────
# 3. _analyze_impact()
# ─────────────────────────────────────────────────────────────────────────────

class TestAnalyzeImpact:
    """_analyze_impact() AI 影响分析"""

    @pytest.mark.asyncio
    async def test_analyze_impact_parses_low_risk_response(self):
        """正常低风险响应解析正确"""
        planner = OperationPlanner(
            model_router=_make_mock_router(_IMPACT_JSON_LOW),
            db=MagicMock(),
        )
        impact = await planner._analyze_impact("store.clone", {}, str(uuid4()))
        assert impact.affected_stores == 5
        assert impact.risk_level == RiskLevel.LOW
        assert impact.reversible is True
        assert impact.impact_summary == "影响5家门店"

    @pytest.mark.asyncio
    async def test_analyze_impact_parses_high_risk_response(self):
        """高风险响应包含 warnings 和 reversible=False"""
        planner = OperationPlanner(
            model_router=_make_mock_router(_IMPACT_JSON_HIGH),
            db=MagicMock(),
        )
        impact = await planner._analyze_impact("payroll.recalculate", {}, str(uuid4()))
        assert impact.risk_level == RiskLevel.HIGH
        assert impact.reversible is False
        assert len(impact.warnings) == 1

    @pytest.mark.asyncio
    async def test_analyze_impact_ai_failure_degrades_to_high_risk(self):
        """AI 分析失败时降级为 HIGH 风险、reversible=False"""
        router = MagicMock()
        router.complete = AsyncMock(side_effect=ValueError("api error"))
        planner = OperationPlanner(model_router=router, db=MagicMock())
        impact = await planner._analyze_impact("store.clone", {}, str(uuid4()))
        assert impact.risk_level == RiskLevel.HIGH
        assert impact.reversible is False

    @pytest.mark.asyncio
    async def test_analyze_impact_bad_json_degrades_gracefully(self):
        """模型返回非法 JSON 时降级为 HIGH 风险"""
        planner = OperationPlanner(
            model_router=_make_mock_router("这不是JSON {{{{"),
            db=MagicMock(),
        )
        impact = await planner._analyze_impact("store.clone", {}, str(uuid4()))
        assert impact.risk_level == RiskLevel.HIGH

    @pytest.mark.asyncio
    async def test_analyze_impact_calls_model_router(self):
        """_analyze_impact 应调用 model_router.complete"""
        router = _make_mock_router(_IMPACT_JSON_LOW)
        planner = OperationPlanner(model_router=router, db=MagicMock())
        await planner._analyze_impact("store.clone", {}, str(uuid4()))
        router.complete.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# 4. confirm()
# ─────────────────────────────────────────────────────────────────────────────

class TestOperationPlanConfirm:
    """confirm() 确认操作计划"""

    @pytest.mark.asyncio
    async def test_confirm_pending_plan_returns_true(self):
        """正常确认待处理计划返回 True"""
        plan_id = uuid4()
        record = _make_mock_db_record(plan_id)
        db = _make_mock_db(record)

        planner = OperationPlanner(model_router=MagicMock(), db=db)
        result = await planner.confirm(str(plan_id), str(uuid4()))
        assert result is True

    @pytest.mark.asyncio
    async def test_confirm_updates_record_status_to_confirmed(self):
        """确认后 record.status 应被设为 CONFIRMED"""
        plan_id = uuid4()
        record = _make_mock_db_record(plan_id)
        db = _make_mock_db(record)

        planner = OperationPlanner(model_router=MagicMock(), db=db)
        await planner.confirm(str(plan_id), str(uuid4()))
        assert record.status == OperationStatus.CONFIRMED.value

    @pytest.mark.asyncio
    async def test_confirm_nonexistent_plan_returns_false(self):
        """不存在的 plan_id 返回 False"""
        db = _make_mock_db(record=None)
        planner = OperationPlanner(model_router=MagicMock(), db=db)
        result = await planner.confirm(str(uuid4()), str(uuid4()))
        assert result is False

    @pytest.mark.asyncio
    async def test_confirm_already_confirmed_plan_returns_false(self):
        """已确认的计划再次确认应返回 False"""
        plan_id = uuid4()
        record = _make_mock_db_record(plan_id, status=OperationStatus.CONFIRMED.value)
        db = _make_mock_db(record)

        planner = OperationPlanner(model_router=MagicMock(), db=db)
        result = await planner.confirm(str(plan_id), str(uuid4()))
        assert result is False

    @pytest.mark.asyncio
    async def test_confirm_expired_plan_returns_false(self):
        """已过期的计划确认应返回 False 并标记为 CANCELLED"""
        plan_id = uuid4()
        # expires_at 设为过去时间
        record = _make_mock_db_record(
            plan_id,
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        db = _make_mock_db(record)

        planner = OperationPlanner(model_router=MagicMock(), db=db)
        result = await planner.confirm(str(plan_id), str(uuid4()))
        assert result is False
        assert record.status == OperationStatus.CANCELLED.value

    @pytest.mark.asyncio
    async def test_confirm_sets_confirmed_by(self):
        """确认后 record.confirmed_by 应被设置"""
        plan_id = uuid4()
        confirmer_id = uuid4()
        record = _make_mock_db_record(plan_id)
        db = _make_mock_db(record)

        planner = OperationPlanner(model_router=MagicMock(), db=db)
        await planner.confirm(str(plan_id), str(confirmer_id))
        assert record.confirmed_by == confirmer_id


# ─────────────────────────────────────────────────────────────────────────────
# 5. cancel()
# ─────────────────────────────────────────────────────────────────────────────

class TestOperationPlanCancel:
    """cancel() 取消操作计划"""

    @pytest.mark.asyncio
    async def test_cancel_pending_plan_returns_true(self):
        """正常取消待处理计划返回 True"""
        plan_id = uuid4()
        record = _make_mock_db_record(plan_id)
        db = _make_mock_db(record)

        planner = OperationPlanner(model_router=MagicMock(), db=db)
        result = await planner.cancel(str(plan_id), str(uuid4()))
        assert result is True

    @pytest.mark.asyncio
    async def test_cancel_updates_record_status_to_cancelled(self):
        """取消后 record.status 应被设为 CANCELLED"""
        plan_id = uuid4()
        record = _make_mock_db_record(plan_id)
        db = _make_mock_db(record)

        planner = OperationPlanner(model_router=MagicMock(), db=db)
        await planner.cancel(str(plan_id), str(uuid4()))
        assert record.status == OperationStatus.CANCELLED.value

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_plan_returns_false(self):
        """不存在的 plan_id 取消返回 False"""
        db = _make_mock_db(record=None)
        planner = OperationPlanner(model_router=MagicMock(), db=db)
        result = await planner.cancel(str(uuid4()), str(uuid4()))
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_already_confirmed_plan_returns_false(self):
        """已确认的计划取消应返回 False（状态不是 PENDING_CONFIRM）"""
        plan_id = uuid4()
        record = _make_mock_db_record(plan_id, status=OperationStatus.CONFIRMED.value)
        db = _make_mock_db(record)

        planner = OperationPlanner(model_router=MagicMock(), db=db)
        result = await planner.cancel(str(plan_id), str(uuid4()))
        assert result is False


# ─────────────────────────────────────────────────────────────────────────────
# 6. get_plan()
# ─────────────────────────────────────────────────────────────────────────────

class TestGetPlan:
    """get_plan() 查询计划"""

    @pytest.mark.asyncio
    async def test_get_plan_returns_operation_plan(self):
        """存在的计划应返回 OperationPlan 实例"""
        plan_id = uuid4()
        record = _make_mock_db_record(plan_id)
        db = _make_mock_db(record)

        planner = OperationPlanner(model_router=MagicMock(), db=db)
        plan = await planner.get_plan(str(plan_id))
        assert plan is not None
        assert isinstance(plan, OperationPlan)
        assert plan.plan_id == str(plan_id)

    @pytest.mark.asyncio
    async def test_get_plan_nonexistent_returns_none(self):
        """不存在的 plan_id 应返回 None"""
        db = _make_mock_db(record=None)
        planner = OperationPlanner(model_router=MagicMock(), db=db)
        plan = await planner.get_plan(str(uuid4()))
        assert plan is None


# ─────────────────────────────────────────────────────────────────────────────
# 7. PLAN_MODE_RULES 配置完整性
# ─────────────────────────────────────────────────────────────────────────────

class TestPlanModeRulesConfig:
    """PLAN_MODE_RULES 配置完整性"""

    def test_all_rules_have_required_fields(self):
        """每条规则必须有 threshold_field 和 threshold_value"""
        for op_type, rule in PLAN_MODE_RULES.items():
            assert "threshold_field" in rule, f"{op_type} 缺少 threshold_field"
            assert "threshold_value" in rule, f"{op_type} 缺少 threshold_value"
            assert "description" in rule, f"{op_type} 缺少 description"

    def test_always_rules_have_zero_threshold(self):
        """always 规则 threshold_value 应为 0"""
        for op_type, rule in PLAN_MODE_RULES.items():
            if rule["threshold_field"] == "always":
                assert rule["threshold_value"] == 0, (
                    f"{op_type} always 规则 threshold_value 应为 0"
                )

    def test_six_operation_types_defined(self):
        """PLAN_MODE_RULES 应包含 6 种操作类型"""
        assert len(PLAN_MODE_RULES) == 6
