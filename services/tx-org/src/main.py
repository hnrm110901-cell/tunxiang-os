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

app = FastAPI(title="TunxiangOS tx-org", version="3.0.0")
app.include_router(emp_router)
app.include_router(schedule_router)
app.include_router(role_router)
app.include_router(transfer_router)
app.include_router(efficiency_router)
app.include_router(salary_items_router)
app.include_router(payslip_router)

@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-org", "version": "3.0.0"}}
