/**
 * GrowthSegmentTagsPage — 增长标签中心
 * 路由: /hq/growth/segment-tags
 *
 * 区域1: 标签分布概览（3个饼图）
 * 区域2: P0预置规则模板（3张卡片）
 * 区域3: 标签字典（静态表格）
 */
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Table, Tag, Button, Space, Row, Col, Spin, message } from 'antd';
import { TagsOutlined, TeamOutlined, RocketOutlined, EyeOutlined } from '@ant-design/icons';
import {
  fetchSegmentPresets,
  fetchTagDistribution,
  fetchP1Distribution,
  type SegmentPreset,
  type TagDistribution,
  type P1Distribution,
} from '../../../api/growthHubApi';

// ---- 颜色常量（深色主题） ----
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

// ---- 饼图颜色 ----
const PIE_COLORS = ['#FF6B35', '#1890ff', '#52c41a', '#faad14', '#ff4d4f', '#722ed1', '#13c2c2', '#eb2f96'];

// ---- 优先级颜色映射 ----
const PRIORITY_COLORS: Record<string, string> = {
  critical: DANGER_RED,
  high: WARNING_ORANGE,
  medium: INFO_BLUE,
  low: SUCCESS_GREEN,
};

// ---- 标签字典（静态数据） ----
interface TagDictEntry {
  category: string;
  value: string;
  label: string;
  trigger: string;
  action: string;
}

const TAG_DICTIONARY: TagDictEntry[] = [
  // 复购阶段
  { category: '复购阶段', value: 'not_started', label: '未开始', trigger: '尚未产生任何订单', action: '新客激活' },
  { category: '复购阶段', value: 'first_order_done', label: '首单完成', trigger: '首笔订单支付成功', action: '首单转二访旅程' },
  { category: '复购阶段', value: 'second_order_done', label: '二单完成', trigger: '第二笔订单支付成功', action: '复购习惯养成旅程' },
  { category: '复购阶段', value: 'stable_repeat', label: '稳定复购', trigger: '累计3+笔订单且近60天内有消费', action: '忠诚度维护' },
  // 召回优先级
  { category: '召回优先级', value: 'none', label: '无需召回', trigger: '近30天内有到店', action: '无' },
  { category: '召回优先级', value: 'low', label: '低优先', trigger: '30-60天未到店', action: '轻触达提醒' },
  { category: '召回优先级', value: 'medium', label: '中优先', trigger: '60-90天未到店', action: '关系唤醒旅程' },
  { category: '召回优先级', value: 'high', label: '高优先', trigger: '30天沉默或有权益将到期', action: '沉默召回旅程' },
  { category: '召回优先级', value: 'critical', label: '紧急', trigger: '90天+未到店或高价值客流失', action: '紧急召回旅程' },
  // 修复状态
  { category: '修复状态', value: 'none', label: '无投诉', trigger: '无投诉记录', action: '无' },
  { category: '修复状态', value: 'complaint_opened', label: '投诉处理中', trigger: '收到客户投诉', action: '投诉处理流程' },
  { category: '修复状态', value: 'complaint_closed_pending_repair', label: '投诉关闭待修复', trigger: '投诉结案但未修复', action: '服务修复旅程' },
  { category: '修复状态', value: 'repair_in_progress', label: '修复进行中', trigger: '已启动修复旅程', action: '持续跟进' },
  { category: '修复状态', value: 'recovered', label: '已修复', trigger: '修复成功，客户回访', action: '转入正常运营' },
  // P1 标签
  { category: '心理距离', value: 'near', label: '亲近', trigger: '近期到店且互动良好', action: '维护关系' },
  { category: '心理距离', value: 'habit_break', label: '习惯中断', trigger: '消费习惯出现断裂信号', action: '轻触达提醒' },
  { category: '心理距离', value: 'fading', label: '渐远', trigger: '心理距离开始变远，还有关系记忆', action: '心理距离修复旅程' },
  { category: '心理距离', value: 'abstracted', label: '疏离', trigger: '心理距离已远，品牌印象模糊', action: '轻触达修复旅程' },
  { category: '心理距离', value: 'lost', label: '失联', trigger: '完全失去联系', action: '放弃或极轻触达' },
  { category: '超级用户', value: 'none', label: '普通', trigger: '未达到超级用户标准', action: '无' },
  { category: '超级用户', value: 'potential', label: '潜在', trigger: 'RFM高分但未激活', action: '培养激活' },
  { category: '超级用户', value: 'active', label: '活跃', trigger: '高频高额且有互动', action: '关系经营旅程' },
  { category: '超级用户', value: 'advocate', label: '品牌大使', trigger: '主动推荐且有裂变行为', action: '赋能推荐' },
  { category: '成长里程碑', value: 'newcomer', label: '新客', trigger: '首次到店', action: '首单转二访' },
  { category: '成长里程碑', value: 'regular', label: '常客', trigger: '累计3+笔订单', action: '里程碑庆祝' },
  { category: '成长里程碑', value: 'loyal', label: '忠诚客', trigger: '累计10+笔订单', action: '里程碑庆祝' },
  { category: '成长里程碑', value: 'vip', label: 'VIP', trigger: '累计消费达VIP阈值', action: '里程碑庆祝' },
  { category: '成长里程碑', value: 'legend', label: '传奇', trigger: '累计消费达传奇阈值', action: '里程碑庆祝' },
  { category: '裂变场景', value: 'none', label: '无', trigger: '无裂变行为', action: '无' },
  { category: '裂变场景', value: 'birthday_organizer', label: '生日组织者', trigger: '多次组织生日聚餐', action: '生日裂变旅程' },
  { category: '裂变场景', value: 'family_host', label: '家庭聚餐达人', trigger: '高频家庭聚餐', action: '家庭裂变旅程' },
  { category: '裂变场景', value: 'corporate_host', label: '企业宴请', trigger: '企业宴请场景', action: '企业裂变旅程' },
  { category: '裂变场景', value: 'super_referrer', label: '超级推荐者', trigger: '推荐多位新客', action: '推荐赋能旅程' },
];

const dictColumns = [
  { title: '标签类型', dataIndex: 'category', key: 'category',
    render: (v: string, _: TagDictEntry, idx: number) => {
      const prev = TAG_DICTIONARY[idx - 1];
      if (prev && prev.category === v) return { children: null, props: { rowSpan: 0 } };
      const span = TAG_DICTIONARY.filter((r) => r.category === v).length;
      return { children: <span style={{ fontWeight: 600, color: TEXT_PRIMARY }}>{v}</span>, props: { rowSpan: span } };
    },
  },
  { title: '标签值', dataIndex: 'value', key: 'value',
    render: (v: string) => <code style={{ fontSize: 12, color: '#87ceeb', background: 'rgba(24,144,255,0.1)', padding: '1px 6px', borderRadius: 4 }}>{v}</code>,
  },
  { title: '中文名称', dataIndex: 'label', key: 'label' },
  { title: '触发条件', dataIndex: 'trigger', key: 'trigger', render: (v: string) => <span style={{ color: TEXT_SECONDARY }}>{v}</span> },
  { title: '推荐动作', dataIndex: 'action', key: 'action', render: (v: string) => <Tag color="blue">{v}</Tag> },
];

// ---- 简易饼图组件（SVG） ----
function MiniPie({ data, title }: { data: { label: string; value: number }[]; title: string }) {
  const total = data.reduce((s, d) => s + d.value, 0);
  if (total === 0) {
    return (
      <div style={{ textAlign: 'center', padding: 20 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: TEXT_PRIMARY, marginBottom: 12 }}>{title}</div>
        <div style={{ color: TEXT_SECONDARY, fontSize: 13 }}>暂无数据</div>
      </div>
    );
  }

  let cumAngle = 0;
  const slices = data.map((d, i) => {
    const angle = (d.value / total) * 360;
    const startAngle = cumAngle;
    cumAngle += angle;
    return { ...d, startAngle, angle, color: PIE_COLORS[i % PIE_COLORS.length] };
  });

  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const cx = 80, cy = 80, r = 60;

  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: 14, fontWeight: 600, color: TEXT_PRIMARY, marginBottom: 8 }}>{title}</div>
      <svg width={160} height={160} viewBox="0 0 160 160">
        {slices.map((s, i) => {
          if (s.angle >= 359.99) {
            return <circle key={i} cx={cx} cy={cy} r={r} fill={s.color} />;
          }
          const x1 = cx + r * Math.cos(toRad(s.startAngle - 90));
          const y1 = cy + r * Math.sin(toRad(s.startAngle - 90));
          const x2 = cx + r * Math.cos(toRad(s.startAngle + s.angle - 90));
          const y2 = cy + r * Math.sin(toRad(s.startAngle + s.angle - 90));
          const large = s.angle > 180 ? 1 : 0;
          return (
            <path
              key={i}
              d={`M${cx},${cy} L${x1},${y1} A${r},${r} 0 ${large} 1 ${x2},${y2} Z`}
              fill={s.color}
            />
          );
        })}
        <circle cx={cx} cy={cy} r={30} fill={CARD_BG} />
        <text x={cx} y={cy + 5} textAnchor="middle" fill={TEXT_PRIMARY} fontSize={16} fontWeight={700}>
          {total}
        </text>
      </svg>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, justifyContent: 'center', marginTop: 4 }}>
        {slices.map((s, i) => (
          <span key={i} style={{ fontSize: 11, color: TEXT_SECONDARY, display: 'flex', alignItems: 'center', gap: 3 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: s.color, display: 'inline-block' }} />
            {s.label}: {s.value}
          </span>
        ))}
      </div>
    </div>
  );
}

// ---- 标签名映射 ----
const STAGE_LABELS: Record<string, string> = {
  not_started: '未开始', first_order_done: '首单完成', second_order_done: '二单完成', stable_repeat: '稳定复购',
};
const PRIORITY_LABELS: Record<string, string> = {
  none: '无需召回', low: '低', medium: '中', high: '高', critical: '紧急',
};
const REPAIR_LABELS: Record<string, string> = {
  complaint_opened: '投诉处理中', complaint_closed_pending_repair: '投诉关闭待修复',
  repair_in_progress: '修复进行中', recovered: '已修复',
};
const PSYCH_DISTANCE_LABELS: Record<string, string> = {
  near: '亲近', habit_break: '习惯中断', fading: '渐远', abstracted: '疏离', lost: '失联',
};
const SUPER_USER_LABELS: Record<string, string> = {
  none: '普通', potential: '潜在', active: '活跃', advocate: '品牌大使',
};
const MILESTONE_LABELS: Record<string, string> = {
  newcomer: '新客', regular: '常客', loyal: '忠诚客', vip: 'VIP', legend: '传奇',
};
const REFERRAL_LABELS: Record<string, string> = {
  none: '无', birthday_organizer: '生日组织者', family_host: '家庭聚餐达人',
  corporate_host: '企业宴请', super_referrer: '超级推荐者',
};

// ---- 主组件 ----
export function GrowthSegmentTagsPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [presets, setPresets] = useState<SegmentPreset[]>([]);
  const [distribution, setDistribution] = useState<TagDistribution | null>(null);
  const [p1Dist, setP1Dist] = useState<P1Distribution | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [presetsRes, distRes, p1Res] = await Promise.all([
          fetchSegmentPresets(),
          fetchTagDistribution(),
          fetchP1Distribution().catch(() => null),
        ]);
        if (cancelled) return;
        setPresets(presetsRes.presets);
        setDistribution(distRes);
        if (p1Res) setP1Dist(p1Res);
      } catch (e: unknown) {
        if (!cancelled) message.error('加载标签数据失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <div style={{ padding: 24, background: PAGE_BG, minHeight: '100vh', color: TEXT_PRIMARY }}>
      {/* 页头 */}
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 8 }}>
          <TagsOutlined style={{ color: BRAND_ORANGE }} />
          增长标签中心
        </h2>
        <div style={{ color: TEXT_SECONDARY, fontSize: 13, marginTop: 4 }}>
          可运营标签分布总览 / P0+P1规则模板 / 标签字典
        </div>
      </div>

      <Spin spinning={loading}>
        {/* 区域1: 标签分布概览 */}
        <Card
          title={<span style={{ color: TEXT_PRIMARY }}>标签分布概览</span>}
          style={{ background: CARD_BG, border: `1px solid ${BORDER}`, marginBottom: 24 }}
          styles={{ header: { background: CARD_BG, borderBottom: `1px solid ${BORDER}`, color: TEXT_PRIMARY }, body: { background: CARD_BG } }}
        >
          <Row gutter={24}>
            <Col span={8}>
              <MiniPie
                title="复购阶段分布"
                data={(distribution?.repurchase_stage || []).map((d) => ({
                  label: STAGE_LABELS[d.stage] || d.stage,
                  value: d.count,
                }))}
              />
            </Col>
            <Col span={8}>
              <MiniPie
                title="召回优先级分布"
                data={(distribution?.reactivation_priority || []).map((d) => ({
                  label: PRIORITY_LABELS[d.priority] || d.priority,
                  value: d.count,
                }))}
              />
            </Col>
            <Col span={8}>
              <MiniPie
                title="修复状态分布"
                data={(distribution?.service_repair_status || []).map((d) => ({
                  label: REPAIR_LABELS[d.status] || d.status,
                  value: d.count,
                }))}
              />
            </Col>
          </Row>
          {/* P1 标签分布 */}
          {p1Dist && (
            <Row gutter={24} style={{ marginTop: 24 }}>
              <Col span={6}>
                <MiniPie
                  title="心理距离分布"
                  data={(p1Dist.psych_distance || []).map((d) => ({
                    label: PSYCH_DISTANCE_LABELS[d.level] || d.level,
                    value: d.count,
                  }))}
                />
              </Col>
              <Col span={6}>
                <MiniPie
                  title="超级用户分布"
                  data={(p1Dist.super_user || []).map((d) => ({
                    label: SUPER_USER_LABELS[d.level] || d.level,
                    value: d.count,
                  }))}
                />
              </Col>
              <Col span={6}>
                <MiniPie
                  title="成长里程碑分布"
                  data={(p1Dist.milestones || []).map((d) => ({
                    label: MILESTONE_LABELS[d.stage] || d.stage,
                    value: d.count,
                  }))}
                />
              </Col>
              <Col span={6}>
                <MiniPie
                  title="裂变场景分布"
                  data={(p1Dist.referral || []).map((d) => ({
                    label: REFERRAL_LABELS[d.scenario] || d.scenario,
                    value: d.count,
                  }))}
                />
              </Col>
            </Row>
          )}
        </Card>

        {/* 区域2: P0预置规则模板 */}
        <Card
          title={<span style={{ color: TEXT_PRIMARY }}>P0 预置规则模板</span>}
          style={{ background: CARD_BG, border: `1px solid ${BORDER}`, marginBottom: 24 }}
          styles={{ header: { background: CARD_BG, borderBottom: `1px solid ${BORDER}`, color: TEXT_PRIMARY }, body: { background: CARD_BG } }}
        >
          <Row gutter={16}>
            {presets.map((p) => (
              <Col span={8} key={p.id}>
                <div style={{
                  background: PAGE_BG, border: `1px solid ${BORDER}`, borderRadius: 8, padding: 20,
                  display: 'flex', flexDirection: 'column', gap: 12, height: '100%',
                }}>
                  {/* 头部：名称 + 优先级 */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: 16, fontWeight: 700, color: TEXT_PRIMARY }}>{p.name}</span>
                    <Tag color={PRIORITY_COLORS[p.priority] || INFO_BLUE} style={{ margin: 0, fontWeight: 600 }}>
                      {p.priority === 'critical' ? '紧急' : p.priority === 'high' ? '高优' : p.priority}
                    </Tag>
                  </div>

                  {/* 描述 */}
                  <div style={{ color: TEXT_SECONDARY, fontSize: 13, lineHeight: 1.5 }}>{p.description}</div>

                  {/* 命中人数 */}
                  <div style={{ textAlign: 'center', padding: '8px 0' }}>
                    <div style={{ fontSize: 36, fontWeight: 700, color: BRAND_ORANGE }}>{p.matched_count.toLocaleString()}</div>
                    <div style={{ fontSize: 12, color: TEXT_SECONDARY }}>命中客户数</div>
                  </div>

                  {/* 推荐动作 */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: SUCCESS_GREEN }}>
                    <RocketOutlined />
                    {p.recommended_action}
                  </div>

                  {/* 操作按钮 */}
                  <Space style={{ marginTop: 'auto' }}>
                    <Button
                      size="small"
                      icon={<EyeOutlined />}
                      onClick={() => navigate(`/hq/growth/customers?filter=${p.id}`)}
                    >
                      查看客户
                    </Button>
                    <Button
                      size="small"
                      type="primary"
                      icon={<RocketOutlined />}
                      style={{ background: BRAND_ORANGE, borderColor: BRAND_ORANGE }}
                      onClick={() => navigate('/hq/growth/journey-templates')}
                    >
                      发起旅程
                    </Button>
                  </Space>
                </div>
              </Col>
            ))}
            {presets.length === 0 && !loading && (
              <Col span={24}>
                <div style={{ textAlign: 'center', padding: 40, color: TEXT_SECONDARY }}>暂无预置规则</div>
              </Col>
            )}
          </Row>
        </Card>

        {/* 区域3: 标签字典 */}
        <Card
          title={<span style={{ color: TEXT_PRIMARY }}>标签字典</span>}
          style={{ background: CARD_BG, border: `1px solid ${BORDER}` }}
          styles={{ header: { background: CARD_BG, borderBottom: `1px solid ${BORDER}`, color: TEXT_PRIMARY }, body: { background: CARD_BG, padding: 0 } }}
        >
          <Table
            dataSource={TAG_DICTIONARY}
            columns={dictColumns}
            rowKey={(r) => `${r.category}-${r.value}`}
            pagination={false}
            size="small"
            style={{ background: CARD_BG }}
          />
        </Card>
      </Spin>
    </div>
  );
}
