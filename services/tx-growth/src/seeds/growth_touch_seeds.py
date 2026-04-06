"""增长中枢V2 — 系统触达模板种子数据（认知友好模板库）

按心理机制分类而非按节日分类。
每个模板包含: 机制类型、渠道、语气、内容模板、变量schema、禁止用语。

P0 — 8个认知友好模板:
- identity_anchor    身份锚定（首单欢迎）
- micro_commitment   最小承诺（回访引导）
- variable_reward    多样化奖励（随机惊喜）
- loss_aversion      损失厌恶（权益到期提醒）
- relationship_warmup 关系唤醒（轻问候）
- minimal_action     最小行动（一键操作）
- service_repair x2  服务修复（情绪承接 + 补偿方案）

P1 — 11个扩展模板:
- super_user_exclusive x4  超级用户（欢迎/特权/推荐赋能/季节专属）
- psych_bridge x2          心理距离修复（轻触达/关系重建）
- milestone_celebration x2 里程碑庆祝（恭喜/进度可见性）
- referral_activation x3   裂变激活（生日/家庭/通用）
"""
from typing import Any

SYSTEM_TOUCH_TEMPLATES: list[dict[str, Any]] = [
    # ──────────────────────────────────────────────────────────
    # 1. 身份锚定·首单欢迎
    # 心理机制: 给客户赋予"贵宾"身份标签，建立归属感
    # 禁止: 任何促销/打折语言（此刻目的是建立身份，不是卖东西）
    # ──────────────────────────────────────────────────────────
    {
        "code": "tmpl_identity_anchor_welcome",
        "name": "身份确认·首单欢迎",
        "template_family": "first_to_second",
        "mechanism_type": "identity_anchor",
        "channel": "wecom",  # 企微
        "tone": "warm",
        "content_template": (
            "{customer_name}您好！感谢您成为{brand_name}的贵宾。"
            "您的专属会员身份已生效，下次到店出示即享贵宾待遇。"
            "期待再次为您服务 🤝"
        ),
        "variables_schema_json": [
            {"name": "customer_name", "type": "string", "required": True},
            {"name": "brand_name", "type": "string", "required": True},
        ],
        "forbidden_phrases_json": ["促销", "打折", "优惠券", "限时"],
        "requires_human_review": False,
        "is_system": True,
    },

    # ──────────────────────────────────────────────────────────
    # 2. 最小承诺·回访引导
    # 心理机制: 用极低门槛的承诺引导行动（"不需要额外消费"）
    # 禁止: 最低消费、满减等增加行动阻力的语言
    # ──────────────────────────────────────────────────────────
    {
        "code": "tmpl_micro_commitment_return",
        "name": "最小承诺·回访引导",
        "template_family": "first_to_second",
        "mechanism_type": "micro_commitment",
        "channel": "wecom",
        "tone": "warm",
        "content_template": (
            "{customer_name}，上次您点的{favorite_dish}是我们的招牌。"
            "这周内回来，为您留了一份主厨小食作为回馈。"
            "不需要额外消费，到店跟服务员说一声就好。"
        ),
        "variables_schema_json": [
            {"name": "customer_name", "type": "string", "required": True},
            {"name": "favorite_dish", "type": "string", "required": True},
        ],
        "forbidden_phrases_json": ["必须消费", "最低消费", "满减"],
        "requires_human_review": False,
        "is_system": True,
    },

    # ──────────────────────────────────────────────────────────
    # 3. 多样化奖励·随机惊喜
    # 心理机制: 不确定性奖励比固定奖励更有吸引力（多巴胺驱动）
    # 渠道: 小程序（需要点击链接查看）
    # 禁止: 暗示群发的语言（必须让客户感到专属）
    # ──────────────────────────────────────────────────────────
    {
        "code": "tmpl_variable_reward_surprise",
        "name": "多样化奖励·随机惊喜",
        "template_family": "first_to_second",
        "mechanism_type": "variable_reward",
        "channel": "miniapp",  # 小程序
        "tone": "warm",
        "content_template": (
            "{customer_name}，我们为您准备了一份专属惊喜礼遇，"
            "点击查看是什么 → {link}。每位贵宾的礼遇都不同哦。"
        ),
        "variables_schema_json": [
            {"name": "customer_name", "type": "string", "required": True},
            {"name": "link", "type": "string", "required": True},
        ],
        "forbidden_phrases_json": ["群发", "所有人"],
        "requires_human_review": False,
        "is_system": True,
    },

    # ──────────────────────────────────────────────────────────
    # 4. 损失厌恶·权益到期提醒
    # 心理机制: 人对失去的恐惧大于获得的快乐（"即将失效">"给您一张券"）
    # 关键: 只提醒已有权益，不创造新权益
    # 禁止: 新优惠、额外赠送（这会破坏损失厌恶的纯粹性）
    # ──────────────────────────────────────────────────────────
    {
        "code": "tmpl_loss_aversion_benefit_expiring",
        "name": "损失厌恶·权益到期提醒",
        "template_family": "reactivation",
        "mechanism_type": "loss_aversion",
        "channel": "wecom",
        "tone": "urgent",
        "content_template": (
            "{customer_name}，温馨提醒：您在{brand_name}的{benefit_name}"
            "将于{expire_date}失效。这是您之前获得的专属权益，过期后将无法恢复。"
            "如需使用，可直接预订 → {booking_link}"
        ),
        "variables_schema_json": [
            {"name": "customer_name", "type": "string", "required": True},
            {"name": "brand_name", "type": "string", "required": True},
            {"name": "benefit_name", "type": "string", "required": True},
            {"name": "expire_date", "type": "string", "required": True},
            {"name": "booking_link", "type": "string", "required": False},
        ],
        "forbidden_phrases_json": ["再给您一张券", "新优惠", "额外赠送"],
        "requires_human_review": False,
        "is_system": True,
    },

    # ──────────────────────────────────────────────────────────
    # 5. 关系唤醒·轻问候
    # 心理机制: 用人情味唤醒关系，不提任何促销
    # 适用: 无已有权益的沉默客户
    # 禁止: "好久不见"等过度亲密语言、"快来消费"等促销语言
    # ──────────────────────────────────────────────────────────
    {
        "code": "tmpl_relationship_warmup",
        "name": "关系唤醒·轻问候",
        "template_family": "reactivation",
        "mechanism_type": "relationship_warmup",
        "channel": "wecom",
        "tone": "warm",
        "content_template": (
            "{customer_name}您好，{brand_name}的{store_manager}问候您。"
            "最近{seasonal_context}，我们的厨师团队准备了几道新菜，想到您可能会喜欢。"
            "方便时欢迎来坐坐。"
        ),
        "variables_schema_json": [
            {"name": "customer_name", "type": "string", "required": True},
            {"name": "brand_name", "type": "string", "required": True},
            {"name": "store_manager", "type": "string", "required": True},
            {"name": "seasonal_context", "type": "string", "required": False},
        ],
        "forbidden_phrases_json": ["好久不见", "想你了", "快来消费"],
        "requires_human_review": False,
        "is_system": True,
    },

    # ──────────────────────────────────────────────────────────
    # 6. 最小行动·一键操作
    # 心理机制: 将行动门槛降到最低（一键完成，不需要思考）
    # 渠道: 小程序（链接直达操作页面）
    # 禁止: 催促性语言（"赶快""马上""错过"）
    # ──────────────────────────────────────────────────────────
    {
        "code": "tmpl_minimal_action_simple",
        "name": "最小行动·一键操作",
        "template_family": "reactivation",
        "mechanism_type": "minimal_action",
        "channel": "miniapp",
        "tone": "neutral",
        "content_template": (
            "{customer_name}，{brand_name}为您保留了一个便捷入口。"
            "一键即可完成：{action_description} → {action_link}"
        ),
        "variables_schema_json": [
            {"name": "customer_name", "type": "string", "required": True},
            {"name": "brand_name", "type": "string", "required": True},
            {"name": "action_description", "type": "string", "required": True},
            {"name": "action_link", "type": "string", "required": True},
        ],
        "forbidden_phrases_json": ["赶快", "马上", "错过"],
        "requires_human_review": False,
        "is_system": True,
    },

    # ──────────────────────────────────────────────────────────
    # 7. 服务修复·情绪承接
    # 心理机制: 先接住情绪，不急于解决问题
    # 渠道: manual_task（必须由店长/经理人工发送，确保语气真诚）
    # 禁止: 任何辩解性语言（"但是""不过""其实是"等）
    # 关键: requires_human_review=True，修复类触达必须人工审核
    # ──────────────────────────────────────────────────────────
    {
        "code": "tmpl_repair_ack_empathy",
        "name": "服务修复·情绪承接",
        "template_family": "service_repair",
        "mechanism_type": "service_repair",
        "channel": "manual_task",
        "tone": "apologetic",
        "content_template": (
            "{customer_name}您好，我是{brand_name}{store_name}的{manager_name}。"
            "关于您上次的用餐体验，我们非常重视您的反馈。"
            "首先向您真诚致歉，这不是我们应有的服务水准。"
            "我已经了解了情况，想听听您的想法，看我们能怎样弥补。"
            "方便时请回复，我随时在。"
        ),
        "variables_schema_json": [
            {"name": "customer_name", "type": "string", "required": True},
            {"name": "brand_name", "type": "string", "required": True},
            {"name": "store_name", "type": "string", "required": True},
            {"name": "manager_name", "type": "string", "required": True},
        ],
        "forbidden_phrases_json": ["但是", "不过", "我们也", "您误会了", "其实是"],
        "requires_human_review": True,  # 修复类必须人工审核
        "is_system": True,
    },

    # ──────────────────────────────────────────────────────────
    # 8. 服务修复·补偿方案
    # 心理机制: 给客户选择权（控制感恢复）
    # 渠道: manual_task（补偿方案必须人工确认后发送）
    # 禁止: 限制性语言（"只能""不能退""公司规定"等）
    # 关键: requires_human_review=True
    # ──────────────────────────────────────────────────────────
    {
        "code": "tmpl_repair_compensation",
        "name": "服务修复·补偿方案",
        "template_family": "service_repair",
        "mechanism_type": "service_repair",
        "channel": "manual_task",
        "tone": "apologetic",
        "content_template": (
            "{customer_name}，感谢您的耐心。为了表达歉意，"
            "我们为您准备了以下方案，您可以选择最合适的：\n\n"
            "{compensation_options}\n\n"
            "无论您选择哪个，我们都会安排专人跟进。期待能有机会重新为您服务。"
        ),
        "variables_schema_json": [
            {"name": "customer_name", "type": "string", "required": True},
            {"name": "compensation_options", "type": "string", "required": True},
        ],
        "forbidden_phrases_json": ["只能", "不能退", "没办法", "公司规定"],
        "requires_human_review": True,  # 补偿方案必须人工审核
        "is_system": True,
    },

    # ══════════════════════════════════════════════════════════
    # P1 扩展模板
    # ══════════════════════════════════════════════════════════

    # ──────────────────────────────────────────────────────────
    # 9. 超级用户·身份仪式
    # 心理机制: 身份仪式感（恭喜晋升+专属权益一览）
    # 禁止: 普通/一般/群发（必须让客户感受到独一无二的尊贵）
    # ──────────────────────────────────────────────────────────
    {
        "code": "tmpl_super_user_welcome",
        "name": "超级用户·身份仪式",
        "template_family": "super_user",
        "mechanism_type": "super_user_exclusive",
        "channel": "wecom",
        "tone": "exclusive",
        "content_template": (
            "恭喜{customer_name}！您已成为{brand_name}的{super_level}超级用户。"
            "作为品牌最珍贵的朋友，您将享有：{privileges_list}。"
            "期待与您一起创造更多美好用餐体验。"
        ),
        "variables_schema_json": [
            {"name": "customer_name", "type": "string", "required": True},
            {"name": "brand_name", "type": "string", "required": True},
            {"name": "super_level", "type": "string", "required": True},
            {"name": "privileges_list", "type": "string", "required": True},
        ],
        "forbidden_phrases_json": ["普通", "一般", "群发"],
        "requires_human_review": False,
        "is_system": True,
    },

    # ──────────────────────────────────────────────────────────
    # 10. 超级用户·特权体验
    # 心理机制: 专属体验（新品试菜/主厨晚宴）
    # 禁止: 优惠券/打折/促销（超级用户不需要折扣驱动）
    # ──────────────────────────────────────────────────────────
    {
        "code": "tmpl_super_user_privilege",
        "name": "超级用户·特权体验",
        "template_family": "super_user",
        "mechanism_type": "super_user_exclusive",
        "channel": "wecom",
        "tone": "exclusive",
        "content_template": (
            "{customer_name}，{brand_name}为您准备了一场专属体验：{experience_desc}。"
            "仅限{super_level}及以上贵宾参与，名额有限。"
            "如您感兴趣，回复确认即可预留席位。"
        ),
        "variables_schema_json": [
            {"name": "customer_name", "type": "string", "required": True},
            {"name": "brand_name", "type": "string", "required": True},
            {"name": "super_level", "type": "string", "required": True},
            {"name": "experience_desc", "type": "string", "required": True},
        ],
        "forbidden_phrases_json": ["优惠券", "打折", "促销"],
        "requires_human_review": False,
        "is_system": True,
    },

    # ──────────────────────────────────────────────────────────
    # 11. 超级用户·推荐赋能
    # 心理机制: 社交赋能（让超级用户成为品牌大使）
    # 渠道: 小程序（需要分享链接）
    # ──────────────────────────────────────────────────────────
    {
        "code": "tmpl_super_user_referral_invite",
        "name": "超级用户·推荐赋能",
        "template_family": "super_user",
        "mechanism_type": "referral_empowerment",
        "channel": "miniapp",
        "tone": "warm",
        "content_template": (
            "{customer_name}，作为{brand_name}的{super_level}，"
            "您可以分享专属邀请给好友。被您邀请的朋友将享有{friend_benefit}，"
            "您也将获得{referrer_reward}。\u2192 {share_link}"
        ),
        "variables_schema_json": [
            {"name": "customer_name", "type": "string", "required": True},
            {"name": "brand_name", "type": "string", "required": True},
            {"name": "super_level", "type": "string", "required": True},
            {"name": "friend_benefit", "type": "string", "required": True},
            {"name": "referrer_reward", "type": "string", "required": True},
            {"name": "share_link", "type": "string", "required": True},
        ],
        "forbidden_phrases_json": ["群发", "所有人", "不限"],
        "requires_human_review": False,
        "is_system": True,
    },

    # ──────────────────────────────────────────────────────────
    # 12. 超级用户·季节专属
    # 心理机制: 季节限定体验（稀缺性+专属感）
    # ──────────────────────────────────────────────────────────
    {
        "code": "tmpl_super_user_seasonal",
        "name": "超级用户·季节专属",
        "template_family": "super_user",
        "mechanism_type": "super_user_exclusive",
        "channel": "wecom",
        "tone": "warm",
        "content_template": (
            "{customer_name}，{seasonal_context}到了。"
            "{brand_name}主厨为{super_level}贵宾特别准备了{seasonal_dish}，数量有限。"
            "回复'预订'即可安排。"
        ),
        "variables_schema_json": [
            {"name": "customer_name", "type": "string", "required": True},
            {"name": "brand_name", "type": "string", "required": True},
            {"name": "super_level", "type": "string", "required": True},
            {"name": "seasonal_context", "type": "string", "required": True},
            {"name": "seasonal_dish", "type": "string", "required": True},
        ],
        "forbidden_phrases_json": ["打折", "促销", "优惠券", "群发"],
        "requires_human_review": False,
        "is_system": True,
    },

    # ──────────────────────────────────────────────────────────
    # 13. 心理距离修复·轻触达
    # 心理机制: 低侵入性信息分享（不打扰，只告知）
    # 适用: abstracted客户（心理距离已远，需极轻触达）
    # 禁止: 好久不见/想你/快来/优惠（这些会加深距离感）
    # ──────────────────────────────────────────────────────────
    {
        "code": "tmpl_psych_bridge_gentle",
        "name": "心理距离修复·轻触达",
        "template_family": "psych_distance",
        "mechanism_type": "psych_bridge",
        "channel": "sms",
        "tone": "neutral",
        "content_template": (
            "{customer_name}，{brand_name}有些新变化想和您分享。"
            "不打扰，只是想让您知道。\u2192 {info_link}"
        ),
        "variables_schema_json": [
            {"name": "customer_name", "type": "string", "required": True},
            {"name": "brand_name", "type": "string", "required": True},
            {"name": "info_link", "type": "string", "required": True},
        ],
        "forbidden_phrases_json": ["好久不见", "想你", "快来", "优惠"],
        "requires_human_review": False,
        "is_system": True,
    },

    # ──────────────────────────────────────────────────────────
    # 14. 心理距离修复·关系重建
    # 心理机制: 人情味关系重建（有名有姓的店员问候）
    # 适用: fading客户（心理距离开始变远，还有关系记忆）
    # ──────────────────────────────────────────────────────────
    {
        "code": "tmpl_psych_bridge_warmup",
        "name": "心理距离修复·关系重建",
        "template_family": "psych_distance",
        "mechanism_type": "psych_bridge",
        "channel": "wecom",
        "tone": "warm",
        "content_template": (
            "{customer_name}您好，{brand_name}{store_name}的{staff_name}向您问好。"
            "最近我们的{change_desc}，想到您可能会感兴趣。"
            "如果方便，欢迎随时来坐坐。"
        ),
        "variables_schema_json": [
            {"name": "customer_name", "type": "string", "required": True},
            {"name": "brand_name", "type": "string", "required": True},
            {"name": "store_name", "type": "string", "required": True},
            {"name": "staff_name", "type": "string", "required": True},
            {"name": "change_desc", "type": "string", "required": True},
        ],
        "forbidden_phrases_json": ["好久不见", "想你了", "快来消费", "促销"],
        "requires_human_review": False,
        "is_system": True,
    },

    # ──────────────────────────────────────────────────────────
    # 15. 里程碑·进阶恭喜
    # 心理机制: 成就庆祝（让客户感受到进步与认可）
    # 渠道: 小程序（需要展示勋章/权益详情页）
    # ──────────────────────────────────────────────────────────
    {
        "code": "tmpl_milestone_congrats",
        "name": "里程碑·进阶恭喜",
        "template_family": "milestone",
        "mechanism_type": "milestone_celebration",
        "channel": "miniapp",
        "tone": "celebratory",
        "content_template": (
            "\U0001f389 恭喜{customer_name}！您在{brand_name}达成了{milestone_name}成就！"
            "这意味着您已解锁：{unlocked_privileges}。"
            "感谢您一直以来的支持！"
        ),
        "variables_schema_json": [
            {"name": "customer_name", "type": "string", "required": True},
            {"name": "brand_name", "type": "string", "required": True},
            {"name": "milestone_name", "type": "string", "required": True},
            {"name": "unlocked_privileges", "type": "string", "required": True},
        ],
        "forbidden_phrases_json": ["打折", "促销", "群发"],
        "requires_human_review": False,
        "is_system": True,
    },

    # ──────────────────────────────────────────────────────────
    # 16. 里程碑·进度可见性
    # 心理机制: 进度可见性（告知距下一里程碑的距离，激发内驱力）
    # 渠道: 小程序（进度条展示）
    # ──────────────────────────────────────────────────────────
    {
        "code": "tmpl_milestone_next_goal",
        "name": "里程碑·进度可见性",
        "template_family": "milestone",
        "mechanism_type": "milestone_celebration",
        "channel": "miniapp",
        "tone": "warm",
        "content_template": (
            "{customer_name}，您距离下一个成就\u201c{next_milestone}\u201d"
            "还差{remaining_count}次用餐。继续加油！"
            "每一次到店都在积累您的专属权益。"
        ),
        "variables_schema_json": [
            {"name": "customer_name", "type": "string", "required": True},
            {"name": "next_milestone", "type": "string", "required": True},
            {"name": "remaining_count", "type": "integer", "required": True},
        ],
        "forbidden_phrases_json": ["催促", "赶快", "错过"],
        "requires_human_review": False,
        "is_system": True,
    },

    # ──────────────────────────────────────────────────────────
    # 17. 裂变·生日组织者
    # 心理机制: 场景化社交赋能（帮生日组织者创造惊喜）
    # ──────────────────────────────────────────────────────────
    {
        "code": "tmpl_referral_birthday",
        "name": "裂变·生日组织者",
        "template_family": "referral",
        "mechanism_type": "referral_activation",
        "channel": "wecom",
        "tone": "warm",
        "content_template": (
            "{customer_name}，我们注意到您经常为亲朋好友组织生日聚餐。"
            "{brand_name}为生日组织者准备了专属方案：{birthday_package_desc}。"
            "提前告知我们，为您的朋友送上特别的生日惊喜。"
        ),
        "variables_schema_json": [
            {"name": "customer_name", "type": "string", "required": True},
            {"name": "brand_name", "type": "string", "required": True},
            {"name": "birthday_package_desc", "type": "string", "required": True},
        ],
        "forbidden_phrases_json": ["群发", "促销", "限时"],
        "requires_human_review": False,
        "is_system": True,
    },

    # ──────────────────────────────────────────────────────────
    # 18. 裂变·家庭聚餐达人
    # 心理机制: 场景化权益（家庭聚餐场景的专属权益）
    # ──────────────────────────────────────────────────────────
    {
        "code": "tmpl_referral_family",
        "name": "裂变·家庭聚餐达人",
        "template_family": "referral",
        "mechanism_type": "referral_activation",
        "channel": "wecom",
        "tone": "warm",
        "content_template": (
            "{customer_name}，{brand_name}推出了家庭聚餐专享权益：{family_package_desc}。"
            "作为我们的家庭聚餐常客，您和同行家人都可享受。"
            "\u2192 {booking_link}"
        ),
        "variables_schema_json": [
            {"name": "customer_name", "type": "string", "required": True},
            {"name": "brand_name", "type": "string", "required": True},
            {"name": "family_package_desc", "type": "string", "required": True},
            {"name": "booking_link", "type": "string", "required": True},
        ],
        "forbidden_phrases_json": ["群发", "所有人", "不限"],
        "requires_human_review": False,
        "is_system": True,
    },

    # ──────────────────────────────────────────────────────────
    # 19. 裂变·通用推荐
    # 心理机制: 双向激励（推荐人+被推荐人双方得益）
    # 渠道: 小程序（需要分享链接）
    # ──────────────────────────────────────────────────────────
    {
        "code": "tmpl_referral_generic",
        "name": "裂变·通用推荐",
        "template_family": "referral",
        "mechanism_type": "referral_activation",
        "channel": "miniapp",
        "tone": "warm",
        "content_template": (
            "{customer_name}，分享{brand_name}给您的朋友，"
            "双方均可获得专属权益。\u2192 {share_link}"
        ),
        "variables_schema_json": [
            {"name": "customer_name", "type": "string", "required": True},
            {"name": "brand_name", "type": "string", "required": True},
            {"name": "share_link", "type": "string", "required": True},
        ],
        "forbidden_phrases_json": ["群发", "不限", "所有人"],
        "requires_human_review": False,
        "is_system": True,
    },
]
