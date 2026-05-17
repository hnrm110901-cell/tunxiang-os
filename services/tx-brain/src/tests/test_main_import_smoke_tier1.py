"""Tier 1 — tx-brain main.py 容器布局 import 烟测

防止 production main.py 启动失败的回归门禁。复用 shared/test_infra/main_import_smoke.py
helper（构造 mktemp 容器布局 + subprocess 隔离）。

为什么 Tier 1：services/tx-brain/src/main.py 是 production 入口，main.py import 失败 = 服务无法启动。
本烟测捕捉所有 main.py 内 absolute import 解析问题（容器路径 PYTHONPATH=/app 真实模拟）。

Dockerfile mode B (非标准容器布局):
  COPY services/tx-brain/src/ ./src/   （而非 ./services/tx_brain/src/）
  CMD uvicorn src.main:app             （而非 services.tx_brain.src.main:app）

helper ``mode="B"`` 由 issue #714 PR 引入, 复刻 tx-brain 的非标 layout (PR #351 当时
留 skip 等 helper 二次设计补)。
"""

from __future__ import annotations

from shared.test_infra.main_import_smoke import assert_main_app_imports


def test_main_module_loads_in_container_layout() -> None:
    """tx_brain main.py 必须在 Docker 容器布局下干净 import (mode B)."""
    assert_main_app_imports(
        "tx-brain",
        mode="B",
        extra_env={
            "TX_JWT_SECRET_KEY": "pytest-smoke-jwt-min-32-chars-padded!",
            "TX_MFA_ENCRYPT_KEY": "00" * 32,
        },
    )
