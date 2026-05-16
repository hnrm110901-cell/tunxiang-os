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

from typing import Any, Final

# Tier 1 CI minimal deps trap (feedback_tier1_ci_minimal_deps_trap.md):
# tier1-gate workflow 只装 ~10 包，prometheus_client 不在内。生产 / staging
# 通过 prometheus-fastapi-instrumentator transitive 装；Tier 1 CI 走 fail-open
# stub 而非扩 workflow（与 PR #227 round-3 metrics.py 同模式）。
try:
    from prometheus_client import Counter  # type: ignore[import-not-found]

    _PROMETHEUS_AVAILABLE = True
except ImportError:  # pragma: no cover — CI Tier 1 minimal deps 路径
    _PROMETHEUS_AVAILABLE = False

    class _NoOpChild:
        """Counter().labels(...) 返回的 child 的 no-op 替身.

        生产路径 prometheus_client 真接 in；只有 Tier 1 minimal-deps CI 走此分支。
        """

        def inc(self, amount: float = 1.0) -> None:  # noqa: D401
            return None

    class _NoOpCounter:
        """prometheus_client.Counter 的 no-op 替身（fail-open）.

        保留 API 表面 (.labels / .collect) 让 metrics 调用方代码无需 branch。
        """

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            return None

        def labels(self, **_kwargs: Any) -> _NoOpChild:
            return _NoOpChild()

        def collect(self) -> list[Any]:
            return []

    Counter = _NoOpCounter  # type: ignore[assignment, misc]

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


# ─────────────────────────────────────────────────────────────────────────────
# silent failure 治理 Wave 1 sub-A (issue #663): tx-supply 业务 silent fallback
# ─────────────────────────────────────────────────────────────────────────────
# 设计参照 doc_number_fallback 同模式 (PR #586 §19 / issue #592)，复用 fail-open
# 契约 + Tier 1 CI minimal deps no-op stub。
#
# 4 个 (b)/(c) site (Plan §2 表 #3/#6/#7/#8/#9) 共用此 counter，以 `site` label
# 区分 callsite — 与 doc_number 用 (service, doc_type) 双 label 同模式，
# cardinality 封闭：5 个固定 site 字符串。
#
# Site 枚举（plan §2 表）:
#   smart_procurement.supplier_history  — 供应商最近供货查询 (Tier 1 邻接, 触毛利)
#   expiry_monitor.parse_notes          — 批次效期解析 (Tier 1 邻接, 食安)
#   theoretical_cost.get_current_bom    — BOM 查询 (毛利辅助)
#   actual_cost.last_purchase           — 实际采购价查询 (毛利辅助)
#   actual_cost.ledger_price            — 台账价查询 (毛利辅助)
silent_fallback_total: Final[Counter] = Counter(
    "tx_supply_silent_fallback_total",
    "tx-supply 业务 silent fallback 落 None 次数 (issue #663 Wave 1 sub-A)",
    ["site"],
)


def record_silent_fallback(site: str) -> None:
    """记录一次 tx-supply silent fallback (fail-open).

    fail-open 契约：metrics 写入不能 raise，绝不阻塞 Tier 1 业务路径
    （毛利底线 / 食安合规 / 客户体验）。本 fn 在 graceful degradation
    except arm 内调用，必须吞掉自身任何异常。

    Args:
        site: callsite 标识（plan §2 site 枚举 — smart_procurement.supplier_history /
              expiry_monitor.parse_notes / theoretical_cost.get_current_bom /
              actual_cost.last_purchase / actual_cost.ledger_price）
    """
    try:
        silent_fallback_total.labels(site=site).inc()
    except Exception:  # noqa: BLE001 — metrics 写入失败不能阻塞 Tier 1 业务
        # prometheus_client 内部已保证不 raise，此处兜底防注册表损坏等极端场景
        pass
