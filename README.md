# 屯象OS (TunXiang OS)

> 连锁餐饮 AI 经营决策系统 — 餐饮人的好伙伴

<p align="center">
  <img src="apps/web/public/logo-mark-v3.svg" alt="屯象OS" width="80" />
</p>

## 产品定位

屯象OS 是面向连锁餐饮品牌的 **AI 驱动经营决策 SaaS 平台**。通过 15+ AI Agent 将门店运营决策（排班、库存、菜单、营销、财务、合规）自动化，帮助连锁老板每年多赚 30 万+（成本率降低 2 个百分点）。

**核心指标**：续费率 ≥ 95%

**首批客户**：尝在一起（品智 POS）、徐记海鲜（奥琦玮）、最黔线、尚宫厨

**当前版本**：v3.0 · D1-D12 全域覆盖 · 合规/财务/薪酬生产级闭环

---

## 系统架构

```
用户端
  管理后台 (React)  ·  店长/厨师长/楼面移动端  ·  总部驾驶舱
        │
        ▼
┌─────────────────────────────────────────────────────┐
│  apps/api-gateway  (FastAPI · Python 3.11)          │
│  100+ API · BFF 聚合 · RBAC · 多租户隔离            │
└──────────┬──────────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────────┐
│  packages/agents  (LangChain + LangGraph)            │
│  15 个 AI Agent · 向量检索 · 事件驱动 · 联邦学习     │
└──────────┬──────────────────────────────────────────┘
           │
     ┌─────┼─────────────────┐
     ▼     ▼                 ▼
 PostgreSQL  Redis         Qdrant
 (主存储)   (缓存·队列)    (向量检索)
```

**部署形态**：SaaS 多租户（`brand_id` + `store_id` 两级隔离）

---

## 核心能力

### 15+ AI Agent

| 层级 | Agent | 能力 |
|------|-------|------|
| 增长层 | **经营智能体** BusinessIntel | KPI 异常检测、经营日报、CEO/CFO 驾驶舱 |
| 增长层 | **营销智能体** PrivateDomain | 私域运营、会员 RFM 分层、企微自动触发 |
| 增长层 | **宴会智能体** Banquet | 7 阶段销售漏斗、宴会全生命周期管理 |
| 运营层 | **运营流程体** OpsFlow | 出品链联动、损耗推理、三源对账 |
| 运营层 | **人员智能体** People | 智能排班、员工绩效、人力成本分析 |
| 运营层 | **菜品研发** DishRd | BOM 配方管理、菜品成本分析、新品研发 |
| 底座层 | **合规智能体** Compliance | 质量管理、食品安全、审计追踪、健康证/合同到期扫描 |
| 底座层 | **IT 运维** Ops | 系统健康、适配器监控、Edge 节点管理 |
| 底座层 | **财务智能体** FCT | 利润分析、预算管理、结算风控、财务预测 |
| 底座层 | **供应商智能体** Supplier | 供应链管理、采购协同、库存预警 |

### LLM 生产级治理（v3.0 新增）

- **三级降级链**：Claude → DeepSeek → OpenAI（5s 超时 + 3 次指数退避，全挂抛异常不静默）
- **安全网关**：sanitize_input（prompt injection 检测）+ scrub_pii（手机/身份证/邮箱）+ filter_output（API_KEY/SECRET 泄露）
- **Agent 记忆总线**：hot(Redis 1h) → warm(PG 7天) → cold(PG 永久) 三级存储
- **审计日志**：`prompt_audit_logs` 表记录 request_id / input_hash / risk_score / tokens / cost_fen

### 4 角色工作台

| 角色 | 路由 | 设备 | 核心场景 |
|------|------|------|----------|
| 店长 | `/sm` | 手机 | 晨间 AI 决策卡、KPI 大盘、一键确认排班 |
| 厨师长 | `/chef` | 手机 | 出品看板、损耗登记、备菜清单、沽清管理 |
| 楼面经理 | `/floor` | 平板 | 排队叫号、翻台监控、预订冲突检测 |
| 总部 | `/hq` | 桌面 | 多店矩阵、跨店对标、品牌级决策下发 |

### 三层导航架构

```
L1  顶部域Tab    经营总览 · 运营中心 · 增长引擎 · 供应链 · 智能体 · 平台治理
L2  可折叠侧栏   220px ↔ 56px · 分组折叠 · RBAC 过滤 · 状态徽标
L3  内容区       面包屑 · KPI 卡片 · AI 建议卡 · 数据钻取
```

### POS 系统适配

| 适配器 | 品牌 | 能力 |
|--------|------|------|
| 品智 Pinzhi | 尝在一起 | 订单同步、日结汇总、菜品明细、Celery 每日 01:30 自动拉取 |
| 天财商龙 | 最黔线 | 订单查询、门店汇总 |
| 奥琦玮 | 徐记海鲜 | 排班、预订、订单 |
| 客如云 | — | 订单、会员 |
| 易订 | — | 预订管理 |
| 美团 SaaS | — | 排队、外卖、等位 Webhook |

### 企业级合规能力（v3.0 新增）

| 领域 | 能力 |
|------|------|
| 会计凭证 | 借贷平衡强校验、储值卡/挂账/发票自动生成凭证（1002↔220301↔6001）|
| AR/AP 应收应付 | 台账 + 0-30/31-60/61-90/90+ 账龄报表 |
| 电子发票 | 结算 post-hook 自动开票 + 7 位短码自助填写链接 |
| 月结/年结 | 试算平衡快照 + 利润表/资产负债表 + 损益结转 |
| 六险一金 | 基数上下限裁剪 + 单险种禁用 + 公积金覆写 |
| 累计预扣个税 | 7 级税率表（对照国税总局公式）+ 专项附加扣除 |
| 银行代发 | 工行 TXT / 建行 TXT / 通用 CSV |
| 健康证到期扫描 | 30/15/7/1 天分级预警 + 过期自动停岗 |
| 劳动合同预警 | 60/30/15 天分级 + 状态回写 |
| 在线考试 | 5 题型自动判卷（单选/多选/判断/填空/主观）+ 证书 PDF + 公开验证页 |
| 跨店权限 | 5 角色矩阵（admin/finance/store_manager/head_chef/staff）+ 财务资源二级权限 |

---

## 技术栈

### 后端

| 组件 | 技术 |
|------|------|
| 框架 | FastAPI (Python 3.11+, async) |
| AI | LangChain + LangGraph |
| 数据库 | PostgreSQL 15 (asyncpg, 多租户 Schema) |
| 缓存/队列 | Redis 7 (Sentinel HA) + Celery Beat |
| 向量数据库 | Qdrant 1.7 |
| 图数据库 | Neo4j 5.17 |
| 认证 | JWT + RBAC + OAuth (企微/飞书/钉钉) |
| 迁移 | Alembic (多租户 Schema 级迁移) |

### 前端

| 组件 | 技术 |
|------|------|
| 框架 | React 18 + TypeScript |
| UI 库 | Ant Design 5 + 自研 Z 组件库 |
| 图表 | ECharts (ReactECharts) |
| 构建 | Vite 5 |
| 样式 | CSS Modules + Design Token 系统 |
| 路由 | React Router 6 (角色路由 /sm /chef /floor /hq) |

### 运维

| 组件 | 技术 |
|------|------|
| 容器 | Docker + Docker Compose (dev/staging/prod) |
| CI/CD | GitHub Actions |
| 监控 | Prometheus + Grafana + Alertmanager |
| 反向代理 | Nginx (SSL/TLS, 通配符证书) |
| 语音 | Shokz 骨传导耳机 WebSocket 集成 |

---

## 项目结构

```
tunxiang-os/
├── apps/
│   ├── web/                    # 管理后台 (React 19 + Vite 7)
│   │   ├── src/layouts/        # MainLayout(三层导航) + 角色 Layout
│   │   ├── src/pages/          # 240+ 页面
│   │   ├── src/pages/sm/       # 店长移动端（含 ManagementHub 功能聚合页）
│   │   ├── src/pages/chef/     # 厨师长
│   │   ├── src/pages/hq/       # 总部驾驶舱
│   │   ├── src/pages/hr/       # 培训课程/考试中心/我的证书 (v3.0)
│   │   ├── src/pages/public/   # 公开页（证书验证 /public/cert/verify）
│   │   ├── src/design-system/  # Design Token + Z 组件库
│   │   └── src/components/     # 全局搜索 · 通知中心 · 推荐卡片
│   └── api-gateway/            # API 网关 (FastAPI)
│       ├── src/api/            # 60+ API 路由模块
│       ├── src/services/       # 220+ Service 文件
│       │   └── llm_gateway/    # LLM 三级降级+安全网关 (v3.0)
│       ├── src/models/         # 90+ SQLAlchemy ORM 模型
│       ├── src/tasks/          # Celery 定时任务（健康证/合同扫描）
│       ├── src/core/           # 安全 · 数据库 · Celery · 配置 · 权限依赖
│       ├── src/middleware/     # CORS · GZip · 认证 · 限流 · 租户
│       └── alembic/            # 数据库迁移（z60→z65 链路）
├── packages/
│   ├── agents/                 # 15 个 AI Agent
│   │   ├── schedule/           # 智能排班
│   │   ├── order/              # 订单协同
│   │   ├── inventory/          # 库存预警
│   │   ├── banquet/            # 宴会管理
│   │   ├── business_intel/     # 经营智能
│   │   ├── people_agent/       # 人员管理
│   │   ├── ops_flow/           # 运营流程
│   │   ├── private_domain/     # 私域运营
│   │   ├── dish_rd/            # 菜品研发
│   │   ├── supplier/           # 供应商
│   │   ├── decision/           # 决策支持
│   │   ├── service/            # 服务质量
│   │   ├── training/           # 培训辅导
│   │   ├── reservation/        # 预订管理
│   │   └── performance/        # 绩效分析
│   └── api-adapters/           # POS 适配器
│       ├── pinzhi/             # 品智 (尝在一起)
│       ├── tiancai-shanglong/  # 天财商龙
│       ├── aoqiwei/            # 奥琦韦
│       ├── keruyun/            # 客如云
│       ├── yiding/             # 易订
│       └── meituan-saas/       # 美团 SaaS
├── nginx/                      # Nginx 配置 + SSL
├── scripts/                    # 运维脚本 (部署/备份/监控)
├── docker-compose.yml          # 开发环境
├── docker-compose.staging.yml  # Staging 环境
├── docker-compose.prod.yml     # 生产环境 (Redis HA + Celery)
└── docs/                       # 产品/技术文档
```

---

## 快速开始

### 环境要求

- Node.js ≥ 18 · pnpm ≥ 8
- Python ≥ 3.11
- Docker ≥ 24 · Docker Compose
- PostgreSQL ≥ 15 · Redis ≥ 7

### 安装与启动

```bash
# 1. 克隆
git clone https://github.com/hnrm110901-cell/tunxiang-os.git
cd tunxiang-os

# 2. 启动基础设施
docker-compose up -d   # PostgreSQL, Redis, Qdrant, Neo4j

# 3. 后端
cd apps/api-gateway
pip install -r requirements.txt
cp .env.example .env   # 编辑环境变量
alembic upgrade head   # 数据库迁移

# 跑会计科目 + 社保配置种子
python scripts/seed_chart_of_accounts.py
python scripts/seed_si_config.py

uvicorn src.main:app --reload --port 8000

# 启动 Celery Worker + Beat（健康证/合同定时扫描）
celery -A src.core.celery_app.celery_app worker -Q default,high_priority,low_priority -l info &
celery -A src.core.celery_app.celery_app beat -l info &

# 4. 前端
cd apps/web
pnpm install
pnpm dev               # http://localhost:5173
```

### 关键环境变量

| 变量 | 说明 |
|------|------|
| `DATABASE_URL` | PostgreSQL 连接串 |
| `REDIS_URL` | Redis 连接串 |
| `JWT_SECRET_KEY` | JWT 签名密钥 |
| `ANTHROPIC_API_KEY` | Claude API Key（优先） |
| `DEEPSEEK_API_KEY` | DeepSeek Key（二级降级） |
| `OPENAI_API_KEY` | OpenAI Key（三级兜底） |
| `LLM_PROVIDER_PRIORITY` | `claude,deepseek,openai`（默认） |
| `LLM_FALLBACK_ENABLED` | `true` 启用三级降级 |
| `PINZHI_TOKEN` | 品智 POS Token |
| `PUBLIC_DOMAIN` | 证书二维码验证域名（如 `https://zlsjos.cn`） |

### Docker 生产镜像注意事项

PDF 证书生成依赖中文字体，Dockerfile 必须安装：
```dockerfile
RUN apt-get update && apt-get install -y fonts-noto-cjk && rm -rf /var/lib/apt/lists/*
```
否则证书上的中文将显示为方块。

### 生产部署

```bash
# 环境检查
make prod-env-check

# 一键部署 (Docker Compose)
make prod-deploy

# 健康检查
make prod-health

# 数据库迁移
docker compose -f docker-compose.prod.yml exec api-gateway alembic upgrade head
```

详细部署文档：[docs/deployment-guide.md](./docs/deployment-guide.md)

---

## 开发规范

- **提交规范**：Conventional Commits (`feat:` / `fix:` / `docs:`)
- **分支策略**：`main` → 功能分支 → PR → 合并
- **TypeScript**：严格模式，零 TS 错误
- **Python**：snake_case, 参数化 SQL, 禁止字符串拼接
- **CSS**：CSS Modules，禁止内联样式（动态值除外）
- **前端数据获取**：统一使用 `apiClient`，禁止裸 fetch/axios

完整规范：[CLAUDE.md](./CLAUDE.md)

---

## 许可证

MIT License

---

**屯象OS** © 2026 — 让每一家连锁餐厅都有自己的 AI 经营伙伴
