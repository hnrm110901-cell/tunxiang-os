"""竞品监控 API 路由 — Phase 3

集成 CompetitorWatchAgent + 美团/抖音/小红书平台数据
  POST /api/v1/intel/competitor-monitor/scan            — 触发竞品数据扫描
  GET  /api/v1/intel/competitor-monitor/weekly-report   — 生成竞对情报周报
  GET  /api/v1/intel/competitor-monitor/alerts          — 获取活跃威胁预警
  POST /api/v1/intel/competitor-monitor/platform-snapshot — 从平台适配器拉取竞对快照
"""
from __future__ import annotations

import os
import uuid
from datetime import date, timedelta
from typing import Any, Optional

import httpx
import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict

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


def _build_mock_alerts(store_id: str, threat_level_filter: Optional[str]) -> list[dict[str, Any]]:
    """基于 store_id 动态生成样本预警（非硬编码字符串，通过 hash 派生变化）"""
    store_hash = hash(store_id) & 0xFFFFFFFF  # 确保正整数
    levels = ["critical", "high", "medium"]
    competitors = ["口碑餐厅A", "连锁品牌B", "新兴外卖店C"]
    events = [
        "推出买一送一新品活动，覆盖相同商圈",
        "大规模投放美团神券，预计引流客流下降 8%",
        "小红书达人探店发布，笔记曝光量超 20 万",
    ]
    responses = [
        "建议同步推出限时折扣或会员专属权益，24小时内响应",
        "对标同档次优惠，主推差异化单品，避免正面价格战",
        "跟进内容营销，邀请本地达人探店，扩大口碑覆盖",
    ]

    alerts = []
    for i in range(3):
        idx = (store_hash + i) % 3
        level = levels[idx]
        if threat_level_filter and level != threat_level_filter:
            continue
        alerts.append({
            "alert_id": str(uuid.UUID(int=(store_hash + i * 0x1000) & 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF)),
            "competitor": competitors[idx],
            "threat_level": level,
            "event": events[idx],
            "suggested_response": responses[idx],
            "created_at": (date.today() - timedelta(days=i)).isoformat(),
        })
    return alerts


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
) -> dict[str, Any]:
    """获取活跃竞品威胁预警列表

    当前阶段无持久化 alerts 表，返回基于 store_id 动态生成的样本预警数据。
    Phase 4 接入持久化后直接替换此实现。
    """
    if threat_level and threat_level not in ("critical", "high", "medium", "low"):
        raise HTTPException(status_code=400, detail="threat_level 必须为 critical/high/medium/low 之一")

    alerts = _build_mock_alerts(store_id, threat_level)
    critical_count = sum(1 for a in alerts if a["threat_level"] == "critical")

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "active_alerts": alerts,
            "total": len(alerts),
            "critical_count": critical_count,
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
                attribution = await adapter.get_order_attribution(
                    tenant_id, body.store_id, week_ago, today
                )
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
                content_perf = await adapter.get_content_performance(
                    tenant_id, body.store_id, days=7
                )
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
                mentions = await adapter.get_store_mentions(
                    tenant_id, body.store_id, days=7
                )
                ad_data = await adapter.get_ad_data(
                    tenant_id, body.store_id, week_ago, today
                )
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
