/**
 * 知识检索测试页 — 测试语义搜索效果
 */
import { useState } from 'react';
import { Card, Input, Button, Select, Typography, Space, Tag, Empty, List } from 'antd';
import {
  SearchOutlined,
  ThunderboltOutlined,
  FileTextOutlined,
} from '@ant-design/icons';

const { TextArea } = Input;
const { Text, Paragraph } = Typography;

const C = {
  primary: '#FF6B35',
  success: '#0F6E56',
  warning: '#BA7517',
  info: '#185FA5',
  textSub: '#5F5E5A',
  textMuted: '#B4B2A9',
  border: '#E8E6E1',
};

interface SearchResult {
  id: string;
  document_title: string;
  chunk_text: string;
  score: number;
  collection: string;
}

const COLLECTIONS = [
  { label: '全部集合', value: '' },
  { label: '菜品知识', value: '菜品知识' },
  { label: '运营SOP', value: '运营SOP' },
  { label: '食安标准', value: '食安标准' },
  { label: '培训手册', value: '培训手册' },
  { label: '设备维护', value: '设备维护' },
];

// Mock 搜索结果
const MOCK_RESULTS: SearchResult[] = [
  {
    id: 'c001',
    document_title: '剁椒鱼头标准制作流程',
    chunk_text: '剁椒鱼头选用鲢鱼头，重量1.5-2斤为佳。鱼头对半剖开，用料酒、盐腌制15分钟。剁椒酱需提前用蒜末、姜末炒香...',
    score: 0.94,
    collection: '菜品知识',
  },
  {
    id: 'c002',
    document_title: '剁椒鱼头标准制作流程',
    chunk_text: '蒸制要求：大火蒸8-10分钟，鱼眼凸出发白即为熟透。出锅后淋上热油激发香气，撒上葱花装饰...',
    score: 0.89,
    collection: '菜品知识',
  },
  {
    id: 'c003',
    document_title: '食品安全自检手册 v3.0',
    chunk_text: '鲜鱼类食材到货后需在30分钟内完成验收，检查鱼鳃颜色（鲜红为佳）、鱼眼清澈度、鱼体弹性...',
    score: 0.72,
    collection: '食安标准',
  },
];

function scoreColor(score: number): string {
  if (score >= 0.85) return C.success;
  if (score >= 0.7) return C.warning;
  return C.textMuted;
}

export default function SearchTestPage() {
  const [query, setQuery] = useState('');
  const [collection, setCollection] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searched, setSearched] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleSearch = () => {
    if (!query.trim()) return;
    setLoading(true);
    // TODO: 调用 knowledgeApi.searchKnowledge
    setTimeout(() => {
      setResults(MOCK_RESULTS);
      setSearched(true);
      setLoading(false);
    }, 600);
  };

  return (
    <div style={{ padding: 24, maxWidth: 960 }}>
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ margin: 0, fontSize: 20, color: '#2C2C2A' }}>
          <Space>
            <ThunderboltOutlined style={{ color: C.primary }} />
            检索测试
          </Space>
        </h2>
        <Text style={{ fontSize: 13, color: C.textSub }}>
          测试知识库语义检索效果，验证 RAG 召回质量
        </Text>
      </div>

      {/* 搜索区 */}
      <Card style={{ marginBottom: 20 }}>
        <div style={{ marginBottom: 12 }}>
          <TextArea
            placeholder="输入查询问题，例如：剁椒鱼头怎么做？"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            rows={2}
            style={{ fontSize: 14 }}
          />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Select
            value={collection}
            onChange={setCollection}
            style={{ width: 160 }}
            options={COLLECTIONS}
          />
          <Button
            type="primary"
            icon={<SearchOutlined />}
            onClick={handleSearch}
            loading={loading}
            disabled={!query.trim()}
          >
            检索
          </Button>
        </div>
      </Card>

      {/* 搜索结果 */}
      {searched && (
        <Card
          title={
            <Space>
              <span>检索结果</span>
              <Tag color="blue">{results.length} 条匹配</Tag>
            </Space>
          }
        >
          {results.length > 0 ? (
            <List
              dataSource={results}
              renderItem={(item) => (
                <List.Item style={{ padding: '16px 0', borderBottom: `1px solid ${C.border}` }}>
                  <div style={{ width: '100%' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                      <Space>
                        <FileTextOutlined style={{ color: C.info }} />
                        <Text strong style={{ fontSize: 13 }}>{item.document_title}</Text>
                        <Tag color="blue" style={{ fontSize: 11 }}>{item.collection}</Tag>
                      </Space>
                      <Tag
                        color={item.score >= 0.85 ? 'green' : item.score >= 0.7 ? 'orange' : 'default'}
                        style={{ fontSize: 12, fontWeight: 600 }}
                      >
                        相似度 {(item.score * 100).toFixed(0)}%
                      </Tag>
                    </div>
                    <Paragraph
                      style={{ margin: 0, fontSize: 13, color: C.textSub, lineHeight: 1.6 }}
                      ellipsis={{ rows: 3 }}
                    >
                      {item.chunk_text}
                    </Paragraph>
                  </div>
                </List.Item>
              )}
            />
          ) : (
            <Empty description="未找到匹配的知识" />
          )}
        </Card>
      )}
    </div>
  );
}
