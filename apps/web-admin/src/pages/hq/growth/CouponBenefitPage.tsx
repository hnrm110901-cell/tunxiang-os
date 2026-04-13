/**
 * CouponBenefitPage — 券权益中心
 * 路由: /hq/growth/coupon-benefit
 * 管理优惠券、积分商城、储值卡、礼品卡等会员权益
 * 数据来源: GET/POST /api/v1/member/coupons, /points, /stored-value, /gift-cards
 */
import { useState, useEffect, useCallback } from 'react';
import { formatPrice } from '@tx-ds/utils';
import { txFetchData } from '../../../api/client';
import type {
  Coupon, CouponType, CouponStatus, CouponStats, CreateCouponPayload,
  PointsRule, PointsProduct, StoredValuePlan, StoredValueStats,
  GiftCardTemplate,
} from '../../../api/couponBenefitApi';

// ---- 颜色常量 ----
const PRIMARY = '#FF6B35';
const SUCCESS = '#0F6E56';
const WARNING = '#BA7517';
const ERROR = '#A32D2D';
const BG_PAGE = '#0d1b21';
const BG_CARD = '#112228';
const BG_INPUT = '#1a2a33';
const BORDER = '#1e3040';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

type TabKey = 'coupon' | 'points' | 'stored_value' | 'gift_card';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'coupon', label: '优惠券' },
  { key: 'points', label: '积分商城' },
  { key: 'stored_value', label: '储值卡' },
  { key: 'gift_card', label: '礼品卡' },
];

const COUPON_TYPE_MAP: Record<CouponType, string> = {
  cash_off: '满减', discount: '折扣', gift: '赠品', free: '免单',
};
const STATUS_MAP: Record<CouponStatus, { label: string; color: string }> = {
  draft: { label: '草稿', color: TEXT_4 },
  active: { label: '生效中', color: SUCCESS },
  paused: { label: '已暂停', color: WARNING },
  expired: { label: '已过期', color: ERROR },
};

// ---- 工具函数 ----
/** @deprecated Use formatPrice from @tx-ds/utils */
function fenToYuan(fen: number): string {
  return (fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatDate(d: string): string {
  return new Date(d).toLocaleDateString('zh-CN');
}

// ---- 骨架屏 ----
function Skeleton({ w = '100%', h = 24 }: { w?: string | number; h?: number }) {
  return (
    <div style={{
      width: w, height: h, borderRadius: 6,
      background: `linear-gradient(90deg, ${BG_INPUT} 25%, ${BORDER} 50%, ${BG_INPUT} 75%)`,
      backgroundSize: '200% 100%', animation: 'shimmer 1.5s infinite',
    }} />
  );
}

// ---- 错误提示 ----
function ErrorBanner({ msg, onRetry }: { msg: string; onRetry?: () => void }) {
  return (
    <div style={{
      padding: '12px 16px', borderRadius: 8, marginBottom: 12,
      background: ERROR + '18', borderLeft: `3px solid ${ERROR}`,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    }}>
      <span style={{ fontSize: 13, color: ERROR }}>{msg}</span>
      {onRetry && (
        <button onClick={onRetry} style={{
          padding: '4px 12px', borderRadius: 6, border: `1px solid ${ERROR}`,
          background: 'transparent', color: ERROR, fontSize: 12, cursor: 'pointer',
        }}>重试</button>
      )}
    </div>
  );
}

// ---- 按钮 ----
function Btn({ children, onClick, primary, small, disabled, style: s }:
  { children: React.ReactNode; onClick?: () => void; primary?: boolean; small?: boolean; disabled?: boolean; style?: React.CSSProperties }) {
  return (
    <button disabled={disabled} onClick={onClick} style={{
      padding: small ? '4px 12px' : '8px 20px',
      borderRadius: 6, border: primary ? 'none' : `1px solid ${BORDER}`,
      background: primary ? PRIMARY : 'transparent',
      color: primary ? '#fff' : TEXT_2,
      fontSize: small ? 12 : 13, fontWeight: 600, cursor: disabled ? 'not-allowed' : 'pointer',
      opacity: disabled ? 0.5 : 1, ...s,
    }}>{children}</button>
  );
}

// ============================================================
// 子组件 — 优惠券Tab
// ============================================================

interface CouponListResponse { items: Coupon[]; total: number }

function CouponTab() {
  const [coupons, setCoupons] = useState<Coupon[]>([]);
  const [stats, setStats] = useState<CouponStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [res, s] = await Promise.all([
        txFetchData<CouponListResponse>('/api/v1/member/coupons?page=1&size=50'),
        txFetchData<CouponStats>('/api/v1/member/coupons/stats'),
      ]);
      setCoupons(res.items);
      setStats(s);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const statCards = [
    { label: '总发放', value: stats ? stats.total_issued.toLocaleString() : '-', color: PRIMARY },
    { label: '核销率', value: stats ? `${(stats.redemption_rate * 100).toFixed(1)}%` : '-', color: SUCCESS },
    { label: '带动消费', value: stats ? `¥${fenToYuan(stats.driven_revenue_fen)}` : '-', color: WARNING },
  ];

  return (
    <div>
      {/* 统计卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 16 }}>
        {statCards.map((c, i) => (
          <div key={i} style={{ background: BG_CARD, borderRadius: 10, padding: '14px 18px', border: `1px solid ${BORDER}` }}>
            <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 4 }}>{c.label}</div>
            {loading ? <Skeleton h={28} /> : <div style={{ fontSize: 24, fontWeight: 700, color: c.color }}>{c.value}</div>}
          </div>
        ))}
      </div>

      {/* 操作栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: TEXT_1 }}>优惠券列表</div>
        <Btn primary onClick={() => setShowCreate(true)}>+ 创建优惠券</Btn>
      </div>

      {error && <ErrorBanner msg={error} onRetry={load} />}

      {/* 表格 */}
      <div style={{ background: BG_CARD, borderRadius: 10, border: `1px solid ${BORDER}`, overflow: 'hidden' }}>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: BG_INPUT }}>
                {['券名称', '类型', '面值', '有效期', '已发放', '已核销', '已过期', '状态', '操作'].map(h => (
                  <th key={h} style={{ padding: '10px 14px', textAlign: 'left', color: TEXT_3, fontWeight: 500, whiteSpace: 'nowrap' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i}><td colSpan={9} style={{ padding: '10px 14px' }}><Skeleton h={18} /></td></tr>
                ))
              ) : coupons.length === 0 ? (
                <tr><td colSpan={9} style={{ padding: 32, textAlign: 'center', color: TEXT_4 }}>暂无优惠券</td></tr>
              ) : coupons.map(c => {
                const st = STATUS_MAP[c.status];
                return (
                  <tr key={c.id} style={{ borderTop: `1px solid ${BORDER}` }}>
                    <td style={{ padding: '10px 14px', color: TEXT_1, fontWeight: 500 }}>{c.name}</td>
                    <td style={{ padding: '10px 14px' }}>
                      <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 4, background: PRIMARY + '22', color: PRIMARY }}>
                        {COUPON_TYPE_MAP[c.type]}
                      </span>
                    </td>
                    <td style={{ padding: '10px 14px', color: TEXT_2 }}>
                      {c.type === 'discount' ? `${((c.discount_rate ?? 0) * 10).toFixed(1)}折` : `¥${fenToYuan(c.value_fen)}`}
                    </td>
                    <td style={{ padding: '10px 14px', color: TEXT_3, whiteSpace: 'nowrap' }}>
                      {formatDate(c.valid_from)} ~ {formatDate(c.valid_to)}
                    </td>
                    <td style={{ padding: '10px 14px', color: TEXT_2 }}>{c.total_issued.toLocaleString()}</td>
                    <td style={{ padding: '10px 14px', color: SUCCESS }}>{c.used_count.toLocaleString()}</td>
                    <td style={{ padding: '10px 14px', color: TEXT_4 }}>{c.expired_count.toLocaleString()}</td>
                    <td style={{ padding: '10px 14px' }}>
                      <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 4, background: st.color + '22', color: st.color }}>
                        {st.label}
                      </span>
                    </td>
                    <td style={{ padding: '10px 14px' }}>
                      <Btn small onClick={() => {/* TODO: edit */}}>编辑</Btn>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* 创建券 Modal */}
      {showCreate && <CreateCouponModal onClose={() => setShowCreate(false)} onSuccess={() => { setShowCreate(false); load(); }} />}
    </div>
  );
}

// ---- 创建券 Modal ----
function CreateCouponModal({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const [form, setForm] = useState<CreateCouponPayload>({
    name: '', type: 'cash_off', value_fen: 0, min_order_fen: 0,
    valid_from: '', valid_to: '', total_limit: 0, applicable_stores: [],
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  const update = (k: keyof CreateCouponPayload, v: unknown) => setForm(f => ({ ...f, [k]: v }));

  const handleSave = async () => {
    if (!form.name.trim()) { setErr('请输入券名称'); return; }
    if (!form.valid_from || !form.valid_to) { setErr('请选择有效期'); return; }
    setSaving(true); setErr('');
    try {
      await txFetchData<Coupon>('/api/v1/member/coupons', { method: 'POST', body: JSON.stringify(form) });
      onSuccess();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : '创建失败');
    } finally { setSaving(false); }
  };

  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '8px 12px', borderRadius: 6, border: `1px solid ${BORDER}`,
    background: BG_INPUT, color: TEXT_1, fontSize: 13, outline: 'none',
  };
  const labelStyle: React.CSSProperties = { fontSize: 12, color: TEXT_3, marginBottom: 4, display: 'block' };

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)',
    }} onClick={onClose}>
      <div style={{
        width: 520, maxHeight: '80vh', overflow: 'auto', background: BG_PAGE,
        borderRadius: 12, border: `1px solid ${BORDER}`, padding: 24,
      }} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 20 }}>
          <span style={{ fontSize: 16, fontWeight: 700, color: TEXT_1 }}>创建优惠券</span>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: TEXT_3, fontSize: 18, cursor: 'pointer' }}>x</button>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div>
            <label style={labelStyle}>券名称</label>
            <input style={inputStyle} value={form.name} onChange={e => update('name', e.target.value)} placeholder="如：新客满50减10" />
          </div>

          <div>
            <label style={labelStyle}>券类型</label>
            <select style={inputStyle} value={form.type} onChange={e => update('type', e.target.value)}>
              {(Object.entries(COUPON_TYPE_MAP) as [CouponType, string][]).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <label style={labelStyle}>面值（元）</label>
              <input style={inputStyle} type="number" value={form.value_fen / 100 || ''} onChange={e => update('value_fen', Math.round(Number(e.target.value) * 100))} placeholder="10" />
            </div>
            <div>
              <label style={labelStyle}>最低消费（元）</label>
              <input style={inputStyle} type="number" value={form.min_order_fen / 100 || ''} onChange={e => update('min_order_fen', Math.round(Number(e.target.value) * 100))} placeholder="50" />
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <label style={labelStyle}>开始日期</label>
              <input style={inputStyle} type="date" value={form.valid_from} onChange={e => update('valid_from', e.target.value)} />
            </div>
            <div>
              <label style={labelStyle}>结束日期</label>
              <input style={inputStyle} type="date" value={form.valid_to} onChange={e => update('valid_to', e.target.value)} />
            </div>
          </div>

          <div>
            <label style={labelStyle}>发放数量</label>
            <input style={inputStyle} type="number" value={form.total_limit || ''} onChange={e => update('total_limit', Number(e.target.value))} placeholder="1000" />
          </div>
        </div>

        {err && <div style={{ marginTop: 12, fontSize: 12, color: ERROR }}>{err}</div>}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 20 }}>
          <Btn onClick={onClose}>取消</Btn>
          <Btn primary onClick={handleSave} disabled={saving}>{saving ? '保存中...' : '创建'}</Btn>
        </div>
      </div>
    </div>
  );
}

// ============================================================
// 子组件 — 积分Tab
// ============================================================

function PointsTab() {
  const [rules, setRules] = useState<PointsRule | null>(null);
  const [products, setProducts] = useState<PointsProduct[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingRules, setEditingRules] = useState(false);
  const [ruleForm, setRuleForm] = useState<Partial<PointsRule>>({});

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [r, p] = await Promise.all([
        txFetchData<PointsRule>('/api/v1/member/points/rules'),
        txFetchData<{ items: PointsProduct[]; total: number }>('/api/v1/member/points/products?page=1&size=50'),
      ]);
      setRules(r); setProducts(p.items);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const saveRules = async () => {
    try {
      const updated = await txFetchData<PointsRule>('/api/v1/member/points/rules', {
        method: 'PATCH', body: JSON.stringify(ruleForm),
      });
      setRules(updated); setEditingRules(false);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '保存失败');
    }
  };

  if (error) return <ErrorBanner msg={error} onRetry={load} />;

  const ruleCards = rules ? [
    { label: '消费积分', desc: `每消费 ¥${fenToYuan(rules.spend_fen_per_point)} = 1积分`, value: rules.spend_fen_per_point },
    { label: '签到积分', desc: `每日签到 +${rules.checkin_points} 积分`, value: rules.checkin_points },
    { label: '生日积分', desc: `生日当天 +${rules.birthday_points} 积分`, value: rules.birthday_points },
    { label: '积分有效期', desc: `${rules.expiry_days} 天`, value: rules.expiry_days },
  ] : [];

  return (
    <div>
      {/* 积分规则 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: TEXT_1 }}>积分规则配置</div>
        {!editingRules ? (
          <Btn small onClick={() => { setEditingRules(true); setRuleForm(rules ?? {}); }}>编辑规则</Btn>
        ) : (
          <div style={{ display: 'flex', gap: 8 }}>
            <Btn small onClick={() => setEditingRules(false)}>取消</Btn>
            <Btn small primary onClick={saveRules}>保存</Btn>
          </div>
        )}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 20 }}>
        {loading ? Array.from({ length: 4 }).map((_, i) => (
          <div key={i} style={{ background: BG_CARD, borderRadius: 10, padding: '14px 18px', border: `1px solid ${BORDER}` }}>
            <Skeleton h={16} w="60%" /><div style={{ height: 8 }} /><Skeleton h={24} />
          </div>
        )) : ruleCards.map((c, i) => (
          <div key={i} style={{ background: BG_CARD, borderRadius: 10, padding: '14px 18px', border: `1px solid ${BORDER}` }}>
            <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 4 }}>{c.label}</div>
            {editingRules ? (
              <input
                type="number"
                value={ruleForm[(['spend_fen_per_point', 'checkin_points', 'birthday_points', 'expiry_days'] as const)[i]] ?? c.value}
                onChange={e => setRuleForm(f => ({
                  ...f, [(['spend_fen_per_point', 'checkin_points', 'birthday_points', 'expiry_days'] as const)[i]]: Number(e.target.value),
                }))}
                style={{
                  width: '100%', padding: '6px 10px', borderRadius: 6,
                  border: `1px solid ${PRIMARY}`, background: BG_INPUT, color: TEXT_1, fontSize: 14, outline: 'none',
                }}
              />
            ) : (
              <div style={{ fontSize: 14, color: TEXT_2, fontWeight: 500 }}>{c.desc}</div>
            )}
          </div>
        ))}
      </div>

      {/* 兑换商品列表 */}
      <div style={{ fontSize: 14, fontWeight: 600, color: TEXT_1, marginBottom: 12 }}>积分兑换商品</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 12 }}>
        {loading ? Array.from({ length: 4 }).map((_, i) => (
          <div key={i} style={{ background: BG_CARD, borderRadius: 10, padding: 16, border: `1px solid ${BORDER}` }}>
            <Skeleton h={80} /><div style={{ height: 8 }} /><Skeleton h={16} /><div style={{ height: 4 }} /><Skeleton h={14} w="50%" />
          </div>
        )) : products.length === 0 ? (
          <div style={{ gridColumn: '1/-1', padding: 40, textAlign: 'center', color: TEXT_4, background: BG_CARD, borderRadius: 10, border: `1px solid ${BORDER}` }}>
            暂无兑换商品
          </div>
        ) : products.map(p => (
          <div key={p.id} style={{
            background: BG_CARD, borderRadius: 10, padding: 16, border: `1px solid ${BORDER}`,
            opacity: p.is_active ? 1 : 0.5,
          }}>
            <div style={{
              height: 80, borderRadius: 8, background: BG_INPUT, marginBottom: 10,
              display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 28, color: TEXT_4,
            }}>
              {p.image_url ? <img src={p.image_url} alt={p.name} style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: 8 }} /> : '🎁'}
            </div>
            <div style={{ fontSize: 14, fontWeight: 600, color: TEXT_1, marginBottom: 4 }}>{p.name}</div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
              <span style={{ color: PRIMARY, fontWeight: 600 }}>{p.points_cost} 积分</span>
              <span style={{ color: TEXT_3 }}>库存 {p.stock} | 已兑 {p.exchanged_count}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ============================================================
// 子组件 — 储值卡Tab
// ============================================================

function StoredValueTab() {
  const [plans, setPlans] = useState<StoredValuePlan[]>([]);
  const [stats, setStats] = useState<StoredValueStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [p, s] = await Promise.all([
        txFetchData<{ items: StoredValuePlan[]; total: number }>('/api/v1/member/stored-value/plans'),
        txFetchData<StoredValueStats>('/api/v1/member/stored-value/stats'),
      ]);
      setPlans(p.items); setStats(s);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (error) return <ErrorBanner msg={error} onRetry={load} />;

  const statCards = stats ? [
    { label: '总充值额', value: `¥${fenToYuan(stats.total_charged_fen)}`, color: PRIMARY },
    { label: '总余额', value: `¥${fenToYuan(stats.total_balance_fen)}`, color: WARNING },
    { label: '消耗率', value: `${(stats.consumption_rate * 100).toFixed(1)}%`, color: SUCCESS },
  ] : [];

  return (
    <div>
      {/* 统计卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 20 }}>
        {loading ? Array.from({ length: 3 }).map((_, i) => (
          <div key={i} style={{ background: BG_CARD, borderRadius: 10, padding: '14px 18px', border: `1px solid ${BORDER}` }}>
            <Skeleton h={16} w="40%" /><div style={{ height: 6 }} /><Skeleton h={28} />
          </div>
        )) : statCards.map((c, i) => (
          <div key={i} style={{ background: BG_CARD, borderRadius: 10, padding: '14px 18px', border: `1px solid ${BORDER}` }}>
            <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 4 }}>{c.label}</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: c.color }}>{c.value}</div>
          </div>
        ))}
      </div>

      {/* 储值方案列表 */}
      <div style={{ fontSize: 14, fontWeight: 600, color: TEXT_1, marginBottom: 12 }}>储值方案</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
        {loading ? Array.from({ length: 3 }).map((_, i) => (
          <div key={i} style={{ background: BG_CARD, borderRadius: 10, padding: 20, border: `1px solid ${BORDER}` }}>
            <Skeleton h={20} w="60%" /><div style={{ height: 10 }} /><Skeleton h={40} /><div style={{ height: 10 }} /><Skeleton h={14} />
          </div>
        )) : plans.length === 0 ? (
          <div style={{ gridColumn: '1/-1', padding: 40, textAlign: 'center', color: TEXT_4, background: BG_CARD, borderRadius: 10, border: `1px solid ${BORDER}` }}>
            暂无储值方案
          </div>
        ) : plans.map(p => (
          <div key={p.id} style={{
            background: BG_CARD, borderRadius: 10, padding: 20, border: `1px solid ${BORDER}`,
            opacity: p.is_active ? 1 : 0.5,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
              <span style={{ fontSize: 15, fontWeight: 700, color: TEXT_1 }}>{p.name}</span>
              <span style={{
                fontSize: 11, padding: '2px 8px', borderRadius: 4,
                background: (p.is_active ? SUCCESS : TEXT_4) + '22',
                color: p.is_active ? SUCCESS : TEXT_4,
              }}>{p.is_active ? '启用' : '停用'}</span>
            </div>
            <div style={{
              padding: '12px 16px', borderRadius: 8, background: BG_INPUT, marginBottom: 12,
              display: 'flex', alignItems: 'baseline', gap: 8,
            }}>
              <span style={{ fontSize: 24, fontWeight: 700, color: PRIMARY }}>充¥{fenToYuan(p.charge_fen)}</span>
              <span style={{ fontSize: 14, color: SUCCESS, fontWeight: 600 }}>送¥{fenToYuan(p.bonus_fen)}</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, fontSize: 12 }}>
              <div>
                <div style={{ color: TEXT_3 }}>已售</div>
                <div style={{ color: TEXT_2, fontWeight: 600 }}>{p.total_sold}</div>
              </div>
              <div>
                <div style={{ color: TEXT_3 }}>总充值</div>
                <div style={{ color: TEXT_2, fontWeight: 600 }}>¥{fenToYuan(p.total_charged_fen)}</div>
              </div>
              <div>
                <div style={{ color: TEXT_3 }}>余额</div>
                <div style={{ color: TEXT_2, fontWeight: 600 }}>¥{fenToYuan(p.total_balance_fen)}</div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ============================================================
// 子组件 — 礼品卡Tab
// ============================================================

function GiftCardTab() {
  const [templates, setTemplates] = useState<GiftCardTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const res = await txFetchData<{ items: GiftCardTemplate[]; total: number }>('/api/v1/member/gift-cards/templates');
      setTemplates(res.items);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (error) return <ErrorBanner msg={error} onRetry={load} />;

  // 汇总统计
  const totalSold = templates.reduce((a, t) => a + t.total_sold, 0);
  const totalActivated = templates.reduce((a, t) => a + t.total_activated, 0);
  const totalBalance = templates.reduce((a, t) => a + t.total_balance_fen, 0);

  const summaryCards = [
    { label: '已售出', value: loading ? '-' : totalSold.toLocaleString(), color: PRIMARY },
    { label: '已激活', value: loading ? '-' : totalActivated.toLocaleString(), color: SUCCESS },
    { label: '总余额', value: loading ? '-' : `¥${fenToYuan(totalBalance)}`, color: WARNING },
  ];

  return (
    <div>
      {/* 汇总统计 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 20 }}>
        {summaryCards.map((c, i) => (
          <div key={i} style={{ background: BG_CARD, borderRadius: 10, padding: '14px 18px', border: `1px solid ${BORDER}` }}>
            <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 4 }}>{c.label}</div>
            {loading ? <Skeleton h={28} /> : <div style={{ fontSize: 24, fontWeight: 700, color: c.color }}>{c.value}</div>}
          </div>
        ))}
      </div>

      {/* 礼品卡模板 */}
      <div style={{ fontSize: 14, fontWeight: 600, color: TEXT_1, marginBottom: 12 }}>礼品卡模板</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 12 }}>
        {loading ? Array.from({ length: 3 }).map((_, i) => (
          <div key={i} style={{ background: BG_CARD, borderRadius: 10, padding: 16, border: `1px solid ${BORDER}` }}>
            <Skeleton h={100} /><div style={{ height: 10 }} /><Skeleton h={18} /><div style={{ height: 6 }} /><Skeleton h={14} w="50%" />
          </div>
        )) : templates.length === 0 ? (
          <div style={{ gridColumn: '1/-1', padding: 40, textAlign: 'center', color: TEXT_4, background: BG_CARD, borderRadius: 10, border: `1px solid ${BORDER}` }}>
            暂无礼品卡模板
          </div>
        ) : templates.map(t => (
          <div key={t.id} style={{
            background: BG_CARD, borderRadius: 10, overflow: 'hidden',
            border: `1px solid ${BORDER}`, opacity: t.is_active ? 1 : 0.5,
          }}>
            {/* 卡面 */}
            <div style={{
              height: 100, background: `linear-gradient(135deg, ${PRIMARY}, ${WARNING})`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              position: 'relative',
            }}>
              {t.design_url ? (
                <img src={t.design_url} alt={t.name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
              ) : (
                <span style={{ fontSize: 28, fontWeight: 800, color: '#fff' }}>¥{fenToYuan(t.face_value_fen)}</span>
              )}
              <span style={{
                position: 'absolute', top: 8, right: 8, fontSize: 10, padding: '2px 8px', borderRadius: 4,
                background: 'rgba(0,0,0,0.4)', color: '#fff',
              }}>{t.is_active ? '在售' : '停售'}</span>
            </div>
            <div style={{ padding: 14 }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: TEXT_1, marginBottom: 8 }}>{t.name}</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, fontSize: 12 }}>
                <div>
                  <div style={{ color: TEXT_3 }}>已售</div>
                  <div style={{ color: TEXT_2, fontWeight: 600 }}>{t.total_sold}</div>
                </div>
                <div>
                  <div style={{ color: TEXT_3 }}>已激活</div>
                  <div style={{ color: TEXT_2, fontWeight: 600 }}>{t.total_activated}</div>
                </div>
                <div>
                  <div style={{ color: TEXT_3 }}>余额</div>
                  <div style={{ color: TEXT_2, fontWeight: 600 }}>¥{fenToYuan(t.total_balance_fen)}</div>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ============================================================
// 主页面
// ============================================================

export default function CouponBenefitPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('coupon');

  return (
    <div style={{ minHeight: '100vh', background: BG_PAGE, padding: '20px 24px' }}>
      {/* shimmer keyframes */}
      <style>{`@keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }`}</style>

      {/* 页头 */}
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: TEXT_1 }}>券权益中心</h1>
        <p style={{ margin: '4px 0 0', fontSize: 13, color: TEXT_3 }}>管理优惠券、积分商城、储值卡、礼品卡等会员权益</p>
      </div>

      {/* Tab切换 */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 20, background: BG_CARD, borderRadius: 8, padding: 4, width: 'fit-content' }}>
        {TABS.map(t => (
          <button key={t.key} onClick={() => setActiveTab(t.key)} style={{
            padding: '8px 20px', borderRadius: 6, border: 'none',
            background: activeTab === t.key ? PRIMARY : 'transparent',
            color: activeTab === t.key ? '#fff' : TEXT_3,
            fontSize: 13, fontWeight: 600, cursor: 'pointer',
            transition: 'all 0.2s',
          }}>{t.label}</button>
        ))}
      </div>

      {/* Tab内容 */}
      {activeTab === 'coupon' && <CouponTab />}
      {activeTab === 'points' && <PointsTab />}
      {activeTab === 'stored_value' && <StoredValueTab />}
      {activeTab === 'gift_card' && <GiftCardTab />}
    </div>
  );
}
