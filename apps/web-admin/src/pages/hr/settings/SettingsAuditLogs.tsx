/**
 * SettingsAuditLogs — 审计日志
 * 域F · 配置中心
 *
 * 功能：
 *  1. ProTable审计日志（时间/操作人/模块/操作/详情）
 *  2. 日期范围 + 模块筛选
 *
 * API:
 *  GET /api/v1/audit-logs?page=&size=&module=&start_date=&end_date=&operator=
 */

import { useRef } from 'react';
import { Tag, Typography } from 'antd';
import { AuditOutlined } from '@ant-design/icons';
import {
  ActionType,
  ProColumns,
  ProTable,
} from '@ant-design/pro-components';
import { txFetchData } from '../../../api';

const { Title } = Typography;

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface AuditLog {
  id: string;
  operator_id: string;
  operator_name: string;
  module: string;
  action: string;
  detail: string;
  ip_address: string;
  created_at: string;
}

interface AuditLogListResp {
  items: AuditLog[];
  total: number;
}

// ─── 枚举 ────────────────────────────────────────────────────────────────────

const moduleMap: Record<string, { text: string; color: string }> = {
  employee: { text: '员工管理', color: 'blue' },
  attendance: { text: '考勤', color: 'green' },
  schedule: { text: '排班', color: 'cyan' },
  leave: { text: '请假', color: 'purple' },
  payroll: { text: '薪资', color: 'gold' },
  performance: { text: '绩效', color: 'orange' },
  compliance: { text: '合规', color: 'red' },
  agent: { text: 'Agent', color: 'geekblue' },
  role: { text: '角色权限', color: 'default' },
  approval: { text: '审批流', color: 'lime' },
  system: { text: '系统', color: 'default' },
};

const actionColorMap: Record<string, string> = {
  create: 'green',
  update: 'blue',
  delete: 'red',
  login: 'cyan',
  export: 'purple',
  approve: 'gold',
  reject: 'orange',
};

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function SettingsAuditLogs() {
  const actionRef = useRef<ActionType>();

  const columns: ProColumns<AuditLog>[] = [
    {
      title: '时间',
      dataIndex: 'created_at',
      valueType: 'dateTime',
      width: 170,
      hideInSearch: true,
      sorter: true,
      defaultSortOrder: 'descend',
    },
    {
      title: '日期范围',
      dataIndex: 'dateRange',
      valueType: 'dateRange',
      hideInTable: true,
      fieldProps: {
        placeholder: ['开始日期', '结束日期'],
      },
    },
    {
      title: '操作人',
      dataIndex: 'operator_name',
      width: 100,
      fieldProps: { placeholder: '姓名搜索' },
    },
    {
      title: '模块',
      dataIndex: 'module',
      width: 100,
      valueType: 'select',
      valueEnum: Object.fromEntries(
        Object.entries(moduleMap).map(([k, v]) => [k, { text: v.text }]),
      ),
      render: (_, r) => {
        const m = moduleMap[r.module] || { text: r.module, color: 'default' };
        return <Tag color={m.color}>{m.text}</Tag>;
      },
    },
    {
      title: '操作',
      dataIndex: 'action',
      width: 80,
      hideInSearch: true,
      render: (_, r) => (
        <Tag color={actionColorMap[r.action] || 'default'}>{r.action}</Tag>
      ),
    },
    {
      title: '详情',
      dataIndex: 'detail',
      hideInSearch: true,
      ellipsis: true,
    },
    {
      title: 'IP',
      dataIndex: 'ip_address',
      hideInSearch: true,
      width: 130,
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Title level={4}>
        <AuditOutlined style={{ marginRight: 8 }} />
        审计日志
      </Title>

      <ProTable<AuditLog>
        actionRef={actionRef}
        columns={columns}
        rowKey="id"
        request={async (params, sorter) => {
          const query = new URLSearchParams();
          query.set('page', String(params.current || 1));
          query.set('size', String(params.pageSize || 20));
          if (params.module) query.set('module', params.module);
          if (params.operator_name) query.set('operator', params.operator_name);
          if (params.dateRange) {
            const [start, end] = params.dateRange;
            if (start) query.set('start_date', start);
            if (end) query.set('end_date', end);
          }
          if (sorter?.created_at) {
            query.set('sort', sorter.created_at === 'ascend' ? 'asc' : 'desc');
          }
          try {
            const data = await txFetchData<AuditLogListResp>(
              `/api/v1/audit-logs?${query.toString()}`,
            );
            return { data: data.items || [], total: data.total || 0, success: true };
          } catch {
            return { data: [], total: 0, success: true };
          }
        }}
        search={{ labelWidth: 'auto' }}
        pagination={{ defaultPageSize: 20, showSizeChanger: true }}
        dateFormatter="string"
      />
    </div>
  );
}
