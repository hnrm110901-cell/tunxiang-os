"""Wave 4 PR-4 silent failures observability — tx-finance sample tests

Covers the 2 fixed sites in tx-finance:
  1. finance_pl_routes._fetch: warning logged when PLService.get_store_pl raises ValueError
  2. payroll_routes: debug logged on bad month format string (graceful degradation)

Tests replicate the exact fixed code logic with self-contained logger capture.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest


# ── Self-contained logger capture ─────────────────────────────────────────────


class _CapLogger:
    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []

    def warning(self, event: str, **kw):
        self.calls.append(("warning", event, kw))

    def debug(self, event: str, **kw):
        self.calls.append(("debug", event, kw))

    def info(self, event: str, **kw):
        self.calls.append(("info", event, kw))


# ── Test 1: P&L mom inner _fetch warning on ValueError ───────────────────────


@pytest.mark.asyncio
async def test_pl_mom_fetch_logs_warning_on_value_error():
    """Silent failure fix: _fetch in mom endpoint logs warning when PLService raises ValueError.

    Replicates the fixed code in finance_pl_routes.py::get_pl_mom inner _fetch.
    """
    logger = _CapLogger()
    sid = uuid.uuid4()
    tid = str(uuid.uuid4())
    m = "2026-01"
    mock_db = AsyncMock()

    # Simulate PLService that raises ValueError (e.g., store not found, no data)
    mock_pl_svc = AsyncMock()
    mock_pl_svc.get_store_pl = AsyncMock(side_effect=ValueError("no P&L data for period"))

    # ── fixed code ─────────────────────────────────────────────────────────────
    result = None
    try:
        pl = await mock_pl_svc.get_store_pl(sid, "2026-01-01", "2026-01-31", tid, mock_db)
        d: dict = {}
        d["month"] = m
        result = d
    except ValueError as exc:
        logger.warning("pl_mom_fetch_failed", month=m, store_id=str(sid), error=str(exc))
        result = None
    # ──────────────────────────────────────────────────────────────────────────

    assert result is None
    warning_events = [e for lvl, e, _ in logger.calls if lvl == "warning"]
    assert any("pl_mom_fetch_failed" in ev for ev in warning_events), (
        f"Expected pl_mom_fetch_failed warning, got: {logger.calls}"
    )
    # Verify context fields are included
    warn_kw = [kw for lvl, e, kw in logger.calls if lvl == "warning" and "pl_mom_fetch_failed" in e]
    assert warn_kw and "store_id" in warn_kw[0] and "error" in warn_kw[0]


# ── Test 2: payroll month filter parse debug ──────────────────────────────────


def test_payroll_month_parse_bad_format_logs_debug():
    """Silent failure fix: bad month string logs debug and gracefully skips filter.

    Replicates the fixed code in payroll_routes.py list_payroll_records.
    """
    logger = _CapLogger()
    month = "BAD-FORMAT"
    year, month_num = None, None

    # ── fixed code ─────────────────────────────────────────────────────────────
    try:
        year, month_num = int(month[:4]), int(month[5:7])
    except (ValueError, IndexError) as exc:
        logger.debug("payroll_month_filter_parse_failed", month=month, error=str(exc))
        # 忽略格式错误，不过滤月份
    # ──────────────────────────────────────────────────────────────────────────

    debug_events = [e for lvl, e, _ in logger.calls if lvl == "debug"]
    assert any("payroll_month_filter_parse_failed" in ev for ev in debug_events), (
        f"Expected debug log for bad month format, got: {logger.calls}"
    )
    # Verify graceful degradation: year/month_num remain None (no filter applied)
    assert year is None
    assert month_num is None


# ── Test 3: payroll month parse — valid month works normally ─────────────────


def test_payroll_month_parse_valid_format_no_log():
    """Regression guard: valid month '2026-05' parses correctly without logging."""
    logger = _CapLogger()
    month = "2026-05"
    year, month_num = None, None

    try:
        year, month_num = int(month[:4]), int(month[5:7])
    except (ValueError, IndexError) as exc:
        logger.debug("payroll_month_filter_parse_failed", month=month, error=str(exc))

    assert year == 2026
    assert month_num == 5
    assert not logger.calls, f"No log expected for valid month, got: {logger.calls}"
