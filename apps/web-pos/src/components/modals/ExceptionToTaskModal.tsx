/**
 * 异常转任务弹层 — 将异常事件转为整改任务（E8）
 */
interface Props {
  visible: boolean;
  exceptionTitle: string;
  exceptionType: string;
  onSubmit: (data: { assignee: string; deadline: string; notes: string }) => void;
  onClose: () => void;
}

const ASSIGNEES = ['张明华(店长)', '王大厨(厨师长)', '刘小妹(领班)', '李翠花(收银)'];

export function ExceptionToTaskModal({ visible, exceptionTitle, exceptionType, onSubmit, onClose }: Props) {
  if (!visible) return null;

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
      <div style={{ width: 400, background: '#112228', borderRadius: 12, padding: 24, border: '2px solid #1890ff' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
          <span style={{ fontSize: 24 }}>📋</span>
          <h3 style={{ margin: 0, color: '#1890ff' }}>转为整改任务</h3>
        </div>

        <div style={{ fontSize: 13, color: '#ccc', marginBottom: 12, padding: 10, background: '#0B1A20', borderRadius: 6 }}>
          <div style={{ fontWeight: 'bold' }}>{exceptionTitle}</div>
          <div style={{ fontSize: 11, color: '#666' }}>类型: {exceptionType}</div>
        </div>

        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 12, color: '#999' }}>指派责任人</label>
          <select id="task-assignee" style={{
            width: '100%', padding: 8, marginTop: 4, borderRadius: 6, border: '1px solid #333',
            background: '#0B1A20', color: '#fff', fontSize: 13,
          }}>
            {ASSIGNEES.map(a => <option key={a} value={a}>{a}</option>)}
          </select>
        </div>

        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 12, color: '#999' }}>截止日期</label>
          <input type="date" id="task-deadline" style={{
            width: '100%', padding: 8, marginTop: 4, borderRadius: 6, border: '1px solid #333',
            background: '#0B1A20', color: '#fff', fontSize: 13,
          }} />
        </div>

        <textarea placeholder="备注说明..." id="task-notes" style={{
          width: '100%', height: 60, padding: 8, borderRadius: 6, border: '1px solid #333',
          background: '#0B1A20', color: '#fff', fontSize: 13, resize: 'none', marginBottom: 12,
        }} />

        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={onClose} style={{ flex: 1, padding: 10, background: '#333', color: '#fff', border: 'none', borderRadius: 8, cursor: 'pointer' }}>取消</button>
          <button onClick={() => onSubmit({
            assignee: (document.getElementById('task-assignee') as HTMLSelectElement)?.value || '',
            deadline: (document.getElementById('task-deadline') as HTMLInputElement)?.value || '',
            notes: (document.getElementById('task-notes') as HTMLTextAreaElement)?.value || '',
          })} style={{ flex: 1, padding: 10, background: '#1890ff', color: '#fff', border: 'none', borderRadius: 8, cursor: 'pointer' }}>
            创建任务
          </button>
        </div>
      </div>
    </div>
  );
}
