"""[Tier1][SECURITY] v413 — member_identity_map 表 + RLS

CH-13（channel-aggregation milestone, issue #393）：
跨渠道身份解析（CDP 雏形）— 把 phone / openid / card_no 反向映射到统一 member_id，
让 mv_member_clv 全渠道版（CH-15）能算"老客复购率"。

定位：CH-14（渠道订单反向解析到 member_id）的前置；demo "全渠道老客识别"卖点的底盘。

表 schema：
  - identity_id           UUID PK，gen_random_uuid 默认
  - tenant_id             UUID NOT NULL（RLS 强制）
  - member_id             UUID NOT NULL（指向 customers / members 主表）
  - identity_type         VARCHAR(16) CHECK in ('phone','openid','card_no','email')
  - identity_value_hash   CHAR(64) NOT NULL（SHA256 hex，phone 标准化后哈希）
  - platform              VARCHAR(20)（openid 必填；phone/card_no/email 通常 NULL 表"跨平台"）
                          CHECK in ALLOWED_PLATFORMS or NULL
  - confidence            NUMERIC(5,4) NOT NULL DEFAULT 1.0
                          CHECK (confidence BETWEEN 0 AND 1)
  - first_seen_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
  - last_seen_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
  - source                VARCHAR(32)（cashier_engine / channel_ingest / manual_link 等）
  - created_at / updated_at / is_deleted（§6 底层基类）

约束：
  - 复合 UNIQUE (tenant_id, identity_type, identity_value_hash, platform)
    NULLS NOT DISTINCT — PG 15+ 特性：让 platform=NULL 也参与去重
    （同 tenant + 同 identity hash + platform=NULL 不可重复）

索引：
  - 复合 UNIQUE 自带索引
  - ix_member_identity_map_member: (tenant_id, member_id) WHERE is_deleted=FALSE
    — list_member_identities 反查路径
  - ix_member_identity_map_hash_lookup: (tenant_id, identity_value_hash, identity_type)
    WHERE is_deleted=FALSE — resolve() 高频查找

加密 / 哈希策略：
  - phone / card_no / email 全部 SHA256 哈希后存储，不存原文
  - 标准化规则（在 services/tx-member/src/services/identity_resolver.py 实现）：
    - phone: 去除 +86 / 前导 0 / 空格 / 横线
    - email: lowercase + trim
    - card_no: 去除空格 + 横线
    - openid: 原样（platform 内已唯一）
  - 哈希前 salt 用 OS env `IDENTITY_HASH_SALT`（防彩虹表 + 同租户内可比性）

RLS：v403 / v395 模式（ENABLE + FORCE，写入侧 USING + WITH CHECK）

部署约束（CLAUDE.md §17 Tier1）：
  - 新表 + 4 RLS policy，DDL 毫秒级
  - PG 15+ 必需（NULLS NOT DISTINCT 特性）；屯象生产用 PG 16，OK
  - 上线前必须配 OS env IDENTITY_HASH_SALT

Revision ID: v413_member_identity_map
Revises: v412_raw_channel_events
Create Date: 2026-05-10
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v413_member_identity_map"
down_revision: Union[str, None] = "v412_raw_channel_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "member_identity_map"
_RLS_EXPR = "NULLIF(current_setting('app.tenant_id', true), '')::UUID"
_WRITE_ACTIONS = ("INSERT", "UPDATE", "DELETE")

_ALLOWED_IDENTITY_TYPES = ("phone", "openid", "card_no", "email")
_ALLOWED_PLATFORMS = (
    "meituan", "eleme", "douyin", "xiaohongshu", "wechat", "grabfood", "other"
)


def upgrade() -> None:
    identity_types_check = ", ".join(f"'{t}'" for t in _ALLOWED_IDENTITY_TYPES)
    platforms_check = ", ".join(f"'{p}'" for p in _ALLOWED_PLATFORMS)
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            identity_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            member_id               UUID NOT NULL,
            identity_type           VARCHAR(16) NOT NULL
                                    CHECK (identity_type IN ({identity_types_check})),
            identity_value_hash     CHAR(64) NOT NULL,
            platform                VARCHAR(20)
                                    CHECK (platform IS NULL OR platform IN ({platforms_check})),
            confidence              NUMERIC(5,4) NOT NULL DEFAULT 1.0
                                    CHECK (confidence BETWEEN 0 AND 1),
            first_seen_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_seen_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            source                  VARCHAR(32),
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE,
            CONSTRAINT uq_{_TABLE}_tenant_type_hash_platform
                UNIQUE NULLS NOT DISTINCT
                (tenant_id, identity_type, identity_value_hash, platform)
        );
    """)

    # 索引：member_id 反查（list_member_identities 路径）
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_{_TABLE}_member "
        f"ON {_TABLE} (tenant_id, member_id) "
        f"WHERE is_deleted = FALSE;"
    )

    # 索引：resolve() 高频查找路径（hash + type）
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_{_TABLE}_hash_lookup "
        f"ON {_TABLE} (tenant_id, identity_value_hash, identity_type) "
        f"WHERE is_deleted = FALSE;"
    )

    # RLS — ENABLE + FORCE
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY;")

    # SELECT 策略 — USING-only
    op.execute(f"DROP POLICY IF EXISTS rls_{_TABLE}_select ON {_TABLE};")
    op.execute(
        f"CREATE POLICY rls_{_TABLE}_select ON {_TABLE} "
        f"AS PERMISSIVE FOR SELECT TO PUBLIC "
        f"USING (tenant_id = {_RLS_EXPR});"
    )

    # 写入侧策略 — USING + WITH CHECK（v395 修法）
    for action in _WRITE_ACTIONS:
        policy = f"rls_{_TABLE}_{action.lower()}_with_check"
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {_TABLE};")
        op.execute(
            f"CREATE POLICY {policy} ON {_TABLE} "
            f"AS PERMISSIVE FOR {action} TO PUBLIC "
            f"USING (tenant_id = {_RLS_EXPR}) "
            f"WITH CHECK (tenant_id = {_RLS_EXPR});"
        )


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {_TABLE};")
