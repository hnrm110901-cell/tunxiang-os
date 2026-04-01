/**
 * 审批中心 — 真实审批流 API 版本
 * 接入 POST/GET /api/v1/approvals/* (tx-org approval_router v2)
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { txFetch } from '../../../api';

// ─── 类型定义 ────────────────────────────────────────────────────────────────

type ApprovalType = 'discount' | 'refund' | 'price_adjust' | 'leave' | 'exception';
type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'cancelled';
type RiskLevel = 'low' | 'medium' | 'high' | 'critical';
type TabKey = 'pending' | 'initiated';
type TypeFilter = ApprovalType | 'all';

interface ApprovalItem {
  id: string;
  approval_type: ApprovalType;
  title: string;
  applicant_name: string;
  store_name: string;
  amount_fen?: number;
  risk_level?: RiskLevel;
  status: ApprovalStatus;
  created_at: string;
  expires_at?: string;
  detail: Record<string, unknown>;
  // v2 API 字段映射
  business_type?: string;
  business_id?: string;
  initiator_id?: string;
  context_data?: Record<string, unknown>;
}

interface ApprovalDetail extends ApprovalItem {
  steps?: Array<{
    step: number;
    approver_role: string;
    approver_name?: string;
    status: string;
    comment?: string;
    acted_at?: string;
  }>;
  ai_suggestion?: string;
}

interface PendingCountData {
  pending_mine: number;
  initiated_by_me: number;
  today_processed: number;
  avg_process_hours: number;
}

// ─── 常量配置 ────────────────────────────────────────────────────────────────

const TYPE_CONFIG: Record<ApprovalType, { label: string; color: string; icon: string }> = {
  discount:     { label: '折扣审批', color: '#FF6B2C', icon: '⚡' },
  refund:       { label: '退款审批', color: '#ff4d4f', icon: '↩' },
  price_adjust: { label: '调价审批', color: '#1890ff', icon: '📊' },
  leave:        { label: '请假审批', color: '#722ed1', icon: '🗓' },
  exception:    { label: '异常处理', color: '#faad14', icon: '⚠' },
};

const STATUS_CONFIG: Record<ApprovalStatus, { label: string; color: string }> = {
  pending:   { label: '待审批', color: '#faad14' },
  approved:  { label: '已通过', color: '#52c41a' },
  rejected:  { label: '已拒绝', color: '#ff4d4f' },
  cancelled: { label: '已撤回', color: '#999' },
};

const RISK_CONFIG: Record<RiskLevel, { label: string; color: string }> = {
  low:      { label: 'LOW',      color: '#52c41a' },
  medium:   { label: 'MEDIUM',   color: '#faad14' },
  high:     { label: 'HIGH',     color: '#FF6B2C' },
  critical: { label: 'CRITICAL', color: '#ff4d4f' },
};

// 将后端 business_type 映射到前端 approval_type
function mapBusinessType(bt: string): ApprovalType {
  if (bt === 'discount')     return 'discount';
  if (bt === 'refund')       return 'refund';
  if (bt === 'price_adjust') return 'price_adjust';
  if (bt === 'leave')        return 'leave';
  return 'exception';
}

// 从 API 响应标准化为 ApprovalItem
function normalizeItem(raw: Record<string, unknown>): ApprovalItem {
  const bt = (raw.business_type as string) || 'exception';
  return {
    id:             String(raw.id || raw.instance_id || ''),
    approval_type:  mapBusinessType(bt),
    title:          String(raw.title || ''),
    applicant_name: String(raw.initiator_name || raw.applicant_name || ''),
    store_name:     String(raw.store_name || ''),
    amount_fen:     typeof raw.amount_fen === 'number' ? raw.amount_fen : undefined,
    risk_level:     (raw.risk_level as RiskLevel) || undefined,
    status:         (raw.status as ApprovalStatus) || 'pending',
    created_at:     String(raw.created_at || ''),
    expires_at:     raw.expires_at ? String(raw.expires_at) : undefined,
    detail:         (raw.context_data as Record<string, unknown>) || {},
    business_type:  bt,
    business_id:    String(raw.business_id || ''),
    initiator_id:   String(raw.initiator_id || ''),
    context_data:   (raw.context_data as Record<string, unknown>) || {},
  };
}

function formatRelativeTime(isoStr: string): string {
  if (!isoStr) return '';
  const diff = Date.now() - new Date(isoStr).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1)  return '刚刚';
  if (minutes < 60) return `${minutes}分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24)   return `${hours}小时前`;
  return `${Math.floor(hours / 24)}天前`;
}

// ─── API 层 ──────────────────────────────────────────────────────────────────

interface ListParams { role?: 'approver' | 'initiator'; status?: string; business_type?: string; page?: number; size?: number; }
interface ListResp   { items: Record<string, unknown>[]; total: number; }
interface ActionReq  { approver_id: string; comment?: string; }

async function apiListApprovals(params: ListParams): Promise<ListResp> {
  const qs = new URLSearchParams();
  if (params.role)          qs.set('role', params.role);
  if (params.status)        qs.set('status', params.status);
  if (params.business_type) qs.set('business_type', params.business_type);
  qs.set('page', String(params.page || 1));
  qs.set('size', String(params.size || 50));
  return txFetch<ListResp>(`/api/v1/approvals?${qs}`);
}

async function apiGetDetail(id: string): Promise<Record<string, unknown>> {
  return txFetch<Record<string, unknown>>(`/api/v1/approvals/${encodeURIComponent(id)}`);
}

async function apiApprove(id: string, req: ActionReq): Promise<unknown> {
  return txFetch(`/api/v1/approvals/${encodeURIComponent(id)}/approve`, {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

async function apiReject(id: string, req: ActionReq): Promise<unknown> {
  return txFetch(`/api/v1/approvals/${encodeURIComponent(id)}/reject`, {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

async function apiPendingCount(): Promise<PendingCountData> {
  return txFetch<PendingCountData>('/api/v1/approvals/pending-count');
}

// ─── 子组件 ──────────────────────────────────────────────────────────────────

function StatCard({
  title, value, unit, color, loading,
}: {
  title: string; value: string | number; unit?: string;
  color: string; loading?: boolean;
}) {
  return (
    <div style={{
      background: '#112228', borderRadius: 8, padding: '16px 20px',
      borderLeft: `3px solid ${color}`, flex: 1, minWidth: 0,
    }}>
      <div style={{ fontSize: 12, color: '#999', marginBottom: 6 }}>{title}</div>
      {loading ? (
        <div style={{ height: 28, background: '#1a2a33', borderRadius: 4, width: '60%' }} />
      ) : (
        <div style={{ fontSize: 24, fontWeight: 700, color: '#fff' }}>
          {value}
          {unit && <span style={{ fontSize: 13, color: '#999', marginLeft: 4 }}>{unit}</span>}
        </div>
      )}
    </div>
  );
}

function ApprovalCard({
  item, isSelected, onClick,
}: {
  item: ApprovalItem; isSelected: boolean; onClick: () => void;
}) {
  const tc = TYPE_CONFIG[item.approval_type];
  const sc = STATUS_CONFIG[item.status];
  const rc = item.risk_level ? RISK_CONFIG[item.risk_level] : null;

  return (
    <div
      onClick={onClick}
      style={{
        padding: 14, borderRadius: 8, cursor: 'pointer',
        background: isSelected ? 'rgba(255,107,44,0.08)' : '#0B1A20',
        border: isSelected ? '1px solid #FF6B2C' : '1px solid #1a2a33',
        transition: 'all .15s',
      }}
    >
      {/* 第一行：类型 + 状态 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{
            padding: '1px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600,
            background: `${tc.color}20`, color: tc.color,
          }}>{tc.icon} {tc.label}</span>
          <span style={{ fontSize: 13, fontWeight: 600 }}>{item.title}</span>
        </div>
        <span style={{
          fontSize: 10, padding: '1px 6px', borderRadius: 4,
          background: `${sc.color}20`, color: sc.color,
        }}>{sc.label}</span>
      </div>

      {/* 第二行：申请人 + 门店 + 时间 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#666' }}>
        <span>{item.applicant_name} · {item.store_name}</span>
        <span style={{ color: '#555' }}>⏰ {formatRelativeTime(item.created_at)}</span>
      </div>

      {/* 第三行：金额 + 风险等级 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 6 }}>
        {item.amount_fen != null && item.amount_fen !== 0 && (
          <span style={{ fontSize: 12, color: item.amount_fen < 0 ? '#ff4d4f' : '#52c41a' }}>
            {item.amount_fen < 0 ? '-' : '+'}¥{Math.abs(item.amount_fen / 100).toFixed(2)}
          </span>
        )}
        {rc && (
          <span style={{
            fontSize: 10, padding: '1px 6px', borderRadius: 3,
            background: `${rc.color}20`, color: rc.color, fontWeight: 600,
          }}>风险 {rc.label}</span>
        )}
      </div>
    </div>
  );
}

function ConfirmModal({
  action, item, onConfirm, onCancel, loading,
}: {
  action: 'approve' | 'reject';
  item: ApprovalItem;
  onConfirm: (comment: string) => void;
  onCancel: () => void;
  loading: boolean;
}) {
  const [comment, setComment] = useState('');
  const isApprove = action === 'approve';

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 1000,
      background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <div style={{
        background: '#112228', borderRadius: 10, padding: 24, width: 400,
        border: '1px solid #1a2a33', boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
      }}>
        <h3 style={{ margin: '0 0 6px', fontSize: 16, color: isApprove ? '#52c41a' : '#ff4d4f' }}>
          {isApprove ? '✅ 确认通过' : '❌ 确认拒绝'}
        </h3>
        <p style={{ margin: '0 0 16px', fontSize: 13, color: '#999' }}>
          {item.title} — {item.applicant_name} · {item.store_name}
        </p>

        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 12, color: '#999', marginBottom: 6 }}>
            审批意见{!isApprove && <span style={{ color: '#ff4d4f' }}> *</span>}
          </div>
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder={isApprove ? '可选：输入通过意见…' : '请输入拒绝原因（必填）'}
            style={{
              width: '100%', minHeight: 80, padding: '8px 10px',
              background: '#0B1A20', border: '1px solid #1a2a33', borderRadius: 6,
              color: '#ddd', fontSize: 13, resize: 'vertical', boxSizing: 'border-box',
              outline: 'none',
            }}
          />
        </div>

        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button
            onClick={onCancel}
            disabled={loading}
            style={{
              padding: '8px 20px', borderRadius: 6, border: '1px solid #1a2a33',
              background: 'transparent', color: '#999', cursor: 'pointer', fontSize: 13,
            }}
          >取消</button>
          <button
            onClick={() => {
              if (!isApprove && !comment.trim()) return;
              onConfirm(comment.trim());
            }}
            disabled={loading || (!isApprove && !comment.trim())}
            style={{
              padding: '8px 20px', borderRadius: 6, border: 'none', cursor: 'pointer',
              background: isApprove ? '#52c41a' : '#ff4d4f',
              color: '#fff', fontSize: 13, fontWeight: 600,
              opacity: loading ? 0.7 : 1,
            }}
          >{loading ? '处理中…' : (isApprove ? '确认通过' : '确认拒绝')}</button>
        </div>
      </div>
    </div>
  );
}

function DetailPanel({
  detail, onApprove, onReject,
}: {
  detail: ApprovalDetail | null;
  onApprove: (item: ApprovalItem) => void;
  onReject:  (item: ApprovalItem) => void;
}) {
  if (!detail) {
    return (
      <div style={{
        background: '#112228', borderRadius: 8, padding: 20,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: '#666', minHeight: 300,
      }}>
        选择一条审批记录查看详情
      </div>
    );
  }

  const tc = TYPE_CONFIG[detail.approval_type];
  const sc = STATUS_CONFIG[detail.status];

  // 从 context_data / detail 提取关键展示字段
  const ctx = detail.context_data || detail.detail || {};
  const keyFields: [string, string][] = [];
  if (ctx.discount_rate) keyFields.push(['折扣率', `${ctx.discount_rate}`]);
  if (ctx.refund_amount_fen) keyFields.push(['退款金额', `¥${(Number(ctx.refund_amount_fen) / 100).toFixed(2)}`]);
  if (ctx.original_price_fen) keyFields.push(['原价', `¥${(Number(ctx.original_price_fen) / 100).toFixed(2)}`]);
  if (ctx.new_price_fen) keyFields.push(['调整后价格', `¥${(Number(ctx.new_price_fen) / 100).toFixed(2)}`]);
  if (ctx.leave_days) keyFields.push(['请假天数', `${ctx.leave_days}天`]);
  if (ctx.reason) keyFields.push(['原因', String(ctx.reason)]);
  if (detail.amount_fen) keyFields.push(['涉及金额', `${detail.amount_fen < 0 ? '-' : '+'}¥${Math.abs(detail.amount_fen / 100).toFixed(2)}`]);

  return (
    <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
      {/* 标题区 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
        <div>
          <span style={{
            padding: '2px 10px', borderRadius: 4, fontSize: 11, fontWeight: 600,
            background: `${tc.color}20`, color: tc.color,
          }}>{tc.icon} {tc.label}</span>
          <h3 style={{ margin: '8px 0 4px', fontSize: 18 }}>{detail.title}</h3>
          <div style={{ fontSize: 12, color: '#999' }}>
            {detail.applicant_name} · {detail.store_name} · {formatRelativeTime(detail.created_at)}
          </div>
        </div>
        <span style={{
          padding: '2px 10px', borderRadius: 4, fontSize: 12, fontWeight: 600,
          background: `${sc.color}20`, color: sc.color,
        }}>{sc.label}</span>
      </div>

      {/* 关键参数卡片 */}
      {keyFields.length > 0 && (
        <div style={{
          display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8,
          background: '#0B1A20', borderRadius: 8, padding: 12, marginBottom: 16,
        }}>
          {keyFields.map(([k, v]) => (
            <div key={k}>
              <div style={{ fontSize: 10, color: '#666' }}>{k}</div>
              <div style={{ fontSize: 13, color: '#ddd', fontWeight: 600 }}>{v}</div>
            </div>
          ))}
        </div>
      )}

      {/* 风险标签 */}
      {detail.risk_level && (
        <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: '#999' }}>风险等级</span>
          <span style={{
            padding: '2px 10px', borderRadius: 4, fontSize: 11, fontWeight: 700,
            background: `${RISK_CONFIG[detail.risk_level].color}20`,
            color: RISK_CONFIG[detail.risk_level].color,
          }}>{RISK_CONFIG[detail.risk_level].label}</span>
        </div>
      )}

      {/* AI 分析建议 */}
      {detail.ai_suggestion && (
        <div style={{
          background: '#0d1f2a', border: '1px solid #185FA520',
          borderRadius: 8, padding: 12, marginBottom: 16,
        }}>
          <div style={{ fontSize: 11, color: '#185FA5', marginBottom: 6, fontWeight: 600 }}>
            🤖 AI 分析建议
          </div>
          <div style={{ fontSize: 13, color: '#ccc', lineHeight: 1.7 }}>
            {detail.ai_suggestion}
          </div>
        </div>
      )}

      {/* 审批步骤时间线 */}
      {detail.steps && detail.steps.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 12, color: '#999', marginBottom: 8 }}>审批流程</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {detail.steps.map((step) => (
              <div key={step.step} style={{
                display: 'flex', alignItems: 'flex-start', gap: 10,
                padding: '8px 10px', background: '#0B1A20', borderRadius: 6,
              }}>
                <span style={{
                  minWidth: 20, height: 20, borderRadius: '50%',
                  background: step.status === 'approved' ? '#52c41a20' :
                               step.status === 'rejected' ? '#ff4d4f20' : '#faad1420',
                  color: step.status === 'approved' ? '#52c41a' :
                         step.status === 'rejected' ? '#ff4d4f' : '#faad14',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 10, fontWeight: 700,
                }}>{step.step}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, color: '#ccc' }}>
                    {step.approver_name || step.approver_role}
                  </div>
                  {step.comment && (
                    <div style={{ fontSize: 11, color: '#888', marginTop: 2 }}>
                      "{step.comment}"
                    </div>
                  )}
                </div>
                {step.acted_at && (
                  <span style={{ fontSize: 10, color: '#555' }}>
                    {formatRelativeTime(step.acted_at)}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 操作按钮（仅 pending 状态显示） */}
      {detail.status === 'pending' && (
        <div style={{ display: 'flex', gap: 12, marginTop: 4 }}>
          <button
            onClick={() => onApprove(detail)}
            style={{
              flex: 1, height: 44, borderRadius: 8, border: 'none',
              background: '#52c41a', color: '#fff', fontSize: 14, fontWeight: 600,
              cursor: 'pointer',
            }}
          >✅ 通过</button>
          <button
            onClick={() => onReject(detail)}
            style={{
              flex: 1, height: 44, borderRadius: 8, border: 'none',
              background: '#ff4d4f', color: '#fff', fontSize: 14, fontWeight: 600,
              cursor: 'pointer',
            }}
          >❌ 拒绝</button>
        </div>
      )}
    </div>
  );
}

// ─── 主组件 ──────────────────────────────────────────────────────────────────

// 当前登录用户（实际项目从 auth store 取，此处 fallback）
const CURRENT_USER_ID = (() => {
  try {
    const u = JSON.parse(localStorage.getItem('tx_user') || '{}');
    return u.employee_id || u.id || 'current_user';
  } catch {
    return 'current_user';
  }
})();

export function ApprovalCenterPage() {
  // ── 状态 ──
  const [tab, setTab] = useState<TabKey>('pending');
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all');

  const [pendingItems, setPendingItems]   = useState<ApprovalItem[]>([]);
  const [initiatedItems, setInitiatedItems] = useState<ApprovalItem[]>([]);
  const [statsData, setStatsData]         = useState<PendingCountData | null>(null);

  const [selectedId, setSelectedId]       = useState<string | null>(null);
  const [detailData, setDetailData]       = useState<ApprovalDetail | null>(null);

  const [listLoading, setListLoading]     = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [statsLoading, setStatsLoading]   = useState(false);
  const [actionLoading, setActionLoading] = useState(false);

  const [errorMsg, setErrorMsg]           = useState<string | null>(null);
  const [successMsg, setSuccessMsg]       = useState<string | null>(null);

  const [confirmAction, setConfirmAction] = useState<{
    action: 'approve' | 'reject'; item: ApprovalItem;
  } | null>(null);

  // initiated 状态筛选
  const [initiatedStatusFilter, setInitiatedStatusFilter] = useState<ApprovalStatus | 'all'>('all');

  const prevTabRef = useRef<TabKey | null>(null);

  // ── 数据加载 ──

  const loadStats = useCallback(async () => {
    setStatsLoading(true);
    try {
      const data = await apiPendingCount();
      setStatsData(data);
    } catch {
      // stats 失败不阻断主流程
    } finally {
      setStatsLoading(false);
    }
  }, []);

  const loadPending = useCallback(async () => {
    setListLoading(true);
    try {
      const resp = await apiListApprovals({
        role: 'approver',
        status: 'pending',
        business_type: typeFilter !== 'all' ? typeFilter : undefined,
        size: 50,
      });
      setPendingItems((resp.items || []).map(normalizeItem));
      if (selectedId === null && resp.items.length > 0) {
        setSelectedId(String(resp.items[0].id || ''));
      }
    } catch (e) {
      setErrorMsg((e as Error).message || '加载待审批列表失败');
    } finally {
      setListLoading(false);
    }
  }, [typeFilter, selectedId]);

  const loadInitiated = useCallback(async () => {
    setListLoading(true);
    try {
      const resp = await apiListApprovals({
        role: 'initiator',
        status: initiatedStatusFilter !== 'all' ? initiatedStatusFilter : undefined,
        business_type: typeFilter !== 'all' ? typeFilter : undefined,
        size: 50,
      });
      setInitiatedItems((resp.items || []).map(normalizeItem));
    } catch (e) {
      setErrorMsg((e as Error).message || '加载我发起的审批失败');
    } finally {
      setListLoading(false);
    }
  }, [typeFilter, initiatedStatusFilter]);

  const loadDetail = useCallback(async (id: string) => {
    setDetailLoading(true);
    try {
      const raw = await apiGetDetail(id);
      const base = normalizeItem(raw);
      setDetailData({
        ...base,
        steps:         (raw.steps as ApprovalDetail['steps']) || [],
        ai_suggestion: raw.ai_suggestion as string | undefined,
      });
    } catch {
      setDetailData(null);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  // 初始化：加载统计数据
  useEffect(() => {
    loadStats();
  }, []);

  // tab / typeFilter 变化时加载列表
  useEffect(() => {
    const prevTab = prevTabRef.current;
    prevTabRef.current = tab;

    // 切换 tab 时重置选中
    if (prevTab !== null && prevTab !== tab) {
      setSelectedId(null);
      setDetailData(null);
    }

    if (tab === 'pending') {
      loadPending();
    } else {
      loadInitiated();
    }
  }, [tab, typeFilter, initiatedStatusFilter]);

  // selectedId 变化时加载详情
  useEffect(() => {
    if (selectedId) {
      loadDetail(selectedId);
    } else {
      setDetailData(null);
    }
  }, [selectedId]);

  // 消息自动消失
  useEffect(() => {
    if (!errorMsg && !successMsg) return;
    const t = setTimeout(() => {
      setErrorMsg(null);
      setSuccessMsg(null);
    }, 4000);
    return () => clearTimeout(t);
  }, [errorMsg, successMsg]);

  // ── 操作处理 ──

  const handleApproveClick = (item: ApprovalItem) => {
    setConfirmAction({ action: 'approve', item });
  };

  const handleRejectClick = (item: ApprovalItem) => {
    setConfirmAction({ action: 'reject', item });
  };

  const handleConfirm = async (comment: string) => {
    if (!confirmAction) return;
    const { action, item } = confirmAction;
    setActionLoading(true);
    try {
      const req = { approver_id: CURRENT_USER_ID, comment: comment || undefined };
      if (action === 'approve') {
        await apiApprove(item.id, req);
        setSuccessMsg(`已通过：${item.title}`);
      } else {
        await apiReject(item.id, req);
        setSuccessMsg(`已拒绝：${item.title}`);
      }
      setConfirmAction(null);
      setSelectedId(null);
      setDetailData(null);
      await loadPending();
      await loadStats();
    } catch (e) {
      setErrorMsg((e as Error).message || '操作失败，数据未变更');
    } finally {
      setActionLoading(false);
    }
  };

  // ── 当前展示列表 ──
  const displayItems = tab === 'pending' ? pendingItems : initiatedItems;

  // ── 渲染 ──────────────────────────────────────────────────────────────────

  return (
    <div style={{ color: '#ddd' }}>

      {/* 错误/成功提示条 */}
      {(errorMsg || successMsg) && (
        <div style={{
          marginBottom: 12, padding: '8px 14px', borderRadius: 6, fontSize: 13,
          background: errorMsg ? 'rgba(255,77,79,0.15)' : 'rgba(82,196,26,0.15)',
          border: `1px solid ${errorMsg ? '#ff4d4f' : '#52c41a'}40`,
          color: errorMsg ? '#ff4d4f' : '#52c41a',
        }}>
          {errorMsg || successMsg}
        </div>
      )}

      {/* 页头 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
          审批中心
          {(statsData?.pending_mine ?? 0) > 0 && (
            <span style={{
              padding: '2px 10px', borderRadius: 10, fontSize: 12,
              background: 'rgba(255,107,44,0.15)', color: '#FF6B2C', fontWeight: 600,
            }}>{statsData!.pending_mine} 待审</span>
          )}
        </h2>
        <div style={{ display: 'flex', gap: 8 }}>
          {(['pending', 'initiated'] as const).map((t) => (
            <button key={t} onClick={() => setTab(t)} style={{
              padding: '4px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
              fontSize: 12, fontWeight: 600,
              background: tab === t ? '#FF6B2C' : '#1a2a33',
              color: tab === t ? '#fff' : '#999',
            }}>{t === 'pending' ? '待我审批' : '我发起的'}</button>
          ))}
        </div>
      </div>

      {/* Section 1：汇总卡片 */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
        <StatCard
          title="待我审批"
          value={statsData?.pending_mine ?? '—'}
          color="#FF6B2C"
          loading={statsLoading}
        />
        <StatCard
          title="我发起的"
          value={statsData?.initiated_by_me ?? '—'}
          color="#1890ff"
          loading={statsLoading}
        />
        <StatCard
          title="今日已处理"
          value={statsData?.today_processed ?? '—'}
          color="#52c41a"
          loading={statsLoading}
        />
        <StatCard
          title="平均处理时长"
          value={statsData?.avg_process_hours != null ? statsData.avg_process_hours.toFixed(1) : '—'}
          unit="小时"
          color="#722ed1"
          loading={statsLoading}
        />
      </div>

      {/* Section 2 顶部：筛选 Tab */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
        <button onClick={() => setTypeFilter('all')} style={{
          padding: '3px 12px', borderRadius: 4, border: 'none', cursor: 'pointer', fontSize: 11,
          background: typeFilter === 'all' ? '#1a2a33' : 'transparent',
          color: typeFilter === 'all' ? '#fff' : '#666',
        }}>全部</button>
        {(Object.keys(TYPE_CONFIG) as ApprovalType[]).map((t) => (
          <button key={t} onClick={() => setTypeFilter(t)} style={{
            padding: '3px 12px', borderRadius: 4, border: 'none', cursor: 'pointer', fontSize: 11,
            background: typeFilter === t ? `${TYPE_CONFIG[t].color}20` : 'transparent',
            color: typeFilter === t ? TYPE_CONFIG[t].color : '#666',
          }}>{TYPE_CONFIG[t].label}</button>
        ))}

        {/* 仅"我发起的"显示状态筛选 */}
        {tab === 'initiated' && (
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
            {(['all', 'pending', 'approved', 'rejected'] as const).map((s) => (
              <button key={s} onClick={() => setInitiatedStatusFilter(s)} style={{
                padding: '3px 10px', borderRadius: 4, border: 'none', cursor: 'pointer', fontSize: 11,
                background: initiatedStatusFilter === s ? '#1a2a33' : 'transparent',
                color: initiatedStatusFilter === s ? '#fff' : '#666',
              }}>
                {s === 'all' ? '全部状态' : STATUS_CONFIG[s as ApprovalStatus].label}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* 主体：左列表 + 右详情 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 400px', gap: 16 }}>

        {/* 左：审批列表 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 16 }}>
          {listLoading ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {[1, 2, 3].map((i) => (
                <div key={i} style={{
                  height: 80, background: '#0B1A20', borderRadius: 8,
                  opacity: 0.6, animation: 'pulse 1.5s ease-in-out infinite',
                }} />
              ))}
            </div>
          ) : displayItems.length === 0 ? (
            <div style={{ textAlign: 'center', color: '#666', padding: 60 }}>
              {tab === 'pending' ? '暂无待审批记录 ✓' : '暂无发起的审批记录'}
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {displayItems.map((item) => (
                <ApprovalCard
                  key={item.id}
                  item={item}
                  isSelected={selectedId === item.id}
                  onClick={() => setSelectedId(item.id)}
                />
              ))}
            </div>
          )}
        </div>

        {/* 右：审批详情 */}
        {detailLoading ? (
          <div style={{
            background: '#112228', borderRadius: 8, padding: 20,
            display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#666',
          }}>
            加载中…
          </div>
        ) : (
          <DetailPanel
            detail={detailData}
            onApprove={handleApproveClick}
            onReject={handleRejectClick}
          />
        )}
      </div>

      {/* 二次确认弹窗 */}
      {confirmAction && (
        <ConfirmModal
          action={confirmAction.action}
          item={confirmAction.item}
          onConfirm={handleConfirm}
          onCancel={() => setConfirmAction(null)}
          loading={actionLoading}
        />
      )}
    </div>
  );
}
