"""v093: 设备注册表与心跳追踪

device_registry: 门店设备基本信息
  - device_id: UUID主键
  - tenant_id: 租户隔离
  - store_id: 关联门店
  - device_type: 'android_pos' | 'mac_mini' | 'android_tablet' | 'ipad' | 'printer' | 'kds'
  - device_name: 可读名称（如"1号收银台"）
  - hardware_model: 型号（如"商米T2"）
  - mac_address: MAC地址（唯一标识）
  - ip_address: 最后已知IP
  - app_version: 应用版本号
  - os_version: 系统版本
  - status: 'online' | 'offline' | 'maintenance'
  - last_heartbeat_at: 最后心跳时间
  - registered_at: 注册时间
  - created_at / updated_at

device_heartbeats: 心跳日志（保留7天）
  - id: UUID
  - device_id: FK device_registry
  - tenant_id
  - cpu_usage_pct: CPU使用率（0-100）
  - memory_usage_pct: 内存使用率
  - disk_usage_pct: 磁盘使用率
  - network_latency_ms: 到服务器延迟
  - app_version: 本次心跳时的版本
  - extra: JSONB（额外指标，如打印机状态）
  - created_at

设计要点：
  - device_registry 按 (tenant_id, mac_address) 建唯一索引，支持 UPSERT 去重
  - device_heartbeats 写入频繁，保留7天，按 created_at 建索引方便清理
  - RLS 使用 v006+ 标准（WITH CHECK 约束，禁NULL绕过），两张表都启用
  - status 用 VARCHAR(20) 不用枚举（便于扩展）

Revision ID: v093
Revises: v092
Create Date: 2026-03-31
"""

from alembic import op

revision = "v093"
down_revision = "v092"
branch_labels = None
depends_on = None

# v006+ 标准 RLS 条件（禁止 NULL 绕过）
_RLS_COND = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID"
)


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        policy_name = f"{table}_{action.lower()}_tenant"
        op.execute(
            f"CREATE POLICY {policy_name} "
            f"ON {table} FOR {action} "
            f"USING ({_RLS_COND}) "
            f"WITH CHECK ({_RLS_COND})"
        )


def upgrade() -> None:
    # ── device_registry：门店设备基本信息 ────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS device_registry (
            device_id         UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID         NOT NULL,
            store_id          UUID         NOT NULL,

            device_type       VARCHAR(30)  NOT NULL,
            device_name       VARCHAR(100) NOT NULL,
            hardware_model    VARCHAR(100),
            mac_address       VARCHAR(17)  NOT NULL,
            ip_address        VARCHAR(45),

            app_version       VARCHAR(50),
            os_version        VARCHAR(100),

            status            VARCHAR(20)  NOT NULL DEFAULT 'offline',

            last_heartbeat_at TIMESTAMPTZ,
            registered_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

            created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """)

    # 唯一索引：同一租户内 MAC 地址唯一（跨租户可重复）
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_device_registry_tenant_mac "
        "ON device_registry(tenant_id, mac_address)"
    )

    # 辅助查询索引
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_device_registry_store "
        "ON device_registry(tenant_id, store_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_device_registry_status "
        "ON device_registry(tenant_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_device_registry_heartbeat "
        "ON device_registry(tenant_id, last_heartbeat_at) "
        "WHERE status = 'online'"
    )

    _enable_rls("device_registry")

    # ── device_heartbeats：心跳日志（保留7天） ───────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS device_heartbeats (
            id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            device_id           UUID         NOT NULL
                                    REFERENCES device_registry(device_id) ON DELETE CASCADE,
            tenant_id           UUID         NOT NULL,

            cpu_usage_pct       NUMERIC(5,2),
            memory_usage_pct    NUMERIC(5,2),
            disk_usage_pct      NUMERIC(5,2),
            network_latency_ms  INTEGER,

            app_version         VARCHAR(50),
            extra               JSONB        DEFAULT '{}'::JSONB,

            created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """)

    # 按 device_id + created_at 查询最近心跳
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_device_heartbeats_device_time "
        "ON device_heartbeats(device_id, created_at DESC)"
    )
    # 按 tenant + created_at 支持7天清理
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_device_heartbeats_tenant_time "
        "ON device_heartbeats(tenant_id, created_at)"
    )

    _enable_rls("device_heartbeats")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS device_heartbeats CASCADE")
    op.execute("DROP TABLE IF EXISTS device_registry CASCADE")
