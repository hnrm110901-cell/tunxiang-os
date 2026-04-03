# 屯象OS 人力管理模块 — 开发计划

> 版本：V1.0 | 日期：2026-04-01 | 编制：屯象科技工程部
> 依据：`hr-product-report.md` 发展路线图 + `hr-module-upgrade-plan.md` 升级计划

---

## 总览

| Phase | 时间 | 主题 | Sprint 数 | 估算人周 | 产出 |
|-------|------|------|----------|---------|------|
| Phase 1 | 2026 Q2 (4月-6月) | 补齐核心能力 | 3 个 Sprint | 8 人周 | 客户签约门槛清零 |
| Phase 2 | 2026 Q3 (7月-9月) | 产品专业化 | 3 个 Sprint | 12 人周 | 对标 i人事产品深度 |
| Phase 3 | 2026 Q4 (10月-12月) | AI 深度赋能 | 3 个 Sprint | 8 人周 | 建立技术壁垒 |
| **合计** | | | **9 个 Sprint** | **28 人周** | |

Sprint 节奏：**2 周/Sprint**，每 Sprint 含 1 天 code review + 1 天 QA。

---

## Phase 1 — 补齐核心能力（2026 Q2）

> 目标：消除客户签约时被竞品比下去的核心缺项，让尝在一起/最黔线/尚宫厨三家首批客户全面上线。

### Sprint 1（4月1日 - 4月14日）：薪资项目库增强 + 合规预警 Agent

#### Task 1.1 — 薪资项目库模板增强（1 人周）

**现状分析**：`salary_item_library.py` 已有 70 项薪资项目（7 大分类），API 已就绪（`salary_items.py`）。与 i人事 138 项的差距主要在餐饮专项补贴和地区差异化。

**开发任务**：

| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| 1.1.1 | 扩充薪资项目至 ~100 项 | `services/tx-org/src/services/salary_item_library.py` | 新增：餐饮行业专项（高温补贴/夜班补贴/技能津贴/带教奖金/外卖骑手补贴）、地区差异项（长沙/北京/上海最低工资） |
| 1.1.2 | 门店模板差异化 | 同上 | 扩展 `init_store_salary_config()` 支持 4 类模板：standard(中餐)/seafood(海鲜酒楼)/fast_food(快餐)/hotpot(火锅) |
| 1.1.3 | 薪资项目启用/停用管理 | 新建 `services/tx-org/src/services/salary_item_config_service.py` | `enable_item(store_id, item_code)` / `disable_item()` / `get_store_config()` — 门店级薪资项目开关，持久化到 `store_salary_configs` 表 |
| 1.1.4 | API 增强 | `services/tx-org/src/api/salary_items.py` | 新增 `PUT /api/v1/org/salary-items/{store_id}/config` 门店级项目启用配置 |
| 1.1.5 | DB Migration | `shared/db-migrations/` | 新建 `store_salary_configs` 表：`(id, tenant_id, store_id, item_code, enabled, custom_value_fen, updated_at)` |

**验收标准**：
- [ ] 薪资项目总数 ≥ 95 项
- [ ] 4 类门店模板可初始化
- [ ] 门店级项目启用/停用 API 可用
- [ ] 单元测试覆盖新增项目计算逻辑

---

#### Task 1.2 — 合规预警 Agent（1.5 人周）

**现状分析**：`Employee.health_cert_expiry` / `id_card_expiry` 字段已有，`evaluate_effectiveness` Agent 有绩效评估能力，但缺少**主动扫描 + 自动预警推送**的闭环。

**开发任务**：

| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| 1.2.1 | 合规扫描服务 | 新建 `services/tx-org/src/services/compliance_alert_service.py` | 三个扫描器：`scan_expiring_documents()` / `scan_low_performers()` / `scan_attendance_anomalies()` |
| 1.2.2 | 证件到期扫描 | 同上 | 查询 `employees` 表，检查 `health_cert_expiry`、`id_card_expiry` 字段，三档预警（30天/15天/7天/已过期） |
| 1.2.3 | 连续低绩效扫描 | 同上 | 查询 `payroll_records_v2` 近 N 月绩效，连续 3 月 performance_score < 60 触发预警 |
| 1.2.4 | Agent 集成 | 新建 `services/tx-agent/src/agents/skills/compliance_alert.py` | `ComplianceAlertAgent(SkillAgent)` — 支持 `scan_all` / `scan_documents` / `scan_performance` 三个 action |
| 1.2.5 | 定时调度 | `services/tx-agent/src/main.py` | 注册每日 08:00 定时扫描任务（或通过 cron 事件触发） |
| 1.2.6 | 预警推送 | `compliance_alert_service.py` | 发布 `OrgEventType.COMPLIANCE_ALERT` 事件 → Agent Console 弹窗 + 企微/钉钉 Webhook 通道（预留） |
| 1.2.7 | API 端点 | 新建 `services/tx-org/src/api/compliance_routes.py` | `GET /api/v1/org/compliance/alerts` 查询当前预警列表 / `POST /api/v1/org/compliance/scan` 手动触发扫描 |
| 1.2.8 | 注册路由 | `services/tx-org/src/main.py` | `app.include_router(compliance_router)` |

**合规扫描逻辑**：

```python
async def scan_expiring_documents(db, tenant_id, threshold_days=30):
    """
    扫描即将到期的证件：
    - health_cert_expiry: 健康证到期
    - id_card_expiry: 身份证到期
    - contract_end_date: 劳动合同到期（需新增字段）
    
    三档预警：
    - urgent (≤7天): severity=high
    - warning (≤15天): severity=medium
    - notice (≤30天): severity=low
    - expired (已过期): severity=critical
    """
```

**验收标准**：
- [ ] 证件到期扫描覆盖健康证 + 身份证
- [ ] 连续 3 月低绩效员工可被自动检出
- [ ] Agent Console 可收到预警推送
- [ ] 手动/定时扫描均可工作
- [ ] 单元测试 ≥ 5 个用例

---

### Sprint 2（4月15日 - 4月28日）：钉钉/企微员工同步 + 考勤 Stub 接真

#### Task 2.1 — 企业微信/钉钉 SDK 员工同步（2 人周）

**现状分析**：`Employee.wechat_userid` / `dingtalk_userid` 字段已预留，但 SDK 未对接。

**开发任务**：

| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| 2.1.1 | IM 同步服务抽象层 | 新建 `services/tx-org/src/services/im_sync_service.py` | `IMSyncProvider` 基类 + `WeChatWorkProvider` / `DingTalkProvider` 两个实现 |
| 2.1.2 | 企微通讯录同步 | 同上 | 调用企微 API：`/cgi-bin/user/list_id` 拉取部门-员工树 → 与 `employees` 表 diff → 新增/更新/标记离职 |
| 2.1.3 | 钉钉通讯录同步 | 同上 | 调用钉钉 API：`/topapi/v2/user/list` 同逻辑 |
| 2.1.4 | 双向绑定 | 同上 | `bind_im_account(employee_id, platform, userid)` — 绑定后员工的 IM 消息可触达 |
| 2.1.5 | Webhook 消息通道 | 新建 `services/tx-org/src/services/im_notify_service.py` | `send_notification(employee_ids, title, content, platform)` — 通过企微/钉钉群机器人或工作通知推送 |
| 2.1.6 | 配置管理 | 环境变量 | `WECHAT_CORP_ID` / `WECHAT_SECRET` / `DINGTALK_APP_KEY` / `DINGTALK_APP_SECRET` |
| 2.1.7 | API 端点 | 新建 `services/tx-org/src/api/im_sync_routes.py` | `POST /api/v1/org/im-sync/trigger` 手动同步 / `GET /api/v1/org/im-sync/status` 同步状态 / `POST /api/v1/org/im-sync/bind` 手动绑定 |
| 2.1.8 | 定时同步 | `services/tx-org/src/main.py` | 每日 02:00 自动同步通讯录（增量） |

**关键设计**：

```python
class IMSyncProvider(ABC):
    @abstractmethod
    async def fetch_department_tree(self) -> list[dict]: ...
    @abstractmethod
    async def fetch_employees(self, dept_id: str) -> list[dict]: ...
    @abstractmethod
    async def send_message(self, user_ids: list[str], content: dict) -> bool: ...

class WeChatWorkProvider(IMSyncProvider):
    def __init__(self, corp_id: str, secret: str): ...

class DingTalkProvider(IMSyncProvider):
    def __init__(self, app_key: str, app_secret: str): ...
```

**Diff 同步策略**：
1. 拉取 IM 平台全量员工列表
2. 与本地 `employees` 表按 `wechat_userid`/`dingtalk_userid` 匹配
3. 新增：IM 有、本地无 → 自动创建 Employee 记录（status=pending，待 HR 确认）
4. 更新：姓名/手机号变更 → 更新本地记录
5. 离职：IM 已删除、本地仍 active → 标记为疑似离职（不自动删除，通知 HR 确认）

**验收标准**：
- [ ] 企微通讯录同步可运行（需测试企微 sandbox）
- [ ] 钉钉通讯录同步可运行（需测试钉钉 sandbox）
- [ ] 消息推送通道可用（群机器人 Webhook）
- [ ] 合规预警可通过企微/钉钉推送到员工或管理者
- [ ] 单元测试覆盖 diff 同步逻辑

---

### Sprint 3（4月29日 - 5月12日）：考勤/排班 API 接真 + 前端联调

#### Task 3.1 — 考勤/排班 Stub API 接真实服务（1.5 人周）

**现状分析**：`api/schedule.py` 和 `api/employees.py` 部分端点为 stub（返回空数据），而 `attendance_engine.py` 和 `smart_schedule.py` 有完整的服务层实现，需要打通。

**开发任务**：

| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| 3.1.1 | 排班 API 接真 | `services/tx-org/src/api/schedule.py` | 将 stub 端点改为调用 `SmartScheduleService`：`GET /schedule/weekly` → `generate_schedule()` / `GET /schedule/traffic` → `predict_traffic()` / `GET /schedule/staffing` → `calculate_staffing_need()` |
| 3.1.2 | 员工 API 接真 | `services/tx-org/src/api/employees.py` | 将 stub 改为真实查询 `employees` 表：`GET /employees` → 分页查询 + 角色筛选 / `GET /employees/{id}` → 单员工详情 |
| 3.1.3 | 排班持久化 | 新建 `services/tx-org/src/services/schedule_repository.py` | 将排班结果写入 `employee_schedules` 表，支持查询已发布排班 |
| 3.1.4 | 考勤 DB 持久化 | `services/tx-org/src/services/attendance_repository.py` | 现有 repository 需补充：将 `AttendanceEngine` 的内存记录同步写入 `attendance_records` 表 |
| 3.1.5 | DB Migration | `shared/db-migrations/` | 确认 `employee_schedules` / `attendance_records` 表结构与服务层一致 |

#### Task 3.2 — 前端联调（1 人周）

| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| 3.2.1 | OrgPage 联调 | `apps/web-admin/src/pages/OrgPage.tsx` | 确认花名册/考勤/排班/人力成本排行均调真实 API，去除 mock 数据 |
| 3.2.2 | HRDashboardPage 联调 | `apps/web-admin/src/pages/hq/org/HRDashboardPage.tsx` | 考勤 Tab / 请假 Tab / 薪资 Tab 接真实后端 |
| 3.2.3 | 合规预警卡片 | `apps/web-admin/src/pages/OrgPage.tsx` | 新增"合规预警"卡片区，显示证件到期/低绩效预警列表 |

**验收标准**：
- [ ] 排班 API 返回真实的 7 天排班表（非空数据）
- [ ] 员工列表 API 返回真实员工（分页 + 筛选可用）
- [ ] OrgPage 全部数据来自真实 API
- [ ] HRDashboardPage 薪资批量计算 → 确认 → 发放流程可走通
- [ ] 合规预警在前端可见

---

### Phase 1 交付物清单

| 交付物 | 类型 | 文件路径 |
|--------|------|---------|
| 薪资项目库增强 | 服务层 | `services/tx-org/src/services/salary_item_library.py`（扩充） |
| 门店薪资配置服务 | 新建 | `services/tx-org/src/services/salary_item_config_service.py` |
| 合规预警服务 | 新建 | `services/tx-org/src/services/compliance_alert_service.py` |
| 合规预警 Agent | 新建 | `services/tx-agent/src/agents/skills/compliance_alert.py` |
| 合规预警 API | 新建 | `services/tx-org/src/api/compliance_routes.py` |
| IM 同步服务 | 新建 | `services/tx-org/src/services/im_sync_service.py` |
| IM 消息通道 | 新建 | `services/tx-org/src/services/im_notify_service.py` |
| IM 同步 API | 新建 | `services/tx-org/src/api/im_sync_routes.py` |
| 排班持久化 | 新建 | `services/tx-org/src/services/schedule_repository.py` |
| DB Migration | 新建 | `shared/db-migrations/versions/xxx_salary_config_compliance.py` |
| 前端联调 | 修改 | `apps/web-admin/src/pages/OrgPage.tsx` + `HRDashboardPage.tsx` |

---

## Phase 2 — 产品专业化（2026 Q3）

> 目标：补齐与 i人事的产品深度差距，建立绩效+赛马+积分的完整员工激励体系。

### Sprint 4（7月1日 - 7月14日）：绩效在线打分系统

#### Task 4.1 — 绩效评审周期管理（2 人周）

**开发任务**：

| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| 4.1.1 | 绩效服务核心 | 新建 `services/tx-org/src/services/performance_service.py` | 完整的绩效评审生命周期管理 |
| 4.1.2 | 评审周期 | 同上 | `create_review_cycle(period, template, scope, target_employees)` — 支持月度/季度/年度周期 |
| 4.1.3 | 评审模板 | 同上 | 预设模板：`waiter_monthly` / `chef_monthly` / `manager_quarterly` / `store_annual` — 各含不同维度+权重 |
| 4.1.4 | 在线打分 | 同上 | `submit_score(reviewer_id, employee_id, cycle_id, scores_by_dimension)` — 支持自评+上级评+交叉评 |
| 4.1.5 | 排名生成 | 同上 | `generate_ranking(cycle_id, scope=store/region/brand)` — 门店内/区域间/品牌级排名 |
| 4.1.6 | 绩效等级 | 同上 | 强制分布：A(10%) / B(25%) / C(50%) / D(10%) / E(5%)，可配置比例 |
| 4.1.7 | 绩效联动薪资 | 同上 | `link_to_payroll(cycle_id)` — 绩效等级 → 绩效系数 → 自动写入下月薪资绩效项 |

**数据模型（DB Migration）**：

```sql
CREATE TABLE performance_review_cycles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    cycle_name VARCHAR(100) NOT NULL,      -- "2026年Q2绩效评审"
    period_type VARCHAR(20) NOT NULL,      -- monthly/quarterly/annual
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    template VARCHAR(50) NOT NULL,         -- waiter_monthly/chef_monthly/...
    scope VARCHAR(20) NOT NULL,            -- store/region/brand
    scope_id UUID,                         -- 对应的 store_id/region_id
    status VARCHAR(20) DEFAULT 'draft',    -- draft/in_progress/completed/archived
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    is_deleted BOOLEAN DEFAULT FALSE
);

CREATE TABLE performance_scores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    cycle_id UUID NOT NULL REFERENCES performance_review_cycles(id),
    employee_id UUID NOT NULL REFERENCES employees(id),
    reviewer_id UUID NOT NULL REFERENCES employees(id),
    review_type VARCHAR(20) NOT NULL,      -- self/supervisor/peer
    dimensions JSONB NOT NULL,             -- {"service_volume": 85, "revenue": 72, ...}
    total_score DECIMAL(5,1),
    grade VARCHAR(5),                      -- A/B/C/D/E
    comment TEXT,
    submitted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    is_deleted BOOLEAN DEFAULT FALSE
);
```

**API 端点**：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/org/performance/cycles` | 创建评审周期 |
| GET | `/api/v1/org/performance/cycles` | 列出评审周期 |
| POST | `/api/v1/org/performance/scores` | 提交打分 |
| GET | `/api/v1/org/performance/scores/{cycle_id}` | 查询某周期的评分 |
| GET | `/api/v1/org/performance/ranking/{cycle_id}` | 排名列表 |
| POST | `/api/v1/org/performance/cycles/{cycle_id}/finalize` | 锁定评审结果 |

**验收标准**：
- [ ] 可创建月度/季度评审周期
- [ ] 支持自评 + 上级评的双评模式
- [ ] 门店内排名自动生成
- [ ] 强制分布可配置比例
- [ ] 评审结果可联动下月薪资

---

### Sprint 5（7月15日 - 7月28日）：赛马机制 + 员工积分体系

#### Task 5.1 — 员工积分体系（2 人周）

| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| 5.1.1 | 积分服务 | 新建 `services/tx-org/src/services/points_service.py` | 积分规则引擎 + 积分账户 + 积分流水 + 排行榜 |
| 5.1.2 | 积分获取规则 | 同上 | 可配置积分来源（每个来源的分值可调） |
| 5.1.3 | 积分消费/兑换 | 同上 | `redeem_points(employee_id, item_id, points)` — 积分商城兑换（调休/奖品/培训机会） |
| 5.1.4 | 排行榜 | 同上 | `get_leaderboard(scope, period)` — 实时排行（日/周/月/季度） |
| 5.1.5 | 赛马机制 | 同上 | `create_competition(name, scope, metrics, period)` — 门店间/员工间竞赛活动 |

**积分获取规则矩阵**：

| 积分来源 | 默认分值 | 触发条件 | 数据来源 |
|---------|---------|---------|---------|
| 全勤奖 | +100/月 | 月度无迟到/旷工/早退 | 考勤引擎 |
| 绩效 A 级 | +200/月 | 月度绩效评审得 A | 绩效服务 |
| 零客诉 | +50/月 | 月度无客户投诉 | tx-trade 订单 |
| 推菜成功 | +5/次 | 推荐菜品被点单 | tx-trade 订单 |
| 培训通过 | +30/次 | 完成一门培训课程 | 培训管理 |
| 带教新人 | +80/月 | 带教新员工通过试用期 | HR 录入 |
| 拾金不昧 | +50/次 | 拾到客人物品并归还 | HR 录入 |
| 迟到扣分 | -10/次 | 迟到 | 考勤引擎 |
| 客诉扣分 | -30/次 | 被客户投诉 | tx-trade 订单 |
| 食安扣分 | -100/次 | 食品安全违规 | 巡店质检 |

**数据模型**：

```sql
CREATE TABLE employee_points_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    employee_id UUID NOT NULL REFERENCES employees(id),
    total_points INT DEFAULT 0,
    available_points INT DEFAULT 0,       -- 可用（扣除已兑换）
    lifetime_earned INT DEFAULT 0,
    lifetime_spent INT DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, employee_id)
);

CREATE TABLE employee_points_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    employee_id UUID NOT NULL,
    points INT NOT NULL,                  -- 正=获取，负=消费
    source VARCHAR(50) NOT NULL,          -- full_attendance/performance_a/zero_complaint/...
    source_ref_id UUID,                   -- 关联的业务ID（考勤ID/绩效ID等）
    description VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE competitions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    name VARCHAR(100) NOT NULL,
    scope VARCHAR(20) NOT NULL,           -- store/region/brand/individual
    metrics JSONB NOT NULL,               -- [{"name": "revenue_per_hour", "weight": 0.4}, ...]
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    prize_description TEXT,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**验收标准**：
- [ ] 全勤/绩效/零客诉自动加分
- [ ] 迟到/客诉/食安违规自动扣分
- [ ] 积分排行榜可按日/周/月查看
- [ ] 积分兑换流程可走通
- [ ] 门店间竞赛活动可创建和查看

---

### Sprint 6（7月29日 - 8月11日）：电子签约 + 薪资台账双视角

#### Task 6.1 — 电子签约模块（2 人周）

| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| 6.1.1 | 签约服务核心 | 新建 `services/tx-org/src/services/e_signature_service.py` | 合同模板管理 + 签署流程 + 到期提醒 |
| 6.1.2 | 合同模板 | 同上 | 4 类标准模板：`labor_contract`(劳动合同) / `probation_agreement`(试用期协议) / `confidentiality`(保密协议) / `non_compete`(竞业禁止) |
| 6.1.3 | 签署流程 | 同上 | `initiate_signing(template_id, employee_id, params)` → 生成合同 → 推送到员工手机 → 员工签字 → 管理者确认 → 归档 |
| 6.1.4 | 到期提醒 | 同上 | 集成到 `compliance_alert_service.py` — 合同到期前 30/15/7 天三档提醒 |
| 6.1.5 | Employee 字段扩展 | `shared/ontology/src/entities.py` | 新增 `contract_start_date` / `contract_end_date` / `contract_type` / `contract_status` |
| 6.1.6 | DB Migration | `shared/db-migrations/` | 新建 `employee_contracts` 表 + Employee 新增字段 |
| 6.1.7 | API 端点 | 新建 `services/tx-org/src/api/contract_routes.py` | CRUD 合同 + 发起签署 + 查询签署状态 |

**签署状态机**：

```
draft → pending_employee → pending_manager → signed → archived
                                                  ↓
                                              expired → renewal_pending
```

**数据模型**：

```sql
CREATE TABLE employee_contracts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    employee_id UUID NOT NULL REFERENCES employees(id),
    template_type VARCHAR(50) NOT NULL,
    contract_no VARCHAR(50),
    start_date DATE NOT NULL,
    end_date DATE,
    status VARCHAR(30) DEFAULT 'draft',
    content_snapshot JSONB,               -- 合同内容快照
    employee_signed_at TIMESTAMPTZ,
    manager_signed_at TIMESTAMPTZ,
    manager_id UUID,
    attachment_path VARCHAR(500),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    is_deleted BOOLEAN DEFAULT FALSE
);
```

#### Task 6.2 — 薪资台账双视角（1 人周）

| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| 6.2.1 | 管理端薪资台账 | `services/tx-org/src/api/payroll_router.py` | 新增 `GET /api/v1/payroll/ledger` — 按部门/岗位/门店聚合的薪资台账视图 |
| 6.2.2 | 员工端工资条 | `services/tx-org/src/api/payslip.py` | 增强 `GET /api/v1/org/payslip/{employee_id}` — 员工可查看自己的月度工资条明细 |
| 6.2.3 | 薪资趋势 | `services/tx-org/src/api/payroll_router.py` | 新增 `GET /api/v1/payroll/trend` — 门店/品牌级月度薪资趋势（近 12 个月） |
| 6.2.4 | 前端管理端 | `apps/web-admin/src/pages/hq/org/` | 新建 `PayrollLedgerPage.tsx` — 薪资台账管理页（表格 + 图表） |
| 6.2.5 | 前端员工端 | `apps/web-crew/src/pages/` | 新建 `MyPayslipPage.tsx` — 员工查看个人工资条 |

### Sprint 7（8月12日 - 8月25日）：绩效/积分前端 + 集成测试

#### Task 7.1 — 前端开发（2 人周）

| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| 7.1.1 | 绩效管理页 | 新建 `apps/web-admin/src/pages/hq/org/PerformancePage.tsx` | 评审周期列表 + 打分面板 + 排名榜 |
| 7.1.2 | 员工积分页 | 新建 `apps/web-admin/src/pages/hq/org/PointsLeaderboardPage.tsx` | 积分排行榜 + 竞赛活动管理 |
| 7.1.3 | 合同管理页 | 新建 `apps/web-admin/src/pages/hq/org/ContractPage.tsx` | 合同列表 + 签署状态追踪 + 到期预警 |
| 7.1.4 | 服务员端绩效 | `apps/web-crew/src/pages/` | 新建 `MyPerformancePage.tsx` — 员工查看自己的绩效/积分/排名 |
| 7.1.5 | 侧栏导航更新 | `apps/web-admin/src/shell/SidebarHQ.tsx` | 人力管理子菜单新增：绩效管理/积分排行/合同管理/薪资台账 |
| 7.1.6 | API 层 | `apps/web-admin/src/api/` | 新建 `performanceApi.ts` / `pointsApi.ts` / `contractApi.ts` |

#### Task 7.2 — 集成测试（1 人周）

| # | 任务 | 说明 |
|---|------|------|
| 7.2.1 | 绩效全流程测试 | 创建周期 → 打分 → 排名 → 联动薪资 |
| 7.2.2 | 积分全流程测试 | 全勤加分 → 客诉扣分 → 排行榜 → 兑换 |
| 7.2.3 | 签约全流程测试 | 创建合同 → 发起签署 → 签字 → 归档 → 到期预警 |
| 7.2.4 | 薪资台账测试 | 双视角数据一致性 |

---

### Phase 2 交付物清单

| 交付物 | 类型 | 文件路径 |
|--------|------|---------|
| 绩效评审服务 | 新建 | `services/tx-org/src/services/performance_service.py` |
| 绩效 API | 新建 | `services/tx-org/src/api/performance_routes.py` |
| 积分服务 | 新建 | `services/tx-org/src/services/points_service.py` |
| 积分 API | 新建 | `services/tx-org/src/api/points_routes.py` |
| 电子签约服务 | 新建 | `services/tx-org/src/services/e_signature_service.py` |
| 合同 API | 新建 | `services/tx-org/src/api/contract_routes.py` |
| 薪资台账 API | 增强 | `services/tx-org/src/api/payroll_router.py` |
| 绩效管理页 | 新建 | `apps/web-admin/src/pages/hq/org/PerformancePage.tsx` |
| 积分排行页 | 新建 | `apps/web-admin/src/pages/hq/org/PointsLeaderboardPage.tsx` |
| 合同管理页 | 新建 | `apps/web-admin/src/pages/hq/org/ContractPage.tsx` |
| 薪资台账页 | 新建 | `apps/web-admin/src/pages/hq/org/PayrollLedgerPage.tsx` |
| 员工端绩效 | 新建 | `apps/web-crew/src/pages/MyPerformancePage.tsx` |
| 员工端工资条 | 新建 | `apps/web-crew/src/pages/MyPayslipPage.tsx` |
| DB Migration | 新建 | 3 个迁移文件 |

---

## Phase 3 — AI 深度赋能（2026 Q4）

> 目标：利用 Claude API + Core ML 边缘推理，建立不可复制的 AI 壁垒。

### Sprint 8（10月1日 - 10月14日）：AI 薪资项目推荐

#### Task 8.1 — AI 薪酬结构推荐（2 人周）

| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| 8.1.1 | 薪酬推荐 Agent | 新建 `services/tx-agent/src/agents/skills/salary_advisor.py` | `SalaryAdvisorAgent(SkillAgent)` — 支持 `recommend_salary_structure` / `benchmark_salary` / `predict_turnover_risk` |
| 8.1.2 | 薪酬推荐逻辑 | 同上 | 基于输入（岗位/城市/工龄/技能数/门店规模），从历史数据中找到相似员工群体，推荐薪酬结构（基本工资:绩效:提成 的比例） |
| 8.1.3 | 薪酬竞争力基准 | 同上 | `benchmark_salary(role, city, experience_years)` — 对比行业薪资水平（数据来源：内部数据聚合 + 行业报告基准值） |
| 8.1.4 | 离职风险预测 | 同上 | `predict_turnover_risk(employee_id)` — 基于薪资竞争力+绩效趋势+考勤异常+司龄，预测员工离职风险等级 |
| 8.1.5 | Claude API 增强推理 | 同上 | 复杂场景（如多门店薪酬平衡）通过 Claude API 进行推理，简单场景走本地规则引擎 |
| 8.1.6 | API 端点 | 新建 `services/tx-org/src/api/salary_advisor_routes.py` | `POST /api/v1/org/salary-advisor/recommend` / `GET /api/v1/org/salary-advisor/benchmark` |

**推荐算法**：

```python
async def recommend_salary_structure(params):
    """
    输入: role, city, experience_years, skill_count, store_tier
    输出:
      - recommended_base_fen: 建议基本工资
      - recommended_structure: {base_pct: 0.6, performance_pct: 0.2, commission_pct: 0.2}
      - market_percentile: 当前薪资在市场的百分位
      - risk_level: 薪资竞争力风险(low/medium/high)
      - reasoning: AI 推理说明
    """
```

**离职风险评分模型**：

| 特征 | 权重 | 评分逻辑 |
|------|------|---------|
| 薪资竞争力(vs市场) | 30% | 低于P25=高风险，P25-P50=中风险，>P50=低风险 |
| 绩效趋势 | 20% | 连续下降=高风险，波动=中风险，稳定/上升=低风险 |
| 考勤异常频率 | 15% | 月均迟到>3次=高风险 |
| 司龄 | 15% | <6月=高风险（试用期离职高峰），6-24月=中风险，>24月=低风险 |
| 培训完成率 | 10% | <30%=高风险（敬业度低） |
| 加班频率 | 10% | 月均加班>40h=高风险（burnout） |

---

### Sprint 9（10月15日 - 10月28日）：薪税申报对接 + 考勤深度合规

#### Task 9.1 — 薪税申报对接（2 人周）

| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| 9.1.1 | 税务申报服务 | 新建 `services/tx-org/src/services/tax_filing_service.py` | 生成个税申报数据包 + 对接自然人电子税务局 API |
| 9.1.2 | 申报数据生成 | 同上 | `generate_tax_filing_data(tenant_id, period)` — 从 `payroll_records_v2` 聚合月度个税数据，生成符合税务局格式的 XML/JSON |
| 9.1.3 | 税务局 API 对接 | 同上 | `submit_filing(filing_data)` — 调用自然人电子税务局开放接口（需申请 API 权限） |
| 9.1.4 | 申报状态追踪 | 同上 | `get_filing_status(filing_id)` — 查询申报处理状态（submitted/accepted/rejected） |
| 9.1.5 | 申报记录 | 同上 | `tax_filing_records` 表：`(id, tenant_id, period, status, submitted_at, result)` |
| 9.1.6 | API 端点 | 新建 `services/tx-org/src/api/tax_filing_routes.py` | `POST /generate` / `POST /submit` / `GET /status` |

#### Task 9.2 — 考勤深度合规（1 人周）

| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| 9.2.1 | 合规检测引擎 | 新建 `services/tx-org/src/services/attendance_compliance.py` | 三大合规检测能力 |
| 9.2.2 | GPS 异常检测 | 同上 | `detect_gps_anomaly(clock_record)` — 打卡位置与门店距离超过阈值(默认500米)告警 |
| 9.2.3 | 同设备打卡检测 | 同上 | `detect_device_sharing(clock_records)` — 同一设备ID在短时间内为多人打卡 → 代打卡告警 |
| 9.2.4 | 加班超时预警 | 同上 | `detect_overtime_violation(employee_id, month)` — 月度加班超36小时/日均超3小时 → 劳动法违规告警 |
| 9.2.5 | 打卡扩展字段 | `services/tx-org/src/services/attendance_engine.py` | `clock_in()` 新增可选参数：`gps_lat` / `gps_lng` / `device_id` |
| 9.2.6 | 合规报告 | 同上 | `generate_compliance_report(store_id, month)` — 月度考勤合规报告（合规率/违规明细/风险评估） |

**GPS 异常检测逻辑**：

```python
async def detect_gps_anomaly(clock_record, store_location):
    """
    1. 计算打卡GPS与门店GPS的直线距离(Haversine公式)
    2. 距离 > 500m: 标记为 gps_anomaly
    3. 距离 > 2km: 标记为 gps_critical (疑似异地打卡)
    4. 无GPS数据: 标记为 gps_missing (设备未开启定位)
    """
```

---

### Sprint 10（10月29日 - 11月11日）：AI 前端 + 全链路集成

#### Task 10.1 — AI 功能前端（1.5 人周）

| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| 10.1.1 | 薪酬推荐页面 | 新建 `apps/web-admin/src/pages/hq/org/SalaryAdvisorPage.tsx` | 输入岗位/城市/工龄 → AI 推荐薪酬结构 + 市场基准对比 |
| 10.1.2 | 离职风险看板 | 新建 `apps/web-admin/src/pages/hq/org/TurnoverRiskPage.tsx` | 全品牌离职风险热力图 + 高风险员工列表 + 干预建议 |
| 10.1.3 | 考勤合规看板 | 扩展 `HRDashboardPage.tsx` | 新增"合规"Tab：GPS 异常/代打卡/加班超时的可视化看板 |
| 10.1.4 | 薪税申报入口 | 扩展 `HRDashboardPage.tsx` | 薪资 Tab 新增"一键生成申报数据"+ "提交税务局"操作按钮 |

#### Task 10.2 — 全链路集成测试（0.5 人周）

| # | 测试场景 | 涉及模块 |
|---|---------|---------|
| 10.2.1 | AI 薪酬推荐 → 薪资项目配置 → 月度计算 | salary_advisor → salary_item_config → payroll_engine_db |
| 10.2.2 | GPS 打卡 → 异常检测 → Agent 预警 → 企微推送 | attendance_engine → attendance_compliance → compliance_alert → im_notify |
| 10.2.3 | 月度薪资计算 → 个税 → 申报数据生成 → 提交 | payroll_engine_db → income_tax → tax_filing |
| 10.2.4 | 离职风险预测 → HR 干预 → 跟进 | salary_advisor.predict_turnover_risk → compliance_alert → HR 操作 |

---

### Phase 3 交付物清单

| 交付物 | 类型 | 文件路径 |
|--------|------|---------|
| 薪酬推荐 Agent | 新建 | `services/tx-agent/src/agents/skills/salary_advisor.py` |
| 薪酬推荐 API | 新建 | `services/tx-org/src/api/salary_advisor_routes.py` |
| 薪税申报服务 | 新建 | `services/tx-org/src/services/tax_filing_service.py` |
| 薪税申报 API | 新建 | `services/tx-org/src/api/tax_filing_routes.py` |
| 考勤合规引擎 | 新建 | `services/tx-org/src/services/attendance_compliance.py` |
| 薪酬推荐页 | 新建 | `apps/web-admin/src/pages/hq/org/SalaryAdvisorPage.tsx` |
| 离职风险页 | 新建 | `apps/web-admin/src/pages/hq/org/TurnoverRiskPage.tsx` |
| DB Migration | 新建 | 2 个迁移文件 |

---

## 全局依赖与风险

### 外部依赖

| 依赖项 | 影响 Sprint | 风险 | 缓解措施 |
|--------|-----------|------|---------|
| 企业微信开放平台审批 | Sprint 2 | 审批周期 1-2 周 | 提前在 Sprint 1 期间申请 |
| 钉钉开放平台应用审批 | Sprint 2 | 审批周期 1 周 | 同上 |
| 自然人电子税务局 API 权限 | Sprint 9 | 需企业资质 + 审批 | Phase 2 期间提前申请 |
| e签宝/法大大等电子签约平台 | Sprint 6 | 第三方 SDK 集成 | 先做合同管理，签署能力可后接 |

### 技术风险

| 风险 | 影响 | 应对策略 |
|------|------|---------|
| Stub API 数量多，接真周期超预期 | Phase 1 延期 | Sprint 3 预留 buffer，按优先级排序接真 |
| 企微/钉钉 API 限流 | Sprint 2 数据同步不完整 | 增量同步 + 重试队列 + 限流降级 |
| Claude API 响应延迟影响 AI 推荐体验 | Phase 3 体验差 | 缓存策略 + 异步计算 + 边缘规则引擎兜底 |
| 个税申报格式变更 | Sprint 9 对接失败 | 申报数据生成与提交解耦，格式可配置 |

### 测试策略

| 层级 | 覆盖要求 | 工具 |
|------|---------|------|
| 单元测试 | 每个新增服务 ≥ 5 个测试用例 | pytest + pytest-asyncio |
| 集成测试 | 每个 Phase 结束时全链路测试 | pytest + httpx |
| 前端测试 | 核心流程 E2E | Playwright（可选） |
| 性能测试 | 薪资批量计算 ≤ 30s/1000人 | locust |

---

## 里程碑总览

```
2026 Q2                          2026 Q3                          2026 Q4
├─ Sprint 1 ─┤─ Sprint 2 ─┤─ Sprint 3 ─┤  ├─ Sprint 4 ─┤─ Sprint 5 ─┤─ Sprint 6 ─┤─ Sprint 7 ─┤  ├─ Sprint 8 ─┤─ Sprint 9 ─┤─ Sprint 10 ─┤
│  薪资项目库  │  企微/钉钉  │  API接真    │  │  绩效打分   │  积分赛马   │  电子签约   │  前端+集成  │  │  AI薪酬     │  薪税申报   │  AI前端      │
│  合规预警    │  员工同步   │  前端联调    │  │  评审周期   │  排行榜    │  薪资台账   │  测试      │  │  离职预测   │  考勤合规   │  全链路测试   │
│             │            │             │  │            │           │            │           │  │            │            │              │
▼             ▼            ▼             ▼  ▼            ▼           ▼            ▼           ▼  ▼            ▼            ▼              ▼
M1: 核心能力就绪                          M2: 产品专业化完成                                     M3: AI深度赋能上线
客户可签约上线                             对标i人事产品深度                                       建立不可复制壁垒
```

---

## 新增文件清单（全 Phase）

### 后端服务层（Python）

| # | 文件路径 | Phase | 说明 |
|---|---------|-------|------|
| 1 | `services/tx-org/src/services/salary_item_config_service.py` | P1 | 门店级薪资项目配置 |
| 2 | `services/tx-org/src/services/compliance_alert_service.py` | P1 | 合规预警扫描服务 |
| 3 | `services/tx-org/src/services/im_sync_service.py` | P1 | 企微/钉钉通讯录同步 |
| 4 | `services/tx-org/src/services/im_notify_service.py` | P1 | IM 消息推送 |
| 5 | `services/tx-org/src/services/schedule_repository.py` | P1 | 排班持久化 |
| 6 | `services/tx-org/src/services/performance_service.py` | P2 | 绩效评审 |
| 7 | `services/tx-org/src/services/points_service.py` | P2 | 员工积分 |
| 8 | `services/tx-org/src/services/e_signature_service.py` | P2 | 电子签约 |
| 9 | `services/tx-org/src/services/tax_filing_service.py` | P3 | 薪税申报 |
| 10 | `services/tx-org/src/services/attendance_compliance.py` | P3 | 考勤合规检测 |

### 后端 API 层（Python）

| # | 文件路径 | Phase | 说明 |
|---|---------|-------|------|
| 11 | `services/tx-org/src/api/compliance_routes.py` | P1 | 合规预警 |
| 12 | `services/tx-org/src/api/im_sync_routes.py` | P1 | IM 同步 |
| 13 | `services/tx-org/src/api/performance_routes.py` | P2 | 绩效 |
| 14 | `services/tx-org/src/api/points_routes.py` | P2 | 积分 |
| 15 | `services/tx-org/src/api/contract_routes.py` | P2 | 合同签约 |
| 16 | `services/tx-org/src/api/salary_advisor_routes.py` | P3 | AI 薪酬推荐 |
| 17 | `services/tx-org/src/api/tax_filing_routes.py` | P3 | 薪税申报 |

### Agent 层（Python）

| # | 文件路径 | Phase | 说明 |
|---|---------|-------|------|
| 18 | `services/tx-agent/src/agents/skills/compliance_alert.py` | P1 | 合规预警 Agent |
| 19 | `services/tx-agent/src/agents/skills/salary_advisor.py` | P3 | AI 薪酬推荐 Agent |

### 前端（TypeScript/React）

| # | 文件路径 | Phase | 说明 |
|---|---------|-------|------|
| 20 | `apps/web-admin/src/pages/hq/org/PerformancePage.tsx` | P2 | 绩效管理 |
| 21 | `apps/web-admin/src/pages/hq/org/PointsLeaderboardPage.tsx` | P2 | 积分排行 |
| 22 | `apps/web-admin/src/pages/hq/org/ContractPage.tsx` | P2 | 合同管理 |
| 23 | `apps/web-admin/src/pages/hq/org/PayrollLedgerPage.tsx` | P2 | 薪资台账 |
| 24 | `apps/web-admin/src/pages/hq/org/SalaryAdvisorPage.tsx` | P3 | AI 薪酬推荐 |
| 25 | `apps/web-admin/src/pages/hq/org/TurnoverRiskPage.tsx` | P3 | 离职风险 |
| 26 | `apps/web-crew/src/pages/MyPayslipPage.tsx` | P2 | 员工工资条 |
| 27 | `apps/web-crew/src/pages/MyPerformancePage.tsx` | P2 | 员工绩效 |

### DB Migration

| # | Phase | 涉及表 |
|---|-------|--------|
| 28 | P1 | `store_salary_configs` |
| 29 | P1 | `employees` 字段扩展（contract 相关） |
| 30 | P2 | `performance_review_cycles` + `performance_scores` |
| 31 | P2 | `employee_points_accounts` + `employee_points_transactions` + `competitions` |
| 32 | P2 | `employee_contracts` |
| 33 | P3 | `tax_filing_records` |

---

*每个 Sprint 结束时进行 code review + QA 验收。Phase 结束时进行客户演示 + 反馈收集。*
