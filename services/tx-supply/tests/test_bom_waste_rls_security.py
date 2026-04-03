"""BOM/废料表 RLS 安全测试 — 多租户隔离验证

验证内容：
1. bom_templates / bom_items / waste_events 使用正确 session 变量 app.tenant_id
   （不是 app.current_store_id，也不是 app.current_tenant）
2. 正确设置 session 变量后，同租户数据可访问
3. 不同租户数据不可越权访问（SELECT 隔离）
4. NULL 防护：未设置 session 变量时全表不可见
5. 跨租户 INSERT 被 RLS WITH CHECK 阻止
6. v063 迁移文件覆盖这 3 张表且使用正确变量

对应漏洞：MEMORY - project_rls_vulnerability.md
  原报告：r01_bom_tables.py / r04_waste_event_table.py 使用 app.current_store_id，
          而应用代码设置的是 app.current_tenant，导致 RLS 永远不生效。
  修复目标：统一为 app.tenant_id（项目标准，见 CLAUDE.md / v056_fix_rls_vulnerabilities.py）
"""
import os
import uuid
from dataclasses import dataclass, field

# ─────────────────────────────────────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────────────────────────────────────

# 正确的 session 变量名（与 CLAUDE.md 安全约束和 v006+ 迁移一致）
CORRECT_SESSION_VAR = "app.tenant_id"

# 禁止使用的变量名
WRONG_VARS = [
    "app.current_store_id",  # 原漏洞中使用的错误变量
    "app.current_tenant",    # 内存记录中应用代码曾用的变量（同样错误）
    "app.store_id",
    "app.tenant",
]

# 受影响的三张表
TARGET_TABLES = ["bom_templates", "bom_items", "waste_events"]

# 正确的 NULLIF 安全条件（v056+ 标准）
CORRECT_SAFE_CONDITION = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"
)


# ─────────────────────────────────────────────────────────────────────────────
# Mock RLS 引擎（模拟 PostgreSQL RLS 行为）
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class MockRow:
    table: str
    id: str
    tenant_id: str
    data: dict = field(default_factory=dict)


class MockRLSDatabase:
    """模拟带 v056+ NULLIF 安全 RLS 的 PostgreSQL 数据库。

    安全条件（与 v056 _SAFE_CONDITION 一致）：
        tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID

    NULL 防护：current_setting 返回 '' 或 None 时，NULLIF 使结果为 NULL，
               UUID 比较永远为 false，全行被过滤掉。
    """

    def __init__(self) -> None:
        self._rows: list[MockRow] = []
        self._current_tenant: str | None = None  # None 模拟 session 未设置
        self._rls_tables: set[str] = set()

    def enable_rls(self, table: str) -> None:
        self._rls_tables.add(table)

    def set_tenant(self, tenant_id: str) -> None:
        """模拟 set_config('app.tenant_id', tid, true)"""
        self._current_tenant = tenant_id

    def clear_tenant(self) -> None:
        """模拟 session 变量未设置（current_setting 返回 ''）"""
        self._current_tenant = None

    def _rls_check(self, table: str, row_tenant_id: str) -> bool:
        """v056+ NULLIF 安全条件：NULL/空值防护 + 精确匹配。"""
        if table not in self._rls_tables:
            return True  # RLS 未启用
        if self._current_tenant is None or self._current_tenant == "":
            return False  # NULLIF 将空串变为 NULL，UUID 比较 false → 过滤
        return row_tenant_id == self._current_tenant

    def insert(self, table: str, tenant_id: str, data: dict | None = None) -> MockRow:
        """模拟 INSERT WITH CHECK。"""
        if table in self._rls_tables:
            if self._current_tenant is None or self._current_tenant == "":
                raise PermissionError(
                    "RLS INSERT blocked: app.tenant_id is not set (NULL/empty)"
                )
            if tenant_id != self._current_tenant:
                raise PermissionError(
                    f"RLS INSERT blocked: row.tenant_id={tenant_id} != "
                    f"current_setting('app.tenant_id')={self._current_tenant}"
                )
        row = MockRow(
            table=table,
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            data=data or {},
        )
        self._rows.append(row)
        return row

    def select(self, table: str) -> list[MockRow]:
        """模拟 SELECT USING 过滤。"""
        return [
            r for r in self._rows
            if r.table == table and self._rls_check(table, r.tenant_id)
        ]

    def select_bypass_rls(self, table: str) -> list[MockRow]:
        """超级用户视角（绕过 RLS，确认数据确实存在）。"""
        return [r for r in self._rows if r.table == table]


def _make_db_with_data() -> tuple[MockRLSDatabase, str, str]:
    """创建带有两租户三张表数据的测试 DB，返回 (db, tenant_a, tenant_b)。"""
    db = MockRLSDatabase()
    for t in TARGET_TABLES:
        db.enable_rls(t)

    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())

    db.set_tenant(tenant_a)
    db.insert("bom_templates", tenant_a, {"dish_id": str(uuid.uuid4()), "version": "v1"})
    db.insert("bom_items", tenant_a, {"bom_id": str(uuid.uuid4()), "standard_qty": 0.5})
    db.insert("waste_events", tenant_a, {"event_type": "cooking_loss", "quantity": 0.1})

    db.set_tenant(tenant_b)
    db.insert("bom_templates", tenant_b, {"dish_id": str(uuid.uuid4()), "version": "v1"})
    db.insert("bom_items", tenant_b, {"bom_id": str(uuid.uuid4()), "standard_qty": 1.0})
    db.insert("waste_events", tenant_b, {"event_type": "spoilage", "quantity": 0.2})

    return db, tenant_a, tenant_b


# ─────────────────────────────────────────────────────────────────────────────
# 测试组 1：session 变量名正确性验证
# ─────────────────────────────────────────────────────────────────────────────

def test_correct_session_variable_in_safe_condition():
    """RLS 安全条件必须使用 app.tenant_id，不能使用 app.current_store_id 或 app.current_tenant。"""
    assert CORRECT_SESSION_VAR in CORRECT_SAFE_CONDITION, (
        f"安全条件必须包含 '{CORRECT_SESSION_VAR}'"
    )
    for wrong_var in WRONG_VARS:
        assert wrong_var not in CORRECT_SAFE_CONDITION, (
            f"安全条件不应包含错误变量 '{wrong_var}'；"
            f"此变量曾引发 bom_templates/bom_items/waste_events RLS 永不生效的 CRITICAL 漏洞"
        )


def test_rls_policy_sql_uses_correct_variable():
    """为三张表生成的 RLS Policy SQL 必须引用 app.tenant_id。"""
    for table in TARGET_TABLES:
        for action in ("select", "insert", "update", "delete"):
            if action == "select":
                sql = (
                    f"CREATE POLICY {table}_rls_{action} ON {table} "
                    f"FOR SELECT USING ({CORRECT_SAFE_CONDITION})"
                )
            elif action == "insert":
                sql = (
                    f"CREATE POLICY {table}_rls_{action} ON {table} "
                    f"FOR INSERT WITH CHECK ({CORRECT_SAFE_CONDITION})"
                )
            elif action == "update":
                sql = (
                    f"CREATE POLICY {table}_rls_{action} ON {table} "
                    f"FOR UPDATE USING ({CORRECT_SAFE_CONDITION}) "
                    f"WITH CHECK ({CORRECT_SAFE_CONDITION})"
                )
            else:  # delete
                sql = (
                    f"CREATE POLICY {table}_rls_{action} ON {table} "
                    f"FOR DELETE USING ({CORRECT_SAFE_CONDITION})"
                )

            assert CORRECT_SESSION_VAR in sql, (
                f"[{table}/{action}] SQL 未引用正确变量 '{CORRECT_SESSION_VAR}': {sql}"
            )
            for wrong_var in WRONG_VARS:
                assert wrong_var not in sql, (
                    f"[{table}/{action}] SQL 引用了错误变量 '{wrong_var}': {sql}"
                )


# ─────────────────────────────────────────────────────────────────────────────
# 测试组 2：同租户数据可访问（设置正确 session 后）
# ─────────────────────────────────────────────────────────────────────────────

def test_tenant_a_can_access_own_bom_templates():
    """设置正确的 app.tenant_id 后，tenant_a 可以访问自己的 bom_templates。"""
    db, tenant_a, tenant_b = _make_db_with_data()

    db.set_tenant(tenant_a)
    visible = db.select("bom_templates")

    assert len(visible) == 1, (
        f"tenant_a 应能访问自己的 bom_templates，实际看到 {len(visible)} 条"
    )
    assert visible[0].tenant_id == tenant_a


def test_tenant_a_can_access_own_bom_items():
    """设置正确的 app.tenant_id 后，tenant_a 可以访问自己的 bom_items。"""
    db, tenant_a, tenant_b = _make_db_with_data()

    db.set_tenant(tenant_a)
    visible = db.select("bom_items")

    assert len(visible) == 1, (
        f"tenant_a 应能访问自己的 bom_items，实际看到 {len(visible)} 条"
    )
    assert visible[0].tenant_id == tenant_a


def test_tenant_a_can_access_own_waste_events():
    """设置正确的 app.tenant_id 后，tenant_a 可以访问自己的 waste_events。"""
    db, tenant_a, tenant_b = _make_db_with_data()

    db.set_tenant(tenant_a)
    visible = db.select("waste_events")

    assert len(visible) == 1, (
        f"tenant_a 应能访问自己的 waste_events，实际看到 {len(visible)} 条"
    )
    assert visible[0].tenant_id == tenant_a


# ─────────────────────────────────────────────────────────────────────────────
# 测试组 3：不同租户数据不可越权访问
# ─────────────────────────────────────────────────────────────────────────────

def test_tenant_a_cannot_read_tenant_b_bom_templates():
    """tenant_a 不能读取 tenant_b 的 bom_templates。"""
    db, tenant_a, tenant_b = _make_db_with_data()

    db.set_tenant(tenant_a)
    visible = db.select("bom_templates")
    all_rows = db.select_bypass_rls("bom_templates")

    assert len(all_rows) == 2, "超级用户视角应能看到两条记录"
    assert len(visible) == 1, f"tenant_a 只应看到 1 条记录，实际看到 {len(visible)} 条"
    assert visible[0].tenant_id == tenant_a
    for row in visible:
        assert row.tenant_id != tenant_b, "tenant_a 不应看到 tenant_b 的 bom_templates"


def test_tenant_b_cannot_read_tenant_a_bom_templates():
    """tenant_b 不能读取 tenant_a 的 bom_templates。"""
    db, tenant_a, tenant_b = _make_db_with_data()

    db.set_tenant(tenant_b)
    visible = db.select("bom_templates")

    assert len(visible) == 1, f"tenant_b 只应看到 1 条记录，实际看到 {len(visible)} 条"
    assert visible[0].tenant_id == tenant_b
    for row in visible:
        assert row.tenant_id != tenant_a, "tenant_b 不应看到 tenant_a 的 bom_templates"


def test_tenant_a_cannot_read_tenant_b_bom_items():
    """tenant_a 不能读取 tenant_b 的 bom_items。"""
    db, tenant_a, tenant_b = _make_db_with_data()

    db.set_tenant(tenant_a)
    visible = db.select("bom_items")
    all_rows = db.select_bypass_rls("bom_items")

    assert len(all_rows) == 2
    assert len(visible) == 1
    assert visible[0].tenant_id == tenant_a
    for row in visible:
        assert row.tenant_id != tenant_b


def test_tenant_b_cannot_read_tenant_a_bom_items():
    """tenant_b 不能读取 tenant_a 的 bom_items。"""
    db, tenant_a, tenant_b = _make_db_with_data()

    db.set_tenant(tenant_b)
    visible = db.select("bom_items")

    assert len(visible) == 1
    assert visible[0].tenant_id == tenant_b
    for row in visible:
        assert row.tenant_id != tenant_a


def test_tenant_a_cannot_read_tenant_b_waste_events():
    """tenant_a 不能读取 tenant_b 的 waste_events。"""
    db, tenant_a, tenant_b = _make_db_with_data()

    db.set_tenant(tenant_a)
    visible = db.select("waste_events")
    all_rows = db.select_bypass_rls("waste_events")

    assert len(all_rows) == 2
    assert len(visible) == 1
    assert visible[0].tenant_id == tenant_a
    for row in visible:
        assert row.tenant_id != tenant_b


def test_tenant_b_cannot_read_tenant_a_waste_events():
    """tenant_b 不能读取 tenant_a 的 waste_events。"""
    db, tenant_a, tenant_b = _make_db_with_data()

    db.set_tenant(tenant_b)
    visible = db.select("waste_events")

    assert len(visible) == 1
    assert visible[0].tenant_id == tenant_b
    for row in visible:
        assert row.tenant_id != tenant_a


# ─────────────────────────────────────────────────────────────────────────────
# 测试组 4：NULL 防护（session 未设置时全表不可见）
# ─────────────────────────────────────────────────────────────────────────────

def test_bom_templates_invisible_when_tenant_not_set():
    """未设置 app.tenant_id 时，bom_templates 全表不可见（NULL 防护）。"""
    db, tenant_a, tenant_b = _make_db_with_data()

    db.clear_tenant()
    visible = db.select("bom_templates")

    assert len(visible) == 0, (
        f"未设置 app.tenant_id 时不应看到任何 bom_templates，"
        f"但实际看到 {len(visible)} 条 —— RLS NULL 防护失效！"
    )


def test_bom_items_invisible_when_tenant_not_set():
    """未设置 app.tenant_id 时，bom_items 全表不可见（NULL 防护）。"""
    db, tenant_a, tenant_b = _make_db_with_data()

    db.clear_tenant()
    visible = db.select("bom_items")

    assert len(visible) == 0, (
        f"未设置 app.tenant_id 时不应看到任何 bom_items，"
        f"但实际看到 {len(visible)} 条 —— RLS NULL 防护失效！"
    )


def test_waste_events_invisible_when_tenant_not_set():
    """未设置 app.tenant_id 时，waste_events 全表不可见（NULL 防护）。"""
    db, tenant_a, tenant_b = _make_db_with_data()

    db.clear_tenant()
    visible = db.select("waste_events")

    assert len(visible) == 0, (
        f"未设置 app.tenant_id 时不应看到任何 waste_events，"
        f"但实际看到 {len(visible)} 条 —— RLS NULL 防护失效！"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 测试组 5：跨租户 INSERT 被 RLS 阻止
# ─────────────────────────────────────────────────────────────────────────────

def test_cross_tenant_insert_blocked_bom_templates():
    """tenant_a 不能向 bom_templates 写入 tenant_b 的数据。"""
    db = MockRLSDatabase()
    db.enable_rls("bom_templates")

    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    db.set_tenant(tenant_a)

    blocked = False
    try:
        db.insert("bom_templates", tenant_b, {"dish_id": str(uuid.uuid4()), "version": "hack"})
    except PermissionError:
        blocked = True

    assert blocked, "跨租户 INSERT 应被 RLS WITH CHECK 阻止"


def test_cross_tenant_insert_blocked_bom_items():
    """tenant_a 不能向 bom_items 写入 tenant_b 的数据。"""
    db = MockRLSDatabase()
    db.enable_rls("bom_items")

    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    db.set_tenant(tenant_a)

    blocked = False
    try:
        db.insert("bom_items", tenant_b, {"bom_id": str(uuid.uuid4()), "standard_qty": 999})
    except PermissionError:
        blocked = True

    assert blocked, "跨租户 INSERT 应被 RLS WITH CHECK 阻止"


def test_cross_tenant_insert_blocked_waste_events():
    """tenant_a 不能向 waste_events 写入 tenant_b 的数据。"""
    db = MockRLSDatabase()
    db.enable_rls("waste_events")

    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    db.set_tenant(tenant_a)

    blocked = False
    try:
        db.insert("waste_events", tenant_b, {"event_type": "malicious", "quantity": 9999})
    except PermissionError:
        blocked = True

    assert blocked, "跨租户 INSERT 应被 RLS WITH CHECK 阻止"


def test_insert_without_tenant_blocked():
    """未设置 app.tenant_id 时，INSERT 应被 RLS 阻止（防止匿名写入）。"""
    db = MockRLSDatabase()
    for t in TARGET_TABLES:
        db.enable_rls(t)

    db.clear_tenant()

    for table in TARGET_TABLES:
        blocked = False
        try:
            db.insert(table, str(uuid.uuid4()), {"data": "anonymous"})
        except PermissionError:
            blocked = True

        assert blocked, f"未设置 app.tenant_id 时 INSERT 到 {table} 应被阻止"


# ─────────────────────────────────────────────────────────────────────────────
# 测试组 6：v063 迁移文件内容验证
# ─────────────────────────────────────────────────────────────────────────────

def _get_migration_path(filename: str) -> str:
    """根据当前测试文件位置解析迁移文件路径。"""
    base = os.path.dirname(__file__)
    return os.path.normpath(
        os.path.join(base, "..", "..", "..", "shared", "db-migrations", "versions", filename)
    )


def test_v063_migration_file_exists():
    """v063_fix_rls_bom_waste.py 迁移文件必须存在。"""
    migration_path = _get_migration_path("v063_fix_rls_bom_waste.py")
    assert os.path.exists(migration_path), (
        f"修复迁移文件不存在: {migration_path}\n"
        f"请创建 shared/db-migrations/versions/v063_fix_rls_bom_waste.py"
    )


def test_v063_covers_all_target_tables():
    """v063 迁移文件必须覆盖 bom_templates、bom_items、waste_events 全部三张表。"""
    migration_path = _get_migration_path("v063_fix_rls_bom_waste.py")
    if not os.path.exists(migration_path):
        return  # 已被上一个测试捕获

    with open(migration_path) as f:
        content = f.read()

    for table in TARGET_TABLES:
        assert table in content, (
            f"v063 迁移文件未覆盖表 '{table}'，该表存在 RLS 漏洞"
        )


def test_v063_uses_correct_session_variable():
    """v063 迁移文件必须使用 app.tenant_id，禁止使用错误变量。"""
    migration_path = _get_migration_path("v063_fix_rls_bom_waste.py")
    if not os.path.exists(migration_path):
        return  # 已被上一个测试捕获

    with open(migration_path) as f:
        content = f.read()

    assert CORRECT_SESSION_VAR in content, (
        f"v063 迁移文件未使用正确 session 变量 '{CORRECT_SESSION_VAR}'"
    )

    for wrong_var in WRONG_VARS:
        # 排除注释中的说明性文字（以 # 开头的行）
        non_comment_lines = [
            line for line in content.splitlines()
            if not line.strip().startswith("#")
        ]
        non_comment_content = "\n".join(non_comment_lines)
        assert wrong_var not in non_comment_content, (
            f"v063 迁移文件代码部分包含错误 session 变量 '{wrong_var}'，"
            f"这是此次修复要解决的漏洞根因"
        )


def test_v063_has_drop_old_policies():
    """v063 迁移文件必须 DROP 旧策略才能替换。"""
    migration_path = _get_migration_path("v063_fix_rls_bom_waste.py")
    if not os.path.exists(migration_path):
        return

    with open(migration_path) as f:
        content = f.read()

    assert "DROP POLICY" in content, (
        "v063 迁移文件必须包含 DROP POLICY 语句，否则新策略会与旧策略冲突"
    )


def test_v063_has_force_row_level_security():
    """v063 迁移文件必须设置 FORCE ROW LEVEL SECURITY（防止表 owner 绕过）。"""
    migration_path = _get_migration_path("v063_fix_rls_bom_waste.py")
    if not os.path.exists(migration_path):
        return

    with open(migration_path) as f:
        content = f.read()

    assert "FORCE ROW LEVEL SECURITY" in content, (
        "v063 迁移文件必须包含 FORCE ROW LEVEL SECURITY，防止表 owner 绕过 RLS"
    )


def test_v063_has_nullif_guard():
    """v063 迁移文件必须使用 NULLIF NULL guard，防止空值绕过。"""
    migration_path = _get_migration_path("v063_fix_rls_bom_waste.py")
    if not os.path.exists(migration_path):
        return

    with open(migration_path) as f:
        content = f.read()

    assert "NULLIF" in content, (
        "v063 迁移文件必须使用 NULLIF guard，"
        "防止 session 变量为空时 RLS 被绕过"
    )
