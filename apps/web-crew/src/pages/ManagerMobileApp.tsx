import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';

const MC = {
  bg: '#060C10',
  card: '#0E1A22',
  border: '#152430',
  text: '#E8EDF0',
  muted: '#5A7080',
  primary: '#FF6B35',
  success: '#30D158',
  warning: '#FF9F0A',
  danger: '#FF3B30',
  info: '#1A9BE8',
};

const API_BASE = '/api/v1/manager';
const APPROVAL_API = '/api/v1';

// ---------- Types ----------

interface KpiData {
  revenue: number;
  revenue_vs_yesterday: number;
  order_count: number;
  avg_check: number;
  table_turns: number;
  guest_count: number;
  labor_cost_pct: number;
  on_table_count: number;
  free_table_count: number;
}

interface Alert {
  id: string;
  type: string;
  severity: 'info' | 'warning' | 'critical';
  message: string;
  created_at: string;
  is_read: boolean;
}

interface DiscountRequest {
  id: string;
  applicant: string;
  applicant_role: string;
  table: string;
  discount_type: string;
  discount_amount: number;
  reason: string;
  created_at: string;
  status: string;
}

interface StaffMember {
  id: string;
  name: string;
  role: string;
  status: string;
  table_count: number;
}

// ---------- Mock Fallback ----------

const MOCK_KPI: KpiData = {
  revenue: 2845000,
  revenue_vs_yesterday: 13.2,
  order_count: 142,
  avg_check: 20035,
  table_turns: 3.2,
  guest_count: 368,
  labor_cost_pct: 22.4,
  on_table_count: 8,
  free_table_count: 5,
};

const MOCK_ALERTS: Alert[] = [
  {
    id: 'alert-001', type: 'overtime_table', severity: 'critical',
    message: 'A03桌就餐已71分钟，建议催结账', created_at: new Date().toISOString(), is_read: false,
  },
  {
    id: 'alert-002', type: 'low_margin', severity: 'warning',
    message: '热菜档毛利率跌至43%，低于设定阈值50%', created_at: new Date().toISOString(), is_read: false,
  },
  {
    id: 'alert-003', type: 'complaint', severity: 'critical',
    message: 'B07桌客诉：等待上菜超过40分钟', created_at: new Date().toISOString(), is_read: false,
  },
];

const MOCK_DISCOUNT_REQUESTS: DiscountRequest[] = [
  {
    id: 'disc-001', applicant: '李四', applicant_role: '服务员', table: 'A03桌',
    discount_type: '整单9折', discount_amount: 2850, reason: '顾客等待时间较长，超过30分钟',
    created_at: new Date().toISOString(), status: 'pending',
  },
  {
    id: 'disc-002', applicant: '王五', applicant_role: '服务员', table: 'C12桌',
    discount_type: '赠送甜品', discount_amount: 380, reason: '庆生活动，顾客VIP会员',
    created_at: new Date().toISOString(), status: 'pending',
  },
];

const MOCK_STAFF: StaffMember[] = [
  { id: 'staff-001', name: '张三', role: '服务员', status: 'on_duty', table_count: 3 },
  { id: 'staff-002', name: '李四', role: '服务员', status: 'on_duty', table_count: 4 },
  { id: 'staff-003', name: '王五', role: '服务员', status: 'on_duty', table_count: 2 },
  { id: 'staff-004', name: '赵六', role: '收银员', status: 'on_duty', table_count: 0 },
  { id: 'staff-005', name: '陈七', role: '传菜员', status: 'on_duty', table_count: 0 },
];

// ---------- Helpers ----------

function fmtYuan(fen: number): string {
  return '¥' + (fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

function alertSeverityStyle(severity: Alert['severity']): { bg: string; icon: string; border: string } {
  if (severity === 'critical') return { bg: `${MC.danger}18`, icon: '🔴', border: MC.danger };
  if (severity === 'warning') return { bg: `${MC.warning}18`, icon: '🟡', border: MC.warning };
  return { bg: `${MC.info}18`, icon: 'ℹ️', border: MC.info };
}

// ---------- DiscountApprovalModal ----------

interface DiscountApprovalModalProps {
  request: DiscountRequest;
  onClose: () => void;
  onApprove: (id: string, approved: boolean, reason?: string) => Promise<void>;
}

function DiscountApprovalModal({ request, onClose, onApprove }: DiscountApprovalModalProps) {
  const [reason, setReason] = useState('');
  const [loading, setLoading] = useState(false);

  const handle = async (approved: boolean) => {
    setLoading(true);
    await onApprove(request.id, approved, reason || undefined);
    setLoading(false);
    onClose();
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)',
      display: 'flex', alignItems: 'flex-end', justifyContent: 'center', zIndex: 200,
    }}
      onClick={onClose}
    >
      <div
        style={{
          width: '100%', maxWidth: 480, background: MC.card, borderRadius: '16px 16px 0 0',
          padding: 24, paddingBottom: 36, border: `1px solid ${MC.border}`,
        }}
        onClick={e => e.stopPropagation()}
      >
        <div style={{ fontSize: 18, fontWeight: 700, color: MC.text, marginBottom: 20 }}>
          收到折扣申请
        </div>

        {[
          { label: '申请人', value: `${request.applicant}（${request.applicant_role}）` },
          { label: '桌台', value: request.table },
          { label: '折扣类型', value: request.discount_type },
          { label: '折扣金额', value: fmtYuan(request.discount_amount) },
          { label: '原因', value: request.reason },
        ].map(row => (
          <div key={row.label} style={{
            display: 'flex', gap: 12, paddingBottom: 10, marginBottom: 10,
            borderBottom: `1px solid ${MC.border}`,
          }}>
            <span style={{ color: MC.muted, fontSize: 15, minWidth: 64 }}>{row.label}</span>
            <span style={{ color: MC.text, fontSize: 15, flex: 1 }}>{row.value}</span>
          </div>
        ))}

        <textarea
          placeholder="备注（可选）"
          value={reason}
          onChange={e => setReason(e.target.value)}
          style={{
            width: '100%', minHeight: 72, background: MC.bg, border: `1px solid ${MC.border}`,
            borderRadius: 8, color: MC.text, fontSize: 15, padding: '10px 12px',
            resize: 'none', marginTop: 8, boxSizing: 'border-box',
          }}
        />

        <div style={{ display: 'flex', gap: 12, marginTop: 16 }}>
          <button
            disabled={loading}
            onClick={() => handle(false)}
            style={{
              flex: 1, height: 52, borderRadius: 10, border: `1px solid ${MC.danger}`,
              background: 'transparent', color: MC.danger, fontSize: 17, fontWeight: 600,
              cursor: loading ? 'not-allowed' : 'pointer',
            }}
          >
            拒绝
          </button>
          <button
            disabled={loading}
            onClick={() => handle(true)}
            style={{
              flex: 1, height: 52, borderRadius: 10, border: 'none',
              background: MC.success, color: '#fff', fontSize: 17, fontWeight: 600,
              cursor: loading ? 'not-allowed' : 'pointer',
            }}
          >
            批准
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------- BroadcastModal ----------

interface BroadcastModalProps {
  storeId: string;
  onClose: () => void;
}

function BroadcastModal({ storeId, onClose }: BroadcastModalProps) {
  const [message, setMessage] = useState('');
  const [target, setTarget] = useState<'all' | 'crew' | 'kitchen'>('all');
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);

  const handleSend = async () => {
    if (!message.trim()) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/broadcast-message`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ store_id: storeId, message: message.trim(), target }),
      });
      if (res.ok) setSent(true);
    } catch {
      setSent(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)',
      display: 'flex', alignItems: 'flex-end', justifyContent: 'center', zIndex: 200,
    }}
      onClick={onClose}
    >
      <div
        style={{
          width: '100%', maxWidth: 480, background: MC.card, borderRadius: '16px 16px 0 0',
          padding: 24, paddingBottom: 36, border: `1px solid ${MC.border}`,
        }}
        onClick={e => e.stopPropagation()}
      >
        {sent ? (
          <div style={{ textAlign: 'center', padding: '24px 0' }}>
            <div style={{ fontSize: 40, marginBottom: 12 }}>✅</div>
            <div style={{ color: MC.success, fontSize: 18, fontWeight: 600 }}>消息已发送</div>
            <button
              onClick={onClose}
              style={{
                marginTop: 20, height: 48, width: '100%', borderRadius: 10,
                background: MC.primary, border: 'none', color: '#fff', fontSize: 16, cursor: 'pointer',
              }}
            >
              关闭
            </button>
          </div>
        ) : (
          <>
            <div style={{ fontSize: 18, fontWeight: 700, color: MC.text, marginBottom: 16 }}>
              📢 推送消息
            </div>

            <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
              {([['all', '全体'], ['crew', '服务员'], ['kitchen', '厨房']] as const).map(([val, label]) => (
                <button
                  key={val}
                  onClick={() => setTarget(val)}
                  style={{
                    flex: 1, height: 40, borderRadius: 8, fontSize: 15,
                    border: `1px solid ${target === val ? MC.primary : MC.border}`,
                    background: target === val ? `${MC.primary}22` : 'transparent',
                    color: target === val ? MC.primary : MC.muted,
                    cursor: 'pointer',
                  }}
                >
                  {label}
                </button>
              ))}
            </div>

            <textarea
              placeholder="输入消息内容..."
              value={message}
              onChange={e => setMessage(e.target.value)}
              style={{
                width: '100%', minHeight: 100, background: MC.bg, border: `1px solid ${MC.border}`,
                borderRadius: 8, color: MC.text, fontSize: 16, padding: '12px',
                resize: 'none', boxSizing: 'border-box',
              }}
            />

            <button
              disabled={loading || !message.trim()}
              onClick={handleSend}
              style={{
                marginTop: 16, height: 52, width: '100%', borderRadius: 10, border: 'none',
                background: message.trim() ? MC.primary : MC.border,
                color: '#fff', fontSize: 17, fontWeight: 600,
                cursor: message.trim() ? 'pointer' : 'not-allowed',
              }}
            >
              {loading ? '发送中...' : '发送'}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

// ---------- AlertDetailModal ----------

interface AlertDetailModalProps {
  alert: Alert;
  onClose: () => void;
  onRead: (id: string) => void;
}

function AlertDetailModal({ alert, onClose, onRead }: AlertDetailModalProps) {
  const style = alertSeverityStyle(alert.severity);

  const handleRead = () => {
    onRead(alert.id);
    onClose();
  };

  const severityLabel = { critical: '紧急', warning: '警告', info: '提示' }[alert.severity];

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      zIndex: 200, padding: 20,
    }}
      onClick={onClose}
    >
      <div
        style={{
          width: '100%', maxWidth: 400, background: MC.card, borderRadius: 16,
          padding: 24, border: `1px solid ${style.border}`,
        }}
        onClick={e => e.stopPropagation()}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
          <span style={{ fontSize: 24 }}>{style.icon}</span>
          <span style={{
            fontSize: 13, fontWeight: 600, padding: '3px 10px', borderRadius: 20,
            background: style.bg, color: style.border, border: `1px solid ${style.border}`,
          }}>
            {severityLabel}
          </span>
        </div>
        <div style={{ fontSize: 16, color: MC.text, lineHeight: 1.6, marginBottom: 20 }}>
          {alert.message}
        </div>
        <div style={{ fontSize: 13, color: MC.muted, marginBottom: 20 }}>
          {new Date(alert.created_at).toLocaleString('zh-CN')}
        </div>
        <button
          onClick={handleRead}
          style={{
            width: '100%', height: 48, borderRadius: 10, border: 'none',
            background: MC.primary, color: '#fff', fontSize: 16, fontWeight: 600, cursor: 'pointer',
          }}
        >
          标记已处理
        </button>
      </div>
    </div>
  );
}

// ---------- Main Component ----------

export function ManagerMobileApp() {
  const navigate = useNavigate();
  const role = (window as any).__STAFF_ROLE__;
  const storeId = (window as any).__STORE_ID__ || '';
  const storeName = (window as any).__STORE_NAME__ || '尝在一起·万达店';

  const [period, setPeriod] = useState<'today' | 'week' | 'month'>('today');
  const [kpi, setKpi] = useState<KpiData>(MOCK_KPI);
  const [alerts, setAlerts] = useState<Alert[]>(MOCK_ALERTS);
  const [staff, setStaff] = useState<StaffMember[]>(MOCK_STAFF);
  const [discountRequests, setDiscountRequests] = useState<DiscountRequest[]>(MOCK_DISCOUNT_REQUESTS);

  const [pendingApprovalCount, setPendingApprovalCount] = useState(0);

  const [selectedAlert, setSelectedAlert] = useState<Alert | null>(null);
  const [selectedDiscount, setSelectedDiscount] = useState<DiscountRequest | null>(null);
  const [showBroadcast, setShowBroadcast] = useState(false);
  const [showAllAlerts, setShowAllAlerts] = useState(false);

  const fetchKpi = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/realtime-kpi?store_id=${storeId}&period=${period}`);
      if (res.ok) {
        const json = await res.json();
        if (json.ok) setKpi(json.data);
      }
    } catch {
      // mock fallback already set
    }
  }, [storeId, period]);

  const fetchAlerts = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/alerts?store_id=${storeId}`);
      if (res.ok) {
        const json = await res.json();
        if (json.ok) setAlerts(json.data);
      }
    } catch {
      // mock fallback
    }
  }, [storeId]);

  const fetchStaff = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/staff-online?store_id=${storeId}`);
      if (res.ok) {
        const json = await res.json();
        if (json.ok) setStaff(json.data);
      }
    } catch {
      // mock fallback
    }
  }, [storeId]);

  const fetchDiscountRequests = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/discount-requests?store_id=${storeId}`);
      if (res.ok) {
        const json = await res.json();
        if (json.ok) setDiscountRequests(json.data);
      }
    } catch {
      // mock fallback
    }
  }, [storeId]);

  const staffId = (window as any).__STAFF_ID__ || '';
  const fetchPendingApprovalCount = useCallback(async () => {
    if (!staffId) return;
    try {
      const res = await fetch(
        `${APPROVAL_API}/approvals/pending-count?approver_id=${encodeURIComponent(staffId)}`,
        { headers: { 'X-Tenant-ID': (window as any).__TENANT_ID__ || '' } },
      );
      if (res.ok) {
        const json = await res.json();
        if (json.ok) setPendingApprovalCount(json.data?.count ?? 0);
      }
    } catch {
      // 网络失败时保留上次值
    }
  }, [staffId]);

  const refreshAll = useCallback(() => {
    fetchKpi();
    fetchAlerts();
    fetchStaff();
    fetchDiscountRequests();
    fetchPendingApprovalCount();
  }, [fetchKpi, fetchAlerts, fetchStaff, fetchDiscountRequests, fetchPendingApprovalCount]);

  useEffect(() => {
    refreshAll();
  }, [refreshAll]);

  useEffect(() => {
    const kpiTimer = setInterval(fetchKpi, 30_000);
    const alertTimer = setInterval(fetchAlerts, 10_000);
    const approvalTimer = setInterval(fetchPendingApprovalCount, 30_000);
    return () => {
      clearInterval(kpiTimer);
      clearInterval(alertTimer);
      clearInterval(approvalTimer);
    };
  }, [fetchKpi, fetchAlerts, fetchPendingApprovalCount]);

  const handleMarkAlertRead = async (id: string) => {
    try {
      await fetch(`${API_BASE}/alerts/${id}/read`, { method: 'POST' });
    } catch {
      // ignore
    }
    setAlerts(prev => prev.map(a => a.id === id ? { ...a, is_read: true } : a));
  };

  const handleApproveDiscount = async (reqId: string, approved: boolean, reason?: string) => {
    try {
      await fetch(`${API_BASE}/discount/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request_id: reqId, approved, reason }),
      });
    } catch {
      // ignore
    }
    setDiscountRequests(prev =>
      prev.map(r => r.id === reqId ? { ...r, status: approved ? 'approved' : 'rejected' } : r)
    );
  };

  if (role !== 'manager' && role !== 'owner') {
    return (
      <div style={{
        minHeight: '100vh', background: MC.bg, display: 'flex',
        flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        color: MC.muted, gap: 16, padding: 24,
      }}>
        <div style={{ fontSize: 48 }}>🔒</div>
        <div style={{ fontSize: 20, fontWeight: 700, color: MC.text }}>权限不足</div>
        <div style={{ fontSize: 15, textAlign: 'center' }}>管理驾驶舱仅限店长或老板访问</div>
        <button
          onClick={() => navigate('/profile')}
          style={{
            marginTop: 8, height: 48, padding: '0 32px', borderRadius: 10,
            background: MC.primary, border: 'none', color: '#fff', fontSize: 16, cursor: 'pointer',
          }}
        >
          返回
        </button>
      </div>
    );
  }

  const unreadAlerts = alerts.filter(a => !a.is_read);
  const visibleAlerts = showAllAlerts ? unreadAlerts : unreadAlerts.slice(0, 3);
  const pendingDiscounts = discountRequests.filter(r => r.status === 'pending');
  const complaints = unreadAlerts.filter(a => a.type === 'complaint');
  const totalTables = kpi.on_table_count + kpi.free_table_count;
  const pendingCheckout = Math.max(0, Math.round(kpi.on_table_count * 0.2));

  return (
    <div style={{ minHeight: '100vh', background: MC.bg, color: MC.text, fontFamily: 'system-ui, sans-serif', paddingBottom: 24 }}>

      {/* Top Bar */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '12px 16px', background: MC.card, borderBottom: `1px solid ${MC.border}`,
        position: 'sticky', top: 0, zIndex: 100,
      }}>
        <button
          onClick={() => navigate('/profile')}
          style={{
            minWidth: 48, minHeight: 48, display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: 'transparent', border: 'none', color: MC.text, fontSize: 20, cursor: 'pointer',
          }}
        >
          ←
        </button>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 16, fontWeight: 700, color: MC.text }}>管理驾驶舱</span>
          {unreadAlerts.length > 0 && (
            <span style={{
              background: MC.danger, color: '#fff', fontSize: 12, fontWeight: 700,
              borderRadius: 10, padding: '1px 7px', minWidth: 20, textAlign: 'center',
            }}>
              {unreadAlerts.length}
            </span>
          )}
        </div>
        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <span style={{
            fontSize: 14, color: MC.muted, padding: '6px 10px', background: `${MC.border}80`,
            borderRadius: 8, border: `1px solid ${MC.border}`,
          }}>
            {storeName} ▾
          </span>
          <button
            onClick={refreshAll}
            style={{
              minWidth: 48, minHeight: 48, display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: 'transparent', border: 'none', color: MC.muted, fontSize: 18, cursor: 'pointer',
            }}
          >
            ↻
          </button>
        </div>
      </div>

      <div style={{ padding: '0 12px' }}>

        {/* Agent Alert Section */}
        {unreadAlerts.length > 0 && (
          <div style={{ marginTop: 14 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: MC.muted, marginBottom: 8, letterSpacing: 0.5 }}>
              ⚠️ Agent预警
            </div>
            {visibleAlerts.map(alert => {
              const s = alertSeverityStyle(alert.severity);
              return (
                <div
                  key={alert.id}
                  onClick={() => setSelectedAlert(alert)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 10,
                    background: s.bg, border: `1px solid ${s.border}40`,
                    borderLeft: `3px solid ${s.border}`,
                    borderRadius: 8, padding: '10px 12px', marginBottom: 6,
                    cursor: 'pointer',
                  }}
                >
                  <span style={{ fontSize: 16 }}>{s.icon}</span>
                  <span style={{ fontSize: 15, color: MC.text, flex: 1, lineHeight: 1.4 }}>
                    {alert.message}
                  </span>
                  <span style={{ fontSize: 18, color: MC.muted }}>›</span>
                </div>
              );
            })}
            {unreadAlerts.length > 3 && (
              <button
                onClick={() => setShowAllAlerts(v => !v)}
                style={{
                  width: '100%', padding: '8px 0', background: 'transparent',
                  border: `1px solid ${MC.border}`, borderRadius: 8,
                  color: MC.primary, fontSize: 14, cursor: 'pointer', marginTop: 2,
                }}
              >
                {showAllAlerts ? '收起' : `查看全部 ${unreadAlerts.length} 条预警`}
              </button>
            )}
          </div>
        )}

        {/* Period Tabs */}
        <div style={{ display: 'flex', gap: 6, marginTop: 16, marginBottom: 4 }}>
          {(['today', 'week', 'month'] as const).map((p, i) => {
            const labels = ['今日', '本周', '本月'];
            return (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                style={{
                  height: 34, padding: '0 14px', borderRadius: 8, fontSize: 14,
                  border: `1px solid ${period === p ? MC.primary : MC.border}`,
                  background: period === p ? `${MC.primary}22` : 'transparent',
                  color: period === p ? MC.primary : MC.muted,
                  cursor: 'pointer',
                }}
              >
                {labels[i]}
              </button>
            );
          })}
        </div>

        {/* Revenue Card */}
        <div style={{
          background: MC.card, border: `1px solid ${MC.border}`, borderRadius: 12,
          padding: '16px 16px 12px', marginTop: 8,
        }}>
          <div style={{ fontSize: 13, color: MC.muted, marginBottom: 4 }}>营业额</div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
            <span style={{ fontSize: 32, fontWeight: 700, color: MC.text }}>
              {fmtYuan(kpi.revenue)}
            </span>
            <span style={{
              fontSize: 15, fontWeight: 600,
              color: kpi.revenue_vs_yesterday >= 0 ? MC.success : MC.danger,
            }}>
              {kpi.revenue_vs_yesterday >= 0 ? '+' : ''}{kpi.revenue_vs_yesterday.toFixed(1)}%↑
            </span>
          </div>
          <div style={{ fontSize: 13, color: MC.muted, marginBottom: 14 }}>较昨日同期</div>

          <div style={{
            display: 'grid', gridTemplateColumns: '1fr 1fr 1fr',
            border: `1px solid ${MC.border}`, borderRadius: 10, overflow: 'hidden',
          }}>
            {[
              { label: '客流量', value: kpi.guest_count.toString(), unit: '人' },
              { label: '客单价', value: fmtYuan(kpi.avg_check), unit: '' },
              { label: '翻台率', value: kpi.table_turns.toFixed(1) + '×', unit: '' },
            ].map((item, idx) => (
              <div key={item.label} style={{
                textAlign: 'center', padding: '12px 8px',
                borderLeft: idx > 0 ? `1px solid ${MC.border}` : 'none',
              }}>
                <div style={{ fontSize: 20, fontWeight: 700, color: MC.text }}>{item.value}</div>
                <div style={{ fontSize: 12, color: MC.muted, marginTop: 3 }}>{item.label}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Table Status */}
        <div style={{
          background: MC.card, border: `1px solid ${MC.border}`, borderRadius: 12,
          padding: '14px 16px', marginTop: 10,
        }}>
          <div style={{ fontSize: 15, fontWeight: 600, color: MC.text, marginBottom: 10 }}>桌台状态</div>
          <div style={{ fontSize: 13, color: MC.muted, marginBottom: 10 }}>
            在台 <span style={{ color: MC.warning, fontWeight: 600 }}>{kpi.on_table_count}桌</span>
            &nbsp;·&nbsp;
            空台 <span style={{ color: MC.success, fontWeight: 600 }}>{kpi.free_table_count}桌</span>
            &nbsp;·&nbsp;
            待结账 <span style={{ color: MC.danger, fontWeight: 600 }}>{pendingCheckout}桌</span>
          </div>
          <div style={{ height: 12, background: MC.border, borderRadius: 6, overflow: 'hidden' }}>
            <div style={{
              height: '100%', borderRadius: 6,
              width: `${totalTables > 0 ? (kpi.on_table_count / totalTables) * 100 : 0}%`,
              background: `linear-gradient(90deg, ${MC.primary}, ${MC.warning})`,
            }} />
          </div>
          <div style={{ fontSize: 12, color: MC.muted, marginTop: 6 }}>
            {kpi.on_table_count}/{totalTables}桌在用（满座率{totalTables > 0 ? Math.round(kpi.on_table_count / totalTables * 100) : 0}%）
          </div>
        </div>

        {/* Staff Online */}
        <div style={{
          background: MC.card, border: `1px solid ${MC.border}`, borderRadius: 12,
          padding: '14px 16px', marginTop: 10,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
            <span style={{ fontSize: 15, fontWeight: 600, color: MC.text }}>在班员工</span>
            <span style={{ fontSize: 14, color: MC.success, fontWeight: 600 }}>{staff.length}人</span>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {staff.map(s => (
              <div key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <span style={{
                  width: 8, height: 8, borderRadius: '50%',
                  background: s.status === 'on_duty' ? MC.success : MC.muted,
                  flexShrink: 0,
                }} />
                <span style={{ fontSize: 15, color: MC.text }}>{s.name}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Pending Tasks */}
        <div style={{
          background: MC.card, border: `1px solid ${MC.border}`, borderRadius: 12,
          padding: '14px 16px', marginTop: 10,
        }}>
          <div style={{ fontSize: 15, fontWeight: 600, color: MC.text, marginBottom: 10 }}>待处理事项</div>

          {pendingApprovalCount > 0 && (
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '10px 0', borderBottom: `1px solid ${MC.border}`,
            }}>
              <span style={{ fontSize: 15, color: MC.text, display: 'flex', alignItems: 'center', gap: 6 }}>
                ✅ 待审批事项
                <span style={{
                  background: MC.warning, color: '#fff', fontSize: 12, fontWeight: 700,
                  borderRadius: 10, padding: '1px 7px', minWidth: 20, textAlign: 'center',
                }}>
                  {pendingApprovalCount}
                </span>
              </span>
              <button
                onClick={() => navigate(`/approvals?approver_id=${encodeURIComponent(staffId)}`)}
                style={{
                  minHeight: 36, padding: '0 16px', borderRadius: 8,
                  background: MC.warning, border: 'none', color: '#fff',
                  fontSize: 14, fontWeight: 600, cursor: 'pointer',
                }}
              >
                处理
              </button>
            </div>
          )}

          {pendingDiscounts.length > 0 && (
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '10px 0', borderBottom: `1px solid ${MC.border}`,
            }}>
              <span style={{ fontSize: 15, color: MC.text }}>
                📋 折扣审批请求 <span style={{ color: MC.warning }}>({pendingDiscounts.length}条)</span>
              </span>
              <button
                onClick={() => setSelectedDiscount(pendingDiscounts[0])}
                style={{
                  minHeight: 36, padding: '0 16px', borderRadius: 8,
                  background: MC.primary, border: 'none', color: '#fff',
                  fontSize: 14, fontWeight: 600, cursor: 'pointer',
                }}
              >
                处理
              </button>
            </div>
          )}

          {complaints.length > 0 && (
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '10px 0',
            }}>
              <span style={{ fontSize: 15, color: MC.text }}>
                💬 客诉未处理 <span style={{ color: MC.danger }}>({complaints.length}条)</span>
              </span>
              <button
                onClick={() => setSelectedAlert(complaints[0])}
                style={{
                  minHeight: 36, padding: '0 16px', borderRadius: 8,
                  background: `${MC.danger}22`, border: `1px solid ${MC.danger}`,
                  color: MC.danger, fontSize: 14, fontWeight: 600, cursor: 'pointer',
                }}
              >
                查看
              </button>
            </div>
          )}

          {pendingApprovalCount === 0 && pendingDiscounts.length === 0 && complaints.length === 0 && (
            <div style={{ color: MC.muted, fontSize: 15, textAlign: 'center', padding: '8px 0' }}>
              暂无待处理事项 ✓
            </div>
          )}
        </div>

        {/* Quick Actions */}
        <div style={{
          background: MC.card, border: `1px solid ${MC.border}`, borderRadius: 12,
          padding: '14px 16px', marginTop: 10,
        }}>
          <div style={{ fontSize: 15, fontWeight: 600, color: MC.text, marginBottom: 12 }}>快捷操作</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            {[
              {
                icon: '📢', label: '推送消息', color: MC.info,
                action: () => setShowBroadcast(true),
              },
              {
                icon: '🔒', label: '锁定设备', color: MC.warning,
                action: () => alert('设备锁定功能即将上线'),
              },
              {
                icon: '📊', label: '查报表', color: MC.success,
                action: () => navigate('/review'),
              },
              {
                icon: '⚙️', label: '设置', color: MC.muted,
                action: () => navigate('/profile'),
              },
            ].map(btn => (
              <button
                key={btn.label}
                onClick={btn.action}
                style={{
                  minHeight: 72, borderRadius: 12,
                  border: `1px solid ${btn.color}40`,
                  background: `${btn.color}10`,
                  color: MC.text, fontSize: 15, fontWeight: 600,
                  cursor: 'pointer', display: 'flex',
                  flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 6,
                }}
              >
                <span style={{ fontSize: 24 }}>{btn.icon}</span>
                <span>{btn.label}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Labor Cost Footer */}
        <div style={{
          marginTop: 10, padding: '10px 16px', background: MC.card,
          border: `1px solid ${MC.border}`, borderRadius: 12,
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <span style={{ fontSize: 14, color: MC.muted }}>人工成本占比</span>
          <span style={{
            fontSize: 16, fontWeight: 700,
            color: kpi.labor_cost_pct > 30 ? MC.danger : kpi.labor_cost_pct > 25 ? MC.warning : MC.success,
          }}>
            {kpi.labor_cost_pct.toFixed(1)}%
          </span>
        </div>

      </div>

      {/* Modals */}
      {selectedAlert && (
        <AlertDetailModal
          alert={selectedAlert}
          onClose={() => setSelectedAlert(null)}
          onRead={handleMarkAlertRead}
        />
      )}

      {selectedDiscount && (
        <DiscountApprovalModal
          request={selectedDiscount}
          onClose={() => setSelectedDiscount(null)}
          onApprove={handleApproveDiscount}
        />
      )}

      {showBroadcast && (
        <BroadcastModal storeId={storeId} onClose={() => setShowBroadcast(false)} />
      )}
    </div>
  );
}
