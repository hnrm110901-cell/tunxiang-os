import { Card, Col, Row, Statistic, Typography } from 'antd'
import { Boxes, Workflow, Rocket, ShieldCheck } from 'lucide-react'

const { Title } = Typography

export default function DashboardPage() {
  return (
    <div>
      <Title level={3} style={{ margin: 0, marginBottom: 16 }}>
        <span className="mono" style={{ color: '#64748b', marginRight: 12 }}>
          01
        </span>
        工作台
      </Title>

      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} md={6}>
          <Card>
            <Statistic
              title={
                <span>
                  <Boxes size={14} style={{ verticalAlign: -2 }} /> 应用总数
                </span>
              }
              value={5}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={6}>
          <Card>
            <Statistic
              title={
                <span>
                  <Workflow size={14} style={{ verticalAlign: -2 }} /> 今日流水线
                </span>
              }
              value={0}
              suffix="/ 0 成功"
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={6}>
          <Card>
            <Statistic
              title={
                <span>
                  <Rocket size={14} style={{ verticalAlign: -2 }} /> 待发布
                </span>
              }
              value={0}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={6}>
          <Card>
            <Statistic
              title={
                <span>
                  <ShieldCheck size={14} style={{ verticalAlign: -2 }} /> 高危告警
                </span>
              }
              value={0}
            />
          </Card>
        </Col>
      </Row>

      <Card title="动态信息流" style={{ marginTop: 16 }}>
        <span style={{ color: '#94a3b8' }}>TODO：接入 events / pipeline runs / deployments 流</span>
      </Card>
    </div>
  )
}
