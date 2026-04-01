/**
 * AlertListTable — 预警列表表格
 *
 * 用于预警中心页。支持：
 * - 严重级 + 类型 + 状态筛选
 * - 批量操作（指派/忽略/生成任务）
 * - 点击展开 Agent 解释
 *
 * Admin 终端：使用 ProTable
 */
import { useRef } from 'react';
import { ProTable, ActionType, ProColumns } from '@ant-design/pro-components';
import { Tag, Button, Space, Popconfirm, Tooltip } from 'antd';
import {
  SendOutlined,
  CheckOutlined,
  DeleteOutlined,
  FileAddOutlined,
  EyeOutlined,
} from '@ant-design/icons';

export interface AlertItem {
  id: string;
  severity: 'P1' | 'P2' | 'P3';
  type: string;
  storeName: string;
  storeId: string;
  metric: string;
  value: string;
  threshold: string;
  firstSeenAt: string;
  status: 'pending' | 'processing' | 'resolved' | 'ignored';
  assignee?: string;
  agentSuggestion?: string;
}

export interface AlertListTableProps {
  onViewDetail: (alert: AlertItem) => void;
  onAssign: (alertIds: string[], assignee: string) => void;
  onCreateTask: (alertIds: string[]) => void;
  onIgnore: (alertIds: string[], reason: string) => void;
  request: (params: any) => Promise<{ data: AlertItem[]; total: number }>;
}

const severityEnum = {
  P1: { text: 'P1 严重', status: 'Error' },
  P2: { text: 'P2 警告', status: 'Warning' },
  P3: { text: 'P3 提示', status: 'Processing' },
};

const statusEnum = {
  pending: { text: '待处理', status: 'Error' },
  processing: { text: '处理中', status: 'Warning' },
  resolved: { text: '已闭环', status: 'Success' },
  ignored: { text: '已忽略', status: 'Default' },
};

export function AlertListTable({
  onViewDetail,
  onAssign,
  onCreateTask,
  onIgnore,
  request,
}: AlertListTableProps) {
  const actionRef = useRef<ActionType>();

  const columns: ProColumns<AlertItem>[] = [
    {
      title: '严重级',
      dataIndex: 'severity',
      valueType: 'select',
      valueEnum: severityEnum,
      width: 100,
      render: (_, r) => (
        <Tag color={r.severity === 'P1' ? 'red' : r.severity === 'P2' ? 'orange' : 'blue'}>
          {r.severity}
        </Tag>
      ),
    },
    { title: '门店', dataIndex: 'storeName', width: 120 },
    { title: '类型', dataIndex: 'type', width: 100, valueType: 'select',
      valueEnum: {
        operation: '经营', service: '服务', kitchen: '厨房',
        payment: '支付', member: '会员', risk: '风险',
      },
    },
    { title: '异常指标', dataIndex: 'metric', width: 120 },
    { title: '当前值', dataIndex: 'value', width: 100, search: false },
    { title: '阈值', dataIndex: 'threshold', width: 100, search: false },
    { title: '首次发现', dataIndex: 'firstSeenAt', valueType: 'dateTime', width: 160, search: false },
    {
      title: '状态',
      dataIndex: 'status',
      valueType: 'select',
      valueEnum: statusEnum,
      width: 100,
    },
    { title: '责任人', dataIndex: 'assignee', width: 100, search: false },
    {
      title: '操作',
      valueType: 'option',
      width: 160,
      render: (_, record) => (
        <Space size={4}>
          <Tooltip title="查看详情">
            <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => onViewDetail(record)} />
          </Tooltip>
          <Tooltip title="生成任务">
            <Button type="link" size="small" icon={<FileAddOutlined />} onClick={() => onCreateTask([record.id])} />
          </Tooltip>
          <Tooltip title="标记忽略">
            <Popconfirm title="确认忽略此预警？" onConfirm={() => onIgnore([record.id], '')}>
              <Button type="link" size="small" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          </Tooltip>
        </Space>
      ),
    },
  ];

  return (
    <ProTable<AlertItem>
      columns={columns}
      actionRef={actionRef}
      request={async (params) => {
        const res = await request(params);
        return { data: res.data, total: res.total, success: true };
      }}
      rowKey="id"
      search={{ labelWidth: 'auto' }}
      rowSelection={{}}
      tableAlertOptionRender={({ selectedRowKeys, onCleanSelected }) => (
        <Space>
          <Button size="small" icon={<SendOutlined />} onClick={() => onAssign(selectedRowKeys as string[], '')}>
            批量指派
          </Button>
          <Button size="small" icon={<FileAddOutlined />} onClick={() => onCreateTask(selectedRowKeys as string[])}>
            批量建任务
          </Button>
          <Button size="small" danger icon={<DeleteOutlined />} onClick={() => onIgnore(selectedRowKeys as string[], '')}>
            批量忽略
          </Button>
          <Button size="small" type="link" onClick={onCleanSelected}>取消选择</Button>
        </Space>
      )}
      pagination={{ defaultPageSize: 20, showSizeChanger: true }}
    />
  );
}
