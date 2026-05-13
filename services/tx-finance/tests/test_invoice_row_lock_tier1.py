"""Tier 1 行锁测试：invoice_service 4 mutation 路径必须 with_for_update

关联：
  - docs/security/tier1-row-lock-audit-2026-05.md §4.2 (tx-finance invoice 4 路径全裸)
  - PR #538 (audit doc), Issue #532 (audit parent), PR-A of 6-PR fix roadmap
  - 修复参考范本：services/tx-member/tests/test_stored_value.py:243 (with_for_update 验证模式)

业务影响（audit doc §4.2）：
  - retry_failed (P0)：并发 retry → 诺诺端双重开票（金税四期合规硬错）
  - get_invoice_status (P0)：并发 query → 诺诺回写竞态 → invoice_no 错写
  - reprint (P3)：pdf_url 双写（业务无害，但仍加锁以统一）
  - cancel_invoice (P0)：并发红冲 → 金税四期重复红冲投诉
"""
from __future__ import annotations

import os
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.selectable import Select

# ── 路径 ───────────────────────────────────────────────────────────────────────
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
FINANCE_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
for p in [ROOT, FINANCE_SRC]:
    if p not in sys.path:
        sys.path.insert(0, p)


TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
INVOICE_ID = uuid.uuid4()


def _select_has_for_update(stmt) -> bool:
    """检测 SQLAlchemy Select 编译后 SQL 是否含 FOR UPDATE.

    用 postgresql 方言 compile 而非检查私有属性 `_for_update_arg`，
    更稳定（属性名在 SQLAlchemy 主版本间可能变化）。
    """
    if not isinstance(stmt, Select):
        return False
    try:
        compiled = str(stmt.compile(dialect=postgresql.dialect()))
        return "FOR UPDATE" in compiled.upper()
    except Exception:
        # Fallback：检查私有属性
        return getattr(stmt, "_for_update_arg", None) is not None


def _make_invoice(**kw):
    """构造 Invoice mock。"""
    inv = MagicMock()
    inv.id = kw.get("id", INVOICE_ID)
    inv.tenant_id = kw.get("tenant_id", TENANT_ID)
    inv.status = kw.get("status", "pending")
    inv.amount_fen = kw.get("amount_fen", 8800)
    inv.tax_fen = kw.get("tax_fen", 528)
    inv.invoice_no = kw.get("invoice_no", None)
    inv.invoice_code = kw.get("invoice_code", None)
    inv.invoice_type = kw.get("invoice_type", "electronic")
    inv.invoice_title = kw.get("invoice_title", "徐记海鲜有限公司")
    inv.tax_number = kw.get("tax_number", "91430000XXXXXXXXXX")
    inv.platform_request_id = kw.get("platform_request_id", "TX-ABC1234567890")
    inv.pdf_url = kw.get("pdf_url", None)
    inv.failed_reason = kw.get("failed_reason", None)
    inv.platform = kw.get("platform", "nuonuo")
    inv.order_id = kw.get("order_id", uuid.uuid4())
    inv.issued_at = kw.get("issued_at", None)
    inv.created_at = kw.get("created_at", None)
    return inv


def _mock_nuonuo_response(success=True, data=None, error_msg=""):
    resp = MagicMock()
    resp.success = success
    resp.data = data or {}
    resp.error_msg = error_msg
    return resp


def _build_db_mock(invoice_to_return):
    """构造 AsyncSession mock，capture 所有 execute 的 stmt。"""
    db = AsyncMock()
    captured = []

    async def mock_execute(stmt, *args, **kwargs):
        captured.append(stmt)
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=invoice_to_return)
        return result

    db.execute = mock_execute
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db, captured


class TestInvoiceRowLockTier1:
    """invoice_service.py 4 mutation 路径必须 with_for_update 防止金税四期并发竞态.

    与 services/tx-member/src/services/stored_value_service.py 模式对齐
    （11 处 .with_for_update() 含 2 卡同锁排序防死锁）— 全仓 row-lock 最严谨服务。
    """

    @pytest.mark.asyncio
    async def test_retry_failed_uses_for_update(self):
        """retry_failed 必须 with_for_update — 防止并发触发诺诺端重复开票.

        Race 场景（audit doc §4.2 P0）：
          两路并发 retry 都读到 status='failed' → 都过守卫 →
          都调诺诺 → 诺诺侧双开票（金税四期合规硬错）.
        """
        from services.tx_finance.src.services.invoice_service import InvoiceService

        client = MagicMock()
        client.apply_invoice = AsyncMock(
            return_value=_mock_nuonuo_response(success=True, data={"serialNo": "NN-SN-XYZ"})
        )
        svc = InvoiceService(nuonuo_client=client)
        db, captured = _build_db_mock(_make_invoice(status="failed"))

        await svc.retry_failed(INVOICE_ID, TENANT_ID, db)

        locked = [s for s in captured if _select_has_for_update(s)]
        assert locked, (
            "retry_failed 内 SELECT Invoice 必须 with_for_update — "
            "audit doc §4.2 P0 金税四期重复开票风险（诺诺侧 hard 错）"
        )

    @pytest.mark.asyncio
    async def test_get_invoice_status_uses_for_update(self):
        """get_invoice_status 必须 with_for_update — 防止诺诺回写竞态.

        Race 场景（audit doc §4.2 P0）：
          两路并发 query 同一发票（status=pending）→ 各自拿到诺诺返回 →
          先写者 issued + invoice_no=X，后写者覆盖 invoice_no=Y → invoice_no 错写.
        """
        from services.tx_finance.src.services.invoice_service import InvoiceService

        client = MagicMock()
        client.query_invoice = AsyncMock(
            return_value=_mock_nuonuo_response(
                success=True,
                data={
                    "invoiceQueryResultList": [
                        {
                            "status": "1",
                            "invoiceNo": "12345678",
                            "invoiceCode": "1100002330",
                            "pdfUrl": "https://nuonuo.com/x.pdf",
                        }
                    ]
                },
            )
        )
        svc = InvoiceService(nuonuo_client=client)
        db, captured = _build_db_mock(_make_invoice(status="pending", platform_request_id="NN-PENDING-1"))

        await svc.get_invoice_status(INVOICE_ID, TENANT_ID, db)

        locked = [s for s in captured if _select_has_for_update(s)]
        assert locked, (
            "get_invoice_status 内 SELECT Invoice 必须 with_for_update — "
            "audit doc §4.2 P0 诺诺回写竞态 invoice_no 错写"
        )

    @pytest.mark.asyncio
    async def test_reprint_uses_for_update(self):
        """reprint 必须 with_for_update — 与其他写路径一致.

        即使业务影响 P3（pdf_url 双写无害），仍加锁以简化运维心智模型：
        所有 invoice mutation 路径走同一 helper(_get_invoice, lock=True).
        """
        from services.tx_finance.src.services.invoice_service import InvoiceService

        client = MagicMock()
        client.get_pdf_url = AsyncMock(
            return_value=_mock_nuonuo_response(success=True, data={"pdf_url": "https://new.url"})
        )
        svc = InvoiceService(nuonuo_client=client)
        db, captured = _build_db_mock(
            _make_invoice(status="issued", invoice_no="N", invoice_code="C", pdf_url="old_url")
        )

        await svc.reprint(INVOICE_ID, TENANT_ID, db)

        locked = [s for s in captured if _select_has_for_update(s)]
        assert locked, (
            "reprint 内 SELECT Invoice 必须 with_for_update — "
            "audit doc §4.2 P3 但与其他 mutation 路径一致"
        )

    @pytest.mark.asyncio
    async def test_cancel_invoice_uses_for_update(self):
        """cancel_invoice (红冲) 必须 with_for_update — 防止金税四期重复红冲.

        Race 场景（audit doc §4.2 P0）：
          两路并发 cancel 同一 issued 发票 → 各自调诺诺红冲 →
          双红冲（金税四期投诉 + 财务对账错）.
        """
        from services.tx_finance.src.services.invoice_service import InvoiceService

        client = MagicMock()
        client.red_flush_invoice = AsyncMock(return_value=_mock_nuonuo_response(success=True))
        svc = InvoiceService(nuonuo_client=client)
        db, captured = _build_db_mock(
            _make_invoice(status="issued", invoice_no="N123", invoice_code="C456")
        )

        await svc.cancel_invoice(INVOICE_ID, TENANT_ID, db)

        locked = [s for s in captured if _select_has_for_update(s)]
        assert locked, (
            "cancel_invoice 内 SELECT Invoice 必须 with_for_update — "
            "audit doc §4.2 P0 金税四期重复红冲风险"
        )

    @pytest.mark.asyncio
    async def test_get_invoice_helper_lock_param_default_no_lock(self):
        """_get_invoice helper 默认 lock=False，保留未来 read-only 入口能力.

        本测验证 helper 的 lock 参数语义：默认不加锁，调用方显式 lock=True 才加.
        4 个 mutation 路径都必须显式传 lock=True（前 4 个测试已覆盖）.
        """
        from services.tx_finance.src.services.invoice_service import InvoiceService

        svc = InvoiceService(nuonuo_client=MagicMock())
        db, captured = _build_db_mock(_make_invoice())

        # 默认调用（lock=False）
        await svc._get_invoice(INVOICE_ID, TENANT_ID, db)
        assert captured, "_get_invoice 必须 execute 至少一条 select"
        assert not _select_has_for_update(captured[0]), (
            "_get_invoice 默认 lock=False 时 SELECT 不应含 FOR UPDATE"
        )

        # 显式 lock=True
        captured.clear()
        await svc._get_invoice(INVOICE_ID, TENANT_ID, db, lock=True)
        assert captured, "_get_invoice(lock=True) 必须 execute select"
        assert _select_has_for_update(captured[0]), (
            "_get_invoice(lock=True) SELECT 必须含 FOR UPDATE"
        )
