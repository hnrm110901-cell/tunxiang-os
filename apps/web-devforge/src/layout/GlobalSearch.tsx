import { useEffect, useState } from 'react'
import { Modal, AutoComplete, Input } from 'antd'
import { Search } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { MENU } from '@/data/menuConfig'

interface Props {
  open: boolean
  onClose: () => void
}

export function GlobalSearch({ open, onClose }: Props) {
  const navigate = useNavigate()
  const [value, setValue] = useState('')

  useEffect(() => {
    if (!open) setValue('')
  }, [open])

  // 简单基于菜单的 mock 搜索；后续接 /api/v1/devforge/search
  const options = MENU.filter(
    (m) =>
      !value ||
      m.label.toLowerCase().includes(value.toLowerCase()) ||
      m.key.toLowerCase().includes(value.toLowerCase()),
  ).map((m) => ({
    value: m.path,
    label: (
      <span style={{ display: 'inline-flex', gap: 10, alignItems: 'center' }}>
        <span style={{ color: '#64748b', fontSize: 11 }}>{m.no}</span>
        <span>{m.icon}</span>
        <span>{m.label}</span>
        <span style={{ marginLeft: 'auto', color: '#64748b', fontSize: 11 }}>{m.path}</span>
      </span>
    ),
  }))

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={620}
      destroyOnClose
      closable={false}
      styles={{ body: { padding: 12 } }}
    >
      <AutoComplete
        autoFocus
        style={{ width: '100%' }}
        value={value}
        options={options}
        onChange={setValue}
        onSelect={(path) => {
          navigate(path)
          onClose()
        }}
        popupMatchSelectWidth
      >
        <Input
          size="large"
          prefix={<Search size={16} />}
          placeholder="搜索菜单 / 应用 / 流水线 …  （ESC 关闭）"
          allowClear
        />
      </AutoComplete>
      <div
        style={{
          padding: '8px 4px 0',
          fontSize: 11,
          color: '#64748b',
          display: 'flex',
          gap: 12,
        }}
      >
        <span>↑↓ 导航</span>
        <span>↵ 跳转</span>
        <span>ESC 关闭</span>
      </div>
    </Modal>
  )
}
