"""
TunxiangOS Smart Table Card - Field Definitions
Module: services/tx-trade/src/config/table_card_field_defs.py

Complete field definitions and schema for all possible smart table card fields.
"""

from typing import Any, Dict, List, Optional
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict


class FieldCategory(str, Enum):
    """Field category for organizational purposes."""
    IDENTITY = "identity"      # Table/customer identification
    STATUS = "status"          # Current state/status
    FINANCIAL = "financial"    # Financial/monetary data
    SERVICE = "service"        # Service-related flags/data
    TIMING = "timing"          # Time-based metrics
    CUSTOM = "custom"          # Custom/extension fields


class FieldType(str, Enum):
    """Data type of field value."""
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATETIME = "datetime"
    DURATION = "duration"
    CURRENCY = "currency"
    PERCENTAGE = "percentage"
    BADGE = "badge"
    PROGRESS = "progress"
    STATUS_INDICATOR = "status_indicator"


class FieldVisibility(str, Enum):
    """Default visibility settings."""
    ALWAYS = "always"
    PRO_ONLY = "pro_only"
    CONDITIONAL = "conditional"
    HIDDEN = "hidden"


class FieldDefinition(BaseModel):
    """Complete definition of a table card field."""
    model_config = ConfigDict(from_attributes=True)

    key: str = Field(description="Unique field key identifier")
    label: str = Field(description="Display label (Chinese)")
    category: FieldCategory = Field(description="Field category")
    field_type: FieldType = Field(description="Data type")
    description: str = Field(description="Field description")
    base_priority: int = Field(default=50, ge=0, le=100, description="Base priority score")
    default_visible: bool = Field(default=True, description="Default visibility")
    visibility: FieldVisibility = Field(default=FieldVisibility.ALWAYS)
    render_hint: Optional[str] = Field(
        default=None,
        description="Frontend render hint (e.g., 'large', 'warning_color', 'blink')"
    )
    business_types: List[str] = Field(
        default=["pro", "standard", "lite"],
        description="Business types where visible"
    )
    requires_data_source: Optional[str] = Field(
        default=None,
        description="Required data source (table, order, customer, reservation)"
    )
    computed_from: Optional[List[str]] = Field(
        default=None,
        description="Fields this is computed from"
    )
    validation_rules: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Validation rules for values"
    )
    formatting: Optional[Dict[str, str]] = Field(
        default=None,
        description="Formatting hints (precision, unit, etc.)"
    )


# ============================================================================
# Field Definitions Catalog
# ============================================================================

FIELD_DEFINITIONS: Dict[str, FieldDefinition] = {
    # ========== IDENTITY FIELDS ==========
    "table_no": FieldDefinition(
        key="table_no",
        label="æ¡å·",
        category=FieldCategory.IDENTITY,
        field_type=FieldType.STRING,
        description="Table number/identifier",
        base_priority=100,
        requires_data_source="table",
        formatting={"prefix": ""},
    ),
    "area": FieldDefinition(
        key="area",
        label="åºå",
        category=FieldCategory.IDENTITY,
        field_type=FieldType.STRING,
        description="Area/zone in restaurant",
        base_priority=60,
        requires_data_source="table",
    ),
    "seats": FieldDefinition(
        key="seats",
        label="åº§ä½",
        category=FieldCategory.IDENTITY,
        field_type=FieldType.NUMBER,
        description="Number of seats at table",
        base_priority=55,
        requires_data_source="table",
        formatting={"unit": "äºº"},
    ),
    "vip_badge": FieldDefinition(
        key="vip_badge",
        label="VIP",
        category=FieldCategory.IDENTITY,
        field_type=FieldType.BADGE,
        description="VIP customer indicator",
        base_priority=70,
        visibility=FieldVisibility.CONDITIONAL,
        render_hint="warning_color",
        requires_data_source="customer",
        business_types=["pro", "standard"],
    ),
    "member_name": FieldDefinition(
        key="member_name",
        label="ä¼åå",
        category=FieldCategory.IDENTITY,
        field_type=FieldType.STRING,
        description="Customer name if member",
        base_priority=65,
        visibility=FieldVisibility.CONDITIONAL,
        requires_data_source="customer",
        business_types=["pro", "standard"],
    ),

    # ========== STATUS FIELDS ==========
    "status": FieldDefinition(
        key="status",
        label="ç¶æ",
        category=FieldCategory.STATUS,
        field_type=FieldType.STATUS_INDICATOR,
        description="Current table status",
        base_priority=90,
        requires_data_source="table",
        formatting={"colors": {"empty": "green", "dining": "blue", "reserved": "yellow"}},
    ),
    "payment_status": FieldDefinition(
        key="payment_status",
        label="ä»æ¬¾",
        category=FieldCategory.STATUS,
        field_type=FieldType.STATUS_INDICATOR,
        description="Payment method/status",
        base_priority=40,
        visibility=FieldVisibility.CONDITIONAL,
        requires_data_source="order",
        business_types=["pro", "standard"],
    ),
    "arrears_flag": FieldDefinition(
        key="arrears_flag",
        label="æè´¦",
        category=FieldCategory.STATUS,
        field_type=FieldType.BADGE,
        description="Whether customer has arrears/tab",
        base_priority=70,
        visibility=FieldVisibility.CONDITIONAL,
        render_hint="critical_color",
        requires_data_source="customer",
    ),
    "no_show_warning": FieldDefinition(
        key="no_show_warning",
        label="çä¼¼ç½çº¦",
        category=FieldCategory.STATUS,
        field_type=FieldType.BADGE,
        description="Possible no-show for reservation",
        base_priority=80,
        visibility=FieldVisibility.CONDITIONAL,
        render_hint="critical_color_blink",
        requires_data_source="reservation",
    ),

    # ========== FINANCIAL FIELDS ==========
    "amount": FieldDefinition(
        key="amount",
        label="æ¶è´¹",
        category=FieldCategory.FINANCIAL,
        field_type=FieldType.CURRENCY,
        description="Total order amount",
        base_priority=80,
        requires_data_source="order",
        formatting={"currency": "CNY", "decimals": 2},
    ),
    "per_capita": FieldDefinition(
        key="per_capita",
        label="äººå",
        category=FieldCategory.FINANCIAL,
        field_type=FieldType.CURRENCY,
        description="Per-capita spending",
        base_priority=65,
        visibility=FieldVisibility.CONDITIONAL,
        requires_data_source="order",
        computed_from=["amount", "guest_count"],
        formatting={"currency": "CNY", "decimals": 2},
        business_types=["pro", "standard"],
    ),
    "discount_amount": FieldDefinition(
        key="discount_amount",
        label="ææ£",
        category=FieldCategory.FINANCIAL,
        field_type=FieldType.CURRENCY,
        description="Discount/promotion amount",
        base_priority=40,
        visibility=FieldVisibility.CONDITIONAL,
        requires_data_source="order",
        formatting={"currency": "CNY", "decimals": 2},
        business_types=["pro", "standard"],
    ),
    "deposit_balance": FieldDefinition(
        key="deposit_balance",
        label="æ¼é",
        category=FieldCategory.FINANCIAL,
        field_type=FieldType.CURRENCY,
        description="Remaining deposit/prepay balance",
        base_priority=35,
        visibility=FieldVisibility.PRO_ONLY,
        requires_data_source="order",
        formatting={"currency": "CNY", "decimals": 2},
        business_types=["pro"],
    ),

    # ========== SERVICE FIELDS ==========
    "guest_count": FieldDefinition(
        key="guest_count",
        label="äººæ°",
        category=FieldCategory.SERVICE,
        field_type=FieldType.STRING,  # "3/4" format
        description="Current guests vs. seats",
        base_priority=60,
        requires_data_source="table",
        formatting={"format": "current/total"},
    ),
    "waiter": FieldDefinition(
        key="waiter",
        label="æå¡å",
        category=FieldCategory.SERVICE,
        field_type=FieldType.STRING,
        description="Assigned waiter name",
        base_priority=30,
        visibility=FieldVisibility.CONDITIONAL,
        requires_data_source="order",
        business_types=["pro", "standard"],
    ),
    "special_requirements": FieldDefinition(
        key="special_requirements",
        label="ç¹æ®éæ±",
        category=FieldCategory.SERVICE,
        field_type=FieldType.STRING,
        description="Special requirements (allergies, preferences, etc.)",
        base_priority=50,
        visibility=FieldVisibility.CONDITIONAL,
        requires_data_source="reservation",
        business_types=["pro", "standard"],
    ),
    "service_requests": FieldDefinition(
        key="service_requests",
        label="æå¡è¯·æ±",
        category=FieldCategory.SERVICE,
        field_type=FieldType.BADGE,
        description="Active service requests (check, refill, etc.)",
        base_priority=65,
        visibility=FieldVisibility.CONDITIONAL,
        render_hint="warning_color",
        requires_data_source="order",
        business_types=["pro", "standard"],
    ),
    "dish_progress": FieldDefinition(
        key="dish_progress",
        label="ä¸è",
        category=FieldCategory.SERVICE,
        field_type=FieldType.PROGRESS,
        description="Dishes served vs. ordered",
        base_priority=55,
        visibility=FieldVisibility.CONDITIONAL,
        requires_data_source="order",
        computed_from=["order_items"],
        formatting={"format": "served/total"},
        business_types=["pro", "standard"],
    ),
    "dish_alert": FieldDefinition(
        key="dish_alert",
        label="å¬è",
        category=FieldCategory.SERVICE,
        field_type=FieldType.BADGE,
        description="Pending dishes alert",
        base_priority=70,
        visibility=FieldVisibility.CONDITIONAL,
        render_hint="critical_color_blink",
        requires_data_source="order",
        business_types=["pro", "standard"],
    ),
    "queue_count": FieldDefinition(
        key="queue_count",
        label="ç­ä½",
        category=FieldCategory.SERVICE,
        field_type=FieldType.NUMBER,
        description="Number of customers waiting in queue",
        base_priority=90,
        visibility=FieldVisibility.CONDITIONAL,
        render_hint="critical_color",
        requires_data_source="table",
        formatting={"unit": "äºº"},
        business_types=["pro", "standard"],
    ),
    "vip_level": FieldDefinition(
        key="vip_level",
        label="ä¼åç­çº§",
        category=FieldCategory.SERVICE,
        field_type=FieldType.STRING,
        description="Customer VIP level (S1, S2, etc.)",
        base_priority=60,
        visibility=FieldVisibility.CONDITIONAL,
        requires_data_source="customer",
        business_types=["pro", "standard"],
    ),

    # ========== TIMING FIELDS ==========
    "duration": FieldDefinition(
        key="duration",
        label="æ¶é¿",
        category=FieldCategory.TIMING,
        field_type=FieldType.DURATION,
        description="Time spent dining",
        base_priority=60,
        visibility=FieldVisibility.CONDITIONAL,
        requires_data_source="table",
        computed_from=["seated_at"],
        formatting={"unit": "min"},
        business_types=["pro", "standard"],
    ),
    "idle_duration": FieldDefinition(
        key="idle_duration",
        label="ç©ºé²æ¶é¿",
        category=FieldCategory.TIMING,
        field_type=FieldType.DURATION,
        description="Time table has been empty",
        base_priority=45,
        visibility=FieldVisibility.CONDITIONAL,
        requires_data_source="table",
        formatting={"unit": "min"},
        business_types=["pro", "standard"],
    ),
    "checkout_duration": FieldDefinition(
        key="checkout_duration",
        label="å¾ç»æ¶é¿",
        category=FieldCategory.TIMING,
        field_type=FieldType.DURATION,
        description="Time spent waiting for checkout",
        base_priority=85,
        visibility=FieldVisibility.CONDITIONAL,
        render_hint="warning_color",
        requires_data_source="table",
        formatting={"unit": "min"},
        business_types=["pro", "standard"],
    ),
    "cleanup_duration": FieldDefinition(
        key="cleanup_duration",
        label="å¾æ¸æ¶é¿",
        category=FieldCategory.TIMING,
        field_type=FieldType.DURATION,
        description="Time table has been waiting cleanup",
        base_priority=80,
        visibility=FieldVisibility.CONDITIONAL,
        requires_data_source="table",
        formatting={"unit": "min"},
        business_types=["pro", "standard"],
    ),
    "last_order_time": FieldDefinition(
        key="last_order_time",
        label="æåç¹é¤",
        category=FieldCategory.TIMING,
        field_type=FieldType.DURATION,
        description="Time since last order placed",
        base_priority=40,
        visibility=FieldVisibility.CONDITIONAL,
        requires_data_source="order",
        formatting={"unit": "min"},
        business_types=["pro", "standard"],
    ),
    "turnover_time": FieldDefinition(
        key="turnover_time",
        label="ç¿»å°æ¶é´",
        category=FieldCategory.TIMING,
        field_type=FieldType.DATETIME,
        description="Last table turnover time",
        base_priority=40,
        visibility=FieldVisibility.CONDITIONAL,
        requires_data_source="table",
        business_types=["pro", "standard"],
    ),
    "turnover_count": FieldDefinition(
        key="turnover_count",
        label="ä»æ¥ç¿»å°",
        category=FieldCategory.TIMING,
        field_type=FieldType.NUMBER,
        description="Number of turnovers today",
        base_priority=35,
        visibility=FieldVisibility.CONDITIONAL,
        requires_data_source="table",
        business_types=["pro", "standard"],
    ),
    "reservation_time": FieldDefinition(
        key="reservation_time",
        label="é¢è®¢æ¶é´",
        category=FieldCategory.TIMING,
        field_type=FieldType.DATETIME,
        description="Reservation time",
        base_priority=75,
        visibility=FieldVisibility.CONDITIONAL,
        requires_data_source="reservation",
        business_types=["pro", "standard"],
    ),

    # ========== CUSTOM/EXTENSION FIELDS ==========
    "birthday_badge": FieldDefinition(
        key="birthday_badge",
        label="çæ¥",
        category=FieldCategory.CUSTOM,
        field_type=FieldType.BADGE,
        description="Customer birthday indicator",
        base_priority=100,
        visibility=FieldVisibility.CONDITIONAL,
        render_hint="celebration_color",
        requires_data_source="customer",
        business_types=["pro", "standard"],
    ),
    "upcoming_reservation": FieldDefinition(
        key="upcoming_reservation",
        label="é¢è®¢é¢è­¦",
        category=FieldCategory.CUSTOM,
        field_type=FieldType.BADGE,
        description="Upcoming reservation warning",
        base_priority=60,
        visibility=FieldVisibility.CONDITIONAL,
        render_hint="info_color",
        requires_data_source="reservation",
    ),
    "room_name": FieldDefinition(
        key="room_name",
        label="åé´å",
        category=FieldCategory.IDENTITY,
        field_type=FieldType.STRING,
        description="Private room name",
        base_priority=50,
        visibility=FieldVisibility.PRO_ONLY,
        requires_data_source="table",
        business_types=["pro"],
    ),
    "reservation_name": FieldDefinition(
        key="reservation_name",
        label="é¢è®¢äºº",
        category=FieldCategory.IDENTITY,
        field_type=FieldType.STRING,
        description="Reservation customer name",
        base_priority=70,
        visibility=FieldVisibility.CONDITIONAL,
        requires_data_source="reservation",
    ),
    "reservation_headcount": FieldDefinition(
        key="reservation_headcount",
        label="é¢è®¢äººæ°",
        category=FieldCategory.SERVICE,
        field_type=FieldType.NUMBER,
        description="Reserved headcount",
        base_priority=65,
        visibility=FieldVisibility.CONDITIONAL,
        requires_data_source="reservation",
        formatting={"unit": "äºº"},
    ),
}


# ============================================================================
# Field Groups and Presets
# ============================================================================

FIELD_GROUPS = {
    "identity": ["table_no", "area", "seats", "vip_badge", "member_name"],
    "status": ["status", "payment_status", "arrears_flag", "no_show_warning"],
    "financial": ["amount", "per_capita", "discount_amount", "deposit_balance"],
    "service": ["guest_count", "waiter", "service_requests", "dish_progress", "dish_alert", "queue_count", "vip_level"],
    "timing": ["duration", "idle_duration", "checkout_duration", "cleanup_duration", "last_order_time"],
    "custom": ["birthday_badge", "upcoming_reservation"],
}


def get_field_definition(field_key: str) -> Optional[FieldDefinition]:
    """Get a field definition by key."""
    return FIELD_DEFINITIONS.get(field_key)


def get_fields_by_category(category: FieldCategory) -> Dict[str, FieldDefinition]:
    """Get all fields in a category."""
    return {k: v for k, v in FIELD_DEFINITIONS.items() if v.category == category}


def get_fields_by_business_type(business_type: str) -> Dict[str, FieldDefinition]:
    """Get all fields available for a business type."""
    return {
        k: v
        for k, v in FIELD_DEFINITIONS.items()
        if business_type in v.business_types
    }


def validate_field_key(field_key: str) -> bool:
    """Check if field key is valid."""
    return field_key in FIELD_DEFINITIONS
