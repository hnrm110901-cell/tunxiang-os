"""tx-analytics — 域G 经营分析微服务"""

import asyncio
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI

from .api.analytics import router as analytics_router
from .api.etl import router as etl_router
from .etl.scheduler import get_etl_scheduler

logger = structlog.get_logger()

from .api.ai_evidence_chain_routes import router as ai_evidence_chain_router  # May W2: B-04
from .api.alert_routes import router as alert_router  # BI-2.2: 预警闭环引擎（8端点）
from .api.anomaly_routes import router as anomaly_router
from .api.banquet_analytics_routes import router as banquet_analytics_router  # S7 宴会分析报表（8端点）
from .api.booking_report_routes import router as booking_report_router  # 预定报表（4端点）
from .api.boss_bi_routes import router as boss_bi_router
from .api.ceo_cockpit_routes import (
    router as ceo_cockpit_router,  # G6: CEO今日经营驾驶舱（7端点）  # G6: CEO今日经营驾驶舱（7端点）
)
from .api.cost_health_routes import router as cost_health_router
from .api.cost_root_cause_routes import (
    router as cost_root_cause_router,  # v379: 成本根因分析Agent（4端点）  # v379: 成本根因分析Agent（4端点）
)
from .api.daily_brief_routes import router as daily_brief_router
from .api.dashboard_routes import router as dashboard_router
from .api.delivery_report_routes import router as delivery_report_router  # 外卖报表（4端点）
from .api.demo_monitor_routes import router as demo_monitor_router  # May W2: C-04 演示监控
from .api.dish_analysis_routes import router as dish_analysis_router
from .api.go_live_review_routes import router as go_live_review_router  # May W4: GO-TO-LIVE 评审
from .api.group_dashboard_routes import router as group_dashboard_router
from .api.hq_brand_analytics_routes import router as hq_brand_analytics_router
from .api.insights_routes import router as insights_router
from .api.inventory_analysis_routes import router as inventory_analysis_router
from .api.kitchen_report_routes import router as kitchen_report_router  # 厨房管理报表（8端点）
from .api.knowledge_query import router as knowledge_router
from .api.merchant_data_quality_routes import router as data_quality_router
from .api.merchant_delivery_scorecard_routes import router as delivery_scorecard_router  # W4: 交付评分卡
from .api.merchant_kpi_config_routes import router as merchant_kpi_router  # W2 4/13 商户KPI权重
from .api.merchant_targets_routes import _load_overrides_from_db  # B-03: 启动时加载DB覆盖值
from .api.merchant_targets_routes import router as merchant_targets_router  # May W2: B-03
from .api.metrics_dict_routes import router as metrics_dict_router  # W2 4/13 指标口径字典
from .api.monthly_brief_routes import router as monthly_brief_router  # W2 4/13 月报
from .api.narrative_enhanced_routes import router as narrative_enhanced_router  # P3-02
from .api.nlq_routes import router as nlq_router
from .api.olap_routes import router as olap_router  # BI-1.1: OLAP多维分析引擎（5端点）
from .api.pinned_dashboard_routes import router as pinned_dashboard_router  # S4-04 PR2.C: 驾驶舱 Pin
from .api.private_domain_routes import router as private_domain_router
from .api.report_builder_routes import router as report_builder_router  # S5: 报表配置化引擎（12端点）
from .api.report_config_routes import router as report_config_router
from .api.report_routes import router as report_router
from .api.reports_router import router as p0_reports_router
from .api.seed_loader import load_p0_seeds
from .api.self_service_routes import router as self_service_router  # BI-1.2: 自助取数（8端点）
from .api.special_ops_report_routes import router as special_ops_report_router  # 特殊操作报表（14端点）
from .api.store_analysis_routes import router as store_analysis_router
from .api.stream_report_routes import router as stream_report_router
from .api.weekly_brief_routes import router as weekly_brief_router  # W2 4/13 周报

# PRD-11 sub-C — SplitAttributionProjector (env-gated, dev/demo 默认 ON 激活)
from .api.cost_attribution_routes import router as cost_attribution_router
from .api.dlq_split_routes import router as dlq_split_router
from .projectors.registry import (
    is_enabled as split_projector_enabled,
    is_enabled_for_tenant as split_projector_enabled_for_tenant,
    list_active_tenants as split_projector_list_tenants,
    start_split_attribution_projector,
    stop_all_split_attribution_projectors,
    stop_split_attribution_projector,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    scheduler = get_etl_scheduler()
    scheduler.start()
    # 幂等加载 P0 报表种子数据
    try:
        await load_p0_seeds()
    except ConnectionRefusedError:
        logger.warning("p0_seed_load_skipped", reason="DB not available")
    except OSError as exc:
        logger.warning("p0_seed_load_skipped", reason=str(exc))
    # 从 merchant_target_overrides 表加载覆盖值到内存缓存
    try:
        await _load_overrides_from_db()
    except Exception as exc:
        logger.warning("merchant_targets_overrides_load_skipped", error=str(exc))

    # PRD-11 sub-C 激活 — env-gated SplitAttributionProjector daemon (镜像 tx-supply
    # sub-B.2 lifespan refresh loop, PR #698 模式). dev/demo 默认 ON, prod/staging/gray
    # 默认 OFF 灰度. lifespan 启动失败不阻塞 service (fail-open).
    refresh_task: "asyncio.Task[None] | None" = None
    stop_event = asyncio.Event()
    started_tenants: set[str] = set()

    if split_projector_enabled():
        async def _refresh_loop() -> None:
            nonlocal started_tenants
            refresh_sec = float(
                os.getenv("TX_ANALYTICS_SPLIT_ATTRIBUTION_TENANT_REFRESH_SEC", "300")
            )
            while not stop_event.is_set():
                try:
                    tenants = await split_projector_list_tenants()
                    # PRD-11 sub-C 灰度: per-tenant gating via feature_flags SDK.
                    # 全局 gate (`split_projector_enabled()`) 通过后, refresh loop 仍按
                    # tenant 维度二次过滤 — targeting_rules.prod.tenant_id 白名单命中
                    # 才启 daemon. 已 start 但本轮 flag 翻 OFF 的 tenant 走 stop.
                    enabled_set = {
                        tid
                        for tid in tenants
                        if split_projector_enabled_for_tenant(tid)
                    }
                    for tid in enabled_set - started_tenants:
                        await start_split_attribution_projector(tid)
                    for tid in started_tenants - enabled_set:
                        await stop_split_attribution_projector(tid)
                    started_tenants = enabled_set
                except Exception as exc:  # noqa: BLE001 — lifespan 周期任务必须 fail-open
                    logger.error(
                        "split_attribution_tenant_refresh_failed",
                        error=str(exc),
                        exc_info=True,
                    )
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=refresh_sec)
                except asyncio.TimeoutError:
                    logger.debug("split_attribution_refresh_tick")

        refresh_sec_val = float(
            os.getenv("TX_ANALYTICS_SPLIT_ATTRIBUTION_TENANT_REFRESH_SEC", "300")
        )
        refresh_task = asyncio.create_task(
            _refresh_loop(), name="split_attribution_tenant_refresh"
        )
        logger.info(
            "split_attribution_projector_lifespan_started",
            refresh_sec=refresh_sec_val,
        )
    else:
        logger.info("split_attribution_projector_lifespan_skipped", reason="env_off")

    logger.info("tx_analytics_started", etl_scheduler="running")
    try:
        yield
    finally:
        stop_event.set()
        if refresh_task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(refresh_task), timeout=5.0)
            except asyncio.TimeoutError:
                refresh_task.cancel()
                try:
                    await refresh_task
                except asyncio.CancelledError:
                    logger.debug("split_attribution_refresh_task_cancelled")
        # §19 round-1 P1-1 mirror (sub-B.2 PR #698 教训): 以 _PROJECTOR_TASKS 真实
        # 状态为准, 而非 started_tenants 闭包. refresh loop 中途 cancel 时, started_tenants
        # 可能漏掉新 started 的 task, 走 stop_all_split_attribution_projectors() 兜底.
        try:
            await stop_all_split_attribution_projectors()
        except Exception as exc:  # noqa: BLE001 — shutdown 兜底
            logger.warning(
                "split_attribution_projector_shutdown_failed",
                error=str(exc),
                exc_info=True,
            )
        scheduler.shutdown()
        logger.info("split_attribution_projector_lifespan_stopped")
        logger.info("tx_analytics_stopped")


app = FastAPI(title="TunxiangOS tx-analytics", version="3.0.0", lifespan=lifespan)

from prometheus_fastapi_instrumentator import Instrumentator

Instrumentator().instrument(app).expose(app)

# /metrics 端点 Bearer + IP allowlist 鉴权 (issue #829, parent #825 W3 D2 决策矩阵分母)
from shared.middleware.src.metrics_auth import MetricsAuthMiddleware  # noqa: E402

app.add_middleware(MetricsAuthMiddleware)

app.include_router(analytics_router)
app.include_router(etl_router)

app.include_router(dashboard_router)
app.include_router(store_analysis_router)
app.include_router(dish_analysis_router)
app.include_router(report_router)
app.include_router(private_domain_router)
app.include_router(knowledge_router)
app.include_router(inventory_analysis_router)
app.include_router(p0_reports_router)
app.include_router(cost_health_router)
app.include_router(boss_bi_router)
app.include_router(stream_report_router)
app.include_router(group_dashboard_router)
app.include_router(report_config_router)
app.include_router(narrative_enhanced_router)  # P3-02 对比叙事+异常叙事
app.include_router(nlq_router)
app.include_router(anomaly_router)
app.include_router(insights_router)
app.include_router(daily_brief_router)
app.include_router(hq_brand_analytics_router)
app.include_router(weekly_brief_router)  # W2: GET /api/v1/analytics/weekly-brief/*
app.include_router(monthly_brief_router)  # W2: GET /api/v1/analytics/monthly-brief/*
app.include_router(merchant_kpi_router)  # W2: GET/PUT /api/v1/analytics/merchant-kpi/*
app.include_router(metrics_dict_router)  # W2: GET /api/v1/analytics/metrics-dict/*
app.include_router(data_quality_router)  # May W1: 数据质量验收
app.include_router(merchant_targets_router)  # May W2: B-03 分商户目标
app.include_router(ai_evidence_chain_router)  # May W2: B-04 证据链
app.include_router(delivery_scorecard_router)  # W4: 商户交付评分卡
app.include_router(go_live_review_router)  # May W4: GO-TO-LIVE 最终评审
app.include_router(kitchen_report_router)  # 厨房管理报表：8端点
app.include_router(delivery_report_router)  # 外卖报表：4端点
app.include_router(booking_report_router)  # 预定报表：4端点
app.include_router(special_ops_report_router)  # 特殊操作报表：14端点
app.include_router(banquet_analytics_router)  # S7 宴会分析报表：8端点
app.include_router(report_builder_router)  # S5 报表配置化引擎：12端点
app.include_router(ceo_cockpit_router)  # G6 CEO今日经营驾驶舱：7端点
app.include_router(cost_root_cause_router)  # v379 成本根因分析Agent：4端点
app.include_router(olap_router)  # BI-1.1: OLAP多维分析引擎：5端点
app.include_router(self_service_router)  # BI-1.2: 自助取数（8端点）
app.include_router(alert_router)  # BI-2.2: 预警闭环引擎（8端点）
app.include_router(demo_monitor_router)  # May W2: C-04 演示环境监控面板
app.include_router(pinned_dashboard_router)  # S4-04 PR2.C 驾驶舱 Pin（issue #291）
app.include_router(cost_attribution_router)  # PRD-11 sub-C: 成本分摊 dashboard（3 端点）
app.include_router(dlq_split_router)  # PRD-11 sub-C: split-attribution 死信看板（3 端点）


@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-analytics", "version": "3.0.0"}}
