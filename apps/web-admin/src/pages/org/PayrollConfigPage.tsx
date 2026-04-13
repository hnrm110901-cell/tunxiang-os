/**
 * PayrollConfigPage — 薪资方案配置
 * 域F · 组织人事 · HR Admin
 *
 * 功能：
 *  - ProTable 展示薪资方案列表（岗位/门店/薪资类型/底薪或时薪/提成配置/有效期/状态）
 *  - 新增/编辑：ModalForm（employee_role/store_id/salary_type/base_salary|hourly_rate/commission_type/effective_from~to）
 *  - 软删除：Popconfirm 二次确认
 *  - 搜索栏：employee_role + store_id + is_active
 *
 * API 基地址: /api/v1/payroll/configs
 * X-Tenant-ID 通过 txFetchData 统一注入
 */

import { useRef, useState } from 'react';
import { formatPrice } from '@tx-ds/utils';
import {
  Button,
  Popconfirm,
  Space,
  Tag,
  message,
} from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import {
  ActionType,
  ModalForm,
  ProColumns,
  ProFormDatePicker,
  ProFormSelect,
  ProFormText,
  ProFormRadio,
  ProFormDigit,
  ProTable,
} from '@ant-design/pro-components';
import { txFetchData } from '../../api';

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface PayrollConfig {
  id: string;
  employee_role: string;
  store_id: string;
  store_name?: string;
  salary_type: 'monthly' | 'hourly' | 'piecework';
  base_salary?: number;   // fen
  hourly_rate?: number;   // fen
  commission_type?: string;
  effective_from: string;
  effective_to?: string;
  is_active: boolean;
  created_at: string;
}

interface ConfigListResp {
  items: PayrollConfig[];
  total: number;
}

// ─── 枚举常量 ────────────────────────────────────────────────────────────────

const ROLE_ENUM: Record<string, { text: string }> = {
  cashier: { text: '收银员' },
  chef:    { text: '厨师' },
  waiter:  { text: '服务员' },
  manager: { text: '店长' },
};

const SALARY_TYPE_ENUM: Record<string, { text: string; status: string }> = {
  monthly:   { text: '月薪',   status: 'Processing' },
  hourly:    { text: '时薪',   status: 'Warning'    },
  piecework: { text: '计件',   status: 'Default'    },
};

const COMMISSION_TYPE_OPTIONS = [
  { label: '无提成',     value: 'none'          },
  { label: '按销售额%',  value: 'revenue_pct'   },
  { label: '按利润%',    value: 'profit_pct'    },
  { label: '固定件数提成', value: 'fixed_piece' },
];

// ─── 金额格式化 ───────────────────────────────────────────────────────────────

/** @deprecated Use formatPrice from @tx-ds/utils */
const fenToYuan = (fen?: number) =>
  fen == null ? '-' : `¥${(fen / 100).toFixed(2)}`;

// ─── 页面组件 ─────────────────────────────────────────────────────────────────

export function PayrollConfigPage() {
  const actionRef = useRef<ActionType>(null);
  const [editingRecord, setEditingRecord] = useState<PayrollConfig | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [messageApi, contextHolder] = message.useMessage();

  // ─── 列定义 ─────────────────────────────────────────────────────────────────

  const columns: ProColumns<PayrollConfig>[] = [
    {
      title: '岗位',
      dataIndex: 'employee_role',
      valueType: 'select',
      valueEnum: ROLE_ENUM,
      width: 100,
    },
    {
      title: '门店',
      dataIndex: 'store_id',
      renderText: (_, r) => r.store_name || r.store_id,
      width: 140,
      search: {
        transform: (v) => ({ store_id: v }),
      },
    },
    {
      title: '薪资类型',
      dataIndex: 'salary_type',
      valueType: 'select',
      valueEnum: SALARY_TYPE_ENUM,
      width: 100,
      hideInSearch: true,
    },
    {
      title: '底薪/时薪',
      dataIndex: 'base_salary',
      hideInSearch: true,
      width: 120,
      render: (_, r) => {
        if (r.salary_type === 'monthly')   return fenToYuan(r.base_salary);
        if (r.salary_type === 'hourly')    return `${fenToYuan(r.hourly_rate)}/时`;
        if (r.salary_type === 'piecework') return '-';
        return '-';
      },
    },
    {
      title: '提成配置',
      dataIndex: 'commission_type',
      hideInSearch: true,
      width: 120,
      renderText: (v?: string) =>
        COMMISSION_TYPE_OPTIONS.find((o) => o.value === v)?.label ?? '-',
    },
    {
      title: '有效期',
      key: 'effective_period',
      hideInSearch: true,
      width: 180,
      render: (_, r) =>
        `${r.effective_from} ~ ${r.effective_to ?? '长期'}`,
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      valueType: 'select',
      valueEnum: {
        true:  { text: '启用', status: 'Success'  },
        false: { text: '停用', status: 'Default'  },
      },
      width: 80,
      render: (_, r) => (
        <Tag color={r.is_active ? 'green' : 'default'}>
          {r.is_active ? '启用' : '停用'}
        </Tag>
      ),
    },
    {
      title: '操作',
      valueType: 'option',
      width: 120,
      render: (_, record) => [
        <a
          key="edit"
          onClick={() => {
            setEditingRecord(record);
            setModalOpen(true);
          }}
        >
          编辑
        </a>,
        <Popconfirm
          key="delete"
          title="确认删除此薪资方案？"
          onConfirm={() => handleDelete(record.id)}
          okText="确认"
          cancelText="取消"
        >
          <a style={{ color: '#A32D2D' }}>删除</a>
        </Popconfirm>,
      ],
    },
  ];

  // ─── 数据请求 ────────────────────────────────────────────────────────────────

  const handleRequest = async (params: {
    employee_role?: string;
    store_id?: string;
    is_active?: string;
    current?: number;
    pageSize?: number;
  }) => {
    const query = new URLSearchParams();
    if (params.employee_role) query.set('employee_role', params.employee_role);
    if (params.store_id)      query.set('store_id', params.store_id);
    if (params.is_active != null && params.is_active !== '')
      query.set('is_active', params.is_active);
    query.set('page',  String(params.current ?? 1));
    query.set('size',  String(params.pageSize ?? 20));

    try {
      const data = await txFetchData<ConfigListResp>(
        `/api/v1/payroll/configs?${query.toString()}`,
      );
      return { data: data.items, total: data.total, success: true };
    } catch (err) {
      messageApi.error(`加载薪资方案失败：${(err as Error).message}`);
      return { data: [], total: 0, success: false };
    }
  };

  // ─── 新增 / 编辑提交 ─────────────────────────────────────────────────────────

  const handleFinish = async (values: Record<string, unknown>) => {
    const payload = {
      ...values,
      // 金额转 fen
      base_salary:  values.base_salary  != null ? Math.round(Number(values.base_salary)  * 100) : undefined,
      hourly_rate:  values.hourly_rate  != null ? Math.round(Number(values.hourly_rate)  * 100) : undefined,
    };

    try {
      if (editingRecord) {
        await txFetchData(`/api/v1/payroll/configs/${editingRecord.id}`, {
          method: 'PUT',
          body: JSON.stringify(payload),
        });
        messageApi.success('薪资方案已更新');
      } else {
        await txFetchData('/api/v1/payroll/configs', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
        messageApi.success('薪资方案已创建');
      }
      actionRef.current?.reload();
      setEditingRecord(null);
      return true;
    } catch (err) {
      messageApi.error(`操作失败：${(err as Error).message}`);
      return false;
    }
  };

  // ─── 删除 ────────────────────────────────────────────────────────────────────

  const handleDelete = async (id: string) => {
    try {
      await txFetchData(`/api/v1/payroll/configs/${id}`, { method: 'DELETE' });
      messageApi.success('方案已删除');
      actionRef.current?.reload();
    } catch (err) {
      messageApi.error(`删除失败：${(err as Error).message}`);
    }
  };

  // ─── 渲染 ────────────────────────────────────────────────────────────────────

  return (
    <>
      {contextHolder}

      <ProTable<PayrollConfig>
        headerTitle="薪资方案配置"
        rowKey="id"
        actionRef={actionRef}
        columns={columns}
        request={handleRequest}
        search={{ labelWidth: 'auto' }}
        pagination={{ defaultPageSize: 20, showSizeChanger: true }}
        toolBarRender={() => [
          <Button
            key="add"
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              setEditingRecord(null);
              setModalOpen(true);
            }}
          >
            新增方案
          </Button>,
        ]}
      />

      {/* 新增 / 编辑 ModalForm */}
      <ConfigModalForm
        open={modalOpen}
        record={editingRecord}
        onOpenChange={(v) => {
          setModalOpen(v);
          if (!v) setEditingRecord(null);
        }}
        onFinish={handleFinish}
      />
    </>
  );
}

// ─── 独立 ModalForm 组件（避免状态联动复杂度）───────────────────────────────

interface ConfigModalFormProps {
  open: boolean;
  record: PayrollConfig | null;
  onOpenChange: (open: boolean) => void;
  onFinish: (values: Record<string, unknown>) => Promise<boolean>;
}

function ConfigModalForm({ open, record, onOpenChange, onFinish }: ConfigModalFormProps) {
  const [salaryType, setSalaryType] = useState<string>(record?.salary_type ?? 'monthly');

  return (
    <ModalForm
      title={record ? '编辑薪资方案' : '新增薪资方案'}
      open={open}
      onOpenChange={onOpenChange}
      onFinish={onFinish}
      initialValues={
        record
          ? {
              ...record,
              base_salary: record.base_salary != null ? record.base_salary / 100 : undefined,
              hourly_rate: record.hourly_rate != null ? record.hourly_rate / 100 : undefined,
            }
          : { salary_type: 'monthly', commission_type: 'none', is_active: true }
      }
      modalProps={{ destroyOnClose: true }}
      width={560}
    >
      <ProFormSelect
        name="employee_role"
        label="岗位"
        rules={[{ required: true, message: '请选择岗位' }]}
        options={Object.entries(ROLE_ENUM).map(([v, { text }]) => ({ label: text, value: v }))}
      />

      <ProFormText
        name="store_id"
        label="门店 ID"
        rules={[{ required: true, message: '请输入门店 ID' }]}
        placeholder="如 store-001"
      />

      <ProFormRadio.Group
        name="salary_type"
        label="薪资类型"
        rules={[{ required: true }]}
        options={[
          { label: '月薪', value: 'monthly'   },
          { label: '时薪', value: 'hourly'    },
          { label: '计件', value: 'piecework' },
        ]}
        fieldProps={{
          onChange: (e) => setSalaryType(e.target.value),
        }}
      />

      {(salaryType === 'monthly' || record?.salary_type === 'monthly') && (
        <ProFormDigit
          name="base_salary"
          label="底薪（元）"
          min={0}
          fieldProps={{ precision: 2, addonAfter: '元/月' }}
        />
      )}

      {(salaryType === 'hourly' || record?.salary_type === 'hourly') && (
        <ProFormDigit
          name="hourly_rate"
          label="时薪（元）"
          min={0}
          fieldProps={{ precision: 2, addonAfter: '元/时' }}
        />
      )}

      <ProFormSelect
        name="commission_type"
        label="提成配置"
        options={COMMISSION_TYPE_OPTIONS}
        initialValue="none"
      />

      <Space>
        <ProFormDatePicker
          name="effective_from"
          label="有效期开始"
          rules={[{ required: true, message: '请选择开始日期' }]}
          fieldProps={{ style: { width: 180 } }}
        />
        <ProFormDatePicker
          name="effective_to"
          label="有效期结束"
          fieldProps={{ style: { width: 180 } }}
          tooltip="不填则表示长期有效"
        />
      </Space>

      <ProFormSelect
        name="is_active"
        label="状态"
        options={[
          { label: '启用', value: true  },
          { label: '停用', value: false },
        ]}
        initialValue={true}
      />
    </ModalForm>
  );
}
