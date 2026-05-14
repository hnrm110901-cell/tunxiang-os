"""tx-supply Prometheus 指标定义

issue #592（PR #586 §19 round-2 follow-up）:
  doc_number 生成失败 graceful degradation (issue #580 同模式) 之前
  仅 structlog warn level — 运维侧无主动告警机制，徐记 5/15 凌晨
  PG 主从切换早高峰 200 单批量 doc_number=NULL 才人工发现的场景需可观测性。

设计:
  - 仅 `except Exception`（BLE001 兜底）路径计数 — 真"infra 异常"信号
    DocNumberError 是预期 sentinel（模板未配置等），不计入告警
  - labels: service(callsite 模块名) × doc_type（gen_doc_number 传参）
    封闭枚举，cardinality ≤ 6 个序列（issue #592 列出的 4 文件 6 catch 块），
    无 tenant_id 标签防爆炸（运维聚合视角，按租户拆分通过 Grafana 转 PromQL）
  - record fn 必须 fail-open（counter.inc() 内部 prometheus_client 保证不 raise，
    但外层 try/except 仍兜一层防 wheel 损坏 / 注册表损坏极端场景，与 issue #580
    graceful degradation 契约一致）
"""

from __future__ import annotations

from typing import Final

from prometheus_client import Counter

# 6 catch 现场命中（PR #586 §19 round-2 / issue #592）:
#   inventory_io.receive_stock          (service=inventory_io, doc_type=inventory_io)
#   inventory_io.issue_stock (waste 路径) (service=inventory_io, doc_type=waste)
#   inventory_io.adjust_stock           (service=inventory_io, doc_type=adjustment)
#   receiving_v2_service.create_receiving_order (service=receiving_v2, doc_type=receiving)
#   stocktake_service.create_stocktake  (service=stocktake,   doc_type=stocktake)
#   purchase_order_routes.create_purchase_order (service=purchase_order, doc_type=purchase_order)
doc_number_fallback_null_total: Final[Counter] = Counter(
    "tx_supply_doc_number_fallback_null_count",
    "doc_number infra 异常 graceful degradation 落 NULL 次数 (PR #586 §19 / issue #592)",
    ["service", "doc_type"],
)


def record_doc_number_fallback(service: str, doc_type: str) -> None:
    """记录一次 doc_number infra fallback (fail-open).

    fail-open 契约：metrics 写入不能 raise，绝不阻塞 Tier 1 业务路径
    （毛利底线 / 食安合规 / 客户体验）。本 fn 在 graceful degradation
    `except Exception` arm 内调用，必须吞掉自身任何异常。

    Args:
        service: callsite 模块名（inventory_io / receiving_v2 / stocktake / purchase_order）
        doc_type: gen_doc_number 传入的 doc_type（inventory_io / waste / adjustment /
                  receiving / stocktake / purchase_order）
    """
    try:
        doc_number_fallback_null_total.labels(service=service, doc_type=doc_type).inc()
    except Exception:  # noqa: BLE001 — metrics 写入失败不能阻塞 Tier 1 业务
        # prometheus_client 内部已保证不 raise，此处兜底防注册表损坏等极端场景
        pass
