/**
 * 交接班页面 — 服务员端 PWA
 * 路由：/handover
 */
import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchTableStatus, txFetch } from '../api/index';

/* ---------- 颜色常量 ---------- */
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  text: '#E0E0E0',
  muted: '#64748b',
  primary: '#FF6B35',
  red: '#ef4444',
  yellow: '#FF9F0A',
  success: '#30D158',
};

/* ---------- 类型 ---------- */
interface TableStatus {
  table_no: string;
  name: string;
  status: 'empty' | 'occupied' | 'dirty';
  has_unpaid_order: boolean;
}

interface PendingOrder {
  order_no: string;
  table_no: string;
  amount: number;
  created_at: string;
}

/* ---------- 默认值 ---------- */
const DEFAULT_SUMMARY = {
  table_count: 0,
  order_count: 0,
  revenue: 0,
  bell_responses: 0,
  complaints: 0,
  good_reviews: 0,
};

/* ---------- 工具函数 ---------- */
function formatAmount(fen: number): string {
  return `¥${(fen / 100).toFixed(2)}`;
}

function getTableRowBg(t: TableStatus): string {
  if (t.has_unpaid_order) return 'rgba(239,68,68,0.10)';
  if (t.status === 'dirty') return 'rgba(255,159,10,0.10)';
  return 'transparent';
}

function getTableBadge(t: TableStatus): { label: string; color: string } | null {
  if (t.has_unpaid_order) return { label: '未结账', color: C.red };
  if (t.status === 'dirty') return { label: '未清桌', color: C.yellow };
  if (t.status === 'empty') return { label: '空闲', color: C.success };
  return { label: '用餐中', color: C.muted };
}

/* ---------- 主组件 ---------- */
export function HandoverMobilePage() {
  const navigate = useNavigate();
  const [notes, setNotes] = useState('');
  const [showConfirm, setShowConfirm] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [currentTime, setCurrentTime] = useState('');
  const [shiftDuration, setShiftDuration] = useState('');
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  /* 真实数据 state */
  const storeId: string = (window as any).__STORE_ID__ || 'store_001';
  const crewName: string = (window as any).__CREW_NAME__ || '服务员';
  const crewId: string = (window as any).__CREW_ID__ || '';

  const [summary, setSummary] = useState(DEFAULT_SUMMARY);
  const [tables, setTables] = useState<TableStatus[]>([]);
  const [shiftStart, setShiftStart] = useState('09:00');

  /* 加载真实数据 */
  useEffect(() => {
    async function loadData() {
      try {
        const [tableRes, summaryRes] = await Promise.all([
          fetchTableStatus(storeId),
          txFetch<Record<string, any>>(`/api/v1/trade/handover/summary?store_id=${storeId}`),
        ]);

        /* 映射桌台数据 */
        if (tableRes?.items) {
          const mapped: TableStatus[] = tableRes.items.map((item: any) => ({
            table_no: item.table_no,
            name: `${item.table_no}桌`,
            status: item.status === 'occupied'
              ? 'occupied'
              : item.status === 'cleaning'
                ? 'dirty'
                : 'empty',
            has_unpaid_order: item.status === 'occupied' && item.order_id !== null,
          }));
          setTables(mapped);
        }

        /* 映射汇总数据 */
        if (summaryRes) {
          setSummary({
            table_count: summaryRes.table_count ?? 0,
            order_count: summaryRes.order_count ?? 0,
            revenue: summaryRes.revenue ?? 0,
            bell_responses: summaryRes.bell_responses ?? 0,
            complaints: summaryRes.complaints ?? 0,
            good_reviews: summaryRes.good_reviews ?? 0,
          });
          if (summaryRes.shift_start) {
            setShiftStart(summaryRes.shift_start);
          }
        }
      } catch (_err) {
        /* 加载失败降级：保持默认值，页面不崩溃 */
      }
    }
    loadData();
  }, [storeId]);

  /* 未结订单：从桌台数据中派生 */
  const pendingOrders: PendingOrder[] = tables
    .filter(t => t.has_unpaid_order)
    .map(t => ({
      order_no: `—`,
      table_no: t.name,
      amount: 0,
      created_at: '—',
    }));

  /* 员工信息（从全局变量获取） */
  const crew = {
    name: crewName,
    employee_id: crewId || '—',
    shift_start: shiftStart,
    avatar_letter: crewName.charAt(0) || '服',
  };

  /* 实时时钟 */
  useEffect(() => {
    function tick() {
      const now = new Date();
      const h = String(now.getHours()).padStart(2, '0');
      const m = String(now.getMinutes()).padStart(2, '0');
      const s = String(now.getSeconds()).padStart(2, '0');
      setCurrentTime(`${h}:${m}:${s}`);

      /* 计算上班时长 */
      const [sh, sm] = shiftStart.split(':').map(Number);
      const startDate = new Date(now);
      startDate.setHours(sh, sm, 0, 0);
      const diffMs = now.getTime() - startDate.getTime();
      if (diffMs > 0) {
        const totalMin = Math.floor(diffMs / 60000);
        const dh = Math.floor(totalMin / 60);
        const dm = totalMin % 60;
        setShiftDuration(`${dh}小时${dm}分`);
      } else {
        setShiftDuration('—');
      }
    }
    tick();
    timerRef.current = setInterval(tick, 1000);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [shiftStart]);

  /* 打印交班单 */
  function handlePrint() {
    if ((window as any).TXBridge) {
      (window as any).TXBridge.print('[交班单]\n' + JSON.stringify(summary, null, 2));
    } else {
      alert('打印功能需在 POS 终端上使用');
    }
  }

  /* 确认交班 */
  async function handleConfirmHandover() {
    setSubmitting(true);
    try {
      const res = await fetch('/api/v1/crew/handover', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          crew_id: crewId,
          notes,
          shift_summary_data: summary,
        }),
      });
      const json = await res.json();
      if (json.ok) {
        navigate('/profile');
      } else {
        alert('交班失败：' + (json.error?.message || '未知错误'));
      }
    } catch (_err) {
      alert('网络错误，请重试');
    } finally {
      setSubmitting(false);
      setShowConfirm(false);
    }
  }

  const summaryItems = [
    { label: '接待桌次', value: `${summary.table_count}桌` },
    { label: '点单笔数', value: `${summary.order_count}笔` },
    { label: '营业额',   value: formatAmount(summary.revenue) },
    { label: '服务铃响应', value: `${summary.bell_responses}次` },
    { label: '投诉件数', value: `${summary.complaints}件`, accent: summary.complaints > 0 ? C.red : C.success },
    { label: '好评数',   value: `${summary.good_reviews}条`, accent: C.success },
  ];

  return (
    <div style={{ background: C.bg, minHeight: '100vh', color: C.text, paddingBottom: 100 }}>

      {/* ---- 顶部导航栏 ---- */}
      <div style={{
        position: 'sticky', top: 0, zIndex: 20,
        background: C.bg, borderBottom: `1px solid ${C.border}`,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '0 16px', height: 56,
      }}>
        <button
          onClick={() => navigate(-1)}
          style={{
            background: 'none', border: 'none', color: C.text, fontSize: 20,
            cursor: 'pointer', minWidth: 48, minHeight: 48,
            display: 'flex', alignItems: 'center', justifyContent: 'flex-start',
            padding: 0,
          }}
        >
          ←
        </button>
        <span style={{ fontSize: 18, fontWeight: 700, color: '#fff' }}>交接班</span>
        <span style={{ fontSize: 16, color: C.muted, minWidth: 80, textAlign: 'right' }}>
          {currentTime}
        </span>
      </div>

      <div style={{ padding: '16px 16px 0' }}>

        {/* ---- 交班人信息区 ---- */}
        <div style={{
          background: C.card, borderRadius: 16, padding: '20px 16px',
          border: `1px solid ${C.border}`, marginBottom: 16,
          display: 'flex', alignItems: 'center', gap: 16,
        }}>
          {/* 头像占位 */}
          <div style={{
            width: 60, height: 60, borderRadius: '50%',
            background: C.primary, display: 'flex', alignItems: 'center',
            justifyContent: 'center', fontSize: 24, fontWeight: 700,
            color: '#fff', flexShrink: 0,
          }}>
            {crew.avatar_letter}
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 20, fontWeight: 700, color: '#fff', marginBottom: 4 }}>
              {crew.name}
            </div>
            <div style={{ fontSize: 16, color: C.muted, marginBottom: 4 }}>
              工号：{crew.employee_id}
            </div>
            <div style={{ fontSize: 16, color: C.muted }}>
              上班时长：<span style={{ color: C.primary, fontWeight: 600 }}>{shiftDuration}</span>
              <span style={{ marginLeft: 8 }}>（{crew.shift_start} 上班）</span>
            </div>
          </div>
        </div>

        {/* ---- 本班数据摘要 2×3 网格 ---- */}
        <h2 style={{ fontSize: 16, fontWeight: 600, color: '#fff', margin: '0 0 10px' }}>
          本班数据摘要
        </h2>
        <div style={{
          display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)',
          gap: 8, marginBottom: 16,
        }}>
          {summaryItems.map(item => (
            <div key={item.label} style={{
              background: C.card, borderRadius: 12, padding: '14px 10px',
              border: `1px solid ${C.border}`, textAlign: 'center',
            }}>
              <div style={{
                fontSize: 20, fontWeight: 800,
                color: item.accent || C.text, marginBottom: 4,
              }}>
                {item.value}
              </div>
              <div style={{ fontSize: 13, color: C.muted }}>{item.label}</div>
            </div>
          ))}
        </div>

        {/* ---- 桌台状态检查 ---- */}
        <h2 style={{ fontSize: 16, fontWeight: 600, color: '#fff', margin: '0 0 10px' }}>
          桌台状态检查
        </h2>
        <div style={{
          background: C.card, borderRadius: 12, border: `1px solid ${C.border}`,
          overflow: 'hidden', marginBottom: 16,
          maxHeight: 280, overflowY: 'auto',
        }}>
          {tables.map((t, idx) => {
            const badge = getTableBadge(t);
            return (
              <div key={t.table_no} style={{
                display: 'flex', alignItems: 'center',
                padding: '14px 16px', minHeight: 52,
                background: getTableRowBg(t),
                borderBottom: idx < tables.length - 1
                  ? `1px solid ${C.border}` : 'none',
              }}>
                <span style={{ fontSize: 16, flex: 1, color: '#fff', fontWeight: 500 }}>
                  {t.name}
                </span>
                {badge && (
                  <span style={{
                    fontSize: 13, fontWeight: 600, color: badge.color,
                    border: `1px solid ${badge.color}`,
                    borderRadius: 6, padding: '2px 8px',
                  }}>
                    {badge.label}
                  </span>
                )}
              </div>
            );
          })}
        </div>

        {/* ---- 未结订单列表 ---- */}
        {pendingOrders.length > 0 && (
          <>
            <h2 style={{ fontSize: 16, fontWeight: 600, color: '#fff', margin: '0 0 10px' }}>
              未结订单
              <span style={{
                marginLeft: 8, fontSize: 13, color: C.red,
                border: `1px solid ${C.red}`, borderRadius: 6, padding: '1px 6px',
              }}>
                {pendingOrders.length}单
              </span>
            </h2>
            <div style={{
              background: C.card, borderRadius: 12, border: `1px solid ${C.border}`,
              overflow: 'hidden', marginBottom: 16,
            }}>
              {pendingOrders.map((order, idx) => (
                <div key={order.order_no + idx} style={{
                  padding: '14px 16px', minHeight: 52,
                  borderBottom: idx < pendingOrders.length - 1
                    ? `1px solid ${C.border}` : 'none',
                  background: 'rgba(239,68,68,0.06)',
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                    <span style={{ fontSize: 14, color: C.muted }}>{order.order_no}</span>
                    <span style={{ fontSize: 18, fontWeight: 700, color: C.red }}>
                      {formatAmount(order.amount)}
                    </span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: 16, color: '#fff' }}>{order.table_no}</span>
                    <span style={{ fontSize: 14, color: C.muted }}>下单 {order.created_at}</span>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}

        {/* ---- 交接事项备注 ---- */}
        <h2 style={{ fontSize: 16, fontWeight: 600, color: '#fff', margin: '0 0 10px' }}>
          交接事项备注
        </h2>
        <div style={{ marginBottom: 24 }}>
          <textarea
            value={notes}
            onChange={e => setNotes(e.target.value)}
            placeholder="请填写需要交接的事项，如特殊顾客、未完成任务、设备问题等……"
            style={{
              width: '100%', minHeight: 120, boxSizing: 'border-box',
              background: C.card, border: `1px solid ${C.border}`,
              borderRadius: 12, padding: '14px 16px',
              color: C.text, fontSize: 18, lineHeight: 1.6,
              resize: 'vertical', outline: 'none',
              fontFamily: 'inherit',
            }}
          />
        </div>

      </div>

      {/* ---- 底部固定按钮区 ---- */}
      <div style={{
        position: 'fixed', bottom: 0, left: 0, right: 0,
        background: C.bg, borderTop: `1px solid ${C.border}`,
        padding: '12px 16px', display: 'flex', gap: 12, zIndex: 30,
      }}>
        {/* 打印交班单 */}
        <button
          onClick={handlePrint}
          style={{
            flex: 1, minHeight: 52, borderRadius: 12,
            border: `2px solid ${C.primary}`, background: 'transparent',
            color: C.primary, fontSize: 17, fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          打印交班单
        </button>

        {/* 确认交班 */}
        <button
          onClick={() => setShowConfirm(true)}
          style={{
            flex: 1, minHeight: 52, borderRadius: 12,
            border: 'none', background: C.primary,
            color: '#fff', fontSize: 17, fontWeight: 700,
            cursor: 'pointer',
          }}
        >
          确认交班
        </button>
      </div>

      {/* ---- 二次确认弹窗 ---- */}
      {showConfirm && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 100,
          background: 'rgba(0,0,0,0.7)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          padding: '0 24px',
        }}>
          <div style={{
            background: '#1a2f38', borderRadius: 20, padding: '28px 24px',
            border: `1px solid ${C.border}`, width: '100%', maxWidth: 360,
          }}>
            <h3 style={{ fontSize: 20, fontWeight: 700, color: '#fff', marginBottom: 16, textAlign: 'center' }}>
              确认交班
            </h3>
            <p style={{ fontSize: 17, color: C.muted, lineHeight: 1.6, textAlign: 'center', marginBottom: 28 }}>
              确认交班后将退出当前工作状态，是否继续？
            </p>
            <div style={{ display: 'flex', gap: 12 }}>
              <button
                onClick={() => setShowConfirm(false)}
                disabled={submitting}
                style={{
                  flex: 1, minHeight: 52, borderRadius: 12,
                  border: `1px solid ${C.border}`, background: 'transparent',
                  color: C.text, fontSize: 17, cursor: 'pointer',
                }}
              >
                取消
              </button>
              <button
                onClick={handleConfirmHandover}
                disabled={submitting}
                style={{
                  flex: 1, minHeight: 52, borderRadius: 12,
                  border: 'none', background: submitting ? '#8B3A1E' : C.primary,
                  color: '#fff', fontSize: 17, fontWeight: 700,
                  cursor: submitting ? 'not-allowed' : 'pointer',
                }}
              >
                {submitting ? '提交中…' : '确认交班'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
