/**
 * 储值充值页面 — 服务员端
 * URL: /stored-value-recharge?member_id=xxx&member_name=xxx
 *
 * Step 1: 选金额（快捷按钮 + 自定义输入）
 * Step 2: 选支付方式
 * Step 3: 确认充值
 * 成功: 绿色确认 + 当前余额
 */
import { useState, useCallback } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { rechargeStoredValue, calcBonus } from '../api/storedValueApi';

// ─── 颜色常量 ───────────────────────────────────────────────────────────
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B35',
  green: '#22c55e',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
  red: '#ef4444',
  blue: '#3b82f6',
};

// ─── 快捷金额档位（分） ─────────────────────────────────────────────────
const PRESET_AMOUNTS = [100_00, 200_00, 500_00, 1_000_00, 2_000_00, 5_000_00];

// ─── 支付方式 ───────────────────────────────────────────────────────────
type PayMethod = 'cash' | 'wechat' | 'alipay' | 'card';
const PAY_METHODS: { id: PayMethod; label: string; icon: string }[] = [
  { id: 'cash',   label: '现金',   icon: '💵' },
  { id: 'wechat', label: '微信',   icon: '💚' },
  { id: 'alipay', label: '支付宝', icon: '🔵' },
  { id: 'card',   label: '刷卡',   icon: '💳' },
];

// ─── 工具 ───────────────────────────────────────────────────────────────
function fen2yuan(fen: number): string {
  return (fen / 100).toFixed(0);
}
function fen2yuanDecimal(fen: number): string {
  return (fen / 100).toFixed(2).replace(/\.00$/, '');
}

type Step = 'amount' | 'method' | 'confirm' | 'success';

export function StoredValueRechargePage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const memberId = searchParams.get('member_id') || '';
  const memberName = searchParams.get('member_name') || '会员';

  const [step, setStep] = useState<Step>('amount');
  const [selectedPreset, setSelectedPreset] = useState<number | null>(null);
  const [customYuan, setCustomYuan] = useState('');
  const [payMethod, setPayMethod] = useState<PayMethod | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [successBalance, setSuccessBalance] = useState(0);
  const [successBonus, setSuccessBonus] = useState(0);

  // 实际选中的充值金额（分）
  const amountFen: number = (() => {
    if (selectedPreset !== null) return selectedPreset;
    const yuan = parseFloat(customYuan);
    if (!isNaN(yuan) && yuan > 0) return Math.round(yuan * 100);
    return 0;
  })();

  const bonusFen = calcBonus(amountFen);

  // ── Step 1: 选金额 ──────────────────────────────────────────────────
  const handlePreset = (v: number) => {
    setSelectedPreset(v);
    setCustomYuan('');
  };

  const handleCustomInput = (v: string) => {
    setCustomYuan(v);
    setSelectedPreset(null);
  };

  const goToMethod = () => {
    if (amountFen < 100) {
      setError('充值金额最小1元');
      return;
    }
    setError('');
    setStep('method');
  };

  // ── Step 2: 选支付方式 ──────────────────────────────────────────────
  const handleSelectMethod = (m: PayMethod) => {
    setPayMethod(m);
    setStep('confirm');
  };

  // ── Step 3: 确认充值 ────────────────────────────────────────────────
  const handleConfirm = useCallback(async () => {
    if (!payMethod || amountFen < 100) return;
    setLoading(true);
    setError('');
    try {
      const operatorId = (window as unknown as Record<string, unknown>).__CREW_ID__ as string || 'unknown';
      const result = await rechargeStoredValue(memberId, {
        amount_fen: amountFen,
        payment_method: payMethod,
        operator_id: operatorId,
        note: bonusFen > 0 ? `充${fen2yuanDecimal(amountFen)}元赠${fen2yuanDecimal(bonusFen)}元` : undefined,
      });
      setSuccessBalance(result.balance_after_fen);
      setSuccessBonus(result.bonus_fen);
      setStep('success');
    } catch (err) {
      setError(err instanceof Error ? err.message : '充值失败，请重试');
    } finally {
      setLoading(false);
    }
  }, [memberId, amountFen, payMethod, bonusFen]);

  // ── 渲染 ─────────────────────────────────────────────────────────────
  return (
    <div style={{ padding: '16px 12px 80px', background: C.bg, minHeight: '100vh' }}>

      {/* 标题栏 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
        <button
          onClick={() => {
            if (step === 'amount') navigate(-1);
            else if (step === 'method') setStep('amount');
            else if (step === 'confirm') setStep('method');
            else navigate(-1);
          }}
          style={{
            minWidth: 44, minHeight: 44, borderRadius: 10,
            background: C.card, border: `1px solid ${C.border}`,
            color: C.text, fontSize: 20, cursor: 'pointer',
          }}
        >
          ←
        </button>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: C.white }}>储值充值</div>
          <div style={{ fontSize: 16, color: C.muted }}>{memberName}</div>
        </div>
      </div>

      {/* 步骤指示 */}
      {step !== 'success' && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 20, alignItems: 'center' }}>
          {(['amount', 'method', 'confirm'] as Step[]).map((s, i) => {
            const stepIdx = ['amount', 'method', 'confirm'].indexOf(step);
            const active = i === stepIdx;
            const done = i < stepIdx;
            return (
              <div key={s} style={{ display: 'flex', alignItems: 'center', flex: 1 }}>
                <div style={{
                  flex: 1, height: 4, borderRadius: 2,
                  background: done || active ? C.accent : C.border,
                }} />
                {i < 2 && <div style={{ width: 4 }} />}
              </div>
            );
          })}
          <div style={{ fontSize: 14, color: C.muted, whiteSpace: 'nowrap' }}>
            {step === 'amount' ? '① 选金额' : step === 'method' ? '② 支付方式' : '③ 确认'}
          </div>
        </div>
      )}

      {/* ── Step 1: 选金额 ── */}
      {step === 'amount' && (
        <>
          <div style={{
            background: C.card, borderRadius: 14, padding: 20,
            border: `1px solid ${C.border}`, marginBottom: 16,
          }}>
            <div style={{ fontSize: 17, fontWeight: 600, color: C.white, marginBottom: 14 }}>
              选择充值金额
            </div>

            {/* 快捷金额2列网格 */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 16 }}>
              {PRESET_AMOUNTS.map(v => {
                const bonus = calcBonus(v);
                const active = selectedPreset === v;
                return (
                  <button
                    key={v}
                    onClick={() => handlePreset(v)}
                    style={{
                      minHeight: 72, borderRadius: 12, cursor: 'pointer',
                      background: active ? `${C.accent}22` : C.bg,
                      border: `2px solid ${active ? C.accent : C.border}`,
                      display: 'flex', flexDirection: 'column',
                      alignItems: 'center', justifyContent: 'center', gap: 4,
                      position: 'relative',
                    }}
                  >
                    <span style={{ fontSize: 22, fontWeight: 700, color: active ? C.accent : C.white }}>
                      ¥{fen2yuan(v)}
                    </span>
                    {bonus > 0 && (
                      <span style={{
                        fontSize: 13, fontWeight: 600, color: C.red,
                        background: `${C.red}18`, borderRadius: 6, padding: '2px 8px',
                      }}>
                        赠¥{fen2yuan(bonus)}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>

            {/* 自定义输入 */}
            <div style={{ fontSize: 16, color: C.muted, marginBottom: 8 }}>或自定义金额</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 22, color: C.muted }}>¥</span>
              <input
                type="number"
                inputMode="decimal"
                placeholder="输入金额（元）"
                value={customYuan}
                onChange={e => handleCustomInput(e.target.value)}
                style={{
                  flex: 1, padding: '12px 14px', fontSize: 20,
                  background: C.bg, border: `1px solid ${C.border}`,
                  borderRadius: 10, color: C.white,
                }}
              />
            </div>

            {/* 赠送预览 */}
            {amountFen >= 100 && bonusFen > 0 && (
              <div style={{
                marginTop: 12, padding: '10px 14px', borderRadius: 10,
                background: `${C.red}12`, border: `1px solid ${C.red}44`,
                fontSize: 16, color: C.red, fontWeight: 600,
              }}>
                充¥{fen2yuanDecimal(amountFen)} 赠¥{fen2yuanDecimal(bonusFen)}，实到¥{fen2yuanDecimal(amountFen + bonusFen)}
              </div>
            )}
          </div>

          {error && <div style={{ fontSize: 16, color: C.red, marginBottom: 12 }}>{error}</div>}

          <button
            onClick={goToMethod}
            disabled={amountFen < 100}
            style={{
              width: '100%', minHeight: 56, borderRadius: 14,
              background: amountFen >= 100 ? C.accent : C.muted,
              color: C.white, border: 'none', fontSize: 18, fontWeight: 700,
              cursor: amountFen >= 100 ? 'pointer' : 'not-allowed',
            }}
          >
            下一步，选支付方式
          </button>
        </>
      )}

      {/* ── Step 2: 选支付方式 ── */}
      {step === 'method' && (
        <>
          <div style={{
            background: C.card, borderRadius: 14, padding: 20,
            border: `1px solid ${C.border}`, marginBottom: 16,
          }}>
            <div style={{ fontSize: 17, fontWeight: 600, color: C.white, marginBottom: 6 }}>
              选择支付方式
            </div>
            <div style={{ fontSize: 16, color: C.muted, marginBottom: 16 }}>
              充值金额 ¥{fen2yuanDecimal(amountFen)}
              {bonusFen > 0 && <span style={{ color: C.red, marginLeft: 8 }}>+赠¥{fen2yuanDecimal(bonusFen)}</span>}
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              {PAY_METHODS.map(m => (
                <button
                  key={m.id}
                  onClick={() => handleSelectMethod(m.id)}
                  style={{
                    minHeight: 72, borderRadius: 12, cursor: 'pointer',
                    background: C.bg, border: `2px solid ${C.border}`,
                    display: 'flex', flexDirection: 'column',
                    alignItems: 'center', justifyContent: 'center', gap: 6,
                  }}
                >
                  <span style={{ fontSize: 26 }}>{m.icon}</span>
                  <span style={{ fontSize: 17, fontWeight: 600, color: C.white }}>{m.label}</span>
                </button>
              ))}
            </div>
          </div>
        </>
      )}

      {/* ── Step 3: 确认充值 ── */}
      {step === 'confirm' && payMethod && (
        <>
          <div style={{
            background: C.card, borderRadius: 14, padding: 20,
            border: `1px solid ${C.border}`, marginBottom: 16,
          }}>
            <div style={{ fontSize: 17, fontWeight: 600, color: C.white, marginBottom: 16 }}>
              确认充值信息
            </div>

            {[
              { label: '会员', value: memberName, color: C.white },
              { label: '充值金额', value: `¥${fen2yuanDecimal(amountFen)}`, color: C.white },
              ...(bonusFen > 0 ? [{ label: '赠送金额', value: `¥${fen2yuanDecimal(bonusFen)}`, color: C.red }] : []),
              {
                label: '到账金额',
                value: `¥${fen2yuanDecimal(amountFen + bonusFen)}`,
                color: C.green,
              },
              {
                label: '支付方式',
                value: PAY_METHODS.find(m => m.id === payMethod)?.label ?? payMethod,
                color: C.white,
              },
            ].map(row => (
              <div key={row.label} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '12px 0', borderBottom: `1px solid ${C.border}`,
              }}>
                <span style={{ fontSize: 17, color: C.muted }}>{row.label}</span>
                <span style={{ fontSize: 17, fontWeight: 600, color: row.color }}>{row.value}</span>
              </div>
            ))}
          </div>

          {error && <div style={{ fontSize: 16, color: C.red, marginBottom: 12 }}>{error}</div>}

          <button
            onClick={handleConfirm}
            disabled={loading}
            style={{
              width: '100%', minHeight: 60, borderRadius: 14,
              background: loading ? C.muted : C.accent,
              color: C.white, border: 'none', fontSize: 19, fontWeight: 700,
              cursor: loading ? 'not-allowed' : 'pointer',
            }}
          >
            {loading ? '处理中...' : `确认收款 ¥${fen2yuanDecimal(amountFen)}`}
          </button>
        </>
      )}

      {/* ── 成功页面 ── */}
      {step === 'success' && (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          paddingTop: 40, gap: 16,
        }}>
          <div style={{
            width: 80, height: 80, borderRadius: 40,
            background: `${C.green}22`, border: `3px solid ${C.green}`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 36,
          }}>
            ✓
          </div>

          <div style={{ fontSize: 22, fontWeight: 700, color: C.green }}>
            充值成功
          </div>

          <div style={{
            background: C.card, borderRadius: 14, padding: 20,
            border: `1px solid ${C.border}`, width: '100%',
            textAlign: 'center',
          }}>
            <div style={{ fontSize: 16, color: C.muted, marginBottom: 8 }}>
              {memberName} 当前余额
            </div>
            <div style={{ fontSize: 36, fontWeight: 800, color: C.green }}>
              ¥{fen2yuanDecimal(successBalance)}
            </div>
            {successBonus > 0 && (
              <div style={{ fontSize: 16, color: C.red, marginTop: 8, fontWeight: 600 }}>
                本次含赠送 ¥{fen2yuanDecimal(successBonus)}
              </div>
            )}
          </div>

          <button
            onClick={() => navigate(-1)}
            style={{
              width: '100%', minHeight: 56, borderRadius: 14,
              background: C.card, color: C.text,
              border: `1px solid ${C.border}`, fontSize: 18, fontWeight: 600,
              cursor: 'pointer', marginTop: 8,
            }}
          >
            返回会员页
          </button>
        </div>
      )}
    </div>
  );
}
