# Cutover E2E 5 项验收 Checklist

**对应任务**：#17 staging 端到端 5 项验收（cutover 阶段 E）
**前置**：[cutover-staging-deployment.md](./cutover-staging-deployment.md) 阶段 A-D 全绿
**估时**：1 个工作日（D+1 日 16:00 – D+2 日 12:00）

每项必须 ✅ 才解锁 prod 灰度。

---

## 1️⃣ Tier 1 测试套（CLAUDE.md §17 零容忍域）

```bash
# 在 staging 跑（连真 staging DB / Redis）
TX_ENV=staging \
DATABASE_URL=postgresql+asyncpg://staging-db... \
REDIS_URL=redis://staging-redis:6379 \
TX_INTERNAL_JWT_SECRET=$STAGING_INTERNAL_JWT \
pytest tests/tier1/ -v --tb=short --maxfail=1 2>&1 | tee /tmp/tier1-result.log
```

**验收**：
- [ ] Pass rate = 100%（任何 fail 即立即回滚）
- [ ] 含以下 8 项 Tier 1 域全绿：
  - 订单状态机 / 支付 Saga / RLS 隔离 / POS 写入 / 存酒押金 / 全电发票 / LWW 冲突解析（终态豁免）/ 三条硬约束

---

## 2️⃣ k6 性能套（P99 < 200ms / 错误率 < 0.1%）

```bash
# 200 桌并发结账（CLAUDE.md §17 Tier 1 验收标准）
k6 run \
  --vus=200 \
  --duration=10m \
  --env STAGING_HOST=staging.tunxiang.internal \
  --env TX_INTERNAL_JWT=$STAGING_JWT_FOR_K6 \
  tests/k6/cutover-checkout-200vus.js

# 期望输出（k6 summary）：
#   ✓ http_req_duration p(99) < 200ms
#   ✓ http_req_failed   rate < 0.1%
#   ✓ checks            rate > 99%
```

**验收**：
- [ ] P99 < 200ms（Tier 1 基准）
- [ ] 错误率 < 0.1%
- [ ] 200 vus / 10m 全程稳定（无 RAM/CPU 飙升）
- [ ] baseline JSON 已更新（任务 #16 OPS-004 闭环）

---

## 3️⃣ 支付全链路（微信/支付宝/银联 query/refund/callback）

```bash
# 自动化脚本（PR #206 metric 验证 + #205 runbook drill）
bash scripts/staging/payment-e2e-three-channels.sh
```

**手工验收**（与 staging 收银员协调）：
- [ ] **微信 JSAPI**：小程序下单 → wxpay sandbox 支付 → callback 收到 → 订单状态 PAID
- [ ] **微信退款**：发起 refund → callback 收到 → 订单状态 REFUNDED
- [ ] **支付宝当面付**：扫码支付 → callback → 订单 PAID
- [ ] **支付宝退款**：refund → callback → 订单 REFUNDED
- [ ] **银联刷卡**（如 staging 有真硬件）：刷卡 → callback → 订单 PAID
- [ ] **3 个 metric 都有数据**（PR #200/#206 修复后必须）：
  ```
  payment_channel_call_total{channel="wechat", method="pay", status="success"} > 0
  payment_channel_call_total{channel="wechat", method="query", status="success"} > 0
  payment_channel_call_total{channel="wechat", method="refund", status="success"} > 0
  ```

---

## 4️⃣ 跨租户隔离（S-02 + S-05 复合验证）

```bash
# 用 staging 的 2 个 tenant 互探
TENANT_A_JWT=$STAGING_TENANT_A_JWT
TENANT_B_JWT=$STAGING_TENANT_B_JWT

# 测试 1: tenant_A 用自己 JWT 查 tenant_B 的订单 — 必须返 0 行 / 403
curl -H "X-Internal-JWT: $TENANT_A_JWT" \
     -H "X-Tenant-ID: <tenant_b_uuid>" \
     "https://staging.tunxiang.internal/api/v1/trade/orders" \
     | jq '.data.items | length'
# 期望：0（state 来自 JWT，header 被忽略）

# 测试 2: 直发 X-Tenant-ID header 不带 X-Internal-JWT — 必须 401
curl -H "X-Tenant-ID: <any_uuid>" \
     "https://staging.tunxiang.internal/api/v1/trade/orders" \
     -o /dev/null -w "%{http_code}"
# 期望：401（PR #208 InternalJwtMiddleware 必须拒）

# 测试 3: NetworkPolicy 验证（PR #210）— 直接打 tx-trade nodePort 应 timeout
curl --max-time 5 "http://staging-node-ip:30001/api/v1/orders" 2>&1 | grep -E "timed out|refused"
# 期望：connection timed out 或 connection refused（NetworkPolicy 阻止）
```

**验收**：
- [ ] 测试 1: tenant_A 用自己 JWT 跨租查 tenant_B → 返 0 行
- [ ] 测试 2: 无 JWT 直发 X-Tenant-ID → 401
- [ ] 测试 3: nodePort 直连 → timeout/refused

---

## 5️⃣ 断网 4h 恢复（LWW + 终态豁免 / sync-engine）

```bash
# 在 staging-edge-1 (Mac mini staging 环境) 模拟断网
ssh staging-edge-1
sudo ifconfig en0 down

# 在 staging-edge-1 上跑 4h 真实业务（订单 / KDS / 库存）
# ... 4 小时业务操作 ...

# 恢复网络
sudo ifconfig en0 up

# 等 sync-engine 自动追平（默认 5 min 1 轮，4h 数据约 12 轮可追完）
sleep 1800

# 比对：staging-edge-1 本地 PG vs 云端 PG
psql "$EDGE_DB_URL"  -c "SELECT COUNT(*) FROM orders WHERE created_at >= NOW() - INTERVAL '5 hours';" \
  > /tmp/edge_count.txt
psql "$CLOUD_DB_URL" -c "SELECT COUNT(*) FROM orders WHERE created_at >= NOW() - INTERVAL '5 hours' AND store_id = '<staging_store_id>';" \
  > /tmp/cloud_count.txt
diff /tmp/edge_count.txt /tmp/cloud_count.txt
# 期望：完全一致
```

**验收**：
- [ ] 边缘 PG 订单数 == 云端 PG 订单数
- [ ] 无未收敛冲突（检查 `lww_unresolved_conflicts_total` 指标 = 0；指标名仍可能为 `crdt_conflicts_total` — 见 sync-engine /metrics）
- [ ] sync-engine 无 fatal error log（grep "level=ERROR" /var/log/sync-engine/*.log）

---

## 解锁 prod 灰度的判定

| # | 项目 | ✅/❌ |
|---|------|-------|
| 1 | Tier 1 测试套 100% 绿 | |
| 2 | k6 P99 < 200ms / 错误率 < 0.1% | |
| 3 | 支付全链路 3 渠道 / 6 用例全绿 + 3 metric 全有数据 | |
| 4 | 跨租户隔离 3 测试全绿 | |
| 5 | 断网 4h 恢复无丢失 / 无冲突 | |

**全 ✅** → 进入 [cutover-staging-deployment.md](./cutover-staging-deployment.md) §五 24h 观察 + 准备 prod 灰度。

**任意 ❌** → 立即回滚（详见 deployment runbook §五.2 回滚阈值）+ 记录 root cause +
本 checklist 标注失败原因后重新执行。

---

## 自动化执行（推荐）

```bash
# 一键跑全 5 项（fail 即停）
bash scripts/staging/cutover-acceptance-all.sh \
     --tenant-a-jwt $A --tenant-b-jwt $B \
     --staging-host staging.tunxiang.internal
```
（脚本待 staging env 准备好后由 QA 实现，本 checklist 提供期望行为契约。）
