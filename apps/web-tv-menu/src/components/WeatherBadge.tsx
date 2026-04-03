import { type CSSProperties } from 'react';

type WeatherType = 'hot' | 'cold' | 'rainy' | 'normal';

interface WeatherBadgeProps {
  weather: WeatherType;
  label?: string;
}

const weatherConfig: Record<WeatherType, { icon: string; text: string; bg: string; color: string }> = {
  hot: {
    icon: '🔥',
    text: '天热推荐',
    bg: 'rgba(255, 68, 68, 0.85)',
    color: '#FFD0D0',
  },
  cold: {
    icon: '❄️',
    text: '暖身推荐',
    bg: 'rgba(24, 95, 165, 0.85)',
    color: '#C0DFFF',
  },
  rainy: {
    icon: '🌧️',
    text: '雨天暖心',
    bg: 'rgba(100, 130, 160, 0.85)',
    color: '#D8E8F8',
  },
  normal: {
    icon: '👨‍🍳',
    text: '主厨推荐',
    bg: 'rgba(255, 107, 44, 0.85)',
    color: '#FFD4B8',
  },
};

export default function WeatherBadge({ weather, label }: WeatherBadgeProps) {
  const config = weatherConfig[weather];

  const style: CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    fontSize: 14,
    fontWeight: 600,
    padding: '6px 12px',
    borderRadius: 8,
    background: config.bg,
    color: config.color,
    backdropFilter: 'blur(4px)',
    whiteSpace: 'nowrap',
  };

  return (
    <span style={style}>
      <span>{config.icon}</span>
      <span>{label || config.text}</span>
    </span>
  );
}
