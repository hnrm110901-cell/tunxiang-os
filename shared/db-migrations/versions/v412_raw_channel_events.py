"""[Tier1][SECURITY] v412 — raw_channel_events 表 + RLS

CH-02.5（channel-aggregation milestone, issue #377）：
所有渠道平台 webhook 接收的原始 payload 落湖，幂等去重，便于事故重放与合规审计。

定位：是 channel webhook → channel_canonical_service ingest 链路的"防丢消息 + 重放"安全网。
所有 webhook 路由（/meituan/order /eleme/order /douyin/order /wechat/order）在签名校验通过后
立即落本表，再走 ingest。

表 schema：
  - event_id              UUID PK，gen_random_uuid 默认（内部 ID）
  - tenant_id             UUID NOT NULL（RLS 强制）
  - platform              VARCHAR(20) CHECK in ALLOWED_PLATFORMS（与 v411 / canonical 对齐）
  - external_event_id     VARCHAR(128) NOT NULL（平台分配的唯一事件 ID，幂等键）
  - event_type            VARCHAR(32) NOT NULL（order_pushed / status_changed / refund_requested 等）
  - payload               JSONB NOT NULL（原始 payload，原样落库不做改写）
  - signature             VARCHAR(256)（webhook 签名，用于事后审计）
  - received_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
  - processed_at          TIMESTAMPTZ（成功投递到 ingest 后写入）
  - status                VARCHAR(20) NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending','processed','failed','skipped'))
  - process_error         TEXT（失败原因，可空）
  - retry_count           INTEGER NOT NULL DEFAULT 0
  - created_at / updated_at / is_deleted（§6 底层基类）

约束：
  - 复合 UNIQUE (tenant_id, platform, external_event_id) — 幂等去重；
    重复 webhook 投递（平台超时重试常见）将被 ON CONFLICT 跳过

索引：
  - 复合 UNIQUE 自带索引
  - ix_raw_channel_events_pending: (tenant_id, status, received_at)
    WHERE status = 'pending' — 重试队列扫描
  - ix_raw_channel_events_received: (tenant_id, received_at DESC)
    WHERE is_deleted = FALSE — 审计排查

RLS：v403 / v395 模式
  - ENABLE + FORCE
  - SELECT       USING-only
  - INSERT/UPDATE/DELETE  USING + WITH CHECK（v395 修法）

部署约束（CLAUDE.md §17 Tier1）：
  - 新表 + 4 RLS policy，DDL 毫秒级
  - JSONB payload 单条预估 < 10KB（外卖 webhook 典型负载），10W/日 → 1GB/年/租户

Revision ID: v412_raw_channel_events
Revises: v411_channel_oauth_tokens
Create Date: 2026-05-10
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v412_raw_channel_events"
down_revision: Union[str, None] = "v411_channel_oauth_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "raw_channel_events"
_RLS_EXPR = "NULLIF(current_setting('app.tenant_id', true), '')::UUID"
_WRITE_ACTIONS = ("INSERT", "UPDATE", "DELETE")

# 与 v411_channel_oauth_tokens._ALLOWED_PLATFORMS 对齐
_ALLOWED_PLATFORMS = (
    "meituan", "eleme", "douyin", "xiaohongshu", "wechat", "grabfood", "other"
)


def upgrade() -> None:
    platforms_check = ", ".join(f"'{p}'" for p in _ALLOWED_PLATFORMS)
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            event_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            platform            VARCHAR(20) NOT NULL
                                CHECK (platform IN ({platforms_check})),
            external_event_id   VARCHAR(128) NOT NULL,
            event_type          VARCHAR(32) NOT NULL,
            payload             JSONB NOT NULL,
            signature           VARCHAR(256),
            received_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            processed_at        TIMESTAMPTZ,
            status              VARCHAR(20) NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending','processed','failed','skipped')),
            process_error       TEXT,
            retry_count         INTEGER NOT NULL DEFAULT 0,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
            CONSTRAINT uq_{_TABLE}_tenant_platform_event
                UNIQUE (tenant_id, platform, external_event_id)
        );
    """)

    # 索引：重试队列扫描（status=pending 高频）
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_{_TABLE}_pending "
        f"ON {_TABLE} (tenant_id, status, received_at) "
        f"WHERE status = 'pending' AND is_deleted = FALSE;"
    )

    # 索引：审计排查（按时间倒序）
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_{_TABLE}_received "
        f"ON {_TABLE} (tenant_id, received_at DESC) "
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
