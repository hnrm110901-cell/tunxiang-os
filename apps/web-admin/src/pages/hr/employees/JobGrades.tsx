/**
 * JobGrades — 岗位职级管理
 * Sprint 5 · 员工主档
 *
 * API: GET  /api/v1/job-grades
 *      POST /api/v1/job-grades
 *      PUT  /api/v1/job-grades/{id}
 */

import { useRef, useState } from 'react';
import { Tag, message } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import {
  ActionType,
  ModalForm,
  ProColumns,
  ProFormDigitRange,
  ProFormSelect,
  ProFormText,
  ProFormTextArea,
  ProTable,
} from '@ant-design/pro-components';
import { txFetchData } from '../../../api';

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface JobGrade {
  id: string;
  name: string;
  category: 'front' | 'kitchen' | 'management' | 'support';
  level: number;
  salary_min_fen: number;
  salary_max_fen: number;
  headcount: number;
  status: 'active' | 'inactive';
  description: string | null;
}

// ─── 枚举 ────────────────────────────────────────────────────────────────────

const categoryMap: Record<string, { text: string; color: string }> = {
  front: { text: '前厅', color: 'blue' },
  kitchen: { text: '后厨', color: 'orange' },
  management: { text: '管理', color: 'purple' },
  support: { text: '后勤', color: 'default' },
};

function fenToYuan(fen: number): string {
  return (fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 0 });
}

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function JobGrades() {
  const actionRef = useRef<ActionType>();
  const [editItem, setEditItem] = useState<JobGrade | null>(null);
  const [formVisible, setFormVisible] = useState(false);
  const [activeCategory, setActiveCategory] = useState<string>('all');

  const columns: ProColumns<JobGrade>[] = [
    { title: '名称', dataIndex: 'name' },
    {
      title: '分类',
      dataIndex: 'category',
      render: (_, r) => {
        const c = categoryMap[r.category];
        return <Tag color={c?.color}>{c?.text ?? r.category}</Tag>;
      },
    },
    { title: '级别', dataIndex: 'level', valueType: 'digit', width: 80 },
    {
      title: '薪资区间(元/月)',
      render: (_, r) => `${fenToYuan(r.salary_min_fen)} ~ ${fenToYuan(r.salary_max_fen)}`,
    },
    { title: '在职人数', dataIndex: 'headcount', valueType: 'digit', width: 100 },
    {
      title: '状态',
      dataIndex: 'status',
      render: (_, r) => (
        <Tag color={r.status === 'active' ? 'green' : 'default'}>
          {r.status === 'active' ? '启用' : '停用'}
        </Tag>
      ),
      width: 80,
    },
    {
      title: '操作',
      valueType: 'option',
      width: 120,
      render: (_, r) => [
        <a
          key="edit"
          onClick={() => {
            setEditItem(r);
            setFormVisible(true);
          }}
        >
          编辑
        </a>,
      ],
    },
  ];

  return (
    <>
      <ProTable<JobGrade>
        headerTitle="岗位职级"
        actionRef={actionRef}
        columns={columns}
        rowKey="id"
        search={false}
        toolbar={{
          menu: {
            type: 'tab',
            activeKey: activeCategory,
            items: [
              { key: 'all', label: '全部' },
              { key: 'front', label: '前厅' },
              { key: 'kitchen', label: '后厨' },
              { key: 'management', label: '管理' },
              { key: 'support', label: '后勤' },
            ],
            onChange: (key) => {
              setActiveCategory(key as string);
              actionRef.current?.reload();
            },
          },
        }}
        request={async (params) => {
          const query = new URLSearchParams();
          if (params.current) query.set('page', String(params.current));
          if (params.pageSize) query.set('size', String(params.pageSize));
          if (activeCategory !== 'all') query.set('category', activeCategory);
          const resp = await txFetchData<{ items: JobGrade[]; total: number }>(
            `/api/v1/job-grades?${query.toString()}`,
          );
          const d = resp.data;
          return { data: d?.items ?? [], total: d?.total ?? 0, success: resp.ok };
        }}
        pagination={{ defaultPageSize: 20 }}
        toolBarRender={() => [
          <ModalForm
            key="create"
            title={editItem ? '编辑岗位职级' : '新建岗位职级'}
            trigger={<PlusOutlined />}
            open={formVisible}
            onOpenChange={(v) => {
              setFormVisible(v);
              if (!v) setEditItem(null);
            }}
            initialValues={
              editItem
                ? {
                    name: editItem.name,
                    category: editItem.category,
                    level: editItem.level,
                    salary_range: [editItem.salary_min_fen / 100, editItem.salary_max_fen / 100],
                    description: editItem.description,
                  }
                : {}
            }
            onFinish={async (values) => {
              const payload = {
                ...values,
                salary_min_fen: Math.round((values.salary_range?.[0] ?? 0) * 100),
                salary_max_fen: Math.round((values.salary_range?.[1] ?? 0) * 100),
              };
              delete payload.salary_range;
              if (editItem) {
                await txFetchData(`/api/v1/job-grades/${editItem.id}`, {
                  method: 'PUT',
                  body: JSON.stringify(payload),
                });
                message.success('更新成功');
              } else {
                await txFetchData('/api/v1/job-grades', {
                  method: 'POST',
                  body: JSON.stringify(payload),
                });
                message.success('创建成功');
              }
              actionRef.current?.reload();
              return true;
            }}
          >
            <ProFormText name="name" label="名称" rules={[{ required: true }]} width="md" />
            <ProFormSelect
              name="category"
              label="分类"
              rules={[{ required: true }]}
              width="sm"
              options={[
                { label: '前厅', value: 'front' },
                { label: '后厨', value: 'kitchen' },
                { label: '管理', value: 'management' },
                { label: '后勤', value: 'support' },
              ]}
            />
            <ProFormDigitRange name="salary_range" label="薪资区间(元/月)" />
            <ProFormTextArea name="description" label="要求描述" />
          </ModalForm>,
        ]}
      />
    </>
  );
}
