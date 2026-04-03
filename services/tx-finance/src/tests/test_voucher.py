"""自动凭证生成测试"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.voucher_service import format_for_kingdee, generate_voucher_from_settlement


class TestVoucherGeneration:
    def test_basic_settlement(self):
        settlement = {
            "settlement_date": "2026-03-23",
            "cash_fen": 125000,
            "wechat_fen": 480000,
            "alipay_fen": 210000,
            "unionpay_fen": 41000,
            "credit_fen": 0,
            "member_balance_fen": 0,
            "net_revenue_fen": 856000,
            "total_discount_fen": 0,
            "total_refund_fen": 0,
        }
        voucher = generate_voucher_from_settlement(settlement, "芙蓉路店")
        assert voucher["is_balanced"]
        assert voucher["entry_count"] >= 4  # 现金+微信+支付宝+银联 借方 + 收入贷方
        assert voucher["debit_total_fen"] == voucher["credit_total_fen"]

    def test_with_discount(self):
        settlement = {
            "settlement_date": "2026-03-23",
            "cash_fen": 100000,
            "wechat_fen": 0, "alipay_fen": 0, "unionpay_fen": 0,
            "credit_fen": 0, "member_balance_fen": 0,
            "net_revenue_fen": 100000,
            "total_discount_fen": 10000,
            "total_refund_fen": 0,
        }
        voucher = generate_voucher_from_settlement(settlement)
        discount_entries = [e for e in voucher["entries"] if "折扣" in e.get("summary", "")]
        assert len(discount_entries) == 1

    def test_kingdee_format(self):
        settlement = {
            "settlement_date": "2026-03-23",
            "cash_fen": 50000,
            "wechat_fen": 0, "alipay_fen": 0, "unionpay_fen": 0,
            "credit_fen": 0, "member_balance_fen": 0,
            "net_revenue_fen": 50000,
            "total_discount_fen": 0, "total_refund_fen": 0,
        }
        voucher = generate_voucher_from_settlement(settlement)
        kingdee = format_for_kingdee(voucher)
        assert "FDate" in kingdee
        assert "FEntity" in kingdee
        assert len(kingdee["FEntity"]) >= 2
