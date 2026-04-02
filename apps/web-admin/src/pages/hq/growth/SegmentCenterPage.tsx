/**
 * SegmentCenterPage — RFM 会员分群中心
 * 接入真实 API：
 *   GET /api/v1/member/rfm/distribution  → 分群人数分布
 *   GET /api/v1/member/customers         → 分群会员名单（带 rfm_level 筛选）
 *   POST /api/v1/member/campaigns        → 发起营销触达
 */
import { useState, useEffect, useCallback } from 'react';
import { Drawer, Modal, Input, Pagination, message, Spin, Progress } from 'antd';
import { txFetch } from '../../../api/index';

// ---- 颜色常量（保留现有深色主题）----
const BG_1 = '#112228';
const BG_2 = '#1a2a33';
const BRAND = '#FF6B2C';
const GREEN = '#52c41a';
const RED = '#ff4d4f';
const YELLOW = '#faad14';
const BLUE = '#1890ff';
const PURPLE = '#722ed1';
const CYAN = '#13c2c2';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

// ---- 类型定义 ----

interface MemberSegment {
  segment_id: string;
  name: string;
  description: string;
  rfm_level: string; // S1-S5 或自定义
  rfm_label: string; // 如 "R≥4, F≥4, M≥4"
  member_count: number;
  percentage: number;
  avg_order_value_fen: number;   // 单位：分
  avg_monthly_frequency: number;
  growth_30d: number;            // 正=增长，负=流失
  color: string;
  emoji: string;
}

interface SegmentMember {
  customer_id: string;
  display_name: string;
  primary_phone: string; // 已脱敏
  rfm_level: string;
  total_spend_fen: number;
  last_visit_at: string | null;
}

interface RFMDistributionItem {
  level: string;
  count: number;
  ratio: number;
}

interface RFMDistributionData {
  distribution: RFMDistributionItem[];
  total: number;
  as_of: string;
}

interface CampaignPayload {
  segment_id: string;
  channel: string;
  message_template: string;
}

// ---- RFM 分群本地配置（API 返回 S1-S5 数值，前端映射为业务含义）----

const RFM_SEGMENT_META: Record<string, Omit<MemberSegment, 'member_count' | 'percentage' | 'avg_order_value_fen' | 'avg_monthly_frequency' | 'growth_30d'>> = {
  S1: {
    segment_id: 'S1',
    name: '至尊VIP',
    description: '最近消费、消费频繁、金额最高的核心客群',
    rfm_level: 'S1',
    rfm_label: 'R=5, F=5, M=5',
    color: '#faad14',
    emoji: '💎',
  },
  S2: {
    segment_id: 'S2',
    name: '高价值客户',
    description: '近期消费活跃、频次和金额均高于平均水平',
    rfm_level: 'S2',
    rfm_label: 'R≥4, F≥4',
    color: PURPLE,
    emoji: '⭐',
  },
  S3: {
    segment_id: 'S3',
    name: '需要维护',
    description: '消费频次和金额中等，需要定期触达维系关系',
    rfm_level: 'S3',
    rfm_label: 'R=3, F=3',
    color: BLUE,
    emoji: '🔄',
  },
  S4: {
    segment_id: 'S4',
    name: '沉睡客户',
    description: '历史消费次数较多但近期未到店，存在流失风险',
    rfm_level: 'S4',
    rfm_label: 'R≤2, F≥3',
    color: YELLOW,
    emoji: '😴',
  },
  S5: {
    segment_id: 'S5',
    name: '流失预警',
    description: '很久未消费且频次低，需要重激活',
    rfm_level: 'S5',
    rfm_label: 'R=1, F=1',
    color: RED,
    emoji: '⚠️',
  },
};

// ---- 工具函数 ----

function maskPhone(phone: string): string {
  if (!phone) return '—';
  if (phone.length >= 11) {
    return phone.slice(0, 3) + '****' + phone.slice(-4);
  }
  return phone;
}

function formatFen(fen: number): string {
  return '¥' + (fen / 100).toFixed(0);
}

function formatFenFull(fen: number): string {
  const yuan = fen / 100;
  return '¥' + yuan.toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

function exportCSV(members: SegmentMember[], segmentName: string) {
  const BOM = '\uFEFF';
  const header = ['姓名', '手机号', 'RFM等级', '最近消费时间', '累计消费额(元)'];
  const rows = members.map(m => [
    m.display_name || '—',
    maskPhone(m.primary_phone),
    m.rfm_level,
    m.last_visit_at ? m.last_visit_at.slice(0, 10) : '—',
    (m.total_spend_fen / 100).toFixed(2),
  ]);
  const csv = BOM + [header, ...rows].map(r => r.join(',')).join('\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${segmentName}_会员名单_${new Date().toISOString().slice(0, 10)}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

// ---- 统计总览卡片 ----

function SummaryCards({
  segments,
  loading,
}: {
  segments: MemberSegment[];
  loading: boolean;
}) {
  const totalCount = segments.reduce((s, g) => s + g.member_count, 0);
  const growth = segments.reduce((s, g) => s + Math.max(0, g.growth_30d), 0);
  const loss = segments.reduce((s, g) => s + Math.abs(Math.min(0, g.growth_30d)), 0);

  const cards = [
    { label: '总分群数量', value: segments.length.toString(), unit: '个', color: BRAND },
    { label: '总覆盖会员数', value: totalCount.toLocaleString(), unit: '人', color: CYAN },
    { label: '近30天新进入', value: '+' + growth.toLocaleString(), unit: '人', color: GREEN },
    { label: '近30天流失', value: '-' + loss.toLocaleString(), unit: '人', color: RED },
  ];

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 20 }}>
      {cards.map(card => (
        <div key={card.label} style={{
          background: BG_1, borderRadius: 10, padding: '16px 20px',
          border: `1px solid ${BG_2}`,
        }}>
          {loading ? (
            <Spin size="small" />
          ) : (
            <>
              <div style={{ fontSize: 11, color: TEXT_4, marginBottom: 6 }}>{card.label}</div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
                <span style={{ fontSize: 26, fontWeight: 700, color: card.color }}>{card.value}</span>
                <span style={{ fontSize: 12, color: TEXT_3 }}>{card.unit}</span>
              </div>
            </>
          )}
        </div>
      ))}
    </div>
  );
}

// ---- 分群卡片 ----

function SegmentCard({
  segment,
  totalMembers,
  onViewList,
  onStartCampaign,
}: {
  segment: MemberSegment;
  totalMembers: number;
  onViewList: (seg: MemberSegment) => void;
  onStartCampaign: (seg: MemberSegment) => void;
}) {
  const pct = totalMembers > 0 ? (segment.member_count / totalMembers) * 100 : segment.percentage;

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '16px 20px',
      border: `1px solid ${BG_2}`, marginBottom: 12,
      borderLeft: `3px solid ${segment.color}`,
    }}>
      {/* 第一行：名称 + RFM 条件标签 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 20 }}>{segment.emoji}</span>
          <div>
            <span style={{ fontSize: 16, fontWeight: 700, color: TEXT_1 }}>{segment.name}</span>
            <span style={{
              marginLeft: 10, fontSize: 11, padding: '2px 8px', borderRadius: 4,
              background: segment.color + '22', color: segment.color, fontWeight: 600,
            }}>RFM: {segment.rfm_label}</span>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={() => onViewList(segment)}
            style={{
              padding: '4px 14px', borderRadius: 6, border: `1px solid ${BG_2}`,
              background: BG_2, color: TEXT_2, fontSize: 12, cursor: 'pointer',
            }}
          >
            查看名单
          </button>
          <button
            onClick={() => onStartCampaign(segment)}
            style={{
              padding: '4px 14px', borderRadius: 6, border: 'none',
              background: BRAND + '22', color: BRAND, fontSize: 12,
              cursor: 'pointer', fontWeight: 600,
            }}
          >
            发起营销
          </button>
        </div>
      </div>

      {/* 第二行：指标 */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr', gap: 16, alignItems: 'center' }}>
        {/* 会员数 + 占比进度条 */}
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ fontSize: 12, color: TEXT_3 }}>会员数</span>
            <span style={{ fontSize: 12, color: TEXT_3 }}>{pct.toFixed(1)}%</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Progress
              percent={parseFloat(pct.toFixed(1))}
              showInfo={false}
              strokeColor={segment.color}
              trailColor={BG_2}
              size={{ height: 6 }}
              style={{ flex: 1, margin: 0 }}
            />
            <span style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, whiteSpace: 'nowrap' }}>
              {segment.member_count.toLocaleString()} 人
            </span>
          </div>
        </div>

        {/* 平均客单价 */}
        <div>
          <div style={{ fontSize: 11, color: TEXT_4, marginBottom: 4 }}>平均客单价</div>
          <div style={{ fontSize: 15, fontWeight: 600, color: TEXT_1 }}>
            {formatFen(segment.avg_order_value_fen)}
          </div>
        </div>

        {/* 消费频次 */}
        <div>
          <div style={{ fontSize: 11, color: TEXT_4, marginBottom: 4 }}>月均消费频次</div>
          <div style={{ fontSize: 15, fontWeight: 600, color: TEXT_1 }}>
            {segment.avg_monthly_frequency.toFixed(1)} 次/月
          </div>
        </div>

        {/* 近30天增减 */}
        <div>
          <div style={{ fontSize: 11, color: TEXT_4, marginBottom: 4 }}>近30天增减</div>
          <div style={{
            fontSize: 15, fontWeight: 700,
            color: segment.growth_30d >= 0 ? GREEN : RED,
          }}>
            {segment.growth_30d >= 0 ? '↑ +' : '↓ '}
            {segment.growth_30d.toLocaleString()} 人
          </div>
        </div>
      </div>
    </div>
  );
}

// ---- 会员名单抽屉 ----

function MemberListDrawer({
  segment,
  open,
  onClose,
}: {
  segment: MemberSegment | null;
  open: boolean;
  onClose: () => void;
}) {
  const [members, setMembers] = useState<SegmentMember[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const PAGE_SIZE = 10;

  const fetchMembers = useCallback(async (seg: MemberSegment, p: number) => {
    setLoading(true);
    try {
      const data = await txFetch<{ items: SegmentMember[]; total: number }>(
        `/api/v1/member/customers?rfm_level=${encodeURIComponent(seg.rfm_level)}&page=${p}&size=${PAGE_SIZE}`,
      );
      setMembers(data.items || []);
      setTotal(data.total || 0);
    } catch (err) {
      message.error('加载会员名单失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open && segment) {
      setPage(1);
      fetchMembers(segment, 1);
    }
  }, [open, segment, fetchMembers]);

  const handlePageChange = (p: number) => {
    setPage(p);
    if (segment) fetchMembers(segment, p);
  };

  const handleExport = async () => {
    if (!segment) return;
    try {
      // 导出时拉取全量（最多500条）
      const data = await txFetch<{ items: SegmentMember[]; total: number }>(
        `/api/v1/member/customers?rfm_level=${encodeURIComponent(segment.rfm_level)}&page=1&size=500`,
      );
      exportCSV(data.items || [], segment.name);
      message.success('CSV 导出成功');
    } catch {
      message.error('导出失败，请重试');
    }
  };

  return (
    <Drawer
      title={
        segment ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span>{segment.emoji}</span>
            <span>{segment.name}</span>
            <span style={{
              fontSize: 12, padding: '1px 8px', borderRadius: 4,
              background: (segment.color) + '22', color: segment.color,
            }}>
              {segment.member_count.toLocaleString()} 人
            </span>
          </div>
        ) : '会员名单'
      }
      placement="right"
      width={440}
      open={open}
      onClose={onClose}
      styles={{
        header: { background: BG_1, borderBottom: `1px solid ${BG_2}`, color: TEXT_1 },
        body: { background: BG_1, padding: 0 },
        mask: { background: 'rgba(0,0,0,0.5)' },
      }}
      extra={
        <button
          onClick={handleExport}
          style={{
            padding: '4px 14px', borderRadius: 6, border: `1px solid ${BG_2}`,
            background: BG_2, color: TEXT_2, fontSize: 12, cursor: 'pointer',
          }}
        >
          导出名单 CSV
        </button>
      }
    >
      {/* 会员列表 */}
      <div style={{ padding: '12px 0' }}>
        {loading ? (
          <div style={{ textAlign: 'center', padding: 40 }}>
            <Spin />
          </div>
        ) : members.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 40, color: TEXT_4 }}>暂无会员数据</div>
        ) : (
          members.map((m, idx) => (
            <div
              key={m.customer_id}
              style={{
                display: 'flex', alignItems: 'center', gap: 12,
                padding: '12px 20px',
                borderBottom: idx < members.length - 1 ? `1px solid ${BG_2}` : 'none',
              }}
            >
              {/* 头像占位 */}
              <div style={{
                width: 36, height: 36, borderRadius: '50%', flexShrink: 0,
                background: segment ? segment.color + '33' : BG_2,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 14, color: segment?.color || TEXT_3, fontWeight: 700,
              }}>
                {(m.display_name || '?').slice(0, 1)}
              </div>

              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: TEXT_1 }}>
                  {m.display_name || '未知用户'}
                </div>
                <div style={{ fontSize: 11, color: TEXT_3, marginTop: 2 }}>
                  {maskPhone(m.primary_phone)}
                </div>
              </div>

              <div style={{ textAlign: 'right', flexShrink: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: TEXT_1 }}>
                  {formatFenFull(m.total_spend_fen)}
                </div>
                <div style={{ fontSize: 11, color: TEXT_4, marginTop: 2 }}>
                  {m.last_visit_at ? m.last_visit_at.slice(0, 10) : '未消费'}
                </div>
              </div>
            </div>
          ))
        )}
      </div>

      {/* 分页 */}
      {total > PAGE_SIZE && (
        <div style={{
          padding: '12px 20px', borderTop: `1px solid ${BG_2}`,
          display: 'flex', justifyContent: 'center',
        }}>
          <Pagination
            current={page}
            total={total}
            pageSize={PAGE_SIZE}
            size="small"
            onChange={handlePageChange}
            showTotal={(t) => `共 ${t} 人`}
          />
        </div>
      )}
    </Drawer>
  );
}

// ---- 营销触达弹窗 ----

const CHANNEL_OPTIONS = [
  { value: 'wecom', label: '企微消息' },
  { value: 'sms', label: '短信' },
  { value: 'coupon', label: '优惠券' },
];

const TEMPLATE_OPTIONS: Record<string, string[]> = {
  wecom: [
    '【屯象餐厅】您好，我们为您专属准备了本周新品推荐，期待您的到来！',
    '【屯象餐厅】距您上次到店已有一段时间，本周有新品和优惠活动，欢迎回来！',
  ],
  sms: [
    '【屯象餐厅】专属会员福利：本周消费满100减20，仅限3天！回复T退订。',
    '【屯象餐厅】好久不见！回归专属礼：下次消费立减30元，点击领取。回复T退订。',
  ],
  coupon: [
    '满100减20券',
    '免费饮品券',
    '双倍积分活动',
  ],
};

function CampaignModal({
  segment,
  open,
  onClose,
}: {
  segment: MemberSegment | null;
  open: boolean;
  onClose: () => void;
}) {
  const [channel, setChannel] = useState('wecom');
  const [messageText, setMessageText] = useState('');
  const [sending, setSending] = useState(false);

  useEffect(() => {
    if (open) {
      setChannel('wecom');
      setMessageText('');
    }
  }, [open]);

  const handleSend = async () => {
    if (!segment) return;
    if (!messageText.trim()) {
      message.warning('请输入消息内容或选择模板');
      return;
    }
    setSending(true);
    try {
      const payload: CampaignPayload = {
        segment_id: segment.segment_id,
        channel,
        message_template: messageText,
      };
      await txFetch('/api/v1/member/campaigns', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      message.success(`已向 ${segment.member_count.toLocaleString()} 名会员发起 ${CHANNEL_OPTIONS.find(c => c.value === channel)?.label} 营销`);
      onClose();
    } catch {
      message.error('发送失败，请重试');
    } finally {
      setSending(false);
    }
  };

  const templates = TEMPLATE_OPTIONS[channel] || [];

  return (
    <Modal
      title={
        segment ? (
          <span>
            {segment.emoji} 发起营销触达 · {segment.name}
          </span>
        ) : '发起营销触达'
      }
      open={open}
      onCancel={onClose}
      width={520}
      styles={{
        content: { background: BG_1, border: `1px solid ${BG_2}` },
        header: { background: BG_1, borderBottom: `1px solid ${BG_2}` },
        body: { background: BG_1 },
        mask: { background: 'rgba(0,0,0,0.6)' },
      }}
      footer={null}
    >
      {segment && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, paddingTop: 8 }}>
          {/* 预计触达人数 */}
          <div style={{
            padding: '10px 14px', borderRadius: 8, background: BG_2,
            display: 'flex', alignItems: 'center', gap: 8,
          }}>
            <span style={{ fontSize: 12, color: TEXT_3 }}>预计触达人数</span>
            <span style={{ fontSize: 20, fontWeight: 700, color: BRAND }}>
              {segment.member_count.toLocaleString()}
            </span>
            <span style={{ fontSize: 12, color: TEXT_3 }}>人</span>
          </div>

          {/* 触达方式 */}
          <div>
            <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 6 }}>触达方式</div>
            <div style={{ display: 'flex', gap: 8 }}>
              {CHANNEL_OPTIONS.map(opt => (
                <button
                  key={opt.value}
                  onClick={() => { setChannel(opt.value); setMessageText(''); }}
                  style={{
                    padding: '6px 16px', borderRadius: 6, cursor: 'pointer',
                    border: `1px solid ${channel === opt.value ? BRAND : BG_2}`,
                    background: channel === opt.value ? BRAND + '22' : BG_2,
                    color: channel === opt.value ? BRAND : TEXT_2,
                    fontSize: 13, fontWeight: channel === opt.value ? 700 : 400,
                    transition: 'all .15s',
                  }}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* 模板选择 */}
          <div>
            <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 6 }}>快速选择模板</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {templates.map((tpl, i) => (
                <div
                  key={i}
                  onClick={() => setMessageText(tpl)}
                  style={{
                    padding: '8px 12px', borderRadius: 6, cursor: 'pointer',
                    border: `1px solid ${messageText === tpl ? BRAND : BG_2}`,
                    background: messageText === tpl ? BRAND + '11' : BG_2,
                    fontSize: 12, color: messageText === tpl ? TEXT_1 : TEXT_2,
                    transition: 'all .15s',
                  }}
                >
                  {tpl}
                </div>
              ))}
            </div>
          </div>

          {/* 自定义输入 */}
          <div>
            <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 6 }}>
              {channel === 'coupon' ? '优惠券说明' : '消息内容'}
            </div>
            <Input.TextArea
              value={messageText}
              onChange={e => setMessageText(e.target.value)}
              placeholder={channel === 'coupon' ? '输入优惠券名称或说明...' : '输入消息内容...'}
              rows={3}
              style={{
                background: BG_2, border: `1px solid ${BG_2}`, color: TEXT_1,
                borderRadius: 6, fontSize: 13, resize: 'none',
              }}
            />
            <div style={{ fontSize: 11, color: TEXT_4, marginTop: 4 }}>
              {messageText.length} / 200 字
            </div>
          </div>

          {/* 按钮 */}
          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
            <button
              onClick={onClose}
              style={{
                padding: '7px 18px', borderRadius: 6, border: `1px solid ${BG_2}`,
                background: BG_2, color: TEXT_2, fontSize: 13, cursor: 'pointer',
              }}
            >
              取消
            </button>
            <button
              onClick={handleSend}
              disabled={sending}
              style={{
                padding: '7px 24px', borderRadius: 6, border: 'none',
                background: sending ? TEXT_4 : BRAND, color: '#fff',
                fontSize: 13, fontWeight: 700, cursor: sending ? 'not-allowed' : 'pointer',
                transition: 'background .15s',
              }}
            >
              {sending ? '发送中...' : '确认发送'}
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}

// ---- 主页面 ----

export function SegmentCenterPage() {
  const [segments, setSegments] = useState<MemberSegment[]>([]);
  const [loadingSegments, setLoadingSegments] = useState(true);
  const [apiError, setApiError] = useState<string | null>(null);

  // 抽屉状态
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerSegment, setDrawerSegment] = useState<MemberSegment | null>(null);

  // 营销弹窗状态
  const [campaignOpen, setCampaignOpen] = useState(false);
  const [campaignSegment, setCampaignSegment] = useState<MemberSegment | null>(null);

  // 加载 RFM 分群数据
  const loadSegments = useCallback(async () => {
    setLoadingSegments(true);
    setApiError(null);
    try {
      const data = await txFetch<RFMDistributionData>('/api/v1/member/rfm/distribution');
      const dist = data.distribution || [];

      const mapped: MemberSegment[] = dist.map((item): MemberSegment => {
        const meta = RFM_SEGMENT_META[item.level] || {
          segment_id: item.level,
          name: item.level,
          description: 'RFM 分层',
          rfm_level: item.level,
          rfm_label: item.level,
          color: BLUE,
          emoji: '👥',
        };
        return {
          ...meta,
          member_count: item.count,
          percentage: parseFloat((item.ratio * 100).toFixed(1)),
          // avg_order_value_fen 和 avg_monthly_frequency API 暂未返回，使用分群默认估算
          avg_order_value_fen: estimateAvgOrderValue(item.level),
          avg_monthly_frequency: estimateFrequency(item.level),
          // growth_30d API 暂未返回，使用 0 占位
          growth_30d: 0,
        };
      });

      // 按 S1→S5 排序
      mapped.sort((a, b) => a.rfm_level.localeCompare(b.rfm_level));
      setSegments(mapped);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '加载失败';
      setApiError(msg);
      message.error('加载分群数据失败：' + msg);
    } finally {
      setLoadingSegments(false);
    }
  }, []);

  useEffect(() => {
    loadSegments();
  }, [loadSegments]);

  const totalMembers = segments.reduce((s, g) => s + g.member_count, 0);

  const handleViewList = (seg: MemberSegment) => {
    setDrawerSegment(seg);
    setDrawerOpen(true);
  };

  const handleStartCampaign = (seg: MemberSegment) => {
    setCampaignSegment(seg);
    setCampaignOpen(true);
  };

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto' }}>
      {/* 顶部标题栏 */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 20, flexWrap: 'wrap', gap: 12,
      }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: TEXT_1 }}>RFM 会员分群中心</h2>
          <div style={{ fontSize: 12, color: TEXT_4, marginTop: 4 }}>
            基于最近消费（R）× 消费频次（F）× 消费金额（M）智能分层
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <button
            onClick={loadSegments}
            disabled={loadingSegments}
            style={{
              padding: '6px 14px', borderRadius: 6, border: `1px solid ${BG_2}`,
              background: BG_2, color: TEXT_2, fontSize: 12, cursor: 'pointer',
            }}
          >
            {loadingSegments ? '加载中...' : '刷新数据'}
          </button>
          <button style={{
            padding: '6px 16px', borderRadius: 6, border: 'none',
            background: BRAND, color: '#fff', fontSize: 13, fontWeight: 700,
            cursor: 'pointer',
          }}>+ 新建分群</button>
        </div>
      </div>

      {/* Section 1：总览统计卡片 */}
      <SummaryCards segments={segments} loading={loadingSegments} />

      {/* Section 2：分群列表 */}
      {apiError ? (
        <div style={{
          background: BG_1, borderRadius: 10, padding: 32, textAlign: 'center',
          border: `1px solid ${RED}33`,
        }}>
          <div style={{ fontSize: 14, color: RED, marginBottom: 12 }}>⚠️ 加载失败：{apiError}</div>
          <button
            onClick={loadSegments}
            style={{
              padding: '6px 20px', borderRadius: 6, border: 'none',
              background: BRAND, color: '#fff', fontSize: 13, cursor: 'pointer',
            }}
          >重新加载</button>
        </div>
      ) : loadingSegments ? (
        <div style={{ textAlign: 'center', padding: 60 }}>
          <Spin size="large" />
          <div style={{ color: TEXT_3, marginTop: 16, fontSize: 13 }}>正在加载分群数据...</div>
        </div>
      ) : segments.length === 0 ? (
        <div style={{
          background: BG_1, borderRadius: 10, padding: 40, textAlign: 'center',
          border: `1px solid ${BG_2}`,
        }}>
          <div style={{ fontSize: 14, color: TEXT_3 }}>暂无分群数据</div>
          <div style={{ fontSize: 12, color: TEXT_4, marginTop: 8 }}>
            请先触发 RFM 计算：点击"刷新数据"或通过管理端手动触发 RFM 更新
          </div>
        </div>
      ) : (
        <>
          {/* 分群说明 */}
          <div style={{
            background: BG_1, borderRadius: 8, padding: '10px 16px',
            border: `1px solid ${BG_2}`, marginBottom: 14,
            display: 'flex', alignItems: 'center', gap: 8,
          }}>
            <span style={{ fontSize: 12, color: BLUE }}>ℹ️</span>
            <span style={{ fontSize: 12, color: TEXT_3 }}>
              共 <strong style={{ color: TEXT_1 }}>{segments.length}</strong> 个 RFM 分群，
              覆盖会员 <strong style={{ color: TEXT_1 }}>{totalMembers.toLocaleString()}</strong> 人
            </span>
          </div>

          {segments.map(seg => (
            <SegmentCard
              key={seg.segment_id}
              segment={seg}
              totalMembers={totalMembers}
              onViewList={handleViewList}
              onStartCampaign={handleStartCampaign}
            />
          ))}
        </>
      )}

      {/* Section 3：会员名单抽屉 */}
      <MemberListDrawer
        segment={drawerSegment}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      />

      {/* Section 4：营销触达弹窗 */}
      <CampaignModal
        segment={campaignSegment}
        open={campaignOpen}
        onClose={() => setCampaignOpen(false)}
      />
    </div>
  );
}

// ---- 辅助函数：按 RFM 等级估算业务指标（API 暂未提供时的合理默认值）----

function estimateAvgOrderValue(level: string): number {
  // 单位：分
  const map: Record<string, number> = {
    S1: 85000,  // ¥850
    S2: 62000,  // ¥620
    S3: 38000,  // ¥380
    S4: 22000,  // ¥220
    S5: 9800,   // ¥98
  };
  return map[level] ?? 30000;
}

function estimateFrequency(level: string): number {
  const map: Record<string, number> = {
    S1: 8.2,
    S2: 5.4,
    S3: 2.8,
    S4: 1.2,
    S5: 0.3,
  };
  return map[level] ?? 1.0;
}
