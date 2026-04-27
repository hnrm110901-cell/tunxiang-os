import { useState } from 'react'
import { Dropdown, Modal, Tag, Space } from 'antd'
import { ChevronDown } from 'lucide-react'
import { useEnvStore, ENV_LABELS, ENV_ORDER, type DevforgeEnv } from '@/stores/env'
import { COLORS } from '@/styles/theme'

const ENV_TONE: Record<DevforgeEnv, string> = {
  dev: COLORS.blue,
  test: COLORS.green,
  staging: COLORS.yellow,
  gray: COLORS.amber600,
  prod: COLORS.red,
}

export function EnvSwitcher() {
  const { currentEnv, setEnv } = useEnvStore()
  const [pendingEnv, setPendingEnv] = useState<DevforgeEnv | null>(null)

  const isProd = currentEnv === 'prod'

  const handleChoose = (env: DevforgeEnv) => {
    if (env === currentEnv) return
    if (env === 'prod') {
      setPendingEnv(env)
    } else {
      setEnv(env)
    }
  }

  return (
    <>
      <Dropdown
        menu={{
          items: ENV_ORDER.map((e) => ({
            key: e,
            label: (
              <Space>
                <span
                  style={{
                    display: 'inline-block',
                    width: 8,
                    height: 8,
                    borderRadius: 4,
                    background: ENV_TONE[e],
                  }}
                />
                {ENV_LABELS[e]}
                <span className="mono" style={{ color: '#64748b', fontSize: 11 }}>
                  {e}
                </span>
              </Space>
            ),
            onClick: () => handleChoose(e),
          })),
        }}
        trigger={['click']}
      >
        <div
          className={isProd ? 'devforge-prod-warning' : ''}
          style={{
            padding: '4px 12px',
            borderRadius: 6,
            cursor: 'pointer',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            background: COLORS.slate800,
            border: `1px solid ${isProd ? COLORS.red : COLORS.slate700}`,
            color: '#fff',
            fontSize: 13,
            userSelect: 'none',
          }}
        >
          <Tag color={ENV_TONE[currentEnv]} style={{ margin: 0, fontWeight: 600 }}>
            {ENV_LABELS[currentEnv]}
          </Tag>
          <ChevronDown size={14} />
        </div>
      </Dropdown>

      <Modal
        open={!!pendingEnv}
        title="切换到生产环境？"
        okText="确认切换到 PROD"
        cancelText="取消"
        okButtonProps={{ danger: true }}
        onOk={() => {
          if (pendingEnv) setEnv(pendingEnv)
          setPendingEnv(null)
        }}
        onCancel={() => setPendingEnv(null)}
      >
        <p>切换到生产环境后，所有操作将作用于真实门店流量。</p>
        <p style={{ color: COLORS.red, fontWeight: 600 }}>请再次确认你知道自己在做什么。</p>
      </Modal>
    </>
  )
}
