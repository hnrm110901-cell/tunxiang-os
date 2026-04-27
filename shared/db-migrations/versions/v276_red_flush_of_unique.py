"""v276 — financial_vouchers red_flush_of_voucher_id 升级为 UNIQUE [Tier1]

[§19 DBA P1-5 响应 / Wave 2 Batch 1 收尾]

背景:
  W1.5 (v272) 建的 ix_fv_red_flush_of 是**非 UNIQUE** partial index.
  红冲 service red_flush() 内部两次 flush (见 financial_voucher_service.py):
    1. flush 新红字凭证 (含 red_flush_of_voucher_id = original.id)
    2. flush 原凭证反向 link (original.red_flushed_by_voucher_id = red.id)

  如果 flush #2 前连接断 + 外层 txn 误 commit (W1.5 docstring 的已知风险):
    - 红字凭证已落 DB, red_flush_of_voucher_id 指向原凭证
    - 原凭证 red_flushed_by_voucher_id = NULL (反向 link 丢失)

  此时重试 red_flush(original):
    service 层 has_been_red_flushed 检查 `original.red_flushed_by_voucher_id is None`
    → False (因为 NULL), 放行 → 生成第二张红字凭证指向同一 original
    → **一张原凭证被两张红字凭证指向**, 金税四期对账裂开

  v272 的 ix_fv_red_flush_of 非 UNIQUE, 允许这种重复.

修复 (DB 层兜底):
  把 ix_fv_red_flush_of 升级为 UNIQUE partial index.
  一张原凭证最多被**一张**红字凭证指向.
  与 uq_fv_red_flushed_by (v272, 一张原凭证最多被红冲一次) 对称.

幂等步骤:
  1. DROP INDEX IF EXISTS ix_fv_red_flush_of (老 partial index)
  2. CREATE UNIQUE INDEX CONCURRENTLY (新 UNIQUE partial)
  3. 如果生产已有重复 (概率极低, W1.5 上线时间短):
     UNIQUE INDEX 创建会失败, 需 DBA 手工 dedup 后重试
     (预检 SQL 在 runbook)

预检 (生产上线前必跑):
  SELECT red_flush_of_voucher_id, COUNT(*)
  FROM financial_vouchers
  WHERE red_flush_of_voucher_id IS NOT NULL
  GROUP BY 1 HAVING COUNT(*) > 1;

Tier 级别: Tier 1 (资金安全 / 金税四期)

──────────────────────────────────────────────────────────────────────
【上线 Runbook】
──────────────────────────────────────────────────────────────────────

🕐 窗口: 03:00 — 06:00. CREATE UNIQUE INDEX CONCURRENTLY 可能耗时数分钟.

🔒 锁:
  - DROP INDEX IF EXISTS (老普通 index): 毫秒级
  - CREATE UNIQUE INDEX CONCURRENTLY: 不阻塞 DML. 百万行扫 ~ 2-5 分钟.
    期间如检出重复, index 创建失败, 需 DBA 手工 dedup.

📊 回填: 不自动. 预检 SQL (见 docstring) 必须在上线前跑.
  W1.5 上线至今红冲操作极少 (审计场景), 重复概率接近 0, 但必须验证.

⚠️ downgrade: 升级为 UNIQUE 后无法无损 downgrade 到普通 index (可能有新
  数据依赖 UNIQUE 防护). downgrade 仅用于紧急撤销 (会失去 UNIQUE 保护).

Revision ID: v276
Revises: v274
Create Date: 2026-04-19
"""
from alembic import op


revision = "v276"
down_revision = "v274"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DO $$ BEGIN RAISE NOTICE 'v276 step 1/2: DROP old ix_fv_red_flush_of'; END $$;")
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_fv_red_flush_of;")

    op.execute("DO $$ BEGIN RAISE NOTICE 'v276 step 2/2: CREATE UNIQUE INDEX CONCURRENTLY ix_fv_red_flush_of'; END $$;")
    with op.get_context().autocommit_block():
        op.execute("""
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS ix_fv_red_flush_of
                ON financial_vouchers(red_flush_of_voucher_id)
                WHERE red_flush_of_voucher_id IS NOT NULL;
        """)

    op.execute("""
        COMMENT ON INDEX ix_fv_red_flush_of IS
            '[W2.D v276] UNIQUE partial: 一张原凭证最多被一张红字凭证指向. '
            '与 uq_fv_red_flushed_by (v272) 对称, 防 red_flush 双 flush 孤儿.';
    """)

    op.execute("DO $$ BEGIN RAISE NOTICE 'v276 upgrade complete'; END $$;")


def downgrade() -> None:
    # 降级为普通 index (失去 UNIQUE 保护, 仅紧急撤销用)
    op.execute("DO $$ BEGIN RAISE NOTICE 'v276 downgrade: replace UNIQUE with regular index'; END $$;")
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_fv_red_flush_of;")
        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_fv_red_flush_of
                ON financial_vouchers(red_flush_of_voucher_id)
                WHERE red_flush_of_voucher_id IS NOT NULL;
        """)
    op.execute("DO $$ BEGIN RAISE NOTICE 'v276 downgrade complete'; END $$;")
