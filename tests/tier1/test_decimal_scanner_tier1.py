"""Tier1 TDD 测试 — scan_decimal_amount_columns.py 扫描器本身的正确性

覆盖：
1. test_scanner_finds_invoice_violation     — 找到 tx-finance/invoice.py:66 amount 违规
2. test_scanner_finds_wine_violation        — 找到 tx-trade/wine_storage.py:61 storage_price 违规
3. test_scanner_skips_rate_column          — tax_rate Numeric(5, 4) 不报警（白名单）
4. test_scanner_idempotent                  — 跑两次结果一致
"""
from __future__ import annotations

import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

# 确保 scripts/audit 在 sys.path 上
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCANNER_DIR = _REPO_ROOT / "scripts" / "audit"
if str(_SCANNER_DIR) not in sys.path:
    sys.path.insert(0, str(_SCANNER_DIR))

from scan_decimal_amount_columns import (  # noqa: E402
    Violation,
    scan_directory,
    scan_file,
)

# ─── fixtures ─────────────────────────────────────────────────────────────────


def _make_service_tree(tmp_path: Path, service: str, model_name: str, source: str) -> Path:
    """在 tmp_path 下创建 <service>/src/models/<model_name>.py，返回 model 文件路径。"""
    model_dir = tmp_path / service / "src" / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    model_file = model_dir / model_name
    model_file.write_text(textwrap.dedent(source), encoding="utf-8")
    return model_file


# ─── 测试 1：找到 invoice 违规 ─────────────────────────────────────────────────


def test_scanner_finds_invoice_violation(tmp_path: Path) -> None:
    """扫描器必须识别 tx-finance/invoice.py 的 amount: Decimal = Column(Numeric(10, 2)) 违规。"""
    source = """\
        from decimal import Decimal
        from typing import Optional
        from sqlalchemy import Column, Numeric, String

        class Invoice:
            __tablename__ = "invoices"
            amount: Decimal = Column(Numeric(10, 2), nullable=False)
            tax_amount: Optional[Decimal] = Column(Numeric(10, 2))
    """
    _make_service_tree(tmp_path, "tx-finance", "invoice.py", source)

    violations = scan_directory(tmp_path)

    assert len(violations) >= 2, f"期望至少 2 个违规，实际 {len(violations)}: {violations}"

    names = [v.column_name for v in violations]
    assert "amount" in names, f"未找到 amount 违规: {names}"
    assert "tax_amount" in names, f"未找到 tax_amount 违规: {names}"

    for v in violations:
        assert v.severity == "high", f"{v.column_name} 期望 high，实际 {v.severity}"
        assert v.type_args == "Numeric(10, 2)"


# ─── 测试 2：找到 wine_storage 违规 ───────────────────────────────────────────


def test_scanner_finds_wine_violation(tmp_path: Path) -> None:
    """扫描器必须识别 tx-trade/wine_storage.py 的 storage_price: Mapped[Decimal] = mapped_column(Numeric(12, 2)) 违规。"""
    source = """\
        from decimal import Decimal
        from sqlalchemy import Numeric
        from sqlalchemy.orm import Mapped, mapped_column

        class WineStorageRecord:
            __tablename__ = "wine_storage_records"
            storage_price: Mapped[Decimal | None] = mapped_column(
                Numeric(12, 2), nullable=True, comment="存入时金额（元）"
            )
    """
    _make_service_tree(tmp_path, "tx-trade", "wine_storage.py", source)

    violations = scan_directory(tmp_path)

    assert len(violations) >= 1, f"期望至少 1 个违规，实际 {len(violations)}"
    assert violations[0].column_name == "storage_price"
    assert violations[0].type_args == "Numeric(12, 2)"
    assert violations[0].severity == "high"


# ─── 测试 3：白名单 rate 字段不报警 ──────────────────────────────────────────


def test_scanner_skips_rate_column(tmp_path: Path) -> None:
    """tax_rate: Mapped[Numeric] = mapped_column(Numeric(5, 4)) 不得报警（百分比白名单）。"""
    source = """\
        from decimal import Decimal
        from typing import Optional
        from sqlalchemy import Numeric
        from sqlalchemy.orm import Mapped, mapped_column

        class Invoice:
            __tablename__ = "invoices"
            # 以下应被白名单豁免（rate 字段 scale<=4）
            tax_rate: Mapped[Optional[Decimal]] = mapped_column(
                Numeric(5, 4), nullable=True, comment="税率（如0.13表示13%）"
            )
            discount_rate: Mapped[Optional[Decimal]] = mapped_column(
                Numeric(5, 4), nullable=True, comment="折扣率"
            )
    """
    _make_service_tree(tmp_path, "tx-expense", "invoice.py", source)

    violations = scan_directory(tmp_path)

    rate_violations = [v for v in violations if "rate" in v.column_name]
    assert len(rate_violations) == 0, (
        f"rate 字段不应被报警，但发现: {[v.column_name for v in rate_violations]}"
    )


# ─── 测试 4：幂等性 ────────────────────────────────────────────────────────────


def test_scanner_idempotent(tmp_path: Path) -> None:
    """扫描同一目录两次，结果完全一致（文件列表 + 行号 + 字段名）。"""
    source = """\
        from decimal import Decimal
        from sqlalchemy import Numeric
        from sqlalchemy.orm import Mapped, mapped_column

        class Banquet:
            __tablename__ = "banquets"
            deposit_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
            total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    """
    _make_service_tree(tmp_path, "tx-trade", "banquet.py", source)

    run1 = scan_directory(tmp_path)
    run2 = scan_directory(tmp_path)

    assert len(run1) == len(run2), f"两次扫描数量不一致: {len(run1)} vs {len(run2)}"
    for v1, v2 in zip(run1, run2):
        assert v1.file == v2.file
        assert v1.line == v2.line
        assert v1.column_name == v2.column_name
        assert v1.type_args == v2.type_args
        assert v1.severity == v2.severity


# ─── 额外：确保不报 Integer 字段 ───────────────────────────────────────────────


def test_scanner_skips_integer_amount_fields(tmp_path: Path) -> None:
    """已正确使用 Integer 类型的金额字段不应报警。"""
    source = """\
        from sqlalchemy import Integer
        from sqlalchemy.orm import Mapped, mapped_column

        class Order:
            __tablename__ = "orders"
            total_amount: Mapped[int] = mapped_column(Integer, nullable=False)
            payment_amount: Mapped[int] = mapped_column(Integer, nullable=False)
            discount_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    """
    _make_service_tree(tmp_path, "tx-trade", "order.py", source)

    violations = scan_directory(tmp_path)

    assert len(violations) == 0, f"Integer 字段不应报警，但发现: {violations}"
