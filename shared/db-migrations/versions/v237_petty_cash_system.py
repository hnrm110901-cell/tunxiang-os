"""备用金管理系统：账户 + 流水 + 月末核销单

Tables: petty_cash_accounts, petty_cash_transactions, petty_cash_settlements
Sprint: P0-S3 预建表（服务层在P0-S3实现）

Revision ID: v237b
Revises: v236
Create Date: 2026-04-12
"""

from alembic import op

revision = "v237b"
down_revision = "v236"
branch_labels = None
depends_on = None

# 标准安全 RLS 条件（NULLIF 保护，与 v231 规范一致）
_RLS_COND = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"


def upgrade() -> None:
    # ──────────────────────────────────────────────────────────────────
    # petty_cash_accounts — 备用金账户
    # 每个门店只有一个备用金账户（UNIQUE store_id）
    # ──────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS petty_cash_accounts (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID        NOT NULL,
            store_id            UUID        NOT NULL UNIQUE,
            brand_id            UUID        NOT NULL,
            account_name        VARCHAR(100) NOT NULL DEFAULT '门店备用金',
            balance             BIGINT      NOT NULL DEFAULT 0,
            approved_limit      BIGINT      NOT NULL,
            warning_threshold   BIGINT      NOT NULL,
            daily_avg_7d        BIGINT      DEFAULT 0,
            keeper_id           UUID        NOT NULL,
            status              VARCHAR(20) NOT NULL DEFAULT 'active',
            frozen_reason       TEXT,
            frozen_at           TIMESTAMPTZ,
            last_reconciled_at  TIMESTAMPTZ,
            pos_session_ref     VARCHAR(100),
            created_at          TIMESTAMPTZ DEFAULT now(),
            updated_at          TIMESTAMPTZ DEFAULT now()
        );

        COMMENT ON TABLE petty_cash_accounts IS
            '备用金账户：每个门店一个账户，记录当前余额、审批额度上限和预警阈值，支持冻结和关闭状态';

        COMMENT ON COLUMN petty_cash_accounts.store_id IS
            '门店ID，UNIQUE 约束确保每个门店只有一个备用金账户';
        COMMENT ON COLUMN petty_cash_accounts.balance IS
            '当前余额，单位：分(fen)；由应用层在每次 transaction 写入后同步更新，保持与 petty_cash_transactions.balance_after 最新值一致';
        COMMENT ON COLUMN petty_cash_accounts.approved_limit IS
            '审批额度上限，单位：分(fen)；超过此额度的补充申请需额外审批';
        COMMENT ON COLUMN petty_cash_accounts.warning_threshold IS
            '预警阈值，单位：分(fen)；余额低于此值时由 A1Agent 推送预警通知';
        COMMENT ON COLUMN petty_cash_accounts.daily_avg_7d IS
            '近7日日均消耗，单位：分(fen)；由 A1Agent 定时计算并更新，用于预测补充时机';
        COMMENT ON COLUMN petty_cash_accounts.keeper_id IS
            '保管人员工ID（通常是店长），对应 employees.id；账户冻结时关联离职员工ID';
        COMMENT ON COLUMN petty_cash_accounts.status IS
            '账户状态：active=正常使用 / frozen=临时冻结（员工离职时等待归还确认）/ closed=已注销';
        COMMENT ON COLUMN petty_cash_accounts.frozen_reason IS
            '冻结原因，status=frozen 时必填，如"店长离职，备用金待归还确认"';
        COMMENT ON COLUMN petty_cash_accounts.last_reconciled_at IS
            '最后一次日结对账时间，与 POS 日结数据比对后更新';
        COMMENT ON COLUMN petty_cash_accounts.pos_session_ref IS
            '最后对账关联的 POS 日结ID，与 tx-ops 日结单关联';

        CREATE UNIQUE INDEX IF NOT EXISTS uq_petty_cash_accounts_tenant_store
            ON petty_cash_accounts (tenant_id, store_id);

        CREATE INDEX IF NOT EXISTS ix_petty_cash_accounts_tenant_brand_status
            ON petty_cash_accounts (tenant_id, brand_id, status);

        CREATE INDEX IF NOT EXISTS ix_petty_cash_accounts_tenant_keeper
            ON petty_cash_accounts (tenant_id, keeper_id);
    """)

    op.execute("ALTER TABLE petty_cash_accounts ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE petty_cash_accounts FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY petty_cash_accounts_rls ON petty_cash_accounts
            USING ({_RLS_COND})
            WITH CHECK ({_RLS_COND});
    """)

    # ──────────────────────────────────────────────────────────────────
    # petty_cash_transactions — 备用金流水
    # 每笔流水记录金额变动、操作后余额和关联业务单据
    # ──────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS petty_cash_transactions (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID        NOT NULL,
            account_id          UUID        NOT NULL REFERENCES petty_cash_accounts(id),
            transaction_type    VARCHAR(30) NOT NULL,
            amount              BIGINT      NOT NULL,
            balance_after       BIGINT      NOT NULL,
            description         VARCHAR(200) NOT NULL,
            reference_id        UUID,
            reference_type      VARCHAR(50),
            operator_id         UUID        NOT NULL,
            is_reconciled       BOOLEAN     DEFAULT false,
            reconciled_at       TIMESTAMPTZ,
            expense_date        DATE        NOT NULL DEFAULT CURRENT_DATE,
            notes               TEXT,
            created_at          TIMESTAMPTZ DEFAULT now()
        );

        COMMENT ON TABLE petty_cash_transactions IS
            '备用金流水：记录每一笔收支变动，正数为收入（补充/归还），负数为支出（日常使用/日结调整），支持月末核销';

        COMMENT ON COLUMN petty_cash_transactions.transaction_type IS
            '交易类型 — income类：replenishment=补充备用金 / return_from_keeper=员工归还；expense类：daily_use=日常支出 / pos_reconcile_adjust=日结调整；system类：opening_balance=期初录入 / freeze_reserve=冻结备用';
        COMMENT ON COLUMN petty_cash_transactions.amount IS
            '交易金额，单位：分(fen)；正数=收入，负数=支出';
        COMMENT ON COLUMN petty_cash_transactions.balance_after IS
            '本次交易后余额，单位：分(fen)；由应用层在每次 transaction 写入时同步计算，值应与 petty_cash_accounts.balance 保持一致（即最新一笔流水的 balance_after = 账户当前 balance）';
        COMMENT ON COLUMN petty_cash_transactions.reference_id IS
            '关联业务单据ID，如费用申请ID/POS日结ID/核销单ID；可为 NULL（无关联单据时）';
        COMMENT ON COLUMN petty_cash_transactions.reference_type IS
            '关联单据类型：expense_application=费用申请单 / pos_session=POS日结 / settlement=月末核销单';
        COMMENT ON COLUMN petty_cash_transactions.operator_id IS
            '操作人员工ID，对应 employees.id；记录是谁录入了这笔流水';
        COMMENT ON COLUMN petty_cash_transactions.is_reconciled IS
            '是否已核销；false=未核销（月末核销单中标红提示），true=已纳入核销单确认';
        COMMENT ON COLUMN petty_cash_transactions.expense_date IS
            '费用发生日期（业务日期），用于月末核销单的区间统计，与 created_at（系统录入时间）可能不同';

        CREATE INDEX IF NOT EXISTS ix_petty_cash_transactions_tenant_account_created
            ON petty_cash_transactions (tenant_id, account_id, created_at DESC);

        CREATE INDEX IF NOT EXISTS ix_petty_cash_transactions_tenant_account_reconciled
            ON petty_cash_transactions (tenant_id, account_id, is_reconciled);

        CREATE INDEX IF NOT EXISTS ix_petty_cash_transactions_tenant_reference
            ON petty_cash_transactions (tenant_id, reference_id);
    """)

    op.execute("ALTER TABLE petty_cash_transactions ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE petty_cash_transactions FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY petty_cash_transactions_rls ON petty_cash_transactions
            USING ({_RLS_COND})
            WITH CHECK ({_RLS_COND});
    """)

    # ──────────────────────────────────────────────────────────────────
    # petty_cash_settlements — 月末核销单
    # 每个账户每月一张，由 A1Agent 自动生成 draft，财务人工确认后 closed
    # ──────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS petty_cash_settlements (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID        NOT NULL,
            account_id          UUID        NOT NULL REFERENCES petty_cash_accounts(id),
            store_id            UUID        NOT NULL,
            settlement_month    VARCHAR(7)  NOT NULL,
            period_start        DATE        NOT NULL,
            period_end          DATE        NOT NULL,
            opening_balance     BIGINT      NOT NULL,
            total_income        BIGINT      NOT NULL DEFAULT 0,
            total_expense       BIGINT      NOT NULL DEFAULT 0,
            closing_balance     BIGINT      NOT NULL,
            reconciled_count    INTEGER     DEFAULT 0,
            unreconciled_count  INTEGER     DEFAULT 0,
            status              VARCHAR(20) NOT NULL DEFAULT 'draft',
            notes               TEXT,
            generated_by        VARCHAR(20) DEFAULT 'a1_agent',
            confirmed_by        UUID,
            confirmed_at        TIMESTAMPTZ,
            created_at          TIMESTAMPTZ DEFAULT now(),
            updated_at          TIMESTAMPTZ DEFAULT now()
        );

        COMMENT ON TABLE petty_cash_settlements IS
            '月末核销单：每个备用金账户每自然月自动生成一张，汇总期间收支明细，经财务确认后关闭';

        COMMENT ON COLUMN petty_cash_settlements.settlement_month IS
            '核销月份，格式：YYYY-MM，如 2026-04；与 UNIQUE(tenant_id, account_id, settlement_month) 约束确保每月唯一';
        COMMENT ON COLUMN petty_cash_settlements.opening_balance IS
            '期初余额，单位：分(fen)；等于上月核销单的 closing_balance，首月为账户 opening_balance 流水的 balance_after';
        COMMENT ON COLUMN petty_cash_settlements.total_income IS
            '本期收入合计，单位：分(fen)；统计 period_start～period_end 内所有 amount>0 的流水之和';
        COMMENT ON COLUMN petty_cash_settlements.total_expense IS
            '本期支出合计，单位：分(fen)；统计 period_start～period_end 内所有 amount<0 的流水绝对值之和';
        COMMENT ON COLUMN petty_cash_settlements.closing_balance IS
            '期末余额，单位：分(fen)；= opening_balance + total_income - total_expense，应与账户实际余额一致';
        COMMENT ON COLUMN petty_cash_settlements.reconciled_count IS
            '已核销流水笔数；已关联业务单据且 is_reconciled=true 的 transactions 数量';
        COMMENT ON COLUMN petty_cash_settlements.unreconciled_count IS
            '未核销流水笔数；is_reconciled=false 的 transactions 数量，财务核销单中标红提示，需人工逐笔核查';
        COMMENT ON COLUMN petty_cash_settlements.status IS
            '核销单状态：draft=A1Agent 自动生成待确认 / submitted=提交财务审核 / confirmed=财务已确认 / closed=已归档关闭';
        COMMENT ON COLUMN petty_cash_settlements.generated_by IS
            '生成方式：a1_agent=系统自动生成 / manual=财务手工创建';
        COMMENT ON COLUMN petty_cash_settlements.confirmed_by IS
            '财务确认人员工ID，对应 employees.id；status=confirmed 时必填';

        CREATE UNIQUE INDEX IF NOT EXISTS uq_petty_cash_settlements_tenant_account_month
            ON petty_cash_settlements (tenant_id, account_id, settlement_month);

        CREATE INDEX IF NOT EXISTS ix_petty_cash_settlements_tenant_store_month
            ON petty_cash_settlements (tenant_id, store_id, settlement_month);

        CREATE INDEX IF NOT EXISTS ix_petty_cash_settlements_tenant_status
            ON petty_cash_settlements (tenant_id, status);
    """)

    op.execute("ALTER TABLE petty_cash_settlements ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE petty_cash_settlements FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY petty_cash_settlements_rls ON petty_cash_settlements
            USING ({_RLS_COND})
            WITH CHECK ({_RLS_COND});
    """)


def downgrade() -> None:
    # 按依赖顺序反向删除（先删叶子表，后删被引用表）

    # petty_cash_settlements（引用 petty_cash_accounts）
    op.execute("DROP POLICY IF EXISTS petty_cash_settlements_rls ON petty_cash_settlements;")
    op.execute("DROP TABLE IF EXISTS petty_cash_settlements CASCADE;")

    # petty_cash_transactions（引用 petty_cash_accounts）
    op.execute("DROP POLICY IF EXISTS petty_cash_transactions_rls ON petty_cash_transactions;")
    op.execute("DROP TABLE IF EXISTS petty_cash_transactions CASCADE;")

    # petty_cash_accounts（被上两张表引用，最后删）
    op.execute("DROP POLICY IF EXISTS petty_cash_accounts_rls ON petty_cash_accounts;")
    op.execute("DROP TABLE IF EXISTS petty_cash_accounts CASCADE;")
