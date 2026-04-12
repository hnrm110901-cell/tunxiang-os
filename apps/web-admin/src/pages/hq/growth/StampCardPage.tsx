/**
 * StampCardPage — 集章卡管理
 * 路由: /hq/growth/stamp-card
 * 接入真实 API: GET/POST /api/v1/stamp-cards/templates
 */
import { useState, useEffect, useCallback } from 'react';
import { txFetchData } from '../../../api';

// ── 设计 Token ──────────────────────────────────────────────────
const BG_1   = '#0d1e28';
const BG_2   = '#1a2a33';
const BG_3   = '#223040';
const BRAND  = '#FF6B35';
const GREEN  = '#52c41a';
const RED    = '#ff4d4f';
const YELLOW = '#faad14';
const BLUE   = '#1890ff';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

// ── 类型定义 ────────────────────────────────────────────────────
type TabKey = 'templates' | 'instances' | 'analytics';

interface StampTemplate {
  id: string;
  name: string;
  target_stamps: number;
  reward_type: string;
  reward_config: Record<string, unknown>;
  validity_days: number;
  min_order_fen: number;
  status?: string;
  issued_count?: number;
  completed_count?: number;
  created_at?: string;
}

interface KPI {
  label: string;
  value: string;
  sub: string;
  trend: 'up' | 'down' | 'flat';
  color?: string;
}

interface CreateTemplateForm {
  name: string;
  target_stamps: number;
  reward_type: string;
  reward_desc: string;
  validity_days: number;
  min_order_fen_yuan: string;
}

// ── 工具函数 ────────────────────────────────────────────────────
function fenToYuan(v: number): string {
  return v > 0 ? `¥${(v / 100).toFixed(0)}起` : '无门槛';
}

function calcCompletionRate(issued: number, completed: number): string {
  if (issued <= 0) return '-';
  return `${((completed / issued) * 100).toFixed(1)}%`;
}

function statusColor(status: string): string {
  if (status === 'active' || status === '进行中') return GREEN;
  if (status === 'pending' || status === '待启动') return YELLOW;
  return TEXT_4;
}

function statusBg(status: string): string {
  if (status === 'active' || status === '进行中') return 'rgba(82,196,26,0.15)';
  if (status === 'pending' || status === '待启动') return 'rgba(250,173,20,0.15)';
  return 'rgba(255,255,255,0.06)';
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    active: '进行中', pending: '待启动', ended: '已结束',
    进行中: '进行中', 待启动: '待启动', 已结束: '已结束',
  };
  return map[status] ?? status;
}

// ── 主页面 ──────────────────────────────────────────────────────
export function StampCardPage() {
  const [tab, setTab] = useState<TabKey>('templates');
  const [showCreate, setShowCreate] = useState(false);
  const [templates, setTemplates] = useState<StampTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [apiError, setApiError] = useState<string | null>(null);

  const tabs: { key: TabKey; label: string }[] = [
    { key: 'templates', label: '集章卡模板' },
    { key: 'instances', label: '会员集章' },
    { key: 'analytics', label: '效果分析' },
  ];

  const loadTemplates = useCallback(async () => {
    setLoading(true);
    setApiError(null);
    try {
      const data = await txFetchData<StampTemplate[] | { items: StampTemplate[] }>(
        '/api/v1/stamp-cards/templates'
      );
      const list = Array.isArray(data) ? data : (data as { items: StampTemplate[] }).items ?? [];
      setTemplates(list);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '接口暂不可用';
      setApiError(msg);
      setTemplates([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadTemplates(); }, [loadTemplates]);

  // 汇总 KPI
  const kpis: KPI[] = (() => {
    const active = templates.filter(t => t.status === 'active' || t.status === '进行中');
    const totalIssued = templates.reduce((s, t) => s + (t.issued_count ?? 0), 0);
    const totalCompleted = templates.reduce((s, t) => s + (t.completed_count ?? 0), 0);
    return [
      { label: '发行量（张）', value: totalIssued > 0 ? totalIssued.toLocaleString() : '-', sub: `共 ${templates.length} 个模板`, trend: 'up' },
      { label: '活跃模板', value: String(active.length), sub: `占比 ${templates.length > 0 ? Math.round((active.length / templates.length) * 100) : 0}%`, trend: 'up', color: BRAND },
      { label: '完成率', value: calcCompletionRate(totalIssued, totalCompleted), sub: `已完成 ${totalCompleted} 张`, trend: 'up', color: GREEN },
      { label: '兑换量（张）', value: totalCompleted > 0 ? totalCompleted.toLocaleString() : '-', sub: '已完成集章兑换', trend: 'up', color: BLUE },
    ];
  })();

  return (
    <div style={{ padding: 24, background: BG_1, minHeight: '100vh', color: TEXT_1, fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif' }}>

      {/* Header */}
      <div style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>集章卡管理</h1>
          <div style={{ fontSize: 13, color: TEXT_3, marginTop: 4 }}>消费集章 · 到店复购 · 会员粘性</div>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <button
            onClick={loadTemplates}
            style={{ background: BG_3, color: TEXT_2, border: '1px solid rgba(255,255,255,0.08)', borderRadius: 6, padding: '8px 14px', fontSize: 13, cursor: 'pointer' }}
          >
            刷新
          </button>
          <button
            onClick={() => setShowCreate(true)}
            style={{ background: BRAND, color: '#fff', border: 'none', borderRadius: 6, padding: '8px 20px', fontSize: 14, fontWeight: 600, cursor: 'pointer' }}
          >
            + 创建集章卡
          </button>
        </div>
      </div>

      {/* API 异常提示 */}
      {apiError && (
        <div style={{ marginBottom: 16, padding: '12px 16px', background: 'rgba(255,77,79,0.1)', border: '1px solid rgba(255,77,79,0.3)', borderRadius: 8, fontSize: 13, color: RED }}>
          接口暂不可用：{apiError}。当前显示空数据，请检查后端服务是否启动。
        </div>
      )}

      {/* KPI 卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
        {kpis.map(k => (
          <div key={k.label} style={{ background: BG_2, borderRadius: 10, padding: 18, borderLeft: `3px solid ${k.color ?? BRAND}` }}>
            <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 6 }}>{k.label}</div>
            <div style={{ fontSize: 28, fontWeight: 700, color: k.color ?? TEXT_1 }}>{loading ? '—' : k.value}</div>
            <div style={{ fontSize: 12, color: TEXT_4, marginTop: 6 }}>
              {k.trend === 'up' ? '↑ ' : k.trend === 'down' ? '↓ ' : ''}{k.sub}
            </div>
          </div>
        ))}
      </div>

      {/* Tab 切换 */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 20, background: BG_2, borderRadius: 8, padding: 4, width: 'fit-content' }}>
        {tabs.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            style={{
              padding: '8px 22px', fontSize: 14, fontWeight: tab === t.key ? 600 : 400, cursor: 'pointer',
              border: 'none', borderRadius: 6,
              background: tab === t.key ? BRAND : 'transparent',
              color: tab === t.key ? '#fff' : TEXT_3,
              transition: 'all 0.15s',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* 内容区 */}
      {tab === 'templates' && (
        <TemplatesTab templates={templates} loading={loading} onRefresh={loadTemplates} />
      )}
      {tab === 'instances' && <InstancesTab />}
      {tab === 'analytics' && <AnalyticsTab templates={templates} />}

      {/* 新建弹窗 */}
      {showCreate && (
        <CreateModal onClose={() => setShowCreate(false)} onSuccess={() => { setShowCreate(false); loadTemplates(); }} />
      )}
    </div>
  );
}

// ── 模板列表 Tab ─────────────────────────────────────────────────
function TemplatesTab({ templates, loading, onRefresh }: {
  templates: StampTemplate[];
  loading: boolean;
  onRefresh: () => void;
}) {
  if (loading) {
    return (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 16 }}>
        {[1, 2, 3].map(i => (
          <div key={i} style={{ background: BG_2, borderRadius: 12, padding: 20, height: 200, opacity: 0.4 }}>
            <div style={{ background: BG_3, height: 18, width: '60%', borderRadius: 4, marginBottom: 12 }} />
            <div style={{ background: BG_3, height: 40, borderRadius: 4, marginBottom: 12 }} />
            <div style={{ background: BG_3, height: 14, width: '80%', borderRadius: 4 }} />
          </div>
        ))}
      </div>
    );
  }

  if (templates.length === 0) {
    return (
      <div style={{ background: BG_2, borderRadius: 12, padding: 60, textAlign: 'center' }}>
        <div style={{ fontSize: 40, marginBottom: 16 }}>🎟</div>
        <div style={{ fontSize: 15, color: TEXT_2, marginBottom: 8 }}>暂无集章卡模板</div>
        <div style={{ fontSize: 13, color: TEXT_4 }}>点击右上角「创建集章卡」开始您的第一个集章活动</div>
        <button onClick={onRefresh} style={{ marginTop: 20, background: BRAND, color: '#fff', border: 'none', borderRadius: 6, padding: '8px 20px', fontSize: 13, cursor: 'pointer' }}>
          重新加载
        </button>
      </div>
    );
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 16 }}>
      {templates.map(t => {
        const issued = t.issued_count ?? 0;
        const completed = t.completed_count ?? 0;
        const rewardDesc = typeof t.reward_config?.desc === 'string'
          ? t.reward_config.desc
          : (t.reward_type === 'coupon' ? '优惠券奖励' : t.reward_type === 'free_dish' ? '免费菜品' : `${t.reward_type}奖励`);

        return (
          <div key={t.id} style={{ background: BG_2, borderRadius: 12, padding: 20, position: 'relative', overflow: 'hidden', border: '1px solid rgba(255,255,255,0.04)' }}>
            {/* 状态角标 */}
            <div style={{ position: 'absolute', top: 14, right: 14 }}>
              <span style={{
                padding: '3px 10px', borderRadius: 12, fontSize: 11, fontWeight: 500,
                background: statusBg(t.status ?? ''),
                color: statusColor(t.status ?? ''),
              }}>
                {statusLabel(t.status ?? 'active')}
              </span>
            </div>

            <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 600, paddingRight: 80 }}>{t.name}</h3>

            {/* 集章进度可视化 */}
            <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginBottom: 16 }}>
              {Array.from({ length: Math.min(t.target_stamps, 10) }).map((_, i) => (
                <div key={i} style={{
                  width: 26, height: 26, borderRadius: '50%',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12,
                  background: i < Math.min(3, t.target_stamps) ? BRAND : 'rgba(255,255,255,0.06)',
                  color: i < Math.min(3, t.target_stamps) ? '#fff' : TEXT_4,
                  fontWeight: 600,
                }}>
                  {i < Math.min(3, t.target_stamps) ? '✓' : (i + 1)}
                </div>
              ))}
              {t.target_stamps > 10 && (
                <div style={{ width: 26, height: 26, display: 'flex', alignItems: 'center', justifyContent: 'center', color: TEXT_4, fontSize: 12 }}>…</div>
              )}
            </div>

            {/* 规则说明 */}
            <div style={{ fontSize: 13, color: TEXT_2, marginBottom: 6 }}>
              集满 <span style={{ color: BRAND, fontWeight: 700 }}>{t.target_stamps}</span> 章兑换：
              <span style={{ color: BRAND, fontWeight: 500 }}> {rewardDesc}</span>
            </div>
            <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 16 }}>
              门槛：{fenToYuan(t.min_order_fen)} · 有效期 {t.validity_days} 天
            </div>

            {/* 数据统计 */}
            <div style={{ display: 'flex', justifyContent: 'space-between', paddingTop: 14, borderTop: '1px solid rgba(255,255,255,0.06)' }}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 20, fontWeight: 700 }}>{issued}</div>
                <div style={{ fontSize: 11, color: TEXT_4, marginTop: 2 }}>已发放</div>
              </div>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 20, fontWeight: 700, color: GREEN }}>{completed}</div>
                <div style={{ fontSize: 11, color: TEXT_4, marginTop: 2 }}>已完成</div>
              </div>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 20, fontWeight: 700, color: BLUE }}>{calcCompletionRate(issued, completed)}</div>
                <div style={{ fontSize: 11, color: TEXT_4, marginTop: 2 }}>完成率</div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── 会员集章 Tab（依赖 /my 接口，需带 customer_id 参数）────────────
function InstancesTab() {
  return (
    <div style={{ background: BG_2, borderRadius: 12, padding: 40, textAlign: 'center' }}>
      <div style={{ fontSize: 36, marginBottom: 14 }}>🔍</div>
      <div style={{ fontSize: 15, color: TEXT_2, marginBottom: 8 }}>会员集章进度查询</div>
      <div style={{ fontSize: 13, color: TEXT_4, maxWidth: 400, margin: '0 auto 20px' }}>
        请通过「会员档案」页面搜索具体会员，查看其集章卡进度与兑换记录。
        接口：<code style={{ color: BRAND, fontSize: 12 }}>GET /api/v1/stamp-cards/my?customer_id=xxx</code>
      </div>
      <div style={{ display: 'inline-block', padding: '8px 20px', background: BG_3, borderRadius: 8, fontSize: 12, color: TEXT_3, border: '1px solid rgba(255,255,255,0.06)' }}>
        功能路径：会员管理 → 会员档案 → 集章记录
      </div>
    </div>
  );
}

// ── 效果分析 Tab ─────────────────────────────────────────────────
function AnalyticsTab({ templates }: { templates: StampTemplate[] }) {
  const active = templates.filter(t => t.status === 'active' || t.status === '进行中');
  const totalIssued = templates.reduce((s, t) => s + (t.issued_count ?? 0), 0);
  const totalCompleted = templates.reduce((s, t) => s + (t.completed_count ?? 0), 0);

  // 按完成率排序前5
  const ranked = [...templates]
    .filter(t => (t.issued_count ?? 0) > 0)
    .sort((a, b) => {
      const ra = (a.completed_count ?? 0) / (a.issued_count ?? 1);
      const rb = (b.completed_count ?? 0) / (b.issued_count ?? 1);
      return rb - ra;
    })
    .slice(0, 5);

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
      {/* 总体概览 */}
      <div style={{ background: BG_2, borderRadius: 10, padding: 20 }}>
        <h3 style={{ margin: '0 0 18px', fontSize: 15, fontWeight: 600 }}>活动总览</h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          {[
            { label: '模板总数', value: templates.length, color: TEXT_1 },
            { label: '活跃中', value: active.length, color: GREEN },
            { label: '累计发放', value: totalIssued.toLocaleString(), color: BLUE },
            { label: '累计完成', value: totalCompleted.toLocaleString(), color: BRAND },
          ].map(m => (
            <div key={m.label} style={{ padding: 14, background: BG_3, borderRadius: 8 }}>
              <div style={{ fontSize: 11, color: TEXT_3, marginBottom: 6 }}>{m.label}</div>
              <div style={{ fontSize: 24, fontWeight: 700, color: m.color }}>{m.value}</div>
            </div>
          ))}
        </div>
        {/* 进度条：整体完成率 */}
        <div style={{ marginTop: 18 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 6 }}>
            <span style={{ color: TEXT_3 }}>整体完成率</span>
            <span style={{ color: BRAND, fontWeight: 600 }}>{calcCompletionRate(totalIssued, totalCompleted)}</span>
          </div>
          <div style={{ height: 8, background: 'rgba(255,255,255,0.06)', borderRadius: 4, overflow: 'hidden' }}>
            <div style={{
              width: totalIssued > 0 ? `${Math.min((totalCompleted / totalIssued) * 100, 100)}%` : '0%',
              height: '100%', background: BRAND, borderRadius: 4,
              transition: 'width 0.5s ease',
            }} />
          </div>
        </div>
      </div>

      {/* 完成率排行 */}
      <div style={{ background: BG_2, borderRadius: 10, padding: 20 }}>
        <h3 style={{ margin: '0 0 18px', fontSize: 15, fontWeight: 600 }}>完成率 TOP 5</h3>
        {ranked.length === 0 ? (
          <div style={{ color: TEXT_4, fontSize: 13, textAlign: 'center', paddingTop: 40 }}>暂无足够数据</div>
        ) : (
          ranked.map((t, i) => {
            const rate = ((t.completed_count ?? 0) / (t.issued_count ?? 1)) * 100;
            const barColors = [BRAND, GREEN, BLUE, YELLOW, TEXT_3];
            return (
              <div key={t.id} style={{ marginBottom: 14 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 5 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{
                      width: 20, height: 20, borderRadius: 4, background: barColors[i],
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: 11, fontWeight: 700, color: '#fff', flexShrink: 0,
                    }}>
                      {i + 1}
                    </span>
                    <span style={{ color: TEXT_2 }}>{t.name}</span>
                  </div>
                  <span style={{ color: barColors[i], fontWeight: 600 }}>{rate.toFixed(1)}%</span>
                </div>
                <div style={{ height: 5, background: 'rgba(255,255,255,0.06)', borderRadius: 3, overflow: 'hidden' }}>
                  <div style={{ width: `${Math.min(rate, 100)}%`, height: '100%', background: barColors[i], borderRadius: 3 }} />
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

// ── 创建集章卡弹窗 ───────────────────────────────────────────────
function CreateModal({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const [form, setForm] = useState<CreateTemplateForm>({
    name: '',
    target_stamps: 5,
    reward_type: 'free_dish',
    reward_desc: '',
    validity_days: 90,
    min_order_fen_yuan: '0',
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async () => {
    if (!form.name.trim()) { setError('请填写活动名称'); return; }
    if (!form.reward_desc.trim()) { setError('请填写奖励描述'); return; }
    if (form.target_stamps < 2 || form.target_stamps > 50) { setError('集章数量需在 2-50 之间'); return; }

    setSubmitting(true);
    setError(null);
    try {
      const minOrderFen = Math.round(parseFloat(form.min_order_fen_yuan || '0') * 100);
      await txFetchData('/api/v1/stamp-cards/templates', {
        method: 'POST',
        body: JSON.stringify({
          name: form.name.trim(),
          target_stamps: form.target_stamps,
          reward_type: form.reward_type,
          reward_config: { desc: form.reward_desc.trim() },
          validity_days: form.validity_days,
          min_order_fen: isNaN(minOrderFen) ? 0 : minOrderFen,
          applicable_stores: [],
        }),
      });
      onSuccess();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '创建失败，请重试';
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const inputStyle: React.CSSProperties = {
    width: '100%', background: BG_3, border: '1px solid rgba(255,255,255,0.1)',
    borderRadius: 6, padding: '9px 12px', color: TEXT_1, fontSize: 14, outline: 'none',
    boxSizing: 'border-box',
  };
  const labelStyle: React.CSSProperties = { fontSize: 13, color: TEXT_2, marginBottom: 6, display: 'block' };

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.65)', zIndex: 1000,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div style={{ background: BG_2, borderRadius: 12, padding: 28, width: 480, maxHeight: '90vh', overflowY: 'auto' }}>
        <h2 style={{ margin: '0 0 24px', fontSize: 18, fontWeight: 700 }}>创建集章卡活动</h2>

        {/* 活动名称 */}
        <div style={{ marginBottom: 16 }}>
          <label style={labelStyle}>活动名称 *</label>
          <input
            style={inputStyle}
            placeholder="例：集5章送招牌拿铁"
            value={form.name}
            onChange={e => setForm(p => ({ ...p, name: e.target.value }))}
          />
        </div>

        {/* 集章数 + 奖励类型 */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 16 }}>
          <div>
            <label style={labelStyle}>集章数量（2-50）*</label>
            <input
              type="number" min={2} max={50} style={inputStyle}
              value={form.target_stamps}
              onChange={e => setForm(p => ({ ...p, target_stamps: parseInt(e.target.value) || 5 }))}
            />
          </div>
          <div>
            <label style={labelStyle}>奖励类型</label>
            <select
              style={{ ...inputStyle, cursor: 'pointer' }}
              value={form.reward_type}
              onChange={e => setForm(p => ({ ...p, reward_type: e.target.value }))}
            >
              <option value="free_dish">免费菜品</option>
              <option value="coupon">优惠券</option>
              <option value="points">积分奖励</option>
              <option value="stored_value">储值赠送</option>
            </select>
          </div>
        </div>

        {/* 奖励描述 */}
        <div style={{ marginBottom: 16 }}>
          <label style={labelStyle}>奖励说明 *</label>
          <input
            style={inputStyle}
            placeholder="例：招牌拿铁一杯"
            value={form.reward_desc}
            onChange={e => setForm(p => ({ ...p, reward_desc: e.target.value }))}
          />
        </div>

        {/* 有效期 + 消费门槛 */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 24 }}>
          <div>
            <label style={labelStyle}>有效期（天）</label>
            <input
              type="number" min={1} max={365} style={inputStyle}
              value={form.validity_days}
              onChange={e => setForm(p => ({ ...p, validity_days: parseInt(e.target.value) || 90 }))}
            />
          </div>
          <div>
            <label style={labelStyle}>消费门槛（元，0=无）</label>
            <input
              type="number" min={0} step="0.01" style={inputStyle}
              value={form.min_order_fen_yuan}
              onChange={e => setForm(p => ({ ...p, min_order_fen_yuan: e.target.value }))}
            />
          </div>
        </div>

        {error && (
          <div style={{ marginBottom: 16, padding: '10px 14px', background: 'rgba(255,77,79,0.1)', border: '1px solid rgba(255,77,79,0.3)', borderRadius: 6, fontSize: 13, color: RED }}>
            {error}
          </div>
        )}

        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button
            onClick={onClose}
            style={{ padding: '9px 22px', borderRadius: 6, border: '1px solid rgba(255,255,255,0.1)', background: 'transparent', color: TEXT_2, fontSize: 14, cursor: 'pointer' }}
          >
            取消
          </button>
          <button
            onClick={handleSubmit}
            disabled={submitting}
            style={{ padding: '9px 24px', borderRadius: 6, border: 'none', background: submitting ? TEXT_4 : BRAND, color: '#fff', fontSize: 14, fontWeight: 600, cursor: submitting ? 'not-allowed' : 'pointer' }}
          >
            {submitting ? '创建中...' : '创建活动'}
          </button>
        </div>
      </div>
    </div>
  );
}
