"""Brain 编排层 + DiscountGuardianAgent 单元测试

测试范围：
  1. DiscountGuardianAgent.analyze — 正常路径
  2. DiscountGuardianAgent.analyze — Claude 返回非 JSON → fallback warn
  3. DiscountGuardianAgent.analyze — reject 高折扣场景
  4. DiscountGuardianAgent._parse_response — 有效 JSON 提取
  5. DiscountGuardianAgent._parse_response — 无效 JSON → 兜底
  6. FinanceAuditor.analyze — 正常路径（含 constraints_check / source 字段）
  7. FinanceAuditor.analyze — Claude 连接失败 → source=fallback
  8. FinanceAuditor.analyze — Python 强制对齐 constraints_check（覆盖 Claude 错误结果）
  9. _write_decision_log — 正常写入（execute >= 2, commit 1次）
 10. _write_decision_log — DB 报错不抛异常（graceful）
 11. _write_decision_log — 缺少 tenant_id 跳过写入

技术约束：
  - 全部 unittest.mock，不连真实 DB 或 LLM
  - 使用 patch 直接替换模块级 client.messages.create
  - AsyncMock 替代 AsyncSession
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest
from sqlalchemy.exc import SQLAlchemyError

from ..agents.discount_guardian import DiscountGuardianAgent
from ..agents.finance_auditor import FinanceAuditor

# ── 固定测试值 ─────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())

# patch 路径（对应模块内 client = anthropic.AsyncAnthropic() 的 messages.create）
_DG_CREATE = "services.tx_brain.src.agents.discount_guardian.client.messages.create"
_FA_CREATE = "services.tx_brain.src.agents.finance_auditor.client.messages.create"


# ── 工厂函数 ───────────────────────────────────────────────────────────────────


def _make_claude_message(text: str) -> MagicMock:
    """伪造 anthropic Message（content[0].text = text）。"""
    msg = MagicMock()
    block = MagicMock()
    block.text = text
    msg.content = [block]
    return msg


def _make_db_session(raise_on_execute: bool = False) -> AsyncMock:
    db = AsyncMock()
    if raise_on_execute:
        db.execute = AsyncMock(side_effect=SQLAlchemyError("DB down"))
    else:
        db.execute = AsyncMock(return_value=MagicMock())
    db.commit = AsyncMock(return_value=None)
    return db


def _discount_event(
    operator_role: str = "employee",
    discount_rate: float = 0.9,
) -> dict:
    return {
        "operator_id": "emp_001",
        "operator_role": operator_role,
        "dish_id": "dish_001",
        "dish_name": "酸菜鱼",
        "original_price_fen": 6800,
        "discount_type": "manager_discount",
        "discount_rate": discount_rate,
        "table_no": "3",
        "order_id": str(uuid.uuid4()),
        "store_id": STORE_ID,
        "margin_rate": 0.35,
    }


def _finance_payload(
    tenant_id: str = TENANT_ID,
    revenue_fen: int = 100_000,
    cost_fen: int = 50_000,
) -> dict:
    return {
        "tenant_id": tenant_id,
        "store_id": STORE_ID,
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


def _finance_metrics() -> dict:
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


def _finance_result() -> dict:
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


def _valid_discount_response() -> str:
    return json.dumps(
        {
            "decision": "allow",
            "confidence": 0.92,
            "reason": "折扣率在授权范围内，毛利达标",
            "risk_factors": [],
            "constraints_check": {
                "margin_ok": True,
                "authority_ok": True,
                "pattern_ok": True,
            },
        },
        ensure_ascii=False,
    )


def _valid_finance_response() -> str:
    return json.dumps(
        {
            "risk_level": "low",
            "score": 15.0,
            "anomalies": [],
            "audit_suggestions": ["当日财务数据正常"],
            "constraints_check": {
                "margin_ok": True,
                "void_rate_ok": True,
                "cash_diff_ok": True,
            },
        },
        ensure_ascii=False,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  1-3. DiscountGuardianAgent.analyze
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_discount_guardian_analyze_allow():
    """mock Claude → 正确 JSON → decision=allow，三条约束全部 ok。"""
    agent = DiscountGuardianAgent()
    mock_msg = _make_claude_message(_valid_discount_response())

    with patch(_DG_CREATE, new=AsyncMock(return_value=mock_msg)):
        result = await agent.analyze(_discount_event(), history=[])

    assert result["decision"] == "allow"
    assert result["confidence"] == pytest.approx(0.92)
    assert result["constraints_check"]["margin_ok"] is True
    assert result["constraints_check"]["authority_ok"] is True
    assert result["constraints_check"]["pattern_ok"] is True


@pytest.mark.asyncio
async def test_discount_guardian_analyze_reject_over_limit():
    """折扣率0.5（超员工授权范围）→ Claude 返回 reject，authority_ok=False。"""
    agent = DiscountGuardianAgent()
    reject_json = json.dumps(
        {
            "decision": "reject",
            "confidence": 0.97,
            "reason": "折扣率超出员工授权上限",
            "risk_factors": ["折扣率超授权", "毛利低于阈值"],
            "constraints_check": {
                "margin_ok": False,
                "authority_ok": False,
                "pattern_ok": True,
            },
        },
        ensure_ascii=False,
    )
    mock_msg = _make_claude_message(reject_json)

    with patch(_DG_CREATE, new=AsyncMock(return_value=mock_msg)):
        result = await agent.analyze(
            _discount_event(operator_role="employee", discount_rate=0.5),
            history=[],
        )

    assert result["decision"] == "reject"
    assert result["constraints_check"]["authority_ok"] is False


@pytest.mark.asyncio
async def test_discount_guardian_analyze_fallback_on_unparseable_response():
    """Claude 返回无法解析的文字 → fallback warn，不抛异常。"""
    agent = DiscountGuardianAgent()
    mock_msg = _make_claude_message("系统繁忙，无法分析。")

    with patch(_DG_CREATE, new=AsyncMock(return_value=mock_msg)):
        result = await agent.analyze(_discount_event(), history=[])

    assert result["decision"] == "warn"
    assert result["confidence"] == 0.5
    assert "响应解析异常" in result["risk_factors"]


# ══════════════════════════════════════════════════════════════════════════════
#  4-5. DiscountGuardianAgent._parse_response
# ══════════════════════════════════════════════════════════════════════════════


def test_parse_response_extracts_valid_json():
    """_parse_response 从带前缀文字的响应中提取并解析 JSON。"""
    agent = DiscountGuardianAgent()
    raw = f"分析结果如下：\n{_valid_discount_response()}\n以上供参考。"
    result = agent._parse_response(raw)

    assert result["decision"] == "allow"
    assert "constraints_check" in result
    assert result["constraints_check"]["margin_ok"] is True


def test_parse_response_returns_fallback_on_invalid_json():
    """_parse_response 遇到完全无效的文本 → 返回 warn 兜底，不抛异常。"""
    agent = DiscountGuardianAgent()
    result = agent._parse_response("这段文字中没有任何JSON对象，是纯文本乱码。")

    assert result["decision"] == "warn"
    assert result["confidence"] == 0.5
    # 三条约束值应为 None（不确定）
    assert result["constraints_check"]["margin_ok"] is None
    assert result["constraints_check"]["authority_ok"] is None


# ══════════════════════════════════════════════════════════════════════════════
#  6-8. FinanceAuditor.analyze
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_finance_auditor_analyze_returns_required_fields():
    """FinanceAuditor.analyze：mock Claude → 结果包含 risk_level/constraints_check/source。"""
    auditor = FinanceAuditor()
    mock_msg = _make_claude_message(_valid_finance_response())

    with patch(_FA_CREATE, new=AsyncMock(return_value=mock_msg)):
        result = await auditor.analyze(_finance_payload())

    assert "risk_level" in result
    assert "constraints_check" in result
    assert "source" in result
    assert result["source"] == "claude"
    assert result["constraints_check"]["margin_ok"] is True


@pytest.mark.asyncio
async def test_finance_auditor_fallback_on_connection_error():
    """Claude APIConnectionError → source=fallback，不抛异常，仍返回合法结构。"""
    auditor = FinanceAuditor()

    with patch(
        _FA_CREATE,
        new=AsyncMock(
            side_effect=anthropic.APIConnectionError(request=MagicMock())
        ),
    ):
        result = await auditor.analyze(_finance_payload())

    assert result["source"] == "fallback"
    assert "risk_level" in result
    assert "constraints_check" in result


@pytest.mark.asyncio
async def test_finance_auditor_python_overrides_constraints_check():
    """Python 计算必须覆盖 Claude 的 constraints_check。

    revenue=100_000, cost=90_000 → margin_rate=0.9 > 0.65 → margin_ok 必须为 False。
    即使 Claude 错误地返回 margin_ok=True，Python 也会强制纠正。
    """
    auditor = FinanceAuditor()
    # Claude 错误地报告 margin_ok=True
    wrong_json = json.dumps(
        {
            "risk_level": "low",
            "score": 5.0,
            "anomalies": [],
            "audit_suggestions": ["正常"],
            "constraints_check": {
                "margin_ok": True,   # 错误 — 应被 Python 覆盖
                "void_rate_ok": True,
                "cash_diff_ok": True,
            },
        },
        ensure_ascii=False,
    )
    mock_msg = _make_claude_message(wrong_json)

    with patch(_FA_CREATE, new=AsyncMock(return_value=mock_msg)):
        result = await auditor.analyze(
            _finance_payload(revenue_fen=100_000, cost_fen=90_000)  # 成本率 90%
        )

    # Python 强制对齐：成本率超标 → margin_ok 必须为 False
    assert result["constraints_check"]["margin_ok"] is False


# ══════════════════════════════════════════════════════════════════════════════
#  9-11. _write_decision_log 通用行为
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_write_decision_log_writes_and_commits():
    """正常写入：db.execute 至少调用 2 次（set_config + INSERT），commit 1 次。"""
    auditor = FinanceAuditor()
    db = _make_db_session()

    await auditor._write_decision_log(
        db,
        _finance_payload(),
        _finance_metrics(),
        _finance_result(),
        execution_ms=42,
    )

    assert db.execute.call_count >= 2
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_write_decision_log_graceful_on_db_error():
    """DB 故障时不抛异常（graceful degradation），commit 不被调用。"""
    auditor = FinanceAuditor()
    db = _make_db_session(raise_on_execute=True)

    # 不应抛出任何异常
    await auditor._write_decision_log(
        db,
        _finance_payload(),
        _finance_metrics(),
        _finance_result(),
        execution_ms=10,
    )

    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_write_decision_log_skips_empty_tenant_id():
    """tenant_id 为空字符串时，直接跳过，不调用 execute 也不调用 commit。"""
    auditor = FinanceAuditor()
    db = _make_db_session()

    await auditor._write_decision_log(
        db,
        _finance_payload(tenant_id=""),   # 无 tenant_id
        _finance_metrics(),
        _finance_result(),
        execution_ms=5,
    )

    db.execute.assert_not_called()
    db.commit.assert_not_called()
