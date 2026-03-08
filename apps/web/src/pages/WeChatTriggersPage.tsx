import React, { useState, useCallback, useEffect } from 'react';
import { Form, Input, Switch } from 'antd';
import { SendOutlined, ReloadOutlined } from '@ant-design/icons';
import { apiClient } from '../services/api';
import { handleApiError, showSuccess } from '../utils/message';
import { ZCard, ZKpi, ZBadge, ZButton, ZSkeleton, ZTable, ZModal } from '../design-system/components';
import type { ZTableColumn } from '../design-system/components/ZTable';
import styles from './WeChatTriggersPage.module.css';

const { TextArea } = Input;

const WeChatTriggersPage: React.FC = () => {
  const [rules, setRules]             = useState<any[]>([]);
  const [stats, setStats]             = useState<any>(null);
  const [loading, setLoading]         = useState(false);
  const [testVisible, setTestVisible]     = useState(false);
  const [manualVisible, setManualVisible] = useState(false);
  const [testForm]   = Form.useForm();
  const [manualForm] = Form.useForm();
  const [submitting, setSubmitting]   = useState(false);
  const [toggleLoading, setToggleLoading] = useState<Record<string, boolean>>({});

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [rulesRes, statsRes] = await Promise.allSettled([
        apiClient.get('/api/v1/wechat/triggers/rules'),
        apiClient.get('/api/v1/wechat/triggers/stats'),
      ]);
      if (rulesRes.status === 'fulfilled') setRules(rulesRes.value?.rules || rulesRes.value || []);
      if (statsRes.status === 'fulfilled') setStats(statsRes.value);
    } catch (err: any) {
      handleApiError(err, '加载触发规则失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const toggleRule = async (record: any, enabled: boolean) => {
    const key = record.event_type;
    setToggleLoading(prev => ({ ...prev, [key]: true }));
    try {
      await apiClient.put(`/api/v1/wechat/triggers/rules/${record.event_type}/toggle`, { enabled });
      showSuccess(enabled ? '已启用' : '已禁用');
      loadData();
    } catch (err: any) {
      handleApiError(err, '操作失败');
    } finally {
      setToggleLoading(prev => ({ ...prev, [key]: false }));
    }
  };

  const testTrigger = async (values: any) => {
    setSubmitting(true);
    try {
      await apiClient.post('/api/v1/wechat/triggers/test', {
        event_type: values.event_type,
        event_data: JSON.parse(values.event_data || '{}'),
        store_id:   values.store_id,
      });
      showSuccess('测试推送已发送');
      setTestVisible(false);
      testForm.resetFields();
    } catch (err: any) {
      handleApiError(err, '测试失败');
    } finally {
      setSubmitting(false);
    }
  };

  const manualSend = async (values: any) => {
    setSubmitting(true);
    try {
      await apiClient.post('/api/v1/wechat/triggers/manual-send', values);
      showSuccess('消息已发送');
      setManualVisible(false);
      manualForm.resetFields();
    } catch (err: any) {
      handleApiError(err, '发送失败');
    } finally {
      setSubmitting(false);
    }
  };

  const columns: ZTableColumn<any>[] = [
    { key: 'event_type',    title: '事件类型' },
    { key: 'description',   title: '描述' },
    { key: 'template',      title: '消息模板' },
    {
      key: 'trigger_count',
      title: '触发次数',
      align: 'right',
      render: (v: number) => v ?? 0,
    },
    {
      key: 'enabled',
      title: '状态',
      width: 80,
      align: 'center',
      render: (v: boolean, record: any) => (
        <Switch
          checked={v}
          loading={toggleLoading[record.event_type]}
          onChange={(checked) => toggleRule(record, checked)}
        />
      ),
    },
  ];

  const modalFooter = (onSubmit: () => void) => (
    <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
      <ZButton onClick={() => { setTestVisible(false); setManualVisible(false); }}>取消</ZButton>
      <ZButton variant="primary" disabled={submitting} onClick={onSubmit}>
        {submitting ? '发送中…' : '发送'}
      </ZButton>
    </div>
  );

  const enabledCount = rules.filter((r: any) => r.enabled).length;

  return (
    <div className={styles.page}>
      {/* KPI 行 */}
      <div className={styles.kpiGrid}>
        <ZCard><ZKpi value={rules.length}                                   label="规则总数" /></ZCard>
        <ZCard><ZKpi value={enabledCount}                                   label="已启用" /></ZCard>
        <ZCard><ZKpi value={stats?.total_triggers ?? 0}                     label="总触发次数" /></ZCard>
        <ZCard><ZKpi value={((stats?.success_rate || 0) * 100).toFixed(1)} unit="%" label="成功率" /></ZCard>
      </div>

      {/* 规则表 */}
      <ZCard
        title="微信推送触发规则"
        extra={
          <div style={{ display: 'flex', gap: 8 }}>
            <ZButton icon={<ReloadOutlined />} onClick={loadData}>刷新</ZButton>
            <ZButton icon={<SendOutlined />} onClick={() => setTestVisible(true)}>测试推送</ZButton>
            <ZButton variant="primary" icon={<SendOutlined />} onClick={() => setManualVisible(true)}>手动发送</ZButton>
          </div>
        }
      >
        {loading ? (
          <ZSkeleton rows={4} block />
        ) : (
          <ZTable columns={columns} data={rules} rowKey={(r) => r.event_type} emptyText="暂无规则" />
        )}
      </ZCard>

      {/* 测试触发推送 Modal */}
      <ZModal
        open={testVisible}
        title="测试触发推送"
        onClose={() => setTestVisible(false)}
        footer={modalFooter(() => testForm.submit())}
      >
        <Form form={testForm} layout="vertical" onFinish={testTrigger}>
          <Form.Item name="event_type" label="事件类型" rules={[{ required: true }]}>
            <Input placeholder="如 order.created" />
          </Form.Item>
          <Form.Item name="event_data" label="事件数据（JSON）" initialValue="{}">
            <TextArea rows={3} />
          </Form.Item>
          <Form.Item name="store_id" label="门店ID">
            <Input placeholder="可选" />
          </Form.Item>
        </Form>
      </ZModal>

      {/* 手动发送消息 Modal */}
      <ZModal
        open={manualVisible}
        title="手动发送消息"
        onClose={() => setManualVisible(false)}
        footer={modalFooter(() => manualForm.submit())}
      >
        <Form form={manualForm} layout="vertical" onFinish={manualSend}>
          <Form.Item name="content" label="消息内容" rules={[{ required: true }]}>
            <TextArea rows={4} />
          </Form.Item>
          <Form.Item name="touser" label="接收用户（| 分隔）">
            <Input />
          </Form.Item>
          <Form.Item name="toparty" label="接收部门（| 分隔）">
            <Input />
          </Form.Item>
        </Form>
      </ZModal>
    </div>
  );
};

export default WeChatTriggersPage;
