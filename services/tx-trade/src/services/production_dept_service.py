"""出品部门（档口）配置管理服务

负责：
1. 档口 CRUD（创建/查询/更新/删除）
2. 菜品-档口映射管理（单条/批量设置）
3. 档口查询（按 store_id / kds_device_id）

业务规则：
  - 同一租户+门店下，dept_code 唯一
  - 删除档口前必须先解绑所有菜品映射
  - 每道菜在同一租户下只允许有一个 is_primary=True 的映射
"""

import uuid
from typing import Optional

import structlog
from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.production_dept import DishDeptMapping, ProductionDept

logger = structlog.get_logger()


# ─── 出品部门 CRUD ───


async def create_production_dept(
    tenant_id: str,
    brand_id: str,
    store_id: Optional[str],
    dept_name: str,
    dept_code: str,
    printer_address: Optional[str] = None,
    printer_type: str = "network",
    kds_device_id: Optional[str] = None,
    display_color: str = "blue",
    fixed_fee_type: Optional[str] = None,
    default_timeout_minutes: int = 15,
    sort_order: int = 0,
    db: AsyncSession = None,
) -> ProductionDept:
    """创建出品部门（档口）。

    Args:
        tenant_id: 租户ID
        brand_id: 品牌ID
        store_id: 门店ID（None=品牌级通用）
        dept_name: 档口名称，如"凉菜档"
        dept_code: 档口编码，如"cold"
        printer_address: 打印机地址 host:port
        printer_type: 打印机类型 network/usb/bluetooth
        kds_device_id: KDS设备标识
        display_color: KDS颜色标识
        fixed_fee_type: 固定费用类型
        default_timeout_minutes: 默认出品时限
        sort_order: 排序序号
        db: 数据库会话

    Returns:
        创建好的 ProductionDept 实例

    Raises:
        ValueError: dept_code 已存在（同租户+门店下唯一）
    """
    tid = uuid.UUID(tenant_id)
    bid = uuid.UUID(brand_id)
    sid = uuid.UUID(store_id) if store_id else None

    log = logger.bind(tenant_id=tenant_id, dept_code=dept_code, store_id=store_id)

    # 检查 dept_code 唯一性
    existing_stmt = select(ProductionDept).where(
        and_(
            ProductionDept.tenant_id == tid,
            ProductionDept.dept_code == dept_code,
            ProductionDept.store_id == sid,
            ProductionDept.is_deleted == False,  # noqa: E712
        )
    )
    existing = (await db.execute(existing_stmt)).scalar_one_or_none()
    if existing is not None:
        raise ValueError(f"档口编码 '{dept_code}' 在该门店下已存在")

    dept = ProductionDept(
        tenant_id=tid,
        brand_id=bid,
        store_id=sid,
        dept_name=dept_name,
        dept_code=dept_code,
        printer_address=printer_address,
        printer_type=printer_type,
        kds_device_id=kds_device_id,
        display_color=display_color,
        fixed_fee_type=fixed_fee_type,
        default_timeout_minutes=default_timeout_minutes,
        sort_order=sort_order,
        is_active=True,
    )
    db.add(dept)
    await db.flush()
    await db.refresh(dept)

    log.info("production_dept.created", dept_id=str(dept.id), dept_name=dept_name)
    return dept


async def get_production_depts(
    tenant_id: str,
    store_id: Optional[str] = None,
    brand_id: Optional[str] = None,
    active_only: bool = True,
    db: AsyncSession = None,
) -> list[ProductionDept]:
    """查询出品部门列表。

    Args:
        tenant_id: 租户ID
        store_id: 按门店过滤（None=返回品牌级+门店级所有档口）
        brand_id: 按品牌过滤
        active_only: 只返回启用的档口
        db: 数据库会话

    Returns:
        按 sort_order 排序的档口列表
    """
    tid = uuid.UUID(tenant_id)

    conditions = [
        ProductionDept.tenant_id == tid,
        ProductionDept.is_deleted == False,  # noqa: E712
    ]

    if active_only:
        conditions.append(ProductionDept.is_active == True)  # noqa: E712

    if store_id:
        sid = uuid.UUID(store_id)
        # 返回门店专属档口 + 品牌级通用档口（store_id IS NULL）
        conditions.append(
            (ProductionDept.store_id == sid) | (ProductionDept.store_id == None)  # noqa: E711
        )

    if brand_id:
        bid = uuid.UUID(brand_id)
        conditions.append(ProductionDept.brand_id == bid)

    stmt = (
        select(ProductionDept)
        .where(and_(*conditions))
        .order_by(
            ProductionDept.sort_order.asc(),
            ProductionDept.created_at.asc(),
        )
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_production_dept_by_id(
    dept_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> Optional[ProductionDept]:
    """按ID查询单个档口。"""
    tid = uuid.UUID(tenant_id)
    did = uuid.UUID(dept_id)

    stmt = select(ProductionDept).where(
        and_(
            ProductionDept.id == did,
            ProductionDept.tenant_id == tid,
            ProductionDept.is_deleted == False,  # noqa: E712
        )
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_dept_by_kds_device_id(
    kds_device_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> Optional[ProductionDept]:
    """按KDS设备ID查询档口（KDS平板启动时用于自我识别）。"""
    tid = uuid.UUID(tenant_id)

    stmt = select(ProductionDept).where(
        and_(
            ProductionDept.tenant_id == tid,
            ProductionDept.kds_device_id == kds_device_id,
            ProductionDept.is_active == True,  # noqa: E712
            ProductionDept.is_deleted == False,  # noqa: E712
        )
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def update_production_dept(
    dept_id: str,
    tenant_id: str,
    db: AsyncSession,
    *,
    dept_name: Optional[str] = None,
    dept_code: Optional[str] = None,
    printer_address: Optional[str] = None,
    printer_type: Optional[str] = None,
    kds_device_id: Optional[str] = None,
    display_color: Optional[str] = None,
    fixed_fee_type: Optional[str] = None,
    default_timeout_minutes: Optional[int] = None,
    sort_order: Optional[int] = None,
    is_active: Optional[bool] = None,
) -> ProductionDept:
    """更新出品部门配置。

    Returns:
        更新后的档口实例

    Raises:
        LookupError: 档口不存在
        ValueError: dept_code 冲突
    """
    dept = await get_production_dept_by_id(dept_id, tenant_id, db)
    if dept is None:
        raise LookupError(f"档口 {dept_id} 不存在")

    log = logger.bind(dept_id=dept_id, tenant_id=tenant_id)

    # 如果修改 dept_code，检查唯一性
    if dept_code is not None and dept_code != dept.dept_code:
        tid = uuid.UUID(tenant_id)
        dup_stmt = select(ProductionDept).where(
            and_(
                ProductionDept.tenant_id == tid,
                ProductionDept.dept_code == dept_code,
                ProductionDept.store_id == dept.store_id,
                ProductionDept.id != uuid.UUID(dept_id),
                ProductionDept.is_deleted == False,  # noqa: E712
            )
        )
        dup = (await db.execute(dup_stmt)).scalar_one_or_none()
        if dup is not None:
            raise ValueError(f"档口编码 '{dept_code}' 已被其他档口使用")
        dept.dept_code = dept_code

    if dept_name is not None:
        dept.dept_name = dept_name
    if printer_address is not None:
        dept.printer_address = printer_address
    if printer_type is not None:
        dept.printer_type = printer_type
    if kds_device_id is not None:
        dept.kds_device_id = kds_device_id
    if display_color is not None:
        dept.display_color = display_color
    if fixed_fee_type is not None:
        dept.fixed_fee_type = fixed_fee_type
    if default_timeout_minutes is not None:
        dept.default_timeout_minutes = default_timeout_minutes
    if sort_order is not None:
        dept.sort_order = sort_order
    if is_active is not None:
        dept.is_active = is_active

    await db.flush()
    await db.refresh(dept)

    log.info(
        "production_dept.updated",
        dept_name=dept.dept_name,
        kds_device_id=dept.kds_device_id,
        printer_address=dept.printer_address,
    )
    return dept


async def delete_production_dept(
    dept_id: str,
    tenant_id: str,
    db: AsyncSession,
    force: bool = False,
) -> None:
    """软删除出品部门。

    Args:
        dept_id: 档口ID
        tenant_id: 租户ID
        db: 数据库会话
        force: 强制删除（会先解绑所有菜品映射）

    Raises:
        LookupError: 档口不存在
        RuntimeError: 档口下还有菜品映射且 force=False
    """
    dept = await get_production_dept_by_id(dept_id, tenant_id, db)
    if dept is None:
        raise LookupError(f"档口 {dept_id} 不存在")

    tid = uuid.UUID(tenant_id)
    did = uuid.UUID(dept_id)

    # 检查是否有关联菜品映射
    mapping_count_stmt = (
        select(func.count())
        .select_from(DishDeptMapping)
        .where(
            and_(
                DishDeptMapping.tenant_id == tid,
                DishDeptMapping.production_dept_id == did,
                DishDeptMapping.is_deleted == False,  # noqa: E712
            )
        )
    )
    mapping_count = (await db.execute(mapping_count_stmt)).scalar() or 0

    if mapping_count > 0 and not force:
        raise RuntimeError(f"档口下还有 {mapping_count} 条菜品映射，请先解绑菜品或使用 force=True")

    if force and mapping_count > 0:
        # 软删除所有菜品映射
        await db.execute(
            update(DishDeptMapping)
            .where(
                and_(
                    DishDeptMapping.tenant_id == tid,
                    DishDeptMapping.production_dept_id == did,
                )
            )
            .values(is_deleted=True)
        )
        logger.bind(dept_id=dept_id).info("production_dept.force_unbind_dishes", count=mapping_count)

    dept.is_deleted = True
    await db.flush()

    logger.bind(dept_id=dept_id, tenant_id=tenant_id).info("production_dept.deleted")


# ─── 菜品-档口映射管理 ───


async def set_dish_dept_mapping(
    tenant_id: str,
    dish_id: str,
    dept_id: str,
    db: AsyncSession,
    is_primary: bool = True,
    printer_id: Optional[str] = None,
) -> DishDeptMapping:
    """设置菜品所属档口。

    如果该菜品已有映射，则更新；否则新建。
    当 is_primary=True 时，会先将同一菜品的其他映射设为 is_primary=False。

    Returns:
        创建或更新后的 DishDeptMapping 实例

    Raises:
        LookupError: 档口不存在
    """
    tid = uuid.UUID(tenant_id)
    dish_uuid = uuid.UUID(dish_id)
    dept_uuid = uuid.UUID(dept_id)

    # 验证档口存在
    dept = await get_production_dept_by_id(dept_id, tenant_id, db)
    if dept is None:
        raise LookupError(f"档口 {dept_id} 不存在")

    log = logger.bind(tenant_id=tenant_id, dish_id=dish_id, dept_id=dept_id)

    # 查找是否已有该菜品对该档口的映射
    existing_stmt = select(DishDeptMapping).where(
        and_(
            DishDeptMapping.tenant_id == tid,
            DishDeptMapping.dish_id == dish_uuid,
            DishDeptMapping.production_dept_id == dept_uuid,
            DishDeptMapping.is_deleted == False,  # noqa: E712
        )
    )
    mapping = (await db.execute(existing_stmt)).scalar_one_or_none()

    if is_primary:
        # 将同一菜品的其他主档口映射降级
        await db.execute(
            update(DishDeptMapping)
            .where(
                and_(
                    DishDeptMapping.tenant_id == tid,
                    DishDeptMapping.dish_id == dish_uuid,
                    DishDeptMapping.production_dept_id != dept_uuid,
                    DishDeptMapping.is_primary == True,  # noqa: E712
                    DishDeptMapping.is_deleted == False,  # noqa: E712
                )
            )
            .values(is_primary=False)
        )

    if mapping is not None:
        mapping.is_primary = is_primary
        if printer_id is not None:
            mapping.printer_id = uuid.UUID(printer_id)
        await db.flush()
        await db.refresh(mapping)
        log.info("dish_dept_mapping.updated", is_primary=is_primary)
        return mapping

    # 新建映射
    mapping = DishDeptMapping(
        tenant_id=tid,
        dish_id=dish_uuid,
        production_dept_id=dept_uuid,
        is_primary=is_primary,
        printer_id=uuid.UUID(printer_id) if printer_id else None,
        sort_order=0,
    )
    db.add(mapping)
    await db.flush()
    await db.refresh(mapping)

    log.info("dish_dept_mapping.created", is_primary=is_primary)
    return mapping


async def batch_set_dish_dept_mappings(
    tenant_id: str,
    mappings: list[dict],
    db: AsyncSession,
) -> list[DishDeptMapping]:
    """批量设置菜品所属档口（Excel导入场景）。

    Args:
        tenant_id: 租户ID
        mappings: [{"dish_id": ..., "dept_id": ..., "is_primary": bool}]
        db: 数据库会话

    Returns:
        创建或更新的映射列表

    Raises:
        ValueError: mappings 列表为空
        LookupError: 某个档口不存在
    """
    if not mappings:
        raise ValueError("mappings 列表不能为空")

    results = []
    for item in mappings:
        mapping = await set_dish_dept_mapping(
            tenant_id=tenant_id,
            dish_id=item["dish_id"],
            dept_id=item["dept_id"],
            db=db,
            is_primary=item.get("is_primary", True),
            printer_id=item.get("printer_id"),
        )
        results.append(mapping)

    logger.bind(tenant_id=tenant_id).info("dish_dept_mapping.batch_set", count=len(results))
    return results


async def get_dish_dept_mapping(
    tenant_id: str,
    dish_id: str,
    db: AsyncSession,
    primary_only: bool = True,
) -> Optional[DishDeptMapping]:
    """查询菜品所属档口。

    Args:
        primary_only: True=只返回主档口映射；False=返回第一个匹配
    """
    tid = uuid.UUID(tenant_id)
    dish_uuid = uuid.UUID(dish_id)

    conditions = [
        DishDeptMapping.tenant_id == tid,
        DishDeptMapping.dish_id == dish_uuid,
        DishDeptMapping.is_deleted == False,  # noqa: E712
    ]
    if primary_only:
        conditions.append(DishDeptMapping.is_primary == True)  # noqa: E712

    stmt = select(DishDeptMapping).where(and_(*conditions)).limit(1)
    return (await db.execute(stmt)).scalar_one_or_none()


async def remove_dish_dept_mapping(
    tenant_id: str,
    dish_id: str,
    dept_id: str,
    db: AsyncSession,
) -> None:
    """解除菜品与档口的绑定。

    Raises:
        LookupError: 映射不存在
    """
    tid = uuid.UUID(tenant_id)
    dish_uuid = uuid.UUID(dish_id)
    dept_uuid = uuid.UUID(dept_id)

    stmt = select(DishDeptMapping).where(
        and_(
            DishDeptMapping.tenant_id == tid,
            DishDeptMapping.dish_id == dish_uuid,
            DishDeptMapping.production_dept_id == dept_uuid,
            DishDeptMapping.is_deleted == False,  # noqa: E712
        )
    )
    mapping = (await db.execute(stmt)).scalar_one_or_none()
    if mapping is None:
        raise LookupError(f"菜品 {dish_id} 与档口 {dept_id} 的映射不存在")

    mapping.is_deleted = True
    await db.flush()

    logger.bind(tenant_id=tenant_id, dish_id=dish_id, dept_id=dept_id).info("dish_dept_mapping.removed")


async def list_dish_mappings_for_dept(
    tenant_id: str,
    dept_id: str,
    db: AsyncSession,
    page: int = 1,
    size: int = 50,
) -> tuple[list[DishDeptMapping], int]:
    """查询某档口下所有菜品映射（分页）。

    Returns:
        (mappings, total_count)
    """
    tid = uuid.UUID(tenant_id)
    dept_uuid = uuid.UUID(dept_id)

    base_cond = and_(
        DishDeptMapping.tenant_id == tid,
        DishDeptMapping.production_dept_id == dept_uuid,
        DishDeptMapping.is_deleted == False,  # noqa: E712
    )

    count_stmt = select(func.count()).select_from(DishDeptMapping).where(base_cond)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(DishDeptMapping)
        .where(base_cond)
        .order_by(DishDeptMapping.sort_order.asc(), DishDeptMapping.created_at.asc())
        .offset((page - 1) * size)
        .limit(size)
    )
    items = list((await db.execute(stmt)).scalars().all())

    return items, total
