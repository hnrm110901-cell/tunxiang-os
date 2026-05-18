"""Prometheus metrics setup 助手 (Phase C.3 #820)。

22 service 当前各自调用 `Instrumentator().instrument(app).expose(app)`。本 helper 抽出共用形态:
  - 强制 service_name 入参, caller 必须显式声明服务名 (未来加 const label / scrape label 时无需改 caller)
  - 排除 /metrics 自身路径 (常见漏配)
  - 一处改, 所有 service 升级 (eg. expose path 改 /internal/metrics, 或 expose 加 auth middleware)

迁移策略 (per #820-I follow-up):
  - PR 1 (本 PR): gateway 试点 + 单测
  - PR 2-N: 渐进逐 service 替换
"""

from __future__ import annotations

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator


def setup_metrics(app: FastAPI, service_name: str) -> Instrumentator:
    """挂入 Prometheus instrumentator 到 FastAPI app。

    Args:
        app: FastAPI 实例
        service_name: 当前服务名 (eg. "gateway", "tx-trade"), 当前未直接用,
            但是必传参数, 未来加 const label / scrape label 时无需改 caller。

    Returns:
        已 instrument + expose 的 Instrumentator 对象。
    """
    if not service_name:
        raise ValueError("service_name 必传 (用于 Prometheus 标签 + 未来扩展)")

    instrumentator = Instrumentator(excluded_handlers=["/metrics"])
    instrumentator.instrument(app)
    instrumentator.expose(app, endpoint="/metrics", include_in_schema=False)
    return instrumentator
