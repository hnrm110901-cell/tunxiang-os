"""
备用金管理 API 路由

负责门店备用金的借款、还款、盘点、余额查询等操作。
待P0-S3实现，共8端点。
"""
from fastapi import APIRouter

router = APIRouter()

# TODO: POST /accounts — 创建备用金账户（门店级别）
# TODO: GET /accounts — 查询备用金账户列表（按门店过滤）
# TODO: GET /accounts/{account_id} — 账户详情（余额/流水汇总）
# TODO: POST /accounts/{account_id}/borrow — 借款申请
# TODO: POST /accounts/{account_id}/repay — 还款操作
# TODO: GET /accounts/{account_id}/transactions — 流水明细（分页）
# TODO: POST /accounts/{account_id}/inventory — 盘点记录（记录差异）
# TODO: GET /low-balance-alerts — 余额预警列表（低于阈值）
