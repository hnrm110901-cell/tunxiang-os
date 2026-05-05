"""Tests for 淘宝闪购 adapter"""
import pytest
from shared.adapters.taobao.src.client import TaobaoClient


class TestTaobaoClient:
    async def test_sign_consistency(self):
        client = TaobaoClient(app_key="test", app_secret="test", sandbox=True)
        params1 = {"method": "test.api", "timestamp": "2026-01-01 00:00:00"}
        params2 = {k: v for k, v in params1.items()}
        assert client._sign(params1) == client._sign(params2)
        await client.close()

    async def test_sign_changes_with_params(self):
        client = TaobaoClient(app_key="test", app_secret="test", sandbox=True)
        params1 = {"method": "api.one", "timestamp": "2026-01-01 00:00:00"}
        params2 = {"method": "api.two", "timestamp": "2026-01-01 00:00:00"}
        assert client._sign(params1) != client._sign(params2)
        await client.close()
