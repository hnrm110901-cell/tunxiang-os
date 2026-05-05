"""Tests for 高德 AMAP adapter"""
import pytest
from shared.adapters.amap.src.client import AmapClient


class TestAmapClient:
    async def test_sign_consistency(self):
        """相同参数产生相同签名"""
        client = AmapClient(app_key="test_key", app_secret="test_secret", sandbox=True)
        params1 = {"store_id": "1001", "timestamp": "1234567890"}
        params2 = {"store_id": "1001", "timestamp": "1234567890"}
        assert client._sign(params1) == client._sign(params2)
        await client.close()

    async def test_sign_changes_with_params(self):
        """不同参数产生不同签名"""
        client = AmapClient(app_key="test_key", app_secret="test_secret", sandbox=True)
        params1 = {"store_id": "1001", "timestamp": "1234567890"}
        params2 = {"store_id": "1002", "timestamp": "1234567890"}
        assert client._sign(params1) != client._sign(params2)
        await client.close()
