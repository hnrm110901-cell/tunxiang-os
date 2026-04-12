/**
 * CRMCampaignPage — 私域运营活动生成
 * 调用 POST /api/v1/brain/crm/campaign，生成微信群/朋友圈/小程序文案
 */
import { useState, useEffect } from 'react';
import { txFetchData } from '../../api';

// ─── 类型定义 ───

interface CampaignFormData {
  brand_name: string;
  campaign_type: string;
  target_audience: string;
  target_count: number;
  budget_yuan: number;
  key_dishes: string[];
  max_discount_pct: number;
  special_occasion: string;
}

interface CouponSuggestion {
  type: string;
  value_yuan: number;
  valid_days: number;
  description: string;
}

interface CampaignResult {
  campaign_id: string;
  brand_name: string;
  wechat_group_copy: string;
  moments_copy: string;
  miniapp_title: string;
  miniapp_body: string;
  coupon_suggestion: CouponSuggestion;
  send_time_suggestions: string[];
}

interface SavedCampaign {
  id: string;
  savedAt: string;
  form: CampaignFormData;
  result: CampaignResult;
}

// ─── 常量 ───

const CAMPAIGN_TYPES = [
  { value: 'retention', label: '留存活动' },
  { value: 'recall', label: '召回活动' },
  { value: 'upsell', label: '升单活动' },
  { value: 'event', label: '事件营销' },
  { value: 'holiday', label: '节假日' },
];

const TARGET_AUDIENCES = [
  { value: 'vip', label: 'VIP会员' },
  { value: 'regular', label: '普通会员' },
  { value: 'churn_risk', label: '流失风险客群' },
  { value: 'new', label: '新客' },
];

const DISH_OPTIONS = [
  '红烧五花肉', '剁椒鱼头', '麻婆豆腐', '香菇炒肉',
  '莴笋炒腊肉', '土鸡汤', '青椒炒蛋', '腊肉炒饭',
  '清蒸草鱼', '土豆丝', '辣椒炒肉', '豆角焖饭',
];

const MAX_SAVED = 20;

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

function loadSavedCampaigns(): SavedCampaign[] {
  try {
    const raw = localStorage.getItem('tx_crm_campaigns');
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveCampaigns(campaigns: SavedCampaign[]) {
  localStorage.setItem('tx_crm_campaigns', JSON.stringify(campaigns));
}

// ─── 主组件 ───

export function CRMCampaignPage() {
  // 表单状态
  const [form, setForm] = useState<CampaignFormData>({
    brand_name: '尝在一起',
    campaign_type: 'retention',
    target_audience: 'vip',
    target_count: 500,
    budget_yuan: 2000,
    key_dishes: [],
    max_discount_pct: 20,
    special_occasion: '',
  });

  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<CampaignResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [saveToast, setSaveToast] = useState(false);
  const [savedCampaigns, setSavedCampaigns] = useState<SavedCampaign[]>([]);
  const [showHistory, setShowHistory] = useState(false);

  useEffect(() => {
    setSavedCampaigns(loadSavedCampaigns());
  }, []);

  const updateForm = <K extends keyof CampaignFormData>(key: K, value: CampaignFormData[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const handleSubmit = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const payload = {
        ...form,
        budget_fen: Math.round(form.budget_yuan * 100), // 元→分
      };
      const data = await txFetchData<CampaignResult>('/api/v1/brain/crm/campaign', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      setResult(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '生成失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  const handleCopy = (key: string, text: string) => {
    copyText(text, () => {
      setCopiedKey(key);
      setTimeout(() => setCopiedKey(null), 2000);
    });
  };

  const handleSave = () => {
    if (!result) return;
    const saved = loadSavedCampaigns();
    const newItem: SavedCampaign = {
      id: `camp-${Date.now()}`,
      savedAt: new Date().toISOString(),
      form,
      result,
    };
    const updated = [newItem, ...saved].slice(0, MAX_SAVED);
    saveCampaigns(updated);
    setSavedCampaigns(updated);
    setSaveToast(true);
    setTimeout(() => setSaveToast(false), 2500);
  };

  const handleLoadHistory = (item: SavedCampaign) => {
    setForm(item.form);
    setResult(item.result);
    setShowHistory(false);
  };

  const handleDeleteHistory = (id: string) => {
    const updated = savedCampaigns.filter((c) => c.id !== id);
    saveCampaigns(updated);
    setSavedCampaigns(updated);
  };

  const toggleDish = (dish: string) => {
    const current = form.key_dishes;
    if (current.includes(dish)) {
      updateForm('key_dishes', current.filter((d) => d !== dish));
    } else {
      updateForm('key_dishes', [...current, dish]);
    }
  };

  const campaignTypeLabel = CAMPAIGN_TYPES.find((t) => t.value === form.campaign_type)?.label ?? '';
  const audienceLabel = TARGET_AUDIENCES.find((a) => a.value === form.target_audience)?.label ?? '';

  return (
    <div style={{ padding: 24, minHeight: '100vh', background: '#0d1e28', color: '#fff' }}>
      {/* 页头 */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 24 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>📢 私域运营活动生成</h2>
          <p style={{ color: '#888', margin: '4px 0 0', fontSize: 13 }}>
            AI生成微信群、朋友圈、小程序推送文案及优惠券方案
          </p>
        </div>
        <button
          onClick={() => setShowHistory(!showHistory)}
          style={{
            padding: '7px 16px', borderRadius: 6, border: '1px solid #2a3a44',
            background: showHistory ? '#2a3a44' : '#1a2a33', color: '#ccc',
            fontSize: 13, cursor: 'pointer',
          }}
        >
          📁 历史方案（{savedCampaigns.length}）
        </button>
      </div>

      {/* 历史方案抽屉 */}
      {showHistory && (
        <div style={{
          background: '#152028', borderRadius: 10, border: '1px solid #2a3a44',
          padding: 16, marginBottom: 24, maxHeight: 300, overflowY: 'auto',
        }}>
          {savedCampaigns.length === 0 ? (
            <div style={{ color: '#666', textAlign: 'center', padding: '20px 0', fontSize: 13 }}>
              暂无历史方案
            </div>
          ) : (
            savedCampaigns.map((item) => (
              <div
                key={item.id}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '10px 12px', borderRadius: 6, marginBottom: 6,
                  background: '#1a2a33', border: '1px solid #2a3a44',
                }}
              >
                <div>
                  <span style={{ color: '#fff', fontWeight: 600, fontSize: 13 }}>
                    {item.form.brand_name} · {CAMPAIGN_TYPES.find((t) => t.value === item.form.campaign_type)?.label}
                    {' · '}{TARGET_AUDIENCES.find((a) => a.value === item.form.target_audience)?.label}
                  </span>
                  <span style={{ color: '#666', fontSize: 11, marginLeft: 10 }}>
                    {new Date(item.savedAt).toLocaleString('zh-CN')}
                  </span>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button
                    onClick={() => handleLoadHistory(item)}
                    style={{ ...smallBtnStyle, color: '#185FA5' }}
                  >
                    载入
                  </button>
                  <button
                    onClick={() => handleDeleteHistory(item.id)}
                    style={{ ...smallBtnStyle, color: '#A32D2D' }}
                  >
                    删除
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '400px 1fr', gap: 24, alignItems: 'start' }}>

        {/* 左侧：配置表单 */}
        <div style={{
          background: '#1a2a33', borderRadius: 12, border: '1px solid #2a3a44',
          padding: '20px', position: 'sticky', top: 24,
        }}>
          <div style={{ color: '#888', fontSize: 12, letterSpacing: '0.05em', marginBottom: 16 }}>
            活动配置
          </div>

          {/* 品牌名称 */}
          <FormItem label="品牌名称">
            <input
              value={form.brand_name}
              onChange={(e) => updateForm('brand_name', e.target.value)}
              placeholder="如：尝在一起"
              style={inputStyle}
            />
          </FormItem>

          {/* 活动类型 */}
          <FormItem label="活动类型">
            <select
              value={form.campaign_type}
              onChange={(e) => updateForm('campaign_type', e.target.value)}
              style={inputStyle}
            >
              {CAMPAIGN_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </FormItem>

          {/* 目标人群 */}
          <FormItem label="目标人群">
            <select
              value={form.target_audience}
              onChange={(e) => updateForm('target_audience', e.target.value)}
              style={inputStyle}
            >
              {TARGET_AUDIENCES.map((a) => (
                <option key={a.value} value={a.value}>{a.label}</option>
              ))}
            </select>
          </FormItem>

          {/* 目标人数 */}
          <FormItem label="目标人数">
            <input
              type="number"
              value={form.target_count}
              onChange={(e) => updateForm('target_count', Number(e.target.value))}
              min={1}
              style={inputStyle}
            />
          </FormItem>

          {/* 活动预算 */}
          <FormItem label="活动预算（元）">
            <input
              type="number"
              value={form.budget_yuan}
              onChange={(e) => updateForm('budget_yuan', Number(e.target.value))}
              min={0}
              style={inputStyle}
            />
            <div style={{ color: '#666', fontSize: 11, marginTop: 3 }}>
              提交时将自动转换为分（×100）
            </div>
          </FormItem>

          {/* 重点菜品 */}
          <FormItem label="重点菜品（多选）">
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {DISH_OPTIONS.map((dish) => (
                <button
                  key={dish}
                  onClick={() => toggleDish(dish)}
                  style={{
                    padding: '4px 10px', borderRadius: 4, fontSize: 12, border: 'none',
                    background: form.key_dishes.includes(dish) ? '#FF6B35' : '#2a3a44',
                    color: form.key_dishes.includes(dish) ? '#fff' : '#aaa',
                    cursor: 'pointer', transition: 'background 0.15s',
                  }}
                >
                  {dish}
                </button>
              ))}
            </div>
          </FormItem>

          {/* 最大折扣率 */}
          <FormItem label={`最大折扣率：${form.max_discount_pct}%`}>
            <input
              type="range"
              min={0}
              max={50}
              step={5}
              value={form.max_discount_pct}
              onChange={(e) => updateForm('max_discount_pct', Number(e.target.value))}
              style={{ width: '100%', accentColor: '#FF6B35' }}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', color: '#666', fontSize: 11 }}>
              <span>0%</span><span>50%</span>
            </div>
          </FormItem>

          {/* 特殊场合 */}
          <FormItem label="特殊场合（可选）">
            <input
              value={form.special_occasion}
              onChange={(e) => updateForm('special_occasion', e.target.value)}
              placeholder="如：母亲节、店庆日"
              style={inputStyle}
            />
          </FormItem>

          {/* 提交 */}
          <button
            onClick={handleSubmit}
            disabled={loading}
            style={{
              width: '100%', padding: '12px 0', borderRadius: 8, border: 'none',
              background: loading ? '#2a3a44' : '#FF6B35',
              color: loading ? '#888' : '#fff',
              fontSize: 15, fontWeight: 700, cursor: loading ? 'not-allowed' : 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
              marginTop: 8, transition: 'background 0.2s',
            }}
          >
            {loading ? (
              <>
                <span style={spinnerStyle} />
                生成中...
              </>
            ) : '✨ 生成活动方案'}
          </button>
        </div>

        {/* 右侧：结果展示 */}
        <div>
          {/* 错误 */}
          {error && (
            <div style={{
              background: '#A32D2D22', border: '1px solid #A32D2D55', borderRadius: 8,
              padding: '12px 16px', marginBottom: 16, color: '#FF6B6B', fontSize: 13,
            }}>
              ⚠️ {error}
            </div>
          )}

          {/* 加载中 */}
          {loading && (
            <div style={{
              background: '#1a2a33', borderRadius: 12, padding: '60px 24px', textAlign: 'center',
            }}>
              <div style={{ fontSize: 40, marginBottom: 14, display: 'inline-block', animation: 'tx-spin 1.5s linear infinite' }}>📢</div>
              <div style={{ color: '#ccc', fontSize: 15 }}>AI 正在生成{campaignTypeLabel}文案...</div>
              <div style={{ color: '#666', fontSize: 13, marginTop: 6 }}>
                针对 {audienceLabel}，约3-8秒出方案
              </div>
            </div>
          )}

          {/* 空态 */}
          {!result && !loading && !error && (
            <div style={{
              background: '#1a2a33', borderRadius: 12, border: '1px dashed #2a3a44',
              padding: '60px 24px', textAlign: 'center',
            }}>
              <div style={{ fontSize: 52, marginBottom: 14 }}>📢</div>
              <div style={{ color: '#888', fontSize: 15 }}>配置活动参数后，点击「生成活动方案」</div>
              <div style={{ color: '#666', fontSize: 13, marginTop: 6 }}>
                AI将生成4类文案 + 优惠券建议 + 发送时间建议
              </div>
            </div>
          )}

          {/* 结果 */}
          {result && !loading && (
            <>
              {/* 保存操作 */}
              <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
                <button onClick={handleSave} style={actionBtnStyle}>
                  💾 保存方案
                </button>
              </div>

              {saveToast && (
                <div style={toastStyle}>✅ 方案已保存</div>
              )}

              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

                {/* 1. 微信群文案 */}
                <CopyBlock
                  title="💬 微信群文案"
                  hint="≤ 300字"
                  content={result.wechat_group_copy}
                  onCopy={() => handleCopy('wechat', result.wechat_group_copy)}
                  copied={copiedKey === 'wechat'}
                  rows={6}
                />

                {/* 2. 朋友圈文案 */}
                <CopyBlock
                  title="🌟 朋友圈文案"
                  hint="≤ 140字"
                  content={result.moments_copy}
                  onCopy={() => handleCopy('moments', result.moments_copy)}
                  copied={copiedKey === 'moments'}
                  rows={4}
                />

                {/* 3. 小程序推送 */}
                <div style={{ background: '#1a2a33', borderRadius: 10, border: '1px solid #2a3a44', padding: 16 }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                    <div>
                      <span style={{ fontSize: 14, fontWeight: 700, color: '#fff' }}>📱 小程序推送</span>
                      <span style={{ color: '#666', fontSize: 11, marginLeft: 8 }}>标题≤15字 + 内容≤30字</span>
                    </div>
                    <button
                      onClick={() => handleCopy('miniapp', `${result.miniapp_title}\n${result.miniapp_body}`)}
                      style={copyBtnStyle(copiedKey === 'miniapp')}
                    >
                      {copiedKey === 'miniapp' ? '✅ 已复制' : '📋 复制'}
                    </button>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    <div>
                      <span style={{ color: '#888', fontSize: 11 }}>标题（{result.miniapp_title.length}/15）</span>
                      <input
                        readOnly
                        value={result.miniapp_title}
                        style={{ ...inputStyle, marginTop: 4, background: '#0d1e28' }}
                      />
                    </div>
                    <div>
                      <span style={{ color: '#888', fontSize: 11 }}>内容（{result.miniapp_body.length}/30）</span>
                      <input
                        readOnly
                        value={result.miniapp_body}
                        style={{ ...inputStyle, marginTop: 4, background: '#0d1e28' }}
                      />
                    </div>
                  </div>
                </div>

                {/* 4. 优惠券建议 */}
                {result.coupon_suggestion && (
                  <div style={{ background: '#1a2a33', borderRadius: 10, border: '1px solid #2a3a44', padding: 16 }}>
                    <div style={{ fontSize: 14, fontWeight: 700, color: '#fff', marginBottom: 12 }}>
                      🎫 优惠券建议
                    </div>
                    <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
                      <CouponField label="类型" value={result.coupon_suggestion.type} />
                      <CouponField label="面值" value={`¥${result.coupon_suggestion.value_yuan}`} accent />
                      <CouponField label="有效期" value={`${result.coupon_suggestion.valid_days}天`} />
                      {result.coupon_suggestion.description && (
                        <CouponField label="说明" value={result.coupon_suggestion.description} wide />
                      )}
                    </div>
                  </div>
                )}

                {/* 5. 发送时间建议 */}
                {result.send_time_suggestions?.length > 0 && (
                  <div style={{ background: '#1a2a33', borderRadius: 10, border: '1px solid #2a3a44', padding: 16 }}>
                    <div style={{ fontSize: 14, fontWeight: 700, color: '#fff', marginBottom: 10 }}>
                      ⏰ 发送时间建议
                    </div>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                      {result.send_time_suggestions.map((t, i) => (
                        <span
                          key={i}
                          style={{
                            padding: '4px 14px', borderRadius: 20, fontSize: 13,
                            background: '#185FA522', color: '#185FA5',
                            border: '1px solid #185FA533',
                          }}
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>

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

function FormItem({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <label style={{ color: '#888', fontSize: 12, display: 'block', marginBottom: 6 }}>{label}</label>
      {children}
    </div>
  );
}

function CopyBlock({
  title, hint, content, onCopy, copied, rows,
}: {
  title: string;
  hint: string;
  content: string;
  onCopy: () => void;
  copied: boolean;
  rows: number;
}) {
  return (
    <div style={{ background: '#1a2a33', borderRadius: 10, border: '1px solid #2a3a44', padding: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
        <div>
          <span style={{ fontSize: 14, fontWeight: 700, color: '#fff' }}>{title}</span>
          <span style={{ color: '#666', fontSize: 11, marginLeft: 8 }}>{hint}</span>
        </div>
        <button onClick={onCopy} style={copyBtnStyle(copied)}>
          {copied ? '✅ 已复制' : '📋 复制'}
        </button>
      </div>
      <textarea
        readOnly
        value={content}
        rows={rows}
        style={{
          width: '100%', background: '#0d1e28', border: '1px solid #2a3a44',
          borderRadius: 6, color: '#ccc', fontSize: 13, padding: '10px 12px',
          resize: 'none', outline: 'none', lineHeight: 1.7, boxSizing: 'border-box',
          fontFamily: 'inherit',
        }}
      />
      <div style={{ textAlign: 'right', color: '#555', fontSize: 11, marginTop: 4 }}>
        {content.length} 字
      </div>
    </div>
  );
}

function CouponField({ label, value, accent, wide }: { label: string; value: string; accent?: boolean; wide?: boolean }) {
  return (
    <div style={{ flex: wide ? '1 1 200px' : '0 0 auto' }}>
      <div style={{ color: '#666', fontSize: 11, marginBottom: 3 }}>{label}</div>
      <div style={{
        fontSize: accent ? 22 : 14, fontWeight: accent ? 800 : 600,
        color: accent ? '#FF6B35' : '#ccc',
      }}>
        {value}
      </div>
    </div>
  );
}

// ─── 样式常量 ───

const inputStyle: React.CSSProperties = {
  width: '100%', padding: '7px 12px', borderRadius: 6,
  border: '1px solid #2a3a44', background: '#152028',
  color: '#fff', fontSize: 13, outline: 'none', boxSizing: 'border-box',
};

const actionBtnStyle: React.CSSProperties = {
  padding: '7px 16px', borderRadius: 6, border: '1px solid #2a3a44',
  background: '#1a2a33', color: '#ccc', fontSize: 13, cursor: 'pointer',
  transition: 'background 0.15s',
};

const smallBtnStyle: React.CSSProperties = {
  padding: '4px 12px', borderRadius: 4, border: '1px solid #2a3a44',
  background: 'transparent', fontSize: 12, cursor: 'pointer',
};

const spinnerStyle: React.CSSProperties = {
  display: 'inline-block', width: 14, height: 14,
  border: '2px solid #888', borderTopColor: '#fff',
  borderRadius: '50%', animation: 'tx-spin 0.7s linear infinite',
};

const toastStyle: React.CSSProperties = {
  position: 'fixed', bottom: 32, right: 32, zIndex: 9999,
  background: '#0F6E56', color: '#fff', borderRadius: 8,
  padding: '10px 20px', fontSize: 14, fontWeight: 600,
  boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
};

function copyBtnStyle(copied: boolean): React.CSSProperties {
  return {
    padding: '5px 12px', borderRadius: 5,
    border: `1px solid ${copied ? '#0F6E5655' : '#2a3a44'}`,
    background: copied ? '#0F6E5622' : '#152028',
    color: copied ? '#0F6E56' : '#888',
    fontSize: 12, cursor: 'pointer', transition: 'all 0.2s', whiteSpace: 'nowrap',
  };
}
