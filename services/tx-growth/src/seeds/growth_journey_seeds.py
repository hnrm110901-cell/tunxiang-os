"""增长中枢V2 — 系统旅程模板种子数据

P0 三条核心旅程:
1. 首单转二访·Hook化旅程 V2
2. 沉默召回·权益到期型 V2
3. 服务修复·四阶协议 V2
"""
from typing import Any

SYSTEM_JOURNEY_TEMPLATES: list[dict[str, Any]] = [
    # ──────────────────────────────────────────────────────────
    # 旅程1: 首单转二访·Hook化旅程 V2
    # 目的: 通过身份锚定→最小承诺→多样化奖励/损失厌恶的心理机制链，
    #       将首单客户转化为二次回访客户
    # ──────────────────────────────────────────────────────────
    {
        "code": "first_to_second_v2",
        "name": "首单转二访·Hook化旅程 V2",
        "journey_type": "first_to_second",
        "mechanism_family": "hook",
        # 进入条件: 首单完成
        "entry_rule_json": {
            "conditions": [
                {"field": "repurchase_stage", "op": "eq", "value": "first_order_done"}
            ]
        },
        # 退出条件: 已完成二单或进入稳定复购
        "exit_rule_json": {
            "conditions": [
                {"field": "repurchase_stage", "op": "in", "value": ["second_order_done", "stable_repeat"]}
            ]
        },
        # 暂停条件: 正在投诉中 或 用户主动退出增长触达
        "pause_rule_json": {
            "conditions": [
                {"field": "service_repair_status", "op": "eq", "value": "complaint_open"},
                {"field": "growth_opt_out", "op": "eq", "value": True}
            ]
        },
        "priority": 90,
        "is_system": True,
        "steps": [
            {
                # Step1: 首单后立即 — 感谢+入会确认+身份赋予
                # 心理机制: 身份锚定（让客户认同"贵宾"身份）
                "step_no": 1,
                "step_type": "touch",
                "mechanism_type": "identity_anchor",
                "touch_template_code": "tmpl_identity_anchor_welcome",
            },
            {
                # Step2: 等待3天
                # 目的: 给客户消化身份感的时间，不过度打扰
                "step_no": 2,
                "step_type": "wait",
                "wait_minutes": 4320,  # 3天 = 4320分钟
            },
            {
                # Step3: Day3 — 最小承诺引导回访
                # 心理机制: 最小承诺（"7天内回来享专属XXX"，降低行动门槛）
                "step_no": 3,
                "step_type": "touch",
                "mechanism_type": "micro_commitment",
                "touch_template_code": "tmpl_micro_commitment_return",
            },
            {
                # Step4: 等待4天
                # 目的: 观察客户是否打开了Step3的消息
                "step_no": 4,
                "step_type": "wait",
                "wait_minutes": 5760,  # 4天 = 5760分钟
            },
            {
                # Step5: Day7 — 分支决策
                # 判断: 第3步的触达消息是否被打开
                "step_no": 5,
                "step_type": "decision",
                "mechanism_type": None,
                "decision_rule_json": {
                    "check": "touch_opened",
                    "touch_step_no": 3,
                    "true_next": 6,   # 已打开 → 给随机惊喜奖励
                    "false_next": 7,  # 未打开 → 损失厌恶提醒
                },
            },
            {
                # Step6: 已打开消息 → 多样化奖励·随机惊喜
                # 心理机制: 多样化奖励（不确定性奖励比固定奖励更有吸引力）
                "step_no": 6,
                "step_type": "touch",
                "mechanism_type": "variable_reward",
                "touch_template_code": "tmpl_variable_reward_surprise",
                "success_next_step_no": 8,
            },
            {
                # Step7: 未打开消息 → 损失厌恶·权益过期提醒
                # 心理机制: 损失厌恶（"您的XXX即将过期"比"给您XXX"更有效）
                "step_no": 7,
                "step_type": "touch",
                "mechanism_type": "loss_aversion",
                "touch_template_code": "tmpl_loss_aversion_benefit_expiring",
                "success_next_step_no": 8,
            },
            {
                # Step8: 7天观察期
                # 目的: 观察客户是否在观察期内完成二次到店
                "step_no": 8,
                "step_type": "observe",
                "observe_window_hours": 168,  # 7天 = 168小时
            },
            {
                # Step9: 旅程结束
                "step_no": 9,
                "step_type": "exit",
            },
        ],
    },

    # ──────────────────────────────────────────────────────────
    # 旅程2: 沉默召回·权益到期型 V2
    # 目的: 对沉默高/危客户，优先利用已有权益触发损失厌恶，
    #       无已有权益则用轻关系唤醒，避免直接发券
    # ──────────────────────────────────────────────────────────
    {
        "code": "reactivation_loss_aversion_v2",
        "name": "沉默召回·权益到期型 V2",
        "journey_type": "reactivation",
        "mechanism_family": "loss_aversion",
        # 进入条件: 召回优先级为high或critical
        "entry_rule_json": {
            "conditions": [
                {"field": "reactivation_priority", "op": "in", "value": ["high", "critical"]}
            ]
        },
        # 退出条件: 召回优先级降为none（已回访）
        "exit_rule_json": {
            "conditions": [
                {"field": "reactivation_priority", "op": "eq", "value": "none"}
            ]
        },
        # 暂停条件: 正在投诉中
        "pause_rule_json": {
            "conditions": [
                {"field": "service_repair_status", "op": "eq", "value": "complaint_open"}
            ]
        },
        "priority": 80,
        "is_system": True,
        "steps": [
            {
                # Step1: 判断客户是否有未使用的已有权益
                # 目的: 有权益用权益过期提醒，无权益用轻关系唤醒
                "step_no": 1,
                "step_type": "decision",
                "decision_rule_json": {
                    "check": "has_active_owned_benefit",
                    "true_next": 2,   # 有权益 → 损失厌恶
                    "false_next": 3,  # 无权益 → 关系唤醒
                },
            },
            {
                # Step2: 有权益 → 损失厌恶·权益到期提醒
                # 心理机制: 损失厌恶（"您的XXX即将失效"）
                "step_no": 2,
                "step_type": "touch",
                "mechanism_type": "loss_aversion",
                "touch_template_code": "tmpl_loss_aversion_benefit_expiring",
                "success_next_step_no": 4,
            },
            {
                # Step3: 无权益 → 轻关系唤醒
                # 心理机制: 关系唤醒（店长问候+新菜推荐，不涉及促销）
                "step_no": 3,
                "step_type": "touch",
                "mechanism_type": "relationship_warmup",
                "touch_template_code": "tmpl_relationship_warmup",
                "success_next_step_no": 4,
            },
            {
                # Step4: 等待3天
                # 目的: 给客户响应时间
                "step_no": 4,
                "step_type": "wait",
                "wait_minutes": 4320,  # 3天
            },
            {
                # Step5: 判断之前的触达是否被打开
                "step_no": 5,
                "step_type": "decision",
                "decision_rule_json": {
                    "check": "touch_opened",
                    "touch_step_no": 2,  # 检查Step2或Step3（实际运行时引擎按实际执行路径判断）
                    "true_next": 7,   # 已打开 → 直接进入观察期
                    "false_next": 6,  # 未打开 → 最小行动
                },
            },
            {
                # Step6: 未打开 → 最小行动·一键操作
                # 心理机制: 最小行动（降低操作门槛到极致，"一键预订"）
                "step_no": 6,
                "step_type": "touch",
                "mechanism_type": "minimal_action",
                "touch_template_code": "tmpl_minimal_action_simple",
            },
            {
                # Step7: 72小时观察期
                # 目的: 观察客户是否回访
                "step_no": 7,
                "step_type": "observe",
                "observe_window_hours": 72,
            },
            {
                # Step8: 旅程结束
                "step_no": 8,
                "step_type": "exit",
            },
        ],
    },

    # ──────────────────────────────────────────────────────────
    # 旅程3: 服务修复·四阶协议 V2
    # 目的: 投诉关闭后的主动修复，通过四个阶段重建客户信任:
    #       情绪承接 → 控制感补偿 → 补偿确认 → 回访观察
    # 优先级最高（100），且会暂停其他所有增长旅程
    # ──────────────────────────────────────────────────────────
    {
        "code": "service_repair_v2",
        "name": "服务修复·四阶协议 V2",
        "journey_type": "service_repair",
        "mechanism_family": "repair",
        # 进入条件: 投诉已关闭、等待修复
        "entry_rule_json": {
            "conditions": [
                {"field": "service_repair_status", "op": "eq", "value": "complaint_closed_pending_repair"}
            ]
        },
        # 退出条件: 修复完成 或 修复状态清除
        "exit_rule_json": {
            "conditions": [
                {"field": "service_repair_status", "op": "in", "value": ["repair_completed", "none"]}
            ]
        },
        "priority": 100,  # 最高优先级 — 服务修复优于一切增长动作
        "is_system": True,
        "steps": [
            {
                # Step1: 阶段1 — 情绪承接
                # 目的: 第一时间让客户感到被重视，不急于解决问题，先接住情绪
                # 渠道: manual_task（由店长/经理手动发送，确保语气到位）
                "step_no": 1,
                "step_type": "touch",
                "mechanism_type": "service_repair",
                "touch_template_code": "tmpl_repair_ack_empathy",
            },
            {
                # Step2: 等待1小时
                # 目的: 给客户消化情绪的时间，不紧迫逼问
                "step_no": 2,
                "step_type": "wait",
                "wait_minutes": 60,  # 1小时
            },
            {
                # Step3: 阶段2 — 控制感补偿
                # 目的: 给客户选择权（退款/下次全额抵扣/重新制作配送/升级座位）
                # 心理机制: 控制感（让客户选择而非被安排，恢复自主感）
                "step_no": 3,
                "step_type": "offer",
                "mechanism_type": "service_repair",
                "offer_rule_json": {
                    "compensation_type": "choice",
                    "options": ["refund", "full_offset_next_visit", "make_good_delivery", "seat_upgrade"],
                },
            },
            {
                # Step4: 阶段3 — 发送补偿确认
                # 目的: 确认客户选择的补偿方案，让客户安心
                # 渠道: manual_task（人工确认补偿执行）
                "step_no": 4,
                "step_type": "touch",
                "mechanism_type": "service_repair",
                "touch_template_code": "tmpl_repair_compensation",
            },
            {
                # Step5: 阶段4 — 72小时观察期
                # 目的: 观察客户是否在修复后回访
                "step_no": 5,
                "step_type": "observe",
                "observe_window_hours": 72,
            },
            {
                # Step6: 判断是否已回访
                "step_no": 6,
                "step_type": "decision",
                "decision_rule_json": {
                    "check": "has_revisited",
                    "true_next": 7,   # 已回访 → 修复成功，结束
                    "false_next": 8,  # 未回访 → 最后轻触达
                },
            },
            {
                # Step7: 已回访 → 修复成功，旅程结束
                "step_no": 7,
                "step_type": "exit",
            },
            {
                # Step8: 未回访 → 最后轻触达（最小行动）
                # 目的: 最后一次轻量提醒，不施压
                "step_no": 8,
                "step_type": "touch",
                "mechanism_type": "minimal_action",
                "touch_template_code": "tmpl_minimal_action_simple",
            },
            {
                # Step9: 旅程结束（无论是否回访）
                "step_no": 9,
                "step_type": "exit",
            },
        ],
    },
]
