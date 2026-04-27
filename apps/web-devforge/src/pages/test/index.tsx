import { Placeholder } from '../_Placeholder'

export default function TestPage() {
  return (
    <Placeholder
      no="06"
      title="测试中心"
      description="用例管理 + 覆盖率 + Tier 1 用例红绿看板。"
      todos={['Tier 1/2/3 用例分类', '覆盖率趋势图（ECharts）', 'DEMO 环境验收快照']}
    />
  )
}
