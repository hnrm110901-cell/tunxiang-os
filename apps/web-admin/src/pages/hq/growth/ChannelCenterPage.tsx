/**
 * ChannelCenterPage — 渠道中心（增长工具）
 * 路由: /hq/growth/channels
 * 渠道GMV/订单量统计 + 渠道卡片 + 趋势折线图 + 渠道配置展示
 * 数据来源: /api/v1/finance/analytics/revenue-composition
 */
import { useState, useEffect } from 'react';
import { txFetchData } from '../../../api';

// ─── 主题常量 ───
const BG = '#0d1e28';
const BG_1 = '#112228';
const BG_2 = '#1a2a33';
const BRAND = '#FF6B35';
const GREEN = '#52c41a';
const RED = '#ff4d4f';
const YELLOW = '#faad14';
const BLUE = '#1890ff';
const PURPLE = '#722ed1';
const CYAN = '#13c2c2';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

type TabKey = 'overview' | 'trend' | 'config';

// ─── API 类型 ───
interface RevenueChannel {
  name: string;
  amount_fen: number;
  percent: number;
}

interface FinanceTrend {
  date: string;
  revenue_fen: number;
  cost_fen: number;
  profit_fen: number;
  margin_rate: number;
}

// ─── 渠道映射配置（本地静态，不受API影响）───
const CHANNEL_CONFIGS = [
  { key: 'wechat',    label: '微信点餐',  icon: '💬', color: GREEN,  apiKeywords: ['微信', 'wechat', '小程序'] },
  { key: 'douyin',    label: '抖音团购',  icon: '🎵', color: RED,    apiKeywords: ['抖音', 'douyin', 'tiktok'] },
  { key: 'xiaohongshu', label: '小红书',  icon: '📕', color: '#FF2442', apiKeywords: ['小红书', 'xiaohongshu'] },
  { key: 'meituan',  label: '美团外卖',  icon: '🦁', color: YELLOW, apiKeywords: ['美团', 'meituan'] },
  { key: 'eleme',    label: '饿了么',    icon: '🌊', color: BLUE,   apiKeywords: ['饿了么', 'eleme'] },
  { key: 'dine_in',  label: '堂食现场',  icon: '🍽️', color: CYAN,   apiKeywords: ['堂食', '现场', 'dine', '线下'] },
];

// ─── 工具函数 ───
function fenToWan(fen: number): string {
  const yuan = fen / 100;
  if (yuan >= 10000) return `${(yuan / 10000).toFixed(1)}万`;
  if (yuan >= 1000) return `${(yuan / 1000).toFixed(1)}千`;
  return `¥${yuan.toFixed(0)}`;
}

function fenToYuan(fen: number): string {
  return `¥${(fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
}

// ─── KPI汇总卡片 ───
function KpiCard({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '14px 16px',
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ fontSize: 11, color: TEXT_4, marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: color || TEXT_1 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: TEXT_3, marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

// ─── 渠道概览卡片 ───
interface ChannelCardData {
  key: string;
  label: string;
  icon: string;
  color: string;
  gmv_fen: number;
  percent: number;
  hasData: boolean;
}

function ChannelOverview({ channels }: { channels: ChannelCardData[] }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 12 }}>
      {channels.map(ch => (
        <div key={ch.key} style={{
          background: BG_1, borderRadius: 10, padding: 16,
          border: `1px solid ${BG_2}`,
          borderTop: `3px solid ${ch.color}`,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 20 }}>{ch.icon}</span>
              <span style={{ fontSize: 15, fontWeight: 700, color: TEXT_1 }}>{ch.label}</span>
            </div>
            <span style={{
              fontSize: 10, padding: '2px 8px', borderRadius: 4,
              background: ch.hasData ? GREEN + '22' : TEXT_4 + '22',
              color: ch.hasData ? GREEN : TEXT_4, fontWeight: 600,
            }}>{ch.hasData ? '有数据' : '功能对接中'}</span>
          </div>

          {ch.hasData ? (
            <>
              <div style={{ marginBottom: 10 }}>
                <div style={{ fontSize: 10, color: TEXT_4, marginBottom: 3 }}>本月GMV</div>
                <div style={{ fontSize: 20, fontWeight: 700, color: BRAND }}>{fenToWan(ch.gmv_fen)}</div>
              </div>
              <div style={{ marginBottom: 10 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                  <span style={{ fontSize: 10, color: TEXT_4 }}>占总GMV</span>
                  <span style={{ fontSize: 11, fontWeight: 600, color: ch.color }}>{ch.percent.toFixed(1)}%</span>
                </div>
                <div style={{ height: 4, background: BG_2, borderRadius: 2 }}>
                  <div style={{
                    height: '100%', borderRadius: 2, width: `${Math.min(ch.percent, 100)}%`,
                    background: ch.color,
                  }} />
                </div>
              </div>
            </>
          ) : (
            <div style={{
              padding: '12px 0', textAlign: 'center',
              fontSize: 12, color: TEXT_4,
            }}>
              暂无渠道数据<br />
              <span style={{ fontSize: 10, color: TEXT_4 + '88' }}>接入后自动展示</span>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ─── 趋势折线图（手写SVG）───
function TrendChart({ items }: { items: FinanceTrend[] }) {
  if (!items || items.length === 0) {
    return (
      <div style={{
        background: BG_1, borderRadius: 10, padding: 20,
        border: `1px solid ${BG_2}`, textAlign: 'center',
        color: TEXT_4, fontSize: 13, height: 200,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        flexDirection: 'column', gap: 8,
      }}>
        <span style={{ fontSize: 24 }}>📊</span>
        <span>财务趋势数据对接中</span>
        <span style={{ fontSize: 11, color: TEXT_4 + '88' }}>API: /api/v1/finance/analytics/trend</span>
      </div>
    );
  }

  const W = 800;
  const H = 200;
  const PAD = { top: 20, right: 20, bottom: 30, left: 60 };
  const chartW = W - PAD.left - PAD.right;
  const chartH = H - PAD.top - PAD.bottom;

  const maxVal = Math.max(...items.map(d => d.revenue_fen), 1);
  const minVal = 0;

  const toX = (i: number) => PAD.left + (i / (items.length - 1)) * chartW;
  const toY = (v: number) => PAD.top + chartH - ((v - minVal) / (maxVal - minVal)) * chartH;

  const revenuePoints = items.map((d, i) => `${toX(i)},${toY(d.revenue_fen)}`).join(' ');
  const profitPoints  = items.map((d, i) => `${toX(i)},${toY(d.profit_fen)}`).join(' ');

  // 填充路径（收入）
  const revenueFill = `M${PAD.left},${toY(items[0].revenue_fen)} L${revenuePoints} L${toX(items.length - 1)},${PAD.top + chartH} L${PAD.left},${PAD.top + chartH} Z`;

  const yTicks = 4;
  const showDates = items.length <= 14
    ? items.map((d, i) => ({ i, label: d.date.slice(5) }))
    : items.filter((_, i) => i % Math.ceil(items.length / 7) === 0).map((d, i2) => ({
        i: items.indexOf(d), label: d.date.slice(5),
      }));

  return (
    <div style={{ background: BG_1, borderRadius: 10, padding: 16, border: `1px solid ${BG_2}` }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <h3 style={{ margin: 0, fontSize: 14, fontWeight: 700, color: TEXT_1 }}>渠道收入趋势</h3>
        <div style={{ display: 'flex', gap: 12, fontSize: 11 }}>
          <span style={{ color: BRAND }}>● 总收入</span>
          <span style={{ color: GREEN }}>● 利润</span>
        </div>
      </div>
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ overflow: 'visible' }}>
        {/* 网格线 */}
        {Array.from({ length: yTicks + 1 }).map((_, ti) => {
          const y = PAD.top + (ti / yTicks) * chartH;
          const v = maxVal - (ti / yTicks) * maxVal;
          return (
            <g key={ti}>
              <line x1={PAD.left} y1={y} x2={PAD.left + chartW} y2={y}
                stroke={BG_2} strokeWidth={1} />
              <text x={PAD.left - 6} y={y + 4} textAnchor="end"
                fill={TEXT_4} fontSize={9}>{fenToWan(v)}</text>
            </g>
          );
        })}

        {/* X轴标签 */}
        {showDates.map(({ i, label }) => (
          <text key={i} x={toX(i)} y={PAD.top + chartH + 16} textAnchor="middle"
            fill={TEXT_4} fontSize={9}>{label}</text>
        ))}

        {/* 收入填充 */}
        <path d={revenueFill} fill={BRAND + '18'} />

        {/* 收入折线 */}
        <polyline points={revenuePoints} fill="none" stroke={BRAND} strokeWidth={2} strokeLinejoin="round" />

        {/* 利润折线 */}
        <polyline points={profitPoints} fill="none" stroke={GREEN} strokeWidth={2}
          strokeDasharray="5,3" strokeLinejoin="round" />

        {/* 数据点（仅收入） */}
        {items.map((d, i) => (
          <circle key={i} cx={toX(i)} cy={toY(d.revenue_fen)} r={2.5}
            fill={BRAND} stroke={BG_1} strokeWidth={1.5} />
        ))}
      </svg>

      {/* 汇总 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginTop: 10 }}>
        {[
          { label: '周期总收入', value: fenToWan(items.reduce((a, b) => a + b.revenue_fen, 0)), color: BRAND },
          { label: '周期总利润', value: fenToWan(items.reduce((a, b) => a + b.profit_fen, 0)), color: GREEN },
          { label: '平均毛利率', value: `${(items.reduce((a, b) => a + b.margin_rate, 0) / items.length).toFixed(1)}%`, color: BLUE },
        ].map((item, i) => (
          <div key={i} style={{ background: BG_2, borderRadius: 8, padding: '10px 12px', textAlign: 'center' }}>
            <div style={{ fontSize: 10, color: TEXT_4, marginBottom: 4 }}>{item.label}</div>
            <div style={{ fontSize: 16, fontWeight: 700, color: item.color }}>{item.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── 渠道配置展示（只读） ───
function ChannelConfigReadonly({ channels }: { channels: ChannelCardData[] }) {
  const [selected, setSelected] = useState(channels[0]?.key || '');
  const ch = channels.find(c => c.key === selected) || channels[0];

  if (!ch) return null;

  return (
    <div style={{ display: 'flex', gap: 16 }}>
      {/* 左侧列表 */}
      <div style={{
        width: 180, background: BG_1, borderRadius: 10, padding: 10,
        border: `1px solid ${BG_2}`, flexShrink: 0,
      }}>
        {channels.map(c => (
          <div key={c.key} onClick={() => setSelected(c.key)} style={{
            padding: '10px 12px', borderRadius: 6, cursor: 'pointer',
            background: selected === c.key ? BRAND + '22' : 'transparent',
            borderLeft: selected === c.key ? `3px solid ${BRAND}` : '3px solid transparent',
            marginBottom: 2, display: 'flex', alignItems: 'center', gap: 6,
          }}>
            <span style={{ fontSize: 14 }}>{c.icon}</span>
            <span style={{ fontSize: 12, color: selected === c.key ? TEXT_1 : TEXT_3, fontWeight: selected === c.key ? 600 : 400 }}>
              {c.label}
            </span>
          </div>
        ))}
      </div>

      {/* 右侧详情 */}
      <div style={{ flex: 1, background: BG_1, borderRadius: 10, padding: 20, border: `1px solid ${BG_2}` }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
          <span style={{ fontSize: 24 }}>{ch.icon}</span>
          <h3 style={{ margin: 0, fontSize: 17, fontWeight: 700, color: TEXT_1 }}>{ch.label}</h3>
          <span style={{
            fontSize: 10, padding: '2px 8px', borderRadius: 4,
            background: ch.hasData ? GREEN + '22' : TEXT_4 + '22',
            color: ch.hasData ? GREEN : TEXT_4, fontWeight: 600,
          }}>{ch.hasData ? '已接入' : '功能对接中'}</span>
        </div>

        {ch.hasData ? (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12, marginBottom: 16 }}>
              {[
                { label: '本月GMV', value: fenToWan(ch.gmv_fen), color: BRAND },
                { label: '占比', value: `${ch.percent.toFixed(1)}%`, color: ch.color },
              ].map((item, i) => (
                <div key={i} style={{ background: BG_2, borderRadius: 8, padding: 12 }}>
                  <div style={{ fontSize: 10, color: TEXT_4, marginBottom: 4 }}>{item.label}</div>
                  <div style={{ fontSize: 20, fontWeight: 700, color: item.color }}>{item.value}</div>
                </div>
              ))}
            </div>

            <div style={{
              padding: '12px 14px', background: BG_2, borderRadius: 8,
              fontSize: 12, color: TEXT_3, lineHeight: 2,
            }}>
              <div>渠道标识: <strong style={{ color: TEXT_1 }}>{ch.key}</strong></div>
              <div>颜色主题: <strong style={{ color: ch.color }}>●</strong><span style={{ color: TEXT_1 }}> {ch.color}</span></div>
              <div style={{ color: YELLOW, fontSize: 11 }}>
                ⚠ 渠道开关配置需在 tx-member 服务后台操作
              </div>
            </div>
          </>
        ) : (
          <div style={{
            padding: 24, textAlign: 'center', background: BG_2, borderRadius: 8,
            color: TEXT_4, fontSize: 13,
          }}>
            <div style={{ fontSize: 28, marginBottom: 8 }}>🔧</div>
            <div>该渠道尚未接入或暂无数据</div>
            <div style={{ fontSize: 11, marginTop: 6, color: TEXT_4 + '88' }}>
              配置入口：运营后台 → 渠道管理
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── 主页面 ───
export function ChannelCenterPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('overview');
  const [loading, setLoading] = useState(true);
  const [revenueItems, setRevenueItems] = useState<RevenueChannel[]>([]);
  const [trendItems, setTrendItems] = useState<FinanceTrend[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);

      try {
        const [revResp, trendResp] = await Promise.allSettled([
          txFetchData<{ items: RevenueChannel[] }>('/api/v1/finance/analytics/revenue-composition?period=month'),
          txFetchData<{ items: FinanceTrend[] }>('/api/v1/finance/analytics/trend?period=month&days=30'),
        ]);

        if (!cancelled) {
          if (revResp.status === 'fulfilled') {
            setRevenueItems(revResp.value.items || []);
          }
          if (trendResp.status === 'fulfilled') {
            setTrendItems(trendResp.value.items || []);
          }
        }
      } catch {
        if (!cancelled) setError('数据加载失败，部分功能使用本地展示');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => { cancelled = true; };
  }, []);

  // 将 API 数据映射到渠道卡片
  const channelCards: ChannelCardData[] = CHANNEL_CONFIGS.map(cfg => {
    const matched = revenueItems.find(item =>
      cfg.apiKeywords.some(kw => item.name.toLowerCase().includes(kw.toLowerCase()))
    );
    return {
      key: cfg.key,
      label: cfg.label,
      icon: cfg.icon,
      color: cfg.color,
      gmv_fen: matched?.amount_fen || 0,
      percent: matched?.percent || 0,
      hasData: !!matched,
    };
  });

  const totalGmv = revenueItems.reduce((s, r) => s + r.amount_fen, 0);
  const activeChannels = channelCards.filter(c => c.hasData).length;

  const tabs: { key: TabKey; label: string }[] = [
    { key: 'overview', label: '渠道概览' },
    { key: 'trend', label: '收入趋势' },
    { key: 'config', label: '渠道配置' },
  ];

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto', background: BG, minHeight: '100vh', padding: '0 0 32px' }}>
      {/* 页头 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: TEXT_1 }}>渠道中心</h2>
        {loading && (
          <span style={{ fontSize: 12, color: TEXT_4, padding: '4px 10px', background: BG_2, borderRadius: 6 }}>
            加载中...
          </span>
        )}
        {error && (
          <span style={{ fontSize: 12, color: YELLOW, padding: '4px 10px', background: YELLOW + '15', borderRadius: 6 }}>
            ⚠ {error}
          </span>
        )}
      </div>

      {/* KPI 汇总 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
        <KpiCard
          label="本月总GMV"
          value={loading ? '—' : fenToWan(totalGmv)}
          sub="所有渠道合计"
          color={BRAND}
        />
        <KpiCard
          label="已接入渠道"
          value={loading ? '—' : `${activeChannels} / ${CHANNEL_CONFIGS.length}`}
          sub="有数据渠道数"
          color={GREEN}
        />
        <KpiCard
          label="最大渠道占比"
          value={loading || channelCards.every(c => !c.hasData) ? '—'
            : `${Math.max(...channelCards.map(c => c.percent)).toFixed(1)}%`}
          sub={loading ? '' : channelCards.sort((a, b) => b.percent - a.percent)[0]?.label}
          color={PURPLE}
        />
        <KpiCard
          label="数据时段"
          value="本月"
          sub="月度汇总"
          color={BLUE}
        />
      </div>

      {/* Tab 切换 */}
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

      {/* 内容区 */}
      {activeTab === 'overview' && (
        <>
          {revenueItems.length === 0 && !loading && (
            <div style={{
              padding: '16px 20px', background: BG_2, borderRadius: 8,
              marginBottom: 12, fontSize: 13, color: TEXT_3,
              borderLeft: `3px solid ${YELLOW}`,
            }}>
              💡 渠道收入数据尚未从 <code style={{ color: BRAND }}>/api/v1/finance/analytics/revenue-composition</code> 获取到，
              下方展示渠道框架。接入后将自动填充各渠道GMV数据。
            </div>
          )}
          <ChannelOverview channels={channelCards} />
        </>
      )}
      {activeTab === 'trend' && <TrendChart items={trendItems} />}
      {activeTab === 'config' && <ChannelConfigReadonly channels={channelCards} />}
    </div>
  );
}
