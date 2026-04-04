"""v147 — 统一事件存储表 (Unified Event Store)

Event Sourcing + CQRS 架构升级 Phase 1：
- 创建 events 核心表（append-only，不可变）
- RLS 多租户隔离（与现有架构一致）
- 按月分区（range partition by occurred_at）
- 触发器：自动发送 PG NOTIFY 供投影器消费
- PG 辅助函数：_merge_leak_types（JSONB计数器合并，供折扣投影器使用）

设计原则：
- 事件一旦写入不可修改（无 UPDATE/DELETE 权限）
- payload/metadata 均为 JSONB（支持 GIN 全文索引）
- causation_id 追踪因果链（哪个事件触发了我）
- 金额字段全部存分（整数），不存浮点

Revision: v147
"""

from alembic import op

revision = "v147"
down_revision = "v146"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 1. 事件存储主表（分区表）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS events (
            event_id        UUID            NOT NULL DEFAULT gen_random_uuid(),
            tenant_id       UUID            NOT NULL,
            store_id        UUID,
            stream_id       VARCHAR(255)    NOT NULL,
            stream_type     VARCHAR(64)     NOT NULL,
            event_type      VARCHAR(128)    NOT NULL,
            sequence_num    BIGINT          NOT NULL DEFAULT 0,
            occurred_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            recorded_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            payload         JSONB           NOT NULL DEFAULT '{}',
            metadata        JSONB           NOT NULL DEFAULT '{}',
            causation_id    UUID,
            correlation_id  UUID,
            schema_version  VARCHAR(16)     NOT NULL DEFAULT '1.0',
            source_service  VARCHAR(64)     NOT NULL DEFAULT 'unknown',
            CONSTRAINT events_pkey PRIMARY KEY (event_id, occurred_at)
        ) PARTITION BY RANGE (occurred_at)
    """)

    # ─────────────────────────────────────────────────────────────────
    # 2. 默认分区（兜底，防止无分区时写入报错）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS events_default
            PARTITION OF events DEFAULT
    """)

    # ─────────────────────────────────────────────────────────────────
    # 3. 2026年分区（按月）
    # ─────────────────────────────────────────────────────────────────
    for month in range(1, 13):
        m_start = f"{month:02d}"
        m_end = f"{(month % 12) + 1:02d}"
        end_year = 2027 if month == 12 else 2026
        op.execute(f"""
            CREATE TABLE IF NOT EXISTS events_2026_{m_start}
                PARTITION OF events
                FOR VALUES FROM ('2026-{m_start}-01') TO ('{end_year}-{m_end}-01')
        """)

    # ─────────────────────────────────────────────────────────────────
    # 4. 索引
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_tenant_time
            ON events (tenant_id, occurred_at DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_tenant_store
            ON events (tenant_id, store_id, occurred_at DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_stream
            ON events (tenant_id, stream_type, stream_id, sequence_num)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_type
            ON events (tenant_id, event_type, occurred_at DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_causation
            ON events (causation_id) WHERE causation_id IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_payload_gin
            ON events USING GIN (payload)
    """)

    # ─────────────────────────────────────────────────────────────────
    # 5. RLS 多租户隔离
    # ─────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE events FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS events_tenant_isolation ON events;")
    op.execute("""
        CREATE POLICY events_tenant_isolation ON events
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID)
    """)

    # ─────────────────────────────────────────────────────────────────
    # 6. 追加权限约束（防止 UPDATE/DELETE）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE RULE events_no_update AS
            ON UPDATE TO events DO INSTEAD NOTHING
    """)
    op.execute("""
        CREATE OR REPLACE RULE events_no_delete AS
            ON DELETE TO events DO INSTEAD NOTHING
    """)

    # ─────────────────────────────────────────────────────────────────
    # 7. PG NOTIFY 触发器（通知投影器消费）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION notify_event_inserted()
        RETURNS TRIGGER AS $$
        DECLARE
            payload JSONB;
        BEGIN
            payload := jsonb_build_object(
                'event_id',    NEW.event_id,
                'event_type',  NEW.event_type,
                'stream_type', NEW.stream_type,
                'tenant_id',   NEW.tenant_id,
                'store_id',    NEW.store_id,
                'occurred_at', NEW.occurred_at
            );
            PERFORM pg_notify('event_inserted', payload::TEXT);
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_events_notify
            AFTER INSERT ON events
            FOR EACH ROW EXECUTE FUNCTION notify_event_inserted()
    """)

    # ─────────────────────────────────────────────────────────────────
    # 8. 投影器游标表（记录每个投影器消费进度）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS projector_checkpoints (
            projector_name   VARCHAR(64)  NOT NULL,
            tenant_id        UUID         NOT NULL,
            last_event_id    UUID,
            last_occurred_at TIMESTAMPTZ,
            events_processed BIGINT       NOT NULL DEFAULT 0,
            last_rebuilt_at  TIMESTAMPTZ,
            updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            PRIMARY KEY (projector_name, tenant_id)
        )
    """)
    op.execute("ALTER TABLE projector_checkpoints ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE projector_checkpoints FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS projector_checkpoints_rls ON projector_checkpoints;")
    op.execute("""
        CREATE POLICY projector_checkpoints_rls ON projector_checkpoints
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID)
    """)

    # ─────────────────────────────────────────────────────────────────
    # 9. 辅助函数：_merge_leak_types（JSONB计数器合并）
    #    供 DiscountHealthProjector 增量更新泄漏类型分布使用
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION _merge_leak_types(base JSONB, delta JSONB)
        RETURNS JSONB AS $$
        DECLARE
            key TEXT;
            result JSONB := base;
        BEGIN
            FOR key IN SELECT jsonb_object_keys(delta) LOOP
                result := jsonb_set(
                    result,
                    ARRAY[key],
                    to_jsonb(COALESCE((result->>key)::INT, 0) + (delta->>key)::INT)
                );
            END LOOP;
            RETURN result;
        END;
        $$ LANGUAGE plpgsql IMMUTABLE
    """)

    # ─────────────────────────────────────────────────────────────────
    # 10. 注释
    # ─────────────────────────────────────────────────────────────────
    op.execute("COMMENT ON TABLE events IS '统一事件存储 — append-only，不可变，RLS多租户隔离'")
    op.execute("COMMENT ON COLUMN events.stream_id IS '聚合根ID，如订单号、会员ID'")
    op.execute("COMMENT ON COLUMN events.stream_type IS '聚合根类型：order/member/inventory/settlement等'")
    op.execute("COMMENT ON COLUMN events.causation_id IS '因果链追踪：哪个事件触发了我'")
    op.execute("COMMENT ON COLUMN events.correlation_id IS '业务相关ID：如同一次结账流程的所有事件共享'")
    op.execute("COMMENT ON COLUMN events.payload IS '业务数据（金额均为分/整数）'")
    op.execute("COMMENT ON COLUMN events.metadata IS '元数据：设备ID/操作员/渠道/版本号'")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_events_notify ON events")
    op.execute("DROP FUNCTION IF EXISTS notify_event_inserted()")
    op.execute("DROP FUNCTION IF EXISTS _merge_leak_types(JSONB, JSONB)")
    op.execute("DROP TABLE IF EXISTS projector_checkpoints")
    op.execute("DROP TABLE IF EXISTS events CASCADE")
