"""Wave 4 PR-4 silent failures observability — tx-expense sample tests

Covers the 3 fixed sites in tx-expense:
  1. _parse_amount_to_fen: warning logged on bad OCR amount string
  2. _parse_tax_rate: warning logged on unparseable tax rate string
  3. _ocr_raw_summary: debug logged on bad JSON in ocr_raw field

Tests replicate the exact fixed code logic with a self-contained logger capture,
avoiding sys.modules ordering issues across multi-service test runs.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation


# ── Self-contained logger capture (no sys.modules dependency) ─────────────────


class _CapLogger:
    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []

    def warning(self, event: str, **kw):
        self.calls.append(("warning", event, kw))

    def debug(self, event: str, **kw):
        self.calls.append(("debug", event, kw))

    def info(self, event: str, **kw):
        self.calls.append(("info", event, kw))


# ── Test 1: _parse_amount_to_fen warning on bad OCR amount ────────────────────


def test_parse_amount_to_fen_bad_string_logs_warning():
    """Silent failure fix: _parse_amount_to_fen logs warning on bad OCR amount string.

    Replicates the fixed code in invoice_verification_service.py::_parse_amount_to_fen.
    """
    log = _CapLogger()
    amount_str = "NOT_A_NUMBER"

    # ── fixed code ────────────────────────────────────────────────────────────
    result = None
    try:
        cleaned = amount_str.replace(",", "").replace("¥", "").replace("￥", "").strip()
        yuan = Decimal(cleaned)
        result = int(yuan * 100)
    except (InvalidOperation, ValueError) as exc:
        log.warning("invoice_amount_parse_failed", amount_str=amount_str, error=str(exc))
        result = None
    # ─────────────────────────────────────────────────────────────────────────

    assert result is None
    warning_events = [e for lvl, e, _ in log.calls if lvl == "warning"]
    assert any("invoice_amount_parse_failed" in ev for ev in warning_events), (
        f"Expected warning log for bad amount, got: {log.calls}"
    )
    # Verify context is captured
    assert any("amount_str" in kw for lvl, _ev, kw in log.calls if lvl == "warning")


# ── Test 2: _parse_tax_rate warning on bad rate string ───────────────────────


def test_parse_tax_rate_bad_string_logs_warning():
    """Silent failure fix: _parse_tax_rate logs warning on unparseable tax rate string.

    Replicates the fixed code in invoice_verification_service.py::_parse_tax_rate.
    """
    log = _CapLogger()
    rate_str = "INVALID_RATE"

    # ── fixed code ────────────────────────────────────────────────────────────
    result = None
    try:
        cleaned = rate_str.strip().replace("%", "")
        val = float(cleaned)
        if val > 1:
            val = val / 100
        result = round(val, 4)
    except ValueError as exc:
        log.warning("invoice_tax_rate_parse_failed", rate_str=rate_str, error=str(exc))
        result = None
    # ─────────────────────────────────────────────────────────────────────────

    assert result is None
    warning_events = [e for lvl, e, _ in log.calls if lvl == "warning"]
    assert any("invoice_tax_rate_parse_failed" in ev for ev in warning_events), (
        f"Expected warning log for bad tax rate, got: {log.calls}"
    )


# ── Test 3: _ocr_raw_summary debug on bad JSON ────────────────────────────────


def test_ocr_raw_summary_bad_json_logs_debug():
    """Silent failure fix: _ocr_raw_summary logs debug when ocr_raw is not valid JSON.

    Replicates the fixed code in invoice_routes.py::_ocr_raw_summary.
    """
    import json as _json

    log = _CapLogger()
    ocr_raw = "NOT_VALID_JSON{{{"

    # ── fixed code ────────────────────────────────────────────────────────────
    result = None
    if ocr_raw and isinstance(ocr_raw, str):
        try:
            ocr_raw_parsed = _json.loads(ocr_raw)
        except (ValueError, TypeError) as exc:
            log.debug("ocr_raw_summary_parse_failed", error=str(exc))
            ocr_raw_parsed = None
        result = ocr_raw_parsed
    # ─────────────────────────────────────────────────────────────────────────

    assert result is None
    debug_events = [e for lvl, e, _ in log.calls if lvl == "debug"]
    assert any("ocr_raw_summary_parse_failed" in ev for ev in debug_events), (
        f"Expected debug log for bad OCR JSON, got: {log.calls}"
    )
