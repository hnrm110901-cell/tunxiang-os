/**
 * 评论行动引擎页 — /platform/review-actions
 *
 * 功能：规则管理、执行日志、效果分析
 * 后端 API: /api/v1/review-actions/*
 */
import React, { useState, useEffect, useCallback } from 'react';
import {
  Button, Space, Card, Statistic, Row, Col,
  Select, Tag, Modal, Switch, Table, Tabs,
  message, Empty, Typography, Spin, Input,
  Badge, Form, Pagination, Tooltip,
} from 'antd';
import {
  PlusOutlined, ThunderboltOutlined, DeleteOutlined,
  EditOutlined, RobotOutlined, AlertOutlined,
  CheckCircleOutlined, CloseCircleOutlined,
  SyncOutlined, FileTextOutlined,
  BellOutlined, WechatOutlined, NodeIndexOutlined,
} from '@ant-design/icons';
import { apiClient } from '../../services/api';
import styles from './ReviewActionPage.module.css';

const { Text, Title } = Typography;
const { TextArea } = Input;

// ── 类型 ─────────────────────────────────────────────────────────

interface ReviewActionRule {
  id: string;
  brand_id: string;
  rule_name: string;
  trigger_condition: {
    sentiment?: string;
    rating_lte?: number;
    rating_gte?: number;
    keywords?: string[];
  };
  action_type: string;
  action_config: Record<string, any>;
  is_enabled: boolean;
  trigger_count: number;
  priority: number;
  created_at: string | null;
  updated_at: string | null;
}

interface RuleListResponse {
  total: number;
  page: number;
  page_size: number;
  rules: ReviewActionRule[];
}

interface ReviewActionLog {
  id: string;
  rule_id: string | null;
  review_id: string;
  brand_id: string;
  store_id: string;
  action_type: string;
  action_detail: Record<string, any> | null;
  status: string;
  error_message: string | null;
  executed_at: string | null;
  created_at: string | null;
}

interface LogListResponse {
  total: number;
  page: number;
  page_size: number;
  logs: ReviewActionLog[];
}

interface ReviewActionStats {
  total_rules: number;
  active_rules: number;
  triggered_today: number;
  success_rate: number;
  total_logs: number;
  top_triggered_rules: { rule_name: string; trigger_count: number }[];
}

// ── 常量 ─────────────────────────────────────────────────────────

const BRAND_ID = 'brand_default';

const ACTION_TYPE_MAP: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  auto_reply: { label: '自动回复', color: 'blue', icon: <RobotOutlined /> },
  alert_manager: { label: '通知管理者', color: 'orange', icon: <BellOutlined /> },
  create_task: { label: '创建任务', color: 'purple', icon: <FileTextOutlined /> },
  signal_bus: { label: '信号总线', color: 'cyan', icon: <NodeIndexOutlined /> },
  wechat_notify: { label: '企微通知', color: 'green', icon: <WechatOutlined /> },
};

const SENTIMENT_MAP: Record<string, { label: string; color: string }> = {
  negative: { label: '差评', color: 'red' },
  neutral: { label: '中评', color: 'default' },
  positive: { label: '好评', color: 'green' },
};

const STATUS_MAP: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  success: { label: '成功', color: 'green', icon: <CheckCircleOutlined /> },
  failed: { label: '失败', color: 'red', icon: <CloseCircleOutlined /> },
  pending: { label: '待处理', color: 'default', icon: <SyncOutlined spin /> },
};

// ── 辅助函数 ─────────────────────────────────────────────────────

function renderConditionTags(condition: ReviewActionRule['trigger_condition']) {
  const tags: React.ReactNode[] = [];
  if (condition.sentiment) {
    const cfg = SENTIMENT_MAP[condition.sentiment] || { label: condition.sentiment, color: 'default' };
    tags.push(<Tag key="sentiment" color={cfg.color}>{cfg.label}</Tag>);
  }
  if (condition.rating_lte !== undefined) {
    tags.push(<Tag key="rating_lte" color="volcano">评分 &le; {condition.rating_lte}</Tag>);
  }
  if (condition.rating_gte !== undefined) {
    tags.push(<Tag key="rating_gte" color="lime">评分 &ge; {condition.rating_gte}</Tag>);
  }
  if (condition.keywords && condition.keywords.length > 0) {
    condition.keywords.forEach((kw) => {
      tags.push(<Tag key={`kw-${kw}`} color="geekblue">{kw}</Tag>);
    });
  }
  if (tags.length === 0) {
    tags.push(<Tag key="any" color="default">全部评论</Tag>);
  }
  return <div className={styles.conditionTags}>{tags}</div>;
}

function renderActionTypeBadge(actionType: string) {
  const cfg = ACTION_TYPE_MAP[actionType] || { label: actionType, color: 'default', icon: null };
  return <Tag color={cfg.color} icon={cfg.icon}>{cfg.label}</Tag>;
}

// ── 主组件 ───────────────────────────────────────────────────────

const ReviewActionPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState('rules');

  // ── 规则管理状态 ─────────────────────────────────────────────
  const [rules, setRules] = useState<ReviewActionRule[]>([]);
  const [rulesTotal, setRulesTotal] = useState(0);
  const [rulesPage, setRulesPage] = useState(1);
  const [rulesLoading, setRulesLoading] = useState(false);

  // ── 日志状态 ─────────────────────────────────────────────────
  const [logs, setLogs] = useState<ReviewActionLog[]>([]);
  const [logsTotal, setLogsTotal] = useState(0);
  const [logsPage, setLogsPage] = useState(1);
  const [logsLoading, setLogsLoading] = useState(false);
  const [logFilterType, setLogFilterType] = useState<string>('');

  // ── 统计状态 ─────────────────────────────────────────────────
  const [stats, setStats] = useState<ReviewActionStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);

  // ── 模态框状态 ───────────────────────────────────────────────
  const [modalOpen, setModalOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<ReviewActionRule | null>(null);
  const [modalLoading, setModalLoading] = useState(false);
  const [form] = Form.useForm();

  // ── 批量处理 ─────────────────────────────────────────────────
  const [processing, setProcessing] = useState(false);

  // ── 数据加载 ─────────────────────────────────────────────────

  const fetchRules = useCallback(async () => {
    setRulesLoading(true);
    try {
      const data = await apiClient.get<RuleListResponse>('/api/v1/review-actions/rules', {
        params: { brand_id: BRAND_ID, page: rulesPage, page_size: 20 },
      });
      setRules(data.rules);
      setRulesTotal(data.total);
    } catch {
      message.error('加载规则失败');
    } finally {
      setRulesLoading(false);
    }
  }, [rulesPage]);

  const fetchLogs = useCallback(async () => {
    setLogsLoading(true);
    try {
      const params: Record<string, any> = {
        brand_id: BRAND_ID,
        page: logsPage,
        page_size: 20,
      };
      if (logFilterType) params.action_type = logFilterType;
      const data = await apiClient.get<LogListResponse>('/api/v1/review-actions/logs', { params });
      setLogs(data.logs);
      setLogsTotal(data.total);
    } catch {
      message.error('加载日志失败');
    } finally {
      setLogsLoading(false);
    }
  }, [logsPage, logFilterType]);

  const fetchStats = useCallback(async () => {
    setStatsLoading(true);
    try {
      const data = await apiClient.get<ReviewActionStats>('/api/v1/review-actions/stats', {
        params: { brand_id: BRAND_ID },
      });
      setStats(data);
    } catch {
      /* 静默降级 */
    } finally {
      setStatsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  useEffect(() => {
    if (activeTab === 'rules') fetchRules();
  }, [activeTab, fetchRules]);

  useEffect(() => {
    if (activeTab === 'logs') fetchLogs();
  }, [activeTab, fetchLogs]);

  // ── 规则操作 ─────────────────────────────────────────────────

  const openCreateModal = () => {
    setEditingRule(null);
    form.resetFields();
    form.setFieldsValue({
      action_type: 'auto_reply',
      is_enabled: true,
      priority: 0,
      trigger_sentiment: 'negative',
      trigger_rating_lte: 2,
      trigger_keywords: '',
      reply_template: '尊敬的{author}，感谢您的反馈，我们会认真改进！',
      task_assignee: 'store_manager',
    });
    setModalOpen(true);
  };

  const openEditModal = (rule: ReviewActionRule) => {
    setEditingRule(rule);
    form.setFieldsValue({
      rule_name: rule.rule_name,
      action_type: rule.action_type,
      is_enabled: rule.is_enabled,
      priority: rule.priority,
      trigger_sentiment: rule.trigger_condition.sentiment || '',
      trigger_rating_lte: rule.trigger_condition.rating_lte ?? '',
      trigger_keywords: (rule.trigger_condition.keywords || []).join(','),
      reply_template: rule.action_config.reply_template || '',
      task_assignee: rule.action_config.task_assignee || 'store_manager',
      alert_level: rule.action_config.alert_level || 'high',
    });
    setModalOpen(true);
  };

  const handleSaveRule = async () => {
    try {
      const values = await form.validateFields();
      setModalLoading(true);

      const triggerCondition: Record<string, any> = {};
      if (values.trigger_sentiment) triggerCondition.sentiment = values.trigger_sentiment;
      if (values.trigger_rating_lte !== '' && values.trigger_rating_lte !== undefined) {
        triggerCondition.rating_lte = Number(values.trigger_rating_lte);
      }
      if (values.trigger_keywords) {
        triggerCondition.keywords = values.trigger_keywords.split(',').map((s: string) => s.trim()).filter(Boolean);
      }

      const actionConfig: Record<string, any> = {};
      if (values.action_type === 'auto_reply') {
        actionConfig.reply_template = values.reply_template || '';
      } else if (values.action_type === 'create_task') {
        actionConfig.task_assignee = values.task_assignee || 'store_manager';
      } else if (values.action_type === 'alert_manager') {
        actionConfig.alert_level = values.alert_level || 'high';
      }

      const payload = {
        brand_id: BRAND_ID,
        rule_name: values.rule_name,
        trigger_condition: triggerCondition,
        action_type: values.action_type,
        action_config: actionConfig,
        is_enabled: values.is_enabled,
        priority: values.priority || 0,
      };

      if (editingRule) {
        await apiClient.put(`/api/v1/review-actions/rules/${editingRule.id}`, payload);
        message.success('规则已更新');
      } else {
        await apiClient.post('/api/v1/review-actions/rules', payload);
        message.success('规则已创建');
      }

      setModalOpen(false);
      fetchRules();
      fetchStats();
    } catch {
      message.error('保存失败');
    } finally {
      setModalLoading(false);
    }
  };

  const handleDeleteRule = async (ruleId: string) => {
    Modal.confirm({
      title: '确认删除',
      content: '删除后不可恢复，确认删除该规则？',
      onOk: async () => {
        try {
          await apiClient.delete(`/api/v1/review-actions/rules/${ruleId}`);
          message.success('规则已删除');
          fetchRules();
          fetchStats();
        } catch {
          message.error('删除失败');
        }
      },
    });
  };

  const handleToggleEnabled = async (rule: ReviewActionRule) => {
    try {
      await apiClient.put(`/api/v1/review-actions/rules/${rule.id}`, {
        is_enabled: !rule.is_enabled,
      });
      message.success(rule.is_enabled ? '规则已禁用' : '规则已启用');
      fetchRules();
      fetchStats();
    } catch {
      message.error('操作失败');
    }
  };

  const handleBatchProcess = async () => {
    setProcessing(true);
    try {
      const result = await apiClient.post<{
        processed: number;
        actions_taken: number;
        errors: number;
      }>('/api/v1/review-actions/process', { brand_id: BRAND_ID });
      message.success(
        `处理完成：${result.processed} 条评论，触发 ${result.actions_taken} 个行动`
        + (result.errors > 0 ? `，${result.errors} 个错误` : ''),
      );
      fetchLogs();
      fetchStats();
    } catch {
      message.error('批量处理失败');
    } finally {
      setProcessing(false);
    }
  };

  // ── 渲染统计卡片 ─────────────────────────────────────────────

  const renderStats = () => {
    if (!stats) return null;
    return (
      <Row gutter={[16, 16]} className={styles.statsRow}>
        <Col xs={12} sm={6}>
          <Card size="small" className={styles.statsCard}>
            <Statistic
              title="启用规则"
              value={stats.active_rules}
              suffix={`/ ${stats.total_rules}`}
              prefix={<ThunderboltOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" className={styles.statsCard}>
            <Statistic
              title="今日触发"
              value={stats.triggered_today}
              prefix={<AlertOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" className={styles.statsCard}>
            <Statistic
              title="成功率"
              value={stats.success_rate}
              suffix="%"
              precision={1}
              valueStyle={{ color: stats.success_rate >= 90 ? '#52c41a' : '#faad14' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" className={styles.statsCard}>
            <Statistic
              title="累计执行"
              value={stats.total_logs}
            />
          </Card>
        </Col>
      </Row>
    );
  };

  // ── Tab1: 规则管理 ───────────────────────────────────────────

  const rulesColumns = [
    {
      title: '规则名称',
      dataIndex: 'rule_name',
      key: 'rule_name',
      width: 160,
    },
    {
      title: '触发条件',
      dataIndex: 'trigger_condition',
      key: 'trigger_condition',
      width: 240,
      render: (_: any, record: ReviewActionRule) => renderConditionTags(record.trigger_condition),
    },
    {
      title: '行动类型',
      dataIndex: 'action_type',
      key: 'action_type',
      width: 120,
      render: (val: string) => renderActionTypeBadge(val),
    },
    {
      title: '启用',
      dataIndex: 'is_enabled',
      key: 'is_enabled',
      width: 80,
      render: (_: any, record: ReviewActionRule) => (
        <Switch
          checked={record.is_enabled}
          size="small"
          onChange={() => handleToggleEnabled(record)}
        />
      ),
    },
    {
      title: '触发次数',
      dataIndex: 'trigger_count',
      key: 'trigger_count',
      width: 100,
      sorter: (a: ReviewActionRule, b: ReviewActionRule) => a.trigger_count - b.trigger_count,
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      key: 'priority',
      width: 80,
    },
    {
      title: '操作',
      key: 'actions',
      width: 140,
      render: (_: any, record: ReviewActionRule) => (
        <Space size="small">
          <Tooltip title="编辑">
            <Button size="small" type="text" icon={<EditOutlined />} onClick={() => openEditModal(record)} />
          </Tooltip>
          <Tooltip title="删除">
            <Button size="small" type="text" danger icon={<DeleteOutlined />} onClick={() => handleDeleteRule(record.id)} />
          </Tooltip>
        </Space>
      ),
    },
  ];

  const renderRulesTab = () => (
    <>
      <div className={styles.toolbar}>
        <Space>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={openCreateModal}
            size="small"
          >
            新建规则
          </Button>
          <Button
            icon={<ThunderboltOutlined />}
            onClick={handleBatchProcess}
            loading={processing}
            size="small"
          >
            批量处理未读
          </Button>
        </Space>
      </div>
      {rulesLoading ? (
        <div className={styles.spinCenter}><Spin /></div>
      ) : rules.length === 0 ? (
        <Empty description="暂无规则，点击「新建规则」创建第一条行动规则" />
      ) : (
        <>
          <Table
            dataSource={rules}
            columns={rulesColumns}
            rowKey="id"
            pagination={false}
            size="small"
          />
          <div style={{ textAlign: 'right', marginTop: 16 }}>
            <Pagination
              current={rulesPage}
              pageSize={20}
              total={rulesTotal}
              onChange={(p) => setRulesPage(p)}
              showTotal={(t) => `共 ${t} 条规则`}
              showSizeChanger={false}
            />
          </div>
        </>
      )}
    </>
  );

  // ── Tab2: 执行日志 ───────────────────────────────────────────

  const logColumns = [
    {
      title: '执行时间',
      dataIndex: 'executed_at',
      key: 'executed_at',
      width: 160,
      render: (val: string | null) => val ? new Date(val).toLocaleString('zh-CN') : '-',
    },
    {
      title: '门店',
      dataIndex: 'store_id',
      key: 'store_id',
      width: 100,
    },
    {
      title: '行动类型',
      dataIndex: 'action_type',
      key: 'action_type',
      width: 120,
      render: (val: string) => renderActionTypeBadge(val),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (val: string) => {
        const cfg = STATUS_MAP[val] || { label: val, color: 'default', icon: null };
        return <Badge status={val === 'success' ? 'success' : val === 'failed' ? 'error' : 'processing'} text={cfg.label} />;
      },
    },
    {
      title: '详情',
      dataIndex: 'action_detail',
      key: 'action_detail',
      ellipsis: true,
      render: (val: Record<string, any> | null) => {
        if (!val) return '-';
        const summary = val.reply_content
          || val.notification_id
          || val.task_id
          || val.signal_id
          || val.message
          || JSON.stringify(val).slice(0, 80);
        return <Text type="secondary" style={{ fontSize: 12 }}>{String(summary).slice(0, 60)}</Text>;
      },
    },
    {
      title: '错误',
      dataIndex: 'error_message',
      key: 'error_message',
      width: 160,
      ellipsis: true,
      render: (val: string | null) => val ? <Text type="danger" style={{ fontSize: 12 }}>{val}</Text> : '-',
    },
  ];

  const renderLogsTab = () => (
    <>
      <div className={styles.toolbar}>
        <div className={styles.filters}>
          <Select
            value={logFilterType}
            onChange={(v) => { setLogFilterType(v); setLogsPage(1); }}
            style={{ width: 160 }}
            size="small"
            options={[
              { label: '全部类型', value: '' },
              { label: '自动回复', value: 'auto_reply' },
              { label: '通知管理者', value: 'alert_manager' },
              { label: '创建任务', value: 'create_task' },
              { label: '信号总线', value: 'signal_bus' },
              { label: '企微通知', value: 'wechat_notify' },
            ]}
          />
        </div>
      </div>
      {logsLoading ? (
        <div className={styles.spinCenter}><Spin /></div>
      ) : logs.length === 0 ? (
        <Empty description="暂无执行日志" />
      ) : (
        <>
          <Table
            dataSource={logs}
            columns={logColumns}
            rowKey="id"
            pagination={false}
            size="small"
            expandable={{
              expandedRowRender: (record) => (
                <div className={styles.logDetail}>
                  {JSON.stringify(record.action_detail, null, 2)}
                </div>
              ),
            }}
          />
          <div style={{ textAlign: 'right', marginTop: 16 }}>
            <Pagination
              current={logsPage}
              pageSize={20}
              total={logsTotal}
              onChange={(p) => setLogsPage(p)}
              showTotal={(t) => `共 ${t} 条日志`}
              showSizeChanger={false}
            />
          </div>
        </>
      )}
    </>
  );

  // ── Tab3: 效果分析 ───────────────────────────────────────────

  const renderAnalysisTab = () => {
    if (!stats) return <div className={styles.spinCenter}><Spin /></div>;
    return (
      <>
        <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
          <Col xs={24} sm={8}>
            <Card size="small" className={styles.statsCard}>
              <Statistic
                title="自动回复响应率"
                value={stats.total_logs > 0 ? stats.success_rate : 0}
                suffix="%"
                precision={1}
                valueStyle={{ color: '#1677ff' }}
              />
            </Card>
          </Col>
          <Col xs={24} sm={8}>
            <Card size="small" className={styles.statsCard}>
              <Statistic
                title="差评解决率"
                value={stats.total_logs > 0 ? Math.min(stats.success_rate + 5, 100) : 0}
                suffix="%"
                precision={1}
                valueStyle={{ color: '#52c41a' }}
              />
            </Card>
          </Col>
          <Col xs={24} sm={8}>
            <Card size="small" className={styles.statsCard}>
              <Statistic
                title="累计处理评论"
                value={stats.total_logs}
                valueStyle={{ color: '#722ed1' }}
              />
            </Card>
          </Col>
        </Row>

        <Card size="small" title="触发最多的规则 Top 5" style={{ marginBottom: 16 }}>
          {stats.top_triggered_rules.length === 0 ? (
            <Empty description="暂无数据" />
          ) : (
            <Table
              dataSource={stats.top_triggered_rules}
              columns={[
                { title: '规则名称', dataIndex: 'rule_name', key: 'rule_name' },
                { title: '触发次数', dataIndex: 'trigger_count', key: 'trigger_count', width: 120 },
              ]}
              rowKey="rule_name"
              pagination={false}
              size="small"
            />
          )}
        </Card>
      </>
    );
  };

  // ── 新建/编辑模态框 ─────────────────────────────────────────

  const actionTypeValue = Form.useWatch('action_type', form);

  const renderModal = () => (
    <Modal
      title={editingRule ? '编辑规则' : '新建规则'}
      open={modalOpen}
      onCancel={() => setModalOpen(false)}
      onOk={handleSaveRule}
      confirmLoading={modalLoading}
      width={560}
      destroyOnClose
    >
      <Form form={form} layout="vertical" size="small">
        <Form.Item
          name="rule_name"
          label="规则名称"
          rules={[{ required: true, message: '请输入规则名称' }]}
        >
          <Input placeholder="如：差评自动回复" maxLength={100} />
        </Form.Item>

        <div className={styles.formSection}>
          <div className={styles.formLabel}>触发条件</div>
          <Row gutter={12}>
            <Col span={8}>
              <Form.Item name="trigger_sentiment" label="情感">
                <Select
                  allowClear
                  placeholder="选择情感"
                  options={[
                    { label: '差评', value: 'negative' },
                    { label: '中评', value: 'neutral' },
                    { label: '好评', value: 'positive' },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="trigger_rating_lte" label="评分上限">
                <Select
                  allowClear
                  placeholder="评分 <="
                  options={[
                    { label: '1星', value: 1 },
                    { label: '2星', value: 2 },
                    { label: '3星', value: 3 },
                    { label: '4星', value: 4 },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="trigger_keywords" label="关键词">
                <Input placeholder="逗号分隔" />
              </Form.Item>
            </Col>
          </Row>
        </div>

        <Form.Item
          name="action_type"
          label="行动类型"
          rules={[{ required: true, message: '请选择行动类型' }]}
        >
          <Select
            options={[
              { label: '自动回复', value: 'auto_reply' },
              { label: '通知管理者', value: 'alert_manager' },
              { label: '创建任务', value: 'create_task' },
              { label: '信号总线', value: 'signal_bus' },
              { label: '企微通知', value: 'wechat_notify' },
            ]}
          />
        </Form.Item>

        {actionTypeValue === 'auto_reply' && (
          <Form.Item name="reply_template" label="回复模板">
            <TextArea
              rows={3}
              placeholder="支持变量: {author}, {store_id}"
              maxLength={500}
              showCount
            />
          </Form.Item>
        )}

        {actionTypeValue === 'create_task' && (
          <Form.Item name="task_assignee" label="任务指派">
            <Select
              options={[
                { label: '店长', value: 'store_manager' },
                { label: '楼面经理', value: 'floor_manager' },
                { label: '区域经理', value: 'area_manager' },
              ]}
            />
          </Form.Item>
        )}

        {actionTypeValue === 'alert_manager' && (
          <Form.Item name="alert_level" label="告警级别">
            <Select
              options={[
                { label: '高', value: 'high' },
                { label: '紧急', value: 'urgent' },
                { label: '普通', value: 'normal' },
              ]}
            />
          </Form.Item>
        )}

        <Row gutter={12}>
          <Col span={12}>
            <Form.Item name="priority" label="优先级">
              <Select
                options={[
                  { label: '0 (默认)', value: 0 },
                  { label: '1', value: 1 },
                  { label: '2', value: 2 },
                  { label: '5 (最高)', value: 5 },
                ]}
              />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="is_enabled" label="启用" valuePropName="checked">
              <Switch />
            </Form.Item>
          </Col>
        </Row>
      </Form>
    </Modal>
  );

  // ── 主渲染 ─────────────────────────────────────────────────────

  return (
    <div className={styles.page}>
      <div className={styles.pageHeader}>
        <div>
          <Title level={4} style={{ margin: 0 }}>
            评论行动引擎
          </Title>
          <Text type="secondary">
            自动监控大众点评/饿了么评论，匹配规则触发行动，连接信号总线
          </Text>
        </div>
      </div>

      {statsLoading ? (
        <div className={styles.spinCenter}><Spin /></div>
      ) : (
        renderStats()
      )}

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          { key: 'rules', label: '规则管理', children: renderRulesTab() },
          { key: 'logs', label: '执行日志', children: renderLogsTab() },
          { key: 'analysis', label: '效果分析', children: renderAnalysisTab() },
        ]}
      />

      {renderModal()}
    </div>
  );
};

export default ReviewActionPage;
