"""tx-org Prometheus 指标定义

issue #703（PR #695 §19 round-2 follow-up #5）:
  attendance_compliance_service._parse_location_payload 返 None 后 caller
  silent continue 跳过 GPS 校验 — 员工故意输入垃圾 GPS payload (CSV/JSON
  格式错 / 非法字符) 可绕过出勤合规审查 (违规打卡不在排班点也能通过)。
  函数纯逻辑 (无 tenant / employee context), log + metric 加在 caller-side。

设计:
  - 计数 caller "parsed is None continue" 路径 — 真"员工 GPS payload 异常"信号
  - labels: tenant_id × employee_id (cardinality 受租户 + 员工数限制,
    用于 Grafana 按租户聚合 / 按员工告警异常打卡)
  - record fn 必须 fail-open (counter.inc() 内部 prometheus_client 保证不
    raise, 但外层 try/except 仍兜一层防 wheel 损坏 / 注册表损坏极端场景,
    与 tx-supply metrics.py / issue #580 graceful degradation 契约一致)

经批准的 fail-open silent 模式 (silent_failure 治理 scope 外):
  - record_attendance_location_parse_failed() 内 `except Exception: pass` —
    PR #695 §19 round-2 批准 (issue #703, 镜像 tx-supply record_doc_number_fallback
    + record_silent_fallback 同模式)
  本 site 为"metrics 写入兜底防注册表损坏"白名单, 不计入 silent_failure_count 治理 scope
  (与"业务路径 silent"不同 — 此为合规扫描保护层 fail-open 契约,
  与 tx-supply metrics.py 完全镜像)
"""

from __future__ import annotations

from typing import Any, Final

# Tier 1 CI minimal deps trap (feedback_tier1_ci_minimal_deps_trap.md):
# tier1-gate workflow 只装 ~10 包，prometheus_client 不在内。生产 / staging
# 通过 prometheus-fastapi-instrumentator transitive 装；CI 走 fail-open
# stub 而非扩 workflow（与 tx-supply / PR #227 round-3 metrics.py 同模式）。
try:
    from prometheus_client import Counter  # type: ignore[import-not-found]

    _PROMETHEUS_AVAILABLE = True
except ImportError:  # pragma: no cover — CI minimal deps 路径
    _PROMETHEUS_AVAILABLE = False

    class _NoOpChild:
        """Counter().labels(...) 返回的 child 的 no-op 替身.

        生产路径 prometheus_client 真接 in；只有 minimal-deps CI 走此分支。
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


# attendance_compliance_service.scan_all_compliance GPS 校验 caller-side
# (services/tx-org/src/services/attendance_compliance_service.py L589-592).
# 员工故意垃圾 GPS payload (issue #703) -> _parse_location_payload returns
# None -> 当前 silent continue. 加 counter 让运维可视化告警异常员工。
attendance_location_parse_failed_total: Final[Counter] = Counter(
    "tx_org_attendance_location_parse_failed_total",
    "Attendance location payload parse failures (potential employee GPS spoofing) (issue #703)",
    ["tenant_id", "employee_id"],
)


def record_attendance_location_parse_failed(tenant_id: str, employee_id: str) -> None:
    """记录一次出勤 GPS payload 解析失败 (fail-open).

    fail-open 契约：metrics 写入不能 raise，绝不阻塞合规扫描流程
    (虽非 Tier 1, 但合规扫描批跑也不能因 metrics infra 异常中断)。
    本 fn 在 caller "parsed is None continue" 路径调用, 必须吞掉自身任何异常。

    Args:
        tenant_id: 租户 ID (来自 scan_all_compliance 函数参数)
        employee_id: 员工 ID (来自 clock_records.employee_id, 缺失时调用方
                     应传 "unknown")
    """
    try:
        attendance_location_parse_failed_total.labels(
            tenant_id=tenant_id, employee_id=employee_id
        ).inc()
    except Exception:  # noqa: BLE001 — metrics 写入失败不能阻塞合规扫描
        # prometheus_client 内部已保证不 raise，此处兜底防注册表损坏等极端场景
        pass
