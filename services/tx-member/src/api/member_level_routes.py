"""会员等级运营 API

端点列表：
  GET  /api/v1/member/level-configs              — 等级配置列表
  POST /api/v1/member/level-configs              — 创建等级配置
  PUT  /api/v1/member/level-configs/{id}         — 更新等级配置
  POST /api/v1/members/{member_id}/check-upgrade — 检查并执行升降级
  GET  /api/v1/members/{member_id}/level-history — 升降级历史
  POST /api/v1/members/{member_id}/points/earn   — 积分入账
  GET  /api/v1/member/points-rules               — 积分规则列表
  POST /api/v1/member/points-rules               — 创建积分规则
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["member-levels"])


# ─── 类型常量 ───────────────────────────────────────────────────────────────

LevelCode = Literal["normal", "silver", "gold", "diamond"]
TriggerType = Literal["points_upgrade", "spend_upgrade", "manual", "expiry_downgrade"]
EarnType = Literal["consumption", "birthday", "signup", "referral", "checkin"]

_LEVEL_DEFAULTS: list[dict] = [
    {
        "level_code": "normal",
        "level_name": "普通会员",
        "min_points": 0,
        "min_annual_spend_fen": 0,
        "discount_rate": Decimal("1.00"),
        "birthday_bonus_multiplier": Decimal("1.0"),
        "priority_queue": False,
        "free_delivery": False,
        "sort_order": 0,
        "is_active": True,
    },
    {
        "level_code": "silver",
        "level_name": "银卡会员",
        "min_points": 1000,
        "min_annual_spend_fen": 50000,
        "discount_rate": Decimal("0.98"),
        "birthday_bonus_multiplier": Decimal("1.5"),
        "priority_queue": False,
        "free_delivery": False,
        "sort_order": 1,
        "is_active": True,
    },
    {
        "level_code": "gold",
        "level_name": "金卡会员",
        "min_points": 5000,
        "min_annual_spend_fen": 300000,
        "discount_rate": Decimal("0.95"),
        "birthday_bonus_multiplier": Decimal("2.0"),
        "priority_queue": True,
        "free_delivery": False,
        "sort_order": 2,
        "is_active": True,
    },
    {
        "level_code": "diamond",
        "level_name": "黑金会员",
        "min_points": 10000,
        "min_annual_spend_fen": 1000000,
        "discount_rate": Decimal("0.88"),
        "birthday_bonus_multiplier": Decimal("3.0"),
        "priority_queue": True,
        "free_delivery": True,
        "sort_order": 3,
        "is_active": True,
    },
]


# ─── Pydantic 模型 ──────────────────────────────────────────────────────────

class LevelConfigOut(BaseModel):
    id: str
    tenant_id: str
    level_code: str
    level_name: str
    min_points: int
    min_annual_spend_fen: int
    discount_rate: float
    birthday_bonus_multiplier: float
    priority_queue: bool
    free_delivery: bool
    sort_order: int
    is_active: bool
    created_at: str
    updated_at: str


class LevelConfigCreate(BaseModel):
    level_code: LevelCode
    level_name: str = Field(..., max_length=20)
    min_points: int = Field(0, ge=0)
    min_annual_spend_fen: int = Field(0, ge=0)
    discount_rate: float = Field(1.0, ge=0.5, le=1.0)
    birthday_bonus_multiplier: float = Field(1.0, ge=1.0, le=5.0)
    priority_queue: bool = False
    free_delivery: bool = False
    sort_order: int = 0
    is_active: bool = True


class LevelConfigUpdate(BaseModel):
    level_name: Optional[str] = Field(None, max_length=20)
    min_points: Optional[int] = Field(None, ge=0)
    min_annual_spend_fen: Optional[int] = Field(None, ge=0)
    discount_rate: Optional[float] = Field(None, ge=0.5, le=1.0)
    birthday_bonus_multiplier: Optional[float] = Field(None, ge=1.0, le=5.0)
    priority_queue: Optional[bool] = None
    free_delivery: Optional[bool] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class CheckUpgradeResult(BaseModel):
    upgraded: bool
    from_level: Optional[str]
    to_level: str
    current_points: int
    current_annual_spend_fen: int


class LevelHistoryOut(BaseModel):
    id: str
    member_id: str
    from_level: Optional[str]
    to_level: str
    trigger_type: str
    trigger_value: Optional[int]
    note: Optional[str]
    created_at: str


class EarnPointsRequest(BaseModel):
    earn_type: EarnType
    order_id: Optional[str] = None
    amount_fen: Optional[int] = Field(None, ge=0)
    note: Optional[str] = None


class EarnPointsResult(BaseModel):
    earned_points: int
    total_points: int


class PointsRuleOut(BaseModel):
    id: str
    tenant_id: str
    store_id: Optional[str]
    rule_name: str
    earn_type: str
    points_per_100fen: int
    fixed_points: int
    multiplier: float
    valid_from: Optional[str]
    valid_to: Optional[str]
    is_active: bool
    created_at: str
    updated_at: str


class PointsRuleCreate(BaseModel):
    store_id: Optional[str] = None
    rule_name: str = Field(..., max_length=50)
    earn_type: EarnType
    points_per_100fen: int = Field(1, ge=0)
    fixed_points: int = Field(0, ge=0)
    multiplier: float = Field(1.0, ge=0.1, le=10.0)
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    is_active: bool = True


# ─── 工具函数 ───────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _make_level_config(tenant_id: str, d: dict, config_id: Optional[str] = None) -> dict:
    now = _now_iso()
    return {
        "id": config_id or str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "level_code": d["level_code"],
        "level_name": d["level_name"],
        "min_points": d["min_points"],
        "min_annual_spend_fen": d["min_annual_spend_fen"],
        "discount_rate": float(d["discount_rate"]),
        "birthday_bonus_multiplier": float(d["birthday_bonus_multiplier"]),
        "priority_queue": d["priority_queue"],
        "free_delivery": d["free_delivery"],
        "sort_order": d["sort_order"],
        "is_active": d["is_active"],
        "created_at": now,
        "updated_at": now,
    }


# ─── 内存存储（TODO：接入真实数据库） ─────────────────────────────────────────
# 生产环境中所有 _STORE_* 应替换为 asyncpg/sqlalchemy 查询。
# 当前为 stub 实现，结构完整，类型安全，前端可正常对接。

_LEVEL_CONFIG_STORE: dict[str, list[dict]] = {}  # tenant_id -> list[config]
_LEVEL_HISTORY_STORE: dict[str, list[dict]] = {}  # member_id -> list[history]
_POINTS_RULES_STORE: dict[str, list[dict]] = {}   # tenant_id -> list[rule]
_MEMBER_POINTS_STORE: dict[str, int] = {}          # member_id -> points


def _get_tenant_configs(tenant_id: str) -> list[dict]:
    if tenant_id not in _LEVEL_CONFIG_STORE:
        _LEVEL_CONFIG_STORE[tenant_id] = [
            _make_level_config(tenant_id, d) for d in _LEVEL_DEFAULTS
        ]
    return _LEVEL_CONFIG_STORE[tenant_id]


def _find_eligible_level(configs: list[dict], points: int, annual_spend_fen: int) -> dict:
    """找到会员当前积分/消费满足的最高等级。"""
    active = [c for c in configs if c["is_active"]]
    active.sort(key=lambda c: c["sort_order"], reverse=True)
    for cfg in active:
        if points >= cfg["min_points"] and annual_spend_fen >= cfg["min_annual_spend_fen"]:
            return cfg
    # 兜底返回最低等级
    active.sort(key=lambda c: c["sort_order"])
    return active[0] if active else {"level_code": "normal", "level_name": "普通会员"}


def _calc_earned_points(
    earn_type: str,
    amount_fen: Optional[int],
    rules: list[dict],
) -> int:
    """根据积分规则计算应得积分。"""
    today = date.today()
    matching = [
        r for r in rules
        if r["earn_type"] == earn_type
        and r["is_active"]
        and (r["valid_from"] is None or r["valid_from"] <= today)
        and (r["valid_to"] is None or r["valid_to"] >= today)
    ]
    if not matching:
        # 默认规则：消费每100分1积分；其余固定0
        if earn_type == "consumption" and amount_fen:
            return max(1, amount_fen // 100)
        if earn_type == "signup":
            return 100
        if earn_type == "birthday":
            return 200
        if earn_type == "checkin":
            return 5
        return 0

    # 取第一条匹配规则（可扩展为叠加）
    rule = matching[0]
    if earn_type == "consumption" and amount_fen is not None:
        base = (amount_fen // 100) * rule["points_per_100fen"]
        return int(base * float(rule["multiplier"]))
    return int(rule["fixed_points"] * float(rule["multiplier"]))


# ─── 等级配置端点 ────────────────────────────────────────────────────────────

@router.get("/api/v1/member/level-configs")
async def list_level_configs(
    tenant_id: str = Query(..., description="租户ID"),
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
) -> dict:
    """获取租户等级配置列表（按 sort_order 升序）。"""
    tid = tenant_id or x_tenant_id
    if not tid:
        raise HTTPException(status_code=400, detail="tenant_id 必填")
    configs = sorted(_get_tenant_configs(tid), key=lambda c: c["sort_order"])
    return {"ok": True, "data": {"items": configs, "total": len(configs)}}


@router.post("/api/v1/member/level-configs")
async def create_level_config(
    body: LevelConfigCreate,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
) -> dict:
    """创建或重置等级配置（管理员操作）。"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header 必填")
    configs = _get_tenant_configs(x_tenant_id)
    # 同一租户同一 level_code 不允许重复
    existing = next((c for c in configs if c["level_code"] == body.level_code), None)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"等级 {body.level_code} 已存在，请使用 PUT 更新",
        )
    new_config = _make_level_config(x_tenant_id, body.model_dump())
    configs.append(new_config)
    logger.info("level_config_created", tenant_id=x_tenant_id, level_code=body.level_code)
    return {"ok": True, "data": new_config}


@router.put("/api/v1/member/level-configs/{config_id}")
async def update_level_config(
    config_id: str,
    body: LevelConfigUpdate,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
) -> dict:
    """更新等级配置。"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header 必填")
    configs = _get_tenant_configs(x_tenant_id)
    cfg = next((c for c in configs if c["id"] == config_id), None)
    if not cfg:
        raise HTTPException(status_code=404, detail="等级配置不存在")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    cfg.update(updates)
    cfg["updated_at"] = _now_iso()
    logger.info("level_config_updated", tenant_id=x_tenant_id, config_id=config_id)
    return {"ok": True, "data": cfg}


# ─── 升降级检查端点 ───────────────────────────────────────────────────────────

@router.post("/api/v1/members/{member_id}/check-upgrade")
async def check_upgrade(
    member_id: str,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
) -> dict:
    """检查并执行升降级。

    1. 查询会员当前积分（stub：从内存获取）
    2. 查询年度消费（stub：固定值，生产接入 orders 汇总）
    3. 找到符合条件的最高等级
    4. 如等级变更，写 level_history 记录
    5. 返回升降级结果
    """
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header 必填")

    configs = _get_tenant_configs(x_tenant_id)
    if not configs:
        raise HTTPException(status_code=404, detail="未找到等级配置")

    # TODO: 接入真实数据库查询 members 表
    current_points = _MEMBER_POINTS_STORE.get(member_id, 0)
    # TODO: 从 orders 表汇总过去12个月消费金额
    current_annual_spend_fen = 0

    eligible = _find_eligible_level(configs, current_points, current_annual_spend_fen)
    new_level = eligible["level_code"]

    # 获取当前等级（stub：从历史记录最新一条取）
    history = _LEVEL_HISTORY_STORE.get(member_id, [])
    from_level = history[-1]["to_level"] if history else "normal"

    upgraded = new_level != from_level
    if upgraded:
        record = {
            "id": str(uuid.uuid4()),
            "tenant_id": x_tenant_id,
            "member_id": member_id,
            "from_level": from_level,
            "to_level": new_level,
            "trigger_type": "points_upgrade" if current_points >= eligible["min_points"] else "spend_upgrade",
            "trigger_value": current_points,
            "note": f"系统自动检查: 积分{current_points}, 年消费{current_annual_spend_fen}分",
            "created_at": _now_iso(),
        }
        if member_id not in _LEVEL_HISTORY_STORE:
            _LEVEL_HISTORY_STORE[member_id] = []
        _LEVEL_HISTORY_STORE[member_id].append(record)
        logger.info(
            "member_level_changed",
            member_id=member_id,
            from_level=from_level,
            to_level=new_level,
        )

    return {
        "ok": True,
        "data": {
            "upgraded": upgraded,
            "from_level": from_level,
            "to_level": new_level,
            "current_points": current_points,
            "current_annual_spend_fen": current_annual_spend_fen,
        },
    }


@router.get("/api/v1/members/{member_id}/level-history")
async def get_level_history(
    member_id: str,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
) -> dict:
    """获取最近10条升降级记录。"""
    history = _LEVEL_HISTORY_STORE.get(member_id, [])
    recent = sorted(history, key=lambda h: h["created_at"], reverse=True)[:10]
    return {"ok": True, "data": {"items": recent, "total": len(recent)}}


# ─── 积分入账端点 ─────────────────────────────────────────────────────────────

@router.post("/api/v1/members/{member_id}/points/earn")
async def earn_points(
    member_id: str,
    body: EarnPointsRequest,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
) -> dict:
    """积分入账。

    根据 member_points_rules 中的规则计算应得积分并更新会员积分。
    """
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header 必填")

    rules = _POINTS_RULES_STORE.get(x_tenant_id, [])
    earned = _calc_earned_points(body.earn_type, body.amount_fen, rules)

    current = _MEMBER_POINTS_STORE.get(member_id, 0)
    _MEMBER_POINTS_STORE[member_id] = current + earned

    logger.info(
        "points_earned",
        member_id=member_id,
        earn_type=body.earn_type,
        earned=earned,
        total=_MEMBER_POINTS_STORE[member_id],
    )
    return {
        "ok": True,
        "data": {
            "earned_points": earned,
            "total_points": _MEMBER_POINTS_STORE[member_id],
        },
    }


# ─── 积分规则端点 ─────────────────────────────────────────────────────────────

@router.get("/api/v1/member/points-rules")
async def list_points_rules(
    store_id: Optional[str] = Query(None, description="门店ID，不传则返回品牌通用规则"),
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
) -> dict:
    """返回积分规则列表（按 earn_type 分组）。"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header 必填")
    all_rules = _POINTS_RULES_STORE.get(x_tenant_id, [])
    if store_id:
        filtered = [r for r in all_rules if r["store_id"] is None or r["store_id"] == store_id]
    else:
        filtered = [r for r in all_rules if r["store_id"] is None]
    return {"ok": True, "data": {"items": filtered, "total": len(filtered)}}


@router.post("/api/v1/member/points-rules")
async def create_points_rule(
    body: PointsRuleCreate,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
) -> dict:
    """创建积分规则（管理员操作）。"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header 必填")
    now = _now_iso()
    rule = {
        "id": str(uuid.uuid4()),
        "tenant_id": x_tenant_id,
        "store_id": body.store_id,
        "rule_name": body.rule_name,
        "earn_type": body.earn_type,
        "points_per_100fen": body.points_per_100fen,
        "fixed_points": body.fixed_points,
        "multiplier": body.multiplier,
        "valid_from": body.valid_from.isoformat() if body.valid_from else None,
        "valid_to": body.valid_to.isoformat() if body.valid_to else None,
        "is_active": body.is_active,
        "created_at": now,
        "updated_at": now,
    }
    if x_tenant_id not in _POINTS_RULES_STORE:
        _POINTS_RULES_STORE[x_tenant_id] = []
    _POINTS_RULES_STORE[x_tenant_id].append(rule)
    logger.info("points_rule_created", tenant_id=x_tenant_id, earn_type=body.earn_type)
    return {"ok": True, "data": rule}
