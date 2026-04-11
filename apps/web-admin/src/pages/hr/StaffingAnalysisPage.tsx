/**
 * StaffingAnalysisPage — 编制对标分析页
 *
 * 功能：
 *  1. 顶部控件行：门店选择器 + 日期选择 + 生成快照 + 刷新分析
 *  2. 4张统计卡片：编制总数/实际在岗/缺编人数/缺编率
 *  3. 左侧编制对标明细表 + 右侧缺编排名 Top 10
 *  4. 底部趋势折线图（近30天）
 *
 * API:
 *  POST /api/v1/staffing-analysis/snapshot
 *  GET  /api/v1/staffing-analysis/compare
 *  GET  /api/v1/staffing-analysis/gap-ranking
 *  GET  /api/v1/staffing-analysis/trend
 *  GET  /api/v1/staffing-analysis/impact
 */

import { useEffect, useState } from 'react';
import { ProTable, StatisticCard } from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';
import {
  Button,
  Card,
  Col,
  DatePicker,
  message,
  Progress,
  Row,
  Select,
  Space,
  Tag,
  Typography,
} from 'antd';
import { ReloadOutlined, CameraOutlined } from '@ant-design/icons';
import { Line } from '@ant-design/charts';
import dayjs from 'dayjs';
import type { Dayjs } from 'dayjs';
import { txFetch } from '../../api/client';
import type { TxResponse } from '../../api/client';

const { Title } = Typography;

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface StoreOption {
  id: string;
  name: string;
}

interface CompareItem {
  position: string;
  shift: string;
  required: number;
  actual: number;
  gap: number;
  skill_gap_detail: string;
  impact_score: number;
  risk_level?: string;
}

interface CompareSummary {
  total_required: number;
  total_actual: number;
  total_gap: number;
  gap_rate_pct: number;
}

interface CompareData {
  items: CompareItem[];
  summary: CompareSummary;
}

interface RankingItem {
  rank: number;
  store_id: string;
  store_name: string;
  total_required: number;
  total_actual: number;
  total_gap: number;
  gap_rate_pct: number;
}

interface TrendItem {
  date: string;
  total_required: number;
  total_actual: number;
  gap: number;
  gap_rate_pct: number;
}

interface ImpactItem {
  store_id: string;
  store_name: string;
  position: string;
  shift: string;
  gap: number;
  impact_score: number;
  risk_level: string;
}

// ─── 映射 ────────────────────────────────────────────────────────────────────

const positionMap: Record<string, string> = {
  manager: '店长',
  chef: '厨师',
  waiter: '服务员',
  cashier: '收银',
  cleaner: '保洁',
};

const shiftMap: Record<string, string> = {
  morning: '早班',
  afternoon: '午班',
  evening: '晚班',
  full_day: '全天',
};

// ─── 颜色工具 ─────────────────────────────────────────────────────────────────

function gapTagColor(gap: number): string {
  if (gap < 0) return 'red';
  if (gap === 0) return 'green';
  return 'blue';
}

function gapTagLabel(gap: number): string {
  if (gap < 0) return `缺编 ${Math.abs(gap)}`;
  if (gap === 0) return '满编';
  return `富余 ${gap}`;
}

function impactColor(score: number): string {
  if (score >= 8) return '#cf1322';
  if (score >= 5) return '#fa8c16';
  return '#52c41a';
}

function riskTagColor(level: string | undefined): string {
  if (!level) return 'default';
  const l = level.toLowerCase();
  if (l === 'high' || l === '高') return 'red';
  if (l === 'medium' || l === '中') return 'orange';
  return 'green';
}

function gapRatePctStyle(pct: number): React.CSSProperties {
  if (pct > 20) return { color: '#cf1322', fontWeight: 600 };
  if (pct > 10) return { color: '#fa8c16', fontWeight: 600 };
  return {};
}

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function StaffingAnalysisPage() {
  const [storeId, setStoreId] = useState<string>('');
  const [selectedDate, setSelectedDate] = useState<Dayjs>(dayjs());
  const [stores, setStores] = useState<StoreOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [snapshotLoading, setSnapshotLoading] = useState(false);

  // 数据
  const [compareItems, setCompareItems] = useState<CompareItem[]>([]);
  const [summary, setSummary] = useState<CompareSummary | null>(null);
  const [rankingItems, setRankingItems] = useState<RankingItem[]>([]);
  const [trendItems, setTrendItems] = useState<TrendItem[]>([]);
  const [impactItems, setImpactItems] = useState<ImpactItem[]>([]);

  // ─── 加载门店列表 ──────────────────────────────────────────────────────────
  useEffect(() => {
    (async () => {
      const res = await txFetch<{ items: { id: string; name: string }[] }>(
        '/api/v1/stores?page=1&size=200',
      );
      if (res.ok && res.data) {
        const list = res.data.items.map((s) => ({ id: s.id, name: s.name }));
        setStores(list);
        if (list.length > 0) {
          setStoreId(list[0].id);
        }
      }
    })();
  }, []);

  // ─── 数据加载 ──────────────────────────────────────────────────────────────
  const dateStr = selectedDate.format('YYYY-MM-DD');

  const fetchCompare = async (sid: string) => {
    const res = await txFetch<CompareData>(
      `/api/v1/staffing-analysis/compare?store_id=${encodeURIComponent(sid)}&snapshot_date=${dateStr}`,
    );
    if (res.ok && res.data) {
      setCompareItems(res.data.items);
      setSummary(res.data.summary);
    }
  };

  const fetchImpact = async (sid: string) => {
    const res = await txFetch<{ items: ImpactItem[] }>(
      `/api/v1/staffing-analysis/impact?store_id=${encodeURIComponent(sid)}&snapshot_date=${dateStr}`,
    );
    if (res.ok && res.data) {
      setImpactItems(res.data.items);
    }
  };

  const fetchRanking = async () => {
    const res = await txFetch<{ items: RankingItem[] }>(
      `/api/v1/staffing-analysis/gap-ranking?snapshot_date=${dateStr}&limit=10`,
    );
    if (res.ok && res.data) {
      setRankingItems(res.data.items);
    }
  };

  const fetchTrend = async (sid: string) => {
    const endDate = selectedDate.format('YYYY-MM-DD');
    const startDate = selectedDate.subtract(29, 'day').format('YYYY-MM-DD');
    const res = await txFetch<{ items: TrendItem[] }>(
      `/api/v1/staffing-analysis/trend?store_id=${encodeURIComponent(sid)}&start_date=${startDate}&end_date=${endDate}`,
    );
    if (res.ok && res.data) {
      setTrendItems(res.data.items);
    }
  };

  const refreshAll = async (sid?: string) => {
    const id = sid || storeId;
    if (!id) return;
    setLoading(true);
    try {
      await Promise.all([
        fetchCompare(id),
        fetchImpact(id),
        fetchRanking(),
        fetchTrend(id),
      ]);
    } catch (err) {
      message.error('数据加载失败');
    } finally {
      setLoading(false);
    }
  };

  // storeId 或日期变化时自动刷新
  useEffect(() => {
    if (storeId) {
      refreshAll(storeId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storeId, dateStr]);

  // ─── 生成快照 ──────────────────────────────────────────────────────────────
  const handleSnapshot = async () => {
    if (!storeId) {
      message.warning('请先选择门店');
      return;
    }
    setSnapshotLoading(true);
    try {
      const res = await txFetch<unknown>('/api/v1/staffing-analysis/snapshot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ store_id: storeId, snapshot_date: dateStr }),
      });
      if (res.ok) {
        message.success('快照生成成功');
        await refreshAll();
      } else {
        message.error(res.error?.message || '快照生成失败');
      }
    } catch (err) {
      message.error('快照生成请求失败');
    } finally {
      setSnapshotLoading(false);
    }
  };

  // ─── 合并 impact 数据到 compare 明细 ──────────────────────────────────────
  const mergedCompareItems: (CompareItem & { risk_level?: string })[] =
    compareItems.map((item) => {
      const impact = impactItems.find(
        (imp) => imp.position === item.position && imp.shift === item.shift,
      );
      return {
        ...item,
        risk_level: impact?.risk_level ?? item.risk_level,
      };
    });

  // ─── 编制对标明细表列 ──────────────────────────────────────────────────────
  const compareColumns: ProColumns<CompareItem & { risk_level?: string }>[] = [
    {
      title: '岗位',
      dataIndex: 'position',
      width: 80,
      render: (_, r) => positionMap[r.position] || r.position,
    },
    {
      title: '班次',
      dataIndex: 'shift',
      width: 80,
      render: (_, r) => shiftMap[r.shift] || r.shift,
    },
    {
      title: '编制人数',
      dataIndex: 'required',
      width: 80,
      align: 'center',
    },
    {
      title: '实际人数',
      dataIndex: 'actual',
      width: 80,
      align: 'center',
    },
    {
      title: '缺口',
      dataIndex: 'gap',
      width: 100,
      align: 'center',
      render: (_, r) => <Tag color={gapTagColor(r.gap)}>{gapTagLabel(r.gap)}</Tag>,
    },
    {
      title: '影响评分',
      dataIndex: 'impact_score',
      width: 120,
      render: (_, r) => (
        <Progress
          percent={r.impact_score * 10}
          size="small"
          steps={10}
          strokeColor={impactColor(r.impact_score)}
          format={() => r.impact_score.toFixed(1)}
        />
      ),
    },
    {
      title: '风险',
      dataIndex: 'risk_level',
      width: 80,
      align: 'center',
      render: (_, r) =>
        r.risk_level ? (
          <Tag color={riskTagColor(r.risk_level)}>{r.risk_level}</Tag>
        ) : (
          '-'
        ),
    },
  ];

  // ─── 缺编排名表列 ──────────────────────────────────────────────────────────
  const rankingColumns: ProColumns<RankingItem>[] = [
    {
      title: '排名',
      dataIndex: 'rank',
      width: 50,
      align: 'center',
    },
    {
      title: '门店',
      dataIndex: 'store_name',
      ellipsis: true,
      render: (_, r) => (
        <a
          onClick={() => {
            setStoreId(r.store_id);
          }}
        >
          {r.store_name}
        </a>
      ),
    },
    {
      title: '缺编',
      dataIndex: 'total_gap',
      width: 70,
      align: 'center',
      render: (_, r) => (
        <Tag color="red">{r.total_gap}</Tag>
      ),
    },
    {
      title: '缺编率',
      dataIndex: 'gap_rate_pct',
      width: 80,
      align: 'center',
      render: (_, r) => (
        <span style={gapRatePctStyle(r.gap_rate_pct)}>
          {r.gap_rate_pct.toFixed(1)}%
        </span>
      ),
    },
  ];

  // ─── 趋势图配置 ────────────────────────────────────────────────────────────
  const trendChartData = trendItems.flatMap((item) => [
    { date: item.date, value: item.total_required, type: '编制人数' },
    { date: item.date, value: item.total_actual, type: '实际在岗' },
    { date: item.date, value: Math.abs(item.gap), type: '缺口人数' },
  ]);

  const trendConfig = {
    data: trendChartData,
    xField: 'date',
    yField: 'value',
    colorField: 'type',
    shapeField: 'smooth',
    style: {
      lineWidth: 2,
    },
    scale: {
      color: {
        domain: ['编制人数', '实际在岗', '缺口人数'],
        range: ['#1677ff', '#52c41a', '#cf1322'],
      },
    },
    axis: {
      x: { title: '日期' },
      y: { title: '人数' },
    },
    legend: {
      color: {
        position: 'top' as const,
      },
    },
    interaction: {
      tooltip: {
        crosshairs: true,
      },
    },
    height: 320,
  };

  // ─── 渲染 ──────────────────────────────────────────────────────────────────
  return (
    <div style={{ padding: 24 }}>
      <Title level={4} style={{ marginBottom: 16 }}>
        编制对标分析
      </Title>

      {/* Section 1: 控件 + 汇总卡片 */}
      <Card style={{ marginBottom: 16 }}>
        <Space wrap size="middle" style={{ marginBottom: 16 }}>
          <Select
            placeholder="选择门店"
            value={storeId || undefined}
            onChange={(v) => setStoreId(v)}
            style={{ width: 220 }}
            showSearch
            optionFilterProp="label"
            options={stores.map((s) => ({ value: s.id, label: s.name }))}
          />
          <DatePicker
            value={selectedDate}
            onChange={(d) => d && setSelectedDate(d)}
            allowClear={false}
          />
          <Button
            type="primary"
            icon={<CameraOutlined />}
            loading={snapshotLoading}
            onClick={handleSnapshot}
          >
            生成快照
          </Button>
          <Button
            icon={<ReloadOutlined />}
            loading={loading}
            onClick={() => refreshAll()}
          >
            刷新分析
          </Button>
        </Space>

        <Row gutter={16}>
          <Col span={6}>
            <StatisticCard
              statistic={{
                title: '编制总数',
                value: summary?.total_required ?? '-',
                suffix: '人',
              }}
            />
          </Col>
          <Col span={6}>
            <StatisticCard
              statistic={{
                title: '实际在岗',
                value: summary?.total_actual ?? '-',
                suffix: '人',
              }}
            />
          </Col>
          <Col span={6}>
            <StatisticCard
              statistic={{
                title: '缺编人数',
                value: summary?.total_gap ?? '-',
                suffix: '人',
                valueStyle:
                  summary && summary.total_gap < 0
                    ? { color: '#cf1322' }
                    : undefined,
              }}
            />
          </Col>
          <Col span={6}>
            <StatisticCard
              statistic={{
                title: '缺编率',
                value:
                  summary != null
                    ? `${summary.gap_rate_pct.toFixed(1)}%`
                    : '-',
                valueStyle: summary
                  ? gapRatePctStyle(summary.gap_rate_pct)
                  : undefined,
              }}
            />
          </Col>
        </Row>
      </Card>

      {/* Section 2: 明细 + 排名 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={14}>
          <Card title="编制对标明细表" size="small">
            <ProTable<CompareItem & { risk_level?: string }>
              columns={compareColumns}
              dataSource={mergedCompareItems}
              rowKey={(r) => `${r.position}-${r.shift}`}
              loading={loading}
              search={false}
              toolBarRender={false}
              pagination={false}
              size="small"
            />
          </Card>
        </Col>
        <Col span={10}>
          <Card title="缺编排名 Top 10" size="small">
            <ProTable<RankingItem>
              columns={rankingColumns}
              dataSource={rankingItems}
              rowKey="rank"
              loading={loading}
              search={false}
              toolBarRender={false}
              pagination={false}
              size="small"
            />
          </Card>
        </Col>
      </Row>

      {/* Section 3: 趋势图 */}
      <Card title="编制趋势（近30天）">
        {trendItems.length > 0 ? (
          <Line {...trendConfig} />
        ) : (
          <div
            style={{
              height: 320,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#999',
            }}
          >
            暂无趋势数据
          </div>
        )}
      </Card>
    </div>
  );
}
