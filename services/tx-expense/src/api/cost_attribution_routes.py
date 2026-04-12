"""
成本归因 API 路由

负责费用分摊规则配置、成本归因计算、门店成本追踪。
待P2-S2实现，共6端点。
"""
from fastapi import APIRouter

router = APIRouter()

# TODO: POST /rules — 创建分摊规则（按门店/部门/占比）
# TODO: GET /rules — 分摊规则列表
# TODO: PUT /rules/{rule_id} — 更新分摊规则
# TODO: POST /calculate — 触发归因计算（按周期/申请单）
# TODO: GET /results — 归因结果查询（按门店/科目/周期）
# TODO: GET /results/{result_id}/breakdown — 归因明细（分摊来源追溯）
