# 审计修复 cutover playbook — 2026-05

**对应**：23 P0 修复 6 个 PR（#195 / #196 / #199 / #200 / #201 / #202）
**时间窗口**：建议 W1 review/merge → W2 staging 端到端 → W3 灰度门店 → W4 全量 + RLS FORCE
**前置条件**：6 PR 已合 main，staging k8s 环境就绪，K8s Secret 注入 + Redis 已部署

---

## 0. 关系图

```
PR #195 (基础)
   │  服务端 verify_edge_sync_auth + gateway strip + Prometheus 规则 + tier1 gate
   │
   ├──→ #196 (edge HMAC 客户端)            ← 与 #195 配对，避免 cutover 打死客户端
   ├──→ #200 (tx-pay 渠道指标)             ← 启用 #195 的 PaymentChannelHighErrorRate 告警
   ├──→ #201 (Redis nonce store)           ← 替换 #195 的进程内 dict，多副本必修
   ├──→ #202 (InternalJwtMiddleware)        ← 闭合 #195 mint JWT 的下游校验
   │
   └──→ #199 (RLS FORCE migration)          ← DO NOT MERGE 直到 staging dry-run + 阶段 4 完成
```

**merge 顺序**：#195 → #196 → (#200 ‖ #201 ‖ #202 并行) → #199 (4-6 周后)

---

## 1. 部署阶段一览

| 阶段 | 时间 | PR | 关键 env | 验收 |
|---|---|---|---|---|
| **A. staging baseline** | D1 | merge #195 + #196 + #200 + #202 | 不配 secret | 服务正常启动；老行为兼容 |
| **B. staging Redis** | D2 | merge #201 + 部署 Redis | `EDGE_SYNC_NONCE_REDIS_URL` | nonce store 切 Redis；多副本测试通过 |
| **C. staging 配 secret（不开 required）** | D3 | — | `EDGE_SYNC_HMAC_SECRET` + `EDGE_STORE_ID` + `TX_INTERNAL_JWT_SECRET` | 老 client 仍可工作；signed client 也可工作 |
| **D. staging cutover required** | D4-7 | — | `EDGE_SYNC_HMAC_REQUIRED=true` | 所有 client 走签名路径 |
| **E. staging k6 + e2e** | W2 | — | — | P99 < 200ms；4h 离线 0 丢失 |
| **F. 灰度门店** | W3 | — | 同 staging | 真实订单 24h 无异常 |
| **G. 全量** | W4 | — | 同 | 24h 持续 |
| **H. RLS FORCE** | W5+ | merge #199 | — | 详见 docs/security/rls-force-rollout.md |

---

## 2. 阶段 A — staging baseline（D1）

### 部署

```bash
# 在 staging server
cd /opt/tunxiang-os
git pull origin main  # 应包含 #195/#196/#200/#202

# 重启 tx-trade / tx-pay / gateway / sync-engine
docker compose -f infra/compose/base.yml -f infra/compose/envs/staging.yml --env-file .env.staging up -d --force-recreate gateway tx-trade tx-pay
```

### 验收

```bash
# 1. 服务健康
curl -s "$STAGING_URL/health"
# 期望: {"ok": true}

# 2. tx-trade /metrics 应包含 payment_saga 指标（PR #195 da694931 的 Counter）
curl -s "$STAGING_URL/metrics" | grep payment_saga_total

# 3. tx-pay /metrics 应包含 payment_channel 指标（PR #200）
curl -s "$STAGING_URL/api/v1/pay/metrics" | grep payment_channel_requests_total

# 4. tx-trade 日志应有 InternalJwtMiddleware skip warn（dev 模式）
docker compose logs tx-trade | grep internal_jwt_middleware_skip_no_secret
# 期望: 出现（说明 middleware 已挂载但 skip 正常）

# 5. edge sync 仍走兼容路径（无 EDGE_SYNC_HMAC_SECRET）
docker compose logs tx-trade | grep edge_sync_auth_skipped_dev_mode
# 期望: 出现

# 6. 跑端到端冒烟：开台→点单→结算
./scripts/staging-smoke-test.sh
```

### 回滚

```bash
git revert <merge-sha-of-#195> && git push origin main
docker compose pull && docker compose up -d --force-recreate
```

**回滚阈值**：
- 任意服务无法启动
- /health 5xx 持续 5 分钟
- payment_saga_total{result="failed"} 增长率 > 1%

---

## 3. 阶段 B — staging Redis（D2）

### 部署

```bash
# 0. 部署 Redis（如还没有）— 推荐 K8s Redis StatefulSet
kubectl apply -f infra/helm/redis/staging.yaml
# 或 docker compose:
docker run -d --name tunxiang-redis-staging -p 6379:6379 redis:7-alpine

# 1. merge PR #201
git pull origin main

# 2. 配 EDGE_SYNC_NONCE_REDIS_URL 到 .env.staging
echo "EDGE_SYNC_NONCE_REDIS_URL=redis://tunxiang-redis-staging:6379/0" >> .env.staging
# 或用 K8s Secret:
kubectl create secret generic tx-trade-edge-secrets \
  --from-literal=EDGE_SYNC_NONCE_REDIS_URL=redis://... -n staging

# 3. 重启 tx-trade
docker compose -f infra/compose/base.yml -f infra/compose/envs/staging.yml --env-file .env.staging up -d --force-recreate tx-trade
```

### 验收

```bash
# 1. tx-trade 启动日志：edge_sync_nonce_store_redis url=...
docker compose logs tx-trade | grep edge_sync_nonce_store_redis

# 2. Redis 实际看到 SETNX 操作（部署 client 后）
redis-cli -h tunxiang-redis-staging
> KEYS edge_sync_nonce:*
> TTL <一个 key>
# 期望: 有 key，TTL > 0 且 < 300

# 3. 多副本测试：扩 tx-trade 到 2 副本
docker compose -f ... up -d --scale tx-trade=2

# 用 hey/siege 同 nonce 打两次（两次必有一次到不同 pod）
hey -n 100 -c 10 -H "X-Edge-Store-Id: t1" \
    -H "X-Edge-Sync-Nonce: same-nonce-test" \
    -H "X-Edge-Sync-Ts: $(date +%s)" \
    -H "X-Edge-Store-Token: <fake>" \
    "$STAGING_URL/api/v1/sync/ingest"
# 期望: 第 2..n 个请求 401 nonce_replay
```

### 监控

新指标：
```promql
# Redis 故障率（如有）
rate(edge_sync_nonce_check_total{result="store_error"}[5m])

# nonce 命中率（重放检测频率）
rate(edge_sync_nonce_check_total{result="hit"}[5m])
```

### 回滚

如 Redis 故障：
1. 设 `EDGE_SYNC_NONCE_ALLOW_INPROCESS=true` 临时降级单副本
2. 或 revert PR #201

---

## 4. 阶段 C — staging 配 secret（不开 required）（D3）

**关键：先配 secret 不开 required，让老 client 兼容期切换**

### 部署

```bash
# K8s Secret 注入
kubectl create secret generic tx-internal-jwt -n staging \
  --from-literal=TX_INTERNAL_JWT_SECRET=$(openssl rand -hex 32)

kubectl create secret generic edge-sync-hmac -n staging \
  --from-literal=EDGE_SYNC_HMAC_SECRET=$(openssl rand -hex 32)

# 每台 Mac mini 配 EDGE_STORE_ID（按门店 UUID）
ssh mac-mini-01 "echo 'EDGE_STORE_ID=550e8400-e29b-41d4-a716-446655440000' >> /etc/tunxiang/edge.env"

# gateway / tx-trade / tx-pay 重启读 secret
docker compose up -d --force-recreate gateway tx-trade tx-pay

# Mac mini sync-engine 重启
ssh mac-mini-01 "launchctl kickstart -k system/com.tunxiang.sync-engine"
```

### 验收

```bash
# 1. gateway log: 开始 mint JWT
docker compose logs gateway | grep "mint_internal_jwt"
# 期望: 在已认证请求上能看到

# 2. tx-trade log: 开始 verify JWT
docker compose logs tx-trade | grep -E "internal_jwt_middleware_(verify_failed|claims_set)"
# 期望: 收到 gateway 转发的 X-Internal-JWT 后通过校验

# 3. edge log: 开始发 X-Edge-* headers
ssh mac-mini-01 "tail /var/log/tunxiang-sync.log | grep -E 'X-Edge-Store-Token'"

# 4. tx-trade log: edge sync 收到完整 headers + 校验通过
docker compose logs tx-trade | grep edge_sync_auth_ok

# 5. **关键**：未升级的 client 仍能工作（兼容性验证）
# 模拟一个老 client 只发 X-Tenant-ID：
curl -X POST -H "X-Tenant-ID: t1" "$STAGING_URL/api/v1/sync/ingest" -d '...'
# 期望: 200（_edge_sync_required() 默认 false，回退到 X-Tenant-ID 兼容）
```

### 回滚

如 gateway/tx-trade 启动失败：
```bash
kubectl delete secret tx-internal-jwt -n staging
docker compose up -d --force-recreate
# middleware 跑 _has_secret() = False，skip 校验，行为回退
```

---

## 5. 阶段 D — staging cutover required（D4-7）

### 部署

```bash
# 设强制开关
echo "EDGE_SYNC_HMAC_REQUIRED=true" >> .env.staging

docker compose up -d --force-recreate tx-trade
```

### 验收

```bash
# 1. 老 client（不发 X-Edge-*）必须 401
curl -X POST -H "X-Tenant-ID: t1" "$STAGING_URL/api/v1/sync/ingest"
# 期望: 401 "edge sync auth headers missing"

# 2. 升级后的 client（发完整 headers）必须 200
curl -X POST \
  -H "X-Tenant-ID: t1" \
  -H "X-Edge-Store-Id: 550e8400-..." \
  -H "X-Edge-Sync-Ts: $(date +%s)" \
  -H "X-Edge-Sync-Nonce: $(openssl rand -hex 16)" \
  -H "X-Edge-Store-Token: <计算的 HMAC>" \
  "$STAGING_URL/api/v1/sync/ingest"
# 期望: 200

# 3. Mac mini 24h 持续观察日志：无 401 / no 4xx / 同步成功率 100%
```

### 监控告警（PR #195 加的规则现在生效）

```promql
# P99 延迟（PR #195 OPS-003 修复）
histogram_quantile(0.99, sum by (job, le) (rate(http_request_duration_seconds_bucket[5m]))) > 0.2
# 触发: HighResponseTimeHistogram

# 支付成功率（PR #195 OPS-002 + #200 metric 暴露）
sum(rate(payment_saga_total{result="success"}[10m])) / sum(rate(payment_saga_total[10m])) < 0.999
# 触发: PaymentSuccessRateLow

# 渠道 5xx（PR #200 启用）
sum by (channel) (rate(payment_channel_requests_total{status="5xx"}[5m]))
  / sum by (channel) (rate(payment_channel_requests_total[5m])) > 0.01
# 触发: PaymentChannelHighErrorRate
```

### 回滚

`EDGE_SYNC_HMAC_REQUIRED=false` → 重启 tx-trade，回到阶段 C 兼容模式。

---

## 6. 阶段 E — staging 端到端验收（W2）

**CLAUDE.md §22 五个真实交付数字必须实测，不能停在"代码写完"。**

### E1. P99 < 200ms

```bash
# 真 k6 跑测（替换 PR #195 的占位 JSON）
k6 run --vus 50 --duration 5m \
  --out json=infra/performance/k6-latest-results.json \
  infra/performance/k6-load-test.js

# 验收：JSON 中 metrics.http_req_duration.p(99) < 200
# 同时 k6 不应再含 "Baseline result — replace with real k6 run output" marker
grep -L "Baseline result" infra/performance/k6-latest-results.json
```

### E2. 支付成功率 > 99.9%

```bash
# 故障注入：让 tx-pay wechat channel 50% 5xx
# 在 staging 用 toxiproxy:
toxiproxy-cli toxic add wechat-pay -t latency -a latency=5000 -a jitter=2000

# 跑 1 小时支付流量，看 PaymentSuccessRateLow 是否 fire
# 然后清除 toxic，看告警是否 recover
toxiproxy-cli toxic remove wechat-pay -n latency_downstream
```

### E3. 4h 离线无丢失

```bash
# 模拟 Mac mini 离线 4h
ssh mac-mini-01 "sudo iptables -A OUTPUT -d <cloud-ip> -j DROP"
# 期间在 POS 录 50+ 笔订单
# 4h 后恢复网络
ssh mac-mini-01 "sudo iptables -F"

# 验收：
# - 边缘队列 50 单全部回传
# - 云端订单数 = 边缘录入数
# - 无 401 / no replay 错误（验证 HMAC ts 是 send-time）
```

### E4. 200 桌并发（cashier with_for_update 验证）

```bash
# 用 hey 同时打 200 个开台/结算请求
hey -n 200 -c 200 -m POST \
  -H "X-Tenant-ID: $T1" \
  "$STAGING_URL/api/v1/cashier/settle"

# 验收：
# - 任一订单仅成功结账一次（PR #195 cashier 行锁生效）
# - DB 无 duplicate Payment 行
# - tx-trade 无死锁日志
```

### E5. 跨租户 RLS 阻断（无 PR #199 也应工作）

```bash
# 注入两个租户数据
psql -c "INSERT INTO orders (tenant_id, ...) VALUES ('t1', ...), ('t2', ...);"

# 用 t1 的 JWT 查 t2 数据
curl -H "X-Internal-JWT: <t1-mint>" "$STAGING_URL/api/v1/orders/t2-order-id"
# 期望: 404 / 0 行（RLS 拦截）

# 注：PR #199 merge 后 BYPASSRLS 路径也会被拦
# 当前阶段（无 #199）BYPASSRLS 角色仍可绕过 — 这是已知 follow-up
```

---

## 7. 阶段 F-G — 灰度门店 → 全量（W3-W4）

详见 `docs/playbook-store-fullflow.md`（如已存在）。

### 灰度顺序

1. **demo 环境**（24h）— 全部 5 项 e2e 通过
2. **尝在一起 文化城店**（1 店 24h）— 真实订单
3. **尝在一起 全部门店**（1 品牌 24h）
4. **3 品牌全量**（48h 持续观察）

### 监控指标（每阶段必看）

```promql
# 服务可用性
up == 0

# 错误率
rate(http_requests_total{status=~"5.."}[5m]) > 0.05

# 支付 SLO
sum(rate(payment_saga_total{result="success"}[10m])) / sum(rate(payment_saga_total[10m])) < 0.999

# 边缘同步成功率
rate(edge_sync_auth_signature_invalid_total[5m]) > 0
```

### 回滚阈值

任一指标越线 → 立刻 `kubectl rollout undo deployment/<svc> -n <namespace>`

---

## 8. 阶段 H — RLS FORCE（W5+）

**最高风险阶段，独立流程，不与本 cutover 同时做。**

详见 `docs/security/rls-force-rollout.md`。要点：
1. 阶段 4（撤 BYPASSRLS + tx_system_role）必须先做（独立 PR）
2. staging dry-run 验证 5 处合法 BYPASSRLS 调用方仍可工作
3. 灰度 24h 后 merge PR #199
4. 全量 rollout 24h 内若出现 RLS-related 5xx 立刻 NO FORCE 回滚

---

## 9. Cutover 后清理工作

merge cutover 完成后：
1. 路由 `_get_tenant_id()` 改为只读 `request.state.tenant_id`，删 X-Tenant-ID header fallback
2. gateway proxy 不再 strip + reinject `X-Tenant-ID`（让客户端发的进入 gateway 即被 middleware 读，统一信任源）
3. NetworkPolicy 部署，限只有 gateway namespace 可达 tx-* pod 端口（纵深防御 cutover）
4. 删除 `EDGE_SYNC_NONCE_ALLOW_INPROCESS` 等过渡 env

---

## 10. Quick Reference — 关键 env 配置矩阵

| Env | 配在哪 | 阶段 | 缺失行为 | 错误配置后果 |
|---|---|---|---|---|
| `TX_INTERNAL_JWT_SECRET` | gateway + 24 服务 K8s Secret | C | dev skip, 生产 fail-closed | gateway 不签发 JWT 或下游 401 全部请求 |
| `EDGE_SYNC_HMAC_SECRET` | tx-trade K8s Secret + Mac mini env | C | dev skip, required=true 拒 | 所有 edge 请求 401 |
| `EDGE_STORE_ID` | 每台 Mac mini env | C | client 不发 X-Edge-Store-Id → server required=true 拒 | 单店 sync 401 |
| `EDGE_SYNC_HMAC_REQUIRED` | tx-trade env | D | false（兼容）| true 但客户端没升级 → 全部 401 |
| `EDGE_SYNC_NONCE_REDIS_URL` | tx-trade K8s Secret | B | 单副本兜底 InProcess | 多副本下重放被绕过 |
| `EDGE_SYNC_NONCE_ALLOW_INPROCESS` | tx-trade env | （过渡）| 生产 + HMAC required 但无 Redis URL → 启动 raise | 显式接受降级 |
| `TX_ENV` | 全服务 | 始终 | 视为 dev | production 必须设 |

---

## 11. 关键事件 Log 关键字

| 事件 | 关键字 | 含义 | 严重程度 |
|---|---|---|---|
| middleware 通过 | `internal_jwt_middleware_claims_set` | 正常 | INFO |
| middleware 拒 | `internal_jwt_middleware_verify_failed` | 401 | WARN |
| middleware 跳过 | `internal_jwt_middleware_skip_no_secret` | dev 模式 | DEBUG |
| HMAC 通过 | `edge_sync_auth_ok` | 正常 | DEBUG |
| HMAC 拒 | `edge_sync_auth_signature_invalid` | 401 | WARN |
| HMAC 跳过 | `edge_sync_auth_skipped_dev_mode` | dev 模式 | WARN |
| HMAC 时间偏差 | `edge_sync_auth_ts_skew` | 401，可能是离线积压 | WARN |
| Redis 故障 | `edge_sync_nonce_store_redis_error` | 503 | ERROR |
| 微信验签拒 | `banquet_deposit.callback_signature_invalid` | 400 | WARN |
| Cashier 行锁等待 | （无显式日志，看 pg_stat_activity） | DB 层面 | — |

---

## 12. 紧急联系矩阵（请补充实际负责人）

| 阶段 | 主负责人 | 备份 | 联系方式 |
|---|---|---|---|
| 部署 | <ops-team> | <sre> | wecom: ... |
| 监控 | <oncall> | <ops-team> | 告警 webhook: ... |
| 回滚 | <release-manager> | <oncall> | — |
| 安全事件 | <security> | <CTO> | — |

---

**playbook 维护**：本文档应跟随每次 cutover 后更新（学到的新事实 / 实际遇到的回滚场景 / 新增的监控规则）。
