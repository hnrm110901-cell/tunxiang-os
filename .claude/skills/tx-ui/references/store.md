# Store 终端 · 门店触控终端（POS / KDS / Crew）

## 技术栈

```
React 18 + TypeScript (strict)
TXTouch 自定义触控组件库（禁止使用Ant Design）
Zustand（状态管理）
UnoCSS（样式）
Vite（构建）
```

## 为什么禁止Ant Design

Ant Design是为桌面鼠标操作设计的，在门店触控场景下：
- 按钮32px高 → 戴手套的收银员点不到
- Table行高40px → 满手油的厨师滑不准
- Select下拉 → 触控展开体验差
- hover反馈 → 触控设备没有hover

**所有Store终端只允许使用TXTouch组件库。**

## 触控设计铁律

```
最小点击区域：48 × 48 px （Apple HIG标准）
推荐点击区域：56 × 56 px （戴手套场景）
关键操作按钮：72 × 72 px （确认支付/完成出餐）
按钮间距：    ≥ 12 px
最小字体：    16 px（Store终端绝对底线）
KDS标题字体： ≥ 24 px（厨师2米外看）
颜色对比度：  ≥ 4.5:1 WCAG AA（厨房/收银台灯光暗）
```

## TXTouch 组件库

### 基础组件

#### TXButton
```tsx
type TXButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost';
type TXButtonSize = 'normal' | 'large' | 'fullwidth';

interface TXButtonProps {
  variant?: TXButtonVariant;  // 默认 'primary'
  size?: TXButtonSize;        // normal=56px高, large=72px高, fullwidth=56px宽100%
  icon?: React.ReactNode;
  badge?: number;             // 右上角数字角标
  disabled?: boolean;
  loading?: boolean;
  children: React.ReactNode;
  onPress: () => void;
}

// 触控反馈：按下 scale(0.97) + 轻微变暗, 200ms transition
// 禁用：opacity 0.4, pointer-events none
```

#### TXCard
```tsx
interface TXCardProps {
  selected?: boolean;         // 选中态边框变主色
  status?: 'normal' | 'warning' | 'danger'; // 状态色（左侧色条）
  onPress?: () => void;
  children: React.ReactNode;
}
// 圆角12px, 阴影轻微, 选中态border 2px #FF6B35
```

#### TXNumpad
```tsx
// 收银场景的数字键盘
interface TXNumpadProps {
  value: string;
  onChange: (value: string) => void;
  onConfirm: (value: number) => void;
  allowDecimal?: boolean;     // 是否允许小数点
  maxValue?: number;
}
// 按钮尺寸 72×56px, 确认按钮双倍高度, 数字字体 32px
```

#### TXSelector
```tsx
// 替代Ant Design的Select组件
// 展开为全屏/半屏弹层，大按钮选择，不是下拉菜单
interface TXSelectorProps {
  title: string;
  options: { label: string; value: string; icon?: ReactNode }[];
  value: string | string[];
  multiple?: boolean;
  onSelect: (value: string | string[]) => void;
}
// 弹层从底部滑出，选项高度56px，可滚动，顶部搜索栏
```

#### TXScrollList
```tsx
// 触控优化的可滚动列表
interface TXScrollListProps<T> {
  data: T[];
  renderItem: (item: T, index: number) => ReactNode;
  keyExtractor: (item: T) => string;
  onEndReached?: () => void;  // 触底加载更多
}
// 惯性滚动 + 回弹效果 + 触控优化的滚动条
```

### 业务组件

#### TXDishCard
```tsx
// 菜品卡片 —— POS点餐网格中的单个菜品
interface TXDishCardProps {
  name: string;
  price: number;
  image?: string;
  tags?: string[];            // 如"招牌""辣""新品"
  soldOut?: boolean;          // 沽清状态
  quantity?: number;          // 已点数量（右上角角标）
  onPress: () => void;
  onLongPress?: () => void;   // 长按看详情/做法选择
}
// 尺寸：网格单元格，最小 120×140px
// 沽清态：灰色遮罩 + "已沽清"文字
// 已点态：右上角橙色数量角标
```

#### TXKDSTicket
```tsx
// KDS出餐工单卡片
interface TXKDSTicketProps {
  orderId: string;
  tableNo: string;
  items: { name: string; qty: number; spec?: string; priority: 'normal' | 'rush' }[];
  createdAt: Date;
  timeLimit: number;          // 分钟
  isVip?: boolean;
  onComplete: () => void;     // 左滑完成
  onRush: () => void;         // 加急
}
// 颜色编码：
//   正常（剩余>50%时间）→ 白底绿色时间
//   即将超时（<50%）    → 白底黄色时间
//   超时               → 红底白字（整张卡片变红）
// VIP标记：右上角金色VIP徽标
// 完成操作：左滑72px触发完成，带触觉反馈
```

#### TXPaymentPanel
```tsx
// 支付面板 —— 收银结算界面
interface TXPaymentPanelProps {
  total: number;
  discount?: number;
  items: OrderItem[];
  onPayByQR: () => void;      // 扫码支付（微信/支付宝）
  onPayByCash: (amount: number) => void;
  onPayByCard: () => void;     // 银联刷卡
  onPayByCredit: () => void;   // 企业挂账
  onCancel: () => void;
}
// 布局：上方金额汇总 + 中间支付方式大按钮 + 下方折扣信息
// 支付方式按钮：72px高，带图标，一行最多2个
```

#### TXAgentAlert
```tsx
// Agent预警条 —— 固定在屏幕顶部，不可关闭
interface TXAgentAlertProps {
  agentName: string;           // 如"折扣守护Agent"
  message: string;
  severity: 'info' | 'warning' | 'critical';
  data?: Record<string, any>;  // 预警数据
  onAction?: () => void;       // 处理操作
  actionLabel?: string;
}
// critical: 红色背景，白色文字，脉冲动画
// warning: 橙色背景
// info: 蓝色背景
// 固定在SafeArea顶部，其他内容下推
// 不可被用户关闭（只能处理或等Agent撤回）
```

## 三个Store终端的布局差异

### Store-POS · 收银端（横屏）

```
┌─────────────────────────────────────────────────────┐
│ [Agent预警条 - 固定顶部]                              │
├──────┬──────────────────────────────┬───────────────┤
│ 分类  │        菜品网格               │   购物车      │
│ 侧栏  │  ┌────┐ ┌────┐ ┌────┐      │   ┌────────┐ │
│      │  │菜品A│ │菜品B│ │菜品C│      │   │订单行1  │ │
│ 海鲜  │  └────┘ └────┘ └────┘      │   │订单行2  │ │
│ 热菜  │  ┌────┐ ┌────┐ ┌────┐      │   │订单行3  │ │
│ 凉菜  │  │菜品D│ │菜品E│ │菜品F│      │   │...      │ │
│ 汤品  │  └────┘ └────┘ └────┘      │   ├────────┤ │
│ 酒水  │                             │   │合计 ¥xxx│ │
│ 套餐  │  [搜索栏 + 语音按钮]         │   │[结算按钮]│ │
├──────┴──────────────────────────────┴───────────────┤
│ [桌台信息] [会员信息] [挂单] [取单]                    │
└─────────────────────────────────────────────────────┘
分屏比例：分类10% + 菜品55% + 购物车35%
```

### Store-KDS · 后厨出餐屏（横屏）

```
┌─────────────────────────────────────────────────────┐
│ [Agent预警条] [当前待出: 12单] [平均出餐: 18分钟]      │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │
│  │ A3桌 VIP  │ │ B5桌     │ │ C2桌     │ │ D1桌   │ │
│  │ 12:03    │ │ 08:45    │ │ 15:22    │ │ 03:11  │ │
│  │ ■红烧肉 ×1│ │ ■蒜蓉虾×2│ │ ■清蒸鱼×1│ │ ■凉菜×3│ │
│  │ ■清蒸鱼 ×1│ │ ■炒青菜×1│ │ ■汤 ×1   │ │       │ │
│  │ ■汤 ×2   │ │          │ │          │ │       │ │
│  │ [超时！]  │ │ [即将超时]│ │ [正常]   │ │[正常] │ │
│  │ ←滑动完成 │ │ ←滑动完成 │ │ ←滑动完成│ │←完成  │ │
│  └──────────┘ └──────────┘ └──────────┘ └────────┘ │
│  → 水平滚动查看更多工单                               │
└─────────────────────────────────────────────────────┘
工单卡片宽度: 240px固定，水平滚动
倒计时字体: 32px粗体
菜品字体: 20px
```

### Store-Crew · 服务员手机端（竖屏PWA）

```
┌──────────────────────┐
│ [Agent预警条]         │
├──────────────────────┤
│                      │
│  我负责的桌台          │
│  ┌──────────────────┐│
│  │ A3桌 · 就餐中     ││
│  │ 4人 · ¥680 · 50分││
│  │ [加菜] [催菜]     ││
│  └──────────────────┘│
│  ┌──────────────────┐│
│  │ B1桌 · 已点餐     ││
│  │ 2人 · ¥320 · 12分││
│  │ [加菜] [催菜]     ││
│  └──────────────────┘│
│                      │
├──────────────────────┤
│ 🏠主页 📋点餐 👤会员 ⚙更多│
└──────────────────────┘
底部TabBar固定，图标+文字 48px高
卡片操作按钮 48×36px
单手拇指可达区域放核心操作
```

## 编码规则

1. **禁止import任何Ant Design组件** —— `import {} from 'antd'` 是违规的
2. **所有可点击元素 ≥ 48×48px** —— Claude必须计算实际渲染尺寸
3. **字体最小 16px** —— 没有例外
4. **禁止 `<select>` / Dropdown / Popover** —— 用TXSelector全屏弹层
5. **禁止hover样式作为唯一反馈** —— 用 `:active` + `transform: scale(0.97)`
6. **禁止复杂表格** —— 用TXScrollList + TXCard替代Table
7. **所有列表支持触控惯性滚动** —— `-webkit-overflow-scrolling: touch`
8. **颜色对比度 ≥ 4.5:1** —— 深色文字在浅色背景上
9. **关键操作二次确认** —— 反结账/删单/退菜用TXConfirm
10. **Agent预警用TXAgentAlert** —— 固定顶部，不可关闭，不可忽略
11. **WebSocket连接Mac mini** —— KDS工单实时推送、秤数据实时推送
12. **离线降级** —— 断网时显示离线模式提示，收银核心功能不中断

## 外设调用

Store终端通过 `window.TXBridge` 调用安卓POS的外设：

```typescript
// 检测当前环境
const isAndroidPOS = () => !!window.TXBridge;
const isIPad = () => !window.TXBridge && /iPad/.test(navigator.userAgent);

// 统一调用入口
const txDevice = {
  async print(payload: PrintPayload) {
    if (isAndroidPOS()) {
      window.TXBridge.print(JSON.stringify(payload));
    } else {
      // iPad/浏览器：HTTP转发到安卓POS
      await fetch(`${getPosMachineUrl()}/api/device/print`, {
        method: 'POST', body: JSON.stringify(payload),
      });
    }
  },
  async openCashBox() {
    if (isAndroidPOS()) window.TXBridge.openCashBox();
    else await fetch(`${getPosMachineUrl()}/api/device/cashbox`, { method: 'POST' });
  },
  onScaleData(cb: (weight: number) => void) {
    // WebSocket连接安卓POS的秤服务
    const ws = new WebSocket(`ws://${getPosMachineUrl()}/ws/scale`);
    ws.onmessage = (e) => cb(JSON.parse(e.data).weight);
    return () => ws.close();
  },
};
```

## 文件组织

```
apps/
  web-pos/src/
    layouts/PosLayout.tsx      # 左右分屏布局
    pages/
      order/                   # 点餐主界面
      checkout/                # 结算界面
      table-select/            # 开台/桌台选择
      pending-orders/          # 挂单/取单
    components/                # POS专用组件
  web-kds/src/
    layouts/KdsLayout.tsx      # 看板水平滚动布局
    pages/
      board/                   # 待出餐看板
      history/                 # 已完成历史
    components/                # KDS专用组件
  web-crew/src/
    layouts/CrewLayout.tsx     # 单列+底部TabBar
    pages/
      tables/                  # 我的桌台
      order/                   # 点菜
      member-scan/             # 扫会员码
      manager-dashboard/       # 店长看板
    components/                # Crew专用组件

packages/tx-touch/src/         # TXTouch组件库（三端共用）
  components/                  # 所有TXTouch组件
  hooks/                       # 触控相关hooks
    useLongPress.ts            # 长按检测
    useSwipe.ts                # 滑动检测
    useHaptic.ts               # 触觉反馈（安卓vibrate API）
  styles/                      # 基础样式
    reset.css                  # 触控优化的CSS reset
    animations.css             # 按压/滑动动画
```
