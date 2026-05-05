"""ChannelHealthAgent — cross-platform channel health monitoring.

Monitors API health, order volume, and error rates per platform.
Alerts on anomalies: sudden zero orders, high error rate, API timeout spikes.

P5.2 — Part of the Agent OS Layer (L3).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

import structlog

from ..base import ActionConfig, AgentResult, SkillAgent
from ..edge_mixin import EdgeAwareMixin

logger = structlog.get_logger()

PLATFORMS = ("meituan", "eleme", "douyin", "amap", "taobao")

# ── Alert thresholds (configurable class constants) ──────────────────────────
ALERT_ZERO_ORDER_MINUTES = 30
ALERT_ERROR_RATE_THRESHOLD = 0.10  # 10% error rate → alert
ALERT_LATENCY_P99_MS = 5000        # P99 > 5s → alert
ALERT_ORDER_DROP_THRESHOLD = 0.50  # 50% drop vs same window yesterday → alert


@dataclass
class ChannelHealth:
    """Per-platform health snapshot."""

    platform: str
    status: str = "unknown"  # healthy / degraded / down
    last_order_at: Optional[datetime] = None
    error_rate_1h: float = 0.0
    avg_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    total_orders_1h: int = 0
    total_errors_1h: int = 0
    alerts: list[str] = field(default_factory=list)


class ChannelHealthAgent(EdgeAwareMixin, SkillAgent):
    """Monitor delivery platform health and alert on anomalies.

    Actions:
      - check_all:   Run health checks across all known platforms
      - check_one:   Run health check for a single platform
      - get_summary: Build a structured summary from health results
    """

    agent_id = "channel_health"
    agent_name = "渠道健康监控"
    description = "跨平台渠道健康监控：订单量/错误率/延迟异常检测与告警"
    priority = "P2"
    run_location = "edge+cloud"

    # This agent is read-only (monitoring), no hard constraints apply
    constraint_scope: set[str] = set()
    constraint_waived_reason: Optional[str] = (
        "渠道健康监控是只读SLA检测Agent，不触发任何业务变更，三条硬约束不适用"
    )

    def get_supported_actions(self) -> list[str]:
        return [
            "check_all",
            "check_one",
            "get_summary",
        ]

    def get_action_config(self, action: str) -> ActionConfig:
        configs = {
            "check_all": ActionConfig(risk_level="low", max_retries=1),
            "check_one": ActionConfig(risk_level="low", max_retries=1),
            "get_summary": ActionConfig(risk_level="low"),
        }
        return configs.get(action, ActionConfig())

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        if action == "check_all":
            metrics_map = params.get("metrics_map", {})
            results = await self.check_all_platforms(metrics_map)
            return AgentResult(
                success=True,
                action=action,
                data={
                    "results": {
                        p: {
                            "platform": h.platform,
                            "status": h.status,
                            "error_rate_1h": round(h.error_rate_1h, 4),
                            "avg_latency_ms": round(h.avg_latency_ms, 1),
                            "p99_latency_ms": round(h.p99_latency_ms, 1),
                            "total_orders_1h": h.total_orders_1h,
                            "total_errors_1h": h.total_errors_1h,
                            "alerts": h.alerts,
                        }
                        for p, h in results.items()
                    },
                    "summary": await self.get_channel_summary(results),
                },
                reasoning="渠道健康检测完成，所有平台已扫描",
            )

        if action == "check_one":
            platform = params.get("platform", "")
            metrics = params.get("metrics", {})
            if platform not in PLATFORMS:
                return AgentResult(
                    success=False,
                    action=action,
                    error=f"未知平台: {platform}，有效值: {PLATFORMS}",
                    reasoning=f"不受支持的平台标识: {platform}",
                )
            health = self.check_platform_health(platform, metrics)
            return AgentResult(
                success=True,
                action=action,
                data={
                    "platform": health.platform,
                    "status": health.status,
                    "error_rate_1h": round(health.error_rate_1h, 4),
                    "avg_latency_ms": round(health.avg_latency_ms, 1),
                    "p99_latency_ms": round(health.p99_latency_ms, 1),
                    "total_orders_1h": health.total_orders_1h,
                    "total_errors_1h": health.total_errors_1h,
                    "alerts": health.alerts,
                },
                reasoning=f"{platform} 渠道健康检测完成",
            )

        if action == "get_summary":
            raw = params.get("results", {})
            results = {}
            for p, h in raw.items():
                if isinstance(h, dict):
                    results[p] = ChannelHealth(
                        platform=p,
                        status=h.get("status", "unknown"),
                        alerts=h.get("alerts", []),
                    )
                else:
                    results[p] = h
            summary = await self.get_channel_summary(results)
            return AgentResult(
                success=True,
                action=action,
                data=summary,
                reasoning="渠道健康汇总报告已生成",
            )

        return AgentResult(
            success=False,
            action=action,
            error=f"不支持的动作: {action}",
            reasoning=f"ChannelHealthAgent 不支持动作 {action}",
        )

    # ── Core health check logic ─────────────────────────────────────────────

    def check_platform_health(
        self, platform: str, metrics: dict[str, Any]
    ) -> ChannelHealth:
        """Evaluate a single platform's health from raw metrics."""
        health = ChannelHealth(platform=platform)

        health.total_orders_1h = metrics.get("orders_1h", 0)
        health.total_errors_1h = metrics.get("errors_1h", 0)
        health.avg_latency_ms = metrics.get("avg_latency_ms", 0)
        health.p99_latency_ms = metrics.get("p99_latency_ms", 0)

        # Calculate error rate
        total_calls = health.total_orders_1h + health.total_errors_1h
        health.error_rate_1h = (
            health.total_errors_1h / max(total_calls, 1)
        )

        # Check for zero orders (channel might be down)
        zero_minutes = metrics.get("minutes_since_last_order", 0)
        if zero_minutes > ALERT_ZERO_ORDER_MINUTES:
            health.alerts.append(
                f"渠道 {platform} 已 {zero_minutes} 分钟无新订单，请检查平台连接"
            )
            health.status = "degraded"
            logger.warning(
                "channel_health.zero_orders",
                platform=platform,
                minutes=zero_minutes,
            )

        # Check error rate
        if health.error_rate_1h > ALERT_ERROR_RATE_THRESHOLD:
            health.alerts.append(
                f"渠道 {platform} API 错误率 {health.error_rate_1h:.1%}，超过阈值"
            )
            health.status = "degraded"

        # Check latency
        if health.p99_latency_ms > ALERT_LATENCY_P99_MS:
            health.alerts.append(
                f"渠道 {platform} P99 延迟 {health.p99_latency_ms:.0f}ms，接口响应慢"
            )
            if health.status != "degraded":
                health.status = "degraded"

        # Combined checks — zero orders + high error rate → down
        if zero_minutes > ALERT_ZERO_ORDER_MINUTES and health.error_rate_1h > ALERT_ERROR_RATE_THRESHOLD:
            health.status = "down"
            health.alerts.append(f"渠道 {platform} 疑似宕机：无订单+高错误率")

        if not health.alerts:
            health.status = "healthy"

        logger.info(
            "channel_health.check_done",
            platform=platform,
            status=health.status,
            alerts=len(health.alerts),
        )
        return health

    async def check_all_platforms(
        self, metrics_map: dict[str, dict[str, Any]]
    ) -> dict[str, ChannelHealth]:
        """Run health checks for all known platforms."""
        results: dict[str, ChannelHealth] = {}
        alerts_total = 0

        for platform in PLATFORMS:
            metrics = metrics_map.get(platform, {})
            health = self.check_platform_health(platform, metrics)
            results[platform] = health
            alerts_total += len(health.alerts)

        unhealthy = sum(1 for h in results.values() if h.status != "healthy")
        logger.info(
            "channel_health.all_done",
            platforms=len(results),
            healthy=len(results) - unhealthy,
            degraded=unhealthy,
            alerts=alerts_total,
        )
        return results

    async def get_channel_summary(
        self, results: dict[str, ChannelHealth]
    ) -> dict[str, Any]:
        """Aggregate platform health results into a structured summary."""
        healthy = [p for p, h in results.items() if h.status == "healthy"]
        degraded = [p for p, h in results.items() if h.status == "degraded"]
        down = [p for p, h in results.items() if h.status == "down"]
        all_alerts = [
            {"platform": p, "alert": a}
            for p, h in results.items()
            for a in h.alerts
        ]

        return {
            "healthy": healthy,
            "degraded": degraded,
            "down": down,
            "alerts": all_alerts,
            "total_alerts": len(all_alerts),
            "overall_status": "healthy" if not down else "degraded" if not degraded else "down",
        }
