/**
 * PerformancePointDetail — 积分流水
 * 域F · 组织人事 · HR Admin
 *
 * 功能：
 *  - 路由参数取employee_id
 *  - 顶部：员工信息卡+当前积分余额
 *  - ProTable流水记录（日期/类型获取/消耗/分数/原因/操作人）
 *  - 积分趋势Line折线图
 *
 * API: GET /api/v1/points/detail/{employee_id}
 */

import { useEffect, useRef, useState } from 'react';
import { Card, Col, Row, Statistic, Tag, Typography } from 'antd';
import { UserOutlined, StarOutlined } from '@ant-design/icons';
import { ProColumns, ProTable } from '@ant-design/pro-components';
import type { ActionType } from '@ant-design/pro-components';
import { Line } from '@ant-design/charts';
import { useParams } from 'react-router-dom';
import { txFetch } from '../../../api';

const { Title, Text } = Typography;
const TX_PRIMARY = '#FF6B35';

// ─── Types ───────────────────────────────────────────────────────────────────

interface EmployeeInfo {
  employee_id: string;
  employee_name: string;
  role: string;
  store_name: string;
  current_points: number;
}

interface PointRecord {
  id: string;
  date: string;
  type: 'earn' | 'consume';
  points: number;
  reason: string;
  operator: string;
}

interface PointsTrend {
  date: string;
  balance: number;
}

interface DetailResp {
  employee: EmployeeInfo;
  records: { items: PointRecord[]; total: number };
  trend: PointsTrend[];
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function PerformancePointDetail() {
  const { employee_id } = useParams<{ employee_id: string }>();
  const actionRef = useRef<ActionType>(null);
  const [employee, setEmployee] = useState<EmployeeInfo | null>(null);
  const [trend, setTrend] = useState<PointsTrend[]>([]);

  useEffect(() => {
    if (!employee_id) return;
    (async () => {
      try {
        const res = await txFetch(`/api/v1/points/detail/${employee_id}?page=1&size=1`) as {
          ok: boolean;
          data: DetailResp;
        };
        if (res.ok) {
          setEmployee(res.data.employee);
          setTrend(res.data.trend ?? []);
        }
      } catch { /* empty */ }
    })();
  }, [employee_id]);

  const columns: ProColumns<PointRecord>[] = [
    { title: '日期', dataIndex: 'date', width: 120, hideInSearch: true },
    {
      title: '类型',
      dataIndex: 'type',
      width: 80,
      valueEnum: { earn: { text: '获取' }, consume: { text: '消耗' } },
      render: (_, r) => (
        <Tag color={r.type === 'earn' ? 'success' : 'error'}>
          {r.type === 'earn' ? '获取' : '消耗'}
        </Tag>
      ),
    },
    {
      title: '分数',
      dataIndex: 'points',
      width: 80,
      hideInSearch: true,
      render: (_, r) => (
        <span style={{ color: r.type === 'earn' ? '#52c41a' : '#ff4d4f', fontWeight: 'bold' }}>
          {r.type === 'earn' ? '+' : '-'}{r.points}
        </span>
      ),
    },
    { title: '原因', dataIndex: 'reason', width: 200, hideInSearch: true },
    { title: '操作人', dataIndex: 'operator', width: 100, hideInSearch: true },
  ];

  const lineConfig = {
    data: trend,
    xField: 'date',
    yField: 'balance',
    smooth: true,
    color: TX_PRIMARY,
    point: { size: 3, shape: 'circle' },
    yAxis: { title: { text: '积分余额' } },
  };

  return (
    <div style={{ padding: 24 }}>
      <Title level={4}>积分流水</Title>

      {/* ── 员工信息卡 ── */}
      {employee && (
        <Card style={{ marginBottom: 24 }}>
          <Row gutter={24} align="middle">
            <Col span={6}>
              <Space>
                <UserOutlined style={{ fontSize: 24, color: TX_PRIMARY }} />
                <div>
                  <Text strong style={{ fontSize: 18 }}>{employee.employee_name}</Text>
                  <br />
                  <Text type="secondary">{employee.role} | {employee.store_name}</Text>
                </div>
              </Space>
            </Col>
            <Col span={6}>
              <Statistic
                title="当前积分余额"
                value={employee.current_points}
                prefix={<StarOutlined style={{ color: TX_PRIMARY }} />}
                valueStyle={{ color: TX_PRIMARY, fontWeight: 'bold' }}
              />
            </Col>
          </Row>
        </Card>
      )}

      {/* ── 趋势图 ── */}
      <Card title="积分趋势" style={{ marginBottom: 24 }}>
        <Line {...lineConfig} height={250} />
      </Card>

      {/* ── 流水表 ── */}
      <ProTable<PointRecord>
        headerTitle="积分流水记录"
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        search={{ labelWidth: 60 }}
        request={async (params) => {
          if (!employee_id) return { data: [], total: 0, success: true };
          const query = new URLSearchParams();
          if (params.type) query.set('type', params.type);
          query.set('page', String(params.current ?? 1));
          query.set('size', String(params.pageSize ?? 20));
          try {
            const res = await txFetch(`/api/v1/points/detail/${employee_id}?${query}`) as {
              ok: boolean;
              data: DetailResp;
            };
            if (res.ok) {
              setEmployee(res.data.employee);
              setTrend(res.data.trend ?? []);
              return {
                data: res.data.records?.items ?? [],
                total: res.data.records?.total ?? 0,
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
