"""v273 — pos_crash_reports A1 生产风险修补（Tier1 零容忍）

§19 独立验证发现 v268_pos_crash_reports_ext 上线后两条 P0 风险，
不可回滚 v268（已落地，部分环境可能已有数据），需"加迁移修补"。

修补 (a) — INDEX 锁表风险（A1 审查 #1）
  v268 中 `op.create_index("idx_pos_crash_severity_tenant_time", ...)`
  生成 `CREATE INDEX`（非 CONCURRENTLY），生产 PG 上 pos_crash_reports
  已积累大量 telemetry 数据，建索引会持表写锁 → telemetry 写入全部超时。
  本迁移：DROP 后用 CREATE INDEX CONCURRENTLY 重建。

修补 (b) — severity server_default='fatal' 误报雪崩（A1 审查 #3）
  v268 中 `severity` 列加 `server_default="fatal"`：
    - v260~v267 期间所有空入参旧记录被 PG 默认值机制回填为 'fatal'
    - 新版告警面板上线瞬间出现"全表 fatal" 误报
  本迁移：
    - DROP DEFAULT（severity 必须由业务显式写入）
    - 加 CHECK 约束限定枚举值（允许 NULL 兼容旧入参）
    - 历史回填修正：v268 应用时间窗口（'2026-04-24 23:15:00+08' 之前）
      的所有 'fatal' 改 NULL（这些是被 server_default 误回填的）

向后兼容：
  - 业务侧已实装的"显式传 severity"路径不受影响（fatal/error/warn/info）
  - 旧版 client 不传 severity → 写入 NULL（与回填后历史数据一致）

部署约束（CLAUDE.md §17 Tier1 + §21 灰度）：
  - CONCURRENTLY 不能在事务内 → 用 op.get_context().autocommit_block()
  - 生产由 DBA 在低峰期独立审核执行

Revision ID: v273
Revises: v272
Create Date: 2026-04-25
"""

import sqlalchemy as sa
from alembic import op

revision = "v273"
down_revision = "v272"
branch_labels = None
depends_on = None


# v268 应用时间戳（硬编码，alembic_version_history 不一定存在）
# 此前的 'fatal' 全部为 server_default 误回填，应改 NULL
V268_APPLIED_AT = "2026-04-24 23:15:00+08"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "pos_crash_reports" not in set(inspector.get_table_names()):
        # 父迁移未应用（新环境从头初始化）— no-op
        return

    # ── 修补 (b)：severity DROP DEFAULT + CHECK 约束 + 历史回填修正 ──
    existing_cols = {c["name"] for c in inspector.get_columns("pos_crash_reports")}
    if "severity" in existing_cols:
        # 1. DROP DEFAULT（不可在 CONCURRENTLY 块内 — 普通 DDL）
        op.execute(
            "ALTER TABLE pos_crash_reports ALTER COLUMN severity DROP DEFAULT"
        )

        # 2. 历史数据回填修正：v268 应用前所有 'fatal' 改 NULL
        #    这些记录是 server_default 机制回填，并非业务真实判级
        op.execute(
            f"UPDATE pos_crash_reports "
            f"SET severity = NULL "
            f"WHERE severity = 'fatal' "
            f"AND created_at < TIMESTAMP WITH TIME ZONE '{V268_APPLIED_AT}'"
        )

        # 3. 加 CHECK 约束（允许 NULL 兼容旧入参）
        existing_constraints = {
            c["name"] for c in inspector.get_check_constraints("pos_crash_reports")
        }
        if "ck_pos_crash_severity" not in existing_constraints:
            op.execute(
                "ALTER TABLE pos_crash_reports "
                "ADD CONSTRAINT ck_pos_crash_severity "
                "CHECK (severity IS NULL OR severity IN ('info','warn','error','fatal'))"
            )

    # ── 修补 (a)：INDEX CONCURRENTLY 重建 ──
    # 必须先 DROP 旧索引，再 CONCURRENTLY 重建
    # CONCURRENTLY 不能在事务内 → 每个 CONCURRENTLY 语句独立 autocommit_block
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("pos_crash_reports")}
    if "idx_pos_crash_severity_tenant_time" in existing_indexes:
        # DROP INDEX CONCURRENTLY（避免对 SELECT 加锁）
        with op.get_context().autocommit_block():
            op.execute(
                "DROP INDEX CONCURRENTLY IF EXISTS idx_pos_crash_severity_tenant_time"
            )
    # 重建为 CONCURRENTLY 形态（pos_crash_reports 大表上线无锁）
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "idx_pos_crash_severity_tenant_time "
            "ON pos_crash_reports (tenant_id, severity, created_at DESC)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "pos_crash_reports" not in set(inspector.get_table_names()):
        return

    # ── 反向 (a)：DROP CONCURRENTLY → 非 CONCURRENTLY 重建（与 v268 行为对齐） ──
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("pos_crash_reports")}
    if "idx_pos_crash_severity_tenant_time" in existing_indexes:
        # DROP CONCURRENTLY 必须在 autocommit_block 内
        with op.get_context().autocommit_block():
            op.execute(
                "DROP INDEX CONCURRENTLY IF EXISTS idx_pos_crash_severity_tenant_time"
            )
    # 非 CONCURRENTLY 重建（回到 v268 行为：会持表锁，与 v268 对齐）
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_pos_crash_severity_tenant_time "
        "ON pos_crash_reports (tenant_id, severity, created_at DESC)"
    )

    # ── 反向 (b)：DROP CHECK → severity 加回 server_default='fatal' ──
    existing_constraints = {
        c["name"] for c in inspector.get_check_constraints("pos_crash_reports")
    }
    if "ck_pos_crash_severity" in existing_constraints:
        op.execute(
            "ALTER TABLE pos_crash_reports DROP CONSTRAINT ck_pos_crash_severity"
        )

    existing_cols = {c["name"] for c in inspector.get_columns("pos_crash_reports")}
    if "severity" in existing_cols:
        op.execute(
            "ALTER TABLE pos_crash_reports ALTER COLUMN severity SET DEFAULT 'fatal'"
        )
