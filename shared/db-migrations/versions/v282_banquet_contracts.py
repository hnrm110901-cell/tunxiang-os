"""v282 — 宴会合同 / EO 工单 / 审批日志三表

对应规划：docs/reservation-roadmap-2026-q2.md §5.3
对应契约：docs/reservation-r2-contracts.md
依据路线图任务：
  banquet_contract_agent 5 个 action：
    - generate_contract  → 写 banquet_contracts (status=draft/pending_approval)
    - split_eo           → 写 banquet_eo_tickets (5 部门，每部门 1 条)
    - route_approval     → 写 banquet_approval_logs (action=approve/reject)
    - lock_schedule      → 更新 banquet_contracts (status=signed)
    - progress_reminder  → 读 banquet_eo_tickets (T-7d/T-3d/T-1d/T-2h 推送)

本迁移只建表，不含业务路由。banquet_contract_agent 在 Sprint R2 接入 5 action。

表清单：
  banquet_contracts       — 合同主表（与 banquet_leads.lead_id 关联）
  banquet_eo_tickets      — EO 工单（合同 → 厨房/前厅/采购/营销/财务 5 部门）
  banquet_approval_logs   — 合同审批日志（简单自动过 / 10W+ 店长 / 50W+ 区经）

金额单位：分（fen，整数，对齐 CLAUDE.md §15）
RLS：tenant_id = app.tenant_id（对齐 CLAUDE.md §14）
事件：
  BanquetContractEventType.CONTRACT_GENERATED / CONTRACT_SIGNED /
                           EO_DISPATCHED / APPROVAL_ROUTED / SCHEDULE_LOCKED

外键策略：
  - banquet_contracts.lead_id 指向 banquet_leads(lead_id)，但不加 FK 约束（跨服务弱耦合）
  - banquet_eo_tickets.contract_id / banquet_approval_logs.contract_id 加 FK 约束
    （同服务内强一致，便于 CASCADE 删除）

Revision: v282
Revises: v281
Create Date: 2026-04-23
"""

from alembic import op

revision = "v282"
down_revision = "v281"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 1. 枚举类型
    # ─────────────────────────────────────────────────────────────────
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE banquet_contract_status_enum AS ENUM (
                'draft',
                'pending_approval',
                'signed',
                'cancelled'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE banquet_eo_department_enum AS ENUM (
                'kitchen',
                'hall',
                'purchase',
                'finance',
                'marketing'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE banquet_eo_status_enum AS ENUM (
                'pending',
                'dispatched',
                'in_progress',
                'completed'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE banquet_approval_action_enum AS ENUM (
                'approve',
                'reject'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE banquet_approval_role_enum AS ENUM (
                'store_manager',
                'district_manager',
                'finance_manager'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    # 复用 v267_banquet_leads 中的 banquet_type_enum（不重复定义）

    # ─────────────────────────────────────────────────────────────────
    # 2. banquet_contracts 主表
    # ─────────────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS banquet_contracts (
            contract_id         UUID                            NOT NULL DEFAULT gen_random_uuid(),
            tenant_id           UUID                            NOT NULL,
            store_id            UUID,
            lead_id             UUID                            NOT NULL,
            customer_id         UUID                            NOT NULL,
            sales_employee_id   UUID,
            banquet_type        banquet_type_enum               NOT NULL,
            tables              INTEGER                         NOT NULL DEFAULT 0,
            total_amount_fen    BIGINT                          NOT NULL DEFAULT 0,
            deposit_fen         BIGINT                          NOT NULL DEFAULT 0,
            pdf_url             VARCHAR(500),
            status              banquet_contract_status_enum    NOT NULL DEFAULT 'draft',
            approval_chain      JSONB                           NOT NULL DEFAULT '[]',
            scheduled_date      DATE,
            signed_at           TIMESTAMPTZ,
            cancelled_at        TIMESTAMPTZ,
            cancellation_reason VARCHAR(200),
            metadata            JSONB                           NOT NULL DEFAULT '{}',
            created_by          UUID,
            created_at          TIMESTAMPTZ                     NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ                     NOT NULL DEFAULT NOW(),
            CONSTRAINT banquet_contracts_pkey PRIMARY KEY (contract_id),
            CONSTRAINT banquet_contracts_tables_chk CHECK (tables >= 0),
            CONSTRAINT banquet_contracts_total_chk  CHECK (total_amount_fen >= 0),
            CONSTRAINT banquet_contracts_deposit_chk
                CHECK (deposit_fen >= 0 AND deposit_fen <= total_amount_fen),
            CONSTRAINT banquet_contracts_signed_chk
                CHECK (status <> 'signed' OR signed_at IS NOT NULL),
            CONSTRAINT banquet_contracts_cancel_chk
                CHECK (
                    status <> 'cancelled'
                    OR (cancelled_at IS NOT NULL AND cancellation_reason IS NOT NULL)
                )
        )
        """
    )

    # 索引：按 (tenant_id, lead_id) 反查合同（一条商机最多一条签约合同）
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_banquet_contracts_lead
            ON banquet_contracts (tenant_id, lead_id)
        """
    )
    # 索引：按 (tenant_id, customer_id) 查客户合同历史
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_banquet_contracts_customer
            ON banquet_contracts (tenant_id, customer_id)
        """
    )
    # 索引：按 (tenant_id, status, sales_employee_id) 查销售经理签约漏斗
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_banquet_contracts_status_sales
            ON banquet_contracts (tenant_id, status, sales_employee_id)
        """
    )
    # 索引：按 scheduled_date 做档期视图
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_banquet_contracts_scheduled
            ON banquet_contracts (tenant_id, scheduled_date)
            WHERE scheduled_date IS NOT NULL
        """
    )
    # 索引：按 total_amount_fen 做审批路由（10W / 50W 阈值）
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_banquet_contracts_amount
            ON banquet_contracts (tenant_id, total_amount_fen DESC)
        """
    )
    # GIN 索引：approval_chain / metadata
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_banquet_contracts_approval_gin
            ON banquet_contracts USING GIN (approval_chain)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_banquet_contracts_metadata_gin
            ON banquet_contracts USING GIN (metadata)
        """
    )

    # ─────────────────────────────────────────────────────────────────
    # 3. banquet_eo_tickets 表
    # ─────────────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS banquet_eo_tickets (
            eo_ticket_id        UUID                        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id           UUID                        NOT NULL,
            contract_id         UUID                        NOT NULL,
            department          banquet_eo_department_enum  NOT NULL,
            assignee_employee_id UUID,
            content             JSONB                       NOT NULL DEFAULT '{}',
            status              banquet_eo_status_enum      NOT NULL DEFAULT 'pending',
            dispatched_at       TIMESTAMPTZ,
            completed_at        TIMESTAMPTZ,
            reminder_sent_at    TIMESTAMPTZ,
            created_at          TIMESTAMPTZ                 NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ                 NOT NULL DEFAULT NOW(),
            CONSTRAINT banquet_eo_tickets_pkey PRIMARY KEY (eo_ticket_id),
            CONSTRAINT banquet_eo_tickets_contract_fk
                FOREIGN KEY (contract_id)
                REFERENCES banquet_contracts (contract_id)
                ON DELETE CASCADE,
            CONSTRAINT banquet_eo_tickets_dispatched_chk
                CHECK (status <> 'dispatched' OR dispatched_at IS NOT NULL),
            CONSTRAINT banquet_eo_tickets_completed_chk
                CHECK (status <> 'completed' OR completed_at IS NOT NULL)
        )
        """
    )

    # 索引：按 (tenant_id, contract_id) 展开一合同下的 5 部门工单
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_banquet_eo_contract
            ON banquet_eo_tickets (tenant_id, contract_id)
        """
    )
    # 索引：按 (tenant_id, department, status) 查各部门待办
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_banquet_eo_department_status
            ON banquet_eo_tickets (tenant_id, department, status)
        """
    )
    # 索引：按 assignee_employee_id 查个人待办
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_banquet_eo_assignee
            ON banquet_eo_tickets (tenant_id, assignee_employee_id)
            WHERE assignee_employee_id IS NOT NULL
        """
    )
    # GIN 索引：content JSON
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_banquet_eo_content_gin
            ON banquet_eo_tickets USING GIN (content)
        """
    )

    # ─────────────────────────────────────────────────────────────────
    # 4. banquet_approval_logs 表
    # ─────────────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS banquet_approval_logs (
            log_id              UUID                            NOT NULL DEFAULT gen_random_uuid(),
            tenant_id           UUID                            NOT NULL,
            contract_id         UUID                            NOT NULL,
            approver_id         UUID                            NOT NULL,
            role                banquet_approval_role_enum      NOT NULL,
            action              banquet_approval_action_enum    NOT NULL,
            notes               VARCHAR(500),
            source_event_id     UUID,
            created_at          TIMESTAMPTZ                     NOT NULL DEFAULT NOW(),
            CONSTRAINT banquet_approval_logs_pkey PRIMARY KEY (log_id),
            CONSTRAINT banquet_approval_logs_contract_fk
                FOREIGN KEY (contract_id)
                REFERENCES banquet_contracts (contract_id)
                ON DELETE CASCADE,
            CONSTRAINT banquet_approval_logs_reject_chk
                CHECK (action <> 'reject' OR notes IS NOT NULL)
        )
        """
    )

    # 索引：按 (tenant_id, contract_id, created_at) 回放审批链
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_banquet_approval_contract_ts
            ON banquet_approval_logs (tenant_id, contract_id, created_at)
        """
    )
    # 索引：按审批人查个人审批历史
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_banquet_approval_approver
            ON banquet_approval_logs (tenant_id, approver_id)
        """
    )
    # 索引：按 role+action 做审批 SLA 统计
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_banquet_approval_role_action
            ON banquet_approval_logs (tenant_id, role, action)
        """
    )

    # ─────────────────────────────────────────────────────────────────
    # 5. RLS 多租户隔离（3 表）
    # ─────────────────────────────────────────────────────────────────
    for table in ("banquet_contracts", "banquet_eo_tickets", "banquet_approval_logs"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant ON {table}")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant ON {table}
                USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID)
                WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID)
            """
        )

    # ─────────────────────────────────────────────────────────────────
    # 6. 注释
    # ─────────────────────────────────────────────────────────────────
    op.execute(
        "COMMENT ON TABLE banquet_contracts IS "
        "'宴会合同主表（R2 新增，对标食尚订电子合同 + EO 工单）'"
    )
    op.execute(
        "COMMENT ON COLUMN banquet_contracts.lead_id IS "
        "'对应 banquet_leads.lead_id（跨服务弱耦合，不加 FK）'"
    )
    op.execute(
        "COMMENT ON COLUMN banquet_contracts.approval_chain IS "
        "'审批链快照 JSON：[{role, approver_id, required_threshold_fen}]'"
    )
    op.execute(
        "COMMENT ON COLUMN banquet_contracts.total_amount_fen IS "
        "'合同总金额（分/整数，≥10W 触发店长审批、≥50W 触发区经审批）'"
    )
    op.execute(
        "COMMENT ON TABLE banquet_eo_tickets IS "
        "'EO 工单 — 一份合同自动拆到 5 部门（厨房/前厅/采购/营销/财务）'"
    )
    op.execute(
        "COMMENT ON COLUMN banquet_eo_tickets.content IS "
        "'工单内容 JSON：菜单 / 订台 / 供应 / 物料 / 账单等部门专用字段'"
    )
    op.execute(
        "COMMENT ON TABLE banquet_approval_logs IS "
        "'合同审批留痕（每次 approve/reject 写一条，幂等留痕）'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS banquet_approval_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS banquet_eo_tickets CASCADE")
    op.execute("DROP TABLE IF EXISTS banquet_contracts CASCADE")
    op.execute("DROP TYPE IF EXISTS banquet_approval_role_enum")
    op.execute("DROP TYPE IF EXISTS banquet_approval_action_enum")
    op.execute("DROP TYPE IF EXISTS banquet_eo_status_enum")
    op.execute("DROP TYPE IF EXISTS banquet_eo_department_enum")
    op.execute("DROP TYPE IF EXISTS banquet_contract_status_enum")
