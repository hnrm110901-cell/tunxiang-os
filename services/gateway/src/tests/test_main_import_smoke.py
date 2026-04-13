"""网关应用可导入性回归：防止再次出现双 FastAPI 实例、死 middleware 文件等问题。

与 Dockerfile 一致：`uvicorn services.gateway.src.main:app`。

注意：pytest 常设 `PYTHONPATH=src:../../`，此时 `src` 在路径最前，`import services` 会先命中
`gateway/src/services/`（本服务子包），与仓库根的 `services/` 命名冲突。故用子进程、仅将
仓库根加入 PYTHONPATH，做干净导入。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    # .../services/gateway/src/tests/this_file.py -> parents[4] = 仓库根
    return Path(__file__).resolve().parents[4]


def test_main_module_loads_single_fastapi_app() -> None:
    root = _repo_root()
    code = (
        "from services.gateway.src import main as m; "
        "assert m.app.title == 'TunxiangOS Gateway'; "
        "assert m.app.version == '3.0.0'; "
        "assert len(m.app.routes) > 0; "
        "assert len(m.app.user_middleware) >= 1"
    )
    # 避免 import 时 JWT/MFA 走「未设置密钥」分支刷屏（仅烟测，非生产值）
    env = {
        **os.environ,
        "PYTHONPATH": str(root),
        "TX_JWT_SECRET_KEY": "pytest-smoke-gateway-jwt-secret-min-32-chars!",
        "TX_MFA_ENCRYPT_KEY": "00" * 32,  # 64 hex = 32 字节，满足 MFA XOR 密钥
    }
    r = subprocess.run(  # noqa: S603 — 固定脚本，用于隔离 sys.path 上的 services 命名冲突
        [sys.executable, "-c", code],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, f"stderr={r.stderr!r} stdout={r.stdout!r}"
