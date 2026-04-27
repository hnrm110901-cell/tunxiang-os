"""analyze_from_mv() 单元测试 — CRMOperator & CustomerServiceAgent

测试范围（每个 Agent 各 3 个场景）：
  1. 正常路径：物化视图有数据，返回 mv_fast_path 结果
  2. 空视图 fallback：视图无数据，回退到原始 analyze 方法
  3. DB 异常 fallback：SQLAlchemyError 触发，回退到原始 analyze 方法

技术约束：
  - 全部使用 unittest.mock，不连接真实数据库
  - get_db() 通过 contextlib.asynccontextmanager 模拟
  - SQLAlchemyError 注入模拟 DB 故障
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from ..agents.crm_operator import CRMOperator
from ..agents.customer_service import CustomerServiceAgent

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


def _make_clv_row() -> MagicMock:
    """构造 mv_member_clv 物化视图模拟行。"""
    row = MagicMock()
    row._mapping = {
        "tenant_id": TENANT_ID,
        "store_id": STORE_ID,
        "total_members": 1200,
        "active_members": 850,
        "avg_clv": 386.50,
        "churn_risk_count": 95,
        "top_segments": ["vip", "regular"],
    }
    return row


def _make_opinion_row() -> MagicMock:
    """构造 mv_public_opinion 物化视图模拟行。"""
    row = MagicMock()
    row._mapping = {
        "tenant_id": TENANT_ID,
        "store_id": STORE_ID,
        "total_mentions": 340,
        "positive_rate": 0.72,
        "negative_rate": 0.15,
        "top_complaints": ["出餐慢", "分量少"],
        "unresolved_count": 7,
    }
    return row


# ═══════════════════════════════════════════════════════════════════
# CRMOperator.analyze_from_mv
# ═══════════════════════════════════════════════════════════════════


class TestCRMOperatorAnalyzeFromMV:
    """CRMOperator.analyze_from_mv() 三个核心场景。"""

    @pytest.mark.asyncio
    async def test_normal_returns_mv_fast_path(self) -> None:
        """正常路径：视图有数据 → 返回 inference_layer=mv_fast_path 及完整 data。"""
        agent = CRMOperator()
        db_session = _make_db_session(row=_make_clv_row())

        with patch(
            "services.tx_brain.src.agents.crm_operator.get_db",
            return_value=_fake_get_db(db_session),
        ):
            result = await agent.analyze_from_mv(TENANT_ID, STORE_ID)

        assert result["inference_layer"] == "mv_fast_path"
        assert result["agent"] == "CRMOperator"
        data = result["data"]
        assert data["tenant_id"] == TENANT_ID
        assert data["store_id"] == STORE_ID
        assert data["total_members"] == 1200
        assert data["active_members"] == 850
        assert data["avg_clv"] == pytest.approx(386.50)
        assert data["churn_risk_count"] == 95
        assert data["top_segments"] == ["vip", "regular"]

    @pytest.mark.asyncio
    async def test_empty_view_falls_back_to_generate_campaign(self) -> None:
        """空视图 fallback：fetchone() 返回 None → 调用 generate_campaign() 兜底。"""
        agent = CRMOperator()
        db_session = _make_db_session(row=None)

        fallback_result = {
            "campaign_name": "兜底活动",
            "source": "fallback",
        }

        with (
            patch(
                "services.tx_brain.src.agents.crm_operator.get_db",
                return_value=_fake_get_db(db_session),
            ),
            patch.object(agent, "generate_campaign", new=AsyncMock(return_value=fallback_result)) as mock_generate,
        ):
            result = await agent.analyze_from_mv(TENANT_ID, STORE_ID)

        mock_generate.assert_awaited_once()
        call_payload = mock_generate.call_args[0][0]
        assert call_payload["tenant_id"] == TENANT_ID
        assert call_payload["store_id"] == STORE_ID
        assert result == fallback_result

    @pytest.mark.asyncio
    async def test_db_error_falls_back_to_generate_campaign(self) -> None:
        """DB 异常 fallback：SQLAlchemyError → graceful 回退，不抛出异常。"""
        agent = CRMOperator()
        db_session = _make_db_session(raise_exc=True)

        fallback_result = {
            "campaign_name": "异常兜底活动",
            "source": "fallback",
        }

        with (
            patch(
                "services.tx_brain.src.agents.crm_operator.get_db",
                return_value=_fake_get_db(db_session),
            ),
            patch.object(agent, "generate_campaign", new=AsyncMock(return_value=fallback_result)) as mock_generate,
        ):
            result = await agent.analyze_from_mv(TENANT_ID, STORE_ID)

        mock_generate.assert_awaited_once()
        assert result == fallback_result


# ═══════════════════════════════════════════════════════════════════
# CustomerServiceAgent.analyze_from_mv
# ═══════════════════════════════════════════════════════════════════


class TestCustomerServiceAnalyzeFromMV:
    """CustomerServiceAgent.analyze_from_mv() 三个核心场景。"""

    @pytest.mark.asyncio
    async def test_normal_returns_mv_fast_path(self) -> None:
        """正常路径：视图有数据 → 返回 inference_layer=mv_fast_path 及完整 data。"""
        agent = CustomerServiceAgent()
        db_session = _make_db_session(row=_make_opinion_row())

        with patch(
            "services.tx_brain.src.agents.customer_service.get_db",
            return_value=_fake_get_db(db_session),
        ):
            result = await agent.analyze_from_mv(TENANT_ID, STORE_ID)

        assert result["inference_layer"] == "mv_fast_path"
        assert result["agent"] == "CustomerServiceAgent"
        data = result["data"]
        assert data["tenant_id"] == TENANT_ID
        assert data["store_id"] == STORE_ID
        assert data["total_mentions"] == 340
        assert data["positive_rate"] == pytest.approx(0.72)
        assert data["negative_rate"] == pytest.approx(0.15)
        assert data["top_complaints"] == ["出餐慢", "分量少"]
        assert data["unresolved_count"] == 7

    @pytest.mark.asyncio
    async def test_empty_view_falls_back_to_handle(self) -> None:
        """空视图 fallback：fetchone() 返回 None → 调用 handle() 兜底。"""
        agent = CustomerServiceAgent()
        db_session = _make_db_session(row=None)

        fallback_result = {
            "intent": "other",
            "source": "fallback",
        }

        with (
            patch(
                "services.tx_brain.src.agents.customer_service.get_db",
                return_value=_fake_get_db(db_session),
            ),
            patch.object(agent, "handle", new=AsyncMock(return_value=fallback_result)) as mock_handle,
        ):
            result = await agent.analyze_from_mv(TENANT_ID, STORE_ID)

        mock_handle.assert_awaited_once()
        call_payload = mock_handle.call_args[0][0]
        assert call_payload["tenant_id"] == TENANT_ID
        assert call_payload["store_id"] == STORE_ID
        assert result == fallback_result

    @pytest.mark.asyncio
    async def test_db_error_falls_back_to_handle(self) -> None:
        """DB 异常 fallback：SQLAlchemyError → graceful 回退，不抛出异常。"""
        agent = CustomerServiceAgent()
        db_session = _make_db_session(raise_exc=True)

        fallback_result = {
            "intent": "other",
            "escalate_to_human": True,
            "source": "fallback",
        }

        with (
            patch(
                "services.tx_brain.src.agents.customer_service.get_db",
                return_value=_fake_get_db(db_session),
            ),
            patch.object(agent, "handle", new=AsyncMock(return_value=fallback_result)) as mock_handle,
        ):
            result = await agent.analyze_from_mv(TENANT_ID, STORE_ID)

        mock_handle.assert_awaited_once()
        assert result["escalate_to_human"] is True
        assert result == fallback_result
