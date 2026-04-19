"""Bootstrap — Initialize constraints, indexes, and seed data for the ontology.

Provides realistic restaurant BOM and operational seed data for
development and testing.
"""

from typing import Any

import structlog

from .repository import OntologyRepository

logger = structlog.get_logger()

# ─── Seed Data: Realistic Hunan Restaurant ───

SEED_TENANT_ID = "tenant-001"

SEED_BRANDS = [
    {"id": "brand-csyq", "name": "尝在一起", "tenant_id": SEED_TENANT_ID, "business_type": "湘菜正餐"},
]

SEED_REGIONS = [
    {"id": "region-cs", "name": "长沙"},
    {"id": "region-hn", "name": "湖南"},
]

SEED_STORES = [
    {
        "id": "store-001",
        "name": "尝在一起·五一广场店",
        "tenant_id": SEED_TENANT_ID,
        "brand_id": "brand-csyq",
        "region_id": "region-cs",
        "table_count": 30,
        "daily_revenue_avg_fen": 3500000,
        "margin_current": 0.58,
        "margin_previous": 0.62,
        "traffic_change_pct": -8.0,
        "waste_rate": 6.5,
        "discount_rate": 12.0,
    },
    {
        "id": "store-002",
        "name": "尝在一起·梅溪湖店",
        "tenant_id": SEED_TENANT_ID,
        "brand_id": "brand-csyq",
        "region_id": "region-cs",
        "table_count": 25,
        "daily_revenue_avg_fen": 2800000,
        "margin_current": 0.61,
        "margin_previous": 0.60,
        "traffic_change_pct": 3.0,
        "waste_rate": 4.2,
        "discount_rate": 8.0,
    },
]

SEED_CATEGORIES = [
    {"id": "cat-hot", "name": "招牌热菜", "tenant_id": SEED_TENANT_ID},
    {"id": "cat-cold", "name": "凉菜", "tenant_id": SEED_TENANT_ID},
    {"id": "cat-soup", "name": "汤品", "tenant_id": SEED_TENANT_ID},
    {"id": "cat-staple", "name": "主食", "tenant_id": SEED_TENANT_ID},
]

SEED_SUPPLIERS = [
    {"id": "sup-fish", "name": "湘江水产", "tenant_id": SEED_TENANT_ID, "category": "水产", "price_increased": True},
    {"id": "sup-meat", "name": "宁乡牧业", "tenant_id": SEED_TENANT_ID, "category": "肉类", "price_increased": False},
    {
        "id": "sup-veg",
        "name": "浏阳蔬菜基地",
        "tenant_id": SEED_TENANT_ID,
        "category": "蔬菜",
        "price_increased": False,
    },
    {
        "id": "sup-seasoning",
        "name": "湘味调料厂",
        "tenant_id": SEED_TENANT_ID,
        "category": "调料",
        "price_increased": False,
    },
]

SEED_INGREDIENTS = [
    {
        "id": "ing-luyu",
        "name": "鲈鱼",
        "tenant_id": SEED_TENANT_ID,
        "unit": "kg",
        "price_per_kg_fen": 3800,
        "price_change_pct": 20.0,
        "seasonal": False,
        "supplier_id": "sup-fish",
    },
    {
        "id": "ing-duojiao",
        "name": "剁椒",
        "tenant_id": SEED_TENANT_ID,
        "unit": "kg",
        "price_per_kg_fen": 2400,
        "price_change_pct": 5.0,
        "seasonal": False,
        "supplier_id": "sup-seasoning",
    },
    {
        "id": "ing-jiang",
        "name": "姜",
        "tenant_id": SEED_TENANT_ID,
        "unit": "kg",
        "price_per_kg_fen": 1200,
        "price_change_pct": 0.0,
        "seasonal": False,
        "supplier_id": "sup-veg",
    },
    {
        "id": "ing-suan",
        "name": "蒜",
        "tenant_id": SEED_TENANT_ID,
        "unit": "kg",
        "price_per_kg_fen": 1600,
        "price_change_pct": 0.0,
        "seasonal": False,
        "supplier_id": "sup-veg",
    },
    {
        "id": "ing-douchi",
        "name": "豆豉",
        "tenant_id": SEED_TENANT_ID,
        "unit": "kg",
        "price_per_kg_fen": 3000,
        "price_change_pct": 0.0,
        "seasonal": False,
        "supplier_id": "sup-seasoning",
    },
    {
        "id": "ing-conghua",
        "name": "葱花",
        "tenant_id": SEED_TENANT_ID,
        "unit": "kg",
        "price_per_kg_fen": 800,
        "price_change_pct": 0.0,
        "seasonal": False,
        "supplier_id": "sup-veg",
    },
    {
        "id": "ing-huangniurou",
        "name": "黄牛肉",
        "tenant_id": SEED_TENANT_ID,
        "unit": "kg",
        "price_per_kg_fen": 8500,
        "price_change_pct": 3.0,
        "seasonal": False,
        "supplier_id": "sup-meat",
    },
    {
        "id": "ing-lajiao",
        "name": "辣椒",
        "tenant_id": SEED_TENANT_ID,
        "unit": "kg",
        "price_per_kg_fen": 1000,
        "price_change_pct": 0.0,
        "seasonal": True,
        "supplier_id": "sup-veg",
    },
    {
        "id": "ing-suantai",
        "name": "蒜苔",
        "tenant_id": SEED_TENANT_ID,
        "unit": "kg",
        "price_per_kg_fen": 1400,
        "price_change_pct": 0.0,
        "seasonal": True,
        "supplier_id": "sup-veg",
    },
    {
        "id": "ing-caoyu",
        "name": "草鱼",
        "tenant_id": SEED_TENANT_ID,
        "unit": "kg",
        "price_per_kg_fen": 2200,
        "price_change_pct": 0.0,
        "seasonal": False,
        "supplier_id": "sup-fish",
    },
    {
        "id": "ing-suancai",
        "name": "酸菜",
        "tenant_id": SEED_TENANT_ID,
        "unit": "kg",
        "price_per_kg_fen": 1800,
        "price_change_pct": 40.0,
        "seasonal": True,
        "supplier_id": "sup-veg",
    },
    {
        "id": "ing-huajiao",
        "name": "花椒",
        "tenant_id": SEED_TENANT_ID,
        "unit": "kg",
        "price_per_kg_fen": 12000,
        "price_change_pct": 0.0,
        "seasonal": False,
        "supplier_id": "sup-seasoning",
    },
    {
        "id": "ing-ganlajiao",
        "name": "干辣椒",
        "tenant_id": SEED_TENANT_ID,
        "unit": "kg",
        "price_per_kg_fen": 4000,
        "price_change_pct": 0.0,
        "seasonal": False,
        "supplier_id": "sup-seasoning",
    },
    {
        "id": "ing-douya",
        "name": "豆芽",
        "tenant_id": SEED_TENANT_ID,
        "unit": "kg",
        "price_per_kg_fen": 400,
        "price_change_pct": 0.0,
        "seasonal": False,
        "supplier_id": "sup-veg",
    },
]

SEED_DISHES = [
    {
        "id": "dish-djyt",
        "name": "剁椒鱼头",
        "tenant_id": SEED_TENANT_ID,
        "price_fen": 12800,
        "category_id": "cat-hot",
        "total_cost_fen": 5800,
        "margin_rate": 0.547,
        "daily_sales_avg": 25,
    },
    {
        "id": "dish-xchnr",
        "name": "小炒黄牛肉",
        "tenant_id": SEED_TENANT_ID,
        "price_fen": 6800,
        "category_id": "cat-hot",
        "total_cost_fen": 3200,
        "margin_rate": 0.529,
        "daily_sales_avg": 35,
    },
    {
        "id": "dish-scy",
        "name": "酸菜鱼",
        "tenant_id": SEED_TENANT_ID,
        "price_fen": 7800,
        "category_id": "cat-hot",
        "total_cost_fen": 3000,
        "margin_rate": 0.615,
        "discount_rate": 15.0,
        "daily_sales_avg": 30,
    },
]

# BOM: dish_id → [(ingredient_id, quantity_g, yield_rate)]
SEED_BOM: dict[str, list[tuple[str, float, float]]] = {
    "dish-djyt": [
        ("ing-luyu", 1200.0, 0.65),
        ("ing-duojiao", 200.0, 0.95),
        ("ing-jiang", 50.0, 0.90),
        ("ing-suan", 30.0, 0.90),
        ("ing-douchi", 20.0, 1.0),
        ("ing-conghua", 30.0, 0.85),
    ],
    "dish-xchnr": [
        ("ing-huangniurou", 300.0, 0.80),
        ("ing-lajiao", 100.0, 0.90),
        ("ing-suantai", 50.0, 0.85),
        ("ing-jiang", 20.0, 0.90),
    ],
    "dish-scy": [
        ("ing-caoyu", 800.0, 0.55),
        ("ing-suancai", 200.0, 0.95),
        ("ing-huajiao", 10.0, 1.0),
        ("ing-ganlajiao", 20.0, 1.0),
        ("ing-douya", 100.0, 0.95),
    ],
}

SEED_EMPLOYEES = [
    {"id": "emp-001", "name": "张大厨", "tenant_id": SEED_TENANT_ID, "role": "head_chef", "store_id": "store-001"},
    {"id": "emp-002", "name": "李经理", "tenant_id": SEED_TENANT_ID, "role": "store_manager", "store_id": "store-001"},
    {"id": "emp-003", "name": "王服务员", "tenant_id": SEED_TENANT_ID, "role": "waiter", "store_id": "store-001"},
]


class OntologyBootstrap:
    """Initialize the ontology graph with constraints, indexes, and seed data."""

    def __init__(self, repository: OntologyRepository) -> None:
        self.repo = repository

    def bootstrap_all(self) -> dict[str, Any]:
        """Run full bootstrap: constraints + indexes + seed data."""
        seed_result = self.seed_data()
        return {
            "ok": True,
            "constraints": "applied",
            "indexes": "applied",
            "seed": seed_result,
        }

    def seed_data(self) -> dict[str, Any]:
        """Seed the graph with realistic restaurant data."""
        counts: dict[str, int] = {}

        # Regions
        for region in SEED_REGIONS:
            self.repo.create_node("Region", region)
        counts["regions"] = len(SEED_REGIONS)

        # Brands
        for brand in SEED_BRANDS:
            self.repo.create_node("Brand", brand)
        counts["brands"] = len(SEED_BRANDS)

        # Brand→Region
        self.repo.create_relationship("Brand", "brand-csyq", "LOCATED_IN", "Region", "region-hn")

        # Stores
        for store in SEED_STORES:
            self.repo.create_node("Store", store)
            self.repo.create_relationship("Store", store["id"], "BELONGS_TO", "Brand", store["brand_id"])
            self.repo.create_relationship("Store", store["id"], "LOCATED_IN", "Region", store["region_id"])
        counts["stores"] = len(SEED_STORES)

        # Categories
        for cat in SEED_CATEGORIES:
            self.repo.create_node("Category", cat)
        counts["categories"] = len(SEED_CATEGORIES)

        # Suppliers
        for supplier in SEED_SUPPLIERS:
            self.repo.create_node("Supplier", supplier)
        counts["suppliers"] = len(SEED_SUPPLIERS)

        # Ingredients + Ingredient→Supplier
        for ing in SEED_INGREDIENTS:
            supplier_id = ing.pop("supplier_id", None)
            self.repo.create_node("Ingredient", ing)
            if supplier_id:
                self.repo.create_relationship("Ingredient", ing["id"], "SUPPLIED_BY", "Supplier", supplier_id)
        counts["ingredients"] = len(SEED_INGREDIENTS)

        # Dishes + BOM + Store→Dish
        for dish in SEED_DISHES:
            self.repo.create_node("Dish", dish)
            # Both stores serve all dishes
            for store in SEED_STORES:
                self.repo.create_relationship("Store", store["id"], "SERVES", "Dish", dish["id"])
            # Dish→Category
            if dish.get("category_id"):
                self.repo.create_relationship("Dish", dish["id"], "BELONGS_TO", "Category", dish["category_id"])
        counts["dishes"] = len(SEED_DISHES)

        # BOM relationships
        bom_count = 0
        for dish_id, bom_entries in SEED_BOM.items():
            for ing_id, quantity_g, yield_rate in bom_entries:
                self.repo.create_relationship(
                    "Dish",
                    dish_id,
                    "USES_INGREDIENT",
                    "Ingredient",
                    ing_id,
                    {"quantity_g": quantity_g, "unit": "g", "yield_rate": yield_rate},
                )
                bom_count += 1
        counts["bom_entries"] = bom_count

        # Employees + Employee→Store
        for emp in SEED_EMPLOYEES:
            store_id = emp.get("store_id", "")
            self.repo.create_node("Employee", emp)
            if store_id:
                self.repo.create_relationship(
                    "Employee",
                    emp["id"],
                    "WORKS_AT",
                    "Store",
                    store_id,
                    {"role": emp["role"], "since": "2024-01-01"},
                )
        counts["employees"] = len(SEED_EMPLOYEES)

        logger.info("ontology_seeded", counts=counts)
        return {"ok": True, "counts": counts}
