"""tx-trade — 域A 交易履约微服务

收银引擎：开单/点餐/结算/支付/退款/打印/日结
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.ontology.src.database import init_db

from .api.allergen_routes import router as allergen_router
from .api.approval_routes import router as approval_router
from .api.banquet_order_routes import router as banquet_order_router  # Y-A8 宴席支付闭环
from .api.banquet_payment_routes import router as banquet_payment_router
from .api.banquet_routes import router as banquet_router
from .api.booking_api import router as booking_router
from .api.booking_prep_routes import router as booking_prep_router
from .api.booking_webhook_routes import router as booking_webhook_router
from .api.cashier_api import router as cashier_router
from .api.chef_at_home_routes import router as chef_at_home_router
from .api.collab_order_routes import router as collab_order_router
from .api.cook_time_routes import router as cook_time_router
from .api.coupon_routes import router as coupon_router
from .api.course_firing_routes import router as course_firing_router
from .api.crew_handover_router import router as crew_handover_router
from .api.crew_stats_routes import router as crew_stats_router
from .api.delivery_ops_routes import router as delivery_ops_router

# 外卖订单接单面板扩展：状态流转/取消/Webhook mock/Mock订单生成
from .api.delivery_orders_routes import router as delivery_orders_router
from .api.digital_menu_board_router import router as digital_menu_board_router

# v149 桌台中心化架构：堂食会话 + 服务呼叫 + KDS桌台聚合
from .api.dining_session_routes import router as dining_session_router
from .api.discount_audit_routes import router as discount_audit_router
from .api.discount_engine_routes import router as discount_engine_router

# 菜品→档口映射管理（KDS分单依据）
from .api.dish_dept_mapping_routes import router as dish_dept_mapping_router
from .api.dish_practice_routes import router as dish_practice_router
from .api.dispatch_code_routes import router as dispatch_code_router
from .api.dispatch_rule_routes import router as dispatch_rule_router
from .api.enterprise_routes import router as enterprise_router
from .api.expo_routes import router as expo_router
from .api.group_buy_routes import router as group_buy_router
from .api.handover_routes import router as handover_router
from .api.inventory_menu_routes import router as inventory_menu_router
from .api.invoice_routes import router as invoice_router
from .api.kds_analytics_routes import router as kds_analytics_router
from .api.kds_by_session_routes import router as kds_by_session_router
from .api.kds_chef_stats_routes import router as kds_chef_stats_router
from .api.kds_config_routes import router as kds_config_router
from .api.kds_pause_grab_routes import router as kds_pause_grab_router
from .api.kds_prep_routes import router as kds_prep_router
from .api.kds_routes import router as kds_router
from .api.kds_rules_routes import router as kds_rules_router
from .api.kds_shortage_routes import router as kds_shortage_router
from .api.kds_soldout_routes import router as kds_soldout_router
from .api.kds_station_profit_routes import router as kds_station_profit_router
from .api.kds_swimlane_routes import router as kds_swimlane_router
from .api.kitchen_monitor_routes import router as kitchen_monitor_router
from .api.manager_app_routes import router as manager_app_router
from .api.market_session_routes import router as market_session_router  # v186 营业市别
from .api.mobile_ops_routes import router as mobile_ops_router
from .api.omni_channel_routes import router as omni_channel_router
from .api.order_ext_routes import router as order_ext_router
from .api.order_ops_routes import router as order_ops_router
from .api.orders import router as orders_router
from .api.payment_direct_routes import router as payment_direct_router
from .api.platform_coupon_routes import router as platform_coupon_router
from .api.prediction_routes import router as prediction_router
from .api.print_manager_routes import router as print_manager_router  # 模块4.2 打印管理可视化中心

# 打印模板：活鲜称重单 / 宴席通知单 / 企业挂账单
from .api.print_template_routes import router as print_template_router
from .api.printer_config_routes import router as printer_config_router
from .api.printer_routes import router as printer_router
from .api.proactive_service_routes import router as proactive_service_router
from .api.production_dept_routes import router as production_dept_router
from .api.retail_mall_routes import router as retail_mall_router
from .api.runner_routes import router as runner_router
from .api.scan_order_api import router as scan_order_ext_router
from .api.scan_order_routes import router as scan_order_router
from .api.scan_pay_routes import router as scan_pay_router
from .api.seat_order_routes import router as seat_order_router
from .api.self_order_routes import router as self_order_router
from .api.self_pickup_routes import router as self_pickup_router  # v169 自提渠道
from .api.service_bell_routes import router as service_bell_router
from .api.service_call_routes import router as service_call_router
from .api.service_charge_routes import router as service_charge_router
from .api.shift_report_routes import router as shift_report_router
from .api.shift_routes import router as shift_router
from .api.split_payment_routes import router as split_payment_router
from .api.stored_value_routes import router as stored_value_router
from .api.supply_chain_mobile_routes import router as supply_chain_mobile_router
from .api.table_layout_routes import router as table_layout_router
from .api.table_monitor_routes import router as table_monitor_router
from .api.table_ops_routes import router as table_ops_router
from .api.table_routes import router as table_router
from .api.takeaway_routes import router as takeaway_router
from .api.template_editor_routes import router as template_editor_router
from .api.waitlist_routes import router as waitlist_router
from .api.webhook_routes import router as webhook_router
from .api.xhs_routes import router as xhs_router
from .routers.crew_schedule_router import router as crew_schedule_router
from .routers.delivery_panel_router import router as delivery_panel_router
from .routers.delivery_router import router as delivery_router
from .routers.menu_engineering_router import router as menu_engineering_router
from .routers.patrol_router import router as patrol_router
from .routers.payment_router import router as table_side_pay_router
from .routers.self_pay_router import router as self_pay_router
from .routers.shift_summary_router import router as shift_summary_router
from .routers.sync_ingest_router import router as sync_ingest_router
from .routers.vision_router import router as vision_router
from .routers.voice_order_router import router as voice_order_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    from shared.ontology.src.database import async_session_factory

    from .services.cook_time_stats import start_daily_scheduler
    from .services.group_buy_scheduler import start_group_buy_expiry_scheduler

    # ── §19 A4 (b)：lifespan shutdown 跟踪后台任务，避免审计日志在 SIGTERM 时丢失 ──
    # background_tasks 集合用于跟踪所有 fire-and-forget 后台 task（典型如 write_audit）
    # shutdown 时 await asyncio.gather(...) 5s 超时排空，避免部署窗口最后一笔审计被取消。
    app.state.background_tasks = set()

    def _register_background_task(task: asyncio.Task) -> asyncio.Task:
        """注册后台 task 到 app.state.background_tasks 并自动 done 后清理。

        路由层应通过此 helper 创建 fire-and-forget task：
            task = asyncio.create_task(write_audit(...))
            app.state.register_background_task(task)
        """
        app.state.background_tasks.add(task)
        task.add_done_callback(app.state.background_tasks.discard)
        return task

    app.state.register_background_task = _register_background_task

    await init_db()
    _register_background_task(asyncio.create_task(start_daily_scheduler(async_session_factory)))
    _register_background_task(
        asyncio.create_task(start_group_buy_expiry_scheduler(async_session_factory))
    )

    # Feature Flag 检查：TradeFlags.DELIVERY_AUTO_ACCEPT（外卖自动接单）
    # 关闭时跳过自动接单初始化，外卖订单须人工在接单面板手动接单
    # 用 try/except ImportError 保护，SDK不可用时降级为开启（不影响现有逻辑）
    try:
        from shared.feature_flags import is_enabled as _ff_is_enabled
        from shared.feature_flags.flag_names import TradeFlags as _TradeFlags

        if not _ff_is_enabled(_TradeFlags.DELIVERY_AUTO_ACCEPT):
            import structlog as _structlog

            _structlog.get_logger(__name__).info(
                "delivery_auto_accept_disabled",
                reason="feature_flag_disabled",
                flag=_TradeFlags.DELIVERY_AUTO_ACCEPT,
            )
        else:
            import structlog as _structlog

            _structlog.get_logger(__name__).info(
                "delivery_auto_accept_enabled",
                flag=_TradeFlags.DELIVERY_AUTO_ACCEPT,
            )
    except ImportError:
        pass  # feature_flags SDK不可用，外卖自动接单状态由环境变量控制

    # ── C3 §19：mark_offline_if_stale 60s 周期调度（受 EdgeFlags.MARK_OFFLINE_SCHEDULER 控制）──
    mark_offline_task: asyncio.Task | None = None
    try:
        from shared.feature_flags import is_enabled as _ff_is_enabled
        from shared.feature_flags.flag_names import EdgeFlags as _EdgeFlags

        if _ff_is_enabled(_EdgeFlags.MARK_OFFLINE_SCHEDULER):
            import structlog as _structlog

            _structlog.get_logger(__name__).info(
                "mark_offline_scheduler_enabled",
                flag=_EdgeFlags.MARK_OFFLINE_SCHEDULER,
            )
            from .services.mark_offline_scheduler import mark_offline_scheduler_loop

            mark_offline_task = asyncio.create_task(
                mark_offline_scheduler_loop(async_session_factory, interval_sec=60),
                name="mark_offline_scheduler",
            )
        else:
            import structlog as _structlog

            _structlog.get_logger(__name__).info(
                "mark_offline_scheduler_disabled",
                reason="feature_flag_disabled",
                flag=_EdgeFlags.MARK_OFFLINE_SCHEDULER,
            )
    except ImportError:
        # feature_flags SDK 不可用：保守默认关闭（不启动 task）
        import structlog as _structlog

        _structlog.get_logger(__name__).warning(
            "mark_offline_scheduler_skipped_feature_flags_unavailable",
        )

    try:
        yield
    finally:
        # graceful shutdown：cancel + await，避免事件循环退出时 task 仍在 sleep
        if mark_offline_task is not None and not mark_offline_task.done():
            mark_offline_task.cancel()
            try:
                await mark_offline_task
            except asyncio.CancelledError:
                pass

        # ── §19 A4 (b)：gather in-flight 后台任务，5s 超时（避免无限挂起） ──
        # Uvicorn SIGTERM 时若不显式排空 background_tasks，asyncio.create_task
        # 注入的最后一笔审计写入（如删单 write_audit）会被 cancel → 30s 部署窗口丢日志。
        # gather 收集仍在运行的 task；超时后 SIGKILL 兜底，至少给业务 5s 完成 in-flight。
        bg_tasks = getattr(app.state, "background_tasks", None)
        if bg_tasks:
            pending = [t for t in list(bg_tasks) if not t.done()]
            if pending:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*pending, return_exceptions=True),
                        timeout=5.0,
                    )
                except asyncio.TimeoutError:
                    # 5s 内未完成的任务 cancel 释放（避免事件循环退出时报 warning）
                    for t in pending:
                        if not t.done():
                            t.cancel()


app = FastAPI(
    title="TunxiangOS tx-trade",
    version="4.0.0",
    description="交易履约微服务 — 收银/外卖聚合/零售商城",
    lifespan=lifespan,
)

from prometheus_fastapi_instrumentator import Instrumentator

Instrumentator().instrument(app).expose(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(orders_router)
app.include_router(cashier_router)
app.include_router(kds_router)
app.include_router(handover_router)
app.include_router(table_router)
app.include_router(dining_session_router)  # v149 堂食会话（桌台中心化核心）
app.include_router(market_session_router)  # v186 营业市别（早/午/晚市别管理）
app.include_router(service_call_router)  # v149 服务呼叫（催菜/呼叫服务员）
app.include_router(kds_by_session_router)  # v149 KDS桌台维度出餐看板
app.include_router(self_pickup_router)  # v169 自提渠道（取餐码+叫号）
app.include_router(enterprise_router)
app.include_router(order_ext_router)
app.include_router(coupon_router)
app.include_router(platform_coupon_router)
app.include_router(service_charge_router)
app.include_router(invoice_router)
app.include_router(payment_direct_router)
app.include_router(webhook_router)
app.include_router(printer_router)
app.include_router(approval_router)
app.include_router(booking_router)
app.include_router(booking_webhook_router)  # 多平台预订 Webhook + Mock 生成
app.include_router(kds_shortage_router)
app.include_router(scan_order_router)
app.include_router(order_ops_router)
app.include_router(shift_router)
app.include_router(dish_practice_router)
app.include_router(table_ops_router)
app.include_router(banquet_router)
app.include_router(mobile_ops_router)
app.include_router(takeaway_router)
app.include_router(retail_mall_router)
app.include_router(runner_router, prefix="/api/v1/runner")
app.include_router(expo_router, prefix="/api/v1/expo")
app.include_router(cook_time_router, prefix="/api/v1/cook-time")
app.include_router(shift_report_router, prefix="/api/v1/shifts")
app.include_router(dispatch_rule_router, prefix="/api/v1/dispatch-rules")
app.include_router(dispatch_code_router, prefix="/api/v1/dispatch-codes")
app.include_router(kds_config_router, prefix="/api/v1/kds-call")
app.include_router(kds_rules_router, prefix="/api/v1/kds-rules")
app.include_router(kitchen_monitor_router, prefix="/api/v1/kitchen")
app.include_router(table_monitor_router)
app.include_router(booking_prep_router, prefix="/api/v1/booking-prep")
app.include_router(delivery_ops_router)
app.include_router(omni_channel_router, prefix="/api/v1")
app.include_router(banquet_payment_router)
app.include_router(banquet_order_router)  # Y-A8 /api/v1/trade/banquet — 定金/尾款状态机
app.include_router(collab_order_router)
app.include_router(table_layout_router)
app.include_router(chef_at_home_router)
app.include_router(omni_channel_router, prefix="/api/v1")
app.include_router(scan_order_ext_router)
app.include_router(self_order_router)
app.include_router(kds_analytics_router, prefix="/api/v1/kds-analytics")
app.include_router(kds_pause_grab_router)
app.include_router(kds_soldout_router)
app.include_router(kds_chef_stats_router)
app.include_router(kds_swimlane_router)
app.include_router(kds_prep_router)
app.include_router(kds_station_profit_router)
app.include_router(discount_audit_router)
app.include_router(discount_engine_router)
app.include_router(service_bell_router)
app.include_router(course_firing_router)
app.include_router(seat_order_router)
app.include_router(manager_app_router)
app.include_router(crew_stats_router)
app.include_router(allergen_router)
app.include_router(inventory_menu_router)
app.include_router(supply_chain_mobile_router)
app.include_router(prediction_router)
app.include_router(proactive_service_router)
app.include_router(crew_handover_router)
app.include_router(table_side_pay_router)
app.include_router(crew_schedule_router)
app.include_router(menu_engineering_router)
app.include_router(voice_order_router)
app.include_router(vision_router)
app.include_router(patrol_router)
app.include_router(digital_menu_board_router)
app.include_router(shift_summary_router)
app.include_router(sync_ingest_router)
app.include_router(delivery_panel_router)  # 新接单面板（完整实现）先注册，优先匹配
app.include_router(delivery_router)  # 旧骨架路由（保留 /webhook/ 和 /platforms 端点）
app.include_router(self_pay_router)
app.include_router(production_dept_router)
app.include_router(template_editor_router)
app.include_router(group_buy_router)
app.include_router(xhs_router)
app.include_router(split_payment_router)
# 大厨到家：默认开启；生产可设 TX_FEATURE_CHEF_AT_HOME=0|false 关闭
if os.environ.get("TX_FEATURE_CHEF_AT_HOME", "1").lower() in ("1", "true", "yes"):
    app.include_router(chef_at_home_router)
app.include_router(scan_pay_router)
app.include_router(stored_value_router)
# 注意：printer_config_router 必须在 printer_router 之后注册
# printer_router  = 打印执行（/api/v1/printer 单数）
# printer_config_router = 打印机配置（/api/v1/printers 复数）
app.include_router(printer_config_router)
app.include_router(waitlist_router, prefix="/api/v1/waitlist")
# 外卖接单面板扩展端点（状态流转/取消/Webhook mock/Mock订单）
# 注意：delivery_orders_router 与 delivery_panel_router 共享 /api/v1/delivery 前缀
# delivery_panel_router 已在上方注册（接单/拒单/出餐/统计），本 router 补充其余端点
app.include_router(delivery_orders_router)
# 徐记海鲜：宴席同步出品（开席/推进节/进度查询）
from .api.kds_banquet_routes import router as kds_banquet_router

app.include_router(kds_banquet_router)

# 模块4.1：宴会KDS出品 + 宴会定金抵扣
from .api.banquet_deposit_routes import router as banquet_deposit_router
from .api.banquet_kds_routes import router as banquet_kds_router

app.include_router(banquet_kds_router)
app.include_router(banquet_deposit_router)
app.include_router(print_template_router)
app.include_router(print_manager_router)  # 模块4.2 打印管理可视化中心（/api/v1/print/tasks...）
app.include_router(dish_dept_mapping_router)

# ── 快餐模式：快餐收银 + 叫号屏 ──
from .api.calling_screen_routes import router as calling_screen_router
from .api.quick_cashier_routes import router as quick_cashier_router

app.include_router(quick_cashier_router)
app.include_router(calling_screen_router)

# ── 模块3.1: 快餐平行流程（取餐号/出餐叫号/快餐KDS）──
from .api.fastfood_routes import router as fastfood_router

app.include_router(fastfood_router)

# ── TC-P2-12: 智慧商街/档口管理（美食广场多档口并行收银+独立核算）──
from .api.food_court_routes import router as food_court_router

app.include_router(food_court_router)

# ── Y-A12: 全渠道订单中心统一视图 ──
from .api.omni_order_center_routes import router as omni_order_center_router

app.include_router(omni_order_center_router)


# ── Y-I2: 抖音团购核销适配器深化 ──
from .api.douyin_voucher_routes import router as douyin_voucher_router

app.include_router(douyin_voucher_router)


# ── Y-A9: 团餐/企业客户 + Y-M4: 外卖自营配送调度MVP ──
from .api.corporate_order_routes import router as corporate_order_router
from .api.self_delivery_routes import router as self_delivery_router

app.include_router(corporate_order_router)
app.include_router(self_delivery_router)


# ── Y-A5: 外卖聚合深度（美团/饿了么/抖音聚合落库 + 异常补偿 + 对账指标）──
from .api.aggregator_reconcile_routes import router as aggregator_reconcile_router
from .api.delivery_aggregator_routes import router as delivery_aggregator_router

app.include_router(delivery_aggregator_router)
app.include_router(aggregator_reconcile_router)

# ── 外卖平台集成同步（菜单推送 / 估清同步 / 对账汇总）──
from .api.delivery_platform_sync_routes import router as delivery_platform_sync_router

app.include_router(delivery_platform_sync_router)

# ── v212: 最低消费规则引擎 ──
from .api.group_order_routes import router as group_order_router
from .api.minimum_consumption_routes import router as min_consumption_router

app.include_router(min_consumption_router)
app.include_router(group_order_router)

# ── v238: 账单规则引擎（最低消费/服务费，对标天财商龙模块1.4）──
from .api.billing_rules_routes import router as billing_rules_router

app.include_router(billing_rules_router)

# ── 模块2.4: 外卖平台闭环 — 菜单/估清双向同步 + 线上接单 ──
from .api.omni_sync_routes import router as omni_sync_router

app.include_router(omni_sync_router)

# ── 存酒管理：台位/会员存酒全生命周期（存入/取酒/续存/转台/核销）──
from .api.wine_storage_routes import router as wine_storage_router

app.include_router(wine_storage_router)


try:
    from .api.table_card_api import router as table_card_router

    app.include_router(table_card_router)
except (ImportError, AttributeError) as e:
    import logging as _logging

    _logging.getLogger(__name__).warning(f"table_card_router load failed: {e}")


# ── 演示/训练模式（Redis状态管理，不影响真实数据）──
from .api.training_mode_routes import router as training_mode_router

app.include_router(training_mode_router)

# ── 速点快速点单终端（Kiosk/速点）──
from .api.kiosk_routes import router as kiosk_router

app.include_router(kiosk_router)

# ── Sprint E1：渠道 canonical 订单（外卖统一抽象层，纯加法不影响适配器）──
from .api.channel_canonical_routes import router as channel_canonical_router

app.include_router(channel_canonical_router)


@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-trade", "version": "4.0.0"}}
