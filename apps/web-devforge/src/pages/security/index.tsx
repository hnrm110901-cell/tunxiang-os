import { Placeholder } from '../_Placeholder'

export default function SecurityPage() {
  return (
    <Placeholder
      no="14"
      title="安全审计"
      description="CVE 跟踪 + 访问审计 + git-secrets 扫描结果聚合。"
      todos={['CVE 看板（按服务）', 'RBAC 操作审计', '密钥/证书过期提醒']}
    />
  )
}
