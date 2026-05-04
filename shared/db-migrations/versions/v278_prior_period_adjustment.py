"""v278 — financial_vouchers 以前年度损益调整字段 [Tier1]

[§19 CFO P0-1 响应 / Wave 2 Batch 2 首 PR]

背景 — 会计实务最棘手场景:
  2027-03-10 发现 2026-12-31 漏了一张 ¥15,000 采购凭证.
  当前 W2 能力全军覆没:
    - reopen 2026-12: 2026 年已 locked, 不可重开 (金税四期红线)
    - red_flush: 需要原凭证存在, 但这张本就没有生成过
    - create 2026-12-XX: 账期 closed, W1.4b 直接 ValueError
  → 这笔 ¥15,000 永久无法入账. CFO 视角年化千万级潜在损失.

会计实务答案:
  使用"以前年度损益调整"科目 (6901), 写当期日期凭证:
    voucher_date = 2027-03-10 (当期, open 账期正常入账)
    source_period_year = 2026
    source_period_month = 12
    entries:
      借: 1403 原材料 15000
      贷: 6901 以前年度损益调整 15000
  → 2027 年账面反映历史漏账, 2026 账面不改 (保 locked).
  → 金税四期合规: 任何跨期调整有明确审计轨迹.

变更:
  1. ADD 2 列:
     - source_period_year INTEGER NULLABLE (2020-2100 CHECK)
     - source_period_month INTEGER NULLABLE (1-12 CHECK)
  2. CHECK chk_fv_source_period:
     两列同时 NULL 或同时非空 (不能单独填一个)
  3. 索引 ix_fv_source_period partial WHERE NOT NULL:
     按源期间查询 (审计常用: "2026 年有多少跨期调整?")

  注意: 不加 voucher_type CHECK 枚举约束 (现状 String(20) 无 CHECK, 保持最小化影响).
       service 层接受 voucher_type='prior_period_adjustment', 靠应用层校验.

Tier 级别: Tier 1 (资金安全 / 金税四期合规最棘手场景)

──────────────────────────────────────────────────────────────────────
【上线 Runbook】
──────────────────────────────────────────────────────────────────────

🕐 窗口: 03:00 — 06:00. ADD COLUMN 瞬时.

🔒 锁:
  - ADD COLUMN (2 列, NULLABLE): 元数据瞬时
  - ADD CHECK 约束: 元数据瞬时 (新列都是 NULL, CHECK 立即满足)
  - CREATE INDEX CONCURRENTLY partial: 不阻塞 DML

📊 回填: 不需要. 历史凭证 source_period_* 保持 NULL (正常场景).
  仅新的"以前年度损益调整"凭证需要填.

⚠️ downgrade: DROP COLUMN 会丢审计追溯元数据. 超 24h 视为不可.

Revision ID: v278
Revises: v276
Create Date: 2026-04-19
"""
from alembic import op


revision = "v278b"
down_revision = "v276"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── step 1a/4: 扩 voucher_type 长度 (为 'prior_period_adjustment' 25 字符腾空间) ──
    op.execute("DO $$ BEGIN RAISE NOTICE 'v278 step 1a/4: extend voucher_type length'; END $$;")
    op.execute("""
        ALTER TABLE financial_vouchers
            ALTER COLUMN voucher_type TYPE VARCHAR(40);
    """)

    op.execute("DO $$ BEGIN RAISE NOTICE 'v278 step 1b/4: ADD 2 source_period columns'; END $$;")
    op.execute("""
        ALTER TABLE financial_vouchers
            ADD COLUMN IF NOT EXISTS source_period_year  INTEGER,
            ADD COLUMN IF NOT EXISTS source_period_month INTEGER;
    """)

    op.execute("DO $$ BEGIN RAISE NOTICE 'v278 step 2/3: CHECK source_period consistency'; END $$;")
    # CHECK 显式处理 SQL NULL 三值逻辑:
    # 原写法 (source_period_year BETWEEN 2020 AND 2100 AND source_period_month BETWEEN 1 AND 12)
    # 在 month=NULL 时返 NULL, NULL OR FALSE = NULL, CHECK 视为 pass, 导致单填一列通过.
    # 修: 显式 IS NOT NULL 防 NULL 穿透.
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'chk_fv_source_period'
            ) THEN
                ALTER TABLE financial_vouchers
                    ADD CONSTRAINT chk_fv_source_period CHECK (
                        (source_period_year IS NULL AND source_period_month IS NULL)
                        OR (
                            source_period_year IS NOT NULL
                            AND source_period_month IS NOT NULL
                            AND source_period_year BETWEEN 2020 AND 2100
                            AND source_period_month BETWEEN 1 AND 12
                        )
                    );
            END IF;
        END $$;
    """)

    op.execute("DO $$ BEGIN RAISE NOTICE 'v278 step 3/3: partial index for audit query'; END $$;")
    with op.get_context().autocommit_block():
        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_fv_source_period
                ON financial_vouchers(tenant_id, source_period_year, source_period_month)
                WHERE source_period_year IS NOT NULL;
        """)

    op.execute("""
        COMMENT ON COLUMN financial_vouchers.source_period_year IS
            '[W2.A v278] 以前年度损益调整 — 业务原属年份. NULL 为当期凭证.';
        COMMENT ON COLUMN financial_vouchers.source_period_month IS
            '[W2.A v278] 以前年度损益调整 — 业务原属月份.';
    """)

    op.execute("DO $$ BEGIN RAISE NOTICE 'v278 upgrade complete'; END $$;")


def downgrade() -> None:
    op.execute("DO $$ BEGIN RAISE NOTICE 'v278 downgrade: DROP source_period columns (audit data loss!)'; END $$;")
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_fv_source_period;")

    op.execute("""
        ALTER TABLE financial_vouchers
            DROP CONSTRAINT IF EXISTS chk_fv_source_period;
    """)
    op.execute("""
        ALTER TABLE financial_vouchers
            DROP COLUMN IF EXISTS source_period_year,
            DROP COLUMN IF EXISTS source_period_month;
    """)
    op.execute("DO $$ BEGIN RAISE NOTICE 'v278 downgrade complete'; END $$;")
