"""Schema lint Tier 1 — 静态检测 7 类常见 migration bug 模式

涵盖 B'-1 至 B'-6 (PR #337/#339/#340/#342/#343/#345) 暴露的 7 类 bug：

  类 A — 同名表多 schema 撞名（CREATE TABLE 名重复，需手 audit）
  类 B — server_default JSONB 引号嵌套（"'{}'" / "'[]'"）
  类 C — sa.text bind param + PG cast 连写歧义（":cfg::jsonb"）
  类 D — PRIMARY KEY 含函数表达式（PG 拒绝）
  类 F — CREATE POLICY IF NOT EXISTS（PG 不支持）
  类 F — FOR INSERT TO PUBLIC USING（INSERT POLICY 应用 WITH CHECK）
  类 G — GENERATED ALWAYS / CREATE INDEX 含非 IMMUTABLE 函数
  （类 E op.create_index 缺 IF NOT EXISTS 不强制 — alembic 推荐
   op.create_index，幂等性由迁移作者保证；不在本 linter 范围）

每条规则有"已知 baseline 容忍数"。新 PR 引入超过 baseline 的违例 → fail。
随历史 bug 修复，baseline 应 ratchet 下降。

详细规则说明 + 修复指引：见 docs/migration-schema-lint-rules.md
"""

from __future__ import annotations

import collections
import os
import re
from pathlib import Path

VERSIONS_DIR = Path(__file__).parent.parent / "versions"


# ─── 扫描工具 ───────────────────────────────────────────────────────────────

def _iter_migration_files():
    """yield (path, source) for all live migration files (skip .disabled)."""
    for entry in sorted(os.listdir(VERSIONS_DIR)):
        if not entry.endswith(".py") or entry.endswith(".disabled"):
            continue
        if entry.startswith("__"):
            continue
        path = VERSIONS_DIR / entry
        yield path, path.read_text()


def _line_no(src: str, pos: int) -> int:
    """1-based line number for byte offset pos."""
    return src.count("\n", 0, pos) + 1


def _format_violations(name: str, violations: list[tuple[str, int, str]]) -> str:
    lines = [f"{name} ({len(violations)} 处违例):"]
    for path, line, snippet in violations[:30]:  # cap output
        lines.append(f"  {os.path.basename(path)}:{line}  {snippet[:80]}")
    if len(violations) > 30:
        lines.append(f"  ... +{len(violations) - 30} more")
    return "\n".join(lines)


# ─── 类 A — 同名表多 schema 撞名 ─────────────────────────────────────────────

# 支持 schema-qualified `public.orders` — 非捕获组吞 schema 前缀，仅捕获表名
_CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:[a-z_][a-z0-9_]*\.)?([a-z_][a-z0-9_]*)\s*\(",
    re.IGNORECASE,
)


def _scan_class_a():
    """Find tables CREATE'd by 2+ migration files."""
    table_to_files: dict[str, list[str]] = collections.defaultdict(list)
    for path, src in _iter_migration_files():
        for m in _CREATE_TABLE_RE.finditer(src):
            table = m.group(1)
            if path.name not in table_to_files[table]:
                table_to_files[table].append(path.name)
    return {t: fs for t, fs in table_to_files.items() if len(fs) > 1}


# 已知 baseline (2026-05-10): chain 历史 504 mig 中重复 CREATE TABLE 表数
# 已 audit 大类: approval_instances / banquet_leads / banquet_quotes /
# delivery_dispatches / employee_transfers / pos_crash_reports / banquets /
# banquet_venues / banquet_table_groups / banquet_menu_templates / banquet_quote_items /
# banquet_contracts / banquet_feedbacks / banquet_referrals / banquet_eo_tickets /
# banquet_approval_logs（共 ~16 张已暴露）
# 实际仓库数量包含 banquet_proposals 等更多重复 — 总数留浮动空间
_CLASS_A_BASELINE = 25


def test_class_a_no_new_duplicate_table_creates():
    """类 A: 多 migration 文件 CREATE 同表名 — 大概率撞 schema。

    当前 baseline {_CLASS_A_BASELINE} 处。新 PR 引入超过此数 → fail。
    每修复一组（如 banquet_leads triplet），ratchet baseline 下降。
    """
    duplicates = _scan_class_a()
    msg = (
        f"类 A 同名表撞 schema 检测：发现 {len(duplicates)} 张表被多文件创建。\n"
        + "\n".join(f"  {t}: {fs}" for t, fs in sorted(duplicates.items())[:30])
    )
    assert len(duplicates) <= _CLASS_A_BASELINE, (
        f"{msg}\n\n超过 baseline {_CLASS_A_BASELINE}。新 PR 不应引入新撞名表 — "
        f"如确需多文件改 schema，请用 ALTER TABLE 而非 CREATE TABLE，或更名分表。"
    )


# ─── 类 B — server_default JSONB 引号嵌套 ───────────────────────────────────

_CLASS_B_RE = re.compile(r"""server_default=["']'(?:\{\}|\[\])'["']""")


def _scan_class_b():
    violations = []
    for path, src in _iter_migration_files():
        for m in _CLASS_B_RE.finditer(src):
            violations.append((str(path), _line_no(src, m.start()), m.group()))
    return violations


_CLASS_B_BASELINE = 20  # PR #339 修后下降；本 PR 起点 = main 状态


def test_class_b_no_jsonb_double_quoted_default():
    """类 B: `server_default="'{}'"` 双引号嵌套单引号 — Python 字面量传给
    SQLAlchemy 后渲染 SQL `DEFAULT '{}'` PG 端 invalid JSON。

    应改 `server_default=sa.text("'{}'::jsonb")`。
    """
    violations = _scan_class_b()
    assert len(violations) <= _CLASS_B_BASELINE, _format_violations(
        "类 B JSONB 引号嵌套", violations
    ) + (
        f"\n\n超过 baseline {_CLASS_B_BASELINE}。修法："
        f"\nserver_default=\"'{{}}'\"\n→\nserver_default=sa.text(\"'{{}}'::jsonb\")"
    )


# ─── 类 C — sa.text bind param + PG cast 歧义 ───────────────────────────────

_CLASS_C_RE = re.compile(r"sa\.text\([^)]*?:\w+::\w+", re.DOTALL)


def _scan_class_c():
    violations = []
    for path, src in _iter_migration_files():
        for m in _CLASS_C_RE.finditer(src):
            violations.append((str(path), _line_no(src, m.start()), m.group()[:100]))
    return violations


_CLASS_C_BASELINE = 1  # PR #339 修后下降；main 起点 1 处（v232c）


def test_class_c_no_text_bind_with_cast_ambiguity():
    """类 C: `sa.text("...:cfg::jsonb")` PG cast `::` 与命名参数 `:` 连写。

    SQLAlchemy text 解析器误判 `:cfg` 为参数 `cfg::jsonb` 而非简单 `cfg`。

    修法 1：`cast(:cfg AS jsonb)` 显式 cast 函数。
    修法 2：`(:cfg)::jsonb` 加括号断歧义。
    修法 3：`op.get_bind().exec_driver_sql(...)` 跳过 SQLAlchemy 解析。
    """
    violations = _scan_class_c()
    assert len(violations) <= _CLASS_C_BASELINE, _format_violations(
        "类 C bind param + cast 歧义", violations
    )


# ─── 类 D — PRIMARY KEY 含函数表达式 ────────────────────────────────────────

# 简化版：检 PRIMARY KEY (...) 内有 SQL 函数调用（IDENT 后跟左括号，排除常见关键字）。
_CLASS_D_RE = re.compile(
    r"PRIMARY\s+KEY\s*\(([^)]*?(?:[A-Z_]+|coalesce|nullif|greatest|least)\([^)]*\)[^)]*)\)",
    re.IGNORECASE,
)


def _scan_class_d():
    violations = []
    for path, src in _iter_migration_files():
        for m in _CLASS_D_RE.finditer(src):
            violations.append(
                (str(path), _line_no(src, m.start()), m.group()[:120])
            )
    return violations


_CLASS_D_BASELINE = 1  # PR #339 修后下降；main 起点 1 处（v151b）


def test_class_d_no_primary_key_function_expression():
    """类 D: `PRIMARY KEY (..., COALESCE(zone_id, ...))` — PG 拒绝表达式 PK。

    PG PRIMARY KEY 列只接受裸列名，不接受函数表达式。

    修法 1：用哨兵 NOT NULL DEFAULT 替代 NULL coalesce，PK 用裸列。
    修法 2：拆 UNIQUE INDEX with COALESCE expression（非 PK）+ surrogate PK。
    """
    violations = _scan_class_d()
    assert len(violations) <= _CLASS_D_BASELINE, _format_violations(
        "类 D PK 含函数表达式", violations
    )


# ─── 类 F-1 — CREATE POLICY IF NOT EXISTS（PG 不支持）─────────────────────

_CLASS_F1_RE = re.compile(r"CREATE\s+POLICY\s+IF\s+NOT\s+EXISTS", re.IGNORECASE)


def _scan_class_f1():
    violations = []
    for path, src in _iter_migration_files():
        for m in _CLASS_F1_RE.finditer(src):
            violations.append((str(path), _line_no(src, m.start()), m.group()))
    return violations


_CLASS_F1_BASELINE = 1  # PR #345 修后下降；main 起点 1 处（v311）


def test_class_f1_no_create_policy_if_not_exists():
    """类 F-1: PG 不支持 `CREATE POLICY IF NOT EXISTS`。

    修法：先 `DROP POLICY IF EXISTS <name> ON <table>;` 再 `CREATE POLICY ...`。
    """
    violations = _scan_class_f1()
    assert len(violations) <= _CLASS_F1_BASELINE, _format_violations(
        "类 F-1 CREATE POLICY IF NOT EXISTS", violations
    )


# ─── 类 F-2 — FOR INSERT TO PUBLIC USING（INSERT POLICY 应 WITH CHECK）────

_CLASS_F2_RE = re.compile(
    r"FOR\s+INSERT\s+TO\s+PUBLIC\s+USING\s*\(", re.IGNORECASE
)


def _scan_class_f2():
    violations = []
    for path, src in _iter_migration_files():
        for m in _CLASS_F2_RE.finditer(src):
            violations.append((str(path), _line_no(src, m.start()), m.group()))
    return violations


_CLASS_F2_BASELINE = 0  # PR #343 / PR #345 已修；main 起点 0（_enable_rls 都用 helper 函数动态生成，static regex 不命中）


def test_class_f2_no_insert_policy_using_clause():
    """类 F-2: `CREATE POLICY ... FOR INSERT ... USING (...)` PG 拒绝
    "only WITH CHECK expression allowed for INSERT"。

    PG semantics:
      USING       适用 SELECT/UPDATE/DELETE（行可见性过滤）
      WITH CHECK  适用 INSERT/UPDATE（新行写入校验）
      INSERT POLICY 必须 WITH CHECK，禁用 USING。

    修法：if action == "INSERT": "WITH CHECK (...)" else "USING (...)"
    （DELETE 也只能 USING — 类 F-3 但 PG 不强 fail，本 linter 暂不查）。
    """
    violations = _scan_class_f2()
    assert len(violations) <= _CLASS_F2_BASELINE, _format_violations(
        "类 F-2 INSERT POLICY 用 USING", violations
    )


# ─── 类 G — 非 IMMUTABLE 函数在 GENERATED / 索引表达式 ─────────────────────

# 严格 STABLE/VOLATILE 函数 — 出现在 GENERATED ALWAYS / 索引表达式中 PG 必拒。
# 注意：EXTRACT 不在此列 — context-dependent（EXTRACT(EPOCH FROM interval) IMMUTABLE
# vs EXTRACT(EPOCH FROM timestamptz) STABLE）。规则会漏掉 EXTRACT 滥用 case，但
# blanket 标 STABLE 会大量 false positive（v377 5 处合法 EXTRACT(EPOCH FROM interval)
# 减法间隔被误捕）。Trade-off：宁漏不错杀。
_NON_IMMUTABLE_FUNCS = (
    "now",
    "current_date",
    "current_time",
    "current_timestamp",
    "age",
    "date_trunc",  # STABLE in PG 16+
    "localtime",
    "localtimestamp",
    "random",
    "clock_timestamp",
    "transaction_timestamp",
    "statement_timestamp",
    "timeofday",
)
_FUNC_PATTERN = "|".join(_NON_IMMUTABLE_FUNCS)
_CLASS_G_GEN_RE = re.compile(
    rf"GENERATED\s+ALWAYS\s+AS\s*\([^)]*?\b({_FUNC_PATTERN})\s*\(",
    re.IGNORECASE | re.DOTALL,
)
# 必须先匹配 `ON <ident>` 才能继续，防止 `[^;]*?` 跨多 op.execute 跨行误捕
# `op.execute("CREATE INDEX ... ON tbl(col)")` 后面的 `sa.text("NOW()")` 列默认值。
_CLASS_G_IDX_RE = re.compile(
    rf"CREATE\s+(?:UNIQUE\s+)?INDEX\s+\S+\s+ON\s+\S+\s*\([^)]*?\b({_FUNC_PATTERN})\s*\(",
    re.IGNORECASE | re.DOTALL,
)


def _scan_class_g():
    violations = []
    for path, src in _iter_migration_files():
        for m in _CLASS_G_GEN_RE.finditer(src):
            violations.append(
                (str(path), _line_no(src, m.start()), f"GENERATED + {m.group(1)}")
            )
        for m in _CLASS_G_IDX_RE.finditer(src):
            violations.append(
                (str(path), _line_no(src, m.start()), f"INDEX + {m.group(1)}")
            )
    return violations


_CLASS_G_BASELINE = 0  # PR #346: regex 进一步去掉 EXTRACT（context-dependent）→ 5 false positive 消除；v378:146 真违例同 PR 修复。归零，linter enforce no new violations。


def test_class_g_no_non_immutable_in_generated_or_index():
    """类 G: GENERATED ALWAYS AS (... STABLE_FUNC ...) STORED 或
    CREATE INDEX ... ((STABLE_FUNC...)) — PG 拒绝。

    PG 要求 STORED 生成列 / 索引表达式必须 IMMUTABLE。
    NOW / CURRENT_DATE / age / date_trunc 等是 STABLE 不是 IMMUTABLE。

    修法 1：改普通列由 service 维护（Phase G 修 v378 模式）。
    修法 2：改裸列索引 + 查询侧范围过滤（Phase G 修 v264 模式）。
    修法 3：用真 IMMUTABLE 函数（如 lower/upper/btrim）。
    """
    violations = _scan_class_g()
    assert len(violations) <= _CLASS_G_BASELINE, _format_violations(
        "类 G 非 IMMUTABLE 函数表达式", violations
    )


# ─── 元测试：所有 baseline 与磁盘真实违例数对齐 ──────────────────────────

def test_class_a_baseline_matches_disk_state_or_below():
    """sanity: baseline 不应远小于真实违例数（说明修复达成 ratchet 但未更新 baseline）。

    若真实数 < baseline，提示 ratchet down。
    """
    actual = len(_scan_class_a())
    if actual < _CLASS_A_BASELINE:
        # 信息性 — 不 fail，但警示 baseline 可下降
        print(
            f"\n[ratchet hint] 类 A baseline = {_CLASS_A_BASELINE}, "
            f"实际 = {actual}; 建议在下个 PR 中下调 baseline 到 {actual}。"
        )
