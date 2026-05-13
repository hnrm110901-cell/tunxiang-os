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

### Phase 2 — shared 区域框架（中风险，跨服务）

- `shared/region/` 整目录删（PR #129 引入）
- `shared/security/data_sovereignty.py` 整文件删
- `shared/adapters/delivery_publish/publishers.py` + `shared/adapters/delivery_canonical/transformers.py` 中的国际外卖分支

### Phase 3 — tx-agent / tx-trade / tx-finance 内嵌分支（中风险，surgical）

**tx-agent**:
- `services/tx-agent/src/api/regional_forecast_routes.py` 整文件删（PR #129 引入）
- `services/tx-agent/src/services/regional_forecasting_service.py` 整文件删
- `services/tx-agent/src/services/malaysia_forecasting_service.py` 整文件删
- `services/tx-agent/src/config/malaysia_ingredients.py` + `malaysia_holidays.py` 整文件删

**tx-trade**:
- `services/tx-trade/src/routers/delivery_panel_router.py` — surgical 删 FoodPanda / ShopeeFood 路由
- `services/tx-trade/src/services/my_payment_notify_service.py` 整文件删
- `services/tx-trade/src/services/delivery_adapters/foodpanda_adapter.py` + `shopeefood_adapter.py` 整文件删

**tx-finance**:
- `invoice_service.py` MY 分支删（LHDN MyInvois 电子发票）

### Phase 4 — Alembic 反向 migration（高风险，需 user 决策点）

**user 决策点 D1：三国 production 是否有真实 tenant 数据？**

- 若**无**：写 v414+ migration 反向 drop column / drop table（country_code / sst_category / subsidy_programs / tenant_subsidies / subsidy_bills / pdpa_requests / pdpa_consent_logs / ppn_category / vat_category）
- 若**有**：保留 column 但停用代码（Phase 1-3 仍执行，但 country_code 等保留）；后续 N 月按 production 数据自然衰减再清理

按 user prompt（首批客户都在国内）+ commit history（三国服务上线时间 5/3，离当前 10 天，customer adoption 极有限），**默认走"无 production 数据"分支**，等 user 确认后写 v414+ 反向 migration。

### Phase 5 — Gateway 瘦身（W2-B 联动）

W2-B "Gateway 瘦身" 范围未细说，但与 W2-A 联动点：
- `services/gateway/` 删除三国服务的路由代理
- Gateway 健康检查删除 tx-malaysia / tx-indonesia / tx-vietnam upstream

→ **deep-dive 在 fresh session 单独评估**，W2-A merge 后才能精确 grep gateway 影响。

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
按 plan 文档 Phase 1+2 (服务整删 + shared 框架删) 起首 PR：
- branch: refactor/w2a-remove-regional-phase1-2
- diff 规模预估: 50+ 文件删 / 1500+ 行删 / 0 新增（除 reverse migration）
- 验证: import 链全过（python -m pytest -k "not regional" 全绿）

deep-dive 要点：
- gateway 路由代理是否引用三国 service URL（grep services/gateway/）
- infra/compose/ + infra/helm/ 三国 chart / yaml 删除
- apps/ i18n 资源精确路径
- shared/feature_flags/ MalaysiaFlags 删除 import side-effects

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
