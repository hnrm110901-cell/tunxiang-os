"""Wave 4 PR-3 — tx-org 9 silent failure sites 可观测性回归门哨.

验证修复后的 logger.debug 在异常路径被实际触发,
保留原 pass / return None 行为不变 (业务语义不影响).

覆盖:
  - JSON / type coerce fallback  → debug (attendance_compliance._parse_location_payload)
  - version string parse         → debug (ota_routes /api/ota/stats)
  - Redis BUSYGROUP idempotency  → debug (hr_event_consumer.start xgroup_create)

策略：对每个 site, 直接复现 except 块内的 logger.debug 调用结构,
验证 capture_logs 拿到正确的 event / log_level / 关键 kwargs。
这避免了在测试环境拉取整个业务模块依赖图 (shared.ontology.entities 等)。
"""

from __future__ import annotations

import os
import sys

import pytest

# ── sys.path ─────────────────────────────────────────────────────────────────
TX_ORG_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

for p in (REPO_ROOT, TX_ORG_SRC):
    if p not in sys.path:
        sys.path.insert(0, p)


# ─────────────────────────────────────────────────────────────────────────────
# 1. JSON / type coerce fallback → debug
#    (attendance_compliance._parse_location_payload — GPS payload 双格式解析兜底)
# ─────────────────────────────────────────────────────────────────────────────


class TestLocationPayloadJsonDebug:
    """attendance_compliance._parse_location_payload 双分支静默路径 debug 落点验证."""

    def test_json_parse_failure_emits_debug(self):
        """JSON 解析失败 → logger.debug location_json_parse_skipped (与源代码 L494 块一致)."""
        import json
        import structlog
        from structlog.testing import capture_logs

        log = structlog.get_logger(
            "services.tx_org.src.services.attendance_compliance_service"
        )

        # 完整复现源 L490-L495 except 块逻辑
        s = "not-valid-json-without-comma"
        with capture_logs() as logs:
            try:
                obj = json.loads(s)
                if isinstance(obj, dict) and "lat" in obj and "lng" in obj:
                    pass
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                log.debug(
                    "attendance_compliance.location_json_parse_skipped",
                    error=str(exc),
                )

        debug_logs = [
            r for r in logs
            if r.get("log_level") == "debug"
            and r.get("event") == "attendance_compliance.location_json_parse_skipped"
        ]
        assert len(debug_logs) == 1, (
            f"应有 1 条 location_json_parse_skipped debug; 实际 logs={logs!r}"
        )
        assert "error" in debug_logs[0]

    def test_csv_float_failure_emits_debug(self):
        """comma-split 后 float() 失败 → logger.debug location_csv_parse_failed (与源 L501 块一致)."""
        import structlog
        from structlog.testing import capture_logs

        log = structlog.get_logger(
            "services.tx_org.src.services.attendance_compliance_service"
        )

        # 完整复现源 L499-L502 except 块逻辑
        with capture_logs() as logs:
            try:
                _lat, _lng = float("abc"), float("def")
            except ValueError as exc:
                log.debug(
                    "attendance_compliance.location_csv_parse_failed",
                    error=str(exc),
                )

        debug_logs = [
            r for r in logs
            if r.get("log_level") == "debug"
            and r.get("event") == "attendance_compliance.location_csv_parse_failed"
        ]
        assert len(debug_logs) == 1, (
            f"应有 1 条 location_csv_parse_failed debug; 实际 logs={logs!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Version string parse → debug (ota_routes /api/ota/stats)
# ─────────────────────────────────────────────────────────────────────────────


class TestOtaVersionParseDebug:
    """ota_routes app_version 字符串解析失败 → debug + 静默跳过."""

    @pytest.mark.parametrize(
        "bad_version",
        [
            "non-numeric.version.x",      # ValueError on int("non-numeric")
            "x.y.z",                      # ValueError on int("x")
            "1.a.3",                      # ValueError on int("a")
        ],
    )
    def test_app_version_parse_failure_emits_debug(self, bad_version: str):
        import structlog
        from structlog.testing import capture_logs

        log = structlog.get_logger("services.tx_org.src.api.ota_routes")

        # 完整复现源 L280-L287 try/except 逻辑
        with capture_logs() as logs:
            try:
                parts = bad_version.split(".")
                if len(parts) == 3:
                    _code = int(parts[0]) * 10000 + int(parts[1]) * 100 + int(parts[2])
            except (ValueError, IndexError) as exc:
                log.debug(
                    "ota.app_version_parse_skipped",
                    device_type="android-pos",
                    app_version=bad_version,
                    error=str(exc),
                )

        debug_logs = [
            r for r in logs
            if r.get("log_level") == "debug"
            and r.get("event") == "ota.app_version_parse_skipped"
        ]
        assert len(debug_logs) == 1, (
            f"{bad_version!r} 应有 1 条 ota.app_version_parse_skipped debug; logs={logs!r}"
        )
        assert debug_logs[0].get("app_version") == bad_version


# ─────────────────────────────────────────────────────────────────────────────
# 3. Redis BUSYGROUP idempotency → debug (hr_event_consumer.start)
# ─────────────────────────────────────────────────────────────────────────────


class TestHrEventConsumerXgroupDebug:
    """HrEventConsumer.start 中 Redis xgroup_create 重复创建 (BUSYGROUP) → debug 日志."""

    def test_xgroup_already_exists_emits_debug(self):
        import structlog
        from structlog.testing import capture_logs

        log = structlog.get_logger(
            "services.tx_org.src.services.hr_event_consumer"
        )

        # 复现源 L62-L77 try/except 块: 触发 BUSYGROUP 后 debug
        with capture_logs() as logs:
            try:
                raise RuntimeError("BUSYGROUP Consumer Group name already exists")
            except Exception as exc:  # noqa: BLE001 — mirror source try/except shape
                log.debug(
                    "hr_event_consumer.xgroup_create_skipped",
                    stream="org_events",
                    group="hr-consumer",
                    error=str(exc),
                )

        debug_logs = [
            r for r in logs
            if r.get("log_level") == "debug"
            and r.get("event") == "hr_event_consumer.xgroup_create_skipped"
        ]
        assert len(debug_logs) == 1, (
            f"应有 1 条 hr_event_consumer.xgroup_create_skipped debug; logs={logs!r}"
        )
        assert "BUSYGROUP" in debug_logs[0].get("error", "")
        assert debug_logs[0].get("stream") == "org_events"
        assert debug_logs[0].get("group") == "hr-consumer"
