/**
 * BubbleChart -- Pure SVG bubble / scatter chart.
 *
 * Renders circles where position = (x, y), radius proportional to size,
 * and optional label on each bubble. Ideal for: customer-spend (x) x
 * gross-margin (y), bubble-size = revenue, per-dish quadrant analysis.
 *
 * Pattern: BI-2.1 Complex Charts Component Library
 */
import { useMemo, useState } from 'react';

export interface BubblePoint {
  x: number;
  y: number;
  size: number;
  label: string;
  color?: string;
  group?: string;
}

export interface BubbleChartProps {
  data: BubblePoint[];
  title?: string;
  xLabel?: string;
  yLabel?: string;
  width?: number;
  height?: number;
  className?: string;
  darkMode?: boolean;
  xUnit?: string;
  yUnit?: string;
  sizeUnit?: string;
}

const PALETTE = ['#FF6B2C', '#185FA5', '#0F6E56', '#BA7517', '#A32D2D', '#8B5CF6'];

function fmtVal(v: number, u?: string): string {
  if (u === '%') return v.toFixed(1) + '%';
  if (v >= 10000) return (v / 10000).toFixed(1) + '万' + (u || '');
  return v.toLocaleString() + (u || '');
}

function niceTicks(lo: number, hi: number, count: number): number[] {
  const range = hi - lo || 1;
  const rough = range / count;
  const mag = Math.pow(10, Math.floor(Math.log10(rough)));
  const norm = rough / mag;
  let step: number;
  if (norm <= 1.5) step = 1 * mag;
  else if (norm <= 3.5) step = 2 * mag;
  else if (norm <= 7.5) step = 5 * mag;
  else step = 10 * mag;
  const start = Math.floor(lo / step) * step;
  const result: number[] = [];
  for (let v = start; v <= hi + step * 0.5; v += step) result.push(v);
  return result;
}

export const BubbleChart: React.FC<BubbleChartProps> = ({
  data, title, xLabel = 'X', yLabel = 'Y', width = 600, height = 400,
  className = '', darkMode = false, xUnit = '', yUnit = '', sizeUnit = '',
}) => {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  const chartData = useMemo(() => {
    if (\!data.length) return null;
    const xs = data.map((d) => d.x); const ys = data.map((d) => d.y);
    const xMin = Math.min(...xs); const xMax = Math.max(...xs);
    const yMin = Math.min(...ys); const yMax = Math.max(...ys);
    const xRng = xMax - xMin || 1; const yRng = yMax - yMin || 1;
    const xLo = xMin - xRng * 0.08; const xHi = xMax + xRng * 0.08;
    const yLo = yMin - yRng * 0.08; const yHi = yMax + yRng * 0.08;
    const sizes = data.map((d) => d.size);
    const szMin = Math.min(...sizes); const szMax = Math.max(...sizes);
    const szRng = szMax - szMin || 1;
    // Assign colors by group or index
    const groups = [...new Set(data.map((d) => d.group).filter(Boolean))];
    const colored = data.map((d, i) => ({
      ...d,
      color: d.color || (d.group && groups.length
        ? PALETTE[groups.indexOf(d.group\!) % PALETTE.length]
        : PALETTE[i % PALETTE.length]),
    }));
    return { colored, xLo, xHi, yLo, yHi, szMin, szMax, szRng, xRng: xHi - xLo, yRng: yHi - yLo };
  }, [data]);

  if (\!chartData) {
    return (
      <div className={className} style={{ width: '100%', height, display: 'flex', alignItems: 'center', justifyContent: 'center', color: darkMode ? '#9CA3AF' : '#666' }} role="img" aria-label="Bubble chart: no data">
        No data
      </div>
    );
  }

  const pad = { top: 24, right: 24, bottom: 44, left: 56 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const { colored, xLo, xHi, yLo, yHi, szMin, szRng, xRng, yRng } = chartData;
  const toX = (v: number) => pad.left + ((v - xLo) / xRng) * plotW;
  const toY = (v: number) => pad.top + plotH - ((v - yLo) / yRng) * plotH;
  const textColor = darkMode ? '#D1D5DB' : '#374151';
  const subTextColor = darkMode ? '#9CA3AF' : '#6B7280';
  const gridColor = darkMode ? '#374151' : '#E5E7EB';
  const axisColor = darkMode ? '#4B5563' : '#D1D5DB';

  const xTicks = niceTicks(xLo, xHi, 5);
  const yTicks = niceTicks(yLo, yHi, 5);

  // Legend for groups
  const groups = [...new Set(colored.map((d) => d.group).filter(Boolean))];

  return (
    <div className={'relative ' + className} role="img" aria-label={title || 'Bubble chart'}>
      {title && <h3 className={'text-sm font-medium mb-2 ' + (darkMode ? 'text-gray-300' : 'text-gray-700')}>{title}</h3>}
      <svg viewBox={'0 0 ' + width + ' ' + height} className="w-full h-auto">
        {/* Grid lines */}
        {yTicks.map((t) => (
          <g key={'yg-' + t}>
            <line x1={pad.left} y1={toY(t)} x2={width - pad.right} y2={toY(t)} stroke={gridColor} strokeWidth={0.5} />
            <text x={pad.left - 8} y={toY(t) + 4} textAnchor="end" fill={subTextColor} fontSize={10}>{fmtVal(t, yUnit)}</text>
          </g>
        ))}
        {xTicks.map((t) => (
          <g key={'xg-' + t}>
            <line x1={toX(t)} y1={height - pad.bottom} x2={toX(t)} y2={pad.top} stroke={gridColor} strokeWidth={0.5} strokeDasharray="3,3" />
            <text x={toX(t)} y={height - pad.bottom + 16} textAnchor="middle" fill={subTextColor} fontSize={10}>{fmtVal(t, xUnit)}</text>
          </g>
        ))}
        {/* Axes */}
        <line x1={pad.left} y1={height - pad.bottom} x2={width - pad.right} y2={height - pad.bottom} stroke={axisColor} strokeWidth={1} />
        <line x1={pad.left} y1={pad.top} x2={pad.left} y2={height - pad.bottom} stroke={axisColor} strokeWidth={1} />
        {/* Axis labels */}
        <text x={width / 2} y={height - 6} textAnchor="middle" fill={textColor} fontSize={12} fontWeight={500}>{xLabel}</text>
        <text x={14} y={height / 2} textAnchor="middle" fill={textColor} fontSize={12} fontWeight={500} transform={'rotate(-90, 14, ' + height / 2 + ')'}>{yLabel}</text>
        {/* Bubbles */}
        {colored.map((point, i) => {
          const cx = toX(point.x);
          const cy = toY(point.y);
          const radiusScale = (point.size - szMin) / szRng;
          const r = 5 + radiusScale * 22;
          const isHover = hoverIdx === i;
          return (
            <g key={i} onMouseEnter={() => setHoverIdx(i)} onMouseLeave={() => setHoverIdx(null)} style={{ cursor: 'pointer' }}>
              <circle cx={cx} cy={cy} r={isHover ? r + 3 : r}
                fill={point.color} fillOpacity={isHover ? 0.85 : 0.55}
                stroke={point.color} strokeWidth={isHover ? 2 : 0.5}
                style={{ transition: 'fill-opacity 0.2s ease, r 0.2s ease' }} />
              {isHover && (
                <g>
                  <rect x={cx + r + 8} y={cy - 30} width={120} height={52} rx={6}
                    fill={darkMode ? '#1F2937' : '#FFFFFF'} stroke={darkMode ? '#4B5563' : '#E5E7EB'} strokeWidth={1} />
                  <text x={cx + r + 14} y={cy - 14} fill={point.color} fontSize={12} fontWeight={700}>{point.label}</text>
                  <text x={cx + r + 14} y={cy + 2} fill={textColor} fontSize={10}>{xLabel}: {fmtVal(point.x, xUnit)}</text>
                  <text x={cx + r + 14} y={cy + 16} fill={textColor} fontSize={10}>{yLabel}: {fmtVal(point.y, yUnit)} | Size: {fmtVal(point.size, sizeUnit)}</text>
                </g>
              )}
              {/* Label for significant bubbles */}
              {r > 14 && \!isHover && (
                <text x={cx} y={cy + 4} textAnchor="middle" fill="#FFFFFF" fontSize={10} fontWeight={600} style={{ pointerEvents: 'none' }}>
                  {point.label.length > 4 ? point.label.slice(0, 4) : point.label}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      {/* Group legend */}
      {groups.length > 0 && (
        <div style={{ display: 'flex', gap: 16, justifyContent: 'center', marginTop: 4 }}>
          {groups.map((g) => (
            <div key={g} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: subTextColor }}>
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: PALETTE[groups.indexOf(g) % PALETTE.length] }} />
              {g}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default BubbleChart;
