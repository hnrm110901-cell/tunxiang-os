# 屯象OS Harness 对象初始化核查表

> 版本: 1.0 | 最后更新: 2026-04-06
>
> 使用说明：按从上到下的顺序操作，完成一项打一个勾。
> 有依赖关系的对象必须在被依赖对象完成后再创建。

---

## Phase 1 必建对象（CI 底座）

### Secrets（优先级 P0，最先建）

> 路径: Project Settings → Secrets → + New Secret（或 Account Settings → Secrets）

**Account 级别 Secrets（所有 Project 可用）**

- [ ] `secret_github_pat` — GitHub Personal Access Token，需 `repo` + `workflow` 权限
- [ ] `secret_harbor_username` — Harbor CI 专用账号用户名
- [ ] `secret_harbor_password` — Harbor CI 专用账号密码

**Project 级别 Secrets**

- [ ] `secret_pg_url_dev` — Dev 环境 PostgreSQL 连接串
- [ ] `secret_pg_url_test` — Test 环境 PostgreSQL 连接串
- [ ] `secret_pg_url_uat` — UAT 环境 PostgreSQL 连接串
- [ ] `secret_pg_url_pilot` — Pilot 环境 PostgreSQL 连接串
- [ ] `secret_pg_url_prod` — **生产环境 PG 连接串（最高机密，限制访问）**
- [ ] `secret_wecom_webhook` — 企微机器人 Webhook URL（审批+告警）
- [ ] `secret_supabase_anon_key` — Supabase anon key（前端 SDK）
- [ ] `secret_supabase_service_key` — Supabase service role key（后端管理）
- [ ] `secret_jwt_secret` — JWT 签名密钥（32位+随机字符串）
- [ ] `secret_redis_password` — Redis 认证密码
- [ ] `secret_smtp_password` — 邮件发送 SMTP 密码（告警邮件用）

---

### Connectors（优先级 P0）

> 路径: Project Settings → Connectors → + New Connector

**代码仓库**
- [ ] `github_connector` — GitHub App 认证，指向 tunxiang-os 仓库
  - 类型: GitHub
  - 认证: GitHub App 或 PAT（使用 account.secret_github_pat）
  - 测试连接: 必须通过

**镜像仓库**
- [ ] `harbor_connector` — Harbor 私有镜像仓库
  - 类型: Docker Registry → Other
  - URL: https://registry.tunxiang.internal（替换为实际地址）
  - 认证: account.secret_harbor_username + account.secret_harbor_password
  - 测试连接: 必须通过

**K8s 集群（每个环境一个）**
- [ ] `k8s_dev_connector` — Dev 集群（namespace: tunxiang-dev）
- [ ] `k8s_test_connector` — Test 集群（namespace: tunxiang-test）
- [ ] `k8s_uat_connector` — UAT 集群（namespace: tunxiang-uat）
- [ ] `k8s_pilot_connector` — Pilot 集群（namespace: tunxiang-pilot）
- [ ] `k8s_prod_connector` — **生产集群（namespace: tunxiang-prod，限制访问）**

> 共 7 个 Connectors，全部完成后进入下一阶段

---

## Phase 2 必建对象（CD 底座）

### Services（优先级 P1）

> 路径: Deployments → Services → + New Service
> 依赖: github_connector（Manifests）+ harbor_connector（Artifact）

**Batch 1 核心服务（先建）**
- [ ] `svc_api_gateway` — API 网关服务
  - Artifact: tunxiang/api-gateway，tag: `<+pipeline.variables.imageTag>`
  - Manifests: gitops/api-gateway/（github_connector）
- [ ] `svc_web_admin` — 总部管理后台
  - Artifact: tunxiang/web-admin
  - Manifests: gitops/web-admin/
- [ ] `svc_tx_agent` — tx-brain Agent 服务
  - Artifact: tunxiang/tx-brain
  - Manifests: gitops/tx-brain/
  - 变量: AGENT_MODEL=deepseek-v3，MAX_CONTEXT_TOKENS=32000
- [ ] `svc_tx_trade` — 交易核心服务
  - Artifact: tunxiang/tx-trade
  - Manifests: gitops/tx-trade/

**Batch 2 服务（次优先级）**
- [ ] `svc_pos_server` — POS 服务端
- [ ] `svc_kds` — KDS 出餐屏服务
- [ ] `svc_member` — 会员服务
- [ ] `svc_supply_chain` — 供应链服务
- [ ] `svc_report` — 报表服务

**Batch 3 服务（低优先级）**
- [ ] `svc_notification` — 通知服务（短信/企微）
- [ ] `svc_scheduler` — 定时任务服务
- [ ] `svc_audit_log` — 审计日志服务

---

### Environments（优先级 P1）

> 路径: Deployments → Environments → + New Environment

- [ ] `env_dev` — 类型: PreProduction，变量: ENV_NAME=dev，REPLICA_COUNT=1
- [ ] `env_test` — 类型: PreProduction，变量: ENV_NAME=test，REPLICA_COUNT=1
- [ ] `env_uat` — 类型: PreProduction，变量: ENV_NAME=uat，REPLICA_COUNT=2
- [ ] `env_pilot` — 类型: **Production**，变量: ENV_NAME=pilot，REPLICA_COUNT=2
- [ ] `env_prod` — 类型: **Production**，变量: ENV_NAME=prod，REPLICA_COUNT=3
- [ ] `env_demo` — 类型: PreProduction，变量: ENV_NAME=demo，REPLICA_COUNT=1

---

### Infrastructure Definitions（优先级 P1）

> 路径: 对应 Environment 下 → Infrastructure → + New Infrastructure
> 依赖: K8s Connectors + Environments

- [ ] `infra_dev` — env_dev 下，connector: k8s_dev_connector，namespace: tunxiang-dev
- [ ] `infra_test` — env_test 下，connector: k8s_test_connector，namespace: tunxiang-test
- [ ] `infra_uat` — env_uat 下，connector: k8s_uat_connector，namespace: tunxiang-uat
- [ ] `infra_pilot` — env_pilot 下，connector: k8s_pilot_connector，namespace: tunxiang-pilot
- [ ] `infra_prod` — env_prod 下，connector: k8s_prod_connector，namespace: tunxiang-prod
- [ ] `infra_demo` — env_demo 下，connector: k8s_dev_connector，namespace: tunxiang-demo

---

## Phase 3 必建对象（流水线 + 审批）

### Pipelines（优先级 P1）

> 路径: Deployments → Pipelines → + Create Pipeline（从 Git 导入）

**CI 流水线**
- [ ] `ci-api-gateway` — 来源: .harness/pipelines/ci-api-gateway.yaml
- [ ] `ci-web-admin` — 来源: .harness/pipelines/ci-web-admin.yaml
- [ ] `ci-tx-brain` — 来源: .harness/pipelines/ci-tx-brain.yaml

**CD 流水线**
- [ ] `cd-api-gateway` — 多阶段: dev → test → uat → pilot → prod（含审批）
- [ ] `cd-web-admin` — 同上
- [ ] `cd-tx-brain` — 同上，prod 部署需额外 AI 安全审查

**特殊流水线**
- [ ] `db-migration-only` — 仅执行 DB 迁移（无应用部署），用于数据库变更
- [ ] `rollback-prod` — 生产环境快速回滚流水线（输入: 目标版本tag）
- [ ] `feature-flag-sync` — 同步 flags/ 目录下的 Flag YAML 到 Harness FF

---

### Templates（优先级 P1）

> 路径: Project Settings → Templates（或流水线编辑器中保存 Stage 为 Template）

- [ ] `migration-approval-stage` — DB 迁移审批阶段模板（在多个流水线中复用）
  - 包含: 企微通知 + 人工审批 Step
- [ ] `k8s-rolling-deploy-step` — 标准 K8s Rolling Update Step 模板
- [ ] `smoke-test-step` — 部署后冒烟测试 Step 模板

---

### Triggers（优先级 P1）

> 路径: Pipeline 详情页 → Triggers → + New Trigger

- [ ] `trigger_pr_ci` — PR 触发 CI（事件: PR Open/Reopen/Sync）
- [ ] `trigger_main_push_ci` — main 分支 push 触发 CI
- [ ] `trigger_cd_dev_auto` — CI 成功后自动触发 CD 到 dev
- [ ] `trigger_schedule_cost_report` — 每月1日 00:10 触发成本报告（Cron: `10 0 1 * *`）

---

## Phase 4 必建对象（治理 + RBAC）

### User Groups（优先级 P2）

> 路径: Project Settings → Access Control → User Groups → + New User Group

- [ ] `qa_group` — QA/测试人员，有 Test/UAT 环境操作权限
- [ ] `product_group` — 产品人员，只读 + Feature Flag 管理
- [ ] `release_manager_group` — 发布负责人，审批生产发布
- [ ] `sre_group` — SRE/运维，基础设施全权限

---

### Roles（优先级 P2）

> 路径: Project Settings → Access Control → Roles → + New Role

- [ ] `pipeline_executor` — 执行流水线权限
- [ ] `pipeline_approver` — 审批流水线权限
- [ ] `env_admin_nonprod` — 非生产环境管理权限（dev/test/uat/demo）
- [ ] `env_admin_prod` — 生产环境管理权限（pilot/prod）
- [ ] `ff_manager` — Feature Flag 完整管理权限
- [ ] `readonly_viewer` — 只读查看所有对象

---

### RBAC 绑定（Role + User Group + Resource Group）

- [ ] qa_group → pipeline_executor → Resource: env_dev, env_test, env_uat
- [ ] qa_group → env_admin_nonprod → Resource: env_dev, env_test, env_uat
- [ ] product_group → readonly_viewer → All Resources
- [ ] product_group → ff_manager → Resource: Feature Flags
- [ ] release_manager_group → pipeline_approver → Resource: env_pilot, env_prod
- [ ] release_manager_group → env_admin_prod → Resource: env_pilot, env_prod
- [ ] sre_group → Full Admin → All Resources

---

### OPA Policies（优先级 P2）

> 路径: Project Settings → Governance → Policies → + New Policy

- [ ] `require_migration_approval` — 生产发布必须包含 Migration_Approval 阶段
  - 来源: .harness/policy/opa-policies.yaml 中的 require-migration-approval
- [ ] `no_prod_deploy_friday_night` — 禁止周五夜间生产发布
- [ ] `require_image_tag` — 生产发布禁止使用 latest 标签
- [ ] `rls_change_requires_security_review` — RLS 变更需安全审查
- [ ] `require_resource_limits` — Service 必须声明资源限制
- [ ] `no_plaintext_secrets_in_prod` — 生产 Connector 禁止明文密码

**创建 Policy Set（将 Policies 组合生效）**
- [ ] `prod_release_policy_set` — 绑定 P1 + P2 + P3，作用于所有 prod pipeline
  - 包含: require_migration_approval + require_image_tag + no_prod_deploy_friday_night
- [ ] `rls_security_policy_set` — 绑定 P4，作用于所有 pipeline
  - 包含: rls_change_requires_security_review

---

## Phase 5 必建对象（成本治理 + 通知）

### CCM（Cloud Cost Management）

- [ ] 配置 CCM AutoStopping Rules — 参考 .harness/policy/ccm-nonprod-schedule.yaml
  - 路径: Cloud Costs → AutoStopping Rules → + New Rule
  - [ ] dev-nightly-shutdown（工作日夜间停机）
  - [ ] test-weekend-shutdown（周末全停）
  - [ ] uat-idle-shutdown（4h无活动停）
  - [ ] demo-7day-cleanup（7天TTL）
- [ ] 配置 Cost Budgets — 参考 .harness/policy/cost-budget.yaml
  - [ ] tunxiang-monthly-total（月度总预算 3000元）
  - [ ] llm-api-monthly（LLM API 预算 500元）
  - [ ] nonprod-monthly（非生产预算 600元）

---

### Notifications（通知渠道）

- [ ] 企微通知渠道 — Webhook URL: secret_wecom_webhook
  - 路径: Project Settings → Notifications → + New Notification Method
- [ ] 邮件通知渠道 — SMTP 配置（成本超限时使用）
- [ ] 在每条 Pipeline 的关键阶段配置通知:
  - [ ] CI 失败 → 企微
  - [ ] CD 开始部署到 prod → 企微
  - [ ] 审批等待 → 企微
  - [ ] 部署失败/回滚 → 企微 + 邮件

---

## 完成标准

完成所有 Phase 的对象创建后，执行以下验证：

- [ ] 完整走通一次 PR → CI → CD to dev 的全链路
- [ ] 完整走通一次 CD to prod（含 Migration Approval 审批）
- [ ] 验证 OPA 策略能正确拦截不合规的 prod 发布
- [ ] 验证企微收到 CI/CD 关键节点通知
- [ ] 验证 CCM AutoStopping 能正常停止 dev 环境
- [ ] 验证月度成本报告脚本能生成报告

---

*核查表最后更新: 2026-04-06 | 屯象OS Harness 接入项目*
