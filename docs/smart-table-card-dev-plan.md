# TunxiangOS Smart Table Card - Development Plan

## Executive Summary

The Smart Table Card is a context-aware rule engine that automatically determines which information to display on restaurant table management cards. Instead of requiring managers to manually configure 30+ display options, the system learns from context (meal period, customer type, table status) and click patterns to show what matters most in real-time.

**Timeline**: MVP Sprint 1 (3 weeks) â Production Sprint 7 (week 25-28)
**Architecture**: FastAPI backend + SQLAlchemy v2 + PostgreSQL 16 with RLS + React 18 frontend
**Competitive Advantage**: Industry-first self-learning table management that evolves to staff behavior

---

## Feature Overview

### Core Value Proposition

| Problem | TunxiangOS Solution |
|---------|-------------------|
| Store managers configure display fields once, never update | System automatically shows most relevant fields per context |
| All managers see same 6 fields, regardless of meal period | Fields adapt to lunch vs. dinner business goals |
| No visibility into what managers actually care about | Learning engine tracks clicks and auto-optimizes priority |
| Manual status updates, no intelligent state management | 9 business rules trigger alerts and recommendations |

### Three Display Modes

1. **Card Mode** (Sprint 1): Grid of table cards with top 4-6 smart fields
2. **List Mode** (Sprint 1): Dense list view with full field visibility for fast scanning
3. **Map Mode** (Sprint 3-4): Graphical restaurant layout with mini-cards per table

### Three Business Types

1. **PRO** (å°å®«å¨): Full-featured with 15+ fields, all rules enabled
2. **STANDARD** (å°å¨ä¸èµ·): Core 8-10 fields, most rules enabled
3. **LITE** (æé»çº¿): Minimal 4-5 fields, basic rules only

---

## Architecture Design

### System Architecture Diagram

```
âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
â Frontend (React 18 + TypeScript)                            â
â  ââ Card View Component                                     â
â  ââ List View Component                                     â
â  ââ Map View Component (Canvas-based)                       â
â  ââ Click Event Tracker â POST /api/v1/tables/click-log     â
âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
                            â
âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
â FastAPI Router: /api/v1/tables                              â
â  ââ GET / â list_tables(filters)                            â
â  ââ GET /{table_id} â get_table_detail()                    â
â  ââ PUT /{table_id}/status â update_status()                â
â  ââ POST /click-log â record_click()                        â
â  ââ GET /field-rankings â get_field_rankings()              â
â  ââ GET /statistics â get_statistics()                      â
â  ââ GET /learning/stats â get_learning_stats()              â
âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
                            â
âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
â Business Logic Layer                                         â
â  ââ TableCardContextResolver                                â
â  â   ââ resolve() â applies 9 rules + presets               â
â  â   ââ BusinessRuleEngine (R1-R9)                          â
â  â   ââ compute_meal_period()                               â
â  â                                                            â
â  ââ TableCardLearningEngine                                 â
â  â   ââ record_click()                                       â
â  â   ââ get_field_rankings()                                â
â  â   ââ decay_scores() (exponential 0.8^days)               â
â  â   ââ compute_recommendations()                           â
â  â                                                            â
â  ââ TableCardService                                        â
â  â   ââ get_tables_with_context()                           â
â  â   ââ get_table_detail()                                  â
â  â   ââ update_table_status()                               â
â  â   ââ batch_update_table_status()                         â
â  â                                                            â
â  ââ Configuration Layer                                      â
â      ââ table_card_presets (PRO/STANDARD/LITE)              â
â      ââ table_card_field_defs (15+ fields)                  â
âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
                            â
âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
â Data Layer (SQLAlchemy v2 + PostgreSQL 16)                  â
â  ââ tables table (UUID, tenant_id, store_id, status, config)â
â  ââ orders table (linked to tables)                         â
â  ââ customers table (RFM, demographics)                     â
â  ââ reservations table                                      â
â  ââ table_card_click_logs (learning engine)                 â
â                                                              â
â Security: Row-Level Security (RLS) for tenant isolation     â
âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
```

### Data Flow: Card Resolution

```
User requests: GET /api/v1/tables?store_id=X&meal_period=dinner&business_type=standard

â Fetch baseline data (4 parallel queries, <150ms total)
  - SELECT * FROM tables WHERE store_id=X AND is_active=true
  - SELECT * FROM orders WHERE (conditions) for each table
  - SELECT * FROM customers WHERE id IN (order.customer_ids)
  - SELECT * FROM reservations WHERE store_id=X AND (conditions)

â For each table, resolve card fields
  For table A01 (status=dining, customer=VIP):
    1. Get candidate field pool based on status
       â [duration, amount, guest_count, waiter, dish_progress, member_name, ...]

    2. Compute base priority for each field
       â duration: 60, amount: 80, guest_count: 60, ...

    3. Get learned rankings from learning_engine
       â Get click history: duration clicked 25 times, amount clicked 18 times
       â Apply decay: 25 * 0.8^(days_since_first_click)
       â Blend with base: new_score = learned_score * 0.3 + base_score * 0.7

    4. Apply business rules (R1-R9)
       R1 (VIP priority): customer.rfm_level=="S1" â +50 to vip_badge, member_name
       R2 (Overtime): duration > 90min â duration alert=CRITICAL, +30 priority
       R3 (Pending dishes): pending_items > 20min â show dish_alert, +40 priority
       R5 (Checkout timeout): no rules trigger (not in pending_checkout state)
       R8 (Dinner per-capita): meal_period==dinner â amount +20 priority

    5. Apply business type preset (STANDARD)
       â Filter: only show fields in STANDARD_PRESET.visible_fields
       â Enforce max_fields: 5
       â Apply sort_priority override

    6. Sort by final priority, take top 5
       Final result for A01:
       [
         {key: "vip_badge", priority: 100, alert: "info"},
         {key: "amount", priority: 100, alert: "normal"},
         {key: "duration", priority: 90, alert: "critical"},
         {key: "guest_count", priority: 85, alert: "normal"},
         {key: "dish_progress", priority: 75, alert: "warning"},
       ]

â Return all tables with resolved fields

â Frontend renders card fields directly (no logic needed)
  - Field order: already sorted by priority
  - Styling: alert level determines color (normal=black, warning=yellow, critical=red+blink)
  - Layout: only show 5 fields (preset max_fields)
```

---

## Business Rules Specification (R1-R9)

### Rule Overview

| Rule | Name (CN) | Trigger Condition | Action | Business Impact |
|------|-----------|-------------------|--------|-----------------|
| R1 | VIPææ | customer.rfm_level â {S1, S2} | Insert vip_badge + member_name, +50 priority | VIP recognition â premium service |
| R2 | ç¨é¤è¶æ¶è­¦å | duration > 90min (normal) or >180min (VIP) | duration alert=CRITICAL, +30 priority | Turnover rate protection |
| R3 | å¬èé¢è­¦ | pending_items > 20min | Show dish_alert, +40 priority | Kitchen SLA protection |
| R4 | é¢è®¢å³å°å°è¾¾ | next_reservation within 2h, status=empty | Show reservation info, +35 priority | Prep time for new guests |
| R5 | å¾ç»è¶æ¶ | status=pending_checkout AND duration>10min | amount alert=CRITICAL, +45 priority | Turnover rate protection |
| R6 | ç´§æ¥æ¸å° | status=pending_cleanup AND next_res <30min | cleanup_duration alert=CRITICAL, +50 priority | Reservation protection |
| R7 | åå¸ç¿»å°ä¼å | meal_period=lunch AND 11:00-13:30 | turnover_count + duration +20 priority | Lunch speed focus |
| R8 | æå¸å®¢åä¼å | meal_period=dinner AND 17:00-21:00 | amount + per_capita +20 priority | Dinner revenue focus |
| R9 | çæ¥æé | customer.birth_date (month/day) = today | Insert birthday_badge, +60 priority | Surprise service opportunity |

### Detailed Rules

#### R1: VIPææ (VIP Priority)

**Condition**: `customer.rfm_level IN ('S1', 'S2')`

**Action**:
- Insert `vip_badge` field with value = "S1" or "S2"
- Insert `member_name` field with value = customer.name
- Boost priority of both fields: vip_badge +50, member_name +40
- Optionally show `visit_count` (accumulated visits)

**Example**: Restaurant patron is S1 VIP (top tier). System automatically shows:
```
vip_badge: "S1" (priority 95) â displayed first
member_name: "ææ»" (priority 90) â displays immediately so staff recognizes them
visit_count: "25æ¬¡" â context for personal greeting
```

**Business Logic**: VIP customers drive 40%+ of revenue in fine dining. Instant recognition is critical.

---

#### R2: ç¨é¤è¶æ¶è­¦å (Overtime Alert)

**Condition**: `table.status='dining' AND (now - seated_at) > threshold`
- Normal tables: threshold = 120 minutes
- VIP tables: threshold = 180 minutes

**Action**:
- Set `duration` field alert_level = CRITICAL (red + blink)
- Boost `duration` priority +30
- On frontend: card border blinks red, duration field shows red text

**Example**: Table A02 seated at 18:30, now 20:50 (2h 20min â exceeds 2h threshold)
```
duration: "140åé" (priority 90, alert: CRITICAL) â red + blink
```
Store manager immediately sees table is occupying seat longer than typical.

**Business Logic**: Turnover rate = revenue. Lunch target 45min, dinner 60min. Alert helps managers proactively suggest bill to slow eaters.

---

#### R3: å¬èé¢è­¦ (Pending Dishes Alert)

**Condition**: `EXISTS (order_items WHERE sent_to_kds=true AND (now - sent_to_kds_at) > 20min)`

**Action**:
- Insert `dish_alert` synthetic field
- Set alert_level = CRITICAL
- Boost priority +40
- Message: "å¬è" (Push kitchen)

**Example**: Order sent to kitchen at 19:00, now 19:25 (25 min pending)
```
dish_alert: "å¬è" (priority 90, alert: CRITICAL) â flashing red
```

**Business Logic**: Kitchen SLA = 20min from order to pass. Breaking SLA = customer frustration. Alert triggers waiter to rush kitchen.

---

#### R4: é¢è®¢å³å°å°è¾¾ (Reservation Countdown)

**Condition**: `table.status='empty' AND EXISTS (reservation WHERE reservation_time â¤ now + 120min)`

**Action**:
- Insert `upcoming_reservation`, `reservation_time`, `reservation_name` fields
- Boost priority +35
- Set alert_level = INFO (blue)

**Example**: Empty table B01 has reservation at 19:45, now 19:20 (25 min until)
```
upcoming_reservation: "çå¥³å£« 25åé" (priority 85, alert: INFO)
reservation_time: "19:45"
reservation_name: "çå¥³å£«"
```

**Business Logic**: Manager needs 20min notice to prep table (clean, reset, special setup). Alert triggers proactive prep.

---

#### R5: å¾ç»è¶æ¶ (Checkout Timeout)

**Condition**: `table.status='pending_checkout' AND (now - checkout_at) > 10min`

**Action**:
- Set `amount` field alert_level = CRITICAL
- Boost priority +45
- Message overlay: "å°½å¿«ç»è´¦" (Expedite checkout)

**Example**: Table C03 entered pending_checkout at 20:30, now 20:42 (12 min)
```
amount: "Â¥2,450" (priority 95, alert: CRITICAL) â large red text + blink
```

**Business Logic**: Pending checkout > 10min = POS issue or customer indecision. Alert prompts manager to intervene.

---

#### R6: ç´§æ¥æ¸å° (Emergency Cleanup)

**Condition**: `table.status='pending_cleanup' AND (next_reservation_time - now) < 30min`

**Action**:
- Set `cleanup_duration` alert = CRITICAL
- Insert `next_reservation` field
- Boost priority +50
- Message: "ç´§æ¥æ¸å°" (URGENT: Clean now)

**Example**: Table D02 finished dining at 20:15, reservation due at 20:40 (25 min to clean)
```
cleanup_duration: "25åé" (priority 100, alert: CRITICAL)
next_reservation: "èµµåç 25åé" (priority 90)
```

**Business Logic**: Missed turnover = lost reservation = revenue loss. Critical deadline.

---

#### R7: åå¸ç¿»å°ä¼å (Lunch Turnover Priority)

**Condition**: `meal_period='lunch' AND hour IN [11,12,13]`

**Action**:
- Boost `turnover_count` priority +20
- Boost `duration` priority +20
- Prioritize table areas with high turnover (normally low priority)

**Example**: Lunch rush (12:00-13:00). Three tables to manage:
- Table A01: empty (turnover_count: 5, priority +20 â shows first)
- Table A02: dining 35 min (duration: low baseline, priority +20 â now visible)
- Table A03: pending_cleanup 8 min (cleanup_duration: priority +20 â urgent)

**Business Logic**: Lunch margin = volume Ã speed. 45-min target. Every 10min gained = +1-2 covers. Prioritize metrics that support speed.

---

#### R8: æå¸å®¢åä¼å (Dinner Per-Capita Priority)

**Condition**: `meal_period='dinner' AND hour IN [17,18,19,20]`

**Action**:
- Boost `amount` priority +20
- Boost `per_capita` (amount/guest_count) priority +20
- Highlight high-value tables

**Example**: Dinner service (18:00-20:00). Two tables:
- Table B01: dining 45 min, Â¥680/3 people (per_capita: Â¥227, priority +20 â shows first)
- Table B02: dining 60 min, Â¥450/2 people (per_capita: Â¥225, priority +20)

**Business Logic**: Dinner margin = price Ã quality. Manager wants to optimize table mix: upsell high-value customers, ensure service quality for VIP tables.

---

#### R9: çæ¥æé (Birthday Celebration)

**Condition**: `customer.birth_date (month AND day) = today`

**Action**:
- Insert `birthday_badge` field (emoji: ð)
- Set priority = 100 (maximum)
- Set alert = CRITICAL (eye-catching)
- Message: "ðä»æ¥çæ¥"

**Example**: Table E01 customer is Li Wei, birthday is today (2026-03-28)
```
birthday_badge: "ðä»æ¥çæ¥" (priority 100, alert: CRITICAL) â front & center
```

**Business Logic**: Birthday = emotional touch point. Service staff sees badge â greet with complimentary dessert + song = memorable experience = lifetime loyalty. Simple but high-impact feature.

---

## Self-Learning Algorithm

### Overview

The learning engine tracks which fields store staff click on most frequently, then uses exponential decay to weight recent behavior more heavily than old behavior. This allows the system to adapt to seasonal changes and staff preferences.

### Click Tracking

**Trigger**: User clicks on a card field to see details
```
POST /api/v1/tables/click-log
{
  "field_key": "amount",
  "table_no": "A01",
  "meal_period": "dinner"
}
```

**What's Recorded**:
- `field_key`: which field (e.g., "amount", "duration", "member_name")
- `store_id`: which store
- `table_no`: which table (context)
- `meal_period`: lunch/dinner/breakfast/late_night
- `clicked_at`: timestamp
- `metadata`: optional (user_id, click_source, etc.)

**Storage**: Appended to `table_card_click_logs` table

### Decay Algorithm

**Formula**: `score = count * 0.8^(days_elapsed)`

**Interpretation**:
- Day 0 (today): 5 clicks = score 5.0
- Day 1 (yesterday): 5 clicks = score 4.0 (20% decay)
- Day 7 (a week ago): 5 clicks = score 0.66 (87% decay)
- Day 30 (a month ago): 5 clicks = score 0.006 (essentially 0)

**Rationale**: Fresh data matters more. If staff suddenly stops clicking "amount" in lunch, old lunch "amount" clicks shouldn't override their new preference.

### Ranking Computation

**Per meal_period + store**:
1. Count total clicks for each field (in last 30 days)
2. For each field with â¥3 clicks:
   - Get timestamp of first click
   - Calculate days_elapsed = (now - first_click).days
   - Compute decayed_score = count * 0.8^days_elapsed
   - Normalize to 0-100 range
3. Sort by decayed_score descending

**Example**: Dinner at Store A

| Field | Clicks | First Click | Days Ago | Decay Factor | Decayed Score |
|-------|--------|-------------|----------|--------------|---------------|
| amount | 25 | 2026-03-15 | 13 | 0.1074 | 2.69 â 27 (normalized) |
| duration | 18 | 2026-03-10 | 18 | 0.0281 | 0.51 â 5 (normalized) |
| member_name | 12 | 2026-03-21 | 7 | 0.3355 | 4.03 â 40 (normalized) |
| vip_badge | 8 | 2026-03-22 | 6 | 0.4268 | 3.41 â 34 (normalized) |

**Rankings**: member_name (40) > vip_badge (34) > amount (27) > duration (5)

### Integration with Rule Engine

**Flow**:
```
For each table, when resolving fields:

1. Get base priorities from field definitions
   â amount: 80, member_name: 65, vip_badge: 70, duration: 60

2. Get learned rankings from learning_engine.get_field_rankings()
   â member_name: 40, vip_badge: 34, amount: 27, duration: 5

3. Blend: new_priority = (learned_score * 0.3) + (base_priority * 0.7)
   â amount: (27 * 0.3) + (80 * 0.7) = 64
   â member_name: (40 * 0.3) + (65 * 0.7) = 57
   â vip_badge: (34 * 0.3) + (70 * 0.7) = 62
   â duration: (5 * 0.3) + (60 * 0.7) = 43

4. Apply business rules (R1-R9)
   â VIP detected: +50 to vip_badge, +40 to member_name
   â amount: 64 + 0 = 64
   â vip_badge: 62 + 50 = 112 â capped to 100
   â member_name: 57 + 40 = 97
   â duration: 43

5. Final sort: vip_badge (100) > member_name (97) > amount (64) > duration (43)
```

### Decay Background Job

**Frequency**: Daily (scheduled task)
**Action**: Mark or remove clicks older than 30 days
**Rationale**: Reduces memory footprint, keeps computation fast

```python
async def decay_scores(store_id, older_than_days=30):
    cutoff_date = datetime.utcnow() - timedelta(days=older_than_days)
    # Archive or delete old clicks
    await db.execute(
        "DELETE FROM table_card_click_logs "
        "WHERE store_id=? AND clicked_at < ?"
        older_than_days=cutoff_date
    )
```

---

## API Design

### Authentication & Tenant Isolation

All endpoints require:
```
Header: Authorization: Bearer {jwt_token}
Query: tenant_id={uuid}
```

Tenant isolation enforced at:
1. JWT validation (decoded token includes tenant_id)
2. Query parameter validation
3. PostgreSQL RLS policy (fallback)

### Endpoints

#### 1. List Tables with Smart Cards

```
GET /api/v1/tables?store_id=store_001&area=å¤§å&status=dining&business_type=standard&view_mode=card&limit=100
```

**Query Parameters**:
- `store_id` (required): UUID
- `area` (optional): Filter by area
- `status` (optional): Filter by status (empty|dining|reserved|pending_checkout|pending_cleanup)
- `business_type` (optional, default=standard): pro|standard|lite
- `view_mode` (optional, default=card): card|list|map
- `meal_period` (optional): Override computed meal period
- `limit` (optional, default=100, max=500)
- `offset` (optional, default=0)

**Response**:
```json
{
  "summary": {
    "empty": 8,
    "dining": 12,
    "reserved": 3,
    "pending_checkout": 2,
    "pending_cleanup": 1
  },
  "meal_period": "dinner",
  "tables": [
    {
      "table_id": "uuid",
      "table_no": "A01",
      "area": "å¤§å",
      "seats": 4,
      "status": "dining",
      "layout": {"pos_x": 45, "pos_y": 30, "width": 8, "height": 8},
      "card_fields": [
        {"key": "vip_badge", "label": "VIP", "value": "S1", "priority": 95, "alert": "info"},
        {"key": "amount", "label": "æ¶è´¹", "value": "Â¥680", "priority": 90, "alert": "normal"},
        ...
      ]
    },
    ...
  ],
  "total_count": 26
}
```

---

#### 2. Get Single Table Detail

```
GET /api/v1/tables/{table_id}?store_id=store_001
```

**Response**:
```json
{
  "table": { /* same as above */ },
  "order_summary": {
    "items_count": 5,
    "items_pending": 2,
    "amount": 680,
    "duration_minutes": 45
  },
  "customer_info": {
    "customer_id": "cust_001",
    "name": "ææ»",
    "rfm_level": "S1",
    "visit_count": 25
  },
  "reservation_info": null
}
```

---

#### 3. Update Table Status

```
PUT /api/v1/tables/{table_id}/status
Content-Type: application/json

{
  "new_status": "pending_checkout"
}
```

**Status Transitions**:
```
empty â dining (guest seated)
dining â pending_checkout (request bill)
pending_checkout â empty (payment complete)
dining â pending_cleanup (fast service, skip checkout)
pending_cleanup â empty (table cleaned)
empty â reserved (add reservation)
reserved â dining (guest arrives)
```

---

#### 4. Record Field Click

```
POST /api/v1/tables/click-log
Content-Type: application/json

{
  "field_key": "amount",
  "table_no": "A01",
  "meal_period": "dinner",
  "metadata": {"source": "card_view"}
}
```

**Purpose**: Learning engine uses clicks to rank field importance

---

#### 5. Get Field Rankings

```
GET /api/v1/tables/field-rankings?store_id=store_001&meal_period=dinner&limit=10
```

**Response**:
```json
{
  "rankings": [
    {"field_key": "amount", "score": 85, "click_count": 25, "last_clicked_at": "2026-03-28T20:15:00Z"},
    {"field_key": "member_name", "score": 78, "click_count": 18, "last_clicked_at": "2026-03-28T19:50:00Z"},
    ...
  ]
}
```

---

#### 6. Get Statistics

```
GET /api/v1/tables/statistics?store_id=store_001
```

**Response**:
```json
{
  "empty_count": 8,
  "dining_count": 12,
  "reserved_count": 3,
  "pending_checkout_count": 2,
  "pending_cleanup_count": 1,
  "total_occupied": 18,
  "total_available": 8,
  "timestamp": "2026-03-28T20:45:00Z"
}
```

---

## Database Schema

### Tables Table

```sql
CREATE TABLE tables (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  store_id UUID NOT NULL,
  table_no VARCHAR(50) NOT NULL,
  area VARCHAR(100),
  seats INTEGER NOT NULL DEFAULT 4,
  status ENUM('empty', 'dining', 'reserved', 'pending_checkout', 'pending_cleanup'),
  guest_count INTEGER,
  seated_at TIMESTAMP WITH TIME ZONE,
  checkout_at TIMESTAMP WITH TIME ZONE,
  is_active BOOLEAN DEFAULT true,
  is_deleted BOOLEAN DEFAULT false,
  config JSONB DEFAULT '{}', -- layout + card overrides
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  UNIQUE(tenant_id, store_id, table_no),
  FOREIGN KEY (tenant_id) REFERENCES tenants(id),
  FOREIGN KEY (store_id) REFERENCES stores(id)
);

-- Indexes
CREATE INDEX idx_tables_tenant_store_status ON tables(tenant_id, store_id, status);
CREATE INDEX idx_tables_tenant_store_area ON tables(tenant_id, store_id, area);
CREATE INDEX idx_tables_seated_at ON tables(seated_at);
CREATE INDEX idx_tables_updated_at ON tables(updated_at);

-- Row Level Security
ALTER TABLE tables ENABLE ROW LEVEL SECURITY;
CREATE POLICY tables_tenant_isolation ON tables
  USING (tenant_id = current_setting('app.tenant_id')::uuid);
```

### Table Card Click Logs Table

```sql
CREATE TABLE table_card_click_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  store_id UUID NOT NULL,
  table_no VARCHAR(50) NOT NULL,
  field_key VARCHAR(100) NOT NULL,
  clicked_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  meal_period VARCHAR(50),
  user_id UUID,
  score FLOAT DEFAULT 1.0,
  metadata JSONB DEFAULT '{}',
  is_deleted BOOLEAN DEFAULT false,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  FOREIGN KEY (tenant_id) REFERENCES tenants(id),
  FOREIGN KEY (store_id) REFERENCES stores(id)
);

-- Indexes
CREATE INDEX idx_click_logs_tenant_store_field ON table_card_click_logs(tenant_id, store_id, field_key);
CREATE INDEX idx_click_logs_tenant_store_meal ON table_card_click_logs(tenant_id, store_id, meal_period);
CREATE INDEX idx_click_logs_clicked_at ON table_card_click_logs(clicked_at);

-- Row Level Security
ALTER TABLE table_card_click_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY click_logs_tenant_isolation ON table_card_click_logs
  USING (tenant_id = current_setting('app.tenant_id')::uuid);
```

### Table.config JSONB Structure

```json
{
  "layout": {
    "pos_x": 45.0,      // Percentage coordinate 0-100
    "pos_y": 30.0,
    "width": 8.0,       // Table width (e.g., 8% of canvas)
    "height": 8.0,      // Table height
    "rotation": 0,      // Degrees
    "shape": "rect"     // rect|circle|hexagon
  },
  "card_overrides": {
    "pin_fields": ["amount"],       // Force these to top
    "hide_fields": ["waiter"],      // Force these hidden
    "custom_label": {               // Override labels
      "amount": "æ¶è´¹éé¢"
    }
  }
}
```

---

## Frontend Components (React 18 + TypeScript)

### Component Hierarchy

```
<TableCardManager>
  ââ <ViewModeToggle> (Card|List|Map buttons)
  ââ <FilterBar> (area, status, business_type)
  ââ <CardView>
  â   ââ <LazyVerticalGrid>
  â       ââ <TableCard> (repeating)
  â           ââ <TableHeader> (A01, 4åº§, å¤§å)
  â           ââ <CardFieldRenderer> (repeating for each field)
  â           â   ââ <FieldBadge> (VIP S1)
  â           â   ââ <FieldCurrency> (Â¥680)
  â           â   ââ <FieldDuration> (45åé) + click tracking
  â           â   ââ <FieldProgress> (4/6ä¸è)
  â           â   ââ <FieldAlert> (blink animation for critical)
  â           ââ <TableStatusIndicator> (dining â blue border)
  â
  ââ <ListView>
  â   ââ <LazyColumn>
  â       ââ <TableRow> (repeating)
  â           ââ <TableNo>
  â           ââ <AllFields> (6 in a row)
  â           ââ <Expandable> (show order details on tap)
  â           ââ <StatusIndicator>
  â
  ââ <MapView>
      ââ <Canvas>
          ââ <DrawTable> (repeating, mini-cards inside)
              ââ pos_x, pos_y from table.layout
              ââ Top 3 fields
              ââ Click handling for zoom/detail
```

### TableCard Component (Pseudo-code)

```typescript
interface TableCardProps {
  table: ResolvedTableCard;
  onFieldClick: (fieldKey: string) => void;
}

export const TableCard: React.FC<TableCardProps> = ({ table, onFieldClick }) => {
  // Card fields are already sorted by priority from backend
  // Just render them in order

  return (
    <Card
      border={`3px solid ${getStatusColor(table.status)}`}
      className={table.card_fields.some(f => f.alert === 'critical') ? 'blink' : ''}
    >
      <TableHeader>
        <h3>{table.table_no}</h3>
        <span>{table.area} Â· {table.seats}åº§</span>
      </TableHeader>

      <FieldList>
        {table.card_fields.slice(0, 6).map(field => (
          <FieldRow
            key={field.key}
            field={field}
            onClick={() => {
              onFieldClick(field.key);
              // POST /api/v1/tables/click-log
            }}
            className={field.alert === 'critical' ? 'critical-text' : ''}
            style={{
              color: getAlertColor(field.alert),
              animation: field.alert === 'critical' ? 'blink 1s infinite' : 'none'
            }}
          >
            <FieldLabel>{field.label}</FieldLabel>
            <FieldValue>{field.value}</FieldValue>
          </FieldRow>
        ))}
      </FieldList>

      <TableFooter>
        <LastUpdated>{table.updated_at}</LastUpdated>
      </TableFooter>
    </Card>
  );
};
```

---

## Testing Strategy

### Unit Tests (Services)

- **ContextResolver**: Test each rule (R1-R9) individually and combinations
- **LearningEngine**: Test click recording, decay algorithm, ranking computation
- **TableService**: Test filtering, aggregation, status transitions
- **FieldDefinitions**: Test field validation, business type filtering

### Integration Tests (API)

- End-to-end flow: request â resolver â database â response
- Multi-rule scenarios: VIP + overtime + pending_dishes combined
- Business type presets: verify STANDARD hides pro-only fields
- Learning integration: clicks affect next request's field rankings

### E2E Tests (Full Stack)

- Frontend renders card fields in priority order
- Clicking field records click event
- Click count increases in learning stats
- Next refresh shows clicked field ranked higher

### Performance Tests

- List 100 tables: <500ms response time
- Resolve 100 tables in parallel: <1s (with connection pooling)
- Learning computation for 10k clicks: <100ms

---

## Deployment Plan

### Sprint 1 (Weeks 1-3): MVP

**Deliverables**:
- â Context resolver service with 9 rules
- â Card view + List view (React components)
- â API endpoints (list, detail, status update)
- â Database schema + migration
- â Unit + integration tests

**Deployment**: Feature branch â staging â QA sign-off â production (canary 10%)

**Configuration**: Deploy with STANDARD preset as default for all stores

---

### Sprint 7 (Weeks 25-28): Learning Engine

**Deliverables**:
- â Click tracking infrastructure
- â Decay algorithm + ranking computation
- â Learning stats API
- â Background job (daily decay)

**Rollout**: Gradual ramp (20% stores week 1, 50% week 2, 100% week 3)

---

### Phase 2 (2027): L2+ Evolution

- **L2 Predictive**: Predict table duration, add prob
abilities
- **L3 Recommendations**: "Consider table A05 next"
- **L4 Auto-Scheduling**: Agent suggests seating changes

Each phase is additive; L1 components stay unchanged.

---

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Field resolution latency | <100ms | Server logs |
| Card render speed | <300ms | Frontend RUM |
| Staff adoption | >70% | Usage analytics |
| Click-tracking accuracy | 100% | Audit logs |
| Learning ranking improvement | +15% match to behavior | A/B test |
| Customer satisfaction (NPS) | +5 points | Post-service survey |

---

## Known Limitations & Future Work

1. **No real-time updates**: Current design uses polling. Upgrade to WebSocket for live updates.
2. **No photo/video support**: Fields limited to text/numbers. Add image rendering for dishes, room photos.
3. **No mobile-first UX**: Desktop-first design. Mobile app needed for kitchen display.
4. **No audio alerts**: Critical alerts should have sound. Add optional audio.
5. **Hardcoded rules**: Rules are in Python. Move to rule engine (Drools) for no-code config.

---

## Conclusion

The Smart Table Card transforms restaurant management from manual configuration to intelligent adaptation. By combining context awareness, business rules, and self-learning, we create a system that evolves with staff behavior and business needs. This is the foundation for TunxiangOS's positioning as "the AI that understands your restaurant."
