/**
 * RemakeModal — 重做弹窗（独立页面 + 可嵌入看板的弹窗模式）
 *
 * 选择重做原因（客诉/品质/错误）
 * 确认重做（调用 POST /kds/task/{id}/remake）
 * 深色背景，触控优化（最小48x48按钮，最小16px字体）
 */
import { useState, useEffect, useCallback } from 'react';
import { fetchTicketQueue, remakeTicket } from '../api/kdsOpsApi';
import { txFetch } from '../api/index';

// ─── Types ───

type RemakeReason = 'complaint' | 'quality' | 'wrong_dish' | 'wrong_spec' | 'other';

interface RemakeReasonOption {
  id: RemakeReason;
  label: string;
  description: string;
  color: string;
}

interface RemakeTicket {
  id: string;
  orderNo: string;
  tableNo: string;
  dishName: string;
  qty: number;
  originalChef: string;
  dept: string;
}

interface RemakeRecord {
  id: string;
  ticketId: string;
  tableNo: string;
  dishName: string;
  reason: RemakeReason;
  reasonText: string;
  notes: string;
  createdAt: number;
  status: 'remaking' | 'completed';
}

// ─── Constants ───

const REASONS: RemakeReasonOption[] = [
  { id: 'complaint', label: '客诉退回', description: '顾客投诉菜品不满意', color: '#A32D2D' },
  { id: 'quality', label: '品质问题', description: '菜品不符合出品标准', color: '#BA7517' },
  { id: 'wrong_dish', label: '错菜', description: '做错了菜品', color: '#185FA5' },
  { id: 'wrong_spec', label: '规格错误', description: '做法/口味/分量不对', color: '#722ed1' },
  { id: 'other', label: '其他', description: '其他需要重做的原因', color: '#666' },
];

// ─── Config ───

const STATION_ID = localStorage.getItem('kds_station_id') || '';

// ─── Component ───

export function RemakeModal() {
  const [tickets, setTickets] = useState<RemakeTicket[]>([]);
  const [records, setRecords] = useState<RemakeRecord[]>([]);
  const [selectedTicket, setSelectedTicket] = useState<RemakeTicket | null>(null);
  const [selectedReason, setSelectedReason] = useState<RemakeReason | null>(null);
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<'remake' | 'history'>('remake');

  // 加载可重做的工单（cooking 状态的票据）
  const loadTickets = useCallback(async () => {
    if (!STATION_ID) {
      setLoading(false);
      setError('未配置档口信息');
      return;
    }
    setLoading(true);
    try {
      const res = await fetchTicketQueue(STATION_ID, 'cooking');
      const mapped: RemakeTicket[] = res.items.map(t => ({
        id: t.ticket_id,
        orderNo: t.order_no,
        tableNo: t.table_no,
        dishName: t.items.map(i => i.dish_name).join('/'),
        qty: t.items.reduce((sum, i) => sum + i.quantity, 0),
        originalChef: '',
        dept: t.dept_id,
      }));
      setTickets(mapped);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '加载工单失败');
    } finally {
      setLoading(false);
    }
  }, []);

  // 加载重做记录
  const loadRecords = useCallback(async () => {
    if (!STATION_ID) return;
    try {
      const res = await txFetch<{ items: RemakeRecord[] }>(
        `/api/v1/kds/remake-records?station_id=${encodeURIComponent(STATION_ID)}`,
      );
      setRecords(res.items || []);
    } catch {
      // 重做记录加载失败不阻塞主流程
    }
  }, []);

  useEffect(() => {
    loadTickets();
    loadRecords();
  }, [loadTickets, loadRecords]);

  const handleConfirmRemake = async () => {
    if (!selectedTicket || !selectedReason) return;
    setSubmitting(true);

    try {
      await remakeTicket({
        ticket_id: selectedTicket.id,
        reason: selectedReason,
        note: notes,
      });

      const reason = REASONS.find(r => r.id === selectedReason)!;
      const newRecord: RemakeRecord = {
        id: `rr${Date.now()}`,
        ticketId: selectedTicket.id,
        tableNo: selectedTicket.tableNo,
        dishName: selectedTicket.dishName,
        reason: selectedReason,
        reasonText: reason.label,
        notes,
        createdAt: Date.now(),
        status: 'remaking',
      };

      setRecords(prev => [newRecord, ...prev]);
      // 从可重做列表中移除已提交的工单
      setTickets(prev => prev.filter(t => t.id !== selectedTicket.id));
      setSelectedTicket(null);
      setSelectedReason(null);
      setNotes('');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '重做提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancel = () => {
    setSelectedTicket(null);
    setSelectedReason(null);
    setNotes('');
  };

  return (
    <div style={{
      background: '#0A0A0A', minHeight: '100vh', color: '#E0E0E0',
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
      padding: 20,
    }}>
      {/* 顶栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h1 style={{ margin: 0, fontSize: 28, color: '#FF6B35' }}>重做管理</h1>
        <span style={{ fontSize: 18, color: '#888' }}>
          今日重做 <b style={{ color: '#A32D2D', fontSize: 24 }}>{records.length}</b> 次
        </span>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 20 }}>
        <button
          onClick={() => setTab('remake')}
          style={{
            padding: '12px 28px', minHeight: 48,
            fontSize: 18, fontWeight: 'bold',
            background: tab === 'remake' ? '#A32D2D' : '#1a1a1a',
            color: tab === 'remake' ? '#fff' : '#888',
            border: 'none', borderRadius: 8, cursor: 'pointer',
          }}
        >
          发起重做
        </button>
        <button
          onClick={() => setTab('history')}
          style={{
            padding: '12px 28px', minHeight: 48,
            fontSize: 18, fontWeight: 'bold',
            background: tab === 'history' ? '#1890ff' : '#1a1a1a',
            color: tab === 'history' ? '#fff' : '#888',
            border: 'none', borderRadius: 8, cursor: 'pointer',
          }}
        >
          重做记录 ({records.length})
        </button>
      </div>

      {tab === 'remake' && !selectedTicket && (
        <>
          {/* 选择工单 */}
          <h2 style={{ fontSize: 20, color: '#888', marginBottom: 14 }}>选择需要重做的菜品</h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
            {tickets.map(t => (
              <button
                key={t.id}
                onClick={() => setSelectedTicket(t)}
                style={{
                  background: '#111', borderRadius: 12, padding: 18,
                  border: '2px solid #222', cursor: 'pointer',
                  textAlign: 'left', color: '#E0E0E0',
                  minHeight: 100,
                  transition: 'transform 200ms ease',
                }}
                onTouchStart={e => (e.currentTarget.style.transform = 'scale(0.97)')}
                onTouchEnd={e => (e.currentTarget.style.transform = 'scale(1)')}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <span style={{ fontSize: 24, fontWeight: 'bold', color: '#fff' }}>{t.tableNo}</span>
                  <span style={{ fontSize: 16, color: '#666' }}>#{t.orderNo}</span>
                </div>
                <div style={{ fontSize: 22, fontWeight: 'bold', marginBottom: 6 }}>
                  {t.dishName} <span style={{ color: '#FF6B35' }}>x{t.qty}</span>
                </div>
                <div style={{ fontSize: 16, color: '#888' }}>
                  {t.dept} | {t.originalChef}
                </div>
              </button>
            ))}
          </div>
        </>
      )}

      {/* 重做表单弹窗 */}
      {tab === 'remake' && selectedTicket && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.8)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
        }}>
          <div style={{
            background: '#111', borderRadius: 16, padding: 28, width: 500,
            maxHeight: '90vh', overflowY: 'auto',
            border: '2px solid #333',
          }}>
            {/* 工单信息 */}
            <div style={{
              background: '#1a1a1a', borderRadius: 10, padding: 16, marginBottom: 20,
              borderLeft: '6px solid #A32D2D',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                <span style={{ fontSize: 24, fontWeight: 'bold', color: '#fff' }}>{selectedTicket.tableNo}</span>
                <span style={{ fontSize: 16, color: '#666' }}>#{selectedTicket.orderNo}</span>
              </div>
              <div style={{ fontSize: 22, fontWeight: 'bold' }}>
                {selectedTicket.dishName} <span style={{ color: '#FF6B35' }}>x{selectedTicket.qty}</span>
              </div>
            </div>

            {/* 重做原因选择 */}
            <h3 style={{ fontSize: 20, color: '#fff', marginBottom: 12 }}>选择重做原因</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 20 }}>
              {REASONS.map(reason => (
                <button
                  key={reason.id}
                  onClick={() => setSelectedReason(reason.id)}
                  style={{
                    padding: '14px 18px', minHeight: 56,
                    background: selectedReason === reason.id ? `${reason.color}22` : '#1a1a1a',
                    border: selectedReason === reason.id ? `3px solid ${reason.color}` : '2px solid #222',
                    borderRadius: 10, cursor: 'pointer',
                    textAlign: 'left', color: '#E0E0E0',
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    transition: 'transform 200ms ease',
                  }}
                  onTouchStart={e => (e.currentTarget.style.transform = 'scale(0.97)')}
                  onTouchEnd={e => (e.currentTarget.style.transform = 'scale(1)')}
                >
                  <div>
                    <div style={{ fontSize: 20, fontWeight: 'bold', color: reason.color }}>{reason.label}</div>
                    <div style={{ fontSize: 16, color: '#888' }}>{reason.description}</div>
                  </div>
                  {selectedReason === reason.id && (
                    <span style={{ fontSize: 24, color: reason.color, fontWeight: 'bold' }}>
                      ✓
                    </span>
                  )}
                </button>
              ))}
            </div>

            {/* 备注 */}
            <h3 style={{ fontSize: 20, color: '#fff', marginBottom: 8 }}>备注（可选）</h3>
            <textarea
              value={notes}
              onChange={e => setNotes(e.target.value)}
              placeholder="补充说明重做原因..."
              style={{
                width: '100%', boxSizing: 'border-box', padding: '12px 14px',
                background: '#1a1a1a', color: '#fff', border: '1px solid #333',
                borderRadius: 8, fontSize: 18, minHeight: 80, resize: 'vertical',
                fontFamily: 'inherit',
              }}
            />

            {/* 操作按钮 */}
            <div style={{ display: 'flex', gap: 12, marginTop: 20 }}>
              <button
                onClick={handleConfirmRemake}
                disabled={!selectedReason || submitting}
                style={{
                  flex: 1, padding: '14px 0',
                  background: selectedReason ? '#A32D2D' : '#333',
                  color: '#fff', border: 'none', borderRadius: 8,
                  cursor: !selectedReason || submitting ? 'not-allowed' : 'pointer',
                  fontSize: 20, fontWeight: 'bold', minHeight: 56,
                  opacity: !selectedReason || submitting ? 0.5 : 1,
                  transition: 'transform 200ms ease',
                }}
                onTouchStart={e => {
                  if (selectedReason && !submitting) e.currentTarget.style.transform = 'scale(0.97)';
                }}
                onTouchEnd={e => (e.currentTarget.style.transform = 'scale(1)')}
              >
                {submitting ? '提交中...' : '确认重做'}
              </button>
              <button
                onClick={handleCancel}
                style={{
                  flex: 1, padding: '14px 0', background: '#222', color: '#888',
                  border: 'none', borderRadius: 8, cursor: 'pointer',
                  fontSize: 20, minHeight: 56,
                }}
              >
                取消
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 重做记录 */}
      {tab === 'history' && (
        <div>
          {records.length === 0 && (
            <div style={{ textAlign: 'center', padding: 60, color: '#666', fontSize: 20 }}>
              暂无重做记录
            </div>
          )}
          {records.map(r => {
            const reason = REASONS.find(rr => rr.id === r.reason);
            return (
              <div key={r.id} style={{
                background: '#111', borderRadius: 10, padding: 16, marginBottom: 10,
                borderLeft: `5px solid ${reason?.color || '#666'}`,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span style={{ fontSize: 22, fontWeight: 'bold', color: '#fff' }}>{r.tableNo}</span>
                    <span style={{ fontSize: 20 }}>{r.dishName}</span>
                  </div>
                  <span style={{
                    fontSize: 16, padding: '4px 12px', borderRadius: 6,
                    background: r.status === 'remaking' ? '#BA751722' : '#0F6E5622',
                    color: r.status === 'remaking' ? '#BA7517' : '#0F6E56',
                    fontWeight: 'bold',
                  }}>
                    {r.status === 'remaking' ? '重做中' : '已完成'}
                  </span>
                </div>
                <div style={{ display: 'flex', gap: 12, fontSize: 16, color: '#888' }}>
                  <span style={{ color: reason?.color, fontWeight: 'bold' }}>{r.reasonText}</span>
                  {r.notes && <span>| {r.notes}</span>}
                </div>
                <div style={{ fontSize: 16, color: '#555', marginTop: 4 }}>
                  {new Date(r.createdAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
