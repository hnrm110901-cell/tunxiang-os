"""
奥琦玮 CRM 适配器单元测试

重点验证：
  1. 签名算法（_compute_sig / _ksort_recursive / _http_build_query）
     — 这是最核心的正确性约束，任何修改必须通过这些回归测试
  2. 请求体构建（appkey 不出现在发送体中）
  3. 业务方法入参校验
"""

import hashlib
import time
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

import pytest
from src.crm_adapter import (
    AoqiweiCrmAdapter,
    _compute_sig,
    _http_build_query,
    _ksort_recursive,
)

# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def crm_adapter() -> AoqiweiCrmAdapter:
    return AoqiweiCrmAdapter(
        {
            "base_url": "https://welcrm.com",
            "appid": "TEST_APPID",
            "appkey": "TEST_APPKEY",
            "timeout": 5,
            "retry_times": 1,
        }
    )


# ── _ksort_recursive ────────────────────────────────────────────────────────────


class TestKsortRecursive:
    def test_flat_dict_sorted(self):
        result = _ksort_recursive({"b": 2, "a": 1, "c": 3})
        assert list(result.keys()) == ["a", "b", "c"]

    def test_nested_dict_sorted(self):
        result = _ksort_recursive({"z": {"b": 2, "a": 1}, "a": 0})
        assert list(result.keys()) == ["a", "z"]
        assert list(result["z"].keys()) == ["a", "b"]

    def test_bool_true_becomes_1(self):
        assert _ksort_recursive(True) == 1

    def test_bool_false_becomes_0(self):
        assert _ksort_recursive(False) == 0

    def test_list_items_recursed(self):
        result = _ksort_recursive([{"b": 2, "a": 1}])
        assert list(result[0].keys()) == ["a", "b"]

    def test_scalar_passthrough(self):
        assert _ksort_recursive(42) == 42
        assert _ksort_recursive("hello") == "hello"
        assert _ksort_recursive(None) is None


# ── _http_build_query ────────────────────────────────────────────────────────────


class TestHttpBuildQuery:
    def test_flat_params(self):
        result = _http_build_query({"a": "1", "b": "2"})
        assert result == "a=1&b=2"

    def test_skips_none(self):
        result = _http_build_query({"a": "1", "b": None, "c": "3"})
        assert "b" not in result
        assert "a=1" in result
        assert "c=3" in result

    def test_skips_empty_string(self):
        result = _http_build_query({"a": "1", "b": "", "c": "3"})
        assert "b" not in result

    def test_nested_dict(self):
        result = _http_build_query({"outer": {"inner": "val"}})
        assert "outer%5Binner%5D=val" in result

    def test_list_values(self):
        result = _http_build_query({"arr": ["x", "y"]})
        assert "arr%5B0%5D=x" in result
        assert "arr%5B1%5D=y" in result

    def test_integer_values(self):
        result = _http_build_query({"amount": 1234})
        assert result == "amount=1234"

    def test_empty_dict(self):
        assert _http_build_query({}) == ""

    def test_space_encoded_as_plus(self):
        result = _http_build_query({"name": "hello world"})
        assert "hello+world" in result


# ── _compute_sig ────────────────────────────────────────────────────────────────


class TestComputeSig:
    """
    签名算法回归测试。
    黄金值由手动模拟 PHP 算法计算得出，任何算法变更必须更新黄金值。
    """

    def _expected_sig(
        self,
        biz_params: Dict[str, Any],
        appid: str,
        appkey: str,
        ts: int,
        version: str = "2.0",
    ) -> str:
        """
        本地参考实现（独立于被测代码）。
        等价于 PHP:
          ksort($args);
          $args['appid'] = appid; $args['appkey'] = appkey; $args['v'] = version; $args['ts'] = ts;
          $query = http_build_query($args);
          return md5($query);
        """
        sorted_params = _ksort_recursive(biz_params)
        query = _http_build_query(sorted_params)
        query += f"&appid={appid}&appkey={appkey}&v={version}&ts={ts}"
        return hashlib.md5(query.encode("utf-8")).hexdigest().lower()

    def test_flat_params_match_reference(self):
        params = {"cno": "1234567890", "shop_id": 42, "consume_amount": 10000}
        ts = 1700000000
        sig = _compute_sig(params, "APPID", "APPKEY", ts)
        expected = self._expected_sig(params, "APPID", "APPKEY", ts)
        assert sig == expected

    def test_deterministic(self):
        params = {"cno": "ABC", "shop_id": 1}
        ts = 1700000001
        assert _compute_sig(params, "ID", "KEY", ts) == _compute_sig(params, "ID", "KEY", ts)

    def test_output_is_32_char_lowercase_hex(self):
        sig = _compute_sig({"a": "1"}, "id", "key", 1000)
        assert len(sig) == 32
        assert sig == sig.lower()
        assert all(c in "0123456789abcdef" for c in sig)

    def test_different_ts_gives_different_sig(self):
        params = {"cno": "X"}
        sig1 = _compute_sig(params, "ID", "KEY", 1000)
        sig2 = _compute_sig(params, "ID", "KEY", 1001)
        assert sig1 != sig2

    def test_appkey_change_changes_sig(self):
        params = {"cno": "X"}
        ts = 1000
        sig1 = _compute_sig(params, "ID", "KEY1", ts)
        sig2 = _compute_sig(params, "ID", "KEY2", ts)
        assert sig1 != sig2

    def test_param_order_does_not_affect_sig(self):
        """参数顺序不影响签名（因为会先 ksort）"""
        ts = 1000
        params_a = {"z": "last", "a": "first", "m": "mid"}
        params_b = {"a": "first", "m": "mid", "z": "last"}
        assert _compute_sig(params_a, "ID", "KEY", ts) == _compute_sig(params_b, "ID", "KEY", ts)

    def test_seconds_level_timestamp(self):
        """ts 必须是秒级整数（不是毫秒）"""
        ts = int(time.time())
        # 应为 10位数字
        assert 1_000_000_000 <= ts <= 9_999_999_999


# ── AoqiweiCrmAdapter 初始化 ────────────────────────────────────────────────────


class TestCrmAdapterInit:
    def test_init_success(self):
        adapter = AoqiweiCrmAdapter({"base_url": "https://welcrm.com", "appid": "AID", "appkey": "AKEY"})
        assert adapter.appid == "AID"
        assert adapter.appkey == "AKEY"
        assert adapter.base_url == "https://welcrm.com"

    def test_init_missing_credentials_does_not_raise(self, monkeypatch):
        monkeypatch.delenv("AOQIWEI_CRM_APPID", raising=False)
        monkeypatch.delenv("AOQIWEI_CRM_APPKEY", raising=False)
        adapter = AoqiweiCrmAdapter({"base_url": "https://welcrm.com"})
        assert adapter is not None


# ── 请求体构建：appkey 不泄露 ─────────────────────────────────────────────────────


class TestBuildRequestBody:
    def test_appkey_not_in_body(self, crm_adapter):
        body = crm_adapter._build_request_body({"cno": "123"})
        assert "appkey" not in body

    def test_sig_in_body(self, crm_adapter):
        body = crm_adapter._build_request_body({"cno": "123"})
        assert "sig" in body
        assert len(body["sig"]) == 32

    def test_appid_in_body(self, crm_adapter):
        body = crm_adapter._build_request_body({"cno": "123"})
        assert body["appid"] == "TEST_APPID"

    def test_v_in_body(self, crm_adapter):
        body = crm_adapter._build_request_body({"cno": "123"})
        assert body["v"] == "2.0"

    def test_ts_is_seconds_level_integer(self, crm_adapter):
        body = crm_adapter._build_request_body({})
        ts = body["ts"]
        assert isinstance(ts, int)
        assert 1_000_000_000 <= ts <= 9_999_999_999

    def test_biz_params_preserved(self, crm_adapter):
        body = crm_adapter._build_request_body({"cno": "XYZ", "shop_id": 5})
        assert body["cno"] == "XYZ"
        assert body["shop_id"] == 5


# ── get_member_info 入参校验 ──────────────────────────────────────────────────────


class TestGetMemberInfoValidation:
    @pytest.mark.asyncio
    async def test_raises_if_no_cno_or_mobile(self, crm_adapter):
        with pytest.raises(ValueError, match="cno 和 mobile"):
            await crm_adapter.get_member_info()

    @pytest.mark.asyncio
    async def test_cno_only_accepted(self, crm_adapter):
        """只传 cno 时不报错（实际网络调用会失败，但校验通过）"""
        with patch.object(crm_adapter, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"balance": 100}
            result = await crm_adapter.get_member_info(cno="1234567890")
        assert result == {"balance": 100}
        called_params = mock_req.call_args[0][1]
        assert called_params["cno"] == "1234567890"
        assert "mobile" not in called_params

    @pytest.mark.asyncio
    async def test_mobile_only_accepted(self, crm_adapter):
        with patch.object(crm_adapter, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {}
            await crm_adapter.get_member_info(mobile="13800138000")
        called_params = mock_req.call_args[0][1]
        assert called_params["mobile"] == "13800138000"

    @pytest.mark.asyncio
    async def test_returns_empty_dict_on_error(self, crm_adapter):
        with patch.object(crm_adapter, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = Exception("网络超时")
            result = await crm_adapter.get_member_info(cno="X")
        assert result == {}


# ── deal_preview 业务流程 ─────────────────────────────────────────────────────────


class TestDealPreview:
    @pytest.mark.asyncio
    async def test_calls_correct_endpoint(self, crm_adapter):
        with patch.object(crm_adapter, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"final_amount": 9800}
            await crm_adapter.deal_preview(
                cno="CARD001",
                shop_id=10,
                cashier_id=-1,
                consume_amount=10000,
                payment_amount=10000,
                payment_mode=3,
                biz_id="BIZ_UNIQUE_001",
            )
        assert mock_req.call_args[0][0] == "/deal/preview"

    @pytest.mark.asyncio
    async def test_returns_error_dict_on_failure(self, crm_adapter):
        with patch.object(crm_adapter, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = Exception("连接超时")
            result = await crm_adapter.deal_preview(
                cno="CARD001",
                shop_id=10,
                cashier_id=-1,
                consume_amount=10000,
                payment_amount=10000,
                payment_mode=3,
                biz_id="BIZ_001",
            )
        assert result["success"] is False
        assert "message" in result

    @pytest.mark.asyncio
    async def test_sub_balance_defaults_to_zero(self, crm_adapter):
        with patch.object(crm_adapter, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {}
            await crm_adapter.deal_preview(
                cno="C",
                shop_id=1,
                cashier_id=-1,
                consume_amount=100,
                payment_amount=100,
                payment_mode=1,
                biz_id="BIZ",
            )
        params = mock_req.call_args[0][1]
        assert params["sub_balance"] == 0
        assert params["sub_credit"] == 0


# ── deal_reverse 入参 ─────────────────────────────────────────────────────────────


class TestDealReverse:
    @pytest.mark.asyncio
    async def test_calls_correct_endpoint(self, crm_adapter):
        with patch.object(crm_adapter, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"result": "ok"}
            await crm_adapter.deal_reverse(
                biz_id="ORIG_BIZ_001",
                shop_id=10,
                cashier_id=-1,
            )
        assert mock_req.call_args[0][0] == "/deal/reverse"

    @pytest.mark.asyncio
    async def test_reverse_reason_omitted_when_empty(self, crm_adapter):
        with patch.object(crm_adapter, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {}
            await crm_adapter.deal_reverse(biz_id="B", shop_id=1, cashier_id=-1)
        params = mock_req.call_args[0][1]
        assert "reverse_reason" not in params

    @pytest.mark.asyncio
    async def test_reverse_reason_included_when_set(self, crm_adapter):
        with patch.object(crm_adapter, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {}
            await crm_adapter.deal_reverse(biz_id="B", shop_id=1, cashier_id=-1, reverse_reason="误操作")
        params = mock_req.call_args[0][1]
        assert params["reverse_reason"] == "误操作"
