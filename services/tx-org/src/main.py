"""tx-org — 域F 组织运营微服务

员工管理、排班、人力成本、考勤、绩效、培训
来源：57 个 service 文件迁移自 tunxiang V2.x（含 hr/ 子目录 25 个）
"""
from fastapi import FastAPI
from api.employees import router as emp_router
from api.schedule import router as schedule_router

app = FastAPI(title="TunxiangOS tx-org", version="3.0.0")
app.include_router(emp_router)
app.include_router(schedule_router)

@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-org", "version": "3.0.0"}}
