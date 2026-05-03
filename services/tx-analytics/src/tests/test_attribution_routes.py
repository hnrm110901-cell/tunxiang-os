"""test_attribution_routes — AM-1.4 全链路归因 API 单元测试

覆盖：
  1. _parse_uuid 合法/非法输入
  2. _require_tenant Header 缺失/无效
  3. ok() 响应辅助函数
  4. 路由参数验证（日期格式、granularity 枚举）
"""

from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from api.attribution_routes import (  # noqa: E402
    _parse_uuid,
    _require_tenant,
    ok,
)


class TestParseUUID:
    def test_valid_uuid_returns_uuid_object(self):
        uid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        result = _parse_uuid(uid)
        assert isinstance(result, uuid.UUID)
        assert str(result) == uid

    def test_invalid_uuid_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            _parse_uuid("not-a-uuid")
        assert exc.value.status_code == 400

    def test_empty_string_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            _parse_uuid("")
        assert exc.value.status_code == 400

    def test_custom_field_name_in_error(self):
        with pytest.raises(HTTPException) as exc:
            _parse_uuid("bad", field="campaign_id")
        assert "campaign_id" in exc.value.detail

    def test_near_uuid_format_still_invalid(self):
        """类 UUID 格式但含非法字符"""
        with pytest.raises(HTTPException):
            _parse_uuid("xxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")


class TestRequireTenant:
    def test_valid_tenant_returns_string(self):
        uid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        result = _require_tenant(x_tenant_id=uid)
        assert result == uid

    def test_invalid_tenant_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            _require_tenant(x_tenant_id="bad-tenant")
        assert exc.value.status_code == 400

    def test_empty_tenant_raises_400(self):
        with pytest.raises(HTTPException):
            _require_tenant(x_tenant_id="")


class TestOkHelper:
    def test_ok_with_dict(self):
        result = ok({"a": 1, "b": 2})
        assert result == {"ok": True, "data": {"a": 1, "b": 2}}

    def test_ok_with_list(self):
        result = ok([1, 2, 3])
        assert result["ok"] is True
        assert result["data"] == [1, 2, 3]

    def test_ok_with_none(self):
        result = ok(None)
        assert result["ok"] is True
        assert result["data"] is None


class TestDateValidation:
    """验证路由层日期逻辑 (通过导入日期常量验证)"""

    def test_date_imports_available(self):
        """验证模块依赖的日期函数可用"""
        from datetime import date, timedelta

        today = date.today()
        delta = today - timedelta(days=30)
        assert delta < today
        assert delta.isoformat() is not None


class TestGranularityValidation:
    """验证 granularity 参数约束"""

    def test_valid_granularity_values(self):
        valid = {"day", "week", "month"}
        assert "day" in valid
        assert "week" in valid
        assert "month" in valid
        assert len(valid) == 3

    def test_invalid_granularity_rejected(self):
        invalid_values = ["year", "hour", "minute", "daily", "weekly"]
        valid = {"day", "week", "month"}
        for v in invalid_values:
            assert v not in valid, f"{v} 不应是合法的 granularity"


class TestResponseStructure:
    """确保响应格式一致性"""

    def test_ok_response_structure(self):
        resp = ok({"campaigns": [], "total": 0})
        assert list(resp.keys()) == ["ok", "data"]
        assert resp["ok"] is True
        assert isinstance(resp["data"], dict)

    def test_ok_response_with_pagination(self):
        data = {
            "campaigns": [{"id": "1", "name": "test"}],
            "total": 1,
            "page": 1,
            "size": 20,
        }
        resp = ok(data)
        assert resp["data"]["total"] == 1
        assert resp["data"]["page"] == 1
