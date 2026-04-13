/**
 * PointsLeaderboardPage -- 积分排行榜
 * 域F . 组织人事 . HR Admin
 *
 * 功能：
 *  - TOP20积分排行（排名/姓名/总积分/获取/消耗/等级）
 *  - 门店/区域切换筛选
 *  - 统计概览（活跃人数/总发放/总消耗/净余额）
 *  - 搜索员工
 *
 * API: GET /api/v1/points/leaderboard
 *      GET /api/v1/points/stats
 */

import { useEffect, useRef, useState } from 'react';
import { Card, Col, Row, Select, Statistic, Tag, Typography } from 'antd';
import {
  CrownOutlined,
  FireOutlined,
  RiseOutlined,
  FallOutlined,
  TeamOutlined,
  TrophyOutlined,
} from '@ant-design/icons';
import { ProColumns, ProTable } from '@ant-design/pro-components';
import type { ActionType } from '@ant-design/pro-components';
import { txFetchData } from '../../../api';

const { Title } = Typography;
const TX_PRIMARY = '#FF6B35';

// -- Types -------------------------------------------------------------------

interface LeaderboardItem {
  employee_id: string;
  emp_name: string;
  store_id: string | null;
  total_points: number;
  earned: number;
  consumed: number;
  rank: number;
  level: string;
}

interface Stats {
  active_employees: number;
  total_earned: number;
  total_consumed: number;
  net_balance: number;
}

const LEVEL_COLORS: Record<string, string> = {
  '\u89C1\u4E60': '#bfbfbf',
  '\u94DC\u661F': '#cd7f32',
  '\u94F6\u661F': '#c0c0c0',
  '\u91D1\u661F': '#ffd700',
  '\u94BB\u77F3': '#b9f2ff',
  '\u738B\u8005': '#ff4d4f',
};

// -- Component ---------------------------------------------------------------

export default function PointsLeaderboardPage() {
  const actionRef = useRef<ActionType>(null);
  const [scopeType, setScopeType] = useState('store');
  const [scopeId, setScopeId] = useState<string | undefined>(undefined);
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const res = (await txFetchData('/api/v1/points/stats')) as {
          ok: boolean;
          data: Stats;
        };
        if (res.ok) setStats(res.data);
      } catch {
        /* empty */
      }
    })();
  }, []);

  const columns: ProColumns<LeaderboardItem>[] = [
    {
      title: '排名',
      dataIndex: 'rank',
      width: 80,
      hideInSearch: true,
      render: (_, r) => {
        if (r.rank <= 3) {
          const colors = ['#FFD700', '#C0C0C0', '#CD7F32'];
          return (
            <Tag color={colors[r.rank - 1]} style={{ fontWeight: 'bold' }}>
              {r.rank === 1 ? <CrownOutlined /> : <TrophyOutlined />} {r.rank}
            </Tag>
          );
        }
        return r.rank;
      },
    },
    {
      title: '姓名',
      dataIndex: 'emp_name',
      width: 120,
      render: (_, r) => (
        <a href={`/hr/performance/points/${r.employee_id}`}>
          <span style={r.rank <= 3 ? { fontWeight: 'bold', color: TX_PRIMARY } : undefined}>
            {r.emp_name}
          </span>
        </a>
      ),
    },
    {
      title: '等级',
      dataIndex: 'level',
      width: 80,
      hideInSearch: true,
      render: (_, r) => (
        <Tag color={LEVEL_COLORS[r.level] ?? '#d9d9d9'}>{r.level}</Tag>
      ),
    },
    {
      title: '总积分',
      dataIndex: 'total_points',
      width: 100,
      hideInSearch: true,
      sorter: true,
      render: (_, r) => (
        <span style={{ fontWeight: 'bold', color: TX_PRIMARY, fontSize: 16 }}>
          {r.total_points.toLocaleString()}
        </span>
      ),
    },
    {
      title: '获取',
      dataIndex: 'earned',
      width: 100,
      hideInSearch: true,
      render: (_, r) => (
        <span style={{ color: '#52c41a' }}>
          <RiseOutlined /> +{r.earned}
        </span>
      ),
    },
    {
      title: '消耗',
      dataIndex: 'consumed',
      width: 100,
      hideInSearch: true,
      render: (_, r) => (
        <span style={{ color: '#ff4d4f' }}>
          <FallOutlined /> {r.consumed}
        </span>
      ),
    },
    {
      title: '门店',
      dataIndex: 'store_id',
      hideInTable: true,
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Title level={4}>
        <FireOutlined style={{ color: TX_PRIMARY }} /> 积分排行榜
      </Title>

      {/* -- 统计卡 -- */}
      {stats && (
        <Row gutter={16} style={{ marginBottom: 24 }}>
          <Col span={6}>
            <Card>
              <Statistic
                title="参与员工"
                value={stats.active_employees}
                prefix={<TeamOutlined />}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="总发放"
                value={stats.total_earned}
                valueStyle={{ color: '#52c41a' }}
                prefix={<RiseOutlined />}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="总消耗"
                value={stats.total_consumed}
                valueStyle={{ color: '#ff4d4f' }}
                prefix={<FallOutlined />}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="净余额"
                value={stats.net_balance}
                valueStyle={{ color: TX_PRIMARY, fontWeight: 'bold' }}
              />
            </Card>
          </Col>
        </Row>
      )}

      {/* -- 筛选 -- */}
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={16} align="middle">
          <Col>
            <span style={{ marginRight: 8 }}>范围:</span>
            <Select
              value={scopeType}
              onChange={(v) => {
                setScopeType(v);
                setScopeId(undefined);
                actionRef.current?.reload();
              }}
              style={{ width: 120 }}
              options={[
                { label: '门店', value: 'store' },
                { label: '区域', value: 'region' },
                { label: '品牌', value: 'brand' },
              ]}
            />
          </Col>
          <Col>
            <Select
              placeholder="选择范围ID（可选）"
              allowClear
              style={{ width: 240 }}
              value={scopeId}
              onChange={(v) => {
                setScopeId(v);
                actionRef.current?.reload();
              }}
              showSearch
              options={[]}
            />
          </Col>
        </Row>
      </Card>

      {/* -- 表格 -- */}
      <ProTable<LeaderboardItem>
        headerTitle="TOP 积分排名"
        actionRef={actionRef}
        rowKey="employee_id"
        columns={columns}
        search={false}
        request={async () => {
          try {
            const q = new URLSearchParams();
            q.set('scope_type', scopeType);
            if (scopeId) q.set('scope_id', scopeId);
            q.set('limit', '50');
            const res = (await txFetchData(`/api/v1/points/leaderboard?${q}`)) as {
              ok: boolean;
              data: { items: LeaderboardItem[]; total: number };
            };
            if (res.ok) {
              return { data: res.data.items, total: res.data.total, success: true };
            }
          } catch {
            /* fallback */
          }
          return { data: [], total: 0, success: true };
        }}
        pagination={false}
      />
    </div>
  );
}
