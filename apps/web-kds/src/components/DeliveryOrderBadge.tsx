/**
 * DeliveryOrderBadge — KDS 外卖订单平台标识
 *
 * 在 KDS 工单卡片上显示小徽章，标明外卖平台。
 * 色码：GrabFood=绿, foodpanda=粉, ShopeeFood=橙
 * 堂食工单不显示任何徽章。
 */

type DeliveryPlatform = 'grabfood' | 'foodpanda' | 'shopeefood';

interface DeliveryOrderBadgeProps {
  /** 外卖平台标识（仅外卖订单传入） */
  platform?: DeliveryPlatform;
  /** 订单类型：dine-in / delivery */
  orderType?: string;
}

const PLATFORM_STYLES: Record<DeliveryPlatform, { label: string; color: string; bg: string }> = {
  grabfood: { label: 'GrabFood', color: '#00B14F', bg: 'rgba(0,177,79,0.15)' },
  foodpanda: { label: 'foodpanda', color: '#FF6B9D', bg: 'rgba(255,107,157,0.15)' },
  shopeefood: { label: 'ShopeeFood', color: '#EE4D2D', bg: 'rgba(238,77,45,0.15)' },
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
