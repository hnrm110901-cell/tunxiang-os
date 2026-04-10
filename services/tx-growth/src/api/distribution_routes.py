"""
CRM三级分销路由 — 私域裂变三级链路 + 奖励体系

端点列表：
  POST   /api/v1/growth/referral/links                  生成推荐码
  GET    /api/v1/growth/referral/links/{member_id}       获取会员推荐码
  POST   /api/v1/growth/referral/bind                   绑定推荐关系（自动推导三级）
  GET    /api/v1/growth/referral/tree/{member_id}        查看推荐关系树
  POST   /api/v1/growth/referral/rewards/calculate       触发奖励计算
  POST   /api/v1/growth/referral/rewards/issue/{reward_id}  发放奖励
  GET    /api/v1/growth/referral/rewards/{member_id}     会员分销收益明细
  GET    /api/v1/growth/referral/stats                   分销总览
  GET    /api/v1/growth/referral/leaderboard             分销排行榜
  POST   /api/v1/growth/referral/rules                   保存分销规则配置
  GET    /api/v1/growth/referral/rules                   获取分销规则配置
  POST   /api/v1/growth/referral/detect-abuse            异常检测
"""
import random
import string
import uuid
from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, field_validator

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/growth/referral", tags=["distribution"])

# ---------------------------------------------------------------------------
# Mock 数据
# ---------------------------------------------------------------------------

MOCK_REFERRAL_TREE = {
    "member_id": "mem-001",
    "name": "张三",
    "level": 0,
    "children": [
        {
            "member_id": "mem-002",
            "name": "李四（直接推荐）",
            "level": 1,
            "orders": 3,
            "total_fen": 28800,
            "children": [
                {
                    "member_id": "mem-004",
                    "name": "王五（二级）",
                    "level": 2,
                    "orders": 1,
                    "total_fen": 9600,
                    "children": [],
                },
                {
                    "member_id": "mem-005",
                    "name": "赵六（二级）",
                    "level": 2,
                    "orders": 2,
                    "total_fen": 15200,
                    "children": [
                        {
                            "member_id": "mem-007",
                            "name": "钱七（三级）",
                            "level": 3,
                            "orders": 1,
                            "total_fen": 5800,
                            "children": [],
                        }
                    ],
                },
            ],
        },
        {
            "member_id": "mem-003",
            "name": "陈八（直接推荐）",
            "level": 1,
            "orders": 5,
            "total_fen": 48000,
            "children": [],
        },
    ],
}

# 内存模拟存储（mock fallback，生产环境替换为 DB 调用）
_MOCK_LINKS: dict[str, dict] = {}          # referral_code -> link_data
_MOCK_MEMBER_LINKS: dict[str, list] = {}   # member_id -> [link_data]
_MOCK_RELATIONSHIPS: dict[str, dict] = {}  # referee_id -> relationship
_MOCK_REWARDS: dict[str, dict] = {}        # reward_id -> reward_data
_MOCK_RULES: dict = {
    "level1_rate": 0.03,
    "level2_rate": 0.015,
    "level3_rate": 0.005,
    "reward_type": "points",
    "trigger_type": "first_order",
}


# ---------------------------------------------------------------------------
# 统一响应
# ---------------------------------------------------------------------------

def ok(data: object) -> dict:
    return {"ok": True, "data": data}


def err(msg: str, code: str = "ERROR") -> dict:
    return {"ok": False, "error": {"code": code, "message": msg}}


# ---------------------------------------------------------------------------
# Pydantic 请求模型
# ---------------------------------------------------------------------------

class GenerateLinkRequest(BaseModel):
    member_id: str
    channel: str = "wechat"
    expires_at: Optional[str] = None  # ISO8601，None=永久

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, v: str) -> str:
        allowed = {"wechat", "wecom", "direct"}
        if v not in allowed:
            raise ValueError(f"channel 必须是 {allowed} 之一")
        return v


class BindRequest(BaseModel):
    referee_id: str       # 新会员 ID
    referral_code: str    # 使用的推荐码


class CalculateRewardRequest(BaseModel):
    order_id: str
    member_id: str        # 消费会员（触发奖励的人）
    order_amount_fen: int

    @field_validator("order_amount_fen")
    @classmethod
    def validate_amount(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("订单金额必须大于0")
        return v


class SaveRulesRequest(BaseModel):
    level1_rate: float    # 一级佣金比例，如 0.03 = 3%
    level2_rate: float    # 二级佣金比例
    level3_rate: float    # 三级佣金比例
    reward_type: str      # coupon/points/cash
    trigger_type: str     # first_order/order/recharge

    @field_validator("level1_rate", "level2_rate", "level3_rate")
    @classmethod
    def validate_rate(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("佣金比例必须在 0~1 之间")
        return v

    @field_validator("reward_type")
    @classmethod
    def validate_reward_type(cls, v: str) -> str:
        allowed = {"coupon", "points", "cash"}
        if v not in allowed:
            raise ValueError(f"reward_type 必须是 {allowed} 之一")
        return v

    @field_validator("trigger_type")
    @classmethod
    def validate_trigger_type(cls, v: str) -> str:
        allowed = {"first_order", "order", "recharge"}
        if v not in allowed:
            raise ValueError(f"trigger_type 必须是 {allowed} 之一")
        return v


class DetectAbuseRequest(BaseModel):
    referee_id: str
    referral_code: str
    device_id: Optional[str] = None
    ip: Optional[str] = None


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _generate_code() -> str:
    """生成6字符推荐码，TX前缀+4位大写字母数字"""
    chars = string.ascii_uppercase + string.digits
    suffix = "".join(random.choices(chars, k=4))
    return f"TX{suffix}"


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


# ---------------------------------------------------------------------------
# 1. 生成推荐码
# ---------------------------------------------------------------------------

@router.post("/links")
async def generate_referral_link(
    req: GenerateLinkRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """为会员生成专属推荐码（TX + 4位大写字母数字）"""
    logger.info("referral.generate_link", member_id=req.member_id, tenant_id=x_tenant_id)

    # 生成唯一推荐码（避免碰撞）
    max_attempts = 10
    code: Optional[str] = None
    for _ in range(max_attempts):
        candidate = _generate_code()
        if candidate not in _MOCK_LINKS:
            code = candidate
            break
    if code is None:
        raise HTTPException(status_code=500, detail="推荐码生成失败，请重试")

    link_data = {
        "id": str(uuid.uuid4()),
        "tenant_id": x_tenant_id,
        "member_id": req.member_id,
        "referral_code": code,
        "channel": req.channel,
        "expires_at": req.expires_at,
        "click_count": 0,
        "convert_count": 0,
        "is_active": True,
        "created_at": _now_iso(),
    }

    _MOCK_LINKS[code] = link_data
    _MOCK_MEMBER_LINKS.setdefault(req.member_id, []).append(link_data)

    logger.info("referral.link_created", code=code, member_id=req.member_id)
    return ok(link_data)


# ---------------------------------------------------------------------------
# 2. 获取会员的推荐码
# ---------------------------------------------------------------------------

@router.get("/links/{member_id}")
async def get_member_links(
    member_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取会员的推荐码列表（含转化统计）"""
    links = _MOCK_MEMBER_LINKS.get(member_id, [])

    # mock fallback：若无数据则返回演示数据
    if not links:
        links = [
            {
                "id": "link-demo-001",
                "tenant_id": x_tenant_id,
                "member_id": member_id,
                "referral_code": "TX8A3K",
                "channel": "wechat",
                "expires_at": None,
                "click_count": 12,
                "convert_count": 3,
                "is_active": True,
                "created_at": "2026-03-01T08:00:00Z",
            }
        ]

    return ok({
        "member_id": member_id,
        "links": links,
        "total": len(links),
        "total_click": sum(lk["click_count"] for lk in links),
        "total_convert": sum(lk["convert_count"] for lk in links),
    })


# ---------------------------------------------------------------------------
# 3. 绑定推荐关系（自动推导三级）
# ---------------------------------------------------------------------------

@router.post("/bind")
async def bind_referral_relationship(
    req: BindRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """绑定推荐关系

    逻辑：
    - 通过 referral_code 找到 level1_id（直接推荐人）
    - level1 的推荐人 = level2
    - level2 的推荐人 = level3
    - 同一 referee_id 只能绑定一次（幂等）
    """
    logger.info("referral.bind", referee_id=req.referee_id, code=req.referral_code)

    # 幂等检查：已绑定则直接返回
    if req.referee_id in _MOCK_RELATIONSHIPS:
        existing = _MOCK_RELATIONSHIPS[req.referee_id]
        logger.info("referral.bind_idempotent", referee_id=req.referee_id)
        return ok({"idempotent": True, "relationship": existing})

    # 查找推荐码
    link = _MOCK_LINKS.get(req.referral_code)
    if link is None:
        # mock fallback：允许演示码 TX8A3K
        if req.referral_code == "TX8A3K":
            link = {
                "id": "link-demo-001",
                "member_id": "mem-001",
                "tenant_id": x_tenant_id,
            }
        else:
            raise HTTPException(status_code=404, detail=f"推荐码 {req.referral_code} 不存在或已失效")

    level1_id = link["member_id"]

    # 防止自推荐
    if level1_id == req.referee_id:
        raise HTTPException(status_code=400, detail="不可使用自己的推荐码")

    # 推导二级（level1 的直接推荐人）
    level1_rel = _MOCK_RELATIONSHIPS.get(level1_id)
    level2_id: Optional[str] = level1_rel["level1_id"] if level1_rel else None

    # 推导三级（level2 的直接推荐人）
    level3_id: Optional[str] = None
    if level2_id:
        level2_rel = _MOCK_RELATIONSHIPS.get(level2_id)
        level3_id = level2_rel["level1_id"] if level2_rel else None

    relationship = {
        "id": str(uuid.uuid4()),
        "tenant_id": x_tenant_id,
        "referee_id": req.referee_id,
        "level1_id": level1_id,
        "level2_id": level2_id,
        "level3_id": level3_id,
        "referral_link_id": link.get("id"),
        "registered_at": _now_iso(),
    }

    _MOCK_RELATIONSHIPS[req.referee_id] = relationship

    # 更新推荐码的转化计数
    if req.referral_code in _MOCK_LINKS:
        _MOCK_LINKS[req.referral_code]["convert_count"] += 1

    logger.info(
        "referral.bind_success",
        referee=req.referee_id,
        level1=level1_id,
        level2=level2_id,
        level3=level3_id,
    )
    return ok({"idempotent": False, "relationship": relationship})


# ---------------------------------------------------------------------------
# 4. 查看推荐关系树
# ---------------------------------------------------------------------------

@router.get("/tree/{member_id}")
async def get_referral_tree(
    member_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """查看会员的推荐关系树（直接下线+间接下线，含消费数据）"""
    # mock fallback：返回演示三级链路数据
    tree = MOCK_REFERRAL_TREE if member_id == "mem-001" else {
        "member_id": member_id,
        "name": f"会员_{member_id[-4:]}",
        "level": 0,
        "children": [],
    }

    # 计算汇总统计
    def _count(node: dict) -> tuple[int, int, int]:
        direct = len(node.get("children", []))
        indirect = 0
        total_fen = node.get("total_fen", 0)
        for child in node.get("children", []):
            d, ind, fen = _count(child)
            indirect += d + ind
            total_fen += fen
        return direct, indirect, total_fen

    direct_count, indirect_count, total_fen = _count(tree)

    return ok({
        "tree": tree,
        "summary": {
            "direct_referrals": direct_count,
            "indirect_referrals": indirect_count,
            "total_fen": total_fen,
        },
    })


# ---------------------------------------------------------------------------
# 5. 触发奖励计算
# ---------------------------------------------------------------------------

@router.post("/rewards/calculate")
async def calculate_rewards(
    req: CalculateRewardRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """触发奖励计算

    默认规则（可配置）：
    - 一级：订单金额 × 3%（积分）
    - 二级：订单金额 × 1.5%（积分）
    - 三级：订单金额 × 0.5%（积分）
    """
    rules = _MOCK_RULES
    rel = _MOCK_RELATIONSHIPS.get(req.member_id)

    # mock fallback：使用演示关系
    if rel is None:
        rel = {
            "referee_id": req.member_id,
            "level1_id": "mem-level1-demo",
            "level2_id": "mem-level2-demo",
            "level3_id": "mem-level3-demo",
        }

    rewards_created = []
    reward_map = [
        (1, rel.get("level1_id"), rules["level1_rate"]),
        (2, rel.get("level2_id"), rules["level2_rate"]),
        (3, rel.get("level3_id"), rules["level3_rate"]),
    ]

    for level, beneficiary_id, rate in reward_map:
        if beneficiary_id is None:
            continue
        reward_value_fen = int(req.order_amount_fen * rate)
        reward_id = str(uuid.uuid4())
        reward_data = {
            "id": reward_id,
            "tenant_id": x_tenant_id,
            "member_id": beneficiary_id,
            "referee_id": req.member_id,
            "reward_level": level,
            "trigger_type": rules["trigger_type"],
            "reward_type": rules["reward_type"],
            "reward_value_fen": reward_value_fen,
            "status": "pending",
            "order_id": req.order_id,
            "issued_at": None,
            "expires_at": None,
            "created_at": _now_iso(),
        }
        _MOCK_REWARDS[reward_id] = reward_data
        rewards_created.append(reward_data)

    logger.info(
        "referral.rewards_calculated",
        order_id=req.order_id,
        amount_fen=req.order_amount_fen,
        rewards_count=len(rewards_created),
    )
    return ok({
        "order_id": req.order_id,
        "consumer_id": req.member_id,
        "order_amount_fen": req.order_amount_fen,
        "rewards": rewards_created,
        "total_reward_fen": sum(r["reward_value_fen"] for r in rewards_created),
    })


# ---------------------------------------------------------------------------
# 6. 发放奖励
# ---------------------------------------------------------------------------

@router.post("/rewards/issue/{reward_id}")
async def issue_reward(
    reward_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """发放奖励（状态：pending → issued）"""
    reward = _MOCK_REWARDS.get(reward_id)
    if reward is None:
        raise HTTPException(status_code=404, detail=f"奖励记录 {reward_id} 不存在")

    if reward["status"] != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"奖励状态为 {reward['status']}，仅 pending 状态可发放",
        )

    reward["status"] = "issued"
    reward["issued_at"] = _now_iso()

    logger.info("referral.reward_issued", reward_id=reward_id, member_id=reward["member_id"])
    return ok(reward)


# ---------------------------------------------------------------------------
# 7. 会员分销收益明细
# ---------------------------------------------------------------------------

@router.get("/rewards/{member_id}")
async def get_member_rewards(
    member_id: str,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = Query(default=None),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取会员的分销收益明细（分页）"""
    all_rewards = [r for r in _MOCK_REWARDS.values() if r["member_id"] == member_id]

    if status:
        all_rewards = [r for r in all_rewards if r["status"] == status]

    # mock fallback：无数据时返回演示数据
    if not all_rewards:
        all_rewards = [
            {
                "id": "rw-demo-001",
                "tenant_id": x_tenant_id,
                "member_id": member_id,
                "referee_id": "mem-002",
                "reward_level": 1,
                "trigger_type": "first_order",
                "reward_type": "points",
                "reward_value_fen": 300,
                "status": "issued",
                "order_id": "ord-demo-001",
                "issued_at": "2026-03-15T10:00:00Z",
                "expires_at": None,
                "created_at": "2026-03-15T09:58:00Z",
            },
            {
                "id": "rw-demo-002",
                "tenant_id": x_tenant_id,
                "member_id": member_id,
                "referee_id": "mem-003",
                "reward_level": 1,
                "trigger_type": "order",
                "reward_type": "points",
                "reward_value_fen": 480,
                "status": "pending",
                "order_id": "ord-demo-002",
                "issued_at": None,
                "expires_at": None,
                "created_at": "2026-04-01T14:22:00Z",
            },
        ]

    total = len(all_rewards)
    start = (page - 1) * size
    items = all_rewards[start: start + size]

    return ok({
        "items": items,
        "total": total,
        "page": page,
        "size": size,
        "total_issued_fen": sum(
            r["reward_value_fen"] for r in all_rewards if r["status"] == "issued"
        ),
        "total_pending_fen": sum(
            r["reward_value_fen"] for r in all_rewards if r["status"] == "pending"
        ),
    })


# ---------------------------------------------------------------------------
# 8. 分销总览
# ---------------------------------------------------------------------------

@router.get("/stats")
async def get_distribution_stats(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """分销总览（参与会员数/三级链路数/本月奖励发放额）"""
    # 聚合 mock 数据
    participant_count = len(set(lk["member_id"] for lk in _MOCK_LINKS.values()))
    relationship_count = len(_MOCK_RELATIONSHIPS)
    all_rewards = list(_MOCK_REWARDS.values())
    issued_fen = sum(r["reward_value_fen"] for r in all_rewards if r["status"] == "issued")
    pending_fen = sum(r["reward_value_fen"] for r in all_rewards if r["status"] == "pending")

    # fallback mock 数据（若内存为空）
    if participant_count == 0:
        participant_count = 128
        relationship_count = 89
        issued_fen = 456800
        pending_fen = 78200

    return ok({
        "participant_count": participant_count,
        "participant_growth_this_month": 23,
        "three_level_chain_count": relationship_count,
        "this_month_issued_fen": issued_fen,
        "pending_reward_fen": pending_fen,
        "total_click_count": sum(lk["click_count"] for lk in _MOCK_LINKS.values()) or 3842,
        "total_convert_count": sum(lk["convert_count"] for lk in _MOCK_LINKS.values()) or 289,
        "convert_rate": round(289 / 3842, 4) if not _MOCK_LINKS else None,
    })


# ---------------------------------------------------------------------------
# 9. 分销排行榜
# ---------------------------------------------------------------------------

@router.get("/leaderboard")
async def get_leaderboard(
    period: str = Query(default="month", description="today/week/month"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """分销排行榜（按推荐转化数/获得奖励排名）"""
    if period not in ("today", "week", "month"):
        raise HTTPException(status_code=400, detail="period 必须是 today/week/month 之一")

    # mock 排行榜数据
    mock_board = [
        {
            "rank": 1,
            "member_id": "mem-003",
            "nickname": "陈八",
            "phone_tail": "8888",
            "direct_referrals": 15,
            "indirect_referrals": 32,
            "total_reward_fen": 128400,
        },
        {
            "rank": 2,
            "member_id": "mem-001",
            "nickname": "张三",
            "phone_tail": "6666",
            "direct_referrals": 12,
            "indirect_referrals": 28,
            "total_reward_fen": 96200,
        },
        {
            "rank": 3,
            "member_id": "mem-002",
            "nickname": "李四",
            "phone_tail": "1234",
            "direct_referrals": 8,
            "indirect_referrals": 19,
            "total_reward_fen": 68800,
        },
        {
            "rank": 4,
            "member_id": "mem-010",
            "nickname": "周九",
            "phone_tail": "5566",
            "direct_referrals": 6,
            "indirect_referrals": 11,
            "total_reward_fen": 42300,
        },
        {
            "rank": 5,
            "member_id": "mem-011",
            "nickname": "吴十",
            "phone_tail": "7788",
            "direct_referrals": 5,
            "indirect_referrals": 8,
            "total_reward_fen": 31500,
        },
    ]

    return ok({
        "period": period,
        "items": mock_board,
        "total": len(mock_board),
    })


# ---------------------------------------------------------------------------
# 10. 保存分销规则配置
# ---------------------------------------------------------------------------

@router.post("/rules")
async def save_distribution_rules(
    req: SaveRulesRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """保存三级分销规则配置"""
    _MOCK_RULES.update({
        "level1_rate": req.level1_rate,
        "level2_rate": req.level2_rate,
        "level3_rate": req.level3_rate,
        "reward_type": req.reward_type,
        "trigger_type": req.trigger_type,
        "updated_at": _now_iso(),
        "updated_by_tenant": x_tenant_id,
    })
    logger.info(
        "referral.rules_saved",
        tenant_id=x_tenant_id,
        level1=req.level1_rate,
        level2=req.level2_rate,
        level3=req.level3_rate,
    )
    return ok({"saved": True, "rules": _MOCK_RULES})


# ---------------------------------------------------------------------------
# 11. 获取分销规则配置
# ---------------------------------------------------------------------------

@router.get("/rules")
async def get_distribution_rules(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取当前分销规则配置"""
    return ok(_MOCK_RULES)


# ---------------------------------------------------------------------------
# 12. 异常检测（防刷）
# ---------------------------------------------------------------------------

@router.post("/detect-abuse")
async def detect_abuse(
    req: DetectAbuseRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """防刷异常检测

    检查同 referee_id 重复绑定、同设备/同IP短时间多次绑定等异常行为。
    """
    abuse_flags: list[str] = []

    # 检查1：referee_id 是否已绑定（重复绑定）
    if req.referee_id in _MOCK_RELATIONSHIPS:
        abuse_flags.append("DUPLICATE_BIND")

    # 检查2：模拟同设备绑定检测
    if req.device_id:
        device_bind_count = sum(
            1 for rel in _MOCK_RELATIONSHIPS.values()
            if rel.get("device_id") == req.device_id
        )
        if device_bind_count >= 3:
            abuse_flags.append("SAME_DEVICE_MULTIPLE_BIND")

    # 检查3：模拟同IP短时间多次绑定检测（示例：同IP超过5次视为异常）
    if req.ip:
        ip_bind_count = sum(
            1 for rel in _MOCK_RELATIONSHIPS.values()
            if rel.get("ip") == req.ip
        )
        if ip_bind_count >= 5:
            abuse_flags.append("SAME_IP_MULTIPLE_BIND")

    is_abuse = len(abuse_flags) > 0
    risk_level = "high" if len(abuse_flags) >= 2 else ("medium" if is_abuse else "low")

    logger.info(
        "referral.abuse_check",
        referee_id=req.referee_id,
        is_abuse=is_abuse,
        flags=abuse_flags,
        risk_level=risk_level,
    )

    return ok({
        "referee_id": req.referee_id,
        "is_abuse": is_abuse,
        "risk_level": risk_level,
        "flags": abuse_flags,
        "recommendation": "block" if risk_level == "high" else (
            "review" if risk_level == "medium" else "allow"
        ),
    })
