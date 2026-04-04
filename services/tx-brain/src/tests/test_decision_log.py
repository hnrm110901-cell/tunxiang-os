"""FinanceAuditor._write_decision_log 单元测试

测试范围：
  - _write_decision_log：正常写入 / DB 报错不阻断主流程 / 缺少 tenant_id 跳过
  - _write_mv_decision_log：物化视图快速通道的决策日志写入
  - 日志字段完整性验证（id / tenant_id / store_id / agent_id / decision_type 等必填字段）

技术约束：
  - 全部使用 unittest.mock，不连接真实数据库
  - AsyncSession 以 AsyncMock 替代
  - SQLAlchemyError 注入模拟 DB 故障
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call
import json

import pytest
from sqlalchemy.exc import SQLAlchemyError

# ── 被测模块 ──────────────────────────────────────────────────────────────────

from ..agents.finance_auditor import FinanceAuditor

# ── 测试固定值 ─────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())


def _make_db_session(raise_on_execute: bool = False) -> AsyncMock:
    """返回模拟的 AsyncSession。"""
    db = AsyncMock()
    if raise_on_execute:
        db.execute = AsyncMock(side_effect=SQLAlchemyError("DB connection refused"))
    else:
        db.execute = AsyncMock(return_value=MagicMock())
    db.commit = AsyncMock(return_value=None)
    return db


def _make_payload(
    tenant_id: str = TENANT_ID,
    store_id: str = STORE_ID,
    revenue_fen: int = 100_000,
    cost_fen: int = 50_000,
) -> dict:
    return {
        "tenant_id": tenant_id,
        "store_id": store_id,
        "date": "2026-04-04",
        "revenue_fen": revenue_fen,
        "cost_fen": cost_fen,
        "discount_total_fen": 5_000,
        "void_count": 1,
        "void_amount_fen": 2_000,
        "cash_actual_fen": 95_000,
        "cash_expected_fen": 95_000,
        "high_discount_orders": [],
        "total_order_count": 50,
    }


def _make_result() -> dict:
    return {
        "risk_level": "low",
        "score": 20.0,
        "anomalies": [],
        "audit_suggestions": ["当日财务数据正常"],
        "constraints_check": {
            "margin_ok": True,
            "void_rate_ok": True,
            "cash_diff_ok": True,
        },
        "source": "claude",
    }


def _make_metrics() -> dict:
    return {
        "revenue_yuan": 1000.0,
        "cost_yuan": 500.0,
        "margin_rate": 0.50,
        "discount_rate": 0.05,
        "void_rate": 0.02,
        "void_count": 1,
        "void_amount_yuan": 20.0,
        "cash_diff_fen": 0,
        "cash_diff_yuan": 0.0,
        "cash_actual_yuan": 950.0,
        "cash_expected_yuan": 950.0,
        "high_discount_count": 0,
        "margin_ok": True,
        "void_rate_ok": True,
        "cash_diff_ok": True,
        "margin_alert": False,
        "void_rate_alert": False,
        "cash_diff_alert": False,
        "discount_alert": False,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  TestDecisionLog — _write_decision_log 行为测试
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestDecisionLog:
    """测试 FinanceAuditor._write_decision_log 的核心行为。"""

    async def test_writes_log_on_success(self):
        """正常情况下应向 agent_decision_logs 写入记录，db.commit() 被调用一次。"""
        auditor = FinanceAuditor()
        db = _make_db_session()
        payload = _make_payload()
        metrics = _make_metrics()
        result = _make_result()

        await auditor._write_decision_log(db, payload, metrics, result, execution_ms=42)

        # db.execute 至少调用了两次：set_config + INSERT INTO agent_decision_logs
        assert db.execute.call_count >= 2
        db.commit.assert_called_once()

    async def test_does_not_raise_on_db_error(self):
        """DB 故障时 _write_decision_log 不应抛出异常（不阻塞主流程）。"""
        auditor = FinanceAuditor()
        db = _make_db_session(raise_on_execute=True)
        payload = _make_payload()
        metrics = _make_metrics()
        result = _make_result()

        # 不应抛出任何异常
        await auditor._write_decision_log(db, payload, metrics, result, execution_ms=10)

        # commit 不应被调用（execute 已失败）
        db.commit.assert_not_called()

    async def test_skips_when_no_tenant_id(self):
        """payload 缺少 tenant_id 时，应跳过写入（execute 不被调用）。"""
        auditor = FinanceAuditor()
        db = _make_db_session()
        payload = _make_payload(tenant_id="")  # 空字符串 = 无 tenant_id
        metrics = _make_metrics()
        result = _make_result()

        await auditor._write_decision_log(db, payload, metrics, result, execution_ms=5)

        db.execute.assert_not_called()
        db.commit.assert_not_called()

    async def test_log_contains_required_fields(self):
        """写入的 INSERT 语句参数中应包含所有必填字段：
        id / tenant_id / store_id / agent_id / decision_type"""
        auditor = FinanceAuditor()

        captured_params: list[dict] = []

        async def capture_execute(sql_or_text, params=None, **kw):
            if params and isinstance(params, dict) and "agent_id" in params:
                captured_params.append(params)

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=capture_execute)
        db.commit = AsyncMock()

        payload = _make_payload()
        metrics = _make_metrics()
        result = _make_result()

        await auditor._write_decision_log(db, payload, metrics, result, execution_ms=15)

        assert len(captured_params) == 1, "应该恰好有一次 INSERT 调用"
        params = captured_params[0]

        # 验证必填字段存在且非空
        assert params["id"]                            # UUID
        assert params["tenant_id"] == TENANT_ID
        assert params["store_id"] == STORE_ID
        assert params["agent_id"] == "finance_auditor"
        assert params["decision_type"] == "daily_audit"

    async def test_log_confidence_reflects_source(self):
        """claude 来源的 confidence 应为 0.9，fallback 来源的应为 0.7。"""
        auditor = FinanceAuditor()

        captured_params: list[dict] = []

        async def capture_execute(sql_or_text, params=None, **kw):
            if params and isinstance(params, dict) and "confidence" in params:
                captured_params.append(params)

        for source, expected_conf in [("claude", 0.9), ("fallback", 0.7)]:
            captured_params.clear()
            db = AsyncMock()
            db.execute = AsyncMock(side_effect=capture_execute)
            db.commit = AsyncMock()

            result = _make_result()
            result["source"] = source
            payload = _make_payload()
            metrics = _make_metrics()

            await auditor._write_decision_log(db, payload, metrics, result, execution_ms=20)
            assert len(captured_params) == 1
            assert captured_params[0]["confidence"] == expected_conf, (
                f"source={source} 应对应 confidence={expected_conf}"
            )


# ══════════════════════════════════════════════════════════════════════════════
#  TestMvDecisionLog — _write_mv_decision_log 行为测试
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestMvDecisionLog:
    """测试物化视图快速通道的决策日志写入。"""

    async def test_mv_log_writes_on_success(self):
        """_write_mv_decision_log 正常情况下应写入并 commit。"""
        auditor = FinanceAuditor()
        db = _make_db_session()
        mv_context = {
            "revenue_fen": 100_000,
            "gross_profit_fen": 50_000,
            "gross_margin": 0.50,
            "total_orders": 50,
            "avg_order_fen": 2_000,
            "food_cost_fen": 30_000,
            "labor_cost_fen": 10_000,
            "other_cost_fen": 10_000,
        }
        result = _make_result()
        result["source"] = "claude_mv"

        await auditor._write_mv_decision_log(
            db,
            store_id=STORE_ID,
            tenant_id=TENANT_ID,
            stat_date=date(2026, 4, 4),
            mv_context=mv_context,
            result=result,
            execution_ms=5,
        )

        assert db.execute.call_count >= 2
        db.commit.assert_called_once()

    async def test_mv_log_skips_when_no_tenant_id(self):
        """缺少 tenant_id 时，应直接返回，不执行任何 DB 操作。"""
        auditor = FinanceAuditor()
        db = _make_db_session()

        await auditor._write_mv_decision_log(
            db,
            store_id=STORE_ID,
            tenant_id="",
            stat_date=date(2026, 4, 4),
            mv_context={},
            result=_make_result(),
            execution_ms=3,
        )

        db.execute.assert_not_called()

    async def test_mv_log_does_not_raise_on_db_error(self):
        """DB 故障时 _write_mv_decision_log 不应抛出异常。"""
        auditor = FinanceAuditor()
        db = _make_db_session(raise_on_execute=True)

        await auditor._write_mv_decision_log(
            db,
            store_id=STORE_ID,
            tenant_id=TENANT_ID,
            stat_date=date(2026, 4, 4),
            mv_context={"gross_margin": 0.45},
            result=_make_result(),
            execution_ms=5,
        )

        db.commit.assert_not_called()
