"""
门店合规评分 — Store Compliance Scoring Engine

多维度合规评分、风险等级判定、趋势分析、每日批量评分。
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from shared.ontology.src.database import TenantSession

from . import (
    env_compliance_service,
    fire_safety_service,
    kitchen_monitor_service,
    license_manager_service,
    traceability_service,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 各维度权重
# ---------------------------------------------------------------------------
DIMENSION_WEIGHTS: dict[str, int] = {
    "trace": 25,
    "kitchen": 20,
    "env": 15,
    "fire": 15,
    "license": 25,
}


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------


def calculate_dimension_score(domain: str, metrics: dict[str, Any]) -> float:
    """单维度评分算法 (0-100)。

    各维度计算规则:
    - trace: 台账录入率*40 + 供应商资质覆盖*30 + 冷链记录完整*30
    - kitchen: 设备在线率*50 + 告警处理率*30 + 无严重告警*20
    - env: 油烟达标率*50 + 垃圾台账完整*50
    - fire: 设备检查及时*50 + 巡检按时*50
    - license: 证照覆盖率*60 + 无过期证照*40
    """
    if domain == "trace":
        batch_rate = metrics.get("batch_coverage_rate", 0)
        supplier_rate = metrics.get("supplier_cert_coverage", 0)
        coldchain_rate = metrics.get("coldchain_completeness", 0)
        return round(batch_rate * 0.4 + supplier_rate * 0.3 + coldchain_rate * 0.3, 1)

    if domain == "kitchen":
        online_rate = metrics.get("online_rate", 0)
        resolve_rate = metrics.get("resolve_rate", 0)
        no_critical = 100.0 if not metrics.get("has_unresolved_critical") else 0.0
        return round(online_rate * 0.5 + resolve_rate * 0.3 + no_critical * 0.2, 1)

    if domain == "env":
        compliance_rate = metrics.get("compliance_rate", 0)
        waste_completeness = metrics.get("waste_completeness", 0)
        return round(compliance_rate * 0.5 + waste_completeness * 0.5, 1)

    if domain == "fire":
        inspection_rate = metrics.get("inspection_timeliness", 0)
        patrol_rate = metrics.get("patrol_timeliness", 0)
        return round(inspection_rate * 0.5 + patrol_rate * 0.5, 1)

    if domain == "license":
        coverage = metrics.get("coverage_score", 0)
        no_expired = 100.0 if not metrics.get("has_expired") else 0.0
        return round(coverage * 0.6 + no_expired * 0.4, 1)

    return 0.0


def determine_risk_level(total_score: float) -> str:
    """风险等级: green(>=80) / yellow(>=60) / red(<60)。"""
    if total_score >= 80:
        return "green"
    if total_score >= 60:
        return "yellow"
    return "red"


def identify_top_issues(dimension_scores: dict[str, float]) -> list[dict]:
    """找出最紧急的待办事项 — 按得分从低到高排列。"""
    issues = []
    issue_labels = {
        "trace": "食安追溯",
        "kitchen": "明厨亮灶",
        "env": "环保合规",
        "fire": "消防安全",
        "license": "证照管理",
    }
    thresholds = {
        "critical": 50,
        "warning": 70,
    }

    sorted_dims = sorted(dimension_scores.items(), key=lambda x: x[1])
    for domain, score in sorted_dims:
        if score < thresholds["critical"]:
            severity = "critical"
        elif score < thresholds["warning"]:
            severity = "warning"
        else:
            continue
        issues.append(
            {
                "domain": domain,
                "label": issue_labels.get(domain, domain),
                "score": score,
                "severity": severity,
                "weight": DIMENSION_WEIGHTS.get(domain, 0),
            }
        )

    return issues


# ---------------------------------------------------------------------------
# 业务服务
# ---------------------------------------------------------------------------


async def calculate_store_score(tenant_id: str, store_id: str) -> dict:
    """计算单店合规评分。

    调用各领域 service 获取数据，按维度计算子分数，生成总分和 risk_level。
    """
    score_id = str(uuid.uuid4())
    log = logger.bind(tenant_id=tenant_id, store_id=store_id)

    # --- 采集各维度指标 ---

    # 1. 食安追溯
    trace_stats = await traceability_service.get_trace_stats(tenant_id, store_id)
    today_str = date.today().isoformat()
    completeness = await traceability_service.check_completeness(tenant_id, store_id, today_str)
    trace_metrics = {
        "batch_coverage_rate": trace_stats.get("batch_coverage_rate", 0),
        "supplier_cert_coverage": completeness.get("details", {}).get("supplier_cert_coverage", 0),
        "coldchain_completeness": min(trace_stats.get("coldchain_records", 0) * 10, 100),
    }

    # 2. 明厨亮灶
    online = await kitchen_monitor_service.get_online_rate(tenant_id, store_id)
    alert_stats = await kitchen_monitor_service.get_alert_stats(tenant_id, store_id, days=30)
    kitchen_metrics = {
        "online_rate": online.get("online_rate", 0),
        "resolve_rate": alert_stats.get("resolve_rate", 0),
        "has_unresolved_critical": False,  # 默认无
    }
    # 检查是否有未处理的 critical 告警
    async with TenantSession(tenant_id) as db:
        crit_row = await db.execute(
            text(
                "SELECT COUNT(*) AS cnt FROM civic_kitchen_alerts "
                "WHERE tenant_id = :tenant_id AND store_id = :store_id "
                "  AND severity = 'critical' AND resolved = FALSE"
            ),
            {"tenant_id": tenant_id, "store_id": store_id},
        )
        if (crit_row.scalar() or 0) > 0:
            kitchen_metrics["has_unresolved_critical"] = True

    # 3. 环保合规
    env_check = await env_compliance_service.check_emission_compliance(tenant_id, store_id)
    # 垃圾台账完整性: 最近7天是否每天都有记录
    async with TenantSession(tenant_id) as db:
        waste_days_row = await db.execute(
            text(
                "SELECT COUNT(DISTINCT recorded_date) AS days_covered "
                "FROM civic_waste_records "
                "WHERE tenant_id = :tenant_id AND store_id = :store_id "
                "  AND recorded_date >= CURRENT_DATE - 7"
            ),
            {"tenant_id": tenant_id, "store_id": store_id},
        )
        waste_days = waste_days_row.scalar() or 0
    env_metrics = {
        "compliance_rate": env_check.get("compliance_rate", 0),
        "waste_completeness": round(waste_days / 7 * 100, 1),
    }

    # 4. 消防安全
    equipment = await fire_safety_service.get_equipment(tenant_id, store_id)
    total_equip = len(equipment)
    overdue_equip = sum(1 for e in equipment if e.get("overdue"))
    inspection_timeliness = round((total_equip - overdue_equip) / total_equip * 100, 1) if total_equip else 100.0

    async with TenantSession(tenant_id) as db:
        patrol_row = await db.execute(
            text(
                "SELECT COUNT(*) AS cnt FROM civic_fire_inspections "
                "WHERE tenant_id = :tenant_id AND store_id = :store_id "
                "  AND inspection_date >= CURRENT_DATE - 30"
            ),
            {"tenant_id": tenant_id, "store_id": store_id},
        )
        patrol_count = patrol_row.scalar() or 0
    # 每月至少4次巡检为满分
    patrol_timeliness = min(round(patrol_count / 4 * 100, 1), 100.0)
    fire_metrics = {
        "inspection_timeliness": inspection_timeliness,
        "patrol_timeliness": patrol_timeliness,
    }

    # 5. 证照管理
    coverage = await license_manager_service.get_license_coverage(tenant_id, store_id)
    licenses = await license_manager_service.get_licenses(tenant_id, store_id)
    has_expired = any(l.get("renewal_urgency") == "expired" for l in licenses)
    license_metrics = {
        "coverage_score": coverage.get("score", 0),
        "has_expired": has_expired,
    }

    # --- 计算各维度得分 ---
    dimension_scores = {
        "trace": calculate_dimension_score("trace", trace_metrics),
        "kitchen": calculate_dimension_score("kitchen", kitchen_metrics),
        "env": calculate_dimension_score("env", env_metrics),
        "fire": calculate_dimension_score("fire", fire_metrics),
        "license": calculate_dimension_score("license", license_metrics),
    }

    # 加权总分
    total_score = sum(dimension_scores[d] * DIMENSION_WEIGHTS[d] / 100 for d in dimension_scores)
    total_score = round(total_score, 1)
    risk_level = determine_risk_level(total_score)
    top_issues = identify_top_issues(dimension_scores)

    # --- 存储评分 ---
    async with TenantSession(tenant_id) as db:
        await db.execute(
            text(
                "INSERT INTO civic_compliance_scores "
                "(id, tenant_id, store_id, total_score, risk_level, "
                " trace_score, kitchen_score, env_score, fire_score, license_score, "
                " scored_at) "
                "VALUES (:id, :tenant_id, :store_id, :total_score, :risk_level, "
                " :trace, :kitchen, :env, :fire, :license, NOW())"
            ),
            {
                "id": score_id,
                "tenant_id": tenant_id,
                "store_id": store_id,
                "total_score": total_score,
                "risk_level": risk_level,
                "trace": dimension_scores["trace"],
                "kitchen": dimension_scores["kitchen"],
                "env": dimension_scores["env"],
                "fire": dimension_scores["fire"],
                "license": dimension_scores["license"],
            },
        )
        await db.commit()

    log.info("store_score_calculated", total=total_score, risk=risk_level)
    return {
        "id": score_id,
        "store_id": store_id,
        "total_score": total_score,
        "risk_level": risk_level,
        "dimension_scores": dimension_scores,
        "top_issues": top_issues,
    }


async def get_store_score(tenant_id: str, store_id: str) -> dict | None:
    """获取最新评分。"""
    async with TenantSession(tenant_id) as db:
        row = await db.execute(
            text(
                "SELECT id, total_score, risk_level, "
                "  trace_score, kitchen_score, env_score, fire_score, license_score, "
                "  scored_at "
                "FROM civic_compliance_scores "
                "WHERE tenant_id = :tenant_id AND store_id = :store_id "
                "ORDER BY scored_at DESC LIMIT 1"
            ),
            {"tenant_id": tenant_id, "store_id": store_id},
        )
        result = row.mappings().first()
        if not result:
            return None

        data = dict(result)
        data["dimension_scores"] = {
            "trace": data.pop("trace_score"),
            "kitchen": data.pop("kitchen_score"),
            "env": data.pop("env_score"),
            "fire": data.pop("fire_score"),
            "license": data.pop("license_score"),
        }
        data["top_issues"] = identify_top_issues(data["dimension_scores"])
        return data


async def get_brand_scores(tenant_id: str) -> list[dict]:
    """全品牌评分排行 — 每个门店的最新评分。"""
    async with TenantSession(tenant_id) as db:
        rows = await db.execute(
            text(
                "SELECT DISTINCT ON (store_id) "
                "  store_id, total_score, risk_level, "
                "  trace_score, kitchen_score, env_score, fire_score, license_score, "
                "  scored_at "
                "FROM civic_compliance_scores "
                "WHERE tenant_id = :tenant_id "
                "ORDER BY store_id, scored_at DESC"
            ),
            {"tenant_id": tenant_id},
        )
        results = []
        for r in rows.mappings().all():
            data = dict(r)
            data["dimension_scores"] = {
                "trace": data.pop("trace_score"),
                "kitchen": data.pop("kitchen_score"),
                "env": data.pop("env_score"),
                "fire": data.pop("fire_score"),
                "license": data.pop("license_score"),
            }
            results.append(data)

        # 按总分升序（最差的排前面，方便关注）
        results.sort(key=lambda x: x["total_score"])

    return results


async def get_score_trend(
    tenant_id: str,
    store_id: str,
    days: int = 90,
) -> list[dict]:
    """评分趋势 — 最近N天。"""
    async with TenantSession(tenant_id) as db:
        rows = await db.execute(
            text(
                "SELECT DATE(scored_at) AS day, "
                "  AVG(total_score) AS avg_score, "
                "  MIN(total_score) AS min_score, "
                "  MAX(total_score) AS max_score "
                "FROM civic_compliance_scores "
                "WHERE tenant_id = :tenant_id AND store_id = :store_id "
                "  AND scored_at >= CURRENT_DATE - :days "
                "GROUP BY DATE(scored_at) "
                "ORDER BY day"
            ),
            {"tenant_id": tenant_id, "store_id": store_id, "days": days},
        )
        return [dict(r) for r in rows.mappings().all()]


async def daily_score_batch(tenant_id: str) -> dict:
    """每日批量评分 — 对所有门店计算合规评分。"""
    log = logger.bind(tenant_id=tenant_id)

    async with TenantSession(tenant_id) as db:
        store_rows = await db.execute(
            text("SELECT id FROM stores WHERE tenant_id = :tenant_id AND status = 'active'"),
            {"tenant_id": tenant_id},
        )
        store_ids = [r["id"] for r in store_rows.mappings().all()]

    scored = 0
    errors = 0
    results = []

    for sid in store_ids:
        try:
            score = await calculate_store_score(tenant_id, sid)
            results.append({"store_id": sid, "score": score["total_score"], "risk": score["risk_level"]})
            scored += 1
        except (SQLAlchemyError, KeyError, ValueError) as exc:
            log.error("score_batch_error", store_id=sid, error=str(exc), exc_info=True)
            results.append({"store_id": sid, "error": str(exc)})
            errors += 1

    log.info("daily_score_batch_completed", scored=scored, errors=errors, total=len(store_ids))
    return {
        "total_stores": len(store_ids),
        "scored": scored,
        "errors": errors,
        "results": results,
    }
