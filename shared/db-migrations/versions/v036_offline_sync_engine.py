"""v036: 离线收银引擎 — offline_order_queue + sync_checkpoints

新增表：
  offline_order_queue  — 断网时订单本地暂存队列（pending/syncing/synced/conflict）
  sync_checkpoints     — 设备级同步状态追踪（last_pull_seq / last_push_at）

RLS 策略：
  全部使用 v006+ 标准安全模式（4操作 + NULL guard + FORCE ROW LEVEL SECURITY）

Revision ID: v036
Revises: v035
Create Date: 2026-03-30
"""

from alembic import op

revision = "v036"
down_revision = "v035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # offline_order_queue — 离线订单暂存队列
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS offline_order_queue (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID        NOT NULL,
            store_id            UUID        NOT NULL,
            local_order_id      VARCHAR(64) NOT NULL,
            order_data          JSONB       NOT NULL,
            items_data          JSONB       NOT NULL,
            payments_data       JSONB,
            sync_status         VARCHAR(20) NOT NULL DEFAULT 'pending',
            created_offline_at  TIMESTAMPTZ NOT NULL,
            synced_at           TIMESTAMPTZ,
            conflict_reason     TEXT,
            retry_count         INT         NOT NULL DEFAULT 0,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT offline_order_queue_sync_status_check
                CHECK (sync_status IN ('pending', 'syncing', 'synced', 'conflict'))
        );
    """)

    op.execute("ALTER TABLE offline_order_queue ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE offline_order_queue FORCE ROW LEVEL SECURITY;")

    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        op.execute(f"""
            CREATE POLICY offline_order_queue_{action.lower()}_tenant ON offline_order_queue
            AS RESTRICTIVE FOR {action}
            USING (
                current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
        """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_offline_order_queue_tenant_store
            ON offline_order_queue (tenant_id, store_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_offline_order_queue_sync_status
            ON offline_order_queue (tenant_id, sync_status);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_offline_order_queue_local_order_id
            ON offline_order_queue (tenant_id, local_order_id);
    """)

    # ─────────────────────────────────────────────────────────────────
    # sync_checkpoints — 设备同步状态追踪
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS sync_checkpoints (
            id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id    UUID        NOT NULL,
            store_id     UUID        NOT NULL,
            device_id    VARCHAR(64) NOT NULL,
            last_pull_seq BIGINT     NOT NULL DEFAULT 0,
            last_push_at TIMESTAMPTZ,
            last_pull_at TIMESTAMPTZ,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, store_id, device_id)
        );
    """)

    op.execute("ALTER TABLE sync_checkpoints ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE sync_checkpoints FORCE ROW LEVEL SECURITY;")

    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        op.execute(f"""
            CREATE POLICY sync_checkpoints_{action.lower()}_tenant ON sync_checkpoints
            AS RESTRICTIVE FOR {action}
            USING (
                current_setting('app.tenant_id', TRUE) IS NOT NULL
                AND current_setting('app.tenant_id', TRUE) <> ''
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
        """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_sync_checkpoints_tenant_store_device
            ON sync_checkpoints (tenant_id, store_id, device_id);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sync_checkpoints;")
    op.execute("DROP TABLE IF EXISTS offline_order_queue;")
