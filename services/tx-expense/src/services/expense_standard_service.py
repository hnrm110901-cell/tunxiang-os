"""
差标匹配引擎服务
核心能力：
  1. 三维度差标查询（职级 × 城市级别 × 费用类型）
  2. 城市→级别自动映射（支持模糊匹配）
  3. 实时合规检查（提交时调用）
  4. 差标 CRUD（管理端配置）
  5. 连锁品牌差标继承（新门店自动复制同品牌差标）

金额约定：所有金额参数和存储均为分(fen)。
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.expense_enums import CityTier, TravelExpenseType
from ..models.expense_standard import ExpenseStandard, StandardCityTier

logger = structlog.get_logger(__name__)

# 模块级城市级别缓存：key=(tenant_id, city_name) → tier str
# 避免重复查询 DB，check_compliance <100ms 目标关键
_city_tier_cache: dict[tuple[str, str], str] = {}


def _today() -> date:
    return datetime.now(tz=timezone.utc).date()


# ─────────────────────────────────────────────────────────────────────────────
# 城市→级别映射
# ─────────────────────────────────────────────────────────────────────────────

async def get_city_tier(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    city_name: str,
) -> str:
    """查询城市对应的级别（tier1/tier2/tier3/other）。

    查询策略：
      1. 先查模块级内存缓存（避免 DB 重复查询）
      2. 精确匹配优先（city_name = city_name）
      3. 模糊匹配次之（city_name LIKE %city_name%）
      4. 无匹配返回 CityTier.TIER3（保守默认，宁可宽松不误拦）

    缓存 key: (tenant_id_str, city_name)
    """
    cache_key = (str(tenant_id), city_name)
    if cache_key in _city_tier_cache:
        return _city_tier_cache[cache_key]

    # 精确匹配：city_name 完全相等
    exact_stmt = (
        select(StandardCityTier)
        .where(
            StandardCityTier.tenant_id == tenant_id,
            StandardCityTier.city_name == city_name,
        )
        .limit(1)
    )
    result = await db.execute(exact_stmt)
    row = result.scalar_one_or_none()

    if row is None:
        # 模糊匹配：LIKE %city_name%
        from sqlalchemy import func
        fuzzy_stmt = (
            select(StandardCityTier)
            .where(
                StandardCityTier.tenant_id == tenant_id,
                StandardCityTier.city_name.like(f"%{city_name}%"),
            )
            # 精确度：名称更短的更优先（更具体）
            .order_by(func.length(StandardCityTier.city_name).asc())
            .limit(1)
        )
        result = await db.execute(fuzzy_stmt)
        row = result.scalar_one_or_none()

    tier = row.tier if row is not None else CityTier.TIER3.value

    _city_tier_cache[cache_key] = tier
    return tier


# ─────────────────────────────────────────────────────────────────────────────
# 三维度差标查询
# ─────────────────────────────────────────────────────────────────────────────

async def find_standard(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    brand_id: uuid.UUID,
    staff_level: str,
    city_tier: str,
    expense_type: str,
) -> Optional[ExpenseStandard]:
    """三维度精确查询差标规则，支持降级匹配。

    精确查询：brand_id + staff_level + city_tier + expense_type + is_active=True
    有效期过滤：effective_from <= today，effective_to IS NULL OR effective_to >= today
    优先返回有 effective_to 限制的记录（更具体的规则优先，如临时上调差标）

    无精确匹配时降级：
      1. 相同职级 + 相同城市级别 + OTHER_TRAVEL（宽松类型兜底）
      2. 相同职级 + OTHER 城市   + 相同费用类型（城市兜底）
      3. 返回 None（无差标配置）
    """
    today = _today()

    def _base_where(
        sl: str,
        ct: str,
        et: str,
    ):
        return [
            ExpenseStandard.tenant_id == tenant_id,
            ExpenseStandard.brand_id == brand_id,
            ExpenseStandard.staff_level == sl,
            ExpenseStandard.city_tier == ct,
            ExpenseStandard.expense_type == et,
            ExpenseStandard.is_active == True,  # noqa: E712
            ExpenseStandard.effective_from <= today,
        ]

    async def _query(sl: str, ct: str, et: str) -> Optional[ExpenseStandard]:
        from sqlalchemy import or_, and_
        where = _base_where(sl, ct, et)
        # effective_to IS NULL（长期有效）或 effective_to >= today
        where.append(
            or_(
                ExpenseStandard.effective_to.is_(None),
                ExpenseStandard.effective_to >= today,
            )
        )
        stmt = (
            select(ExpenseStandard)
            .where(*where)
            # 有 effective_to 的记录排在前（更具体），再按 effective_from 倒序
            .order_by(
                ExpenseStandard.effective_to.asc().nulls_last(),
                ExpenseStandard.effective_from.desc(),
            )
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    # 第一优先：精确三维匹配
    standard = await _query(staff_level, city_tier, expense_type)
    if standard is not None:
        return standard

    # 降级1：相同职级 + 相同城市 + OTHER_TRAVEL（类型宽松）
    standard = await _query(staff_level, city_tier, TravelExpenseType.OTHER_TRAVEL.value)
    if standard is not None:
        return standard

    # 降级2：相同职级 + OTHER 城市 + 相同费用类型
    standard = await _query(staff_level, CityTier.OTHER.value, expense_type)
    if standard is not None:
        return standard

    return None


# ─────────────────────────────────────────────────────────────────────────────
# 实时合规检查（提交前调用，必须 <100ms）
# ─────────────────────────────────────────────────────────────────────────────

async def check_compliance(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    brand_id: uuid.UUID,
    staff_level: str,
    destination_city: str,
    expense_type: str,
    amount: int,
    is_daily: bool = False,
) -> dict:
    """实时差标合规检查（申请提交时调用）。

    Args:
        amount: 申请金额，单位分(fen)
        is_daily: True=与 daily_limit 比较，False=与 single_limit 比较
                  若 single_limit 为 None，则始终与 daily_limit 比较

    Returns:
        {
            "status": "compliant" | "no_rule" | "over_limit_minor"
                      | "over_limit_major" | "over_limit_critical",
            "compliant": bool,
            "limit": int,          # 适用限额（分），无差标时为 None
            "amount": int,         # 申请金额（分）
            "over_rate": float,    # 超标比例，0.25=超标25%，合规时为0.0
            "city_tier": str,
            "staff_level": str,
            "standard_name": str,  # 差标规则名称，无差标时为 ""
            "message": str,        # 中文说明
            "action_required": str # "none"/"add_note"/"special_approval"/"auto_reject"
        }

    超标分级：
        over_rate <20%  → compliant=True,  action_required="none"（高亮提示即可）
        over_rate 20-50% → compliant=False, action_required="add_note"（必须填写说明）
        over_rate >50%  → compliant=False, action_required="special_approval"（走特殊通道）
    """
    # 1. 城市→级别
    city_tier = await get_city_tier(db, tenant_id, destination_city)

    # 2. 查找差标
    standard = await find_standard(
        db, tenant_id, brand_id, staff_level, city_tier, expense_type
    )

    # 3. 无差标 → 自动通过
    if standard is None:
        return {
            "status": "no_rule",
            "compliant": True,
            "limit": None,
            "amount": amount,
            "over_rate": 0.0,
            "city_tier": city_tier,
            "staff_level": staff_level,
            "standard_name": "",
            "message": "无差标配置，自动通过",
            "action_required": "none",
        }

    # 4. 确定适用限额
    # is_daily=True 或 single_limit 未配置时，用 daily_limit
    if is_daily or standard.single_limit is None:
        limit = standard.daily_limit
        limit_label = "每日限额"
    else:
        limit = standard.single_limit
        limit_label = "单笔限额"

    # 5. 计算超标比例
    over_amount = amount - limit
    if over_amount <= 0:
        # 合规（未超标）
        return {
            "status": "compliant",
            "compliant": True,
            "limit": limit,
            "amount": amount,
            "over_rate": 0.0,
            "city_tier": city_tier,
            "staff_level": staff_level,
            "standard_name": standard.name,
            "message": f"金额符合差标要求（{limit_label} {limit / 100:.0f} 元）",
            "action_required": "none",
        }

    over_rate = round(over_amount / limit, 4)  # 保留4位小数
    over_pct_str = f"{over_rate * 100:.1f}%"
    limit_yuan = limit / 100
    amount_yuan = amount / 100

    if over_rate < 0.20:
        # 轻微超标：合规，仅高亮提示
        return {
            "status": "over_limit_minor",
            "compliant": True,
            "limit": limit,
            "amount": amount,
            "over_rate": over_rate,
            "city_tier": city_tier,
            "staff_level": staff_level,
            "standard_name": standard.name,
            "message": (
                f"金额超出{limit_label}（{limit_yuan:.0f}元）{over_pct_str}，"
                "轻微超标，请确认金额无误"
            ),
            "action_required": "none",
        }
    elif over_rate <= 0.50:
        # 中度超标：需填写说明
        return {
            "status": "over_limit_major",
            "compliant": False,
            "limit": limit,
            "amount": amount,
            "over_rate": over_rate,
            "city_tier": city_tier,
            "staff_level": staff_level,
            "standard_name": standard.name,
            "message": (
                f"金额超出{limit_label}（{limit_yuan:.0f}元）{over_pct_str}，"
                "请在备注中填写超标说明"
            ),
            "action_required": "add_note",
        }
    else:
        # 严重超标：需走特殊审批通道
        return {
            "status": "over_limit_critical",
            "compliant": False,
            "limit": limit,
            "amount": amount,
            "over_rate": over_rate,
            "city_tier": city_tier,
            "staff_level": staff_level,
            "standard_name": standard.name,
            "message": (
                f"金额严重超出{limit_label}（{limit_yuan:.0f}元）{over_pct_str}，"
                f"申请金额 {amount_yuan:.0f} 元，需走特殊审批通道"
            ),
            "action_required": "special_approval",
        }


# ─────────────────────────────────────────────────────────────────────────────
# 差标 CRUD（管理端）
# ─────────────────────────────────────────────────────────────────────────────

async def create_standard(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    brand_id: uuid.UUID,
    name: str,
    staff_level: str,
    city_tier: str,
    expense_type: str,
    daily_limit: int,
    single_limit: Optional[int] = None,
    notes: Optional[str] = None,
    effective_from: Optional[date] = None,
) -> ExpenseStandard:
    """创建差标规则（版本化，不硬删除旧规则）。

    若同维度已有 is_active=True 的规则，先将其 effective_to 设为今天（软关闭），
    再创建新规则，实现版本化管理。

    Args:
        daily_limit:  每日限额，单位分(fen)
        single_limit: 单笔限额，单位分(fen)，None=不限单笔
        effective_from: 生效日期，默认为今天
    """
    today = _today()
    eff_from = effective_from or today

    log = logger.bind(
        tenant_id=str(tenant_id),
        brand_id=str(brand_id),
        staff_level=staff_level,
        city_tier=city_tier,
        expense_type=expense_type,
    )

    try:
        # 查找同维度已有的活跃规则
        from sqlalchemy import or_
        existing_stmt = (
            select(ExpenseStandard)
            .where(
                ExpenseStandard.tenant_id == tenant_id,
                ExpenseStandard.brand_id == brand_id,
                ExpenseStandard.staff_level == staff_level,
                ExpenseStandard.city_tier == city_tier,
                ExpenseStandard.expense_type == expense_type,
                ExpenseStandard.is_active == True,  # noqa: E712
                or_(
                    ExpenseStandard.effective_to.is_(None),
                    ExpenseStandard.effective_to >= today,
                ),
            )
        )
        existing_result = await db.execute(existing_stmt)
        existing_rules = list(existing_result.scalars().all())

        # 软关闭旧规则（设置 effective_to = 今天）
        for old_rule in existing_rules:
            old_rule.effective_to = today
            log.info(
                "expense_standard_superseded",
                old_rule_id=str(old_rule.id),
                old_rule_name=old_rule.name,
            )

        await db.flush()

        # 创建新规则
        new_standard = ExpenseStandard(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            brand_id=brand_id,
            name=name,
            staff_level=staff_level,
            city_tier=city_tier,
            expense_type=expense_type,
            daily_limit=daily_limit,
            single_limit=single_limit,
            notes=notes,
            is_active=True,
            effective_from=eff_from,
            effective_to=None,
        )
        db.add(new_standard)
        await db.flush()

        # 使城市级别缓存失效（差标更新后，缓存仍有效，仅城市映射缓存需清理）
        # 差标自身无需清缓存，城市缓存与差标无关联

        log.info(
            "expense_standard_created",
            standard_id=str(new_standard.id),
            name=name,
            daily_limit=daily_limit,
            superseded_count=len(existing_rules),
        )

        return new_standard

    except SQLAlchemyError as exc:
        log.error("expense_standard_create_db_error", error=str(exc), exc_info=True)
        raise


async def list_standards(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    brand_id: uuid.UUID,
    staff_level: Optional[str] = None,
    city_tier: Optional[str] = None,
    is_active: bool = True,
) -> list[ExpenseStandard]:
    """查询差标规则列表，支持多条件过滤。

    按 staff_level + city_tier + expense_type 排序，便于管理界面展示。
    """
    where = [
        ExpenseStandard.tenant_id == tenant_id,
        ExpenseStandard.brand_id == brand_id,
    ]

    if is_active:
        where.append(ExpenseStandard.is_active == True)  # noqa: E712
    if staff_level is not None:
        where.append(ExpenseStandard.staff_level == staff_level)
    if city_tier is not None:
        where.append(ExpenseStandard.city_tier == city_tier)

    stmt = (
        select(ExpenseStandard)
        .where(*where)
        .order_by(
            ExpenseStandard.staff_level.asc(),
            ExpenseStandard.city_tier.asc(),
            ExpenseStandard.expense_type.asc(),
        )
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ─────────────────────────────────────────────────────────────────────────────
# 连锁品牌差标继承
# ─────────────────────────────────────────────────────────────────────────────

async def init_brand_standards(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    brand_id: uuid.UUID,
    source_brand_id: uuid.UUID,
) -> int:
    """新品牌/新门店入驻时，从 source_brand_id 复制差标配置。

    将 source 品牌所有 is_active=True 的差标规则复制一份，brand_id 改为新品牌。
    复制后的规则保持相同的 staff_level / city_tier / expense_type / limit 配置。

    Returns:
        复制的规则数量（int）
    """
    today = _today()

    # 查询 source 品牌所有活跃差标
    source_stmt = (
        select(ExpenseStandard)
        .where(
            ExpenseStandard.tenant_id == tenant_id,
            ExpenseStandard.brand_id == source_brand_id,
            ExpenseStandard.is_active == True,  # noqa: E712
        )
    )
    source_result = await db.execute(source_stmt)
    source_standards = list(source_result.scalars().all())

    if not source_standards:
        logger.warning(
            "init_brand_standards_no_source",
            tenant_id=str(tenant_id),
            brand_id=str(brand_id),
            source_brand_id=str(source_brand_id),
        )
        return 0

    copied = []
    for src in source_standards:
        new_std = ExpenseStandard(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            brand_id=brand_id,
            name=src.name,
            staff_level=src.staff_level,
            city_tier=src.city_tier,
            expense_type=src.expense_type,
            daily_limit=src.daily_limit,
            single_limit=src.single_limit,
            notes=src.notes,
            is_active=True,
            effective_from=today,
            effective_to=None,
        )
        copied.append(new_std)

    db.add_all(copied)
    await db.flush()

    logger.info(
        "brand_standards_initialized",
        tenant_id=str(tenant_id),
        brand_id=str(brand_id),
        source_brand_id=str(source_brand_id),
        copied_count=len(copied),
    )

    return len(copied)


# ─────────────────────────────────────────────────────────────────────────────
# 餐饮行业默认差标模板
# ─────────────────────────────────────────────────────────────────────────────

async def get_default_standards_template() -> list[dict]:
    """返回餐饮行业推荐差标模板（硬编码业务数据）。

    所有金额单位为分(fen)：1元=100分。
    适用于连锁餐饮品牌首次配置差标时的参考初始值。
    三线城市按二线城市7折计算。
    """
    return [
        # ── 门店员工 ──────────────────────────────────────────────────────
        {"staff_level": "store_staff", "city_tier": "tier1", "expense_type": "accommodation", "daily_limit": 25000},   # 250元
        {"staff_level": "store_staff", "city_tier": "tier1", "expense_type": "meal",          "daily_limit": 6000},    # 60元
        {"staff_level": "store_staff", "city_tier": "tier1", "expense_type": "transport",     "daily_limit": 10000},   # 100元
        {"staff_level": "store_staff", "city_tier": "tier2", "expense_type": "accommodation", "daily_limit": 18000},   # 180元
        {"staff_level": "store_staff", "city_tier": "tier2", "expense_type": "meal",          "daily_limit": 5000},    # 50元
        {"staff_level": "store_staff", "city_tier": "tier2", "expense_type": "transport",     "daily_limit": 8000},    # 80元
        {"staff_level": "store_staff", "city_tier": "tier3", "expense_type": "accommodation", "daily_limit": 12600},   # 126元（≈180×0.7）
        {"staff_level": "store_staff", "city_tier": "tier3", "expense_type": "meal",          "daily_limit": 3500},    # 35元（≈50×0.7）
        {"staff_level": "store_staff", "city_tier": "tier3", "expense_type": "transport",     "daily_limit": 5600},    # 56元（≈80×0.7）

        # ── 店长 ──────────────────────────────────────────────────────────
        {"staff_level": "store_manager", "city_tier": "tier1", "expense_type": "accommodation", "daily_limit": 40000},  # 400元
        {"staff_level": "store_manager", "city_tier": "tier1", "expense_type": "meal",          "daily_limit": 10000},  # 100元
        {"staff_level": "store_manager", "city_tier": "tier1", "expense_type": "transport",     "daily_limit": 20000},  # 200元
        {"staff_level": "store_manager", "city_tier": "tier2", "expense_type": "accommodation", "daily_limit": 30000},  # 300元
        {"staff_level": "store_manager", "city_tier": "tier2", "expense_type": "meal",          "daily_limit": 8000},   # 80元
        {"staff_level": "store_manager", "city_tier": "tier2", "expense_type": "transport",     "daily_limit": 15000},  # 150元
        {"staff_level": "store_manager", "city_tier": "tier3", "expense_type": "accommodation", "daily_limit": 21000},  # 210元（≈300×0.7）
        {"staff_level": "store_manager", "city_tier": "tier3", "expense_type": "meal",          "daily_limit": 5600},   # 56元（≈80×0.7）
        {"staff_level": "store_manager", "city_tier": "tier3", "expense_type": "transport",     "daily_limit": 10500},  # 105元（≈150×0.7）

        # ── 区域经理 ──────────────────────────────────────────────────────
        {"staff_level": "region_manager", "city_tier": "tier1", "expense_type": "accommodation", "daily_limit": 60000},  # 600元
        {"staff_level": "region_manager", "city_tier": "tier1", "expense_type": "meal",          "daily_limit": 15000},  # 150元
        {"staff_level": "region_manager", "city_tier": "tier1", "expense_type": "transport",     "daily_limit": 30000},  # 300元
        {"staff_level": "region_manager", "city_tier": "tier2", "expense_type": "accommodation", "daily_limit": 45000},  # 450元
        {"staff_level": "region_manager", "city_tier": "tier2", "expense_type": "meal",          "daily_limit": 12000},  # 120元
        {"staff_level": "region_manager", "city_tier": "tier2", "expense_type": "transport",     "daily_limit": 20000},  # 200元
        {"staff_level": "region_manager", "city_tier": "tier3", "expense_type": "accommodation", "daily_limit": 31500},  # 315元（≈450×0.7）
        {"staff_level": "region_manager", "city_tier": "tier3", "expense_type": "meal",          "daily_limit": 8400},   # 84元（≈120×0.7）
        {"staff_level": "region_manager", "city_tier": "tier3", "expense_type": "transport",     "daily_limit": 14000},  # 140元（≈200×0.7）

        # ── 品牌运营总监 ──────────────────────────────────────────────────
        {"staff_level": "brand_manager", "city_tier": "tier1", "expense_type": "accommodation", "daily_limit": 80000},  # 800元
        {"staff_level": "brand_manager", "city_tier": "tier1", "expense_type": "meal",          "daily_limit": 20000},  # 200元
        {"staff_level": "brand_manager", "city_tier": "tier1", "expense_type": "transport",     "daily_limit": 40000},  # 400元
        {"staff_level": "brand_manager", "city_tier": "tier2", "expense_type": "accommodation", "daily_limit": 60000},  # 600元
        {"staff_level": "brand_manager", "city_tier": "tier2", "expense_type": "meal",          "daily_limit": 15000},  # 150元
        {"staff_level": "brand_manager", "city_tier": "tier2", "expense_type": "transport",     "daily_limit": 30000},  # 300元
        {"staff_level": "brand_manager", "city_tier": "tier3", "expense_type": "accommodation", "daily_limit": 42000},  # 420元（≈600×0.7）
        {"staff_level": "brand_manager", "city_tier": "tier3", "expense_type": "meal",          "daily_limit": 10500},  # 105元（≈150×0.7）
        {"staff_level": "brand_manager", "city_tier": "tier3", "expense_type": "transport",     "daily_limit": 21000},  # 210元（≈300×0.7）

        # ── 高管（CFO/CEO）────────────────────────────────────────────────
        {"staff_level": "executive", "city_tier": "tier1", "expense_type": "accommodation", "daily_limit": 100000},  # 1000元
        {"staff_level": "executive", "city_tier": "tier1", "expense_type": "meal",          "daily_limit": 30000},   # 300元
        {"staff_level": "executive", "city_tier": "tier1", "expense_type": "transport",     "daily_limit": 60000},   # 600元
        {"staff_level": "executive", "city_tier": "tier2", "expense_type": "accommodation", "daily_limit": 80000},   # 800元
        {"staff_level": "executive", "city_tier": "tier2", "expense_type": "meal",          "daily_limit": 25000},   # 250元
        {"staff_level": "executive", "city_tier": "tier2", "expense_type": "transport",     "daily_limit": 50000},   # 500元
        {"staff_level": "executive", "city_tier": "tier3", "expense_type": "accommodation", "daily_limit": 56000},   # 560元（≈800×0.7）
        {"staff_level": "executive", "city_tier": "tier3", "expense_type": "meal",          "daily_limit": 17500},   # 175元（≈250×0.7）
        {"staff_level": "executive", "city_tier": "tier3", "expense_type": "transport",     "daily_limit": 35000},   # 350元（≈500×0.7）
    ]
