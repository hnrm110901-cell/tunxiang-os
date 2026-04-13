"""网关应用可导入性回归：防止再次出现双 FastAPI 实例、死 middleware 文件等问题。

与 Dockerfile 一致：`uvicorn services.gateway.src.main:app`，需仓库根在 PYTHONPATH 上，
使用包导入 `services.gateway.src.main`（相对导入才能解析）。
"""
from __future__ import annotations

import sys
from pathlib import Path


def _repo_root() -> Path:
    # .../services/gateway/src/tests/this_file.py -> parents[4] = 仓库根
    return Path(__file__).resolve().parents[4]


def test_main_module_loads_single_fastapi_app() -> None:
    root = _repo_root()
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    from services.gateway.src import main as gateway_main

    assert gateway_main.app.title == "TunxiangOS Gateway"
    assert gateway_main.app.version == "3.0.0"
    assert len(gateway_main.app.routes) > 0
    assert len(gateway_main.app.user_middleware) >= 1
