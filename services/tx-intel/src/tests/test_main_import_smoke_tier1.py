"""Tier 1 — tx-intel main.py 容器布局 import 烟测

防止 production main.py 启动失败的回归门禁。复用 shared/test_infra/main_import_smoke.py
helper（构造 mktemp 容器布局 + subprocess 隔离）。

为什么 Tier 1：services/tx-intel/src/main.py 是 production 入口
（Dockerfile CMD: uvicorn services.tx_intel.src.main:app），main.py import 失败 = 服务无法启动。
本烟测捕捉所有 main.py 内 absolute import 解析问题（容器路径 PYTHONPATH=/app 真实模拟）。

**当前 xfail**：本服务 main.py 在容器布局下存在已知 import 失败
（root cause: bare-import-services.calendar_signal）。决策 77 production 端 codemod / 缺失导出修复后
应翻 xfail（删 marker）— 本烟测立网正是为此提供门禁。
"""

from __future__ import annotations

import pytest

from shared.test_infra.main_import_smoke import assert_main_app_imports


@pytest.mark.xfail(
    reason="bare-import-services.calendar_signal；决策 77 production 端 codemod 修复后翻 xfail",
    strict=False,
)
def test_main_module_loads_in_container_layout() -> None:
    """tx_intel main.py 必须在 Docker 容器布局下干净 import。"""
    assert_main_app_imports(
        "tx-intel",
        extra_env={
            "TX_JWT_SECRET_KEY": "pytest-smoke-jwt-min-32-chars-padded!",
            "TX_MFA_ENCRYPT_KEY": "00" * 32,
        },
    )
