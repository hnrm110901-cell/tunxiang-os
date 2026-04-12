/**
 * OfferCenterPage — 权益策略中心
 * 路由: /hq/growth/offers
 * 活跃/过期/草稿统计 + 券模板网格 + 创建表单 + 核销分析
 * 数据来源: GET/POST /api/v1/member/promotions
 */
import { useState, useEffect, useCallback } from 'react';
import { txFetchData } from '../../../api';

// ---- 颜色常量 ----
const BG_1 = '#112228';
const BG_2 = '#1a2a33';
const BRAND = '#FF6B2C';
const GREEN = '#52c41a';
const RED = '#ff4d4f';
const YELLOW = '#faad14';
const BLUE = '#1890ff';
const PURPLE = '#722ed1';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

// ---- 类型定义 ----
type TabKey = 'overview' | 'templates' | 'create' | 'analytics';
type OfferCategory = '全部' | '新客' | '复购' | '老带新' | '储值' | '新品' | '低峰';
type OfferStatus = 'active' | 'expired' | 'scheduled';

interface OfferTemplate {
  id: string;
  name: string;
  category: OfferCategory;
  type: '满减' | '折扣' | '赠品' | '免费' | '积分' | '储值';
  rule: string;
  marginImpact: number;
  totalIssued: number;
  totalRedeemed: number;
  avgOrderIncrease: number;
  status: '生效中' | '已过期' | '草稿';
  validDays: number;
}

interface RedemptionStat {
  date: string;
  issued: number;
  redeemed: number;
  expired: number;
  revenue: number;
}

interface PromotionListResponse {
  items: OfferTemplate[];
  total: number;
}

interface RedemptionStatsResponse {
  items: RedemptionStat[];
  total: number;
}

interface OverviewStats {
  active: number;
  expired: number;
  draft: number;
  totalRedeemed: number;
  avgRedemptionRate: number;
}

// ---- 新建优惠表单类型 ----
interface CreateOfferPayload {
  name: string;
  type: string;
  category: string;
  brand: string;
  minAmount: number;
  discountAmount: number;
  validDays: number;
  totalLimit: number;
  status: 'active' | 'draft';
}

// ---- 工具函数 ----
function computeOverview(templates: OfferTemplate[]): OverviewStats {
  const active = templates.filter(t => t.status === '生效中').length;
  const expired = templates.filter(t => t.status === '已过期').length;
  const draft = templates.filter(t => t.status === '草稿').length;
  const totalRedeemed = templates.reduce((a, t) => a + t.totalRedeemed, 0);
  const validTemplates = templates.filter(t => t.totalIssued > 0);
  const avgRedemptionRate = validTemplates.length > 0
    ? validTemplates.reduce((a, t) => a + (t.totalRedeemed / t.totalIssued * 100), 0) / validTemplates.length
    : 0;
  return { active, expired, draft, totalRedeemed, avgRedemptionRate };
}

// ---- 加载骨架 ----
function Skeleton({ width = '100%', height = 24, radius = 6 }: { width?: string | number; height?: number; radius?: number }) {
  return (
    <div style={{
      width, height, borderRadius: radius,
      background: `linear-gradient(90deg, ${BG_2} 25%, #1e3040 50%, ${BG_2} 75%)`,
      backgroundSize: '200% 100%',
      animation: 'shimmer 1.5s infinite',
    }} />
  );
}

// ---- 错误提示 ----
function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div style={{
      padding: '12px 16px', borderRadius: 8, marginBottom: 12,
      background: RED + '11', borderLeft: `3px solid ${RED}`,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    }}>
      <span style={{ fontSize: 13, color: RED }}>{message}</span>
      {onRetry && (
        <button onClick={onRetry} style={{
          padding: '4px 12px', borderRadius: 6, border: `1px solid ${RED}`,
          background: 'transparent', color: RED, fontSize: 12, cursor: 'pointer',
        }}>重试</button>
      )}
    </div>
  );
}

// ---- 概览统计卡片 ----
function OverviewCards({ templates, loading, error, onRetry }: {
  templates: OfferTemplate[];
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  if (error) return <ErrorBanner message={error} onRetry={onRetry} />;

  const stats = loading ? null : computeOverview(templates);

  const cards = [
    { label: '生效中', value: stats ? stats.active : null, color: GREEN },
    { label: '已过期', value: stats ? stats.expired : null, color: TEXT_4 },
    { label: '草稿', value: stats ? stats.draft : null, color: YELLOW },
    { label: '总核销数', value: stats ? stats.totalRedeemed.toLocaleString() : null, color: BRAND },
    { label: '平均核销率', value: stats ? `${stats.avgRedemptionRate.toFixed(1)}%` : null, color: BLUE },
  ];

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12, marginBottom: 16 }}>
      {cards.map((c, i) => (
        <div key={i} style={{
          background: BG_1, borderRadius: 10, padding: '16px 18px',
          border: `1px solid ${BG_2}`,
        }}>
          <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 6 }}>{c.label}</div>
          {loading ? (
            <Skeleton height={32} radius={4} />
          ) : (
            <div style={{ fontSize: 28, fontWeight: 700, color: c.color }}>{c.value}</div>
          )}
        </div>
      ))}
    </div>
  );
}

// ---- 优惠券网格 ----
function OfferGrid({
  templates, categoryFilter, loading, error, onRetry,
}: {
  templates: OfferTemplate[];
  categoryFilter: OfferCategory;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  if (error) return <ErrorBanner message={`加载优惠券失败：${error}`} onRetry={onRetry} />;

  const filtered = categoryFilter === '全部' ? templates : templates.filter(t => t.category === categoryFilter);
  const statusColors: Record<string, string> = { '生效中': GREEN, '已过期': TEXT_4, '草稿': YELLOW };
  const categoryColors: Record<string, string> = {
    '新客': GREEN, '复购': BLUE, '老带新': PURPLE, '储值': BRAND, '新品': YELLOW, '低峰': TEXT_3,
  };

  if (loading) {
    return (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 12 }}>
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} style={{
            background: BG_1, borderRadius: 10, padding: 16, border: `1px solid ${BG_2}`,
          }}>
            <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
              <Skeleton width={48} height={18} />
              <Skeleton width={36} height={18} />
            </div>
            <Skeleton height={20} radius={4} />
            <div style={{ height: 8 }} />
            <Skeleton height={36} radius={6} />
            <div style={{ height: 10 }} />
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
              <Skeleton height={32} /><Skeleton height={32} /><Skeleton height={32} />
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (filtered.length === 0) {
    return (
      <div style={{
        padding: '40px 20px', textAlign: 'center',
        background: BG_1, borderRadius: 10, border: `1px solid ${BG_2}`,
      }}>
        <div style={{ fontSize: 14, color: TEXT_4 }}>暂无优惠券数据</div>
      </div>
    );
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 12 }}>
      {filtered.map(t => {
        const redemptionRate = t.totalIssued > 0 ? (t.totalRedeemed / t.totalIssued * 100).toFixed(1) : '0';
        return (
          <div key={t.id} style={{
            background: BG_1, borderRadius: 10, padding: 16,
            border: `1px solid ${BG_2}`, cursor: 'pointer',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
              <div style={{ display: 'flex', gap: 6 }}>
                <span style={{
                  fontSize: 10, padding: '2px 8px', borderRadius: 4,
                  background: (categoryColors[t.category] || TEXT_4) + '22',
                  color: categoryColors[t.category] || TEXT_4, fontWeight: 600,
                }}>{t.category}</span>
                <span style={{
                  fontSize: 10, padding: '2px 8px', borderRadius: 4,
                  background: BG_2, color: TEXT_3, fontWeight: 600,
                }}>{t.type}</span>
              </div>
              <span style={{
                fontSize: 10, padding: '2px 8px', borderRadius: 4,
                background: statusColors[t.status] + '22', color: statusColors[t.status], fontWeight: 600,
              }}>{t.status}</span>
            </div>
            <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 6 }}>{t.name}</div>
            <div style={{
              padding: '8px 12px', background: BG_2, borderRadius: 6, marginBottom: 10,
              fontSize: 13, color: BRAND, fontWeight: 600,
            }}>{t.rule}</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 10 }}>
              <div>
                <div style={{ fontSize: 10, color: TEXT_4 }}>已发放</div>
                <div style={{ fontSize: 14, fontWeight: 600, color: TEXT_1 }}>{t.totalIssued.toLocaleString()}</div>
              </div>
              <div>
                <div style={{ fontSize: 10, color: TEXT_4 }}>已核销</div>
                <div style={{ fontSize: 14, fontWeight: 600, color: GREEN }}>{t.totalRedeemed.toLocaleString()}</div>
              </div>
              <div>
                <div style={{ fontSize: 10, color: TEXT_4 }}>核销率</div>
                <div style={{ fontSize: 14, fontWeight: 600, color: Number(redemptionRate) > 40 ? GREEN : YELLOW }}>{redemptionRate}%</div>
              </div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
              <span style={{ color: t.marginImpact < -5 ? RED : t.marginImpact < -3 ? YELLOW : TEXT_3 }}>
                毛利影响: {t.marginImpact}%
              </span>
              <span style={{ color: t.avgOrderIncrease > 0 ? GREEN : RED }}>
                客单提升: {t.avgOrderIncrease > 0 ? '+' : ''}{t.avgOrderIncrease}%
              </span>
              <span style={{ color: TEXT_4 }}>有效期 {t.validDays} 天</span>
            </div>
            {t.marginImpact < -5 && (
              <div style={{
                marginTop: 8, padding: '4px 8px', borderRadius: 4,
                background: RED + '11', fontSize: 10, color: RED,
                borderLeft: `3px solid ${RED}`,
              }}>毛利影响超过5%，需要审批</div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---- 状态筛选器 ----
function StatusFilter({ value, onChange }: { value: OfferStatus | 'all'; onChange: (v: OfferStatus | 'all') => void }) {
  const opts: { key: OfferStatus | 'all'; label: string }[] = [
    { key: 'all', label: '全部' },
    { key: 'active', label: '生效中' },
    { key: 'expired', label: '已过期' },
    { key: 'scheduled', label: '待生效' },
  ];
  return (
    <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
      <span style={{ fontSize: 12, color: TEXT_4, alignSelf: 'center' }}>状态：</span>
      {opts.map(o => (
        <button key={o.key} onClick={() => onChange(o.key)} style={{
          padding: '3px 10px', borderRadius: 6, border: 'none', cursor: 'pointer',
          background: value === o.key ? PURPLE : BG_2,
          color: value === o.key ? '#fff' : TEXT_3,
          fontSize: 11, fontWeight: 600,
        }}>{o.label}</button>
      ))}
    </div>
  );
}

// ---- 创建优惠券表单 ----
function CreateOfferForm({ onSuccess }: { onSuccess: () => void }) {
  const [form, setForm] = useState<CreateOfferPayload>({
    name: '',
    type: '满减',
    category: '新客',
    brand: '全部品牌',
    minAmount: 80,
    discountAmount: 20,
    validDays: 7,
    totalLimit: 5000,
    status: 'active',
  });
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitOk, setSubmitOk] = useState(false);

  const selectStyle: React.CSSProperties = {
    background: BG_2, border: `1px solid ${BG_2}`, borderRadius: 6,
    color: TEXT_2, padding: '8px 12px', fontSize: 13, outline: 'none',
    cursor: 'pointer', width: '100%',
  };
  const inputStyle: React.CSSProperties = { ...selectStyle, cursor: 'text' };

  const marginImpactEst = form.minAmount > 0
    ? -((form.discountAmount / form.minAmount) * 100).toFixed(1)
    : 0;
  const isMarginOk = Number(marginImpactEst) > -5;

  async function handleSubmit(status: 'active' | 'draft') {
    if (!form.name.trim()) { setSubmitError('请填写券名称'); return; }
    setSubmitting(true);
    setSubmitError(null);
    try {
      await txFetchData('/api/v1/member/promotions', {
        method: 'POST',
        body: JSON.stringify({ ...form, status }),
      });
      setSubmitOk(true);
      onSuccess();
    } catch (e: unknown) {
      setSubmitError(e instanceof Error ? e.message : '创建失败，请重试');
    } finally {
      setSubmitting(false);
    }
  }

  if (submitOk) {
    return (
      <div style={{
        background: BG_1, borderRadius: 10, padding: 40,
        border: `1px solid ${BG_2}`, textAlign: 'center',
      }}>
        <div style={{ fontSize: 32, marginBottom: 12, color: GREEN }}>✓</div>
        <div style={{ fontSize: 16, fontWeight: 700, color: TEXT_1, marginBottom: 8 }}>优惠券创建成功</div>
        <button onClick={() => setSubmitOk(false)} style={{
          padding: '8px 20px', borderRadius: 8, border: 'none',
          background: BRAND, color: '#fff', fontSize: 13, cursor: 'pointer',
        }}>继续创建</button>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', gap: 16 }}>
      <div style={{
        flex: 1, background: BG_1, borderRadius: 10, padding: 20,
        border: `1px solid ${BG_2}`,
      }}>
        <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>创建优惠券</h3>
        {submitError && <ErrorBanner message={submitError} />}

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          <div style={{ gridColumn: '1 / -1' }}>
            <label style={{ fontSize: 12, color: TEXT_3, marginBottom: 6, display: 'block' }}>券名称</label>
            <input
              style={inputStyle} placeholder="例：新客首单立减20"
              value={form.name}
              onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
            />
          </div>
          <div>
            <label style={{ fontSize: 12, color: TEXT_3, marginBottom: 6, display: 'block' }}>券类型</label>
            <select style={selectStyle} value={form.type} onChange={e => setForm(f => ({ ...f, type: e.target.value as CreateOfferPayload['type'] }))}>
              <option>满减</option><option>折扣</option><option>赠品</option>
              <option>免费</option><option>积分</option><option>储值</option>
            </select>
          </div>
          <div>
            <label style={{ fontSize: 12, color: TEXT_3, marginBottom: 6, display: 'block' }}>使用场景</label>
            <select style={selectStyle} value={form.category} onChange={e => setForm(f => ({ ...f, category: e.target.value as OfferCategory }))}>
              <option>新客</option><option>复购</option><option>老带新</option>
              <option>储值</option><option>新品</option><option>低峰</option>
            </select>
          </div>
          <div>
            <label style={{ fontSize: 12, color: TEXT_3, marginBottom: 6, display: 'block' }}>适用品牌</label>
            <select style={selectStyle} value={form.brand} onChange={e => setForm(f => ({ ...f, brand: e.target.value }))}>
              <option>全部品牌</option><option>尝在一起</option><option>最黔线</option><option>尚宫厨</option>
            </select>
          </div>
          <div>
            <label style={{ fontSize: 12, color: TEXT_3, marginBottom: 6, display: 'block' }}>门槛金额（元）</label>
            <input
              style={inputStyle} type="number" placeholder="满X元可用"
              value={form.minAmount}
              onChange={e => setForm(f => ({ ...f, minAmount: Number(e.target.value) }))}
            />
          </div>
          <div>
            <label style={{ fontSize: 12, color: TEXT_3, marginBottom: 6, display: 'block' }}>优惠金额（元）</label>
            <input
              style={inputStyle} type="number" placeholder="减X元"
              value={form.discountAmount}
              onChange={e => setForm(f => ({ ...f, discountAmount: Number(e.target.value) }))}
            />
          </div>
          <div>
            <label style={{ fontSize: 12, color: TEXT_3, marginBottom: 6, display: 'block' }}>有效天数</label>
            <input
              style={inputStyle} type="number" placeholder="领取后X天有效"
              value={form.validDays}
              onChange={e => setForm(f => ({ ...f, validDays: Number(e.target.value) }))}
            />
          </div>
          <div>
            <label style={{ fontSize: 12, color: TEXT_3, marginBottom: 6, display: 'block' }}>发放数量上限</label>
            <input
              style={inputStyle} type="number" placeholder="总发放上限"
              value={form.totalLimit}
              onChange={e => setForm(f => ({ ...f, totalLimit: Number(e.target.value) }))}
            />
          </div>
        </div>

        {/* 毛利合规检测 */}
        <div style={{
          marginTop: 16, padding: '12px 16px', borderRadius: 8,
          background: isMarginOk ? GREEN + '11' : RED + '11',
          borderLeft: `3px solid ${isMarginOk ? GREEN : RED}`,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: isMarginOk ? GREEN : RED }}>
              毛利合规检测 {isMarginOk ? '通过' : '警告'}
            </span>
            <span style={{
              fontSize: 10, padding: '1px 6px', borderRadius: 4,
              background: (isMarginOk ? GREEN : RED) + '22', color: isMarginOk ? GREEN : RED,
            }}>{isMarginOk ? 'PASS' : 'WARN'}</span>
          </div>
          <div style={{ fontSize: 11, color: TEXT_3, lineHeight: 1.6 }}>
            预估毛利影响: {marginImpactEst}% | 门槛: ¥{form.minAmount} | 折扣: ¥{form.discountAmount}
            {!isMarginOk && ' | 毛利影响超过5%，提交后需审批'}
          </div>
        </div>

        <div style={{ display: 'flex', gap: 10, marginTop: 16 }}>
          <button
            disabled={submitting}
            onClick={() => handleSubmit('active')}
            style={{
              padding: '10px 24px', borderRadius: 8, border: 'none',
              background: submitting ? TEXT_4 : BRAND, color: '#fff',
              fontSize: 14, fontWeight: 700, cursor: submitting ? 'not-allowed' : 'pointer',
            }}
          >{submitting ? '提交中...' : '创建并发布'}</button>
          <button
            disabled={submitting}
            onClick={() => handleSubmit('draft')}
            style={{
              padding: '10px 24px', borderRadius: 8, border: `1px solid ${BG_2}`,
              background: 'transparent', color: TEXT_3,
              fontSize: 14, fontWeight: 600, cursor: submitting ? 'not-allowed' : 'pointer',
            }}
          >保存草稿</button>
        </div>
      </div>

      {/* 右侧预览 */}
      <div style={{
        width: 280, background: BG_1, borderRadius: 10, padding: 20,
        border: `1px solid ${BG_2}`, flexShrink: 0,
      }}>
        <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>券面预览</h3>
        <div style={{
          background: `linear-gradient(135deg, ${BRAND}, ${BRAND}cc)`,
          borderRadius: 12, padding: 20, textAlign: 'center',
        }}>
          <div style={{ fontSize: 11, color: '#ffffffcc', marginBottom: 4 }}>{form.brand}</div>
          <div style={{ fontSize: 36, fontWeight: 800, color: '#fff' }}>¥{form.discountAmount}</div>
          <div style={{ fontSize: 13, color: '#ffffffcc', marginBottom: 12 }}>
            {form.minAmount > 0 ? `满${form.minAmount}元可用` : '无门槛使用'}
          </div>
          <div style={{
            borderTop: '1px dashed #ffffff44', paddingTop: 10,
            fontSize: 11, color: '#ffffff88',
          }}>
            {form.category} 专享 | 领取后{form.validDays}天有效
          </div>
        </div>
        <div style={{ marginTop: 14, fontSize: 11, color: TEXT_4, lineHeight: 1.8 }}>
          <div>券名称：{form.name || '（未填写）'}</div>
          <div>适用品牌：{form.brand}</div>
          <div>发放上限：{form.totalLimit.toLocaleString()} 张</div>
          <div>每人限领：1张</div>
          <div>不可叠加使用</div>
        </div>
      </div>
    </div>
  );
}

// ---- 核销分析 ----
function RedemptionAnalytics({
  data, loading, error, onRetry,
}: {
  data: RedemptionStat[];
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  if (error) return <ErrorBanner message={`加载核销数据失败：${error}`} onRetry={onRetry} />;

  const maxIssued = data.length > 0 ? Math.max(...data.map(d => d.issued)) : 1;
  const barH = 140;

  if (loading) {
    return (
      <div>
        <div style={{ background: BG_1, borderRadius: 10, padding: 18, border: `1px solid ${BG_2}`, marginBottom: 16 }}>
          <Skeleton height={20} width={200} />
          <div style={{ marginTop: 16 }}>
            <Skeleton height={barH} />
          </div>
        </div>
        <div style={{ background: BG_1, borderRadius: 10, padding: 18, border: `1px solid ${BG_2}` }}>
          <Skeleton height={20} width={200} />
          <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
            {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} height={36} />)}
          </div>
        </div>
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div style={{
        padding: '40px 20px', textAlign: 'center',
        background: BG_1, borderRadius: 10, border: `1px solid ${BG_2}`,
      }}>
        <div style={{ fontSize: 14, color: TEXT_4 }}>暂无核销数据</div>
      </div>
    );
  }

  return (
    <div>
      {/* 趋势图 */}
      <div style={{
        background: BG_1, borderRadius: 10, padding: 18,
        border: `1px solid ${BG_2}`, marginBottom: 16,
      }}>
        <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>核销趋势（近{data.length}天）</h3>
        <div style={{ display: 'flex', gap: 8, marginBottom: 10, fontSize: 11 }}>
          <span style={{ color: BRAND }}>■ 发放量</span>
          <span style={{ color: GREEN }}>■ 核销量</span>
          <span style={{ color: RED }}>■ 过期量</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-end', height: barH, gap: 8 }}>
          {data.map((d, i) => (
            <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
              <div style={{ display: 'flex', gap: 2, alignItems: 'flex-end', height: barH - 30 }}>
                <div style={{
                  width: 16, height: (d.issued / maxIssued) * (barH - 40),
                  background: BRAND, borderRadius: '3px 3px 0 0',
                }} />
                <div style={{
                  width: 16, height: (d.redeemed / maxIssued) * (barH - 40),
                  background: GREEN, borderRadius: '3px 3px 0 0',
                }} />
                <div style={{
                  width: 16, height: Math.max(4, (d.expired / maxIssued) * (barH - 40)),
                  background: RED, borderRadius: '3px 3px 0 0',
                }} />
              </div>
              <span style={{ fontSize: 10, color: TEXT_4 }}>{d.date}</span>
            </div>
          ))}
        </div>
      </div>

      {/* 明细表 */}
      <div style={{
        background: BG_1, borderRadius: 10, padding: 16,
        border: `1px solid ${BG_2}`,
      }}>
        <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>核销明细</h3>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${BG_2}` }}>
              {['日期', '发放', '核销', '过期', '核销率', '贡献营收'].map(h => (
                <th key={h} style={{ textAlign: 'left', padding: '8px 10px', color: TEXT_4, fontWeight: 600, fontSize: 11 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.map(d => {
              const rate = d.issued > 0 ? (d.redeemed / d.issued * 100).toFixed(1) : '0.0';
              return (
                <tr key={d.date} style={{ borderBottom: `1px solid ${BG_2}` }}>
                  <td style={{ padding: '10px', color: TEXT_2 }}>{d.date}</td>
                  <td style={{ padding: '10px', color: TEXT_1 }}>{d.issued}</td>
                  <td style={{ padding: '10px', color: GREEN, fontWeight: 600 }}>{d.redeemed}</td>
                  <td style={{ padding: '10px', color: RED }}>{d.expired}</td>
                  <td style={{ padding: '10px', color: Number(rate) > 45 ? GREEN : YELLOW, fontWeight: 600 }}>{rate}%</td>
                  <td style={{ padding: '10px', color: GREEN, fontWeight: 600 }}>¥{(d.revenue / 10000).toFixed(1)}万</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---- 主页面 ----

export function OfferCenterPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('overview');
  const [categoryFilter, setCategoryFilter] = useState<OfferCategory>('全部');
  const [statusFilter, setStatusFilter] = useState<OfferStatus | 'all'>('all');
  const [page, setPage] = useState(1);
  const pageSize = 20;

  // 优惠券列表状态
  const [templates, setTemplates] = useState<OfferTemplate[]>([]);
  const [total, setTotal] = useState(0);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [errorTemplates, setErrorTemplates] = useState<string | null>(null);

  // 核销数据状态
  const [redemptionData, setRedemptionData] = useState<RedemptionStat[]>([]);
  const [loadingRedemption, setLoadingRedemption] = useState(false);
  const [errorRedemption, setErrorRedemption] = useState<string | null>(null);

  // 加载优惠券列表
  const loadTemplates = useCallback(async () => {
    setLoadingTemplates(true);
    setErrorTemplates(null);
    try {
      const params = new URLSearchParams({
        page: String(page),
        size: String(pageSize),
      });
      if (statusFilter !== 'all') params.set('status', statusFilter);
      const resp = await txFetchData<PromotionListResponse>(`/api/v1/member/promotions?${params}`);
      setTemplates(resp.items ?? []);
      setTotal(resp.total ?? 0);
    } catch (e: unknown) {
      setErrorTemplates(e instanceof Error ? e.message : '加载失败');
      setTemplates([]);
    } finally {
      setLoadingTemplates(false);
    }
  }, [page, statusFilter]);

  // 加载核销统计
  const loadRedemptionStats = useCallback(async () => {
    setLoadingRedemption(true);
    setErrorRedemption(null);
    try {
      const resp = await txFetchData<RedemptionStatsResponse>('/api/v1/member/promotions/redemption-stats?days=7');
      setRedemptionData(resp.items ?? []);
    } catch (e: unknown) {
      setErrorRedemption(e instanceof Error ? e.message : '加载失败');
      setRedemptionData([]);
    } finally {
      setLoadingRedemption(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'overview' || activeTab === 'templates') {
      loadTemplates();
    }
  }, [activeTab, loadTemplates]);

  useEffect(() => {
    if (activeTab === 'analytics') {
      loadRedemptionStats();
    }
  }, [activeTab, loadRedemptionStats]);

  // 切换状态筛选时重置分页
  useEffect(() => {
    setPage(1);
  }, [statusFilter]);

  const tabs: { key: TabKey; label: string }[] = [
    { key: 'overview', label: '券模板总览' },
    { key: 'templates', label: '券模板管理' },
    { key: 'create', label: '创建优惠券' },
    { key: 'analytics', label: '核销分析' },
  ];

  const categories: OfferCategory[] = ['全部', '新客', '复购', '老带新', '储值', '新品', '低峰'];
  const totalPages = Math.ceil(total / pageSize);

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto' }}>
      <h2 style={{ margin: '0 0 16px', fontSize: 22, fontWeight: 700, color: TEXT_1 }}>权益策略中心</h2>

      {/* 概览卡片 */}
      <OverviewCards
        templates={templates}
        loading={loadingTemplates}
        error={errorTemplates}
        onRetry={loadTemplates}
      />

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 16 }}>
        {tabs.map(t => (
          <button key={t.key} onClick={() => setActiveTab(t.key)} style={{
            padding: '8px 18px', borderRadius: 8, border: 'none', cursor: 'pointer',
            background: activeTab === t.key ? BRAND : BG_1,
            color: activeTab === t.key ? '#fff' : TEXT_3,
            fontSize: 13, fontWeight: 600,
          }}>{t.label}</button>
        ))}
      </div>

      {/* 状态筛选 + 分类筛选 */}
      {(activeTab === 'overview' || activeTab === 'templates') && (
        <>
          <StatusFilter value={statusFilter} onChange={setStatusFilter} />
          <div style={{ display: 'flex', gap: 4, marginBottom: 14 }}>
            {categories.map(c => (
              <button key={c} onClick={() => setCategoryFilter(c)} style={{
                padding: '4px 12px', borderRadius: 6, border: 'none', cursor: 'pointer',
                background: categoryFilter === c ? BLUE : BG_2,
                color: categoryFilter === c ? '#fff' : TEXT_3,
                fontSize: 11, fontWeight: 600,
              }}>{c}</button>
            ))}
          </div>
        </>
      )}

      {/* 内容区 */}
      {(activeTab === 'overview' || activeTab === 'templates') && (
        <>
          <OfferGrid
            templates={templates}
            categoryFilter={categoryFilter}
            loading={loadingTemplates}
            error={errorTemplates}
            onRetry={loadTemplates}
          />
          {/* 分页 */}
          {!loadingTemplates && total > pageSize && (
            <div style={{ display: 'flex', justifyContent: 'center', gap: 8, marginTop: 16 }}>
              <button
                disabled={page <= 1}
                onClick={() => setPage(p => Math.max(1, p - 1))}
                style={{
                  padding: '6px 14px', borderRadius: 6, border: `1px solid ${BG_2}`,
                  background: page <= 1 ? BG_2 : BG_1, color: page <= 1 ? TEXT_4 : TEXT_2,
                  fontSize: 12, cursor: page <= 1 ? 'not-allowed' : 'pointer',
                }}
              >上一页</button>
              <span style={{ padding: '6px 12px', fontSize: 12, color: TEXT_3 }}>
                第 {page} / {totalPages} 页，共 {total} 条
              </span>
              <button
                disabled={page >= totalPages}
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                style={{
                  padding: '6px 14px', borderRadius: 6, border: `1px solid ${BG_2}`,
                  background: page >= totalPages ? BG_2 : BG_1, color: page >= totalPages ? TEXT_4 : TEXT_2,
                  fontSize: 12, cursor: page >= totalPages ? 'not-allowed' : 'pointer',
                }}
              >下一页</button>
            </div>
          )}
        </>
      )}

      {activeTab === 'create' && (
        <CreateOfferForm onSuccess={() => {
          setActiveTab('overview');
          loadTemplates();
        }} />
      )}

      {activeTab === 'analytics' && (
        <RedemptionAnalytics
          data={redemptionData}
          loading={loadingRedemption}
          error={errorRedemption}
          onRetry={loadRedemptionStats}
        />
      )}
    </div>
  );
}
