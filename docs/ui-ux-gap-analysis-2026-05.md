# 屯象OS UI/UX 战略调整差距分析报告（2026-05-07）

> **目的**：在 UI/UX 战略调整前，建立"规范真理源 → 代码现状 → 行业对标"的三轴坐标系，列出每一项差距的严重程度与处置优先级。
> **方法**：以 `.claude/skills/tx-ui` 规范为真理源 → 抽样阅读各前端应用源码 → 与 Toast / Lightspeed / Square / 客如云 等竞品 2025H2-2026H1 真实操作流程比对。
> **范围**：apps/ 16 个前端 + edge/ 边缘智能 + tx-agent / tx-brain 服务。

---

## 一、屯象OS UI/UX 设计理念（真理源摘要）

### 1.1 三套终端、三套技术栈、三套设计语言

| 终端 | 技术栈 | 组件库 | 触控规则 | 字号体系 |
|------|--------|--------|----------|----------|
| **Admin**（总部 8 域） | React 18 + AntD 5.x + ProComponents | ProTable / ProForm / ProLayout | 桌面鼠标，无触控约束 | 14px 正文 / 24px h1 |
| **Store-POS / KDS / Crew** | React 18 + UnoCSS | **TXTouch（自研，禁用 AntD）** | 最小 48×48 / 推荐 56×56 / 关键 72×72 | 18px 正文 / 32px h1，**最小 16px 不可破** |
| **MiniApp** | uni-app + Vue 3 + Pinia | uni-ui + 自定义 | 88rpx 标准按钮 | 28rpx 正文 / 44rpx h1 |

### 1.2 品牌色与语义色（唯一真相）

```
品牌主色   #FF6B35   按钮/链接/选中态/品牌标识
辅色       #1E2A3A   Admin 侧边栏/深色标题
success    #0F6E56   毛利率达标/出餐正常
warning    #BA7517   即将超时/毛利率偏低/库存偏低
danger     #A32D2D   超时/毛利率破底线/沽清/Agent critical
info       #185FA5   AI 推荐标记/Agent 建议/CDP 洞察
```

### 1.3 不可违反的设计铁律

1. 品牌色 `#FF6B35` 唯一，从 Token 引用，**不允许硬编码**
2. Store 终端 **禁止 AntD、禁止 select 下拉、禁止 hover 唯一反馈**
3. Store 终端字体 **绝对底线 16px**，KDS 标题 ≥24px（厨师 2 米外阅读）
4. Agent 预警 `TXAgentAlert` 固定屏幕顶部，**用户不可关闭**
5. 三条硬约束可视化：毛利低于阈值红色、临期食材警告色、出餐超时倒计时
6. 所有 API 调用带 `X-Tenant-ID` header（RLS 多租户隔离）

---

## 二、已完成开发的架构与代码明细

### 2.1 全局 Design Token 落地度

| 资产 | 文件证据 | 现状 | 评分 |
|------|----------|------|------|
| 色彩源文件 | `docs/color-system.md` v4 | ✅ 已冻结，44+ 色值含 WCAG AAA 验证（白/深青 14.3:1） | A |
| 共享 Token 包 | `packages/tx-tokens/src/tokens.ts` | ⚠️ 已定义 txColors/txRadius/txSpacing/**txTapTarget(48/56/72)**，但仅部分应用引用 | C+ |
| Admin AntD 主题 | `apps/web-admin/src/theme/antd-theme.ts` | ✅ ConfigProvider 注入完整 | B+ |
| Store base-theme | `apps/web-pos/src/design-system/base-theme.ts` | ⚠️ 定义齐全（TX 13色/BTN 7类/INPUT 3类），**仅 web-pos 引用**，未抽到 packages/tx-touch | C |
| KDS 触控 Token | `apps/web-kds/src/pages/KdsLoginPage.tsx:8` | 🔴 注释声明"戴手套 72px"，**代码实装 48px** | F |
| MiniApp Token | `apps/miniapp-customer-v2/src/uni.scss` | ⚠️ Token 部分注入，h5/v1/v2 三套并存 | C |

### 2.2 Admin 终端（web-admin）完成度

| 模块 | 状态 | 证据 |
|------|------|------|
| 仪表盘指标卡片 + 趋势 | ✅ | `pages/DashboardPage.tsx`、`StatisticCard` + `Line` 图近 30 天 |
| 报表中心（域 G） | ✅ | `analytics/{ReportCenter,DailyReport,DishAnalytics,WineDeposit}Page.tsx` |
| HQ 多门店穿透 | ✅ | `HQDashboardPage.tsx`、租户/品牌/门店 Selector |
| **AI NLQ 专属入口** | 🔴 缺失 | 仅 web-pos 有 CommandPalette，admin 无对应 UI 入口 |
| **Agent 管理界面（域 H）** | ⚠️ 部分 | 决策日志 Timeline 已有组件，监控仪表盘未见 |
| **角色感 Dashboard**（老板/店长/厨师长差异化首屏） | 🔴 缺失 | 全角色看同一个 Dashboard |
| TODO/占位 | ⚠️ 339 行 | 集中在筛选 UI / 导出按钮 / 图表标签 |

### 2.3 Store-POS 终端（web-pos）—— 最关键、完成度最高

| 模块 | 状态 | 证据 |
|------|------|------|
| 主收银/点餐/结算/桌台/外卖/挂单 | ✅ | `pages/{Cashier(610), Order(546), Settle(505), TableMap, OmniChannelOrders, Queue}Page.tsx` 共 50 个页面，真实可用非占位 |
| **离线优先能力** | ✅ | `hooks/useOffline.ts`(356 行) IndexedDB 存储 + 重连 replay + idempotency 防重扣 |
| **TXBridge 外设抽象** | ✅ | `lib/TXBridge.ts` 三路优先级：商米 SDK → 蓝牙打印 → Mac mini HTTP 转发 |
| 打印/钱箱/扫码 | ✅ | TXBridge 已集成 |
| 副屏/客显 | ⚠️ | TXBridge 接口定义但无组件实装 |
| 电子秤 | ⚠️ | `startScale` / `onScaleData` 签名存在，未见调用 |
| **Cmd+K CommandPalette** | ✅ | `components/CommandPalette.tsx` 完整实装含分组+搜索+Agent 模式 |
| **AI Agent 嵌入 UI** | ✅ | `SmartSidebar.tsx`（右侧 326px）+ `InsightCard.tsx` + `ExceptionPage.tsx`（折扣守护异常）+ `SettlePage` 折扣 AI 抽屉 |
| **A2UI Renderer**（Google A2UI v0.8 兼容） | ✅ | `components/a2ui/A2UIRenderer.tsx` 递归渲染 + 白名单组件（Card/List/Table/Badge/Progress/Chart 6+） |
| **状态/错误处理** | ✅ | `ErrorBoundary`(3000ms 自愈+遥测) + `Toast`(离线特殊处理) + `CashierBoundary` 结算专属 |
| 复合支付（现金+扫码+会员卡+挂账） | ✅ | `SettlePage.tsx:92` 含 member_balance/card 模式 |
| TODO/占位 | ⚠️ 107 行 | 集中 UI 边界，业务逻辑 ~98% 在位 |

### 2.4 Store-KDS 终端（web-kds）

| 模块 | 状态 | 证据 |
|------|------|------|
| 订单卡片状态机 | ✅ | `KDSBoardPage.tsx`(1229 行) status: pending/cooking/done |
| 倒计时 + 三色编码（绿/黄/红） | ✅ | `getTimeStatusFromRules`(L108-119) + CSS vars `--tx-kds-red:#ff4d4f` |
| 多档口拆分（中/凉/酒水） | ✅ | `GroupMode='by-table'\|'by-dish'` + `ZoneKitchenBoard` |
| 语音播报 | ✅ | `audio.ts`(2714B) `playNewOrder` / `playTimeout` + `warmUpAudio` |
| 外卖订单平台标识 | ✅ | `DeliveryOrderBadge.tsx` |
| **关键字体 ≥24px**（规范要求） | 🔴 | 实装 20px，违反 Store 规范 |
| **关键操作触控 72px** | 🔴 | 实装 48px，戴手套场景不达标 |
| **SwimLane 出餐节奏 timeline** | ⚠️ | `/swimlane` 路由存在，深度需验证 |

### 2.5 Store-Crew 服务员手机端（web-crew）

- ✅ 6 Tab + 全屏流框架（PWA 配置）
- ✅ "我的桌台 / 加菜 / 催菜 / 会员扫码 / 店长看板" 路由齐全
- ⚠️ 触控反馈 `transform: scale(0.97)` 未见统一应用

### 2.6 MiniApp 终端（miniapp-customer-v2 + h5-self-order）

| 模块 | 状态 | 证据 |
|------|------|------|
| 跨端编译（微信 + 抖音 + H5） | ✅ | uni-app 配置 |
| 菜单/购物车/下单/支付/会员/优惠券/大厨到家/企业订餐 | ✅ | `pages/` 12 主要页面 |
| **AI 推荐组件** `tx-ai-recommend` | ✅ | 组件已实装，带"AI"标签 |
| **i18n 多语言** | ⚠️ | 仅 h5-self-order 4 语言（zh/en/ja/ko），miniapp 全中文 |
| 微信支付 / 抖音支付 | ✅ | 走后端下单 + `uni.requestPayment` |

### 2.7 Agent OS 与 Edge 智能层

| 子系统 | 实测 | 评分 |
|--------|------|------|
| Skill Agent 总数 | 63 个文件（CLAUDE.md 标 9 核心 + 73 Actions） | — |
| **真接 Claude API**（实测） | 13 个：discount_guard / smart_menu / member_insight / rfm_outreach / sales_coach / cost_diagnosis / cost_root_cause / budget_forecast / finance_audit / salary_anomaly / crisis_responder / reservation_concierge | A |
| 业务规则 Agent | 42 个：serve_dispatch / smart_service / inventory_alert 等纯逻辑推理 | B+ |
| **占位/TODO Agent** | 8 个：attendance_compliance / banquet_contract / **voice_order** / points_advisor / salary_advisor / ai_marketing_orchestrator | 🔴 |
| Actions 总数（实测 grep） | **134 个**（高于 CLAUDE.md 标 73） | A |
| AgentDecisionLog 落地 | ✅ `shared/db-migrations/versions/v099_agent_decision_logs.py` 含 RLS + 索引 | A |
| 前端推送通道 | ✅ `useAgentSSE.ts` SSE 优先 + `useAgentInsights.ts` 30s 轮询回退 | A |
| Mac mini coreml-bridge | ⚠️ Swift 726 行，4 端点（dish-time / discount-risk / traffic / dish-price）+ /transcribe，**全部 graceful fallback 到统计规则**，`.mlmodel` 二进制未制作 | C |
| Whisper 语音识别 | ✅ `edge/mac-station/src/voice_service.py` 含 9 意图路由 | B+ |
| **TTS 语音输出** | 🔴 缺失 | F |

---

## 三、连锁餐饮 SAAS 行业对标（2025H2 – 2026H1 真实操作）

### 3.1 国际竞品 AI 化进度

| 竞品 | 上线 | 真实 UI 形态 | 能力边界 |
|------|------|-------------|---------|
| **Toast IQ Conversational Assistant** | 2025-10 | Toast Now App + Web 后台聊天界面 + "For You" 推送 Feed + "Explore" 提示词 | **可对话执行**：菜单修改/86 物料/排班修改 — 业内唯一 |
| **Lightspeed AI** | 2026-01 | 后台问答界面（追问） | **只读分析**，不执行操作 |
| **Lightspeed Tempo** | 2025-12 | Back Office > Analytics > Tempo（Order Key Moments / Global Order Patterns / Table Occupancy） | **事后分析**，非实时作战 |
| **Square AI Assistant** | 2025-10 | 嵌入 Dashboard，含位置上下文（天气/活动），可 pin 洞察 | 销售/人力/客户问答 |
| **Square AI Voice Ordering** | 2025-10 | 电话接单 AI（100% 应答） → 直入 POS/KDS | 订单生成，非菜单查询 |

### 3.2 中国本土厂商

| 厂商 | AI 化进度 |
|------|----------|
| **客如云** | 2025-10 发布"五大智能体"：超级店员（语音点餐+KDS 智能排序）/ 智能小 On（**角色差异化日报**：老板/店长/厨师长不同摘要）/ 超级 IT 等。UI 入口未公开。 |
| **哗啦啦 / 天财商龙 / 银豹** | 2025 公开披露的 LLM 落地极少，停留在扫码点餐 / 多支付 / 供应链宣传 |

### 3.3 协议层与触控标准

- **Google A2UI v0.8** (2025-12 开源)：Agent 输出 JSON → 客户端原生组件渲染。**全球暂无餐饮 SAAS 商业落地**。Flutter GenUI SDK / CopilotKit 已兼容。
- **触控目标行业基线**：WCAG 2.5.5 = 44×44；Android = 48×48；主流 POS 主操作 60–80dp，次操作 44dp 沿（误触高频区）。
- **Toast POS 暗色主题**：POS 终端有，Toast Now App **无**；夜班员工痛点。

---

## 四、差距明细（按维度 × 严重度）

### 4.1 P0 阻断级（违反 tx-ui 规范，需 30 天内修复）

| # | 差距 | 规范出处 | 现状 | 影响 |
|---|------|----------|------|------|
| 1 | **KDS 关键操作触控 < 72px** | tokens.md:106 | 实装 48px | 戴手套点不到，徐记海鲜验收风险 |
| 2 | **KDS 标题字体 < 24px** | store.md:32 | 实装 20px | 厨师 2 米外看不清 |
| 3 | **`base-theme.ts` 困在 web-pos** | store.md:334 应在 `packages/tx-touch` | KDS / Crew 各自硬编码 | Token 漂移、品牌色不统一风险 |
| 4 | **a11y 几乎为零** | 全局缺失 | 仅 LangSwitcher 有 aria-label；无 tab focus / keyboard nav | 与 "Palantir" 品牌定位严重不符 |
| 5 | **8 个占位 Agent**（含 voice_order） | CLAUDE.md 九 | 仅声明无实现 | "9 个 AI Agent 差异化"宣称兑现风险 |

### 4.2 P1 差异化窗口（90 天内可建立护城河）

| # | 机会 | 屯象现状 | 行业对比 | 商业价值 |
|---|------|---------|---------|---------|
| 1 | **A2UI 中国餐饮首发** | A2UIRenderer 已实装，6 组件白名单 | Google 标准 2025-12 开源，无餐饮商业落地 | 行业首家发布权 + 协议标准定义权 |
| 2 | **Cmd+K CommandPalette** | web-pos 已实装 | Toast/Lightspeed 均无 | 收银员效率提升 ≈30% |
| 3 | **Agent 决策留痕 v099** | RLS + 索引完整 | 行业空白 | 监管合规护城河（全电发票/食安） |
| 4 | **Admin AI NLQ 专属入口缺失** | 🔴 | Toast IQ 主战场 | 总部老板首屏价值最高，必补 |
| 5 | **中文对话执行**（折扣/86/排班） | 13 Agent + 134 Actions 已具备引擎 | Toast IQ 仅英文+美国 | 中国市场独家 |

### 4.3 P2 行业空白机会（180 天内可引领）

| # | 机会 | 商业逻辑 |
|---|------|----------|
| 1 | **角色感 Dashboard**（老板/店长/厨师长首屏差异化） | 客如云"智能小 On"对标，国内首个落地 |
| 2 | **KDS 实时档口热力图** | Lightspeed Tempo 是事后分析，无人做实时；屯象 Mac mini 边缘有 traffic 预测端点 |
| 3 | **离线 SLA 计时器** | 屯象 4h 断网 SLA 唯一卖点，需可视化"已缓存 N 单/独立运行剩余 X 小时" |
| 4 | **TTS 语音输出**（KDS 播报"A3 桌锅包肉超时 2 分钟"） | Whisper 已有，TTS 缺失，全双工只差一步 |
| 5 | **Core ML `.mlmodel` 注入** | 4 端点全规则版，模型注入后毛利率/出餐时间预测精度 +15-30% |

### 4.4 P3 完善项（持续优化）

| # | 项目 | 当前 | 目标 |
|---|------|------|------|
| 1 | i18n 扩 B 端 | 仅 h5 4 语 | Admin/Store/MiniApp 全终端 ≥3 语（中/英/繁） |
| 2 | 高对比度 + 色弱模式 | 无 | 提供切换，符合 WCAG AAA |
| 3 | web-admin TODO 收尾 | 339 行 | < 50 行 |
| 4 | 副屏/客显/电子秤 UI 实装 | TXBridge 接口有 | 组件 + 调用链完整 |
| 5 | 暗色主题切换 | 单主题强制 | Admin 暗色可选；Store 暗色为主 |

---

## 五、战略调整路线图

### 5.1 30 天 · 基线对齐（P0 修复）

**目标**：所有 Store 终端通过 tx-ui 规范自动检查（CI 集成）。

- [ ] `packages/tx-touch` 抽出，承载 base-theme.ts + TXButton/TXCard/TXNumpad/TXSelector/TXScrollList/TXAgentAlert/TXKDSTicket/TXPaymentPanel 全部组件
- [ ] KDS 全键升 72px 触控 + 24px 标题字体
- [ ] CI 加触控目标 lint（< 48px 拒绝合并）
- [ ] a11y 最小可行品：aria-label 100% 覆盖 / Tab focus 管理 / 焦点环可见
- [ ] 8 个占位 Agent 优先级排序（P0 voice_order + attendance_compliance）
- [ ] 验收：通过 axe-core 扫描，分数 ≥80

### 5.2 90 天 · 差异化突破（P1 兑现）

**目标**：建立"AI-Native"可被客户感知的具体能力。

- [ ] A2UIRenderer 组件白名单扩展至 18 个（增 Form/Map/Heatmap/Timeline/Cascader/Tabs/Stepper/Calendar/Rating/Empty/Skeleton/Toast）
- [ ] Admin 端 AI NLQ 入口：仪表盘右上角浮动按钮 + 对话面板 + Pin 洞察 + 直接执行三类操作（菜单/排班/86）
- [ ] KDS 实时档口热力图（Mac mini `/predict/traffic` 接入）
- [ ] TTS 端点（`edge/mac-station/voice_service.py` 增 `/speak`）+ KDS 关键事件播报
- [ ] 离线 SLA 计时器组件 + 顶部状态栏可视化
- [ ] 13 个 Agent → 18 个（补 voice_order/points_advisor/ai_marketing_orchestrator）
- [ ] 验收：徐记海鲜 DEMO 现场 demo 5 个差异化能力

### 5.3 180 天 · 行业引领（P2 落地）

- [ ] Core ML `.mlmodel` 注入 4 端点（菜品时间/折扣风险/客流/动态定价）
- [ ] 角色感 Dashboard：老板/店长/厨师长首屏 + Agent 角色画像
- [ ] Tier 1 路径全 a11y AAA（订单状态机/支付 Saga/RLS/POS 写入）
- [ ] i18n 扩 5 语言：繁体/粤语/英文/越南文/泰文
- [ ] 暗色主题切换（Admin 可选 / Store 默认）
- [ ] A2UI 协议白皮书发布 + 开源 demo（Toast/Lightspeed 之前抢首发）

---

## 六、验收标准（与 Week 8 DEMO 门槛对齐）

| 维度 | 门槛 | 验证方法 |
|------|------|----------|
| Tier 1 全绿 | 100% 测试通过 | pytest tier1 全集 |
| P99 延迟 | < 200ms | 200 桌并发压测 |
| 支付成功率 | > 99.9% | 含超时/失败回滚 |
| 断网恢复 | 4h 内无数据丢失 | LWW + 终态豁免验证 |
| **触控达标率** | ≥ 95% Store 终端 | CI lint + axe-core |
| **a11y 评分** | ≥ 80 | axe-core / Lighthouse |
| **品牌色一致性** | 100% 引用 Token | grep 硬编码 hex 应为 0 |
| **收银员零培训上手** | DEMO 现场用户测试 | 徐记海鲜 / 尝在一起 现场 |

---

## 七、附录：关键文件索引

| 主题 | 真理源 | 实装位置 |
|------|--------|----------|
| 设计 Token | `docs/color-system.md` v4 + `.claude/skills/tx-ui/references/tokens.md` | `packages/tx-tokens/src/tokens.ts` + `apps/web-pos/src/design-system/base-theme.ts` |
| Admin 规范 | `.claude/skills/tx-ui/references/admin.md` | `apps/web-admin/src/theme/antd-theme.ts` |
| Store 规范 | `.claude/skills/tx-ui/references/store.md` | `apps/web-pos/src/components/` + `apps/web-kds/src/` + `apps/web-crew/src/` |
| MiniApp 规范 | `.claude/skills/tx-ui/references/miniapp.md` | `apps/miniapp-customer-v2/` + `apps/h5-self-order/` |
| Agent UI 通道 | `services/tx-agent/` 63 Skills + 134 Actions | `apps/web-pos/src/{components/SmartSidebar,components/a2ui/A2UIRenderer,hooks/useAgentSSE}.tsx` |
| Edge 智能 | `edge/coreml-bridge/` Swift HTTP + `edge/mac-station/src/voice_service.py` | 全部 graceful fallback 到规则 |
| 决策留痕 | `shared/db-migrations/versions/v099_agent_decision_logs.py` | 已含 RLS |
| 行业对标 | 详见正文第三章 URL 列表 | — |

---

**报告状态**：v1.0
**待评审人**：未了已（创始人）
**下一步**：会议讨论后将路线图条目转为 issue / 进入 progress.md 跟踪。
