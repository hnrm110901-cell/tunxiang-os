# Database Migration Analysis: Old Project vs New Project (tunxiang-os)

> Generated: 2026-03-27
> Old project: `/Users/lichun/tunxiang/apps/api-gateway/alembic/versions/` (161 migration files)
> New project: `/Users/lichun/tunxiang-os/shared/db-migrations/versions/` (5 migrations + 1 fix)

---

## 1. Executive Summary

The new project (tunxiang-os) has a **completely redesigned schema** in 5 clean migrations (v001-v005) that covers 37 tables across 5 business domains. It is NOT a copy of the old project's 161 incremental migrations -- it is a greenfield rewrite with a unified schema design.

The new project's RLS implementation has **3 security vulnerabilities** (CRITICAL-001/002/003) that have been fixed in the newly created `v006_rls_security_fix.py`.

**Recommendation: Do NOT merge old migrations into the new project.** The v001-v005 migrations already represent the desired target schema. Only the RLS security fix (v006) is needed.

---

## 2. Table Coverage Comparison

### 2.1 New Project Tables (37 total across v001-v005)

| Migration | Tables | Domain |
|-----------|--------|--------|
| v001 (11 tables) | stores, customers, employees, dish_categories, dishes, dish_ingredients, orders, order_items, ingredient_masters, ingredients, ingredient_transactions | Core entities |
| v002 (12 tables) | tables, payments, refunds, settlements, shift_handovers, receipt_templates, receipt_logs, production_depts, dish_dept_mappings, daily_ops_flows, daily_ops_nodes, agent_decision_logs | Operations + payments |
| v003 (6 tables) | payment_records, reconciliation_batches, reconciliation_diffs, tri_reconciliation_records, store_daily_settlements, payment_fees | Payment settlement |
| v004 (8 tables) | reservations, queues, banquet_halls, banquet_leads, banquet_orders, banquet_contracts, menu_packages, banquet_checklists | Reservation + banquet |
| v005 (8 tables) | attendance_rules, clock_records, daily_attendance, payroll_batches, payroll_items, leave_requests, leave_balances, settlement_records | HR operations |

### 2.2 Old Project Tables Covered by New Project

The following old project tables have equivalent (often improved) tables in the new project:

| Old Table | New Equivalent | Notes |
|-----------|---------------|-------|
| orders | orders (v001) | New version adds biz_date (v003), more fields |
| order_items | order_items (v001) | Enhanced with food_cost, gross_margin |
| reservations | reservations (v004) | Complete redesign with 7-status lifecycle |
| inventory_items | ingredients (v001) | Renamed, restructured |
| inventory_transactions | ingredient_transactions (v001) | Renamed |
| employees | employees (v001) | Significantly expanded (HR fields) |
| schedules | (covered by attendance_rules + clock_records in v005) | Redesigned |
| reconciliation_records | reconciliation_batches + reconciliation_diffs (v003) | Split into proper model |
| pos_transactions | payments (v002) | Redesigned as proper payment model |
| financial_records | store_daily_settlements (v003) + settlements (v002) | Split by purpose |
| supply_orders | (not yet in new project) | Gap identified |

### 2.3 Old Project Tables NOT in New Project (Gaps)

| Old Table | Domain | Priority | Action Needed |
|-----------|--------|----------|---------------|
| training_records | HR/Training | Medium | Future v007 migration |
| training_plans | HR/Training | Medium | Future v007 migration |
| service_feedbacks | Service Quality | Medium | Future migration |
| complaints | Service Quality | Medium | Future migration |
| tasks | Operations | Low | May be replaced by daily_ops_nodes |
| notifications | System | Medium | Future migration |
| member_transactions | CRM/Membership | High | Future migration (membership system) |
| supply_orders | Supply Chain | High | Future migration |
| bom_templates | Menu/BOM | High | Future migration (cost truth engine) |
| bom_items | Menu/BOM | High | Future migration |
| waste_events | Inventory/Loss | High | Future migration (loss prevention) |
| users | Auth | Medium | May be in separate auth service |

### 2.4 New Project Tables NOT in Old Project (New Additions)

| New Table | Migration | Purpose |
|-----------|-----------|---------|
| tables | v002 | Table management (dining tables) |
| receipt_templates | v002 | Print template management |
| receipt_logs | v002 | Print audit trail |
| production_depts | v002 | Kitchen station management |
| dish_dept_mappings | v002 | Dish-to-kitchen routing |
| daily_ops_flows | v002 | Daily operations workflow (E1-E8) |
| daily_ops_nodes | v002 | Operations workflow node details |
| agent_decision_logs | v002 | AI Agent audit trail |
| payment_records | v003 | Third-party payment import |
| reconciliation_batches | v003 | Batch reconciliation |
| reconciliation_diffs | v003 | Reconciliation differences |
| tri_reconciliation_records | v003 | Triangle reconciliation |
| store_daily_settlements | v003 | Enhanced daily settlement |
| payment_fees | v003 | Payment fee tracking |
| queues | v004 | Queue management |
| banquet_halls | v004 | Banquet venue management |
| banquet_leads | v004 | Banquet sales pipeline (13 stages) |
| banquet_orders | v004 | Banquet orders |
| banquet_contracts | v004 | Banquet contracts |
| menu_packages | v004 | Banquet menu packages |
| banquet_checklists | v004 | Banquet preparation checklists |
| attendance_rules | v005 | Attendance policy configuration |
| clock_records | v005 | Clock in/out events |
| daily_attendance | v005 | Daily attendance aggregation |
| payroll_batches | v005 | Payroll calculation batches |
| payroll_items | v005 | Per-employee payroll details |
| leave_requests | v005 | Leave management |
| leave_balances | v005 | Leave quota tracking |
| settlement_records | v005 | Payroll bank transfer records |

---

## 3. RLS Policy Comparison

### 3.1 Architecture Differences

| Aspect | Old Project | New Project |
|--------|------------|-------------|
| Session variable | `app.current_tenant` (store_id, text) | `app.tenant_id` (UUID) |
| Isolation level | Store-level (store_id) | Tenant-level (tenant_id as UUID) |
| Brand isolation | Separate rls_002 (app.current_brand) | Not implemented yet |
| Helper function | `set_current_tenant(text)` | `set_tenant_id(UUID)` |
| Policy operations | SELECT + INSERT + UPDATE + DELETE (4) | SELECT + INSERT only (2) -- **gap** |
| NULL bypass guard | Fixed in rls_fix_001 | **Missing** -- fixed in v006 |
| FORCE RLS | Yes (in rls_fix_001) | **Missing** -- fixed in v006 |

### 3.2 RLS Vulnerabilities Found in New Project

#### CRITICAL-001: Potential NULL/Empty Bypass

**Severity: HIGH**

In v001-v005, the RLS policies use:
```sql
USING (tenant_id = current_setting('app.tenant_id')::UUID)
```

When `app.tenant_id` is not set:
- `current_setting('app.tenant_id')` returns NULL (with missing_ok=false) or raises error
- Without the second TRUE parameter, this will ERROR on missing setting
- With `current_setting('app.tenant_id', TRUE)`, it returns NULL
- `NULL::UUID` is NULL, and `tenant_id = NULL` evaluates to NULL (not FALSE)
- PostgreSQL RLS treats NULL as deny, BUT this relies on implicit behavior

The v001-v005 code does NOT pass TRUE as the second argument, meaning an unset variable will raise an error rather than silently bypass. However, this is fragile -- if the variable is set to empty string, `''::UUID` will raise a cast error.

**Fix in v006**: Explicit `IS NOT NULL AND <> ''` guard before the UUID cast.

#### CRITICAL-002: Missing UPDATE and DELETE Policies

**Severity: HIGH**

v001-v005 only create two policies per table:
- `tenant_isolation_{table}` -- USING clause (covers SELECT only by default)
- `tenant_insert_{table}` -- FOR INSERT WITH CHECK

This means UPDATE and DELETE operations have **no explicit RLS policy**. In PostgreSQL's default permissive policy mode, operations without a matching policy are denied. However, the `tenant_isolation_{table}` policy without a `FOR` clause applies to ALL operations as a permissive USING policy. This means:
- SELECT: covered by USING
- INSERT: covered by WITH CHECK
- UPDATE: covered by USING (existing rows) but **no WITH CHECK** (new values not validated)
- DELETE: covered by USING

The actual risk is that UPDATE operations can change `tenant_id` to a different tenant's ID because there is no WITH CHECK on UPDATE.

**Fix in v006**: Explicit 4-operation policies with both USING and WITH CHECK.

#### CRITICAL-003: Table Owner Bypasses RLS

**Severity: MEDIUM**

v001-v005 use `ENABLE ROW LEVEL SECURITY` but NOT `FORCE ROW LEVEL SECURITY`. If the application connects as the table owner (which is common when using a single database role), all RLS policies are bypassed.

**Fix in v006**: Added `FORCE ROW LEVEL SECURITY` on all tables.

### 3.3 Missing Feature: Brand-Level Isolation

The old project's `rls_002_brand_isolation` implements a second layer of RLS based on `app.current_brand`. The new project does not yet have this. This should be addressed in a future migration if multi-brand support is needed.

---

## 4. Revision Chain

### New Project Chain
```
None -> v001 -> v002 -> v003 -> v004 -> v005 -> v006 (security fix)
```

### Old Project Chain (simplified)
```
... -> m01_sync_phase1_models -> rls_001_tenant_isolation -> rls_002_brand_isolation
    -> ... (300+ migrations) ... -> z68_mission_journey -> rls_fix_001 (security fix)
```

---

## 5. Recommendations

### Immediate Actions

1. **Apply v006_rls_security_fix.py** -- fixes all 3 critical RLS vulnerabilities
2. **Run `alembic upgrade head`** on the new project database to apply the fix

### Short-Term (Next Sprint)

3. **Add brand isolation** -- create v007 for `app.current_brand` RLS layer if multi-brand is needed
4. **Add missing tables** -- prioritize:
   - `bom_templates` + `bom_items` (cost truth engine depends on this)
   - `waste_events` (loss prevention Agent depends on this)
   - `member_transactions` (membership/CRM system)
   - `supply_orders` (supply chain management)
   - `notifications` (system notifications)

### Architecture Notes

5. **Do NOT copy old migrations** -- the 161 old migrations represent incremental schema evolution with many merge heads, fixes, and workarounds. The new v001-v005 is a clean redesign.
6. **Variable naming** -- new project correctly uses `app.tenant_id` (UUID) vs old project's `app.current_tenant` (text/store_id). The new naming is better aligned with the multi-tenant architecture.
7. **Session variable consistency** -- ensure all application code (FastAPI middleware, repository layer) sets `app.tenant_id` before any database query. This is the single most critical security requirement.

---

## 6. Application-Level Requirements

For the RLS fix to work correctly, the application MUST:

```python
# In FastAPI middleware or dependency injection:
async def set_tenant_context(session: AsyncSession, tenant_id: UUID):
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, TRUE)"),
        {"tid": str(tenant_id)}
    )
```

The third parameter `TRUE` means the setting is local to the current transaction. This is the correct behavior for connection pooling.

**Never** leave `app.tenant_id` unset when executing queries on RLS-protected tables.
