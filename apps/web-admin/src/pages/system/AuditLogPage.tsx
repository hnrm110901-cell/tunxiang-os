/**
 * AuditLogPage -- 审计日志查询
 * 域F . 系统设置 . 审计日志
 *
 * ProTable：时间/操作人/操作类型/资源类型/资源ID/IP/变更详情
 * 展开行显示 JSON diff（old->new，变化字段高亮）
 * 筛选：操作人+操作类型+资源类型+日期范围
 * 导出 CSV
 *
 * API: gateway :8000, try/catch 降级 Mock
 */

import { useRef, useState } from 'react';
import {
  Button,
  DatePicker,
  Space,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import {
  DownloadOutlined,
  FileTextOutlined,
} from '@ant-design/icons';
import {
  ActionType,
  ProColumns,
  ProTable,
} from '@ant-design/pro-components';
import dayjs from 'dayjs';

const { Text } = Typography;
const { RangePicker } = DatePicker;

const BASE = 'http://localhost:8000';

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Types
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

type AuditAction = 'create' | 'update' | 'delete' | 'login' | 'export' | 'approve';

interface AuditLog {
  id: string;
  timestamp: string;
  user_name: string;
  user_id: string;
  action: AuditAction;
  resource_type: string;
  resource_id: string;
  ip_address: string;
  old_data: Record<string, unknown> | null;
  new_data: Record<string, unknown> | null;
  description: string;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Constants
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const ACTION_CONFIG: Record<AuditAction, { color: string; label: string }> = {
  create: { color: 'green', label: '创建' },
  update: { color: 'blue', label: '更新' },
  delete: { color: 'red', label: '删除' },
  login: { color: 'default', label: '登录' },
  export: { color: 'purple', label: '导出' },
  approve: { color: 'orange', label: '审批' },
};

const RESOURCE_TYPES = [
  { value: 'order', label: '订单' },
  { value: 'dish', label: '菜品' },
  { value: 'member', label: '会员' },
  { value: 'employee', label: '员工' },
  { value: 'store', label: '门店' },
  { value: 'dictionary', label: '字典' },
  { value: 'role', label: '角色' },
  { value: 'system', label: '系统' },
];

// Mock Data 已移除，由 API 提供数据

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Helpers
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function renderJsonDiff(
  oldData: Record<string, unknown> | null,
  newData: Record<string, unknown> | null,
): React.ReactNode {
  if (!oldData && !newData) {
    return <Text type="secondary">无变更数据</Text>;
  }

  const allKeys = new Set([
    ...Object.keys(oldData ?? {}),
    ...Object.keys(newData ?? {}),
  ]);

  return (
    <div
      style={{
        fontFamily: 'monospace',
        fontSize: 13,
        background: '#fafafa',
        borderRadius: 6,
        padding: '12px 16px',
        lineHeight: 1.8,
      }}
    >
      {[...allKeys].map((key) => {
        const oldVal = oldData?.[key];
        const newVal = newData?.[key];
        const changed = JSON.stringify(oldVal) !== JSON.stringify(newVal);

        if (!oldData) {
          // create: all new
          return (
            <div key={key} style={{ color: '#389e0d' }}>
              + {key}: {JSON.stringify(newVal)}
            </div>
          );
        }
        if (!newData) {
          // delete: all old
          return (
            <div key={key} style={{ color: '#cf1322' }}>
              - {key}: {JSON.stringify(oldVal)}
            </div>
          );
        }
        if (changed) {
          return (
            <div key={key}>
              <div style={{ color: '#cf1322', background: '#fff1f0', padding: '0 4px', borderRadius: 2 }}>
                - {key}: {JSON.stringify(oldVal)}
              </div>
              <div style={{ color: '#389e0d', background: '#f6ffed', padding: '0 4px', borderRadius: 2 }}>
                + {key}: {JSON.stringify(newVal)}
              </div>
            </div>
          );
        }
        return (
          <div key={key} style={{ color: '#8c8c8c' }}>
            &nbsp; {key}: {JSON.stringify(oldVal)}
          </div>
        );
      })}
    </div>
  );
}


// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// API
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async function fetchAuditLogs(params: {
  current?: number;
  pageSize?: number;
  user_name?: string;
  action?: string;
  resource_type?: string;
  start_date?: string;
  end_date?: string;
}): Promise<{ data: AuditLog[]; total: number; success: boolean }> {
  const tenantId = localStorage.getItem('tx_tenant_id') ?? '';
  const query = new URLSearchParams();
  if (params.current) query.set('page', String(params.current));
  if (params.pageSize) query.set('size', String(params.pageSize));
  if (params.user_name) query.set('operator', params.user_name);
  if (params.action) query.set('action', params.action);
  if (params.resource_type) query.set('resource_type', params.resource_type);
  if (params.start_date) query.set('start', params.start_date);
  if (params.end_date) query.set('end', params.end_date);

  try {
    const res = await fetch(`${BASE}/api/v1/system/audit-logs?${query}`, {
      headers: { 'X-Tenant-ID': tenantId },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    if (json.ok) {
      return { data: json.data.items, total: json.data.total, success: true };
    }
  } catch { /* API 不可用时返回空数据 */ }

  return { data: [], total: 0, success: true };
}

async function exportAuditLogsCSV(params: {
  user_name?: string;
  action?: string;
  resource_type?: string;
  start_date?: string;
  end_date?: string;
}): Promise<void> {
  const tenantId = localStorage.getItem('tx_tenant_id') ?? '';
  const query = new URLSearchParams({ format: 'csv' });
  if (params.user_name) query.set('operator', params.user_name);
  if (params.action) query.set('action', params.action);
  if (params.resource_type) query.set('resource_type', params.resource_type);
  if (params.start_date) query.set('start', params.start_date);
  if (params.end_date) query.set('end', params.end_date);

  try {
    const res = await fetch(`${BASE}/api/v1/system/audit-logs/export?${query}`, {
      headers: { 'X-Tenant-ID': tenantId },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `audit-logs-${dayjs().format('YYYY-MM-DD')}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    message.success('审计日志已导出');
  } catch {
    message.error('导出失败，请稍后重试');
  }
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Component
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

export function AuditLogPage() {
  const tableRef = useRef<ActionType>();
  const [lastParams, setLastParams] = useState<Parameters<typeof fetchAuditLogs>[0]>({});

  const columns: ProColumns<AuditLog>[] = [
    {
      title: '时间',
      dataIndex: 'timestamp',
      width: 170,
      sorter: (a, b) => dayjs(a.timestamp).unix() - dayjs(b.timestamp).unix(),
      defaultSortOrder: 'descend',
      search: false,
    },
    {
      title: '操作人',
      dataIndex: 'user_name',
      width: 100,
      fieldProps: { placeholder: '搜索操作人' },
    },
    {
      title: '操作类型',
      dataIndex: 'action',
      width: 90,
      valueType: 'select',
      valueEnum: Object.fromEntries(
        Object.entries(ACTION_CONFIG).map(([k, v]) => [k, { text: v.label }]),
      ),
      render: (_, record) => {
        const cfg = ACTION_CONFIG[record.action];
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
    {
      title: '资源类型',
      dataIndex: 'resource_type',
      width: 100,
      valueType: 'select',
      valueEnum: Object.fromEntries(
        RESOURCE_TYPES.map((rt) => [rt.value, { text: rt.label }]),
      ),
    },
    {
      title: '资源ID',
      dataIndex: 'resource_id',
      width: 120,
      copyable: true,
      search: false,
    },
    {
      title: 'IP地址',
      dataIndex: 'ip_address',
      width: 130,
      search: false,
    },
    {
      title: '描述',
      dataIndex: 'description',
      ellipsis: true,
      search: false,
    },
    {
      title: '日期范围',
      dataIndex: 'date_range',
      valueType: 'dateRange',
      hideInTable: true,
      search: {
        transform: (value) => ({
          start_date: value[0],
          end_date: value[1],
        }),
      },
    },
  ];

  return (
    <ProTable<AuditLog>
      actionRef={tableRef}
      rowKey="id"
      columns={columns}
      headerTitle={
        <Space>
          <FileTextOutlined />
          <span>审计日志</span>
        </Space>
      }
      request={async (params) => {
        const p = {
          current: params.current,
          pageSize: params.pageSize,
          user_name: params.user_name,
          action: params.action,
          resource_type: params.resource_type,
          start_date: params.start_date,
          end_date: params.end_date,
        };
        setLastParams(p);
        return fetchAuditLogs(p);
      }}
      pagination={{
        defaultPageSize: 20,
        showSizeChanger: true,
        showTotal: (total) => `共 ${total} 条`,
      }}
      search={{
        labelWidth: 'auto',
        defaultCollapsed: false,
      }}
      expandable={{
        expandedRowRender: (record) => (
          <div style={{ padding: '8px 0' }}>
            <Text strong style={{ marginBottom: 8, display: 'block' }}>
              变更详情
            </Text>
            {renderJsonDiff(record.old_data, record.new_data)}
          </div>
        ),
        rowExpandable: (record) => !!(record.old_data || record.new_data),
      }}
      toolBarRender={() => [
        <Button
          key="export"
          icon={<DownloadOutlined />}
          onClick={() => exportAuditLogsCSV(lastParams)}
        >
          导出 CSV
        </Button>,
      ]}
      options={{ density: true }}
    />
  );
}
