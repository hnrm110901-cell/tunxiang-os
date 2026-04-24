"""v271 — Sprint C3 边缘设备注册表：edge_device_registry

C3 KDS delta + device_kind 多终端统一注册（Tier1 零容忍）。

表用途：
  - 所有边缘设备（pos / kds / crew_phone / tv_menu / reception / mac_mini）
    首次心跳 → insert；后续每次 30s 心跳 → update last_seen_at
  - /kds/orders/delta 接口依赖本表判定 KDS 在线/离线
  - sync-engine Phase 1 通过 device_id + device_kind 双字段协议统一
    与 A3 offline_order_mapping 的 device_id 命名一致

设计约束（CLAUDE.md §6 + §17 Tier1）：
  - tenant_id UUID NOT NULL + RLS（app.tenant_id）非 NULL 绑定
  - PRIMARY KEY (tenant_id, device_id)：同一 device_id 在不同租户可复用
  - device_kind CHECK 枚举（6 个固定终端类型）
  - health_status CHECK ('healthy','degraded','offline','unknown')
  - 索引：
      idx_edge_device_tenant_store_kind  — 按租户+门店+终端类型查询
      idx_edge_device_last_seen          — 活跃设备扫描（partial where health != offline）
  - downgrade 可逆（幂等 DROP）

与 A3 v270 / A2 v269 的关系：
  - device_id TEXT 字段与 v270 offline_order_mapping.device_id / v269 saga_buffer_meta.device_id 同名同格式
  - 但本表不强制外键，三表各自独立（device 可能先登记再产生订单）

迁移号分配：
  - 规划 v264 已被 D2 agent_roi_fields 占用
  - 当前 head v270（A3 offline_order_mapping 之后）
  - 本次锁 v271

Revision ID: v271
Revises: v270
Create Date: 2026-04-24
"""

import sqlalchemy as sa
from alembic import op

revision = "v271"
down_revision = "v270"
branch_labels = None
depends_on = None


ALLOWED_DEVICE_KINDS = ("pos", "kds", "crew_phone", "tv_menu", "reception", "mac_mini")
ALLOWED_HEALTH = ("healthy", "degraded", "offline", "unknown")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "edge_device_registry" not in existing:
        op.execute(
            """
            CREATE TABLE edge_device_registry (
                tenant_id UUID NOT NULL,
                device_id TEXT NOT NULL,
                store_id UUID NOT NULL,
                device_kind TEXT NOT NULL,
                device_label TEXT NULL,
                os_version TEXT NULL,
                app_version TEXT NULL,
                last_seen_at TIMESTAMPTZ NULL,
                health_status TEXT NOT NULL DEFAULT 'unknown',
                buffer_backlog INTEGER NOT NULL DEFAULT 0,
                heartbeat_count INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT pk_edge_device_registry PRIMARY KEY (tenant_id, device_id)
            );
            """
        )

        # device_kind 枚举校验
        op.execute(
            f"""
            ALTER TABLE edge_device_registry
            ADD CONSTRAINT ck_edge_device_kind_enum
            CHECK (device_kind IN {ALLOWED_DEVICE_KINDS});
            """
        )

        # health_status 枚举校验
        op.execute(
            f"""
            ALTER TABLE edge_device_registry
            ADD CONSTRAINT ck_edge_device_health_enum
            CHECK (health_status IN {ALLOWED_HEALTH});
            """
        )

        # 索引：按租户+门店+终端类型查询（KDS 设备列表）
        op.create_index(
            "idx_edge_device_tenant_store_kind",
            "edge_device_registry",
            ["tenant_id", "store_id", "device_kind"],
        )

        # 索引：活跃设备扫描（partial where health != offline）
        op.create_index(
            "idx_edge_device_last_seen",
            "edge_device_registry",
            ["last_seen_at"],
            postgresql_where=sa.text("health_status != 'offline'"),
        )

    # RLS — app.tenant_id 非 NULL 强制租户隔离（CLAUDE.md §XIV 禁止 NULL 绕过）
    op.execute("ALTER TABLE edge_device_registry ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS edge_device_registry_tenant ON edge_device_registry;")
    op.execute(
        """
        CREATE POLICY edge_device_registry_tenant ON edge_device_registry
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS edge_device_registry_tenant ON edge_device_registry;")
    op.execute("ALTER TABLE IF EXISTS edge_device_registry DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP INDEX IF EXISTS idx_edge_device_last_seen;")
    op.execute("DROP INDEX IF EXISTS idx_edge_device_tenant_store_kind;")
    op.execute(
        "ALTER TABLE IF EXISTS edge_device_registry "
        "DROP CONSTRAINT IF EXISTS ck_edge_device_health_enum;"
    )
    op.execute(
        "ALTER TABLE IF EXISTS edge_device_registry "
        "DROP CONSTRAINT IF EXISTS ck_edge_device_kind_enum;"
    )
    op.execute("DROP TABLE IF EXISTS edge_device_registry;")
