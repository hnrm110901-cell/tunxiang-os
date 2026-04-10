/**
 * ScheduleCenter — 排班中心首页
 * 域F · 组织人事 · HR Admin
 *
 * 功能：
 *  - 多门店排班总览
 *  - StatisticCard：总排班人次/总工时/缺口率/调班率
 *  - 门店排班状态列表（门店名/本周排班完成率/冲突数/缺口数）
 *  - 点击门店跳转到该门店周排班
 *
 * API: GET /api/v1/schedules/statistics?month=
 */

import { useRef, useState } from 'react';
import { Button, Card, Col, Progress, Row, Statistic, Tag, Typography } from 'antd';
import {
  CalendarOutlined,
  ClockCircleOutlined,
  ExclamationCircleOutlined,
  SwapOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import { ProColumns, ProTable } from '@ant-design/pro-components';
import type { ActionType } from '@ant-design/pro-components';
import { useNavigate } from 'react-router-dom';
import { txFetch } from '../../../api';

const { Title } = Typography;
const TX_PRIMARY = '#FF6B35';

// ─── Types ───────────────────────────────────────────────────────────────────

interface ScheduleStats {
  total_shifts: number;
  total_hours: number;
  gap_rate: number;
  swap_rate: number;
}

interface StoreScheduleStatus {
  id: string;
  store_id: string;
  store_name: string;
  completion_rate: number;
  conflict_count: number;
  gap_count: number;
  total_scheduled: number;
}

interface StatsResp {
  stats: ScheduleStats;
  stores: { items: StoreScheduleStatus[]; total: number };
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function ScheduleCenter() {
  const actionRef = useRef<ActionType>(null);
  const navigate = useNavigate();
  const [stats, setStats] = useState<ScheduleStats>({
    total_shifts: 0,
    total_hours: 0,
    gap_rate: 0,
    swap_rate: 0,
  });

  const columns: ProColumns<StoreScheduleStatus>[] = [
    {
      title: '门店',
      dataIndex: 'store_name',
      width: 160,
      render: (_, r) => (
        <Button
          type="link"
          onClick={() => navigate(`/hr/schedules/week?store_id=${r.store_id}`)}
          style={{ padding: 0, color: TX_PRIMARY }}
        >
          {r.store_name}
        </Button>
      ),
    },
    {
      title: '本周排班完成率',
      dataIndex: 'completion_rate',
      width: 200,
      hideInSearch: true,
      render: (_, r) => (
        <Progress
          percent={r.completion_rate}
          size="small"
          strokeColor={r.completion_rate >= 90 ? '#52c41a' : r.completion_rate >= 70 ? '#faad14' : '#ff4d4f'}
        />
      ),
    },
    {
      title: '已排班人次',
      dataIndex: 'total_scheduled',
      width: 110,
      hideInSearch: true,
    },
    {
      title: '冲突数',
      dataIndex: 'conflict_count',
      width: 100,
      hideInSearch: true,
      render: (_, r) =>
        r.conflict_count > 0 ? (
          <Tag color="error">{r.conflict_count}</Tag>
        ) : (
          <Tag color="success">0</Tag>
        ),
    },
    {
      title: '缺口数',
      dataIndex: 'gap_count',
      width: 100,
      hideInSearch: true,
      render: (_, r) =>
        r.gap_count > 0 ? (
          <Tag color="warning">{r.gap_count}</Tag>
        ) : (
          <Tag color="success">0</Tag>
        ),
    },
    {
      title: '月份',
      dataIndex: 'month',
      valueType: 'dateMonth',
      hideInTable: true,
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      hideInSearch: true,
      render: (_, r) => (
        <Button
          type="primary"
          size="small"
          icon={<CalendarOutlined />}
          onClick={() => navigate(`/hr/schedules/week?store_id=${r.store_id}`)}
          style={{ backgroundColor: TX_PRIMARY, borderColor: TX_PRIMARY }}
        >
          查看排班
        </Button>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Title level={4}>排班中心</Title>

      {/* ── 统计卡片 ── */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="总排班人次"
              value={stats.total_shifts}
              prefix={<TeamOutlined style={{ color: TX_PRIMARY }} />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="总工时"
              value={stats.total_hours}
              prefix={<ClockCircleOutlined style={{ color: TX_PRIMARY }} />}
              suffix="小时"
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="缺口率"
              value={stats.gap_rate}
              precision={1}
              prefix={<ExclamationCircleOutlined style={{ color: stats.gap_rate > 10 ? '#ff4d4f' : '#52c41a' }} />}
              suffix="%"
              valueStyle={stats.gap_rate > 10 ? { color: '#ff4d4f' } : undefined}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="调班率"
              value={stats.swap_rate}
              precision={1}
              prefix={<SwapOutlined style={{ color: '#1890ff' }} />}
              suffix="%"
            />
          </Card>
        </Col>
      </Row>

      {/* ── 门店列表 ── */}
      <ProTable<StoreScheduleStatus>
        headerTitle="门店排班状态"
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        search={{ labelWidth: 80 }}
        request={async (params) => {
          const query = new URLSearchParams();
          if (params.month) query.set('month', params.month);
          query.set('page', String(params.current ?? 1));
          query.set('size', String(params.pageSize ?? 20));
          try {
            const res = await txFetch(`/api/v1/schedules/statistics?${query}`) as {
              ok: boolean;
              data: StatsResp;
            };
            if (res.ok && res.data) {
              setStats(res.data.stats);
              return {
                data: res.data.stores?.items ?? [],
                total: res.data.stores?.total ?? 0,
                success: true,
              };
            }
          } catch { /* fallback */ }
          return { data: [], total: 0, success: true };
        }}
        pagination={{ defaultPageSize: 20 }}
      />
    </div>
  );
}
