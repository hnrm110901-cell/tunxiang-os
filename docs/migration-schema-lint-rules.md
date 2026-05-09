# Migration Schema Lint 规则详解

> 配套 `shared/db-migrations/tests/test_schema_lint_tier1.py`。每条规则的根因、检测方式、修复指引。
> 
> 整体策略：**ratchet baseline** — 现有违例数作为基线，新 PR 引入新违例 → 测试 fail。每修复一组，PR 中下调 baseline 让基线收紧。

## 规则总览

| 类 | 规则 | main baseline | 修复 PR |
|---|---|---|---|
| A | 同名表多 schema 撞名 | 25 | #342 / #343 / 等 |
| B | server_default JSONB 引号嵌套 | 20 | #339 |
| C | sa.text bind param + cast 歧义 | 1 | #339 / #340 |
| D | PRIMARY KEY 含函数表达式 | 1 | #339 |
| F-1 | CREATE POLICY IF NOT EXISTS | 1 | #345 |
| F-2 | FOR INSERT POLICY 用 USING | 0 | #343 / #345 |
| G | GENERATED / INDEX 含非 IMMUTABLE | 40* | #345 |

*类 G 当前包含正则 false positive（`[^;]*?` 跨多 op.execute 误捕），下个 PR 收紧 regex。

---

## 类 A — 同名表多 schema 撞名

### 根因

14 services 共用 `shared/db-migrations/`，多个 service team 各自给同表名写 CREATE TABLE，schema 完全不同：

```
v031: CREATE TABLE approval_instances (flow_def_id ..., business_type ...)
v059: CREATE TABLE approval_instances (template_id ..., business_id ...)
v235c: CREATE TABLE approval_instances (application_id ..., current_node_index ...)
```

PG 一张表只能有一种 schema → `IF NOT EXISTS` 让先到的胜出，后到的所有 CREATE INDEX / ALTER 引用该表的列时撞列不存在。

### 检测

`_CREATE_TABLE_RE` 扫描所有 `CREATE TABLE [IF NOT EXISTS] <name>`，按表名 group。>1 文件创建同名表 → 违例。

### 修复

需 audit 业务侧 ORM model 用哪个 schema：

```bash
grep -rE "FROM <table_name>|UPDATE <table_name>" services/
grep -rln "<table_name>" services/  # 找 ORM models
```

确定 canonical schema 后：

1. canonical 文件加 `op.execute("DROP TABLE IF EXISTS <table> CASCADE")` 在 CREATE 前
2. 副本文件改 `def upgrade(): return` no-op
3. 若是真不同需求（不只是副本），rename 表 + 拆 service 边界

参考：PR #342 banquet_leads / PR #343 banquet 群 / PR #345 approval_instances

---

## 类 B — server_default JSONB 引号嵌套

### 根因

```python
sa.Column("data", JSONB, server_default="'{}'")  # ❌ Python "'..'" 双层引号
```

SQLAlchemy 把 `"'{}'"` 这个 Python 字面量直接渲染为 SQL `DEFAULT '{}'`，PG 端 JSONB 列尝试解析含转义引号的字面量 → invalid JSON。

### 检测

正则 `server_default="'(?:\{\}|\[\])'"` 直接命中 `"'{}'"` 和 `"'[]'"` 模式。

### 修复

```python
sa.Column("data", JSONB, server_default=sa.text("'{}'::jsonb"))  # ✅ 显式 cast
```

`sa.text(...)` 让 SQLAlchemy 不二次包装；`'{}'::jsonb` 是 PG 标准 cast。

参考：PR #339 v194/v258/v260/v263/v286 批量修

---

## 类 C — sa.text bind param + PG cast 歧义

### 根因

```python
sa.text("UPDATE t SET col = :cfg::jsonb").bindparams(cfg=...)
```

SQLAlchemy text 解析器在 `:cfg::jsonb` 上歧义 — `:` 是 named parameter，`::` 是 PG cast。解析器误判 `cfg::jsonb` 为参数名 → ArgumentError "doesn't define a bound parameter named 'cfg'"。

### 检测

正则 `sa\.text\(.*?:\w+::\w+` (DOTALL)。

### 修复

修法 1（最显式）：
```python
sa.text("SET col = cast(:cfg AS jsonb)").bindparams(cfg=...)
```

修法 2（最少改动）：
```python
sa.text("SET col = (:cfg)::jsonb").bindparams(cfg=...)  # 加括号断歧义
```

修法 3（绕过 sa.text 解析）：
```python
op.get_bind().exec_driver_sql("UPDATE t SET col = '%s'::jsonb" % json.dumps(cfg))
# 注意：自己处理 SQL injection
```

参考：PR #339 v232c / PR #340 v288 用 exec_driver_sql

---

## 类 D — PRIMARY KEY 含函数表达式

### 根因

```sql
PRIMARY KEY (col1, col2, COALESCE(zone_id, '00000000-...'::UUID))
```

PG PRIMARY KEY 列不接受表达式 — 只接受裸列名。

### 检测

正则匹配 `PRIMARY KEY (...)` 内含 `IDENT(` 函数调用。

### 修复

修法 1（哨兵 NOT NULL）：
```sql
zone_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000000'::UUID,
PRIMARY KEY (col1, col2, zone_id)
```

修法 2（拆 UNIQUE INDEX + surrogate PK）：
```sql
id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
... ,
UNIQUE INDEX (col1, col2, COALESCE(zone_id, '00000000-...'::UUID))
```

参考：PR #339 v151b mv_table_turnover

---

## 类 F-1 — CREATE POLICY IF NOT EXISTS

### 根因

PG 不支持 `CREATE POLICY IF NOT EXISTS`（只有 `DROP POLICY IF EXISTS`）。

### 检测

正则 `CREATE\s+POLICY\s+IF\s+NOT\s+EXISTS`。

### 修复

```sql
DROP POLICY IF EXISTS policy_name ON table_name;
CREATE POLICY policy_name ON table_name USING (...);
```

参考：PR #345 v311

---

## 类 F-2 — FOR INSERT POLICY 用 USING（应 WITH CHECK）

### 根因

```sql
CREATE POLICY ... FOR INSERT TO PUBLIC USING (...);  -- ❌ PG 拒绝
```

PG 语义：

| Action | USING | WITH CHECK |
|---|---|---|
| SELECT | ✓ | ✗ |
| INSERT | ✗ | ✓ |
| UPDATE | ✓ | ✓（双子句） |
| DELETE | ✓ | ✗ |

INSERT POLICY 必须 WITH CHECK；DELETE 必须 USING；UPDATE 双子句。

### 检测

正则 `FOR\s+INSERT\s+TO\s+PUBLIC\s+USING\s*\(`。

### 修复

```python
clause = "WITH CHECK" if action == "INSERT" else "USING"
op.execute(f"CREATE POLICY ... FOR {action} ... {clause} (...)")
```

完整 helper（推荐，避免 hard-code 多 helper）：

```python
def _create_rls_policy(table: str, action: str, condition: str) -> None:
    if action == "INSERT":
        op.execute(f"CREATE POLICY ... FOR INSERT TO PUBLIC WITH CHECK ({condition})")
    elif action == "UPDATE":
        op.execute(f"CREATE POLICY ... FOR UPDATE TO PUBLIC USING ({condition}) WITH CHECK ({condition})")
    else:  # SELECT / DELETE
        op.execute(f"CREATE POLICY ... FOR {action} TO PUBLIC USING ({condition})")
```

**安全意义**：原 `FOR INSERT USING (...)` 让整个 POLICY 创建失败 → migration transaction 回滚 → 实际表无 RLS → **跨租户 INSERT 漏洞**。CLAUDE.md §17 Tier 1 多租户隔离硬约束。

参考：PR #343 batch fix 6 helper / PR #345 v395 三 action 子句

---

## 类 G — GENERATED / INDEX 含非 IMMUTABLE 函数

### 根因

PG 要求 STORED 生成列 / 索引表达式必须 IMMUTABLE。常见 STABLE 函数（不能用）：

- `now()` / `current_date` / `current_timestamp`
- `age(...)` — 依赖时区
- `date_trunc(unit, ts)` — STABLE 在 PG 16+
- `extract(field FROM ts)` — 取决于输入类型
- `random()` — VOLATILE

### 检测

正则匹配 `GENERATED ALWAYS AS (...<func>(...))` 和 `CREATE INDEX ((<func>(...)))`。

### 修复

修法 1（生成列改普通列由 service 维护）：
```sql
months_since_opening INT,  -- 由 service INSERT/UPDATE 时计算写入
```

修法 2（索引去掉函数，用裸列 + 查询侧范围过滤）：
```sql
CREATE INDEX idx_x ON t (tenant_id, created_at DESC);  -- 索引
-- 查询侧：
SELECT ... WHERE created_at >= start_of_month AND created_at < start_of_next_month
```

修法 3（用真 IMMUTABLE 函数）：
```sql
CREATE INDEX idx_x ON t ((lower(name)));  -- lower/upper/btrim 都是 IMMUTABLE
```

参考：PR #345 v378 生成列 / v264 索引函数

---

## Ratchet 维护流程

每次修复一组 bug 后：

1. 修代码
2. 跑 `pytest test_schema_lint_tier1.py -v` — 看 `[ratchet hint]` 提示
3. 若 actual < BASELINE，下调对应 `_CLASS_X_BASELINE` 常量到 actual 值
4. 同 PR 提交（修复代码 + 下调 baseline）
5. 后续 PR 不能引入新违例（baseline 已收紧）

终态：所有 BASELINE = 0，linter 完全 enforce 0 violation。

---

## 与 CI 集成（Phase 2）

待 Phase 2 CI gate 落地后：

```yaml
# .github/workflows/migration-ci.yml
- name: Schema lint
  run: pytest shared/db-migrations/tests/test_schema_lint_tier1.py
```

new migration PR 引入违例（超 baseline）→ CI fail，不可合。
