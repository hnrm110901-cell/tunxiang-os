/**
 * 高风险操作待确认中心 — Operation Plan Center
 * 展示所有需要人工确认的高风险操作计划，支持实时 SSE 推送
 */
import { useEffect, useRef, useState, useCallback } from 'react';
import { txFetch } from '../../../api';

// ─── 类型定义 ───

interface ImpactAnalysis {
  affected_stores: number;
  affected_employees: number;
  affected_members: number;
  financial_impact_fen: number;
  risk_level: 'low' | 'medium' | 'high' | 'critical';
  impact_summary: string;
  warnings: string[];
  reversible: boolean;
}

interface OperationPlan {
  plan_id: string;
  operation_type: string;
  status: 'pending_confirm' | 'confirmed' | 'cancelled' | 'executed';
  risk_level: 'low' | 'medium' | 'high' | 'critical';
  impact: ImpactAnalysis;
  operator_id: string;
  expires_at: string;
  created_at: string;
}

// ─── 常量 ───

const OPERATION_TYPE_LABELS: Record<string, string> = {
  'menu.price.bulk_update': '菜品批量改价',
  'payroll.recalculate': '薪资重算',
  'member.points.bulk_adjust': '会员积分批量调整',
  'store.clone': '快速开店克隆',
  'org.role.bulk_change': '角色批量变更',
  'supply.price.bulk_update': '食材价格批量调整',
};

const RISK_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  low:      { bg: '#185FA522', text: '#185FA5', border: '#185FA5' },
  medium:   { bg: '#BA751722', text: '#BA7517', border: '#BA7517' },
  high:     { bg: '#A32D2D22', text: '#A32D2D', border: '#A32D2D' },
  critical: { bg: '#6B0F0F', text: '#FF4D4D', border: '#FF4D4D' },
};

const RISK_LABELS: Record<string, string> = {
  low: '低风险', medium: '中风险', high: '高风险', critical: '极高风险',
};

// ─── 工具函数 ───

function formatFen(fen: number): string {
  if (!fen) return '—';
  return `¥${(fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`;
}

function formatCountdown(expiresAt: string): { text: string; urgent: boolean } {
  const diff = new Date(expiresAt).getTime() - Date.now();
  if (diff <= 0) return { text: '已超时', urgent: true };
  const mins = Math.floor(diff / 60000);
  const secs = Math.floor((diff % 60000) / 1000);
  return {
    text: `${mins}:${secs.toString().padStart(2, '0')}`,
    urgent: diff < 5 * 60 * 1000,
  };
}

// ─── 子组件：倒计时 ───

function Countdown({ expiresAt }: { expiresAt: string }) {
  const [display, setDisplay] = useState(() => formatCountdown(expiresAt));
  useEffect(() => {
    const timer = setInterval(() => setDisplay(formatCountdown(expiresAt)), 1000);
    return () => clearInterval(timer);
  }, [expiresAt]);

  return (
    <span style={{
      fontFamily: 'monospace',
      fontSize: 14,
      fontWeight: 'bold',
      color: display.urgent ? '#FF4D4D' : '#BA7517',
      animation: display.urgent ? 'pulse 1s infinite' : 'none',
    }}>
      ⏱ {display.text}
    </span>
  );
}

// ─── 子组件：风险徽章 ───

function RiskBadge({ level }: { level: string }) {
  const c = RISK_COLORS[level] || RISK_COLORS.medium;
  return (
    <span style={{
      padding: '2px 10px',
      borderRadius: 12,
      fontSize: 12,
      fontWeight: 600,
      background: c.bg,
      color: c.text,
      border: `1px solid ${c.border}`,
    }}>
      {RISK_LABELS[level] || level}
    </span>
  );
}

// ─── 子组件：确认对话框 ───

interface ConfirmDialogProps {
  plan: OperationPlan;
  action: 'confirm' | 'cancel';
  onClose: () => void;
  onSuccess: () => void;
}

function ConfirmDialog({ plan, action, onClose, onSuccess }: ConfirmDialogProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const isConfirm = action === 'confirm';
  const label = isConfirm ? '确认执行' : '取消操作';
  const color = isConfirm ? '#0F6E56' : '#A32D2D';

  const handleSubmit = async () => {
    setLoading(true);
    setError('');
    try {
      await txFetch(`/api/v1/operation-plans/${plan.plan_id}/${action}`, {
        method: 'POST',
        body: JSON.stringify({ operator_id: localStorage.getItem('tx_user_id') || 'admin' }),
      });
      onSuccess();
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '操作失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
    }} onClick={onClose}>
      <div style={{
        background: '#1a2a33', borderRadius: 12, padding: 32, maxWidth: 480, width: '90%',
        border: `2px solid ${color}`,
      }} onClick={e => e.stopPropagation()}>
        <h3 style={{ color: '#fff', marginBottom: 16, fontSize: 18 }}>
          {isConfirm ? '⚠️ 确认执行高风险操作' : '取消此操作计划'}
        </h3>
        <p style={{ color: '#aaa', marginBottom: 8 }}>
          操作：<span style={{ color: '#fff' }}>{OPERATION_TYPE_LABELS[plan.operation_type] || plan.operation_type}</span>
        </p>
        <p style={{ color: '#aaa', marginBottom: 8 }}>
          风险：<RiskBadge level={plan.risk_level} />
        </p>
        {isConfirm && (
          <p style={{ color: '#BA7517', fontSize: 13, marginBottom: 20, lineHeight: 1.6 }}>
            此操作影响范围：{plan.impact.impact_summary}
            {!plan.impact.reversible && <><br /><strong style={{ color: '#FF4D4D' }}>⚠ 此操作不可逆</strong></>}
          </p>
        )}
        {error && <p style={{ color: '#FF4D4D', fontSize: 13, marginBottom: 12 }}>{error}</p>}
        <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{
            padding: '8px 20px', borderRadius: 6, border: '1px solid #444',
            background: 'transparent', color: '#aaa', cursor: 'pointer',
          }}>
            返回
          </button>
          <button onClick={handleSubmit} disabled={loading} style={{
            padding: '8px 20px', borderRadius: 6, border: 'none',
            background: color, color: '#fff', cursor: loading ? 'wait' : 'pointer',
            fontWeight: 600, opacity: loading ? 0.7 : 1,
          }}>
            {loading ? '处理中...' : label}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── 子组件：操作详情抽屉 ───

function PlanDrawer({ plan, onClose, onAction }: {
  plan: OperationPlan;
  onClose: () => void;
  onAction: (action: 'confirm' | 'cancel') => void;
}) {
  return (
    <div style={{
      position: 'fixed', right: 0, top: 0, bottom: 0, width: 480,
      background: '#112228', borderLeft: '1px solid #2a3a44',
      overflow: 'auto', padding: 28, zIndex: 100,
      boxShadow: '-8px 0 24px rgba(0,0,0,0.4)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h3 style={{ color: '#fff', margin: 0, fontSize: 18 }}>操作计划详情</h3>
        <button onClick={onClose} style={{
          background: 'transparent', border: 'none', color: '#aaa', fontSize: 20, cursor: 'pointer',
        }}>✕</button>
      </div>

      {/* 基本信息 */}
      <div style={{ background: '#1a2a33', borderRadius: 8, padding: 16, marginBottom: 16 }}>
        <div style={{ marginBottom: 12 }}>
          <span style={{ color: '#888', fontSize: 12 }}>操作类型</span>
          <div style={{ color: '#fff', fontSize: 15, fontWeight: 600, marginTop: 4 }}>
            {OPERATION_TYPE_LABELS[plan.operation_type] || plan.operation_type}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
          <div>
            <span style={{ color: '#888', fontSize: 12 }}>风险等级</span>
            <div style={{ marginTop: 4 }}><RiskBadge level={plan.risk_level} /></div>
          </div>
          <div>
            <span style={{ color: '#888', fontSize: 12 }}>可逆性</span>
            <div style={{ marginTop: 4, color: plan.impact.reversible ? '#0F6E56' : '#FF4D4D', fontSize: 13 }}>
              {plan.impact.reversible ? '✓ 可撤销' : '✗ 不可逆'}
            </div>
          </div>
          <div>
            <span style={{ color: '#888', fontSize: 12 }}>超时倒计时</span>
            <div style={{ marginTop: 4 }}><Countdown expiresAt={plan.expires_at} /></div>
          </div>
        </div>
      </div>

      {/* 影响范围 */}
      <div style={{ background: '#1a2a33', borderRadius: 8, padding: 16, marginBottom: 16 }}>
        <div style={{ color: '#888', fontSize: 12, marginBottom: 12 }}>AI 影响分析</div>
        <p style={{ color: '#ccc', fontSize: 13, lineHeight: 1.7, marginBottom: 12 }}>
          {plan.impact.impact_summary}
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
          {[
            { label: '影响门店', value: plan.impact.affected_stores, unit: '家' },
            { label: '影响员工', value: plan.impact.affected_employees, unit: '人' },
            { label: '影响会员', value: plan.impact.affected_members, unit: '人' },
          ].map(item => (
            <div key={item.label} style={{ textAlign: 'center', background: '#0d1e28', borderRadius: 6, padding: 12 }}>
              <div style={{ fontSize: 22, fontWeight: 'bold', color: '#FF6B35' }}>{item.value}</div>
              <div style={{ fontSize: 11, color: '#888' }}>{item.label}（{item.unit}）</div>
            </div>
          ))}
        </div>
        {plan.impact.financial_impact_fen > 0 && (
          <div style={{ marginTop: 12, padding: '8px 12px', background: '#BA751722', borderRadius: 6, borderLeft: '3px solid #BA7517' }}>
            <span style={{ color: '#888', fontSize: 12 }}>预估财务影响：</span>
            <span style={{ color: '#BA7517', fontWeight: 600, fontSize: 15 }}>
              {formatFen(plan.impact.financial_impact_fen)}
            </span>
          </div>
        )}
      </div>

      {/* 风险提示 */}
      {plan.impact.warnings.length > 0 && (
        <div style={{ background: '#1a2a33', borderRadius: 8, padding: 16, marginBottom: 16 }}>
          <div style={{ color: '#888', fontSize: 12, marginBottom: 8 }}>⚠ 注意事项</div>
          {plan.impact.warnings.map((w, i) => (
            <div key={i} style={{
              padding: '6px 10px', background: '#BA751722', borderRadius: 4,
              color: '#BA7517', fontSize: 13, marginBottom: 6,
            }}>
              · {w}
            </div>
          ))}
        </div>
      )}

      {/* 操作按钮 */}
      {plan.status === 'pending_confirm' && (
        <div style={{ display: 'flex', gap: 12, marginTop: 8 }}>
          <button onClick={() => onAction('cancel')} style={{
            flex: 1, padding: '12px', borderRadius: 8,
            border: '1px solid #A32D2D', background: 'transparent',
            color: '#A32D2D', cursor: 'pointer', fontWeight: 600, fontSize: 14,
          }}>
            取消操作
          </button>
          <button onClick={() => onAction('confirm')} style={{
            flex: 2, padding: '12px', borderRadius: 8,
            border: 'none', background: '#0F6E56',
            color: '#fff', cursor: 'pointer', fontWeight: 600, fontSize: 14,
          }}>
            确认执行 →
          </button>
        </div>
      )}
      {plan.status !== 'pending_confirm' && (
        <div style={{
          padding: 12, borderRadius: 8, textAlign: 'center',
          background: plan.status === 'confirmed' ? '#0F6E5622' : '#A32D2D22',
          color: plan.status === 'confirmed' ? '#0F6E56' : '#A32D2D',
          fontWeight: 600,
        }}>
          {plan.status === 'confirmed' ? '✓ 已确认执行' : '✗ 已取消'}
        </div>
      )}
    </div>
  );
}

// ─── 主页面 ───

export function OperationPlanPage() {
  const [plans, setPlans] = useState<OperationPlan[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedPlan, setSelectedPlan] = useState<OperationPlan | null>(null);
  const [dialogAction, setDialogAction] = useState<'confirm' | 'cancel' | null>(null);
  const [sseConnected, setSseConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  const fetchPlans = useCallback(async () => {
    try {
      const data = await txFetch<{ items: OperationPlan[] }>('/api/v1/operation-plans/pending');
      setPlans(data.items || []);
    } catch {
      /* 降级：保留现有数据 */
    } finally {
      setLoading(false);
    }
  }, []);

  // SSE 实时通知
  useEffect(() => {
    const tenantId = localStorage.getItem('tx_tenant_id') || '';
    const operatorId = localStorage.getItem('tx_user_id') || '';
    const url = `/api/v1/notifications/stream?operator_id=${operatorId}`;
    const es = new EventSource(url);
    esRef.current = es;

    es.onopen = () => setSseConnected(true);
    es.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        if (msg.type === 'operation_plan_created') {
          fetchPlans(); // 有新计划时刷新列表
        }
      } catch { /* ignore */ }
    };
    es.onerror = () => setSseConnected(false);

    return () => { es.close(); setSseConnected(false); };
  }, [fetchPlans]);

  useEffect(() => { fetchPlans(); }, [fetchPlans]);

  const pending = plans.filter(p => p.status === 'pending_confirm');
  const todayConfirmed = plans.filter(p => p.status === 'confirmed').length;
  const todayCancelled = plans.filter(p => p.status === 'cancelled').length;

  const handleAction = (action: 'confirm' | 'cancel') => {
    setDialogAction(action);
  };

  return (
    <div style={{ padding: 24, minHeight: '100vh', background: '#0d1e28', color: '#fff' }}>
      {/* 脉冲动画 */}
      <style>{`
        @keyframes pulse { 0%,100% { opacity:1 } 50% { opacity:0.5 } }
      `}</style>

      {/* 页头 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>⚠️ 高风险操作待确认</h2>
          <p style={{ color: '#888', margin: '4px 0 0', fontSize: 13 }}>
            超过阈值的操作需要人工确认后才能执行
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{
            width: 8, height: 8, borderRadius: '50%', display: 'inline-block',
            background: sseConnected ? '#0F6E56' : '#888',
            animation: sseConnected ? 'pulse 2s infinite' : 'none',
          }} />
          <span style={{ fontSize: 12, color: '#888' }}>
            {sseConnected ? '实时推送已连接' : '实时推送未连接'}
          </span>
        </div>
      </div>

      {/* 统计卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 16, marginBottom: 24 }}>
        {[
          { label: '待确认', value: pending.length, color: '#BA7517', bg: '#BA751722' },
          { label: '今日已确认', value: todayConfirmed, color: '#0F6E56', bg: '#0F6E5622' },
          { label: '今日已取消', value: todayCancelled, color: '#888', bg: '#1a2a33' },
        ].map(card => (
          <div key={card.label} style={{
            background: card.bg, borderRadius: 10, padding: '16px 20px',
            border: `1px solid ${card.color}44`,
          }}>
            <div style={{ fontSize: 32, fontWeight: 700, color: card.color }}>{card.value}</div>
            <div style={{ fontSize: 13, color: '#888', marginTop: 4 }}>{card.label}</div>
          </div>
        ))}
      </div>

      {/* 操作列表 */}
      {loading ? (
        <div style={{ textAlign: 'center', padding: 60, color: '#888' }}>加载中...</div>
      ) : pending.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 60, color: '#888', background: '#1a2a33', borderRadius: 12 }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>✓</div>
          <div style={{ fontSize: 16 }}>暂无待确认操作</div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {pending.map(plan => {
            const riskC = RISK_COLORS[plan.risk_level] || RISK_COLORS.medium;
            return (
              <div
                key={plan.plan_id}
                onClick={() => setSelectedPlan(plan)}
                style={{
                  background: '#1a2a33', borderRadius: 10, padding: '16px 20px',
                  border: `1px solid ${riskC.border}44`,
                  cursor: 'pointer', transition: 'border-color 0.2s',
                  display: 'flex', alignItems: 'center', gap: 16,
                }}
                onMouseEnter={e => (e.currentTarget.style.borderColor = riskC.border)}
                onMouseLeave={e => (e.currentTarget.style.borderColor = `${riskC.border}44`)}
              >
                {/* 风险色条 */}
                <div style={{ width: 4, alignSelf: 'stretch', borderRadius: 2, background: riskC.border, flexShrink: 0 }} />

                {/* 主信息 */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
                    <span style={{ fontWeight: 600, fontSize: 15, color: '#fff' }}>
                      {OPERATION_TYPE_LABELS[plan.operation_type] || plan.operation_type}
                    </span>
                    <RiskBadge level={plan.risk_level} />
                  </div>
                  <div style={{ color: '#999', fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {plan.impact.impact_summary}
                  </div>
                </div>

                {/* 影响数字 */}
                <div style={{ display: 'flex', gap: 16, flexShrink: 0 }}>
                  {plan.impact.affected_stores > 0 && (
                    <div style={{ textAlign: 'center' }}>
                      <div style={{ color: '#FF6B35', fontWeight: 700 }}>{plan.impact.affected_stores}</div>
                      <div style={{ color: '#888', fontSize: 11 }}>门店</div>
                    </div>
                  )}
                  {plan.impact.financial_impact_fen > 0 && (
                    <div style={{ textAlign: 'center' }}>
                      <div style={{ color: '#BA7517', fontWeight: 700 }}>{formatFen(plan.impact.financial_impact_fen)}</div>
                      <div style={{ color: '#888', fontSize: 11 }}>预估影响</div>
                    </div>
                  )}
                </div>

                {/* 倒计时 */}
                <div style={{ flexShrink: 0, textAlign: 'right', minWidth: 70 }}>
                  <Countdown expiresAt={plan.expires_at} />
                  <div style={{ color: '#888', fontSize: 11, marginTop: 4 }}>剩余确认</div>
                </div>

                {/* 箭头 */}
                <div style={{ color: '#888', fontSize: 18, flexShrink: 0 }}>›</div>
              </div>
            );
          })}
        </div>
      )}

      {/* 详情抽屉 */}
      {selectedPlan && (
        <PlanDrawer
          plan={selectedPlan}
          onClose={() => setSelectedPlan(null)}
          onAction={handleAction}
        />
      )}

      {/* 确认对话框 */}
      {selectedPlan && dialogAction && (
        <ConfirmDialog
          plan={selectedPlan}
          action={dialogAction}
          onClose={() => setDialogAction(null)}
          onSuccess={() => { fetchPlans(); setSelectedPlan(null); }}
        />
      )}
    </div>
  );
}
