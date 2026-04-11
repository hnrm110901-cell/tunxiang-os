/**
 * 营业中控台 — /manager/store-live
 * 店长在营业期间实时监控门店运营状态的核心页面
 * 实时数据 + 慢菜预警 + 退菜/投诉流 + 翻台率 + 等位 + 快捷操作
 *
 * API: GET /api/v1/ops/store/live-dashboard
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchStoreLive, rushDish } from '../../api/storeLiveApi';
import type { StoreLiveData, SlowDish } from '../../api/storeLiveApi';

// ─── 设计Token ───

const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  text: '#E0E0E0',
  muted: '#64748b',
  primary: '#FF6B35',
  success: '#0F6E56',
  warning: '#BA7517',
  danger: '#A32D2D',
};

const pageStyle: React.CSSProperties = {
  padding: 16,
  background: C.bg,
  minHeight: '100vh',
  color: '#fff',
  fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif',
  maxWidth: 500,
  margin: '0 auto',
  paddingBottom: 80,
};

const cardStyle: React.CSSProperties = {
  background: C.card,
  borderRadius: 10,
  padding: 14,
  marginBottom: 12,
};

const fen2yuan = (fen: number) => `¥${(fen / 100).toFixed(0)}`;
const pct = (v: number) => `${(v * 100).toFixed(0)}%`;

// ─── Fallback ───

const FALLBACK: StoreLiveData = {
  revenue_fen: 4280000,
  revenue_target_fen: 6000000,
  order_count: 186,
  table_utilization: 0.78,
  waiting_count: 12,
  avg_dining_minutes: 52,
  table_turnover: 2.4,
  table_turnover_yesterday: 2.1,
  slow_dishes: [
    { dish_name: '剁椒鱼头', table_no: 'A05', wait_minutes: 22, order_item_id: 'oi_001' },
    { dish_name: '口味虾(大)', table_no: 'B12', wait_minutes: 18, order_item_id: 'oi_002' },
    { dish_name: '蒜蓉龙虾', table_no: 'C03', wait_minutes: 16, order_item_id: 'oi_003' },
  ],
  recent_returns: [
    { time: '12:35', dish_name: '皮蛋豆腐', table_no: 'A02', reason: '菜品变质' },
    { time: '12:18', dish_name: '酸辣土豆丝', table_no: 'B08', reason: '上错菜' },
  ],
  recent_complaints: [
    { time: '12:40', type: '服务', content: 'B12桌反映等菜时间过长' },
    { time: '11:55', type: '环境', content: 'A区空调温度偏高' },
  ],
  waiting_queue: [
    { party_size: 4, wait_minutes: 25, queue_no: 'A015' },
    { party_size: 2, wait_minutes: 18, queue_no: 'A016' },
    { party_size: 6, wait_minutes: 12, queue_no: 'A017' },
    { party_size: 3, wait_minutes: 5, queue_no: 'A018' },
  ],
};

const POLL_INTERVAL = 30_000; // 30秒轮询

// ─── 主组件 ───

export function StoreLivePage() {
  const navigate = useNavigate();
  const [data, setData] = useState<StoreLiveData>(FALLBACK);
  const [loading, setLoading] = useState(false);
  const [rushingIds, setRushingIds] = useState<Set<string>>(new Set());
  const [newEventPulse, setNewEventPulse] = useState(false);
  const prevCountRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setInterval>>();

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const d = await fetchStoreLive();
      if (d) setData(d);
    } catch { /* fallback */ }
    setLoading(false);
  }, []);

  useEffect(() => {
    loadData();
    timerRef.current = setInterval(loadData, POLL_INTERVAL);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [loadData]);

  // 新事件脉冲动画
  useEffect(() => {
    const total = data.recent_returns.length + data.recent_complaints.length;
    if (prevCountRef.current > 0 && total > prevCountRef.current) {
      setNewEventPulse(true);
      const t = setTimeout(() => setNewEventPulse(false), 2000);
      return () => clearTimeout(t);
    }
    prevCountRef.current = total;
  }, [data.recent_returns.length, data.recent_complaints.length]);

  const handleRush = async (item: SlowDish) => {
    setRushingIds(prev => new Set(prev).add(item.order_item_id));
    try {
      await rushDish(item.order_item_id);
    } catch { /* ignore */ }
    setTimeout(() => {
      setRushingIds(prev => {
        const s = new Set(prev);
        s.delete(item.order_item_id);
        return s;
      });
    }, 2000);
  };

  const revenueProgress = data.revenue_target_fen > 0
    ? Math.min(data.revenue_fen / data.revenue_target_fen, 1)
    : 0;

  return (
    <div style={pageStyle}>
      {/* 头部 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 600 }}>营业中控台</div>
          <div style={{ fontSize: 13, color: '#9CA3AF', marginTop: 2 }}>
            实时监控 {loading && '· 刷新中...'}
          </div>
        </div>
        <button type="button" onClick={() => navigate(-1)} style={backBtnStyle}>
          ← 返回
        </button>
      </div>

      {/* 实时数据条 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 10, marginBottom: 12 }}>
        <div style={cardStyle}>
          <div style={{ fontSize: 12, color: '#9CA3AF' }}>今日营收</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: C.primary, marginTop: 4 }}>
            {fen2yuan(data.revenue_fen)}
          </div>
          {/* 进度条 */}
          <div style={{ marginTop: 6 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: C.muted, marginBottom: 3 }}>
              <span>目标 {fen2yuan(data.revenue_target_fen)}</span>
              <span>{pct(revenueProgress)}</span>
            </div>
            <div style={{ height: 4, background: C.border, borderRadius: 2, overflow: 'hidden' }}>
              <div style={{
                height: '100%',
                width: pct(revenueProgress),
                background: revenueProgress >= 0.8 ? C.success : revenueProgress >= 0.5 ? C.warning : C.danger,
                borderRadius: 2,
                transition: 'width 0.5s ease',
              }} />
            </div>
          </div>
        </div>
        <div style={cardStyle}>
          <div style={{ fontSize: 12, color: '#9CA3AF' }}>今日单量</div>
          <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>{data.order_count}</div>
          <div style={{ fontSize: 12, color: C.muted, marginTop: 4 }}>客均用餐 {data.avg_dining_minutes}分钟</div>
        </div>
        <div style={cardStyle}>
          <div style={{ fontSize: 12, color: '#9CA3AF' }}>桌台利用率</div>
          <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4, color: data.table_utilization > 0.85 ? C.danger : '#fff' }}>
            {pct(data.table_utilization)}
          </div>
        </div>
        <div style={cardStyle}>
          <div style={{ fontSize: 12, color: '#9CA3AF' }}>当前等位</div>
          <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4, color: data.waiting_count > 10 ? C.warning : '#fff' }}>
            {data.waiting_count}组
          </div>
        </div>
      </div>

      {/* 慢菜预警区 */}
      {data.slow_dishes.length > 0 && (
        <div style={{
          ...cardStyle,
          borderLeft: `4px solid ${C.danger}`,
          background: 'rgba(163,45,45,0.08)',
        }}>
          <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 10, color: C.danger, display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 18 }}>🔥</span> 慢菜预警
            <span style={{ fontSize: 12, fontWeight: 400, color: C.muted, marginLeft: 'auto' }}>超15分钟</span>
          </div>
          {data.slow_dishes.map((d) => (
            <div key={d.order_item_id} style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              padding: '8px 0',
              borderBottom: `1px solid ${C.border}`,
            }}>
              <div>
                <div style={{ fontSize: 14, fontWeight: 500 }}>{d.dish_name}</div>
                <div style={{ fontSize: 12, color: C.muted, marginTop: 2 }}>
                  {d.table_no}桌 · 已等 <span style={{ color: d.wait_minutes >= 20 ? C.danger : C.warning, fontWeight: 600 }}>{d.wait_minutes}分钟</span>
                </div>
              </div>
              <button
                type="button"
                onClick={() => handleRush(d)}
                disabled={rushingIds.has(d.order_item_id)}
                style={{
                  padding: '6px 14px',
                  background: rushingIds.has(d.order_item_id) ? C.muted : C.danger,
                  color: '#fff',
                  border: 'none',
                  borderRadius: 6,
                  fontSize: 13,
                  fontWeight: 500,
                  cursor: rushingIds.has(d.order_item_id) ? 'default' : 'pointer',
                  minHeight: 32,
                  opacity: rushingIds.has(d.order_item_id) ? 0.6 : 1,
                }}
              >
                {rushingIds.has(d.order_item_id) ? '已催' : '催菜'}
              </button>
            </div>
          ))}
        </div>
      )}

      {/* 退菜/投诉实时流 */}
      <div style={{
        ...cardStyle,
        position: 'relative',
        overflow: 'hidden',
      }}>
        {newEventPulse && (
          <div style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            height: 3,
            background: `linear-gradient(90deg, transparent, ${C.primary}, transparent)`,
            animation: 'none',
          }} />
        )}
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 18 }}>📋</span> 退菜/投诉动态
          {newEventPulse && (
            <span style={{
              fontSize: 11,
              background: C.danger,
              color: '#fff',
              padding: '2px 8px',
              borderRadius: 10,
              marginLeft: 8,
            }}>新</span>
          )}
        </div>

        {data.recent_returns.length > 0 && (
          <div style={{ marginBottom: 8 }}>
            <div style={{ fontSize: 12, color: C.muted, marginBottom: 6 }}>退菜记录</div>
            {data.recent_returns.map((r, i) => (
              <div key={`ret-${i}`} style={{
                padding: '8px 10px',
                background: 'rgba(163,45,45,0.06)',
                borderRadius: 6,
                marginBottom: 4,
                borderLeft: `3px solid ${C.danger}`,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
                  <span style={{ fontWeight: 500 }}>{r.dish_name} · {r.table_no}桌</span>
                  <span style={{ color: C.muted }}>{r.time}</span>
                </div>
                <div style={{ fontSize: 12, color: C.muted, marginTop: 2 }}>原因: {r.reason}</div>
              </div>
            ))}
          </div>
        )}

        {data.recent_complaints.length > 0 && (
          <div>
            <div style={{ fontSize: 12, color: C.muted, marginBottom: 6 }}>投诉记录</div>
            {data.recent_complaints.map((c, i) => (
              <div key={`cmp-${i}`} style={{
                padding: '8px 10px',
                background: 'rgba(186,117,23,0.06)',
                borderRadius: 6,
                marginBottom: 4,
                borderLeft: `3px solid ${C.warning}`,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
                  <span style={{ fontWeight: 500 }}>{c.type}</span>
                  <span style={{ color: C.muted }}>{c.time}</span>
                </div>
                <div style={{ fontSize: 12, color: C.muted, marginTop: 2 }}>{c.content}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 翻台率实时图表 */}
      <div style={cardStyle}>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 18 }}>📊</span> 翻台率
        </div>
        <div style={{ display: 'flex', gap: 16, alignItems: 'flex-end', height: 80, marginBottom: 8 }}>
          <BarColumn label="昨日" value={data.table_turnover_yesterday} max={5} color={C.muted} />
          <BarColumn label="今日" value={data.table_turnover} max={5} color={C.primary} />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: C.muted }}>
          <span>
            今日 <span style={{ color: '#fff', fontWeight: 600 }}>{data.table_turnover.toFixed(1)}</span> vs
            昨日 <span style={{ color: '#fff' }}>{data.table_turnover_yesterday.toFixed(1)}</span>
          </span>
          <span>
            {data.table_turnover >= data.table_turnover_yesterday
              ? <span style={{ color: C.success }}>↑ 提升</span>
              : <span style={{ color: C.danger }}>↓ 下降</span>
            }
          </span>
        </div>
      </div>

      {/* 等位队列 */}
      {data.waiting_queue.length > 0 && (
        <div style={cardStyle}>
          <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 18 }}>🪑</span> 等位队列
            <span style={{ fontSize: 12, color: C.muted, fontWeight: 400, marginLeft: 'auto' }}>
              共{data.waiting_queue.length}组
            </span>
          </div>
          {data.waiting_queue.map((w, i) => {
            const isNearlyUp = w.wait_minutes >= 20;
            return (
              <div key={w.queue_no} style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '8px 0',
                borderBottom: i < data.waiting_queue.length - 1 ? `1px solid ${C.border}` : 'none',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    width: 36,
                    height: 36,
                    borderRadius: 8,
                    background: isNearlyUp ? 'rgba(255,107,53,0.12)' : C.border,
                    fontSize: 13,
                    fontWeight: 600,
                    color: isNearlyUp ? C.primary : '#fff',
                  }}>
                    {w.queue_no}
                  </span>
                  <div>
                    <div style={{ fontSize: 14 }}>{w.party_size}人桌</div>
                    <div style={{ fontSize: 12, color: C.muted }}>已等{w.wait_minutes}分钟</div>
                  </div>
                </div>
                {isNearlyUp && (
                  <span style={{
                    fontSize: 11,
                    background: C.primary,
                    color: '#fff',
                    padding: '3px 8px',
                    borderRadius: 10,
                    fontWeight: 500,
                  }}>
                    即将到号
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* 快捷操作区 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 16 }}>
        {[
          { icon: '🔥', label: '催菜', action: () => navigate('/rush') },
          { icon: '🚫', label: '沽清', action: () => {} },
          { icon: '📢', label: '通知后厨', action: () => {} },
          { icon: '🍽️', label: '呼叫传菜', action: () => {} },
        ].map((op) => (
          <button
            key={op.label}
            type="button"
            onClick={op.action}
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 6,
              padding: '14px 0',
              background: C.card,
              border: `1px solid ${C.border}`,
              borderRadius: 10,
              color: '#fff',
              fontSize: 13,
              cursor: 'pointer',
              minHeight: 68,
            }}
          >
            <span style={{ fontSize: 22 }}>{op.icon}</span>
            {op.label}
          </button>
        ))}
      </div>
    </div>
  );
}

// ─── 子组件 ───

function BarColumn({ label, value, max, color }: { label: string; value: number; max: number; color: string }) {
  const h = Math.max((value / max) * 60, 4);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flex: 1, gap: 4 }}>
      <span style={{ fontSize: 13, fontWeight: 600, color }}>{value.toFixed(1)}</span>
      <div style={{ width: '100%', maxWidth: 48, height: 60, display: 'flex', alignItems: 'flex-end' }}>
        <div style={{
          width: '100%',
          height: h,
          background: color,
          borderRadius: 4,
          transition: 'height 0.4s ease',
        }} />
      </div>
      <span style={{ fontSize: 11, color: C.muted }}>{label}</span>
    </div>
  );
}

const backBtnStyle: React.CSSProperties = {
  padding: '6px 14px',
  background: '#1a2a33',
  color: '#9CA3AF',
  border: '1px solid #333',
  borderRadius: 6,
  fontSize: 14,
  cursor: 'pointer',
  minHeight: 36,
};
