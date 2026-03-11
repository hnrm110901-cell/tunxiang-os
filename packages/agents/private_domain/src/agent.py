"""
私域运营Agent - Private Domain Operations Agent

基于《智链OS私域运营Agent模块设计方案v2.0》实现
核心功能：
1. 信号感知引擎（Signal Radar）- 6类信号监听
2. 三维用户分层（RFM × 门店象限 × 动态标签）
3. 门店潜力四象限模型（本地化SPA）
4. 智能旅程引擎（Journey Automation）
5. 舆情监控（Reputation Guard）
6. 私域运营看板
"""

import os
import asyncio
import structlog
from datetime import datetime, timedelta, date
from enum import Enum
from typing import TypedDict, List, Optional, Dict, Any, Tuple
from statistics import mean
from collections import defaultdict
import sys
from pathlib import Path

# Add core module to path
core_path = Path(__file__).parent.parent.parent.parent.parent / "src" / "core"
sys.path.insert(0, str(core_path))

from base_agent import BaseAgent, AgentResponse
from growth_handlers import run_growth_action, GROWTH_ACTIONS

logger = structlog.get_logger()


# ─────────────────────────── Enums ───────────────────────────

class RFMLevel(str, Enum):
    S1 = "S1"  # 高价值
    S2 = "S2"  # 潜力
    S3 = "S3"  # 沉睡
    S4 = "S4"  # 流失预警
    S5 = "S5"  # 流失


class StoreQuadrant(str, Enum):
    BENCHMARK = "benchmark"    # 标杆：高渗透+低竞争
    DEFENSIVE = "defensive"    # 防守：高渗透+高竞争
    POTENTIAL = "potential"    # 潜力：低渗透+低竞争
    BREAKTHROUGH = "breakthrough"  # 突围：低渗透+高竞争


class SignalType(str, Enum):
    CONSUMPTION = "consumption"    # 消费信号
    CHURN_RISK = "churn_risk"      # 流失预警
    BAD_REVIEW = "bad_review"      # 差评信号
    HOLIDAY = "holiday"            # 节气/节日
    COMPETITOR = "competitor"      # 竞品动态
    VIRAL = "viral"                # 裂变触发


class JourneyType(str, Enum):
    NEW_CUSTOMER = "new_customer"      # 新客激活（7天4触点）
    VIP_RETENTION = "vip_retention"    # VIP保鲜
    REACTIVATION = "reactivation"      # 沉睡唤醒
    REVIEW_REPAIR = "review_repair"    # 差评修复


class JourneyStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    AGENT_EXIT = "agent_exit"   # 三触无响应，停止自动化，转人工


# ── 沉睡唤醒旅程步骤定义 ────────────────────────────────────────────────────────
# 理论来源：《思考，快与慢》损失厌恶 + 《助推》框架效应 + 《怪诞行为学》所有权效应

REACTIVATION_STEPS = [
    {
        "step": 1,
        "timing_days": 3,               # 沉睡信号触发后第3天
        "framework": "ownership_effect",
        "label": "所有权效应（您已经拥有）",
        "message_principle": (
            "强调顾客「已拥有」的权益将失效，而非发放新优惠。"
            "禁止使用「想念您」「优惠来啦」等主动营销语气。"
        ),
        "template": (
            "【权益到期提醒】您的{store_name}会员专属特权"
            "「{benefit_name}」将于{expire_days}天后自动清空，"
            "您上次使用是在{last_visit_date}"
        ),
        "psychology": "所有权效应激活，损失厌恶 2× 收益渴望",
        "expected_open_rate_lift": "40%",
    },
    {
        "step": 2,
        "timing_days": 10,              # 第1步发出后7天无响应
        "framework": "social_proof",
        "label": "社会证明 + 具体场景",
        "message_principle": (
            "用可量化的社会证明降低心理距离。"
            "禁止「再给您一个机会」「最后一次」等施压语气。"
        ),
        "template": (
            "您认识的{store_name}老顾客，最近都在推荐「{new_dish}」。"
            "上次{cohort_size}位顾客和您同一天加入，其中{adoption_pct}%已经来体验过了"
        ),
        "psychology": "《乌合之众》从众心理 + 具体场景降低心理距离",
        "expected_open_rate_lift": "25%",
    },
    {
        "step": 3,
        "timing_days": 24,              # 第2步发出后14天无响应
        "framework": "minimum_action",
        "label": "极低门槛的最小行动",
        "message_principle": (
            "不是让他来，是让他说一个字。禁止大额折扣（破坏价格锚点）。"
        ),
        "template": (
            "只需回复「好」，我们帮您保留下周{preferred_slot}的位置"
        ),
        "psychology": "《助推》默认选项——极低行动成本触发系统一决策",
        "no_response_action": "agent_exit",  # 无响应则停止所有自动触达
        "expected_open_rate_lift": "15%",
    },
]

# 旅程步骤间隔天数（REACTIVATION 专用）
_REACTIVATION_STEP_DELAYS = {1: 3, 2: 10, 3: 24}


# ─────────────────────────── TypedDicts ───────────────────────────

class UserSegment(TypedDict):
    customer_id: str
    rfm_level: str          # S1-S5
    store_quadrant: str     # benchmark/defensive/potential/breakthrough
    dynamic_tags: List[str] # 动态标签
    recency_days: int       # 最近消费距今天数
    frequency: int          # 消费频次（近30天）
    monetary: int           # 消费金额（近30天，分）
    last_visit: str
    risk_score: float       # 流失风险分 0-1


class SignalEvent(TypedDict):
    signal_id: str
    signal_type: str
    customer_id: Optional[str]
    store_id: str
    description: str
    severity: str           # low/medium/high/critical
    triggered_at: str
    action_taken: Optional[str]


class JourneyRecord(TypedDict, total=False):
    journey_id: str
    journey_type: str
    customer_id: str
    store_id: str
    status: str
    current_step: int
    total_steps: int
    started_at: str
    next_action_at: Optional[str]
    completed_at: Optional[str]
    step_actions: Optional[list]   # Hook步骤详情（NEW_CUSTOMER旅程）


class StoreQuadrantData(TypedDict):
    store_id: str
    store_name: str
    quadrant: str
    competition_density: float   # 竞争密度（周边1km同品类数）
    member_penetration: float    # 会员渗透率 0-1
    untapped_potential: int      # 待渗透空间（人数）
    strategy: str                # 推荐策略


class PrivateDomainDashboard(TypedDict):
    store_id: str
    total_members: int
    active_members: int          # 近30天有消费
    rfm_distribution: Dict[str, int]  # S1-S5各层人数
    pending_signals: int
    running_journeys: int
    monthly_repurchase_rate: float
    churn_risk_count: int        # 流失预警人数
    bad_review_count: int        # 近7天差评数
    store_quadrant: str
    roi_estimate: float


# ── Hook化新客激活旅程步骤（B2·方向二）────────────────────────────────────────
# 理论来源：《上瘾》Hook模型 + 《助推》默认选项 + 《影响力》承诺一致性
# 核心洞见：习惯养成需要 触发→行动→多变奖励→投入 四步循环，当前旅程缺少"投入"环节。

NEW_CUSTOMER_JOURNEY_STEPS = [
    {
        "step": 1,
        "timing": "消费后2小时内",
        "mechanism": "触发层：即时身份确认",
        "channel": "wechat",
        "action": "welcome_identity_anchor",
        "message_principle": (
            "欢迎加入！您今天的[具体菜品]选择很有品味，"
            "我们把您标注为「会品菜的老饕」。"
            "请问您下次来通常是几人用餐？(2人/3-4人/6人以上)"
        ),
        "psychology": "身份标签（承诺一致性锚点）+ 问小问题（投入感）",
    },
    {
        "step": 2,
        "timing": "Day 2 午餐前1小时",
        "mechanism": "行动层：最小可行行动",
        "channel": "wechat_card",
        "action": "micro_commitment_card",
        "message_principle": (
            "基于Step1答案：「您好像喜欢X人聚餐，本周五有一桌靠窗的位置，"
            "是否帮您预留？（只需回复'预留'两个字）」"
        ),
        "psychology": "默认选项 + 极低行动成本 + 稀缺性",
    },
    {
        "step": 3,
        "timing": "Day 5（个性化时间窗口）",
        "mechanism": "多变奖励：不可预测的惊喜",
        "channel": "wechat_template",
        "action": "variable_reward_dispatch",
        "message_principle": (
            "从3种奖励中随机选1种：A) 专属菜品提前尝鲜资格（稀缺性）"
            "B) 厨师长亲笔推荐的今日时令菜  C) 积分翻倍日通知"
        ),
        "psychology": "变比率强化（老虎机效应），比固定奖励更强",
    },
    {
        "step": 4,
        "timing": "Day 7",
        "mechanism": "投入层：参与感沉淀",
        "channel": "wechat",
        "action": "investment_deepening",
        "message_principle": (
            "「您上次提到喜欢XX口味，我们的厨师团队为您收录了这个偏好。"
            "下次来可以直接说'按我的口味来'，我们会记得。」"
        ),
        "psychology": "让用户意识到自己已经「投入」了信息，离开有成本",
    },
]

# ── 差评修复协议 ────────────────────────────────────────────────────────────────
# 理论来源：《影响力》互惠原则 + 《乌合之众》群体心理 + 《消费者行为学》认知失调
# 核心洞见：差评的本质是认知失调，补偿目标不是"买回评分"，
#           而是帮助顾客重建正确的自我叙事。

BAD_REVIEW_REPAIR_PROTOCOL = {
    "rating_1": {
        "severity": "critical",
        "response_window_minutes": 15,    # 必须15分钟内响应（在群体情绪形成前）
        "steps": [
            {
                "step": 1,
                "timing": "0-15min",
                "channel": "store_manager_personal_wechat",
                "principle": "不解释，不辩解，只承认情感",
                "message_principle": (
                    "情绪先行：「您今天的体验让我很难过，这不是我们应有的标准」"
                ),
                "psychology": "《消费者行为学》：先处理情绪再处理问题",
            },
            {
                "step": 2,
                "timing": "15-60min",
                "channel": "wechat",
                "principle": "主动超预期补偿（不等顾客索取）",
                "message_principle": (
                    "提供3选1给顾客控制感：A) 退款  B) 下次全额抵扣  C) 今晚外送补救菜品"
                ),
                "psychology": "控制感本身就是修复认知失调的方式",
            },
            {
                "step": 3,
                "timing": "48h后",
                "channel": "wechat",
                "principle": "用新场景覆盖负面记忆（完全不提上次差评）",
                "message_principle": (
                    "「{name}，上次您提到喜欢{favorite_dish}，"
                    "我们本周新到了一批，想请您来试试」"
                ),
                "psychology": "用正面情境覆盖负面记忆，行为改变认知",
            },
            {
                "step": 4,
                "timing": "顾客回店时",
                "channel": "edge_hub_shokz",
                "principle": "到店时触发服务员给予超预期现场体验",
                "message_principle": (
                    "Edge Hub → 服务员耳机：「桌位XXX是上次有差评的顾客，"
                    "今日全程关注，主动询问并做记录」"
                ),
                "psychology": "顾客来了就会重新评价那次差评（行为改变认知）",
            },
        ],
    },
    "rating_2_3": {
        "severity": "warning",
        "response_window_minutes": 30,
        "steps": [
            {
                "step": 1,
                "timing": "0-30min",
                "channel": "wechat_template",
                "principle": "模板消息+真实具名（激活公平感而非报复感）",
                "message_principle": (
                    "具体承认问题（「您提到的等待时间确实超过了我们标准」），"
                    "来自具名服务经理（不是系统）"
                ),
                "psychology": "具体>抽象，具名>系统",
            },
            {
                "step": 2,
                "timing": "1-4h",
                "channel": "wechat",
                "principle": "意外个性化互惠（从历史数据提取最爱菜品）",
                "message_principle": (
                    "不是50元券，是「特别为您准备了您上次点的{favorite_dish}免费一份」"
                ),
                "psychology": "《影响力》互惠：意外性+个性化 >> 通用折扣",
            },
        ],
    },
}


def _infer_compensation_type(customer_history: Optional[Dict[str, Any]]) -> str:
    """
    从顾客历史数据推断最合适的个性化补偿类型。
    返回：dish_voucher（最爱菜品）/ credit（消费抵扣）/ refund（退款）
    """
    if not customer_history:
        return "credit"
    favorite = customer_history.get("favorite_dish")
    if favorite:
        return "dish_voucher"
    monetary = customer_history.get("monetary", 0)
    if monetary >= 5000:  # 高消费顾客更在意体验而非钱
        return "dish_voucher"
    return "credit"


# ── 竞品防御剧本（B4·方向九）────────────────────────────────────────────────────
# 理论来源：《定位》里斯/特劳特 + 《黑客增长》留存护城河
# 核心洞见：防守≠折扣战；正确应对是强化「被记录的个性化」和「社交网络」两大护城河

COMPETITOR_DEFENSE_PLAYBOOK: Dict[str, Any] = {
    "竞品新开业": {
        "wrong_action": "立即发高折扣（价格战，双输）",
        "right_actions": [
            {
                "target": "近30天消费过的所有顾客",
                "timing": "7天内",
                "message_principle": (
                    "「感谢您{X}年来的陪伴，您在{门店名}的{菜品偏好}记录，"
                    "是我们每次出菜前都会参考的标准」"
                ),
                "psychology": "强化「被记录的个性化」护城河——新竞品无法复制",
            },
            {
                "target": "S1/S2 高价值用户",
                "timing": "3天内",
                "message_principle": (
                    "「您认识的{门店名}朋友们都在期待本月新品，"
                    "作为老朋友，您是第一批可以预约试菜的」"
                ),
                "psychology": "强化「社交网络」护城河——你的朋友也在这里",
            },
        ],
        "forbidden": "不要主动提及竞争对手（《定位》：提及竞品等于帮对方打广告）",
    },
    "竞品评分上升": {
        "wrong_action": "跟风模仿竞品活动",
        "right_actions": [
            {
                "target": "近60天未消费的S3/S4用户",
                "timing": "立即",
                "message_principle": (
                    "「{上次消费的具体菜品}本周出了新做法，"
                    "只有老顾客才知道这个消息」"
                ),
                "psychology": "用具体记忆重建心理距离，降低对新竞品的好奇心",
            },
        ],
        "forbidden": "不要用「我们比XX更好」的比较语气",
    },
}


# ─────────────────────────── Agent ───────────────────────────

class PrivateDomainAgent(BaseAgent):
    """
    私域运营Agent

    负责餐饮连锁门店的私域用户运营，实现「防损防跑单」核心价值：
    - 防跑单：实时监控高价值用户流失信号，提前14天预警并自动挽回
    - 防损耗：差评48小时内自动处理，避免口碑坏损扩大化
    - 防竞品：门店象限监测，竞品新开店自动触发防守策略
    - 增营收：精准旅程拉动复购和客单价提升
    """

    def __init__(self, store_id: str, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.store_id = store_id
        self.logger = logger.bind(agent="private_domain", store_id=store_id)
        self._db_engine = None

        # 配置参数
        self.churn_threshold_days = int(os.getenv("PD_CHURN_THRESHOLD_DAYS", "14"))
        self.s1_min_frequency = int(os.getenv("PD_S1_MIN_FREQUENCY", "2"))
        self.s1_min_monetary = int(os.getenv("PD_S1_MIN_MONETARY", "10000"))  # 分
        self.penetration_threshold = float(os.getenv("PD_PENETRATION_THRESHOLD", "0.3"))
        self.competition_threshold = int(os.getenv("PD_COMPETITION_THRESHOLD", "5"))
        self.bad_review_threshold = int(os.getenv("PD_BAD_REVIEW_THRESHOLD", "3"))

    def _get_db_engine(self):
        """获取数据库引擎（延迟初始化）"""
        if self._db_engine is None:
            db_url = os.getenv("DATABASE_URL")
            if db_url:
                try:
                    from sqlalchemy import create_engine
                    self._db_engine = create_engine(db_url, pool_pre_ping=True)
                except Exception as e:
                    self.logger.warning("db_engine_init_failed", error=str(e))
        return self._db_engine

    def _fetch_journeys_from_db(self, status: Optional[str] = None) -> List[JourneyRecord]:
        """从数据库查询旅程列表；无 DB 时返回空列表"""
        engine = self._get_db_engine()
        if not engine:
            return []
        try:
            from sqlalchemy import text
            sql = """
                SELECT journey_id, journey_type, customer_id, store_id,
                       status, current_step, total_steps,
                       started_at, next_action_at, completed_at
                FROM private_domain_journeys
                WHERE store_id = :store_id
            """
            params: Dict[str, Any] = {"store_id": self.store_id}
            if status:
                sql += " AND status = :status"
                params["status"] = status
            sql += " ORDER BY started_at DESC LIMIT 100"
            with engine.connect() as conn:
                rows = conn.execute(text(sql), params).fetchall()
            return [
                JourneyRecord(
                    journey_id=row.journey_id,
                    journey_type=row.journey_type,
                    customer_id=row.customer_id,
                    store_id=row.store_id,
                    status=row.status,
                    current_step=row.current_step,
                    total_steps=row.total_steps,
                    started_at=row.started_at.isoformat() if row.started_at else None,
                    next_action_at=row.next_action_at.isoformat() if row.next_action_at else None,
                    completed_at=row.completed_at.isoformat() if row.completed_at else None,
                )
                for row in rows
            ]
        except Exception as e:
            self.logger.warning("fetch_journeys_from_db_failed", error=str(e))
            return []

    def _persist_journey_to_db(self, journey: JourneyRecord) -> None:
        """将旅程记录写入数据库；无 DB 或写入失败时静默跳过"""
        engine = self._get_db_engine()
        if not engine:
            return
        try:
            import uuid as uuid_mod
            from sqlalchemy import text
            from datetime import datetime as dt

            def _parse_dt(v: Optional[str]) -> Optional[dt]:
                return dt.fromisoformat(v) if v else None

            with engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO private_domain_journeys
                            (id, journey_id, store_id, customer_id, journey_type,
                             status, current_step, total_steps,
                             started_at, next_action_at, completed_at,
                             step_history, created_at, updated_at)
                        VALUES
                            (:id, :journey_id, :store_id, :customer_id, :journey_type,
                             :status, :current_step, :total_steps,
                             :started_at, :next_action_at, :completed_at,
                             '[]'::json, NOW(), NOW())
                        ON CONFLICT (journey_id) DO NOTHING
                    """),
                    {
                        "id": str(uuid_mod.uuid4()),
                        "journey_id": journey["journey_id"],
                        "store_id": journey["store_id"],
                        "customer_id": journey["customer_id"],
                        "journey_type": journey["journey_type"],
                        "status": journey["status"],
                        "current_step": journey["current_step"],
                        "total_steps": journey["total_steps"],
                        "started_at": _parse_dt(journey.get("started_at")),
                        "next_action_at": _parse_dt(journey.get("next_action_at")),
                        "completed_at": _parse_dt(journey.get("completed_at")),
                    },
                )
        except Exception as e:
            self.logger.warning("persist_journey_to_db_failed", error=str(e))

    def get_supported_actions(self) -> List[str]:
        return [
            "get_dashboard",
            "analyze_rfm",
            "detect_signals",
            "calculate_store_quadrant",
            "trigger_journey",
            "get_journeys",
            "get_signals",
            "segment_users",
            "get_churn_risks",
            "process_bad_review",
        ] + list(GROWTH_ACTIONS)

    async def execute(self, action: str, params: Dict[str, Any]) -> AgentResponse:
        self.logger.info("executing_action", action=action, params=params)
        try:
            # 用户增长侧 18 个 action（与 chain-restaurant-user-growth Skill 对齐）
            if action in GROWTH_ACTIONS:
                result = await run_growth_action(action, params, self.store_id)
                if result.get("error"):
                    return AgentResponse(
                        success=False,
                        data=result,
                        error=result.get("error"),
                        execution_time=0.0,
                        metadata=None,
                    )
                return AgentResponse(
                    success=True,
                    data=result,
                    error=None,
                    execution_time=0.0,
                    metadata=None,
                )
            if action == "get_dashboard":
                result = await self.get_dashboard()
            elif action == "analyze_rfm":
                result = await self.analyze_rfm(params.get("days", 30))
            elif action == "detect_signals":
                result = await self.detect_signals()
            elif action == "calculate_store_quadrant":
                result = await self.calculate_store_quadrant(
                    params.get("competition_density", 0),
                    params.get("member_count", 0),
                    params.get("estimated_population", 1000),
                )
            elif action == "trigger_journey":
                result = await self.trigger_journey(
                    params["journey_type"],
                    params["customer_id"],
                )
            elif action == "get_journeys":
                result = await self.get_journeys(params.get("status"))
            elif action == "get_signals":
                result = await self.get_signals(params.get("signal_type"), params.get("limit", 50))
            elif action == "segment_users":
                result = await self.segment_users(params.get("days", 30))
            elif action == "get_churn_risks":
                result = await self.get_churn_risks()
            elif action == "process_bad_review":
                result = await self.process_bad_review(
                    params["review_id"],
                    params.get("customer_id"),
                    params.get("rating", 2),
                    params.get("content", ""),
                )
            else:
                return AgentResponse(
                    success=False,
                    data=None,
                    error=f"Unsupported action: {action}",
                    execution_time=0.0,
                    metadata=None,
                )
            return AgentResponse(success=True, data=result, error=None, execution_time=0.0, metadata=None)
        except Exception as e:
            self.logger.error("action_failed", action=action, error=str(e))
            return AgentResponse(success=False, data=None, error=str(e), execution_time=0.0, metadata=None)

    # ─────────────────────────── Core Methods ───────────────────────────

    async def get_dashboard(self) -> PrivateDomainDashboard:
        """获取私域运营看板数据"""
        self.logger.info("getting_dashboard")
        rfm_data = await self.analyze_rfm(30)
        signals = await self.get_signals(limit=100)
        journeys = await self.get_journeys(status="running")
        churn_risks = await self.get_churn_risks()

        rfm_dist = defaultdict(int)
        total_members = len(rfm_data)
        active_members = 0
        for u in rfm_data:
            rfm_dist[u["rfm_level"]] += 1
            if u["recency_days"] <= 30:
                active_members += 1

        repurchase_rate = active_members / total_members if total_members > 0 else 0.0
        bad_reviews = [s for s in signals if s["signal_type"] == SignalType.BAD_REVIEW]

        # 估算ROI（基于文档公式）
        s1_count = rfm_dist.get("S1", 0)
        roi_estimate = round(s1_count * 0.12 * 200 / 3980, 2)  # 简化估算

        quadrant_data = await self.calculate_store_quadrant(
            competition_density=4.0,
            member_count=total_members,
            estimated_population=max(total_members * 3, 1000),
        )

        return PrivateDomainDashboard(
            store_id=self.store_id,
            total_members=total_members,
            active_members=active_members,
            rfm_distribution=dict(rfm_dist),
            pending_signals=len([s for s in signals if not s.get("action_taken")]),
            running_journeys=len(journeys),
            monthly_repurchase_rate=round(repurchase_rate, 3),
            churn_risk_count=len(churn_risks),
            bad_review_count=len(bad_reviews),
            store_quadrant=quadrant_data["quadrant"],
            roi_estimate=roi_estimate,
        )

    async def analyze_rfm(self, days: int = 30) -> List[UserSegment]:
        """
        RFM三维分层分析
        S1: 高价值（近30天消费≥2次 且 金额≥100元）
        S2: 潜力（近30天消费1-2次）
        S3: 沉睡（31-60天无消费）
        S4: 流失预警（61-90天无消费）
        S5: 流失（>90天无消费）
        """
        self.logger.info("analyzing_rfm", days=days)
        customers = await self._fetch_customers_from_db(days)
        if not customers:
            self.logger.info("analyze_rfm_no_data", store_id=self.store_id)
            return []
        segments = []
        for c in customers:
            rfm_level = self._classify_rfm(c["recency_days"], c["frequency"], c["monetary"])
            risk_score = self._calculate_churn_risk(c["recency_days"], c["frequency"])
            dynamic_tags = self._infer_dynamic_tags(c)
            segments.append(UserSegment(
                customer_id=c["customer_id"],
                rfm_level=rfm_level,
                store_quadrant=StoreQuadrant.POTENTIAL.value,
                dynamic_tags=dynamic_tags,
                recency_days=c["recency_days"],
                frequency=c["frequency"],
                monetary=c["monetary"],
                last_visit=c["last_visit"],
                risk_score=risk_score,
            ))
        return segments

    async def _fetch_customers_from_db(self, days: int) -> List[Dict[str, Any]]:
        """从 orders 表聚合 RFM 数据，无 DB 时返回空列表"""
        engine = self._get_db_engine()
        if not engine:
            return []
        try:
            from sqlalchemy import text
            # 注意：INTERVAL 不支持直接绑定参数，需用乘法形式传入天数
            query = text("""
                SELECT
                    customer_id,
                    EXTRACT(DAY FROM NOW() - MAX(created_at))::int AS recency_days,
                    COUNT(*)::int AS frequency,
                    COALESCE(SUM(total_amount), 0)::int AS monetary,
                    MAX(created_at)::date::text AS last_visit,
                    EXTRACT(HOUR FROM AVG(created_at::time))::int AS avg_order_hour
                FROM orders
                WHERE store_id = :store_id
                  AND created_at >= NOW() - (:lookback_days * INTERVAL '1 day')
                  AND customer_id IS NOT NULL
                GROUP BY customer_id
            """)
            lookback = days * 3
            with engine.connect() as conn:
                rows = conn.execute(query, {"store_id": self.store_id, "lookback_days": lookback}).fetchall()
            customers = []
            for row in rows:
                customers.append({
                    "customer_id": str(row[0]),
                    "recency_days": int(row[1]) if row[1] is not None else 999,
                    "frequency": int(row[2]),
                    "monetary": int(row[3]),
                    "last_visit": str(row[4]) if row[4] else datetime.utcnow().strftime("%Y-%m-%d"),
                    "avg_order_time": int(row[5]) if row[5] is not None else 12,
                })
            self.logger.info("rfm_db_fetch_success", count=len(customers))
            return customers
        except Exception as e:
            self.logger.warning("rfm_db_fetch_failed", error=str(e))
            return []

    async def detect_signals(self) -> List[SignalEvent]:
        """检测6类信号"""
        self.logger.info("detecting_signals")
        signals = []
        now = datetime.utcnow().isoformat()

        # 从 DB 查询活跃及近期沉睡客户（lookback = churn_threshold_days × 3）
        lookback_days = max(30, self.churn_threshold_days)
        customers = await self._fetch_customers_from_db(lookback_days)
        if not customers:
            self.logger.info("detect_signals_no_data", store_id=self.store_id)
            return []
        for c in customers:
            # 流失预警信号
            if c["recency_days"] >= self.churn_threshold_days:
                signals.append(SignalEvent(
                    signal_id=f"SIG_CHURN_{c['customer_id']}_{date.today().isoformat()}",
                    signal_type=SignalType.CHURN_RISK.value,
                    customer_id=c["customer_id"],
                    store_id=self.store_id,
                    description=f"高价值用户 {c['customer_id']} 已 {c['recency_days']} 天未消费",
                    severity="high" if c["recency_days"] >= 30 else "medium",
                    triggered_at=now,
                    action_taken=None,
                ))
            # 高消费信号
            if c["monetary"] >= self.s1_min_monetary * 1.5:
                signals.append(SignalEvent(
                    signal_id=f"SIG_CONS_{c['customer_id']}_{date.today().isoformat()}",
                    signal_type=SignalType.CONSUMPTION.value,
                    customer_id=c["customer_id"],
                    store_id=self.store_id,
                    description=f"用户 {c['customer_id']} 本月消费 ¥{c['monetary']//100}，超均值1.5倍",
                    severity="low",
                    triggered_at=now,
                    action_taken=None,
                ))
        return signals[:20]  # 返回最新20条

    async def detect_competitor_signals(
        self,
        revenue_drop_pct: float = 0.0,
        drop_days: int = 7,
        is_holiday: bool = False,
    ) -> List[SignalEvent]:
        """
        竞品信号检测（B4·方向九）。

        采用「代理检测」策略：用自身数据反推竞品存在。
        当门店近期营收/频次突然下降且非节假日，推断周边可能有竞品开业。

        实际生产中可额外接入：
          - 大众点评 API（新店开业/评分变化）
          - 美团后台数据（周边同品类订单分流）

        Args:
            revenue_drop_pct: 近 drop_days 天营收下降百分比（正数表示下降）
            drop_days:        统计窗口天数（默认7天）
            is_holiday:       是否节假日（节假日下降不算竞品信号）

        Returns:
            触发的竞品信号列表（无信号时返回空列表）
        """
        self.logger.info(
            "detecting_competitor_signals",
            store_id=self.store_id,
            revenue_drop_pct=revenue_drop_pct,
            is_holiday=is_holiday,
        )
        signals = []

        # 竞品代理信号：营收骤降 ≥ 15% 且非节假日
        if not is_holiday and revenue_drop_pct >= 15:
            severity = "high" if revenue_drop_pct >= 30 else "medium"
            now = datetime.utcnow().isoformat()
            signals.append(
                SignalEvent(
                    signal_id=(
                        f"SIG_COMPETITOR_{self.store_id}_{date.today().isoformat()}"
                    ),
                    signal_type=SignalType.COMPETITOR.value,
                    customer_id="",
                    store_id=self.store_id,
                    description=(
                        f"周边可能有竞品开业——{self.store_id}近{drop_days}天"
                        f"营收下降 {revenue_drop_pct:.1f}%，非节假日异常"
                    ),
                    severity=severity,
                    triggered_at=now,
                    action_taken=None,
                )
            )
        return signals

    async def calculate_store_quadrant(
        self,
        competition_density: float,
        member_count: int,
        estimated_population: int,
    ) -> StoreQuadrantData:
        """
        计算门店四象限位置
        横轴：竞争密度（周边1km同品类数）
        纵轴：会员渗透率（会员数/估算消费人口）
        """
        self.logger.info("calculating_store_quadrant")
        penetration = member_count / max(estimated_population, 1)
        high_penetration = penetration >= self.penetration_threshold
        high_competition = competition_density >= self.competition_threshold

        if high_penetration and not high_competition:
            quadrant = StoreQuadrant.BENCHMARK
            strategy = "重点投放S1 VIP个性化触达，启动老带新裂变，警惕周边新竞品"
        elif high_penetration and high_competition:
            quadrant = StoreQuadrant.DEFENSIVE
            strategy = "自动触发沉睡预警，优惠券对标竞品节点推送，差评24h内自动补偿"
        elif not high_penetration and not high_competition:
            quadrant = StoreQuadrant.POTENTIAL
            strategy = "引流活码密度最高，新客激活SOP（7天4触点），LBS区域定向推送"
        else:
            quadrant = StoreQuadrant.BREAKTHROUGH
            strategy = "限时高折扣首单券定向推送，异业联名换量，朋友圈广告精准本地投放"

        return StoreQuadrantData(
            store_id=self.store_id,
            store_name=f"门店 {self.store_id}",
            quadrant=quadrant.value,
            competition_density=competition_density,
            member_penetration=round(penetration, 3),
            untapped_potential=max(0, estimated_population - member_count),
            strategy=strategy,
        )

    async def trigger_journey(self, journey_type: str, customer_id: str) -> JourneyRecord:
        """触发用户旅程（持久化到 private_domain_journeys 表）"""
        self.logger.info("triggering_journey", journey_type=journey_type, customer_id=customer_id)
        journey_steps = {
            JourneyType.NEW_CUSTOMER.value: len(NEW_CUSTOMER_JOURNEY_STEPS),  # Hook四步
            JourneyType.VIP_RETENTION.value: 4,     # 月/季/生日/年
            JourneyType.REACTIVATION.value: 3,      # 第1/2/3触（损失厌恶分级）
            JourneyType.REVIEW_REPAIR.value: 4,     # 30min/4h/补偿/追踪
        }
        total_steps = journey_steps.get(journey_type, 3)
        now = datetime.utcnow()

        # REACTIVATION：按步骤定义的精确延迟天数设置首次 next_action_at
        # NEW_CUSTOMER Step1：消费后2小时内，delay=0天
        if journey_type == JourneyType.REACTIVATION.value:
            delay_days = _REACTIVATION_STEP_DELAYS.get(1, 3)
        elif journey_type == JourneyType.NEW_CUSTOMER.value:
            delay_days = 0
        else:
            delay_days = 2
        next_action_at = now + timedelta(days=delay_days)

        record = JourneyRecord(
            journey_id=f"JRN_{journey_type.upper()}_{customer_id}_{now.strftime('%Y%m%d%H%M%S')}",
            journey_type=journey_type,
            customer_id=customer_id,
            store_id=self.store_id,
            status=JourneyStatus.RUNNING.value,
            current_step=1,
            total_steps=total_steps,
            started_at=now.isoformat(),
            next_action_at=next_action_at.isoformat(),
            completed_at=None,
            step_actions=(
                NEW_CUSTOMER_JOURNEY_STEPS
                if journey_type == JourneyType.NEW_CUSTOMER.value
                else None
            ),
        )
        self._persist_journey_to_db(record)
        return record

    async def advance_reactivation_journey(
        self,
        journey: JourneyRecord,
        responded: bool,
    ) -> JourneyRecord:
        """
        推进沉睡唤醒旅程到下一步。

        responded=True  → 前进到下一步
        responded=False → 检查是否已到第3步无响应：是则进入 agent_exit 状态
        """
        current_step = journey["current_step"]
        total_steps = journey["total_steps"]
        now = datetime.utcnow()

        if not responded and current_step >= total_steps:
            # 第3触无响应：停止自动化，边际效益为负
            journey["status"] = JourneyStatus.AGENT_EXIT.value
            journey["completed_at"] = now.isoformat()
            self.logger.info(
                "reactivation_agent_exit",
                customer_id=journey["customer_id"],
                reason="no_response_after_step_3",
            )
        elif responded or current_step < total_steps:
            next_step = current_step + 1
            delay_days = _REACTIVATION_STEP_DELAYS.get(next_step, 7)
            journey["current_step"] = next_step
            journey["next_action_at"] = (now + timedelta(days=delay_days)).isoformat()
            if next_step > total_steps:
                journey["status"] = JourneyStatus.COMPLETED.value
                journey["completed_at"] = now.isoformat()

        self._persist_journey_to_db(journey)
        return journey

    async def get_journeys(self, status: Optional[str] = None) -> List[JourneyRecord]:
        """获取旅程列表（DB-first，无 DB 时返回空列表）"""
        self.logger.info("getting_journeys", status=status)
        return self._fetch_journeys_from_db(status)

    async def get_signals(
        self,
        signal_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[SignalEvent]:
        """获取信号列表"""
        signals = await self.detect_signals()
        if signal_type:
            signals = [s for s in signals if s["signal_type"] == signal_type]
        return signals[:limit]

    async def get_churn_risks(self) -> List[UserSegment]:
        """获取流失风险用户列表"""
        segments = await self.analyze_rfm(30)
        return [s for s in segments if s["rfm_level"] in ("S3", "S4", "S5") or s["risk_score"] >= 0.6]

    async def process_bad_review(
        self,
        review_id: str,
        customer_id: Optional[str],
        rating: int,
        content: str,
        customer_history: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        差评四阶心理修复协议。

        rating 1   → 15分钟响应窗口，4步修复，店长真人介入
        rating 2-3 → 30分钟响应窗口，2步修复，具名模板+个性化互惠

        customer_history 传入时用于推断个性化补偿类型（最爱菜品优先）。
        """
        self.logger.info("processing_bad_review", review_id=review_id, rating=rating)

        # 选择协议
        if rating <= 1:
            protocol = BAD_REVIEW_REPAIR_PROTOCOL["rating_1"]
        else:
            protocol = BAD_REVIEW_REPAIR_PROTOCOL["rating_2_3"]

        response_window = protocol["response_window_minutes"]
        step_sequence = [
            {"step": s["step"], "timing": s["timing"], "channel": s["channel"],
             "principle": s["principle"]}
            for s in protocol["steps"]
        ]
        compensation_type = _infer_compensation_type(customer_history)

        journey = None
        if customer_id:
            journey = await self.trigger_journey(JourneyType.REVIEW_REPAIR.value, customer_id)

        return {
            "review_id": review_id,
            "handled": True,
            "severity": protocol["severity"],
            "response_window_minutes": response_window,
            "total_repair_steps": len(protocol["steps"]),
            "step_sequence": step_sequence,
            "compensation_type": compensation_type,
            "compensation_issued": rating <= 2,
            "journey_triggered": journey is not None,
            "journey_id": journey["journey_id"] if journey else None,
            "handled_at": datetime.utcnow().isoformat(),
        }

    # ─────────────────────────── Private Helpers ───────────────────────────

    def _classify_rfm(self, recency_days: int, frequency: int, monetary: int) -> str:
        if recency_days <= 30 and frequency >= self.s1_min_frequency and monetary >= self.s1_min_monetary:
            return RFMLevel.S1.value
        elif recency_days <= 30 and (frequency >= 1 or monetary >= self.s1_min_monetary // 2):
            return RFMLevel.S2.value
        elif recency_days <= 60:
            return RFMLevel.S3.value
        elif recency_days <= 90:
            return RFMLevel.S4.value
        else:
            return RFMLevel.S5.value

    def _calculate_churn_risk(self, recency_days: int, frequency: int) -> float:
        base_risk = min(recency_days / 90, 1.0)
        freq_factor = max(0, 1 - frequency * 0.1)
        return round(min(base_risk * 0.7 + freq_factor * 0.3, 1.0), 3)

    def _infer_dynamic_tags(self, customer: Dict[str, Any]) -> List[str]:
        tags = []
        if customer["monetary"] >= self.s1_min_monetary * 2:
            tags.append("高消费")
        if customer["frequency"] >= 4:
            tags.append("高频")
        if customer["recency_days"] <= 7:
            tags.append("近期活跃")
        if customer.get("avg_order_time", 12) in range(11, 14):
            tags.append("午餐偏好")
        if customer.get("avg_order_time", 12) in range(17, 21):
            tags.append("晚餐偏好")
        return tags or ["普通用户"]
