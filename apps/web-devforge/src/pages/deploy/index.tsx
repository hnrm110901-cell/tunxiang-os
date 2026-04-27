import { Placeholder } from '../_Placeholder'

export default function DeployPage() {
  return (
    <Placeholder
      no="07"
      title="部署中心"
      description="Helm + ArgoCD 部署编排，五环境矩阵视图。"
      todos={['部署历史时间线', '一键回滚 + diff 对比', '蓝绿 / 滚动策略']}
    />
  )
}
