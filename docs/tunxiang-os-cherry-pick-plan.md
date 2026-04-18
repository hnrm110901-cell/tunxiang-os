# tunxiang-os Cherry-Pick 可执行 Plan

> **使用方法**：在本地独立 clone tunxiang-os main，按顺序执行命令。  
> **安全性**：每个 PR 独立分支，失败可弃；不动 main 直到人工 review。  
> **前提**：已配置 SSH Key 访问 tunxiang-os，本地安装 git + python3。

---

## 前置准备（一次性，5 分钟）

```bash
# 1. 创建独立工作区
mkdir -p ~/tunxiang-integration
cd ~/tunxiang-integration

# 2. Clone 远端 main（浅克隆节省空间）
git clone git@github.com:hnrm110901-cell/tunxiang-os.git tx-main
cd tx-main

# 3. 配置 upstream 指向我们的 feature 分支
git remote add zhilian-feature git@github.com:hnrm110901-cell/tunxiang-os.git
git fetch zhilian-feature feature/d5-d12-compliance-wave123

# 4. 确认可见
git log --oneline zhilian-feature/feature/d5-d12-compliance-wave123 | head -5
# 预期看到：47ae92ef / 2d2d69de / 23a88baf 等
```

---

## 📍 PR #1 · 数据脱敏中间件（1 天，最低风险先行）

```bash
# 1. 新建分支
cd ~/tunxiang-integration/tx-main
git checkout main
git pull origin main
git checkout -b feat/gateway-data-masking

# 2. Checkout 本地独有文件
git checkout zhilian-feature/feature/d5-d12-compliance-wave123 -- \
  apps/api-gateway/src/core/mask_response.py \
  apps/api-gateway/src/services/data_masking_service.py

# 3. 移动到远端微服务结构
mkdir -p services/gateway/src/middleware
git mv apps/api-gateway/src/core/mask_response.py \
       services/gateway/src/middleware/response_masking.py
git mv apps/api-gateway/src/services/data_masking_service.py \
       services/gateway/src/utils/data_masking.py

# 4. 清理空目录
rm -rf apps/api-gateway  # 若 apps/ 完全是空目录

# 5. 改 import（人工 sed）
# 原: from src.core.mask_response → from services.gateway.src.middleware.response_masking
# 原: from src.services.data_masking_service → from services.gateway.src.utils.data_masking

# 6. 提交
git add services/gateway/
git commit -m "feat(gateway): 引入响应脱敏中间件 + PII 工具链

- mask_response: 响应体按角色脱敏手机/身份证/银行卡
- data_masking: 统一 PII 工具函数（sha16 假名化）
- 适配 GDPR Art.32 + 个保法'去标识化'要求

Source: zhilian-os/apps/api-gateway (Wave 2)
"

# 7. 推送
git push -u origin feat/gateway-data-masking

# 8. 创建 PR
gh pr create --repo hnrm110901-cell/tunxiang-os \
  --base main --head feat/gateway-data-masking \
  --title "feat(gateway): 数据脱敏中间件" \
  --body "引入本地 zhilian-os 的响应脱敏+PII 工具链。无业务依赖，可独立 merge。"
```

---

## 📍 PR #2 · LLM 网关 Phase 1 · 基础降级链（3-5 天）

```bash
cd ~/tunxiang-integration/tx-main
git checkout main && git pull
git checkout -b feat/tx-agent-llm-gateway-phase1

# 1. Checkout 本地 LLM 网关（不含 security + audit）
git checkout zhilian-feature/feature/d5-d12-compliance-wave123 -- \
  apps/api-gateway/src/services/llm_gateway/__init__.py \
  apps/api-gateway/src/services/llm_gateway/base.py \
  apps/api-gateway/src/services/llm_gateway/claude_provider.py \
  apps/api-gateway/src/services/llm_gateway/deepseek_provider.py \
  apps/api-gateway/src/services/llm_gateway/openai_provider.py \
  apps/api-gateway/src/services/llm_gateway/gateway.py \
  apps/api-gateway/src/services/llm_gateway/factory.py

# 2. 移动到 tx-agent
mkdir -p services/tx-agent/src/llm_gateway
mv apps/api-gateway/src/services/llm_gateway/* services/tx-agent/src/llm_gateway/

# 3. 删除本地残留
rm -rf apps/api-gateway

# 4. 改配置（核心）
# 编辑 services/tx-agent/src/core/config.py 追加：
cat >> services/tx-agent/src/core/config.py <<'EOF'

# LLM Gateway (from zhilian-os reverse integration)
LLM_PROVIDER_PRIORITY: str = "claude,deepseek,openai"
LLM_FALLBACK_ENABLED: bool = True
LLM_TIMEOUT_SEC: int = 5
EOF

# 5. 改 gateway.py 的 import（sed 批量）
sed -i.bak 's|from src.core.config|from services.tx_agent.src.core.config|g' \
  services/tx-agent/src/llm_gateway/*.py
rm services/tx-agent/src/llm_gateway/*.bak

# 6. 不动 Phase 1 的现有 agent 调用，gateway 作为新底层仅供后续 Phase 2 切换
# 第一期只做「可选择调用」，不替换现有 LLM 调用

# 7. 测试
cp -r ~/tunxiang-integration/zhilian-source/apps/api-gateway/tests/services/test_llm_gateway.py \
      services/tx-agent/tests/

# 8. 提交 & PR
git add services/tx-agent/src/llm_gateway services/tx-agent/src/core/config.py services/tx-agent/tests/test_llm_gateway.py
git commit -m "feat(tx-agent): LLM 三级降级网关 Phase 1 · 基础降级链

- Provider 抽象：Claude → DeepSeek → OpenAI
- 5s timeout + 3 次指数退避
- LLMAllProvidersFailedError 抛出不静默
- 修复 Claude 单家宕机停摆问题

第一期仅引入底层，现有 agent 调用保持不变。
第二期（PR #3）会接入 security + audit + 替换底层调用。

Source: zhilian-os/Wave 2 (commit 9ecffd3)
"
git push -u origin feat/tx-agent-llm-gateway-phase1
```

---

## 📍 PR #3 · LLM 网关 Phase 2 · 安全网关 + 审计日志（3 天）

```bash
cd ~/tunxiang-integration/tx-main
git checkout main && git pull
git checkout -b feat/tx-agent-llm-gateway-phase2

# 依赖 PR #2 已 merge。

# 1. Checkout security + audit model
git checkout zhilian-feature/feature/d5-d12-compliance-wave123 -- \
  apps/api-gateway/src/services/llm_gateway/security.py \
  apps/api-gateway/src/models/prompt_audit_log.py \
  apps/api-gateway/src/models/agent_memory.py \
  apps/api-gateway/src/services/agent_memory_bus.py

# 2. 移动
mv apps/api-gateway/src/services/llm_gateway/security.py services/tx-agent/src/llm_gateway/
mv apps/api-gateway/src/models/prompt_audit_log.py services/tx-agent/src/models/
mv apps/api-gateway/src/models/agent_memory.py services/tx-agent/src/models/
mv apps/api-gateway/src/services/agent_memory_bus.py services/tx-agent/src/services/
rm -rf apps/api-gateway

# 3. 生成 Alembic 迁移（远端 v### 规范）
cd services/tx-agent
alembic revision -m "add llm governance tables (prompt_audit + agent_memory)"
# 人工编辑生成的迁移文件，从本地 z63_d6_llm_governance.py 复制表定义

# 4. 修改 gateway.py 启用 security + audit
# 在 gateway.py 的 chat() 调用前后加：
# - security.sanitize_input / scrub_pii / filter_output
# - 写入 prompt_audit_logs

# 5. 提交
cd ~/tunxiang-integration/tx-main
git add services/tx-agent/
git commit -m "feat(tx-agent): LLM 网关 Phase 2 · 安全层 + 审计日志

- sanitize_input: prompt injection 检测（risk_score 0-100）
- scrub_pii: 手机/身份证/邮箱自动脱敏
- filter_output: API_KEY/SECRET 泄露检测
- PromptAuditLog: 记录 request_id/tokens/cost_fen/risk_score
- AgentMemory: 三级存储 hot(Redis 1h) → warm(PG 7d) → cold(永久)

Source: zhilian-os/Wave 2 (commit 9ecffd3)
依赖 PR #2 已 merge。
"
git push -u origin feat/tx-agent-llm-gateway-phase2
```

---

## 📍 PR #4 · 健康证到期 Celery 扫描（3 天）

```bash
cd ~/tunxiang-integration/tx-main
git checkout main && git pull
git checkout -b feat/tx-org-health-cert-scan

# 1. 先查远端现状
grep -r "health_cert\|health_certificate" services/tx-org/ | head
# 如已有模型，跳过建模步骤；如无，从本地复制

# 2. Checkout 文件
git checkout zhilian-feature/feature/d5-d12-compliance-wave123 -- \
  apps/api-gateway/src/services/health_cert_scan_service.py \
  apps/api-gateway/src/tasks/health_cert_tasks.py

# 3. 若远端 tx-org 有 HealthCertificate 模型则直接用；否则
# 从本地复制: apps/api-gateway/src/models/health_cert.py（Wave 1 创建）

# 4. 移动
mkdir -p services/tx-org/src/{services,tasks}
mv apps/api-gateway/src/services/health_cert_scan_service.py services/tx-org/src/services/
mv apps/api-gateway/src/tasks/health_cert_tasks.py services/tx-org/src/tasks/
rm -rf apps/api-gateway

# 5. 注册 Celery Beat（在 tx-org 的 celery_app.py）
# 追加:
#   "scan-health-certs-daily": {
#       "task": "services.tx_org.src.tasks.health_cert_tasks.scan_health_certs_daily",
#       "schedule": crontab(hour=8, minute=0, timezone="Asia/Shanghai"),
#   }

# 6. 提交
git add services/tx-org/
git commit -m "feat(tx-org): 健康证到期 Celery 扫描 + 过期自动停岗

- 30/15/7/1 天分级预警
- 过期自动 is_active=False + employment_status=suspended_health_cert
- Celery Beat 08:00 Asia/Shanghai
- 推送店长企微

合规价值：食安违法是连锁餐饮最大风险，此功能必备。

Source: zhilian-os/Wave 1 (commit 3ef8308)
"
git push -u origin feat/tx-org-health-cert-scan
```

---

## 📍 PR #5 · 劳动合同到期预警（2 天）

```bash
cd ~/tunxiang-integration/tx-main
git checkout main && git pull
git checkout -b feat/tx-org-labor-contract-alert

git checkout zhilian-feature/feature/d5-d12-compliance-wave123 -- \
  apps/api-gateway/src/services/labor_contract_alert_service.py \
  apps/api-gateway/src/tasks/labor_contract_tasks.py \
  apps/api-gateway/src/models/labor_contract.py   # 如远端无

# 移动 + 改 import + 注册 Beat 08:10

git add services/tx-org/
git commit -m "feat(tx-org): 劳动合同到期 60/30/15 天分级预警

- status 自动回写 EXPIRING/EXPIRED
- Celery Beat 08:10 Asia/Shanghai

合规价值：合同到期未续签 = 劳动法赔 2N 风险

Source: zhilian-os/Wave 1
"
git push -u origin feat/tx-org-labor-contract-alert
```

---

## 📍 PR #6 · 品智 POS 适配器（3 天）

```bash
cd ~/tunxiang-integration/tx-main
git checkout main && git pull
git checkout -b feat/tx-trade-pinzhi-adapter

git checkout zhilian-feature/feature/d5-d12-compliance-wave123 -- \
  packages/api-adapters/pinzhi/

mkdir -p services/tx-trade/src/adapters
mv packages/api-adapters/pinzhi services/tx-trade/src/adapters/

git add services/tx-trade/src/adapters/pinzhi/
git commit -m "feat(tx-trade): 品智 POS 适配器（尝在一起专用）

- 订单同步 / 日结汇总 / 菜品明细
- Celery 每日 01:30 自动拉取
- 支持增量 + 全量模式

客户价值：尝在一起是最高优先级客户，此适配器必备。

Source: zhilian-os/packages/api-adapters/pinzhi
"
git push -u origin feat/tx-trade-pinzhi-adapter
```

---

## 📍 PR #7-#9 · 决策闭环（3 周，依赖顺序）

```bash
# PR #7 SignalBus
git checkout -b feat/tx-intel-signal-bus
git checkout zhilian-feature/feature/d5-d12-compliance-wave123 -- \
  apps/api-gateway/src/services/signal_bus.py
# 移动到 services/tx-intel/src/services/signal_bus.py
# 3 路由按远端实际信号源重写
git commit -m "feat(tx-intel): SignalBus 信号路由"
git push -u origin feat/tx-intel-signal-bus

# PR #8 决策优先级引擎（依赖 PR #7）
git checkout -b feat/tx-intel-decision-priority
git checkout zhilian-feature/feature/d5-d12-compliance-wave123 -- \
  apps/api-gateway/src/services/decision_priority_engine.py \
  apps/api-gateway/src/services/financial_impact_calculator.py
git commit -m "feat(tx-intel): Top3 决策优先级引擎 + ¥影响计算"
git push -u origin feat/tx-intel-decision-priority

# PR #9 执行反馈闭环（依赖 PR #8）
git checkout -b feat/tx-intel-execution-feedback
git checkout zhilian-feature/feature/d5-d12-compliance-wave123 -- \
  apps/api-gateway/src/services/execution_feedback_service.py \
  apps/api-gateway/src/services/decision_push_service.py
git commit -m "feat(tx-intel): 执行反馈回写 + 4 时点推送"
git push -u origin feat/tx-intel-execution-feedback
```

---

## 📍 PR #10-#12 · 报告 + 案例 + 成本真相（3 周）

```bash
# PR #10
git checkout -b feat/tx-finance-monthly-report
git checkout zhilian-feature/feature/d5-d12-compliance-wave123 -- \
  apps/api-gateway/src/services/monthly_report_service.py \
  apps/api-gateway/src/api/monthly_report.py

# PR #11
git checkout -b feat/tx-finance-case-story
git checkout zhilian-feature/feature/d5-d12-compliance-wave123 -- \
  apps/api-gateway/src/services/case_story_generator.py \
  apps/api-gateway/src/services/scenario_matcher.py

# PR #12
git checkout -b feat/tx-finance-cost-truth
git checkout zhilian-feature/feature/d5-d12-compliance-wave123 -- \
  apps/api-gateway/src/services/waste_guard_service.py \
  apps/api-gateway/src/services/food_cost_service.py
```

---

## 📍 PR #13-#15 · HR 高级能力（3 周）

```bash
# PR #13 九宫格
git checkout -b feat/tx-org-nine-box
git checkout zhilian-feature/feature/d5-d12-compliance-wave123 -- \
  apps/api-gateway/src/models/talent_assessment.py \
  apps/api-gateway/src/services/talent_assessment_service.py \
  apps/api-gateway/src/services/nine_box_ai_service.py \
  apps/api-gateway/src/api/talent.py \
  apps/web/src/pages/hr/NineBoxMatrix.tsx

# PR #14 HR 数字人助手（依赖 PR #2+#3 LLM 网关）
git checkout -b feat/tx-agent-hr-assistant
git checkout zhilian-feature/feature/d5-d12-compliance-wave123 -- \
  apps/api-gateway/src/services/hr_assistant_agent/ \
  apps/api-gateway/src/models/hr_assistant.py \
  apps/api-gateway/src/api/hr_assistant.py \
  apps/web/src/pages/hr/HRAssistant.tsx

# PR #15 脉搏调研
git checkout -b feat/tx-org-pulse-survey
git checkout zhilian-feature/feature/d5-d12-compliance-wave123 -- \
  apps/api-gateway/src/models/pulse_survey.py \
  apps/api-gateway/src/services/pulse_survey_service.py \
  apps/api-gateway/src/api/pulse_survey.py \
  apps/web/src/pages/hr/PulseSurvey.tsx
```

---

## 🛠️ 通用技巧速查

### Cherry-pick 只取文件（不取 commit）
```bash
git checkout <branch> -- <file1> <file2>
```

### 查看某文件的 commit 来源
```bash
git log --all --oneline -- apps/api-gateway/src/services/llm_gateway/gateway.py
```

### 批量改 import 路径
```bash
find services/tx-agent/src/llm_gateway -type f -name "*.py" \
  -exec sed -i '' 's|from src.core|from services.tx_agent.src.core|g' {} \;
```

### 验证 Alembic 无漂移
```bash
cd services/tx-org
alembic revision --autogenerate -m "dry-run-check"
# 打开生成的文件，若 upgrade() 为空 = 无漂移，删除该文件
```

### PR 模板（每个 PR 都用）
```markdown
## Summary
- 从 zhilian-os 反向集成 [能力名]
- Source: commit <hash>
- 依赖 PR #X 已 merge（如有）

## Changes
- [ ] 模型/迁移
- [ ] 服务层
- [ ] API 路由
- [ ] 测试

## Test plan
- [ ] pytest services/tx-XXX/tests -v
- [ ] 手动验证 [关键场景]

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

---

## ⚠️ 执行前必读

1. **与远端团队通气**：15 个 PR 密集上线需要团队配合 review
2. **不要跨服务 PR**：每个 PR 只动一个微服务
3. **先做简单的**：按本文档顺序 PR #1 → #15
4. **Alembic 不直接复制**：每次都用 `alembic revision -m` 生成新 v### 号
5. **回滚方案**：每个 PR 独立分支，merge 后若出问题直接 revert 单个 commit

---

## 📞 对应 commit hash 速查

| PR | 原 zhilian commit | 波次 |
|----|-------------------|------|
| #1 脱敏 | （历史 v2.1）| — |
| #2-#3 LLM 网关 | `9ecffd3` | Wave 2 |
| #4-#5 合规扫描 | `3ef8308` | Wave 1 |
| #6 品智 POS | （历史 v2.0）| — |
| #7-#9 决策闭环 | `3ef8308` + 历史 | Wave 1 + v2.0 |
| #10-#11 报告案例 | （历史 v2.0）| — |
| #12 成本真相 | （历史 v2.0）| — |
| #13 九宫格 | `0c2fb5bf` | Wave 4 |
| #14 HR 数字人 | `23a88baf` | Wave 5 |
| #15 脉搏调研 | `23a88baf` | Wave 5 |

---

*本 Plan 与 `tunxiang-os-reverse-integration-guide.md` 配套使用。*
