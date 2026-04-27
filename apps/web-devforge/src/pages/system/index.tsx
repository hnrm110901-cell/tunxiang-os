import { Placeholder } from '../_Placeholder'

export default function SystemPage() {
  return (
    <Placeholder
      no="15"
      title="系统设置"
      description="用户 / 角色 / 租户 / 通知模板 / 平台元配置。"
      todos={['用户管理（SSO 同步）', 'RBAC 角色矩阵', '通知模板（飞书/企微/邮件）']}
    />
  )
}
