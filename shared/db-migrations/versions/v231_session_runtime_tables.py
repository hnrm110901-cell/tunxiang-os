"""Session Runtime 数据模型 — session_runs / session_events / session_checkpoints
Revision: v231
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v231c"
down_revision = "v231b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()

    def _add_rls(table: str, prefix: str) -> None:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='{table}' AND policyname='{prefix}_tenant') THEN
                    EXECUTE 'CREATE POLICY {prefix}_tenant ON {table}
                        USING (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::UUID)
                        WITH CHECK (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::UUID)';
                END IF;
            END$$;
        """)



    # --- session_runs 任务运行实例 ---

    if 'session_runs' not in existing:
        op.create_table(
            "session_runs",
            sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
            sa.Column("session_id", sa.String(100), unique=True, nullable=False),
            sa.Column("agent_template_id", postgresql.UUID()),
            sa.Column("agent_template_name", sa.String(100)),
            sa.Column("store_id", postgresql.UUID()),
            sa.Column("trigger_type", sa.String(50), nullable=False),
            sa.Column("trigger_data", postgresql.JSON()),
            sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'created'")),
            sa.Column("plan_id", sa.String(100)),
            sa.Column("plan_snapshot", postgresql.JSON()),
            sa.Column("result_json", postgresql.JSON()),
            sa.Column("error_message", sa.Text()),
            sa.Column("total_steps", sa.Integer(), server_default=sa.text("0")),
            sa.Column("completed_steps", sa.Integer(), server_default=sa.text("0")),
            sa.Column("failed_steps", sa.Integer(), server_default=sa.text("0")),
            sa.Column("total_tokens", sa.Integer(), server_default=sa.text("0")),
            sa.Column("total_cost_fen", sa.Integer(), server_default=sa.text("0")),
            sa.Column("started_at", sa.TIMESTAMP(timezone=True)),
            sa.Column("finished_at", sa.TIMESTAMP(timezone=True)),
            sa.Column("tenant_id", postgresql.UUID(), nullable=False),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false")),
        )
        op.create_index("ix_sr_session_id", "session_runs", ["session_id"], unique=True)
        op.create_index("ix_sr_tenant", "session_runs", ["tenant_id"])
        op.create_index("ix_sr_store", "session_runs", ["store_id"])
        op.create_index("ix_session_run_status", "session_runs", ["status"])
        op.create_index("ix_session_run_store_time", "session_runs", ["store_id", "started_at"])
        _add_rls("session_runs", "sr")

        # --- session_events 事件记录 ---

    if 'session_events' not in existing:
        op.create_table(
            "session_events",
            sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
            sa.Column("session_id", postgresql.UUID(), sa.ForeignKey("session_runs.id"), nullable=False),
            sa.Column("sequence_no", sa.Integer(), nullable=False),
            sa.Column("event_type", sa.String(50), nullable=False),
            sa.Column("step_id", sa.String(100)),
            sa.Column("agent_id", sa.String(100)),
            sa.Column("action", sa.String(100)),
            sa.Column("input_json", postgresql.JSON()),
            sa.Column("output_json", postgresql.JSON()),
            sa.Column("reasoning", sa.Text()),
            sa.Column("tokens_used", sa.Integer(), server_default=sa.text("0")),
            sa.Column("duration_ms", sa.Integer(), server_default=sa.text("0")),
            sa.Column("inference_layer", sa.String(20)),
            sa.Column("tenant_id", postgresql.UUID(), nullable=False),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false")),
        )
        op.create_index("ix_se_session", "session_events", ["session_id"])
        op.create_index("ix_session_event_session_seq", "session_events", ["session_id", "sequence_no"])
        op.create_index("ix_se_tenant", "session_events", ["tenant_id"])
        _add_rls("session_events", "se")

        # --- session_checkpoints 断点记录 ---

    if 'session_checkpoints' not in existing:
        op.create_table(
            "session_checkpoints",
            sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
            sa.Column("session_id", postgresql.UUID(), sa.ForeignKey("session_runs.id"), nullable=False),
            sa.Column("step_id", sa.String(100), nullable=False),
            sa.Column("agent_id", sa.String(100)),
            sa.Column("reason", sa.String(50), nullable=False),
            sa.Column("reason_detail", sa.Text()),
            sa.Column("checkpoint_data", postgresql.JSON()),
            sa.Column("pending_action", postgresql.JSON()),
            sa.Column("resolution", sa.String(50)),
            sa.Column("resolved_by", sa.String(100)),
            sa.Column("resolved_at", sa.TIMESTAMP(timezone=True)),
            sa.Column("resolved_comment", sa.Text()),
            sa.Column("resumed_at", sa.TIMESTAMP(timezone=True)),
            sa.Column("tenant_id", postgresql.UUID(), nullable=False),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false")),
        )
        op.create_index("ix_sc_session", "session_checkpoints", ["session_id"])
        op.create_index("ix_sc_tenant", "session_checkpoints", ["tenant_id"])
        _add_rls("session_checkpoints", "sc")



def downgrade() -> None:
    op.drop_table("session_checkpoints")
    op.drop_table("session_events")
    op.drop_table("session_runs")
