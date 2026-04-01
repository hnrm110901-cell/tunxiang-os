/**
 * 路由清单类型定义
 */

/** AI 入口类型 */
export type AiEntryType = 'task_input' | 'alert_card' | 'suggestion' | 'review';

/** 路由节点 */
export interface RouteNode {
  /** 路由路径 */
  path: string;
  /** 页面名称（中文） */
  name: string;
  /** 页面名称（英文，用于 component 命名） */
  nameEn: string;
  /** 所属一级模块 ID (如 A1, B2, C3) */
  moduleId: string;
  /** AI 入口类型（无则不显示 AI 入口） */
  aiEntry?: AiEntryType[];
  /** 是否为 V1 优先上线页面 */
  priority?: boolean;
  /** 子路由 */
  children?: RouteNode[];
  /** 是否隐藏在导航中（详情页等） */
  hideInNav?: boolean;
  /** 页面描述 */
  description?: string;
}

/** 导航菜单项 */
export interface NavItem {
  /** 菜单标识 */
  key: string;
  /** 显示名称 */
  label: string;
  /** 图标名称 */
  icon?: string;
  /** 跳转路径 */
  path?: string;
  /** 子菜单 */
  children?: NavItem[];
}

/** 页面联动规则 */
export interface LinkageRule {
  /** 规则 ID */
  id: string;
  /** 规则描述 */
  description: string;
  /** 触发源路由 */
  from: string;
  /** 目标路由 */
  to: string;
  /** 联动动作 */
  action: 'navigate' | 'open_drawer' | 'highlight' | 'prefill';
  /** 携带参数 */
  params?: string[];
}
