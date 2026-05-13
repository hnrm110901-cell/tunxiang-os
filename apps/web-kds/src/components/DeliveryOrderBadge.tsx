/**
 * DeliveryOrderBadge — KDS 外卖订单平台标识
 *
 * 在 KDS 工单卡片上显示小徽章，标明外卖平台。
 * 堂食工单不显示任何徽章。
 */

interface DeliveryOrderBadgeProps {
  /** 外卖平台标识（仅外卖订单传入） */
  platform?: string;
  /** 订单类型：dine-in / delivery */
  orderType?: string;
}

const PLATFORM_STYLES: Record<string, { label: string; color: string; bg: string }> = {
  meituan: { label: '美团', color: '#FF6600', bg: 'rgba(255,102,0,0.15)' },
  eleme: { label: '饿了么', color: '#0EA5E9', bg: 'rgba(14,165,233,0.15)' },
  douyin: { label: '抖音', color: '#1C1C1E', bg: 'rgba(28,28,30,0.10)' },
};

export function DeliveryOrderBadge({ platform, orderType }: DeliveryOrderBadgeProps) {
  // 非外卖订单不显示
  if (!platform || orderType === 'dine-in') return null;

  const style = PLATFORM_STYLES[platform];
  if (!style) return null;

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '1px 8px',
        borderRadius: 4,
        background: style.bg,
        color: style.color,
        fontSize: 11,
        fontWeight: 700,
        border: `1px solid ${style.color}`,
        lineHeight: 1.4,
        whiteSpace: 'nowrap',
      }}
    >
      {style.label}
    </span>
  );
}

export default DeliveryOrderBadge;
