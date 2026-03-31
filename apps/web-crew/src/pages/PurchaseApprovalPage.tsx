/**
 * 采购审批 — 店长/采购经理移动端审批采购申请
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B35',
  green: '#22c55e',
  red: '#ef4444',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
};

interface PurchaseRequest {
  id: string;
  requester_name: string;
  items_summary: string;
  estimated_amount: number;
  created_at: string;
  notes: string | null;
  status: 'pending' | 'approved' | 'rejected';
}

const MOCK_REQUESTS: PurchaseRequest[] = [
  {
    id: 'po_001',
    requester_name: '张厨师长',
    items_summary: '鲈鱼 20kg / 土豆 50kg / 猪里脊 15kg',
    estimated_amount: 1280,
    created_at: '2026-03-31T08:30:00+08:00',
    notes: '明日宴席备货，请尽快审批',
    status: 'pending',
  },
  {
    id: 'po_002',
    requester_name: '李仓管',
    items_summary: '鸡蛋 200个',
    estimated_amount: 160,
    created_at: '2026-03-31T09:15:00+08:00',
    notes: null,
    status: 'pending',
  },
  {
    id: 'po_003',
    requester_name: '王采购',
    items_summary: '菜籽油 20L / 生抽 10瓶',
    estimated_amount: 380,
    created_at: '2026-03-30T14:20:00+08:00',
    notes: null,
    status: 'approved',
  },
];

interface RejectModalProps {
  onConfirm: (comment: string) => void;
  onCancel: () => void;
}

function RejectModal({ onConfirm, onCancel }: RejectModalProps) {
  const [comment, setComment] = useState('');
  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
      display: 'flex', alignItems: 'flex-end', zIndex: 100,
    }}>
      <div style={{
        background: C.card, borderRadius: '16px 16px 0 0', padding: 24,
        width: '100%', boxSizing: 'border-box',
      }}>
        <div style={{ fontSize: 18, fontWeight: 700, color: C.white, marginBottom: 16 }}>拒绝原因</div>
        <textarea
          placeholder="请填写拒绝原因（可选）"
          value={comment}
          onChange={e => setComment(e.target.value)}
          rows={3}
          style={{
            width: '100%', boxSizing: 'border-box', resize: 'none',
            background: '#0B1A20', border: `1px solid ${C.border}`,
            borderRadius: 10, padding: 14,
            fontSize: 16, color: C.white, outline: 'none',
            marginBottom: 16,
          }}
        />
        <div style={{ display: 'flex', gap: 12 }}>
          <button
            onClick={onCancel}
            style={{
              flex: 1, height: 52,
              background: C.border, border: 'none', borderRadius: 12,
              fontSize: 17, color: C.text, cursor: 'pointer',
            }}
          >
            取消
          </button>
          <button
            onClick={() => onConfirm(comment)}
            style={{
              flex: 2, height: 52,
              background: C.red, border: 'none', borderRadius: 12,
              fontSize: 17, fontWeight: 700, color: C.white, cursor: 'pointer',
            }}
          >
            确认拒绝
          </button>
        </div>
      </div>
    </div>
  );
}

function formatDate(iso: string) {
  const d = new Date(iso);
  return `${d.getMonth() + 1}月${d.getDate()}日 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function statusBadge(status: PurchaseRequest['status']) {
  if (status === 'approved') return { label: '已批准', color: C.green };
  if (status === 'rejected') return { label: '已拒绝', color: C.red };
  return { label: '待审批', color: C.accent };
}

export function PurchaseApprovalPage() {
  const navigate = useNavigate();
  const [requests, setRequests] = useState<PurchaseRequest[]>(MOCK_REQUESTS);
  const [rejectTarget, setRejectTarget] = useState<string | null>(null);

  const pendingCount = requests.filter(r => r.status === 'pending').length;

  const handleApprove = (id: string) => {
    setRequests(prev => prev.map(r => r.id === id ? { ...r, status: 'approved' } : r));
  };

  const handleReject = (id: string, comment: string) => {
    setRequests(prev => prev.map(r => r.id === id ? { ...r, status: 'rejected' } : r));
    setRejectTarget(null);
  };

  return (
    <div style={{ background: C.bg, minHeight: '100vh', color: C.white }}>
      {/* 顶栏 */}
      <div style={{
        position: 'sticky', top: 0, zIndex: 10,
        background: C.bg, borderBottom: `1px solid ${C.border}`,
        display: 'flex', alignItems: 'center', padding: '0 16px', height: 56,
      }}>
        <button onClick={() => navigate(-1)} style={{
          background: 'none', border: 'none', color: C.text, fontSize: 22,
          cursor: 'pointer', padding: '8px 8px 8px 0', minWidth: 48, minHeight: 48,
          display: 'flex', alignItems: 'center',
        }}>←</button>
        <span style={{ flex: 1, fontSize: 17, fontWeight: 700, color: C.white }}>采购审批</span>
        {pendingCount > 0 && (
          <span style={{
            background: C.red, borderRadius: 12, padding: '2px 10px',
            fontSize: 13, fontWeight: 700, color: C.white,
          }}>
            {pendingCount}条待处理
          </span>
        )}
      </div>

      {/* 列表 */}
      <div style={{ padding: '12px 16px 32px' }}>
        {requests.map(req => {
          const badge = statusBadge(req.status);
          return (
            <div key={req.id} style={{
              background: C.card, borderRadius: 14, padding: 16, marginBottom: 14,
              border: `1px solid ${req.status === 'pending' ? C.border : badge.color + '40'}`,
              opacity: req.status === 'pending' ? 1 : 0.75,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
                <div>
                  <span style={{ fontSize: 16, fontWeight: 700, color: C.white }}>
                    申请人：{req.requester_name}
                  </span>
                  <span style={{
                    marginLeft: 10, fontSize: 12, padding: '2px 8px',
                    background: badge.color + '22', color: badge.color,
                    borderRadius: 6, fontWeight: 600,
                  }}>
                    {badge.label}
                  </span>
                </div>
                <span style={{ fontSize: 13, color: C.muted }}>{formatDate(req.created_at)}</span>
              </div>

              <div style={{ fontSize: 15, color: C.text, marginBottom: 8 }}>
                {req.items_summary}
              </div>

              <div style={{
                fontSize: 18, fontWeight: 800, color: C.accent, marginBottom: req.notes ? 8 : 0,
              }}>
                预计金额：¥{req.estimated_amount.toLocaleString()}
              </div>

              {req.notes && (
                <div style={{ fontSize: 13, color: C.muted, marginBottom: 12 }}>
                  备注：{req.notes}
                </div>
              )}

              {req.status === 'pending' && (
                <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
                  <button
                    onClick={() => setRejectTarget(req.id)}
                    style={{
                      flex: 1, height: 48,
                      background: 'transparent', border: `1px solid ${C.red}`,
                      borderRadius: 10, fontSize: 16, fontWeight: 600, color: C.red,
                      cursor: 'pointer',
                    }}
                  >
                    拒绝
                  </button>
                  <button
                    onClick={() => handleApprove(req.id)}
                    style={{
                      flex: 2, height: 48,
                      background: C.green, border: 'none',
                      borderRadius: 10, fontSize: 16, fontWeight: 700, color: C.white,
                      cursor: 'pointer',
                    }}
                  >
                    批准 ✓
                  </button>
                </div>
              )}
            </div>
          );
        })}

        {requests.length === 0 && (
          <div style={{ textAlign: 'center', padding: '60px 0', color: C.muted, fontSize: 16 }}>
            暂无采购审批申请
          </div>
        )}
      </div>

      {rejectTarget && (
        <RejectModal
          onConfirm={comment => handleReject(rejectTarget, comment)}
          onCancel={() => setRejectTarget(null)}
        />
      )}
    </div>
  );
}
