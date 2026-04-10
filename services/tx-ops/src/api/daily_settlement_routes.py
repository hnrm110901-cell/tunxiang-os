"""日清日结主控 API 路由 — 真实DB + RLS + Mock fallback

端点:
  POST /api/v1/ops/settlement/run                   一键执行日清日结（E1-E7）
  GET  /api/v1/ops/settlement/status/{store_id}     各节点完成状态
  GET  /api/v1/ops/settlement/checklist/{store_id}  日清待完成清单

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import SettlementEventType
from shared.ontology.src.database import get_db

from ..repositories.ops_repository import OpsRepository

# 从同包路由复用聚合函数（内存变量已迁移至真实DB，不再导入）
from .daily_summary_routes import _aggregate_orders
from .performance_routes import (
    _aggregate_cashier_performance,
    _aggregate_chef_performance,
    _aggregate_waiter_performance,
    _calc_commission_fen,
)
# 以下路由均已迁移至真实DB，此处保留本地空字典供各 fallback 降级使用
_shifts: dict = {}
_local_summaries: dict = {}
_local_issues: dict = {}
_local_reports: dict = {}
_local_performance: dict = {}

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
#  节点状态检查（优先DB，fallback内存）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _check_e1_status_db(
    repo: OpsRepository, store_id: str, shift_date: date
) -> Dict[str, Any]:
    """E1: 检查当日所有班次是否已交班确认（DB版）。"""
    day_shifts = await repo.list_shifts(store_id, shift_date)
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


def _check_e1_status_fallback(store_id: str, date_str: str, tenant_id: str) -> Dict[str, Any]:
    """E1 fallback: 内存版。"""
    day_shifts = [
        s for s in _shifts.values()
        if s["tenant_id"] == tenant_id and s["store_id"] == store_id
        and s["shift_date"] == date_str and not s.get("is_deleted", False)
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
        "detail": {"total_shifts": len(day_shifts), "confirmed": len(confirmed),
                   "pending": len(pending), "disputed": len(disputed)},
    }


async def _check_e2_status_db(
    repo: OpsRepository, store_id: str, summary_date: date
) -> Dict[str, Any]:
    """E2: 检查日汇总是否已生成并锁定（DB版）。"""
    summary = await repo.get_daily_summary(store_id, summary_date)
    if not summary:
        return {"completed": False, "message": "日汇总未生成", "detail": None}
    if summary["status"] == "locked":
        return {"completed": True, "message": "日汇总已锁定", "detail": summary}
    return {"completed": False, "message": f"日汇总状态: {summary['status']}，尚未锁定", "detail": summary}


def _check_e2_status_fallback(store_id: str, date_str: str, tenant_id: str) -> Dict[str, Any]:
    key = f"{tenant_id}:{store_id}:{date_str}"
    summary = _local_summaries.get(key)
    if not summary:
        return {"completed": False, "message": "日汇总未生成", "detail": None}
    if summary["status"] == "locked":
        return {"completed": True, "message": "日汇总已锁定", "detail": summary}
    return {"completed": False, "message": f"日汇总状态: {summary['status']}，尚未锁定", "detail": summary}


async def _check_e5_status_db(
    repo: OpsRepository, store_id: str, issue_date: date
) -> Dict[str, Any]:
    """E5: 检查当日未处理关键问题（DB版）。"""
    counts = await repo.count_open_critical_issues(store_id, issue_date)
    completed = counts["open_critical_high"] == 0
    return {
        "completed": completed,
        "message": "已完成" if completed else f"存在 {counts['open_critical_high']} 个未处理的 critical/high 问题",
        "detail": counts,
    }


def _check_e5_status_fallback(store_id: str, date_str: str, tenant_id: str) -> Dict[str, Any]:
    day_issues = [
        i for i in _local_issues.values()
        if i["tenant_id"] == tenant_id and i["store_id"] == store_id
        and i["issue_date"] == date_str and not i.get("is_deleted", False)
    ]
    open_critical = [
        i for i in day_issues
        if i["status"] in {"open", "in_progress"} and i["severity"] in {"critical", "high"}
    ]
    open_all = [i for i in day_issues if i["status"] in {"open", "in_progress"}]
    completed = len(open_critical) == 0
    return {
        "completed": completed,
        "message": "已完成" if completed else f"存在 {len(open_critical)} 个未处理的 critical/high 问题",
        "detail": {"total_issues": len(day_issues), "open_critical_high": len(open_critical), "open_all": len(open_all)},
    }


def _check_e7_status_fallback(store_id: str, date_str: str, tenant_id: str) -> Dict[str, Any]:
    day_perfs = [
        p for p in _local_performance.values()
        if p["tenant_id"] == tenant_id and p["store_id"] == store_id and p["perf_date"] == date_str
    ]
    completed = len(day_perfs) > 0
    return {
        "completed": completed,
        "message": f"已计算 {len(day_perfs)} 名员工绩效" if completed else "员工绩效未计算",
        "detail": {"employee_count": len(day_perfs)},
    }


def _check_e8_status_fallback(store_id: str, date_str: str, tenant_id: str) -> Dict[str, Any]:
    day_reports = [
        r for r in _local_reports.values()
        if r["tenant_id"] == tenant_id and r["store_id"] == store_id
        and r["inspection_date"] == date_str and not r.get("is_deleted", False)
    ]
    if not day_reports:
        return {"completed": True, "message": "今日无巡店计划（可选节点）", "detail": []}
    unacknowledged = [r for r in day_reports if r["status"] in {"submitted"}]
    return {
        "completed": len(unacknowledged) == 0,
        "message": "已完成" if len(unacknowledged) == 0 else f"{len(unacknowledged)} 份报告门店未确认",
        "detail": {"total_reports": len(day_reports), "unacknowledged": len(unacknowledged)},
    }


async def _build_node_statuses(
    store_id: str, settlement_date: date, date_str: str, tenant_id: str,
    repo: Optional[OpsRepository] = None, use_db: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """构建各节点状态，优先DB，fallback内存。"""
    if use_db and repo:
        try:
            e1 = await _check_e1_status_db(repo, store_id, settlement_date)
            e2 = await _check_e2_status_db(repo, store_id, settlement_date)
            e5 = await _check_e5_status_db(repo, store_id, settlement_date)
            # E7 和 E8 从 DB 查询
            perfs, _ = await repo.list_performance(store_id, settlement_date, page=1, size=1)
            e7_completed = len(perfs) > 0
            perfs_all, _ = await repo.list_performance(store_id, settlement_date, page=1, size=10000)
            e7 = {
                "completed": e7_completed,
                "message": f"已计算 {len(perfs_all)} 名员工绩效" if e7_completed else "员工绩效未计算",
                "detail": {"employee_count": len(perfs_all)},
            }
            inspections, _ = await repo.list_inspections(
                store_id=store_id, start_date=settlement_date, end_date=settlement_date,
                page=1, size=10000,
            )
            if not inspections:
                e8 = {"completed": True, "message": "今日无巡店计划（可选节点）", "detail": []}
            else:
                unack = [r for r in inspections if r["status"] in {"submitted"}]
                e8 = {
                    "completed": len(unack) == 0,
                    "message": "已完成" if len(unack) == 0 else f"{len(unack)} 份报告门店未确认",
                    "detail": {"total_reports": len(inspections), "unacknowledged": len(unack)},
                }
            return {
                "E1_班次交班": e1,
                "E2_日营业汇总": e2,
                "E5_问题预警": e5,
                "E7_员工绩效": e7,
                "E8_巡店质检": e8,
            }
        except (ConnectionRefusedError, OSError, RuntimeError):
            pass  # fall through to memory

    return {
        "E1_班次交班": _check_e1_status_fallback(store_id, date_str, tenant_id),
        "E2_日营业汇总": _check_e2_status_fallback(store_id, date_str, tenant_id),
        "E5_问题预警": _check_e5_status_fallback(store_id, date_str, tenant_id),
        "E7_员工绩效": _check_e7_status_fallback(store_id, date_str, tenant_id),
        "E8_巡店质检": _check_e8_status_fallback(store_id, date_str, tenant_id),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/run")
async def run_daily_settlement(
    body: RunSettlementRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """一键执行日清日结。"""
    date_str = body.settlement_date.isoformat()
    now = datetime.now(tz=timezone.utc)
    steps: List[Dict[str, Any]] = []
    use_db = True

    log.info("settlement_run_started", store_id=body.store_id,
             settlement_date=date_str, operator_id=body.operator_id,
             tenant_id=x_tenant_id)

    try:
        repo = OpsRepository(db, x_tenant_id)
        # 测试DB连接
        await repo._set_rls()
    except (ConnectionRefusedError, OSError, RuntimeError, ValueError):
        repo = None
        use_db = False
        log.warning("settlement_run_db_fallback", tenant_id=x_tenant_id)

    # ── E1: 班次交班检查 ─────────────────────────────────────────────
    if use_db and repo:
        e1 = await _check_e1_status_db(repo, body.store_id, body.settlement_date)
    else:
        e1 = _check_e1_status_fallback(body.store_id, date_str, x_tenant_id)
    steps.append({"node": "E1_班次交班", "action": "check", **e1})

    # ── E2: 自动生成日汇总 ──────────────────────────────────────────
    if use_db and repo:
        existing_summary = await repo.get_daily_summary(body.store_id, body.settlement_date)
        if not existing_summary or (body.force_regenerate and existing_summary["status"] != "locked"):
            aggregated = await _aggregate_orders(body.store_id, body.settlement_date, x_tenant_id, db=db)
            record = await repo.upsert_daily_summary(body.store_id, body.settlement_date, aggregated)
            steps.append({"node": "E2_日营业汇总", "action": "generated", "completed": True,
                          "message": "日汇总已自动生成（草稿状态，需手动确认锁定）",
                          "summary_id": record["id"]})
        else:
            e2 = await _check_e2_status_db(repo, body.store_id, body.settlement_date)
            steps.append({"node": "E2_日营业汇总", "action": "check", **e2})
    else:
        e2_key = f"{x_tenant_id}:{body.store_id}:{date_str}"
        e2_existing = _local_summaries.get(e2_key)
        if not e2_existing or (body.force_regenerate and e2_existing["status"] != "locked"):
            import uuid as _uuid
            # fallback 路径无 DB 连接，返回空聚合结构
            aggregated = {
                "total_orders": 0, "dine_in_orders": 0, "takeaway_orders": 0,
                "banquet_orders": 0, "total_revenue_fen": 0, "actual_revenue_fen": 0,
                "total_discount_fen": 0, "max_discount_pct": None,
                "abnormal_discounts": 0, "avg_table_value_fen": None,
            }
            summary_id = e2_existing["id"] if e2_existing else str(_uuid.uuid4())
            record = {
                "id": summary_id, "tenant_id": x_tenant_id, "store_id": body.store_id,
                "summary_date": date_str, **aggregated, "status": "draft",
                "confirmed_by": None, "confirmed_at": None,
                "created_at": e2_existing["created_at"] if e2_existing else now.isoformat(),
                "updated_at": now.isoformat(), "is_deleted": False,
            }
            _local_summaries[e2_key] = record
            steps.append({"node": "E2_日营业汇总", "action": "generated", "completed": True,
                          "message": "日汇总已自动生成（草稿状态，需手动确认锁定）",
                          "summary_id": summary_id})
        else:
            e2 = _check_e2_status_fallback(body.store_id, date_str, x_tenant_id)
            steps.append({"node": "E2_日营业汇总", "action": "check", **e2})

    # ── E5: 自动扫描预警 ──────────────────────────────────────────────
    from .issues_routes import _scan_discount_abuse, _scan_kds_timeout, _scan_low_inventory
    kds_timeouts = await _scan_kds_timeout(body.store_id, x_tenant_id)
    discount_abuses = await _scan_discount_abuse(body.store_id, x_tenant_id)
    low_inventory = await _scan_low_inventory(body.store_id, x_tenant_id)
    auto_created = len(kds_timeouts) + len(discount_abuses) + len(low_inventory)
    steps.append({
        "node": "E5_问题预警", "action": "auto_scan", "completed": True,
        "message": f"自动扫描完成，新增 {auto_created} 条预警",
        "breakdown": {"kds_timeout": len(kds_timeouts), "discount_abuse": len(discount_abuses),
                      "low_inventory": len(low_inventory)},
    })

    # ── E6: 整改跟踪状态检查 ─────────────────────────────────────────
    if use_db and repo:
        e6 = await _check_e5_status_db(repo, body.store_id, body.settlement_date)
    else:
        e6 = _check_e5_status_fallback(body.store_id, date_str, x_tenant_id)
    steps.append({"node": "E6_整改跟踪", "action": "check", **e6})

    # ── E7: 自动计算员工绩效 ─────────────────────────────────────────
    cashier_data = await _aggregate_cashier_performance(body.store_id, body.settlement_date, x_tenant_id)
    chef_data = await _aggregate_chef_performance(body.store_id, body.settlement_date, x_tenant_id)
    waiter_data = await _aggregate_waiter_performance(body.store_id, body.settlement_date, x_tenant_id)
    perf_count = 0

    if use_db and repo:
        for role, emp_list in [("cashier", cashier_data), ("chef", chef_data), ("waiter", waiter_data)]:
            for emp in emp_list:
                commission = _calc_commission_fen(role, emp)
                await repo.upsert_performance(
                    store_id=body.store_id, perf_date=body.settlement_date,
                    employee_id=emp["employee_id"], employee_name=emp.get("employee_name", ""),
                    role=role, orders_handled=emp.get("orders_handled", 0),
                    revenue_generated_fen=emp.get("revenue_generated_fen", 0),
                    dishes_completed=emp.get("dishes_completed", 0),
                    tables_served=emp.get("tables_served", 0),
                    avg_service_score=emp.get("avg_service_score"),
                    base_commission_fen=commission,
                )
                perf_count += 1
    else:
        import uuid as _uuid2
        for role, emp_list in [("cashier", cashier_data), ("chef", chef_data), ("waiter", waiter_data)]:
            for emp in emp_list:
                emp_id = emp["employee_id"]
                key = f"{x_tenant_id}:{body.store_id}:{date_str}:{emp_id}"
                if key not in _local_performance or body.force_regenerate:
                    commission = _calc_commission_fen(role, emp)
                    existing = _local_performance.get(key)
                    _local_performance[key] = {
                        "id": existing["id"] if existing else str(_uuid2.uuid4()),
                        "tenant_id": x_tenant_id, "store_id": body.store_id,
                        "perf_date": date_str, "employee_id": emp_id,
                        "employee_name": emp.get("employee_name", ""),
                        "role": role, "orders_handled": emp.get("orders_handled", 0),
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
        "node": "E7_员工绩效", "action": "calculated", "completed": True,
        "message": f"已计算 {perf_count} 名员工绩效", "employee_count": perf_count,
    })

    # ── E8: 巡店质检 ───────────────────────────────────────
    if use_db and repo:
        inspections, _ = await repo.list_inspections(
            store_id=body.store_id, start_date=body.settlement_date,
            end_date=body.settlement_date, page=1, size=10000,
        )
        if not inspections:
            e8 = {"completed": True, "message": "今日无巡店计划（可选节点）", "detail": []}
        else:
            unack = [r for r in inspections if r["status"] in {"submitted"}]
            e8 = {
                "completed": len(unack) == 0,
                "message": "已完成" if len(unack) == 0 else f"{len(unack)} 份报告门店未确认",
                "detail": {"total_reports": len(inspections), "unacknowledged": len(unack)},
            }
    else:
        e8 = _check_e8_status_fallback(body.store_id, date_str, x_tenant_id)
    steps.append({"node": "E8_巡店质检", "action": "check", **e8})

    # ── 汇总整体状态 ──────────────────────────────────────────────────
    blocking_incomplete = [
        s for s in steps
        if not s.get("completed", False) and s["node"] not in {"E8_巡店质检"}
    ]
    overall_done = len(blocking_incomplete) == 0

    log.info("settlement_run_completed", store_id=body.store_id,
             settlement_date=date_str, overall_done=overall_done,
             blocking_count=len(blocking_incomplete), tenant_id=x_tenant_id,
             source="db" if use_db else "fallback")

    # ─── Phase 1 平行事件写入：日清日结完成 ───
    if overall_done:
        asyncio.create_task(emit_event(
            event_type=SettlementEventType.DAILY_CLOSED,
            tenant_id=x_tenant_id,
            stream_id=f"{body.store_id}:{date_str}",
            payload={
                "settlement_date": date_str,
                "store_id": body.store_id,
                "operator_id": body.operator_id,
                "steps_completed": len(steps),
                "overall_completed": overall_done,
            },
            store_id=body.store_id,
            source_service="tx-ops",
            metadata={"trigger": "manual_run"},
        ))

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
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """查询各节点完成状态。"""
    target_date = settlement_date or date.today()
    date_str = target_date.isoformat()

    use_db = True
    repo: Optional[OpsRepository] = None
    try:
        repo = OpsRepository(db, x_tenant_id)
        await repo._set_rls()
    except (ConnectionRefusedError, OSError, RuntimeError, ValueError):
        use_db = False

    nodes = await _build_node_statuses(
        store_id, target_date, date_str, x_tenant_id, repo=repo, use_db=use_db
    )
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
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """日清待完成清单。返回未完成节点及操作指引。"""
    target_date = checklist_date or date.today()
    date_str = target_date.isoformat()

    use_db = True
    repo: Optional[OpsRepository] = None
    try:
        repo = OpsRepository(db, x_tenant_id)
        await repo._set_rls()
    except (ConnectionRefusedError, OSError, RuntimeError, ValueError):
        use_db = False

    nodes = await _build_node_statuses(
        store_id, target_date, date_str, x_tenant_id, repo=repo, use_db=use_db
    )

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
