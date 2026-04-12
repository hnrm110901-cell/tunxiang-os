/**
 * PerformancePoints — 积分管理
 * 域F · 组织人事 · HR Admin
 *
 * 功能：
 *  - 积分排行榜ProTable（排名/姓名/总积分/本月获取/本月消耗）
 *  - 发放积分ModalForm（选员工+分数+原因）
 *  - 扣减积分ModalForm
 *
 * API: GET  /api/v1/points/leaderboard?store_id=
 *      POST /api/v1/points/award
 */

import { useRef } from 'react';
import { Button, Space, Tag, Typography, message } from 'antd';
import { PlusOutlined, MinusOutlined, TrophyOutlined } from '@ant-design/icons';
import {
  ActionType,
  ModalForm,
  ProColumns,
  ProFormDigit,
  ProFormSelect,
  ProFormTextArea,
  ProTable,
} from '@ant-design/pro-components';
import { txFetchData } from '../../../api';

const { Title } = Typography;
const TX_PRIMARY = '#FF6B35';

// ─── Types ───────────────────────────────────────────────────────────────────

interface PointsItem {
  id: string;
  rank: number;
  employee_id: string;
  employee_name: string;
  total_points: number;
  month_earned: number;
  month_consumed: number;
  store_name: string;
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function PerformancePoints() {
  const actionRef = useRef<ActionType>(null);
  const [messageApi, contextHolder] = message.useMessage();

  const handleAward = async (values: Record<string, unknown>, type: 'award' | 'deduct') => {
    try {
      const res = await txFetchData('/api/v1/points/award', {
        method: 'POST',
        body: JSON.stringify({ ...values, type }),
      }) as { ok: boolean };
      if (res.ok) {
        messageApi.success(type === 'award' ? '积分发放成功' : '积分扣减成功');
        actionRef.current?.reload();
        return true;
      }
      messageApi.error('操作失败');
    } catch {
      messageApi.error('操作失败');
    }
    return false;
  };

  const columns: ProColumns<PointsItem>[] = [
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
              <TrophyOutlined /> {r.rank}
            </Tag>
          );
        }
        return r.rank;
      },
    },
    { title: '姓名', dataIndex: 'employee_name', width: 100 },
    { title: '门店', dataIndex: 'store_name', width: 140, hideInSearch: true },
    {
      title: '总积分',
      dataIndex: 'total_points',
      width: 100,
      hideInSearch: true,
      render: (_, r) => (
        <span style={{ fontWeight: 'bold', color: TX_PRIMARY }}>{r.total_points}</span>
      ),
    },
    {
      title: '本月获取',
      dataIndex: 'month_earned',
      width: 100,
      hideInSearch: true,
      render: (_, r) => <span style={{ color: '#52c41a' }}>+{r.month_earned}</span>,
    },
    {
      title: '本月消耗',
      dataIndex: 'month_consumed',
      width: 100,
      hideInSearch: true,
      render: (_, r) => <span style={{ color: '#ff4d4f' }}>-{r.month_consumed}</span>,
    },
    {
      title: '门店',
      dataIndex: 'store_id',
      hideInTable: true,
    },
  ];

  const employeeRequest = async () => {
    try {
      const res = await txFetchData('/api/v1/org/employees?page=1&size=200') as {
        ok: boolean;
        data: { items: { id: string; name: string }[] };
      };
      if (res.ok) return res.data.items.map((e) => ({ label: e.name, value: e.id }));
    } catch { /* empty */ }
    return [];
  };

  return (
    <div style={{ padding: 24 }}>
      {contextHolder}
      <Title level={4}>积分管理</Title>

      <ProTable<PointsItem>
        headerTitle="积分排行榜"
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        search={{ labelWidth: 80 }}
        toolBarRender={() => [
          <ModalForm
            key="award"
            title="发放积分"
            trigger={
              <Button
                type="primary"
                icon={<PlusOutlined />}
                style={{ backgroundColor: TX_PRIMARY, borderColor: TX_PRIMARY }}
              >
                发放积分
              </Button>
            }
            onFinish={(v) => handleAward(v, 'award')}
            modalProps={{ destroyOnClose: true }}
          >
            <ProFormSelect name="employee_id" label="员工" rules={[{ required: true }]} request={employeeRequest} />
            <ProFormDigit name="points" label="积分" min={1} max={10000} rules={[{ required: true }]} />
            <ProFormTextArea name="reason" label="原因" rules={[{ required: true }]} />
          </ModalForm>,
          <ModalForm
            key="deduct"
            title="扣减积分"
            trigger={
              <Button icon={<MinusOutlined />}>扣减积分</Button>
            }
            onFinish={(v) => handleAward(v, 'deduct')}
            modalProps={{ destroyOnClose: true }}
          >
            <ProFormSelect name="employee_id" label="员工" rules={[{ required: true }]} request={employeeRequest} />
            <ProFormDigit name="points" label="积分" min={1} max={10000} rules={[{ required: true }]} />
            <ProFormTextArea name="reason" label="原因" rules={[{ required: true }]} />
          </ModalForm>,
        ]}
        request={async (params) => {
          const query = new URLSearchParams();
          if (params.store_id) query.set('store_id', params.store_id);
          query.set('page', String(params.current ?? 1));
          query.set('size', String(params.pageSize ?? 20));
          try {
            const res = await txFetchData(`/api/v1/points/leaderboard?${query}`) as {
              ok: boolean;
              data: { items: PointsItem[]; total: number };
            };
            if (res.ok) {
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
