/**
 * 多门店对比分析 -- 总部端
 * 左侧门店多选 | 右侧维度选择 | 柱状图对比 + 数据表格
 * 支持日/周/月维度切换 | 导出 Excel
 */
import { useState, useMemo, useCallback } from 'react';
import { TxBarChart } from '../../../components/charts';

// ---------- 类型 ----------
type Period = 'day' | 'week' | 'month';
type Dimension = 'revenue' | 'avg_ticket' | 'margin' | 'turnover' | 'complaint';

interface StoreOption {
  store_id: string;
  store_name: string;
}

interface CompareRow {
  store_id: string;
  store_name: string;
  revenue_fen: number;
  avg_ticket_fen: number;
  margin_rate: number;
  turnover_rate: number;
  complaint_rate: number;
}

// ---------- 常量 ----------
const DIMENSIONS: { key: Dimension; label: string; unit: string }[] = [
  { key: 'revenue', label: '营收', unit: '元' },
  { key: 'avg_ticket', label: '客单价', unit: '元' },
  { key: 'margin', label: '毛利率', unit: '%' },
  { key: 'turnover', label: '翻台率', unit: '' },
  { key: 'complaint', label: '客诉率', unit: '%' },
];

const PERIOD_LABELS: Record<Period, string> = { day: '日', week: '周', month: '月' };

// ---------- Mock ----------
const MOCK_STORES: StoreOption[] = [
  { store_id: 's1', store_name: '芙蓉路店' },
  { store_id: 's2', store_name: '岳麓店' },
  { store_id: 's3', store_name: '星沙店' },
  { store_id: 's4', store_name: '河西店' },
  { store_id: 's5', store_name: '开福店' },
  { store_id: 's6', store_name: '望城店' },
  { store_id: 's7', store_name: '雨花店' },
  { store_id: 's8', store_name: '天心店' },
];

const MOCK_COMPARE: CompareRow[] = [
  { store_id: 's1', store_name: '芙蓉路店', revenue_fen: 8560000, avg_ticket_fen: 6700, margin_rate: 50.0, turnover_rate: 3.2, complaint_rate: 0.8 },
  { store_id: 's2', store_name: '岳麓店', revenue_fen: 6400000, avg_ticket_fen: 6300, margin_rate: 48.5, turnover_rate: 2.8, complaint_rate: 1.2 },
  { store_id: 's3', store_name: '星沙店', revenue_fen: 5200000, avg_ticket_fen: 5800, margin_rate: 44.0, turnover_rate: 2.4, complaint_rate: 1.5 },
  { store_id: 's4', store_name: '河西店', revenue_fen: 3800000, avg_ticket_fen: 5200, margin_rate: 38.0, turnover_rate: 1.9, complaint_rate: 2.1 },
  { store_id: 's5', store_name: '开福店', revenue_fen: 3420000, avg_ticket_fen: 5500, margin_rate: 42.0, turnover_rate: 2.1, complaint_rate: 1.8 },
  { store_id: 's6', store_name: '望城店', revenue_fen: 7230000, avg_ticket_fen: 6100, margin_rate: 47.0, turnover_rate: 2.9, complaint_rate: 0.9 },
  { store_id: 's7', store_name: '雨花店', revenue_fen: 4680000, avg_ticket_fen: 5600, margin_rate: 41.7, turnover_rate: 2.3, complaint_rate: 1.6 },
  { store_id: 's8', store_name: '天心店', revenue_fen: 3850000, avg_ticket_fen: 5100, margin_rate: 40.0, turnover_rate: 2.0, complaint_rate: 2.0 },
];

// ---------- 工具 ----------
const marginColor = (m: number) => m >= 45 ? '#0F6E56' : m >= 38 ? '#BA7517' : '#A32D2D';

function getDimValue(row: CompareRow, dim: Dimension): number {
  switch (dim) {
    case 'revenue': return row.revenue_fen / 100;
    case 'avg_ticket': return row.avg_ticket_fen / 100;
    case 'margin': return row.margin_rate;
    case 'turnover': return row.turnover_rate;
    case 'complaint': return row.complaint_rate;
  }
}

function formatDimValue(v: number, dim: Dimension): string {
  if (dim === 'revenue') return `\u00A5${v.toLocaleString()}`;
  if (dim === 'avg_ticket') return `\u00A5${v.toFixed(1)}`;
  if (dim === 'margin' || dim === 'complaint') return `${v.toFixed(1)}%`;
  return v.toFixed(1);
}

// ---------- 组件 ----------
export function MultiStoreComparePage() {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set(['s1', 's2', 's3']));
  const [dimension, setDimension] = useState<Dimension>('revenue');
  const [period, setPeriod] = useState<Period>('day');
  const [exporting, setExporting] = useState(false);

  const toggleStore = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const selectAll = useCallback(() => {
    setSelectedIds(new Set(MOCK_STORES.map((s) => s.store_id)));
  }, []);

  const clearAll = useCallback(() => {
    setSelectedIds(new Set());
  }, []);

  const filteredRows = useMemo(
    () => MOCK_COMPARE.filter((r) => selectedIds.has(r.store_id)),
    [selectedIds],
  );

  const dimMeta = DIMENSIONS.find((d) => d.key === dimension)!;

  // 柱状图数据
  const chartData = useMemo(() => ({
    labels: filteredRows.map((r) => r.store_name),
    datasets: [{ name: dimMeta.label, values: filteredRows.map((r) => getDimValue(r, dimension)) }],
  }), [filteredRows, dimension, dimMeta]);

  // 导出 Excel
  const handleExport = useCallback(async () => {
    setExporting(true);
    try {
      const resp = await fetch('/api/v1/report/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          report_type: 'multi_store_compare',
          store_ids: Array.from(selectedIds),
          dimension,
          period,
        }),
      });
      if (resp.ok) {
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `门店对比_${dimension}_${period}_${new Date().toISOString().slice(0, 10)}.xlsx`;
        a.click();
        URL.revokeObjectURL(url);
      }
    } catch {
      // 导出失败静默处理
    } finally {
      setExporting(false);
    }
  }, [selectedIds, dimension, period]);

  return (
    <div>
      {/* 标题行 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2 style={{ margin: 0 }}>多门店对比分析</h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {/* 周期切换 */}
          {(Object.keys(PERIOD_LABELS) as Period[]).map((p) => (
            <button key={p} onClick={() => setPeriod(p)} style={{
              padding: '4px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
              fontSize: 12, fontWeight: 600,
              background: period === p ? '#FF6B2C' : '#1a2a33',
              color: period === p ? '#fff' : '#999',
            }}>
              {PERIOD_LABELS[p]}
            </button>
          ))}
          <span style={{ width: 1, height: 20, background: '#2a3a43' }} />
          <button onClick={handleExport} disabled={exporting} style={{
            padding: '4px 16px', borderRadius: 6, border: '1px solid #FF6B2C', cursor: 'pointer',
            fontSize: 12, fontWeight: 600, background: 'transparent', color: '#FF6B2C',
            opacity: exporting ? 0.5 : 1,
          }}>
            {exporting ? '导出中...' : '导出 Excel'}
          </button>
        </div>
      </div>

      {/* 筛选区：门店 + 维度 */}
      <div style={{ display: 'grid', gridTemplateColumns: '280px 1fr', gap: 16, marginBottom: 16 }}>
        {/* 左侧：门店多选 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>选择门店</span>
            <div style={{ display: 'flex', gap: 8, fontSize: 11 }}>
              <button onClick={selectAll} style={{ background: 'none', border: 'none', color: '#FF6B2C', cursor: 'pointer', fontSize: 11 }}>全选</button>
              <button onClick={clearAll} style={{ background: 'none', border: 'none', color: '#999', cursor: 'pointer', fontSize: 11 }}>清空</button>
            </div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {MOCK_STORES.map((s) => (
              <label key={s.store_id} style={{
                display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer',
                padding: '6px 8px', borderRadius: 4,
                background: selectedIds.has(s.store_id) ? '#FF6B2C15' : 'transparent',
              }}>
                <input
                  type="checkbox"
                  checked={selectedIds.has(s.store_id)}
                  onChange={() => toggleStore(s.store_id)}
                  style={{ accentColor: '#FF6B2C' }}
                />
                <span style={{ fontSize: 13, color: selectedIds.has(s.store_id) ? '#fff' : '#999' }}>
                  {s.store_name}
                </span>
              </label>
            ))}
          </div>
        </div>

        {/* 右侧：维度选择 + 图表 */}
        <div>
          {/* 维度 Tab */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
            {DIMENSIONS.map((d) => (
              <button key={d.key} onClick={() => setDimension(d.key)} style={{
                padding: '6px 16px', borderRadius: 6, border: 'none', cursor: 'pointer',
                fontSize: 12, fontWeight: 600,
                background: dimension === d.key ? '#FF6B2C' : '#1a2a33',
                color: dimension === d.key ? '#fff' : '#999',
              }}>
                {d.label}
              </button>
            ))}
          </div>

          {/* 柱状图 */}
          <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
            {filteredRows.length === 0 ? (
              <div style={{ textAlign: 'center', padding: 40, color: '#666' }}>请选择至少一个门店</div>
            ) : (
              <TxBarChart data={chartData} height={300} unit={dimMeta.unit} />
            )}
          </div>
        </div>
      </div>

      {/* 数据表格 */}
      <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
        <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>详细数据</h3>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ color: '#999', fontSize: 11, textAlign: 'left' }}>
              <th style={{ padding: '8px 4px' }}>门店</th>
              <th style={{ padding: '8px 4px', textAlign: 'right' }}>营收</th>
              <th style={{ padding: '8px 4px', textAlign: 'right' }}>客单价</th>
              <th style={{ padding: '8px 4px', textAlign: 'right' }}>毛利率</th>
              <th style={{ padding: '8px 4px', textAlign: 'right' }}>翻台率</th>
              <th style={{ padding: '8px 4px', textAlign: 'right' }}>客诉率</th>
            </tr>
          </thead>
          <tbody>
            {filteredRows.map((r) => (
              <tr key={r.store_id} style={{ borderTop: '1px solid #1a2a33' }}>
                <td style={{ padding: '10px 4px', fontWeight: 600 }}>{r.store_name}</td>
                <td style={{ padding: '10px 4px', textAlign: 'right' }}>\u00A5{(r.revenue_fen / 100).toLocaleString()}</td>
                <td style={{ padding: '10px 4px', textAlign: 'right' }}>\u00A5{(r.avg_ticket_fen / 100).toFixed(1)}</td>
                <td style={{ padding: '10px 4px', textAlign: 'right' }}>
                  <span style={{
                    padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 600,
                    background: `${marginColor(r.margin_rate)}20`, color: marginColor(r.margin_rate),
                  }}>{r.margin_rate.toFixed(1)}%</span>
                </td>
                <td style={{ padding: '10px 4px', textAlign: 'right' }}>{r.turnover_rate.toFixed(1)}</td>
                <td style={{ padding: '10px 4px', textAlign: 'right' }}>
                  <span style={{
                    padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 600,
                    background: r.complaint_rate > 1.5 ? '#A32D2D20' : '#0F6E5620',
                    color: r.complaint_rate > 1.5 ? '#A32D2D' : '#0F6E56',
                  }}>{r.complaint_rate.toFixed(1)}%</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
