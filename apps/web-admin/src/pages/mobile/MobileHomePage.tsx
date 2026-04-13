/**
 * 移动端首页 — 管理直通车
 * 路由: /m/home
 * API: tx-analytics :8009 /api/v1/analytics/dashboard-stats
 *
 * 功能：
 * - 今日营业额大字卡片
 * - 今日客流量
 * - 新增会员数
 * - 5日迷你趋势线（CSS柱状图）
 * - 门店在线状态指示点（绿/灰）
 * - 异常汇总卡片（折扣异常/退单异常/库存预警数）
 */
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { MobileLayout } from '../../components/MobileLayout';
import { txFetchData } from '../../api/client';
import { formatPrice } from '@tx-ds/utils';

// ─── 类型 ───

interface DashboardStats {
  revenue_fen: number;
  customer_count: number;
  new_members: number;
  trend_5day: { date: string; revenue_fen: number }[];
  stores: { store_id: string; store_name: string; online: boolean; today_revenue_fen: number }[];
  anomaly_discount: number;
  anomaly_refund: number;
  anomaly_inventory: number;
}

// ─── Mock 数据 ───

const MOCK: DashboardStats = {
  revenue_fen: 1258000,
  customer_count: 156,
  new_members: 23,
  trend_5day: [
    { date: '04-05', revenue_fen: 980000 },
    { date: '04-06', revenue_fen: 1120000 },
    { date: '04-07', revenue_fen: 890000 },
    { date: '04-08', revenue_fen: 1350000 },
    { date: '04-09', revenue_fen: 1258000 },
  ],
  stores: [
    { store_id: 's1', store_name: '五一广场店', online: true, today_revenue_fen: 528000 },
    { store_id: 's2', store_name: '解放西路店', online: true, today_revenue_fen: 412000 },
    { store_id: 's3', store_name: '湘江新区店', online: false, today_revenue_fen: 0 },
    { store_id: 's4', store_name: '梅溪湖店', online: true, today_revenue_fen: 318000 },
  ],
  anomaly_discount: 2,
  anomaly_refund: 1,
  anomaly_inventory: 3,
};

// ─── 工具函数 ───

/** @deprecated Use formatPrice from @tx-ds/utils */
const fen2yuan = (fen: number) =>
  (fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 0 });

// ─── 5日迷你趋势（纯CSS柱状图） ───

function MiniTrend5Day({ data }: { data: DashboardStats['trend_5day'] }) {
  if (!data || data.length === 0) return null;
  const values = data.map(d => d.revenue_fen);
  const max = Math.max(...values);
  const min = Math.min(...values);
  const range = max - min || 1;

  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 6, height: 64 }}>
      {data.map((item, i) => {
        const height = Math.max(10, ((item.revenue_fen - min) / range) * 48 + 16);
        const isToday = i === data.length - 1;
        return (
          <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
            <span style={{ fontSize: 9, color: '#B4B2A9', whiteSpace: 'nowrap' }}>
              {isToday ? '今日' : item.date}
            </span>
            <div style={{
              width: '100%',
              maxWidth: 36,
              height,
              background: isToday
                ? 'linear-gradient(180deg, #FF6B35 0%, #E55A28 100%)'
                : '#E8E6E1',
              borderRadius: '4px 4px 0 0',
              transition: 'height 0.4s ease',
              position: 'relative',
            }}>
              {isToday && (
                <span style={{
                  position: 'absolute',
                  top: -16,
                  left: '50%',
                  transform: 'translateX(-50%)',
                  fontSize: 9,
                  color: '#FF6B35',
                  fontWeight: 700,
                  whiteSpace: 'nowrap',
                }}>
                  ¥{fen2yuan(item.revenue_fen)}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── 主组件 ───

export function MobileHomePage() {
  const navigate = useNavigate();
  const [data, setData] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    txFetchData<DashboardStats>('/api/v1/analytics/dashboard-stats')
      .then(res => {
        if (!cancelled) setData(res.data ?? MOCK);
      })
      .catch(() => {
        if (!cancelled) setData(MOCK);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, []);

  const d = data ?? MOCK;
  const totalAnomalies = d.anomaly_discount + d.anomaly_refund + d.anomaly_inventory;
  const onlineCount = d.stores.filter(s => s.online).length;

  // 加载骨架屏
  if (loading) {
    return (
      <MobileLayout title="经营总览">
        <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
          {[120, 80, 60, 100].map((h, i) => (
            <div key={i} style={{
              height: h,
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

        {/* ── 今日营业额 大字卡片 ── */}
        <div style={{
          background: 'linear-gradient(135deg, #FF6B35 0%, #E55A28 100%)',
          borderRadius: 14,
          padding: '20px 18px',
          color: '#fff',
          boxShadow: '0 4px 12px rgba(255,107,53,0.3)',
        }}>
          <div style={{ fontSize: 13, opacity: 0.85, marginBottom: 4 }}>今日营业额</div>
          <div style={{ fontSize: 36, fontWeight: 800, lineHeight: 1.1, letterSpacing: -1 }}>
            <span style={{ fontSize: 20, fontWeight: 600 }}>¥</span>
            {fen2yuan(d.revenue_fen)}
          </div>
          <div style={{
            display: 'flex',
            gap: 24,
            marginTop: 14,
            paddingTop: 14,
            borderTop: '1px solid rgba(255,255,255,0.2)',
          }}>
            <div>
              <div style={{ fontSize: 11, opacity: 0.7 }}>客流量</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{d.customer_count}<span style={{ fontSize: 12, fontWeight: 400, opacity: 0.7 }}> 人次</span></div>
            </div>
            <div>
              <div style={{ fontSize: 11, opacity: 0.7 }}>新增会员</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{d.new_members}<span style={{ fontSize: 12, fontWeight: 400, opacity: 0.7 }}> 人</span></div>
            </div>
          </div>
        </div>

        {/* ── 5日营业趋势 ── */}
        <div style={{
          background: '#fff',
          borderRadius: 12,
          padding: '14px 16px 12px',
          boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
        }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#2C2C2A', marginBottom: 12 }}>
            营业趋势（近5日）
          </div>
          <MiniTrend5Day data={d.trend_5day} />
        </div>

        {/* ── 门店在线状态 ── */}
        <div style={{
          background: '#fff',
          borderRadius: 12,
          padding: '14px 16px',
          boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
        }}>
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 10,
          }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: '#2C2C2A' }}>
              门店状态
              <span style={{ fontSize: 11, color: '#B4B2A9', fontWeight: 400, marginLeft: 6 }}>
                在线 {onlineCount}/{d.stores.length}
              </span>
            </div>
            <button
              onClick={() => navigate('/m/stores')}
              style={{
                fontSize: 12,
                color: '#FF6B35',
                background: 'transparent',
                border: 'none',
                cursor: 'pointer',
                padding: 0,
              }}
            >
              查看全部 &rsaquo;
            </button>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
            {d.stores.map((store, idx) => (
              <button
                key={store.store_id}
                onClick={() => navigate(`/m/stores?store=${store.store_id}`)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  padding: '10px 0',
                  border: 'none',
                  background: 'transparent',
                  cursor: 'pointer',
                  textAlign: 'left',
                  width: '100%',
                  borderBottom: idx < d.stores.length - 1 ? '1px solid #F0EDE6' : 'none',
                }}
              >
                {/* 在线指示点 */}
                <div style={{
                  width: 10,
                  height: 10,
                  borderRadius: '50%',
                  background: store.online ? '#0F6E56' : '#B4B2A9',
                  flexShrink: 0,
                  boxShadow: store.online ? '0 0 6px rgba(15,110,86,0.4)' : 'none',
                }} />
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 14, color: '#2C2C2A', fontWeight: 500 }}>{store.store_name}</div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: store.online ? '#2C2C2A' : '#B4B2A9' }}>
                    ¥{fen2yuan(store.today_revenue_fen)}
                  </div>
                  <div style={{ fontSize: 11, color: store.online ? '#0F6E56' : '#B4B2A9' }}>
                    {store.online ? '营业中' : '离线'}
                  </div>
                </div>
                <span style={{ fontSize: 12, color: '#B4B2A9' }}>&rsaquo;</span>
              </button>
            ))}
          </div>
        </div>

        {/* ── 异常汇总卡片 ── */}
        <button
          onClick={() => navigate('/m/anomaly')}
          style={{
            background: '#fff',
            borderRadius: 12,
            padding: 16,
            boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
            border: totalAnomalies > 0 ? '1.5px solid #BA7517' : '1px solid #E8E6E1',
            cursor: 'pointer',
            textAlign: 'left',
            width: '100%',
          }}
        >
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 12,
          }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: '#2C2C2A' }}>
              异常汇总
              {totalAnomalies > 0 && (
                <span style={{
                  marginLeft: 8,
                  background: '#A32D2D',
                  color: '#fff',
                  fontSize: 11,
                  fontWeight: 700,
                  borderRadius: 10,
                  padding: '2px 7px',
                }}>
                  {totalAnomalies}
                </span>
              )}
            </span>
            <span style={{ fontSize: 12, color: '#B4B2A9' }}>查看详情 &rsaquo;</span>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {[
              { label: '折扣异常', count: d.anomaly_discount, color: '#A32D2D' },
              { label: '退单异常', count: d.anomaly_refund, color: '#BA7517' },
              { label: '库存预警', count: d.anomaly_inventory, color: '#185FA5' },
            ].map(item => (
              <div key={item.label} style={{
                flex: 1,
                background: item.count > 0 ? `${item.color}0D` : '#F8F7F5',
                borderRadius: 8,
                padding: '10px 8px',
                textAlign: 'center',
              }}>
                <div style={{
                  fontSize: 22,
                  fontWeight: 700,
                  color: item.count > 0 ? item.color : '#B4B2A9',
                  lineHeight: 1.1,
                }}>
                  {item.count}
                </div>
                <div style={{ fontSize: 11, color: '#5F5E5A', marginTop: 4 }}>{item.label}</div>
              </div>
            ))}
          </div>
        </button>

        {/* 底部留白 */}
        <div style={{ height: 8 }} />
      </div>
    </MobileLayout>
  );
}
