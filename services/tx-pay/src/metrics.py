"""tx-pay Prometheus 指标定义。

审计 OPS / 独立 review P5：infra/monitoring 已挂 PaymentChannelHighErrorRate
告警规则（消费 payment_channel_requests_total{channel, status}），但该 metric
未被任何服务暴露 —— 告警永不触发，Tier 1 "支付成功率 > 99.9%" SLO 在监控
上是黑屏的。

main.py 已挂 prometheus_fastapi_instrumentator，本模块只需 import 即注册到
默认 registry，/metrics 端点会自动暴露。

跨服务边界：
  - 本模块只覆盖 tx-pay 拥有的"渠道维度" payment_channel_requests_total
  - tx-trade/services/payment_saga_service 拥有"流程维度" payment_saga_total
  - 两者 label 不同维度，互不替代

label 值约定（低基数，合规 Prometheus best practice）：
  channel: wechat | alipay | lakala | shouqianba | stored_value | cash
  status:  2xx | 4xx | 5xx | timeout | connect_error
"""

from __future__ import annotations

from prometheus_client import Counter

# 支付渠道 HTTP 请求计数（按渠道 + 响应状态分维）
# 告警规则消费方：
#   - tunxiang-alerts PaymentChannelHighErrorRate
#     sum by (channel) (rate(...{status="5xx"}[5m]))
#       / sum by (channel) (rate(...[5m])) > 0.01
payment_channel_requests_total = Counter(
    "payment_channel_requests_total",
    "支付渠道 HTTP 请求计数（按渠道 + 响应状态分维）",
    ["channel", "status"],
)
