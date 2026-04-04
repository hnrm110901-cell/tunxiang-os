/**
 * 收银交班页面 — 四步交班流程
 * Step 1: 班次数据快照
 * Step 2: 现金清点(按面额)
 * Step 3: 差异确认
 * Step 4: 签字确认+提交
 * 触屏POS 1024px+, 深色主题, 最小字体16px, 热区>=48px
 * 调用 POST /api/v1/handover/*
 */
import { useState, useEffect, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  fetchShiftSnapshot,
  submitHandover,
  type ShiftSnapshot,
} from '../api/handoverApi';

/* ---------- 样式常量 ---------- */
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B2C',
  green: '#0F6E56',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
  danger: '#A32D2D',
  warning: '#BA7517',
};

const fen2yuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;

/* ---------- 配置 ---------- */
const STORE_ID = import.meta.env.VITE_STORE_ID || '';
const CASHIER_ID = localStorage.getItem('employeeId') || '';

const CHANNEL_COLORS: Record<string, string> = {
  wechat: '#07C160', alipay: '#1677FF', cash: '#faad14',
  unionpay: '#e6002d', credit_account: '#185FA5', refund: '#ff4d4f',
  微信支付: '#07C160', 支付宝: '#1677FF', 现金: '#faad14',
  银联刷卡: '#e6002d', 企业挂账: '#185FA5', 退款: '#ff4d4f',
};

/* ---------- 面额配置 ---------- */
const DENOMINATIONS = [
  { label: '100元', valueFen: 10000 },
  { label: '50元', valueFen: 5000 },
  { label: '20元', valueFen: 2000 },
  { label: '10元', valueFen: 1000 },
  { label: '5元', valueFen: 500 },
  { label: '1元', valueFen: 100 },
  { label: '硬币', valueFen: 100 },
];

/* ---------- 组件 ---------- */
export function HandoverPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);

  // 班次快照（从 API 加载）
  const [shift, setShift] = useState<ShiftSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Step 2: 现金清点
  const [counts, setCounts] = useState<Record<string, number>>(
    Object.fromEntries(DENOMINATIONS.map(d => [d.label, 0]))
  );

  // Step 4: 签字
  const [signed, setSigned] = useState(false);
  const [remark, setRemark] = useState('');

  // ── 加载班次快照 ──
  const loadSnapshot = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await fetchShiftSnapshot(STORE_ID, CASHIER_ID);
      setShift(data);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : '加载班次数据失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSnapshot();
  }, [loadSnapshot]);

  // 计算实点现金
  const actualCashFen = useMemo(() => {
    return DENOMINATIONS.reduce((sum, d) => sum + (counts[d.label] || 0) * d.valueFen, 0);
  }, [counts]);

  const systemCashFen = shift?.system_cash_fen ?? 0;
  const diffFen = actualCashFen - systemCashFen;

  const handleCountChange = (label: string, delta: number) => {
    setCounts(prev => ({
      ...prev,
      [label]: Math.max(0, (prev[label] || 0) + delta),
    }));
  };

  const handleSubmit = async () => {
    if (!signed || !shift) return;
    setSubmitting(true);
    try {
      await submitHandover({
        shift_id: shift.shift_id,
        store_id: STORE_ID,
        cashier_id: shift.cashier_id,
        cash_counts: DENOMINATIONS
          .filter(d => (counts[d.label] || 0) > 0)
          .map(d => ({ denomination: d.label, count: counts[d.label], subtotal_fen: counts[d.label] * d.valueFen })),
        actual_cash_fen: actualCashFen,
        diff_fen: diffFen,
        remark,
        signed: true,
      });
      alert('交班提交成功！');
      navigate('/dashboard');
    } catch (err) {
      alert(`交班提交失败: ${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setSubmitting(false);
    }
  };

  // 构造渠道展示数据
  const channels = (shift?.channels ?? []).map(ch => ({
    name: ch.channel,
    fen: ch.amount_fen,
    color: CHANNEL_COLORS[ch.channel] || C.muted,
  }));

  // ---------- 步骤指示器 ----------
  const steps = ['班次快照', '现金清点', '差异确认', '签字提交'];

  return (
    <div style={{ padding: 24, background: C.bg, minHeight: '100vh', color: C.white }}>
      {/* 顶部 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h2 style={{ margin: 0, fontSize: 24 }}>收银交班</h2>
        <button
          onClick={() => navigate('/dashboard')}
          style={{
            minHeight: 48, padding: '8px 20px', background: '#1a2a33',
            color: C.white, border: 'none', borderRadius: 8,
            cursor: 'pointer', fontSize: 16,
          }}
        >
          返回
        </button>
      </div>

      {/* 加载状态 */}
      {loading && (
        <div style={{ textAlign: 'center', padding: 60, color: C.muted, fontSize: 18 }}>加载班次数据中...</div>
      )}
      {loadError && (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <div style={{ color: '#ff4d4f', fontSize: 18, marginBottom: 12 }}>{loadError}</div>
          <button onClick={loadSnapshot} style={{
            padding: '10px 24px', background: C.accent, color: C.white,
            border: 'none', borderRadius: 8, fontSize: 16, cursor: 'pointer',
          }}>重试</button>
        </div>
      )}
      {!loading && !loadError && shift && (<>
      {/* 步骤指示器 */}
      <div style={{ display: 'flex', gap: 0, marginBottom: 24 }}>
        {steps.map((s, i) => {
          const stepNum = i + 1;
          const isActive = step === stepNum;
          const isDone = step > stepNum;
          return (
            <div key={s} style={{
              flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4,
            }}>
              <div style={{
                width: 36, height: 36, borderRadius: '50%',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 16, fontWeight: 700,
                background: isDone ? C.green : isActive ? C.accent : '#1a2a33',
                color: isDone || isActive ? C.white : C.muted,
                border: isActive ? `2px solid ${C.accent}` : 'none',
              }}>
                {isDone ? '\u2713' : stepNum}
              </div>
              <div style={{
                fontSize: 16, fontWeight: isActive ? 600 : 400,
                color: isActive ? C.accent : isDone ? C.green : C.muted,
              }}>
                {s}
              </div>
              {i < steps.length - 1 && (
                <div style={{
                  position: 'absolute',
                  width: `calc(${100 / steps.length}% - 40px)`,
                  height: 2,
                  background: isDone ? C.green : '#1a2a33',
                }} />
              )}
            </div>
          );
        })}
      </div>

      {/* Step 1: 班次数据快照 */}
      {step === 1 && (
        <div>
          {/* 班次信息 */}
          <div style={{
            background: C.card, borderRadius: 12, padding: 20, marginBottom: 16,
            border: `1px solid ${C.border}`,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
              <span style={{ fontSize: 16, color: C.muted }}>班次号: {shift?.shift_id}</span>
              <span style={{ fontSize: 16, color: C.muted }}>收银员: {shift?.cashier_name}</span>
            </div>
            <div style={{ fontSize: 16, color: C.muted }}>
              {(shift?.start_time ?? '')} ~ {(shift?.end_time ?? '')}
            </div>
          </div>

          {/* KPI 卡片 */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
            {[
              { label: '订单总数', value: `${(shift?.total_orders ?? 0)}`, sub: '单' },
              { label: '总营收', value: fen2yuan((shift?.total_revenue_fen ?? 0)), sub: '' },
              { label: '客流量', value: `${(shift?.total_guests ?? 0)}`, sub: '人' },
              { label: '客单价', value: fen2yuan((shift?.avg_per_guest_fen ?? 0)), sub: '' },
            ].map(kpi => (
              <div key={kpi.label} style={{
                background: C.card, borderRadius: 12, padding: 16, textAlign: 'center',
                border: `1px solid ${C.border}`,
                borderTop: `3px solid ${C.accent}`,
              }}>
                <div style={{ fontSize: 16, color: C.muted, marginBottom: 4 }}>{kpi.label}</div>
                <div style={{ fontSize: 28, fontWeight: 'bold', color: C.accent }}>
                  {kpi.value}
                </div>
                {kpi.sub && <div style={{ fontSize: 16, color: C.muted }}>{kpi.sub}</div>}
              </div>
            ))}
          </div>

          {/* 各渠道明细 */}
          <div style={{
            background: C.card, borderRadius: 12, padding: 20,
            border: `1px solid ${C.border}`,
          }}>
            <h3 style={{ margin: '0 0 16px', fontSize: 18 }}>各渠道金额</h3>
            {channels.map(ch => (
              <div key={ch.name} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '12px 0', borderBottom: `1px solid ${C.border}`,
                minHeight: 48,
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{
                    width: 10, height: 10, borderRadius: '50%',
                    background: ch.color, display: 'inline-block',
                  }} />
                  <span style={{ fontSize: 18 }}>{ch.name}</span>
                </div>
                <span style={{
                  fontSize: 18, fontWeight: 'bold',
                  color: ch.fen < 0 ? '#ff4d4f' : C.white,
                }}>
                  {ch.fen < 0 ? `-${fen2yuan(-ch.fen)}` : fen2yuan(ch.fen)}
                </span>
              </div>
            ))}
            <div style={{
              display: 'flex', justifyContent: 'space-between', paddingTop: 12,
              fontSize: 20, fontWeight: 'bold',
            }}>
              <span>合计</span>
              <span style={{ color: C.accent }}>{fen2yuan((shift?.total_revenue_fen ?? 0))}</span>
            </div>
          </div>
        </div>
      )}

      {/* Step 2: 现金清点 */}
      {step === 2 && (
        <div>
          <div style={{
            background: `${C.accent}15`, borderRadius: 12, padding: 16, marginBottom: 16,
            border: `1px solid ${C.accent}40`, textAlign: 'center',
          }}>
            <div style={{ fontSize: 16, color: C.muted, marginBottom: 4 }}>系统记录现金</div>
            <div style={{ fontSize: 32, fontWeight: 'bold', color: C.accent }}>
              {fen2yuan(systemCashFen)}
            </div>
          </div>

          <div style={{
            background: C.card, borderRadius: 12, padding: 20,
            border: `1px solid ${C.border}`,
          }}>
            <h3 style={{ margin: '0 0 16px', fontSize: 18 }}>按面额清点</h3>
            {DENOMINATIONS.map(d => (
              <div key={d.label} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '10px 0', borderBottom: `1px solid ${C.border}`,
                minHeight: 56,
              }}>
                <span style={{ fontSize: 18, minWidth: 80 }}>{d.label}</span>

                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <button
                    onClick={() => handleCountChange(d.label, -1)}
                    style={{
                      width: 48, height: 48, borderRadius: 8,
                      background: '#1a2a33', border: 'none',
                      color: C.white, fontSize: 24, cursor: 'pointer',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}
                  >
                    -
                  </button>
                  <span style={{
                    fontSize: 24, fontWeight: 'bold', minWidth: 48,
                    textAlign: 'center', color: C.white,
                  }}>
                    {counts[d.label]}
                  </span>
                  <button
                    onClick={() => handleCountChange(d.label, 1)}
                    style={{
                      width: 48, height: 48, borderRadius: 8,
                      background: C.accent, border: 'none',
                      color: C.white, fontSize: 24, cursor: 'pointer',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}
                  >
                    +
                  </button>
                </div>

                <span style={{ fontSize: 16, color: C.muted, minWidth: 80, textAlign: 'right' }}>
                  {fen2yuan((counts[d.label] || 0) * d.valueFen)}
                </span>
              </div>
            ))}

            <div style={{
              display: 'flex', justifyContent: 'space-between', paddingTop: 16,
              fontSize: 20, fontWeight: 'bold',
            }}>
              <span>实点合计</span>
              <span style={{ color: C.accent }}>{fen2yuan(actualCashFen)}</span>
            </div>
          </div>
        </div>
      )}

      {/* Step 3: 差异确认 */}
      {step === 3 && (
        <div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, marginBottom: 20 }}>
            <div style={{
              background: C.card, borderRadius: 12, padding: 20, textAlign: 'center',
              border: `1px solid ${C.border}`,
            }}>
              <div style={{ fontSize: 16, color: C.muted, marginBottom: 8 }}>系统金额</div>
              <div style={{ fontSize: 28, fontWeight: 'bold', color: C.white }}>
                {fen2yuan(systemCashFen)}
              </div>
            </div>
            <div style={{
              background: C.card, borderRadius: 12, padding: 20, textAlign: 'center',
              border: `1px solid ${C.border}`,
            }}>
              <div style={{ fontSize: 16, color: C.muted, marginBottom: 8 }}>实点金额</div>
              <div style={{ fontSize: 28, fontWeight: 'bold', color: C.accent }}>
                {fen2yuan(actualCashFen)}
              </div>
            </div>
            <div style={{
              background: diffFen === 0 ? `${C.green}20` : `${C.danger}20`,
              borderRadius: 12, padding: 20, textAlign: 'center',
              border: `2px solid ${diffFen === 0 ? C.green : C.danger}`,
            }}>
              <div style={{ fontSize: 16, color: C.muted, marginBottom: 8 }}>差异</div>
              <div style={{
                fontSize: 28, fontWeight: 'bold',
                color: diffFen === 0 ? C.green : C.danger,
              }}>
                {diffFen === 0 ? '无差异' : (diffFen > 0 ? '+' : '') + fen2yuan(diffFen)}
              </div>
            </div>
          </div>

          {diffFen !== 0 && (
            <div style={{
              background: `${C.danger}15`, borderRadius: 12, padding: 16, marginBottom: 16,
              border: `1px solid ${C.danger}`,
            }}>
              <div style={{ fontSize: 18, fontWeight: 700, color: C.danger, marginBottom: 8 }}>
                {diffFen > 0 ? '长款提醒' : '短款提醒'}
              </div>
              <div style={{ fontSize: 16, color: C.text }}>
                {diffFen > 0
                  ? `实点现金比系统多 ${fen2yuan(diffFen)}，请核实是否有未入账收入。`
                  : `实点现金比系统少 ${fen2yuan(-diffFen)}，请确认是否存在找零错误或遗失。`
                }
              </div>
            </div>
          )}

          {/* 面额明细回顾 */}
          <div style={{
            background: C.card, borderRadius: 12, padding: 20,
            border: `1px solid ${C.border}`,
          }}>
            <h3 style={{ margin: '0 0 16px', fontSize: 18 }}>清点明细</h3>
            {DENOMINATIONS.filter(d => (counts[d.label] || 0) > 0).map(d => (
              <div key={d.label} style={{
                display: 'flex', justifyContent: 'space-between',
                padding: '8px 0', borderBottom: `1px solid ${C.border}`,
                fontSize: 16,
              }}>
                <span>{d.label} x {counts[d.label]}</span>
                <span style={{ color: C.accent }}>{fen2yuan((counts[d.label] || 0) * d.valueFen)}</span>
              </div>
            ))}
            {DENOMINATIONS.every(d => (counts[d.label] || 0) === 0) && (
              <div style={{ fontSize: 16, color: C.muted, textAlign: 'center', padding: 16 }}>
                未清点任何面额，请返回上一步清点
              </div>
            )}
          </div>

          {/* 备注 */}
          <div style={{ marginTop: 16 }}>
            <label style={{ fontSize: 16, color: C.muted, display: 'block', marginBottom: 8 }}>
              差异备注（可选）
            </label>
            <textarea
              value={remark}
              onChange={e => setRemark(e.target.value)}
              placeholder="如有差异请说明原因..."
              style={{
                width: '100%', minHeight: 80, padding: 12,
                background: '#1a2a33', border: `1px solid ${C.border}`,
                borderRadius: 8, color: C.white, fontSize: 16,
                resize: 'vertical', boxSizing: 'border-box',
              }}
            />
          </div>
        </div>
      )}

      {/* Step 4: 签字确认 */}
      {step === 4 && (
        <div>
          {/* 交班汇总 */}
          <div style={{
            background: C.card, borderRadius: 12, padding: 20, marginBottom: 16,
            border: `1px solid ${C.border}`,
          }}>
            <h3 style={{ margin: '0 0 16px', fontSize: 18 }}>交班汇总</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              {[
                { label: '班次号', value: shift?.shift_id },
                { label: '收银员', value: shift?.cashier_name },
                { label: '时间段', value: `${(shift?.start_time ?? '').split(' ')[1]} ~ ${(shift?.end_time ?? '').split(' ')[1]}` },
                { label: '总订单', value: `${(shift?.total_orders ?? 0)} 单` },
                { label: '总营收', value: fen2yuan((shift?.total_revenue_fen ?? 0)) },
                { label: '现金差异', value: diffFen === 0 ? '无差异' : fen2yuan(diffFen) },
              ].map(item => (
                <div key={item.label} style={{
                  display: 'flex', justifyContent: 'space-between',
                  padding: '8px 0', borderBottom: `1px solid ${C.border}`,
                  fontSize: 16,
                }}>
                  <span style={{ color: C.muted }}>{item.label}</span>
                  <span style={{
                    fontWeight: 600,
                    color: item.label === '现金差异' && diffFen !== 0 ? C.danger : C.white,
                  }}>
                    {item.value}
                  </span>
                </div>
              ))}
            </div>
            {remark && (
              <div style={{ marginTop: 12, fontSize: 16, color: C.muted }}>
                备注: {remark}
              </div>
            )}
          </div>

          {/* 签字确认 */}
          <div style={{
            background: C.card, borderRadius: 12, padding: 20,
            border: `1px solid ${C.border}`,
          }}>
            <h3 style={{ margin: '0 0 16px', fontSize: 18 }}>确认签字</h3>
            <div
              onClick={() => setSigned(!signed)}
              style={{
                minHeight: 56, borderRadius: 12, display: 'flex',
                alignItems: 'center', justifyContent: 'center', gap: 12,
                cursor: 'pointer', fontSize: 18,
                background: signed ? `${C.green}20` : '#1a2a33',
                border: `2px solid ${signed ? C.green : C.border}`,
                color: signed ? C.green : C.muted,
              }}
            >
              <span style={{
                width: 28, height: 28, borderRadius: 6,
                border: `2px solid ${signed ? C.green : C.muted}`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                background: signed ? C.green : 'transparent',
                color: C.white, fontSize: 16, fontWeight: 'bold',
              }}>
                {signed ? '\u2713' : ''}
              </span>
              <span>
                我确认以上交班数据准确无误，{shift?.cashier_name} 签字确认
              </span>
            </div>
          </div>
        </div>
      )}

      {/* 底部导航按钮 */}
      <div style={{
        display: 'flex', gap: 12, marginTop: 24,
        justifyContent: 'space-between',
      }}>
        {step > 1 && (
          <button
            onClick={() => setStep(step - 1)}
            style={{
              flex: 1, minHeight: 56, borderRadius: 12,
              background: '#1a2a33', border: `1px solid ${C.border}`,
              color: C.white, fontSize: 18, fontWeight: 600, cursor: 'pointer',
            }}
          >
            上一步
          </button>
        )}
        {step < 4 ? (
          <button
            onClick={() => setStep(step + 1)}
            style={{
              flex: step > 1 ? 2 : 1, minHeight: 56, borderRadius: 12,
              background: C.accent, border: 'none',
              color: C.white, fontSize: 18, fontWeight: 700, cursor: 'pointer',
            }}
          >
            下一步
          </button>
        ) : (
          <button
            onClick={handleSubmit}
            disabled={!signed || submitting}
            style={{
              flex: 2, minHeight: 56, borderRadius: 12,
              background: signed && !submitting ? C.green : '#1a2a33',
              border: 'none',
              color: signed ? C.white : C.muted,
              fontSize: 18, fontWeight: 700,
              cursor: signed && !submitting ? 'pointer' : 'not-allowed',
              opacity: signed ? 1 : 0.5,
            }}
          >
            {submitting ? '提交中...' : '提交交班'}
          </button>
        )}
      </div>
      </>)}
    </div>
  );
}
