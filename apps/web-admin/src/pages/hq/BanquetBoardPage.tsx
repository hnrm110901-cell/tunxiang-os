/**
 * 宴会管理看板 — 总部视角
 * 漏斗图：线索→报价→签约→执行→完成
 * KPI 卡片 | 宴会列表（按状态/时间/门店筛选）| 右侧详情抽屉 | 新增线索弹窗
 *
 * 数据源：真实 API（banquetApi.ts）
 * 组件库：Ant Design 5.x（已安装）
 * 主题：深色面板（#112228 / #0B1A20）+ 品牌橙 #FF6B35
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Button,
  Table,
  Drawer,
  Modal,
  Form,
  Input,
  Select,
  DatePicker,
  InputNumber,
  message,
  Timeline,
  Divider,
  Spin,
  Space,
  Tooltip,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { TablePaginationConfig } from 'antd/es/table';
import dayjs from 'dayjs';
import {
  fetchBanquetFunnel,
  fetchBanquetList,
  fetchBanquetKPIs,
  fetchBanquetDetail,
  createBanquetLead,
  advanceBanquetStage,
} from '../../api/banquetApi';
import type {
  BanquetFunnelData,
  BanquetFunnelStage,
  BanquetListItem,
  BanquetKPIs,
  BanquetDetail,
  BanquetStage,
} from '../../api/banquetApi';

// ─── 常量 ───────────────────────────────────────────────────────────────────

type StageFilter = 'all' | BanquetStage;

const STAGE_LABELS: Record<string, string> = {
  all: '全部',
  lead: '线索',
  quote: '报价',
  signed: '签约',
  executing: '执行中',
  completed: '已完成',
  cancelled: '已取消',
};

// 状态徽章颜色：按设计要求
const STAGE_BADGE: Record<string, { bg: string; color: string }> = {
  lead:      { bg: '#185FA520', color: '#185FA5' }, // 蓝
  quote:     { bg: '#BA751720', color: '#BA7517' }, // 橙
  signed:    { bg: '#0F6E5620', color: '#0F6E56' }, // 绿
  executing: { bg: '#0a4a3820', color: '#0a8a68' }, // 深绿
  completed: { bg: '#66666620', color: '#888888' }, // 灰
  cancelled: { bg: '#66666615', color: '#666666' }, // 浅灰
};

const FUNNEL_COLORS = ['#FF6B35', '#185FA5', '#0F6E56', '#BA7517', '#8B5CF6'];

const NEXT_STAGE: Record<string, string> = {
  lead: 'quote',
  quote: 'signed',
  signed: 'executing',
  executing: 'completed',
};

const EVENT_TYPE_OPTIONS = [
  { value: 'wedding',  label: '婚宴' },
  { value: 'birthday', label: '寿宴' },
  { value: 'business', label: '商务宴' },
  { value: 'birthday_party', label: '生日宴' },
  { value: 'other',    label: '其他' },
];

const SOURCE_OPTIONS = [
  { value: 'meituan',   label: '美团' },
  { value: 'koubei',    label: '口碑' },
  { value: 'referral',  label: '转介绍' },
  { value: 'walk_in',   label: '自然到访' },
];

// ─── 工具函数 ────────────────────────────────────────────────────────────────

/** 分→元，2 位小数，千分符 */
const fmtMoney = (fen: number) =>
  `¥${(fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** 手机号脱敏：138****8888 */
const maskPhone = (phone: string) => {
  if (!phone || phone.length < 7) return phone;
  // 如果已脱敏直接返回
  if (phone.includes('*')) return phone;
  return `${phone.slice(0, 3)}****${phone.slice(-4)}`;
};

// ─── 漏斗图组件 ──────────────────────────────────────────────────────────────

function FunnelChart({ stages }: { stages: BanquetFunnelStage[] }) {
  const maxCount = Math.max(...stages.map((s) => s.count), 1);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {stages.map((s, i) => {
        const widthPct = Math.max(20, (s.count / maxCount) * 100);
        const color = FUNNEL_COLORS[i % FUNNEL_COLORS.length];
        return (
          <div key={s.stage}>
            <div style={{
              display: 'flex', justifyContent: 'space-between',
              alignItems: 'center', marginBottom: 4,
            }}>
              <span style={{ fontSize: 12, color: '#aaa', width: 52 }}>{s.label}</span>
              <span style={{ fontSize: 12, fontWeight: 600, color: '#fff' }}>{s.count}</span>
              {i > 0 && (
                <span style={{
                  fontSize: 10, padding: '1px 6px', borderRadius: 4,
                  background: `${color}20`, color,
                }}>
                  {s.conversion_rate.toFixed(1)}%
                </span>
              )}
              {i === 0 && <span style={{ fontSize: 10, color: '#555' }}>基准</span>}
            </div>
            <div style={{ width: '100%', display: 'flex', justifyContent: 'center' }}>
              <div style={{
                width: `${widthPct}%`, height: 30, borderRadius: 4,
                background: `linear-gradient(90deg, ${color}, ${color}88)`,
                transition: 'width 0.5s ease',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>
                <span style={{ fontSize: 11, fontWeight: 700, color: '#fff' }}>{s.count}</span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── 阶段徽章 ────────────────────────────────────────────────────────────────

function StageBadge({ stage }: { stage: string }) {
  const style = STAGE_BADGE[stage] || { bg: '#33333320', color: '#999' };
  return (
    <span style={{
      padding: '2px 10px', borderRadius: 10, fontSize: 11, fontWeight: 600,
      background: style.bg, color: style.color,
    }}>
      {STAGE_LABELS[stage] || stage}
    </span>
  );
}

// ─── KPI 卡片 ────────────────────────────────────────────────────────────────

interface KpiCardProps {
  label: string;
  value: string;
  unit?: string;
  color: string;
  loading?: boolean;
}

function KpiCard({ label, value, unit, color, loading }: KpiCardProps) {
  return (
    <div style={{
      background: '#112228', borderRadius: 8, padding: '16px 20px',
      borderLeft: `3px solid ${color}`, minHeight: 90,
      display: 'flex', flexDirection: 'column', justifyContent: 'center',
    }}>
      <div style={{ fontSize: 12, color: '#888', marginBottom: 6 }}>{label}</div>
      {loading ? (
        <Spin size="small" />
      ) : (
        <div style={{ fontSize: 26, fontWeight: 'bold', color: '#fff', lineHeight: 1.2 }}>
          {value}
          {unit && <span style={{ fontSize: 13, color: '#888', marginLeft: 4 }}>{unit}</span>}
        </div>
      )}
    </div>
  );
}

// ─── 详情抽屉 ────────────────────────────────────────────────────────────────

interface DetailDrawerProps {
  contractId: string | null;
  onClose: () => void;
  onStageAdvanced: () => void;
}

function DetailDrawer({ contractId, onClose, onStageAdvanced }: DetailDrawerProps) {
  const [detail, setDetail] = useState<BanquetDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [advancing, setAdvancing] = useState(false);

  useEffect(() => {
    if (!contractId) { setDetail(null); return; }
    setLoading(true);
    fetchBanquetDetail(contractId)
      .then(setDetail)
      .catch(() => message.error('加载详情失败'))
      .finally(() => setLoading(false));
  }, [contractId]);

  const handleAdvance = async () => {
    if (!detail) return;
    const nextStage = NEXT_STAGE[detail.stage];
    if (!nextStage) return;
    setAdvancing(true);
    try {
      await advanceBanquetStage(detail.contract_id, nextStage);
      message.success(`已推进至：${STAGE_LABELS[nextStage] || nextStage}`);
      onStageAdvanced();
      onClose();
    } catch {
      message.error('推进阶段失败，请重试');
    } finally {
      setAdvancing(false);
    }
  };

  const infoRow = (label: string, value: React.ReactNode) => (
    <div style={{ display: 'flex', marginBottom: 10 }}>
      <span style={{ width: 90, color: '#888', fontSize: 13, flexShrink: 0 }}>{label}</span>
      <span style={{ color: '#fff', fontSize: 13 }}>{value}</span>
    </div>
  );

  return (
    <Drawer
      open={!!contractId}
      onClose={onClose}
      width={400}
      placement="right"
      title={
        <span style={{ color: '#fff', fontSize: 15 }}>
          宴会详情
          {detail && (
            <span style={{ marginLeft: 12 }}>
              <StageBadge stage={detail.stage} />
            </span>
          )}
        </span>
      }
      styles={{
        body: { background: '#1a2a33', padding: 20 },
        header: { background: '#1a2a33', borderBottom: '1px solid #2a3a43' },
        mask: { background: 'rgba(0,0,0,0.4)' },
      }}
      closeIcon={<span style={{ color: '#aaa' }}>×</span>}
      footer={
        detail && NEXT_STAGE[detail.stage] ? (
          <div style={{ padding: '12px 0', display: 'flex', gap: 8 }}>
            <Button
              type="primary"
              loading={advancing}
              onClick={handleAdvance}
              style={{ flex: 1, background: '#FF6B35', borderColor: '#FF6B35' }}
            >
              推进至「{STAGE_LABELS[NEXT_STAGE[detail.stage]]}」
            </Button>
            <Button onClick={onClose} style={{ background: '#0B1A20', borderColor: '#2a3a43', color: '#aaa' }}>
              关闭
            </Button>
          </div>
        ) : (
          <div style={{ padding: '12px 0' }}>
            <Button block onClick={onClose} style={{ background: '#0B1A20', borderColor: '#2a3a43', color: '#aaa' }}>
              关闭
            </Button>
          </div>
        )
      }
    >
      {loading ? (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin />
        </div>
      ) : detail ? (
        <div>
          {/* 客户信息 */}
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 11, color: '#FF6B35', letterSpacing: 1, marginBottom: 10, textTransform: 'uppercase' }}>
              客户信息
            </div>
            {infoRow('客户姓名', detail.customer_name)}
            {infoRow('手机号码', maskPhone(detail.customer_phone))}
            {detail.company_name && infoRow('公司名称', detail.company_name)}
            {detail.source && infoRow('来源渠道', SOURCE_OPTIONS.find(s => s.value === detail.source)?.label || detail.source)}
          </div>

          <Divider style={{ borderColor: '#2a3a43', margin: '12px 0' }} />

          {/* 宴会信息 */}
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 11, color: '#FF6B35', letterSpacing: 1, marginBottom: 10, textTransform: 'uppercase' }}>
              宴会信息
            </div>
            {infoRow('活动类型', EVENT_TYPE_OPTIONS.find(e => e.value === detail.event_type)?.label || detail.event_type)}
            {infoRow('宴会日期', detail.banquet_date)}
            {infoRow('预计桌数', `${detail.table_count} 桌`)}
            {detail.guest_count != null && infoRow('预计宾客', `${detail.guest_count} 人`)}
            {detail.budget_fen != null && infoRow('预计预算', fmtMoney(detail.budget_fen))}
          </div>

          {/* 报价明细（已签约或以上阶段显示） */}
          {(detail.total_amount_fen > 0) && (
            <>
              <Divider style={{ borderColor: '#2a3a43', margin: '12px 0' }} />
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 11, color: '#FF6B35', letterSpacing: 1, marginBottom: 10, textTransform: 'uppercase' }}>
                  报价明细
                </div>
                {detail.menu_name && infoRow('套餐名称', detail.menu_name)}
                {detail.per_table_price_fen != null && infoRow('桌均价格', fmtMoney(detail.per_table_price_fen))}
                {infoRow('合同金额', <span style={{ color: '#FF6B35', fontWeight: 700 }}>{fmtMoney(detail.total_amount_fen)}</span>)}
                {detail.deposit_fen != null && infoRow('已收定金', fmtMoney(detail.deposit_fen))}
                {detail.paid_fen != null && infoRow('已付总额', fmtMoney(detail.paid_fen))}
              </div>
            </>
          )}

          {/* 备注 */}
          {detail.notes && (
            <>
              <Divider style={{ borderColor: '#2a3a43', margin: '12px 0' }} />
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 11, color: '#888', marginBottom: 6 }}>备注</div>
                <div style={{ color: '#ccc', fontSize: 13, lineHeight: 1.6 }}>{detail.notes}</div>
              </div>
            </>
          )}

          {/* 时间轴 */}
          {detail.timeline && detail.timeline.length > 0 && (
            <>
              <Divider style={{ borderColor: '#2a3a43', margin: '12px 0' }} />
              <div>
                <div style={{ fontSize: 11, color: '#FF6B35', letterSpacing: 1, marginBottom: 12, textTransform: 'uppercase' }}>
                  推进记录
                </div>
                <Timeline
                  items={detail.timeline.map((t) => ({
                    color: '#FF6B35',
                    children: (
                      <div>
                        <div style={{ fontSize: 12, color: '#aaa', marginBottom: 2 }}>{t.time}</div>
                        <div style={{ fontSize: 13, color: '#fff', fontWeight: 600 }}>
                          {STAGE_LABELS[t.stage] || t.label}
                        </div>
                        {t.operator && (
                          <div style={{ fontSize: 12, color: '#888' }}>操作人：{t.operator}</div>
                        )}
                        {t.note && (
                          <div style={{ fontSize: 12, color: '#aaa', marginTop: 2 }}>{t.note}</div>
                        )}
                      </div>
                    ),
                  }))}
                />
              </div>
            </>
          )}

          {/* 无时间轴时显示创建时间 */}
          {(!detail.timeline || detail.timeline.length === 0) && (
            <>
              <Divider style={{ borderColor: '#2a3a43', margin: '12px 0' }} />
              <div style={{ fontSize: 12, color: '#555' }}>
                创建于 {detail.created_at}
                {detail.updated_at && detail.updated_at !== detail.created_at && (
                  <span>，最后更新 {detail.updated_at}</span>
                )}
              </div>
            </>
          )}
        </div>
      ) : (
        <div style={{ textAlign: 'center', color: '#555', paddingTop: 60 }}>暂无数据</div>
      )}
    </Drawer>
  );
}

// ─── 新增线索弹窗 ─────────────────────────────────────────────────────────────

interface NewLeadModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

function NewLeadModal({ open, onClose, onCreated }: NewLeadModalProps) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

  const handleOk = async () => {
    let values: Record<string, unknown>;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    setLoading(true);
    try {
      const eventDate = values.event_date
        ? (values.event_date as ReturnType<typeof dayjs>).format('YYYY-MM-DD')
        : '';
      await createBanquetLead({
        customer_name: values.customer_name as string,
        company_name: (values.company_name as string) || '',
        phone: values.phone as string,
        event_type: (values.event_type as string) || 'other',
        event_date: eventDate,
        guest_count: (values.guest_count as number) || 10,
        estimated_budget_fen: Math.round(((values.budget_yuan as number) || 0) * 100),
        source: (values.source as string) || 'walk_in',
        notes: (values.notes as string) || '',
      });
      message.success('线索已录入');
      form.resetFields();
      onCreated();
      onClose();
    } catch {
      message.error('录入失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  const labelStyle: React.CSSProperties = { color: '#ccc', fontSize: 13 };
  const inputStyle: React.CSSProperties = {
    background: '#0B1A20', borderColor: '#2a3a43', color: '#fff',
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      onOk={handleOk}
      confirmLoading={loading}
      title={<span style={{ color: '#fff' }}>+ 录入新宴会线索</span>}
      okText="提交线索"
      cancelText="取消"
      width={520}
      okButtonProps={{ style: { background: '#FF6B35', borderColor: '#FF6B35' } }}
      styles={{
        content: { background: '#1a2a33', padding: 0 },
        header: { background: '#1a2a33', borderBottom: '1px solid #2a3a43', padding: '16px 24px' },
        body: { background: '#1a2a33', padding: '20px 24px' },
        footer: { background: '#1a2a33', borderTop: '1px solid #2a3a43' },
      }}
    >
      <Form form={form} layout="vertical" requiredMark={false}>
        {/* 客户信息 */}
        <div style={{ fontSize: 11, color: '#FF6B35', letterSpacing: 1, marginBottom: 12 }}>
          客户信息
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Form.Item
            name="customer_name"
            label={<span style={labelStyle}>客户姓名</span>}
            rules={[{ required: true, message: '请输入客户姓名' }]}
          >
            <Input placeholder="如：张先生" style={inputStyle} />
          </Form.Item>
          <Form.Item name="company_name" label={<span style={labelStyle}>公司名称（选填）</span>}>
            <Input placeholder="如：某某集团" style={inputStyle} />
          </Form.Item>
        </div>
        <Form.Item
          name="phone"
          label={<span style={labelStyle}>手机号码</span>}
          rules={[
            { required: true, message: '请输入手机号' },
            { pattern: /^1[3-9]\d{9}$/, message: '手机号格式不正确' },
          ]}
        >
          <Input placeholder="138xxxxxxxx" style={inputStyle} />
        </Form.Item>

        <Divider style={{ borderColor: '#2a3a43', margin: '8px 0 16px' }} />

        {/* 宴会信息 */}
        <div style={{ fontSize: 11, color: '#FF6B35', letterSpacing: 1, marginBottom: 12 }}>
          宴会信息
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Form.Item
            name="event_type"
            label={<span style={labelStyle}>活动类型</span>}
            rules={[{ required: true, message: '请选择类型' }]}
          >
            <Select
              options={EVENT_TYPE_OPTIONS}
              placeholder="选择活动类型"
              style={{ background: '#0B1A20' }}
              dropdownStyle={{ background: '#1a2a33' }}
            />
          </Form.Item>
          <Form.Item
            name="event_date"
            label={<span style={labelStyle}>宴会日期</span>}
            rules={[{ required: true, message: '请选择日期' }]}
          >
            <DatePicker
              style={{ width: '100%', ...inputStyle }}
              format="YYYY-MM-DD"
            />
          </Form.Item>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Form.Item
            name="guest_count"
            label={<span style={labelStyle}>预计宾客人数</span>}
            rules={[{ required: true, message: '请输入宾客数' }]}
            initialValue={100}
          >
            <InputNumber min={1} style={{ width: '100%', ...inputStyle }} addonAfter="人" />
          </Form.Item>
          <Form.Item
            name="budget_yuan"
            label={<span style={labelStyle}>预算（元）</span>}
            initialValue={0}
          >
            <InputNumber min={0} style={{ width: '100%', ...inputStyle }} addonBefore="¥" />
          </Form.Item>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Form.Item
            name="source"
            label={<span style={labelStyle}>来源渠道</span>}
            initialValue="walk_in"
          >
            <Select
              options={SOURCE_OPTIONS}
              dropdownStyle={{ background: '#1a2a33' }}
            />
          </Form.Item>
        </div>
        <Form.Item name="notes" label={<span style={labelStyle}>备注（选填）</span>}>
          <Input.TextArea
            rows={3}
            placeholder="其他说明..."
            style={{ ...inputStyle, resize: 'none' }}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export function BanquetBoardPage() {
  // — 数据状态
  const [funnel, setFunnel] = useState<BanquetFunnelData | null>(null);
  const [kpis, setKpis] = useState<BanquetKPIs | null>(null);
  const [list, setList] = useState<BanquetListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loadingFunnel, setLoadingFunnel] = useState(false);
  const [loadingKpis, setLoadingKpis] = useState(false);
  const [loadingList, setLoadingList] = useState(false);

  // — 筛选 & 分页
  const [stageFilter, setStageFilter] = useState<StageFilter>('all');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 20;

  // — UI 状态
  const [selectedContractId, setSelectedContractId] = useState<string | null>(null);
  const [newLeadOpen, setNewLeadOpen] = useState(false);

  // ─ 数据加载

  const loadFunnelAndKpis = useCallback(() => {
    setLoadingFunnel(true);
    fetchBanquetFunnel()
      .then(setFunnel)
      .catch(() => {/* 保持 null，漏斗图显示空 */})
      .finally(() => setLoadingFunnel(false));

    setLoadingKpis(true);
    fetchBanquetKPIs()
      .then(setKpis)
      .catch(() => {})
      .finally(() => setLoadingKpis(false));
  }, []);

  const loadList = useCallback(() => {
    setLoadingList(true);
    fetchBanquetList({
      stage: stageFilter === 'all' ? undefined : stageFilter,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      page,
      size: PAGE_SIZE,
    })
      .then((res) => {
        setList(res.items);
        setTotal(res.total);
      })
      .catch(() => message.error('加载宴会列表失败'))
      .finally(() => setLoadingList(false));
  }, [stageFilter, dateFrom, dateTo, page]);

  useEffect(() => {
    loadFunnelAndKpis();
  }, [loadFunnelAndKpis]);

  useEffect(() => {
    setPage(1);
  }, [stageFilter, dateFrom, dateTo]);

  useEffect(() => {
    loadList();
  }, [loadList]);

  // ─ 分页变更
  const handleTableChange = (pagination: TablePaginationConfig) => {
    setPage(pagination.current || 1);
  };

  // ─ 表格列定义
  const columns: ColumnsType<BanquetListItem> = [
    {
      title: '客户',
      key: 'customer',
      render: (_, r) => (
        <div>
          <div style={{ fontWeight: 600, color: '#fff', fontSize: 13 }}>{r.customer_name}</div>
          <div style={{ fontSize: 11, color: '#555', marginTop: 2 }}>{maskPhone(r.customer_phone)}</div>
        </div>
      ),
    },
    {
      title: '门店',
      dataIndex: 'store_name',
      key: 'store_name',
      render: (v) => <span style={{ color: '#aaa', fontSize: 12 }}>{v || '—'}</span>,
    },
    {
      title: '宴会日期',
      dataIndex: 'banquet_date',
      key: 'banquet_date',
      render: (v) => <span style={{ color: '#aaa', fontSize: 12 }}>{v}</span>,
      sorter: (a, b) => a.banquet_date.localeCompare(b.banquet_date),
    },
    {
      title: '桌数',
      dataIndex: 'table_count',
      key: 'table_count',
      align: 'right',
      render: (v) => <span style={{ color: '#ccc', fontSize: 12 }}>{v} 桌</span>,
      sorter: (a, b) => a.table_count - b.table_count,
    },
    {
      title: '合同金额',
      dataIndex: 'total_amount_fen',
      key: 'total_amount_fen',
      align: 'right',
      render: (v) => (
        <span style={{ fontWeight: 700, color: '#FF6B35', fontSize: 13 }}>
          {v > 0 ? fmtMoney(v) : <span style={{ color: '#555' }}>—</span>}
        </span>
      ),
      sorter: (a, b) => a.total_amount_fen - b.total_amount_fen,
    },
    {
      title: '阶段',
      dataIndex: 'stage',
      key: 'stage',
      align: 'center',
      render: (v) => <StageBadge stage={v} />,
    },
    {
      title: '操作',
      key: 'actions',
      align: 'center',
      render: (_, r) => (
        <Space size={4}>
          <Button
            size="small"
            onClick={() => setSelectedContractId(r.contract_id)}
            style={{ background: '#0B1A20', borderColor: '#2a3a43', color: '#aaa', fontSize: 11 }}
          >
            查看详情
          </Button>
          {NEXT_STAGE[r.stage] && (
            <Tooltip title={`推进至：${STAGE_LABELS[NEXT_STAGE[r.stage]]}`}>
              <Button
                size="small"
                type="primary"
                onClick={async () => {
                  try {
                    await advanceBanquetStage(r.contract_id, NEXT_STAGE[r.stage]);
                    message.success(`已推进至：${STAGE_LABELS[NEXT_STAGE[r.stage]]}`);
                    loadList();
                    loadFunnelAndKpis();
                  } catch {
                    message.error('操作失败');
                  }
                }}
                style={{ background: '#FF6B35', borderColor: '#FF6B35', fontSize: 11 }}
              >
                更新状态
              </Button>
            </Tooltip>
          )}
        </Space>
      ),
    },
  ];

  // ─ KPI 值
  const kpiCards = kpis
    ? [
        {
          label: '本月宴会数',
          value: String(kpis.month_banquet_count),
          unit: '场',
          color: '#FF6B35',
        },
        {
          label: '签约率',
          value: `${(kpis.sign_rate * 100).toFixed(1)}%`,
          color: '#185FA5',
        },
        {
          label: '平均桌均价',
          value: fmtMoney(kpis.avg_per_table_fen),
          color: '#0F6E56',
        },
        {
          label: '本月总营收',
          value: fmtMoney(kpis.month_revenue_fen),
          color: '#BA7517',
        },
      ]
    : Array(4).fill({ label: '', value: '', color: '#444' });

  return (
    <div style={{ minHeight: '100%' }}>
      {/* ─ 标题栏 */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginBottom: 20,
      }}>
        <h2 style={{ margin: 0, fontSize: 20, color: '#fff' }}>宴会管理看板</h2>
        <Button
          type="primary"
          onClick={() => setNewLeadOpen(true)}
          style={{ background: '#FF6B35', borderColor: '#FF6B35', fontWeight: 600 }}
        >
          + 新增线索
        </Button>
      </div>

      {/* ─ Section 1：月度 KPI 卡片 */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)',
        gap: 16, marginBottom: 24,
      }}>
        {kpiCards.map((k, i) => (
          <KpiCard
            key={i}
            label={k.label}
            value={k.value}
            unit={(k as { unit?: string }).unit}
            color={k.color}
            loading={loadingKpis}
          />
        ))}
      </div>

      {/* ─ Section 2 + 3：漏斗 + 列表 */}
      <div style={{ display: 'grid', gridTemplateColumns: '340px 1fr', gap: 16, marginBottom: 16 }}>
        {/* 销售漏斗 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 15, color: '#fff' }}>
            销售漏斗
            {funnel && (
              <span style={{
                fontSize: 11, marginLeft: 8, padding: '2px 8px', borderRadius: 10,
                background: '#FF6B3520', color: '#FF6B35', fontWeight: 600,
              }}>
                总转化 {funnel.overall_conversion.toFixed(1)}%
              </span>
            )}
          </h3>

          {loadingFunnel ? (
            <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
          ) : funnel ? (
            <>
              <FunnelChart stages={funnel.stages} />
              <div style={{
                marginTop: 16, padding: 12, borderRadius: 6, background: '#0B1A20',
                fontSize: 12, color: '#888', lineHeight: 1.8,
              }}>
                <div>总线索：<span style={{ color: '#fff', fontWeight: 600 }}>{funnel.total_leads}</span></div>
                <div>最终完成：<span style={{ color: '#fff', fontWeight: 600 }}>
                  {funnel.stages.find((s) => s.stage === 'completed')?.count || 0}
                </span></div>
                <div>整体转化：<span style={{ color: '#FF6B35', fontWeight: 600 }}>
                  {funnel.overall_conversion.toFixed(1)}%
                </span></div>
              </div>
            </>
          ) : (
            <div style={{ color: '#555', textAlign: 'center', padding: 40 }}>暂无漏斗数据</div>
          )}
        </div>

        {/* 宴会列表 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          {/* 列表工具栏 */}
          <div style={{
            display: 'flex', justifyContent: 'space-between',
            alignItems: 'flex-start', marginBottom: 14, flexWrap: 'wrap', gap: 8,
          }}>
            <h3 style={{ margin: 0, fontSize: 15, color: '#fff' }}>
              宴会列表
              {total > 0 && (
                <span style={{ fontSize: 12, color: '#888', marginLeft: 8, fontWeight: 400 }}>
                  共 {total} 条
                </span>
              )}
            </h3>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {/* 状态筛选按钮组 */}
              <div style={{ display: 'flex', gap: 4 }}>
                {(Object.keys(STAGE_LABELS) as StageFilter[]).map((s) => (
                  <button
                    key={s}
                    onClick={() => setStageFilter(s)}
                    style={{
                      padding: '3px 10px', borderRadius: 4, border: 'none', cursor: 'pointer',
                      fontSize: 11, fontWeight: 600,
                      background: stageFilter === s ? '#FF6B35' : '#0B1A20',
                      color: stageFilter === s ? '#fff' : '#888',
                      transition: 'all 0.2s',
                    }}
                  >
                    {STAGE_LABELS[s]}
                  </button>
                ))}
              </div>
              {/* 日期范围 */}
              <DatePicker
                placeholder="开始日期"
                size="small"
                style={{ width: 110, background: '#0B1A20', borderColor: '#2a3a43' }}
                onChange={(d) => setDateFrom(d ? d.format('YYYY-MM-DD') : '')}
              />
              <DatePicker
                placeholder="结束日期"
                size="small"
                style={{ width: 110, background: '#0B1A20', borderColor: '#2a3a43' }}
                onChange={(d) => setDateTo(d ? d.format('YYYY-MM-DD') : '')}
              />
            </div>
          </div>

          {/* 表格 */}
          <Table<BanquetListItem>
            columns={columns}
            dataSource={list}
            rowKey="contract_id"
            loading={loadingList}
            pagination={{
              current: page,
              pageSize: PAGE_SIZE,
              total,
              showSizeChanger: false,
              showTotal: (t) => `共 ${t} 条`,
              style: { marginTop: 12 },
            }}
            onChange={handleTableChange}
            size="small"
            style={{ fontSize: 13 }}
            scroll={{ x: 700 }}
            locale={{ emptyText: <span style={{ color: '#555' }}>暂无宴会数据</span> }}
            rowHoverable={true}
          />
        </div>
      </div>

      {/* ─ Section 4：详情抽屉 */}
      <DetailDrawer
        contractId={selectedContractId}
        onClose={() => setSelectedContractId(null)}
        onStageAdvanced={() => {
          loadList();
          loadFunnelAndKpis();
        }}
      />

      {/* ─ 新增线索弹窗 */}
      <NewLeadModal
        open={newLeadOpen}
        onClose={() => setNewLeadOpen(false)}
        onCreated={() => {
          loadList();
          loadFunnelAndKpis();
        }}
      />

      {/* 全局深色主题覆盖（仅作用于本页面内的 antd 组件） */}
      <style>{`
        /* 表格 */
        .ant-table { background: transparent !important; }
        .ant-table-thead > tr > th {
          background: #0B1A20 !important;
          color: #888 !important;
          font-size: 11px !important;
          border-bottom: 1px solid #1a2a33 !important;
        }
        .ant-table-tbody > tr > td {
          background: transparent !important;
          border-bottom: 1px solid #1a2a33 !important;
        }
        .ant-table-tbody > tr:hover > td {
          background: #0d2030 !important;
        }
        .ant-table-wrapper .ant-pagination { color: #888; }
        .ant-pagination-item a { color: #888; }
        .ant-pagination-item-active { border-color: #FF6B35 !important; }
        .ant-pagination-item-active a { color: #FF6B35 !important; }
        /* DatePicker */
        .ant-picker { background: #0B1A20 !important; border-color: #2a3a43 !important; color: #fff !important; }
        .ant-picker input { color: #ccc !important; }
        .ant-picker-suffix { color: #555 !important; }
        /* Spin */
        .ant-spin-dot-item { background-color: #FF6B35 !important; }
        /* Timeline */
        .ant-timeline-item-tail { border-color: #2a3a43 !important; }
        /* Select dropdown (form inside Modal uses portal) */
        .ant-select-selector { background: #0B1A20 !important; border-color: #2a3a43 !important; color: #ccc !important; }
        .ant-input, .ant-input-number, .ant-input-number-input {
          background: #0B1A20 !important; border-color: #2a3a43 !important; color: #fff !important;
        }
        .ant-input::placeholder, .ant-input-number-input::placeholder { color: #444 !important; }
        .ant-input-number-group-addon { background: #0B1A20 !important; border-color: #2a3a43 !important; color: #888 !important; }
        .ant-picker-panel-container { background: #1a2a33 !important; }
        .ant-picker-cell-in-view .ant-picker-cell-inner { color: #ccc !important; }
        .ant-picker-header, .ant-picker-header button { color: #ccc !important; }
        .ant-form-item-label > label { color: #ccc !important; }
      `}</style>
    </div>
  );
}
