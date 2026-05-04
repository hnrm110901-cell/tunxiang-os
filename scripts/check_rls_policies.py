#!/usr/bin/env python3
"""RLS 策略安全检查脚本

连接数据库，查询 pg_policies 视图，检查以下问题：
  1. 业务表是否启用了 RLS（ENABLE ROW LEVEL SECURITY）
  2. 是否使用了 FORCE ROW LEVEL SECURITY（防止表 owner 绕过）
  3. 策略中是否使用了正确的变量名（app.tenant_id，禁止 app.current_store_id 等）
  4. 策略中是否有 NULLIF NULL guard（禁止 IS NULL 绕过）
  5. 是否覆盖了四种操作（SELECT / INSERT / UPDATE / DELETE）

使用方式：
  python scripts/check_rls_policies.py                       # 人类可读报告
  python scripts/check_rls_policies.py --json                # JSON 供 Go/No-Go 消费
  python scripts/check_rls_policies.py --strict              # 仅 clean 时 exit 0

Exit codes:
  0  = clean（无问题 / strict 模式通过）
  1  = 发现安全问题
  2  = DB 连接失败（无法验证）
  3  = 其他异常（参数错误 / 依赖缺失）

环境变量：
  DATABASE_URL — PostgreSQL 连接串，兼容多种 scheme：
    postgresql://user:pass@host:5432/db
    postgres://user:pass@host:5432/db
    postgresql+asyncpg://user:pass@host:5432/db  ← SQLAlchemy 格式自动 normalize

依赖：
  pip install asyncpg python-dotenv
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass, field

try:
    import asyncpg
    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv 可选


# ─────────────────────────────────────────────────────────────────────────────
# Exit codes
# ─────────────────────────────────────────────────────────────────────────────

EXIT_CLEAN = 0
EXIT_ISSUES_FOUND = 1
EXIT_DB_CONNECT_FAIL = 2
EXIT_CONFIG_ERROR = 3


# ─────────────────────────────────────────────────────────────────────────────
# 配置
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/tunxiang_db"

# 正确的 session 变量名
CORRECT_VAR = "app.tenant_id"

# 禁止使用的变量名
FORBIDDEN_VARS = [
    "app.current_store_id",
    "app.current_tenant",
    "app.store_id",
    "app.tenant",
]

# 必须覆盖的四种操作
REQUIRED_CMDS = {"SELECT", "INSERT", "UPDATE", "DELETE"}

# 所有业务表（需要 RLS 保护的表，排除系统表和纯配置表）
BUSINESS_TABLES = [
    # 核心交易表
    "orders", "order_items", "payments", "refunds", "settlements",
    "payment_records", "reconciliation_batches", "reconciliation_diffs",
    "tri_reconciliation_records", "store_daily_settlements", "payment_fees",
    # 客户/会员
    "customers", "member_transactions",
    # 门店/组织
    "stores", "employees",
    # 菜品/BOM
    "dishes", "dish_categories", "dish_ingredients",
    "bom_templates", "bom_items",
    "dish_practices", "dish_combos",
    # 库存
    "ingredient_masters", "ingredients", "ingredient_transactions",
    "waste_events", "suppliers", "supply_orders",
    # 预约/宴会
    "reservations", "queues", "banquet_halls", "banquet_leads",
    "banquet_orders", "banquet_contracts", "menu_packages", "banquet_checklists",
    "banquet_proposals", "banquet_quotations", "banquet_feedbacks", "banquet_cases",
    # HR
    "attendance_rules", "clock_records", "daily_attendance",
    "payroll_batches", "payroll_items", "leave_requests",
    "leave_balances", "settlement_records",
    # KDS
    "production_depts", "dish_dept_mappings", "kds_tasks",
    # 运营
    "tables", "shift_handovers", "receipt_templates", "receipt_logs",
    "daily_ops_flows", "daily_ops_nodes", "agent_decision_logs",
    "table_production_plans", "cook_time_baselines",
    "dispatch_rules", "shift_configs",
    # 通知/任务
    "notifications", "notification_preferences",
    "training_courses", "training_enrollments",
    "service_feedbacks", "complaints", "tasks",
    # 增长/会员
    "brand_groups", "store_brand_mappings",
    "referral_campaigns", "referral_records",
    "journey_instances", "journey_steps",
    "premium_cards", "premium_card_tiers", "premium_card_records",
    "points_mall_items", "points_exchange_records",
    "attribution_touchpoints", "attribution_conversions",
    # AB 测试（Sprint G v290）
    "ab_experiments", "ab_experiment_arms",
    "ab_experiment_assignments", "ab_experiment_events",
    # 外卖 canonical / publish / dispute（Sprint E v285-v288）
    "canonical_delivery_orders", "canonical_delivery_items",
    "dish_publish_registry", "dish_publish_tasks",
    "xiaohongshu_shop_bindings", "xiaohongshu_verify_events",
    "delivery_disputes", "delivery_dispute_messages",
    # D 批次 AI 分析（Sprint D v278-v281）
    "dish_pricing_suggestions",
    "cost_root_cause_analyses",
    "salary_anomaly_analyses",
    "budget_forecast_analyses",
    "rfm_outreach_campaigns",
    "campaign_roi_forecasts",
    # 外卖（老）
    "delivery_zones", "delivery_time_configs", "delivery_fee_rules",
    # 服务铃
    "service_bell_records",
    # 经营诊断
    "business_diagnoses", "diagnosis_items",
    # 巡台
    "patrol_logs",
]


# ─────────────────────────────────────────────────────────────────────────────
# DSN 规范化
# ─────────────────────────────────────────────────────────────────────────────

_SQLALCHEMY_DIALECT_RE = re.compile(r"^(postgres(?:ql)?)\+[a-z0-9_]+://", re.IGNORECASE)


def normalize_dsn(dsn: str) -> str:
    """把 SQLAlchemy 风格 DSN 转成 asyncpg 可识别的形式

    输入 → 输出：
      postgresql+asyncpg://...  → postgresql://...
      postgresql+psycopg2://... → postgresql://...
      postgres+psycopg://...    → postgres://...
      postgresql://...          → postgresql://... (不变)
      postgres://...            → postgres://... (不变)
    """
    if not dsn:
        return dsn
    match = _SQLALCHEMY_DIALECT_RE.match(dsn)
    if match:
        scheme = match.group(1).lower()
        # 把 scheme+driver:// 替换为 scheme://
        return re.sub(
            r"^postgres(?:ql)?\+[a-z0-9_]+://",
            f"{scheme}://",
            dsn,
            count=1,
            flags=re.IGNORECASE,
        )
    return dsn


def redact_dsn(dsn: str) -> str:
    """脱敏 DSN 的密码部分（用于日志打印）"""
    # postgresql://user:pass@host:port/db → postgresql://user:***@host:port/db
    return re.sub(
        r"(://[^:/]+:)[^@]+(@)",
        r"\1***\2",
        dsn,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class PolicyRecord:
    table_name: str
    policy_name: str
    cmd: str           # SELECT / INSERT / UPDATE / DELETE / ALL
    using_clause: str | None
    with_check_clause: str | None


@dataclass
class TableRLSStatus:
    table_name: str
    exists_in_db: bool = False  # 表是否存在于 DB 中
    rls_enabled: bool = False
    force_rls: bool = False
    policies: list[PolicyRecord] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    @property
    def has_issues(self) -> bool:
        return len(self.issues) > 0

    @property
    def covered_cmds(self) -> set[str]:
        cmds: set[str] = set()
        for p in self.policies:
            if p.cmd == "ALL":
                cmds.update(REQUIRED_CMDS)
            else:
                cmds.add(p.cmd)
        return cmds


# ─────────────────────────────────────────────────────────────────────────────
# 检查逻辑
# ─────────────────────────────────────────────────────────────────────────────


def _check_clause(
    clause: str | None, table: str, policy: str, clause_type: str
) -> list[str]:
    """检查单个 USING 或 WITH CHECK 子句的安全性。"""
    issues: list[str] = []
    if not clause:
        return issues

    # 检查是否使用了禁止的变量名
    for bad_var in FORBIDDEN_VARS:
        # 精确匹配：防止 "app.tenant" 误匹配 "app.tenant_id"（子串误判）
        if re.search(r"(?<!['\w])" + re.escape(bad_var) + r"(?!['\w_])", clause):
            issues.append(
                f"[CRITICAL] {table}.{policy} {clause_type} 使用了错误变量 "
                f"'{bad_var}'，应改为 '{CORRECT_VAR}'"
            )

    # 检查是否使用了正确变量名（如果没有禁止变量但也没有正确变量）
    if CORRECT_VAR not in clause and not any(
        re.search(r"(?<!['\w])" + re.escape(v) + r"(?!['\w_])", clause) for v in FORBIDDEN_VARS
    ):
        issues.append(
            f"[HIGH] {table}.{policy} {clause_type} 未使用 '{CORRECT_VAR}'，"
            f"请确认 session 变量设置"
        )

    # 检查是否有 IS NULL 绕过（允许未认证请求通过）
    if re.search(r"current_setting\s*\(.*?\)\s+IS\s+NULL", clause, re.IGNORECASE):
        issues.append(
            f"[CRITICAL] {table}.{policy} {clause_type} 包含 IS NULL 条件分支，"
            f"允许未认证请求绕过 RLS"
        )

    # 检查是否有 NULLIF guard（推荐模式）
    has_nullif = "NULLIF" in clause.upper()
    # 检查是否有旧三段条件（可接受但非标准）
    has_is_not_null = "IS NOT NULL" in clause.upper() and "<> ''" in clause
    # 检查是否完全没有 NULL 保护
    if not has_nullif and not has_is_not_null:
        # 检查是否使用了不带 true 参数的 current_setting
        if re.search(
            r"current_setting\s*\(\s*'app\.tenant_id'\s*\)", clause
        ):
            issues.append(
                f"[HIGH] {table}.{policy} {clause_type} 使用 current_setting 时"
                f"缺少 'true' 参数，且无 NULLIF/IS NOT NULL guard"
            )
        elif CORRECT_VAR in clause:
            issues.append(
                f"[MEDIUM] {table}.{policy} {clause_type} 缺少 NULLIF NULL guard，"
                f"建议改为: NULLIF(current_setting('app.tenant_id', true), '')::UUID"
            )

    return issues


def check_table_rls(status: TableRLSStatus) -> None:
    """对单个表执行完整的 RLS 安全检查，将问题写入 status.issues。"""
    if not status.exists_in_db:
        # 表不存在 — 不报问题（可能 migration 未跑）
        return

    # 检查 RLS 是否启用
    if not status.rls_enabled:
        status.issues.append(
            f"[CRITICAL] {status.table_name} 未启用 ROW LEVEL SECURITY"
        )
        return

    # 检查 FORCE RLS
    if not status.force_rls:
        status.issues.append(
            f"[HIGH] {status.table_name} 未设置 FORCE ROW LEVEL SECURITY，"
            f"表 owner 可绕过所有 RLS 策略"
        )

    # 检查是否有策略
    if not status.policies:
        status.issues.append(
            f"[CRITICAL] {status.table_name} 已启用 RLS 但无任何策略"
        )
        return

    # 检查操作覆盖率
    covered = status.covered_cmds
    missing = REQUIRED_CMDS - covered
    if missing:
        status.issues.append(
            f"[HIGH] {status.table_name} 缺少以下操作的 RLS 策略: "
            f"{', '.join(sorted(missing))}"
        )

    # 检查每条策略的子句安全性
    for policy in status.policies:
        if policy.using_clause:
            status.issues.extend(
                _check_clause(
                    policy.using_clause, status.table_name,
                    policy.policy_name, "USING",
                )
            )
        if policy.with_check_clause:
            status.issues.extend(
                _check_clause(
                    policy.with_check_clause, status.table_name,
                    policy.policy_name, "WITH CHECK",
                )
            )


# ─────────────────────────────────────────────────────────────────────────────
# 数据库查询
# ─────────────────────────────────────────────────────────────────────────────


async def fetch_rls_data(
    conn: "asyncpg.Connection",
) -> dict[str, TableRLSStatus]:
    """从 pg_policies 和 pg_tables 获取 RLS 状态数据。"""
    statuses: dict[str, TableRLSStatus] = {}
    for table in BUSINESS_TABLES:
        statuses[table] = TableRLSStatus(table_name=table)

    # 查询所有 public schema 的表（用于判断表是否存在）
    existing = await conn.fetch("""
        SELECT c.relname AS table_name
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
          AND c.relname = ANY($1)
    """, BUSINESS_TABLES)

    for row in existing:
        name = row["table_name"]
        if name in statuses:
            statuses[name].exists_in_db = True

    # 查询 RLS 启用状态
    rls_rows = await conn.fetch("""
        SELECT
            c.relname AS table_name,
            c.relrowsecurity AS rls_enabled,
            c.relforcerowsecurity AS force_rls
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
          AND c.relname = ANY($1)
    """, BUSINESS_TABLES)

    for row in rls_rows:
        name = row["table_name"]
        if name in statuses:
            statuses[name].rls_enabled = row["rls_enabled"]
            statuses[name].force_rls = row["force_rls"]

    # 查询 RLS 策略
    policy_rows = await conn.fetch("""
        SELECT
            tablename AS table_name,
            policyname AS policy_name,
            cmd,
            qual AS using_clause,
            with_check AS with_check_clause
        FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = ANY($1)
        ORDER BY tablename, policyname
    """, BUSINESS_TABLES)

    for row in policy_rows:
        name = row["table_name"]
        if name in statuses:
            statuses[name].policies.append(PolicyRecord(
                table_name=name,
                policy_name=row["policy_name"],
                cmd=row["cmd"],
                using_clause=row["using_clause"],
                with_check_clause=row["with_check_clause"],
            ))

    return statuses


# ─────────────────────────────────────────────────────────────────────────────
# 报告输出
# ─────────────────────────────────────────────────────────────────────────────


def _count_issues(statuses: dict[str, TableRLSStatus]) -> dict[str, int]:
    """按严重度统计问题"""
    critical = 0
    high = 0
    medium = 0
    for status in statuses.values():
        for issue in status.issues:
            if "[CRITICAL]" in issue:
                critical += 1
            elif "[HIGH]" in issue:
                high += 1
            elif "[MEDIUM]" in issue:
                medium += 1
    return {
        "critical": critical,
        "high": high,
        "medium": medium,
        "total": critical + high + medium,
    }


def print_text_report(statuses: dict[str, TableRLSStatus]) -> int:
    """打印人类可读报告，返回发现的问题总数。"""
    for status in statuses.values():
        check_table_rls(status)

    counts = _count_issues(statuses)
    problem_tables = [s for s in statuses.values() if s.has_issues]
    ok_tables = [s for s in statuses.values() if not s.has_issues and s.exists_in_db]
    missing_tables = [s for s in statuses.values() if not s.exists_in_db]

    print()
    print("=" * 70)
    print("  屯象OS RLS 策略安全检查报告")
    from datetime import datetime
    print(f"  检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    print()
    print("【检查汇总】")
    print(f"  总检查表数:      {len(statuses)}")
    print(f"  DB 中存在:        {len([s for s in statuses.values() if s.exists_in_db])}")
    print(f"  DB 中缺失:        {len(missing_tables)}（可能 migration 未跑）")
    print(f"  无问题表数:      {len(ok_tables)}")
    print(f"  有问题表数:      {len(problem_tables)}")
    print(f"  CRITICAL 问题:   {counts['critical']}")
    print(f"  HIGH     问题:   {counts['high']}")
    print(f"  MEDIUM   问题:   {counts['medium']}")

    if missing_tables:
        print()
        print("【DB 中缺失的表（不算违规）】")
        names = sorted(s.table_name for s in missing_tables)
        for i in range(0, len(names), 5):
            print("  " + "  ".join(names[i:i+5]))

    if problem_tables:
        print()
        print("【问题详情】")
        for status in sorted(problem_tables, key=lambda s: s.table_name):
            print()
            print(f"  表: {status.table_name}")
            print(f"    RLS 已启用: {'是' if status.rls_enabled else '否'}")
            print(f"    FORCE RLS:  {'是' if status.force_rls else '否'}")
            print(f"    策略数量:   {len(status.policies)}")
            if status.policies:
                covered = status.covered_cmds
                print(f"    覆盖操作:   {', '.join(sorted(covered)) or '无'}")
            for issue in status.issues:
                print(f"    {issue}")

    if ok_tables:
        print()
        print("【检查通过的表】")
        names = sorted(s.table_name for s in ok_tables)
        for i in range(0, len(names), 5):
            print("  " + "  ".join(names[i:i+5]))

    print()
    print("=" * 70)
    if counts["total"] == 0:
        print("  结论: 所有表 RLS 策略检查通过，无安全问题")
    else:
        print(f"  结论: 发现 {counts['total']} 个安全问题")
        if counts["critical"] > 0:
            print(f"  ACTION REQUIRED: {counts['critical']} 个 CRITICAL 问题必须修复")
    print("=" * 70)
    print()

    return counts["total"]


def print_json_report(
    statuses: dict[str, TableRLSStatus], database_url: str
) -> int:
    """打印 JSON 报告（供 CI / Go/No-Go 消费），返回问题总数"""
    for status in statuses.values():
        check_table_rls(status)

    counts = _count_issues(statuses)
    problem_tables = [s for s in statuses.values() if s.has_issues]
    ok_tables = [s for s in statuses.values() if not s.has_issues and s.exists_in_db]
    missing_tables = [s for s in statuses.values() if not s.exists_in_db]

    payload = {
        "database_url": redact_dsn(database_url),
        "summary": {
            "total_tables": len(statuses),
            "existing_in_db": sum(1 for s in statuses.values() if s.exists_in_db),
            "missing_in_db": len(missing_tables),
            "ok_count": len(ok_tables),
            "issue_tables": len(problem_tables),
            **counts,
            "passed": counts["total"] == 0,
        },
        "issues": [
            {
                "table": s.table_name,
                "rls_enabled": s.rls_enabled,
                "force_rls": s.force_rls,
                "policy_count": len(s.policies),
                "covered_cmds": sorted(s.covered_cmds),
                "issues": s.issues,
            }
            for s in sorted(problem_tables, key=lambda s: s.table_name)
        ],
        "missing_tables": sorted(s.table_name for s in missing_tables),
        "ok_tables": sorted(s.table_name for s in ok_tables),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return counts["total"]


# ─────────────────────────────────────────────────────────────────────────────
# 主程序
# ─────────────────────────────────────────────────────────────────────────────


async def run_audit(args: argparse.Namespace) -> int:
    """返回 exit code"""
    if not HAS_ASYNCPG:
        _print_err(
            "asyncpg 未安装；pip install asyncpg 后重试",
            use_json=args.json,
        )
        return EXIT_CONFIG_ERROR

    database_url = args.database_url or os.environ.get(
        "DATABASE_URL", DEFAULT_DATABASE_URL
    )
    normalized = normalize_dsn(database_url)
    redacted = redact_dsn(normalized)

    if not args.json:
        print(f"连接数据库: {redacted}", file=sys.stderr)

    try:
        conn = await asyncpg.connect(normalized)
    except Exception as exc:  # noqa: BLE001 — 所有连接异常统一处理
        _print_err(
            f"数据库连接失败: {exc}\n"
            f"请确认：\n"
            f"  1. DATABASE_URL 环境变量已正确设置（当前: {redacted}）\n"
            f"  2. 数据库服务正在运行\n"
            f"  3. 网络/防火墙允许连接",
            use_json=args.json,
            database_url=redacted,
        )
        return EXIT_DB_CONNECT_FAIL

    try:
        statuses = await fetch_rls_data(conn)
    finally:
        await conn.close()

    if args.json:
        issue_count = print_json_report(statuses, database_url)
    else:
        issue_count = print_text_report(statuses)

    if issue_count == 0:
        return EXIT_CLEAN
    if args.strict:
        return EXIT_ISSUES_FOUND
    # 非 strict：MEDIUM 问题不阻塞（只 CRITICAL + HIGH 算失败）
    counts = _count_issues(statuses)
    critical_high = counts["critical"] + counts["high"]
    if critical_high > 0:
        return EXIT_ISSUES_FOUND
    return EXIT_CLEAN


def _print_err(
    msg: str,
    *,
    use_json: bool = False,
    database_url: str | None = None,
) -> None:
    """按输出格式打印错误"""
    if use_json:
        print(json.dumps({
            "error": msg,
            "database_url": database_url,
            "summary": {
                "passed": False,
                "total": 0,
                "error": True,
            },
        }, ensure_ascii=False, indent=2))
    else:
        print(f"ERROR: {msg}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="屯象OS RLS 策略安全检查",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="PostgreSQL DSN（默认读 env DATABASE_URL）；"
             "兼容 postgresql+asyncpg:// 等 SQLAlchemy scheme",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="JSON 输出（CI 消费）",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="严格模式：任何 MEDIUM+ 问题都返回非零",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return asyncio.run(run_audit(args))
    except KeyboardInterrupt:
        return EXIT_CONFIG_ERROR


if __name__ == "__main__":
    sys.exit(main())
