/**
 * MemberLevelBadge — 会员等级徽章组件
 * 尺寸：sm(24px) / md(32px) / lg(48px)
 * 深色主题内联CSS，无外部依赖
 */

export interface MemberLevelBadgeProps {
  level: 'bronze' | 'silver' | 'gold' | 'diamond'
  size?: 'sm' | 'md' | 'lg'
}

const LEVEL_CONFIG: Record<
  MemberLevelBadgeProps['level'],
  { label: string; color: string; bg: string; gradient?: string }
> = {
  bronze: {
    label: '铜牌会员',
    color: '#CD7F32',
    bg: '#CD7F3222',
  },
  silver: {
    label: '银牌会员',
    color: '#C0C0C0',
    bg: '#C0C0C022',
  },
  gold: {
    label: '金牌会员',
    color: '#FFD700',
    bg: '#FFD70022',
  },
  diamond: {
    label: '钻石会员',
    color: '#B9F2FF',
    bg: 'linear-gradient(135deg, #B9F2FF22 0%, #7ecfff22 100%)',
    gradient: 'linear-gradient(135deg, #B9F2FF 0%, #7ecfff 100%)',
  },
};

const SIZE_CONFIG: Record<NonNullable<MemberLevelBadgeProps['size']>, {
  height: number;
  fontSize: number;
  padding: string;
  borderRadius: number;
  iconSize: number;
}> = {
  sm: { height: 24, fontSize: 13, padding: '0 7px', borderRadius: 5, iconSize: 12 },
  md: { height: 32, fontSize: 15, padding: '0 10px', borderRadius: 7, iconSize: 14 },
  lg: { height: 48, fontSize: 18, padding: '0 16px', borderRadius: 10, iconSize: 18 },
};

/** 等级图标（小菱形/五角星） */
function LevelIcon({ level, size }: { level: MemberLevelBadgeProps['level']; size: number }) {
  const cfg = LEVEL_CONFIG[level];
  const color = cfg.gradient ?? cfg.color;

  if (level === 'diamond') {
    // 钻石：旋转正方形
    return (
      <span style={{
        display: 'inline-block',
        width: size,
        height: size,
        background: `linear-gradient(135deg, #B9F2FF 0%, #7ecfff 100%)`,
        transform: 'rotate(45deg)',
        borderRadius: 2,
        marginRight: 5,
        flexShrink: 0,
      }} />
    );
  }
  if (level === 'gold') {
    // 金牌：实心五角星
    return (
      <span style={{
        fontSize: size,
        lineHeight: 1,
        marginRight: 4,
        color: cfg.color,
        flexShrink: 0,
        display: 'inline-block',
      }}>★</span>
    );
  }
  // 铜/银：实心圆点
  return (
    <span style={{
      display: 'inline-block',
      width: size * 0.65,
      height: size * 0.65,
      borderRadius: '50%',
      background: color,
      marginRight: 5,
      flexShrink: 0,
    }} />
  );
}

export function MemberLevelBadge({ level, size = 'md' }: MemberLevelBadgeProps) {
  const cfg = LEVEL_CONFIG[level];
  const sz = SIZE_CONFIG[size];
  const isDiamond = level === 'diamond';

  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      height: sz.height,
      padding: sz.padding,
      borderRadius: sz.borderRadius,
      background: cfg.gradient
        ? `linear-gradient(135deg, #B9F2FF15 0%, #7ecfff15 100%)`
        : cfg.bg,
      border: `1px solid ${isDiamond ? '#B9F2FF55' : cfg.color + '55'}`,
      color: isDiamond ? '#B9F2FF' : cfg.color,
      fontSize: sz.fontSize,
      fontWeight: 700,
      whiteSpace: 'nowrap',
      gap: 0,
      lineHeight: 1,
    }}>
      <LevelIcon level={level} size={sz.iconSize} />
      {cfg.label}
    </span>
  );
}
