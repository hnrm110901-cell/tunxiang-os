# tunxiang-os 反哺集成指引（Cherry-Pick Top 10）

> **目的**：把本地 zhilian-os 独有的 10 项能力反哺到远端 tunxiang-os 微服务架构。  
> **架构差异**：本地单体 `apps/api-gateway` vs 远端 18 微服务（tx-org/tx-trade/tx-finance/tx-member/tx-agent/...）。  
> **风险**：两边无共同历史，不能 git merge；必须按微服务边界手工拆分 cherry-pick。  
> **执行原则**：**只动单一微服务，不跨服务改动；每个 PR 控制在 500 行以内**。

---

## 🗺️ 整体映射原则

| 本地能力类型 | 应落在 tunxiang-os 哪个微服务 |
|-------------|---------------------------|
| LLM/AI 基建 | `services/tx-agent/` 或 `services/gateway/` |
| 决策闭环/KPI | `services/tx-intel/` 或 `services/tx-analytics/` |
| 财务/报告 | `services/tx-finance/` |
| HR/合规 | `services/tx-org/` |
| 信号总线 | `services/gateway/` 或 `services/tx-brain/` |
| 数据脱敏 | `services/gateway/` 公共层 |

---

## 📦 Top 10 Cherry-Pick 清单（按优先级排序）

---

### 🏆 Priority 1 · LLM 三级降级网关（最高价值）

**本地路径**：`apps/api-gateway/src/services/llm_gateway/`（8 文件）  
**建议目标**：`services/tx-agent/src/services/llm_gateway/` 或 `services/gateway/src/llm/`

**文件清单**：
```
__init__.py
base.py              — LLMProvider 抽象 + LLMAllProvidersFailedError
claude_provider.py   — Anthropic SDK 封装
deepseek_provider.py — DeepSeek OpenAI 兼容
openai_provider.py   — OpenAI 兜底
security.py          — sanitize_input/scrub_pii/filter_output 三道防线
gateway.py           — 降级链主逻辑 (5s timeout + 3 次指数退避)
factory.py           — 配置驱动单例
```

**依赖**：
- `src/models/prompt_audit_log.py`（审计日志表）
- `src/models/agent_memory.py`（可选，记忆总线）
- 环境变量：`ANTHROPIC_API_KEY` / `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` / `LLM_PROVIDER_PRIORITY`

**适配工作量**：**小**（2-4 小时）
- 只需改 import 路径（`from src.core.config` → `from tx_agent.core.config`）
- Alembic 迁移要按远端 `v###` 前缀重编号

**集成点**：
远端已有 `services/tx-agent/`，推测有 LLM 调用代码。建议：
1. 先读远端 `services/tx-agent/src/` 找到现有 LLM 调用点
2. 把 `gateway.py` 作为新底层替换，保留原接口签名
3. 不改业务层 agent，让 `LLMGateway.chat()` 作为底层（正如本地已做）

**Commit 建议**：
```
feat(tx-agent): 引入三级降级 LLM 网关 + 安全网关

- Claude → DeepSeek → OpenAI 自动降级
- prompt injection + PII 三道防线
- 审计日志 prompt_audit_logs
- 修复 Claude 单家宕机导致整个 AI 层停摆
```

---

### 🥈 Priority 2 · 决策闭环（signal_bus + priority_engine + feedback）

**本地路径**：
- `apps/api-gateway/src/services/signal_bus.py`
- `apps/api-gateway/src/services/decision_priority_engine.py`
- `apps/api-gateway/src/services/execution_feedback_service.py`
- `apps/api-gateway/src/services/decision_push_service.py`（可选）

**建议目标**：`services/tx-intel/src/services/` 或 `services/tx-brain/`

**核心能力**：
- **SignalBus**：3 路由（差评→修复旅程 / 临期库存→废料推送 / 大桌≥6人→裂变识别）
- **DecisionPriorityEngine**：Top3 决策聚合 + ¥影响估算 + 置信度
- **ExecutionFeedback**：决策执行结果回写 → 健康分重算（闭环学习）

**依赖**：
- `src/services/financial_impact_calculator.py`
- `src/services/private_domain_health_service.py`
- `src/models/decision_log.py`

**适配工作量**：**中**（1 人周）
- 需要对齐远端 decision_log 模型字段
- SignalBus 的 3 个路由需要按远端实际业务信号重写（远端可能已有不同 signal 源）

**集成点**：
远端 `tx-brain` / `tx-intel` 微服务推测是 AI 决策大脑。本地决策闭环直接可用。

**PR 拆分建议**：
- PR #1: `feat(tx-intel): SignalBus 信号路由基础`（signal_bus.py 单文件）
- PR #2: `feat(tx-intel): Top3 决策优先级引擎`
- PR #3: `feat(tx-intel): 执行反馈回写闭环`

---

### 🥉 Priority 3 · 月度报告 + 案例生成 + 场景匹配

**本地路径**：
- `apps/api-gateway/src/services/monthly_report_service.py`
- `apps/api-gateway/src/services/case_story_generator.py`
- `apps/api-gateway/src/services/scenario_matcher.py`

**建议目标**：`services/tx-finance/src/services/` 或 `services/tx-analytics/`

**核心能力**：
- **monthly_report_service**：月度 JSON + HTML（print-as-PDF）
- **case_story_generator**：从数据生成日报/周报/月报故事（"这个月省了 3.2 万"）
- **scenario_matcher**：7 场景分类器 + 历史案例匹配

**依赖**：
- `src/services/fct_service.py`（财务合并数据）
- `src/services/waste_guard_service.py`（废料数据）
- `src/services/food_cost_service.py`（食材成本）

**适配工作量**：**中**（3-5 天）
- HTML 模板内联，无外部依赖，直接可用
- 需对齐远端 fct/waste/food_cost 数据源字段名

**商业价值**：**极高** — 案例生成是决策型产品北极星指标，远端缺这能力。

---

### ⭐ Priority 4 · 健康证 Celery 扫描 + OCR

**本地路径**：
- `apps/api-gateway/src/services/health_cert_scan_service.py`
- `apps/api-gateway/src/tasks/health_cert_tasks.py`
- `apps/api-gateway/src/tasks/labor_contract_tasks.py`
- `apps/api-gateway/src/services/labor_contract_alert_service.py`

**建议目标**：`services/tx-org/src/services/` 和 `services/tx-org/src/tasks/`

**核心能力**：
- 30/15/7/1 天分级预警
- 过期自动停岗（`is_active=False` + `employment_status=suspended_health_cert`）
- 60/30/15 天合同到期预警
- Celery Beat 08:00 / 08:10 定时扫描

**依赖**：
- `src/models/health_cert.py` / `src/models/labor_contract.py`
- Celery worker + Redis broker

**适配工作量**：**小**（2-3 天）
- tx-org 应该已有 employee/contract 模型，只需接入扫描逻辑
- 需要远端已部署 Celery 集群（确认下 tx-org 有无 Celery）

**合规价值**：极高 — **食安违法 + 劳动法赔 2N** 是餐饮连锁最大风险。

---

### ⭐ Priority 5 · 数据脱敏中间件

**本地路径**：
- `apps/api-gateway/src/core/mask_response.py`
- `apps/api-gateway/src/services/data_masking_service.py`
- `apps/api-gateway/src/services/llm_gateway/security.py`（部分，PII 相关）

**建议目标**：`services/gateway/src/middleware/masking.py`（公共中间件层）

**核心能力**：
- 响应体自动脱敏手机号/身份证/银行卡
- 按角色分级（admin 看全 / hr 看部分 / staff 脱敏）
- LLM 输入前自动 scrub PII

**适配工作量**：**小**（1-2 天）— 纯工具函数无业务依赖

**合规价值**：**GDPR + 个保法刚需**

---

### Priority 6 · 成本真相引擎

**本地路径**：
- `apps/api-gateway/src/services/waste_guard_service.py`
- `apps/api-gateway/src/services/food_cost_service.py`
- `apps/api-gateway/src/services/cost_truth.py`（如存在）

**建议目标**：`services/tx-finance/` 或 `services/tx-supply/`

**核心能力**：Top5 废料 + ¥ 归因 + 日快照

**适配工作量**：**中**（1 周）— 依赖 BOM / 库存 / 订单 三源数据

---

### Priority 7 · POS 品智适配器（尝在一起专用）

**本地路径**：`packages/api-adapters/pinzhi/`

**建议目标**：`services/tx-trade/src/adapters/pinzhi/`

**核心能力**：订单同步 + 日结汇总 + 菜品明细，Celery 每日 01:30 拉取

**适配工作量**：**小**（2-3 天）— 适配器接口稳定，只需改依赖注入

**客户价值**：**极高** — 尝在一起是最高优先级客户

---

### Priority 8 · 九宫格人才盘点（Wave 4 产出）

**本地路径**：
- `apps/api-gateway/src/models/talent_assessment.py`
- `apps/api-gateway/src/services/talent_assessment_service.py`
- `apps/api-gateway/src/services/nine_box_ai_service.py`
- `apps/web/src/pages/hr/NineBoxMatrix.tsx`

**建议目标**：`services/tx-org/`

**核心能力**：perf×potential → 1-9 矩阵 + 继任方案 top 3

**适配工作量**：**小**（3-5 天）— 独立模块

---

### Priority 9 · HR 数字人助手（Wave 5 产出）

**本地路径**：`apps/api-gateway/src/services/hr_assistant_agent/`（6 文件）

**建议目标**：`services/tx-agent/src/services/hr_assistant/`

**核心能力**：15 类意图 × 18 工具，强制 `current_user_id` 注入

**依赖**：
- LLM gateway（Priority 1）
- 下游 18 个查询工具需要 mock/适配远端实际 service 签名

**适配工作量**：**中**（1 人周）— 工具 handlers 要按远端 service 签名全部重绑

---

### Priority 10 · 脉搏调研（Wave 5 产出）

**本地路径**：
- `apps/api-gateway/src/models/pulse_survey.py`
- `apps/api-gateway/src/services/pulse_survey_service.py`

**建议目标**：`services/tx-org/src/services/`

**核心能力**：匿名 SHA256 + LLM 情感分析 + 多期趋势

**适配工作量**：**小**（2-3 天）— 自包含模块

---

## 📋 PR 拆分建议（推荐 15 个 PR 顺序）

按依赖和风险从低到高：

1. **PR #1**: `feat(gateway): 数据脱敏中间件`（Priority 5，基建先行）
2. **PR #2**: `feat(tx-agent): LLM 三级降级网关基础`（Priority 1 Phase 1，不动业务）
3. **PR #3**: `feat(tx-agent): LLM 网关安全层 + 审计日志`（Priority 1 Phase 2）
4. **PR #4**: `feat(tx-org): 健康证到期 Celery 扫描`（Priority 4 Phase 1）
5. **PR #5**: `feat(tx-org): 劳动合同到期预警`（Priority 4 Phase 2）
6. **PR #6**: `feat(tx-trade): 品智 POS 适配器`（Priority 7）
7. **PR #7**: `feat(tx-intel): SignalBus 信号路由`（Priority 2 Phase 1）
8. **PR #8**: `feat(tx-intel): Top3 决策优先级引擎`（Priority 2 Phase 2）
9. **PR #9**: `feat(tx-intel): 执行反馈闭环`（Priority 2 Phase 3）
10. **PR #10**: `feat(tx-finance): 月度报告生成`（Priority 3 Phase 1）
11. **PR #11**: `feat(tx-finance): 案例生成 + 场景匹配`（Priority 3 Phase 2）
12. **PR #12**: `feat(tx-finance): 成本真相引擎`（Priority 6）
13. **PR #13**: `feat(tx-org): 九宫格人才盘点`（Priority 8）
14. **PR #14**: `feat(tx-agent): HR 数字人助手`（Priority 9，依赖 PR #2）
15. **PR #15**: `feat(tx-org): 脉搏调研`（Priority 10）

---

## 🚧 适配陷阱清单

### 陷阱 1 · Alembic 迁移号冲突
本地 z61-z71，远端 v1-v256+。**不要直接复制**，每个 PR 必须：
```bash
cd services/tx-org/alembic
alembic revision -m "XXX" --head current
# 让 Alembic 基于远端 HEAD 生成新 v### 号
```

### 陷阱 2 · 模型字段类型不匹配
本地 `employee_id` 常用 VARCHAR(50)，远端可能用 UUID。Priority 4（健康证）先查远端 `Employee.id` 类型，不匹配则要 cast。

### 陷阱 3 · Tenant 隔离模式
本地 `brand_id + store_id` 两级，远端 18 微服务可能每个服务独立 tenant schema。适配前用 grep 确认远端 tenant 隔离方式。

### 陷阱 4 · LLM 配置冲突
本地 `LLMSettings` 在 `core/config.py`，远端 tx-agent 可能已有自己的 `LLMConfig`。不要覆盖，新建 namespace：
```python
class LLMGatewaySettings(BaseSettings):
    GATEWAY_PROVIDER_PRIORITY: str = "claude,deepseek,openai"
    # 区别于原有 LLM_PROVIDER
```

### 陷阱 5 · Celery Beat 撞车
Priority 4 的 08:00 / 08:10 可能与远端已注册任务冲突。部署前 `inspect registered | grep scan`。

---

## 🎯 推荐集成节奏

### Week 1（快速见效）
- PR #1 数据脱敏（1 天）
- PR #6 品智 POS（3 天）
- PR #4 健康证扫描（1 天）

### Week 2-3（AI 基建）
- PR #2-#3 LLM 网关（1 周）
- PR #5 劳动合同（3 天）

### Week 4-6（决策闭环）
- PR #7-#9 SignalBus/Priority/Feedback（3 周）

### Week 7-10（报表+HR）
- PR #10-#12 财务报告（3 周）
- PR #13-#15 HR 能力（3 周）

**总工期**：约 2.5 个月 / 1 人力。

---

## 📞 集成支持

- **差分分析报告**：`docs/tunxiang-os-diff-report.md`
- **本地分支**：`feature/d5-d12-compliance-wave123` on `tunxiang-os`
- **代码可直接浏览**：https://github.com/hnrm110901-cell/tunxiang-os/tree/feature/d5-d12-compliance-wave123

每个 Priority 的 commit hash 映射：
- Priority 1 (LLM gateway): `9ecffd3` (Wave 2)
- Priority 2-3 (决策+报告): `3ef8308` + 历史 v2.0
- Priority 4 (健康证): `3ef8308` (Wave 1)
- Priority 5 (脱敏): 历史 v2.1
- Priority 8 (九宫格): `0c2fb5bf` (Wave 4)
- Priority 9 (HR 助手): `23a88baf` (Wave 5)
- Priority 10 (脉搏): `23a88baf` (Wave 5)

---

*本指引基于 `docs/tunxiang-os-diff-report.md` 差分分析，执行前请验证远端最新 main 是否与报告采样时一致。*
