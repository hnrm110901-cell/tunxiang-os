# 审计修复 6 PR Reviewer Checklist — 2026-05

每个 PR 不要简单 ✅，按本文档逐项核查。Tier 1 路径任一项 fail 必须 request changes。

---

## 通用准则（所有 6 PR 必看）

- [ ] 修改是否引入新 `except Exception`（CLAUDE.md §10 / §13 第 4 条禁止）—— 用 `git diff main...HEAD | grep "except Exception"` 验证
- [ ] 金额字段是否用 `_fen` 整数 —— grep 新代码 `Numeric|Decimal|float.*amount|float.*price`
- [ ] 是否动了 `shared/ontology/`（CLAUDE.md §13 第 6 条冻结）
- [ ] 是否改了已应用的 migration v001-v402（禁止）
- [ ] 测试是否 Tier 1 命名（`*tier1*.py`）+ 真跑过（CI 绿）
- [ ] commit message 是否符合 `[type]([service]): ... [Tier级别]` 规范（CLAUDE.md §21）

---

## PR #195 — 23 P0 批量修复（基础 PR，必须先过）

**reviewer 至少 2 人 + 必须含 security-team**。

### F1 cashier 行锁（commit `76528fed`）
- [ ] `cashier_engine.py:_get_order` 加了 `.with_for_update()` —— 4 字符
- [ ] **关键**：所有 `_get_order` 调用方（`grep "_get_order"` 出 ~10 处）是否都在事务内？非事务调用会立即释放锁形同虚设
- [ ] 是否有 `read_committed` 之外的隔离级别假设？

### F2 OrderService 双 init（commit `a7c09646`）
- [ ] 删除了第 39-44 行废弃 `__init__`
- [ ] 保留的 `__init__` 含 `self._tenant_id_str = tenant_id`
- [ ] 删除了 L65-73 zombie create_order
- [ ] **关键**：所有 `OrderService(...)` 调用方（不传 `offline_sync_service` 的）行为不变？

### F3 sync_ingest 列名注入（commit `335bd904`）
- [ ] `_SAFE_COL_NAME_RE = r"^[a-z_][a-z0-9_]{0,62}$"` —— 不允许大写
- [ ] **关键**：业务表 schema 中是否有大写列名？看 `shared/ontology/src/entities.py` 和最新 migrations
- [ ] `_validate_columns` 在 `_upsert_record` 拼 SQL 前调用

### S-04 微信宴会回调验签（commit `9d92800f`）
- [ ] endpoint signature 改 `(request: Request, ...)` 而非 `(body: WechatCallbackReq, ...)`
- [ ] 用 `WechatPayService.verify_callback(headers, body_bytes)` 而非自实现
- [ ] **关键**：`shared/integrations/wechat_pay.py.verify_callback` 是否真做 V3 RSA-SHA256 + AES-256-GCM？翻文件看
- [ ] 失败回 400（让微信重试）；返回 `{"code":"SUCCESS",...}` 给微信
- [ ] **是否破坏内部健康检查路径？**有 admin tool 之前用旧 JSON 格式 POST 这个端点吗？grep `/banquet/deposit/callback`

### S-02 gateway proxy strip（commit `3b52b520`）
- [ ] strip 只剥 `X-Tenant-ID / X-Internal-*`，**保留** `Authorization`（下游 ApiKey 中间件需要）
- [ ] 从 `request.state.tenant_id` 重注入受信值
- [ ] mint internal JWT 调用 `mint_internal_jwt(tenant_id, user_id, role)` 不携带敏感数据
- [ ] **关键**：exempt 路径（健康检查 / wecom callback）走 P0-3 修复的新分支 `is_authenticated=False` 透传，不破坏现有流量

### Prometheus P99 + 支付 SLO（commit `03686211`）
- [ ] 阈值 `> 0.2` 而非 `> 2`
- [ ] 4 条 payment SLO 规则（PaymentSuccessRateLow / PaymentSagaCompensationSpike / PaymentTrafficStalled / PaymentChannelHighErrorRate）
- [ ] **关键**：metric 名（`payment_saga_total{result}` 等）与 PR #200 实际暴露的一致

### Tier1+RLS gate（commit `25d7694a`）
- [ ] `tier1-and-rls-gate` job 用 `find services edge tests -name 'test_*tier1*.py'` 发现测试
- [ ] **关键**：CI runner 上能跑通这个 job 吗？测试这一项最稳妥的办法是直接跑 `gh pr view 195 --checks`
- [ ] k6 P99 检查含 placeholder marker 拒
- [ ] RLS FORCE 静态检查仅 warn 不阻塞（历史债 ~176 张表，需 PR #199 配套）

### rls-gate FORCE 检查（commit `607a26a6`）
- [ ] 新 migration 中 `ENABLE ROW LEVEL SECURITY` 必须配对 `FORCE ROW LEVEL SECURITY`
- [ ] EXEMPT 列表是否需要扩充？（用户的 v399/v400/v401/v402 是否需要更新到 EXEMPT？）

### RLS rollout 文档（commit `21edb1f4`）
- [ ] 5 阶段顺序合理
- [ ] 5 处 BYPASSRLS 调用方迁移注意事项准确
- [ ] 验收标准 6 条可量化

---

## PR #196 — edge sync HMAC 客户端

**reviewer 至少含 edge-team**

### hmac_signer.py
- [ ] HMAC 公式与服务端 PR #195 verify_edge_sync_auth (sync_ingest_router.py L126-127) **完全对称**：
  - 服务端：`HMAC_SHA256(secret, f"{store_id}.{tenant_id}.{ts}.{nonce}")`
  - 客户端：必须同样
- [ ] **关键 send-time freshness**：`sign_headers()` 每次调用都生成新 `ts = int(time.time())` 和 `nonce = uuid.uuid4().hex`，**不是** sign 时缓存
- [ ] `from_env(tenant_id)` 在缺 `EDGE_SYNC_HMAC_SECRET` 或 `EDGE_STORE_ID` 时返回 `None`（dev 兼容）
- [ ] 测试 `test_signature_matches_server_side_formula` 用同公式独立计算 + `hmac.compare_digest`

### 5 处 HTTP 调用接通
- [ ] sync_engine.py L320 / L444
- [ ] change_sync_engine.py L787 / L899
- [ ] offline_sync_service.py L390
- [ ] 全部用 `build_sync_headers(tenant_id)` 替换 `{"X-Tenant-ID": tid}`

### 与 PR #195 配对
- [ ] **必须配对部署**。Cutover 顺序明确：先服务端代码 + secret → 客户端升级 → 灰度 → required=true
- [ ] PR description 列了 4 步 cutover

---

## PR #199 — v500 RLS FORCE migration（DO NOT MERGE）

**reviewer 至少含 dba + security-team。⚠️ 标 `do-not-merge` label**

- [ ] PR title 含 `(DO NOT MERGE - staging dry-run pending)`
- [ ] PR body 顶部一句话警告
- [ ] migration 顶部 docstring 含明示警告（"DO NOT RUN ON STAGING/PRODUCTION WITHOUT DRY-RUN"）
- [ ] EXEMPT 列表 30 张表 + 4 个 partition 前缀 + mv_ 前缀 与 `.github/workflows/rls-gate.yml` **逐字对比**（test_exempt_lists_match 自动验证）
- [ ] upgrade SQL 用 `format('ALTER TABLE %I FORCE ...', t.tablename)` —— `%I` 是 PG identifier 转义（防注入）
- [ ] downgrade docstring 警告"批量降级风险"
- [ ] **关键**：down_revision = "v399"。如果 main 上当前 head 是 v402（用户的 WITH CHECK 系列已 merge），merge 时需要 rebase down_revision
- [ ] 5 处合法 BYPASSRLS 调用方都在 docstring 列出

---

## PR #200 — tx-pay 渠道指标

**reviewer 至少含 ops-team + tx-pay owner**

### metrics.py
- [ ] `payment_channel_requests_total{channel, status}` —— **label 顺序与 PR #195 alerts.yml 的查询一致**
- [ ] `channel` 取值：wechat / alipay / lakala / shouqianba / stored_value / cash（低基数）
- [ ] `status` 取值：2xx / 4xx / 5xx / timeout / connect_error（低基数）

### 6 个 channel 文件接通
- [ ] 每个 channel 的 `create_payment` / `query` / `refund` / `verify_callback` 在响应处理后都 `inc()`
- [ ] **关键**：异常路径（如 `httpx.TimeoutException`）也要 inc 对应 status，不能漏

### 与 PR #195 alerts 对齐
- [ ] 部署后 `curl /metrics | grep payment_channel_requests_total` 应有数据
- [ ] PaymentChannelHighErrorRate 告警表达式中 `{status="5xx"}` 的 label 名 = metrics.py inc 时用的 label

---

## PR #201 — Redis nonce store

**reviewer 至少含 security-team + sre**

### edge_sync_nonce_store.py
- [ ] `EdgeSyncNonceStore` ABC：异步 `seen_and_mark` + `close`
- [ ] `RedisNonceStore` 用 `redis.asyncio` 不阻塞 event loop
- [ ] `redis.asyncio` set 调用必须 **`nx=True` + `ex=ttl_seconds`** 原子操作（不是 SET 后 EXPIRE 两步）
- [ ] **关键 fail-closed**：Redis 故障 → raise `RuntimeError` → router 回 503，**不能** silent fall through 到 in-process

### get_nonce_store() 工厂
- [ ] 生产 + `EDGE_SYNC_HMAC_REQUIRED=true` + 无 `EDGE_SYNC_NONCE_REDIS_URL` → **启动期 raise**
- [ ] 显式 `EDGE_SYNC_NONCE_ALLOW_INPROCESS=true` 才允许生产降级
- [ ] singleton 缓存 + `reset_nonce_store_for_testing()`

### sync_ingest_router 改造
- [ ] 删除 `_EDGE_SYNC_RECENT_NONCES` 进程内 dict
- [ ] **校验顺序**：先 HMAC 校验（失败请求不污染 nonce store）→ 通过后才 `seen_and_mark`
- [ ] 多副本演示测试 `test_two_inprocess_stores_dont_share`：明示问题根源

### 部署前置
- [ ] K8s 已有 Redis service？否则 PR description 应列出"先建 Redis"前置
- [ ] PR description 列灰度策略

---

## PR #202 — InternalJwtMiddleware

**reviewer 至少含 security-team + tx-trade owner**

### internal_jwt_middleware.py
- [ ] 平台端点豁免：`/health` `/healthz` `/metrics` `/docs` `/openapi.json` `/redoc` `/favicon.ico`
- [ ] dev/staging 无 `TX_INTERNAL_JWT_SECRET` → skip middleware（**与 PR #195 mint 路径行为对称**：mint 也返回 None 不附 header）
- [ ] 生产 + 无 secret → 启动期由 `internal_jwt._get_secret()` raise（middleware 中是兜底）
- [ ] 失败回 JSONResponse 不让 FastAPI 默认 HTML 页泄漏堆栈
- [ ] **关键**：注入 `request.state.{tenant_id, user_id, role, auth_method='internal_jwt', internal_jwt_claims}`

### tx-trade 挂载
- [ ] `services/tx-trade/src/main.py` 挂载顺序：FastAPI → Instrumentator → InternalJwtMiddleware → CORSMiddleware → 路由
- [ ] **关键**：CORS preflight 不能被 JWT 中间件拦截 —— 验证 OPTIONS 请求 200

### 与 PR #195 mint 对齐
- [ ] gateway mint 的 claims（`tenant_id, user_id, role, iss, aud, exp, iat`）与 middleware verify 期待的字段对齐
- [ ] iss=tx-gateway / aud=tx-internal 双方一致

### rollout 文档
- [ ] 24 服务挂载 checklist 完整
- [ ] cutover 5 阶段顺序合理
- [ ] 已知 3 个遗留风险（HS256 爆炸半径 / 60s 过期窗口 / 环境变量切换顺序）列出

---

## 跨 PR 一致性验证（merge 顺序敏感）

按建议顺序 **#195 → #196 → (#200 ‖ #201 ‖ #202) → #199** review：

### #195 vs #201
- [ ] PR #201 改 sync_ingest_router.py 的代码区域不与 PR #195 的相同区域冲突 —— `gh pr diff 195 -- services/tx-trade/src/routers/sync_ingest_router.py` 和 `gh pr diff 201` 对比
- [ ] PR #201 的 nonce store 接口与 PR #195 的 `verify_edge_sync_auth` 调用契约一致

### #195 vs #202
- [ ] tx-trade main.py 修改区域：PR #195 加 Instrumentator + CORS，PR #202 加 InternalJwtMiddleware —— 是否在同一段，merge 顺序有讲究

### #195 + #196
- [ ] HMAC 公式：客户端（#196 hmac_signer）与服务端（#195 verify_edge_sync_auth）逐字符对比

### #195 + #200
- [ ] Counter label 名一致：alerts.yml 查询的 `payment_channel_requests_total{channel, status}` 与 metrics.py 暴露的 label 完全对齐

### #195 + #199
- [ ] EXEMPT 列表三处对齐：`.github/workflows/rls-gate.yml` ↔ `tests/tier1/test_rls_force_migration_tier1.py` ↔ migration `_EXEMPT_TABLES`
- [ ] **关键**：PR #199 的 down_revision = v399。如果 PR #192/#193/#194 用户 WITH CHECK 系列先 merge 把 head 推到 v402+，PR #199 必须 rebase down_revision 到 v402

---

## Reviewer 自检：Review 后必须确认

- [ ] 我读了 PR description 的全部 commit 列表，不是只看 diff
- [ ] 我至少跑过一次 PR 的 CI（gh pr checks <num>）确认绿
- [ ] 我针对 Tier 1 路径做了**业务场景思考**（不是只看代码对不对）：
  - 200 桌并发会出什么问题
  - 4h 离线会丢什么数据
  - 跨租户能否绕过
- [ ] 我把 PR description 列的"已知 follow-up"看了，理解本 PR 的边界
- [ ] 我不是同一个人 merge 自己 review 的 PR（CLAUDE.md §19 独立验证规则）

---

## 给 release manager 的"必须做完才 cutover"清单

- [ ] 6 PR 全部 review 通过 + CI 绿 + merge 到 main
- [ ] staging 部署所有 PR 后 24h 无 5xx 增长
- [ ] `docs/runbooks/audit-2026-05-cutover.md` 阶段 E 5 项端到端验收全过
- [ ] 真 k6 跑测结果 commit 进 main（无 placeholder marker）
- [ ] PR #195 OPS-007 提到的 `payment-provider-failure.md` runbook 写好（独立 PR）
- [ ] 品智 17 个 token 已轮换 + git history 已清理（S-01）
- [ ] PR #199 暂留 do-not-merge 状态，不阻塞首客上线（RLS FORCE 是 W5+ 工作）
