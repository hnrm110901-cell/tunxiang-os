/**
 * ComplianceAlerts — 预警列表
 * Sprint 5 · 合规中心
 *
 * API: GET  /api/v1/compliance/alerts?status=&alert_type=&severity=&store_id=
 *      POST /api/v1/compliance/alerts/{id}/acknowledge
 *      POST /api/v1/compliance/alerts/{id}/resolve
 */

import { useRef, useState } from 'react';
import { Space, Tag, message } from 'antd';
import {
  ActionType,
  ModalForm,
  ProColumns,
  ProFormTextArea,
  ProTable,
} from '@ant-design/pro-components';
import { txFetchData } from '../../../api';

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface AlertItem {
  id: string;
  title: string;
  alert_type: 'document' | 'attendance' | 'performance' | 'food_safety';
  severity: 'critical' | 'warning' | 'info';
  store_name: string;
  employee_name: string | null;
  status: 'open' | 'acknowledged' | 'resolved';
  created_at: string;
  due_date: string | null;
}

// ─── 枚举 ────────────────────────────────────────────────────────────────────

const severityTag: Record<string, { color: string; text: string }> = {
  critical: { color: 'red', text: '严重' },
  warning: { color: 'orange', text: '警告' },
  info: { color: 'blue', text: '提示' },
};

const statusTag: Record<string, { color: string; text: string }> = {
  open: { color: 'red', text: '待处理' },
  acknowledged: { color: 'orange', text: '已确认' },
  resolved: { color: 'green', text: '已解决' },
};

const typeLabel: Record<string, string> = {
  document: '证照',
  attendance: '考勤',
  performance: '绩效',
  food_safety: '食品安全',
};

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function ComplianceAlerts() {
  const actionRef = useRef<ActionType>();
  const [activeStatus, setActiveStatus] = useState<string>('all');
  const [actionAlertId, setActionAlertId] = useState<string | null>(null);
  const [actionType, setActionType] = useState<'acknowledge' | 'resolve'>('acknowledge');
  const [modalVisible, setModalVisible] = useState(false);

  const columns: ProColumns<AlertItem>[] = [
    {
      title: '标题',
      dataIndex: 'title',
      ellipsis: true,
      render: (_, r) => (
        <Space>
          {r.severity === 'critical' && (
            <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: '#A32D2D', animation: 'pulse 1.5s infinite' }} />
          )}
          {r.title}
        </Space>
      ),
    },
    {
      title: '类型',
      dataIndex: 'alert_type',
      valueType: 'select',
      valueEnum: {
        document: { text: '证照' },
        attendance: { text: '考勤' },
        performance: { text: '绩效' },
        food_safety: { text: '食品安全' },
      },
      render: (_, r) => typeLabel[r.alert_type] ?? r.alert_type,
      width: 90,
    },
    {
      title: '严重度',
      dataIndex: 'severity',
      valueType: 'select',
      valueEnum: {
        critical: { text: '严重', status: 'Error' },
        warning: { text: '警告', status: 'Warning' },
        info: { text: '提示', status: 'Processing' },
      },
      render: (_, r) => {
        const s = severityTag[r.severity];
        return <Tag color={s?.color}>{s?.text}</Tag>;
      },
      width: 80,
    },
    {
      title: '门店',
      dataIndex: 'store_id',
      hideInTable: true,
      valueType: 'select',
      fieldProps: { placeholder: '选择门店', showSearch: true },
      request: async () => {
        const resp = await txFetchData<{ items: { id: string; name: string }[] }>('/api/v1/stores');
        return (resp?.items ?? []).map((s) => ({ label: s.name, value: s.id }));
      },
    },
    { title: '门店', dataIndex: 'store_name', hideInSearch: true, width: 120 },
    { title: '员工', dataIndex: 'employee_name', hideInSearch: true, width: 80 },
    {
      title: '状态',
      dataIndex: 'status',
      hideInSearch: true,
      render: (_, r) => {
        const s = statusTag[r.status];
        return <Tag color={s?.color}>{s?.text}</Tag>;
      },
      width: 80,
    },
    { title: '创建时间', dataIndex: 'created_at', valueType: 'dateTime', hideInSearch: true, width: 160 },
    { title: '到期日', dataIndex: 'due_date', valueType: 'date', hideInSearch: true, width: 110 },
    {
      title: '操作',
      valueType: 'option',
      width: 140,
      render: (_, r) => (
        <Space size="small">
          {r.status === 'open' && (
            <a
              onClick={() => {
                setActionAlertId(r.id);
                setActionType('acknowledge');
                setModalVisible(true);
              }}
            >
              确认
            </a>
          )}
          {(r.status === 'open' || r.status === 'acknowledged') && (
            <a
              style={{ color: '#0F6E56' }}
              onClick={() => {
                setActionAlertId(r.id);
                setActionType('resolve');
                setModalVisible(true);
              }}
            >
              解决
            </a>
          )}
        </Space>
      ),
    },
  ];

  return (
    <>
      <ProTable<AlertItem>
        headerTitle="合规预警"
        actionRef={actionRef}
        columns={columns}
        rowKey="id"
        search={{ labelWidth: 'auto' }}
        pagination={{ defaultPageSize: 20 }}
        toolbar={{
          menu: {
            type: 'tab',
            activeKey: activeStatus,
            items: [
              { key: 'all', label: '全部' },
              { key: 'open', label: '待处理' },
              { key: 'acknowledged', label: '已确认' },
              { key: 'resolved', label: '已解决' },
            ],
            onChange: (key) => {
              setActiveStatus(key as string);
              actionRef.current?.reload();
            },
          },
        }}
        request={async (params) => {
          const query = new URLSearchParams();
          if (params.current) query.set('page', String(params.current));
          if (params.pageSize) query.set('size', String(params.pageSize));
          if (activeStatus !== 'all') query.set('status', activeStatus);
          if (params.alert_type) query.set('alert_type', params.alert_type);
          if (params.severity) query.set('severity', params.severity);
          if (params.store_id) query.set('store_id', params.store_id);
          const resp = await txFetchData<{ items: AlertItem[]; total: number }>(
            `/api/v1/compliance/alerts?${query.toString()}`,
          );
          const d = resp;
          return { data: d?.items ?? [], total: d?.total ?? 0, success: true };
        }}
      />

      {/* 处理弹窗 */}
      <ModalForm
        title={actionType === 'acknowledge' ? '确认预警' : '解决预警'}
        open={modalVisible}
        onOpenChange={setModalVisible}
        onFinish={async (values) => {
          if (!actionAlertId) return false;
          await txFetchData(`/api/v1/compliance/alerts/${actionAlertId}/${actionType}`, {
            method: 'POST',
            body: JSON.stringify(values),
          });
          message.success(actionType === 'acknowledge' ? '已确认' : '已解决');
          actionRef.current?.reload();
          return true;
        }}
      >
        <ProFormTextArea
          name="note"
          label="处理说明"
          rules={[{ required: true, message: '请填写处理说明' }]}
          placeholder="请描述处理情况..."
        />
      </ModalForm>

      {/* 脉冲动画 */}
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
