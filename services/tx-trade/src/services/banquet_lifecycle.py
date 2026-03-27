"""宴会全生命周期服务 — V1三文件合并增强

完整链路：线索→需求沟通→方案设计→报价→签约→定金→确认→T-7预备→T-1彩排→执行→结算→回访→案例

13阶段状态机：lead → consultation → proposal → quotation → contract →
deposit_paid → menu_confirmed → preparation → rehearsal → execution →
settlement → feedback → archived

增强点（相比已有 banquet_service.py）：
- 完整13阶段状态机（原来只有5个状态）
- 独立合同管理（合同号、条款、定金比例）
- 报价单管理（利润率计算、折扣审批）
- 筹备检查清单（checklist item级别的状态跟踪）
- 销售漏斗分析

所有金额单位：分（fen）。
"""
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import structlog

from .banquet_service import (
    EVENT_TYPE_CONFIG,
    TIER_PRICING,
    MENU_TEMPLATES,
    VENUE_TEMPLATES,
    BanquetProposal,
    BanquetCostEstimate,
)

logger = structlog.get_logger()


# ─── 内存存储 ───

_leads: dict[str, dict] = {}
_followups: dict[str, list[dict]] = {}  # lead_id -> [followup records]
_proposals: dict[str, dict] = {}
_quotations: dict[str, dict] = {}
_contracts: dict[str, dict] = {}
_checklists: dict[str, list[dict]] = {}  # contract_id -> [checklist items]
_feedbacks: dict[str, dict] = {}
_cases: dict[str, dict] = {}


def _gen_id() -> str:
    return uuid.uuid4().hex[:12].upper()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── 13阶段状态机 ───

BANQUET_STAGES = [
    "lead", "consultation", "proposal", "quotation", "contract",
    "deposit_paid", "menu_confirmed", "preparation", "rehearsal",
    "execution", "settlement", "feedback", "archived",
]

STAGE_LABELS = {
    "lead": "新线索",
    "consultation": "需求沟通",
    "proposal": "方案设计",
    "quotation": "报价确认",
    "contract": "签约",
    "deposit_paid": "定金已付",
    "menu_confirmed": "菜单确认",
    "preparation": "筹备中",
    "rehearsal": "彩排",
    "execution": "执行中",
    "settlement": "结算",
    "feedback": "回访",
    "archived": "已归档",
}

# 允许的阶段转换（包含跳过某些可选阶段）
STAGE_TRANSITIONS: dict[str, list[str]] = {
    "lead": ["consultation", "proposal", "cancelled"],
    "consultation": ["proposal", "cancelled"],
    "proposal": ["quotation", "consultation", "cancelled"],  # 可退回沟通
    "quotation": ["contract", "proposal", "cancelled"],      # 可退回方案
    "contract": ["deposit_paid", "cancelled"],
    "deposit_paid": ["menu_confirmed"],
    "menu_confirmed": ["preparation"],
    "preparation": ["rehearsal", "execution"],  # 小规模可跳过彩排
    "rehearsal": ["execution"],
    "execution": ["settlement"],
    "settlement": ["feedback", "archived"],     # 可跳过回访
    "feedback": ["archived"],
    "archived": [],
    "cancelled": [],
}


def can_stage_transition(current: str, target: str) -> bool:
    return target in STAGE_TRANSITIONS.get(current, [])


# ─── 合同号生成 ───

def _gen_contract_no(store_id: str) -> str:
    """生成合同号：BQ-门店缩写-年月-序号"""
    now = datetime.now(timezone.utc)
    prefix = f"BQ-{store_id[:4].upper()}-{now.strftime('%Y%m')}"
    seq = len([c for c in _contracts.values() if c.get("contract_no", "").startswith(prefix)]) + 1
    return f"{prefix}-{seq:04d}"


class BanquetLifecycleService:
    """宴会全生命周期 — V1三文件合并增强

    完整链路：线索→需求沟通→方案设计→报价→签约→定金→确认→T-7预备→T-1彩排→执行→结算→回访→案例
    """

    def __init__(self, tenant_id: str, store_id: str):
        self.tenant_id = tenant_id
        self.store_id = store_id

    # ═══════════════════════════════════════════════════════
    # 1. Lead Management (销售线索)
    # ═══════════════════════════════════════════════════════

    def create_lead(
        self,
        store_id: str,
        customer_name: str,
        phone: str,
        event_type: str,
        estimated_tables: int,
        estimated_budget_fen: int,
        event_date: str,
        special_requirements: Optional[str] = None,
        referral_source: Optional[str] = None,
    ) -> dict:
        """创建宴会销售线索

        Args:
            store_id: 门店ID
            customer_name: 客户姓名
            phone: 联系电话
            event_type: 宴会类型 wedding/birthday/business/team_building/anniversary
            estimated_tables: 预计桌数
            estimated_budget_fen: 预计总预算（分）
            event_date: 宴会日期 YYYY-MM-DD
            special_requirements: 特殊要求
            referral_source: 来源渠道 walk_in/phone/wechat/meituan/referral/ad

        Returns:
            {lead_id, stage, estimated_per_table_fen, ...}
        """
        if event_type not in EVENT_TYPE_CONFIG:
            raise ValueError(f"Unsupported event_type: {event_type}")
        if estimated_tables <= 0:
            raise ValueError("estimated_tables must be positive")
        if estimated_budget_fen <= 0:
            raise ValueError("estimated_budget_fen must be positive")

        lead_id = f"LEAD-{_gen_id()}"
        now = _now_iso()

        # 计算桌均
        per_table_fen = estimated_budget_fen // estimated_tables
        estimated_guests = estimated_tables * 10  # 标准10人/桌

        lead = {
            "lead_id": lead_id,
            "tenant_id": self.tenant_id,
            "store_id": store_id,
            "customer_name": customer_name,
            "phone": phone,
            "event_type": event_type,
            "event_type_name": EVENT_TYPE_CONFIG[event_type]["name"],
            "estimated_tables": estimated_tables,
            "estimated_guests": estimated_guests,
            "estimated_budget_fen": estimated_budget_fen,
            "estimated_per_table_fen": per_table_fen,
            "event_date": event_date,
            "special_requirements": special_requirements,
            "referral_source": referral_source or "walk_in",
            "stage": "lead",
            "stage_label": STAGE_LABELS["lead"],
            "assigned_sales": None,
            "proposal_id": None,
            "quotation_id": None,
            "contract_id": None,
            "created_at": now,
            "updated_at": now,
            "stage_history": [
                {"stage": "lead", "at": now, "by": "system"},
            ],
        }

        _leads[lead_id] = lead
        _followups[lead_id] = []

        logger.info(
            "banquet_lead_created",
            lead_id=lead_id,
            event_type=event_type,
            tables=estimated_tables,
            budget_fen=estimated_budget_fen,
        )

        return lead

    def update_lead_stage(self, lead_id: str, target_stage: str) -> dict:
        """更新线索阶段

        Args:
            lead_id: 线索ID
            target_stage: 目标阶段

        Returns:
            {lead_id, old_stage, new_stage, ...}
        """
        lead = _leads.get(lead_id)
        if not lead:
            raise ValueError(f"Lead not found: {lead_id}")

        current = lead["stage"]
        if not can_stage_transition(current, target_stage):
            raise ValueError(
                f"Cannot transition lead {lead_id} from '{current}' to '{target_stage}'. "
                f"Allowed: {STAGE_TRANSITIONS.get(current, [])}"
            )

        old_stage = current
        now = _now_iso()
        lead["stage"] = target_stage
        lead["stage_label"] = STAGE_LABELS.get(target_stage, target_stage)
        lead["updated_at"] = now
        lead["stage_history"].append({"stage": target_stage, "at": now, "by": "user"})

        logger.info(
            "banquet_lead_stage_updated",
            lead_id=lead_id,
            old_stage=old_stage,
            new_stage=target_stage,
        )

        return {
            "lead_id": lead_id,
            "old_stage": old_stage,
            "old_stage_label": STAGE_LABELS.get(old_stage, old_stage),
            "new_stage": target_stage,
            "new_stage_label": STAGE_LABELS.get(target_stage, target_stage),
            "updated_at": now,
        }

    def add_followup_record(
        self,
        lead_id: str,
        content: str,
        next_action: str,
        next_date: str,
    ) -> dict:
        """添加跟进记录

        Args:
            lead_id: 线索ID
            content: 跟进内容
            next_action: 下一步动作
            next_date: 下次跟进日期

        Returns:
            {followup_id, lead_id, content, ...}
        """
        lead = _leads.get(lead_id)
        if not lead:
            raise ValueError(f"Lead not found: {lead_id}")

        followup_id = f"FU-{_gen_id()}"
        now = _now_iso()

        record = {
            "followup_id": followup_id,
            "lead_id": lead_id,
            "content": content,
            "next_action": next_action,
            "next_date": next_date,
            "created_at": now,
        }

        _followups[lead_id].append(record)
        lead["updated_at"] = now

        logger.info("banquet_followup_added", lead_id=lead_id, followup_id=followup_id)

        return record

    # ═══════════════════════════════════════════════════════
    # 2. Proposal & Quotation (方案报价)
    # ═══════════════════════════════════════════════════════

    def generate_proposal(self, lead_id: str) -> dict:
        """AI生成宴会方案 — 三档方案（经济/标准/豪华）

        每档包含：菜单 + 场地 + 装饰 + 服务方案 + 成本明细

        Args:
            lead_id: 线索ID

        Returns:
            {proposal_id, tiers: [{tier, menu, venue, decoration, cost_breakdown}], recommended_tier}
        """
        lead = _leads.get(lead_id)
        if not lead:
            raise ValueError(f"Lead not found: {lead_id}")

        event_type = lead["event_type"]
        guest_count = lead["estimated_guests"]
        table_count = lead["estimated_tables"]
        budget_fen = lead["estimated_budget_fen"]
        config = EVENT_TYPE_CONFIG[event_type]

        proposal_id = f"PRP-{_gen_id()}"
        now = _now_iso()

        # 生成三档方案
        tiers = []
        for tier_name in ["economy", "standard", "premium"]:
            tier_price = TIER_PRICING[tier_name].get(event_type, 68800)
            menu_items = MENU_TEMPLATES.get(event_type, {}).get(tier_name, [])

            tier_total = tier_price * guest_count

            # 场地推荐
            if guest_count <= 20:
                venue_key = "vip_room"
            elif guest_count <= 60:
                venue_key = "small_hall"
            elif guest_count <= 150:
                venue_key = "medium_hall"
            else:
                venue_key = "large_hall"
            venue = {**VENUE_TEMPLATES[venue_key], "venue_key": venue_key}

            # 装饰成本
            decoration_cost = 15000 * table_count + 50000  # 150元/桌 + 基础500
            decoration = {
                "theme": config["theme_color"],
                "items": config["decoration_items"],
                "cost_fen": decoration_cost,
            }

            # 服务人力
            waiter_count = max(2, guest_count // 15)
            chef_count = max(2, guest_count // 25)
            labor_cost = waiter_count * 30000 + chef_count * 50000 + 80000
            service_plan = {
                "waiters": waiter_count,
                "chefs": chef_count,
                "coordinator": 1,
                "extras": config.get("service_extras", []),
                "labor_cost_fen": labor_cost,
            }

            # 成本明细
            food_cost = int(tier_total * 0.35)
            beverage_cost = guest_count * 5000
            misc_cost = int(tier_total * 0.05)

            cost_breakdown = {
                "food_cost_fen": food_cost,
                "labor_cost_fen": labor_cost,
                "venue_cost_fen": venue["cost_fen"],
                "decoration_cost_fen": decoration_cost,
                "beverage_cost_fen": beverage_cost,
                "misc_cost_fen": misc_cost,
                "total_cost_fen": food_cost + labor_cost + venue["cost_fen"] + decoration_cost + beverage_cost + misc_cost,
            }

            margin_fen = tier_total - cost_breakdown["total_cost_fen"]
            margin_rate = margin_fen / tier_total if tier_total > 0 else 0

            tiers.append({
                "tier": tier_name,
                "tier_label": {"economy": "经济档", "standard": "标准档", "premium": "豪华档"}[tier_name],
                "price_per_head_fen": tier_price,
                "total_fen": tier_total,
                "menu_items": menu_items,
                "course_count": len(menu_items),
                "venue": venue,
                "decoration": decoration,
                "service_plan": service_plan,
                "cost_breakdown": cost_breakdown,
                "margin_fen": margin_fen,
                "margin_rate": round(margin_rate, 4),
            })

        # 推荐档次：预算匹配
        budget_per_head = budget_fen // guest_count if guest_count > 0 else 0
        recommended = "standard"
        for t in tiers:
            if t["price_per_head_fen"] <= budget_per_head:
                recommended = t["tier"]

        proposal = {
            "proposal_id": proposal_id,
            "lead_id": lead_id,
            "tenant_id": self.tenant_id,
            "store_id": self.store_id,
            "event_type": event_type,
            "guest_count": guest_count,
            "table_count": table_count,
            "tiers": tiers,
            "recommended_tier": recommended,
            "created_at": now,
        }

        _proposals[proposal_id] = proposal

        # 更新线索
        lead["proposal_id"] = proposal_id
        lead["stage"] = "proposal"
        lead["stage_label"] = STAGE_LABELS["proposal"]
        lead["updated_at"] = now
        lead["stage_history"].append({"stage": "proposal", "at": now, "by": "system"})

        logger.info(
            "banquet_proposal_generated",
            lead_id=lead_id,
            proposal_id=proposal_id,
            recommended_tier=recommended,
        )

        return proposal

    def create_quotation(
        self,
        lead_id: str,
        proposal_tier: str,
        adjustments: Optional[list[dict]] = None,
    ) -> dict:
        """创建正式报价单

        Args:
            lead_id: 线索ID
            proposal_tier: 选择的档次 economy/standard/premium
            adjustments: 调整项 [{"item": "加菜:佛跳墙", "amount_fen": 78800}, ...]

        Returns:
            {quotation_id, base_total_fen, adjustments_fen, final_total_fen, margin_rate}
        """
        lead = _leads.get(lead_id)
        if not lead:
            raise ValueError(f"Lead not found: {lead_id}")
        if not lead.get("proposal_id"):
            raise ValueError(f"Lead {lead_id} has no proposal yet")

        proposal = _proposals.get(lead["proposal_id"])
        if not proposal:
            raise ValueError(f"Proposal not found: {lead['proposal_id']}")

        # 找到对应档次
        tier_data = None
        for t in proposal["tiers"]:
            if t["tier"] == proposal_tier:
                tier_data = t
                break
        if not tier_data:
            raise ValueError(f"Tier '{proposal_tier}' not found in proposal")

        adjustments = adjustments or []
        adjustment_total = sum(a.get("amount_fen", 0) for a in adjustments)

        base_total = tier_data["total_fen"]
        final_total = base_total + adjustment_total
        total_cost = tier_data["cost_breakdown"]["total_cost_fen"]
        margin_fen = final_total - total_cost
        margin_rate = margin_fen / final_total if final_total > 0 else 0

        quotation_id = f"QT-{_gen_id()}"
        now = _now_iso()

        quotation = {
            "quotation_id": quotation_id,
            "lead_id": lead_id,
            "proposal_id": lead["proposal_id"],
            "tenant_id": self.tenant_id,
            "store_id": self.store_id,
            "tier": proposal_tier,
            "tier_label": tier_data["tier_label"],
            "guest_count": proposal["guest_count"],
            "table_count": proposal["table_count"],
            "menu_items": tier_data["menu_items"],
            "base_total_fen": base_total,
            "adjustments": adjustments,
            "adjustment_total_fen": adjustment_total,
            "final_total_fen": final_total,
            "cost_breakdown": tier_data["cost_breakdown"],
            "margin_fen": margin_fen,
            "margin_rate": round(margin_rate, 4),
            "valid_until": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
            "created_at": now,
        }

        _quotations[quotation_id] = quotation

        # 更新线索
        lead["quotation_id"] = quotation_id
        lead["stage"] = "quotation"
        lead["stage_label"] = STAGE_LABELS["quotation"]
        lead["updated_at"] = now
        lead["stage_history"].append({"stage": "quotation", "at": now, "by": "user"})

        logger.info(
            "banquet_quotation_created",
            lead_id=lead_id,
            quotation_id=quotation_id,
            final_total_fen=final_total,
            margin_rate=round(margin_rate, 4),
        )

        return quotation

    # ═══════════════════════════════════════════════════════
    # 3. Contract & Deposit (签约定金)
    # ═══════════════════════════════════════════════════════

    def create_contract(
        self,
        lead_id: str,
        quotation_id: str,
        terms: dict,
        deposit_rate: float = 0.3,
    ) -> dict:
        """创建宴会合同

        Args:
            lead_id: 线索ID
            quotation_id: 报价单ID
            terms: 合同条款 {cancellation_policy, min_billing_rate, extra_charge_rules, ...}
            deposit_rate: 定金比例（默认30%）

        Returns:
            {contract_id, contract_no, deposit_required_fen, ...}
        """
        lead = _leads.get(lead_id)
        if not lead:
            raise ValueError(f"Lead not found: {lead_id}")

        quotation = _quotations.get(quotation_id)
        if not quotation:
            raise ValueError(f"Quotation not found: {quotation_id}")

        if not 0.1 <= deposit_rate <= 0.5:
            raise ValueError("deposit_rate must be between 10% and 50%")

        contract_id = f"CT-{_gen_id()}"
        contract_no = _gen_contract_no(lead["store_id"])
        now = _now_iso()

        deposit_required = int(quotation["final_total_fen"] * deposit_rate)

        # 默认合同条款
        default_terms = {
            "cancellation_policy": "宴会前7天取消退还50%定金，3天内取消不退定金",
            "min_billing_rate": 0.8,  # 最低按80%计费
            "extra_charge_rules": "加菜按菜单价，加酒水按零售价",
            "payment_deadline_days": 3,  # 宴后3天内结清尾款
        }
        merged_terms = {**default_terms, **terms}

        contract = {
            "contract_id": contract_id,
            "contract_no": contract_no,
            "lead_id": lead_id,
            "quotation_id": quotation_id,
            "tenant_id": self.tenant_id,
            "store_id": lead["store_id"],
            "customer_name": lead["customer_name"],
            "phone": lead["phone"],
            "event_type": lead["event_type"],
            "event_date": lead["event_date"],
            "guest_count": quotation["guest_count"],
            "table_count": quotation["table_count"],
            "contracted_total_fen": quotation["final_total_fen"],
            "deposit_rate": deposit_rate,
            "deposit_required_fen": deposit_required,
            "deposit_paid_fen": 0,
            "deposit_paid": False,
            "terms": merged_terms,
            "menu_items": quotation["menu_items"],
            "menu_confirmed": False,
            "final_menu_items": None,
            "hall_locked": True,  # 签约锁定场地
            "status": "active",
            "stage": "contract",
            "created_at": now,
            "updated_at": now,
        }

        _contracts[contract_id] = contract

        # 更新线索
        lead["contract_id"] = contract_id
        lead["stage"] = "contract"
        lead["stage_label"] = STAGE_LABELS["contract"]
        lead["updated_at"] = now
        lead["stage_history"].append({"stage": "contract", "at": now, "by": "user"})

        logger.info(
            "banquet_contract_created",
            lead_id=lead_id,
            contract_id=contract_id,
            contract_no=contract_no,
            total_fen=quotation["final_total_fen"],
            deposit_fen=deposit_required,
        )

        return contract

    def collect_deposit(
        self,
        contract_id: str,
        amount_fen: int,
        method: str,
        trade_no: Optional[str] = None,
    ) -> dict:
        """收取定金

        Args:
            contract_id: 合同ID
            amount_fen: 定金金额（分）
            method: 支付方式 wechat/alipay/cash/bank_transfer
            trade_no: 第三方交易号

        Returns:
            {contract_id, paid_fen, remaining_fen, deposit_fulfilled}
        """
        contract = _contracts.get(contract_id)
        if not contract:
            raise ValueError(f"Contract not found: {contract_id}")

        if amount_fen <= 0:
            raise ValueError("amount_fen must be positive")

        contract["deposit_paid_fen"] += amount_fen
        now = _now_iso()

        fulfilled = contract["deposit_paid_fen"] >= contract["deposit_required_fen"]
        if fulfilled:
            contract["deposit_paid"] = True
            contract["stage"] = "deposit_paid"

            # 更新关联线索
            lead = _leads.get(contract["lead_id"])
            if lead:
                lead["stage"] = "deposit_paid"
                lead["stage_label"] = STAGE_LABELS["deposit_paid"]
                lead["updated_at"] = now
                lead["stage_history"].append({"stage": "deposit_paid", "at": now, "by": "system"})

        contract["updated_at"] = now

        remaining = max(0, contract["deposit_required_fen"] - contract["deposit_paid_fen"])

        logger.info(
            "banquet_deposit_collected",
            contract_id=contract_id,
            amount_fen=amount_fen,
            method=method,
            fulfilled=fulfilled,
        )

        return {
            "contract_id": contract_id,
            "contract_no": contract["contract_no"],
            "paid_fen": amount_fen,
            "total_deposit_paid_fen": contract["deposit_paid_fen"],
            "deposit_required_fen": contract["deposit_required_fen"],
            "remaining_fen": remaining,
            "deposit_fulfilled": fulfilled,
            "method": method,
            "trade_no": trade_no,
            "paid_at": now,
        }

    # ═══════════════════════════════════════════════════════
    # 4. Preparation (筹备)
    # ═══════════════════════════════════════════════════════

    def confirm_menu(
        self,
        contract_id: str,
        final_menu_items: list[dict],
    ) -> dict:
        """确认最终菜单

        Args:
            contract_id: 合同ID
            final_menu_items: 最终菜单 [{"name": "...", "price_fen": ..., "quantity": ...}, ...]

        Returns:
            {contract_id, menu_total_fen, course_count, confirmed_at}
        """
        contract = _contracts.get(contract_id)
        if not contract:
            raise ValueError(f"Contract not found: {contract_id}")
        if not contract["deposit_paid"]:
            raise ValueError(f"Contract {contract_id}: deposit not paid yet")

        now = _now_iso()
        menu_total = sum(
            item.get("price_fen", 0) * item.get("quantity", 1)
            for item in final_menu_items
        )

        contract["final_menu_items"] = final_menu_items
        contract["menu_confirmed"] = True
        contract["menu_total_fen"] = menu_total
        contract["stage"] = "menu_confirmed"
        contract["updated_at"] = now

        # 更新线索
        lead = _leads.get(contract["lead_id"])
        if lead:
            lead["stage"] = "menu_confirmed"
            lead["stage_label"] = STAGE_LABELS["menu_confirmed"]
            lead["updated_at"] = now
            lead["stage_history"].append({"stage": "menu_confirmed", "at": now, "by": "user"})

        logger.info(
            "banquet_menu_confirmed",
            contract_id=contract_id,
            course_count=len(final_menu_items),
            menu_total_fen=menu_total,
        )

        return {
            "contract_id": contract_id,
            "contract_no": contract["contract_no"],
            "menu_total_fen": menu_total,
            "course_count": len(final_menu_items),
            "final_menu_items": final_menu_items,
            "confirmed_at": now,
        }

    def generate_prep_checklist(self, contract_id: str) -> list[dict]:
        """生成筹备检查清单 — T-7 到 T+1

        Args:
            contract_id: 合同ID

        Returns:
            [{checklist_item_id, phase, task, responsible, status, required, due_offset_days}]
        """
        contract = _contracts.get(contract_id)
        if not contract:
            raise ValueError(f"Contract not found: {contract_id}")

        event_type = contract["event_type"]
        config = EVENT_TYPE_CONFIG.get(event_type, {})
        guest_count = contract["guest_count"]
        event_date = contract["event_date"]

        items = []
        now = _now_iso()

        # T-7: 筹备启动
        t7_tasks = [
            ("食材预订确认 — 高端食材(龙虾/鲍鱼/帝王蟹)提前锁定供应商", "采购主管", True),
            ("人力排班确认 — 确认服务员/厨师/协调员排班到位", "前厅经理", True),
            ("场地布置方案确认 — 与客户确认最终装饰方案和布局图", "宴会经理", True),
            ("设备检查 — LED屏/音响/灯光/投影设备预约和检测", "工程部", True),
            ("客户确认 — 电话确认最终人数、菜单、特殊需求", "宴会经理", True),
            (f"酒水备货 — 根据{guest_count}人预算准备酒水饮料", "吧台主管", False),
        ]

        # T-3: 物料到位
        t3_tasks = [
            (f"食材到货验收 — 检查{guest_count}位宾客所需食材新鲜度和数量", "采购主管", True),
            ("特殊器材准备 — 装饰物料/鲜花/气球/横幅到位", "宴会经理", True),
            ("餐具清点 — 确认足够的碗碟杯筷（含备用10%）", "前厅领班", True),
            ("菜品试做 — 主要菜品预制准备和试味", "行政总厨", True),
            ("活鲜入池 — 活海鲜入养殖池暂养", "海鲜池管理员",
             event_type in ("wedding", "business", "anniversary")),
        ]

        # T-1: 彩排准备
        t1_tasks = [
            ("场地布置 — 按方案完成桌椅/装饰/灯光/音响布置", "宴会经理", True),
            ("灯光音响测试 — 全流程灯光音响走一遍", "工程部", True),
            ("服务流程彩排 — 全体服务人员走位演练", "前厅经理", True),
            ("菜品预制 — 可提前预制的菜品开始准备", "行政总厨", True),
            ("客户最终确认 — 确认最终到场人数和座位安排", "宴会经理", True),
        ]

        # T-0: 宴会当天
        t0_tasks = [
            ("场地最终检查 — 开场前2小时全面检查", "宴会经理", True),
            ("迎宾准备 — 签到台/引导牌/迎宾花篮就位", "前厅领班", True),
            ("迎宾 — 引导宾客入座、发放伴手礼", "服务团队", True),
            ("开场仪式 — 按流程执行(婚礼仪式/祝寿/致辞等)", "宴会协调员", True),
            ("上菜 — 按顺序上菜：冷盘→热菜→主菜→汤→甜品→水果", "传菜组", True),
            ("祝酒/互动环节 — 协助敬酒、游戏互动", "宴会协调员",
             event_type in ("wedding", "birthday", "team_building")),
            ("甜品/蛋糕环节 — 切蛋糕、甜品台开放", "甜品师",
             event_type in ("wedding", "birthday", "anniversary")),
            ("送客 — 客户致谢、伴手礼分发、合影留念", "宴会经理", True),
            ("现场拆除与清洁 — 宴会结束后30分钟内开始", "保洁组", True),
        ]

        # T+1: 结算复盘
        t1_post_tasks = [
            ("费用结算 — 核对最终费用、收取尾款", "财务", True),
            ("客户回访 — 24小时内电话/微信回访，收集满意度", "宴会经理", True),
            ("案例沉淀 — 整理照片/视频/数据，归档为案例", "宴会经理", False),
            ("团队复盘 — 总结亮点和改进点", "店长", False),
            ("物料盘点 — 清点剩余物料、计算损耗", "采购主管", True),
        ]

        phases = [
            ("T-7", "筹备启动", -7, t7_tasks),
            ("T-3", "物料到位", -3, t3_tasks),
            ("T-1", "彩排准备", -1, t1_tasks),
            ("T-0", "宴会当天", 0, t0_tasks),
            ("T+1", "结算复盘", 1, t1_post_tasks),
        ]

        for phase, phase_name, offset, tasks in phases:
            # 计算到期日
            event_dt = datetime.strptime(event_date, "%Y-%m-%d")
            due_date = (event_dt + timedelta(days=offset)).strftime("%Y-%m-%d")

            for task, responsible, required in tasks:
                item_id = f"CL-{_gen_id()}"
                items.append({
                    "checklist_item_id": item_id,
                    "contract_id": contract_id,
                    "phase": phase,
                    "phase_name": phase_name,
                    "due_offset_days": offset,
                    "due_date": due_date,
                    "task": task,
                    "responsible": responsible,
                    "status": "pending",  # pending/in_progress/completed/skipped
                    "required": required,
                    "notes": None,
                    "completed_at": None,
                    "created_at": now,
                })

        _checklists[contract_id] = items

        # 更新合同和线索阶段
        contract["stage"] = "preparation"
        contract["updated_at"] = now
        lead = _leads.get(contract["lead_id"])
        if lead:
            lead["stage"] = "preparation"
            lead["stage_label"] = STAGE_LABELS["preparation"]
            lead["updated_at"] = now
            lead["stage_history"].append({"stage": "preparation", "at": now, "by": "system"})

        logger.info(
            "banquet_checklist_generated",
            contract_id=contract_id,
            total_items=len(items),
        )

        return items

    def update_checklist_item(
        self,
        checklist_item_id: str,
        status: str,
        notes: Optional[str] = None,
    ) -> dict:
        """更新检查清单项状态

        Args:
            checklist_item_id: 清单项ID
            status: 目标状态 pending/in_progress/completed/skipped
            notes: 备注

        Returns:
            {checklist_item_id, old_status, new_status, ...}
        """
        valid_statuses = ["pending", "in_progress", "completed", "skipped"]
        if status not in valid_statuses:
            raise ValueError(f"Invalid status: {status}. Must be one of {valid_statuses}")

        # 查找 item
        target_item = None
        contract_id = None
        for cid, items in _checklists.items():
            for item in items:
                if item["checklist_item_id"] == checklist_item_id:
                    target_item = item
                    contract_id = cid
                    break
            if target_item:
                break

        if not target_item:
            raise ValueError(f"Checklist item not found: {checklist_item_id}")

        old_status = target_item["status"]
        now = _now_iso()
        target_item["status"] = status
        if notes:
            target_item["notes"] = notes
        if status == "completed":
            target_item["completed_at"] = now

        logger.info(
            "banquet_checklist_item_updated",
            checklist_item_id=checklist_item_id,
            old_status=old_status,
            new_status=status,
        )

        return {
            "checklist_item_id": checklist_item_id,
            "contract_id": contract_id,
            "task": target_item["task"],
            "old_status": old_status,
            "new_status": status,
            "notes": notes,
            "updated_at": now,
        }

    # ═══════════════════════════════════════════════════════
    # 5. Execution Day
    # ═══════════════════════════════════════════════════════

    def start_execution(self, contract_id: str) -> dict:
        """开始执行宴会

        Args:
            contract_id: 合同ID

        Returns:
            {contract_id, stage, started_at, checklist_completion}
        """
        contract = _contracts.get(contract_id)
        if not contract:
            raise ValueError(f"Contract not found: {contract_id}")

        now = _now_iso()

        # 检查必要的检查清单完成度
        checklist = _checklists.get(contract_id, [])
        required_items = [i for i in checklist if i["required"]]
        completed_required = [i for i in required_items if i["status"] == "completed"]
        prep_items = [i for i in required_items if i["phase"] in ("T-7", "T-3", "T-1")]
        completed_prep = [i for i in prep_items if i["status"] == "completed"]

        completion_rate = len(completed_prep) / max(1, len(prep_items))

        contract["stage"] = "execution"
        contract["execution_started_at"] = now
        contract["updated_at"] = now

        # 更新线索
        lead = _leads.get(contract["lead_id"])
        if lead:
            lead["stage"] = "execution"
            lead["stage_label"] = STAGE_LABELS["execution"]
            lead["updated_at"] = now
            lead["stage_history"].append({"stage": "execution", "at": now, "by": "system"})

        logger.info(
            "banquet_execution_started",
            contract_id=contract_id,
            prep_completion_rate=round(completion_rate, 2),
        )

        return {
            "contract_id": contract_id,
            "contract_no": contract["contract_no"],
            "stage": "execution",
            "started_at": now,
            "checklist_completion": {
                "total_required": len(required_items),
                "completed_required": len(completed_required),
                "prep_completion_rate": round(completion_rate, 2),
            },
        }

    # ═══════════════════════════════════════════════════════
    # 6. Settlement (结算)
    # ═══════════════════════════════════════════════════════

    def settle_banquet(
        self,
        contract_id: str,
        actual_tables: int,
        actual_guests: int,
        additional_charges: Optional[list[dict]] = None,
        deductions: Optional[list[dict]] = None,
    ) -> dict:
        """宴会结算

        80%最低计费规则：实际桌数 < 合同桌数80% 时，按80%收费

        Args:
            contract_id: 合同ID
            actual_tables: 实际桌数
            actual_guests: 实际到场人数
            additional_charges: 加项 [{"item": "加菜", "amount_fen": 15800}]
            deductions: 减项 [{"item": "未开酒水", "amount_fen": -5000}]

        Returns:
            {settlement, billing_details, balance_due_fen}
        """
        contract = _contracts.get(contract_id)
        if not contract:
            raise ValueError(f"Contract not found: {contract_id}")

        additional_charges = additional_charges or []
        deductions = deductions or []

        contracted_tables = contract["table_count"]
        contracted_total = contract["contracted_total_fen"]

        # 80%最低计费规则
        min_billing_rate = contract["terms"].get("min_billing_rate", 0.8)
        min_billing_tables = int(contracted_tables * min_billing_rate)
        billing_tables = max(actual_tables, min_billing_tables)

        # 按桌均价计算基础费用
        per_table_fen = contracted_total // contracted_tables if contracted_tables > 0 else 0
        base_total = per_table_fen * billing_tables

        # 加项
        additional_total = sum(c.get("amount_fen", 0) for c in additional_charges)

        # 减项
        deduction_total = abs(sum(d.get("amount_fen", 0) for d in deductions))

        # 最终费用
        final_total = base_total + additional_total - deduction_total
        balance_due = final_total - contract["deposit_paid_fen"]

        now = _now_iso()

        # 是否触发了最低计费
        min_billing_applied = actual_tables < min_billing_tables

        settlement = {
            "contract_id": contract_id,
            "contract_no": contract["contract_no"],
            "event_type": contract["event_type"],
            "event_date": contract["event_date"],
            "contracted_tables": contracted_tables,
            "contracted_total_fen": contracted_total,
            "actual_tables": actual_tables,
            "actual_guests": actual_guests,
            "min_billing_tables": min_billing_tables,
            "billing_tables": billing_tables,
            "min_billing_applied": min_billing_applied,
            "per_table_fen": per_table_fen,
            "base_total_fen": base_total,
            "additional_charges": additional_charges,
            "additional_total_fen": additional_total,
            "deductions": deductions,
            "deduction_total_fen": deduction_total,
            "final_total_fen": final_total,
            "deposit_paid_fen": contract["deposit_paid_fen"],
            "balance_due_fen": balance_due,
            "settled_at": now,
        }

        contract["settlement"] = settlement
        contract["stage"] = "settlement"
        contract["status"] = "settled"
        contract["updated_at"] = now

        # 更新线索
        lead = _leads.get(contract["lead_id"])
        if lead:
            lead["stage"] = "settlement"
            lead["stage_label"] = STAGE_LABELS["settlement"]
            lead["updated_at"] = now
            lead["stage_history"].append({"stage": "settlement", "at": now, "by": "system"})

        logger.info(
            "banquet_settled",
            contract_id=contract_id,
            actual_tables=actual_tables,
            billing_tables=billing_tables,
            min_billing_applied=min_billing_applied,
            final_total_fen=final_total,
            balance_due_fen=balance_due,
        )

        return settlement

    # ═══════════════════════════════════════════════════════
    # 7. Feedback & Archive
    # ═══════════════════════════════════════════════════════

    def collect_feedback(
        self,
        contract_id: str,
        satisfaction_score: int,
        feedback_text: str,
    ) -> dict:
        """收集宴会客户反馈

        Args:
            contract_id: 合同ID
            satisfaction_score: 1-10 满意度评分
            feedback_text: 反馈文本

        Returns:
            {feedback_id, satisfaction_level, ...}
        """
        contract = _contracts.get(contract_id)
        if not contract:
            raise ValueError(f"Contract not found: {contract_id}")

        if not 1 <= satisfaction_score <= 10:
            raise ValueError("satisfaction_score must be between 1 and 10")

        feedback_id = f"FB-{_gen_id()}"
        now = _now_iso()

        satisfaction_level = (
            "excellent" if satisfaction_score >= 9 else
            "good" if satisfaction_score >= 7 else
            "average" if satisfaction_score >= 5 else
            "poor"
        )

        feedback = {
            "feedback_id": feedback_id,
            "contract_id": contract_id,
            "contract_no": contract["contract_no"],
            "customer_name": contract["customer_name"],
            "event_type": contract["event_type"],
            "satisfaction_score": satisfaction_score,
            "satisfaction_level": satisfaction_level,
            "feedback_text": feedback_text,
            "collected_at": now,
        }

        _feedbacks[feedback_id] = feedback

        # 更新合同和线索
        contract["feedback_id"] = feedback_id
        contract["stage"] = "feedback"
        contract["updated_at"] = now

        lead = _leads.get(contract["lead_id"])
        if lead:
            lead["stage"] = "feedback"
            lead["stage_label"] = STAGE_LABELS["feedback"]
            lead["updated_at"] = now
            lead["stage_history"].append({"stage": "feedback", "at": now, "by": "system"})

        logger.info(
            "banquet_feedback_collected",
            contract_id=contract_id,
            score=satisfaction_score,
            level=satisfaction_level,
        )

        return feedback

    def archive_as_case(
        self,
        contract_id: str,
        photos: Optional[list[str]] = None,
        highlights: Optional[list[str]] = None,
    ) -> dict:
        """归档为案例 — 供AI方案推荐参考

        Args:
            contract_id: 合同ID
            photos: 照片URL列表
            highlights: 亮点描述列表

        Returns:
            {case_id, ...}
        """
        contract = _contracts.get(contract_id)
        if not contract:
            raise ValueError(f"Contract not found: {contract_id}")

        photos = photos or []
        highlights = highlights or []

        case_id = f"CASE-{_gen_id()}"
        now = _now_iso()

        feedback = None
        if contract.get("feedback_id"):
            feedback = _feedbacks.get(contract["feedback_id"])

        case = {
            "case_id": case_id,
            "contract_id": contract_id,
            "contract_no": contract["contract_no"],
            "tenant_id": self.tenant_id,
            "store_id": contract["store_id"],
            "customer_name": contract["customer_name"],
            "event_type": contract["event_type"],
            "event_date": contract["event_date"],
            "guest_count": contract["guest_count"],
            "table_count": contract["table_count"],
            "final_total_fen": contract.get("settlement", {}).get("final_total_fen", contract["contracted_total_fen"]),
            "satisfaction_score": feedback["satisfaction_score"] if feedback else None,
            "feedback_text": feedback["feedback_text"] if feedback else None,
            "photos": photos,
            "highlights": highlights,
            "menu_items": contract.get("final_menu_items") or contract.get("menu_items"),
            "archived_at": now,
        }

        _cases[case_id] = case

        # 更新合同和线索
        contract["case_id"] = case_id
        contract["stage"] = "archived"
        contract["updated_at"] = now

        lead = _leads.get(contract["lead_id"])
        if lead:
            lead["stage"] = "archived"
            lead["stage_label"] = STAGE_LABELS["archived"]
            lead["updated_at"] = now
            lead["stage_history"].append({"stage": "archived", "at": now, "by": "system"})

        logger.info(
            "banquet_archived_as_case",
            contract_id=contract_id,
            case_id=case_id,
        )

        return case

    # ═══════════════════════════════════════════════════════
    # 8. Analytics
    # ═══════════════════════════════════════════════════════

    def get_banquet_pipeline(self, store_id: str) -> dict:
        """销售漏斗 — 各阶段线索数量

        Returns:
            {total_leads, funnel: [{stage, count, value_fen}], conversion_rates}
        """
        leads = [
            l for l in _leads.values()
            if l["tenant_id"] == self.tenant_id
            and l["store_id"] == store_id
        ]

        total = len(leads)
        funnel: dict[str, dict] = {}
        for stage in BANQUET_STAGES + ["cancelled"]:
            stage_leads = [l for l in leads if l["stage"] == stage]
            funnel[stage] = {
                "stage": stage,
                "stage_label": STAGE_LABELS.get(stage, stage),
                "count": len(stage_leads),
                "value_fen": sum(l["estimated_budget_fen"] for l in stage_leads),
            }

        # 转化率
        lead_count = funnel.get("lead", {}).get("count", 0)
        proposal_count = sum(
            funnel.get(s, {}).get("count", 0)
            for s in BANQUET_STAGES[BANQUET_STAGES.index("proposal"):]
        )
        contract_count = sum(
            funnel.get(s, {}).get("count", 0)
            for s in BANQUET_STAGES[BANQUET_STAGES.index("contract"):]
        )
        executed_count = sum(
            funnel.get(s, {}).get("count", 0)
            for s in BANQUET_STAGES[BANQUET_STAGES.index("execution"):]
        )

        conversion_rates = {
            "lead_to_proposal": round(proposal_count / max(1, total) * 100, 1),
            "proposal_to_contract": round(contract_count / max(1, proposal_count) * 100, 1),
            "contract_to_executed": round(executed_count / max(1, contract_count) * 100, 1),
            "overall": round(executed_count / max(1, total) * 100, 1),
        }

        return {
            "store_id": store_id,
            "total_leads": total,
            "funnel": list(funnel.values()),
            "conversion_rates": conversion_rates,
        }

    def get_banquet_revenue(
        self,
        store_id: str,
        date_range: tuple[str, str],
    ) -> dict:
        """宴会营收统计

        Args:
            store_id: 门店ID
            date_range: (start_date, end_date)

        Returns:
            {total_revenue_fen, total_contracts, by_event_type, avg_per_table_fen}
        """
        start_date, end_date = date_range

        settled_contracts = [
            c for c in _contracts.values()
            if c["tenant_id"] == self.tenant_id
            and c["store_id"] == store_id
            and c.get("status") == "settled"
            and start_date <= c["event_date"] <= end_date
        ]

        total_revenue = sum(
            c.get("settlement", {}).get("final_total_fen", 0)
            for c in settled_contracts
        )
        total_tables = sum(
            c.get("settlement", {}).get("billing_tables", c["table_count"])
            for c in settled_contracts
        )

        # 按类型分组
        by_type: dict[str, dict] = {}
        for c in settled_contracts:
            et = c["event_type"]
            if et not in by_type:
                by_type[et] = {"event_type": et, "count": 0, "revenue_fen": 0, "tables": 0}
            by_type[et]["count"] += 1
            by_type[et]["revenue_fen"] += c.get("settlement", {}).get("final_total_fen", 0)
            by_type[et]["tables"] += c.get("settlement", {}).get("billing_tables", c["table_count"])

        return {
            "store_id": store_id,
            "date_range": list(date_range),
            "total_contracts": len(settled_contracts),
            "total_revenue_fen": total_revenue,
            "total_tables": total_tables,
            "avg_per_table_fen": total_revenue // max(1, total_tables),
            "by_event_type": list(by_type.values()),
        }
