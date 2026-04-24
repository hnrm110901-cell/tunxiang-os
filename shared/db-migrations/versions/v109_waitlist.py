"""v109: 等位调度引擎 — waitlist_entries / waitlist_call_logs

新建 2 张表：
  waitlist_entries   — 等位队列主表（顾客等位信息、优先级、状态）
  waitlist_call_logs — 叫号记录流水（渠道/操作员/时间）

设计要点：
  - queue_no 按日递增（从101起），支持同店多日重置
  - priority: 0=普通, 10=会员, 20=银卡, 30=金卡, 40=黑金
  - status CHECK: waiting/called/seated/cancelled/expired
  - 过号降级：called超15分钟 → expired → 重置waiting/priority=-10
  - RLS: NULLIF(current_setting('app.tenant_id', true), '')::uuid 防NULL绕过
  - 索引覆盖 tenant_id/store_id/status/priority/created_at

Revision ID: v109
Revises: v108
Create Date: 2026-04-02
"""

from alembic import op

revision = "v109"
down_revision = "v108"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. 等位队列主表 ────────────────────────────────────────────────
    op.execute("""
CREATE TABLE IF NOT EXISTS waitlist_entries (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL,
    store_id            UUID NOT NULL,
    queue_no            INT NOT NULL,
    name                VARCHAR(50) NOT NULL,
    phone               VARCHAR(20),
    party_size          INT NOT NULL,
    table_type          VARCHAR(20),
    member_id           UUID,
    priority            INT NOT NULL DEFAULT 0,
    status              VARCHAR(20) NOT NULL DEFAULT 'waiting'
                            CHECK (status IN ('waiting', 'called', 'seated', 'cancelled', 'expired')),
    called_at           TIMESTAMPTZ,
    call_count          INT NOT NULL DEFAULT 0,
    seated_at           TIMESTAMPTZ,
    expired_at          TIMESTAMPTZ,
    estimated_wait_min  INT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
""")

    # 索引
    op.execute("CREATE INDEX IF NOT EXISTS idx_waitlist_entries_tenant_store ON waitlist_entries(tenant_id, store_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_waitlist_entries_store_status ON waitlist_entries(store_id, status);")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_waitlist_entries_priority_created ON waitlist_entries(store_id, priority DESC, created_at ASC);"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_waitlist_entries_queue_no ON waitlist_entries(store_id, queue_no);")

    # updated_at 自动更新触发器
    op.execute("""
CREATE OR REPLACE FUNCTION update_waitlist_entries_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;
""")
    op.execute("""
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'trg_waitlist_entries_updated_at'
  ) THEN
    CREATE TRIGGER trg_waitlist_entries_updated_at
    BEFORE UPDATE ON waitlist_entries
    FOR EACH ROW EXECUTE FUNCTION update_waitlist_entries_updated_at();
  END IF;
END;
$$;
""")

    # RLS
    op.execute("ALTER TABLE waitlist_entries ENABLE ROW LEVEL SECURITY;")
    op.execute("""
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'waitlist_entries' AND policyname = 'tenant_isolation'
  ) THEN
    CREATE POLICY tenant_isolation ON waitlist_entries
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
  END IF;
END;
$$;
""")

    # ── 2. 叫号记录流水表 ─────────────────────────────────────────────
    op.execute("""
CREATE TABLE IF NOT EXISTS waitlist_call_logs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL,
    entry_id    UUID NOT NULL REFERENCES waitlist_entries(id) ON DELETE CASCADE,
    channel     VARCHAR(20) NOT NULL DEFAULT 'screen'
                    CHECK (channel IN ('screen', 'sms', 'wechat')),
    called_by   VARCHAR(100),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
""")

    # 索引
    op.execute("CREATE INDEX IF NOT EXISTS idx_waitlist_call_logs_tenant ON waitlist_call_logs(tenant_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_waitlist_call_logs_entry ON waitlist_call_logs(entry_id);")

    # RLS
    op.execute("ALTER TABLE waitlist_call_logs ENABLE ROW LEVEL SECURITY;")
    op.execute("""
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'waitlist_call_logs' AND policyname = 'tenant_isolation'
  ) THEN
    CREATE POLICY tenant_isolation ON waitlist_call_logs
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
  END IF;
END;
$$;
""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS waitlist_call_logs;")
    op.execute("DROP TABLE IF EXISTS waitlist_entries;")
    op.execute("DROP FUNCTION IF EXISTS update_waitlist_entries_updated_at();")
