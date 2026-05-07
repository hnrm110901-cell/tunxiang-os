# 屯象OS UI/UX 设计宪法 v1.0

> **生效日期**：2026-05-07
> **版本**：v1.0（取代旧 `menu-ui-upgrade-proposal.md` 中所有冲突项；与 `color-system.md` v4 共同构成 UI/UX 真相源）
> **范围**：apps/ 16 个前端 + edge/ 边缘智能 UI + 任何前端代码生成路径
> **关系**：本宪法是 `CLAUDE.md` 项目宪法在 UI/UX 维度的延伸；与 `.claude/skills/tx-ui/references/*.md` 是同一份规范的"宪法表述（本文）+ 操作手册（skill 引用）"两面。

---

## 第一部分 设计哲学

### 1.1 为什么 UI/UX 是屯象OS 的核心竞争力

屯象OS 的商业本质是 **"用一套系统替换连锁餐饮商户的所有现有系统"**（徐记海鲜替换 23 套）。这意味着收银员、店长、厨师、运营总监、财务经理 —— 五类角色一夜之间被要求重新建立操作肌肉记忆。**UI/UX 决定了这场更迭是无感升级还是大面积返工**。

**Toast 的 UX 最强项不是好看，而是稳定**：自 2018 年至今未重构过核心导航。屯象OS 必须采纳同一纪律 —— **条件反射稳定性 > 视觉新鲜感**。

### 1.2 三类终端，三种操作环境，三套设计语言

| 终端 | 用户 | 物理环境 | 核心动作 | 设计语言 |
|------|------|----------|----------|----------|
| **Admin 总部端** | 老板 / 店长 / 财务 / 运营 | 办公室桌面 / 笔记本 | 决策、审批、复盘、报表查询 | **效率密度优先**（AntD ProComponents） |
| **Store-POS / KDS / Crew** | 收银员 / 厨师 / 服务员 | 收银台 / 厨房 / 巡台中 | 点单、结账、出餐、催菜 | **触控容错优先**（TXTouch 自研，禁用 AntD） |
| **MiniApp 消费者端** | 顾客 | 手机 / 餐桌 / 家中 | 扫码点餐、支付、会员、外卖 | **情感共鸣优先**（uni-app + 品牌温度） |

> **铁律**：跨终端共享的是**业务实体**（Customer/Dish/Order/...）和**品牌色**，**不是组件实例**。Admin 用 ProTable，Store 用 TXScrollList，MiniApp 用 scroll-view —— 同一份数据，三个原生组件，绝不"一处复用，多处妥协"。

### 1.3 五大设计原则

#### 原则 1：为环境设计，而非屏幕

| 终端 | 关键环境约束 | 必须设计 |
|------|-------------|----------|
| KDS | 油腻手指、高温水汽、戴手套、3 米外阅读 | 关键操作 ≥72px，订单号 ≥32px，三色编码（绿/黄/红） |
| POS | 高强度 200 桌并发、收银员站立、Drift Flow 焦虑 | 二次确认仅在不可逆操作；Cmd+K 减少层级跳转 |
| Crew | 单手拇指可达、嘈杂、走动中 | 底部 TabBar；操作核心区域距底部 ≤120px |
| Admin | 久坐、多任务、键鼠 | 高密度表格；快捷键支持；批量操作 |
| MiniApp | 餐桌或沙发、注意力碎片、网络不稳 | 首屏 < 2MB；分包；离线缓存 |

#### 原则 2：透明而非隐形（Agent 决策必须留痕展示）

每一个 Agent 决策必须在 UI 上显示：**Agent 名 + 决策依据 + 置信度 + 三条硬约束校验结果**。
- 折扣守护拦截 → "李经理刚才折让¥120，毛利从 65%→58%，跌破阈值（DiscountGuard@v3，置信度 0.92）"
- 不允许"AI 觉得这样更好"式黑盒提示

#### 原则 3：增量发布，保持肌肉记忆

- 核心导航（Admin 侧边栏 / POS 三栏 / KDS 网格 / Crew Tab）**冻结**，未经 V-meeting 不重构
- 新功能用**附加层**（侧边栏、命令面板、生成式弹层），不挤压原有空间
- A/B 实验默认 5% 流量，48h 内可回退

#### 原则 4：安全保障优先于性能

- A2UI 渲染必须基于**预批准白名单组件目录**，禁止 Agent 输出 HTML/JS
- 收银员误点风险高于性能：72px 按钮宁可"拖慢" 50ms，也比误触安全
- 不可逆操作（反结账 / 删单 / 退菜）必须二次确认 + 操作留痕

#### 原则 5：摩擦可以是设计特性

- 三条硬约束触发时**故意制造摩擦**：毛利破底线 → 弹窗 + 经理审批 + 决策留痕
- 但只有不可逆 / 高风险路径有摩擦，常规路径必须丝滑

### 1.4 三条硬约束的可视化表达（强制）

| 硬约束 | 触发条件 | UI 表达 |
|--------|---------|---------|
| 毛利底线 | 折扣后单笔毛利 < 阈值 | 红色 Tag + 锁定结算按钮 + 经理 PIN 解锁 + DiscountGuard Agent 决策面板 |
| 食安合规 | 临期 ≤2 天 / 过期 / 品控不通过 | 黄色徽标（临期）/ 红色遮罩（过期）+ KDS 自动屏蔽 + 库存页警告 |
| 客户体验 | 出餐 > 门店上限 | KDS 卡片整体变红 + 脉冲动画 + Crew 端推送催菜建议 |

**任何 Agent / 后台操作绕过以上 UI 表达 = 违反宪法，CI 直接 reject。**

---

## 第二部分 终端区隔规范

### 2.1 Admin 总部端（apps/web-admin）

- **技术栈**：React 18 + AntD 5.x + ProComponents（ProTable / ProForm / ProLayout）+ @ant-design/charts + Zustand
- **唯一允许的列表组件**：`ProTable`（含搜索/分页/列设置/密度切换）
- **唯一允许的表单组件**：`ModalForm` / `DrawerForm`
- **图表**：`@ant-design/charts`，**禁止引入 ECharts**
- **响应式底线**：≥ 1280px 宽度
- **新增 v1.0 强制项**：
  - 毛利率 Tag 自动变色：< 80% 阈值 → red；< 阈值 → orange
  - Agent 决策来源用 `info` 蓝色 Tag 标识，区分 AI 数据 vs 人工数据
  - 经营驾驶舱必须有"Agent 主动洞察推送 Feed"区块（首屏右侧）

### 2.2 Store-POS（apps/web-pos）

- **技术栈**：React 18 + UnoCSS + TXTouch 组件库（**禁止 AntD**）
- **三栏布局冻结**：分类 10% + 菜品网格 55% + 购物车 35%
- **必须实现**：
  - `useOffline` IndexedDB 离线优先（已落地）
  - `CommandPalette` Cmd+K 命令面板（已落地）
  - `SmartSidebar` 右侧 Agent 推送面板（已落地）
  - `A2UIRenderer` 声明式 UI 渲染入口（已落地）
- **触控目标**：常规 ≥ 56px，关键 ≥ 72px

### 2.3 Store-KDS（apps/web-kds）—— v1.0 强化项

> **2026-05 修订**：KDS 是过去最严重的规范违反点。以下规则即日起进入 CI 强制：

- **触控**：完成 / 加急 / 退回 全部 ≥ **72×72px**（旧实装 48px 必须修正）
- **字体**：
  - 桌号 / 订单号 ≥ **32px** 粗体
  - 区域 / 档口标题 ≥ **28px** 粗体
  - 菜品行 ≥ **20px**
  - 倒计时数字 ≥ **32px** 粗体
- **三色编码**（强制）：
  - 剩余 > 50% 时间 → 白底，时间数字绿色
  - 剩余 ≤ 50% → 白底，时间数字黄色
  - 已超时 → **整张卡片变红 + 脉冲动画 + 语音播报**
- **滑动操作**：左滑 72px 触发完成，带触觉反馈（vibrate API）
- **多档口**：默认按 `by-station` 分屏，可切换 `by-table`
- **TTS 播报**（v1.0 新增）：新单 / 超时 / 加急 三类事件强制语音

### 2.4 Store-Crew（apps/web-crew）

- **技术栈**：React 18 + UnoCSS + TXTouch + PWA
- **布局**：单列竖屏 + 底部 TabBar 4 项
- **核心操作区**：屏幕底部 ≤ 120px 单手拇指可达
- **触控**：常规 ≥ 48px，加菜 / 催菜 / 结账 ≥ 56px

### 2.5 MiniApp（apps/miniapp-customer-v2 + apps/h5-self-order）

- **技术栈**：uni-app + Vue 3 `<script setup>` + Pinia
- **样式单位**：rpx（750rpx = 屏宽）
- **首屏主包 < 2MB**，大厨到家 / 企业订餐 / 评价用分包
- **AI 推荐组件**：必须挂"AI"标签，区分人工编辑数据
- **i18n**：v1.0 起强制接入（即使初版只 zh-CN，i18n 框架先到位）

### 2.6 终端独占 vs 跨终端共享

| 类型 | 跨终端共享 | 终端独占 |
|------|-----------|----------|
| **业务实体** | ✅ Customer / Dish / Order / Store / Ingredient / Employee | — |
| **API 类型** | ✅ `shared/api-types/` | — |
| **常量与枚举** | ✅ `shared/constants/` | — |
| **纯函数工具** | ✅ `shared/utils/` (formatMoney / calcMargin) | — |
| **Design Token** | ✅ `packages/tx-tokens/` | — |
| **UI 组件** | ❌ | Admin AntD / Store TXTouch / MiniApp uni-ui |
| **状态管理** | ❌ | Admin/Store: Zustand / MiniApp: Pinia |
| **API 封装** | ❌ | Admin/Store: fetch / MiniApp: uni.request |

---

## 第三部分 Design Token 唯一真相源

### 3.1 品牌色（不可硬编码）

| Token | 值 | 用途 |
|-------|-----|------|
| `primary` | `#FF6B35` | 主色（按钮 / 链接 / 选中态 / 品牌标识） |
| `primaryHover` | `#FF8555` | 悬停（仅 Admin 桌面端） |
| `primaryActive` | `#E55A28` | 按下态（所有终端） |
| `primaryLight` | `#FFF3ED` | Tag 背景 / 选中行 |
| `navy` | `#1E2A3A` | Admin 侧边栏 / 深色标题 |
| `navyLight` | `#2C3E50` | 辅色浅色 |

### 3.2 语义色（与硬约束绑定）

| Token | 值 | 业务映射 |
|-------|-----|---------|
| `success` | `#0F6E56` | 毛利达标 / 出餐正常 / 在线状态 |
| `warning` | `#BA7517` | 即将超时 / 毛利偏低 / 临期食材 / 库存偏低 |
| `danger` | `#A32D2D` | 超时 / 破毛利底线 / 沽清 / Agent critical / 过期食材 |
| `info` | `#185FA5` | AI 推荐标记 / Agent 建议 / CDP 洞察 |

### 3.3 字号体系（三套并存）

| 级别 | Admin | Store | MiniApp(rpx) | KDS 强化 |
|------|-------|-------|-------------|---------|
| 桌号/订单号 | 24px | 32px | 44rpx | **≥32px 粗体** |
| h1 页面标题 | 24px | 32px | 44rpx | — |
| h2 区域标题 | 20px | 24px | 36rpx | **≥28px 粗体** |
| h3 卡片标题 | 16px | 20px | 32rpx | **≥24px** |
| body 正文 | 14px | 18px | 28rpx | **≥20px** |
| caption 辅助 | 12px | 16px | 24rpx | ≥16px（VIP徽标） |
| mini | 12px | **禁止** | 22rpx | **禁止** |

**Store 终端绝对底线 16px。KDS 终端绝对底线 20px。任何破例触发 CI 拒绝。**

### 3.4 触控安全区（仅 Store）

| 参数 | 值 | 适用 |
|------|-----|------|
| 最小点击区 | 48×48px | 所有 |
| 推荐点击区 | 56×56px | 戴手套场景常规操作 |
| 关键操作 | **72×72px** | 支付确认 / KDS 完成 / KDS 加急 / 反结账 |
| 按钮间距 | ≥ 12px | 防误触 |
| 滑动阈值 | 30px | 区分点击和滑动 |

### 3.5 间距 / 圆角 / 阴影 / 动画

详见 `.claude/skills/tx-ui/references/tokens.md`，本宪法不重复。

### 3.6 Token 消费方式

| 终端 | 消费方式 |
|------|---------|
| Admin | `ConfigProvider theme={txAdminTheme}` |
| Store | CSS Variables（`--tx-*` 全局注入）+ UnoCSS preset |
| MiniApp | `uni.scss` 全局变量 |

**铁律**：不允许任何文件内出现 `#FF6B35` / `#0F6E56` / `#BA7517` / `#A32D2D` / `#185FA5` 等硬编码 hex。CI grep 命中即 fail。

---

## 第四部分 组件库分层

### 4.1 packages/tx-tokens（v1.0 完成度：80%，待补 KDS 字体规则）

设计变量唯一来源：颜色 / 字号 / 间距 / 圆角 / 阴影 / 触控目标 / 动画时长。

### 4.2 packages/tx-touch（v1.0 新增产物，30 天内交付）

> **现状问题**：所有 TXTouch 组件困在 `apps/web-pos/src/`，KDS / Crew 各自重写，导致 Token 漂移。
> **v1.0 决议**：抽出独立包 `packages/tx-touch/`，三个 Store 终端共用。

必须包含：

```
packages/tx-touch/src/
  components/
    TXButton / TXCard / TXNumpad / TXSelector / TXScrollList
    TXDishCard / TXKDSTicket / TXPaymentPanel / TXAgentAlert
    TXCommandPalette / TXSmartSidebar / TXInsightCard
    TXA2UIRenderer
  hooks/
    useLongPress / useSwipe / useHaptic / useOffline
    useAgentSSE / useAgentInsights
  styles/
    reset.css / animations.css / variables.css
```

### 4.3 Admin AntD ProComponents（无新增，约束执行）

详见 `.claude/skills/tx-ui/references/admin.md`。v1.0 强制审计：所有 Admin 列表必须用 ProTable，所有表单必须用 ProForm 系列。

### 4.4 MiniApp tx-* Vue 组件（无新增，约束执行）

详见 `.claude/skills/tx-ui/references/miniapp.md`。

---

## 第五部分 Agent-UI 融合规范

### 5.1 Agent 嵌入 UI 六大模式（采用 Red Baton 2026 框架）

| 模式 | 屯象OS 应用 | 当前状态 |
|------|------------|---------|
| **影响式**（推送上下文洞察） | SmartSidebar 折扣预警 / 推荐搭配 / 会员洞察 | ✅ 已落地 |
| **集成功能**（原生功能内嵌 AI） | SettlePage 折扣 AI 抽屉 / Queue 叫号建议 | ✅ 已落地 |
| **会话式**（自然语言） | CommandPalette Cmd+K Agent 模式 | ✅ 已落地 |
| **生成功能**（动态生成 UI） | A2UIRenderer 声明式渲染 | ✅ 已落地（白名单 6 组件，需扩 18） |
| **微 Agent**（细粒度自动化） | 库存自动盘点 / 异常自动标记 | ⚠️ 部分 |
| **全分离**（独立对话） | Admin 端 AI NLQ 专属面板 | 🔴 v1.0 必须新建 |

### 5.2 SmartSidebar 设计契约

- **位置**：POS / Crew 右侧 326px 可展开 / Admin 经营驾驶舱右上角浮窗
- **优先级**：critical（红 + 脉冲）> warning（橙）> info（蓝）
- **必须信息**：Agent 名 / 决策依据 / 三条硬约束校验 / 置信度 / 操作按钮
- **不可关闭项**：critical 级别洞察用户不能 dismiss，只能"处理 / 升级 / 等待 Agent 撤回"

### 5.3 CommandPalette 命令面板规范

- **快捷键**：所有终端统一 `Ctrl+K` / `Cmd+K`，POS 额外支持 F1
- **响应延迟**：< 100ms 显示面板，< 500ms 返回结果（Mac mini 边缘推理）
- **命令类型**：直接动作（86 牛油果）/ 查询（库存 三文鱼）/ 通知（呼叫经理）/ 自然语言查询（今天毛利最高的菜）
- **每个命令显示**：分类徽标、可见步骤、Agent 名（若由 Agent 执行）

### 5.4 A2UI 声明式渲染白名单

> 屯象OS 是中国餐饮 SAAS **首家** Google A2UI v0.8 兼容产品。这是核心差异化资产，必须建立纪律。

**安全契约**：
- Agent 输出必须是 JSON Surface（`{surfaceId, components: []}`）
- 客户端只渲染白名单组件，未知 type 一律拒绝
- 禁止 HTML / iframe / Script 注入
- 所有 Action 回调走 Agent dispatch，不直接执行业务

**v1.0 白名单（6 个，需扩至 18）**：
- 已支持：Card / List / Table / Badge / Progress / Chart
- 待补：Form / Map / Heatmap / Timeline / Cascader / Tabs / Stepper / Calendar / Rating / Empty / Skeleton / Toast

**新增组件流程**：提案 → 安全 review → 设计 review → 进入白名单 → CI 校验。

### 5.5 Agent 决策留痕展示（v099 已落地）

任何 Agent UI 操作可一键展开 `AgentDecisionLog` Timeline：
- agent_id / decision_type / input_context / reasoning / output_action / **constraints_check** / confidence / created_at
- 监管 / 审计 / 客诉场景必须可追溯

### 5.6 三条硬约束的 UI 表达（强制清单）

参见 1.4。所有 Agent 输出必须包含 `constraints_check` 字段，UI 必须根据该字段渲染相应表达。

---

## 第六部分 质量基线（CI 强制）

| 检查项 | 工具 | 阈值 | 违反处理 |
|--------|------|------|---------|
| 触控目标尺寸 | `pnpm lint:tap-target` | Store 终端 ≥48px，关键 ≥72px | reject merge |
| 字体最小值 | `pnpm lint:font-size` | Store ≥16px，KDS ≥20px | reject merge |
| 品牌色硬编码 | `grep -rE "#FF6B35\|#0F6E56\|#BA7517\|#A32D2D\|#185FA5"` | 0 | reject merge |
| AntD 在 Store | `grep "from 'antd'" apps/web-{pos,kds,crew}` | 0 | reject merge |
| a11y 评分 | axe-core / Lighthouse | ≥80 | warn → 90 天后 reject |
| WCAG 对比度 | axe-core | ≥4.5:1 (AA) | warn |
| Agent 决策留痕 | grep AgentDecisionLog 调用率 | 100% Agent UI 操作 | warn |
| A2UI 白名单 | 自定义 lint | 未注册组件 0 | reject |
| 组件库越界 | grep AntD in TXTouch | 0 | reject |

CI 配置详见 `infra/ci/ui-quality-gate.yml`（待建）。

---

## 第七部分 可访问性 a11y（v1.0 起强制）

> **现状**：屯象OS 几乎零 a11y。这与 "Palantir 定位" 严重不符，v1.0 起逐步建立基线。

### 7.1 ARIA 强制规则（30 天内全覆盖）

- 所有交互元素必须有 `role` 或语义化标签
- 所有 IconButton 必须 `aria-label`
- 所有图表必须有 `aria-describedby` 摘要
- 所有 Dialog / Modal 必须 `aria-modal="true"` + `aria-labelledby`

### 7.2 键盘导航（90 天）

- Admin：Tab 顺序符合视觉顺序，Esc 关闭弹层，Enter 提交，Cmd+K 命令面板
- Store：触控为主，键盘是辅助通道（如外接键盘场景）
- 焦点环：所有可聚焦元素 `focus-visible` 样式必须可见

### 7.3 高对比度 / 色弱模式（180 天）

- 提供 `prefers-contrast: more` 高对比度主题
- 色弱模式：危险/成功不仅靠红绿区分，必须配图标
- 暗色主题：Admin 可选，Store 默认（默认对比度 ≥7:1 AAA）

---

## 第八部分 i18n 国际化

### 8.1 文案外置规范

- 所有可见文案外置到 `locales/{zh-CN,en-US,zh-TW,...}.json`
- 禁止 `.tsx` 中硬编码中文（图标 / 单字符 emoji 例外）
- 复数 / 性别 / 日期 / 货币用 ICU MessageFormat

### 8.2 字体 fallback

```
-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue",
"Noto Sans SC", "Microsoft YaHei", "WenQuanYi Micro Hei", sans-serif
```

繁体场景额外加 `"PingFang TC"`，越南/泰文额外加对应 Noto 字体。

### 8.3 v1.0 落地优先级

| 阶段 | 终端 | 语言 |
|------|------|------|
| 30 天 | h5-self-order | zh-CN / en-US / zh-TW（已有 zh/en/ja/ko，需补繁） |
| 90 天 | miniapp / web-admin | zh-CN / zh-TW |
| 180 天 | 全终端 | zh-CN / zh-TW / en-US / 粤语（粤港澳） |

---

## 第九部分 禁止事项（违反 = 违宪）

1. ❌ Store 终端引入任何 AntD 组件（`from 'antd'` 一律 fail）
2. ❌ Store 终端使用 `<select>` / Dropdown / Popover（用 TXSelector 全屏弹层替代）
3. ❌ Store 终端使用 `:hover` 作为唯一反馈（必须 `:active` + transform scale）
4. ❌ 任何文件硬编码品牌 / 语义色 hex 值
5. ❌ Admin 端使用 TXTouch 组件
6. ❌ 跨终端复用 React 组件实例（共享业务实体 / 类型 / 工具是 OK 的）
7. ❌ Agent 决策不展示 `constraints_check` 字段
8. ❌ 不可逆操作无二次确认（反结账 / 删单 / 退菜 / 反审）
9. ❌ A2UI 渲染未在白名单的组件 type
10. ❌ KDS 触控 < 72px（关键操作）/ 字体 < 20px（菜品行）
11. ❌ 重构核心导航（Admin 侧边栏 / POS 三栏 / KDS 网格 / Crew 4 Tab）未经 V-meeting
12. ❌ 新增交互元素无 `aria-label` 或语义化角色
13. ❌ 中文硬编码在 `.tsx` 模板（30 天 grace period 后强制）

---

## 第十部分 版本管理与变更流程

### 10.1 本宪法的变更

| 改动类型 | 流程 |
|---------|------|
| 新增组件 / Token | UI 负责人 + 1 评审 |
| 修改铁律 / 触控基线 / 字号底线 | 创始人审批 + V-meeting 通过 |
| Agent UI 模式新增 | 创始人 + 安全 review |
| 任何禁止事项变更 | 全员 V-meeting + 创始人审批 |

### 10.2 与代码仓库的关系

```
docs/ui-ux-constitution-v1.md          ← 本宪法（人读）
docs/color-system.md                   ← 色彩源（与本宪法一致）
.claude/skills/tx-ui/references/*.md   ← 操作手册（Claude 读）
packages/tx-tokens/src/tokens.ts       ← 代码源（编译时引用）
infra/ci/ui-quality-gate.yml           ← CI 强制（机器读）
```

四者必须保持同步。任何修改需在同一 PR 内完成对齐。

### 10.3 当前已知 v1.0 待落实项

参见 `docs/ui-ux-development-plan-2026-q3-q4.md`。

---

**签发**：未了已（创始人）/ 屯象科技
**起草**：UI/UX Lead + Claude Code 协作
**生效**：2026-05-07
**下次评审**：2026-08-07（90 天）

---

## 附录 A：本宪法相对旧版的关键变更

| # | 旧版 | v1.0 | 触发原因 |
|---|------|------|----------|
| 1 | KDS 触控 48px | KDS 关键操作 **72px** | 戴手套场景失败案例 |
| 2 | KDS 标题"建议 24px" | **强制 24px**（订单号 32px） | 厨师 3 米外看不清 |
| 3 | base-theme 在 web-pos | **抽出 packages/tx-touch** | KDS / Crew 重写造成漂移 |
| 4 | a11y 自由 | 30 天起 aria 全覆盖，180 天 ≥80 分 | Palantir 定位倒逼 |
| 5 | i18n 仅 h5 4 语 | 全终端框架先到位，180 天 4 语 | B 端可扩展 |
| 6 | A2UI 6 组件 | 90 天扩 18 组件 | 中国首发护城河 |
| 7 | Admin 无 NLQ 入口 | 90 天必建 | Toast IQ 主战场对标 |
| 8 | TTS 缺失 | 90 天接入 KDS / 收银员 | 全双工差异化 |
| 9 | 暗色主题强制 | Admin 可选 / Store 默认 / Crew 默认 | 夜班场景痛点 |
| 10 | 触控/字体无 CI | 30 天起 CI 强制 lint | 防止规范漂移 |
