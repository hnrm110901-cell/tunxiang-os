"""Wave 5 silent failures observability — tx-org sample tests

Covers the 1 tx-org silent site status:
  1. metrics.py:87 except Exception → pass — APPROVED whitelist (PR #695 §19 round-2 / issue #703)

Wave 5 changes:
  - metrics.py site: 不动 (continue 沿用 Wave 4 PR-3 #695 批准, 镜像 tx-supply metrics.py 同模式)
  - metrics.py module docstring 加 "经批准的 fail-open silent 模式" 段, audit trail 显式声明
    白名单 (与 tx-supply metrics.py 镜像), 不计入 silent_failure_count 治理 scope

PR pattern (Wave 4 PR-4 #697 cross-svc batch mirror; Wave 1 sub-D PR #752 individual-svc mirror).
"""
from __future__ import annotations

import pytest

# ── Test 1: metrics.py 白名单 fail-open 契约 (record_attendance_location_parse_failed) ─


def test_record_attendance_location_parse_failed_swallows_counter_error():
    """metrics.py:87 — record_attendance_location_parse_failed 内 except Exception: pass 白名单.

    fail-open 契约 (PR #695 §19 round-2 批准, issue #703):
    Prometheus counter.labels(...).inc() 内部异常不可阻塞合规扫描批跑.
    本 fn 在 caller "parsed is None continue" 路径调用, 必须吞自身任何异常.

    虽非 Tier 1, 但合规扫描批跑是日级任务, 单 metrics infra 异常不应中断整轮扫描
    (员工 GPS 校验 1k 数量级, 中断会漏校验后续员工).

    silent_failure 治理 scope 外 — 白名单已在 metrics.py module docstring (Wave 5
    新增 "经批准的 fail-open silent 模式" 段) 记录, 与 tx-supply metrics.py 完全镜像.
    """
    class _BrokenCounter:
        def labels(self, **_kwargs):
            raise RuntimeError("prometheus registry corrupted")

    def _record_under_test(counter, tenant_id: str, employee_id: str) -> None:
        try:
            counter.labels(tenant_id=tenant_id, employee_id=employee_id).inc()
        except Exception:  # noqa: BLE001 — 经批准的白名单, 同 metrics.py:87
            pass

    # 调用必须不抛 — fail-open 契约
    try:
        _record_under_test(_BrokenCounter(), "tenant_a", "emp_42")
    except Exception as exc:
        pytest.fail(f"record_attendance_location_parse_failed 不应 raise, got: {exc}")


# ── Test 2: 白名单文档化校验 ─────────────────────────────────────────────────


def test_metrics_docstring_documents_whitelist():
    """tx-org/src/metrics.py module docstring 必须显式列出白名单 (Wave 5 新增段).

    与 tx-supply/src/metrics.py 镜像, 提供 audit trail 让后续治理 review 可定位
    哪些 silent_failure 是经批准的 fail-open 白名单 (vs 真业务 silent bug).
    """
    import services.tx_org.src.metrics as metrics_mod

    doc = metrics_mod.__doc__ or ""
    assert "经批准的 fail-open silent 模式" in doc, (
        "metrics.py docstring 必须显式记录白名单段 (Wave 5 镜像 tx-supply metrics.py)"
    )
    assert "record_attendance_location_parse_failed" in doc, (
        "白名单段必须列出具体 fn 名称"
    )
    assert "PR #695" in doc and "issue #703" in doc, (
        "白名单段必须引用批准 PR + issue"
    )
