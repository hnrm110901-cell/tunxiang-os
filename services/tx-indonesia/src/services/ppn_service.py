"""印度尼西亚 PPN（Pajak Pertambahan Nilai）计算引擎 — Phase 3 Sprint 3.4

税率（UU HPP 2022 生效）：
  - Standard: 11% （大部分商品和服务，2022年4月起）
  - Luxury:   12% （奢侈品，计划中逐步实施）
  - Export:    0% （出口商品）
  - Exempt:    0% （生活必需品、医疗服务、教育服务等）

所有金额单位：分（fen），与整系统 Amount Convention 一致。
印尼盾（IDR）没有小数位，按系统约定仍使用分存储（1 IDR = 1 fen）。
"""

from __future__ import annotations

import enum
import re
from typing import Any, Dict, List

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Dish

log = structlog.get_logger(__name__)


class PPNCategory(str, enum.Enum):
    """PPN 分类枚举"""

    STANDARD = "standard"  # 11% (standard rate)
    LUXURY = "luxury"  # 12% (luxury goods, planned)
    EXPORT = "export"  # 0% (export)
    EXEMPT = "exempt"  # 0% (essential goods)


class PPNInvalidNPWPError(ValueError):
    """NPWP 税号格式无效"""
    pass


class PPNService:
    """PPN 计算引擎

    用法：
        ppn = PPNService(db, tenant_id)
        tax = await ppn.calculate_invoice_ppn(items)

    金额全部使用分（整数），避免浮点误差。
    印尼盾（IDR）没有小数位，1 IDR = 1 fen。
    """

    PPN_RATES = {
        PPNCategory.STANDARD: 0.11,  # 11% — UU HPP
        PPNCategory.LUXURY: 0.12,  # 12% — 奢侈品（计划）
        PPNCategory.EXPORT: 0.0,  # 0% — 出口
        PPNCategory.EXEMPT: 0.0,  # 0% — 基本必需品
    }

    # 反向查找：字符串 → 枚举
    _STR_TO_CATEGORY = {
        "standard": PPNCategory.STANDARD,
        "luxury": PPNCategory.LUXURY,
        "export": PPNCategory.EXPORT,
        "exempt": PPNCategory.EXEMPT,
    }

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id

    # ════════════════════════════════════════════════════════
    # 核心计算
    # ════════════════════════════════════════════════════════

    def calculate_ppn(self, category: PPNCategory, amount_fen: int) -> int:
        """计算单项 PPN 金额（分）

        PPN 采用价内税模式（PPN termasuk dalam harga）：
          PPN payable = amount × rate / (1 + rate)

        例：Rp100,000 标准商品，PPN = 100,000 × 0.11 / 1.11 ≈ Rp9,910
        """
        rate = self.PPN_RATES[category]
        if rate == 0.0:
            return 0
        return int(amount_fen * rate / (1 + rate))

    async def get_ppn_category(self, dish_id: str) -> PPNCategory:
        """查询菜品的 PPN 分类，默认返回 STANDARD

        从 Dish.ppn_category 字段读取：
          - "standard"  → STANDARD (11%)
          - "luxury"    → LUXURY   (12%)
          - "export"    → EXPORT   (0%)
          - "exempt"    → EXEMPT   (0%)
          - NULL 或未知  → STANDARD (11%)
        """
        result = await self.db.execute(
            select(Dish.ppn_category).where(Dish.id == dish_id)
        )
        row = result.fetchone()
        if row is None:
            return PPNCategory.STANDARD
        raw = row[0]
        return self._STR_TO_CATEGORY.get(raw, PPNCategory.STANDARD)

    async def calculate_invoice_ppn(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """计算整单 PPN

        Args:
            items: 订单明细列表，每条包含:
                - amount_fen (int): 该项金额（分）
                - ppn_category (str, optional): "standard"/"luxury"/"export"/"exempt"

        Returns:
            {
                "standard_11_fen":  总 11% PPN 金额,
                "luxury_12_fen":    总 12% PPN 金额,
                "export_fen":       总出口金额,
                "exempt_fen":       总豁免金额,
                "total_ppn_fen":    应付 PPN 总额,
            }
        """
        standard_11_fen = 0
        luxury_12_fen = 0
        export_fen = 0
        exempt_fen = 0

        for item in items:
            amount_fen = int(item.get("amount_fen", 0))
            raw_category = item.get("ppn_category", PPNCategory.STANDARD.value)
            category = self._STR_TO_CATEGORY.get(raw_category, PPNCategory.STANDARD)

            ppn_amount = self.calculate_ppn(category, amount_fen)

            if category == PPNCategory.STANDARD:
                standard_11_fen += ppn_amount
            elif category == PPNCategory.LUXURY:
                luxury_12_fen += ppn_amount
            elif category == PPNCategory.EXPORT:
                export_fen += amount_fen
            elif category == PPNCategory.EXEMPT:
                exempt_fen += amount_fen

        total_ppn_fen = standard_11_fen + luxury_12_fen

        return {
            "standard_11_fen": standard_11_fen,
            "standard_11_idr": round(standard_11_fen, 0),
            "luxury_12_fen": luxury_12_fen,
            "luxury_12_idr": round(luxury_12_fen, 0),
            "export_fen": export_fen,
            "export_idr": round(export_fen, 0),
            "exempt_fen": exempt_fen,
            "exempt_idr": round(exempt_fen, 0),
            "total_ppn_fen": total_ppn_fen,
            "total_ppn_idr": round(total_ppn_fen, 0),
        }

    # ════════════════════════════════════════════════════════
    # NPWP 验证
    # ════════════════════════════════════════════════════════

    @staticmethod
    def validate_npwp(npwp: str) -> bool:
        """验证印尼 NPWP 税号格式

        NPWP 格式：NN.NNN.NNN.N-NNN.NNN（15位数字）或 16 位数字（个人 2024 新规）
        格式校验规则：
          - 只保留数字
          - 15 位或 16 位纯数字
          - 校验简单格式匹配

        Args:
            npwp: NPWP 号（可含格式符号）

        Returns:
            True 如果格式合法
        """
        if not npwp:
            return False

        # 只保留数字
        digits = re.sub(r"[^0-9]", "", npwp)

        # NPWP 格式：15 位（法人）或 16 位（个人，2024 年起）
        if len(digits) not in (15, 16):
            return False

        return True

    # ════════════════════════════════════════════════════════
    # 工具方法
    # ════════════════════════════════════════════════════════

    @staticmethod
    def get_rates() -> Dict[str, Any]:
        """返回当前 PPN 税率表"""
        return {
            "rates": [
                {
                    "category": PPNCategory.STANDARD.value,
                    "label": "Tarif Standar",
                    "rate": 0.11,
                    "rate_percent": 11.0,
                    "description": "大部分商品和服务（UU HPP 2022）",
                },
                {
                    "category": PPNCategory.LUXURY.value,
                    "label": "Barang Mewah",
                    "rate": 0.12,
                    "rate_percent": 12.0,
                    "description": "奢侈品（计划中逐步实施）",
                },
                {
                    "category": PPNCategory.EXPORT.value,
                    "label": "Ekspor",
                    "rate": 0.0,
                    "rate_percent": 0.0,
                    "description": "出口商品（0%）",
                },
                {
                    "category": PPNCategory.EXEMPT.value,
                    "label": "Dibebaskan",
                    "rate": 0.0,
                    "rate_percent": 0.0,
                    "description": "基本必需品、医疗、教育等",
                },
            ],
            "note": "印度尼西亚 PPN 税率，UU HPP 2022 生效",
        }

    @staticmethod
    def get_categories() -> List[Dict[str, Any]]:
        """返回 PPN 分类选项（用于前端下拉/配置）"""
        return [
            {
                "value": PPNCategory.STANDARD.value,
                "label": "Standar 11%",
                "description": "一般商品和服务",
            },
            {
                "value": PPNCategory.LUXURY.value,
                "label": "Mewah 12%",
                "description": "奢侈品",
            },
            {
                "value": PPNCategory.EXPORT.value,
                "label": "Ekspor 0%",
                "description": "出口商品",
            },
            {
                "value": PPNCategory.EXEMPT.value,
                "label": "Bebas 0%",
                "description": "豁免供应品（基本必需品等）",
            },
        ]
