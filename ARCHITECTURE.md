# ARCHITECTURE.md — 屯象OS 全景图（Level 1）

> 每次新任务启动必读。理解整体架构后再定位具体模块。  
> **版本**：v3.0 · **最后更新**：2026-04-17（D1-D12 全域覆盖 + 合规/财务/薪酬闭环）

---

## 系统定位

**屯象OS (TunXiang OS)** = 餐饮连锁智能体操作系统
- 通过 15+ 专属 AI Agent，将门店运营决策（排班/库存/菜单/服务/培训/合规/财务）自动化
- 核心接入：企业微信 / 飞书 Webhook → 自然语言指令 → Agent 执行 → 结果回传
- 部署形态：SaaS 多租户（brand_id + store_id 两级隔离）
- 定位类比：餐饮行业的 Palantir —— 不替换 POS，做 POS 上层的本体化智能层

---

## 模块依赖图

```
外部渠道
  企业微信 Webhook  ·  飞书 Webhook  ·  POS 系统  ·  美团外卖  ·  公开扫码（证书验证）
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│  apps/api-gateway  (FastAPI, Python 3.11+, 60+ 路由模块)     │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ API Routes   │  │ Middleware   │  │ Store Access │       │
│  │ /api/v1/...  │  │ CORS/GZip/   │  │ 跨店权限依赖 │       │
│  │ /public/...  │  │ Auth/Rate/   │  │ 5 角色矩阵   │       │
│  └──────┬───────┘  │ Tenant/Audit │  └──────────────┘       │
│         │          └──────────────┘                         │
│         │                                                   │
│  ┌──────▼──────────────────────────────────────────────┐    │
│  │  Services 层（220+ service files）                   │    │
│  │                                                      │    │
│  │  【核心业务】agent_service / intent_router           │    │
│  │  【记忆语义】store_memory_service / rag_service      │    │
│  │             vector_db_service_enhanced               │    │
│  │  【财务合规】voucher_service / ar_ap_service         │    │
│  │             einvoice_service / month_close_service   │    │
│  │             social_insurance_service                 │    │
│  │             personal_tax_service                     │    │
│  │             bank_disbursement_service                │    │
│  │  【合规预警】health_cert_scan_service                │    │
│  │             labor_contract_alert_service             │    │
│  │  【培训认证】exam_service / certificate_pdf_service  │    │
│  │  【POS 集成】fast_food_service / kds_service         │    │
│  │             payment_service / stored_value_service   │    │
│  │  【LLM 治理】llm_gateway/{gateway,security,factory}  │    │
│  │             agent_memory_bus（hot/warm/cold）        │    │
│  └──────┬──────────────────────────────────────────────┘    │
│         │                                                   │
│  ┌──────▼──────────────────────────────────────────────┐    │
│  │  Tasks 层（Celery Beat 定时任务）                    │    │
│  │  健康证扫描 08:00 · 劳动合同 08:10                   │    │
│  │  POS 日结 01:30 · 决策推送 4 个时间点                │    │
│  └──────┬──────────────────────────────────────────────┘    │
└─────────┼───────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│  packages/agents  (LangChain + LangGraph, 15 个领域 Agent)   │
│                                                             │
│  schedule │ order │ inventory │ private_domain              │
│  service  │ training │ decision │ ops_flow                  │
│  performance │ reservation │ banquet │ supplier             │
│  people_agent │ dish_rd │ business_intel                    │
└──────────────────────┬──────────────────────────────────────┘
                       │
          ┌────────────┼────────────────┬──────────────┐
          ▼            ▼                ▼              ▼
    PostgreSQL       Redis            Qdrant         Neo4j
    (主存储)      (缓存+队列+热记忆)  (向量检索)    (本体图)
    asyncpg        Sentinel HA        384维嵌入     待迁移
```

---

## LLM 三级降级架构（v3.0 新增）

```
┌──────────────────────────────────────────────────┐
│  LLMGateway.chat(messages, **kwargs)             │
│         │                                        │
│         ▼                                        │
│  ┌─────────────┐    ┌──────────────────┐         │
│  │ 输入安全层  │───▶│ sanitize_input   │         │
│  │             │    │ scrub_pii        │         │
│  └──────┬──────┘    └──────────────────┘         │
│         │                                        │
│         ▼                                        │
│  ┌─────────────────────────────────────┐         │
│  │ Provider 优先级链（5s timeout）    │         │
│  │                                     │         │
│  │  1. ClaudeProvider                  │         │
│  │         ↓ 失败 / 超时 / 3次重试      │         │
│  │  2. DeepSeekProvider                │         │
│  │         ↓ 失败 / 超时 / 3次重试      │         │
│  │  3. OpenAIProvider（兜底）          │         │
│  │         ↓ 全失败                     │         │
│  │  LLMAllProvidersFailedError         │         │
│  └─────────────────┬───────────────────┘         │
│                    │                             │
│         ┌──────────▼──────────┐                  │
│         │ 输出安全层          │                  │
│         │ filter_output       │                  │
│         │ (API_KEY/SECRET)    │                  │
│         └──────────┬──────────┘                  │
│                    │                             │
│         ┌──────────▼──────────┐                  │
│         │ PromptAuditLog      │                  │
│         │ tokens/cost/risk    │                  │
│         └─────────────────────┘                  │
└──────────────────────────────────────────────────┘
```

**配置项**：`LLM_PROVIDER_PRIORITY` / `LLM_TIMEOUT_SEC` / `LLM_FALLBACK_ENABLED`

---

## Agent 记忆总线（三级存储）

```
┌────────────────────────────────────────────┐
│  AgentMemoryBus                            │
│                                            │
│  save(level='hot')                         │
│    ├─ hot  : Redis (TTL 1h)      [快速]    │
│    ├─ warm : PostgreSQL (7 天)   [中期]    │
│    └─ cold : PostgreSQL (永久)   [归档]    │
│                                            │
│  load()                                    │
│    hot miss → warm promote → hot           │
│                                            │
│  evict_expired() ─ Celery                  │
│    hot 过期 → 降级 warm                    │
└────────────────────────────────────────────┘
```

---

## 核心领域模型

| 实体 | 说明 | 关键字段 |
|------|------|---------|
| `Store` | 门店（多租户基本单元）| `store_id`, `brand_id` |
| `Order` / `OrderItem` | 订单及明细 | `store_id`, `waiter_id`, `final_amount`(分) |
| `Employee` | 员工 | `store_id`, `role`, `id_card_no`（AES-256-GCM）|
| `Dish` | 菜品 | `store_id`, `is_available`, `cost`, `price` |
| `InventoryItem` | 库存 | `store_id`, `current_stock`, `min_stock` |
| `StoreMemory` | 门店运营记忆快照 | `peak_patterns`, `anomaly_patterns` |
| **`Voucher` / `VoucherEntry`** | 会计凭证（借贷平衡）| `total_debit_fen`, `total_credit_fen`, `status` |
| **`AccountReceivable` / `AccountPayable`** | AR/AP 台账 | `amount_fen`, `due_date`, `aging_bucket` |
| **`EInvoiceLog`** | 电子发票记录 | `bill_id`, `short_code`, `status` |
| **`SocialInsuranceConfig`** | 社保费率配置 | `region_code`, `pension/medical/...pct` |
| **`PersonalTaxRecord`** | 累计预扣个税 | `cumulative_taxable_income_fen`, `tax_rate_pct` |
| **`ExamCertificate`** | 培训证书 | `cert_no`, `expire_at`, `pdf_url` |
| **`MonthCloseLog`** | 月结/年结日志 | `year_month`, `status`, `snapshot_json` |
| **`UserStoreScope`** | 跨店权限授权 | `access_level`, `finance_access`, `expires_at` |
| **`PromptAuditLog`** | LLM 调用审计 | `risk_score`, `tokens`, `cost_fen` |

**金额单位约定**：数据库存分（fen），展示/计算时 `/100` 转元；模型提供 `*_yuan` 伴生属性

---

## 技术栈快照

| 层次 | 技术 | 版本/说明 |
|------|------|---------|
| Web 框架 | FastAPI | async first |
| ORM | SQLAlchemy 2.0 | async session + asyncpg |
| 数据库迁移 | Alembic | sync psycopg2（迁移专用）|
| Agent 框架 | LangChain + LangGraph | 状态机式 Agent |
| **LLM 网关** | Claude + DeepSeek + OpenAI | 三级降级 + 5s 超时 + 3 次重试 |
| 向量DB | Qdrant | 384 维嵌入 |
| 嵌入模型 | sentence-transformers | 本地优先，零向量降级 |
| 缓存 | Redis + Sentinel | TTL 策略按业务定 |
| 任务队列 | Celery + Celery Beat | Redis broker |
| **PDF 生成** | reportlab | 证书 A4 横版，需 fonts-noto-cjk |
| **二维码** | qrcode[pil] | 证书公开验证 |
| 前端 | React 19 + TS 5.9 | Vite 7.3 |
| UI 库 | Ant Design 5 + Z 组件 | 品牌色 `#FF6B2C` |
| 图表 | ECharts 5 + ChartTrend | 大图表/小趋势分开 |
| 监控 | Prometheus + Grafana | grafana-dashboard.json |
| 容器编排 | Docker Compose / K8s | k8s/ 目录全套 |
| 反向代理 | Nginx | SSL/TLS 终止 |
| 边缘计算 | Raspberry Pi 5 | 离线优先，300s 云同步 |

---

## Alembic 迁移链路（v3.0）

```
z60_d1_d4_pos_crm_menu_tables (34 表：POS/CRM/菜单基座)
        │
        ├─ z61_d7_finance_must_fix                  (7 表：Voucher/AR/AP/EInvoice)
        ├─ z61_compliance_training                  (1 表+索引：TrainingMaterial)
        └─ z61_d12_payroll_compliance               (6 表：SI/Tax/Disbursement)
                │
                └─ z62_merge_mustfix_p0             (空 merge)
                        │
                        ├─ z63_d6_llm_governance    (2 表：PromptAudit/AgentMemory)
                        ├─ z63_d8_d10_procurement_attendance (5 表)
                        └─ z63_d11_exam_system      (3 表+扩展：Question/Paper/Cert)
                                │
                                └─ z64_merge_shouldfix_p1 (空 merge)
                                        │
                                        └─ z65_d5_d7_closing_access [HEAD]
                                           (3 表：UserStoreScope/MonthClose/TrialBalance)
```

遗留 head：`z51_customer_dish_interactions`（前置技术债，待合并）

---

## API 路由概览（60+ 模块）

```
/api/v1/
  ├─ bff/                  角色驱动 BFF 聚合（sm/chef/floor/hq/hr）
  ├─ ar-ap/                应收应付台账
  ├─ finance/
  │   ├─ month-close/      月结/年结
  │   └─ ...
  ├─ payroll/              薪酬计算（社保/个税/代发）
  ├─ hr/
  │   ├─ health-certs/     健康证扫描
  │   ├─ labor-contracts/  合同到期
  │   └─ training/
  │       ├─ courses/      培训课程
  │       └─ exam/         考试/证书
  ├─ purchase-approval/    采购审批
  ├─ goods-receipt/        收货质检
  ├─ attendance-punch/     5 种打卡
  ├─ shift-swap/           换班审批
  ├─ stored-value/         储值卡
  ├─ credit-accounts/      挂账
  ├─ deposits/             押金
  ├─ wine-storage/         存酒
  ├─ e-receipts/           电子小票
  └─ ... (60+ 端点)
/public/                   公开端点（无需登录）
  └─ cert/verify/{cert_no} 证书验证（姓名脱敏）
```

---

## 权限边界（跨店访问）

| 角色 | 可访问门店 | read | write | finance(read) | finance(write) |
|---|---|:-:|:-:|:-:|:-:|
| admin | 全部 | ✓ | ✓ | ✓ | ✓ |
| finance | 本 brand 全部 | ✓ | ✓ | ✓ | ✓ |
| store_manager / assistant_manager / floor_manager | 本店 + `user_store_scopes` 扩展 | ✓ | ✓ | ✓ | ✗ |
| head_chef / station_manager | 本店 | ✓ | ✗ | ✗ | ✗ |
| customer_manager（区域经理） | 仅 `user_store_scopes` 授权 | 依 level | admin/write | finance_access=true | admin+finance_access |
| 其他员工 | 仅个人数据 | ✗ | ✗ | ✗ | ✗ |

**集成方式**：敏感端点加 `Depends(require_store_access('finance'|'finance_write'|...))`

---

## 关键文件路径

```bash
# 入口
apps/api-gateway/src/main.py              # FastAPI app, 中间件+路由注册
apps/api-gateway/src/core/config.py       # Settings（LLM_PROVIDER_PRIORITY 等）
apps/api-gateway/src/core/celery_app.py   # Celery Beat 调度（健康证/合同扫描）
apps/api-gateway/src/core/deps_store_access.py  # require_store_access 依赖

# Agent 分发
apps/api-gateway/src/services/agent_service.py   # Agent 调度入口
apps/api-gateway/src/services/intent_router.py   # 自然语言意图路由
apps/api-gateway/src/services/llm_gateway/       # LLM 三级降级 + 安全网关
apps/api-gateway/src/services/agent_memory_bus.py  # 三级记忆存储

# 财务合规（v3.0）
apps/api-gateway/src/services/voucher_service.py
apps/api-gateway/src/services/ar_ap_service.py
apps/api-gateway/src/services/einvoice_service.py
apps/api-gateway/src/services/month_close_service.py
apps/api-gateway/src/services/social_insurance_service.py
apps/api-gateway/src/services/personal_tax_service.py
apps/api-gateway/src/services/bank_disbursement_service.py
apps/api-gateway/src/services/health_cert_scan_service.py
apps/api-gateway/src/services/labor_contract_alert_service.py
apps/api-gateway/src/services/exam_service.py
apps/api-gateway/src/services/certificate_pdf_service.py

# 数据模型
apps/api-gateway/src/models/__init__.py   # 所有 model 注册（Alembic 依赖）
apps/api-gateway/alembic/env.py           # 迁移环境配置

# Agent 包（每个 agent 结构相同）
packages/agents/{domain}/src/agent.py    # Agent 实现
packages/agents/{domain}/tests/          # Agent 测试

# 种子数据
apps/api-gateway/scripts/seed_chart_of_accounts.py  # 26 条会计科目
apps/api-gateway/scripts/seed_si_config.py          # 长沙/北京/上海/深圳社保

# 基础设施
nginx/conf.d/default.conf                 # Nginx SSL + 安全头
k8s/                                      # K8s 全套配置
monitoring/                               # Prometheus + Grafana
```

---

## 构建 / 测试 / 部署（一行命令）

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行全量测试
pytest packages/*/tests -v --cov=packages

# 运行 API Gateway 测试
cd apps/api-gateway && pytest tests/ -v

# 启动本地开发服务
make run           # uvicorn + reload，端口 8000

# 数据库迁移
make migrate-gen msg="描述变更"
make migrate-up
make migrate-status

# 跑种子
python scripts/seed_chart_of_accounts.py
python scripts/seed_si_config.py

# Celery
celery -A src.core.celery_app.celery_app worker -l info &
celery -A src.core.celery_app.celery_app beat -l info &

# LLM 网关烟测
python scripts/smoke_test_llm_gateway.py

# Docker
make up            # docker-compose 启动所有服务
make down
make logs
```

---

## 已知约束与痛点

| 痛点 | 说明 | 影响范围 |
|------|------|---------|
| sys.path 污染 | 多 Agent 测试并行运行时互相覆盖 `src/agent.py` | packages/agents/* 测试需独立运行 |
| 同步 Alembic | 迁移用 psycopg2（同步），运行时用 asyncpg | alembic/env.py URL 转换逻辑不能删 |
| 金额单位 | DB 存分，API 返回元；已统一 `*_yuan` 伴生属性 | 改动金额字段时必须确认单位 |
| 嵌入降级 | 无本地模型+无 API Key 时返回零向量 | RAG 检索质量会下降 |
| Neo4j 迁移 | PostgreSQL → Neo4j 本体图迁移未完成 | 已识别为根级差距 |
| **PDF 中文字体** | Docker 镜像需安装 `fonts-noto-cjk` | 证书中文显示方块 |
| **多 Alembic head** | 遗留 `z51_customer_dish_interactions` 未合并 | 升级前需决定合并策略 |
| **财务端点权限** | 仅 month_close 已接入 `require_store_access` | vouchers/ar_ap/stored_value 待批量接入 |

---

## 版本演进

| 版本 | 日期 | 关键变更 |
|------|------|---------|
| v1.0 | 2025-Q4 | MVP 10 功能：决策推送/废料守护/成本分析 |
| v2.0 | 2026-Q1 | 私域健康分/信号总线/店长简报/老板多店版 |
| v2.1 | 2026-Q2 | POS 收银全链路/CRM 5 模块/菜单 6 模块 |
| **v3.0** | **2026-04-17** | **D1-D12 全域覆盖 · 合规/财务/薪酬生产级闭环 · LLM 三级降级 · 31 项差距消化** |

---

*本文件由 Claude Code 维护，重大架构变更后同步更新。*
