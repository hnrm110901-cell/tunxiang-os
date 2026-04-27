"""Tier 1 契约测试 — scripts/check_rls_policies.py CLI

Week 8 Go/No-Go §7 RLS/凭证零告警依赖此脚本。本文件验证：
  1. DSN 规范化（SQLAlchemy scheme → asyncpg）
  2. DSN 密码脱敏（日志安全）
  3. CLI 参数解析（--json / --strict / --database-url）
  4. Exit codes 语义（0/1/2/3 分别对应 clean/issues/db-fail/config）

不测试：
  · 真实 DB 查询（需 PG 实例）
  · JSON 报告数值准确性（需真数据）
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys  # noqa: F401 — 用在 _load_module
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_rls_policies.py"


def _load_module():
    """importlib 加载脚本（避免依赖安装 asyncpg 时 import 失败）

    注：dataclasses 装饰器需要 `sys.modules[module.__name__]` 存在，
    所以先注册再 exec。
    """
    module_name = "check_rls_policies_under_test"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ─────────────────────────────────────────────────────────────
# 1. DSN 规范化
# ─────────────────────────────────────────────────────────────


class TestDsnNormalization:
    """normalize_dsn 必须处理多种 DSN 格式"""

    @pytest.fixture(scope="class")
    def mod(self):
        return _load_module()

    def test_sqlalchemy_asyncpg_stripped(self, mod):
        dsn = "postgresql+asyncpg://user:pass@localhost/db"
        assert mod.normalize_dsn(dsn) == "postgresql://user:pass@localhost/db"

    def test_sqlalchemy_psycopg2_stripped(self, mod):
        dsn = "postgresql+psycopg2://user:pass@host:5432/db"
        assert mod.normalize_dsn(dsn) == "postgresql://user:pass@host:5432/db"

    def test_sqlalchemy_psycopg_stripped(self, mod):
        dsn = "postgresql+psycopg://user:pass@host/db"
        assert mod.normalize_dsn(dsn) == "postgresql://user:pass@host/db"

    def test_postgres_scheme_preserved(self, mod):
        """短 scheme 'postgres://' 不变"""
        dsn = "postgres://user:pass@localhost/db"
        assert mod.normalize_dsn(dsn) == "postgres://user:pass@localhost/db"

    def test_postgres_with_dialect_stripped(self, mod):
        dsn = "postgres+psycopg://user:pass@localhost/db"
        assert mod.normalize_dsn(dsn) == "postgres://user:pass@localhost/db"

    def test_postgresql_plain_unchanged(self, mod):
        dsn = "postgresql://user:pass@localhost/db"
        assert mod.normalize_dsn(dsn) == dsn

    def test_empty_dsn_unchanged(self, mod):
        assert mod.normalize_dsn("") == ""

    def test_complex_dsn_with_query_params(self, mod):
        dsn = "postgresql+asyncpg://user:pass@localhost:5432/db?sslmode=require"
        normalized = mod.normalize_dsn(dsn)
        assert normalized.startswith("postgresql://")
        assert "?sslmode=require" in normalized

    def test_no_scheme_dsn_unchanged(self, mod):
        """无 scheme 的 DSN 保持原样（会在 connect 时报错）"""
        dsn = "user:pass@localhost/db"
        assert mod.normalize_dsn(dsn) == dsn

    def test_case_insensitive_match(self, mod):
        """scheme 大小写混合也能处理"""
        dsn = "POSTGRESQL+asyncpg://user:pass@localhost/db"
        normalized = mod.normalize_dsn(dsn)
        assert "://" in normalized
        assert "+" not in normalized.split("://")[0]


# ─────────────────────────────────────────────────────────────
# 2. DSN 脱敏
# ─────────────────────────────────────────────────────────────


class TestDsnRedaction:
    """redact_dsn 必须隐藏密码（防日志泄露）"""

    @pytest.fixture(scope="class")
    def mod(self):
        return _load_module()

    def test_password_redacted(self, mod):
        dsn = "postgresql://user:secret123@localhost/db"
        redacted = mod.redact_dsn(dsn)
        assert "secret123" not in redacted
        assert "user" in redacted
        assert "localhost" in redacted
        assert "***" in redacted

    def test_complex_password_redacted(self, mod):
        """含特殊字符的密码也能脱敏"""
        dsn = "postgresql://admin:A1b2!Cd3@host:5432/db"
        redacted = mod.redact_dsn(dsn)
        assert "A1b2!Cd3" not in redacted
        assert "admin" in redacted

    def test_no_password_unchanged(self, mod):
        """无密码 DSN 不脱敏"""
        dsn = "postgresql://user@localhost/db"
        assert mod.redact_dsn(dsn) == dsn

    def test_no_auth_unchanged(self, mod):
        """无 auth 部分的 DSN 不脱敏"""
        dsn = "postgresql://localhost/db"
        assert mod.redact_dsn(dsn) == dsn


# ─────────────────────────────────────────────────────────────
# 3. CLI 契约（子进程）
# ─────────────────────────────────────────────────────────────


class TestCliContract:
    def test_help_flag_returns_0(self):
        """--help 必须 exit 0 + 有 usage 信息"""
        result = subprocess.run(  # noqa: S603
            [sys.executable, str(SCRIPT), "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "usage" in result.stdout.lower()

    def test_exit_code_on_db_connect_fail_is_2(self):
        """无法连接 DB 时 exit 2（区别于"发现问题" exit 1）"""
        result = subprocess.run(  # noqa: S603
            [
                sys.executable, str(SCRIPT),
                "--database-url", "postgresql://none:none@127.0.0.1:9/none",
            ],
            capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 2, (
            f"DB connect fail 应 exit 2，实际 {result.returncode}"
        )

    def test_sqlalchemy_dsn_accepted(self):
        """SQLAlchemy DSN 不再报 'invalid DSN scheme'"""
        result = subprocess.run(  # noqa: S603
            [
                sys.executable, str(SCRIPT),
                "--database-url", "postgresql+asyncpg://u:p@127.0.0.1:9/x",
            ],
            capture_output=True, text=True, timeout=15,
        )
        combined = result.stdout + result.stderr
        assert "invalid DSN" not in combined, (
            "DSN normalization 应消除 invalid DSN 错误"
        )
        # 但仍会 DB connect 失败
        assert result.returncode == 2

    def test_json_flag_outputs_valid_json(self):
        """--json 模式输出必须是合法 JSON"""
        import json as _json
        result = subprocess.run(  # noqa: S603
            [
                sys.executable, str(SCRIPT),
                "--json",
                "--database-url", "postgresql://none:none@127.0.0.1:9/none",
            ],
            capture_output=True, text=True, timeout=15,
        )
        # stdout 必须是合法 JSON（即便是 error case）
        try:
            data = _json.loads(result.stdout)
        except _json.JSONDecodeError:
            pytest.fail(f"--json 输出不是合法 JSON:\n{result.stdout}")
        assert "summary" in data

    def test_json_error_payload_shape(self):
        """DB 失败时 JSON 必须含 error + summary.error=true"""
        import json as _json
        result = subprocess.run(  # noqa: S603
            [
                sys.executable, str(SCRIPT),
                "--json",
                "--database-url", "postgresql://none:none@127.0.0.1:9/none",
            ],
            capture_output=True, text=True, timeout=15,
        )
        data = _json.loads(result.stdout)
        assert "error" in data
        assert data["summary"]["passed"] is False
        assert data["summary"]["error"] is True

    def test_json_does_not_leak_password(self):
        """JSON 输出不得泄露 DB 密码"""
        result = subprocess.run(  # noqa: S603
            [
                sys.executable, str(SCRIPT),
                "--json",
                "--database-url", "postgresql://admin:super_secret_xyz@127.0.0.1:9/x",
            ],
            capture_output=True, text=True, timeout=15,
        )
        combined = result.stdout + result.stderr
        assert "super_secret_xyz" not in combined, (
            "JSON / stderr 不得含明文密码"
        )

    def test_strict_flag_parseable(self):
        """--strict 是合法参数（不抛 unknown flag）"""
        result = subprocess.run(  # noqa: S603
            [
                sys.executable, str(SCRIPT), "--strict", "--help",
            ],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0


# ─────────────────────────────────────────────────────────────
# 4. Exit code 语义
# ─────────────────────────────────────────────────────────────


class TestExitCodeSemantics:
    """Exit code 语义必须稳定（CI 脚本依赖）"""

    @pytest.fixture(scope="class")
    def mod(self):
        return _load_module()

    def test_exit_codes_defined(self, mod):
        """EXIT_* 常量必须定义"""
        assert mod.EXIT_CLEAN == 0
        assert mod.EXIT_ISSUES_FOUND == 1
        assert mod.EXIT_DB_CONNECT_FAIL == 2
        assert mod.EXIT_CONFIG_ERROR == 3

    def test_exit_codes_distinct(self, mod):
        """4 个 exit code 必须互不相同"""
        codes = {
            mod.EXIT_CLEAN,
            mod.EXIT_ISSUES_FOUND,
            mod.EXIT_DB_CONNECT_FAIL,
            mod.EXIT_CONFIG_ERROR,
        }
        assert len(codes) == 4


# ─────────────────────────────────────────────────────────────
# 5. BUSINESS_TABLES 覆盖 Sprint D/E/G 新表
# ─────────────────────────────────────────────────────────────


class TestBusinessTablesCoverage:
    """BUSINESS_TABLES 必须包含最近 Sprint 的新表"""

    @pytest.fixture(scope="class")
    def mod(self):
        return _load_module()

    def test_has_core_transaction_tables(self, mod):
        """核心交易表必须在清单"""
        for t in ("orders", "payments", "customers", "stores"):
            assert t in mod.BUSINESS_TABLES

    def test_has_sprint_e_delivery_tables(self, mod):
        """Sprint E canonical + publish + xhs + disputes"""
        for t in (
            "canonical_delivery_orders",
            "dish_publish_registry",
            "xiaohongshu_shop_bindings",
            "delivery_disputes",
        ):
            assert t in mod.BUSINESS_TABLES, (
                f"Sprint E 表 {t} 未纳入 BUSINESS_TABLES（RLS 审计会漏）"
            )

    def test_has_sprint_g_ab_tables(self, mod):
        """Sprint G A/B 实验"""
        for t in (
            "ab_experiments", "ab_experiment_arms",
            "ab_experiment_assignments", "ab_experiment_events",
        ):
            assert t in mod.BUSINESS_TABLES

    def test_has_sprint_d_ai_tables(self, mod):
        """Sprint D 批次 AI 分析表"""
        for t in (
            "cost_root_cause_analyses",
            "salary_anomaly_analyses",
            "budget_forecast_analyses",
        ):
            assert t in mod.BUSINESS_TABLES

    def test_no_duplicates(self, mod):
        """BUSINESS_TABLES 不应有重复"""
        assert len(mod.BUSINESS_TABLES) == len(set(mod.BUSINESS_TABLES))

    def test_count_reasonable(self, mod):
        """总表数应在合理范围（太少说明遗漏 / 太多说明污染）"""
        count = len(mod.BUSINESS_TABLES)
        assert 80 < count < 200, f"BUSINESS_TABLES 数量 {count} 异常"
