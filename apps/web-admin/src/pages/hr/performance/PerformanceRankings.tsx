/**
 * PerformanceRankings — 绩效排名
 * 域F · 组织人事 · HR Admin
 *
 * 功能：
 *  - 门店+周期选择
 *  - 排名ProTable（排名/姓名/分数/变化趋势）
 *  - 前三名金银铜高亮
 *  - 分布柱状图（各分数段人数分布）
 *
 * API: GET /api/v1/performance/rankings?store_id=&period=
 */

import { useRef, useState } from 'react';
import { Card, Col, Row, Tag, Typography } from 'antd';
import { TrophyOutlined, ArrowUpOutlined, ArrowDownOutlined, MinusOutlined } from '@ant-design/icons';
import { ProColumns, ProTable } from '@ant-design/pro-components';
import type { ActionType } from '@ant-design/pro-components';
import { Column } from '@ant-design/charts';
import { txFetchData } from '../../../api';

const { Title } = Typography;
const TX_PRIMARY = '#FF6B35';

// ─── Types ───────────────────────────────────────────────────────────────────

interface RankingItem {
  id: string;
  rank: number;
  employee_id: string;
  employee_name: string;
  score: number;
  trend: 'up' | 'down' | 'same';
  trend_change: number;
  store_name: string;
  role: string;
}

interface ScoreDistribution {
  range: string;
  count: number;
}

interface RankingResp {
  items: RankingItem[];
  total: number;
  distribution: ScoreDistribution[];
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const MEDAL_COLORS: Record<number, string> = {
  1: '#FFD700', // 金
  2: '#C0C0C0', // 银
  3: '#CD7F32', // 铜
};

function TrendIcon({ trend, change }: { trend: string; change: number }) {
  if (trend === 'up') return <span style={{ color: '#52c41a' }}><ArrowUpOutlined /> +{change}</span>;
  if (trend === 'down') return <span style={{ color: '#ff4d4f' }}><ArrowDownOutlined /> {change}</span>;
  return <span style={{ color: '#999' }}><MinusOutlined /> 0</span>;
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function PerformanceRankings() {
  const actionRef = useRef<ActionType>(null);
  const [distribution, setDistribution] = useState<ScoreDistribution[]>([]);

  const columns: ProColumns<RankingItem>[] = [
    {
      title: '排名',
      dataIndex: 'rank',
      width: 80,
      hideInSearch: true,
      render: (_, r) => {
        const medal = MEDAL_COLORS[r.rank];
        return medal ? (
          <Tag color={medal} style={{ fontWeight: 'bold', fontSize: 14 }}>
            <TrophyOutlined /> {r.rank}
          </Tag>
        ) : (
          <span style={{ paddingLeft: 8 }}>{r.rank}</span>
        );
      },
    },
    { title: '姓名', dataIndex: 'employee_name', width: 100 },
    { title: '门店', dataIndex: 'store_name', width: 140, hideInSearch: true },
    { title: '岗位', dataIndex: 'role', width: 100, hideInSearch: true },
    {
      title: '分数',
      dataIndex: 'score',
      width: 100,
      hideInSearch: true,
      render: (_, r) => (
        <span style={{ fontWeight: r.rank <= 3 ? 'bold' : 'normal', color: r.rank <= 3 ? TX_PRIMARY : undefined }}>
          {r.score}
        </span>
      ),
    },
    {
      title: '变化趋势',
      key: 'trend',
      width: 100,
      hideInSearch: true,
      render: (_, r) => <TrendIcon trend={r.trend} change={r.trend_change} />,
    },
    {
      title: '考核期',
      dataIndex: 'period',
      valueType: 'dateMonth',
      hideInTable: true,
    },
    {
      title: '门店',
      dataIndex: 'store_id',
      hideInTable: true,
    },
  ];

  const chartConfig = {
    data: distribution,
    xField: 'range',
    yField: 'count',
    color: TX_PRIMARY,
    label: { position: 'top' as const },
    xAxis: { label: { autoRotate: false } },
  };

  return (
    <div style={{ padding: 24 }}>
      <Title level={4}>绩效排名</Title>

      <Row gutter={16}>
        <Col span={16}>
          <ProTable<RankingItem>
            headerTitle="绩效排行榜"
            actionRef={actionRef}
            rowKey="id"
            columns={columns}
            search={{ labelWidth: 80 }}
            rowClassName={(r) => (r.rank <= 3 ? 'ranking-top3' : '')}
            request={async (params) => {
              const query = new URLSearchParams();
              if (params.store_id) query.set('store_id', params.store_id);
              if (params.period) query.set('period', params.period);
              query.set('page', String(params.current ?? 1));
              query.set('size', String(params.pageSize ?? 20));
              try {
                const res = await txFetchData(`/api/v1/performance/rankings?${query}`) as {
                  ok: boolean;
                  data: RankingResp;
                };
                if (res.ok) {
                  setDistribution(res.data.distribution ?? []);
                  return { data: res.data.items, total: res.data.total, success: true };
                }
              } catch { /* fallback */ }
              return { data: [], total: 0, success: true };
            }}
            pagination={{ defaultPageSize: 20 }}
          />
        </Col>
        <Col span={8}>
          <Card title="分数段分布">
            <Column {...chartConfig} height={400} />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
