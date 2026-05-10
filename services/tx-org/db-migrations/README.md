# tx-org alembic migrations

service 独立 alembic — Phase 4a 路线 a (per-service migrations)。

## Stamp 表
`tx_org_alembic_version` — 与其他 service 的 alembic_version 表互不冲突。

## 起手新 migration

```bash
cd services/tx-org/db-migrations
alembic revision -m "describe what changes"
# 编辑 versions/<rev>_describe_what_changes.py 写 upgrade/downgrade
```

## 跑 upgrade

```bash
DATABASE_URL=postgresql://... \
  alembic -c services/tx-org/db-migrations/alembic.ini \
  upgrade head
```

## CI 集成

`.github/workflows/migration-ci.yml` 中各 service alembic upgrade 并发跑（fresh PG）；
schema linter (`docs/migration-schema-lint-rules.md`) 7 类规则共用。

## 边界

- 仅放 tx-org 拥有的表（per `docs/migration-architecture-route-a-ownership-audit.md`）
- 跨 service 的表 / RLS 基础设施 / ENUM types：放 `shared/db-migrations-core/`
- 跨 service FK 用软引用（UUID 不强 FK 约束）

## Versions/

迁移文件命名：`v_<seq>_<short_desc>.py`，从 `v_001` 起。Phase 4a-4 baseline squash
会在此目录生成 `v_001_baseline.py` + `v_001_baseline.sql`（来自 production
pg_dump --schema-only 拆出本 service 拥有的表）。
