/**
 * OrgStructure — 组织架构树
 * Sprint 5 · 员工主档
 *
 * API: GET  /api/v1/org-structure/tree
 *      POST /api/v1/org-structure/departments
 *      PUT  /api/v1/org-structure/departments/{id}
 */

import { useEffect, useState } from 'react';
import {
  Button,
  Card,
  Col,
  Descriptions,
  Popconfirm,
  Row,
  Space,
  Tree,
  Typography,
  message,
} from 'antd';
import {
  ApartmentOutlined,
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  ShopOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import {
  ModalForm,
  ProFormSelect,
  ProFormText,
} from '@ant-design/pro-components';
import type { DataNode } from 'antd/es/tree';
import { txFetchData } from '../../../api';

const { Title, Text } = Typography;

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface OrgNode {
  id: string;
  name: string;
  type: 'group' | 'brand' | 'region' | 'store' | 'department';
  head_name: string | null;
  employee_count: number;
  children: OrgNode[];
}

// ─── 工具 ────────────────────────────────────────────────────────────────────

const typeIcon: Record<string, React.ReactNode> = {
  group: <ApartmentOutlined />,
  brand: <ShopOutlined style={{ color: '#FF6B35' }} />,
  region: <ApartmentOutlined style={{ color: '#185FA5' }} />,
  store: <ShopOutlined style={{ color: '#0F6E56' }} />,
  department: <TeamOutlined />,
};

const typeLabel: Record<string, string> = {
  group: '集团',
  brand: '品牌',
  region: '区域',
  store: '门店',
  department: '部门',
};

function toTreeData(nodes: OrgNode[]): DataNode[] {
  return nodes.map((n) => ({
    key: n.id,
    title: (
      <Space size={4}>
        {typeIcon[n.type]}
        <span>{n.name}</span>
        <Text type="secondary" style={{ fontSize: 12 }}>({n.employee_count}人)</Text>
      </Space>
    ),
    children: n.children?.length ? toTreeData(n.children) : undefined,
  }));
}

function findNode(nodes: OrgNode[], id: string): OrgNode | null {
  for (const n of nodes) {
    if (n.id === id) return n;
    if (n.children) {
      const found = findNode(n.children, id);
      if (found) return found;
    }
  }
  return null;
}

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function OrgStructure() {
  const [tree, setTree] = useState<OrgNode[]>([]);
  const [selected, setSelected] = useState<OrgNode | null>(null);
  const [loading, setLoading] = useState(true);
  const [addVisible, setAddVisible] = useState(false);
  const [editVisible, setEditVisible] = useState(false);

  const loadTree = async () => {
    setLoading(true);
    try {
      const resp = await txFetchData<OrgNode[]>('/api/v1/org-structure/tree');
      setTree(resp ?? []);
    } catch {
      message.error('加载组织架构失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadTree();
  }, []);

  const handleSelect = (keys: React.Key[]) => {
    if (keys.length === 0) {
      setSelected(null);
      return;
    }
    const node = findNode(tree, keys[0] as string);
    setSelected(node);
  };

  const handleDelete = async () => {
    if (!selected) return;
    await txFetchData(`/api/v1/org-structure/departments/${selected.id}`, { method: 'DELETE' });
    message.success('删除成功');
    setSelected(null);
    loadTree();
  };

  return (
    <Row gutter={16}>
      {/* 左侧：组织树 */}
      <Col span={10}>
        <Card
          title="组织架构"
          loading={loading}
          extra={
            <Button
              type="primary"
              size="small"
              icon={<PlusOutlined />}
              onClick={() => setAddVisible(true)}
            >
              新增
            </Button>
          }
        >
          <Tree
            showLine
            defaultExpandAll
            treeData={toTreeData(tree)}
            onSelect={handleSelect}
          />
        </Card>
      </Col>

      {/* 右侧：选中节点详情 */}
      <Col span={14}>
        <Card title={selected ? `${selected.name} 详情` : '请选择节点'}>
          {selected ? (
            <>
              <Descriptions column={1} bordered size="small">
                <Descriptions.Item label="名称">{selected.name}</Descriptions.Item>
                <Descriptions.Item label="类型">
                  <Space>{typeIcon[selected.type]} {typeLabel[selected.type]}</Space>
                </Descriptions.Item>
                <Descriptions.Item label="负责人">{selected.head_name ?? '未设置'}</Descriptions.Item>
                <Descriptions.Item label="员工数">{selected.employee_count}</Descriptions.Item>
              </Descriptions>
              <Space style={{ marginTop: 16 }}>
                <Button icon={<PlusOutlined />} onClick={() => setAddVisible(true)}>
                  新增子节点
                </Button>
                <Button icon={<EditOutlined />} onClick={() => setEditVisible(true)}>
                  编辑
                </Button>
                <Popconfirm title="确认删除此节点？" onConfirm={handleDelete}>
                  <Button danger icon={<DeleteOutlined />}>删除</Button>
                </Popconfirm>
              </Space>
            </>
          ) : (
            <Text type="secondary">在左侧选择一个节点查看详情</Text>
          )}
        </Card>
      </Col>

      {/* 新增子部门弹窗 */}
      <ModalForm
        title="新增节点"
        open={addVisible}
        onOpenChange={setAddVisible}
        onFinish={async (values) => {
          await txFetchData('/api/v1/org-structure/departments', {
            method: 'POST',
            body: JSON.stringify({ ...values, parent_id: selected?.id }),
          });
          message.success('创建成功');
          loadTree();
          return true;
        }}
      >
        <ProFormText name="name" label="名称" rules={[{ required: true }]} />
        <ProFormSelect
          name="type"
          label="类型"
          rules={[{ required: true }]}
          options={[
            { label: '品牌', value: 'brand' },
            { label: '区域', value: 'region' },
            { label: '门店', value: 'store' },
            { label: '部门', value: 'department' },
          ]}
        />
        <ProFormText name="head_name" label="负责人" />
      </ModalForm>

      {/* 编辑弹窗 */}
      <ModalForm
        title="编辑节点"
        open={editVisible}
        onOpenChange={setEditVisible}
        initialValues={selected ? { name: selected.name, type: selected.type, head_name: selected.head_name } : {}}
        onFinish={async (values) => {
          if (!selected) return false;
          await txFetchData(`/api/v1/org-structure/departments/${selected.id}`, {
            method: 'PUT',
            body: JSON.stringify(values),
          });
          message.success('更新成功');
          loadTree();
          return true;
        }}
      >
        <ProFormText name="name" label="名称" rules={[{ required: true }]} />
        <ProFormSelect
          name="type"
          label="类型"
          rules={[{ required: true }]}
          options={[
            { label: '集团', value: 'group' },
            { label: '品牌', value: 'brand' },
            { label: '区域', value: 'region' },
            { label: '门店', value: 'store' },
            { label: '部门', value: 'department' },
          ]}
        />
        <ProFormText name="head_name" label="负责人" />
      </ModalForm>
    </Row>
  );
}
