"""
差旅费用 API 路由

负责出差申请、行程管理、差旅报销实报实销等操作。
待P1-S3实现，共8端点。
"""
from fastapi import APIRouter

router = APIRouter()

# TODO: POST /requests — 创建出差申请（含目的地/日期/预算）
# TODO: GET /requests — 出差申请列表（按状态/人员/日期过滤）
# TODO: GET /requests/{request_id} — 出差申请详情
# TODO: POST /requests/{request_id}/submit — 提交出差申请（触发审批）
# TODO: POST /expense-reports — 提交差旅报销单（关联出差申请）
# TODO: GET /expense-reports — 差旅报销列表
# TODO: GET /expense-reports/{report_id} — 报销单详情（含行程明细/票据）
# TODO: GET /allowance-standards — 差旅补贴标准查询（城市级别）
