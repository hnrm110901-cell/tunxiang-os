/**
 * TxScatterChart -- 纯SVG散点图（四象限）
 * 用于菜品四象限分析（销量 vs 毛利率）
 * 品牌色 #FF6B2C，深色主题适配
 */
import { useRef, useState, useEffect, useCallback } from 'react';

interface DataPoint {
  name: string;
  x: number;
  y: number;
  size?: number; // 气泡大小
  color?: string;
  quadrant?: string; // 象限标签
}

interface Props {
  data: DataPoint[];
  height?: number;
  xLabel?: string;
  yLabel?: string;
  xUnit?: string;
  yUnit?: string;
  showQuadrants?: boolean;
  quadrantLabels?: [string, string, string, string]; // [右上, 左上, 左下, 右下]
}

const QUADRANT_COLORS = ['#0F6E56', '#185FA5', '#A32D2D', '#BA7517']; // 明星, 问号, 瘦狗, 金牛

export function TxScatterChart({
  data,
  height = 400,
  xLabel = 'X',
  yLabel = 'Y',
  xUnit = '',
  yUnit = '',
  showQuadrants = false,
  quadrantLabels = ['明星', '问号', '瘦狗', '金牛'],
}: Props) {
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

  if (!data.length) {
    return (
      <div ref={containerRef} style={{ width: '100%', height, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#666' }}>
        暂无数据
      </div>
    );
  }

  const pad = { top: 24, right: 24, bottom: 44, left: 56 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  const xs = data.map((d) => d.x);
  const ys = data.map((d) => d.y);
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const yMin = Math.min(...ys);
  const yMax = Math.max(...ys);
  const xRange = xMax - xMin || 1;
  const yRange = yMax - yMin || 1;

  // 加一点padding
  const xLo = xMin - xRange * 0.1;
  const xHi = xMax + xRange * 0.1;
  const yLo = yMin - yRange * 0.1;
  const yHi = yMax + yRange * 0.1;
  const xR = xHi - xLo;
  const yR = yHi - yLo;

  const toSvgX = (v: number) => pad.left + ((v - xLo) / xR) * plotW;
  const toSvgY = (v: number) => pad.top + plotH - ((v - yLo) / yR) * plotH;

  // 四象限中线
  const midX = (xMin + xMax) / 2;
  const midY = (yMin + yMax) / 2;

  const getQuadrantColor = (point: DataPoint) => {
    if (!showQuadrants) return point.color || '#FF6B2C';
    const isRight = point.x >= midX;
    const isTop = point.y >= midY;
    if (isRight && isTop) return QUADRANT_COLORS[0]; // 明星
    if (!isRight && isTop) return QUADRANT_COLORS[1]; // 问号
    if (!isRight && !isTop) return QUADRANT_COLORS[2]; // 瘦狗
    return QUADRANT_COLORS[3]; // 金牛
  };

  const handleMove = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      const rect = e.currentTarget.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      let closest = -1;
      let minDist = 30; // 最大感知距离
      data.forEach((d, i) => {
        const dx = toSvgX(d.x) - mx;
        const dy = toSvgY(d.y) - my;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < minDist) {
          minDist = dist;
          closest = i;
        }
      });
      setHoverIdx(closest >= 0 ? closest : null);
    },
    [data],
  );

  return (
    <div ref={containerRef} style={{ width: '100%', position: 'relative' }}>
      <svg
        width={width}
        height={height}
        style={{ display: 'block' }}
        onMouseMove={handleMove}
        onMouseLeave={() => setHoverIdx(null)}
      >
        {/* 四象限背景色 */}
        {showQuadrants && (
          <>
            <rect x={toSvgX(midX)} y={pad.top} width={toSvgX(xHi) - toSvgX(midX)} height={toSvgY(midY) - pad.top} fill={`${QUADRANT_COLORS[0]}08`} />
            <rect x={pad.left} y={pad.top} width={toSvgX(midX) - pad.left} height={toSvgY(midY) - pad.top} fill={`${QUADRANT_COLORS[1]}08`} />
            <rect x={pad.left} y={toSvgY(midY)} width={toSvgX(midX) - pad.left} height={toSvgY(yLo) - toSvgY(midY)} fill={`${QUADRANT_COLORS[2]}08`} />
            <rect x={toSvgX(midX)} y={toSvgY(midY)} width={toSvgX(xHi) - toSvgX(midX)} height={toSvgY(yLo) - toSvgY(midY)} fill={`${QUADRANT_COLORS[3]}08`} />
            {/* 中线 */}
            <line x1={toSvgX(midX)} y1={pad.top} x2={toSvgX(midX)} y2={height - pad.bottom} stroke="#1a2a33" strokeDasharray="6,4" />
            <line x1={pad.left} y1={toSvgY(midY)} x2={width - pad.right} y2={toSvgY(midY)} stroke="#1a2a33" strokeDasharray="6,4" />
            {/* 象限标签 */}
            <text x={toSvgX(midX) + (toSvgX(xHi) - toSvgX(midX)) / 2} y={pad.top + 16} textAnchor="middle" fill="#0F6E56" fontSize={12} opacity={0.6}>{quadrantLabels[0]}</text>
            <text x={pad.left + (toSvgX(midX) - pad.left) / 2} y={pad.top + 16} textAnchor="middle" fill="#185FA5" fontSize={12} opacity={0.6}>{quadrantLabels[1]}</text>
            <text x={pad.left + (toSvgX(midX) - pad.left) / 2} y={height - pad.bottom - 8} textAnchor="middle" fill="#A32D2D" fontSize={12} opacity={0.6}>{quadrantLabels[2]}</text>
            <text x={toSvgX(midX) + (toSvgX(xHi) - toSvgX(midX)) / 2} y={height - pad.bottom - 8} textAnchor="middle" fill="#BA7517" fontSize={12} opacity={0.6}>{quadrantLabels[3]}</text>
          </>
        )}

        {/* 坐标轴 */}
        <line x1={pad.left} y1={height - pad.bottom} x2={width - pad.right} y2={height - pad.bottom} stroke="#1a2a33" />
        <line x1={pad.left} y1={pad.top} x2={pad.left} y2={height - pad.bottom} stroke="#1a2a33" />

        {/* 轴标签 */}
        <text x={width / 2} y={height - 6} textAnchor="middle" fill="#666" fontSize={11}>{xLabel}</text>
        <text x={12} y={height / 2} textAnchor="middle" fill="#666" fontSize={11} transform={`rotate(-90, 12, ${height / 2})`}>{yLabel}</text>

        {/* 散点 */}
        {data.map((point, i) => {
          const px = toSvgX(point.x);
          const py = toSvgY(point.y);
          const r = point.size ? Math.max(5, Math.min(20, Math.sqrt(point.size) * 2)) : 6;
          const color = getQuadrantColor(point);
          const isHover = hoverIdx === i;
          return (
            <g key={i}>
              <circle
                cx={px}
                cy={py}
                r={isHover ? r + 2 : r}
                fill={color}
                fillOpacity={isHover ? 0.9 : 0.7}
                stroke={isHover ? '#fff' : color}
                strokeWidth={isHover ? 2 : 1}
              />
              {/* 标签 */}
              <text
                x={px}
                y={py - r - 4}
                textAnchor="middle"
                fill={isHover ? '#fff' : '#999'}
                fontSize={isHover ? 12 : 10}
                fontWeight={isHover ? 600 : 400}
              >
                {point.name}
              </text>
            </g>
          );
        })}
      </svg>

      {/* Hover详情 */}
      {hoverIdx !== null && data[hoverIdx] && (
        <div
          style={{
            position: 'absolute',
            left: Math.min(toSvgX(data[hoverIdx].x) + 14, width - 180),
            top: Math.max(toSvgY(data[hoverIdx].y) - 30, 0),
            background: '#1a2a33',
            border: '1px solid #2a3a43',
            borderRadius: 6,
            padding: '8px 12px',
            pointerEvents: 'none',
            zIndex: 10,
          }}
        >
          <div style={{ fontSize: 13, fontWeight: 600, color: '#fff', marginBottom: 4 }}>{data[hoverIdx].name}</div>
          <div style={{ fontSize: 11, color: '#999' }}>
            {xLabel}: {data[hoverIdx].x.toLocaleString()}{xUnit}
          </div>
          <div style={{ fontSize: 11, color: '#999' }}>
            {yLabel}: {data[hoverIdx].y.toLocaleString()}{yUnit}
          </div>
        </div>
      )}
    </div>
  );
}
