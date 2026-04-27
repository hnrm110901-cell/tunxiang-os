"""v269 — Sprint A2 Saga SQLite 本地缓冲元数据：saga_buffer_meta

云端 PG 表，用于汇总每个门店 Mac mini 本地 SQLite saga buffer 的状态：
  - buffer_count       — pending 条目数
  - dead_letter_count  — 超过 4h TTL 未补发的死信条目
  - last_flush_at      — 最近一次成功补发到云端的 UTC 时间
  - health_status      — healthy / degraded / stale（>10min 无心跳）

门店 mac-station 的 Flusher 成功补发后心跳一次(UPSERT)。
云端监控查询 `WHERE health_status <> 'healthy'` 定位需要介入的门店。

设计约束：
  - tenant_id NOT NULL + RLS（app.tenant_id）非 NULL 绑定
  - 主键 (tenant_id, store_id, device_id) — 一个门店可能多台 Mac mini
  - 索引覆盖查询"哪些店当前有 backlog"（tenant_id, store_id, health_status）
  - 金额/时间字段语义参考 shared/events/src/emitter.py，时间一律 TIMESTAMPTZ
  - downgrade 可逆（幂等删表 + 删 policy）

SQLite 端本地表 schema 在 edge/mac-station/src/saga_buffer/buffer.py
CREATE TABLE IF NOT EXISTS 声明，不走 alembic。

Revision ID: v269
Revises: v268
Create Date: 2026-04-24
"""
import sqlalchemy as sa
from alembic import op

revision = "v269"
down_revision = "v268"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "saga_buffer_meta" not in existing:
        op.execute("""
            CREATE TABLE saga_buffer_meta (
                tenant_id UUID NOT NULL,
                store_id UUID NOT NULL,
                device_id TEXT NOT NULL,
                buffer_count INTEGER NOT NULL DEFAULT 0,
                dead_letter_count INTEGER NOT NULL DEFAULT 0,
                last_flush_at TIMESTAMPTZ NULL,
                health_status TEXT NOT NULL DEFAULT 'healthy',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (tenant_id, store_id, device_id)
            );
        """)

        op.execute("""
            ALTER TABLE saga_buffer_meta
            ADD CONSTRAINT ck_saga_buffer_meta_health
            CHECK (health_status IN ('healthy', 'degraded', 'stale'));
        """)

        op.create_index(
            "ix_saga_buffer_meta_tenant_store_health",
            "saga_buffer_meta",
            ["tenant_id", "store_id", "health_status"],
        )

    # RLS — app.tenant_id 非 NULL 强制租户隔离（§XIV 禁止 NULL 绕过）
    op.execute("ALTER TABLE saga_buffer_meta ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS saga_buffer_meta_tenant ON saga_buffer_meta;")
    op.execute("""
        CREATE POLICY saga_buffer_meta_tenant ON saga_buffer_meta
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS saga_buffer_meta_tenant ON saga_buffer_meta;")
    op.execute("ALTER TABLE IF EXISTS saga_buffer_meta DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP INDEX IF EXISTS ix_saga_buffer_meta_tenant_store_health;")
    op.execute(
        "ALTER TABLE IF EXISTS saga_buffer_meta "
        "DROP CONSTRAINT IF EXISTS ck_saga_buffer_meta_health;"
    )
    op.execute("DROP TABLE IF EXISTS saga_buffer_meta;")
