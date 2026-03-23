# 屯象OS 人力模块升级计划 — 对标商龙i人事 23 项能力

> 来源：商龙i人事能力明细 + 乐才/奥琦玮对比分析
> 目标：取乐才排班深度 + 奥琦玮ERP集成 + i人事成本精细化&AI，打通"POS营业数据→人力决策"闭环

---

## 一、屯象OS tx-org 现有能力 vs i人事 23 项

| # | i人事能力 | 屯象OS 现状 | 差距 |
|---|---------|-----------|------|
| 1 | 138项薪资项目库 | payroll_engine 已有(基本工资/加班/提成/个税) | 🟡 有基础，缺完整项目库 |
| 2 | 多维度出勤(一人多岗) | 考勤 API 骨架 | 🔴 缺借调场景 |
| 3 | 成本5维度管理 | analyze_labor_cost Agent 已有 | 🟡 缺成本分摊 |
| 4 | 薪资台账双视角 | 无 | 🔴 需新建 |
| 5 | 钉钉/企微同步 | Employee.wechat_userid/dingtalk_userid 字段已有 | 🟡 字段有，SDK 未接 |
| 6 | 选用育留一体化 | smart_service Agent(培训) + 离职预测 | 🟡 有骨架 |
| 7 | 复杂薪酬自动化 | salary_formula_engine(1109行) 已迁移 | 🟡 需前端+审批流 |
| 8 | 绩效自动化 | score_performance Agent 已有 | 🟡 缺在线打分UI |
| 9 | AI智能排班 | serve_dispatch Agent(7/7) + schedule API | 🟢 已有核心算法 |
| 10 | AI薪资项目 | 无 | 🔴 需新建 |
| 11 | AI绩效指标库 | analyze_skill_gaps Agent | 🟡 有差距分析，缺指标库 |
| 12 | 人效预警体系 | store_health(5维) + warn_attendance Agent | 🟢 已有 |
| 13 | 多角色看板 | Shell三档 + menu_config角色裁剪 | 🟢 已有机制 |
| 14 | 电子签约 | 无 | 🔴 需新建 |
| 15 | 合同/证件到期预警 | Employee.health_cert_expiry 字段已有 | 🟡 字段有，预警逻辑缺 |
| 16 | 连续低绩效预警 | evaluate_effectiveness Agent | 🟡 有评估，缺自动预警 |
| 17 | 考勤合规 | warn_attendance Agent(出勤异常) | 🟡 有预警，缺合规检测 |
| 18 | 薪税通一体化 | compute_monthly_tax(7级累进) 已有 | 🟡 算法有，缺申报对接 |
| 19 | 出海多语言 | 无 | ⚪ Year 3 |
| 20 | 数字人AI助手 | Agent Console(Chat面板) 已有 | 🟢 已有NL查询 |
| 21 | 应用商城 | 无 | ⚪ Year 3 |
| 22 | 员工积分+赛马 | 无 | 🔴 需新建 |
| 23 | 智能管理中心 | workflow_engine 已迁移 | 🟡 有引擎，缺协同 |

**统计：🟢已有 4 项 | 🟡有基础需补齐 12 项 | 🔴需新建 5 项 | ⚪远期 2 项**

---

## 二、按优先级排列的开发任务

### P0 — 必须做（直接影响客户签约）

#### 1. 门店借调 + 工时自动拆分 + 成本分摊（i人事核心差异化）
```
新建: services/tx-org/src/services/store_transfer_service.py
- create_transfer_order(from_store, to_store, employee, start/end_date)
- compute_time_split(employee, date_range) → {store_id: hours}
- compute_cost_split(employee, date_range) → {store_id: {wage_fen, social_fen, bonus_fen}}
- generate_transfer_report() → 三表：明细分摊表 + 薪资汇总表 + 成本分析表

模型: StoreTransferOrder(employee_id, from_store, to_store, dates, status)
API: POST /org/transfers + GET /org/transfers + GET /org/cost-split-report
```

#### 2. 人效指标体系 + 行业基准值
```
新建: services/tx-org/src/services/labor_efficiency_service.py
- 5大指标（直接使用i人事行业基准）:
  - labor_cost_ratio: 目标 20%-30%
  - revenue_per_capita_yuan: 目标 ≥35000/月
  - revenue_per_hour_yuan: 目标 ≥150/时
  - guests_per_hour: 目标 ≥1.5人/时
  - work_effectiveness_pct: 目标 ≥80%
- compare_to_benchmark(store_metrics, industry_benchmark)
- generate_efficiency_alert(store_id) → 低于基准自动预警

API: GET /org/efficiency/{store_id} + GET /org/efficiency/benchmark
```

#### 3. 薪资项目库模板（138项→屯象精简版）
```
新建: services/tx-org/src/services/salary_item_library.py
- 按类型分组: 出勤类(15) / 加班类(8) / 假期类(10) / 绩效类(12) / 补贴类(10) / 扣款类(8) / 社保类(6)
- 每项带属性: item_code, item_name, tax_type(税前加/税前减/其他), calc_rule
- init_salary_items_for_store(store_id, template="standard")
```

### P1 — 强烈建议（提升产品专业度）

#### 4. 电子签约模块
```
新建: services/tx-org/src/services/e_signature_service.py
- 合同模板管理(labor_contract/confidentiality/non_compete)
- 发起签署 → 员工手机端签字 → 归档
- 到期自动提醒(30天/15天/7天三档)
```

#### 5. 绩效在线打分 + 赛马机制
```
扩展: services/tx-org/src/services/performance_service.py
- create_review_cycle(period, template, target_employees)
- submit_score(reviewer, employee, scores_by_dimension)
- generate_ranking(scope=store/region/brand) → 门店间/员工间排名
- employee_points_system: 积分规则 + 积分兑换 + 排行榜
```

#### 6. 证件到期 + 低绩效自动预警
```
扩展: services/tx-org/src/services/compliance_alert_service.py
- scan_expiring_documents(threshold_days=30) → 健康证/身份证/合同
- scan_low_performers(consecutive_months=3) → 连续低绩效员工
- 推送到企微/Agent Console
```

### P2 — 中期规划

#### 7. AI薪资项目推荐
```
基于岗位/区域/工龄推荐薪酬结构
利用 smart_service Agent 的 analyze_skill_gaps 扩展
```

#### 8. 薪税申报对接
```
个税累进算法已有(payroll_engine.compute_monthly_tax)
需对接自然人电子税务局 API
```

#### 9. 考勤深度合规
```
同设备打卡检测 + GPS异常检测 + 加班超时预警
```

---

## 三、开发工期估算

| 优先级 | 任务 | 人周 |
|--------|------|------|
| P0 | 借调+成本分摊 | 3 |
| P0 | 人效指标+基准值 | 2 |
| P0 | 薪资项目库 | 1 |
| P1 | 电子签约 | 3 |
| P1 | 绩效打分+赛马 | 3 |
| P1 | 证件/绩效预警 | 1 |
| P2 | AI薪资推荐 | 2 |
| P2 | 薪税申报 | 2 |
| P2 | 考勤合规 | 1 |
| **合计** | | **18 人周** |

---

## 四、屯象OS 的差异化路径

> **i人事强在"成本精细化"，但弱在"业务数据打通"。**
> **屯象OS 独有的 Ontology 全链路可以做到 i人事做不到的事：**

| 能力 | i人事 | 屯象OS |
|------|------|--------|
| POS 营业额 → 排班需求 | ❌ 需手工导入 | ✅ tx-trade 订单数据直接驱动 |
| 菜品销量 → 厨师绩效 | ❌ 不了解菜品 | ✅ tx-menu 菜品 + KDS 出餐时间 |
| 客流预测 → 人力预算 | ❌ 无客流数据 | ✅ serve_dispatch Agent 客流预测 |
| 损耗归因 → 厨师考核 | ❌ 无损耗数据 | ✅ waste_guard + 出品部门关联 |
| 折扣审批 → 员工信用分 | ❌ 不了解折扣 | ✅ discount_guard Agent 异常记录 |
| 会员满意度 → 服务员绩效 | ❌ 无会员数据 | ✅ member_insight 反馈归因 |

**这就是"连锁餐饮 Palantir"的壁垒——人力决策不是孤立的 HR 系统，而是建立在 Ontology 全链路数据之上的智能决策。**
