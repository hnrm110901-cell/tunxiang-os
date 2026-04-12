"""
合同台账 API 路由

负责合同的登记、查询、到期提醒、关联费用管理。
待P1-S5实现，共5端点。
"""
from fastapi import APIRouter

router = APIRouter()

# TODO: POST / — 登记合同（含金额/甲乙方/有效期/附件）
# TODO: GET / — 合同列表（按状态/到期日/供应商过滤）
# TODO: GET /{contract_id} — 合同详情（含关联费用申请）
# TODO: PUT /{contract_id} — 更新合同信息（续签/变更）
# TODO: GET /expiring-soon — 即将到期合同（30天/60天/90天预警）
