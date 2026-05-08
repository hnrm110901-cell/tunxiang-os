/**
 * A2UI 协议类型定义 — Google Agent-to-User-Interface v0.8
 *
 * Agent 返回的 JSON UI 声明 -> 白名单组件目录 -> React 组件渲染
 *
 * 参考: Google A2UI Spec v0.8 (Dec 2025)
 * 组件白名单: Card | Text | Button | List | Input | Image | Chart | Badge |
 *             Progress | Table | ActionsBar | Section | Divider | Spinner
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
  | 'spinner';

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
