/**
 * WaterfallChart -- Pure SVG waterfall (bridge) chart.
 *
 * Shows cumulative effect of sequentially introduced positive or negative
 * values. Intermediate subtotals and a final total bar. Ideal for: profit
 * decomposition (revenue -> food-cost -> labor -> ... -> net-profit),
 * month-over-month revenue bridge, P&L waterfall.
 *
 * Pattern: BI-2.1 Complex Charts Component Library
 */
import { useMemo, useState } from 'react';

export interface WaterfallBar {
  label: string;
  value: number;
  isTotal?: boolean;
}

export interface WaterfallChartProps {
  data: WaterfallBar[];
  title?: string;
  width?: number;
  height?: number;
  className?: string;
  darkMode?: boolean;
  unit?: string;
  startLabel?: string;
  endLabel?: string;
}

const COLORS = {
  positive: '#10B981',
  negative: '#EF4444',
  total: '#6B7280',
  start: '#185FA5',
};

function fmtVal(v: number, unit?: string): string {
  const sign = v < 0 ? '-' : '';
  const av = Math.abs(v);
  if (unit === '%') return sign + av.toFixed(1) + '%';
  if (av >= 10000) return sign + (av / 10000).toFixed(1) + '万' + (unit || '');
  return sign + av.toLocaleString() + (unit || '');
}

export const WaterfallChart: React.FC<WaterfallChartProps> = ({
  data, title, width = 600, height = 380, className = '', darkMode = false, unit = '',
}) => {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  const chartData = useMemo(() => {
    if (\!data.length) return null;
    // Compute running total and bar positions
    let runningTotal = 0;
    const bars: {
      label: string; value: number; isTotal?: boolean;
      bottom: number; top: number; color: string;
    }[] = [];
    for (const item of data) {
      const bottom = item.value >= 0 ? runningTotal : runningTotal + item.value;
      const top = item.value >= 0 ? runningTotal + item.value : runningTotal;
      const color = item.isTotal
        ? COLORS.total
        : item.value >= 0 ? COLORS.positive : COLORS.negative;
      bars.push({ ...item, bottom, top, color });
      runningTotal = item.isTotal ? item.value : runningTotal + item.value;
    }
    const allEnds = bars.flatMap((b) => [b.bottom, b.top]);
    const minAll = Math.min(...allEnds, 0);
    const maxAll = Math.max(...allEnds, 1);
    const rng = maxAll - minAll || 1;
    const yMin = minAll - rng * 0.08;
    const yMax = maxAll + rng * 0.08;
    return { bars, yMin, yMax, range: yMax - yMin };
  }, [data]);

  if (\!chartData) {
    return (
      <div className={className} style={{ width: '100%', height, display: 'flex', alignItems: 'center', justifyContent: 'center', color: darkMode ? '#9CA3AF' : '#666' }} role="img" aria-label="Waterfall chart: no data">
        No data
      </div>
    );
  }

  const pad = { top: 24, right: 30, bottom: 56, left: 64 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const { bars, yMin, yMax, range } = chartData;
  const toY = (v: number) => pad.top + plotH - ((v - yMin) / range) * plotH;
  const zeroY = toY(0);
  const textColor = darkMode ? '#D1D5DB' : '#374151';
  const subTextColor = darkMode ? '#9CA3AF' : '#6B7280';
  const gridColor = darkMode ? '#374151' : '#E5E7EB';

  // Y-axis ticks based on nice scale
  const tickCount = 5;
  const tickStep = range / tickCount;
  const yTicks: number[] = [];
  for (let i = 0; i <= tickCount; i++) yTicks.push(yMin + tickStep * i);

  const barGap = 6;
  const barW = Math.max(12, Math.min(40, (plotW - (bars.length - 1) * barGap) / bars.length - barGap));

  return (
    <div className={'relative ' + className} role="img" aria-label={title || 'Waterfall chart'}>
      {title && <h3 className={'text-sm font-medium mb-2 ' + (darkMode ? 'text-gray-300' : 'text-gray-700')}>{title}</h3>}
      <svg viewBox={'0 0 ' + width + ' ' + height} className="w-full h-auto">
        {/* Grid lines */}
        {yTicks.map((tick) => (
          <g key={tick}>
            <line x1={pad.left} y1={toY(tick)} x2={width - pad.right} y2={toY(tick)} stroke={gridColor} strokeWidth={0.5} />
            <text x={pad.left - 8} y={toY(tick) + 4} textAnchor="end" fill={subTextColor} fontSize={10}>{fmtVal(tick, unit)}</text>
          </g>
        ))}
        {/* Zero line */}
        <line x1={pad.left} y1={zeroY} x2={width - pad.right} y2={zeroY}
          stroke={darkMode ? '#4B5563' : '#D1D5DB'} strokeWidth={1} strokeDasharray="4,4" />
        {/* X-axis */}
        <line x1={pad.left} y1={height - pad.bottom + 2} x2={width - pad.right} y2={height - pad.bottom + 2}
          stroke={darkMode ? '#4B5563' : '#D1D5DB'} strokeWidth={1} />

        {/* Bars and connectors */}
        {bars.map((bar, i) => {
          const cx = pad.left + (i + 0.5) * (plotW / bars.length);
          const isHover = hoverIdx === i;
          const topY = toY(bar.top);
          const botY = toY(bar.bottom);
          const barHeight = Math.max(Math.abs(botY - topY), 2);

          return (
            <g key={i} onMouseEnter={() => setHoverIdx(i)} onMouseLeave={() => setHoverIdx(null)} style={{ cursor: 'pointer' }}>
              {/* Connector line to previous bar */}
              {i > 0 && \!bar.isTotal && (
                <line x1={pad.left + (i - 0.5) * (plotW / bars.length)}
                  y1={toY(bars[i - 1].top)} x2={cx} y2={topY}
                  stroke={subTextColor} strokeWidth={1} strokeDasharray="3,3" opacity={0.5} />
              )}
              {/* Bar */}
              <rect x={cx - barW / 2} y={Math.min(topY, botY)} width={barW} height={barHeight}
                rx={2} fill={bar.color} fillOpacity={isHover ? 0.95 : 0.78}
                stroke={bar.color} strokeWidth={isHover ? 2 : 1}
                style={{ transition: 'fill-opacity 0.2s ease' }} />
              {/* Value label */}
              <text x={cx} y={Math.min(topY, botY) - 6}
                textAnchor="middle" fill={isHover ? bar.color : textColor}
                fontSize={isHover ? 12 : 10} fontWeight={isHover ? 600 : 400}>
                {fmtVal(bar.value, unit)}
              </text>
              {/* Category label */}
              <text x={cx} y={height - pad.bottom + 18}
                textAnchor={barW > 20 ? 'middle' : 'start'}
                fill={textColor} fontSize={10}
                transform={barW <= 20 ? 'rotate(-35, ' + cx + ', ' + (height - pad.bottom + 18) + ')' : undefined}>
                {bar.label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
};

export default WaterfallChart;
