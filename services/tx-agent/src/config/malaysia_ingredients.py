"""Malaysia-specific ingredient catalog for supply chain AI

Contains 20+ commonly used Malaysian ingredients with local names in
Malay (ms), Chinese (zh), and Tamil (ta), supplier data, seasonal price
fluctuations, shelf life, common pack sizes, and halal certification
status.

Used by the inventory prediction service and the agent layer to forecast
ingredient demand and generate purchase recommendations for Malaysian
stores.

All amounts in fen (分) for pricing — 1 fen = 0.01 MYR.
"""

from __future__ import annotations

from typing import Any

# ─────────────────────────────────────────────
# Malaysian Ingredient Catalog
# ─────────────────────────────────────────────

MALAYSIA_INGREDIENTS: dict[str, dict[str, Any]] = {
    "coconut_milk": {
        "local_names": {"ms": "Santan", "zh": "椰浆", "ta": "தேங்காய் பால்"},
        "unit": "ml",
        "typical_suppliers": ["Santan", "Kara", "AYAM BRAND", "Marina"],
        "seasonal_price_fluctuation": {
            "nov-feb": 1.15,
            "mar-may": 1.05,
            "jun-aug": 0.95,
            "sep-oct": 1.0,
        },
        "shelf_life_days": 7,
        "common_pack_sizes_ml": [200, 500, 1000],
        "halal_certified": True,
        "storage_type": "chilled",
        "category": "dairy_alternatives",
        "typical_monthly_usage_ml": 50000,
        "is_perishable": True,
        "substitute_ids": ["evaporated_milk"],
    },
    "rice_jasmine": {
        "local_names": {"ms": "Beras Wangi", "zh": "香米", "ta": "மல்லிகை அரிசி"},
        "unit": "kg",
        "typical_suppliers": ["Bernas", "FAZZA", "Royal Umbrella", "Sunshine"],
        "seasonal_price_fluctuation": {
            "jan-mar": 1.05,
            "apr-jun": 1.0,
            "jul-sep": 0.95,
            "oct-dec": 1.10,
        },
        "shelf_life_days": 180,
        "common_pack_sizes_kg": [1, 5, 10, 25],
        "halal_certified": True,
        "storage_type": "ambient",
        "category": "grains",
        "typical_monthly_usage_kg": 200,
        "is_perishable": False,
        "substitute_ids": ["rice_brown", "basmati_rice"],
    },
    "belacan_shrimp_paste": {
        "local_names": {"ms": "Belacan", "zh": "虾膏", "ta": "இறால் பேஸ்ட்"},
        "unit": "g",
        "typical_suppliers": ["Pekasam", "Syarikat Sianglam", "Lee Brand"],
        "seasonal_price_fluctuation": {
            "jan-dec": 1.0,
        },
        "shelf_life_days": 365,
        "common_pack_sizes_g": [100, 200, 500],
        "halal_certified": True,
        "storage_type": "ambient",
        "category": "condiments",
        "typical_monthly_usage_g": 500,
        "is_perishable": False,
        "note": "Essential for sambal belacan, nasi lemak, and many Malay dishes. After opening, refrigerate.",
    },
    "kafir_lime_leaves": {
        "local_names": {"ms": "Daun Limau Purut", "zh": "疯柑叶", "ta": "கற்பூர இலை"},
        "unit": "g",
        "typical_suppliers": ["Cameron Fresh", "Genting Farm", "Local wet market wholesalers"],
        "seasonal_price_fluctuation": {
            "jan-mar": 1.10,
            "apr-jun": 0.95,
            "jul-sep": 0.90,
            "oct-dec": 1.05,
        },
        "shelf_life_days": 7,
        "common_pack_sizes_g": [50, 100, 200],
        "halal_certified": True,
        "storage_type": "chilled",
        "category": "herbs",
        "typical_monthly_usage_g": 800,
        "is_perishable": True,
        "substitute_ids": ["lime_zest"],
    },
    "lemongrass": {
        "local_names": {"ms": "Serai", "zh": "香茅", "ta": "இலவங்கப்பட்டை"},
        "unit": "g",
        "typical_suppliers": ["Cameron Fresh", "Puncak Niaga", "Local wholesalers"],
        "seasonal_price_fluctuation": {
            "jan-dec": 1.0,
        },
        "shelf_life_days": 10,
        "common_pack_sizes_g": [100, 250, 500],
        "halal_certified": True,
        "storage_type": "chilled",
        "category": "herbs",
        "typical_monthly_usage_g": 3000,
        "is_perishable": True,
    },
    "pandan_leaves": {
        "local_names": {"ms": "Daun Pandan", "zh": "斑兰叶", "ta": "பன்றி இலை"},
        "unit": "g",
        "typical_suppliers": ["Cameron Fresh", "Local market vendors"],
        "seasonal_price_fluctuation": {
            "jan-dec": 1.0,
        },
        "shelf_life_days": 5,
        "common_pack_sizes_g": [50, 100],
        "halal_certified": True,
        "storage_type": "chilled",
        "category": "herbs",
        "typical_monthly_usage_g": 500,
        "is_perishable": True,
        "note": "Used for fragrance in rice, desserts, and curries. Can be frozen for extended shelf life.",
    },
    "coconut_fresh": {
        "local_names": {"ms": "Kelapa", "zh": "椰子", "ta": "தேங்காய்"},
        "unit": "unit",
        "typical_suppliers": ["Maju Coconut", "Syarikat Kelapa Murni", "Local wet market"],
        "seasonal_price_fluctuation": {
            "jan-mar": 1.05,
            "apr-jun": 0.95,
            "jul-sep": 0.90,
            "oct-dec": 1.05,
        },
        "shelf_life_days": 14,
        "common_pack_sizes": [{"size": "young_coconut", "weight_g": 500}, {"size": "mature_coconut", "weight_g": 800}],
        "halal_certified": True,
        "storage_type": "ambient",
        "category": "fruits",
        "typical_monthly_usage_unit": 300,
        "is_perishable": True,
    },
    "chicken_whole": {
        "local_names": {"ms": "Ayam", "zh": "鸡", "ta": "கோழி"},
        "unit": "kg",
        "typical_suppliers": ["CP", "Leong Hup", "Sri Ayamas", "Teo Seng"],
        "seasonal_price_fluctuation": {
            "jan-feb": 1.10,
            "mar-may": 1.0,
            "jun-aug": 0.95,
            "sep-dec": 1.05,
        },
        "shelf_life_days": 5,
        "common_pack_sizes_kg": [1.2, 1.5, 1.8, 2.0],
        "halal_certified": True,
        "storage_type": "chilled",
        "category": "poultry",
        "typical_monthly_usage_kg": 500,
        "is_perishable": True,
        "note": "Must be JAKIM halal certified for Malaysian halal restaurants. CP and Leong Hup are major integrated suppliers.",
        "supplier_notes": "During festive seasons (Hari Raya, CNY), poultry prices typically rise 10-15%.",
    },
    "beef_imported": {
        "local_names": {"ms": "Daging Lembu", "zh": "牛肉", "ta": "மாட்டிறைச்சி"},
        "unit": "kg",
        "typical_suppliers": ["Australia Meat", "JBS Malaysia", "NZ Beef", "Kawan Lama"],
        "seasonal_price_fluctuation": {
            "jan-feb": 1.05,
            "mar-may": 1.0,
            "jun-aug": 1.10,
            "sep-dec": 1.05,
        },
        "shelf_life_days": 7,
        "common_pack_sizes_kg": [1, 2, 5, 10],
        "halal_certified": True,
        "storage_type": "chilled",
        "category": "meat",
        "typical_monthly_usage_kg": 150,
        "is_perishable": True,
        "note": "Majority of Malaysian beef is imported from Australia, India, and New Zealand. Must be halal-certified at import.",
    },
    "shrimp_medium": {
        "local_names": {"ms": "Udang", "zh": "虾", "ta": "இறால்"},
        "unit": "kg",
        "typical_suppliers": ["Kuala Lumpur Kepong", "Sea Fresh", "Frozen Marine Products", "Local fishermen"],
        "seasonal_price_fluctuation": {
            "jan-feb": 1.10,
            "mar-may": 1.0,
            "jun-aug": 0.90,
            "sep-dec": 1.05,
        },
        "shelf_life_days": 3,
        "common_pack_sizes_kg": [0.5, 1, 2],
        "halal_certified": True,
        "storage_type": "chilled",
        "category": "seafood",
        "typical_monthly_usage_kg": 80,
        "is_perishable": True,
        "note": "Monsoon season (Nov-Jan) reduces catch and increases prices. Frozen shrimp is a stable alternative.",
    },
    "turmeric_fresh": {
        "local_names": {"ms": "Kunyit", "zh": "黄姜", "ta": "மஞ்சள்"},
        "unit": "g",
        "typical_suppliers": ["Cameron Fresh", "Local market", "Benta Fresh"],
        "seasonal_price_fluctuation": {
            "jan-dec": 1.0,
        },
        "shelf_life_days": 14,
        "common_pack_sizes_g": [100, 200, 500],
        "halal_certified": True,
        "storage_type": "ambient",
        "category": "spices",
        "typical_monthly_usage_g": 1500,
        "is_perishable": True,
    },
    "galangal": {
        "local_names": {"ms": "Lengkuas", "zh": "南姜", "ta": "பெருங்காயம்"},
        "unit": "g",
        "typical_suppliers": ["Cameron Fresh", "Local wholesalers"],
        "seasonal_price_fluctuation": {
            "jan-dec": 1.0,
        },
        "shelf_life_days": 14,
        "common_pack_sizes_g": [100, 200, 500],
        "halal_certified": True,
        "storage_type": "ambient",
        "category": "spices",
        "typical_monthly_usage_g": 1000,
        "is_perishable": True,
    },
    "gula_melaka": {
        "local_names": {"ms": "Gula Melaka / Gula Kabung", "zh": "马六甲椰糖", "ta": "மலாக்கா சர்க்கரை"},
        "unit": "g",
        "typical_suppliers": ["Gula Melaka Asli", "Koperasi Kampung", "Melaka Trading"],
        "seasonal_price_fluctuation": {
            "jan-dec": 1.0,
        },
        "shelf_life_days": 365,
        "common_pack_sizes_g": [200, 500, 1000],
        "halal_certified": True,
        "storage_type": "ambient",
        "category": "sweeteners",
        "typical_monthly_usage_g": 2000,
        "is_perishable": False,
        "note": "Coconut palm sugar from Melaka. Essential for cendol, desserts, and some Malay curries. Premium product.",
    },
    "tamarind_paste": {
        "local_names": {"ms": "Asam Jawa", "zh": "罗望子", "ta": "புளி"},
        "unit": "g",
        "typical_suppliers": ["Adabi", "Brahims", "Local wholesalers"],
        "seasonal_price_fluctuation": {
            "jan-dec": 1.0,
        },
        "shelf_life_days": 365,
        "common_pack_sizes_g": [100, 200, 500],
        "halal_certified": True,
        "storage_type": "ambient",
        "category": "condiments",
        "typical_monthly_usage_g": 1000,
        "is_perishable": False,
    },
    "dried_chili": {
        "local_names": {"ms": "Cili Kering", "zh": "干辣椒", "ta": "உலர் மிளகாய்"},
        "unit": "g",
        "typical_suppliers": ["Adabi", "Brahims", "Baba's", "Local wholesalers"],
        "seasonal_price_fluctuation": {
            "jan-mar": 1.10,
            "apr-jun": 0.90,
            "jul-sep": 0.95,
            "oct-dec": 1.15,
        },
        "shelf_life_days": 180,
        "common_pack_sizes_g": [100, 200, 500, 1000],
        "halal_certified": True,
        "storage_type": "ambient",
        "category": "spices",
        "typical_monthly_usage_g": 5000,
        "is_perishable": False,
        "note": "Price volatility is high. During rainy season (Oct-Dec), quality decreases and prices spike. Stock up in Jun-Sep.",
    },
    "peanut_ground": {
        "local_names": {"ms": "Kacang Tanah", "zh": "花生", "ta": "வேர்க்கடலை"},
        "unit": "g",
        "typical_suppliers": ["Munchy's", "Julie's", "Fancy", "Local wholesalers"],
        "seasonal_price_fluctuation": {
            "jan-mar": 0.95,
            "apr-jun": 1.0,
            "jul-sep": 1.05,
            "oct-dec": 1.0,
        },
        "shelf_life_days": 90,
        "common_pack_sizes_g": [200, 500, 1000],
        "halal_certified": True,
        "storage_type": "ambient",
        "category": "nuts",
        "typical_monthly_usage_g": 3000,
        "is_perishable": False,
        "note": "Used for satay sauce, rojak dressing, and kuih. Peanut is a common allergen — must label dishes containing peanut.",
        "allergen": True,
    },
    "fish_mackerel": {
        "local_names": {"ms": "Ikan Kembung", "zh": "鲭鱼", "ta": "கானாங்கெளுத்தி"},
        "unit": "kg",
        "typical_suppliers": ["MFC (Malaysian Fisheries)", "Sea Fresh", "Local fishermen cooperative"],
        "seasonal_price_fluctuation": {
            "jan-feb": 1.15,
            "mar-may": 1.0,
            "jun-aug": 0.85,
            "sep-dec": 1.10,
        },
        "shelf_life_days": 2,
        "common_pack_sizes_kg": [0.5, 1, 2],
        "halal_certified": True,
        "storage_type": "chilled",
        "category": "seafood",
        "typical_monthly_usage_kg": 100,
        "is_perishable": True,
        "note": "Monsoon ban (Nov-Jan) on trawling in east coast reduces supply. Substitute with frozen mackerel during ban period.",
    },
    "tofu": {
        "local_names": {"ms": "Tahu", "zh": "豆腐", "ta": "டோஃபு"},
        "unit": "unit",
        "typical_suppliers": ["Unicurd", "Yeo's", "SoGood", "Local tofu makers"],
        "seasonal_price_fluctuation": {
            "jan-dec": 1.0,
        },
        "shelf_life_days": 5,
        "common_pack_sizes": [{"type": "soft", "weight_g": 300}, {"type": "firm", "weight_g": 300}],
        "halal_certified": True,
        "storage_type": "chilled",
        "category": "soy_products",
        "typical_monthly_usage_unit": 400,
        "is_perishable": True,
    },
    "egg_chicken": {
        "local_names": {"ms": "Telur Ayam", "zh": "鸡蛋", "ta": "கோழி முட்டை"},
        "unit": "unit",
        "typical_suppliers": ["Teo Seng", "BW Farm", "Pulai Egg", "Linggi Egg"],
        "seasonal_price_fluctuation": {
            "jan-feb": 1.08,
            "mar-may": 0.95,
            "jun-aug": 1.02,
            "sep-dec": 1.05,
        },
        "shelf_life_days": 21,
        "common_pack_sizes": [{"count": 10}, {"count": 30}],
        "halal_certified": True,
        "storage_type": "ambient",
        "category": "poultry",
        "typical_monthly_usage_unit": 3000,
        "is_perishable": True,
        "note": "Price is government-controlled (harga terkawal). Supply is generally stable year-round.",
    },
    "flour_wheat": {
        "local_names": {"ms": "Tepung Gandum", "zh": "面粉", "ta": "கோதுமை மாவு"},
        "unit": "kg",
        "typical_suppliers": ["Malayan Flour Mills", "FFM", "Pertama", "Bakersville"],
        "seasonal_price_fluctuation": {
            "jan-dec": 1.0,
        },
        "shelf_life_days": 180,
        "common_pack_sizes_kg": [1, 5, 10, 25],
        "halal_certified": True,
        "storage_type": "ambient",
        "category": "grains",
        "typical_monthly_usage_kg": 100,
        "is_perishable": False,
        "note": "Global wheat price affects local pricing. Malaysia imports wheat primarily from Australia.",
    },
    "cooking_oil_palm": {
        "local_names": {"ms": "Minyak Masak", "zh": "食用油", "ta": "சமையல் எண்ணெய்"},
        "unit": "litre",
        "typical_suppliers": ["Buruh", "Saji", "Vesawit", "Minyak Kita"],
        "seasonal_price_fluctuation": {
            "jan-mar": 1.05,
            "apr-jun": 1.0,
            "jul-sep": 0.92,
            "oct-dec": 1.03,
        },
        "shelf_life_days": 365,
        "common_pack_sizes_litre": [1, 2, 5],
        "halal_certified": True,
        "storage_type": "ambient",
        "category": "oils",
        "typical_monthly_usage_litre": 60,
        "is_perishable": False,
        "note": "Palm oil price is volatile and linked to CPO (Crude Palm Oil) futures market. Government subsidy scheme for 1kg pack.",
    },
    "curry_powder_malaysian": {
        "local_names": {"ms": "Serbuk Kari", "zh": "咖喱粉", "ta": "கறி தூள்"},
        "unit": "g",
        "typical_suppliers": ["Baba's", "Adabi", "Shah's", "Alagappas"],
        "seasonal_price_fluctuation": {
            "jan-dec": 1.0,
        },
        "shelf_life_days": 180,
        "common_pack_sizes_g": [100, 200, 500, 1000],
        "halal_certified": True,
        "storage_type": "ambient",
        "category": "spices",
        "typical_monthly_usage_g": 3000,
        "is_perishable": False,
        "note": "Malaysian curry powder differs from Indian — contains rempah (lemongrass, galangal, candlenut). Spicier and more aromatic.",
    },
    "sambal_paste": {
        "local_names": {"ms": "Sambal", "zh": "参巴酱", "ta": "சம்பல்"},
        "unit": "g",
        "typical_suppliers": ["Adabi", "Baba's", "Mak Nyonya", "Home-based suppliers"],
        "seasonal_price_fluctuation": {
            "jan-dec": 1.0,
        },
        "shelf_life_days": 60,
        "common_pack_sizes_g": [200, 500, 1000],
        "halal_certified": True,
        "storage_type": "chilled",
        "category": "condiments",
        "typical_monthly_usage_g": 4000,
        "is_perishable": False,
        "note": "Many restaurants make their own sambal in-house (signature recipe). Retail sambal is backup/replacement.",
    },
    "noodles_rice": {
        "local_names": {"ms": "Mee Hoon / Bihun", "zh": "米粉", "ta": "ரைஸ் நூடுல்ஸ்"},
        "unit": "kg",
        "typical_suppliers": ["Klang Noodle Factory", "Soon Soon", "Farlim", "Local noodle factories"],
        "seasonal_price_fluctuation": {
            "jan-dec": 1.0,
        },
        "shelf_life_days": 14,
        "common_pack_sizes_kg": [1, 2, 5],
        "halal_certified": True,
        "storage_type": "ambient",
        "category": "noodles",
        "typical_monthly_usage_kg": 50,
        "is_perishable": True,
        "note": "Used for laksa, bihun goreng, and sarawak laksa. Dried rice noodles (bihun) has longer shelf life.",
    },
    "noodles_egg": {
        "local_names": {"ms": "Mee Kuning", "zh": "黄面", "ta": "முட்டை நூடுல்ஸ்"},
        "unit": "kg",
        "typical_suppliers": ["Klang Noodle Factory", "Penang Noodle", "Local suppliers"],
        "seasonal_price_fluctuation": {
            "jan-dec": 1.0,
        },
        "shelf_life_days": 3,
        "common_pack_sizes_kg": [0.5, 1, 2],
        "halal_certified": True,
        "storage_type": "chilled",
        "category": "noodles",
        "typical_monthly_usage_kg": 60,
        "is_perishable": True,
        "note": "Fresh yellow noodles are used in Hokkien Mee, Mee Goreng, Wantan Mee. Highly perishable — daily ordering recommended.",
    },
    "durian_musang_king": {
        "local_names": {"ms": "Durian Musang King", "zh": "猫山王榴莲", "ta": "முசாங் கிங்"},
        "unit": "kg",
        "typical_suppliers": ["Durian King", "Musang King Group", "Pahang Durian Farms", "Raub Durian"],
        "seasonal_price_fluctuation": {
            "jan-may": 1.5,
            "jun-aug": 0.7,
            "sep-nov": 1.2,
            "dec": 1.3,
        },
        "shelf_life_days": 3,
        "common_pack_sizes_kg": [1, 2, 5],
        "halal_certified": True,
        "storage_type": "chilled",
        "category": "fruits",
        "typical_monthly_usage_kg": 30,
        "is_perishable": True,
        "note": "Premium ingredient. Peak season Jun-Aug sees 50% discount vs off-season. Durian-themed F&B has grown 200% YoY.",
    },
}

# ─────────────────────────────────────────────
# Supplier Notes
# ─────────────────────────────────────────────

MALAYSIA_SUPPLIER_NOTES: dict[str, Any] = {
    "recommended_payment_terms": "net_30",
    "typical_lead_time_days": 2,
    "halal_certification_authority": "JAKIM",
    "local_supplier_market": {
        "wet_market": {
            "description": "Pasar Basah — fresh ingredients, daily pricing, cash basis",
            "best_for": ["herbs", "seafood", "vegetables", "spices"],
            "quality_consistency": "variable",
        },
        "hypermarket": {
            "description": "Lotus's, AEON, Giant — packaged goods, stable pricing",
            "best_for": ["packaged_goods", "oils", "canned"],
            "quality_consistency": "consistent",
        },
        "wholesaler": {
            "description": "Pasar Borong — bulk purchasing, best pricing",
            "best_for": ["rice", "oil", "flour", "chicken", "spices"],
            "quality_consistency": "good",
            "minimum_order_myr": 500,
        },
    },
    "delivery_note_requirement": "e-invoice (LHDN compliant)",
}

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────


def get_ingredient(key: str) -> dict[str, Any] | None:
    """Get ingredient profile by key.

    Args:
        key: Ingredient key (e.g., "coconut_milk", "belacan_shrimp_paste").

    Returns:
        Ingredient dict or None if not found.
    """
    return MALAYSIA_INGREDIENTS.get(key)


def get_perishable_ingredients() -> dict[str, dict[str, Any]]:
    """Return only perishable ingredients (requiring chilled storage)."""
    return {k: v for k, v in MALAYSIA_INGREDIENTS.items() if v.get("is_perishable", False)}


def get_halal_certified_ingredients() -> dict[str, dict[str, Any]]:
    """Return only halal-certified ingredients."""
    return {k: v for k, v in MALAYSIA_INGREDIENTS.items() if v.get("halal_certified", False)}


def get_ingredients_by_category(category: str) -> dict[str, dict[str, Any]]:
    """Filter ingredients by category.

    Args:
        category: Category name (e.g., "spices", "seafood", "poultry").

    Returns:
        Filtered ingredient dict.
    """
    return {k: v for k, v in MALAYSIA_INGREDIENTS.items() if v.get("category") == category}
