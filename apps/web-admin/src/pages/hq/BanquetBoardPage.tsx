/**
 * 宴会管理看板 -- 总部视角
 * 漏斗图：线索→报价→签约→执行→完成
 * 宴会列表（按状态筛选）| 关键指标卡片
 */
import { useState, useEffect, useMemo } from 'react';
import {
  fetchBanquetFunnel,
  fetchBanquetList,
  fetchBanquetKPIs,
} from '../../api/banquetApi';
import type {
  BanquetFunnelData,
  BanquetFunnelStage,
  BanquetListItem,
  BanquetKPIs,
} from '../../api/banquetApi';

// ---------- 常量 ----------
type Stage = 'all' | 'lead' | 'quote' | 'signed' | 'executing' | 'completed' | 'cancelled';

const STAGE_LABELS: Record<string, string> = {
  all: '全部', lead: '线索', quote: '报价', signed: '签约',
  executing: '执行中', completed: '已完成', cancelled: '已取消',
};

const STAGE_COLORS: Record<string, string> = {
  lead: '#BA7517', quote: '#185FA5', signed: '#FF6B2C',
  executing: '#0F6E56', completed: '#52c41a', cancelled: '#666',
};

const FUNNEL_COLORS = ['#FF6B2C', '#185FA5', '#0F6E56', '#BA7517', '#8B5CF6'];

// ---------- Mock ----------
const MOCK_FUNNEL: BanquetFunnelData = {
  stages: [
    { stage: 'lead', label: '线索', count: 86, conversion_rate: 100 },
    { stage: 'quote', label: '报价', count: 52, conversion_rate: 60.5 },
    { stage: 'signed', label: '签约', count: 34, conversion_rate: 65.4 },
    { stage: 'executing', label: '执行', count: 28, conversion_rate: 82.4 },
    { stage: 'completed', label: '完成', count: 22, conversion_rate: 78.6 },
  ],
  total_leads: 86,
  overall_conversion: 25.6,
};

const MOCK_KPIS: BanquetKPIs = {
  month_banquet_count: 34,
  sign_rate: 0.395,
  avg_per_table_fen: 288000,
  month_revenue_fen: 97920000,
};

const MOCK_LIST: BanquetListItem[] = [
  { contract_id: 'bq001', customer_name: '张先生', customer_phone: '138****1234', banquet_date: '2026-04-05', table_count: 30, total_amount_fen: 8640000, stage: 'signed', store_name: '芙蓉路店', created_at: '2026-03-20', updated_at: '2026-03-25' },
  { contract_id: 'bq002', customer_name: '李女士', customer_phone: '139****5678', banquet_date: '2026-04-12', table_count: 20, total_amount_fen: 5760000, stage: 'executing', store_name: '岳麓店', created_at: '2026-03-15', updated_at: '2026-03-26' },
  { contract_id: 'bq003', customer_name: '王总', customer_phone: '136****9012', banquet_date: '2026-04-18', table_count: 15, total_amount_fen: 4320000, stage: 'quote', store_name: '星沙店', created_at: '2026-03-22', updated_at: '2026-03-27' },
  { contract_id: 'bq004', customer_name: '刘先生', customer_phone: '137****3456', banquet_date: '2026-03-28', table_count: 25, total_amount_fen: 7200000, stage: 'completed', store_name: '芙蓉路店', created_at: '2026-03-10', updated_at: '2026-03-28' },
  { contract_id: 'bq005', customer_name: '陈女士', customer_phone: '135****7890', banquet_date: '2026-04-08', table_count: 18, total_amount_fen: 5184000, stage: 'lead', store_name: '开福店', created_at: '2026-03-26', updated_at: '2026-03-26' },
  { contract_id: 'bq006', customer_name: '赵先生', customer_phone: '133****2345', banquet_date: '2026-04-20', table_count: 12, total_amount_fen: 3456000, stage: 'signed', store_name: '望城店', created_at: '2026-03-18', updated_at: '2026-03-24' },
  { contract_id: 'bq007', customer_name: '周总', customer_phone: '138****6789', banquet_date: '2026-03-25', table_count: 35, total_amount_fen: 10080000, stage: 'completed', store_name: '岳麓店', created_at: '2026-03-05', updated_at: '2026-03-25' },
  { contract_id: 'bq008', customer_name: '吴女士', customer_phone: '136****0123', banquet_date: '2026-04-15', table_count: 10, total_amount_fen: 2880000, stage: 'cancelled', store_name: '河西店', created_at: '2026-03-12', updated_at: '2026-03-23' },
];

// ---------- 工具 ----------
const formatMoney = (fen: number) => `\u00A5${(fen / 100).toLocaleString()}`;

// ---------- 漏斗图组件 ----------
function FunnelChart({ stages }: { stages: BanquetFunnelStage[] }) {
  const maxCount = Math.max(...stages.map((s) => s.count), 1);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {stages.map((s, i) => {
        const widthPct = Math.max(20, (s.count / maxCount) * 100);
        const color = FUNNEL_COLORS[i % FUNNEL_COLORS.length];
        return (
          <div key={s.stage}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
              <span style={{ fontSize: 12, color: '#999', width: 50 }}>{s.label}</span>
              <span style={{ fontSize: 12, fontWeight: 600, color: '#fff' }}>{s.count}</span>
              {i > 0 && (
                <span style={{
                  fontSize: 10, padding: '1px 6px', borderRadius: 4,
                  background: `${color}20`, color,
                }}>
                  {s.conversion_rate.toFixed(1)}%
                </span>
              )}
            </div>
            <div style={{
              width: '100%', display: 'flex', justifyContent: 'center',
            }}>
              <div style={{
                width: `${widthPct}%`, height: 32, borderRadius: 4,
                background: `linear-gradient(90deg, ${color}, ${color}88)`,
                transition: 'width 0.5s ease',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>
                <span style={{ fontSize: 11, fontWeight: 700, color: '#fff' }}>{s.count}</span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------- 主组件 ----------
export function BanquetBoardPage() {
  const [funnel, setFunnel] = useState<BanquetFunnelData>(MOCK_FUNNEL);
  const [kpis, setKpis] = useState<BanquetKPIs>(MOCK_KPIS);
  const [list, setList] = useState<BanquetListItem[]>(MOCK_LIST);
  const [stageFilter, setStageFilter] = useState<Stage>('all');

  // 加载实际数据
  useEffect(() => {
    (async () => {
      try {
        const [funnelRes, kpiRes, listRes] = await Promise.allSettled([
          fetchBanquetFunnel(),
          fetchBanquetKPIs(),
          fetchBanquetList({ stage: stageFilter === 'all' ? undefined : stageFilter }),
        ]);
        if (funnelRes.status === 'fulfilled') setFunnel(funnelRes.value);
        if (kpiRes.status === 'fulfilled') setKpis(kpiRes.value);
        if (listRes.status === 'fulfilled') setList(listRes.value.items);
      } catch {
        // keep mock data
      }
    })();
  }, [stageFilter]);

  const filteredList = useMemo(
    () => stageFilter === 'all' ? list : list.filter((item) => item.stage === stageFilter),
    [list, stageFilter],
  );

  return (
    <div>
      {/* 标题 */}
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ margin: 0 }}>宴会管理看板</h2>
      </div>

      {/* KPI 卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
        {[
          { label: '本月宴会数', value: String(kpis.month_banquet_count), unit: '场', color: '#FF6B2C' },
          { label: '签约率', value: `${(kpis.sign_rate * 100).toFixed(1)}%`, unit: '', color: '#185FA5' },
          { label: '平均桌均价', value: formatMoney(kpis.avg_per_table_fen), unit: '', color: '#0F6E56' },
          { label: '本月总营收', value: formatMoney(kpis.month_revenue_fen), unit: '', color: '#BA7517' },
        ].map((kpi) => (
          <div key={kpi.label} style={{
            background: '#112228', borderRadius: 8, padding: 20,
            borderLeft: `3px solid ${kpi.color}`,
          }}>
            <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>{kpi.label}</div>
            <div style={{ fontSize: 28, fontWeight: 'bold', color: '#fff' }}>
              {kpi.value}
              {kpi.unit && <span style={{ fontSize: 14, color: '#999', marginLeft: 4 }}>{kpi.unit}</span>}
            </div>
          </div>
        ))}
      </div>

      {/* 漏斗 + 列表 */}
      <div style={{ display: 'grid', gridTemplateColumns: '360px 1fr', gap: 16 }}>
        {/* 漏斗图 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>
            销售漏斗
            <span style={{
              fontSize: 11, marginLeft: 8, padding: '2px 8px', borderRadius: 10,
              background: '#FF6B2C20', color: '#FF6B2C', fontWeight: 600,
            }}>
              总转化 {funnel.overall_conversion.toFixed(1)}%
            </span>
          </h3>
          <FunnelChart stages={funnel.stages} />
          <div style={{
            marginTop: 16, padding: 12, borderRadius: 6, background: '#0B1A20',
            fontSize: 12, color: '#999', lineHeight: 1.6,
          }}>
            <div>总线索: <span style={{ color: '#fff', fontWeight: 600 }}>{funnel.total_leads}</span></div>
            <div>最终完成: <span style={{ color: '#fff', fontWeight: 600 }}>
              {funnel.stages.find((s) => s.stage === 'completed')?.count || 0}
            </span></div>
            <div>整体转化率: <span style={{ color: '#FF6B2C', fontWeight: 600 }}>
              {funnel.overall_conversion.toFixed(1)}%
            </span></div>
          </div>
        </div>

        {/* 宴会列表 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          {/* 状态筛选 */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h3 style={{ margin: 0, fontSize: 16 }}>宴会列表</h3>
            <div style={{ display: 'flex', gap: 6 }}>
              {(Object.keys(STAGE_LABELS) as Stage[]).map((s) => (
                <button key={s} onClick={() => setStageFilter(s)} style={{
                  padding: '3px 10px', borderRadius: 4, border: 'none', cursor: 'pointer',
                  fontSize: 11, fontWeight: 600,
                  background: stageFilter === s ? '#FF6B2C' : '#0B1A20',
                  color: stageFilter === s ? '#fff' : '#999',
                }}>
                  {STAGE_LABELS[s]}
                </button>
              ))}
            </div>
          </div>

          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ color: '#999', fontSize: 11, textAlign: 'left' }}>
                <th style={{ padding: '8px 4px' }}>客户</th>
                <th style={{ padding: '8px 4px' }}>宴会日期</th>
                <th style={{ padding: '8px 4px' }}>门店</th>
                <th style={{ padding: '8px 4px', textAlign: 'right' }}>桌数</th>
                <th style={{ padding: '8px 4px', textAlign: 'right' }}>金额</th>
                <th style={{ padding: '8px 4px', textAlign: 'center' }}>阶段</th>
              </tr>
            </thead>
            <tbody>
              {filteredList.length === 0 ? (
                <tr>
                  <td colSpan={6} style={{ padding: 30, textAlign: 'center', color: '#666' }}>暂无数据</td>
                </tr>
              ) : (
                filteredList.map((item) => {
                  const stageColor = STAGE_COLORS[item.stage] || '#666';
                  return (
                    <tr key={item.contract_id} style={{ borderTop: '1px solid #1a2a33' }}>
                      <td style={{ padding: '10px 4px' }}>
                        <div style={{ fontWeight: 600 }}>{item.customer_name}</div>
                        <div style={{ fontSize: 11, color: '#666' }}>{item.customer_phone}</div>
                      </td>
                      <td style={{ padding: '10px 4px', color: '#999' }}>{item.banquet_date}</td>
                      <td style={{ padding: '10px 4px', color: '#999' }}>{item.store_name}</td>
                      <td style={{ padding: '10px 4px', textAlign: 'right' }}>{item.table_count}桌</td>
                      <td style={{ padding: '10px 4px', textAlign: 'right', fontWeight: 600 }}>
                        {formatMoney(item.total_amount_fen)}
                      </td>
                      <td style={{ padding: '10px 4px', textAlign: 'center' }}>
                        <span style={{
                          padding: '2px 10px', borderRadius: 10, fontSize: 11, fontWeight: 600,
                          background: `${stageColor}20`, color: stageColor,
                        }}>
                          {STAGE_LABELS[item.stage] || item.stage}
                        </span>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
