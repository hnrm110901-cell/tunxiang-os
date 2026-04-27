"""v290 — 预订电话集成（呼叫中心）

3张新表：
  - call_records          — 通话记录（来电/去电/回拨）
  - call_customer_matches — 来电客户匹配（自动识别来电客户）
  - callback_tasks        — 回拨任务（未接/确认预订/跟进）

所有表启用 RLS 租户隔离。

Revision ID: v290
Revises: v289
Create Date: 2026-04-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "v290"
down_revision: Union[str, None] = "v289"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── call_records ──
    op.execute("""
    CREATE TABLE call_records (
        tenant_id       UUID          NOT NULL,
        id              UUID          DEFAULT gen_random_uuid() PRIMARY KEY,
        store_id        UUID          NOT NULL,
        caller_phone    VARCHAR(20),
        caller_name     VARCHAR(100),
        call_type       VARCHAR(20)   CHECK (call_type IN ('inbound', 'outbound', 'callback')),
        duration_sec    INTEGER,
        recording_url   TEXT,
        agent_ext       VARCHAR(20),
        customer_id     UUID,
        status          VARCHAR(20)   CHECK (status IN ('ringing', 'answered', 'missed', 'voicemail')),
        started_at      TIMESTAMPTZ,
        ended_at        TIMESTAMPTZ,
        notes           TEXT,
        created_at      TIMESTAMPTZ   DEFAULT now(),
        updated_at      TIMESTAMPTZ   DEFAULT now(),
        is_deleted      BOOLEAN       DEFAULT FALSE
    );

    ALTER TABLE call_records ENABLE ROW LEVEL SECURITY;
    CREATE POLICY call_records_tenant ON call_records
        USING (tenant_id = current_setting('app.tenant_id', true)::UUID);

    CREATE INDEX ix_call_records_tenant_store_started
        ON call_records (tenant_id, store_id, started_at DESC);
    CREATE INDEX ix_call_records_caller_phone
        ON call_records (caller_phone);
    CREATE INDEX ix_call_records_status
        ON call_records (status);
    """)

    # ── call_customer_matches ──
    op.execute("""
    CREATE TABLE call_customer_matches (
        tenant_id       UUID          NOT NULL,
        id              UUID          DEFAULT gen_random_uuid() PRIMARY KEY,
        call_record_id  UUID          NOT NULL REFERENCES call_records(id),
        customer_id     UUID          NOT NULL,
        match_type      VARCHAR(20),
        confidence      NUMERIC(3,2),
        matched_at      TIMESTAMPTZ   DEFAULT now(),
        created_at      TIMESTAMPTZ   DEFAULT now(),
        updated_at      TIMESTAMPTZ   DEFAULT now(),
        is_deleted      BOOLEAN       DEFAULT FALSE
    );

    ALTER TABLE call_customer_matches ENABLE ROW LEVEL SECURITY;
    CREATE POLICY call_customer_matches_tenant ON call_customer_matches
        USING (tenant_id = current_setting('app.tenant_id', true)::UUID);
    """)

    # ── callback_tasks ──
    op.execute("""
    CREATE TABLE callback_tasks (
        tenant_id       UUID          NOT NULL,
        id              UUID          DEFAULT gen_random_uuid() PRIMARY KEY,
        store_id        UUID          NOT NULL,
        call_record_id  UUID          REFERENCES call_records(id),
        customer_id     UUID,
        callback_phone  VARCHAR(20)   NOT NULL,
        reason          VARCHAR(30)   CHECK (reason IN ('confirm_reservation', 'follow_up', 'missed_call', 'custom')),
        status          VARCHAR(20)   CHECK (status IN ('pending', 'in_progress', 'completed', 'cancelled')),
        assigned_to     UUID,
        scheduled_at    TIMESTAMPTZ,
        completed_at    TIMESTAMPTZ,
        notes           TEXT,
        created_at      TIMESTAMPTZ   DEFAULT now(),
        updated_at      TIMESTAMPTZ   DEFAULT now(),
        is_deleted      BOOLEAN       DEFAULT FALSE
    );

    ALTER TABLE callback_tasks ENABLE ROW LEVEL SECURITY;
    CREATE POLICY callback_tasks_tenant ON callback_tasks
        USING (tenant_id = current_setting('app.tenant_id', true)::UUID);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS callback_tasks CASCADE;")
    op.execute("DROP TABLE IF EXISTS call_customer_matches CASCADE;")
    op.execute("DROP TABLE IF EXISTS call_records CASCADE;")
