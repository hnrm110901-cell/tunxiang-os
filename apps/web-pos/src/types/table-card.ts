/**
 * 智能桌台卡片 - 类型定义
 * @module types/table-card
 */

/**
 * 字段告警级别
 */
export type AlertLevel = 'normal' | 'info' | 'warning' | 'critical';

/**
 * 桌台状态枚举
 */
export enum TableStatus {
  Empty = 'empty', // 空台
  Dining = 'dining', // 用餐中
  Reserved = 'reserved', // 已预订
  PendingCheckout = 'pending_checkout', // 待结账
  PendingCleanup = 'pending_cleanup', // 待清台
}

/**
 * 卡片字段数据
 * 表示卡片中的单个数据项
 */
export interface CardField {
  /** 字段唯一标识 */
  key: string;
  /** 字段显示标签 */
  label: string;
  /** 字段值 */
  value: string;
  /** 字段优先级 (0-100, 越高越靠前) */
  priority: number;
  /** 字段告警级别 */
  alert: AlertLevel;
}

/**
 * 桌台布局信息
 * 用于地图视图的平面图定位
 */
export interface TableLayout {
  /** X轴位置 (百分比: 0-100) */
  pos_x: number;
  /** Y轴位置 (百分比: 0-100) */
  pos_y: number;
  /** 宽度 (百分比: 0-100) */
  width: number;
  /** 高度 (百分比: 0-100) */
  height: number;
  /** 旋转角度 (可选, 单位度数) */
  rotation?: number;
  /** 形状: 矩形 or 圆形 */
  shape: 'rect' | 'circle';
}

/**
 * 桌台卡片数据
 * 单个桌台的完整信息
 */
export interface TableCardData {
  /** 桌号 */
  table_no: string;
  /** 区域名称 */
  area: string;
  /** 座位数 */
  seats: number;
  /** 桌台状态 */
  status: TableStatus;
  /** 布局信息 */
  layout: TableLayout;
  /** 卡片显示的字段列表 */
  card_fields: CardField[];
}

/**
 * 桌台汇总统计
 */
export interface TableSummary {
  /** 空台数 */
  empty: number;
  /** 用餐中 */
  dining: number;
  /** 已预订 */
  reserved: number;
  /** 待结账 */
  pending_checkout: number;
  /** 待清台 */
  pending_cleanup: number;
}

/**
 * 获取表格列表的响应数据
 */
export interface TableListResponse {
  /** 是否成功 */
  ok: boolean;
  /** 响应数据 */
  data: {
    /** 汇总统计 */
    summary: TableSummary;
    /** 当前用餐时段 (breakfast|lunch|dinner|late_night) */
    meal_period: string;
    /** 桌台列表 */
    tables: TableCardData[];
  };
}

/**
 * 视图模式类型
 */
export type ViewMode = 'card' | 'list' | 'map';

/**
 * 桌台点击追踪请求
 */
export interface ClickTrackPayload {
  /** 门店ID */
  store_id: string;
  /** 桌号 */
  table_no: string;
  /** 字段键值 */
  field_key: string;
  /** 字段标签 */
  field_label: string;
  /** 点击时间戳 */
  timestamp: number;
}

/**
 * 字段点击追踪响应
 */
export interface ClickTrackResponse {
  /** 是否成功 */
  ok: boolean;
  /** 响应消息 */
  message?: string;
}
