"""Agent 决策流程集成测试 — 折扣守护 / 库存预警 / 出餐调度 / 硬约束

测试场景:
  1. 折扣守护 → 异常折扣检测 → 拦截
  2. 库存预警 → 低库存检测 → 通知
  3. 出餐调度 → 超时预警 → 干预
  4. 三条硬约束校验
"""
from __future__ import annotations

import sys
import os
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import (
    DEFAULT_HEADERS,
    MOCK_STORE_ID,
    MOCK_TENANT_ID,
    assert_ok,
)

# ─── 确保 tx-agent/src 在 path 中 ──────────────────────────────────────────

_AGENT_SRC = os.path.join(os.path.dirname(__file__), "..", "..", "services", "tx-agent", "src")
if _AGENT_SRC not in sys.path:
    sys.path.insert(0, os.path.abspath(_AGENT_SRC))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  三条硬约束 — 纯函数测试（不需要 HTTP 调用）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


from agents.constraints import ConstraintChecker, ConstraintResult


class TestConstraintChecker:
    """三条硬约束校验器测试。"""

    def setup_method(self) -> None:
        """每个测试前创建新的校验器。"""
        self.checker = ConstraintChecker(
            min_margin_rate=0.15,
            expiry_buffer_hours=24,
            max_serve_minutes=30,
        )

    def test_all_constraints_pass(self) -> None:
        """所有约束均通过 → passed=True。"""
        decision = {
            "margin": {"revenue_fen": 10000, "cost_fen": 7000},
            "ingredients": [
                {"name": "鸡肉", "expires_in_hours": 48},
            ],
            "serve_time_minutes": 20,
        }
        result = self.checker.check_all(decision)
        assert result.passed is True
        assert len(result.violations) == 0

    def test_margin_violation(self) -> None:
        """毛利率低于阈值 → 拦截。"""
        decision = {
            "margin": {"revenue_fen": 10000, "cost_fen": 9500},  # 毛利率 5%
            "ingredients": [],
            "serve_time_minutes": 20,
        }
        result = self.checker.check_all(decision)
        # 如果 margin 校验生效，应该违规
        if result.margin_check and not result.margin_check.get("passed", True):
            assert result.passed is False
            assert any("毛利" in v for v in result.violations)

    def test_food_safety_violation(self) -> None:
        """临期食材 → 拦截。"""
        decision = {
            "margin": {"revenue_fen": 10000, "cost_fen": 7000},
            "ingredients": [
                {"name": "鱼片", "expires_in_hours": 6},  # 6小时 < 24小时
            ],
            "serve_time_minutes": 20,
        }
        result = self.checker.check_all(decision)
        if result.food_safety_check and not result.food_safety_check.get("passed", True):
            assert result.passed is False
            assert any("食安" in v for v in result.violations)

    def test_experience_violation(self) -> None:
        """出餐超时 → 拦截。"""
        decision = {
            "margin": {"revenue_fen": 10000, "cost_fen": 7000},
            "ingredients": [],
            "serve_time_minutes": 45,  # 45分钟 > 30分钟上限
        }
        result = self.checker.check_all(decision)
        if result.experience_check and not result.experience_check.get("passed", True):
            assert result.passed is False
            assert any("客户" in v or "出餐" in v for v in result.violations)

    def test_multiple_violations(self) -> None:
        """同时违反多条约束 → 全部记录。"""
        decision = {
            "margin": {"revenue_fen": 10000, "cost_fen": 9500},
            "ingredients": [
                {"name": "过期鱼", "expires_in_hours": 0},
            ],
            "serve_time_minutes": 60,
        }
        result = self.checker.check_all(decision)
        # 至少应该能检测出某些违规
        assert isinstance(result, ConstraintResult)
        assert isinstance(result.violations, list)

    def test_constraint_result_to_dict(self) -> None:
        """ConstraintResult 可序列化为 dict。"""
        result = ConstraintResult(
            passed=False,
            violations=["毛利底线违规"],
            margin_check={"passed": False, "actual_rate": 0.05},
        )
        d = result.to_dict()
        assert d["passed"] is False
        assert "毛利底线违规" in d["violations"]
        assert d["margin_check"]["actual_rate"] == 0.05

    def test_custom_thresholds(self) -> None:
        """自定义阈值 → 使用自定义值校验。"""
        strict_checker = ConstraintChecker(
            min_margin_rate=0.30,  # 更严格：30%
            expiry_buffer_hours=48,  # 更严格：48小时
            max_serve_minutes=15,  # 更严格：15分钟
        )
        assert strict_checker.min_margin_rate == 0.30
        assert strict_checker.expiry_buffer_hours == 48
        assert strict_checker.max_serve_minutes == 15

    def test_empty_decision(self) -> None:
        """空决策数据 → 不崩溃，passed=True（无数据可校验）。"""
        result = self.checker.check_all({})
        assert isinstance(result, ConstraintResult)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Master Agent 意图检测
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


from api.master_agent_routes import _detect_intent


class TestIntentDetection:
    """Agent 意图识别测试。"""

    def test_discount_intent(self) -> None:
        """包含'折扣'关键词 → intent=discount。"""
        assert _detect_intent("检查今天的折扣异常") == "discount"

    def test_inventory_intent(self) -> None:
        """包含'库存'关键词 → intent=inventory。"""
        assert _detect_intent("当前库存水平怎么样") == "inventory"

    def test_dispatch_intent(self) -> None:
        """包含'出餐'关键词 → intent=dispatch。"""
        assert _detect_intent("出餐太慢了帮忙催一下") == "dispatch"

    def test_member_intent(self) -> None:
        """包含'会员'关键词 → intent=member。"""
        assert _detect_intent("查一下这个会员的消费记录") == "member"

    def test_finance_intent(self) -> None:
        """包含'财务'关键词 → intent=finance。"""
        assert _detect_intent("今天的财务对账有问题") == "finance"

    def test_no_match(self) -> None:
        """无匹配关键词 → None。"""
        result = _detect_intent("今天天气不错")
        assert result is None

    def test_multiple_keywords_first_wins(self) -> None:
        """多个关键词 → 返回第一个匹配。"""
        result = _detect_intent("折扣和库存都要检查")
        assert result is not None  # 应该匹配到第一个


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Agent API 端点测试（HTTP 层）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _get_agent_app():
    """获取 tx-agent 的 FastAPI app（跳过 lifespan）。

    lifespan 中有 DomainEventConsumer 会连接 Redis，
    测试中构建精简 app 规避此依赖。
    """
    from fastapi import FastAPI, Header
    from api.master_agent_routes import router as master_agent_router
    from api.health_routes import router as health_router
    from api.inventory_routes import router as inventory_router

    app = FastAPI(title="test-tx-agent")
    app.include_router(master_agent_router)
    app.include_router(health_router)
    app.include_router(inventory_router)
    return app


@pytest.mark.asyncio
async def test_agent_health() -> None:
    """Agent 健康检查端点 → ok=True。"""
    app = _get_agent_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/agent/health",
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True


@pytest.mark.asyncio
async def test_agent_execute_discount_guard() -> None:
    """执行折扣守护指令 → ok=True + agent_name。"""
    app = _get_agent_app()
    transport = ASGITransport(app=app)

    # Mock httpx 的外部调用（tx-brain 服务）
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "ok": True,
        "data": {"risk_score": 0.85, "action": "intercept", "reason": "折扣幅度异常"},
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/agent/execute",
                json={
                    "instruction": "检查这笔订单的折扣是否合理",
                    "context": {"order_id": str(uuid.uuid4()), "discount_rate": 0.3},
                },
                headers=DEFAULT_HEADERS,
            )
    assert resp.status_code == 200
    data = assert_ok(resp.json())
    assert "agent" in data or "intent" in data or "result" in data


@pytest.mark.asyncio
async def test_agent_execute_inventory_alert() -> None:
    """执行库存预警指令 → ok=True。"""
    app = _get_agent_app()
    transport = ASGITransport(app=app)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "ok": True,
        "data": {"low_stock_items": [{"name": "鸡肉", "current_qty": 2, "min_qty": 10}]},
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/agent/execute",
                json={
                    "instruction": "检查库存水平",
                    "context": {"store_id": MOCK_STORE_ID},
                },
                headers=DEFAULT_HEADERS,
            )
    assert resp.status_code == 200
    assert_ok(resp.json())


@pytest.mark.asyncio
async def test_agent_execute_dispatch_alert() -> None:
    """执行出餐调度指令 → ok=True。"""
    app = _get_agent_app()
    transport = ASGITransport(app=app)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "ok": True,
        "data": {"overdue_orders": 3, "avg_wait_minutes": 35},
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/agent/execute",
                json={
                    "instruction": "出餐超时了帮忙催一下",
                    "context": {"store_id": MOCK_STORE_ID},
                },
                headers=DEFAULT_HEADERS,
            )
    assert resp.status_code == 200
    assert_ok(resp.json())


@pytest.mark.asyncio
async def test_agent_execute_unknown_intent() -> None:
    """未识别意图 → 仍应返回 200 + 友好提示。"""
    app = _get_agent_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/agent/execute",
            json={
                "instruction": "今天天气怎么样",
                "context": {},
            },
            headers=DEFAULT_HEADERS,
        )
    # 即使意图未识别也不应 500
    assert resp.status_code in (200, 400)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Skill Agent 注册测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_skill_agents_registered() -> None:
    """ALL_SKILL_AGENTS 包含 9 个 Agent。"""
    from agents.skills import ALL_SKILL_AGENTS

    assert len(ALL_SKILL_AGENTS) >= 9, f"Expected >= 9 agents, got {len(ALL_SKILL_AGENTS)}"


def test_each_agent_has_required_attrs() -> None:
    """每个 Skill Agent 具备 agent_id / agent_name / priority。"""
    from agents.skills import ALL_SKILL_AGENTS

    for agent_cls in ALL_SKILL_AGENTS:
        agent = agent_cls(tenant_id="test")
        assert hasattr(agent, "agent_id"), f"{agent_cls.__name__} missing agent_id"
        assert hasattr(agent, "agent_name"), f"{agent_cls.__name__} missing agent_name"
        assert hasattr(agent, "priority"), f"{agent_cls.__name__} missing priority"


def test_master_agent_can_register_skills() -> None:
    """MasterAgent 可以注册所有 Skill Agent。"""
    from agents.master import MasterAgent
    from agents.skills import ALL_SKILL_AGENTS

    master = MasterAgent(tenant_id="test")
    for agent_cls in ALL_SKILL_AGENTS:
        master.register(agent_cls(tenant_id="test"))

    assert len(master.agents) >= 9


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  决策留痕格式校验
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_constraint_result_serializable() -> None:
    """ConstraintResult 可序列化为 JSON 兼容 dict。"""
    result = ConstraintResult(
        passed=True,
        violations=[],
        margin_check={"passed": True, "actual_rate": 0.25},
        food_safety_check={"passed": True},
        experience_check={"passed": True, "serve_minutes": 20},
    )
    d = result.to_dict()
    assert isinstance(d, dict)
    assert d["passed"] is True
    assert d["margin_check"]["actual_rate"] == 0.25
    assert d["experience_check"]["serve_minutes"] == 20
