"""tx-org — 域F 组织运营微服务

员工管理、排班、人力成本、考勤、绩效、培训
来源：57 个 service 文件迁移自 tunxiang V2.x（含 hr/ 子目录 25 个）
"""
import asyncio

# Feature Flag SDK（try/except 保护，SDK不可用时自动降级为全量开启）
try:
    from shared.feature_flags import is_enabled, FlagContext
    from shared.feature_flags.flag_names import OrgFlags
    _FLAG_SDK_AVAILABLE = True
except ImportError:
    _FLAG_SDK_AVAILABLE = False
    def is_enabled(flag, context=None): return True  # noqa: E731

from api.admin_routes import router as admin_router
from api.approval_engine_routes import router as approval_engine_router
from api.approval_router import router as approval_router
from api.attendance_routes import router as attendance_router
from api.compliance_alert_routes import router as compliance_alert_router
from api.compliance_routes import router as compliance_router
from api.device_routes import router as device_router
from api.employee_document_routes import router as employee_document_router
from api.efficiency import router as efficiency_router
from api.employee_depth_routes import router as employee_depth_router
from api.employees import router as emp_router
from api.franchise_mgmt_routes import router as franchise_mgmt_router
from api.job_grade_routes import router as job_grade_router
from api.org_structure_routes import router as org_structure_router
from api.franchise_router import router as franchise_v2_router
from api.franchise_routes import router as franchise_router
from api.franchise_settlement_routes import router as franchise_settlement_router
from api.im_sync_routes import router as im_sync_router
from api.leave_routes import router as leave_router
from api.ota_routes import router as ota_router
from api.patrol_routes import router as patrol_router
import api.payroll_engine_routes as _payroll_engine_mod
from api.payroll_engine_routes import router as payroll_engine_v3_router
from api.payroll_router import router as payroll_v2_router
from api.payroll_routes import router as payroll_router
from api.payslip import router as payslip_router
from api.performance_routes import router as performance_router
from api.permission_routes import role_limits_router
from api.permission_routes import router as permission_router
from api.role_api import router as role_router
from api.salary_items import router as salary_items_router
from api.schedule import router as schedule_router
from api.franchise_v4_routes import router as franchise_v4_router
from api.governance_routes import router as governance_router
from api.hr_dashboard_routes import router as hr_dashboard_router
from api.schedule_routes import router as schedule_v2_router
from api.store_clone_routes import router as store_clone_router
from api.store_ops_routes import router as store_ops_router
from api.transfers import router as transfer_router
from api.contribution_routes import router as contribution_router
from api.labor_margin_routes import router as labor_margin_router
from api.revenue_schedule_routes import router as revenue_schedule_router
from api.unified_schedule_routes import router as unified_schedule_router
from contextlib import asynccontextmanager
from fastapi import FastAPI
from shared.ontology.src.database import get_db as _shared_get_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 将真实 get_db 注入到 payroll_engine_routes 模块（覆盖其 stub）
    _payroll_engine_mod.get_db = _shared_get_db

    # ── Feature Flag 启动检查 ────────────────────────────────────────
    import structlog as _structlog
    _flag_logger = _structlog.get_logger(__name__)

    # OrgFlags.HR_REVENUE_SCHEDULE: 营收驱动智能排班
    if is_enabled(OrgFlags.HR_REVENUE_SCHEDULE):
        _flag_logger.info("feature_flag_enabled", flag=OrgFlags.HR_REVENUE_SCHEDULE,
                          note="营收驱动智能排班已激活，HRAgentScheduler将运行排班优化任务")
    else:
        _flag_logger.info("feature_flag_disabled", flag=OrgFlags.HR_REVENUE_SCHEDULE,
                          note="营收驱动排班已关闭，排班优化任务将跳过")

    # OrgFlags.HR_CONTRIBUTION_SCORE: 员工贡献度评分
    if is_enabled(OrgFlags.HR_CONTRIBUTION_SCORE):
        _flag_logger.info("feature_flag_enabled", flag=OrgFlags.HR_CONTRIBUTION_SCORE,
                          note="员工贡献度评分已激活，HRAgentScheduler将运行贡献度重算任务")
    else:
        _flag_logger.info("feature_flag_disabled", flag=OrgFlags.HR_CONTRIBUTION_SCORE,
                          note="员工贡献度评分已关闭，贡献度重算任务将跳过")

    # OrgFlags.HR_ATTRITION_MODEL: 7维离职预警模型
    if is_enabled(OrgFlags.HR_ATTRITION_MODEL):
        _flag_logger.info("feature_flag_enabled", flag=OrgFlags.HR_ATTRITION_MODEL,
                          note="离职预警模型已激活，HRAgentScheduler将运行离职风险扫描")
    else:
        _flag_logger.info("feature_flag_disabled", flag=OrgFlags.HR_ATTRITION_MODEL,
                          note="离职预警模型已关闭，离职风险扫描任务将跳过")

    # 启动 HR Agent 调度器（定时任务：合规扫描/离职风险/排班优化/贡献度重算）
    from services.hr_agent_scheduler import HRAgentScheduler
    scheduler = HRAgentScheduler()
    scheduler.start()

    # 启动 HR 事件消费器（监听 Redis Stream: org_events）
    from services.hr_event_consumer import HREventConsumer
    consumer = HREventConsumer()
    _consumer_task = asyncio.create_task(consumer.start())

    yield

    # 优雅关停
    consumer_stop = consumer.stop()
    scheduler.stop()
    await consumer_stop


app = FastAPI(title="TunxiangOS tx-org", version="3.0.0", lifespan=lifespan)

from prometheus_fastapi_instrumentator import Instrumentator
Instrumentator().instrument(app).expose(app)

app.include_router(emp_router)
app.include_router(schedule_router)
app.include_router(role_router)
app.include_router(transfer_router)
app.include_router(efficiency_router)
app.include_router(salary_items_router)
app.include_router(payslip_router)
app.include_router(employee_depth_router)
app.include_router(admin_router)
app.include_router(payroll_router)          # 薪资引擎 V4（v121 表，mock数据）前缀已内置 /api/v1/org/payroll
app.include_router(payroll_v2_router,      prefix="/api/v1/payroll")
app.include_router(approval_engine_router, prefix="/api/v1/approval-engine")
app.include_router(franchise_router)
app.include_router(franchise_v2_router)
app.include_router(approval_router,        prefix="/api/v1")
app.include_router(patrol_router,              prefix="/api/v1")
app.include_router(franchise_settlement_router)
app.include_router(permission_router)    # 权限检查 API（v075）
app.include_router(role_limits_router)   # 角色限制配置 CRUD（v075）
app.include_router(attendance_router)    # 考勤打卡 API（v077）
app.include_router(leave_router)         # 请假管理 API（v077）
app.include_router(store_clone_router)   # 快速开店克隆 API（v078）
app.include_router(device_router)        # 品牌级设备管理 API（v093）
app.include_router(ota_router)           # OTA 版本管理 API（v094）
app.include_router(compliance_router)
app.include_router(im_sync_router)       # IM 同步 API（企微/钉钉）
app.include_router(performance_router)
app.include_router(payroll_engine_v3_router)  # 薪资计算引擎 V3（v119 表）
app.include_router(franchise_mgmt_router)     # 加盟管理完整版（v125 表）
app.include_router(schedule_v2_router)        # 排班管理完整版（work_schedules 表）
app.include_router(franchise_v4_router)       # 加盟管理 V4（v060/v135/v155 表，DB版）
app.include_router(store_ops_router)          # 门店人力作战台 BFF（Sprint 1）
app.include_router(org_structure_router)      # 组织架构管理（Sprint 0）
app.include_router(job_grade_router)          # 岗位职级管理（Sprint 0）
app.include_router(employee_document_router)  # 员工证照管理（Sprint 0）
app.include_router(compliance_alert_router)   # 合规预警管理（Sprint 0）
app.include_router(unified_schedule_router)   # 统一排班中心（Sprint 1）
app.include_router(governance_router)         # 总部治理台 BFF（Sprint 6）
app.include_router(hr_dashboard_router)       # 人力中枢首页 BFF（Sprint 7）
app.include_router(contribution_router)        # 员工经营贡献度排名（POS数据→实时评分）
app.include_router(revenue_schedule_router)   # 营收驱动排班（POS数据→最优排班）
app.include_router(labor_margin_router)       # 人力成本实时毛利仪表盘（P2-5）

@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-org", "version": "3.0.0"}}
