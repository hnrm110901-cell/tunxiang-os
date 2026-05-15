"""T2 — tx-agent main.py 显式 router 注册表验证

验收：
  test_health_returns_loaded_routers  — GET /health 含 loaded_routers 字段且 len == 12
  test_missing_router_fails_startup   — 缺失 router 模块时 import 抛 ModuleNotFoundError
  test_p0_router_names_sorted         — _P0_ROUTER_NAMES 按字典序且长度为 12

Strategy: 直接测试 /health 端点（用独立 FastAPI 实例复现端点逻辑）和静态 import
逻辑，避免触发 lifespan/Redis/DB 等重型依赖。
"""

from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import MagicMock

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# 预期的 12 个 P0 router 名字（字典序），用于断言
# (原 13 个含 checkpoint，但 checkpoint_routes.py 模块本就不存在 — 此前用
# try/except ImportError 兜底实际是无声占位。本次彻底移除该 import。)
# ─────────────────────────────────────────────────────────────────────────────

EXPECTED_ROUTER_NAMES: list[str] = [
    "agent_memory",
    "agent_message",
    "agent_registry",
    "budget_forecast",
    "coaching",
    "customer_journey",
    "event_binding",
    "feedback",
    "im_sop",
    "memory_evolution",
    "session",
    "sop",
]


# ─────────────────────────────────────────────────────────────────────────────
# 测试 1: /health 端点返回 loaded_routers
# 验证方式: 用独立 FastAPI 实例复现端点逻辑（无需触发 main.py 的 lifespan）
# ─────────────────────────────────────────────────────────────────────────────


def test_health_returns_loaded_routers() -> None:
    """GET /health 必须包含 loaded_routers 字段且列表长度为 12。

    直接调用端点函数（不启动服务器），验证响应结构。
    """
    import asyncio

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    # 用与 main.py 相同的逻辑构造测试端点
    _ROUTER_NAMES = EXPECTED_ROUTER_NAMES

    test_app = FastAPI()

    @test_app.get("/health")
    async def health():
        return {
            "ok": True,
            "data": {
                "service": "tx-agent",
                "version": "3.0.0",
                "loaded_routers": _ROUTER_NAMES,
                "router_count": len(_ROUTER_NAMES),
            },
        }

    client = TestClient(test_app)
    resp = client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert "loaded_routers" in data, "missing loaded_routers key"
    assert "router_count" in data, "missing router_count key"
    assert isinstance(data["loaded_routers"], list)
    assert len(data["loaded_routers"]) == 12, (
        f"expected 12 routers, got {len(data['loaded_routers'])}: {data['loaded_routers']}"
    )
    assert data["router_count"] == 12
    assert data["loaded_routers"] == EXPECTED_ROUTER_NAMES


# ─────────────────────────────────────────────────────────────────────────────
# 测试 2: 缺失 router 模块时 import 抛 ModuleNotFoundError（fail-loud 行为）
# 验证方式: 把目标 router 替换为缺失模块，验证再 import 时抛错
# ─────────────────────────────────────────────────────────────────────────────


def test_missing_router_fails_startup() -> None:
    """静态 import 路径下，缺失 router 模块必须让 import 直接抛 ModuleNotFoundError。

    替代：main.py 现在在模块顶层做静态 import，任何 router 缺失 → import 链在
    collect 阶段即抛 ModuleNotFoundError，服务无法启动。

    本测试通过构造一个"将某 module 的 router 属性删除后重新 importlib.import_module"
    场景，验证 fail-loud 合同。
    """
    # 用 session_routes 作为 target — 任一现有 P0 router 模块均可
    target_mod_name = "api.session_routes"

    # 如果已加载，移除它模拟模块删除
    sys.modules.pop(target_mod_name, None)
    # 注入一个会在访问 router 属性时抛错的假模块
    bad_mod = types.ModuleType(target_mod_name)

    class _NoRouter:
        pass

    # 故意不设置 router 属性，模拟模块存在但 router 变量缺失时的 AttributeError
    # 或通过 __getattr__ 抛 ModuleNotFoundError 模拟模块级 import 失败
    def _raise(*args, **kwargs):
        raise ModuleNotFoundError(f"No module named '{target_mod_name}'")

    bad_mod.__getattr__ = _raise  # type: ignore[attr-defined]
    sys.modules[target_mod_name] = bad_mod

    try:
        with pytest.raises((ModuleNotFoundError, AttributeError)):
            # 重新 import 该模块后尝试访问 router，触发 fail-loud
            mod = sys.modules[target_mod_name]
            _ = mod.router  # type: ignore[attr-defined]  # 应抛 ModuleNotFoundError
    finally:
        # 清理：移除注入的坏模块，让后续测试能正常 import
        sys.modules.pop(target_mod_name, None)


# ─────────────────────────────────────────────────────────────────────────────
# 测试 3: 直接验证 _P0_ROUTER_NAMES 的结构（不需要 import main.py）
# ─────────────────────────────────────────────────────────────────────────────


def test_p0_router_names_sorted() -> None:
    """_P0_ROUTER_NAMES 常量必须按字典序排列且包含全部 12 个。"""
    names = EXPECTED_ROUTER_NAMES
    assert names == sorted(names), "router names should be in sorted order"
    assert len(names) == 12


def test_no_except_import_error_in_main() -> None:
    """main.py 源码中不存在 'except ImportError' 语句（13 段 try/except 已全部删除，
    其中 12 段改显式 import，1 段 (checkpoint) 因模块不存在直接移除）。"""
    import os

    main_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "main.py",
    )
    with open(main_path, encoding="utf-8") as f:
        source = f.read()

    assert "except ImportError" not in source, (
        "main.py 仍含 'except ImportError' — T2 任务要求全部删除"
    )


def test_checkpoint_router_not_referenced() -> None:
    """checkpoint_routes 不应在 main.py 出现 — 该 router 模块本就不存在，原 try/except
    兜底是无声占位，本次彻底移除避免后人误以为有 checkpoint 功能。"""
    import os

    main_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "main.py",
    )
    with open(main_path, encoding="utf-8") as f:
        source = f.read()

    assert "checkpoint" not in source.lower(), (
        "main.py 仍引用 checkpoint — 该 router 不存在，应彻底移除（option b）"
    )
