"""v281 — 预订礼宾员邀请函与核餐电话记录表

对应规划：docs/reservation-roadmap-2026-q2.md §5.1
对应契约：docs/reservation-r2-contracts.md
依据路线图任务：
  reservation_concierge Agent 的
    - send_invitation  → 写 reservation_invitations (channel 任意 / status=sent)
    - confirm_arrival  → 写 reservation_invitations (channel=call, status=confirmed/pending)

本迁移只建表，不含业务路由。reservation_concierge Agent 在 Sprint R2 接入
5 个 action，其中 send_invitation / confirm_arrival 写本表。

表清单：
  reservation_invitations — 邀请函/核餐电话统一记录

金额单位：分（fen，整数，对齐 CLAUDE.md §15）
RLS：tenant_id = app.tenant_id（对齐 CLAUDE.md §14）
事件：R2ReservationEventType.INVITATION_SENT / CONFIRM_CALL_SENT / CONFIRMED / NO_SHOW

版本号分配说明：
  原规划 v230-v233，R1 实装时 v230-v263 已占用顺延为 v264-v267。
  R2 本应接续 v268/v269，但 v266_memory_evolution/v267_agent_episodes/
  v268_agent_procedures/v269_agent_memory_history 已在平行分支占用（见
  shared/db-migrations/versions/ 目录中的 SOP / 记忆进化系列），
  因此 R2 顺延到 v281 / v282。
  迁移链：v267_banquet_leads → v270_tasks_idem → v281 → v282
  （v270_tasks_idem 由独立验证 P1-2 修复插入，为 tasks 表补幂等唯一索引）

Revision: v281
Revises: v270_tasks_idem
Create Date: 2026-04-23
"""

from alembic import op

revision = "v281"
down_revision = "v270_tasks_idem"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 1. 枚举类型
    # ─────────────────────────────────────────────────────────────────
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE invitation_channel_enum AS ENUM (
                'sms',
                'wechat',
                'call'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE invitation_status_enum AS ENUM (
                'pending',
                'sent',
                'confirmed',
                'failed'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    # ─────────────────────────────────────────────────────────────────
    # 2. reservation_invitations 主表
    # ─────────────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS reservation_invitations (
            invitation_id       UUID                        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id           UUID                        NOT NULL,
            store_id            UUID,
            reservation_id      UUID                        NOT NULL,
            customer_id         UUID,
            channel             invitation_channel_enum     NOT NULL,
            status              invitation_status_enum      NOT NULL DEFAULT 'pending',
            sent_at             TIMESTAMPTZ,
            confirmed_at        TIMESTAMPTZ,
            coupon_code         VARCHAR(64),
            coupon_value_fen    BIGINT                      NOT NULL DEFAULT 0,
            failure_reason      VARCHAR(200),
            payload             JSONB                       NOT NULL DEFAULT '{}',
            source_event_id     UUID,
            created_at          TIMESTAMPTZ                 NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ                 NOT NULL DEFAULT NOW(),
            CONSTRAINT reservation_invitations_pkey PRIMARY KEY (invitation_id),
            CONSTRAINT reservation_invitations_coupon_fen_chk
                CHECK (coupon_value_fen >= 0),
            CONSTRAINT reservation_invitations_confirm_chk
                CHECK (
                    status <> 'confirmed' OR confirmed_at IS NOT NULL
                ),
            CONSTRAINT reservation_invitations_failed_chk
                CHECK (
                    status <> 'failed' OR failure_reason IS NOT NULL
                )
        )
        """
    )

    # 索引：按 (tenant_id, reservation_id) 查一次预订的所有邀请/外呼记录
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_resv_invitations_reservation
            ON reservation_invitations (tenant_id, reservation_id)
        """
    )
    # 索引：按 (tenant_id, customer_id) 查客户历史邀请
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_resv_invitations_customer
            ON reservation_invitations (tenant_id, customer_id)
            WHERE customer_id IS NOT NULL
        """
    )
    # 索引：按 (tenant_id, channel, status) 聚合接通质量/发送成功率
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_resv_invitations_channel_status
            ON reservation_invitations (tenant_id, channel, status)
        """
    )
    # 索引：按 sent_at 做时序分析（T-2h 核餐到店率曲线）
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_resv_invitations_sent_at
            ON reservation_invitations (tenant_id, sent_at DESC)
            WHERE sent_at IS NOT NULL
        """
    )
    # 索引：coupon_code 唯一定位（兑券反查）
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_resv_invitations_coupon
            ON reservation_invitations (tenant_id, coupon_code)
            WHERE coupon_code IS NOT NULL
        """
    )
    # GIN 索引：payload JSON 查询
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_resv_invitations_payload_gin
            ON reservation_invitations USING GIN (payload)
        """
    )

    # ─────────────────────────────────────────────────────────────────
    # 3. RLS 多租户隔离
    # ─────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE reservation_invitations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE reservation_invitations FORCE ROW LEVEL SECURITY")
    op.execute(
        "DROP POLICY IF EXISTS reservation_invitations_tenant ON reservation_invitations"
    )
    op.execute(
        """
        CREATE POLICY reservation_invitations_tenant ON reservation_invitations
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID)
        """
    )

    # ─────────────────────────────────────────────────────────────────
    # 4. 注释
    # ─────────────────────────────────────────────────────────────────
    op.execute(
        "COMMENT ON TABLE reservation_invitations IS "
        "'预订礼宾员邀请函/核餐外呼统一记录（R2 新增，对标食尚订邀请函+智能电话 Pro）'"
    )
    op.execute(
        "COMMENT ON COLUMN reservation_invitations.channel IS "
        "'发送渠道：sms/wechat/call（call 代表 AI 外呼）'"
    )
    op.execute(
        "COMMENT ON COLUMN reservation_invitations.status IS "
        "'生命周期：pending（排队）→ sent（已发）→ confirmed（客户确认）/ failed（失败）'"
    )
    op.execute(
        "COMMENT ON COLUMN reservation_invitations.coupon_value_fen IS "
        "'附带券面值（分/整数，对齐金额公约）'"
    )
    op.execute(
        "COMMENT ON COLUMN reservation_invitations.source_event_id IS "
        "'触发本次邀请的事件ID（可追溯因果链）'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reservation_invitations CASCADE")
    op.execute("DROP TYPE IF EXISTS invitation_status_enum")
    op.execute("DROP TYPE IF EXISTS invitation_channel_enum")
