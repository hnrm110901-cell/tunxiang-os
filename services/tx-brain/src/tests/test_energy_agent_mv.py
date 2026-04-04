"""EnergyMonitorAgent.analyze_from_mv() 单元测试

测试范围（3个核心场景）：
  1. 正常路径：物化视图有数据，返回 inference_layer=mv_fast_path 及完整字段
  2. 空视图 fallback：视图无数据（fetchone 返回 None），回退到 analyze()
  3. DB 异常 fallback：SQLAlchemyError 触发，graceful 回退到 analyze()，不抛出异常

技术约束：
  - 全部使用 unittest.mock，不连接真实数据库
  - get_db() 通过 contextlib.asynccontextmanager 模拟
  - SQLAlchemyError 注入模拟 DB 故障
  - analyze() fallback 通过 patch.object 隔离，不调用真实 Claude API
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from ..agents.energy_monitor import EnergyMonitorAgent

# ── 固定测试值 ─────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())

# ── 辅助工厂 ───────────────────────────────────────────────────────────────────


def _make_db_session(row=None, raise_exc: bool = False) -> AsyncMock:
    """构造模拟 AsyncSession。

    Args:
        row: fetchone() 返回值（None 表示空视图）
        raise_exc: True 时 execute() 抛出 SQLAlchemyError
    """
    db = AsyncMock()
    if raise_exc:
        db.execute = AsyncMock(side_effect=SQLAlchemyError("connection refused"))
    else:
        mock_result = MagicMock()
        mock_result.fetchone.return_value = row
        db.execute = AsyncMock(return_value=mock_result)
    return db


@asynccontextmanager
async def _fake_get_db(db_session: AsyncMock):
    """模拟 get_db() async context manager。"""
    yield db_session


def _make_energy_mv_row() -> MagicMock:
    """构造 mv_energy_efficiency 物化视图模拟行。

    字段对应 v148_event_materialized_views.py 中的 CREATE TABLE 定义。
    """
    row = MagicMock()
    row._mapping = {
        "tenant_id": TENANT_ID,
        "store_id": STORE_ID,
        "stat_date": date(2026, 4, 4),
        "electricity_kwh": Decimal("185.500"),
        "gas_m3": Decimal("42.300"),
        "water_ton": Decimal("8.200"),
        "energy_cost_fen": 3600,          # 36.00 元
        "revenue_fen": 80000,             # 800.00 元
        "energy_revenue_ratio": Decimal("0.0450"),  # 4.5% — 优秀
        "anomaly_count": 0,
        "off_hours_anomalies": "[]",
        "updated_at": datetime(2026, 4, 4, 8, 0, 0, tzinfo=timezone.utc),
    }
    return row


def _make_fallback_analyze_result() -> dict:
    """构造 analyze() fallback 返回值（规则兜底）。"""
    return {
        "efficiency_level": "良好",
        "anomaly_summary": "能耗整体正常",
        "top_issues": [],
        "action_items": [],
        "estimated_saving_pct": 0.0,
        "constraints_check": {
            "margin_ok": True,
            "food_safety_ok": True,
            "experience_ok": True,
        },
        "source": "fallback",
    }


# ═══════════════════════════════════════════════════════════════════
# EnergyMonitorAgent.analyze_from_mv — 三个核心测试场景
# ═══════════════════════════════════════════════════════════════════


class TestEnergyMonitorAnalyzeFromMV:
    """EnergyMonitorAgent.analyze_from_mv() 完整测试套件。"""

    # ── 场景1：正常路径 ────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_normal_returns_mv_fast_path(self) -> None:
        """正常路径：视图有数据 → 返回 inference_layer=mv_fast_path 及完整视图数据。

        验证：
        - inference_layer == "mv_fast_path"
        - agent == "EnergyMonitorAgent"
        - data 包含所有 mv_energy_efficiency 关键字段
        - 数值字段正确透传（energy_revenue_ratio, anomaly_count 等）
        """
        agent = EnergyMonitorAgent()
        db_session = _make_db_session(row=_make_energy_mv_row())

        with patch(
            "services.tx_brain.src.agents.energy_monitor.get_db",
            return_value=_fake_get_db(db_session),
        ):
            result = await agent.analyze_from_mv(TENANT_ID, STORE_ID)

        # 顶层结构校验
        assert result["inference_layer"] == "mv_fast_path"
        assert result["agent"] == "EnergyMonitorAgent"

        # 数据字段校验
        data = result["data"]
        assert data["tenant_id"] == TENANT_ID
        assert data["store_id"] == STORE_ID
        assert data["stat_date"] == date(2026, 4, 4)
        assert float(data["electricity_kwh"]) == pytest.approx(185.5)
        assert float(data["gas_m3"]) == pytest.approx(42.3)
        assert float(data["water_ton"]) == pytest.approx(8.2)
        assert data["energy_cost_fen"] == 3600
        assert data["revenue_fen"] == 80000
        assert float(data["energy_revenue_ratio"]) == pytest.approx(0.045)
        assert data["anomaly_count"] == 0

        # 确认未调用 fallback analyze
        db_session.execute.assert_called()

    @pytest.mark.asyncio
    async def test_normal_without_store_id(self) -> None:
        """正常路径（无 store_id）：store_clause 为空，仍返回 mv_fast_path。"""
        agent = EnergyMonitorAgent()
        db_session = _make_db_session(row=_make_energy_mv_row())

        with patch(
            "services.tx_brain.src.agents.energy_monitor.get_db",
            return_value=_fake_get_db(db_session),
        ):
            result = await agent.analyze_from_mv(TENANT_ID)  # 不传 store_id

        assert result["inference_layer"] == "mv_fast_path"
        assert result["agent"] == "EnergyMonitorAgent"
        assert "data" in result

    # ── 场景2：空视图 fallback ─────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_empty_view_falls_back_to_analyze(self) -> None:
        """空视图 fallback：fetchone() 返回 None → 调用 analyze() 兜底。

        验证：
        - analyze() 被调用一次，且传入正确的 tenant_id / store_id
        - 返回结果来自 analyze() 而非物化视图
        - 不抛出任何异常
        """
        agent = EnergyMonitorAgent()
        db_session = _make_db_session(row=None)  # 空视图

        fallback_result = _make_fallback_analyze_result()

        with patch(
            "services.tx_brain.src.agents.energy_monitor.get_db",
            return_value=_fake_get_db(db_session),
        ), patch.object(
            agent, "analyze", new=AsyncMock(return_value=fallback_result)
        ) as mock_analyze:
            result = await agent.analyze_from_mv(TENANT_ID, STORE_ID)

        # analyze() 被调用一次
        mock_analyze.assert_awaited_once()
        call_payload = mock_analyze.call_args[0][0]
        assert call_payload["tenant_id"] == TENANT_ID
        assert call_payload["store_id"] == STORE_ID

        # 返回值来自 analyze()
        assert result == fallback_result
        assert result["source"] == "fallback"

        # 确认不含 mv_fast_path 标识
        assert result.get("inference_layer") is None

    # ── 场景3：DB 异常 fallback ────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_db_error_falls_back_to_analyze(self) -> None:
        """DB 异常 fallback：SQLAlchemyError → graceful 回退 analyze()，不抛出异常。

        验证：
        - SQLAlchemyError 被正确捕获（不暴露给调用方）
        - analyze() 被调用一次作为兜底
        - 返回结果结构与正常 analyze() 一致
        """
        agent = EnergyMonitorAgent()
        db_session = _make_db_session(raise_exc=True)  # 模拟 DB 故障

        fallback_result = _make_fallback_analyze_result()
        fallback_result["efficiency_level"] = "警告"
        fallback_result["anomaly_summary"] = "DB不可用，降级为规则分析"

        with patch(
            "services.tx_brain.src.agents.energy_monitor.get_db",
            return_value=_fake_get_db(db_session),
        ), patch.object(
            agent, "analyze", new=AsyncMock(return_value=fallback_result)
        ) as mock_analyze:
            # 不应抛出任何异常
            result = await agent.analyze_from_mv(TENANT_ID, STORE_ID)

        # SQLAlchemyError 被吞掉，analyze() 作为兜底被调用
        mock_analyze.assert_awaited_once()
        call_payload = mock_analyze.call_args[0][0]
        assert call_payload["tenant_id"] == TENANT_ID
        assert call_payload["store_id"] == STORE_ID

        # 返回来自 fallback
        assert result == fallback_result
        # 无 mv_fast_path 标识
        assert result.get("inference_layer") is None
