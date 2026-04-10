/**
 * 出餐码管理页面
 *
 * 功能：
 * - 门店选择
 * - 待确认出餐码列表（外卖订单等待打包扫码确认）
 * - 生成出餐码（手动为订单生成）
 * - 扫码确认（输入6位码 + 操作员ID 确认出餐）
 * - 查询单订单出餐码状态
 *
 * 注意：后端 dispatch_code 是外卖出餐流程扫码确认模块，
 * 与"档口编码方案"（本页也提供说明卡片）是不同概念。
 *
 * 设计规范：admin.md + tokens.md
 * API：/api/v1/dispatch-codes/*
 */

import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Descriptions,
  Divider,
  Empty,
  Form,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  BarcodeOutlined,
  CheckCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import {
  type DispatchCode,
  type DispatchCodePending,
  type StoreOption,
  fetchStoreOptions,
  generateDispatchCode,
  getDispatchCodeByOrder,
  listPendingDispatchCodes,
  scanDispatchCode,
} from '../../api/kdsManageApi';

const { Title, Text, Paragraph } = Typography;

// ─── Design Token ──────────────────────────────────────────────────────────
const TX_PRIMARY = '#FF6B35';
const TX_SUCCESS = '#0F6E56';
const TX_WARNING = '#BA7517';
const TX_BG_SECONDARY = '#F8F7F5';
const TX_TEXT_SECONDARY = '#5F5E5A';

// ─── 平台标签颜色 ──────────────────────────────────────────────────────────
const PLATFORM_COLORS: Record<string, string> = {
  meituan: 'gold',
  eleme: 'blue',
  douyin: 'magenta',
  dianping: 'red',
  unknown: 'default',
};

const PLATFORM_LABELS: Record<string, string> = {
  meituan: '美团',
  eleme: '饿了么',
  douyin: '抖音',
  dianping: '大众点评',
  unknown: '其他',
};

const PLATFORM_OPTIONS = Object.entries(PLATFORM_LABELS).map(([v, l]) => ({
  value: v,
  label: l,
}));

function PlatformTag({ platform }: { platform: string }) {
  return (
    <Tag color={PLATFORM_COLORS[platform] ?? 'default'}>
      {PLATFORM_LABELS[platform] ?? platform}
    </Tag>
  );
}

// ─── 生成出餐码 Modal ──────────────────────────────────────────────────────

interface GenerateModalProps {
  open: boolean;
  onClose: () => void;
  onGenerated: () => void;
}

function GenerateModal({ open, onClose, onGenerated }: GenerateModalProps) {
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<{
    code: string;
    qr_data: string;
    order_id: string;
    platform: string;
  } | null>(null);

  const handleGenerate = async () => {
    let values: Record<string, unknown>;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    setSaving(true);
    try {
      const res = await generateDispatchCode(
        values.order_id as string,
        (values.platform as string) || 'unknown',
      );
      setResult(res);
      message.success('出餐码已生成');
      onGenerated();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '生成失败');
    } finally {
      setSaving(false);
    }
  };

  const handleClose = () => {
    form.resetFields();
    setResult(null);
    onClose();
  };

  return (
    <Modal
      title="生成出餐码"
      open={open}
      onCancel={handleClose}
      footer={
        result ? (
          <Button onClick={handleClose}>关闭</Button>
        ) : (
          <Space>
            <Button onClick={handleClose}>取消</Button>
            <Button
              type="primary"
              loading={saving}
              onClick={handleGenerate}
              style={{ background: TX_PRIMARY, borderColor: TX_PRIMARY }}
            >
              生成
            </Button>
          </Space>
        )
      }
      destroyOnClose
    >
      {result ? (
        <div style={{ textAlign: 'center', padding: '16px 0' }}>
          <div style={{
            fontSize: 48,
            fontWeight: 900,
            letterSpacing: 8,
            color: TX_PRIMARY,
            background: TX_BG_SECONDARY,
            borderRadius: 8,
            padding: '20px 32px',
            display: 'inline-block',
          }}>
            {result.code}
          </div>
          <div style={{ marginTop: 16, color: TX_TEXT_SECONDARY, fontSize: 13 }}>
            订单：{result.order_id}
          </div>
          <div style={{ color: TX_TEXT_SECONDARY, fontSize: 13 }}>
            平台：{PLATFORM_LABELS[result.platform] ?? result.platform}
          </div>
          <Alert
            type="success"
            showIcon
            message="出餐码已生成，告知打包员扫码确认出餐"
            style={{ marginTop: 16 }}
          />
        </div>
      ) : (
        <Form form={form} layout="vertical">
          <Form.Item
            name="order_id"
            label="订单ID（UUID）"
            rules={[{ required: true, message: '请输入订单ID' }]}
          >
            <Input placeholder="粘贴或输入订单UUID" />
          </Form.Item>
          <Form.Item name="platform" label="外卖平台">
            <Select
              placeholder="选择平台（可不填）"
              allowClear
              options={PLATFORM_OPTIONS}
            />
          </Form.Item>
        </Form>
      )}
    </Modal>
  );
}

// ─── 扫码确认 Modal ────────────────────────────────────────────────────────

interface ScanModalProps {
  open: boolean;
  onClose: () => void;
  onConfirmed: () => void;
}

function ScanModal({ open, onClose, onConfirmed }: ScanModalProps) {
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);

  const handleScan = async () => {
    let values: Record<string, unknown>;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    setSaving(true);
    try {
      const res = await scanDispatchCode(
        values.code as string,
        values.operator_id as string,
      );
      if (res.already_confirmed) {
        message.warning('该出餐码已经确认过了');
      } else if (res.success) {
        message.success(`出餐确认成功 · 订单：${res.order_id}`);
        form.resetFields();
        onConfirmed();
      } else {
        message.error('确认失败，请检查出餐码是否正确');
      }
    } catch (err) {
      message.error(err instanceof Error ? err.message : '确认失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={
        <Space>
          <BarcodeOutlined style={{ color: TX_PRIMARY }} />
          扫码确认出餐
        </Space>
      }
      open={open}
      onCancel={() => { form.resetFields(); onClose(); }}
      onOk={handleScan}
      confirmLoading={saving}
      okText="确认出餐"
      cancelText="取消"
      destroyOnClose
    >
      <Form form={form} layout="vertical" style={{ marginTop: 8 }}>
        <Form.Item
          name="code"
          label="出餐码（6位）"
          rules={[{ required: true, message: '请输入出餐码' }]}
        >
          <Input
            placeholder="输入或扫码枪扫入"
            maxLength={20}
            style={{ fontSize: 20, letterSpacing: 4, fontWeight: 700 }}
            autoFocus
          />
        </Form.Item>
        <Form.Item
          name="operator_id"
          label="操作员ID"
          rules={[{ required: true, message: '请输入操作员ID' }]}
        >
          <Input placeholder="操作员UUID" />
        </Form.Item>
      </Form>
    </Modal>
  );
}

// ─── 查询订单出餐码状态 ───────────────────────────────────────────────────

function QueryPanel() {
  const [orderId, setOrderId] = useState('');
  const [loading, setLoading] = useState(false);
  const [codeInfo, setCodeInfo] = useState<DispatchCode | null | undefined>(undefined);

  const handleQuery = async () => {
    if (!orderId.trim()) {
      message.warning('请输入订单ID');
      return;
    }
    setLoading(true);
    setCodeInfo(undefined);
    try {
      const result = await getDispatchCodeByOrder(orderId.trim());
      setCodeInfo(result);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '查询失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card
      title={
        <Space>
          <SearchOutlined style={{ color: TX_PRIMARY }} />
          查询订单出餐码状态
        </Space>
      }
      style={{ marginTop: 24 }}
    >
      <Space.Compact style={{ width: '100%', maxWidth: 500 }}>
        <Input
          placeholder="输入订单UUID"
          value={orderId}
          onChange={(e) => setOrderId(e.target.value)}
          onPressEnter={handleQuery}
        />
        <Button
          type="primary"
          loading={loading}
          onClick={handleQuery}
          style={{ background: TX_PRIMARY, borderColor: TX_PRIMARY }}
        >
          查询
        </Button>
      </Space.Compact>

      {codeInfo === null && (
        <Alert
          type="info"
          showIcon
          message="该订单暂无出餐码记录（可能尚未生成）"
          style={{ marginTop: 16 }}
        />
      )}

      {codeInfo && (
        <Descriptions
          style={{ marginTop: 16 }}
          bordered
          size="small"
          column={2}
        >
          <Descriptions.Item label="出餐码">
            <Text strong style={{ fontSize: 20, letterSpacing: 4, color: TX_PRIMARY }}>
              {codeInfo.code}
            </Text>
          </Descriptions.Item>
          <Descriptions.Item label="平台">
            <PlatformTag platform={codeInfo.platform} />
          </Descriptions.Item>
          <Descriptions.Item label="确认状态">
            {codeInfo.confirmed ? (
              <Badge status="success" text="已确认出餐" />
            ) : (
              <Badge status="processing" text="待确认" />
            )}
          </Descriptions.Item>
          <Descriptions.Item label="确认时间">
            {codeInfo.confirmed_at ?? '—'}
          </Descriptions.Item>
          <Descriptions.Item label="生成时间" span={2}>
            {codeInfo.created_at}
          </Descriptions.Item>
        </Descriptions>
      )}
    </Card>
  );
}

// ─── 主页面 ────────────────────────────────────────────────────────────────

export const DispatchCodePage: React.FC = () => {
  const [stores, setStores] = useState<StoreOption[]>([]);
  const [storeId, setStoreId] = useState<string>('');
  const [pendingList, setPendingList] = useState<DispatchCodePending[]>([]);
  const [loading, setLoading] = useState(false);
  const [generateOpen, setGenerateOpen] = useState(false);
  const [scanOpen, setScanOpen] = useState(false);

  useEffect(() => {
    fetchStoreOptions().then((opts) => {
      setStores(opts);
      if (opts.length > 0) setStoreId(opts[0].value);
    });
  }, []);

  const loadPending = useCallback(async () => {
    if (!storeId) return;
    setLoading(true);
    try {
      const res = await listPendingDispatchCodes(storeId);
      setPendingList(res.items);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [storeId]);

  useEffect(() => {
    void loadPending();
  }, [loadPending]);

  const columns: ColumnsType<DispatchCodePending> = [
    {
      title: '出餐码',
      dataIndex: 'code',
      key: 'code',
      width: 120,
      render: (code: string) => (
        <Text strong style={{ fontSize: 18, letterSpacing: 3, color: TX_PRIMARY }}>
          {code}
        </Text>
      ),
    },
    {
      title: '订单ID',
      dataIndex: 'order_id',
      key: 'order_id',
      ellipsis: true,
      render: (id: string) => <Text copyable={{ text: id }}>{id.slice(0, 12)}…</Text>,
    },
    {
      title: '平台',
      dataIndex: 'platform',
      key: 'platform',
      width: 100,
      render: (p: string) => <PlatformTag platform={p} />,
    },
    {
      title: '状态',
      dataIndex: 'confirmed',
      key: 'confirmed',
      width: 100,
      render: (confirmed: boolean) =>
        confirmed ? (
          <Badge status="success" text="已确认" />
        ) : (
          <Badge status="warning" text="待打包" />
        ),
    },
    {
      title: '生成时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
    },
  ];

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto' }}>
      {/* 页面标题 */}
      <div style={{ marginBottom: 24 }}>
        <Title level={2} style={{ margin: 0, color: '#2C2C2A' }}>
          出餐码管理
        </Title>
        <Paragraph style={{ color: TX_TEXT_SECONDARY, margin: '8px 0 0', fontSize: 14 }}>
          外卖出餐流程扫码确认。系统为每笔外卖订单生成唯一6位出餐码，打包员扫码后自动通知平台出餐。
        </Paragraph>
      </div>

      {/* 门店选择 + 操作按钮 */}
      <Card
        style={{ marginBottom: 24 }}
        styles={{ body: { padding: '16px 24px' } }}
      >
        <Space size={16} wrap>
          <Space>
            <Text strong>门店：</Text>
            <Select
              options={stores}
              value={storeId || undefined}
              onChange={(v) => setStoreId(v)}
              placeholder="选择门店"
              style={{ width: 220 }}
              showSearch
              optionFilterProp="label"
            />
          </Space>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => void loadPending()}
            loading={loading}
          >
            刷新
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            disabled={!storeId}
            onClick={() => setGenerateOpen(true)}
            style={{ background: TX_PRIMARY, borderColor: TX_PRIMARY }}
          >
            生成出餐码
          </Button>
          <Button
            icon={<BarcodeOutlined />}
            disabled={!storeId}
            onClick={() => setScanOpen(true)}
          >
            扫码确认出餐
          </Button>
        </Space>
      </Card>

      {/* 待确认出餐码列表 */}
      <Card
        title={
          <Space>
            <span>待打包订单</span>
            {pendingList.length > 0 && (
              <Tag color="orange">{pendingList.length} 单待出餐</Tag>
            )}
          </Space>
        }
      >
        {!storeId ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请先选择门店" />
        ) : (
          <Spin spinning={loading}>
            {pendingList.length === 0 ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={
                  <Text style={{ color: TX_SUCCESS }}>
                    <CheckCircleOutlined style={{ marginRight: 6 }} />
                    暂无待出餐订单，一切顺利！
                  </Text>
                }
              />
            ) : (
              <Table<DispatchCodePending>
                columns={columns}
                dataSource={pendingList}
                rowKey="id"
                pagination={{ defaultPageSize: 20, showSizeChanger: true }}
                size="middle"
              />
            )}
          </Spin>
        )}
      </Card>

      {/* 查询面板 */}
      <QueryPanel />

      {/* 流程说明 */}
      <Card
        title="出餐码工作流程"
        style={{ marginTop: 24 }}
        styles={{ body: { background: TX_BG_SECONDARY } }}
      >
        <Row gutter={16}>
          {[
            { step: '1', title: '接单', desc: '外卖订单进入系统，自动生成出餐码', color: TX_PRIMARY },
            { step: '2', title: '备餐', desc: '厨师完成菜品，打包员准备出餐', color: TX_WARNING },
            { step: '3', title: '扫码', desc: '打包员扫码 / 输入6位出餐码确认', color: '#185FA5' },
            { step: '4', title: '通知', desc: '系统自动通知外卖平台，骑手取餐', color: TX_SUCCESS },
          ].map(({ step, title, desc, color }) => (
            <Col span={6} key={step}>
              <div style={{
                textAlign: 'center',
                padding: '16px 8px',
                background: '#fff',
                borderRadius: 8,
                border: `2px solid ${color}`,
              }}>
                <div style={{
                  width: 36,
                  height: 36,
                  borderRadius: '50%',
                  background: color,
                  color: '#fff',
                  fontSize: 18,
                  fontWeight: 700,
                  lineHeight: '36px',
                  margin: '0 auto 8px',
                }}>
                  {step}
                </div>
                <div style={{ fontWeight: 600, marginBottom: 4 }}>{title}</div>
                <div style={{ fontSize: 12, color: TX_TEXT_SECONDARY }}>{desc}</div>
              </div>
            </Col>
          ))}
        </Row>
      </Card>

      {/* Modals */}
      <GenerateModal
        open={generateOpen}
        onClose={() => setGenerateOpen(false)}
        onGenerated={() => void loadPending()}
      />
      <ScanModal
        open={scanOpen}
        onClose={() => setScanOpen(false)}
        onConfirmed={() => {
          void loadPending();
          setScanOpen(false);
        }}
      />
    </div>
  );
};

export default DispatchCodePage;
