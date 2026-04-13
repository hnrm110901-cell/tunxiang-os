/**
 * ContractTemplatesPage -- 合同模板管理
 * 域F - 组织人事 - 电子签约
 *
 * 功能：
 *  1. ProTable 模板列表（名称/类型/状态/版本/操作）
 *  2. 新建模板 ModalForm
 *  3. 编辑模板 ModalForm
 */

import { useRef, useState } from 'react';
import {
  Button,
  message,
  Space,
  Switch,
  Tag,
  Typography,
} from 'antd';
import {
  ModalForm,
  ProFormSelect,
  ProFormSwitch,
  ProFormText,
  ProFormTextArea,
  ProTable,
} from '@ant-design/pro-components';
import type { ActionType, ProColumns } from '@ant-design/pro-components';
import { FileTextOutlined, PlusOutlined } from '@ant-design/icons';
import type { ContractTemplate } from '../../../api/contractApi';
import {
  createContractTemplate,
  fetchContractTemplates,
  updateContractTemplate,
} from '../../../api/contractApi';

const { Title } = Typography;
const TX_PRIMARY = '#FF6B35';

const CONTRACT_TYPE_OPTIONS = [
  { label: '劳动合同', value: 'labor' },
  { label: '保密协议', value: 'confidentiality' },
  { label: '竞业限制协议', value: 'non_compete' },
  { label: '实习协议', value: 'internship' },
  { label: '非全日制用工协议', value: 'part_time' },
];

const TYPE_COLOR: Record<string, string> = {
  labor: 'blue',
  confidentiality: 'purple',
  non_compete: 'red',
  internship: 'cyan',
  part_time: 'green',
};

export default function ContractTemplatesPage() {
  const actionRef = useRef<ActionType>();
  const [createOpen, setCreateOpen] = useState(false);
  const [editRecord, setEditRecord] = useState<ContractTemplate | null>(null);

  const columns: ProColumns<ContractTemplate>[] = [
    {
      title: '模板名称',
      dataIndex: 'template_name',
      ellipsis: true,
      width: 220,
    },
    {
      title: '合同类型',
      dataIndex: 'contract_type',
      width: 140,
      render: (_, record) => (
        <Tag color={TYPE_COLOR[record.contract_type] || 'default'}>
          {record.contract_type_label}
        </Tag>
      ),
      valueEnum: Object.fromEntries(
        CONTRACT_TYPE_OPTIONS.map((o) => [o.value, { text: o.label }]),
      ),
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      width: 100,
      render: (_, record) => (
        <Tag color={record.is_active ? 'green' : 'default'}>
          {record.is_active ? '启用' : '停用'}
        </Tag>
      ),
    },
    {
      title: '版本',
      dataIndex: 'version',
      width: 80,
      render: (_, record) => `V${record.version}`,
    },
    {
      title: '变量数',
      dataIndex: 'variables',
      width: 80,
      render: (_, record) =>
        Array.isArray(record.variables) ? record.variables.length : 0,
      search: false,
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      valueType: 'dateTime',
      width: 170,
      search: false,
    },
    {
      title: '操作',
      valueType: 'option',
      width: 120,
      render: (_, record) => (
        <Space>
          <a onClick={() => setEditRecord(record)}>编辑</a>
          <a
            onClick={async () => {
              try {
                await updateContractTemplate(record.id, {
                  is_active: !record.is_active,
                });
                message.success(record.is_active ? '已停用' : '已启用');
                actionRef.current?.reload();
              } catch {
                message.error('操作失败');
              }
            }}
          >
            {record.is_active ? '停用' : '启用'}
          </a>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Title level={4}>
        <FileTextOutlined style={{ color: TX_PRIMARY, marginRight: 8 }} />
        合同模板管理
      </Title>

      <ProTable<ContractTemplate>
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        headerTitle="模板列表"
        search={{ labelWidth: 'auto' }}
        toolBarRender={() => [
          <Button
            key="create"
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setCreateOpen(true)}
            style={{ background: TX_PRIMARY, borderColor: TX_PRIMARY }}
          >
            新建模板
          </Button>,
        ]}
        request={async (params) => {
          try {
            const result = await fetchContractTemplates({
              contract_type: params.contract_type,
              page: params.current || 1,
              size: params.pageSize || 20,
            });
            let items = result.items || [];
            if (params.template_name) {
              items = items.filter((t) =>
                t.template_name.includes(params.template_name),
              );
            }
            return { data: items, total: result.total, success: true };
          } catch {
            message.error('加载模板失败');
            return { data: [], total: 0, success: false };
          }
        }}
        pagination={{ pageSize: 20 }}
      />

      {/* 新建模板 */}
      <ModalForm
        title="新建合同模板"
        open={createOpen}
        onOpenChange={setCreateOpen}
        width={640}
        onFinish={async (values) => {
          try {
            await createContractTemplate(values);
            message.success('模板创建成功');
            actionRef.current?.reload();
            return true;
          } catch {
            message.error('创建失败');
            return false;
          }
        }}
      >
        <ProFormText
          name="template_name"
          label="模板名称"
          rules={[{ required: true, message: '请输入模板名称' }]}
          placeholder="如：标准劳动合同"
        />
        <ProFormSelect
          name="contract_type"
          label="合同类型"
          rules={[{ required: true, message: '请选择合同类型' }]}
          options={CONTRACT_TYPE_OPTIONS}
        />
        <ProFormTextArea
          name="content_html"
          label="合同内容(HTML)"
          placeholder="合同正文，支持 {{变量名}} 占位符"
          fieldProps={{ rows: 6 }}
        />
        <ProFormSwitch name="is_active" label="立即启用" initialValue={true} />
      </ModalForm>

      {/* 编辑模板 */}
      <ModalForm
        title="编辑合同模板"
        open={!!editRecord}
        onOpenChange={(open) => {
          if (!open) setEditRecord(null);
        }}
        width={640}
        initialValues={editRecord || {}}
        onFinish={async (values) => {
          if (!editRecord) return false;
          try {
            await updateContractTemplate(editRecord.id, values);
            message.success('模板更新成功');
            actionRef.current?.reload();
            setEditRecord(null);
            return true;
          } catch {
            message.error('更新失败');
            return false;
          }
        }}
      >
        <ProFormText
          name="template_name"
          label="模板名称"
          rules={[{ required: true, message: '请输入模板名称' }]}
        />
        <ProFormSelect
          name="contract_type"
          label="合同类型"
          rules={[{ required: true, message: '请选择合同类型' }]}
          options={CONTRACT_TYPE_OPTIONS}
        />
        <ProFormTextArea
          name="content_html"
          label="合同内容(HTML)"
          fieldProps={{ rows: 6 }}
        />
        <ProFormSwitch name="is_active" label="启用" />
      </ModalForm>
    </div>
  );
}
