from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/org/compliance", tags=["compliance"])

_SCAN_TYPES = frozenset({"all", "documents", "performance", "attendance"})


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


def _err(code: str, message: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"ok": False, "error": {"code": code, "message": message}},
    )


class ScanRequest(BaseModel):
    scan_type: str = Field(default="all", description="扫描范围")


_MOCK_DOCUMENTS: list[dict[str, Any]] = [
    {"employee_id": "emp-mock-01", "emp_name": "张三", "document_type": "health_cert", "expiry_date": "2026-04-15", "days_remaining": 13, "severity": "high", "category": "document"},
    {"employee_id": "emp-mock-02", "emp_name": "李四", "document_type": "id_card", "expiry_date": "2026-04-28", "days_remaining": 26, "severity": "low", "category": "document"},
]
_MOCK_PERFORMANCE: list[dict[str, Any]] = [
    {"employee_id": "emp-mock-03", "emp_name": "王五", "document_type": "", "expiry_date": "", "days_remaining": 0, "severity": "high", "category": "performance"},
]
_MOCK_ATTENDANCE: list[dict[str, Any]] = [
    {"employee_id": "emp-mock-04", "emp_name": "赵六", "document_type": "", "expiry_date": "", "days_remaining": 0, "severity": "medium", "category": "attendance"},
]


def _build_compliance_resp(
    severity: Optional[str] = None,
) -> dict[str, Any]:
    docs = _MOCK_DOCUMENTS if severity is None else [a for a in _MOCK_DOCUMENTS if a["severity"] == severity]
    perf = _MOCK_PERFORMANCE if severity is None else [a for a in _MOCK_PERFORMANCE if a["severity"] == severity]
    att = _MOCK_ATTENDANCE if severity is None else [a for a in _MOCK_ATTENDANCE if a["severity"] == severity]
    all_items = docs + perf + att
    return {
        "documents": docs,
        "performance": perf,
        "attendance": att,
        "summary": {
            "total": len(all_items),
            "critical": sum(1 for x in all_items if x["severity"] == "critical"),
            "high": sum(1 for x in all_items if x["severity"] == "high"),
            "medium": sum(1 for x in all_items if x["severity"] == "medium"),
            "low": sum(1 for x in all_items if x["severity"] == "low"),
        },
    }


def scan_expiring_documents(threshold_days: int) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "items": [
            {
                "document_id": "doc-mock-1",
                "document_type": "food_license",
                "holder_name": "尝在一起 XX 路店",
                "store_id": "store-mock-a",
                "expires_on": "2026-04-20",
                "days_remaining": 18,
            },
            {
                "document_id": "doc-mock-2",
                "document_type": "health_cert",
                "holder_name": "张三",
                "employee_id": "emp-mock-01",
                "store_id": "store-mock-b",
                "expires_on": "2026-04-28",
                "days_remaining": 25,
            },
        ],
        "threshold_days": threshold_days,
        "scanned_at": now,
    }


def scan_low_performers(consecutive_months: int) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "items": [
            {
                "employee_id": "emp-mock-low-1",
                "employee_name": "李四",
                "store_id": "store-mock-c",
                "role": "服务员",
                "avg_score": 62.5,
                "consecutive_low_months": 3,
            },
            {
                "employee_id": "emp-mock-low-2",
                "employee_name": "王五",
                "store_id": "store-mock-c",
                "role": "传菜",
                "avg_score": 58.0,
                "consecutive_low_months": 4,
            },
        ],
        "consecutive_months": consecutive_months,
        "scanned_at": now,
    }


@router.get("/alerts")
async def get_compliance_alerts(
    severity: Optional[str] = Query(None, description="严重级别筛选"),
    document_type: Optional[str] = Query(None, description="证件类型筛选"),
):
    """查询合规预警列表（当前为 Mock）。"""
    return _ok(_build_compliance_resp(severity=severity))


@router.post("/scan")
async def post_compliance_scan(body: ScanRequest):
    """手动触发合规扫描（当前为 Mock）。"""
    if body.scan_type not in _SCAN_TYPES:
        return _err(
            "invalid_scan_type",
            f"scan_type 须为 {sorted(_SCAN_TYPES)} 之一",
        )
    return _ok(_build_compliance_resp())


@router.get("/documents/expiring")
async def get_expiring_compliance_documents(
    threshold_days: int = Query(30, ge=1, le=365, description="距到期天数阈值"),
):
    """返回即将到期的证件列表（当前为 Mock）。"""
    data = scan_expiring_documents(threshold_days)
    return _ok(data)


@router.get("/performance/low")
async def get_low_performance_employees(
    consecutive_months: int = Query(3, ge=1, le=24, description="连续低绩效月数阈值"),
):
    """返回低绩效员工列表（当前为 Mock）。"""
    data = scan_low_performers(consecutive_months)
    return _ok(data)
