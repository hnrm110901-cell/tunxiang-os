/**
 * 舆情监控页 — /hq/ops/public-opinion
 *
 * 布局：
 *   顶部：平台 Tabs + 情感筛选 + 门店筛选
 *   左侧（1/3）：趋势折线图（最近8周好评/差评）
 *   中间（1/3）：舆情列表卡片（分页）
 *   右侧（1/3）：高频投诉关键词词云（标签大小表示频率）
 *
 * API：
 *   GET /api/v1/ops/public-opinion/stats
 *   GET /api/v1/ops/public-opinion/mentions
 *   GET /api/v1/ops/public-opinion/trends
 *   GET /api/v1/ops/public-opinion/top-complaints
 *   PATCH /api/v1/ops/public-opinion/mentions/{id}/resolve
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Card, Row, Col, Tabs, Select, Tag, Button, Spin, Empty,
  Pagination, Tooltip, Badge, message, Typography, Space,
} from 'antd';
import { CheckCircleOutlined, ExclamationCircleOutlined, ReloadOutlined } from '@ant-design/icons';
import { Line } from '@ant-design/charts';
import { apiGet, apiRequest } from '../api/client';

const { Text, Paragraph } = Typography;

// ─────────────────────────────────────────────────────────
//  类型定义
// ─────────────────────────────────────────────────────────

interface Mention {
  id: string;
  platform: 'dianping' | 'meituan' | 'weibo' | 'wechat';
  content: string;
  sentiment: 'positive' | 'neutral' | 'negative';
  sentiment_score: number;
  rating: number | null;
  author_name: string;
  published_at: string;
  is_resolved: boolean;
  resolution_note: string | null;
  store_id: string;
}

interface MentionListData {
  mentions: Mention[];
  total: number;
  page: number;
  page_size: number;
}

interface OpinionStats {
  store_id: string;
  platform: string;
  total_count: number;
  positive_count: number;
  neutral_count: number;
  negative_count: number;
  avg_rating: number | null;
  unresolved_count: number;
}

interface TrendPoint {
  week_start: string;
  positive_count: number;
  neutral_count: number;
  negative_count: number;
  total_count: number;
  avg_rating: number | null;
}

interface KeywordItem {
  keyword: string;
  frequency: number;
}

// ─────────────────────────────────────────────────────────
//  常量
// ─────────────────────────────────────────────────────────

const PLATFORM_ICON: Record<string, string> = {
  dianping: '🍴',
  meituan: '🛵',
  weibo: '🐦',
  wechat: '💬',
};

const PLATFORM_LABEL: Record<string, string> = {
  dianping: '大众点评',
  meituan: '美团',
  weibo: '微博',
  wechat: '微信',
};

const SENTIMENT_CONFIG: Record<string, { color: string; label: string; antColor: string }> = {
  positive: { color: '#0F6E56', label: '好评', antColor: 'success' },
  neutral:  { color: '#5F5E5A', label: '中性', antColor: 'default' },
  negative: { color: '#A32D2D', label: '差评', antColor: 'error' },
};

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

// ─────────────────────────────────────────────────────────
//  主组件
// ─────────────────────────────────────────────────────────

export function PublicOpinionPage() {
  const [platformFilter, setPlatformFilter] = useState<string>('all');
  const [sentimentFilter, setSentimentFilter] = useState<string>('all');
  const [storeFilter, setStoreFilter] = useState<string | undefined>(undefined);

  const [mentions, setMentions] = useState<Mention[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [trends, setTrends] = useState<TrendPoint[]>([]);
  const [stats, setStats] = useState<OpinionStats[]>([]);
  const [keywords, setKeywords] = useState<KeywordItem[]>([]);

  const [loadingMentions, setLoadingMentions] = useState(false);
  const [loadingTrends, setLoadingTrends] = useState(false);
  const [loadingKeywords, setLoadingKeywords] = useState(false);
  const [resolvingId, setResolvingId] = useState<string | null>(null);

  // ── 拉取数据 ──────────────────────────────────────────
  const fetchMentions = useCallback(async (currentPage: number) => {
    setLoadingMentions(true);
    try {
      const params = new URLSearchParams();
      params.set('page', String(currentPage));
      params.set('page_size', '20');
      if (platformFilter !== 'all') params.set('platform', platformFilter);
      if (sentimentFilter !== 'all') params.set('sentiment', sentimentFilter);
      if (storeFilter) params.set('store_id', storeFilter);

      const data = await apiGet<MentionListData>(`${BASE_URL}/api/v1/ops/public-opinion/mentions?${params.toString()}`);
      setMentions(data.mentions || []);
      setTotal(data.total || 0);
    } catch {
      setMentions([]);
      setTotal(0);
    } finally {
      setLoadingMentions(false);
    }
  }, [platformFilter, sentimentFilter, storeFilter]);

  const fetchTrends = useCallback(async () => {
    setLoadingTrends(true);
    try {
      const params = new URLSearchParams();
      if (platformFilter !== 'all') params.set('platform', platformFilter);
      if (storeFilter) params.set('store_id', storeFilter);
      const data = await apiGet<{ trends: TrendPoint[] }>(`${BASE_URL}/api/v1/ops/public-opinion/trends?${params.toString()}`);
      setTrends(data.trends || []);
    } catch {
      setTrends([]);
    } finally {
      setLoadingTrends(false);
    }
  }, [platformFilter, storeFilter]);

  const fetchStats = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (storeFilter) params.set('store_id', storeFilter);
      const data = await apiGet<{ stats: OpinionStats[] }>(`${BASE_URL}/api/v1/ops/public-opinion/stats?${params.toString()}`);
      setStats(data.stats || []);
    } catch {
      setStats([]);
    }
  }, [storeFilter]);

  const fetchKeywords = useCallback(async () => {
    setLoadingKeywords(true);
    try {
      const params = new URLSearchParams();
      if (storeFilter) params.set('store_id', storeFilter);
      const data = await apiGet<{ keywords: KeywordItem[] }>(`${BASE_URL}/api/v1/ops/public-opinion/top-complaints?${params.toString()}`);
      setKeywords(data.keywords || []);
    } catch {
      setKeywords([]);
    } finally {
      setLoadingKeywords(false);
    }
  }, [storeFilter]);

  useEffect(() => {
    setPage(1);
    Promise.allSettled([
      fetchMentions(1),
      fetchTrends(),
      fetchStats(),
      fetchKeywords(),
    ]);
  }, [platformFilter, sentimentFilter, storeFilter, fetchMentions, fetchTrends, fetchStats, fetchKeywords]);

  // ── 标记已处理 ─────────────────────────────────────────
  const handleResolve = async (mentionId: string) => {
    setResolvingId(mentionId);
    try {
      await apiRequest(`${BASE_URL}/api/v1/ops/public-opinion/mentions/${mentionId}/resolve`, {
        method: 'PATCH',
        body: { resolution_note: '已处理' },
      });
      message.success('已标记为处理完成');
      setMentions(prev => prev.map(m => m.id === mentionId ? { ...m, is_resolved: true } : m));
    } catch {
      message.error('操作失败，请重试');
    } finally {
      setResolvingId(null);
    }
  };

  // ── 趋势图数据 ────────────────────────────────────────
  const trendChartData = trends.flatMap(t => {
    const week = t.week_start ? t.week_start.slice(0, 10) : '';
    return [
      { week, count: t.positive_count, type: '好评' },
      { week, count: t.negative_count, type: '差评' },
    ];
  });

  const trendConfig = {
    data: trendChartData,
    xField: 'week',
    yField: 'count',
    seriesField: 'type',
    color: ['#0F6E56', '#A32D2D'],
    smooth: true,
    point: { size: 3, shape: 'circle' as const },
    legend: { position: 'top-right' as const },
    xAxis: { label: { rotate: -30, style: { fontSize: 11 } } },
    yAxis: { label: { style: { fontSize: 11 } } },
    tooltip: {
      formatter: (datum: { type: string; count: number }) => ({ name: datum.type, value: `${datum.count} 条` }),
    },
    height: 200,
  };

  // ── 汇总统计卡片 ───────────────────────────────────────
  const totalMentions = stats.reduce((acc, s) => acc + (s.total_count || 0), 0);
  const totalPositive = stats.reduce((acc, s) => acc + (s.positive_count || 0), 0);
  const totalNegative = stats.reduce((acc, s) => acc + (s.negative_count || 0), 0);
  const totalUnresolved = stats.reduce((acc, s) => acc + (s.unresolved_count || 0), 0);

  // ── 关键词词云最大频率 ────────────────────────────────
  const maxFreq = keywords.length > 0 ? Math.max(...keywords.map(k => k.frequency)) : 1;

  return (
    <div style={{ padding: '16px 20px', minHeight: '100vh', background: '#F8F7F5' }}>
      {/* ── 页面标题 ── */}
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ fontSize: 20, fontWeight: 700, color: '#2C2C2A' }}>舆情监控</span>
        {totalUnresolved > 0 && (
          <Badge count={totalUnresolved} color="#A32D2D" overflowCount={99}>
            <Tag icon={<ExclamationCircleOutlined />} color="error">未处理差评</Tag>
          </Badge>
        )}
        <Button
          size="small"
          icon={<ReloadOutlined />}
          onClick={() => {
            setPage(1);
            fetchMentions(1);
            fetchTrends();
            fetchStats();
            fetchKeywords();
          }}
          style={{ marginLeft: 'auto' }}
        >
          刷新
        </Button>
      </div>

      {/* ── 汇总指标 ── */}
      <Row gutter={12} style={{ marginBottom: 16 }}>
        {[
          { label: '总声量', value: totalMentions, color: '#185FA5' },
          { label: '好评', value: totalPositive, color: '#0F6E56' },
          { label: '差评', value: totalNegative, color: '#A32D2D' },
          { label: '未处理', value: totalUnresolved, color: '#BA7517' },
        ].map(({ label, value, color }) => (
          <Col span={6} key={label}>
            <Card size="small" bordered={false} style={{ borderTop: `3px solid ${color}` }}>
              <div style={{ fontSize: 11, color: '#5F5E5A', marginBottom: 2 }}>{label}</div>
              <div style={{ fontSize: 22, fontWeight: 700, color }}>{value}</div>
            </Card>
          </Col>
        ))}
      </Row>

      {/* ── 筛选栏 ── */}
      <Card size="small" bordered={false} style={{ marginBottom: 16 }}>
        <Space wrap>
          <span style={{ fontSize: 12, color: '#5F5E5A' }}>平台：</span>
          <Tabs
            size="small"
            activeKey={platformFilter}
            onChange={setPlatformFilter}
            style={{ marginBottom: 0 }}
            items={[
              { key: 'all', label: '全部' },
              { key: 'dianping', label: '🍴 大众点评' },
              { key: 'meituan', label: '🛵 美团' },
              { key: 'weibo', label: '🐦 微博' },
              { key: 'wechat', label: '💬 微信' },
            ]}
          />
          <span style={{ fontSize: 12, color: '#5F5E5A', marginLeft: 12 }}>情感：</span>
          <Select
            size="small"
            value={sentimentFilter}
            onChange={setSentimentFilter}
            style={{ width: 100 }}
            options={[
              { value: 'all', label: '全部' },
              { value: 'positive', label: '😊 好评' },
              { value: 'neutral', label: '😐 中性' },
              { value: 'negative', label: '😠 差评' },
            ]}
          />
        </Space>
      </Card>

      {/* ── 三栏主体 ── */}
      <Row gutter={12}>
        {/* 左：趋势折线图 */}
        <Col span={8}>
          <Card
            title="近8周趋势"
            size="small"
            bordered={false}
            style={{ marginBottom: 12 }}
            loading={loadingTrends}
          >
            {trends.length > 0 ? (
              <Line {...trendConfig} />
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无趋势数据" style={{ margin: '20px 0' }} />
            )}
          </Card>

          {/* 各平台统计小卡 */}
          <Card title="平台分布" size="small" bordered={false}>
            {stats.length === 0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无统计数据" style={{ margin: '12px 0' }} />}
            {stats.slice(0, 8).map((s, idx) => (
              <div key={idx} style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '4px 0', borderBottom: '1px solid #F0EDE6',
              }}>
                <span style={{ fontSize: 12 }}>
                  {PLATFORM_ICON[s.platform] || '📌'} {PLATFORM_LABEL[s.platform] || s.platform}
                </span>
                <Space size={4}>
                  <Tag color="success" style={{ fontSize: 10, margin: 0 }}>{s.positive_count}好</Tag>
                  <Tag color="error" style={{ fontSize: 10, margin: 0 }}>{s.negative_count}差</Tag>
                  {s.avg_rating && (
                    <span style={{ fontSize: 11, color: '#BA7517' }}>⭐{Number(s.avg_rating).toFixed(1)}</span>
                  )}
                </Space>
              </div>
            ))}
          </Card>
        </Col>

        {/* 中：舆情列表 */}
        <Col span={8}>
          <Card
            title={
              <span>
                舆情列表
                <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>共 {total} 条</Text>
              </span>
            }
            size="small"
            bordered={false}
          >
            <Spin spinning={loadingMentions}>
              {mentions.length === 0 && !loadingMentions && (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无舆情数据" style={{ margin: '32px 0' }} />
              )}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {mentions.map((m) => {
                  const isNegativeUnresolved = m.sentiment === 'negative' && !m.is_resolved;
                  const sentCfg = SENTIMENT_CONFIG[m.sentiment] || SENTIMENT_CONFIG.neutral;
                  return (
                    <div
                      key={m.id}
                      style={{
                        background: '#fff',
                        borderRadius: 6,
                        padding: '10px 12px',
                        borderLeft: isNegativeUnresolved ? '3px solid #A32D2D' : '3px solid transparent',
                        boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
                        opacity: m.is_resolved ? 0.65 : 1,
                      }}
                    >
                      {/* 头部：平台 + 情感 + 时间 */}
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                        <span style={{ fontSize: 14 }}>{PLATFORM_ICON[m.platform] || '📌'}</span>
                        <span style={{ fontSize: 11, color: '#5F5E5A' }}>{PLATFORM_LABEL[m.platform] || m.platform}</span>
                        <Tag
                          color={sentCfg.antColor as 'success' | 'error' | 'default'}
                          style={{ fontSize: 10, padding: '0 4px', margin: 0 }}
                        >
                          {sentCfg.label}
                        </Tag>
                        {m.rating !== null && m.rating !== undefined && (
                          <span style={{ fontSize: 11, color: '#BA7517', marginLeft: 2 }}>
                            {'⭐'.repeat(Math.round(m.rating))}
                          </span>
                        )}
                        <span style={{ fontSize: 10, color: '#B4B2A9', marginLeft: 'auto' }}>
                          {m.published_at ? m.published_at.slice(0, 10) : '—'}
                        </span>
                      </div>

                      {/* 内容摘要 */}
                      <Paragraph
                        ellipsis={{ rows: 2 }}
                        style={{ fontSize: 12, color: '#2C2C2A', margin: 0, lineHeight: 1.5 }}
                      >
                        {m.content}
                      </Paragraph>

                      {/* 底部：作者 + 操作 */}
                      <div style={{ display: 'flex', alignItems: 'center', marginTop: 6 }}>
                        {m.author_name && (
                          <span style={{ fontSize: 11, color: '#B4B2A9' }}>@{m.author_name}</span>
                        )}
                        <div style={{ marginLeft: 'auto' }}>
                          {m.is_resolved ? (
                            <Tag icon={<CheckCircleOutlined />} color="default" style={{ fontSize: 10 }}>已处理</Tag>
                          ) : (
                            <Button
                              size="small"
                              type="link"
                              style={{ fontSize: 11, padding: '0 4px', height: 'auto' }}
                              loading={resolvingId === m.id}
                              onClick={() => handleResolve(m.id)}
                            >
                              标记已处理
                            </Button>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* 分页 */}
              {total > 20 && (
                <div style={{ display: 'flex', justifyContent: 'center', marginTop: 12 }}>
                  <Pagination
                    size="small"
                    current={page}
                    total={total}
                    pageSize={20}
                    showSizeChanger={false}
                    onChange={(p) => {
                      setPage(p);
                      fetchMentions(p);
                    }}
                  />
                </div>
              )}
            </Spin>
          </Card>
        </Col>

        {/* 右：高频关键词词云 */}
        <Col span={8}>
          <Card
            title="高频投诉关键词"
            size="small"
            bordered={false}
            loading={loadingKeywords}
          >
            {keywords.length === 0 && !loadingKeywords && (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无关键词数据" style={{ margin: '32px 0' }} />
            )}
            {keywords.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, padding: '8px 0' }}>
                {keywords.map(({ keyword, frequency }) => {
                  const ratio = frequency / maxFreq;
                  const fontSize = Math.round(11 + ratio * 14); // 11px ~ 25px
                  const opacity = 0.5 + ratio * 0.5;
                  // 颜色从橙到红（高频越红）
                  const red = Math.round(163 + (1 - ratio) * 50);
                  const green = Math.round(45 * (1 - ratio));
                  const blue = Math.round(45 * (1 - ratio));
                  const color = `rgb(${red},${green},${blue})`;
                  return (
                    <Tooltip key={keyword} title={`出现 ${frequency} 次`}>
                      <span
                        style={{
                          fontSize,
                          fontWeight: ratio > 0.7 ? 700 : 500,
                          color,
                          opacity,
                          cursor: 'default',
                          lineHeight: 1.6,
                          padding: '2px 4px',
                          borderRadius: 4,
                          background: ratio > 0.7 ? `rgba(163,45,45,0.08)` : 'transparent',
                          transition: 'all 0.2s',
                        }}
                      >
                        {keyword}
                      </span>
                    </Tooltip>
                  );
                })}
              </div>
            )}

            {/* 差评关键词排行 */}
            {keywords.length > 0 && (
              <div style={{ marginTop: 12, borderTop: '1px solid #F0EDE6', paddingTop: 10 }}>
                <div style={{ fontSize: 11, color: '#5F5E5A', marginBottom: 8, fontWeight: 600 }}>Top 差评词排行</div>
                {keywords.slice(0, 5).map(({ keyword, frequency }, idx) => (
                  <div key={keyword} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <span style={{
                      width: 18, height: 18, borderRadius: '50%',
                      background: idx < 3 ? '#A32D2D' : '#E8E6E1',
                      color: idx < 3 ? '#fff' : '#5F5E5A',
                      fontSize: 10, fontWeight: 700,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      flexShrink: 0,
                    }}>
                      {idx + 1}
                    </span>
                    <span style={{ flex: 1, fontSize: 12, color: '#2C2C2A' }}>{keyword}</span>
                    <span style={{ fontSize: 11, color: '#A32D2D', fontWeight: 600 }}>{frequency}次</span>
                    <div style={{
                      width: 60, height: 4, borderRadius: 2, background: '#F0EDE6', overflow: 'hidden',
                    }}>
                      <div style={{
                        width: `${(frequency / maxFreq) * 100}%`,
                        height: '100%',
                        background: '#A32D2D',
                        borderRadius: 2,
                      }} />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );
}

export default PublicOpinionPage;
