# Cutover Staging 部署 Runbook

**对应任务**：#15 staging 部署 6 PR + 24h 观察 / #16 真 k6 替换占位 JSON / #17 e2e 5 项验收
**估时**：3 个工作日
**执行方**：DevOps + QA
**前置**：6 PR 已完成 review（任务 #14）

---

## 一、本 cutover 涉及的 6 PR

| 顺序 | PR | 内容 | Tier |
|------|-----|------|------|
| 1 | #195 | gateway proxy strip + mint internal JWT + Tier1 监控 + RLS gate | P0 batch base |
| 2 | #200 | tx-pay 渠道指标暴露 + PaymentChannelHighErrorRate 告警 | OPS |
| 3 | #201 | tx-trade edge sync nonce store 改 Redis 防多副本绕过 | SECURITY |
| 4 | #202 | InternalJwtMiddleware 实现 + tx-trade 挂载示范（S-02 50→70%） | SECURITY |
| 5 | #206 | tx-pay query/refund/callback 渠道方法 metric 监控盲区补 | OPS |
| 6 | #208 | InternalJwtMiddleware 挂载剩 22 服务（S-02 70→100%） | SECURITY |

**外加**（cutover 阶段独立 PR，部署在主 6 PR 之后）：
- #207 RLS 阶段 4 双模式（部署前不可启用 `RLS_USE_TX_SYSTEM_ROLE=true`）
- #210 K8s NetworkPolicy 强制网络层隔离
- #199 v500 FORCE RLS 全表回填（DO NOT MERGE 到 RLS 阶段 5 完成）
- #211 PR #199 merge checklist + alembic head 自动检查脚本

---

## 二、阶段 A — 镜像构建（D 日 09:00 – 11:00）

```bash
# 1. checkout 合并临时 branch（按依赖序合）
git checkout -b cutover/staging-2026-XX origin/main
git merge origin/audit/p0-fixes-batch-1-5         # PR #195
git merge origin/audit/p0-followup-tx-pay-channel-metrics  # PR #200
git merge origin/audit/p0-followup-redis-nonce-store        # PR #201
git merge origin/audit/p0-followup-internal-jwt-middleware  # PR #202
git merge origin/audit/p0-followup-tx-pay-monitoring-blindspots  # PR #206
git merge origin/audit/p0-followup-internaljwt-23-services  # PR #208

# 冲突解决：6 PR 之间无 file overlap（已 verifier 验证），不应有冲突
# 若冲突 → STOP，回滚 cutover branch，单独 review

# 2. 推送 cutover branch + 触发 CI 构建 staging 镜像
git push origin cutover/staging-2026-XX
gh workflow run build-images.yml -f branch=cutover/staging-2026-XX -f registry=staging
```

**验证**：
- [ ] CI 全绿（rls-gate / tier1-gate / pytest-tier1）
- [ ] 22 个服务镜像已 push 到 staging registry
- [ ] image tag = `cutover/staging-2026-XX-<sha7>`

---

## 三、阶段 B — staging env 准备（D 日 11:00 – 14:00）

### 3.1 注入 InternalJwt secret

```bash
# 32 byte 随机
NEW_SECRET=$(openssl rand -hex 32)
# 写入 staging k8s secret
kubectl -n tunxiang-staging create secret generic internal-jwt \
  --from-literal=TX_INTERNAL_JWT_SECRET="$NEW_SECRET" \
  --dry-run=client -o yaml | kubectl apply -f -

# 验证 22 服务 deployment 已挂载该 secret
for svc in gateway tx-trade tx-pay tx-menu tx-member tx-growth tx-ops tx-supply \
           tx-finance tx-agent tx-analytics tx-brain tx-intel tx-org tx-civic \
           tx-expense tunxiang-api tx-devforge tx-forge tx-predict tx-vietnam \
           tx-indonesia tx-malaysia; do
  kubectl -n tunxiang-staging get deployment "$svc" -o jsonpath='{.spec.template.spec.containers[*].env[?(@.name=="TX_INTERNAL_JWT_SECRET")].valueFrom.secretKeyRef.name}{"\n"}'
done | sort -u  # 期望：单一行 "internal-jwt"
```

### 3.2 RLS 角色准备（仅当 #207 也部署时）

```bash
# 在 staging PG 跑（不撤老 BYPASSRLS，仅创建新角色）
psql "$STAGING_DB_URL" -f scripts/db/create_tx_system_role.sql
# 不跑 revoke_tunxiang_bypassrls.sql！这是阶段 5 的事
```

### 3.3 NetworkPolicy 应用（仅当 #210 也部署时）

```bash
bash scripts/k8s/apply_networkpolicy_s02.sh staging
# 验证 NetworkPolicy 已生效
kubectl -n tunxiang-staging get networkpolicy
```

---

## 四、阶段 C — 滚动部署（D 日 14:00 – 16:00）

```bash
# 按依赖顺序逐个 rollout（避免 InternalJwt 校验失败连锁）
# 1. gateway 先（mint JWT 源）
helm upgrade gateway infra/helm/gateway --namespace tunxiang-staging \
  --set image.tag=cutover/staging-2026-XX-$(git rev-parse --short=7 HEAD) \
  --reuse-values

# 等 gateway 完全 ready 再 rollout 22 个下游服务
kubectl -n tunxiang-staging rollout status deployment/gateway --timeout=5m

# 2. 22 服务并行 rollout
for svc in tx-trade tx-pay tx-menu tx-member tx-growth tx-ops tx-supply \
           tx-finance tx-agent tx-analytics tx-brain tx-intel tx-org tx-civic \
           tx-expense tunxiang-api tx-devforge tx-forge tx-predict tx-vietnam \
           tx-indonesia tx-malaysia; do
  helm upgrade "$svc" "infra/helm/$svc" --namespace tunxiang-staging \
    --set image.tag=cutover/staging-2026-XX-$(git rev-parse --short=7 HEAD) \
    --reuse-values &
done
wait

# 3. 全部 ready 检查
kubectl -n tunxiang-staging get pods | grep -v Running | grep -v Completed
# 期望：空输出（除 header line）
```

---

## 五、阶段 D — 24h 观察（D 日 16:00 – D+1 日 16:00）

### 5.1 关键 Prometheus 指标

```promql
# 1. InternalJwt 错误率（应稳定 0）
sum(rate(http_requests_total{status=~"4..", path!~"/health|/metrics|/docs.*"}[5m])) by (service)
  / sum(rate(http_requests_total{path!~"/health|/metrics|/docs.*"}[5m])) by (service)

# 2. RLS 错误（应 0）
sum(rate(rls_query_total{status="error"}[5m])) by (service)

# 3. 5xx 增量（与部署前 24h 同期对比，不应 > 0.1%）
sum(rate(http_requests_total{status=~"5.."}[5m])) by (service)

# 4. P99 延迟（不应增加 > 10%）
histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, service))

# 5. payment SLO（PR #200/#206 新指标）
rate(payment_channel_call_total{status="failed"}[5m]) by (channel, method)
```

### 5.2 回滚阈值

| 指标 | 阈值 | 动作 |
|------|------|------|
| InternalJwt-related 4xx 率 | > 0.5% | 回滚 #208 |
| 任意服务 5xx 增 | > 0.1% | 全 cutover 回滚 |
| P99 增 | > 20% | 暂停灰度，调查 |
| RLS 错误 | > 0 | 立即回滚 #207（如已启用） |

回滚命令：
```bash
# 单服务回滚
helm rollback gateway --namespace tunxiang-staging
# 全 cutover 回滚（从 git 切回 main）
git checkout main && bash scripts/staging-deploy-from-main.sh
```

---

## 六、阶段 E — e2e 5 项验收（D+1 日 16:00 – D+2 日 12:00）

详见 [cutover-acceptance-checklist.md](./cutover-acceptance-checklist.md) — 5 项 e2e 必须全绿才解锁 prod 灰度：

1. **Tier 1 测试套**：`pytest tests/tier1/ -v` 100% 绿
2. **k6 性能套**：见 §七 k6 占位替换 + P99 < 200ms
3. **支付全链路**：微信/支付宝/银联 query/refund/callback 三方 e2e
4. **跨租户隔离**：tenant_A 探测 tenant_B 数据返 0 行
5. **断网恢复**：模拟 4h 断网后 sync-engine 无数据丢失

---

## 七、k6 占位 JSON 替换（任务 #16 / OPS-004）

当前 k6 套件的 baseline JSON 为占位（见 `tests/k6/baselines/*.json` 头注释）。
staging 跑通后用真实数据替换：

```bash
# 1. 跑当前 k6 套件，输出 baseline
k6 run --out json=tests/k6/baselines/staging-baseline-$(date +%Y%m%d).json \
       tests/k6/cutover-suite.js \
       --env STAGING_HOST=staging.tunxiang.internal

# 2. review JSON：P50/P95/P99 是否在 SLO 内（< 200ms）
jq '.metrics["http_req_duration"].values' tests/k6/baselines/staging-baseline-*.json

# 3. 如果通过 → 替换占位
mv tests/k6/baselines/staging-baseline-*.json tests/k6/baselines/cutover-suite.json
git add tests/k6/baselines/cutover-suite.json
git commit -m "ops(k6): 替换 cutover-suite baseline 为 staging 真值 [OPS-004]"
```

---

## 八、验收标准（cutover 阶段 A-E 全闭环）

- [ ] 阶段 A: 6 PR + 4 cutover-period PR 全部 CI 绿，镜像已 build
- [ ] 阶段 B: 22 服务 secret/RLS 角色/NetworkPolicy 全部就位
- [ ] 阶段 C: 22 服务全部 rollout 成功 + ready
- [ ] 阶段 D: 24h 观察 5xx/P99/RLS 全部在阈值内
- [ ] 阶段 E: 5 项 e2e 全绿（pytest tier1 + k6 + 支付 + 跨租户 + 断网）
- [ ] k6 baseline 占位已替换为 staging 真值（OPS-004 闭环）

---

## 九、并行可执行的任务

| 任务 | 何时跑 | 谁 |
|------|--------|-----|
| #13 品智 17 token 轮换 | 与 cutover 并行（独立营业窗口） | DevOps + 品智客服 |
| 监控 dashboard 复盘 | D 日 16:00 后 | SRE |
| 客户提前通知（告知本次 cutover 时间窗口） | D-1 日 18:00 | CSM + 客户运营 |
