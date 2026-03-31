"""内置旅程模板 — 5个开箱即用的营销旅程

导入方式：
    from templates.journey_templates import TEMPLATES
    template = TEMPLATES["first_visit_welcome"]

模板说明：
  first_visit_welcome   — 首次到店欢迎旅程
  dormant_recall        — 沉睡客唤醒旅程
  birthday_vip          — 生日关怀旅程
  post_banquet          — 宴会后关怀旅程
  high_value_nurture    — 高价值客户培育旅程

步骤字段说明：
  step_id:       唯一步骤 ID（在旅程内唯一）
  action_type:   执行动作类型
  action_config: 动作配置（发消息用 template_id/message，发券用 coupon_template_id）
  wait_hours:    执行前等待时长（0=立即执行）
  next_steps:    下一步 step_id 列表（空=旅程结束）
"""

from typing import Any

TEMPLATES: dict[str, dict[str, Any]] = {

    # ─────────────────────────────────────────────────────────────────
    # 1. 首次到店欢迎旅程
    #    触发：first_visit（首次到店下单）
    #    路径：即刻感谢 → 48h后询问体验 → 7天未返回发券 → 14天标记召回目标
    # ─────────────────────────────────────────────────────────────────
    "first_visit_welcome": {
        "name": "首次到店欢迎旅程",
        "description": "客户首次到店后，48小时内发感谢消息，7天未返回发优惠券，14天后打召回标签",
        "trigger_event": "first_visit",
        "trigger_conditions": [],
        "target_segment": "new_customer",
        "steps": [
            {
                "step_id": "s1_welcome",
                "action_type": "send_wecom",
                "action_config": {
                    "template_id": "tpl_first_visit_welcome",
                    "message": "感谢您今天光临！我们很高兴为您服务，期待您的再次到来。如有任何问题，请随时联系我们 😊",
                },
                "wait_hours": 2,
                "next_steps": ["s2_wait_return"],
            },
            {
                "step_id": "s2_wait_return",
                "action_type": "wait",
                "action_config": {"wait_hours": 46},
                "wait_hours": 46,
                "next_steps": ["s3_check_return"],
            },
            {
                "step_id": "s3_check_return",
                "action_type": "condition_branch",
                "action_config": {
                    "condition": {
                        "field": "recency_days",
                        "operator": "lte",
                        "value": 2,
                    },
                    "true_next": "s4_end_happy",
                    "false_next": "s4_invite_back",
                },
                "wait_hours": 0,
                "next_steps": [],
            },
            {
                "step_id": "s4_invite_back",
                "action_type": "send_wecom",
                "action_config": {
                    "template_id": "tpl_invite_back_7d",
                    "message": "好久不见！上次您在我们这里用餐，不知道您是否满意？我们为您准备了一张专属优惠券，期待您的再次光临！",
                },
                "wait_hours": 0,
                "next_steps": ["s5_send_coupon"],
            },
            {
                "step_id": "s5_send_coupon",
                "action_type": "award_coupon",
                "action_config": {
                    "coupon_template_id": "ctp_new_customer_7d_recall",
                    "quantity": 1,
                    "note": "首次到店7天召回券",
                },
                "wait_hours": 0,
                "next_steps": ["s6_wait_recall"],
            },
            {
                "step_id": "s6_wait_recall",
                "action_type": "wait",
                "action_config": {"wait_hours": 168},
                "wait_hours": 168,
                "next_steps": ["s7_tag_if_not_returned"],
            },
            {
                "step_id": "s7_tag_if_not_returned",
                "action_type": "tag_customer",
                "action_config": {
                    "tags_add": ["14d_no_return", "recall_target"],
                    "tags_remove": ["new_customer_active"],
                },
                "wait_hours": 0,
                "next_steps": [],
            },
            {
                "step_id": "s4_end_happy",
                "action_type": "tag_customer",
                "action_config": {
                    "tags_add": ["second_visit_completed"],
                    "tags_remove": [],
                },
                "wait_hours": 0,
                "next_steps": [],
            },
        ],
    },

    # ─────────────────────────────────────────────────────────────────
    # 2. 沉睡客唤醒旅程
    #    触发：30day_inactive（30天未到店）
    #    路径：企微问候 → 3天无反应发券 → 7天标记流失
    # ─────────────────────────────────────────────────────────────────
    "dormant_recall": {
        "name": "沉睡客唤醒旅程",
        "description": "30天未到店客户，发企微问候 → 3天无反应发券 → 7天后标记流失",
        "trigger_event": "30day_inactive",
        "trigger_conditions": [
            {"field": "recency_days", "operator": "gte", "value": 30},
        ],
        "target_segment": "dormant",
        "steps": [
            {
                "step_id": "s1_greeting",
                "action_type": "send_wecom",
                "action_config": {
                    "template_id": "tpl_dormant_greeting",
                    "message": "您好，好久没见了！我们最近推出了几道新品，非常适合您的口味。期待您有时间再来尝尝 🍜",
                },
                "wait_hours": 0,
                "next_steps": ["s2_wait_response"],
            },
            {
                "step_id": "s2_wait_response",
                "action_type": "wait",
                "action_config": {"wait_hours": 72},
                "wait_hours": 72,
                "next_steps": ["s3_check_visit"],
            },
            {
                "step_id": "s3_check_visit",
                "action_type": "condition_branch",
                "action_config": {
                    "condition": {
                        "field": "recency_days",
                        "operator": "lte",
                        "value": 3,
                    },
                    "true_next": "s4_success_tag",
                    "false_next": "s4_send_coupon",
                },
                "wait_hours": 0,
                "next_steps": [],
            },
            {
                "step_id": "s4_send_coupon",
                "action_type": "award_coupon",
                "action_config": {
                    "coupon_template_id": "ctp_dormant_recall_coupon",
                    "quantity": 1,
                    "note": "沉睡客专属唤醒券",
                },
                "wait_hours": 0,
                "next_steps": ["s5_coupon_notify"],
            },
            {
                "step_id": "s5_coupon_notify",
                "action_type": "send_sms",
                "action_config": {
                    "template_id": "sms_tpl_recall_coupon",
                    "template_params": {
                        "brand_name": "{brand_name}",
                        "coupon_desc": "88折优惠券",
                        "expire_days": 7,
                    },
                },
                "wait_hours": 0,
                "next_steps": ["s6_wait_final"],
            },
            {
                "step_id": "s6_wait_final",
                "action_type": "wait",
                "action_config": {"wait_hours": 168},
                "wait_hours": 168,
                "next_steps": ["s7_mark_lost"],
            },
            {
                "step_id": "s7_mark_lost",
                "action_type": "tag_customer",
                "action_config": {
                    "tags_add": ["churned", "recall_failed"],
                    "tags_remove": ["dormant"],
                },
                "wait_hours": 0,
                "next_steps": [],
            },
            {
                "step_id": "s4_success_tag",
                "action_type": "tag_customer",
                "action_config": {
                    "tags_add": ["recall_success"],
                    "tags_remove": ["dormant", "churned"],
                },
                "wait_hours": 0,
                "next_steps": [],
            },
        ],
    },

    # ─────────────────────────────────────────────────────────────────
    # 3. 生日关怀旅程
    #    触发：birthday（生日前3天触发）
    #    路径：提前提醒预订 → 生日当天送权益 → 生日后7天复购跟进
    # ─────────────────────────────────────────────────────────────────
    "birthday_vip": {
        "name": "生日 VIP 关怀旅程",
        "description": "生日前3天提醒预订，生日当天发专属权益，7天后复购跟进",
        "trigger_event": "birthday",
        "trigger_conditions": [],
        "target_segment": "vip",
        "steps": [
            {
                "step_id": "s1_birthday_pre",
                "action_type": "send_wecom",
                "action_config": {
                    "template_id": "tpl_birthday_pre",
                    "message": "🎂 您的生日快到了！我们已为您预留专属座位，还准备了生日专属套餐，快来预订吧！使用生日码享受免费甜点。",
                },
                "wait_hours": 0,
                "next_steps": ["s2_wait_birthday"],
            },
            {
                "step_id": "s2_wait_birthday",
                "action_type": "wait",
                "action_config": {"wait_hours": 72},
                "wait_hours": 72,
                "next_steps": ["s3_birthday_gift"],
            },
            {
                "step_id": "s3_birthday_gift",
                "action_type": "award_coupon",
                "action_config": {
                    "coupon_template_id": "ctp_birthday_special",
                    "quantity": 1,
                    "note": "生日专属权益券",
                },
                "wait_hours": 0,
                "next_steps": ["s4_birthday_wish"],
            },
            {
                "step_id": "s4_birthday_wish",
                "action_type": "send_miniapp_push",
                "action_config": {
                    "template_id": "tmpl_birthday_wish_miniapp",
                    "page": "pages/birthday/index",
                    "data": {
                        "title": {"value": "🎂 生日快乐！"},
                        "content": {"value": "专属生日礼遇已送达，点击领取"},
                    },
                },
                "wait_hours": 0,
                "next_steps": ["s5_notify_staff"],
            },
            {
                "step_id": "s5_notify_staff",
                "action_type": "notify_staff",
                "action_config": {
                    "staff_role": "store_manager",
                    "message": "VIP客户 {phone} 今日生日，已发送专属礼遇，请主动问候",
                },
                "wait_hours": 0,
                "next_steps": ["s6_wait_followup"],
            },
            {
                "step_id": "s6_wait_followup",
                "action_type": "wait",
                "action_config": {"wait_hours": 168},
                "wait_hours": 168,
                "next_steps": ["s7_birthday_followup"],
            },
            {
                "step_id": "s7_birthday_followup",
                "action_type": "send_wecom",
                "action_config": {
                    "template_id": "tpl_birthday_followup",
                    "message": "生日过得开心吗？我们的生日优惠券还有效，欢迎近期再来，我们为您留着最好的位置 ❤️",
                },
                "wait_hours": 0,
                "next_steps": ["s8_birthday_tag"],
            },
            {
                "step_id": "s8_birthday_tag",
                "action_type": "tag_customer",
                "action_config": {
                    "tags_add": ["birthday_cared_2026"],
                    "tags_remove": [],
                },
                "wait_hours": 0,
                "next_steps": [],
            },
        ],
    },

    # ─────────────────────────────────────────────────────────────────
    # 4. 宴会后关怀旅程
    #    触发：banquet_completed（宴会完成后）
    #    路径：感谢+收集反馈 → 14天后推荐下次宴会
    # ─────────────────────────────────────────────────────────────────
    "post_banquet": {
        "name": "宴会后关怀旅程",
        "description": "宴会完成后发感谢+反馈问卷，14天后推荐下次宴会预订",
        "trigger_event": "banquet_completed",
        "trigger_conditions": [],
        "target_segment": "banquet_host",
        "steps": [
            {
                "step_id": "s1_thanks",
                "action_type": "send_wecom",
                "action_config": {
                    "template_id": "tpl_banquet_thanks",
                    "message": "感谢您选择我们举办宴会！希望宾客们宾至如归。请问此次宴会体验如何？您的建议对我们非常宝贵。",
                },
                "wait_hours": 4,
                "next_steps": ["s2_feedback"],
            },
            {
                "step_id": "s2_feedback",
                "action_type": "send_miniapp_push",
                "action_config": {
                    "template_id": "tmpl_banquet_feedback",
                    "page": "pages/feedback/banquet",
                    "data": {
                        "title": {"value": "宴会体验反馈"},
                        "content": {"value": "填写反馈，获得下次宴会专属折扣"},
                    },
                },
                "wait_hours": 0,
                "next_steps": ["s3_tag_vip"],
            },
            {
                "step_id": "s3_tag_vip",
                "action_type": "tag_customer",
                "action_config": {
                    "tags_add": ["banquet_host", "high_value_event"],
                    "tags_remove": [],
                },
                "wait_hours": 0,
                "next_steps": ["s4_wait_recommend"],
            },
            {
                "step_id": "s4_wait_recommend",
                "action_type": "wait",
                "action_config": {"wait_hours": 336},
                "wait_hours": 336,
                "next_steps": ["s5_next_banquet"],
            },
            {
                "step_id": "s5_next_banquet",
                "action_type": "send_wecom",
                "action_config": {
                    "template_id": "tpl_banquet_next_recommend",
                    "message": "上次宴会已过去两周，不知道您是否有近期宴会计划？我们为老客户提供专属档期和折扣，提前预订更有保障！",
                },
                "wait_hours": 0,
                "next_steps": ["s6_banquet_coupon"],
            },
            {
                "step_id": "s6_banquet_coupon",
                "action_type": "award_coupon",
                "action_config": {
                    "coupon_template_id": "ctp_banquet_repeat_discount",
                    "quantity": 1,
                    "note": "宴会回头客专属折扣",
                },
                "wait_hours": 0,
                "next_steps": [],
            },
        ],
    },

    # ─────────────────────────────────────────────────────────────────
    # 5. 高价值客户培育旅程
    #    触发：high_ltv（LTV 超阈值）
    #    路径：专属客服分配 → 月度专属权益
    # ─────────────────────────────────────────────────────────────────
    "high_value_nurture": {
        "name": "高价值客户培育旅程",
        "description": "LTV超阈值触发，分配专属客服并每月发放专属权益",
        "trigger_event": "high_ltv",
        "trigger_conditions": [
            {"field": "ltv_score", "operator": "gte", "value": 5000},
        ],
        "target_segment": "high_value",
        "steps": [
            {
                "step_id": "s1_tag_vip",
                "action_type": "tag_customer",
                "action_config": {
                    "tags_add": ["high_value_vip", "personal_service"],
                    "tags_remove": ["standard_tier"],
                },
                "wait_hours": 0,
                "next_steps": ["s2_notify_staff"],
            },
            {
                "step_id": "s2_notify_staff",
                "action_type": "notify_staff",
                "action_config": {
                    "staff_role": "vip_manager",
                    "message": "新晋高价值客户 {phone}（LTV: {ltv_score}元），请尽快建立专属服务档案并主动联系",
                },
                "wait_hours": 0,
                "next_steps": ["s3_welcome_vip"],
            },
            {
                "step_id": "s3_welcome_vip",
                "action_type": "send_wecom",
                "action_config": {
                    "template_id": "tpl_vip_welcome",
                    "message": "您好！感谢您一直以来对我们的厚爱 ❤️ 您已被升级为尊享会员，我们已为您配备专属客服，如有任何需求请随时告知。",
                },
                "wait_hours": 1,
                "next_steps": ["s4_monthly_benefit"],
            },
            {
                "step_id": "s4_monthly_benefit",
                "action_type": "award_coupon",
                "action_config": {
                    "coupon_template_id": "ctp_vip_monthly_benefit",
                    "quantity": 1,
                    "note": "高价值VIP月度专属权益",
                },
                "wait_hours": 0,
                "next_steps": ["s5_benefit_notify"],
            },
            {
                "step_id": "s5_benefit_notify",
                "action_type": "send_miniapp_push",
                "action_config": {
                    "template_id": "tmpl_vip_monthly_benefit",
                    "page": "pages/vip/benefits",
                    "data": {
                        "title": {"value": "🎁 您的专属月度权益已到账"},
                        "content": {"value": "点击查看，立享尊享服务"},
                    },
                },
                "wait_hours": 0,
                "next_steps": [],
            },
        ],
    },
}
