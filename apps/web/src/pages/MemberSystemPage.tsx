/**
 * MemberSystemPage — 会员档案管理
 *
 * 功能：
 *   - 分页浏览私域会员（按 customer_id 搜索，按生命周期状态/RFM等级过滤）
 *   - 内联编辑生日（birth_date），使 birthday_reminder Celery 任务生效
 *   - 显示 RFM 等级、生命周期状态（彩色 Tag）、企微 openid、消费金额
 *   - 一键触发指定旅程（birthday_greeting / anniversary_greeting / dormant_wakeup）
 */
import React, { useEffect, useState, useCallback } from 'react';
import {
  Card, Table, Input, Select, Space, Tag, Button, DatePicker,
  Tooltip, message, Typography, Form, Popconfirm,
} from 'antd';
import {
  SearchOutlined, ReloadOutlined, EditOutlined, CheckOutlined,
  CloseOutlined, SendOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import apiClient from '../services/api';

const { Text } = Typography;
const { Option } = Select;

// ── Types ─────────────────────────────────────────────────────────────────────

interface Member {
  customer_id: string;
  rfm_level: string;
  lifecycle_state: string | null;
  birth_date: string | null;
  wechat_openid: string | null;
  channel_source: string | null;
  recency_days: number;
  frequency: number;
  monetary_yuan: number;
  last_visit: string | null;
  is_active: boolean;
  joined_at: string | null;
}

interface ListResponse {
  total: number;
  page: number;
  page_size: number;
  members: Member[];
}

// ── Constants ─────────────────────────────────────────────────────────────────

const STORE_OPTIONS = ['S001', 'S002', 'S003'];

const LIFECYCLE_COLOR: Record<string, string> = {
  lead: 'default', registered: 'blue', first_order_pending: 'gold',
  repeat: 'green', high_frequency: 'cyan', vip: 'purple',
  at_risk: 'orange', dormant: 'red', lost: 'default',
};
const LIFECYCLE_LABEL: Record<string, string> = {
  lead: '潜客', registered: '已注册', first_order_pending: '待首单',
  repeat: '复购', high_frequency: '高频', vip: 'VIP',
  at_risk: '风险', dormant: '沉睡', lost: '流失',
};
const RFM_COLOR: Record<string, string> = {
  S1: 'gold', S2: 'blue', S3: 'green', S4: 'orange', S5: 'default',
};

const JOURNEY_OPTIONS = [
  { value: 'birthday_greeting',    label: '生日祝福' },
  { value: 'anniversary_greeting', label: '入会周年' },
  { value: 'dormant_wakeup',       label: '沉睡唤醒' },
  { value: 'member_activation',    label: '入会激活' },
];

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

  // per-row edit state for birth_date
  const [editingKey, setEditingKey]       = useState<string | null>(null);
  const [editBirthDate, setEditBirthDate] = useState<dayjs.Dayjs | null>(null);

  // per-row journey trigger state
  const [triggerKey, setTriggerKey]           = useState<string | null>(null);
  const [selectedJourney, setSelectedJourney] = useState<string>('birthday_greeting');

  const fetchMembers = useCallback(async (p = page) => {
    setLoading(true);
    try {
      const params: Record<string, string | number> = {
        page: p, page_size: 20,
      };
      if (search) params.search = search;
      if (lcFilter) params.lifecycle_state = lcFilter;
      if (rfmFilter) params.rfm_level = rfmFilter;

      const res = await apiClient.get(
        `/private-domain/members/${selectedStore}/list`,
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
        `/private-domain/members/${selectedStore}/${customerId}`,
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
    try {
      await apiClient.post(`/private-domain/journeys/${selectedStore}/trigger-v2`, {
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

  const columns: ColumnsType<Member> = [
    {
      title: '客户ID',
      dataIndex: 'customer_id',
      width: 120,
      ellipsis: true,
      render: (v: string) => <Text code copyable={{ text: v }}>{v}</Text>,
    },
    {
      title: 'RFM',
      dataIndex: 'rfm_level',
      width: 70,
      render: (v: string) => <Tag color={RFM_COLOR[v] || 'default'}>{v || '—'}</Tag>,
    },
    {
      title: '生命周期',
      dataIndex: 'lifecycle_state',
      width: 90,
      render: (v: string | null) => v
        ? <Tag color={LIFECYCLE_COLOR[v] || 'default'}>{LIFECYCLE_LABEL[v] || v}</Tag>
        : <Text type="secondary">—</Text>,
    },
    {
      title: '生日',
      dataIndex: 'birth_date',
      width: 160,
      render: (_: string | null, record: Member) => {
        const isEditing = editingKey === record.customer_id;
        if (isEditing) {
          return (
            <Space>
              <DatePicker
                size="small"
                value={editBirthDate}
                onChange={setEditBirthDate}
                format="YYYY-MM-DD"
                placeholder="选择生日"
                allowClear
              />
              <Button
                type="link" size="small" icon={<CheckOutlined />}
                onClick={() => saveBirthDate(record.customer_id)}
              />
              <Button
                type="link" size="small" icon={<CloseOutlined />}
                onClick={() => setEditingKey(null)}
              />
            </Space>
          );
        }
        return (
          <Space>
            <Text>{record.birth_date || <Text type="secondary">未设置</Text>}</Text>
            <Tooltip title="设置生日（用于生日提醒）">
              <Button
                type="link" size="small" icon={<EditOutlined />}
                onClick={() => {
                  setEditingKey(record.customer_id);
                  setEditBirthDate(record.birth_date ? dayjs(record.birth_date) : null);
                }}
              />
            </Tooltip>
          </Space>
        );
      },
    },
    {
      title: '企微ID',
      dataIndex: 'wechat_openid',
      width: 130,
      ellipsis: true,
      render: (v: string | null) => v
        ? <Text type="secondary" ellipsis={{ tooltip: v }}>{v}</Text>
        : <Text type="secondary">—</Text>,
    },
    {
      title: '消费次数',
      dataIndex: 'frequency',
      width: 80,
      align: 'right',
    },
    {
      title: '消费金额',
      dataIndex: 'monetary_yuan',
      width: 100,
      align: 'right',
      render: (v: number) => `¥${v.toFixed(2)}`,
    },
    {
      title: '最近到访',
      dataIndex: 'recency_days',
      width: 90,
      align: 'right',
      render: (v: number) => v != null ? `${v}天前` : '—',
    },
    {
      title: '触发旅程',
      key: 'actions',
      width: 180,
      render: (_: unknown, record: Member) => {
        const isTriggering = triggerKey === record.customer_id;
        if (isTriggering) {
          return (
            <Space>
              <Select
                size="small" style={{ width: 110 }}
                value={selectedJourney}
                onChange={setSelectedJourney}
              >
                {JOURNEY_OPTIONS.map(o => (
                  <Option key={o.value} value={o.value}>{o.label}</Option>
                ))}
              </Select>
              <Popconfirm
                title={`触发「${JOURNEY_OPTIONS.find(o => o.value === selectedJourney)?.label}」旅程？`}
                onConfirm={() => triggerJourney(record.customer_id, record.wechat_openid)}
                okText="确认" cancelText="取消"
              >
                <Button type="primary" size="small" icon={<SendOutlined />}>发送</Button>
              </Popconfirm>
              <Button size="small" onClick={() => setTriggerKey(null)}>取消</Button>
            </Space>
          );
        }
        return (
          <Button
            size="small" icon={<SendOutlined />}
            onClick={() => { setTriggerKey(record.customer_id); setSelectedJourney('birthday_greeting'); }}
          >
            触发旅程
          </Button>
        );
      },
    },
  ];

  return (
    <Card
      title="会员档案管理"
      extra={
        <Button icon={<ReloadOutlined />} onClick={() => fetchMembers(page)}>
          刷新
        </Button>
      }
    >
      {/* Filter Bar */}
      <Space wrap style={{ marginBottom: 16 }}>
        <Select
          value={selectedStore}
          onChange={v => { setSelectedStore(v); setPage(1); }}
          style={{ width: 100 }}
        >
          {STORE_OPTIONS.map(s => <Option key={s} value={s}>{s}</Option>)}
        </Select>

        <Input
          placeholder="搜索客户ID"
          value={search}
          onChange={e => setSearch(e.target.value)}
          onPressEnter={handleSearch}
          suffix={<SearchOutlined style={{ cursor: 'pointer' }} onClick={handleSearch} />}
          style={{ width: 200 }}
          allowClear
        />

        <Select
          placeholder="生命周期状态"
          value={lcFilter}
          onChange={setLcFilter}
          allowClear
          style={{ width: 130 }}
        >
          {Object.entries(LIFECYCLE_LABEL).map(([k, v]) => (
            <Option key={k} value={k}><Tag color={LIFECYCLE_COLOR[k]}>{v}</Tag></Option>
          ))}
        </Select>

        <Select
          placeholder="RFM等级"
          value={rfmFilter}
          onChange={setRfmFilter}
          allowClear
          style={{ width: 100 }}
        >
          {['S1', 'S2', 'S3', 'S4', 'S5'].map(r => (
            <Option key={r} value={r}><Tag color={RFM_COLOR[r]}>{r}</Tag></Option>
          ))}
        </Select>
      </Space>

      <Table<Member>
        rowKey="customer_id"
        columns={columns}
        dataSource={data?.members || []}
        loading={loading}
        size="small"
        scroll={{ x: 1100 }}
        pagination={{
          current: page,
          pageSize: 20,
          total: data?.total || 0,
          showTotal: t => `共 ${t} 位会员`,
          onChange: (p) => { setPage(p); fetchMembers(p); },
          showSizeChanger: false,
        }}
      />
    </Card>
  );
};

export default MemberSystemPage;
