/**
 * TrendReportPage — 趋势报告中心
 * 路由: /hq/market-intel/reports
 * 报告列表（接真实 /api/v1/reports）+ 报告详情预览 + 降级友好
 */
import { useState, useEffect } from 'react';
import { txFetch } from '../../../api';

// ---- 颜色常量 ----
const BG   = '#0d1e28';
const BG_1 = '#1a2a33';
const BG_2 = '#243442';
const BRAND  = '#ff6b2c';
const GREEN  = '#52c41a';
const RED    = '#ff4d4f';
const YELLOW = '#faad14';
const BLUE   = '#1890ff';
const CYAN   = '#13c2c2';
const PURPLE = '#722ed1';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

// ---- 类型 ----
type TabKey = 'list' | 'preview';
type ReportTypeFilter = '全部' | '竞对周报' | '需求周报' | '新品周报' | '原料周报' | '商圈周报' | '月报';

interface ReportItem {
  id: string;
  title: string;
  type: string;
  date: string;
  status: '已发布' | '生成中' | '待审核' | '草稿';
  summary: string;
  keyFindings: string[];
  readCount: number;
  pageCount: number;
}

interface ApiReportRow {
  report_id: string;
  name: string;
  category: string;
  description?: string;
  is_active: boolean;
}

// ---- API ----
async function fetchTrendReports(): Promise<ReportItem[]> {
  try {
    const data = await txFetch<{ items: ApiReportRow[]; total: number }>(
      '/api/v1/reports?category=operation'
    );
    if (data?.items?.length) {
      return data.items.map((r) => ({
        id: r.report_id,
        title: r.name,
        type: mapCategoryToType(r.category),
        date: new Date().toISOString().slice(0, 10),
        status: r.is_active ? '已发布' : '草稿',
        summary: r.description || '报告摘要生成中...',
        keyFindings: [],
        readCount: 0,
        pageCount: 0,
      }));
    }
    return [];
  } catch {
    return [];
  }
}

function mapCategoryToType(category: string): string {
  const map: Record<string, string> = {
    revenue: '月报', dish: '需求周报', audit: '竞对周报',
    margin: '原料周报', operation: '商圈周报',
  };
  return map[category] || '竞对周报';
}

// ---- 子组件 ----

function KPICard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '14px 16px',
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 700, color }}>{value}</div>
    </div>
  );
}

const TYPE_COLORS: Record<string, string> = {
  '竞对周报': RED, '需求周报': BLUE, '新品周报': GREEN,
  '原料周报': BRAND, '商圈周报': PURPLE, '月报': CYAN,
};
const STATUS_COLORS: Record<string, string> = {
  '已发布': GREEN, '生成中': BLUE, '待审核': YELLOW, '草稿': TEXT_4,
};

function ReportCard({ report, onPreview }: { report: ReportItem; onPreview: (r: ReportItem) => void }) {
  const tc = TYPE_COLORS[report.type] || TEXT_4;
  const sc = STATUS_COLORS[report.status] || TEXT_4;
  return (
    <div
      style={{
        background: BG_1, borderRadius: 10, padding: 16,
        border: `1px solid ${BG_2}`, cursor: 'pointer',
        transition: 'border-color .2s',
      }}
      onClick={() => onPreview(report)}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{
            fontSize: 10, padding: '2px 8px', borderRadius: 4,
            background: tc + '22', color: tc, fontWeight: 600,
          }}>{report.type}</span>
          <span style={{ fontSize: 15, fontWeight: 700, color: TEXT_1 }}>{report.title}</span>
        </div>
        <span style={{
          fontSize: 10, padding: '2px 8px', borderRadius: 4,
          background: sc + '22', color: sc, fontWeight: 600, flexShrink: 0,
        }}>{report.status}</span>
      </div>
      {report.summary && (
        <div style={{ fontSize: 12, color: TEXT_3, lineHeight: 1.6, marginBottom: 10 }}>{report.summary}</div>
      )}
      {report.keyFindings.length > 0 && (
        <div style={{ marginBottom: 10 }}>
          {report.keyFindings.map((f, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 6, fontSize: 11, color: TEXT_2, lineHeight: 1.6, marginBottom: 2 }}>
              <span style={{ color: BRAND, flexShrink: 0 }}>&bull;</span>
              <span>{f}</span>
            </div>
          ))}
        </div>
      )}
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: TEXT_4 }}>
        <span>{report.date}</span>
        <div style={{ display: 'flex', gap: 12 }}>
          {report.readCount > 0 && <span>阅读 {report.readCount}</span>}
          {report.pageCount > 0 && <span>{report.pageCount} 页</span>}
        </div>
      </div>
    </div>
  );
}

function ReportPreview({ report, onBack }: { report: ReportItem; onBack: () => void }) {
  return (
    <div style={{ background: BG_1, borderRadius: 10, padding: 24, border: `1px solid ${BG_2}` }}>
      <button
        onClick={onBack}
        style={{
          marginBottom: 16, padding: '6px 14px', borderRadius: 6, border: 'none',
          background: BG_2, color: TEXT_3, fontSize: 12, cursor: 'pointer',
        }}
      >← 返回列表</button>
      <div style={{ maxWidth: 800, margin: '0 auto' }}>
        <div style={{ textAlign: 'center', marginBottom: 24, paddingBottom: 16, borderBottom: `1px solid ${BG_2}` }}>
          <div style={{ fontSize: 10, color: BRAND, fontWeight: 600, marginBottom: 8 }}>屯象OS 市场情报中心</div>
          <h2 style={{ margin: '0 0 8px', fontSize: 20, fontWeight: 700, color: TEXT_1 }}>{report.title}</h2>
          <div style={{ fontSize: 12, color: TEXT_4 }}>
            {report.date}
            {report.pageCount > 0 && ` | ${report.pageCount} 页`}
            {report.readCount > 0 && ` | 阅读 ${report.readCount}`}
          </div>
        </div>

        {report.status === '生成中' ? (
          <div style={{
            padding: '40px 20px', textAlign: 'center',
            background: BG_2, borderRadius: 10, border: `1px dashed ${BLUE}44`,
          }}>
            <div style={{ fontSize: 32, marginBottom: 12 }}>⏳</div>
            <div style={{ fontSize: 16, fontWeight: 600, color: BLUE, marginBottom: 8 }}>报告生成中</div>
            <div style={{ fontSize: 13, color: TEXT_3, lineHeight: 1.7 }}>
              AI 正在收集市场数据并生成报告，预计需要 3-5 分钟。<br />
              生成完成后将自动推送通知，您也可以稍后刷新查看。
            </div>
          </div>
        ) : (
          <>
            <div style={{ marginBottom: 24 }}>
              <h3 style={{ fontSize: 15, fontWeight: 700, color: BRAND, marginBottom: 10 }}>摘要</h3>
              <div style={{
                fontSize: 13, color: TEXT_2, lineHeight: 1.8,
                padding: '12px 16px', background: BG_2, borderRadius: 8,
                borderLeft: `3px solid ${BRAND}`,
              }}>{report.summary || '摘要数据加载中...'}</div>
            </div>

            {report.keyFindings.length > 0 && (
              <div style={{ marginBottom: 24 }}>
                <h3 style={{ fontSize: 15, fontWeight: 700, color: BRAND, marginBottom: 10 }}>核心发现</h3>
                {report.keyFindings.map((f, i) => (
                  <div key={i} style={{
                    display: 'flex', gap: 10, marginBottom: 8,
                    padding: '10px 14px', background: BG_2, borderRadius: 6,
                  }}>
                    <span style={{
                      width: 22, height: 22, borderRadius: 11, background: BRAND + '22', color: BRAND,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: 11, fontWeight: 700, flexShrink: 0,
                    }}>{i + 1}</span>
                    <span style={{ fontSize: 13, color: TEXT_1, lineHeight: 1.6 }}>{f}</span>
                  </div>
                ))}
              </div>
            )}

            <div style={{ marginBottom: 24 }}>
              <h3 style={{ fontSize: 15, fontWeight: 700, color: BRAND, marginBottom: 10 }}>数据图表</h3>
              <div style={{
                height: 140, background: BG_2, borderRadius: 8,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                color: TEXT_4, fontSize: 13, flexDirection: 'column', gap: 8,
              }}>
                <span style={{ fontSize: 24 }}>📊</span>
                <span>详细图表数据请前往「经营分析」模块查看</span>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div style={{
      padding: '60px 20px', textAlign: 'center',
      background: BG_1, borderRadius: 10, border: `1px dashed ${BG_2}`,
    }}>
      <div style={{ fontSize: 36, marginBottom: 12 }}>📄</div>
      <div style={{ fontSize: 15, color: TEXT_3, marginBottom: 8 }}>{message}</div>
      <div style={{ fontSize: 12, color: TEXT_4 }}>
        AI 将根据您的配置自动生成市场情报报告
      </div>
    </div>
  );
}

// ---- 主页面 ----

export function TrendReportPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('list');
  const [typeFilter, setTypeFilter] = useState<ReportTypeFilter>('全部');
  const [reports, setReports] = useState<ReportItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [previewReport, setPreviewReport] = useState<ReportItem | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchTrendReports().then((data) => {
      if (!cancelled) {
        setReports(data);
        setLoading(false);
      }
    }).catch(() => {
      if (!cancelled) {
        setError('数据加载失败，请稍后重试');
        setLoading(false);
      }
    });
    return () => { cancelled = true; };
  }, []);

  const typeOptions: ReportTypeFilter[] = ['全部', '竞对周报', '需求周报', '新品周报', '原料周报', '商圈周报', '月报'];

  const filtered = typeFilter === '全部'
    ? reports
    : reports.filter((r) => r.type === typeFilter);

  const publishedCount = reports.filter((r) => r.status === '已发布').length;
  const generatingCount = reports.filter((r) => r.status === '生成中').length;
  const totalReads = reports.reduce((sum, r) => sum + r.readCount, 0);

  const handlePreview = (r: ReportItem) => {
    setPreviewReport(r);
    setActiveTab('preview');
  };

  const handleBackToList = () => {
    setPreviewReport(null);
    setActiveTab('list');
  };

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto', background: BG, minHeight: '100%', padding: '0 0 24px' }}>
      <h2 style={{ margin: '0 0 16px', fontSize: 22, fontWeight: 700, color: TEXT_1 }}>趋势报告中心</h2>

      {/* KPI 卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
        <KPICard label="总报告数" value={loading ? '...' : String(reports.length)} color={TEXT_1} />
        <KPICard label="已发布" value={loading ? '...' : String(publishedCount)} color={GREEN} />
        <KPICard label="生成中" value={loading ? '...' : String(generatingCount)} color={BLUE} />
        <KPICard label="总阅读量" value={loading ? '...' : totalReads.toLocaleString()} color={BRAND} />
      </div>

      {/* Tab 栏 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', gap: 4 }}>
          {(['list', 'preview'] as TabKey[]).map((k) => (
            <button
              key={k}
              onClick={() => { setActiveTab(k); if (k === 'list') setPreviewReport(null); }}
              style={{
                padding: '8px 18px', borderRadius: 8, border: 'none', cursor: 'pointer',
                background: activeTab === k ? BRAND : BG_1,
                color: activeTab === k ? '#fff' : TEXT_3,
                fontSize: 13, fontWeight: 600,
              }}
            >{k === 'list' ? '报告列表' : '报告预览'}</button>
          ))}
        </div>
        {activeTab === 'list' && (
          <div style={{ display: 'flex', gap: 4, marginLeft: 12, flexWrap: 'wrap' }}>
            {typeOptions.map((t) => (
              <button
                key={t}
                onClick={() => setTypeFilter(t)}
                style={{
                  padding: '4px 10px', borderRadius: 6, border: 'none', cursor: 'pointer',
                  background: typeFilter === t ? BLUE : BG_2,
                  color: typeFilter === t ? '#fff' : TEXT_3,
                  fontSize: 11, fontWeight: 600,
                }}
              >{t}</button>
            ))}
          </div>
        )}
      </div>

      {/* 内容区 */}
      {activeTab === 'list' && (
        <>
          {loading && (
            <div style={{ padding: '40px 0', textAlign: 'center', color: TEXT_4 }}>加载中...</div>
          )}
          {!loading && error && (
            <div style={{
              padding: '20px', background: RED + '11', borderRadius: 10,
              border: `1px solid ${RED}44`, color: RED, fontSize: 13, marginBottom: 16,
            }}>
              {error}
            </div>
          )}
          {!loading && !error && filtered.length === 0 && (
            <EmptyState message="暂无报告数据" />
          )}
          {!loading && !error && filtered.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {filtered.map((r) => (
                <ReportCard key={r.id} report={r} onPreview={handlePreview} />
              ))}
            </div>
          )}
          {/* 降级提示 */}
          {!loading && !error && reports.length === 0 && (
            <div style={{
              marginTop: 16, padding: '14px 18px',
              background: BLUE + '11', borderRadius: 8, border: `1px solid ${BLUE}33`,
              fontSize: 12, color: BLUE, lineHeight: 1.7,
            }}>
              提示：市场情报报告由 AI 定时自动生成。首次使用请在「生成调度」中启用报告任务，
              系统将按计划生成竞对周报、需求周报等情报报告。
            </div>
          )}
        </>
      )}

      {activeTab === 'preview' && (
        previewReport
          ? <ReportPreview report={previewReport} onBack={handleBackToList} />
          : (
            <div style={{
              padding: '48px 20px', textAlign: 'center',
              background: BG_1, borderRadius: 10, border: `1px solid ${BG_2}`,
            }}>
              <div style={{ fontSize: 32, marginBottom: 12 }}>👆</div>
              <div style={{ fontSize: 14, color: TEXT_3 }}>请先在「报告列表」中点击一份报告查看详情</div>
            </div>
          )
      )}
    </div>
  );
}
