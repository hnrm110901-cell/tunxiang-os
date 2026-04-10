/**
 * MenuSkillMatch -- 菜品技能匹配分析
 * P2-7 · 菜品技能匹配
 *
 * 功能：
 *  1. 选择菜品分类 -> 分析技能覆盖
 *  2. 技能覆盖热力图（门店 x 技能）
 *  3. 门店技能缺口列表 ProTable
 *  4. 推荐培训计划卡片
 *  5. 可借调厨师列表
 *
 * API:
 *  POST /api/v1/agent/growth_coach/menu_skill_match
 */

import { useState } from 'react';
import {
  Button,
  Card,
  Col,
  Input,
  List,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import { Heatmap } from '@ant-design/charts';
import {
  BookOutlined,
  ExperimentOutlined,
  SearchOutlined,
  SwapOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { txFetch } from '../../../api';

const { Title, Text } = Typography;

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface StoreGap {
  store_id: string;
  store_name: string;
  missing_skills: string[];
  missing_labels: string[];
  gap_count: number;
  action: string;
}

interface HeatmapItem {
  store_name: string;
  skill_label: string;
  count: number;
}

interface TrainingPlan {
  store_id: string;
  store_name: string;
  skill_label: string;
  course_name: string;
  target_trainees: number;
  estimated_hours: number;
}

interface TransferableChef {
  employee_id: string;
  emp_name: string;
  store_id: string;
  store_name: string;
  matched_skills: string[];
  matched_labels: string[];
}

interface MatchData {
  cuisine_type: string;
  dish_name: string;
  required_skills: string[];
  required_skill_labels: string[];
  store_count: number;
  gap_store_count: number;
  store_gaps: StoreGap[];
  heatmap: HeatmapItem[];
  training_plans: TrainingPlan[];
  transferable_chefs: TransferableChef[];
  ai_tag: string;
}

// ─── 常量 ────────────────────────────────────────────────────────────────────

const CUISINE_OPTIONS = [
  { label: '粤菜', value: '粤菜' },
  { label: '川菜', value: '川菜' },
  { label: '湘菜', value: '湘菜' },
  { label: '日料', value: '日料' },
  { label: '西餐', value: '西餐' },
  { label: '烘焙', value: '烘焙' },
  { label: '火锅', value: '火锅' },
  { label: '海鲜', value: '海鲜' },
  { label: '面点', value: '面点' },
  { label: '烧烤', value: '烧烤' },
];

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function MenuSkillMatch() {
  const [cuisineType, setCuisineType] = useState('湘菜');
  const [dishName, setDishName] = useState('');
  const [data, setData] = useState<MatchData | null>(null);
  const [loading, setLoading] = useState(false);

  const handleAnalyze = async () => {
    setLoading(true);
    try {
      const resp = await txFetch<{ data: MatchData }>('/api/v1/agent/growth_coach/menu_skill_match', {
        method: 'POST',
        body: JSON.stringify({
          cuisine_type: cuisineType,
          dish_name: dishName || undefined,
        }),
      });
      setData(resp.data?.data || resp.data);
    } catch {
      message.error('分析失败');
    } finally {
      setLoading(false);
    }
  };

  // 缺口表列
  const gapColumns = [
    { title: '门店', dataIndex: 'store_name', key: 'store' },
    {
      title: '缺少技能',
      dataIndex: 'missing_labels',
      key: 'skills',
      render: (labels: string[]) =>
        labels.map((l) => <Tag key={l} color="red" style={{ marginBottom: 4 }}>{l}</Tag>),
    },
    { title: '缺口数', dataIndex: 'gap_count', key: 'gap', align: 'center' as const },
    {
      title: '建议操作',
      dataIndex: 'action',
      key: 'action',
      render: (v: string) => (
        <Tag color={v === '需要招聘' ? 'red' : 'gold'}>{v}</Tag>
      ),
    },
  ];

  // 培训计划列
  const trainingColumns = [
    { title: '门店', dataIndex: 'store_name', key: 'store' },
    { title: '技能', dataIndex: 'skill_label', key: 'skill' },
    { title: '培训课程', dataIndex: 'course_name', key: 'course' },
    { title: '目标学员数', dataIndex: 'target_trainees', key: 'trainees', align: 'center' as const },
    { title: '预计学时', dataIndex: 'estimated_hours', key: 'hours', align: 'center' as const, render: (v: number) => `${v}h` },
  ];

  // 借调厨师列
  const chefColumns = [
    { title: '姓名', dataIndex: 'emp_name', key: 'name' },
    { title: '所属门店', dataIndex: 'store_name', key: 'store' },
    {
      title: '匹配技能',
      dataIndex: 'matched_labels',
      key: 'skills',
      render: (labels: string[]) =>
        labels.map((l) => <Tag key={l} color="green" style={{ marginBottom: 4 }}>{l}</Tag>),
    },
  ];

  return (
    <div>
      <Title level={4}>菜品技能匹配分析</Title>

      {/* 筛选栏 */}
      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          value={cuisineType}
          onChange={setCuisineType}
          style={{ width: 140 }}
          options={CUISINE_OPTIONS}
          placeholder="菜品分类"
        />
        <Input
          value={dishName}
          onChange={(e) => setDishName(e.target.value)}
          placeholder="菜品名称（可选）"
          style={{ width: 200 }}
        />
        <Button
          type="primary"
          icon={<SearchOutlined />}
          onClick={handleAnalyze}
          loading={loading}
        >
          分析技能覆盖
        </Button>
      </Space>

      {data && (
        <>
          {/* 概览卡片 */}
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={6}>
              <Card size="small">
                <Text type="secondary">菜品分类</Text>
                <Title level={4} style={{ margin: '4px 0' }}>
                  {data.cuisine_type}
                  {data.dish_name && <Text type="secondary" style={{ fontSize: 14 }}> ({data.dish_name})</Text>}
                </Title>
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Text type="secondary">所需技能</Text>
                <div style={{ marginTop: 4 }}>
                  {data.required_skill_labels.map((l) => (
                    <Tag key={l} color="blue" style={{ marginBottom: 4 }}>{l}</Tag>
                  ))}
                </div>
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Text type="secondary">覆盖门店</Text>
                <Title level={4} style={{ margin: '4px 0' }}>
                  {data.store_count - data.gap_store_count}/{data.store_count}
                  <Text type="secondary" style={{ fontSize: 14 }}> 家达标</Text>
                </Title>
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Text type="secondary">技能缺口</Text>
                <Title level={4} style={{ margin: '4px 0', color: data.gap_store_count > 0 ? '#A32D2D' : '#0F6E56' }}>
                  {data.gap_store_count}
                  <Text type="secondary" style={{ fontSize: 14 }}> 家有缺口</Text>
                </Title>
              </Card>
            </Col>
          </Row>

          {/* 热力图 */}
          {data.heatmap.length > 0 && (
            <Card
              title={
                <Space>
                  <ExperimentOutlined />
                  <span>技能覆盖热力图</span>
                  <Tag color="blue">{data.ai_tag}</Tag>
                </Space>
              }
              style={{ marginBottom: 16 }}
            >
              <Heatmap
                data={data.heatmap}
                xField="store_name"
                yField="skill_label"
                colorField="count"
                height={Math.max(200, data.required_skill_labels.length * 60)}
                color={['#A32D2D', '#BA7517', '#F5C842', '#7EC384', '#0F6E56']}
                meta={{ count: { alias: '掌握人数' } }}
                label={{
                  style: { fill: '#fff', fontSize: 12 },
                }}
                tooltip={{
                  formatter: (datum) => ({
                    name: `${datum.store_name} - ${datum.skill_label}`,
                    value: `${datum.count}人`,
                  }),
                }}
              />
            </Card>
          )}

          {/* 缺口列表 */}
          {data.store_gaps.length > 0 && (
            <Card
              title={
                <Space>
                  <WarningOutlined style={{ color: '#A32D2D' }} />
                  <span>门店技能缺口</span>
                </Space>
              }
              style={{ marginBottom: 16 }}
            >
              <Table
                dataSource={data.store_gaps}
                columns={gapColumns}
                rowKey="store_id"
                pagination={false}
                size="small"
              />
            </Card>
          )}

          <Row gutter={16}>
            {/* 培训计划 */}
            {data.training_plans.length > 0 && (
              <Col span={14}>
                <Card
                  title={
                    <Space>
                      <BookOutlined />
                      <span>推荐培训计划</span>
                      <Tag color="blue">{data.ai_tag}</Tag>
                    </Space>
                  }
                >
                  <Table
                    dataSource={data.training_plans}
                    columns={trainingColumns}
                    rowKey={(r) => `${r.store_id}-${r.skill_label}`}
                    pagination={false}
                    size="small"
                  />
                </Card>
              </Col>
            )}

            {/* 可借调厨师 */}
            {data.transferable_chefs.length > 0 && (
              <Col span={10}>
                <Card
                  title={
                    <Space>
                      <SwapOutlined />
                      <span>可借调厨师</span>
                    </Space>
                  }
                >
                  <Table
                    dataSource={data.transferable_chefs}
                    columns={chefColumns}
                    rowKey="employee_id"
                    pagination={false}
                    size="small"
                  />
                </Card>
              </Col>
            )}
          </Row>
        </>
      )}
    </div>
  );
}
