"""
预算管理 API 路由

负责年度/季度预算设置、预算执行跟踪、超支预警等操作。
待P1-S6实现，共7端点。
"""
from fastapi import APIRouter

router = APIRouter()

# TODO: POST / — 创建预算（年度/季度，按门店/科目维度）
# TODO: GET / — 预算列表（按维度/周期过滤）
# TODO: GET /{budget_id} — 预算详情（含执行率/剩余额度）
# TODO: PUT /{budget_id} — 调整预算额度（需管理员权限）
# TODO: GET /{budget_id}/execution — 预算执行明细（关联费用申请）
# TODO: GET /warnings — 预算预警列表（执行率≥80% / ≥95%）
# TODO: GET /summary — 预算汇总报表（按门店/品牌/集团聚合）
