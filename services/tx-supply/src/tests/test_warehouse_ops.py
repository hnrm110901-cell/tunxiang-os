"""移库与拆组测试"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from services.warehouse_ops import (
    create_transfer_order,
    create_split_assembly,
    create_bom_split,
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  移库单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestCreateTransferOrder:
    @pytest.mark.asyncio
    async def test_create_basic(self):
        items = [
            {"ingredient_id": "i1", "name": "鲈鱼", "quantity": 20, "unit": "kg", "batch_no": "B001"},
        ]
        result = await create_transfer_order("wh_main", "wh_cold", items, "t1", db=None)
        assert result["transfer_id"].startswith("wtf_")
        assert result["status"] == "pending"
        assert result["from_warehouse"] == "wh_main"
        assert result["to_warehouse"] == "wh_cold"
        assert result["item_count"] == 1
        assert result["total_qty"] == 20

    @pytest.mark.asyncio
    async def test_same_warehouse_raises(self):
        items = [{"ingredient_id": "i1", "quantity": 1}]
        with pytest.raises(ValueError, match="不能相同"):
            await create_transfer_order("wh_main", "wh_main", items, "t1", db=None)

    @pytest.mark.asyncio
    async def test_empty_items_raises(self):
        with pytest.raises(ValueError, match="至少一项"):
            await create_transfer_order("wh_main", "wh_cold", [], "t1", db=None)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  拆分/组装
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestCreateSplitAssembly:
    @pytest.mark.asyncio
    async def test_split(self):
        components = [
            {"ingredient_id": "c1", "name": "鸡腿", "quantity": 2, "unit": "个"},
            {"ingredient_id": "c2", "name": "鸡翅", "quantity": 2, "unit": "个"},
            {"ingredient_id": "c3", "name": "鸡胸", "quantity": 2, "unit": "块"},
        ]
        result = await create_split_assembly("chicken_whole", "split", components, "t1", db=None)
        assert result["sa_id"].startswith("sa_")
        assert result["op_type"] == "split"
        assert result["component_count"] == 3
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_assembly(self):
        components = [
            {"ingredient_id": "c1", "name": "鸡腿", "quantity": 1, "unit": "个"},
            {"ingredient_id": "c2", "name": "卤料", "quantity": 0.5, "unit": "kg"},
        ]
        result = await create_split_assembly("braised_leg", "assembly", components, "t1", db=None)
        assert result["op_type"] == "assembly"
        assert result["total_component_qty"] == 1.5

    @pytest.mark.asyncio
    async def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="split 或 assembly"):
            await create_split_assembly("item_1", "merge", [{"ingredient_id": "c1", "quantity": 1}], "t1", db=None)

    @pytest.mark.asyncio
    async def test_empty_components_raises(self):
        with pytest.raises(ValueError, match="至少一项"):
            await create_split_assembly("item_1", "split", [], "t1", db=None)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  BOM 拆分
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestCreateBomSplit:
    @pytest.mark.asyncio
    async def test_bom_split_basic(self):
        bom = [
            {"ingredient_id": "i1", "name": "鲈鱼", "qty_per_dish": 0.5, "unit": "kg", "cost_fen": 1750},
            {"ingredient_id": "i2", "name": "酱油", "qty_per_dish": 0.05, "unit": "L", "cost_fen": 50},
        ]
        result = await create_bom_split("dish_1", 10, "t1", db=None, bom=bom)
        assert result["split_id"].startswith("bsplit_")
        assert result["ingredient_count"] == 2
        assert result["ingredients"][0]["required_qty"] == 5.0  # 0.5 * 10
        assert result["ingredients"][1]["required_qty"] == 0.5  # 0.05 * 10
        assert result["total_cost_fen"] == (1750 + 50) * 10

    @pytest.mark.asyncio
    async def test_zero_quantity_raises(self):
        with pytest.raises(ValueError, match="大于0"):
            await create_bom_split("dish_1", 0, "t1", db=None, bom=[])

    @pytest.mark.asyncio
    async def test_no_bom_raises(self):
        with pytest.raises(ValueError, match="无 BOM"):
            await create_bom_split("dish_1", 5, "t1", db=None, bom=[])
