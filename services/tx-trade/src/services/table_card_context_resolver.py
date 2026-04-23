"""
TunxiangOS Smart Table Card - Context Resolver Service
Module: services/tx-trade/src/services/table_card_context_resolver.py

Core context resolver with 9 business rules (R1-R9).
Resolves which fields to display on table cards based on current context.
"""

import logging
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ============================================================================
# Enums and Models
# ============================================================================


class AlertLevel(str, Enum):
    """Alert level for card fields."""

    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"


class MealPeriod(str, Enum):
    """Meal period classification."""

    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    LATE_NIGHT = "late_night"


class TableStatus(str, Enum):
    """Table status values."""

    EMPTY = "empty"
    DINING = "dining"
    RESERVED = "reserved"
    PENDING_CHECKOUT = "pending_checkout"
    PENDING_CLEANUP = "pending_cleanup"


class BusinessType(str, Enum):
    """Business type classification."""

    PRO = "pro"  # Full-featured (å°å®«å)
    STANDARD = "standard"  # Standard features (å°å¨ä¸èµ·)
    LITE = "lite"  # Minimal features (æé»çº¿)


class CardFieldDef(BaseModel):
    """Field definition for table card display."""

    key: str
    label: str
    category: str  # identity, status, financial, service, timing, custom
    base_priority: int = Field(default=50, ge=0, le=100)
    alert_level: AlertLevel = AlertLevel.NORMAL
    render_hint: Optional[str] = None  # format hint for frontend


class CardField(BaseModel):
    """Resolved card field with value and priority."""

    key: str
    label: str
    value: Any
    priority: int = Field(ge=0, le=100)
    alert: AlertLevel = AlertLevel.NORMAL
    render_hint: Optional[str] = None


class ContextRule(BaseModel):
    """Context-aware rule for field adjustment."""

    rule_id: str  # R1, R2, ..., R9
    condition: str
    priority_delta: int = 0
    fields_to_add: List[str] = []
    fields_to_remove: List[str] = []
    alert_overrides: Dict[str, AlertLevel] = {}


class ResolveContext(BaseModel):
    """Context for field resolution."""

    tenant_id: str
    store_id: str
    table_id: str
    table_no: str
    meal_period: MealPeriod
    business_type: BusinessType
    is_weekend: bool
    current_time: datetime


# ============================================================================
# Status Field Pool Definitions
# ============================================================================

STATUS_FIELD_POOLS = {
    TableStatus.EMPTY: [
        CardFieldDef(key="turnover_time", label="ä¸æ¬¡ç¿»å°", category="timing", base_priority=40),
        CardFieldDef(key="turnover_count", label="ä»æ¥ç¿»å°", category="timing", base_priority=35),
        CardFieldDef(key="idle_duration", label="ç©ºé²æ¶é¿", category="timing", base_priority=45),
        CardFieldDef(key="upcoming_reservation", label="é¢è®¢é¢è­¦", category="service", base_priority=60),
        CardFieldDef(key="reservation_time", label="é¢è®¢æ¶é´", category="timing", base_priority=55),
    ],
    TableStatus.DINING: [
        CardFieldDef(key="vip_badge", label="VIP", category="identity", base_priority=70),
        CardFieldDef(key="member_name", label="ä¼å", category="identity", base_priority=65),
        CardFieldDef(key="guest_count", label="äººæ°", category="service", base_priority=60),
        CardFieldDef(key="amount", label="æ¶è´¹", category="financial", base_priority=65),
        CardFieldDef(key="duration", label="æ¶é¿", category="timing", base_priority=60),
        CardFieldDef(key="dish_progress", label="ä¸è", category="service", base_priority=55),
        CardFieldDef(key="waiter", label="æå¡å", category="service", base_priority=30),
        CardFieldDef(key="last_order_time", label="æåç¹é¤", category="timing", base_priority=40),
    ],
    TableStatus.RESERVED: [
        CardFieldDef(key="reservation_name", label="é¢è®¢äºº", category="identity", base_priority=70),
        CardFieldDef(key="reservation_time", label="é¢è®¢æ¶é´", category="timing", base_priority=75),
        CardFieldDef(key="reservation_headcount", label="äººæ°", category="service", base_priority=65),
        CardFieldDef(key="special_requirements", label="ç¹æ®éæ±", category="service", base_priority=50),
        CardFieldDef(key="vip_level", label="ä¼åç­çº§", category="identity", base_priority=60),
        CardFieldDef(key="no_show_warning", label="çä¼¼ç½çº¦", category="status", base_priority=80),
    ],
    TableStatus.PENDING_CHECKOUT: [
        CardFieldDef(key="amount", label="æ¶è´¹", category="financial", base_priority=90),
        CardFieldDef(key="checkout_duration", label="å¾ç»æ¶é¿", category="timing", base_priority=85),
        CardFieldDef(key="discount_amount", label="ææ£", category="financial", base_priority=40),
        CardFieldDef(key="payment_status", label="ä»æ¬¾æ¹å¼", category="financial", base_priority=50),
        CardFieldDef(key="arrears_flag", label="æè´¦æ è®°", category="status", base_priority=70),
    ],
    TableStatus.PENDING_CLEANUP: [
        CardFieldDef(key="cleanup_duration", label="å¾æ¸æ¶é¿", category="timing", base_priority=80),
        CardFieldDef(key="next_reservation", label="ä¸ä¸é¢è®¢", category="service", base_priority=85),
        CardFieldDef(key="queue_count", label="ç­ä½äººæ°", category="service", base_priority=90),
    ],
}

# ============================================================================
# Business Rules (R1-R9)
# ============================================================================


class BusinessRuleEngine:
    """Engine for applying business context rules."""

    @staticmethod
    def rule_r1_vip_priority(
        context: ResolveContext,
        scored_fields: Dict[str, int],
        table_data: Dict[str, Any],
        customer_data: Optional[Dict[str, Any]],
    ) -> Tuple[Dict[str, int], List[str], Dict[str, AlertLevel]]:
        """R1: VIPææ - Boost VIP customer fields."""
        if not customer_data or customer_data.get("rfm_level") not in ["S1", "S2"]:
            return scored_fields, [], {}

        additions = ["vip_badge", "member_name"]
        adjustments = {
            "vip_badge": 50,
            "member_name": 40,
        }
        for field_key, delta in adjustments.items():
            scored_fields[field_key] = scored_fields.get(field_key, 50) + delta

        return scored_fields, additions, {}

    @staticmethod
    def rule_r2_overtime_alert(
        context: ResolveContext,
        scored_fields: Dict[str, int],
        table_data: Dict[str, Any],
        order_data: Optional[Dict[str, Any]],
    ) -> Tuple[Dict[str, int], List[str], Dict[str, AlertLevel]]:
        """R2: ç¨é¤è¶æ¶è­¦å - Alert on extended dining duration."""
        if table_data.get("status") != TableStatus.DINING.value:
            return scored_fields, [], {}

        seated_at = table_data.get("seated_at")
        if not seated_at:
            return scored_fields, [], {}

        duration_minutes = (context.current_time - seated_at).total_seconds() / 60
        vip = True if table_data.get("is_vip") else False
        threshold = 180 if vip else 120  # 3h for VIP, 2h for normal

        alerts = {}
        if duration_minutes > threshold:
            alerts["duration"] = AlertLevel.CRITICAL
            scored_fields["duration"] = scored_fields.get("duration", 50) + 30

        return scored_fields, [], alerts

    @staticmethod
    def rule_r3_pending_dishes(
        context: ResolveContext,
        scored_fields: Dict[str, int],
        table_data: Dict[str, Any],
        order_data: Optional[Dict[str, Any]],
    ) -> Tuple[Dict[str, int], List[str], Dict[str, AlertLevel]]:
        """R3: å¬èé¢è­¦ - Alert on pending dishes."""
        if not order_data or table_data.get("status") != TableStatus.DINING.value:
            return scored_fields, [], {}

        pending_items = order_data.get("pending_items", [])
        if not pending_items:
            return scored_fields, [], {}

        oldest_pending = min([item.get("sent_to_kds_at") for item in pending_items if item.get("sent_to_kds_at")])
        if not oldest_pending:
            return scored_fields, [], {}

        pending_minutes = (context.current_time - oldest_pending).total_seconds() / 60
        if pending_minutes > 20:
            return scored_fields, ["dish_alert"], {"dish_alert": AlertLevel.CRITICAL}

        return scored_fields, [], {}

    @staticmethod
    def rule_r4_reservation_countdown(
        context: ResolveContext,
        scored_fields: Dict[str, int],
        table_data: Dict[str, Any],
        reservation_data: Optional[Dict[str, Any]],
    ) -> Tuple[Dict[str, int], List[str], Dict[str, AlertLevel]]:
        """R4: é¢è®¢å³å°å°è¾¾ - Highlight upcoming reservations."""
        if table_data.get("status") != TableStatus.EMPTY.value:
            return scored_fields, [], {}

        if not reservation_data:
            return scored_fields, [], {}

        reservation_time = reservation_data.get("reservation_time")
        if not reservation_time:
            return scored_fields, [], {}

        time_until = (reservation_time - context.current_time).total_seconds() / 60
        if 0 < time_until <= 120:  # Within 2 hours
            scored_fields["upcoming_reservation"] = scored_fields.get("upcoming_reservation", 50) + 35
            return scored_fields, ["reservation_time", "reservation_name"], {}

        return scored_fields, [], {}

    @staticmethod
    def rule_r5_checkout_timeout(
        context: ResolveContext,
        scored_fields: Dict[str, int],
        table_data: Dict[str, Any],
        order_data: Optional[Dict[str, Any]],
    ) -> Tuple[Dict[str, int], List[str], Dict[str, AlertLevel]]:
        """R5: å¾ç»è¶æ¶ - Alert on slow checkout."""
        if table_data.get("status") != TableStatus.PENDING_CHECKOUT.value:
            return scored_fields, [], {}

        checkout_at = table_data.get("checkout_at")
        if not checkout_at:
            return scored_fields, [], {}

        checkout_minutes = (context.current_time - checkout_at).total_seconds() / 60
        if checkout_minutes > 10:
            alerts = {"amount": AlertLevel.CRITICAL}
            scored_fields["amount"] = scored_fields.get("amount", 50) + 45
            return scored_fields, [], alerts

        return scored_fields, [], {}

    @staticmethod
    def rule_r6_emergency_cleanup(
        context: ResolveContext,
        scored_fields: Dict[str, int],
        table_data: Dict[str, Any],
        next_reservation: Optional[Dict[str, Any]],
    ) -> Tuple[Dict[str, int], List[str], Dict[str, AlertLevel]]:
        """R6: ç´§æ¥æ¸å° - Highlight urgent cleanup before next reservation."""
        if table_data.get("status") != TableStatus.PENDING_CLEANUP.value:
            return scored_fields, [], {}

        if not next_reservation:
            return scored_fields, [], {}

        reservation_time = next_reservation.get("reservation_time")
        if not reservation_time:
            return scored_fields, [], {}

        time_until = (reservation_time - context.current_time).total_seconds() / 60
        if time_until < 30:
            alerts = {"cleanup_duration": AlertLevel.CRITICAL}
            scored_fields["cleanup_duration"] = scored_fields.get("cleanup_duration", 50) + 50
            return scored_fields, ["next_reservation"], alerts

        return scored_fields, [], {}

    @staticmethod
    def rule_r7_lunch_turnover_focus(
        context: ResolveContext,
        scored_fields: Dict[str, int],
        table_data: Dict[str, Any],
    ) -> Tuple[Dict[str, int], List[str], Dict[str, AlertLevel]]:
        """R7: åå¸ç¿»å°ä¼å - Prioritize turnover metrics during lunch."""
        if context.meal_period != MealPeriod.LUNCH:
            return scored_fields, [], {}

        scored_fields["turnover_count"] = scored_fields.get("turnover_count", 50) + 20
        scored_fields["duration"] = scored_fields.get("duration", 50) + 20

        return scored_fields, [], {}

    @staticmethod
    def rule_r8_dinner_per_capita_focus(
        context: ResolveContext,
        scored_fields: Dict[str, int],
        table_data: Dict[str, Any],
        order_data: Optional[Dict[str, Any]],
    ) -> Tuple[Dict[str, int], List[str], Dict[str, AlertLevel]]:
        """R8: æå¸å®¢åä¼å - Prioritize per-capita spending during dinner."""
        if context.meal_period != MealPeriod.DINNER:
            return scored_fields, [], {}

        scored_fields["amount"] = scored_fields.get("amount", 50) + 20

        return scored_fields, [], {}

    @staticmethod
    def rule_r9_birthday_celebration(
        context: ResolveContext,
        scored_fields: Dict[str, int],
        customer_data: Optional[Dict[str, Any]],
    ) -> Tuple[Dict[str, int], List[str], Dict[str, AlertLevel]]:
        """R9: çæ¥æé - Highlight customer birthday."""
        if not customer_data:
            return scored_fields, [], {}

        birth_date = customer_data.get("birth_date")
        if not birth_date:
            return scored_fields, [], {}

        today = context.current_time.date()
        if birth_date.month == today.month and birth_date.day == today.day:
            scored_fields["birthday_badge"] = 100
            return scored_fields, ["birthday_badge"], {"birthday_badge": AlertLevel.CRITICAL}

        return scored_fields, [], {}


# ============================================================================
# Main Context Resolver
# ============================================================================


class TableCardContextResolver:
    """
    Core context resolver service for smart table card display.

    Resolves which fields to display on table cards based on:
    - Current table status (empty, dining, reserved, etc.)
    - Business context (meal period, business type, weekend flag)
    - Customer data (RFM level, loyalty info)
    - Order data (items, duration, amounts)
    - Rules engine (9 dynamic rules R1-R9)
    """

    def __init__(self, db_session: AsyncSession, learning_engine=None):
        """Initialize resolver with database session and optional learning engine."""
        self.db = db_session
        self.learning_engine = learning_engine
        self.rule_engine = BusinessRuleEngine()

    async def resolve(
        self,
        context: ResolveContext,
        table_data: Dict[str, Any],
        customer_data: Optional[Dict[str, Any]] = None,
        order_data: Optional[Dict[str, Any]] = None,
        next_reservation: Optional[Dict[str, Any]] = None,
    ) -> List[CardField]:
        """
        Resolve card fields for a table based on current context.

        Args:
            context: ResolveContext with tenant, store, meal period, etc.
            table_data: Current table state (status, seated_at, etc.)
            customer_data: Customer info (rfm_level, visit_count, etc.)
            order_data: Order info (pending items, amounts, etc.)
            next_reservation: Next reservation info if applicable

        Returns:
            List of CardField objects sorted by priority
        """
        status = TableStatus(table_data.get("status", TableStatus.EMPTY.value))
        field_pool = STATUS_FIELD_POOLS.get(status, [])

        # Compute base scores for all candidate fields
        scored_fields: Dict[str, int] = {field.key: field.base_priority for field in field_pool}

        # Get field rankings from learning engine if available
        if self.learning_engine:
            learned_rankings = await self.learning_engine.get_field_rankings(context.store_id, context.meal_period)
            for field_key, learned_score in learned_rankings.items():
                if field_key in scored_fields:
                    scored_fields[field_key] = int(learned_score * 0.3 + scored_fields[field_key] * 0.7)

        # Apply business rules (R1-R9)
        alert_overrides: Dict[str, AlertLevel] = {}
        fields_to_add: List[str] = []

        # Apply each rule
        rules_to_apply = [
            (self.rule_engine.rule_r1_vip_priority, (context, scored_fields, table_data, customer_data)),
            (self.rule_engine.rule_r2_overtime_alert, (context, scored_fields, table_data, order_data)),
            (self.rule_engine.rule_r3_pending_dishes, (context, scored_fields, table_data, order_data)),
            (self.rule_engine.rule_r4_reservation_countdown, (context, scored_fields, table_data, next_reservation)),
            (self.rule_engine.rule_r5_checkout_timeout, (context, scored_fields, table_data, order_data)),
            (self.rule_engine.rule_r6_emergency_cleanup, (context, scored_fields, table_data, next_reservation)),
            (self.rule_engine.rule_r7_lunch_turnover_focus, (context, scored_fields, table_data)),
            (self.rule_engine.rule_r8_dinner_per_capita_focus, (context, scored_fields, table_data, order_data)),
            (self.rule_engine.rule_r9_birthday_celebration, (context, scored_fields, customer_data)),
        ]

        for rule_func, rule_args in rules_to_apply:
            result = rule_func(*rule_args)
            if len(result) == 3:
                scored_fields, additions, overrides = result
                fields_to_add.extend(additions)
                alert_overrides.update(overrides)

        # Build resolved fields
        resolved = []
        for field_key, priority in scored_fields.items():
            field_def = next((f for f in field_pool if f.key == field_key), None)
            if not field_def and field_key in fields_to_add:
                continue  # Skip synthetic fields not in pool

            resolved.append(
                CardField(
                    key=field_key,
                    label=field_def.label if field_def else field_key,
                    value=None,  # Frontend will compute values
                    priority=priority,
                    alert=alert_overrides.get(field_key, AlertLevel.NORMAL),
                )
            )

        # Sort by priority descending, take top 6
        resolved.sort(key=lambda f: f.priority, reverse=True)
        return resolved[:6]

    async def compute_meal_period(self, store_id: str, current_time: datetime) -> MealPeriod:
        """Compute meal period based on store config and current time."""
        hour = current_time.hour

        if 6 <= hour < 11:
            return MealPeriod.BREAKFAST
        elif 11 <= hour < 15:
            return MealPeriod.LUNCH
        elif 15 <= hour < 22:
            return MealPeriod.DINNER
        else:
            return MealPeriod.LATE_NIGHT

    async def get_display_config(self, store_id: str, business_type: BusinessType) -> Dict[str, Any]:
        """Get display configuration for given business type."""
        configs = {
            BusinessType.PRO: {
                "max_fields": 6,
                "visible_categories": ["identity", "status", "financial", "service", "timing"],
                "refresh_interval": 2000,
                "features_enabled": ["vip_tracking", "order_monitoring", "overtime_alerts"],
            },
            BusinessType.STANDARD: {
                "max_fields": 5,
                "visible_categories": ["identity", "status", "financial", "service"],
                "refresh_interval": 3000,
                "features_enabled": ["vip_tracking", "order_monitoring"],
            },
            BusinessType.LITE: {
                "max_fields": 4,
                "visible_categories": ["status", "service"],
                "refresh_interval": 5000,
                "features_enabled": ["status_display"],
            },
        }
        return configs.get(business_type, configs[BusinessType.STANDARD])
