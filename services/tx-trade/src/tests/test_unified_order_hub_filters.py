"""unified_order_hub 筛选参数解析（无 DB）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from services.unified_order_hub import (
    _parse_channel_key_filter,
    _parse_status_filter,
)


def test_parse_status_empty() -> None:
    assert _parse_status_filter(None) is None
    assert _parse_status_filter("") is None
    assert _parse_status_filter("  ") is None


def test_parse_status_normalizes_and_dedupes() -> None:
    assert _parse_status_filter("Pending, CONFIRMED,pending") == ["pending", "confirmed"]


def test_parse_status_invalid_token() -> None:
    with pytest.raises(ValueError, match="非法 status"):
        _parse_status_filter("ok-pending")


def test_parse_channel_key_ok() -> None:
    assert _parse_channel_key_filter("meituan") == "meituan"
    assert _parse_channel_key_filter("ch_meituan.v1") == "ch_meituan.v1"


def test_parse_channel_key_invalid() -> None:
    with pytest.raises(ValueError, match="channel_key"):
        _parse_channel_key_filter("a;b")
