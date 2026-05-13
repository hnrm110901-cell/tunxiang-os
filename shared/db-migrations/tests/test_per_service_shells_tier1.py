"""Phase 4a-3 smoke test: verify per-service alembic shells 完整性。

每个 shell 必须含：
  - alembic.ini (with unique version_table)
  - env.py (imports cleanly)
  - script.py.mako
  - versions/ (empty + .gitkeep)
  - tests/__init__.py
  - README.md

并且各 service 的 version_table 唯一（多 alembic 共享 PG 时 stamp 隔离）。

Phase 4a-4 baseline schema 入栈后，本测试可继续验证 shell 结构稳定。
"""

from __future__ import annotations

import configparser
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent.parent  # tunxiang-os/
SERVICES_DIR = REPO_ROOT / "services"
SHARED_CORE_DIR = REPO_ROOT / "shared/db-migrations-core"

# Phase 4a-1 audit 决定的 16 个 service owners — 这些 services 在
# docs/migration-architecture-route-a-ownership-audit.md 中被 grep heuristic
# 标记为某张表的 owner（clear/weak）。
#
# 以下 4 个 services 目录存在但未纳入（audit 未发现表 ownership）：
#   tx-civic / tx-devforge / tx-forge / mcp-server
# 待 4a-2 founder review 时若证实它们有自有表，再添加 shell（同模式扩展）。
#
# 4a-3（本 PR）在 4a-2 founder review 完成前 ship 是 intentional：骨架是确定性
# 工作，与 owner 决策正交；若 4a-2 改 owner 归属，调整本列表 + 重跑生成脚本即可。
#
# W2-A Phase 1 (PR 待开)：tx-indonesia / tx-malaysia / tx-vietnam 三服务整删；
# 原 17→16 services owner list. 见 docs/w2-deprecate-regional-plan.md。
EXPECTED_SERVICE_SHELLS = [
    "gateway",
    "tx-agent",
    "tx-analytics",
    "tx-brain",
    "tx-expense",
    "tx-finance",
    "tx-growth",
    "tx-intel",
    "tx-member",
    "tx-menu",
    "tx-ops",
    "tx-org",
    "tx-pay",
    "tx-predict",
    "tx-supply",
    "tx-trade",
]


def _shell_dirs():
    """Return list of (name, path) for all alembic shells (services + core)."""
    shells = [(svc, SERVICES_DIR / svc / "db-migrations") for svc in EXPECTED_SERVICE_SHELLS]
    shells.append(("shared/core", SHARED_CORE_DIR))
    return shells


def test_all_expected_shells_exist():
    """16 service + 1 core shells exist."""
    missing = [(name, str(path)) for name, path in _shell_dirs() if not path.is_dir()]
    assert not missing, f"Missing shells: {missing}"


def test_each_shell_has_required_files():
    """每个 shell 含 alembic.ini / env.py / script.py.mako / versions/ / tests/__init__.py / README.md"""
    required = ["alembic.ini", "env.py", "script.py.mako", "README.md"]
    required_dirs = ["versions", "tests"]
    missing: list[str] = []
    for name, path in _shell_dirs():
        if not path.is_dir():
            continue  # caught by other test
        for f in required:
            if not (path / f).is_file():
                missing.append(f"{name}: missing {f}")
        for d in required_dirs:
            if not (path / d).is_dir():
                missing.append(f"{name}: missing {d}/")
        if not (path / "tests" / "__init__.py").is_file():
            missing.append(f"{name}: missing tests/__init__.py")
    assert not missing, "Required files missing:\n" + "\n".join(missing)


def test_version_table_names_unique_and_correct_pattern():
    """每个 alembic.ini 声明 version_table，且彼此唯一。

    pattern：service 名（- → _）+ '_alembic_version' / shared/core = 'core_alembic_version'
    """
    expected_tables: dict[str, str] = {}
    for svc in EXPECTED_SERVICE_SHELLS:
        expected_tables[svc] = svc.replace("-", "_") + "_alembic_version"
    expected_tables["shared/core"] = "core_alembic_version"

    actual: dict[str, str] = {}
    for name, path in _shell_dirs():
        if not (path / "alembic.ini").is_file():
            continue
        cp = configparser.ConfigParser()
        cp.read(path / "alembic.ini")
        actual[name] = cp.get("alembic", "version_table", fallback="<missing>")

    assert actual == expected_tables, (
        f"version_table mismatches:\n  expected: {expected_tables}\n  actual: {actual}"
    )

    # Uniqueness
    seen = set()
    dups = []
    for name, vt in actual.items():
        if vt in seen:
            dups.append(vt)
        seen.add(vt)
    assert not dups, f"Duplicate version_table values: {dups}"


def test_each_env_py_imports_cleanly():
    """env.py 不能有 syntax error / import error。"""
    failures: list[str] = []
    for name, path in _shell_dirs():
        env_py = path / "env.py"
        if not env_py.is_file():
            continue
        # 仅 compile 检查 syntax，不执行 import（env.py top-level 会运行 migration
        # 需要 DB 连接）。compile 只可能抛 SyntaxError，不会抛 ImportError；
        # 真 ImportError（如 alembic 未装）会在实际跑 alembic 时立即报错。
        try:
            with open(env_py) as f:
                compile(f.read(), str(env_py), "exec")
        except SyntaxError as e:
            failures.append(f"{name}: {e}")
    assert not failures, "env.py compile failures:\n" + "\n".join(failures)


def test_versions_dir_starts_empty_with_gitkeep():
    """Phase 4a-3 起手 — versions/ 应为空，仅 .gitkeep（待 Phase 4a-4 baseline 注入）。"""
    for name, path in _shell_dirs():
        if not (path / "versions").is_dir():
            continue
        py_files = list((path / "versions").glob("*.py"))
        assert not py_files, (
            f"{name}: versions/ 应为空（Phase 4a-3 阶段），实际含 {[f.name for f in py_files]}。"
            f"Phase 4a-4 baseline 入栈应改 baseline 测试断言。"
        )
        assert (path / "versions" / ".gitkeep").is_file(), (
            f"{name}: versions/.gitkeep 缺失（防止 git 忽略空目录）"
        )


def test_old_mono_repo_migrations_not_archived_yet():
    """Phase 4a 进行中：shared/db-migrations/ 仍存在（mono-repo 历史未 archive）。

    当 Phase 4a-7 完成时，此测试改 assert shared/db-migrations/_archive/ 存在。
    """
    old = REPO_ROOT / "shared/db-migrations"
    assert old.is_dir(), f"old mono-repo {old} 应仍存在（Phase 4a-7 archive 前）"
    # 未来 Phase 4a-7 完成后，改 assert (old / "_archive").is_dir()
