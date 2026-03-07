/**
 * MemberSystemPage — 会员档案管理
 *
 * 功能：
 *   - 分页浏览私域会员（按 customer_id 搜索，按生命周期状态/RFM等级过滤）
 *   - 内联编辑生日（birth_date），使 birthday_reminder Celery 任务生效
 *   - 显示 RFM 等级、生命周期状态（彩色 Badge）、企微 openid、消费金额
 *   - 一键触发指定旅程（birthday_greeting / anniversary_greeting / dormant_wakeup）
 */
import React, { useEffect, useState, useCallback } from 'react';
import { Input, Select, DatePicker, message } from 'antd';
import {
  SearchOutlined, ReloadOutlined, EditOutlined, CheckOutlined,
  CloseOutlined, SendOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import apiClient from '../services/api';
import { ZCard, ZBadge, ZButton, ZSkeleton, ZSelect, ZTable } from '../design-system/components';
import type { ZTableColumn } from '../design-system/components/ZTable';
import styles from './MemberSystemPage.module.css';

const { Option } = Select;

// ── Types ─────────────────────────────────────────────────────────────────────

interface Member {
  customer_id:    string;
  rfm_level:      string;
  lifecycle_state: string | null;
  birth_date:     string | null;
  wechat_openid:  string | null;
  channel_source: string | null;
  recency_days:   number;
  frequency:      number;
  monetary_yuan:  number;
  last_visit:     string | null;
  is_active:      boolean;
  joined_at:      string | null;
}

interface ListResponse {
  total:     number;
  page:      number;
  page_size: number;
  members:   Member[];
}

// ── Constants ─────────────────────────────────────────────────────────────────

const STORE_OPTIONS = ['S001', 'S002', 'S003'];

const LIFECYCLE_BADGE_TYPE: Record<string, 'default' | 'info' | 'warning' | 'success' | 'critical' | 'accent'> = {
  lead:                 'default',
  registered:           'info',
  first_order_pending:  'warning',
  repeat:               'success',
  high_frequency:       'accent',
  vip:                  'accent',
  at_risk:              'warning',
  dormant:              'critical',
  lost:                 'default',
};
const LIFECYCLE_LABEL: Record<string, string> = {
  lead: '潜客', registered: '已注册', first_order_pending: '待首单',
  repeat: '复购', high_frequency: '高频', vip: 'VIP',
  at_risk: '风险', dormant: '沉睡', lost: '流失',
};
const RFM_BADGE_TYPE: Record<string, 'warning' | 'info' | 'success' | 'default'> = {
  S1: 'warning', S2: 'info', S3: 'success', S4: 'warning', S5: 'default',
};

const JOURNEY_OPTIONS = [
  { value: 'birthday_greeting',    label: '生日祝福' },
  { value: 'anniversary_greeting', label: '入会周年' },
  { value: 'dormant_wakeup',       label: '沉睡唤醒' },
  { value: 'member_activation',    label: '入会激活' },
];

const lcSelectOptions = Object.entries(LIFECYCLE_LABEL).map(([k, v]) => ({ value: k, label: v }));
const rfmSelectOptions = ['S1', 'S2', 'S3', 'S4', 'S5'].map(r => ({ value: r, label: r }));
const storeSelectOptions = STORE_OPTIONS.map(s => ({ value: s, label: s }));

// ── Main Component ────────────────────────────────────────────────────────────

const MemberSystemPage: React.FC = () => {
  const storeId = localStorage.getItem('store_id') || 'S001';

  const [selectedStore, setSelectedStore] = useState(storeId);
  const [search, setSearch]       = useState('');
  const [lcFilter, setLcFilter]   = useState<string | undefined>();
  const [rfmFilter, setRfmFilter] = useState<string | undefined>();
  const [page, setPage]           = useState(1);
  const [data, setData]           = useState<ListResponse | null>(null);
  const [loading, setLoading]     = useState(false);

  const [editingKey, setEditingKey]       = useState<string | null>(null);
  const [editBirthDate, setEditBirthDate] = useState<dayjs.Dayjs | null>(null);
  const [triggerKey, setTriggerKey]           = useState<string | null>(null);
  const [selectedJourney, setSelectedJourney] = useState<string>('birthday_greeting');

  const fetchMembers = useCallback(async (p = page) => {
    setLoading(true);
    try {
      const params: Record<string, string | number> = { page: p, page_size: 20 };
      if (search)   params.search          = search;
      if (lcFilter) params.lifecycle_state = lcFilter;
      if (rfmFilter) params.rfm_level      = rfmFilter;

      const res = await apiClient.get(
        `/api/v1/private-domain/members/${selectedStore}/list`,
        { params },
      );
      setData(res.data);
    } catch {
      message.error('加载会员列表失败');
    } finally {
      setLoading(false);
    }
  }, [selectedStore, search, lcFilter, rfmFilter, page]);

  useEffect(() => { fetchMembers(1); setPage(1); }, [selectedStore, lcFilter, rfmFilter]);

  const handleSearch = () => { fetchMembers(1); setPage(1); };

  const saveBirthDate = async (customerId: string) => {
    try {
      await apiClient.patch(
        `/api/v1/private-domain/members/${selectedStore}/${customerId}`,
        { birth_date: editBirthDate ? editBirthDate.format('YYYY-MM-DD') : null },
      );
      message.success('生日已更新');
      setEditingKey(null);
      fetchMembers(page);
    } catch {
      message.error('更新失败');
    }
  };

  const triggerJourney = async (customerId: string, wechatOpenid: string | null) => {
    const journeyLabel = JOURNEY_OPTIONS.find(o => o.value === selectedJourney)?.label;
    if (!window.confirm(`触发「${journeyLabel}」旅程？`)) return;
    try {
      await apiClient.post(`/api/v1/private-domain/journeys/${selectedStore}/trigger-v2`, {
        customer_id:    customerId,
        journey_id:     selectedJourney,
        wechat_user_id: wechatOpenid ?? undefined,
      });
      message.success('旅程已触发');
      setTriggerKey(null);
    } catch {
      message.error('触发失败');
    }
  };

  const columns: ZTableColumn<Member>[] = [
    {
      key: 'customer_id',
      title: '客户ID',
      width: 120,
      render: (v: string) => <span className={styles.codeCell}>{v}</span>,
    },
    {
      key: 'rfm_level',
      title: 'RFM',
      width: 70,
      align: 'center',
      render: (v: string) => v
        ? <ZBadge type={RFM_BADGE_TYPE[v] || 'default'} text={v} />
        : <span className={styles.muted}>—</span>,
    },
    {
      key: 'lifecycle_state',
      title: '生命周期',
      width: 90,
      align: 'center',
      render: (v: string | null) => v
        ? <ZBadge type={LIFECYCLE_BADGE_TYPE[v] || 'default'} text={LIFECYCLE_LABEL[v] || v} />
        : <span className={styles.muted}>—</span>,
    },
    {
      key: 'birth_date',
      title: '生日',
      width: 180,
      render: (_: string | null, record: Member) => {
        const isEditing = editingKey === record.customer_id;
        if (isEditing) {
          return (
            <div className={styles.inlineEdit}>
              <DatePicker
                size="small"
                value={editBirthDate}
                onChange={setEditBirthDate}
                format="YYYY-MM-DD"
                placeholder="选择生日"
                allowClear
              />
              <button className={styles.iconBtn} onClick={() => saveBirthDate(record.customer_id)}>
                <CheckOutlined style={{ color: '#52c41a' }} />
              </button>
              <button className={styles.iconBtn} onClick={() => setEditingKey(null)}>
                <CloseOutlined style={{ color: '#cf1322' }} />
              </button>
            </div>
          );
        }
        return (
          <div className={styles.inlineEdit}>
            <span className={record.birth_date ? undefined : styles.muted}>
              {record.birth_date || '未设置'}
            </span>
            <button
              className={styles.iconBtn}
              title="设置生日（用于生日提醒）"
              onClick={() => {
                setEditingKey(record.customer_id);
                setEditBirthDate(record.birth_date ? dayjs(record.birth_date) : null);
              }}
            >
              <EditOutlined style={{ color: 'var(--text-secondary)' }} />
            </button>
          </div>
        );
      },
    },
    {
      key: 'wechat_openid',
      title: '企微ID',
      width: 130,
      render: (v: string | null) => v
        ? <span className={`${styles.muted} ${styles.ellipsis}`} title={v}>{v}</span>
        : <span className={styles.muted}>—</span>,
    },
    {
      key: 'frequency',
      title: '消费次数',
      width: 80,
      align: 'right',
    },
    {
      key: 'monetary_yuan',
      title: '消费金额',
      width: 100,
      align: 'right',
      render: (v: number) => `¥${v.toFixed(2)}`,
    },
    {
      key: 'recency_days',
      title: '最近到访',
      width: 90,
      align: 'right',
      render: (v: number) => v != null ? `${v}天前` : '—',
    },
    {
      key: 'customer_id' as any,
      title: '触发旅程',
      width: 190,
      render: (_: unknown, record: Member) => {
        const isTriggering = triggerKey === record.customer_id;
        if (isTriggering) {
          return (
            <div className={styles.inlineEdit}>
              <Select
                size="small"
                style={{ width: 110 }}
                value={selectedJourney}
                onChange={setSelectedJourney}
              >
                {JOURNEY_OPTIONS.map(o => (
                  <Option key={o.value} value={o.value}>{o.label}</Option>
                ))}
              </Select>
              <ZButton
                variant="primary"
                icon={<SendOutlined />}
                onClick={() => triggerJourney(record.customer_id, record.wechat_openid)}
              >
                发送
              </ZButton>
              <ZButton onClick={() => setTriggerKey(null)}>取消</ZButton>
            </div>
          );
        }
        return (
          <ZButton
            icon={<SendOutlined />}
            onClick={() => { setTriggerKey(record.customer_id); setSelectedJourney('birthday_greeting'); }}
          >
            触发旅程
          </ZButton>
        );
      },
    },
  ];

  const totalPages = Math.ceil((data?.total || 0) / 20);

  return (
    <ZCard
      title="会员档案管理"
      extra={
        <ZButton icon={<ReloadOutlined />} onClick={() => fetchMembers(page)}>
          刷新
        </ZButton>
      }
    >
      {/* Filter Bar */}
      <div className={styles.filterBar}>
        <ZSelect
          value={selectedStore}
          options={storeSelectOptions}
          onChange={v => { setSelectedStore(v as string); setPage(1); }}
          style={{ width: 100 }}
        />
        <Input
          placeholder="搜索客户ID"
          value={search}
          onChange={e => setSearch(e.target.value)}
          onPressEnter={handleSearch}
          suffix={<SearchOutlined style={{ cursor: 'pointer' }} onClick={handleSearch} />}
          style={{ width: 200 }}
          allowClear
        />
        <ZSelect
          value={lcFilter}
          options={[{ value: '', label: '全部状态' }, ...lcSelectOptions]}
          onChange={v => setLcFilter((v as string) || undefined)}
          style={{ width: 130 }}
        />
        <ZSelect
          value={rfmFilter}
          options={[{ value: '', label: 'RFM等级' }, ...rfmSelectOptions]}
          onChange={v => setRfmFilter((v as string) || undefined)}
          style={{ width: 100 }}
        />
      </div>

      {/* Table */}
      {loading ? (
        <ZSkeleton rows={6} block />
      ) : (
        <>
          <ZTable
            columns={columns}
            data={data?.members || []}
            rowKey="customer_id"
            emptyText="暂无会员数据"
          />

          {/* 分页 */}
          <div className={styles.pagination}>
            <span className={styles.paginationInfo}>
              共 {data?.total || 0} 位会员
            </span>
            <div className={styles.paginationBtns}>
              <ZButton
                disabled={page <= 1}
                onClick={() => { const p = page - 1; setPage(p); fetchMembers(p); }}
              >
                上一页
              </ZButton>
              <span className={styles.pageLabel}>第 {page} / {totalPages || 1} 页</span>
              <ZButton
                disabled={page >= totalPages}
                onClick={() => { const p = page + 1; setPage(p); fetchMembers(p); }}
              >
                下一页
              </ZButton>
            </div>
          </div>
        </>
      )}
    </ZCard>
  );
};

export default MemberSystemPage;
