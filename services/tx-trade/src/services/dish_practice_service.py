"""口味做法管理服务 — 菜品做法/忌口/辣度/甜度

品智POS核心需求：每道菜可配置多种做法（如辣度、甜度、忌口），
点餐时选择做法影响价格和配料。

v345 重构：内存存储 → PostgreSQL dish_practices 表读写。
保留 build_customizations() 接口不变。
所有金额单位：分（fen）。
"""

import uuid
from collections import defaultdict

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


# ─── 默认做法模板（seed 到 DB 用） ───

DEFAULT_PRACTICE_TEMPLATES: list[dict] = [
    # 辣度
    {
        "practice_name": "不辣",
        "practice_group": "辣度",
        "additional_price_fen": 0,
        "practice_type": "standard",
        "sort_order": 0,
        "is_default": True,
        "max_quantity": 1,
    },
    {
        "practice_name": "微辣",
        "practice_group": "辣度",
        "additional_price_fen": 0,
        "practice_type": "standard",
        "sort_order": 1,
        "is_default": False,
        "max_quantity": 1,
    },
    {
        "practice_name": "中辣",
        "practice_group": "辣度",
        "additional_price_fen": 0,
        "practice_type": "standard",
        "sort_order": 2,
        "is_default": False,
        "max_quantity": 1,
    },
    {
        "practice_name": "特辣",
        "practice_group": "辣度",
        "additional_price_fen": 200,
        "practice_type": "standard",
        "sort_order": 3,
        "is_default": False,
        "max_quantity": 1,
    },
    # 甜度
    {
        "practice_name": "不加糖",
        "practice_group": "甜度",
        "additional_price_fen": 0,
        "practice_type": "standard",
        "sort_order": 0,
        "is_default": True,
        "max_quantity": 1,
    },
    {
        "practice_name": "半糖",
        "practice_group": "甜度",
        "additional_price_fen": 0,
        "practice_type": "standard",
        "sort_order": 1,
        "is_default": False,
        "max_quantity": 1,
    },
    {
        "practice_name": "全糖",
        "practice_group": "甜度",
        "additional_price_fen": 0,
        "practice_type": "standard",
        "sort_order": 2,
        "is_default": False,
        "max_quantity": 1,
    },
    # 忌口
    {
        "practice_name": "不要香菜",
        "practice_group": "忌口",
        "additional_price_fen": 0,
        "practice_type": "standard",
        "sort_order": 0,
        "is_default": False,
        "max_quantity": 1,
    },
    {
        "practice_name": "不要葱",
        "practice_group": "忌口",
        "additional_price_fen": 0,
        "practice_type": "standard",
        "sort_order": 1,
        "is_default": False,
        "max_quantity": 1,
    },
    {
        "practice_name": "不要蒜",
        "practice_group": "忌口",
        "additional_price_fen": 0,
        "practice_type": "standard",
        "sort_order": 2,
        "is_default": False,
        "max_quantity": 1,
    },
    {
        "practice_name": "不加味精",
        "practice_group": "忌口",
        "additional_price_fen": 0,
        "practice_type": "standard",
        "sort_order": 3,
        "is_default": False,
        "max_quantity": 1,
    },
    # 加料
    {
        "practice_name": "加蛋",
        "practice_group": "加料",
        "additional_price_fen": 200,
        "practice_type": "addon",
        "sort_order": 0,
        "is_default": False,
        "max_quantity": 3,
    },
    {
        "practice_name": "加芝士",
        "practice_group": "加料",
        "additional_price_fen": 300,
        "practice_type": "addon",
        "sort_order": 1,
        "is_default": False,
        "max_quantity": 2,
    },
]


# ─── DB 辅助 ───


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS tenant context"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ─── Service 函数 ───


async def get_dish_practices(
    dish_id: str,
    tenant_id: str,
    db: AsyncSession,
    *,
    include_temporary: bool = True,
) -> list[dict]:
    """获取菜品可选做法列表（从 DB），按 practice_group + sort_order 排序。

    Args:
        dish_id: 菜品ID
        tenant_id: 租户ID
        db: 数据库会话
        include_temporary: 是否包含临时做法（默认True）

    Returns:
        做法列表，每项含 id/practice_name/practice_group/additional_price_fen 等
    """
    await _set_rls(db, tenant_id)

    conditions = """
        tenant_id = :tid::uuid
        AND dish_id = :did::uuid
        AND is_deleted = false
    """
    if not include_temporary:
        conditions += " AND is_temporary = false"

    result = await db.execute(
        text(f"""
            SELECT id, dish_id, practice_name, practice_group,
                   additional_price_fen, is_default, sort_order,
                   is_temporary, practice_type, max_quantity,
                   created_at
            FROM dish_practices
            WHERE {conditions}
            ORDER BY practice_group, sort_order, created_at
        """),
        {"tid": tenant_id, "did": dish_id},
    )
    rows = result.mappings().all()

    practices = [
        {
            "id": str(r["id"]),
            "dish_id": str(r["dish_id"]),
            "practice_name": r["practice_name"],
            "practice_group": r["practice_group"],
            "additional_price_fen": r["additional_price_fen"],
            "is_default": r["is_default"],
            "sort_order": r["sort_order"],
            "is_temporary": r["is_temporary"],
            "practice_type": r["practice_type"],
            "max_quantity": r["max_quantity"],
        }
        for r in rows
    ]

    logger.info(
        "dish_practices_queried",
        dish_id=dish_id,
        count=len(practices),
        tenant_id=tenant_id,
    )
    return practices


async def add_dish_practice(
    dish_id: str,
    practice: dict,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """添加菜品做法（写DB）。

    Args:
        dish_id: 菜品ID
        practice: {
            "practice_name": str,
            "practice_group": str,
            "additional_price_fen": int,
            "is_default": bool,
            "sort_order": int,
            "practice_type": str,  # standard|temporary|addon
            "max_quantity": int,
        }
        tenant_id: 租户ID
        db: 数据库会话

    Returns:
        插入后的做法字典（含id）
    """
    await _set_rls(db, tenant_id)

    price_fen = practice.get("additional_price_fen", 0)
    if price_fen < 0:
        raise ValueError("加价不能为负数")

    practice_id = uuid.uuid4()
    practice_type = practice.get("practice_type", "standard")
    is_temporary = practice_type == "temporary" or practice.get("is_temporary", False)

    await db.execute(
        text("""
            INSERT INTO dish_practices
              (id, tenant_id, dish_id, practice_name, practice_group,
               additional_price_fen, is_default, sort_order,
               is_temporary, practice_type, max_quantity)
            VALUES
              (:id::uuid, :tid::uuid, :did::uuid, :name, :grp,
               :price, :is_def, :sort,
               :is_tmp, :ptype, :max_qty)
        """),
        {
            "id": str(practice_id),
            "tid": tenant_id,
            "did": dish_id,
            "name": practice["practice_name"],
            "grp": practice.get("practice_group", "default"),
            "price": price_fen,
            "is_def": practice.get("is_default", False),
            "sort": practice.get("sort_order", 0),
            "is_tmp": is_temporary,
            "ptype": practice_type,
            "max_qty": practice.get("max_quantity", 1),
        },
    )
    await db.flush()

    result = {
        "id": str(practice_id),
        "dish_id": dish_id,
        "practice_name": practice["practice_name"],
        "practice_group": practice.get("practice_group", "default"),
        "additional_price_fen": price_fen,
        "is_default": practice.get("is_default", False),
        "sort_order": practice.get("sort_order", 0),
        "is_temporary": is_temporary,
        "practice_type": practice_type,
        "max_quantity": practice.get("max_quantity", 1),
    }

    logger.info(
        "dish_practice_added",
        practice_id=str(practice_id),
        dish_id=dish_id,
        name=practice["practice_name"],
        additional_price_fen=price_fen,
        practice_type=practice_type,
        tenant_id=tenant_id,
    )
    return result


async def get_practice_templates(
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, list[dict]]:
    """获取通用做法模板（从DB按practice_group分组）。

    查询 dish_id 为全局模板（dish_id = '00000000-...-000000000000'）的做法记录。
    如果 DB 中无模板数据，返回内存中的默认模板（兼容未 seed 的场景）。

    Returns:
        {"辣度": [...], "甜度": [...], "忌口": [...], "加料": [...]}
    """
    await _set_rls(db, tenant_id)

    # 模板使用全零 dish_id 标识
    template_dish_id = "00000000-0000-0000-0000-000000000000"

    result = await db.execute(
        text("""
            SELECT id, practice_name, practice_group,
                   additional_price_fen, is_default, sort_order,
                   is_temporary, practice_type, max_quantity
            FROM dish_practices
            WHERE tenant_id = :tid::uuid
              AND dish_id = :did::uuid
              AND is_deleted = false
            ORDER BY practice_group, sort_order
        """),
        {"tid": tenant_id, "did": template_dish_id},
    )
    rows = result.mappings().all()

    # 如果DB中有模板，按group分组返回
    if rows:
        groups: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            groups[r["practice_group"]].append(
                {
                    "id": str(r["id"]),
                    "practice_name": r["practice_name"],
                    "practice_group": r["practice_group"],
                    "additional_price_fen": r["additional_price_fen"],
                    "is_default": r["is_default"],
                    "sort_order": r["sort_order"],
                    "practice_type": r["practice_type"],
                    "max_quantity": r["max_quantity"],
                }
            )
        logger.info("practice_templates_queried", source="db", count=len(rows))
        return dict(groups)

    # DB无模板，返回内存默认模板（兼容未 seed 场景）
    groups = defaultdict(list)
    for tpl in DEFAULT_PRACTICE_TEMPLATES:
        groups[tpl["practice_group"]].append(tpl)
    logger.info("practice_templates_queried", source="memory_fallback", count=len(DEFAULT_PRACTICE_TEMPLATES))
    return dict(groups)


async def create_temporary_practice(
    dish_id: str,
    name: str,
    price_fen: int,
    tenant_id: str,
    db: AsyncSession,
    *,
    practice_group: str = "临时做法",
    max_quantity: int = 1,
) -> dict:
    """创建临时做法（有价做法）— 顾客下单时自定义。

    临时做法自动标记 is_temporary=True, practice_type='temporary'。

    Args:
        dish_id: 菜品ID
        name: 做法名称（如"加辣椒酱"）
        price_fen: 加价金额（分），必须 >= 0
        tenant_id: 租户ID
        db: 数据库会话
        practice_group: 分组名（默认"临时做法"）
        max_quantity: 可选数量上限

    Returns:
        创建的临时做法字典
    """
    if price_fen < 0:
        raise ValueError("临时做法加价不能为负数")

    return await add_dish_practice(
        dish_id=dish_id,
        practice={
            "practice_name": name,
            "practice_group": practice_group,
            "additional_price_fen": price_fen,
            "is_default": False,
            "sort_order": 99,
            "practice_type": "temporary",
            "is_temporary": True,
            "max_quantity": max_quantity,
        },
        tenant_id=tenant_id,
        db=db,
    )


async def seed_default_templates(
    tenant_id: str,
    db: AsyncSession,
) -> int:
    """初始化默认做法模板到 DB。

    使用全零 dish_id 作为模板标识。幂等操作 — 已存在则跳过。

    Args:
        tenant_id: 租户ID
        db: 数据库会话

    Returns:
        实际插入的模板数量
    """
    await _set_rls(db, tenant_id)

    template_dish_id = "00000000-0000-0000-0000-000000000000"

    # 检查是否已初始化
    existing = await db.execute(
        text("""
            SELECT count(*) FROM dish_practices
            WHERE tenant_id = :tid::uuid
              AND dish_id = :did::uuid
              AND is_deleted = false
        """),
        {"tid": tenant_id, "did": template_dish_id},
    )
    count = existing.scalar() or 0
    if count > 0:
        logger.info("seed_templates_skipped", tenant_id=tenant_id, existing=count)
        return 0

    # 批量插入
    inserted = 0
    for tpl in DEFAULT_PRACTICE_TEMPLATES:
        practice_id = uuid.uuid4()
        is_temporary = tpl.get("practice_type") == "temporary"
        await db.execute(
            text("""
                INSERT INTO dish_practices
                  (id, tenant_id, dish_id, practice_name, practice_group,
                   additional_price_fen, is_default, sort_order,
                   is_temporary, practice_type, max_quantity)
                VALUES
                  (:id::uuid, :tid::uuid, :did::uuid, :name, :grp,
                   :price, :is_def, :sort,
                   :is_tmp, :ptype, :max_qty)
            """),
            {
                "id": str(practice_id),
                "tid": tenant_id,
                "did": template_dish_id,
                "name": tpl["practice_name"],
                "grp": tpl["practice_group"],
                "price": tpl["additional_price_fen"],
                "is_def": tpl.get("is_default", False),
                "sort": tpl.get("sort_order", 0),
                "is_tmp": is_temporary,
                "ptype": tpl.get("practice_type", "standard"),
                "max_qty": tpl.get("max_quantity", 1),
            },
        )
        inserted += 1

    await db.flush()
    logger.info("seed_templates_done", tenant_id=tenant_id, inserted=inserted)
    return inserted


def build_customizations(
    selected_practices: list[dict],
) -> dict:
    """构建 OrderItem.customizations 字段。

    在 add_item 时调用，将选择的做法转为 customizations JSON。
    支持多份加料场景（quantity 字段）。

    Args:
        selected_practices: [
            {
                "practice_id": "...",           # 或 "id"
                "name": "微辣",                  # 或 "practice_name"
                "additional_price_fen": 0,
                "quantity": 1,                   # 加料份数，默认1
                "materials": [...],              # 可选
            }
        ]

    Returns:
        适合存入 OrderItem.customizations 的 dict：
        {
            "practices": [...],
            "total_extra_price_fen": int,
        }
    """
    total_extra_fen = 0
    practices_out = []

    for p in selected_practices:
        qty = p.get("quantity", 1)
        unit_price = p.get("additional_price_fen", 0)
        line_price = unit_price * qty
        total_extra_fen += line_price

        practices_out.append(
            {
                "practice_id": p.get("practice_id") or p.get("id", ""),
                "name": p.get("name") or p.get("practice_name", ""),
                "additional_price_fen": unit_price,
                "quantity": qty,
                "line_price_fen": line_price,
                "materials": p.get("materials", []),
                "practice_type": p.get("practice_type", "standard"),
                "is_temporary": p.get("is_temporary", False),
            }
        )

    return {
        "practices": practices_out,
        "total_extra_price_fen": total_extra_fen,
    }


def calc_practice_extra_fen(customizations: dict) -> int:
    """从 customizations 字典中提取做法加价总额。

    供 order_service / cashier_engine 在计算 subtotal 时调用。

    Args:
        customizations: OrderItem.customizations JSON

    Returns:
        做法加价总额（分）
    """
    return customizations.get("total_extra_price_fen", 0)
