"""Tier 1 — NLQ SQL Generator 工厂 + 真 ModelRouter wiring (PR2.B.2)。

本组测试需要真 anthropic SDK（MigrationRouter 在 _init_legacy 直接 import）。
本地 dev 缺包时 skip；CI Tier 1 跑 tx-brain 时 requirements.txt 已含 anthropic>=0.25.0。

校验点：
  1. ANTHROPIC_API_KEY 缺失 → 工厂透传 ValueError（让上层 SSE 503）
  2. ANTHROPIC_API_KEY 存在 → 工厂返回 SqlGenerator + 真 router 实现 ModelRouterLike
  3. shared/ai_providers/migration.py _task_model_map 显式含 nlq_sql_generation 映射

Refs: issue #289
"""

from __future__ import annotations

import pytest

# 本地缺 anthropic SDK 时 skip 整个 module（不影响主测试文件 22 mock 用例）
pytest.importorskip(
    "anthropic",
    reason="anthropic SDK 未安装；tx-brain CI 必装，本地 skip",
)

from services.sql_generator import (  # noqa: E402
    SqlGenerator,
    create_default_sql_generator,
)


def test_factory_raises_when_api_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ANTHROPIC_API_KEY 未设置时，工厂必须抛 ValueError（让上层 SSE 503）。"""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("MULTI_PROVIDER_ENABLED", "false")

    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        create_default_sql_generator()


def test_factory_returns_sql_generator_with_real_router(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """有 API key 时，工厂返回 SqlGenerator + 真 router（duck-type 检查）。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake-test-key")
    monkeypatch.setenv("MULTI_PROVIDER_ENABLED", "false")

    gen = create_default_sql_generator()
    assert isinstance(gen, SqlGenerator)
    # router 必须实现 complete()（duck-type 即可，匹配 ModelRouterLike）
    assert hasattr(gen._router, "complete")  # type: ignore[attr-defined]
    assert callable(gen._router.complete)  # type: ignore[attr-defined]


def test_task_model_map_has_nlq_sql_generation_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_task_model_map 必须显式含 nlq_sql_generation 映射。

    防漂移：未显式映射时落 default sonnet（行为相同），但显式 entry 让模型选择
    策略可见可改 —— 后续 prompt 调优若发现需 opus，单点改 map 即可。
    """
    from shared.ai_providers.migration import MigrationRouter

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake-test-key")
    monkeypatch.setenv("MULTI_PROVIDER_ENABLED", "false")

    router = MigrationRouter()
    assert "nlq_sql_generation" in router._task_model_map  # type: ignore[attr-defined]
    # NLQ SQL 生成需中等推理能力（schema 约束理解 + JSON 格式输出）；sonnet 合理
    assert "sonnet" in router._task_model_map["nlq_sql_generation"].lower()  # type: ignore[attr-defined]
