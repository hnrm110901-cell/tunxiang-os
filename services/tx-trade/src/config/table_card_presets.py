"""
TunxiangOS Smart Table Card - Business Type Presets
Module: services/tx-trade/src/config/table_card_presets.py

Business type configurations (PRO, STANDARD, LITE) with field visibility and feature settings.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class BusinessType(str, Enum):
    """Business type classification."""

    PRO = "pro"  # å°å®«å¨ - Full-featured restaurants
    STANDARD = "standard"  # å°å¨ä¸èµ· - Standard restaurants
    LITE = "lite"  # æé»çº¿ - Fast-casual/quick service


class PresetConfig(BaseModel):
    """Configuration preset for a business type."""

    model_config = ConfigDict(from_attributes=True)

    business_type: BusinessType
    max_fields: int = Field(default=6, ge=3, le=15)
    visible_categories: List[str] = []
    visible_fields: List[str] = []
    hidden_fields: List[str] = []
    sort_priority: Dict[str, int] = {}
    refresh_interval_ms: int = Field(default=3000, ge=1000, le=30000)
    features_enabled: List[str] = []
    custom_rules: Dict[str, Any] = {}


# ============================================================================
# PRO Preset (å°å®«å¨)
# ============================================================================

PRO_PRESET = PresetConfig(
    business_type=BusinessType.PRO,
    max_fields=6,
    visible_categories=[
        "identity",
        "status",
        "financial",
        "service",
        "timing",
        "custom",
    ],
    visible_fields=[
        # Identity (2)
        "vip_badge",
        "member_name",
        # Status (4)
        "status",
        "payment_status",
        "arrears_flag",
        "no_show_warning",
        # Financial (4)
        "amount",
        "per_capita",
        "discount_amount",
        "deposit_balance",
        # Service (8)
        "guest_count",
        "waiter",
        "service_requests",
        "dish_progress",
        "dish_alert",
        "queue_count",
        "vip_level",
        "special_requirements",
        # Timing (6)
        "duration",
        "idle_duration",
        "checkout_duration",
        "cleanup_duration",
        "last_order_time",
        "turnover_time",
        # Custom (3)
        "birthday_badge",
        "upcoming_reservation",
        "room_name",
    ],
    hidden_fields=[],
    sort_priority={
        "birthday_badge": 100,
        "vip_badge": 95,
        "no_show_warning": 90,
        "amount": 85,
        "status": 85,
        "checkout_duration": 80,
        "duration": 75,
        "member_name": 70,
        "dish_progress": 65,
    },
    refresh_interval_ms=2000,
    features_enabled=[
        "vip_tracking",  # Track and highlight VIP customers
        "order_monitoring",  # Real-time order monitoring
        "overtime_alerts",  # Alert on table occupancy time
        "dish_tracking",  # Track dish status in kitchen
        "payment_tracking",  # Monitor payment methods
        "reservation_management",  # Full reservation features
        "team_management",  # Waiter assignment and tracking
        "analytics_export",  # Export capabilities
        "custom_rules",  # Allow custom business rules
        "learning_optimization",  # Field importance learning
        "multi_language",  # Multi-language support
    ],
    custom_rules={
        "vip_auto_alert": True,
        "overtime_threshold_normal": 120,  # 2 hours
        "overtime_threshold_vip": 180,  # 3 hours
        "pending_dishes_warning": 20,  # 20 minutes
        "checkout_timeout_threshold": 10,  # 10 minutes
        "cleanup_emergency_threshold": 30,  # 30 minutes before next reservation
        "enable_dish_image_preview": True,
        "enable_customer_history": True,
        "enable_room_management": True,
    },
)


# ============================================================================
# STANDARD Preset (å°å¨ä¸èµ·)
# ============================================================================

STANDARD_PRESET = PresetConfig(
    business_type=BusinessType.STANDARD,
    max_fields=5,
    visible_categories=[
        "identity",
        "status",
        "financial",
        "service",
        "timing",
    ],
    visible_fields=[
        # Identity (2)
        "vip_badge",
        "member_name",
        # Status (3)
        "status",
        "payment_status",
        "arrears_flag",
        # Financial (2)
        "amount",
        "per_capita",
        # Service (5)
        "guest_count",
        "waiter",
        "service_requests",
        "dish_progress",
        "vip_level",
        # Timing (4)
        "duration",
        "checkout_duration",
        "cleanup_duration",
        "last_order_time",
        # Custom (2)
        "birthday_badge",
        "upcoming_reservation",
    ],
    hidden_fields=[
        "discount_amount",
        "deposit_balance",
        "idle_duration",
        "room_name",
        "no_show_warning",
        "special_requirements",
        "dish_alert",
        "queue_count",
        "turnover_time",
        "turnover_count",
    ],
    sort_priority={
        "birthday_badge": 95,
        "vip_badge": 90,
        "amount": 85,
        "status": 85,
        "checkout_duration": 80,
        "duration": 75,
        "member_name": 65,
        "dish_progress": 60,
    },
    refresh_interval_ms=3000,
    features_enabled=[
        "vip_tracking",
        "order_monitoring",
        "overtime_alerts",
        "dish_tracking",
        "payment_tracking",
        "reservation_management",
        "team_management",
        "learning_optimization",
    ],
    custom_rules={
        "vip_auto_alert": True,
        "overtime_threshold_normal": 120,
        "overtime_threshold_vip": 180,
        "pending_dishes_warning": 20,
        "checkout_timeout_threshold": 10,
        "enable_customer_history": True,
        "enable_dish_image_preview": False,
        "enable_room_management": False,
    },
)


# ============================================================================
# LITE Preset (æé»çº¿)
# ============================================================================

LITE_PRESET = PresetConfig(
    business_type=BusinessType.LITE,
    max_fields=4,
    visible_categories=[
        "status",
        "financial",
        "service",
        "timing",
    ],
    visible_fields=[
        # Status (1)
        "status",
        # Financial (1)
        "amount",
        # Service (2)
        "guest_count",
        "dish_progress",
        # Timing (2)
        "duration",
        "checkout_duration",
    ],
    hidden_fields=[
        "vip_badge",
        "member_name",
        "payment_status",
        "arrears_flag",
        "per_capita",
        "discount_amount",
        "deposit_balance",
        "waiter",
        "service_requests",
        "vip_level",
        "idle_duration",
        "cleanup_duration",
        "last_order_time",
        "birthday_badge",
        "upcoming_reservation",
        "room_name",
        "no_show_warning",
        "special_requirements",
        "dish_alert",
        "queue_count",
        "turnover_time",
        "turnover_count",
        "reservation_name",
        "reservation_headcount",
    ],
    sort_priority={
        "status": 100,
        "amount": 90,
        "checkout_duration": 85,
        "duration": 80,
        "guest_count": 75,
        "dish_progress": 70,
    },
    refresh_interval_ms=5000,
    features_enabled=[
        "order_monitoring",
        "overtime_alerts",
    ],
    custom_rules={
        "vip_auto_alert": False,
        "overtime_threshold_normal": 120,
        "pending_dishes_warning": 20,
        "checkout_timeout_threshold": 10,
        "enable_customer_history": False,
        "enable_dish_image_preview": False,
        "enable_room_management": False,
    },
)


# ============================================================================
# Preset Registry and Factory
# ============================================================================

PRESET_REGISTRY: Dict[BusinessType, PresetConfig] = {
    BusinessType.PRO: PRO_PRESET,
    BusinessType.STANDARD: STANDARD_PRESET,
    BusinessType.LITE: LITE_PRESET,
}


def get_preset(business_type: BusinessType) -> PresetConfig:
    """
    Get preset configuration for a business type.

    Args:
        business_type: BusinessType enum value

    Returns:
        PresetConfig for the specified business type

    Raises:
        ValueError if business_type is not recognized
    """
    if business_type not in PRESET_REGISTRY:
        raise ValueError(f"Unknown business type: {business_type}")
    return PRESET_REGISTRY[business_type]


def get_preset_by_name(business_type_name: str) -> PresetConfig:
    """
    Get preset configuration by string name.

    Args:
        business_type_name: String name of business type (pro/standard/lite)

    Returns:
        PresetConfig for the specified business type

    Raises:
        ValueError if business_type_name is not recognized
    """
    try:
        business_type = BusinessType(business_type_name.lower())
        return get_preset(business_type)
    except ValueError:
        raise ValueError(
            f"Unknown business type: {business_type_name}. Valid values: {', '.join([bt.value for bt in BusinessType])}"
        )


def get_all_presets() -> Dict[BusinessType, PresetConfig]:
    """Get all available presets."""
    return PRESET_REGISTRY.copy()


def list_preset_names() -> List[str]:
    """Get list of all preset names."""
    return [bt.value for bt in BusinessType]


def get_preset_features(business_type: BusinessType) -> List[str]:
    """Get enabled features for a business type."""
    preset = get_preset(business_type)
    return preset.features_enabled


def is_feature_enabled(business_type: BusinessType, feature: str) -> bool:
    """Check if a feature is enabled for a business type."""
    preset = get_preset(business_type)
    return feature in preset.features_enabled


def get_visible_fields_for_type(business_type: BusinessType) -> List[str]:
    """Get list of visible fields for a business type."""
    preset = get_preset(business_type)
    return preset.visible_fields


def get_hidden_fields_for_type(business_type: BusinessType) -> List[str]:
    """Get list of hidden fields for a business type."""
    preset = get_preset(business_type)
    return preset.hidden_fields


def customize_preset(
    base_business_type: BusinessType,
    overrides: Dict[str, Any],
) -> PresetConfig:
    """
    Create a customized preset based on a base preset.

    Args:
        base_business_type: Base business type to customize
        overrides: Dictionary of fields to override

    Returns:
        New PresetConfig with customizations applied
    """
    base_preset = get_preset(base_business_type)

    # Create a new config with overrides
    custom_config = base_preset.model_copy(update=overrides)
    return custom_config


def validate_preset_fields(
    business_type: BusinessType,
    fields: List[str],
) -> tuple[bool, Optional[str]]:
    """
    Validate that requested fields are allowed for business type.

    Args:
        business_type: BusinessType
        fields: List of field keys to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    preset = get_preset(business_type)
    visible_fields = set(preset.visible_fields)
    hidden_fields = set(preset.hidden_fields)

    for field in fields:
        if field in hidden_fields:
            return False, f"Field '{field}' is hidden for {business_type.value} type"

    return True, None


# ============================================================================
# Preset Comparison and Migration
# ============================================================================


def compare_presets(
    business_type1: BusinessType,
    business_type2: BusinessType,
) -> Dict[str, Any]:
    """
    Compare two presets and show differences.

    Args:
        business_type1: First business type
        business_type2: Second business type

    Returns:
        Dictionary showing differences
    """
    preset1 = get_preset(business_type1)
    preset2 = get_preset(business_type2)

    visible1 = set(preset1.visible_fields)
    visible2 = set(preset2.visible_fields)

    return {
        "business_type1": business_type1.value,
        "business_type2": business_type2.value,
        "only_in_1": list(visible1 - visible2),
        "only_in_2": list(visible2 - visible1),
        "common_fields": list(visible1 & visible2),
        "max_fields_1": preset1.max_fields,
        "max_fields_2": preset2.max_fields,
        "features_only_in_1": list(set(preset1.features_enabled) - set(preset2.features_enabled)),
        "features_only_in_2": list(set(preset2.features_enabled) - set(preset1.features_enabled)),
    }


def get_migration_path(
    from_business_type: BusinessType,
    to_business_type: BusinessType,
) -> Dict[str, Any]:
    """
    Get migration recommendations when changing business type.

    Args:
        from_business_type: Current business type
        to_business_type: Target business type

    Returns:
        Migration plan with recommendations
    """
    from_preset = get_preset(from_business_type)
    to_preset = get_preset(to_business_type)

    from_visible = set(from_preset.visible_fields)
    to_visible = set(to_preset.visible_fields)

    will_be_hidden = from_visible - to_visible
    will_be_shown = to_visible - from_visible

    return {
        "from_type": from_business_type.value,
        "to_type": to_business_type.value,
        "fields_will_be_hidden": list(will_be_hidden),
        "fields_will_be_shown": list(will_be_shown),
        "preserved_fields": list(from_visible & to_visible),
        "warning_data_loss": len(will_be_hidden) > 0,
        "feature_changes": {
            "features_will_be_disabled": list(set(from_preset.features_enabled) - set(to_preset.features_enabled)),
            "features_will_be_enabled": list(set(to_preset.features_enabled) - set(from_preset.features_enabled)),
        },
    }
