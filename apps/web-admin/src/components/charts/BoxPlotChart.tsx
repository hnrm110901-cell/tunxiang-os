/**
 * BoxPlotChart -- Pure SVG box plot (box-and-whisker) chart.
 *
 * Shows distribution statistics: min, Q1, median, Q3, max with whiskers,
 * and outliers as individual dots. Ideal for: per-store customer spend
 * distribution, dish preparation time distribution by category.
 *
 * Pattern: BI-2.1 Complex Charts Component Library
 */
import { useMemo, useState } from 'react';

export interface BoxPlotData {
  category: string;
  min: number;
  q1: number;
  median: number;
  q3: number;
  max: number;
  outliers?: number[];
  color?: string;
}

export interface BoxPlotChartProps {
  data: BoxPlotData[];
  title?: string;
  width?: number;
  height?: number;
  className?: string;
  darkMode?: boolean;
  unit?: string;
}

const PALETTE = ['#FF6B2C', '#185FA5', '#0F6E56', '#BA7517', '#A32D2D', '#8B5CF6'];

function fmtVal(v: number, unit?: string): string {
  if (unit === '%') return v.toFixed(1) + '%';
  if (v >= 10000) return (v / 10000).toFixed(1) + '万' + (unit || '');
  return v.toLocaleString() + (unit || '');
}

export const BoxPlotChart: React.FC<BoxPlotChartProps> = ({
  data, title, width = 600, height = 380, className = '', darkMode = false, unit = '',
}) => {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  const chartData = useMemo(() => {
    if (\!data.length) return null;
    const allVals = data.flatMap((d) => [d.min, d.q1, d.median, d.q3, d.max, ...(d.outliers || [])]);
    const globalMin = Math.min(...allVals);
    const globalMax = Math.max(...allVals);
    const range = globalMax - globalMin || 1;
    const yMin = globalMin - range * 0.08;
    const yMax = globalMax + range * 0.08;
    return { yMin, yMax, range: yMax - yMin, boxes: data.map((d, i) => ({ ...d, color: d.color || PALETTE[i % PALETTE.length] })) };
  }, [data]);

  if (\!chartData) {
    return (
      <div className={className} style={{ width: '100%', height, display: 'flex', alignItems: 'center', justifyContent: 'center', color: darkMode ? '#9CA3AF' : '#666' }} role="img" aria-label="Box plot: no data">
        No data
      </div>
    );
  }

  const pad = { top: 24, right: 24, bottom: 52, left: 56 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const { yMin, yMax, range, boxes } = chartData;
  const toY = (v: number) => pad.top + plotH - ((v - yMin) / range) * plotH;
  const textColor = darkMode ? '#D1D5DB' : '#374151';
  const subTextColor = darkMode ? '#9CA3AF' : '#6B7280';
  const gridColor = darkMode ? '#374151' : '#E5E7EB';

  // Y-axis ticks
  const tickCount = 5;
  const tickStep = range / tickCount;
  const yTicks: number[] = [];
  for (let i = 0; i <= tickCount; i++) yTicks.push(yMin + tickStep * i);

  const groupW = plotW / boxes.length;
  const boxW = Math.max(16, Math.min(48, groupW * 0.55));

  return (
    <div className={'relative ' + className} role="img" aria-label={title || 'Box plot chart'}>
      {title && <h3 className={'text-sm font-medium mb-2 ' + (darkMode ? 'text-gray-300' : 'text-gray-700')}>{title}</h3>}
      <svg viewBox={'0 0 ' + width + ' ' + height} className="w-full h-auto">
        {/* Grid lines */}
        {yTicks.map((tick) => (
          <g key={tick}>
            <line x1={pad.left} y1={toY(tick)} x2={width - pad.right} y2={toY(tick)} stroke={gridColor} strokeWidth={0.5} />
            <text x={pad.left - 8} y={toY(tick) + 4} textAnchor="end" fill={subTextColor} fontSize={10}>{fmtVal(tick, unit)}</text>
          </g>
        ))}
        {/* X-axis */}
        <line x1={pad.left} y1={height - pad.bottom + 2} x2={width - pad.right} y2={height - pad.bottom + 2} stroke={darkMode ? '#4B5563' : '#D1D5DB'} strokeWidth={1} />
        {/* Boxes */}
        {boxes.map((box, i) => {
          const cx = pad.left + groupW * (i + 0.5);
          const isHover = hoverIdx === i;
          const whiskerTop = toY(box.max);
          const whiskerBot = toY(box.min);
          const q1Y = toY(box.q1);
          const q3Y = toY(box.q3);
          const medY = toY(box.median);
          const boxH = q1Y - q3Y;

          return (
            <g key={box.category} onMouseEnter={() => setHoverIdx(i)} onMouseLeave={() => setHoverIdx(null)} style={{ cursor: 'pointer' }}>
              {/* Whisker line */}
              <line x1={cx} y1={whiskerTop} x2={cx} y2={whiskerBot}
                stroke={box.color} strokeWidth={1.5} />
              {/* Top whisker cap */}
              <line x1={cx - boxW * 0.3} y1={whiskerTop} x2={cx + boxW * 0.3} y2={whiskerTop}
                stroke={box.color} strokeWidth={1.5} />
              {/* Bottom whisker cap */}
              <line x1={cx - boxW * 0.3} y1={whiskerBot} x2={cx + boxW * 0.3} y2={whiskerBot}
                stroke={box.color} strokeWidth={1.5} />
              {/* Box (Q1 to Q3) */}
              <rect x={cx - boxW / 2} y={Math.min(q1Y, q3Y)} width={boxW} height={Math.abs(boxH)}
                fill={box.color} fillOpacity={isHover ? 0.35 : 0.18}
                stroke={box.color} strokeWidth={isHover ? 2 : 1.5} rx={2}
                style={{ transition: 'fill-opacity 0.2s ease, stroke-width 0.2s ease' }} />
              {/* Median line */}
              <line x1={cx - boxW / 2 + 2} y1={medY} x2={cx + boxW / 2 - 2} y2={medY}
                stroke={box.color} strokeWidth={2} />
              {/* Outliers */}
              {(box.outliers || []).map((val, oi) => (
                <circle key={oi} cx={cx} cy={toY(val)} r={3.5} fill="none" stroke={box.color} strokeWidth={1.5} />
              ))}
              {/* Tooltip on hover */}
              {isHover && (
                <g>
                  <rect x={cx - 64} y={whiskerTop - 76} width={128} height={72} rx={6}
                    fill={darkMode ? '#1F2937' : '#FFFFFF'} stroke={darkMode ? '#4B5563' : '#D1D5DB'} strokeWidth={1} />
                  <text x={cx} y={whiskerTop - 58} textAnchor="middle" fill={box.color} fontSize={12} fontWeight={700}>{box.category}</text>
                  <text x={cx} y={whiskerTop - 40} textAnchor="middle" fill={textColor} fontSize={10}>
                    Max: {fmtVal(box.max, unit)} | Q3: {fmtVal(box.q3, unit)}
                  </text>
                  <text x={cx} y={whiskerTop - 24} textAnchor="middle" fill={textColor} fontSize={10}>
                    Median: {fmtVal(box.median, unit)} | Q1: {fmtVal(box.q1, unit)}
                  </text>
                  <text x={cx} y={whiskerTop - 8} textAnchor="middle" fill={textColor} fontSize={10}>
                    Min: {fmtVal(box.min, unit)}
                  </text>
                </g>
              )}
              {/* Category label */}
              <text x={cx} y={height - pad.bottom + 20} textAnchor="middle" fill={textColor} fontSize={11}>{box.category}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
};

export default BoxPlotChart;
