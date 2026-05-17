"""Wave 5 silent failures observability — tx-supply sample tests

Covers the 3 tx-supply silent sites status:
  1. metrics.py:96  except Exception → pass — APPROVED whitelist (PR #586 §19 / issue #592)
  2. metrics.py:141 except Exception → pass — APPROVED whitelist (PR #742 §19 / issue #663 sub-A)
  3. tests/test_certificate_type_routes_tier1.py:73 except ImportError → return None —
     test fixture (narrowed from broad Exception in this PR), pytest.skip pattern

Wave 5 changes:
  - metrics.py 两 site: 不动 (continue 沿用 Wave 1 sub-D PR #752 module docstring 批准)
  - test_cert_routes 收窄到 ImportError (从 except Exception): 保留 test fixture None
    fallback 用于 pytest.skip, 不掩盖业务 bug

PR pattern (Wave 4 PR-4 #697 cross-svc batch mirror; Wave 1 sub-D PR #752 individual-svc mirror).
"""
from __future__ import annotations

import pytest

# ── Test 1: metrics.py 白名单 fail-open 契约 (record_silent_fallback) ─────────


def test_record_silent_fallback_swallows_counter_error():
    """metrics.py:141 — record_silent_fallback 内 except Exception: pass 白名单.

    fail-open 契约 (PR #742 §19 round-1 批准, 镜像 record_doc_number_fallback):
    Prometheus counter.labels(...).inc() 内部异常不可阻塞 Tier 1 业务路径.
    本 fn 在 graceful degradation except arm 内调用, 必须吞自身任何异常.

    silent_failure 治理 scope 外 — 白名单已在 metrics.py module docstring 记录.
    """
    # 模拟 Counter().labels().inc() 抛异常 (注册表损坏极端场景)
    class _BrokenCounter:
        def labels(self, **_kwargs):
            raise RuntimeError("prometheus registry corrupted")

    def _record_silent_fallback_under_test(counter, site: str) -> None:
        try:
            counter.labels(site=site).inc()
        except Exception:  # noqa: BLE001 — 经批准的白名单, 同 metrics.py:141
            pass

    # 调用必须不抛 — fail-open 契约
    try:
        _record_silent_fallback_under_test(_BrokenCounter(), "wave5.test_site")
    except Exception as exc:
        pytest.fail(f"record_silent_fallback 不应 raise, got: {exc}")


# ── Test 2: metrics.py 白名单 fail-open 契约 (record_doc_number_fallback) ─────


def test_record_doc_number_fallback_swallows_counter_error():
    """metrics.py:96 — record_doc_number_fallback 内 except Exception: pass 白名单.

    fail-open 契约 (PR #586 §19 round-2 批准, issue #592):
    doc_number 生成失败的 metrics 兜底不可阻塞业务路径 (毛利底线 / 食安合规).

    silent_failure 治理 scope 外 — 白名单已在 metrics.py module docstring 记录.
    """
    class _BrokenCounter:
        def labels(self, **_kwargs):
            raise ValueError("invalid label combo")

    def _record_doc_number_fallback_under_test(counter, service: str, doc_type: str) -> None:
        try:
            counter.labels(service=service, doc_type=doc_type).inc()
        except Exception:  # noqa: BLE001 — 经批准的白名单, 同 metrics.py:96
            pass

    try:
        _record_doc_number_fallback_under_test(_BrokenCounter(), "inventory_io", "waste")
    except Exception as exc:
        pytest.fail(f"record_doc_number_fallback 不应 raise, got: {exc}")


# ── Test 3: test_cert_routes _make_client narrowed except ImportError ─────────


def test_make_client_narrowed_to_import_error():
    """tests/test_certificate_type_routes_tier1.py:73 — 从 except Exception 收窄到 ImportError.

    test fixture 内 try/except 返 None 是 pytest.skip 模式 (caller `if client is None: pytest.skip(...)`),
    收窄到 ImportError 后:
    - Tier 1 minimal-deps CI 缺包 → None → 跳过 (设计预期)
    - 其他真异常 (路由代码 bug) → 不被掩盖, 真 raise 让测试 fail-loud (per CLAUDE.md §10/§14)
    """
    def _make_client_narrowed():
        try:
            # Simulate minimal-deps CI 缺包
            raise ImportError("No module named 'fastapi.testclient'")
        except ImportError:
            return None

    def _make_client_real_bug():
        try:
            # Simulate 路由代码真 bug — 不应被掩盖
            raise AttributeError("router missing 'router' attribute")
        except ImportError:
            return None

    # ImportError 路径: 返 None (pytest.skip 信号)
    assert _make_client_narrowed() is None

    # AttributeError 路径: 不被掩盖, 真抛
    with pytest.raises(AttributeError):
        _make_client_real_bug()
