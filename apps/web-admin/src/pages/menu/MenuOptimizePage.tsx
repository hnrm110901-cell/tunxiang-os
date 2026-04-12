/**
 * MenuOptimizePage — 智能排菜AI建议
 * 调用 POST /api/v1/brain/menu/optimize，展示AI排菜方案
 */
import { useState, useEffect } from 'react';
import { txFetchData } from '../../api';

// ─── 类型定义 ───

interface RecommendedDish {
  dish_id: string;
  dish_name: string;
  reason: string;
  expected_lift: string;
  priority: number;
}

interface ComboSuggestion {
  combo_name: string;
  dishes: string[];
  reason: string;
}

interface HardConstraint {
  constraint_id: string;
  label: string;
  detail: string;
}

interface MenuOptimizeResult {
  store_id: string;
  meal_period: string;
  date: string;
  recommended_dishes: RecommendedDish[];
  dishes_to_deplete: string[];
  combo_suggestions: ComboSuggestion[];
  menu_adjustments: string[];
  hard_constraints: HardConstraint[];
}

// ─── 餐段常量（固定配置，无需 API） ───

const MEAL_PERIODS = [
  { value: 'breakfast', label: '早市' },
  { value: 'lunch', label: '午市' },
  { value: 'dinner', label: '晚市' },
];

// ─── 工具函数 ───

function copyText(text: string, onSuccess: () => void) {
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).then(onSuccess).catch(() => {
      fallbackCopy(text, onSuccess);
    });
  } else {
    fallbackCopy(text, onSuccess);
  }
}

function fallbackCopy(text: string, onSuccess: () => void) {
  const el = document.createElement('textarea');
  el.value = text;
  el.style.position = 'fixed';
  el.style.opacity = '0';
  document.body.appendChild(el);
  el.select();
  document.execCommand('copy');
  document.body.removeChild(el);
  onSuccess();
}

function formatResultAsText(result: MenuOptimizeResult): string {
  const lines: string[] = [
    `屯象OS · 智能排菜建议`,
    `门店：${result.store_id}  餐段：${result.meal_period}  日期：${result.date}`,
    '',
    '== 重点推荐菜品 ==',
    ...result.recommended_dishes.map(
      (d, i) => `${i + 1}. ${d.dish_name}（优先级${d.priority}）\n   原因：${d.reason}\n   预期提升：${d.expected_lift}`,
    ),
    '',
    '== 今日待消耗菜品 ==',
    result.dishes_to_deplete.join('、'),
    '',
    '== 推荐套餐组合 ==',
    ...result.combo_suggestions.map(
      (c) => `${c.combo_name}：${c.dishes.join(' + ')}\n   理由：${c.reason}`,
    ),
    '',
    '== 菜单调整建议 ==',
    ...result.menu_adjustments.map((a, i) => `${i + 1}. ${a}`),
    '',
    '== 三条硬约束 ==',
    ...result.hard_constraints.map((c) => `• ${c.label}：${c.detail}`),
  ];
  return lines.join('\n');
}

// ─── 主组件 ───

export function MenuOptimizePage() {
  const today = new Date().toISOString().slice(0, 10);

  const [storeId, setStoreId] = useState('');
  const [stores, setStores] = useState<{ id: string; name: string }[]>([]);
  const [mealPeriod, setMealPeriod] = useState<string>('lunch');
  const [date, setDate] = useState(today);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<MenuOptimizeResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copyToast, setCopyToast] = useState(false);
  const [sendToast, setSendToast] = useState(false);

  useEffect(() => {
    txFetchData<{ items: { id: string; name: string }[] }>('/api/v1/org/stores?page=1&size=100')
      .then((data) => {
        if (data?.items?.length) {
          setStores(data.items);
          setStoreId(data.items[0].id);
        }
      })
      .catch(() => setStores([]));
  }, []);

  const handleGetAdvice = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const resp = await txFetchData<MenuOptimizeResult>('/api/v1/brain/menu-optimizer', {
        method: 'POST',
        body: JSON.stringify({ store_id: storeId, date, meal_period: mealPeriod }),
      });
      setResult(resp ?? null);
      if (!resp) {
        setError('AI 返回数据为空，请重试');
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '获取建议失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  const handleExport = () => {
    if (!result) return;
    const text = formatResultAsText(result);
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `menu-optimize-${result.date}-${result.meal_period}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleSendToChef = () => {
    setSendToast(true);
    setTimeout(() => setSendToast(false), 3000);
  };

  const handleCopyAll = () => {
    if (!result) return;
    copyText(formatResultAsText(result), () => {
      setCopyToast(true);
      setTimeout(() => setCopyToast(false), 2000);
    });
  };

  const storeName = stores.find((s) => s.id === storeId)?.name ?? storeId;
  const mealLabel = MEAL_PERIODS.find((m) => m.value === mealPeriod)?.label ?? mealPeriod;

  return (
    <div style={{ padding: 24, minHeight: '100vh', background: '#0d1e28', color: '#fff' }}>
      {/* 页头 */}
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>🧠 智能排菜AI建议</h2>
        <p style={{ color: '#888', margin: '4px 0 0', fontSize: 13 }}>
          基于库存状态与菜品表现，AI生成今日最优排菜方案
        </p>
      </div>

      {/* 触发区 */}
      <div style={{
        background: '#1a2a33', borderRadius: 12, border: '1px solid #2a3a44',
        padding: '20px 24px', marginBottom: 24,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
          {/* 门店 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={{ color: '#888', fontSize: 12 }}>门店</label>
            <select
              value={storeId}
              onChange={(e) => setStoreId(e.target.value)}
              style={selectStyle}
            >
              {stores.map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          </div>

          {/* 餐段 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={{ color: '#888', fontSize: 12 }}>餐段</label>
            <div style={{ display: 'flex', gap: 8 }}>
              {MEAL_PERIODS.map((m) => (
                <button
                  key={m.value}
                  onClick={() => setMealPeriod(m.value)}
                  style={{
                    padding: '6px 16px', borderRadius: 6, border: 'none', fontSize: 13,
                    background: mealPeriod === m.value ? '#FF6B35' : '#2a3a44',
                    color: mealPeriod === m.value ? '#fff' : '#ccc',
                    cursor: 'pointer', fontWeight: mealPeriod === m.value ? 700 : 400,
                    transition: 'background 0.15s',
                  }}
                >
                  {m.label}
                </button>
              ))}
            </div>
          </div>

          {/* 日期 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={{ color: '#888', fontSize: 12 }}>日期</label>
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              style={selectStyle}
            />
          </div>

          {/* 触发按钮 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignSelf: 'flex-end' }}>
            <label style={{ color: 'transparent', fontSize: 12 }}>_</label>
            <button
              onClick={handleGetAdvice}
              disabled={loading}
              style={{
                padding: '8px 20px', borderRadius: 6, border: 'none', fontSize: 14,
                background: loading ? '#2a3a44' : '#FF6B35',
                color: loading ? '#888' : '#fff',
                fontWeight: 600, cursor: loading ? 'not-allowed' : 'pointer',
                display: 'flex', alignItems: 'center', gap: 8,
                transition: 'background 0.2s',
              }}
            >
              {loading ? (
                <>
                  <span style={spinnerStyle} />
                  分析中...
                </>
              ) : '✨ 获取AI排菜建议'}
            </button>
          </div>
        </div>
      </div>

      {/* 错误提示 */}
      {error && (
        <div style={{
          background: '#A32D2D22', border: '1px solid #A32D2D55', borderRadius: 8,
          padding: '12px 16px', marginBottom: 20, color: '#FF6B6B', fontSize: 13,
        }}>
          ⚠️ {error}
        </div>
      )}

      {/* 加载中 */}
      {loading && (
        <div style={{
          background: '#1a2a33', borderRadius: 12, padding: '60px 24px', textAlign: 'center',
        }}>
          <div style={{ fontSize: 40, marginBottom: 14, display: 'inline-block', animation: 'tx-spin 1.5s linear infinite' }}>🧠</div>
          <div style={{ color: '#ccc', fontSize: 15 }}>AI 正在分析{storeName} · {mealLabel}排菜数据...</div>
          <div style={{ color: '#666', fontSize: 13, marginTop: 6 }}>通常需要3-8秒</div>
        </div>
      )}

      {/* 结果展示 */}
      {result && !loading && (
        <>
          {/* 操作栏 */}
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            marginBottom: 20, flexWrap: 'wrap', gap: 12,
          }}>
            <div style={{ color: '#888', fontSize: 13 }}>
              {storeName} · {mealLabel} · {result.date}
            </div>
            <div style={{ display: 'flex', gap: 10 }}>
              <button onClick={handleExport} style={actionBtnStyle}>
                📥 一键导出建议
              </button>
              <button onClick={handleSendToChef} style={actionBtnStyle}>
                👨‍🍳 发送给厨长
              </button>
              <button onClick={handleCopyAll} style={actionBtnStyle}>
                📋 复制全部
              </button>
            </div>
          </div>

          {/* Toast 提示 */}
          {sendToast && (
            <div style={toastStyle}>
              ✅ 已发送（功能开发中）
            </div>
          )}
          {copyToast && (
            <div style={toastStyle}>
              ✅ 已复制到剪贴板
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: 20 }}>

            {/* 1. 重点推荐菜品 */}
            <section>
              <SectionTitle>⭐ 重点推荐菜品</SectionTitle>
              <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
                {result.recommended_dishes.map((dish) => (
                  <div
                    key={dish.dish_id}
                    style={{
                      background: '#1a2a33',
                      border: dish.priority === 1 ? '2px solid #FF6B35' : '1px solid #2a3a44',
                      borderRadius: 10, padding: '16px 18px', minWidth: 200, flex: '1 1 200px',
                      maxWidth: 280, position: 'relative',
                    }}
                  >
                    {dish.priority === 1 && (
                      <span style={{
                        position: 'absolute', top: -10, right: 12, fontSize: 10,
                        background: '#FF6B35', color: '#fff', borderRadius: 6,
                        padding: '2px 8px', fontWeight: 700,
                      }}>
                        TOP PICK
                      </span>
                    )}
                    <div style={{ fontSize: 18, fontWeight: 800, color: '#fff', marginBottom: 6 }}>
                      {dish.dish_name}
                    </div>
                    <div style={{ fontSize: 12, color: '#185FA5', marginBottom: 8, lineHeight: 1.5 }}>
                      {dish.reason}
                    </div>
                    <div style={{
                      fontSize: 12, color: '#0F6E56', background: '#0F6E5622',
                      borderRadius: 4, padding: '3px 8px', display: 'inline-block',
                    }}>
                      {dish.expected_lift}
                    </div>
                    <div style={{
                      position: 'absolute', top: 12, left: 12, width: 20, height: 20,
                      borderRadius: '50%', background: dish.priority === 1 ? '#FF6B35' : '#2a3a44',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: 10, fontWeight: 700, color: '#fff',
                    }}>
                      {dish.priority}
                    </div>
                  </div>
                ))}
              </div>
            </section>

            {/* 2. 今日待消耗菜品 */}
            {result.dishes_to_deplete.length > 0 && (
              <section>
                <SectionTitle>⚠️ 今日待消耗菜品</SectionTitle>
                <div style={{
                  background: '#A32D2D22', border: '1px solid #A32D2D55', borderRadius: 8,
                  padding: '12px 16px', color: '#FF6B6B', fontSize: 14,
                }}>
                  <span style={{ fontWeight: 700, marginRight: 8 }}>以下食材临期，建议今日优先推售：</span>
                  {result.dishes_to_deplete.join('、')}
                </div>
              </section>
            )}

            {/* 3. 推荐套餐组合 */}
            {result.combo_suggestions.length > 0 && (
              <section>
                <SectionTitle>🍱 推荐套餐组合</SectionTitle>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                    <thead>
                      <tr style={{ background: '#1a2a33' }}>
                        <th style={thStyle}>套餐名</th>
                        <th style={thStyle}>菜品组合</th>
                        <th style={thStyle}>推荐理由</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.combo_suggestions.map((combo, idx) => (
                        <tr key={idx} style={{ borderBottom: '1px solid #2a3a44' }}>
                          <td style={tdStyle}>
                            <span style={{ fontWeight: 700, color: '#FF6B35' }}>{combo.combo_name}</span>
                          </td>
                          <td style={tdStyle}>
                            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                              {combo.dishes.map((d, i) => (
                                <span key={i} style={{
                                  background: '#185FA522', color: '#185FA5',
                                  borderRadius: 4, padding: '2px 8px', fontSize: 12,
                                }}>
                                  {d}
                                </span>
                              ))}
                            </div>
                          </td>
                          <td style={{ ...tdStyle, color: '#aaa' }}>{combo.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            {/* 4. 菜单调整建议 */}
            {result.menu_adjustments.length > 0 && (
              <section>
                <SectionTitle>📋 菜单调整建议</SectionTitle>
                <div style={{ background: '#1a2a33', borderRadius: 8, padding: '16px 20px' }}>
                  <ol style={{ margin: 0, paddingLeft: 20, lineHeight: 2 }}>
                    {result.menu_adjustments.map((item, idx) => (
                      <li key={idx} style={{ color: '#ccc', fontSize: 14 }}>{item}</li>
                    ))}
                  </ol>
                </div>
              </section>
            )}

            {/* 5. 三条硬约束 */}
            {result.hard_constraints.length > 0 && (
              <section>
                <SectionTitle>🔒 三条硬约束</SectionTitle>
                <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
                  {result.hard_constraints.map((c) => (
                    <div
                      key={c.constraint_id}
                      style={{
                        background: '#152028', border: '1px solid #2a3a44', borderRadius: 10,
                        padding: '14px 18px', flex: '1 1 200px',
                      }}
                    >
                      <div style={{ color: '#BA7517', fontSize: 13, fontWeight: 700, marginBottom: 6 }}>
                        {c.label}
                      </div>
                      <div style={{ color: '#888', fontSize: 12, lineHeight: 1.6 }}>{c.detail}</div>
                    </div>
                  ))}
                </div>
              </section>
            )}
          </div>
        </>
      )}

      {/* 空状态 */}
      {!result && !loading && !error && (
        <div style={{
          background: '#1a2a33', borderRadius: 12, border: '1px dashed #2a3a44',
          padding: '60px 24px', textAlign: 'center',
        }}>
          <div style={{ fontSize: 52, marginBottom: 14 }}>🧠</div>
          <div style={{ color: '#888', fontSize: 15 }}>选择门店、餐段和日期，点击「获取AI排菜建议」</div>
          <div style={{ color: '#666', fontSize: 13, marginTop: 6 }}>
            AI将分析库存状态、临期食材与历史菜品表现，约3-8秒出建议
          </div>
        </div>
      )}

      <style>{`
        @keyframes tx-spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}

// ─── 子组件 ───

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontSize: 15, fontWeight: 700, color: '#ddd',
      marginBottom: 12, display: 'flex', alignItems: 'center', gap: 6,
    }}>
      {children}
    </div>
  );
}

// ─── 样式常量 ───

const selectStyle: React.CSSProperties = {
  padding: '7px 12px', borderRadius: 6, border: '1px solid #2a3a44',
  background: '#152028', color: '#fff', fontSize: 13, cursor: 'pointer',
  outline: 'none', minWidth: 180,
};

const actionBtnStyle: React.CSSProperties = {
  padding: '7px 16px', borderRadius: 6, border: '1px solid #2a3a44',
  background: '#1a2a33', color: '#ccc', fontSize: 13, cursor: 'pointer',
  transition: 'background 0.15s, color 0.15s',
};

const spinnerStyle: React.CSSProperties = {
  display: 'inline-block', width: 14, height: 14,
  border: '2px solid #888', borderTopColor: '#fff',
  borderRadius: '50%', animation: 'tx-spin 0.7s linear infinite',
};

const thStyle: React.CSSProperties = {
  padding: '10px 14px', textAlign: 'left', color: '#888',
  fontSize: 12, fontWeight: 700, borderBottom: '1px solid #2a3a44',
};

const tdStyle: React.CSSProperties = {
  padding: '10px 14px', color: '#ccc', verticalAlign: 'top',
};

const toastStyle: React.CSSProperties = {
  position: 'fixed', bottom: 32, right: 32, zIndex: 9999,
  background: '#0F6E56', color: '#fff', borderRadius: 8,
  padding: '10px 20px', fontSize: 14, fontWeight: 600,
  boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
};
