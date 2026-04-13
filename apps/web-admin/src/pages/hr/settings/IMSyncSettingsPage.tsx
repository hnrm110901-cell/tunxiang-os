/**
 * IMSyncSettingsPage -- IM 集成配置（企微/钉钉）
 * 域F - 设置中心
 *
 * 功能：
 *  1. 企微/钉钉连接状态展示
 *  2. 凭证配置表单（corp_id / corp_secret / agent_id）
 *  3. 手动触发同步按钮
 *  4. 同步结果展示（已绑定/待绑定/待创建/待停用数量）
 *
 * API:
 *  GET  /api/v1/org/im-sync/config
 *  GET  /api/v1/org/im-sync/status
 *  POST /api/v1/org/im-sync/preview
 */

import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Descriptions,
  Divider,
  message,
  Row,
  Space,
  Statistic,
  Tabs,
  Typography,
} from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  DingdingOutlined,
  ReloadOutlined,
  SyncOutlined,
  WechatWorkOutlined,
} from '@ant-design/icons';
import {
  ProForm,
  ProFormText,
} from '@ant-design/pro-components';
import { txFetchData } from '../../../api';

const { Title, Text } = Typography;

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface IMConfigStatus {
  wecom_configured: boolean;
  dingtalk_configured: boolean;
  wecom_corp_id: string;
  dingtalk_app_key: string;
}

interface IMSyncStatus {
  total_employees: number;
  wecom_bound: number;
  dingtalk_bound: number;
  unbound: number;
}

interface IMPreviewEntry {
  im_userid: string;
  name: string;
  employee_id: string | null;
}

interface IMSyncPreview {
  to_bind: IMPreviewEntry[];
  to_create: IMPreviewEntry[];
  to_deactivate: IMPreviewEntry[];
  unchanged: number;
}

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function IMSyncSettingsPage() {
  const [configStatus, setConfigStatus] = useState<IMConfigStatus | null>(null);
  const [syncStatus, setSyncStatus] = useState<IMSyncStatus | null>(null);
  const [preview, setPreview] = useState<IMSyncPreview | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [loading, setLoading] = useState(false);

  // ─── 加载配置状态 ──────────────────────────────────────────────────────

  const loadConfig = useCallback(async () => {
    try {
      const data = await txFetchData<IMConfigStatus>('/api/v1/org/im-sync/config');
      setConfigStatus(data);
    } catch {
      message.error('加载 IM 配置状态失败');
    }
  }, []);

  const loadSyncStatus = useCallback(async () => {
    try {
      const data = await txFetchData<IMSyncStatus>('/api/v1/org/im-sync/status');
      setSyncStatus(data);
    } catch {
      message.error('加载绑定状态失败');
    }
  }, []);

  useEffect(() => {
    loadConfig();
    loadSyncStatus();
  }, [loadConfig, loadSyncStatus]);

  // ─── 同步预览 ──────────────────────────────────────────────────────────

  const handleSync = async (provider: string, values: Record<string, string>) => {
    setSyncing(true);
    setPreview(null);
    try {
      const data = await txFetchData<IMSyncPreview>('/api/v1/org/im-sync/preview', {
        method: 'POST',
        body: JSON.stringify({
          provider,
          corp_id: values.corp_id,
          corp_secret: values.corp_secret,
          agent_id: values.agent_id || '',
        }),
      });
      setPreview(data);
      message.success('同步预览完成');
    } catch {
      message.error('同步预览失败，请检查凭证是否正确');
    } finally {
      setSyncing(false);
    }
  };

  // ─── 连接状态卡片 ──────────────────────────────────────────────────────

  const renderConnectionStatus = () => (
    <Card title="连接状态" style={{ marginBottom: 16 }}>
      <Row gutter={24}>
        <Col span={12}>
          <Space>
            <WechatWorkOutlined style={{ fontSize: 24, color: '#1890ff' }} />
            <Text strong>企业微信</Text>
            {configStatus?.wecom_configured ? (
              <Badge
                status="success"
                text={
                  <Text type="success">
                    <CheckCircleOutlined /> 已连接 ({configStatus.wecom_corp_id})
                  </Text>
                }
              />
            ) : (
              <Badge
                status="default"
                text={
                  <Text type="secondary">
                    <CloseCircleOutlined /> 未配置
                  </Text>
                }
              />
            )}
          </Space>
        </Col>
        <Col span={12}>
          <Space>
            <DingdingOutlined style={{ fontSize: 24, color: '#1890ff' }} />
            <Text strong>钉钉</Text>
            {configStatus?.dingtalk_configured ? (
              <Badge
                status="success"
                text={
                  <Text type="success">
                    <CheckCircleOutlined /> 已连接 ({configStatus.dingtalk_app_key})
                  </Text>
                }
              />
            ) : (
              <Badge
                status="default"
                text={
                  <Text type="secondary">
                    <CloseCircleOutlined /> 未配置
                  </Text>
                }
              />
            )}
          </Space>
        </Col>
      </Row>

      {syncStatus && (
        <>
          <Divider />
          <Row gutter={16}>
            <Col span={6}>
              <Statistic title="总员工数" value={syncStatus.total_employees} />
            </Col>
            <Col span={6}>
              <Statistic
                title="企微已绑定"
                value={syncStatus.wecom_bound}
                valueStyle={{ color: '#52c41a' }}
              />
            </Col>
            <Col span={6}>
              <Statistic
                title="钉钉已绑定"
                value={syncStatus.dingtalk_bound}
                valueStyle={{ color: '#1890ff' }}
              />
            </Col>
            <Col span={6}>
              <Statistic
                title="未绑定"
                value={syncStatus.unbound}
                valueStyle={{ color: syncStatus.unbound > 0 ? '#faad14' : undefined }}
              />
            </Col>
          </Row>
        </>
      )}
    </Card>
  );

  // ─── 凭证配置表单 ──────────────────────────────────────────────────────

  const renderProviderForm = (provider: 'wecom' | 'dingtalk') => {
    const isWecom = provider === 'wecom';
    return (
      <Card
        title={
          <Space>
            {isWecom ? <WechatWorkOutlined /> : <DingdingOutlined />}
            {isWecom ? '企业微信配置' : '钉钉配置'}
          </Space>
        }
        extra={
          <Button
            icon={<ReloadOutlined />}
            onClick={() => {
              loadConfig();
              loadSyncStatus();
            }}
          >
            刷新状态
          </Button>
        }
      >
        <ProForm
          layout="horizontal"
          labelCol={{ span: 6 }}
          wrapperCol={{ span: 14 }}
          submitter={{
            searchConfig: { submitText: '保存并同步预览' },
            resetButtonProps: false,
            render: (_, dom) => (
              <Space>
                {dom}
                <Button
                  type="default"
                  icon={<SyncOutlined spin={syncing} />}
                  loading={syncing}
                  disabled={syncing}
                >
                  仅预览同步
                </Button>
              </Space>
            ),
          }}
          onFinish={async (values) => {
            await handleSync(provider, values as Record<string, string>);
            return true;
          }}
        >
          <ProFormText
            name="corp_id"
            label={isWecom ? '企业ID (Corp ID)' : '应用Key (App Key)'}
            placeholder={isWecom ? '请输入企业 Corp ID' : '请输入应用 App Key'}
            rules={[{ required: true, message: '此字段必填' }]}
          />
          <ProFormText.Password
            name="corp_secret"
            label={isWecom ? '应用Secret' : '应用Secret'}
            placeholder={isWecom ? '请输入应用 Corp Secret' : '请输入应用 App Secret'}
            rules={[{ required: true, message: '此字段必填' }]}
          />
          <ProFormText
            name="agent_id"
            label="Agent ID"
            placeholder="请输入应用 Agent ID（发消息需要）"
          />
        </ProForm>

        {isWecom && (
          <Alert
            type="info"
            showIcon
            style={{ marginTop: 16 }}
            message="回调地址"
            description={
              <Text copyable>
                {`${window.location.origin}/api/v1/org/im-sync/webhook/wecom`}
              </Text>
            }
          />
        )}
        {!isWecom && (
          <Alert
            type="info"
            showIcon
            style={{ marginTop: 16 }}
            message="回调地址"
            description={
              <Text copyable>
                {`${window.location.origin}/api/v1/org/im-sync/webhook/dingtalk`}
              </Text>
            }
          />
        )}
      </Card>
    );
  };

  // ─── 同步结果展示 ──────────────────────────────────────────────────────

  const renderSyncPreview = () => {
    if (!preview) return null;
    return (
      <Card title="同步预览结果" style={{ marginTop: 16 }}>
        <Row gutter={16}>
          <Col span={6}>
            <Statistic
              title="待绑定"
              value={preview.to_bind.length}
              valueStyle={{ color: '#1890ff' }}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="待创建"
              value={preview.to_create.length}
              valueStyle={{ color: '#52c41a' }}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="待停用"
              value={preview.to_deactivate.length}
              valueStyle={{ color: '#ff4d4f' }}
            />
          </Col>
          <Col span={6}>
            <Statistic title="未变化" value={preview.unchanged} />
          </Col>
        </Row>

        {preview.to_bind.length > 0 && (
          <>
            <Divider orientation="left">待绑定</Divider>
            <Descriptions column={3} size="small" bordered>
              {preview.to_bind.map((e) => (
                <Descriptions.Item key={e.im_userid} label={e.im_userid}>
                  {e.name} {e.employee_id ? `(${e.employee_id})` : ''}
                </Descriptions.Item>
              ))}
            </Descriptions>
          </>
        )}

        {preview.to_create.length > 0 && (
          <>
            <Divider orientation="left">待创建</Divider>
            <Descriptions column={3} size="small" bordered>
              {preview.to_create.map((e) => (
                <Descriptions.Item key={e.im_userid} label={e.im_userid}>
                  {e.name}
                </Descriptions.Item>
              ))}
            </Descriptions>
          </>
        )}

        {preview.to_deactivate.length > 0 && (
          <>
            <Divider orientation="left">待停用</Divider>
            <Descriptions column={3} size="small" bordered>
              {preview.to_deactivate.map((e) => (
                <Descriptions.Item key={e.im_userid} label={e.im_userid}>
                  {e.name}
                </Descriptions.Item>
              ))}
            </Descriptions>
          </>
        )}

        <Divider />
        <Space>
          <Button
            type="primary"
            loading={loading}
            onClick={async () => {
              setLoading(true);
              try {
                await txFetchData('/api/v1/org/im-sync/apply', {
                  method: 'POST',
                  body: JSON.stringify({
                    provider: 'wecom',
                    auto_create: false,
                    diff_id: 'latest',
                  }),
                });
                message.success('同步应用成功');
                loadSyncStatus();
              } catch {
                message.error('同步应用失败');
              } finally {
                setLoading(false);
              }
            }}
          >
            确认应用（仅绑定）
          </Button>
          <Button
            loading={loading}
            onClick={async () => {
              setLoading(true);
              try {
                await txFetchData('/api/v1/org/im-sync/apply', {
                  method: 'POST',
                  body: JSON.stringify({
                    provider: 'wecom',
                    auto_create: true,
                    diff_id: 'latest',
                  }),
                });
                message.success('同步应用成功（含自动建档）');
                loadSyncStatus();
              } catch {
                message.error('同步应用失败');
              } finally {
                setLoading(false);
              }
            }}
          >
            确认应用（含自动建档）
          </Button>
        </Space>
      </Card>
    );
  };

  // ─── 渲染 ──────────────────────────────────────────────────────────────

  return (
    <div style={{ padding: 24 }}>
      <Title level={4}>IM 集成配置</Title>
      <Text type="secondary" style={{ marginBottom: 16, display: 'block' }}>
        配置企业微信或钉钉集成，实现通讯录自动同步与消息推送
      </Text>

      {renderConnectionStatus()}

      <Tabs
        defaultActiveKey="wecom"
        items={[
          {
            key: 'wecom',
            label: (
              <Space>
                <WechatWorkOutlined />
                企业微信
              </Space>
            ),
            children: renderProviderForm('wecom'),
          },
          {
            key: 'dingtalk',
            label: (
              <Space>
                <DingdingOutlined />
                钉钉
              </Space>
            ),
            children: renderProviderForm('dingtalk'),
          },
        ]}
      />

      {renderSyncPreview()}
    </div>
  );
}
