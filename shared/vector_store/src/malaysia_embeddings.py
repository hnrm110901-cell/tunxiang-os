"""Malaysia market embedding configurations and namespace definitions

Defines the vector namespace schemas for Malaysia-specific embeddings
used by the vector store for semantic search across Malaysian F&B data.

Namespaces are used to partition the vector index by data type and
language, enabling efficient multilingual retrieval across Malay (ms),
Chinese (zh), Tamil (ta), and English (en).

Malaysia-specific considerations:
- Bahasa Malaysia (ms) is the national language
- Chinese (zh) is widely used in menus and marketing
- Tamil (ta) is used in Indian-Muslim restaurant contexts
- English (en) is used for business and technical terms
- Code-switching between languages is common in Malaysian F&B
"""

from __future__ import annotations

from typing import Any

# ─────────────────────────────────────────────
# Vector Namespace Definitions
# ─────────────────────────────────────────────

MALAYSIA_EMBEDDING_NAMESPACES: dict[str, dict[str, Any]] = {
    "ingredient_master": {
        "lang": "ms",
        "label": "Ingredient Master (Malaysia)",
        "dimension": 256,
        "description": "Malaysian ingredient embeddings in Bahasa Malaysia. Covers supplier names, local ingredient terms, and packaging descriptions.",
        "fallback_lang": "en",
    },
    "dish": {
        "lang": "ms",
        "label": "Dish/Menu Item (Malaysia)",
        "dimension": 256,
        "description": "Malaysian dish and menu item embeddings. Handles multilingual dish names, cooking methods, and cuisine type classification.",
        "fallback_lang": "en",
    },
    "holiday_event": {
        "lang": "en",
        "label": "Holiday & Cultural Event (Malaysia)",
        "dimension": 128,
        "description": "Malaysian public holiday and cultural event embeddings. Used for sales forecasting and promotional planning.",
        "fallback_lang": "ms",
    },
    "pdpa_compliance": {
        "lang": "en",
        "label": "PDPA Compliance (Malaysia)",
        "dimension": 128,
        "description": "Malaysian Personal Data Protection Act (PDPA 2010) compliance document embeddings. Supports consent management and data subject rights queries.",
    },
    "cuisine_profile": {
        "lang": "en",
        "label": "Cuisine Profile (Malaysia)",
        "dimension": 256,
        "description": "Malaysian cuisine profile embeddings. Flavor profiles, dish popularity, ingredient affinity for recommendation systems.",
        "fallback_lang": "ms",
    },
    "supplier_catalog": {
        "lang": "ms",
        "label": "Supplier Catalog (Malaysia)",
        "dimension": 256,
        "description": "Malaysian F&B supplier catalog embeddings. Supplier names, product categories, halal certification status, delivery areas.",
        "fallback_lang": "en",
    },
    "menu_localization": {
        "lang": "zh",
        "label": "Menu Localization (Malaysia - Chinese)",
        "dimension": 256,
        "description": "Chinese-language menu item embeddings for Malaysian Chinese restaurant menus. Handles traditional Chinese dish names and regional variations.",
        "fallback_lang": "ms",
    },
}

# ─────────────────────────────────────────────
# Embedding Model Configuration
# ─────────────────────────────────────────────

MALAYSIA_EMBEDDING_CONFIG: dict[str, Any] = {
    "preferred_model": "voyage-3",
    "fallback_model": "text-embedding-ada-002",
    "batch_size": 32,
    "max_retries": 3,
    "timeout_seconds": 10.0,
    "language_support": {
        "primary_languages": ["ms", "zh", "ta", "en"],
        "mixed_language_handling": "concatenate_with_lang_tag",
        "code_switch_detection": True,
    },
    "normalization": {
        "malay_stopwords": [
            "dan", "di", "ke", "dari", "yang", "ini", "itu", "pada",
            "untuk", "dengan", "adalah", "telah", "akan", "boleh",
            "saya", "kami", "kita", "mereka", "anda", "atau",
        ],
        "chinese_stopwords": [
            "的", "了", "在", "是", "我", "有", "和", "就", "不", "人",
            "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去",
        ],
    },
}

# ─────────────────────────────────────────────
# Search Query Templates
# ─────────────────────────────────────────────

MALAYSIA_SEARCH_TEMPLATES: dict[str, dict[str, Any]] = {
    "find_halal_ingredient": {
        "namespace": "ingredient_master",
        "pre_filter": {"halal_certified": True},
        "boost_fields": ["local_names.ms", "local_names.zh"],
    },
    "holiday_impact_query": {
        "namespace": "holiday_event",
        "pre_filter": {"impact": {"$in": ["high", "medium"]}},
    },
    "cuisine_similar_dishes": {
        "namespace": "dish",
        "boost_fields": ["flavor_profile.spicy", "flavor_profile.savory"],
    },
}

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────


def get_namespace_config(namespace: str) -> dict[str, Any] | None:
    """Get embedding namespace config by key.

    Args:
        namespace: Namespace key (e.g., "ingredient_master").

    Returns:
        Namespace config dict or None if not found.
    """
    return MALAYSIA_EMBEDDING_NAMESPACES.get(namespace)


def get_language_dimension(lang: str) -> int:
    """Get the recommended embedding dimension for a language.

    Args:
        lang: Language code ("ms", "zh", "ta", "en").

    Returns:
        Default embedding dimension (256 for most MY use cases).
    """
    for ns_config in MALAYSIA_EMBEDDING_NAMESPACES.values():
        if ns_config["lang"] == lang:
            return ns_config["dimension"]
    return 256


def get_supported_languages() -> list[str]:
    """Get list of languages supported by Malaysia embeddings.

    Returns:
        List of language codes.
    """
    return MALAYSIA_EMBEDDING_CONFIG["language_support"]["primary_languages"]
