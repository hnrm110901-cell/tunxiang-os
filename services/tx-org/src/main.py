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

@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-org", "version": "3.0.0"}}
