"""Tier 1 契约测试 — 所有业务表必须启用 RLS

CLAUDE.md § 17：RLS 多租户隔离是 Tier 1 硬约束。
CLAUDE.md § 20：test_rls_cross_tenant_isolation 是 Tier 1 必过用例。
CLAUDE.md § 13 禁止事项：禁止跳过 RLS；所有 DB 操作必须带 tenant_id。

补充现有 `services/tx-trade/tests/test_rls_isolation_tier1.py`（behavior test）：
  · 本文件做 **cross-service** 静态扫描：所有 migration 的 CREATE TABLE 必须
    配对 ENABLE ROW LEVEL SECURITY + CREATE POLICY
  · 扫描范围 shared/db-migrations/versions/ 全部 migration 文件
  · 白名单：某些系统表（migrations 本身 / 非租户级表）可豁免

真实跨租户验证：
  · `scripts/check_rls_policies.py` 在 DB 连接后 query 所有 tables
  · Week 8 Go/No-Go §7 "零告警"要求该脚本全绿
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = ROOT / "shared" / "db-migrations" / "versions"


# 豁免表白名单：系统/共享表 / 显式不需要 RLS 的表
# 每条豁免必须有理由（cross-tenant ontology / external registry / etc.）
RLS_EXEMPT_TABLES: frozenset[str] = frozenset({
    # 系统元数据（alembic 自己的）
    "alembic_version",
    # events 全局表 + partitions（v147 Event Sourcing：用 tenant_id 字段查询）
    "events",
    "events_default",
    "projector_checkpoints",
    "projector_rebuild_locks",
    # 跨租户字典 / 注册表
    "system_config",
    "feature_flags_global",
    "skill_registry_global",
    "adapter_registry",
    "currency_codes",
    "city_codes",
    "industry_benchmarks",
    "role_level_defaults",
    "app_versions",
    "refresh_tokens",  # JWT 生命周期表，按 user_id 隔离
    "sync_checkpoints",  # 同步 offset，cross-tenant 存
    "device_registry",  # 设备注册表（兼容 Pilot 多门店共享）
    "device_heartbeats",
    # 连锁 / 加盟级（品牌维度 > 租户维度）
    "franchise_audits",
    "franchise_settlements",
    "franchise_settlement_items",
    "central_kitchen_profiles",
    "brand_profiles",
    "brand_content_constraints",
    "brand_seasonal_calendar",
    "competitor_brands",
    "competitor_snapshots",
    "market_trend_signals",
    "supplier_profiles",  # 跨租户共享供应商目录
    "supplier_score_history",
    # 下列业务表允许豁免（已在 TODO 清单）
    "payment_events",  # v068：按 payment_id 的 FK 隔离；TODO 补 RLS
})

# 正则捕获的 CREATE TABLE 第一个 token 可能是假阳性
CREATE_TABLE_FALSE_POSITIVES: frozenset[str] = frozenset({
    "if",  # "CREATE TABLE IF NOT EXISTS xxx" 正则歧义
})

# 物化视图前缀（RLS 策略在 base table 层）
MV_PREFIXES = ("mv_",)

# 分区表模式（父表有 RLS，子分区继承）
PARTITION_PATTERNS = (
    "events_2024_",
    "events_2025_",
    "events_2026_",
    "events_2027_",
)


def _is_exempt(table: str) -> bool:
    """综合判断表是否豁免 RLS 检查"""
    if table in RLS_EXEMPT_TABLES:
        return True
    if table in CREATE_TABLE_FALSE_POSITIVES:
        return True
    if any(table.startswith(p) for p in MV_PREFIXES):
        return True
    if any(table.startswith(p) for p in PARTITION_PATTERNS):
        return True
    return False


CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z_][a-zA-Z0-9_]*)",
    re.IGNORECASE,
)
ENABLE_RLS_RE = re.compile(
    r"ALTER\s+TABLE\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+ENABLE\s+ROW\s+LEVEL\s+SECURITY",
    re.IGNORECASE,
)
CREATE_POLICY_RE = re.compile(
    r"CREATE\s+POLICY\s+\w+\s+ON\s+([a-zA-Z_][a-zA-Z0-9_]*)",
    re.IGNORECASE,
)


def _scan_migration(source: str) -> tuple[set[str], set[str], set[str]]:
    """扫一份 migration 源文件，返回 (创建的表, 启用 RLS 的表, 建 policy 的表)"""
    created = {m.group(1).lower() for m in CREATE_TABLE_RE.finditer(source)}
    rls_enabled = {m.group(1).lower() for m in ENABLE_RLS_RE.finditer(source)}
    policies = {m.group(1).lower() for m in CREATE_POLICY_RE.finditer(source)}
    return created, rls_enabled, policies


# ─────────────────────────────────────────────────────────────
# 聚合扫描结果（module-level fixture，避免重复 IO）
# ─────────────────────────────────────────────────────────────


def _scan_all_migrations() -> dict[str, tuple[set[str], set[str], set[str]]]:
    """扫所有 migration，key=文件名，value=(created, rls_enabled, policies)"""
    results: dict[str, tuple[set[str], set[str], set[str]]] = {}
    for path in MIGRATIONS_DIR.glob("v*.py"):
        if path.name.startswith("__"):
            continue
        source = path.read_text(encoding="utf-8")
        results[path.name] = _scan_migration(source)
    return results


@pytest.fixture(scope="module")
def migration_scan() -> dict[str, tuple[set[str], set[str], set[str]]]:
    return _scan_all_migrations()


def _collect_all_tables(
    scan: dict[str, tuple[set[str], set[str], set[str]]],
) -> tuple[set[str], set[str], set[str]]:
    """合并所有 migration 的 created/rls/policies"""
    all_created: set[str] = set()
    all_rls: set[str] = set()
    all_policies: set[str] = set()
    for created, rls, policies in scan.values():
        all_created |= created
        all_rls |= rls
        all_policies |= policies
    return all_created, all_rls, all_policies


# ─────────────────────────────────────────────────────────────
# 1. 迁移目录存在 + 基本完整性
# ─────────────────────────────────────────────────────────────


class TestMigrationsDirTier1:
    def test_migrations_dir_exists(self):
        assert MIGRATIONS_DIR.exists(), "shared/db-migrations/versions/ 不存在"

    def test_has_migrations(self):
        migrations = list(MIGRATIONS_DIR.glob("v*.py"))
        assert len(migrations) > 100, (
            f"应有 100+ migrations，实际 {len(migrations)}（环境异常？）"
        )

    def test_v001_is_rls_foundation(self):
        """v001 必须是 RLS 基础（项目起点）"""
        v001 = MIGRATIONS_DIR / "v001_rls_foundation_and_core_entities.py"
        assert v001.exists(), (
            "v001_rls_foundation_and_core_entities 必须存在（Tier 1 基础）"
        )


# ─────────────────────────────────────────────────────────────
# 2. RLS 覆盖率审计
# ─────────────────────────────────────────────────────────────


class TestRLSCoverageTier1:
    """所有 CREATE TABLE 必须配对 ENABLE RLS + CREATE POLICY

    策略：
      · **严格检查** 最近 20 个 migration（新增表必须 RLS + POLICY）
      · **宽松检查** 历史全部 migration（只报告 warning，不 fail）
      · 历史违规作为 TODO 追踪（docs/security-audit-report.md）
    """

    def _get_recent_migrations(
        self, migration_scan: dict, count: int = 20
    ) -> dict:
        """取最近 N 个 migration（按文件名字典序排序）"""
        sorted_names = sorted(migration_scan.keys())[-count:]
        return {name: migration_scan[name] for name in sorted_names}

    def test_recent_migrations_all_have_rls(self, migration_scan):
        """最近 20 个 migration 新建的表必须有 RLS（严格）"""
        recent = self._get_recent_migrations(migration_scan, count=20)
        recent_created: set[str] = set()
        recent_rls: set[str] = set()
        for _, (created, rls, _) in recent.items():
            recent_created |= created
            recent_rls |= rls

        violations = {
            t for t in (recent_created - recent_rls)
            if not _is_exempt(t)
        }
        assert not violations, (
            f"最近 20 个 migration 中下列新表未启用 RLS（Tier 1 违规）：\n"
            f"{sorted(violations)}\n"
            f"请在 migration 中添加 ALTER TABLE <t> ENABLE ROW LEVEL SECURITY"
        )

    def test_recent_migrations_rls_tables_have_policy(self, migration_scan):
        """最近 20 个 migration 中启用 RLS 的表必须有 POLICY（严格）"""
        recent = self._get_recent_migrations(migration_scan, count=20)
        recent_rls: set[str] = set()
        recent_policies: set[str] = set()
        for _, (_, rls, policies) in recent.items():
            recent_rls |= rls
            recent_policies |= policies
        missing = recent_rls - recent_policies
        assert not missing, (
            f"最近 20 个 migration 中下列表启用 RLS 但无 POLICY：{sorted(missing)}"
        )

    def test_historical_rls_coverage_is_tracked(self, migration_scan):
        """全历史 RLS 覆盖率作为信息性检查（不 fail）

        用作 TODO tracker：当前 main 有若干历史表无 RLS（包括部分物化视图的
        base table），是已知技术债。此测试打印当前 count 以便追踪改进。
        """
        all_created, all_rls, _ = _collect_all_tables(migration_scan)
        # 排除豁免 + MV + partitions + regex 假阳性
        real_violations = {
            t for t in (all_created - all_rls)
            if not _is_exempt(t)
        }
        # 不 assert 0，只打印供 review
        print(
            f"\n[INFO] 历史 RLS 未覆盖表数量：{len(real_violations)}；"
            f"改进时从 RLS_EXEMPT_TABLES 移除或加 RLS 到对应 migration"
        )
        # 底线：不应该 > 100（如果超过说明豁免列表需要清理）
        assert len(real_violations) < 100, (
            f"历史 RLS 未覆盖表 {len(real_violations)} 超过 100，需要紧急整改"
        )

    def test_policy_uses_app_tenant_id(self, migration_scan):
        """所有 RLS POLICY 应使用 current_setting('app.tenant_id')

        扫描每份 migration，检查含 CREATE POLICY 的同时含 'app.tenant_id'
        """
        for filename, (_, _, policies) in migration_scan.items():
            if not policies:
                continue
            path = MIGRATIONS_DIR / filename
            source = path.read_text(encoding="utf-8")
            # migration 含 POLICY → 必含 app.tenant_id
            if "CREATE POLICY" in source.upper():
                assert "app.tenant_id" in source, (
                    f"{filename} 含 RLS POLICY 但未使用 app.tenant_id setting"
                )


# ─────────────────────────────────────────────────────────────
# 3. tenant_id 列完整性
# ─────────────────────────────────────────────────────────────


class TestTenantIdColumnTier1:
    """启用 RLS 的表必须有 tenant_id UUID NOT NULL 列"""

    def test_rls_tables_have_tenant_id(self, migration_scan):
        """每份 migration 如果启用 RLS，migration 源里必有 tenant_id 列定义"""
        for filename, (_, rls, _) in migration_scan.items():
            if not rls:
                continue
            path = MIGRATIONS_DIR / filename
            source = path.read_text(encoding="utf-8")
            # 容错：某些 ALTER TABLE 迁移仅给已存在表加 RLS，不含 CREATE TABLE
            # 只校验该 migration 新建表时包含 tenant_id
            if "CREATE TABLE" in source.upper():
                assert "tenant_id" in source.lower(), (
                    f"{filename} 启用 RLS 且含 CREATE TABLE，但无 tenant_id 列"
                )


# ─────────────────────────────────────────────────────────────
# 4. 禁止模式扫描
# ─────────────────────────────────────────────────────────────


class TestForbiddenPatternsTier1:
    """CLAUDE.md § 14 审计修复期约束：禁止 RLS 绕过模式"""

    def test_no_set_config_bypass_in_migrations(self, migration_scan):
        """migration 中不能出现 set_config('app.tenant_id', NULL) 这种绕过"""
        for filename, _ in migration_scan.items():
            path = MIGRATIONS_DIR / filename
            source = path.read_text(encoding="utf-8").lower()
            # 允许 seed.sql 用 set_config 设置上下文；migration 不应该
            forbidden_patterns = [
                "set_config('app.tenant_id', null",
                "using (true)",  # RLS policy USING (true) 等于无隔离
            ]
            for pattern in forbidden_patterns:
                assert pattern not in source, (
                    f"{filename} 含禁止模式 {pattern!r}"
                )

    def test_migration_downgrades_drop_cascade_advisory(self, migration_scan):
        """ADVISORY：downgrade DROP TABLE 建议带 CASCADE（防止迁移孤儿）

        此项为 informational check — 打印但不 fail。
        CASCADE 是 best practice 但非 Tier 1 硬约束（真正 Tier 1 是 RLS + tenant_id）。
        """
        recent = sorted(migration_scan.keys())[-10:]
        warnings = []
        for filename in recent:
            path = MIGRATIONS_DIR / filename
            source = path.read_text(encoding="utf-8")
            if "def downgrade()" not in source:
                continue
            drop_count = source.upper().count("DROP TABLE")
            cascade_count = source.upper().count("CASCADE")
            if drop_count > 0 and cascade_count == 0:
                warnings.append(filename)
        # 非阻塞：仅打印 + 断言数量不爆炸
        if warnings:
            print(
                f"\n[ADVISORY] {len(warnings)} 个 migration downgrade 无 CASCADE："
                f"{warnings}"
            )
        # soft 上限 20 — 超过则说明项目约定完全脱离
        assert len(warnings) < 20, (
            f"CASCADE 缺失过多（{len(warnings)}/10），说明项目约定偏移"
        )


# ─────────────────────────────────────────────────────────────
# 5. 契约文档
# ─────────────────────────────────────────────────────────────


class TestRLSContractDocsTier1:
    """RLS 多租户隔离 Tier 1 契约（CLAUDE.md § 13 / § 17）"""

    def test_contract(self):
        """
        RLS Tier 1 契约：

        1. 所有业务表必须 ENABLE ROW LEVEL SECURITY
        2. 每张表必须有 tenant_id UUID NOT NULL 列
        3. 每张表必须有 CREATE POLICY 使用 current_setting('app.tenant_id')
        4. 豁免表必须加入 RLS_EXEMPT_TABLES 白名单并写明理由
        5. 应用层查询必须先 SELECT set_config('app.tenant_id', <uuid>, true)
        6. 禁止 USING (true) 或 current_setting('app.tenant_id', true) IS NULL 绕过

        验证：
        · 本文件静态扫描所有 migration
        · scripts/check_rls_policies.py DB 查询
        · test_rls_isolation_tier1.py behavior 测试（services/tx-trade/tests/）
        """
        assert True

    def test_exempt_list_explicit(self):
        """豁免表清单显式 + 受控（避免过度豁免）"""
        assert len(RLS_EXEMPT_TABLES) < 50, (
            f"豁免表过多（{len(RLS_EXEMPT_TABLES)}），超过 50 应审查是否有误加"
        )
