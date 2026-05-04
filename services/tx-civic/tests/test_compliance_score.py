"""test_compliance_score.py — 门店合规评分服务测试

覆盖范围：
  1. calculate_dimension_score — 五维度评分算法 (trace/kitchen/env/fire/license)
  2. determine_risk_level — 风险等级绿/黄/红阈值
  3. identify_top_issues — 待办事项排序
  4. calculate_store_score — 单店全流程评分
  5. daily_score_batch — 全品牌批量评分

分层：
  - 纯函数（1-3）：直接测试，不依赖 DB
  - 服务函数（4-5）：Mock 外部依赖（traceability_service 等 + TenantSession）
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services import (
    compliance_score_service,
)
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.compliance_score_service import (
    calculate_dimension_score,
    calculate_store_score,
    daily_score_batch,
    determine_risk_level,
    get_store_score,
    identify_top_issues,
)

TENANT_ID = "00000000-0000-0000-0000-000000000001"
STORE_ID = "store-001"


# =============================================================================
# 纯函数: calculate_dimension_score
# =============================================================================


class TestCalculateDimensionScore:
    def test_trace_dimension_full(self):
        """食安追溯：台账 100%、供应商 100%、冷链 100% → 100 分。"""
        score = calculate_dimension_score("trace", {
            "batch_coverage_rate": 100,
            "supplier_cert_coverage": 100,
            "coldchain_completeness": 100,
        })
        assert score == 100.0

    def test_trace_dimension_partial(self):
        """食安追溯：台账 60%、供应商 50%、冷链 30% → 48 分。"""
        score = calculate_dimension_score("trace", {
            "batch_coverage_rate": 60,
            "supplier_cert_coverage": 50,
            "coldchain_completeness": 30,
        })
        assert score == 48.0  # 60*0.4 + 50*0.3 + 30*0.3 = 24 + 15 + 9

    def test_kitchen_dimension_no_critical(self):
        """明厨亮灶：在线 100%、处理率 100%、无严重告警 → 90 分（权重 50/30/20）。"""
        score = calculate_dimension_score("kitchen", {
            "online_rate": 100,
            "resolve_rate": 100,
            "has_unresolved_critical": False,
        })
        assert score == 100.0  # 100*0.5 + 100*0.3 + 100*0.2 = 100

    def test_kitchen_dimension_with_critical(self):
        """明厨亮灶：有未处理严重告警 → no_critical = 0。"""
        score = calculate_dimension_score("kitchen", {
            "online_rate": 80,
            "resolve_rate": 70,
            "has_unresolved_critical": True,
        })
        assert score == 61.0  # 80*0.5 + 70*0.3 + 0*0.2 = 40 + 21 + 0

    def test_env_dimension_full(self):
        """环保合规：排放 100%、垃圾台账完整 → 100 分。"""
        score = calculate_dimension_score("env", {
            "compliance_rate": 100,
            "waste_completeness": 100,
        })
        assert score == 100.0

    def test_fire_dimension(self):
        """消防安全：设备检查 80%、巡检 60% → 70 分。"""
        score = calculate_dimension_score("fire", {
            "inspection_timeliness": 80,
            "patrol_timeliness": 60,
        })
        assert score == 70.0  # 80*0.5 + 60*0.5

    def test_license_dimension_no_expired(self):
        """证照管理：覆盖 90%、无过期 → 94 分（90*0.6 + 100*0.4）。"""
        score = calculate_dimension_score("license", {
            "coverage_score": 90,
            "has_expired": False,
        })
        assert score == 94.0  # 90*0.6 + 100*0.4

    def test_license_dimension_expired(self):
        """证照管理：有过期 → no_expired = 0。"""
        score = calculate_dimension_score("license", {
            "coverage_score": 80,
            "has_expired": True,
        })
        assert score == 48.0  # 80*0.6 + 0*0.4

    def test_unknown_domain_returns_zero(self):
        """未知域 → 0 分。"""
        score = calculate_dimension_score("unknown", {"foo": 100})
        assert score == 0.0


# =============================================================================
# 纯函数: determine_risk_level
# =============================================================================


class TestDetermineRiskLevel:
    def test_green_above_80(self):
        """80 及以上 → green。"""
        assert determine_risk_level(80.0) == "green"
        assert determine_risk_level(95.0) == "green"
        assert determine_risk_level(100.0) == "green"

    def test_yellow_60_to_80(self):
        """[60, 80) → yellow。"""
        assert determine_risk_level(60.0) == "yellow"
        assert determine_risk_level(70.5) == "yellow"
        assert determine_risk_level(79.9) == "yellow"

    def test_red_below_60(self):
        """< 60 → red。"""
        assert determine_risk_level(0.0) == "red"
        assert determine_risk_level(30.0) == "red"
        assert determine_risk_level(59.9) == "red"

    def test_boundary_80_is_green(self):
        """边界 80.0 → green。"""
        assert determine_risk_level(80.0) == "green"

    def test_boundary_60_is_yellow(self):
        """边界 60.0 → yellow。"""
        assert determine_risk_level(60.0) == "yellow"


# =============================================================================
# 纯函数: identify_top_issues
# =============================================================================


class TestIdentifyTopIssues:
    def test_all_green_no_issues(self):
        """五项全 green（>=70）→ 空列表。"""
        issues = identify_top_issues({
            "trace": 80, "kitchen": 85, "env": 90,
            "fire": 75, "license": 88,
        })
        assert issues == []

    def test_one_critical_issue(self):
        """单维度 < 50 → critical。"""
        issues = identify_top_issues({
            "trace": 30, "kitchen": 80, "env": 80,
            "fire": 80, "license": 80,
        })
        assert len(issues) == 1
        assert issues[0]["domain"] == "trace"
        assert issues[0]["severity"] == "critical"

    def test_warning_threshold(self):
        """维度在 [50, 70) → warning。"""
        issues = identify_top_issues({
            "trace": 65, "kitchen": 80, "env": 80,
            "fire": 80, "license": 80,
        })
        assert len(issues) == 1
        assert issues[0]["domain"] == "trace"
        assert issues[0]["severity"] == "warning"

    def test_sorted_by_score_ascending(self):
        """问题列表按得分升序排列（最紧急的排第一）。"""
        issues = identify_top_issues({
            "trace": 65, "kitchen": 40, "env": 80,
            "fire": 55, "license": 80,
        })
        assert len(issues) == 3
        assert issues[0]["domain"] == "kitchen"  # 40 -> critical
        assert issues[1]["domain"] == "fire"     # 55 -> critical
        assert issues[2]["domain"] == "trace"    # 65 -> warning

    def test_mixed_severities(self):
        """混合严重等级。"""
        issues = identify_top_issues({
            "trace": 45, "kitchen": 68, "env": 80,
            "fire": 80, "license": 80,
        })
        assert len(issues) == 2
        assert issues[0]["severity"] == "critical"  # trace < 50
        assert issues[1]["severity"] == "warning"   # kitchen < 70


# =============================================================================
# 服务函数: calculate_store_score
# =============================================================================


class TestCalculateStoreScore:
    """Mock 所有外部依赖测试单店评分全流程。"""

    @pytest.mark.asyncio
    async def test_calculate_store_score_happy_path(self):
        """五维度全部高分的门店 → total ~92 分、risk_level=green。"""
        with (
            patch.object(compliance_score_service, "traceability_service") as mock_trace,
            patch.object(compliance_score_service, "kitchen_monitor_service") as mock_kitchen,
            patch.object(compliance_score_service, "env_compliance_service") as mock_env,
            patch.object(compliance_score_service, "fire_safety_service") as mock_fire,
            patch.object(compliance_score_service, "license_manager_service") as mock_license,
            patch.object(compliance_score_service, "TenantSession") as mock_ts,
        ):
            # Mock 各领域 service 调用 — 使用 AsyncMock 使 await 可正常解析
            mock_trace.get_trace_stats = AsyncMock(return_value={"batch_coverage_rate": 95, "coldchain_records": 10})
            mock_trace.check_completeness = AsyncMock(return_value={"details": {"supplier_cert_coverage": 90}})

            mock_kitchen.get_online_rate = AsyncMock(return_value={"online_rate": 100})
            mock_kitchen.get_alert_stats = AsyncMock(return_value={"resolve_rate": 95})

            mock_env.check_emission_compliance = AsyncMock(return_value={"compliance_rate": 90})
            mock_fire.get_equipment = AsyncMock(return_value=[
                {"id": "e1", "overdue": False},
                {"id": "e2", "overdue": False},
            ])
            mock_license.get_license_coverage = AsyncMock(return_value={"score": 95})
            mock_license.get_licenses = AsyncMock(return_value=[
                {"id": "l1", "renewal_urgency": "valid"},
                {"id": "l2", "renewal_urgency": "valid"},
            ])

            # Mock TenantSession — 三次内部 execute 分别控制不同字段
            # 调用 1: critical_check  → scalar=0 → has_unresolved_critical=False
            # 调用 2: waste_days       → scalar=7 → waste_completeness=100%
            # 调用 3: patrol_count     → scalar=4 → patrol_timeliness=100%
            mock_session = AsyncMock()
            mock_session.execute = AsyncMock(side_effect=[
                MagicMock(scalar=MagicMock(return_value=0)),  # no critical
                MagicMock(scalar=MagicMock(return_value=7)),  # 7/7 waste days
                MagicMock(scalar=MagicMock(return_value=4)),  # 4/4 patrols
            ])
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
            mock_cm.__aexit__ = AsyncMock(return_value=None)
            mock_ts.return_value = mock_cm

            result = await calculate_store_score(TENANT_ID, STORE_ID)

            assert result["store_id"] == STORE_ID
            assert result["total_score"] >= 80  # green
            assert result["risk_level"] == "green"
            assert len(result["dimension_scores"]) == 5
            assert len(result["top_issues"]) == 0  # 全高分
            assert "id" in result

    @pytest.mark.asyncio
    async def test_calculate_store_score_low_scores(self):
        """五维度全部低分 → total 低、risk_level=red、top_issues 包含 5 项。"""
        with (
            patch.object(compliance_score_service, "traceability_service") as mock_trace,
            patch.object(compliance_score_service, "kitchen_monitor_service") as mock_kitchen,
            patch.object(compliance_score_service, "env_compliance_service") as mock_env,
            patch.object(compliance_score_service, "fire_safety_service") as mock_fire,
            patch.object(compliance_score_service, "license_manager_service") as mock_license,
            patch.object(compliance_score_service, "TenantSession") as mock_ts,
        ):
            mock_trace.get_trace_stats = AsyncMock(return_value={"batch_coverage_rate": 10, "coldchain_records": 0})
            mock_trace.check_completeness = AsyncMock(return_value={"details": {"supplier_cert_coverage": 10}})

            mock_kitchen.get_online_rate = AsyncMock(return_value={"online_rate": 20})
            mock_kitchen.get_alert_stats = AsyncMock(return_value={"resolve_rate": 10})

            mock_env.check_emission_compliance = AsyncMock(return_value={"compliance_rate": 15})
            mock_fire.get_equipment = AsyncMock(return_value=[
                {"id": "e1", "overdue": True},
            ])
            mock_license.get_license_coverage = AsyncMock(return_value={"score": 10})
            mock_license.get_licenses = AsyncMock(return_value=[
                {"id": "l1", "renewal_urgency": "expired"},
            ])

            mock_session = AsyncMock()
            mock_session.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=2)))
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
            mock_cm.__aexit__ = AsyncMock(return_value=None)
            mock_ts.return_value = mock_cm

            result = await calculate_store_score(TENANT_ID, STORE_ID)

            assert result["store_id"] == STORE_ID
            assert result["total_score"] < 60  # red
            assert result["risk_level"] == "red"
            assert len(result["top_issues"]) == 5  # 全部低于 warning 阈值


# =============================================================================
# 服务函数: get_store_score
# =============================================================================


class TestGetStoreScore:
    @pytest.mark.asyncio
    async def test_get_store_score_returns_latest(self):
        """门店有评分记录 → 返回最新一条。"""
        with (
            patch.object(compliance_score_service, "TenantSession") as mock_ts,
        ):
            mock_session = AsyncMock()
            mock_row = {
                "id": "score-001",
                "total_score": 88.5,
                "risk_level": "green",
                "trace_score": 85.0,
                "kitchen_score": 90.0,
                "env_score": 80.0,
                "fire_score": 92.0,
                "license_score": 90.0,
                "scored_at": "2026-05-01T00:00:00",
            }

            # result.mappings().first() → returns a real dict
            mock_result = MagicMock()
            mock_result.mappings.return_value.first.return_value = mock_row

            mock_session.execute = AsyncMock(return_value=mock_result)

            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
            mock_cm.__aexit__ = AsyncMock(return_value=None)
            mock_ts.return_value = mock_cm

            result = await get_store_score(TENANT_ID, STORE_ID)

            assert result is not None
            assert result["total_score"] == 88.5
            assert result["risk_level"] == "green"
            assert "dimension_scores" in result
            assert result["dimension_scores"]["trace"] == 85.0
            assert "top_issues" in result

    @pytest.mark.asyncio
    async def test_get_store_score_no_data(self):
        """门店没有评分记录 → 返回 None。"""
        with (
            patch.object(compliance_score_service, "TenantSession") as mock_ts,
        ):
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.mappings.return_value.first.return_value = None

            mock_session.execute = AsyncMock(return_value=mock_result)

            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
            mock_cm.__aexit__ = AsyncMock(return_value=None)
            mock_ts.return_value = mock_cm

            result = await get_store_score(TENANT_ID, STORE_ID)
            assert result is None


# =============================================================================
# 服务函数: daily_score_batch
# =============================================================================


class TestDailyScoreBatch:
    @pytest.mark.asyncio
    async def test_daily_batch_all_success(self):
        """3 家活跃门店全部评分成功。"""
        with (
            patch.object(compliance_score_service, "TenantSession") as mock_ts,
            patch.object(compliance_score_service, "calculate_store_score", new_callable=AsyncMock) as mock_calc,
        ):
            # Mock TenantSession for store list query: session.execute().mappings().all()
            mock_session = AsyncMock()
            store_rows = [
                MagicMock(**{"__getitem__": lambda self, k: {"id": "store-001"}[k]}),
                MagicMock(**{"__getitem__": lambda self, k: {"id": "store-002"}[k]}),
                MagicMock(**{"__getitem__": lambda self, k: {"id": "store-003"}[k]}),
            ]
            # Simply provide store IDs as dicts for the mapping rows
            store_dicts = [{"id": "store-001"}, {"id": "store-002"}, {"id": "store-003"}]
            mock_result = MagicMock()
            mock_result.mappings.return_value.all.return_value = store_dicts
            mock_session.execute = AsyncMock(return_value=mock_result)

            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
            mock_cm.__aexit__ = AsyncMock(return_value=None)
            mock_ts.return_value = mock_cm

            # Mock calculate_store_score — use AsyncMock since daily_score_batch calls await on it
            mock_calc.side_effect = [
                {"store_id": "store-001", "total_score": 90.0, "risk_level": "green"},
                {"store_id": "store-002", "total_score": 70.0, "risk_level": "yellow"},
                {"store_id": "store-003", "total_score": 50.0, "risk_level": "red"},
            ]

            result = await daily_score_batch(TENANT_ID)

            assert result["total_stores"] == 3
            assert result["scored"] == 3
            assert result["errors"] == 0
            assert len(result["results"]) == 3

    @pytest.mark.asyncio
    async def test_daily_batch_partial_errors(self):
        """3 家门店中 1 家评分失败。"""
        with (
            patch.object(compliance_score_service, "TenantSession") as mock_ts,
            patch.object(compliance_score_service, "calculate_store_score", new_callable=AsyncMock) as mock_calc,
        ):
            mock_session = AsyncMock()
            store_dicts = [{"id": "store-001"}, {"id": "store-002"}, {"id": "store-003"}]
            mock_result = MagicMock()
            mock_result.mappings.return_value.all.return_value = store_dicts
            mock_session.execute = AsyncMock(return_value=mock_result)

            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
            mock_cm.__aexit__ = AsyncMock(return_value=None)
            mock_ts.return_value = mock_cm

            def _calc_side_effect(tenant_id, store_id):
                if store_id == "store-002":
                    raise ValueError("DB connection timeout")
                return {"store_id": store_id, "total_score": 85.0, "risk_level": "green"}

            mock_calc.side_effect = _calc_side_effect

            result = await daily_score_batch(TENANT_ID)

            assert result["total_stores"] == 3
            assert result["scored"] == 2
            assert result["errors"] == 1
            success_ids = [r["store_id"] for r in result["results"] if "score" in r]
            assert "store-001" in success_ids
            assert "store-003" in success_ids
