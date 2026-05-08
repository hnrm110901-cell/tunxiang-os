/**
 * A2UI 协议类型定义 — Google Agent-to-User-Interface v0.8
 *
 * Agent 返回的 JSON UI 声明 -> 白名单组件目录 -> React 组件渲染
 *
 * 参考: Google A2UI Spec v0.8 (Dec 2025)
 * 组件白名单 (20 type, Sprint 3 S3-01 扩展 +6):
 *   - 基础: Card | Text | Button | List | Input | Image | Chart | Badge |
 *           Progress | Table | ActionsBar | Section | Divider | Spinner
 *   - Sprint 3 新增: Form | Map | Heatmap | Timeline | Cascader | Tabs
 */
// ─── A2UI 基础组件类型 ─────────────────────────────────────────────────────────

export type A2UIComponentType =
  | 'card'
  | 'text'
  | 'button'
  | 'list'
  | 'input'
  | 'image'
  | 'chart'
  | 'badge'
  | 'progress'
  | 'table'
  | 'actions'
  | 'section'
  | 'divider'
  | 'spinner'
  // Sprint 3 S3-01 新增 6 种 ───────────────────────
  | 'form'
  | 'map'
  | 'heatmap'
  | 'timeline'
  | 'cascader'
  | 'tabs';

// ─── A2UI 节点定义 ──────────────────────────────────────────────────────────────

/** A2UI 协议中的单个节点 */
export interface A2UINode {
  id: string;
  type: A2UIComponentType;
  props: Record<string, unknown>;
  children?: A2UINode[];
  /** 绑定的 Agent action ID，交互时回调 */
  actionId?: string;
}

/** A2UI 完整声明（Agent 返回的 JSON 根结构） */
export interface A2UIDeclaration {
  version: string;
  surface: A2UINode;
  metadata?: {
    agentId?: string;
    confidence?: number;
    reasoning?: string;
    timestamp?: string;
  };
}

// ─── 组件 Props 类型（给特定组件用）───────────────────────────────────────────────

export interface A2UIButtonProps {
  label: string;
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
  disabled?: boolean;
  icon?: string;
  action?: string;        // action name to dispatch on click
  actionPayload?: Record<string, unknown>;
}

export interface A2UICardProps {
  title?: string;
  subtitle?: string;
  severity?: 'info' | 'warning' | 'critical';
  collapsed?: boolean;
  children?: A2UINode[];
}

export interface A2UIListProps {
  items: A2UIListItem[];
  ordered?: boolean;
}

export interface A2UIListItem {
  id: string;
  title: string;
  subtitle?: string;
  leadingIcon?: string;
  trailingText?: string;
  actionId?: string;
}

export interface A2UITableProps {
  columns: { key: string; title: string; align?: 'left' | 'center' | 'right' }[];
  rows: Record<string, unknown>[];
  pageSize?: number;
}

export interface A2UIProgressProps {
  value: number;
  max: number;
  label?: string;
  color?: 'success' | 'warning' | 'danger' | 'accent';
}

export interface A2UIBadgeProps {
  text: string;
  variant?: 'success' | 'warning' | 'danger' | 'info';
}

export interface A2UIChartProps {
  chartType: 'bar' | 'line' | 'pie' | 'number';
  title?: string;
  data: { label: string; value: number; color?: string }[];
  height?: number;
}

// ─── Sprint 3 S3-01 新增 6 个组件 props ───────────────────────────────────────

/**
 * Form — Agent 引导填表场景（如"创建宴席合同"）
 * 安全约束：fields 类型严格枚举，不接受 raw HTML 输入；submit action 走 actionId 走白名单。
 */
export interface A2UIFormProps {
  fields: Array<{
    key: string;
    label: string;
    type: 'text' | 'number' | 'date' | 'select' | 'textarea';
    required?: boolean;
    placeholder?: string;
    /** select 类型必填 */
    options?: Array<{ value: string; label: string }>;
    /** number 类型可选 */
    min?: number;
    max?: number;
  }>;
  submitLabel?: string;
  /** action ID 提交时回调 */
  submitAction?: string;
}

/**
 * Map — 桌台地图 / 配送范围可视化
 * 安全约束：不接受 raw URL；图片走 storeId 白名单（背景图）；markers 仅渲染坐标。
 */
export interface A2UIMapProps {
  /** 背景图标识符（Agent 不能注入 raw URL，前端通过 storeId 派生） */
  storeId?: string;
  /** 标注点列表 */
  markers: Array<{
    id: string;
    x: number;            // 0-100 百分比
    y: number;
    label: string;
    color?: 'success' | 'warning' | 'danger' | 'info';
    /** 点击触发的 actionId（白名单） */
    actionId?: string;
  }>;
  width?: number;
  height?: number;
}

/**
 * Heatmap — KDS 实时档口热力 / 销售热力
 * 数据值 0-1（Agent 端归一化），前端按梯度映射颜色。
 */
export interface A2UIHeatmapProps {
  /** 二维数据，rows × cols；值范围 0-1（>1 自动 clamp） */
  data: number[][];
  /** 行标签（如"档口 A"） */
  rowLabels: string[];
  /** 列标签（如时段 "10:00"） */
  colLabels: string[];
  /** 颜色梯度 (低值色 → 高值色) */
  gradient?: { low: string; high: string };
  title?: string;
}

/**
 * Timeline — 订单时间线 / 食材生命周期
 */
export interface A2UITimelineProps {
  items: Array<{
    id: string;
    timestamp: string;     // ISO 8601
    title: string;
    description?: string;
    severity?: 'success' | 'warning' | 'danger' | 'info';
  }>;
  /** 仅显示最近 N 条 */
  limit?: number;
}

/**
 * Cascader — 多级菜单选择（菜系→菜→规格）
 * 安全约束：children 节点深度限 5（防递归攻击）；value 全部走白名单字符串。
 */
export interface A2UICascaderProps {
  options: A2UICascaderOption[];
  /** 当前选中路径（值数组） */
  value?: string[];
  /** 选中变化时触发（values=完整路径） */
  changeAction?: string;
  placeholder?: string;
}

export interface A2UICascaderOption {
  value: string;
  label: string;
  /** 子级选项；递归深度上限 5（在 renderer 中 enforce） */
  children?: A2UICascaderOption[];
  /** 叶子节点附加描述 */
  description?: string;
}

/**
 * Tabs — 多视图切换
 * 安全约束：tab 数量上限 12，children 同 A2UI 通用约束。
 */
export interface A2UITabsProps {
  tabs: Array<{
    key: string;
    label: string;
    /** 该 tab 的内容（A2UINode 子树） */
    contentId: string;
    badge?: number;
    disabled?: boolean;
  }>;
  /** 当前激活 tab key */
  activeKey?: string;
  /** 切换 tab 时触发 */
  changeAction?: string;
}

// ─── 回调类型 ──────────────────────────────────────────────────────────────────

/** 当 A2UI 组件触发 action 时的回调 */
export type A2UIActionCallback = (actionId: string, action: string, payload?: Record<string, unknown>) => void;

/** 渲染上下文中可用的额外能力 */
export interface A2UIRenderContext {
  /** 格式化金额（分→元） */
  formatPrice?: (fen: number) => string;
  /** 格式化时间 */
  formatTime?: (iso: string) => string;
  /** 导航到路径 */
  navigate?: (path: string) => void;
}
