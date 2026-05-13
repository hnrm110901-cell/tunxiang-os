"""D2-B grabfood enum-shrink — 3 表 CHECK constraint 删 'grabfood' token

承接 PR #527 (Issue #522 D2 走 A) 删 grabfood 代码层后, 本 PR 修 production
PG schema: v411/v412/v413 三表 CHECK constraint 收缩 enum 删 'grabfood'.

Python 源码 v411/v412/v413 的 _ALLOWED_PLATFORMS 已在 #527 删除 (与
canonical/base.py:ALLOWED_PLATFORMS 重新对齐, drift test 全过). 本 PR 真实
ALTER PG CHECK constraint.

创始人 risk-accept (路径 A): 假定 production 三表 WHERE platform='grabfood'
全零, 5 条独立证据 (analyst D2 brief converge):
  1. 0 production webhook 流量
  2. 0 staging seed grabfood tenant
  3. 0 metrics counter
  4. 3 首批客户 (czyz/zqx/sgc) 无 6 月内出海规划
  5. channel-aggregation-plan-2026-05-10.md L36 明示"出海储备 不在 demo 路径"

如果 production 真有 'grabfood' row, ALTER 会 fail (PG 阻止违反 CHECK 的
ALTER). 该场景视为 production rollback + 创始人决策.

Tier 1 — DDL 改动, 影响 channel oauth / webhook events / member identity
3 表 INSERT/UPDATE 校验. 不动业务代码, 不动 RLS policy, 不动 column 数据.

v411/v412/v413 三表的 platform CHECK 均为匿名内联 CHECK, PostgreSQL 自动
命名为 <tablename>_platform_check. v412 另有 status column 内联 CHECK
(status_check), DROP IF EXISTS 不会误删.

Revision ID: v417_grabfood_enum_shrink
Revises: v416_w2a_phase4_reverse
Create Date: 2026-05-13
"""

from typing import Sequence, Union
from alembic import op

revision: str = "v417_grabfood_enum_shrink"
down_revision: Union[str, None] = "v416_w2a_phase4_reverse"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 收缩后的 platforms enum (与 canonical/base.py:ALLOWED_PLATFORMS 对齐, 删 'grabfood')
_ALLOWED_PLATFORMS_NEW = (
    "meituan", "eleme", "douyin", "xiaohongshu", "wechat", "other"
)


def upgrade() -> None:
    """3 表 CHECK constraint 收缩, drop+recreate pattern.

    PostgreSQL 匿名内联 CHECK 自动命名: <tablename>_platform_check.
    v411 / v412: platform NOT NULL, CHECK (platform IN (...))
    v413: platform NULL-able, CHECK (platform IS NULL OR platform IN (...))
    """
    platforms_check = ", ".join(f"'{p}'" for p in _ALLOWED_PLATFORMS_NEW)

    # channel_oauth_tokens (v411) — platform NOT NULL
    op.execute(
        "ALTER TABLE channel_oauth_tokens "
        "DROP CONSTRAINT IF EXISTS channel_oauth_tokens_platform_check"
    )
    op.execute(
        f"ALTER TABLE channel_oauth_tokens "
        f"ADD CONSTRAINT channel_oauth_tokens_platform_check "
        f"CHECK (platform IN ({platforms_check}))"
    )

    # raw_channel_events (v412) — platform NOT NULL
    op.execute(
        "ALTER TABLE raw_channel_events "
        "DROP CONSTRAINT IF EXISTS raw_channel_events_platform_check"
    )
    op.execute(
        f"ALTER TABLE raw_channel_events "
        f"ADD CONSTRAINT raw_channel_events_platform_check "
        f"CHECK (platform IN ({platforms_check}))"
    )

    # member_identity_map (v413) — platform NULL-able, 保留 IS NULL OR
    op.execute(
        "ALTER TABLE member_identity_map "
        "DROP CONSTRAINT IF EXISTS member_identity_map_platform_check"
    )
    op.execute(
        f"ALTER TABLE member_identity_map "
        f"ADD CONSTRAINT member_identity_map_platform_check "
        f"CHECK (platform IS NULL OR platform IN ({platforms_check}))"
    )


def downgrade() -> None:
    """Reverse: 恢复含 'grabfood' 的 CHECK constraint."""
    platforms_check_old = ", ".join(
        f"'{p}'" for p in (
            "meituan", "eleme", "douyin", "xiaohongshu", "wechat", "grabfood", "other"
        )
    )

    # channel_oauth_tokens (v411) — platform NOT NULL
    op.execute(
        "ALTER TABLE channel_oauth_tokens "
        "DROP CONSTRAINT IF EXISTS channel_oauth_tokens_platform_check"
    )
    op.execute(
        f"ALTER TABLE channel_oauth_tokens "
        f"ADD CONSTRAINT channel_oauth_tokens_platform_check "
        f"CHECK (platform IN ({platforms_check_old}))"
    )

    # raw_channel_events (v412) — platform NOT NULL
    op.execute(
        "ALTER TABLE raw_channel_events "
        "DROP CONSTRAINT IF EXISTS raw_channel_events_platform_check"
    )
    op.execute(
        f"ALTER TABLE raw_channel_events "
        f"ADD CONSTRAINT raw_channel_events_platform_check "
        f"CHECK (platform IN ({platforms_check_old}))"
    )

    # member_identity_map (v413) — platform NULL-able, 恢复 IS NULL OR
    op.execute(
        "ALTER TABLE member_identity_map "
        "DROP CONSTRAINT IF EXISTS member_identity_map_platform_check"
    )
    op.execute(
        f"ALTER TABLE member_identity_map "
        f"ADD CONSTRAINT member_identity_map_platform_check "
        f"CHECK (platform IS NULL OR platform IN ({platforms_check_old}))"
    )
