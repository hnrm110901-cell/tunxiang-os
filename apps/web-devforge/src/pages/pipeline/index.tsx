import { Placeholder } from '../_Placeholder'

export default function PipelinePage() {
  return (
    <Placeholder
      no="04"
      title="流水线"
      description="基于 Argo Workflows / Tekton 的 CI/CD 编排，支持 DAG 可视化。"
      todos={['流水线列表 + 状态汇总', '运行详情 + 实时日志（xterm.js）', '模板库（Python / TS / Edge）']}
    />
  )
}
