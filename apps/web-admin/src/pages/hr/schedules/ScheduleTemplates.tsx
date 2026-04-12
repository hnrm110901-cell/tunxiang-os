/**
 * ScheduleTemplates — 班次模板
 * 域F · 组织人事 · HR Admin
 *
 * 功能：
 *  - ProTable模板列表（名称/时段/休息/适用岗位/颜色标记）
 *  - 新建/编辑ModalForm
 *  - 颜色选择器（用于排班日历的视觉区分）
 *
 * API: GET  /api/v1/schedules/templates
 *      POST /api/v1/schedules/templates
 *      PUT  /api/v1/schedules/templates/{id}
 */

import { useRef, useState } from 'react';
import { Button, Space, Tag, Typography, message } from 'antd';
import { PlusOutlined, EditOutlined } from '@ant-design/icons';
import {
  ActionType,
  ModalForm,
  ProColumns,
  ProFormSelect,
  ProFormText,
  ProFormTimePicker,
  ProTable,
} from '@ant-design/pro-components';
import { txFetchData } from '../../../api';

const { Title } = Typography;
const TX_PRIMARY = '#FF6B35';

// ─── Types ───────────────────────────────────────────────────────────────────

interface TemplateItem {
  id: string;
  name: string;
  shift_start: string;
  shift_end: string;
  break_start?: string;
  break_end?: string;
  applicable_roles: string[];
  color: string;
  is_active: boolean;
  created_at: string;
}

const COLOR_OPTIONS = [
  { label: '橙色', value: '#FF6B35' },
  { label: '蓝色', value: '#1890ff' },
  { label: '紫色', value: '#722ed1' },
  { label: '绿色', value: '#52c41a' },
  { label: '金色', value: '#faad14' },
  { label: '红色', value: '#ff4d4f' },
  { label: '青色', value: '#13c2c2' },
];

const ROLE_OPTIONS = [
  { label: '服务员', value: 'waiter' },
  { label: '厨师', value: 'chef' },
  { label: '收银员', value: 'cashier' },
  { label: '店长', value: 'manager' },
  { label: '清洁', value: 'cleaner' },
];

// ─── Component ───────────────────────────────────────────────────────────────

export default function ScheduleTemplates() {
  const actionRef = useRef<ActionType>(null);
  const [messageApi, contextHolder] = message.useMessage();
  const [editRecord, setEditRecord] = useState<TemplateItem | null>(null);
  const [editVisible, setEditVisible] = useState(false);

  const handleSave = async (values: Record<string, unknown>, isEdit: boolean) => {
    try {
      const url = isEdit
        ? `/api/v1/schedules/templates/${editRecord?.id}`
        : '/api/v1/schedules/templates';
      const res = await txFetchData(url, {
        method: isEdit ? 'PUT' : 'POST',
        body: JSON.stringify(values),
      }) as { ok: boolean };
      if (res.ok) {
        messageApi.success(isEdit ? '模板更新成功' : '模板创建成功');
        actionRef.current?.reload();
        return true;
      }
      messageApi.error('保存失败');
    } catch {
      messageApi.error('保存失败');
    }
    return false;
  };

  const columns: ProColumns<TemplateItem>[] = [
    {
      title: '颜色',
      dataIndex: 'color',
      width: 60,
      hideInSearch: true,
      render: (_, r) => (
        <div
          style={{
            width: 24,
            height: 24,
            borderRadius: 4,
            backgroundColor: r.color,
          }}
        />
      ),
    },
    { title: '模板名称', dataIndex: 'name', width: 140 },
    {
      title: '时段',
      key: 'time',
      width: 140,
      hideInSearch: true,
      render: (_, r) => `${r.shift_start} - ${r.shift_end}`,
    },
    {
      title: '休息时间',
      key: 'break',
      width: 140,
      hideInSearch: true,
      render: (_, r) =>
        r.break_start && r.break_end ? `${r.break_start} - ${r.break_end}` : '--',
    },
    {
      title: '适用岗位',
      dataIndex: 'applicable_roles',
      width: 200,
      hideInSearch: true,
      render: (_, r) =>
        r.applicable_roles?.map((role) => {
          const opt = ROLE_OPTIONS.find((o) => o.value === role);
          return <Tag key={role}>{opt?.label ?? role}</Tag>;
        }),
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      width: 80,
      hideInSearch: true,
      render: (_, r) =>
        r.is_active ? <Tag color="success">启用</Tag> : <Tag color="default">停用</Tag>,
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      hideInSearch: true,
      render: (_, r) => (
        <Button
          type="link"
          size="small"
          icon={<EditOutlined />}
          onClick={() => {
            setEditRecord(r);
            setEditVisible(true);
          }}
        >
          编辑
        </Button>
      ),
    },
  ];

  // ─── 表单字段 ────────────────────────────────────────────────────────────

  const formFields = (
    <>
      <ProFormText name="name" label="模板名称" rules={[{ required: true }]} />
      <ProFormTimePicker name="shift_start" label="上班时间" rules={[{ required: true }]} />
      <ProFormTimePicker name="shift_end" label="下班时间" rules={[{ required: true }]} />
      <ProFormTimePicker name="break_start" label="休息开始" />
      <ProFormTimePicker name="break_end" label="休息结束" />
      <ProFormSelect
        name="applicable_roles"
        label="适用岗位"
        mode="multiple"
        options={ROLE_OPTIONS}
        rules={[{ required: true }]}
      />
      <ProFormSelect
        name="color"
        label="颜色标记"
        options={COLOR_OPTIONS}
        rules={[{ required: true }]}
        fieldProps={{
          optionRender: (option) => (
            <Space>
              <div
                style={{
                  width: 16,
                  height: 16,
                  borderRadius: 3,
                  backgroundColor: option.value as string,
                }}
              />
              {option.label}
            </Space>
          ),
        }}
      />
    </>
  );

  return (
    <div style={{ padding: 24 }}>
      {contextHolder}
      <Title level={4}>班次模板</Title>

      <ProTable<TemplateItem>
        headerTitle="模板列表"
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        search={{ labelWidth: 80 }}
        toolBarRender={() => [
          <ModalForm
            key="create"
            title="新建班次模板"
            trigger={
              <Button
                type="primary"
                icon={<PlusOutlined />}
                style={{ backgroundColor: TX_PRIMARY, borderColor: TX_PRIMARY }}
              >
                新建模板
              </Button>
            }
            onFinish={(v) => handleSave(v, false)}
            modalProps={{ destroyOnClose: true }}
          >
            {formFields}
          </ModalForm>,
        ]}
        request={async (params) => {
          const query = new URLSearchParams();
          if (params.name) query.set('name', params.name);
          query.set('page', String(params.current ?? 1));
          query.set('size', String(params.pageSize ?? 20));
          try {
            const res = await txFetchData(`/api/v1/schedules/templates?${query}`) as {
              ok: boolean;
              data: { items: TemplateItem[]; total: number };
            };
            if (res.ok) {
              return { data: res.data.items, total: res.data.total, success: true };
            }
          } catch { /* fallback */ }
          return { data: [], total: 0, success: true };
        }}
        pagination={{ defaultPageSize: 20 }}
      />

      {/* ── 编辑弹窗 ── */}
      <ModalForm
        title="编辑班次模板"
        open={editVisible}
        onOpenChange={setEditVisible}
        initialValues={editRecord ?? undefined}
        onFinish={(v) => handleSave(v, true)}
        modalProps={{ destroyOnClose: true }}
      >
        {formFields}
      </ModalForm>
    </div>
  );
}
