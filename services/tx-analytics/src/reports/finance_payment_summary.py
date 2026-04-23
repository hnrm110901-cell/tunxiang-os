"""中台财务报表: 支付方式汇总（含手续费率）

按支付方式汇总收款金额和笔数，包含各渠道手续费率。
支持: 微信/支付宝/现金/银联/美团/饿了么/抖音/押金/AR清账
"""

REPORT_ID = "finance_payment_summary"
REPORT_NAME = "支付方式汇总表"
CATEGORY = "finance"

# 各支付渠道手续费率（行业标准）
FEE_RATES: dict[str, float] = {
    "wechat": 0.006,  # 微信 0.6%
    "alipay": 0.006,  # 支付宝 0.6%
    "cash": 0.0,  # 现金 0%
    "unionpay": 0.006,  # 银联 0.6%
    "meituan": 0.05,  # 美团 5% (含佣金)
    "eleme": 0.05,  # 饿了么 5% (含佣金)
    "douyin": 0.03,  # 抖音 3%
    "deposit": 0.0,  # 押金 0%
    "ar_clearing": 0.0,  # AR清账（应收账款冲抵）0%
}

SQL_TEMPLATE = """
SELECT
    COALESCE(p.payment_method, 'unknown') AS payment_method,
    COUNT(DISTINCT p.order_id) AS order_count,
    COUNT(*) AS payment_count,
    SUM(p.amount_fen) AS total_amount_fen,
    CASE WHEN SUM(p.amount_fen) > 0
         THEN ROUND(SUM(p.amount_fen)::NUMERIC
                     / (SELECT COALESCE(SUM(pp.amount_fen), 1)
                        FROM payments pp
                        JOIN orders oo ON oo.id = pp.order_id AND oo.tenant_id = pp.tenant_id
                        WHERE pp.tenant_id = :tenant_id
                          AND pp.is_deleted = FALSE
                          AND pp.status = 'success'
                          AND oo.status = 'paid'
                          AND COALESCE(oo.biz_date, DATE(oo.created_at))
                              BETWEEN :start_date AND :end_date
                          AND (:store_id IS NULL OR oo.store_id = :store_id::UUID))
                     * 100, 2)
         ELSE 0
    END AS amount_pct
FROM payments p
JOIN orders o ON o.id = p.order_id AND o.tenant_id = p.tenant_id
WHERE p.tenant_id = :tenant_id
  AND p.is_deleted = FALSE
  AND p.status = 'success'
  AND o.status = 'paid'
  AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :end_date
  AND (:store_id IS NULL OR o.store_id = :store_id::UUID)
GROUP BY COALESCE(p.payment_method, 'unknown')
ORDER BY total_amount_fen DESC
"""

DIMENSIONS = ["payment_method"]
METRICS = ["order_count", "payment_count", "total_amount_fen", "amount_pct"]
FILTERS = ["start_date", "end_date", "store_id"]


def enrich_with_fee(rows: list[dict]) -> list[dict]:
    """为查询结果追加手续费率和手续费金额

    Args:
        rows: SQL查询返回的行列表

    Returns:
        追加 fee_rate / fee_fen / net_amount_fen 的行列表
    """
    enriched = []
    for row in rows:
        method = row.get("payment_method", "unknown")
        amount_fen = row.get("total_amount_fen", 0)
        fee_rate = FEE_RATES.get(method, 0.0)
        fee_fen = int(amount_fen * fee_rate)
        net_amount_fen = amount_fen - fee_fen

        enriched.append(
            {
                **row,
                "fee_rate": fee_rate,
                "fee_fen": fee_fen,
                "net_amount_fen": net_amount_fen,
            }
        )

    return enriched
