/**
 * GrowthSettingsPage -- 增长配置治理（Sprint D2）
 * 路由: /hq/growth/settings
 * 5个Tab: 旅程机制字典 / 模板管理 / 触达模板 / 频控规则 / 审计日志
 */
import { useState, useEffect, useCallback } from 'react';
import { Card, Tabs, Table, Tag, Switch, message, Space, Spin } from 'antd';
import { SettingOutlined } from '@ant-design/icons';
import { txFetchData } from '../../../api';

// ---- 颜色常量（深色主题） ----
const PAGE_BG = '#0d1e28';
const CARD_BG = '#142833';
const BORDER = '#1e3a4a';
const TEXT_PRIMARY = '#e8e8e8';
const TEXT_SECONDARY = '#8899a6';

// ---- Tab 1: 旅程机制字典 ----

const MECHANISM_DICT = [
  { code: 'identity_anchor', name: '身份锚定', scenario: '首单入会/超级用户仪式', desc: '赋予客户明确身份，建立归属感' },
  { code: 'micro_commitment', name: '最小承诺', scenario: '二访引导/体验邀请', desc: '降低行动门槛，用轻承诺推动回访' },
  { code: 'variable_reward', name: '多样化奖励', scenario: '惊喜奖励/随机礼遇', desc: '不可预测的奖励更能激发好奇心' },
  { code: 'loss_aversion', name: '损失厌恶', scenario: '权益到期/储值余额提醒', desc: '已拥有的即将失去比新获得更有动力' },
  { code: 'relationship_warmup', name: '关系唤醒', scenario: '沉默召回/轻问候', desc: '不带促销的关系维护，重建品牌记忆' },
  { code: 'minimal_action', name: '最小行动', scenario: '一键预订/简化入口', desc: '让客户用最少步骤完成目标动作' },
  { code: 'social_proof', name: '社会证明', scenario: '裂变推荐/口碑传播', desc: '用他人行为影响客户决策' },
  { code: 'service_repair', name: '服务修复', scenario: '投诉修复/情绪承接', desc: '四阶协议：承接->补偿->观察->恢复' },
  { code: 'super_user_exclusive', name: '超级用户专属', scenario: '非折扣型特权', desc: '身份仪式+参与特权+社会证明赋能' },
  { code: 'milestone_celebration', name: '里程碑庆祝', scenario: '成长进阶提醒', desc: '进度可见性+里程碑奖励+下一目标' },
  { code: 'referral_activation', name: '裂变激活', scenario: '高K值场景识别', desc: '生日组织者/家庭聚餐/超级推荐' },
  { code: 'psych_bridge', name: '心理距离修复', scenario: '关系远近修复', desc: '按心理距离选择触达强度' },
];

const mechanismColumns = [
  { title: '机制代码', dataIndex: 'code', key: 'code', render: (v: string) => <Tag color="blue">{v}</Tag> },
  { title: '中文名称', dataIndex: 'name', key: 'name', width: 120 },
  { title: '适用场景', dataIndex: 'scenario', key: 'scenario' },
  { title: '描述', dataIndex: 'desc', key: 'desc' },
];

// ---- Tab 2: 模板管理 ----

interface JourneyTemplate {
  id: string;
  template_name: string;
  journey_type: string;
  mechanism_family: string | null;
  is_active: boolean;
}

function TemplateManageTab() {
  const [templates, setTemplates] = useState<JourneyTemplate[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchTemplates = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await txFetchData<{ items: JourneyTemplate[]; total: number }>(
        '/api/v1/growth/journey-templates?size=100'
      );
      if (resp.data) setTemplates(resp.data.items);
    } catch (err) {
      console.error('fetch templates error', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchTemplates(); }, [fetchTemplates]);

  const handleToggle = async (id: string, active: boolean) => {
    try {
      const action = active ? 'activate' : 'deactivate';
      await txFetchData(`/api/v1/growth/journey-templates/${id}/${action}`, { method: 'POST' });
      message.success(active ? '已激活' : '已停用');
      fetchTemplates();
    } catch (err) {
      message.error('操作失败');
    }
  };

  const activeCount = templates.filter((t) => t.is_active).length;

  return (
    <Spin spinning={loading}>
      <Table
        dataSource={templates}
        rowKey="id"
        pagination={false}
        size="small"
        columns={[
          { title: '模板名称', dataIndex: 'template_name', key: 'template_name' },
          { title: '旅程类型', dataIndex: 'journey_type', key: 'journey_type', render: (v: string) => <Tag>{v}</Tag> },
          { title: '机制族', dataIndex: 'mechanism_family', key: 'mechanism_family', render: (v: string | null) => v ? <Tag color="cyan">{v}</Tag> : '-' },
          {
            title: '状态', dataIndex: 'is_active', key: 'is_active', width: 100,
            render: (active: boolean, record: JourneyTemplate) => (
              <Switch checked={active} onChange={(v) => handleToggle(record.id, v)} size="small" />
            ),
          },
        ]}
      />
      <div style={{ marginTop: 12, color: TEXT_SECONDARY, fontSize: 12 }}>
        共 {templates.length} 条模板，{activeCount} 条激活中
      </div>
    </Spin>
  );
}

// ---- Tab 3: 触达模板 ----

const TOUCH_TEMPLATES = [
  { family: 'identity_anchor', items: [
    { code: 'IA_WELCOME_CARD', name: '入会欢迎卡', mechanism: 'identity_anchor', channel: 'wecom', tone: 'warm', review: false },
    { code: 'IA_SUPER_USER_RITUAL', name: '超级用户仪式', mechanism: 'identity_anchor', channel: 'wecom', tone: 'ceremonial', review: true },
  ]},
  { family: 'micro_commitment', items: [
    { code: 'MC_SECOND_VISIT_INVITE', name: '二访邀请', mechanism: 'micro_commitment', channel: 'wecom', tone: 'casual', review: false },
    { code: 'MC_TASTE_QUIZ', name: '口味小测试', mechanism: 'micro_commitment', channel: 'miniapp', tone: 'playful', review: false },
  ]},
  { family: 'loss_aversion', items: [
    { code: 'LA_EXPIRY_REMIND', name: '权益到期提醒', mechanism: 'loss_aversion', channel: 'sms', tone: 'urgent', review: false },
    { code: 'LA_STORED_VALUE_ALERT', name: '储值余额提醒', mechanism: 'loss_aversion', channel: 'wecom', tone: 'caring', review: false },
  ]},
  { family: 'relationship_warmup', items: [
    { code: 'RW_LIGHT_GREETING', name: '轻问候', mechanism: 'relationship_warmup', channel: 'wecom', tone: 'gentle', review: false },
    { code: 'RW_SILENT_RECALL', name: '沉默召回', mechanism: 'relationship_warmup', channel: 'wecom', tone: 'warm', review: true },
  ]},
  { family: 'service_repair', items: [
    { code: 'SR_APOLOGY_FIRST', name: '致歉承接', mechanism: 'service_repair', channel: 'wecom', tone: 'empathetic', review: true },
    { code: 'SR_COMPENSATION', name: '补偿方案', mechanism: 'service_repair', channel: 'wecom', tone: 'sincere', review: true },
  ]},
];

function TouchTemplateTab() {
  return (
    <div>
      {TOUCH_TEMPLATES.map((group) => (
        <div key={group.family} style={{ marginBottom: 16 }}>
          <div style={{ color: TEXT_PRIMARY, fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
            <Tag color="blue">{group.family}</Tag>
          </div>
          <Table
            dataSource={group.items}
            rowKey="code"
            pagination={false}
            size="small"
            columns={[
              { title: '编码', dataIndex: 'code', key: 'code', width: 200, render: (v: string) => <code style={{ fontSize: 11 }}>{v}</code> },
              { title: '名称', dataIndex: 'name', key: 'name', width: 140 },
              { title: '机制', dataIndex: 'mechanism', key: 'mechanism', width: 140, render: (v: string) => <Tag color="cyan">{v}</Tag> },
              { title: '渠道', dataIndex: 'channel', key: 'channel', width: 100, render: (v: string) => <Tag>{v}</Tag> },
              { title: '语气', dataIndex: 'tone', key: 'tone', width: 100 },
              { title: '需人审', dataIndex: 'review', key: 'review', width: 80, render: (v: boolean) => v ? <Tag color="red">是</Tag> : <Tag color="green">否</Tag> },
            ]}
          />
        </div>
      ))}
    </div>
  );
}

// ---- Tab 4: 频控规则 ----

const CHANNEL_FREQ = [
  { channel: 'wecom', name: '企业微信', max_daily: 3 },
  { channel: 'sms', name: '短信', max_daily: 2 },
  { channel: 'miniapp', name: '小程序订阅消息', max_daily: 5 },
  { channel: 'app_push', name: 'App Push', max_daily: 3 },
  { channel: 'pos_receipt', name: 'POS小票二维码', max_daily: 999 },
  { channel: 'reservation_page', name: '预订确认页', max_daily: 1 },
  { channel: 'store_task', name: '门店人工任务', max_daily: 1 },
];

const freqColumns = [
  { title: '渠道代码', dataIndex: 'channel', key: 'channel', render: (v: string) => <Tag>{v}</Tag> },
  { title: '渠道名称', dataIndex: 'name', key: 'name' },
  { title: '每日上限（/人）', dataIndex: 'max_daily', key: 'max_daily', render: (v: number) => (
    <span style={{ fontWeight: 600, color: v >= 999 ? TEXT_SECONDARY : TEXT_PRIMARY }}>{v >= 999 ? '不限' : v}</span>
  )},
  { title: '状态', key: 'status', render: () => <Tag color="green">生效中</Tag> },
];

// ---- Tab 5: 审计日志 ----

interface AuditItem {
  id: string;
  suggestion_type: string;
  mechanism_type: string | null;
  review_state: string;
  reviewer_id: string | null;
  created_at: string | null;
}

const REVIEW_LABELS: Record<string, string> = {
  pending_review: '待审核', approved: '已通过', rejected: '已退回', published: '已发布', expired: '已过期',
};

function AuditLogTab() {
  const [items, setItems] = useState<AuditItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const resp = await txFetchData<{ items: AuditItem[]; total: number }>(
          '/api/v1/growth/agent-suggestions?size=50'
        );
        if (resp.data) setItems(resp.data.items);
      } catch (err) {
        console.error('fetch audit log error', err);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <Spin spinning={loading}>
      <Table
        dataSource={items}
        rowKey="id"
        pagination={{ pageSize: 20 }}
        size="small"
        columns={[
          { title: '时间', dataIndex: 'created_at', key: 'created_at', width: 160,
            render: (v: string | null) => v ? v.slice(0, 16).replace('T', ' ') : '-' },
          { title: '类型', dataIndex: 'suggestion_type', key: 'suggestion_type', width: 120,
            render: (v: string) => <Tag>{v}</Tag> },
          { title: '机制', dataIndex: 'mechanism_type', key: 'mechanism_type', width: 140,
            render: (v: string | null) => v ? <Tag color="cyan">{v}</Tag> : '-' },
          { title: '审核结果', dataIndex: 'review_state', key: 'review_state', width: 100,
            render: (v: string) => {
              const colors: Record<string, string> = { pending_review: 'orange', approved: 'green', rejected: 'red', published: 'cyan', expired: 'default' };
              return <Tag color={colors[v] || 'default'}>{REVIEW_LABELS[v] || v}</Tag>;
            }},
          { title: '审核人', dataIndex: 'reviewer_id', key: 'reviewer_id', width: 120,
            render: (v: string | null) => v || '-' },
        ]}
      />
    </Spin>
  );
}

// ---- 主页面 ----

export function GrowthSettingsPage() {
  return (
    <div style={{ padding: 24, background: PAGE_BG, minHeight: '100vh' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 24 }}>
        <SettingOutlined style={{ color: TEXT_PRIMARY, fontSize: 20 }} />
        <h2 style={{ color: TEXT_PRIMARY, margin: 0 }}>增长配置治理</h2>
      </div>

      <Card style={{ background: CARD_BG, border: `1px solid ${BORDER}` }}>
        <Tabs
          defaultActiveKey="mechanism"
          items={[
            {
              key: 'mechanism',
              label: '旅程机制字典',
              children: (
                <Table
                  dataSource={MECHANISM_DICT}
                  columns={mechanismColumns}
                  rowKey="code"
                  pagination={false}
                  size="small"
                />
              ),
            },
            {
              key: 'templates',
              label: '模板管理',
              children: <TemplateManageTab />,
            },
            {
              key: 'touch',
              label: '触达模板',
              children: <TouchTemplateTab />,
            },
            {
              key: 'freq',
              label: '频控规则',
              children: (
                <div>
                  <Table
                    dataSource={CHANNEL_FREQ}
                    columns={freqColumns}
                    rowKey="channel"
                    pagination={false}
                    size="small"
                  />
                  <div style={{ marginTop: 12, color: TEXT_SECONDARY, fontSize: 12 }}>
                    频控编辑功能将在后续版本开放
                  </div>
                </div>
              ),
            },
            {
              key: 'audit',
              label: '审计日志',
              children: <AuditLogTab />,
            },
          ]}
        />
      </Card>
    </div>
  );
}
