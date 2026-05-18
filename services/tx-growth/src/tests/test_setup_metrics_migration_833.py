"""#833 Lane A — tx-growth setup_metrics helper 迁移烟测

验证 main.py 已替换 Instrumentator 直调为 shared.observability.setup_metrics helper,
确认 MetricsAuthMiddleware 鉴权层保留 (issue #829 决策矩阵分母).

per feedback_helper_only_test_for_import_blocked_module: 直接 grep source literal,
不走 importlib/DB 黑魔法 — 简单可靠.
"""

from __future__ import annotations

import pathlib

MAIN_PY = pathlib.Path(__file__).parents[1] / "main.py"


def _source() -> str:
    return MAIN_PY.read_text(encoding="utf-8")


def test_setup_metrics_helper_used() -> None:
    """main.py 必须调用 setup_metrics(app, service_name="tx-growth")."""
    src = _source()
    assert 'setup_metrics(app, service_name="tx-growth")' in src, (
        "tx-growth/main.py 未调用 setup_metrics helper (#833 Lane A 迁移未完成)"
    )


def test_observability_import_present() -> None:
    """main.py 顶部 import 必须含 from shared.observability import setup_metrics."""
    src = _source()
    assert "from shared.observability import setup_metrics" in src, (
        "tx-growth/main.py 缺少 shared.observability setup_metrics import"
    )


def test_raw_instrumentator_removed() -> None:
    """main.py 不应再有裸 Instrumentator().instrument(app).expose(app) 调用."""
    src = _source()
    assert "Instrumentator().instrument(app).expose(app)" not in src, (
        "tx-growth/main.py 仍含裸 Instrumentator 调用 — 迁移未完成"
    )


def test_metrics_auth_middleware_retained() -> None:
    """/metrics Bearer 鉴权层必须保留 (issue #829 决策矩阵分母)."""
    src = _source()
    assert "app.add_middleware(MetricsAuthMiddleware)" in src, (
        "tx-growth/main.py 丢失 MetricsAuthMiddleware mount — 鉴权层被意外移除"
    )
