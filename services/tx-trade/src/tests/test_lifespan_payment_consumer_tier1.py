"""Tier 1 — payment_event_consumer 启动 fail-loud 测试（W1-T1）

资金链路 (CLAUDE.md §17)：tx-pay → tx-trade 支付事件消费者启动失败时，tx-trade
lifespan 必须 fail-loud — 让 k8s readiness probe 直接拒绝服务上线，而非以
"无支付事件消费"的残废状态启动。

历史背景：`fd94028e feat(payment+rls): 支付事件消费者...` (PR #128) 引入
broad `except Exception: warning(...)` 静吞，导致 redis 不可达 / topic 配置错
等 boot 失败时 tx-trade 仍能起来，订单永远 stuck 在 paying — 这是 P0 资金风险。

测试契约（W1-T1）：
  T1. consumer.create 抛 → helper 重新抛（不静吞）
  T2. consumer.start  抛 → helper 重新抛（不静吞）
  T3. 正常路径：consumer 启动成功 → register_background_task 被调用 → 返回 task
  T4. AST 守护：main.py lifespan 不再有 broad `except Exception:` 静吞
       payment_event_consumer 块（防止回归）
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ─── 路径锚点 ────────────────────────────────────────────────
_MAIN_PY = Path(__file__).resolve().parents[1] / "main.py"


# ─── T1: create 抛 → helper 重抛 ─────────────────────────────


@pytest.mark.asyncio
async def test_create_raises_helper_reraises(monkeypatch):
    """create_payment_event_consumer 抛 → helper 不得静吞。

    场景：boot 期 redis 连接尚未就绪 / 配置错 → 工厂初始化失败。
    旧代码 silent warning → 服务起来但不消费支付事件 (P0 资金风险)。
    新代码必须重新抛 → readiness probe 失败。
    """
    from src.services import payment_consumer_lifecycle as lc
    from src.services import payment_event_consumer as pec_mod

    class _BootError(RuntimeError):
        pass

    def _raise_create(_session_factory):
        raise _BootError("redis stream not reachable at boot")

    monkeypatch.setattr(pec_mod, "create_payment_event_consumer", _raise_create)

    with pytest.raises(_BootError, match="redis stream not reachable"):
        await lc.start_payment_event_consumer_or_raise(
            session_factory=MagicMock(),
            register_background_task=lambda t: t,
        )


# ─── T2: start 抛 → helper 重抛 ──────────────────────────────


@pytest.mark.asyncio
async def test_start_raises_helper_reraises(monkeypatch):
    """start_payment_event_consumer 抛 → helper 不得静吞。

    场景：consumer 实例化 OK 但 XREADGROUP / XADD 错；旧代码同样静吞。
    """
    from src.services import payment_consumer_lifecycle as lc
    from src.services import payment_event_consumer as pec_mod

    monkeypatch.setattr(
        pec_mod, "create_payment_event_consumer", lambda _sf: MagicMock()
    )

    class _StartError(RuntimeError):
        pass

    async def _raise_start(_consumer, _sf):
        raise _StartError("xreadgroup error at start")

    monkeypatch.setattr(pec_mod, "start_payment_event_consumer", _raise_start)

    with pytest.raises(_StartError, match="xreadgroup error"):
        await lc.start_payment_event_consumer_or_raise(
            session_factory=MagicMock(),
            register_background_task=lambda t: t,
        )


# ─── T3: 正常路径 — register_background_task 被调用 ──────────


@pytest.mark.asyncio
async def test_happy_path_registers_and_returns_task(monkeypatch):
    """正常路径：consumer 启动成功 → register_background_task 注册 task → 返回 task。"""
    from src.services import payment_consumer_lifecycle as lc
    from src.services import payment_event_consumer as pec_mod

    monkeypatch.setattr(
        pec_mod, "create_payment_event_consumer", lambda _sf: MagicMock()
    )

    async def _noop():
        await asyncio.sleep(0)

    started_task = asyncio.create_task(_noop())

    async def _fake_start(_consumer, _sf):
        return started_task

    monkeypatch.setattr(pec_mod, "start_payment_event_consumer", _fake_start)

    registered: list = []

    def _register(t):
        registered.append(t)
        return t

    result = await lc.start_payment_event_consumer_or_raise(
        session_factory=MagicMock(),
        register_background_task=_register,
    )

    assert result is started_task
    assert registered == [started_task]
    await started_task  # 清理 fixture


# ─── T4: 源码守护 — main.py lifespan 不再静吞 ────────────────


def test_lifespan_payment_event_consumer_no_silent_except():
    """CLAUDE.md §14（禁 broad except）+ §17（Tier 1 fail-loud）联合源码锁。

    lifespan() 中 payment_event_consumer 调用区段，不得存在：
      (a) bare `except:` 静吞
      (b) `except Exception:` 静吞（无 bare-re-raise）

    这是回归防护 — 防止后人重新引入 PR #128 的 silent failure 反模式。
    """
    source = _MAIN_PY.read_text(encoding="utf-8")
    tree = ast.parse(source)

    lifespan = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "lifespan"
        ),
        None,
    )
    assert lifespan is not None, "lifespan AsyncFunctionDef 在 main.py 未找到"

    for node in ast.walk(lifespan):
        if not isinstance(node, ast.Try):
            continue
        body_src = ast.unparse(node)
        if "payment_event_consumer" not in body_src:
            continue

        for handler in node.handlers:
            # (a) bare `except:`
            if handler.type is None:
                pytest.fail(
                    "lifespan payment_event_consumer 区段含 bare `except:` "
                    "(§14 禁止 + §17 fail-loud 违反)"
                )
            # (b) `except Exception:` 没有 bare re-raise
            if isinstance(handler.type, ast.Name) and handler.type.id == "Exception":
                reraises = any(
                    isinstance(b, ast.Raise) and b.exc is None for b in handler.body
                )
                if not reraises:
                    pytest.fail(
                        "lifespan payment_event_consumer 区段 `except Exception:` "
                        "不重新抛 — §17 Tier 1 fail-loud 违反 (PR #128 silent 回归)"
                    )
