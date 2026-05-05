"""tx-trade Prometheus 指标定义。

审计 OPS-002 + 独立 review P1-3：tunxiang-payment-slo 告警规则需要这些 Counter
被实际暴露，否则 Prometheus 告警永不触发，Tier 1"支付成功率 > 99.9%"
SLO 在监控上是黑屏的。

main.py 已挂 prometheus_fastapi_instrumentator，本模块只需 import 即注册到
默认 registry，/metrics 端点会自动暴露。

跨服务的指标（如 tx-pay 各渠道的 payment_channel_requests_total）由各服务
自己定义，本模块只覆盖 tx-trade 拥有的支付 Saga 维度。
"""

from __future__ import annotations

from prometheus_client import Counter

# 支付 Saga 总计数（按最终结果维度）
# 告警规则消费方：
#   - tunxiang-payment-slo PaymentSuccessRateLow
#     (sum result=success / sum total) < 0.999
#   - tunxiang-payment-slo PaymentTrafficStalled
#     sum rate(payment_saga_total[5m]) == 0 → 业务时段假死告警
payment_saga_total = Counter(
    "payment_saga_total",
    "支付 Saga 流程总数，按最终状态分维",
    ["result"],  # "success" | "failed" | "compensated"
)

# 支付 Saga 补偿计数（按补偿原因维度）
# 告警规则消费方：
#   - tunxiang-payment-slo PaymentSagaCompensationSpike
#     rate(payment_saga_compensated_total[5m]) > 0.05 持续 3m
payment_saga_compensated_total = Counter(
    "payment_saga_compensated_total",
    "支付 Saga 补偿（退款）计数，按原因分维",
    ["reason"],  # 见 payment_saga_service.compensate() 的 reason 字符串
)
