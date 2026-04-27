"""tx-supply — 域D 供应链微服务

库存管理、采购、供应商、损耗追踪、需求预测、BOM管理、理论成本计算
来源：12 个 service 文件迁移自 tunxiang V2.x
"""

import structlog
from fastapi import FastAPI

# Feature Flag SDK（try/except 保护，SDK不可用时自动降级为全量开启）
try:
    from shared.feature_flags import is_enabled
    from shared.feature_flags.flag_names import SupplyFlags

    _FLAG_SDK_AVAILABLE = True
except ImportError:
    _FLAG_SDK_AVAILABLE = False

    def is_enabled(flag, context=None):
        return True  # noqa: E731


logger = structlog.get_logger(__name__)

from .api.bom_routes import router as bom_router
from .api.central_kitchen_routes import router as ck_router
from .api.ck_production_routes import router as ck_production_router
from .api.ck_recipe_routes import router as ck_recipe_router
from .api.craft_routes import router as craft_router
from .api.deduction_routes import router as deduction_router
from .api.delivery_route_routes import router as delivery_route_router
from .api.dept_issue_routes import router as dept_issue_router
from .api.distribution_routes import router as distribution_router
from .api.edi_routes import router as edi_router
from .api.food_safety_routes import router as food_safety_router
from .api.inventory import router as inv_router
from .api.kingdee_routes import router as kingdee_router
from .api.mobile_supply_routes import (
    edi_ext_router,
    transfer_ext_router,
)
from .api.mobile_supply_routes import (
    router as mobile_supply_router,
)
from .api.period_close_routes import router as period_close_router
from .api.procurement_recommend_routes import router as procurement_recommend_router
from .api.receiving_routes import router as receiving_router
from .api.receiving_v2_routes import router as receiving_v2_router
from .api.requisition_routes import router as requisition_router
from .api.seafood_routes import router as seafood_router
from .api.smart_procurement_routes import router as smart_procurement_router
from .api.smart_replenishment_routes import router as smart_replenishment_router
from .api.supplier_portal_routes import router as supplier_portal_router
from .api.supplier_portal_v2_routes import router as supplier_portal_v2_router
from .api.supplier_scoring_routes import router as supplier_scoring_router
from .api.trace_routes import router as trace_router
from .api.transfer_routes import router as transfer_router
from .api.warehouse_location_routes import router as warehouse_location_router
from .api.warehouse_ops_routes import router as warehouse_ops_router

app = FastAPI(title="TunxiangOS tx-supply", version="3.0.0")

from prometheus_fastapi_instrumentator import Instrumentator

Instrumentator().instrument(app).expose(app)

# ── Feature Flag 启动检查 ──────────────────────────────────────────
# SupplyFlags.RECEIVING_INSPECTION: 收货验收功能（入库加权均价计算）
if is_enabled(SupplyFlags.RECEIVING_INSPECTION):
    logger.info(
        "feature_flag_enabled",
        flag=SupplyFlags.RECEIVING_INSPECTION,
        note="收货验收功能已激活，receiving_routes将执行入库加权均价计算",
    )
else:
    logger.warning(
        "feature_flag_disabled",
        flag=SupplyFlags.RECEIVING_INSPECTION,
        note="收货验收功能已关闭，入库加权均价计算将跳过（供应链核心功能，建议开启）",
    )

# SupplyFlags.TRANSFER_LOSS_DETECTION: 门店调拨运输损耗检测
if is_enabled(SupplyFlags.TRANSFER_LOSS_DETECTION):
    logger.info("feature_flag_enabled", flag=SupplyFlags.TRANSFER_LOSS_DETECTION, note="调拨损耗检测已激活")
else:
    logger.info("feature_flag_disabled", flag=SupplyFlags.TRANSFER_LOSS_DETECTION, note="调拨损耗检测已关闭")

# SupplyFlags.SMART_REORDER: AI智能补货（依赖tx-brain）
if is_enabled(SupplyFlags.SMART_REORDER):
    logger.info(
        "feature_flag_enabled",
        flag=SupplyFlags.SMART_REORDER,
        note="AI智能补货已激活，smart_replenishment_router将使用tx-brain推理",
    )
else:
    logger.info(
        "feature_flag_disabled",
        flag=SupplyFlags.SMART_REORDER,
        note="AI智能补货已关闭，smart_replenishment使用规则引擎降级模式",
    )

app.include_router(inv_router)
app.include_router(bom_router)
app.include_router(deduction_router)
app.include_router(receiving_router)
app.include_router(kingdee_router)
app.include_router(requisition_router)
app.include_router(dept_issue_router)
app.include_router(warehouse_ops_router)
app.include_router(warehouse_location_router)  # 库位/库区/温区编码（v367 TASK-2）
app.include_router(period_close_router)
app.include_router(craft_router)
app.include_router(distribution_router)
app.include_router(food_safety_router)
app.include_router(seafood_router)
app.include_router(trace_router)
app.include_router(ck_router)
app.include_router(procurement_recommend_router, prefix="/api/v1/procurement")
app.include_router(smart_replenishment_router, prefix="/api/v1/smart-replenishment")
app.include_router(delivery_route_router)
app.include_router(supplier_scoring_router)
app.include_router(receiving_v2_router)
app.include_router(transfer_router)
app.include_router(ck_production_router)
app.include_router(ck_recipe_router)
app.include_router(supplier_portal_router)
app.include_router(supplier_portal_v2_router)  # Y-E10 去除静默内存降级
app.include_router(edi_router)  # 供应商EDI对接（v217表）
app.include_router(smart_procurement_router)  # 预测驱动智能采购（v219表，对标Fourth iQ）
app.include_router(mobile_supply_router)  # 移动端供应链：扫码采购/收货/盘点（模块3.3）
app.include_router(transfer_ext_router)  # 调拨扩展：execute 端点
app.include_router(edi_ext_router)  # EDI 扩展：供应商查看订单 + 确认发货

# ── 语音盘点（Voice Inventory Count）──
from .api.voice_count_routes import router as voice_count_router

app.include_router(voice_count_router)  # 语音盘点：会话管理/语音录入/差异分析/提交盘点单

# ── MRP智能预估（S6: 生产计划+采购计划联动）──
from .api.mrp_routes import router as mrp_router

app.include_router(mrp_router, prefix="/api/v1/supply/mrp")  # MRP预估：需求计算/生产建议/采购建议/领料（v282表）

# ── 价格台账 + 预警（v366：对标奥琦玮供应链）──
from .api.price_ledger_routes import router as price_ledger_router

app.include_router(price_ledger_router)  # 价格台账：快照/趋势/对比/预警规则/预警实例

# ── 配送在途温控告警（TASK-3 / v368）──
from .api.delivery_temperature_routes import router as delivery_temp_router

app.include_router(delivery_temp_router)  # 配送车温度告警：上报/时序/告警/凭证（海鲜冷链命门）


@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-supply", "version": "3.0.0"}}
