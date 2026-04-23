"""analyze_from_mv() 单元测试 — MenuOptimizer & DispatchPredictorAgent (Team C)

测试范围：
  MenuOptimizer（4个场景）：
    1. 正常路径：3个高损耗食材(loss_rate=0.15) → high_loss_count=3, risk_signal="medium"
    2. 高风险：5个高损耗食材 → risk_signal="high", menu_hints 不为空
    3. 无数据：rows=[] → high_loss_count=0, risk_signal="normal"
    4. DB错误：SQLAlchemyError → inference_layer="mv_fast_path_error"

  DispatchPredictorAgent（4个场景）：
    1. 正常：近7天 order_count=[200,180,190,170,180,175,200] → avg≈185, load_level="medium"
    2. 高负载趋势：最近3天=[350,360,370]，之前=[200,180,190] → load_level="high", trend="rising"
    3. 无数据：rows=[] → note 字段存在
    4. DB错误：SQLAlchemyError → error 字段存在

技术约束：
  - 全部使用 unittest.mock，不连接真实数据库
  - get_db() 通过 async generator 模拟
  - SQLAlchemyError 注入模拟 DB 故障
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from ..agents.dispatch_predictor import DispatchPredictorAgent
from ..agents.menu_optimizer import MenuOptimizer

# ── 固定测试值 ─────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())

# ── 辅助工厂 ───────────────────────────────────────────────────────────────────


def _make_mappings_result(rows: list[dict]) -> MagicMock:
    """构造 result.mappings().all() 返回值。"""
    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value = rows
    return mock_result


def _make_db_session(rows: list[dict] | None = None, raise_exc: bool = False) -> AsyncMock:
    """构造模拟 AsyncSession。

    Args:
        rows: mappings().all() 返回值列表（None 表示返回空列表）
        raise_exc: True 时 execute() 的第二次调用（查询）抛出 SQLAlchemyError
    """
    db = AsyncMock()
    if raise_exc:
        db.execute = AsyncMock(side_effect=SQLAlchemyError("connection refused"))
    else:
        actual_rows = rows if rows is not None else []
        # 第一次 execute 是 set_config，第二次是真正的查询
        set_config_result = MagicMock()
        query_result = _make_mappings_result(actual_rows)
        db.execute = AsyncMock(side_effect=[set_config_result, query_result])
    return db


async def _fake_get_db_gen(db_session: AsyncMock):
    """模拟 get_db() async generator。"""
    yield db_session


def _make_bom_row(ingredient_id: str, name: str, loss_rate: float) -> dict:
    """构造 mv_inventory_bom 模拟行（dict 模拟 RowMapping）。"""
    return {
        "ingredient_id": ingredient_id,
        "ingredient_name": name,
        "loss_rate": loss_rate,
        "unexplained_loss_g": 50.0 if loss_rate > 0.10 else 5.0,
        "waste_g": 30.0,
        "theoretical_usage_g": 500.0,
        "actual_usage_g": 500.0 * (1 + loss_rate),
    }


def _make_pnl_row(stat_date: str, order_count: int, avg_check_fen: int = 8800) -> dict:
    """构造 mv_store_pnl 模拟行（dict 模拟 RowMapping）。"""
    return {
        "stat_date": stat_date,
        "order_count": order_count,
        "customer_count": order_count * 2,
        "avg_check_fen": avg_check_fen,
        "gross_margin_rate": 0.55,
    }


# ═══════════════════════════════════════════════════════════════════
# MenuOptimizer.analyze_from_mv
# ═══════════════════════════════════════════════════════════════════


class TestMenuOptimizerAnalyzeFromMV:
    """MenuOptimizer.analyze_from_mv() 四个核心场景。"""

    @pytest.mark.asyncio
    async def test_normal_3_high_loss_returns_medium_risk(self) -> None:
        """正常路径：3个高损耗食材(loss_rate=0.15) → high_loss_count=3, risk_signal="medium"。"""
        agent = MenuOptimizer()
        rows = [_make_bom_row(f"ING-{i:03d}", f"食材{i}", 0.15) for i in range(3)]
        db_session = _make_db_session(rows=rows)

        with patch(
            "services.tx_brain.src.agents.menu_optimizer.get_db",
            return_value=_fake_get_db_gen(db_session),
        ):
            result = await agent.analyze_from_mv(TENANT_ID, STORE_ID)

        assert result["inference_layer"] == "mv_fast_path"
        assert result["agent"] == "MenuOptimizer"
        assert result["risk_signal"] == "medium"
        data = result["data"]
        assert data["high_loss_count"] == 3
        assert len(data["high_loss_ingredients"]) == 3
        assert len(data["normal_ingredients"]) == 0
        # 3个高损耗但不超过3，不触发 >3 的 hints
        hints = data["menu_optimization_hints"]
        assert isinstance(hints, list)
        # 有高损耗食材，应有"建议优先安排套餐"提示
        assert any("套餐" in h for h in hints)

    @pytest.mark.asyncio
    async def test_5_high_loss_returns_high_risk_with_hints(self) -> None:
        """高风险：5个高损耗食材 → risk_signal="high", menu_hints 不为空。"""
        agent = MenuOptimizer()
        rows = [_make_bom_row(f"ING-{i:03d}", f"高损食材{i}", 0.20) for i in range(5)]
        db_session = _make_db_session(rows=rows)

        with patch(
            "services.tx_brain.src.agents.menu_optimizer.get_db",
            return_value=_fake_get_db_gen(db_session),
        ):
            result = await agent.analyze_from_mv(TENANT_ID, STORE_ID)

        assert result["inference_layer"] == "mv_fast_path"
        assert result["risk_signal"] == "high"
        data = result["data"]
        assert data["high_loss_count"] == 5
        hints = data["menu_optimization_hints"]
        assert len(hints) > 0
        # 超过3个高损耗，应有"损耗异常"提示
        assert any("损耗异常" in h for h in hints)

    @pytest.mark.asyncio
    async def test_empty_rows_returns_normal_risk(self) -> None:
        """无数据：rows=[] → high_loss_count=0, risk_signal="normal"。"""
        agent = MenuOptimizer()
        db_session = _make_db_session(rows=[])

        with patch(
            "services.tx_brain.src.agents.menu_optimizer.get_db",
            return_value=_fake_get_db_gen(db_session),
        ):
            result = await agent.analyze_from_mv(TENANT_ID)

        assert result["inference_layer"] == "mv_fast_path"
        assert result["risk_signal"] == "normal"
        data = result["data"]
        assert data["high_loss_count"] == 0
        assert data["high_loss_ingredients"] == []
        assert data["normal_ingredients"] == []
        assert data["menu_optimization_hints"] == []

    @pytest.mark.asyncio
    async def test_db_error_returns_fast_path_error(self) -> None:
        """DB错误：SQLAlchemyError → inference_layer="mv_fast_path_error"。"""
        agent = MenuOptimizer()
        db_session = _make_db_session(raise_exc=True)

        with patch(
            "services.tx_brain.src.agents.menu_optimizer.get_db",
            return_value=_fake_get_db_gen(db_session),
        ):
            result = await agent.analyze_from_mv(TENANT_ID, STORE_ID)

        assert result["inference_layer"] == "mv_fast_path_error"
        assert result["agent"] == "MenuOptimizer"
        assert result["data"] == {}
        assert "error" in result
        assert "数据库查询失败" in result["error"]


# ═══════════════════════════════════════════════════════════════════
# DispatchPredictorAgent.analyze_from_mv
# ═══════════════════════════════════════════════════════════════════


class TestDispatchPredictorAnalyzeFromMV:
    """DispatchPredictorAgent.analyze_from_mv() 四个核心场景。"""

    @pytest.mark.asyncio
    async def test_normal_7d_medium_load(self) -> None:
        """正常：近7天 order_count=[200,180,190,170,180,175,200] → avg≈185, load_level="medium"。"""
        agent = DispatchPredictorAgent()
        order_counts = [200, 180, 190, 170, 180, 175, 200]
        rows = [_make_pnl_row(f"2026-03-{28 - i:02d}", cnt) for i, cnt in enumerate(order_counts)]
        db_session = _make_db_session(rows=rows)

        with patch(
            "services.tx_brain.src.agents.dispatch_predictor.get_db",
            return_value=_fake_get_db_gen(db_session),
        ):
            result = await agent.analyze_from_mv(TENANT_ID, STORE_ID)

        assert result["inference_layer"] == "mv_fast_path"
        assert result["agent"] == "DispatchPredictorAgent"
        data = result["data"]
        assert data["kitchen_load_level"] == "medium"
        assert data["avg_daily_orders"] == pytest.approx(185.0, abs=0.2)
        assert data["max_daily_orders"] == 200
        assert "daily_orders_history" in data
        assert data["daily_orders_history"] == order_counts

    @pytest.mark.asyncio
    async def test_high_load_rising_trend_returns_high_risk(self) -> None:
        """高负载趋势：最近3天=[350,360,370]，之前=[200,180,190] → load_level="high", trend="rising", risk_signal="high"。"""
        agent = DispatchPredictorAgent()
        # rows 按 stat_date DESC，最新的在前
        order_counts = [370, 360, 350, 190, 180, 200, 195]
        rows = [_make_pnl_row(f"2026-03-{28 - i:02d}", cnt) for i, cnt in enumerate(order_counts)]
        db_session = _make_db_session(rows=rows)

        with patch(
            "services.tx_brain.src.agents.dispatch_predictor.get_db",
            return_value=_fake_get_db_gen(db_session),
        ):
            result = await agent.analyze_from_mv(TENANT_ID, STORE_ID)

        assert result["inference_layer"] == "mv_fast_path"
        data = result["data"]
        assert data["kitchen_load_level"] == "high"
        assert data["recent_7d_trend"] == "rising"
        assert result["risk_signal"] == "high"

    @pytest.mark.asyncio
    async def test_empty_rows_returns_note_field(self) -> None:
        """无数据：rows=[] → note 字段存在。"""
        agent = DispatchPredictorAgent()
        db_session = _make_db_session(rows=[])

        with patch(
            "services.tx_brain.src.agents.dispatch_predictor.get_db",
            return_value=_fake_get_db_gen(db_session),
        ):
            result = await agent.analyze_from_mv(TENANT_ID)

        assert result["inference_layer"] == "mv_fast_path"
        assert result["agent"] == "DispatchPredictorAgent"
        assert "note" in result
        assert result["data"] == {}

    @pytest.mark.asyncio
    async def test_db_error_returns_error_field(self) -> None:
        """DB错误：SQLAlchemyError → error 字段存在。"""
        agent = DispatchPredictorAgent()
        db_session = _make_db_session(raise_exc=True)

        with patch(
            "services.tx_brain.src.agents.dispatch_predictor.get_db",
            return_value=_fake_get_db_gen(db_session),
        ):
            result = await agent.analyze_from_mv(TENANT_ID, STORE_ID)

        assert result["inference_layer"] == "mv_fast_path_error"
        assert result["agent"] == "DispatchPredictorAgent"
        assert "error" in result
        assert result["data"] == {}
