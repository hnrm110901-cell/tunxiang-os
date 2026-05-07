"""Tier 1 测试 — invoice 模型金额必须用 fen int (CLAUDE.md §15+§17)

关联差距：docs/gap-verification-2026-05-07.md Part E 第 1 项 + Part C §C.6
红线：amount/tax_amount 用 Numeric(10,2) Decimal 存元 — 违反"金额全部用分整数"

本文件只测 schema 形状 + 边界换算 + helper 行为，不依赖真实数据库或 alembic 运行。
存量数据迁移的语义正确性由 v403 迁移文件本身的 SQL 保证（dry-run 由 staging 验证）。
"""
from __future__ import annotations

import importlib.util
import os
import sys
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy

# ── 路径 ───────────────────────────────────────────────────────────────────────
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
FINANCE_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for p in [ROOT, os.path.join(FINANCE_SRC, "src"), FINANCE_SRC]:
    if p not in sys.path:
        sys.path.insert(0, p)


# ── 1. 模型 schema：必须用 BigInteger fen，不能再有 Numeric Decimal 元 ─────────
class TestInvoiceModelFenSchema:
    """invoice 模型字段类型必须是 BigInteger (fen)，旧 Decimal 字段必须删除。"""

    def test_amount_fen_column_is_big_integer(self):
        from models.invoice import Invoice

        col = Invoice.__table__.columns.get("amount_fen")
        assert col is not None, "Invoice 必须有 amount_fen 列（旧 amount 已重命名为 amount_fen）"
        assert isinstance(col.type, sqlalchemy.BigInteger), (
            f"amount_fen 必须是 BigInteger，got {col.type!r}（违反 CLAUDE.md §15 金额用分整数）"
        )
        assert col.nullable is False, "amount_fen 必须 NOT NULL"

    def test_tax_fen_column_is_big_integer(self):
        from models.invoice import Invoice

        col = Invoice.__table__.columns.get("tax_fen")
        assert col is not None, "Invoice 必须有 tax_fen 列（旧 tax_amount 已重命名为 tax_fen）"
        assert isinstance(col.type, sqlalchemy.BigInteger), (
            f"tax_fen 必须是 BigInteger，got {col.type!r}"
        )

    def test_old_decimal_columns_removed(self):
        from models.invoice import Invoice

        assert Invoice.__table__.columns.get("amount") is None, (
            "旧 amount 列必须已删除（不能 Decimal/Numeric 与 fen 共存导致歧义）"
        )
        assert Invoice.__table__.columns.get("tax_amount") is None, (
            "旧 tax_amount 列必须已删除"
        )


# ── 2. 纯整数算术：fen + fen 必须保持 int，不退化为 Decimal/float ──────────────
class TestInvoiceFenArithmetic:
    def test_fen_addition_keeps_int_type(self):
        from models.invoice import Invoice

        # 不入库，仅构造对象测字段类型
        inv = Invoice(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            order_id=uuid.uuid4(),
            invoice_type="electronic",
            amount_fen=12345,
            tax_fen=741,
            platform="nuonuo",
            status="pending",
        )
        total = inv.amount_fen + (inv.tax_fen or 0)
        assert isinstance(total, int), (
            f"int + int 必须是 int，got {type(total).__name__}（金额绝不能退化为 Decimal/float）"
        )
        assert total == 13086

    def test_fen_negation_for_red_flush_keeps_int(self):
        """红冲场景金额取负，必须保持 int"""
        amount_fen = 12345
        neg = -amount_fen
        assert isinstance(neg, int)
        assert neg == -12345


# ── 3. 元 ↔ fen 边界换算 helper：避免 0.30、0.1+0.2 类浮点舍入 bug ────────────
class TestYuanFenBoundaryHelpers:
    def test_yuan_to_fen_simple(self):
        from services.invoice_service import _yuan_to_fen

        assert _yuan_to_fen(Decimal("123.45")) == 12345
        assert _yuan_to_fen(Decimal("100.00")) == 10000
        assert _yuan_to_fen(Decimal("0.01")) == 1

    def test_yuan_to_fen_handles_decimal_floating_edges(self):
        """边界：0.1 + 0.2 = 0.3 在 float 是 0.30000000000000004，但 Decimal 精确"""
        from services.invoice_service import _yuan_to_fen

        assert _yuan_to_fen(Decimal("0.30")) == 30
        assert _yuan_to_fen(Decimal("0.1") + Decimal("0.2")) == 30
        # 三位小数应在边界 round half-even 处理（金额场景餐饮一般两位即可）
        assert _yuan_to_fen(Decimal("9.999")) == 1000  # ROUND_HALF_EVEN

    def test_yuan_to_fen_rejects_negative_or_zero(self):
        """金额必须 > 0；红冲走另外的 negation 路径，不通过此 helper"""
        from services.invoice_service import _yuan_to_fen

        with pytest.raises(ValueError):
            _yuan_to_fen(Decimal("0"))
        with pytest.raises(ValueError):
            _yuan_to_fen(Decimal("-1.00"))

    def test_fen_to_yuan_str_two_decimals(self):
        from services.invoice_service import _fen_to_yuan_str

        assert _fen_to_yuan_str(12345) == "123.45"
        assert _fen_to_yuan_str(10000) == "100.00"
        assert _fen_to_yuan_str(1) == "0.01"
        assert _fen_to_yuan_str(0) == "0.00"
        assert _fen_to_yuan_str(None) is None


# ── 4. _validate_amount 必须接收 int fen 进行精确比较，容差 1 fen ──────────────
class TestValidateAmountFen:
    def test_validate_accepts_exact_match(self):
        from services.invoice_service import InvoiceService

        svc = InvoiceService()
        # exact match never raises
        svc._validate_amount_fen(12345, 12345)

    def test_validate_accepts_one_fen_tolerance(self):
        from services.invoice_service import InvoiceService

        svc = InvoiceService()
        # 1 fen diff allowed (tolerance == 1 fen)
        svc._validate_amount_fen(12346, 12345)
        svc._validate_amount_fen(12344, 12345)

    def test_validate_rejects_two_fen_diff(self):
        from services.invoice_service import InvoiceAmountMismatchError, InvoiceService

        svc = InvoiceService()
        with pytest.raises(InvoiceAmountMismatchError):
            svc._validate_amount_fen(12347, 12345)

    def test_validate_signature_uses_int_not_decimal(self):
        """方法签名必须用 int 类型注解，避免重新引入 Decimal"""
        import inspect

        from services.invoice_service import InvoiceService

        sig = inspect.signature(InvoiceService._validate_amount_fen)
        for name, param in sig.parameters.items():
            if name == "self":
                continue
            ann = param.annotation
            assert ann is int, (
                f"_validate_amount_fen 参数 {name} 类型注解必须是 int，got {ann!r}"
            )


# ── 5. _invoice_to_dict 序列化：API 边界向后兼容（输出 amount=元字符串）──────
class TestInvoiceToDictSerialization:
    def test_dict_emits_amount_as_yuan_string(self):
        """API 响应 amount 字段保持 '123.45' 元字符串向后兼容（外部消费者不破）。"""
        from datetime import datetime, timezone

        from models.invoice import Invoice
        from services.invoice_service import _invoice_to_dict

        now = datetime.now(timezone.utc)
        inv = Invoice(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            order_id=uuid.uuid4(),
            invoice_type="electronic",
            amount_fen=12345,
            tax_fen=741,
            platform="nuonuo",
            status="pending",
            created_at=now,
        )
        out = _invoice_to_dict(inv)

        assert out["amount"] == "123.45", (
            f"amount 序列化必须是 '123.45' 元字符串（API 兼容），got {out['amount']!r}"
        )
        assert out["tax_amount"] == "7.41"
        # 同时输出 fen 整数供新客户端使用（金税四期对账）
        assert out["amount_fen"] == 12345
        assert out["tax_fen"] == 741
        assert isinstance(out["amount_fen"], int)

    def test_dict_emits_none_for_missing_tax(self):
        from models.invoice import Invoice
        from services.invoice_service import _invoice_to_dict

        inv = Invoice(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            order_id=uuid.uuid4(),
            invoice_type="electronic",
            amount_fen=12345,
            tax_fen=None,
            platform="nuonuo",
            status="pending",
        )
        out = _invoice_to_dict(inv)
        assert out["tax_amount"] is None
        assert out["tax_fen"] is None


# ── 6. 迁移文件存在 + revision 链对接 v402（AST 解析，不依赖 alembic 运行时）───
class TestMigrationFile:
    def test_v403_invoice_amount_fen_migration_present(self):
        import ast

        repo_root = Path(__file__).resolve().parents[4]
        mig_path = (
            repo_root
            / "shared"
            / "db-migrations"
            / "versions"
            / "v403_invoice_amount_fen.py"
        )
        assert mig_path.exists(), f"迁移文件 {mig_path} 必须存在"

        # AST 解析避免依赖 alembic / sqlalchemy 运行时
        tree = ast.parse(mig_path.read_text(encoding="utf-8"))

        assigned: dict[str, str] = {}
        functions: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if isinstance(node.value, ast.Constant):
                    assigned[node.target.id] = node.value.value
            elif isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name) and isinstance(node.value, ast.Constant):
                        assigned[tgt.id] = node.value.value
            elif isinstance(node, ast.FunctionDef):
                functions.add(node.name)

        assert assigned.get("revision") == "v403", (
            f"revision 必须是 'v403'，got {assigned.get('revision')!r}"
        )
        assert assigned.get("down_revision") == "v402", (
            f"down_revision 必须接 'v402'，got {assigned.get('down_revision')!r}"
        )
        assert "upgrade" in functions, "缺 upgrade()"
        assert "downgrade" in functions, "缺 downgrade()"

        # 守门：迁移文件正文必须含 amount_fen 列名（防漂移到错误字段）
        body = mig_path.read_text(encoding="utf-8")
        assert "amount_fen" in body
        assert "tax_fen" in body
        assert "BigInteger" in body
