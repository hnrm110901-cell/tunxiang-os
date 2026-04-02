"""tx-org — 域F 组织运营微服务

员工管理、排班、人力成本、考勤、绩效、培训
来源：57 个 service 文件迁移自 tunxiang V2.x（含 hr/ 子目录 25 个）
"""
from fastapi import FastAPI
from api.employees import router as emp_router
from api.schedule import router as schedule_router
from api.role_api import router as role_router
from api.transfers import router as transfer_router
from api.efficiency import router as efficiency_router
from api.salary_items import router as salary_items_router
from api.payslip import router as payslip_router
from api.employee_depth_routes import router as employee_depth_router
from api.admin_routes import router as admin_router
from api.payroll_routes import router as payroll_router
from api.approval_engine_routes import router as approval_engine_router
from api.franchise_routes import router as franchise_router
from api.franchise_router import router as franchise_v2_router
from api.approval_router import router as approval_router
from api.payroll_router import router as payroll_v2_router
from api.patrol_routes import router as patrol_router
from api.franchise_settlement_routes import router as franchise_settlement_router
from api.permission_routes import router as permission_router
from api.permission_routes import role_limits_router
from api.attendance_routes import router as attendance_router
from api.leave_routes import router as leave_router
from api.store_clone_routes import router as store_clone_router
from api.device_routes import router as device_router
from api.ota_routes import router as ota_router
from api.compliance_routes import router as compliance_router
from api.im_sync_routes import router as im_sync_router
from api.performance_routes import router as performance_router

app = FastAPI(title="TunxiangOS tx-org", version="3.0.0")
app.include_router(emp_router)
app.include_router(schedule_router)
app.include_router(role_router)
app.include_router(transfer_router)
app.include_router(efficiency_router)
app.include_router(salary_items_router)
app.include_router(payslip_router)
app.include_router(employee_depth_router)
app.include_router(admin_router)
app.include_router(payroll_router,         prefix="/api/v1/payroll")
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

@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-org", "version": "3.0.0"}}
