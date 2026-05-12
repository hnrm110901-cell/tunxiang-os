# api-gateway Helm Chart

屯象OS API Gateway 微服务的 Kubernetes Helm Chart。包含 Deployment、Service、HPA、PDB、NetworkPolicy、ConfigMap、双 Ingress（主 + 专限 /api/v1/auth/*）等工件。

## 部署前提

### 限流（rate-limit）仅对 client real IP 有效的前提

`templates/ingress-auth.yaml` 给 `/api/v1/auth/*` 配了 `nginx.ingress.kubernetes.io/limit-rpm` 等限流 annotation（issue #455 / F#6 PR-1）。
**但 ingress-nginx 默认按 `$binary_remote_addr` 计数 = 直连 nginx 的 socket peer IP。**

#### 云 LB 部署（腾讯云 CLB / 阿里云 SLB / AWS NLB 等）

- `$binary_remote_addr` = LB 的 source-NAT IP（所有 client 共享同一个或几个 IP）
- 后果：
  1. **限流聚合误伤** — 10 r/m 全租户共享，一个租户密集登录会把所有租户挤掉
  2. **攻击者控连接源路由获 N× 桶绕过** — 控制多个出站 IP 即可线性放大攻击速率
- **必须**在 ingress-nginx-controller 的 ConfigMap 设置：

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: ingress-nginx-controller
  namespace: ingress-nginx
data:
  use-forwarded-for: "true"
  proxy-real-ip-cidr: "<你的 LB 源段>"   # e.g. 腾讯云 CLB: 100.125.0.0/16
  # 阿里云 SLB / AWS NLB 源段以各云厂商文档为准
```

- 应用：`kubectl apply -f ingress-nginx-configmap.yaml` 后 `kubectl rollout restart deployment/ingress-nginx-controller -n ingress-nginx`
- ⚠️ **这是跨 namespace cluster ops 改动，本 helm chart 不自动应用**；由 ops 团队负责（追踪 issue 待补）
- ⚠️ **per-Ingress annotation 不存在** — ingress-nginx 把 `use-forwarded-for` 设为 ConfigMap-only setting，chart 模板层无法注入

#### 验证方法

1. 从两个不同公网 IP 各发 10 r/m，应彼此独立计数（不共享 limit-rpm 桶）
2. 伪造 `X-Forwarded-For: 1.2.3.4` 头多次请求，不应改变计数桶（防绕过）

#### bare-metal / 直连部署

- 无 LB 中间层，`$binary_remote_addr` 就是 client IP，无需上述 ConfigMap 改动
- `values.yaml` 的 `ingress.realIP.enabled` 保持 `false`
- 对照 bare-metal nginx config: `infra/nginx/nginx-tls-hardened.conf:130`（同等限流策略）

### values.yaml 限流配置说明

```yaml
ingress:
  rateLimit:
    enabled: true              # 整 ingress-auth.yaml 渲染开关；false 不渲染
    authPathRpm: 10            # /api/v1/auth/* per-IP rate ceiling（req/min）
    authBurstMultiplier: 1     # burst = rpm × multiplier = 10 r/m
  realIP:
    enabled: false             # 云 LB 部署必须 enabled=true + 填 trustedCidr
    trustedCidr: ""            # e.g. "100.125.0.0/16" for 腾讯云 CLB
    header: "X-Forwarded-For"
```

#### bare-metal 对照表

| 参数 | helm 默认 | bare-metal (`nginx-tls-hardened.conf:130`) | 差异 |
|---|---|---|---|
| rate ceiling | 10 r/m | 10 r/m (`rate=10r/m`) | 一致 |
| burst | 10 r/m (multiplier=1) | 5 (`burst=5 nodelay`) | helm 是 2× 宽（multiplier 整数最小有效值=1） |
| 计数键 | `$binary_remote_addr`（默认；云 LB 部署需经上述 ConfigMap 重定向到 XFF） | `$binary_remote_addr` | bare-metal 直连一致；云 LB 需 ConfigMap 修复 |
| 连接上限 | 10 (`limit-connections`) | 无显式 `limit_conn` | helm 多一道连接闸 |

`authBurstMultiplier` 范围说明：
- `0`：controller 接受但 burst = 0 → 所有非匀速请求立即 429，过严
- `1`（默认）：burst = rpm × 1 = 10 r/m，距离 bare-metal burst=5 最近的合法值
- `5`（controller 缺省）：burst = 50 r/m，过松不取

### 紧急关闭限流（仅 ops 临时使用）

```bash
helm upgrade api-gateway ./infra/helm/api-gateway \
  --set ingress.rateLimit.enabled=false \
  --reuse-values
```

恢复需 follow-up issue 跟踪（追踪：issue #455）。

## 主要工件

| 文件 | 说明 |
|---|---|
| `Chart.yaml` | chart metadata |
| `values.yaml` | 默认值（生产覆盖通过 `-f values-prod.yaml`） |
| `templates/deployment.yaml` | 主 Deployment（含 F#2 PSA restricted securityContext） |
| `templates/service.yaml` | ClusterIP Service |
| `templates/ingress.yaml` | 主 Ingress（`/` Prefix，无限流） |
| `templates/ingress-auth.yaml` | 专限 Ingress（`/api/v1/auth` Prefix，含 limit-rpm/burst/connections） |
| `templates/hpa.yaml` | HorizontalPodAutoscaler（默认 disabled） |
| `templates/poddisruptionbudget.yaml` | PDB（Tier 1 服务 minAvailable=1） |
| `templates/networkpolicy.yaml` | NetworkPolicy（默认 disabled，需画服务依赖图后启用） |
| `templates/configmap.yaml` | 可选额外 ConfigMap（默认 disabled） |

## Follow-up

- P2-1（issue #455 round-1 P2）：`limit-connections` 暴露到 values.yaml 而非硬编码
- P2-2（issue #455 round-1 P2）：`proxy-body-size` 收紧（auth path 不需要 10m）
- 主 `templates/ingress.yaml` 也存在 deprecated `kubernetes.io/ingress.class: nginx` annotation，留 follow-up（不在本 PR scope）
- ingress-nginx-controller ConfigMap 应用 ops issue 待补
