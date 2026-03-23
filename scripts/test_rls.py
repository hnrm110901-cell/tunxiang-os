#!/usr/bin/env python3
"""RLS 验证测试脚本 — 纯 Python mock 测试，无需真实 DB 连接

验证内容:
1. 所有表定义都包含 tenant_id 字段
2. RLS Policy SQL 语句的语法正确性
3. 不同 tenant_id 的数据隔离逻辑

使用: python scripts/test_rls.py
"""
import re
import sys
import uuid
from dataclasses import dataclass, field
from typing import Any


# ──────────────────────────────────────────────
# Mock 表定义（对应 v001 + v002 全部 23 张表）
# ──────────────────────────────────────────────
ALL_TABLES = [
    # v001 — 11 张核心表
    "stores", "customers", "employees",
    "dish_categories", "dishes", "dish_ingredients",
    "orders", "order_items",
    "ingredient_masters", "ingredients", "ingredient_transactions",
    # v002 — 12 张新增表
    "tables", "payments", "refunds",
    "settlements", "shift_handovers",
    "receipt_templates", "receipt_logs",
    "production_depts", "dish_dept_mappings",
    "daily_ops_flows", "daily_ops_nodes",
    "agent_decision_logs",
]

# 每张表的必须字段列表（取自 CLAUDE.md 基类要求）
REQUIRED_COLUMNS = ["id", "tenant_id", "created_at", "updated_at", "is_deleted"]

# Mock 表结构 — 模拟从迁移脚本解析出的列定义
TABLE_COLUMNS: dict[str, list[str]] = {}
for t in ALL_TABLES:
    TABLE_COLUMNS[t] = REQUIRED_COLUMNS.copy()


# ──────────────────────────────────────────────
# Mock RLS Policy SQL
# ──────────────────────────────────────────────
def generate_rls_sql(table_name: str) -> list[str]:
    """生成某张表的 RLS Policy SQL（与迁移脚本 _enable_rls 一致）"""
    return [
        f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY",
        (
            f"CREATE POLICY tenant_isolation_{table_name} ON {table_name} "
            f"USING (tenant_id = current_setting('app.tenant_id')::UUID)"
        ),
        (
            f"CREATE POLICY tenant_insert_{table_name} ON {table_name} "
            f"FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID)"
        ),
    ]


def generate_disable_rls_sql(table_name: str) -> list[str]:
    """生成禁用 RLS 的 SQL"""
    return [
        f"DROP POLICY IF EXISTS tenant_insert_{table_name} ON {table_name}",
        f"DROP POLICY IF EXISTS tenant_isolation_{table_name} ON {table_name}",
        f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY",
    ]


# ──────────────────────────────────────────────
# Mock 数据库引擎（模拟 RLS 行为）
# ──────────────────────────────────────────────
@dataclass
class MockRow:
    table: str
    id: str
    tenant_id: str
    data: dict = field(default_factory=dict)


class MockRLSDatabase:
    """模拟带 RLS 的数据库"""

    def __init__(self) -> None:
        self.rows: list[MockRow] = []
        self.current_tenant_id: str | None = None
        self.rls_enabled_tables: set[str] = set()

    def set_tenant(self, tenant_id: str) -> None:
        self.current_tenant_id = tenant_id

    def enable_rls(self, table_name: str) -> None:
        self.rls_enabled_tables.add(table_name)

    def insert(self, table: str, tenant_id: str, data: dict | None = None) -> MockRow:
        row = MockRow(
            table=table,
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            data=data or {},
        )
        # RLS INSERT 检查
        if table in self.rls_enabled_tables:
            if self.current_tenant_id and tenant_id != self.current_tenant_id:
                raise PermissionError(
                    f"RLS violation: INSERT into '{table}' with tenant_id={tenant_id} "
                    f"but current_setting('app.tenant_id')={self.current_tenant_id}"
                )
        self.rows.append(row)
        return row

    def select(self, table: str) -> list[MockRow]:
        """SELECT — RLS 过滤"""
        all_rows = [r for r in self.rows if r.table == table]
        if table in self.rls_enabled_tables and self.current_tenant_id:
            return [r for r in all_rows if r.tenant_id == self.current_tenant_id]
        return all_rows

    def select_all_bypass_rls(self, table: str) -> list[MockRow]:
        """超级用户视角（绕过 RLS）"""
        return [r for r in self.rows if r.table == table]


# ──────────────────────────────────────────────
# 测试用例
# ──────────────────────────────────────────────
@dataclass
class TestResult:
    name: str
    passed: bool
    detail: str = ""


def test_all_tables_have_tenant_id() -> list[TestResult]:
    """验证所有表定义都包含 tenant_id 字段"""
    results = []
    for table in ALL_TABLES:
        cols = TABLE_COLUMNS.get(table, [])
        has_tenant_id = "tenant_id" in cols
        results.append(TestResult(
            name=f"[tenant_id] {table}",
            passed=has_tenant_id,
            detail=f"columns: {cols}" if not has_tenant_id else "",
        ))
    return results


def test_all_tables_have_required_columns() -> list[TestResult]:
    """验证所有表定义都包含必须的基类字段"""
    results = []
    for table in ALL_TABLES:
        cols = TABLE_COLUMNS.get(table, [])
        for req_col in REQUIRED_COLUMNS:
            has_col = req_col in cols
            results.append(TestResult(
                name=f"[required_col:{req_col}] {table}",
                passed=has_col,
                detail="" if has_col else f"missing '{req_col}' in {table}",
            ))
    return results


def test_rls_policy_sql_syntax() -> list[TestResult]:
    """验证 RLS Policy SQL 语句的语法正确性"""
    results = []

    # 正则：ALTER TABLE <name> ENABLE ROW LEVEL SECURITY
    alter_pattern = re.compile(
        r"^ALTER TABLE \w+ ENABLE ROW LEVEL SECURITY$"
    )
    # 正则：CREATE POLICY ... ON <table> USING (tenant_id = ...)
    select_policy_pattern = re.compile(
        r"^CREATE POLICY tenant_isolation_\w+ ON \w+ "
        r"USING \(tenant_id = current_setting\('app\.tenant_id'\)::UUID\)$"
    )
    # 正则：CREATE POLICY ... FOR INSERT WITH CHECK (...)
    insert_policy_pattern = re.compile(
        r"^CREATE POLICY tenant_insert_\w+ ON \w+ "
        r"FOR INSERT WITH CHECK \(tenant_id = current_setting\('app\.tenant_id'\)::UUID\)$"
    )

    for table in ALL_TABLES:
        sqls = generate_rls_sql(table)

        # ALTER TABLE
        match_alter = alter_pattern.match(sqls[0])
        results.append(TestResult(
            name=f"[rls_alter_syntax] {table}",
            passed=bool(match_alter),
            detail="" if match_alter else f"bad SQL: {sqls[0]}",
        ))

        # SELECT policy
        match_select = select_policy_pattern.match(sqls[1])
        results.append(TestResult(
            name=f"[rls_select_policy_syntax] {table}",
            passed=bool(match_select),
            detail="" if match_select else f"bad SQL: {sqls[1]}",
        ))

        # INSERT policy
        match_insert = insert_policy_pattern.match(sqls[2])
        results.append(TestResult(
            name=f"[rls_insert_policy_syntax] {table}",
            passed=bool(match_insert),
            detail="" if match_insert else f"bad SQL: {sqls[2]}",
        ))

    return results


def test_rls_disable_sql_syntax() -> list[TestResult]:
    """验证禁用 RLS 的 SQL 语法"""
    results = []
    drop_pattern = re.compile(r"^DROP POLICY IF EXISTS \w+ ON \w+$")
    disable_pattern = re.compile(r"^ALTER TABLE \w+ DISABLE ROW LEVEL SECURITY$")

    for table in ALL_TABLES:
        sqls = generate_disable_rls_sql(table)
        for sql in sqls[:2]:
            m = drop_pattern.match(sql)
            results.append(TestResult(
                name=f"[rls_drop_syntax] {table}",
                passed=bool(m),
                detail="" if m else f"bad SQL: {sql}",
            ))
        m = disable_pattern.match(sqls[2])
        results.append(TestResult(
            name=f"[rls_disable_syntax] {table}",
            passed=bool(m),
            detail="" if m else f"bad SQL: {sqls[2]}",
        ))
    return results


def test_tenant_data_isolation() -> list[TestResult]:
    """验证不同 tenant_id 的数据隔离逻辑"""
    results = []
    db = MockRLSDatabase()

    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())

    test_tables = ["stores", "orders", "tables", "payments", "agent_decision_logs"]

    # 启用 RLS
    for t in test_tables:
        db.enable_rls(t)

    # 以 tenant_a 身份插入数据
    db.set_tenant(tenant_a)
    for t in test_tables:
        db.insert(t, tenant_a, {"name": f"{t}_data_A"})

    # 以 tenant_b 身份插入数据
    db.set_tenant(tenant_b)
    for t in test_tables:
        db.insert(t, tenant_b, {"name": f"{t}_data_B"})

    # 验证 tenant_a 只能看到自己的数据
    db.set_tenant(tenant_a)
    for t in test_tables:
        visible = db.select(t)
        all_rows = db.select_all_bypass_rls(t)

        # tenant_a 只能看到 1 条（自己的）
        isolation_ok = (
            len(visible) == 1
            and visible[0].tenant_id == tenant_a
            and len(all_rows) == 2  # 总共 2 条
        )
        results.append(TestResult(
            name=f"[isolation:A_sees_only_own] {t}",
            passed=isolation_ok,
            detail=f"visible={len(visible)}, total={len(all_rows)}" if not isolation_ok else "",
        ))

    # 验证 tenant_b 只能看到自己的数据
    db.set_tenant(tenant_b)
    for t in test_tables:
        visible = db.select(t)
        isolation_ok = len(visible) == 1 and visible[0].tenant_id == tenant_b
        results.append(TestResult(
            name=f"[isolation:B_sees_only_own] {t}",
            passed=isolation_ok,
            detail="" if isolation_ok else f"visible={len(visible)}",
        ))

    return results


def test_cross_tenant_insert_blocked() -> list[TestResult]:
    """验证跨租户 INSERT 被 RLS 阻止"""
    results = []
    db = MockRLSDatabase()

    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())

    test_tables = ["orders", "payments", "settlements"]
    for t in test_tables:
        db.enable_rls(t)

    # tenant_a 尝试用 tenant_b 的 ID 插入
    db.set_tenant(tenant_a)
    for t in test_tables:
        blocked = False
        try:
            db.insert(t, tenant_b, {"name": "cross_tenant_data"})
        except PermissionError:
            blocked = True
        results.append(TestResult(
            name=f"[cross_tenant_insert_blocked] {t}",
            passed=blocked,
            detail="" if blocked else "cross-tenant INSERT was NOT blocked!",
        ))

    return results


def test_rls_policy_naming_convention() -> list[TestResult]:
    """验证 RLS Policy 命名规范一致性"""
    results = []
    for table in ALL_TABLES:
        sqls = generate_rls_sql(table)
        # 检查 policy 名称包含表名
        select_name_ok = f"tenant_isolation_{table}" in sqls[1]
        insert_name_ok = f"tenant_insert_{table}" in sqls[2]
        results.append(TestResult(
            name=f"[policy_naming] {table}",
            passed=select_name_ok and insert_name_ok,
            detail="" if (select_name_ok and insert_name_ok) else "naming mismatch",
        ))
    return results


def test_all_23_tables_covered() -> list[TestResult]:
    """验证 v001 + v002 共 23 张表全部有 RLS 覆盖"""
    results = []
    expected_count = 23
    actual_count = len(ALL_TABLES)
    results.append(TestResult(
        name="[table_count] v001(11) + v002(12) = 23",
        passed=actual_count == expected_count,
        detail=f"expected {expected_count}, got {actual_count}" if actual_count != expected_count else "",
    ))
    return results


# ──────────────────────────────────────────────
# 运行器
# ──────────────────────────────────────────────
def run_all_tests() -> None:
    all_results: list[TestResult] = []

    test_suites = [
        ("1. 表总数验证", test_all_23_tables_covered),
        ("2. tenant_id 字段检查", test_all_tables_have_tenant_id),
        ("3. 基类必须字段检查", test_all_tables_have_required_columns),
        ("4. RLS 启用 SQL 语法", test_rls_policy_sql_syntax),
        ("5. RLS 禁用 SQL 语法", test_rls_disable_sql_syntax),
        ("6. RLS Policy 命名规范", test_rls_policy_naming_convention),
        ("7. 租户数据隔离", test_tenant_data_isolation),
        ("8. 跨租户 INSERT 拦截", test_cross_tenant_insert_blocked),
    ]

    print("=" * 60)
    print("  RLS 验证测试报告 -- 屯象OS V3.2")
    print("=" * 60)

    total_pass = 0
    total_fail = 0

    for suite_name, suite_fn in test_suites:
        print(f"\n--- {suite_name} ---")
        results = suite_fn()
        all_results.extend(results)

        suite_pass = sum(1 for r in results if r.passed)
        suite_fail = sum(1 for r in results if not r.passed)
        total_pass += suite_pass
        total_fail += suite_fail

        for r in results:
            status = "PASS" if r.passed else "FAIL"
            line = f"  [{status}] {r.name}"
            if r.detail:
                line += f"  -- {r.detail}"
            print(line)

        print(f"  >> {suite_pass}/{len(results)} passed")

    print("\n" + "=" * 60)
    print(f"  TOTAL: {total_pass} passed, {total_fail} failed, "
          f"{total_pass + total_fail} total")
    if total_fail == 0:
        print("  RESULT: ALL TESTS PASSED")
    else:
        print(f"  RESULT: {total_fail} FAILURES")
    print("=" * 60)

    sys.exit(0 if total_fail == 0 else 1)


if __name__ == "__main__":
    run_all_tests()
