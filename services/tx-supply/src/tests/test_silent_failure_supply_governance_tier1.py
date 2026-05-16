"""Tier 1 — silent failure 治理 Wave 1 sub-A (#663) regression suite.

12 cases 覆盖 9 业务 site (3 routes + 6 services) 的 fix 模式断言.

设计原则:
  - **Tier 1 CI minimal-deps 安全**: 纯 pathlib.Path source 读取 + str/regex 检查,
    零 sqlalchemy / prometheus_client / fastapi import (避 feedback_tier1_ci_minimal_deps_trap.md).
  - **静态断言强于运行时 mock**: 9 site 都是 try/except 改造 (无逻辑迁移),
    static "源码含 structlog.warn + record_silent_fallback" 已足覆盖意图,
    runtime mock 反而引入 deps + flakiness.
  - **§19 reviewer 视角**: 每个 assert 都对应 plan §2 表的 1 个 cell, 失败 message
    直接说明哪个 site 哪个模式未应用.

参考: issue #663, plan §2 表, feedback_tier1_test_filename_workflow_trigger.md.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

SRC_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    """读源文件原始内容 (零 import 避 minimal-deps 陷阱)."""
    return (SRC_ROOT / rel_path).read_text(encoding="utf-8")


def _ast_silent_count(rel_path: str) -> int:
    """对单文件做 AST silent failure 扫描, 与 scripts/code-fact-scan.py 同口径."""
    tree = ast.parse(_read(rel_path))
    count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            if len(handler.body) != 1:
                continue
            stmt = handler.body[0]
            if isinstance(stmt, ast.Pass):
                count += 1
            elif isinstance(stmt, ast.Return) and (
                stmt.value is None
                or (isinstance(stmt.value, ast.Constant) and stmt.value.value is None)
            ):
                count += 1
    return count


# ──────────────────────────────────────────────────────────────────────────────
# Site 1 — api/voice_count_routes.py:167  (refactor 删 try/except, T3)
# ──────────────────────────────────────────────────────────────────────────────


def test_site1_voice_count_no_more_silent_except():
    """site 1 (T3): _cn_integer_to_int 不再以 try/except ValueError pass 当 fast-path."""
    src = _read("api/voice_count_routes.py")
    # 原 silent pattern: `except ValueError:\n        pass`
    assert not re.search(
        r"try:\s*\n\s*return int\(cn_str\)\s*\n\s*except ValueError:\s*\n\s*pass",
        src,
    ), (
        "voice_count_routes._cn_integer_to_int 仍含 `try int(cn_str) except ValueError: pass`, "
        "refactor 未应用 (plan §2 表 #1). 应改 isdigit() 显式判断."
    )
    # refactor 应使用 isdigit() 显式判断
    assert "isdigit()" in src, (
        "voice_count_routes 应使用 .isdigit() 显式判断替代 try/except control flow (plan §2 表 #1)."
    )


# ──────────────────────────────────────────────────────────────────────────────
# Site 2 — api/deduction_routes.py:247  (Tier 1 邻接, 库存盘亏审计, b 模式)
# ──────────────────────────────────────────────────────────────────────────────


def test_site2_deduction_auto_create_loss_case_warn_with_exc_info():
    """site 2 (Tier 1 邻接): except CaseValidationError 必须 emit structlog.warn + exc_info."""
    src = _read("api/deduction_routes.py")
    assert "auto_create_loss_case_failed" in src, (
        "deduction_routes auto_create_loss_case fail-open 必须含 event "
        "'auto_create_loss_case_failed' (plan §2 表 #2). 库存盘亏审计静默失败 → 运维盲区."
    )
    assert "exc_info=True" in src, (
        "auto_create_loss_case_failed warn 必须含 exc_info=True 让 stack 被 structlog 捕获."
    )


# ──────────────────────────────────────────────────────────────────────────────
# Site 3 — api/smart_procurement_routes.py:234  (Tier 1 邻接, 供应商推荐, b 模式 + counter)
# ──────────────────────────────────────────────────────────────────────────────


def test_site3_smart_procurement_warn_and_counter():
    """site 3 (Tier 1 邻接): supplier_history SQLAlchemyError 必须 warn + record_silent_fallback."""
    src = _read("api/smart_procurement_routes.py")
    assert "supplier_history_lookup_failed" in src, (
        "smart_procurement _get_best_supplier 必须 emit 'supplier_history_lookup_failed' warn "
        "(plan §2 表 #3, Tier 1 邻接 触毛利)."
    )
    assert 'record_silent_fallback("smart_procurement.supplier_history")' in src, (
        "smart_procurement 必须 call record_silent_fallback('smart_procurement.supplier_history') "
        "让运维 Prom 主动告警 (与 doc_number_fallback 同模式)."
    )


# ──────────────────────────────────────────────────────────────────────────────
# Site 4 — services/auto_procurement.py:414  (§13 broad except 零容忍, b 模式)
# ──────────────────────────────────────────────────────────────────────────────


def test_site4_auto_procurement_supplier_score_no_broad_except():
    """site 4 (§13 零容忍): supplier_score except 必须收窄, 0 bare `except Exception`."""
    src = _read("services/auto_procurement.py")
    # 原 silent: `except Exception:  # noqa: BLE001\n                    pass`
    assert not re.search(
        r"try:.*?except Exception:.*?pass",
        src,
        re.DOTALL,
    ) or re.search(
        # 容许文件其他位置 (非 supplier_score 上下文) 历史的 except Exception 兜底,
        # 但 supplier_score 上下文必须收窄
        r"except \(SQLAlchemyError, KeyError, TypeError, ValueError\)",
        src,
    ), (
        "auto_procurement supplier_score 必须收窄至 (SQLAlchemyError, KeyError, TypeError, ValueError) "
        "(plan §2 表 #4, CLAUDE.md §13 零容忍违反闭合)."
    )
    # 必须存在 narrowed except
    assert "except (SQLAlchemyError, KeyError, TypeError, ValueError)" in src, (
        "auto_procurement supplier_score except 必须显式收窄至 4 类具体异常类型."
    )
    # warn event 必须存在
    assert "supplier_score_calc_failed" in src, (
        "auto_procurement supplier_score 必须 emit 'supplier_score_calc_failed' warn."
    )


# ──────────────────────────────────────────────────────────────────────────────
# Site 5 — services/auto_procurement.py:584  (ImportError debug log, c 模式)
# ──────────────────────────────────────────────────────────────────────────────


def test_site5_auto_procurement_create_requisition_debug_log():
    """site 5 (T3): create_requisition ImportError 必须 log.debug 让 test isolation 可追踪."""
    src = _read("services/auto_procurement.py")
    assert "requisition_module_unavailable_using_mock" in src, (
        "auto_procurement create_requisition 测试 isolation fallback 必须 emit "
        "'requisition_module_unavailable_using_mock' debug log (plan §2 表 #5)."
    )


# ──────────────────────────────────────────────────────────────────────────────
# Site 6 — services/expiry_monitor.py:45  (Tier 1 邻接, 食安, b 模式 + counter)
# ──────────────────────────────────────────────────────────────────────────────


def test_site6_expiry_monitor_warn_and_counter():
    """site 6 (Tier 1 邻接, 食安): _parse_notes_expiry 必须 warn + counter (食安不能静默)."""
    src = _read("services/expiry_monitor.py")
    assert "expiry_notes_parse_failed" in src, (
        "expiry_monitor _parse_notes_expiry 必须 emit 'expiry_notes_parse_failed' warn "
        "(plan §2 表 #6, 食安硬约束 — notes JSON schema 漂移必须可见)."
    )
    assert 'record_silent_fallback("expiry_monitor.parse_notes")' in src, (
        "expiry_monitor 必须 call record_silent_fallback('expiry_monitor.parse_notes') "
        "(食安主动告警)."
    )


# ──────────────────────────────────────────────────────────────────────────────
# Site 7 — services/theoretical_cost.py:232  (T2 邻接, 毛利辅助, c 模式 + counter)
# ──────────────────────────────────────────────────────────────────────────────


def test_site7_theoretical_cost_warn_and_counter():
    """site 7 (T2 邻接): _get_current_bom (ImportError/AttributeError) 必须 warn + counter."""
    src = _read("services/theoretical_cost.py")
    assert "bom_template_lookup_dep_failed" in src, (
        "theoretical_cost _get_current_bom 必须 emit 'bom_template_lookup_dep_failed' warn "
        "(plan §2 表 #7)."
    )
    assert 'record_silent_fallback("theoretical_cost.get_current_bom")' in src, (
        "theoretical_cost 必须 call record_silent_fallback('theoretical_cost.get_current_bom')."
    )


# ──────────────────────────────────────────────────────────────────────────────
# Site 8 — services/actual_cost.py:231  (T2 邻接, 实际采购价查询, c 模式 + counter)
# ──────────────────────────────────────────────────────────────────────────────


def test_site8_actual_cost_last_purchase_warn_and_counter():
    """site 8 (T2 邻接): _get_latest_purchase_price 必须 warn + counter."""
    src = _read("services/actual_cost.py")
    assert "actual_cost_last_purchase_dep_failed" in src, (
        "actual_cost _get_latest_purchase_price 必须 emit "
        "'actual_cost_last_purchase_dep_failed' warn (plan §2 表 #8)."
    )
    assert 'record_silent_fallback("actual_cost.last_purchase")' in src, (
        "actual_cost.last_purchase 必须 call record_silent_fallback('actual_cost.last_purchase')."
    )


# ──────────────────────────────────────────────────────────────────────────────
# Site 9 — services/actual_cost.py:260  (T2 邻接, 台账价查询, c 模式 + counter)
# ──────────────────────────────────────────────────────────────────────────────


def test_site9_actual_cost_ledger_price_warn_and_counter():
    """site 9 (T2 邻接): _get_ledger_price 必须 warn + counter."""
    src = _read("services/actual_cost.py")
    assert "actual_cost_ledger_price_dep_failed" in src, (
        "actual_cost _get_ledger_price 必须 emit "
        "'actual_cost_ledger_price_dep_failed' warn (plan §2 表 #9)."
    )
    assert 'record_silent_fallback("actual_cost.ledger_price")' in src, (
        "actual_cost.ledger_price 必须 call record_silent_fallback('actual_cost.ledger_price')."
    )


# ──────────────────────────────────────────────────────────────────────────────
# §13 broad except 零容忍 regression — 6 modified service files 0 bare `except Exception:`
# ──────────────────────────────────────────────────────────────────────────────


_MODIFIED_FILES = [
    "api/voice_count_routes.py",
    "api/deduction_routes.py",
    "api/smart_procurement_routes.py",
    "services/auto_procurement.py",
    "services/expiry_monitor.py",
    "services/theoretical_cost.py",
    "services/actual_cost.py",
]


def test_no_broad_except_in_modified_files():
    """CLAUDE.md §13 零容忍: 本 PR 修改的 7 个文件不得存在 bare `except Exception:`."""
    offenders = []
    for rel in _MODIFIED_FILES:
        src = _read(rel)
        # 真 bare except Exception (含或不含 noqa BLE001 注释), 后接 pass / return None
        # 注意: 历史 noqa BLE001 + pass 模式仍违反 §13, 但需区分"已 noqa 标准但 fix 中"
        # 本 regression 只抓 § 真 silent (body = pass / return None)
        for m in re.finditer(
            r"except\s+Exception\s*:(?:\s*#\s*noqa[^\n]*)?\s*\n\s+(pass|return None)",
            src,
        ):
            line_no = src[: m.start()].count("\n") + 1
            offenders.append(f"{rel}:{line_no}  {m.group(0)[:60]}")
    assert not offenders, (
        "CLAUDE.md §13 zero-tolerance bare `except Exception: pass/return None` 仍残留:\n"
        + "\n".join(offenders)
    )


# ──────────────────────────────────────────────────────────────────────────────
# AST silent count drop — 7 modified files contribute 0 silent (per AST)
# ──────────────────────────────────────────────────────────────────────────────


def test_modified_files_silent_count_zero():
    """7 个 modified 业务文件 AST silent_count 必须全部 == 0 (per-site fix 收口验证).

    与 scripts/code-fact-scan.py 同口径. 整服务 tx-supply 仍剩 15 silent
    (10 tests + 5 新业务 site sub-D follow-up), 但本 PR 修改的 7 个文件应清零.
    """
    failures = []
    for rel in _MODIFIED_FILES:
        count = _ast_silent_count(rel)
        if count != 0:
            failures.append(f"{rel}: {count} silent (期望 0)")
    assert not failures, (
        "本 PR 修改的文件 silent_failure_count 未清零 — 还有 site 未应用 fix:\n"
        + "\n".join(failures)
    )


# ──────────────────────────────────────────────────────────────────────────────
# metrics.py 契约 — silent_fallback_total counter + record_silent_fallback helper 存在
# ──────────────────────────────────────────────────────────────────────────────


def test_metrics_silent_fallback_contract():
    """metrics.py 必须含 silent_fallback_total counter + record_silent_fallback helper.

    cardinality 封闭 5 个 site label, 与 plan §2 表 4 个 (b)/(c) site 一致
    (smart_procurement.supplier_history / expiry_monitor.parse_notes /
    theoretical_cost.get_current_bom / actual_cost.last_purchase /
    actual_cost.ledger_price).
    """
    src = _read("metrics.py")
    assert "silent_fallback_total" in src, "metrics.py 必须定义 silent_fallback_total counter."
    assert "tx_supply_silent_fallback_total" in src, (
        "Prom counter 名必须是 tx_supply_silent_fallback_total (与既有 tx_supply_* metric 一致)."
    )
    assert "def record_silent_fallback(" in src, (
        "metrics.py 必须 export record_silent_fallback(site: str) helper."
    )
    # 5 site label 都在 docstring / counter 注册路径出现
    for site in [
        "smart_procurement.supplier_history",
        "expiry_monitor.parse_notes",
        "theoretical_cost.get_current_bom",
        "actual_cost.last_purchase",
        "actual_cost.ledger_price",
    ]:
        assert site in src, (
            f"site label '{site}' 必须在 metrics.py 中登记 (plan §2 表 cardinality 封闭)."
        )
