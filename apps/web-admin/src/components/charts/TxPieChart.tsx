/**
 * TxPieChart -- CSS conic-gradient 饼图/环形图
 * 品牌色 #FF6B2C，深色主题，响应式
 */

interface Segment {
  name: string;
  value: number;
  color?: string;
}

interface Props {
  data: Segment[];
  size?: number;
  donut?: boolean; // 环形图
  unit?: string;
  title?: string; // 中心文字（环形图时显示）
}

const PALETTE = ['#FF6B2C', '#185FA5', '#0F6E56', '#BA7517', '#A32D2D', '#8B5CF6', '#EC4899', '#14B8A6'];

function formatValue(v: number, unit?: string): string {
  if (unit === '%') return `${v.toFixed(1)}%`;
  if (v >= 10000) return `${(v / 10000).toFixed(1)}万${unit || ''}`;
  return `${v.toLocaleString()}${unit || ''}`;
}

export function TxPieChart({ data, size = 160, donut = true, unit = '', title }: Props) {
  if (!data.length) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: size, color: '#666' }}>
        暂无数据
      </div>
    );
  }

  const total = data.reduce((s, d) => s + d.value, 0);
  if (total === 0) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: size, color: '#666' }}>
        暂无数据
      </div>
    );
  }

  // 构建 conic-gradient
  let cumPct = 0;
  const gradientParts: string[] = [];
  data.forEach((seg, i) => {
    const pct = (seg.value / total) * 100;
    const color = seg.color || PALETTE[i % PALETTE.length];
    gradientParts.push(`${color} ${cumPct.toFixed(2)}% ${(cumPct + pct).toFixed(2)}%`);
    cumPct += pct;
  });
  const gradient = `conic-gradient(${gradientParts.join(', ')})`;

  const holeSize = donut ? size * 0.6 : 0;

  return (
    <div style={{ display: 'flex', gap: 20, alignItems: 'center' }}>
      {/* 饼图 */}
      <div
        style={{
          width: size,
          height: size,
          borderRadius: '50%',
          background: gradient,
          position: 'relative',
          flexShrink: 0,
        }}
      >
        {donut && (
          <div
            style={{
              position: 'absolute',
              inset: (size - holeSize) / 2,
              borderRadius: '50%',
              background: '#112228',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexDirection: 'column',
            }}
          >
            {title && <div style={{ fontSize: 11, color: '#999' }}>{title}</div>}
            <div style={{ fontSize: 14, fontWeight: 'bold', color: '#fff' }}>
              {formatValue(total, unit)}
            </div>
          </div>
        )}
      </div>

      {/* 图例 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, flex: 1 }}>
        {data.map((seg, i) => {
          const pct = ((seg.value / total) * 100).toFixed(1);
          const color = seg.color || PALETTE[i % PALETTE.length];
          return (
            <div key={seg.name} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: 2,
                  background: color,
                  flexShrink: 0,
                }}
              />
              <span style={{ fontSize: 12, color: '#ccc', flex: 1 }}>{seg.name}</span>
              <span style={{ fontSize: 12, fontWeight: 600, color: '#fff' }}>
                {formatValue(seg.value, unit)}
              </span>
              <span style={{ fontSize: 11, color: '#999', width: 40, textAlign: 'right' }}>{pct}%</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
