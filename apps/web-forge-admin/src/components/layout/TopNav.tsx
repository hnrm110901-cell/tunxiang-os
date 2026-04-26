export function TopNav() {
  return (
    <header style={{
      gridColumn: '1 / -1',
      background: 'var(--ink-950)',
      padding: '0 18px',
      borderBottom: '1px solid var(--border-tertiary)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      fontSize: 12
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ width: 22, height: 22, background: 'var(--ember-500)', borderRadius: 5, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontFamily: 'var(--font-serif)', fontSize: 13, fontWeight: 500 }}>屯</span>
        <span className="h-serif" style={{ fontSize: 13 }}>Forge <span className="ember">Admin</span></span>
        <span className="lbl" style={{ marginLeft: 6, color: 'var(--text-tertiary)' }}>v2.0 · 内部管理后台</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, color: 'var(--text-secondary)' }}>
        <div style={{ background: 'var(--bg-secondary)', border: '0.5px solid var(--border-secondary)', borderRadius: 6, padding: '5px 12px', color: 'var(--text-tertiary)', fontSize: 11, display: 'flex', alignItems: 'center', gap: 6, minWidth: 280 }}>
          ⌕ 全局搜索 商品 / ISV / 订单 / Skill ⌘K
        </div>
        <span className="ember mono" style={{ fontSize: 11 }}>12 待办</span>
        <span style={{ color: 'var(--text-tertiary)' }}>|</span>
        <span style={{ fontSize: 11 }}>Forge Ops · 张工</span>
        <div style={{ width: 24, height: 24, background: 'var(--bg-surface)', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--ember-300)', fontSize: 11 }}>张</div>
      </div>
    </header>
  )
}
