"""test_d2_roi_fields.py —— Sprint D2 ROI 三字段 + mv_agent_roi_monthly

测试点（不依赖真实 DB，纯 Python 逻辑）：
  1. AgentResult 新增 ROI 字段（saved_labor_hours / prevented_loss_fen /
     improved_kpi / roi_evidence）默认值正确
  2. decision_log_service.log_skill_result 从 AgentResult 提取 ROI 字段
     （mock db.add 检查 AgentDecisionLog 实例被创建时带 ROI 值）
  3. 向后兼容：旧代码未填 ROI 字段时，仍走默认 0/{} 不报错
  4. 类型校验：improved_kpi/roi_evidence 非 dict 时降级为 {}
  5. 非负约束：负数 saved_labor_hours / prevented_loss_fen 在 ORM 层无校验
     （交由 DB CHECK 约束，v264 迁移已加）
  6. v264 / v265 迁移 SQL 静态验证（构造 Alembic env，不实际跑）
"""
from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base import AgentResult

# ──────────────────────────────────────────────────────────────────────
# 1. AgentResult ROI 字段默认值
# ──────────────────────────────────────────────────────────────────────

def test_agent_result_roi_fields_default_zero():
    r = AgentResult(success=True, action="noop")
    assert r.saved_labor_hours == 0.0
    assert r.prevented_loss_fen == 0
    assert r.improved_kpi == {}
    assert r.roi_evidence == {}


def test_agent_result_roi_fields_can_be_populated():
    r = AgentResult(
        success=True,
        action="detect_anomaly",
        saved_labor_hours=1.5,
        prevented_loss_fen=8800,
        improved_kpi={"revenue_uplift_fen": 500, "nps_delta": 0.3},
        roi_evidence={"sql": "SELECT ...", "event_id": "evt-001"},
    )
    assert r.saved_labor_hours == 1.5
    assert r.prevented_loss_fen == 8800
    assert r.improved_kpi["revenue_uplift_fen"] == 500
    assert r.roi_evidence["event_id"] == "evt-001"


def test_agent_result_roi_fields_independent_per_instance():
    """field(default_factory=dict) 避免多实例共享同一个 dict 引用"""
    r1 = AgentResult(success=True, action="a")
    r2 = AgentResult(success=True, action="b")
    r1.improved_kpi["x"] = 1
    assert "x" not in r2.improved_kpi, "improved_kpi 实例间不应共享"


# ──────────────────────────────────────────────────────────────────────
# 2. decision_log_service 提取 ROI（mock db）
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_decision_log_service_extracts_roi_fields():
    """log_skill_result 应把 AgentResult.ROI 字段写入 AgentDecisionLog"""
    try:
        from services.decision_log_service import DecisionLogService
    except ImportError:
        pytest.skip("decision_log_service 无法导入（测试环境可能缺依赖）")

    mock_db = MagicMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()

    result = AgentResult(
        success=True,
        action="detect_anomaly",
        data={"confidence": 0.9},
        saved_labor_hours=2.5,
        prevented_loss_fen=15000,
        improved_kpi={"revenue_uplift_fen": 800},
        roi_evidence={"source": "orders_table"},
    )

    await DecisionLogService.log_skill_result(
        db=mock_db,
        tenant_id="00000000-0000-0000-0000-000000000001",
        agent_id="discount_guard",
        action="detect_anomaly",
        input_context={"store_id": "s1"},
        result=result,
    )

    # mock_db.add 应被调用 1 次，参数是 AgentDecisionLog 实例
    assert mock_db.add.called
    log_record = mock_db.add.call_args[0][0]
    assert log_record.saved_labor_hours == 2.5
    assert log_record.prevented_loss_fen == 15000
    assert log_record.improved_kpi == {"revenue_uplift_fen": 800}
    assert log_record.roi_evidence == {"source": "orders_table"}


@pytest.mark.asyncio
async def test_decision_log_service_defaults_roi_to_zero_when_missing():
    """向后兼容：旧代码返回的 AgentResult 不带 ROI → 降级 0/{} 不报错"""
    try:
        from services.decision_log_service import DecisionLogService
    except ImportError:
        pytest.skip("decision_log_service 无法导入")

    mock_db = MagicMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()

    # 模拟旧风格的 AgentResult（通过 object() 绕过新字段）
    class _OldResult:
        success = True
        data: dict = {"confidence": 0.8}
        # 注意：不设置 saved_labor_hours 等新字段

    await DecisionLogService.log_skill_result(
        db=mock_db,
        tenant_id="00000000-0000-0000-0000-000000000001",
        agent_id="legacy_skill",
        action="noop",
        input_context={},
        result=_OldResult(),
    )
    assert mock_db.add.called
    log_record = mock_db.add.call_args[0][0]
    assert log_record.saved_labor_hours == 0.0
    assert log_record.prevented_loss_fen == 0
    assert log_record.improved_kpi == {}
    assert log_record.roi_evidence == {}


@pytest.mark.asyncio
async def test_decision_log_service_degrades_non_dict_kpi():
    """improved_kpi 被错误填成 list/string → 降级为 {}（不 crash）"""
    try:
        from services.decision_log_service import DecisionLogService
    except ImportError:
        pytest.skip("decision_log_service 无法导入")

    mock_db = MagicMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()

    result = AgentResult(success=True, action="x")
    result.improved_kpi = ["not", "a", "dict"]  # type: ignore[assignment]
    result.roi_evidence = "also not a dict"  # type: ignore[assignment]

    await DecisionLogService.log_skill_result(
        db=mock_db, tenant_id="00000000-0000-0000-0000-000000000001",
        agent_id="x", action="x", input_context={}, result=result,
    )
    log_record = mock_db.add.call_args[0][0]
    assert log_record.improved_kpi == {}
    assert log_record.roi_evidence == {}


# ──────────────────────────────────────────────────────────────────────
# 3. v264/v265 迁移文件静态校验
# ──────────────────────────────────────────────────────────────────────

def test_v264_migration_has_four_roi_columns():
    """v264 迁移 SQL 必须含 4 个 ROI 列定义"""
    path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "..",
        "shared", "db-migrations", "versions", "v264_agent_decision_logs_roi_fields.py"
    )
    if not os.path.exists(path):
        pytest.skip(f"迁移文件不存在: {path}")

    with open(path, encoding="utf-8") as f:
        content = f.read()

    assert "saved_labor_hours" in content
    assert "prevented_loss_fen" in content
    assert "improved_kpi" in content
    assert "roi_evidence" in content
    assert "JSONB" in content, "improved_kpi / roi_evidence 应为 JSONB"
    assert "chk_agent_decision_logs_saved_labor_hours_nonneg" in content, "必须有非负约束"
    assert "chk_agent_decision_logs_prevented_loss_nonneg" in content


def test_v265_migration_creates_materialized_view():
    """v265 迁移必须创建 mv_agent_roi_monthly 物化视图 + refresh function"""
    path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "..",
        "shared", "db-migrations", "versions", "v265_mv_agent_roi_monthly.py"
    )
    if not os.path.exists(path):
        pytest.skip(f"迁移文件不存在: {path}")

    with open(path, encoding="utf-8") as f:
        content = f.read()

    assert "CREATE MATERIALIZED VIEW" in content
    assert "mv_agent_roi_monthly" in content
    assert "CREATE UNIQUE INDEX" in content, "CONCURRENTLY REFRESH 要求 unique index"
    assert "refresh_mv_agent_roi_monthly" in content, "必须有 refresh 函数"
    assert "DATE_TRUNC('month'" in content, "按月聚合"
    # 保留 13 个月数据
    assert "13 months" in content or "13 month" in content


def test_v265_down_revision_chains_to_v264():
    """v265 必须 depends on v264_roi"""
    path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "..",
        "shared", "db-migrations", "versions", "v265_mv_agent_roi_monthly.py"
    )
    if not os.path.exists(path):
        pytest.skip("迁移文件不存在")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert 'down_revision = "v264_roi"' in content


def test_v264_down_revision_chains_to_v263():
    path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "..",
        "shared", "db-migrations", "versions", "v264_agent_decision_logs_roi_fields.py"
    )
    if not os.path.exists(path):
        pytest.skip("迁移文件不存在")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert 'down_revision = "v263"' in content
