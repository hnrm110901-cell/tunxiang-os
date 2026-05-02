/**
 * FunnelChart -- Pure SVG horizontal funnel chart.
 *
 * Renders a conversion funnel with trapezoid shapes, showing
 * label, value, and conversion rate from the previous stage.
 * Ideal for sales / ordering / payment funnels in restaurant analytics.
 *
 * Pattern: BI-2.1 Complex Charts Component Library
 */
import { useMemo, useState } from 'react';

// ─── Types ───

export interface FunnelStage {
  stage: string;
  value: number;
  color?: string;
}

export interface FunnelChartProps {
  data: FunnelStage[];
  title?: string;
  width?: number;
  height?: number;
  className?: string;
  darkMode?: boolean;
}

// ─── Palette (brand-first) ───

const PALETTE = ['#FF6B2C', '#185FA5', '#0F6E56', '#BA7517', '#A32D2D', '#8B5CF6'];

// ─── Helpers ───

function formatLarge(v: number): string {
  if (v >= 10000) return `${(v / 10000).toFixed(1)}万`;
  return v.toLocaleString();
}

// ─── Component ───

export const FunnelChart: React.FC<FunnelChartProps> = ({
  data,
  title,
  width = 600,
  height = 400,
  className = '',
  darkMode = false,
}) => {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  const chartData = useMemo(() => {
    if (\!data.length) return null;
    const maxVal = Math.max(...data.map((d) => d.value), 1);

    return data.map((stage, i) => {
      const prevVal = i > 0 ? data[i - 1].value : stage.value;
      const ratio = stage.value / maxVal;
      const conversionRate = i > 0 ? (stage.value / prevVal) * 100 : 100;
      return {
        ...stage,
        ratio,
        conversionRate,
        color: stage.color || PALETTE[i % PALETTE.length],
      };
    });
  }, [data]);

  if (\!chartData || \!chartData.length) {
    return (
      <div
        className={className}
        style={{
          width: '100%',
          height,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: darkMode ? '#9CA3AF' : '#666',
        }}
        role="img"
        aria-label="Funnel chart: no data"
      >
        No data
      </div>
    );
  }

  const padTop = 20;
  const padBottom = 16;
  const funnelHeight = height - padTop - padBottom;
  const stageH = funnelHeight / chartData.length;
  const maxBarW = width * 0.72;
  const leftPad = width * 0.12;
  const textColor = darkMode ? '#D1D5DB' : '#374151';
  const subTextColor = darkMode ? '#9CA3AF' : '#6B7280';

  return (
    <div
      className={`relative ${className}`}
      role="img"
      aria-label={title || 'Funnel chart'}
    >
      {title && (
        <h3
          className={`text-sm font-medium mb-2 ${
            darkMode ? 'text-gray-300' : 'text-gray-700'
          }`}
        >
          {title}
        </h3>
      )}
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full h-auto"
        style={{ overflow: 'visible' }}
      >
        {chartData.map((stage, i) => {
          const barW =
            width * 0.04 + (maxBarW - width * 0.04) * stage.ratio;
          const x = leftPad + (maxBarW - barW) / 2;
          const y = padTop + i * stageH;
          const innerH = Math.max(stageH - 6, 20);
          const innerY = y + (stageH - innerH) / 2;
          const isHover = hoverIdx === i;
          const slope = 10;

          const pathD = [
            `M ${x + slope} ${innerY}`,
            `L ${x + barW - slope} ${innerY}`,
            `C ${x + barW} ${innerY} ${x + barW} ${innerY + innerH} ${x + barW - slope} ${innerY + innerH}`,
            `L ${x + slope} ${innerY + innerH}`,
            `C ${x} ${innerY + innerH} ${x} ${innerY} ${x + slope} ${innerY}`,
            'Z',
          ].join(' ');

          return (
            <g
              key={stage.stage}
              onMouseEnter={() => setHoverIdx(i)}
              onMouseLeave={() => setHoverIdx(null)}
              style={{ cursor: 'pointer' }}
            >
              <path
                d={pathD}
                fill={stage.color}
                fillOpacity={isHover ? 0.92 : 0.72}
                stroke={stage.color}
                strokeWidth={isHover ? 2 : 1}
                style={{
                  transition: 'fill-opacity 0.2s ease, stroke-width 0.2s ease',
                }}
              />
              <text
                x={leftPad - 12}
                y={innerY + innerH / 2 + 4}
                textAnchor="end"
                fill={textColor}
                fontSize={13}
                fontWeight={600}
              >
                {stage.stage}
              </text>
              <text
                x={leftPad + maxBarW / 2}
                y={innerY + innerH / 2 + 4}
                textAnchor="middle"
                fill={isHover ? '#FFFFFF' : textColor}
                fontSize={isHover ? 15 : 14}
                fontWeight={isHover ? 700 : 600}
                style={{ transition: 'font-size 0.2s ease' }}
              >
                {formatLarge(stage.value)}
              </text>
              {i > 0 && (
                <text
                  x={x + barW + 16}
                  y={innerY + innerH / 2 + 4}
                  textAnchor="start"
                  fill={subTextColor}
                  fontSize={11}
                >
                  {stage.conversionRate.toFixed(1)}%
                </text>
              )}
              {i < chartData.length - 1 && (
                <line
                  x1={leftPad + maxBarW / 2}
                  y1={y + stageH}
                  x2={leftPad + maxBarW / 2}
                  y2={y + stageH + 2}
                  stroke={subTextColor}
                  strokeWidth={1}
                  strokeDasharray="3,3"
                  opacity={0.3}
                />
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
};

export default FunnelChart;
