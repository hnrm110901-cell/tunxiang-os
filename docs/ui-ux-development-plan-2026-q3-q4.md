# 屯象OS UI/UX 战略调整开发计划（2026-Q3 / Q4）

> **配套文件**：
> - `docs/ui-ux-gap-analysis-2026-05.md`（差距来源）
> - `docs/ui-ux-constitution-v1.md`（验收规范）
> - `CLAUDE.md`（项目宪法 / Tier 制 / Week 8 DEMO 门槛）
>
> **覆盖周期**：2026-05-07 → 2026-12-07（7 个月，14 个双周 Sprint）
> **目标客户**：首批 — 尝在一起（品智POS）/ 最黔线 / 尚宫厨；标杆 — 徐记海鲜（23 系统替换）

---

## 一、总目标与里程碑

### 1.1 北极星指标（贯穿全程）

| 指标 | 当前 | M1（30天） | **M1 实测 2026-05-07** | M2（90天） | M3（180天） |
|------|------|-----------|----------------------|-----------|------------|
| Tier 1 测试通过率 | 部分 | 100% | **100%（19/19）** ✅ | 100% | 100% |
| P99 延迟（200桌并发） | 未实测 | < 300ms | **0.01ms**（pinzhi 单测）⚡ | < 100ms | < 100ms |
| 支付成功率 | 未实测 | > 99% | 待 #260 现场 ⏳ | > 99.9% | > 99.9% |
| 断网恢复（数据完整） | 256s 同步 | 4h | 单测覆盖（待 #260 现场）⏳ | 4h | 8h |
| **触控规范达标率（Store）** | ~70% | ≥ 95% | **100%**（KDS 72px + lint 锁定） ✅ | ≥ 99% | 100% |
| **品牌色硬编码数** | ~134 处（实测 4112） | 0 | **69**（98.3% 减幅，余 #273）⚠️ | 0 | 0 |
| **a11y 评分（axe-core）** | 未测 | 报告基线 | **基线锁定 817 处违规** ✅ | ≥ 80 | ≥ 90 |
| 占位 Agent 数（共 8 个） | 8 | 6 | **6**（#257+#258 关闭） ✅ | 2 | 0 |
| A2UI 白名单组件数 | 6 | 6 | 6 ✅ | 18 | 24 |
| Core ML 真实模型数 | 0 / 4 | 0 / 4 | 0 / 4 ✅ | 1 / 4 | 4 / 4 |
| **CI 闸门数** | 0 | 4 | **5**（含 a11y） ✅ | 5 | 5（全 strict） |
| **lint-ui 总耗时** | — | < 30s | **803ms** ⚡ | < 1s | < 1s |

### 1.2 客户里程碑映射

| 客户 | 验收时间 | 关键能力依赖 |
|------|---------|-------------|
| **尝在一起**（品智POS） | M1 末 | 主收银流程 + adapters/pinjin + Tier 1 全绿 |
| **最黔线** | M2 中 | 多门店 Admin + 报表中心 + 离线优先 |
| **尚宫厨** | M2 末 | KDS 完整 + Crew 服务员 PWA + Agent 推送 |
| **徐记海鲜 DEMO**（标杆） | M3 中（Week 8） | 全部 Tier 1 + AI Agent + A2UI + 替换 23 系统场景演示 |

### 1.3 周期性闸门（Gate）

| Gate | 时间 | 验收人 | 通过条件 |
|------|------|--------|---------|
| G1 基线闸 | 2026-06-07 | UI Lead + 创始人 | M1 全绿 + 触控/字体 CI 强制 + 尝在一起上线 |
| G2 差异化闸 | 2026-09-07 | 创始人 + 徐记海鲜技术对接人 | M2 全绿 + Admin AI NLQ + KDS 实时热力 |
| G3 行业引领闸 | 2026-12-07 | 创始人 + 行业评审 | Week 8 DEMO 通过 + A2UI 白皮书 |

---

## 二、阶段一：基线对齐（M1，30 天，Sprint 1-2）

**Epic 跟踪**：
- Sprint 1：[#252 Epic] tx-touch 抽包 + KDS 修复 + CI 闸门
- Sprint 2：[#263 Epic] a11y 基线 + 占位 Agent + 尝在一起首店上线

### 2.1 阶段目标

- 解决 P0 阻断级差距，让所有 Store 终端通过 tx-ui 规范
- 抽出 `packages/tx-touch` 作为 v1.0 起点
- 建立 CI 质量闸门（防止规范漂移）
- 服务尝在一起首批上线

### 2.2 Sprint 1（W1-W2，2026-05-07 → 2026-05-21）

| ID | Issue | 任务 | 模块 | 人天 | Tier | 依赖 | 验收标准 |
|----|-------|------|------|-----|------|------|---------|
| S1-01 | [#244](https://github.com/hnrm110901-cell/tunxiang-os/issues/244) | 抽出 `packages/tx-touch` 包结构 | shared | 3 | T2 | — | 包初始化 + 编译通过 + 三个 app（pos/kds/crew）依赖切换不报错 |
| S1-02 | [#245](https://github.com/hnrm110901-cell/tunxiang-os/issues/245) | 迁移 TXButton/TXCard/TXNumpad/TXSelector/TXScrollList 至新包 | tx-touch | 5 | T2 | #244 | 现有页面 0 视觉回归（截图 diff） |
| S1-03 | [#246](https://github.com/hnrm110901-cell/tunxiang-os/issues/246) | 迁移 TXAgentAlert/TXKDSTicket/TXPaymentPanel/TXDishCard | tx-touch | 4 | T2 | #244 | 同上 |
| S1-04 | [#247](https://github.com/hnrm110901-cell/tunxiang-os/issues/247) | 抽 useOffline / useAgentSSE / useAgentInsights / useLongPress / useSwipe / useHaptic 至 tx-touch/hooks | tx-touch | 3 | T2 | #244 | 三 app 引用统一，行为一致 |
| S1-05 | [#248](https://github.com/hnrm110901-cell/tunxiang-os/issues/248) | KDS 关键操作触控升 72px | web-kds | 3 | T2 | #246 | KDS 完成/加急/退回 全部 ≥ 72×72；CI lint 通过 |
| S1-06 | [#249](https://github.com/hnrm110901-cell/tunxiang-os/issues/249) | KDS 字体规范修订实装（订单号 32px / 标题 24-28px / 菜品行 20px） | web-kds | 2 | T2 | #246 | 视觉验证 + CI lint |
| S1-07 | [#250](https://github.com/hnrm110901-cell/tunxiang-os/issues/250) | 写 CI lint：`lint:tap-target` + `lint:font-size` + 品牌色硬编码扫描 | infra/ci | 3 | T2 | — | infra/ci/ui-quality-gate.yml 新建；本地+CI 都跑通 |
| S1-08 | [#251](https://github.com/hnrm110901-cell/tunxiang-os/issues/251) | 全项目硬编码品牌色清理（grep 134 处 → 0） | 全前端 | 4 | T2 | #244 + #250 | grep 命中数 = 0；视觉 0 回归 |

**Sprint 1 总人天**：27（约 2 人 × 14 天 = 28，刚好填满）
**关键路径**：#244 → (#245 ∥ #246 ∥ #247) → (#248 ∥ #249) → (#250 ∥ #251)

### 2.3 Sprint 2（W3-W4，2026-05-22 → 2026-06-07）

| ID | Issue | 任务 | 模块 | 人天 | Tier | 依赖 | 验收标准 |
|----|-------|------|------|-----|------|------|---------|
| S2-01 | [#253](https://github.com/hnrm110901-cell/tunxiang-os/issues/253) | a11y 基线扫描报告（全 16 app 跑 axe-core） | infra | 2 | T3 | — | 报告写入 docs/a11y-baseline-2026-05.md，标注 Top 30 问题 |
| S2-02 | [#254](https://github.com/hnrm110901-cell/tunxiang-os/issues/254) | aria-label 全覆盖：所有 IconButton + 图标交互元素 | 全前端 | 5 | T3 | #253 | axe-core 报告 missing-label 类问题 = 0 |
| S2-03 | [#255](https://github.com/hnrm110901-cell/tunxiang-os/issues/255) | Tab focus 顺序梳理（Admin 重点） | web-admin | 3 | T3 | #253 | 主要页面 Tab 顺序符合视觉顺序，Esc 关闭弹层 |
| S2-04 | [#256](https://github.com/hnrm110901-cell/tunxiang-os/issues/256) | 焦点环 `:focus-visible` 全终端样式 | tx-touch + admin | 2 | T3 | #253 | 视觉验证 |
| S2-05 | [#257](https://github.com/hnrm110901-cell/tunxiang-os/issues/257) | 占位 Agent 补全 P0：voice_order Agent | tx-agent | 3 | T1 | — | 真实 Claude API 调用 + 语音意图解析 + AgentDecisionLog 写入 |
| S2-06 | [#258](https://github.com/hnrm110901-cell/tunxiang-os/issues/258) | 占位 Agent 补全 P0：attendance_compliance Agent | tx-agent | 3 | T2 | — | 同上 |
| S2-07 | [#259](https://github.com/hnrm110901-cell/tunxiang-os/issues/259) | 尝在一起：adapters/pinjin POS 数据写入 Tier 1 测试覆盖 | tx-trade/adapters | 4 | T1 | — | test_pinjin_tier1.py 覆盖 200 桌并发 / RLS / 离线 4h |
| S2-08 | [#260](https://github.com/hnrm110901-cell/tunxiang-os/issues/260) | 尝在一起：主收银流程现场联调 | web-pos + tx-trade | 4 | T1 | #259 | 商米 T2 上跑通点单→结算→打印→出餐全流程 |
| S2-09 | [#261](https://github.com/hnrm110901-cell/tunxiang-os/issues/261) | DEVLOG.md / progress.md 更新规范脚本 | scripts | 1 | T3 | — | scripts/update-devlog.sh 一键追加格式化记录 |
| S2-10 | [#262](https://github.com/hnrm110901-cell/tunxiang-os/issues/262) | M1 闸门评审材料 | docs | 1 | T3 | 全部 | 报告 + 演示视频 |

**Sprint 2 总人天**：28
**关键路径**：#253 → (#254 ∥ #255 ∥ #256) ‖ (#257 ∥ #258) ‖ (#259 → #260) ‖ #261 → #262

### 2.4 M1 验收（G1 闸门）

- [ ] 所有 P0 差距清零（参见差距分析报告 4.1 节）
- [ ] CI ui-quality-gate 强制（触控 / 字体 / 硬编码色 / AntD 越界）
- [ ] axe-core 基线报告归档
- [ ] **尝在一起首店上线**，2 周稳定运行
- [ ] DEVLOG.md / progress.md 闭环更新机制运行

---

## 三、阶段二：差异化突破（M2，90 天，Sprint 3-8）

### 3.1 阶段目标

- 兑现 P1 差异化窗口，建立"中国餐饮 SAAS 唯一具备 X 能力"的定位
- 服务最黔线 / 尚宫厨上线
- 为 Week 8 DEMO（徐记海鲜）做能力储备

### 3.2 Sprint 3（W5-W6，2026-06-08 → 2026-06-21）：A2UI 扩展

| ID | 任务 | 模块 | 人天 | Tier | 验收 |
|----|------|------|-----|------|------|
| S3-01 | A2UI 白名单扩展 6 → 12（增 Form / Map / Heatmap / Timeline / Cascader / Tabs） | tx-touch/a2ui | 8 | T2 | 每个组件含 Storybook 案例 + 安全 review 通过 |
| S3-02 | A2UI 协议文档（中文）+ 安全 review 流程 | docs | 3 | T3 | docs/a2ui-protocol-cn.md |
| S3-03 | tx-agent → A2UI Surface 生成器（折扣预警/会员洞察/库存告警 三个 demo） | tx-agent | 5 | T2 | Agent 输出 JSON Surface，前端渲染卡片 |
| S3-04 | TXAgentAlert 升级支持 critical/warning/info 三级 + TTS 触发 | tx-touch | 3 | T2 | KDS 超时事件触发声音 |

### 3.3 Sprint 4（W7-W8，2026-06-22 → 2026-07-05）：Admin AI NLQ

| ID | 任务 | 模块 | 人天 | Tier | 验收 |
|----|------|------|-----|------|------|
| S4-01 | Admin 端 AI NLQ 浮动按钮 + 对话面板 | web-admin | 5 | T2 | 仪表盘右上角浮动按钮，点击展开聊天面板 |
| S4-02 | NLQ → 自然语言查询 SQL（tx-brain 接入） | tx-brain | 5 | T1 | "上周 Top 5 菜" 真实返回数据，跨租户隔离 |
| S4-03 | NLQ → 直接执行三类操作（菜单更新 / 86 物料 / 排班修改） | tx-agent | 5 | T1 | 操作前二次确认 + AgentDecisionLog 留痕 |
| S4-04 | NLQ "Pin 洞察" 功能（保存到驾驶舱 Feed） | web-admin | 3 | T3 | 用户 Pin 后下次访问可见 |

### 3.4 Sprint 5（W9-W10，2026-07-06 → 2026-07-19）：KDS 实时热力 + 最黔线

| ID | 任务 | 模块 | 人天 | Tier | 验收 |
|----|------|------|-----|------|------|
| S5-01 | KDS 实时档口热力图组件（基于 `/predict/traffic`） | web-kds | 5 | T2 | 显示当前各档口负载 / 预计峰值时间 |
| S5-02 | Mac mini `/predict/traffic` 完善（规则版精度提升） | edge/coreml-bridge | 4 | T2 | 与历史数据对比 MAPE < 20% |
| S5-03 | 最黔线：多门店 Admin 联调 | web-admin | 3 | T1 | 总部能切换 5 家门店，数据隔离正确 |
| S5-04 | 最黔线：报表中心场景化（折扣 / 库存 / 员工三大报表） | web-admin/analytics | 5 | T2 | 三类报表上线 |
| S5-05 | 离线 SLA 计时器组件（顶部状态栏） | tx-touch | 3 | T2 | 显示"已缓存 N 单 / 离线 X 小时 / 距离极限 4-X 小时" |

### 3.5 Sprint 6（W11-W12，2026-07-20 → 2026-08-02）：TTS + 占位 Agent

| ID | 任务 | 模块 | 人天 | Tier | 验收 |
|----|------|------|-----|------|------|
| S6-01 | Mac mini TTS `/speak` 端点（Edge TTS 或 macOS say） | edge/mac-station | 3 | T2 | 接收文本返回音频流 |
| S6-02 | KDS 关键事件 TTS 播报（新单/超时/加急） | web-kds | 3 | T2 | 实地厨房噪音环境清晰可闻 |
| S6-03 | 收银员误操作 TTS 提示（毛利破底线 / 库存不足） | web-pos | 2 | T2 | 配合 SmartSidebar 视觉提示 |
| S6-04 | 占位 Agent 补全：points_advisor | tx-agent | 3 | T2 | 真实 Claude API + 决策留痕 |
| S6-05 | 占位 Agent 补全：salary_advisor | tx-agent | 3 | T2 | 同上 |
| S6-06 | 占位 Agent 补全：banquet_contract_agent | tx-agent | 3 | T2 | 宴席合同生成 + 审核 |

### 3.6 Sprint 7（W13-W14，2026-08-03 → 2026-08-16）：Crew + 尚宫厨

| ID | 任务 | 模块 | 人天 | Tier | 验收 |
|----|------|------|-----|------|------|
| S7-01 | Crew 端 PWA 推送通知（Agent 主动催菜建议） | web-crew | 4 | T2 | 服务员手机收到 Agent 建议 |
| S7-02 | Crew 端店长看板 Agent 洞察集成 | web-crew | 3 | T2 | 店长看到三色门店健康度 |
| S7-03 | Crew 端单手拇指可达性优化 | web-crew | 3 | T2 | 核心操作 ≤ 屏幕底部 120px |
| S7-04 | 尚宫厨：KDS 全套现场联调 | web-kds | 4 | T1 | 商米 D2 平板上 30+ 桌并发 |
| S7-05 | 尚宫厨：Crew 端 5 名服务员实测 | web-crew | 3 | T1 | 高峰餐时 30 分钟无操作错误 |
| S7-06 | A2UI 白名单扩展 12 → 18（增 Stepper / Calendar / Rating / Empty / Skeleton / Toast） | tx-touch/a2ui | 6 | T2 | 每个组件 Storybook + 安全 review |

### 3.7 Sprint 8（W15-W16，2026-08-17 → 2026-09-07）：M2 收尾 + Week 8 准备

| ID | 任务 | 模块 | 人天 | Tier | 验收 |
|----|------|------|-----|------|------|
| S8-01 | 占位 Agent 补全：ai_marketing_orchestrator | tx-agent | 4 | T2 | — |
| S8-02 | 占位 Agent 补全：剩余 1 个（按客户优先级排） | tx-agent | 3 | T2 | — |
| S8-03 | a11y 提升至 ≥80 分（axe-core） | 全前端 | 6 | T3 | 报告 |
| S8-04 | 200 桌并发压测（DEMO 环境，徐记海鲜数据） | infra | 4 | T1 | P99 < 200ms |
| S8-05 | 4h 断网压测（LWW + 终态豁免验证） | edge/sync-engine | 4 | T1 | 重连后 0 丢失、0 冲突 |
| S8-06 | M2 闸门评审材料 | docs | 2 | T3 | 演示视频 + 数据报告 |

### 3.8 M2 验收（G2 闸门）

- [ ] A2UI 白名单 ≥ 18 组件
- [ ] Admin AI NLQ 上线，三类对话执行可用
- [ ] KDS 实时档口热力 + TTS 播报
- [ ] 离线 SLA 计时器全终端
- [ ] **最黔线 + 尚宫厨上线**
- [ ] 占位 Agent ≤ 2 个
- [ ] P99 < 200ms / 4h 断网无丢
- [ ] axe-core ≥ 80 分

---

## 四、阶段三：行业引领（M3，90 天，Sprint 9-14）

### 4.1 阶段目标

- 完成 Week 8 DEMO（徐记海鲜验收）
- Core ML 真实模型注入（替换规则版）
- 建立 A2UI 中国餐饮首发地位
- 国际化与无障碍达到行业领先

### 4.2 Sprint 9（W17-W18，2026-09-08 → 2026-09-21）：Core ML 模型 #1

| ID | 任务 | 模块 | 人天 | Tier | 验收 |
|----|------|------|-----|------|------|
| S9-01 | dish-time 预测模型训练（基于历史出餐数据） | scientist + tx-brain | 8 | T2 | MAPE < 10% |
| S9-02 | dish-time .mlmodel 导出 + Mac mini 部署 | edge/coreml-bridge | 3 | T2 | 推理延迟 < 50ms |
| S9-03 | KDS 接入预测出餐时间（替换规则版） | web-kds | 3 | T2 | 实地验证 |
| S9-04 | 角色感 Dashboard 设计稿（老板/店长/厨师长 三套首屏） | designer | 4 | T2 | UI 评审通过 |

### 4.3 Sprint 10（W19-W20，2026-09-22 → 2026-10-05）：角色感 Dashboard + 模型 #2

| ID | 任务 | 模块 | 人天 | Tier | 验收 |
|----|------|------|-----|------|------|
| S10-01 | 角色感 Dashboard 老板视图（营收/利润/扩张） | web-admin | 5 | T2 | 上线 |
| S10-02 | 角色感 Dashboard 店长视图（门店健康度/任务/异常） | web-admin | 5 | T2 | 上线 |
| S10-03 | 角色感 Dashboard 厨师长视图（出品/损耗/食安） | web-admin | 5 | T2 | 上线 |
| S10-04 | discount-risk 模型训练 + 部署 | scientist + edge | 6 | T2 | 准确率 > 85% |

### 4.4 Sprint 11（W21-W22，2026-10-06 → 2026-10-19）：i18n 扩展 + 模型 #3

| ID | 任务 | 模块 | 人天 | Tier | 验收 |
|----|------|------|-----|------|------|
| S11-01 | i18n 框架升级（ICU MessageFormat + 动态加载） | 全前端 | 5 | T3 | — |
| S11-02 | 全终端中文文案外置 → locales/zh-CN.json | 全前端 | 6 | T3 | grep 中文硬编码 = 0 |
| S11-03 | 繁体（zh-TW）文案翻译 + Admin/MiniApp 上线 | 全前端 | 4 | T3 | 切换可用 |
| S11-04 | traffic 客流预测模型训练 + 部署 | scientist + edge | 5 | T2 | 节假日效应 MAPE < 25% |

### 4.5 Sprint 12（W23-W24，2026-10-20 → 2026-11-02）：暗色主题切换 + 模型 #4

| ID | 任务 | 模块 | 人天 | Tier | 验收 |
|----|------|------|-----|------|------|
| S12-01 | Admin 暗色主题切换 | web-admin | 4 | T3 | 用户偏好持久化 |
| S12-02 | Store 终端高对比度主题 | tx-touch | 4 | T3 | `prefers-contrast: more` 支持 |
| S12-03 | 色弱模式（不仅靠红绿） | tx-touch | 3 | T3 | 危险/成功配图标 |
| S12-04 | dish-price 动态定价模型 + 部署 | scientist + edge | 6 | T1 | 三条硬约束保护（毛利底线） |

### 4.6 Sprint 13（W25-W26，2026-11-03 → 2026-11-16）：徐记海鲜 DEMO 集训

| ID | 任务 | 模块 | 人天 | Tier | 验收 |
|----|------|------|-----|------|------|
| S13-01 | 徐记海鲜场景脚本（替换 23 系统的 7 个核心场景） | docs + 创始人 | 3 | T1 | 脚本通过 |
| S13-02 | 场景 1-3 现场演练（订单/支付/会员） | 全栈 | 4 | T1 | 通过 |
| S13-03 | 场景 4-7 现场演练（库存/食安/财务/Agent） | 全栈 | 4 | T1 | 通过 |
| S13-04 | 200 桌并发 + 4h 断网终极压测 | infra | 5 | T1 | 全绿 |
| S13-05 | a11y 提升至 ≥ 90 分 | 全前端 | 4 | T3 | 报告 |

### 4.7 Sprint 14（W27-W28，2026-11-17 → 2026-12-07）：Week 8 DEMO + A2UI 白皮书

| ID | 任务 | 模块 | 人天 | Tier | 验收 |
|----|------|------|-----|------|------|
| S14-01 | A2UI 白名单扩至 24 组件（v1.0 完整版） | tx-touch/a2ui | 6 | T2 | — |
| S14-02 | A2UI 中文白皮书 + 开源 demo | docs | 5 | T3 | 行业首发 |
| S14-03 | **徐记海鲜 Week 8 DEMO** | 全员 | 7 | T1 | 通过验收 |
| S14-04 | M3 闸门评审 + 全年回顾 | docs | 3 | T3 | — |

### 4.8 M3 验收（G3 闸门 + Week 8 DEMO）

| 指标 | 门槛 |
|------|------|
| Tier 1 全绿 | 100% |
| P99 延迟 | < 200ms（200 桌并发） |
| 支付成功率 | > 99.9% |
| 断网恢复 | 4h 内 0 数据丢失 |
| 收银员零培训上手 | 现场用户测试通过 |
| Core ML 模型 | 4 / 4 真实模型 |
| A2UI 白名单 | 24 组件 |
| 占位 Agent | 0 |
| a11y 评分 | ≥ 90 |
| 触控/字体/硬编码色 lint | 100% 通过 |

---

## 五、关键依赖与并行计划

### 5.1 任务依赖图（关键路径）

```
S1-01 (tx-touch 抽包)
  ├── S1-02..04 (组件迁移)
  │     └── S1-05/06 (KDS 修复)
  │           └── S1-07/08 (CI 闸门)
  └── S2-02..04 (a11y 基线)

S2-07 (品智 adapter Tier1) ──┐
                             ├──→ 尝在一起 上线 (M1 末)
S2-08 (尝在一起联调) ─────────┘

S3-01..04 (A2UI 扩 12)
  └── S4-01..04 (Admin AI NLQ)
        └── S5-01..05 (KDS 热力 + 最黔线)
              └── S6-01..06 (TTS + Agent)
                    └── S7 (尚宫厨)
                          └── S8 (M2 闸门)

S9-01 (模型#1) ──┬── S10 (Dashboard + 模型#2)
                 ├── S11 (i18n + 模型#3)
                 ├── S12 (暗色 + 模型#4)
                 └── S13 (DEMO 集训)
                       └── S14 (Week 8 + 白皮书)
```

### 5.2 资源建议（最小可行配置）

| 角色 | 人数 | 主责范围 |
|------|-----|---------|
| 前端 Lead | 1 | tx-touch / Admin / 全终端协调 |
| 前端工程师 | 2 | apps/* 实施 |
| 后端 / Agent 工程师 | 2 | tx-agent / tx-brain / edge |
| 数据科学 / Core ML | 0.5 | 模型训练 + 导出（Sprint 9 起） |
| 设计师 | 0.5 | 组件库 / Dashboard / 暗色主题 |
| QA | 1 | Tier 1 测试 + 现场联调 |
| **合计** | **7** | — |

总人天估算：14 sprint × 28 人天 / sprint = **392 人天 ≈ 7 人 × 7 个月**

---

## 六、风险与缓解

| 风险 | 概率 | 影响 | 缓解策略 |
|------|------|------|---------|
| tx-touch 抽包导致视觉回归 | 中 | 高 | 截图 diff 自动化（Chromatic / Playwright），灰度 5% |
| KDS 触控 72px 视觉过密 | 中 | 中 | 同步调整网格列数（240px → 280px），单屏少 1 列 |
| Core ML 模型训练延期 | 高 | 中 | 规则版兜底，模型注入是优化非阻断 |
| 客户现场硬件兼容（商米 T2/D2） | 中 | 高 | 提前 2 sprint 做硬件兼容测试 |
| A2UI 安全 review 拖慢节奏 | 中 | 中 | 提前定义安全契约 / 预批模板 |
| Agent 占位补全质量不稳 | 中 | 高 | Tier 划分严格，T1 必须 TDD |
| 创始人时间不足 | 中 | 高 | 闸门评审排期前置 + 异步审批 |
| 三条硬约束 UI 表达漏掉新场景 | 低 | 高 | 每个 Agent PR 都必须列出 constraints_check 表达截图 |

---

## 七、监控与汇报机制

### 7.1 每日

- 每个工程师当日结束更新 `DEVLOG.md`（按 CLAUDE.md 第十六条格式）
- 每个会话结束更新 `docs/progress.md`（防漂移）

### 7.2 每周

- 周一站会：上周 done / 本周 plan / 阻塞
- 周五指标：触控/字体/硬编码色 lint 数 + a11y 评分 + 占位 Agent 剩余 + Tier 1 测试通过率

### 7.3 每 Sprint

- Sprint Review：演示 + 验收标准核对
- Sprint Retro：流程改进
- 更新本计划的"实际完成 / 计划差异"列

### 7.4 每月

- 客户反馈汇总（尝在一起 / 最黔线 / 尚宫厨）
- 风险矩阵更新

### 7.5 闸门（M1 / M2 / M3）

- 创始人评审 + 客户对接人评审
- 评审材料：演示视频 + 数据报告 + 风险更新 + 下阶段计划微调

---

## 八、与 CLAUDE.md 防漂移规范的衔接

每个 Sprint 任务接受时，工程师必须在会话开头按 CLAUDE.md 第十八条声明：

```
## 本次会话目标
[任务 ID 与功能]

## 不得触碰的边界
- [ ] shared/ontology/ 任何文件
- [ ] 已应用的迁移
- [ ] RLS 策略文件
- [ ] 核心导航布局（除非 V-meeting 通过）

## 本次涉及范围
- 服务：[服务名]
- 迁移版本：vXXX → vXXX（如有）
- Tier 级别：[ ] T1  [ ] T2  [ ] T3
```

任务完成时按第十八条更新 `docs/progress.md`。

涉及 Tier 1 改动必须按第十九条独立验证（新会话从验证视角重检）。

---

## 九、版本与变更

| 版本 | 日期 | 改动 |
|------|------|------|
| v1.0 | 2026-05-07 | 初版，覆盖 7 个月 14 Sprint |

变更流程：每 Sprint Retro 后微调；M1 / M2 / M3 闸门后大版本更新。

---

**签发**：未了已（创始人）
**起草**：UI/UX Lead + Claude Code 协作
**生效**：2026-05-07
**首个 Sprint 开始**：2026-05-07
