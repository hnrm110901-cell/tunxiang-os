/**
 * SettingsApprovalWorkflows — 审批流配置
 * 域F · 配置中心
 *
 * 功能：
 *  1. 审批流模板 ProTable（请假审批/调岗审批/薪资审批/补位审批）
 *  2. 配置节点 Drawer（审批节点列表+添加/删除）
 *
 * API:
 *  GET /api/v1/approval-engine/templates
 *  GET /api/v1/approval-engine/templates/{id}
 *  PUT /api/v1/approval-engine/templates/{id}
 */

import { useRef, useState } from 'react';
import {
  Button,
  Card,
  Drawer,
  List,
  message,
  Space,
  Steps,
  Tag,
  Typography,
} from 'antd';
import {
  BranchesOutlined,
  DeleteOutlined,
  PlusOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import {
  ActionType,
  ModalForm,
  ProColumns,
  ProFormDigit,
  ProFormSelect,
  ProFormText,
  ProTable,
} from '@ant-design/pro-components';
import { txFetch } from '../../../api';

const { Title, Text } = Typography;

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface ApprovalNode {
  step: number;
  name: string;
  approver_type: 'role' | 'user' | 'department_head';
  approver_value: string;
  auto_approve_hours: number | null;
}

interface WorkflowTemplate {
  id: string;
  name: string;
  code: string;
  description: string;
  category: 'leave' | 'transfer' | 'payroll' | 'gap_filling';
  is_active: boolean;
  nodes: ApprovalNode[];
  created_at: string;
}

interface TemplateListResp {
  items: WorkflowTemplate[];
  total: number;
}

// ─── 枚举 ────────────────────────────────────────────────────────────────────

const categoryMap: Record<string, { text: string; color: string }> = {
  leave: { text: '请假审批', color: 'blue' },
  transfer: { text: '调岗审批', color: 'purple' },
  payroll: { text: '薪资审批', color: 'green' },
  gap_filling: { text: '补位审批', color: 'orange' },
};

const approverTypeMap: Record<string, string> = {
  role: '按角色',
  user: '指定用户',
  department_head: '部门负责人',
};

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function SettingsApprovalWorkflows() {
  const actionRef = useRef<ActionType>();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [currentTemplate, setCurrentTemplate] = useState<WorkflowTemplate | null>(null);
  const [nodes, setNodes] = useState<ApprovalNode[]>([]);

  const openDrawer = (template: WorkflowTemplate) => {
    setCurrentTemplate(template);
    setNodes([...(template.nodes || [])]);
    setDrawerOpen(true);
  };

  const saveNodes = async () => {
    if (!currentTemplate) return;
    try {
      await txFetch(`/api/v1/approval-engine/templates/${currentTemplate.id}`, {
        method: 'PUT',
        body: JSON.stringify({ nodes }),
      });
      message.success('审批流已保存');
      setDrawerOpen(false);
      actionRef.current?.reload();
    } catch {
      message.error('保存失败');
    }
  };

  const addNode = () => {
    setNodes((prev) => [
      ...prev,
      {
        step: prev.length + 1,
        name: `审批节点 ${prev.length + 1}`,
        approver_type: 'department_head',
        approver_value: '',
        auto_approve_hours: null,
      },
    ]);
  };

  const removeNode = (index: number) => {
    setNodes((prev) => {
      const next = prev.filter((_, i) => i !== index);
      return next.map((n, i) => ({ ...n, step: i + 1 }));
    });
  };

  const columns: ProColumns<WorkflowTemplate>[] = [
    {
      title: '流程名称',
      dataIndex: 'name',
      width: 160,
    },
    {
      title: '类型',
      dataIndex: 'category',
      width: 100,
      valueType: 'select',
      valueEnum: {
        leave: { text: '请假审批' },
        transfer: { text: '调岗审批' },
        payroll: { text: '薪资审批' },
        gap_filling: { text: '补位审批' },
      },
      render: (_, r) => {
        const c = categoryMap[r.category] || { text: r.category, color: 'default' };
        return <Tag color={c.color}>{c.text}</Tag>;
      },
    },
    {
      title: '描述',
      dataIndex: 'description',
      hideInSearch: true,
      ellipsis: true,
    },
    {
      title: '节点数',
      dataIndex: 'nodes',
      hideInSearch: true,
      width: 80,
      render: (_, r) => (r.nodes || []).length,
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      hideInSearch: true,
      width: 80,
      render: (_, r) =>
        r.is_active ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>,
    },
    {
      title: '操作',
      valueType: 'option',
      width: 120,
      render: (_, r) => (
        <Button
          type="link"
          size="small"
          icon={<SettingOutlined />}
          onClick={() => openDrawer(r)}
        >
          配置节点
        </Button>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Title level={4}>
        <BranchesOutlined style={{ marginRight: 8 }} />
        审批流配置
      </Title>

      <ProTable<WorkflowTemplate>
        actionRef={actionRef}
        columns={columns}
        rowKey="id"
        request={async (params) => {
          const query = new URLSearchParams();
          query.set('page', String(params.current || 1));
          query.set('size', String(params.pageSize || 20));
          if (params.category) query.set('category', params.category);
          try {
            const data = await txFetch<TemplateListResp>(
              `/api/v1/approval-engine/templates?${query.toString()}`,
            );
            return { data: data.items || [], total: data.total || 0, success: true };
          } catch {
            return { data: [], total: 0, success: true };
          }
        }}
        search={{ labelWidth: 'auto' }}
        pagination={{ defaultPageSize: 20 }}
      />

      {/* 节点配置 Drawer */}
      <Drawer
        title={`审批节点配置 - ${currentTemplate?.name || ''}`}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={520}
        extra={
          <Space>
            <Button onClick={() => setDrawerOpen(false)}>取消</Button>
            <Button type="primary" onClick={saveNodes}>保存</Button>
          </Space>
        }
      >
        {/* 审批流程可视化 */}
        <Steps
          direction="vertical"
          size="small"
          current={-1}
          items={nodes.map((n) => ({
            title: n.name,
            description: `${approverTypeMap[n.approver_type] || n.approver_type}${
              n.auto_approve_hours ? ` (${n.auto_approve_hours}h自动通过)` : ''
            }`,
          }))}
          style={{ marginBottom: 24 }}
        />

        {/* 节点列表 */}
        <List
          dataSource={nodes}
          renderItem={(node, index) => (
            <Card
              size="small"
              style={{ marginBottom: 8 }}
              extra={
                <Button
                  type="text"
                  danger
                  size="small"
                  icon={<DeleteOutlined />}
                  onClick={() => removeNode(index)}
                />
              }
            >
              <Space direction="vertical" style={{ width: '100%' }} size={4}>
                <Text strong>步骤 {node.step}: {node.name}</Text>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  审批人类型: {approverTypeMap[node.approver_type] || node.approver_type}
                </Text>
                {node.auto_approve_hours && (
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    超时自动通过: {node.auto_approve_hours}小时
                  </Text>
                )}
              </Space>
            </Card>
          )}
        />

        <ModalForm
          title="添加审批节点"
          trigger={
            <Button type="dashed" block icon={<PlusOutlined />} style={{ marginTop: 8 }}>
              添加节点
            </Button>
          }
          width={400}
          onFinish={async (values) => {
            setNodes((prev) => [
              ...prev,
              {
                step: prev.length + 1,
                name: values.name,
                approver_type: values.approver_type,
                approver_value: values.approver_value || '',
                auto_approve_hours: values.auto_approve_hours || null,
              },
            ]);
            return true;
          }}
        >
          <ProFormText name="name" label="节点名称" rules={[{ required: true }]} />
          <ProFormSelect
            name="approver_type"
            label="审批人类型"
            rules={[{ required: true }]}
            options={[
              { label: '部门负责人', value: 'department_head' },
              { label: '按角色', value: 'role' },
              { label: '指定用户', value: 'user' },
            ]}
          />
          <ProFormText name="approver_value" label="审批人/角色编码" />
          <ProFormDigit name="auto_approve_hours" label="超时自动通过(小时)" min={1} />
        </ModalForm>
      </Drawer>
    </div>
  );
}
