"""自动凭证生成服务 (C6)

日结汇总 → 自动生成会计凭证 → 推送金蝶

凭证映射规则：
  借：银行存款（微信/支付宝/银联到账）
  借：现金（现金收入）
  借：应收账款（挂账）
  贷：主营业务收入（菜品收入）
  贷：其他业务收入（服务费/茶位费）
"""

from datetime import date

# 科目映射
ACCOUNT_MAPPING = {
    # 借方
    "cash": {"code": "1001", "name": "库存现金"},
    "wechat": {"code": "1002.01", "name": "银行存款-微信"},
    "alipay": {"code": "1002.02", "name": "银行存款-支付宝"},
    "unionpay": {"code": "1002.03", "name": "银行存款-银联"},
    "credit_account": {"code": "1122", "name": "应收账款"},
    "member_balance": {"code": "2204", "name": "预收账款-储值卡"},
    # 贷方
    "food_revenue": {"code": "6001", "name": "主营业务收入-餐饮"},
    "service_fee": {"code": "6051", "name": "其他业务收入-服务费"},
    "discount": {"code": "6001.99", "name": "主营业务收入-折扣抵减"},
    "refund": {"code": "6001.98", "name": "主营业务收入-退款抵减"},
}


def generate_voucher_from_settlement(settlement: dict, store_name: str = "") -> dict:
    """从日结数据自动生成凭证

    Args:
        settlement: 日结汇总数据（Settlement 模型的 dict）
            含 cash_fen, wechat_fen, alipay_fen, unionpay_fen, credit_fen,
            member_balance_fen, total_revenue_fen, total_discount_fen, total_refund_fen
    """
    voucher_date = settlement.get("settlement_date", str(date.today()))
    entries = []

    # 借方：按支付方式分录
    payment_fields = [
        ("cash_fen", "cash"),
        ("wechat_fen", "wechat"),
        ("alipay_fen", "alipay"),
        ("unionpay_fen", "unionpay"),
        ("credit_fen", "credit_account"),
        ("member_balance_fen", "member_balance"),
    ]

    for field, account_key in payment_fields:
        amount_fen = settlement.get(field, 0)
        if amount_fen > 0:
            account = ACCOUNT_MAPPING[account_key]
            entries.append(
                {
                    "direction": "debit",
                    "account_code": account["code"],
                    "account_name": account["name"],
                    "amount_fen": amount_fen,
                    "amount_yuan": round(amount_fen / 100, 2),
                    "summary": f"{store_name}{voucher_date}收入",
                }
            )

    # 贷方：营业收入
    net_revenue = settlement.get("net_revenue_fen", 0)
    if net_revenue > 0:
        entries.append(
            {
                "direction": "credit",
                "account_code": ACCOUNT_MAPPING["food_revenue"]["code"],
                "account_name": ACCOUNT_MAPPING["food_revenue"]["name"],
                "amount_fen": net_revenue,
                "amount_yuan": round(net_revenue / 100, 2),
                "summary": f"{store_name}{voucher_date}营业收入",
            }
        )

    # 折扣抵减
    discount_fen = settlement.get("total_discount_fen", 0)
    if discount_fen > 0:
        entries.append(
            {
                "direction": "credit",
                "account_code": ACCOUNT_MAPPING["discount"]["code"],
                "account_name": ACCOUNT_MAPPING["discount"]["name"],
                "amount_fen": -discount_fen,
                "amount_yuan": -round(discount_fen / 100, 2),
                "summary": f"{store_name}{voucher_date}折扣",
            }
        )

    # 验证借贷平衡
    debit_total = sum(e["amount_fen"] for e in entries if e["direction"] == "debit")
    credit_total = sum(abs(e["amount_fen"]) for e in entries if e["direction"] == "credit")

    return {
        "voucher_date": voucher_date,
        "voucher_type": "收",
        "store_name": store_name,
        "entries": entries,
        "debit_total_fen": debit_total,
        "credit_total_fen": credit_total,
        "is_balanced": debit_total == credit_total,
        "entry_count": len(entries),
    }


def format_for_kingdee(voucher: dict) -> dict:
    """格式化为金蝶凭证接口格式"""
    return {
        "FDate": voucher["voucher_date"],
        "FVoucherGroupId": {"FNumber": "PRE001"},
        "FSourceBillKey": "78cca82c-d5ea-4927-b844-8c1b7e9b3772",
        "FVOUCHERGROUPNO": voucher["voucher_type"],
        "FEntity": [
            {
                "FEXPLANATION": e["summary"],
                "FACCOUNTID": {"FNumber": e["account_code"]},
                "FDEBIT" if e["direction"] == "debit" else "FCREDIT": e["amount_yuan"],
            }
            for e in voucher["entries"]
        ],
    }
