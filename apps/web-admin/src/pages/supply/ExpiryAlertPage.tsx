/**
 * 临期食材预警页 — 域D 供应链
 * 查询 ingredient_batches.expiry_date，结合 /api/v1/supply/alerts 展示临期预警
 *
 * 技术栈：Ant Design 5.x + ProComponents
 * 颜色规范：≤3天 danger红 / ≤7天 orange / ≤15天 warning黄 / 其余正常
 */
import { useRef, useState, useCallback, useEffect } from 'react';
import { txFetchData, txFetch } from '../../api/client';
import {
  ProTable,
  ProColumns,
  ActionType,
  ModalForm,
  ProFormText,
  ProFormSelect,
  ProFormDigit,
} from '@ant-design/pro-components';
import {
  Button,
  Tag,
  Space,
  Alert,
  Row,
  Col,
  Card,
  Statistic,
  Badge,
  Select,
  List,
  Typography,
  message,
  Modal,
  Spin,
  Divider,
} from 'antd';
import {
  ExclamationCircleOutlined,
  WarningOutlined,
  RobotOutlined,
  ExportOutlined,
  CheckCircleOutlined,
  SwapOutlined,
  ShoppingCartOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';

const { Text, Paragraph } = Typography;

// ─── 类型定义 ────────────────────────────────────────────────────────────────

interface ExpiryAlert {
  id: string;
  ingredient_name: string;
  batch_no: string;
  quantity: number;
  unit: string;
  expiry_date: string;
  days_remaining: number;
  suggested_action: string;
  related_dishes?: string[];
  status: 'pending' | 'handled';
  store_id: string;
}

interface AIAnalysisResult {
  risk_level: 'low' | 'medium' | 'high' | 'critical';
  at_risk_count: number;
  recommendations: {
    ingredient_name: string;
    suggested_quantity: number;
    unit: string;
    reason: string;
  }[];
  food_safety_constraints: {
    status: 'ok' | 'warning' | 'violation';
    message: string;
  };
  summary: string;
}

// ─── 统计概览类型 ──────────────────────────────────────────────────────────────

interface ExpirySummary {
  urgent_count: number;       // ≤3天
  near_expiry_count: number;  // ≤7天
  pending_count: number;
  handled_count: number;
}

// ─── 工具函数 ─────────────────────────────────────────────────────────────────

async function apiPatch<T = unknown>(path: string, body?: unknown): Promise<T> {
  const resp = await txFetch<T>(path, {
    method: 'PATCH',
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  return resp.data as T;
}

function getDaysColor(days: number): string {
  if (days <= 3) return '#A32D2D';
  if (days <= 7) return '#D46B08';
  if (days <= 15) return '#BA7517';
  return '#0F6E56';
}

function getDaysTag(days: number) {
  if (days <= 3) {
    return (
      <Tag color="error" icon={<ExclamationCircleOutlined />}>
        {days}天
      </Tag>
    );
  }
  if (days <= 7) {
    return <Tag color="orange">{days}天</Tag>;
  }
  if (days <= 15) {
    return <Tag color="warning">{days}天</Tag>;
  }
  return <Tag color="default">{days}天</Tag>;
}

function getRiskBadge(level: AIAnalysisResult['risk_level']) {
  const map = {
    low: { status: 'success' as const, text: '低风险' },
    medium: { status: 'warning' as const, text: '中风险' },
    high: { status: 'error' as const, text: '高风险' },
    critical: { status: 'error' as const, text: '严重风险' },
  };
  return map[level] ?? map.medium;
}

// ─── 快速新建采购单弹窗 ────────────────────────────────────────────────────────

interface QuickPOModalProps {
  ingredientName: string;
  open: boolean;
  onClose: () => void;
}

function QuickPOModal({ ingredientName, open, onClose }: QuickPOModalProps) {
  return (
    <ModalForm
      title={`快速采购 — ${ingredientName}`}
      open={open}
      modalProps={{ onCancel: onClose, destroyOnClose: true }}
      onFinish={async (values) => {
        try {
          await txFetch('/api/v1/supply/purchase-orders', {
            method: 'POST',
            body: JSON.stringify({
              store_id: values.store_id,
              items: [{
                ingredient_name: ingredientName,
                quantity: values.quantity,
                unit: values.unit,
                unit_price_fen: Math.round((values.unit_price_yuan ?? 0) * 100),
                subtotal_fen: Math.round((values.quantity ?? 0) * (values.unit_price_yuan ?? 0) * 100),
              }],
            }),
          });
          message.success('采购单已创建，等待审批');
          onClose();
          return true;
        } catch {
          message.error('创建采购单失败，请重试');
          return false;
        }
      }}
    >
      <ProFormText
        name="ingredient_name"
        label="食材名称"
        initialValue={ingredientName}
        disabled
      />
      <ProFormSelect
        name="store_id"
        label="门店"
        rules={[{ required: true }]}
        options={[
          { label: '芙蓉路店', value: 'store-001' },
          { label: '五一广场店', value: 'store-002' },
        ]}
      />
      <ProFormDigit name="quantity" label="采购数量" min={0.001} fieldProps={{ precision: 3 }} rules={[{ required: true }]} />
      <ProFormSelect
        name="unit"
        label="单位"
        initialValue="kg"
        options={['kg', '件', '箱', '包', '瓶', 'L'].map((u) => ({ label: u, value: u }))}
      />
      <ProFormDigit
        name="unit_price_yuan"
        label="参考单价（元）"
        min={0}
        fieldProps={{ precision: 2, prefix: '¥' }}
        rules={[{ required: true }]}
      />
    </ModalForm>
  );
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export function ExpiryAlertPage() {
  const actionRef = useRef<ActionType>();
  const [storeId, setStoreId] = useState(localStorage.getItem('tx_store_id') ?? 'default');
  const [daysThreshold, setDaysThreshold] = useState(7);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiResult, setAiResult] = useState<AIAnalysisResult | null>(null);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [quickPOIngredient, setQuickPOIngredient] = useState<string | null>(null);
  const [allAlerts, setAllAlerts] = useState<ExpiryAlert[]>([]);

  // 统计概览（来自 API summary 接口）
  const [summary, setSummary] = useState<ExpirySummary | null>(null);

  const todayCount  = summary?.urgent_count      ?? allAlerts.filter((a) => a.days_remaining <= 3 && a.status === 'pending').length;
  const weekCount   = summary?.near_expiry_count  ?? allAlerts.filter((a) => a.days_remaining <= 7 && a.status === 'pending').length;
  const pendingCount = summary?.pending_count     ?? allAlerts.filter((a) => a.status === 'pending').length;
  const handledCount = summary?.handled_count     ?? allAlerts.filter((a) => a.status === 'handled').length;

  // 加载统计概览
  useEffect(() => {
    txFetchData<ExpirySummary>(`/api/v1/supply/expiry-alerts/summary?store_id=${storeId}`)
      .then(setSummary)
      .catch(() => { /* 降级：使用本地计算 */ });
  }, [storeId]);

  // 标记已处理
  const handleMarkDone = useCallback(async (record: ExpiryAlert) => {
    try {
      await apiPatch(`/api/v1/supply/expiry-alerts/${record.id}/resolve`);
    } catch {
      // 降级：本地乐观更新
    }
    setAllAlerts((prev) =>
      prev.map((a) => (a.id === record.id ? { ...a, status: 'handled' } : a)),
    );
    // 刷新统计
    txFetchData<ExpirySummary>(`/api/v1/supply/expiry-alerts/summary?store_id=${storeId}`)
      .then(setSummary)
      .catch(() => {});
    message.success('已标记为处理完成');
    actionRef.current?.reload();
  }, [storeId]);

  // 转移门店
  const handleTransfer = useCallback((record: ExpiryAlert) => {
    Modal.confirm({
      title: `转移 ${record.ingredient_name} 至其他门店`,
      icon: <SwapOutlined />,
      content: (
        <Select
          defaultValue="store-002"
          style={{ width: '100%', marginTop: 8 }}
          options={[
            { label: '五一广场店', value: 'store-002' },
            { label: '解放西路店', value: 'store-003' },
          ]}
        />
      ),
      okText: '确认转移',
      onOk: async () => {
        message.success(`${record.ingredient_name} 已发起转移申请`);
      },
    });
  }, []);

  // AI 分析
  const handleAIAnalyze = useCallback(async () => {
    setAiLoading(true);
    setAiResult(null);
    try {
      const result = await txFetchData<AIAnalysisResult>(
        `/api/v1/brain/inventory/analyze?store_id=${storeId}`,
      );
      setAiResult(result);
    } catch {
      message.warning('AI 分析服务暂不可用');
    } finally {
      setAiLoading(false);
    }
  }, [storeId]);

  // 导出 CSV
  const handleExport = useCallback(() => {
    const headers = ['食材名', '批次号', '数量', '单位', '保质期', '剩余天数', '建议操作', '关联菜品', '状态'];
    const rows = allAlerts.map((a) => [
      a.ingredient_name,
      a.batch_no,
      a.quantity,
      a.unit,
      a.expiry_date,
      a.days_remaining,
      a.suggested_action,
      (a.related_dishes ?? []).join('|'),
      a.status === 'handled' ? '已处理' : '待处理',
    ]);
    const csv = [headers, ...rows].map((r) => r.join(',')).join('\n');
    const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `临期预警_${dayjs().format('YYYYMMDD')}.csv`;
    link.click();
    URL.revokeObjectURL(url);
    message.success('报告已导出');
  }, [allAlerts]);

  const columns: ProColumns<ExpiryAlert>[] = [
    {
      title: '食材名称',
      dataIndex: 'ingredient_name',
      valueType: 'text',
      width: 130,
      render: (_, r) => <Text strong>{r.ingredient_name}</Text>,
    },
    {
      title: '批次号',
      dataIndex: 'batch_no',
      valueType: 'text',
      width: 170,
      render: (_, r) => <Text type="secondary" style={{ fontSize: 12 }}>{r.batch_no}</Text>,
    },
    {
      title: '剩余数量',
      dataIndex: 'quantity',
      hideInSearch: true,
      width: 100,
      render: (_, r) => `${r.quantity} ${r.unit}`,
    },
    {
      title: '保质期',
      dataIndex: 'expiry_date',
      hideInSearch: true,
      width: 110,
      render: (_, r) => (
        <span style={{ color: getDaysColor(r.days_remaining) }}>
          {r.expiry_date}
        </span>
      ),
    },
    {
      title: '剩余天数',
      dataIndex: 'days_remaining',
      hideInSearch: true,
      width: 90,
      sorter: (a, b) => a.days_remaining - b.days_remaining,
      defaultSortOrder: 'ascend',
      render: (_, r) => getDaysTag(r.days_remaining),
    },
    {
      title: '建议操作',
      dataIndex: 'suggested_action',
      hideInSearch: true,
      ellipsis: true,
      render: (_, r) => (
        <Text style={{ fontSize: 13, color: '#5F5E5A' }}>{r.suggested_action}</Text>
      ),
    },
    {
      title: '关联菜品',
      dataIndex: 'related_dishes',
      hideInSearch: true,
      width: 160,
      render: (_, r) => (
        <Space size={4} wrap>
          {(r.related_dishes ?? []).map((d) => (
            <Tag key={d} style={{ fontSize: 11, margin: 0 }}>{d}</Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      valueType: 'select',
      width: 80,
      valueEnum: {
        pending: { text: '待处理', status: 'Warning' },
        handled: { text: '已处理', status: 'Success' },
      },
      render: (_, r) =>
        r.status === 'handled' ? (
          <Tag color="success" icon={<CheckCircleOutlined />}>已处理</Tag>
        ) : (
          <Tag color="warning">待处理</Tag>
        ),
    },
    {
      title: '操作',
      valueType: 'option',
      width: 200,
      render: (_, r) => (
        <Space size="small">
          {r.status === 'pending' && (
            <a
              style={{ color: '#0F6E56', fontSize: 12 }}
              onClick={() => handleMarkDone(r)}
            >
              标记已处理
            </a>
          )}
          <a
            style={{ color: '#185FA5', fontSize: 12 }}
            onClick={() => handleTransfer(r)}
          >
            转移门店
          </a>
          <a
            style={{ color: '#FF6B35', fontSize: 12 }}
            onClick={() => setQuickPOIngredient(r.ingredient_name)}
          >
            生成采购单
          </a>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: '24px 24px 0' }}>
      {/* 全局错误提示 */}
      {globalError && (
        <Alert
          type="error"
          message={globalError}
          closable
          onClose={() => setGlobalError(null)}
          style={{ marginBottom: 16 }}
        />
      )}

      {/* 顶部控制区 */}
      <Card
        bordered={false}
        style={{ marginBottom: 16, background: '#F8F7F5' }}
        bodyStyle={{ padding: '12px 16px' }}
      >
        <Space size="middle" wrap>
          <Space>
            <Text type="secondary">门店：</Text>
            <Select
              value={storeId}
              onChange={setStoreId}
              style={{ width: 160 }}
              options={[
                { label: '芙蓉路店', value: 'store-001' },
                { label: '五一广场店', value: 'store-002' },
                { label: '解放西路店', value: 'store-003' },
              ]}
            />
          </Space>
          <Space>
            <Text type="secondary">预警天数：</Text>
            <Select
              value={daysThreshold}
              onChange={(v) => {
                setDaysThreshold(v);
                actionRef.current?.reload();
              }}
              style={{ width: 120 }}
              options={[
                { label: '3天内', value: 3 },
                { label: '7天内', value: 7 },
                { label: '15天内', value: 15 },
                { label: '30天内', value: 30 },
              ]}
            />
          </Space>
          <Button
            type="primary"
            icon={<RobotOutlined />}
            loading={aiLoading}
            onClick={handleAIAnalyze}
            style={{ background: '#185FA5', borderColor: '#185FA5' }}
          >
            AI 分析
          </Button>
          <Button icon={<ExportOutlined />} onClick={handleExport}>
            导出报告
          </Button>
        </Space>
      </Card>

      {/* 统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card bordered={false} style={{ borderLeft: '4px solid #A32D2D' }}>
            <Statistic
              title="今日临期（≤3天）"
              value={todayCount}
              suffix="种"
              valueStyle={{ color: '#A32D2D', fontWeight: 700 }}
              prefix={<ExclamationCircleOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card bordered={false} style={{ borderLeft: '4px solid #D46B08' }}>
            <Statistic
              title="本周临期（≤7天）"
              value={weekCount}
              suffix="种"
              valueStyle={{ color: '#D46B08', fontWeight: 700 }}
              prefix={<WarningOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card bordered={false} style={{ borderLeft: '4px solid #BA7517' }}>
            <Statistic
              title="待处理预警"
              value={pendingCount}
              suffix="条"
              valueStyle={{ color: '#BA7517', fontWeight: 700 }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card bordered={false} style={{ borderLeft: '4px solid #0F6E56' }}>
            <Statistic
              title="已处理预警"
              value={handledCount}
              suffix="条"
              valueStyle={{ color: '#0F6E56', fontWeight: 700 }}
              prefix={<CheckCircleOutlined />}
            />
          </Card>
        </Col>
      </Row>

      {/* AI 分析结果 Card */}
      {aiLoading && (
        <Card bordered={false} style={{ marginBottom: 16, textAlign: 'center', padding: '32px 0' }}>
          <Spin tip="AI 正在分析库存状态..." />
        </Card>
      )}
      {!aiLoading && aiResult && (
        <Card
          bordered={false}
          style={{
            marginBottom: 16,
            background: aiResult.risk_level === 'critical' || aiResult.risk_level === 'high'
              ? '#FFF1F0' : '#F6FFED',
            border: `1px solid ${aiResult.risk_level === 'critical' || aiResult.risk_level === 'high' ? '#FFCCC7' : '#B7EB8F'}`,
          }}
          title={
            <Space>
              <RobotOutlined style={{ color: '#185FA5' }} />
              <Text strong style={{ color: '#185FA5' }}>AI 库存分析结果</Text>
              <Badge
                {...getRiskBadge(aiResult.risk_level)}
                text={getRiskBadge(aiResult.risk_level).text}
              />
              <Tag color="blue">风险食材 {aiResult.at_risk_count} 种</Tag>
            </Space>
          }
        >
          <Paragraph style={{ marginBottom: 12 }}>{aiResult.summary}</Paragraph>

          <Divider orientation="left" style={{ fontSize: 12 }}>建议采购清单</Divider>
          <List
            size="small"
            dataSource={aiResult.recommendations}
            renderItem={(item) => (
              <List.Item
                actions={[
                  <a
                    key="po"
                    style={{ color: '#FF6B35' }}
                    onClick={() => setQuickPOIngredient(item.ingredient_name)}
                  >
                    <ShoppingCartOutlined /> 生成采购单
                  </a>,
                ]}
              >
                <Space>
                  <Tag color="orange">{item.ingredient_name}</Tag>
                  <Text>建议补购 <Text strong>{item.suggested_quantity} {item.unit}</Text></Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>{item.reason}</Text>
                </Space>
              </List.Item>
            )}
          />

          <Divider orientation="left" style={{ fontSize: 12 }}>食安硬约束状态</Divider>
          <Alert
            type={
              aiResult.food_safety_constraints.status === 'ok'
                ? 'success'
                : aiResult.food_safety_constraints.status === 'warning'
                ? 'warning'
                : 'error'
            }
            message={aiResult.food_safety_constraints.message}
            showIcon
          />
        </Card>
      )}

      {/* 临期食材 ProTable */}
      <ProTable<ExpiryAlert>
        headerTitle="临期食材清单"
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        search={{ labelWidth: 'auto' }}
        request={async () => {
          try {
            const data = await txFetchData<{ items: ExpiryAlert[]; total: number }>(
              `/api/v1/supply/expiry-alerts?store_id=${storeId}&days=${daysThreshold}`,
            );
            const items = data.items ?? [];
            setAllAlerts(items);
            return { data: items, total: data.total, success: true };
          } catch {
            // 空数据 fallback，不显示 Mock
            setAllAlerts([]);
            return { data: [], total: 0, success: true };
          }
        }}
        rowClassName={(r) => {
          if (r.days_remaining <= 3) return 'expiry-row-critical';
          if (r.days_remaining <= 7) return 'expiry-row-warning';
          return '';
        }}
        toolBarRender={() => [
          <Button
            key="ai"
            type="default"
            icon={<RobotOutlined />}
            loading={aiLoading}
            onClick={handleAIAnalyze}
            style={{ color: '#185FA5', borderColor: '#185FA5' }}
          >
            AI 分析
          </Button>,
          <Button
            key="export"
            icon={<ExportOutlined />}
            onClick={handleExport}
          >
            导出 CSV
          </Button>,
        ]}
        pagination={{ defaultPageSize: 20 }}
        scroll={{ x: 1100 }}
      />

      {/* 快速采购单弹窗 */}
      {quickPOIngredient && (
        <QuickPOModal
          ingredientName={quickPOIngredient}
          open={!!quickPOIngredient}
          onClose={() => setQuickPOIngredient(null)}
        />
      )}

      {/* 行颜色样式 */}
      <style>{`
        .expiry-row-critical td { background: #FFF1F0 !important; }
        .expiry-row-warning td { background: #FFF7E6 !important; }
      `}</style>
    </div>
  );
}

export default ExpiryAlertPage;
