"""快速开店 — 配置克隆测试"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.store_clone import execute_clone, StoreCloneRequest, CloneItemResult


class TestExecuteClone:
    def test_clone_all_items_success(self):
        """克隆所有配置项应全部成功"""
        items = ["dishes", "payments", "tables", "marketing", "kds", "roles"]
        result = execute_clone("store_a", "store_b", items)
        assert result.total == 6
        assert result.succeeded == 6
        assert result.failed == 0
        for r in result.results:
            assert r.success is True

    def test_clone_single_item(self):
        """克隆单个配置项"""
        result = execute_clone("store_a", "store_b", ["dishes"])
        assert result.total == 1
        assert result.succeeded == 1
        assert result.results[0].item == "dishes"
        assert result.results[0].count == 56

    def test_clone_same_store_fails(self):
        """源门店与目标门店相同时应全部失败"""
        items = ["dishes", "payments", "tables"]
        result = execute_clone("store_a", "store_a", items)
        assert result.total == 3
        assert result.succeeded == 0
        assert result.failed == 3
        for r in result.results:
            assert r.success is False
            assert "不能相同" in r.message

    def test_clone_preserves_store_ids(self):
        """返回结果应包含正确的门店ID"""
        result = execute_clone("src_123", "tgt_456", ["kds"])
        assert result.source_store_id == "src_123"
        assert result.target_store_id == "tgt_456"

    def test_clone_empty_items(self):
        """空配置项列表应返回空结果"""
        result = execute_clone("store_a", "store_b", [])
        assert result.total == 0
        assert result.succeeded == 0
        assert result.failed == 0
        assert result.results == []

    def test_clone_mock_counts_correct(self):
        """各配置项的模拟数量应正确"""
        items = ["dishes", "payments", "tables", "marketing", "kds", "roles"]
        result = execute_clone("s1", "s2", items)
        counts = {r.item: r.count for r in result.results}
        assert counts["dishes"] == 56
        assert counts["payments"] == 4
        assert counts["tables"] == 30
        assert counts["marketing"] == 12
        assert counts["kds"] == 3
        assert counts["roles"] == 8

    def test_clone_partial_items(self):
        """克隆部分配置项"""
        result = execute_clone("s1", "s2", ["dishes", "tables"])
        assert result.total == 2
        assert result.succeeded == 2
        item_names = [r.item for r in result.results]
        assert "dishes" in item_names
        assert "tables" in item_names
