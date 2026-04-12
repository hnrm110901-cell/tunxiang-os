/**
 * CampaignManagePage — 营销活动管理
 * 域C：营销活动 CRUD + 效果统计 + 推送触达
 * API: /api/v1/growth/campaigns/
 */
import { useRef, useState } from 'react';
import {
  ProTable,
  ProColumns,
  ActionType,
  DrawerForm,
  ProFormText,
  ProFormSelect,
  ProFormTextArea,
  ProFormDigit,
  ProFormDateTimeRangePicker,
} from '@ant-design/pro-components';
import {
  Alert,
  Button,
  Descriptions,
  Drawer,
  message,
  Progress,
  Table,
  Tag,
  Typography,
} from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { txFetchData } from '../../api';

const { Text } = Typography;

// ─── 类型定义 ───

type CampaignStatus = 'draft' | 'active' | 'ended' | 'cancelled';
type CampaignType = 'coupon_distribution' | 'points_double' | 'discount' | 'referral_rebate';
type TargetAudience = 'all' | 'vip' | 'regular' | 'churn_risk' | 'new';

interface Campaign {
  id: string;
  name: string;
  type: CampaignType;
  target_audience: TargetAudience;
  start_time: string;
  end_time: string;
  budget_fen: number;
  status: CampaignStatus;
  created_at: string;
}

interface CampaignStats {
  claimed_count: number;
  used_count: number;
  discount_total_fen: number;
  participant_count: number;
}

interface NotificationTask {
  id: string;
  channel: string;
  status: string;
  sent_count: number;
  created_at: string;
}

interface AvailableCoupon {
  id: string;
  name: string;
}

// ─── 常量 ───

const CAMPAIGN_TYPE_MAP: Record<CampaignType, string> = {
  coupon_distribution: '优惠券发放',
  points_double: '积分翻倍',
  discount: '折扣活动',
  referral_rebate: '邀请返利',
};

const TARGET_AUDIENCE_MAP: Record<TargetAudience, string> = {
  all: '全部',
  vip: 'VIP',
  regular: '普通',
  churn_risk: '流失风险',
  new: '新客',
};

const NOTIFICATION_CHANNEL_MAP: Record<string, string> = {
  sms: '短信',
  wechat_template: '微信模板',
  miniapp_push: '小程序推送',
};

const PRESET_TEMPLATES: Record<string, string> = {
  sms: '【屯象OS】您有一张专属优惠券待领取，点击链接立即领取：{link}，有效期至{expiry}。',
  wechat_template: '尊敬的{name}，您好！我们为您准备了专属福利，活动期间享{discount}优惠，期待您的光临！',
  miniapp_push: '专属优惠来袭！限时{discount}折，快来抢先领取，先到先得！',
};

// ─── 状态 Tag 渲染 ───

function StatusTag({ status }: { status: CampaignStatus }) {
  const config: Record<CampaignStatus, { color: string; text: string }> = {
    draft: { color: 'default', text: '草稿' },
    active: { color: 'success', text: '✓ 进行中' },
    ended: { color: 'blue', text: '已结束' },
    cancelled: { color: 'error', text: '已取消' },
  };
  const { color, text } = config[status] ?? { color: 'default', text: status };
  return <Tag color={color}>{text}</Tag>;
}

// ─── 主组件 ───

export function CampaignManagePage() {
  const actionRef = useRef<ActionType>();
  const [createDrawerOpen, setCreateDrawerOpen] = useState(false);
  const [statsDrawerOpen, setStatsDrawerOpen] = useState(false);
  const [notifyDrawerOpen, setNotifyDrawerOpen] = useState(false);
  const [selectedCampaign, setSelectedCampaign] = useState<Campaign | null>(null);
  const [stats, setStats] = useState<CampaignStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [notifyTasks, setNotifyTasks] = useState<NotificationTask[]>([]);
  const [notifyTasksLoading, setNotifyTasksLoading] = useState(false);
  const [notifyChannel, setNotifyChannel] = useState<string>('sms');
  const [notifyTemplate, setNotifyTemplate] = useState<string>(PRESET_TEMPLATES.sms);
  const [sendingNotify, setSendingNotify] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);

  // 打开统计抽屉
  const handleViewStats = async (campaign: Campaign) => {
    setSelectedCampaign(campaign);
    setStatsError(null);
    setStats(null);
    setStatsDrawerOpen(true);
    setStatsLoading(true);
    try {
      const data = await txFetchData<CampaignStats>(`/api/v1/growth/campaigns/${campaign.id}/stats`);
      setStats(data);
    } catch (e: unknown) {
      setStatsError(e instanceof Error ? e.message : '获取统计数据失败');
    } finally {
      setStatsLoading(false);
    }
  };

  // 打开推送面板
  const handleOpenNotify = async (campaign: Campaign) => {
    setSelectedCampaign(campaign);
    setSendError(null);
    setNotifyDrawerOpen(true);
    setNotifyTasksLoading(true);
    try {
      const data = await txFetchData<{ items: NotificationTask[] }>(
        `/api/v1/growth/notifications/tasks?campaign_id=${campaign.id}`,
      );
      setNotifyTasks(data.items ?? []);
    } catch {
      setNotifyTasks([]);
    } finally {
      setNotifyTasksLoading(false);
    }
  };

  // 激活活动 draft → active
  const handleActivate = async (campaign: Campaign) => {
    try {
      await txFetchData(`/api/v1/growth/campaigns/${campaign.id}/activate`, { method: 'POST' });
      message.success('活动已激活');
      actionRef.current?.reload();
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '激活失败');
    }
  };

  // 结束活动 active → ended
  const handleEnd = async (campaign: Campaign) => {
    try {
      await txFetchData(`/api/v1/growth/campaigns/${campaign.id}/end`, { method: 'POST' });
      message.success('活动已结束');
      actionRef.current?.reload();
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '操作失败');
    }
  };

  // 发送推送
  const handleSendNotify = async () => {
    if (!selectedCampaign) return;
    setSendingNotify(true);
    setSendError(null);
    try {
      await txFetchData('/api/v1/growth/notifications/send-campaign', {
        method: 'POST',
        body: JSON.stringify({
          campaign_id: selectedCampaign.id,
          channel: notifyChannel,
          message_template: notifyTemplate,
        }),
      });
      message.success('推送已发送');
      // 刷新发送记录
      const data = await txFetchData<{ items: NotificationTask[] }>(
        `/api/v1/growth/notifications/tasks?campaign_id=${selectedCampaign.id}`,
      );
      setNotifyTasks(data.items ?? []);
    } catch (e: unknown) {
      setSendError(e instanceof Error ? e.message : '发送失败，请重试');
    } finally {
      setSendingNotify(false);
    }
  };

  // 列定义
  const columns: ProColumns<Campaign>[] = [
    {
      title: '活动名称',
      dataIndex: 'name',
      valueType: 'text',
      ellipsis: true,
    },
    {
      title: '类型',
      dataIndex: 'type',
      valueType: 'select',
      valueEnum: Object.fromEntries(
        Object.entries(CAMPAIGN_TYPE_MAP).map(([k, v]) => [k, { text: v }]),
      ),
      render: (_, record) => CAMPAIGN_TYPE_MAP[record.type] ?? record.type,
    },
    {
      title: '目标人群',
      dataIndex: 'target_audience',
      valueType: 'select',
      valueEnum: Object.fromEntries(
        Object.entries(TARGET_AUDIENCE_MAP).map(([k, v]) => [k, { text: v }]),
      ),
      render: (_, record) => TARGET_AUDIENCE_MAP[record.target_audience] ?? record.target_audience,
    },
    {
      title: '开始时间',
      dataIndex: 'start_time',
      valueType: 'dateTime',
      search: false,
      render: (_, record) =>
        record.start_time ? new Date(record.start_time).toLocaleString('zh-CN') : '-',
    },
    {
      title: '结束时间',
      dataIndex: 'end_time',
      valueType: 'dateTime',
      search: false,
      render: (_, record) =>
        record.end_time ? new Date(record.end_time).toLocaleString('zh-CN') : '-',
    },
    {
      title: '预算（元）',
      dataIndex: 'budget_fen',
      valueType: 'money',
      search: false,
      render: (_, record) =>
        record.budget_fen != null ? `¥${(record.budget_fen / 100).toFixed(2)}` : '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      valueType: 'select',
      valueEnum: {
        draft: { text: '草稿', status: 'Default' },
        active: { text: '进行中', status: 'Success' },
        ended: { text: '已结束', status: 'Processing' },
        cancelled: { text: '已取消', status: 'Error' },
      },
      render: (_, record) => <StatusTag status={record.status} />,
    },
    {
      title: '操作',
      valueType: 'option',
      render: (_, record) => {
        const actions: React.ReactNode[] = [
          <a key="stats" onClick={() => handleViewStats(record)}>
            查看统计
          </a>,
          <a key="notify" onClick={() => handleOpenNotify(record)}>
            推送触达
          </a>,
        ];
        if (record.status === 'draft') {
          actions.push(
            <a key="activate" style={{ color: '#0F6E56' }} onClick={() => handleActivate(record)}>
              激活
            </a>,
          );
          actions.push(
            <a key="edit" style={{ color: '#185FA5' }}>
              编辑
            </a>,
          );
        }
        if (record.status === 'active') {
          actions.push(
            <a key="end" style={{ color: '#A32D2D' }} onClick={() => handleEnd(record)}>
              结束
            </a>,
          );
        }
        return actions;
      },
    },
  ];

  // 顶部筛选项（状态、类型、日期范围）通过 ProTable search 实现
  // 日期范围需自定义列（在 search 中用 dateTimeRange）
  const filterColumns: ProColumns<Campaign>[] = [
    ...columns,
    {
      title: '时间范围',
      dataIndex: 'time_range',
      valueType: 'dateTimeRange',
      hideInTable: true,
      search: {
        transform: (value: [string, string]) => ({
          start_time_gte: value?.[0],
          start_time_lte: value?.[1],
        }),
      },
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <ProTable<Campaign>
        headerTitle="营销活动管理"
        actionRef={actionRef}
        rowKey="id"
        columns={filterColumns}
        request={async (params) => {
          const { current, pageSize, name, type, status, start_time_gte, start_time_lte } =
            params as Record<string, unknown>;
          const query = new URLSearchParams();
          if (current) query.set('page', String(current));
          if (pageSize) query.set('size', String(pageSize));
          if (name) query.set('name', String(name));
          if (type) query.set('type', String(type));
          if (status) query.set('status', String(status));
          if (start_time_gte) query.set('start_time_gte', String(start_time_gte));
          if (start_time_lte) query.set('start_time_lte', String(start_time_lte));
          try {
            const data = await txFetchData<{ items: Campaign[]; total: number }>(
              `/api/v1/growth/campaigns/?${query.toString()}`,
            );
            return { data: data.items, total: data.total, success: true };
          } catch {
            return { data: [], total: 0, success: false };
          }
        }}
        search={{ labelWidth: 'auto' }}
        pagination={{ defaultPageSize: 20 }}
        toolBarRender={() => [
          <Button
            key="create"
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setCreateDrawerOpen(true)}
          >
            新建活动
          </Button>,
        ]}
      />

      {/* ─── 创建活动 DrawerForm ─── */}
      <DrawerForm
        title="新建营销活动"
        open={createDrawerOpen}
        onOpenChange={setCreateDrawerOpen}
        width={520}
        onFinish={async (values) => {
          try {
            const [start_time, end_time] = (values.time_range as [string, string]) ?? [];
            await txFetchData('/api/v1/growth/campaigns/', {
              method: 'POST',
              body: JSON.stringify({
                name: values.name,
                type: values.type,
                description: values.description,
                start_time,
                end_time,
                target_audience: values.target_audience,
                budget_fen: Math.round((values.budget_yuan as number) * 100),
                coupon_id: values.coupon_id,
              }),
            });
            message.success('活动创建成功');
            actionRef.current?.reload();
            return true;
          } catch (e: unknown) {
            message.error(e instanceof Error ? e.message : '创建失败');
            return false;
          }
        }}
      >
        <ProFormText
          name="name"
          label="活动名称"
          rules={[{ required: true, message: '请输入活动名称' }]}
          placeholder="请输入活动名称"
        />
        <ProFormSelect
          name="type"
          label="活动类型"
          rules={[{ required: true, message: '请选择活动类型' }]}
          options={Object.entries(CAMPAIGN_TYPE_MAP).map(([value, label]) => ({ value, label }))}
          placeholder="请选择活动类型"
        />
        <ProFormTextArea
          name="description"
          label="活动描述"
          placeholder="请输入活动描述"
          fieldProps={{ rows: 3 }}
        />
        <ProFormDateTimeRangePicker
          name="time_range"
          label="活动时间"
          rules={[{ required: true, message: '请选择活动时间范围' }]}
        />
        <ProFormSelect
          name="target_audience"
          label="目标人群"
          rules={[{ required: true, message: '请选择目标人群' }]}
          options={Object.entries(TARGET_AUDIENCE_MAP).map(([value, label]) => ({ value, label }))}
          placeholder="请选择目标人群"
        />
        <ProFormDigit
          name="budget_yuan"
          label="预算（元）"
          min={0}
          placeholder="请输入预算金额"
          fieldProps={{ precision: 2, addonBefore: '¥' }}
          extra="提交时自动转换为分（×100）"
        />
        <ProFormSelect
          name="coupon_id"
          label="关联优惠券"
          placeholder="请选择优惠券（可选）"
          request={async () => {
            try {
              const data = await txFetchData<{ items: AvailableCoupon[] }>(
                '/api/v1/growth/coupons/available',
              );
              return (data.items ?? []).map((c) => ({ value: c.id, label: c.name }));
            } catch {
              return [];
            }
          }}
        />
      </DrawerForm>

      {/* ─── 活动效果统计 Drawer ─── */}
      <Drawer
        title={`活动效果统计 — ${selectedCampaign?.name ?? ''}`}
        open={statsDrawerOpen}
        onClose={() => {
          setStatsDrawerOpen(false);
          setStats(null);
          setStatsError(null);
        }}
        width={480}
      >
        {statsError && (
          <Alert
            type="error"
            message={statsError}
            showIcon
            style={{ marginBottom: 16 }}
          />
        )}
        {statsLoading && (
          <div style={{ textAlign: 'center', padding: '40px 0', color: '#999' }}>
            加载中...
          </div>
        )}
        {stats && !statsLoading && (
          <>
            <Descriptions column={1} bordered size="small" style={{ marginBottom: 24 }}>
              <Descriptions.Item label="已领取数量">
                {stats.claimed_count.toLocaleString()} 次
              </Descriptions.Item>
              <Descriptions.Item label="已使用数量">
                {stats.used_count.toLocaleString()} 次
              </Descriptions.Item>
              <Descriptions.Item label="折扣总额">
                ¥{(stats.discount_total_fen / 100).toFixed(2)}
              </Descriptions.Item>
              <Descriptions.Item label="参与顾客数">
                {stats.participant_count.toLocaleString()} 人
              </Descriptions.Item>
            </Descriptions>

            <div style={{ marginBottom: 8 }}>
              <Text type="secondary" style={{ fontSize: 13 }}>
                核销率（已使用 / 已领取）
              </Text>
            </div>
            <Progress
              percent={
                stats.claimed_count > 0
                  ? Math.round((stats.used_count / stats.claimed_count) * 100)
                  : 0
              }
              status="active"
              strokeColor="#0F6E56"
              format={(pct) => `${pct}%`}
            />
          </>
        )}
      </Drawer>

      {/* ─── 推送触达面板 Drawer ─── */}
      <Drawer
        title={`推送触达 — ${selectedCampaign?.name ?? ''}`}
        open={notifyDrawerOpen}
        onClose={() => {
          setNotifyDrawerOpen(false);
          setSendError(null);
        }}
        width={560}
      >
        {/* 发送配置区 */}
        <div
          style={{
            background: '#F8F7F5',
            borderRadius: 8,
            padding: 16,
            marginBottom: 24,
          }}
        >
          <div style={{ marginBottom: 12 }}>
            <label style={{ fontSize: 13, color: '#5F5E5A', display: 'block', marginBottom: 6 }}>
              推送渠道
            </label>
            <select
              value={notifyChannel}
              onChange={(e) => {
                setNotifyChannel(e.target.value);
                setNotifyTemplate(PRESET_TEMPLATES[e.target.value] ?? '');
              }}
              style={{
                width: '100%',
                padding: '7px 12px',
                borderRadius: 6,
                border: '1px solid #E8E6E1',
                background: '#fff',
                fontSize: 13,
                outline: 'none',
              }}
            >
              {Object.entries(NOTIFICATION_CHANNEL_MAP).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </div>

          <div style={{ marginBottom: 12 }}>
            <label style={{ fontSize: 13, color: '#5F5E5A', display: 'block', marginBottom: 6 }}>
              消息模板
            </label>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 6 }}>
              {Object.entries(PRESET_TEMPLATES).map(([ch, tpl]) => (
                <button
                  key={ch}
                  onClick={() => {
                    setNotifyChannel(ch);
                    setNotifyTemplate(tpl);
                  }}
                  style={{
                    padding: '3px 10px',
                    borderRadius: 4,
                    border: '1px solid #E8E6E1',
                    background: notifyChannel === ch ? '#FFF3ED' : '#fff',
                    color: notifyChannel === ch ? '#FF6B35' : '#5F5E5A',
                    fontSize: 12,
                    cursor: 'pointer',
                  }}
                >
                  {NOTIFICATION_CHANNEL_MAP[ch]} 模板
                </button>
              ))}
            </div>
            <textarea
              value={notifyTemplate}
              onChange={(e) => setNotifyTemplate(e.target.value)}
              rows={4}
              style={{
                width: '100%',
                padding: '8px 12px',
                borderRadius: 6,
                border: '1px solid #E8E6E1',
                fontSize: 13,
                resize: 'vertical',
                outline: 'none',
                boxSizing: 'border-box',
              }}
            />
          </div>

          {sendError && (
            <Alert
              type="error"
              message={sendError}
              showIcon
              style={{ marginBottom: 12 }}
            />
          )}

          <Button
            type="primary"
            loading={sendingNotify}
            onClick={handleSendNotify}
            block
          >
            发送推送
          </Button>
        </div>

        {/* 发送记录表 */}
        <div style={{ fontSize: 13, fontWeight: 600, color: '#2C2C2A', marginBottom: 8 }}>
          发送记录
        </div>
        <Table<NotificationTask>
          dataSource={notifyTasks}
          rowKey="id"
          loading={notifyTasksLoading}
          size="small"
          pagination={false}
          columns={[
            {
              title: '渠道',
              dataIndex: 'channel',
              render: (v: string) => NOTIFICATION_CHANNEL_MAP[v] ?? v,
            },
            {
              title: '状态',
              dataIndex: 'status',
              render: (v: string) => {
                const color = v === 'success' ? 'success' : v === 'failed' ? 'error' : 'default';
                const label = v === 'success' ? '成功' : v === 'failed' ? '失败' : '处理中';
                return <Tag color={color}>{label}</Tag>;
              },
            },
            {
              title: '发送数',
              dataIndex: 'sent_count',
            },
            {
              title: '发送时间',
              dataIndex: 'created_at',
              render: (v: string) => (v ? new Date(v).toLocaleString('zh-CN') : '-'),
            },
          ]}
        />
      </Drawer>
    </div>
  );
}

