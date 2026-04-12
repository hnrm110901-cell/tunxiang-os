/**
 * LeaveBalances — 假期余额
 * 域F · 组织人事 · 请假管理
 *
 * 功能：
 *  1. ProTable展示每个员工的假期余额（年假/事假/病假/调休各类余额）
 *  2. 余额为0红色标记
 *
 * API:
 *  GET /api/v1/leave-requests/balance?store_id=xxx
 */

import { useEffect, useRef, useState } from 'react';
import {
  Card,
  Col,
  message,
  Row,
  Select,
  Typography,
} from 'antd';
import { ProTable } from '@ant-design/pro-components';
import type { ActionType, ProColumns } from '@ant-design/pro-components';
import { WalletOutlined } from '@ant-design/icons';
import { txFetchData } from '../../../api';

const { Title } = Typography;
const TX_PRIMARY = '#FF6B35';
const TX_SUCCESS = '#0F6E56';
const TX_DANGER  = '#A32D2D';

// ─── Types ───────────────────────────────────────────────────────────────────

interface LeaveBalance {
  employee_id: string;
  employee_name: string;
  annual_total: number;
  annual_used: number;
  annual_remaining: number;
  personal_total: number;
  personal_used: number;
  personal_remaining: number;
  sick_total: number;
  sick_used: number;
  sick_remaining: number;
  compensatory_total: number;
  compensatory_used: number;
  compensatory_remaining: number;
}

// ─── Helper ──────────────────────────────────────────────────────────────────

function balanceCell(remaining: number, total: number) {
  return (
    <span style={{ color: remaining === 0 ? TX_DANGER : TX_SUCCESS, fontWeight: 600 }}>
      {remaining}
      <span style={{ color: '#999', fontWeight: 400 }}>/{total}</span>
    </span>
  );
}

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export default function LeaveBalances() {
  const actionRef = useRef<ActionType>();
  const [storeId, setStoreId] = useState<string>('');
  const [stores, setStores] = useState<{ store_id: string; store_name: string }[]>([]);

  useEffect(() => {
    (async () => {
      try {
        const res = await txFetchData<{ store_id: string; store_name: string }[]>('/api/v1/org/stores');
        const list = res.data ?? [];
        setStores(list);
        if (list.length > 0) setStoreId(list[0].store_id);
      } catch {
        message.error('加载门店列表失败');
      }
    })();
  }, []);

  useEffect(() => {
    actionRef.current?.reload();
  }, [storeId]);

  const columns: ProColumns<LeaveBalance>[] = [
    { title: '员工', dataIndex: 'employee_name', width: 100, fixed: 'left' },
    {
      title: '年假（剩余/总）',
      width: 120,
      render: (_, r) => balanceCell(r.annual_remaining, r.annual_total),
    },
    {
      title: '事假（剩余/总）',
      width: 120,
      render: (_, r) => balanceCell(r.personal_remaining, r.personal_total),
    },
    {
      title: '病假（剩余/总）',
      width: 120,
      render: (_, r) => balanceCell(r.sick_remaining, r.sick_total),
    },
    {
      title: '调休（剩余/总）',
      width: 120,
      render: (_, r) => balanceCell(r.compensatory_remaining, r.compensatory_total),
    },
    {
      title: '年假已用',
      dataIndex: 'annual_used',
      width: 80,
      hideInTable: true,
    },
    {
      title: '事假已用',
      dataIndex: 'personal_used',
      width: 80,
      hideInTable: true,
    },
    {
      title: '病假已用',
      dataIndex: 'sick_used',
      width: 80,
      hideInTable: true,
    },
    {
      title: '调休已用',
      dataIndex: 'compensatory_used',
      width: 80,
      hideInTable: true,
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>
            <WalletOutlined style={{ color: TX_PRIMARY, marginRight: 8 }} />
            假期余额
          </Title>
        </Col>
        <Col>
          <Select
            value={storeId}
            onChange={setStoreId}
            style={{ width: 200 }}
            placeholder="选择门店"
            options={stores.map((s) => ({ label: s.store_name, value: s.store_id }))}
          />
        </Col>
      </Row>

      <Card>
        <ProTable<LeaveBalance>
          actionRef={actionRef}
          columns={columns}
          request={async () => {
            if (!storeId) return { data: [], total: 0, success: true };
            const res = await txFetchData<{ items: LeaveBalance[]; total: number }>(
              `/api/v1/leave-requests/balance?store_id=${storeId}`,
            );
            return {
              data: res.data?.items ?? [],
              total: res.data?.total ?? 0,
              success: true,
            };
          }}
          rowKey="employee_id"
          search={false}
          options={{ reload: true }}
          pagination={{ pageSize: 20 }}
          scroll={{ x: 600 }}
        />
      </Card>
    </div>
  );
}
