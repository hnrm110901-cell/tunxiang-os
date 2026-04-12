/**
 * ComplianceDocExpiring — 证照到期
 * Sprint 5 · 合规中心
 *
 * API: GET /api/v1/employee-documents/expiring
 */

import { useRef, useState } from 'react';
import { Button, Space, Tag, message } from 'antd';
import { ActionType, ProColumns, ProTable } from '@ant-design/pro-components';
import { NotificationOutlined } from '@ant-design/icons';
import { txFetchData } from '../../../api';

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface ExpiringDoc {
  id: string;
  employee_id: string;
  employee_name: string;
  doc_type: string;
  expiry_date: string;
  days_remaining: number;
  store_name: string;
}

// ─── 工具 ────────────────────────────────────────────────────────────────────

function daysTag(days: number) {
  if (days < 0)
    return (
      <Tag color="red" style={{ animation: 'pulse 1.5s infinite' }}>
        已过期 {Math.abs(days)}天
      </Tag>
    );
  if (days < 7) return <Tag color="red">{days}天</Tag>;
  if (days < 15) return <Tag color="orange">{days}天</Tag>;
  if (days < 30) return <Tag color="gold">{days}天</Tag>;
  return <Tag color="green">{days}天</Tag>;
}

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function ComplianceDocExpiring() {
  const actionRef = useRef<ActionType>();
  const [activeTab, setActiveTab] = useState<string>('7');

  const columns: ProColumns<ExpiringDoc>[] = [
    { title: '员工', dataIndex: 'employee_name', width: 100 },
    { title: '证照类型', dataIndex: 'doc_type', width: 120 },
    { title: '到期日期', dataIndex: 'expiry_date', valueType: 'date', width: 120 },
    {
      title: '剩余天数',
      dataIndex: 'days_remaining',
      width: 120,
      sorter: true,
      render: (_, r) => daysTag(r.days_remaining),
    },
    { title: '门店', dataIndex: 'store_name', width: 140 },
    {
      title: '操作',
      valueType: 'option',
      width: 160,
      render: (_, r) => (
        <Space size="small">
          <a onClick={() => message.info(`通知 ${r.employee_name} 更新证照`)}>
            <NotificationOutlined /> 通知员工
          </a>
          <a onClick={() => message.info(`更新 ${r.employee_name} 的证照信息`)}>
            更新证照
          </a>
        </Space>
      ),
    },
  ];

  return (
    <>
      <ProTable<ExpiringDoc>
        headerTitle="证照到期预警"
        actionRef={actionRef}
        columns={columns}
        rowKey="id"
        search={false}
        pagination={{ defaultPageSize: 20 }}
        toolbar={{
          menu: {
            type: 'tab',
            activeKey: activeTab,
            items: [
              { key: '7', label: '7天内到期' },
              { key: '15', label: '15天内到期' },
              { key: '30', label: '30天内到期' },
            ],
            onChange: (key) => {
              setActiveTab(key as string);
              actionRef.current?.reload();
            },
          },
        }}
        request={async (params) => {
          const query = new URLSearchParams();
          if (params.current) query.set('page', String(params.current));
          if (params.pageSize) query.set('size', String(params.pageSize));
          query.set('days', activeTab);
          const resp = await txFetchData<{ items: ExpiringDoc[]; total: number }>(
            `/api/v1/employee-documents/expiring?${query.toString()}`,
          );
          const d = resp.data;
          return { data: d?.items ?? [], total: d?.total ?? 0, success: resp.ok };
        }}
      />

      <style>{`
        @keyframes pulse {
          0% { opacity: 1; }
          50% { opacity: 0.3; }
          100% { opacity: 1; }
        }
      `}</style>
    </>
  );
}
