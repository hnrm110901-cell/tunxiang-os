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

from datetime import date, datetime, timezone
from typing import Literal, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["member-levels"])


# ─── 类型常量 ───────────────────────────────────────────────────────────────

LevelCode = Literal["normal", "silver", "gold", "diamond"]
TriggerType = Literal["points_upgrade", "spend_upgrade", "manual", "expiry_downgrade"]
EarnType = Literal["consumption", "birthday", "signup", "referral", "checkin"]


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


async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ─── 等级配置端点 ────────────────────────────────────────────────────────────


@router.get("/api/v1/member/level-configs")
async def list_level_configs(
    tenant_id: str = Query(..., description="租户ID"),
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict:
    """获取租户等级配置列表（按 sort_order 升序）。"""
    tid = tenant_id or x_tenant_id
    if not tid:
        raise HTTPException(status_code=400, detail="tenant_id 必填")
    try:
        result = await db.execute(
            text(
                "SELECT id, tenant_id, level_code, level_name, min_points, "
                "min_annual_spend_fen, discount_rate, birthday_bonus_multiplier, "
                "priority_queue, free_delivery, sort_order, is_active, "
                "created_at, updated_at "
                "FROM member_level_configs "
                "WHERE is_deleted = FALSE "
                "ORDER BY sort_order ASC"
            )
        )
        rows = result.mappings().all()
        items = [
            {
                **dict(row),
                "id": str(row["id"]),
                "tenant_id": str(row["tenant_id"]),
                "discount_rate": float(row["discount_rate"]),
                "birthday_bonus_multiplier": float(row["birthday_bonus_multiplier"]),
                "created_at": row["created_at"].isoformat(),
                "updated_at": row["updated_at"].isoformat(),
            }
            for row in rows
        ]
        return {"ok": True, "data": {"items": items, "total": len(items)}}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error("list_level_configs_error", error=str(exc))
        raise HTTPException(status_code=500, detail="查询等级配置失败")


@router.post("/api/v1/member/level-configs")
async def create_level_config(
    body: LevelConfigCreate,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict:
    """创建等级配置（管理员操作）。"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header 必填")
    try:
        # 检查 level_code 唯一性
        check = await db.execute(
            text(
                "SELECT id FROM member_level_configs "
                "WHERE tenant_id = :tid AND level_code = :code AND is_deleted = FALSE"
            ),
            {"tid": x_tenant_id, "code": body.level_code},
        )
        if check.fetchone():
            raise HTTPException(
                status_code=409,
                detail=f"等级 {body.level_code} 已存在，请使用 PUT 更新",
            )
        result = await db.execute(
            text(
                "INSERT INTO member_level_configs "
                "(tenant_id, level_code, level_name, min_points, min_annual_spend_fen, "
                "discount_rate, birthday_bonus_multiplier, priority_queue, free_delivery, "
                "sort_order, is_active) "
                "VALUES (:tid, :code, :name, :min_pts, :min_spend, :disc, :bday, "
                ":pq, :fd, :sort, :active) "
                "RETURNING id, tenant_id, level_code, level_name, min_points, "
                "min_annual_spend_fen, discount_rate, birthday_bonus_multiplier, "
                "priority_queue, free_delivery, sort_order, is_active, created_at, updated_at"
            ),
            {
                "tid": x_tenant_id,
                "code": body.level_code,
                "name": body.level_name,
                "min_pts": body.min_points,
                "min_spend": body.min_annual_spend_fen,
                "disc": body.discount_rate,
                "bday": body.birthday_bonus_multiplier,
                "pq": body.priority_queue,
                "fd": body.free_delivery,
                "sort": body.sort_order,
                "active": body.is_active,
            },
        )
        row = result.mappings().one()
        await db.commit()
        new_config = {
            **dict(row),
            "id": str(row["id"]),
            "tenant_id": str(row["tenant_id"]),
            "discount_rate": float(row["discount_rate"]),
            "birthday_bonus_multiplier": float(row["birthday_bonus_multiplier"]),
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
        }
        logger.info("level_config_created", tenant_id=x_tenant_id, level_code=body.level_code)
        return {"ok": True, "data": new_config}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("create_level_config_error", error=str(exc))
        raise HTTPException(status_code=500, detail="创建等级配置失败")


@router.put("/api/v1/member/level-configs/{config_id}")
async def update_level_config(
    config_id: str,
    body: LevelConfigUpdate,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict:
    """更新等级配置。"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header 必填")
    try:
        updates = {k: v for k, v in body.model_dump().items() if v is not None}
        if not updates:
            raise HTTPException(status_code=400, detail="没有可更新的字段")

        set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
        params = {**updates, "cid": config_id, "updated_at": datetime.now(tz=timezone.utc)}
        result = await db.execute(
            text(
                f"UPDATE member_level_configs "
                f"SET {set_clauses}, updated_at = :updated_at "
                f"WHERE id = :cid AND is_deleted = FALSE "
                f"RETURNING id, tenant_id, level_code, level_name, min_points, "
                f"min_annual_spend_fen, discount_rate, birthday_bonus_multiplier, "
                f"priority_queue, free_delivery, sort_order, is_active, created_at, updated_at"
            ),
            params,
        )
        row = result.mappings().fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="等级配置不存在")
        await db.commit()
        updated = {
            **dict(row),
            "id": str(row["id"]),
            "tenant_id": str(row["tenant_id"]),
            "discount_rate": float(row["discount_rate"]),
            "birthday_bonus_multiplier": float(row["birthday_bonus_multiplier"]),
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
        }
        logger.info("level_config_updated", tenant_id=x_tenant_id, config_id=config_id)
        return {"ok": True, "data": updated}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("update_level_config_error", error=str(exc))
        raise HTTPException(status_code=500, detail="更新等级配置失败")


# ─── 升降级检查端点 ───────────────────────────────────────────────────────────


@router.post("/api/v1/members/{member_id}/check-upgrade")
async def check_upgrade(
    member_id: str,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict:
    """检查并执行升降级。

    1. 查询会员当前积分（member_points_balance）
    2. 查询年度消费（orders 表汇总）
    3. 找到符合条件的最高等级
    4. 如等级变更，写 member_level_history 并更新 customers
    5. 返回升降级结果
    """
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header 必填")
    try:
        # 查积分余额
        pts_row = await db.execute(
            text("SELECT points FROM member_points_balance WHERE tenant_id = :tid AND member_id = :mid"),
            {"tid": x_tenant_id, "mid": member_id},
        )
        pts_record = pts_row.fetchone()
        current_points: int = pts_record[0] if pts_record else 0

        # 查年度消费（orders 表，customer_id 字段，DATE_TRUNC 年初）
        spend_row = await db.execute(
            text(
                "SELECT COALESCE(SUM(total_fen), 0) AS annual_spend "
                "FROM orders "
                "WHERE tenant_id = :tid AND customer_id = :mid "
                "AND created_at >= DATE_TRUNC('year', NOW())"
            ),
            {"tid": x_tenant_id, "mid": member_id},
        )
        spend_record = spend_row.fetchone()
        current_annual_spend_fen: int = int(spend_record[0]) if spend_record else 0

        # 查所有等级配置（按 min_points DESC，找最高满足等级）
        configs_result = await db.execute(
            text(
                "SELECT level_code, min_points, min_annual_spend_fen "
                "FROM member_level_configs "
                "WHERE tenant_id = :tid AND is_active = TRUE AND is_deleted = FALSE "
                "ORDER BY min_points DESC"
            ),
            {"tid": x_tenant_id},
        )
        configs = configs_result.mappings().all()
        if not configs:
            raise HTTPException(status_code=404, detail="未找到等级配置")

        eligible_level: Optional[str] = None
        for cfg in configs:
            if current_points >= cfg["min_points"] and current_annual_spend_fen >= cfg["min_annual_spend_fen"]:
                eligible_level = cfg["level_code"]
                break
        # 兜底：最低等级（min_points 最小，即列表末尾）
        if eligible_level is None:
            eligible_level = configs[-1]["level_code"]

        # 查当前等级（customers 表，字段不确定时返回 None）
        from_level: Optional[str] = None
        try:
            cur_row = await db.execute(
                text("SELECT level FROM customers WHERE id = :mid AND tenant_id = :tid"),
                {"mid": member_id, "tid": x_tenant_id},
            )
            cur_record = cur_row.fetchone()
            if cur_record:
                from_level = cur_record[0]
        except SQLAlchemyError:
            from_level = None

        upgraded = eligible_level != from_level
        if upgraded:
            trigger_type = "points_upgrade"
            # 更新 customers 等级
            try:
                await db.execute(
                    text("UPDATE customers SET level = :new_level WHERE id = :mid AND tenant_id = :tid"),
                    {"new_level": eligible_level, "mid": member_id, "tid": x_tenant_id},
                )
            except SQLAlchemyError:
                pass  # customers 表字段可能不存在，容错处理

            # 写升降级历史
            await db.execute(
                text(
                    "INSERT INTO member_level_history "
                    "(tenant_id, member_id, from_level, to_level, trigger_type, "
                    "trigger_value, note) "
                    "VALUES (:tid, :mid, :from_l, :to_l, :ttype, :tval, :note)"
                ),
                {
                    "tid": x_tenant_id,
                    "mid": member_id,
                    "from_l": from_level,
                    "to_l": eligible_level,
                    "ttype": trigger_type,
                    "tval": current_points,
                    "note": f"系统自动检查: 积分{current_points}, 年消费{current_annual_spend_fen}分",
                },
            )
            await db.commit()
            logger.info(
                "member_level_changed",
                member_id=member_id,
                from_level=from_level,
                to_level=eligible_level,
            )

        return {
            "ok": True,
            "data": {
                "upgraded": upgraded,
                "from_level": from_level,
                "to_level": eligible_level,
                "current_points": current_points,
                "current_annual_spend_fen": current_annual_spend_fen,
            },
        }
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("check_upgrade_error", member_id=member_id, error=str(exc))
        raise HTTPException(status_code=500, detail="升降级检查失败")


@router.get("/api/v1/members/{member_id}/level-history")
async def get_level_history(
    member_id: str,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict:
    """获取最近10条升降级记录。"""
    try:
        result = await db.execute(
            text(
                "SELECT id, member_id, from_level, to_level, trigger_type, "
                "trigger_value, note, created_at "
                "FROM member_level_history "
                "WHERE tenant_id = :tid AND member_id = :mid "
                "ORDER BY created_at DESC LIMIT 10"
            ),
            {"tid": x_tenant_id, "mid": member_id},
        )
        rows = result.mappings().all()
        items = [
            {
                **dict(row),
                "id": str(row["id"]),
                "member_id": str(row["member_id"]),
                "trigger_value": int(row["trigger_value"]) if row["trigger_value"] is not None else None,
                "created_at": row["created_at"].isoformat(),
            }
            for row in rows
        ]
        return {"ok": True, "data": {"items": items, "total": len(items)}}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error("get_level_history_error", member_id=member_id, error=str(exc))
        raise HTTPException(status_code=500, detail="查询升降级历史失败")


# ─── 积分入账端点 ─────────────────────────────────────────────────────────────


@router.post("/api/v1/members/{member_id}/points/earn")
async def earn_points(
    member_id: str,
    body: EarnPointsRequest,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict:
    """积分入账：查规则 → 计算积分 → UPSERT 余额。"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header 必填")
    try:
        today = date.today()
        # 查适用积分规则
        rules_result = await db.execute(
            text(
                "SELECT points_per_100fen, fixed_points, multiplier "
                "FROM points_rules "
                "WHERE tenant_id = :tid AND earn_type = :etype "
                "AND is_active = TRUE AND is_deleted = FALSE "
                "AND (valid_from IS NULL OR valid_from <= :today) "
                "AND (valid_until IS NULL OR valid_until >= :today) "
                "LIMIT 1"
            ),
            {"tid": x_tenant_id, "etype": body.earn_type, "today": today},
        )
        rule = rules_result.mappings().fetchone()

        if rule:
            if body.earn_type == "consumption" and body.amount_fen is not None:
                base = (body.amount_fen / 100) * float(rule["points_per_100fen"])
                earned_points = int(base * float(rule["multiplier"]))
            else:
                earned_points = int(float(rule["fixed_points"]) * float(rule["multiplier"]))
        else:
            # 无规则时使用默认逻辑
            if body.earn_type == "consumption" and body.amount_fen:
                earned_points = max(1, body.amount_fen // 100)
            elif body.earn_type == "signup":
                earned_points = 100
            elif body.earn_type == "birthday":
                earned_points = 200
            elif body.earn_type == "checkin":
                earned_points = 5
            else:
                earned_points = 0

        # UPSERT 积分余额
        upsert_result = await db.execute(
            text(
                "INSERT INTO member_points_balance (tenant_id, member_id, points) "
                "VALUES (:tid, :mid, :pts) "
                "ON CONFLICT (tenant_id, member_id) "
                "DO UPDATE SET points = member_points_balance.points + :pts, "
                "updated_at = NOW() "
                "RETURNING points"
            ),
            {"tid": x_tenant_id, "mid": member_id, "pts": earned_points},
        )
        total_row = upsert_result.fetchone()
        total_points: int = total_row[0] if total_row else earned_points
        await db.commit()

        logger.info(
            "points_earned",
            member_id=member_id,
            earn_type=body.earn_type,
            earned=earned_points,
            total=total_points,
        )
        return {
            "ok": True,
            "data": {
                "earned_points": earned_points,
                "total_points": total_points,
            },
        }
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("earn_points_error", member_id=member_id, error=str(exc))
        raise HTTPException(status_code=500, detail="积分入账失败")


# ─── 积分规则端点 ─────────────────────────────────────────────────────────────


@router.get("/api/v1/member/points-rules")
async def list_points_rules(
    store_id: Optional[str] = Query(None, description="门店ID，不传则返回品牌通用规则"),
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict:
    """返回积分规则列表，支持 store_id 过滤。"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header 必填")
    try:
        if store_id:
            result = await db.execute(
                text(
                    "SELECT id, tenant_id, store_id, rule_name, earn_type, "
                    "points_per_100fen, fixed_points, multiplier, "
                    "valid_from, valid_until, is_active, created_at, updated_at "
                    "FROM points_rules "
                    "WHERE tenant_id = :tid AND is_deleted = FALSE "
                    "AND (store_id IS NULL OR store_id = :sid)"
                ),
                {"tid": x_tenant_id, "sid": store_id},
            )
        else:
            result = await db.execute(
                text(
                    "SELECT id, tenant_id, store_id, rule_name, earn_type, "
                    "points_per_100fen, fixed_points, multiplier, "
                    "valid_from, valid_until, is_active, created_at, updated_at "
                    "FROM points_rules "
                    "WHERE tenant_id = :tid AND is_deleted = FALSE AND store_id IS NULL"
                ),
                {"tid": x_tenant_id},
            )
        rows = result.mappings().all()
        items = [
            {
                **dict(row),
                "id": str(row["id"]),
                "tenant_id": str(row["tenant_id"]),
                "store_id": str(row["store_id"]) if row["store_id"] else None,
                "points_per_100fen": float(row["points_per_100fen"]),
                "multiplier": float(row["multiplier"]),
                "valid_from": row["valid_from"].isoformat() if row["valid_from"] else None,
                "valid_to": row["valid_until"].isoformat() if row["valid_until"] else None,
                "created_at": row["created_at"].isoformat(),
                "updated_at": row["updated_at"].isoformat(),
            }
            for row in rows
        ]
        return {"ok": True, "data": {"items": items, "total": len(items)}}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error("list_points_rules_error", error=str(exc))
        raise HTTPException(status_code=500, detail="查询积分规则失败")


@router.post("/api/v1/member/points-rules")
async def create_points_rule(
    body: PointsRuleCreate,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> dict:
    """创建积分规则（管理员操作）。"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header 必填")
    try:
        result = await db.execute(
            text(
                "INSERT INTO points_rules "
                "(tenant_id, store_id, rule_name, earn_type, points_per_100fen, "
                "fixed_points, multiplier, valid_from, valid_until, is_active) "
                "VALUES (:tid, :sid, :name, :etype, :p100, :fp, :mult, :vf, :vu, :active) "
                "RETURNING id, tenant_id, store_id, rule_name, earn_type, "
                "points_per_100fen, fixed_points, multiplier, "
                "valid_from, valid_until, is_active, created_at, updated_at"
            ),
            {
                "tid": x_tenant_id,
                "sid": body.store_id,
                "name": body.rule_name,
                "etype": body.earn_type,
                "p100": body.points_per_100fen,
                "fp": body.fixed_points,
                "mult": body.multiplier,
                "vf": body.valid_from,
                "vu": body.valid_to,
                "active": body.is_active,
            },
        )
        row = result.mappings().one()
        await db.commit()
        new_rule = {
            **dict(row),
            "id": str(row["id"]),
            "tenant_id": str(row["tenant_id"]),
            "store_id": str(row["store_id"]) if row["store_id"] else None,
            "points_per_100fen": float(row["points_per_100fen"]),
            "multiplier": float(row["multiplier"]),
            "valid_from": row["valid_from"].isoformat() if row["valid_from"] else None,
            "valid_to": row["valid_until"].isoformat() if row["valid_until"] else None,
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
        }
        logger.info("points_rule_created", tenant_id=x_tenant_id, earn_type=body.earn_type)
        return {"ok": True, "data": new_rule}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("create_points_rule_error", error=str(exc))
        raise HTTPException(status_code=500, detail="创建积分规则失败")
