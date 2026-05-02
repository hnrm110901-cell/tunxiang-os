/**
 * HeatmapChart -- Pure SVG 2D heatmap (matrix visualization).
 *
 * Each cell is an SVG rect whose fill color intensity represents value.
 * Ideal for: hour-of-day x category revenue heatmap, date x store
 * table-turnover matrix, day-of-week x dish popularity grid.
 *
 * Pattern: BI-2.1 Complex Charts Component Library
 */
import { useMemo, useState } from 'react';

export interface HeatmapCell {
  x: string;
  y: string;
  value: number;
}

export interface HeatmapChartProps {
  data: HeatmapCell[];
  xLabels: string[];
  yLabels: string[];
  title?: string;
  width?: number;
  height?: number;
  className?: string;
  darkMode?: boolean;
  colorRange?: [string, string];
  unit?: string;
}

function interpolateColor(a: string, b: string, t: number): string {
  const pa = (h: string) => [parseInt(h.slice(1,3),16), parseInt(h.slice(3,5),16), parseInt(h.slice(5,7),16)];
  const [r1,g1,b1] = pa(a); const [r2,g2,b2] = pa(b);
  return 'rgb(' + Math.round(r1+(r2-r1)*t) + ',' + Math.round(g1+(g2-g1)*t) + ',' + Math.round(b1+(b2-b1)*t) + ')';
}

function fmtVal(v: number, u?: string): string {
  if (u === '%') return v.toFixed(1) + '%';
  if (v >= 10000) return (v/10000).toFixed(1) + '万' + (u||'');
  return v.toLocaleString() + (u||'');
}

export const HeatmapChart: React.FC<HeatmapChartProps> = ({
  data, xLabels, yLabels, title, width = 600, height = 380, className = '',
  darkMode = false, colorRange = ['#F3F4F6', '#FF6B2C'], unit = '',
}) => {
  const [hover, setHover] = useState<{ xi: number; yi: number } | null>(null);

  const chartData = useMemo(() => {
    const valMap = new Map<string, number>();
    for (const cell of data) valMap.set(cell.x + '::' + cell.y, cell.value);
    const allVals = data.map((d) => d.value);
    const minVal = Math.min(...allVals, 0);
    const maxVal = Math.max(...allVals, 1);
    return { valMap, minVal, maxVal, range: maxVal - minVal || 1 };
  }, [data]);

  if (\!xLabels.length || \!yLabels.length || \!data.length) {
    return (
      <div className={className} style={{ width: '100%', height, display: 'flex', alignItems: 'center', justifyContent: 'center', color: darkMode ? '#9CA3AF' : '#666' }} role="img" aria-label="Heatmap: no data">
        No data
      </div>
    );
  }

  const pad = { top: 28, right: 20, bottom: 52, left: 72 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const cellW = plotW / xLabels.length;
  const cellH = plotH / yLabels.length;
  const textColor = darkMode ? '#D1D5DB' : '#374151';
  const subTextColor = darkMode ? '#9CA3AF' : '#6B7280';
  const { valMap, minVal, maxVal, range } = chartData;

  const legendW = 120;
  const legendH = 12;
  const legendX = width - pad.right - legendW;
  const legendY = height - 14;

  return (
    <div className={'relative ' + className} role="img" aria-label={title || 'Heatmap chart'}>
      {title && <h3 className={'text-sm font-medium mb-2 ' + (darkMode ? 'text-gray-300' : 'text-gray-700')}>{title}</h3>}
      <svg viewBox={'0 0 ' + width + ' ' + height} className="w-full h-auto">
        {/* Cells */}
        {yLabels.map((yLabel, yi) =>
          xLabels.map((xLabel, xi) => {
            const val = valMap.get(xLabel + '::' + yLabel) ?? 0;
            const t = (val - minVal) / range;
            const fill = interpolateColor(colorRange[0], colorRange[1], t);
            const isHover = hover?.xi === xi && hover?.yi === yi;
            const cx = pad.left + xi * cellW + 1;
            const cy = pad.top + yi * cellH + 1;
            const cw = cellW - 2;
            const ch = cellH - 2;
            return (
              <g key={xi + '-' + yi}>
                <rect x={cx} y={cy} width={cw} height={ch} rx={3}
                  fill={fill} stroke={isHover ? '#FFFFFF' : 'none'} strokeWidth={isHover ? 2 : 0}
                  style={{ transition: 'stroke-width 0.15s ease' }}
                  onMouseEnter={() => setHover({ xi, yi })}
                  onMouseLeave={() => setHover(null)}
                />
                {isHover && (
                  <g>
                    <rect x={cx + cw / 2 - 40} y={cy - 28} width={80} height={22} rx={4}
                      fill={darkMode ? '#1F2937' : '#FFFFFF'} stroke={darkMode ? '#4B5563' : '#E5E7EB'} strokeWidth={1} />
                    <text x={cx + cw / 2} y={cy - 12} textAnchor="middle" fill={textColor} fontSize={11} fontWeight={600}>
                      {fmtVal(val, unit)}
                    </text>
                  </g>
                )}
              </g>
            );
          })
        )}
        {/* Y-axis labels */}
        {yLabels.map((label, yi) => (
          <text key={'y-' + yi} x={pad.left - 8} y={pad.top + yi * cellH + cellH / 2 + 4}
            textAnchor="end" fill={textColor} fontSize={11}>
            {label}
          </text>
        ))}
        {/* X-axis labels */}
        {xLabels.map((label, xi) => (
          <text key={'x-' + xi} x={pad.left + xi * cellW + cellW / 2} y={height - pad.bottom + 18}
            textAnchor="middle" fill={textColor} fontSize={10}>
            {label}
          </text>
        ))}
        {/* Color legend */}
        <defs>
          <linearGradient id="heatmapLegend" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor={colorRange[0]} />
            <stop offset="100%" stopColor={colorRange[1]} />
          </linearGradient>
        </defs>
        <rect x={legendX} y={legendY} width={legendW} height={legendH} rx={4} fill="url(#heatmapLegend)" />
        <text x={legendX - 6} y={legendY + 10} textAnchor="end" fill={subTextColor} fontSize={10}>{fmtVal(minVal, unit)}</text>
        <text x={legendX + legendW + 6} y={legendY + 10} textAnchor="start" fill={subTextColor} fontSize={10}>{fmtVal(maxVal, unit)}</text>
      </svg>
    </div>
  );
};

export default HeatmapChart;
