"""v280 — financial_vouchers 红冲审计字段 [Tier1]

[§19 安全 P1-4 + CFO P1-7 响应 / Wave 2 Batch 2]

背景:
  W1.5 red_flush_service 的 operator_id + reason **只进 structlog 日志**, 不入 DB.
  问题:
    1. 日志轮转 (默认 30-90 天) 后红冲操作员 / 原因消失
    2. 金税四期要求凭证审计链**保存 10 年**, 日志不够
    3. DB 与日志聚合系统 (ELK) 权限边界不同, 审计链路分裂
    4. void 有 voided_by/reason 入 DB, 红冲语义不对称 (感觉像漏)

修复:
  ADD 3 列 (对齐 void 字段风格):
    - red_flush_operator_id UUID  (操作员)
    - red_flush_reason VARCHAR(200) (原因, 审计必读)
    - red_flushed_at TIMESTAMPTZ (操作时间)

  CHECK chk_voucher_red_flush_audit:
    红字凭证 (red_flush_of_voucher_id 非空) 必须有 red_flush_operator_id
    + red_flushed_at (reason 应用层强制, DB 允许 NULL 兼容历史).

  这与 W1.2 void 的 chk_voucher_void_consistency 对称.

Tier 级别: Tier 1 (金税四期审计完整性).

上线 Runbook:
- ADD COLUMN 3 列 NULLABLE: 瞬时
- CHECK 约束: 现有红字凭证 red_flush_operator_id=NULL, 会违反 CHECK
  → 迁移前必须先 UPDATE 回填 (没有则 CHECK NOT VALID 延迟校验)
  → W1.5 刚上线, 生产红字凭证量应极少或零, 直接 CHECK 即可
  → 若已有历史红冲: 迁移预检 SQL 见 docstring

Revision ID: v280
Revises: v278
Create Date: 2026-04-19
"""
from alembic import op


revision = "v280"
down_revision = "v278"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DO $$ BEGIN RAISE NOTICE 'v280 step 1/3: ADD 3 red_flush audit columns'; END $$;")
    op.execute("""
        ALTER TABLE financial_vouchers
            ADD COLUMN IF NOT EXISTS red_flush_operator_id UUID,
            ADD COLUMN IF NOT EXISTS red_flush_reason VARCHAR(200),
            ADD COLUMN IF NOT EXISTS red_flushed_at TIMESTAMPTZ;
    """)

    # CHECK: 红字凭证必须有审计留痕
    # 用 NOT VALID 首次添加 (跳过历史行校验), W1.5 历史红冲量极少.
    # 后续手工 VALIDATE CONSTRAINT 或新数据强制.
    op.execute("DO $$ BEGIN RAISE NOTICE 'v280 step 2/3: CHECK red_flush audit (NOT VALID for existing rows)'; END $$;")
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'chk_voucher_red_flush_audit'
            ) THEN
                ALTER TABLE financial_vouchers
                    ADD CONSTRAINT chk_voucher_red_flush_audit CHECK (
                        red_flush_of_voucher_id IS NULL
                        OR (
                            red_flush_operator_id IS NOT NULL
                            AND red_flushed_at IS NOT NULL
                        )
                    ) NOT VALID;
            END IF;
        END $$;
    """)

    op.execute("DO $$ BEGIN RAISE NOTICE 'v280 step 3/3: column comments'; END $$;")
    op.execute("""
        COMMENT ON COLUMN financial_vouchers.red_flush_operator_id IS
            '[W2.F v280] 红冲操作员 UUID. 红字凭证必填 (DB CHECK).';
        COMMENT ON COLUMN financial_vouchers.red_flush_reason IS
            '[W2.F v280] 红冲原因 (审计必读). 应用层强制非空, DB 允许 NULL 兼容历史.';
        COMMENT ON COLUMN financial_vouchers.red_flushed_at IS
            '[W2.F v280] 红冲操作时间. 红字凭证必填 (DB CHECK).';
    """)

    op.execute("DO $$ BEGIN RAISE NOTICE 'v280 upgrade complete'; END $$;")


def downgrade() -> None:
    op.execute("DO $$ BEGIN RAISE NOTICE 'v280 downgrade: DROP audit columns (金税四期审计数据丢!)'; END $$;")
    op.execute("""
        ALTER TABLE financial_vouchers
            DROP CONSTRAINT IF EXISTS chk_voucher_red_flush_audit;
    """)
    op.execute("""
        ALTER TABLE financial_vouchers
            DROP COLUMN IF EXISTS red_flush_operator_id,
            DROP COLUMN IF EXISTS red_flush_reason,
            DROP COLUMN IF EXISTS red_flushed_at;
    """)
    op.execute("DO $$ BEGIN RAISE NOTICE 'v280 downgrade complete'; END $$;")
