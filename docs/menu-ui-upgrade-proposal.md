# 屯象OS 菜单及UI重构升级方案

> 基于 `tunxiang-menu-ui` 分支代码审计 + 全球顶级餐饮POS/菜单UI设计研究
> 编写日期：2026-04-12

---

## 一、现状诊断：五大核心问题

### 1.1 品牌色混乱 — 三套色板共存

| 终端 | 品牌色 | 来源 |
|------|--------|------|
| web-pos 设计系统 | Mint `#0AAF9A` | tokens/colors.ts |
| h5-self-order | Orange `#FF6B2C` | 全局CSS硬编码 |
| web-admin | Orange-Red `#FF6B35` | Ant Design theme |
| miniapp-customer-v2 | Orange `#FF6B2C` | Taro组件硬编码 |

**问题**：用户在不同终端看到完全不同的品牌色，品牌认知割裂。

### 1.2 菜品卡片（DishCard）四端四写

| 终端 | 文件 | 布局 | 样式方案 |
|------|------|------|----------|
| web-pos | CashierPage.tsx 内联 | 左菜单右购物车 | 内联style |
| h5-self-order | DishCard.tsx | 横向：图左信息右 | CSS Modules |
| miniapp-v2 | DishCard/index.tsx | 横向：160rpx图+信息 | Taro CSS |
| web-crew | AddDishSheet.tsx | 简化列表 | 内联style |

**问题**：同一个"菜品卡片"组件写了4遍，逻辑/样式/交互全部不一致。

### 1.3 设计系统孤岛化

- `web-pos/src/design-system/` 有完整的 Z* 组件库（ZButton、ZCard、ZInput 等 18个组件）
- 但**只有 web-pos 在使用**，其他 5 个前端应用完全独立造轮子
- 没有 `shared/design-system/` 或 `packages/ui/` 共享包
- 没有 Storybook 文档，没有组件用法指南

### 1.4 菜单交互模式碎片化

| 模式 | web-pos | h5-self-order | miniapp | web-admin |
|------|---------|---------------|---------|-----------|
| 分类导航 | 顶部Tab | 左侧边栏+右grid | Tab栏 | 树形菜单 |
| 菜品搜索 | 无 | 有（含语音） | 有 | 有 |
| 规格/做法选择 | Bottom Sheet | 无 | 弹窗 | 表单 |
| 购物车 | 右侧固定面板 | 底部悬浮Bar | 底部悬浮 | N/A |
| 套餐选择 | ComboSelectorSheet | 无 | 无 | 表格配置 |

### 1.5 触控适配不统一

- web-pos `.shell--store` 定义 56px 触控目标 — 但 CashierPage 内菜品按钮未遵守
- h5-self-order 最小触控 44px — 符合 Apple HIG 但偏小
- 行业最佳实践（油手环境）推荐 **56-64px** 触控目标 + **10-12px** 间距
- KDS 页面无防误触设计

---

## 二、全球最佳实践提炼

### 2.1 来自 Toast / Square / Lightspeed 的 POS 设计原则

| 原则 | 含义 | 屯象现状 |
|------|------|----------|
| **最少点击** | 从选品到结账 ≤3步操作 | CashierPage 基本达标 |
| **分屏布局** | 左=菜单浏览，右=实时订单 | CashierPage 已采用 |
| **搜索优先** | 100+品时搜索比分类更快 | web-pos 缺失搜索 |
| **快捷键/手势** | 高频操作绑定快捷键 | ShortcutOverlay 已有，需扩展 |
| **KDS 无滚动** | 厨房屏分页不滚动，防油手 | web-kds 仍用滚动 |
| **深色KDS** | 厨房暗光+减少眼疲劳 | 已是深色，good |

### 2.2 来自美团/饿了么的中国餐饮 UI 模式

| 模式 | 说明 | 建议 |
|------|------|------|
| **底部上滑面板** | 规格/做法选择用上滑卡片 | 替代当前 modal 弹窗 |
| **密集信息仪表板** | 首页一屏展示营收/订单/评分 | POSDashboardPage 可参考 |
| **多渠道聚合** | 堂食/美团/饿了么/抖音统一视图 | OmniChannelOrders 已有框架 |
| **即时营销耦合** | 菜单管理 + 促销活动同屏 | web-admin 菜单页可增强 |

### 2.3 Apple HIG / Material Design 3 的触控规范

```
最小触控面积：56×56px（餐饮油手环境推荐 64×64px）
触控间距：    12px（最小 8px）
字号下限：    16px body / 18-20px 菜品名（手臂距离可读）
对比度：      WCAG AA 4.5:1（弱光厨房环境推荐 7:1）
圆角：        12-16px（Apple 风格，现有 tokens 已对齐）
动效：        150-300ms spring curve（现有 motion tokens 已对齐）
```

---

## 三、升级方案：四层架构

### 架构总览

```
┌─────────────────────────────────────────────────────────┐
│  L3  终端适配层   web-pos / h5 / miniapp / admin / kds  │
│       ↓ 只做布局组合 + 终端特有逻辑                       │
├─────────────────────────────────────────────────────────┤
│  L2  业务组件层   DishCard / CartPanel / CategoryNav     │
│       ↓ 共享菜单业务组件（React + CSS Modules）           │
├─────────────────────────────────────────────────────────┤
│  L1  基础组件层   ZButton / ZCard / ZInput / ZBadge      │
│       ↓ 现有 Z* 组件库提升为共享包                        │
├─────────────────────────────────────────────────────────┤
│  L0  设计令牌层   colors / spacing / typography / motion  │
│       统一品牌色 + 语义变量 + CSS Custom Properties       │
└─────────────────────────────────────────────────────────┘
```

---

## 四、L0 设计令牌统一方案

### 4.1 品牌色决策

**建议：统一为 Mint `#0AAF9A` 作为品牌主色，Orange `#FF6B2C` 降级为行动色/CTA色。**

理由：
- Mint 是 v2 设计系统正式定义，有完整 50-900 色阶
- 橙色在餐饮行业过于常见（美团橙、饿了么蓝橙），Mint 是差异化识别
- Orange 保留为购物车/加购按钮/CTA 行动色，符合餐饮心理学（暖色促食欲）

```typescript
// shared/design-tokens/colors.ts（统一版）
export const brand = {
  50: '#E6F7F5', 500: '#0AAF9A', 600: '#099987', 700: '#078070'
};
export const action = {
  primary: '#FF6B2C',   // CTA按钮、加购、结算
  hover:   '#E55A1E',
  active:  '#CC4F1A',
};
```

### 4.2 语义变量规范

```css
/* 所有终端共享的语义变量命名 */
--tx-bg-base:         /* 页面底色 */
--tx-bg-surface:      /* 卡片/面板底色 */
--tx-bg-elevated:     /* 悬浮/弹窗底色 */
--tx-text-primary:    /* 主文字 */
--tx-text-secondary:  /* 次要文字 */
--tx-text-tertiary:   /* 辅助文字 */
--tx-border:          /* 分割线/边框 */
--tx-brand:           /* 品牌色（Mint） */
--tx-action:          /* 行动色（Orange，加购/结算） */
--tx-success:         /* 成功/已完成 */
--tx-warning:         /* 警告/超时提醒 */
--tx-danger:          /* 危险/售罄/过期 */
--tx-info:            /* 信息/提示 */
```

### 4.3 终端专属 Shell Token

```css
/* 不同终端的触控/字号差异通过 Shell Class 控制 */
.shell--pos     { --tx-touch-min: 56px; --tx-font-body: 14px; --tx-font-dish: 18px; }
.shell--kds     { --tx-touch-min: 64px; --tx-font-body: 16px; --tx-font-dish: 24px; }
.shell--crew    { --tx-touch-min: 48px; --tx-font-body: 16px; --tx-font-dish: 16px; }
.shell--h5      { --tx-touch-min: 44px; --tx-font-body: 14px; --tx-font-dish: 16px; }
.shell--admin   { --tx-touch-min: 32px; --tx-font-body: 13px; --tx-font-dish: 14px; }
```

---

## 五、L1 基础组件库共享方案

### 5.1 目标目录结构

```
shared/
  design-system/
    tokens/
      colors.ts          # 统一色板
      typography.ts       # 统一字体
      spacing.ts          # 统一间距
      elevation.ts        # 阴影/圆角/动效
      index.ts            # injectTokens()
    themes/
      light.ts
      dark.ts
      kds.ts              # KDS 专用高对比主题
    components/
      ZButton/
        ZButton.tsx
        ZButton.module.css
        ZButton.stories.tsx   # Storybook 文档
      ZCard/
      ZInput/
      ZBadge/
      ZTag/
      ZModal/
      ZDrawer/
      ZTabs/
      ZTable/
      ZSelect/
      ZAlert/
      ZAvatar/
      ZEmpty/
      ZSkeleton/
      ZKpi/
      index.ts
    hooks/
      useTheme.ts         # 主题切换 hook
      useShell.ts         # 终端检测 hook
    utils/
      formatPrice.ts      # 分→元 统一格式化
      cn.ts               # className 合并工具
    index.ts
```

### 5.2 从 web-pos 提取的路径

现有 `apps/web-pos/src/design-system/` 的 18 个 Z* 组件 **整体迁移** 到 `shared/design-system/`，然后：
- web-pos 改为 `import { ZButton } from '@shared/design-system'`
- h5-self-order / web-crew / web-kds 逐步接入
- miniapp-customer-v2（Taro）通过条件编译或 CSS 变量注入

### 5.3 新增 KDS 高对比主题

```typescript
// shared/design-system/themes/kds.ts
export const kdsTheme = {
  '--tx-bg-base':       '#000000',
  '--tx-bg-surface':    '#1A1A1A',
  '--tx-text-primary':  '#FFFFFF',
  // 时间指示器（行业标准）
  '--tx-kds-green':     '#22C55E',  // < 5分钟
  '--tx-kds-amber':     '#F59E0B',  // 5-10分钟
  '--tx-kds-red':       '#EF4444',  // > 10分钟
  // 超大字号
  '--tx-font-ticket':   '20px',
  '--tx-font-item':     '18px',
  '--tx-touch-min':     '64px',
};
```

---

## 六、L2 菜单业务组件统一方案

### 6.1 统一 DishCard — 一个组件，三种变体

```
┌─ DishCard variant="grid" ──────────┐    ┌─ DishCard variant="horizontal" ─┐
│ ┌───────────────────┐              │    │ ┌────────┐                      │
│ │                   │              │    │ │        │ 剁椒鱼头              │
│ │     菜品图片       │              │    │ │  图片  │ 招牌 · 辣度★★        │
│ │                   │              │    │ │ 110px  │ ¥88.00  会员¥78      │
│ └───────────────────┘              │    │ │        │            [+]       │
│ 剁椒鱼头                            │    │ └────────┘                      │
│ ¥88.00          [+]               │    └────────────────────────────────┘
└────────────────────────────────────┘
                                          ┌─ DishCard variant="compact" ───┐
用于：POS 收银页（平板/大屏）              │  剁椒鱼头        ¥88.00   [+]  │
                                          └────────────────────────────────┘
用于：H5/小程序菜单浏览                    用于：服务员加菜/搜索结果
```

```typescript
// shared/design-system/components/DishCard/DishCard.tsx
interface DishCardProps {
  dish: DishData;
  variant: 'grid' | 'horizontal' | 'compact';
  quantity?: number;
  showMemberPrice?: boolean;
  showTags?: boolean;
  showAllergens?: boolean;
  onAdd: () => void;
  onTap: () => void;
  // 终端感知
  shell?: 'pos' | 'h5' | 'crew' | 'miniapp';
}
```

### 6.2 统一 CategoryNav — 两种布局

```
┌─ CategoryNav layout="sidebar" ─────────────────────────────────────┐
│ ┌──────────┐ ┌────────────────────────────────────────────────┐   │
│ │ 热菜  ●  │ │                                                │   │
│ │ 凉菜     │ │              菜品网格/列表                      │   │
│ │ 活鲜     │ │                                                │   │
│ │ 主食     │ │                                                │   │
│ │ 饮品     │ │                                                │   │
│ │ 套餐     │ │                                                │   │
│ └──────────┘ └────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
用于：H5自助点餐（竖屏手机）

┌─ CategoryNav layout="topbar" ─────────────────────────────────────┐
│ [全部] [热菜●] [凉菜] [活鲜] [主食] [饮品] [套餐]    🔍 搜索     │
│ ┌────────────────────────────────────────────────────────────┐   │
│ │                     菜品网格                                │   │
│ └────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
用于：POS收银/平板（横屏大屏）
```

### 6.3 统一 CartPanel — 两种形态

```
┌─ CartPanel mode="sidebar" ──┐      ┌─ CartPanel mode="bottom-bar" ────────────┐
│ 当前订单  桌号 A12          │      │ 🛒 3  │  合计 ¥198.00  │ [ 去结算 ]     │
│ ─────────────────────       │      └────────────────────────────────────────────┘
│ 剁椒鱼头    ×1    ¥88.00   │      用于：H5/小程序/服务员手机（竖屏）
│ 口味虾      ×1    ¥128.00  │
│ 米饭        ×2    ¥6.00    │      点击展开为 BottomSheet：
│ ─────────────────────       │      ┌────────────────────────────────────────┐
│ 小计             ¥222.00   │      │ 购物车                          [清空] │
│ [ 挂单 ]  [ 结算 ¥222.00 ] │      │ ────────────────────────────────────── │
└─────────────────────────────┘      │ 剁椒鱼头   [-] 1 [+]        ¥88.00   │
用于：POS收银（右侧固定面板）         │ 口味虾     [-] 1 [+]        ¥128.00  │
                                     │ ────────────────────────────────────── │
                                     │ 合计 ¥216.00    [ 去结算 ¥216.00 ]    │
                                     └────────────────────────────────────────┘
```

### 6.4 统一 SpecSheet — 规格/做法选择

全终端统一使用**底部上滑面板**（Bottom Sheet），替代现有的 modal 弹窗：

```
┌──────────────────────────────────────────┐
│                                          │
│             （页面内容变暗）               │
│                                          │
├──────────────────────────────────────────┤  ← 手势拖拽条
│  剁椒鱼头                         ¥88.00 │
│  ──────────────────────────────────────  │
│  辣度    ○ 微辣  ● 中辣  ○ 特辣         │
│  做法    ○ 清蒸  ● 红烧  ○ 剁椒         │
│  配菜    ☑ 豆腐 ☑ 粉丝  ☐ 金针菇       │
│  ──────────────────────────────────────  │
│  数量    [-]  1  [+]                     │
│                                          │
│  [ 加入购物车  ¥88.00 ]                  │
└──────────────────────────────────────────┘
```

**来源**：美团/饿了么的上滑面板已被中国用户充分验证，比 modal 更适合触屏。

### 6.5 统一 MenuSearch — 搜索组件

```typescript
// 所有菜单场景顶部均提供搜索
interface MenuSearchProps {
  placeholder?: string;      // 默认："搜索菜品"
  enableVoice?: boolean;     // H5/小程序开启语音搜索
  onSearch: (keyword: string) => void;
  recentSearches?: string[]; // 最近搜索（本地存储）
}
```

**为什么必须有搜索**：100+ 品的菜单，收银员找菜品平均用搜索比翻分类快 3 倍（Toast 数据）。

---

## 七、L3 各终端菜单页面重构方案

### 7.1 web-pos CashierPage 重构

**现状**：CashierPage.tsx 约 300 行，菜品展示和购物车逻辑内联在一个文件。

**目标**：

```
CashierPage.tsx（轻量编排层）
├── <MenuSearch />                    ← 新增：顶部搜索
├── <CategoryNav layout="topbar" />   ← 共享组件
├── <DishGrid>                        ← 新增：菜品网格容器
│   └── <DishCard variant="grid" />   ← 共享组件
├── <CartPanel mode="sidebar" />      ← 共享组件
├── <SpecSheet />                     ← 共享组件（底部上滑）
├── <LiveSeafoodOrderSheet />         ← 保留：活鲜专用
└── <ComboSelectorSheet />            ← 保留：套餐专用
```

**关键改进**：
1. 菜品搜索 — 顶部常驻搜索框，支持拼音/首字母
2. 快捷键增强 — `F1-F9` 快速切换分类，`/` 聚焦搜索
3. 收藏菜品 — 常点菜品置顶，减少翻找
4. 智能推荐条 — DishRecommendBanner 基于桌号/时段/历史推荐

### 7.2 h5-self-order 重构

**现状**：自有 DishCard + CartBar + MenuBrowse，独立样式体系。

**目标**：

```
MenuBrowse.tsx（布局编排）
├── <MenuSearch enableVoice />
├── <CategoryNav layout="sidebar" />
├── <DishList>
│   └── <DishCard variant="horizontal" shell="h5" />
├── <CartPanel mode="bottom-bar" />
└── <SpecSheet />                     ← 新增：规格选择
```

**关键改进**：
1. 接入共享 DishCard（`variant="horizontal"`），样式通过 `--tx-*` 变量控制
2. 新增规格/做法选择（SpecSheet），当前缺失
3. 购物车展开态 — 从 CartBar 上滑展开完整购物车列表
4. 套餐选择 — 复用 ComboSelectorSheet

### 7.3 web-kds 重构

**关键原则**：厨房屏 = 大字 + 高对比 + 无滚动 + 单击操作

```
KDS 布局：
┌───────────────────────────────────────────────────────┐
│ 状态栏：待出 12 | 制作中 5 | 超时 2        14:32:05  │
├──────┬──────┬──────┬──────┬──────┬──────┬─────────────┤
│ A03  │ A07  │ B12  │ A01  │ A09  │ B03  │  ...分页    │
│ 5:32 │ 3:15 │ 8:47 │ 1:22 │ 12:0 │ 2:45 │             │
│ ──── │ ──── │ ──── │ ──── │ ──── │ ──── │             │
│ 剁椒  │ 口味  │ 小炒  │ 米饭  │ 鲈鱼  │ 黄瓜  │             │
│ 鱼头  │ 虾   │ 肉   │ ×3  │ (活) │     │             │
│ ×1   │ ×1   │ ×2   │     │ ×1   │ ×2   │             │
│      │      │ 🔴   │     │ 🔴   │      │             │
│[完成] │[完成] │[完成] │[完成] │[完成] │[完成] │             │
└──────┴──────┴──────┴──────┴──────┴──────┴─────────────┘
```

**改进点**：
1. 分页不滚动 — 左右翻页，每页最多 6-8 张票卡
2. 时间色标 — 绿(<5min) / 黄(5-10min) / 红(>10min)，渐变过渡
3. 一键完成 — 单击 bump 出票，无确认弹窗（厨房场景速度第一）
4. 同品聚合视图 — 可切换"按桌号"或"按菜品聚合"（批量制作模式）

### 7.4 web-admin 菜单管理重构

```
菜单管理中心
├── 菜品库 — 全品牌菜品 CRUD + BOM + 四象限分析
├── 菜单方案 — 时段菜单/渠道菜单/节日菜单模板
├── 实时控制 — LiveMenuEditor（沽清/限量/临时调价）
├── 菜单工程 — AI 菜品优化建议（毛利/销量矩阵）
├── 渠道同步 — 堂食/美团/饿了么/抖音一键同步
└── 菜品分析 — 销量排行/毛利排行/退菜分析
```

**改进点**：
1. 菜单管理 + 营销耦合 — 菜品编辑页可直接创建"新品推荐"营销活动
2. 菜品图片 AI 生成 — 接入 AI 生成菜品图，解决小品牌无专业摄影问题
3. 一键多渠道发布 — 编辑一次，美团/饿了么/抖音/堂食同步更新

---

## 八、关键交互设计规范

### 8.1 加购动效（全终端统一）

```
点击 [+] 按钮：
1. 按钮 scale 0.85 → 1.0（150ms spring）
2. 菜品图片缩略图抛物线飞入购物车图标（300ms ease-out）
3. 购物车图标 shake 动效（200ms）
4. 购物车数量 +1 放大弹跳（200ms spring）
```

### 8.2 分类切换动效

```
点击分类 Tab：
1. Tab 下划线滑动过渡（250ms spring）
2. 菜品列表 fade-out（100ms）→ fade-in（200ms）
3. 可选：列表 stagger 逐个淡入（每项延迟 30ms）
```

### 8.3 购物车展开动效（H5/小程序）

```
点击 CartBar：
1. 蒙层 fade-in（150ms）
2. 购物车面板 slide-up（300ms spring）
3. 每个购物项 stagger 淡入（延迟 50ms）
```

### 8.4 售罄状态

```
菜品售罄时：
- 图片加灰色遮罩（opacity 0.5）
- 右下角显示"已售罄"标签（红底白字）
- [+] 按钮禁用，变灰色
- 整张卡片不可点击
```

---

## 九、性能优化规范

### 9.1 菜品图片

```typescript
// 图片加载策略
const IMAGE_STRATEGY = {
  // 列表页缩略图
  thumbnail: { width: 200, quality: 75, format: 'webp', lazy: true },
  // 详情页大图
  detail:    { width: 600, quality: 85, format: 'webp', lazy: false },
  // KDS 不加载图片
  kds:       null,
  // 渐进加载：低质量模糊图 → 高清图
  placeholder: { width: 20, quality: 30, format: 'webp', blur: true },
};
```

### 9.2 菜品数据缓存

```typescript
// 菜品列表缓存策略（SWR/React Query 模式）
const CACHE_STRATEGY = {
  staleTime:    60_000,     // 1分钟内直接用缓存
  gcTime:       300_000,    // 5分钟后清除
  refetchOnFocus: true,     // 窗口聚焦时刷新
  // 离线时使用本地 IndexedDB 缓存
  offlineFallback: true,
};
```

### 9.3 虚拟滚动

菜品数量 > 50 时启用虚拟滚动（react-window），避免 DOM 节点过多。

---

## 十、实施路线图

### Phase 1：令牌统一（1周）

```
目标：所有终端共享同一套设计令牌
───────────────────────────────────
1. 创建 shared/design-system/tokens/
2. 从 web-pos/src/design-system/tokens/ 迁移
3. 统一品牌色决策（Mint品牌 + Orange行动）
4. 所有终端接入 CSS Custom Properties
5. 验证深色/浅色主题切换
```

### Phase 2：基础组件提取（1周）

```
目标：Z* 组件库成为共享包
───────────────────────────────────
1. 迁移 18 个 Z* 组件到 shared/design-system/components/
2. 配置 TypeScript path alias + 构建集成
3. web-pos 率先切换 import 路径
4. 搭建 Storybook 文档（可选，视时间）
```

### Phase 3：菜单业务组件统一（2周）

```
目标：DishCard / CategoryNav / CartPanel / SpecSheet 各终端复用
───────────────────────────────────
1. 实现统一 DishCard（三种 variant）
2. 实现统一 CategoryNav（两种 layout）
3. 实现统一 CartPanel（两种 mode）
4. 实现统一 SpecSheet（Bottom Sheet）
5. 实现统一 MenuSearch
6. web-pos CashierPage 接入
7. h5-self-order 接入
```

### Phase 4：KDS 重构 + 终端适配（1周）

```
目标：KDS 无滚动 + 时间色标 + 高对比主题
───────────────────────────────────
1. KDS 主题（kds.ts）接入
2. 票卡分页布局替代滚动
3. 时间色标 + 一键bump
4. web-crew 接入共享组件
```

### Phase 5：高级功能（2周）

```
目标：搜索 + 动效 + 智能推荐
───────────────────────────────────
1. 菜品搜索（拼音/首字母/语音）
2. 加购抛物线动效
3. AI 智能推荐条
4. 菜品图片渐进加载
5. 虚拟滚动（大菜单）
6. 多渠道菜单同步
```

---

## 十一、度量指标

| 指标 | 当前 | 目标 | 方法 |
|------|------|------|------|
| 收银员选菜平均时间 | 未知 | < 5秒/品 | 埋点统计 |
| DishCard 代码重复度 | 4份 × ~100行 | 1份共享 | 代码行数 |
| 品牌色一致性 | 3种色板 | 1套统一 | 视觉走查 |
| KDS 出票确认时间 | 需2次点击 | 1次点击 | 操作录像 |
| 首屏菜单渲染时间 | 未知 | < 800ms | Lighthouse |
| 触控目标合规率 | ~60% | 100% | 自动化检测 |
| 设计系统组件复用率 | ~20% | > 80% | import 分析 |

---

## 十二、与现有架构的兼容性

### 与 CLAUDE.md 规范的对齐

| CLAUDE.md 条款 | 本方案对应 |
|---------------|-----------|
| React 18 + TypeScript + Zustand | 所有共享组件基于此技术栈 |
| 外设调用通过 TXBridge 抽象 | DishCard 不涉及外设，CartPanel 结算按钮触发 TXBridge |
| CSS Modules 为主 | 所有 Z* 组件使用 CSS Modules + CSS Custom Properties |
| 终端差异通过 Shell Class | 通过 `--tx-touch-min` 等 Shell Token 控制 |
| Kotlin/Swift 不写业务逻辑 | 菜单/UI 全部在 React Web App 层，壳层不涉及 |

### 与事件总线的对齐

菜品沽清/恢复 通过事件推送到所有终端：
```
emit_event(MENU.DISH_SOLD_OUT) → WebSocket → 所有终端 DishCard 实时更新
emit_event(MENU.PRICE_CHANGED) → WebSocket → 所有终端价格刷新
```

---

## 附录A：全球参考对标

| 公司 | 值得学习的点 | 屯象对应 |
|------|-------------|---------|
| Toast POS | 分屏布局 + 菜单搜索 + 快捷键 | CashierPage |
| Square | 极简操作流 ≤3步结账 | 点菜→确认→结算 |
| Lightspeed | 菜品图片卡片网格 | DishCard grid |
| 美团商家版 | 底部上滑规格面板 + 营销耦合 | SpecSheet + 菜单+营销 |
| 饿了么商家版 | 多渠道订单聚合 | OmniChannelOrders |
| Apple HIG | 44-56px触控 + 12px圆角 + spring动效 | 设计令牌已对齐 |
| Material Design 3 | 语义色系统 + elevation层级 | --tx-* 语义变量 |

---

## 附录B：设计参考色板一览

```
品牌识别色：
  Mint 500    #0AAF9A   ████████  品牌主色（标识/导航/选中态）
  Mint 50     #E6F7F5   ████████  浅底色（选中行/高亮区域）

行动/转化色：
  Orange      #FF6B2C   ████████  CTA按钮/加购/结算
  Orange Hover #E55A1E  ████████  悬停态

语义色：
  Success     #22C55E   ████████  已完成/KDS绿灯
  Warning     #F59E0B   ████████  KDS黄灯/库存预警
  Danger      #EF4444   ████████  售罄/KDS红灯/异常
  Info        #2D9CDB   ████████  提示/新品

深色主题背景：
  Base        #0B1A20   ████████  页面底色
  Surface     #0D2029   ████████  卡片底色
  Elevated    #132A35   ████████  弹窗底色

文字层级（深色主题）：
  T1 Primary   rgba(255,255,255,0.92)  主标题
  T2 Secondary rgba(255,255,255,0.65)  副文字
  T3 Tertiary  rgba(255,255,255,0.38)  辅助说明
  T4 Disabled  rgba(255,255,255,0.08)  分割线
```
