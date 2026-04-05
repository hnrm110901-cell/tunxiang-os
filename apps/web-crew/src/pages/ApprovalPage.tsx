/**
 * 审批处理页 — 服务员/店长手机端
 * 路由：/approvals
 * API：
 *   GET /api/v1/ops/approvals/instances/pending-mine?approver_id=
 *   GET /api/v1/ops/approvals/instances/my-initiated?initiator_id=
 *   POST /api/v1/ops/approvals/instances/{id}/act
 *   GET /api/v1/ops/approvals/notifications?recipient_id=
 *   GET /api/v1/ops/approvals/instances/{id}
 */

import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { txFetch } from '../api/index';

// ─── Design Tokens (inline CSS) ──────────────────────────────────────────────

const C = {
  bg:       '#0B1A20',
  card:     '#112228',
  border:   '#1a2a33',
  accent:   '#FF6B35',
  green:    '#0F6E56',
  red:      '#A32D2D',
  greenBg:  '#e6f4f1',
  redBg:    '#fde8e8',
  muted:    '#5F5E5A',
  text:     '#e2e8f0',
  subtext:  '#94a3b8',
  white:    '#ffffff',
  warning:  '#BA7517',
  warningBg:'#fff8e1',
};

// ─── Types ────────────────────────────────────────────────────────────────────

type InstanceStatus = 'pending' | 'approved' | 'rejected' | 'expired';
type BusinessType =
  | 'discount' | 'refund' | 'void_order'
  | 'large_purchase' | 'leave' | 'payroll';

interface ApprovalStep {
  step_no: number;
  approver_role: string;
  approver_name?: string;
  status: 'pending' | 'approved' | 'rejected' | 'waiting';
  comment?: string;
  acted_at?: string;
}

interface ApprovalInstance {
  id: string;
  instance_no: string;
  title: string;
  description?: string;
  business_type: BusinessType;
  initiator_name: string;
  store_name: string;
  amount_fen?: number;
  current_step: number;
  total_steps: number;
  status: InstanceStatus;
  created_at: string;
  deadline_at?: string;
  steps?: ApprovalStep[];
}

interface Notification {
  id: string;
  title: string;
  body: string;
  is_read: boolean;
  created_at: string;
}

// ─── Constants ────────────────────────────────────────────────────────────────

const BIZ_LABEL: Record<BusinessType, string> = {
  discount:       '折扣审批',
  refund:         '退款审批',
  void_order:     '作废单',
  large_purchase: '大额采购',
  leave:          '员工请假',
  payroll:        '薪资审批',
};

const BIZ_ICON: Record<BusinessType, string> = {
  discount:       '⚡',
  refund:         '↩',
  void_order:     '🚫',
  large_purchase: '🛒',
  leave:          '🗓',
  payroll:        '💰',
};

const MY_ID = (window as unknown as Record<string, unknown>).__CREW_ID__ as string | undefined || 'crew_001';

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatAmount(fen?: number): string {
  if (fen == null) return '';
  return `¥${(fen / 100).toFixed(2)}`;
}

function getDeadlineInfo(deadlineAt?: string): { label: string; urgent: boolean; expired: boolean } {
  if (!deadlineAt) return { label: '', urgent: false, expired: false };
  const diff = new Date(deadlineAt).getTime() - Date.now();
  const diffH = diff / 1000 / 3600;
  const expired = diff < 0;
  const urgent = !expired && diffH < 2;
  if (expired) return { label: '已过期', urgent: false, expired: true };
  if (diffH < 1) {
    const mins = Math.floor(diff / 1000 / 60);
    return { label: `${mins}分钟后截止`, urgent: true, expired: false };
  }
  if (diffH < 24) {
    return { label: `${Math.floor(diffH)}小时后截止`, urgent, expired: false };
  }
  const days = Math.floor(diffH / 24);
  return { label: `${days}天后截止`, urgent: false, expired: false };
}

function getStepStatusStyle(status: string): { label: string; color: string; bg: string } {
  if (status === 'approved') return { label: '已通过', color: C.green, bg: C.greenBg };
  if (status === 'rejected') return { label: '已拒绝', color: C.red, bg: C.redBg };
  if (status === 'pending')  return { label: '审批中', color: C.warning, bg: C.warningBg };
  return { label: '待处理', color: C.muted, bg: '#f5f5f5' };
}

// ─── ApprovalCard (待我审批卡片) ──────────────────────────────────────────────

interface ApprovalCardProps {
  instance: ApprovalInstance;
  onActioned: () => void;
}

function ApprovalCard({ instance, onActioned }: ApprovalCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [acting, setActing] = useState<'approve' | 'reject' | null>(null);
  const [comment, setComment] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<'approved' | 'rejected' | null>(null);

  const deadline = getDeadlineInfo(instance.deadline_at);
  const biz = BIZ_LABEL[instance.business_type] || instance.business_type;
  const icon = BIZ_ICON[instance.business_type] || '📋';

  const handleAct = async (action: 'approve' | 'reject') => {
    if (action === 'reject' && !comment.trim()) {
      alert('请填写拒绝理由');
      return;
    }
    setSubmitting(true);
    try {
      await txFetch(`/api/v1/ops/approvals/instances/${instance.id}/act`, {
        method: 'POST',
        body: JSON.stringify({
          action,
          comment: comment.trim() || undefined,
          approver_id: MY_ID,
        }),
      });
      setResult(action === 'approve' ? 'approved' : 'rejected');
      setActing(null);
      setTimeout(() => onActioned(), 1200);
    } catch {
      alert('操作失败，请检查网络后重试');
    } finally {
      setSubmitting(false);
    }
  };

  if (result) {
    return (
      <div style={{
        background: result === 'approved' ? '#e6f4f1' : '#fde8e8',
        borderRadius: 12,
        padding: '20px 16px',
        marginBottom: 12,
        textAlign: 'center',
        border: `1px solid ${result === 'approved' ? C.green : C.red}`,
      }}>
        <div style={{ fontSize: 32 }}>{result === 'approved' ? '✅' : '❌'}</div>
        <div style={{ fontWeight: 700, color: result === 'approved' ? C.green : C.red, fontSize: 17, marginTop: 8 }}>
          {result === 'approved' ? '已批准' : '已拒绝'}
        </div>
        <div style={{ color: C.muted, fontSize: 15, marginTop: 4 }}>{instance.title}</div>
      </div>
    );
  }

  return (
    <div style={{
      background: C.card,
      borderRadius: 12,
      marginBottom: 12,
      border: `1px solid ${deadline.urgent ? C.warning : deadline.expired ? C.red : C.border}`,
      overflow: 'hidden',
    }}>
      {/* 卡片头部（可点击展开） */}
      <button
        onClick={() => setExpanded(e => !e)}
        style={{
          width: '100%',
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          padding: '16px',
          textAlign: 'left',
          color: C.text,
          WebkitTapHighlightColor: 'transparent',
        }}
      >
        {/* 顶行：类型 + 截止 */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <span style={{
            background: C.bg,
            color: C.accent,
            borderRadius: 6,
            padding: '2px 10px',
            fontSize: 13,
            fontWeight: 600,
          }}>
            {icon} {biz}
          </span>
          {deadline.label && (
            <span style={{
              fontSize: 13,
              color: deadline.expired ? C.red : deadline.urgent ? C.warning : C.subtext,
              fontWeight: deadline.urgent || deadline.expired ? 700 : 400,
            }}>
              ⏱ {deadline.label}
            </span>
          )}
        </div>

        {/* 标题 */}
        <div style={{ fontSize: 17, fontWeight: 700, color: C.white, marginBottom: 6, lineHeight: 1.4 }}>
          {instance.title}
        </div>

        {/* 发起人 + 金额 */}
        <div style={{ display: 'flex', gap: 16, fontSize: 15, color: C.subtext }}>
          <span>发起：{instance.initiator_name}</span>
          {instance.amount_fen != null && (
            <span style={{ color: C.accent, fontWeight: 700 }}>{formatAmount(instance.amount_fen)}</span>
          )}
        </div>

        <div style={{ textAlign: 'right', color: C.subtext, fontSize: 13, marginTop: 4 }}>
          {expanded ? '▲ 收起' : '▼ 展开详情'}
        </div>
      </button>

      {/* 展开内容 */}
      {expanded && (
        <div style={{ borderTop: `1px solid ${C.border}`, padding: '12px 16px' }}>
          {/* 描述 */}
          {instance.description && (
            <div style={{ fontSize: 15, color: C.text, marginBottom: 12, lineHeight: 1.6 }}>
              {instance.description}
            </div>
          )}

          {/* 历史步骤 */}
          {instance.steps && instance.steps.length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 14, color: C.subtext, marginBottom: 8, fontWeight: 600 }}>审批进度</div>
              {instance.steps.map((step, i) => {
                const sc = getStepStatusStyle(step.status);
                return (
                  <div key={i} style={{
                    display: 'flex',
                    gap: 10,
                    marginBottom: 8,
                    alignItems: 'flex-start',
                  }}>
                    {/* 步骤圆点 */}
                    <div style={{
                      width: 28,
                      height: 28,
                      borderRadius: '50%',
                      background: sc.bg,
                      border: `2px solid ${sc.color}`,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: 13,
                      fontWeight: 700,
                      color: sc.color,
                      flexShrink: 0,
                    }}>
                      {step.step_no}
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 15, color: C.text, fontWeight: 600 }}>
                        {step.approver_role}
                        {step.approver_name && (
                          <span style={{ color: C.subtext, fontWeight: 400 }}> · {step.approver_name}</span>
                        )}
                      </div>
                      <div style={{
                        display: 'inline-block',
                        background: sc.bg,
                        color: sc.color,
                        borderRadius: 4,
                        padding: '1px 8px',
                        fontSize: 13,
                        marginTop: 2,
                      }}>
                        {sc.label}
                      </div>
                      {step.comment && (
                        <div style={{ fontSize: 14, color: C.subtext, marginTop: 4 }}>
                          意见：{step.comment}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* 审批操作区 */}
          {!acting && (
            <div style={{ display: 'flex', gap: 12, marginTop: 8 }}>
              <button
                onClick={() => setActing('approve')}
                style={{
                  flex: 1,
                  height: 52,
                  background: C.green,
                  color: C.white,
                  border: 'none',
                  borderRadius: 10,
                  fontSize: 17,
                  fontWeight: 700,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 6,
                  WebkitTapHighlightColor: 'transparent',
                  transition: 'opacity 0.15s',
                }}
                onMouseDown={e => (e.currentTarget.style.opacity = '0.8')}
                onMouseUp={e => (e.currentTarget.style.opacity = '1')}
                onTouchStart={e => (e.currentTarget.style.transform = 'scale(0.97)')}
                onTouchEnd={e => (e.currentTarget.style.transform = 'scale(1)')}
              >
                ✅ 通过
              </button>
              <button
                onClick={() => setActing('reject')}
                style={{
                  flex: 1,
                  height: 52,
                  background: C.red,
                  color: C.white,
                  border: 'none',
                  borderRadius: 10,
                  fontSize: 17,
                  fontWeight: 700,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 6,
                  WebkitTapHighlightColor: 'transparent',
                  transition: 'opacity 0.15s',
                }}
                onMouseDown={e => (e.currentTarget.style.opacity = '0.8')}
                onMouseUp={e => (e.currentTarget.style.opacity = '1')}
                onTouchStart={e => (e.currentTarget.style.transform = 'scale(0.97)')}
                onTouchEnd={e => (e.currentTarget.style.transform = 'scale(1)')}
              >
                ❌ 拒绝
              </button>
            </div>
          )}

          {/* 意见输入区 */}
          {acting && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 15, color: C.text, marginBottom: 8, fontWeight: 600 }}>
                {acting === 'approve' ? '✅ 通过审批' : '❌ 拒绝申请'}
                {acting === 'reject' && (
                  <span style={{ color: C.red, fontSize: 13, fontWeight: 400 }}> （必须填写拒绝理由）</span>
                )}
              </div>
              <textarea
                value={comment}
                onChange={e => setComment(e.target.value)}
                placeholder={acting === 'approve' ? '可选：填写审批意见...' : '请填写拒绝理由（必填）'}
                rows={3}
                style={{
                  width: '100%',
                  background: C.bg,
                  border: `1px solid ${C.border}`,
                  borderRadius: 8,
                  color: C.text,
                  fontSize: 16,
                  padding: '10px 12px',
                  resize: 'none',
                  boxSizing: 'border-box',
                  marginBottom: 12,
                  outline: 'none',
                  lineHeight: 1.6,
                }}
              />
              <div style={{ display: 'flex', gap: 10 }}>
                <button
                  onClick={() => { setActing(null); setComment(''); }}
                  style={{
                    flex: 1,
                    height: 52,
                    background: C.border,
                    color: C.text,
                    border: 'none',
                    borderRadius: 10,
                    fontSize: 16,
                    fontWeight: 600,
                    cursor: 'pointer',
                    WebkitTapHighlightColor: 'transparent',
                  }}
                >
                  取消
                </button>
                <button
                  onClick={() => handleAct(acting)}
                  disabled={submitting}
                  style={{
                    flex: 2,
                    height: 52,
                    background: acting === 'approve' ? C.green : C.red,
                    color: C.white,
                    border: 'none',
                    borderRadius: 10,
                    fontSize: 17,
                    fontWeight: 700,
                    cursor: submitting ? 'not-allowed' : 'pointer',
                    opacity: submitting ? 0.7 : 1,
                    WebkitTapHighlightColor: 'transparent',
                  }}
                >
                  {submitting ? '提交中...' : `确认${acting === 'approve' ? '通过' : '拒绝'}`}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── InitiatedCard (我发起的卡片) ─────────────────────────────────────────────

function InitiatedCard({ instance }: { instance: ApprovalInstance }) {
  const biz = BIZ_LABEL[instance.business_type] || instance.business_type;
  const icon = BIZ_ICON[instance.business_type] || '📋';
  const statusColors: Record<InstanceStatus, { bg: string; text: string; label: string }> = {
    pending:  { bg: C.warningBg, text: C.warning, label: '审批中' },
    approved: { bg: C.greenBg, text: C.green, label: '已通过' },
    rejected: { bg: C.redBg, text: C.red, label: '已拒绝' },
    expired:  { bg: '#f5f5f5', text: C.muted, label: '已过期' },
  };
  const sc = statusColors[instance.status];

  // 进度计算
  const completedSteps = (instance.steps || []).filter(s => s.status === 'approved' || s.status === 'rejected').length;
  const progressPct = instance.total_steps > 0
    ? Math.round((completedSteps / instance.total_steps) * 100)
    : 0;

  return (
    <div style={{
      background: C.card,
      borderRadius: 12,
      marginBottom: 12,
      padding: '16px',
      border: `1px solid ${C.border}`,
    }}>
      {/* 顶行：类型标签 + 状态 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <span style={{
          background: C.bg,
          color: C.accent,
          borderRadius: 6,
          padding: '2px 10px',
          fontSize: 13,
          fontWeight: 600,
        }}>
          {icon} {biz}
        </span>
        <span style={{
          background: sc.bg,
          color: sc.text,
          borderRadius: 6,
          padding: '2px 10px',
          fontSize: 13,
          fontWeight: 700,
        }}>
          {sc.label}
        </span>
      </div>

      {/* 标题 */}
      <div style={{ fontSize: 17, fontWeight: 700, color: C.white, marginBottom: 6, lineHeight: 1.4 }}>
        {instance.title}
      </div>

      {/* 金额 */}
      {instance.amount_fen != null && (
        <div style={{ fontSize: 16, color: C.accent, fontWeight: 700, marginBottom: 10 }}>
          {formatAmount(instance.amount_fen)}
        </div>
      )}

      {/* 进度条 */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
          <span style={{ fontSize: 14, color: C.subtext }}>审批进度</span>
          <span style={{ fontSize: 14, color: C.subtext }}>
            {completedSteps} / {instance.total_steps} 步 · {progressPct}%
          </span>
        </div>
        <div style={{
          height: 8,
          background: C.border,
          borderRadius: 4,
          overflow: 'hidden',
        }}>
          <div style={{
            height: '100%',
            width: `${progressPct}%`,
            background: instance.status === 'rejected' ? C.red
              : instance.status === 'approved' ? C.green
              : C.accent,
            borderRadius: 4,
            transition: 'width 0.3s ease',
          }} />
        </div>
      </div>

      {/* 步骤标签行 */}
      {instance.steps && instance.steps.length > 0 && (
        <div style={{ display: 'flex', gap: 6, marginTop: 10, flexWrap: 'wrap' }}>
          {instance.steps.map((step, i) => {
            const sc2 = getStepStatusStyle(step.status);
            return (
              <span key={i} style={{
                background: sc2.bg,
                color: sc2.color,
                borderRadius: 4,
                padding: '2px 8px',
                fontSize: 13,
              }}>
                {step.step_no}. {step.approver_role}
              </span>
            );
          })}
        </div>
      )}

      {/* 创建时间 */}
      <div style={{ fontSize: 13, color: C.subtext, marginTop: 8 }}>
        发起于 {new Date(instance.created_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
      </div>
    </div>
  );
}

// ─── 触发审批说明卡片 ─────────────────────────────────────────────────────────

function TriggerInfoCard() {
  return (
    <div style={{
      background: 'rgba(255,107,53,0.08)',
      border: `1px dashed ${C.accent}`,
      borderRadius: 12,
      padding: '14px 16px',
      marginBottom: 16,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: C.accent, marginBottom: 6 }}>
        💡 自动触发说明
      </div>
      <div style={{ fontSize: 14, color: C.subtext, lineHeight: 1.7 }}>
        以下操作会自动发起审批：
        <br />⚡ <strong style={{ color: C.text }}>折扣申请</strong> — 在收银/桌台页申请折扣时触发
        <br />↩ <strong style={{ color: C.text }}>退款申请</strong> — 在订单详情申请退款时触发
        <br />🚫 <strong style={{ color: C.text }}>作废单</strong> — 在订单详情点击"作废"时触发
        <br />🛒 <strong style={{ color: C.text }}>大额采购</strong> — 在采购申请超出金额上限时触发
      </div>
    </div>
  );
}

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export function ApprovalPage() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<'pending' | 'initiated'>('pending');
  const [pendingList, setPendingList] = useState<ApprovalInstance[]>([]);
  const [initiatedList, setInitiatedList] = useState<ApprovalInstance[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');

  const loadData = useCallback(async () => {
    setLoading(true);
    setErrorMsg('');
    let hasError = false;

    try {
      // 待我审批
      const pendingRes = await txFetch<{ items: ApprovalInstance[]; total: number }>(
        `/api/v1/ops/approvals/instances/pending-mine?approver_id=${encodeURIComponent(MY_ID)}`,
      );
      setPendingList(pendingRes.items);
    } catch {
      setPendingList([]);
      hasError = true;
    }

    try {
      // 我发起的
      const initiatedRes = await txFetch<{ items: ApprovalInstance[]; total: number }>(
        `/api/v1/ops/approvals/instances/my-initiated?initiator_id=${encodeURIComponent(MY_ID)}`,
      );
      setInitiatedList(initiatedRes.items);
    } catch {
      setInitiatedList([]);
      hasError = true;
    }

    try {
      // 通知未读数
      const notiRes = await txFetch<{ items: Notification[]; total: number }>(
        `/api/v1/ops/approvals/notifications?recipient_id=${encodeURIComponent(MY_ID)}`,
      );
      setUnreadCount(notiRes.items.filter(n => !n.is_read).length);
    } catch {
      setUnreadCount(0);
      hasError = true;
    }

    if (hasError) {
      setErrorMsg('部分数据加载失败，请点击重试');
    }

    setLoading(false);
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const pendingCount = pendingList.length;

  return (
    <div style={{
      background: C.bg,
      minHeight: '100vh',
      color: C.text,
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif',
      paddingBottom: 80,
    }}>
      {/* 顶部导航 */}
      <div style={{
        background: C.card,
        padding: '16px 16px 12px',
        borderBottom: `1px solid ${C.border}`,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        position: 'sticky',
        top: 0,
        zIndex: 10,
      }}>
        <button
          onClick={() => navigate(-1)}
          style={{
            background: 'transparent',
            border: 'none',
            color: C.subtext,
            fontSize: 24,
            cursor: 'pointer',
            padding: '4px 8px',
            minWidth: 48,
            minHeight: 48,
            display: 'flex',
            alignItems: 'center',
            WebkitTapHighlightColor: 'transparent',
          }}
        >
          ‹
        </button>

        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 18, fontWeight: 700, color: C.white }}>审批处理</div>
          {pendingCount > 0 && (
            <div style={{ fontSize: 14, color: C.warning, marginTop: 2 }}>
              待处理 {pendingCount} 件
            </div>
          )}
        </div>

        {/* 通知徽章 */}
        <button
          style={{
            background: 'transparent',
            border: 'none',
            cursor: 'pointer',
            position: 'relative',
            minWidth: 48,
            minHeight: 48,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            WebkitTapHighlightColor: 'transparent',
          }}
        >
          <span style={{ fontSize: 22 }}>🔔</span>
          {unreadCount > 0 && (
            <span style={{
              position: 'absolute',
              top: 6,
              right: 6,
              background: C.red,
              color: C.white,
              borderRadius: '50%',
              width: 18,
              height: 18,
              fontSize: 11,
              fontWeight: 700,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              lineHeight: 1,
            }}>
              {unreadCount > 99 ? '99+' : unreadCount}
            </span>
          )}
        </button>
      </div>

      {/* Tab 栏 */}
      <div style={{
        display: 'flex',
        background: C.card,
        borderBottom: `1px solid ${C.border}`,
      }}>
        {([
          { key: 'pending', label: `待我审批`, badge: pendingCount },
          { key: 'initiated', label: '我发起的', badge: 0 },
        ] as const).map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            style={{
              flex: 1,
              padding: '14px 0',
              background: 'transparent',
              border: 'none',
              borderBottom: activeTab === tab.key ? `3px solid ${C.accent}` : '3px solid transparent',
              color: activeTab === tab.key ? C.accent : C.subtext,
              fontSize: 16,
              fontWeight: activeTab === tab.key ? 700 : 400,
              cursor: 'pointer',
              WebkitTapHighlightColor: 'transparent',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 6,
              minHeight: 48,
            }}
          >
            {tab.label}
            {tab.badge > 0 && (
              <span style={{
                background: C.red,
                color: C.white,
                borderRadius: 10,
                padding: '1px 7px',
                fontSize: 12,
                fontWeight: 700,
              }}>
                {tab.badge}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* 内容区 */}
      <div style={{ padding: '16px' }}>
        {errorMsg && (
          <div style={{
            background: C.redBg,
            border: `1px solid ${C.red}`,
            borderRadius: 10,
            padding: '12px 16px',
            marginBottom: 12,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}>
            <span style={{ fontSize: 15, color: C.red }}>{errorMsg}</span>
            <button
              onClick={() => loadData()}
              style={{
                background: C.red,
                color: C.white,
                border: 'none',
                borderRadius: 8,
                padding: '6px 16px',
                fontSize: 14,
                fontWeight: 600,
                cursor: 'pointer',
                minHeight: 36,
                minWidth: 60,
              }}
            >重试</button>
          </div>
        )}
        {loading ? (
          <div style={{ textAlign: 'center', padding: '48px 0', color: C.subtext, fontSize: 16 }}>
            <div style={{
              width: 32, height: 32,
              border: `3px solid ${C.border}`,
              borderTopColor: C.accent,
              borderRadius: '50%',
              animation: 'spin 0.8s linear infinite',
              margin: '0 auto 12px',
            }} />
            <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
            加载中...
          </div>
        ) : activeTab === 'pending' ? (
          <>
            {pendingList.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '48px 0' }}>
                <div style={{ fontSize: 48, marginBottom: 12 }}>✅</div>
                <div style={{ color: C.subtext, fontSize: 17 }}>暂无待处理审批</div>
              </div>
            ) : (
              pendingList.map(ins => (
                <ApprovalCard key={ins.id} instance={ins} onActioned={loadData} />
              ))
            )}
          </>
        ) : (
          <>
            <TriggerInfoCard />
            {initiatedList.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '48px 0' }}>
                <div style={{ fontSize: 48, marginBottom: 12 }}>📋</div>
                <div style={{ color: C.subtext, fontSize: 17 }}>暂无发起的审批</div>
              </div>
            ) : (
              initiatedList.map(ins => (
                <InitiatedCard key={ins.id} instance={ins} />
              ))
            )}
          </>
        )}
      </div>
    </div>
  );
}
