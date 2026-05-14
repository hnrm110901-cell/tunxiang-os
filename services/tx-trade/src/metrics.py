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

# PR #227 round-2 fix：CI Tier 1 test runner 不装 requirements.txt（仅
# pytest/pytest-asyncio/pydantic/fastapi/httpx/sqlalchemy/structlog/asyncpg/
# pyyaml/aiosqlite/cryptography），但 prometheus_client 是 metrics 真依赖
# （prod 通过 prometheus-fastapi-instrumentator transitive 引入）。Tier 1
# tests import payment_saga_service → metrics 链路触发 ModuleNotFoundError，
# 导致 12 个 payment_saga tier1 测试集体 fail。
#
# 应用 graceful degradation pattern（feedback_graceful_degradation_pattern.md）：
# observability 是辅助层，fail-open 不阻塞业务。test runtime 用 no-op stub，
# prod runtime 用真 Counter — 监控 SLO 由 prometheus-fastapi-instrumentator
# 在 main.py 启动时挂载。
try:
    from prometheus_client import Counter
except ImportError:  # pragma: no cover — CI Tier 1 fallback
    class Counter:  # type: ignore[no-redef]
        """no-op stub for environments without prometheus_client。"""

        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def labels(self, *args: object, **kwargs: object) -> "Counter":
            return self

        def inc(self, *args: object, **kwargs: object) -> None:
            pass

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
