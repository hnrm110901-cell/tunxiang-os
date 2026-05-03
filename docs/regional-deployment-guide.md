# Regional Deployment Guide

Phase 3 Sprint 3.6 — Multi-country restaurant OS. This document describes
the deployment architecture, region-specific configuration, and operational
considerations for operating TunxiangOS across multiple Southeast Asian and
Chinese markets.

---

## Supported Markets

| Code | Market      | Primary DC           | Data Residency    | Status     |
|------|-------------|----------------------|-------------------|------------|
| CN   | China       | Tencent Cloud Shanghai | Shanghai, CN     | **Live**   |
| MY   | Malaysia    | Malaysia DC (KL)     | Kuala Lumpur, MY  | **Live**   |
| ID   | Indonesia   | Indonesia DC (Jakarta)| Jakarta, ID       | Planned    |
| VN   | Vietnam     | Vietnam DC (HCMC)    | Ho Chi Minh, VN   | Planned    |
| SG   | Singapore   | Singapore DC         | Singapore         | Future     |
| TH   | Thailand    | Thailand DC (BKK)    | Bangkok, TH       | Future     |

---

## Deployment Architecture

### Multi-Region Topology

```
                    ┌──────────────────────┐
                    │   Global Load Balancer│
                    │   (Cloudflare / GTM)  │
                    └──────┬───────┬───────┘
                           │       │
              ┌────────────┘       └────────────┐
              │                                  │
    ┌─────────┴──────────┐          ┌───────────┴──────────┐
    │   CN Region         │          │   MY Region           │
    │   Tencent Cloud     │          │   Malaysia DC         │
    │   Shanghai          │          │   Kuala Lumpur        │
    │                     │          │                       │
    │  ┌───────────────┐  │          │  ┌─────────────────┐  │
    │  │ API Gateway   │  │          │  │ API Gateway     │  │
    │  │ :8000         │  │          │  │ :8000           │  │
    │  └───────┬───────┘  │          │  └──────┬──────────┘  │
    │          │          │          │         │             │
    │  ┌───────┴───────┐  │          │  ┌──────┴──────────┐  │
    │  │ tx-trade      │  │          │  │ tx-malaysia     │  │
    │  │ tx-finance    │  │          │  │ (SST/e-Invoice) │  │
    │  │ tx-member     │  │          │  │                 │  │
    │  │ ... (14 svc)  │  │          │  │ tx-trade (MY)   │  │
    │  └───────┬───────┘  │          │  │                 │  │
    │          │          │          │  └──────┬──────────┘  │
    │  ┌───────┴───────┐  │          │         │             │
    │  │ PostgreSQL    │  │          │  ┌──────┴──────────┐  │
    │  │ (Shanghai)    │  │          │  │ PostgreSQL (KL) │  │
    │  └───────────────┘  │          │  └─────────────────┘  │
    └─────────────────────┘          └───────────────────────┘
```

### Data Flow

1. **CN stores** route through Tencent Cloud Shanghai (primary DC).
2. **MY stores** route through Malaysia DC (KL) for data residency compliance.
3. **Cross-border reporting** aggregates data from both DCs via the
   `CrossBorderReportService`, using fixed reference exchange rates.
4. **Sync engine** (edge/sync-engine) handles local-to-cloud sync for Mac mini
   stations, with configurable sync interval per region.

### Regional Services

The following services are region-scoped (deployed per region):

| Service       | CN  | MY  | ID  | VN  | Purpose                         |
|---------------|-----|-----|-----|-----|---------------------------------|
| tx-trade      | Yes | Yes | TBD | TBD | Core transaction processing     |
| tx-finance    | Yes | Yes | TBD | TBD | Tax & financial reconciliation  |
| tx-member     | Yes | TBD | TBD | TBD | Member CDP                      |
| tx-analytics  | Yes | Yes | TBD | TBD | Reporting & analytics           |
| tx-malaysia   | No  | Yes | No  | No  | MY-specific (SST, e-Invoice)    |

Global services (single deployment):

| Service       | Purpose                                       |
|---------------|-----------------------------------------------|
| tx-org        | Organisation, roles, cross-region HR          |
| tx-agent      | Agent OS — Master + Skill Agents              |
| tx-brain      | AI decision engine (Claude API)               |
| gateway       | API Gateway (domain routing + tenant mgmt)    |

---

## Region-Specific Config

| Configuration       | CN                  | MY                       | ID                     | VN                     |
|---------------------|---------------------|--------------------------|------------------------|------------------------|
| Tax regime          | VAT 13%/9%/6%       | SST 8%/6%/0%             | PPN 11%                | VAT 10%/8%             |
| Invoice system      | Nuonuo              | MyInvois (LHDN)          | e-Faktur (DJP)         | e-Invoice (GDT)        |
| Currency            | CNY (¥)             | MYR (RM)                 | IDR (Rp)               | VND (₫)               |
| Timezone            | Asia/Shanghai (+8)  | Asia/KL (+8)             | Asia/Jakarta (+7)      | Asia/HCMC (+7)         |
| Payment methods     | WeChat, Alipay      | TnG, GrabPay, Boost      | GoPay, DANA            | MoMo, ZaloPay          |
| Delivery platforms  | Meituan, Eleme, DY  | GrabFood, Foodpanda, SF  | GoFood, ShopeeFood     | GrabFood, ShopeeFood   |
| Date format         | YYYY-MM-DD          | DD/MM/YYYY               | DD/MM/YYYY             | DD/MM/YYYY             |
| Phone prefix        | +86                 | +60                      | +62                    | +84                    |
| Languages           | zh, en              | ms, zh, en, ta           | id, en                 | vi, en                 |
| Data residency      | Shanghai, CN        | Kuala Lumpur, MY         | Jakarta, ID            | HCMC, VN               |
| PDPA / equivalent   | Personal Info Law   | PDPA 2010                | PDP Law (UU 27/2022)   | Decree 13/2023        |

---

## Environment Variables (Per Region)

```bash
# Region identifier
REGION_CODE=MY
REGION_NAME=malaysia
REGION_TZ=Asia/Kuala_Lumpur

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@kl-db.internal:5432/tunxiang_my
DATABASE_POOL_SIZE=20
DATABASE_MAX_OVERFLOW=40

# Tax configuration (example: MY SST)
SST_STANDARD_RATE=0.08
SST_FNB_RATE=0.06

# Invoice system (example: MY MyInvois)
MYINVOIS_API_BASE=https://api.myinvois.hasil.gov.my
MYINVOIS_CLIENT_ID=...
MYINVOIS_CLIENT_SECRET=...

# SSM verification
SSM_API_BASE=https://api.ssm.com.my

# Exchange rate reference
EXCHANGE_RATE_UPDATE_QUARTERLY=true

# Feature flags
MARKET_MY_ENABLED=true
MARKET_ID_ENABLED=false
MARKET_VN_ENABLED=false
```

---

## Migration Path

### Adding a New Region

1. Add the market to `MarketRegion` enum in
   `shared/region/src/region_config.py`.
2. Add the full `RegionConfig` entry to `REGION_CONFIGS`.
3. Add exchange rates in `shared/region/src/cross_border_report.py`.
4. Create region-specific service (e.g. `tx-indonesia/`) if the market
   requires significant localisation.
5. Add feature flags in `shared/feature_flags/flag_names.py`.
6. Create region deployment config in `infra/docker/` and `infra/helm/`.
7. Add data sovereignty routing in
   `shared/security/src/data_sovereignty.py`.
8. Update this guide.

### ID Launch Checklist

- [ ] Tax engine: PPN 11% calculation confirmed by local accountant
- [ ] Invoice: e-Faktur integration with DJP
- [ ] Payments: GoPay + DANA merchant onboarding complete
- [ ] Delivery: GoFood + ShopeeFood webhook integration
- [ ] Language: id-ID locale support in frontend
- [ ] Data residency: Jakarta DC provisioned
- [ ] Compliance: UU PDP (Law 27/2022) review completed

### VN Launch Checklist

- [ ] Tax engine: VAT 10%/8% confirmed by local accountant
- [ ] Invoice: GDT e-Invoice integration
- [ ] Payments: MoMo + ZaloPay merchant onboarding complete
- [ ] Delivery: GrabFood + ShopeeFood webhook integration
- [ ] Language: vi-VN locale support in frontend
- [ ] Data residency: HCMC DC provisioned
- [ ] Compliance: Decree 13/2023 review completed

---

## Operational Considerations

### Data Residency

- MY customer data must not leave Malaysia without explicit consent
  (PDPA 2010). See `shared/security/src/data_sovereignty.py`.
- Cross-border reporting aggregates *aggregated* (non-PII) revenue data
  only. Individual customer profiles stay in their home region.
- The `CrossBorderReportService` operates on store-level aggregates,
  not individual-level data.

### Exchange Rates

- The system uses fixed reference rates (updated quarterly) for
  consolidated reporting — NOT real-time forex rates.
- Real-time settlement rates come from payment processor feeds
  (WeChat, Alipay, TnG, etc.) at transaction time.
- Quarterly update is manual: update `EXCHANGE_RATES` in
  `shared/region/src/cross_border_report.py` and note the change date.

### Monitoring

| Metric                          | Threshold         | Action                                |
|---------------------------------|-------------------|---------------------------------------|
| Cross-region sync latency       | > 5 min           | Alert on-call, check sync-engine      |
| Exchange rate staleness         | > 90 days         | Schedule quarterly rate update        |
| Invoice submission failure (MY) | > 1%              | Check LHDN MyInvois API status        |
| SSM verification failure        | > 5%              | Check SSM API / contact SSM support   |
| Regional API P99 latency        | > 500 ms          | Investigate DC network / PG query     |

### Backup & DR

| Region | Backup Schedule       | DR Target                  | RPO   | RTO   |
|--------|-----------------------|----------------------------|-------|-------|
| CN     | Daily (full) + WAL    | Tencent Cloud cross-AZ     | 1 min | 1 hr  |
| MY     | Daily (full) + WAL    | Malaysia secondary AZ      | 1 min | 1 hr  |
| ID     | Daily (full)          | Planned for Phase 4        | 24 hr | 4 hr  |
| VN     | Daily (full)          | Planned for Phase 4        | 24 hr | 4 hr  |
