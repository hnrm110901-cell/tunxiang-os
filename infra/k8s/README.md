# 屯象OS K8s Bootstrap 说明

本目录包含屯象OS Kubernetes集群的Bootstrap配置，适用于腾讯云TKE（Tencent Kubernetes Engine）。

## 文件清单

| 文件 | 用途 |
|------|------|
| `namespaces.yaml` | 7个Namespace定义（dev/test/uat/pilot/prod/demo/monitoring） |
| `rbac.yaml` | Harness Delegate RBAC配置（ServiceAccount + ClusterRole + ClusterRoleBinding） |
| `secrets-template.yaml` | Secret结构模板（不含真实值，由Harness注入） |
| `network-policy.yaml` | 网络隔离策略（默认拒绝 + 白名单访问） |
| `resource-quotas.yaml` | 各namespace资源配额 + LimitRange |

---

## 首次部署顺序

严格按以下顺序执行，确保依赖关系正确：

```bash
# Step 1：创建Namespace（所有后续资源的容器）
kubectl apply -f namespaces.yaml

# Step 2：创建RBAC（Harness Delegate需要权限才能部署服务）
kubectl apply -f rbac.yaml

# Step 3：Secret由Harness注入（不手动apply secrets-template.yaml）
# 在Harness平台配置好Secret Manager后，由Pipeline自动注入
# 仅开发调试时可手动创建（见下方说明）

# Step 4：创建NetworkPolicy（服务间访问控制）
kubectl apply -f network-policy.yaml

# Step 5：创建ResourceQuota（资源配额上限）
kubectl apply -f resource-quotas.yaml
```

---

## 如何使用Harness Delegate连接TKE集群

### 前置条件
- 已有腾讯云TKE集群（建议版本：1.28+）
- 已在Harness平台创建Organization和Project
- 本地已安装kubectl并配置好TKE kubeconfig

### Step 1：在Harness平台安装Delegate

1. 进入 Harness > Account Settings > Delegates > New Delegate
2. 选择 **Kubernetes** 类型
3. 下载生成的 `harness-delegate.yaml`
4. 修改namespace为 `tunxiang-prod`（或对应环境）

```bash
kubectl apply -f harness-delegate.yaml -n tunxiang-prod
```

5. 等待Delegate状态变为 Connected（约2-3分钟）

### Step 2：配置TKE集群凭证

1. 在Harness > Connectors 创建 **Kubernetes Cluster** Connector
2. 认证方式选择 **Inherit from Delegate**（使用Delegate的ServiceAccount权限）
3. Delegate选择刚创建的 `harness-delegate`
4. 测试连接确认成功

### Step 3：验证权限

```bash
# 验证Delegate ServiceAccount权限
kubectl auth can-i create deployments --as=system:serviceaccount:tunxiang-prod:harness-delegate -n tunxiang-prod
kubectl auth can-i create secrets --as=system:serviceaccount:tunxiang-prod:harness-delegate -n tunxiang-prod
```

---

## Namespace隔离策略说明

### 隔离原则
- 每个环境独立Namespace，完全隔离
- 生产数据库与非生产数据库物理分离（不同TencentDB实例）
- 跨Namespace流量默认拒绝，仅白名单例外

### 各环境用途

| Namespace | 用途 | 流量 |
|-----------|------|------|
| tunxiang-dev | 开发联调 | 仅内部访问 |
| tunxiang-test | 自动化测试 | CI/CD Pipeline触发 |
| tunxiang-uat | 用户验收测试 | 客户体验环境 |
| tunxiang-pilot | 灰度（徐记海鲜等标杆门店） | 小批量真实流量 |
| tunxiang-prod | 生产 | 全量真实门店流量 |
| tunxiang-demo | POC演示 | 销售演示用 |
| monitoring | 监控（Prometheus/Grafana） | 采集所有namespace metrics |

### 网络白名单规则

```
监控采集：monitoring → 所有namespace（Prometheus抓取metrics）
南北向：api-gateway → 所有business service（唯一入口）
Agent链路：tx-agent → tx-brain（LLM调用，需低延迟）
同namespace：namespace内Pod间互通（同环境服务间调用）
其余：默认拒绝
```

---

## Secret管理

### 安全红线
**绝对禁止在任何Git文件中提交真实凭证。** `secrets-template.yaml` 仅为结构说明，不含真实值。

### Harness Secret Manager集成

生产环境Secret注入流程：
1. 运维在Harness Secret Manager中配置各环境的Secret值
2. Harness Pipeline在部署时通过 `${secrets.getValue("...")}` 动态读取
3. Pipeline生成真实Secret并apply到对应namespace
4. 服务通过 `secretRef.name` 引用，无需接触明文

### 开发环境手动创建（仅dev/test）

```bash
# 仅限开发测试环境，生产绝对不用此方法
kubectl create secret generic tunxiang-app-secrets \
  --from-literal=DATABASE_URL="postgresql://..." \
  --from-literal=REDIS_URL="redis://..." \
  --from-literal=JWT_SECRET="..." \
  -n tunxiang-dev
```

---

## 从docker-compose迁移到K8s的注意事项

屯象OS此前使用docker-compose运行（参考 `infra/docker/`），迁移到K8s时需注意：

### 1. 服务发现变化

| docker-compose | K8s |
|----------------|-----|
| 服务名直接作为hostname | ClusterIP Service名作为hostname |
| `http://tx-trade:8001` | `http://tx-trade.tunxiang-prod.svc.cluster.local:8001` |
| 同network内自动发现 | 同namespace内通过Service DNS发现 |

### 2. 环境变量注入变化

| docker-compose | K8s |
|----------------|-----|
| `.env` 文件 | Secret + ConfigMap |
| `environment:` 块直接写值 | `envFrom.secretRef` 引用 |
| 明文存储 | 加密存储（etcd加密） |

### 3. 数据持久化

- docker-compose使用本地volume → K8s使用PVC（腾讯云CBS云硬盘）
- Redis/PostgreSQL建议使用托管服务（TencentDB/Tendis），不在K8s内运行有状态服务

### 4. 健康检查

docker-compose无内置健康检查机制，K8s通过 `livenessProbe` + `readinessProbe` 实现：
- 所有服务已在Helm Chart中配置 `GET /health` 健康检查端点
- `initialDelaySeconds: 30` 给FastAPI服务留足启动时间

### 5. 日志收集

- docker-compose：`docker logs` 查看
- K8s：统一输出到stdout/stderr，由腾讯云CLS（日志服务）采集
- 服务日志格式已统一为JSON（structlog），便于CLS过滤查询

### 6. 迁移验证清单

在切流生产前完成以下验证：

- [ ] 所有13个服务在tunxiang-uat正常启动
- [ ] `/health` 端点全部返回200
- [ ] api-gateway路由转发正常（抽查核心接口）
- [ ] NetworkPolicy验证：跨namespace访问被拦截
- [ ] ResourceQuota验证：资源用量在限额内
- [ ] Harness Pipeline完成一次全量部署演练
- [ ] 回滚演练：模拟失败并执行回滚
