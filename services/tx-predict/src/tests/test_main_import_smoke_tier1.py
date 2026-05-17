"""Tier 1 — tx-predict main.py 容器布局 import 烟测 (issue #714 W22 补全 PR #351 漏 5 服务)。

Dockerfile CMD: ``uvicorn src.main:app`` (mode B 非标准布局, COPY services/tx-predict/src/ → ./src/).

mode="B" 由 helper 在 issue #714 PR 中加入支持 (复刻同模式的 tx-brain 处理).
"""

from __future__ import annotations

from shared.test_infra.main_import_smoke import assert_main_app_imports


def test_main_module_loads_in_container_layout() -> None:
    """tx_predict main.py 必须在 Docker 容器布局下干净 import (mode B)."""
    assert_main_app_imports(
        "tx-predict",
        mode="B",
        extra_env={
            "TX_JWT_SECRET_KEY": "pytest-smoke-jwt-min-32-chars-padded!",
            "TX_MFA_ENCRYPT_KEY": "00" * 32,
        },
    )
