"""tx-org 考勤深度合规服务。"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Employee, Store

logger = structlog.get_logger(__name__)

COMPLIANCE_RULES: dict[str, dict[str, Any]] = {
    "overtime_weekly_limit": {
        "name": "周加班上限",
        "threshold": 36,
        "unit": "hours",
        "law": "劳动法第四十一条",
        "severity": "high",
    },
    "overtime_daily_limit": {
        "name": "日加班上限",
        "threshold": 3,
        "unit": "hours",
        "law": "劳动法第四十一条",
        "severity": "medium",
    },
    "rest_between_shifts": {
        "name": "班次间休息",
        "threshold": 11,
        "unit": "hours",
        "law": "劳动法规定合理休息时间",
        "severity": "high",
    },
    "consecutive_work_days": {
        "name": "连续工作天数",
        "threshold": 6,
        "unit": "days",
        "law": "劳动法第三十八条",
        "severity": "high",
    },
    "minor_worker_hours": {
        "name": "未成年工时限制",
        "threshold": 8,
        "unit": "hours_per_day",
        "law": "未成年人保护法",
        "severity": "critical",
    },
}

_EARTH_RADIUS_M = 6371000.0
_GPS_THRESHOLD_M = 500.0
_REST_MIN_HOURS = float(COMPLIANCE_RULES["rest_between_shifts"]["threshold"])
_DEVICE_WINDOW_MINUTES = 30

EMPLOYEES_TABLE = Employee.__tablename__
STORES_TABLE = Store.__tablename__


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    c = 2 * math.asin(min(1.0, math.sqrt(a)))
    return _EARTH_RADIUS_M * c


def _shift_bounds(work_date: date, st: time, et: time) -> tuple[datetime, datetime]:
    start_dt = datetime.combine(work_date, st, tzinfo=timezone.utc)
    end_dt = datetime.combine(work_date, et, tzinfo=timezone.utc)
    if et <= st:
        end_dt = end_dt + timedelta(days=1)
    return start_dt, end_dt


def _age_on_date(birth: date, as_of: date) -> int:
    y = as_of.year - birth.year
    if (as_of.month, as_of.day) < (birth.month, birth.day):
        y -= 1
    return y


def _parse_iso_date(s: str) -> date:
    return date.fromisoformat(s)


def _parse_clock_dt(clock_time: str) -> datetime:
    raw = clock_time.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def _employee_store_coords(
    db: AsyncSession,
    tenant_id: str,
    employee_id: str,
) -> tuple[float | None, float | None, str | None]:
    row = await db.execute(
        text(
            f"""
            SELECT s.latitude, s.longitude, s.id::text AS store_id
            FROM {EMPLOYEES_TABLE} e
            INNER JOIN {STORES_TABLE} s ON s.id = e.store_id AND s.tenant_id = e.tenant_id
            WHERE e.tenant_id = CAST(:tid AS uuid)
              AND e.is_deleted = FALSE
              AND s.is_deleted = FALSE
              AND e.id::text = :eid
            """
        ),
        {"tid": tenant_id, "eid": employee_id},
    )
    m = row.mappings().first()
    if not m:
        return None, None, None
    return m.get("latitude"), m.get("longitude"), m.get("store_id")


async def check_gps_anomaly(
    db: AsyncSession,
    tenant_id: str,
    employee_id: str,
    clock_location: dict[str, Any],
) -> dict[str, Any]:
    """GPS 打卡异常检测。"""
    await _set_tenant(db, tenant_id)
    try:
        lat = float(clock_location["lat"])
        lng = float(clock_location["lng"])
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError("clock_location 需包含可解析的 lat、lng") from e

    slat, slng, _sid = await _employee_store_coords(db, tenant_id, employee_id)
    if slat is None or slng is None:
        logger.info(
            "attendance_compliance.gps_skip_no_store_coords",
            tenant_id=tenant_id,
            employee_id=employee_id,
        )
        return {
            "is_anomaly": False,
            "distance_meters": 0.0,
            "store_location": None,
            "threshold_meters": _GPS_THRESHOLD_M,
        }

    dist = _haversine_meters(lat, lng, float(slat), float(slng))
    is_anomaly = dist > _GPS_THRESHOLD_M
    logger.info(
        "attendance_compliance.check_gps",
        tenant_id=tenant_id,
        employee_id=employee_id,
        distance_meters=round(dist, 2),
        is_anomaly=is_anomaly,
    )
    return {
        "is_anomaly": is_anomaly,
        "distance_meters": round(dist, 2),
        "store_location": {"lat": float(slat), "lng": float(slng)},
        "threshold_meters": _GPS_THRESHOLD_M,
    }


async def check_same_device(
    db: AsyncSession,
    tenant_id: str,
    employee_id: str,
    device_fingerprint: str,
    clock_time: str,
) -> dict[str, Any]:
    """同设备代打卡检测。"""
    await _set_tenant(db, tenant_id)
    if not device_fingerprint.strip():
        return {"is_suspicious": False, "same_device_clocks": []}

    center = _parse_clock_dt(clock_time)
    win = timedelta(minutes=_DEVICE_WINDOW_MINUTES)
    t0 = center - win
    t1 = center + win

    rows = await db.execute(
        text(
            f"""
            SELECT cr.employee_id, e.emp_name, cr.clock_time
            FROM clock_records cr
            INNER JOIN {EMPLOYEES_TABLE} e ON e.id::text = cr.employee_id AND e.tenant_id = cr.tenant_id
            WHERE cr.tenant_id = CAST(:tid AS uuid)
              AND cr.is_deleted = FALSE
              AND e.is_deleted = FALSE
              AND cr.device_info = :fp
              AND cr.clock_time >= :t0 AND cr.clock_time <= :t1
              AND cr.employee_id <> :eid
            ORDER BY cr.clock_time
            """
        ),
        {
            "tid": tenant_id,
            "fp": device_fingerprint,
            "t0": t0,
            "t1": t1,
            "eid": employee_id,
        },
    )
    clocks: list[dict[str, Any]] = []
    for r in rows.mappings().fetchall():
        ct = r["clock_time"]
        if isinstance(ct, datetime):
            cts = ct.astimezone(timezone.utc).isoformat()
        else:
            cts = str(ct)
        clocks.append(
            {
                "other_employee_id": str(r["employee_id"]),
                "other_emp_name": str(r["emp_name"]),
                "clock_time": cts,
            },
        )
    out = {"is_suspicious": len(clocks) > 0, "same_device_clocks": clocks}
    logger.info(
        "attendance_compliance.check_same_device",
        tenant_id=tenant_id,
        employee_id=employee_id,
        suspicious=out["is_suspicious"],
        conflict_count=len(clocks),
    )
    return out


async def check_overtime_compliance(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    week_start: str,
) -> list[dict[str, Any]]:
    """检查加班合规性。"""
    await _set_tenant(db, tenant_id)
    ws = _parse_iso_date(week_start)
    we = ws + timedelta(days=6)
    rule_w = COMPLIANCE_RULES["overtime_weekly_limit"]
    rule_d = COMPLIANCE_RULES["overtime_daily_limit"]
    rule_m = COMPLIANCE_RULES["minor_worker_hours"]
    limit_w = float(rule_w["threshold"])
    limit_d = float(rule_d["threshold"])
    limit_m = float(rule_m["threshold"])

    weekly_rows = await db.execute(
        text(
            """
            SELECT employee_id, SUM(COALESCE(overtime_hours, 0)) AS weekly_ot
            FROM daily_attendance
            WHERE tenant_id = CAST(:tid AS uuid)
              AND store_id = :sid
              AND date >= :ws AND date <= :we
              AND is_deleted = FALSE
            GROUP BY employee_id
            """
        ),
        {"tid": tenant_id, "sid": store_id, "ws": ws, "we": we},
    )
    weekly_map: dict[str, float] = {
        str(r["employee_id"]): float(r["weekly_ot"] or 0) for r in weekly_rows.mappings().fetchall()
    }

    daily_rows = await db.execute(
        text(
            """
            SELECT employee_id, date, COALESCE(overtime_hours, 0) AS ot,
                   COALESCE(work_hours, 0) AS wh
            FROM daily_attendance
            WHERE tenant_id = CAST(:tid AS uuid)
              AND store_id = :sid
              AND date >= :ws AND date <= :we
              AND is_deleted = FALSE
            """
        ),
        {"tid": tenant_id, "sid": store_id, "ws": ws, "we": we},
    )
    daily_by_emp: dict[str, list[tuple[date, float, float]]] = {}
    for r in daily_rows.mappings().fetchall():
        eid = str(r["employee_id"])
        d_raw = r["date"]
        if isinstance(d_raw, datetime):
            d_cell: date = d_raw.date()
        elif isinstance(d_raw, date):
            d_cell = d_raw
        else:
            continue
        daily_by_emp.setdefault(eid, []).append((d_cell, float(r["ot"] or 0), float(r["wh"] or 0)))

    emp_ids = set(weekly_map.keys()) | set(daily_by_emp.keys())
    if not emp_ids:
        return []

    name_rows = await db.execute(
        text(
            f"""
            SELECT id::text AS employee_id, emp_name, birth_date
            FROM {EMPLOYEES_TABLE}
            WHERE tenant_id = CAST(:tid AS uuid)
              AND is_deleted = FALSE
              AND id::text = ANY(:eids)
            """
        ),
        {"tid": tenant_id, "eids": list(emp_ids)},
    )
    meta: dict[str, dict[str, Any]] = {}
    for r in name_rows.mappings().fetchall():
        meta[str(r["employee_id"])] = {
            "emp_name": r["emp_name"],
            "birth_date": r["birth_date"],
        }

    violations: list[dict[str, Any]] = []

    for eid in sorted(emp_ids):
        info = meta.get(eid, {"emp_name": eid, "birth_date": None})
        emp_name = str(info.get("emp_name") or eid)
        birth = info.get("birth_date")
        birth_d: date | None
        if birth is None:
            birth_d = None
        elif isinstance(birth, datetime):
            birth_d = birth.date()
        elif isinstance(birth, date):
            birth_d = birth
        else:
            birth_d = None

        wot = weekly_map.get(eid, 0.0)
        if wot > limit_w:
            violations.append(
                {
                    "employee_id": eid,
                    "emp_name": emp_name,
                    "weekly_ot_hours": round(wot, 2),
                    "limit_hours": limit_w,
                    "is_violation": True,
                    "rule": rule_w["name"],
                    "law_reference": rule_w["law"],
                },
            )

        for d, ot, wh in daily_by_emp.get(eid, []):
            if ot > limit_d:
                violations.append(
                    {
                        "employee_id": eid,
                        "emp_name": emp_name,
                        "weekly_ot_hours": round(ot, 2),
                        "limit_hours": limit_d,
                        "is_violation": True,
                        "rule": f"{rule_d['name']} ({d.isoformat()})",
                        "law_reference": rule_d["law"],
                    },
                )
            if birth_d is not None and _age_on_date(birth_d, d) < 18 and wh > limit_m:
                violations.append(
                    {
                        "employee_id": eid,
                        "emp_name": emp_name,
                        "weekly_ot_hours": round(wh, 2),
                        "limit_hours": limit_m,
                        "is_violation": True,
                        "rule": f"{rule_m['name']} ({d.isoformat()})",
                        "law_reference": rule_m["law"],
                    },
                )

    logger.info(
        "attendance_compliance.check_overtime",
        tenant_id=tenant_id,
        store_id=store_id,
        week_start=week_start,
        violation_count=len(violations),
    )
    return violations


async def check_rest_compliance(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    date: str,
) -> list[dict[str, Any]]:
    """检查班次间休息合规。"""
    await _set_tenant(db, tenant_id)
    d0 = _parse_iso_date(date)
    d_prev = d0 - timedelta(days=1)

    rows = await db.execute(
        text(
            """
            SELECT employee_id, work_date, shift_start_time, shift_end_time
            FROM employee_schedules
            WHERE tenant_id = CAST(:tid AS uuid)
              AND store_id = :sid
              AND work_date IN (:d0, :dprev)
              AND is_deleted = FALSE
              AND is_day_off = FALSE
              AND shift_start_time IS NOT NULL
              AND shift_end_time IS NOT NULL
            ORDER BY employee_id, work_date, shift_start_time
            """
        ),
        {"tid": tenant_id, "sid": store_id, "d0": d0, "dprev": d_prev},
    )
    by_emp: dict[str, list[tuple[date, time, time]]] = {}
    for r in rows.mappings().fetchall():
        wd = r["work_date"]
        if isinstance(wd, datetime):
            wd = wd.date()
        st = r["shift_start_time"]
        et = r["shift_end_time"]
        if not isinstance(st, time) or not isinstance(et, time):
            continue
        eid = str(r["employee_id"])
        by_emp.setdefault(eid, []).append((wd, st, et))

    emp_ids = list(by_emp.keys())
    names: dict[str, str] = {}
    if emp_ids:
        nr = await db.execute(
            text(
                f"""
                SELECT id::text AS employee_id, emp_name
                FROM {EMPLOYEES_TABLE}
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND is_deleted = FALSE
                  AND id::text = ANY(:eids)
                """
            ),
            {"tid": tenant_id, "eids": emp_ids},
        )
        for row in nr.mappings().fetchall():
            names[str(row["employee_id"])] = str(row["emp_name"])

    violations: list[dict[str, Any]] = []
    for eid, shifts in by_emp.items():
        shifts.sort(key=lambda x: (x[0], x[1]))
        for i in range(len(shifts) - 1):
            wd_a, sta, eta = shifts[i]
            wd_b, stb, etb = shifts[i + 1]
            _, end_a = _shift_bounds(wd_a, sta, eta)
            start_b, _ = _shift_bounds(wd_b, stb, etb)
            gap_h = (start_b - end_a).total_seconds() / 3600.0
            if gap_h < _REST_MIN_HOURS:
                violations.append(
                    {
                        "employee_id": eid,
                        "emp_name": names.get(eid, eid),
                        "previous_shift_end": end_a.astimezone(timezone.utc).isoformat(),
                        "next_shift_start": start_b.astimezone(timezone.utc).isoformat(),
                        "gap_hours": round(gap_h, 2),
                        "is_violation": True,
                    },
                )

    logger.info(
        "attendance_compliance.check_rest",
        tenant_id=tenant_id,
        store_id=store_id,
        date=date,
        violation_count=len(violations),
    )
    return violations


def _parse_location_payload(loc: str | None) -> tuple[float, float] | None:
    if not loc or not loc.strip():
        return None
    s = loc.strip()
    try:
        obj = json.loads(s)
        if isinstance(obj, dict) and "lat" in obj and "lng" in obj:
            return float(obj["lat"]), float(obj["lng"])
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    if "," in s:
        parts = [p.strip() for p in s.split(",", 1)]
        if len(parts) == 2:
            try:
                return float(parts[0]), float(parts[1])
            except ValueError:
                return None
    return None


def _severity_for_rule_name(rule_name: str) -> str:
    for _k, cfg in COMPLIANCE_RULES.items():
        if cfg["name"] in rule_name or rule_name.startswith(str(cfg["name"])):
            return str(cfg["severity"])
    return "medium"


async def scan_all_compliance(
    db: AsyncSession,
    tenant_id: str,
    store_id: str,
    date_range: tuple[str, str],
) -> dict[str, Any]:
    """综合合规扫描。"""
    await _set_tenant(db, tenant_id)
    start_d = _parse_iso_date(date_range[0])
    end_d = _parse_iso_date(date_range[1])
    if end_d < start_d:
        start_d, end_d = end_d, start_d

    period = f"{start_d.isoformat()}~{end_d.isoformat()}"

    overtime_violations: list[dict[str, Any]] = []
    monday = start_d - timedelta(days=start_d.weekday())
    while monday <= end_d:
        overtime_violations.extend(
            await check_overtime_compliance(db, tenant_id, store_id, monday.isoformat()),
        )
        monday = monday + timedelta(days=7)

    rest_violations: list[dict[str, Any]] = []
    d = start_d
    while d <= end_d:
        rest_violations.extend(await check_rest_compliance(db, tenant_id, store_id, d.isoformat()))
        d = d + timedelta(days=1)

    slat: float | None = None
    slng: float | None = None
    sr = await db.execute(
        text(
            f"""
            SELECT latitude, longitude
            FROM {STORES_TABLE}
            WHERE tenant_id = CAST(:tid AS uuid)
              AND id::text = :sid
              AND is_deleted = FALSE
            """
        ),
        {"tid": tenant_id, "sid": store_id},
    )
    sm = sr.mappings().first()
    if sm and sm.get("latitude") is not None and sm.get("longitude") is not None:
        slat = float(sm["latitude"])
        slng = float(sm["longitude"])

    gps_anomalies: list[dict[str, Any]] = []
    cr = await db.execute(
        text(
            """
            SELECT id, employee_id, clock_time, location
            FROM clock_records
            WHERE tenant_id = CAST(:tid AS uuid)
              AND store_id = :sid
              AND is_deleted = FALSE
              AND clock_time >= :t0 AND clock_time < :t1
            """
        ),
        {
            "tid": tenant_id,
            "sid": store_id,
            "t0": datetime.combine(start_d, time.min, tzinfo=timezone.utc),
            "t1": datetime.combine(end_d + timedelta(days=1), time.min, tzinfo=timezone.utc),
        },
    )
    for row in cr.mappings().fetchall():
        parsed = _parse_location_payload(row.get("location"))
        if parsed is None:
            continue
        lat, lng = parsed
        if slat is None or slng is None:
            continue
        dist = _haversine_meters(lat, lng, slat, slng)
        if dist <= _GPS_THRESHOLD_M:
            continue
        ct = row["clock_time"]
        cts = ct.astimezone(timezone.utc).isoformat() if isinstance(ct, datetime) else str(ct)
        en = await db.execute(
            text(
                f"""
                SELECT emp_name FROM {EMPLOYEES_TABLE}
                WHERE tenant_id = CAST(:tid AS uuid) AND is_deleted = FALSE
                  AND id::text = :eid
                """
            ),
            {"tid": tenant_id, "eid": str(row["employee_id"])},
        )
        em = en.mappings().first()
        ename = str(em["emp_name"]) if em else str(row["employee_id"])
        gps_anomalies.append(
            {
                "employee_id": str(row["employee_id"]),
                "emp_name": ename,
                "clock_time": cts,
                "is_anomaly": True,
                "distance_meters": round(dist, 2),
                "threshold_meters": _GPS_THRESHOLD_M,
                "severity": "medium",
            },
        )

    device_anomalies: list[dict[str, Any]] = []
    dr = await db.execute(
        text(
            """
            SELECT DISTINCT a.id, a.employee_id, a.clock_time, a.device_info
            FROM clock_records a
            INNER JOIN clock_records b
              ON a.tenant_id = b.tenant_id
             AND a.store_id = b.store_id
             AND a.device_info = b.device_info
             AND a.device_info IS NOT NULL
             AND TRIM(a.device_info) <> ''
             AND a.employee_id <> b.employee_id
             AND b.clock_time BETWEEN a.clock_time - INTERVAL '30 minutes'
                                  AND a.clock_time + INTERVAL '30 minutes'
            WHERE a.tenant_id = CAST(:tid AS uuid)
              AND a.store_id = :sid
              AND a.is_deleted = FALSE
              AND b.is_deleted = FALSE
              AND a.clock_time >= :t0 AND a.clock_time < :t1
            """
        ),
        {
            "tid": tenant_id,
            "sid": store_id,
            "t0": datetime.combine(start_d, time.min, tzinfo=timezone.utc),
            "t1": datetime.combine(end_d + timedelta(days=1), time.min, tzinfo=timezone.utc),
        },
    )
    seen_dev: set[tuple[str, str, str]] = set()
    for row in dr.mappings().fetchall():
        eid = str(row["employee_id"])
        ct = row["clock_time"]
        cts = ct.astimezone(timezone.utc).isoformat() if isinstance(ct, datetime) else str(ct)
        fp = str(row["device_info"])
        key = (eid, fp, cts)
        if key in seen_dev:
            continue
        seen_dev.add(key)
        chk = await check_same_device(db, tenant_id, eid, fp, cts)
        if not chk["is_suspicious"]:
            continue
        en = await db.execute(
            text(
                f"""
                SELECT emp_name FROM {EMPLOYEES_TABLE}
                WHERE tenant_id = CAST(:tid AS uuid) AND is_deleted = FALSE
                  AND id::text = :eid
                """
            ),
            {"tid": tenant_id, "eid": eid},
        )
        em = en.mappings().first()
        ename = str(em["emp_name"]) if em else eid
        device_anomalies.append(
            {
                "employee_id": eid,
                "emp_name": ename,
                "clock_time": cts,
                "is_suspicious": True,
                "same_device_clocks": chk["same_device_clocks"],
                "severity": "high",
            },
        )

    def _sev_from_ot(row: dict[str, Any]) -> str:
        return _severity_for_rule_name(str(row.get("rule", "")))

    crit = high = medium = 0
    for v in overtime_violations:
        s = _sev_from_ot(v)
        if s == "critical":
            crit += 1
        elif s == "high":
            high += 1
        else:
            medium += 1
    for _ in rest_violations:
        high += 1
    for _ in gps_anomalies:
        medium += 1
    for _ in device_anomalies:
        high += 1

    total = len(overtime_violations) + len(rest_violations) + len(gps_anomalies) + len(device_anomalies)

    logger.info(
        "attendance_compliance.scan_all",
        tenant_id=tenant_id,
        store_id=store_id,
        period=period,
        total_violations=total,
    )

    return {
        "period": period,
        "overtime_violations": overtime_violations,
        "rest_violations": rest_violations,
        "gps_anomalies": gps_anomalies,
        "device_anomalies": device_anomalies,
        "summary": {
            "total_violations": total,
            "critical": crit,
            "high": high,
            "medium": medium,
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
#  AttendanceComplianceLogService — attendance_compliance_logs 表 CRUD
#
#  v255 新增表的持久化 + 查询 + 确认/驳回操作。
#  扫描方法委托给上面的函数，结果持久化到日志表。
# ══════════════════════════════════════════════════════════════════════════════


class AttendanceComplianceLogService:
    """考勤合规违规记录管理（基于 v255 attendance_compliance_logs 表）"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self._db = db
        self._tenant_id = tenant_id

    async def run_full_scan(
        self,
        check_date: str,
        store_id: str | None = None,
    ) -> dict[str, Any]:
        """运行全部深度合规检测，结果写入 attendance_compliance_logs"""
        await _set_tenant(self._db, self._tenant_id)

        if store_id:
            scan_result = await scan_all_compliance(
                self._db, self._tenant_id, store_id,
                (check_date, check_date),
            )
        else:
            scan_result = {
                "gps_anomalies": [],
                "device_anomalies": [],
                "overtime_violations": [],
                "rest_violations": [],
                "summary": {"total_violations": 0, "critical": 0, "high": 0, "medium": 0},
            }

        # 持久化扫描结果到 compliance_logs 表
        inserted = 0
        for item in scan_result.get("gps_anomalies", []):
            await self._insert_log(
                employee_id=item.get("employee_id", ""),
                employee_name=item.get("emp_name"),
                store_id=store_id,
                check_date=check_date,
                violation_type="gps_anomaly",
                severity=item.get("severity", "medium"),
                detail=item,
            )
            inserted += 1

        for item in scan_result.get("device_anomalies", []):
            await self._insert_log(
                employee_id=item.get("employee_id", ""),
                employee_name=item.get("emp_name"),
                store_id=store_id,
                check_date=check_date,
                violation_type="same_device",
                severity=item.get("severity", "high"),
                detail=item,
            )
            inserted += 1

        for item in scan_result.get("overtime_violations", []):
            await self._insert_log(
                employee_id=item.get("employee_id", ""),
                employee_name=item.get("emp_name"),
                store_id=store_id,
                check_date=check_date,
                violation_type="overtime_exceed",
                severity=_severity_for_rule_name(str(item.get("rule", ""))),
                detail=item,
            )
            inserted += 1

        for item in scan_result.get("rest_violations", []):
            await self._insert_log(
                employee_id=item.get("employee_id", ""),
                employee_name=item.get("emp_name"),
                store_id=store_id,
                check_date=check_date,
                violation_type="proxy_punch",
                severity="high",
                detail=item,
            )
            inserted += 1

        try:
            await self._db.commit()
        except (OperationalError, ProgrammingError) as exc:
            logger.warning("run_full_scan_commit_failed", error=str(exc))

        return {
            "scan_date": check_date,
            "store_id": store_id,
            "inserted": inserted,
            "summary": scan_result.get("summary", {}),
        }

    async def list_violations(
        self,
        store_id: str | None = None,
        violation_type: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict[str, Any]:
        """违规记录分页列表"""
        await _set_tenant(self._db, self._tenant_id)

        conditions = ["tenant_id = CAST(:tenant_id AS uuid)", "is_deleted = false"]
        params: dict[str, Any] = {"tenant_id": self._tenant_id}

        if store_id:
            conditions.append("store_id = CAST(:store_id AS uuid)")
            params["store_id"] = store_id
        if violation_type:
            conditions.append("violation_type = :violation_type")
            params["violation_type"] = violation_type
        if status:
            conditions.append("status = :status")
            params["status"] = status

        where = " AND ".join(conditions)

        count_q = text(f"SELECT COUNT(*) FROM attendance_compliance_logs WHERE {where}")
        try:
            count_result = await self._db.execute(count_q, params)
            total = count_result.scalar() or 0
        except (OperationalError, ProgrammingError) as exc:
            logger.warning("list_violations_count_failed", error=str(exc))
            total = 0

        offset = (page - 1) * size
        data_q = text(f"""
            SELECT id::text, employee_id::text, employee_name, store_id::text,
                   check_date, violation_type, severity, detail,
                   status, confirmed_by::text, confirmed_at, appeal_reason,
                   created_at, updated_at
            FROM attendance_compliance_logs
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """)
        params["limit"] = size
        params["offset"] = offset

        try:
            result = await self._db.execute(data_q, params)
            rows = [dict(r) for r in result.mappings()]
        except (OperationalError, ProgrammingError) as exc:
            logger.warning("list_violations_query_failed", error=str(exc))
            rows = []

        for row in rows:
            for key in ("check_date", "confirmed_at", "created_at", "updated_at"):
                val = row.get(key)
                if val and hasattr(val, "isoformat"):
                    row[key] = val.isoformat()

        return {"items": rows, "total": total, "page": page, "size": size}

    async def get_violation(self, log_id: str) -> dict[str, Any] | None:
        """获取单条违规详情"""
        await _set_tenant(self._db, self._tenant_id)
        q = text("""
            SELECT id::text, employee_id::text, employee_name, store_id::text,
                   check_date, violation_type, severity, detail,
                   status, confirmed_by::text, confirmed_at, appeal_reason,
                   created_at, updated_at
            FROM attendance_compliance_logs
            WHERE id = CAST(:log_id AS uuid)
              AND tenant_id = CAST(:tenant_id AS uuid)
              AND is_deleted = false
        """)
        try:
            result = await self._db.execute(
                q, {"log_id": log_id, "tenant_id": self._tenant_id},
            )
            row = result.mappings().first()
        except (OperationalError, ProgrammingError) as exc:
            logger.warning("get_violation_failed", error=str(exc))
            return None
        if not row:
            return None
        data = dict(row)
        for key in ("check_date", "confirmed_at", "created_at", "updated_at"):
            val = data.get(key)
            if val and hasattr(val, "isoformat"):
                data[key] = val.isoformat()
        return data

    async def confirm_violation(self, log_id: str, confirmer_id: str) -> dict[str, Any]:
        """确认违规"""
        await _set_tenant(self._db, self._tenant_id)
        q = text("""
            UPDATE attendance_compliance_logs
            SET status = 'confirmed',
                confirmed_by = CAST(:confirmer_id AS uuid),
                confirmed_at = NOW(),
                updated_at = NOW()
            WHERE id = CAST(:log_id AS uuid)
              AND tenant_id = CAST(:tenant_id AS uuid)
              AND is_deleted = false
              AND status = 'pending'
            RETURNING id::text
        """)
        try:
            result = await self._db.execute(
                q,
                {"log_id": log_id, "confirmer_id": confirmer_id, "tenant_id": self._tenant_id},
            )
            await self._db.commit()
            row = result.scalar()
        except (OperationalError, ProgrammingError) as exc:
            logger.warning("confirm_violation_failed", error=str(exc))
            return {"ok": False, "error": str(exc)}

        if not row:
            return {"ok": False, "error": "记录不存在或状态非pending"}
        return {"ok": True, "id": row}

    async def dismiss_violation(self, log_id: str, reason: str) -> dict[str, Any]:
        """驳回/申诉违规"""
        await _set_tenant(self._db, self._tenant_id)
        q = text("""
            UPDATE attendance_compliance_logs
            SET status = 'dismissed',
                appeal_reason = :reason,
                updated_at = NOW()
            WHERE id = CAST(:log_id AS uuid)
              AND tenant_id = CAST(:tenant_id AS uuid)
              AND is_deleted = false
              AND status IN ('pending', 'confirmed')
            RETURNING id::text
        """)
        try:
            result = await self._db.execute(
                q,
                {"log_id": log_id, "reason": reason, "tenant_id": self._tenant_id},
            )
            await self._db.commit()
            row = result.scalar()
        except (OperationalError, ProgrammingError) as exc:
            logger.warning("dismiss_violation_failed", error=str(exc))
            return {"ok": False, "error": str(exc)}

        if not row:
            return {"ok": False, "error": "记录不存在或状态不可驳回"}
        return {"ok": True, "id": row}

    async def get_compliance_stats(self, month: str | None = None) -> dict[str, Any]:
        """合规统计：各类型违规数量 + 状态分布"""
        await _set_tenant(self._db, self._tenant_id)
        month_filter = month or date.today().strftime("%Y-%m")
        start_date = f"{month_filter}-01"
        y, m_num = int(month_filter[:4]), int(month_filter[5:7])
        if m_num == 12:
            end_date_str = f"{y + 1}-01-01"
        else:
            end_date_str = f"{y}-{m_num + 1:02d}-01"

        q = text("""
            SELECT violation_type, severity, status, COUNT(*) AS cnt
            FROM attendance_compliance_logs
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND is_deleted = false
              AND check_date >= CAST(:start AS date)
              AND check_date < CAST(:end AS date)
            GROUP BY violation_type, severity, status
            ORDER BY violation_type, severity
        """)
        try:
            result = await self._db.execute(
                q,
                {"tenant_id": self._tenant_id, "start": start_date, "end": end_date_str},
            )
            rows = [dict(r) for r in result.mappings()]
        except (OperationalError, ProgrammingError) as exc:
            logger.warning("get_compliance_stats_failed", error=str(exc))
            rows = []

        by_type: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        by_status: dict[str, int] = {}
        total = 0
        for row in rows:
            cnt = int(row.get("cnt", 0))
            total += cnt
            vt = str(row.get("violation_type", "unknown"))
            sev = str(row.get("severity", "medium"))
            st = str(row.get("status", "pending"))
            by_type[vt] = by_type.get(vt, 0) + cnt
            by_severity[sev] = by_severity.get(sev, 0) + cnt
            by_status[st] = by_status.get(st, 0) + cnt

        return {
            "month": month_filter,
            "total": total,
            "by_type": by_type,
            "by_severity": by_severity,
            "by_status": by_status,
        }

    async def _insert_log(
        self,
        employee_id: str,
        employee_name: str | None,
        store_id: str | None,
        check_date: str,
        violation_type: str,
        severity: str,
        detail: dict[str, Any],
    ) -> None:
        """将检测结果写入 attendance_compliance_logs 表"""
        q = text("""
            INSERT INTO attendance_compliance_logs
                (tenant_id, employee_id, employee_name, store_id, check_date,
                 violation_type, severity, detail, status)
            VALUES
                (CAST(:tenant_id AS uuid), CAST(:employee_id AS uuid), :employee_name,
                 CAST(:store_id AS uuid), CAST(:check_date AS date),
                 :violation_type, :severity, CAST(:detail AS jsonb), 'pending')
        """)
        try:
            await self._db.execute(q, {
                "tenant_id": self._tenant_id,
                "employee_id": employee_id,
                "employee_name": employee_name,
                "store_id": store_id,
                "check_date": check_date,
                "violation_type": violation_type,
                "severity": severity,
                "detail": json.dumps(detail, ensure_ascii=False, default=str),
            })
        except (OperationalError, ProgrammingError) as exc:
            logger.warning(
                "insert_compliance_log_failed",
                error=str(exc),
                violation_type=violation_type,
            )
