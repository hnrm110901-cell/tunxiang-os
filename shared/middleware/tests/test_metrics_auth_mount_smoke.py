"""Smoke test: 验证 PR #829 (post-SPLIT) 12 svc main.py 已挂载 MetricsAuthMiddleware.

参考 §19 round-1 code reviewer P1-2 + memory feedback_tx_supply_main_import_ci_smoke_gap:
真 import 在 CI Tier 1 最小依赖集 + Python 3.9 type-hint 等 pre-existing
service-side 问题下不可靠. 用 grep verify 模式 (per
feedback_helper_only_test_for_import_blocked_module): 验证每 svc main.py
literal 包含 `MetricsAuthMiddleware` import 与 `app.add_middleware(MetricsAuthMiddleware)`
mount 调用即可.

tx-pay 不在列表: SPLIT 到 #847 (Tier 1 资金路径, §19 security 重审).
"""

from __future__ import annotations

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

# 12 svc (post-SPLIT, tx-pay 移除到 #847)
SERVICES_WITH_METRICS_AUTH = [
    "tx-agent",
    "tx-analytics",
    "tx-civic",
    "tx-devforge",
    "tx-expense",
    "tx-finance",
    "tx-growth",
    "tx-member",
    "tx-menu",
    "tx-ops",
    "tx-org",
    "tx-supply",
]


@pytest.mark.parametrize("svc", SERVICES_WITH_METRICS_AUTH)
def test_main_mounts_metrics_auth(svc: str) -> None:
    """每个 svc 的 main.py 必须 import 并 mount MetricsAuthMiddleware."""
    main_py = REPO_ROOT / "services" / svc / "src" / "main.py"
    assert main_py.exists(), f"{svc}/src/main.py 不存在"
    content = main_py.read_text(encoding="utf-8")
    assert "MetricsAuthMiddleware" in content, (
        f"{svc}/src/main.py 未 import MetricsAuthMiddleware"
    )
    assert "app.add_middleware(MetricsAuthMiddleware)" in content, (
        f"{svc}/src/main.py 未调用 app.add_middleware(MetricsAuthMiddleware)"
    )


def test_tx_pay_does_not_mount_metrics_auth() -> None:
    """tx-pay SPLIT 到 #847; 本 PR 不应触碰 tx-pay/src/main.py."""
    main_py = REPO_ROOT / "services" / "tx-pay" / "src" / "main.py"
    assert main_py.exists()
    content = main_py.read_text(encoding="utf-8")
    assert "MetricsAuthMiddleware" not in content, (
        "tx-pay 已挂 MetricsAuthMiddleware; 本 PR SPLIT 后 tx-pay 应保持 origin/main 状态, "
        "改动归到 #847 (Tier 1 资金路径)"
    )
