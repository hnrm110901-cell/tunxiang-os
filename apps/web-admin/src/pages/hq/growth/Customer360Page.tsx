/**
 * Customer360Page — 客户360详情（单客经营中枢）
 * 路由: /hq/growth/customers/:customerId
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Card, Tag, Button, Space, Row, Col, Statistic, Table, Timeline, Spin, Descriptions, Progress, message,
  Modal, Select, Radio, Tabs, List,
} from 'antd';
import type { TabsProps } from 'antd';
import { BulbOutlined } from '@ant-design/icons';
import {
  ArrowLeftOutlined, RocketOutlined, RobotOutlined, StarOutlined,
  PhoneOutlined, ShopOutlined, CrownOutlined, HeartOutlined, TrophyOutlined, ShareAltOutlined,
} from '@ant-design/icons';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { txFetch } from '../../../api';
import type { GrowthProfile, TouchExecution, AgentSuggestion, ServiceRepairCase, JourneyTemplate } from '../../../api/growthHubApi';

echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);

// ---- 颜色常量 ----
const PAGE_BG = '#0d1e28';
const CARD_BG = '#142833';
const BORDER = '#1e3a4a';
const TEXT_PRIMARY = '#e8e8e8';
const TEXT_SECONDARY = '#8899a6';
const BRAND_ORANGE = '#FF6B35';
const SUCCESS_GREEN = '#52c41a';
const WARNING_ORANGE = '#faad14';
const DANGER_RED = '#ff4d4f';
const INFO_BLUE = '#1890ff';

// ---- 类型 ----
interface CustomerDetail {
  customer_id: string;
  display_name: string;
  primary_phone: string | null;
  level: string;
  total_spend_fen: number;
  order_count: number;
  avg_order_fen: number;
  rfm_tag: string | null;
  tags: string[];
  recent_orders: RecentOrder[];
  spend_trend: { month: string; amount_fen: number }[];
}

interface RecentOrder {
  order_id: string;
  store_name: string;
  total_fen: number;
  item_count: number;
  created_at: string;
}

const STAGE_TAG_MAP: Record<string, { color: string; label: string }> = {
  first_order: { color: 'blue', label: '首单' },
  second_order: { color: 'cyan', label: '二单' },
  active: { color: 'green', label: '活跃' },
  silent: { color: 'orange', label: '沉默' },
  lapsed: { color: 'red', label: '流失' },
  reactivated: { color: 'purple', label: '已激活' },
};

const PRIORITY_COLORS: Record<string, string> = {
  critical: 'red', high: 'orange', medium: 'blue', low: 'default',
};

const EXEC_STATE_COLORS: Record<string, string> = {
  sent: 'blue', delivered: 'cyan', opened: 'green', clicked: 'green',
  bounced: 'red', failed: 'red', pending: 'default',
};

// ---- P1 标签颜色映射 ----
const PSYCH_DISTANCE_TAG: Record<string, { color: string; label: string }> = {
  near: { color: 'green', label: '亲近' },
  habit_break: { color: 'blue', label: '习惯中断' },
  fading: { color: 'orange', label: '渐远' },
  abstracted: { color: 'red', label: '疏离' },
  lost: { color: 'default', label: '失联' },
};

const SUPER_USER_TAG: Record<string, { color: string; label: string }> = {
  potential: { color: 'blue', label: '潜在超级用户' },
  active: { color: 'gold', label: '超级用户' },
  advocate: { color: 'purple', label: '品牌大使' },
};

const MILESTONE_LABELS: Record<string, string> = {
  newcomer: '新客', regular: '常客', loyal: '忠诚客', vip: 'VIP', legend: '传奇',
};

const REFERRAL_TAG: Record<string, { color: string; label: string }> = {
  birthday_organizer: { color: 'magenta', label: '生日组织者' },
  family_host: { color: 'volcano', label: '家庭聚餐达人' },
  corporate_host: { color: 'geekblue', label: '企业宴请' },
  super_referrer: { color: 'gold', label: '超级推荐者' },
};

// ---- 组件 ----
export function Customer360Page() {
  const { customerId } = useParams<{ customerId: string }>();
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [customer, setCustomer] = useState<CustomerDetail | null>(null);
  const [growthProfile, setGrowthProfile] = useState<GrowthProfile | null>(null);
  const [touches, setTouches] = useState<TouchExecution[]>([]);
  const [suggestions, setSuggestions] = useState<AgentSuggestion[]>([]);
  const [repairCases, setRepairCases] = useState<ServiceRepairCase[]>([]);

  // 发起旅程 Modal
  const [journeyModalOpen, setJourneyModalOpen] = useState(false);
  const [journeyTemplates, setJourneyTemplates] = useState<JourneyTemplate[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | undefined>();
  const [journeySubmitting, setJourneySubmitting] = useState(false);

  // 交给Agent Modal
  const [agentModalOpen, setAgentModalOpen] = useState(false);
  const [agentSuggestionType, setAgentSuggestionType] = useState<string>('reactivation');
  const [agentSubmitting, setAgentSubmitting] = useState(false);

  const fetchAll = useCallback(async () => {
    if (!customerId) return;
    setLoading(true);
    try {
      const [custResp, profileResp, touchResp, suggResp, repairResp] = await Promise.allSettled([
        txFetch<CustomerDetail>(`/api/v1/member/customers/${customerId}`),
        txFetch<GrowthProfile>(`/api/v1/growth/customers/${customerId}/profile`),
        txFetch<{ items: TouchExecution[] }>(`/api/v1/growth/touch-executions?customer_id=${customerId}`),
        txFetch<{ items: AgentSuggestion[] }>(`/api/v1/growth/agent-suggestions?customer_id=${customerId}`),
        txFetch<{ items: ServiceRepairCase[] }>(`/api/v1/growth/service-repair-cases?customer_id=${customerId}`),
      ]);
      if (custResp.status === 'fulfilled' && custResp.value.data) setCustomer(custResp.value.data);
      if (profileResp.status === 'fulfilled' && profileResp.value.data) setGrowthProfile(profileResp.value.data);
      if (touchResp.status === 'fulfilled' && touchResp.value.data) setTouches(touchResp.value.data.items);
      if (suggResp.status === 'fulfilled' && suggResp.value.data) setSuggestions(suggResp.value.data.items);
      if (repairResp.status === 'fulfilled' && repairResp.value.data) setRepairCases(repairResp.value.data.items);
    } catch (err) {
      console.error('Customer360 fetch error', err);
    } finally {
      setLoading(false);
    }
  }, [customerId]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  // 打开"发起旅程"Modal时加载模板
  const handleOpenJourneyModal = useCallback(async () => {
    setJourneyModalOpen(true);
    try {
      const resp = await txFetch<{ items: JourneyTemplate[] }>('/api/v1/growth/journey-templates?is_active=true');
      if (resp.data) setJourneyTemplates(resp.data.items);
    } catch (err) {
      console.error('fetch journey templates error', err);
    }
  }, []);

  const handleCreateJourney = useCallback(async () => {
    if (!customerId || !selectedTemplateId) return;
    setJourneySubmitting(true);
    try {
      await txFetch('/api/v1/growth/journey-enrollments', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          customer_id: customerId,
          journey_template_id: selectedTemplateId,
          enrollment_source: 'manual',
        }),
      });
      message.success('旅程已创建');
      setJourneyModalOpen(false);
      setSelectedTemplateId(undefined);
    } catch (err) {
      console.error('create journey error', err);
      message.error('旅程创建失败');
    } finally {
      setJourneySubmitting(false);
    }
  }, [customerId, selectedTemplateId]);

  const handleCreateAgentSuggestion = useCallback(async () => {
    if (!customerId) return;
    setAgentSubmitting(true);
    try {
      await txFetch('/api/v1/growth/agent-suggestions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          customer_id: customerId,
          suggestion_type: agentSuggestionType,
          priority: 'medium',
          explanation_summary: '手动触发',
          created_by_agent: 'manual',
        }),
      });
      message.success('Agent建议已生成');
      setAgentModalOpen(false);
      navigate('/hq/growth/agent-workbench');
    } catch (err) {
      console.error('create agent suggestion error', err);
      message.error('Agent建议创建失败');
    } finally {
      setAgentSubmitting(false);
    }
  }, [customerId, agentSuggestionType, navigate]);

  const chartOption = useMemo(() => {
    if (!customer?.spend_trend) return {};
    return {
      tooltip: { trigger: 'axis' as const },
      grid: { left: 50, right: 20, top: 20, bottom: 30 },
      xAxis: {
        type: 'category' as const,
        data: customer.spend_trend.map((d) => d.month),
        axisLabel: { color: TEXT_SECONDARY },
        axisLine: { lineStyle: { color: BORDER } },
      },
      yAxis: {
        type: 'value' as const,
        axisLabel: { color: TEXT_SECONDARY, formatter: (v: number) => `¥${(v / 100).toFixed(0)}` },
        splitLine: { lineStyle: { color: BORDER, type: 'dashed' as const } },
      },
      series: [{
        type: 'line',
        data: customer.spend_trend.map((d) => d.amount_fen),
        smooth: true,
        lineStyle: { color: BRAND_ORANGE },
        itemStyle: { color: BRAND_ORANGE },
        areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [
          { offset: 0, color: 'rgba(255,107,53,0.3)' },
          { offset: 1, color: 'rgba(255,107,53,0.02)' },
        ]}},
      }],
    };
  }, [customer]);

  // 经营行动时间轴：合并所有事件
  const timelineEvents = useMemo(() => {
    const events: { time: string; label: string; color: string }[] = [];

    // 首单时间
    if (growthProfile?.first_order_at) {
      events.push({ time: growthProfile.first_order_at, label: '\uD83D\uDED2 首单完成', color: SUCCESS_GREEN });
    }
    // 二访时间
    if (growthProfile?.second_order_at) {
      events.push({ time: growthProfile.second_order_at, label: '\uD83D\uDD04 二次到店', color: INFO_BLUE });
    }
    // 投诉记录
    repairCases.forEach((rc) => {
      events.push({ time: rc.created_at, label: `\u26A0\uFE0F 投诉: ${rc.summary || '无摘要'}`, color: DANGER_RED });
      if (rc.recovered_at) {
        events.push({ time: rc.recovered_at, label: '\u2705 修复完成', color: SUCCESS_GREEN });
      }
    });
    // 触达记录
    touches.forEach((t) => {
      events.push({ time: t.created_at, label: `\uD83D\uDCE8 触达: ${t.channel} (${t.mechanism_type || '通用'})`, color: INFO_BLUE });
      if (t.attributed_order_id) {
        events.push({ time: t.updated_at || t.created_at, label: '\uD83D\uDCB0 归因回店', color: SUCCESS_GREEN });
      }
    });
    // Agent建议
    suggestions.forEach((s) => {
      events.push({ time: s.created_at, label: `\uD83E\uDD16 Agent建议: ${s.suggestion_type}`, color: WARNING_ORANGE });
    });

    // 按时间正序排列
    events.sort((a, b) => new Date(a.time).getTime() - new Date(b.time).getTime());
    return events;
  }, [growthProfile, repairCases, touches, suggestions]);

  // 选中模板的详情
  const selectedTemplate = useMemo(
    () => journeyTemplates.find((t) => t.id === selectedTemplateId),
    [journeyTemplates, selectedTemplateId],
  );

  if (loading) {
    return (
      <div style={{ padding: 24, background: PAGE_BG, minHeight: '100vh', display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
        <Spin size="large" />
      </div>
    );
  }

  const cust = customer;

  return (
    <div style={{ padding: 24, background: PAGE_BG, minHeight: '100vh' }}>
      {/* 返回 + 标题 */}
      <Space style={{ marginBottom: 16 }}>
        <Button
          icon={<ArrowLeftOutlined />}
          onClick={() => navigate('/hq/growth/customers')}
          style={{ borderColor: BORDER, color: TEXT_SECONDARY }}
        />
        <h2 style={{ color: TEXT_PRIMARY, margin: 0 }}>客户360 — {cust?.display_name || '未知'}</h2>
      </Space>

      {/* 顶部概览卡片 */}
      <Card style={{ background: CARD_BG, border: `1px solid ${BORDER}`, marginBottom: 16 }}>
        <Row align="middle" gutter={24}>
          <Col flex="80px">
            <div style={{
              width: 64, height: 64, borderRadius: '50%', background: BRAND_ORANGE,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 28, color: '#fff', fontWeight: 700,
            }}>
              {(cust?.display_name || '?')[0]}
            </div>
          </Col>
          <Col flex="auto">
            <div style={{ color: TEXT_PRIMARY, fontSize: 18, fontWeight: 600 }}>
              {cust?.display_name || '匿名客户'}
              {cust?.level && <Tag color="gold" style={{ marginLeft: 8 }}>{cust.level}</Tag>}
              {growthProfile?.repurchase_stage && (
                <Tag color={STAGE_TAG_MAP[growthProfile.repurchase_stage]?.color || 'default'} style={{ marginLeft: 4 }}>
                  {STAGE_TAG_MAP[growthProfile.repurchase_stage]?.label || growthProfile.repurchase_stage}
                </Tag>
              )}
              {cust?.rfm_tag && <Tag color="purple" style={{ marginLeft: 4 }}>{cust.rfm_tag}</Tag>}
            </div>
            {/* P1 标签行 */}
            <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 4, alignItems: 'center' }}>
              {growthProfile?.psych_distance_level && PSYCH_DISTANCE_TAG[growthProfile.psych_distance_level] && (
                <Tag icon={<HeartOutlined />} color={PSYCH_DISTANCE_TAG[growthProfile.psych_distance_level].color}>
                  {PSYCH_DISTANCE_TAG[growthProfile.psych_distance_level].label}
                </Tag>
              )}
              {growthProfile?.super_user_level && SUPER_USER_TAG[growthProfile.super_user_level] && (
                <Tag icon={<CrownOutlined />} color={SUPER_USER_TAG[growthProfile.super_user_level].color}>
                  {SUPER_USER_TAG[growthProfile.super_user_level].label}
                </Tag>
              )}
              {growthProfile?.growth_milestone_stage && growthProfile.growth_milestone_stage !== 'newcomer' && (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  <Tag icon={<TrophyOutlined />} color="cyan">
                    {MILESTONE_LABELS[growthProfile.growth_milestone_stage] || growthProfile.growth_milestone_stage}
                  </Tag>
                  {growthProfile.growth_milestone_progress != null && growthProfile.growth_milestone_next && (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, color: TEXT_SECONDARY }}>
                      <Progress
                        percent={growthProfile.growth_milestone_progress}
                        size="small"
                        style={{ width: 80, margin: 0 }}
                        strokeColor={BRAND_ORANGE}
                        showInfo={false}
                      />
                      <span>{growthProfile.growth_milestone_progress}% &rarr; {MILESTONE_LABELS[growthProfile.growth_milestone_next] || growthProfile.growth_milestone_next}</span>
                    </span>
                  )}
                </span>
              )}
              {growthProfile?.referral_scenario && growthProfile.referral_scenario !== 'none' && REFERRAL_TAG[growthProfile.referral_scenario] && (
                <Tag icon={<ShareAltOutlined />} color={REFERRAL_TAG[growthProfile.referral_scenario].color}>
                  {REFERRAL_TAG[growthProfile.referral_scenario].label}
                </Tag>
              )}
            </div>
            <Space style={{ marginTop: 8, color: TEXT_SECONDARY, fontSize: 13 }}>
              {cust?.primary_phone && <span><PhoneOutlined /> {cust.primary_phone}</span>}
              <span>累计消费 ¥{((cust?.total_spend_fen || 0) / 100).toFixed(0)}</span>
              <span>订单 {cust?.order_count || 0} 笔</span>
              <span>客单价 ¥{((cust?.avg_order_fen || 0) / 100).toFixed(0)}</span>
            </Space>
          </Col>
          <Col>
            <Space>
              <Button type="primary" icon={<RocketOutlined />} style={{ background: BRAND_ORANGE, borderColor: BRAND_ORANGE }} onClick={handleOpenJourneyModal}>
                发起旅程
              </Button>
              <Button icon={<RobotOutlined />} style={{ borderColor: INFO_BLUE, color: INFO_BLUE }} onClick={() => setAgentModalOpen(true)}>
                交给Agent
              </Button>
              <Button icon={<StarOutlined />} style={{ borderColor: WARNING_ORANGE, color: WARNING_ORANGE }}>
                加重点跟进
              </Button>
            </Space>
          </Col>
        </Row>
      </Card>

      <Row gutter={16}>
        {/* 左上: 消费趋势 + 最近订单 */}
        <Col span={12}>
          <Card
            title={<span style={{ color: TEXT_PRIMARY }}>消费趋势</span>}
            style={{ background: CARD_BG, border: `1px solid ${BORDER}`, marginBottom: 16 }}
            styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
          >
            {cust?.spend_trend && cust.spend_trend.length > 0 ? (
              <ReactEChartsCore echarts={echarts} option={chartOption} style={{ height: 220 }} />
            ) : (
              <div style={{ textAlign: 'center', padding: 40, color: TEXT_SECONDARY }}>暂无消费数据</div>
            )}
          </Card>

          <Card
            title={<span style={{ color: TEXT_PRIMARY }}>最近订单</span>}
            style={{ background: CARD_BG, border: `1px solid ${BORDER}`, marginBottom: 16 }}
            styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
            bodyStyle={{ padding: 0 }}
          >
            <Table
              dataSource={cust?.recent_orders || []}
              rowKey="order_id"
              size="small"
              pagination={false}
              columns={[
                { title: '时间', dataIndex: 'created_at', width: 110,
                  render: (v: string) => <span style={{ color: TEXT_SECONDARY }}>{v?.slice(0, 10)}</span> },
                { title: '门店', dataIndex: 'store_name', width: 120,
                  render: (v: string) => <span style={{ color: TEXT_PRIMARY }}>{v}</span> },
                { title: '金额', dataIndex: 'total_fen', width: 90,
                  render: (v: number) => <span style={{ color: BRAND_ORANGE }}>¥{(v / 100).toFixed(0)}</span> },
                { title: '菜品数', dataIndex: 'item_count', width: 70 },
              ]}
            />
          </Card>
        </Col>

        {/* 右上: Agent推荐 + 标签 */}
        <Col span={12}>
          <Card
            title={<span style={{ color: TEXT_PRIMARY }}><RobotOutlined style={{ marginRight: 6 }} />Agent推荐</span>}
            style={{ background: CARD_BG, border: `1px solid ${BORDER}`, marginBottom: 16 }}
            styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
          >
            {suggestions.length === 0 ? (
              <div style={{ textAlign: 'center', padding: 40, color: TEXT_SECONDARY }}>暂无Agent建议</div>
            ) : (
              suggestions.slice(0, 3).map((s) => (
                <div
                  key={s.id}
                  style={{
                    padding: '10px 12px', borderRadius: 6, marginBottom: 8,
                    border: `1px solid ${BORDER}`, background: 'rgba(255,107,53,0.05)',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                    <Space size={4}>
                      <Tag color={PRIORITY_COLORS[s.priority] || 'default'}>{s.priority}</Tag>
                      <Tag>{s.suggestion_type}</Tag>
                    </Space>
                    <span style={{ fontSize: 11, color: TEXT_SECONDARY }}>{s.created_at?.slice(0, 10)}</span>
                  </div>
                  <div style={{ color: TEXT_PRIMARY, fontSize: 13 }}>{s.explanation_summary}</div>
                  <Space style={{ marginTop: 6 }} size={4}>
                    {s.mechanism_type && <Tag color="cyan">{s.mechanism_type}</Tag>}
                    {s.recommended_channel && <Tag color="blue">{s.recommended_channel}</Tag>}
                    {s.recommended_offer_type && <Tag color="orange">{s.recommended_offer_type}</Tag>}
                  </Space>
                </div>
              ))
            )}
          </Card>

          <Card
            title={<span style={{ color: TEXT_PRIMARY }}>客户标签</span>}
            style={{ background: CARD_BG, border: `1px solid ${BORDER}`, marginBottom: 16 }}
            styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
          >
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {cust?.tags && cust.tags.length > 0 ? (
                cust.tags.map((t, i) => <Tag key={i} color="blue">{t}</Tag>)
              ) : (
                <span style={{ color: TEXT_SECONDARY }}>暂无标签</span>
              )}
              {growthProfile?.has_active_owned_benefit && (
                <Tag color="gold">有权益: {growthProfile.owned_benefit_type}</Tag>
              )}
              {growthProfile?.service_repair_status && growthProfile.service_repair_status !== 'none' && (
                <Tag color="red">修复中: {growthProfile.service_repair_status}</Tag>
              )}
              {growthProfile?.growth_opt_out && (
                <Tag color="default">已退订</Tag>
              )}
            </div>
          </Card>
        </Col>
      </Row>

      <Row gutter={16}>
        {/* 左下: 触达历史 */}
        <Col span={12}>
          <Card
            title={<span style={{ color: TEXT_PRIMARY }}>触达历史</span>}
            style={{ background: CARD_BG, border: `1px solid ${BORDER}`, marginBottom: 16 }}
            styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
            bodyStyle={{ padding: 0 }}
          >
            <Table
              dataSource={touches.slice(0, 10)}
              rowKey="id"
              size="small"
              pagination={false}
              columns={[
                { title: '时间', dataIndex: 'created_at', width: 110,
                  render: (v: string) => <span style={{ color: TEXT_SECONDARY }}>{v?.slice(0, 10)}</span> },
                { title: '渠道', dataIndex: 'channel', width: 80,
                  render: (v: string) => <Tag>{v}</Tag> },
                { title: '机制', dataIndex: 'mechanism_type', width: 90,
                  render: (v: string | null) => v ? <Tag color="cyan">{v}</Tag> : '-' },
                { title: '状态', dataIndex: 'execution_state', width: 80,
                  render: (v: string) => <Tag color={EXEC_STATE_COLORS[v] || 'default'}>{v}</Tag> },
                { title: '归因收入', dataIndex: 'attributed_revenue_fen', width: 90,
                  render: (v: number | null) => v ? (
                    <span style={{ color: SUCCESS_GREEN }}>¥{(v / 100).toFixed(0)}</span>
                  ) : '-' },
              ]}
            />
          </Card>
        </Col>

        {/* 右下: 增长档案 */}
        <Col span={12}>
          <Card
            title={<span style={{ color: TEXT_PRIMARY }}>增长档案</span>}
            style={{ background: CARD_BG, border: `1px solid ${BORDER}`, marginBottom: 16 }}
            styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
          >
            {growthProfile ? (
              <Descriptions
                column={2}
                size="small"
                labelStyle={{ color: TEXT_SECONDARY, fontSize: 12 }}
                contentStyle={{ color: TEXT_PRIMARY, fontSize: 12 }}
              >
                <Descriptions.Item label="复购阶段">
                  <Tag color={STAGE_TAG_MAP[growthProfile.repurchase_stage]?.color || 'default'}>
                    {STAGE_TAG_MAP[growthProfile.repurchase_stage]?.label || growthProfile.repurchase_stage}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="激活优先级">
                  <Tag color={PRIORITY_COLORS[growthProfile.reactivation_priority] || 'default'}>
                    {growthProfile.reactivation_priority}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="首单时间">{growthProfile.first_order_at?.slice(0, 10) || '-'}</Descriptions.Item>
                <Descriptions.Item label="二单时间">{growthProfile.second_order_at?.slice(0, 10) || '-'}</Descriptions.Item>
                <Descriptions.Item label="末单时间">{growthProfile.last_order_at?.slice(0, 10) || '-'}</Descriptions.Item>
                <Descriptions.Item label="最近触达">
                  {growthProfile.last_growth_touch_at?.slice(0, 10) || '未触达'}
                  {growthProfile.last_growth_touch_channel && (
                    <Tag style={{ marginLeft: 4 }}>{growthProfile.last_growth_touch_channel}</Tag>
                  )}
                </Descriptions.Item>
                <Descriptions.Item label="修复状态">{growthProfile.service_repair_status}</Descriptions.Item>
                <Descriptions.Item label="激活原因">{growthProfile.reactivation_reason || '-'}</Descriptions.Item>
              </Descriptions>
            ) : (
              <div style={{ textAlign: 'center', padding: 40, color: TEXT_SECONDARY }}>暂无增长档案</div>
            )}
          </Card>
        </Col>
      </Row>

      {/* 🧠 AI 洞察 Tab 区域 */}
      <Card
        title={
          <Tabs
            defaultActiveKey="timeline"
            items={[
              { key: 'timeline', label: '经营行动时间轴' },
              { key: 'ai-insight', label: '🧠 AI 洞察' },
            ] as TabsProps['items']}
            onChange={() => {}}
            style={{ marginBottom: -16 }}
          />
        }
        style={{ background: CARD_BG, border: `1px solid ${BORDER}`, marginBottom: 16 }}
        styles={{ header: { borderBottom: `1px solid ${BORDER}`, padding: '0 24px' } }}
      >
        <Row gutter={16}>
          <Col span={14}>
            <Card
              title={<span style={{ color: TEXT_PRIMARY }}>AI 消费预测</span>}
              style={{ background: 'rgba(255,107,53,0.04)', border: `1px solid ${BORDER}` }}
              styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
            >
              <Statistic
                title={<span style={{ color: TEXT_SECONDARY }}>预测本月消费</span>}
                value={2840}
                prefix="¥"
                valueStyle={{ color: SUCCESS_GREEN, fontWeight: 700 }}
              />
              <Statistic
                title={<span style={{ color: TEXT_SECONDARY }}>预测到访次数</span>}
                value={3}
                suffix="次"
                style={{ marginTop: 16 }}
                valueStyle={{ color: INFO_BLUE, fontWeight: 700 }}
              />
              <Progress
                percent={72}
                strokeColor={BRAND_ORANGE}
                style={{ marginTop: 16 }}
              />
              <div style={{ color: TEXT_SECONDARY, fontSize: 12, marginTop: 6 }}>
                预计 2026-04-12 到访，置信度 72%
              </div>
            </Card>
          </Col>
          <Col span={10}>
            <Card
              title={<span style={{ color: TEXT_PRIMARY }}>个性化服务建议</span>}
              style={{ background: 'rgba(255,107,53,0.04)', border: `1px solid ${BORDER}` }}
              styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
            >
              <List
                dataSource={[
                  '偏好安静包厢，提前预留 VIP 包厢',
                  '对海鲜过敏，点单时自动提示',
                  '钻石会员，迎宾升级专属服务',
                ]}
                renderItem={(item) => (
                  <List.Item style={{ padding: '8px 0' }}>
                    <Space>
                      <BulbOutlined style={{ color: BRAND_ORANGE }} />
                      <span style={{ color: TEXT_PRIMARY, fontSize: 13 }}>{item}</span>
                    </Space>
                  </List.Item>
                )}
              />
            </Card>
          </Col>
        </Row>
      </Card>

      {/* 底部: 经营行动时间轴 */}
      <Card
        title={<span style={{ color: TEXT_PRIMARY }}>经营行动时间轴</span>}
        style={{ background: CARD_BG, border: `1px solid ${BORDER}` }}
        styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
      >
        {timelineEvents.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 40, color: TEXT_SECONDARY }}>暂无行动记录</div>
        ) : (
          <Timeline
            items={timelineEvents.map((evt) => ({
              color: evt.color,
              children: (
                <div>
                  <div style={{ color: TEXT_PRIMARY, fontSize: 13 }}>{evt.label}</div>
                  <div style={{ color: TEXT_SECONDARY, fontSize: 11 }}>{evt.time?.slice(0, 16).replace('T', ' ')}</div>
                </div>
              ),
            }))}
          />
        )}
      </Card>

      {/* 发起旅程 Modal */}
      <Modal
        title={`为 ${cust?.display_name || '客户'} 发起旅程`}
        open={journeyModalOpen}
        onCancel={() => { setJourneyModalOpen(false); setSelectedTemplateId(undefined); }}
        onOk={handleCreateJourney}
        okText="确认"
        cancelText="取消"
        confirmLoading={journeySubmitting}
        okButtonProps={{ disabled: !selectedTemplateId }}
      >
        <div style={{ marginBottom: 16 }}>
          <div style={{ marginBottom: 8, fontWeight: 500 }}>选择旅程模板</div>
          <Select
            placeholder="请选择旅程模板"
            style={{ width: '100%' }}
            value={selectedTemplateId}
            onChange={(v) => setSelectedTemplateId(v)}
            options={journeyTemplates.map((t) => ({
              value: t.id,
              label: `${t.name} (${t.journey_type})`,
            }))}
          />
        </div>
        {selectedTemplate && (
          <div style={{ padding: 12, background: '#f5f5f5', borderRadius: 6 }}>
            <div style={{ marginBottom: 4 }}>
              <span style={{ fontWeight: 500 }}>机制族：</span>
              <Tag color="blue">{selectedTemplate.mechanism_family || '-'}</Tag>
            </div>
            <div>
              <span style={{ fontWeight: 500 }}>旅程类型：</span>
              <Tag color="cyan">{selectedTemplate.journey_type}</Tag>
            </div>
            {selectedTemplate.description && (
              <div style={{ marginTop: 8, color: '#666', fontSize: 12 }}>{selectedTemplate.description}</div>
            )}
          </div>
        )}
      </Modal>

      {/* 交给Agent Modal */}
      <Modal
        title={`为 ${cust?.display_name || '客户'} 生成Agent建议`}
        open={agentModalOpen}
        onCancel={() => setAgentModalOpen(false)}
        onOk={handleCreateAgentSuggestion}
        okText="生成建议"
        cancelText="取消"
        confirmLoading={agentSubmitting}
      >
        <div style={{ marginBottom: 8, fontWeight: 500 }}>选择目标</div>
        <Radio.Group
          value={agentSuggestionType}
          onChange={(e) => setAgentSuggestionType(e.target.value)}
          style={{ display: 'flex', flexDirection: 'column', gap: 12 }}
        >
          <Radio value="reactivation">复购召回</Radio>
          <Radio value="stored_value">储值续航</Radio>
          <Radio value="booking">订台推荐</Radio>
          <Radio value="service_repair">服务修复</Radio>
        </Radio.Group>
      </Modal>
    </div>
  );
}
