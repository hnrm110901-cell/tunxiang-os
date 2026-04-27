import { Placeholder } from '../_Placeholder'

export default function ReleasePage() {
  return (
    <Placeholder
      no="08"
      title="灰度发布"
      description="特性开关（feature_flags）+ 灰度策略，支持按门店 / 品牌维度放量。"
      todos={['flags/ 配置同步', '灰度计划 5%→50%→100%', '错误率自动回滚阈值']}
    />
  )
}
