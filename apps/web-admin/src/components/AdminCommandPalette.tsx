/**
 * AdminCommandPalette — Cmd+K 命令面板（Admin 端）
 *
 * v1.0 宪法 §5.3：
 *   - 全局触发：Ctrl+K / Cmd+K
 *   - < 100ms 显示 / < 500ms 响应
 *   - 命令分类：导航 / 系统 / 自定义动作
 *
 * 设计语言：与 Admin AntD ProComponents 一致（Modal + Input + List）
 */
import { useEffect, useState, useRef } from 'react';
import { Modal, Input, List, Tag, Empty } from 'antd';
import type { InputRef } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { useAdminCommandPalette, AdminCommand } from '../hooks/useAdminCommandPalette';

const GROUP_LABELS: Record<string, string> = {
  nav: '导航',
  action: '操作',
  system: '系统',
};

const GROUP_COLORS: Record<string, string> = {
  nav: 'blue',
  action: 'orange',
  system: 'default',
};

export function AdminCommandPalette() {
  const { open, setOpen, query, setQuery, filtered, grouped, execute } = useAdminCommandPalette();
  const inputRef = useRef<InputRef>(null);
  const [activeIdx, setActiveIdx] = useState(0);

  // 打开时聚焦输入框
  useEffect(() => {
    if (open) {
      setActiveIdx(0);
      // 微任务后聚焦，等 modal 渲染
      const t = setTimeout(() => inputRef.current?.focus(), 50);
      return () => clearTimeout(t);
    }
  }, [open]);

  // 键盘导航：↑↓ 切换、Enter 执行
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setActiveIdx(prev => Math.min(prev + 1, filtered.length - 1));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setActiveIdx(prev => Math.max(prev - 1, 0));
      } else if (e.key === 'Enter') {
        e.preventDefault();
        const cmd = filtered[activeIdx];
        if (cmd) execute(cmd);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, filtered, activeIdx, execute]);

  // 重置 activeIdx 当 filtered 变化
  useEffect(() => {
    if (activeIdx >= filtered.length) setActiveIdx(0);
  }, [filtered.length, activeIdx]);

  // 计算扁平化的 index 给键盘导航
  const flatList = filtered;

  return (
    <Modal
      open={open}
      onCancel={() => setOpen(false)}
      footer={null}
      closable={false}
      width={600}
      style={{ top: 100 }}
      styles={{ body: { padding: 0 } }}
      destroyOnClose
      aria-label="命令面板"
    >
      <Input
        ref={inputRef}
        size="large"
        placeholder="搜索命令、页面..."
        value={query}
        onChange={e => setQuery(e.target.value)}
        prefix={<SearchOutlined />}
        style={{ border: 'none', borderRadius: 0, padding: '12px 16px', fontSize: 16 }}
        bordered={false}
        aria-label="命令搜索输入"
      />
      <div style={{ borderTop: '1px solid var(--tx-border)', maxHeight: 400, overflowY: 'auto' }}>
        {flatList.length === 0 ? (
          <Empty description="无匹配命令" style={{ padding: 24 }} />
        ) : (
          (['nav', 'action', 'system'] as const).map(group => {
            const items = grouped[group];
            if (items.length === 0) return null;
            return (
              <div key={group}>
                <div style={{
                  padding: '8px 16px 4px',
                  fontSize: 12,
                  color: 'var(--tx-text-3)',
                  fontWeight: 600,
                  textTransform: 'uppercase',
                  letterSpacing: 0.4,
                }}>
                  {GROUP_LABELS[group]}
                </div>
                <List
                  dataSource={items}
                  renderItem={(cmd: AdminCommand) => {
                    const isActive = flatList[activeIdx]?.id === cmd.id;
                    return (
                      <List.Item
                        onClick={() => execute(cmd)}
                        onMouseEnter={() => setActiveIdx(flatList.findIndex(x => x.id === cmd.id))}
                        role="option"
                        aria-selected={isActive}
                        tabIndex={0}
                        style={{
                          padding: '10px 16px',
                          cursor: 'pointer',
                          background: isActive ? 'var(--tx-primary-light)' : 'transparent',
                          borderBottom: '1px solid var(--tx-bg-2)',
                          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                        }}
                      >
                        <span>
                          <Tag color={GROUP_COLORS[cmd.group]} style={{ marginRight: 8 }}>
                            {GROUP_LABELS[cmd.group]}
                          </Tag>
                          <span style={{ fontWeight: 500 }}>{cmd.title}</span>
                          {cmd.description && (
                            <span style={{ marginLeft: 8, color: 'var(--tx-text-3)', fontSize: 13 }}>
                              {cmd.description}
                            </span>
                          )}
                        </span>
                        {cmd.shortcut && (
                          <kbd style={{
                            padding: '2px 6px', borderRadius: 4,
                            background: 'var(--tx-bg-3)',
                            border: '1px solid var(--tx-border)',
                            fontSize: 11, fontFamily: 'monospace',
                          }}>{cmd.shortcut}</kbd>
                        )}
                      </List.Item>
                    );
                  }}
                />
              </div>
            );
          })
        )}
      </div>
      <div style={{
        padding: '8px 16px',
        borderTop: '1px solid var(--tx-border)',
        fontSize: 12,
        color: 'var(--tx-text-3)',
        display: 'flex', justifyContent: 'space-between',
      }}>
        <span>
          <kbd>↑</kbd> <kbd>↓</kbd> 选择 · <kbd>Enter</kbd> 执行 · <kbd>Esc</kbd> 关闭
        </span>
        <span>{filtered.length} 个命令</span>
      </div>
    </Modal>
  );
}
