"""东南亚税务引擎集成测试 — SST / PPN / VAT

验证价内税公式正确性、分类映射、发票计算。
所有金额单位：分（fen）。
"""
from __future__ import annotations

import importlib.util
import sys
from unittest.mock import AsyncMock

import pytest

from tests.conftest import MOCK_TENANT_ID  # noqa: F401


def _load_module(name: str, path: str):
    """从文件路径加载 Python 模块（解决目录名含连字符的问题）。"""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ═══════════════════════════════════════════════════════════════════════════
# SST — Malaysia (6%/8%/0%)
# ═══════════════════════════════════════════════════════════════════════════


class TestSSTEngine:
    """马来西亚 SST (Sales & Service Tax)"""

    @pytest.fixture
    def sst_service(self):
        mod = _load_module(
            "sst_service",
            "services/tx-malaysia/src/services/sst_service.py",
        )
        db = AsyncMock()
        service = mod.SSTService(db, MOCK_TENANT_ID)
        return service, mod.SSTCategory

    def test_standard_rate_6pct(self, sst_service):
        """SST 6% 价内税: RM100 × 0.06 / 1.06 ≈ RM5.66"""
        service, Cat = sst_service
        tax = service.calculate_sst(Cat.STANDARD, 10000)
        assert tax == 566, f"Expected 566 fen, got {tax}"

    def test_specific_rate_8pct(self, sst_service):
        """SST 8%: RM50 × 0.08 / 1.08 ≈ RM3.70"""
        service, Cat = sst_service
        tax = service.calculate_sst(Cat.SPECIFIC, 5000)
        assert tax == 370, f"Expected 370 fen, got {tax}"

    def test_exempt_rate_0pct(self, sst_service):
        """SST 0% 豁免"""
        service, Cat = sst_service
        assert service.calculate_sst(Cat.EXEMPT, 10000) == 0

    def test_zero_amount(self, sst_service):
        """金额为 0 时 SST 为 0"""
        service, Cat = sst_service
        assert service.calculate_sst(Cat.STANDARD, 0) == 0

    def test_large_amount_edge(self, sst_service):
        """大金额场景: RM1,000,000"""
        service, Cat = sst_service
        tax = service.calculate_sst(Cat.STANDARD, 100_000_000)
        assert tax == 5_660_377, f"Expected 5,660,377 fen, got {tax}"

    def test_invoice_calculation(self, sst_service):
        """整单 SST 计算（异步方法）"""
        import asyncio

        service, Cat = sst_service
        items = [
            {"amount_fen": 10000, "sst_category": "standard"},
            {"amount_fen": 5000, "sst_category": "specific"},
            {"amount_fen": 8000, "sst_category": "exempt"},
        ]
        result = asyncio.run(service.calculate_invoice_sst(items))
        assert result["standard_6_fen"] == 566
        assert result["specific_8_fen"] == 370
        assert result["exempt_fen"] == 0
        assert result["total_sst_fen"] == 936

    def test_unknown_category_defaults_standard(self, sst_service):
        """未知分类默认回退到 STANDARD"""
        import asyncio

        service, Cat = sst_service
        result = asyncio.run(
            service.calculate_invoice_sst(
                [{"amount_fen": 10000, "sst_category": "unknown_category"}]
            )
        )
        assert result["standard_6_fen"] == 566

    def test_missing_category_defaults_standard(self, sst_service):
        """NULL/缺省分类默认为 STANDARD"""
        import asyncio

        service, Cat = sst_service
        result = asyncio.run(
            service.calculate_invoice_sst([{"amount_fen": 10000}])
        )
        assert result["standard_6_fen"] > 0


# ═══════════════════════════════════════════════════════════════════════════
# PPN — Indonesia (11%/12%/0%)
# ═══════════════════════════════════════════════════════════════════════════


class TestPPNEngine:
    """印度尼西亚 PPN (Pajak Pertambahan Nilai)"""

    @pytest.fixture
    def ppn_service(self):
        mod = _load_module(
            "ppn_service",
            "services/tx-indonesia/src/services/ppn_service.py",
        )
        db = AsyncMock()
        service = mod.PPNService(db, MOCK_TENANT_ID)
        return service, mod.PPNCategory

    def test_standard_rate_11pct(self, ppn_service):
        """PPN 11%: Rp11100 × 0.11 / 1.11 = Rp1100"""
        service, Cat = ppn_service
        tax = service.calculate_ppn(Cat.STANDARD, 11100)
        assert tax == 1100, f"Expected 1100, got {tax}"

    def test_luxury_rate_12pct(self, ppn_service):
        """PPN 12%: Rp11200 × 0.12 / 1.12 ≈ Rp1200"""
        service, Cat = ppn_service
        tax = service.calculate_ppn(Cat.LUXURY, 11200)
        assert tax in (1199, 1200), f"Expected ~1200, got {tax}"

    def test_export_rate_0pct(self, ppn_service):
        """PPN 0% 出口"""
        service, Cat = ppn_service
        assert service.calculate_ppn(Cat.EXPORT, 10000) == 0

    def test_exempt_rate_0pct(self, ppn_service):
        """PPN 0% 豁免"""
        service, Cat = ppn_service
        assert service.calculate_ppn(Cat.EXEMPT, 10000) == 0

    def test_invoice_ppn(self, ppn_service):
        """整单 PPN 计算"""
        import asyncio

        service, Cat = ppn_service
        items = [
            {"amount_fen": 11100, "ppn_category": "standard"},
            {"amount_fen": 11200, "ppn_category": "luxury"},
            {"amount_fen": 10000, "ppn_category": "export"},
        ]
        result = asyncio.run(service.calculate_invoice_ppn(items))
        assert result["standard_11_fen"] == 1100
        assert result["total_ppn_fen"] > 0

    def test_npwp_validation(self, ppn_service):
        """NPWP 税号: 15 位数字 / 带格式"""
        service, Cat = ppn_service
        assert service.validate_npwp("123456789012345") is True
        assert service.validate_npwp("12.345.678.9-012.345") is True
        assert service.validate_npwp("12345") is False
        assert service.validate_npwp("") is False
        assert service.validate_npwp("abcdefghijklmno") is False


# ═══════════════════════════════════════════════════════════════════════════
# VAT — Vietnam (10%/8%/0%)
# ═══════════════════════════════════════════════════════════════════════════


class TestVATEngine:
    """越南 VAT (Value Added Tax)"""

    @pytest.fixture
    def vat_mod(self):
        mod = _load_module(
            "vat_service",
            "services/tx-vietnam/src/services/vat_service.py",
        )
        return mod

    def test_standard_rate_10pct(self, vat_mod):
        """VAT 10%: ₫110000 × 0.10 / 1.10 = ₫10000"""
        tax = vat_mod.VATService.calculate_vat(vat_mod.VATCategory.STANDARD, 110000)
        assert tax == 10000

    def test_reduced_rate_8pct(self, vat_mod):
        """VAT 8%: ₫108000 × 0.08 / 1.08 = ₫8000"""
        tax = vat_mod.VATService.calculate_vat(vat_mod.VATCategory.REDUCED, 108000)
        assert tax == 8000

    def test_export_rate_0pct(self, vat_mod):
        """VAT 0% 出口"""
        tax = vat_mod.VATService.calculate_vat(vat_mod.VATCategory.EXPORT, 100000)
        assert tax == 0

    def test_exempt_rate_0pct(self, vat_mod):
        """VAT 0% 豁免"""
        tax = vat_mod.VATService.calculate_vat(vat_mod.VATCategory.EXEMPT, 100000)
        assert tax == 0

    def test_price_exclusive(self, vat_mod):
        """从价内价格反推不含税价"""
        excl = vat_mod.VATService.calculate_price_exclusive(
            vat_mod.VATCategory.STANDARD, 110000
        )
        assert excl == 100000

    def test_invoice_vat_calculation(self, vat_mod):
        """整单 VAT 计算"""
        result = vat_mod.VATService.calculate_invoice_vat(
            [
                {"amount_fen": 110000, "vat_category": "standard"},
                {"amount_fen": 108000, "vat_category": "reduced"},
                {"amount_fen": 100000, "vat_category": "exempt"},
            ]
        )
        assert result["total_vat_fen"] == 18000  # 10000 + 8000 + 0
        assert result["total_inclusive_fen"] == 318000

    def test_empty_invoice(self, vat_mod):
        """空发票返回零值"""
        result = vat_mod.VATService.calculate_invoice_vat([])
        assert result["total_vat_fen"] == 0
        assert result["items"] == []

    def test_vietnam_tax_id_10_digit(self, vat_mod):
        """10 位 MST 税号"""
        assert vat_mod.VATService.validate_tax_id("0100109106") is True

    def test_vietnam_tax_id_13_digit(self, vat_mod):
        """13 位 MST 税号 (10 + 后缀)"""
        assert vat_mod.VATService.validate_tax_id("0100109106-001") is True

    def test_vietnam_tax_id_invalid(self, vat_mod):
        """无效税号"""
        assert vat_mod.VATService.validate_tax_id("12345") is False
        assert vat_mod.VATService.validate_tax_id("") is False
        assert vat_mod.VATService.validate_tax_id("abcdefghij") is False

    def test_get_rates(self, vat_mod):
        """税率表包含完整分类"""
        rates = vat_mod.VATService.get_rates()
        assert "standard" in rates
        assert "reduced" in rates
        assert "export" in rates
        assert "exempt" in rates
        assert rates["standard"]["rate"] == "10%"
