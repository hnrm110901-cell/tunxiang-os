/**
 * 移动端经营总览
 * 路由: /m/dashboard
 * API: tx-analytics :8009
 */
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { MobileLayout } from '../../components/MobileLayout';
import { txFetchData } from '../../api/client';
import { formatPrice } from '@tx-ds/utils';

// ─── 类型 ───

interface MobileDashboardData {
  revenue_fen: number;      // 营业额（分）
  customer_count: number;   // 客流量
  new_members: number;      // 新增会员
  gross_margin_pct: number; // 毛利率 0~1
  trend_5day: number[];     // 近5日营业额（分）
  stores: { store_id: string; store_name: string; online: boolean }[];
  anomaly_discount: number; // 折扣异常数
  anomaly_inventory: number; // 库存预警数
}

// ─── Mock 数据 ───

const MOCK_DATA: MobileDashboardData = {
  revenue_fen: 1258000,
  customer_count: 156,
  new_members: 23,
  gross_margin_pct: 0.42,
  trend_5day: [980000, 1120000, 890000, 1350000, 1258000],
  stores: [
    { store_id: 's1', store_name: '五一广场店', online: true },
    { store_id: 's2', store_name: '解放西路店', online: true },
    { store_id: 's3', store_name: '湘江新区店', online: false },
  ],
  anomaly_discount: 2,
  anomaly_inventory: 1,
};

// ─── 工具函数 ───

/** @deprecated Use formatPrice from @tx-ds/utils */
const fen2yuan = (fen: number) => (fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 0 });

function marginColor(pct: number): string {
  if (pct >= 0.5) return '#0F6E56';
  if (pct >= 0.3) return '#BA7517';
  return '#A32D2D';
}

function marginBg(pct: number): string {
  if (pct >= 0.5) return '#F0FDF4';
  if (pct >= 0.3) return '#FFFBEB';
  return '#FEF2F2';
}

// ─── 迷你趋势图 ───

function MiniTrendChart({ data }: { data: number[] }) {
  if (!data || data.length === 0) return null;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const days = ['周一', '周二', '周三', '周四', '今日'];

  return (
    <div style={{ padding: '16px 0 8px' }}>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 6, height: 60 }}>
        {data.map((val, i) => {
          const height = Math.max(8, ((val - min) / range) * 52 + 8);
          const isToday = i === data.length - 1;
          return (
            <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
              <div style={{
                width: '100%',
                height,
                background: isToday ? '#FF6B35' : '#E8E6E1',
                borderRadius: '3px 3px 0 0',
                transition: 'height 0.3s ease',
              }} />
              <span style={{ fontSize: 10, color: '#B4B2A9' }}>{days[i]}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── 主组件 ───

export function MobileDashboard() {
  const navigate = useNavigate();
  const [data, setData] = useState<MobileDashboardData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    txFetchData<MobileDashboardData>('/api/v1/analytics/dashboard?store_id=all')
      .then(res => {
        if (!cancelled) setData(res ?? MOCK_DATA);
      })
      .catch(() => {
        if (!cancelled) setData(MOCK_DATA);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, []);

  const d = data ?? MOCK_DATA;
  const grossMarginPct = d.gross_margin_pct;
  const estimatedCost = d.revenue_fen * 0.35;
  const isMarginLow = grossMarginPct < 0.3;
  const isMarginGood = grossMarginPct >= 0.5;

  if (loading) {
    return (
      <MobileLayout title="经营总览">
        <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
          {[1, 2, 3].map(i => (
            <div key={i} style={{
              height: 80,
              background: '#E8E6E1',
              borderRadius: 12,
              animation: 'pulse 1.5s ease-in-out infinite',
            }} />
          ))}
          <style>{`@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.5} }`}</style>
        </div>
      </MobileLayout>
    );
  }

  return (
    <MobileLayout title="经营总览">
      <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>

        {/* 今日核心指标 */}
        <div>
          <div style={{ fontSize: 12, color: '#B4B2A9', marginBottom: 8, letterSpacing: 1 }}>
            TODAY · {new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' })}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
            {[
              { label: '营业额', value: `¥${fen2yuan(d.revenue_fen)}`, sub: '元', color: '#FF6B35' },
              { label: '客流量', value: String(d.customer_count), sub: '人次', color: '#185FA5' },
              { label: '新增会员', value: String(d.new_members), sub: '人', color: '#0F6E56' },
            ].map(kpi => (
              <div key={kpi.label} style={{
                background: '#fff',
                borderRadius: 12,
                padding: '14px 12px',
                boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
              }}>
                <div style={{ fontSize: 11, color: '#B4B2A9', marginBottom: 4 }}>{kpi.label}</div>
                <div style={{ fontSize: 22, fontWeight: 700, color: kpi.color, lineHeight: 1.1 }}>
                  {kpi.value}
                </div>
                <div style={{ fontSize: 11, color: '#5F5E5A', marginTop: 2 }}>{kpi.sub}</div>
              </div>
            ))}
          </div>
        </div>

        {/* 盈亏红线 */}
        <div style={{
          background: marginBg(grossMarginPct),
          borderRadius: 12,
          padding: 16,
          border: `1.5px solid ${isMarginLow ? '#A32D2D' : isMarginGood ? '#0F6E56' : '#BA7517'}`,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <div style={{ fontSize: 12, color: '#5F5E5A' }}>今日毛利率</div>
              <div style={{
                fontSize: 32,
                fontWeight: 700,
                color: marginColor(grossMarginPct),
                marginTop: 2,
              }}>
                {(grossMarginPct * 100).toFixed(1)}%
              </div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 11, color: '#B4B2A9' }}>预估成本</div>
              <div style={{ fontSize: 16, fontWeight: 600, color: '#2C2C2A' }}>
                ¥{fen2yuan(estimatedCost)}
              </div>
            </div>
          </div>
          {isMarginLow && (
            <div style={{
              marginTop: 10,
              padding: '6px 10px',
              background: '#A32D2D',
              color: '#fff',
              borderRadius: 6,
              fontSize: 13,
              fontWeight: 600,
            }}>
              ⚠️ 毛利偏低，请检查折扣和成本
            </div>
          )}
          {isMarginGood && (
            <div style={{
              marginTop: 10,
              fontSize: 12,
              color: '#0F6E56',
              fontWeight: 500,
            }}>
              ✓ 毛利健康，继续保持
            </div>
          )}
        </div>

        {/* 5日营业趋势 */}
        <div style={{ background: '#fff', borderRadius: 12, padding: 16, boxShadow: '0 1px 2px rgba(0,0,0,0.05)' }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#2C2C2A', marginBottom: 4 }}>营业趋势（近5日）</div>
          <MiniTrendChart data={d.trend_5day} />
        </div>

        {/* 门店在线状态 */}
        <div style={{ background: '#fff', borderRadius: 12, padding: 16, boxShadow: '0 1px 2px rgba(0,0,0,0.05)' }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#2C2C2A', marginBottom: 12 }}>
            门店状态
            <span style={{ fontSize: 11, color: '#B4B2A9', fontWeight: 400, marginLeft: 6 }}>
              在线 {d.stores.filter(s => s.online).length}/{d.stores.length}
            </span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {d.stores.map(store => (
              <button
                key={store.store_id}
                onClick={() => navigate(`/m/tables?store=${store.store_id}`)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  padding: '10px 0',
                  border: 'none',
                  background: 'transparent',
                  cursor: 'pointer',
                  textAlign: 'left',
                  borderBottom: '1px solid #F0EDE6',
                }}
              >
                <div style={{
                  width: 10,
                  height: 10,
                  borderRadius: '50%',
                  background: store.online ? '#0F6E56' : '#B4B2A9',
                  flexShrink: 0,
                }} />
                <span style={{ flex: 1, fontSize: 14, color: '#2C2C2A' }}>{store.store_name}</span>
                <span style={{ fontSize: 12, color: store.online ? '#0F6E56' : '#B4B2A9' }}>
                  {store.online ? '在线' : '离线'}
                </span>
                <span style={{ fontSize: 12, color: '#B4B2A9' }}>›</span>
              </button>
            ))}
          </div>
        </div>

        {/* 今日异常摘要 */}
        <button
          onClick={() => navigate('/m/anomaly')}
          style={{
            background: '#fff',
            borderRadius: 12,
            padding: 16,
            boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
            border: (d.anomaly_discount + d.anomaly_inventory) > 0 ? '1.5px solid #BA7517' : '1px solid transparent',
            cursor: 'pointer',
            textAlign: 'left',
            width: '100%',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: '#2C2C2A' }}>今日异常摘要</span>
            <span style={{ fontSize: 12, color: '#B4B2A9' }}>查看全部 ›</span>
          </div>
          <div style={{ display: 'flex', gap: 12, marginTop: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{
                background: d.anomaly_discount > 0 ? '#A32D2D' : '#B4B2A9',
                color: '#fff',
                fontSize: 11,
                fontWeight: 700,
                borderRadius: 10,
                padding: '2px 7px',
                minWidth: 20,
                textAlign: 'center',
              }}>{d.anomaly_discount}</span>
              <span style={{ fontSize: 13, color: '#5F5E5A' }}>折扣异常</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{
                background: d.anomaly_inventory > 0 ? '#BA7517' : '#B4B2A9',
                color: '#fff',
                fontSize: 11,
                fontWeight: 700,
                borderRadius: 10,
                padding: '2px 7px',
                minWidth: 20,
                textAlign: 'center',
              }}>{d.anomaly_inventory}</span>
              <span style={{ fontSize: 13, color: '#5F5E5A' }}>库存预警</span>
            </div>
          </div>
        </button>

        {/* 底部留白 */}
        <div style={{ height: 8 }} />
      </div>
    </MobileLayout>
  );
}
