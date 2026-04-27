import { Placeholder } from '../_Placeholder'

export default function SourcePage() {
  return (
    <Placeholder
      no="03"
      title="代码协作"
      description="对接 GitLab / Gitea。支持 MR 评审、代码搜索、Owner 巡检。"
      todos={['仓库列表', 'Merge Request 列表 + 评审', 'Owner 文件 + CODEOWNERS 校验']}
    />
  )
}
