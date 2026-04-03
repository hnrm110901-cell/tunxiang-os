/**
 * TxLineChart -- 纯SVG折线/面积图
 * 品牌色 #FF6B2C，深色主题适配，响应式宽度
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
  showArea?: boolean;
  unit?: string; // '元' | '%' | '单' 等
}

// ─── 默认色板（品牌色为首） ───

const PALETTE = ['#FF6B2C', '#185FA5', '#0F6E56', '#BA7517', '#A32D2D', '#8B5CF6'];

// ─── 工具函数 ───

function niceStep(range: number, targetTicks: number): number {
  const rough = range / targetTicks;
  const mag = Math.pow(10, Math.floor(Math.log10(rough)));
  const normalized = rough / mag;
  let nice: number;
  if (normalized <= 1.5) nice = 1;
  else if (normalized <= 3.5) nice = 2;
  else if (normalized <= 7.5) nice = 5;
  else nice = 10;
  return nice * mag;
}

function formatValue(v: number, unit?: string): string {
  if (unit === '%') return `${v.toFixed(1)}%`;
  if (v >= 10000) return `${(v / 10000).toFixed(1)}万${unit || ''}`;
  return `${v.toLocaleString()}${unit || ''}`;
}

// ─── 组件 ───

export function TxLineChart({ data, height = 240, showArea = false, unit = '' }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(600);
  const [tooltip, setTooltip] = useState<{
    x: number;
    y: number;
    label: string;
    values: { name: string; value: number; color: string }[];
  } | null>(null);

  // 响应式宽度
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

  // 悬浮处理 -- hook必须在条件分支之前
  const handleMouseMove = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      if (!labels.length || !datasets.length) return;

      const pad = { top: 20, right: 20, bottom: 36, left: 56 };
      const plotW = width - pad.left - pad.right;
      const xStep = labels.length > 1 ? plotW / (labels.length - 1) : plotW / 2;
      const toXLocal = (i: number) => pad.left + i * xStep;

      const allVals = datasets.flatMap((d) => d.values);
      const rawMin = Math.min(...allVals);
      const rawMax = Math.max(...allVals);
      const range = rawMax - rawMin || 1;
      const step = niceStep(range, 4);
      const yMin = Math.floor(rawMin / step) * step;

      const svg = e.currentTarget;
      const rect = svg.getBoundingClientRect();
      const mx = e.clientX - rect.left;

      let closestIdx = 0;
      let closestDist = Infinity;
      for (let i = 0; i < labels.length; i++) {
        const dist = Math.abs(toXLocal(i) - mx);
        if (dist < closestDist) {
          closestDist = dist;
          closestIdx = i;
        }
      }
      if (closestDist < xStep + 10) {
        setTooltip({
          x: toXLocal(closestIdx),
          y: e.clientY - rect.top,
          label: labels[closestIdx],
          values: datasets.map((ds, di) => ({
            name: ds.name,
            value: ds.values[closestIdx],
            color: ds.color || PALETTE[di % PALETTE.length],
          })),
        });
      } else {
        setTooltip(null);
      }
    },
    [labels, datasets, width],
  );

  const handleMouseLeave = useCallback(() => setTooltip(null), []);

  // 空数据判断（hooks已全部声明完毕）
  if (!labels.length || !datasets.length) {
    return (
      <div ref={containerRef} style={{ width: '100%', height, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#666' }}>
        暂无数据
      </div>
    );
  }

  // 边距
  const pad = { top: 20, right: 20, bottom: 36, left: 56 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  // 数据范围
  const allValues = datasets.flatMap((d) => d.values);
  const rawMin = Math.min(...allValues);
  const rawMax = Math.max(...allValues);
  const range = rawMax - rawMin || 1;
  const step = niceStep(range, 4);
  const yMin = Math.floor(rawMin / step) * step;
  const yMax = Math.ceil(rawMax / step) * step + step * 0.1;
  const yRange = yMax - yMin || 1;

  // Y轴刻度
  const yTicks: number[] = [];
  for (let v = yMin; v <= yMax; v += step) {
    yTicks.push(Math.round(v * 1000) / 1000);
  }

  // 坐标转换
  const xStep = labels.length > 1 ? plotW / (labels.length - 1) : plotW / 2;
  const toX = (i: number) => pad.left + i * xStep;
  const toY = (v: number) => pad.top + plotH - ((v - yMin) / yRange) * plotH;

  // 生成路径
  const linePaths = datasets.map((ds) => {
    return ds.values
      .map((v, i) => `${i === 0 ? 'M' : 'L'}${toX(i).toFixed(1)},${toY(v).toFixed(1)}`)
      .join(' ');
  });

  const areaPaths = showArea
    ? datasets.map((ds) => {
        const line = ds.values.map((v, i) => `${toX(i).toFixed(1)},${toY(v).toFixed(1)}`).join(' L');
        const lastX = toX(ds.values.length - 1);
        const firstX = toX(0);
        const baseY = toY(yMin);
        return `M${firstX.toFixed(1)},${toY(ds.values[0]).toFixed(1)} L${line} L${lastX.toFixed(1)},${baseY.toFixed(1)} L${firstX.toFixed(1)},${baseY.toFixed(1)} Z`;
      })
    : [];

  // X轴标签跳步（避免挤在一起）
  const maxLabels = Math.max(1, Math.floor(plotW / 60));
  const labelStep = Math.ceil(labels.length / maxLabels);

  return (
    <div ref={containerRef} style={{ width: '100%', position: 'relative' }}>
      <svg
        width={width}
        height={height}
        style={{ display: 'block' }}
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
      >
        {/* Y轴网格线 + 刻度 */}
        {yTicks.map((v) => (
          <g key={v}>
            <line
              x1={pad.left}
              y1={toY(v)}
              x2={width - pad.right}
              y2={toY(v)}
              stroke="#1a2a33"
              strokeDasharray="4,3"
            />
            <text
              x={pad.left - 8}
              y={toY(v) + 4}
              textAnchor="end"
              fill="#666"
              fontSize={11}
            >
              {formatValue(v, unit)}
            </text>
          </g>
        ))}

        {/* X轴标签 */}
        {labels.map((lbl, i) =>
          i % labelStep === 0 ? (
            <text
              key={i}
              x={toX(i)}
              y={height - 8}
              textAnchor="middle"
              fill="#666"
              fontSize={11}
            >
              {lbl}
            </text>
          ) : null,
        )}

        {/* 面积填充 */}
        {showArea &&
          areaPaths.map((path, di) => (
            <path
              key={`area-${di}`}
              d={path}
              fill={datasets[di].color || PALETTE[di % PALETTE.length]}
              opacity={0.12}
            />
          ))}

        {/* 折线 */}
        {linePaths.map((path, di) => (
          <path
            key={`line-${di}`}
            d={path}
            fill="none"
            stroke={datasets[di].color || PALETTE[di % PALETTE.length]}
            strokeWidth={2}
            strokeLinejoin="round"
          />
        ))}

        {/* 数据点 */}
        {datasets.map((ds, di) =>
          ds.values.map((v, i) => (
            <circle
              key={`dot-${di}-${i}`}
              cx={toX(i)}
              cy={toY(v)}
              r={3}
              fill={ds.color || PALETTE[di % PALETTE.length]}
              stroke="#0B1A20"
              strokeWidth={1.5}
            />
          )),
        )}

        {/* Tooltip竖线 */}
        {tooltip && (
          <line
            x1={tooltip.x}
            y1={pad.top}
            x2={tooltip.x}
            y2={height - pad.bottom}
            stroke="#FF6B2C"
            strokeWidth={1}
            strokeDasharray="4,3"
            opacity={0.5}
          />
        )}
      </svg>

      {/* Tooltip浮层 */}
      {tooltip && (
        <div
          style={{
            position: 'absolute',
            left: Math.min(tooltip.x + 10, width - 160),
            top: Math.max(tooltip.y - 20, 0),
            background: '#1a2a33',
            border: '1px solid #2a3a43',
            borderRadius: 6,
            padding: '8px 12px',
            pointerEvents: 'none',
            zIndex: 10,
            minWidth: 120,
          }}
        >
          <div style={{ fontSize: 11, color: '#999', marginBottom: 4 }}>{tooltip.label}</div>
          {tooltip.values.map((v) => (
            <div
              key={v.name}
              style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, marginBottom: 2 }}
            >
              <span style={{ width: 8, height: 8, borderRadius: 2, background: v.color, flexShrink: 0 }} />
              <span style={{ color: '#ccc' }}>{v.name}</span>
              <span style={{ color: '#fff', fontWeight: 600, marginLeft: 'auto' }}>
                {formatValue(v.value, unit)}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* 图例 */}
      {datasets.length > 1 && (
        <div style={{ display: 'flex', gap: 16, justifyContent: 'center', marginTop: 4 }}>
          {datasets.map((ds, di) => (
            <div key={ds.name} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#999' }}>
              <span style={{ width: 10, height: 3, borderRadius: 1, background: ds.color || PALETTE[di % PALETTE.length] }} />
              {ds.name}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
