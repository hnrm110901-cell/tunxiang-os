"""v042: 跨品牌会员权益穿越 — group_member_profiles + cross_brand_transactions

集团级表（无 RLS）：
  group_member_profiles    — 集团会员档案，跨品牌统一视图
  cross_brand_transactions — 跨品牌交易记录（积分转移/储值通用记录）

设计说明：
  - 这两张表是「集团级表」，存储在集团主库，不做 RLS 租户隔离。
  - 数据隔离改用 group_id 字段实现（不同集团之间数据不互通）。
  - 查询这两张表必须使用 group_service_role 连接（BYPASSRLS 权限）。
  - phone_hash 使用 SHA256(手机号明文)，不存储明文手机号。

Revision ID: v042
Revises: v040
Create Date: 2026-03-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID, ARRAY

revision: str = "v042"
down_revision: Union[str, None] = "v040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE_PROFILES = "group_member_profiles"
_TABLE_TRANSACTIONS = "cross_brand_transactions"


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # group_member_profiles — 集团会员档案
    #
    # 注意：本表不启用 RLS，用 group_id 字段隔离不同集团数据。
    # 访问本表必须通过 group_service_role（BYPASSRLS）连接，普通品牌
    # tenant 角色无权直接访问，避免跨集团数据泄露。
    # ─────────────────────────────────────────────────────────────────
    op.create_table(
        _TABLE_PROFILES,
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "group_id",
            UUID(as_uuid=True),
            nullable=False,
            comment="关联 brand_groups.id",
        ),
        sa.Column(
            "phone_hash",
            sa.String(64),
            nullable=False,
            comment="SHA256(手机号明文) — 不存储明文",
        ),
        sa.Column(
            "total_points",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
            comment="集团积分池（可跨品牌使用）",
        ),
        sa.Column(
            "total_stored_value_fen",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
            comment="跨品牌储值余额合计（只读汇总，不用于实际扣款）",
        ),
        sa.Column(
            "brands_visited",
            ARRAY(UUID(as_uuid=True)),
            nullable=True,
            server_default=sa.text("'{}'"),
            comment="访问过的品牌 tenant_id 列表",
        ),
        sa.Column(
            "last_visit_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="最近一次跨品牌访问时间",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.UniqueConstraint("group_id", "phone_hash", name="uq_group_member_phone"),
        comment="集团会员档案（聚合多品牌下的统一视图）",
    )

    # 索引：按 group_id 查所有集团会员；按 phone_hash 全局反查
    op.create_index(
        "idx_gmp_group_id",
        _TABLE_PROFILES,
        ["group_id"],
    )
    op.create_index(
        "idx_gmp_phone_hash",
        _TABLE_PROFILES,
        ["phone_hash"],
    )
    op.create_index(
        "idx_gmp_last_visit",
        _TABLE_PROFILES,
        ["group_id", "last_visit_at"],
    )

    # ─────────────────────────────────────────────────────────────────
    # cross_brand_transactions — 跨品牌交易记录
    #
    # 记录所有跨品牌操作的审计日志：
    #   points_earn      — 消费积累集团积分
    #   points_use       — 使用集团积分
    #   points_transfer  — 积分在品牌间转移
    #   stored_value_query — 跨品牌查询储值余额（审计用）
    #
    # 本表同样不启用 RLS，通过 group_id 隔离。
    # ─────────────────────────────────────────────────────────────────
    op.create_table(
        _TABLE_TRANSACTIONS,
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "group_member_id",
            UUID(as_uuid=True),
            sa.ForeignKey(f"{_TABLE_PROFILES}.id", ondelete="RESTRICT"),
            nullable=False,
            comment="关联 group_member_profiles.id",
        ),
        sa.Column(
            "group_id",
            UUID(as_uuid=True),
            nullable=False,
            comment="冗余 group_id，方便按集团聚合查询",
        ),
        sa.Column(
            "from_tenant_id",
            UUID(as_uuid=True),
            nullable=False,
            comment="来源品牌 tenant_id",
        ),
        sa.Column(
            "to_tenant_id",
            UUID(as_uuid=True),
            nullable=False,
            comment="目标品牌 tenant_id（points_transfer 场景；其他场景与 from_tenant_id 相同）",
        ),
        sa.Column(
            "transaction_type",
            sa.String(30),
            nullable=False,
            comment="points_earn / points_use / points_transfer / stored_value_query",
        ),
        sa.Column(
            "points_delta",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
            comment="积分变动（正为增，负为减）",
        ),
        sa.Column(
            "amount_fen",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
            comment="金额（仅 stored_value 场景，单位：分）",
        ),
        sa.Column(
            "order_id",
            UUID(as_uuid=True),
            nullable=True,
            comment="关联订单（可选）",
        ),
        sa.Column(
            "operator_id",
            UUID(as_uuid=True),
            nullable=True,
            comment="操作员 ID",
        ),
        sa.Column(
            "note",
            sa.Text(),
            nullable=True,
            comment="备注",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        comment="跨品牌交易记录（积分转移/储值查询审计日志）",
    )

    # 索引：按集团+会员查流水；按集团+类型查聚合；按时间倒序分页
    op.create_index(
        "idx_cbt_group_member",
        _TABLE_TRANSACTIONS,
        ["group_member_id", "created_at"],
    )
    op.create_index(
        "idx_cbt_group_type",
        _TABLE_TRANSACTIONS,
        ["group_id", "transaction_type", "created_at"],
    )
    op.create_index(
        "idx_cbt_from_tenant",
        _TABLE_TRANSACTIONS,
        ["from_tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_cbt_from_tenant", table_name=_TABLE_TRANSACTIONS)
    op.drop_index("idx_cbt_group_type", table_name=_TABLE_TRANSACTIONS)
    op.drop_index("idx_cbt_group_member", table_name=_TABLE_TRANSACTIONS)
    op.drop_table(_TABLE_TRANSACTIONS)

    op.drop_index("idx_gmp_last_visit", table_name=_TABLE_PROFILES)
    op.drop_index("idx_gmp_phone_hash", table_name=_TABLE_PROFILES)
    op.drop_index("idx_gmp_group_id", table_name=_TABLE_PROFILES)
    op.drop_constraint("uq_group_member_phone", _TABLE_PROFILES, type_="unique")
    op.drop_table(_TABLE_PROFILES)
