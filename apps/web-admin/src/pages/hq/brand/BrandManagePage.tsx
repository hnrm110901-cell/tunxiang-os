/**
 * 多品牌管控台 -- 总部视角
 * 品牌卡片列表（品牌名/门店数/今日总营收/环比）
 * 新建品牌 | 品牌对比视图（2-3个品牌并排KPI）
 * 跨品牌会员统计（总会员/共享会员/品牌独占会员）
 *
 * 数据源：txFetch（后端 API）
 * 纯 CSS 实现可视化，无第三方图表库
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { Button, Modal, Form, Input, InputNumber, Spin, Tag, message, Checkbox } from 'antd';
import { PlusOutlined, ReloadOutlined, SwapOutlined } from '@ant-design/icons';
import { txFetch } from '../../../api';

// ─── 类型定义 ───────────────────────────────────────────────────────────────

interface BrandInfo {
  brand_id: string;
  brand_name: string;
  logo_color: string;  // 品牌代表色
  store_count: number;
  today_revenue_fen: number;
  yesterday_revenue_fen: number;
  trend_percent: number;  // 环比 %
  member_count: number;
  avg_ticket_fen: number;
  monthly_orders: number;
  turnover_rate: number;
}

interface CrossBrandMember {
  total_members: number;
  shared_members: number;    // 跨品牌会员
  brand_exclusive: Record<string, number>; // brand_id -> 独占会员数
}

// ─── 工具函数 ────────────────────────────────────────────────────────────────

const fmtMoney = (fen: number) =>
  `¥${(fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const fmtMoneyShort = (fen: number) => {
  const yuan = fen / 100;
  if (yuan >= 10000) return `¥${(yuan / 10000).toFixed(1)}万`;
  return `¥${yuan.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`;
};

const fmtPercent = (v: number) => `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`;

// ─── Mock 数据 ──────────────────────────────────────────────────────────────

const BRAND_COLORS = ['#FF6B35', '#185FA5', '#0F6E56', '#BA7517', '#8B5CF6', '#A32D2D'];

function mockBrands(): BrandInfo[] {
  const names = [
    { name: '尝在一起', stores: 28 },
    { name: '最黔线', stores: 15 },
    { name: '尚宫厨', stores: 8 },
    { name: '辣小厨', stores: 12 },
  ];
  return names.map((b, i) => {
    const todayRev = 1500000 + Math.floor(Math.random() * 3000000);
    const yesterdayRev = todayRev - 200000 + Math.floor(Math.random() * 400000);
    return {
      brand_id: `b${i}`,
      brand_name: b.name,
      logo_color: BRAND_COLORS[i % BRAND_COLORS.length],
      store_count: b.stores,
      today_revenue_fen: todayRev,
      yesterday_revenue_fen: yesterdayRev,
      trend_percent: +((todayRev - yesterdayRev) / yesterdayRev * 100).toFixed(1),
      member_count: 5000 + Math.floor(Math.random() * 20000),
      avg_ticket_fen: 6000 + Math.floor(Math.random() * 4000),
      monthly_orders: 8000 + Math.floor(Math.random() * 15000),
      turnover_rate: +(2 + Math.random() * 3).toFixed(1),
    };
  });
}

function mockCrossBrandMembers(brands: BrandInfo[]): CrossBrandMember {
  const total = brands.reduce((s, b) => s + b.member_count, 0);
  const shared = Math.floor(total * 0.15);
  const exclusive: Record<string, number> = {};
  brands.forEach(b => {
    exclusive[b.brand_id] = b.member_count - Math.floor(shared / brands.length);
  });
  return { total_members: total, shared_members: shared, brand_exclusive: exclusive };
}

// ─── 组件 ────────────────────────────────────────────────────────────────────

export function BrandManagePage() {
  const [loading, setLoading] = useState(false);
  const [brands, setBrands] = useState<BrandInfo[]>([]);
  const [memberStats, setMemberStats] = useState<CrossBrandMember | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [compareMode, setCompareMode] = useState(false);
  const [selectedBrandIds, setSelectedBrandIds] = useState<string[]>([]);
  const [form] = Form.useForm();

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      // TODO: 后端就绪后替换
      // const [brandRes, memberRes] = await Promise.allSettled([
      //   txFetch<{ items: BrandInfo[] }>('/api/v1/org/brands'),
      //   txFetch<CrossBrandMember>('/api/v1/member/cross-brand-stats'),
      // ]);
      await new Promise(r => setTimeout(r, 400));
      const b = mockBrands();
      setBrands(b);
      setMemberStats(mockCrossBrandMembers(b));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  // ─── 新建品牌 ───

  const handleCreateBrand = async () => {
    try {
      const values = await form.validateFields();
      // TODO: 后端就绪后替换
      // await txFetch('/api/v1/org/brands', { method: 'POST', body: JSON.stringify(values) });
      await new Promise(r => setTimeout(r, 500));
      message.success(`品牌「${values.brand_name}」创建成功`);
      setCreateOpen(false);
      form.resetFields();
      loadData();
    } catch {
      // 表单校验失败
    }
  };

  // ─── 对比选中 ───

  const toggleBrandSelect = (brandId: string) => {
    setSelectedBrandIds(prev => {
      if (prev.includes(brandId)) return prev.filter(id => id !== brandId);
      if (prev.length >= 3) {
        message.warning('最多选择3个品牌进行对比');
        return prev;
      }
      return [...prev, brandId];
    });
  };

  const selectedBrands = useMemo(
    () => brands.filter(b => selectedBrandIds.includes(b.brand_id)),
    [brands, selectedBrandIds],
  );

  // ─── KPI 对比指标 ───

  const compareMetrics = [
    { key: 'today_revenue_fen', label: '今日营收', format: fmtMoneyShort },
    { key: 'store_count', label: '门店数', format: (v: number) => `${v} 家` },
    { key: 'member_count', label: '会员数', format: (v: number) => v >= 10000 ? `${(v / 10000).toFixed(1)}万` : `${v}` },
    { key: 'avg_ticket_fen', label: '客单价', format: fmtMoney },
    { key: 'monthly_orders', label: '月订单', format: (v: number) => v >= 10000 ? `${(v / 10000).toFixed(1)}万` : `${v}` },
    { key: 'turnover_rate', label: '翻台率', format: (v: number) => `${v}次/天` },
  ] as const;

  return (
    <div style={{ padding: 24, background: '#F8F7F5', minHeight: '100vh' }}>
      {/* ─── 顶部 ─── */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 24, flexWrap: 'wrap', gap: 12,
      }}>
        <h2 style={{ margin: 0, fontSize: 20, color: '#2C2C2A' }}>多品牌管控台</h2>
        <div style={{ display: 'flex', gap: 8 }}>
          <Button
            icon={<SwapOutlined />}
            onClick={() => {
              setCompareMode(!compareMode);
              if (compareMode) setSelectedBrandIds([]);
            }}
            type={compareMode ? 'primary' : 'default'}
            style={compareMode ? { background: '#FF6B35', borderColor: '#FF6B35' } : {}}
          >
            {compareMode ? '退出对比' : '品牌对比'}
          </Button>
          <Button icon={<ReloadOutlined />} onClick={loadData} loading={loading}>
            刷新
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setCreateOpen(true)}
            style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
          >
            新建品牌
          </Button>
        </div>
      </div>

      <Spin spinning={loading}>
        {/* ─── 品牌卡片列表 ─── */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
          gap: 16, marginBottom: 24,
        }}>
          {brands.map(brand => {
            const isSelected = selectedBrandIds.includes(brand.brand_id);
            return (
              <div
                key={brand.brand_id}
                onClick={() => compareMode && toggleBrandSelect(brand.brand_id)}
                style={{
                  background: '#fff', borderRadius: 8, padding: 20,
                  boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
                  cursor: compareMode ? 'pointer' : 'default',
                  border: isSelected ? `2px solid ${brand.logo_color}` : '2px solid transparent',
                  transition: 'border-color 0.2s, box-shadow 0.2s',
                  position: 'relative',
                }}
              >
                {compareMode && (
                  <Checkbox
                    checked={isSelected}
                    style={{ position: 'absolute', top: 12, right: 12 }}
                  />
                )}

                {/* 品牌头部 */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
                  <div style={{
                    width: 40, height: 40, borderRadius: 8,
                    background: brand.logo_color, display: 'flex',
                    alignItems: 'center', justifyContent: 'center',
                    color: '#fff', fontWeight: 700, fontSize: 18,
                  }}>
                    {brand.brand_name.charAt(0)}
                  </div>
                  <div>
                    <div style={{ fontWeight: 600, fontSize: 16, color: '#2C2C2A' }}>
                      {brand.brand_name}
                    </div>
                    <div style={{ fontSize: 13, color: '#5F5E5A' }}>
                      {brand.store_count} 家门店
                    </div>
                  </div>
                </div>

                {/* 营收 */}
                <div style={{ marginBottom: 12 }}>
                  <div style={{ fontSize: 13, color: '#5F5E5A', marginBottom: 4 }}>今日营收</div>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                    <span style={{ fontSize: 24, fontWeight: 700, color: '#2C2C2A' }}>
                      {fmtMoneyShort(brand.today_revenue_fen)}
                    </span>
                    <span style={{
                      fontSize: 13, fontWeight: 600,
                      color: brand.trend_percent >= 0 ? '#0F6E56' : '#A32D2D',
                    }}>
                      {fmtPercent(brand.trend_percent)}
                    </span>
                  </div>
                </div>

                {/* 底部指标 */}
                <div style={{
                  display: 'grid', gridTemplateColumns: '1fr 1fr 1fr',
                  gap: 8, paddingTop: 12, borderTop: '1px solid #F0EDE6',
                }}>
                  <div>
                    <div style={{ fontSize: 11, color: '#B4B2A9' }}>会员</div>
                    <div style={{ fontSize: 14, fontWeight: 600, color: '#2C2C2A' }}>
                      {brand.member_count >= 10000 ? `${(brand.member_count / 10000).toFixed(1)}万` : brand.member_count}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: '#B4B2A9' }}>客单价</div>
                    <div style={{ fontSize: 14, fontWeight: 600, color: '#2C2C2A' }}>
                      {fmtMoney(brand.avg_ticket_fen)}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: '#B4B2A9' }}>翻台率</div>
                    <div style={{ fontSize: 14, fontWeight: 600, color: '#2C2C2A' }}>
                      {brand.turnover_rate}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* ─── 品牌对比视图 ─── */}
        {compareMode && selectedBrands.length >= 2 && (
          <div style={{
            background: '#fff', borderRadius: 8, padding: 24, marginBottom: 24,
            boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
          }}>
            <div style={{ fontSize: 16, fontWeight: 600, color: '#2C2C2A', marginBottom: 16 }}>
              品牌对比
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
              <thead>
                <tr style={{ borderBottom: '2px solid #E8E6E1' }}>
                  <th style={{ padding: '10px 12px', textAlign: 'left', color: '#5F5E5A', fontWeight: 500, width: 120 }}>
                    指标
                  </th>
                  {selectedBrands.map(b => (
                    <th key={b.brand_id} style={{ padding: '10px 12px', textAlign: 'center' }}>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
                        <span style={{
                          width: 12, height: 12, borderRadius: 3, background: b.logo_color,
                          display: 'inline-block',
                        }} />
                        <span style={{ fontWeight: 600, color: '#2C2C2A' }}>{b.brand_name}</span>
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {compareMetrics.map(metric => {
                  const values = selectedBrands.map(b => (b as Record<string, number>)[metric.key] as number);
                  const maxVal = Math.max(...values);
                  return (
                    <tr key={metric.key} style={{ borderBottom: '1px solid #F0EDE6' }}>
                      <td style={{ padding: '10px 12px', color: '#5F5E5A', fontWeight: 500 }}>
                        {metric.label}
                      </td>
                      {selectedBrands.map((b, idx) => {
                        const val = values[idx];
                        const isMax = val === maxVal;
                        return (
                          <td key={b.brand_id} style={{ padding: '10px 12px', textAlign: 'center' }}>
                            <span style={{
                              fontWeight: isMax ? 700 : 400,
                              color: isMax ? '#FF6B35' : '#2C2C2A',
                            }}>
                              {metric.format(val)}
                            </span>
                            {isMax && <Tag color="orange" style={{ marginLeft: 4, fontSize: 10 }}>最高</Tag>}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>

            {/* 对比柱状条 */}
            <div style={{ marginTop: 20 }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: '#2C2C2A', marginBottom: 12 }}>
                营收对比
              </div>
              {selectedBrands.map(b => {
                const maxRev = Math.max(...selectedBrands.map(x => x.today_revenue_fen));
                const pct = (b.today_revenue_fen / maxRev) * 100;
                return (
                  <div key={b.brand_id} style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
                    <span style={{ width: 80, fontSize: 13, color: '#2C2C2A', textAlign: 'right', flexShrink: 0 }}>
                      {b.brand_name}
                    </span>
                    <div style={{
                      flex: 1, height: 24, borderRadius: 4, background: '#F0EDE6',
                      position: 'relative', overflow: 'hidden',
                    }}>
                      <div style={{
                        position: 'absolute', left: 0, top: 0, height: '100%',
                        borderRadius: 4,
                        width: `${pct}%`,
                        background: b.logo_color,
                        transition: 'width 0.6s ease',
                        display: 'flex', alignItems: 'center', justifyContent: 'flex-end',
                        paddingRight: 8,
                      }}>
                        <span style={{ fontSize: 11, color: '#fff', fontWeight: 600 }}>
                          {fmtMoneyShort(b.today_revenue_fen)}
                        </span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* ─── 跨品牌会员统计 ─── */}
        {memberStats && (
          <div style={{
            background: '#fff', borderRadius: 8, padding: 24,
            boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
          }}>
            <div style={{ fontSize: 16, fontWeight: 600, color: '#2C2C2A', marginBottom: 16 }}>
              跨品牌会员统计
            </div>

            {/* 三个大字卡 */}
            <div style={{
              display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
              gap: 16, marginBottom: 20,
            }}>
              <div style={{
                background: '#F8F7F5', borderRadius: 8, padding: 16, textAlign: 'center',
              }}>
                <div style={{ fontSize: 13, color: '#5F5E5A', marginBottom: 4 }}>总会员数</div>
                <div style={{ fontSize: 32, fontWeight: 700, color: '#2C2C2A' }}>
                  {memberStats.total_members >= 10000
                    ? `${(memberStats.total_members / 10000).toFixed(1)}万`
                    : memberStats.total_members}
                </div>
              </div>
              <div style={{
                background: '#FFF3ED', borderRadius: 8, padding: 16, textAlign: 'center',
              }}>
                <div style={{ fontSize: 13, color: '#5F5E5A', marginBottom: 4 }}>跨品牌共享会员</div>
                <div style={{ fontSize: 32, fontWeight: 700, color: '#FF6B35' }}>
                  {memberStats.shared_members >= 10000
                    ? `${(memberStats.shared_members / 10000).toFixed(1)}万`
                    : memberStats.shared_members}
                </div>
                <div style={{ fontSize: 12, color: '#B4B2A9', marginTop: 4 }}>
                  占比 {((memberStats.shared_members / memberStats.total_members) * 100).toFixed(1)}%
                </div>
              </div>
              <div style={{
                background: '#F0F7F4', borderRadius: 8, padding: 16, textAlign: 'center',
              }}>
                <div style={{ fontSize: 13, color: '#5F5E5A', marginBottom: 4 }}>品牌独占会员</div>
                <div style={{ fontSize: 32, fontWeight: 700, color: '#0F6E56' }}>
                  {(memberStats.total_members - memberStats.shared_members) >= 10000
                    ? `${((memberStats.total_members - memberStats.shared_members) / 10000).toFixed(1)}万`
                    : memberStats.total_members - memberStats.shared_members}
                </div>
              </div>
            </div>

            {/* 各品牌独占分布 */}
            <div style={{ fontSize: 14, fontWeight: 600, color: '#2C2C2A', marginBottom: 12 }}>
              各品牌独占会员分布
            </div>
            <div style={{ display: 'flex', gap: 4, height: 32, borderRadius: 6, overflow: 'hidden', marginBottom: 8 }}>
              {brands.map(b => {
                const exclusive = memberStats.brand_exclusive[b.brand_id] ?? 0;
                const pct = (exclusive / memberStats.total_members) * 100;
                return (
                  <div
                    key={b.brand_id}
                    style={{
                      width: `${pct}%`, minWidth: pct > 3 ? undefined : 24,
                      background: b.logo_color,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      color: '#fff', fontSize: 11, fontWeight: 600,
                      transition: 'width 0.6s ease',
                    }}
                    title={`${b.brand_name}: ${exclusive} 人 (${pct.toFixed(1)}%)`}
                  >
                    {pct > 8 && b.brand_name}
                  </div>
                );
              })}
              {/* 共享会员条 */}
              <div
                style={{
                  width: `${(memberStats.shared_members / memberStats.total_members) * 100}%`,
                  background: 'repeating-linear-gradient(45deg, #E8E6E1, #E8E6E1 4px, #F8F7F5 4px, #F8F7F5 8px)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  color: '#5F5E5A', fontSize: 11, fontWeight: 600,
                }}
                title={`共享会员: ${memberStats.shared_members} 人`}
              >
                共享
              </div>
            </div>
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 12, color: '#5F5E5A' }}>
              {brands.map(b => (
                <span key={b.brand_id} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span style={{
                    width: 10, height: 10, borderRadius: 2,
                    background: b.logo_color, display: 'inline-block',
                  }} />
                  {b.brand_name}: {memberStats.brand_exclusive[b.brand_id] ?? 0}人
                </span>
              ))}
              <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <span style={{
                  width: 10, height: 10, borderRadius: 2,
                  background: 'repeating-linear-gradient(45deg, #E8E6E1, #E8E6E1 2px, #F8F7F5 2px, #F8F7F5 4px)',
                  display: 'inline-block',
                }} />
                共享: {memberStats.shared_members}人
              </span>
            </div>
          </div>
        )}
      </Spin>

      {/* ─── 新建品牌弹窗 ─── */}
      <Modal
        title="新建品牌"
        open={createOpen}
        onOk={handleCreateBrand}
        onCancel={() => { setCreateOpen(false); form.resetFields(); }}
        okText="确认创建"
        cancelText="取消"
        okButtonProps={{ style: { background: '#FF6B35', borderColor: '#FF6B35' } }}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            name="brand_name"
            label="品牌名称"
            rules={[{ required: true, message: '请输入品牌名称' }]}
          >
            <Input placeholder="例如：尝在一起" />
          </Form.Item>
          <Form.Item
            name="brand_code"
            label="品牌编码"
            rules={[
              { required: true, message: '请输入品牌编码' },
              { pattern: /^[a-z][a-z0-9_-]*$/, message: '小写字母开头，仅含字母数字下划线连字符' },
            ]}
          >
            <Input placeholder="例如：czyz" />
          </Form.Item>
          <Form.Item
            name="contact_person"
            label="联系人"
          >
            <Input placeholder="品牌负责人姓名" />
          </Form.Item>
          <Form.Item
            name="contact_phone"
            label="联系电话"
          >
            <Input placeholder="手机号码" />
          </Form.Item>
          <Form.Item
            name="initial_store_count"
            label="初始门店数"
          >
            <InputNumber min={0} placeholder="0" style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

export default BrandManagePage;
