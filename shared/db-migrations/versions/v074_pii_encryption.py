"""v074 — PII字段加密列 + 数据完整性列

等保三级要求：
  - 数据保密性：敏感个人信息（手机号）存储加密
  - 数据完整性：关键业务数据（订单）HMAC校验

迁移策略（渐进式，不影响现有数据）：
  1. customers表：新增 phone_encrypted TEXT, phone_last4 CHAR(4)
     原有明文列 primary_phone 保留30天过渡期，迁移脚本执行后可删除
  2. employees表：新增 phone_encrypted TEXT, phone_last4 CHAR(4)
     原有明文列 phone, emergency_phone 保留30天过渡期
  3. orders表：新增 integrity_hash VARCHAR(64)
     用于HMAC-SHA256防篡改校验（签名字段：id, tenant_id, total_amount, discount_amount, final_amount）

注：financial_records表在本项目中不存在，跳过。
    如未来添加财务明细流水表，请在对应迁移中添加 integrity_hash 列。

执行顺序：
  1. 本迁移（添加列）
  2. 配置 TX_FIELD_ENCRYPTION_KEY 和 TX_INTEGRITY_SECRET 环境变量
  3. 执行 scripts/migrate_pii_encryption.py（回填加密数据）
  4. 应用切换读取加密列
  5. 30天后删除明文列（需另建迁移）

Revision ID: v074
Revises: v073
Create Date: 2026-03-31
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "v074"
down_revision: str = "v073"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # customers — 手机号加密列
    # primary_phone（明文）保留过渡期，phone_encrypted为加密后的完整手机号
    # phone_last4 明文存储最后4位，用于搜索/展示（无需解密）
    # ─────────────────────────────────────────────────────────────────
    op.add_column(
        "customers",
        sa.Column(
            "phone_encrypted",
            sa.Text,
            nullable=True,
            comment="AES-256-GCM加密的手机号（格式：enc:v1:<base64>），迁移完成后替代primary_phone",
        ),
    )
    op.add_column(
        "customers",
        sa.Column(
            "phone_last4",
            sa.CHAR(4),
            nullable=True,
            comment="手机号后4位明文，用于展示脱敏（****6789）和模糊查询",
        ),
    )

    # ─────────────────────────────────────────────────────────────────
    # employees — 手机号加密列
    # 员工手机号(phone)和紧急联系人手机号(emergency_phone)均加密
    # ─────────────────────────────────────────────────────────────────
    op.add_column(
        "employees",
        sa.Column(
            "phone_encrypted",
            sa.Text,
            nullable=True,
            comment="AES-256-GCM加密的员工手机号（格式：enc:v1:<base64>），迁移完成后替代phone",
        ),
    )
    op.add_column(
        "employees",
        sa.Column(
            "phone_last4",
            sa.CHAR(4),
            nullable=True,
            comment="员工手机号后4位明文，用于展示脱敏和模糊查询",
        ),
    )
    op.add_column(
        "employees",
        sa.Column(
            "emergency_phone_encrypted",
            sa.Text,
            nullable=True,
            comment="AES-256-GCM加密的紧急联系人手机号（格式：enc:v1:<base64>），迁移完成后替代emergency_phone",
        ),
    )

    # ─────────────────────────────────────────────────────────────────
    # orders — 数据完整性校验列
    # HMAC-SHA256签名，防止订单金额被数据库层面篡改
    # 签名字段：id, tenant_id, total_amount, discount_amount, final_amount
    # ─────────────────────────────────────────────────────────────────
    op.add_column(
        "orders",
        sa.Column(
            "integrity_hash",
            sa.String(64),
            nullable=True,
            comment="HMAC-SHA256订单完整性签名（覆盖：id/tenant_id/total_amount/discount_amount/final_amount）",
        ),
    )

    # financial_records表不存在，跳过
    # 如未来新增财务流水明细表，请参考orders表模式添加 integrity_hash 列


def downgrade() -> None:
    # orders — 移除完整性校验列
    op.drop_column("orders", "integrity_hash")

    # employees — 移除加密列
    op.drop_column("employees", "emergency_phone_encrypted")
    op.drop_column("employees", "phone_last4")
    op.drop_column("employees", "phone_encrypted")

    # customers — 移除加密列
    op.drop_column("customers", "phone_last4")
    op.drop_column("customers", "phone_encrypted")
