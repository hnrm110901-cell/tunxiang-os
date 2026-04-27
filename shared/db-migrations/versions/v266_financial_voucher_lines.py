"""v266 — financial_voucher_lines 会计分录子表 [Tier1]

背景:
  v264 (本 Wave 前置 PR) 已把 financial_vouchers 主表 schema ↔ ORM 对齐,
  金额统一到 fen BIGINT. 但分录仍塞在 entries JSONB 列里:
    - 无法加 CHECK (借贷互斥 / 非负 / 至少一方非零)
    - 无法走账结构化查询 (科目总账/T 字账/日结对账)
    - JSONB GIN 索引对"某科目汇总"仍是全表扫
    - 跨行事务一致性 (如红冲时整卷凭证 lines 取反) 只能应用层拼
  W1.1 引入 financial_voucher_lines 作为**分录 SSOT**:
    - 每行 (debit_fen, credit_fen) CHECK 借贷互斥
    - CASCADE 删 — voucher 删, lines 自动清
    - RLS: 按 app.tenant_id 强隔离 (合资公司 / 多品牌)

变更:
  1. CREATE TABLE financial_voucher_lines
     - id UUID PK
     - tenant_id UUID NOT NULL (冗余到子表, RLS 用)
     - voucher_id UUID NOT NULL REFERENCES financial_vouchers(id) ON DELETE CASCADE
     - line_no INT NOT NULL (凭证内序号, 1-based)
     - account_code VARCHAR(20) NOT NULL   (e.g. "6001")
     - account_name VARCHAR(100) NOT NULL  (e.g. "主营业务收入-餐饮")
     - debit_fen BIGINT NOT NULL DEFAULT 0
     - credit_fen BIGINT NOT NULL DEFAULT 0
     - summary VARCHAR(200)
     - created_at / updated_at TIMESTAMPTZ
  2. CHECK 约束 (会计红线, 不可绕过):
     - chk_voucher_line_debit_credit_exclusive:
         (debit_fen = 0 AND credit_fen > 0) OR (debit_fen > 0 AND credit_fen = 0)
       → 同行借贷互斥, 非负, 至少一方非零 (三约束合一)
     - chk_voucher_line_non_negative:
         debit_fen >= 0 AND credit_fen >= 0 (冗余防御, 上面蕴含但显式写)
  3. UNIQUE (voucher_id, line_no) — 凭证内行号唯一
  4. 3 索引:
     - ix_fvl_voucher_id            (voucher_id)        — 父子关联 lookup
     - ix_fvl_tenant_account        (tenant_id, account_code) — 科目总账扫描
     - ix_fvl_tenant_created        (tenant_id, created_at)   — 时间线审计
  5. RLS:
     - ALTER TABLE ENABLE ROW LEVEL SECURITY
     - POLICY financial_voucher_lines_tenant USING
         tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
     - 与 financial_vouchers (v031 建表已启用 RLS) 同策略
     - 为什么子表也带 tenant_id 而非仅靠 voucher_id 关联:
       * 跨租户 JOIN 攻击面: 单靠 voucher_id 关联, 恶意租户用伪造 voucher_id
         可能绕过 USING 子句; 子表自带 tenant_id 走相同 NULLIF current_setting
         校验, 零风险冗余.
       * 性能: 科目总账 (tenant_id, account_code) 单表索引比
         JOIN vouchers 再过滤快 10x 以上.

金额单位:
  debit_fen / credit_fen 全部 BIGINT 分 (屯象 fen 约定, 与 v264 total_amount_fen 一致).
  不再留"元"字段 — W1.1 是新表, 没有历史负担.

Tier 级别: Tier 1 (资金安全 / 金税四期链路)

──────────────────────────────────────────────────────────────────────
【上线 Runbook — 生产执行前必读】
──────────────────────────────────────────────────────────────────────

🕐 上线窗口:
    03:00 — 06:00 (业务低峰)
  禁止窗口:
    20:00 — 02:00 (日结高峰)

🔒 锁分析:
  - CREATE TABLE 新表: 无阻塞, 元数据瞬时
  - CREATE INDEX 新表: 新表零数据, 秒级完成 (非 CONCURRENTLY 也安全)
    故本迁移不用 autocommit_block() — 新空表索引立即完成.
  - RLS POLICY 创建: 元数据瞬时

📊 回填:
  W1.1 只建表 不迁数据. 历史 entries JSONB 会在 W1.6 PR 批量回填.
  在此期间:
    - 新建凭证: 应用层 (W1.3 PR) 双写 entries + voucher_lines
    - 读路径: 报表/ERP 推送仍读 entries (W1.3 后切 lines)
    - is_balanced(): 主表依然靠 entries 判定 (W1.3 引入 is_balanced_from_lines)

⚠️ downgrade 边界:
  DROP TABLE financial_voucher_lines CASCADE — 若 W1.6 已回填历史数据, 数据会丢!
  → 本迁移 downgrade 仅用于 W1.1 发布失败紧急回滚.
  → 上线 24h 后若一切稳定, 认为 downgrade 不再可用.

🔗 链表依赖:
  revision = v266, down_revision = v264 (跳过 v265 — 并行会话的
  event_outbox_cursor, 与本 PR 互相独立, 双方都直连 v263 是历史遗留).
  → Alembic 链去重是 P0 单独 PR (fix/alembic-chain-dedup), 不在本 PR 范围.

Revision ID: v266
Revises: v264
Create Date: 2026-04-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "v266"
down_revision = "v264"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    op.execute("DO $$ BEGIN RAISE NOTICE 'v266 step 1/4: CREATE TABLE financial_voucher_lines'; END $$;")

    if "financial_voucher_lines" not in existing:
        op.create_table(
            "financial_voucher_lines",
            sa.Column(
                "id", UUID(as_uuid=True), primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "tenant_id", UUID(as_uuid=True), nullable=False,
                comment="租户 ID (RLS). 与父 voucher.tenant_id 同步, 冗余防跨租户 JOIN 攻击.",
            ),
            sa.Column(
                "voucher_id", UUID(as_uuid=True), nullable=False,
                comment="父凭证 ID. CASCADE 删.",
            ),
            sa.Column(
                "line_no", sa.Integer, nullable=False,
                comment="凭证内分录序号 (1-based).",
            ),
            sa.Column(
                "account_code", sa.String(20), nullable=False,
                comment="会计科目代码 (e.g. 6001 主营业务收入).",
            ),
            sa.Column(
                "account_name", sa.String(100), nullable=False,
                comment="科目名称 (冗余, ERP 推送直接读).",
            ),
            sa.Column(
                "debit_fen", sa.BigInteger, nullable=False,
                server_default="0",
                comment="借方金额 (分). 与 credit_fen 互斥, 非负.",
            ),
            sa.Column(
                "credit_fen", sa.BigInteger, nullable=False,
                server_default="0",
                comment="贷方金额 (分). 与 debit_fen 互斥, 非负.",
            ),
            sa.Column(
                "summary", sa.String(200), nullable=True,
                comment="分录摘要 (e.g. 2026-04-19 堂食收入).",
            ),
            sa.Column(
                "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.ForeignKeyConstraint(
                ["voucher_id"], ["financial_vouchers.id"],
                ondelete="CASCADE",
                name="fk_fvl_voucher_id",
            ),
            sa.UniqueConstraint(
                "voucher_id", "line_no",
                name="uq_fvl_voucher_line_no",
            ),
            sa.CheckConstraint(
                "(debit_fen = 0 AND credit_fen > 0) "
                "OR (debit_fen > 0 AND credit_fen = 0)",
                name="chk_fvl_debit_credit_exclusive",
            ),
            sa.CheckConstraint(
                "debit_fen >= 0 AND credit_fen >= 0",
                name="chk_fvl_non_negative",
            ),
        )
        op.create_index(
            "ix_fvl_voucher_id",
            "financial_voucher_lines", ["voucher_id"],
        )
        op.create_index(
            "ix_fvl_tenant_account",
            "financial_voucher_lines", ["tenant_id", "account_code"],
        )
        op.create_index(
            "ix_fvl_tenant_created",
            "financial_voucher_lines", ["tenant_id", "created_at"],
        )

    # ── step 2/4: RLS ─────────────────────────────────────────────────
    op.execute("DO $$ BEGIN RAISE NOTICE 'v266 step 2/4: ENABLE ROW LEVEL SECURITY'; END $$;")
    op.execute("ALTER TABLE financial_voucher_lines ENABLE ROW LEVEL SECURITY;")
    op.execute(
        "DROP POLICY IF EXISTS financial_voucher_lines_tenant "
        "ON financial_voucher_lines;"
    )
    # [BLOCKER-B2 独立验证响应 — DBA P0-4 / 安全 P0-1]:
    # 原策略只有 USING 无 WITH CHECK. PG 对 FOR ALL POLICY 会复用 USING 为
    # WITH CHECK 兜底, 但显式声明更稳: (1) 未来如果有 FOR SELECT / FOR UPDATE
    # 等细分策略添加, 不会默认缺 WITH CHECK; (2) 防御性编程, 明确 INSERT/UPDATE
    # 的 tenant 约束.
    op.execute("""
        CREATE POLICY financial_voucher_lines_tenant ON financial_voucher_lines
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)

    # ── step 3/4: 表注释 ───────────────────────────────────────────────
    op.execute("DO $$ BEGIN RAISE NOTICE 'v266 step 3/4: table/column comments'; END $$;")
    op.execute("""
        COMMENT ON TABLE financial_voucher_lines IS
            '会计凭证分录子表 (SSOT, W1.1 建). 取代 financial_vouchers.entries JSONB. '
            '借贷互斥非负由 CHECK 约束兜底.';
    """)

    op.execute("DO $$ BEGIN RAISE NOTICE 'v266 step 4/4: upgrade complete'; END $$;")


def downgrade() -> None:
    # ⚠️ 若 W1.6 历史回填已执行 (~N 年数据), downgrade 会永久丢分录.
    # 仅 W1.1 上线当天紧急回滚可用; 超 24h 视为不可降级.
    op.execute("DO $$ BEGIN RAISE NOTICE 'v266 downgrade: DROP TABLE financial_voucher_lines'; END $$;")

    # RLS 策略 + 索引随 DROP TABLE 自动回收, 无需显式 DROP POLICY / DROP INDEX.
    op.drop_table("financial_voucher_lines")

    op.execute("DO $$ BEGIN RAISE NOTICE 'v266 downgrade complete'; END $$;")
