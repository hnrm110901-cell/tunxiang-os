"""马来西亚 SST（Sales & Service Tax）计算引擎 — Sprint 1.3

税率（2026年最新）：
  - Standard: 6% （大部分商品和服务）
  - Specific: 8% （石油产品、加工食品等特定品类）
  - Exempt:   0% （豁免供应品）

所有金额单位：分（fen），与整系统 Amount Convention 一致。
"""

from __future__ import annotations

import enum
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Dish

log = structlog.get_logger(__name__)


class SSTCategory(str, enum.Enum):
    """SST 分类枚举"""

    STANDARD = "standard"  # 6%
    SPECIFIC = "specific"  # 8%
    EXEMPT = "exempt"  # 0%


class SSTService:
    """SST 计算引擎

    用法：
        sst = SSTService(db, tenant_id)
        tax = await sst.calculate_invoice_sst(items)

    金额全部使用分（整数），避免浮点误差。
    """

    SST_RATES = {
        SSTCategory.STANDARD: 0.06,
        SSTCategory.SPECIFIC: 0.08,
        SSTCategory.EXEMPT: 0.0,
    }

    # 反向查找：字符串 → 枚举
    _STR_TO_CATEGORY = {
        "standard": SSTCategory.STANDARD,
        "specific": SSTCategory.SPECIFIC,
        "exempt": SSTCategory.EXEMPT,
    }

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id

    # ════════════════════════════════════════════════════════
    # 核心计算
    # ════════════════════════════════════════════════════════

    def calculate_sst(self, category: SSTCategory, amount_fen: int) -> int:
        """计算单项 SST 金额（分）

        SST 采用价内税模式（与增值税一致）：
          SST payable = price × rate / (1 + rate)

        例：RM100 标准商品，SST = 100 × 0.06 / 1.06 ≈ RM5.66
        """
        rate = self.SST_RATES[category]
        if rate == 0.0:
            return 0
        return int(amount_fen * rate / (1 + rate))

    async def get_sst_category(self, dish_id: str) -> SSTCategory:
        """查询菜品的 SST 分类，默认返回 STANDARD

        从 Dish.sst_category 字段读取：
          - "standard"  → STANDARD (6%)
          - "specific"  → SPECIFIC  (8%)
          - "exempt"    → EXEMPT    (0%)
          - NULL 或未知  → STANDARD (6%)
        """
        result = await self.db.execute(
            select(Dish.sst_category).where(Dish.id == dish_id)
        )
        row = result.fetchone()
        if row is None:
            return SSTCategory.STANDARD
        raw = row[0]
        return self._STR_TO_CATEGORY.get(raw, SSTCategory.STANDARD)

    async def calculate_invoice_sst(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """计算整单 SST

        Args:
            items: 订单明细列表，每条包含:
                - amount_fen (int): 该项金额（分）
                - sst_category (str, optional): "standard"/"specific"/"exempt"

        Returns:
            {
                "standard_6_fen":  总 6% SST 金额,
                "specific_8_fen":  总 8% SST 金额,
                "exempt_fen":      总豁免金额,
                "total_sst_fen":   应付 SST 总额,
            }
        """
        standard_6_fen = 0
        specific_8_fen = 0
        exempt_fen = 0

        for item in items:
            amount_fen = int(item.get("amount_fen", 0))
            raw_category = item.get("sst_category", SSTCategory.STANDARD.value)
            category = self._STR_TO_CATEGORY.get(raw_category, SSTCategory.STANDARD)

            sst_amount = self.calculate_sst(category, amount_fen)

            if category == SSTCategory.STANDARD:
                standard_6_fen += sst_amount
            elif category == SSTCategory.SPECIFIC:
                specific_8_fen += sst_amount
            elif category == SSTCategory.EXEMPT:
                exempt_fen += sst_amount

        total_sst_fen = standard_6_fen + specific_8_fen

        return {
            "standard_6_fen": standard_6_fen,
            "standard_6_yuan": round(standard_6_fen / 100, 2),
            "specific_8_fen": specific_8_fen,
            "specific_8_yuan": round(specific_8_fen / 100, 2),
            "exempt_fen": exempt_fen,
            "exempt_yuan": round(exempt_fen / 100, 2),
            "total_sst_fen": total_sst_fen,
            "total_sst_yuan": round(total_sst_fen / 100, 2),
        }

    # ════════════════════════════════════════════════════════
    # 工具方法
    # ════════════════════════════════════════════════════════

    @staticmethod
    def get_rates() -> Dict[str, Any]:
        """返回当前 SST 税率表"""
        return {
            "rates": [
                {
                    "category": SSTCategory.STANDARD.value,
                    "label": "标准税率",
                    "rate": 0.06,
                    "rate_percent": 6.0,
                    "description": "大部分商品和服务",
                },
                {
                    "category": SSTCategory.SPECIFIC.value,
                    "label": "特定税率",
                    "rate": 0.08,
                    "rate_percent": 8.0,
                    "description": "石油产品、加工食品等特定品类",
                },
                {
                    "category": SSTCategory.EXEMPT.value,
                    "label": "豁免",
                    "rate": 0.0,
                    "rate_percent": 0.0,
                    "description": "豁免供应品（基本食材/教育/医疗等）",
                },
            ],
            "note": "2026年马来西亚 SST 税率，生效日期 2024-03-01",
        }

    @staticmethod
    def get_categories() -> List[Dict[str, Any]]:
        """返回 SST 分类选项（用于前端下拉/配置）"""
        return [
            {
                "value": SSTCategory.STANDARD.value,
                "label": "标准 6%",
                "description": "一般商品和服务",
            },
            {
                "value": SSTCategory.SPECIFIC.value,
                "label": "特定 8%",
                "description": "石油产品、加工食品等特定品类",
            },
            {
                "value": SSTCategory.EXEMPT.value,
                "label": "豁免 0%",
                "description": "豁免供应品",
            },
        ]
