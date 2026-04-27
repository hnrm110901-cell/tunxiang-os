"""v368: 配送在途温控告警 — 3 张表（thresholds/logs/alerts）

P0 任务 TASK-3：海鲜冷链场景下，配送车温度超限是命门。
新增三张表：
  delivery_temperature_thresholds  — 阈值配置（按 SKU/品类/温度类型/全局优先级）
  delivery_temperature_logs        — 时序温度数据（按月分区 + brin 索引）
  delivery_temperature_alerts      — 超限告警实例（合并连续超限）

RLS 策略：标准 NULLIF 安全模式，禁止 NULL 绕过。

Revision ID: v368_delivery_temperature
Revises: v365_forge_ecosystem_metrics
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "v368_delivery_temperature"
# 注意：v366/v367/v369/v370 由其他 P0 智能体并行生成，
# coordinator 合并时可能需要重排 down_revision；本分支单独跑通 alembic upgrade
# 时直接基于当前 head v365。
down_revision: Union[str, None] = "v365_forge_ecosystem_metrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RLS_CONDITION = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID"
)


def _enable_rls(table_name: str) -> None:
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
    for action, clause in [
        ("select", f"FOR SELECT USING ({_RLS_CONDITION})"),
        ("insert", f"FOR INSERT WITH CHECK ({_RLS_CONDITION})"),
        ("update", f"FOR UPDATE USING ({_RLS_CONDITION}) WITH CHECK ({_RLS_CONDITION})"),
        ("delete", f"FOR DELETE USING ({_RLS_CONDITION})"),
    ]:
        op.execute(
            f"CREATE POLICY {table_name}_rls_{action} ON {table_name} "
            f"AS PERMISSIVE {clause}"
        )


def _disable_rls(table_name: str) -> None:
    for suffix in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS {table_name}_rls_{suffix} ON {table_name}")
    op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")


_UPDATE_TIMESTAMP_FN = """
CREATE OR REPLACE FUNCTION trg_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def _attach_updated_at_trigger(table_name: str) -> None:
    op.execute(
        f"""
        CREATE TRIGGER trg_{table_name}_updated_at
        BEFORE UPDATE ON {table_name}
        FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
        """
    )


def upgrade() -> None:
    # 确保 trigger 函数存在（多次创建幂等）
    op.execute(_UPDATE_TIMESTAMP_FN)

    # ── 1. delivery_temperature_thresholds ─────────────────────────────────
    op.create_table(
        "delivery_temperature_thresholds",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "scope_type",
            sa.String(16),
            nullable=False,
            comment="GLOBAL|TEMPERATURE_TYPE|CATEGORY|SKU",
        ),
        sa.Column("scope_value", sa.String(64), nullable=True, comment="配合 scope_type 使用"),
        sa.Column("min_temp_celsius", sa.Numeric(5, 2), nullable=True),
        sa.Column("max_temp_celsius", sa.Numeric(5, 2), nullable=True),
        sa.Column("alert_min_seconds", sa.Integer, nullable=False, server_default=sa.text("60")),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.CheckConstraint(
            "scope_type IN ('GLOBAL','TEMPERATURE_TYPE','CATEGORY','SKU')",
            name="ck_delivery_temp_thresholds_scope_type",
        ),
    )
    op.create_index(
        "ix_delivery_temp_thresholds_tenant_scope",
        "delivery_temperature_thresholds",
        ["tenant_id", "scope_type", "scope_value"],
    )
    op.create_index(
        "ix_delivery_temp_thresholds_enabled",
        "delivery_temperature_thresholds",
        ["tenant_id", "enabled"],
    )
    _enable_rls("delivery_temperature_thresholds")
    _attach_updated_at_trigger("delivery_temperature_thresholds")

    # ── 2. delivery_temperature_logs（时序大表）────────────────────────────
    # 设计：按 recorded_at 月分区 + brin 索引（时序数据高效）。
    # 兼容性：默认创建 PARTITION BY RANGE 父表，但若 PG 版本不支持
    # 或测试场景使用普通表，这里通过 IF NOT EXISTS 兜底。
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS delivery_temperature_logs (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            delivery_id UUID NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL,
            temperature_celsius NUMERIC(5,2) NOT NULL,
            humidity_percent NUMERIC(5,2) NULL,
            gps_lat NUMERIC(10,7) NULL,
            gps_lng NUMERIC(10,7) NULL,
            device_id VARCHAR(64) NULL,
            source VARCHAR(16) NOT NULL DEFAULT 'DEVICE',
            extra JSONB NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
            PRIMARY KEY (id, recorded_at),
            CONSTRAINT ck_delivery_temp_logs_source CHECK (
                source IN ('DEVICE','MOBILE','MANUAL')
            )
        ) PARTITION BY RANGE (recorded_at);
        """
    )
    # 默认分区（兜底），生产应按月预创建
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS delivery_temperature_logs_default
        PARTITION OF delivery_temperature_logs DEFAULT;
        """
    )
    op.create_index(
        "ix_delivery_temp_logs_tenant_delivery_time",
        "delivery_temperature_logs",
        ["tenant_id", "delivery_id", sa.text("recorded_at DESC")],
    )
    op.create_index(
        "ix_delivery_temp_logs_recorded_at_brin",
        "delivery_temperature_logs",
        ["recorded_at"],
        postgresql_using="brin",
    )
    _enable_rls("delivery_temperature_logs")
    _attach_updated_at_trigger("delivery_temperature_logs")

    # ── 3. delivery_temperature_alerts ─────────────────────────────────────
    op.create_table(
        "delivery_temperature_alerts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("delivery_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "threshold_id",
            UUID(as_uuid=True),
            sa.ForeignKey("delivery_temperature_thresholds.id"),
            nullable=True,
        ),
        sa.Column("breach_type", sa.String(8), nullable=False, comment="HIGH|LOW"),
        sa.Column("breach_started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("breach_ended_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("peak_temperature_celsius", sa.Numeric(5, 2), nullable=True),
        sa.Column("threshold_min_celsius", sa.Numeric(5, 2), nullable=True),
        sa.Column("threshold_max_celsius", sa.Numeric(5, 2), nullable=True),
        sa.Column(
            "severity",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'WARNING'"),
            comment="INFO|WARNING|CRITICAL",
        ),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'ACTIVE'"),
            comment="ACTIVE|HANDLED|FALSE_POSITIVE",
        ),
        sa.Column("handled_by", UUID(as_uuid=True), nullable=True),
        sa.Column("handled_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("handle_comment", sa.Text, nullable=True),
        sa.Column("handle_action", sa.String(32), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.CheckConstraint(
            "breach_type IN ('HIGH','LOW')",
            name="ck_delivery_temp_alerts_breach_type",
        ),
        sa.CheckConstraint(
            "severity IN ('INFO','WARNING','CRITICAL')",
            name="ck_delivery_temp_alerts_severity",
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE','HANDLED','FALSE_POSITIVE')",
            name="ck_delivery_temp_alerts_status",
        ),
    )
    op.create_index(
        "ix_delivery_temp_alerts_tenant_status_started",
        "delivery_temperature_alerts",
        ["tenant_id", "status", sa.text("breach_started_at DESC")],
    )
    op.create_index(
        "ix_delivery_temp_alerts_tenant_delivery",
        "delivery_temperature_alerts",
        ["tenant_id", "delivery_id"],
    )
    _enable_rls("delivery_temperature_alerts")
    _attach_updated_at_trigger("delivery_temperature_alerts")


def downgrade() -> None:
    # 反向顺序：先 alerts (依赖 thresholds)
    op.execute("DROP TRIGGER IF EXISTS trg_delivery_temperature_alerts_updated_at ON delivery_temperature_alerts")
    _disable_rls("delivery_temperature_alerts")
    op.drop_index("ix_delivery_temp_alerts_tenant_delivery", table_name="delivery_temperature_alerts")
    op.drop_index("ix_delivery_temp_alerts_tenant_status_started", table_name="delivery_temperature_alerts")
    op.drop_table("delivery_temperature_alerts")

    op.execute("DROP TRIGGER IF EXISTS trg_delivery_temperature_logs_updated_at ON delivery_temperature_logs")
    _disable_rls("delivery_temperature_logs")
    op.execute("DROP INDEX IF EXISTS ix_delivery_temp_logs_recorded_at_brin")
    op.execute("DROP INDEX IF EXISTS ix_delivery_temp_logs_tenant_delivery_time")
    op.execute("DROP TABLE IF EXISTS delivery_temperature_logs_default")
    op.execute("DROP TABLE IF EXISTS delivery_temperature_logs")

    op.execute("DROP TRIGGER IF EXISTS trg_delivery_temperature_thresholds_updated_at ON delivery_temperature_thresholds")
    _disable_rls("delivery_temperature_thresholds")
    op.drop_index("ix_delivery_temp_thresholds_enabled", table_name="delivery_temperature_thresholds")
    op.drop_index("ix_delivery_temp_thresholds_tenant_scope", table_name="delivery_temperature_thresholds")
    op.drop_table("delivery_temperature_thresholds")
