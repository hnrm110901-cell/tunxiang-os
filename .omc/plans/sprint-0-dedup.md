# Sprint 0 · 重复模块去重执行计划（R1-R7）

**决策日期**：2026-05-06
**决策人**：lichun（创始人）
**原则**：已开发功能不删，只处理"真重复"。海外功能 W12 内一律冻结，不在本计划范围。
**目标 commit 原子化**：每条 R 一个独立 commit，可回滚。
**工作分支**：建议从 `fix/pg1-1-alembic-merge-v397` 切 `chore/sprint-0-dedup` 单独走。

---

## 总览

| 编号 | 对象 | 动作 | 工时估算 | 风险 | 顺序 |
|---|---|---|---:|---|---:|
| R1 | `services/tunxiang-api/` | 迁 import → 删 service | 半天 | 中（7 skill + 测试改路径）| 4 |
| R2 | `edge/mac-mini/` | git mv 入 mac-station → 删 | 30 分钟 | 低 | 2 |
| R3 | `apps/android-shell/` × `apps/android-pos/` | ⏸ **SUSPENDED** — 升级为独立 V4 架构对齐 sprint（见 v4-architecture-alignment.md）| 7 天 | 高（双重宪法违反，需重新对齐）| — |
| R4 | `tx-brain` + `tx-intel` + `tx-predict` → `tx-agent/sub/` | **W12 后做**，本计划仅留 marker | — | 高 | （延后）|
| R5 | `shared/adapters/meituan/`（空目录）| git rm | 1 分钟 | 零 | 1 |
| R6 | 外卖三家 单文件 + 目录重命名 | git mv + 改 import | 1 小时 | 低 | 5 |
| R7 | `apps/miniapp-customer/`（v1）| README 标 deprecated | 10 分钟 | 零 | 6 |

总工时 ~4 小时 + 一次完整 CI 跑测。

---

## R5 — 删除 `shared/adapters/meituan/` 空目录（先做，零风险）

**前置检查**
```bash
find /Users/lichun/tunxiang-os/shared/adapters/meituan -type f | wc -l   # 必须 = 0
grep -rn "from shared.adapters.meituan import\|adapters\.meituan\." /Users/lichun/tunxiang-os --include="*.py" | grep -v "_adapter\|__pycache__"  # 必须无命中
```

**执行**
```bash
git rm -r shared/adapters/meituan
git commit -m "chore(adapters): remove empty meituan dir (R5)

Empty placeholder. Real meituan delivery logic lives in
shared/adapters/meituan_adapter.py (mock delivery) and will move to
shared/adapters/delivery/meituan/ in R6."
```

**验收**：`shared/adapters/meituan_adapter.py` 仍可 import；CI 全绿。

**回滚**：`git revert <sha>`

---

## R2 — 合并 `edge/mac-mini/` 入 `mac-station/`

**已查证**
- `edge/mac-mini/offline_buffer.py` 与 `edge/mac-station/src/offline_buffer.py` 同源（注释一字不差）
- `edge/mac-mini/print_queue.py` 在 `mac-station/src/` 中**不存在**——需迁入
- `mac-station` 是完整边缘服务（22 文件）

**前置检查**
```bash
diff edge/mac-mini/offline_buffer.py edge/mac-station/src/offline_buffer.py    # 看是否完全一致
grep -rn "edge\.mac_mini\|edge/mac-mini\|from mac_mini" /Users/lichun/tunxiang-os --include="*.py"   # 看引用
```

**执行**
```bash
# 1. 把 print_queue.py 迁到 mac-station
git mv edge/mac-mini/print_queue.py edge/mac-station/src/print_queue.py

# 2. offline_buffer.py 已重复，直接删 mac-mini 的
git rm edge/mac-mini/offline_buffer.py

# 3. 删空目录
rmdir edge/mac-mini  # 若 mac-mini 还有 README/__init__.py 之类的，git rm 后 rmdir
git rm -r edge/mac-mini 2>/dev/null || true

# 4. 在 mac-station/src/__init__.py 暴露 print_queue（若需要）
# 5. 改 mac-station 测试或调用方的 import 路径（grep 后定向修改）

git commit -m "chore(edge): merge mac-mini into mac-station (R2)

mac-mini was an early fragment with offline_buffer.py duplicating
mac-station/src/offline_buffer.py. print_queue.py is moved into
mac-station; offline_buffer.py is dropped.

Physical hardware is the same Mac mini — naming was confusing."
```

**验收**：
- `python -m pytest edge/mac-station/tests/` 全绿
- `grep -r "edge.mac_mini\|edge/mac-mini" .` 0 命中

**回滚**：`git revert <sha>` 即可恢复（git mv 是 add+rm，revert 一并复原）

---

## R3 — `apps/android-shell` × `apps/android-pos` ⏸ **SUSPENDED**（2026-05-06）

**状态变更**：原 plan 假设是简单合并（情况 A 直接删 / 情况 B cherry-pick 后删）。深入勘察后发现这不是物理重复，是**两套架构方向之争**，且 pos 当前实装存在双重宪法违反。R3 不能在 sprint-0-dedup 范围内闭环，已升级为独立的 V4 架构对齐 sprint。

**升级理由**

勘察 `apps/android-pos/src/main/kotlin/com/tunxiang/pos/bridge/TXBridge.kt:119-122` + `data/remote/ApiClient.kt` + `sync/SyncManager.kt` 三处证据：

```kotlin
// pos/TXBridge.kt:119-122 — V4 团队的真实意图
fun getMacMiniUrl(): String {
    // No longer needed in V4 (Room DB replaces Mac mini for POS)
    return ""
}
```

- pos 5 屏 Compose（OrderScreen / SettleScreen / DailyClose / Shift / TableMap）共 2186 行业务代码 → **违反 CLAUDE.md §十三 第 1 条铁律（"禁止 Kotlin 写业务逻辑"）**
- pos 用 Room DB 作本地真相源 + Retrofit 直连云端，绕开 mac-station → **违反 CLAUDE.md §八 路线 C（"Mac mini = 本地 PG 真相源"）**
- shell 路线相反：WebView only + 真实 `getMacMiniUrl` → 符合路线 C，但收银 hot path 在商米 T2 物理性能边界以内不够稳

**第一性原理判断**：收银 hot path 必须 Native（Compose），cool path 必须 WebView（React），Mac mini PG 是真相源。当前 shell 和 pos **都不完整**——shell 缺 Native hot path，pos 缺 Mac mini 真相源。直接合并/删除任何一方都把宪法债买进 V4。

按创始人原则"MVP 前 + 稳定 + 零技术债"，R3 升级为：

→ 详见 [`.omc/plans/v4-architecture-alignment.md`](v4-architecture-alignment.md)（7 天独立 sprint）

**本计划下 R3 的动作**：
- ❌ 不删 `apps/android-shell`
- ❌ 不改 `apps/android-pos`
- ✅ 升级到 V4 架构对齐 sprint，作为独立工作单元
- ✅ V4 sprint 完成后回头删 shell（V4 sprint 的 D7 即此动作）

**回滚**：本 commit 不动代码，无需回滚。

---

## R1 — 删除 `services/tunxiang-api/` 早期 MVP 单体

**已查证依赖**
- 7 个 `tx-agent` skill 引用 `services.tunxiang_api.src.shared.core.model_router`：
  - `table_dispatch.py` / `enterprise_activation.py` / `cost_diagnosis.py` / `review_summary.py` / `growth_attribution.py` / `smart_customer_service.py` + 1
- `tx-finance/src/tests/test_d4c_budget_forecast.py:571` 读取 `services/tunxiang-api/src/shared/core/model_router.py` 源文件
- 4 个测试（tx-org/tx-menu/tx-member/tx-finance）字面字符串 `"tunxiang-api"` 出现——需逐个查上下文（疑似 service-name 常量列表）
- `gateway/src/services/oauth2_service.py:480` 默认 salt = `"tunxiang-api-salt-v1"`（**不能改**，改会让现有 token 失效；保留字面字符串无影响）
- `gateway/src/proxy.py:72` 注释提及，无功能依赖

**关键事实**：
- `shared/ai_providers/router.py` (31KB) 是新一代 `MultiProviderRouter`，**自带 `ModelRouterCompat` 向后兼容层**
- `tunxiang-api/.../model_router.py` (7KB) 是早期 stub
- 迁移路径已铺好

**执行步骤（顺序敏感）**

### Step 1 — 验证 ModelRouterCompat 兼容性
```bash
# 读 shared/ai_providers/router.py 末尾的 ModelRouterCompat
grep -n "class ModelRouterCompat\|model_router" shared/ai_providers/router.py

# 看 7 个 skill 用 model_router 的哪些方法
grep -n "model_router\." services/tx-agent/src/agents/skills/{table_dispatch,enterprise_activation,cost_diagnosis,review_summary,growth_attribution,smart_customer_service}.py
```
若 `ModelRouterCompat` 提供的方法签名与 skill 调用一致 → 进入 Step 2；否则在 `shared/ai_providers/router.py` 补 shim 后再走。

### Step 2 — 改写 7 个 skill 的 import
```bash
# 全局替换（先 dry-run）
grep -rln "from services.tunxiang_api.src.shared.core.model_router" services/tx-agent/

# 改成
# from shared.ai_providers.router import model_router  （或 ModelRouterCompat 实例）
```
逐文件 Edit，**不要 sed -i 全局替换**（5 个 skill 用的是 `try/except` 包裹的 lazy import，sed 容易错）。

### Step 3 — 改写 tx-finance 测试
`services/tx-finance/src/tests/test_d4c_budget_forecast.py:571` 改读 `shared/ai_providers/router.py` 路径，或直接改成 import 测试。

### Step 4 — 排查字面字符串 `"tunxiang-api"`
```bash
grep -rn '"tunxiang-api"' services/ --include="*.py"
```
对每条命中：
- 若是 service-name 常量列表（如检查"屯象有哪些 service"的测试），从列表里**移除该项**
- 若是 salt/secret 默认值（如 oauth2_service 的 salt）**保留字面字符串**（改会让线上失效）

### Step 5 — 跑测试验证 import 全部迁移成功
```bash
pytest services/tx-agent/src/tests/ services/tx-finance/src/tests/ -x
```

### Step 6 — 删除 service
```bash
git rm -r services/tunxiang-api
```

### Step 7 — 更新 `gateway/src/proxy.py:72` 注释（顺手）
把"端口：8013 容器内（Docker DNS 隔离，与 tunxiang-api/tx-predict 同号不冲突）"中的 `tunxiang-api` 改掉或注释清理。

### Step 8 — 提交
```bash
git commit -m "chore(services): remove tunxiang-api MVP monolith (R1)

tunxiang-api was the single-process monolith (gateway/trade/brain/ops
modules) from the solo-founder era. All capabilities have been split
into independent microservices long ago.

Migrations:
- 7 tx-agent skills now import shared.ai_providers.router
  (MultiProviderRouter with ModelRouterCompat layer)
- tx-finance test_d4c_budget_forecast reads new router path
- oauth2_service salt string left untouched to avoid token invalidation

Closes Sprint-0 Dedup R1."
```

**验收**：
- 全 service `pytest -x` 绿
- `docker compose up` 所有 service 起来
- gateway 健康检查通过（注意 proxy.py 的 tunxiang-api 路由若有，要先去除）

**回滚**：`git revert <sha>` —— 因为只是改 import 路径 + 删 service，revert 安全。

---

## R6 — 重命名外卖适配器（澄清双视角，不删任何代码）

**双视角已确认**：
- 单文件 `*_adapter.py` = 配送发单（DeliveryPlatformAdapter）
- 目录 `eleme/` `douyin/` `pinzhi/` = 开放平台 API（订单/商品/webhook 完整套）

**执行**

```bash
# 1. 单文件加 _delivery 后缀（明确"配送视角"）
git mv shared/adapters/meituan_adapter.py shared/adapters/meituan_delivery_adapter.py
git mv shared/adapters/eleme_adapter.py   shared/adapters/eleme_delivery_adapter.py
git mv shared/adapters/douyin_adapter.py  shared/adapters/douyin_delivery_adapter.py
git mv shared/adapters/wechat_delivery_adapter.py shared/adapters/wechat_delivery_adapter.py  # 已带 _delivery 不动

# 2. 目录加 _open_platform 后缀（明确"接平台 API 视角"）
git mv shared/adapters/eleme   shared/adapters/eleme_open_platform
git mv shared/adapters/douyin  shared/adapters/douyin_open_platform
git mv shared/adapters/pinzhi  shared/adapters/pinzhi_pos          # pinzhi 是 POS 不是外卖

# 3. 全局改 import（注意：dry-run 先 grep，确认范围）
grep -rln "from shared.adapters.meituan_adapter\|from shared.adapters.eleme_adapter\|from shared.adapters.douyin_adapter\|from shared.adapters.eleme\b\|from shared.adapters.douyin\b\|from shared.adapters.pinzhi\b" services/ shared/ apps/

# 4. 在 shared/adapters/INTEGRATION_GUIDE.md 加一段说明双视角的命名约定
```

**提交**
```bash
git commit -m "chore(adapters): rename meituan/eleme/douyin to clarify dual viewpoints (R6)

- *_delivery_adapter.py = our outbound delivery dispatch (mock today)
- *_open_platform/      = inbound order/product/webhook API integration

Names were ambiguous and looked like duplicates. Code is unchanged."
```

**验收**：CI 全绿，所有 import 已更新。

---

## R7 — 冻结 `apps/miniapp-customer/`（v1）

**执行**

在 `apps/miniapp-customer/README.md` 顶部加：
```markdown
> ⚠️ **DEPRECATED**（since 2026-05-06）
>
> This is the v1 customer mini-program. Active development has moved to
> `apps/miniapp-customer-v2` (Taro framework).
>
> **Maintenance policy**:
> - Security patches: ✅ accepted
> - Bug fixes for active customers: ✅ accepted
> - New features: ❌ rejected — implement in v2 instead
>
> EOL date: TBD（after all v1 tenants migrated to v2）
```

在 `apps/miniapp-customer/package.json` `description` 字段加 `[DEPRECATED, use v2]`。

**提交**
```bash
git commit -m "chore(miniapp): freeze v1 customer miniapp, redirect to v2 (R7)

v1 stays for security/bugfix only. All new work lands in v2."
```

**验收**：README 顶部 deprecated banner 可见。

---

## R4 — `tx-brain` + `tx-intel` + `tx-predict` → `tx-agent/sub/` 子模块（W12 后做，本计划仅留 marker）

**为何延后到 W12**：
- 三服务合计 130 py / 25 routes，合并涉及大量 router prefix / DI / DB session 改动
- W8 demo 前 Tier 1 测试不能引入回归
- Hassabis 课程学习路径要求 Agent 单进程闭环——但这事 W9-W12 才需要

**本计划只做的事**
1. 在每个 service 的 README 顶部加：
   ```
   > 🟡 **POST-W12 MIGRATION**: This service will be merged into tx-agent/sub/{name}/
   > as part of Sprint 4 (W12+) consolidation. No new top-level routes here —
   > add them in tx-agent and import; OR plan to migrate cleanly post-W12.
   ```
2. 添加 `.omc/plans/post-w12-tx-agent-merger.md` 占位文档（待规划）
3. **不动代码**

**提交**
```bash
git commit -m "docs(intelligence): mark tx-brain/tx-intel/tx-predict for post-W12 merge (R4)

Physical merge into tx-agent/sub/ deferred to Sprint 4. Only annotation
added — no code change. See .omc/plans/post-w12-tx-agent-merger.md."
```

---

## 执行顺序（更新于 2026-05-06）

```
R5  ❌ 取消（false alarm — meituan/ 不是空目录，是 meituan-saas/）
R2  ✅ 完成（commit 586aabe3 已落 chore/sprint-0-dedup）
R3  ⏸ SUSPENDED → 升级为 v4-architecture-alignment 独立 sprint（7 天）
R1  → 半天，tunxiang-api 删除（最高风险，留时间跑全测）
R6  → 1 小时，重命名外卖
R7  → 10 分钟，miniapp v1 冻结 banner
R4  → 5 分钟，加 marker docs
```

每条 R 一次 commit，PR 名 `chore(dedup): sprint-0 R1-R7`。**不要合成一个大 commit**。

R3 升级后的处理：sprint-0-dedup PR 在 R1/R6/R7/R4 完成后即可 ship，不等 R3。
V4 架构对齐 sprint 单独走 PR，shell 删除是该 sprint 的最后一步（D7）。

---

## 全局回滚

若中途发现严重回归：
```bash
git checkout fix/pg1-1-alembic-merge-v397    # 回到起点分支
git branch -D chore/sprint-0-dedup           # 丢弃工作分支
```

每条 commit 都是原子的，也可单独 `git revert <sha>` 局部回滚。

---

## 验收标准（全部满足才能合回主分支）

- [ ] `pytest services/ -x` 全绿
- [ ] `docker compose up -d` 所有 service 起来 + 健康检查通过
- [ ] `cd apps/web-pos && pnpm build` 成功（同样在 web-admin / web-kds / web-crew / miniapp-customer-v2）
- [ ] `cd apps/android-pos && ./gradlew assembleDebug` 成功
- [ ] `grep -r "tunxiang_api\|tunxiang-api" services/ apps/ shared/ edge/ --include="*.py" --include="*.ts" --include="*.tsx"` 仅剩 oauth2 salt 字符串（无 import）
- [ ] `grep -r "edge.mac_mini\|edge/mac-mini" .` 0 命中
- [ ] `find shared/adapters -type d -empty` 0 命中
- [ ] alembic 链未受影响（不应该被影响，但跑一遍 `alembic heads` 确认还是 35 head 等待 PI.2 收敛）

---

## 后续：Sprint 0 第二批（不在本计划，但应紧接着做）

- 35 alembic dangling head 收敛（PI.2）
- legal_entity 内存字典落库（致命差距 1 第一刀）
- omni_channel webhook secret 强校验（删除 `return True` fallback）

这三项各自独立 plan，不混入本去重计划。
