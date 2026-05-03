"""test_segmentation_routes — AM-1.1 人群细分 API 单元测试

覆盖：
  1. _parse_uuid 合法/非法输入
  2. _require_tenant Header 缺失/无效
  3. ok() 响应辅助函数
  4. _BUILT_IN_SEGMENTS 列表完整性
  5. 内置人群字段完整性
"""

from __future__ import annotations

import json
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from api.segmentation_routes import (  # noqa: E402
    _BUILT_IN_SEGMENTS,
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
        assert "格式无效" in exc.value.detail

    def test_empty_string_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            _parse_uuid("", field="segment_id")
        assert exc.value.status_code == 400
        assert "segment_id" in exc.value.detail

    def test_numeric_string_raises_400(self):
        with pytest.raises(HTTPException):
            _parse_uuid("12345")


class TestRequireTenant:
    def test_valid_tenant_returns_string(self):
        uid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        result = _require_tenant(x_tenant_id=uid)
        assert result == uid

    def test_invalid_tenant_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            _require_tenant(x_tenant_id="bad-tenant")
        assert exc.value.status_code == 400


class TestOkHelper:
    def test_ok_returns_expected_structure(self):
        result = ok({"key": "value"})
        assert result == {"ok": True, "data": {"key": "value"}}

    def test_ok_with_list(self):
        result = ok([1, 2, 3])
        assert result["ok"] is True
        assert result["data"] == [1, 2, 3]

    def test_ok_with_none(self):
        result = ok(None)
        assert result["ok"] is True
        assert result["data"] is None


class TestBuiltInSegments:
    def test_builtin_count(self):
        """应有 6 个内置人群"""
        assert len(_BUILT_IN_SEGMENTS) == 6

    def test_builtin_has_all_members(self):
        ids = {s["id"] for s in _BUILT_IN_SEGMENTS}
        assert "builtin_all_members" in ids
        assert "builtin_active_30d" in ids
        assert "builtin_dormant_30_90" in ids
        assert "builtin_churn_risk_90" in ids
        assert "builtin_high_value" in ids
        assert "builtin_new_7d" in ids

    def test_builtin_required_fields(self):
        for seg in _BUILT_IN_SEGMENTS:
            assert seg["id"], f"missing id in {seg}"
            assert seg["name"], f"missing name in {seg}"
            assert seg["type"] == "builtin", f"wrong type in {seg}"
            assert "criteria" in seg, f"missing criteria in {seg}"
            assert "color" in seg, f"missing color in {seg}"

    def test_builtin_unique_ids(self):
        ids = [s["id"] for s in _BUILT_IN_SEGMENTS]
        assert len(ids) == len(set(ids)), "duplicate builtin segment IDs"

    def test_builtin_criteria_are_valid(self):
        """内置人群的 criteria 为 dict 或空"""
        for seg in _BUILT_IN_SEGMENTS:
            assert isinstance(seg["criteria"], dict)


class TestBuiltinNameCompleteness:
    """确保内置人群覆盖主要营销场景的命名完整性"""

    def test_fresh_new_customer_segment(self):
        names = {s["name"] for s in _BUILT_IN_SEGMENTS}
        assert any("新客" in n or "新" in n for n in names), "缺少新客人群"

    def test_active_customer_segment(self):
        names = {s["name"] for s in _BUILT_IN_SEGMENTS}
        assert any("活跃" in n for n in names), "缺少活跃人群"

    def test_churn_risk_segment(self):
        names = {s["name"] for s in _BUILT_IN_SEGMENTS}
        assert any("流失" in n or "沉睡" in n for n in names), "缺少流失/沉睡人群"

    def test_high_value_segment(self):
        names = {s["name"] for s in _BUILT_IN_SEGMENTS}
        assert any("高价值" in n for n in names), "缺少高价值人群"
