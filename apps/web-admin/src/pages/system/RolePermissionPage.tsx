/**
 * RolePermissionPage -- 权限与角色管理
 * 域F . 系统设置 . 权限管理
 *
 * Tab1: 角色管理 -- ProTable + 新建/编辑角色 ModalForm (权限树)
 * Tab2: 用户角色分配 -- ProTable + 编辑角色/批量设置
 * Tab3: 操作日志 -- ProTable (只读)
 *
 * API: tx-org :8012, try/catch 降级 Mock
 */

import { useEffect, useRef, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  DatePicker,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Tabs,
  Tag,
  Tree,
  Typography,
  message,
} from 'antd';
import {
  DeleteOutlined,
  EditOutlined,
  LockOutlined,
  PlusOutlined,
  ReloadOutlined,
  SafetyOutlined,
  SearchOutlined,
  StopOutlined,
  TeamOutlined,
  UserOutlined,
} from '@ant-design/icons';
import {
  ActionType,
  ModalForm,
  ProColumns,
  ProFormText,
  ProFormTextArea,
  ProTable,
} from '@ant-design/pro-components';
import dayjs from 'dayjs';

const { Title } = Typography;
const { RangePicker } = DatePicker;

const BASE = 'http://localhost:8012';

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  类型
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

interface PermNode {
  key: string;
  title: string;
  children?: PermNode[];
}

interface RoleItem {
  id: string;
  name: string;
  description: string;
  is_preset: boolean;
  status: string;
  permission_count: number;
  user_count: number;
  permissions: string[];
}

interface UserRoleItem {
  id: string;
  name: string;
  phone: string;
  store: string;
  roles: string[];
  last_login: string;
  status: string;
}

interface AuditLogItem {
  id: string;
  time: string;
  operator: string;
  action: string;
  target: string;
  ip: string;
  detail: string;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  降级 Mock 数据
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const FALLBACK_PERM_TREE: PermNode[] = [
  { key: 'store', title: '门店管理', children: [
    { key: 'store:view', title: '查看' }, { key: 'store:create', title: '新增' },
    { key: 'store:edit', title: '编辑' }, { key: 'store:delete', title: '删除' },
    { key: 'store:approve', title: '审批' },
  ]},
  { key: 'dish', title: '菜品管理', children: [
    { key: 'dish:view', title: '查看' }, { key: 'dish:create', title: '新增' },
    { key: 'dish:edit', title: '编辑' }, { key: 'dish:delete', title: '删除' },
    { key: 'dish:approve', title: '审批' },
  ]},
  { key: 'order', title: '订单管理', children: [
    { key: 'order:view', title: '查看' }, { key: 'order:create', title: '新增' },
    { key: 'order:edit', title: '编辑' }, { key: 'order:delete', title: '删除' },
    { key: 'order:approve', title: '审批' },
  ]},
  { key: 'member', title: '会员管理', children: [
    { key: 'member:view', title: '查看' }, { key: 'member:create', title: '新增' },
    { key: 'member:edit', title: '编辑' }, { key: 'member:delete', title: '删除' },
    { key: 'member:approve', title: '审批' },
  ]},
  { key: 'finance', title: '财务管理', children: [
    { key: 'finance:view', title: '查看' }, { key: 'finance:create', title: '新增' },
    { key: 'finance:edit', title: '编辑' }, { key: 'finance:delete', title: '删除' },
    { key: 'finance:approve', title: '审批' },
  ]},
  { key: 'marketing', title: '营销管理', children: [
    { key: 'marketing:view', title: '查看' }, { key: 'marketing:create', title: '新增' },
    { key: 'marketing:edit', title: '编辑' }, { key: 'marketing:delete', title: '删除' },
    { key: 'marketing:approve', title: '审批' },
  ]},
  { key: 'supply', title: '供应链', children: [
    { key: 'supply:view', title: '查看' }, { key: 'supply:create', title: '新增' },
    { key: 'supply:edit', title: '编辑' }, { key: 'supply:delete', title: '删除' },
    { key: 'supply:approve', title: '审批' },
  ]},
  { key: 'system', title: '系统设置', children: [
    { key: 'system:view', title: '查看' }, { key: 'system:create', title: '新增' },
    { key: 'system:edit', title: '编辑' }, { key: 'system:delete', title: '删除' },
    { key: 'system:approve', title: '审批' },
  ]},
];

const ALL_PERM_KEYS = FALLBACK_PERM_TREE.flatMap(g => (g.children ?? []).map(c => c.key));

const FALLBACK_ROLES: RoleItem[] = [
  { id: 'r-001', name: '超级管理员', description: '拥有全部权限', is_preset: true, status: 'active', permission_count: 40, user_count: 2, permissions: ALL_PERM_KEYS },
  { id: 'r-002', name: '品牌经理', description: '品牌全局管理', is_preset: true, status: 'active', permission_count: 35, user_count: 3, permissions: ALL_PERM_KEYS.filter(k => !k.startsWith('system:')) },
  { id: 'r-003', name: '区域经理', description: '区域运营管理', is_preset: true, status: 'active', permission_count: 9, user_count: 5, permissions: ['store:view', 'store:edit', 'dish:view', 'order:view', 'order:edit', 'member:view', 'finance:view', 'marketing:view', 'supply:view'] },
  { id: 'r-004', name: '店长', description: '单店全权管理', is_preset: true, status: 'active', permission_count: 10, user_count: 12, permissions: ['store:view', 'store:edit', 'dish:view', 'order:view', 'order:create', 'order:edit', 'member:view', 'member:create', 'finance:view', 'supply:view'] },
  { id: 'r-005', name: '收银员', description: '收银操作权限', is_preset: true, status: 'active', permission_count: 4, user_count: 28, permissions: ['order:view', 'order:create', 'order:edit', 'member:view'] },
  { id: 'r-006', name: '服务员', description: '点餐服务权限', is_preset: true, status: 'active', permission_count: 4, user_count: 45, permissions: ['order:view', 'order:create', 'dish:view', 'member:view'] },
  { id: 'r-007', name: '厨师长', description: '后厨管理权限', is_preset: true, status: 'active', permission_count: 5, user_count: 8, permissions: ['dish:view', 'dish:edit', 'order:view', 'supply:view', 'supply:create'] },
  { id: 'r-008', name: '财务', description: '财务数据查看与审批', is_preset: true, status: 'active', permission_count: 5, user_count: 4, permissions: ['finance:view', 'finance:create', 'finance:edit', 'finance:approve', 'order:view'] },
];

const FALLBACK_USERS: UserRoleItem[] = [
  { id: 'u-001', name: '张伟', phone: '138****1234', store: '旗舰店', roles: ['超级管理员'], last_login: '2026-04-02 09:30:00', status: 'active' },
  { id: 'u-002', name: '李娜', phone: '139****5678', store: '万达店', roles: ['品牌经理'], last_login: '2026-04-02 08:15:00', status: 'active' },
  { id: 'u-003', name: '王芳', phone: '136****9012', store: '步行街店', roles: ['店长'], last_login: '2026-04-01 18:20:00', status: 'active' },
  { id: 'u-004', name: '赵敏', phone: '137****3456', store: '大学城店', roles: ['收银员'], last_login: '2026-04-02 07:55:00', status: 'active' },
  { id: 'u-005', name: '刘洋', phone: '135****7890', store: '旗舰店', roles: ['区域经理'], last_login: '2026-04-01 17:00:00', status: 'active' },
  { id: 'u-006', name: '陈强', phone: '133****2345', store: '步行街店', roles: ['厨师长'], last_login: '2026-04-02 06:30:00', status: 'active' },
  { id: 'u-007', name: '杨柳', phone: '131****6789', store: '万达店', roles: ['服务员'], last_login: '2026-03-31 20:00:00', status: 'active' },
  { id: 'u-008', name: '黄蕾', phone: '132****0123', store: '旗舰店', roles: ['财务'], last_login: '2026-04-02 09:00:00', status: 'active' },
];

const FALLBACK_LOGS: AuditLogItem[] = [
  { id: 'log-001', time: '2026-04-02 10:15:00', operator: '张伟', action: '修改权限', target: '品牌经理', ip: '192.168.1.100', detail: '新增营销管理-审批权限' },
  { id: 'log-002', time: '2026-04-02 09:30:00', operator: '张伟', action: '登录', target: '系统', ip: '192.168.1.100', detail: '总部后台登录成功' },
  { id: 'log-003', time: '2026-04-02 08:15:00', operator: '李娜', action: '修改权限', target: '区域经理', ip: '10.0.0.55', detail: '新增供应链-新增权限' },
  { id: 'log-004', time: '2026-04-02 07:00:00', operator: '张伟', action: '删除', target: '临时活动角色', ip: '192.168.1.100', detail: '删除自定义角色：临时活动角色' },
  { id: 'log-005', time: '2026-04-01 17:00:00', operator: '李娜', action: '审批', target: '门店折扣申请#2046', ip: '10.0.0.55', detail: '审批通过，折扣率85%' },
  { id: 'log-006', time: '2026-04-01 12:00:00', operator: '张伟', action: '导出', target: '月度考勤报表', ip: '192.168.1.100', detail: '导出2026年3月全员考勤数据' },
];

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  API 调用（try/catch 降级 Mock）
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options?.headers as Record<string, string> | undefined),
    },
  });
  const json = await resp.json();
  if (!json.ok) throw new Error(json.error?.message || 'API Error');
  return json.data as T;
}

async function fetchPermTree(): Promise<PermNode[]> {
  try {
    return await apiFetch<PermNode[]>('/api/v1/org/permissions/tree');
  } catch {
    return FALLBACK_PERM_TREE;
  }
}

interface PaginatedResp<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
}

async function fetchRoles(page: number, size: number, keyword: string): Promise<PaginatedResp<RoleItem>> {
  try {
    return await apiFetch<PaginatedResp<RoleItem>>(
      `/api/v1/org/roles-admin?page=${page}&size=${size}&keyword=${encodeURIComponent(keyword)}`
    );
  } catch {
    const filtered = keyword
      ? FALLBACK_ROLES.filter(r => r.name.includes(keyword) || r.description.includes(keyword))
      : FALLBACK_ROLES;
    return { items: filtered.slice((page - 1) * size, page * size), total: filtered.length, page, size };
  }
}

async function createRole(name: string, description: string, permissions: string[]): Promise<RoleItem> {
  try {
    return await apiFetch<RoleItem>('/api/v1/org/roles-admin', {
      method: 'POST',
      body: JSON.stringify({ name, description, permissions }),
    });
  } catch {
    const newRole: RoleItem = {
      id: `r-local-${Date.now()}`,
      name,
      description,
      is_preset: false,
      status: 'active',
      permission_count: permissions.length,
      user_count: 0,
      permissions,
    };
    FALLBACK_ROLES.push(newRole);
    return newRole;
  }
}

async function updateRolePerms(roleId: string, permissions: string[], description?: string): Promise<void> {
  try {
    await apiFetch(`/api/v1/org/roles-admin/${roleId}`, {
      method: 'PATCH',
      body: JSON.stringify({ permissions, description }),
    });
  } catch {
    const r = FALLBACK_ROLES.find(x => x.id === roleId);
    if (r) {
      r.permissions = permissions;
      r.permission_count = permissions.length;
      if (description !== undefined) r.description = description;
    }
  }
}

async function deleteRole(roleId: string): Promise<void> {
  try {
    await apiFetch(`/api/v1/org/roles-admin/${roleId}`, { method: 'DELETE' });
  } catch {
    const idx = FALLBACK_ROLES.findIndex(x => x.id === roleId);
    if (idx >= 0) FALLBACK_ROLES.splice(idx, 1);
  }
}

async function fetchUsers(page: number, size: number, keyword: string): Promise<PaginatedResp<UserRoleItem>> {
  try {
    return await apiFetch<PaginatedResp<UserRoleItem>>(
      `/api/v1/org/user-roles?page=${page}&size=${size}&keyword=${encodeURIComponent(keyword)}`
    );
  } catch {
    const filtered = keyword
      ? FALLBACK_USERS.filter(u => u.name.includes(keyword) || u.phone.includes(keyword))
      : FALLBACK_USERS;
    return { items: filtered.slice((page - 1) * size, page * size), total: filtered.length, page, size };
  }
}

async function updateUserRoles(userId: string, roles: string[]): Promise<void> {
  try {
    await apiFetch(`/api/v1/org/user-roles/${userId}`, {
      method: 'PATCH',
      body: JSON.stringify({ roles }),
    });
  } catch {
    const u = FALLBACK_USERS.find(x => x.id === userId);
    if (u) u.roles = roles;
  }
}

async function batchSetRoles(userIds: string[], roles: string[]): Promise<void> {
  try {
    await apiFetch('/api/v1/org/user-roles/batch', {
      method: 'POST',
      body: JSON.stringify({ user_ids: userIds, roles }),
    });
  } catch {
    for (const u of FALLBACK_USERS) {
      if (userIds.includes(u.id)) u.roles = roles;
    }
  }
}

async function fetchAuditLogs(
  page: number, size: number, keyword: string, action: string
): Promise<PaginatedResp<AuditLogItem>> {
  try {
    let url = `/api/v1/org/audit-logs?page=${page}&size=${size}`;
    if (keyword) url += `&keyword=${encodeURIComponent(keyword)}`;
    if (action) url += `&action=${encodeURIComponent(action)}`;
    return await apiFetch<PaginatedResp<AuditLogItem>>(url);
  } catch {
    let filtered = FALLBACK_LOGS;
    if (keyword) filtered = filtered.filter(l => l.operator.includes(keyword) || l.target.includes(keyword));
    if (action) filtered = filtered.filter(l => l.action === action);
    return { items: filtered.slice((page - 1) * size, page * size), total: filtered.length, page, size };
  }
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  操作日志 Tag 颜色
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const ACTION_TAG_COLOR: Record<string, string> = {
  '登录': 'blue',
  '修改权限': 'orange',
  '删除': 'red',
  '审批': 'green',
  '导出': 'purple',
};

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  角色名列表（用于用户角色 Select）
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const PRESET_ROLE_NAMES = ['超级管理员', '品牌经理', '区域经理', '店长', '收银员', '服务员', '厨师长', '财务'];

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  组件
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

export function RolePermissionPage() {
  const [activeTab, setActiveTab] = useState('roles');
  const [permTree, setPermTree] = useState<PermNode[]>([]);

  // 角色管理状态
  const roleTableRef = useRef<ActionType>();
  const [roleModalOpen, setRoleModalOpen] = useState(false);
  const [editingRole, setEditingRole] = useState<RoleItem | null>(null);
  const [checkedKeys, setCheckedKeys] = useState<string[]>([]);
  const [roleName, setRoleName] = useState('');
  const [roleDesc, setRoleDesc] = useState('');

  // 用户角色分配
  const userTableRef = useRef<ActionType>();
  const [selectedUserIds, setSelectedUserIds] = useState<string[]>([]);
  const [batchRoleModalOpen, setBatchRoleModalOpen] = useState(false);
  const [batchRoles, setBatchRoles] = useState<string[]>([]);
  const [editUserModalOpen, setEditUserModalOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<UserRoleItem | null>(null);
  const [editUserRoles, setEditUserRoles] = useState<string[]>([]);

  // 日志
  const logTableRef = useRef<ActionType>();

  useEffect(() => {
    fetchPermTree().then(setPermTree);
  }, []);

  // ─── Tab1: 角色管理 ───

  const openCreateRole = () => {
    setEditingRole(null);
    setRoleName('');
    setRoleDesc('');
    setCheckedKeys([]);
    setRoleModalOpen(true);
  };

  const openEditRole = (role: RoleItem) => {
    setEditingRole(role);
    setRoleName(role.name);
    setRoleDesc(role.description);
    setCheckedKeys(role.permissions);
    setRoleModalOpen(true);
  };

  const handleSaveRole = async () => {
    if (!roleName.trim()) {
      message.warning('请输入角色名称');
      return;
    }
    if (editingRole) {
      await updateRolePerms(editingRole.id, checkedKeys, roleDesc);
      message.success('角色权限已更新');
    } else {
      await createRole(roleName, roleDesc, checkedKeys);
      message.success('角色创建成功');
    }
    setRoleModalOpen(false);
    roleTableRef.current?.reload();
  };

  const handleDeleteRole = async (roleId: string) => {
    await deleteRole(roleId);
    message.success('角色已删除');
    roleTableRef.current?.reload();
  };

  const roleColumns: ProColumns<RoleItem>[] = [
    {
      title: '角色名',
      dataIndex: 'name',
      width: 140,
      render: (_, record) => (
        <Space>
          {record.is_preset ? <LockOutlined style={{ color: '#FF6B35' }} /> : <SafetyOutlined />}
          <span style={{ fontWeight: record.is_preset ? 600 : 400 }}>{record.name}</span>
          {record.is_preset && <Tag color="volcano" style={{ fontSize: 11 }}>预设</Tag>}
        </Space>
      ),
    },
    { title: '描述', dataIndex: 'description', ellipsis: true, width: 200 },
    {
      title: '权限数量',
      dataIndex: 'permission_count',
      width: 100,
      sorter: (a, b) => a.permission_count - b.permission_count,
      render: (val) => <Badge count={val as number} style={{ backgroundColor: '#FF6B35' }} overflowCount={999} />,
    },
    {
      title: '用户数量',
      dataIndex: 'user_count',
      width: 100,
      sorter: (a, b) => a.user_count - b.user_count,
      render: (val) => <Space><TeamOutlined />{val as number}</Space>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 80,
      render: (val) => (
        <Tag color={val === 'active' ? 'green' : 'default'}>
          {val === 'active' ? '启用' : '停用'}
        </Tag>
      ),
    },
    {
      title: '操作',
      width: 150,
      valueType: 'option',
      render: (_, record) => [
        <Button
          key="edit"
          type="link"
          size="small"
          icon={<EditOutlined />}
          onClick={() => openEditRole(record)}
        >
          编辑
        </Button>,
        !record.is_preset && (
          <Popconfirm
            key="delete"
            title="确认删除此角色？"
            description="删除后不可恢复，已分配此角色的用户将失去对应权限。"
            onConfirm={() => handleDeleteRole(record.id)}
            okText="确认删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        ),
      ],
    },
  ];

  // ─── Tab2: 用户角色分配 ───

  const openEditUser = (user: UserRoleItem) => {
    setEditingUser(user);
    setEditUserRoles(user.roles);
    setEditUserModalOpen(true);
  };

  const handleSaveUserRoles = async () => {
    if (!editingUser) return;
    await updateUserRoles(editingUser.id, editUserRoles);
    message.success(`${editingUser.name} 的角色已更新`);
    setEditUserModalOpen(false);
    userTableRef.current?.reload();
  };

  const handleBatchSetRoles = async () => {
    if (selectedUserIds.length === 0) {
      message.warning('请先选择用户');
      return;
    }
    if (batchRoles.length === 0) {
      message.warning('请选择至少一个角色');
      return;
    }
    await batchSetRoles(selectedUserIds, batchRoles);
    message.success(`已为 ${selectedUserIds.length} 位用户设置角色`);
    setBatchRoleModalOpen(false);
    setBatchRoles([]);
    setSelectedUserIds([]);
    userTableRef.current?.reload();
  };

  const handleToggleUserStatus = async (user: UserRoleItem) => {
    const newStatus = user.status === 'active' ? 'disabled' : 'active';
    // Mock: 更新本地
    const u = FALLBACK_USERS.find(x => x.id === user.id);
    if (u) u.status = newStatus;
    message.success(`${user.name} 已${newStatus === 'active' ? '启用' : '禁用'}`);
    userTableRef.current?.reload();
  };

  const userColumns: ProColumns<UserRoleItem>[] = [
    {
      title: '用户名',
      dataIndex: 'name',
      width: 100,
      render: (_, record) => (
        <Space>
          <UserOutlined />
          <span>{record.name}</span>
        </Space>
      ),
    },
    { title: '手机号', dataIndex: 'phone', width: 130 },
    { title: '门店', dataIndex: 'store', width: 120 },
    {
      title: '当前角色',
      dataIndex: 'roles',
      width: 200,
      render: (_, record) => (
        <Space wrap>
          {record.roles.map(r => (
            <Tag key={r} color="orange">{r}</Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '最近登录',
      dataIndex: 'last_login',
      width: 170,
      render: (val) => <span style={{ color: '#999' }}>{val as string}</span>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 80,
      render: (val) => (
        <Tag color={val === 'active' ? 'green' : 'red'}>
          {val === 'active' ? '正常' : '已禁用'}
        </Tag>
      ),
    },
    {
      title: '操作',
      width: 180,
      valueType: 'option',
      render: (_, record) => [
        <Button
          key="edit-role"
          type="link"
          size="small"
          icon={<EditOutlined />}
          onClick={() => openEditUser(record)}
        >
          编辑角色
        </Button>,
        <Popconfirm
          key="toggle"
          title={`确认${record.status === 'active' ? '禁用' : '启用'}此账号？`}
          onConfirm={() => handleToggleUserStatus(record)}
          okText="确认"
          cancelText="取消"
        >
          <Button
            type="link"
            size="small"
            danger={record.status === 'active'}
            icon={record.status === 'active' ? <StopOutlined /> : <SafetyOutlined />}
          >
            {record.status === 'active' ? '禁用' : '启用'}
          </Button>
        </Popconfirm>,
      ],
    },
  ];

  // ─── Tab3: 操作日志 ───

  const logColumns: ProColumns<AuditLogItem>[] = [
    {
      title: '操作时间',
      dataIndex: 'time',
      width: 170,
      sorter: (a, b) => a.time.localeCompare(b.time),
    },
    { title: '操作人', dataIndex: 'operator', width: 100 },
    {
      title: '操作类型',
      dataIndex: 'action',
      width: 110,
      render: (val) => (
        <Tag color={ACTION_TAG_COLOR[val as string] || 'default'}>{val as string}</Tag>
      ),
      filters: [
        { text: '登录', value: '登录' },
        { text: '修改权限', value: '修改权限' },
        { text: '删除', value: '删除' },
        { text: '审批', value: '审批' },
        { text: '导出', value: '导出' },
      ],
      onFilter: (value, record) => record.action === value,
    },
    { title: '目标', dataIndex: 'target', width: 160, ellipsis: true },
    { title: 'IP地址', dataIndex: 'ip', width: 140 },
    { title: '详情', dataIndex: 'detail', ellipsis: true },
  ];

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  //  渲染
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  return (
    <div style={{ padding: '24px 32px', minHeight: '100vh', backgroundColor: '#f5f5f5' }}>
      <Title level={3} style={{ marginBottom: 24 }}>
        <SafetyOutlined style={{ color: '#FF6B35', marginRight: 8 }} />
        权限与角色管理
      </Title>

      <Card>
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
          {
            key: 'roles',
            label: <span><LockOutlined /> 角色管理</span>,
            children: (
              <>
                <ProTable<RoleItem>
                  actionRef={roleTableRef}
                  rowKey="id"
                  columns={roleColumns}
                  request={async (params) => {
                    const res = await fetchRoles(
                      params.current ?? 1,
                      params.pageSize ?? 20,
                      (params.name as string) || ''
                    );
                    return { data: res.items, total: res.total, success: true };
                  }}
                  search={false}
                  toolBarRender={() => [
                    <Button
                      key="create"
                      type="primary"
                      icon={<PlusOutlined />}
                      onClick={openCreateRole}
                      style={{ backgroundColor: '#FF6B35', borderColor: '#FF6B35' }}
                    >
                      新建角色
                    </Button>,
                  ]}
                  pagination={{ pageSize: 10, showSizeChanger: true }}
                  headerTitle="角色列表"
                />

                {/* 新建/编辑角色 Modal */}
                <Modal
                  title={editingRole ? `编辑角色: ${editingRole.name}` : '新建角色'}
                  open={roleModalOpen}
                  onCancel={() => setRoleModalOpen(false)}
                  onOk={handleSaveRole}
                  okText={editingRole ? '保存' : '创建'}
                  cancelText="取消"
                  width={640}
                  okButtonProps={{ style: { backgroundColor: '#FF6B35', borderColor: '#FF6B35' } }}
                >
                  <div style={{ marginBottom: 16 }}>
                    <div style={{ marginBottom: 8, fontWeight: 500 }}>角色名称</div>
                    <Input
                      value={roleName}
                      onChange={e => setRoleName(e.target.value)}
                      placeholder="请输入角色名称"
                      disabled={editingRole?.is_preset}
                      maxLength={50}
                    />
                  </div>
                  <div style={{ marginBottom: 16 }}>
                    <div style={{ marginBottom: 8, fontWeight: 500 }}>角色描述</div>
                    <Input.TextArea
                      value={roleDesc}
                      onChange={e => setRoleDesc(e.target.value)}
                      placeholder="请输入角色描述"
                      rows={2}
                      maxLength={200}
                    />
                  </div>
                  <div>
                    <div style={{ marginBottom: 8, fontWeight: 500 }}>
                      权限配置 <span style={{ color: '#999', fontWeight: 400 }}>（已选 {checkedKeys.length} 项）</span>
                    </div>
                    <div style={{ border: '1px solid #d9d9d9', borderRadius: 6, padding: 12, maxHeight: 360, overflow: 'auto' }}>
                      <Tree
                        checkable
                        treeData={permTree.length > 0 ? permTree : FALLBACK_PERM_TREE}
                        checkedKeys={checkedKeys}
                        onCheck={(checked) => {
                          const keys = Array.isArray(checked) ? checked : checked.checked;
                          setCheckedKeys(keys as string[]);
                        }}
                        defaultExpandAll
                      />
                    </div>
                  </div>
                </Modal>
              </>
            ),
          },
          {
            key: 'users',
            label: <span><TeamOutlined /> 用户角色分配</span>,
            children: (
              <>
                <ProTable<UserRoleItem>
                  actionRef={userTableRef}
                  rowKey="id"
                  columns={userColumns}
                  request={async (params) => {
                    const keyword = (params.name as string) || (params.phone as string) || '';
                    const res = await fetchUsers(params.current ?? 1, params.pageSize ?? 20, keyword);
                    return { data: res.items, total: res.total, success: true };
                  }}
                  search={false}
                  rowSelection={{
                    selectedRowKeys: selectedUserIds,
                    onChange: (keys) => setSelectedUserIds(keys as string[]),
                  }}
                  toolBarRender={() => [
                    <Button
                      key="batch"
                      icon={<TeamOutlined />}
                      disabled={selectedUserIds.length === 0}
                      onClick={() => setBatchRoleModalOpen(true)}
                    >
                      批量设置角色 {selectedUserIds.length > 0 && `(${selectedUserIds.length})`}
                    </Button>,
                  ]}
                  pagination={{ pageSize: 10, showSizeChanger: true }}
                  headerTitle="用户列表"
                />

                {/* 编辑用户角色 Modal */}
                <Modal
                  title={`编辑角色: ${editingUser?.name || ''}`}
                  open={editUserModalOpen}
                  onCancel={() => setEditUserModalOpen(false)}
                  onOk={handleSaveUserRoles}
                  okText="保存"
                  cancelText="取消"
                  okButtonProps={{ style: { backgroundColor: '#FF6B35', borderColor: '#FF6B35' } }}
                >
                  <div style={{ marginBottom: 8, fontWeight: 500 }}>分配角色</div>
                  <Select
                    mode="multiple"
                    style={{ width: '100%' }}
                    value={editUserRoles}
                    onChange={setEditUserRoles}
                    placeholder="请选择角色"
                    options={PRESET_ROLE_NAMES.map(r => ({ label: r, value: r }))}
                  />
                </Modal>

                {/* 批量设置角色 Modal */}
                <Modal
                  title={`批量设置角色（已选 ${selectedUserIds.length} 人）`}
                  open={batchRoleModalOpen}
                  onCancel={() => setBatchRoleModalOpen(false)}
                  onOk={handleBatchSetRoles}
                  okText="确认设置"
                  cancelText="取消"
                  okButtonProps={{ style: { backgroundColor: '#FF6B35', borderColor: '#FF6B35' } }}
                >
                  <div style={{ marginBottom: 8, fontWeight: 500 }}>选择角色</div>
                  <Select
                    mode="multiple"
                    style={{ width: '100%' }}
                    value={batchRoles}
                    onChange={setBatchRoles}
                    placeholder="请选择要批量设置的角色"
                    options={PRESET_ROLE_NAMES.map(r => ({ label: r, value: r }))}
                  />
                </Modal>
              </>
            ),
          },
          {
            key: 'logs',
            label: <span><SearchOutlined /> 操作日志</span>,
            children: (
              <ProTable<AuditLogItem>
                actionRef={logTableRef}
                rowKey="id"
                columns={logColumns}
                request={async (params, _sort, filter) => {
                  const keyword = (params.operator as string) || '';
                  const action = filter?.action?.[0] as string || '';
                  const res = await fetchAuditLogs(
                    params.current ?? 1,
                    params.pageSize ?? 20,
                    keyword,
                    action
                  );
                  return { data: res.items, total: res.total, success: true };
                }}
                search={false}
                toolBarRender={() => [
                  <Input.Search
                    key="search"
                    placeholder="搜索操作人"
                    allowClear
                    style={{ width: 200 }}
                    onSearch={() => logTableRef.current?.reload()}
                  />,
                ]}
                pagination={{ pageSize: 10, showSizeChanger: true }}
                headerTitle="操作日志"
              />
            ),
          },
        ]} />
      </Card>
    </div>
  );
}
