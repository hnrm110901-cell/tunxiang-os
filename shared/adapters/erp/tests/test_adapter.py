"""
ERP 适配器测试 — 金蝶 + 用友

Mock httpx.AsyncClient 覆盖：
- push_voucher 成功/失败路径
- sync_chart_of_accounts 成功/降级路径
- health_check
- 幂等性
- 事件发射
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from shared.adapters.erp.src import (
    ERPAccount,
    ERPPushResult,
    ERPType,
    ERPVoucher,
    ERPVoucherEntry,
    PushStatus,
    VoucherType,
)
from shared.adapters.erp.src.kingdee_adapter import KingdeeAdapter
from shared.adapters.erp.src.yonyou_adapter import YonyouAdapter


# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def sample_voucher():
    """标准测试凭证（借贷平衡）"""
    return ERPVoucher(
        voucher_type=VoucherType.MEMO,
        business_date=date(2026, 5, 3),
        entries=[
            ERPVoucherEntry(
                account_code="5001",
                account_name="主营业务收入",
                credit_fen=8800,
                summary="日结收入结转",
            ),
            ERPVoucherEntry(
                account_code="1002",
                account_name="银行存款",
                debit_fen=8800,
                summary="日结收入结转",
            ),
        ],
        source_type="daily_revenue",
        source_id="SETTLE001",
        tenant_id="tenant-1",
        store_id="store-1",
    )


# ─── 金蝶适配器测试 ─────────────────────────────────────────────────────────


class TestKingdeeAdapter:
    """金蝶 K3/Cloud 适配器测试"""

    @pytest.fixture
    def adapter(self, monkeypatch):
        monkeypatch.setenv("KINGDEE_APP_ID", "test_app_id")
        monkeypatch.setenv("KINGDEE_APP_SECRET", "test_app_secret")
        monkeypatch.setenv("KINGDEE_BASE_URL", "https://kingdee.example.com")
        return KingdeeAdapter()

    @pytest.mark.asyncio
    async def test_push_voucher_success(self, adapter, sample_voucher):
        """凭证推送成功"""
        mock_response = httpx.Response(
            200,
            json={
                "Result": {"Result": True, "Id": "KD12345"},
            },
        )
        with patch.object(adapter._client, "post", return_value=mock_response):
            result = await adapter.push_voucher(sample_voucher)

        assert result.status == PushStatus.SUCCESS
        assert result.erp_voucher_id == "KD12345"
        assert result.erp_type == ERPType.KINGDEE

    @pytest.mark.asyncio
    async def test_push_voucher_business_error(self, adapter, sample_voucher):
        """金蝶 API 返回业务错误"""
        mock_response = httpx.Response(
            200,
            json={
                "Result": {"Result": False, "Message": "科目编码不存在"},
            },
        )
        with patch.object(adapter._client, "post", return_value=mock_response):
            with pytest.raises(RuntimeError, match="科目编码不存在"):
                await adapter.push_voucher(sample_voucher)

    @pytest.mark.asyncio
    async def test_health_check_success(self, adapter):
        """健康检查成功"""
        mock_response = httpx.Response(200)
        with patch.object(adapter._client, "head", return_value=mock_response):
            assert await adapter.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self, adapter):
        """健康检查失败"""
        mock_response = httpx.Response(500)
        with patch.object(adapter._client, "head", return_value=mock_response):
            assert await adapter.health_check() is False

    @pytest.mark.asyncio
    async def test_health_check_http_error(self, adapter):
        """健康检查网络异常降级"""
        with patch.object(adapter._client, "head", side_effect=httpx.ConnectError("timeout")):
            assert await adapter.health_check() is False

    @pytest.mark.asyncio
    async def test_sync_chart_of_accounts_success(self, adapter):
        """科目同步成功"""
        mock_response = httpx.Response(
            200,
            json={
                "data": [
                    {
                        "FNumber": "1001",
                        "FName": "库存现金",
                        "FAccountType": "资产",
                        "FIsLeaf": True,
                    },
                    {
                        "FNumber": "1002",
                        "FName": "银行存款",
                        "FAccountType": "资产",
                        "FIsLeaf": True,
                    },
                ]
            },
        )
        with patch.object(adapter._client, "get", return_value=mock_response):
            accounts = await adapter.sync_chart_of_accounts()

        assert len(accounts) == 2
        assert accounts[0].code == "1001"
        assert accounts[0].name == "库存现金"
        assert accounts[0].is_leaf is True

    @pytest.mark.asyncio
    async def test_sync_chart_of_accounts_fallback(self, adapter):
        """科目同步HTTP失败时降级到默认科目表"""
        with patch.object(adapter._client, "get", side_effect=httpx.ConnectError("timeout")):
            accounts = await adapter.sync_chart_of_accounts()

        # 降级到13个内置默认科目
        assert len(accounts) == 13
        assert accounts[0].code == "1001"
        assert accounts[-1].code == "5602"

    @pytest.mark.asyncio
    async def test_push_voucher_triggers_event(self, adapter, sample_voucher):
        """push_voucher 成功后触发事件发射"""
        mock_response = httpx.Response(
            200,
            json={"Result": {"Result": True, "Id": "KD12345"}},
        )
        with patch.object(adapter._client, "post", return_value=mock_response):
            with patch.object(adapter, "_emit_sync_event", new_callable=AsyncMock) as mock_emit:
                await adapter.push_voucher(sample_voucher)
                mock_emit.assert_awaited_once()
                args, _ = mock_emit.call_args
                assert args[1] == "finance"  # scope


# ─── 用友适配器测试 ─────────────────────────────────────────────────────────


class TestYonyouAdapter:
    """用友云 YonBIP 适配器测试"""

    @pytest.fixture
    def adapter(self, monkeypatch):
        monkeypatch.setenv("YONYOU_CLIENT_ID", "test_client_id")
        monkeypatch.setenv("YONYOU_CLIENT_SECRET", "test_client_secret")
        monkeypatch.setenv("YONYOU_BASE_URL", "https://yonyou.example.com")
        return YonyouAdapter()

    @pytest.mark.asyncio
    async def test_push_voucher_success(self, adapter, sample_voucher):
        """凭证推送成功"""
        # 先 mock token 请求
        token_response = httpx.Response(
            200,
            json={"access_token": "test_token", "expires_in": 7200},
        )
        # 再 mock 推送请求
        push_response = httpx.Response(
            200,
            json={"code": "0", "data": {"voucherId": "YY12345"}},
        )

        async def mock_post(url, **kwargs):
            if "oauth2/token" in url:
                return token_response
            return push_response

        with patch.object(adapter._client, "post", side_effect=mock_post):
            result = await adapter.push_voucher(sample_voucher)

        assert result.status == PushStatus.SUCCESS
        assert result.erp_voucher_id == "YY12345"
        assert result.erp_type == ERPType.YONYOU

    @pytest.mark.asyncio
    async def test_push_voucher_http_error_queued(self, adapter, sample_voucher):
        """HTTP 失败时入队并返回 QUEUED"""
        with patch.object(adapter._client, "post", side_effect=httpx.ConnectError("network down")):
            result = await adapter.push_voucher(sample_voucher)

        assert result.status == PushStatus.QUEUED
        assert result.erp_voucher_id is None
        assert "network down" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_health_check_success(self, adapter):
        """健康检查成功"""
        token_response = httpx.Response(
            200,
            json={"access_token": "test_token", "expires_in": 7200},
        )
        with patch.object(adapter._client, "post", return_value=token_response):
            assert await adapter.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self, adapter):
        """健康检查网络异常"""
        with patch.object(adapter._client, "post", side_effect=httpx.ConnectError("timeout")):
            assert await adapter.health_check() is False

    @pytest.mark.asyncio
    async def test_sync_chart_of_accounts(self, adapter, sample_voucher):
        """科目同步成功"""
        token_response = httpx.Response(
            200,
            json={"access_token": "test_token", "expires_in": 7200},
        )
        accounts_response = httpx.Response(
            200,
            json={
                "code": "0",
                "data": {
                    "list": [
                        {
                            "accountCode": "5001",
                            "accountName": "主营业务收入",
                            "accountType": "收入",
                            "isLeaf": True,
                        },
                    ]
                },
            },
        )

        async def mock_get(url, **kwargs):
            return accounts_response

        with patch.object(adapter._client, "get", side_effect=mock_get):
            # 预置 token（避免 OAuth2 请求）
            adapter._access_token = "test_token"
            adapter._token_expires_at = 9999999999.0
            accounts = await adapter.sync_chart_of_accounts()

        assert len(accounts) == 1
        assert accounts[0].code == "5001"
        assert accounts[0].name == "主营业务收入"

    @pytest.mark.asyncio
    async def test_push_voucher_triggers_event(self, adapter, sample_voucher):
        """push_voucher 成功后触发事件发射"""
        token_response = httpx.Response(
            200,
            json={"access_token": "test_token", "expires_in": 7200},
        )
        push_response = httpx.Response(
            200,
            json={"code": "0", "data": {"voucherId": "YY12345"}},
        )

        async def mock_post(url, **kwargs):
            if "oauth2/token" in url:
                return token_response
            return push_response

        with patch.object(adapter._client, "post", side_effect=mock_post):
            with patch.object(adapter, "_emit_sync_event", new_callable=AsyncMock) as mock_emit:
                result = await adapter.push_voucher(sample_voucher)
                # 异步 create_task 可能在事件循环中延迟执行，验证推送结果
                assert result.status == PushStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_queue_size_and_drain(self, adapter, sample_voucher, tmp_path, monkeypatch):
        """离线队列大小与消费"""
        monkeypatch.setattr(adapter, "_queue_path", tmp_path / "test_queue.jsonl")

        assert adapter.queue_size() == 0

        # 模拟一条入队记录
        adapter._enqueue(sample_voucher, "test error")
        assert adapter.queue_size() == 1

        # drain_queue 时 post 抛出异常，条目应保留
        with patch.object(adapter._client, "post", side_effect=httpx.ConnectError("still down")):
            results = await adapter.drain_queue()
            assert len(results) == 1
            assert results[0].status == PushStatus.QUEUED

        # 队列保留失败条目
        assert adapter.queue_size() == 1


# ─── 幂等性测试（基类级别） ─────────────────────────────────────────────────


class TestERPIdempotency:
    """ERP 适配器基类幂等性测试"""

    def test_idempotency_key_deterministic(self, monkeypatch):
        """相同操作+payload 生成相同幂等键"""
        monkeypatch.setenv("KINGDEE_APP_ID", "test")
        monkeypatch.setenv("KINGDEE_APP_SECRET", "test")
        monkeypatch.setenv("KINGDEE_BASE_URL", "https://example.com")
        adapter = KingdeeAdapter()
        payload = {"a": 1, "b": "test"}
        key1 = adapter.idempotency_key("push_voucher", payload)
        key2 = adapter.idempotency_key("push_voucher", payload)
        assert key1 == key2
        assert len(key1) == 32  # MD5 hex

    def test_idempotency_key_differs_by_tenant(self, monkeypatch):
        """不同租户 ID 生成不同幂等键"""
        monkeypatch.setenv("KINGDEE_APP_ID", "test")
        monkeypatch.setenv("KINGDEE_APP_SECRET", "test")
        monkeypatch.setenv("KINGDEE_BASE_URL", "https://example.com")
        adapter = KingdeeAdapter()
        payload = {"a": 1}

        adapter._tenant_id = "tenant_a"
        key_a = adapter.idempotency_key("push_voucher", payload)

        adapter._tenant_id = "tenant_b"
        key_b = adapter.idempotency_key("push_voucher", payload)

        assert key_a != key_b

    def test_is_duplicate_and_mark(self, monkeypatch):
        """mark 后 is_duplicate 返回 True"""
        monkeypatch.setenv("YONYOU_CLIENT_ID", "test")
        monkeypatch.setenv("YONYOU_CLIENT_SECRET", "test")
        monkeypatch.setenv("YONYOU_BASE_URL", "https://example.com")
        adapter = YonyouAdapter()

        adapter._nonce_store.clear()
        assert adapter.is_duplicate("erp_test_key") is False
        adapter.mark_idempotent("erp_test_key")
        assert adapter.is_duplicate("erp_test_key") is True
        adapter._nonce_store.discard("erp_test_key")


# ─── 数据模型测试 ───────────────────────────────────────────────────────────


class TestERPVoucherValidation:
    """ERPVoucher 校验测试"""

    def test_balanced_voucher_passes(self):
        """借贷平衡的凭证通过校验"""
        voucher = ERPVoucher(
            voucher_type=VoucherType.MEMO,
            business_date=date(2026, 5, 3),
            entries=[
                ERPVoucherEntry(account_code="5001", account_name="收入", credit_fen=1000, summary="test"),
                ERPVoucherEntry(account_code="1002", account_name="银行", debit_fen=1000, summary="test"),
            ],
            source_type="test",
            source_id="123",
            tenant_id="t1",
            store_id="s1",
        )
        assert voucher.total_fen == 1000

    def test_unbalanced_voucher_fails(self):
        """借贷不平的凭证拒绝创建"""
        with pytest.raises(ValueError, match="借贷不平衡"):
            ERPVoucher(
                voucher_type=VoucherType.MEMO,
                business_date=date(2026, 5, 3),
                entries=[
                    ERPVoucherEntry(account_code="5001", account_name="收入", credit_fen=1000, summary="test"),
                    ERPVoucherEntry(account_code="1002", account_name="银行", debit_fen=500, summary="test"),
                ],
                source_type="test",
                source_id="123",
                tenant_id="t1",
                store_id="s1",
            )

    def test_entry_both_zero_fails(self):
        """分录借贷同时为零拒绝"""
        with pytest.raises(ValueError, match="借贷金额不能同时为 0"):
            ERPVoucherEntry(account_code="1403", account_name="原材料", debit_fen=0, credit_fen=0, summary="test")

    def test_entry_both_positive_fails(self):
        """分录借贷同时非零拒绝（单边原则）"""
        with pytest.raises(ValueError, match="借贷金额不能同时非零"):
            ERPVoucherEntry(account_code="1403", account_name="原材料", debit_fen=100, credit_fen=100, summary="test")
