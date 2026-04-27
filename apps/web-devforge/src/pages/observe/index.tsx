import { Placeholder } from '../_Placeholder'

export default function ObservePage() {
  return (
    <Placeholder
      no="10"
      title="可观测"
      description="Metrics + Logs + Traces 三件套，对接 Prometheus / Loki / Tempo。"
      todos={['服务大盘（ECharts）', '日志聚合搜索', '调用链拓扑（AntV G6）']}
    />
  )
}
