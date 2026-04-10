# 屯象OS Harness 平台建对象操作手册

> 版本: 1.0 | 最后更新: 2026-04-06 | 维护人: 李淳（屯象OS创始人）
>
> 本手册面向屯象OS单人开发场景定制，按实际操作顺序编写，避免依赖缺失导致的反复重建。

---

## 第一节：前置准备

### 1.1 Harness 账号三层架构

```
Account（屯象OS）
└── Org（tunxiang-org）
    └── Project（tunxiang-os）
```

| 层级 | 用途 | 说明 |
|------|------|------|
| Account | 计费单元、账号级别的 Secrets 和 Connectors | 跨项目共用的基础设施连接，如 Harbor、GitHub |
| Org（tunxiang-org） | 跨 Project 共享资源 | 公共 Connector、User Group 定义 |
| Project（tunxiang-os） | 业务 Service、Pipeline、Environment | 屯象OS所有CI/CD对象均在此 Project 下 |

### 1.2 作用域决策原则

| 对象类型 | 放哪个层级 | 理由 |
|---------|-----------|------|
| secret_github_pat | Account | GitHub App全局共用 |
| secret_harbor_* | Account | Harbor镜像仓库全局共用 |
| secret_pg_url_* | Project | 各环境DB URL不同 |
| github_connector | Org | 代码仓库连接共用 |
| harbor_connector | Org | 镜像仓库连接共用 |
| k8s_*_connector | Project | 各环境K8s集群不同 |
| svc_* (Services) | Project | 业务服务属于项目级 |
| env_* (Environments) | Project | 环境属于项目级 |
| Pipeline | Project | 流水线属于项目级 |

### 1.3 事前检查清单

在 Harness 界面操作前，确认以下信息已就绪：

- [ ] Harness 账号已注册，Plan 满足需求（Free Tier 或 Team）
- [ ] GitHub 仓库 `tunxiang-os` 已存在，可通过 GitHub App 授权
- [ ] Harbor 镜像仓库地址已确认（内网地址 + 凭证）
- [ ] 云端 K8s 集群的 kubeconfig / Service Account Token 已准备
- [ ] 企微机器人 Webhook URL 已准备（用于审批通知）
- [ ] 本地已克隆仓库，`.harness/` 目录下的 YAML 文件均已就绪

---

## 第二节：必建对象清单（按操作顺序）

> **操作顺序至关重要**：后面的对象依赖前面的对象，必须按序创建。

### 2.1 Secrets（P0，优先级最高）

**路径**: Project Settings → Secrets → + New Secret

所有 Secret 均使用 `Inline Secret Value` 类型（文本），除非另有说明。

| Secret 标识符 | 类型 | 值来源 | 作用域 | 说明 |
|-------------|------|-------|--------|------|
| `secret_github_pat` | Text | GitHub → Settings → PAT → Classic Token | Account | 需 `repo`, `workflow` 权限 |
| `secret_harbor_username` | Text | Harbor 用户名 | Account | 通常为 `tunxiang-ci` |
| `secret_harbor_password` | Text | Harbor 密码 | Account | CI 专用账号密码 |
| `secret_pg_url_dev` | Text | dev DB连接串 | Project | `postgresql://user:pass@host:5432/db` |
| `secret_pg_url_test` | Text | test DB连接串 | Project | - |
| `secret_pg_url_uat` | Text | uat DB连接串 | Project | - |
| `secret_pg_url_pilot` | Text | pilot DB连接串 | Project | - |
| `secret_pg_url_prod` | Text | prod DB连接串 | Project | **最高机密，限SRE访问** |
| `secret_wecom_webhook` | Text | 企微机器人Webhook URL | Project | 用于审批、告警通知 |
| `secret_supabase_anon_key` | Text | Supabase anon key | Project | 前端SDK使用 |
| `secret_supabase_service_key` | Text | Supabase service role key | Project | 后端管理操作 |
| `secret_jwt_secret` | Text | JWT签名密钥 | Project | 生成32位以上随机字符串 |
| `secret_redis_password` | Text | Redis 认证密码 | Project | - |

> **安全提示**: `secret_pg_url_prod` 和 `secret_supabase_service_key` 应设置 Secret 访问控制，仅允许 `release_manager_group` 访问。

### 2.2 Connectors（7个）

**路径**: Project Settings → Connectors → + New Connector

按以下顺序创建（github_connector 最先，因为 Service 的代码拉取依赖它）：

#### Connector 1: github_connector（GitHub 代码仓库）

| 字段 | 值 |
|------|----|
| Name | `github_connector` |
| Identifier | `github_connector` |
| Type | GitHub |
| URL Type | Repository |
| Connection URL | `https://github.com/lichun/tunxiang-os`（替换为实际路径） |
| Authentication | GitHub App（推荐）或 Personal Access Token |
| PAT Secret | `account.secret_github_pat` |
| Connectivity Mode | Connect through Harness Platform |

验证：点击 Test Connection，确保显示 Connection Successful。

#### Connector 2: harbor_connector（容器镜像仓库）

| 字段 | 值 |
|------|----|
| Name | `harbor_connector` |
| Identifier | `harbor_connector` |
| Type | Docker Registry |
| Provider | Other（Harbor） |
| Docker Registry URL | `https://registry.tunxiang.internal`（替换为实际地址） |
| Authentication | Username and Password |
| Username | `account.secret_harbor_username` |
| Password | `account.secret_harbor_password` |

#### Connector 3: k8s_dev_connector（Dev K8s集群）

| 字段 | 值 |
|------|----|
| Name | `k8s_dev_connector` |
| Identifier | `k8s_dev_connector` |
| Type | Kubernetes Cluster |
| Connection Method | Service Account |
| Master URL | Dev集群API Server地址 |
| Service Account Token | 对应 Secret |
| Namespace | `tunxiang-dev` |

#### Connector 4: k8s_test_connector（Test K8s集群）

同 k8s_dev_connector，namespace 改为 `tunxiang-test`。

#### Connector 5: k8s_uat_connector（UAT K8s集群）

同 k8s_dev_connector，namespace 改为 `tunxiang-uat`。

#### Connector 6: k8s_pilot_connector（Pilot K8s集群）

同 k8s_dev_connector，namespace 改为 `tunxiang-pilot`。

#### Connector 7: k8s_prod_connector（生产 K8s集群）

| 字段 | 值 |
|------|----|
| Name | `k8s_prod_connector` |
| Identifier | `k8s_prod_connector` |
| Type | Kubernetes Cluster |
| Connection Method | Service Account |
| Namespace | `tunxiang-prod` |
| 注意 | **此Connector仅赋权给 release_manager_group，其他角色不可访问** |

### 2.3 Services（Batch 1，4个核心服务）

**路径**: Deployments → Services → + New Service

#### Service 1: svc_api_gateway

| 字段 | 值 |
|------|----|
| Name | `svc_api_gateway` |
| Identifier | `svc_api_gateway` |
| Deployment Type | Kubernetes |

**Artifact Source**:
```
- Identifier: api_gateway_image
  Type: DockerRegistry
  connectorRef: harbor_connector
  imagePath: tunxiang/api-gateway
  tag: <+pipeline.variables.imageTag>
```

**Manifests**:
```
- Identifier: api_gateway_k8s
  Type: K8sManifest
  connectorRef: github_connector
  gitFetchType: Branch
  branch: main
  paths: [gitops/api-gateway/]
```

**Service Variables**:
- `PORT`: `8000`
- `LOG_LEVEL`: `info`
- `ENABLE_FEATURE_FLAGS`: `true`

#### Service 2: svc_web_admin

| 字段 | 值 |
|------|----|
| Name | `svc_web_admin` |
| Identifier | `svc_web_admin` |
| Deployment Type | Kubernetes |
| Image Path | `tunxiang/web-admin` |
| Manifests Path | `gitops/web-admin/` |

#### Service 3: svc_tx_agent（tx-brain Agent服务）

| 字段 | 值 |
|------|----|
| Name | `svc_tx_agent` |
| Identifier | `svc_tx_agent` |
| Deployment Type | Kubernetes |
| Image Path | `tunxiang/tx-brain` |
| Manifests Path | `gitops/tx-brain/` |

**Service Variables**:
- `AGENT_MODEL`: `deepseek-v3`（可通过Feature Flag切换）
- `MAX_CONTEXT_TOKENS`: `32000`

#### Service 4: svc_tx_trade（交易服务）

| 字段 | 值 |
|------|----|
| Name | `svc_tx_trade` |
| Identifier | `svc_tx_trade` |
| Deployment Type | Kubernetes |
| Image Path | `tunxiang/tx-trade` |
| Manifests Path | `gitops/tx-trade/` |

### 2.4 Environments（6个）

**路径**: Deployments → Environments → + New Environment

| 名称 | Identifier | Type | 说明 |
|------|-----------|------|------|
| Dev | `env_dev` | PreProduction | 开发联调 |
| Test | `env_test` | PreProduction | 自动化测试 |
| UAT | `env_uat` | PreProduction | 验收测试 |
| Pilot | `env_pilot` | Production | 灰度试点（按 tenant 分流） |
| Prod | `env_prod` | Production | 全量生产 |
| Demo | `env_demo` | PreProduction | 售前演示 |

每个 Environment 需要添加以下 **Environment Variables**：
- `ENV_NAME`: 对应环境名（如 `dev`）
- `PG_URL`: 引用对应 `secret_pg_url_*`
- `REPLICA_COUNT`: dev=1, test=1, uat=2, pilot=2, prod=3

### 2.5 Infrastructure Definitions（6个）

每个 Environment 下创建对应的 Infrastructure Definition：

**路径**: Deployments → Environments → 点击对应 Env → Infrastructure → + New Infrastructure

| Environment | Infra Identifier | Connector | Namespace | Release Name |
|-------------|----------------|-----------|-----------|-------------|
| env_dev | `infra_dev` | k8s_dev_connector | tunxiang-dev | release-dev |
| env_test | `infra_test` | k8s_test_connector | tunxiang-test | release-test |
| env_uat | `infra_uat` | k8s_uat_connector | tunxiang-uat | release-uat |
| env_pilot | `infra_pilot` | k8s_pilot_connector | tunxiang-pilot | release-pilot |
| env_prod | `infra_prod` | k8s_prod_connector | tunxiang-prod | release-prod |
| env_demo | `infra_demo` | k8s_dev_connector | tunxiang-demo | release-demo |

### 2.6 User Groups（4个）

**路径**: Account Settings → User Groups → + New User Group（或 Project Settings）

| User Group | Identifier | 成员 | 用途 |
|-----------|-----------|------|------|
| QA Group | `qa_group` | QA人员（暂时为创始人） | 触发Test/UAT流水线，查看测试报告 |
| Product Group | `product_group` | 产品人员 | 只读访问，Feature Flag管理 |
| Release Manager Group | `release_manager_group` | 创始人 | 审批生产发布，操作Pilot/Prod |
| SRE Group | `sre_group` | 创始人 | 故障响应，基础设施管理 |

> **注意**: 当前为单人开发，以上4个 User Group 均为同一人（创始人），但预建好组织结构，方便未来团队扩张时直接调整。

### 2.7 Roles + Resource Groups（RBAC）

**路径**: Project Settings → Access Control → Roles

创建以下角色并绑定 Resource Group：

| Role | 权限说明 | 绑定 User Group |
|------|---------|----------------|
| Pipeline Executor | 执行流水线，查看日志 | qa_group, product_group |
| Pipeline Approver | 审批流水线（Migration/Release Approval） | release_manager_group |
| Environment Viewer | 只读查看所有 Environment | product_group |
| Environment Admin (Non-Prod) | 管理 dev/test/uat/demo 环境 | qa_group, sre_group |
| Environment Admin (Prod) | 管理 pilot/prod 环境 | release_manager_group, sre_group |
| Feature Flag Manager | 创建/修改/关闭 Feature Flag | product_group, release_manager_group |
| Full Admin | 所有权限 | sre_group（创始人自己） |

---

## 第三节：YAML 文件导入说明

### 3.1 目录结构与 Harness 对象对应关系

```
.harness/
├── pipelines/          → Deployments > Pipelines
│   ├── ci-api-gateway.yaml
│   ├── cd-api-gateway.yaml
│   └── feature-flag-sync.yaml
├── templates/          → Templates（Step/Stage模板）
│   └── approval-stage.yaml
├── triggers/           → Triggers
│   └── pr-trigger.yaml
└── policy/             → Governance > Policies
    ├── ccm-nonprod-schedule.yaml  （手动配置，非直接import）
    ├── cost-budget.yaml           （手动配置）
    └── opa-policies.yaml          → Governance > Policies > New Policy
```

### 3.2 如何导入 Pipeline YAML

**方法一：通过界面导入**
1. Deployments → Pipelines → + Create Pipeline
2. 选择 `Import from Git`
3. Git Connector: `github_connector`
4. Repository: `tunxiang-os`
5. Branch: `main`
6. YAML Path: `.harness/pipelines/ci-api-gateway.yaml`
7. Pipeline Name 自动从 YAML 读取

**方法二：Harness CLI（推荐批量操作）**
```bash
# 安装 Harness CLI
curl -LO https://app.harness.io/storage/harness-download/harness-cli/release/latest/bin/linux/amd64/harness
chmod +x harness

# 登录
harness login --api-key <your-api-key> --account-id <account-id>

# 导入所有 pipeline
for f in .harness/pipelines/*.yaml; do
  harness pipeline import --file "$f" --project tunxiang-os --org tunxiang-org
done
```

### 3.3 引用关系说明

YAML 中的 `connectorRef` / `serviceRef` / `environmentRef` 必须与 Harness 中已创建的对象 Identifier 完全一致：

```yaml
# 示例: cd-api-gateway.yaml 中的引用
serviceConfig:
  serviceRef: svc_api_gateway          # 必须与 Service Identifier 一致
environmentRef: env_dev                 # 必须与 Environment Identifier 一致
infrastructure:
  infrastructureRef: infra_dev          # 必须与 Infrastructure Definition Identifier 一致
connectorRef: harbor_connector          # 必须与 Connector Identifier 一致
```

### 3.4 常见错误排查

| 错误信息 | 原因 | 解决方案 |
|---------|------|---------|
| `Connector [xxx] not found` | Connector 未创建或 Identifier 拼写错误 | 检查 Connector Identifier，注意大小写 |
| `Service [xxx] not found` | Service 未创建 | 按 2.3 节创建 Service |
| `Environment [xxx] not found` | Environment 未创建 | 按 2.4 节创建 Environment |
| `Secret not accessible` | Secret 作用域不包含当前 Project | 检查 Secret 的 Scope，确保 Project 可访问 |
| `Infrastructure Definition not found` | Infra Definition 未在对应 Environment 下创建 | 确认在正确的 Environment 下创建了 Infra |
| `Pipeline validation failed: imageTag required` | OPA 策略阻止：生产发布缺少 imageTag | 在 Pipeline Run 前设置 `imageTag` 变量 |

---

## 第四节：验证清单

### 4.1 CI 流水线验证

```bash
# 1. 提交一个小改动触发 CI
git commit --allow-empty -m "test: trigger CI"
git push origin main

# 2. 在 Harness 界面确认
# Builds > ci-api-gateway > 最新执行 > 状态应为 Success
```

- [ ] CI 流水线在 push 到 main 后自动触发
- [ ] Build Stage 能成功拉取代码（github_connector 正常）
- [ ] Docker Build 能成功，镜像推送到 Harbor（harbor_connector 正常）
- [ ] 测试 Stage 能运行并输出测试结果
- [ ] CI 完成后触发通知到企微

### 4.2 CD 流水线验证（dev 环境）

- [ ] 手动触发 `cd-api-gateway` 到 dev 环境
- [ ] imageTag 设置为最新 CI 产物的 tag（如 `v0.1.0-abc1234`）
- [ ] K8s Deploy Stage 正常执行（k8s_dev_connector 正常）
- [ ] Pod 在 tunxiang-dev namespace 下正常 Running
- [ ] 健康检查通过
- [ ] Rollout 完成，无 CrashLoopBackOff

### 4.3 审批流验证

- [ ] 手动触发 `cd-api-gateway` 到 pilot 环境
- [ ] 流水线在 `Migration_Approval` 阶段暂停
- [ ] 企微收到审批通知
- [ ] 点击审批通过后流水线继续执行
- [ ] 拒绝测试：拒绝后流水线标记为 Failed

### 4.4 回滚验证

- [ ] 部署一个已知正常版本到 dev
- [ ] 部署一个会失败的版本（如 tag 不存在）
- [ ] 确认 Kubernetes Rollout Undo 自动触发
- [ ] 确认回滚后 Pod 恢复到上一个正常版本
- [ ] 回滚通知发送到企微

### 4.5 OPA 策略验证

- [ ] 尝试对 prod 使用 `imageTag=latest`，应被 OPA 拒绝
- [ ] 尝试在 prod 发布时不设置 `migration_approved`，应被拒绝
- [ ] 设置 `has_rls_migration=true` 但不设置 `security_approved=true`，应被拒绝
- [ ] 正常合规的 prod 发布（设置所有必要变量）应能通过
