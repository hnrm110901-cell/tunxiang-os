import React from 'react';

interface HealthRingProps {
  score: number;       // 0-100
  size?: number;       // px, default 80
  strokeWidth?: number;
  label?: string;
}

/**
 * 环形健康分指示器。
 * score 0-100；颜色：≥90 绿，≥70 蓝，≥50 橙，else 红
 */
export default function HealthRing({ score, size = 80, strokeWidth = 8, label }: HealthRingProps) {
  const r     = (size - strokeWidth) / 2;
  const circ  = 2 * Math.PI * r;
  const dash  = circ * Math.min(Math.max(score, 0), 100) / 100;

  const color =
    score >= 90 ? 'var(--green)' :
    score >= 70 ? '#007AFF'      :
    score >= 50 ? 'var(--accent)' :
    'var(--red)';

  return (
    <div style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        {/* track */}
        <circle
          cx={size / 2} cy={size / 2} r={r}
          fill="none"
          stroke="var(--surface-hover)"
          strokeWidth={strokeWidth}
        />
        {/* progress */}
        <circle
          cx={size / 2} cy={size / 2} r={r}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeDasharray={`${dash} ${circ - dash}`}
          strokeLinecap="round"
          style={{ transition: 'stroke-dasharray 600ms ease' }}
        />
        {/* center text — rotated back */}
        <text
          x={size / 2} y={size / 2}
          textAnchor="middle"
          dominantBaseline="central"
          fill={color}
          style={{ transform: `rotate(90deg)`, transformOrigin: `${size / 2}px ${size / 2}px`, fontSize: size * 0.22, fontWeight: 700, fontFamily: 'inherit' }}
        >
          {Math.round(score)}
        </text>
      </svg>
      {label && (
        <span style={{ fontSize: 12, color: 'var(--text-secondary)', textAlign: 'center' }}>{label}</span>
      )}
    </div>
  );
}
