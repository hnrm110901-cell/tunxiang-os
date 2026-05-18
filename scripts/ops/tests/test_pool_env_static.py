"""#737 Phase A — 3 个 pool 源 env knob 静态层检查 (任何 Python 版本都跑).

per memory feedback_helper_only_test_for_import_blocked_module — 项目主源 import
链含 Python 3.10+ 特性 (@dataclass(slots=True), `|` type hint), 本机 Python 3.9
无法 import. Source-level grep 是 helper-only 替代方案, CI (3.11) + 本机都跑.

覆盖 3 个 pool 源:
  - shared/ontology/src/database.py (DATABASE_POOL_SIZE / DATABASE_POOL_OVERFLOW)
  - shared/events/src/projector.py (ASYNCPG_POOL_MAX × 2 — run + rebuild)
  - services/tx-supply/src/workers/cert_expiry_alerter.py (CERT_ALERTER_POOL_*)

每个源 verify:
  1. env 读取 pattern 真存在
  2. default 与 ship 前等价 (Q2=A regression-safe)
"""
from __future__ import annotations

import os
from pathlib import Path

# 仓库根 (从 scripts/ops/tests/ 上溯 3 层)
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _read(rel_path: str) -> str:
    full = _REPO_ROOT / rel_path
    return full.read_text(encoding="utf-8")


# ─── shared/ontology/src/database.py (SQLAlchemy 共享 engine) ───────────────


def test_database_pool_size_env_knob() -> None:
    content = _read("shared/ontology/src/database.py")
    assert 'os.getenv("DATABASE_POOL_SIZE", "20")' in content
    assert 'os.getenv("DATABASE_POOL_OVERFLOW", "30")' in content


def test_database_dead_engine_line_14_untouched() -> None:
    """Q3=A: dead engine line 14 `pool_size=10, max_overflow=20` 不动 (#738 独立 PR scope)."""
    content = _read("shared/ontology/src/database.py")
    assert "pool_size=10, max_overflow=20" in content, (
        "dead engine line 14 literal must remain unchanged per Q3=A — #738 scope"
    )


def test_database_active_engine_defaults_match_pre_ship() -> None:
    """Q2=A: active engine env default 20/30 = ship 前值."""
    content = _read("shared/ontology/src/database.py")
    assert '"DATABASE_POOL_SIZE", "20"' in content
    assert '"DATABASE_POOL_OVERFLOW", "30"' in content


# ─── shared/events/src/projector.py (asyncpg pool × 2) ──────────────────────


def test_projector_asyncpg_pool_max_env_two_sites() -> None:
    """run + rebuild 路径都读 ASYNCPG_POOL_MAX env."""
    content = _read("shared/events/src/projector.py")
    occurrences = content.count('os.getenv("ASYNCPG_POOL_MAX", "3")')
    assert occurrences == 2, (
        f"expected 2 occurrences of ASYNCPG_POOL_MAX env (run + rebuild), got {occurrences}"
    )


def test_projector_min_size_unchanged() -> None:
    """min_size=1 default 不动 (sanity)."""
    content = _read("shared/events/src/projector.py")
    assert content.count("min_size=1") >= 2, "min_size=1 should appear at both create_pool sites"


# ─── services/tx-supply/src/workers/cert_expiry_alerter.py ─────────────────


def test_cert_alerter_pool_env_knobs() -> None:
    content = _read("services/tx-supply/src/workers/cert_expiry_alerter.py")
    assert 'os.getenv("CERT_ALERTER_POOL_SIZE", "5")' in content
    assert 'os.getenv("CERT_ALERTER_POOL_OVERFLOW", "10")' in content


def test_cert_alerter_defaults_match_pre_ship() -> None:
    """Q2=A: env default 5/10 = ship 前值."""
    content = _read("services/tx-supply/src/workers/cert_expiry_alerter.py")
    assert '"CERT_ALERTER_POOL_SIZE", "5"' in content
    assert '"CERT_ALERTER_POOL_OVERFLOW", "10"' in content


# ─── helm + compose 静态层 ──────────────────────────────────────────────────


def test_helm_tx_supply_values_has_5_pool_env() -> None:
    content = _read("infra/helm/tx-supply/values.yaml")
    for key in (
        "DATABASE_POOL_SIZE",
        "DATABASE_POOL_OVERFLOW",
        "ASYNCPG_POOL_MAX",
        "CERT_ALERTER_POOL_SIZE",
        "CERT_ALERTER_POOL_OVERFLOW",
    ):
        assert key in content, f"helm/tx-supply values.yaml missing {key}"


def test_helm_tx_analytics_values_has_3_pool_env() -> None:
    """tx-analytics 没有 cert_alerter, 只暴露 3 个 pool env (Q1=B 决议)."""
    content = _read("infra/helm/tx-analytics/values.yaml")
    for key in ("DATABASE_POOL_SIZE", "DATABASE_POOL_OVERFLOW", "ASYNCPG_POOL_MAX"):
        assert key in content, f"helm/tx-analytics values.yaml missing {key}"
    # cert_alerter env 应不存在 (Q1=B scope 分离)
    assert "CERT_ALERTER_POOL_SIZE" not in content, (
        "tx-analytics should NOT expose CERT_ALERTER_POOL_SIZE (no cert_alerter daemon)"
    )


def test_compose_base_x_env_has_5_pool_env() -> None:
    """infra/compose/base.yml x-env: &common-env anchor 含 5 个 pool env."""
    content = _read("infra/compose/base.yml")
    for key, default in [
        ("DATABASE_POOL_SIZE", "20"),
        ("DATABASE_POOL_OVERFLOW", "30"),
        ("ASYNCPG_POOL_MAX", "3"),
        ("CERT_ALERTER_POOL_SIZE", "5"),
        ("CERT_ALERTER_POOL_OVERFLOW", "10"),
    ]:
        assert f"${{{key}:-{default}}}" in content, f"compose base.yml missing {key} with default {default}"
