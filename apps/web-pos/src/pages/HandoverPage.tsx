/**
 * 收银交班页面 — 四步交班流程
 * Step 1: 班次数据快照
 * Step 2: 现金清点(按面额)
 * Step 3: 差异确认
 * Step 4: 签字确认+提交
 * 触屏POS 1024px+, 深色主题, 最小字体16px, 热区>=48px
 * 调用 POST /api/v1/handover/*
 */
import { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';

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

/* ---------- Mock 班次数据 ---------- */
const MOCK_SHIFT = {
  shiftId: 'SH-20260327-001',
  cashierName: '王芳',
  startTime: '2026-03-27 10:00',
  endTime: '2026-03-27 15:30',
  totalOrders: 86,
  totalRevenueFen: 1728000,
  totalGuests: 258,
  avgPerGuestFen: 6698,
  channels: [
    { name: '微信支付', fen: 892000, color: '#07C160' },
    { name: '支付宝', fen: 486000, color: '#1677FF' },
    { name: '现金', fen: 215000, color: '#faad14' },
    { name: '银联刷卡', fen: 98000, color: '#e6002d' },
    { name: '企业挂账', fen: 45000, color: '#185FA5' },
    { name: '退款', fen: -8000, color: '#ff4d4f' },
  ],
  systemCashFen: 215000, // 系统记录应有现金
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

  // Step 2: 现金清点
  const [counts, setCounts] = useState<Record<string, number>>(
    Object.fromEntries(DENOMINATIONS.map(d => [d.label, 0]))
  );

  // Step 4: 签字
  const [signed, setSigned] = useState(false);
  const [remark, setRemark] = useState('');

  // 计算实点现金
  const actualCashFen = useMemo(() => {
    return DENOMINATIONS.reduce((sum, d) => sum + (counts[d.label] || 0) * d.valueFen, 0);
  }, [counts]);

  const diffFen = actualCashFen - MOCK_SHIFT.systemCashFen;

  const handleCountChange = (label: string, delta: number) => {
    setCounts(prev => ({
      ...prev,
      [label]: Math.max(0, (prev[label] || 0) + delta),
    }));
  };

  const handleSubmit = () => {
    if (!signed) {
      alert('请先确认签字');
      return;
    }
    // TODO: POST /api/v1/handover/submit
    alert('交班提交成功！');
    navigate('/dashboard');
  };

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
              <span style={{ fontSize: 16, color: C.muted }}>班次号: {MOCK_SHIFT.shiftId}</span>
              <span style={{ fontSize: 16, color: C.muted }}>收银员: {MOCK_SHIFT.cashierName}</span>
            </div>
            <div style={{ fontSize: 16, color: C.muted }}>
              {MOCK_SHIFT.startTime} ~ {MOCK_SHIFT.endTime}
            </div>
          </div>

          {/* KPI 卡片 */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
            {[
              { label: '订单总数', value: `${MOCK_SHIFT.totalOrders}`, sub: '单' },
              { label: '总营收', value: fen2yuan(MOCK_SHIFT.totalRevenueFen), sub: '' },
              { label: '客流量', value: `${MOCK_SHIFT.totalGuests}`, sub: '人' },
              { label: '客单价', value: fen2yuan(MOCK_SHIFT.avgPerGuestFen), sub: '' },
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
            {MOCK_SHIFT.channels.map(ch => (
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
              <span style={{ color: C.accent }}>{fen2yuan(MOCK_SHIFT.totalRevenueFen)}</span>
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
              {fen2yuan(MOCK_SHIFT.systemCashFen)}
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
                {fen2yuan(MOCK_SHIFT.systemCashFen)}
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
                { label: '班次号', value: MOCK_SHIFT.shiftId },
                { label: '收银员', value: MOCK_SHIFT.cashierName },
                { label: '时间段', value: `${MOCK_SHIFT.startTime.split(' ')[1]} ~ ${MOCK_SHIFT.endTime.split(' ')[1]}` },
                { label: '总订单', value: `${MOCK_SHIFT.totalOrders} 单` },
                { label: '总营收', value: fen2yuan(MOCK_SHIFT.totalRevenueFen) },
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
                我确认以上交班数据准确无误，{MOCK_SHIFT.cashierName} 签字确认
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
            disabled={!signed}
            style={{
              flex: 2, minHeight: 56, borderRadius: 12,
              background: signed ? C.green : '#1a2a33',
              border: 'none',
              color: signed ? C.white : C.muted,
              fontSize: 18, fontWeight: 700,
              cursor: signed ? 'pointer' : 'not-allowed',
              opacity: signed ? 1 : 0.5,
            }}
          >
            提交交班
          </button>
        )}
      </div>
    </div>
  );
}
