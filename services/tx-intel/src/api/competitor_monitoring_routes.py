"""竞品监控 API 路由 — Phase 3

集成 CompetitorWatchAgent + 美团/抖音/小红书平台数据
  POST /api/v1/intel/competitor-monitor/scan            — 触发竞品数据扫描
  GET  /api/v1/intel/competitor-monitor/weekly-report   — 生成竞对情报周报
  GET  /api/v1/intel/competitor-monitor/alerts          — 获取活跃威胁预警
  POST /api/v1/intel/competitor-monitor/platform-snapshot — 从平台适配器拉取竞对快照
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any, Optional

import httpx
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/intel/competitor-monitor", tags=["competitor-monitoring"])

AGENT_SERVICE_URL = os.getenv("AGENT_SERVICE_URL", "http://tx-agent:8008")


# ─── 请求模型 ─────────────────────────────────────────────────────────────────


class ScanBody(BaseModel):
    """竞品扫描请求体"""

    model_config = ConfigDict(extra="ignore")

    store_id: str
    competitors: list[dict[str, Any]] = []
    brand_data: dict[str, Any] = {}


class PlatformSnapshotBody(BaseModel):
    """平台快照请求体"""

    model_config = ConfigDict(extra="ignore")

    store_id: str
    platforms: list[str] = ["meituan", "douyin", "xiaohongshu"]


# ─── 内部工具 ─────────────────────────────────────────────────────────────────


def _require_tenant(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return x_tenant_id


async def _dispatch_agent(
    tenant_id: str,
    action: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """调用 tx-agent 服务的 dispatch 接口；连接失败时返回 None（由调用方处理 fallback）"""
    url = f"{AGENT_SERVICE_URL}/api/v1/agent/dispatch"
    payload = {
        "agent_id": "competitor_watch",
        "action": action,
        "params": params,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload, headers={"X-Tenant-ID": tenant_id})
        resp.raise_for_status()
        return resp.json()


# ─── 路由 ─────────────────────────────────────────────────────────────────────


@router.post("/scan")
async def scan_competitors(
    body: ScanBody,
    tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """触发竞品数据扫描 + 威胁预警生成

    调用 CompetitorWatchAgent 的 scan_competitor_updates + generate_threat_alert 动作。
    """
    params = {
        "store_id": body.store_id,
        "competitors": body.competitors,
        "brand_data": body.brand_data,
    }

    scan_result: dict[str, Any] = {}
    alert_result: dict[str, Any] = {}

    try:
        scan_result = await _dispatch_agent(tenant_id, "scan_competitor_updates", params)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.warning(
            "competitor_monitor.scan.agent_unavailable",
            action="scan_competitor_updates",
            exc=str(exc),
        )
        scan_result = {
            "ok": False,
            "_is_mock": True,
            "message": "tx-agent 服务暂时不可用，扫描结果降级为空",
        }

    try:
        alert_result = await _dispatch_agent(tenant_id, "generate_threat_alert", params)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.warning(
            "competitor_monitor.scan.alert_unavailable",
            action="generate_threat_alert",
            exc=str(exc),
        )
        alert_result = {
            "ok": False,
            "_is_mock": True,
            "message": "威胁预警生成降级，请稍后重试",
        }

    return {
        "ok": True,
        "data": {
            "store_id": body.store_id,
            "scan": scan_result.get("data", scan_result),
            "alert": alert_result.get("data", alert_result),
        },
    }


@router.get("/weekly-report")
async def get_weekly_report(
    store_id: str = Query(...),
    days: int = Query(default=7, ge=1, le=30),
    tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """生成竞对情报周报

    调用 CompetitorWatchAgent 的 generate_weekly_intel_report + summarize_weekly 动作。
    """
    params = {
        "store_id": store_id,
        "days": days,
        "start_date": (date.today() - timedelta(days=days)).isoformat(),
        "end_date": date.today().isoformat(),
    }

    report_result: dict[str, Any] = {}
    summary_result: dict[str, Any] = {}

    try:
        report_result = await _dispatch_agent(tenant_id, "generate_weekly_intel_report", params)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.warning(
            "competitor_monitor.weekly_report.agent_unavailable",
            action="generate_weekly_intel_report",
            exc=str(exc),
        )
        report_result = {
            "ok": False,
            "_is_mock": True,
            "message": "tx-agent 服务暂时不可用，周报生成降级",
        }

    try:
        summary_result = await _dispatch_agent(tenant_id, "summarize_weekly", params)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.warning(
            "competitor_monitor.weekly_report.summary_unavailable",
            action="summarize_weekly",
            exc=str(exc),
        )
        summary_result = {
            "ok": False,
            "_is_mock": True,
            "message": "周报摘要生成降级",
        }

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "period_days": days,
            "report": report_result.get("data", report_result),
            "summary": summary_result.get("data", summary_result),
        },
    }


@router.get("/alerts")
async def get_active_alerts(
    store_id: str = Query(...),
    threat_level: Optional[str] = Query(default=None, description="过滤级别: critical/high/medium/low"),
    tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """获取活跃竞品威胁预警列表

    从 competitor_snapshots + competitor_brands 读取近14天快照，
    将含活跃促销活动的竞对映射为威胁预警。
    threat_level 由活跃促销数量和快照新鲜度推导：
      3+ 促销 → critical，2 促销 → high，1 促销 → medium，0 促销 → low
    """
    if threat_level and threat_level not in ("critical", "high", "medium", "low"):
        raise HTTPException(status_code=400, detail="threat_level 必须为 critical/high/medium/low 之一")

    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        # 取近14天内每个竞对品牌的最新快照，提取活跃促销
        sql = text("""
            SELECT DISTINCT ON (cs.competitor_brand_id)
                cs.id::text                     AS snapshot_id,
                cb.id::text                     AS competitor_id,
                cb.name                         AS competitor_name,
                cs.active_promotions,
                cs.avg_rating,
                cs.snapshot_date,
                cs.source,
                cb.price_tier
            FROM competitor_snapshots cs
            JOIN competitor_brands cb ON cb.id = cs.competitor_brand_id
            WHERE cs.tenant_id = :tenant_id
              AND cb.is_active = TRUE
              AND cs.snapshot_date >= CURRENT_DATE - INTERVAL '14 days'
            ORDER BY cs.competitor_brand_id, cs.snapshot_date DESC
        """)
        result = await db.execute(sql, {"tenant_id": tenant_id})
        rows = result.fetchall()

        _level_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}

        alerts: list[dict[str, Any]] = []
        for row in rows:
            d = dict(row._mapping)
            promotions: list[dict[str, Any]] = d.get("active_promotions") or []
            promo_count = len(promotions)

            if promo_count >= 3:
                level = "critical"
            elif promo_count == 2:
                level = "high"
            elif promo_count == 1:
                level = "medium"
            else:
                level = "low"

            if threat_level and level != threat_level:
                continue

            # 构建事件描述：汇总促销标题
            if promotions:
                promo_titles = "、".join(p.get("title", "未知活动") for p in promotions[:3])
                event = f"当前活跃促销：{promo_titles}"
            else:
                event = "暂无活跃促销，关注评分变化"

            alerts.append(
                {
                    "alert_id": d["snapshot_id"],
                    "competitor_id": d["competitor_id"],
                    "competitor": d["competitor_name"],
                    "threat_level": level,
                    "active_promotions": promotions,
                    "event": event,
                    "avg_rating": float(d["avg_rating"]) if d.get("avg_rating") is not None else None,
                    "source": d.get("source"),
                    "created_at": d["snapshot_date"].isoformat() if d.get("snapshot_date") else None,
                }
            )

        # 按威胁级别排序
        alerts.sort(key=lambda a: _level_rank.get(a["threat_level"], 99))
        critical_count = sum(1 for a in alerts if a["threat_level"] == "critical")

        logger.info(
            "get_active_alerts",
            tenant_id=tenant_id,
            store_id=store_id,
            total=len(alerts),
            critical_count=critical_count,
        )
        return {
            "ok": True,
            "data": {
                "store_id": store_id,
                "active_alerts": alerts,
                "total": len(alerts),
                "critical_count": critical_count,
            },
        }

    except SQLAlchemyError as exc:
        logger.warning("get_active_alerts_db_unavailable", error=str(exc), store_id=store_id)
        return {
            "ok": True,
            "data": {
                "store_id": store_id,
                "active_alerts": [],
                "total": 0,
                "critical_count": 0,
                "degraded": True,
            },
        }


@router.post("/platform-snapshot")
async def get_platform_snapshot(
    body: PlatformSnapshotBody,
    tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """从平台适配器拉取竞对快照（美团/抖音/小红书）

    对每个请求的 platform 调用对应适配器，汇总竞对相关数据。
    如某平台适配器不可导入（旧环境），静默跳过。
    """
    snapshots: dict[str, Any] = {}
    today = date.today().isoformat()
    week_ago = (date.today() - timedelta(days=7)).isoformat()

    for platform in body.platforms:
        if platform == "meituan":
            try:
                from shared.integrations.meituan_marketing import MeituanMarketingAdapter

                adapter = MeituanMarketingAdapter()
                promotions = await adapter.get_promotion_list(tenant_id, body.store_id)
                attribution = await adapter.get_order_attribution(tenant_id, body.store_id, week_ago, today)
                snapshots["meituan"] = {
                    "promotions": promotions,
                    "order_attribution": attribution,
                }
                logger.info("competitor_monitor.snapshot.meituan_ok", store_id=body.store_id)
            except ImportError:
                logger.warning("competitor_monitor.snapshot.meituan_import_error")
            except (ValueError, OSError) as exc:
                logger.warning("competitor_monitor.snapshot.meituan_error", exc=str(exc))
                snapshots["meituan"] = {"error": str(exc)}

        elif platform == "douyin":
            try:
                from shared.integrations.douyin_marketing import DouyinMarketingAdapter

                adapter = DouyinMarketingAdapter()
                content_perf = await adapter.get_content_performance(tenant_id, body.store_id, days=7)
                ad_roi = await adapter.get_ad_roi_data(tenant_id, body.store_id)
                snapshots["douyin"] = {
                    "content_performance": content_perf,
                    "ad_roi": ad_roi,
                }
                logger.info("competitor_monitor.snapshot.douyin_ok", store_id=body.store_id)
            except ImportError:
                logger.warning("competitor_monitor.snapshot.douyin_import_error")
            except (ValueError, OSError) as exc:
                logger.warning("competitor_monitor.snapshot.douyin_error", exc=str(exc))
                snapshots["douyin"] = {"error": str(exc)}

        elif platform == "xiaohongshu":
            try:
                from shared.integrations.xiaohongshu_marketing import XiaohongshuMarketingAdapter

                adapter = XiaohongshuMarketingAdapter()
                mentions = await adapter.get_store_mentions(tenant_id, body.store_id, days=7)
                ad_data = await adapter.get_ad_data(tenant_id, body.store_id, week_ago, today)
                snapshots["xiaohongshu"] = {
                    "store_mentions": mentions,
                    "ad_data": ad_data,
                }
                logger.info("competitor_monitor.snapshot.xhs_ok", store_id=body.store_id)
            except ImportError:
                logger.warning("competitor_monitor.snapshot.xhs_import_error")
            except (ValueError, OSError) as exc:
                logger.warning("competitor_monitor.snapshot.xhs_error", exc=str(exc))
                snapshots["xiaohongshu"] = {"error": str(exc)}

        else:
            logger.warning("competitor_monitor.snapshot.unknown_platform", platform=platform)

    return {
        "ok": True,
        "data": {
            "store_id": body.store_id,
            "platforms_requested": body.platforms,
            "platforms_returned": list(snapshots.keys()),
            "snapshot": snapshots,
        },
    }
