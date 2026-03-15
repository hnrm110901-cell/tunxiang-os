import React, { useState, useEffect, useCallback } from 'react';
import {
  Table, Button, Modal, Form, Input, InputNumber, Select, Switch,
  message, Popconfirm, Tag, Space,
} from 'antd';
import {
  PlusOutlined, DeleteOutlined, AppstoreOutlined, ReloadOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { apiClient } from '../../../services/api';
import type { ChannelConfigItem } from '../merchant-constants';
import { CHANNEL_LABELS, CHANNEL_OPTIONS } from '../merchant-constants';
import styles from './ChannelsTab.module.css';

interface Props {
  brandId: string;
}

const ChannelsTab: React.FC<Props> = ({ brandId }) => {
  const [channels, setChannels] = useState<ChannelConfigItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [addVisible, setAddVisible] = useState(false);
  const [form] = Form.useForm();

  const fetchChannels = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiClient.get<ChannelConfigItem[]>(`/api/v1/merchants/${brandId}/channels`);
      setChannels(data);
    } catch {
      message.error('加载渠道配置失败');
    } finally {
      setLoading(false);
    }
  }, [brandId]);

  useEffect(() => { fetchChannels(); }, [fetchChannels]);

  const handleAdd = async () => {
    try {
      const values = await form.validateFields();
      await apiClient.post(`/api/v1/merchants/${brandId}/channels`, values);
      message.success('渠道配置已保存');
      setAddVisible(false);
      form.resetFields();
      fetchChannels();
    } catch {
      message.error('保存失败');
    }
  };

  const handleDelete = async (channelId: string) => {
    try {
      await apiClient.delete(`/api/v1/merchants/${brandId}/channels/${channelId}`);
      message.success('已删除');
      fetchChannels();
    } catch {
      message.error('删除失败');
    }
  };

  const columns: ColumnsType<ChannelConfigItem> = [
    {
      title: '渠道', dataIndex: 'channel', key: 'channel', width: 140,
      render: (v: string) => <Tag color="blue">{CHANNEL_LABELS[v] || v}</Tag>,
    },
    {
      title: '平台佣金率', dataIndex: 'platform_commission_pct', key: 'commission', width: 120,
      render: (v: number) => `${(v * 100).toFixed(2)}%`,
    },
    {
      title: '配送费', dataIndex: 'delivery_cost_fen', key: 'delivery', width: 100,
      render: (v: number) => `¥${(v / 100).toFixed(2)}`,
    },
    {
      title: '包装费', dataIndex: 'packaging_cost_fen', key: 'packaging', width: 100,
      render: (v: number) => `¥${(v / 100).toFixed(2)}`,
    },
    {
      title: '启用', dataIndex: 'is_active', key: 'is_active', width: 70,
      render: (v: boolean) => v ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>,
    },
    {
      title: '操作', key: 'action', width: 70,
      render: (_: unknown, r: ChannelConfigItem) => (
        <Popconfirm title="确认删除该渠道配置？" onConfirm={() => handleDelete(r.id)}>
          <Button type="text" size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      ),
    },
  ];

  return (
    <div>
      <div className={styles.header}>
        <span className={styles.title}><AppstoreOutlined /> 销售渠道配置</span>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={fetchChannels}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setAddVisible(true)}>
            添加渠道
          </Button>
        </Space>
      </div>
      <Table<ChannelConfigItem>
        rowKey="id"
        columns={columns}
        dataSource={channels}
        loading={loading}
        pagination={false}
        size="small"
        locale={{ emptyText: '暂无渠道配置' }}
      />

      <div className={styles.hint}>
        佣金率为小数形式（如 0.18 = 18%），配送费/包装费单位为分（如 500 = ¥5.00）。
      </div>

      <Modal
        title="添加/更新渠道配置"
        open={addVisible}
        onCancel={() => { setAddVisible(false); form.resetFields(); }}
        onOk={handleAdd}
        width={480}
      >
        <Form form={form} layout="vertical" initialValues={{ platform_commission_pct: 0, delivery_cost_fen: 0, packaging_cost_fen: 0, is_active: true }}>
          <Form.Item name="channel" label="渠道" rules={[{ required: true, message: '请选择渠道' }]}>
            <Select options={CHANNEL_OPTIONS} placeholder="选择渠道" />
          </Form.Item>
          <Form.Item name="platform_commission_pct" label="平台佣金率（小数，如 0.18）">
            <InputNumber min={0} max={1} step={0.01} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="delivery_cost_fen" label="配送费（分）">
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="packaging_cost_fen" label="包装费（分）">
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default ChannelsTab;
