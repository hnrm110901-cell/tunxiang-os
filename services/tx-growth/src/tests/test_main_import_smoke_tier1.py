"""Tier 1 — tx-growth main.py 容器布局 import 烟测

防止 production main.py 启动失败的回归门禁。复用 shared/test_infra/main_import_smoke.py
helper（构造 mktemp 容器布局 + subprocess 隔离）。

为什么 Tier 1：services/tx-growth/src/main.py 是 production 入口
（Dockerfile CMD: uvicorn services.tx_growth.src.main:app），main.py import 失败 = 服务无法启动。
本烟测捕捉所有 main.py 内 absolute import 解析问题（容器路径 PYTHONPATH=/app 真实模拟）。
"""

from __future__ import annotations

from shared.test_infra.main_import_smoke import assert_main_app_imports


def test_main_module_loads_in_container_layout() -> None:
    """tx_growth main.py 必须在 Docker 容器布局下干净 import。"""
    assert_main_app_imports(
        "tx-growth",
        extra_env={
            "TX_JWT_SECRET_KEY": "pytest-smoke-jwt-min-32-chars-padded!",
            "TX_MFA_ENCRYPT_KEY": "00" * 32,
        },
    )
