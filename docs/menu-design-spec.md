# 屯象系统 · 菜单导航设计风格分析与开发方案

---

## 一、设计风格总结

### 1.1 整体架构：四栏式网格布局

这套设计采用 CSS Grid 构建了经典的企业级 SaaS 操作台布局，由四个垂直功能区 + 一个顶栏水平贯穿组成：

| 区域 | 宽度 | 功能定位 |
|------|------|----------|
| **Icon Rail（图标导轨）** | 56px 固定 | 一级模块切换，纯图标 |
| **Sidebar（侧边栏）** | 220px 固定 | 二级导航 + 分组 + 搜索 + 门店切换 |
| **Main Content（主内容区）** | 弹性填充 | 面包屑 + 视图Tab + 业务内容 |
| **Context Panel（上下文面板）** | 340px 固定 | 活动流 / AI 对话 / 辅助信息 |
| **Topbar（顶栏）** | 48px 高度，贯穿全宽 | LOGO + 全局搜索 + 通知 + 用户头像 |

Grid 定义为：
```
grid-template-rows: 48px 1fr;
grid-template-columns: 56px 220px 1fr 340px;
```

### 1.2 导航层级设计（三级递进）

**第一级 → Icon Rail（图标导轨）**
- 36×36px 图标按钮，圆角 9px
- 仅显示 SVG 图标，无文字
- 激活态：半透明主色背景 + 主色图标
- 悬停态：极浅底色 + 提亮图标
- 中间有 1px 分割线（`rail-sep`）区分功能组与工具组
- 底部固定"帮助"图标（`margin-top: auto`）

**第二级 → Sidebar（侧边栏）**
- 顶部：模块名称（大写字母间距标签）+ 搜索框
- 中部：可滚动导航区，按 `sb-group` 分组
  - 分组标签：9px 大写字母间距
  - 菜单项：13px 中文字体，左侧 SVG 图标 14px
  - 激活态：半透明主色背景 + 主色文字
  - 计数徽标：右对齐的 `sb-count` 胶囊
  - 门店项：左侧圆点状态指示（绿色/琥珀/红色）
- 底部：门店选择器卡片（固定于底部，包含状态点 + 名称 + 区域 + 下拉箭头）

**第三级 → Main Content 内的 View Tabs**
- 水平 Tab 条，底部 2px 激活指示线
- 激活态为主色文字 + 主色底线
- 用于在同一模块内切换子视图

### 1.3 顶栏设计细节

顶栏从左到右依次排列：

1. **Logo 区域**：品牌标识方块（28×28px，圆角 7px）+ 系统名称（serif 字体加粗）+ 版本号（mono 字体，极弱色）
2. **全局命令面板触发器**：搜索图标 + 占位提示文字 + 键盘快捷键标签（⌘K），外观为一个可点击的输入框模拟控件
3. **右侧工具栏**：实时时钟 + 功能按钮组（键盘快捷键、通知、设置）+ 用户头像（渐变圆形）

### 1.4 交互模式汇总

| 模式 | 触发方式 | 表现形式 |
|------|----------|----------|
| **Command Palette** | ⌘K 或点击顶栏搜索 | 居中模态弹窗 + 毛玻璃遮罩 |
| **通知中心** | 点击铃铛 或 ⌘. | 右侧 380px 滑入面板 |
| **键盘快捷键** | 按 ? 键 | 居中模态弹窗（520px）|
| **门店详情** | 点击门店卡片 | 右侧 420px 滑入面板 |
| **Toast 提示** | 操作反馈 | 底部居中浮动条，2.2s 自动消失 |
| **批量操作栏** | 勾选表格行 | 底部居中弹起工具条 |
| **Tooltip** | hover 元素 | 顶部居中浮动标签 |

### 1.5 排版体系

| 用途 | 字体 | 字号 | 权重 |
|------|------|------|------|
| 系统名称/标题 | Noto Serif SC | 13px | 700-900 |
| 中文正文/菜单项 | Noto Sans SC | 12-13px | 400-600 |
| 西文数字 | Inter | 根据语境 | 300-900 |
| 数据/代码/时间 | JetBrains Mono | 10-11px | 400-500 |
| 模块/分组标签 | 主字体 | 9-10px | 700, 大写, 0.1em 字间距 |

### 1.6 间距与圆角体系

**圆角 Token**：4px / 8px / 12px / 16px（不同层级组件逐级递增）

**典型间距**：
- 导轨图标间距：4px gap
- 侧边栏项内边距：7px 10px
- 面板内边距：12-16px
- 卡片间距：12px gap
- 分组间距：8px margin-bottom

### 1.7 状态色语义

| 语义 | 色值变量 | 用途场景 |
|------|----------|----------|
| 正常/完成 | `--green` | 在线状态、完成标记、健康指标 |
| 警告/注意 | `--amber` | 异常告警、处理中状态 |
| 危险/错误 | `--red` | 严重告警、待处理、未解决 |
| 信息/辅助 | `--blue` | 信息性提示、冷链类标签 |
| AI/智能 | `--purple` | AI 预测、智能标签 |

### 1.8 动画规范

- 过渡统一用 `transition: all .15s`（快速反馈）
- 滑入面板：`.3s cubic-bezier(.2,.9,.3,1)`（弹性缓出）
- 脉冲动画：`2s infinite`（直播/在线指示灯）
- KPI 数值揭示：`.4s opacity`，延迟递增（300ms + i×80ms）
- 骨架屏闪烁：`1.5s infinite shimmer`
- 批量操作栏弹起：`.28s cubic-bezier(.2,.9,.3,1)`

---

## 二、开发方案

### 2.1 方案目标

将上述菜单导航设计风格（排除 LOGO 图标和具体颜色值）移植到屯象系统，形成一套可复用的 **Shell Layout + Navigation Framework**。

### 2.2 技术选型建议

| 维度 | 建议 | 理由 |
|------|------|------|
| 框架 | React 18+ / Vue 3 | 组件化管理四栏布局与状态切换 |
| 样式方案 | CSS Variables + CSS Modules 或 Tailwind | Design Token 天然适合 CSS 变量体系 |
| 图标 | Lucide Icons 或 自定义 SVG Icon 组件 | 与原设计一致的 stroke 风格 |
| 字体 | 保持四字体栈结构（替换为屯象品牌字体）| 区分标题/正文/数字/代码四种排版角色 |
| 动画 | CSS Transitions + Framer Motion（React）| 覆盖面板滑入、弹窗、微交互 |
| 状态管理 | Zustand / Pinia | 管理导航激活态、面板展开/收起 |

### 2.3 组件拆分清单

按照原子设计方法论，将菜单系统拆分为以下组件：

#### 原子组件 (Atoms)

| 组件 | 文件名 | 职责 |
|------|--------|------|
| IconButton | `IconButton.tsx` | 导轨/顶栏的图标按钮，含 tooltip、active、badge |
| NavItem | `NavItem.tsx` | 侧边栏菜单项，含图标、文字、计数徽标 |
| GroupLabel | `GroupLabel.tsx` | 大写字母间距分组标签 |
| StatusDot | `StatusDot.tsx` | 彩色圆点状态指示（ok/warn/crit） |
| KbdTag | `KbdTag.tsx` | 键盘快捷键标签 |
| Badge | `Badge.tsx` | 计数/状态胶囊徽标 |
| Tooltip | `Tooltip.tsx` | 通用浮动提示 |
| ViewTab | `ViewTab.tsx` | 主内容区顶部的视图切换 Tab |

#### 分子组件 (Molecules)

| 组件 | 文件名 | 职责 |
|------|--------|------|
| NavGroup | `NavGroup.tsx` | 侧边栏分组（标签 + N 个 NavItem） |
| SearchInput | `SearchInput.tsx` | 侧边栏/命令面板的搜索输入 |
| StoreSelector | `StoreSelector.tsx` | 侧边栏底部门店选择器 |
| CommandTrigger | `CommandTrigger.tsx` | 顶栏全局搜索触发器 |
| UserAvatar | `UserAvatar.tsx` | 渐变头像 + 下拉菜单 |
| Breadcrumb | `Breadcrumb.tsx` | 主内容区面包屑导航 |
| NotifItem | `NotifItem.tsx` | 通知列表单条 |

#### 有机体组件 (Organisms)

| 组件 | 文件名 | 职责 |
|------|--------|------|
| Topbar | `Topbar.tsx` | 完整顶栏（Logo + 搜索 + 工具 + 头像） |
| IconRail | `IconRail.tsx` | 图标导轨（一级导航） |
| Sidebar | `Sidebar.tsx` | 侧边栏（搜索 + 多分组 + 门店选择） |
| ViewTabBar | `ViewTabBar.tsx` | 视图 Tab 条 |
| CommandPalette | `CommandPalette.tsx` | ⌘K 命令面板弹窗 |
| NotificationPanel | `NotificationPanel.tsx` | 右侧滑入通知面板 |
| ShortcutsModal | `ShortcutsModal.tsx` | 快捷键说明弹窗 |
| ContextPanel | `ContextPanel.tsx` | 右侧上下文面板 |

#### 模板组件 (Templates)

| 组件 | 文件名 | 职责 |
|------|--------|------|
| **ShellLayout** | `ShellLayout.tsx` | 四栏 Grid 主框架，编排所有 Organism |

### 2.4 Design Token 文件结构

```
tokens/
├── spacing.css          /* 间距 Token：--sp-1 到 --sp-12 */
├── radius.css           /* 圆角 Token：--r4, --r8, --r12, --r16 */
├── typography.css       /* 字体族、字号、权重、字间距 */
├── shadows.css          /* 阴影层级：sm / md / lg / xl */
├── z-index.css          /* 层级管理 */
├── layout.css           /* 布局 Token：sidebar-w, rail-w, context-w, topbar-h */
├── opacity.css          /* 透明度体系：t1-t5 */
├── animation.css        /* 过渡/缓动曲线统一定义 */
└── semantic-colors.css  /* 状态色语义变量（由屯象品牌色覆盖）*/
```

### 2.5 实施阶段划分

#### Phase 1 · Shell 骨架搭建（2-3 天）

**目标**：实现四栏 Grid 布局框架 + 响应式处理

- 实现 `ShellLayout` 组件，Grid 定义四栏
- 顶栏骨架（Logo 区、搜索触发器占位、右侧工具栏）
- 导轨骨架（图标按钮列表，active 切换）
- 侧边栏骨架（Header + 滚动区 + Footer）
- 主内容区骨架（Header + TabBar + Body）
- 右侧上下文面板骨架

**交付物**：空壳布局可运行，四区域边界清晰

#### Phase 2 · 导航交互实现（3-4 天）

**目标**：完成三级导航联动 + 路由集成

- Icon Rail 点击 → 切换 Sidebar 模块内容 + 高亮
- Sidebar NavItem 点击 → 切换主内容区 + 面包屑更新
- View TabBar 点击 → 切换子视图内容
- 路由集成：URL 与导航状态双向同步
- 门店选择器切换逻辑
- Sidebar 搜索筛选（前端过滤菜单项）

**交付物**：三级导航可点击联动，URL 可直达

#### Phase 3 · 命令面板与全局控件（2-3 天）

**目标**：实现 Command Palette + 通知 + 快捷键

- Command Palette（⌘K）：搜索输入 + 结果分组 + 键盘上下选择 + 回车执行
- 通知面板：右侧滑入 + 分时段分组 + 已读/未读
- 快捷键模态弹窗
- Toast 提示系统
- Tooltip 系统

**交付物**：全局快捷操作可用

#### Phase 4 · 动效与细节打磨（2 天）

**目标**：实现所有微交互与过渡动画

- 面板滑入/滑出动画（cubic-bezier 弹性缓出）
- 导航项 hover/active 过渡
- KPI 数值揭示动画（延迟递增）
- 通知徽章弹入动画
- 骨架屏加载态
- 批量操作栏弹起动画
- 滚动条样式（4px 细轨）

**交付物**：交互体验达到参考设计水准

#### Phase 5 · Token 替换与品牌适配（1-2 天）

**目标**：将屯象品牌视觉注入 Token 系统

- 替换主色/辅色/语义色为屯象品牌色
- 替换 LOGO 组件
- 替换/确认字体栈
- 确认间距/圆角是否需要微调
- 暗色/亮色主题切换支持（如需要）

**交付物**：屯象品牌风格完整呈现

### 2.6 关键技术要点

**1. 导轨与侧边栏的联动状态管理**

```typescript
// 导航状态 Store（以 Zustand 为例）
interface NavState {
  activeModule: string;       // Rail 激活模块 ID
  activeItem: string;         // Sidebar 激活菜单项 ID
  activeTab: string;          // ViewTab 激活标签
  sidebarCollapsed: boolean;  // 侧边栏折叠态
  contextVisible: boolean;    // 上下文面板显隐
}
```

**2. Command Palette 搜索架构**

建议采用分类注册机制：各业务模块向 Command Palette 注册可搜索命令，面板统一检索和执行。

**3. 键盘快捷键管理**

统一注册全局快捷键（⌘K 搜索、? 帮助、Esc 关闭、⌘. 通知），避免与浏览器/系统快捷键冲突。

**4. 响应式策略**

- 小于 1280px：隐藏 Context Panel
- 小于 1024px：Icon Rail 模式（隐藏 Sidebar 文字）
- 小于 768px：抽屉模式（Sidebar 覆盖层）

### 2.7 预估工期

| 阶段 | 工期 | 人力 |
|------|------|------|
| Phase 1 · Shell 骨架 | 2-3 天 | 1 前端 |
| Phase 2 · 导航交互 | 3-4 天 | 1 前端 |
| Phase 3 · 全局控件 | 2-3 天 | 1 前端 |
| Phase 4 · 动效打磨 | 2 天 | 1 前端 |
| Phase 5 · 品牌适配 | 1-2 天 | 1 前端 + 1 设计 |
| **合计** | **10-14 天** | — |

---

## 三、核心设计模式速查表

| 设计模式 | 原文件中的实现方式 | 移植要点 |
|----------|-------------------|----------|
| 图标导轨 | `.rail` + `.rail-item` | 固定 56px 宽、36px 图标按钮、auto 底部锚定 |
| 分组侧边栏 | `.sb-group` + `.sb-group-label` + `.sb-item` | 9px 大写标签 + 8px 圆角项 + 右侧计数 |
| 门店状态点 | 内联 7px 圆点 span | 语义色变量驱动 |
| 命令面板 | `.cmd-overlay` + `.cmd-search` + `.cmd-result` | 毛玻璃遮罩 + 搜索 + 分组结果 + 键盘导航 |
| 滑入面板 | `.notif-overlay` / `.store-detail-panel` | fixed 定位 + translateX 动画 + backdrop |
| 批量操作栏 | `.bulk-bar` | fixed 底部 + translateY 弹入 + 选中计数 |
| 视图切换 Tab | `.vtab` | 底部 2px 指示线 + 主色激活态 |
| 面包屑 | `.breadcrumb` | 12px 灰色路径 + 当前项加粗 |
| Tooltip | `[data-tip]::before` | 纯 CSS 实现，无额外 JS 依赖 |

---

*此方案专注于菜单导航设计风格的提取与移植，不涉及具体业务组件（KPI卡片、损耗表格、看板等）的实现。业务组件可在 Shell 框架完成后按需开发。*
