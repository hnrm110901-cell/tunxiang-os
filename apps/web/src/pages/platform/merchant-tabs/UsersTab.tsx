import React, { useState } from 'react';
import {
  Table, Button, Modal, Form, Input, Select, Switch, Row, Col,
  message, Popconfirm, Tag, Typography,
} from 'antd';
import {
  PlusOutlined, UserAddOutlined, DeleteOutlined, MailOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { apiClient } from '../../../services/api';
import type { UserItem, StoreItem } from '../merchant-constants';
import { ROLE_LABELS, ROLE_OPTIONS } from '../merchant-constants';
import styles from './UsersTab.module.css';

const { Text } = Typography;

interface Props {
  brandId: string;
  users: UserItem[];
  stores: StoreItem[];
  onRefresh: () => void;
}

const UsersTab: React.FC<Props> = ({ brandId, users, stores, onRefresh }) => {
  const [addVisible, setAddVisible] = useState(false);
  const [userForm] = Form.useForm();

  const handleAddUser = async () => {
    try {
      const values = await userForm.validateFields();
      await apiClient.post(`/api/v1/merchants/${brandId}/users`, values);
      message.success('用户添加成功');
      setAddVisible(false);
      userForm.resetFields();
      onRefresh();
    } catch {
      message.error('添加用户失败');
    }
  };

  const handleToggleUser = async (userId: string) => {
    try {
      await apiClient.post(`/api/v1/merchants/${brandId}/users/${userId}/toggle-status`, {});
      message.success('用户状态已切换');
      onRefresh();
    } catch {
      message.error('操作失败');
    }
  };

  const handleRemoveUser = async (userId: string) => {
    try {
      await apiClient.delete(`/api/v1/merchants/${brandId}/users/${userId}`);
      message.success('用户已移除');
      onRefresh();
    } catch {
      message.error('移除失败');
    }
  };

  const columns: ColumnsType<UserItem> = [
    {
      title: '用户', dataIndex: 'username', key: 'username', width: 140,
      render: (_: unknown, r: UserItem) => (
        <div>
          <div style={{ fontWeight: 500 }}>{r.full_name || r.username}</div>
          <Text type="secondary" style={{ fontSize: 11 }}>{r.username}</Text>
        </div>
      ),
    },
    { title: '邮箱', dataIndex: 'email', key: 'email', width: 180, ellipsis: true },
    {
      title: '角色', dataIndex: 'role', key: 'role', width: 90,
      render: (v: string) => <Tag>{ROLE_LABELS[v] || v}</Tag>,
    },
    {
      title: '启用', dataIndex: 'is_active', key: 'is_active', width: 70,
      render: (v: boolean, r: UserItem) => (
        <Switch size="small" checked={v} onChange={() => handleToggleUser(r.id)} />
      ),
    },
    {
      title: '开通时间', dataIndex: 'created_at', key: 'created_at', width: 110,
      render: (v: string | null) => v ? new Date(v).toLocaleDateString('zh-CN') : '-',
    },
    {
      title: '操作', key: 'action', width: 60,
      render: (_: unknown, r: UserItem) => (
        <Popconfirm title={`确认移除用户「${r.username}」?`} onConfirm={() => handleRemoveUser(r.id)}>
          <Button type="text" size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      ),
    },
  ];

  return (
    <div>
      <div className={styles.header}>
        <span className={styles.title}><UserAddOutlined /> 用户列表 ({users.length})</span>
        <Button type="primary" size="small" icon={<PlusOutlined />} onClick={() => setAddVisible(true)}>
          添加用户
        </Button>
      </div>
      <Table<UserItem>
        rowKey="id"
        columns={columns}
        dataSource={users}
        pagination={false}
        size="small"
        locale={{ emptyText: '暂无用户，点击上方按钮添加' }}
      />

      <Modal
        title="添加用户"
        open={addVisible}
        onCancel={() => { setAddVisible(false); userForm.resetFields(); }}
        onOk={handleAddUser}
      >
        <Form form={userForm} layout="vertical">
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="username" label="用户名" rules={[{ required: true }]}>
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="full_name" label="姓名"><Input /></Form.Item>
            </Col>
          </Row>
          <Form.Item name="email" label="邮箱" rules={[{ required: true, type: 'email' }]}>
            <Input prefix={<MailOutlined />} />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, min: 6 }]}>
            <Input.Password />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="role" label="角色" initialValue="waiter">
                <Select options={ROLE_OPTIONS} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="store_id" label="所属门店">
                <Select
                  allowClear
                  placeholder="可选"
                  options={stores.map(s => ({ value: s.id, label: s.name }))}
                />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </div>
  );
};

export default UsersTab;
