"""[Tier1] channel_identity_resolver.py 单元测试

CH-13（issue #393）。覆盖范围：
  1. phone 标准化（+86 / 前导 0 / 空格 / 横线）
  2. email / card_no / openid 标准化
  3. hash_identity 一致性（相同 phone 不同格式 → 相同 hash）
  4. hash_identity salt 隔离（不同 salt → 不同 hash）
  5. _load_salt env 处理
  6. validate openid 必须带 platform
  7. validate identity_type 白名单
  8. invalid confidence 拒绝

DB 交互真测在 shared/db-migrations/tests/test_v413_member_identity_map_tier1.py
（opt-in via INTEGRATION_PG_DSN）。
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from services.channel_identity_resolver import (
    ChannelIdentityResolverError,
    InvalidIdentityTypeError,
    MissingPlatformError,
    _normalize_card_no,
    _normalize_email,
    _normalize_openid,
    _normalize_phone,
    hash_identity,
    normalize,
    _load_salt,
)


# ─────────────────────────────────────────────────────────────────
# 1. phone 标准化
# ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw,expected", [
    ("13900001111", "13900001111"),       # 裸号
    ("139 0000 1111", "13900001111"),     # 带空格
    ("139-0000-1111", "13900001111"),     # 带横线
    ("+8613900001111", "13900001111"),    # +86 前缀
    ("8613900001111", "13900001111"),     # 86 前缀
    ("013900001111", "13900001111"),      # 前导 0
    ("00013900001111", "13900001111"),    # 多个前导 0
    ("  13900001111  ", "13900001111"),   # 两端空格
    ("+86 139-0000 1111", "13900001111"),  # 混合
])
def test_normalize_phone(raw, expected):
    assert _normalize_phone(raw) == expected


# ─────────────────────────────────────────────────────────────────
# 2. email / card_no / openid 标准化
# ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw,expected", [
    ("user@example.com", "user@example.com"),
    ("USER@EXAMPLE.COM", "user@example.com"),
    ("  user@Example.com  ", "user@example.com"),
])
def test_normalize_email(raw, expected):
    assert _normalize_email(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("CARD-001", "CARD001"),
    ("CARD 001", "CARD001"),
    ("  CARD-001  ", "CARD001"),
])
def test_normalize_card_no(raw, expected):
    assert _normalize_card_no(raw) == expected


def test_normalize_openid_keeps_original():
    """openid 在 platform 内已唯一，仅 trim 不改大小写不去符号。"""
    assert _normalize_openid("  oABC-xyz_123  ") == "oABC-xyz_123"


def test_normalize_dispatches_by_type():
    assert normalize("phone", "+86 139-0000-1111") == "13900001111"
    assert normalize("email", " USER@X.COM ") == "user@x.com"


def test_normalize_unknown_type_raises():
    with pytest.raises(InvalidIdentityTypeError):
        normalize("unknown", "value")


# ─────────────────────────────────────────────────────────────────
# 3. hash_identity 一致性
# ─────────────────────────────────────────────────────────────────


SALT = b"test-salt-2026"


def test_hash_phone_consistent_across_formats():
    """同一手机号不同格式 → 相同 hash（标准化生效的核心证据）。"""
    h1 = hash_identity("phone", "13900001111", salt=SALT)
    h2 = hash_identity("phone", "+86 139-0000-1111", salt=SALT)
    h3 = hash_identity("phone", "139 0000 1111", salt=SALT)
    h4 = hash_identity("phone", "013900001111", salt=SALT)
    assert h1 == h2 == h3 == h4
    assert len(h1) == 64  # SHA256 hex


def test_hash_different_phones_different():
    h1 = hash_identity("phone", "13900001111", salt=SALT)
    h2 = hash_identity("phone", "13900002222", salt=SALT)
    assert h1 != h2


def test_hash_email_normalized():
    h1 = hash_identity("email", "user@example.com", salt=SALT)
    h2 = hash_identity("email", "USER@Example.COM", salt=SALT)
    assert h1 == h2


def test_hash_type_separates_namespace():
    """同 value 不同 identity_type → 不同 hash（防 phone='13900001111' 撞 card_no='13900001111'）。"""
    h_phone = hash_identity("phone", "13900001111", salt=SALT)
    h_card = hash_identity("card_no", "13900001111", salt=SALT)
    assert h_phone != h_card


# ─────────────────────────────────────────────────────────────────
# 4. salt 隔离
# ─────────────────────────────────────────────────────────────────


def test_hash_different_salts_different():
    h1 = hash_identity("phone", "13900001111", salt=b"salt-A")
    h2 = hash_identity("phone", "13900001111", salt=b"salt-B")
    assert h1 != h2


def test_hash_loads_salt_from_env_when_omitted():
    """salt 参数省略时从 env 加载。"""
    with patch.dict(os.environ, {"IDENTITY_HASH_SALT": "env-salt"}):
        h_env = hash_identity("phone", "13900001111")
        h_explicit = hash_identity("phone", "13900001111", salt=b"env-salt")
    assert h_env == h_explicit


# ─────────────────────────────────────────────────────────────────
# 5. _load_salt env 处理
# ─────────────────────────────────────────────────────────────────


def test_load_salt_missing_raises():
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ChannelIdentityResolverError, match="IDENTITY_HASH_SALT"):
            _load_salt()


def test_load_salt_empty_raises():
    with patch.dict(os.environ, {"IDENTITY_HASH_SALT": ""}):
        with pytest.raises(ChannelIdentityResolverError, match="IDENTITY_HASH_SALT"):
            _load_salt()


# ─────────────────────────────────────────────────────────────────
# 6. validate openid 必须带 platform
# ─────────────────────────────────────────────────────────────────


def test_resolver_validate_openid_requires_platform():
    """openid 类型 platform=None 应抛 MissingPlatformError。

    用 hash_identity 触发不便（它不验 platform），改为间接验证：
    通过 mock session 构造 resolver 测 _validate。
    """
    # 简化：直接测 _validate 逻辑（resolver 依赖 _load_salt，需 mock env）
    from unittest.mock import MagicMock
    from services.channel_identity_resolver import (
        ChannelIdentityResolver,
    )
    fake_session = MagicMock()
    resolver = ChannelIdentityResolver(fake_session, salt=SALT)

    # openid + platform=None → 拒绝
    with pytest.raises(MissingPlatformError):
        resolver._validate("openid", None)

    # openid + 有 platform → OK
    resolver._validate("openid", "meituan")  # 不应抛错

    # phone + platform=None → OK（phone 跨平台允许）
    resolver._validate("phone", None)


# ─────────────────────────────────────────────────────────────────
# 7. validate identity_type 白名单
# ─────────────────────────────────────────────────────────────────


def test_resolver_validate_unknown_type():
    from unittest.mock import MagicMock
    from services.channel_identity_resolver import (
        ChannelIdentityResolver,
    )
    resolver = ChannelIdentityResolver(MagicMock(), salt=SALT)
    with pytest.raises(InvalidIdentityTypeError):
        resolver._validate("biometric", None)


# ─────────────────────────────────────────────────────────────────
# 8. 并发 race — link()/get_or_create_member 必须返回 DB 真实 member_id
# ─────────────────────────────────────────────────────────────────


def _make_mock_row(member_id_or_none):
    from unittest.mock import MagicMock
    m = MagicMock()
    m.mappings.return_value.first.return_value = (
        {"member_id": member_id_or_none} if member_id_or_none is not None else None
    )
    return m


async def test_link_returns_db_member_id_on_conflict_keeps_existing():
    """ON CONFLICT 场景：link() 通过 RETURNING 返回 DB 已有的 member_id（非本地传入值）。

    防止 issue：caller 在并发 race 中传入新 uuid，但 DB 已有记录，必须以 DB 为准。
    """
    from unittest.mock import AsyncMock, MagicMock
    from uuid import uuid4
    from services.channel_identity_resolver import ChannelIdentityResolver

    db_existing_id = uuid4()
    local_member_id = uuid4()

    fake_session = MagicMock()
    fake_session.execute = AsyncMock(return_value=_make_mock_row(db_existing_id))

    resolver = ChannelIdentityResolver(fake_session, salt=SALT)
    returned = await resolver.link(
        tenant_id=uuid4(),
        member_id=local_member_id,
        identity_type="phone",
        value="13900001111",
        platform=None,
    )
    assert returned == db_existing_id, "link() 必须返回 RETURNING 的 DB 真实值"
    assert returned != local_member_id, "并发 race 下 DB 真实值与本地传入值必然不同"


async def test_get_or_create_member_concurrent_race_returns_db_real_id():
    """并发 race：caller B 的本地 uuid4 与 DB 实际 member_id 不一致时，
    必须返回 DB 真实 ID，且 was_created=False。

    Race 场景（200 桌外卖 ingest 同手机号同时入）：
      T0: A、B 并发调 get_or_create_member 同 phone hash
      T1: A、B 各自 resolve() → 都返回 None
      T2: A 先 link()/INSERT，DB 写入 uuid_A
      T3: B 后 link()/INSERT，命中 ON CONFLICT DO UPDATE，DB 仍是 uuid_A
      T4: B 的 RETURNING 必须返回 uuid_A → 防止 orders.member_id 写入 uuid_B 错位
    """
    from unittest.mock import AsyncMock, MagicMock
    from uuid import uuid4
    from services.channel_identity_resolver import ChannelIdentityResolver

    db_winner_id = uuid4()
    fake_session = MagicMock()
    fake_session.execute = AsyncMock(side_effect=[
        _make_mock_row(None),           # resolve() → None
        _make_mock_row(db_winner_id),    # link() → DB 真实值（A 的）
    ])

    resolver = ChannelIdentityResolver(fake_session, salt=SALT)
    actual_id, was_created = await resolver.get_or_create_member(
        tenant_id=uuid4(),
        identity_type="phone",
        value="13900001111",
        platform=None,
    )
    assert actual_id == db_winner_id, (
        "并发 race 下必须返回 DB 真实 member_id，否则 orders.member_id 错位"
    )
    assert was_created is False, (
        "DB RETURNING 与本地 candidate 不同 → 本调用没真正创建 member"
    )


async def test_get_or_create_member_first_creator_was_created_true():
    """无 race：DB RETURNING 等于本调用 candidate → was_created=True。"""
    from unittest.mock import AsyncMock, MagicMock
    from uuid import UUID, uuid4
    from services.channel_identity_resolver import ChannelIdentityResolver

    fake_session = MagicMock()

    def execute_side_effect(stmt, params=None):
        # link() 路径：params 含 'member_id' 键 → 回显本调用传入的 uuid
        if params and "member_id" in params:
            return _make_mock_row(UUID(params["member_id"]))
        # resolve() 路径
        return _make_mock_row(None)

    fake_session.execute = AsyncMock(side_effect=execute_side_effect)

    resolver = ChannelIdentityResolver(fake_session, salt=SALT)
    actual_id, was_created = await resolver.get_or_create_member(
        tenant_id=uuid4(),
        identity_type="phone",
        value="13900001111",
        platform=None,
    )
    assert was_created is True, "无 race，DB RETURNING == candidate → 本调用真正创建"
    assert isinstance(actual_id, UUID)


async def test_get_or_create_member_existing_match_returns_was_created_false():
    """resolve() 命中已有 member → 直接返回，was_created=False，不生成新 uuid。"""
    from unittest.mock import AsyncMock, MagicMock
    from uuid import uuid4
    from services.channel_identity_resolver import ChannelIdentityResolver

    existing_member_id = uuid4()
    fake_session = MagicMock()
    fake_session.execute = AsyncMock(side_effect=[
        _make_mock_row(existing_member_id),       # resolve() → 命中
        _make_mock_row(existing_member_id),        # link() refresh last_seen_at
    ])

    resolver = ChannelIdentityResolver(fake_session, salt=SALT)
    actual_id, was_created = await resolver.get_or_create_member(
        tenant_id=uuid4(),
        identity_type="phone",
        value="13900001111",
        platform=None,
    )
    assert actual_id == existing_member_id
    assert was_created is False


async def test_get_or_create_member_existing_branch_uses_link_returning():
    """existing 分支必须使用 link() 的 RETURNING 真实值（而非本地 resolve() 结果）。

    防御 #412 race fix 的"另一面"漏洞：
      - T0: resolve() → uuid_A（行存在，DB 当前 member_id=uuid_A）
      - T1: 并发或 admin 操作改了 member_id（成员合并 / hard delete + 重插）
            DB 当前 member_id=uuid_X
      - T2: 我侧 link(existing=uuid_A) ON CONFLICT DO UPDATE，UPDATE SET 不含
            member_id 列，RETURNING 返 uuid_X（DB 真实值）
      - T3: existing 分支必须返回 uuid_X，不能返回 resolve() 时拍到的 uuid_A

    若 caller 拿 uuid_A 写到 orders.member_id → 错位失真（与 PR #412 同种 BUG）。
    """
    from unittest.mock import AsyncMock, MagicMock
    from uuid import uuid4
    from services.channel_identity_resolver import ChannelIdentityResolver

    resolved_id = uuid4()      # T0 resolve() 看到的 uuid
    db_actual_id = uuid4()      # T1 后 DB 真实值（admin/race 改过）

    fake_session = MagicMock()
    fake_session.execute = AsyncMock(side_effect=[
        _make_mock_row(resolved_id),    # resolve() → uuid_A
        _make_mock_row(db_actual_id),    # link() RETURNING → uuid_X (DB 真实)
    ])

    resolver = ChannelIdentityResolver(fake_session, salt=SALT)
    actual_id, was_created = await resolver.get_or_create_member(
        tenant_id=uuid4(),
        identity_type="phone",
        value="13900001111",
        platform=None,
    )
    assert actual_id == db_actual_id, (
        f"existing 分支必须返回 link() RETURNING 的 DB 真实值 {db_actual_id}，"
        f"实际返回 {actual_id}（应是本地 resolve 结果 {resolved_id} 或 DB 真实值）"
    )
    assert was_created is False
