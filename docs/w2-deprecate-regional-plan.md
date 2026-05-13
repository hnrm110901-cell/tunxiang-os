# W2-A 调研：删除 indonesia/malaysia/vietnam 国际化

> **本文档是 W2 起手 quick recon 结果**，由 W1-T1 (PR #489 `06f4a19f`) merge 后 session 产出。
> deep-dive + 实施 PR 在 fresh session 继续 — 见末尾 starter prompt。

---

## 背景与决策

### 创始人决策（12 周升级战略 W2）

PR #129 (`1f9e592b`, 2026-05-03) 引入了马来西亚/印尼/越南国际化框架：
- 3 个独立微服务：`tx-malaysia` / `tx-indonesia` / `tx-vietnam`
- 6 个 alembic migrations：v384 (country_code) / v385 (SST) / v386 (subsidy) / v387 (PDPA) / v388 (PPN/ID market) / v389 (VAT/VN market)
- 4 语种 i18n：ms_MY / ta_IN / id_ID / vi_VN
- 跨境框架：`shared/region/` + `shared/security/data_sovereignty.py`
- 7 国际支付/外卖 adapter：TnG / GrabPay / Boost / GoPay / DANA / MoMo / ZaloPay / FoodPanda / ShopeeFood

### 为什么删（第一性原理）

CLAUDE.md §一 首批客户：尝在一起 / 最黔线 / 尚宫厨；标杆：徐记海鲜 — **全部在国内**。

三国国际化在当前阶段是 dead weight：
- **认知噪音** — 跨服务 `if MarketRegion.MY` 分支增加 Tier 1 资金路径迭代心智成本
- **维护成本** — 100+ 文件需跟随核心域演化（v413 migration 已远超 v389）
- **攻击面** — PDPA / SST / 电子发票 合规复杂度（CSO audit 已多次将三国规则列为 P2+）
- **W8 DEMO 门槛迫近** — 徐记海鲜 23 套系统替换需 Tier 1 全绿，三国代码与此目标无关

---

## Quick Recon 数据

| 指标 | 数据 |
|---|---|
| 总引用文件数（含 indonesia/malaysia/vietnam/印尼/马来西亚/越南） | **63** |
| 三独立服务 py 文件 | **37** (tx-malaysia 23 + tx-indonesia 6 + tx-vietnam 8) |
| Migration 文件 | **6** (v384–v389)，downgrade 完整可逆（逐表 add_column 模式） |
| Migration 影响 schema | 17 张表新增 `country_code` (default `'CN'`) + 4 张新表 (subsidy/PDPA) + dishes 3 个 region category column |
| shared/region/ 整目录 | PR #129 引入，可整删 |
| shared/security/data_sovereignty.py | PR #129 引入，可整删 |
| shared/feature_flags/ MalaysiaFlags | 15 个 flag，可删 enum |
| i18n 4 语种 | ms_MY / ta_IN / id_ID / vi_VN |

### 关键发现：§18 ontology 冻结约束 **不触发**

- `shared/ontology/src/base.py:11 TenantBase` **不含 country_code**（PR #129 commit message 说"TenantBase 新增 country_code"，但实际实现是 v384 migration 逐表 add_column，**未改 base.py**）
- `shared/ontology/src/entities.py:162 Store.region` 是**国内行政区域** (`String(50)`, 华东/华南/华北 等)，与 PR #129 引入的国家级 region (`MarketRegion.MY/ID/VN/CN`) **语义无关，不需删**

→ ontology 冻结约束自动满足，**无需创始人确认 ontology 改动**。

### 关键发现：country_code 后续无新引用

```
shared/db-migrations/versions/v384_country_code.py     # 引入
shared/db-migrations/versions/v386_subsidy_programs.py # PR #129 内
shared/db-migrations/versions/v388_id_market.py        # PR #129 内
shared/db-migrations/versions/v389_vn_market.py        # PR #129 内
```

v390 → v413 (24 个后续 migration) **不引用 country_code**，反向 drop 不破坏 chain。

---

## 删除清单（分 Phase）

### Phase 0 — 文档 / i18n / 配置（低风险）

- `docs/` 含三国引用的文档（保留 `docs/security/INDEX.md` 历史审计引用 — audit 记录不删）
- `apps/` 中的 i18n 资源：ms_MY / ta_IN / id_ID / vi_VN 语言包
- `shared/feature_flags/flag_names.py` 删 `MalaysiaFlags` enum (15 flag)

### Phase 1 — 三独立服务整删（低风险，无 cross-service 依赖）

- `services/tx-malaysia/` (23 py + alembic.ini + db-migrations/)
- `services/tx-indonesia/` (6 py)
- `services/tx-vietnam/` (8 py + tests/)

→ 三服务都是独立 FastAPI app，与 gateway 通过 HTTP/event-bus 通信。删除前需确认 `infra/compose/base.yml` / `infra/helm/` 中是否有 chart 引用。

### Phase 2 — shared 区域框架（低-中风险，已 deep-recon 5/13）

> **5/13 recon 修正 3 处 stale**（plan 原文 vs 实际仓库）：
> - 真实路径 `shared/security/src/data_sovereignty.py`（多一层 `src/`）
> - `MalaysiaFlags` 不存在；实际只有 `VietnamFlags` + `IndonesiaFlags` (`shared/feature_flags/flag_names.py:223 + 248`)
> - `delivery_publish/publishers.py` + `delivery_canonical/transformers.py` 内**无**国际分支；国际外卖/支付实际在 `shared/adapters/` 下 8 个独立 brand 目录

**Phase 2 完整删除清单（外部 consumer 0 验证 5/13）**：

| # | 路径 | 文件数 | 外部 consumer |
|---|------|------|-----------|
| 1 | `shared/region/` 整目录 | 3 (`__init__` + 2 src) | 0（只剩 Phase 1 已删的 tx-malaysia） |
| 2 | `shared/security/src/data_sovereignty.py` | 1 | 0（只剩 Phase 1 已删的 tx-malaysia） |
| 3 | `shared/vector_store/src/malaysia_embeddings.py` | 1 | 0 |
| 4 | `shared/feature_flags/flag_names.py` 删 `VietnamFlags` + `IndonesiaFlags` class | edit | 0 |
| 5 | `shared/adapters/dana/` | 4 | 0（仅自引用 adapter.py→client.py） |
| 6 | `shared/adapters/foodpanda/` | 4 | 0 |
| 7 | `shared/adapters/gopay/` | 4 | 0 |
| 8 | `shared/adapters/momo/` | 4 | 0 |
| 9 | `shared/adapters/myinvois/` | 3 | 0（唯一 consumer tx-malaysia 已 Phase 1 删） |
| 10 | `shared/adapters/shopeefood/` | 4 | 0 |
| 11 | `shared/adapters/zalopay/` | 4 | 0 |

**总计 ~37 files 整删 + 1 file edit / 0 新增**。

**CI/infra/scripts 引用扫描 0 命中**：`.github/workflows/` / `infra/compose/` / `infra/helm/` / `scripts/` 均无对 Phase 2 11 项的引用（已 grep）。

**grabfood 撤回（PR #504 round-2 reviewer 发现）**：原 plan 把 `shared/adapters/grabfood/` 列入 #8 应删项，但 reviewer 发现 `GrabFoodDeliveryAdapter` 经 `shared/adapters/delivery_factory.py:15` import 进入 `_PLATFORM_REGISTRY` 与 meituan/eleme/douyin/wechat 并列为 6 大主流外卖平台之一；`delivery_canonical/transformers.GrabFoodTransformer` + `delivery_publish/publishers.GrabFoodPublisher` + `delivery_panel_router.py:298 @router.post("/webhooks/grabfood")` 均 active；v411/v412/v413 migration enum 含 `"grabfood"`。grabfood 是 OmniChannel 6 平台一等公民，**不属东南亚 i18n 跨境删除范围**。Phase 2 撤回 grabfood，另起 follow-up issue 评估"grabfood OmniChannel 是否真有马来业务流量，含 transformer/publisher/webhook router/migration enum 整体 deprecate or 保留"。

**保留**（不删，与 i18n 无关或 generic 通用组件）：
- `shared/security/data_masking.py`（PII 脱敏通用工具）
- `shared/security/tests/` 4 个测试（encryption/error_handler/prompt_sanitizer/validators）
- `shared/security/src/` 下其他通用 security 文件
- `shared/vector_store/{client,embeddings,indexes}.py`（tx-agent 知识检索在用）

### Phase 3 — tx-agent / tx-trade 内嵌分支（低-中风险，5/13 recon 修正）

> **5/13 recon 修正 plan 原文**：
> - `services/tx-trade/src/routers/delivery_panel_router.py` 内**无** FoodPanda/ShopeeFood 路由（plan 原文 stale）
> - `tx-finance/invoice_service.py` 内**无** MY/LHDN/MyInvois 分支（plan 原文 stale，已整目录 grep 0 hit）
> - gateway / tx-menu / tx-member / tx-ops / tx-supply / tx-brain / tx-analytics / tx-intel / tx-org / tx-civic / tx-growth / mcp-server **0 regional 引用**

**Phase 3 完整清单**：

| # | 路径 | 类型 | 验证 |
|---|---|---|---|
| 1 | `services/tx-agent/src/api/regional_forecast_routes.py` | 整删 | tx-agent/main.py 未注册（dead route） |
| 2 | `services/tx-agent/src/services/regional_forecasting_service.py` | 整删 | 仅被 #1 引用 |
| 3 | `services/tx-agent/src/services/malaysia_forecasting_service.py` | 整删 | 0 外部引用 |
| 4 | `services/tx-agent/src/config/malaysia_ingredients.py` | 整删 | 0 外部引用 |
| 5 | `services/tx-agent/src/config/malaysia_holidays.py` | 整删 | 0 外部引用 |
| 6 | `services/tx-trade/src/services/my_payment_notify_service.py` | 整删 | 0 外部引用 |
| 7 | `services/tx-trade/src/services/delivery_adapters/foodpanda_adapter.py` | 整删 | 0 外部引用 |
| 8 | `services/tx-trade/src/services/delivery_adapters/shopeefood_adapter.py` | 整删 | 0 外部引用（仅自身 class 定义） |
| 9 | `services/tx-trade/src/services/payment_gateway.py` | **surgical** | 删 line 53-56 (Malaysia comment + tng_ewallet/grabpay/boost in `PAYMENT_METHODS` dict) + line 672-675 (Malaysia comment + 3 项 in 标签 mapping) — **保留**国内 alipay/wechat/unionpay/member_balance/credit_account |

**Phase 3 PR diff 估算**：8 files 整删 + 1 file surgical edit / 0 新增 / 约 500-1000 行删

### Phase 4 — Alembic 反向 migration（高风险，需 user 决策点）

**user 决策点 D1：三国 production 是否有真实 tenant 数据？**

- 若**无**：写 v414+ migration 反向 drop column / drop table（country_code / sst_category / subsidy_programs / tenant_subsidies / subsidy_bills / pdpa_requests / pdpa_consent_logs / ppn_category / vat_category）
- 若**有**：保留 column 但停用代码（Phase 1-3 仍执行，但 country_code 等保留）；后续 N 月按 production 数据自然衰减再清理

按 user prompt（首批客户都在国内）+ commit history（三国服务上线时间 5/3，离当前 10 天，customer adoption 极有限），**默认走"无 production 数据"分支**，等 user 确认后写 v414+ 反向 migration。

### Phase 5 — Gateway 瘦身（5/13 recon: 范围实际为空）

> **5/13 recon 结论**：gateway / 其他 11 个服务 0 regional 引用 — Phase 5 W2-A 联动范围实际**为空**（gateway 从未注册三国 service upstream proxy）。
>
> W2-B "Gateway 瘦身" 真实范围（非 W2-A 衍生）需 fresh session deep-dive。本 plan Phase 5 标记 **closed (out of W2-A scope)**。

---

## 影响面初评

| 维度 | 影响 | 缓解 |
|---|---|---|
| API 兼容性 | 三国 service URL 全部 404 | 三国 customer 无 → 无回归 |
| 数据库 schema | 17 表去 country_code + 4 表 drop | downgrade migration 完整可逆 |
| 前端 i18n | 4 语种切换失效 | apps/ 前端默认 zh_CN，多语种无 customer |
| Feature flag 灰度 | 15 个 MalaysiaFlags 失效 | 已无 flag consumer |
| 边缘 (Mac mini) | 无 — 区域代码不在 edge/ 路径 | N/A |
| CI Pipeline | 三服务的 docker build / 测试 stage 移除 | 净加速 CI |
| Helm chart | tx-malaysia / tx-indonesia / tx-vietnam chart 删 | infra/helm/ 减 3 chart |
| 审计文档 | `docs/security/` 三国审计记录 | **保留**（CSO 审计活历史不删，CLAUDE.md §14 指针不变） |

---

## 风险 + User 决策点

| 风险 / 决策点 | 类型 | 建议 |
|---|---|---|
| **D1**：三国 production 数据状态 | user 创始人 | 默认走"无数据 → drop"，user 确认 |
| **D2**：W2-A 单 PR 还是分 phase PR | user / engineering | 5 phase 全单 PR 是巨大 diff (60+ 文件)，建议 **Phase 1+2 一 PR / Phase 3 一 PR / Phase 4 一 PR**，T2 标 |
| **D3**：是否同时删 audit 文档历史 | user | 不删（CSO 审计活历史） |
| **D4**：W2-B Gateway 瘦身是否合并 | user / engineering | 建议 W2-A 落定后再 deep-dive，分独立 PR |
| **R1**：v384 reverse migration 在已部署生产数据库的 rollback | 工程 | drop column 在 PG 是 ALTER TABLE DROP，需评估表大小 + LOCK 窗口 |
| **R2**：apps/ 前端 i18n 切换器是否硬编码 4 语种 | 工程 | grep apps/ 中 ms_MY 引用面后再决定 |

---

## 下一步 (fresh session starter prompt)

```
继续屯象OS 12 周升级战略 — W2-A 删除 indonesia/malaysia/vietnam deep-dive。

== 起手必跑 ==
cd /Users/lichun/tunxiang-os
git fetch origin main && git log -n 5 origin/main --oneline
gh pr list --search "is:open w1 OR W2 OR regional" --limit 10

== 必读 ==
1. docs/w2-deprecate-regional-plan.md（quick recon + phase 拆分，本 session 产出）
2. DEVLOG.md 顶部 W1-T1 round-3 merge 段（commit 06f4a19f）
3. docs/progress.md 顶部 round-3 段

== 任务 ==
按 plan 文档 Phase 2 (shared 区域框架删) 起首 PR — Phase 1 已 merged commit `21fde0e6` (#499)：
- branch: refactor/w2a-remove-regional-phase2
- diff 规模预估: ~37 文件删 + 1 file edit / 0 新增（grabfood 撤回后修正）
- 验证:
  - import 链全过（`python -c "import shared.feature_flags.flag_names"` 等关键 module）
  - Tier 1 测试全绿（`pytest tests/tier1/` + `pytest shared/db-migrations/tests/test_per_service_shells_tier1.py`）
  - alembic chain integrity 不变（`python3 scripts/check_alembic_chain.py --versions-dir shared/db-migrations/versions`）

deep-recon 结论 (5/13)：
- Phase 2 11 项 0 外部 consumer（grabfood 撤回后修正；详见上方"grabfood 撤回"段）
- 7 个国际 adapter 仅自引用，全部整删（dana/foodpanda/gopay/momo/myinvois/shopeefood/zalopay）
- VietnamFlags + IndonesiaFlags class 0 consumer，删 enum 段

== 强制约束 ==
- CLAUDE.md §14 / §17 / §18 / §19 / §20 全约束
- Phase 4 reverse migration **必须 user 创始人确认 D1** 再写
- Phase 1+2 PR T2 标，不 admin-merge 但可 normal merge with 1 reviewer
- memory feedback_concurrent_pr_race: push/PR 前 fetch + log -n 5

== 持续阻塞 ==
- PR #487 W1-T2/T3/T4/T5 仍 OPEN 等 reviewer（不阻塞 W2-A）
- B: dev-plan-60d demo 故事核心
- C: DailySummary / Header export ontology

== W1 完工状态 ==
- W1-T1 (#489) ✅ MERGED 2026-05-13T01:47:42Z commit 06f4a19f
- W1-T2/T3/T4/T5 (#487) OPEN 等 reviewer
```

---

## 沿用 PR 风格

- W2-A Phase 1+2 PR T2 标 + 不 admin-merge + 1 reviewer normal merge
- Commit message：`refactor(regional): 删除 indonesia/malaysia/vietnam 国际化 Phase 1+2 [T2]`
- 沿用本仓库 squash merge 风格（每 PR = main 上 1 commit）

---

## 锚点

- 触发 PR：#489 W1-T1 merge (commit `06f4a19f`)
- 关联 commit history：`1f9e592b` (PR #129) 三国引入
- 关联文档：CLAUDE.md §一 / §17 / §18 / §22 (Week 8 DEMO 验收)
- 关联 hardening issue：#496 (lifespan startup 序列闭合)
