# 屯象OS Harness 配置目录说明

本目录（`.harness/`）包含屯象OS项目的所有 Harness CI/CD 配置文件，包括流水线（pipelines）、模板（templates）和触发器（triggers）。

---

## 目录结构

```
.harness/
├── README.md                          # 本文件
├── pipelines/                         # CI 流水线定义
│   ├── ci-api-gateway.yaml            # gateway 服务 CI
│   ├── ci-tx-agent.yaml               # tx-agent 服务 CI
│   ├── ci-tx-trade.yaml               # tx-trade 服务 CI
│   └── ci-web-admin.yaml              # web-admin 前端 CI
├── templates/                         # 可复用模板
│   ├── tpl-ci-python-service.yaml     # Python/FastAPI 服务 CI 模板（StepGroup）
│   └── tpl-ci-node-service.yaml       # Node/React 前端 CI 模板（StepGroup）
└── triggers/                          # 自动触发器
    ├── trigger-pr-api-gateway.yaml    # gateway PR 触发器
    ├── trigger-main-api-gateway.yaml  # gateway main 分支推送触发器
    ├── trigger-tag-release-api-gateway.yaml  # gateway Tag 发版触发器
    ├── trigger-pr-web-admin.yaml      # web-admin PR 触发器
    └── trigger-main-web-admin.yaml    # web-admin main 分支推送触发器
```

---

## 占位符说明

所有 YAML 文件中使用以下固定标识符，在 Harness 平台上需保持一致：

| 占位符 | 值 | 说明 |
|---|---|---|
| `projectIdentifier` | `TunXiangOS` | Harness 项目标识 |
| `orgIdentifier` | `default` | Harness 组织标识 |
| `connectorRef: github_connector` | GitHub 连接器 | 代码仓库连接，需在平台预建 |
| `connectorRef: harbor_connector` | Harbor 镜像仓库连接器 | 镜像推送，需在平台预建 |
| `repoName: tunxiang-os` | GitHub 仓库名 | 触发器绑定的仓库 |

### Stage Variables（流水线变量）

各流水线通过 `stage.variables` 传入服务路径等信息，模板通过表达式引用：

| 变量名 | 说明 | 示例值 |
|---|---|---|
| `<+stage.variables.servicePath>` | 服务/应用在仓库中的相对路径 | `services/gateway` |
| `<+stage.variables.imageRepo>` | Harbor 镜像仓库路径 | `tunxiang/api-gateway` |
| `<+stage.variables.dockerfile>` | Dockerfile 路径（Python服务用） | `services/gateway/Dockerfile` |

### 运行时表达式

| 表达式 | 说明 |
|---|---|
| `<+codebase.shortCommitSha>` | Git commit SHA（短） |
| `<+pipeline.sequenceId>` | 流水线运行序号 |

---

## 在 Harness 平台上使用前需预建的对象

在将本目录的 YAML 同步到 Harness 之前，请确保以下资源已在 Harness 平台（项目 `TunXiangOS` / 组织 `default`）中创建完毕：

### Connectors（连接器）

1. **`github_connector`**
   - 类型：GitHub
   - 用途：代码仓库拉取、触发器绑定
   - 权限：需要 `repo` 和 `admin:repo_hook` 权限

2. **`harbor_connector`**
   - 类型：Docker Registry（Harbor）
   - 用途：构建镜像推送
   - 权限：需要 Harbor 项目 `tunxiang` 的 push 权限

### Environments（环境）

以下环境标识符在 CD 流水线（本目录暂未包含）中引用：

| 标识符 | 说明 |
|---|---|
| `env_staging` | 预发/灰度环境 |
| `env_production` | 生产环境 |

### Infrastructure Definitions（基础设施定义）

CD 流水线所需，与环境绑定，CI 阶段暂不涉及。

### Secrets（密钥）

以下 Secret 需在 Harness Secret Manager 中创建：

| Secret 标识符 | 说明 |
|---|---|
| `harbor_username` | Harbor 登录用户名 |
| `harbor_password` | Harbor 登录密码 |

---

## 模板使用说明

### Python 服务流水线引用 Python 模板

```yaml
steps:
  - step:
      template:
        templateRef: tpl_ci_python_service
        versionLabel: v1
        templateInputs:
          type: StepGroup
```

### Node 前端流水线引用 Node 模板

```yaml
steps:
  - step:
      template:
        templateRef: tpl_ci_node_service
        versionLabel: v1
        templateInputs:
          type: StepGroup
```

---

## 架构安全红线（来自 feedback_dev_constraints）

所有 CI 流水线必须包含以下检查，缺一不可：

- **Lint**：Python 服务用 `ruff`，前端用 `pnpm lint`（ESLint）
- **类型检查**：前端用 `tsc --noEmit`
- **安全扫描**：`git-secrets --scan`（Python 服务）
- **单元测试**：`pytest`（Python），`pnpm test`（前端，按需）
- **Migration检查**：Python 服务检查新增 alembic migration 文件

---

*最后更新：2026-04-06，屯象OS Team A*
