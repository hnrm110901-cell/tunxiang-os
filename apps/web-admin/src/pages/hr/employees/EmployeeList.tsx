/**
 * EmployeeList — 员工列表 (P0)
 * Sprint 5 · 员工主档
 *
 * API: GET /api/v1/employees?page=&size=&store_id=&department_id=&status=&employment_type=&keyword=
 */

import { useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Space, Tag, message } from 'antd';
import {
  PlusOutlined,
  UploadOutlined,
  UserOutlined,
  SwapOutlined,
  LogoutOutlined,
} from '@ant-design/icons';
import { ActionType, ProColumns, ProTable } from '@ant-design/pro-components';
import { txFetchData } from '../../../api';

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface Employee {
  id: string;
  name: string;
  employee_no: string;
  department_name: string;
  position_name: string;
  store_name: string;
  hire_date: string;
  employment_type: 'full_time' | 'part_time' | 'intern' | 'outsourced';
  status: 'active' | 'probation' | 'resigned' | 'terminated';
}

interface EmployeeListResp {
  items: Employee[];
  total: number;
}

// ─── 枚举映射 ────────────────────────────────────────────────────────────────

const statusMap: Record<string, { text: string; color: string }> = {
  active: { text: '在职', color: 'green' },
  probation: { text: '试用', color: 'blue' },
  resigned: { text: '离职', color: 'default' },
  terminated: { text: '解除', color: 'default' },
};

const employmentTypeMap: Record<string, string> = {
  full_time: '全职',
  part_time: '兼职',
  intern: '实习',
  outsourced: '外包',
};

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function EmployeeList() {
  const actionRef = useRef<ActionType>();
  const navigate = useNavigate();

  const columns: ProColumns<Employee>[] = [
    {
      title: '关键词',
      dataIndex: 'keyword',
      hideInTable: true,
      fieldProps: { placeholder: '姓名/工号/手机' },
    },
    {
      title: '姓名',
      dataIndex: 'name',
      hideInSearch: true,
      render: (_, r) => (
        <a onClick={() => navigate(`/hr/employees/${r.id}`)}>{r.name}</a>
      ),
    },
    { title: '工号', dataIndex: 'employee_no', hideInSearch: true, width: 100 },
    {
      title: '部门',
      dataIndex: 'department_id',
      hideInTable: true,
      valueType: 'select',
      fieldProps: { placeholder: '选择部门', showSearch: true },
      request: async () => {
        const resp = await txFetchData<{ items: { id: string; name: string }[] }>(
          '/api/v1/org-structure/departments',
        );
        return (resp?.items ?? []).map((d) => ({ label: d.name, value: d.id }));
      },
    },
    { title: '部门', dataIndex: 'department_name', hideInSearch: true },
    { title: '岗位', dataIndex: 'position_name', hideInSearch: true },
    {
      title: '门店',
      dataIndex: 'store_id',
      hideInTable: true,
      valueType: 'select',
      fieldProps: { placeholder: '选择门店', showSearch: true },
      request: async () => {
        const resp = await txFetchData<{ items: { id: string; name: string }[] }>(
          '/api/v1/stores',
        );
        return (resp?.items ?? []).map((s) => ({ label: s.name, value: s.id }));
      },
    },
    { title: '门店', dataIndex: 'store_name', hideInSearch: true },
    { title: '入职日期', dataIndex: 'hire_date', hideInSearch: true, valueType: 'date', width: 110 },
    {
      title: '用工类型',
      dataIndex: 'employment_type',
      valueType: 'select',
      valueEnum: {
        full_time: { text: '全职' },
        part_time: { text: '兼职' },
        intern: { text: '实习' },
        outsourced: { text: '外包' },
      },
      render: (_, r) => employmentTypeMap[r.employment_type] ?? r.employment_type,
      width: 90,
    },
    {
      title: '状态',
      dataIndex: 'status',
      valueType: 'select',
      valueEnum: {
        active: { text: '在职', status: 'Success' },
        probation: { text: '试用', status: 'Processing' },
        resigned: { text: '离职', status: 'Default' },
        terminated: { text: '解除', status: 'Default' },
      },
      render: (_, r) => {
        const s = statusMap[r.status];
        return <Tag color={s?.color}>{s?.text ?? r.status}</Tag>;
      },
      width: 80,
    },
    {
      title: '操作',
      valueType: 'option',
      width: 200,
      render: (_, r) => (
        <Space size="small">
          <a onClick={() => navigate(`/hr/employees/${r.id}`)}>
            <UserOutlined /> 详情
          </a>
          <a onClick={() => navigate(`/hr/employees/${r.id}?tab=edit`)}>编辑</a>
          <a onClick={() => message.info(`调岗: ${r.name}`)}>
            <SwapOutlined /> 调岗
          </a>
          {r.status !== 'resigned' && (
            <a style={{ color: '#999' }} onClick={() => message.info(`离职: ${r.name}`)}>
              <LogoutOutlined /> 离职
            </a>
          )}
        </Space>
      ),
    },
  ];

  return (
    <ProTable<Employee>
      headerTitle="员工列表"
      actionRef={actionRef}
      columns={columns}
      rowKey="id"
      search={{ labelWidth: 'auto' }}
      pagination={{ defaultPageSize: 20, showSizeChanger: true }}
      request={async (params) => {
        const query = new URLSearchParams();
        if (params.current) query.set('page', String(params.current));
        if (params.pageSize) query.set('size', String(params.pageSize));
        if (params.keyword) query.set('keyword', params.keyword);
        if (params.store_id) query.set('store_id', params.store_id);
        if (params.department_id) query.set('department_id', params.department_id);
        if (params.status) query.set('status', params.status);
        if (params.employment_type) query.set('employment_type', params.employment_type);
        const resp = await txFetchData<EmployeeListResp>(
          `/api/v1/employees?${query.toString()}`,
        );
        const d = resp;
        return { data: d?.items ?? [], total: d?.total ?? 0, success: true };
      }}
      toolBarRender={() => [
        <Button
          key="create"
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => navigate('/hr/employees/create')}
        >
          新增员工
        </Button>,
        <Button
          key="import"
          icon={<UploadOutlined />}
          onClick={() => message.info('批量导入功能开发中')}
        >
          批量导入
        </Button>,
      ]}
    />
  );
}
