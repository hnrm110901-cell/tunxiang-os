# scripts/ — 自动化脚本索引

> 屯象OS 的运维 / 安全 / 测试 / 部署 ad-hoc 脚本。新增脚本请把它分类登记到这里。

## 1. 安全 / 合规检查

| 脚本 | 用途 |
|------|------|
| `check_alembic_chain.py` | Alembic 链路完整性 + KNOWN_BROKEN 白名单守门（PJ.5） |
| `check_migrations.sh` | 迁移文件命名 / 危险 SQL（DROP/TRUNCATE） |
| `check_rls_policies.py` | RLS Policy 静态检查（多租户隔离） |
| `check_secrets.sh` | git-secrets 扫描入口 |
| `check_signoffs.sh` | 提交 sign-off 校验 |
| `check_tier1_pass.sh` | Tier 1 测试通过率门槛 |
| `security-scan.sh` | 综合安全扫描 |
| `setup-git-secrets.sh` | git-secrets 钩子初始化 |
| `setup-security-keys.sh` | 安全密钥初始化 |

## 2. 批量改写（codemod）

| 脚本 | 用途 |
|------|------|
| `codemod_safe_http_exception.py` | `HTTPException(detail=str(e))` → `safe_http_exception(...)`（P2.5 异常泄漏归一） |
| `codemod_utcnow.py` | `datetime.utcnow()` → `datetime.now(UTC)`（PG.2 时区归一） |
| `migrate_legacy_db.py` | 旧业务库到屯象 schema 数据迁移 |
| `migrate_pii_encryption.py` | PII 字段加密迁移 |

## 3. 部署 / 上线

| 脚本 | 用途 |
|------|------|
| `deploy.sh` / `deploy-pos.sh` | 主 / POS 子集部署 |
| `migrate.sh` | Alembic 升级入口 |
| `gray-release.sh` | 灰度发布编排 |
| `gate1-manual-ops.sh` | Gate1 人工操作 runbook |
| `release-gate.sh` | 发布门禁检查 |
| `rollback-service.sh` | 单服务回滚 |
| `build-mac-installer.sh` | Mac mini 边缘安装包 |
| `create-prod-env.sh` / `env-manager.sh` | 生产环境初始化 / 多环境管理 |
| `setup-nginx-apps.sh` | Nginx 站点配置 |
| `merchant-deploy-check.sh` | 商户上线前自检 |

## 4. Demo 演示环境

| 脚本 | 用途 |
|------|------|
| `create-demo-env.sh` / `demo_build_deploy.sh` / `demo_deploy.sh` / `demo-reset.sh` / `reset_demo.sh` / `demo_quick_start.sh` | demo 环境生命周期 |
| `demo_go_no_go.py` | demo Go/No-Go 自审 |
| `demo_prep_czyz.py` | 尝在一起 demo 数据准备 |
| `demo_seed.py` / `seed_demo_data.py` | demo 种子数据 |
| `seed_czyz.py` / `seed_zqx.py` / `seed_sgc.py` / `seed_xuji_data.py` / `seed_three_brands_stores.py` | 三品牌 / 徐记海鲜 种子 |
| `generate_xuji_presales_ppt.py` | 徐记海鲜售前 PPT 生成 |
| `new_store_setup.sh` | 新门店初始化向导 |

## 5. 测试运行

| 脚本 | 用途 |
|------|------|
| `run_tier1_tests.sh` | Tier 1 测试 docker run 逐文件运行器（核心 W8 gate） |
| `sandbox_integration_test.py` | 沙箱集成测试 |
| `smoke_test.sh` / `gateway-import-smoke.sh` | 冒烟 / gateway import 冒烟 |
| `ab-experiment-verify.sh` | AB 实验验证 |
| `load-test.sh` | 压测入口（k6 包装） |
| `test_rls.py` | RLS 多租户隔离测试 |
| `verify_agents.py` | Agent 决策回归验证 |
| `collect-offline-results.sh` | 离线 e2e 结果收集 |

## 6. 数据 / Migration / 事件总线

| 脚本 | 用途 |
|------|------|
| `backfill_franchise_events.py` | 加盟事件回填（PG.5） |
| `refresh_mv_agent_roi.sh` | Agent ROI 物化视图刷新 |
| `ontology-consolidation.py` | Ontology 实体收敛 |
| `forge_register_resources.py` | Forge 开发者市场资源注册 |

## 7. 监控 / 健康度

| 脚本 | 用途 |
|------|------|
| `monitor.sh` | 综合监控 |
| `cost-report.sh` | 云成本报告 |
| `weekly-health-check.sh` | 周度健康度 |
| `week8_gate_check.sh` | W8 DEMO Go/No-Go 门槛检查 |
| `score_adapters.py` | 适配器评分 |
| `auto-sync.sh` | 边缘同步状态 |

## 8. 依赖管理

| 脚本 | 用途 |
|------|------|
| `generate_requirements_locks.sh` | requirements lockfile 生成 |
