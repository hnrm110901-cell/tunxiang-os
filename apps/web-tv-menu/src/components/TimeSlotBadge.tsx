import { type CSSProperties } from 'react';

type TimeSlot = 'morning_tea' | 'lunch' | 'dinner' | 'late_night';

interface TimeSlotBadgeProps {
  slot: TimeSlot;
}

const slotConfig: Record<TimeSlot, { label: string; icon: string; bg: string; color: string }> = {
  morning_tea: {
    label: '早茶',
    icon: '🍵',
    bg: 'rgba(15, 110, 86, 0.85)',
    color: '#A8F0D0',
  },
  lunch: {
    label: '午餐',
    icon: '☀️',
    bg: 'rgba(186, 117, 23, 0.85)',
    color: '#FFE0A0',
  },
  dinner: {
    label: '晚餐',
    icon: '🌙',
    bg: 'rgba(255, 107, 44, 0.85)',
    color: '#FFD4B8',
  },
  late_night: {
    label: '宵夜',
    icon: '🌃',
    bg: 'rgba(24, 95, 165, 0.85)',
    color: '#A8C8F0',
  },
};

export default function TimeSlotBadge({ slot }: TimeSlotBadgeProps) {
  const config = slotConfig[slot];

  const style: CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
    fontSize: 14,
    fontWeight: 600,
    padding: '4px 10px',
    borderRadius: 8,
    background: config.bg,
    color: config.color,
    backdropFilter: 'blur(4px)',
    whiteSpace: 'nowrap',
  };

  return (
    <span style={style}>
      <span>{config.icon}</span>
      <span>{config.label}</span>
    </span>
  );
}
