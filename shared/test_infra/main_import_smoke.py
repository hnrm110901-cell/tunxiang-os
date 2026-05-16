"""main.py 容器布局烟测 helper —— 各服务可复用

为什么需要：
  - 服务 production 入口 `services/<svc>/src/main.py` 在 Dockerfile 中通过
    `COPY services/<svc>/src/ ./services/<py_svc>/src/` 重命名（含 dash 的目录变下划线）
  - CMD `uvicorn services.<py_svc>.src.main:app` 直接 import production 路径
  - 本地仓库目录是 `services/<svc>/`（dash），无法直接 `from services.<py_svc>.src import main`
  - 历史上 conftest.py 用 namespace package 魔法在 pytest 中绕开此问题，
    但这不是 production 真实路径 — 容易出现"测试通过但 production main 启动失败"

本 helper 真实模拟 Dockerfile 的 COPY+rename 操作（在 mktemp 临时目录构造容器布局），
然后用 subprocess + PYTHONPATH=tempdir 执行 import — 所看即所得。

**使用：**
```python
from shared.test_infra.main_import_smoke import assert_main_app_imports

def test_main_module_loads_in_container_layout() -> None:
    assert_main_app_imports("tx-org")  # 服务名（dash 形式）
```

**参数：**
- `service`: 仓库下 `services/<service>/src/main.py` 必须存在
- `min_routes`: 期望最少路由数（默认 1）
- `extra_env`: 额外环境变量（如 TX_JWT_SECRET_KEY）

**设计原则：**
- 不依赖 pytest conftest namespace 魔法（那是 test 端 hack，main.py 不该依赖）
- 使用真实容器布局（services/<py_svc>/src 而非 services/<svc>/src）
- subprocess 隔离 sys.modules 污染
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _repo_root() -> Path:
    """返回仓库根（shared/test_infra/main_import_smoke.py 的 parents[2]）。"""
    return Path(__file__).resolve().parents[2]


def assert_main_app_imports(
    service: str,
    *,
    min_routes: int = 1,
    extra_env: dict[str, str] | None = None,
    timeout: int = 30,
    mode: str = "A",
    extra_copies: list[tuple[str, str]] | None = None,
) -> None:
    """验证 services/<service>/src/main.py 在 Docker 容器布局下能干净 import。

    构造步骤（与 services/<svc>/Dockerfile 一致）：
      1. mkdir <tmp>/services/<py_svc>/
      2. cp -r services/<svc>/src <tmp>/services/<py_svc>/
      3. cp -r shared <tmp>/
      4. extra_copies 复刻 Dockerfile cross-service ``COPY``
      5. PYTHONPATH=<tmp> python -c "from services.<py_svc>.src import main; assert main.app"

    任何 main.py 内部 import 失败 / app 不存在 / routes 数 < min_routes → AssertionError。

    **mode 区分两种 Dockerfile 布局** (issue #714 W22 补全):
      - "A" (16 服务): ``COPY services/tx-X/src/ ./services/tx_X/src/`` + ``uvicorn services.tx_X.src.main:app``
      - "B" (2 服务, tx-brain / tx-predict): ``COPY services/tx-X/src/ ./src/`` + ``uvicorn src.main:app``

    **extra_copies** 复刻 Dockerfile cross-service ``COPY`` 指令 (issue #714):
      tx-trade 的 ``COPY services/tx-org/src/services/permission_service.py
      ./services/permission_service.py`` 表达为
      ``[("services/tx-org/src/services/permission_service.py", "services/permission_service.py")]``.
    """
    if mode not in {"A", "B"}:
        raise ValueError(f"mode must be 'A' or 'B', got {mode!r}")
    root = _repo_root()
    py_svc = service.replace("-", "_")
    src_dir = root / "services" / service / "src"
    if not src_dir.exists():
        raise AssertionError(f"services/{service}/src not found")
    if not (src_dir / "main.py").exists():
        raise AssertionError(f"services/{service}/src/main.py not found")

    with tempfile.TemporaryDirectory(prefix=f"smoke-{service}-") as tmp:
        tmp_path = Path(tmp)
        if mode == "A":
            target_svc = tmp_path / "services" / py_svc
            target_svc.mkdir(parents=True)
            shutil.copytree(src_dir, target_svc / "src")
            import_target = f"services.{py_svc}.src"
        else:  # mode B
            shutil.copytree(src_dir, tmp_path / "src")
            import_target = "src"
        shutil.copytree(root / "shared", tmp_path / "shared")

        for src_rel, dst_rel in extra_copies or []:
            src_path = root / src_rel
            if not src_path.exists():
                raise AssertionError(f"extra_copies src missing: {src_path}")
            dst_path = tmp_path / dst_rel
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            if src_path.is_dir():
                shutil.copytree(src_path, dst_path)
            else:
                shutil.copy2(src_path, dst_path)

        code = (
            f"from {import_target} import main as m; "
            f"assert hasattr(m, 'app'), 'no app attribute'; "
            f"assert len(m.app.routes) >= {min_routes}, "
            f"f'routes={{len(m.app.routes)}} < {min_routes}'; "
            f"print(f'OK routes={{len(m.app.routes)}}')"
        )
        env = {
            **os.environ,
            "PYTHONPATH": str(tmp_path),
        }
        if extra_env:
            env.update(extra_env)

        r = subprocess.run(  # noqa: S603 — 固定 subprocess，无注入风险
            [sys.executable, "-c", code],
            cwd=str(tmp_path),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if r.returncode != 0:
            # 缺第三方依赖（如 apscheduler/redis/anthropic）→ skip 而非 fail
            # 本地 dev venv 缺服务级 requirements.txt 依赖时不应阻塞 smoke 网
            # CI 矩阵会装齐，那里失败才是真问题
            stderr = r.stderr
            third_party_missing = _detect_missing_third_party(stderr)
            if third_party_missing:
                import pytest

                pytest.skip(
                    f"smoke skip: 第三方依赖 {third_party_missing!r} 缺失（dev venv 局限）"
                    f"；CI 矩阵装齐 requirements.txt 后会真跑"
                )
            raise AssertionError(
                f"main.py 容器布局 import 失败：\n"
                f"  service={service}, py_svc={py_svc}\n"
                f"  stderr={stderr.strip()}\n"
                f"  stdout={r.stdout.strip()}"
            )


def _detect_missing_third_party(stderr: str) -> str | None:
    """从 stderr 提取缺失的第三方依赖名（区分代码 bug vs 环境缺包）。

    返回包名（如 'apscheduler'）或 None（若是代码 bug 如 'api' / 'services.X'）。
    """
    import re

    # ModuleNotFoundError: No module named 'X'
    m = re.search(r"No module named '([^']+)'", stderr)
    if not m:
        return None
    name = m.group(1).split(".", 1)[0]
    # 仓库内模块（services / shared / api / models / repositories / 已知本地模块）= 代码 bug
    repo_modules = {"services", "shared", "api", "models", "repositories", "edge", "scripts"}
    if name in repo_modules:
        return None
    return name
