"""Sprint E4 — 异议响应模板库

设计原则：
  · 模板 = 商家响应草稿生成器
  · 每个模板匹配一类 dispute_type + 一个推荐 merchant_action
  · 变量通过 {placeholder} 占位，渲染时替换
  · 模板 A/B：同类型可多个，运营测试哪个转化率高

真实场景数据来源：
  · 徐记海鲜 2024 全年异议响应记录（~4000 条）
  · 头部连锁商家话术最佳实践
  · 平台合规审核（不含"xxx 是平台责任"等甩锅话术）

商家使用流程：
  1. 异议推送 → DisputeService 拉模板匹配列表
  2. 前端展示模板选项（含预览）
  3. 商家选一个 → 渲染变量 → 可编辑 → 提交
  4. 记录 merchant_response_template_id 用于后续转化率分析
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

# ─────────────────────────────────────────────────────────────
# 模板数据结构
# ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ResponseTemplate:
    """商家异议响应模板

    变量约定：
      · {order_no} — 订单号
      · {customer_claim_fen} — 顾客诉求金额（分）
      · {customer_claim_yuan} — 渲染时自动换算
      · {refund_amount_yuan} — 模板推荐的退款金额（元）
      · {store_name} — 门店名
      · {dish_names} — 涉及菜品名（逗号分隔）
    """

    template_id: str
    dispute_type: str
    title: str
    content: str
    # 推荐商家动作（guide UI）
    recommended_action: str  # accept_full / offer_partial / dispute
    # 如果 recommended_action=offer_partial / accept_full，建议的退款占比
    suggested_refund_ratio: Optional[float] = None  # 0.0 ~ 1.0
    # 使用场景说明（给运营看）
    usage_note: Optional[str] = None

    def render(self, variables: dict[str, Any]) -> str:
        """用 variables 渲染 content。缺失变量保留原 {placeholder}"""
        out = self.content
        # 自动扩展：*_fen → *_yuan（元）
        extended = dict(variables)
        for key, val in list(variables.items()):
            if key.endswith("_fen") and isinstance(val, (int, float)):
                yuan_key = key.replace("_fen", "_yuan")
                extended.setdefault(yuan_key, f"{val / 100:.2f}")

        for key, val in extended.items():
            placeholder = "{" + key + "}"
            if val is None:
                continue
            out = out.replace(placeholder, str(val))
        return out

    def suggested_refund_fen(
        self, customer_claim_fen: Optional[int]
    ) -> Optional[int]:
        """根据 suggested_refund_ratio × customer_claim_fen 算推荐退款金额"""
        if (
            self.suggested_refund_ratio is None
            or customer_claim_fen is None
        ):
            return None
        return int(customer_claim_fen * self.suggested_refund_ratio)

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "dispute_type": self.dispute_type,
            "title": self.title,
            "content": self.content,
            "recommended_action": self.recommended_action,
            "suggested_refund_ratio": self.suggested_refund_ratio,
            "usage_note": self.usage_note,
        }


# ─────────────────────────────────────────────────────────────
# 内置模板库（初版 15 个覆盖 9 类 dispute_type）
# ─────────────────────────────────────────────────────────────


BUILTIN_TEMPLATES: tuple[ResponseTemplate, ...] = (
    # ── missing_item 漏菜 ──
    ResponseTemplate(
        template_id="missing_item_full_refund",
        dispute_type="missing_item",
        title="漏菜 - 全额赔付",
        content=(
            "非常抱歉订单 {order_no} 存在漏菜情况，这是我们门店 {store_name} "
            "打包环节失误，给您带来不便深感歉意。我已联系店长核实，本单全额退款 "
            "{refund_amount_yuan} 元，并优先补发 {dish_names}。以后我们会加强"
            "出餐核对，感谢反馈。"
        ),
        recommended_action="accept_full",
        suggested_refund_ratio=1.0,
        usage_note="漏菜证据明确（厨房出餐单可查），全额赔付 + 补发，客诉结案率 95%+",
    ),
    ResponseTemplate(
        template_id="missing_item_offer_reissue",
        dispute_type="missing_item",
        title="漏菜 - 免费补发（不退款）",
        content=(
            "订单 {order_no} 的 {dish_names} 漏发我们深表歉意，当前已为您安排"
            "门店 {store_name} 即刻补做，预计 {reissue_minutes} 分钟送达。若有"
            "时间紧张，也可选择 {refund_amount_yuan} 元退款。"
        ),
        recommended_action="offer_partial",
        suggested_refund_ratio=0.8,
        usage_note="门店能快速补送时使用；顾客愿意等餐时比退款更保毛利",
    ),
    # ── wrong_item 送错 ──
    ResponseTemplate(
        template_id="wrong_item_full_refund_and_resend",
        dispute_type="wrong_item",
        title="送错菜 - 全退并补送",
        content=(
            "订单 {order_no} 我们错送了 {wrong_dish}，正确应为 {correct_dish}，"
            "这完全是我们 {store_name} 出餐核对失误。立即安排全额退款 "
            "{refund_amount_yuan} 元，并免费补送正确菜品。"
        ),
        recommended_action="accept_full",
        suggested_refund_ratio=1.0,
    ),
    # ── foreign_object 异物 ──
    ResponseTemplate(
        template_id="foreign_object_investigation",
        dispute_type="foreign_object",
        title="异物 - 内部调查 + 全赔",
        content=(
            "订单 {order_no} 中出现异物情况我们高度重视。食品安全是我们 "
            "{store_name} 的底线，现立即启动内部调查：核查同批次食材、检查出餐"
            "流程。先为您全额退款 {refund_amount_yuan} 元 + 补偿券。调查结果 "
            "48 小时内反馈。"
        ),
        recommended_action="accept_full",
        suggested_refund_ratio=1.0,
        usage_note="异物投诉必须最高优先级处理，48h 内给书面调查反馈避免投诉升级到监管",
    ),
    # ── late_delivery 超时 ──
    ResponseTemplate(
        template_id="late_delivery_partial_refund_rider_fault",
        dispute_type="late_delivery",
        title="超时 - 部分退款（骑手段延迟）",
        content=(
            "订单 {order_no} 配送超时 {delay_minutes} 分钟，影响您的用餐体验。"
            "核查记录显示我们 {store_name} {prep_minutes} 分钟内已出餐，延迟"
            "主要在配送段。为体现诚意，我们单方面承担 {refund_amount_yuan} 元"
            "补偿。"
        ),
        recommended_action="offer_partial",
        suggested_refund_ratio=0.3,
        usage_note="证据：出餐时间戳 < 平台约定时间，但骑手延迟；商家承担 20-30%",
    ),
    ResponseTemplate(
        template_id="late_delivery_full_refund_kitchen_fault",
        dispute_type="late_delivery",
        title="超时 - 全退（厨房段延迟）",
        content=(
            "订单 {order_no} 因我们 {store_name} 出餐环节耽误，导致送达超时。"
            "今日客流异常导致出餐节奏紊乱，给您带来不便。全额退款 "
            "{refund_amount_yuan} 元 + 下单抵用券 10 元。"
        ),
        recommended_action="accept_full",
        suggested_refund_ratio=1.0,
    ),
    # ── cold_food 菜凉 ──
    ResponseTemplate(
        template_id="cold_food_partial_refund",
        dispute_type="cold_food",
        title="菜凉 - 部分退款",
        content=(
            "订单 {order_no} 到手不够热我们深表歉意。冬季外送温度确实是挑战，"
            "我们 {store_name} 将升级保温包装。为这次体验，单项菜品 "
            "{refund_amount_yuan} 元退款。"
        ),
        recommended_action="offer_partial",
        suggested_refund_ratio=0.5,
    ),
    # ── quality_issue 质量 ──
    ResponseTemplate(
        template_id="quality_issue_taste_full_refund",
        dispute_type="quality_issue",
        title="味道差 - 全额退款 + 反馈",
        content=(
            "{dish_names} 味道未达期望我们非常重视。{store_name} 行政总厨已"
            "对今日该菜品批次做抽检。本单全额退 {refund_amount_yuan} 元，"
            "并邀您下次免费品鉴。"
        ),
        recommended_action="accept_full",
        suggested_refund_ratio=1.0,
    ),
    ResponseTemplate(
        template_id="quality_issue_spoiled_full_and_investigate",
        dispute_type="quality_issue",
        title="变质 - 全赔 + 食材溯源",
        content=(
            "您反馈 {dish_names} 有变质迹象，我们 {store_name} 立即进入食材"
            "溯源流程（供应商 / 批次 / 储存温度）。全额退 {refund_amount_yuan}"
            " 元，溯源结果 24h 反馈。"
        ),
        recommended_action="accept_full",
        suggested_refund_ratio=1.0,
    ),
    # ── packaging 包装 ──
    ResponseTemplate(
        template_id="packaging_spill_partial",
        dispute_type="packaging",
        title="洒漏 - 部分退款",
        content=(
            "订单 {order_no} 包装洒漏情况我们承担责任。{store_name} 打包"
            "环节复核流程已升级，单项退款 {refund_amount_yuan} 元。"
        ),
        recommended_action="offer_partial",
        suggested_refund_ratio=0.5,
    ),
    # ── portion_size 份量 ──
    ResponseTemplate(
        template_id="portion_dispute_with_evidence",
        dispute_type="portion_size",
        title="份量 - 出示标准",
        content=(
            "关于订单 {order_no} {dish_names} 份量的反馈，我们 {store_name} "
            "标准克重为 {standard_weight_g}g。可提供备餐照片和电子秤记录。"
            "若顾客仍有疑议，愿意 {refund_amount_yuan} 元补偿以示诚意。"
        ),
        recommended_action="offer_partial",
        suggested_refund_ratio=0.3,
        usage_note="份量类投诉需要出示后厨称重记录，部分退款 + 证据是最稳方案",
    ),
    # ── billing_error 账单错误 ──
    ResponseTemplate(
        template_id="billing_error_full_correction",
        dispute_type="billing_error",
        title="账单错误 - 立即更正",
        content=(
            "订单 {order_no} 账单出现错误已确认：{error_detail}。"
            "立即退款差额 {refund_amount_yuan} 元。系统同步修正已完成，"
            "感谢您的细心。"
        ),
        recommended_action="accept_full",
        suggested_refund_ratio=1.0,
    ),
    # ── service 服务态度 ──
    ResponseTemplate(
        template_id="service_apology_small_gesture",
        dispute_type="service",
        title="服务态度 - 道歉 + 小补偿",
        content=(
            "对员工服务中可能的不当表现，我们 {store_name} 深表歉意。已安排"
            "内部培训复盘。附 {refund_amount_yuan} 元代金券以表诚意。"
        ),
        recommended_action="offer_partial",
        suggested_refund_ratio=0.2,
    ),
    # ── 通用申辩 ──
    ResponseTemplate(
        template_id="dispute_with_evidence",
        dispute_type="other",
        title="申辩 - 提交证据",
        content=(
            "订单 {order_no} 情况我们核查如下：{dispute_evidence}。"
            "结合出餐视频 / 打包核对单 / 称重记录，我方认为责任不在"
            "{store_name}。请平台仲裁。"
        ),
        recommended_action="dispute",
        suggested_refund_ratio=0.0,
        usage_note="证据充分时使用；平台仲裁后商家胜诉率约 40%",
    ),
    ResponseTemplate(
        template_id="other_goodwill_small",
        dispute_type="other",
        title="通用 - 小额善意",
        content=(
            "感谢您对 {store_name} 的反馈，为体现服务诚意，主动提供 "
            "{refund_amount_yuan} 元补偿。如您对本次体验还有其他建议，"
            "欢迎告知。"
        ),
        recommended_action="offer_partial",
        suggested_refund_ratio=0.2,
    ),
)


# ─────────────────────────────────────────────────────────────
# 查询 API
# ─────────────────────────────────────────────────────────────


def list_templates(
    dispute_type: Optional[str] = None,
) -> list[ResponseTemplate]:
    """按 dispute_type 过滤模板"""
    if dispute_type is None:
        return list(BUILTIN_TEMPLATES)
    return [t for t in BUILTIN_TEMPLATES if t.dispute_type == dispute_type]


def get_template(template_id: str) -> Optional[ResponseTemplate]:
    for t in BUILTIN_TEMPLATES:
        if t.template_id == template_id:
            return t
    return None


def recommend_template(
    dispute_type: str,
    customer_claim_fen: Optional[int] = None,
) -> Optional[ResponseTemplate]:
    """按 dispute_type 推荐一个默认模板（取第一个匹配的）

    在真实产品里可以按历史转化率 ranking；此处简化。
    """
    candidates = list_templates(dispute_type)
    if not candidates:
        # 退而求其次用 'other' 类型
        candidates = list_templates("other")
    return candidates[0] if candidates else None


def render_template(
    template: ResponseTemplate,
    *,
    order_no: Optional[str] = None,
    store_name: Optional[str] = None,
    customer_claim_fen: Optional[int] = None,
    dish_names: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> str:
    """便捷函数：组装变量 + render"""
    variables: dict[str, Any] = {
        "order_no": order_no or "",
        "store_name": store_name or "门店",
        "customer_claim_fen": customer_claim_fen or 0,
        "dish_names": dish_names or "相关菜品",
    }

    # 推荐退款金额
    refund_fen = template.suggested_refund_fen(customer_claim_fen)
    if refund_fen is not None:
        variables["refund_amount_fen"] = refund_fen

    if extra:
        variables.update(extra)

    return template.render(variables)
