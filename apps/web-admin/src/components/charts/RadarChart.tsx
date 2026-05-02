/**
 * RadarChart -- Pure SVG radar (spider) chart.
 *
 * Multi-dimensional comparison on a circular axis with polygon shapes.
 * Supports multiple series overlay. Ideal for: store health radar
 * (turnover-rate, labor-efficiency, area-efficiency, gross-margin,
 * customer-spend, satisfaction), employee skill radar.
 *
 * Pattern: BI-2.1 Complex Charts Component Library
 */
import { useMemo, useState } from 'react';

export interface RadarDimension {
  dimension: string;
  value: number;
  maxValue: number;
}

export interface RadarSeries {
  name: string;
  data: { dimension: string; value: number }[];
  color?: string;
}

export interface RadarChartProps {
  data: RadarDimension[];
  series?: RadarSeries[];
  title?: string;
  width?: number;
  height?: number;
  className?: string;
  darkMode?: boolean;
}

const PALETTE = ['#FF6B2C', '#185FA5', '#0F6E56', '#BA7517', '#A32D2D', '#8B5CF6'];

export const RadarChart: React.FC<RadarChartProps> = ({
  data, series, title, width = 420, height = 400, className = '', darkMode = false,
}) => {
  const [hoverDim, setHoverDim] = useState<number | null>(null);
  const [hoverSeries, setHoverSeries] = useState<number | null>(null);

  const chartData = useMemo(() => {
    if (\!data.length) return null;
    const n = data.length;
    const cx = width / 2;
    const cy = height / 2;
    const radius = Math.min(cx, cy) - 48;
    const angleStep = (Math.PI * 2) / n;
    const startAngle = -Math.PI / 2; // top

    const getPoint = (idx: number, ratio: number) => {
      const angle = startAngle + idx * angleStep;
      return {
        x: cx + Math.cos(angle) * radius * ratio,
        y: cy + Math.sin(angle) * radius * ratio,
      };
    };

    // Grid levels
    const gridLevels = [0.2, 0.4, 0.6, 0.8, 1.0];

    // Primary data polygon (single dataset mode)
    const primaryRatios = data.map((d) => Math.min(d.value / (d.maxValue || 1), 1));
    const primaryPoints = primaryRatios.map((r, i) => getPoint(i, r));
    const primaryPoly = primaryPoints.map((p) => p.x.toFixed(1) + ',' + p.y.toFixed(1)).join(' ');

    // Series polygons
    const seriesData = (series || []).map((s, si) => {
      const ratios = data.map((dim) => {
        const match = s.data.find((d) => d.dimension === dim.dimension);
        return match ? Math.min(match.value / (dim.maxValue || 1), 1) : 0;
      });
      const points = ratios.map((r, i) => getPoint(i, r));
      const poly = points.map((p) => p.x.toFixed(1) + ',' + p.y.toFixed(1)).join(' ');
      return {
        ...s,
        color: s.color || PALETTE[si % PALETTE.length],
        ratios,
        points,
        poly,
      };
    });

    return { n, cx, cy, radius, angleStep, startAngle, getPoint, gridLevels, primaryRatios, primaryPoints, primaryPoly, seriesData };
  }, [data, series, width, height]);

  if (\!chartData) {
    return (
      <div className={className} style={{ width: '100%', height, display: 'flex', alignItems: 'center', justifyContent: 'center', color: darkMode ? '#9CA3AF' : '#666' }} role="img" aria-label="Radar chart: no data">
        No data
      </div>
    );
  }

  const { n, cx, cy, radius, angleStep, startAngle, getPoint, gridLevels, primaryRatios, primaryPoly, seriesData } = chartData;
  const textColor = darkMode ? '#D1D5DB' : '#374151';
  const subTextColor = darkMode ? '#9CA3AF' : '#6B7280';
  const gridColor = darkMode ? '#374151' : '#E5E7EB';
  const axisColor = darkMode ? '#4B5563' : '#D1D5DB';
  const hasSeries = seriesData.length > 0;

  return (
    <div className={'relative flex flex-col items-center ' + className} role="img" aria-label={title || 'Radar chart'}>
      {title && <h3 className={'text-sm font-medium mb-2 ' + (darkMode ? 'text-gray-300' : 'text-gray-700')}>{title}</h3>}
      <svg viewBox={'0 0 ' + width + ' ' + height} className="w-full h-auto">
        {/* Grid polygons */}
        {gridLevels.map((lv) => (
          <polygon key={lv}
            points={Array(n).fill(0).map((_, i) => { const p = getPoint(i, lv); return p.x.toFixed(1) + ',' + p.y.toFixed(1); }).join(' ')}
            fill="none" stroke={gridColor} strokeWidth={1} />
        ))}
        {/* Axis lines */}
        {data.map((_, i) => {
          const p = getPoint(i, 1);
          return <line key={i} x1={cx} y1={cy} x2={p.x} y2={p.y} stroke={axisColor} strokeWidth={0.5} />;
        })}

        {/* Primary data polygon (single dataset mode) */}
        {\!hasSeries && (
          <g>
            <polygon points={primaryPoly} fill={PALETTE[0]} fillOpacity={0.15} stroke={PALETTE[0]} strokeWidth={2} />
            {primaryRatios.map((r, i) => {
              const p = getPoint(i, r);
              return (
                <g key={i} onMouseEnter={() => setHoverDim(i)} onMouseLeave={() => setHoverDim(null)}>
                  <circle cx={p.x} cy={p.y} r={5} fill={PALETTE[0]} stroke="#FFFFFF" strokeWidth={1.5}
                    style={{ cursor: 'pointer', transition: 'r 0.15s ease' }} />
                  {hoverDim === i && (
                    <g>
                      <rect x={p.x - 32} y={p.y - 30} width={64} height={22} rx={4}
                        fill={darkMode ? '#1F2937' : '#FFFFFF'} stroke={darkMode ? '#4B5563' : '#E5E7EB'} strokeWidth={1} />
                      <text x={p.x} y={p.y - 14} textAnchor="middle" fill={textColor} fontSize={11} fontWeight={600}>
                        {data[i].value.toLocaleString()}
                      </text>
                    </g>
                  )}
                </g>
              );
            })}
          </g>
        )}

        {/* Series overlay polygons */}
        {seriesData.map((s, si) => (
          <g key={si} onMouseEnter={() => setHoverSeries(si)} onMouseLeave={() => setHoverSeries(null)}>
            <polygon points={s.poly}
              fill={s.color} fillOpacity={hoverSeries === si ? 0.25 : 0.1}
              stroke={s.color} strokeWidth={hoverSeries === si ? 2.5 : 1.5}
              style={{ cursor: 'pointer', transition: 'fill-opacity 0.2s ease, stroke-width 0.2s ease' }} />
            {s.points.map((p, i) => (
              <circle key={i} cx={p.x} cy={p.y} r={hoverSeries === si ? 5 : 3.5}
                fill={s.color} stroke="#FFFFFF" strokeWidth={1}
                style={{ transition: 'r 0.15s ease', cursor: 'pointer' }}
                onMouseEnter={() => setHoverDim(i)}
                onMouseLeave={() => setHoverDim(null)} />
            ))}
            {/* Hover tooltip for series values */}
            {hoverSeries === si && hoverDim \!== null && (
              <g>
                <rect x={s.points[hoverDim].x - 36} y={s.points[hoverDim].y - 32} width={72} height={26} rx={4}
                  fill={darkMode ? '#1F2937' : '#FFFFFF'} stroke={s.color} strokeWidth={1} />
                <text x={s.points[hoverDim].x} y={s.points[hoverDim].y - 20} textAnchor="middle" fill={s.color} fontSize={10} fontWeight={600}>{s.name}</text>
                <text x={s.points[hoverDim].x} y={s.points[hoverDim].y - 6} textAnchor="middle" fill={textColor} fontSize={10}>
                  {s.ratios[hoverDim] \!== undefined ? (s.ratios[hoverDim] * data[hoverDim].maxValue).toLocaleString() : ''}
                </text>
              </g>
            )}
          </g>
        ))}

        {/* Dimension labels */}
        {data.map((dim, i) => {
          const p = getPoint(i, 1.22);
          const angle = startAngle + i * angleStep;
          const cosA = Math.cos(angle);
          let anchor: 'start' | 'middle' | 'end' = 'middle';
          if (Math.abs(cosA) > 0.05) anchor = cosA > 0 ? 'start' : 'end';
          return (
            <text key={i} x={p.x} y={p.y + 4} textAnchor={anchor} fill={textColor} fontSize={11} fontWeight={500}>
              {dim.dimension}
            </text>
          );
        })}
      </svg>

      {/* Series legend */}
      {hasSeries && (
        <div style={{ display: 'flex', gap: 16, marginTop: 4, flexWrap: 'wrap', justifyContent: 'center' }}>
          {seriesData.map((s, si) => (
            <div key={si} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: subTextColor }}>
              <span style={{ width: 10, height: 10, borderRadius: 2, background: s.color }} />
              {s.name}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default RadarChart;
