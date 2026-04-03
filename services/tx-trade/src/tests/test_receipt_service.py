"""小票打印服务测试"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from services.receipt_service import ReceiptService


def _sample_order():
    return {
        "order_no": "TX202603221430001A",
        "table_number": "A03",
        "order_time": "2026-03-22T14:30:00+08:00",
        "total_amount_fen": 16800,
        "discount_amount_fen": 1000,
        "final_amount_fen": 15800,
        "items": [
            {"item_name": "剁椒鱼头", "quantity": 1, "subtotal_fen": 8800, "kitchen_station": "热菜档", "notes": "少辣"},
            {"item_name": "农家小炒肉", "quantity": 1, "subtotal_fen": 4200, "kitchen_station": "热菜档", "notes": ""},
            {"item_name": "凉拌黄瓜", "quantity": 2, "subtotal_fen": 1800, "kitchen_station": "凉菜档", "notes": ""},
            {"item_name": "米饭", "quantity": 3, "subtotal_fen": 2000, "kitchen_station": None, "notes": ""},
        ],
    }


class TestFormatReceipt:
    def test_generates_bytes(self):
        result = ReceiptService.format_receipt(_sample_order(), store_name="尝在一起")
        assert isinstance(result, bytes)
        assert len(result) > 100

    def test_contains_store_name(self):
        result = ReceiptService.format_receipt(_sample_order(), store_name="尝在一起")
        assert "尝在一起".encode("gbk") in result

    def test_contains_order_no(self):
        result = ReceiptService.format_receipt(_sample_order())
        assert b"TX2026" in result

    def test_contains_cut_command(self):
        result = ReceiptService.format_receipt(_sample_order())
        assert b'\x1d\x56\x00' in result  # GS V 0 = cut

    def test_58mm_and_80mm_differ(self):
        r58 = ReceiptService.format_receipt(_sample_order(), paper_width=58)
        r80 = ReceiptService.format_receipt(_sample_order(), paper_width=80)
        assert r58 != r80


class TestKitchenOrder:
    def test_generates_bytes(self):
        result = ReceiptService.format_kitchen_order(_sample_order(), station="热菜档")
        assert isinstance(result, bytes)
        assert "热菜档".encode("gbk") in result

    def test_contains_table_number(self):
        result = ReceiptService.format_kitchen_order(_sample_order(), station="热菜档")
        assert b"A03" in result


class TestSplitByStation:
    def test_splits_correctly(self):
        stations = ReceiptService.split_by_station(_sample_order())
        assert "热菜档" in stations
        assert len(stations["热菜档"]) == 2
        assert "凉菜档" in stations
        assert len(stations["凉菜档"]) == 1
        assert "default" in stations
        assert len(stations["default"]) == 1


class TestContentHash:
    def test_same_content_same_hash(self):
        content = b"test content"
        assert ReceiptService.content_hash(content) == ReceiptService.content_hash(content)

    def test_different_content_different_hash(self):
        assert ReceiptService.content_hash(b"a") != ReceiptService.content_hash(b"b")

    def test_hash_length(self):
        assert len(ReceiptService.content_hash(b"test")) == 16
