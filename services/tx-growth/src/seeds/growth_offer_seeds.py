"""增长中枢V2 — 权益包种子数据

P0三类权益包：
1. 首单二访轻权益包 — 不发大额券，用轻体验引导回访
2. 召回权益分层包 — 按机制分3类（到期提醒/关系唤醒/最小行动）
3. 服务修复补偿包 — 给客户选择权的多选项补偿
"""
from __future__ import annotations

from typing import Any

GROWTH_OFFER_PACKS: list[dict[str, Any]] = [
    {
        "code": "pack_first_to_second_light",
        "name": "首单二访·轻权益包",
        "pack_type": "first_to_second",
        "mechanism_type": "micro_commitment",
        "description": "不发大额折扣券，用主厨小食/专属品鉴引导自然回访",
        "items": [
            {"type": "experience", "name": "主厨推荐小食", "description": "到店即享，不需额外消费", "cost_fen": 800},
            {"type": "privilege", "name": "优先排位", "description": "7天内到店免排队", "cost_fen": 0},
            {"type": "surprise", "name": "随机惊喜礼遇", "description": "可能是甜品/饮品/小食之一", "cost_fen": 500},
        ],
        "budget_limit_fen": 1500,
        "valid_days": 14,
    },
    {
        "code": "pack_reactivation_benefit_expiry",
        "name": "召回·权益到期提醒包",
        "pack_type": "reactivation",
        "mechanism_type": "loss_aversion",
        "description": "不给新权益，只提醒已有权益即将失效",
        "items": [
            {"type": "reminder", "name": "已有权益到期提醒", "description": "提醒客户已拥有的券/储值/积分将过期", "cost_fen": 0},
        ],
        "budget_limit_fen": 0,
        "valid_days": 7,
    },
    {
        "code": "pack_reactivation_warmup",
        "name": "召回·关系唤醒包",
        "pack_type": "reactivation",
        "mechanism_type": "relationship_warmup",
        "description": "轻问候+新品体验邀请，不带价格促销",
        "items": [
            {"type": "experience", "name": "新品品鉴邀请", "description": "主厨新创菜品免费品尝一份", "cost_fen": 1200},
        ],
        "budget_limit_fen": 1200,
        "valid_days": 14,
    },
    {
        "code": "pack_reactivation_minimal",
        "name": "召回·最小行动包",
        "pack_type": "reactivation",
        "mechanism_type": "minimal_action",
        "description": "一键预订入口+到店小礼，降低行动门槛",
        "items": [
            {"type": "convenience", "name": "一键预订通道", "description": "免电话，直接线上预订", "cost_fen": 0},
            {"type": "gift", "name": "到店伴手礼", "description": "到店即领精美伴手礼一份", "cost_fen": 600},
        ],
        "budget_limit_fen": 600,
        "valid_days": 7,
    },
    {
        "code": "pack_repair_compensation",
        "name": "服务修复·补偿选择包",
        "pack_type": "service_repair",
        "mechanism_type": "service_repair",
        "description": "给客户选择权：多种补偿方案自选其一",
        "items": [
            {"type": "refund", "name": "部分退款", "description": "退还本次消费的30%", "cost_fen": 0},
            {"type": "offset", "name": "下次全额抵扣", "description": "下次到店本单金额全额抵扣", "cost_fen": 0},
            {"type": "upgrade", "name": "包厢/席位升级", "description": "下次到店免费升级包厢或VIP席位", "cost_fen": 0},
            {"type": "gift", "name": "赠送招牌菜", "description": "下次到店赠送一道招牌菜", "cost_fen": 3000},
        ],
        "budget_limit_fen": 5000,
        "valid_days": 30,
    },
]
