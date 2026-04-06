/**
 * Customer360Page — 客户360详情（单客经营中枢）
 * 路由: /hq/growth/customers/:customerId
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Card, Tag, Button, Space, Row, Col, Statistic, Table, Timeline, Spin, Descriptions, Progress, message,
} from 'antd';
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
import type { GrowthProfile, TouchExecution, AgentSuggestion } from '../../../api/growthHubApi';

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

  const fetchAll = useCallback(async () => {
    if (!customerId) return;
    setLoading(true);
    try {
      const [custResp, profileResp, touchResp, suggResp] = await Promise.allSettled([
        txFetch<CustomerDetail>(`/api/v1/member/customers/${customerId}`),
        txFetch<GrowthProfile>(`/api/v1/growth/customers/${customerId}/profile`),
        txFetch<{ items: TouchExecution[] }>(`/api/v1/growth/touch-executions?customer_id=${customerId}`),
        txFetch<{ items: AgentSuggestion[] }>(`/api/v1/growth/agent-suggestions?customer_id=${customerId}`),
      ]);
      if (custResp.status === 'fulfilled' && custResp.value.data) setCustomer(custResp.value.data);
      if (profileResp.status === 'fulfilled' && profileResp.value.data) setGrowthProfile(profileResp.value.data);
      if (touchResp.status === 'fulfilled' && touchResp.value.data) setTouches(touchResp.value.data.items);
      if (suggResp.status === 'fulfilled' && suggResp.value.data) setSuggestions(suggResp.value.data.items);
    } catch (err) {
      console.error('Customer360 fetch error', err);
    } finally {
      setLoading(false);
    }
  }, [customerId]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

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
              <Button type="primary" icon={<RocketOutlined />} style={{ background: BRAND_ORANGE, borderColor: BRAND_ORANGE }}>
                发起旅程
              </Button>
              <Button icon={<RobotOutlined />} style={{ borderColor: INFO_BLUE, color: INFO_BLUE }}>
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

      {/* 底部: 经营行动时间轴 */}
      <Card
        title={<span style={{ color: TEXT_PRIMARY }}>经营行动时间轴</span>}
        style={{ background: CARD_BG, border: `1px solid ${BORDER}` }}
        styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
      >
        {touches.length === 0 && suggestions.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 40, color: TEXT_SECONDARY }}>暂无行动记录</div>
        ) : (
          <Timeline
            items={[
              ...touches.slice(0, 5).map((t) => ({
                color: EXEC_STATE_COLORS[t.execution_state] === 'green' ? SUCCESS_GREEN :
                       EXEC_STATE_COLORS[t.execution_state] === 'red' ? DANGER_RED : INFO_BLUE,
                children: (
                  <div>
                    <div style={{ color: TEXT_PRIMARY, fontSize: 13 }}>
                      触达 [{t.channel}] {t.mechanism_type || '通用'} — {t.execution_state}
                    </div>
                    <div style={{ color: TEXT_SECONDARY, fontSize: 11 }}>{t.created_at?.slice(0, 16)}</div>
                  </div>
                ),
              })),
              ...suggestions.slice(0, 3).map((s) => ({
                color: WARNING_ORANGE,
                children: (
                  <div>
                    <div style={{ color: TEXT_PRIMARY, fontSize: 13 }}>
                      Agent建议: {s.explanation_summary.slice(0, 50)}
                    </div>
                    <div style={{ color: TEXT_SECONDARY, fontSize: 11 }}>{s.created_at?.slice(0, 16)}</div>
                  </div>
                ),
              })),
            ]}
          />
        )}
      </Card>
    </div>
  );
}
