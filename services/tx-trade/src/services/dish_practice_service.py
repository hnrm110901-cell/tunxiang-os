"""口味做法管理服务 — 菜品做法/忌口/辣度/甜度

品智POS核心需求：每道菜可配置多种做法（如辣度、甜度、忌口），
点餐时选择做法影响价格和配料。

数据模型：内存存储（后续可迁移 DB）。
所有金额单位：分（fen）。
"""
import uuid

import structlog

logger = structlog.get_logger()


# ─── 数据模型 ───


class DishPracticeStore:
    """口味做法内存存储

    结构: { dish_id -> [{ practice_id, name, additional_price_fen, materials }] }
    后续可替换为 PostgreSQL 表。
    """

    _practices: dict[str, list[dict]] = {}  # dish_id -> practices list
    _templates: list[dict] = []  # 通用做法模板（初始化时填充）

    @classmethod
    def _ensure_templates(cls) -> None:
        """确保通用模板已初始化"""
        if cls._templates:
            return
        cls._templates = [
            # 辣度
            {
                "template_id": "tpl-spicy-none",
                "category": "spicy",
                "category_label": "辣度",
                "name": "不辣",
                "additional_price_fen": 0,
                "materials": [],
            },
            {
                "template_id": "tpl-spicy-mild",
                "category": "spicy",
                "category_label": "辣度",
                "name": "微辣",
                "additional_price_fen": 0,
                "materials": [{"name": "干辣椒", "amount": "少许"}],
            },
            {
                "template_id": "tpl-spicy-medium",
                "category": "spicy",
                "category_label": "辣度",
                "name": "中辣",
                "additional_price_fen": 0,
                "materials": [{"name": "干辣椒", "amount": "适量"}],
            },
            {
                "template_id": "tpl-spicy-hot",
                "category": "spicy",
                "category_label": "辣度",
                "name": "特辣",
                "additional_price_fen": 200,
                "materials": [
                    {"name": "干辣椒", "amount": "大量"},
                    {"name": "小米辣", "amount": "适量"},
                ],
            },
            # 甜度
            {
                "template_id": "tpl-sweet-none",
                "category": "sweetness",
                "category_label": "甜度",
                "name": "不加糖",
                "additional_price_fen": 0,
                "materials": [],
            },
            {
                "template_id": "tpl-sweet-half",
                "category": "sweetness",
                "category_label": "甜度",
                "name": "半糖",
                "additional_price_fen": 0,
                "materials": [{"name": "白砂糖", "amount": "少许"}],
            },
            {
                "template_id": "tpl-sweet-full",
                "category": "sweetness",
                "category_label": "甜度",
                "name": "全糖",
                "additional_price_fen": 0,
                "materials": [{"name": "白砂糖", "amount": "标准"}],
            },
            # 忌口
            {
                "template_id": "tpl-avoid-cilantro",
                "category": "avoid",
                "category_label": "忌口",
                "name": "不要香菜",
                "additional_price_fen": 0,
                "materials": [],
            },
            {
                "template_id": "tpl-avoid-green-onion",
                "category": "avoid",
                "category_label": "忌口",
                "name": "不要葱",
                "additional_price_fen": 0,
                "materials": [],
            },
            {
                "template_id": "tpl-avoid-garlic",
                "category": "avoid",
                "category_label": "忌口",
                "name": "不要蒜",
                "additional_price_fen": 0,
                "materials": [],
            },
            {
                "template_id": "tpl-avoid-msg",
                "category": "avoid",
                "category_label": "忌口",
                "name": "不加味精",
                "additional_price_fen": 0,
                "materials": [],
            },
            # 加料
            {
                "template_id": "tpl-extra-egg",
                "category": "extra",
                "category_label": "加料",
                "name": "加蛋",
                "additional_price_fen": 200,
                "materials": [{"name": "鸡蛋", "amount": "1个"}],
            },
            {
                "template_id": "tpl-extra-cheese",
                "category": "extra",
                "category_label": "加料",
                "name": "加芝士",
                "additional_price_fen": 300,
                "materials": [{"name": "芝士片", "amount": "1片"}],
            },
        ]

    @classmethod
    def get_practices(cls, dish_id: str) -> list[dict]:
        return cls._practices.get(dish_id, [])

    @classmethod
    def add_practice(cls, dish_id: str, practice: dict) -> None:
        if dish_id not in cls._practices:
            cls._practices[dish_id] = []
        cls._practices[dish_id].append(practice)

    @classmethod
    def remove_practice(cls, dish_id: str, practice_id: str) -> bool:
        practices = cls._practices.get(dish_id, [])
        for i, p in enumerate(practices):
            if p["practice_id"] == practice_id:
                practices.pop(i)
                return True
        return False

    @classmethod
    def get_templates(cls) -> list[dict]:
        cls._ensure_templates()
        return cls._templates


# ─── Service 函数 ───


async def get_dish_practices(dish_id: str, tenant_id: str) -> list[dict]:
    """获取菜品可选做法列表"""
    practices = DishPracticeStore.get_practices(dish_id)
    logger.info(
        "dish_practices_queried",
        dish_id=dish_id,
        count=len(practices),
        tenant_id=tenant_id,
    )
    return practices


async def add_dish_practice(
    dish_id: str,
    name: str,
    additional_price_fen: int,
    materials: list[dict],
    tenant_id: str,
    category: str = "",
) -> dict:
    """添加菜品做法

    Args:
        dish_id: 菜品ID
        name: 做法名称（如"微辣"、"不要香菜"）
        additional_price_fen: 加价（分），0表示不加价
        materials: 配料调整 [{"name": "辣椒", "amount": "少许"}]
        tenant_id: 租户ID
        category: 做法分类（spicy/sweetness/avoid/extra）
    """
    if additional_price_fen < 0:
        raise ValueError("加价不能为负数")

    practice_id = str(uuid.uuid4())
    practice = {
        "practice_id": practice_id,
        "dish_id": dish_id,
        "name": name,
        "category": category,
        "additional_price_fen": additional_price_fen,
        "materials": materials,
        "tenant_id": tenant_id,
    }
    DishPracticeStore.add_practice(dish_id, practice)

    logger.info(
        "dish_practice_added",
        practice_id=practice_id,
        dish_id=dish_id,
        name=name,
        additional_price_fen=additional_price_fen,
        tenant_id=tenant_id,
    )
    return practice


async def remove_dish_practice(
    dish_id: str,
    practice_id: str,
    tenant_id: str,
) -> bool:
    """删除菜品做法

    Returns:
        True 删除成功, False 未找到
    """
    removed = DishPracticeStore.remove_practice(dish_id, practice_id)
    if removed:
        logger.info(
            "dish_practice_removed",
            practice_id=practice_id,
            dish_id=dish_id,
            tenant_id=tenant_id,
        )
    else:
        logger.warning(
            "dish_practice_not_found",
            practice_id=practice_id,
            dish_id=dish_id,
            tenant_id=tenant_id,
        )
    return removed


async def get_practice_templates() -> list[dict]:
    """获取通用做法模板（辣度/甜度/忌口/加料）

    门店可基于模板快速为菜品配置做法。
    """
    templates = DishPracticeStore.get_templates()
    logger.info("practice_templates_queried", count=len(templates))
    return templates


def build_customizations(
    selected_practices: list[dict],
) -> dict:
    """构建 OrderItem.customizations 字段

    在 add_item 时调用，将选择的做法转为 customizations JSON。

    Args:
        selected_practices: [{"practice_id": "...", "name": "微辣", "additional_price_fen": 0, "materials": [...]}]

    Returns:
        适合存入 OrderItem.customizations 的 dict
    """
    total_extra_fen = sum(p.get("additional_price_fen", 0) for p in selected_practices)
    return {
        "practices": [
            {
                "practice_id": p.get("practice_id", ""),
                "name": p["name"],
                "additional_price_fen": p.get("additional_price_fen", 0),
                "materials": p.get("materials", []),
            }
            for p in selected_practices
        ],
        "total_extra_price_fen": total_extra_fen,
    }
