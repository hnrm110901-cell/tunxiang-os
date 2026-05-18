# Prometheus Bearer Token Secret — 创建 / 轮换 / 回滚 Runbook

**适用范围**: `api-gateway` / `tx-trade` / `tx-event-relay` 三个 Helm chart  
**Secret 名称**: `tx-metrics-token`  
**Secret key**: `token`  
**env var**: `PROMETHEUS_BEARER_TOKEN`  
**相关 issue**: #830 / #825  
**预计操作时间**: 新人 5-10 分钟可跑通

---

## 前置说明

本 Secret 用于 `/metrics` 端点 Bearer Token 鉴权 (`MetricsAuthMiddleware`, `shared/middleware`)。

- 未启用 (`prometheus.metricsToken.enabled: false`): backend pod 不注入该 env，`/metrics` 按 `PROMETHEUS_AUTH_ENFORCE` 值决定行为（默认 `false` = 放行）。  
- 启用后 (`enabled: true`): pod 注入 `PROMETHEUS_BEARER_TOKEN`，Secret **必须**在 helm upgrade 前已存在，否则 `CreateContainerConfigError`，pod 不启动。

---

## Step 1: 生成 Token

```bash
# 生成 43 字符 URL-safe token（> _MIN_TOKEN_LEN=16，符合 metrics_auth.py 校验）
TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
echo "Token length: $(echo -n $TOKEN | wc -c)"   # 期望: 43
# 不要将 token 写入文件或提交到 git
```

---

## Step 2: 创建 Kubernetes Secret

```bash
NAMESPACE=<ns>   # 替换为真实 namespace，例: tunxiang-prod / tunxiang-staging

# 检查 Secret 是否已存在
kubectl -n $NAMESPACE get secret tx-metrics-token 2>/dev/null && echo "EXISTS" || echo "NOT FOUND"

# 首次创建（Secret 不存在时）
kubectl -n $NAMESPACE create secret generic tx-metrics-token \
  --from-literal=token="$TOKEN"

# 已存在时（幂等更新，不删 Secret 保 Prometheus 可继续读旧值）
kubectl -n $NAMESPACE create secret generic tx-metrics-token \
  --from-literal=token="$TOKEN" \
  --dry-run=client -o yaml | kubectl -n $NAMESPACE apply -f -

# 验证 Secret 已创建（不要 echo token 明文）
kubectl -n $NAMESPACE get secret tx-metrics-token -o jsonpath='{.data.token}' | base64 -d | wc -c
# 期望: 43
```

---

## Step 3: 启用 Chart 并滚动部署

```bash
NAMESPACE=<ns>
RELEASE_NAME=<release>   # 例: api-gateway / tx-trade / tx-event-relay

# 启用 metricsToken 注入（3 个 chart 逐个或并行）
helm upgrade $RELEASE_NAME infra/helm/$RELEASE_NAME \
  --namespace $NAMESPACE \
  --reuse-values \
  --set prometheus.metricsToken.enabled=true

# 或使用 values override 文件（推荐 prod 管理）:
# helm upgrade $RELEASE_NAME infra/helm/$RELEASE_NAME \
#   --namespace $NAMESPACE \
#   -f values-prod.yaml

# 等待滚动完成
kubectl -n $NAMESPACE rollout status deployment/$RELEASE_NAME --timeout=120s
```

---

## Step 4: 验证 env 已注入

```bash
POD=$(kubectl -n $NAMESPACE get pods -l app.kubernetes.io/name=$RELEASE_NAME \
  -o jsonpath='{.items[0].metadata.name}')

# 验证 env 存在（不输出 token 值）
kubectl -n $NAMESPACE exec $POD -- env | grep PROMETHEUS_BEARER_TOKEN | cut -d= -f1
# 期望: PROMETHEUS_BEARER_TOKEN

# 验证 /metrics 可用（需先获取 token）
TOKEN_VAL=$(kubectl -n $NAMESPACE exec $POD -- sh -c 'echo $PROMETHEUS_BEARER_TOKEN')
kubectl -n $NAMESPACE exec $POD -- sh -c \
  "wget -q -O- --header='Authorization: Bearer $TOKEN_VAL' http://localhost:<port>/metrics | head -5"
# 期望: # HELP 或 # TYPE 开头的 Prometheus 文本格式
```

---

## Step 5: 轮换 Token（零停机注意事项）

> **重要限制**: 当前 `metrics_auth.py` 仅支持单 token。轮换窗口期（新 Secret apply → pod 重启完成）内 Prometheus 使用旧 token，backend pod 重启后使用新 token，**约 ~5 分钟内 Prometheus scrape 会收到 401**。  
> 可接受的 trade-off: scrape 401 不影响业务数据，仅监控出现短暂断点。  
> 若需真 zero-downtime 轮换，需先 ship `PROMETHEUS_BEARER_TOKEN_PREV` 双 token 支持（follow-up issue）。

```bash
NAMESPACE=<ns>

# 1. 生成新 token
NEW_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')

# 2. 先更新 Prometheus 侧 credentials（让 Prometheus 用新 token）
#    如用 kubernetes secret 挂载 credentials_file，更新该 Secret：
#    kubectl -n $NAMESPACE patch secret prometheus-credentials ...
#    等一个 scrape 间隔（默认 30s）让 Prometheus reload

# 3. 更新 backend Secret（幂等 apply）
kubectl -n $NAMESPACE create secret generic tx-metrics-token \
  --from-literal=token="$NEW_TOKEN" \
  --dry-run=client -o yaml | kubectl -n $NAMESPACE apply -f -

# 4. 滚动重启 3 个 chart（触发 pod 重新读 env）
for CHART in api-gateway tx-trade tx-event-relay; do
  kubectl -n $NAMESPACE rollout restart deployment/$CHART
done

# 5. 等待滚动完成
for CHART in api-gateway tx-trade tx-event-relay; do
  kubectl -n $NAMESPACE rollout status deployment/$CHART --timeout=180s
done

# 6. 验证 Prometheus scrape 恢复正常（无 401）
kubectl -n $NAMESPACE logs -l app.kubernetes.io/name=prometheus --since=5m | grep -i "401\|unauthorized" | wc -l
# 期望: 0
```

---

## Step 6: 回滚

```bash
NAMESPACE=<ns>
CHART=api-gateway   # 重复 tx-trade / tx-event-relay

# 查询可回滚版本
helm -n $NAMESPACE history $CHART

# 回滚到上一版本（pod 不再注入 PROMETHEUS_BEARER_TOKEN env）
helm -n $NAMESPACE rollback $CHART

# 验证 pod 已重启且 env 不存在
POD=$(kubectl -n $NAMESPACE get pods -l app.kubernetes.io/name=$CHART \
  -o jsonpath='{.items[0].metadata.name}')
kubectl -n $NAMESPACE exec $POD -- env | grep PROMETHEUS_BEARER_TOKEN || echo "env not found (expected)"

# Secret 保留不删（Prometheus 仍可读 credentials_file，backend 不读 = 安全降级）
# MetricsAuthMiddleware 在 PROMETHEUS_AUTH_ENFORCE=false（默认）时放行所有请求
```

---

## 相关资源

- `shared/middleware/src/metrics_auth.py` — Bearer Token 鉴权实现
- `infra/monitoring/prometheus/prometheus.yml` — Prometheus scrape credentials_file 配置
- Issue #830 — 本 runbook 来源 PR
- Issue #825 — `/metrics` 401 fix (MetricsAuthMiddleware ship)
- Follow-up: Prometheus Helm chart (`infra/helm/prometheus/`) — docker-compose → k8s 迁移
