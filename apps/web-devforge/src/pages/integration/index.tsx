import { Placeholder } from '../_Placeholder'

export default function IntegrationPage() {
  return (
    <Placeholder
      no="13"
      title="集成中心"
      description="对接 Webhook / MCP Server / OpenAPI 网关。"
      todos={['Webhook 配置 + 重试日志', 'MCP Server 列表 + 健康', 'OpenAPI Schema 浏览']}
    />
  )
}
