"""Tier 1 三段事务测试：invoice_service.get_invoice_status 持锁调诺诺 HTTP 拆三段

关联：
  - Issue #543 (本 PR 闭环)
  - PR #544 PR-A §19 reviewer P1 follow-up
  - CLAUDE.md § 17 invoice_service.py 在 Tier 1 资金路径 (全电发票/金税四期)
  - docs/security/tier1-row-lock-audit-2026-05.md §4.2 (invoice_service 加锁路径)

业务影响：
  - 拆分前：get_invoice_status 全程持锁调诺诺 HTTP（5-30 秒），并发 cancel_invoice /
    retry_failed 路径被阻塞，200 桌高峰期前台多路轮询可能把 invoice 行锁占满 →
    cancel_invoice 排队等待诺诺超时.
  - 拆分后：Step 1 无锁读 → Step 2 诺诺 HTTP (锁外) → Step 3 短事务加锁写回
    (再校验 status 防覆盖).

测试策略：mock-only（不 import Invoice ORM 模型，避免同目录 test_invoice_fen_tier1.py
bare-NS `from models.invoice` 与 FQN 路径双注册 SQLAlchemy MetaData，
memory `feedback_pytest_stub_setdefault_pitfall.md` 实例 #1/#2 教训）.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
FINANCE_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
for p in [ROOT, FINANCE_SRC]:
    if p not in sys.path:
        sys.path.insert(0, p)


TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
INVOICE_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


def _make_invoice_mock(
    *,
    status: str = "pending",
    platform_request_id: str | None = "NN-2026-001",
    invoice_no: str = "",
    invoice_code: str = "",
    pdf_url: str = "",
    failed_reason: str | None = None,
    issued_at: datetime | None = None,
) -> MagicMock:
    """构造 Invoice 行的 MagicMock（不依赖 ORM 真实模型）."""
    inv = MagicMock()
    inv.id = INVOICE_ID
    inv.tenant_id = TENANT_ID
    inv.status = status
    inv.platform_request_id = platform_request_id
    inv.invoice_no = invoice_no
    inv.invoice_code = invoice_code
    inv.pdf_url = pdf_url
    inv.failed_reason = failed_reason
    inv.issued_at = issued_at
    inv.amount_fen = 10000
    inv.tax_fen = 1300
    inv.amount_yuan_str = "100.00"
    inv.tax_yuan_str = "13.00"
    return inv


def _make_nuonuo_resp(*, success: bool, items: list[dict] | None = None) -> MagicMock:
    """构造诺诺 NuoNuoResponse mock."""
    resp = MagicMock()
    resp.success = success
    resp.data = {"invoiceQueryResultList": items or []}
    resp.error_msg = "" if success else "mock error"
    return resp


def _make_service_with_mocks(invoice_seq: list[MagicMock], nuonuo_resp: MagicMock):
    """构造 InvoiceService 实例，注入 _get_invoice 顺序返回 + _client mock.

    invoice_seq: 顺序返回的 invoice mock 列表（每次 _get_invoice 调用按 index 取）
    nuonuo_resp: _client.query_invoice 返回值.
    """
    from services.tx_finance.src.services.invoice_service import InvoiceService

    svc = InvoiceService(nuonuo_client=AsyncMock())
    svc._client.query_invoice = AsyncMock(return_value=nuonuo_resp)

    call_log: list[dict] = []

    async def _get_invoice_mock(invoice_id, tenant_id, db, *, lock: bool = False):
        call_log.append({"lock": lock})
        idx = len(call_log) - 1
        if idx >= len(invoice_seq):
            raise AssertionError(
                f"_get_invoice 调用第 {idx + 1} 次，但 invoice_seq 只准备了 {len(invoice_seq)} 个"
            )
        return invoice_seq[idx]

    svc._get_invoice = _get_invoice_mock  # type: ignore[method-assign]
    return svc, call_log


class TestGetInvoiceStatusThreePhaseTier1:
    """invoice_service.get_invoice_status 拆三段事务 — Tier 1 全电发票路径

    三段语义（issue #543）：
      Step 1: lock=False 读判断 (非 pending / 无 platform_request_id → 直接 return)
      Step 2: 诺诺 query_invoice HTTP (锁外，5-30s 不阻塞其他 mutation)
      Step 3: lock=True 短事务写回 (再校验 status 仍为 pending 防覆盖)
    """

    @pytest.mark.asyncio
    async def test_step1_non_pending_short_circuit_no_lock_no_http(self):
        """非 pending 状态 → 一次无锁读即 return，不调诺诺，不二次加锁.

        Race 场景：前台轮询 issued 状态的发票，不应触诺诺 HTTP（cost 0 + 不写回）.
        """
        issued_inv = _make_invoice_mock(status="issued", platform_request_id="NN-001")
        svc, call_log = _make_service_with_mocks([issued_inv], _make_nuonuo_resp(success=True))
        db = AsyncMock()

        await svc.get_invoice_status(INVOICE_ID, TENANT_ID, db)

        assert len(call_log) == 1, f"非 pending 只应 _get_invoice 一次，实际 {len(call_log)}"
        assert call_log[0]["lock"] is False, "Step 1 必须 lock=False（无锁读判断）"
        svc._client.query_invoice.assert_not_awaited()
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_step1_no_platform_request_id_short_circuit(self):
        """pending 但无 platform_request_id（诺诺未受理）→ 不调 HTTP."""
        no_pid_inv = _make_invoice_mock(status="pending", platform_request_id=None)
        svc, call_log = _make_service_with_mocks([no_pid_inv], _make_nuonuo_resp(success=True))
        db = AsyncMock()

        await svc.get_invoice_status(INVOICE_ID, TENANT_ID, db)

        assert len(call_log) == 1
        assert call_log[0]["lock"] is False
        svc._client.query_invoice.assert_not_awaited()
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_step2_http_called_after_unlocked_read(self):
        """pending → Step 2 诺诺 HTTP 在 lock=False 读之后调，调用前未触发 lock=True.

        Issue #543 核心断言：诺诺 HTTP 期间不持锁（call order 验证）.
        """
        pending_inv = _make_invoice_mock(status="pending")
        # 诺诺返回开票中 status="0"，不触发 Step 3 写回
        resp = _make_nuonuo_resp(success=True, items=[{"status": "0"}])
        svc, call_log = _make_service_with_mocks([pending_inv], resp)
        db = AsyncMock()

        await svc.get_invoice_status(INVOICE_ID, TENANT_ID, db)

        # Step 1 lock=False 读完成，Step 2 query_invoice 调用一次
        assert len(call_log) == 1, "诺诺非终态时，Step 3 不进 → 只一次 _get_invoice"
        assert call_log[0]["lock"] is False, "诺诺 HTTP 调用前不应加锁"
        svc._client.query_invoice.assert_awaited_once_with("NN-2026-001")
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_step3_writeback_with_lock_on_status_issued(self):
        """诺诺 status='1' → Step 3 二次 lock=True 加锁写回 issued + commit."""
        pending_inv_step1 = _make_invoice_mock(status="pending")
        pending_inv_step3 = _make_invoice_mock(status="pending")
        resp = _make_nuonuo_resp(
            success=True,
            items=[
                {
                    "status": "1",
                    "invoiceNo": "12345678",
                    "invoiceCode": "044001",
                    "pdfUrl": "https://nuonuo.example/pdf/abc.pdf",
                }
            ],
        )
        svc, call_log = _make_service_with_mocks(
            [pending_inv_step1, pending_inv_step3], resp
        )
        db = AsyncMock()

        await svc.get_invoice_status(INVOICE_ID, TENANT_ID, db)

        assert len(call_log) == 2, "Step 3 触发需 2 次 _get_invoice (lock=False → lock=True)"
        assert call_log[0]["lock"] is False, "Step 1 必须 lock=False"
        assert call_log[1]["lock"] is True, "Step 3 必须 lock=True"
        assert pending_inv_step3.status == "issued"
        assert pending_inv_step3.invoice_no == "12345678"
        assert pending_inv_step3.invoice_code == "044001"
        assert pending_inv_step3.pdf_url == "https://nuonuo.example/pdf/abc.pdf"
        assert pending_inv_step3.issued_at is not None
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once_with(pending_inv_step3)

    @pytest.mark.asyncio
    async def test_step3_writeback_on_status_failed(self):
        """诺诺 status='2' → Step 3 写回 failed + 记录 failCause."""
        pending_inv_step1 = _make_invoice_mock(status="pending")
        pending_inv_step3 = _make_invoice_mock(status="pending")
        resp = _make_nuonuo_resp(
            success=True,
            items=[{"status": "2", "failCause": "税号校验失败"}],
        )
        svc, call_log = _make_service_with_mocks(
            [pending_inv_step1, pending_inv_step3], resp
        )
        db = AsyncMock()

        await svc.get_invoice_status(INVOICE_ID, TENANT_ID, db)

        assert call_log[1]["lock"] is True
        assert pending_inv_step3.status == "failed"
        assert pending_inv_step3.failed_reason == "税号校验失败"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_step3_race_protection_concurrent_finalization_no_overwrite(self):
        """中间被改：Step 1 读到 pending，诺诺返回 '1'，但 Step 3 加锁后发现已是 issued.

        Race 场景：本路径 query_invoice 期间，另一路径（retry_failed / 同时另一查询）
        已先写入终态。Step 3 再校验 status 防覆盖。
        """
        pending_inv_step1 = _make_invoice_mock(status="pending")
        # Step 3 加锁读时，invoice 已被并发路径写入 issued
        issued_inv_step3 = _make_invoice_mock(
            status="issued",
            invoice_no="99999999",  # 另一路径写入的发票号，本路径不应覆盖
            invoice_code="999999",
        )
        resp = _make_nuonuo_resp(
            success=True,
            items=[
                {
                    "status": "1",
                    "invoiceNo": "12345678",  # 本路径诺诺响应（应被丢弃）
                    "invoiceCode": "044001",
                    "pdfUrl": "https://nuonuo.example/pdf/abc.pdf",
                }
            ],
        )
        svc, call_log = _make_service_with_mocks(
            [pending_inv_step1, issued_inv_step3], resp
        )
        db = AsyncMock()

        await svc.get_invoice_status(INVOICE_ID, TENANT_ID, db)

        assert len(call_log) == 2
        # Step 3 加锁后发现已 issued → 不覆盖
        assert issued_inv_step3.invoice_no == "99999999", (
            "Race 场景：本路径不能覆盖另一路径已写入的 invoice_no"
        )
        assert issued_inv_step3.invoice_code == "999999"
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_step2_http_failure_no_writeback(self):
        """诺诺 HTTP 失败（success=False）→ Step 3 不进，不二次加锁，不 commit."""
        pending_inv = _make_invoice_mock(status="pending")
        resp = _make_nuonuo_resp(success=False)
        svc, call_log = _make_service_with_mocks([pending_inv], resp)
        db = AsyncMock()

        await svc.get_invoice_status(INVOICE_ID, TENANT_ID, db)

        assert len(call_log) == 1
        assert call_log[0]["lock"] is False
        svc._client.query_invoice.assert_awaited_once()
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_step2_empty_items_no_writeback(self):
        """诺诺 success=True 但 invoiceQueryResultList 空 → Step 3 不进."""
        pending_inv = _make_invoice_mock(status="pending")
        resp = _make_nuonuo_resp(success=True, items=[])
        svc, call_log = _make_service_with_mocks([pending_inv], resp)
        db = AsyncMock()

        await svc.get_invoice_status(INVOICE_ID, TENANT_ID, db)

        assert len(call_log) == 1
        db.commit.assert_not_called()
