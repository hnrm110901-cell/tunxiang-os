/**
 * TxBarChart -- 纯SVG柱状图
 * 支持垂直/水平方向、多组数据、品牌色渐变
 */
import { useRef, useState, useEffect, useCallback } from 'react';

// ─── 类型 ───

interface Dataset {
  name: string;
  values: number[];
  color?: string;
}

interface Props {
  data: { labels: string[]; datasets: Dataset[] };
  height?: number;
  direction?: 'vertical' | 'horizontal';
  unit?: string;
}

const PALETTE = ['#FF6B2C', '#185FA5', '#0F6E56', '#BA7517', '#A32D2D', '#8B5CF6'];

function formatValue(v: number, unit?: string): string {
  if (unit === '%') return `${v.toFixed(1)}%`;
  if (v >= 10000) return `${(v / 10000).toFixed(1)}万${unit || ''}`;
  return `${v.toLocaleString()}${unit || ''}`;
}

// ─── 组件 ───

export function TxBarChart({ data, height = 240, direction = 'vertical', unit = '' }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(600);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setWidth(entry.contentRect.width);
      }
    });
    observer.observe(el);
    setWidth(el.clientWidth);
    return () => observer.disconnect();
  }, []);

  const { labels, datasets } = data;
  const isVertical = direction === 'vertical';

  // 布局
  const pad = isVertical
    ? { top: 20, right: 20, bottom: 36, left: 56 }
    : { top: 20, right: 60, bottom: 20, left: 80 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  const allValues = datasets.flatMap((d) => d.values);
  const maxVal = Math.max(...allValues, 1);

  const groupCount = labels.length || 1;
  const barCount = datasets.length || 1;
  const groupWidth = plotW / groupCount;

  const handleMove = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      const rect = e.currentTarget.getBoundingClientRect();
      const mx = e.clientX - rect.left - pad.left;
      const idx = Math.floor(mx / groupWidth);
      setHoverIdx(idx >= 0 && idx < groupCount ? idx : null);
    },
    [groupWidth, groupCount, pad.left],
  );

  if (!labels.length || !datasets.length) {
    return (
      <div ref={containerRef} style={{ width: '100%', height, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#666' }}>
        暂无数据
      </div>
    );
  }

  if (isVertical) {
    const barGap = 2;
    const barWidth = Math.max(4, Math.min(32, (groupWidth - (barCount + 1) * barGap) / barCount));
    const groupUsed = barWidth * barCount + barGap * (barCount - 1);
    const groupPad = (groupWidth - groupUsed) / 2;

    // Y轴刻度
    const tickCount = 4;
    const tickStep = maxVal / tickCount;
    const yTicks: number[] = [];
    for (let i = 0; i <= tickCount; i++) yTicks.push(Math.round(tickStep * i));

    return (
      <div ref={containerRef} style={{ width: '100%', position: 'relative' }}>
        <svg
          width={width}
          height={height}
          style={{ display: 'block' }}
          onMouseMove={handleMove}
          onMouseLeave={() => setHoverIdx(null)}
        >
          <defs>
            {datasets.map((ds, di) => {
              const c = ds.color || PALETTE[di % PALETTE.length];
              return (
                <linearGradient key={di} id={`bar-grad-${di}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={c} stopOpacity={0.9} />
                  <stop offset="100%" stopColor={c} stopOpacity={0.5} />
                </linearGradient>
              );
            })}
          </defs>

          {/* Y轴网格 + 刻度 */}
          {yTicks.map((v) => {
            const y = pad.top + plotH - (v / maxVal) * plotH;
            return (
              <g key={v}>
                <line x1={pad.left} y1={y} x2={width - pad.right} y2={y} stroke="#1a2a33" strokeDasharray="4,3" />
                <text x={pad.left - 8} y={y + 4} textAnchor="end" fill="#666" fontSize={11}>
                  {formatValue(v, unit)}
                </text>
              </g>
            );
          })}

          {/* 柱子 */}
          {labels.map((_, gi) =>
            datasets.map((ds, di) => {
              const x = pad.left + gi * groupWidth + groupPad + di * (barWidth + barGap);
              const val = ds.values[gi] || 0;
              const barH = (val / maxVal) * plotH;
              const y = pad.top + plotH - barH;
              const isHover = hoverIdx === gi;
              return (
                <rect
                  key={`${gi}-${di}`}
                  x={x}
                  y={y}
                  width={barWidth}
                  height={Math.max(0, barH)}
                  rx={2}
                  fill={`url(#bar-grad-${di})`}
                  opacity={isHover ? 1 : 0.8}
                />
              );
            }),
          )}

          {/* X轴标签 */}
          {labels.map((lbl, i) => {
            const maxLabels = Math.max(1, Math.floor(plotW / 50));
            const labelStep = Math.ceil(labels.length / maxLabels);
            if (i % labelStep !== 0) return null;
            return (
              <text
                key={i}
                x={pad.left + i * groupWidth + groupWidth / 2}
                y={height - 8}
                textAnchor="middle"
                fill="#666"
                fontSize={11}
              >
                {lbl}
              </text>
            );
          })}

          {/* Hover数值 */}
          {hoverIdx !== null &&
            datasets.map((ds, di) => {
              const x = pad.left + hoverIdx * groupWidth + groupPad + di * (barWidth + barGap) + barWidth / 2;
              const val = ds.values[hoverIdx] || 0;
              const y = pad.top + plotH - (val / maxVal) * plotH - 6;
              return (
                <text key={di} x={x} y={y} textAnchor="middle" fill="#fff" fontSize={10} fontWeight={600}>
                  {formatValue(val, unit)}
                </text>
              );
            })}
        </svg>

        {/* 图例 */}
        {datasets.length > 1 && (
          <div style={{ display: 'flex', gap: 16, justifyContent: 'center', marginTop: 4 }}>
            {datasets.map((ds, di) => (
              <div key={ds.name} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#999' }}>
                <span style={{ width: 10, height: 10, borderRadius: 2, background: ds.color || PALETTE[di % PALETTE.length] }} />
                {ds.name}
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  // ─── 水平方向 ───
  return (
    <div ref={containerRef} style={{ width: '100%' }}>
      <svg width={width} height={height} style={{ display: 'block' }}>
        {labels.map((lbl, i) => {
          const barH = Math.max(12, (plotH / groupCount) * 0.6);
          const gap = plotH / groupCount;
          const y = pad.top + i * gap + (gap - barH) / 2;
          const val = datasets[0]?.values[i] || 0;
          const barW = (val / maxVal) * plotW;
          const c = datasets[0]?.color || PALETTE[0];
          return (
            <g key={i}>
              <text x={pad.left - 8} y={y + barH / 2 + 4} textAnchor="end" fill="#ccc" fontSize={12}>
                {lbl}
              </text>
              <rect x={pad.left} y={y} width={plotW} height={barH} rx={3} fill="#1a2a33" />
              <rect x={pad.left} y={y} width={Math.max(0, barW)} height={barH} rx={3} fill={c} opacity={0.8} />
              <text x={pad.left + barW + 6} y={y + barH / 2 + 4} fill="#ccc" fontSize={11}>
                {formatValue(val, unit)}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
