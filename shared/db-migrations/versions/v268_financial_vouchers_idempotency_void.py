"""v268 — financial_vouchers 幂等字段 + 作废状态机 [Tier1]

背景:
  W1.0 (v264) 对齐 ORM, W1.1 (v266) 建 lines 子表. 但两大业务漏洞未补:

  1. **幂等缺失**: order.paid 事件重试 / 日结 Celery 重跑 / 操作员重复点击 都可能
     生成重复凭证. 当前只有 voucher_no UNIQUE 兜底, 但 voucher_no 是业务编号
     (V{store}{YYYYMMDD}{SEQ}), 幂等不健壮 (SEQ 冲突即已失真).
     → 引入 (tenant_id, event_type, event_id) 幂等键.

  2. **作废无状态机**: "误生成"凭证只能硬删 (违反审计留痕), 或用 status='cancelled'
     但无审计字段 (谁 / 何时 / 为何作废). 金税四期审计要求可回溯.
     → 引入 voided / voided_at / voided_by / voided_reason + DB CHECK 强一致.

变更:
  1. ADD 2 idempotency columns:
     - event_type VARCHAR(50)  — 事件类型 (order.paid / daily_settlement.closed 等)
     - event_id UUID           — 事件去重 ID
  2. UNIQUE partial index (tenant_id, event_type, event_id) WHERE event_id IS NOT NULL
     - partial 原因: 历史凭证 event_id=NULL 不参与去重; 手工录入凭证也允许 NULL
  3. ADD 4 void columns:
     - voided BOOLEAN NOT NULL DEFAULT FALSE
     - voided_at TIMESTAMPTZ
     - voided_by UUID
     - voided_reason VARCHAR(200)
  4. CHECK chk_voucher_void_consistency:
     voided=TRUE → voided_at + voided_by 必填 (审计留痕)
  5. 索引:
     - ix_fv_event              (tenant_id, event_type) — 事件溯源查询
     - ix_fv_voided_at          (tenant_id, voided_at) WHERE voided=TRUE — 作废审计

  注: W1.2 **不**加红冲字段 (red_flush_of / red_flushed_by).
    红冲是金税四期专用机制 (新建反向凭证 + 双方 link), 比 void 复杂:
    - void: 误生成, draft/confirmed 可 void, exported 不可
    - red_flush: exported 到 ERP 后才用, 必须生成反向分录入账
    → W1.5 PR (红冲作废 API) 专门处理红冲.

状态机 (应用层, W1.3 PR 落 service 层):
  ┌─────────┐ void()      ┌────────┐
  │  draft  │─────────────>│ voided │ (审计留痕, 不硬删)
  └────┬────┘              └────────┘
       │ confirm()
       ↓
  ┌─────────┐ void()      ┌────────┐
  │confirmed│─────────────>│ voided │
  └────┬────┘              └────────┘
       │ export_to_erp()
       ↓
  ┌─────────┐ ✗ void() 禁 │
  │exported │─────────────>  red_flush() only (W1.5 PR)
  └─────────┘

金额单位: 本 PR 不动金额. v264 (total_amount_fen) / v266 (lines.debit_fen/credit_fen)
  已落 fen SSOT.

Tier 级别: Tier 1 (资金安全 / 金税四期审计留痕)

──────────────────────────────────────────────────────────────────────
【上线 Runbook】
──────────────────────────────────────────────────────────────────────

🕐 上线窗口: 03:00 — 06:00 (业务低峰). 禁止窗口: 20:00 — 02:00 (日结高峰).

🔒 锁分析:
  - ADD COLUMN (6 列, 全 nullable 或带 stable DEFAULT) — PG11+ 元数据瞬时.
  - ALTER TABLE 仍获 AccessExclusiveLock, 预检长事务 (同 v264 策略).
  - UNIQUE partial index CONCURRENTLY — 不阻塞 DML, 必要.
    理由: financial_vouchers 已有百万级行, 非 CONCURRENTLY 会锁表
    直到索引建完 (~数分钟).
  - CHECK 约束 ADD — 瞬时 (新列只有默认值, 不触发全表扫).

📊 回填: 无. event_type/event_id 是未来字段, 历史凭证保 NULL (partial UNIQUE
  允许 NULL). voided 默认 FALSE, 语义正确.

⚠️ downgrade 边界:
  DROP COLUMN 会永久丢审计数据 (voided_at/by/reason). 若 W1.2 上线后已有
  凭证被作废, downgrade 视为不可. 本 migration downgrade 仅 W1.2 发布当天
  紧急回滚用.

Revision ID: v268
Revises: v266
Create Date: 2026-04-19
"""
from alembic import op
import sqlalchemy as sa


revision = "v268"
down_revision = "v266"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── step 1/5: ADD 6 columns (幂等 + 作废) ─────────────────────────
    op.execute("DO $$ BEGIN RAISE NOTICE 'v268 step 1/5: ADD 6 columns (idempotency + void)'; END $$;")
    op.execute("""
        ALTER TABLE financial_vouchers
            ADD COLUMN IF NOT EXISTS event_type     VARCHAR(50),
            ADD COLUMN IF NOT EXISTS event_id       UUID,
            ADD COLUMN IF NOT EXISTS voided         BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS voided_at      TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS voided_by      UUID,
            ADD COLUMN IF NOT EXISTS voided_reason  VARCHAR(200);
    """)

    # ── step 2/5: CHECK 作废一致性 ─────────────────────────────────────
    op.execute("DO $$ BEGIN RAISE NOTICE 'v268 step 2/5: CHECK void consistency'; END $$;")
    # 注意: CHECK 约束需要 IF NOT EXISTS 等价 (PG 原生不支持, 用 DO 块包裹)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                 WHERE conname = 'chk_voucher_void_consistency'
            ) THEN
                ALTER TABLE financial_vouchers
                    ADD CONSTRAINT chk_voucher_void_consistency CHECK (
                        voided = FALSE
                        OR (voided = TRUE
                            AND voided_at IS NOT NULL
                            AND voided_by IS NOT NULL)
                    );
            END IF;
        END $$;
    """)

    # ── step 3/5: UNIQUE partial index (幂等) CONCURRENTLY ────────────
    # 必须 CONCURRENTLY: financial_vouchers 是百万级老表, 非 CONCURRENTLY 会锁表.
    op.execute("DO $$ BEGIN RAISE NOTICE 'v268 step 3/5: UNIQUE partial index CONCURRENTLY'; END $$;")
    with op.get_context().autocommit_block():
        op.execute("""
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_fv_tenant_event
                ON financial_vouchers(tenant_id, event_type, event_id)
                WHERE event_id IS NOT NULL;
        """)

    # ── step 4/5: 辅助索引 CONCURRENTLY ────────────────────────────────
    op.execute("DO $$ BEGIN RAISE NOTICE 'v268 step 4/5: auxiliary indexes CONCURRENTLY'; END $$;")
    with op.get_context().autocommit_block():
        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_fv_event
                ON financial_vouchers(tenant_id, event_type)
                WHERE event_type IS NOT NULL;
        """)
        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_fv_voided_at
                ON financial_vouchers(tenant_id, voided_at)
                WHERE voided = TRUE;
        """)

    # ── step 5/5: 列注释 ──────────────────────────────────────────────
    op.execute("DO $$ BEGIN RAISE NOTICE 'v268 step 5/5: column comments'; END $$;")
    op.execute("""
        COMMENT ON COLUMN financial_vouchers.event_type IS
            '事件类型 (e.g. order.paid / daily_settlement.closed). 幂等 3 元组之一.';
        COMMENT ON COLUMN financial_vouchers.event_id IS
            '事件去重 ID (UUID). 同 (tenant, event_type, event_id) 只允许一条凭证.';
        COMMENT ON COLUMN financial_vouchers.voided IS
            '作废标志. TRUE 时强制要求 voided_at + voided_by 审计留痕 (DB CHECK).';
        COMMENT ON COLUMN financial_vouchers.voided_at IS
            '作废时间戳. voided=TRUE 时由 CHECK 强制非空.';
        COMMENT ON COLUMN financial_vouchers.voided_by IS
            '作废操作员 UUID. voided=TRUE 时由 CHECK 强制非空.';
        COMMENT ON COLUMN financial_vouchers.voided_reason IS
            '作废原因 (审计必读). 建议应用层也强制非空, 但 DB 层允许 NULL 以兼容.';
    """)

    op.execute("DO $$ BEGIN RAISE NOTICE 'v268 upgrade complete'; END $$;")


def downgrade() -> None:
    # ⚠️ 若 W1.2 上线后已有 voided 凭证 (voided_at/by/reason 已填), downgrade
    # 会永久丢失审计数据. 超 24h 视为不可降级.
    op.execute("DO $$ BEGIN RAISE NOTICE 'v268 downgrade step 1/3: DROP INDEX CONCURRENTLY'; END $$;")
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS uq_fv_tenant_event;")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_fv_event;")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_fv_voided_at;")

    op.execute("DO $$ BEGIN RAISE NOTICE 'v268 downgrade step 2/3: DROP CHECK'; END $$;")
    op.execute("""
        ALTER TABLE financial_vouchers
            DROP CONSTRAINT IF EXISTS chk_voucher_void_consistency;
    """)

    op.execute("DO $$ BEGIN RAISE NOTICE 'v268 downgrade step 3/3: DROP 6 columns (audit data loss!)'; END $$;")
    op.execute("""
        ALTER TABLE financial_vouchers
            DROP COLUMN IF EXISTS event_type,
            DROP COLUMN IF EXISTS event_id,
            DROP COLUMN IF EXISTS voided,
            DROP COLUMN IF EXISTS voided_at,
            DROP COLUMN IF EXISTS voided_by,
            DROP COLUMN IF EXISTS voided_reason;
    """)

    op.execute("DO $$ BEGIN RAISE NOTICE 'v268 downgrade complete'; END $$;")
