"""
发票采集与核验 API 路由

负责发票的拍照采集、OCR解析、合规核验、归档管理。
待P0-S4实现，共7端点。
"""
from fastapi import APIRouter

router = APIRouter()

# TODO: POST /upload — 上传发票图片/PDF（触发OCR解析）
# TODO: GET /{invoice_id} — 发票详情（OCR结果/核验状态）
# TODO: PUT /{invoice_id} — 修正OCR识别结果（人工校正）
# TODO: POST /{invoice_id}/verify — 发票真伪核验（对接税务局接口）
# TODO: GET / — 发票列表（按申请单/状态/日期过滤）
# TODO: POST /{invoice_id}/attach — 关联到费用申请单
# TODO: GET /stats — 发票汇总统计（已用/未用/作废）
