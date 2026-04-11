/**
 * StaffingTemplatePage -- 门店编制模板管理
 * 域H . 组织人事 . 编制模板维护
 *
 * 功能：
 *   1. 顶部 Summary 卡片（按店型汇总）
 *   2. ProTable 全 CRUD（筛选/新增/编辑/删除）
 *   3. 复制模板（跨店型）
 *   4. 批量导入（占位）
 *
 * API: tx-org :8012
 */

import { useEffect, useRef, useState } from 'react';
import {
  ActionType,
  ModalForm,
  ProColumns,
  ProFormDigit,
  ProFormSelect,
  ProFormSwitch,
  ProFormTextArea,
  ProTable,
  StatisticCard,
} from '@ant-design/pro-components';
import {
  Button,
  Col,
  message,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Tag,
} from 'antd';
import { CopyOutlined, PlusOutlined, UploadOutlined } from '@ant-design/icons';
import { txFetch } from '../../api/client';

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  类型
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

interface StaffingTemplate {
  id: string;
  store_type: string;
  position: string;
  shift: string;
  day_type: string;
  min_count: number;
  recommended_count: number;
  peak_buffer: number;
  min_skill_level: number;
  notes: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

interface StoreSummary {
  store_type: string;
  total_positions: number;
  total_min_count: number;
  total_recommended_count: number;
}

interface ListResult {
  items: StaffingTemplate[];
  total: number;
}

interface CopyResult {
  copied_count: number;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  枚举映射
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const storeTypeEnum: Record<string, { text: string }> = {
  flagship: { text: '旗舰店' },
  standard: { text: '标准店' },
  mini: { text: '精品店' },
  kiosk: { text: '档口店' },
};

const positionEnum: Record<string, { text: string }> = {
  manager: { text: '店长' },
  chef: { text: '厨师' },
  waiter: { text: '服务员' },
  cashier: { text: '收银' },
  cleaner: { text: '保洁' },
};

const shiftEnum: Record<string, { text: string }> = {
  morning: { text: '早班' },
  afternoon: { text: '午班' },
  evening: { text: '晚班' },
  full_day: { text: '全天' },
};

const dayTypeEnum: Record<string, { text: string }> = {
  weekday: { text: '工作日' },
  weekend: { text: '周末' },
  holiday: { text: '节假日' },
};

const selectOptions = (enumMap: Record<string, { text: string }>) =>
  Object.entries(enumMap).map(([value, { text: label }]) => ({ value, label }));

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  组件
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const StaffingTemplatePage: React.FC = () => {
  const actionRef = useRef<ActionType>();
  const [summaryList, setSummaryList] = useState<StoreSummary[]>([]);
  const [summaryLoading, setSummaryLoading] = useState(false);

  // ModalForm state
  const [formOpen, setFormOpen] = useState(false);
  const [editRecord, setEditRecord] = useState<StaffingTemplate | null>(null);

  // Copy modal state
  const [copyOpen, setCopyOpen] = useState(false);
  const [copySource, setCopySource] = useState<string>('');
  const [copyTarget, setCopyTarget] = useState<string>('');
  const [copyLoading, setCopyLoading] = useState(false);

  // ── Summary 加载 ──
  const loadSummary = async () => {
    setSummaryLoading(true);
    try {
      const resp = await txFetch<StoreSummary[]>('/api/v1/staffing-templates/summary');
      setSummaryList(resp.data ?? []);
    } catch (err) {
      console.error('加载汇总失败', err);
    } finally {
      setSummaryLoading(false);
    }
  };

  useEffect(() => {
    loadSummary();
  }, []);

  // ── 删除 ──
  const handleDelete = async (id: string) => {
    try {
      await txFetch<null>(`/api/v1/staffing-templates/${id}`, { method: 'DELETE' });
      message.success('删除成功');
      actionRef.current?.reload();
      loadSummary();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '删除失败');
    }
  };

  // ── 复制 ──
  const handleCopy = async () => {
    if (!copySource || !copyTarget) {
      message.warning('请选择源店型和目标店型');
      return;
    }
    if (copySource === copyTarget) {
      message.warning('源店型和目标店型不能相同');
      return;
    }
    setCopyLoading(true);
    try {
      const resp = await txFetch<CopyResult>('/api/v1/staffing-templates/copy', {
        method: 'POST',
        body: JSON.stringify({
          source_store_type: copySource,
          target_store_type: copyTarget,
        }),
      });
      message.success(`复制成功，共复制 ${resp.data?.copied_count ?? 0} 条模板`);
      setCopyOpen(false);
      setCopySource('');
      setCopyTarget('');
      actionRef.current?.reload();
      loadSummary();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '复制失败');
    } finally {
      setCopyLoading(false);
    }
  };

  // ── 新增/编辑提交 ──
  const handleSubmit = async (values: Record<string, unknown>) => {
    try {
      if (editRecord) {
        await txFetch<StaffingTemplate>(`/api/v1/staffing-templates/${editRecord.id}`, {
          method: 'PUT',
          body: JSON.stringify(values),
        });
        message.success('更新成功');
      } else {
        await txFetch<StaffingTemplate>('/api/v1/staffing-templates', {
          method: 'POST',
          body: JSON.stringify(values),
        });
        message.success('创建成功');
      }
      setFormOpen(false);
      setEditRecord(null);
      actionRef.current?.reload();
      loadSummary();
      return true;
    } catch (err) {
      message.error(err instanceof Error ? err.message : '操作失败');
      return false;
    }
  };

  // ── 表格列 ──
  const columns: ProColumns<StaffingTemplate>[] = [
    {
      title: '店型',
      dataIndex: 'store_type',
      valueType: 'select',
      valueEnum: storeTypeEnum,
      width: 100,
    },
    {
      title: '岗位',
      dataIndex: 'position',
      valueType: 'select',
      valueEnum: positionEnum,
      width: 90,
    },
    {
      title: '班次',
      dataIndex: 'shift',
      valueEnum: shiftEnum,
      hideInSearch: true,
      width: 80,
    },
    {
      title: '日类型',
      dataIndex: 'day_type',
      valueType: 'select',
      valueEnum: dayTypeEnum,
      width: 90,
    },
    {
      title: '最低人数',
      dataIndex: 'min_count',
      hideInSearch: true,
      width: 90,
      align: 'center',
    },
    {
      title: '建议人数',
      dataIndex: 'recommended_count',
      hideInSearch: true,
      width: 90,
      align: 'center',
    },
    {
      title: '峰值保护',
      dataIndex: 'peak_buffer',
      hideInSearch: true,
      width: 90,
      align: 'center',
    },
    {
      title: '最低技能',
      dataIndex: 'min_skill_level',
      hideInSearch: true,
      width: 90,
      align: 'center',
      render: (_, record) => `Lv.${record.min_skill_level}`,
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      hideInSearch: true,
      width: 80,
      align: 'center',
      render: (_, record) =>
        record.is_active ? (
          <Tag color="green">启用</Tag>
        ) : (
          <Tag>停用</Tag>
        ),
    },
    {
      title: '操作',
      valueType: 'option',
      width: 140,
      render: (_, record) => (
        <Space size="small">
          <a
            onClick={() => {
              setEditRecord(record);
              setFormOpen(true);
            }}
          >
            编辑
          </a>
          <Popconfirm
            title="确认删除此编制模板？"
            onConfirm={() => handleDelete(record.id)}
            okText="确认"
            cancelText="取消"
          >
            <a style={{ color: '#ff4d4f' }}>删除</a>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ minWidth: 1280 }}>
      {/* ── Summary Cards ── */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        {summaryLoading
          ? Array.from({ length: 4 }).map((_, i) => (
              <Col span={6} key={i}>
                <StatisticCard loading style={{ height: 120 }} />
              </Col>
            ))
          : summaryList.map((s) => (
              <Col span={6} key={s.store_type}>
                <StatisticCard
                  statistic={{
                    title: storeTypeEnum[s.store_type]?.text ?? s.store_type,
                    value: s.total_positions,
                    suffix: '个岗位',
                    description: (
                      <Space split="/" size={4}>
                        <span>最低 {s.total_min_count} 人</span>
                        <span>建议 {s.total_recommended_count} 人</span>
                      </Space>
                    ),
                  }}
                />
              </Col>
            ))}
      </Row>

      {/* ── ProTable ── */}
      <ProTable<StaffingTemplate>
        columns={columns}
        actionRef={actionRef}
        rowKey="id"
        headerTitle="编制模板列表"
        search={{ labelWidth: 'auto' }}
        request={async (params) => {
          const query = new URLSearchParams();
          if (params.store_type) query.set('store_type', params.store_type as string);
          if (params.position) query.set('position', params.position as string);
          if (params.day_type) query.set('day_type', params.day_type as string);
          if (params.is_active !== undefined) query.set('is_active', String(params.is_active));
          query.set('page', String(params.current ?? 1));
          query.set('size', String(params.pageSize ?? 20));
          try {
            const resp = await txFetch<ListResult>(
              `/api/v1/staffing-templates?${query.toString()}`,
            );
            const list = resp.data;
            return {
              data: list?.items ?? [],
              total: list?.total ?? 0,
              success: true,
            };
          } catch {
            return { data: [], total: 0, success: false };
          }
        }}
        pagination={{ defaultPageSize: 20, showSizeChanger: true }}
        toolBarRender={() => [
          <Button
            key="create"
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              setEditRecord(null);
              setFormOpen(true);
            }}
          >
            新增编制
          </Button>,
          <Button
            key="copy"
            icon={<CopyOutlined />}
            onClick={() => setCopyOpen(true)}
          >
            复制模板
          </Button>,
          <Button key="import" icon={<UploadOutlined />} disabled>
            批量导入
          </Button>,
        ]}
      />

      {/* ── Create / Edit ModalForm ── */}
      <ModalForm<Record<string, unknown>>
        title={editRecord ? '编辑编制模板' : '新增编制模板'}
        open={formOpen}
        onOpenChange={(open) => {
          if (!open) {
            setFormOpen(false);
            setEditRecord(null);
          }
        }}
        initialValues={
          editRecord
            ? { ...editRecord }
            : { is_active: true, min_count: 1, recommended_count: 1, peak_buffer: 0, min_skill_level: 1 }
        }
        modalProps={{ destroyOnClose: true }}
        onFinish={handleSubmit}
        width={560}
      >
        <ProFormSelect
          name="store_type"
          label="店型"
          options={selectOptions(storeTypeEnum)}
          rules={[{ required: true, message: '请选择店型' }]}
        />
        <ProFormSelect
          name="position"
          label="岗位"
          options={selectOptions(positionEnum)}
          rules={[{ required: true, message: '请选择岗位' }]}
        />
        <ProFormSelect
          name="shift"
          label="班次"
          options={selectOptions(shiftEnum)}
          rules={[{ required: true, message: '请选择班次' }]}
        />
        <ProFormSelect
          name="day_type"
          label="日类型"
          options={selectOptions(dayTypeEnum)}
          rules={[{ required: true, message: '请选择日类型' }]}
        />
        <ProFormDigit
          name="min_count"
          label="最低人数"
          min={0}
          fieldProps={{ precision: 0 }}
          rules={[{ required: true, message: '请输入最低人数' }]}
        />
        <ProFormDigit
          name="recommended_count"
          label="建议人数"
          min={0}
          fieldProps={{ precision: 0 }}
          rules={[{ required: true, message: '请输入建议人数' }]}
        />
        <ProFormDigit
          name="peak_buffer"
          label="峰值保护"
          min={0}
          fieldProps={{ precision: 0 }}
          rules={[{ required: true, message: '请输入峰值保护人数' }]}
        />
        <ProFormDigit
          name="min_skill_level"
          label="最低技能等级"
          min={1}
          max={5}
          fieldProps={{ precision: 0 }}
          rules={[{ required: true, message: '请输入最低技能等级(1-5)' }]}
        />
        <ProFormTextArea name="notes" label="备注" fieldProps={{ rows: 3 }} />
        <ProFormSwitch name="is_active" label="启用状态" />
      </ModalForm>

      {/* ── Copy Modal ── */}
      <Modal
        title="复制编制模板"
        open={copyOpen}
        onCancel={() => {
          setCopyOpen(false);
          setCopySource('');
          setCopyTarget('');
        }}
        onOk={handleCopy}
        confirmLoading={copyLoading}
        okText="确认复制"
        cancelText="取消"
        destroyOnClose
      >
        <div style={{ marginBottom: 16 }}>
          <div style={{ marginBottom: 8, fontWeight: 500 }}>源店型</div>
          <Select
            value={copySource || undefined}
            onChange={(val) => setCopySource(val)}
            options={selectOptions(storeTypeEnum)}
            placeholder="请选择源店型"
            style={{ width: '100%' }}
          />
        </div>
        <div>
          <div style={{ marginBottom: 8, fontWeight: 500 }}>目标店型</div>
          <Select
            value={copyTarget || undefined}
            onChange={(val) => setCopyTarget(val)}
            options={selectOptions(storeTypeEnum)}
            placeholder="请选择目标店型"
            style={{ width: '100%' }}
          />
        </div>
      </Modal>
    </div>
  );
};

export default StaffingTemplatePage;
