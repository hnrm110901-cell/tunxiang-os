/**
 * GrowthOfferPacksPage — 增长权益策略台
 * 路由: /hq/growth/offer-packs
 *
 * 缺口1: 权益包展示（卡片列表 + 筛选）
 * 缺口2: 权益-旅程关联展示
 * 缺口3: 毛利守护预算面板
 */
import { useState, useEffect, useMemo } from 'react';
import {
  Card, Row, Col, Tag, Select, Spin, Statistic, Space, Collapse, message,
} from 'antd';
import {
  GiftOutlined, DollarOutlined, LinkOutlined, SafetyCertificateOutlined,
} from '@ant-design/icons';
import {
  fetchOfferPacks,
  fetchJourneyTemplates,
  type OfferPack,
  type JourneyTemplate,
} from '../../../api/growthHubApi';

// ---- 颜色常量（深色主题） ----
const PAGE_BG = '#0d1e28';
const CARD_BG = '#142833';
const BORDER = '#1e3a4a';
const TEXT_PRIMARY = '#e8e8e8';
const TEXT_SECONDARY = '#8899a6';
const BRAND_ORANGE = '#FF6B35';
const SUCCESS_GREEN = '#52c41a';
const DANGER_RED = '#ff4d4f';

// ---- pack_type 中文映射 ----
const PACK_TYPE_LABELS: Record<string, string> = {
  first_to_second: '首单二访',
  reactivation: '召回',
  service_repair: '服务修复',
  super_user: '超级用户',
  milestone: '里程碑',
  referral: '裂变',
};

const PACK_TYPE_COLORS: Record<string, string> = {
  first_to_second: 'blue',
  reactivation: 'orange',
  service_repair: 'red',
  super_user: 'purple',
  milestone: 'cyan',
  referral: 'green',
};

// ---- item type icon ----
const ITEM_TYPE_ICONS: Record<string, string> = {
  experience: '🎁',
  privilege: '👑',
  surprise: '🎲',
  reminder: '🔔',
  gift: '🎀',
  convenience: '🚀',
  refund: '💰',
  offset: '🏷️',
  upgrade: '⬆️',
  reward: '🏆',
};

// ---- 主组件 ----
export function GrowthOfferPacksPage() {
  const [loading, setLoading] = useState(true);
  const [packs, setPacks] = useState<OfferPack[]>([]);
  const [templates, setTemplates] = useState<JourneyTemplate[]>([]);
  const [filterPackType, setFilterPackType] = useState<string | undefined>(undefined);
  const [filterMechanism, setFilterMechanism] = useState<string | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [packsRes, templatesRes] = await Promise.all([
          fetchOfferPacks(),
          fetchJourneyTemplates({ is_active: 'true' }).catch(() => ({ items: [], total: 0 })),
        ]);
        if (cancelled) return;
        setPacks(packsRes.items);
        setTemplates(templatesRes.items);
      } catch {
        if (!cancelled) message.error('加载权益包数据失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // 筛选
  const filteredPacks = useMemo(() => {
    let items = packs;
    if (filterPackType) items = items.filter((p) => p.pack_type === filterPackType);
    if (filterMechanism) items = items.filter((p) => p.mechanism_type === filterMechanism);
    return items;
  }, [packs, filterPackType, filterMechanism]);

  // 获取所有 mechanism_type 去重
  const mechanismTypes = useMemo(() =>
    [...new Set(packs.map((p) => p.mechanism_type))],
  [packs]);

  // 缺口2: 根据 mechanism_type 匹配关联旅程
  const getLinkedJourneys = (pack: OfferPack): JourneyTemplate[] => {
    // 匹配逻辑: journey_type 与 pack_type 相同，或 journey 步骤中 mechanism_type 匹配
    return templates.filter((t) =>
      t.journey_type === pack.pack_type ||
      (t.steps || []).some((s) => s.offer_type === pack.mechanism_type)
    );
  };

  // 缺口3: 预算统计
  const budgetStats = useMemo(() => {
    const total = packs.reduce((s, p) => s + p.budget_limit_fen, 0);
    const p0Types = ['first_to_second', 'reactivation', 'service_repair'];
    const p0 = packs.filter((p) => p0Types.includes(p.pack_type)).reduce((s, p) => s + p.budget_limit_fen, 0);
    const p1 = total - p0;
    const avgPerCustomer = packs.length > 0 ? Math.round(total / packs.length) : 0;
    return { total, p0, p1, avgPerCustomer };
  }, [packs]);

  const formatYuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;

  return (
    <div style={{ padding: 24, background: PAGE_BG, minHeight: '100vh', color: TEXT_PRIMARY }}>
      {/* 页头 */}
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 8 }}>
          <GiftOutlined style={{ color: BRAND_ORANGE }} />
          增长权益策略台
        </h2>
        <div style={{ color: TEXT_SECONDARY, fontSize: 13, marginTop: 4 }}>
          权益包总览 / 旅程关联 / 毛利守护预算
        </div>
      </div>

      <Spin spinning={loading}>
        {/* 缺口3: 毛利守护预算面板 */}
        <Row gutter={16} style={{ marginBottom: 24 }}>
          <Col span={6}>
            <Card
              style={{ background: CARD_BG, border: `1px solid ${BORDER}` }}
              styles={{ body: { background: CARD_BG, padding: 16 } }}
            >
              <Statistic
                title={<span style={{ color: TEXT_SECONDARY }}>总预算上限</span>}
                value={formatYuan(budgetStats.total)}
                prefix={<DollarOutlined />}
                valueStyle={{ color: TEXT_PRIMARY, fontSize: 22 }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card
              style={{ background: CARD_BG, border: `1px solid ${BORDER}` }}
              styles={{ body: { background: CARD_BG, padding: 16 } }}
            >
              <Statistic
                title={<span style={{ color: TEXT_SECONDARY }}>P0包预算</span>}
                value={formatYuan(budgetStats.p0)}
                prefix={<SafetyCertificateOutlined />}
                valueStyle={{ color: budgetStats.p0 > 10000 ? DANGER_RED : SUCCESS_GREEN, fontSize: 22 }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card
              style={{ background: CARD_BG, border: `1px solid ${BORDER}` }}
              styles={{ body: { background: CARD_BG, padding: 16 } }}
            >
              <Statistic
                title={<span style={{ color: TEXT_SECONDARY }}>P1包预算</span>}
                value={formatYuan(budgetStats.p1)}
                valueStyle={{ color: budgetStats.p1 > 50000 ? DANGER_RED : SUCCESS_GREEN, fontSize: 22 }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card
              style={{ background: CARD_BG, border: `1px solid ${BORDER}` }}
              styles={{ body: { background: CARD_BG, padding: 16 } }}
            >
              <Statistic
                title={<span style={{ color: TEXT_SECONDARY }}>平均单包成本</span>}
                value={formatYuan(budgetStats.avgPerCustomer)}
                valueStyle={{ color: TEXT_PRIMARY, fontSize: 22 }}
              />
            </Card>
          </Col>
        </Row>

        {/* 顶部筛选 */}
        <Card
          style={{ background: CARD_BG, border: `1px solid ${BORDER}`, marginBottom: 24 }}
          styles={{ body: { background: CARD_BG, padding: 16 } }}
        >
          <Space size={16}>
            <Select
              style={{ width: 180 }}
              placeholder="权益包类型"
              allowClear
              value={filterPackType}
              onChange={setFilterPackType}
              options={[
                { value: 'first_to_second', label: '首单二访' },
                { value: 'reactivation', label: '召回' },
                { value: 'service_repair', label: '服务修复' },
                { value: 'super_user', label: '超级用户' },
                { value: 'milestone', label: '里程碑' },
                { value: 'referral', label: '裂变' },
              ]}
            />
            <Select
              style={{ width: 200 }}
              placeholder="机制类型"
              allowClear
              value={filterMechanism}
              onChange={setFilterMechanism}
              options={mechanismTypes.map((m) => ({ value: m, label: m }))}
            />
            <span style={{ color: TEXT_SECONDARY, fontSize: 13 }}>
              共 {filteredPacks.length} 个权益包
            </span>
          </Space>
        </Card>

        {/* 权益包卡片列表 */}
        <Row gutter={[16, 16]}>
          {filteredPacks.map((pack) => {
            const linkedJourneys = getLinkedJourneys(pack);
            return (
              <Col span={8} key={pack.code}>
                <Card
                  style={{
                    background: CARD_BG, border: `1px solid ${BORDER}`,
                    height: '100%', display: 'flex', flexDirection: 'column',
                  }}
                  styles={{ body: { background: CARD_BG, padding: 20, flex: 1, display: 'flex', flexDirection: 'column' } }}
                >
                  {/* 头部：名称 + Tags + 关联旅程badge */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 16, fontWeight: 700, color: TEXT_PRIMARY, marginBottom: 8 }}>
                        {pack.name}
                      </div>
                      <Space size={4}>
                        <Tag color={PACK_TYPE_COLORS[pack.pack_type] || 'default'}>
                          {PACK_TYPE_LABELS[pack.pack_type] || pack.pack_type}
                        </Tag>
                        <Tag color="geekblue">{pack.mechanism_type}</Tag>
                      </Space>
                    </div>
                    {linkedJourneys.length > 0 && (
                      <Tag color={BRAND_ORANGE} style={{ borderRadius: 12, fontWeight: 600 }}>
                        <LinkOutlined /> {linkedJourneys.length}
                      </Tag>
                    )}
                  </div>

                  {/* 描述 */}
                  <div style={{ color: TEXT_SECONDARY, fontSize: 13, lineHeight: 1.6, marginBottom: 12 }}>
                    {pack.description}
                  </div>

                  {/* Items展开列表 */}
                  <Collapse
                    ghost
                    items={[{
                      key: 'items',
                      label: <span style={{ color: TEXT_SECONDARY, fontSize: 12 }}>权益明细 ({pack.items.length}项)</span>,
                      children: (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                          {pack.items.map((item, idx) => (
                            <div
                              key={idx}
                              style={{
                                background: PAGE_BG, borderRadius: 6, padding: '8px 12px',
                                border: `1px solid ${BORDER}`,
                              }}
                            >
                              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                <span>{ITEM_TYPE_ICONS[item.type] || '📦'}</span>
                                <span style={{ fontWeight: 600, color: TEXT_PRIMARY, fontSize: 13 }}>{item.name}</span>
                                {item.cost_fen > 0 && (
                                  <Tag color="orange" style={{ marginLeft: 'auto', fontSize: 11 }}>
                                    {formatYuan(item.cost_fen)}
                                  </Tag>
                                )}
                              </div>
                              <div style={{ color: TEXT_SECONDARY, fontSize: 12, marginTop: 4, paddingLeft: 22 }}>
                                {item.description}
                              </div>
                            </div>
                          ))}
                        </div>
                      ),
                    }]}
                    style={{ margin: '0 -8px' }}
                  />

                  {/* 底部: 预算 + 有效天数 */}
                  <div style={{
                    marginTop: 'auto', paddingTop: 12, borderTop: `1px solid ${BORDER}`,
                    display: 'flex', justifyContent: 'space-between', fontSize: 12,
                  }}>
                    <span style={{ color: TEXT_SECONDARY }}>
                      预算上限: <span style={{ color: pack.budget_limit_fen > 5000 ? DANGER_RED : SUCCESS_GREEN, fontWeight: 600 }}>
                        {formatYuan(pack.budget_limit_fen)}
                      </span>
                    </span>
                    <span style={{ color: TEXT_SECONDARY }}>
                      有效期: <span style={{ color: TEXT_PRIMARY, fontWeight: 600 }}>{pack.valid_days}天</span>
                    </span>
                  </div>

                  {/* 缺口2: 关联旅程展示 */}
                  {linkedJourneys.length > 0 && (
                    <Collapse
                      ghost
                      items={[{
                        key: 'journeys',
                        label: <span style={{ color: BRAND_ORANGE, fontSize: 12 }}>
                          <LinkOutlined /> 关联旅程 ({linkedJourneys.length})
                        </span>,
                        children: (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                            {linkedJourneys.map((j) => (
                              <div
                                key={j.id}
                                style={{
                                  background: PAGE_BG, borderRadius: 6, padding: '6px 10px',
                                  border: `1px solid ${BORDER}`,
                                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                                }}
                              >
                                <span style={{ color: TEXT_PRIMARY, fontSize: 13 }}>{j.name}</span>
                                <Tag color="blue" style={{ fontSize: 11 }}>{j.journey_type}</Tag>
                              </div>
                            ))}
                          </div>
                        ),
                      }]}
                      style={{ margin: '8px -8px 0' }}
                    />
                  )}
                </Card>
              </Col>
            );
          })}

          {filteredPacks.length === 0 && !loading && (
            <Col span={24}>
              <div style={{ textAlign: 'center', padding: 60, color: TEXT_SECONDARY }}>
                暂无匹配的权益包
              </div>
            </Col>
          )}
        </Row>
      </Spin>
    </div>
  );
}
