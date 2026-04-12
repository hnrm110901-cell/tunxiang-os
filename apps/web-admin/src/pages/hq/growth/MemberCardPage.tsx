/**
 * 储值卡与积分管理页面
 * 深色主题，与 EventBusHealthPage 风格一致
 */
import { useEffect, useState, useCallback } from 'react';
import { txFetchData } from '../../../api';

// ─── 类型定义 ───

interface StoredValueCard {
  id: string;
  customer_id: string;
  customer_name?: string;
  phone?: string;
  balance_fen: number;
  bonus_balance_fen: number;
  total_recharged_fen: number;
  last_used_at?: string;
  card_level?: string;
}

interface RechargePlan {
  id: string;
  name: string;
  recharge_fen: number;
  bonus_fen: number;
  description?: string;
}

interface StoredValueTransaction {
  id: string;
  type: string;
  amount_fen: number;
  balance_after_fen: number;
  created_at: string;
  remark?: string;
}

interface PointsHistoryItem {
  id: string;
  customer_name?: string;
  source: string;
  amount: number;
  balance_after: number;
  created_at: string;
}

interface PointsEarnRule {
  spend_fen_per_point: number;
  expiry_days?: number;
  spend_fen_per_yuan?: number;
}

interface PointsSpendRule {
  points_per_yuan: number;
}

// ─── 工具函数 ───

function fenToYuan(fen: number): string {
  return (fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function maskPhone(phone: string): string {
  return phone.replace(/(\d{3})\d{4}(\d{4})/, '$1****$2');
}

function relativeTime(dateStr?: string): string {
  if (!dateStr) return '未使用';
  const diff = Date.now() - new Date(dateStr).getTime();
  const days = Math.floor(diff / 86400000);
  if (days === 0) return '今天';
  if (days === 1) return '昨天';
  if (days < 30) return `${days}天前`;
  if (days < 365) return `${Math.floor(days / 30)}个月前`;
  return `${Math.floor(days / 365)}年前`;
}

function formatDateTime(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function getSourceLabel(source: string): { label: string; color: string } {
  const map: Record<string, { label: string; color: string }> = {
    consume:    { label: '消费积分', color: '#0F6E56' },
    recharge:   { label: '充值赠送', color: '#4A90D9' },
    activity:   { label: '活动赠送', color: '#BA7517' },
    sign_in:    { label: '签到', color: '#7B68EE' },
    cash_offset:{ label: '积分抵现', color: '#FF7043' },
    exchange:   { label: '积分兑换', color: '#FF4D4D' },
    expire:     { label: '积分过期', color: '#666' },
  };
  return map[source] || { label: source, color: '#888' };
}

// ─── 充值弹窗 ───

interface RechargeModalProps {
  card: StoredValueCard;
  plans: RechargePlan[];
  onClose: () => void;
  onSuccess: () => void;
}

function RechargeModal({ card, plans, onClose, onSuccess }: RechargeModalProps) {
  const [selectedPlanId, setSelectedPlanId] = useState<string | null>(null);
  const [customAmount, setCustomAmount] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const selectedPlan = plans.find(p => p.id === selectedPlanId);
  const customAmountFen = customAmount ? Math.round(parseFloat(customAmount) * 100) : 0;

  const handleRecharge = async () => {
    if (!selectedPlanId && !customAmountFen) {
      setError('请选择充值套餐或输入自定义金额');
      return;
    }
    setLoading(true);
    setError('');
    try {
      if (selectedPlanId) {
        await txFetchData('/api/v1/member/stored-value/recharge-by-plan', {
          method: 'POST',
          body: JSON.stringify({ card_id: card.id, plan_id: selectedPlanId }),
        });
      } else {
        await txFetchData(`/api/v1/member/stored-value/accounts/${card.id}/recharge`, {
          method: 'POST',
          body: JSON.stringify({ amount_fen: customAmountFen }),
        });
      }
      onSuccess();
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '充值失败，请重试');
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
        background: '#1a2a33', borderRadius: 12, padding: 28, width: 440,
        border: '1px solid #2a3a44', boxShadow: '0 20px 60px rgba(0,0,0,0.5)',
      }} onClick={e => e.stopPropagation()}>
        {/* 弹窗标题 */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
          <div>
            <div style={{ color: '#fff', fontSize: 16, fontWeight: 700 }}>💳 储值充值</div>
            <div style={{ color: '#888', fontSize: 12, marginTop: 4 }}>
              {card.customer_name || '未知会员'}
              {card.phone ? ` · ${maskPhone(card.phone)}` : ''}
              {' · 当前余额：¥ ' + fenToYuan(card.balance_fen)}
            </div>
          </div>
          <button onClick={onClose} style={{
            background: 'transparent', border: 'none', color: '#888',
            cursor: 'pointer', fontSize: 20, lineHeight: 1,
          }}>×</button>
        </div>

        {/* 充值套餐 */}
        {plans.length > 0 && (
          <div style={{ marginBottom: 20 }}>
            <div style={{ color: '#888', fontSize: 12, marginBottom: 10 }}>充值套餐</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2,1fr)', gap: 10 }}>
              {plans.map(plan => (
                <div
                  key={plan.id}
                  onClick={() => { setSelectedPlanId(plan.id); setCustomAmount(''); }}
                  style={{
                    padding: '12px 14px', borderRadius: 8, cursor: 'pointer',
                    border: `2px solid ${selectedPlanId === plan.id ? '#0F6E56' : '#2a3a44'}`,
                    background: selectedPlanId === plan.id ? '#0F6E5620' : '#0d1e28',
                    transition: 'border-color .15s, background .15s',
                  }}
                >
                  <div style={{ color: '#fff', fontWeight: 700, fontSize: 15 }}>
                    ¥ {fenToYuan(plan.recharge_fen)}
                  </div>
                  {plan.bonus_fen > 0 && (
                    <div style={{ color: '#0F6E56', fontSize: 12, marginTop: 4 }}>
                      赠送 ¥ {fenToYuan(plan.bonus_fen)}
                    </div>
                  )}
                  {plan.name && (
                    <div style={{ color: '#888', fontSize: 11, marginTop: 2 }}>{plan.name}</div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 自定义金额 */}
        <div style={{ marginBottom: 20 }}>
          <div style={{ color: '#888', fontSize: 12, marginBottom: 8 }}>自定义金额（元）</div>
          <div style={{ position: 'relative' }}>
            <span style={{
              position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)',
              color: '#888', fontSize: 15,
            }}>¥</span>
            <input
              type="number"
              min="1"
              placeholder="输入金额"
              value={customAmount}
              onChange={e => { setCustomAmount(e.target.value); setSelectedPlanId(null); }}
              style={{
                width: '100%', padding: '10px 12px 10px 28px', borderRadius: 8,
                border: `1px solid ${customAmount && !selectedPlanId ? '#0F6E56' : '#2a3a44'}`,
                background: '#0d1e28', color: '#fff', fontSize: 14, outline: 'none',
                boxSizing: 'border-box',
              }}
            />
          </div>
        </div>

        {/* 确认信息 */}
        {(selectedPlan || customAmountFen > 0) && (
          <div style={{
            background: '#0F6E5610', border: '1px solid #0F6E5640', borderRadius: 8,
            padding: '12px 14px', marginBottom: 16, fontSize: 13,
          }}>
            <div style={{ color: '#0F6E56', fontWeight: 600 }}>充值确认</div>
            {selectedPlan ? (
              <>
                <div style={{ color: '#ccc', marginTop: 6 }}>充值金额：¥ {fenToYuan(selectedPlan.recharge_fen)}</div>
                {selectedPlan.bonus_fen > 0 && (
                  <div style={{ color: '#ccc' }}>赠送金额：¥ {fenToYuan(selectedPlan.bonus_fen)}</div>
                )}
                <div style={{ color: '#fff', fontWeight: 600, marginTop: 4 }}>
                  到账：¥ {fenToYuan(selectedPlan.recharge_fen + selectedPlan.bonus_fen)}
                </div>
              </>
            ) : (
              <div style={{ color: '#fff', fontWeight: 600, marginTop: 6 }}>
                到账：¥ {customAmount}
              </div>
            )}
          </div>
        )}

        {error && (
          <div style={{ color: '#FF4D4D', fontSize: 13, marginBottom: 12 }}>{error}</div>
        )}

        <div style={{ display: 'flex', gap: 10 }}>
          <button onClick={onClose} style={{
            flex: 1, padding: '10px 0', borderRadius: 8, border: '1px solid #2a3a44',
            background: 'transparent', color: '#888', cursor: 'pointer', fontSize: 14,
          }}>取消</button>
          <button onClick={handleRecharge} disabled={loading} style={{
            flex: 2, padding: '10px 0', borderRadius: 8, border: 'none',
            background: loading ? '#0a4a38' : '#0F6E56', color: '#fff',
            cursor: loading ? 'not-allowed' : 'pointer', fontSize: 14, fontWeight: 600,
          }}>
            {loading ? '处理中...' : '确认充值'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Tab 1：储值卡管理 ───

interface StoredValueTabProps {
  cards: StoredValueCard[];
  plans: RechargePlan[];
  loading: boolean;
  onRefresh: () => void;
}

function StoredValueTab({ cards, plans, loading, onRefresh }: StoredValueTabProps) {
  const [rechargeTarget, setRechargeTarget] = useState<StoredValueCard | null>(null);
  const [detailCard, setDetailCard] = useState<StoredValueCard | null>(null);
  const [transactions, setTransactions] = useState<StoredValueTransaction[]>([]);
  const [txLoading, setTxLoading] = useState(false);

  const totalBalance = cards.reduce((s, c) => s + c.balance_fen + c.bonus_balance_fen, 0);
  const totalRecharged = cards.reduce((s, c) => s + c.total_recharged_fen, 0);

  const openDetail = async (card: StoredValueCard) => {
    setDetailCard(card);
    setTxLoading(true);
    try {
      const result = await txFetchData<{ items: StoredValueTransaction[] }>(
        `/api/v1/member/stored-value/transactions/${card.id}?page=1&size=20`
      );
      setTransactions(result.items || []);
    } catch {
      setTransactions([]);
    } finally {
      setTxLoading(false);
    }
  };

  const statCards = [
    { label: '有效储值卡', value: cards.length.toString(), unit: '张', emoji: '💳' },
    { label: '储值余额总额', value: `¥ ${fenToYuan(totalBalance)}`, unit: '', emoji: '💰' },
    { label: '本月充值金额', value: `¥ ${fenToYuan(totalRecharged)}`, unit: '', emoji: '📈' },
    { label: '本月消费使用', value: '—', unit: '', emoji: '📉' },
  ];

  return (
    <div>
      {/* 统计卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 14, marginBottom: 24 }}>
        {statCards.map(sc => (
          <div key={sc.label} style={{
            background: '#1a2a33', borderRadius: 10, padding: '16px 18px',
            border: '1px solid #2a3a44',
          }}>
            <div style={{ fontSize: 22, marginBottom: 8 }}>{sc.emoji}</div>
            <div style={{ color: '#fff', fontSize: 20, fontWeight: 700 }}>
              {sc.value}
              {sc.unit && <span style={{ fontSize: 13, color: '#888', marginLeft: 4 }}>{sc.unit}</span>}
            </div>
            <div style={{ color: '#888', fontSize: 12, marginTop: 4 }}>{sc.label}</div>
          </div>
        ))}
      </div>

      {/* 储值卡列表 */}
      <div style={{ background: '#1a2a33', borderRadius: 12, overflow: 'hidden', border: '1px solid #2a3a44' }}>
        <div style={{
          padding: '14px 20px', borderBottom: '1px solid #2a3a44',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <span style={{ color: '#888', fontSize: 14 }}>储值卡列表（共 {cards.length} 张）</span>
          <button onClick={onRefresh} style={{
            padding: '4px 12px', borderRadius: 6, border: '1px solid #2a3a44',
            background: 'transparent', color: '#888', cursor: 'pointer', fontSize: 12,
          }}>↻ 刷新</button>
        </div>

        {loading ? (
          <div style={{ textAlign: 'center', padding: 48, color: '#888' }}>加载中...</div>
        ) : cards.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 48, color: '#888' }}>暂无储值卡数据</div>
        ) : (
          <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
            {cards.map(card => (
              <div key={card.id} style={{
                background: '#0d1e28', borderRadius: 10, padding: '16px 18px',
                border: '1px solid #2a3a4440',
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                gap: 16,
              }}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                    <span style={{ fontSize: 18 }}>💎</span>
                    <span style={{ color: '#fff', fontWeight: 700, fontSize: 15 }}>
                      {card.customer_name || '未知会员'}
                    </span>
                    {card.phone && (
                      <span style={{ color: '#888', fontSize: 13 }}>{maskPhone(card.phone)}</span>
                    )}
                    {card.card_level && (
                      <span style={{
                        padding: '2px 8px', borderRadius: 10, fontSize: 11,
                        background: '#BA751722', color: '#BA7517',
                      }}>{card.card_level}</span>
                    )}
                  </div>
                  <div style={{ display: 'flex', gap: 20, color: '#ccc', fontSize: 13 }}>
                    <span>
                      余额：<span style={{ color: '#fff', fontWeight: 600 }}>¥ {fenToYuan(card.balance_fen)}</span>
                    </span>
                    {card.bonus_balance_fen > 0 && (
                      <span>
                        赠送余额：<span style={{ color: '#0F6E56', fontWeight: 600 }}>¥ {fenToYuan(card.bonus_balance_fen)}</span>
                      </span>
                    )}
                    <span style={{ color: '#888' }}>
                      最近消费：{relativeTime(card.last_used_at)}
                    </span>
                    <span style={{ color: '#888' }}>
                      累计充值：¥ {fenToYuan(card.total_recharged_fen)}
                    </span>
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
                  <button onClick={() => setRechargeTarget(card)} style={{
                    padding: '6px 14px', borderRadius: 6,
                    border: '1px solid #0F6E56', background: '#0F6E5620',
                    color: '#0F6E56', cursor: 'pointer', fontSize: 13, fontWeight: 600,
                  }}>充值</button>
                  <button onClick={() => openDetail(card)} style={{
                    padding: '6px 14px', borderRadius: 6,
                    border: '1px solid #2a3a44', background: 'transparent',
                    color: '#888', cursor: 'pointer', fontSize: 13,
                  }}>查看</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 充值弹窗 */}
      {rechargeTarget && (
        <RechargeModal
          card={rechargeTarget}
          plans={plans}
          onClose={() => setRechargeTarget(null)}
          onSuccess={onRefresh}
        />
      )}

      {/* 流水详情弹窗 */}
      {detailCard && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
        }} onClick={() => setDetailCard(null)}>
          <div style={{
            background: '#1a2a33', borderRadius: 12, padding: 28, width: 520,
            maxHeight: '80vh', display: 'flex', flexDirection: 'column',
            border: '1px solid #2a3a44', boxShadow: '0 20px 60px rgba(0,0,0,0.5)',
          }} onClick={e => e.stopPropagation()}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
              <div>
                <div style={{ color: '#fff', fontSize: 15, fontWeight: 700 }}>
                  {detailCard.customer_name || '未知会员'} — 流水记录
                </div>
                <div style={{ color: '#888', fontSize: 12, marginTop: 2 }}>
                  当前余额：¥ {fenToYuan(detailCard.balance_fen)}
                  {detailCard.bonus_balance_fen > 0 && ` + 赠送 ¥ ${fenToYuan(detailCard.bonus_balance_fen)}`}
                </div>
              </div>
              <button onClick={() => setDetailCard(null)} style={{
                background: 'transparent', border: 'none', color: '#888',
                cursor: 'pointer', fontSize: 20,
              }}>×</button>
            </div>
            <div style={{ flex: 1, overflow: 'auto' }}>
              {txLoading ? (
                <div style={{ textAlign: 'center', padding: 32, color: '#888' }}>加载中...</div>
              ) : transactions.length === 0 ? (
                <div style={{ textAlign: 'center', padding: 32, color: '#888' }}>暂无流水记录</div>
              ) : (
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                  <thead>
                    <tr style={{ color: '#888', fontSize: 11 }}>
                      {['时间', '类型', '金额', '余额后'].map(h => (
                        <th key={h} style={{ padding: '6px 10px', textAlign: 'left', fontWeight: 500 }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {transactions.map(tx => (
                      <tr key={tx.id} style={{ borderTop: '1px solid #2a3a4440' }}>
                        <td style={{ padding: '8px 10px', color: '#888' }}>{formatDateTime(tx.created_at)}</td>
                        <td style={{ padding: '8px 10px', color: '#ccc' }}>{tx.type}</td>
                        <td style={{ padding: '8px 10px', color: tx.amount_fen >= 0 ? '#0F6E56' : '#FF4D4D', fontWeight: 600 }}>
                          {tx.amount_fen >= 0 ? '+' : ''}¥ {fenToYuan(Math.abs(tx.amount_fen))}
                        </td>
                        <td style={{ padding: '8px 10px', color: '#fff' }}>¥ {fenToYuan(tx.balance_after_fen)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Tab 2：积分管理 ───

interface PointsTabProps {
  history: PointsHistoryItem[];
  earnRules: PointsEarnRule | null;
  spendRules: PointsSpendRule | null;
  loading: boolean;
  onRefresh: () => void;
}

function PointsTab({ history, earnRules, spendRules, loading, onRefresh }: PointsTabProps) {
  const earned = history.filter(h => ['consume', 'recharge', 'activity', 'sign_in'].includes(h.source));
  const spent = history.filter(h => ['cash_offset', 'exchange', 'expire'].includes(h.source));
  const totalEarned = earned.reduce((s, h) => s + h.amount, 0);
  const totalSpent = spent.reduce((s, h) => s + Math.abs(h.amount), 0);
  const totalBalance = history.length > 0 ? history[0].balance_after : 0;

  const statCards = [
    { label: '本月发放积分', value: totalEarned.toLocaleString('zh-CN'), emoji: '🏆' },
    { label: '本月兑换积分', value: totalSpent.toLocaleString('zh-CN'), emoji: '💫' },
    { label: '积分余额总量', value: totalBalance.toLocaleString('zh-CN'), emoji: '📊' },
  ];

  return (
    <div>
      {/* 统计卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 14, marginBottom: 24 }}>
        {statCards.map(sc => (
          <div key={sc.label} style={{
            background: '#1a2a33', borderRadius: 10, padding: '16px 18px',
            border: '1px solid #2a3a44',
          }}>
            <div style={{ fontSize: 22, marginBottom: 8 }}>{sc.emoji}</div>
            <div style={{ color: '#fff', fontSize: 22, fontWeight: 700 }}>{sc.value}</div>
            <div style={{ color: '#888', fontSize: 12, marginTop: 4 }}>{sc.label}</div>
          </div>
        ))}
      </div>

      {/* 积分规则 */}
      <div style={{
        background: '#1a2a33', borderRadius: 12, padding: '16px 20px', marginBottom: 20,
        border: '1px solid #2a3a44',
      }}>
        <div style={{ color: '#888', fontSize: 12, marginBottom: 14, textTransform: 'uppercase', letterSpacing: '.08em', fontWeight: 700 }}>
          积分规则（只读）
        </div>
        <div style={{ display: 'flex', gap: 32, flexWrap: 'wrap' }}>
          <div>
            <div style={{ color: '#888', fontSize: 12 }}>消费获积分</div>
            <div style={{ color: '#fff', fontSize: 15, fontWeight: 600, marginTop: 4 }}>
              {earnRules
                ? `每消费 ¥${(earnRules.spend_fen_per_point / 100).toFixed(0)} 得 1 积分`
                : '—'}
            </div>
          </div>
          <div>
            <div style={{ color: '#888', fontSize: 12 }}>积分有效期</div>
            <div style={{ color: '#fff', fontSize: 15, fontWeight: 600, marginTop: 4 }}>
              {earnRules?.expiry_days ? `${earnRules.expiry_days} 天` : '永久有效'}
            </div>
          </div>
          <div>
            <div style={{ color: '#888', fontSize: 12 }}>兑换比例</div>
            <div style={{ color: '#fff', fontSize: 15, fontWeight: 600, marginTop: 4 }}>
              {spendRules ? `${spendRules.points_per_yuan} 积分 = ¥1` : '—'}
            </div>
          </div>
        </div>
      </div>

      {/* 积分流水 */}
      <div style={{ background: '#1a2a33', borderRadius: 12, overflow: 'hidden', border: '1px solid #2a3a44' }}>
        <div style={{
          padding: '14px 20px', borderBottom: '1px solid #2a3a44',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <span style={{ color: '#888', fontSize: 14 }}>积分流水（最近 {history.length} 条）</span>
          <button onClick={onRefresh} style={{
            padding: '4px 12px', borderRadius: 6, border: '1px solid #2a3a44',
            background: 'transparent', color: '#888', cursor: 'pointer', fontSize: 12,
          }}>↻ 刷新</button>
        </div>
        {loading ? (
          <div style={{ textAlign: 'center', padding: 48, color: '#888' }}>加载中...</div>
        ) : history.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 48, color: '#888' }}>暂无积分流水</div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: '#0d1e28' }}>
                {['时间', '会员', '操作类型', '积分变动', '操作后余额'].map(h => (
                  <th key={h} style={{
                    padding: '10px 16px', textAlign: 'left',
                    color: '#888', fontSize: 12, fontWeight: 500,
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {history.map(item => {
                const src = getSourceLabel(item.source);
                const isGain = item.amount > 0;
                return (
                  <tr key={item.id} style={{ borderBottom: '1px solid #2a3a4440' }}>
                    <td style={{ padding: '12px 16px', color: '#888', fontSize: 13 }}>
                      {formatDateTime(item.created_at)}
                    </td>
                    <td style={{ padding: '12px 16px', color: '#ccc', fontSize: 13 }}>
                      {item.customer_name || '—'}
                    </td>
                    <td style={{ padding: '12px 16px' }}>
                      <span style={{
                        padding: '2px 10px', borderRadius: 10, fontSize: 12,
                        background: `${src.color}22`, color: src.color,
                      }}>{src.label}</span>
                    </td>
                    <td style={{ padding: '12px 16px', fontWeight: 700, fontSize: 14, color: isGain ? '#0F6E56' : '#FF4D4D' }}>
                      {isGain ? '+' : ''}{item.amount.toLocaleString('zh-CN')}
                    </td>
                    <td style={{ padding: '12px 16px', color: '#fff', fontSize: 13 }}>
                      {item.balance_after.toLocaleString('zh-CN')}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// ─── 主页面 ───

export function MemberCardPage() {
  const [activeTab, setActiveTab] = useState<'stored-value' | 'points'>('stored-value');
  const [cards, setCards] = useState<StoredValueCard[]>([]);
  const [plans, setPlans] = useState<RechargePlan[]>([]);
  const [pointsHistory, setPointsHistory] = useState<PointsHistoryItem[]>([]);
  const [earnRules, setEarnRules] = useState<PointsEarnRule | null>(null);
  const [spendRules, setSpendRules] = useState<PointsSpendRule | null>(null);
  const [svLoading, setSvLoading] = useState(false);
  const [ptLoading, setPtLoading] = useState(false);

  const loadStoredValueData = useCallback(async () => {
    setSvLoading(true);
    try {
      const [plansRes] = await Promise.all([
        txFetchData<RechargePlan[]>('/api/v1/member/stored-value/plans'),
      ]);
      setPlans(Array.isArray(plansRes) ? plansRes : []);
      // 注：储值卡列表目前无全量列表端点，使用空数组占位
      // 实际数据通过搜索会员后获取各卡详情
      setCards([]);
    } catch {
      setPlans([]);
    } finally {
      setSvLoading(false);
    }
  }, []);

  const loadPointsData = useCallback(async () => {
    setPtLoading(true);
    try {
      // 积分流水：暂用 settlement 端点获取本月汇总
      const now = new Date();
      const month = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
      const settlement = await txFetchData<{
        store_settlements: { card_id: string; points_earned: number; points_spent: number }[];
        total_points_earned: number;
        total_points_spent: number;
      }>(`/api/v1/member/points/settlement/${month}`);

      // 将 settlement 汇总转换为展示用 history 条目
      const syntheticHistory: PointsHistoryItem[] = (settlement.store_settlements || []).map((s, i) => ({
        id: `${s.card_id}-${i}`,
        customer_name: s.card_id,
        source: s.points_earned > 0 ? 'consume' : 'cash_offset',
        amount: s.points_earned > 0 ? s.points_earned : -s.points_spent,
        balance_after: s.points_earned - s.points_spent,
        created_at: new Date().toISOString(),
      }));
      setPointsHistory(syntheticHistory);

      // 积分规则：占位默认值（后续接入 /api/v1/member/points/types/:id/earn-rules）
      setEarnRules({ spend_fen_per_point: 1000, expiry_days: 365 });
      setSpendRules({ points_per_yuan: 100 });
    } catch {
      setPointsHistory([]);
    } finally {
      setPtLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStoredValueData();
    loadPointsData();
  }, [loadStoredValueData, loadPointsData]);

  const tabs: { key: 'stored-value' | 'points'; label: string; emoji: string }[] = [
    { key: 'stored-value', label: '储值卡管理', emoji: '💳' },
    { key: 'points',       label: '积分管理',   emoji: '🏆' },
  ];

  return (
    <div style={{ padding: 24, minHeight: '100vh', background: '#0d1e28', color: '#fff' }}>
      {/* 页头 */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 24 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>💳 储值卡与积分</h2>
          <p style={{ color: '#888', margin: '4px 0 0', fontSize: 13 }}>
            储值账户管理 · 积分规则与流水
          </p>
        </div>
      </div>

      {/* Tab 导航 */}
      <div style={{
        display: 'flex', gap: 4, marginBottom: 24,
        background: '#1a2a33', borderRadius: 10, padding: 4,
        width: 'fit-content', border: '1px solid #2a3a44',
      }}>
        {tabs.map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            style={{
              padding: '8px 20px', borderRadius: 7, border: 'none', cursor: 'pointer',
              fontSize: 14, fontWeight: activeTab === tab.key ? 700 : 400,
              background: activeTab === tab.key ? '#0F6E56' : 'transparent',
              color: activeTab === tab.key ? '#fff' : '#888',
              transition: 'background .15s, color .15s',
            }}
          >
            {tab.emoji} {tab.label}
          </button>
        ))}
      </div>

      {/* Tab 内容 */}
      {activeTab === 'stored-value' ? (
        <StoredValueTab
          cards={cards}
          plans={plans}
          loading={svLoading}
          onRefresh={loadStoredValueData}
        />
      ) : (
        <PointsTab
          history={pointsHistory}
          earnRules={earnRules}
          spendRules={spendRules}
          loading={ptLoading}
          onRefresh={loadPointsData}
        />
      )}
    </div>
  );
}
