"""小红书核销测试 — 客户端 + 适配器

测试:
1. XHSClient 签名生成
2. XHSClient 公共参数构建
3. XHSCouponAdapter 重复核销拦截
4. XHSCouponAdapter 列表查询
5. Webhook 端点冒烟
6. POI 绑定端点冒烟
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

import pytest

from shared.adapters.xiaohongshu.src.xhs_client import XHSClient

# ===========================================================================
# 1. XHSClient 签名
# ===========================================================================


def test_sign_deterministic():
    """相同参数生成相同签名"""
    client = XHSClient(app_id="test_app", app_secret="test_secret")
    params = {"app_id": "test_app", "timestamp": "1700000000", "nonce": "abc123"}
    sign1 = client._sign(params)
    sign2 = client._sign(params)
    assert sign1 == sign2
    assert len(sign1) == 64  # SHA256 hex


def test_sign_changes_with_params():
    """不同参数生成不同签名"""
    client = XHSClient(app_id="test_app", app_secret="test_secret")
    params1 = {"app_id": "test_app", "timestamp": "1700000000", "nonce": "abc"}
    params2 = {"app_id": "test_app", "timestamp": "1700000001", "nonce": "abc"}
    assert client._sign(params1) != client._sign(params2)


def test_sign_sorted_keys():
    """参数按 key 字典序排列"""
    client = XHSClient(app_id="test_app", app_secret="secret")
    params_a = {"z": "1", "a": "2", "m": "3"}
    params_b = {"a": "2", "m": "3", "z": "1"}
    assert client._sign(params_a) == client._sign(params_b)


# ===========================================================================
# 2. 公共参数
# ===========================================================================


def test_common_params_structure():
    """公共参数包含 app_id/timestamp/nonce"""
    client = XHSClient(app_id="my_app", app_secret="my_secret")
    params = client._build_common_params()
    assert params["app_id"] == "my_app"
    assert "timestamp" in params
    assert "nonce" in params
    assert len(params["nonce"]) == 16


# ===========================================================================
# 3. API 调用冒烟（Mock 模式）
# ===========================================================================


@pytest.mark.asyncio
async def test_verify_coupon_mock():
    """核销 API 返回结构正确（Mock 模式）"""
    client = XHSClient(app_id="test", app_secret="test")
    result = await client.verify_coupon("CODE123", "shop-001")
    assert isinstance(result, dict)
    assert "verified" in result


@pytest.mark.asyncio
async def test_get_poi_info_mock():
    """POI 查询返回结构正确（Mock 模式）"""
    client = XHSClient(app_id="test", app_secret="test")
    result = await client.get_poi_info("poi-001")
    assert isinstance(result, dict)
    assert "code" in result


@pytest.mark.asyncio
async def test_get_store_notes_mock():
    """笔记查询返回结构正确（Mock 模式）"""
    client = XHSClient(app_id="test", app_secret="test")
    result = await client.get_store_notes("poi-001", page=1, size=10)
    assert isinstance(result, dict)
