/**
 * TxHeatmap -- 纯CSS热力图网格
 * 时段 x 桌台/档口，颜色深浅表示数值
 * 品牌色 #FF6B2C，深色主题适配
 */
import { Fragment, useState } from 'react';

interface Props {
  data: {
    xLabels: string[]; // 列标签（如时段）
    yLabels: string[]; // 行标签（如桌台/档口）
    values: number[][]; // [row][col]
  };
  height?: number;
  unit?: string;
  colorRange?: [string, string]; // [低, 高] 颜色
}

function interpolateColor(low: string, high: string, t: number): string {
  // 简单16进制插值
  const parse = (hex: string) => {
    const h = hex.replace('#', '');
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
  };
  const [r1, g1, b1] = parse(low);
  const [r2, g2, b2] = parse(high);
  const r = Math.round(r1 + (r2 - r1) * t);
  const g = Math.round(g1 + (g2 - g1) * t);
  const b = Math.round(b1 + (b2 - b1) * t);
  return `rgb(${r},${g},${b})`;
}

export function TxHeatmap({
  data,
  height,
  unit = '',
  colorRange = ['#112228', '#FF6B2C'],
}: Props) {
  const [hover, setHover] = useState<{ row: number; col: number } | null>(null);

  const { xLabels, yLabels, values } = data;
  if (!xLabels.length || !yLabels.length) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: height || 200, color: '#666' }}>
        暂无数据
      </div>
    );
  }

  const allValues = values.flat();
  const minVal = Math.min(...allValues);
  const maxVal = Math.max(...allValues);
  const range = maxVal - minVal || 1;

  const cellH = Math.max(28, Math.min(40, ((height || 300) - 40) / yLabels.length));

  return (
    <div style={{ width: '100%', overflowX: 'auto', position: 'relative' }}>
      <div style={{ display: 'grid', gridTemplateColumns: `80px repeat(${xLabels.length}, 1fr)`, gap: 2 }}>
        {/* 左上角空格 */}
        <div />
        {/* X轴标签 */}
        {xLabels.map((lbl) => (
          <div key={lbl} style={{ fontSize: 11, color: '#666', textAlign: 'center', padding: '4px 0' }}>
            {lbl}
          </div>
        ))}

        {/* 行 */}
        {yLabels.map((yLbl, ri) => (
          <Fragment key={`row-${ri}`}>
            <div style={{ fontSize: 12, color: '#ccc', display: 'flex', alignItems: 'center', paddingRight: 8, justifyContent: 'flex-end' }}>
              {yLbl}
            </div>
            {xLabels.map((_, ci) => {
              const val = values[ri]?.[ci] ?? 0;
              const t = (val - minVal) / range;
              const bg = interpolateColor(colorRange[0], colorRange[1], t);
              const isHover = hover?.row === ri && hover?.col === ci;
              return (
                <div
                  key={`${ri}-${ci}`}
                  onMouseEnter={() => setHover({ row: ri, col: ci })}
                  onMouseLeave={() => setHover(null)}
                  style={{
                    height: cellH,
                    borderRadius: 3,
                    background: bg,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    cursor: 'default',
                    transition: 'transform 0.15s',
                    transform: isHover ? 'scale(1.08)' : 'scale(1)',
                    position: 'relative',
                    zIndex: isHover ? 2 : 1,
                    border: isHover ? '1px solid #FF6B2C' : '1px solid transparent',
                  }}
                >
                  {isHover && (
                    <span style={{ fontSize: 11, color: '#fff', fontWeight: 600 }}>
                      {val.toLocaleString()}{unit}
                    </span>
                  )}
                </div>
              );
            })}
          </Fragment>
        ))}
      </div>

      {/* 色标 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'flex-end', marginTop: 8 }}>
        <span style={{ fontSize: 10, color: '#666' }}>{minVal}{unit}</span>
        <div style={{
          width: 80, height: 8, borderRadius: 4,
          background: `linear-gradient(90deg, ${colorRange[0]}, ${colorRange[1]})`,
        }} />
        <span style={{ fontSize: 10, color: '#666' }}>{maxVal}{unit}</span>
      </div>
    </div>
  );
}
