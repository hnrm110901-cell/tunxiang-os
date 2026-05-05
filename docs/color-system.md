# 屯象OS 色彩设计系统

> 版本：v4 — 2026-05-04
> 设计原则：品牌识别 ≠ UI 主色。橙色是 CTA 色，不是底色。

---

## 一、核心理念：三个层次的颜色分工

```
品牌层（≤10%  UI 面积）
  └─ #FF6B35 暖橙 — Logo / 图标 / 营销物料 / 品牌元素
  └─ 金色 #FFC244 — VIP 会员标识（<1% 面积）

操作层（15%  UI 面积）
  └─ #FF6B35 橙 — CTA 按钮 / 价格 / 待处理项
  └─ #34D399 绿 — 成功 / 正常 / 通过
  └─ #F87171 红 — 超时 / 报错 / 硬约束违反
  └─ #60A5FA 蓝 — 信息 / 提示

基础层（75%+ UI 面积）
  └─ #0B1A20 深青 — 主背景
  └─ #0D2029 深青 — 面板 / 卡片
  └─ #132830 浅青 — hover 态
  └─ 白色 92%/65%/38%/8% 透明度层级 — 文字
```

**核心约束：橙色只出现在"需要操作"的地方，不装饰、不填充、不点缀。**

---

## 二、色彩令牌参考表

### 2.1 品牌色 Brand

| 令牌 | 值 | 用途 | 出现频率 |
|------|-----|------|---------|
| `brand[50]` | `#FFF3ED` | CTA 按钮轻背景 | 组件级 |
| `brand[100]` | `#FFE0CC` | — | 极低频 |
| `brand[200]` | `#FFBD99` | — | 极低频 |
| `brand[300]` | `#FF9966` | CTA active 态 | 组件级 |
| `brand[400]` | `#FF8555` | CTA hover 态 | 组件级 |
| `brand[500]` | `**#FF6B35**` | **CTA 按钮 / 价格 / 活跃指示器** | 操作点 |
| `brand[600]` | `#E55A28` | CTA pressed 态 | 组件级 |
| `brand[700]` | `#CC4A1A` | CTA 深色 hover | 组件级 |
| `brand[800]` | `#A33515` | — | 极低频 |
| `brand[900]` | `#7A2510` | — | 极低频 |

### 2.2 基础色 Base

| 令牌 | 值 | 用途 |
|------|-----|------|
| `base.bg` | `#0B1A20` | 最深底色 — POS/Admin 主背景 |
| `base.raised` | `#0D2029` | 面板 / 卡片 / sidebar |
| `base.hover` | `#132830` | hover 增强 |
| `base.input` | `#1a2a33` | 输入框 / 分割线 |
| `base.border` | `rgba(255,255,255,0.08)` | 默认边框 |
| `base.borderStrong` | `rgba(255,255,255,0.15)` | 强调边框 |

### 2.3 文字色 Text

| 令牌 | 值 | 用途 |
|------|-----|------|
| `text[1]` | `rgba(255,255,255,0.92)` | 主文字 — 标题 / KPI |
| `text[2]` | `rgba(255,255,255,0.65)` | 次要文字 — 正文 / 标签 |
| `text[3]` | `rgba(255,255,255,0.38)` | 辅助文字 — 注释 / 灰化 |
| `text[4]` | `rgba(255,255,255,0.08)` | 禁用 / 分割线 |

浅色模式下的文字以 navy `#1E2A3A` 为基色，透明度同理。

### 2.4 语义色 Semantic

| 色名 | 暗色模式 | 浅色模式 | 用途 |
|------|---------|---------|------|
| `green` | `#34D399` | `#27AE60` | KDS 正常 / 成功 / 已确认 |
| `amber` | `#FBBF24` | `#F2994A` | 接近阈值 / 待处理 |
| `red` | `#F87171` | `#EB5757` | 超时 / 报错 / 硬约束违反 |
| `blue` | `#60A5FA` | `#2D9CDB` | 信息 / 提示 / 通知 |

### 2.5 CTA 行动色 Action（品牌色别名）

```typescript
// 物理值 = brand[500..700]，语义别名用于 CTA 场景
action.primary = brand[500]   // #FF6B35
action.hover   = brand[400]   // #FF8555
action.active  = brand[300]   // #FF9966
action.soft    = rgba(255,107,53,0.12)
action.bg      = brand[50]    // #FFF3ED
```

### 2.6 特殊色 Special

| 色名 | 值 | 用途 |
|------|-----|------|
| `gold` | `#FFC244` | VIP 会员标识、钻石勋章 |
| `kdsGreen` | `#22C55E` | KDS < 5min 正常 |
| `kdsAmber` | `#F59E0B` | KDS 5-10min 警告 |
| `kdsRed` | `#EF4444` | KDS > 10min 超时 |

---

## 三、各终端色值分配

### POS（web-pos）

| 元素 | 色值 | 说明 |
|------|------|------|
| 主背景 | `#0B1A20` | 深青底色 |
| 卡片/面板 | `#0D2029` | raised surface |
| **结算/下单按钮** | **`brand[500]`** | **唯一 CTA，独享橙** |
| **价格/金额** | **`brand[500]`** | **橙** |
| 菜品卡价格 | `brand[500]` | 橙，与"操作"绑定 |
| 菜品卡文字 | `text[1]` | 白色 |
| 活跃 Tab | `brand[500]` | 橙色下划线/文字 |
| 折扣预警标题 | `red` | 红，不是橙 |
| 库存预警 | `amber` | 黄，不是橙 |
| 加载 Spinner | `text[3]` | 灰色，不是橙 |
| 确认弹窗标题 | `text[1]` | 白色，不是橙 |
| AI 置信度进度条 | green/amber/red 三阶 | 不染橙 |

### KDS（web-kds）

| 元素 | 色值 | 说明 |
|------|------|------|
| 主背景 | `#000000` | 纯黑最高对比 |
| **不出现品牌橙** | — | 厨房不需要品牌色 |
| 时间正常 | `#22C55E` | < 5min |
| 时间警告 | `#F59E0B` | 5-10min |
| 时间超时 | `#EF4444` | > 10min |
| 卡片文字 | `#FFFFFF` 92% | 高对比白 |
| 新单高亮 | `rgba(34,197,94,0.15)` | 绿色轻背景 |
| 催单高亮 | `rgba(239,68,68,0.15)` | 红色轻背景 |

### Crew（web-crew）

| 元素 | 色值 | 说明 |
|------|------|------|
| 主背景 | `#0B1A20` | 同 POS |
| **点餐/叫服务按钮** | **`brand[500]`** | **唯一 CTA** |
| 台位状态 | green/amber/red | 语义三色 |
| VIP 标识 | `#FFC244` | 金色 |
| 次要操作 | `text[3]` | 灰化 |

### Admin（web-admin）

| 元素 | 色值 | 说明 |
|------|------|------|
| 主背景 | `#0D2029`（侧栏）/ `#f5f5f5`（内容区） | 混合模式 |
| **侧栏活跃项** | **`brand[500]`** | **橙** |
| 页面 CTA | `brand[500]` | 新建/保存/提交 |
| Agent 决策卡片 crit | `red` | 硬约束违反 |
| Agent 决策卡片 info | `blue` | 信息 |
| 图表系列色 | 彩色 10 色调色板 | 不含橙作底色 |
| NLQ 发送按钮 | `brand[500]` | 橙 |

### H5 自助点餐（h5-self-order）

| 元素 | 色值 | 说明 |
|------|------|------|
| 主背景 | `#FFFFFF`（浅色） | 顾客端轻量 |
| **去结算按钮** | **`brand[500]`** | **唯一 CTA** |
| 菜品价格 | `brand[500]` | 橙 |
| 分类 Tab 活跃 | `brand[500]` | 橙色下划线 |
| 其他 | 白色/灰色 | 不变 |

---

## 四、反模式与自动审查

### 4.1 禁止模式（CI 检查项）

| # | 禁止 | 原因 | 替代 |
|---|------|------|------|
| 1 | 橙色作为卡片/面板背景 | 扩大橙色面积，视觉疲劳 | 使用 `base.raised`（`#0D2029`） |
| 2 | 橙色作为加载动画色 | 加载不需要吸引注意力 | 使用 `text[3]`（`rgba(255,255,255,0.38)`） |
| 3 | 橙色作为进度条底色 | 进度条有语义三色 | 使用 `green/amber/red` 三阶 |
| 4 | 橙色作为标签/Tag 色（非 CTA） | 标签应中性 | 使用中性色或语义色 |
| 5 | 橙色作为边框色（非 CTA） | 边框应低调 | 使用 `base.border` |
| 6 | 橙色作为非活跃元素的 hover | hover 不应抢 CTA 风头 | 使用 `base.hover`（`#132830`） |
| 7 | 硬编码 `#FF6B35` 之外的橙色值 | 防止色值漂移 | 统一使用 `brand[500]` |
| 8 | 浅色模式中使用 `#0AAF9A` | 品牌色已统一为 `#FF6B35` | 使用 `brand[500]` |

### 4.2 自动审查策略

```yaml
# scripts/lint-colors.sh 或 ESLint 插件
rules:
  - pattern: "#0AAF9A"    # 旧 mint 主色
    action: error
    message: "品牌色已变更为 #FF6B35（brand[500]），使用 @tx/tokens 导出"
  - pattern: "#FF6B2C"    # h5-self-order 独立色值
    action: warning
    message: "使用 brand[500]（#FF6B35），非 #FF6B2C"
  - pattern: "#e55a28\|#E55A28"  # brand[600] 仅用于 pressed
    action: info
    message: "确认使用场景：仅用于 CTA pressed 态"
  - pattern: 'color:\s*#FF6B35|background:\s*#FF6B35|border.*#FF6B35'
    action: warning  # 每个橙色出现应被审查
    message: "橙色作为 CTA 被使用，确认上下文是否为操作点"
```

---

## 五、维护与管理

### 5.1 数据流

```
docs/color-system.md            ← 设计规范，唯一真理源
  │
  ▼
shared/design-system/src/tokens/colors.ts   ← 所有终端的程序化令牌
  │
  ├──▶ apps/*/ （9 个前端应用）
  │       └── sidebar 品牌色
  │       └── Ant Design 主题
  │       └── Tailwind 配置
  │
  ├──▶ packages/tx-tokens/     ← v1 兼容层
  │       └── tokens.css（CSS 变量降级）
  │       └── antd-theme.ts（AntD 主题）
  │
  └──▶ docs/color-system.md    ← 自持一致性
```

### 5.2 如何新增一个颜色

1. 先在 `shared/design-system/src/tokens/colors.ts` 中定义
2. 在 `docs/color-system.md` 的"色彩令牌参考表"中注册用途
3. 在"反模式"中判断是否需要添加禁止规则
4. 在各终端的"色值分配"表中确认是否需新增
5. 审查影响范围内所有硬编码色值

### 5.3 迁移进度

> ✅ = 已更新至 v3（暖橙 #FF6B35），🟡 = 色值已正确但需架构优化，🔴 = 仍有问题

| 文件 | 状态 | 优先级 |
|------|------|--------|
| `shared/design-system/src/tokens/colors.ts` | ✅ v3 已更新 | — |
| `shared/design-system/src/tokens/index.ts` | ✅ v3 已更新 | — |
| `shared/design-system/src/themes/dark.ts` | ✅ v3 已对齐 | — |
| `shared/design-system/src/themes/light.ts` | ✅ v3 已对齐 | — |
| `shared/design-system/src/themes/kds.ts` | ✅ v3 零品牌色原则 | — |
| `packages/tx-tokens/src/tokens.ts` | 🟡 色值正确（独立副本，未引用 shared） | 低 |
| `packages/tx-tokens/src/tokens.css` | 🟡 色值正确（独立副本） | 低 |
| `packages/tx-tokens/src/antd-theme.ts` | 🟡 色值正确（独立副本） | 低 |
| `apps/web-pos/src/design-system/` | 🟡 本地副本色值已正确，长期应统一到 shared | 中 |
| `apps/web-admin/src/theme/antd-theme.ts` | 🟡 硬编码色值 #FF6B35 正确，建议替换为导入 | 低 |
| `apps/h5-self-order/src/styles/global.css` | ✅ 已修复 #FF6B2C → #FF6B35 | — |
| `apps/web-wecom-sidebar/tailwind.config.js` | 🟡 需确认引用路径 | 低 |
| `apps/miniapp-customer-v2/tailwind.config.js` | 🟡 需确认引用路径 | 低 |

---

## 六、附录

### 6.1 竞品配色对比

| 产品 | 品牌色 | UI 主色 | 品牌色占比 |
|------|-------|---------|-----------|
| Toast POS | `#2E6B4E` 深绿 | `#1A1A2E` 深蓝黑 | ~8% |
| Lightspeed | `#0051C0` 蓝 | `#1C2333` 深蓝灰 | ~10% |
| Square | `#00D68F` 绿 | `#FFFFFF` 白 | ~5% |
| **屯象OS v3** | **`#FF6B35` 橙** | **`#0B1A20` 深青** | **~8%** |
| 天财商龙 | `#2B6CB0` 蓝 | `#F0F2F5` 浅灰 | ~15% |
| 客如云 | `#E4393C` 红 | 红 + 白 | ~40%（过高） |

### 6.2 WCAG 对比度验证

| 前景 | 背景 | 对比度 | 等级 |
|------|------|--------|------|
| `#FFFFFF` | `#0B1A20` | 14.3:1 | ✅ AAA |
| `#FFFFFF` 92% (t1) | `#0D2029` | 12.8:1 | ✅ AAA |
| `#FFFFFF` 65% (t2) | `#0D2029` | 9.1:1 | ✅ AAA |
| `#FFFFFF` 38% (t3) | `#0D2029` | 5.3:1 | ✅ AA |
| `#FF6B35` | `#0B1A20` | 5.1:1 | ✅ AA（大文字 AAA） |
| `#FF6B35` | `#FFFFFF` | 3.2:1 | ⚠️ AA（仅大文字）— 浅色模式注意 |
| `#CC4A1A` | `#FFFFFF` | 4.7:1 | ✅ AA |

### 6.3 变更历史

| 日期 | 版本 | 变更说明 |
|------|------|---------|
| 2026-05-04 | v4 | 执行 v3 规范的代码修改：brand 色阶从 Mint 替换为暖橙，修复 web-pos/h5 遗留的 mint rgba 和色值偏移，KDS 零品牌色。 |
| 2026-05-04 | v3 | 设计规范编写：统一品牌色为 `#FF6B35`，橙作为 CTA 色而非底色。新增反模式列表。KDS 零橙色。 |
| 2026-04-12 | v2 | 尝试迁移到 `#0AAF9A` 薄荷绿（menu-ui-upgrade-proposal，未执行完毕） |
| — | v1 | `#FF6B35` + `@tx/tokens` 最初版本 |
