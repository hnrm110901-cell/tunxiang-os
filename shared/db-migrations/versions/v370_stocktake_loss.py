"""盘亏处理审批闭环 — 案件 / 明细 / 审批 / 核销

新增 4 张表，构建 "盘点完成 → 案件登记 → 多级审批 → 财务核销" 完整链路：

  stocktake_loss_cases      — 盘亏案件主表（案件号 + 状态机 + 责任方）
  stocktake_loss_items      — 案件明细（每条食材一行 + 盘亏/盘盈金额）
  stocktake_loss_approvals  — 审批节点流水（按 approval_node_seq 顺序处理）
  stocktake_loss_writeoffs  — 财务核销凭证（一案件可能多次核销）

状态机（单向不可逆）：
  DRAFT → PENDING_APPROVAL → APPROVED → WRITTEN_OFF
                          ↓
                       REJECTED（终态）

审批链规则（按净亏损金额）：
  < 5000 元（500000 分）       — 仅店长审批（1 个节点）
  5000-50000 元                 — 店长 + 区域经理（2 个节点）
  > 50000 元（5000000 分）     — 店长 + 区域经理 + 财务（3 个节点）

RLS：使用 v064 同款标准（NULLIF + FORCE ROW LEVEL SECURITY）
案件号：LOSS-YYYYMMDD-NNNN（每天独立序列，避免跨日竞态）

Revision ID: v370
Revises: v365
Create Date: 2026-04-27
"""
from typing import Sequence, Union

from alembic import op

revision: str = "v370_stocktake_loss"
down_revision: Union[str, None] = "v365_forge_ecosystem_metrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ─────────────────────────────────────────────────────────────────────────────
# 安全 RLS 条件（v056+ 标准）
# ─────────────────────────────────────────────────────────────────────────────
_SAFE_CONDITION = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"
)

_LOSS_TABLES = [
    "stocktake_loss_cases",
    "stocktake_loss_items",
    "stocktake_loss_approvals",
    "stocktake_loss_writeoffs",
]


def _apply_safe_rls(table: str) -> None:
    """4 操作 PERMISSIVE + NULLIF NULL-guard + FORCE。"""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_select ON {table}")
    op.execute(
        f"CREATE POLICY {table}_rls_select ON {table} "
        f"FOR SELECT USING ({_SAFE_CONDITION})"
    )
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_insert ON {table}")
    op.execute(
        f"CREATE POLICY {table}_rls_insert ON {table} "
        f"FOR INSERT WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_update ON {table}")
    op.execute(
        f"CREATE POLICY {table}_rls_update ON {table} "
        f"FOR UPDATE USING ({_SAFE_CONDITION}) WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_delete ON {table}")
    op.execute(
        f"CREATE POLICY {table}_rls_delete ON {table} "
        f"FOR DELETE USING ({_SAFE_CONDITION})"
    )


def _create_updated_at_trigger(table: str) -> None:
    """为指定表创建 updated_at 自动维护 trigger。"""
    op.execute(f"""
        CREATE TRIGGER trg_{table}_updated_at
        BEFORE UPDATE ON {table}
        FOR EACH ROW
        EXECUTE FUNCTION fn_set_updated_at_v370();
    """)


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 0. 公共 trigger 函数：updated_at 自动维护（命名带 v370 防冲突）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION fn_set_updated_at_v370()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # ─────────────────────────────────────────────────────────────────
    # 1. stocktake_loss_cases — 盘亏案件主表
    #    case_status 单向状态机：
    #      DRAFT → PENDING_APPROVAL → APPROVED → WRITTEN_OFF
    #      REJECTED 为终态（任一审批节点驳回）
    #    net_loss = total_loss - total_gain（生成列）
    #    case_no 格式 LOSS-YYYYMMDD-NNNN（同租户当天唯一）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS stocktake_loss_cases (
            id                       UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id                UUID         NOT NULL,
            stocktake_id             UUID         NOT NULL,
            store_id                 UUID         NOT NULL,
            case_no                  VARCHAR(32)  NOT NULL,
            total_loss_amount_fen    BIGINT       NOT NULL DEFAULT 0
                                          CHECK (total_loss_amount_fen >= 0),
            total_gain_amount_fen    BIGINT       NOT NULL DEFAULT 0
                                          CHECK (total_gain_amount_fen >= 0),
            net_loss_amount_fen      BIGINT       GENERATED ALWAYS AS
                                          (total_loss_amount_fen - total_gain_amount_fen) STORED,
            responsible_party_type   VARCHAR(16)
                                          CHECK (responsible_party_type IN
                                          ('STORE','EMPLOYEE','SUPPLIER','UNKNOWN')),
            responsible_party_id     UUID,
            responsible_reason       TEXT,
            case_status              VARCHAR(16)  NOT NULL DEFAULT 'DRAFT'
                                          CHECK (case_status IN
                                          ('DRAFT','PENDING_APPROVAL','APPROVED','REJECTED','WRITTEN_OFF')),
            created_by               UUID         NOT NULL,
            submitted_at             TIMESTAMPTZ,
            final_approved_at        TIMESTAMPTZ,
            written_off_at           TIMESTAMPTZ,
            created_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted               BOOLEAN      NOT NULL DEFAULT FALSE,
            CONSTRAINT uq_stl_cases_tenant_caseno UNIQUE (tenant_id, case_no)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_stl_cases_tenant_status_created "
        "ON stocktake_loss_cases (tenant_id, case_status, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_stl_cases_tenant_stocktake "
        "ON stocktake_loss_cases (tenant_id, stocktake_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_stl_cases_tenant_store "
        "ON stocktake_loss_cases (tenant_id, store_id, created_at DESC) "
        "WHERE is_deleted = FALSE"
    )
    _create_updated_at_trigger("stocktake_loss_cases")
    _apply_safe_rls("stocktake_loss_cases")

    # ─────────────────────────────────────────────────────────────────
    # 2. stocktake_loss_items — 案件明细（每条食材一行）
    #    diff_qty = actual_qty - expected_qty（生成列）
    #    diff_qty < 0：盘亏；diff_qty > 0：盘盈
    #    diff_amount_fen 由 service 在 INSERT 时计算（绝对值 * unit_cost_fen）
    #    保留正负号语义（盘亏为负），便于汇总时区分
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS stocktake_loss_items (
            id              UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID           NOT NULL,
            case_id         UUID           NOT NULL
                                  REFERENCES stocktake_loss_cases(id) ON DELETE CASCADE,
            ingredient_id   UUID           NOT NULL,
            batch_no        VARCHAR(64),
            expected_qty    NUMERIC(14, 3) NOT NULL,
            actual_qty      NUMERIC(14, 3) NOT NULL,
            diff_qty        NUMERIC(14, 3) GENERATED ALWAYS AS (actual_qty - expected_qty) STORED,
            unit_cost_fen   BIGINT         NOT NULL CHECK (unit_cost_fen >= 0),
            diff_amount_fen BIGINT         NOT NULL DEFAULT 0,
            reason_code     VARCHAR(24)
                                  CHECK (reason_code IS NULL OR reason_code IN
                                  ('EXPIRED','BROKEN','THEFT','MEASUREMENT','UNRECORDED_USE','OTHER')),
            reason_detail   TEXT,
            created_at      TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN        NOT NULL DEFAULT FALSE
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_stl_items_tenant_case "
        "ON stocktake_loss_items (tenant_id, case_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_stl_items_tenant_ingredient "
        "ON stocktake_loss_items (tenant_id, ingredient_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_stl_items_tenant_reason "
        "ON stocktake_loss_items (tenant_id, reason_code) "
        "WHERE reason_code IS NOT NULL"
    )
    _create_updated_at_trigger("stocktake_loss_items")
    _apply_safe_rls("stocktake_loss_items")

    # ─────────────────────────────────────────────────────────────────
    # 3. stocktake_loss_approvals — 审批节点流水
    #    按 approval_node_seq 顺序处理：1, 2, 3...
    #    decision = NULL 表示待审批；APPROVED 进入下一节点；REJECTED 终止
    #    approver_role 校验在 service 层完成（不放 DB CHECK，便于扩展）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS stocktake_loss_approvals (
            id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID         NOT NULL,
            case_id             UUID         NOT NULL
                                      REFERENCES stocktake_loss_cases(id) ON DELETE CASCADE,
            approval_node_seq   INTEGER      NOT NULL CHECK (approval_node_seq >= 1),
            approver_role       VARCHAR(32)  NOT NULL
                                      CHECK (approver_role IN
                                      ('STORE_MANAGER','REGIONAL_MANAGER','FINANCE')),
            approver_id         UUID,
            decision            VARCHAR(16)
                                      CHECK (decision IS NULL OR decision IN
                                      ('APPROVED','REJECTED')),
            comment             TEXT,
            approved_at         TIMESTAMPTZ,
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN      NOT NULL DEFAULT FALSE,
            CONSTRAINT uq_stl_approvals_case_seq UNIQUE (case_id, approval_node_seq)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_stl_approvals_tenant_case_seq "
        "ON stocktake_loss_approvals (tenant_id, case_id, approval_node_seq)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_stl_approvals_tenant_pending "
        "ON stocktake_loss_approvals (tenant_id, approver_role) "
        "WHERE decision IS NULL"
    )
    _create_updated_at_trigger("stocktake_loss_approvals")
    _apply_safe_rls("stocktake_loss_approvals")

    # ─────────────────────────────────────────────────────────────────
    # 4. stocktake_loss_writeoffs — 财务核销凭证
    #    fk on delete RESTRICT：已核销不可删除案件
    #    writeoff_voucher_no 同租户唯一（避免重复入账）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS stocktake_loss_writeoffs (
            id                    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id             UUID         NOT NULL,
            case_id               UUID         NOT NULL
                                        REFERENCES stocktake_loss_cases(id) ON DELETE RESTRICT,
            writeoff_voucher_no   VARCHAR(64)  NOT NULL,
            writeoff_amount_fen   BIGINT       NOT NULL CHECK (writeoff_amount_fen > 0),
            accounting_subject    VARCHAR(64),
            writeoff_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            finance_user_id       UUID         NOT NULL,
            attachment_url        TEXT,
            comment               TEXT,
            created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted            BOOLEAN      NOT NULL DEFAULT FALSE,
            CONSTRAINT uq_stl_writeoffs_tenant_voucher UNIQUE (tenant_id, writeoff_voucher_no)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_stl_writeoffs_tenant_case "
        "ON stocktake_loss_writeoffs (tenant_id, case_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_stl_writeoffs_tenant_writeoffat "
        "ON stocktake_loss_writeoffs (tenant_id, writeoff_at DESC)"
    )
    _create_updated_at_trigger("stocktake_loss_writeoffs")
    _apply_safe_rls("stocktake_loss_writeoffs")

    # ─────────────────────────────────────────────────────────────────
    # 5. PG sequence + 函数：原子化生成案件号
    #    使用按天独立 sequence + advisory lock，避免高并发冲突
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS stocktake_loss_case_no_seq (
            tenant_id   UUID         NOT NULL,
            seq_date    DATE         NOT NULL,
            last_seq    INTEGER      NOT NULL DEFAULT 0,
            updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, seq_date)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_stl_caseno_seq_date "
        "ON stocktake_loss_case_no_seq (seq_date DESC)"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION fn_next_loss_case_no(
            p_tenant_id UUID,
            p_date DATE DEFAULT CURRENT_DATE
        ) RETURNS TEXT AS $$
        DECLARE
            v_next_seq INTEGER;
            v_date_str TEXT;
        BEGIN
            -- advisory lock 按 tenant + date hash 防止竞态
            PERFORM pg_advisory_xact_lock(
                hashtext(p_tenant_id::text || p_date::text)::bigint
            );

            INSERT INTO stocktake_loss_case_no_seq (tenant_id, seq_date, last_seq)
            VALUES (p_tenant_id, p_date, 1)
            ON CONFLICT (tenant_id, seq_date)
            DO UPDATE SET last_seq = stocktake_loss_case_no_seq.last_seq + 1,
                          updated_at = NOW()
            RETURNING last_seq INTO v_next_seq;

            v_date_str := to_char(p_date, 'YYYYMMDD');
            RETURN 'LOSS-' || v_date_str || '-' || lpad(v_next_seq::text, 4, '0');
        END;
        $$ LANGUAGE plpgsql;
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS fn_next_loss_case_no(UUID, DATE);")
    op.execute("DROP TABLE IF EXISTS stocktake_loss_case_no_seq CASCADE;")

    for table in reversed(_LOSS_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table};")
        for suffix in ("select", "insert", "update", "delete"):
            op.execute(f"DROP POLICY IF EXISTS {table}_rls_{suffix} ON {table};")
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")

    op.execute("DROP FUNCTION IF EXISTS fn_set_updated_at_v370();")
