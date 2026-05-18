"""tx-pay /metrics 鉴权 + setup_metrics 挂载冒烟测试 [Tier1 邻接]

#847 (post-SPLIT from #845) — tx-pay 是 §17 Tier 1 资金路径首次公开 /metrics, 必须:
  1. 通过 `shared.observability.setup_metrics` helper 挂载 Instrumentator
     (helper 已设 excluded_handlers=["/metrics"] + include_in_schema=False,
      避免 /metrics 自身计入 metric / 不入 OpenAPI 公开 schema)
  2. 挂载 `MetricsAuthMiddleware` (issue #825): /metrics Bearer + IP allowlist
     fail-loud 契约 (PROD 环境 token 缺/短直接 RuntimeError 拒启动)

此测试用 grep-verify 源码 literal 出现, 不依赖运行时（避免 lifespan 初始化真实
支付渠道副作用），等价于 import smoke 的最小子集。
"""

from __future__ import annotations

from pathlib import Path


def _read_main_py() -> str:
    main_path = Path(__file__).resolve().parents[1] / "src" / "main.py"
    assert main_path.exists(), f"tx-pay main.py 不存在: {main_path}"
    return main_path.read_text(encoding="utf-8")


def test_setup_metrics_mounted() -> None:
    """tx-pay main.py 必须用 setup_metrics helper 挂 Prometheus (不用 raw Instrumentator)."""
    source = _read_main_py()
    assert "from shared.observability import setup_metrics" in source, (
        "缺 shared.observability.setup_metrics import (gateway 试点对齐, "
        "避免制造第 17 个 raw Instrumentator 用户后立刻 #820-I 迁移)"
    )
    assert 'setup_metrics(app, service_name="tx-pay")' in source, (
        "缺 setup_metrics(app, service_name=\"tx-pay\") 调用 — "
        "helper 已设 excluded_handlers=[\"/metrics\"] + include_in_schema=False"
    )


def test_metrics_auth_middleware_mounted() -> None:
    """tx-pay 无 AuthMiddleware (gateway 反代后内网调用), /metrics 必须配 MetricsAuthMiddleware."""
    source = _read_main_py()
    assert "from shared.middleware.src.metrics_auth import MetricsAuthMiddleware" in source, (
        "缺 MetricsAuthMiddleware import (issue #825 — /metrics Bearer + IP allowlist)"
    )
    assert "app.add_middleware(MetricsAuthMiddleware)" in source, (
        "缺 app.add_middleware(MetricsAuthMiddleware) — Tier 1 资金路径不可裸暴露 /metrics"
    )
