import type { ReactNode } from 'react'

/** 一级菜单项 */
export interface MenuItem {
  /** 唯一 key（路由 path 去掉前导 /） */
  key: string
  /** 中文标题，显示在侧栏 */
  label: string
  /** 编号（01-15），用于排序与展示 */
  no: string
  /** 图标节点（lucide-react 或 antd icon） */
  icon: ReactNode
  /** 路由路径 */
  path: string
  /** 二级菜单（悬浮展示） */
  children?: SubMenuItem[]
}

export interface SubMenuItem {
  key: string
  label: string
  /** 锚点或子路由 */
  path: string
}
