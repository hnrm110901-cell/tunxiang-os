"""VoucherGenerator + ERP 适配器 单元测试

测试覆盖：
1. 采购凭证借贷平衡验证
2. 日收入凭证按支付方式生成多借方分录
3. 用友适配器离线缓冲（推送失败 → 写队列）
4. 队列 drain 重试（成功后条目从队列移除）
5. 科目映射租户覆盖（tenant_config 优先）
6. ERPVoucher 借贷不平衡时 Pydantic 抛出 ValueError
7. 工厂函数对不支持类型的处理
"""
from __future__ import annotations

import json
import os
import pathlib

# ─── 模块路径适配（无需安装，直接 sys.path 注入）────────────────────────────────
import sys
import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

_REPO = pathlib.Path(__file__).parents[3]  # tunxiang-os/
sys.path.insert(0, str(_REPO / "services/tx-finance/src"))
sys.path.insert(0, str(_REPO))

from shared.adapters.erp.src.base import (
    ERPType,
    ERPVoucher,
    ERPVoucherEntry,
    PushStatus,
    VoucherType,
)
from shared.adapters.erp.src.factory import get_erp_adapter

# ─── 工具函数 ─────────────────────────────────────────────────────────────────


def _make_purchase_voucher(
    total_fen: int = 10000,
    tenant_id: str | None = None,
    store_id: str | None = None,
) -> ERPVoucher:
    """构造一张采购入库凭证（借贷平衡）"""
    t = tenant_id or str(uuid.uuid4())
    s = store_id or str(uuid.uuid4())
    return ERPVoucher(
        voucher_type=VoucherType.MEMO,
        business_date=date(2026, 3, 31),
        entries=[
            ERPVoucherEntry(
                account_code="1403",
                account_name="原材料",
                debit_fen=total_fen,
                summary="采购入库-某供应商-PO2026001",
            ),
            ERPVoucherEntry(
                account_code="2202",
                account_name="应付账款",
                credit_fen=total_fen,
                summary="应付-某供应商-PO2026001",
            ),
        ],
        source_type="purchase_order",
        source_id=str(uuid.uuid4()),
        tenant_id=t,
        store_id=s,
    )


def _make_daily_revenue_voucher(tenant_id: str | None = None) -> ERPVoucher:
    """构造一张日收入凭证（3 种支付方式 → 1 条主营业务收入）"""
    t = tenant_id or str(uuid.uuid4())
    s = str(uuid.uuid4())
    return ERPVoucher(
        voucher_type=VoucherType.RECEIPT,
        business_date=date(2026, 3, 31),
        entries=[
            ERPVoucherEntry(
                account_code="1001",
                account_name="库存现金",
                debit_fen=3000,
                summary="2026-03-31现金收入(10笔)",
            ),
            ERPVoucherEntry(
                account_code="1012.01",
                account_name="微信收款",
                debit_fen=5000,
                summary="2026-03-31微信收入(20笔)",
            ),
            ERPVoucherEntry(
                account_code="1012.02",
                account_name="支付宝收款",
                debit_fen=2000,
                summary="2026-03-31支付宝收入(8笔)",
            ),
            ERPVoucherEntry(
                account_code="5001",
                account_name="主营业务收入",
                credit_fen=10000,
                summary="2026-03-31营业收入合计",
            ),
        ],
        source_type="daily_revenue",
        source_id=f"{s}_2026-03-31",
        tenant_id=t,
        store_id=s,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  1. ERPVoucher 模型验证
# ═══════════════════════════════════════════════════════════════════════════════


class TestERPVoucherModel:
    """Pydantic 模型层校验"""

    def test_balanced_purchase_voucher_ok(self) -> None:
        """采购凭证借贷平衡，构造不抛异常"""
        v = _make_purchase_voucher(10000)
        assert v.total_fen == 10000
        assert v.total_yuan == pytest.approx(100.0)

    def test_unbalanced_voucher_raises_value_error(self) -> None:
        """借贷不平衡时 ERPVoucher 构造抛出 ValueError"""
        with pytest.raises(ValueError, match="借贷不平衡"):
            ERPVoucher(
                voucher_type=VoucherType.MEMO,
                business_date=date(2026, 3, 31),
                entries=[
                    ERPVoucherEntry(
                        account_code="1403",
                        account_name="原材料",
                        debit_fen=10000,
                        summary="借方",
                    ),
                    ERPVoucherEntry(
                        account_code="2202",
                        account_name="应付账款",
                        credit_fen=9999,  # 故意差 1 分
                        summary="贷方",
                    ),
                ],
                source_type="test",
                source_id="x",
                tenant_id=str(uuid.uuid4()),
                store_id=str(uuid.uuid4()),
            )

    def test_entry_both_zero_raises_value_error(self) -> None:
        """分录借贷同时为 0 时抛出 ValueError"""
        with pytest.raises(ValueError, match="同时为 0"):
            ERPVoucherEntry(
                account_code="1403",
                account_name="原材料",
                debit_fen=0,
                credit_fen=0,
                summary="错误分录",
            )

    def test_entry_both_nonzero_raises_value_error(self) -> None:
        """分录借贷同时非零时抛出 ValueError（单边原则）"""
        with pytest.raises(ValueError, match="同时非零"):
            ERPVoucherEntry(
                account_code="1403",
                account_name="原材料",
                debit_fen=100,
                credit_fen=100,
                summary="违反单边原则",
            )

    def test_daily_revenue_balanced(self) -> None:
        """日收入凭证借贷平衡（3 借 1 贷）"""
        v = _make_daily_revenue_voucher()
        debit_sum = sum(e.debit_fen for e in v.entries)
        credit_sum = sum(e.credit_fen for e in v.entries)
        assert debit_sum == credit_sum == 10000
        assert len(v.entries) == 4  # 3 种支付方式 + 1 贷方


# ═══════════════════════════════════════════════════════════════════════════════
#  2. 工厂函数
# ═══════════════════════════════════════════════════════════════════════════════


class TestERPAdapterFactory:
    """get_erp_adapter 工厂函数"""

    def test_unsupported_type_raises_value_error(self) -> None:
        """不支持的 ERP 类型抛出 ValueError"""
        with pytest.raises(ValueError, match="不支持的 ERP 类型"):
            get_erp_adapter("sap")

    def test_kingdee_instantiation_without_env_raises_key_error(self) -> None:
        """缺少环境变量时金蝶适配器构造抛出 KeyError"""
        # 清理环境变量
        for key in ("KINGDEE_APP_ID", "KINGDEE_APP_SECRET", "KINGDEE_BASE_URL"):
            os.environ.pop(key, None)
        with pytest.raises(KeyError):
            get_erp_adapter("kingdee")

    def test_yonyou_instantiation_without_env_raises_key_error(self) -> None:
        """缺少环境变量时用友适配器构造抛出 KeyError"""
        for key in ("YONYOU_CLIENT_ID", "YONYOU_CLIENT_SECRET", "YONYOU_BASE_URL"):
            os.environ.pop(key, None)
        with pytest.raises(KeyError):
            get_erp_adapter("yonyou")


# ═══════════════════════════════════════════════════════════════════════════════
#  3. 金蝶适配器
# ═══════════════════════════════════════════════════════════════════════════════


class TestKingdeeAdapter:
    """金蝶适配器单元测试（Mock HTTP）"""

    @pytest.fixture(autouse=True)
    def set_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KINGDEE_APP_ID", "test_app_id")
        monkeypatch.setenv("KINGDEE_APP_SECRET", "test_app_secret")
        monkeypatch.setenv("KINGDEE_BASE_URL", "https://mock.kingdee.example.com")

    @pytest.fixture()
    def adapter(self):
        from shared.adapters.erp.src.kingdee_adapter import KingdeeAdapter
        a = KingdeeAdapter()
        yield a

    def test_sign_deterministic(self, adapter) -> None:
        """相同输入生成相同签名（确定性）"""
        s1 = adapter._sign("1000", "abc123", '{"test":1}')
        s2 = adapter._sign("1000", "abc123", '{"test":1}')
        assert s1 == s2
        assert len(s1) == 64  # SHA256 hex 64 chars

    def test_sign_different_input(self, adapter) -> None:
        """不同输入生成不同签名"""
        s1 = adapter._sign("1000", "abc123", '{"test":1}')
        s2 = adapter._sign("1001", "abc123", '{"test":1}')
        assert s1 != s2

    @pytest.mark.asyncio
    async def test_push_voucher_success(self, adapter) -> None:
        """推送成功时返回 SUCCESS 状态"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "Result": {"Result": True, "Id": "KD-2026-001"},
        }
        adapter._client.post = AsyncMock(return_value=mock_response)

        voucher = _make_purchase_voucher(10000)
        result = await adapter.push_voucher(voucher)

        assert result.status == PushStatus.SUCCESS
        assert result.erp_type == ERPType.KINGDEE
        assert result.erp_voucher_id == "KD-2026-001"

    @pytest.mark.asyncio
    async def test_push_voucher_business_error_raises(self, adapter) -> None:
        """ERP 业务错误时抛出 RuntimeError"""

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "Result": {"Result": False, "Message": "科目编码不存在"},
        }
        adapter._client.post = AsyncMock(return_value=mock_response)

        voucher = _make_purchase_voucher(10000)
        with pytest.raises(RuntimeError, match="科目编码不存在"):
            await adapter.push_voucher(voucher)

    @pytest.mark.asyncio
    async def test_health_check_returns_true_on_2xx(self, adapter) -> None:
        """HTTP 2xx 时 health_check 返回 True"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        adapter._client.head = AsyncMock(return_value=mock_response)

        ok = await adapter.health_check()
        assert ok is True

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_http_error(self, adapter) -> None:
        """网络错误时 health_check 返回 False（不抛异常）"""
        import httpx

        adapter._client.head = AsyncMock(
            side_effect=httpx.ConnectError("connection refused")
        )
        ok = await adapter.health_check()
        assert ok is False

    @pytest.mark.asyncio
    async def test_sync_chart_of_accounts_fallback(self, adapter) -> None:
        """HTTP 错误时降级返回内置默认科目表"""
        import httpx

        adapter._client.get = AsyncMock(
            side_effect=httpx.ConnectError("no route to host")
        )
        accounts = await adapter.sync_chart_of_accounts()
        assert len(accounts) > 0
        codes = [a.code for a in accounts]
        assert "1403" in codes  # 原材料必须在默认科目表中


# ═══════════════════════════════════════════════════════════════════════════════
#  4. 用友适配器 — 离线缓冲
# ═══════════════════════════════════════════════════════════════════════════════


class TestYonyouAdapterOfflineBuffer:
    """用友适配器离线缓冲机制测试"""

    @pytest.fixture(autouse=True)
    def set_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
        monkeypatch.setenv("YONYOU_CLIENT_ID", "test_client_id")
        monkeypatch.setenv("YONYOU_CLIENT_SECRET", "test_secret")
        monkeypatch.setenv("YONYOU_BASE_URL", "https://mock.yonbip.example.com")
        queue_file = tmp_path / "test_queue.jsonl"
        monkeypatch.setenv("YONYOU_QUEUE_PATH", str(queue_file))
        self._queue_file = queue_file

    @pytest.fixture()
    def adapter(self):
        from shared.adapters.erp.src.yonyou_adapter import YonyouAdapter
        return YonyouAdapter()

    @pytest.mark.asyncio
    async def test_push_failure_writes_to_queue(self, adapter) -> None:
        """HTTP 错误时凭证写入离线队列，返回 QUEUED 状态"""
        import httpx

        # Mock token 获取和推送均失败
        adapter._client.post = AsyncMock(
            side_effect=httpx.ConnectError("connection refused")
        )
        voucher = _make_purchase_voucher(5000)
        result = await adapter.push_voucher(voucher)

        assert result.status == PushStatus.QUEUED
        assert result.erp_voucher_id is None
        assert result.error_message is not None

        # 验证队列文件被写入
        assert self._queue_file.exists()
        lines = [l for l in self._queue_file.read_text().splitlines() if l.strip()]
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["voucher"]["voucher_id"] == voucher.voucher_id

    @pytest.mark.asyncio
    async def test_queue_size_reflects_entries(self, adapter) -> None:
        """queue_size 正确反映队列条目数"""
        import httpx

        adapter._client.post = AsyncMock(
            side_effect=httpx.ConnectError("connection refused")
        )
        v1 = _make_purchase_voucher(1000)
        v2 = _make_purchase_voucher(2000)
        await adapter.push_voucher(v1)
        await adapter.push_voucher(v2)

        assert adapter.queue_size() == 2

    @pytest.mark.asyncio
    async def test_drain_queue_success_removes_entries(self, adapter) -> None:
        """drain_queue 成功后队列清空"""
        import httpx

        # 第一次 post（获取 token）抛错 → 入队
        adapter._client.post = AsyncMock(
            side_effect=httpx.ConnectError("connection refused")
        )
        voucher = _make_purchase_voucher(3000)
        await adapter.push_voucher(voucher)
        assert adapter.queue_size() == 1

        # 重试时 mock 成功
        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.raise_for_status = MagicMock()
        token_resp.json.return_value = {"access_token": "tok", "expires_in": 7200}

        push_resp = MagicMock()
        push_resp.status_code = 200
        push_resp.raise_for_status = MagicMock()
        push_resp.json.return_value = {
            "code": "0",
            "data": {"voucherId": "YY-2026-001"},
        }

        call_count = [0]

        async def _side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return token_resp
            return push_resp

        adapter._client.post = AsyncMock(side_effect=_side_effect)
        # 重置 token 缓存
        adapter._access_token = None
        adapter._token_expires_at = 0.0

        results = await adapter.drain_queue()
        assert len(results) == 1
        assert results[0].status == PushStatus.SUCCESS
        # 队列应已清空
        assert adapter.queue_size() == 0

    @pytest.mark.asyncio
    async def test_drain_queue_failed_entries_stay_in_queue(self, adapter) -> None:
        """drain_queue 失败的条目保留在队列中"""
        import httpx

        adapter._client.post = AsyncMock(
            side_effect=httpx.ConnectError("connection refused")
        )
        voucher = _make_purchase_voucher(4000)
        await adapter.push_voucher(voucher)
        assert adapter.queue_size() == 1

        # drain 时仍然失败
        results = await adapter.drain_queue()
        assert len(results) == 0 or all(r.status != PushStatus.SUCCESS for r in results)
        assert adapter.queue_size() == 1  # 失败的留在队列


# ═══════════════════════════════════════════════════════════════════════════════
#  5. 科目映射覆盖测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestAccountMappingOverride:
    """租户科目映射覆盖（tenant_config 优先级）"""

    @pytest.mark.asyncio
    async def test_tenant_override_applied(self) -> None:
        """租户自定义科目映射覆盖默认映射"""
        from services.voucher_generator import VoucherGenerator

        generator = VoucherGenerator()
        tenant_id = str(uuid.uuid4())

        # Mock DB 返回自定义映射
        custom_mapping = {
            "purchase_payment": {
                "debit":  {"code": "9901", "name": "自定义原材料"},
                "credit": {"code": "9902", "name": "自定义应付"},
            }
        }
        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = {
            "config_value": custom_mapping
        }
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mapping = await generator._get_account_mapping(tenant_id, mock_db)
        assert mapping["purchase_payment"]["debit"]["code"] == "9901"
        assert mapping["purchase_payment"]["debit"]["name"] == "自定义原材料"
        # 其他未覆盖的场景保留默认
        assert "sales_revenue" in mapping

    @pytest.mark.asyncio
    async def test_default_mapping_when_no_tenant_config(self) -> None:
        """无租户配置时使用默认科目映射"""
        from services.voucher_generator import ACCOUNT_MAPPING, VoucherGenerator

        generator = VoucherGenerator()
        tenant_id = str(uuid.uuid4())

        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = None
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mapping = await generator._get_account_mapping(tenant_id, mock_db)
        assert mapping == ACCOUNT_MAPPING

    @pytest.mark.asyncio
    async def test_db_error_fallbacks_to_default(self) -> None:
        """DB 读取异常时降级使用默认映射（不阻断凭证生成）"""
        from services.voucher_generator import ACCOUNT_MAPPING, VoucherGenerator

        generator = VoucherGenerator()
        tenant_id = str(uuid.uuid4())

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=RuntimeError("DB connection lost"))

        mapping = await generator._get_account_mapping(tenant_id, mock_db)
        assert mapping == ACCOUNT_MAPPING


# ═══════════════════════════════════════════════════════════════════════════════
#  6. VoucherGenerator 凭证生成（Mock DB）
# ═══════════════════════════════════════════════════════════════════════════════


class TestVoucherGeneratorWithMockDB:
    """凭证生成器集成级测试（Mock 数据库返回）"""

    @pytest.fixture()
    def generator(self):
        from services.voucher_generator import VoucherGenerator
        return VoucherGenerator()

    def _mock_db_for_purchase(self, total_fen: int = 12000):
        """返回 Mock 的 AsyncSession，模拟采购单查询"""
        store_id = uuid.uuid4()
        order_date = date(2026, 3, 31)

        purchase_row = {
            "id": uuid.uuid4(),
            "store_id": store_id,
            "order_no": "PO2026001",
            "total_amount_fen": total_fen,
            "order_date": order_date,
            "supplier_name": "鲜蔬供应商",
            "status": "confirmed",
        }
        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = purchase_row

        # tenant_config 查询返回 None（使用默认映射）
        config_result = MagicMock()
        config_result.mappings.return_value.first.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[config_result, mock_result])
        return mock_db

    @pytest.mark.asyncio
    async def test_purchase_voucher_is_balanced(self, generator) -> None:
        """采购凭证借贷必须平衡"""
        db = self._mock_db_for_purchase(12000)
        # 因为 _get_account_mapping 先查 DB，再查采购单，需要两次 execute
        # 调整：让 config 先执行
        tenant_id = str(uuid.uuid4())
        order_id = str(uuid.uuid4())

        store_id = uuid.uuid4()
        purchase_row = {
            "id": uuid.uuid4(),
            "store_id": store_id,
            "order_no": "PO2026001",
            "total_amount_fen": 12000,
            "order_date": date(2026, 3, 31),
            "supplier_name": "鲜蔬供应商",
            "status": "confirmed",
        }
        config_result = MagicMock()
        config_result.mappings.return_value.first.return_value = None
        order_result = MagicMock()
        order_result.mappings.return_value.first.return_value = purchase_row

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[config_result, order_result])

        voucher = await generator.generate_from_purchase_order(order_id, tenant_id, mock_db)

        total_debit = sum(e.debit_fen for e in voucher.entries)
        total_credit = sum(e.credit_fen for e in voucher.entries)
        assert total_debit == total_credit == 12000
        assert voucher.source_type == "purchase_order"

    @pytest.mark.asyncio
    async def test_purchase_zero_amount_raises(self, generator) -> None:
        """采购单金额为 0 时抛出 ValueError"""
        tenant_id = str(uuid.uuid4())
        order_id = str(uuid.uuid4())
        store_id = uuid.uuid4()

        purchase_row = {
            "id": uuid.uuid4(),
            "store_id": store_id,
            "order_no": "PO2026002",
            "total_amount_fen": 0,
            "order_date": date(2026, 3, 31),
            "supplier_name": "测试供应商",
            "status": "confirmed",
        }
        config_result = MagicMock()
        config_result.mappings.return_value.first.return_value = None
        order_result = MagicMock()
        order_result.mappings.return_value.first.return_value = purchase_row

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[config_result, order_result])

        with pytest.raises(ValueError, match="金额为 0"):
            await generator.generate_from_purchase_order(order_id, tenant_id, mock_db)

    @pytest.mark.asyncio
    async def test_purchase_not_found_raises(self, generator) -> None:
        """采购单不存在时抛出 ValueError"""
        tenant_id = str(uuid.uuid4())
        order_id = str(uuid.uuid4())

        config_result = MagicMock()
        config_result.mappings.return_value.first.return_value = None
        order_result = MagicMock()
        order_result.mappings.return_value.first.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[config_result, order_result])

        with pytest.raises(ValueError, match="不存在或无权限"):
            await generator.generate_from_purchase_order(order_id, tenant_id, mock_db)

    @pytest.mark.asyncio
    async def test_daily_revenue_multi_payment_balanced(self, generator) -> None:
        """日收入凭证：多种支付方式借方合计 = 收入贷方"""
        tenant_id = str(uuid.uuid4())
        store_id = str(uuid.uuid4())

        payment_rows = [
            {"pay_method": "cash",    "amount_fen": 2000, "pay_count": 5},
            {"pay_method": "wechat",  "amount_fen": 6000, "pay_count": 15},
            {"pay_method": "alipay",  "amount_fen": 2000, "pay_count": 8},
        ]

        config_result = MagicMock()
        config_result.mappings.return_value.first.return_value = None
        rev_result = MagicMock()
        rev_result.mappings.return_value.all.return_value = payment_rows

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[config_result, rev_result])

        voucher = await generator.generate_from_daily_revenue(
            store_id=store_id,
            business_date=date(2026, 3, 31),
            tenant_id=tenant_id,
            db=mock_db,
        )

        total_debit = sum(e.debit_fen for e in voucher.entries)
        total_credit = sum(e.credit_fen for e in voucher.entries)
        assert total_debit == total_credit == 10000
        # 3 种支付 + 1 贷方
        assert len(voucher.entries) == 4
        assert voucher.voucher_type == VoucherType.RECEIPT

    @pytest.mark.asyncio
    async def test_daily_revenue_no_data_raises(self, generator) -> None:
        """当日无收入数据时抛出 ValueError"""
        tenant_id = str(uuid.uuid4())
        store_id = str(uuid.uuid4())

        config_result = MagicMock()
        config_result.mappings.return_value.first.return_value = None
        rev_result = MagicMock()
        rev_result.mappings.return_value.all.return_value = []

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[config_result, rev_result])

        with pytest.raises(ValueError, match="无收入数据"):
            await generator.generate_from_daily_revenue(
                store_id=store_id,
                business_date=date(2026, 3, 31),
                tenant_id=tenant_id,
                db=mock_db,
            )
