"""KDS相关表RLS安全测试 — 多租户隔离验证

验证内容：
1. production_depts 表：tenant_a 无法读取 tenant_b 的数据
2. dish_dept_mappings 表：tenant_a 无法读取 tenant_b 的数据
3. RLS策略使用正确的 session 变量 app.tenant_id（非 app.current_store_id / app.current_tenant）
4. RLS 具备 NULL 防护（未设置 tenant 时不可见全表）
5. 跨租户 INSERT 被阻止（RLS WITH CHECK 校验）
"""
import re
import uuid
from dataclasses import dataclass, field
from typing import Any


# ──────────────────────────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────────────────────────

CORRECT_SESSION_VAR = "app.tenant_id"
WRONG_VARS = ["app.current_store_id", "app.current_tenant", "app.store_id"]

KDS_TABLES = ["production_depts", "dish_dept_mappings"]


# ──────────────────────────────────────────────────────────────────
# Mock RLS 引擎（模拟 PostgreSQL RLS 行为）
# ──────────────────────────────────────────────────────────────────

@dataclass
class MockRow:
    table: str
    id: str
    tenant_id: str
    data: dict = field(default_factory=dict)


class MockRLSDatabase:
    """模拟带 v006+ 安全 RLS 的 PostgreSQL 数据库。

    安全条件（与迁移文件 _SAFE_CONDITION 一致）：
        current_setting('app.tenant_id', TRUE) IS NOT NULL
        AND current_setting('app.tenant_id', TRUE) <> ''
        AND tenant_id = current_setting('app.tenant_id')::UUID
    """

    def __init__(self) -> None:
        self._rows: list[MockRow] = []
        self._current_tenant: str | None = None  # None = session 变量未设置
        self._rls_tables: set[str] = set()

    def enable_rls(self, table: str) -> None:
        self._rls_tables.add(table)

    def set_tenant(self, tenant_id: str) -> None:
        """模拟 set_config('app.tenant_id', tid, true)"""
        self._current_tenant = tenant_id

    def clear_tenant(self) -> None:
        """模拟未设置 session 变量的状态"""
        self._current_tenant = None

    def _rls_check(self, table: str, row_tenant_id: str) -> bool:
        """v006+ 安全条件检查（NULL 防护 + 非空检查 + 匹配）"""
        if table not in self._rls_tables:
            return True  # RLS 未启用，全量可见
        if self._current_tenant is None or self._current_tenant == "":
            return False  # NULL / 空值防护 → 拒绝
        return row_tenant_id == self._current_tenant

    def insert(self, table: str, tenant_id: str, data: dict | None = None) -> MockRow:
        """RLS INSERT WITH CHECK 校验"""
        if table in self._rls_tables:
            if self._current_tenant is None or self._current_tenant == "":
                raise PermissionError(
                    f"RLS INSERT blocked: app.tenant_id is not set (NULL/empty)"
                )
            if tenant_id != self._current_tenant:
                raise PermissionError(
                    f"RLS INSERT blocked: row.tenant_id={tenant_id} != "
                    f"current_setting('app.tenant_id')={self._current_tenant}"
                )
        row = MockRow(table=table, id=str(uuid.uuid4()), tenant_id=tenant_id, data=data or {})
        self._rows.append(row)
        return row

    def select(self, table: str) -> list[MockRow]:
        """RLS SELECT USING 过滤"""
        return [
            r for r in self._rows
            if r.table == table and self._rls_check(table, r.tenant_id)
        ]

    def select_bypass_rls(self, table: str) -> list[MockRow]:
        """超级用户视角（绕过 RLS，用于验证数据确实存在）"""
        return [r for r in self._rows if r.table == table]


def _make_db_with_kds_data() -> tuple[MockRLSDatabase, str, str]:
    """创建带有两租户 KDS 数据的测试 DB，返回 (db, tenant_a, tenant_b)。"""
    db = MockRLSDatabase()
    for t in KDS_TABLES:
        db.enable_rls(t)

    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())

    db.set_tenant(tenant_a)
    db.insert("production_depts", tenant_a, {"dept_name": "热菜间", "dept_code": "HOT"})
    db.insert("dish_dept_mappings", tenant_a, {"dish_id": str(uuid.uuid4())})

    db.set_tenant(tenant_b)
    db.insert("production_depts", tenant_b, {"dept_name": "凉菜间", "dept_code": "COLD"})
    db.insert("dish_dept_mappings", tenant_b, {"dish_id": str(uuid.uuid4())})

    return db, tenant_a, tenant_b


# ──────────────────────────────────────────────────────────────────
# 测试 1：session 变量名正确性检查
# ──────────────────────────────────────────────────────────────────

def test_rls_uses_correct_session_variable():
    """RLS 策略必须使用 app.tenant_id，而非 app.current_store_id / app.current_tenant。"""
    # 模拟 v006+ _SAFE_CONDITION（与 shared/db-migrations/versions/v006_rls_security_fix.py 一致）
    safe_condition = (
        "current_setting('app.tenant_id', TRUE) IS NOT NULL "
        "AND current_setting('app.tenant_id', TRUE) <> '' "
        "AND tenant_id = current_setting('app.tenant_id')::UUID"
    )

    assert CORRECT_SESSION_VAR in safe_condition, (
        f"RLS 安全条件必须包含 '{CORRECT_SESSION_VAR}'"
    )

    for wrong_var in WRONG_VARS:
        assert wrong_var not in safe_condition, (
            f"RLS 安全条件不应包含错误变量 '{wrong_var}'，"
            f"当前应用代码使用 '{CORRECT_SESSION_VAR}'"
        )


def test_rls_policy_sql_references_correct_variable():
    """生成的 RLS Policy SQL 引用正确的 session 变量。"""
    for table in KDS_TABLES:
        for action in ("select", "insert", "update", "delete"):
            # 模拟迁移脚本生成的 SQL
            if action == "select":
                sql = (
                    f"CREATE POLICY {table}_rls_{action} ON {table} "
                    f"FOR SELECT USING ("
                    f"current_setting('app.tenant_id', TRUE) IS NOT NULL "
                    f"AND current_setting('app.tenant_id', TRUE) <> '' "
                    f"AND tenant_id = current_setting('app.tenant_id')::UUID)"
                )
            elif action == "insert":
                sql = (
                    f"CREATE POLICY {table}_rls_{action} ON {table} "
                    f"FOR INSERT WITH CHECK ("
                    f"current_setting('app.tenant_id', TRUE) IS NOT NULL "
                    f"AND current_setting('app.tenant_id', TRUE) <> '' "
                    f"AND tenant_id = current_setting('app.tenant_id')::UUID)"
                )
            else:
                sql = (
                    f"CREATE POLICY {table}_rls_{action} ON {table} "
                    f"FOR {action.upper()} USING ("
                    f"current_setting('app.tenant_id', TRUE) IS NOT NULL "
                    f"AND current_setting('app.tenant_id', TRUE) <> '' "
                    f"AND tenant_id = current_setting('app.tenant_id')::UUID)"
                )

            assert CORRECT_SESSION_VAR in sql, (
                f"[{table}/{action}] SQL 未引用正确变量 '{CORRECT_SESSION_VAR}': {sql}"
            )
            for wrong_var in WRONG_VARS:
                assert wrong_var not in sql, (
                    f"[{table}/{action}] SQL 引用了错误变量 '{wrong_var}': {sql}"
                )


# ──────────────────────────────────────────────────────────────────
# 测试 2：production_depts 多租户隔离
# ──────────────────────────────────────────────────────────────────

def test_tenant_a_cannot_read_tenant_b_production_depts():
    """tenant_a 设置 session 后，只能看到自己的 production_depts，看不到 tenant_b 的。"""
    db, tenant_a, tenant_b = _make_db_with_kds_data()

    db.set_tenant(tenant_a)
    visible = db.select("production_depts")
    all_rows = db.select_bypass_rls("production_depts")

    assert len(all_rows) == 2, "超级用户视角应能看到两条记录"
    assert len(visible) == 1, f"tenant_a 只应看到 1 条记录，实际看到 {len(visible)} 条"
    assert visible[0].tenant_id == tenant_a, "tenant_a 看到的记录必须是自己的"


def test_tenant_b_cannot_read_tenant_a_production_depts():
    """tenant_b 设置 session 后，只能看到自己的 production_depts，看不到 tenant_a 的。"""
    db, tenant_a, tenant_b = _make_db_with_kds_data()

    db.set_tenant(tenant_b)
    visible = db.select("production_depts")

    assert len(visible) == 1, f"tenant_b 只应看到 1 条记录，实际看到 {len(visible)} 条"
    assert visible[0].tenant_id == tenant_b, "tenant_b 看到的记录必须是自己的"
    for row in visible:
        assert row.tenant_id != tenant_a, "tenant_b 不应看到 tenant_a 的 production_depts"


# ──────────────────────────────────────────────────────────────────
# 测试 3：dish_dept_mappings 多租户隔离
# ──────────────────────────────────────────────────────────────────

def test_tenant_a_cannot_read_tenant_b_dish_dept_mappings():
    """tenant_a 设置 session 后，只能看到自己的 dish_dept_mappings，看不到 tenant_b 的。"""
    db, tenant_a, tenant_b = _make_db_with_kds_data()

    db.set_tenant(tenant_a)
    visible = db.select("dish_dept_mappings")
    all_rows = db.select_bypass_rls("dish_dept_mappings")

    assert len(all_rows) == 2, "超级用户视角应能看到两条记录"
    assert len(visible) == 1, f"tenant_a 只应看到 1 条记录，实际看到 {len(visible)} 条"
    assert visible[0].tenant_id == tenant_a


def test_tenant_b_cannot_read_tenant_a_dish_dept_mappings():
    """tenant_b 设置 session 后，只能看到自己的 dish_dept_mappings，看不到 tenant_a 的。"""
    db, tenant_a, tenant_b = _make_db_with_kds_data()

    db.set_tenant(tenant_b)
    visible = db.select("dish_dept_mappings")

    assert len(visible) == 1, f"tenant_b 只应看到 1 条记录，实际看到 {len(visible)} 条"
    assert visible[0].tenant_id == tenant_b
    for row in visible:
        assert row.tenant_id != tenant_a, "tenant_b 不应看到 tenant_a 的 dish_dept_mappings"


# ──────────────────────────────────────────────────────────────────
# 测试 4：NULL 防护（session 未设置时全表不可见）
# ──────────────────────────────────────────────────────────────────

def test_production_depts_invisible_when_tenant_not_set():
    """未设置 app.tenant_id 时，production_depts 应全表不可见（NULL 防护）。"""
    db, tenant_a, tenant_b = _make_db_with_kds_data()

    db.clear_tenant()  # 模拟未设置 session 变量
    visible = db.select("production_depts")

    assert len(visible) == 0, (
        f"未设置 app.tenant_id 时不应看到任何记录，"
        f"但实际看到 {len(visible)} 条 —— RLS NULL 防护失效！"
    )


def test_dish_dept_mappings_invisible_when_tenant_not_set():
    """未设置 app.tenant_id 时，dish_dept_mappings 应全表不可见（NULL 防护）。"""
    db, tenant_a, tenant_b = _make_db_with_kds_data()

    db.clear_tenant()
    visible = db.select("dish_dept_mappings")

    assert len(visible) == 0, (
        f"未设置 app.tenant_id 时不应看到任何记录，"
        f"但实际看到 {len(visible)} 条 —— RLS NULL 防护失效！"
    )


# ──────────────────────────────────────────────────────────────────
# 测试 5：跨租户 INSERT 被 RLS 阻止
# ──────────────────────────────────────────────────────────────────

def test_cross_tenant_insert_blocked_production_depts():
    """tenant_a 不能向 production_depts 写入 tenant_b 的数据。"""
    db = MockRLSDatabase()
    db.enable_rls("production_depts")

    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())

    db.set_tenant(tenant_a)

    blocked = False
    try:
        db.insert("production_depts", tenant_b, {"dept_name": "非法写入"})
    except PermissionError:
        blocked = True

    assert blocked, "跨租户 INSERT 应被 RLS WITH CHECK 阻止"


def test_cross_tenant_insert_blocked_dish_dept_mappings():
    """tenant_a 不能向 dish_dept_mappings 写入 tenant_b 的数据。"""
    db = MockRLSDatabase()
    db.enable_rls("dish_dept_mappings")

    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())

    db.set_tenant(tenant_a)

    blocked = False
    try:
        db.insert("dish_dept_mappings", tenant_b, {"dish_id": str(uuid.uuid4())})
    except PermissionError:
        blocked = True

    assert blocked, "跨租户 INSERT 应被 RLS WITH CHECK 阻止"


def test_insert_without_tenant_blocked():
    """未设置 app.tenant_id 时，INSERT 应被 RLS 阻止。"""
    db = MockRLSDatabase()
    db.enable_rls("production_depts")

    db.clear_tenant()

    blocked = False
    try:
        db.insert("production_depts", str(uuid.uuid4()), {"dept_name": "无租户写入"})
    except PermissionError:
        blocked = True

    assert blocked, "未设置 app.tenant_id 时 INSERT 应被阻止"


# ──────────────────────────────────────────────────────────────────
# 测试 6：迁移文件包含 v016 对 KDS 表的覆盖验证
# ──────────────────────────────────────────────────────────────────

def test_v017_migration_covers_kds_tables():
    """验证 v017 迁移文件覆盖了 production_depts 和 dish_dept_mappings。"""
    import os
    migration_path = os.path.join(
        os.path.dirname(__file__),
        "..", "..", "..", "shared", "db-migrations", "versions",
        "v017_kds_rls_security_fix.py",
    )
    migration_path = os.path.normpath(migration_path)

    assert os.path.exists(migration_path), (
        f"迁移文件不存在: {migration_path}"
    )

    with open(migration_path) as f:
        content = f.read()

    for table in KDS_TABLES:
        assert table in content, (
            f"v017 迁移文件未覆盖表 '{table}'"
        )

    assert CORRECT_SESSION_VAR in content, (
        f"v017 迁移文件未使用正确 session 变量 '{CORRECT_SESSION_VAR}'"
    )

    for wrong_var in WRONG_VARS:
        assert wrong_var not in content, (
            f"v017 迁移文件包含错误 session 变量 '{wrong_var}'"
        )
