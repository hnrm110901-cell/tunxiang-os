# 屯象 DevForge 研运平台 · 开发计划明细 V1

> 制定日期：2026-04-27
> 适用周期：MVP → V3，约 6 个月
> 设计来源：`/Users/lichun/Library/.../outputs/Forge管理后台_菜单与UI设计.md` + `Forge_UI_Mockup.html`
> 关键约束：本计划遵循 [CLAUDE.md](../CLAUDE.md) 项目宪法 V3.0

---

## 〇、命名与定位说明

**命名冲突处置**：
- 现仓 `apps/web-forge-admin/` + `services/tx-forge/`（v3.0 已交付）= **AI Agent Exchange 市场后台**（ISV 视角）
- 本计划 `apps/web-devforge/` + `services/tx-devforge/`（待建）= **屯象内部研运一体化平台**（GitLab+ArgoCD+Backstage+Spinnaker 类，研发视角）

两个产品**不合并**：受众不同（外部 ISV vs 内部研发）、节奏不同（市场化 vs 工程化）、数据模型不同。

**定位**：把 14 微服务 + 16 客户端 + N 个门店边缘 + 10 类适配器 + 229 迁移 全部可治理、可追溯、可回滚。

**数据校正**（与设计文档差异）：
| 项 | 设计文档 | 实际 |
|---|---|---|
| 微服务数 | 18 | 21（含 gateway / 14 tx-* 主域 / tx-pay / tx-expense / tx-predict / tx-forge / tx-devforge / mcp-server / tunxiang-api）|
| 客户端数 | 18 | 18（13 web/h5 + 2 miniapp + 2 android + 1 ios + 1 windows-pos） |
| 迁移数 | 256 | 实测 409 个版本文件（含旧 `0001_*.py` + 新 `vNNN_*.py` 双格式，head=`v365_forge_ecosystem_metrics`，本计划新表从 **v366** 起接续，避开 v230 多版本占用冲突） |
| 适配器数 | 15 | 13 类（pinzhi/aoqiwei/keruyun/yiding/weishenghuo/meituan-saas/douyin/eleme/xiaohongshu/tiancai-shanglong/nuonuo/erp/logistics） |

---

## 一、技术选型（与 CLAUDE.md 对齐）

| 层 | 选型 | 理由 |
|---|---|---|
| 前端 | React 18 + TS strict + Vite + Zustand + TanStack Query | 与现有 16 个前端应用一致 |
| UI 库 | **Ant Design v5**（替代设计文档中的 Arco） | 现仓 web-admin / web-forge-admin 已沉淀 AntD 体系 |
| 图表/拓扑 | ECharts + AntV G6 | 拓扑图、桑基图、力导向 |
| 编辑器 | Monaco + xterm.js | 日志/YAML/SQL |
| 后端 | FastAPI + SQLAlchemy 2.0 + asyncpg + Pydantic v2 | 与 14 微服务一致 |
| 事件 | 复用 `shared/events` 总线（v147 起） | 所有研运动作 = 事件 |
| 部署 | 与现有 docker-compose / Helm 同构 | 不新增编排体系 |
| 端口 | tx-devforge `:8017` | 8015/8016 已被 tx-expense/tx-pay 占用，实际分配 8017 |

---

## 二、模块 → 现有资产映射 + 优先级

| # | 模块 | 现有资产 | 缺口 | Tier | 阶段 |
|---|---|---|---|---|---|
| 01 | 工作台 Dashboard | 无 | 全新 | T3 | MVP |
| 02 | 应用中心 Apps | services/* + apps/* + edge/* + shared/adapters | 资源元数据库 + 统一 Owner/SLO 模型 | T2 | **MVP** |
| 03 | 代码协作 Source | GitHub | API 拉取 + 镜像化 | T3 | V1 |
| 04 | 流水线 Pipeline | .github/workflows/* (8 个) | 统一编排 + 结果聚合 | T2 | **MVP** |
| 05 | 制品库 Artifact | Docker Registry + npm/pypi | 元数据中台 + 晋升通道 | T2 | **MVP** |
| 06 | 测试中心 Test | 现有 pytest + Playwright 任务 | 用例库 + PR 环境 | T2 | V1 |
| 07 | 部署中心 Deploy | docker-compose.{prod,staging,gray}.yml + Helm × 11 | 工单 + 可视化编排 | **T1** | **MVP** |
| 08 | 灰度发布 Release ⭐ | flags/ + shared/feature_flags | 餐饮维度切流 + 熔断 | **T1** | **MVP** |
| 09 | 配置中心 Config | shared/feature_flags + 各服务 .env | 配置服务 + KMS 引用 | T2 | V1 |
| 10 | 可观测 Observe | infra/monitoring (Prometheus+Grafana+Loki) + 2 dashboards + alerts.yml | SLO 看板 + 业务指标 | T2 | V1 |
| 11 | 边缘门店 Edge ⭐ | edge/{mac-station, coreml-bridge, sync-engine, mac-mini} | 上报 Agent + OTA + 地图 | **T1** | V1 |
| 12 | 数据治理 Data | shared/db-migrations (229 版) + Alembic | 迁移拓扑 + 慢 SQL | **T1** | V2 |
| 13 | 集成中心 Integration | shared/adapters (10 类) | 适配器实例监控 + 凭证保险箱 | T2 | V2 |
| 14 | 安全审计 Security | services/tx-civic 已有合规评分 | 审计中台 + Kill Switch | **T1** | V2 |
| 15 | 系统 System | gateway 有 auth + brand_switcher | RBAC + SSO | T2 | MVP |

---

## 三、后端 services/tx-devforge 工程结构

```
services/tx-devforge/                            # FastAPI :8017（8015/8016 被 tx-expense/tx-pay 占）
  src/
    models/                                      # ~30 SQLAlchemy 实体
      app_catalog.py                             #   Application/Component（5类资源统一模型）
      pipeline.py                                #   Pipeline / Run / Stage / Step
      artifact.py                                #   Artifact / Tag / Promotion
      deployment.py                              #   Deployment / Environment / Order
      release.py                                 #   Release / Strategy / GraySegment / Gate
      config_item.py                             #   Config / Secret / FeatureFlag
      slo.py                                     #   SLO / SLI / ErrorBudget
      edge_device.py                             #   Store / Device / OTABundle
      migration_meta.py                          #   MigrationGraph / RiskLevel / RollbackSQL
      integration.py                             #   IntegrationInstance / Credential / CallbackLog
      audit.py                                   #   AuditLog (WORM) / KillSwitch / Vulnerability
      iam.py                                     #   User / Role / Policy / Token
    api/
      app_routes.py        catalog_routes.py     pipeline_routes.py
      artifact_routes.py   deploy_routes.py      release_routes.py
      config_routes.py     observe_routes.py     edge_routes.py
      data_routes.py       integration_routes.py audit_routes.py
      iam_routes.py        webhook_routes.py
    services/                                    # 业务领域服务
      pipeline_runner.py                         #   GitHub Actions / Harness 适配
      release_orchestrator.py                    #   切流/熔断核心
      ota_dispatcher.py                          #   边缘 OTA 推送
      config_dispatcher.py                       #   配置下发 + 灰度
      kill_switch.py                             #   秒级关停
    integrations/                                # 外部系统对接
      github_actions.py    harness.py
      docker_registry.py   prometheus.py        loki.py        tempo.py
      grafana_proxy.py     kms_client.py        tailscale_api.py
    projectors/                                  # 事件总线投影器（基于 v147）
      release_projector.py                       #   RELEASE.* → mv_release_health
      deploy_projector.py                        #   DEPLOY.* → mv_deploy_history
      audit_projector.py                         #   * → mv_audit_trail (WORM)
    main.py
  Dockerfile
  alembic/                                       # 新增迁移 v230-v245
```

### 新增数据库迁移（v366-v381，共 ~16 版）

> 原计划 v230-v245，因 v230 已被 `agent_registry_tables` + `rls_nullif_backfill` 占用，统一改从 head=v365 之后的 v366 起接续。

| 版本 | 表 | 说明 |
|---|---|---|
| v366 | `devforge_applications` | 5 类资源统一目录（已交付） |
| v367 | `devforge_component_relations` | 依赖拓扑边 |
| v368 | `devforge_pipelines` + `devforge_pipeline_runs` | 流水线 |
| v369 | `devforge_artifacts` + `devforge_artifact_promotions` | 制品库 |
| v370 | `devforge_environments` + `devforge_deployment_orders` | 部署工单 |
| v371 | `devforge_releases` + `devforge_release_segments` + `devforge_release_gates` | 灰度发布 |
| v372 | `devforge_config_items` + `devforge_config_revisions` | 配置中心 |
| v373 | `devforge_secret_refs` | 密钥引用（不存明文） |
| v374 | `devforge_feature_flags` + `devforge_flag_assignments` | 特性开关 |
| v375 | `devforge_slos` + `devforge_error_budgets` | SLO |
| v376 | `devforge_edge_devices` + `devforge_ota_bundles` + `devforge_ota_tasks` | 边缘 |
| v377 | `devforge_migration_meta` | 迁移图谱 |
| v378 | `devforge_integration_instances` + `devforge_callback_logs` | 集成中心 |
| v379 | `devforge_audit_logs`（WORM 表） | 审计 |
| v380 | `devforge_kill_switches` | 紧急关停 |
| v381 | `devforge_iam_*`（user/role/policy/token） | RBAC |

**所有表强制 `tenant_id` + RLS**（CLAUDE.md 第十四条）。审计表用 `INSERT-only` 触发器禁止 UPDATE/DELETE 实现 WORM。

---

## 四、前端 apps/web-devforge 工程结构

```
apps/web-devforge/                               # Vite + React 18 + AntD v5
  src/
    layout/
      AppLayout.tsx                              # 240px 侧栏 + 56px 顶栏
      EnvSwitcher.tsx                            # dev/test/staging/gray/prod，prod 红框
      GlobalSearch.tsx                           # ⌘K
      EnvFreezeBanner.tsx                        # 高峰期/冻结期提示
    pages/
      dashboard/                                 # 01 工作台
      apps/                                      # 02 应用中心
        ServicesList / ClientsList / EdgeList / AdaptersList / DataAssetsList
        AppDetail/{Overview,Deps,Versions,Pipelines,Config,Monitor,Alerts,Docs}.tsx
      source/                                    # 03 代码协作
      pipeline/                                  # 04 流水线
        PipelineList / RunDetail / TemplateGallery / ActionsBoard / HarnessBoard
      artifact/                                  # 05 制品库
        DockerView / WheelView / ApkView / IpaView / DmgView / MiniappView
        ArtifactDetail (SBOM + 漏洞 + 晋升路径)
      test/                                      # 06 测试中心
      deploy/                                    # 07 部署中心
        EnvMatrix / DeployOrder / OrchestrationCanvas / RollbackCenter
      release/                                   # 08 灰度发布 ⭐
        ReleaseList / StrategyEditor (G6 画布) / LiveDashboard / GateConfig
        StoreSelector (高德地图选店) / TimeWindowPicker (避开高峰)
      config/                                    # 09 配置中心
      observe/                                   # 10 可观测
        UnifiedQuery / SloBoard / BusinessKpiBoard / AlertConsole / TopologyView
      edge/                                      # 11 边缘门店 ⭐
        StoreMap (高德) / DeviceList / DeviceDetail / OtaTaskCenter / OnboardingWizard
      data/                                      # 12 数据治理
        MigrationGraph / SchemaBrowser / DdlOrder / SlowSqlBoard
      integration/                               # 13 集成中心
        PlatformCatalog / InstanceMonitor / CredentialVault / CallbackReplay / Reconciliation
      security/                                  # 14 安全审计
        AuditTimeline / VulnBoard / ComplianceCheck / KillSwitchPanel
      system/                                    # 15 系统
        Users / Roles / Teams / SsoConfig / Tokens / Notifications
    components/
      ResourceCard / HealthDot / EnvBadge / RiskBadge / DangerConfirm
      LogStream (xterm) / YamlEditor (monaco) / SqlEditor (monaco)
      TopologyGraph (G6) / ReleasePieChart (echarts) / ErrorBudgetBurnup
    api/                                         # 与 tx-devforge 1:1
    stores/                                      # Zustand: env / user / layout
    hooks/
    router.tsx                                   # 15 一级路由
```

---

## 五、按阶段开发明细（MVP → V3）

### **MVP（第 1-2 月，约 8 周）— 闭环最小研发流**

> 目标：让 14 微服务 + 16 客户端的代码能在 DevForge 上"看见 → 构建 → 部署 → 灰度"。

**M1（第 1-3 周）— 骨架与应用中心 + 系统**
- W1 项目脚手架：`apps/web-devforge` + `services/tx-devforge` 初始化，Docker Compose 接入，`/health` 通跑
- W1 数据库 v230-v231 + v245 迁移，AppLayout + EnvSwitcher + GlobalSearch
- W2 **02 应用中心**：5 类资源统一目录页，从 services/、apps/、edge/、shared/adapters/ 自动扫描注册（一次性脚本 + 后续 webhook）
  - 应用详情页 8 个 Tab 中先实现：概览 / 依赖拓扑 / 版本历史 / 文档（README 自动同步）
- W3 **15 系统**：RBAC + Token + 企业微信 SSO（gateway 已有 auth 基础，扩展即可）

**M2（第 4-5 周）— 流水线 + 制品库**
- W4 数据库 v232-v233，**04 流水线**：
  - GitHub Actions API 拉取（8 个 workflow 全收编）
  - Webhook 反向通知 Run 结果
  - 列表 + 实时日志（xterm 流式）+ 阶段图
  - 5 套官方模板（Python 服务 / TS 前端 / iOS / Android / Mac 桌面）落地
- W5 **05 制品库**：
  - Docker / Wheel / APK / IPA / DMG / Miniapp 6 类视图
  - SBOM + Trivy 扫描结果（异步任务）
  - 晋升通道 test → gray → prod（手动按钮 + 审批流）

**M3（第 6-8 周）— 部署 + 灰度（基础）**
- W6 数据库 v234，**07 部署中心**：
  - 解析现有 `infra/docker/docker-compose.{prod,staging,gray}.yml` → 环境矩阵可视化
  - 部署工单四态：申请 → 审批 → 执行 → 回滚
  - 实时部署日志，回滚一键到任意历史版本
- W7-W8 数据库 v235，**08 灰度发布（基础）**：
  - 发布单 = N 服务 + M 客户端协同
  - 灰度维度先做 4 个：按门店 / 按城市 / 按比例 / 按时段（餐饮高峰禁推校验）
  - 蓝绿 + 金丝雀两种策略
  - 实时看板：流量饼图 + 错误率对比 + GMV 对比（接 tx-finance 实时指标）
  - **熔断**：错误率 > 0.1% 自动停滚（**Tier 1，必须 TDD**）
  - 一键回滚（全量 + 按门店分批）

**MVP 验收门槛**：
- [ ] `tx-trade` 服务能从 DevForge 触发流水线 → 产出镜像 → 部署到 staging → 按 1 家门店灰度 → 一键回滚
- [ ] 所有操作留痕到 `devforge_audit_log`，事件总线 `RELEASE.STARTED/COMPLETED/ROLLED_BACK` 落库
- [ ] Tier 1 用例覆盖：熔断、回滚、跨租户隔离、高峰期禁推
- [ ] P99 < 200ms（DEMO 环境压测）

---

### **V1（第 3-4 月）— 上线后必要治理**

**M4（第 9-11 周）— 配置中心 + 可观测**
- 数据库 v236-v239
- **09 配置中心**：配置项三维（命名空间×环境×集群）、KMS 密钥引用、Feature Flag 与 shared/feature_flags 双向同步、变更审计
- **10 可观测**：
  - 嵌入现有 Grafana iframe（`infra/monitoring/`），但导航在 DevForge 内
  - SLO 看板（每服务可用性/延迟/错误预算燃尽，从 Prometheus 算）
  - 业务指标看板：下单成功率、KDS 出餐时延、POS 离线时长（接 mv_store_pnl 等物化视图）
  - 告警规则编辑器（Prometheus rules 可视化编辑）
  - 拓扑视图（G6 力导向，从依赖关系反推）

**M5（第 12-14 周）— 测试中心 + 边缘门店（基础）**
- 数据库 v240
- **06 测试中心**：用例库（对齐现有 7K+ 测试）、Playwright 任务调度、PR 环境（每 MR 自动拉一套 docker-compose 子环境）、k6 压测调度
- **11 边缘门店（基础）**：
  - 门店地图（高德 SDK）+ 健康度色块
  - 设备清单 + 详情（CPU/内存/磁盘/PG 副本延迟/Core ML 推理状态）
  - 上报 Agent 在 `edge/mac-mini/` 新增 `agent_reporter.py`，每 60s 上报指标到 tx-devforge

---

### **V2（第 5-6 月）— 餐饮场景护城河**

**M6（第 15-17 周）— 灰度高级 + 边缘 OTA**
- **08 灰度发布（高级）**：A/B 实验、按客流量分群（接 mv_store_pnl）、按门店类型（直营/加盟/旗舰）、复合指标熔断（GMV + 错误率 + 延迟三维）
- **11 边缘 OTA**：批量推送边缘镜像、断网续传、失败回滚、开业向导（新门店 0→1 自动化交付清单）

**M7（第 18-20 周）— 数据治理 + 集成中心**
- 数据库 v241-v242
- **12 数据治理**：229 个 Alembic 迁移可视化为 DAG，标注风险等级与回滚 SQL；DDL 走工单审批；接 pg_stat_statements 做慢 SQL Top N
- **13 集成中心**：10 个 adapter 实例运行状态监控；凭证保险箱（appKey/token 加密 + 自动轮换）；回调日志失败重放（接 v147 事件总线 `CHANNEL.ORDER_SYNCED`）；三方对账报表

---

### **V3（持续）— 安全与 AI**

**M8（第 21-24 周）— 安全审计**
- 数据库 v243-v244
- **14 安全审计**：审计日志（WORM）、依赖 CVE 看板、合规检查项（GDPR/等保）、Kill Switch（秒级关停某服务/某门店/某第三方接入）

**M9（持续）— AI 辅助（与屯象 Agent OS 对接）**
- Agent 辅助根因定位：告警 → 日志/链路自动归因（调用 tx-brain Claude API）
- Agent 辅助发布建议：基于历史发布数据 + 当前业务指标推荐灰度比例与时间窗口
- 与 tx-agent 9 大 Skill Agent 复用决策留痕模型（`AgentDecisionLog`）

---

## 六、关键技术决策

### 6.1 资源元数据自动发现
不让运维填表。在 CI 步骤里加 `forge-register` 命令，扫描仓库自动写入 `devforge_application`：
- 后端服务：扫 `services/*/main.py` + `services/*/Dockerfile`
- 前端：扫 `apps/*/package.json`
- 边缘：扫 `edge/*/`
- 适配器：扫 `shared/adapters/*/`
- 迁移：扫 `shared/db-migrations/versions/*.py` 解析依赖关系生成 DAG

### 6.2 灰度策略 = 可执行的事件
所有切流动作发到事件总线（v147）：
```python
ReleaseEventType.SEGMENT_OPENED  # 某门店进入新版本
ReleaseEventType.GATE_FAILED     # 熔断触发
ReleaseEventType.ROLLBACK_DONE
```
Agent 端订阅事件 → 自动告警；分析端投影到 `mv_release_health`。

### 6.3 与现有 16 个客户端、14 服务的对接零侵入
所有应用通过**配置文件** `forge.yml` 声明自己（Owner、SLO、依赖、Pipeline 模板），DevForge 反向读取，**不要求服务代码改造**。

### 6.4 复用现有，禁止重复造轮子

| 不重做 | 复用方式 |
|---|---|
| 镜像构建 | 沿用 GitHub Actions / Harness |
| 监控数据 | 嵌入 Grafana iframe + Prometheus API |
| 配置文件 | feature_flags 表双向同步，不迁移 |
| 数据库迁移执行 | 仍由 Alembic 跑，DevForge 只做编排和审计 |
| Agent 决策 | 复用 tx-agent，DevForge 不重做 AI |

---

## 七、Tier 分级与测试要求（按 CLAUDE.md 第十七条）

**Tier 1（零容忍，必须 TDD）：**
- 灰度熔断逻辑（错误率/延迟/GMV 三维触发）
- 一键回滚（全量 + 按门店分批，无半状态）
- 部署工单审批 + 跨租户隔离
- 边缘 OTA 失败回滚（断网 4h 重连后镜像状态正确）
- Kill Switch（秒级生效，影响范围可审计）
- WORM 审计表（INSERT-only，禁止改/删）

**Tier 1 验收用例样板（节选）：**
```python
class TestReleaseGateTier1:
    def test_gmv_drop_triggers_auto_stop(self):
        """灰度中 GMV 比基线下降 >5%，5 分钟内自动停滚"""
    def test_rollback_per_store_no_half_state(self):
        """按门店分批回滚 50 家中的 10 家，无 9 家中间态"""
    def test_kill_switch_propagates_under_60s(self):
        """Kill Switch 触发后 60s 内全网生效，事件全留痕"""
    def test_audit_log_worm_reject_update(self):
        """对 devforge_audit_log 执行 UPDATE 必须被触发器拒绝"""
```

**Tier 2**：流水线、配置中心、SLO、设备清单
**Tier 3**：仪表盘、文档同步、贡献分析

---

## 八、人力与里程碑

| 阶段 | 周期 | 后端人日 | 前端人日 | 测试人日 | 关键交付 |
|---|---|---|---|---|---|
| MVP | 8 周 | 40 | 50 | 15 | 应用中心 / 流水线 / 制品库 / 部署 / 基础灰度 |
| V1 | 8 周 | 30 | 35 | 10 | 配置 / 可观测 / 测试 / 边缘基础 |
| V2 | 8 周 | 25 | 25 | 10 | 高级灰度 / OTA / 数据治理 / 集成 |
| V3 | 持续 | 20 | 15 | 8 | 安全审计 / AI 辅助 |
| **合计** | **24 周** | **115** | **125** | **43** | 15 模块全量上线 |

按 2 后端 + 2 前端 + 1 测试配置，约 **6 个月**完成 MVP→V2，V3 持续迭代。

---

## 九、Day-1 启动任务

1. ✅ 本计划落档为 `docs/devforge-platform-plan.md`
2. 创建 `services/tx-devforge` 骨架（FastAPI + 端口 8017 + 接入 gateway 路由代理）
3. 创建 `apps/web-devforge` 骨架（Vite + AntD + AppLayout + EnvSwitcher + 15 模块路由占位）
4. 起草 v366 迁移：`devforge_application` 表 + RLS 策略（v230 已被占用，新表从 v366 起接续）
5. 写 `scripts/forge_register_resources.py`：一次性扫描全仓 5 类资源入库
6. 在 gateway 注册 tx-devforge `:8017` 反向代理
7. 在 `progress.md` 加一条 Tier 标注：本计划属 Tier 2 起步，08/07/11/14 模块为 Tier 1
