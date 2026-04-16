/**
 * StatusBar -- KPI 统计指标条
 *
 * 跨端共享组件，用于：
 *   - web-kds KitchenBoard 顶部（待制作/制作中/已完成）
 *   - web-reception QueuePage 顶部（大桌等待/小桌等待）
 *   - web-pos TableMapPage 顶部（总/空/用/订）
 *   - web-pos CashierPage 顶部 KPI
 *
 * 支持两种尺寸: 'default' | 'compact'
 */
import styles from './StatusBar.module.css';
import { cn } from '../../utils/cn';

export interface StatusBarItem {
  /** 标签文字，如 "待制作" / "大桌等待" */
  label: string;
  /** 数值 */
  value: number | string;
  /** 可选后缀，如 "组" / "单" */
  suffix?: string;
  /** 数值颜色（CSS color） */
  color?: string;
  /** 可选图标 */
  icon?: React.ReactNode;
}

export interface StatusBarProps {
  items: StatusBarItem[];
  /** 尺寸：default(KDS/大屏) compact(POS/reception) */
  size?: 'default' | 'compact';
  /** 额外 className */
  className?: string;
}

export default function StatusBar({
  items,
  size = 'default',
  className,
}: StatusBarProps) {
  return (
    <div className={cn(styles.bar, size === 'compact' && styles.compact, className)}>
      {items.map((item, i) => (
        <div key={i} className={styles.item}>
          {item.icon && <span className={styles.icon}>{item.icon}</span>}
          <span className={styles.label}>{item.label}</span>
          <span
            className={styles.value}
            style={item.color ? { color: item.color } : undefined}
          >
            {item.value}
          </span>
          {item.suffix && <span className={styles.suffix}>{item.suffix}</span>}
        </div>
      ))}
    </div>
  );
}
