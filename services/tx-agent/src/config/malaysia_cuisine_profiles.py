"""Malaysia-specific cuisine profiles and local taste preferences

Each profile captures dish popularity, flavor characteristics, common
ingredients, and dining patterns for the major Malaysian culinary
traditions. Used by the menu optimization and sales forecasting AI to
make culturally-aware recommendations.

Halal status is critical for Malaysian F&B operations — all dishes
served in halal-certified restaurants must comply with JAKIM standards.
"""

from __future__ import annotations

from typing import Any

# ─────────────────────────────────────────────
# Core Cuisine Profiles
# ─────────────────────────────────────────────

CUISINE_PROFILES: dict[str, dict[str, Any]] = {
    "malay": {
        "description": "Traditional Malay cuisine — the national cuisine of Malaysia, rich in coconut milk, spices, and herbs.",
        "popular_dishes": [
            "Nasi Lemak",
            "Rendang Ayam/Daging",
            "Satay Ayam/Daging",
            "Laksa Lemak",
            "Nasi Goreng Kampung",
            "Mee Rebus",
            "Soto Ayam",
            "Ikan Bakar",
            "Ayam Percik",
            "Keropok Lekor",
        ],
        "flavor_profile": {
            "spicy": 0.8,
            "sweet": 0.3,
            "savory": 0.7,
            "coconut": 0.6,
            "sour": 0.3,
            "umami": 0.4,
            "bitter": 0.1,
        },
        "common_ingredients": [
            "coconut milk",
            "lemongrass",
            "turmeric",
            "belacan (shrimp paste)",
            "kafir lime leaves",
            "pandan leaves",
            "galangal",
            "cumin",
            "fennel",
            "star anise",
            "cinnamon",
            "tamarind",
            "kerisik (toasted coconut)",
            "budu (fish sauce)",
        ],
        "meal_times": {
            "breakfast": "7-9am",
            "lunch": "12-2pm",
            "dinner": "7-9pm",
        },
        "halal": True,
        "avg_spend_per_pax_fen": 1800,
        "peak_hours": [12, 13, 19, 20],
        "popular_meal_period": "dinner",
        "dietary_restrictions": ["no_pork", "no_alcohol"],
        "regional_variations": {
            "kelantan": "Stronger sweetness, more kerisuk use",
            "terengganu": "Heavier use of budu and keropok lekor",
            "negeri_sembilan": "Spiciest Malay cuisine, heavy use of lemak cili api",
            "johor": "Pengaruh (influence) from Javanese and Arab cuisine",
            "kedah": "Influenced by Thai border, more sour elements",
        },
    },
    "chinese": {
        "description": "Malaysian Chinese cuisine — evolved from regional Chinese traditions with Southeast Asian adaptations.",
        "popular_dishes": [
            "Char Kway Teow",
            "Hokkien Mee",
            "Wonton Mee",
            "Bak Kut Teh",
            "Dim Sum",
            "Kai Si Hor Fun",
            "Ipoh Hor Fun",
            "Claypot Chicken Rice",
            "Fried Oyster Omelette",
            "Pan Mee",
        ],
        "flavor_profile": {
            "spicy": 0.4,
            "sweet": 0.3,
            "savory": 0.8,
            "umami": 0.7,
            "sour": 0.2,
            "coconut": 0.1,
            "bitter": 0.15,
        },
        "common_ingredients": [
            "soy sauce (light and dark)",
            "sesame oil",
            "ginger",
            "garlic",
            "five spice powder",
            "white pepper",
            "oyster sauce",
            "fermented bean paste",
            "dried shrimp",
            "pork lard",
            "spring onion",
            "shallots",
        ],
        "meal_times": {
            "breakfast": "6-10am",
            "lunch": "11am-2pm",
            "dinner": "6-9pm",
        },
        "halal": False,
        "has_pork_free_variants": True,
        "avg_spend_per_pax_fen": 2500,
        "peak_hours": [12, 13, 18, 19],
        "popular_meal_period": "dinner",
        "regional_variations": {
            "penang": "Strongest street food culture, nanyang influence",
            "ipoh": "Famous for hor fun and white coffee",
            "klang": "Bak Kut Teh capital, strong tea culture",
            "kuching": "Sarawak特色 — Sarawak laksa, kompia",
            "melaka": "Baba Nyonya cuisine influence",
        },
        "sub_cuisines": {
            "baba_nyonya": {
                "description": "Peranakan Chinese-Malay fusion — unique to Melaka and Penang",
                "popular_dishes": ["Nyonya Laksa", "Ayam Pongteh", "Itek Tim", "Nyonya Kuih"],
                "flavor_profile": {"spicy": 0.5, "sweet": 0.4, "sour": 0.4, "savory": 0.6},
            },
            "chinese_halaL": {
                "description": "Halal Chinese cuisine — pork-free, certified halal, popular with Muslim customers",
                "popular_dishes": ["Halal Char Kway Teow", "Halal Dim Sum", "Halal Hokkien Mee"],
                "flavor_profile": {"spicy": 0.4, "sweet": 0.3, "savory": 0.8, "umami": 0.7},
                "halal": True,
            },
        },
    },
    "indian": {
        "description": "Malaysian Indian cuisine — a vibrant blend of South Indian, North Indian, and local Malay influences.",
        "popular_dishes": [
            "Roti Canai",
            "Nasi Biryani",
            "Tandoori Chicken",
            "Banana Leaf Rice",
            "Teh Tarik",
            "Mee Goreng Mamak",
            "Curry Kapitan",
            "Fish Head Curry",
            "Roti Tissue",
            "Pasembur",
        ],
        "flavor_profile": {
            "spicy": 0.7,
            "sweet": 0.2,
            "savory": 0.6,
            "sour": 0.3,
            "umami": 0.3,
            "coconut": 0.4,
            "bitter": 0.1,
        },
        "common_ingredients": [
            "curry leaves",
            "mustard seeds",
            "cardamom",
            "turmeric",
            "ghee",
            "tamarind",
            "fenugreek",
            "cumin",
            "coriander seeds",
            "chili powder",
            "curry powder",
            "coconut milk",
            "paneer",
            "lentils (dal)",
        ],
        "meal_times": {
            "breakfast": "7-10am",
            "lunch": "12-3pm",
            "dinner": "7-10pm",
        },
        "halal": True,
        "avg_spend_per_pax_fen": 2000,
        "peak_hours": [8, 9, 12, 13, 14, 19, 20],
        "popular_meal_period": "lunch",
        "note": "Mamak (Indian Muslim) stalls are uniquely Malaysian — open late, popular for supper, and central to Malaysian social life.",
        "sub_cuisines": {
            "mamak": {
                "description": "Indian Muslim (Mamak) — Malaysian-born fusion, late-night staple",
                "popular_dishes": ["Roti Canai", "Mee Goreng Mamak", "Nasi Goreng Mamak", "Maggi Goreng"],
                "halal": True,
                "peak_hours": [22, 23, 0, 1],
                "note": "Many Mamak stalls operate 24 hours. Supper (lepas maghrib) is peak.",
            },
            "north_indian": {
                "description": "North Indian style — heavier, creamier, bread-based",
                "popular_dishes": ["Naan", "Butter Chicken", "Dal Makhani", "Kulcha"],
                "halal": True,
            },
            "south_indian": {
                "description": "South Indian style — rice-based, lighter, more lentil use",
                "popular_dishes": ["Dosa", "Idli", "Vada", "Uttapam", "Banana Leaf Rice"],
                "halal": True,
            },
        },
    },
    "fusion": {
        "description": "Malaysian fusion / modern Malaysian — contemporary interpretations of traditional flavors, influenced by global trends.",
        "popular_dishes": [
            "Nasi Lemak Burger",
            "Mamak Mee Goreng",
            "Cendol",
            "ABC (Ais Batu Campur)",
            "Durian Crepe",
            "Nasi Kerabu",
            "Ulam Rice Bowl",
            "Sambal Pasta",
            "Teh Tarik Latte",
            "Pandan Chiffon Cake",
        ],
        "flavor_profile": {
            "spicy": 0.5,
            "sweet": 0.5,
            "savory": 0.6,
            "umami": 0.4,
            "sour": 0.2,
            "coconut": 0.4,
            "bitter": 0.1,
        },
        "common_ingredients": [
            "sambal",
            "pandan",
            "coconut",
            "peanut",
            "belacan",
            "kerisik",
            "lemongrass",
            "chili padi",
        ],
        "meal_times": {
            "breakfast": "variable",
            "lunch": "12-3pm",
            "dinner": "6-11pm",
        },
        "halal": True,
        "avg_spend_per_pax_fen": 3500,
        "peak_hours": [12, 13, 19, 20, 21],
        "popular_meal_period": "dinner",
        "note": "Fusion cuisine appeals to younger urban consumers. Higher price point. Instagram-worthy presentation expected.",
        "target_demographic": "urban millennials and Gen Z, tourists, office workers in KL/Penang/Johor",
    },
    "sabah_sarawak": {
        "description": "East Malaysian (Borneo) cuisine — unique indigenous dishes from Sabah and Sarawak, distinct from Peninsular Malaysia.",
        "popular_dishes": [
            "Sarawak Laksa",
            "Kolo Mee",
            "Nasi Lemak (Borneo style)",
            "Linopot",
            "Hinava (Sabah raw fish salad)",
            "Pansoh (Manok Pansoh — bamboo chicken)",
            "Tuak (rice wine)",
            "Midin (wild fern stir fry)",
            "Umai (Sarawak raw fish)",
            "Kuih Lapis Sarawak",
        ],
        "flavor_profile": {
            "spicy": 0.5,
            "sweet": 0.3,
            "savory": 0.7,
            "sour": 0.4,
            "umami": 0.3,
            "coconut": 0.3,
            "bitter": 0.15,
        },
        "common_ingredients": [
            "sago",
            "tapioca",
            "wild ferns (midin)",
            "bamboo shoots",
            "tuhau (wild ginger)",
            "bambangan (wild mango)",
            "budu",
            "coconut",
            "freshwater fish",
            "wild boar",
        ],
        "meal_times": {
            "breakfast": "6-9am",
            "lunch": "12-2pm",
            "dinner": "6-8pm",
        },
        "halal": False,
        "note": "Many indigenous dishes are not halal (use of wild boar, tuak rice wine). Halal variants available in urban areas. Must label clearly.",
        "has_halal_variants": True,
        "avg_spend_per_pax_fen": 2200,
        "peak_hours": [12, 13, 18, 19],
        "popular_meal_period": "lunch",
        "regional_variations": {
            "sarawak": "Iban, Bidayuh, Orang Ulu influences. Strong pepper culture.",
            "sabah": "Kadazan-Dusun, Murut, Bajau influences. Hinava and tuhau are iconic.",
        },
    },
}

# ─────────────────────────────────────────────
# Malaysian Beverage Profiles
# ─────────────────────────────────────────────

MALAYSIA_BEVERAGE_PROFILES: dict[str, dict[str, Any]] = {
    "teh_tarik": {
        "description": "Pulled milk tea — Malaysia's national beverage",
        "flavor_profile": {"sweet": 0.7, "creamy": 0.8, "tea_bitterness": 0.3},
        "peak_hours": [8, 9, 10, 14, 15, 22, 23],
        "avg_price_fen": 500,
        "halal": True,
        "note": "Essential at Mamak stalls. Afternoon tea and late-night supper pairing.",
    },
    " kopi_o": {
        "description": "Black coffee with sugar — traditional Malaysian kopitiam style",
        "flavor_profile": {"bitter": 0.7, "sweet": 0.5, "roasted": 0.8},
        "peak_hours": [7, 8, 9, 10, 14, 15],
        "avg_price_fen": 400,
        "halal": True,
        "note": "Kopi-O Kosong (no sugar) also popular. Served with butter kaya toast.",
    },
    "cendol": {
        "description": "Shaved ice dessert with green jelly, coconut milk and gula melaka",
        "flavor_profile": {"sweet": 0.8, "coconut": 0.6, "herbal": 0.2},
        "peak_hours": [13, 14, 15, 16, 20, 21],
        "avg_price_fen": 600,
        "halal": True,
        "note": "Popular as afternoon dessert in tropical heat. Peak demand at 2-4pm.",
    },
    "ais_kacang": {
        "description": "Shaved ice with sweet corn, red beans, jelly, nuts and syrup (ABC)",
        "flavor_profile": {"sweet": 0.9, "creamy": 0.5, "nutty": 0.3},
        "peak_hours": [13, 14, 15, 16],
        "avg_price_fen": 700,
        "halal": True,
        "note": "Air Batu Campur. Iconic Malaysian dessert. Best selling during hot season (Mar-Oct).",
    },
    "sirap_bandung": {
        "description": "Rose syrup drink with evaporated milk",
        "flavor_profile": {"sweet": 0.8, "creamy": 0.4, "floral": 0.5},
        "peak_hours": [11, 12, 13, 14, 15],
        "avg_price_fen": 500,
        "halal": True,
        "note": "Popular with Malay customers. Bright pink color. Often ordered with spicy food.",
    },
    "milo_ais": {
        "description": "Iced Milo — Malaysia's unofficial national drink",
        "flavor_profile": {"sweet": 0.8, "malty": 0.6, "creamy": 0.5},
        "peak_hours": [7, 8, 9, 10, 14, 15, 21, 22],
        "avg_price_fen": 500,
        "halal": True,
        "note": "Universally loved across all ethnic groups. Served at all meal periods.",
    },
}

# ─────────────────────────────────────────────
# Meal Period Analysis
# ─────────────────────────────────────────────

MALAYSIA_MEAL_PERIODS: dict[str, dict[str, Any]] = {
    "breakfast": {
        "time_range": "6:00-11:00",
        "typical_dishes": ["nasi lemak", "roti canai", "kaya toast", "kopi", "teh", "dim sum"],
        "avg_spend_fen": 800,
        "top_cuisines": ["malay", "chinese"],
        "dine_in_ratio": 0.60,
        "takeaway_ratio": 0.35,
        "delivery_ratio": 0.05,
    },
    "lunch": {
        "time_range": "11:00-15:00",
        "typical_dishes": ["nasi campur", "economy rice", "mee goreng", "laksa", "chicken rice"],
        "avg_spend_fen": 1500,
        "top_cuisines": ["malay", "chinese", "indian"],
        "dine_in_ratio": 0.45,
        "takeaway_ratio": 0.30,
        "delivery_ratio": 0.25,
    },
    "afternoon_tea": {
        "time_range": "15:00-17:00",
        "typical_dishes": ["cendol", "kuih", "roti canai", "teh tarik", "pulut inti"],
        "avg_spend_fen": 500,
        "top_cuisines": ["malay", "indian", "fusion"],
        "dine_in_ratio": 0.55,
        "takeaway_ratio": 0.35,
        "delivery_ratio": 0.10,
    },
    "dinner": {
        "time_range": "17:00-22:00",
        "typical_dishes": ["nasi kandar", "bak kut teh", "steamboat", "seafood", "banana leaf rice"],
        "avg_spend_fen": 3000,
        "top_cuisines": ["malay", "chinese", "indian", "fusion"],
        "dine_in_ratio": 0.55,
        "takeaway_ratio": 0.20,
        "delivery_ratio": 0.25,
    },
    "supper": {
        "time_range": "22:00-2:00",
        "typical_dishes": ["roti canai", "mee goreng", "nasi lemak", "satay", "maggi goreng"],
        "avg_spend_fen": 1000,
        "top_cuisines": ["indian", "malay", "chinese"],
        "dine_in_ratio": 0.60,
        "takeaway_ratio": 0.25,
        "delivery_ratio": 0.15,
    },
}

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────


def get_cuisine_profile(cuisine_name: str) -> dict[str, Any] | None:
    """Get a full cuisine profile by name.

    Args:
        cuisine_name: Key from CUISINE_PROFILES (e.g., "malay", "chinese").

    Returns:
        Cuisine profile dict or None if not found.
    """
    return CUISINE_PROFILES.get(cuisine_name.lower())


def get_all_halal_profiles() -> dict[str, dict[str, Any]]:
    """Return only halal-certified cuisine profiles.

    Used by stores that operate with JAKIM halal certification.
    """
    return {k: v for k, v in CUISINE_PROFILES.items() if v.get("halal", False)}


def get_cuisine_by_state(state: str) -> list[str]:
    """Suggest which cuisine profiles are most relevant for a given state.

    Args:
        state: Malaysian state name.

    Returns:
        List of cuisine profile keys in order of relevance.
    """
    state_cuisine_map: dict[str, list[str]] = {
        "johor": ["malay", "chinese", "indian"],
        "kedah": ["malay", "indian"],
        "kelantan": ["malay", "fusion"],
        "melaka": ["chinese", "malay", "baba_nyonya"],
        "negeri_sembilan": ["malay", "chinese"],
        "pahang": ["malay", "chinese"],
        "penang": ["chinese", "malay", "indian", "fusion"],
        "perak": ["chinese", "malay", "indian"],
        "perlis": ["malay", "fusion"],
        "sabah": ["sabah_sarawak", "chinese", "malay", "fusion"],
        "sarawak": ["sabah_sarawak", "chinese", "malay", "fusion"],
        "selangor": ["malay", "chinese", "indian", "fusion"],
        "terengganu": ["malay", "fusion"],
        "kuala_lumpur": ["malay", "chinese", "indian", "fusion", "sabah_sarawak"],
        "labuan": ["malay", "chinese", "sabah_sarawak"],
        "putrajaya": ["malay", "chinese", "indian", "fusion"],
    }
    return state_cuisine_map.get(state.lower(), ["malay", "chinese", "indian"])


def get_peak_hours_by_cuisine(cuisine_name: str) -> list[int]:
    """Return peak meal hours for a given cuisine type.

    Args:
        cuisine_name: Cuisine profile key.

    Returns:
        List of hour integers (0-23) representing peak hours.
    """
    profile = get_cuisine_profile(cuisine_name)
    if profile:
        return profile.get("peak_hours", [12, 13, 19, 20])
    return [12, 13, 19, 20]
