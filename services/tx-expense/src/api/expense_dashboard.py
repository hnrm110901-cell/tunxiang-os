"""
费控看板 API 路由

负责费控数据汇总、预算执行率展示、趋势分析等看板数据接口。
待P2实现，共5端点。
"""
from fastapi import APIRouter

router = APIRouter()

# TODO: GET /overview — 费控总览（本月/本季度支出、预算执行率、待审批数）
# TODO: GET /by-store — 按门店维度费控汇总（支持多门店对比）
# TODO: GET /by-category — 按科目维度费控汇总（科目占比/趋势）
# TODO: GET /trend — 费用趋势（月度/季度环比/同比）
# TODO: GET /top-applicants — 高频申请人排行（按申请金额/次数）
