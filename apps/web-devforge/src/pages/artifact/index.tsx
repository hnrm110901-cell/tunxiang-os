import { Placeholder } from '../_Placeholder'

export default function ArtifactPage() {
  return (
    <Placeholder
      no="05"
      title="制品库"
      description="镜像仓库 / Package / SBOM 一站式管理，支持签名验证。"
      todos={['Harbor 镜像列表', 'PyPI / npm 私服', 'SBOM 生成 + CVE 关联']}
    />
  )
}
