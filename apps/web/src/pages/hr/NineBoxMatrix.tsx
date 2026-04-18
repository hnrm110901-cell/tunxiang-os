/**
 * 九宫格人才盘点矩阵
 * 3×3 grid，业绩(x) × 潜力(y)
 * - 左下(cell=1) = 低绩低潜(观察清退)
 * - 右上(cell=9) = 明星(接班人)
 */
import { useEffect, useMemo, useState } from 'react';
import { apiClient, handleApiError } from '../../services/api';

type CellEmp = {
  id: string;
  name: string;
  position?: string;
  performance: number;
  potential: number;
  assessment_date: string;
};

type CellData = { label: string; count: number; employees: CellEmp[] };
type Matrix = Record<string, CellData>;

const CELL_ORDER = [3, 6, 9, 2, 5, 8, 1, 4, 7]; // 渲染顺序: 上到下(潜力高→低), 左到右(绩效低→高)
const CELL_COLORS: Record<number, string> = {
  1: '#fde2e2', 2: '#fff3cd', 3: '#fff3cd',
  4: '#fff3cd', 5: '#fff3cd', 6: '#d4edda',
  7: '#fff3cd', 8: '#d4edda', 9: '#c3e6cb',
};

export default function NineBoxMatrix() {
  const [storeId, setStoreId] = useState('S001');
  const [matrix, setMatrix] = useState<Matrix>({});
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<CellEmp | null>(null);
  const [error, setError] = useState<string>('');

  const load = async (sid: string) => {
    setLoading(true);
    setError('');
    try {
      const resp = await apiClient.get(`/api/v1/hr/talent/nine-box/${sid}`);
      setMatrix((resp as any)?.matrix || {});
    } catch (e: any) {
      setError(handleApiError(e, '加载九宫格失败'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(storeId); }, []); // eslint-disable-line

  const totalCount = useMemo(
    () => Object.values(matrix).reduce((s, c) => s + (c?.count || 0), 0),
    [matrix],
  );

  return (
    <div style={{ padding: 24, fontFamily: "'Noto Sans SC', -apple-system, BlinkMacSystemFont, sans-serif" }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>🎯 九宫格人才盘点</h2>
        <span style={{ color: '#666' }}>共 {totalCount} 人</span>
        <input
          value={storeId}
          onChange={(e) => setStoreId(e.target.value)}
          style={{ marginLeft: 'auto', padding: 6, border: '1px solid #ccc', borderRadius: 4 }}
          placeholder="门店 ID"
        />
        <button
          onClick={() => load(storeId)}
          style={{ padding: '6px 16px', background: '#FF6B2C', color: 'white', border: 'none', borderRadius: 4, cursor: 'pointer' }}
        >
          刷新
        </button>
      </div>

      {error && <div style={{ color: '#c00', marginBottom: 8 }}>{error}</div>}
      {loading && <div>加载中...</div>}

      <div style={{ display: 'flex', gap: 8 }}>
        {/* Y 轴标签 */}
        <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between', fontSize: 12, color: '#666', writingMode: 'vertical-rl', transform: 'rotate(180deg)' }}>
          <span>↑ 潜力 高</span>
          <span>潜力 低 ↓</span>
        </div>

        <div style={{ flex: 1 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
            {CELL_ORDER.map((cellKey) => {
              const cell = matrix[cellKey] || { label: '', count: 0, employees: [] };
              return (
                <div
                  key={cellKey}
                  style={{
                    background: CELL_COLORS[cellKey] || '#f5f5f5',
                    borderRadius: 8,
                    padding: 12,
                    minHeight: 160,
                    border: '1px solid #e0e0e0',
                  }}
                >
                  <div style={{ fontSize: 12, color: '#888', marginBottom: 4 }}>cell={cellKey}</div>
                  <div style={{ fontWeight: 600, marginBottom: 6 }}>{cell.label}（{cell.count}人）</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {cell.employees.map((e) => (
                      <button
                        key={e.id}
                        onClick={() => setSelected(e)}
                        style={{
                          padding: '4px 8px',
                          borderRadius: 12,
                          background: 'white',
                          border: '1px solid #ccc',
                          fontSize: 12,
                          cursor: 'pointer',
                        }}
                      >
                        {e.name}
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, fontSize: 12, color: '#666' }}>
            <span>← 业绩 低</span>
            <span>业绩 高 →</span>
          </div>
        </div>
      </div>

      {selected && (
        <div
          onClick={() => setSelected(null)}
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{ background: 'white', borderRadius: 8, padding: 24, minWidth: 360 }}
          >
            <h3 style={{ margin: '0 0 12px' }}>{selected.name}</h3>
            <div>岗位：{selected.position || '—'}</div>
            <div>业绩评分：{selected.performance} / 5</div>
            <div>潜力评分：{selected.potential} / 5</div>
            <div>盘点日期：{selected.assessment_date}</div>
            <button
              onClick={() => setSelected(null)}
              style={{ marginTop: 12, padding: '6px 16px', background: '#FF6B2C', color: 'white', border: 'none', borderRadius: 4, cursor: 'pointer' }}
            >
              关闭
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
