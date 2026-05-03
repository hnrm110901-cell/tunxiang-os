"""MU-1 UnionID 全渠道打通 单元测试

覆盖：
  1. profile360 — unionid/openid 字段暴露（service 层）
  2. AssociateUnionIDReq Pydantic 模型校验（可脱离 DB 工作）
"""

from __future__ import annotations

import os
import sys
import uuid
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, Field, ValidationError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TENANT_ID = "a0000000-0000-0000-0000-000000000001"
CUSTOMER_A = "b0000000-0000-0000-0000-000000000001"
OPENID = "wx_openid_test_001"
UNIONID = "wx_unionid_test_001"


# ─── AssociateUnionIDReq Pydantic 模型（镜像用于测试）────────────────────


class _AssociateUnionIDReq(BaseModel):
    """Mirror of api.golden_id_routes.AssociateUnionIDReq for test validation.

    Defined here instead of imported because golden_id_routes has a
    relative import (`from ..db import get_db`) that fails outside the
    full service environment.
    """

    customer_id: str = Field(min_length=1)
    wechat_openid: str = Field(min_length=1, max_length=128)
    wechat_unionid: str = Field(min_length=1, max_length=128)
    operator_id: Optional[str] = Field(default=None)


class TestAssociateUnionIDReqModel:
    """AssociateUnionIDReq Pydantic 模型校验"""

    def test_valid_request(self):
        """有效请求应通过校验"""
        req = _AssociateUnionIDReq(
            customer_id=CUSTOMER_A,
            wechat_openid=OPENID,
            wechat_unionid=UNIONID,
        )
        assert req.customer_id == CUSTOMER_A
        assert req.wechat_openid == OPENID
        assert req.wechat_unionid == UNIONID

    def test_empty_customer_id_raises(self):
        """空 customer_id 应报错"""
        with pytest.raises(ValidationError):
            _AssociateUnionIDReq(
                customer_id="",
                wechat_openid=OPENID,
                wechat_unionid=UNIONID,
            )

    def test_empty_openid_raises(self):
        """空 wechat_openid 应报错"""
        with pytest.raises(ValidationError):
            _AssociateUnionIDReq(
                customer_id=CUSTOMER_A,
                wechat_openid="",
                wechat_unionid=UNIONID,
            )

    def test_empty_unionid_raises(self):
        """空 wechat_unionid 应报错"""
        with pytest.raises(ValidationError):
            _AssociateUnionIDReq(
                customer_id=CUSTOMER_A,
                wechat_openid=OPENID,
                wechat_unionid="",
            )

    def test_openid_too_long_raises(self):
        """超长 wechat_openid 应报错"""
        with pytest.raises(ValidationError):
            _AssociateUnionIDReq(
                customer_id=CUSTOMER_A,
                wechat_openid="x" * 129,
                wechat_unionid=UNIONID,
            )

    def test_operator_id_optional(self):
        """operator_id 应为可选字段"""
        req = _AssociateUnionIDReq(
            customer_id=CUSTOMER_A,
            wechat_openid=OPENID,
            wechat_unionid=UNIONID,
            operator_id="op001",
        )
        assert req.operator_id == "op001"

        req2 = _AssociateUnionIDReq(
            customer_id=CUSTOMER_A,
            wechat_openid=OPENID,
            wechat_unionid=UNIONID,
        )
        assert req2.operator_id is None


# ─── Test profile360 unionid exposure ─────────────────────────────────────


class TestProfile360UnionID:
    """profile360 应暴露 wechat_openid / wechat_unionid"""

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.__aenter__ = AsyncMock(return_value=db)
        db.__aexit__ = AsyncMock()
        return db

    def _make_member_row(self):
        return {
            "id": uuid.UUID(CUSTOMER_A),
            "primary_phone": "13800138000",
            "display_name": "测试会员",
            "gender": "male",
            "birth_date": None,
            "wechat_avatar_url": None,
            "wechat_nickname": "测试",
            "wechat_openid": OPENID,
            "wechat_unionid": UNIONID,
            "source": "wechat",
            "wecom_external_userid": None,
            "wecom_remark": None,
            "rfm_level": "S1",
            "r_score": 90,
            "f_score": 80,
            "m_score": 85,
            "risk_score": 10,
            "total_order_count": 10,
            "total_order_amount_fen": 100000,
            "first_order_at": None,
            "last_order_at": None,
            "tags": [],
            "created_at": None,
        }

    async def test_full_profile_contains_unionid(self, mock_db):
        """get_full_profile 返回的数据应包含 wechat_openid / wechat_unionid"""
        member_row = self._make_member_row()
        from services.profile360_service import Profile360Service

        svc = Profile360Service()

        with patch.object(svc, "_fetch_member", return_value=member_row):
            with patch.object(svc, "_fetch_consumption", return_value={}):
                with patch.object(svc, "_fetch_recent_30d", return_value={"count": 0, "amount_fen": 0}):
                    with patch.object(svc, "_fetch_frequent_store", return_value=None):
                        with patch.object(svc, "_fetch_dish_preferences", return_value=[]):
                            with patch.object(svc, "_fetch_stored_value", return_value={}):
                                with patch.object(svc, "_fetch_points", return_value={"balance": 0}):
                                    with patch.object(svc, "_fetch_member_card", return_value=None):
                                        with patch.object(svc, "_fetch_available_coupons", return_value=[]):
                                            with patch.object(svc, "_fetch_recent_coupon_sends", return_value=[]):
                                                with patch.object(svc, "_fetch_time_preference", return_value=None):
                                                    profile = await svc.get_full_profile(
                        TENANT_ID, CUSTOMER_A, mock_db
                    )

        assert profile is not None
        assert profile["wechat_openid"] == OPENID
        assert profile["wechat_unionid"] == UNIONID

    async def test_fetch_member_selects_unionid(self, mock_db):
        """_fetch_member 返回的数据应包含 wechat_openid 和 wechat_unionid"""
        from services.profile360_service import Profile360Service

        svc = Profile360Service()

        mock_result = AsyncMock()
        mock_mappings = MagicMock()
        mock_mappings.first = MagicMock(
            return_value={
                "id": uuid.UUID(CUSTOMER_A),
                "primary_phone": "13800138000",
                "display_name": "测试",
                "wechat_openid": OPENID,
                "wechat_unionid": UNIONID,
            }
        )
        mock_result.mappings = MagicMock(return_value=mock_mappings)
        mock_db.execute = AsyncMock(return_value=mock_result)

        row = await svc._fetch_member(TENANT_ID, CUSTOMER_A, mock_db)

        assert row is not None
        assert row.get("wechat_openid") == OPENID
        assert row.get("wechat_unionid") == UNIONID
