/**
 * ScheduleConflicts — 排班冲突
 * 域F · 组织人事 · HR Admin
 *
 * 功能：
 *  - ProTable展示冲突列表（员工/日期/冲突班次A/冲突班次B）
 *  - 操作列：取消其一/调整
 *  - 顶部统计：本周冲突总数
 *
 * API: GET /api/v1/schedules/conflicts?store_id=&start_date=&end_date=
 */

import { useRef, useState } from 'react';
import { Button, Card, Col, Popconfirm, Row, Space, Statistic, Tag, Typography, message } from 'antd';
import { ExclamationCircleOutlined, DeleteOutlined, EditOutlined } from '@ant-design/icons';
import { ActionType, ProColumns, ProTable } from '@ant-design/pro-components';
import { txFetchData } from '../../../api';

const { Title } = Typography;

// ─── Types ───────────────────────────────────────────────────────────────────

interface ConflictItem {
  id: string;
  employee_id: string;
  employee_name: string;
  date: string;
  shift_a_id: string;
  shift_a_type: string;
  shift_a_time: string;
  shift_b_id: string;
  shift_b_type: string;
  shift_b_time: string;
  store_name: string;
}

interface ConflictsResp {
  items: ConflictItem[];
  total: number;
  week_total: number;
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function ScheduleConflicts() {
  const actionRef = useRef<ActionType>(null);
  const [weekTotal, setWeekTotal] = useState(0);
  const [messageApi, contextHolder] = message.useMessage();

  const handleCancelShift = async (shiftId: string) => {
    try {
      const res = await txFetchData(`/api/v1/schedules/${shiftId}`, {
        method: 'DELETE',
      }) as { ok: boolean };
      if (res.ok) {
        messageApi.success('班次已取消');
        actionRef.current?.reload();
      }
    } catch {
      messageApi.error('取消失败');
    }
  };

  const columns: ProColumns<ConflictItem>[] = [
    { title: '员工', dataIndex: 'employee_name', width: 100 },
    { title: '门店', dataIndex: 'store_name', width: 140, hideInSearch: true },
    { title: '日期', dataIndex: 'date', width: 120, hideInSearch: true },
    {
      title: '冲突班次A',
      key: 'shift_a',
      width: 180,
      hideInSearch: true,
      render: (_, r) => (
        <Tag color="error">{r.shift_a_type} {r.shift_a_time}</Tag>
      ),
    },
    {
      title: '冲突班次B',
      key: 'shift_b',
      width: 180,
      hideInSearch: true,
      render: (_, r) => (
        <Tag color="error">{r.shift_b_type} {r.shift_b_time}</Tag>
      ),
    },
    {
      title: '门店',
      dataIndex: 'store_id',
      hideInTable: true,
    },
    {
      title: '开始日期',
      dataIndex: 'start_date',
      valueType: 'date',
      hideInTable: true,
    },
    {
      title: '结束日期',
      dataIndex: 'end_date',
      valueType: 'date',
      hideInTable: true,
    },
    {
      title: '操作',
      key: 'action',
      width: 200,
      hideInSearch: true,
      render: (_, r) => (
        <Space>
          <Popconfirm title="取消班次A？" onConfirm={() => handleCancelShift(r.shift_a_id)}>
            <Button type="link" size="small" icon={<DeleteOutlined />} danger>
              取消A
            </Button>
          </Popconfirm>
          <Popconfirm title="取消班次B？" onConfirm={() => handleCancelShift(r.shift_b_id)}>
            <Button type="link" size="small" icon={<DeleteOutlined />} danger>
              取消B
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      {contextHolder}
      <Title level={4}>排班冲突</Title>

      {/* ── 统计 ── */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="本周冲突总数"
              value={weekTotal}
              prefix={<ExclamationCircleOutlined style={{ color: weekTotal > 0 ? '#ff4d4f' : '#52c41a' }} />}
              valueStyle={weekTotal > 0 ? { color: '#ff4d4f' } : { color: '#52c41a' }}
            />
          </Card>
        </Col>
      </Row>

      <ProTable<ConflictItem>
        headerTitle="冲突列表"
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        search={{ labelWidth: 80 }}
        request={async (params) => {
          const query = new URLSearchParams();
          if (params.store_id) query.set('store_id', params.store_id);
          if (params.start_date) query.set('start_date', params.start_date);
          if (params.end_date) query.set('end_date', params.end_date);
          query.set('page', String(params.current ?? 1));
          query.set('size', String(params.pageSize ?? 20));
          try {
            const res = await txFetchData(`/api/v1/schedules/conflicts?${query}`) as {
              ok: boolean;
              data: ConflictsResp;
            };
            if (res.ok) {
              setWeekTotal(res.data.week_total ?? 0);
              return { data: res.data.items, total: res.data.total, success: true };
            }
          } catch { /* fallback */ }
          return { data: [], total: 0, success: true };
        }}
        pagination={{ defaultPageSize: 20 }}
      />
    </div>
  );
}
