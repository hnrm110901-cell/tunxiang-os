"""v272 — financial_vouchers 红冲链接字段 [Tier1]

背景:
  W1.2 引入 void 状态机 (draft/confirmed 可作废, exported 拒绝).
  exported 凭证已推送 ERP (金蝶/用友), 删改违反金税四期:
    - 必须新建一张\"反向凭证\" (红字凭证) 入账
    - 原凭证 + 红冲凭证双向 link, 形成审计可溯链
    - closed/locked 账期也允许红冲 (红冲本身才是唯一合法的修正路径)

  W1.5 引入两个字段建立红冲关系:
    red_flush_of_voucher_id     — 本凭证是哪个原凭证的红冲
    red_flushed_by_voucher_id   — 本凭证被哪个红冲凭证冲正 (反向 link)

变更:
  1. ADD COLUMN red_flush_of_voucher_id UUID
     - 指向被红冲的原凭证 (本凭证是红字凭证时非空)
     - FK to financial_vouchers(id), ON DELETE RESTRICT
  2. ADD COLUMN red_flushed_by_voucher_id UUID
     - 指向红冲此凭证的红字凭证 (本凭证被红冲时非空)
     - FK to financial_vouchers(id), ON DELETE RESTRICT
  3. CHECK chk_voucher_red_flush_exclusive:
     red_flush_of_voucher_id IS NULL OR red_flushed_by_voucher_id IS NULL
     → 一张凭证不能同时是红冲凭证且被红冲 (防红冲链递归)
  4. UNIQUE ix_fv_red_flushed_by WHERE red_flushed_by_voucher_id IS NOT NULL
     → 一张凭证最多被红冲一次 (重复红冲语义不清)
  5. 索引:
     - ix_fv_red_flush_of   (red_flush_of_voucher_id) WHERE NOT NULL
       查\"这张原凭证有没有被红冲过\"
     - UNIQUE (red_flushed_by_voucher_id) WHERE NOT NULL (同上, 充当索引)

  注意: 不加红冲凭证 status 约束 — 状态仍沿用 draft/confirmed/exported,
  红冲凭证本身也会走 ERP 推送. 是否红冲通过 red_flush_of 字段判定, 不是 status.

Tier 级别: Tier 1 (资金安全 / 金税四期审计红线)

──────────────────────────────────────────────────────────────────────
【上线 Runbook】
──────────────────────────────────────────────────────────────────────

🕐 窗口: 03:00 — 06:00. 禁: 20:00 — 02:00.

🔒 锁:
  - ADD COLUMN (2 列, nullable) — 瞬时.
  - CHECK ADD — 瞬时 (新列都是 NULL, CHECK 立即满足).
  - CREATE INDEX CONCURRENTLY (2 个 partial) — 不阻塞 DML.

📊 回填: 本 PR 不回填. 红冲是新功能, 历史没有红冲关系需要追溯.

⚠️ downgrade: DROP COLUMN 会丢所有红冲关系. 超 24h 视为不可降级.

Revision ID: v272
Revises: v270
Create Date: 2026-04-19
"""
from alembic import op


revision = "v272"
down_revision = "v270"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── step 1/4: ADD 2 columns ───────────────────────────────────────
    op.execute("DO $$ BEGIN RAISE NOTICE 'v272 step 1/4: ADD 2 red_flush columns'; END $$;")
    op.execute("""
        ALTER TABLE financial_vouchers
            ADD COLUMN IF NOT EXISTS red_flush_of_voucher_id   UUID,
            ADD COLUMN IF NOT EXISTS red_flushed_by_voucher_id UUID;
    """)

    # ── step 2/4: FK 双向引用 ─────────────────────────────────────────
    op.execute("DO $$ BEGIN RAISE NOTICE 'v272 step 2/4: ADD FK red_flush links'; END $$;")
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_fv_red_flush_of'
            ) THEN
                ALTER TABLE financial_vouchers
                    ADD CONSTRAINT fk_fv_red_flush_of
                        FOREIGN KEY (red_flush_of_voucher_id)
                        REFERENCES financial_vouchers(id)
                        ON DELETE RESTRICT;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_fv_red_flushed_by'
            ) THEN
                ALTER TABLE financial_vouchers
                    ADD CONSTRAINT fk_fv_red_flushed_by
                        FOREIGN KEY (red_flushed_by_voucher_id)
                        REFERENCES financial_vouchers(id)
                        ON DELETE RESTRICT;
            END IF;
        END $$;
    """)

    # ── step 3/4: CHECK 互斥 (防红冲链) ───────────────────────────────
    op.execute("DO $$ BEGIN RAISE NOTICE 'v272 step 3/4: CHECK red_flush exclusive'; END $$;")
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'chk_voucher_red_flush_exclusive'
            ) THEN
                ALTER TABLE financial_vouchers
                    ADD CONSTRAINT chk_voucher_red_flush_exclusive CHECK (
                        red_flush_of_voucher_id IS NULL
                        OR red_flushed_by_voucher_id IS NULL
                    );
            END IF;
        END $$;
    """)

    # ── step 4/4: 索引 CONCURRENTLY (partial WHERE NOT NULL) ──────────
    op.execute("DO $$ BEGIN RAISE NOTICE 'v272 step 4/4: partial indexes CONCURRENTLY'; END $$;")
    with op.get_context().autocommit_block():
        # 查\"这张原凭证是否被红冲\" (给红冲凭证的 red_flush_of_voucher_id 建索引)
        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_fv_red_flush_of
                ON financial_vouchers(red_flush_of_voucher_id)
                WHERE red_flush_of_voucher_id IS NOT NULL;
        """)
        # UNIQUE: 一张凭证只能被红冲一次 (同时充当 red_flushed_by_voucher_id 索引)
        op.execute("""
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_fv_red_flushed_by
                ON financial_vouchers(red_flushed_by_voucher_id)
                WHERE red_flushed_by_voucher_id IS NOT NULL;
        """)

    op.execute("""
        COMMENT ON COLUMN financial_vouchers.red_flush_of_voucher_id IS
            '本凭证是哪个原凭证的红冲 (红字凭证, fen BIGINT 取负显示).';
        COMMENT ON COLUMN financial_vouchers.red_flushed_by_voucher_id IS
            '本凭证被哪个红冲凭证冲正 (反向 link, 最多一次).';
    """)

    op.execute("DO $$ BEGIN RAISE NOTICE 'v272 upgrade complete'; END $$;")


def downgrade() -> None:
    op.execute("DO $$ BEGIN RAISE NOTICE 'v272 downgrade step 1/3: DROP INDEX CONCURRENTLY'; END $$;")
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS uq_fv_red_flushed_by;")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_fv_red_flush_of;")

    op.execute("DO $$ BEGIN RAISE NOTICE 'v272 downgrade step 2/3: DROP CHECK + FK'; END $$;")
    op.execute("""
        ALTER TABLE financial_vouchers
            DROP CONSTRAINT IF EXISTS chk_voucher_red_flush_exclusive,
            DROP CONSTRAINT IF EXISTS fk_fv_red_flushed_by,
            DROP CONSTRAINT IF EXISTS fk_fv_red_flush_of;
    """)

    op.execute("DO $$ BEGIN RAISE NOTICE 'v272 downgrade step 3/3: DROP 2 columns (link data loss!)'; END $$;")
    op.execute("""
        ALTER TABLE financial_vouchers
            DROP COLUMN IF EXISTS red_flush_of_voucher_id,
            DROP COLUMN IF EXISTS red_flushed_by_voucher_id;
    """)
    op.execute("DO $$ BEGIN RAISE NOTICE 'v272 downgrade complete'; END $$;")
