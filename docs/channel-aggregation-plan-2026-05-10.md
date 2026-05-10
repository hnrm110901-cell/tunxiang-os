# 全渠道聚合开发计划 — 2026-05-10

> **横切计划**，叠加在 `docs/dev-plan-60d-2026-05-09.md` W3-W6 主线之上。
> 目标：让屯象OS 能把美团 / 抖音 / 饿了么 / 微信 / 小红书 / 高德 / 淘宝系的人、财、物、信息聚合到统一中台，支撑 W8 (7/4) 徐记海鲜 demo 的"全渠道驾驶舱"故事线。
>
> **Living document**：每周一晨段更新一次，会话起手前优先读本文件。

---

## 0. 起点：dev-plan-60d 关系

| dev-plan-60d 锚点 | 本计划承接 |
|---|---|
| W2 S4-02 NLQ 闭环（已完成 PR #330-#333） | NLQ 是聚合下游消费方，无需改 |
| W3-4 14 报表（G3 候选清单待答） | 至少 4 张是渠道聚合报表（团购核销 / 渠道毛利 / 投放 ROI / 评价健康度），CH-07/12/18 直接出料 |
| W5-6 P1-10 团购核销 4 平台 | **与本计划 Phase 1 (CH-03..CH-06) 完全重叠**，建议合并为同一批 PR |
| W7-8 demo 彩排 | CH-21/22 入场 |

**本计划不替换主线**，只补"全渠道"主题在 60d plan 里被低估的工作量与缺失基建。

---

## 1. 现状真值表（5/10 实测）

### 1.1 外卖 adapter 双层并存（重要发现）

每个平台同时存在两层实现：top-level `*_delivery_adapter.py`（早期 mock 层）+ subdir `{platform}/src/`（后期真接入层）。`shared/adapters/delivery_factory.py` **注册的是 top-level**，subdir 真层除 `meituan-saas` 在 `apps/api-gateway` 用之外**未被工厂引用**。

| 平台 | top-level LOC | top-level 真接入信号 | subdir 真层 LOC | subdir 真接入信号 | 写入目标 schema | 测试 |
|---|---|---|---|---|---|---|
| 美团 | `meituan_delivery_adapter.py` 447 | http:0 / sig:4 / **mock 数据生成器** | `meituan-saas/src/` 1334 | client http:6 / adapter to_order/handle_error/auth 完整 | **OrderSchema**（早期模型） | 共用 846 + 独立 690 / 35 tests |
| 抖音 | `douyin_delivery_adapter.py` 447 | http:0 / sig:9 / mock | `douyin_open_platform/src/` 550 | adapter 仅 161 行（基本空）/ client http:4 / sig:4 | **无** | 仅共用 |
| 饿了么 | `eleme_delivery_adapter.py` 436 | http:0 / sig:10 / mock | `eleme_open_platform/src/` 832 | adapter to_order 376 行 / client http:4 / sig:6 | **OrderSchema** | 仅共用 |
| 微信 | `wechat_delivery_adapter.py` 217 | http:0 / sig:0 / **几乎全空** | 无 | — | **无** | 仅共用 |
| 小红书 | — | — | `xiaohongshu/src/` 1160 | oauth_token + signature + xhs_client + coupon + poi_sync + **review_crawler** | **CanonicalDeliveryOrder**（仅 verification 路径） | 独立 530 / 47 tests |
| Grabfood / Foodpanda / Shopeefood | — | — | 各 ~300+ | 出海储备，不在 demo 路径 | — | 仅共用 |

### 1.2 Canonical 体系部分接入，webhook→canonical 未桥接

- `shared/adapters/delivery_canonical/` 完整存在（base / registry / transformers，对齐 v285 migration）
- `ALLOWED_PLATFORMS = {meituan, eleme, douyin, xiaohongshu, wechat, grabfood, other}`
- **服务端入口已就绪**（5/10 二次校准发现）：
  - `services/tx-trade/src/services/channel_canonical_service.py` 377 LOC — `ChannelCanonicalRepository` + `ChannelCanonicalService` 完整
  - `services/tx-trade/src/api/channel_canonical_routes.py` 188 LOC — `POST /orders ingest_canonical_order` + `GET /orders` + `GET /orders/{id}`
  - `services/tx-trade/src/tests/test_channel_canonical_tier2.py` 357 LOC — Tier 2 测试已覆盖
- **Webhook 接收已就绪**：
  - `services/tx-trade/src/api/webhook_routes.py` 512 LOC — `POST /meituan/order` / `/eleme/order` / `/douyin/order` 三平台路由已实现，含签名校验
  - 三路由都已 `emit_event(ChannelEventType.ORDER_SYNCED)` 事件总线接入完成
- **`omni_sync_routes.py` 1035 LOC 存在**（omni-channel 同步入口，需进一步勘察）
- **关键缺口**：
  - webhook 路由调用的是 top-level **mock adapter** `MeituanDeliveryAdapter.receive_order()`，**没有调用 channel_canonical_service.ingest_canonical_order()** —— 数据未真正落 canonical_delivery_orders
  - subdir 真层 adapter（如 meituan-saas）`to_order()` 写的是 `apps/api-gateway/src/schemas/restaurant_standard_schema.OrderSchema`（早期模型），与 canonical 平行存在
  - `delivery_canonical/registry.py` 的 transformer 仅小红书 verification 路径调用

### 1.3 Marketing / 评价 / 身份层

| 类别 | 现状 |
|---|---|
| `shared/integrations/{meituan,douyin,xiaohongshu,wechat}_marketing.py` | 占位文件（未实质化） |
| 评价归一化模型 | 无（小红书 review_crawler 单点存在，无 canonical 层） |
| 投放归一化模型 | 无 |
| Identity Resolution / CDP | 无（`mv_member_clv` v148 仅按内部 member_id 聚合，不跨渠道） |
| OAuth token 持久化 | 无统一表（小红书有 `oauth_token_service.py` 单点实现） |
| 统一 Webhook 网关 | 无（每平台各自 webhook handler） |

### 1.4 mv_* 物化视图（v148 已建 8 张，v404-v406 已暴露给 NLQ）

`mv_discount_health / mv_channel_margin / mv_inventory_bom / mv_member_clv / mv_store_pnl / mv_daily_settlement / mv_safety_compliance / mv_energy_efficiency`

聚合维度都是按 internal store / member，**没有按 platform / external_account 维度聚合**。`mv_channel_margin` 名字带 channel 但实际是按内部销售渠道（堂食 / 外卖 / 团购 / 储值）聚合，不是按外部平台。

---

## 2. 缺失清单（决定 PR 范围）

| # | 缺失项 | 阻塞 demo？ |
|---|---|---|
| 1 | OAuth token 多门店多账号统一表 + 加密存储 | 是（CH-01） |
| 2 | webhook 路由 → channel_canonical_service 桥接（meituan/eleme/douyin 现走 mock adapter） | 是（CH-02，**降至轻量**） |
| 3 | 原始 payload 落湖（raw_channel_events 表，幂等 dedup_key） | 是（CH-02.5） |
| 4 | 双层 adapter 收敛（subdir 真层接 transformer + 工厂入口收口） | 是（CH-02.7） |
| 5 | 4 平台 adapter 实质化 transformer 实现 → 写 CanonicalDeliveryOrder | 是（CH-03..06） |
| 6 | 微信外卖 webhook + adapter 全新建（webhook_routes 仅 3 平台） | 仅微信场景需要（CH-06） |
| 7 | mv_channel_funnel（按 platform × store × day 聚合订单 / GMV / 退款率） | 是（CH-07） |
| 6 | CanonicalReview 模型 + 4 平台拉取 + LLM 情感打标 + mv_review_sentiment | 加分项（CH-08..12） |
| 7 | member_identity_map + ChannelIdentityResolver + mv_member_clv 全渠道版 | 是（CH-13..15，"老客复购率"卖点） |
| 8 | CanonicalAdSpend + 3 平台投放接入 + mv_ad_roi | 加分项（CH-16..18） |
| 9 | 高德 adapter（POI / 路径 / ETA） | 否（demo 后） |
| 10 | NLQ demo prompt 库 + web-admin 全渠道驾驶舱 Pin 卡 | 是（CH-21/22） |

---

## 3. PR 明细（校准估时）

约定：每个 PR 标 **Tier / 估时 / diff size / 依赖**。遵循 `CLAUDE.md §16 §18` 双 commit 留痕、≤350 行 diff、Tier 1 必须 TDD（真 PG fixture, opt-in via `INTEGRATION_PG_DSN`，参照 PR #333 模式）。

> **版本号说明**：plan 中 `v4XX_*` 是占位号，**实际 migration 版本按 PR merge 顺序分配**。当 v413/v414/... 被某 PR 抢占后，后续 PR 在 rebase 时改 `down_revision` 顺移即可。

### 已起手 PR 实绩（2026-05-10 18:00）

| CH | 实际版本 | Issue | 文件 | 测试 | 状态 |
|---|---|---|---|---|---|
| CH-01 | v411_channel_oauth_tokens | [#375](https://github.com/hnrm110901-cell/tunxiang-os/issues/375) | 4 (migration + service + 2 tests) | 27 ✅ + 3 ⏳真PG | ⏳ 待 commit/push |
| CH-02.5 | v412_raw_channel_events | [#377](https://github.com/hnrm110901-cell/tunxiang-os/issues/377) | 2 (migration + test) | 16 ✅ + 2 ⏳真PG | ⏳ 待 commit/push |
| CH-13 | v413_member_identity_map | [#393](https://github.com/hnrm110901-cell/tunxiang-os/issues/393) | 4 (migration + service + 2 tests) | 43 ✅ + 3 ⏳真PG | ⏳ 待 commit/push |

**关键调整**：
- CH-13 service path：`identity_resolver.py` → `channel_identity_resolver.py`（原文件已被 S2W5 CDP WiFi 匹配占用 397 LOC，新建独立模块避免冲突；类名相应改为 `ChannelIdentityResolver`）
- CH-13 migration 编号：plan 占位 v416 → 实际 v413（按 merge 顺序分配）

### Phase 0 — 体系收敛（W3 起，3d）

#### CH-01 OAuth token 持久化表 + 加密存储 [Tier 1, 1d, ~200 LOC] ✅ 已起手

- 新增 migration `v411_channel_oauth_tokens`：
  - 字段 `tenant_id, store_id, platform, account_id, access_token_enc, refresh_token_enc, token_type, expires_at, refresh_expires_at, scope, last_refreshed_at, refresh_failure_count, last_refresh_error`
  - RLS policy（按 tenant_id, v403/v395 模式 USING + WITH CHECK）
  - 复合 UNIQUE `(tenant_id, store_id, platform, account_id)`
  - 索引 `(tenant_id, expires_at) WHERE is_deleted=FALSE` — 自动续期 job 高频
- 新增 `shared/adapters/base/src/oauth_token_store.py`（**应用层 Fernet 加密**，不依赖 pgcrypto；密钥从 env `OAUTH_TOKEN_ENCRYPTION_KEY`）：
  - `OAuthTokenStore.get / upsert / get_or_refresh / list_expiring_within / _record_refresh_failure`
  - 自动续期：threshold_seconds 默认 300s，失败累加 `refresh_failure_count` + 记录 `last_refresh_error`
- TDD：cross-tenant 反测、token 解密 wrong-key/篡改抛 TokenDecryptError、Fernet 同明文双次加密结果不同（防离线相等性攻击）
- 依赖：无

#### CH-02 webhook 路由桥接 channel_canonical_service [Tier 1, 0.5d, ~150 LOC]

> **校准说明**：`webhook_routes.py` 三平台路由 + `channel_canonical_service.py` 服务层均已存在，缺的只是桥接调用。

- 改 `services/tx-trade/src/api/webhook_routes.py` 三个路由（meituan/eleme/douyin），把 `delivery_adapter.receive_order()` 的调用替换为 `channel_canonical_service.ingest_canonical_order()`
- 在调用前先经 `delivery_canonical/registry.transform(platform, raw, tenant_id)` 转 canonical
- TDD：3 平台各 1 种 sandbox payload → ingest 后能在 `canonical_delivery_orders` 查到记录 + emit_event 仍正确
- 依赖：CH-03（需要 transformer 先注册）— **Phase 0 与 Phase 1 有交叉依赖，CH-02 实际位置在 CH-03 之后**

#### CH-02.5 raw_channel_events 落湖表 [Tier 1, 0.5d, ~150 LOC] ✅ 已起手

- 新增 migration `v412_raw_channel_events`：
  - `event_id UUID PK, tenant_id, platform CHECK, external_event_id, event_type, payload JSONB, signature, received_at, processed_at, status CHECK in (pending/processed/failed/skipped), process_error, retry_count`
  - 复合 UNIQUE `(tenant_id, platform, external_event_id)` — 幂等去重
  - 索引：`(tenant_id, status, received_at) WHERE status='pending'`（重试队列）+ `(tenant_id, received_at DESC)`（审计）
  - RLS policy v403/v395 模式
- 改 `webhook_routes.py` 三路由（meituan/eleme/douyin）：在签名校验通过后立即 INSERT ON CONFLICT DO NOTHING 落表，再走 ingest（**本 PR 仅落表，路由桥接见 CH-02**）
- TDD：重复 dedup_key 幂等（ON CONFLICT 跳过）、cross-tenant 隔离、payload 完整保存
- 依赖：无（可与 CH-01 并行）

#### CH-02.7 双层 adapter 收敛（按 G-CH-2=B：subdir → top-level 并入） [Tier 1, 3d 合计, ~600 LOC 合计]

> **G-CH-2 决策为 B**：top-level 为 SoT，subdir 真层内容并入 top-level。原 1d 估时升至 3d，拆 3 sub-PR。
> **范围**：仅 meituan / eleme / douyin / wechat 4 平台；**xiaohongshu 维持 subdir 不动**（小红书走 marketing 路径，无 top-level 对应文件）

**CH-02.7a** meituan subdir 内容并入 top-level [1.5d, ~300 LOC]
- 把 `meituan-saas/src/{client,adapter,order_webhook_handler}.py` 1334 LOC 内容并入 `meituan_delivery_adapter.py`
- 删除 `_mock_orders` 函数（移到 `tests/fixtures/channel_mocks/meituan_fixtures.py`）
- meituan-saas/tests 35 tests 重指向 top-level
- TDD：先跑全量 baseline → 迁移后 0 失败方算通过

**CH-02.7b** eleme + douyin subdir 内容并入对应 top-level [1d, ~200 LOC]
- 类比 02.7a 模板，douyin (550 LOC) + eleme (832 LOC) 并入

**CH-02.7c** subdir 删除 + import 重定向 + delivery_factory 确认 [0.5d, ~100 LOC]
- 删 `meituan-saas/src/` `eleme_open_platform/src/` `douyin_open_platform/src/`
- 全仓 grep `from shared.adapters.{meituan-saas,eleme_open_platform,douyin_open_platform}` import 重定向
- `delivery_factory.py` 确认仍指向 top-level（已是）

依赖：无（结构改动可与 CH-01 / CH-02.5 并行）

### Phase 1 — 4 平台外卖订单实质化（W3 末-W5，demo 必需）

> **核心调整**：所有 PR 的"实质化"指 (a) 真 API client wiring (b) 实现 `to_canonical()` 返回 `CanonicalDeliveryOrder` (c) 桥接 ingest 链路写 canonical_delivery_orders + orders + Saga + emit_event。

#### CH-03 美团 transformer 实现 + 接入 [Tier 1, 1d, ~200 LOC]

- 改 `shared/adapters/meituan-saas/src/adapter.py`：
  - 新增 `to_canonical(payload, tenant_id) -> CanonicalDeliveryOrder`（**复用现有 to_order 字段映射逻辑**，仅改输出类型）
  - 改类继承 `DeliveryPlatformAdapter`
- 新增 transformer 实现到 `shared/adapters/delivery_canonical/transformers.py`（如未实现 meituan）+ `register_transformer`
- ingest 链路使用现有 `channel_canonical_service.ingest_canonical_order()`（**不新增 service，复用**）
- TDD：5 种美团 sandbox payload → 全部入 canonical_delivery_orders + 状态机推进 + emit_event 仍正确
- 依赖：CH-02.7（基类继承）

**校准说明**：原估 2d/350 LOC → 二次校准发现 ingest 服务已存在，降至 1d/200 LOC。

#### CH-04 抖音 transformer 实现 + adapter 实质化（拆 2 sub-PR） [Tier 1, 2.5d 合计, ~450 LOC 合计]

**CH-04a** 抖音 adapter 字段映射补全 [1.5d, ~250 LOC]
- `douyin_open_platform/src/adapter.py` 当前 161 行（基本空），补完整字段映射
- 实现 `to_canonical()` + 继承 `DeliveryPlatformAdapter`
- 抖音特殊：团购核销 vs 外卖订单两类 webhook 分支处理

**CH-04b** transformer 注册 + ingest 接入 [1d, ~200 LOC]
- 注册 transformer 到 `delivery_canonical/registry.py`
- 改 `webhook_routes.py /douyin/order` 走 ingest 链路
- TDD：团购核销 + 外卖各 3 种 payload

依赖：CH-02.7 / CH-03

#### CH-05 饿了么 transformer 实现 + 接入 [Tier 1, 1d, ~200 LOC]

- 改 `eleme_open_platform/src/adapter.py`（已有 to_order 376 行，复用）
- 实现 `to_canonical()` + transformer 注册
- 改 `webhook_routes.py /eleme/order` 走 ingest 链路
- 依赖：CH-02.7 / CH-03

#### CH-06 微信外卖 webhook + adapter 全新建（拆 2 sub-PR） [Tier 1, 3d 合计, ~500 LOC 合计]

> **微信缺口最大**：`webhook_routes.py` 没有 `/wechat/order` 路由；`wechat_delivery_adapter.py` 仅 217 行 + http:0 + sig:0；无 subdir 真层。

**CH-06a** 微信 webhook 路由 + adapter 真接入层新建 [1.5d, ~250 LOC]
- 新建 `shared/adapters/wechat_delivery/src/{adapter,client,webhook_handler}.py`（与其它平台对齐）
- `webhook_routes.py` 新增 `POST /wechat/order` + 签名校验
- 实现 client + signature

**CH-06b** transformer 实现 + ingest 接入 [1.5d, ~250 LOC]
- `to_canonical()` + transformer 注册
- 桥接 channel_canonical_service

依赖：CH-02.7 / CH-03

#### CH-07 mv_channel_funnel 聚合视图 [Tier 1, 0.5d, ~150 LOC]

- 新增 migration `v413_mv_channel_funnel`：按 `tenant_id × store_id × platform × order_date` 聚合订单数 / GMV / 平均客单 / 退款率 / 取消率
- 暴露给 NLQ：扩 `v406` 模式的 reports view
- TDD：物化视图刷新一致性 + RLS 隔离 + NLQ 查询能命中
- 依赖：CH-03..CH-06 任一 merged

**Phase 0+1 小计**：12 PR / **三次校准 12.5d**（二次校准 10.5d → 因 G-CH-2=B 决策 CH-02.7 拆 3 sub-PR 增 2d）

### Phase 2 — 评价聚合（W4-W5，demo 加分项）

#### CH-08 CanonicalReview 模型 + 迁移 [Tier 1, 1d, ~250 LOC]

- 新增 `shared/adapters/review_canonical/{base,registry,transformers}.py`（对标 delivery_canonical 结构）
- 新增 migration `v414_canonical_reviews`：
  - `tenant_id, store_id, platform, external_review_id UNIQUE, rating, content, sentiment_score, keywords[], replied_at, raw_payload jsonb`
  - RLS + 平台 CHECK 约束（复用 ALLOWED_PLATFORMS）

#### CH-09 美团 / 点评评价拉取 [Tier 2, 1.5d, ~300 LOC]

- 改造 `shared/adapters/meituan-saas/src/`：增 `review_client.py + review_poller.py`
- 新增 `services/tx-trade/src/jobs/channel_review_poll_job.py`（每小时轮询，落 canonical_reviews）

#### CH-10 抖音视频评论拉取 [Tier 2, 1.5d, ~300 LOC]

- 同上结构。**抖音 API 需巨量引擎资质**，资质未到位则留 stub + 文档

#### CH-11 小红书评价 / 笔记数据 [Tier 2, 2d, ~400 LOC]

- 复用 `xhs_review_crawler.py`（已存在！1160 LOC subdir）
- 接 canonical_reviews + 合规标注（`source = 'crawler' | 'official'`）
- **关键合规**：crawler 数据进入隔离 schema `reviews_crawler_*`，**不入主 canonical_reviews**，不上 demo 现场（避开合规问询）

#### CH-12 mv_review_sentiment + Claude API 情感打标 [Tier 1, 1.5d, ~300 LOC]

- 新增 `services/tx-brain/src/skills/review_sentiment_skill.py`（调 Claude API 批量打 sentiment + 关键词，复用 `shared/ai_providers/`）
- 新增 migration `v415_mv_review_sentiment`（按 store × platform × week 聚合）
- TDD：mock LLM → 打标准确率 + 成本上限熔断

**Phase 2 小计**：5 PR / 7.5d

### Phase 3 — Identity Resolution / CDP（W4-W5，"老客复购率" demo 卖点）

#### CH-13 member_identity_map 表 + ChannelIdentityResolver [Tier 1, 2d, ~400 LOC] ✅ 已起手

- 新增 migration `v413_member_identity_map`（实际分配，plan 原占位 v416）：
  - `tenant_id, member_id, identity_type (phone/openid/card_no/email), identity_value_hash CHAR(64), platform, confidence, first_seen_at, last_seen_at, source`
  - 复合 UNIQUE `(tenant_id, identity_type, identity_value_hash, platform)` **NULLS NOT DISTINCT** (PG 15+) — 让 phone 类型 (platform=NULL) 也参与去重
  - phone / email / card_no 全部 SHA256 + salt 哈希存储（salt 从 env `IDENTITY_HASH_SALT`）
- 新增 `services/tx-member/src/services/channel_identity_resolver.py`（**新文件名**，原 `identity_resolver.py` 已被 S2W5 CDP WiFi 匹配占用 397 LOC）：
  - `ChannelIdentityResolver.resolve(tenant_id, identity_type, value, platform) -> member_id | None`
  - `.link(tenant_id, member_id, identity_type, value, platform, confidence, source)`
  - `.get_or_create_member(...)` — resolve 不命中则自动创建 member（CH-14 用）
  - `.list_member_identities(tenant_id, member_id)` — 反向列出 identity（CH-15 用）
  - 标准化函数 `_normalize_phone`（去 +86/前导 0/空格/横线）/`_normalize_email`（lower+trim）/etc
- TDD：cross-tenant 隔离 + 哈希一致性（同 phone 不同格式 → 同 hash）+ 并发 upsert 不重复 + salt 隔离

#### CH-14 渠道订单反向解析到 member_id [Tier 1, 1.5d, ~250 LOC]

- 改造 CH-03 的 `channel_canonical_service`：在 ingest 时调 `ChannelIdentityResolver`，把 platform openid / phone → member_id 写到 `orders.member_id`
- TDD：4 平台订单 + 同一手机号 → 同一 member_id

#### CH-15 mv_member_clv 全渠道版升级 [Tier 1, 1d, ~200 LOC]

- 重写 v148 `mv_member_clv`，按 `member_id` 跨 platform 聚合
- 扩字段 `channel_diversity_score`（多渠道触达度）
- TDD：兼容性反测（旧字段不变 + 新字段语义正确）

**Phase 3 小计**：3 PR / 4.5d

### Phase 4 — 投放 ROI（W5 末，demo 加分项）

#### CH-16 CanonicalAdSpend 模型 + 迁移 [Tier 1, 1d, ~250 LOC]

类比 CH-08，新增 `shared/adapters/ad_canonical/` + migration `v417_canonical_ad_spend`（cost_fen / impression / click / campaign_id / platform）

#### CH-17 美团 / 抖音 / 小红书投放数据接入 [Tier 2, 2d, ~400 LOC]

实质化 `shared/integrations/{meituan,douyin,xiaohongshu}_marketing.py`，每日 T+1 拉 spend + impression

#### CH-18 mv_ad_roi 聚合视图 [Tier 1, 1d, ~200 LOC]

关联 ad_spend + canonical_delivery_orders（按 utm_campaign / coupon_code 归因），暴露给 NLQ

**Phase 4 小计**：3 PR / 4d

### Phase 5 — 高德地图（W6 / demo 后均可）

#### CH-19 高德 adapter 骨架 [Tier 2, 1d, ~200 LOC]

新增 `shared/adapters/gaode/src/{client.py, geocoder.py, routing.py, eta.py}`

#### CH-20 配送 ETA 集成 [Tier 2, 1d, ~200 LOC]

改 `services/tx-trade/src/services/delivery_dispatch_service.py`，注入 ETA

**Phase 5 小计**：2 PR / 2d

### Phase 6 — Demo 集成（W7-W8）

#### CH-21 全渠道聚合 NLQ 示例查询库 [Tier 3, 1d, ~150 LOC]

`services/tx-brain/` 增 NLQ demo prompts + `docs/demo-playbook-channel-aggregation.md`：
- "上周抖音和美团的核销转化率对比"
- "小红书种草到门店核销的最长链路"
- "全渠道老客复购占比 TOP10 门店"

#### CH-22 web-admin 全渠道驾驶舱 Pin 卡 [Tier 2, 1.5d, ~250 LOC]

复用 S4-04 Pin 框架，新增 4 张卡：渠道漏斗 / 评价情感 / 投放 ROI / 全渠道 CLV

**Phase 6 小计**：2 PR / 2.5d

---

## 4. 时间线（叠加 dev-plan-60d 主线）

```
W2 (5/9-5/15) ▓▓▓▓▓▓ Sprint 4 PR2 主线（不动）
W3 (5/16-5/22) ▓▓▓▓ 14 报表 + ▓▓▓ Phase 0 (CH-01/02/02.5)
W4 (5/23-5/29) ▓▓▓▓ 14 报表 + ▓▓▓▓▓ CH-03/04a/04b/05/07 + ▓ CH-08/13
W5 (5/30-6/5)  ▓▓ P1-10 + ▓▓▓▓ CH-06a/06b/09/10/12 + ▓▓ CH-14/15/16
W6 (6/6-6/12)  ▓▓ P1-10 + ▓▓▓ CH-11/17/18 + ▓▓ CH-19/20
W7 (6/13-6/19) ▓▓▓▓ Demo 彩排 + ▓▓ CH-21/22
W8 (6/20-7/4)  ▓▓▓▓ Demo go/no-go + 押缩
```

**Demo 必需关键路径（8 PR）**：CH-01 → CH-02 → CH-02.5 → CH-03 → CH-13 → CH-14 → CH-15 → CH-21 → CH-22

**Demo 加分（不阻塞）**：CH-04..06（其它 3 平台）+ CH-08/12（评价情感）+ CH-16..18（投放 ROI）

**Demo 后**：CH-09..11（评价拉取需平台资质）+ CH-19/20（高德）

---

## 5. Gating（需创始人决策）

### 决策矩阵总览（5/10 创始人定盘）

| Gating | 问题 | **决策** | 决策截止 | 影响 PR |
|---|---|---|---|---|
| G-CH-1 | 平台资质获取节奏 | ✅ **A 全平台真接入** | 5/22（W3 末） | CH-03..06 全部真接入 |
| G-CH-2 | 双层 adapter 收敛方案 | ✅ **B top-level 为 SoT** | CH-02.7 起手前 | CH-02.7 估时 1d→3d，全 Phase 1 顺延 2d |
| G-CH-3 | 微信外卖是否做 | ✅ **A 做完整微信外卖** | 5/29（W4 末） | CH-06 维持 3d |
| G-CH-4 | 小红书 crawler 数据合规 | ✅ **A 隔离 schema 不上 demo** | CH-11 起手前 | CH-11 + demo playbook |
| G-CH-5 | 14 报表清单是否钉 4 张全渠道 | ✅ **A 钉 4 张** | dev-plan-60d G3 答完前 | W3-4 报表 4 张归本计划 |

**总量影响**：原 24 PR / 31d → **24 PR / 33d**（G-CH-2=B 增 2d）+ **G-CH-1=A 引入资质 deal-breaker 风险**（详见各 Gating 决策章节）

---

### G-CH-1 平台资质获取节奏

> 美团 / 抖音 / 饿了么开放平台需企业资质 + 商户授权，预估 2-4 周。是否在 demo 前推动？

| 选项 | 内容 | demo 故事强度 | 工作量影响 |
|---|---|---|---|
| A | 全平台真接入（美团+抖音+饿了么+小红书）— 立即启动资质流程 | ⭐⭐⭐⭐⭐ | CH-03..06 全部 sandbox→生产；W3 末美团资质必到位 |
| B | demo 全用 sandbox 跑 — 真接入推 demo 后 | ⭐⭐ | CH-03..06 按计划但 sandbox payload；deal-breaker 风险 |
| **C 推荐** | 美团真接入 + 其他 sandbox（聚焦最大盘） | ⭐⭐⭐⭐ | CH-03 真接入；CH-04/05/06 sandbox；W3 启动美团资质流程 |

**理由**：徐记海鲜外卖 GMV 美团占主，单平台真接入足以撑 demo 故事；其它平台 sandbox 演示 + 对外说"已对接，资质审核中"无损可信度。

**决策回填**：
- [x] **A 全平台真接入**   [ ] B   [ ] C
- 决策日期：2026-05-10  决策人：未了已
- 备注：选 A 偏向"做大做全"，故事强度最高但需立即同步启动美团/抖音/饿了么 3 套企业资质流程

**⚠️ 决策风险与必须立即动作**：
1. **资质流程 deal-breaker 风险**：3 套资质 ≥2 周/套，并行也需 2-3 周。**必须 5/13（W3 起头）前已提交 3 套申请**，否则 W3 末资质未到位 → CH-03..06 全部 stuck → demo 故事崩
2. **Plan B 必须备好**：若 W3 末任一平台资质未到 → 该平台降级 sandbox + 文档说明"资质审核中"，**不得**因此延期 demo
3. **行政前置任务**：明日 5/11 即起手联系美团商户经理 / 抖音生活服务 BD / 饿了么开放平台对接人，并向法务/财务确认 3 套资质所需材料（营业执照、ICP、商户授权书等）
4. **追踪入口**：建议 dev-plan-60d 加专项跟踪条目"3 平台资质流程"，每周一晨段更新

---

### G-CH-2 双层 adapter 收敛方案

> top-level `*_delivery_adapter.py`（mock 层）+ subdir `{platform}/src/`（真层）并存，`delivery_factory` 注册的是 mock 层。CH-02.7 必须收敛。

| 选项 | 内容 | 工作量 | 风险 |
|---|---|---|---|
| **A 推荐** | subdir 真层为 SoT，top-level mock 移 `tests/fixtures/channel_mocks/` | 1d (CH-02.7) | 低，只影响测试代码引用路径 |
| B | top-level 为 SoT，subdir 真层内容并入 top-level | 3d+ | 高，meituan-saas 1334 LOC 改写风险大 |
| C | 维持双层不动（**不推荐**） | 0d | 高，永久双层维护 + delivery_factory 永远用不到真 adapter |

**理由**：subdir 真层 LOC 远超 top-level（1334 vs 447），且已有 deeper 测试覆盖（meituan 35 tests / xhs 47 tests）；top-level 的 `_mock_orders` 函数本质就是测试 fixture。

**决策回填**：
- [ ] A   [x] **B top-level 为 SoT**   [ ] C
- 决策日期：2026-05-10  决策人：未了已
- 备注：与推荐方向相反，需特别关注 meituan-saas 1334 LOC 改写风险

**⚠️ 决策风险与执行调整**：
1. **CH-02.7 估时 1d → 3d**（subdir 内容并入 top-level，工作量翻 3 倍）
2. **回归测试风险**：meituan-saas/tests 35 tests + xiaohongshu/tests 47 tests 可能因 SoT 迁移失效，必须**先跑全量 baseline → 迁移后逐项对比**，0 失败方算通过
3. **执行拆分**：CH-02.7 拆 3 sub-PR：
   - **CH-02.7a** meituan subdir 内容并入 `meituan_delivery_adapter.py`（最厚 1334 LOC，1.5d）
   - **CH-02.7b** eleme + douyin subdir 内容并入对应 top-level（共 1d）
   - **CH-02.7c** 删除 subdir + 所有 import 重定向（0.5d）
4. **xiaohongshu 特殊处理**：xhs 没有 top-level 对应文件（小红书走 marketing 路径，非外卖），**该平台 SoT 维持 subdir 不动**，G-CH-2 决策仅适用 meituan/eleme/douyin/wechat 4 平台
5. **整体 Phase 1 顺延 +2d**

---

### G-CH-3 微信外卖路径

> `webhook_routes.py` 没有 `/wechat/order` 路由，`wechat_delivery_adapter.py` 几乎全空（217 行 + http:0 + sig:0）。是否做？

| 选项 | 内容 | demo 影响 | 工作量 |
|---|---|---|---|
| A | 做完整微信外卖（公众号 + 小程序自营） | 强 | CH-06 = 3d |
| **B 推荐** | 不做微信外卖；仅保留微信支付 + 小程序点餐（已有） | 中 | 0d，节省 3d |
| C | 推 demo 后做 | 弱 | 0d in demo period |

**决策依据**：徐记海鲜微信外卖 GMV 占比？若 < 10%，B 最优。

**决策回填**：
- [x] **A 做完整微信外卖**   [ ] B   [ ] C
- 决策日期：2026-05-10  决策人：未了已
- 备注：与推荐相反，CH-06 维持 3d 不省

**执行确认**：
1. CH-06 维持 §3 既有 3d 估时（拆 CH-06a webhook + adapter 1.5d / CH-06b transformer + ingest 1.5d）不变
2. 注意微信外卖技术路径：建议先确认徐记是用"微信小程序自营外卖"还是"公众号点餐外卖"，两条路 webhook 接入口不同
3. 因微信开放平台资质相对宽松（小程序商家版即可），**资质风险显著低于 G-CH-1 的 3 平台**

---

### G-CH-4 小红书 crawler 数据合规

> `xhs_review_crawler.py` 已存在 1160 LOC subdir，但 crawler 数据合规边界灰区。是否上 demo？

| 选项 | 内容 | 合规风险 | demo 故事影响 |
|---|---|---|---|
| **A 推荐** | 进隔离 schema `reviews_crawler_*`，**不上 demo 现场** | 低 | 中（小红书评价完全不出现在 demo） |
| B | 完全不接 crawler 数据，仅接小红书蒲公英官方 API | 极低 | 弱（demo 无小红书） |
| C | 上 demo 但加显式合规免责声明 | 高 | 强 |

**决策依据**：徐记法务团队风险偏好 + 小红书种草是否本次 demo 卖点。**默认 A 最稳**。

**决策回填**：
- [x] **A 隔离 schema 不上 demo**   [ ] B   [ ] C
- 决策日期：2026-05-10  决策人：未了已

**执行确认**：
1. CH-11 实施时，crawler 数据进入新建 schema `reviews_crawler_*`，不接 `canonical_reviews` 主表
2. NLQ 端不暴露 `reviews_crawler_*` schema（`tx_nlq_readonly` role 不授权）
3. demo playbook（CH-21）不包含小红书评价/笔记相关 prompt
4. demo 现场若被问及小红书数据：标准回答"crawler 数据已采集，进入合规审核流程，本次 demo 不展示"

---

### G-CH-5 14 报表清单 vs 渠道聚合报表

> `dev-plan-60d-2026-05-09.md` §2 W3-4 14 报表清单 G3 待答，能否钉 4 张全渠道报表入清单？

| 选项 | 内容 | 影响 |
|---|---|---|
| **A 推荐** | 钉 4 张：`mv_channel_funnel` + `mv_review_sentiment` + `mv_ad_roi` + `mv_member_clv` 全渠道版 | 14 报表里 4 张直接归本计划，节约重复工作 |
| B | 不钉，14 报表与全渠道聚合独立交付 | 报表团队和 channel 团队可能重复造轮子 |
| C | 部分钉（仅 channel_funnel + member_clv 2 张） | 折中，少 2 张 demo 卖点 |

**决策依赖**：本 Gating 与 dev-plan-60d 主线 G3（14 报表清单）联动决策。

**决策回填**：
- [x] **A 钉 4 张**   [ ] B   [ ] C
- 决策日期：2026-05-10  决策人：未了已

**执行确认**：
1. dev-plan-60d-2026-05-09.md §2 W3-4 节加注："4 张全渠道报表（mv_channel_funnel / mv_review_sentiment / mv_ad_roi / mv_member_clv 全渠道版）已钉入 14 报表清单，归本计划 CH-07/12/18/15 交付"
2. dev-plan-60d 主线 G3（14 报表清单）剩 10 张待答（=14-4）
3. 报表团队和 channel 团队**避免重复造轮子**的责任落到本计划 CH-07/12/15/18 owner 身上

---

### 决策回填后动作

1. patch 本节决策回填区
2. 在 `DEVLOG.md` 当日条目记录"G-CH-X 决策为 X"
3. 影响的 PR 估时按决策选项对应工作量更新（patch §3 / §7）
4. 若 G-CH-3 选 B → 从 §3 删除 CH-06 + §4 时间线节省 3d
5. 若 G-CH-2 选 B → CH-02.7 估时 1d → 3d，全 Phase 1 顺延 2d

---

## 6. 与 CLAUDE.md 规范对齐

- 所有 Tier 1 PR 双 commit 留痕（test commit + impl commit）
- ≤350 行 diff（CH-04/CH-06 已主动拆 sub-PR，CH-13 接近上限需注意）
- Tier 1 跑真 PG 集成测试（opt-in via `INTEGRATION_PG_DSN`，参照 PR #333）
- 所有金额字段用**分（整数）**（铁律）
- emit_event 异步旁路（v147+ 标准），新增事件类型：`order.created.from_channel`、`review.received`、`ad_spend.recorded`、`identity.linked`
- RLS 反测必做（参照 PR #333 模式：security_invoker / WHERE 过滤 / 敏感字段 / role 权限边界）
- 提交格式：`feat(channel): CH-XX [描述] [Tier1]`
- 会话结束更新 DEVLOG.md + docs/progress.md

---

## 7. 总量（5/10 创始人定盘后）

- **28 PR / 33d / 横跨 W3-W7**（Phase 0 拆 5 PR：CH-01 / CH-02 / CH-02.5 / CH-02.7a/b/c）
- 其中 Tier 1 = 18 PR，Tier 2 = 6 PR，Tier 3 = 2 PR
- Demo 必需关键路径：12 PR / 12d（CH-01/02/02.5/02.7a-c/03/07/13/14/15/21/22）
- 与 dev-plan-60d 主线 P1-10 团购核销有 4 PR 重叠（CH-03..CH-06），合并后净增量 22 PR / ~24d
- **创始人定盘影响**：
  - G-CH-1=A → CH-03..06 全平台真接入（资质 deal-breaker 风险，5/13 前必须提交 3 套申请）
  - G-CH-2=B → CH-02.7 1d → 3d，拆 3 sub-PR
  - G-CH-3=A → CH-06 维持 3d
  - G-CH-5=A → 14 报表里 4 张归本计划交付

---

## 8. Living Doc 维护规则

- 每周一晨段 review 并标记完成 PR（链 PR #）
- 任何 PR merged 后 24h 内回填 DEVLOG.md + docs/progress.md，并 patch 本文件相关 PR 标 ✅
- Gating 解答后立即 patch 第 5 节
- adapter 实质化进度变化（top-level → subdir 迁移）必须 patch 第 1 节真值表
- 本文件腐化（>3 天 PR 状态滞后）→ 全文重写并存为 `channel-aggregation-plan-YYYY-MM-DD.md`

---

## 9. 起手协议（5/10 定盘后）

**5/11 即起头**（创始人级别，非技术）：
1. 联系美团商户经理 / 抖音生活服务 BD / 饿了么开放平台对接人，启动 3 套企业资质流程
2. 向法务/财务确认资质所需材料（营业执照、ICP、商户授权书等）
3. 5/13 前 3 套申请必须已提交（G-CH-1 deal-breaker 关）

**5/12-5/15 W2 末（技术，并行起）**：
1. 起 CH-01 + CH-02.5 + CH-13 三 PR 完全独立可并行
2. 起 CH-02.7a meituan subdir → top-level 收敛（最厚 1334 LOC，先行）

**5/16-5/22 W3（技术，闭环验证）**：
1. CH-02.7a/b/c 全 merged 后起 CH-03（美团 transformer + ingest 桥接，最快闭环）
2. CH-03 验证通后并行起 CH-02 + CH-04/05/06
3. **5/22 资质 Gating**：3 平台资质未到位的降级 sandbox + 文档说明

**5/23 起 W4-W6**：按 Phase 1-4 时间线推进

**reviewer 通道（按 §19 独立验证）**：CH-02 / CH-03 / CH-13 / CH-15 / CH-02.7a 必须开新会话从徐记海鲜收银员视角重检
