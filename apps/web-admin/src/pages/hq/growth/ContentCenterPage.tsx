/**
 * ContentCenterPage — 内容资产中心
 * 路由: /hq/growth/content
 * 接入: GET /api/v1/member/content（优雅降级）
 * 文案/海报/短信/企微/小程序/节日模板 + 内容生成工作台 + 审核队列 + 效果统计
 */
import { useState, useEffect, useCallback } from 'react';
import { txFetch } from '../../../api';

// ---- 颜色常量 ----
const BG_MAIN = '#0d1e28';
const BG_1 = '#112228';
const BG_2 = '#1a2a33';
const BRAND = '#FF6B2C';
const GREEN = '#52c41a';
const RED = '#ff4d4f';
const YELLOW = '#faad14';
const BLUE = '#1890ff';
const PURPLE = '#722ed1';
const TEAL = '#13c2c2';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

// ---- 类型 ----
type ContentType = '全部' | '文案' | '海报' | '短信' | '企微' | '小程序' | '节日';
type TabKey = 'templates' | 'workbench' | 'review' | 'stats';

interface ContentTemplate {
  id: string;
  name: string;
  type: ContentType;
  scene: string;
  previewText: string;
  usageCount: number;
  conversionRate: number;
  status: '已发布' | '草稿' | '待审核';
  updatedAt: string;
}

interface ReviewItem {
  id: string;
  title: string;
  type: ContentType;
  submitter: string;
  submitTime: string;
  status: '待审核' | '已通过' | '已拒绝';
  content: string;
}

interface ContentStat {
  id: string;
  title: string;
  type: ContentType;
  sendCount: number;
  openRate: number;
  clickRate: number;
  conversionRate: number;
  revenue: number;
  date: string;
}

interface ContentListResponse {
  items: ContentTemplate[];
  total: number;
}

interface ContentReviewResponse {
  items: ReviewItem[];
  total: number;
}

interface ContentStatsResponse {
  items: ContentStat[];
  total: number;
}

interface ContentOverviewResponse {
  total_templates: number;
  monthly_generations: number;
  review_pass_rate: number;
  avg_conversion_rate: number;
  total_revenue_contribution: number;
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

// ---- 空态引导组件 ----
function EmptyStatePlaceholder({
  title,
  description,
  actionLabel,
  onAction,
  icon,
}: {
  title: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
  icon?: string;
}) {
  return (
    <div style={{
      padding: '56px 24px', textAlign: 'center',
      background: BG_1, borderRadius: 12,
      border: `1px dashed ${BG_2}`,
    }}>
      {icon && (
        <div style={{
          width: 72, height: 72, borderRadius: '50%',
          background: BRAND + '15', margin: '0 auto 20px',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 32,
        }}>{icon}</div>
      )}
      <div style={{ fontSize: 16, fontWeight: 700, color: TEXT_2, marginBottom: 10 }}>{title}</div>
      <div style={{ fontSize: 13, color: TEXT_4, lineHeight: 1.8, maxWidth: 360, margin: '0 auto 20px' }}>{description}</div>
      {actionLabel && onAction && (
        <button onClick={onAction} style={{
          padding: '9px 24px', borderRadius: 8, border: 'none',
          background: BRAND, color: '#fff', fontSize: 13, fontWeight: 600,
          cursor: 'pointer',
        }}>{actionLabel}</button>
      )}
    </div>
  );
}

// ---- 待接入平台占位组件 ----
function ContentPlatformComingSoon() {
  const channels = [
    { icon: '📱', label: '企业微信', desc: '私域精准触达', color: GREEN },
    { icon: '✉️', label: '短信平台', desc: '批量营销推送', color: BLUE },
    { icon: '🖼️', label: '海报生成', desc: 'AI自动排版', color: PURPLE },
    { icon: '📝', label: '文案创作', desc: '品牌调性一致', color: BRAND },
    { icon: '🎉', label: '节日模板', desc: '节日营销素材库', color: YELLOW },
    { icon: '📲', label: '小程序弹窗', desc: '会员权益通知', color: TEAL },
  ];

  return (
    <div style={{ background: BG_1, borderRadius: 12, padding: 28, border: `1px solid ${BG_2}` }}>
      {/* 头部 */}
      <div style={{ textAlign: 'center', marginBottom: 32 }}>
        <div style={{
          display: 'inline-flex', alignItems: 'center', gap: 8,
          padding: '6px 16px', borderRadius: 20,
          background: YELLOW + '15', border: `1px solid ${YELLOW}33`,
          marginBottom: 20,
        }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: YELLOW, display: 'inline-block' }} />
          <span style={{ fontSize: 12, color: YELLOW, fontWeight: 600 }}>待接入内容平台</span>
        </div>
        <h3 style={{ margin: '0 0 10px', fontSize: 22, fontWeight: 800, color: TEXT_1 }}>
          内容营销中台建设中
        </h3>
        <p style={{ margin: 0, fontSize: 14, color: TEXT_3, lineHeight: 1.8, maxWidth: 460, marginLeft: 'auto', marginRight: 'auto' }}>
          屯象OS内容中台将统一管理企微、短信、海报、文案、小程序等全渠道营销物料，
          目前正在对接第三方内容平台，即将上线。
        </p>
      </div>

      {/* 渠道卡片网格 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 28 }}>
        {channels.map((ch, i) => (
          <div key={i} style={{
            background: BG_2, borderRadius: 10, padding: '16px 18px',
            border: `1px solid ${ch.color}22`,
            display: 'flex', alignItems: 'center', gap: 14,
          }}>
            <div style={{
              width: 44, height: 44, borderRadius: 10,
              background: ch.color + '18',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 20, flexShrink: 0,
            }}>{ch.icon}</div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 700, color: TEXT_1, marginBottom: 3 }}>{ch.label}</div>
              <div style={{ fontSize: 11, color: TEXT_4 }}>{ch.desc}</div>
            </div>
            <div style={{ marginLeft: 'auto' }}>
              <span style={{
                fontSize: 9, padding: '2px 7px', borderRadius: 8,
                background: YELLOW + '22', color: YELLOW, fontWeight: 600,
              }}>开发中</span>
            </div>
          </div>
        ))}
      </div>

      {/* 时间线 */}
      <div style={{
        background: BG_2, borderRadius: 10, padding: '18px 22px',
        border: `1px solid ${BG_2}`,
      }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: TEXT_2, marginBottom: 14 }}>上线计划</div>
        <div style={{ display: 'flex', gap: 0 }}>
          {[
            { label: '基础API对接', date: 'Q2 2026', done: false },
            { label: '模板库导入', date: 'Q3 2026', done: false },
            { label: '渠道发送', date: 'Q3 2026', done: false },
            { label: '效果统计', date: 'Q4 2026', done: false },
          ].map((step, i) => (
            <div key={i} style={{ flex: 1, position: 'relative' }}>
              <div style={{
                width: 12, height: 12, borderRadius: '50%',
                background: step.done ? GREEN : BG_1,
                border: `2px solid ${step.done ? GREEN : TEXT_4}`,
                marginBottom: 8, position: 'relative', zIndex: 1,
              }} />
              {i < 3 && (
                <div style={{
                  position: 'absolute', top: 5, left: 12,
                  width: 'calc(100% - 12px)', height: 2,
                  background: step.done ? GREEN : TEXT_4 + '44',
                }} />
              )}
              <div style={{ fontSize: 11, color: step.done ? GREEN : TEXT_3, fontWeight: 600 }}>{step.label}</div>
              <div style={{ fontSize: 10, color: TEXT_4, marginTop: 2 }}>{step.date}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ---- Tab 栏 ----
function TabBar({
  activeTab,
  setActiveTab,
  pendingReviews,
}: {
  activeTab: TabKey;
  setActiveTab: (t: TabKey) => void;
  pendingReviews: number;
}) {
  const tabs: { key: TabKey; label: string; badge?: number }[] = [
    { key: 'templates', label: '模板库' },
    { key: 'workbench', label: '内容生成工作台' },
    { key: 'review', label: '审核队列', badge: pendingReviews },
    { key: 'stats', label: '效果统计' },
  ];
  return (
    <div style={{ display: 'flex', gap: 4, marginBottom: 16 }}>
      {tabs.map(t => (
        <button key={t.key} onClick={() => setActiveTab(t.key)} style={{
          padding: '8px 18px', borderRadius: 8, border: 'none', cursor: 'pointer',
          background: activeTab === t.key ? BRAND : BG_1,
          color: activeTab === t.key ? '#fff' : TEXT_3,
          fontSize: 13, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6,
        }}>
          {t.label}
          {t.badge != null && t.badge > 0 && (
            <span style={{
              fontSize: 10, padding: '1px 6px', borderRadius: 10,
              background: activeTab === t.key ? '#ffffff33' : RED + '22',
              color: activeTab === t.key ? '#fff' : RED, fontWeight: 700,
            }}>{t.badge}</span>
          )}
        </button>
      ))}
    </div>
  );
}

// ---- KPI 概览 ----
function KpiCards({
  data,
  loading,
  error,
  onRetry,
}: {
  data: ContentOverviewResponse | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  if (error) {
    return (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12, marginBottom: 16 }}>
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} style={{
            background: BG_1, borderRadius: 10, padding: '14px 16px',
            border: `1px solid ${RED}33`,
          }}>
            <div style={{ fontSize: 11, color: RED }}>加载失败</div>
            {i === 0 && (
              <button onClick={onRetry} style={{
                marginTop: 8, padding: '3px 10px', borderRadius: 5,
                border: `1px solid ${RED}`, background: 'transparent',
                color: RED, fontSize: 10, cursor: 'pointer',
              }}>重试</button>
            )}
          </div>
        ))}
      </div>
    );
  }

  const kpis = [
    {
      label: '模板总数',
      value: loading ? null : (data?.total_templates ?? 0).toLocaleString(),
      color: TEXT_1,
    },
    {
      label: '本月生成次数',
      value: loading ? null : (data?.monthly_generations ?? 0).toLocaleString(),
      color: TEXT_1,
    },
    {
      label: '审核通过率',
      value: loading ? null : `${(data?.review_pass_rate ?? 0).toFixed(1)}%`,
      color: GREEN,
    },
    {
      label: '平均转化率',
      value: loading ? null : `${(data?.avg_conversion_rate ?? 0).toFixed(1)}%`,
      color: BRAND,
    },
    {
      label: '内容贡献营收',
      value: loading ? null : `¥${((data?.total_revenue_contribution ?? 0) / 10000).toFixed(1)}万`,
      color: GREEN,
    },
  ];

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12, marginBottom: 16 }}>
      {kpis.map((kpi, i) => (
        <div key={i} style={{
          background: BG_1, borderRadius: 10, padding: '14px 16px',
          border: `1px solid ${BG_2}`,
        }}>
          <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 6 }}>{kpi.label}</div>
          {loading ? (
            <Skeleton height={32} radius={4} />
          ) : (
            <div style={{ fontSize: 24, fontWeight: 700, color: kpi.color }}>{kpi.value}</div>
          )}
        </div>
      ))}
    </div>
  );
}

// ---- 模板网格 ----
function TemplateGrid({
  templates,
  typeFilter,
  loading,
  error,
  onRetry,
}: {
  templates: ContentTemplate[];
  typeFilter: ContentType;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  if (error) return <ErrorBanner message={`加载模板失败：${error}`} onRetry={onRetry} />;

  const filtered = typeFilter === '全部' ? templates : templates.filter(t => t.type === typeFilter);
  const statusColors: Record<string, string> = { '已发布': GREEN, '草稿': TEXT_4, '待审核': YELLOW };

  if (loading) {
    return (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 12 }}>
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} style={{
            background: BG_1, borderRadius: 10, padding: 16, border: `1px solid ${BG_2}`,
          }}>
            <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
              <Skeleton width={48} height={18} /><Skeleton width={36} height={18} />
            </div>
            <Skeleton height={18} />
            <div style={{ height: 8 }} />
            <Skeleton height={48} radius={6} />
            <div style={{ height: 10 }} />
            <Skeleton height={14} width="70%" />
          </div>
        ))}
      </div>
    );
  }

  if (filtered.length === 0) {
    return (
      <ContentPlatformComingSoon />
    );
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 12 }}>
      {filtered.map(t => (
        <div key={t.id} style={{
          background: BG_1, borderRadius: 10, padding: 16,
          border: `1px solid ${BG_2}`, cursor: 'pointer',
          transition: 'border-color 0.2s',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <span style={{
                fontSize: 10, padding: '1px 6px', borderRadius: 4,
                background: BRAND + '22', color: BRAND, fontWeight: 600,
              }}>{t.type}</span>
              <span style={{
                fontSize: 10, padding: '1px 6px', borderRadius: 4,
                background: BLUE + '22', color: BLUE, fontWeight: 600,
              }}>{t.scene}</span>
            </div>
            <span style={{
              fontSize: 10, padding: '1px 6px', borderRadius: 4,
              background: (statusColors[t.status] || TEXT_4) + '22',
              color: statusColors[t.status] || TEXT_4, fontWeight: 600,
            }}>{t.status}</span>
          </div>
          <div style={{ fontSize: 14, fontWeight: 600, color: TEXT_1, marginBottom: 8 }}>{t.name}</div>
          <div style={{
            fontSize: 12, color: TEXT_3, lineHeight: 1.6, marginBottom: 10,
            padding: '8px 10px', background: BG_2, borderRadius: 6,
            borderLeft: `3px solid ${BRAND}44`,
          }}>{t.previewText}</div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: TEXT_4 }}>
            <span>使用 {t.usageCount.toLocaleString()} 次</span>
            <span>转化率 {t.conversionRate > 0 ? `${t.conversionRate}%` : '-'}</span>
            <span>{t.updatedAt}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

// ---- 内容生成工作台 ----
function GenerationWorkbench() {
  const [contentType, setContentType] = useState<string>('短信');
  const [brand, setBrand] = useState<string>('尝在一起');
  const [segment, setSegment] = useState<string>('30天未复购');
  const [scene, setScene] = useState<string>('复购召回');
  const [tone, setTone] = useState<string>('温暖亲切');
  const [generating, setGenerating] = useState(false);
  const [results, setResults] = useState<string[]>([]);
  const [genError, setGenError] = useState<string | null>(null);

  const selectStyle: React.CSSProperties = {
    background: BG_2, border: `1px solid ${BG_2}33`, borderRadius: 6,
    color: TEXT_2, padding: '8px 12px', fontSize: 13, outline: 'none',
    cursor: 'pointer', width: '100%',
  };

  async function handleGenerate() {
    setGenerating(true);
    setGenError(null);
    setResults([]);
    try {
      const resp = await txFetch<{ items: string[] }>('/api/v1/member/content/generate', {
        method: 'POST',
        body: JSON.stringify({ contentType, brand, segment, scene, tone }),
      });
      setResults(resp.items ?? []);
    } catch {
      // 优雅降级：后端未接入时显示占位提示
      setGenError('内容生成服务暂未接入，将在 Q2 2026 上线');
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div style={{ display: 'flex', gap: 16 }}>
      {/* 左侧配置区 */}
      <div style={{
        width: 320, background: BG_1, borderRadius: 10, padding: 20,
        border: `1px solid ${BG_2}`, flexShrink: 0,
      }}>
        <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>生成配置</h3>

        {[
          { label: '内容类型', value: contentType, onChange: setContentType, options: ['文案', '海报', '短信', '企微', '小程序', '节日'] },
          { label: '品牌', value: brand, onChange: setBrand, options: ['尝在一起', '最黔线', '尚宫厨'] },
          { label: '目标人群', value: segment, onChange: setSegment, options: ['30天未复购', '新客首单', '沉睡客户', '高频复购', '生日客户', '全部会员'] },
          { label: '营销场景', value: scene, onChange: setScene, options: ['复购召回', '新品推广', '节日营销', '低峰引流', '储值推广', '裂变拉新'] },
          { label: '语气风格', value: tone, onChange: setTone, options: ['温暖亲切', '活泼俏皮', '简洁商务', '文艺情感'] },
        ].map(({ label, value, onChange, options }) => (
          <div key={label} style={{ marginBottom: 14 }}>
            <label style={{ fontSize: 12, color: TEXT_3, marginBottom: 6, display: 'block' }}>{label}</label>
            <select value={value} onChange={e => onChange(e.target.value)} style={selectStyle}>
              {options.map(o => <option key={o}>{o}</option>)}
            </select>
          </div>
        ))}

        <button
          onClick={handleGenerate}
          disabled={generating}
          style={{
            width: '100%', padding: '10px 0', borderRadius: 8, border: 'none',
            background: generating ? TEXT_4 : BRAND, color: '#fff',
            fontSize: 14, fontWeight: 700,
            cursor: generating ? 'not-allowed' : 'pointer', marginTop: 8,
          }}
        >
          {generating ? '生成中...' : 'AI 生成内容'}
        </button>
      </div>

      {/* 右侧结果区 */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {genError && <ErrorBanner message={genError} />}

        {!generating && results.length === 0 && !genError && (
          <div style={{
            background: BG_1, borderRadius: 10, padding: 40,
            border: `1px solid ${BG_2}`, textAlign: 'center',
          }}>
            <div style={{
              width: 64, height: 64, borderRadius: '50%',
              background: PURPLE + '15', margin: '0 auto 16px',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 28,
            }}>AI</div>
            <div style={{ fontSize: 15, color: TEXT_3, marginBottom: 8 }}>配置参数后点击「AI 生成内容」</div>
            <div style={{ fontSize: 12, color: TEXT_4 }}>AI 将根据品牌调性、目标人群和营销场景自动生成多个方案</div>
          </div>
        )}

        {generating && (
          <div style={{
            background: BG_1, borderRadius: 10, padding: 24,
            border: `1px solid ${BG_2}`,
          }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} style={{ padding: 16, background: BG_2, borderRadius: 8 }}>
                  <Skeleton height={14} width="30%" />
                  <div style={{ marginTop: 8 }}>
                    <Skeleton height={14} />
                    <div style={{ height: 4 }} />
                    <Skeleton height={14} width="80%" />
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {results.length > 0 && (
          <div style={{
            background: BG_1, borderRadius: 10, padding: 16,
            border: `1px solid ${BG_2}`,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
              <span style={{ fontSize: 15, fontWeight: 700, color: TEXT_1 }}>生成结果</span>
              <span style={{
                fontSize: 10, padding: '2px 8px', borderRadius: 10,
                background: PURPLE + '22', color: PURPLE, fontWeight: 600,
              }}>AI</span>
              <span style={{ fontSize: 11, color: TEXT_4 }}>
                品牌: {brand} | 人群: {segment} | 类型: {contentType}
              </span>
            </div>
            {results.map((text, i) => (
              <div key={i} style={{
                padding: '14px 16px', background: BG_2, borderRadius: 8,
                marginBottom: 10, borderLeft: `3px solid ${i === 0 ? GREEN : BG_2}`,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                  <span style={{ fontSize: 12, color: TEXT_2, fontWeight: 600 }}>方案 {i + 1}</span>
                  {i === 0 && <span style={{ fontSize: 10, color: GREEN, fontWeight: 600 }}>推荐</span>}
                </div>
                <div style={{ fontSize: 13, color: TEXT_1, lineHeight: 1.7, marginBottom: 10 }}>{text}</div>
                <div style={{ display: 'flex', gap: 8 }}>
                  {['采用', '编辑', '提交审核'].map(action => (
                    <button key={action} style={{
                      padding: '4px 12px', borderRadius: 6, border: 'none',
                      background: action === '采用' ? BRAND + '22' : BG_1,
                      color: action === '采用' ? BRAND : TEXT_3,
                      fontSize: 11, fontWeight: 600, cursor: 'pointer',
                    }}>{action}</button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ---- 审核队列 ----
function ReviewQueue({
  reviews,
  loading,
  error,
  onRetry,
  onApprove,
  onReject,
}: {
  reviews: ReviewItem[];
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
}) {
  const [filter, setFilter] = useState<string>('全部');

  if (error) return <ErrorBanner message={`加载审核队列失败：${error}`} onRetry={onRetry} />;

  const statusColors: Record<string, string> = { '待审核': YELLOW, '已通过': GREEN, '已拒绝': RED };
  const filtered = filter === '全部' ? reviews : reviews.filter(r => r.status === filter);

  if (loading) {
    return (
      <div style={{ background: BG_1, borderRadius: 10, padding: 16, border: `1px solid ${BG_2}` }}>
        <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
          <Skeleton width={120} height={22} /><Skeleton width={60} height={22} /><Skeleton width={60} height={22} />
        </div>
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} style={{ padding: 14, background: BG_2, borderRadius: 8, marginBottom: 10 }}>
            <Skeleton height={16} width="60%" /><div style={{ height: 6 }} /><Skeleton height={12} />
          </div>
        ))}
      </div>
    );
  }

  if (reviews.length === 0) {
    return (
      <EmptyStatePlaceholder
        icon="✅"
        title="暂无审核内容"
        description="当内容团队提交审核申请后，将在此处显示待审内容。"
      />
    );
  }

  return (
    <div style={{ background: BG_1, borderRadius: 10, padding: 16, border: `1px solid ${BG_2}` }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: TEXT_1 }}>内容审核队列</h3>
        {['全部', '待审核', '已通过', '已拒绝'].map(s => (
          <button key={s} onClick={() => setFilter(s)} style={{
            padding: '3px 10px', borderRadius: 6, border: 'none', cursor: 'pointer',
            background: filter === s ? BRAND : BG_2, color: filter === s ? '#fff' : TEXT_3,
            fontSize: 11, fontWeight: 600,
          }}>{s}</button>
        ))}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {filtered.map(r => (
          <div key={r.id} style={{
            padding: '14px 16px', background: BG_2, borderRadius: 8,
            borderLeft: `3px solid ${statusColors[r.status] || TEXT_4}`,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: TEXT_1 }}>{r.title}</span>
                <span style={{
                  fontSize: 10, padding: '1px 6px', borderRadius: 4,
                  background: BRAND + '22', color: BRAND, fontWeight: 600,
                }}>{r.type}</span>
              </div>
              <span style={{
                fontSize: 10, padding: '1px 6px', borderRadius: 4,
                background: (statusColors[r.status] || TEXT_4) + '22',
                color: statusColors[r.status] || TEXT_4, fontWeight: 600,
              }}>{r.status}</span>
            </div>
            <div style={{ fontSize: 12, color: TEXT_3, lineHeight: 1.6, marginBottom: 8 }}>{r.content}</div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 11, color: TEXT_4 }}>提交人: {r.submitter} | {r.submitTime}</span>
              {r.status === '待审核' && (
                <div style={{ display: 'flex', gap: 6 }}>
                  <button onClick={() => onApprove(r.id)} style={{
                    padding: '4px 14px', borderRadius: 6, border: 'none',
                    background: GREEN + '22', color: GREEN, fontSize: 11, fontWeight: 600, cursor: 'pointer',
                  }}>通过</button>
                  <button onClick={() => onReject(r.id)} style={{
                    padding: '4px 14px', borderRadius: 6, border: 'none',
                    background: RED + '22', color: RED, fontSize: 11, fontWeight: 600, cursor: 'pointer',
                  }}>拒绝</button>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---- 效果统计 ----
function StatsSection({
  stats,
  loading,
  error,
  onRetry,
}: {
  stats: ContentStat[];
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  if (error) return <ErrorBanner message={`加载统计数据失败：${error}`} onRetry={onRetry} />;

  if (loading) {
    return (
      <div style={{ background: BG_1, borderRadius: 10, padding: 16, border: `1px solid ${BG_2}` }}>
        <Skeleton height={20} width={160} />
        <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
          {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} height={40} />)}
        </div>
      </div>
    );
  }

  if (stats.length === 0) {
    return (
      <EmptyStatePlaceholder
        icon="📊"
        title="暂无效果统计数据"
        description="内容平台接入后，将自动统计发送量、打开率、点击率、转化率和贡献营收。"
      />
    );
  }

  // 渠道分布统计
  const typeDist = stats.reduce((acc, s) => {
    acc[s.type] = (acc[s.type] || 0) + s.sendCount;
    return acc;
  }, {} as Record<string, number>);
  const totalSend = Object.values(typeDist).reduce((a, b) => a + b, 0);

  const typeColors: Record<string, string> = {
    '短信': BLUE, '企微': GREEN, '海报': PURPLE, '文案': BRAND, '小程序': TEAL, '节日': YELLOW,
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* 渠道分布 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* 内容类型分布 */}
        <div style={{ background: BG_1, borderRadius: 10, padding: 16, border: `1px solid ${BG_2}` }}>
          <h3 style={{ margin: '0 0 14px', fontSize: 14, fontWeight: 700, color: TEXT_1 }}>内容类型分布</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {Object.entries(typeDist).sort((a, b) => b[1] - a[1]).map(([type, count]) => (
              <div key={type}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 4 }}>
                  <span style={{ color: TEXT_2 }}>{type}</span>
                  <span style={{ color: typeColors[type] || TEXT_3, fontWeight: 600 }}>
                    {count.toLocaleString()} ({totalSend > 0 ? ((count / totalSend) * 100).toFixed(1) : 0}%)
                  </span>
                </div>
                <div style={{ height: 6, borderRadius: 3, background: BG_2, overflow: 'hidden' }}>
                  <div style={{
                    height: '100%', borderRadius: 3,
                    width: `${totalSend > 0 ? (count / totalSend) * 100 : 0}%`,
                    background: typeColors[type] || TEXT_4,
                    transition: 'width 0.6s ease',
                  }} />
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* 汇总指标 */}
        <div style={{ background: BG_1, borderRadius: 10, padding: 16, border: `1px solid ${BG_2}` }}>
          <h3 style={{ margin: '0 0 14px', fontSize: 14, fontWeight: 700, color: TEXT_1 }}>汇总指标</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {[
              { label: '总发送量', value: stats.reduce((a, s) => a + s.sendCount, 0).toLocaleString(), color: TEXT_1 },
              {
                label: '平均转化率',
                value: `${(stats.reduce((a, s) => a + s.conversionRate, 0) / stats.length).toFixed(1)}%`,
                color: BRAND,
              },
              {
                label: '总营收贡献',
                value: `¥${(stats.reduce((a, s) => a + s.revenue, 0) / 10000).toFixed(1)}万`,
                color: GREEN,
              },
              {
                label: '最高转化率',
                value: `${Math.max(...stats.map(s => s.conversionRate)).toFixed(1)}%`,
                color: YELLOW,
              },
            ].map(({ label, value, color }) => (
              <div key={label} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '8px 12px', background: BG_2, borderRadius: 6,
              }}>
                <span style={{ fontSize: 12, color: TEXT_3 }}>{label}</span>
                <span style={{ fontSize: 16, fontWeight: 700, color }}>{value}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 明细表 */}
      <div style={{ background: BG_1, borderRadius: 10, padding: 16, border: `1px solid ${BG_2}` }}>
        <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>内容效果明细</h3>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${BG_2}` }}>
                {['内容标题', '类型', '发送量', '打开率', '点击率', '转化率', '贡献营收', '日期'].map(h => (
                  <th key={h} style={{
                    textAlign: 'left', padding: '8px 10px',
                    color: TEXT_4, fontWeight: 600, fontSize: 11,
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {stats.map(s => (
                <tr key={s.id} style={{ borderBottom: `1px solid ${BG_2}` }}>
                  <td style={{ padding: '10px', color: TEXT_1, fontWeight: 500 }}>{s.title}</td>
                  <td style={{ padding: '10px' }}>
                    <span style={{
                      fontSize: 10, padding: '1px 6px', borderRadius: 4,
                      background: (typeColors[s.type] || TEXT_4) + '22',
                      color: typeColors[s.type] || TEXT_4,
                    }}>{s.type}</span>
                  </td>
                  <td style={{ padding: '10px', color: TEXT_2 }}>{s.sendCount.toLocaleString()}</td>
                  <td style={{ padding: '10px', color: s.openRate > 70 ? GREEN : TEXT_2 }}>
                    {s.openRate > 0 ? `${s.openRate}%` : '-'}
                  </td>
                  <td style={{ padding: '10px', color: s.clickRate > 25 ? GREEN : TEXT_2 }}>{s.clickRate}%</td>
                  <td style={{
                    padding: '10px', fontWeight: 600,
                    color: s.conversionRate > 15 ? GREEN : s.conversionRate > 8 ? YELLOW : TEXT_3,
                  }}>{s.conversionRate}%</td>
                  <td style={{ padding: '10px', color: GREEN, fontWeight: 600 }}>
                    ¥{(s.revenue / 10000).toFixed(1)}万
                  </td>
                  <td style={{ padding: '10px', color: TEXT_4 }}>{s.date}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ---- 主页面 ----

export function ContentCenterPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('templates');
  const [typeFilter, setTypeFilter] = useState<ContentType>('全部');

  // 概览数据
  const [overview, setOverview] = useState<ContentOverviewResponse | null>(null);
  const [loadingOverview, setLoadingOverview] = useState(false);
  const [errorOverview, setErrorOverview] = useState<string | null>(null);

  // 模板列表
  const [templates, setTemplates] = useState<ContentTemplate[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [errorTemplates, setErrorTemplates] = useState<string | null>(null);

  // 审核队列
  const [reviews, setReviews] = useState<ReviewItem[]>([]);
  const [loadingReviews, setLoadingReviews] = useState(false);
  const [errorReviews, setErrorReviews] = useState<string | null>(null);

  // 效果统计
  const [stats, setStats] = useState<ContentStat[]>([]);
  const [loadingStats, setLoadingStats] = useState(false);
  const [errorStats, setErrorStats] = useState<string | null>(null);

  // 加载概览
  const loadOverview = useCallback(async () => {
    setLoadingOverview(true);
    setErrorOverview(null);
    try {
      const data = await txFetch<ContentOverviewResponse>('/api/v1/member/content/overview');
      setOverview(data);
    } catch {
      // 优雅降级：显示空状态而非报错
      setOverview(null);
      setErrorOverview(null); // 静默失败，不显示错误
    } finally {
      setLoadingOverview(false);
    }
  }, []);

  // 加载模板列表
  const loadTemplates = useCallback(async () => {
    setLoadingTemplates(true);
    setErrorTemplates(null);
    try {
      const resp = await txFetch<ContentListResponse>('/api/v1/member/content?page=1&size=50');
      setTemplates(resp.items ?? []);
    } catch {
      // 优雅降级：显示空态引导页
      setTemplates([]);
      setErrorTemplates(null);
    } finally {
      setLoadingTemplates(false);
    }
  }, []);

  // 加载审核队列
  const loadReviews = useCallback(async () => {
    setLoadingReviews(true);
    setErrorReviews(null);
    try {
      const resp = await txFetch<ContentReviewResponse>('/api/v1/member/content/reviews?page=1&size=50');
      setReviews(resp.items ?? []);
    } catch {
      setReviews([]);
      setErrorReviews(null);
    } finally {
      setLoadingReviews(false);
    }
  }, []);

  // 加载效果统计
  const loadStats = useCallback(async () => {
    setLoadingStats(true);
    setErrorStats(null);
    try {
      const resp = await txFetch<ContentStatsResponse>('/api/v1/member/content/stats?days=30');
      setStats(resp.items ?? []);
    } catch {
      setStats([]);
      setErrorStats(null);
    } finally {
      setLoadingStats(false);
    }
  }, []);

  // 审核操作
  async function handleApprove(id: string) {
    try {
      await txFetch(`/api/v1/member/content/reviews/${id}/approve`, { method: 'POST' });
      setReviews(prev => prev.map(r => r.id === id ? { ...r, status: '已通过' } : r));
    } catch {
      // 静默失败，不中断操作
    }
  }

  async function handleReject(id: string) {
    try {
      await txFetch(`/api/v1/member/content/reviews/${id}/reject`, { method: 'POST' });
      setReviews(prev => prev.map(r => r.id === id ? { ...r, status: '已拒绝' } : r));
    } catch {
      // 静默失败
    }
  }

  // 初始加载
  useEffect(() => {
    loadOverview();
    loadTemplates();
  }, [loadOverview, loadTemplates]);

  useEffect(() => {
    if (activeTab === 'review') loadReviews();
  }, [activeTab, loadReviews]);

  useEffect(() => {
    if (activeTab === 'stats') loadStats();
  }, [activeTab, loadStats]);

  const typeOptions: ContentType[] = ['全部', '文案', '海报', '短信', '企微', '小程序', '节日'];
  const pendingReviewCount = reviews.filter(r => r.status === '待审核').length;

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto', background: BG_MAIN, minHeight: '100%' }}>
      {/* shimmer 动画样式注入 */}
      <style>{`
        @keyframes shimmer {
          0% { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
      `}</style>

      <h2 style={{ margin: '0 0 16px', fontSize: 22, fontWeight: 700, color: TEXT_1 }}>内容资产中心</h2>

      {/* KPI 概览卡片 */}
      <KpiCards
        data={overview}
        loading={loadingOverview}
        error={errorOverview}
        onRetry={loadOverview}
      />

      {/* Tab 栏 */}
      <TabBar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        pendingReviews={pendingReviewCount}
      />

      {/* 类型过滤（模板库 + 统计可用） */}
      {(activeTab === 'templates' || activeTab === 'stats') && (
        <div style={{ display: 'flex', gap: 4, marginBottom: 14 }}>
          {typeOptions.map(t => (
            <button key={t} onClick={() => setTypeFilter(t)} style={{
              padding: '4px 12px', borderRadius: 6, border: 'none', cursor: 'pointer',
              background: typeFilter === t ? BLUE : BG_2,
              color: typeFilter === t ? '#fff' : TEXT_3,
              fontSize: 11, fontWeight: 600,
            }}>{t}</button>
          ))}
        </div>
      )}

      {/* Tab 内容 */}
      {activeTab === 'templates' && (
        <TemplateGrid
          templates={templates}
          typeFilter={typeFilter}
          loading={loadingTemplates}
          error={errorTemplates}
          onRetry={loadTemplates}
        />
      )}

      {activeTab === 'workbench' && <GenerationWorkbench />}

      {activeTab === 'review' && (
        <ReviewQueue
          reviews={reviews}
          loading={loadingReviews}
          error={errorReviews}
          onRetry={loadReviews}
          onApprove={handleApprove}
          onReject={handleReject}
        />
      )}

      {activeTab === 'stats' && (
        <StatsSection
          stats={stats}
          loading={loadingStats}
          error={errorStats}
          onRetry={loadStats}
        />
      )}
    </div>
  );
}
