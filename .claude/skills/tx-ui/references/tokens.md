# 屯象OS Design Token 规范

> 所有终端共享同一套品牌设计语言。Token是唯一真相源。
> 改一处Token，所有终端自动更新。

## 品牌色

| Token | 值 | 用途 |
|-------|-----|------|
| `primary` | `#FF6B35` | 主色（按钮、链接、选中态、品牌标识） |
| `primaryHover` | `#FF8555` | 主色悬停态（仅Admin桌面端） |
| `primaryActive` | `#E55A28` | 主色按下态（所有终端） |
| `primaryLight` | `#FFF3ED` | 主色浅底（Tag背景、选中行背景） |
| `navy` | `#1E2A3A` | 辅色（Admin侧边栏、深色标题） |
| `navyLight` | `#2C3E50` | 辅色浅色 |

## 语义色

| Token | 值 | 用途 |
|-------|-----|------|
| `success` | `#0F6E56` | 成功/健康（毛利率达标、出餐正常、在线状态） |
| `warning` | `#BA7517` | 警告/注意（即将超时、毛利率偏低、库存偏低） |
| `danger` | `#A32D2D` | 危险/错误（超时、毛利率低于底线、沽清、Agent严重预警） |
| `info` | `#185FA5` | 信息/AI（AI推荐标记、Agent建议、CDP洞察标记） |

## 语义色在业务场景中的映射

```
毛利率：
  ≥ 设定阈值     → success绿色
  < 阈值且 ≥ 80% → warning黄色
  < 80%阈值      → danger红色

出餐时间：
  剩余 > 50% 时限 → success绿色
  剩余 ≤ 50%      → warning黄色
  已超时           → danger红色 + 脉冲动画

库存：
  充足            → 不显示颜色
  低于安全线      → warning黄色
  已沽清          → danger红色 + 灰色遮罩

Agent预警：
  info级别        → info蓝色背景
  warning级别     → warning橙色背景
  critical级别    → danger红色背景 + 脉冲动画
```

## 中性色

| Token | 值 | 用途 |
|-------|-----|------|
| `textPrimary` | `#2C2C2A` | 主要文字 |
| `textSecondary` | `#5F5E5A` | 次要文字（描述、标签） |
| `textTertiary` | `#B4B2A9` | 辅助文字（时间戳、占位符） |
| `border` | `#E8E6E1` | 边框、分割线 |
| `bgPrimary` | `#FFFFFF` | 主背景 |
| `bgSecondary` | `#F8F7F5` | 次级背景（卡片、表头） |
| `bgTertiary` | `#F0EDE6` | 三级背景（代码块、强调区） |

## 字体

### 字体族
```
-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif
```

### 字号对照表（Admin vs Store vs MiniApp）

| 级别 | Admin | Store | MiniApp(rpx) | 用途 |
|------|-------|-------|-------------|------|
| h1 | 24px | 32px | 44rpx | 页面标题 |
| h2 | 20px | 24px | 36rpx | 区域标题 |
| h3 | 16px | 20px | 32rpx | 卡片标题 |
| body | 14px | 18px | 28rpx | 正文 |
| caption | 12px | 16px | 24rpx | 辅助文字 |
| mini | 12px | **禁止** | 22rpx | 最小文字（Store终端禁止） |

**铁律：Store终端不允许出现低于16px的文字。**

## 间距

| 级别 | Admin | Store | MiniApp(rpx) |
|------|-------|-------|-------------|
| xs | 4px | 8px | 8rpx |
| sm | 8px | 12px | 16rpx |
| md | 16px | 20px | 24rpx |
| lg | 24px | 32px | 32rpx |
| xl | 32px | 48px | 48rpx |

## 圆角

| 级别 | Admin | Store | MiniApp(rpx) |
|------|-------|-------|-------------|
| sm | 4px | 8px | 8rpx |
| md | 6px | 12px | 16rpx |
| lg | 8px | 16px | 24rpx |

## 触控安全区（仅Store终端）

| 参数 | 值 | 说明 |
|------|-----|------|
| 最小点击区域 | 48×48px | Apple HIG标准 |
| 推荐点击区域 | 56×56px | 戴手套场景 |
| 关键操作按钮 | 72×72px | 确认支付/完成出餐 |
| 按钮间距 | ≥12px | 防误触 |
| 滑动触发阈值 | 30px | 区分点击和滑动 |

## 阴影

| 级别 | 值 | 用途 |
|------|-----|------|
| sm | `0 1px 2px rgba(0,0,0,0.05)` | 卡片、按钮 |
| md | `0 4px 12px rgba(0,0,0,0.08)` | 弹层、浮窗 |
| lg | `0 8px 24px rgba(0,0,0,0.12)` | Modal、全屏弹层 |

Admin和Store都用，MiniApp用小程序原生阴影。

## 动画

| 参数 | 值 | 用途 |
|------|-----|------|
| 按钮按压 | `transform: scale(0.97), 200ms ease` | Store终端所有按钮 |
| 弹层出现 | `translateY(100%) → translateY(0), 300ms ease-out` | TXSelector等弹层 |
| 预警脉冲 | `opacity 0.8→1→0.8, 1.5s infinite` | Agent critical预警 |
| 列表项入场 | `opacity 0→1, translateY(8px)→0, 200ms` | Admin表格行、Store卡片 |

**Store终端动画规则：仅用于操作反馈，不用于装饰。**

## Token的消费方式

### Admin终端（Ant Design 5.x ConfigProvider）
```tsx
import { ConfigProvider } from 'antd';
<ConfigProvider theme={txAdminTheme}>
  {children}
</ConfigProvider>
```

### Store终端（UnoCSS / CSS Variables）
```css
:root {
  --tx-primary: #FF6B35;
  --tx-success: #0F6E56;
  --tx-warning: #BA7517;
  --tx-danger: #A32D2D;
  --tx-text-1: #2C2C2A;
  --tx-text-2: #5F5E5A;
  --tx-bg-1: #FFFFFF;
  --tx-bg-2: #F8F7F5;
  --tx-radius-md: 12px;
  --tx-tap-min: 48px;
  --tx-tap-rec: 56px;
  --tx-tap-lg: 72px;
}
```

### MiniApp终端（uni.scss全局变量）
```scss
// uni.scss
$tx-primary: #FF6B35;
$tx-success: #0F6E56;
$tx-warning: #BA7517;
$tx-danger: #A32D2D;
$tx-text-1: #2C2C2A;
$tx-text-2: #5F5E5A;
$tx-radius-md: 16rpx;
```
