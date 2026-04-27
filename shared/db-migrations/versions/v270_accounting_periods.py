"""v270 — accounting_periods 会计账期表 [Tier1]

背景:
  Wave 1 前面 4 个 PR 建立了凭证 schema + service 能力, 但缺"账期"概念:
    - 2026-03 月结后, 不应再允许 2026-03-XX 的凭证写入 (审计红线)
    - 月结只做"锁定"不做"数据迁移" (符合金税四期)
    - 年结更严格: 12 月 close 后, 全年 12 张 period 跟随 lock (不可重开)

  当前 financial_vouchers 只有 voucher_date 字段, 无 period 归属.
  W1.4 引入 accounting_periods 表作为**账期元数据** + 状态机.
  W1.4b (独立 PR) 再把 voucher_service 的写入路径接入 period 校验.

变更:
  1. CREATE TABLE accounting_periods
     - id UUID PK
     - tenant_id UUID (RLS)
     - period_year INTEGER (2020-2100)
     - period_month INTEGER (1-12)
     - period_start DATE / period_end DATE (冗余, 便于按日期 range 查)
     - status VARCHAR(20): 'open' / 'closed' / 'locked'
     - 审计字段 3 组: closed_* / reopened_* / locked_*

  2. 状态转换规则 (应用层守, DB 层只保审计字段一致):
        open ──close_period()──> closed
       closed ──reopen_period()──> open  (可重开, 留痕)
       closed ──lock_period()──> locked  (年结锁定)
       locked ──×──> ∅               (不可重开, 只能追加红冲凭证)

  3. CHECK 约束:
     - chk_ap_status_valid:     status IN ('open', 'closed', 'locked')
     - chk_ap_month_range:      period_month BETWEEN 1 AND 12
     - chk_ap_year_range:       period_year BETWEEN 2020 AND 2100
     - chk_ap_date_range:       period_end >= period_start
     - chk_ap_closed_audit:     status='closed' → closed_at + closed_by 必填
     - chk_ap_locked_audit:     status='locked' → locked_at + locked_by 必填

  4. UNIQUE (tenant_id, period_year, period_month) — 每租户每月唯一

  5. 索引:
     - uq_ap_tenant_year_month      UNIQUE (tenant_id, period_year, period_month)
     - ix_ap_tenant_open            (tenant_id) WHERE status='open' — 快速找 open periods
     - ix_ap_tenant_date_range      (tenant_id, period_start, period_end) — 按 voucher_date 查 period

  6. RLS: app.tenant_id policy

Tier 级别: Tier 1 (资金安全 / 金税四期审计红线)

──────────────────────────────────────────────────────────────────────
【上线 Runbook】
──────────────────────────────────────────────────────────────────────

🕐 上线窗口: 03:00 — 06:00 (业务低峰). 新空表, 无锁风险, 但 W1.4b 接入后
  voucher 写路径会加 period 查询, 需要 prewarming.

🔒 锁分析:
  - 全新空表: CREATE TABLE / INDEX 秒级.
  - 不用 CONCURRENTLY (空表上无意义, 与 v266 策略一致).

📊 回填:
  本 PR 不自动回填历史 period. 应用层 W1.4b 接入时懒初始化:
    ensure_period(tenant, year, month) → 若不存在则 INSERT open 状态.
  年结 close 脚本 (W1.4c) 会批量回填.

⚠️ downgrade 边界:
  DROP TABLE 丢所有 close/lock 审计数据. 若 W1.4b 接入后已有数月关账,
  downgrade 会令 voucher 写路径失去 period 校验 (可能跨月写回已关月).
  → 上线 24h 后不可 downgrade.

Revision ID: v270
Revises: v268
Create Date: 2026-04-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "v270"
down_revision = "v268"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    op.execute("DO $$ BEGIN RAISE NOTICE 'v270 step 1/3: CREATE TABLE accounting_periods'; END $$;")

    if "accounting_periods" not in existing:
        op.create_table(
            "accounting_periods",
            sa.Column(
                "id", UUID(as_uuid=True), primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "tenant_id", UUID(as_uuid=True), nullable=False,
                comment="租户 ID (RLS).",
            ),
            sa.Column(
                "period_year", sa.Integer, nullable=False,
                comment="账期年份 (2020-2100).",
            ),
            sa.Column(
                "period_month", sa.Integer, nullable=False,
                comment="账期月份 (1-12).",
            ),
            sa.Column(
                "period_start", sa.Date, nullable=False,
                comment="账期首日 (冗余, 便于按日期 range 查 voucher_date 所属 period).",
            ),
            sa.Column(
                "period_end", sa.Date, nullable=False,
                comment="账期末日 (冗余).",
            ),
            sa.Column(
                "status", sa.String(20), nullable=False,
                server_default="'open'",
                comment="open / closed / locked. "
                        "open=可写; closed=月结, 凭证禁写 (除红冲); "
                        "locked=年结锁定, 不可重开.",
            ),

            # closed audit (status='closed' 时 CHECK 强制非空)
            sa.Column(
                "closed_at", sa.TIMESTAMP(timezone=True), nullable=True,
                comment="月结时间.",
            ),
            sa.Column(
                "closed_by", UUID(as_uuid=True), nullable=True,
                comment="月结操作员 UUID.",
            ),
            sa.Column(
                "closed_reason", sa.String(200), nullable=True,
                comment="月结原因/备注.",
            ),

            # reopened audit (closed → open 留痕, 不影响 CHECK)
            sa.Column(
                "reopened_at", sa.TIMESTAMP(timezone=True), nullable=True,
                comment="重开时间 (仅 closed → open 填).",
            ),
            sa.Column(
                "reopened_by", UUID(as_uuid=True), nullable=True,
                comment="重开操作员 UUID.",
            ),
            sa.Column(
                "reopened_reason", sa.String(200), nullable=True,
                comment="重开原因 (必填, 应用层强制).",
            ),

            # locked audit (year close)
            sa.Column(
                "locked_at", sa.TIMESTAMP(timezone=True), nullable=True,
                comment="年结锁定时间.",
            ),
            sa.Column(
                "locked_by", UUID(as_uuid=True), nullable=True,
                comment="年结操作员 UUID.",
            ),
            sa.Column(
                "locked_reason", sa.String(200), nullable=True,
                comment="年结原因 (通常 '2026 年度结账').",
            ),

            sa.Column(
                "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                server_default=sa.text("now()"),
            ),

            # ── 约束 ──────────────────────────────────────────
            sa.UniqueConstraint(
                "tenant_id", "period_year", "period_month",
                name="uq_ap_tenant_year_month",
            ),
            sa.CheckConstraint(
                "status IN ('open', 'closed', 'locked')",
                name="chk_ap_status_valid",
            ),
            sa.CheckConstraint(
                "period_month BETWEEN 1 AND 12",
                name="chk_ap_month_range",
            ),
            sa.CheckConstraint(
                "period_year BETWEEN 2020 AND 2100",
                name="chk_ap_year_range",
            ),
            sa.CheckConstraint(
                "period_end >= period_start",
                name="chk_ap_date_range",
            ),
            sa.CheckConstraint(
                "status != 'closed' OR (closed_at IS NOT NULL AND closed_by IS NOT NULL)",
                name="chk_ap_closed_audit",
            ),
            sa.CheckConstraint(
                "status != 'locked' OR (locked_at IS NOT NULL AND locked_by IS NOT NULL)",
                name="chk_ap_locked_audit",
            ),
        )

        # Partial index: 只为 open 状态建索引 (常查 "有哪些 period 还开着")
        op.create_index(
            "ix_ap_tenant_open",
            "accounting_periods",
            ["tenant_id"],
            postgresql_where=sa.text("status = 'open'"),
        )
        # Range lookup: 给定日期查所属 period (voucher 写路径用)
        op.create_index(
            "ix_ap_tenant_date_range",
            "accounting_periods",
            ["tenant_id", "period_start", "period_end"],
        )

    # ── step 2/3: RLS ─────────────────────────────────────────────────
    op.execute("DO $$ BEGIN RAISE NOTICE 'v270 step 2/3: ENABLE ROW LEVEL SECURITY'; END $$;")
    op.execute("ALTER TABLE accounting_periods ENABLE ROW LEVEL SECURITY;")
    op.execute(
        "DROP POLICY IF EXISTS accounting_periods_tenant ON accounting_periods;"
    )
    op.execute("""
        CREATE POLICY accounting_periods_tenant ON accounting_periods
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)

    # ── step 3/3: 表注释 ──────────────────────────────────────────────
    op.execute("DO $$ BEGIN RAISE NOTICE 'v270 step 3/3: table comment'; END $$;")
    op.execute("""
        COMMENT ON TABLE accounting_periods IS
            '会计账期元数据. 状态机: open → closed → (open | locked). '
            'W1.4b 接入 voucher 写路径: 写凭证前校验所属 period 必须 open. '
            '年结 locked 不可重开, 只能追加红冲凭证.';
    """)

    op.execute("DO $$ BEGIN RAISE NOTICE 'v270 upgrade complete'; END $$;")


def downgrade() -> None:
    # ⚠️ 若 W1.4b 接入后已有 close/lock 数据, downgrade 永久丢审计.
    # 超 24h 视为不可降级.
    op.execute("DO $$ BEGIN RAISE NOTICE 'v270 downgrade: DROP TABLE accounting_periods'; END $$;")
    op.drop_table("accounting_periods")
    op.execute("DO $$ BEGIN RAISE NOTICE 'v270 downgrade complete'; END $$;")
