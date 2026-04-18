/**
 * 脉搏调研 — 员工填答 + 管理端查看
 * 路由: /hr/pulse
 */
import React, { useEffect, useState } from 'react';
import {
  Card, Typography, Input, Rate, Radio, Button, message, Checkbox, Tabs, Table, Tag, Empty, Space,
} from 'antd';
import { HeartOutlined, BarChartOutlined } from '@ant-design/icons';
import { apiClient } from '../../services/api';
import { useAuthStore } from '../../stores/authStore';

const { Title, Text, Paragraph } = Typography;

interface Question {
  id: number | string;
  type: 'rating' | 'text' | 'multi_choice';
  text: string;
  options?: string[];
  required?: boolean;
}

const PulseSurvey: React.FC = () => {
  const user = useAuthStore((s) => s.user);
  const [instanceId, setInstanceId] = useState('');
  const [questions, setQuestions] = useState<Question[]>([]);
  const [answers, setAnswers] = useState<Record<string | number, any>>({});
  const [anonymous, setAnonymous] = useState(true);
  const [results, setResults] = useState<any>(null);
  const [templateId, setTemplateId] = useState('');
  const [trends, setTrends] = useState<any[]>([]);

  // 演示：从 URL ?instance_id=... 读取；或手动输入
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const iid = params.get('instance_id');
    if (iid) setInstanceId(iid);
  }, []);

  const submit = async () => {
    if (!instanceId) { message.warning('请先输入问卷实例 ID'); return; }
    const responses = questions.map(q => ({ question_id: q.id, answer: answers[q.id] ?? '' }));
    try {
      await apiClient.post('/api/v1/hr/pulse/responses', {
        instance_id: instanceId,
        employee_id: user?.id || 'anonymous',
        responses,
        is_anonymous: anonymous,
      });
      message.success('已提交，感谢反馈');
      setAnswers({});
    } catch (e: any) { message.error(e?.response?.data?.detail || '提交失败'); }
  };

  const loadResults = async () => {
    if (!instanceId) return;
    try {
      const resp = await apiClient.get(`/api/v1/hr/pulse/instances/${instanceId}/results?with_sentiment=true`);
      setResults(resp.data);
    } catch { message.error('加载失败'); }
  };

  const loadTrends = async () => {
    if (!templateId) return;
    try {
      const resp = await apiClient.get(`/api/v1/hr/pulse/trends/${templateId}?last_n_periods=6`);
      setTrends(resp.data?.periods || []);
    } catch { /* ignore */ }
  };

  return (
    <div style={{ padding: 24 }}>
      <Title level={3}><HeartOutlined /> 脉搏调研</Title>
      <Tabs defaultActiveKey="answer" items={[
        {
          key: 'answer', label: '员工填答', children: (
            <Card>
              <Space direction="vertical" style={{ width: '100%' }}>
                <Input placeholder="问卷实例 ID" value={instanceId} onChange={e => setInstanceId(e.target.value)} />
                <Checkbox checked={anonymous} onChange={e => setAnonymous(e.target.checked)}>匿名提交（管理端看不到我的身份）</Checkbox>
                {/* 演示题目：正式场景从 instance/template 拉取 */}
                {questions.length === 0 && (
                  <Button onClick={() => setQuestions([
                    { id: 1, type: 'rating', text: '本月工作满意度（1-5）', required: true },
                    { id: 2, type: 'multi_choice', text: '最影响你的因素', options: ['薪酬', '排班', '同事关系', '晋升'] },
                    { id: 3, type: 'text', text: '请给管理者一条建议' },
                  ])}>加载示例题目</Button>
                )}
                {questions.map(q => (
                  <Card key={q.id} size="small" title={q.text}>
                    {q.type === 'rating' && <Rate value={answers[q.id] || 0} onChange={v => setAnswers(a => ({ ...a, [q.id]: v }))} />}
                    {q.type === 'multi_choice' && (
                      <Radio.Group value={answers[q.id]} onChange={e => setAnswers(a => ({ ...a, [q.id]: e.target.value }))}>
                        {(q.options || []).map(o => <Radio key={o} value={o}>{o}</Radio>)}
                      </Radio.Group>
                    )}
                    {q.type === 'text' && (
                      <Input.TextArea rows={2} value={answers[q.id] || ''} onChange={e => setAnswers(a => ({ ...a, [q.id]: e.target.value }))} />
                    )}
                  </Card>
                ))}
                {questions.length > 0 && <Button type="primary" onClick={submit}>提交</Button>}
              </Space>
            </Card>
          ),
        },
        {
          key: 'admin', label: '管理端查看', children: (
            <Card>
              <Space style={{ marginBottom: 12 }}>
                <Input placeholder="实例 ID" value={instanceId} onChange={e => setInstanceId(e.target.value)} />
                <Button onClick={loadResults}>加载结果</Button>
              </Space>
              {!results ? <Empty /> : (
                <>
                  <Paragraph>
                    回收：{results.response_count} · 匿名：{results.anonymous_count}
                    {results.sentiment && (
                      <>
                        {' '} · 情感：
                        <Tag color="green">正向 {results.sentiment.positive}</Tag>
                        <Tag color="default">中性 {results.sentiment.neutral}</Tag>
                        <Tag color="red">负向 {results.sentiment.negative}</Tag>
                      </>
                    )}
                  </Paragraph>
                  <Table
                    rowKey="question_id"
                    dataSource={results.per_question || []}
                    pagination={false}
                    columns={[
                      { title: '题目', dataIndex: 'text' },
                      { title: '类型', dataIndex: 'type' },
                      { title: '答数', dataIndex: 'count' },
                      { title: '均分/分布', render: (_: any, r: any) => (
                        r.type === 'rating' ? <Text>{r.rating_avg ?? '-'}</Text>
                          : r.type === 'multi_choice' ? <Text>{JSON.stringify(r.options_count)}</Text>
                            : <Text type="secondary">{(r.text_samples || []).slice(0, 3).join(' / ')}</Text>
                      ) },
                    ]}
                  />
                </>
              )}
              <div style={{ marginTop: 24 }}>
                <Space>
                  <Input placeholder="模板 ID（趋势）" value={templateId} onChange={e => setTemplateId(e.target.value)} />
                  <Button icon={<BarChartOutlined />} onClick={loadTrends}>加载趋势</Button>
                </Space>
                {trends.length > 0 && (
                  <Table
                    style={{ marginTop: 12 }}
                    rowKey="instance_id"
                    dataSource={trends}
                    pagination={false}
                    columns={[
                      { title: '日期', dataIndex: 'scheduled_date' },
                      { title: '回收', dataIndex: 'response_count' },
                      { title: '平均评分', dataIndex: 'avg_rating' },
                    ]}
                  />
                )}
              </div>
            </Card>
          ),
        },
      ]} />
    </div>
  );
};

export default PulseSurvey;
