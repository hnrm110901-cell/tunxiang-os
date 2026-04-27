"""v274 — erp_push_log 表 + RLS 策略 [Tier1]

[§19 安全 P1-2 响应 / Wave 2 Batch 1]

背景:
  erp_push_log 表在 W1.7 voucher_generator._record_push_result 被 INSERT,
  但本仓库的 shared/db-migrations/versions/ 里**没有该表的建表迁移**.
  如果表已存在于生产, 它**也没有 RLS POLICY** (审计发现的安全漏洞).

  任何持有有效 X-Tenant-ID 的调用方查询 erp_push_log, 可看到
  **全部租户**的 ERP 推送记录 — 含 source_id (业务单据 UUID), erp_type
  (租户用金蝶 or 用友的商业情报), 错误消息 (ERP 内部错误). 这是竞品情报
  + GDPR/数据合规 P0 级漏洞.

修复 (幂等, 两种生产状态都兼容):
  1. CREATE TABLE IF NOT EXISTS erp_push_log — 缺失时新建
  2. ALTER TABLE ENABLE ROW LEVEL SECURITY — noop 若已启用
  3. DROP POLICY IF EXISTS + CREATE POLICY (USING + WITH CHECK)
     — 与 W1 Blockers B2 一致: 显式双声明

表结构 (从 voucher_generator._record_push_result 反推):
  id UUID PK
  tenant_id UUID NOT NULL (RLS key)
  store_id UUID
  voucher_id VARCHAR (ERP 侧 voucher_id, 非本地 FK)
  erp_type VARCHAR (kingdee / yonyou / ...)
  status VARCHAR (success / failed / queued)
  erp_voucher_id VARCHAR (ERP 侧返回的凭证号)
  error_message TEXT
  source_type VARCHAR
  source_id VARCHAR
  pushed_at TIMESTAMPTZ
  created_at TIMESTAMPTZ DEFAULT NOW()

索引:
  ix_erp_push_log_tenant_pushed (tenant_id, pushed_at DESC) 常查"最近推送"
  ix_erp_push_log_voucher_id (voucher_id) 按凭证查推送历史
  ix_erp_push_log_status WHERE status='failed' partial - 查失败重试队列

Tier 级别: Tier 1 (数据合规 / 租户隔离)

──────────────────────────────────────────────────────────────────────
【上线 Runbook】
──────────────────────────────────────────────────────────────────────

🕐 窗口: 任意 (新表建表 + RLS 启用都是元数据瞬时).

🔒 锁:
  - CREATE TABLE IF NOT EXISTS: 元数据瞬时, 表已存在则 noop.
  - ALTER TABLE ENABLE RLS: 元数据瞬时. 已启用 noop.
  - CREATE POLICY: 元数据瞬时.

📊 回填:
  如果生产 erp_push_log 已有历史行, RLS USING 会立即按当前 app.tenant_id
  过滤. 行内 tenant_id 必须已正确写入 (voucher_generator._record_push_result
  在 W1.7 就写了, OK).

  如果某些历史行 tenant_id=NULL (遗留脏数据), RLS 过滤后看不到, 需要
  离线修复. 本迁移不做 backfill (需要业务逻辑判断 tenant_id).

⚠️ downgrade: DROP POLICY + DISABLE RLS. 不删表 (保数据).

Revision ID: v274
Revises: v272
Create Date: 2026-04-19
"""
from alembic import op


revision = "v274"
down_revision = "v272"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── step 1/3: 建表 (幂等 IF NOT EXISTS) ────────────────────────────
    op.execute("DO $$ BEGIN RAISE NOTICE 'v274 step 1/3: CREATE TABLE IF NOT EXISTS erp_push_log'; END $$;")
    op.execute("""
        CREATE TABLE IF NOT EXISTS erp_push_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            store_id UUID,
            voucher_id VARCHAR(100),
            erp_type VARCHAR(30),
            status VARCHAR(20),
            erp_voucher_id VARCHAR(100),
            error_message TEXT,
            source_type VARCHAR(30),
            source_id VARCHAR(200),
            pushed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    # 索引 (IF NOT EXISTS 幂等)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_erp_push_log_tenant_pushed
            ON erp_push_log(tenant_id, pushed_at DESC);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_erp_push_log_voucher_id
            ON erp_push_log(voucher_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_erp_push_log_status_failed
            ON erp_push_log(tenant_id, pushed_at DESC)
            WHERE status = 'failed';
    """)

    # ── step 2/3: ENABLE RLS (幂等: 已启用则 noop) ─────────────────────
    op.execute("DO $$ BEGIN RAISE NOTICE 'v274 step 2/3: ENABLE ROW LEVEL SECURITY'; END $$;")
    op.execute("ALTER TABLE erp_push_log ENABLE ROW LEVEL SECURITY;")

    # ── step 3/3: POLICY (USING + WITH CHECK, 与 W1.BLOCKERS B2 一致) ──
    op.execute("DO $$ BEGIN RAISE NOTICE 'v274 step 3/3: CREATE POLICY erp_push_log_tenant'; END $$;")
    op.execute("DROP POLICY IF EXISTS erp_push_log_tenant ON erp_push_log;")
    op.execute("""
        CREATE POLICY erp_push_log_tenant ON erp_push_log
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)

    op.execute("""
        COMMENT ON TABLE erp_push_log IS
            'ERP 凭证推送日志. W1.7 voucher_generator._record_push_result 写入. '
            'W2.G (v274) 补 RLS 策略防跨租户泄漏 (source_id / erp_type / 错误消息).';
    """)

    op.execute("DO $$ BEGIN RAISE NOTICE 'v274 upgrade complete'; END $$;")


def downgrade() -> None:
    # 不删表 (保历史数据). 只关 RLS + 删 POLICY.
    op.execute("DO $$ BEGIN RAISE NOTICE 'v274 downgrade: disable RLS + drop POLICY'; END $$;")
    op.execute("DROP POLICY IF EXISTS erp_push_log_tenant ON erp_push_log;")
    op.execute("ALTER TABLE erp_push_log DISABLE ROW LEVEL SECURITY;")
    # 索引保留 (非破坏性), 表也保留
    op.execute("DO $$ BEGIN RAISE NOTICE 'v274 downgrade complete'; END $$;")
