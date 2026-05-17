"""Tier 1 — tx-forge main.py 容器布局 import 烟测 (issue #714 W22 补全 PR #351 漏 5 服务)。

Dockerfile CMD: ``uvicorn services.tx_forge.src.main:app`` (mode A 标准布局).
"""

from __future__ import annotations

from shared.test_infra.main_import_smoke import assert_main_app_imports


def test_main_module_loads_in_container_layout() -> None:
    """tx_forge main.py 必须在 Docker 容器布局下干净 import."""
    assert_main_app_imports(
        "tx-forge",
        extra_env={
            "TX_JWT_SECRET_KEY": "pytest-smoke-jwt-min-32-chars-padded!",
            "TX_MFA_ENCRYPT_KEY": "00" * 32,
        },
    )
