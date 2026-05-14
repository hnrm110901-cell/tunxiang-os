"""Tier 1 邻接测试：doc_number infra fallback counter wiring + admin API.

issue #592 / PR-03D / PR #586 §19 round-2 follow-up.

为什么 *tier1* 后缀（触发 tier1-gate）:
  - 6 catch 现场位于 inventory_io / receiving_v2 / stocktake / purchase_order
    Tier 1 邻接路径（毛利底线 + 食安 + 资金链路）。fallback wiring 漏 inc
    会让运维告警失效，与 audit doc §4.3 同类风险（无可观测性下静默漂移）。
  - 直接 grep 源码模式 + Counter 行为单元测试，不依赖真 PG
    （参考 PR #595 raw SQL audit + PR-A/B/C row-lock 同方法学）。

测试范围:
  1. 6 个 callsite 都存在 record_doc_number_fallback 调用（源码 regex audit）
  2. record_doc_number_fallback 调用必须在 `except Exception` 兜底 arm
     （DocNumberError 不计数 — 避免预期 sentinel 触发告警噪音）
  3. record_doc_number_fallback inc() 正确 + 异常吞掉（fail-open 契约）
  4. doc-number-admin endpoint 返回结构正确
  5. admin gate 拒绝缺失 / 错误 X-Internal-Role；允许 admin/ops（大小写不敏感）
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ── 路径 ───────────────────────────────────────────────────────────────────────
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SRC_DIR = Path(__file__).resolve().parent.parent / "src"


# ── 1. 6 catch 现场都有 record_doc_number_fallback ─────────────────────────────


# (相对 src 路径, service 标签, doc_type 标签)
_EXPECTED_CALLSITES = [
    ("services/inventory_io.py", "inventory_io", "inventory_io"),
    ("services/inventory_io.py", "inventory_io", "waste"),
    ("services/inventory_io.py", "inventory_io", "adjustment"),
    ("services/receiving_v2_service.py", "receiving_v2", "receiving"),
    ("services/stocktake_service.py", "stocktake", "stocktake"),
    ("api/purchase_order_routes.py", "purchase_order", "purchase_order"),
]


def test_six_callsites_all_record_fallback() -> None:
    """6 catch 现场（issue #592）都有 record_doc_number_fallback 调用.

    防 future regression: 新加 catch site 漏 inc / 重构改了 service 标签拼写错.
    """
    for rel_path, service, doc_type in _EXPECTED_CALLSITES:
        full = SRC_DIR / rel_path
        text = full.read_text(encoding="utf-8")
        pattern = (
            rf'record_doc_number_fallback\(\s*service\s*=\s*"{re.escape(service)}"\s*,'
            rf'\s*doc_type\s*=\s*"{re.escape(doc_type)}"\s*\)'
        )
        assert re.search(pattern, text), (
            f"{rel_path} 缺 record_doc_number_fallback("
            f'service="{service}", doc_type="{doc_type}") 调用'
        )


def test_callsite_only_in_bare_except_arm() -> None:
    """record_doc_number_fallback 调用必须在 `except Exception` 兜底 arm 内.

    DocNumberError arm（预期 sentinel — 模板未配置等）不应计数，避免告警噪音
    （PagerDuty 误触发）。

    检查方式: 从 record 调用行向上回溯找最近的 `except` 子句行
    （`except DocNumberError` / `except Exception` / `except (...)` 三选一），
    必须是 `except Exception`. 不依赖固定行距 / 前一行字面匹配（fragile）.
    """
    except_clause_re = re.compile(r"^\s*except\s+\S")
    for rel_path, _, doc_type in _EXPECTED_CALLSITES:
        full = SRC_DIR / rel_path
        lines = full.read_text(encoding="utf-8").splitlines()
        record_indices = [
            i
            for i, line in enumerate(lines)
            if "record_doc_number_fallback" in line and f'doc_type="{doc_type}"' in line
        ]
        assert record_indices, f"{rel_path}/{doc_type} 无 record 调用"
        for idx in record_indices:
            # 向上回溯找最近的 except 子句
            nearest_except = None
            for j in range(idx - 1, max(-1, idx - 10), -1):
                if except_clause_re.match(lines[j]):
                    nearest_except = lines[j].strip()
                    break
            assert nearest_except is not None, (
                f"{rel_path}:{idx + 1} record({doc_type}) "
                f"上方 10 行内未找到 except 子句 — 结构反常"
            )
            assert "except Exception" in nearest_except, (
                f"{rel_path}:{idx + 1} record({doc_type}) 挂在 `{nearest_except}` arm 而非 "
                f"`except Exception` 兜底 arm — 预期 sentinel 不应计入 fallback 计数"
            )


# ── 2. record_doc_number_fallback 行为 ─────────────────────────────────────────


def _snapshot_for(metrics_module, service: str, doc_type: str) -> float:
    """通过公开 collect() API 读 (service, doc_type) 当前值 — 不碰私属性."""
    for mf in metrics_module.doc_number_fallback_null_total.collect():
        for sample in mf.samples:
            if not sample.name.endswith("_total"):
                continue
            if (
                sample.labels.get("service") == service
                and sample.labels.get("doc_type") == doc_type
            ):
                return float(sample.value)
    return 0.0


def test_record_fallback_increments_counter() -> None:
    """record_doc_number_fallback 写入 Counter 后 collect() 公开 API 可见 +1."""
    from services.tx_supply.src import metrics

    before = _snapshot_for(metrics, "test_svc_unique_1", "test_type_unique_1")
    metrics.record_doc_number_fallback(
        service="test_svc_unique_1", doc_type="test_type_unique_1"
    )
    after = _snapshot_for(metrics, "test_svc_unique_1", "test_type_unique_1")
    assert after == before + 1


def test_record_fallback_is_fail_open() -> None:
    """record_doc_number_fallback 内部异常必须吞掉 (fail-open contract).

    若 inc 失败导致 raise → graceful degradation 反而劈了 Tier 1 业务,
    违反 feedback_graceful_degradation_pattern.md 契约.
    """
    from services.tx_supply.src import metrics

    with patch.object(
        metrics.doc_number_fallback_null_total,
        "labels",
        side_effect=RuntimeError("simulated registry corruption"),
    ):
        # 必须不 raise
        metrics.record_doc_number_fallback(service="x", doc_type="y")


# ── 3. admin API endpoint ─────────────────────────────────────────────────────


@pytest.fixture
def client():
    """构造 minimal FastAPI app 只挂 doc_number_admin_router.

    避免 main.py 拖全 tx-supply 依赖；参考 PR #608 sub-PR C / PR #602
    minimal-app endpoint-level test 模式。
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from services.tx_supply.src.api.doc_number_admin_routes import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_fallback_stats_returns_structure(client) -> None:
    """endpoint 返回 ok=True + by_service/by_doc_type/by_combo + total."""
    from services.tx_supply.src import metrics

    # 先 inc 一次以保证至少 1 个 sample（用本测试独有 label 避免污染）
    metrics.record_doc_number_fallback(
        service="inventory_io", doc_type="waste"
    )

    resp = client.get(
        "/api/v1/doc-number/fallback-stats", headers={"X-Internal-Role": "admin"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert "total" in data
    assert "by_service" in data
    assert "by_doc_type" in data
    assert "by_combo" in data
    assert "note" in data
    assert data["total"] >= 1.0
    # by_combo 排序: 按 (service, doc_type)
    combos = data["by_combo"]
    if len(combos) >= 2:
        for prev, curr in zip(combos, combos[1:]):
            assert (prev["service"], prev["doc_type"]) <= (
                curr["service"],
                curr["doc_type"],
            )


def test_fallback_stats_rejects_missing_role(client) -> None:
    """缺 X-Internal-Role header 返回 403 (cross-tenant 暴露需 admin)."""
    resp = client.get("/api/v1/doc-number/fallback-stats")
    assert resp.status_code == 403


def test_fallback_stats_rejects_wrong_role(client) -> None:
    """普通 cashier/store 角色拒绝 (跨租户聚合数据保护)."""
    for role in ["cashier", "store", "kitchen", "guest", "manager"]:
        resp = client.get(
            "/api/v1/doc-number/fallback-stats", headers={"X-Internal-Role": role}
        )
        assert resp.status_code == 403, (
            f"role={role!r} 应拒绝, 实际 {resp.status_code}"
        )


def test_fallback_stats_accepts_admin_case_insensitive(client) -> None:
    """admin/ADMIN/Admin/ops/OPS/Ops 都允许 (header 大小写不敏感 + 剥空格)."""
    for role in ["admin", "ADMIN", "Admin", " admin ", "ops", "OPS", " ops "]:
        resp = client.get(
            "/api/v1/doc-number/fallback-stats", headers={"X-Internal-Role": role}
        )
        assert resp.status_code == 200, f"role={role!r} 应允许"
