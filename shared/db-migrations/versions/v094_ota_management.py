"""v094: OTA 版本管理

app_versions: 版本发布记录
  - tenant_id NULL = 全局版本，非NULL = 租户专属版本
  - target_type: android_pos | mac_mini | android_tablet | ipad | all
  - version_code: 递增整数（如 31000 = v3.10.0），用于比较
  - min_version_code: 低于此版本强制升级
  - is_forced: 是否强制升级
  - rollout_pct: 灰度发布百分比 0-100

ota_check_logs: 设备检查记录（统计升级进度）

Revision ID: v094
Revises: v093
Create Date: 2026-04-01
"""

from alembic import op
import sqlalchemy as sa

revision = "v094"
down_revision = "v093"
branch_labels = None
depends_on = None

_RLS_COND = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID"
)

# app_versions 支持全局版本（tenant_id IS NULL），RLS 条件特殊处理
_VERSIONS_RLS_COND = (
    "tenant_id IS NULL OR ("
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID)"
)


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS app_versions (
            id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID,
            target_type       VARCHAR(30)  NOT NULL,
            version_name      VARCHAR(50)  NOT NULL,
            version_code      INTEGER      NOT NULL,
            min_version_code  INTEGER      NOT NULL DEFAULT 0,
            download_url      VARCHAR(500) NOT NULL,
            file_sha256       VARCHAR(64),
            file_size_bytes   BIGINT,
            release_notes     TEXT,
            is_forced         BOOLEAN      NOT NULL DEFAULT FALSE,
            is_active         BOOLEAN      NOT NULL DEFAULT TRUE,
            rollout_pct       SMALLINT     NOT NULL DEFAULT 100,
            created_by        UUID,
            created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_app_versions_query "
        "ON app_versions(tenant_id, target_type, is_active, version_code DESC)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_app_versions_tenant_type_code "
        "ON app_versions(COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::UUID), "
        "target_type, version_code)"
    )

    op.execute("ALTER TABLE app_versions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE app_versions FORCE ROW LEVEL SECURITY")
    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        using_clause = f"USING ({_VERSIONS_RLS_COND})" if action != "INSERT" else ""
        check_clause = f"WITH CHECK ({_VERSIONS_RLS_COND})" if action in ("INSERT", "UPDATE") else ""
        op.execute(
            f"CREATE POLICY app_versions_{action.lower()}_tenant "
            f"ON app_versions FOR {action} "
            f"{using_clause} "
            f"{check_clause}"
        )

    op.execute("""
        CREATE TABLE IF NOT EXISTS ota_check_logs (
            id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            device_id            UUID,
            tenant_id            UUID        NOT NULL,
            current_version_code INTEGER,
            latest_version_code  INTEGER,
            has_update           BOOLEAN,
            is_forced            BOOLEAN,
            checked_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ota_check_logs_device "
        "ON ota_check_logs(device_id, checked_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ota_check_logs_tenant "
        "ON ota_check_logs(tenant_id, checked_at DESC)"
    )
    op.execute("ALTER TABLE ota_check_logs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ota_check_logs FORCE ROW LEVEL SECURITY")
    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        using_clause = f"USING ({_RLS_COND})" if action != "INSERT" else ""
        check_clause = f"WITH CHECK ({_RLS_COND})" if action in ("INSERT", "UPDATE") else ""
        op.execute(
            f"CREATE POLICY ota_check_logs_{action.lower()}_tenant "
            f"ON ota_check_logs FOR {action} "
            f"{using_clause} "
            f"{check_clause}"
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ota_check_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS app_versions CASCADE")
