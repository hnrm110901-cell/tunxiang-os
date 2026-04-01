/**
 * ShiftSummaryPanel — 班次复盘摘要面板
 *
 * 用于店长工作台、日清日结页。
 * 展示 Agent 生成的班次经营总结。
 */
import { Card, Descriptions, Tag, Typography, Divider, List } from 'antd';
import { RiseOutlined, FallOutlined } from '@ant-design/icons';

const { Text, Paragraph, Title } = Typography;

export interface ShiftMetric {
  label: string;
  value: string;
  changeRate?: number;
  isAnomaly?: boolean;
}

export interface ShiftAnomaly {
  title: string;
  description: string;
  severity: 'warning' | 'critical';
}

export interface ShiftSummaryPanelProps {
  shiftName: string;
  summary: string;
  metrics: ShiftMetric[];
  anomalies: ShiftAnomaly[];
  improvements?: string[];
}

export function ShiftSummaryPanel({
  shiftName,
  summary,
  metrics,
  anomalies,
  improvements = [],
}: ShiftSummaryPanelProps) {
  return (
    <Card title={`${shiftName} 复盘`} size="small">
      <Paragraph style={{ fontSize: 13, color: '#5F5E5A' }}>{summary}</Paragraph>

      <Divider style={{ margin: '12px 0' }} />

      <Descriptions column={2} size="small" bordered>
        {metrics.map((m) => (
          <Descriptions.Item
            key={m.label}
            label={m.label}
            labelStyle={{ fontSize: 12 }}
            contentStyle={{ fontSize: 13 }}
          >
            <span style={{ fontWeight: 600, color: m.isAnomaly ? '#A32D2D' : '#2C2C2A' }}>
              {m.value}
            </span>
            {m.changeRate !== undefined && (
              <span style={{
                marginLeft: 6, fontSize: 11,
                color: m.changeRate >= 0 ? '#0F6E56' : '#A32D2D',
              }}>
                {m.changeRate >= 0 ? <RiseOutlined /> : <FallOutlined />}
                {Math.abs(m.changeRate * 100).toFixed(1)}%
              </span>
            )}
            {m.isAnomaly && <Tag color="red" style={{ marginLeft: 4, fontSize: 10 }}>异常</Tag>}
          </Descriptions.Item>
        ))}
      </Descriptions>

      {anomalies.length > 0 && (
        <>
          <Divider style={{ margin: '12px 0' }} />
          <Title level={5} style={{ fontSize: 13 }}>异常发现</Title>
          <List
            size="small"
            dataSource={anomalies}
            renderItem={(a) => (
              <List.Item>
                <List.Item.Meta
                  title={
                    <span>
                      <Tag color={a.severity === 'critical' ? 'red' : 'orange'} style={{ fontSize: 10 }}>
                        {a.severity === 'critical' ? '严重' : '警告'}
                      </Tag>
                      {a.title}
                    </span>
                  }
                  description={<Text style={{ fontSize: 12 }}>{a.description}</Text>}
                />
              </List.Item>
            )}
          />
        </>
      )}

      {improvements.length > 0 && (
        <>
          <Divider style={{ margin: '12px 0' }} />
          <Title level={5} style={{ fontSize: 13 }}>改善建议</Title>
          <List
            size="small"
            dataSource={improvements}
            renderItem={(item, i) => (
              <List.Item>
                <Text style={{ fontSize: 12 }}>{i + 1}. {item}</Text>
              </List.Item>
            )}
          />
        </>
      )}
    </Card>
  );
}
