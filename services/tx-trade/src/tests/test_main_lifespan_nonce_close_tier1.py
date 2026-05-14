"""Tier 1 — main.py lifespan EdgeSyncNonceStore warmup + close 源码守护

PR #618 实现（PR #609 §19 round-1 P2 follow-up — issues #610 + #611）：
  - startup: `get_nonce_store()` 工厂预热 — fail-fast on Redis URL missing in prod
    (EDGE_SYNC_HMAC_REQUIRED=true + InProcess 不允许时 → RuntimeError)
  - shutdown: `await get_nonce_store().close()` — graceful Redis pool release
    (避免 k8s rolling update 高频部署累积 maxclients 耗尽)

本测覆盖 PR #609 §19 round-1 E 项 P2 建议：
  T1. AST 守护 — startup 段 (yield 前) 含 `get_nonce_store()` warmup 调用
  T2. AST 守护 — shutdown 段 (yield 后) 含 `await get_nonce_store().close()` 调用
  T3. AST 守护 — close() 必须包在 try/except 内不向 SIGTERM 传播
       (graceful shutdown 优先 audit/payment 关键路径，与 §17 fail-loud 规则
        互补 — close 失败不应触发 k8s SIGKILL 跳过其他 cleanup hooks)

回归防护 — 防止 lifespan 重构时漏掉这两个 hook：
  - 漏 warmup → 生产 EDGE_SYNC_HMAC_REQUIRED=true 时错误延迟到首请求 503 才暴露
  - 漏 close → k8s rolling update 累积耗尽 Redis maxclients

模式参考：`test_lifespan_payment_consumer_tier1.py`（PR #128 silent failure 同模式守护）。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

# ─── 路径锚点 ────────────────────────────────────────────────
_MAIN_PY = Path(__file__).resolve().parents[1] / "main.py"


def _lifespan_node() -> ast.AsyncFunctionDef:
    """提取 main.py lifespan() AsyncFunctionDef 节点。"""
    source = _MAIN_PY.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for n in ast.walk(tree):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "lifespan":
            return n
    pytest.fail("lifespan() AsyncFunctionDef 在 main.py 未找到")


def _lifespan_source() -> str:
    """ast.unparse(lifespan) — 保证 yield 前后切分只针对 lifespan 函数体内的 yield。"""
    return ast.unparse(_lifespan_node())


def _split_around_first_yield(src: str) -> tuple[str, str]:
    """把 lifespan 源代码按第一个 `yield` 关键字切两段（startup / shutdown）。

    用 `\\byield\\b` word-boundary 避免误匹配 'yields'/'yielded' 等子串。
    """
    parts = re.split(r"\byield\b", src, maxsplit=1)
    assert len(parts) == 2, "lifespan 必须含 yield（FastAPI lifespan 契约）"
    return parts[0], parts[1]


# ─── T1: startup warmup ─────────────────────────────────────


def test_lifespan_has_get_nonce_store_warmup_in_startup():
    """T1: startup 段 (yield 前) 必须含 `get_nonce_store()` warmup 调用。

    匹配 `get_nonce_store(...)` 但**排除** `get_nonce_store().close()` 形式
    （后者属 shutdown 范畴）。

    生产 EDGE_SYNC_HMAC_REQUIRED=true 缺 Redis URL 时，warmup 立即 RuntimeError
    → k8s readiness probe 失败拒绝服务上线；不预热则错误延迟到首次 edge sync
    请求 503 才暴露 (issue #610 实现合约)。
    """
    startup, _ = _split_around_first_yield(_lifespan_source())
    # 匹配 get_nonce_store(任意参数) 但排除紧跟 .close 的形式
    matches = re.findall(r"get_nonce_store\s*\([^)]*\)(?!\s*\.close)", startup)
    assert len(matches) >= 1, (
        "T1: lifespan startup 段必须含 `get_nonce_store()` warmup 调用 "
        "(PR #618 / issue #610 实现合约)。生产 EDGE_SYNC_HMAC_REQUIRED=true "
        "缺 Redis URL 时 fail-fast (k8s readiness 失败) 而非延迟到首请求 503。"
    )


# ─── T2: shutdown close ─────────────────────────────────────


def test_lifespan_has_get_nonce_store_close_in_shutdown():
    """T2: shutdown 段 (yield 后) 必须含 `await get_nonce_store().close()` 调用。

    K8s rolling update 高频部署时累积可能耗尽 Redis maxclients (issue #611)。
    InProcessNonceStore.close() 是 no-op，所以不分 prod/dev 一律调用。
    """
    _, shutdown = _split_around_first_yield(_lifespan_source())
    # 严格匹配 get_nonce_store().close() 调用形态
    assert re.search(r"get_nonce_store\s*\(\s*\)\s*\.close\s*\(\s*\)", shutdown), (
        "T2: lifespan shutdown 段必须含 `get_nonce_store().close()` 调用 "
        "(PR #618 / issue #611 实现合约)。K8s rolling update 高频部署时累积 "
        "Redis 连接耗尽 maxclients。"
    )


# ─── T3: close 包在 try/except 不传播 ───────────────────────


def test_lifespan_close_wrapped_in_try_except_no_propagation():
    """T3: `get_nonce_store().close()` 必须包在 try/except 内不向 SIGTERM 传播。

    graceful shutdown 优先 audit/payment 关键路径 — close 失败不应阻塞 SIGTERM
    导致 k8s force-kill 触发 SIGKILL（跳过其他 cleanup hooks 如 audit outbox flush）。

    与 §17 Tier 1 fail-loud 规则互补：startup fail-loud（让 readiness 失败），
    shutdown fail-graceful（确保其他 cleanup 跑完）。
    """
    lifespan = _lifespan_node()

    # 找含 get_nonce_store().close() 的 Try 节点
    found_in_try: ast.Try | None = None
    for node in ast.walk(lifespan):
        if not isinstance(node, ast.Try):
            continue
        body_src = "\n".join(ast.unparse(s) for s in node.body)
        if re.search(r"get_nonce_store\s*\(\s*\)\s*\.close\s*\(\s*\)", body_src):
            found_in_try = node
            break

    assert found_in_try is not None, (
        "T3 (a): get_nonce_store().close() 必须在 try 块体内 — 不向 SIGTERM "
        "传播保证 graceful shutdown 优先 audit/payment 清理路径。"
    )

    # except 子句必须存在 (graceful — 任意异常都吞掉)
    assert len(found_in_try.handlers) > 0, (
        "T3 (b): close() 所在 try 必须有至少一个 except handler — bare try "
        "(无 except / 无 finally) 不闭合 graceful shutdown 契约。"
    )
