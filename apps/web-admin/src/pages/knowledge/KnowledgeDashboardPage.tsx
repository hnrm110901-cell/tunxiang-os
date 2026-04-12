/**
 * 知识库管理驾驶舱 — 概览统计 + 快捷入口
 */
import { useState, useEffect } from 'react';
import { Card, Row, Col, Typography, Tag, Space, Button } from 'antd';
import { StatisticCard } from '@ant-design/pro-components';
import {
  FileTextOutlined,
  SearchOutlined,
  UploadOutlined,
  AlertOutlined,
  DatabaseOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';

const { Text } = Typography;

const C = {
  primary: '#FF6B35',
  success: '#0F6E56',
  warning: '#BA7517',
  danger: '#A32D2D',
  info: '#185FA5',
  bg: '#F8F7F5',
  border: '#E8E6E1',
  textSub: '#5F5E5A',
  textMuted: '#B4B2A9',
};

// Mock 数据（演示用）
const MOCK_STATS = {
  total_documents: 128,
  published_documents: 96,
  total_chunks: 3420,
  stale_documents: 7,
  collections: ['菜品知识', '运营SOP', '食安标准', '培训手册', '设备维护'],
};

export default function KnowledgeDashboardPage() {
  const navigate = useNavigate();
  const [stats] = useState(MOCK_STATS);

  return (
    <div style={{ padding: 24, minWidth: 1080 }}>
      {/* Header */}
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ margin: 0, fontSize: 20, color: '#2C2C2A' }}>
          知识库管理
        </h2>
        <Text style={{ fontSize: 13, color: C.textSub }}>
          管理企业知识文档、检索测试、同步状态监控
          <Tag color="blue" style={{ marginLeft: 8, fontSize: 11 }}>Phase 4</Tag>
        </Text>
      </div>

      {/* KPI 卡片 */}
      <Row gutter={16} style={{ marginBottom: 20 }}>
        <Col span={6}>
          <StatisticCard
            statistic={{
              title: '文档总数',
              value: stats.total_documents,
              suffix: '篇',
              valueStyle: { color: C.info, fontSize: 28 },
            }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            statistic={{
              title: '已发布',
              value: stats.published_documents,
              suffix: '篇',
              valueStyle: { color: C.success, fontSize: 28 },
            }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            statistic={{
              title: '知识块',
              value: stats.total_chunks,
              suffix: '条',
              valueStyle: { color: '#722ed1', fontSize: 28 },
            }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            statistic={{
              title: '过期待审',
              value: stats.stale_documents,
              suffix: '篇',
              valueStyle: { color: C.danger, fontSize: 28 },
              description: (
                <Space size={4}>
                  <AlertOutlined style={{ color: C.warning }} />
                  <span style={{ color: C.warning, fontSize: 12 }}>超过90天未更新</span>
                </Space>
              ),
            }}
          />
        </Col>
      </Row>

      {/* 快捷入口 */}
      <Row gutter={16} style={{ marginBottom: 20 }}>
        <Col span={8}>
          <Card
            hoverable
            onClick={() => navigate('/knowledge/documents')}
            style={{ borderLeft: `3px solid ${C.info}` }}
          >
            <Space>
              <FileTextOutlined style={{ fontSize: 24, color: C.info }} />
              <div>
                <div style={{ fontSize: 14, fontWeight: 600 }}>文档管理</div>
                <Text style={{ fontSize: 12, color: C.textMuted }}>查看、编辑、发布知识文档</Text>
              </div>
            </Space>
          </Card>
        </Col>
        <Col span={8}>
          <Card
            hoverable
            onClick={() => navigate('/knowledge/upload')}
            style={{ borderLeft: `3px solid ${C.success}` }}
          >
            <Space>
              <UploadOutlined style={{ fontSize: 24, color: C.success }} />
              <div>
                <div style={{ fontSize: 14, fontWeight: 600 }}>上传文档</div>
                <Text style={{ fontSize: 12, color: C.textMuted }}>上传新文档到知识库</Text>
              </div>
            </Space>
          </Card>
        </Col>
        <Col span={8}>
          <Card
            hoverable
            onClick={() => navigate('/knowledge/search')}
            style={{ borderLeft: `3px solid ${C.primary}` }}
          >
            <Space>
              <SearchOutlined style={{ fontSize: 24, color: C.primary }} />
              <div>
                <div style={{ fontSize: 14, fontWeight: 600 }}>检索测试</div>
                <Text style={{ fontSize: 12, color: C.textMuted }}>测试知识库语义检索效果</Text>
              </div>
            </Space>
          </Card>
        </Col>
      </Row>

      {/* 知识库集合列表 */}
      <Card
        title={
          <Space>
            <DatabaseOutlined style={{ color: C.primary }} />
            <span>知识库集合</span>
          </Space>
        }
      >
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: C.bg }}>
              {['集合名称', '状态'].map((h) => (
                <th key={h} style={{
                  padding: '10px 14px', textAlign: 'left',
                  fontSize: 12, color: C.textSub, fontWeight: 600,
                  borderBottom: `1px solid ${C.border}`,
                }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {stats.collections.map((name, i) => (
              <tr key={name} style={{
                borderBottom: `1px solid ${C.border}`,
                background: i % 2 === 0 ? '#fff' : '#fafaf9',
              }}>
                <td style={{ padding: '12px 14px', fontSize: 13, fontWeight: 500 }}>
                  {name}
                </td>
                <td style={{ padding: '12px 14px' }}>
                  <Tag color="green">已同步</Tag>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
