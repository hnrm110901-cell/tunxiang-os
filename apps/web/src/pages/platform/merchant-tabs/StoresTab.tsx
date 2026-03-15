import React, { useState } from 'react';
import {
  Table, Button, Modal, Form, Input, InputNumber, Row, Col,
  message, Popconfirm, Badge,
} from 'antd';
import { PlusOutlined, ShopOutlined, DeleteOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { apiClient } from '../../../services/api';
import type { StoreItem } from '../merchant-constants';
import styles from './StoresTab.module.css';

interface Props {
  brandId: string;
  stores: StoreItem[];
  onRefresh: () => void;
}

const StoresTab: React.FC<Props> = ({ brandId, stores, onRefresh }) => {
  const [addVisible, setAddVisible] = useState(false);
  const [storeForm] = Form.useForm();

  const handleAddStore = async () => {
    try {
      const values = await storeForm.validateFields();
      await apiClient.post(`/api/v1/merchants/${brandId}/stores`, values);
      message.success('门店添加成功');
      setAddVisible(false);
      storeForm.resetFields();
      onRefresh();
    } catch {
      message.error('添加门店失败');
    }
  };

  const handleRemoveStore = async (storeId: string) => {
    try {
      await apiClient.delete(`/api/v1/merchants/${brandId}/stores/${storeId}`);
      message.success('门店已移除');
      onRefresh();
    } catch {
      message.error('移除失败');
    }
  };

  const columns: ColumnsType<StoreItem> = [
    { title: '名称', dataIndex: 'name', key: 'name', width: 160 },
    { title: '编码', dataIndex: 'code', key: 'code', width: 100 },
    { title: '城市', dataIndex: 'city', key: 'city', width: 90 },
    { title: '区域', dataIndex: 'district', key: 'district', width: 90 },
    { title: '地址', dataIndex: 'address', key: 'address', ellipsis: true },
    { title: '座位', dataIndex: 'seats', key: 'seats', width: 70, render: (v: number | null) => v ?? '-' },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (s: string) => <Badge status={s === 'active' ? 'success' : 'default'} text={s === 'active' ? '运营' : s} />,
    },
    {
      title: '操作', key: 'action', width: 70,
      render: (_: unknown, r: StoreItem) => (
        <Popconfirm title={`确认移除「${r.name}」?`} onConfirm={() => handleRemoveStore(r.id)}>
          <Button type="text" size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      ),
    },
  ];

  return (
    <div>
      <div className={styles.header}>
        <span className={styles.title}><ShopOutlined /> 门店列表 ({stores.length})</span>
        <Button type="primary" size="small" icon={<PlusOutlined />} onClick={() => setAddVisible(true)}>
          添加门店
        </Button>
      </div>
      <Table<StoreItem>
        rowKey="id"
        columns={columns}
        dataSource={stores}
        pagination={false}
        size="small"
        locale={{ emptyText: '暂无门店，点击上方按钮添加' }}
      />

      <Modal
        title="添加门店"
        open={addVisible}
        onCancel={() => { setAddVisible(false); storeForm.resetFields(); }}
        onOk={handleAddStore}
      >
        <Form form={storeForm} layout="vertical">
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="store_name" label="门店名称" rules={[{ required: true }]}>
                <Input placeholder="如：花果园店" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="store_code" label="门店编码" rules={[{ required: true }]}>
                <Input placeholder="如：GY001" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="city" label="城市"><Input /></Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="district" label="区域"><Input /></Form.Item>
            </Col>
          </Row>
          <Form.Item name="address" label="地址"><Input /></Form.Item>
          <Form.Item name="seats" label="座位数"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default StoresTab;
