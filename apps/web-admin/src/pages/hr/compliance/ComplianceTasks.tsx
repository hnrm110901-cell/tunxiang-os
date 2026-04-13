/**
 * ComplianceTasks — 风险处置
 * Sprint 5 · 合规中心
 *
 * API: GET  /api/v1/compliance/alerts?status=open&status=acknowledged
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

interface TaskItem {
  id: string;
  title: string;
  severity: 'critical' | 'warning' | 'info';
  assignee_name: string | null;
  due_date: string | null;
  status: 'open' | 'acknowledged';
  created_at: string;
}

// ─── 枚举 ────────────────────────────────────────────────────────────────────

const severityTag: Record<string, { color: string; text: string }> = {
  critical: { color: 'red', text: '紧急' },
  warning: { color: 'orange', text: '中等' },
  info: { color: 'blue', text: '一般' },
};

const statusTag: Record<string, { color: string; text: string }> = {
  open: { color: 'red', text: '待处理' },
  acknowledged: { color: 'orange', text: '处理中' },
};

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function ComplianceTasks() {
  const actionRef = useRef<ActionType>();
  const [resolveId, setResolveId] = useState<string | null>(null);
  const [modalVisible, setModalVisible] = useState(false);

  const columns: ProColumns<TaskItem>[] = [
    { title: '标题', dataIndex: 'title', ellipsis: true },
    {
      title: '紧急度',
      dataIndex: 'severity',
      width: 80,
      render: (_, r) => {
        const s = severityTag[r.severity];
        return <Tag color={s?.color}>{s?.text}</Tag>;
      },
    },
    { title: '负责人', dataIndex: 'assignee_name', width: 100, render: (_, r) => r.assignee_name ?? '-' },
    { title: '到期日', dataIndex: 'due_date', valueType: 'date', width: 110 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (_, r) => {
        const s = statusTag[r.status];
        return <Tag color={s?.color}>{s?.text}</Tag>;
      },
    },
    { title: '创建时间', dataIndex: 'created_at', valueType: 'dateTime', width: 160 },
    {
      title: '操作',
      valueType: 'option',
      width: 140,
      render: (_, r) => (
        <Space size="small">
          {r.status === 'open' && (
            <a
              onClick={async () => {
                await txFetchData(`/api/v1/compliance/alerts/${r.id}/acknowledge`, { method: 'POST' });
                message.success('已标记为处理中');
                actionRef.current?.reload();
              }}
            >
              开始处理
            </a>
          )}
          <a
            style={{ color: '#0F6E56' }}
            onClick={() => {
              setResolveId(r.id);
              setModalVisible(true);
            }}
          >
            解决
          </a>
        </Space>
      ),
    },
  ];

  return (
    <>
      <ProTable<TaskItem>
        headerTitle="待处置任务"
        actionRef={actionRef}
        columns={columns}
        rowKey="id"
        search={false}
        pagination={{ defaultPageSize: 20 }}
        request={async (params) => {
          const query = new URLSearchParams();
          if (params.current) query.set('page', String(params.current));
          if (params.pageSize) query.set('size', String(params.pageSize));
          query.append('status', 'open');
          query.append('status', 'acknowledged');
          const resp = await txFetchData<{ items: TaskItem[]; total: number }>(
            `/api/v1/compliance/alerts?${query.toString()}`,
          );
          const d = resp;
          return { data: d?.items ?? [], total: d?.total ?? 0, success: true };
        }}
      />

      <ModalForm
        title="解决预警"
        open={modalVisible}
        onOpenChange={setModalVisible}
        onFinish={async (values) => {
          if (!resolveId) return false;
          await txFetchData(`/api/v1/compliance/alerts/${resolveId}/resolve`, {
            method: 'POST',
            body: JSON.stringify(values),
          });
          message.success('预警已解决');
          actionRef.current?.reload();
          return true;
        }}
      >
        <ProFormTextArea
          name="resolution_note"
          label="处理说明"
          rules={[{ required: true, message: '请填写处理说明' }]}
          placeholder="请描述处理措施和结果..."
        />
      </ModalForm>
    </>
  );
}
