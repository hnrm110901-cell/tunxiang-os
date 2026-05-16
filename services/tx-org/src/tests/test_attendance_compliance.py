"""考勤深度合规服务测试 — attendance_compliance_service.py

覆盖:
- 纯函数：_haversine_meters / _age_on_date / _parse_iso_date / _parse_clock_dt
          / _parse_location_payload / _severity_for_rule_name / _shift_bounds
- GPS 打卡异常检测 check_gps_anomaly
- 同设备代打卡 check_same_device
- 加班合规 check_overtime_compliance（周 / 日 / 未成年）
- 班次间休息 check_rest_compliance
- AttendanceComplianceLogService：list / confirm / dismiss / stats

使用 AsyncMock 模拟 AsyncSession，无真实 DB 依赖。
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, time, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

# 确保 src 目录在导入路径中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from services.tx_org.src.services.attendance_compliance_service import (
    COMPLIANCE_RULES,
    AttendanceComplianceLogService,
    _age_on_date,
    _haversine_meters,
    _parse_clock_dt,
    _parse_iso_date,
    _parse_location_payload,
    _severity_for_rule_name,
    _shift_bounds,
    check_gps_anomaly,
    check_overtime_compliance,
    check_rest_compliance,
    check_same_device,
    scan_all_compliance,
)

TENANT_ID = str(uuid4())
STORE_ID = str(uuid4())
EMP_ID = str(uuid4())


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  辅助
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


def _mk_result(rows: list[dict] | None = None, first: dict | None = None, scalar_value=None) -> MagicMock:
    """构造 SQLAlchemy Result mock"""
    result = MagicMock()
    mappings = MagicMock()
    mappings.fetchall = MagicMock(return_value=rows or [])
    mappings.first = MagicMock(return_value=first)
    # 模拟迭代 mappings()
    mappings.__iter__ = MagicMock(return_value=iter(rows or []))
    result.mappings = MagicMock(return_value=mappings)
    result.scalar = MagicMock(return_value=scalar_value)
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. 纯工具函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_haversine_zero_distance():
    """同点距离为 0"""
    assert _haversine_meters(28.2, 112.9, 28.2, 112.9) == pytest.approx(0.0, abs=0.01)


def test_haversine_roughly_500m():
    """约 500m 距离：纬度差 0.0045 度 ≈ 500m"""
    d = _haversine_meters(28.20, 112.90, 28.2045, 112.90)
    assert 450 < d < 550


def test_age_on_date():
    """正确计算出生日期对应日期时的年龄"""
    assert _age_on_date(date(2000, 6, 15), date(2026, 6, 14)) == 25
    assert _age_on_date(date(2000, 6, 15), date(2026, 6, 15)) == 26
    assert _age_on_date(date(2008, 12, 1), date(2026, 4, 1)) == 17  # 未成年


def test_parse_iso_date():
    """ISO 日期解析"""
    assert _parse_iso_date("2026-04-01") == date(2026, 4, 1)


def test_parse_clock_dt_zulu():
    """Z 结尾的 UTC 时间可解析"""
    dt = _parse_clock_dt("2026-04-01T09:00:00Z")
    assert dt.tzinfo is not None
    assert dt.year == 2026


def test_parse_clock_dt_naive_adds_utc():
    """naive 时间被补上 UTC tzinfo"""
    dt = _parse_clock_dt("2026-04-01T09:00:00")
    assert dt.tzinfo == timezone.utc


def test_parse_location_payload_json():
    """JSON 格式 location 解析"""
    assert _parse_location_payload('{"lat": 28.2, "lng": 112.9}') == (28.2, 112.9)


def test_parse_location_payload_csv():
    """CSV 格式 location 解析"""
    assert _parse_location_payload("28.2,112.9") == (28.2, 112.9)


def test_parse_location_payload_invalid():
    """无效 location 返回 None"""
    assert _parse_location_payload(None) is None
    assert _parse_location_payload("") is None
    assert _parse_location_payload("invalid") is None


def test_severity_for_rule_name():
    """根据规则名查询严重等级"""
    # 周加班上限 -> high
    assert _severity_for_rule_name("周加班上限") == "high"
    # 未知规则 -> medium
    assert _severity_for_rule_name("未知规则") == "medium"


def test_shift_bounds_cross_midnight():
    """跨零点班次：结束时间 +1 天"""
    wd = date(2026, 4, 1)
    start, end = _shift_bounds(wd, time(22, 0), time(6, 0))
    assert start.day == 1
    assert end.day == 2


def test_compliance_rules_keys():
    """5 条合规规则存在"""
    for k in (
        "overtime_weekly_limit",
        "overtime_daily_limit",
        "rest_between_shifts",
        "consecutive_work_days",
        "minor_worker_hours",
    ):
        assert k in COMPLIANCE_RULES


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. GPS 异常检测
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_check_gps_anomaly_invalid_location_raises():
    """clock_location 缺少 lat/lng 时报错"""
    db = _make_db()
    with pytest.raises(ValueError, match="clock_location"):
        await check_gps_anomaly(db, TENANT_ID, EMP_ID, {"lat": "bad"})


@pytest.mark.asyncio
async def test_check_gps_anomaly_no_store_coords():
    """门店无坐标 -> 跳过异常检测"""
    db = _make_db()
    # set_config + 员工/门店联表返回空
    db.execute.side_effect = [MagicMock(), _mk_result(first=None)]
    out = await check_gps_anomaly(db, TENANT_ID, EMP_ID, {"lat": 28.2, "lng": 112.9})
    assert out["is_anomaly"] is False
    assert out["store_location"] is None


@pytest.mark.asyncio
async def test_check_gps_anomaly_within_threshold():
    """打卡点在 500m 阈值内 -> 非异常"""
    db = _make_db()
    store_row = {"latitude": 28.2, "longitude": 112.9, "store_id": STORE_ID}
    db.execute.side_effect = [MagicMock(), _mk_result(first=store_row)]
    out = await check_gps_anomaly(db, TENANT_ID, EMP_ID, {"lat": 28.2, "lng": 112.9})
    assert out["is_anomaly"] is False
    assert out["distance_meters"] < 1.0


@pytest.mark.asyncio
async def test_check_gps_anomaly_outside_threshold():
    """打卡点距离 >500m -> 异常"""
    db = _make_db()
    store_row = {"latitude": 28.2, "longitude": 112.9, "store_id": STORE_ID}
    db.execute.side_effect = [MagicMock(), _mk_result(first=store_row)]
    out = await check_gps_anomaly(db, TENANT_ID, EMP_ID, {"lat": 28.3, "lng": 112.9})
    assert out["is_anomaly"] is True
    assert out["distance_meters"] > 500


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 同设备代打卡检测
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_check_same_device_empty_fingerprint():
    """空设备指纹时直接返回非可疑"""
    db = _make_db()
    db.execute.side_effect = [MagicMock()]
    out = await check_same_device(db, TENANT_ID, EMP_ID, "  ", "2026-04-01T09:00:00Z")
    assert out["is_suspicious"] is False
    assert out["same_device_clocks"] == []


@pytest.mark.asyncio
async def test_check_same_device_no_conflict():
    """同设备无其它打卡记录 -> 非可疑"""
    db = _make_db()
    db.execute.side_effect = [MagicMock(), _mk_result(rows=[])]
    out = await check_same_device(
        db,
        TENANT_ID,
        EMP_ID,
        "dev-fp-001",
        "2026-04-01T09:00:00Z",
    )
    assert out["is_suspicious"] is False


@pytest.mark.asyncio
async def test_check_same_device_conflict_found():
    """同设备有其它员工打卡 -> 可疑"""
    db = _make_db()
    other_ct = datetime(2026, 4, 1, 9, 10, 0, tzinfo=timezone.utc)
    conflict_rows = [
        {"employee_id": uuid4(), "emp_name": "李四", "clock_time": other_ct},
    ]
    db.execute.side_effect = [MagicMock(), _mk_result(rows=conflict_rows)]
    out = await check_same_device(
        db,
        TENANT_ID,
        EMP_ID,
        "dev-fp-001",
        "2026-04-01T09:00:00Z",
    )
    assert out["is_suspicious"] is True
    assert len(out["same_device_clocks"]) == 1
    assert out["same_device_clocks"][0]["other_emp_name"] == "李四"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. 加班合规
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_check_overtime_empty_returns_empty():
    """无考勤数据 -> 空列表"""
    db = _make_db()
    db.execute.side_effect = [MagicMock(), _mk_result(rows=[]), _mk_result(rows=[])]
    out = await check_overtime_compliance(db, TENANT_ID, STORE_ID, "2026-03-30")
    assert out == []


@pytest.mark.asyncio
async def test_check_overtime_weekly_exceed():
    """周加班 >36h 触发违规"""
    db = _make_db()
    weekly_rows = [{"employee_id": EMP_ID, "weekly_ot": 40.0}]
    daily_rows = [
        {"employee_id": EMP_ID, "date": date(2026, 3, 30), "ot": 2.0, "wh": 8.0},
    ]
    name_rows = [{"employee_id": EMP_ID, "emp_name": "张三", "birth_date": date(1990, 1, 1)}]
    db.execute.side_effect = [
        MagicMock(),
        _mk_result(rows=weekly_rows),
        _mk_result(rows=daily_rows),
        _mk_result(rows=name_rows),
    ]
    out = await check_overtime_compliance(db, TENANT_ID, STORE_ID, "2026-03-30")
    assert len(out) >= 1
    assert out[0]["is_violation"] is True
    assert out[0]["rule"] == "周加班上限"
    assert out[0]["weekly_ot_hours"] == 40.0


@pytest.mark.asyncio
async def test_check_overtime_minor_worker():
    """未成年工 >8h 触发违规"""
    db = _make_db()
    weekly_rows = [{"employee_id": EMP_ID, "weekly_ot": 5.0}]
    daily_rows = [
        {"employee_id": EMP_ID, "date": date(2026, 3, 30), "ot": 1.0, "wh": 10.0},
    ]
    # 17 岁（2008 年出生，2026 年时 17 岁）
    name_rows = [{"employee_id": EMP_ID, "emp_name": "小明", "birth_date": date(2008, 12, 1)}]
    db.execute.side_effect = [
        MagicMock(),
        _mk_result(rows=weekly_rows),
        _mk_result(rows=daily_rows),
        _mk_result(rows=name_rows),
    ]
    out = await check_overtime_compliance(db, TENANT_ID, STORE_ID, "2026-03-30")
    minor_violations = [v for v in out if "未成年" in v["rule"]]
    assert len(minor_violations) == 1


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. 班次间休息
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_check_rest_sufficient_no_violation():
    """两班间隔 >= 11 小时 -> 无违规"""
    db = _make_db()
    schedule_rows = [
        {
            "employee_id": EMP_ID,
            "work_date": date(2026, 3, 31),
            "shift_start_time": time(9, 0),
            "shift_end_time": time(18, 0),
        },
        {
            "employee_id": EMP_ID,
            "work_date": date(2026, 4, 1),
            "shift_start_time": time(9, 0),
            "shift_end_time": time(18, 0),
        },
    ]
    name_rows = [{"employee_id": EMP_ID, "emp_name": "张三"}]
    db.execute.side_effect = [
        MagicMock(),
        _mk_result(rows=schedule_rows),
        _mk_result(rows=name_rows),
    ]
    out = await check_rest_compliance(db, TENANT_ID, STORE_ID, "2026-04-01")
    assert out == []


@pytest.mark.asyncio
async def test_check_rest_insufficient_violation():
    """两班间隔 < 11 小时 -> 违规"""
    db = _make_db()
    # 前一天 18-22, 次日 6:00 上班 -> 间隔仅 8 小时
    schedule_rows = [
        {
            "employee_id": EMP_ID,
            "work_date": date(2026, 3, 31),
            "shift_start_time": time(18, 0),
            "shift_end_time": time(22, 0),
        },
        {
            "employee_id": EMP_ID,
            "work_date": date(2026, 4, 1),
            "shift_start_time": time(6, 0),
            "shift_end_time": time(14, 0),
        },
    ]
    name_rows = [{"employee_id": EMP_ID, "emp_name": "张三"}]
    db.execute.side_effect = [
        MagicMock(),
        _mk_result(rows=schedule_rows),
        _mk_result(rows=name_rows),
    ]
    out = await check_rest_compliance(db, TENANT_ID, STORE_ID, "2026-04-01")
    assert len(out) == 1
    assert out[0]["is_violation"] is True
    assert out[0]["gap_hours"] < 11


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6. AttendanceComplianceLogService
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_log_service_list_violations_empty():
    """违规列表：无数据返回空"""
    db = _make_db()
    # set_config + COUNT + SELECT
    count_result = MagicMock()
    count_result.scalar = MagicMock(return_value=0)
    data_result = MagicMock()
    data_result.mappings = MagicMock(return_value=iter([]))
    db.execute.side_effect = [MagicMock(), count_result, data_result]
    svc = AttendanceComplianceLogService(db, TENANT_ID)
    out = await svc.list_violations(page=1, size=20)
    assert out["total"] == 0
    assert out["items"] == []
    assert out["page"] == 1


@pytest.mark.asyncio
async def test_log_service_confirm_success():
    """确认违规成功"""
    db = _make_db()
    result = MagicMock()
    result.scalar = MagicMock(return_value="log-001")
    db.execute.side_effect = [MagicMock(), result]
    svc = AttendanceComplianceLogService(db, TENANT_ID)
    out = await svc.confirm_violation("log-001", str(uuid4()))
    assert out["ok"] is True
    assert out["id"] == "log-001"


@pytest.mark.asyncio
async def test_log_service_confirm_not_found():
    """确认违规失败：记录不存在或状态非 pending"""
    db = _make_db()
    result = MagicMock()
    result.scalar = MagicMock(return_value=None)
    db.execute.side_effect = [MagicMock(), result]
    svc = AttendanceComplianceLogService(db, TENANT_ID)
    out = await svc.confirm_violation("log-999", str(uuid4()))
    assert out["ok"] is False
    assert "error" in out


@pytest.mark.asyncio
async def test_log_service_dismiss_success():
    """驳回违规成功"""
    db = _make_db()
    result = MagicMock()
    result.scalar = MagicMock(return_value="log-002")
    db.execute.side_effect = [MagicMock(), result]
    svc = AttendanceComplianceLogService(db, TENANT_ID)
    out = await svc.dismiss_violation("log-002", "误报：员工已到岗")
    assert out["ok"] is True


@pytest.mark.asyncio
async def test_log_service_stats_aggregation():
    """合规统计按 type/severity/status 聚合"""
    db = _make_db()
    rows = [
        {"violation_type": "gps_anomaly", "severity": "medium", "status": "pending", "cnt": 3},
        {"violation_type": "overtime_exceed", "severity": "high", "status": "confirmed", "cnt": 2},
        {"violation_type": "gps_anomaly", "severity": "medium", "status": "dismissed", "cnt": 1},
    ]
    data_result = MagicMock()
    data_result.mappings = MagicMock(return_value=iter(rows))
    db.execute.side_effect = [MagicMock(), data_result]
    svc = AttendanceComplianceLogService(db, TENANT_ID)
    stats = await svc.get_compliance_stats(month="2026-04")
    assert stats["month"] == "2026-04"
    assert stats["total"] == 6
    assert stats["by_type"]["gps_anomaly"] == 4
    assert stats["by_type"]["overtime_exceed"] == 2
    assert stats["by_severity"]["medium"] == 4
    assert stats["by_status"]["pending"] == 3


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  7. issue #703 — GPS payload parse fail caller-side log + Prom counter
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _make_sql_router_db(handlers: dict) -> AsyncMock:
    """构造 SQL-text-based 路由 mock db.

    handlers: {sql_keyword: result_mock} — 按 SQL text 模糊匹配返回对应 result.
              未匹配的 SQL 返回 _mk_result(rows=[]) 默认空 (兼容 set_config 等).
    """
    db = _make_db()

    async def _execute(stmt, *args, **kwargs):
        # stmt 是 sqlalchemy.text() 包装, 转 str 后查询
        sql_text = str(stmt)
        for keyword, result in handlers.items():
            if keyword in sql_text:
                return result
        return _mk_result(rows=[])

    db.execute = AsyncMock(side_effect=_execute)
    return db


@pytest.mark.asyncio
async def test_scan_all_compliance_garbage_gps_logs_warning_and_increments_counter(monkeypatch):
    """issue #703: 垃圾 GPS payload 解析失败 -> caller 升 warning + Prom counter inc.

    防员工故意输入非法 GPS payload (CSV 格式错 / 空 / 非法字符) 绕过出勤合规
    审查 (违规打卡不在排班点也能通过 GPS 校验)。
    """
    from services.tx_org.src.services import attendance_compliance_service as svc_mod

    # mock counter helper — 捕获调用次数与参数
    counter_calls: list[dict] = []

    def fake_record(tenant_id: str, employee_id: str) -> None:
        counter_calls.append({"tenant_id": tenant_id, "employee_id": employee_id})

    monkeypatch.setattr(svc_mod, "record_attendance_location_parse_failed", fake_record)

    # mock logger.warning — 捕获日志事件
    warning_events: list[tuple[str, dict]] = []
    original_warning = svc_mod.logger.warning

    def fake_warning(event: str, **kwargs):
        warning_events.append((event, kwargs))
        return original_warning(event, **kwargs)

    monkeypatch.setattr(svc_mod.logger, "warning", fake_warning)

    garbage_emp_id = str(uuid4())
    clock_records = [
        {
            "id": uuid4(),
            "employee_id": garbage_emp_id,
            "clock_time": datetime(2026, 4, 1, 9, 0, 0, tzinfo=timezone.utc),
            "location": "not_a_valid_gps_payload_xxx",  # 垃圾 payload
            "device_info": "",
        },
    ]
    store_row = {"latitude": 28.2, "longitude": 112.9}

    # SQL-text routed handlers — 比 side_effect 列表更稳健 (不依赖调用顺序)
    db = _make_sql_router_db({
        "latitude, longitude": _mk_result(first=store_row),
        "SELECT id, employee_id, clock_time, location": _mk_result(rows=clock_records),
    })

    await scan_all_compliance(
        db,
        TENANT_ID,
        STORE_ID,
        ("2026-04-01", "2026-04-01"),
    )

    # 验证 counter 调用 — 1 row 垃圾 GPS = 1 次 inc
    assert len(counter_calls) == 1
    assert counter_calls[0]["tenant_id"] == TENANT_ID
    assert counter_calls[0]["employee_id"] == garbage_emp_id

    # 验证 warning 日志被发射
    matching = [e for e in warning_events if e[0] == "attendance_location_parse_failed"]
    assert len(matching) == 1
    _event_name, event_kwargs = matching[0]
    assert event_kwargs["tenant_id"] == TENANT_ID
    assert event_kwargs["employee_id"] == garbage_emp_id
    # payload_preview 必须截断 (防日志炸 / PII)
    assert len(event_kwargs["payload_preview"]) <= 50


@pytest.mark.asyncio
async def test_scan_all_compliance_valid_gps_no_counter_inc(monkeypatch):
    """issue #703: 合法 GPS payload -> counter 不动 (无误报)."""
    from services.tx_org.src.services import attendance_compliance_service as svc_mod

    counter_calls: list[dict] = []

    def fake_record(tenant_id: str, employee_id: str) -> None:
        counter_calls.append({"tenant_id": tenant_id, "employee_id": employee_id})

    monkeypatch.setattr(svc_mod, "record_attendance_location_parse_failed", fake_record)

    valid_emp_id = str(uuid4())
    clock_records = [
        {
            "id": uuid4(),
            "employee_id": valid_emp_id,
            "clock_time": datetime(2026, 4, 1, 9, 0, 0, tzinfo=timezone.utc),
            "location": '{"lat": 28.2, "lng": 112.9}',  # 合法 GPS, 与门店同点
            "device_info": "",
        },
    ]
    store_row = {"latitude": 28.2, "longitude": 112.9}

    db = _make_sql_router_db({
        "latitude, longitude": _mk_result(first=store_row),
        "SELECT id, employee_id, clock_time, location": _mk_result(rows=clock_records),
    })

    await scan_all_compliance(
        db,
        TENANT_ID,
        STORE_ID,
        ("2026-04-01", "2026-04-01"),
    )

    # 合法 GPS, counter 不应被调用
    assert counter_calls == []


def test_metrics_module_fallback_stub_when_prometheus_missing(monkeypatch):
    """tx-org metrics.py 在 prometheus_client 缺失时走 _NoOpCounter (fail-open).

    与 feedback_tier1_ci_minimal_deps_trap.md 模式一致: CI minimal deps 不装
    prometheus_client, 模块必须 fail-open stub, record_* helper 不能 raise.
    """
    from services.tx_org.src import metrics as metrics_mod

    # record helper 不 raise (无论 prometheus_client 是否真实安装)
    metrics_mod.record_attendance_location_parse_failed(
        tenant_id=TENANT_ID, employee_id=EMP_ID
    )
    # 调用 5 次连续无异常
    for _ in range(5):
        metrics_mod.record_attendance_location_parse_failed(
            tenant_id=TENANT_ID, employee_id="unknown"
        )
