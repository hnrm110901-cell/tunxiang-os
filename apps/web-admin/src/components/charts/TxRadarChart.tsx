/**
 * TxRadarChart -- 纯SVG雷达图
 * 用于员工绩效卡等场景
 * 品牌色 #FF6B2C，深色主题适配
 */

interface Dimension {
  name: string;
  max: number;
}

interface RadarDataset {
  name: string;
  values: number[];
  color?: string;
}

interface Props {
  dimensions: Dimension[];
  datasets: RadarDataset[];
  size?: number;
}

const PALETTE = ['#FF6B2C', '#185FA5', '#0F6E56', '#BA7517'];

export function TxRadarChart({ dimensions, datasets, size = 240 }: Props) {
  if (!dimensions.length || !datasets.length) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: size, color: '#666' }}>
        暂无数据
      </div>
    );
  }

  const cx = size / 2;
  const cy = size / 2;
  const radius = size / 2 - 36;
  const n = dimensions.length;
  const angleStep = (Math.PI * 2) / n;
  const startAngle = -Math.PI / 2; // 从顶部开始

  // 生成多边形顶点
  const levels = [0.25, 0.5, 0.75, 1.0];

  const getPoint = (idx: number, ratio: number) => {
    const angle = startAngle + idx * angleStep;
    return {
      x: cx + Math.cos(angle) * radius * ratio,
      y: cy + Math.sin(angle) * radius * ratio,
    };
  };

  const polyPoints = (ratios: number[]) =>
    ratios.map((r, i) => {
      const p = getPoint(i, r);
      return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
    }).join(' ');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
      <svg width={size} height={size} style={{ display: 'block' }}>
        {/* 网格多边形 */}
        {levels.map((lv) => (
          <polygon
            key={lv}
            points={polyPoints(Array(n).fill(lv))}
            fill="none"
            stroke="#1a2a33"
            strokeWidth={1}
          />
        ))}

        {/* 轴线 */}
        {dimensions.map((_, i) => {
          const p = getPoint(i, 1);
          return (
            <line
              key={i}
              x1={cx}
              y1={cy}
              x2={p.x}
              y2={p.y}
              stroke="#1a2a33"
              strokeWidth={1}
            />
          );
        })}

        {/* 数据多边形 */}
        {datasets.map((ds, di) => {
          const ratios = ds.values.map((v, i) => Math.min(v / (dimensions[i].max || 1), 1));
          const color = ds.color || PALETTE[di % PALETTE.length];
          return (
            <g key={di}>
              <polygon
                points={polyPoints(ratios)}
                fill={color}
                fillOpacity={0.15}
                stroke={color}
                strokeWidth={2}
              />
              {/* 顶点圆点 */}
              {ratios.map((r, i) => {
                const p = getPoint(i, r);
                return (
                  <circle
                    key={i}
                    cx={p.x}
                    cy={p.y}
                    r={3.5}
                    fill={color}
                    stroke="#0B1A20"
                    strokeWidth={1.5}
                  />
                );
              })}
            </g>
          );
        })}

        {/* 维度标签 */}
        {dimensions.map((dim, i) => {
          const p = getPoint(i, 1.18);
          const angle = startAngle + i * angleStep;
          const textAnchor =
            Math.abs(Math.cos(angle)) < 0.1
              ? 'middle'
              : Math.cos(angle) > 0
                ? 'start'
                : 'end';
          return (
            <text
              key={i}
              x={p.x}
              y={p.y + 4}
              textAnchor={textAnchor}
              fill="#999"
              fontSize={11}
            >
              {dim.name}
            </text>
          );
        })}
      </svg>

      {/* 图例 */}
      {datasets.length > 1 && (
        <div style={{ display: 'flex', gap: 16, marginTop: 4 }}>
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
