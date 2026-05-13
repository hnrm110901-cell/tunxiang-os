"""Tier 1 — payment_event_consumer 启动 fail-loud 测试（W1-T1）

资金链路 (CLAUDE.md §17)：tx-pay → tx-trade 支付事件消费者启动失败时，tx-trade
lifespan 必须 fail-loud — 让 k8s readiness probe 直接拒绝服务上线，而非以
"无支付事件消费"的残废状态启动。

历史背景：`fd94028e feat(payment+rls): 支付事件消费者...` (PR #128) 引入
broad `except Exception: warning(...)` 静吞，导致 redis 不可达 / topic 配置错
等 boot 失败时 tx-trade 仍能起来，订单永远 stuck 在 paying — 这是 P0 资金风险。

测试契约（W1-T1 round-1 / round-2 review 后扩展）：
  T1. consumer.create 抛 → helper 重新抛（不静吞）+ register_background_task 未被调用
  T2. consumer.start  抛 → helper 重新抛（不静吞）+ register_background_task 未被调用
  T3. 正常路径：consumer 启动成功 → register_background_task 被调用 → 返回 task
  T4. AST 守护：main.py lifespan 不再有 broad `except Exception:` 静吞
       payment_event_consumer 块（防止回归 PR #128 反模式）
  T5. AST 守护（round-1 P0 修补）：tuple 形式 `except (Exception, ...):` 等价
       broad except，必须同样禁止（防止 reviewer 指出的绕过路径）
  T6. AST 守护（round-2 outside-diff #1 修补）：start_payment_event_consumer_or_raise
       调用必须在 try 块体内、且同一 try 的 finally 子句含 audit_outbox_flusher_stop
       清理 — 闭合 round-1 P1 "任意终止路径均 stop + flush" 契约的姊妹漏洞
       （若 await 在 try 之外，raise 路径下 finally 不跑 → audit cleanup 被跳过）
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

    registered: list = []
    with pytest.raises(_BootError, match="redis stream not reachable"):
        await lc.start_payment_event_consumer_or_raise(
            session_factory=MagicMock(),
            register_background_task=lambda t: registered.append(t) or t,
        )

    # round-1 reviewer 遗漏覆盖 #2：raise 路径下 register 必须不被调用
    assert registered == []


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

    registered: list = []
    with pytest.raises(_StartError, match="xreadgroup error"):
        await lc.start_payment_event_consumer_or_raise(
            session_factory=MagicMock(),
            register_background_task=lambda t: registered.append(t) or t,
        )

    # round-1 reviewer 遗漏覆盖 #2：raise 路径下 register 必须不被调用
    assert registered == []


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


# ─── T4 / T5: 源码守护 — main.py lifespan 不再静吞 ───────────


def _exception_handler_is_broad(handler_type: ast.expr | None) -> bool:
    """判断 except 子句类型是否为"宽泛捕获" (broad catch)。

    覆盖：
      - bare `except:`                      → handler_type is None
      - `except Exception:`                 → ast.Name(id='Exception')
      - `except (Exception, asyncio...):`   → ast.Tuple(elts=[...])
        其中 elts 含 `Exception` Name（reviewer round-1 P0 绕过路径）

    BaseException 同理（更宽），但 lifespan 应几乎不该用，本守护也覆盖。
    """
    if handler_type is None:
        return True

    if isinstance(handler_type, ast.Name) and handler_type.id in {
        "Exception",
        "BaseException",
    }:
        return True

    if isinstance(handler_type, ast.Tuple):
        for elt in handler_type.elts:
            if isinstance(elt, ast.Name) and elt.id in {"Exception", "BaseException"}:
                return True

    return False


def _lifespan_try_blocks_around_payment_event_consumer() -> list[ast.Try]:
    """返回 lifespan 函数中 body 提及 payment_event_consumer 的所有 Try 节点。"""
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

    result: list[ast.Try] = []
    for node in ast.walk(lifespan):
        if not isinstance(node, ast.Try):
            continue
        if "payment_event_consumer" in ast.unparse(node):
            result.append(node)
    return result


def test_lifespan_payment_event_consumer_no_silent_except():
    """CLAUDE.md §14（禁 broad except）+ §17（Tier 1 fail-loud）联合源码锁。

    lifespan() 中 payment_event_consumer 调用区段，不得存在 broad except 静吞：
      (a) bare `except:`
      (b) `except Exception:` / `except BaseException:` 无 bare-re-raise
      (c) `except (Exception, ...):` tuple 形式 同 (b)，无 bare-re-raise
          ← round-1 reviewer P0 修补：原版本只查 ast.Name，tuple 形式绕过

    回归防护 — 防止后人重新引入 PR #128 的 silent failure 反模式。
    """
    for node in _lifespan_try_blocks_around_payment_event_consumer():
        for handler in node.handlers:
            if not _exception_handler_is_broad(handler.type):
                continue
            reraises = any(
                isinstance(b, ast.Raise) and b.exc is None for b in handler.body
            )
            if reraises:
                continue
            # broad + 不重抛 → fail
            tname = (
                "bare except"
                if handler.type is None
                else ast.unparse(handler.type)
            )
            pytest.fail(
                f"lifespan payment_event_consumer 区段含 broad except `{tname}:` "
                "且不重新抛 — §14 禁 broad except + §17 Tier 1 fail-loud 违反 "
                "(PR #128 silent 回归)"
            )


def test_ast_guard_detects_tuple_broad_except_round1_bypass():
    """round-1 reviewer P0 修补的回归测试：构造 tuple 形式 broad except 字符串，
    用相同 helper 验证能被识别为"宽泛捕获" — 防止后续误改 helper 又回到只查
    ast.Name 的盲区。

    本测不读 main.py（不假设它含 tuple except），而是直接喂样本字符串给 helper。
    """
    # (c) `except (Exception, ValueError):` — 含 Exception 的 tuple
    tuple_with_exception = ast.parse(
        "try:\n    pass\nexcept (Exception, ValueError):\n    pass"
    ).body[0].handlers[0].type
    assert _exception_handler_is_broad(tuple_with_exception), \
        "T5 P0：含 Exception 的 tuple except 必须识别为 broad"

    # 反例：narrow tuple 不应误判
    narrow_tuple = ast.parse(
        "try:\n    pass\nexcept (ValueError, KeyError):\n    pass"
    ).body[0].handlers[0].type
    assert not _exception_handler_is_broad(narrow_tuple), \
        "T5 反例：纯 narrow tuple 不应误判为 broad"

    # bare except
    bare = ast.parse(
        "try:\n    pass\nexcept:\n    pass"
    ).body[0].handlers[0].type
    assert _exception_handler_is_broad(bare), "T5 bare except 必须识别为 broad"

    # except Exception:
    name_exc = ast.parse(
        "try:\n    pass\nexcept Exception:\n    pass"
    ).body[0].handlers[0].type
    assert _exception_handler_is_broad(name_exc), "T5 Name Exception 必须识别为 broad"

    # narrow
    narrow = ast.parse(
        "try:\n    pass\nexcept ValueError:\n    pass"
    ).body[0].handlers[0].type
    assert not _exception_handler_is_broad(narrow), "T5 narrow Name 不应误判为 broad"


# ─── T6: 源码守护 — start await 在 try 块内 + audit cleanup 在 finally ──


def test_lifespan_start_consumer_in_try_block_with_audit_cleanup_in_finally():
    """round-2 reviewer (CodeRabbit) outside-diff #1 修补的源码契约锁。

    round-1 P1 修补承诺"任意终止路径均 stop + flush audit outbox"，但若
    `start_payment_event_consumer_or_raise` 在 try 块之外调用，其 raise 路径
    不会触发 finally → audit_outbox_flusher_stop.set() 被跳过（契约姊妹漏洞）。

    本测锁两条契约：
      (a) `start_payment_event_consumer_or_raise` 调用必须在 try 块体内
      (b) 同一 try 的 finalbody 含 `audit_outbox_flusher_stop` + `.set(`
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

    candidate_try: ast.Try | None = None
    for node in ast.walk(lifespan):
        if not isinstance(node, ast.Try):
            continue
        body_text = "\n".join(ast.unparse(b) for b in node.body)
        if "start_payment_event_consumer_or_raise" in body_text:
            candidate_try = node
            break

    assert candidate_try is not None, (
        "T6 (a)：start_payment_event_consumer_or_raise 调用必须在 try 块体内，"
        "保证其 raise 路径下 finally 仍跑 → audit_outbox_flusher_stop 被 set "
        "(round-2 CodeRabbit outside-diff #1 修补)"
    )

    finally_text = "\n".join(ast.unparse(b) for b in candidate_try.finalbody)
    assert "audit_outbox_flusher_stop" in finally_text, (
        "T6 (b)：audit_outbox_flusher_stop 清理必须在 start_payment_event_consumer "
        "所在 try 块的 finally 子句内（任意终止路径均 stop + flush 契约）"
    )
    assert ".set(" in finally_text, (
        "T6 (c)：finally 子句必须显式调用 audit_outbox_flusher_stop.set() "
        "触发 flusher 退出循环"
    )
