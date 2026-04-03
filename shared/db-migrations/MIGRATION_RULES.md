# 数据库迁移规范

## 铁律：向前兼容

每次迁移必须保证：旧版本代码在新 schema 上照样能跑。

### 改列名（4步走）
```
V008: ALTER TABLE ADD COLUMN new_name ...;         -- 新增列
V009: UPDATE SET new_name = old_name WHERE ...;    -- 数据同步
      -- 应用代码切到 new_name，部署验证
V010: ALTER TABLE DROP COLUMN old_name;            -- 确认无误删旧列
```

### 删列
```
V008: -- 应用代码先停止使用该列，部署验证
V009: ALTER TABLE DROP COLUMN ...; -- 确认无引用后再删
```

### 加列
- 新列必须有 DEFAULT 或允许 NULL（否则旧代码 INSERT 会失败）
- 新列加完后在应用层逐步填充

## 文件命名

```
v{NNN}_{描述}.py    例: v008_add_coupon_tables.py
```

- 序号三位数，连续递增
- 描述用英文 snake_case
- **禁止**重复 revision ID

## 每次迁移必须包含

1. `upgrade()` — 正向迁移
2. `downgrade()` — 反向回滚（不能是空的 pass）
3. 新表必须包含 `tenant_id` + RLS 策略
4. docstring 说明变更内容和原因

## 执行流程

```bash
# 1. 预检
./scripts/migrate.sh check

# 2. dev 环境先跑
DATABASE_URL=... ./scripts/migrate.sh up --no-backup

# 3. staging 环境跑
DATABASE_URL=... ./scripts/migrate.sh up

# 4. 生产环境跑（自动备份）
DATABASE_URL=... ./scripts/migrate.sh up
```

## 紧急回滚

```bash
# 方法1: alembic 回滚
./scripts/migrate.sh rollback

# 方法2: 从备份恢复（最后手段）
gunzip -c backups/tunxiang_os_20260328_120000.sql.gz | psql $DATABASE_URL
```
