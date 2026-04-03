"""v038: 外卖全链路补全 — delivery_store_configs + delivery_reviews + platform_health_snapshots

新增表：
  delivery_store_configs     — 门店外卖运营配置（自动接单/Busy Mode/出餐时间）
  delivery_reviews           — 外卖评价收集（差评预警）
  platform_health_snapshots  — 平台健康度每日快照

RLS 策略：
  全部使用 v006+ 标准安全模式（4操作 + NULL guard + FORCE ROW LEVEL SECURITY）

Revision ID: v038
Revises: v037
Create Date: 2026-03-30
"""

from alembic import op

revision = "v038"
down_revision = "v037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # delivery_store_configs — 门店外卖运营配置
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS delivery_store_configs (
            id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID        NOT NULL,
            store_id                UUID        NOT NULL,
            platform                VARCHAR(20) NOT NULL,
            auto_accept             BOOLEAN     NOT NULL DEFAULT false,
            auto_accept_max_per_hour INT        NOT NULL DEFAULT 30,
            busy_mode               BOOLEAN     NOT NULL DEFAULT false,
            busy_mode_prep_time_min INT         NOT NULL DEFAULT 40,
            normal_prep_time_min    INT         NOT NULL DEFAULT 25,
            busy_mode_started_at    TIMESTAMPTZ,
            busy_mode_auto_off_at   TIMESTAMPTZ,
            max_delivery_distance_km DECIMAL(5,2) NOT NULL DEFAULT 5.0,
            is_active               BOOLEAN     NOT NULL DEFAULT true,
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, store_id, platform),
            CONSTRAINT delivery_store_configs_platform_check
                CHECK (platform IN ('meituan', 'eleme', 'douyin'))
        );
    """)

    op.execute("ALTER TABLE delivery_store_configs ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE delivery_store_configs FORCE ROW LEVEL SECURITY;")

    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        op.execute(f"""
            CREATE POLICY delivery_store_configs_{action.lower()}_tenant
                ON delivery_store_configs
                AS RESTRICTIVE FOR {action}
                USING (
                    current_setting('app.tenant_id', TRUE) IS NOT NULL
                    AND current_setting('app.tenant_id', TRUE) <> ''
                    AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
                );
        """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_delivery_store_configs_tenant_store
            ON delivery_store_configs (tenant_id, store_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_delivery_store_configs_tenant_store_platform
            ON delivery_store_configs (tenant_id, store_id, platform);
    """)

    # ─────────────────────────────────────────────────────────────────
    # delivery_reviews — 外卖评价（差评预警）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS delivery_reviews (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID        NOT NULL,
            store_id            UUID        NOT NULL,
            platform            VARCHAR(20) NOT NULL,
            platform_order_id   VARCHAR(100),
            platform_review_id  VARCHAR(100) UNIQUE,
            rating              INT         NOT NULL,
            content             TEXT,
            tags                TEXT[],
            is_negative         BOOLEAN GENERATED ALWAYS AS (rating <= 3) STORED,
            reply_content       TEXT,
            replied_at          TIMESTAMPTZ,
            alert_sent          BOOLEAN     NOT NULL DEFAULT false,
            reviewed_at         TIMESTAMPTZ NOT NULL,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT delivery_reviews_rating_check
                CHECK (rating BETWEEN 1 AND 5),
            CONSTRAINT delivery_reviews_platform_check
                CHECK (platform IN ('meituan', 'eleme', 'douyin'))
        );
    """)

    op.execute("ALTER TABLE delivery_reviews ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE delivery_reviews FORCE ROW LEVEL SECURITY;")

    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        op.execute(f"""
            CREATE POLICY delivery_reviews_{action.lower()}_tenant
                ON delivery_reviews
                AS RESTRICTIVE FOR {action}
                USING (
                    current_setting('app.tenant_id', TRUE) IS NOT NULL
                    AND current_setting('app.tenant_id', TRUE) <> ''
                    AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
                );
        """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_delivery_reviews_tenant_store
            ON delivery_reviews (tenant_id, store_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_delivery_reviews_tenant_store_platform
            ON delivery_reviews (tenant_id, store_id, platform);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_delivery_reviews_is_negative
            ON delivery_reviews (tenant_id, store_id, is_negative, reviewed_at DESC);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_delivery_reviews_alert_sent
            ON delivery_reviews (tenant_id, alert_sent, is_negative)
            WHERE alert_sent = false;
    """)

    # ─────────────────────────────────────────────────────────────────
    # platform_health_snapshots — 平台健康度每日快照
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS platform_health_snapshots (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL,
            store_id        UUID        NOT NULL,
            platform        VARCHAR(20) NOT NULL,
            snapshot_date   DATE        NOT NULL,
            overall_score   DECIMAL(3,2),
            dsr_food        DECIMAL(3,2),
            dsr_service     DECIMAL(3,2),
            dsr_delivery    DECIMAL(3,2),
            monthly_sales   INT         NOT NULL DEFAULT 0,
            positive_rate   DECIMAL(5,4),
            bad_review_count INT        NOT NULL DEFAULT 0,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, store_id, platform, snapshot_date),
            CONSTRAINT platform_health_snapshots_platform_check
                CHECK (platform IN ('meituan', 'eleme', 'douyin'))
        );
    """)

    op.execute("ALTER TABLE platform_health_snapshots ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE platform_health_snapshots FORCE ROW LEVEL SECURITY;")

    for action in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        op.execute(f"""
            CREATE POLICY platform_health_snapshots_{action.lower()}_tenant
                ON platform_health_snapshots
                AS RESTRICTIVE FOR {action}
                USING (
                    current_setting('app.tenant_id', TRUE) IS NOT NULL
                    AND current_setting('app.tenant_id', TRUE) <> ''
                    AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
                );
        """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_platform_health_snapshots_tenant_store
            ON platform_health_snapshots (tenant_id, store_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_platform_health_snapshots_date
            ON platform_health_snapshots (tenant_id, store_id, platform, snapshot_date DESC);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS platform_health_snapshots;")
    op.execute("DROP TABLE IF EXISTS delivery_reviews;")
    op.execute("DROP TABLE IF EXISTS delivery_store_configs;")
