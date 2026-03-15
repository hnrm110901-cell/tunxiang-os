import React, { useState, useEffect, useCallback } from 'react';
import {
  Card, Form, Input, Select, Button, Table, Tag, Space,
  message, Switch, Divider, Badge, Spin, InputNumber,
} from 'antd';
import {
  ApiOutlined, SyncOutlined, CheckCircleOutlined,
  CloseCircleOutlined, ReloadOutlined, LinkOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { apiClient } from '../../../services/api';
import styles from './IMConfigTab.module.css';

interface IMConfig {
  brand_id: string;
  im_platform: string;
  corp_id?: string;
  corp_secret?: string;
  agent_id?: string;
  token?: string;
  encoding_aes_key?: string;
  app_key?: string;
  app_secret?: string;
  dingtalk_agent_id?: string;
  aes_key?: string;
  dingtalk_token?: string;
  sync_enabled: boolean;
  sync_interval_minutes: number;
  auto_create_user: boolean;
  auto_disable_user: boolean;
  default_store_id?: string;
  department_store_mapping?: Record<string, string>;
  last_sync_at?: string;
  last_sync_status?: string;
  last_sync_message?: string;
  last_sync_stats?: Record<string, number>;
}

interface SyncLog {
  id: string;
  sync_type: string;
  status: string;
  started_at: string;
  completed_at?: string;
  stats?: Record<string, number>;
  error_message?: string;
}

interface Props {
  brandId: string;
}

const IM_PLATFORMS = [
  { value: 'wechat_work', label: '企业微信' },
  { value: 'dingtalk', label: '钉钉' },
];

const IMConfigTab: React.FC<Props> = ({ brandId }) => {
  const [config, setConfig] = useState<IMConfig | null>(null);
  const [syncLogs, setSyncLogs] = useState<SyncLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [testing, setTesting] = useState(false);
  const [form] = Form.useForm();
  const [platform, setPlatform] = useState<string>('wechat_work');

  const fetchConfig = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiClient.get<IMConfig>(`/api/v1/merchants/${brandId}/im/config`);
      setConfig(data);
      setPlatform(data.im_platform || 'wechat_work');
      form.setFieldsValue({
        im_platform: data.im_platform,
        // WeChat
        corp_id: data.corp_id,
        corp_secret: data.corp_secret,
        agent_id: data.agent_id,
        token: data.token,
        encoding_aes_key: data.encoding_aes_key,
        // DingTalk
        app_key: data.app_key,
        app_secret: data.app_secret,
        dingtalk_agent_id: data.dingtalk_agent_id,
        aes_key: data.aes_key,
        dingtalk_token: data.dingtalk_token,
        // Sync
        sync_enabled: data.sync_enabled,
        sync_interval_minutes: data.sync_interval_minutes,
        auto_create_user: data.auto_create_user,
        auto_disable_user: data.auto_disable_user,
        default_store_id: data.default_store_id,
      });
    } catch {
      // No config yet — fresh form
      setConfig(null);
    } finally {
      setLoading(false);
    }
  }, [brandId, form]);

  const fetchSyncLogs = useCallback(async () => {
    try {
      const data = await apiClient.get<SyncLog[]>(`/api/v1/merchants/${brandId}/im/sync-logs`);
      setSyncLogs(data);
    } catch { /* silent */ }
  }, [brandId]);

  useEffect(() => { fetchConfig(); fetchSyncLogs(); }, [fetchConfig, fetchSyncLogs]);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      await apiClient.post(`/api/v1/merchants/${brandId}/im/config`, values);
      message.success('IM 配置已保存');
      fetchConfig();
    } catch {
      message.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleTestConnection = async () => {
    setTesting(true);
    try {
      const result = await apiClient.post<{ success: boolean; message: string }>(
        `/api/v1/merchants/${brandId}/im/test-connection`, {}
      );
      if (result.success) {
        message.success('连接测试成功');
      } else {
        message.warning(`连接测试失败: ${result.message}`);
      }
    } catch {
      message.error('连接测试失败');
    } finally {
      setTesting(false);
    }
  };

  const handleSync = async () => {
    setSyncing(true);
    try {
      await apiClient.post(`/api/v1/merchants/${brandId}/im/sync`, {});
      message.success('同步已触发');
      setTimeout(() => { fetchSyncLogs(); fetchConfig(); }, 2000);
    } catch {
      message.error('同步触发失败');
    } finally {
      setSyncing(false);
    }
  };

  const logColumns: ColumnsType<SyncLog> = [
    {
      title: '类型', dataIndex: 'sync_type', key: 'sync_type', width: 100,
      render: (v: string) => <Tag>{v}</Tag>,
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (s: string) => (
        <Badge
          status={s === 'success' ? 'success' : s === 'running' ? 'processing' : 'error'}
          text={s === 'success' ? '成功' : s === 'running' ? '运行中' : '失败'}
        />
      ),
    },
    {
      title: '开始时间', dataIndex: 'started_at', key: 'started_at', width: 160,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    {
      title: '统计', dataIndex: 'stats', key: 'stats',
      render: (stats: Record<string, number> | undefined) => {
        if (!stats) return '-';
        return Object.entries(stats).map(([k, v]) => `${k}: ${v}`).join(', ');
      },
    },
    {
      title: '错误', dataIndex: 'error_message', key: 'error_message', ellipsis: true,
      render: (v: string | undefined) => v || '-',
    },
  ];

  if (loading) {
    return <div className={styles.loadingContainer}><Spin /></div>;
  }

  return (
    <div className={styles.container}>
      {/* ── IM Config Form ─────────────────────────────────────────────────── */}
      <Card
        title={<span><ApiOutlined /> IM 平台配置</span>}
        size="small"
        className={styles.card}
        extra={
          <Space>
            {config && (
              <Button
                icon={<LinkOutlined />}
                loading={testing}
                onClick={handleTestConnection}
              >
                测试连接
              </Button>
            )}
            <Button type="primary" loading={saving} onClick={handleSave}>
              保存配置
            </Button>
          </Space>
        }
      >
        <Form form={form} layout="vertical" initialValues={{ im_platform: 'wechat_work', sync_interval_minutes: 60 }}>
          <Form.Item name="im_platform" label="IM 平台">
            <Select options={IM_PLATFORMS} onChange={(v) => setPlatform(v)} />
          </Form.Item>

          {platform === 'wechat_work' ? (
            <>
              <Divider plain style={{ fontSize: 12 }}>企业微信凭证</Divider>
              <Form.Item name="corp_id" label="Corp ID" rules={[{ required: true }]}>
                <Input placeholder="企业 ID" />
              </Form.Item>
              <Form.Item name="corp_secret" label="Corp Secret" rules={[{ required: true }]}>
                <Input.Password placeholder="应用 Secret" />
              </Form.Item>
              <Form.Item name="agent_id" label="Agent ID">
                <Input placeholder="应用 AgentId" />
              </Form.Item>
              <Form.Item name="token" label="回调 Token">
                <Input placeholder="事件回调 Token" />
              </Form.Item>
              <Form.Item name="encoding_aes_key" label="Encoding AES Key">
                <Input placeholder="消息加密密钥" />
              </Form.Item>
            </>
          ) : (
            <>
              <Divider plain style={{ fontSize: 12 }}>钉钉凭证</Divider>
              <Form.Item name="app_key" label="App Key" rules={[{ required: true }]}>
                <Input />
              </Form.Item>
              <Form.Item name="app_secret" label="App Secret" rules={[{ required: true }]}>
                <Input.Password />
              </Form.Item>
              <Form.Item name="dingtalk_agent_id" label="Agent ID">
                <Input />
              </Form.Item>
              <Form.Item name="aes_key" label="AES Key">
                <Input />
              </Form.Item>
              <Form.Item name="dingtalk_token" label="回调 Token">
                <Input />
              </Form.Item>
            </>
          )}

          <Divider plain style={{ fontSize: 12 }}>同步设置</Divider>
          <Form.Item name="sync_enabled" label="启用自动同步" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="sync_interval_minutes" label="同步间隔（分钟）">
            <InputNumber min={5} max={1440} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="auto_create_user" label="自动创建用户" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="auto_disable_user" label="离职自动禁用" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="default_store_id" label="默认门店 ID">
            <Input placeholder="新同步用户的默认门店" />
          </Form.Item>
        </Form>
      </Card>

      {/* ── Sync Status & Actions ────────────────────────────────────────────── */}
      {config && (
        <Card
          title="同步状态"
          size="small"
          className={styles.card}
          extra={
            <Space>
              <Button icon={<ReloadOutlined />} onClick={fetchSyncLogs}>刷新</Button>
              <Button
                type="primary"
                icon={<SyncOutlined spin={syncing} />}
                loading={syncing}
                onClick={handleSync}
              >
                立即同步
              </Button>
            </Space>
          }
        >
          {config.last_sync_at && (
            <div className={styles.lastSync}>
              <span>上次同步: {new Date(config.last_sync_at).toLocaleString('zh-CN')}</span>
              <Badge
                status={config.last_sync_status === 'success' ? 'success' : 'error'}
                text={config.last_sync_status === 'success' ? '成功' : config.last_sync_status || '未知'}
              />
              {config.last_sync_stats && (
                <span className={styles.syncStats}>
                  {Object.entries(config.last_sync_stats).map(([k, v]) => `${k}: ${v}`).join(' | ')}
                </span>
              )}
            </div>
          )}
          <Table<SyncLog>
            rowKey="id"
            columns={logColumns}
            dataSource={syncLogs}
            pagination={{ pageSize: 10 }}
            size="small"
            locale={{ emptyText: '暂无同步记录' }}
          />
        </Card>
      )}

      {/* ── Callback URL hint ─────────────────────────────────────────────────── */}
      {config && (
        <div className={styles.callbackHint}>
          <strong>回调地址：</strong>
          {platform === 'wechat_work'
            ? `https://api.zlsjos.cn/api/v1/im/callback/wechat/${brandId}`
            : `https://api.zlsjos.cn/api/v1/im/callback/dingtalk/${brandId}`
          }
        </div>
      )}
    </div>
  );
};

export default IMConfigTab;
