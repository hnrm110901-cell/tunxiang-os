"""[Tier1][SECURITY] v411 — channel_oauth_tokens 表 + RLS

CH-01（channel-aggregation milestone, issue #375）：
为美团 / 抖音 / 饿了么 / 微信 / 小红书等渠道平台的 OAuth token 提供统一持久化，
支持多租户多门店多账号场景。

定位：本表是全渠道聚合的资质底盘 — Phase 1 (CH-03..06) 4 平台外卖订单实质化的前置。

表 schema：
  - token_id              UUID PK，gen_random_uuid 默认
  - tenant_id             UUID NOT NULL（RLS 强制）
  - store_id              UUID NOT NULL（多门店多 token 场景）
  - platform              VARCHAR(20) CHECK in ALLOWED_PLATFORMS（与 v285 canonical 对齐）
  - account_id            VARCHAR(64) NOT NULL（平台分配商户号 POI ID / shop_id 等）
  - access_token_enc      BYTEA NOT NULL（应用层 Fernet 加密，密钥从 env OAUTH_TOKEN_ENCRYPTION_KEY）
  - refresh_token_enc     BYTEA（可空，部分平台无 refresh_token）
  - token_type            VARCHAR(20) DEFAULT 'Bearer'
  - expires_at            TIMESTAMPTZ NOT NULL（access_token 过期时间）
  - refresh_expires_at    TIMESTAMPTZ（refresh_token 过期时间，可空）
  - scope                 TEXT（OAuth scope）
  - last_refreshed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
  - refresh_failure_count INT NOT NULL DEFAULT 0（续期失败计数，用于告警）
  - last_refresh_error    TEXT（最后续期失败原因，可空）
  - created_at / updated_at / is_deleted（§6 底层基类）

加密策略（决策记录）：
  - 不依赖 pgcrypto 扩展（避免密钥下沉到 SQL 文本风险）
  - BYTEA 字段存储，应用层用 cryptography.fernet.Fernet 加解密
  - 密钥从 OS env `OAUTH_TOKEN_ENCRYPTION_KEY`（base64 32-byte key），不入库不入代码
  - 详见 shared/adapters/base/src/oauth_token_store.py

约束：
  - 复合 UNIQUE (tenant_id, store_id, platform, account_id) — 一组 token 唯一标识
  - platform CHECK 与 shared/adapters/delivery_canonical/base.py:ALLOWED_PLATFORMS 对齐

索引：
  - 复合 UNIQUE 自带索引
  - ix_channel_oauth_tokens_tenant_expires (tenant_id, expires_at) — 自动续期 job 高频扫
  - WHERE is_deleted = FALSE — partial index 节省空间

RLS：v403 / v395 模式
  - ENABLE + FORCE
  - SELECT       USING-only
  - INSERT/UPDATE/DELETE  USING + WITH CHECK（v395 PR #139 §19 修法）

部署约束（CLAUDE.md §17 Tier1 + §21 灰度）：
  - 新表 + 4 RLS policy，DDL 毫秒级，可在低峰窗口直接灰度
  - 无数据迁移
  - 上线前必须配置 OS env OAUTH_TOKEN_ENCRYPTION_KEY（生产 / 预发 / 开发各一）

Revision ID: v411_channel_oauth_tokens
Revises: v409_fund_settlement_revive
Create Date: 2026-05-10
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v411_channel_oauth_tokens"
down_revision: Union[str, None] = "v409_fund_settlement_revive"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "channel_oauth_tokens"
_RLS_EXPR = "NULLIF(current_setting('app.tenant_id', true), '')::UUID"

# 写入侧 actions — INSERT/UPDATE/DELETE 必须 USING + WITH CHECK（v395 修法）
_WRITE_ACTIONS = ("INSERT", "UPDATE", "DELETE")

# 与 shared/adapters/delivery_canonical/base.py:ALLOWED_PLATFORMS 对齐
# 新增平台时需同步两处
_ALLOWED_PLATFORMS = (
    "meituan", "eleme", "douyin", "xiaohongshu", "wechat", "grabfood", "other"
)


def upgrade() -> None:
    # 1. 建表
    platforms_check = ", ".join(f"'{p}'" for p in _ALLOWED_PLATFORMS)
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            token_id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            store_id                UUID NOT NULL,
            platform                VARCHAR(20) NOT NULL
                                    CHECK (platform IN ({platforms_check})),
            account_id              VARCHAR(64) NOT NULL,
            access_token_enc        BYTEA NOT NULL,
            refresh_token_enc       BYTEA,
            token_type              VARCHAR(20) NOT NULL DEFAULT 'Bearer',
            expires_at              TIMESTAMPTZ NOT NULL,
            refresh_expires_at      TIMESTAMPTZ,
            scope                   TEXT,
            last_refreshed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            refresh_failure_count   INTEGER NOT NULL DEFAULT 0,
            last_refresh_error      TEXT,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE,
            CONSTRAINT uq_{_TABLE}_tenant_store_platform_account
                UNIQUE (tenant_id, store_id, platform, account_id)
        );
    """)

    # 2. 索引 — 自动续期 job 扫"将过期"高频
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_{_TABLE}_tenant_expires "
        f"ON {_TABLE} (tenant_id, expires_at) "
        f"WHERE is_deleted = FALSE;"
    )

    # 3. RLS — ENABLE + FORCE
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY;")

    # 4. SELECT 策略 — USING-only
    op.execute(f"DROP POLICY IF EXISTS rls_{_TABLE}_select ON {_TABLE};")
    op.execute(
        f"CREATE POLICY rls_{_TABLE}_select ON {_TABLE} "
        f"AS PERMISSIVE FOR SELECT TO PUBLIC "
        f"USING (tenant_id = {_RLS_EXPR});"
    )

    # 5. INSERT/UPDATE/DELETE 策略 — USING + WITH CHECK（v395 修法）
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
    # DROP TABLE 自动级联删 policies + index
    op.execute(f"DROP TABLE IF EXISTS {_TABLE};")
