"""情报->增长自动接力服务 — 从发现机会到执行动作的闭环

Intel Hub 发现市场机会后，自动创建增长活动草稿；
Growth Hub 试点结果反馈到 Intel 模型，形成数据闭环。
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()


# ---- 数据模型 ----

class OpportunityRelay(BaseModel):
    """情报机会 -> 增长活动草稿"""
    relay_id: str = Field(default_factory=lambda: f"relay-{uuid.uuid4().hex[:8]}")
    opportunity_id: str
    opportunity_type: str  # 新品机会 / 竞对防御 / 需求趋势 / 原料机会
    opportunity_title: str
    opportunity_score: float  # 0-100

    campaign_draft_id: Optional[str] = None
    campaign_type: Optional[str] = None  # 新品推广 / 价格防御 / 趋势跟进 / 裂变活动
    campaign_title: Optional[str] = None
    suggested_actions: list[str] = Field(default_factory=list)

    status: str = "pending"  # pending / draft_created / approved / executing / completed / rejected
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PilotFeedback(BaseModel):
    """增长试点结果 -> 情报模型反馈"""
    feedback_id: str = Field(default_factory=lambda: f"fb-{uuid.uuid4().hex[:8]}")
    pilot_id: str
    relay_id: str
    results: dict  # 试点结果数据
    metrics: dict  # 关键指标
    intel_model_updated: bool = False
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---- Mock 数据 ----

MOCK_RELAYS: list[dict] = [
    {
        "relay_id": "relay-a1b2c3d4",
        "opportunity_id": "opp-001",
        "opportunity_type": "新品机会",
        "opportunity_title": "酸汤火锅系列 — 市场热度飙升",
        "opportunity_score": 87.0,
        "campaign_draft_id": "camp-draft-001",
        "campaign_type": "新品推广",
        "campaign_title": "[自动草稿] 酸汤系列上新推广",
        "suggested_actions": [
            "芙蓉路店启动14天试点",
            "目标日均50份",
            "企微+小程序双渠道推广",
            "搭配新客满80减20券",
        ],
        "status": "executing",
        "created_at": "2026-03-22T08:00:00+00:00",
        "updated_at": "2026-03-25T10:30:00+00:00",
    },
    {
        "relay_id": "relay-e5f6g7h8",
        "opportunity_id": "opp-002",
        "opportunity_type": "竞对防御",
        "opportunity_title": "费大厨39.9元外卖套餐 — 低价分流风险",
        "opportunity_score": 78.0,
        "campaign_draft_id": "camp-draft-002",
        "campaign_type": "价格防御",
        "campaign_title": "[自动草稿] 差异化午市外卖组合",
        "suggested_actions": [
            "推出42元午市工作套餐（含汤）",
            "突出食材新鲜和分量优势",
            "美团限时满减活动",
        ],
        "status": "approved",
        "created_at": "2026-03-23T09:15:00+00:00",
        "updated_at": "2026-03-26T08:00:00+00:00",
    },
    {
        "relay_id": "relay-i9j0k1l2",
        "opportunity_id": "opp-003",
        "opportunity_type": "需求趋势",
        "opportunity_title": "一人食需求持续增长35%",
        "opportunity_score": 82.0,
        "campaign_draft_id": "camp-draft-003",
        "campaign_type": "趋势跟进",
        "campaign_title": "[自动草稿] 一人食精品套餐推广",
        "suggested_actions": [
            "五一广场店试点一人食专区",
            "午间时段11:30-13:30专属推送",
            "小红书KOL种草内容投放",
        ],
        "status": "draft_created",
        "created_at": "2026-03-24T11:00:00+00:00",
        "updated_at": "2026-03-24T11:00:00+00:00",
    },
    {
        "relay_id": "relay-m3n4o5p6",
        "opportunity_id": "opp-004",
        "opportunity_type": "新品机会",
        "opportunity_title": "节气限定菜品 — 社交传播潜力",
        "opportunity_score": 75.0,
        "campaign_draft_id": None,
        "campaign_type": None,
        "campaign_title": None,
        "suggested_actions": [],
        "status": "pending",
        "created_at": "2026-03-25T14:00:00+00:00",
        "updated_at": "2026-03-25T14:00:00+00:00",
    },
    {
        "relay_id": "relay-q7r8s9t0",
        "opportunity_id": "opp-005",
        "opportunity_type": "原料机会",
        "opportunity_title": "云南酸笋 — 搜索热度+60%",
        "opportunity_score": 68.0,
        "campaign_draft_id": "camp-draft-005",
        "campaign_type": "新品推广",
        "campaign_title": "[自动草稿] 酸笋系列配菜上新",
        "suggested_actions": [
            "采购部评估供应稳定性",
            "研发部开发3款酸笋配菜",
            "小范围试点后决定推广",
        ],
        "status": "draft_created",
        "created_at": "2026-03-25T16:30:00+00:00",
        "updated_at": "2026-03-25T16:30:00+00:00",
    },
]

MOCK_FEEDBACKS: list[dict] = [
    {
        "feedback_id": "fb-x1y2z3",
        "pilot_id": "pilot-001",
        "relay_id": "relay-a1b2c3d4",
        "results": {
            "pilot_store": "芙蓉路店",
            "duration_days": 4,
            "total_orders": 186,
            "avg_daily_orders": 46.5,
            "customer_satisfaction": 4.6,
        },
        "metrics": {
            "target_daily_orders": 50,
            "achievement_rate": 93.0,
            "repeat_order_rate": 28.5,
            "avg_ticket_size": 72.0,
            "gross_margin": 62.3,
        },
        "intel_model_updated": True,
        "created_at": "2026-03-26T09:00:00+00:00",
    },
]


# ---- 接力服务 ----

class GrowthIntelRelayService:
    """情报->增长自动接力 — 从发现机会到执行动作的闭环"""

    def __init__(self) -> None:
        self._relays: list[dict] = list(MOCK_RELAYS)
        self._feedbacks: list[dict] = list(MOCK_FEEDBACKS)

    def relay_opportunity_to_campaign(self, opportunity_id: str) -> dict:
        """Intel 发现机会 -> 自动创建增长活动草稿

        流程:
        1. 从 Intel Hub 获取机会详情
        2. 根据机会类型匹配活动模板
        3. 生成活动草稿（含渠道/券/内容建议）
        4. 写入接力记录
        """
        # 查找已有接力记录
        existing = next((r for r in self._relays if r["opportunity_id"] == opportunity_id), None)
        if existing and existing["status"] != "pending":
            logger.info("relay_already_exists", relay_id=existing["relay_id"], status=existing["status"])
            return existing

        # 模拟: 根据机会类型生成活动草稿
        campaign_type_map = {
            "新品机会": "新品推广",
            "竞对防御": "价格防御",
            "需求趋势": "趋势跟进",
            "原料机会": "新品推广",
        }

        relay_id = f"relay-{uuid.uuid4().hex[:8]}"
        campaign_draft_id = f"camp-draft-{uuid.uuid4().hex[:6]}"
        now = datetime.now(timezone.utc).isoformat()

        opp_type = "新品机会"
        opp_title = f"机会 {opportunity_id}"
        opp_score = 70.0

        if existing:
            opp_type = existing["opportunity_type"]
            opp_title = existing["opportunity_title"]
            opp_score = existing["opportunity_score"]
            relay_id = existing["relay_id"]

        campaign_type = campaign_type_map.get(opp_type, "趋势跟进")

        relay = {
            "relay_id": relay_id,
            "opportunity_id": opportunity_id,
            "opportunity_type": opp_type,
            "opportunity_title": opp_title,
            "opportunity_score": opp_score,
            "campaign_draft_id": campaign_draft_id,
            "campaign_type": campaign_type,
            "campaign_title": f"[自动草稿] {opp_title} 推广活动",
            "suggested_actions": [
                "选择试点门店",
                "配置目标人群和触达渠道",
                "设置权益和优惠券",
                "启动A/B测试",
            ],
            "status": "draft_created",
            "created_at": now,
            "updated_at": now,
        }

        if existing:
            idx = self._relays.index(existing)
            self._relays[idx] = relay
        else:
            self._relays.append(relay)

        logger.info(
            "relay_created",
            relay_id=relay_id,
            opportunity_id=opportunity_id,
            campaign_draft_id=campaign_draft_id,
        )
        return relay

    def relay_pilot_result_to_intel(self, pilot_id: str, results: dict) -> dict:
        """Growth 试点结果 -> 反馈到 Intel 模型

        流程:
        1. 接收试点结果数据
        2. 计算关键指标
        3. 更新 Intel 模型的机会评分
        4. 记录反馈
        """
        # 查找关联的接力记录
        relay = next(
            (r for r in self._relays if r.get("campaign_draft_id") and pilot_id in r.get("campaign_draft_id", "")),
            None,
        )
        relay_id = relay["relay_id"] if relay else "unknown"

        metrics = {
            "achievement_rate": results.get("achievement_rate", 0),
            "repeat_order_rate": results.get("repeat_order_rate", 0),
            "avg_ticket_size": results.get("avg_ticket_size", 0),
            "gross_margin": results.get("gross_margin", 0),
        }

        feedback = {
            "feedback_id": f"fb-{uuid.uuid4().hex[:6]}",
            "pilot_id": pilot_id,
            "relay_id": relay_id,
            "results": results,
            "metrics": metrics,
            "intel_model_updated": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        self._feedbacks.append(feedback)

        # 更新接力记录状态
        if relay:
            relay["status"] = "completed"
            relay["updated_at"] = datetime.now(timezone.utc).isoformat()

        logger.info(
            "pilot_feedback_recorded",
            feedback_id=feedback["feedback_id"],
            pilot_id=pilot_id,
            relay_id=relay_id,
        )
        return feedback

    def get_relay_history(self) -> list[dict]:
        """获取所有接力记录历史"""
        return sorted(self._relays, key=lambda r: r["created_at"], reverse=True)

    def get_active_relays(self) -> list[dict]:
        """获取活跃接力记录（非终态）"""
        active_statuses = {"pending", "draft_created", "approved", "executing"}
        return [
            r for r in self._relays
            if r["status"] in active_statuses
        ]

    def get_feedbacks(self) -> list[dict]:
        """获取所有试点反馈"""
        return sorted(self._feedbacks, key=lambda f: f["created_at"], reverse=True)

    def get_relay_stats(self) -> dict:
        """获取接力统计"""
        total = len(self._relays)
        by_status: dict[str, int] = {}
        for r in self._relays:
            by_status[r["status"]] = by_status.get(r["status"], 0) + 1

        return {
            "total_relays": total,
            "active_relays": len(self.get_active_relays()),
            "completed_relays": by_status.get("completed", 0),
            "rejected_relays": by_status.get("rejected", 0),
            "total_feedbacks": len(self._feedbacks),
            "by_status": by_status,
        }


# ---- FastAPI 路由 ----

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/growth-intel-relay", tags=["growth-intel-relay"])
_service = GrowthIntelRelayService()


@router.get("/relays")
async def list_relays() -> dict:
    """列出所有接力记录"""
    return {"ok": True, "data": {"items": _service.get_relay_history(), "total": len(_service.get_relay_history())}}


@router.get("/relays/active")
async def list_active_relays() -> dict:
    """列出活跃接力记录"""
    active = _service.get_active_relays()
    return {"ok": True, "data": {"items": active, "total": len(active)}}


@router.post("/relays/create")
async def create_relay(opportunity_id: str) -> dict:
    """从情报机会创建增长活动草稿"""
    relay = _service.relay_opportunity_to_campaign(opportunity_id)
    return {"ok": True, "data": relay}


@router.post("/feedbacks/create")
async def create_feedback(pilot_id: str, results: dict) -> dict:
    """记录试点结果反馈"""
    feedback = _service.relay_pilot_result_to_intel(pilot_id, results)
    return {"ok": True, "data": feedback}


@router.get("/feedbacks")
async def list_feedbacks() -> dict:
    """列出所有试点反馈"""
    feedbacks = _service.get_feedbacks()
    return {"ok": True, "data": {"items": feedbacks, "total": len(feedbacks)}}


@router.get("/stats")
async def relay_stats() -> dict:
    """接力统计"""
    return {"ok": True, "data": _service.get_relay_stats()}
