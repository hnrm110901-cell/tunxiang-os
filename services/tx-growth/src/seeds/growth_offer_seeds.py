"""增长中枢V2 — 权益包种子数据

P0三类权益包：
1. 首单二访轻权益包 — 不发大额券，用轻体验引导回访
2. 召回权益分层包 — 按机制分3类（到期提醒/关系唤醒/最小行动）
3. 服务修复补偿包 — 给客户选择权的多选项补偿

P1三类权益包：
6. 超级用户关系权益包 — 非折扣型专属体验
7. 里程碑庆祝权益包 — 按等级递进的权益
8. 裂变场景激励包 — 推荐人+被推荐人双向激励

P2三类权益包 (V2.1 Sprint A):
9. 储值续航包 — 激活沉睡储值余额
10. 宴席复购包 — 高价值宴席客户关系维护
11. 渠道回流包 — 平台客转品牌客激励
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
            {
                "type": "reminder",
                "name": "已有权益到期提醒",
                "description": "提醒客户已拥有的券/储值/积分将过期",
                "cost_fen": 0,
            },
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
    # ══════════════════════════════════════════════════════════
    # P1 扩展权益包
    # ══════════════════════════════════════════════════════════
    {
        "code": "pack_super_user_relationship",
        "name": "超级用户·关系权益包",
        "pack_type": "super_user",
        "mechanism_type": "super_user_exclusive",
        "description": "非折扣型专属体验权益，通过稀缺性与尊贵感维护超级用户关系",
        "items": [
            {
                "type": "privilege",
                "name": "专属包厢优先预订",
                "description": "超级用户可优先预订VIP包厢，无需排队",
                "cost_fen": 0,
            },
            {
                "type": "experience",
                "name": "新品试菜资格",
                "description": "主厨新品上市前优先品鉴，提供反馈即可",
                "cost_fen": 2000,
            },
            {
                "type": "experience",
                "name": "主厨定制菜单",
                "description": "主厨根据超级用户口味偏好定制专属菜单",
                "cost_fen": 5000,
            },
            {
                "type": "experience",
                "name": "年度感谢晚宴邀请",
                "description": "每年一次品牌感谢晚宴，仅限超级用户参加",
                "cost_fen": 15000,
            },
        ],
        "budget_limit_fen": 22000,
        "valid_days": 365,
    },
    {
        "code": "pack_milestone_celebration",
        "name": "里程碑·庆祝权益包",
        "pack_type": "milestone",
        "mechanism_type": "milestone_celebration",
        "description": "按里程碑等级递进的权益，每达到新里程碑解锁对应权益",
        "items": [
            {
                "type": "gift",
                "name": "regular·专属甜品",
                "description": "达成常客里程碑，赠送招牌甜品一份",
                "cost_fen": 800,
            },
            {
                "type": "privilege",
                "name": "loyal·免排队特权",
                "description": "达成忠诚客里程碑，享30天免排队特权",
                "cost_fen": 0,
            },
            {
                "type": "experience",
                "name": "vip·主厨私房菜",
                "description": "达成VIP里程碑，赠送主厨私房菜品鉴一次",
                "cost_fen": 3000,
            },
            {
                "type": "experience",
                "name": "legend·专属晚宴席位",
                "description": "达成传奇里程碑，获年度感谢晚宴永久席位",
                "cost_fen": 8000,
            },
            {
                "type": "privilege",
                "name": "全等级·进度徽章",
                "description": "每个里程碑对应专属电子徽章，在小程序展示",
                "cost_fen": 0,
            },
        ],
        "budget_limit_fen": 12000,
        "valid_days": 90,
    },
    {
        "code": "pack_referral_incentive",
        "name": "裂变场景·激励权益包",
        "pack_type": "referral",
        "mechanism_type": "referral_activation",
        "description": "推荐人与被推荐人双向激励，鼓励优质客户的社交裂变",
        "items": [
            {
                "type": "reward",
                "name": "推荐人奖励·感谢礼遇",
                "description": "每成功推荐1位新客，推荐人获得主厨小食一份",
                "cost_fen": 800,
            },
            {
                "type": "gift",
                "name": "被推荐人·首次专属礼",
                "description": "被推荐新客首次到店享专属欢迎小食+饮品",
                "cost_fen": 1200,
            },
            {
                "type": "experience",
                "name": "双方·专属聚餐优惠",
                "description": "推荐人与被推荐人同桌用餐，赠送招牌菜一道",
                "cost_fen": 2500,
            },
        ],
        "budget_limit_fen": 4500,
        "valid_days": 30,
    },
    # ══════════════════════════════════════════════════════════
    # P2 场景权益包 (V2.1 Sprint A)
    # ══════════════════════════════════════════════════════════
    {
        "code": "pack_stored_value_renewal",
        "name": "储值续航·余额唤醒包",
        "pack_type": "stored_value",
        "mechanism_type": "loss_aversion",
        "description": "激活沉睡储值余额，通过体验邀请和优先通道引导到店使用",
        "items": [
            {
                "type": "reminder",
                "name": "储值余额使用提醒",
                "description": "提醒客户储值卡剩余余额及使用方式",
                "cost_fen": 0,
            },
            {
                "type": "experience",
                "name": "专属品鉴体验",
                "description": "储值贵宾专属品鉴体验一次，直接从储值卡扣款",
                "cost_fen": 1500,
            },
            {
                "type": "privilege",
                "name": "优先预订通道",
                "description": "储值客户专属快捷预订入口，免排队",
                "cost_fen": 0,
            },
        ],
        "budget_limit_fen": 1500,
        "valid_days": 14,
    },
    {
        "code": "pack_banquet_repurchase",
        "name": "宴席复购·关系维护包",
        "pack_type": "banquet",
        "mechanism_type": "relationship",
        "description": "通过服务升级和体验增值维护高价值宴席客户关系，驱动复购",
        "items": [
            {
                "type": "privilege",
                "name": "包厢优先预订",
                "description": "宴席客户可优先预订VIP包厢，节假日也不排队",
                "cost_fen": 0,
            },
            {
                "type": "privilege",
                "name": "定制菜单服务",
                "description": "根据宴请场景和口味偏好定制专属菜单",
                "cost_fen": 0,
            },
            {
                "type": "experience",
                "name": "宴席布置升级",
                "description": "免费升级宴席桌面布置和氛围装饰",
                "cost_fen": 3000,
            },
            {"type": "gift", "name": "赠送招牌甜品", "description": "宴席结束赠送招牌甜品拼盘一份", "cost_fen": 1500},
        ],
        "budget_limit_fen": 5000,
        "valid_days": 30,
    },
    {
        "code": "pack_channel_reflow",
        "name": "渠道回流·平台客转化包",
        "pack_type": "channel_reflow",
        "mechanism_type": "hook",
        "description": "通过到店专属权益和储值体验金，将平台客户转化为品牌自有会员",
        "items": [
            {"type": "gift", "name": "品牌会员礼", "description": "首次到店领取精美伴手小礼品一份", "cost_fen": 500},
            {
                "type": "experience",
                "name": "首次到店专属菜品",
                "description": "到店专享品牌招牌菜一道，平台渠道不提供",
                "cost_fen": 1200,
            },
            {
                "type": "stored_value",
                "name": "储值体验金",
                "description": "充100送20元体验金，感受储值便利",
                "cost_fen": 2000,
            },
        ],
        "budget_limit_fen": 3700,
        "valid_days": 14,
    },
]
