/**
 * KPIStatCard — 经营指标卡片
 *
 * 用于驾驶舱、工作台等页面的顶部指标展示。
 * 支持：数值 + 同比/环比 + 趋势箭头 + 点击下钻
 *
 * Admin 终端：使用 Ant Design StatisticCard
 */
import { StatisticCard } from '@ant-design/pro-components';
import { Statistic, Tag } from 'antd';
import { ArrowUpOutlined, ArrowDownOutlined, MinusOutlined } from '@ant-design/icons';

export interface KPIStatCardProps {
  title: string;
  value: number;
  /** 值格式：money=¥前缀, percent=%, number=纯数字 */
  format?: 'money' | 'percent' | 'number';
  /** 同比/环比变化率 (0.05 = +5%) */
  changeRate?: number;
  changeLabel?: string;
  /** 目标值（有则显示达成率） */
  target?: number;
  /** 是否异常（Agent标记） */
  isAnomaly?: boolean;
  /** 点击回调（下钻） */
  onClick?: () => void;
}

export function KPIStatCard({
  title,
  value,
  format = 'number',
  changeRate,
  changeLabel = '环比',
  target,
  isAnomaly = false,
  onClick,
}: KPIStatCardProps) {
  const formatValue = () => {
    if (format === 'money') return `¥${value.toLocaleString()}`;
    if (format === 'percent') return `${(value * 100).toFixed(1)}%`;
    return value.toLocaleString();
  };

  const trend = changeRate !== undefined
    ? changeRate > 0 ? 'up' as const : changeRate < 0 ? 'down' as const : undefined
    : undefined;

  const trendColor = trend === 'up' ? '#0F6E56' : trend === 'down' ? '#A32D2D' : '#5F5E5A';
  const trendIcon = trend === 'up' ? <ArrowUpOutlined /> : trend === 'down' ? <ArrowDownOutlined /> : <MinusOutlined />;

  const achievementRate = target ? value / target : undefined;

  return (
    <StatisticCard
      statistic={{
        title: (
          <span>
            {title}
            {isAnomaly && <Tag color="red" style={{ marginLeft: 6, fontSize: 10 }}>异常</Tag>}
          </span>
        ),
        value: formatValue(),
        description: changeRate !== undefined ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
            <Statistic
              value={Math.abs(changeRate * 100)}
              precision={1}
              valueStyle={{ fontSize: 13, color: trendColor }}
              prefix={trendIcon}
              suffix="%"
            />
            <span style={{ fontSize: 11, color: '#B4B2A9' }}>{changeLabel}</span>
            {achievementRate !== undefined && (
              <Tag color={achievementRate >= 1 ? 'green' : 'orange'} style={{ fontSize: 10 }}>
                达成 {(achievementRate * 100).toFixed(0)}%
              </Tag>
            )}
          </div>
        ) : undefined,
      }}
      style={{
        cursor: onClick ? 'pointer' : 'default',
        border: isAnomaly ? '1px solid #A32D2D' : undefined,
        borderRadius: 8,
      }}
      onClick={onClick}
    />
  );
}
