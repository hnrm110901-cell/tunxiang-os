"""Tier 1 — tx-brain main.py 容器布局 import 烟测

防止 production main.py 启动失败的回归门禁。复用 shared/test_infra/main_import_smoke.py
helper（构造 mktemp 容器布局 + subprocess 隔离）。

为什么 Tier 1：services/tx-brain/src/main.py 是 production 入口，main.py import 失败 = 服务无法启动。
本烟测捕捉所有 main.py 内 absolute import 解析问题（容器路径 PYTHONPATH=/app 真实模拟）。

**当前 skip**：tx-brain Dockerfile 使用**非标准容器布局**——
  COPY services/tx-brain/src/ ./src/   （而非 ./services/tx_brain/src/）
  CMD uvicorn src.main:app             （而非 services.tx_brain.src.main:app）

其他 13 个服务全部使用 `services.<py_svc>.src.main:app` 标准 layout，helper
`assert_main_app_imports("tx-brain")` 假设此 layout — 与 tx-brain production 实际
路径不一致。简单跑会"虚假通过"（subprocess 因找不到 `services.tx_brain.src` 而 fail，
helper 误判为缺第三方包触发 skip）。

正确路径：先将 tx-brain Dockerfile / CMD 改为标准 layout，再删本 skip。
或：扩展 helper 支持 `module_path` 参数覆盖 — 但属 helper 二次设计，超出本 PR scope。

跟踪：tx-brain Dockerfile 非标准 layout 统一化 — 独立 follow-up。
"""

from __future__ import annotations

import pytest

from shared.test_infra.main_import_smoke import assert_main_app_imports  # noqa: F401


@pytest.mark.skip(
    reason="tx-brain Dockerfile 非标准 layout (`src.main:app`)；helper 假设 "
    "`services.<py_svc>.src.main:app` 标准布局。统一化 Dockerfile 后翻 skip。"
)
def test_main_module_loads_in_container_layout() -> None:
    """tx_brain main.py 必须在 Docker 容器布局下干净 import。"""
    assert_main_app_imports(
        "tx-brain",
        extra_env={
            "TX_JWT_SECRET_KEY": "pytest-smoke-jwt-min-32-chars-padded!",
            "TX_MFA_ENCRYPT_KEY": "00" * 32,
        },
    )
