"""v075 — 修复 v067-v073 UPDATE 策略缺少 WITH CHECK 约束

Revision ID: v075
Revises: v074
Create Date: 2026-03-31

漏洞说明：
  PostgreSQL UPDATE 策略分两个阶段：
    1. USING 条件：决定哪些行可以被"选中"（读取阶段）
    2. WITH CHECK 条件：决定更新后的行是否满足策略（写入阶段）

  若 UPDATE 策略只有 USING 而没有 WITH CHECK，则攻击者可以：
    - 将 tenant_id 字段修改为其他租户的 UUID（数据越权写入）
    - 更新后的行不受任何租户约束检查

  涉及迁移及表：
    v067：purchase_invoices / purchase_match_records
      - 额外问题：使用三段条件而非 NULLIF 标准模式（技术上安全但不一致）
    v068：ontology_snapshots
    v069：api_applications / api_access_tokens / api_request_logs / api_webhooks
    v072：users
    v073：user_roles

标准 RLS 模式（v056+ 规范，严格遵守）：
  正确：tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
  UPDATE 策略必须同时包含：
    USING (...)          — 读取阶段行过滤
    WITH CHECK (...)     — 写入阶段行校验（防止 tenant_id 被篡改）

修复策略：
  对每张涉及的表，DROP 旧 UPDATE 策略，以完整的 USING + WITH CHECK 重建。
  使用幂等的 DROP POLICY IF EXISTS，可安全重复执行。
"""

from alembic import op

revision = "v075"
down_revision = "v074"
branch_labels = None
depends_on = None

# 标准 NULLIF NULL guard 条件（v056+ 唯一正确模式）
_SAFE_CONDITION = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"

# ─────────────────────────────────────────────────────────────────────────────
# 各表的 UPDATE 策略名（与原迁移保持一致）
# ─────────────────────────────────────────────────────────────────────────────

# v067 格式：{table}_update
V067_TABLES = [
    ("purchase_invoices", "purchase_invoices_update"),
    ("purchase_match_records", "purchase_match_records_update"),
]

# v068 格式：onto_snap_update
V068_TABLES = [
    ("ontology_snapshots", "onto_snap_update"),
]

# v069 格式：{prefix}_update
V069_TABLES = [
    ("api_applications", "api_apps_update"),
    ("api_access_tokens", "api_tokens_update"),
    ("api_request_logs", "api_logs_update"),
    ("api_webhooks", "api_webhooks_update"),
]

# v072 格式：users_update
V072_TABLES = [
    ("users", "users_update"),
]

# v073 格式：user_roles_update
V073_TABLES = [
    ("user_roles", "user_roles_update"),
]

ALL_TABLES = V067_TABLES + V068_TABLES + V069_TABLES + V072_TABLES + V073_TABLES


def upgrade() -> None:
    """重建所有缺少 WITH CHECK 的 UPDATE 策略。"""
    for table, policy_name in ALL_TABLES:
        # 删除旧 UPDATE 策略（幂等）
        op.execute(f"DROP POLICY IF EXISTS {policy_name} ON {table}")
        # 重建：同时包含 USING（读取过滤）和 WITH CHECK（写入校验）
        op.execute(
            f"CREATE POLICY {policy_name} ON {table} "
            f"FOR UPDATE "
            f"USING ({_SAFE_CONDITION}) "
            f"WITH CHECK ({_SAFE_CONDITION})"
        )


def downgrade() -> None:
    """回退：恢复只有 USING 的 UPDATE 策略（警告：回退后写入校验失效）。"""
    for table, policy_name in ALL_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {policy_name} ON {table}")
        op.execute(f"CREATE POLICY {policy_name} ON {table} FOR UPDATE USING ({_SAFE_CONDITION})")
