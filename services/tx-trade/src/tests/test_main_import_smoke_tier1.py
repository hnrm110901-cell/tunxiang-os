"""Tier 1 — tx-trade main.py 容器布局 import 烟测

防止 production main.py 启动失败的回归门禁。复用 shared/test_infra/main_import_smoke.py
helper（构造 mktemp 容器布局 + subprocess 隔离）。

为什么 Tier 1：services/tx-trade/src/main.py 是 production 入口
（Dockerfile CMD: uvicorn services.tx_trade.src.main:app），main.py import 失败 = 服务无法启动。
本烟测捕捉所有 main.py 内 absolute import 解析问题（容器路径 PYTHONPATH=/app 真实模拟）。

Dockerfile cross-service COPY (issue #714 PR-A 加 extra_copies 复刻 PR #351 时漏的部分):
  COPY services/tx-org/src/services/permission_service.py ./services/permission_service.py

PR #351 立网时 xfail 标 "bare-import-services.permission_service" — 实际是 helper 没
复刻 Dockerfile 的 cross-service COPY (这不是 main.py bug). issue #714 PR-A 给 helper 加
``extra_copies`` 参数 + 本 wrapper 显式传 → false-positive xfail 移除。
"""

from __future__ import annotations

from shared.test_infra.main_import_smoke import assert_main_app_imports


def test_main_module_loads_in_container_layout() -> None:
    """tx_trade main.py 必须在 Docker 容器布局下干净 import (含 cross-service COPY)."""
    assert_main_app_imports(
        "tx-trade",
        extra_copies=[
            (
                "services/tx-org/src/services/permission_service.py",
                "services/permission_service.py",
            ),
        ],
        extra_env={
            "TX_JWT_SECRET_KEY": "pytest-smoke-jwt-min-32-chars-padded!",
            "TX_MFA_ENCRYPT_KEY": "00" * 32,
        },
    )
