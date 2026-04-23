"""
Agent 编排主服务 — Civic Agent Orchestrator

事件驱动处理、自然语言交互 Skill、每日合规巡检。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import structlog
from sqlalchemy import text

from shared.ontology.src.database import TenantSession

from . import (
    compliance_score_service,
    env_compliance_service,
    kitchen_monitor_service,
    license_manager_service,
    submission_engine,
    traceability_service,
)

logger = structlog.get_logger(__name__)


# ===========================================================================
# 事件驱动处理
# ===========================================================================


async def on_purchase_received(event: dict[str, Any]) -> dict:
    """进货入库 -> 自动录入追溯台账。

    event: tenant_id, store_id, items: [{item_name, quantity, unit, supplier_id, batch_no, ...}]
    """
    tenant_id = event["tenant_id"]
    store_id = event["store_id"]
    items = event.get("items", [])
    log = logger.bind(tenant_id=tenant_id, store_id=store_id, event="purchase_received")

    results = []
    for item in items:
        record = await traceability_service.record_inbound(tenant_id, store_id, item)
        results.append(record)

        # 判断是否需要自动上报
        if submission_engine.should_auto_submit("trace"):
            await submission_engine.submit_to_platform(
                tenant_id,
                store_id,
                "trace",
                {"type": "inbound", "record": record},
            )

    log.info("purchase_processed", item_count=len(items))
    return {"event": "purchase_received", "processed": len(items), "results": results}


async def on_employee_onboarded(event: dict[str, Any]) -> dict:
    """新员工入职 -> 健康证检查。

    event: tenant_id, store_id, employee_id, employee_name
    """
    tenant_id = event["tenant_id"]
    store_id = event["store_id"]
    employee_id = event["employee_id"]
    employee_name = event.get("employee_name", "")
    log = logger.bind(tenant_id=tenant_id, employee_id=employee_id, event="employee_onboarded")

    # 检查该员工是否已有健康证
    async with TenantSession(tenant_id) as db:
        row = await db.execute(
            text(
                "SELECT id, expiry_date FROM civic_health_certs "
                "WHERE tenant_id = :tenant_id AND employee_id = :employee_id "
                "ORDER BY expiry_date DESC LIMIT 1"
            ),
            {"tenant_id": tenant_id, "employee_id": employee_id},
        )
        cert = row.mappings().first()

    if not cert:
        log.warning("no_health_cert", employee_name=employee_name)
        return {
            "event": "employee_onboarded",
            "employee_id": employee_id,
            "health_cert_status": "missing",
            "action_required": f"员工 {employee_name} 尚无健康证，请尽快办理",
        }

    cert_data = dict(cert)
    expiry = cert_data.get("expiry_date")
    if expiry:
        risk = traceability_service.check_expiry_risk(expiry)
        if risk["status"] != "valid":
            log.warning("health_cert_expiry", status=risk["status"], days=risk["days_remaining"])
            return {
                "event": "employee_onboarded",
                "employee_id": employee_id,
                "health_cert_status": risk["status"],
                "days_remaining": risk["days_remaining"],
                "action_required": f"员工 {employee_name} 健康证{risk['status']}，剩余{risk['days_remaining']}天",
            }

    log.info("health_cert_valid", employee_name=employee_name)
    return {
        "event": "employee_onboarded",
        "employee_id": employee_id,
        "health_cert_status": "valid",
    }


async def on_waste_recorded(event: dict[str, Any]) -> dict:
    """废弃物记录 -> 同步垃圾台账。

    event: tenant_id, store_id, waste_type, weight_kg, collector, ...
    """
    tenant_id = event["tenant_id"]
    store_id = event["store_id"]
    log = logger.bind(tenant_id=tenant_id, store_id=store_id, event="waste_recorded")

    data = {
        "waste_type": event["waste_type"],
        "weight_kg": event["weight_kg"],
        "collector": event.get("collector"),
        "collector_license": event.get("collector_license"),
        "disposal_method": event.get("disposal_method"),
        "recorded_date": event.get("recorded_date"),
    }
    record = await env_compliance_service.record_waste_disposal(tenant_id, store_id, data)

    # 自动上报
    if submission_engine.should_auto_submit("env"):
        await submission_engine.submit_to_platform(
            tenant_id,
            store_id,
            "env",
            {"type": "waste_disposal", "record": record},
        )

    log.info("waste_synced", record_id=record["id"])
    return {"event": "waste_recorded", "record": record}


async def on_kitchen_alert(event: dict[str, Any]) -> dict:
    """AI告警 -> 评估是否需要上报。

    event: tenant_id, store_id, device_id, alert_type, confidence, snapshot_url, detail
    """
    tenant_id = event["tenant_id"]
    store_id = event["store_id"]
    device_id = event["device_id"]
    log = logger.bind(tenant_id=tenant_id, store_id=store_id, event="kitchen_alert")

    alert_data = {
        "alert_type": event["alert_type"],
        "confidence": event.get("confidence", 0.0),
        "snapshot_url": event.get("snapshot_url"),
        "detail": event.get("detail"),
    }
    alert = await kitchen_monitor_service.record_ai_alert(tenant_id, store_id, device_id, alert_data)

    # 评估是否自动上报
    if submission_engine.should_auto_submit("kitchen", alert_type=event["alert_type"]):
        submission = await submission_engine.submit_to_platform(
            tenant_id,
            store_id,
            "kitchen",
            {"type": "ai_alert", "alert": alert},
        )
        log.info("kitchen_alert_auto_submitted", alert_id=alert["id"], submission=submission["status"])
        alert["auto_submitted"] = True
        alert["submission_status"] = submission["status"]
    else:
        alert["auto_submitted"] = False

    log.info("kitchen_alert_processed", alert_id=alert["id"], severity=alert["severity"])
    return {"event": "kitchen_alert", "alert": alert}


# ===========================================================================
# Agent Skill（自然语言交互）
# ===========================================================================


async def skill_check_compliance(tenant_id: str, store_id: str) -> str:
    """返回门店合规状态的自然语言摘要。"""
    score_data = await compliance_score_service.get_store_score(tenant_id, store_id)
    if not score_data:
        # 没有评分记录，先计算一次
        score_data = await compliance_score_service.calculate_store_score(tenant_id, store_id)

    total = score_data["total_score"]
    risk = score_data["risk_level"]
    dims = score_data["dimension_scores"]
    issues = score_data.get("top_issues", [])

    risk_labels = {"green": "低风险", "yellow": "中风险", "red": "高风险"}
    risk_label = risk_labels.get(risk, risk)

    lines = [
        f"门店合规评分: {total}分 ({risk_label})",
        "",
        "各维度得分:",
        f"  食安追溯: {dims.get('trace', 0)}分",
        f"  明厨亮灶: {dims.get('kitchen', 0)}分",
        f"  环保合规: {dims.get('env', 0)}分",
        f"  消防安全: {dims.get('fire', 0)}分",
        f"  证照管理: {dims.get('license', 0)}分",
    ]

    if issues:
        lines.append("")
        lines.append("需要关注的问题:")
        for issue in issues:
            sev_label = "紧急" if issue["severity"] == "critical" else "注意"
            lines.append(f"  [{sev_label}] {issue['label']}: {issue['score']}分")

    return "\n".join(lines)


async def skill_trace_ingredient(
    tenant_id: str,
    store_id: str,
    keyword: str,
) -> str:
    """追溯食材来源 — 根据关键词搜索食材的进货记录和供应商信息。"""
    safe_keyword = keyword.replace("%", r"\%").replace("_", r"\_")
    async with TenantSession(tenant_id) as db:
        rows = await db.execute(
            text(
                "SELECT r.item_name, r.batch_no, r.quantity, r.unit, "
                "  r.supplier_id, r.production_date, r.expiry_date, r.recorded_at, "
                "  s.name AS supplier_name, s.license_no AS supplier_license "
                "FROM trace_inbound_records r "
                "LEFT JOIN civic_suppliers s ON s.tenant_id = r.tenant_id AND s.id = r.supplier_id "
                "WHERE r.tenant_id = :tenant_id AND r.store_id = :store_id "
                r"  AND r.item_name ILIKE :keyword ESCAPE '\' "
                "ORDER BY r.recorded_at DESC "
                "LIMIT 10"
            ),
            {"tenant_id": tenant_id, "store_id": store_id, "keyword": f"%{safe_keyword}%"},
        )
        records = [dict(r) for r in rows.mappings().all()]

    if not records:
        return f'未找到与 "{keyword}" 相关的进货记录'

    lines = [f'找到 {len(records)} 条与 "{keyword}" 相关的记录:']
    for r in records:
        supplier_info = r.get("supplier_name", "未知供应商")
        if r.get("supplier_license"):
            supplier_info += f" (许可证: {r['supplier_license']})"
        lines.append("")
        lines.append(f"  品名: {r['item_name']}")
        lines.append(f"  批次: {r.get('batch_no', '无')}")
        lines.append(f"  数量: {r['quantity']}{r.get('unit', '')}")
        lines.append(f"  供应商: {supplier_info}")
        lines.append(f"  入库时间: {r['recorded_at']}")
        if r.get("expiry_date"):
            risk = traceability_service.check_expiry_risk(r["expiry_date"])
            if risk["status"] != "valid":
                lines.append(f"  保质期状态: {risk['status']}（剩余{risk['days_remaining']}天）")

    return "\n".join(lines)


async def skill_license_overview(tenant_id: str) -> str:
    """证照到期总览。"""
    expiring_licenses = await license_manager_service.get_expiring_licenses(tenant_id, days=60)
    expiring_certs = await license_manager_service.get_expiring_health_certs(tenant_id, days=60)

    lines = ["证照到期总览:"]

    # 证照
    expired_lic = [l for l in expiring_licenses if l.get("renewal_urgency") == "expired"]
    soon_lic = [l for l in expiring_licenses if l.get("renewal_urgency") == "expiring_soon"]

    if expired_lic:
        lines.append(f"\n已过期证照 ({len(expired_lic)} 件):")
        for l in expired_lic:
            lines.append(f"  - {l['license_type']} (门店 {l['store_id']})")
    if soon_lic:
        lines.append(f"\n即将到期证照 ({len(soon_lic)} 件):")
        for l in soon_lic:
            days = l.get("days_remaining", "?")
            lines.append(f"  - {l['license_type']} (门店 {l['store_id']}, 剩余{days}天)")

    # 健康证
    expired_cert = [c for c in expiring_certs if c.get("renewal_urgency") == "expired"]
    soon_cert = [c for c in expiring_certs if c.get("renewal_urgency") == "expiring_soon"]

    if expired_cert:
        lines.append(f"\n已过期健康证 ({len(expired_cert)} 人):")
        for c in expired_cert:
            lines.append(f"  - {c.get('employee_name', c['employee_id'])} (门店 {c['store_id']})")
    if soon_cert:
        lines.append(f"\n即将到期健康证 ({len(soon_cert)} 人):")
        for c in soon_cert:
            days = c.get("days_remaining", "?")
            lines.append(f"  - {c.get('employee_name', c['employee_id'])} (门店 {c['store_id']}, 剩余{days}天)")

    if not expiring_licenses and not expiring_certs:
        lines.append("\n所有证照和健康证均在有效期内，无需处理。")

    return "\n".join(lines)


# ===========================================================================
# 每日任务
# ===========================================================================


async def daily_compliance_scan(tenant_id: str) -> dict:
    """全品牌合规巡检 — 每日执行。

    - 证照到期扫描
    - 健康证到期扫描
    - 追溯完整性检查（所有门店）
    - 生成合规评分
    - 返回巡检摘要
    """
    log = logger.bind(tenant_id=tenant_id, task="daily_compliance_scan")
    today_str = date.today().isoformat()
    summary_parts = []

    # 1. 证照到期扫描
    expiring_licenses = await license_manager_service.get_expiring_licenses(tenant_id, days=30)
    expired_count = sum(1 for l in expiring_licenses if l.get("renewal_urgency") == "expired")
    expiring_count = sum(1 for l in expiring_licenses if l.get("renewal_urgency") == "expiring_soon")
    if expired_count or expiring_count:
        summary_parts.append(f"证照: {expired_count}件已过期, {expiring_count}件即将到期")
    else:
        summary_parts.append("证照: 全部有效")

    # 2. 健康证到期扫描
    expiring_certs = await license_manager_service.get_expiring_health_certs(tenant_id, days=30)
    expired_cert_count = sum(1 for c in expiring_certs if c.get("renewal_urgency") == "expired")
    expiring_cert_count = sum(1 for c in expiring_certs if c.get("renewal_urgency") == "expiring_soon")
    if expired_cert_count or expiring_cert_count:
        summary_parts.append(f"健康证: {expired_cert_count}人已过期, {expiring_cert_count}人即将到期")
    else:
        summary_parts.append("健康证: 全部有效")

    # 3. 供应商资质到期
    expiring_suppliers = await traceability_service.check_supplier_cert_expiry(tenant_id)
    if expiring_suppliers:
        summary_parts.append(f"供应商资质: {len(expiring_suppliers)}家需关注")
    else:
        summary_parts.append("供应商资质: 全部有效")

    # 4. 追溯完整性（所有门店）
    async with TenantSession(tenant_id) as db:
        store_rows = await db.execute(
            text("SELECT id, name FROM stores WHERE tenant_id = :tenant_id AND status = 'active'"),
            {"tenant_id": tenant_id},
        )
        stores = [dict(r) for r in store_rows.mappings().all()]

    trace_issues = []
    for store in stores:
        completeness = await traceability_service.check_completeness(
            tenant_id,
            store["id"],
            today_str,
        )
        if completeness["score"] < 80:
            trace_issues.append(
                {
                    "store_id": store["id"],
                    "store_name": store.get("name"),
                    "score": completeness["score"],
                }
            )

    if trace_issues:
        summary_parts.append(f"追溯完整性: {len(trace_issues)}家门店低于80分")
    else:
        summary_parts.append("追溯完整性: 全部达标")

    # 5. 生成合规评分
    score_result = await compliance_score_service.daily_score_batch(tenant_id)
    red_stores = [r for r in score_result.get("results", []) if r.get("risk") == "red"]
    yellow_stores = [r for r in score_result.get("results", []) if r.get("risk") == "yellow"]
    summary_parts.append(
        f"合规评分: {score_result['scored']}家已评分, {len(red_stores)}家高风险, {len(yellow_stores)}家中风险"
    )

    # 组装摘要
    scan_summary = "\n".join([f"[{date.today()}] 每日合规巡检摘要:"] + [f"  - {p}" for p in summary_parts])

    log.info(
        "daily_scan_completed",
        stores=len(stores),
        expired_licenses=expired_count,
        expired_certs=expired_cert_count,
        trace_issues=len(trace_issues),
        red_stores=len(red_stores),
    )

    return {
        "scan_date": today_str,
        "summary": scan_summary,
        "details": {
            "expiring_licenses": expiring_licenses,
            "expiring_health_certs": expiring_certs,
            "expiring_suppliers": expiring_suppliers,
            "trace_issues": trace_issues,
            "score_result": score_result,
            "red_stores": red_stores,
            "yellow_stores": yellow_stores,
        },
    }
