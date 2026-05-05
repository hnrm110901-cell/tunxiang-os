"""v264 — financial_vouchers Schema ↔ ORM 对齐 + 金额统一到 fen [Tier1]

背景:
  v031 (2 年前) 建表 financial_vouchers 含 period_start/period_end/total_debit/total_credit。
  同期 ORM (services/tx-finance/src/models/voucher.py) 已演进为 store_id/voucher_date/
  total_amount/source_type/source_id/exported_at/updated_at 字段，但无对应迁移，
  造成 ORM INSERT 会爆 "column does not exist"。

变更:
  1. ADD 8 columns (全 nullable 或带 DEFAULT, 向前兼容):
     store_id, voucher_date, total_amount (NUMERIC 元, 兼容 ORM 历史字段),
     total_amount_fen (BIGINT 分, 新 SSOT), source_type, source_id,
     exported_at, updated_at
  2. ALTER period_start / period_end DROP NOT NULL (MIGRATION_RULES 向前兼容)
  3. 回填 voucher_date = period_start (语义等价)
  4. 标记 period_start / period_end / total_debit / total_credit / total_amount 为 DEPRECATED
  5. 补索引 CONCURRENTLY (不阻塞 DML):
     (tenant_id, store_id, voucher_date) + (tenant_id, status)

金额单位:
  total_amount (NUMERIC 元, v031) 保留,ORM 标记 DEPRECATED.
  total_amount_fen (BIGINT 分, 本 PR 新增) 为屯象 fen 约定标准字段.
  entries JSONB 内分录仍为 元 (ERP 推送契约,由 W1.1 后续 PR 治理).

RLS:
  financial_vouchers RLS 策略在 v031 已建,本 PR 不改动.

Tier 级别: Tier 1 (资金安全 / 金税四期链路)

──────────────────────────────────────────────────────────────────────
【上线 Runbook — 生产执行前必读 (CFO + DBA 两轮风险评估结论)】
──────────────────────────────────────────────────────────────────────

⛔ 禁止上线窗口:
    20:00 — 02:00 (全国 200 门店日结高峰)
  推荐上线窗口:
    03:00 — 06:00 (业务低峰, 有回滚时间余量)

🔒 锁分析:
  1. ADD COLUMN (8 列, nullable 或带 stable DEFAULT) — PG11+ 元数据瞬时.
     但 ALTER TABLE 仍获 AccessExclusiveLock, 队列里长事务会阻塞.
     → 预检: SELECT pid, query_start, query FROM pg_stat_activity
              WHERE state = 'active' AND query_start < now() - interval '1 min';
     → 有长事务时先 kill 或等待; 阻塞堆积时不要硬推.
  2. DROP NOT NULL (period_start/end) — 元数据瞬时.
  3. UPDATE financial_vouchers SET voucher_date = period_start — ⚠️ 全表扫描.
     → 千万级行可能跑 30min+, WAL 膨胀, 主从延迟.
     → 预检: SELECT COUNT(*) FROM financial_vouchers WHERE voucher_date IS NULL;
     → 超 100 万行时 SKIP migration 里的 UPDATE, 改为上线后跑
       scripts/backfill_voucher_date.sh (外部 psql 分批, 见下方).
  4. CREATE INDEX CONCURRENTLY — 不阻塞 DML, 但耗时更长 (~2x).
     通过 op.get_context().autocommit_block() 脱离 alembic 主事务.

📊 大表回填替代方案 (行数 > 100 万, 外部脚本, 每批独立事务):

  # scripts/backfill_voucher_date.sh — 不要在 migration 里跑
  #!/usr/bin/env bash
  set -euo pipefail
  : "${DATABASE_URL:?}"
  while true; do
    n=$(psql "$DATABASE_URL" -t -A <<SQL
      WITH batch AS (
        SELECT id FROM financial_vouchers
         WHERE voucher_date IS NULL AND period_start IS NOT NULL
         LIMIT 10000
         FOR UPDATE SKIP LOCKED
      )
      UPDATE financial_vouchers fv
         SET voucher_date = fv.period_start
        FROM batch
       WHERE fv.id = batch.id
      RETURNING 1;
  SQL
    )
    count=$(echo "$n" | wc -l | tr -d ' ')
    echo "backfilled $count rows"
    [[ "$count" -lt 1 ]] && break
    sleep 0.5  # 每批独立事务 + sleep, 让主从追齐
  done

  ⚠️ 注意: 上一版 runbook 里的 DO $$ + pg_sleep 是错的 — DO 块是单事务,
  pg_sleep 只是挂事务不 COMMIT, 主从和 WAL 都不释放, 分批失效.

⚠️ downgrade 边界 (已在代码里加 guard):
  downgrade 会 SET NOT NULL 回 period_start/end. 若 upgrade 后已有新写入行
  (只填 voucher_date, period_start 为 NULL), SET NOT NULL 会失败.
  → downgrade() 内置前置检查, 发现 NULL 行直接 RAISE EXCEPTION 中止.
  → 恢复步骤:
      UPDATE financial_vouchers SET period_start = voucher_date,
                                     period_end   = voucher_date
       WHERE period_start IS NULL;
    然后重跑 downgrade.

🚦 应用层熔断 (运维层):
  migration 期间 tx-finance 所有 DB 连接会排队等锁. PgBouncer transaction pool
  会快速耗尽, FastAPI 上游 timeout → 502 → k8s liveness kill → crash-loop.
  → 上线前 kubectl scale deploy/tx-finance --replicas=0, 或发布 maintenance 页.
  → 或用 feature flag 把财务写路径熔断到只读.

Revision ID: v264
Revises: v263
Create Date: 2026-04-19
"""
from alembic import op


revision = "v264c"
down_revision = "v263"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── step 1/5: 新增 ORM 期望字段(全 nullable, 向前兼容) ──────────────
    # 注意 total_amount (NUMERIC 元) 在 v031 建表时未建, ORM 2 年来悬空引用.
    # 本 PR 一并补齐, 同时新增 total_amount_fen (BIGINT 分) 作 SSOT.
    op.execute("DO $$ BEGIN RAISE NOTICE 'v264 step 1/5: ADD 8 columns'; END $$;")
    op.execute("""
        ALTER TABLE financial_vouchers
            ADD COLUMN IF NOT EXISTS store_id         UUID,
            ADD COLUMN IF NOT EXISTS voucher_date     DATE,
            ADD COLUMN IF NOT EXISTS total_amount     NUMERIC(12, 2),
            ADD COLUMN IF NOT EXISTS total_amount_fen BIGINT,
            ADD COLUMN IF NOT EXISTS source_type      VARCHAR(30),
            ADD COLUMN IF NOT EXISTS source_id        UUID,
            ADD COLUMN IF NOT EXISTS exported_at      TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW();
    """)

    # ── step 2/5: 旧 period 字段松绑 NOT NULL(向前兼容) ─────────────────
    op.execute("DO $$ BEGIN RAISE NOTICE 'v264 step 2/5: DROP NOT NULL period_start/end'; END $$;")
    op.execute("""
        ALTER TABLE financial_vouchers
            ALTER COLUMN period_start DROP NOT NULL,
            ALTER COLUMN period_end   DROP NOT NULL;
    """)

    # ── step 3/5: 回填 voucher_date = period_start (语义等价, 幂等) ──────
    # [W1.0 BLOCKER-B4 修复]
    # 原方案: 迁移内 UPDATE 全表. TB 级老表会导致 alembic 主事务长持有,
    #   WAL 膨胀 + 主从 lag 小时级 + 后续 CREATE INDEX CONCURRENTLY 被阻.
    # 修复: 预检待回填行数. 超过 BACKFILL_INLINE_THRESHOLD (默认 5 万) 直接
    #   RAISE EXCEPTION, 强制 DBA 走外部脚本 scripts/backfill_voucher_date.sh.
    #   小表 (<5 万行) 仍然在迁移内 UPDATE, 部署更平滑.
    #
    # 阈值 5 万行的依据:
    #   - PG16 WAL segment 16MB, 全表 UPDATE 5 万行 ~ 100 MB WAL
    #   - 对 15 分钟主从 lag 阈值友好 (一般 100 MB WAL replay < 1 min)
    #   - 大于阈值的部署路径 (外部脚本分批 10k 行/批, 每批独立事务) 成本低
    op.execute("DO $$ BEGIN RAISE NOTICE 'v264 step 3/5: backfill voucher_date'; END $$;")
    op.execute("""
        DO $$
        DECLARE
            null_rows BIGINT;
            threshold BIGINT := 50000;  -- BACKFILL_INLINE_THRESHOLD
        BEGIN
            SELECT COUNT(*) INTO null_rows
              FROM financial_vouchers
             WHERE voucher_date IS NULL
               AND period_start IS NOT NULL;

            IF null_rows > threshold THEN
                RAISE EXCEPTION
                    'v264 backfill aborted: % rows need voucher_date backfill '
                    '(threshold: %). Too many for inline migration — '
                    'WAL growth + replication lag risk. '
                    'Use external script: scripts/backfill_voucher_date.sh '
                    '(batched with FOR UPDATE SKIP LOCKED). '
                    'Then stamp this migration: alembic stamp v264.',
                    null_rows, threshold;
            END IF;

            IF null_rows > 0 THEN
                UPDATE financial_vouchers
                   SET voucher_date = period_start
                 WHERE voucher_date IS NULL
                   AND period_start IS NOT NULL;
                RAISE NOTICE 'v264 step 3/5: backfilled % rows inline', null_rows;
            ELSE
                RAISE NOTICE 'v264 step 3/5: no rows need backfill';
            END IF;
        END $$;
    """)

    # ── step 4/5: DEPRECATED 注释 ──────────────────────────────────────
    op.execute("DO $$ BEGIN RAISE NOTICE 'v264 step 4/5: DEPRECATED comments'; END $$;")
    op.execute("""
        COMMENT ON COLUMN financial_vouchers.period_start IS
            'DEPRECATED v264: 用 voucher_date 替代. 将在 v270+ drop.';
        COMMENT ON COLUMN financial_vouchers.period_end IS
            'DEPRECATED v264. 将在 v270+ drop.';
        COMMENT ON COLUMN financial_vouchers.total_debit IS
            'DEPRECATED v264: 从 financial_voucher_lines 汇总 (W1.1 PR 建表).';
        COMMENT ON COLUMN financial_vouchers.total_credit IS
            'DEPRECATED v264. 将在 v270+ drop.';
        COMMENT ON COLUMN financial_vouchers.total_amount IS
            'DEPRECATED v264 (NUMERIC 元): 用 total_amount_fen (BIGINT 分) 替代.';
        COMMENT ON COLUMN financial_vouchers.total_amount_fen IS
            '凭证总金额(分, 屯象 fen BIGINT 约定). 与 total_amount 双写期间同步.';
    """)

    # ── step 5/5: 补索引 CONCURRENTLY (脱离主事务, 不阻塞 DML) ──────────
    # autocommit_block() 在 PG 上把语句提出 alembic 主事务, 必须这样才能用 CONCURRENTLY.
    # 如果索引已存在则 skip (IF NOT EXISTS).
    op.execute("DO $$ BEGIN RAISE NOTICE 'v264 step 5/5: CREATE INDEX CONCURRENTLY'; END $$;")
    with op.get_context().autocommit_block():
        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_financial_vouchers_tenant_store_date
                ON financial_vouchers(tenant_id, store_id, voucher_date);
        """)
        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_financial_vouchers_status
                ON financial_vouchers(tenant_id, status);
        """)

    op.execute("DO $$ BEGIN RAISE NOTICE 'v264 upgrade complete'; END $$;")


def downgrade() -> None:
    # ── 前置 guard: 若有新写入行 (period_start IS NULL), 直接中止 ──
    # 避免 SET NOT NULL 半途失败导致 schema/代码分裂状态.
    op.execute("""
        DO $$
        DECLARE null_rows INTEGER;
        BEGIN
            SELECT COUNT(*) INTO null_rows
              FROM financial_vouchers
             WHERE period_start IS NULL;
            IF null_rows > 0 THEN
                RAISE EXCEPTION
                    'v264 downgrade blocked: % rows have period_start IS NULL. '
                    'Run: UPDATE financial_vouchers SET period_start=voucher_date, '
                    'period_end=voucher_date WHERE period_start IS NULL; '
                    'then retry downgrade.', null_rows;
            END IF;
        END $$;
    """)

    op.execute("DO $$ BEGIN RAISE NOTICE 'v264 downgrade step 1/3: DROP INDEX CONCURRENTLY'; END $$;")
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_financial_vouchers_tenant_store_date;")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_financial_vouchers_status;")

    op.execute("DO $$ BEGIN RAISE NOTICE 'v264 downgrade step 2/3: DROP 8 columns'; END $$;")
    op.execute("""
        ALTER TABLE financial_vouchers
            DROP COLUMN IF EXISTS store_id,
            DROP COLUMN IF EXISTS voucher_date,
            DROP COLUMN IF EXISTS total_amount,
            DROP COLUMN IF EXISTS total_amount_fen,
            DROP COLUMN IF EXISTS source_type,
            DROP COLUMN IF EXISTS source_id,
            DROP COLUMN IF EXISTS exported_at,
            DROP COLUMN IF EXISTS updated_at;
    """)

    op.execute("DO $$ BEGIN RAISE NOTICE 'v264 downgrade step 3/3: restore NOT NULL'; END $$;")
    op.execute("""
        ALTER TABLE financial_vouchers
            ALTER COLUMN period_start SET NOT NULL,
            ALTER COLUMN period_end   SET NOT NULL;
    """)

    op.execute("DO $$ BEGIN RAISE NOTICE 'v264 downgrade complete'; END $$;")
