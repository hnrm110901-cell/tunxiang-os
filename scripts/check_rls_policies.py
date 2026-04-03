#!/usr/bin/env python3
"""RLS 策略安全检查脚本

连接数据库，查询 pg_policies 视图，检查以下问题：
1. 业务表是否启用了 RLS（ENABLE ROW LEVEL SECURITY）
2. 是否使用了 FORCE ROW LEVEL SECURITY（防止表 owner 绕过）
3. 策略中是否使用了正确的变量名（app.tenant_id，禁止 app.current_store_id 等）
4. 策略中是否有 NULLIF NULL guard（禁止 IS NULL 绕过）
5. 是否覆盖了四种操作（SELECT / INSERT / UPDATE / DELETE）

使用方式：
  python scripts/check_rls_policies.py

环境变量（可通过 .env 或命令行设置）：
  DATABASE_URL — PostgreSQL 连接串，例如：
    postgresql://user:pass@localhost:5432/tunxiang_db

依赖：
  pip install asyncpg python-dotenv
"""

import asyncio
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any

try:
    import asyncpg
except ImportError:
    print("ERROR: asyncpg 未安装，请执行: pip install asyncpg")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv 可选

# ─────────────────────────────────────────────────────────────────────────────
# 配置
# ─────────────────────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/tunxiang_db",
)

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
    # AB 测试
    "ab_tests", "ab_test_assignments",
    # 外卖
    "delivery_zones", "delivery_time_configs", "delivery_fee_rules",
    # 服务铃
    "service_bell_records",
    # 经营诊断
    "business_diagnoses", "diagnosis_items",
    # 巡台
    "patrol_logs",
]


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
def _check_clause(clause: str | None, table: str, policy: str, clause_type: str) -> list[str]:
    """检查单个 USING 或 WITH CHECK 子句的安全性。"""
    issues: list[str] = []
    if not clause:
        return issues

    # 检查是否使用了禁止的变量名
    for bad_var in FORBIDDEN_VARS:
        if bad_var in clause:
            issues.append(
                f"[CRITICAL] {table}.{policy} {clause_type} 使用了错误变量 '{bad_var}'，"
                f"应改为 '{CORRECT_VAR}'"
            )

    # 检查是否使用了正确变量名（如果没有禁止变量但也没有正确变量）
    if CORRECT_VAR not in clause and not any(v in clause for v in FORBIDDEN_VARS):
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
        if re.search(r"current_setting\s*\(\s*'app\.tenant_id'\s*\)", clause):
            issues.append(
                f"[HIGH] {table}.{policy} {clause_type} 使用 current_setting 时缺少 'true' 参数，"
                f"且无 NULLIF/IS NOT NULL guard，变量未设置时可能抛出异常或绕过 RLS"
            )
        elif CORRECT_VAR in clause:
            issues.append(
                f"[MEDIUM] {table}.{policy} {clause_type} 缺少 NULLIF NULL guard，"
                f"建议改为: NULLIF(current_setting('app.tenant_id', true), '')::UUID"
            )

    return issues


def check_table_rls(status: TableRLSStatus) -> None:
    """对单个表执行完整的 RLS 安全检查，将问题写入 status.issues。"""

    # 检查 RLS 是否启用
    if not status.rls_enabled:
        status.issues.append(f"[CRITICAL] {status.table_name} 未启用 ROW LEVEL SECURITY")
        return  # 未启用 RLS 则无策略可检查

    # 检查 FORCE RLS
    if not status.force_rls:
        status.issues.append(
            f"[HIGH] {status.table_name} 未设置 FORCE ROW LEVEL SECURITY，"
            f"表 owner 可绕过所有 RLS 策略"
        )

    # 检查是否有策略
    if not status.policies:
        status.issues.append(f"[CRITICAL] {status.table_name} 已启用 RLS 但无任何策略，"
                             f"所有操作将被拒绝（安全但可能影响正常功能）")
        return

    # 检查操作覆盖率
    covered = status.covered_cmds
    missing = REQUIRED_CMDS - covered
    if missing:
        status.issues.append(
            f"[HIGH] {status.table_name} 缺少以下操作的 RLS 策略: "
            f"{', '.join(sorted(missing))}，这些操作无 RLS 限制"
        )

    # 检查每条策略的子句安全性
    for policy in status.policies:
        if policy.using_clause:
            status.issues.extend(
                _check_clause(policy.using_clause, status.table_name,
                              policy.policy_name, "USING")
            )
        if policy.with_check_clause:
            status.issues.extend(
                _check_clause(policy.with_check_clause, status.table_name,
                              policy.policy_name, "WITH CHECK")
            )


# ─────────────────────────────────────────────────────────────────────────────
# 数据库查询
# ─────────────────────────────────────────────────────────────────────────────
async def fetch_rls_data(conn: "asyncpg.Connection") -> dict[str, TableRLSStatus]:
    """从 pg_policies 和 pg_tables 获取 RLS 状态数据。"""
    statuses: dict[str, TableRLSStatus] = {}

    # 初始化所有需要检查的表
    for table in BUSINESS_TABLES:
        statuses[table] = TableRLSStatus(table_name=table)

    # 查询 RLS 启用状态（pg_class.relrowsecurity / relforcerowsecurity）
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

    # 查询 RLS 策略（pg_policies 视图）
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
def print_report(statuses: dict[str, TableRLSStatus]) -> int:
    """打印检查报告，返回发现的问题总数。"""
    critical_count = 0
    high_count = 0
    medium_count = 0
    problem_tables: list[TableRLSStatus] = []
    ok_tables: list[TableRLSStatus] = []
    missing_tables: list[str] = []

    for table_name, status in statuses.items():
        # 检查表是否存在于数据库（rls_enabled 默认 False，但我们需要区分"不存在"和"未启用"）
        check_table_rls(status)

        if status.has_issues:
            problem_tables.append(status)
            for issue in status.issues:
                if "[CRITICAL]" in issue:
                    critical_count += 1
                elif "[HIGH]" in issue:
                    high_count += 1
                elif "[MEDIUM]" in issue:
                    medium_count += 1
        else:
            ok_tables.append(status)

    # 检查表是否在数据库中不存在（可能尚未迁移）
    all_checked = set(statuses.keys())
    # 注：这里无法区分"不存在"和"rls_enabled=False"，后者已被 check 捕获

    total_issues = critical_count + high_count + medium_count

    print()
    print("=" * 70)
    print("  屯象OS RLS 策略安全检查报告")
    print(f"  检查时间: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # 汇总
    print()
    print("【检查汇总】")
    print(f"  总检查表数:  {len(statuses)}")
    print(f"  无问题表数:  {len(ok_tables)}")
    print(f"  有问题表数:  {len(problem_tables)}")
    print(f"  CRITICAL 问题: {critical_count}")
    print(f"  HIGH     问题: {high_count}")
    print(f"  MEDIUM   问题: {medium_count}")

    # 有问题的表
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

    # 正常表列表
    if ok_tables:
        print()
        print("【检查通过的表】")
        names = sorted(s.table_name for s in ok_tables)
        for i in range(0, len(names), 5):
            print("  " + "  ".join(names[i:i+5]))

    # 结论
    print()
    print("=" * 70)
    if total_issues == 0:
        print("  结论: 所有表 RLS 策略检查通过，无安全问题")
    else:
        print(f"  结论: 发现 {total_issues} 个安全问题，请立即处理 CRITICAL 和 HIGH 级别")
        if critical_count > 0:
            print(f"  ACTION REQUIRED: {critical_count} 个 CRITICAL 问题必须在发布前修复")
    print("=" * 70)
    print()

    return total_issues


# ─────────────────────────────────────────────────────────────────────────────
# 主程序
# ─────────────────────────────────────────────────────────────────────────────
async def main() -> None:
    print(f"连接数据库: {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else DATABASE_URL}")

    try:
        conn = await asyncpg.connect(DATABASE_URL)
    except Exception as exc:
        print(f"ERROR: 数据库连接失败: {exc}")
        print()
        print("请确认：")
        print("  1. DATABASE_URL 环境变量已正确设置")
        print("  2. 数据库服务正在运行")
        print("  3. 网络/防火墙允许连接")
        sys.exit(1)

    try:
        statuses = await fetch_rls_data(conn)
        issue_count = print_report(statuses)
    finally:
        await conn.close()

    sys.exit(0 if issue_count == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
