/**
 * OnlineScoringPage -- 在线打分
 * 域F tx-org | v254 review_scores
 *
 * 功能：
 *  - 选择评审周期 -> 显示待评员工列表
 *  - 打分表单（5维滑块 + 评语输入）
 *  - 提交打分
 *
 * API:
 *   GET  /api/v1/org/performance/review-cycles (选择周期)
 *   GET  /api/v1/org/performance/review-cycles/:id/my-pending
 *   POST /api/v1/org/performance/review-cycles/:id/scores
 */

import { useEffect, useRef, useState } from 'react';
import {
  Button,
  Card,
  Col,
  Drawer,
  Form,
  Input,
  List,
  message,
  Row,
  Select,
  Slider,
  Space,
  Tag,
  Typography,
} from 'antd';
import { CheckCircleOutlined, EditOutlined } from '@ant-design/icons';
import { txFetchData } from '../../../api';
import { getTokenPayload } from '../../../api/client';

const { Title, Text } = Typography;
const { TextArea } = Input;

// ─── Types ───────────────────────────────────────────────────────────────────

interface CycleOption {
  id: string;
  cycle_name: string;
  status: string;
}

interface PendingEmployee {
  employee_id: string;
  emp_name: string;
  role: string;
  store_id: string | null;
  store_name: string | null;
  scored: boolean;
  score_status: string | null;
}

interface DimensionConfig {
  name: string;
  weight: number;
  max_score: number;
}

// ─── Default Dimensions ──────────────────────────────────────────────────────

const DEFAULT_DIMS: DimensionConfig[] = [
  { name: '服务质量', weight: 25, max_score: 100 },
  { name: '销售业绩', weight: 25, max_score: 100 },
  { name: '出勤纪律', weight: 20, max_score: 100 },
  { name: '技能成长', weight: 15, max_score: 100 },
  { name: '团队协作', weight: 15, max_score: 100 },
];

const SLIDER_MARKS = { 0: '0', 25: '25', 50: '50', 75: '75', 100: '100' };

// ─── Component ───────────────────────────────────────────────────────────────

export default function OnlineScoringPage() {
  const [messageApi, contextHolder] = message.useMessage();
  const [cycles, setCycles] = useState<CycleOption[]>([]);
  const [selectedCycleId, setSelectedCycleId] = useState<string | null>(null);
  const [cycleDimensions, setCycleDimensions] = useState<DimensionConfig[]>(DEFAULT_DIMS);
  const [employees, setEmployees] = useState<PendingEmployee[]>([]);
  const [loading, setLoading] = useState(false);

  // Drawer state
  const [drawerVisible, setDrawerVisible] = useState(false);
  const [scoringEmployee, setScoringEmployee] = useState<PendingEmployee | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm();

  const user = getTokenPayload();
  const reviewerId = user?.user_id || '';

  // Fetch scoring cycles
  useEffect(() => {
    (async () => {
      try {
        const res = (await txFetchData(
          '/api/v1/org/performance/review-cycles?status=scoring&size=50'
        )) as { items: CycleOption[] };
        setCycles(res.items || []);
        // Auto-select from URL param
        const params = new URLSearchParams(window.location.hash.split('?')[1] || '');
        const cycleIdParam = params.get('cycle_id');
        if (cycleIdParam && res.items.some((c) => c.id === cycleIdParam)) {
          setSelectedCycleId(cycleIdParam);
        }
      } catch {
        // silent
      }
    })();
  }, []);

  // Fetch pending employees
  useEffect(() => {
    if (!selectedCycleId || !reviewerId) return;
    setLoading(true);
    (async () => {
      try {
        // Fetch cycle detail for dimensions
        const detail = (await txFetchData(
          `/api/v1/org/performance/review-cycles/${selectedCycleId}`
        )) as { dimensions?: DimensionConfig[] };
        if (detail.dimensions && detail.dimensions.length > 0) {
          setCycleDimensions(detail.dimensions);
        } else {
          setCycleDimensions(DEFAULT_DIMS);
        }

        const res = (await txFetchData(
          `/api/v1/org/performance/review-cycles/${selectedCycleId}/my-pending?reviewer_id=${reviewerId}`
        )) as { items: PendingEmployee[] };
        setEmployees(res.items || []);
      } catch {
        setEmployees([]);
      } finally {
        setLoading(false);
      }
    })();
  }, [selectedCycleId, reviewerId]);

  const openScoringDrawer = (emp: PendingEmployee) => {
    setScoringEmployee(emp);
    // Set default scores
    const defaults: Record<string, unknown> = { comment: '' };
    cycleDimensions.forEach((d) => {
      defaults[`dim_${d.name}`] = 75;
    });
    form.setFieldsValue(defaults);
    setDrawerVisible(true);
  };

  const handleSubmitScore = async () => {
    if (!scoringEmployee || !selectedCycleId) return;
    try {
      const values = await form.validateFields();
      setSubmitting(true);

      const dimensionScores: Record<string, number> = {};
      cycleDimensions.forEach((d) => {
        dimensionScores[d.name] = values[`dim_${d.name}`] ?? 0;
      });

      await txFetchData(`/api/v1/org/performance/review-cycles/${selectedCycleId}/scores`, {
        method: 'POST',
        body: JSON.stringify({
          employee_id: scoringEmployee.employee_id,
          employee_name: scoringEmployee.emp_name,
          store_id: scoringEmployee.store_id,
          reviewer_id: reviewerId,
          reviewer_name: user?.name || '',
          reviewer_role: user?.role || 'manager',
          dimension_scores: dimensionScores,
          comment: values.comment || '',
        }),
      });

      messageApi.success(`已完成对 ${scoringEmployee.emp_name} 的打分`);
      setDrawerVisible(false);

      // Refresh list
      setEmployees((prev) =>
        prev.map((e) =>
          e.employee_id === scoringEmployee.employee_id
            ? { ...e, scored: true, score_status: 'submitted' }
            : e
        )
      );
    } catch {
      messageApi.error('打分提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  const scoredCount = employees.filter((e) => e.scored).length;
  const pendingCount = employees.length - scoredCount;

  return (
    <div style={{ padding: 24 }}>
      {contextHolder}
      <Title level={4}>在线打分</Title>

      <Card style={{ marginBottom: 16 }}>
        <Row gutter={16} align="middle">
          <Col>
            <Text strong>选择评审周期：</Text>
          </Col>
          <Col flex="auto">
            <Select
              style={{ width: 360 }}
              placeholder="请选择打分中的评审周期"
              value={selectedCycleId}
              onChange={setSelectedCycleId}
              options={cycles.map((c) => ({
                label: `${c.cycle_name}`,
                value: c.id,
              }))}
            />
          </Col>
          <Col>
            {selectedCycleId && (
              <Space>
                <Tag color="processing">待评 {pendingCount}</Tag>
                <Tag color="success">已评 {scoredCount}</Tag>
              </Space>
            )}
          </Col>
        </Row>
      </Card>

      {selectedCycleId && (
        <List
          loading={loading}
          dataSource={employees}
          renderItem={(emp) => (
            <List.Item
              actions={[
                emp.scored ? (
                  <Tag key="done" color="success" icon={<CheckCircleOutlined />}>
                    已评
                  </Tag>
                ) : (
                  <Button
                    key="score"
                    type="primary"
                    size="small"
                    icon={<EditOutlined />}
                    onClick={() => openScoringDrawer(emp)}
                    style={{ backgroundColor: '#FF6B35', borderColor: '#FF6B35' }}
                  >
                    打分
                  </Button>
                ),
              ]}
            >
              <List.Item.Meta
                title={
                  <Space>
                    <Text strong>{emp.emp_name}</Text>
                    <Tag>{emp.role || '通用'}</Tag>
                  </Space>
                }
                description={emp.store_name || '未分配门店'}
              />
            </List.Item>
          )}
        />
      )}

      {/* 打分抽屉 */}
      <Drawer
        title={scoringEmployee ? `评审打分 - ${scoringEmployee.emp_name}` : '评审打分'}
        open={drawerVisible}
        onClose={() => setDrawerVisible(false)}
        width={520}
        footer={
          <Space style={{ float: 'right' }}>
            <Button onClick={() => setDrawerVisible(false)}>取消</Button>
            <Button
              type="primary"
              loading={submitting}
              onClick={handleSubmitScore}
              style={{ backgroundColor: '#FF6B35', borderColor: '#FF6B35' }}
            >
              提交评分
            </Button>
          </Space>
        }
      >
        <Form form={form} layout="vertical">
          {cycleDimensions.map((dim) => (
            <Form.Item
              key={dim.name}
              name={`dim_${dim.name}`}
              label={
                <Space>
                  <Text strong>{dim.name}</Text>
                  <Text type="secondary">权重 {dim.weight}%</Text>
                </Space>
              }
              rules={[{ required: true, message: `请为${dim.name}打分` }]}
            >
              <Slider
                min={0}
                max={dim.max_score}
                marks={SLIDER_MARKS}
                tooltip={{ formatter: (v) => `${v}分` }}
              />
            </Form.Item>
          ))}
          <Form.Item name="comment" label="综合评语">
            <TextArea rows={4} placeholder="请输入对该员工的综合评价..." maxLength={500} showCount />
          </Form.Item>
        </Form>
      </Drawer>
    </div>
  );
}
