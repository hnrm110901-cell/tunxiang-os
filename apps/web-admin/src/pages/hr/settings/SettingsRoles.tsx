/**
 * SettingsRoles — 角色权限配置
 * 域F · 配置中心
 *
 * 功能：
 *  1. 角色列表 ProTable
 *  2. 权限配置 Drawer（勾选权限树）
 *
 * API:
 *  GET  /api/v1/roles
 *  GET  /api/v1/roles/{id}/permissions
 *  PUT  /api/v1/roles/{id}/permissions
 */

import { useRef, useState } from 'react';
import {
  Button,
  Drawer,
  message,
  Space,
  Tag,
  Tree,
  Typography,
} from 'antd';
import { PlusOutlined, SettingOutlined } from '@ant-design/icons';
import {
  ActionType,
  ModalForm,
  ProColumns,
  ProFormText,
  ProFormTextArea,
  ProTable,
} from '@ant-design/pro-components';
import { txFetchData } from '../../../api';

const { Title } = Typography;

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface Role {
  id: string;
  name: string;
  code: string;
  description: string;
  user_count: number;
  is_system: boolean;
  created_at: string;
}

interface RoleListResp {
  items: Role[];
  total: number;
}

interface PermissionNode {
  key: string;
  title: string;
  children?: PermissionNode[];
}

// ─── 权限树 ──────────────────────────────────────────────────────────────────

const PERMISSION_TREE: PermissionNode[] = [
  {
    key: 'hr',
    title: '人力资源',
    children: [
      { key: 'hr:employee:read', title: '查看员工' },
      { key: 'hr:employee:write', title: '编辑员工' },
      { key: 'hr:attendance:read', title: '查看考勤' },
      { key: 'hr:attendance:write', title: '考勤管理' },
      { key: 'hr:schedule:read', title: '查看排班' },
      { key: 'hr:schedule:write', title: '排班管理' },
      { key: 'hr:leave:read', title: '查看请假' },
      { key: 'hr:leave:approve', title: '审批请假' },
      { key: 'hr:payroll:read', title: '查看薪资' },
      { key: 'hr:payroll:write', title: '薪资管理' },
      { key: 'hr:performance:read', title: '查看绩效' },
      { key: 'hr:performance:write', title: '绩效管理' },
    ],
  },
  {
    key: 'agent',
    title: 'Agent中枢',
    children: [
      { key: 'agent:view', title: '查看Agent' },
      { key: 'agent:adopt', title: '采纳建议' },
      { key: 'agent:config', title: 'Agent配置' },
    ],
  },
  {
    key: 'compliance',
    title: '合规管理',
    children: [
      { key: 'compliance:alert:read', title: '查看预警' },
      { key: 'compliance:alert:resolve', title: '处理预警' },
      { key: 'compliance:scan', title: '触发扫描' },
    ],
  },
  {
    key: 'governance',
    title: '治理中心',
    children: [
      { key: 'governance:dashboard', title: '驾驶舱' },
      { key: 'governance:benchmark', title: '对标分析' },
      { key: 'governance:staffing', title: '编制治理' },
    ],
  },
  {
    key: 'settings',
    title: '系统设置',
    children: [
      { key: 'settings:role', title: '角色权限' },
      { key: 'settings:approval', title: '审批流配置' },
      { key: 'settings:audit', title: '审计日志' },
    ],
  },
];

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function SettingsRoles() {
  const actionRef = useRef<ActionType>();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [currentRole, setCurrentRole] = useState<Role | null>(null);
  const [checkedKeys, setCheckedKeys] = useState<string[]>([]);
  const [permLoading, setPermLoading] = useState(false);

  const loadPermissions = async (roleId: string) => {
    setPermLoading(true);
    try {
      const data = await txFetchData<{ permissions: string[] }>(
        `/api/v1/roles/${roleId}/permissions`,
      );
      setCheckedKeys(data.permissions || []);
    } catch {
      setCheckedKeys([]);
    } finally {
      setPermLoading(false);
    }
  };

  const savePermissions = async () => {
    if (!currentRole) return;
    try {
      await txFetchData(`/api/v1/roles/${currentRole.id}/permissions`, {
        method: 'PUT',
        body: JSON.stringify({ permissions: checkedKeys }),
      });
      message.success('权限已保存');
      setDrawerOpen(false);
    } catch {
      message.error('保存失败');
    }
  };

  const columns: ProColumns<Role>[] = [
    { title: '角色名称', dataIndex: 'name', width: 150 },
    { title: '角色编码', dataIndex: 'code', hideInSearch: true, width: 120 },
    { title: '描述', dataIndex: 'description', hideInSearch: true, ellipsis: true },
    {
      title: '用户数',
      dataIndex: 'user_count',
      hideInSearch: true,
      width: 80,
    },
    {
      title: '类型',
      dataIndex: 'is_system',
      hideInSearch: true,
      width: 80,
      render: (_, r) =>
        r.is_system ? <Tag color="blue">系统</Tag> : <Tag>自定义</Tag>,
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
          onClick={() => {
            setCurrentRole(r);
            setDrawerOpen(true);
            loadPermissions(r.id);
          }}
        >
          权限配置
        </Button>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Title level={4}>
        <SettingOutlined style={{ marginRight: 8 }} />
        角色权限
      </Title>

      <ProTable<Role>
        actionRef={actionRef}
        columns={columns}
        rowKey="id"
        request={async (params) => {
          const query = new URLSearchParams();
          query.set('page', String(params.current || 1));
          query.set('size', String(params.pageSize || 20));
          if (params.name) query.set('keyword', params.name);
          try {
            const data = await txFetchData<RoleListResp>(
              `/api/v1/roles?${query.toString()}`,
            );
            return { data: data.items || [], total: data.total || 0, success: true };
          } catch {
            return { data: [], total: 0, success: true };
          }
        }}
        search={{ labelWidth: 'auto' }}
        pagination={{ defaultPageSize: 20 }}
        toolBarRender={() => [
          <ModalForm
            key="create"
            title="新建角色"
            trigger={
              <Button type="primary" icon={<PlusOutlined />}>
                新建角色
              </Button>
            }
            onFinish={async (values) => {
              try {
                await txFetchData('/api/v1/roles', {
                  method: 'POST',
                  body: JSON.stringify(values),
                });
                message.success('角色已���建');
                actionRef.current?.reload();
                return true;
              } catch {
                message.error('创建失败');
                return false;
              }
            }}
          >
            <ProFormText name="name" label="角色名称" rules={[{ required: true }]} />
            <ProFormText name="code" label="角色编码" rules={[{ required: true }]} />
            <ProFormTextArea name="description" label="描述" />
          </ModalForm>,
        ]}
      />

      {/* 权限配置 Drawer */}
      <Drawer
        title={`权限配置 - ${currentRole?.name || ''}`}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={480}
        extra={
          <Space>
            <Button onClick={() => setDrawerOpen(false)}>取消</Button>
            <Button type="primary" onClick={savePermissions}>
              保存
            </Button>
          </Space>
        }
      >
        <Tree
          checkable
          defaultExpandAll
          checkedKeys={checkedKeys}
          onCheck={(keys) => setCheckedKeys(keys as string[])}
          treeData={PERMISSION_TREE}
        />
      </Drawer>
    </div>
  );
}
