"""日清日结主控 API 路由

端点:
  POST /api/v1/ops/settlement/run                   一键执行日清日结（E1-E7）
  GET  /api/v1/ops/settlement/status/{store_id}     各节点完成状态
  GET  /api/v1/ops/settlement/checklist/{store_id}  日清待完成清单

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, Field

from .daily_summary_routes import _summaries
from .inspection_routes import _reports
from .issues_routes import _issues
from .performance_routes import _performance

# 从同包路由复用内存存储（生产替换为统一 DB 查询）
from .shift_routes import _shifts

router = APIRouter(prefix="/api/v1/ops/settlement", tags=["ops-settlement"])
log = structlog.get_logger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class RunSettlementRequest(BaseModel):
    store_id: str = Field(..., description="门店ID")
    settlement_date: date = Field(..., description="结算日期")
    operator_id: str = Field(..., description="执行人UUID")
    force_regenerate: bool = Field(False, description="是否强制重新生成已有汇总")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  节点状态检查辅助
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _check_e1_status(store_id: str, date_str: str, tenant_id: str) -> Dict[str, Any]:
    """E1: 检查当日所有班次是否已交班确认。"""
    day_shifts = [
        s for s in _shifts.values()
        if s["tenant_id"] == tenant_id
        and s["store_id"] == store_id
        and s["shift_date"] == date_str
        and not s.get("is_deleted", False)
    ]
    if not day_shifts:
        return {"completed": False, "message": "无班次记录", "detail": []}

    pending = [s for s in day_shifts if s["status"] == "pending"]
    disputed = [s for s in day_shifts if s["status"] == "disputed"]
    confirmed = [s for s in day_shifts if s["status"] == "confirmed"]

    completed = len(pending) == 0 and len(disputed) == 0
    return {
        "completed": completed,
        "message": "已完成" if completed else f"{len(pending)} 个班次未确认，{len(disputed)} 个班次有争议",
        "detail": {
            "total_shifts": len(day_shifts),
            "confirmed": len(confirmed),
            "pending": len(pending),
            "disputed": len(disputed),
        },
    }


def _check_e2_status(store_id: str, date_str: str, tenant_id: str) -> Dict[str, Any]:
    """E2: 检查日汇总是否已生成并锁定。"""
    key = f"{tenant_id}:{store_id}:{date_str}"
    summary = _summaries.get(key)
    if not summary:
        return {"completed": False, "message": "日汇总未生成", "detail": None}
    if summary["status"] == "locked":
        return {"completed": True, "message": "日汇总已锁定", "detail": summary}
    return {
        "completed": False,
        "message": f"日汇总状态: {summary['status']}，尚未锁定",
        "detail": summary,
    }


def _check_e5_status(store_id: str, date_str: str, tenant_id: str) -> Dict[str, Any]:
    """E5: 检查当日问题预警是否有未处理的 critical/high 级别问题。"""
    day_issues = [
        i for i in _issues.values()
        if i["tenant_id"] == tenant_id
        and i["store_id"] == store_id
        and i["issue_date"] == date_str
        and not i.get("is_deleted", False)
    ]
    open_critical = [
        i for i in day_issues
        if i["status"] in {"open", "in_progress"}
        and i["severity"] in {"critical", "high"}
    ]
    open_all = [i for i in day_issues if i["status"] in {"open", "in_progress"}]

    completed = len(open_critical) == 0
    return {
        "completed": completed,
        "message": (
            "已完成" if completed
            else f"存在 {len(open_critical)} 个未处理的 critical/high 问题"
        ),
        "detail": {
            "total_issues": len(day_issues),
            "open_critical_high": len(open_critical),
            "open_all": len(open_all),
        },
    }


def _check_e7_status(store_id: str, date_str: str, tenant_id: str) -> Dict[str, Any]:
    """E7: 检查员工绩效是否已计算。"""
    day_perfs = [
        p for p in _performance.values()
        if p["tenant_id"] == tenant_id
        and p["store_id"] == store_id
        and p["perf_date"] == date_str
    ]
    completed = len(day_perfs) > 0
    return {
        "completed": completed,
        "message": f"已计算 {len(day_perfs)} 名员工绩效" if completed else "员工绩效未计算",
        "detail": {"employee_count": len(day_perfs)},
    }


def _check_e8_status(store_id: str, date_str: str, tenant_id: str) -> Dict[str, Any]:
    """E8: 检查巡店报告状态（可选节点，无报告也算通过）。"""
    day_reports = [
        r for r in _reports.values()
        if r["tenant_id"] == tenant_id
        and r["store_id"] == store_id
        and r["inspection_date"] == date_str
        and not r.get("is_deleted", False)
    ]
    if not day_reports:
        return {"completed": True, "message": "今日无巡店计划（可选节点）", "detail": []}

    unacknowledged = [r for r in day_reports if r["status"] in {"submitted"}]
    return {
        "completed": len(unacknowledged) == 0,
        "message": (
            "已完成" if len(unacknowledged) == 0
            else f"{len(unacknowledged)} 份报告门店未确认"
        ),
        "detail": {
            "total_reports": len(day_reports),
            "unacknowledged": len(unacknowledged),
        },
    }


def _build_node_statuses(
    store_id: str, date_str: str, tenant_id: str
) -> Dict[str, Dict[str, Any]]:
    return {
        "E1_班次交班": _check_e1_status(store_id, date_str, tenant_id),
        "E2_日营业汇总": _check_e2_status(store_id, date_str, tenant_id),
        "E5_问题预警": _check_e5_status(store_id, date_str, tenant_id),
        "E7_员工绩效": _check_e7_status(store_id, date_str, tenant_id),
        "E8_巡店质检": _check_e8_status(store_id, date_str, tenant_id),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/run")
async def run_daily_settlement(
    body: RunSettlementRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """
    一键执行日清日结。
    依次触发 E1→E2→E5→E7 状态检查，
    自动执行可以自动化的节点（E2 生成汇总、E5 自动扫描、E7 计算绩效）。
    返回各节点执行结果与整体完成状态。
    """
    date_str = body.settlement_date.isoformat()
    now = datetime.now(tz=timezone.utc)
    steps: List[Dict[str, Any]] = []

    log.info("settlement_run_started", store_id=body.store_id,
             settlement_date=date_str, operator_id=body.operator_id,
             tenant_id=x_tenant_id)

    # ── E1: 班次交班检查 ─────────────────────────────────────────────
    e1 = _check_e1_status(body.store_id, date_str, x_tenant_id)
    steps.append({"node": "E1_班次交班", "action": "check", **e1})

    # ── E2: 自动生成日汇总（若未锁定）──────────────────────────────────
    e2_key = f"{x_tenant_id}:{body.store_id}:{date_str}"
    e2_existing = _summaries.get(e2_key)
    if not e2_existing or (body.force_regenerate and e2_existing["status"] != "locked"):
        # 懒加载 avoid circular import
        import uuid as _uuid

        from .daily_summary_routes import _aggregate_orders

        aggregated = await _aggregate_orders(body.store_id, body.settlement_date, x_tenant_id)
        summary_id = e2_existing["id"] if e2_existing else str(_uuid.uuid4())
        record = {
            "id": summary_id,
            "tenant_id": x_tenant_id,
            "store_id": body.store_id,
            "summary_date": date_str,
            **aggregated,
            "status": "draft",
            "confirmed_by": None,
            "confirmed_at": None,
            "created_at": e2_existing["created_at"] if e2_existing else now.isoformat(),
            "updated_at": now.isoformat(),
            "is_deleted": False,
        }
        _summaries[e2_key] = record
        steps.append({"node": "E2_日营业汇总", "action": "generated", "completed": True,
                      "message": "日汇总已自动生成（草稿状态，需手动确认锁定）",
                      "summary_id": summary_id})
    else:
        e2 = _check_e2_status(body.store_id, date_str, x_tenant_id)
        steps.append({"node": "E2_日营业汇总", "action": "check", **e2})

    # ── E5: 自动扫描预警──────────────────────────────────────────────
    from .issues_routes import (
        _scan_discount_abuse,
        _scan_kds_timeout,
        _scan_low_inventory,
    )
    today = body.settlement_date
    kds_timeouts = await _scan_kds_timeout(body.store_id, x_tenant_id)
    discount_abuses = await _scan_discount_abuse(body.store_id, x_tenant_id)
    low_inventory = await _scan_low_inventory(body.store_id, x_tenant_id)
    auto_created = len(kds_timeouts) + len(discount_abuses) + len(low_inventory)
    steps.append({
        "node": "E5_问题预警",
        "action": "auto_scan",
        "completed": True,
        "message": f"自动扫描完成，新增 {auto_created} 条预警",
        "breakdown": {
            "kds_timeout": len(kds_timeouts),
            "discount_abuse": len(discount_abuses),
            "low_inventory": len(low_inventory),
        },
    })

    # ── E6: 整改跟踪状态检查 ─────────────────────────────────────────
    e6 = _check_e5_status(body.store_id, date_str, x_tenant_id)
    steps.append({"node": "E6_整改跟踪", "action": "check", **e6})

    # ── E7: 自动计算员工绩效 ─────────────────────────────────────────
    import uuid as _uuid2

    from .performance_routes import (
        _aggregate_cashier_performance,
        _aggregate_chef_performance,
        _aggregate_waiter_performance,
        _calc_commission_fen,
    )
    cashier_data = await _aggregate_cashier_performance(body.store_id, body.settlement_date, x_tenant_id)
    chef_data = await _aggregate_chef_performance(body.store_id, body.settlement_date, x_tenant_id)
    waiter_data = await _aggregate_waiter_performance(body.store_id, body.settlement_date, x_tenant_id)
    perf_count = 0
    for role, emp_list in [("cashier", cashier_data), ("chef", chef_data), ("waiter", waiter_data)]:
        for emp in emp_list:
            emp_id = emp["employee_id"]
            key = f"{x_tenant_id}:{body.store_id}:{date_str}:{emp_id}"
            if key not in _performance or body.force_regenerate:
                commission = _calc_commission_fen(role, emp)
                existing = _performance.get(key)
                _performance[key] = {
                    "id": existing["id"] if existing else str(_uuid2.uuid4()),
                    "tenant_id": x_tenant_id,
                    "store_id": body.store_id,
                    "perf_date": date_str,
                    "employee_id": emp_id,
                    "employee_name": emp.get("employee_name", ""),
                    "role": role,
                    "orders_handled": emp.get("orders_handled", 0),
                    "revenue_generated_fen": emp.get("revenue_generated_fen", 0),
                    "dishes_completed": emp.get("dishes_completed", 0),
                    "tables_served": emp.get("tables_served", 0),
                    "avg_service_score": emp.get("avg_service_score"),
                    "base_commission_fen": commission,
                    "created_at": existing["created_at"] if existing else now.isoformat(),
                    "updated_at": now.isoformat(),
                }
                perf_count += 1
    steps.append({
        "node": "E7_员工绩效",
        "action": "calculated",
        "completed": True,
        "message": f"已计算 {perf_count} 名员工绩效",
        "employee_count": perf_count,
    })

    # ── E8: 巡店质检（检查状态，不自动创建）───────────────────────────
    e8 = _check_e8_status(body.store_id, date_str, x_tenant_id)
    steps.append({"node": "E8_巡店质检", "action": "check", **e8})

    # ── 汇总整体状态 ──────────────────────────────────────────────────
    blocking_incomplete = [
        s for s in steps
        if not s.get("completed", False)
        and s["node"] not in {"E8_巡店质检"}  # E8 为可选节点
    ]
    overall_done = len(blocking_incomplete) == 0

    log.info("settlement_run_completed", store_id=body.store_id,
             settlement_date=date_str, overall_done=overall_done,
             blocking_count=len(blocking_incomplete), tenant_id=x_tenant_id)

    return {
        "ok": True,
        "data": {
            "store_id": body.store_id,
            "settlement_date": date_str,
            "overall_completed": overall_done,
            "blocking_incomplete": [s["node"] for s in blocking_incomplete],
            "executed_at": now.isoformat(),
            "operator_id": body.operator_id,
            "steps": steps,
        },
    }


@router.get("/status/{store_id}")
async def get_settlement_status(
    store_id: str,
    settlement_date: Optional[date] = Query(None, description="结算日期，默认今日"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """查询各节点完成状态。"""
    target_date = settlement_date or date.today()
    date_str = target_date.isoformat()

    nodes = _build_node_statuses(store_id, date_str, x_tenant_id)
    completed_count = sum(1 for n in nodes.values() if n.get("completed", False))
    total_count = len(nodes)

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "settlement_date": date_str,
            "overall_progress": f"{completed_count}/{total_count}",
            "overall_completed": completed_count == total_count,
            "nodes": nodes,
        },
    }


@router.get("/checklist/{store_id}")
async def get_settlement_checklist(
    store_id: str,
    checklist_date: Optional[date] = Query(None, alias="date", description="日期，默认今日"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """日清待完成清单。返回未完成节点及操作指引。"""
    target_date = checklist_date or date.today()
    date_str = target_date.isoformat()

    nodes = _build_node_statuses(store_id, date_str, x_tenant_id)

    checklist: List[Dict[str, Any]] = []
    for node_name, status in nodes.items():
        checklist.append({
            "node": node_name,
            "completed": status.get("completed", False),
            "message": status.get("message", ""),
            "action_hint": _get_action_hint(node_name, status),
        })

    pending_items = [c for c in checklist if not c["completed"]]
    completed_items = [c for c in checklist if c["completed"]]

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "date": date_str,
            "pending_count": len(pending_items),
            "completed_count": len(completed_items),
            "pending": pending_items,
            "completed": completed_items,
        },
    }


def _get_action_hint(node_name: str, status: Dict[str, Any]) -> str:
    if status.get("completed"):
        return ""
    hints: Dict[str, str] = {
        "E1_班次交班": "请前往「班次管理」确认所有未完成交班",
        "E2_日营业汇总": "请前往「日汇总」确认并锁定数据",
        "E5_问题预警": "存在高优先级未处理问题，请立即处理 critical/high 级别问题",
        "E6_整改跟踪": "存在未解决问题，请前往「问题管理」跟进处理进度",
        "E7_员工绩效": "请调用「绩效计算」API 完成员工当日绩效汇算",
        "E8_巡店质检": "巡店报告待门店确认，请及时签收",
    }
    return hints.get(node_name, "请完成该节点操作")
