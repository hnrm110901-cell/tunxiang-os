/**
 * ContentCalendarPage — 智能内容工厂 / 内容日历管理
 * 四大模块：月历视图 / 内容管理 / AI生成 / 周计划生成器
 * API: tx-growth :8004
 * S3W11-12 Smart Content Factory
 */
import { useRef, useState, useEffect, useCallback } from 'react';
import {
  ProTable,
  ProColumns,
  ActionType,
  ModalForm,
  ProFormText,
  ProFormSelect,
  ProFormTextArea,
  ProFormDateTimePicker,
} from '@ant-design/pro-components';
import {
  Badge,
  Button,
  Calendar,
  Card,
  Col,
  Descriptions,
  Drawer,
  message,
  Modal,
  Row,
  Space,
  Statistic,
  Tabs,
  Tag,
  Typography,
  Spin,
  Tooltip,
  List,
} from 'antd';
import {
  PlusOutlined,
  RobotOutlined,
  CalendarOutlined,
  SendOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  EditOutlined,
  DeleteOutlined,
  ScheduleOutlined,
  ThunderboltOutlined,
  FileTextOutlined,
} from '@ant-design/icons';
import type { Dayjs } from 'dayjs';
import dayjs from 'dayjs';
import { txFetchData } from '../../api';

const { Text, Title } = Typography;

// --- Types ---

type ContentStatus = 'draft' | 'scheduled' | 'publishing' | 'published' | 'failed' | 'cancelled';
type ContentType = 'moments' | 'wecom_chat' | 'sms' | 'poster' | 'short_video_script' | 'dish_story' | 'seasonal_campaign' | 'live_preview';

interface ContentEntry {
  id: string;
  store_id: string | null;
  title: string;
  content_type: ContentType;
  content_body: string;
  media_urls: { url: string; type: 'image' | 'video' }[];
  target_channels: { channel: string; group_id?: string }[];
  tags: string[];
  ai_generated: boolean;
  ai_model: string | null;
  status: ContentStatus;
  scheduled_at: string | null;
  published_at: string | null;
  created_by: string | null;
  approved_by: string | null;
  approved_at: string | null;
  view_count: number;
  click_count: number;
  share_count: number;
  created_at: string;
  updated_at: string;
}

interface CalendarDateMap {
  [date: string]: {
    id: string;
    title: string;
    content_type: ContentType;
    status: ContentStatus;
    ai_generated: boolean;
  }[];
}

// --- Constants ---

const CONTENT_TYPE_TAG: Record<ContentType, { color: string; label: string }> = {
  moments: { color: 'green', label: '朋友圈' },
  wecom_chat: { color: 'blue', label: '企微会话' },
  sms: { color: 'orange', label: '短信' },
  poster: { color: 'purple', label: '海报' },
  short_video_script: { color: 'magenta', label: '短视频脚本' },
  dish_story: { color: 'cyan', label: '菜品故事' },
  seasonal_campaign: { color: 'gold', label: '时令活动' },
  live_preview: { color: 'red', label: '直播预告' },
};

const STATUS_BADGE: Record<ContentStatus, { status: 'default' | 'success' | 'warning' | 'error' | 'processing'; text: string }> = {
  draft: { status: 'default', text: '草稿' },
  scheduled: { status: 'processing', text: '已排期' },
  publishing: { status: 'warning', text: '发布中' },
  published: { status: 'success', text: '已发布' },
  failed: { status: 'error', text: '发布失败' },
  cancelled: { status: 'default', text: '已取消' },
};

const AI_GENERATE_MODES = [
  { value: 'auto', label: '自由生成' },
  { value: 'dish', label: '菜品推广' },
  { value: 'holiday', label: '节日营销' },
  { value: 'weekly_plan', label: '一周计划' },
];

const CHANNEL_OPTIONS = [
  { value: 'moments', label: '朋友圈' },
  { value: 'wecom_chat', label: '企微会话' },
  { value: 'sms', label: '短信' },
  { value: 'poster', label: '海报' },
  { value: 'short_video_script', label: '短视频脚本' },
  { value: 'dish_story', label: '菜品故事' },
  { value: 'seasonal_campaign', label: '时令活动' },
  { value: 'live_preview', label: '直播预告' },
];

// --- API ---

async function fetchContentList(params: {
  status?: string;
  content_type?: string;
  page?: number;
  size?: number;
}): Promise<{ items: ContentEntry[]; total: number }> {
  try {
    const qs = new URLSearchParams();
    if (params.status) qs.set('status', params.status);
    if (params.content_type) qs.set('content_type', params.content_type);
    qs.set('page', String(params.page ?? 1));
    qs.set('size', String(params.size ?? 20));
    return await txFetchData<{ items: ContentEntry[]; total: number }>(
      `/api/v1/growth/content-calendar?${qs.toString()}`
    );
  } catch {
    return { items: [], total: 0 };
  }
}

async function fetchCalendarView(year: number, month: number): Promise<CalendarDateMap> {
  try {
    const res = await txFetchData<{ dates: CalendarDateMap }>(
      `/api/v1/growth/content-calendar/calendar-view?year=${year}&month=${month}`
    );
    return res?.dates ?? {};
  } catch {
    return {};
  }
}

async function createContent(data: Record<string, unknown>): Promise<{ id: string } | null> {
  try {
    return await txFetchData<{ id: string }>('/api/v1/growth/content-calendar', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  } catch {
    return null;
  }
}

async function updateContent(id: string, data: Record<string, unknown>): Promise<boolean> {
  try {
    await txFetchData(`/api/v1/growth/content-calendar/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
    return true;
  } catch {
    return false;
  }
}

async function deleteContent(id: string): Promise<boolean> {
  try {
    await txFetchData(`/api/v1/growth/content-calendar/${id}`, { method: 'DELETE' });
    return true;
  } catch {
    return false;
  }
}

async function aiGenerate(data: Record<string, unknown>): Promise<Record<string, unknown> | null> {
  try {
    return await txFetchData<Record<string, unknown>>('/api/v1/growth/content-calendar/auto-generate', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  } catch {
    return null;
  }
}

async function scheduleContent(id: string, scheduledAt: string): Promise<boolean> {
  try {
    await txFetchData(`/api/v1/growth/content-calendar/${id}/schedule`, {
      method: 'POST',
      body: JSON.stringify({ scheduled_at: scheduledAt }),
    });
    return true;
  } catch {
    return false;
  }
}

async function publishContent(id: string): Promise<boolean> {
  try {
    await txFetchData(`/api/v1/growth/content-calendar/${id}/publish`, { method: 'POST' });
    return true;
  } catch {
    return false;
  }
}

// === Component ===

export default function ContentCalendarPage() {
  const tableRef = useRef<ActionType>();
  const [activeTab, setActiveTab] = useState<string>('calendar');
  const [calendarData, setCalendarData] = useState<CalendarDateMap>({});
  const [calendarMonth, setCalendarMonth] = useState<Dayjs>(dayjs());
  const [calendarLoading, setCalendarLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const [detailDrawer, setDetailDrawer] = useState<ContentEntry | null>(null);
  const [scheduleModal, setScheduleModal] = useState<string | null>(null);
  const [aiGenerating, setAiGenerating] = useState(false);
  const [aiResult, setAiResult] = useState<Record<string, unknown> | null>(null);

  // --- Calendar data loading ---
  const loadCalendar = useCallback(async (d: Dayjs) => {
    setCalendarLoading(true);
    const data = await fetchCalendarView(d.year(), d.month() + 1);
    setCalendarData(data);
    setCalendarLoading(false);
  }, []);

  useEffect(() => {
    loadCalendar(calendarMonth);
  }, [calendarMonth, loadCalendar]);

  // --- Calendar cell renderer ---
  const dateCellRender = (value: Dayjs) => {
    const key = value.format('YYYY-MM-DD');
    const entries = calendarData[key];
    if (!entries || entries.length === 0) return null;
    return (
      <List
        size="small"
        dataSource={entries.slice(0, 3)}
        renderItem={(item) => {
          const typeTag = CONTENT_TYPE_TAG[item.content_type as ContentType];
          return (
            <List.Item style={{ padding: '2px 0', border: 'none' }}>
              <Tooltip title={item.title}>
                <Tag
                  color={typeTag?.color ?? 'default'}
                  style={{ fontSize: 11, lineHeight: '18px', margin: 0, maxWidth: '100%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                >
                  {item.ai_generated ? <RobotOutlined style={{ marginRight: 2 }} /> : null}
                  {item.title.slice(0, 8)}
                </Tag>
              </Tooltip>
            </List.Item>
          );
        }}
      />
    );
  };

  // --- Table columns ---
  const columns: ProColumns<ContentEntry>[] = [
    {
      title: '标题',
      dataIndex: 'title',
      width: 200,
      ellipsis: true,
      render: (_, r) => (
        <a onClick={() => setDetailDrawer(r)}>
          {r.ai_generated && <RobotOutlined style={{ marginRight: 4, color: '#1890ff' }} />}
          {r.title}
        </a>
      ),
    },
    {
      title: '类型',
      dataIndex: 'content_type',
      width: 100,
      render: (_, r) => {
        const t = CONTENT_TYPE_TAG[r.content_type];
        return t ? <Tag color={t.color}>{t.label}</Tag> : r.content_type;
      },
      valueEnum: Object.fromEntries(
        Object.entries(CONTENT_TYPE_TAG).map(([k, v]) => [k, { text: v.label }])
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (_, r) => {
        const s = STATUS_BADGE[r.status];
        return s ? <Badge status={s.status} text={s.text} /> : r.status;
      },
      valueEnum: Object.fromEntries(
        Object.entries(STATUS_BADGE).map(([k, v]) => [k, { text: v.text, status: v.status }])
      ),
    },
    {
      title: '排期时间',
      dataIndex: 'scheduled_at',
      width: 160,
      render: (_, r) => r.scheduled_at ? dayjs(r.scheduled_at).format('YYYY-MM-DD HH:mm') : '-',
      sorter: true,
    },
    {
      title: '数据',
      width: 150,
      render: (_, r) => (
        <Space size={12}>
          <Tooltip title="浏览"><Text type="secondary">{r.view_count}</Text></Tooltip>
          <Tooltip title="点击"><Text type="secondary">{r.click_count}</Text></Tooltip>
          <Tooltip title="分享"><Text type="secondary">{r.share_count}</Text></Tooltip>
        </Space>
      ),
    },
    {
      title: '操作',
      width: 200,
      render: (_, r) => (
        <Space size={4}>
          {r.status === 'draft' && (
            <>
              <Tooltip title="编辑">
                <Button size="small" icon={<EditOutlined />} onClick={() => setDetailDrawer(r)} />
              </Tooltip>
              <Tooltip title="排期">
                <Button size="small" icon={<ClockCircleOutlined />} onClick={() => setScheduleModal(r.id)} />
              </Tooltip>
              <Tooltip title="立即发布">
                <Button
                  size="small"
                  icon={<SendOutlined />}
                  onClick={async () => {
                    const ok = await publishContent(r.id);
                    if (ok) { message.success('发布成功'); tableRef.current?.reload(); }
                    else message.error('发布失败');
                  }}
                />
              </Tooltip>
            </>
          )}
          {r.status === 'scheduled' && (
            <Tooltip title="立即发布">
              <Button
                size="small"
                type="primary"
                icon={<SendOutlined />}
                onClick={async () => {
                  const ok = await publishContent(r.id);
                  if (ok) { message.success('发布成功'); tableRef.current?.reload(); }
                  else message.error('发布失败');
                }}
              />
            </Tooltip>
          )}
          <Tooltip title="删除">
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              onClick={() => {
                Modal.confirm({
                  title: '确认删除？',
                  content: `将删除内容「${r.title}」`,
                  onOk: async () => {
                    const ok = await deleteContent(r.id);
                    if (ok) { message.success('已删除'); tableRef.current?.reload(); }
                    else message.error('删除失败');
                  },
                });
              }}
            />
          </Tooltip>
        </Space>
      ),
    },
  ];

  // --- AI Generate handler ---
  const handleAiGenerate = async (values: Record<string, unknown>) => {
    setAiGenerating(true);
    const result = await aiGenerate(values);
    setAiGenerating(false);
    if (result) {
      setAiResult(result);
      message.success('AI内容生成完成');
      return true;
    }
    message.error('生成失败，请重试');
    return false;
  };

  return (
    <div style={{ padding: 24 }}>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small"><Statistic title="草稿" prefix={<FileTextOutlined />} value="-" /></Card>
        </Col>
        <Col span={6}>
          <Card size="small"><Statistic title="已排期" prefix={<ScheduleOutlined />} value="-" valueStyle={{ color: '#1890ff' }} /></Card>
        </Col>
        <Col span={6}>
          <Card size="small"><Statistic title="已发布" prefix={<CheckCircleOutlined />} value="-" valueStyle={{ color: '#52c41a' }} /></Card>
        </Col>
        <Col span={6}>
          <Card size="small"><Statistic title="AI生成" prefix={<RobotOutlined />} value="-" valueStyle={{ color: '#722ed1' }} /></Card>
        </Col>
      </Row>

      <Card
        tabList={[
          { key: 'calendar', tab: <span><CalendarOutlined /> 日历视图</span> },
          { key: 'list', tab: <span><FileTextOutlined /> 列表管理</span> },
        ]}
        activeTabKey={activeTab}
        onTabChange={setActiveTab}
        tabBarExtraContent={
          <Space>
            <Button icon={<RobotOutlined />} onClick={() => setAiOpen(true)}>
              AI生成
            </Button>
            <Button icon={<ThunderboltOutlined />} onClick={async () => {
              setAiGenerating(true);
              const result = await aiGenerate({ mode: 'weekly_plan' });
              setAiGenerating(false);
              if (result) { message.success('周计划已生成'); loadCalendar(calendarMonth); tableRef.current?.reload(); }
              else message.error('生成失败');
            }}>
              生成周计划
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
              新建内容
            </Button>
          </Space>
        }
      >
        {/* --- Calendar View --- */}
        {activeTab === 'calendar' && (
          <Spin spinning={calendarLoading}>
            <Calendar
              value={calendarMonth}
              onPanelChange={(d) => setCalendarMonth(d)}
              cellRender={(current, info) => {
                if (info.type === 'date') return dateCellRender(current);
                return null;
              }}
            />
          </Spin>
        )}

        {/* --- List View --- */}
        {activeTab === 'list' && (
          <ProTable<ContentEntry>
            actionRef={tableRef}
            rowKey="id"
            columns={columns}
            request={async (params) => {
              const res = await fetchContentList({
                status: params.status,
                content_type: params.content_type,
                page: params.current,
                size: params.pageSize,
              });
              return { data: res.items, total: res.total, success: true };
            }}
            search={{ labelWidth: 80, defaultCollapsed: true }}
            pagination={{ defaultPageSize: 20, showSizeChanger: true }}
            options={{ density: true, reload: true }}
          />
        )}
      </Card>

      {/* --- Create Modal --- */}
      <ModalForm
        title="新建内容"
        open={createOpen}
        onOpenChange={setCreateOpen}
        width={640}
        onFinish={async (values) => {
          const result = await createContent(values);
          if (result) {
            message.success('创建成功');
            tableRef.current?.reload();
            loadCalendar(calendarMonth);
            return true;
          }
          message.error('创建失败');
          return false;
        }}
      >
        <ProFormText name="title" label="标题" rules={[{ required: true, max: 200 }]} />
        <ProFormSelect name="content_type" label="内容类型" rules={[{ required: true }]} options={CHANNEL_OPTIONS} />
        <ProFormTextArea name="content_body" label="内容正文" rules={[{ required: true }]} fieldProps={{ rows: 4 }} />
        <ProFormSelect name="target_channels" label="目标渠道" mode="multiple" options={[
          { value: 'wecom_group', label: '企微社群' },
          { value: 'wecom_moments', label: '企微朋友圈' },
          { value: 'sms', label: '短信' },
          { value: 'miniapp', label: '小程序' },
        ]} />
        <ProFormDateTimePicker name="scheduled_at" label="排期时间" />
      </ModalForm>

      {/* --- AI Generate Modal --- */}
      <ModalForm
        title={<span><RobotOutlined /> AI智能生成</span>}
        open={aiOpen}
        onOpenChange={(v) => { setAiOpen(v); if (!v) setAiResult(null); }}
        width={640}
        submitter={{ submitButtonProps: { loading: aiGenerating } }}
        onFinish={handleAiGenerate}
      >
        <ProFormSelect name="mode" label="生成模式" rules={[{ required: true }]} options={AI_GENERATE_MODES} initialValue="auto" />
        <ProFormSelect name="target_channel" label="目标渠道" options={CHANNEL_OPTIONS} initialValue="moments" />
        <ProFormText name="event_name" label="活动名称" />
        <ProFormText name="holiday" label="节日" />
        <ProFormText name="season" label="季节" />
        <ProFormTextArea name="custom_prompt" label="自定义要求" fieldProps={{ rows: 2, placeholder: '可选：补充具体要求...' }} />
        {aiResult && (
          <Card size="small" title="生成结果" style={{ marginTop: 12, background: '#f6ffed' }}>
            <pre style={{ whiteSpace: 'pre-wrap', fontSize: 13 }}>
              {JSON.stringify(aiResult, null, 2)}
            </pre>
          </Card>
        )}
      </ModalForm>

      {/* --- Schedule Modal --- */}
      <ModalForm
        title="设置排期"
        open={!!scheduleModal}
        onOpenChange={(v) => { if (!v) setScheduleModal(null); }}
        width={400}
        onFinish={async (values) => {
          if (!scheduleModal) return false;
          const ok = await scheduleContent(scheduleModal, values.scheduled_at);
          if (ok) {
            message.success('排期已设置');
            tableRef.current?.reload();
            loadCalendar(calendarMonth);
            setScheduleModal(null);
            return true;
          }
          message.error('排期失败');
          return false;
        }}
      >
        <ProFormDateTimePicker name="scheduled_at" label="发布时间" rules={[{ required: true }]} />
      </ModalForm>

      {/* --- Detail Drawer --- */}
      <Drawer
        title={detailDrawer?.title ?? '内容详情'}
        open={!!detailDrawer}
        onClose={() => setDetailDrawer(null)}
        width={560}
      >
        {detailDrawer && (
          <>
            <Descriptions column={2} bordered size="small">
              <Descriptions.Item label="类型">
                <Tag color={CONTENT_TYPE_TAG[detailDrawer.content_type]?.color}>
                  {CONTENT_TYPE_TAG[detailDrawer.content_type]?.label}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                <Badge {...STATUS_BADGE[detailDrawer.status]} />
              </Descriptions.Item>
              <Descriptions.Item label="AI生成">
                {detailDrawer.ai_generated ? <Tag color="purple"><RobotOutlined /> {detailDrawer.ai_model}</Tag> : '手动创建'}
              </Descriptions.Item>
              <Descriptions.Item label="排期">
                {detailDrawer.scheduled_at ? dayjs(detailDrawer.scheduled_at).format('YYYY-MM-DD HH:mm') : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="发布时间">
                {detailDrawer.published_at ? dayjs(detailDrawer.published_at).format('YYYY-MM-DD HH:mm') : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="审批">
                {detailDrawer.approved_at ? dayjs(detailDrawer.approved_at).format('MM-DD HH:mm') : '待审批'}
              </Descriptions.Item>
              <Descriptions.Item label="浏览" span={1}>{detailDrawer.view_count}</Descriptions.Item>
              <Descriptions.Item label="点击">{detailDrawer.click_count}</Descriptions.Item>
              <Descriptions.Item label="分享" span={2}>{detailDrawer.share_count}</Descriptions.Item>
            </Descriptions>
            <Card size="small" title="内容正文" style={{ marginTop: 16 }}>
              <pre style={{ whiteSpace: 'pre-wrap', fontSize: 13 }}>{detailDrawer.content_body}</pre>
            </Card>
            {detailDrawer.tags?.length > 0 && (
              <div style={{ marginTop: 12 }}>
                {detailDrawer.tags.map((tag) => <Tag key={tag}>{tag}</Tag>)}
              </div>
            )}
            <Space style={{ marginTop: 16 }}>
              {detailDrawer.status === 'draft' && (
                <>
                  <Button
                    icon={<CheckCircleOutlined />}
                    onClick={async () => {
                      const ok = await publishContent(detailDrawer.id);
                      if (ok) { message.success('已发布'); setDetailDrawer(null); tableRef.current?.reload(); }
                    }}
                  >
                    立即发布
                  </Button>
                  <Button
                    icon={<ClockCircleOutlined />}
                    onClick={() => { setScheduleModal(detailDrawer.id); setDetailDrawer(null); }}
                  >
                    设置排期
                  </Button>
                </>
              )}
            </Space>
          </>
        )}
      </Drawer>
    </div>
  );
}
