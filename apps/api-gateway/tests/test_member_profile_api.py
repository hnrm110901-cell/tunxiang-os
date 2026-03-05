"""
private_domain.py 会员档案管理端点测试

覆盖：
  GET  /private-domain/members/{store_id}/list
    - 正常返回分页列表（total/page/members）
    - search 参数按 ILIKE 过滤
    - lifecycle_state 过滤
    - rfm_level 过滤
    - 空结果正常返回
    - DB 异常返回 500

  PATCH /private-domain/members/{store_id}/{customer_id}
    - 更新 birth_date 成功
    - 更新 wechat_openid 成功
    - 同时更新多个字段
    - 空 body（无可更新字段）返回 422
    - 会员不存在返回 404
    - DB 异常返回 500
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("APP_ENV", "test")

from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date
import pytest


# ════════════════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════════════════

def _member_row(
    customer_id="C001", rfm_level="S2", lifecycle_state="repeat",
    birth_date=None, wechat_openid="wx001", channel_source="wxwork",
    recency_days=5, frequency=8, monetary=50000,
    last_visit="2026-03-01", is_active=True, created_at="2025-01-10",
):
    row = MagicMock()
    vals = (
        customer_id, rfm_level, lifecycle_state, birth_date,
        wechat_openid, channel_source, recency_days, frequency,
        monetary, last_visit, is_active, created_at,
    )
    row.__getitem__ = lambda self, i: vals[i]
    return row


def _make_db(count=1, rows=None, returning=None, raise_exc=None):
    """Construct a mock AsyncSession."""
    db = AsyncMock()

    call_count = [0]

    async def execute(sql, params=None):
        call_count[0] += 1
        mock_result = MagicMock()
        if raise_exc:
            raise raise_exc
        if "COUNT(" in str(sql):
            mock_result.scalar = MagicMock(return_value=count)
        elif "RETURNING" in str(sql):
            mock_result.fetchone = MagicMock(return_value=returning)
        else:
            mock_result.fetchall = MagicMock(return_value=rows or [])
        return mock_result

    db.execute = execute
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


# ════════════════════════════════════════════════════════════════════════════
# GET /members/{store_id}/list
# ════════════════════════════════════════════════════════════════════════════

class TestListMembers:

    @pytest.mark.asyncio
    async def test_returns_paginated_list(self):
        from src.api.private_domain import list_members
        from unittest.mock import MagicMock

        row = _member_row()
        db = _make_db(count=1, rows=[row])
        mock_user = MagicMock()

        result = await list_members(
            store_id="S001", page=1, page_size=20,
            search=None, lifecycle_state=None, rfm_level=None,
            current_user=mock_user, db=db,
        )

        assert result["store_id"] == "S001"
        assert result["total"] == 1
        assert result["page"] == 1
        assert len(result["members"]) == 1
        m = result["members"][0]
        assert m["customer_id"] == "C001"
        assert m["rfm_level"] == "S2"
        assert m["monetary_yuan"] == 500.0

    @pytest.mark.asyncio
    async def test_empty_result(self):
        from src.api.private_domain import list_members
        from unittest.mock import MagicMock

        db = _make_db(count=0, rows=[])
        result = await list_members(
            store_id="S001", page=1, page_size=20,
            search=None, lifecycle_state=None, rfm_level=None,
            current_user=MagicMock(), db=db,
        )
        assert result["total"] == 0
        assert result["members"] == []

    @pytest.mark.asyncio
    async def test_search_filter_included(self):
        """search 参数被传入时，结果仍正常返回（SQL 动态拼接覆盖）。"""
        from src.api.private_domain import list_members
        from unittest.mock import MagicMock

        row = _member_row(customer_id="C_SEARCH_001")
        db = _make_db(count=1, rows=[row])
        result = await list_members(
            store_id="S001", page=1, page_size=20,
            search="C_SEARCH", lifecycle_state=None, rfm_level=None,
            current_user=MagicMock(), db=db,
        )
        assert result["members"][0]["customer_id"] == "C_SEARCH_001"

    @pytest.mark.asyncio
    async def test_lifecycle_filter(self):
        from src.api.private_domain import list_members
        from unittest.mock import MagicMock

        row = _member_row(lifecycle_state="dormant")
        db = _make_db(count=1, rows=[row])
        result = await list_members(
            store_id="S001", page=1, page_size=20,
            search=None, lifecycle_state="dormant", rfm_level=None,
            current_user=MagicMock(), db=db,
        )
        assert result["members"][0]["lifecycle_state"] == "dormant"

    @pytest.mark.asyncio
    async def test_rfm_filter(self):
        from src.api.private_domain import list_members
        from unittest.mock import MagicMock

        row = _member_row(rfm_level="S1")
        db = _make_db(count=1, rows=[row])
        result = await list_members(
            store_id="S001", page=1, page_size=20,
            search=None, lifecycle_state=None, rfm_level="S1",
            current_user=MagicMock(), db=db,
        )
        assert result["members"][0]["rfm_level"] == "S1"

    @pytest.mark.asyncio
    async def test_birth_date_serialized_as_string(self):
        from src.api.private_domain import list_members
        from unittest.mock import MagicMock

        row = _member_row(birth_date=date(1992, 8, 15))
        db = _make_db(count=1, rows=[row])
        result = await list_members(
            store_id="S001", page=1, page_size=20,
            search=None, lifecycle_state=None, rfm_level=None,
            current_user=MagicMock(), db=db,
        )
        assert result["members"][0]["birth_date"] == "1992-08-15"

    @pytest.mark.asyncio
    async def test_db_error_raises_500(self):
        from src.api.private_domain import list_members
        from fastapi import HTTPException
        from unittest.mock import MagicMock

        db = _make_db(raise_exc=Exception("DB down"))
        with pytest.raises(HTTPException) as exc_info:
            await list_members(
                store_id="S001", page=1, page_size=20,
                search=None, lifecycle_state=None, rfm_level=None,
                current_user=MagicMock(), db=db,
            )
        assert exc_info.value.status_code == 500


# ════════════════════════════════════════════════════════════════════════════
# PATCH /members/{store_id}/{customer_id}
# ════════════════════════════════════════════════════════════════════════════

class TestPatchMemberProfile:

    @pytest.mark.asyncio
    async def test_update_birth_date(self):
        from src.api.private_domain import patch_member_profile, MemberProfilePatch
        from unittest.mock import MagicMock

        db = _make_db(returning=("C001",))
        body = MemberProfilePatch(birth_date=date(1993, 5, 20))
        result = await patch_member_profile(
            store_id="S001", customer_id="C001",
            body=body, current_user=MagicMock(), db=db,
        )
        assert result["updated"] is True
        assert "birth_date" in result["fields"]

    @pytest.mark.asyncio
    async def test_update_wechat_openid(self):
        from src.api.private_domain import patch_member_profile, MemberProfilePatch
        from unittest.mock import MagicMock

        db = _make_db(returning=("C002",))
        body = MemberProfilePatch(wechat_openid="new_wx_id_001")
        result = await patch_member_profile(
            store_id="S001", customer_id="C002",
            body=body, current_user=MagicMock(), db=db,
        )
        assert result["updated"] is True
        assert "wechat_openid" in result["fields"]

    @pytest.mark.asyncio
    async def test_update_multiple_fields(self):
        from src.api.private_domain import patch_member_profile, MemberProfilePatch
        from unittest.mock import MagicMock

        db = _make_db(returning=("C003",))
        body = MemberProfilePatch(
            birth_date=date(1990, 3, 5),
            wechat_openid="wx_new",
            channel_source="miniapp",
        )
        result = await patch_member_profile(
            store_id="S001", customer_id="C003",
            body=body, current_user=MagicMock(), db=db,
        )
        assert set(result["fields"]) == {"birth_date", "wechat_openid", "channel_source"}

    @pytest.mark.asyncio
    async def test_empty_body_raises_422(self):
        from src.api.private_domain import patch_member_profile, MemberProfilePatch
        from fastapi import HTTPException
        from unittest.mock import MagicMock

        db = _make_db()
        body = MemberProfilePatch()  # all None
        with pytest.raises(HTTPException) as exc_info:
            await patch_member_profile(
                store_id="S001", customer_id="C001",
                body=body, current_user=MagicMock(), db=db,
            )
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_member_not_found_raises_404(self):
        from src.api.private_domain import patch_member_profile, MemberProfilePatch
        from fastapi import HTTPException
        from unittest.mock import MagicMock

        db = _make_db(returning=None)  # RETURNING returns nothing
        body = MemberProfilePatch(birth_date=date(2000, 1, 1))
        with pytest.raises(HTTPException) as exc_info:
            await patch_member_profile(
                store_id="S001", customer_id="NO_EXIST",
                body=body, current_user=MagicMock(), db=db,
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_db_error_raises_500_and_rollback(self):
        from src.api.private_domain import patch_member_profile, MemberProfilePatch
        from fastapi import HTTPException
        from unittest.mock import MagicMock

        db = _make_db(raise_exc=Exception("constraint violation"))
        body = MemberProfilePatch(birth_date=date(2000, 1, 1))
        with pytest.raises(HTTPException) as exc_info:
            await patch_member_profile(
                store_id="S001", customer_id="C001",
                body=body, current_user=MagicMock(), db=db,
            )
        assert exc_info.value.status_code == 500
        db.rollback.assert_called_once()
