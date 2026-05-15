"""Wave 4 PR-1 — tx-agent 26 silent failure sites 可观测性回归门哨.

验证修复后的 logger.warning/debug 在异常路径被实际触发,
保留原 pass / return None 行为不变 (业务语义不影响).

覆盖:
  - AI router fallback → warning (personalization_agent)
  - DB error fallback  → warning (growth_coach)
  - type coerce        → debug  (banquet_contract_agent._coerce_uuid)

Note on import strategy:
  agents/skills/__init__.py imports reservation_concierge which has top-level
  'from shared.ontology...' — unavailable in Python 3.9 test env (str|None union).
  We load the target modules directly via importlib with the package namespace
  pre-seeded in sys.modules so relative imports resolve correctly.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from unittest.mock import AsyncMock

import pytest

# ── sys.path ─────────────────────────────────────────────────────────────────
TX_AGENT_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

if TX_AGENT_SRC not in sys.path:
    sys.path.insert(0, TX_AGENT_SRC)


def _load_module_direct(rel_path: str, module_name: str) -> types.ModuleType:
    """Load a .py file as a module with a given name, bypassing package __init__.

    Relative imports (e.g. '..base') work because we pre-seed the parent
    package namespaces in sys.modules before loading.
    """
    abs_path = os.path.join(TX_AGENT_SRC, rel_path)
    spec = importlib.util.spec_from_file_location(module_name, abs_path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _ensure_package_stubs() -> None:
    """Seed package stubs so relative imports resolve without loading __init__.py."""
    # agents package stub
    if "agents" not in sys.modules:
        agents_pkg = types.ModuleType("agents")
        agents_pkg.__path__ = [os.path.join(TX_AGENT_SRC, "agents")]  # type: ignore[assignment]
        agents_pkg.__package__ = "agents"
        sys.modules["agents"] = agents_pkg

    # agents.base (needed by relative '..base' in skills)
    if "agents.base" not in sys.modules:
        _load_module_direct("agents/base.py", "agents.base")
        agents_pkg = sys.modules["agents"]
        agents_pkg.base = sys.modules["agents.base"]  # type: ignore[attr-defined]

    # agents.context (needed by some skills)
    if "agents.context" not in sys.modules:
        try:
            _load_module_direct("agents/context.py", "agents.context")
        except Exception:
            sys.modules["agents.context"] = types.ModuleType("agents.context")

    # agents.skills package stub (bypass __init__ which pulls reservation_concierge)
    if "agents.skills" not in sys.modules:
        skills_pkg = types.ModuleType("agents.skills")
        skills_pkg.__path__ = [os.path.join(TX_AGENT_SRC, "agents", "skills")]  # type: ignore[assignment]
        skills_pkg.__package__ = "agents.skills"
        sys.modules["agents.skills"] = skills_pkg


_ensure_package_stubs()


# ─────────────────────────────────────────────────────────────────────────────
# 1. AI router fallback → logger.warning (personalization_agent)
# ─────────────────────────────────────────────────────────────────────────────


class TestPersonalizationAiRouterWarning:
    """personalization_agent._generate_dish_reason: AI router 抛异常 → warning 日志."""

    @pytest.mark.asyncio
    async def test_dish_reason_ai_router_failed_emits_warning(self):
        """router.complete 抛 RuntimeError → warning 日志 + 降级规则结果."""
        from structlog.testing import capture_logs

        if "agents.skills.personalization_agent" not in sys.modules:
            _load_module_direct(
                "agents/skills/personalization_agent.py",
                "agents.skills.personalization_agent",
            )
        PersonalizationAgent = sys.modules["agents.skills.personalization_agent"].PersonalizationAgent

        mock_router = AsyncMock()
        mock_router.complete.side_effect = RuntimeError("upstream timeout")

        agent = PersonalizationAgent.__new__(PersonalizationAgent)
        agent._router = mock_router
        agent.agent_id = "personalization"
        agent.tenant_id = "t1"

        params = {
            "dish_name": "红烧肉",
            "reason_type": "history",
            "user_prefs": {"spicy": 1, "top_dishes": ["红烧肉"]},
        }

        with capture_logs() as logs:
            result = await agent._generate_dish_reason(params)

        # 业务行为保留：降级成功（router 失败后仍返回推荐结果）
        assert result.success is True
        assert result.data["dish_name"] == "红烧肉"
        assert result.data.get("reason") is not None  # 规则降级填充了推荐理由

        # 可观测性：warning 被记录
        warning_logs = [
            log for log in logs
            if log.get("log_level") == "warning"
            and log.get("event") == "personalization_dish_reason_ai_failed"
        ]
        assert len(warning_logs) == 1, (
            f"应有 1 条 personalization_dish_reason_ai_failed warning; 实际 logs={logs!r}"
        )
        assert "upstream timeout" in warning_logs[0].get("error", "")


# ─────────────────────────────────────────────────────────────────────────────
# 2. DB error fallback → logger.warning (growth_coach)
# ─────────────────────────────────────────────────────────────────────────────


class TestGrowthCoachDbWarning:
    """growth_coach._load_training_courses: DB 异常 → warning 日志 + 降级内置课程."""

    @pytest.mark.asyncio
    async def test_db_query_failed_emits_warning(self):
        """OperationalError → warning 日志 + fallback _TRAINING_COURSES."""
        from structlog.testing import capture_logs

        try:
            from sqlalchemy.exc import OperationalError
        except ImportError:
            pytest.skip("sqlalchemy not available")

        if "agents.skills.growth_coach" not in sys.modules:
            _load_module_direct(
                "agents/skills/growth_coach.py",
                "agents.skills.growth_coach",
            )
        gc_module = sys.modules["agents.skills.growth_coach"]

        mock_db = AsyncMock()
        mock_db.execute.side_effect = OperationalError("DB conn", None, None)

        with capture_logs() as logs:
            result = await gc_module._load_training_courses(
                db=mock_db,
                tenant_id="t1",
            )

        # 业务行为保留：返回内置课程（降级）
        assert result is gc_module._TRAINING_COURSES

        # 可观测性：warning 被记录
        warning_logs = [
            log for log in logs
            if log.get("log_level") == "warning"
            and log.get("event") == "growth_coach_db_query_failed"
        ]
        assert len(warning_logs) == 1, (
            f"应有 1 条 growth_coach_db_query_failed warning; 实际 logs={logs!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3. type coerce → logger.debug (banquet_contract_agent._coerce_uuid)
# ─────────────────────────────────────────────────────────────────────────────


class TestBanquetContractCoerceUuidDebug:
    """banquet_contract_agent._coerce_uuid: 无效输入 → debug 日志 + return None."""

    def test_invalid_uuid_emits_debug(self):
        """非法 UUID 字符串 → debug 日志 + None 返回."""
        from structlog.testing import capture_logs

        if "agents.skills.banquet_contract_agent" not in sys.modules:
            _load_module_direct(
                "agents/skills/banquet_contract_agent.py",
                "agents.skills.banquet_contract_agent",
            )
        _coerce_uuid = sys.modules["agents.skills.banquet_contract_agent"]._coerce_uuid

        with capture_logs() as logs:
            result = _coerce_uuid("not-a-valid-uuid-!!!")

        # 业务行为保留：返回 None
        assert result is None

        # 可观测性：debug 被记録
        debug_logs = [
            log for log in logs
            if log.get("log_level") == "debug"
            and log.get("event") == "banquet_contract_coerce_uuid_failed"
        ]
        assert len(debug_logs) == 1, (
            f"应有 1 条 banquet_contract_coerce_uuid_failed debug; 实際 logs={logs!r}"
        )
        assert "not-a-valid-uuid" in debug_logs[0].get("value", "")
