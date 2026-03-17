import React from 'react';
import { Card, Empty } from 'antd';
import { ThunderboltOutlined } from '@ant-design/icons';

const LLMConfigPage: React.FC = () => (
  <div style={{ padding: 0 }}>
    <Card>
      <Empty
        image={<ThunderboltOutlined style={{ fontSize: 48, color: 'rgba(255,255,255,0.15)' }} />}
        description={
          <div>
            <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8, color: 'var(--text-primary)' }}>LLM 选型配置</div>
            <div style={{ color: 'var(--text-tertiary)', fontSize: 13 }}>为商户配置 LLM 模型选型，平衡成本与效果</div>
          </div>
        }
      />
    </Card>
  </div>
);

export default LLMConfigPage;
