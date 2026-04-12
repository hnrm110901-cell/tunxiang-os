/**
 * XHSIntegrationPage — 小红书运营管理
 * 路由: /hq/growth/xhs
 * 渠道配置检测 + 笔记监控 + AI内容建议 + 数据分析
 */
import { useState, useEffect, useCallback } from 'react';
import { txFetchData } from '../../../api';

const BG_1 = '#0d1e28';
const BG_2 = '#1a2a33';
const BG_3 = '#223040';
const BRAND = '#FF6B2C';
const XHS_RED = '#FF2442';
const GREEN = '#52c41a';
const RED = '#ff4d4f';
const YELLOW = '#faad14';
const BLUE = '#1890ff';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

type TabKey = 'posts' | 'ai' | 'config';

interface ChannelConfig {
  channel: string;
  bound: boolean;
  accountName?: string;
  accountId?: string;
  status: 'active' | 'pending' | 'unbound' | 'connecting';
  boundAt?: string;
}

interface XHSPost {
  id: string;
  title: string;
  author: string;
  exposure: number;
  likes: number;
  comments: number;
  conversions: number;
  conversionRate: string;
  sentiment: '正面' | '中性' | '负面';
  publishedAt: string;
  url?: string;
}

interface XHSAnalytics {
  totalPosts: number;
  totalExposure: number;
  totalInteractions: number;
  avgConversionRate: string;
  period: string;
}

interface AIContentSuggestion {
  title: string;
  body: string;
  tags: string[];
  strategy: string;
}

function useChannelConfig() {
  const [config, setConfig] = useState<ChannelConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    txFetchData<ChannelConfig>('/api/v1/system/channel-config?channel=xhs')
      .then(data => {
        setConfig(data);
        setError(null);
      })
      .catch(() => {
        // 降级：展示"对接中"状态
        setConfig({ channel: 'xhs', bound: false, status: 'connecting' });
        setError(null);
      })
      .finally(() => setLoading(false));
  }, []);

  return { config, loading, error };
}

function useXHSPosts(enabled: boolean) {
  const [posts, setPosts] = useState<XHSPost[]>([]);
  const [analytics, setAnalytics] = useState<XHSAnalytics | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!enabled) return;
    setLoading(true);
    txFetchData<{ items: XHSPost[]; analytics: XHSAnalytics }>('/api/v1/analytics/xhs/posts')
      .then(data => {
        setPosts(data.items || []);
        setAnalytics(data.analytics || null);
      })
      .catch(() => {
        setPosts([]);
        setAnalytics(null);
      })
      .finally(() => setLoading(false));
  }, [enabled]);

  return { posts, analytics, loading };
}

export function XHSIntegrationPage() {
  const { config, loading: configLoading } = useChannelConfig();
  const [tab, setTab] = useState<TabKey>('posts');

  if (configLoading) return <LoadingScreen />;

  const isConnecting = config?.status === 'connecting';
  const isUnbound = !config?.bound && config?.status !== 'connecting';

  return (
    <div style={{ padding: 24, background: BG_1, minHeight: '100vh', color: TEXT_1, fontFamily: '-apple-system, BlinkMacSystemFont, sans-serif' }}>
      {/* Header */}
      <div style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ width: 36, height: 36, borderRadius: 8, background: XHS_RED, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 18, fontWeight: 700 }}>书</div>
          <div>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>小红书运营</h1>
            <div style={{ fontSize: 13, color: TEXT_3, marginTop: 2 }}>内容监控 · AI文案 · 数据分析</div>
          </div>
        </div>
        <ChannelStatusBadge config={config} />
      </div>

      {isConnecting && <ConnectingView />}
      {isUnbound && <UnboundView />}
      {config?.bound && (
        <>
          <AnalyticsCards config={config} />
          {/* Tabs */}
          <div style={{ display: 'flex', gap: 4, marginBottom: 20, background: BG_2, borderRadius: 8, padding: 4, width: 'fit-content' }}>
            {([
              { key: 'posts' as TabKey, label: '笔记监控' },
              { key: 'ai' as TabKey, label: 'AI内容建议' },
              { key: 'config' as TabKey, label: '账号配置' },
            ]).map(t => (
              <button key={t.key} onClick={() => setTab(t.key)}
                style={{
                  padding: '8px 20px', fontSize: 14, fontWeight: tab === t.key ? 600 : 400, cursor: 'pointer',
                  border: 'none', borderRadius: 6,
                  background: tab === t.key ? XHS_RED : 'transparent',
                  color: tab === t.key ? '#fff' : TEXT_3,
                }}>
                {t.label}
              </button>
            ))}
          </div>
          {tab === 'posts' && <PostsTab />}
          {tab === 'ai' && <AIContentTab />}
          {tab === 'config' && <ConfigTab config={config} />}
        </>
      )}
    </div>
  );
}

/* ─── 加载屏 ─── */
function LoadingScreen() {
  return (
    <div style={{ padding: 24, background: BG_1, minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ textAlign: 'center', color: TEXT_3 }}>
        <div style={{ fontSize: 32, marginBottom: 12 }}>⟳</div>
        <div style={{ fontSize: 14 }}>加载渠道配置...</div>
      </div>
    </div>
  );
}

/* ─── 渠道状态徽章 ─── */
function ChannelStatusBadge({ config }: { config: ChannelConfig | null }) {
  if (!config) return null;
  const statusMap = {
    active: { label: '已接入', color: GREEN, bg: 'rgba(82,196,26,0.15)' },
    pending: { label: '审核中', color: YELLOW, bg: 'rgba(250,173,20,0.15)' },
    unbound: { label: '未绑定', color: TEXT_4, bg: 'rgba(255,255,255,0.06)' },
    connecting: { label: '对接中', color: BLUE, bg: 'rgba(24,144,255,0.15)' },
  };
  const s = statusMap[config.status] || statusMap.unbound;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <span style={{ padding: '4px 12px', borderRadius: 20, fontSize: 12, fontWeight: 600, background: s.bg, color: s.color }}>
        {s.label}
      </span>
      {config.bound && (
        <span style={{ fontSize: 13, color: TEXT_3 }}>{config.accountName}</span>
      )}
    </div>
  );
}

/* ─── 未绑定引导页 ─── */
function UnboundView() {
  return (
    <div style={{ maxWidth: 600, margin: '40px auto', textAlign: 'center' }}>
      <div style={{ width: 80, height: 80, borderRadius: 20, background: 'rgba(255,36,66,0.12)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 40, margin: '0 auto 24px' }}>书</div>
      <h2 style={{ fontSize: 22, fontWeight: 700, margin: '0 0 8px' }}>绑定小红书商业账号</h2>
      <p style={{ fontSize: 14, color: TEXT_3, lineHeight: 1.6, margin: '0 0 32px' }}>
        绑定后可监控品牌相关笔记、分析内容互动数据、获取 AI 文案建议，助力私域增长。
      </p>
      <div style={{ background: BG_2, borderRadius: 12, padding: 24, textAlign: 'left', marginBottom: 24 }}>
        <h3 style={{ fontSize: 15, fontWeight: 600, margin: '0 0 16px', color: TEXT_2 }}>授权步骤</h3>
        {[
          { step: '01', title: '登录小红书商业平台', desc: '使用品牌账号登录 xhs.com/pro' },
          { step: '02', title: '申请 API 访问权限', desc: '在「开放平台」申请数据权限，审核约 3-5 个工作日' },
          { step: '03', title: '获取 App Key / Secret', desc: '审核通过后在开发者中心获取凭证' },
          { step: '04', title: '在屯象OS填入凭证', desc: '将 App Key 和 App Secret 填入下方配置项' },
        ].map((s) => (
          <div key={s.step} style={{ display: 'flex', gap: 16, marginBottom: 16, alignItems: 'flex-start' }}>
            <div style={{ width: 28, height: 28, borderRadius: '50%', background: 'rgba(255,36,66,0.15)', color: XHS_RED, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700, flexShrink: 0 }}>{s.step}</div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 2 }}>{s.title}</div>
              <div style={{ fontSize: 12, color: TEXT_3 }}>{s.desc}</div>
            </div>
          </div>
        ))}
      </div>
      <button style={{ background: XHS_RED, color: '#fff', border: 'none', borderRadius: 8, padding: '12px 32px', fontSize: 15, fontWeight: 600, cursor: 'pointer' }}>
        前往小红书商业平台
      </button>
    </div>
  );
}

/* ─── 对接中功能规划卡 ─── */
function ConnectingView() {
  const features = [
    { icon: '📊', title: '笔记数据监控', desc: '品牌相关笔记的曝光量、互动量、情感分析实时追踪', eta: '接入后即用' },
    { icon: '🤖', title: 'AI 文案生成', desc: '基于门店菜品和营销目标，一键生成小红书种草文案', eta: '接入后即用' },
    { icon: '📈', title: '转化率分析', desc: '从笔记曝光到到店转化全链路数据追踪', eta: '接入后即用' },
    { icon: '🎯', title: 'KOL 合作推荐', desc: '基于品牌定位推荐适合的探店达人，分析合作性价比', eta: '规划中' },
    { icon: '📅', title: '内容日历', desc: '智能规划内容发布节奏，抓住营销节点', eta: '规划中' },
    { icon: '🔔', title: '负面舆情预警', desc: '实时监控负面评价，第一时间处理危机', eta: '规划中' },
  ];

  return (
    <div>
      <div style={{ background: 'linear-gradient(135deg, rgba(255,36,66,0.1), rgba(255,107,44,0.08))', border: '1px solid rgba(255,36,66,0.2)', borderRadius: 12, padding: '16px 20px', marginBottom: 24, display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ width: 8, height: 8, borderRadius: '50%', background: BLUE, animation: 'pulse 1.5s infinite' }} />
        <div>
          <span style={{ fontSize: 14, fontWeight: 600, color: TEXT_1 }}>渠道接入中</span>
          <span style={{ fontSize: 13, color: TEXT_3, marginLeft: 8 }}>小红书商业 API 正在对接，预计 3-5 个工作日完成</span>
        </div>
      </div>
      <div style={{ marginBottom: 16, fontSize: 15, fontWeight: 600, color: TEXT_2 }}>接入后可用功能</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
        {features.map(f => (
          <div key={f.title} style={{ background: BG_2, borderRadius: 12, padding: 20 }}>
            <div style={{ fontSize: 28, marginBottom: 10 }}>{f.icon}</div>
            <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 6 }}>{f.title}</div>
            <div style={{ fontSize: 13, color: TEXT_3, lineHeight: 1.5, marginBottom: 12 }}>{f.desc}</div>
            <span style={{
              fontSize: 11, padding: '2px 8px', borderRadius: 10,
              background: f.eta === '接入后即用' ? 'rgba(82,196,26,0.12)' : 'rgba(255,255,255,0.06)',
              color: f.eta === '接入后即用' ? GREEN : TEXT_4,
            }}>{f.eta}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── 已绑定 KPI 卡片 ─── */
function AnalyticsCards({ config }: { config: ChannelConfig | null }) {
  const { analytics } = useXHSPosts(!!config?.bound);

  const kpis = analytics
    ? [
        { label: '笔记总数', value: String(analytics.totalPosts), sub: `统计周期: ${analytics.period}`, trend: 'up' as const },
        { label: '总曝光量', value: analytics.totalExposure >= 10000 ? `${(analytics.totalExposure / 10000).toFixed(1)}万` : String(analytics.totalExposure), sub: '品牌相关内容', trend: 'up' as const },
        { label: '总互动量', value: analytics.totalInteractions >= 10000 ? `${(analytics.totalInteractions / 10000).toFixed(1)}万` : String(analytics.totalInteractions), sub: '点赞+评论+收藏', trend: 'up' as const },
        { label: '平均转化率', value: analytics.avgConversionRate, sub: '笔记到到店转化', trend: 'up' as const },
      ]
    : [
        { label: '笔记总数', value: '--', sub: '加载中...', trend: 'up' as const },
        { label: '总曝光量', value: '--', sub: '加载中...', trend: 'up' as const },
        { label: '总互动量', value: '--', sub: '加载中...', trend: 'up' as const },
        { label: '平均转化率', value: '--', sub: '加载中...', trend: 'up' as const },
      ];

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
      {kpis.map(k => (
        <div key={k.label} style={{ background: BG_2, borderRadius: 8, padding: 16 }}>
          <div style={{ fontSize: 13, color: TEXT_3 }}>{k.label}</div>
          <div style={{ fontSize: 28, fontWeight: 700, marginTop: 4 }}>{k.value}</div>
          <div style={{ fontSize: 12, color: GREEN, marginTop: 4 }}>{k.sub}</div>
        </div>
      ))}
    </div>
  );
}

/* ─── 笔记监控 Tab ─── */
function PostsTab() {
  const { posts, loading } = useXHSPosts(true);
  const [filter, setFilter] = useState<string>('全部');

  const filtered = filter === '全部' ? posts : posts.filter(p => p.sentiment === filter);

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, alignItems: 'center' }}>
        <input
          placeholder="搜索笔记标题 / 作者"
          style={{ flex: 1, maxWidth: 300, padding: '7px 12px', background: BG_2, border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, color: TEXT_1, fontSize: 13, outline: 'none' }}
        />
        {['全部', '正面', '中性', '负面'].map(f => (
          <button key={f} onClick={() => setFilter(f)}
            style={{ padding: '6px 14px', background: filter === f ? 'rgba(255,36,66,0.15)' : 'transparent', color: filter === f ? XHS_RED : TEXT_3, border: filter === f ? `1px solid rgba(255,36,66,0.3)` : '1px solid transparent', borderRadius: 6, fontSize: 13, cursor: 'pointer' }}>
            {f}
          </button>
        ))}
      </div>

      {loading && (
        <div style={{ textAlign: 'center', padding: 60, color: TEXT_3 }}>加载笔记数据...</div>
      )}

      {!loading && filtered.length === 0 && (
        <div style={{ textAlign: 'center', padding: 60, background: BG_2, borderRadius: 12 }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>📝</div>
          <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 6 }}>暂无笔记数据</div>
          <div style={{ fontSize: 13, color: TEXT_3 }}>品牌相关笔记将在接入后自动采集</div>
        </div>
      )}

      {!loading && filtered.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: 16 }}>
          {filtered.map(n => (
            <div key={n.id} style={{ background: BG_2, borderRadius: 12, padding: 20 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
                <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, flex: 1, lineHeight: 1.4 }}>{n.title}</h3>
                <span style={{
                  marginLeft: 8, padding: '2px 8px', borderRadius: 10, fontSize: 11, flexShrink: 0,
                  background: n.sentiment === '正面' ? 'rgba(82,196,26,0.15)' : n.sentiment === '负面' ? 'rgba(255,77,79,0.15)' : 'rgba(255,255,255,0.06)',
                  color: n.sentiment === '正面' ? GREEN : n.sentiment === '负面' ? RED : TEXT_3,
                }}>{n.sentiment}</span>
              </div>
              <div style={{ fontSize: 13, color: TEXT_3, marginBottom: 12 }}>@{n.author} · {n.publishedAt}</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 12 }}>
                {[
                  { label: '曝光', value: n.exposure >= 10000 ? `${(n.exposure / 10000).toFixed(1)}万` : n.exposure },
                  { label: '互动', value: n.likes + n.comments },
                  { label: '转化率', value: n.conversionRate },
                ].map(m => (
                  <div key={m.label} style={{ textAlign: 'center', padding: '8px 4px', background: BG_3, borderRadius: 6 }}>
                    <div style={{ fontSize: 16, fontWeight: 700 }}>{m.value}</div>
                    <div style={{ fontSize: 11, color: TEXT_4, marginTop: 2 }}>{m.label}</div>
                  </div>
                ))}
              </div>
              <div style={{ display: 'flex', gap: 12, fontSize: 13, color: TEXT_3 }}>
                <span>♥ {n.likes}</span>
                <span>💬 {n.comments}</span>
                {n.url && <span style={{ marginLeft: 'auto', color: BLUE, cursor: 'pointer' }}>查看原文</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ─── AI 内容建议 Tab ─── */
function AIContentTab() {
  const [prompt, setPrompt] = useState('');
  const [result, setResult] = useState<AIContentSuggestion | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const generate = useCallback(async () => {
    if (!prompt.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await txFetchData<AIContentSuggestion>('/api/v1/orchestrate', {
        method: 'POST',
        body: JSON.stringify({
          agent: 'content_writer',
          channel: 'xhs',
          prompt: prompt.trim(),
        }),
      });
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'AI 生成失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  }, [prompt]);

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, alignItems: 'start' }}>
      {/* 左：输入区 */}
      <div style={{ background: BG_2, borderRadius: 12, padding: 24 }}>
        <h3 style={{ margin: '0 0 16px', fontSize: 16, fontWeight: 600 }}>AI 小红书文案生成</h3>
        <div style={{ fontSize: 13, color: TEXT_3, marginBottom: 16, lineHeight: 1.5 }}>
          描述营销目标、主推菜品或活动内容，AI 将生成适合小红书风格的种草文案。
        </div>
        <textarea
          value={prompt}
          onChange={e => setPrompt(e.target.value)}
          placeholder="例如：推广本月新品「夏日龙虾套餐」，目标是吸引25-35岁女性，重点突出性价比和海鲜新鲜度..."
          rows={6}
          style={{
            width: '100%', padding: '10px 12px', background: BG_3, border: '1px solid rgba(255,255,255,0.1)',
            borderRadius: 8, color: TEXT_1, fontSize: 13, outline: 'none', resize: 'vertical',
            boxSizing: 'border-box', lineHeight: 1.6,
          }}
        />
        <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
          <button
            onClick={generate}
            disabled={loading || !prompt.trim()}
            style={{
              flex: 1, padding: '10px 0', background: loading || !prompt.trim() ? 'rgba(255,36,66,0.3)' : XHS_RED,
              color: '#fff', border: 'none', borderRadius: 8, fontSize: 14, fontWeight: 600,
              cursor: loading || !prompt.trim() ? 'not-allowed' : 'pointer',
            }}>
            {loading ? '生成中...' : '生成文案'}
          </button>
        </div>
        {error && (
          <div style={{ marginTop: 12, padding: '10px 14px', background: 'rgba(255,77,79,0.1)', borderRadius: 8, fontSize: 13, color: RED }}>
            {error}
          </div>
        )}
        {/* 快捷模板 */}
        <div style={{ marginTop: 20, borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: 16 }}>
          <div style={{ fontSize: 12, color: TEXT_4, marginBottom: 10 }}>快捷模板</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {[
              '新品上线推广',
              '节日营销活动',
              '探店打卡引导',
              '会员专属福利',
            ].map(t => (
              <button key={t} onClick={() => setPrompt(t)}
                style={{ padding: '4px 12px', background: BG_3, color: TEXT_3, border: '1px solid rgba(255,255,255,0.08)', borderRadius: 20, fontSize: 12, cursor: 'pointer' }}>
                {t}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* 右：结果区 */}
      <div>
        {!result && !loading && (
          <div style={{ background: BG_2, borderRadius: 12, padding: 40, textAlign: 'center' }}>
            <div style={{ fontSize: 40, marginBottom: 12 }}>✨</div>
            <div style={{ fontSize: 14, color: TEXT_3 }}>填写需求后点击生成</div>
          </div>
        )}
        {loading && (
          <div style={{ background: BG_2, borderRadius: 12, padding: 40, textAlign: 'center' }}>
            <div style={{ fontSize: 14, color: TEXT_3 }}>AI 正在创作中...</div>
          </div>
        )}
        {result && !loading && (
          <div style={{ background: BG_2, borderRadius: 12, padding: 24 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>生成结果</h3>
              <button
                onClick={() => navigator.clipboard?.writeText(`${result.title}\n\n${result.body}\n\n${result.tags.join(' ')}`)}
                style={{ padding: '4px 12px', background: 'rgba(255,255,255,0.06)', color: TEXT_3, border: 'none', borderRadius: 6, fontSize: 12, cursor: 'pointer' }}>
                复制全文
              </button>
            </div>
            <div style={{ fontSize: 13, color: TEXT_4, marginBottom: 6 }}>标题</div>
            <div style={{ fontSize: 15, fontWeight: 600, color: XHS_RED, marginBottom: 16, lineHeight: 1.5 }}>{result.title}</div>
            <div style={{ fontSize: 13, color: TEXT_4, marginBottom: 6 }}>正文</div>
            <div style={{ fontSize: 14, color: TEXT_2, lineHeight: 1.8, whiteSpace: 'pre-wrap', marginBottom: 16 }}>{result.body}</div>
            <div style={{ fontSize: 13, color: TEXT_4, marginBottom: 8 }}>话题标签</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 16 }}>
              {result.tags.map(tag => (
                <span key={tag} style={{ padding: '2px 10px', background: 'rgba(255,36,66,0.1)', color: XHS_RED, borderRadius: 20, fontSize: 12 }}>{tag}</span>
              ))}
            </div>
            {result.strategy && (
              <div style={{ padding: 12, background: BG_3, borderRadius: 8, fontSize: 12, color: TEXT_3, lineHeight: 1.5 }}>
                <span style={{ color: TEXT_2, fontWeight: 600 }}>营销策略: </span>{result.strategy}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/* ─── 账号配置 Tab ─── */
function ConfigTab({ config }: { config: ChannelConfig }) {
  return (
    <div style={{ maxWidth: 560 }}>
      <div style={{ background: BG_2, borderRadius: 12, padding: 24 }}>
        <h3 style={{ margin: '0 0 20px', fontSize: 16, fontWeight: 600 }}>账号信息</h3>
        {[
          { label: '绑定账号', value: config.accountName || '--' },
          { label: '账号 ID', value: config.accountId || '--' },
          { label: '接入状态', value: config.status === 'active' ? '正常' : config.status === 'pending' ? '审核中' : '对接中' },
          { label: '绑定时间', value: config.boundAt || '--' },
        ].map(row => (
          <div key={row.label} style={{ display: 'flex', justifyContent: 'space-between', padding: '12px 0', borderBottom: '1px solid rgba(255,255,255,0.06)', fontSize: 14 }}>
            <span style={{ color: TEXT_3 }}>{row.label}</span>
            <span style={{ color: TEXT_1 }}>{row.value}</span>
          </div>
        ))}
        <div style={{ marginTop: 20 }}>
          <button style={{ padding: '8px 20px', background: 'rgba(255,77,79,0.1)', color: RED, border: `1px solid ${RED}`, borderRadius: 6, fontSize: 13, cursor: 'pointer' }}>
            解绑账号
          </button>
        </div>
      </div>
    </div>
  );
}
