"""v270 — Sprint A3 离线订单号映射：offline_order_mapping

A3 离线订单号 UUID v7 + 死信待人工确认（Tier1 零容忍）。

表用途：
  - 前端（web-pos）或安卓 POS 离线时本地生成 order_id
    = `{device_id}:{ms_epoch}:{counter}` 字符串 + UUID v7 payload
  - 恢复联网后同步到云端，服务端生成 cloud_order_id（UUID）
  - offline_order_mapping 记录 offline_id → cloud_id 映射，供对账使用
  - 连续同步失败 20 次 → state='dead_letter'，不自动删除，等店长确认

设计约束：
  - tenant_id UUID NOT NULL + RLS（app.tenant_id）非 NULL 绑定
  - UNIQUE (tenant_id, offline_order_id) — 前端幂等 key 去重
  - state 枚举：pending / synced / dead_letter
  - 索引：
      ix_offline_order_mapping_tenant_state_created — 查某租户 backlog
      ix_offline_order_mapping_cloud_order_id       — cloud_order_id 反查
  - downgrade 可逆（幂等 DROP）

与 A2 saga_buffer_meta 的关系：
  - saga_buffer_meta 记录 Mac mini SagaBuffer 的心跳/健康
  - offline_order_mapping 记录每个 order_id 的 offline↔cloud 映射
  - 两表各自独立，均属 edge.offline 子域

Revision ID: v270
Revises: v269
Create Date: 2026-04-24
"""

import sqlalchemy as sa
from alembic import op

revision = "v270"
down_revision = "v269"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "offline_order_mapping" not in existing:
        op.execute("""
            CREATE TABLE offline_order_mapping (
                id UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
                tenant_id UUID NOT NULL,
                store_id UUID NOT NULL,
                device_id TEXT NOT NULL,
                offline_order_id TEXT NOT NULL,
                cloud_order_id UUID NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                sync_attempts INTEGER NOT NULL DEFAULT 0,
                dead_letter_reason TEXT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                synced_at TIMESTAMPTZ NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_offline_order_mapping_tenant_oid
                    UNIQUE (tenant_id, offline_order_id)
            );
        """)

        # state 枚举校验（pending / synced / dead_letter）
        op.execute("""
            ALTER TABLE offline_order_mapping
            ADD CONSTRAINT ck_offline_order_mapping_state
            CHECK (state IN ('pending', 'synced', 'dead_letter'));
        """)

        # 索引：backlog 扫描（租户 + 状态 + 时间）
        op.create_index(
            "ix_offline_order_mapping_tenant_state_created",
            "offline_order_mapping",
            ["tenant_id", "state", "created_at"],
        )

        # 索引：cloud_order_id 反查（对账路径）
        op.create_index(
            "ix_offline_order_mapping_cloud_order_id",
            "offline_order_mapping",
            ["cloud_order_id"],
            postgresql_where=sa.text("cloud_order_id IS NOT NULL"),
        )

    # RLS — app.tenant_id 非 NULL 强制租户隔离（§XIV 禁止 NULL 绕过）
    op.execute("ALTER TABLE offline_order_mapping ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS offline_order_mapping_tenant ON offline_order_mapping;")
    op.execute("""
        CREATE POLICY offline_order_mapping_tenant ON offline_order_mapping
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS offline_order_mapping_tenant ON offline_order_mapping;")
    op.execute("ALTER TABLE IF EXISTS offline_order_mapping DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP INDEX IF EXISTS ix_offline_order_mapping_cloud_order_id;")
    op.execute("DROP INDEX IF EXISTS ix_offline_order_mapping_tenant_state_created;")
    op.execute("ALTER TABLE IF EXISTS offline_order_mapping DROP CONSTRAINT IF EXISTS ck_offline_order_mapping_state;")
    op.execute("DROP TABLE IF EXISTS offline_order_mapping;")
